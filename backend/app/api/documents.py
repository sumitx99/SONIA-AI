"""/upload and /documents: storing PDFs, and serving them and their images back."""

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from asyncpg.exceptions import UniqueViolationError
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse, Response
from requests.exceptions import HTTPError, RequestException

from app.core.auth import current_user
from app.core.db import (completed_upload, delete_document, discard_unfinished_upload, document_status,
                         finish_upload, get_document_source, insert_embeddings, insert_file,
                         owned_document_ids, set_document_source_key, set_images_status, touch_upload)
from app.services.conversation_cache import invalidate_conversations
from app.services.embeddings import get_embeddings_batch
from app.services.images.image_db import find_document_images
from app.services.images.image_pipeline import image_attachments, ingest_document_images
from app.services.images.image_storage import R2ImageStorage, document_prefix, valid_chat_id
from app.services.parsing.docling_utils import docling_enabled, process_pdf_with_docling
from app.services.parsing.pdf_utils import chunk_text

logger = logging.getLogger(__name__)
router = APIRouter()
# A small Render instance must not parse several PDFs, or render several PDFs' images, at once.
_upload_slots = asyncio.Semaphore(1)
_image_slots = asyncio.Semaphore(1)
_image_jobs: set[asyncio.Task] = set()
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
# Work in progress refreshes its row every HEARTBEAT_SECONDS; a row silent for STALE_AFTER_SECONDS
# belongs to a process that died (out of memory, restarted), on this instance or another one.
HEARTBEAT_SECONDS = 15
STALE_AFTER_SECONDS = 90


@router.post("/upload", tags=["Document Handling"])
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
    async with _upload_slots:
        cached = await completed_upload(user_id, request_id)
        if cached:
            cached = json.loads(cached) if isinstance(cached, str) else cached
            # Images may have finished (or failed) since this response was first sent.
            return {**cached, **(await document_status(cached["file_id"], STALE_AFTER_SECONDS) or {})}
        return await _process_upload(file, file_bytes, chat_id, request_id, user_id)


@asynccontextmanager
async def _heartbeat(document_id):
    """Keep the document's heartbeat fresh while this process works on it."""
    async def beat():
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            try:
                await touch_upload(document_id)
            except Exception:
                logger.warning("Could not refresh the heartbeat of document %s", document_id)

    task = asyncio.create_task(beat())
    try:
        yield
    finally:
        task.cancel()


async def _process_upload(file, file_bytes, chat_id, request_id, user_id):
    """Store the PDF and make its text searchable; images follow in a background job."""
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
        if request_id:
            await _discard_abandoned_attempts(user_id, request_id, storage)
        file_id = await insert_file(file.filename, None if storage else file_bytes, chat_id, user_id, request_id)
        async with _heartbeat(file_id):
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

            chunks = chunk_text(rich_content)
            logger.info(f"Extracted {len(chunks)} chunks; generating embeddings.")
            all_embeddings = await asyncio.to_thread(get_embeddings_batch, chunks)
            await insert_embeddings(file_id, chunks, all_embeddings)

            images_status = "processing" if storage else "disabled"
            await set_images_status(file_id, images_status)
            result = {"file_id": file_id, "filename": file.filename, "chunks_stored": len(chunks),
                      "images_stored": 0, "images_status": images_status, "warnings": []}
            # A retry after a lost response returns this result without creating a duplicate.
            await finish_upload(file_id, result)
            succeeded = True
            await invalidate_conversations(user_id)
        if storage:
            _start_image_job(file_id, source_key, rich_content, storage, prefix)
        return result

    except HTTPException:
        raise
    except UniqueViolationError:
        # An earlier attempt of this request is still alive (fresh heartbeat), maybe on another instance.
        raise HTTPException(409, "This upload is still being processed. Please wait a moment.",
                            headers={"Retry-After": str(STALE_AFTER_SECONDS // 3)})
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


def _start_image_job(document_id, source_key, markdown, storage, prefix):
    # Keep a reference: the event loop holds tasks only weakly.
    task = asyncio.create_task(_process_images(document_id, source_key, markdown, storage, prefix))
    _image_jobs.add(task)
    task.add_done_callback(_image_jobs.discard)


async def _process_images(document_id, source_key, markdown, storage, prefix):
    """Extract, store and index the document's images; the text is already searchable."""
    # The heartbeat starts before queueing, so a job waiting behind another is not taken for dead.
    async with _heartbeat(document_id), _image_slots:
        try:
            # Fetched only now, so PDFs queued behind another job don't wait in memory.
            pdf_bytes = await asyncio.to_thread(storage.download_pdf, source_key)
            stored = await ingest_document_images(document_id, pdf_bytes, markdown, storage, prefix)
            del pdf_bytes
            await set_images_status(document_id, "ready", stored)
            logger.info("Stored %s images for document %s", stored, document_id)
        except Exception:
            logger.exception("Image processing failed for document %s", document_id)
            try:
                await set_images_status(document_id, "failed")
            except Exception:
                logger.exception("Could not record the image failure of document %s", document_id)


async def _discard_abandoned_attempts(user_id, request_id, storage):
    """Clear what an earlier attempt of this request left behind when its process died mid-upload.

    Such an attempt (killed for memory, restarted by the host) keeps its documents row with no
    response and its cleanup never ran, so every retry would hit the unique request index. Its
    heartbeat has stopped; an attempt whose heartbeat is still fresh is left alone (see 409 above).
    """
    for document_id, chat_id in await discard_unfinished_upload(user_id, request_id, STALE_AFTER_SECONDS):
        logger.warning("Discarded abandoned upload attempt %s for request %s", document_id, request_id)
        if storage:
            try:
                await asyncio.to_thread(storage.delete_upload, document_prefix(user_id, chat_id, document_id))
            except Exception:
                logger.exception("Could not remove stored objects of abandoned upload %s", document_id)


@router.get("/documents/{document_id}/status", tags=["Document Handling"])
async def get_document_status(document_id: int, user_id: str = Depends(current_user)):
    if not await owned_document_ids(user_id, [document_id]):
        raise HTTPException(status_code=404, detail="Document not found")
    status = await document_status(document_id, STALE_AFTER_SECONDS)
    if status is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if status["images_status"] == "failed":
        status["warnings"] = ["Text is ready, but this document's images could not be processed."]
    return status


@router.get("/documents/{document_id}/source", tags=["Document Handling"])
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


@router.get("/documents/{document_id}/images", tags=["Document Images"])
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


@router.get("/documents/{document_id}/images/{image_id}", tags=["Document Images"])
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
