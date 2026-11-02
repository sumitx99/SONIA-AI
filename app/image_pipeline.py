"""Coordinate image ingestion and return signed, source-linked attachments."""

import asyncio
import logging
import re
from concurrent.futures import ThreadPoolExecutor

from app.document_images import extract_document_images
from app.embeddings import get_embeddings_batch
from app.image_db import save_document_images

logger = logging.getLogger(__name__)


async def ingest_document_images(document_id, pdf_bytes, markdown, storage, prefix):
    # Extraction, embedding and R2 calls are blocking; run them in worker threads.
    images = await asyncio.to_thread(extract_document_images, pdf_bytes, markdown)
    if not images:
        return 0
    embeddings = await asyncio.to_thread(get_embeddings_batch, [image["search_text"] for image in images])
    if len(embeddings) != len(images):
        raise ValueError("Image embedding count does not match extracted image count")
    uploaded = []

    def upload(image):
        key = storage.upload(prefix, image)
        uploaded.append(key)  # list.append is thread-safe
        image["object_key"] = key

    def upload_all():
        # Each upload is a network round trip to R2; send them concurrently.
        with ThreadPoolExecutor(max_workers=min(8, len(images))) as pool:
            for result in [pool.submit(upload, image) for image in images]:
                result.result()

    def clean_up():
        for key in uploaded:
            try:
                storage.delete(key)
            except Exception:
                logger.exception("Could not clean up an image after failed ingestion")

    try:
        await asyncio.to_thread(upload_all)
        await save_document_images(document_id, images, embeddings)
    except Exception:
        await asyncio.to_thread(clean_up)
        raise
    return len(images)


# Caption lines usually start "Figure 2:", "Fig. 3", "Table 1." and sit right below
# (or, for tables, right above) the image.
CAPTION_PATTERN = re.compile(
    r"^\s*(fig(ure)?|table|chart|diagram|graph|image|exhibit|plate|illustration)\.?\s*"
    r"[0-9ivxlc]+[a-z]?\b", re.IGNORECASE)
# Only these fields reach the browser; surrounding text stays server-side for retrieval.
PUBLIC_FIELDS = ("image_id", "document_id", "page_number", "image_number",
                 "heading_path", "width", "height")


def image_caption(image):
    """The image's own caption from the nearby text, or None when there isn't one."""
    after = [block.get("text", "") for block in image.get("after_context") or []][:2]
    before = [block.get("text", "") for block in reversed(image.get("before_context") or [])][:2]
    for text in after + before:
        if CAPTION_PATTERN.match(text):
            caption = " ".join(text.split())
            return caption if len(caption) <= 400 else caption[:399].rstrip() + "…"
    return None


def image_attachments(images, storage):
    attachments = []
    for image in images:
        attachments.append({
            **{key: image[key] for key in PUBLIC_FIELDS if key in image},
            "caption": image_caption(image),
            "url": storage.sign(image["object_key"]),
            # Signed link to the PDF itself, so the browser can open it without an auth header.
            "source_url": (f"{storage.sign(image['source_key'])}#page={image['page_number']}"
                           if image.get("source_key") else None),
            "url_expires_in": storage.expires_in,
            "source_path": f"/documents/{image['document_id']}/source#page={image['page_number']}",
        })
    return attachments
