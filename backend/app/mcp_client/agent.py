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
import json
import logging
import re
import uuid

import requests
from fastapi.concurrency import iterate_in_threadpool

from app.services.llm import (READ_WEB_PAGE_TOOL, URL_CONTEXT, WEB_SEARCH_TOOL, conversation_turns, google_search_ready, search_web,
                              stream_gemini_parts, web_search_available, stream_tool_backup,
                              backup_configured, gemini_unavailable)
from app.services.web_activity import WebActivity, requested_urls, safe_url
from app.services.source_reader import read_source
from app.services.page_rendering import render_page
from app.services.images.web_images import IMAGE_SEARCH_TOOL, configured as image_search_configured, search_and_store
from app.mcp_client import store
from app.mcp_client.oauth import provider_for, needs_reauthorization
from app.mcp_client.session import call_tool, open_session

logger = logging.getLogger(__name__)

MAX_ROUNDS = 5
MAX_TOOLS = 64
MAX_SOURCES = 10
MAX_DIRECT_PAGES = 3
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
    """A tool's input schema as Gemini accepts it.

    Gemini rejects schemas whose $refs loop back on themselves (MCP servers such as Zapier use one
    for "any JSON value"). Local $defs are inlined, and a reference that would loop becomes an
    open schema ({}), which accepts any value just like the loop did.
    """
    schema = dict(schema or {})
    definitions = {**schema.pop("definitions", {}), **schema.pop("$defs", {})}

    def inline(node, resolving):
        if isinstance(node, list):
            return [inline(item, resolving) for item in node]
        if not isinstance(node, dict):
            return node
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith(("#/$defs/", "#/definitions/")):
            name = ref.rsplit("/", 1)[-1]
            if name in resolving or name not in definitions:
                return {}
            return inline(definitions[name], resolving | {name})
        return {key: inline(value, resolving) for key, value in node.items()
                if key not in ("$schema", "$defs", "definitions")}

    schema = inline(schema, frozenset())
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
    if connection.get("unavailable_reason"):
        return connection["unavailable_reason"], True
    try:
        auth = provider_for(user_id, connection) if connection["auth_type"] == "oauth" else None
        async with open_session(connection, auth) as session:
            result = await call_tool(session, tool["name"], arguments)
        # A refreshed OAuth token can make an earlier failure obsolete. Avoid leaving
        # the Settings page stuck showing a warning once the server is usable again.
        if connection.get("last_error"):
            connection["last_error"] = None
            try:
                await store.update_connection(user_id, connection["id"], last_error=None)
            except Exception:
                logger.info("Could not clear the connection error after a successful tool call")
        return result
    except Exception as error:
        if needs_reauthorization(error):
            message = "Sign in to this server again from Settings → Connections. The OAuth session needs reauthorization; no action was executed. Do not retry until reconnected."
            connection["unavailable_reason"] = message
            try:
                await store.update_connection(user_id, connection["id"], last_error=message)
            except Exception:
                logger.info("Could not save the connection's reauthorization status")
            return message, True
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
    question_urls = requested_urls(query)
    attempted_pages = set()
    web = WebActivity()
    image_searches, image_count = 0, 0
    backend = {"backup": False}

    def iterate_model_parts(offered):
        if backend["backup"]:
            yield from stream_tool_backup(contents, offered, allow_web=round_number < MAX_ROUNDS)
            return
        generated = False
        try:
            for part in stream_gemini_parts(contents, offered):
                generated = True
                yield part
        except Exception as error:
            # A rejected catalog can still be usable on the backup model. Switch before
            # the first round produces anything, so native Gemini turns need no translation.
            rejected_catalog = (round_number == 0 and bool(declarations) and
                                isinstance(error, requests.HTTPError) and error.response is not None and
                                error.response.status_code == 400)
            if generated or not (gemini_unavailable(error) or rejected_catalog) or not backup_configured():
                raise
            backend["backup"] = True
            # Keep the connected tools; their execution and approvals remain in this loop.
            yield from stream_tool_backup(contents, offered, allow_web=round_number < MAX_ROUNDS)
    for round_number in range(MAX_ROUNDS + 1):
        # The last round offers no tools, so the model has to answer with what it has. While
        # Google Search is paused, web search runs through the web_search tool instead.
        offered = []
        contents.final_answer_only = round_number == MAX_ROUNDS
        if round_number < MAX_ROUNDS:
            offered = declarations + ([WEB_SEARCH_TOOL]
                                      if (question_urls or not google_search_ready()) and web_search_available() else [])
            if URL_CONTEXT and question_urls - attempted_pages and len(attempted_pages) < MAX_DIRECT_PAGES:
                offered = offered + [READ_WEB_PAGE_TOOL]
            if image_search_configured() and image_searches < 2 and image_count < 3:
                offered = offered + [IMAGE_SEARCH_TOOL]
        model_parts, calls, search_refused = [], [], False
        try:
            async for part in iterate_in_threadpool(iterate_model_parts(offered)):
                if "searchUnavailable" in part:
                    search_refused = True
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
                    part["functionCall"].setdefault("id", uuid.uuid4().hex)
                    calls.append(part["functionCall"])
                elif part.get("text") and not part.get("thought"):
                    yield "delta", {"text": part["text"]}
        except requests.HTTPError as error:
            # Gemini rejects the whole request when one connected tool's schema is invalid. That
            # happens before anything is generated, so ask again without the connected tools.
            if not backend["backup"] and error.response is not None and error.response.status_code == 400 and declarations:
                logger.warning("Gemini rejected the connected tools; answering without them: %s",
                               error.response.text[:300])
                declarations = []
                for connection in {item[0]["id"]: item[0] for item in registry.values()}.values():
                    yield "tool_call", {"id": f"connection-{connection['id']}", "server": connection["name"],
                        "tool": "connection_status", "title": "Tools unavailable", "status": "error",
                        "summary": "The connected tools could not be loaded for this answer. No action was executed."}
                continue
            for event in web.finish(failed=True):
                yield "tool_call", event
            raise
        except Exception:
            for event in web.finish(failed=True):
                yield "tool_call", event
            raise
        for event in web.finish():
            yield "tool_call", event
        if search_refused:
            continue  # nothing was generated; ask again with the web_search tool on offer
        if not calls or contents.final_answer_only:
            break
        contents.append({"role": "model", "parts": model_parts})
        responses = []
        for call in calls:
            name, arguments = call.get("name", ""), call.get("args") or {}
            entry = registry.get(name)
            source_id = None
            page_image = None
            search_url = safe_url(str(arguments.get("query", "")).strip())
            exact_url_search = name == WEB_SEARCH_TOOL["name"] and URL_CONTEXT and search_url in question_urls
            if entry is None and name == IMAGE_SEARCH_TOOL["name"]:
                event = {"id": f"web-images-{uuid.uuid4().hex[:8]}", "server": "Web", "tool": "image_search",
                         "title": "Searching web images", "arguments": {"query": str(arguments.get("query", ""))[:250]}}
                yield "tool_call", {**event, "status": "running"}
                try:
                    if not any(tool["name"] == IMAGE_SEARCH_TOOL["name"] for tool in offered):
                        raise ValueError("Image search is unavailable for this turn")
                    image_searches += 1
                    requested = arguments.get("limit", 1)
                    if isinstance(requested, bool) or not isinstance(requested, int) or requested < 1:
                        raise ValueError("Choose a valid image count")
                    images = await search_and_store(user_id, arguments.get("query"), min(requested, 3 - image_count))
                    image_count += len(images)
                    text, is_error = "No suitable reusable images were found.", False
                    if images:
                        yield "web_images", {"images": images}
                        source_id = f"I{event['id']}"
                        # Signed URLs are only for the UI, never included in model/tool context.
                        text = json.dumps([{key: image[key] for key in ("image_id", "title", "source_url", "author", "license", "license_url")}
                                           for image in images], ensure_ascii=False)
                        yield "evidence", {"sources": [{"id": source_id, "kind": "tool", "title": "Web image search", "text": text}]}
                        for image in images:
                            if len(sources) < MAX_SOURCES:
                                sources.setdefault(image["source_url"], {"title": image["title"], "url": image["source_url"]})
                        yield "sources", {"sources": list(sources.values())}
                except Exception:
                    logger.info("Web image search failed", exc_info=True)
                    text, is_error = "Web images could not be searched or saved. No image is available; do not invent one.", True
                yield "tool_call", {**event, "status": "error" if is_error else "done",
                    "title": "Web images unavailable" if is_error else "Web image search complete",
                    "summary": "No images were saved." if is_error else f"{len(images)} image previews saved."}
            elif entry is None and (name == READ_WEB_PAGE_TOOL["name"] or exact_url_search):
                url = search_url if exact_url_search else safe_url(arguments.get("url"))
                if READ_WEB_PAGE_TOOL not in offered or url not in question_urls or url in attempted_pages or len(attempted_pages) >= MAX_DIRECT_PAGES:
                    text, is_error = "Only unread public links supplied in the current request may be opened.", True
                else:
                    attempted_pages.add(url)
                    event = {"id": f"web-page-{uuid.uuid4().hex[:8]}", "server": "Web",
                             "tool": READ_WEB_PAGE_TOOL["name"],
                             "title": "Reading web page", "arguments": {"url": url}}
                    yield "tool_call", {**event, "status": "running"}
                    try:
                        page_text = (await asyncio.to_thread(read_source, url, include_head=False))[:6000]
                    except Exception:
                        logger.info("The requested public page could not be read")
                        page_text = ""
                    visual = exact_url_search or arguments.get("visual") is True or not page_text
                    if visual:
                        try:
                            rendered_text, page_image = await asyncio.to_thread(
                                render_page, url, screenshot=not backend["backup"])
                            page_text = rendered_text or page_text
                        except requests.HTTPError as error:
                            status = error.response.status_code if error.response is not None else "unknown"
                            logger.warning("Cloudflare browser request failed (HTTP %s)", status)
                        except (requests.RequestException, ValueError, OSError) as error:
                            logger.warning("Cloudflare browser request failed (%s)", type(error).__name__)
                    is_error = not page_text and not page_image
                    text = f"Source URL: {url}\nPage text:\n{page_text}" if page_text else (
                        "The requested page did not return readable text. If asked to rate the page, "
                        "explain this limitation and ask for screenshots. Do not search for reviews as a substitute.")
                    if page_image and not page_text:
                        text = f"Source URL: {url}\nOnly a desktop viewport screenshot is available."
                    elif visual and page_text and not page_image:
                        text += "\nNo screenshot is available. Limit the review to the readable content."
                    if not is_error:
                        link = {"url": url, "title": url}
                        if len(sources) < MAX_SOURCES:
                            sources.setdefault(url, link)
                            yield "sources", {"sources": list(sources.values())}
                        if page_text:
                            yield "evidence", {"sources": [{**link, "kind": "web", "text": page_text}]}
                    yield "tool_call", {**event, "status": "error" if is_error else "done",
                                        "title": "Page could not be read" if is_error else "Read web page"}
            elif entry is None and name == WEB_SEARCH_TOOL["name"]:
                search_query = str(arguments.get("query") or query)[:500]
                event = {"id": f"web-search-{uuid.uuid4().hex[:8]}", "server": "Web", "tool": "web_search",
                         "title": "Searching the web", "arguments": {"query": search_query}}
                yield "tool_call", {**event, "status": "running"}
                try:
                    text, links, pages = await asyncio.to_thread(search_web, search_query)
                    is_error = False
                except Exception:
                    logger.info("Web search failed", exc_info=True)
                    text, is_error, links, pages = "Web search is unavailable right now.", True, [], []
                for link in links:
                    if len(sources) < MAX_SOURCES:
                        sources.setdefault(link["url"], link)
                if links:
                    yield "sources", {"sources": list(sources.values())}
                if pages:
                    yield "evidence", {"sources": [{**page, "kind": "web"} for page in pages]}
                yield "tool_call", {**event, "status": "error" if is_error else "done",
                                    "title": "Web search unavailable" if is_error else "Searched the web",
                                    "summary": None if is_error else f"{len(links)} source links returned."}
            elif entry is None:
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
                    if not is_error:
                        source_id = f"T{event['id'][:8]}"
                        yield "evidence", {"sources": [{"id": source_id, "kind": "tool",
                            "title": f"{connection['name']} · {tool['title']}", "text": text[:12000]}]}
                    yield "tool_call", {**event, "status": "error" if is_error else "done",
                                        "summary": text[:280]}
            response = {"name": name, "response": {
                # Marked so the model treats it as data, never as instructions.
                "source": "external tool (untrusted data)", "is_error": is_error, "result": text,
                **({"source_id": source_id} if source_id else {})}}
            if call.get("id"):
                response["id"] = call["id"]
            if page_image:
                response["response"]["desktop_viewport"] = {"$ref": "desktop.jpg"}
                response["response"]["page_text_available"] = bool(page_text)
                response["parts"] = [{"inlineData": {"mimeType": "image/jpeg",
                                                     "displayName": "desktop.jpg", "data": page_image}}]
            responses.append({"functionResponse": response})
        contents.append({"role": "user", "parts": responses})
