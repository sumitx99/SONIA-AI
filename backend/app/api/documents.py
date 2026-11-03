"""/upload and /documents: storing PDFs, and serving them and their images back."""

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse, Response
from requests.exceptions import HTTPError, RequestException

from app.core.auth import current_user
from app.core.db import (completed_upload, delete_document, finish_upload, get_document_source, insert_embeddings,
                         insert_file, owned_document_ids, set_document_source_key)
from app.services.embeddings import get_embeddings_batch
from app.services.images.image_db import find_document_images
from app.services.images.image_pipeline import image_attachments, ingest_document_images
from app.services.images.image_storage import R2ImageStorage, document_prefix, valid_chat_id
from app.services.parsing.docling_utils import docling_enabled, process_pdf_with_docling
from app.services.parsing.pdf_utils import chunk_text

logger = logging.getLogger(__name__)
router = APIRouter()
_upload_slots = asyncio.Semaphore(1)
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


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
