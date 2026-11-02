"""Coordinate image ingestion and return signed, source-linked attachments."""

import logging
from concurrent.futures import ThreadPoolExecutor

from app.document_images import extract_document_images
from app.embeddings import get_embeddings_batch
from app.image_db import save_document_images

logger = logging.getLogger(__name__)


def ingest_document_images(document_id, pdf_bytes, markdown, storage, prefix):
    images = extract_document_images(pdf_bytes, markdown)
    if not images:
        return 0
    embeddings = get_embeddings_batch([image["search_text"] for image in images])
    if len(embeddings) != len(images):
        raise ValueError("Image embedding count does not match extracted image count")
    uploaded = []

    def upload(image):
        key = storage.upload(prefix, image)
        uploaded.append(key)  # list.append is thread-safe
        image["object_key"] = key

    try:
        # Each upload is a network round trip to R2; send them concurrently.
        with ThreadPoolExecutor(max_workers=min(8, len(images))) as pool:
            for result in [pool.submit(upload, image) for image in images]:
                result.result()
        save_document_images(document_id, images, embeddings)
    except Exception:
        for key in uploaded:
            try:
                storage.delete(key)
            except Exception:
                logger.exception("Could not clean up an image after failed ingestion")
        raise
    return len(images)


def image_attachments(images, storage):
    attachments = []
    for image in images:
        attachments.append({
            **{key: value for key, value in image.items()
               if key not in {"object_key", "search_text", "data", "source_key"}},
            "url": storage.sign(image["object_key"]),
            # Signed link to the PDF itself, so the browser can open it without an auth header.
            "source_url": (f"{storage.sign(image['source_key'])}#page={image['page_number']}"
                           if image.get("source_key") else None),
            "url_expires_in": storage.expires_in,
            "source_path": f"/documents/{image['document_id']}/source#page={image['page_number']}",
        })
    return attachments
