"""Answering with tools: Gemini may read the web and call tools from the user's MCP connections.

Each tool follows the user's policy for it: "allow" runs at once, "ask" pauses the answer
until the user approves in chat (POST /chat/approvals/{id}), "off" is never offered.
Progress is reported as stream events for the chat UI:
  ("tool_call", {...status: running | awaiting_approval | done | error | denied})
  ("approval_required", {...})
  ("delta", {"text"})
  ("sources", {"sources": [{"title", "url"}]})   web pages the answer used, once at the end
"""

import asyncio
import logging
import re
import uuid

from fastapi.concurrency import iterate_in_threadpool

from app.services.llm import stream_gemini_parts, conversation_turns, GeminiSearchUnavailable
from app.services.web_search import needs_web
from app.services.web_activity import WebActivity, safe_url
from app.mcp_client import store
from app.mcp_client.oauth import provider_for
from app.mcp_client.session import call_tool, open_session

logger = logging.getLogger(__name__)

MAX_ROUNDS = 5
MAX_TOOLS = 64
MAX_SOURCES = 10
APPROVAL_TIMEOUT = 120
# approval id -> (user id, future resolved with True/False). One API instance, so in memory.
_approvals: dict[str, tuple[str, asyncio.Future]] = {}


def resolve_approval(user_id: str, approval_id: str, approved: bool) -> bool:
    """Records the user's decision; False if there is no such pending request for them."""
    pending = _approvals.get(approval_id)
    if not pending or pending[0] != user_id or pending[1].done():
        return False
    pending[1].set_result(approved)
    return True


def _function_name(index: int, tool_name: str) -> str:
    # Gemini allows [a-zA-Z0-9_.-], at most 64 characters, starting with a letter or "_".
    return f"c{index}__{re.sub(r'[^a-zA-Z0-9_.-]', '_', tool_name)}"[:64]


def _clean_schema(schema: dict) -> dict:
    schema = {key: value for key, value in (schema or {}).items() if key != "$schema"}
    schema.setdefault("type", "object")
    return schema


async def available_tools(user_id: str) -> tuple[list[dict], dict]:
    """Gemini function declarations for the user's enabled tools, and how to reach each one."""
    connections = await store.list_connections(user_id, enabled_only=True, with_secret=True)
    declarations, registry = [], {}
    for index, connection in enumerate(connections):
        for tool in connection["tools"]:
            if tool["policy"] == "off" or len(declarations) >= MAX_TOOLS:
                continue
            name = _function_name(index, tool["name"])
            registry[name] = (connection, tool)
            declarations.append({
                "name": name,
                "description": f"[{connection['name']}] {tool['title']}. {tool['description']}"[:1024],
                "parametersJsonSchema": _clean_schema(tool["input_schema"]),
            })
    return declarations, registry


async def _run_tool(user_id: str, connection: dict, tool: dict, arguments: dict) -> tuple[str, bool]:
    try:
        auth = provider_for(user_id, connection) if connection["auth_type"] == "oauth" else None
        async with open_session(connection, auth) as session:
            return await call_tool(session, tool["name"], arguments)
    except Exception as error:
        logger.info("Tool %s on %s failed: %r", tool["name"], connection["url"], error)
        return "The tool could not be reached or failed to run.", True


def _add_sources(grounding: dict, sources: dict) -> None:
    for chunk in grounding.get("groundingChunks") or []:
        web = chunk.get("web") or {}
        url = web.get("uri") or ""
        if safe_url(url) and url not in sources and len(sources) < MAX_SOURCES:
            sources[url] = {"title": (web.get("title") or url)[:200], "url": url[:2048]}


