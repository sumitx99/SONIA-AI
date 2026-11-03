# app/app.py

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from requests.exceptions import HTTPError, RequestException

# --- MODIFIED IMPORTS ---
from app.auth import current_user
from app.db import (insert_file, insert_embeddings, get_document_source, close_pool,
                    set_document_source_key, delete_document, owned_document_ids,
                    completed_upload, finish_upload)
from app.embeddings import get_embedding, get_embeddings_batch
from app.llm import NO_ANSWER, get_llm_response
from app.pdf_utils import chunk_text
from app.docling_utils import docling_enabled, process_pdf_with_docling
from app.retriever import get_reranked_context, rank_contexts
from app.document_images import wants_images, requested_image_location
from app.image_storage import R2ImageStorage, document_prefix, valid_chat_id
from app.image_db import find_document_images
from app.image_pipeline import ingest_document_images, image_attachments
from app.conversations import router as conversations_router
from app.profiles import router as profiles_router
from app.mcp_server.server import MCPMount, build_mcp_app
from app.mcp_client.connections import router as mcp_connections_router
from app.mcp_client.agent import answer_with_tools, available_tools, resolve_approval
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_mcp_mount = MCPMount()


def warm_up_docling():
    # Load Docling's layout models in the background so the first upload isn't slow.
    import threading

    if not docling_enabled():
        return

    def load():
        try:
            from app.docling_utils import _converter
            _converter()
            logger.info("Docling models loaded.")
        except Exception:
            logger.exception("Docling warm-up failed; uploads will fall back to PyMuPDF")

    threading.Thread(target=load, daemon=True).start()


@asynccontextmanager
async def lifespan(_app):
    warm_up_docling()
    # The MCP session manager runs once per app instance, so each lifespan gets a fresh one.
    mcp_app = build_mcp_app()
    async with mcp_app.router.lifespan_context(mcp_app):
        _mcp_mount.app = mcp_app
        try:
            yield
        finally:
            _mcp_mount.app = None
    await close_pool()


app = FastAPI(title="Sonia Advanced RAG API", lifespan=lifespan)
app.include_router(conversations_router)
app.include_router(profiles_router)
app.include_router(mcp_connections_router)
_upload_slots = asyncio.Semaphore(1)
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

