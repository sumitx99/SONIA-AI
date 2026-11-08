"""Connecting to a user's MCP server: list its tools and call them, with time and size limits."""

import asyncio
import base64
import binascii
import json
import re
from contextlib import asynccontextmanager
from urllib.parse import urljoin, urlsplit

import httpx2
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
import mcp.types as types

from app.mcp_client.safety import UnsafeURLError, assert_public_url
from app.services.tool_evidence import bounded_tool_text

CONNECT_TIMEOUT = 20
CALL_TIMEOUT = 180
MAX_RESULT_CHARS = 8000
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_OUTPUTS = 3
MAX_TOOLS = 40
CLIENT_INFO = types.Implementation(name="Sonia", version="1.0")
_IMAGE_EXTENSIONS = {"apng", "avif", "bmp", "gif", "heic", "heif", "ico", "jfif", "jif",
                     "jpe", "jpeg", "jpg", "jxl", "png", "svg", "tif", "tiff", "webp"}
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


def _headers(connection: dict) -> dict:
    secret = connection.get("secret") or {}
    if connection["auth_type"] == "header":
        # New connections can carry credentials required by gateway MCP servers,
        # such as RapidAPI's host and API-key headers. Read old single-header
        # secrets too so existing connections keep working.
        if secret.get("headers"):
            return dict(secret["headers"])
        if secret.get("header_value"):
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


def server_icon_url(server_info: types.Implementation | None, endpoint: str) -> str | None:
    """Return the server-advertised icon, if it is safe to hand to the browser.

    ``serverInfo.icons`` is MCP metadata, so this works for every compliant server instead
    of keeping a growing list of provider names in the UI. Relative icon URLs are resolved
    against the MCP endpoint; insecure and non-web schemes are intentionally ignored.
    """
    for icon in (getattr(server_info, "icons", None) or []):
        url = urljoin(endpoint, icon.src)
        if urlsplit(url).scheme == "https":
            return url
    return None


async def fetch_tools(connection: dict, auth: httpx2.Auth | None = None, *, include_server_info=False):
    async with open_session(connection, auth) as session:
        listed = await asyncio.wait_for(session.list_tools(), CONNECT_TIMEOUT)
        icon_url = server_icon_url(session.server_info, connection["url"])
    tools = [describe_tool(tool) for tool in listed.tools[:MAX_TOOLS]]
    return (tools, icon_url) if include_server_info else tools


def _is_image_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        extension = parsed.path.rsplit("/", 1)[-1].rsplit(".", 1)[-1].lower()
        return parsed.scheme in {"https", "http"} and bool(parsed.netloc) and extension in _IMAGE_EXTENSIONS
    except ValueError:
        return False


def _image_outputs(result, text: str) -> list[dict]:
    """Return bounded MCP image blocks and direct image-file URLs for the browser."""
    images, seen = [], set()
    total_bytes = 0
    for block in getattr(result, "content", None) or []:
        mime = getattr(block, "mimeType", None) or getattr(block, "mime_type", None)
        data = getattr(block, "data", None)
        if getattr(block, "type", None) == "image" and isinstance(data, str) and isinstance(mime, str) \
                and re.fullmatch(r"image/[a-zA-Z0-9.+-]+", mime):
            if len(data) > (MAX_IMAGE_BYTES * 4 // 3 + 8):
                continue
            try:
                raw = base64.b64decode(data, validate=True)
            except (binascii.Error, ValueError):
                continue
            if not raw or len(raw) > MAX_IMAGE_BYTES or total_bytes + len(raw) > MAX_IMAGE_BYTES:
                continue
            src = f"data:{mime};base64,{data}"
            if src not in seen:
                images.append({"src": src, "alt": "Image returned by connected tool"})
                seen.add(src)
                total_bytes += len(raw)
        if len(images) >= MAX_IMAGE_OUTPUTS:
            return images
    for match in _URL_RE.finditer(text):
        url = match.group(0).rstrip(".,;:!?) ]}")
        nearby = text[max(0, match.start() - 100):match.start()].lower()
        image_labeled = bool(re.search(r"\b(image|photo|picture|generated)\b", nearby))
        if (_is_image_url(url) or image_labeled) and url not in seen:
            images.append({"src": url, "alt": "Image returned by connected tool"})
            seen.add(url)
            if len(images) >= MAX_IMAGE_OUTPUTS:
                break
    return images


def result_text(result) -> tuple[str, bool, list[dict]]:
    """Return bounded tool text, error status, and bounded image outputs."""
    parts = []
    for block in getattr(result, "content", None) or []:
        if isinstance(block, types.TextContent):
            parts.append(block.text)
        elif isinstance(block, types.EmbeddedResource) and getattr(block.resource, "text", None):
            parts.append(block.resource.text)
        else:
            parts.append(f"[{getattr(block, 'type', 'content')} omitted]")
    structured = getattr(result, "structured_content", None)
    # MCP may return a human summary alongside machine-readable data. Use the data
    # as the single citation source rather than silently dropping it or duplicating it.
    if structured is not None:
        value = structured
    elif len(parts) > 1:
        value = []
        for part in parts:
            try:
                value.append(json.loads(part))
            except (ValueError, RecursionError):
                value.append(part)
    else:
        value = parts[0] if parts else "(no content)"
    text = bounded_tool_text(value, MAX_RESULT_CHARS)
    images = _image_outputs(result, text)
    if images:
        text += f"\n[{len(images)} image(s) returned; displayed separately in the chat.]"
    return text, bool(getattr(result, "is_error", False)), images


async def call_tool(session: ClientSession, name: str, arguments: dict) -> tuple[str, bool, list[dict]]:
    result = await asyncio.wait_for(session.call_tool(name, arguments), CALL_TIMEOUT)
    return result_text(result)
