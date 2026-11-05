"""Licensed web image search, private per-account R2 storage and renewable attachments."""
import asyncio
import hashlib
import io
import json
import logging
import os
import re
import uuid
import warnings
from urllib.parse import urlencode, urlsplit

from PIL import Image, ImageOps

from app.core.db import get_pool
from app.services.images.image_storage import ID_PATTERN, R2ImageStorage
from app.services.source_reader import PageText, read_public_resource
from app.services.web_activity import safe_url

logger = logging.getLogger(__name__)
MAX_IMAGES = 3
MAX_BYTES = 6 * 1024 * 1024
_schema_ready = False

IMAGE_SEARCH_TOOL = {
    "name": "search_web_images",
    "description": "Search Wikimedia Commons for relevant reusable web images and save previews for this user. "
        "For user-visible WEB images use this tool: ordinary text web search cannot attach images. "
        "Use when the user asks for web pictures/diagrams, or a public visual materially helps. "
        "Do not use for greetings, text-only answers, or to retrieve a figure from an uploaded PDF. "
        "Use concise public search terms, never private document text or personal data. "
        "Results include real image IDs, source pages and license attribution; the app displays them. "
        "Never invent an image or claim the pixels were analyzed. No suitable result is a valid outcome.",
    "parametersJsonSchema": {"type": "object", "required": ["query"], "properties": {
        "query": {"type": "string", "description": "Concise public image search terms (prefer English).", "maxLength": 250},
        "limit": {"type": "integer", "minimum": 1, "maximum": MAX_IMAGES,
                  "description": "Number requested by the user; default to one preview."}}},
}


