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
from app.services.answer_verification import check_citations
from app.services.llm import (NO_ANSWER, BackupUnavailable, backup_configured, gemini_unavailable,
                              stream_backup_answer, WebSearchUnavailable)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/chat", tags=["Chat"])
async def chat(query: str = Form(...), document_ids: list[int] | None = Form(None),
               scope_documents: bool = Form(False), include_images: bool = Form(False),
               user_id: str = Depends(current_user), history: str | None = Form(None)):
    turns = parse_history(history)
    try:
        logger.info(f"Received query: '{query}'")
        context, meta = await answer_context(query, document_ids, scope_documents, include_images, user_id)
        declarations, registry = await _load_tools(user_id)
        answer, citations, web_images = "", [], []
        async for name, data in _answer_events(user_id, query, context, declarations, registry, turns):
            if name == "citations":
                answer, citations = data["answer"], data["citations"]
            elif name == "web_images":
                web_images.extend(data["images"])
        logger.info("Generated LLM response.")
        return {"query": query, "answer": answer or NO_ANSWER, "citations": citations, "web_images": web_images, **meta}

    except HTTPError as e:
        logger.error(f"HTTPError during LLM call: {e}")
        raise HTTPException(status_code=503, detail=f"The AI service is temporarily unavailable: {e.response.text}")
    except Exception as e:
        logger.error(f"An unexpected error occurred during chat: {e}")
        raise HTTPException(status_code=500, detail=f"An internal server error occurred: {str(e)}")


def _failure_message(error: Exception) -> str:
    if isinstance(error, WebSearchUnavailable):
        return "Web search could not be completed right now. Please try again later; current information could not be verified."
    if isinstance(error, BackupUnavailable) or gemini_unavailable(error):
        return "Sonia's AI models are busy or have used up today's free quota. Please try again in a little while."
    return "The answer was interrupted. Please try again."


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/chat/stream", tags=["Chat"])
async def chat_stream(query: str = Form(...), document_ids: list[int] | None = Form(None),
                      scope_documents: bool = Form(False), include_images: bool = Form(False),
                      user_id: str = Depends(current_user), history: str | None = Form(None)):
    """Like /chat, but streams the answer as server-sent events while Gemini writes it.

    Events: `meta` (images and status, once), `delta` ({"text"}, repeatedly), `citations`
    ({"answer", "citations"}: the final text without its citations block, and each checked
    citation), then `done`, or `error` ({"detail"}) if the answer breaks off part-way. The model
    may read web pages, listed in `sources` events. With MCP connections it may also call tools, reported as
    `tool_call` and, for tools that need consent, `approval_required`. If Gemini is out of quota or
    down before anything was shown, a backup model answers instead.
    """
    turns = parse_history(history)
    try:
        logger.info(f"Received streaming query: '{query}'")
        # Retrieval errors happen before any bytes are sent, so they keep normal status codes.
        context, meta = await answer_context(query, document_ids, scope_documents, include_images, user_id)
    except HTTPError as e:
        logger.error(f"HTTPError during retrieval: {e}")
        raise HTTPException(status_code=503, detail=f"The AI service is temporarily unavailable: {e.response.text}")
    except Exception as e:
        logger.error(f"An unexpected error occurred during chat: {e}")
        raise HTTPException(status_code=500, detail=f"An internal server error occurred: {str(e)}")

    declarations, registry = await _load_tools(user_id)

    async def events():
        yield _sse("meta", meta)
        try:
            async for name, data in _answer_events(user_id, query, context, declarations, registry, turns):
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


async def _answer_events(user_id, query, context, declarations, registry, turns):
    """The answer's events, streamed as written, ending with its checked citations."""
    draft, sources, evidence = [], {}, []
    shown = False  # text or a non-web tool step the user has already seen
    try:
        async for name, data in answer_with_tools(user_id, query, context, declarations, registry,
                                                  **({"history": turns} if turns else {})):
            if name == "evidence":
                evidence.extend(data["sources"])
                continue
            if name == "delta":
                draft.append(data["text"])
            elif name == "sources":
                sources.update({item["url"]: item for item in data["sources"]})
            shown = shown or name == "delta" or (name == "tool_call" and data.get("server") != "Web")
            yield name, data
    except Exception as error:
        # A backup may answer only if nothing was shown and no external action ran.
        # Connected-tool fallbacks belong to the agent, which preserves the registry.
        # Never replace them with a plain answer path that has no connected tools.
        if declarations or shown or not gemini_unavailable(error) or not backup_configured():
            raise
        logger.warning("Gemini unavailable (%s); answering with a backup model", error)
        async for kind, value in iterate_in_threadpool(stream_backup_answer(query, context, *([turns] if turns else []))):
            if kind == "model":
                logger.info("Backup model %s is answering", value)
            elif kind == "evidence":
                evidence.extend(value["sources"])
            elif kind == "text":
                draft.append(value)
                yield "delta", {"text": value}
            else:
                if kind == "sources":
                    sources.update({item["url"]: item for item in value["sources"]})
                yield kind, value
    if not draft:
        yield "delta", {"text": NO_ANSWER}
        return
    answer, citations = await asyncio.to_thread(check_citations, "".join(draft), context,
                                                list(sources.values()), evidence)
    yield "citations", {"answer": answer, "citations": citations}


class ApprovalInput(BaseModel):
    approve: bool


@router.post("/chat/approvals/{approval_id}", tags=["Chat"])
async def decide_tool_call(approval_id: str, payload: ApprovalInput, user_id: str = Depends(current_user)):
    """Approve or decline a tool call that a streaming answer is waiting on."""
    if not resolve_approval(user_id, approval_id, payload.approve):
        raise HTTPException(status_code=404, detail="This request has already been answered or has expired.")
    return {"ok": True}
