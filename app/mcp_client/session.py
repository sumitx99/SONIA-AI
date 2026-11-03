"""Connecting to a user's MCP server: list its tools and call them, with time and size limits."""

import asyncio
import json
from contextlib import asynccontextmanager

import httpx2
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
import mcp.types as types

from app.mcp_client.safety import UnsafeURLError, assert_public_url

CONNECT_TIMEOUT = 20
CALL_TIMEOUT = 30
MAX_RESULT_CHARS = 8000
MAX_TOOLS = 40
CLIENT_INFO = types.Implementation(name="Sonia", version="1.0")


def _headers(connection: dict) -> dict:
    secret = connection.get("secret") or {}
    if connection["auth_type"] == "header" and secret.get("header_value"):
        return {secret.get("header_name") or "Authorization": secret["header_value"]}
    return {}


@asynccontextmanager
async def open_session(connection: dict, auth: httpx2.Auth | None = None):
    """An initialized MCP session to the connection's server (URL re-checked on every connect)."""
    url = await assert_public_url(connection["url"])
    timeout = httpx2.Timeout(CONNECT_TIMEOUT, read=CALL_TIMEOUT)
    async with create_mcp_http_client(headers=_headers(connection), timeout=timeout, auth=auth) as http:
        # Every request is checked, not just the first: OAuth discovery and token endpoints
        # come from the server's metadata and could otherwise point at internal addresses.
        http.event_hooks["request"].append(_guard_request)
        async with streamable_http_client(url, http_client=http) as (read, write):
            async with ClientSession(read, write, client_info=CLIENT_INFO) as session:
                await asyncio.wait_for(session.initialize(), CONNECT_TIMEOUT)
                yield session


async def _guard_request(request: httpx2.Request) -> None:
    try:
        await assert_public_url(str(request.url))
    except UnsafeURLError as error:
        raise UnsafeURLError(f"Blocked a request to {request.url.host}: {error}") from None


def describe_tool(tool: types.Tool) -> dict:
    hints = tool.annotations
    return {
        "name": tool.name,
        "title": tool.title or (hints.title if hints else None) or tool.name,
        "description": (tool.description or "")[:1000],
        "read_only": bool(hints and hints.read_only_hint),
        "destructive": bool(hints and hints.destructive_hint),
        "input_schema": tool.input_schema or {"type": "object", "properties": {}},
    }


async def fetch_tools(connection: dict, auth: httpx2.Auth | None = None) -> list[dict]:
    async with open_session(connection, auth) as session:
        listed = await asyncio.wait_for(session.list_tools(), CONNECT_TIMEOUT)
    return [describe_tool(tool) for tool in listed.tools[:MAX_TOOLS]]


def result_text(result) -> tuple[str, bool]:
    """A tool result as plain text for the model (truncated), and whether it is an error."""
    parts = []
    for block in getattr(result, "content", None) or []:
        if isinstance(block, types.TextContent):
            parts.append(block.text)
        elif isinstance(block, types.EmbeddedResource) and getattr(block.resource, "text", None):
            parts.append(block.resource.text)
        else:
            parts.append(f"[{getattr(block, 'type', 'content')} omitted]")
    structured = getattr(result, "structured_content", None)
    if structured and not parts:
        parts.append(json.dumps(structured, ensure_ascii=False))
    text = "\n".join(parts) or "(no content)"
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + "\n…[truncated]"
    return text, bool(getattr(result, "is_error", False))


async def call_tool(session: ClientSession, name: str, arguments: dict) -> tuple[str, bool]:
    result = await asyncio.wait_for(session.call_tool(name, arguments), CALL_TIMEOUT)
    return result_text(result)