def configured():
    return os.getenv("WEB_IMAGE_SEARCH", "true").lower() != "false" and all(
        os.getenv(name, "").strip() for name in ("R2_ENDPOINT_URL", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET_NAME"))


def plain_html(value, limit=500):
    parser = PageText()
    parser.feed(str(value or ""))
    return " ".join(" ".join(parser.parts).split())[:limit]


def commons_candidates(query, limit):
    params = {"action": "query", "generator": "search", "gsrnamespace": 6, "gsrsearch": query,
              "gsrlimit": min(12, limit * 4), "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata",
              "iiurlwidth": 1280, "format": "json", "formatversion": 2}
    data, _ = read_public_resource("https://commons.wikimedia.org/w/api.php?" + urlencode(params))
    payload = json.loads(data)
    if payload.get("error"):
        raise ValueError("Image search is temporarily unavailable")
    results = []
    for page in sorted(payload.get("query", {}).get("pages", []), key=lambda item: item.get("index", 999)):
        info = (page.get("imageinfo") or [{}])[0]
        metadata = info.get("extmetadata") or {}
        value = lambda field: plain_html((metadata.get(field) or {}).get("value"))
        license_id = value("License").lower()
        # Commons returns explicit licensing; unknown/missing licenses are never copied.
        if not re.fullmatch(r"(?:cc-by(?:-sa)?-\d\.\d|cc0|pd)", license_id):
            continue
        download = info.get("thumburl") or info.get("url")
        source = safe_url(info.get("descriptionurl"))
        license_url = safe_url(value("LicenseUrl"))
        if not source or urlsplit(source).hostname != "commons.wikimedia.org":
            continue
        if not safe_url(download) or urlsplit(download).hostname not in {"upload.wikimedia.org", "thumb.wikimedia.org"}:
            continue
        if not license_url and license_id in {"pd", "cc0"}:
            license_url = "https://creativecommons.org/publicdomain/" + ("mark/1.0/" if license_id == "pd" else "zero/1.0/")
        author = value("Artist") or value("Credit")
        if not license_url or (license_id.startswith("cc-by") and not author):
            continue
        results.append({"download_url": download, "source_url": source,
            "title": plain_html(page.get("title", "Image").removeprefix("File:"), 300),
            "description": value("ImageDescription"), "author": author,
            "license": value("LicenseShortName"), "license_url": license_url,
            "provider": "Wikimedia Commons"})
    return results


def preview_image(data):
    if len(data) > MAX_BYTES:
        raise ValueError("Image exceeds download limit")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in {"JPEG", "PNG", "WEBP"} or source.width * source.height > 16_000_000:
                raise ValueError("Unsupported image or pixel count")
            source.seek(0)
            image = ImageOps.exif_transpose(source)
            image.thumbnail((1600, 1600))
            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            output = io.BytesIO()
            # Re-encoding strips scripts, metadata and remote references; SVG is not accepted.
            image.save(output, format="WEBP", quality=85)
            return output.getvalue(), image.width, image.height


async def ensure_schema():
    global _schema_ready
    if _schema_ready:
        return
    async with (await get_pool()).acquire() as connection:
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS web_images (
                user_id TEXT NOT NULL, image_id TEXT NOT NULL, object_key TEXT NOT NULL,
                source_url TEXT NOT NULL, metadata JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY(user_id, image_id), UNIQUE(user_id, source_url)
            );
            ALTER TABLE web_images ENABLE ROW LEVEL SECURITY;
        """)
    _schema_ready = True


def attachment(row, storage):
    metadata = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]
    return {**metadata, "image_id": row["image_id"], "source_url": row["source_url"],
            "url": storage.sign(row["object_key"]) if storage else "", "url_expires_in": storage.expires_in if storage else 900}


async def owned_images(user_id, ids=None):
    if not ids:
        return {}
    await ensure_schema()
    async with (await get_pool()).acquire() as connection:
        rows = await connection.fetch("SELECT * FROM web_images WHERE user_id=$1 AND image_id=ANY($2::text[])", user_id, list(set(ids)))
    return {row["image_id"]: row for row in rows}


async def store_candidate(user_id, candidate, storage):
    await ensure_schema()
    async with (await get_pool()).acquire() as connection:
        existing = await connection.fetchrow("SELECT * FROM web_images WHERE user_id=$1 AND source_url=$2", user_id, candidate["source_url"])
    if existing:
        return attachment(existing, storage)
    data, _ = await asyncio.to_thread(read_public_resource, candidate["download_url"], MAX_BYTES,
                                     ("image/jpeg", "image/png", "image/webp"))
    preview, width, height = await asyncio.to_thread(preview_image, data)
    image_id = hashlib.sha256(preview).hexdigest()
    # Unique upload key makes cleanup safe even when concurrent searches find the same image.
    prefix = f"users/{user_id}/web-images/{uuid.uuid4().hex}"
    key = await asyncio.to_thread(storage.upload, prefix, {"image_id": image_id, "extension": "webp",
        "content_type": "image/webp", "data": preview})
    metadata = {field: value for field, value in candidate.items() if field != "download_url"}
    metadata.update(width=width, height=height, preview_note="Resized WebP preview")
    try:
        async with (await get_pool()).acquire() as connection:
            row = await connection.fetchrow("""INSERT INTO web_images(user_id,image_id,object_key,source_url,metadata)
                VALUES($1,$2,$3,$4,$5::jsonb) ON CONFLICT DO NOTHING RETURNING *""",
                user_id, image_id, key, candidate["source_url"], json.dumps(metadata))
            if row is None:
                row = await connection.fetchrow("SELECT * FROM web_images WHERE user_id=$1 AND (image_id=$2 OR source_url=$3) LIMIT 1",
                                                 user_id, image_id, candidate["source_url"])
                await asyncio.to_thread(storage.delete, key)
        if row is None:
            raise ValueError("Image could not be saved")
    except Exception:
        # This key was allocated by this operation; never delete a pre-existing shared object.
        try:
            await asyncio.to_thread(storage.delete, key)
        except Exception:
            logger.exception("Could not clean up an unsuccessful web image upload")
        raise
    return attachment(row, storage)


async def search_and_store(user_id, query, limit=1):
    if not ID_PATTERN.fullmatch(user_id or ""):
        raise ValueError("Invalid account ID")
    if not isinstance(query, str) or not query.strip() or len(query) > 250:
        raise ValueError("Provide public image search terms of 1–250 characters")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_IMAGES:
        raise ValueError("Choose between one and three images")
    if not configured():
        raise ValueError("Web image storage is not configured")
    storage = R2ImageStorage.from_env()
    candidates = await asyncio.to_thread(commons_candidates, query.strip(), limit)
    images, seen, failures = [], set(), 0
    for candidate in candidates:
        try:
            image = await store_candidate(user_id, candidate, storage)
            if image["image_id"] not in seen:
                seen.add(image["image_id"])
                images.append(image)
            if len(images) >= limit:
                break
        except Exception:
            failures += 1
            logger.info("A web image could not be saved", exc_info=True)
    if candidates and failures == len(candidates):
        raise ValueError("Image previews could not be downloaded or saved. Please try again.")
    return images
