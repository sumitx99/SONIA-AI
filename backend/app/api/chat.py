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
from app.services.llm import (NO_ANSWER, BackupUnavailable, backup_configured, gemini_unavailable,
                              get_llm_response, stream_backup_answer)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/chat", tags=["Chat"])
async def chat(query: str = Form(...), document_ids: list[int] | None = Form(None),
               scope_documents: bool = Form(False), include_images: bool = Form(False),
               user_id: str = Depends(current_user)):
    try:
        logger.info(f"Received query: '{query}'")
        context, meta = await answer_context(query, document_ids, scope_documents, include_images, user_id)
        answer = await asyncio.to_thread(get_llm_response, query, context)
        logger.info("Generated LLM response.")
        return {"query": query, "answer": answer, **meta}

    except HTTPError as e:
        logger.error(f"HTTPError during LLM call: {e}")
        raise HTTPException(status_code=503, detail=f"The AI service is temporarily unavailable: {e.response.text}")
    except Exception as e:
        logger.error(f"An unexpected error occurred during chat: {e}")
        raise HTTPException(status_code=500, detail=f"An internal server error occurred: {str(e)}")


def _failure_message(error: Exception) -> str:
    if isinstance(error, BackupUnavailable) or gemini_unavailable(error):
        return "Sonia's AI models are busy or have used up today's free quota. Please try again in a little while."
    return "The answer was interrupted. Please try again."


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/chat/stream", tags=["Chat"])
async def chat_stream(query: str = Form(...), document_ids: list[int] | None = Form(None),
                      scope_documents: bool = Form(False), include_images: bool = Form(False),
                      user_id: str = Depends(current_user)):
    """Like /chat, but streams the answer as server-sent events while Gemini writes it.

    Events: `meta` (images and status, once), `delta` ({"text"}, repeatedly), then `done`,
    or `error` ({"detail"}) if the answer breaks off part-way. The model may read web pages, listed
    in a `sources` event at the end. With MCP connections it may also call tools, reported as
    `tool_call` and, for tools that need consent, `approval_required`. If Gemini is out of quota or
    down before anything was shown, a backup model answers and a `notice` ({"text"}) says so.
    """
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

    try:
        declarations, registry = await available_tools(user_id)
    except Exception:
        # Connections must never stop a plain answer (e.g. MCP_SECRET_KEY missing).
        logger.exception("Couldn't load MCP connections; answering without tools")
        declarations, registry = [], {}

    async def events():
        yield _sse("meta", meta)
        try:
            wrote_any = shown_any = False
            try:
                async for name, data in answer_with_tools(user_id, query, context, declarations, registry):
                    shown_any = True
                    wrote_any = wrote_any or name == "delta"
                    yield _sse(name, data)
            except Exception as error:
                # Until the user has seen something, a backup model can still answer; after that
                # the answer is cut off rather than started again.
                if shown_any or not gemini_unavailable(error) or not backup_configured():
                    raise
                logger.warning("Gemini unavailable (%s); answering with a backup model", error)
                async for kind, value in iterate_in_threadpool(stream_backup_answer(query, context)):
                    if kind == "model":
                        yield _sse("notice", {"text": f"Answered by a backup model ({value}): web pages, "
                                                      "web search and connected tools weren't available."})
                    else:
                        wrote_any = True
                        yield _sse("delta", {"text": value})
            if not wrote_any:
                yield _sse("delta", {"text": NO_ANSWER})
            yield _sse("done", {})
        except Exception as error:
            logger.exception("Streaming the answer failed")
            yield _sse("error", {"detail": _failure_message(error)})

    # No buffering by proxies, so each piece reaches the browser as soon as it is written.
    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class ApprovalInput(BaseModel):
    approve: bool


@router.post("/chat/approvals/{approval_id}", tags=["Chat"])
async def decide_tool_call(approval_id: str, payload: ApprovalInput, user_id: str = Depends(current_user)):
    """Approve or decline a tool call that a streaming answer is waiting on."""
    if not resolve_approval(user_id, approval_id, payload.approve):
        raise HTTPException(status_code=404, detail="This request has already been answered or has expired.")
    return {"ok": True}
