"""Image metadata and contextual-vector retrieval using the existing pgvector DB."""

import json
from functools import lru_cache

from app.db import get_connection


@lru_cache(maxsize=1)
def ensure_image_schema():
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS document_images (
                image_id TEXT PRIMARY KEY,
                document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                page_number INTEGER NOT NULL CHECK (page_number > 0),
                image_number INTEGER NOT NULL CHECK (image_number > 0),
                object_key TEXT NOT NULL,
                metadata JSONB NOT NULL,
                search_text TEXT NOT NULL,
                embedding vector NOT NULL
            )
        """)
        cursor.execute("""CREATE INDEX IF NOT EXISTS document_images_location_idx
                          ON document_images(document_id, page_number, image_number)""")
        conn.commit()
    finally:
        conn.close()


def save_document_images(document_id: int, images: list[dict], embeddings: list[list[float]]):
    if len(images) != len(embeddings):
        raise ValueError("Each image must have an embedding")
    ensure_image_schema()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        for image, embedding in zip(images, embeddings):
            metadata = {key: value for key, value in image.items()
                        if key not in {"data", "object_key", "search_text", "image_id"}}
            cursor.execute("""
                INSERT INTO document_images
                    (image_id, document_id, page_number, image_number, object_key,
                     metadata, search_text, embedding)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s::vector)
            """, (image["image_id"], document_id, image["page_number"], image["image_number"],
                  image["object_key"], json.dumps(metadata), image["search_text"], str(embedding)))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def find_document_images(query_embedding=None, document_ids=None, page_number=None,
                         image_number=None, limit=25, image_id=None) -> list[dict]:
    # An explicitly empty scope must never fall back to all documents.
    if document_ids == []:
        return []
    ensure_image_schema()
    filters, values = [], []
    if document_ids is not None:
        filters.append("document_id IN (" + ", ".join(["%s"] * len(document_ids)) + ")")
        values.extend(document_ids)
    for field, value in (("page_number", page_number), ("image_number", image_number),
                         ("image_id", image_id)):
        if value is not None:
            filters.append(f"{field} = %s")
            values.append(value)
    where = " WHERE " + " AND ".join(filters) if filters else ""
    order = "embedding <-> %s::vector" if query_embedding is not None else "document_id, page_number, image_number"
    if query_embedding is not None:
        values.append(str(query_embedding))
    values.append(min(max(limit, 1), 100))
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT image_id, document_id, object_key, metadata, search_text, documents.source_key "
            f"FROM document_images JOIN documents ON documents.id = document_id{where} "
            f"ORDER BY {order} LIMIT %s", tuple(values),
        )
        images = []
        for image_id, document_id, key, metadata, search_text, source_key in cursor.fetchall():
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            images.append({**metadata, "image_id": image_id, "document_id": document_id,
                           "object_key": key, "search_text": search_text, "source_key": source_key})
        return images
    finally:
        conn.close()
