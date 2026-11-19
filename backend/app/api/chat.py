"""/chat, /chat/stream and tool approvals: answering the user's questions."""

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.concurrency import iterate_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from requests.exceptions import HTTPError

from app.core.auth import current_user
from app.mcp_client.agent import answer_with_tools, available_tools, resolve_approval
from app.services.context import answer_context
from app.services.chat_memory import parse_history
from app.api.projects import project_document_ids
from app.services.images.image_storage import valid_chat_id
from app.services.memory import (MemoryTurn, chat_project, memory_context, memory_enabled, schedule_summary,
                                 scope_for)
from app.services.genui import GenUIStream, supported_chart
from app.services.answer_verification import check_citations
from app.services.llm import (NO_ANSWER, BackupUnavailable, backup_configured, gemini_access_denied, gemini_unavailable,
                              stream_backup_answer, ToolSelectionUnavailable, WebSearchUnavailable)
from app.services.web_activity import requested_urls

logger = logging.getLogger(__name__)
router = APIRouter()


class AnswerSetup:
    """The chat's project and memory, as they apply to one answer."""

    def __init__(self, background: str = "", memory: MemoryTurn | None = None, voice: str | None = None):
        self.background, self.memory, self.voice = background, memory, voice


VOICE_INSTRUCTION = (
    "Live voice call: the user is talking to you out loud and hears your reply spoken. Sound like a warm, "
    "friendly person on a call, not a textbook or a translation: short natural sentences, contractions, a "
    "brief reaction to what they said when it fits, one idea at a time, and a short follow-up question when "
    "it helps the conversation. Usually one to three sentences. No lists, tables, headings, code or URLs "
    "unless they ask. Reply in the same language and mix the user spoke (English, Hindi or Hinglish). "
    "For facts from documents or the web, keep the required citations; the chat shows them.")
# The assistant's name in a voice call follows the chosen voice.
VOICE_NAMES = {"male": "Bheem", "female": "Sonia"}


def _voice_choice(value: str | None) -> str | None:
    """The voice of a spoken turn. Older app versions sent voice=true; they get the default voice,
    so a frontend and backend deployed a few minutes apart never reject each other's requests."""
    if not value or value.strip().lower() in ("false", "0", ""):
        return None
    value = value.strip().lower()
    return value if value in VOICE_NAMES else "female"


def _voice_instruction(voice: str | None) -> str:
    if not voice:
        return ""
    name = VOICE_NAMES.get(voice, "Sonia")
    return VOICE_INSTRUCTION + f" In this call your name is {name}; introduce yourself as {name} when asked."


async def _answer_setup(user_id, chat_id, project_id, document_ids, scope_documents, voice=None):
    voice = _voice_choice(voice)
    """Adds the project's files to the searched documents, and its instructions and memory to the prompt.

    Memory problems never block an answer: it is then given without memory.
    """
    if not valid_chat_id(chat_id) or not valid_chat_id(project_id):
        raise HTTPException(422, "Invalid conversation or project ID")
    try:
        project = await chat_project(user_id, chat_id, project_id)
    except Exception:
        logger.exception("Could not load the chat's project")
        return document_ids, AnswerSetup(_voice_instruction(voice), voice=voice)
    background = [_voice_instruction(voice)] if voice else []
    if project:
        if scope_documents:
            document_ids = list(document_ids or []) + await project_document_ids(user_id, project["id"])
        if project["instructions"].strip():
            background.append(
                f"Project \"{project['name']}\": instructions the user wrote for every chat in this project. "
                "Follow them unless the current request says otherwise:\n" + project["instructions"].strip())
    memory = None
    try:
        if await memory_enabled(user_id):
            scope = scope_for(project)
            memory = MemoryTurn(user_id, scope, chat_id, True)
            block = await memory_context(user_id, scope)
            if block:
                background.append(block)
            schedule_summary(user_id, scope)
    except Exception:
        logger.exception("Memory is unavailable for this answer")
    return document_ids, AnswerSetup("\n\n".join(background), memory, voice)