async def answer_with_tools(user_id: str, query: str, context: str, declarations: list, registry: dict, history=None):
    """Yields (event, data) while answering; text arrives as "delta" events."""
    contents = conversation_turns(query, context, history)
    sources: dict[str, dict] = {}
    web = WebActivity()
    for round_number in range(MAX_ROUNDS + 1):
        # The last round offers no tools, so the model has to answer with what it has.
        offered = declarations if round_number < MAX_ROUNDS else []
        model_parts, calls = [], []
        try:
            async for part in iterate_in_threadpool(stream_gemini_parts(contents, offered)):
                if "webStatus" in part:
                    for event in web.finish(failed=True):
                        yield "tool_call", event
                    yield "tool_call", {"id": "web-search-unavailable", "server": "Web", "tool": "google_search",
                                        "title": "Web search unavailable", "status": "error",
                                        "summary": "The search-enabled request was rate-limited. Retrying without Google Search."}
                    if needs_web(query, history):
                        raise GeminiSearchUnavailable("Gemini search was rate-limited")
                    continue
                if "groundingMetadata" in part:
                    grounding = part["groundingMetadata"]
                    _add_sources(grounding, sources)
                    queries = grounding.get("webSearchQueries") or []
                    if queries and not any(call["tool"] == "google_search" for call in web.calls.values()):
                        yield "tool_call", {"id": f"web-grounding-{round_number}", "server": "Web", "tool": "google_search",
                                            "title": "Searched the web", "status": "done",
                                            "arguments": {"queries": [q[:500] for q in queries[:5] if isinstance(q, str)]}}
                    if sources:
                        yield "sources", {"sources": list(sources.values())}
                    continue
                if "urlContextMetadata" in part:
                    for index, item in enumerate(part["urlContextMetadata"].get("urlMetadata") or []):
                        url = safe_url(item.get("retrievedUrl"))
                        if not url:
                            continue
                        success = item.get("urlRetrievalStatus") == "URL_RETRIEVAL_STATUS_SUCCESS"
                        yield "tool_call", {"id": f"web-page-{round_number}-{index}", "server": "Web", "tool": "url_context",
                                            "title": "Read web page" if success else "Page could not be read",
                                            "arguments": {"url": url}, "status": "done" if success else "error"}
                        if success and len(sources) < MAX_SOURCES:
                            sources.setdefault(url, {"title": url, "url": url})
                    if sources:
                        yield "sources", {"sources": list(sources.values())}
                    continue
                model_parts.append(part)
                for name, response in (("toolCall", False), ("toolResponse", True)):
                    if name in part:
                        event = web.event(part[name], response, round_number)
                        if event:
                            yield "tool_call", event
                if "functionCall" in part:
                    calls.append(part["functionCall"])
                elif part.get("text") and not part.get("thought"):
                    yield "delta", {"text": part["text"]}
        except Exception:
            for event in web.finish(failed=True):
                yield "tool_call", event
            raise
        for event in web.finish():
            yield "tool_call", event
        if not calls:
            break
        contents.append({"role": "model", "parts": model_parts})
        responses = []
        for call in calls:
            name, arguments = call.get("name", ""), call.get("args") or {}
            entry = registry.get(name)
            if entry is None:
                text, is_error = "Unknown tool.", True
            else:
                connection, tool = entry
                event = {"id": uuid.uuid4().hex, "server": connection["name"], "tool": tool["name"],
                         "title": tool["title"], "arguments": arguments}
                approved = True
                if tool["policy"] == "ask":
                    future = asyncio.get_running_loop().create_future()
                    _approvals[event["id"]] = (user_id, future)
                    yield "tool_call", {**event, "status": "awaiting_approval"}
                    yield "approval_required", event
                    try:
                        approved = await asyncio.wait_for(future, APPROVAL_TIMEOUT)
                    except asyncio.TimeoutError:
                        approved = False
                    finally:
                        _approvals.pop(event["id"], None)
                if not approved:
                    text, is_error = "The user declined this action. Do not try it again.", False
                    yield "tool_call", {**event, "status": "denied"}
                else:
                    yield "tool_call", {**event, "status": "running"}
                    text, is_error = await _run_tool(user_id, connection, tool, arguments)
                    yield "tool_call", {**event, "status": "error" if is_error else "done",
                                        "summary": text[:280]}
            response = {"name": name, "response": {
                # Marked so the model treats it as data, never as instructions.
                "source": "external tool (untrusted data)", "is_error": is_error, "result": text}}
            if call.get("id"):
                response["id"] = call["id"]
            responses.append({"functionResponse": response})
        contents.append({"role": "user", "parts": responses})
