import os
import pg8000
from dotenv import load_dotenv

load_dotenv()

DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))

def get_connection():
    """Establishes and returns a database connection."""
    return pg8000.connect(
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT
    )

def insert_file(filename, file_bytes):
    """Inserts a file into the documents table and returns its ID."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO documents (filename, file) VALUES (%s, %s) RETURNING id",
            (filename, file_bytes)
        )
        file_id = cursor.fetchone()[0]
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    return file_id

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

def search_embeddings(query_embedding, top_k=3):
    """Searches for the most similar embeddings in the database."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # Also convert the query embedding to a string for the search
        query_embedding_str = str(query_embedding)

        cursor.execute(
            """
            SELECT chunk_text
            FROM document_chunks
            ORDER BY embedding <-> %s
            LIMIT %s
            """,
            (query_embedding_str, top_k)
        )
        results = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return [{"chunk_text": r[0]} for r in results]