@router.post("/chat", tags=["Chat"])
async def chat(query: str = Form(...), document_ids: list[int] | None = Form(None),
               scope_documents: bool = Form(False), include_images: bool = Form(False),
               user_id: str = Depends(current_user), history: str | None = Form(None),
               chat_id: str | None = Form(None), project_id: str | None = Form(None),
               voice: str | None = Form(None)):
    turns = parse_history(history)
    document_ids, setup = await _answer_setup(user_id, chat_id, project_id, document_ids, scope_documents, voice)
    try:
        logger.info(f"Received query: '{query}'")
        context, meta = await answer_context(query, document_ids, scope_documents, include_images, user_id)
        declarations, registry = await _load_tools(user_id)
        answer, citations, web_images, ui_spec = "", [], [], None
        ui_incomplete = False
        async for name, data in _answer_events(user_id, query, context, declarations, registry, turns, setup):
            if name == "citations":
                answer, citations = data["answer"], data["citations"]
            elif name == "ui_spec":
                ui_spec = data["spec"]
                ui_incomplete = data.get("incomplete", False)
            elif name == "web_images":
                web_images.extend(data["images"])
        logger.info("Generated LLM response.")
        return {"query": query, "answer": answer or NO_ANSWER, "citations": citations, "web_images": web_images, "ui_spec": ui_spec, "ui_incomplete": ui_incomplete, **meta}

    except HTTPError as e:
        logger.exception("The AI service failed during chat")
        raise HTTPException(status_code=503, detail=_failure_message(e))
    except Exception:
        logger.exception("An unexpected error occurred during chat")
        raise HTTPException(status_code=500, detail="Something went wrong on our side. Please try again.")


def _failure_message(error: Exception) -> str:
    if isinstance(error, ToolSelectionUnavailable):
        return "Sonia couldn’t select the connected tools for this request. Please retry your question."
    if isinstance(error, WebSearchUnavailable):
        return "Web search could not be completed right now. Please try again later; current information could not be verified."
    if gemini_access_denied(error):
        return "Sonia couldn't access the AI provider. Check the backend's model credentials and permissions."
    if isinstance(error, BackupUnavailable) or gemini_unavailable(error):
        return "Sonia's AI models are busy or have used up today's free quota. Please try again in a little while."
    return "The answer was interrupted. Please try again."


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/chat/stream", tags=["Chat"])
async def chat_stream(query: str = Form(...), document_ids: list[int] | None = Form(None),
                      scope_documents: bool = Form(False), include_images: bool = Form(False),
                      user_id: str = Depends(current_user), history: str | None = Form(None),
                      chat_id: str | None = Form(None), project_id: str | None = Form(None),
                      voice: str | None = Form(None)):
    """Like /chat, but streams the answer as server-sent events while Gemini writes it.

    Events: `meta` (images and status, once), `delta` ({"text"}, repeatedly), `inline_citation`
    (a provider-grounded answer segment and source link, as grounding metadata arrives), `citations`
    ({"answer", "citations"}: the final text without its citations block, and each checked
    citation), then `done`, or `error` ({"detail"}) if the answer breaks off part-way. The model
    may emit validated layout snapshots in `ui_spec` events and read web pages listed in `sources`.
    With MCP connections it may also call tools, reported as `tool_call` and, for tools that need
    consent, `approval_required`. If Gemini is out of quota or
    down before anything was shown, a backup model answers instead.
    """
    turns = parse_history(history)
    document_ids, setup = await _answer_setup(user_id, chat_id, project_id, document_ids, scope_documents, voice)
    try:
        logger.info(f"Received streaming query: '{query}'")
        # Retrieval errors happen before any bytes are sent, so they keep normal status codes.
        context, meta = await answer_context(query, document_ids, scope_documents, include_images, user_id)
    except HTTPError as e:
        # Provider error bodies stay in the logs; users get a plain explanation.
        logger.exception("Retrieval failed")
        raise HTTPException(status_code=503, detail=_failure_message(e))
    except Exception:
        logger.exception("An unexpected error occurred during retrieval")
        raise HTTPException(status_code=500, detail="Something went wrong on our side. Please try again.")

    declarations, registry = await _load_tools(user_id)

    async def events():
        yield _sse("meta", meta)
        try:
            async for name, data in _answer_events(user_id, query, context, declarations, registry, turns, setup):
                yield _sse(name, data)
            yield _sse("done", {})
        except Exception as error:
            logger.exception("Generating the answer failed")
            yield _sse("error", {"detail": _failure_message(error)})

    # No buffering by proxies, so each piece reaches the browser as soon as it is written.
    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _load_tools(user_id):
    try:
        return await available_tools(user_id)
    except Exception:
        logger.exception("Couldn't load MCP connections; answering without tools")
        return [], {}