# Comma-separated, e.g. "https://sonia.vercel.app,http://localhost:3000".
origins = [origin.strip().rstrip("/") for origin in
           os.getenv("FRONTEND_ORIGINS", "http://localhost:3000").split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", tags=["General"])
async def root():
    return {"message": "Sonia Advanced RAG Chatbot API is running 🚀", "version": "history-upload-images-v2"}

@app.post("/upload", tags=["Document Handling"])
async def upload_pdf(file: UploadFile = File(...), chat_id: str | None = Form(None),
                     request_id: str | None = Form(None),
                     user_id: str = Depends(current_user)):
    if not valid_chat_id(chat_id):
        raise HTTPException(status_code=422, detail="chat_id may only contain letters, digits, '-' and '_' (max 64)")
    if request_id is not None and not valid_chat_id(request_id):
        raise HTTPException(422, "Invalid upload request ID")
    file_bytes = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Please upload a PDF smaller than 25 MB.")
    if not file_bytes or b"%PDF-" not in file_bytes[:1024]:
        raise HTTPException(422, "This file is not a readable PDF.")
    # A small Render instance must not parse several PDFs into memory at once.
    async with _upload_slots:
        cached = await completed_upload(user_id, request_id)
        if cached:
            return json.loads(cached) if isinstance(cached, str) else cached
        return await _process_upload(file, file_bytes, chat_id, request_id, user_id)


async def _process_upload(file, file_bytes, chat_id, request_id, user_id):
    file_id = None
    storage = None
    source_key = None
    prefix = None
    succeeded = False
    try:
        logger.info(f"Receiving file: {file.filename} (chat {chat_id})")

        # With R2 configured the PDF goes to users/{user}/chats/{chat}/documents/{id}/source.pdf
        # and Postgres keeps only the key; without it the bytes stay in Postgres.
        storage = R2ImageStorage.from_env()
        file_id = await insert_file(file.filename, None if storage else file_bytes, chat_id, user_id, request_id)
        prefix = document_prefix(user_id, chat_id, file_id)
        if storage:
            source_key = await asyncio.to_thread(storage.upload_pdf, prefix, file_bytes)
            await set_document_source_key(file_id, source_key)
        logger.info(f"File '{file.filename}' stored with ID: {file_id}")

        # Layout-aware Markdown via Docling (or PyMuPDF text), off the event loop: it takes seconds.
        logger.info("Extracting text with %s...", "Docling" if docling_enabled() else "PyMuPDF")
        rich_content = await run_in_threadpool(process_pdf_with_docling, file_bytes, file.filename)
        
        if not rich_content:
            raise HTTPException(status_code=422, detail="No text could be read from this PDF. "
                                "If it is a scanned document, try a PDF with selectable text.")
        
        # --- Chunk the high-quality Markdown content ---
        chunks = chunk_text(rich_content)
        logger.info(f"Extracted {len(chunks)} chunks.")

        # --- SPEED UPGRADE: Generate all embeddings in one batch ---
        logger.info(f"Generating embeddings for {len(chunks)} chunks in a single batch.")
        all_embeddings = await asyncio.to_thread(get_embeddings_batch, chunks)
        
        # --- Store the results ---
        logger.info("Storing chunks and embeddings in the database.")
        await insert_embeddings(file_id, chunks, all_embeddings)

        images_stored = 0
        images_status = "disabled"
        warnings = []
        try:
            if storage:
                images_stored = await ingest_document_images(file_id, file_bytes, rich_content, storage, prefix)
                images_status = "ready"
        except Exception:
            logger.exception("Image processing failed for document %s", file_id)
            images_status = "failed"
            warnings.append("Text is ready, but image processing failed. Check the server configuration and logs.")

        result = {"file_id": file_id, "filename": file.filename, "chunks_stored": len(chunks),
                  "images_stored": images_stored, "images_status": images_status, "warnings": warnings}
        # A retry after a lost response returns this result without creating a duplicate.
        await finish_upload(file_id, result)
        succeeded = True
        return result

    except HTTPException:
        raise
    except HTTPError as e:
        status = e.response.status_code if e.response is not None else 503
        logger.error("Embedding service failed with HTTP %s", status)
        raise HTTPException(status_code=503 if status in (429, 500, 502, 503, 504) else 502,
                            detail="The document service is busy. Please try this upload again.")
    except RequestException:
        logger.warning("The document service timed out or could not be reached")
        raise HTTPException(503, "The document service did not respond. Please try again.")
    except Exception as e:
        logger.exception("Document upload failed")
        raise HTTPException(500, "The document could not be processed. Please try again.")
    finally:
        if file_id is not None and not succeeded:
            try:
                await delete_document(file_id)
                if storage and prefix:
                    await asyncio.to_thread(storage.delete_upload, prefix)
            except Exception:
                logger.exception("Could not clean up failed upload %s", file_id)


async def _answer_context(query, document_ids, scope_documents, include_images, user_id):
    """Retrieves the passages (and, when asked, images) an answer is grounded in.

    Image URLs come from retrieved metadata; the language model never invents them.
    Returns the prompt context and the image fields of the response.
    """
    query_embedding = await asyncio.to_thread(get_embedding, query)
    logger.info("Starting advanced retrieval with re-ranking...")
    requested = (document_ids or []) if scope_documents else document_ids
    # Only the signed-in user's documents are ever searched (None = all of theirs).
    scope = await owned_document_ids(user_id, requested)
    context = await get_reranked_context(query, query_embedding, document_ids=scope)

    images = []
    image_status = "not_requested"
    image_notice = None
    if include_images or wants_images(query):
        image_status = "disabled"
        image_notice = "Image storage is not configured on this server."
        try:
            storage = R2ImageStorage.from_env()
            if storage:
                page_number, image_number = requested_image_location(query)
                candidates = await find_document_images(query_embedding, document_ids=scope,
                                                         page_number=page_number, image_number=image_number)
                selected = await asyncio.to_thread(rank_contexts, query, candidates,
                                                   text_key="search_text", limit=5)
                images = image_attachments(selected, storage)
                image_status = "ready" if images else "not_found"
                image_notice = None if images else "No indexed image matched the requested document or location."
                if selected:
                    image_context = "\n\n".join(
                        f"Image ID: {image['image_id']}; document {image['document_id']}; "
                        f"page {image['page_number']}; image {image['image_number']}\n"
                        + image["search_text"] for image in selected
                    )
                    context += "\n\nImage source locations and surrounding text:\n" + image_context
        except Exception:
            logger.exception("Image retrieval failed")
            image_status = "failed"
            image_notice = "Image retrieval is temporarily unavailable."

        context += (
            "\n\nImage retrieval status: " + image_status + ". " + (image_notice or "")
            + "\nOnly the image locations and nearby text are available; the image pixels "
            "have not been analyzed. Do not invent visual details or image URLs. "
            "The application displays retrieved images separately. "
            "If no image was found, say so rather than claiming to display one."
        )

    if not context:
        logger.warning("No relevant context found after re-ranking for the query.")
    else:
        logger.info("Retrieved and re-ranked context successfully.")
    return context, {"images": images, "image_status": image_status, "image_notice": image_notice}


@app.post("/chat", tags=["Chat"])
async def chat(query: str = Form(...), document_ids: list[int] | None = Form(None),
               scope_documents: bool = Form(False), include_images: bool = Form(False),
               user_id: str = Depends(current_user)):
    try:
        logger.info(f"Received query: '{query}'")
        context, meta = await _answer_context(query, document_ids, scope_documents, include_images, user_id)
        answer = await asyncio.to_thread(get_llm_response, query, context)
        logger.info("Generated LLM response.")
        return {"query": query, "answer": answer, **meta}

    except HTTPError as e:
        logger.error(f"HTTPError during LLM call: {e}")
        raise HTTPException(status_code=503, detail=f"The AI service is temporarily unavailable: {e.response.text}")
    except Exception as e:
        logger.error(f"An unexpected error occurred during chat: {e}")
        raise HTTPException(status_code=500, detail=f"An internal server error occurred: {str(e)}")


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.post("/chat/stream", tags=["Chat"])
async def chat_stream(query: str = Form(...), document_ids: list[int] | None = Form(None),
                      scope_documents: bool = Form(False), include_images: bool = Form(False),
                      user_id: str = Depends(current_user)):
    """Like /chat, but streams the answer as server-sent events while Gemini writes it.

    Events: `meta` (images and status, once), `delta` ({"text"}, repeatedly), then `done`,
    or `error` ({"detail"}) if the answer breaks off part-way. The model may read web pages, listed
    in a `sources` event at the end. With MCP connections it may also call tools, reported as
    `tool_call` and, for tools that need consent, `approval_required`.
    """
    try:
        logger.info(f"Received streaming query: '{query}'")
        # Retrieval errors happen before any bytes are sent, so they keep normal status codes.
        context, meta = await _answer_context(query, document_ids, scope_documents, include_images, user_id)
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
            wrote_any = False
            async for name, data in answer_with_tools(user_id, query, context, declarations, registry):
                wrote_any = wrote_any or name == "delta"
                yield _sse(name, data)
            if not wrote_any:
                yield _sse("delta", {"text": NO_ANSWER})
            yield _sse("done", {})
        except Exception:
            logger.exception("Streaming the answer failed")
            yield _sse("error", {"detail": "The answer was interrupted. Please try again."})

    # No buffering by proxies, so each piece reaches the browser as soon as it is written.
    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class ApprovalInput(BaseModel):
    approve: bool


@app.post("/chat/approvals/{approval_id}", tags=["Chat"])
async def decide_tool_call(approval_id: str, payload: ApprovalInput, user_id: str = Depends(current_user)):
    """Approve or decline a tool call that a streaming answer is waiting on."""
    if not resolve_approval(user_id, approval_id, payload.approve):
        raise HTTPException(status_code=404, detail="This request has already been answered or has expired.")
    return {"ok": True}


@app.get("/documents/{document_id}/source", tags=["Document Handling"])
async def document_source(document_id: int, user_id: str = Depends(current_user)):
    source = await get_document_source(document_id, user_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if source["source_key"]:
        storage = R2ImageStorage.from_env()
        if storage is None:
            raise HTTPException(status_code=503, detail="Document storage is not configured")
        # Browsers keep the #page=N fragment across this redirect.
        return RedirectResponse(storage.sign(source["source_key"]), status_code=307)
    return Response(source["file"], media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="document-{document_id}.pdf"',
    })


@app.get("/documents/{document_id}/images", tags=["Document Images"])
async def list_images(document_id: int, page_number: int | None = Query(None, ge=1),
                      image_number: int | None = Query(None, ge=1),
                      limit: int = Query(25, ge=1, le=100), user_id: str = Depends(current_user)):
    if not await owned_document_ids(user_id, [document_id]):
        raise HTTPException(status_code=404, detail="Document not found")
    storage = R2ImageStorage.from_env()
    if storage is None:
        raise HTTPException(status_code=503, detail="Image storage is not configured")
    results = await find_document_images(document_ids=[document_id], page_number=page_number,
                                         image_number=image_number, limit=limit)
    return {"images": image_attachments(results, storage)}


@app.get("/documents/{document_id}/images/{image_id}", tags=["Document Images"])
async def get_image(document_id: int, image_id: str, user_id: str = Depends(current_user)):
    if not await owned_document_ids(user_id, [document_id]):
        raise HTTPException(status_code=404, detail="Image not found in this document")
    storage = R2ImageStorage.from_env()
    if storage is None:
        raise HTTPException(status_code=503, detail="Image storage is not configured")
    results = await find_document_images(document_ids=[document_id], image_id=image_id, limit=1)
    if not results:
        raise HTTPException(status_code=404, detail="Image not found in this document")
    return image_attachments(results, storage)[0]


# MCP for Claude, Cursor and other clients: /mcp and its OAuth metadata at
# /.well-known/oauth-protected-resource/mcp. Mounted last so the API's own routes match first.
app.mount("/", _mcp_mount)
