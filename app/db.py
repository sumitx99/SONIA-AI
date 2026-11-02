import os
import ssl
import threading
import time
from collections import deque
from functools import lru_cache

import pg8000
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


def _ssl_context():
    if not DB_SSLMODE or DB_SSLMODE == "disable":
        return None
    if DB_SSL_ROOT_CERT:
        return ssl.create_default_context(cafile=DB_SSL_ROOT_CERT)
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def _connect():
    return pg8000.connect(
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT,
        ssl_context=_ssl_context(),
    )


# Opening a TLS connection to a hosted Postgres costs ~1-3 s, so connections are reused.
# Callers keep the usual pattern: get_connection() ... finally conn.close().
_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "4"))
# A connection idle longer than this is pinged first: the pooler may have dropped it.
_PING_AFTER_SECONDS = 60
_pool: deque = deque()
_pool_lock = threading.Lock()


class _PooledConnection:
    """Proxy whose close() returns the connection to the pool instead of closing it."""

    def __init__(self, raw):
        self._raw = raw

    def __getattr__(self, name):
        return getattr(self._raw, name)

    def close(self):
        raw, self._raw = self._raw, None
        if raw is None:
            return
        try:
            raw.rollback()  # discard anything the caller left uncommitted
        except Exception:
            _close_quietly(raw)
            return
        with _pool_lock:
            if len(_pool) < _POOL_SIZE:
                _pool.append((raw, time.monotonic()))
                return
        _close_quietly(raw)


def _close_quietly(raw):
    try:
        raw.close()
    except Exception:
        pass


def get_connection():
    """Returns a database connection, reusing an idle one when it is still alive."""
    while True:
        with _pool_lock:
            item = _pool.pop() if _pool else None
        if item is None:
            return _PooledConnection(_connect())
        raw, idle_since = item
        if time.monotonic() - idle_since < _PING_AFTER_SECONDS:
            return _PooledConnection(raw)
        try:
            raw.run("SELECT 1")
            return _PooledConnection(raw)
        except Exception:
            _close_quietly(raw)

@lru_cache(maxsize=1)
def ensure_document_schema():
    """PDFs stored in R2 keep only their object key here, so `file` may be NULL."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS chat_id TEXT")
        cursor.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_key TEXT")
        cursor.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS user_id TEXT")
        cursor.execute("CREATE INDEX IF NOT EXISTS documents_user_idx ON documents(user_id)")
        cursor.execute("ALTER TABLE documents ALTER COLUMN file DROP NOT NULL")
        cursor.execute("CREATE INDEX IF NOT EXISTS documents_chat_idx ON documents(chat_id)")
        conn.commit()
    finally:
        conn.close()

def insert_file(filename, file_bytes, chat_id=None, user_id=None):
    """Inserts a file into the documents table and returns its ID.

    Pass file_bytes=None when the PDF itself is stored in R2 (see set_document_source_key).
    """
    ensure_document_schema()
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO documents (filename, file, chat_id, user_id) VALUES (%s, %s, %s, %s) RETURNING id",
            (filename, file_bytes, chat_id, user_id)
        )
        file_id = cursor.fetchone()[0]
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    return file_id

def set_document_source_key(document_id, source_key):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE documents SET source_key = %s WHERE id = %s", (source_key, document_id))
        conn.commit()
    finally:
        conn.close()

def delete_document(document_id):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM documents WHERE id = %s", (document_id,))
        conn.commit()
    finally:
        conn.close()

def insert_embeddings(document_id, chunks, embeddings, batch_size=100):
    """Inserts text chunks and their vectors in a few multi-row INSERTs on one connection."""
    if len(chunks) != len(embeddings):
        raise ValueError("Each chunk must have an embedding")
    conn = get_connection()
    try:
        cursor = conn.cursor()
        for start in range(0, len(chunks), batch_size):
            rows = list(zip(chunks[start:start + batch_size], embeddings[start:start + batch_size]))
            placeholders = ", ".join(["(%s, %s, %s::vector)"] * len(rows))
            values = [value for chunk, embedding in rows for value in (document_id, chunk, str(embedding))]
            cursor.execute(
                f"INSERT INTO document_chunks (document_id, chunk_text, embedding) VALUES {placeholders}",
                tuple(values),
            )
        conn.commit()
    finally:
        cursor.close()
        conn.close()

def search_embeddings(query_embedding, top_k=3, document_ids=None):
    """Searches for the most similar embeddings in the database."""
    if document_ids == []:
        return []
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # Also convert the query embedding to a string for the search
        query_embedding_str = str(query_embedding)

        where = ""
        values = []
        if document_ids is not None:
            where = " WHERE document_id IN (" + ", ".join(["%s"] * len(document_ids)) + ")"
            values.extend(document_ids)
        values.extend([query_embedding_str, top_k])
        cursor.execute(
            f"""
            SELECT chunk_text
            FROM document_chunks{where}
            ORDER BY embedding <-> %s::vector
            LIMIT %s
            """,
            tuple(values)
        )
        results = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return [{"chunk_text": r[0]} for r in results]


def owned_document_ids(user_id, document_ids=None):
    """The subset of document_ids owned by user_id; all of the user's documents when None."""
    if document_ids == []:
        return []
    ensure_document_schema()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        sql, values = "SELECT id FROM documents WHERE user_id = %s", [user_id]
        if document_ids is not None:
            sql += " AND id IN (" + ", ".join(["%s"] * len(document_ids)) + ")"
            values.extend(document_ids)
        cursor.execute(sql + " ORDER BY id", tuple(values))
        return [row[0] for row in cursor.fetchall()]
    finally:
        conn.close()


def get_document_source(document_id, user_id):
    """Returns {"file": bytes | None, "source_key": str | None}, or None if missing or not the user's."""
    ensure_document_schema()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT file, source_key FROM documents WHERE id = %s AND user_id = %s",
                       (document_id, user_id))
        row = cursor.fetchone()
        if not row:
            return None
        return {"file": bytes(row[0]) if row[0] is not None else None, "source_key": row[1]}
    finally:
        conn.close()