async def _answer_events(user_id, query, context, declarations, registry, turns, setup=None):
    """Stream prose and UI previews, then checked citations and the final UI spec."""
    setup = setup or AnswerSetup()
    extra = {**({"background": setup.background} if setup.background else {}),
             **({"memory": setup.memory} if setup.memory else {}),
             # Voice replies favour a fast first word over everything else.
             **({"fast": True} if setup.voice else {})}
    draft, sources, evidence = [], {}, []
    ui = GenUIStream()

    def answer_text(events):
        text = []

        def flush():
            if text:
                piece = "".join(text)
                draft.append(piece)
                text.clear()
                yield "delta", {"text": piece}

        for name, data in events:
            if name == "delta":
                text.append(data["text"])
            else:
                yield from flush()
                yield name, data
        yield from flush()

    linked_pages = requested_urls(query)
    failed_pages = set()
    page_unreadable = ("I couldn’t read the content at the link you shared. "
                       "Share a screenshot or the page text so I can review it.")
    shown = False  # text or a non-web tool step the user has already seen
    try:
        async for name, data in answer_with_tools(user_id, query, context, declarations, registry,
                                                  **({"history": turns} if turns else {}), **extra):
            if name == "evidence":
                evidence.extend(data["sources"])
                continue
            if name == "delta":
                shown = True
                for event in answer_text(ui.feed(data["text"])):
                    yield event
                continue
            if name == "inline_citation":
                position = ui.position(data["position"])
                if position is None:
                    continue
                data = {**data, "position": position}
            elif name == "sources":
                sources.update({item["url"]: item for item in data["sources"]})
            elif name == "tool_call" and data.get("tool") in {"read_web_page", "url_context"}:
                url = (data.get("arguments") or {}).get("url")
                if isinstance(url, str) and url in linked_pages:
                    if data.get("status") == "error":
                        failed_pages.add(url)
                    elif data.get("status") == "done":
                        failed_pages.discard(url)
            shown = shown or (name == "tool_call" and data.get("server") != "Web")
            yield name, data
    except Exception as error:
        if (not shown and linked_pages and linked_pages <= failed_pages
                and (isinstance(error, BackupUnavailable) or gemini_unavailable(error))):
            yield "delta", {"text": page_unreadable}
            return
        # A backup may answer only if nothing was shown and no external action ran.
        # Connected-tool fallbacks belong to the agent, which preserves the registry.
        # Never replace them with a plain answer path that has no connected tools.
        if declarations or shown or not gemini_unavailable(error) or not backup_configured():
            raise
        logger.warning("Gemini unavailable (%s); answering with a backup model", error)
        backup = stream_backup_answer(query, context, *([turns] if turns else []),
                                      **({"background": setup.background} if setup.background else {}))
        async for kind, value in iterate_in_threadpool(backup):
            if kind == "model":
                logger.info("Backup model %s is answering", value)
            elif kind == "evidence":
                evidence.extend(value["sources"])
            elif kind == "text":
                for event in answer_text(ui.feed(value)):
                    yield event
            else:
                if kind == "sources":
                    sources.update({item["url"]: item for item in value["sources"]})
                yield kind, value
    for event in answer_text(ui.finish()):
        yield event
    if not "".join(draft).strip():
        if ui.seen_ui:
            yield "ui_spec", {"spec": None}
        message = page_unreadable if linked_pages and linked_pages <= failed_pages else NO_ANSWER
        yield "delta", {"text": message}
        return
    answer, citations = await asyncio.to_thread(check_citations, "".join(draft), context,
                                                list(sources.values()), evidence)
    yield "citations", {"answer": answer, "citations": citations}
    if ui.seen_ui:
        quotes = {item["n"]: item["quote"] for item in citations if item["verified"]}
        user_text = [query, *(turn["content"] for turn in turns if turn["sender"] == "user")]
        spec = (ui.spec.snapshot(lambda chart: supported_chart(chart, quotes, user_text))
                if ui.complete else None)
        payload = {"spec": spec}
        if ui.dropped or not ui.complete:
            # Whatever was valid is still shown; the flag tells the client some of it was lost.
            payload["incomplete"] = True
        yield "ui_spec", payload


class ApprovalInput(BaseModel):
    approve: bool


@router.post("/chat/approvals/{approval_id}", tags=["Chat"])
async def decide_tool_call(approval_id: str, payload: ApprovalInput, user_id: str = Depends(current_user)):
    """Approve or decline a tool call that a streaming answer is waiting on."""
    if not resolve_approval(user_id, approval_id, payload.approve):
        raise HTTPException(status_code=404, detail="This request has already been answered or has expired.")
    return {"ok": True}
