import asyncio
import os
import ssl

import asyncpg
from dotenv import load_dotenv

# Load the project's .env by path so it works whatever directory the server starts from.
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
# "require" encrypts the connection (needed for Supabase); add DB_SSL_ROOT_CERT to also
# verify the server certificate. Leave blank for a local Postgres without SSL.
DB_SSLMODE = os.getenv("DB_SSLMODE", "").strip().lower()
DB_SSL_ROOT_CERT = os.getenv("DB_SSL_ROOT_CERT", "").strip()
# Opening a TLS connection to a hosted Postgres costs ~1-3 s, so a small pool is kept open.
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "4"))


def _ssl_context():
    if not DB_SSLMODE or DB_SSLMODE == "disable":
        return None
    if DB_SSL_ROOT_CERT:
        return ssl.create_default_context(cafile=DB_SSL_ROOT_CERT)
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


async def _init_connection(conn):
    # pgvector has no built-in asyncpg codec: exchange vectors as text ("[0.1, 0.2, ...]").
    schema = await conn.fetchval(
        "SELECT n.nspname FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace "
        "WHERE t.typname = 'vector' LIMIT 1")
    if schema:
        await conn.set_type_codec("vector", schema=schema, format="text",
                                  encoder=lambda value: value if isinstance(value, str) else str(list(value)),
                                  decoder=str)


_pool = None
_pool_lock = None


async def get_pool():
    """The shared asyncpg pool, created on first use. Use `async with (await get_pool()).acquire()`."""
    global _pool, _pool_lock
    if _pool is None:
        _pool_lock = _pool_lock or asyncio.Lock()
        async with _pool_lock:
            if _pool is None:
                _pool = await asyncpg.create_pool(
                    database=DB_NAME, user=DB_USER, password=DB_PASSWORD, host=DB_HOST, port=DB_PORT,
                    ssl=_ssl_context(), min_size=1, max_size=DB_POOL_SIZE,
                    # Recycle idle connections before a hosted pooler drops them.
                    max_inactive_connection_lifetime=60, init=_init_connection,
                )
    return _pool


async def close_pool():
    global _pool
    if _pool is not None:
        pool, _pool = _pool, None
        try:
            await pool.close()
        except RuntimeError:
            # The pool belongs to an event loop that has already closed (e.g. one app instance
            # per test); its connections can't be closed politely, so drop them.
            pool.terminate()


_document_schema_ready = False


async def ensure_document_schema():
    """PDFs stored in R2 keep only their object key here, so `file` may be NULL."""
    global _document_schema_ready
    if _document_schema_ready:
        return
    async with (await get_pool()).acquire() as conn:
        await conn.execute("""
            ALTER TABLE documents ADD COLUMN IF NOT EXISTS chat_id TEXT;
            ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_key TEXT;
            ALTER TABLE documents ADD COLUMN IF NOT EXISTS user_id TEXT;
            ALTER TABLE documents ADD COLUMN IF NOT EXISTS upload_request_id TEXT;
            ALTER TABLE documents ADD COLUMN IF NOT EXISTS upload_response JSONB;
            CREATE UNIQUE INDEX IF NOT EXISTS documents_upload_request_idx
                ON documents(user_id, upload_request_id) WHERE upload_request_id IS NOT NULL;
            CREATE INDEX IF NOT EXISTS documents_user_idx ON documents(user_id);
            ALTER TABLE documents ALTER COLUMN file DROP NOT NULL;
            CREATE INDEX IF NOT EXISTS documents_chat_idx ON documents(chat_id);
        """)
    _document_schema_ready = True


async def insert_file(filename, file_bytes, chat_id=None, user_id=None, request_id=None):
    """Inserts a file into the documents table and returns its ID.

    Pass file_bytes=None when the PDF itself is stored in R2 (see set_document_source_key).
    """
    await ensure_document_schema()
    async with (await get_pool()).acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO documents (filename, file, chat_id, user_id, upload_request_id) "
            "VALUES ($1, $2, $3, $4, $5) RETURNING id", filename, file_bytes, chat_id, user_id, request_id)


async def completed_upload(user_id, request_id):
    if not request_id:
        return None
    await ensure_document_schema()
    async with (await get_pool()).acquire() as conn:
        return await conn.fetchval("SELECT upload_response FROM documents "
                                   "WHERE user_id = $1 AND upload_request_id = $2", user_id, request_id)


