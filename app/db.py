import os
import ssl
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


def get_connection():
    """Establishes and returns a database connection."""
    return pg8000.connect(
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT,
        ssl_context=_ssl_context(),
    )

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

def insert_embeddings(document_id, chunk_text, embedding):
    """Inserts a text chunk and its vector embedding into the database."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # --- THIS IS THE FIX ---
        # Convert the Python list to a string in the format pgvector expects: '[...]'
        embedding_str = str(embedding)
        
        cursor.execute(
            "INSERT INTO document_chunks (document_id, chunk_text, embedding) VALUES (%s, %s, %s)",
            (document_id, chunk_text, embedding_str) # Pass the string version
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
