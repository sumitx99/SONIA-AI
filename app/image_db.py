"""Image metadata and contextual-vector retrieval using the existing pgvector DB."""

import json

from app.db import get_pool

_image_schema_ready = False


async def ensure_image_schema():
    global _image_schema_ready
    if _image_schema_ready:
        return
    async with (await get_pool()).acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS document_images (
                image_id TEXT PRIMARY KEY,
                document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                page_number INTEGER NOT NULL CHECK (page_number > 0),
                image_number INTEGER NOT NULL CHECK (image_number > 0),
                object_key TEXT NOT NULL,
                metadata JSONB NOT NULL,
                search_text TEXT NOT NULL,
                embedding vector NOT NULL
            );
            CREATE INDEX IF NOT EXISTS document_images_location_idx
                ON document_images(document_id, page_number, image_number);
        """)
    _image_schema_ready = True


async def save_document_images(document_id: int, images: list[dict], embeddings: list[list[float]]):
    if len(images) != len(embeddings):
        raise ValueError("Each image must have an embedding")
    await ensure_image_schema()
    rows = []
    for image, embedding in zip(images, embeddings):
        metadata = {key: value for key, value in image.items()
                    if key not in {"data", "object_key", "search_text", "image_id"}}
        rows.append((image["image_id"], document_id, image["page_number"], image["image_number"],
                     image["object_key"], json.dumps(metadata), image["search_text"], embedding))
    async with (await get_pool()).acquire() as conn:
        # All images of a document are stored, or none are.
        async with conn.transaction():
            await conn.executemany("""
                INSERT INTO document_images
                    (image_id, document_id, page_number, image_number, object_key,
                     metadata, search_text, embedding)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8)
            """, rows)


async def find_document_images(query_embedding=None, document_ids=None, page_number=None,
                               image_number=None, limit=25, image_id=None) -> list[dict]:
    # An explicitly empty scope must never fall back to all documents.
    if document_ids == []:
        return []
    await ensure_image_schema()
    filters, values = [], []

    def param(value):
        values.append(value)
        return f"${len(values)}"

    if document_ids is not None:
        filters.append(f"document_id = ANY({param(list(document_ids))}::int[])")
    for field, value in (("page_number", page_number), ("image_number", image_number),
                         ("image_id", image_id)):
        if value is not None:
            filters.append(f"{field} = {param(value)}")
    where = " WHERE " + " AND ".join(filters) if filters else ""
    order = (f"embedding <-> {param(query_embedding)}" if query_embedding is not None
             else "document_id, page_number, image_number")
    limit_param = param(min(max(limit, 1), 100))
    async with (await get_pool()).acquire() as conn:
        rows = await conn.fetch(
            "SELECT image_id, document_id, object_key, metadata, search_text, documents.source_key "
            f"FROM document_images JOIN documents ON documents.id = document_id{where} "
            f"ORDER BY {order} LIMIT {limit_param}", *values,
        )
    images = []
    for row in rows:
        metadata = row["metadata"]
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        images.append({**metadata, "image_id": row["image_id"], "document_id": row["document_id"],
                       "object_key": row["object_key"], "search_text": row["search_text"],
                       "source_key": row["source_key"]})
    return images