async def finish_upload(document_id, response):
    import json
    async with (await get_pool()).acquire() as conn:
        await conn.execute("UPDATE documents SET upload_response = $1::jsonb WHERE id = $2",
                           json.dumps(response), document_id)


async def set_document_source_key(document_id, source_key):
    async with (await get_pool()).acquire() as conn:
        await conn.execute("UPDATE documents SET source_key = $1 WHERE id = $2", source_key, document_id)


async def delete_document(document_id):
    async with (await get_pool()).acquire() as conn:
        await conn.execute("DELETE FROM documents WHERE id = $1", document_id)


async def insert_embeddings(document_id, chunks, embeddings):
    """Inserts text chunks and their vectors in one transaction (asyncpg pipelines the rows)."""
    if len(chunks) != len(embeddings):
        raise ValueError("Each chunk must have an embedding")
    async with (await get_pool()).acquire() as conn:
        async with conn.transaction():
            await conn.executemany(
                "INSERT INTO document_chunks (document_id, chunk_text, embedding) VALUES ($1, $2, $3)",
                [(document_id, chunk, embedding) for chunk, embedding in zip(chunks, embeddings)])


async def search_embeddings(query_embedding, top_k=3, document_ids=None):
    """Searches for the most similar embeddings in the database."""
    if document_ids == []:
        return []
    where, values = "", [query_embedding, top_k]
    if document_ids is not None:
        where = " WHERE document_id = ANY($3::int[])"
        values.append(list(document_ids))
    async with (await get_pool()).acquire() as conn:
        rows = await conn.fetch(
            f"SELECT chunk_text FROM document_chunks{where} ORDER BY embedding <-> $1 LIMIT $2", *values)
    return [{"chunk_text": row["chunk_text"]} for row in rows]


async def owned_document_ids(user_id, document_ids=None):
    """The subset of document_ids owned by user_id; all of the user's documents when None."""
    if document_ids == []:
        return []
    await ensure_document_schema()
    sql, values = "SELECT id FROM documents WHERE user_id = $1", [user_id]
    if document_ids is not None:
        sql += " AND id = ANY($2::int[])"
        values.append(list(document_ids))
    async with (await get_pool()).acquire() as conn:
        rows = await conn.fetch(sql + " ORDER BY id", *values)
    return [row["id"] for row in rows]


async def get_document_source(document_id, user_id):
    """Returns {"file": bytes | None, "source_key": str | None}, or None if missing or not the user's."""
    await ensure_document_schema()
    async with (await get_pool()).acquire() as conn:
        row = await conn.fetchrow("SELECT file, source_key FROM documents WHERE id = $1 AND user_id = $2",
                                  document_id, user_id)
    if not row:
        return None
    return {"file": bytes(row["file"]) if row["file"] is not None else None, "source_key": row["source_key"]}


async def list_user_documents(user_id, limit=100):
    """The user's documents, newest first."""
    await ensure_document_schema()
    async with (await get_pool()).acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, filename, chat_id, uploaded_at FROM documents WHERE user_id = $1 "
            "ORDER BY uploaded_at DESC, id DESC LIMIT $2", user_id, limit)
    return [{"id": row["id"], "filename": row["filename"], "chat_id": row["chat_id"],
             "uploaded_at": row["uploaded_at"].isoformat() if row["uploaded_at"] else None} for row in rows]


async def search_document_chunks(query_embedding, document_ids, top_k=5):
    """Like search_embeddings, but says which document each passage came from.

    `document_ids` must already be limited to what the caller may see; [] finds nothing.
    """
    if not document_ids:
        return []
    async with (await get_pool()).acquire() as conn:
        rows = await conn.fetch(
            "SELECT c.document_id, d.filename, c.chunk_text FROM document_chunks c "
            "JOIN documents d ON d.id = c.document_id WHERE c.document_id = ANY($2::int[]) "
            "ORDER BY c.embedding <-> $1 LIMIT $3", query_embedding, list(document_ids), top_k)
    return [{"document_id": row["document_id"], "filename": row["filename"], "text": row["chunk_text"]}
            for row in rows]
