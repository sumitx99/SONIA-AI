import uuid
import datetime
from db import get_connection

def store_pdf(file_path):
    conn = get_connection()
    cur = conn.cursor()

    file_id = str(uuid.uuid4())
    filename = file_path.split("/")[-1]

    with open(file_path, "rb") as f:
        file_data = f.read()

    cur.execute("""
        INSERT INTO documents (file_id, filename, file, uploaded_at)
        VALUES (%s, %s, %s, %s)
        RETURNING id
    """, (file_id, filename, file_data, datetime.datetime.now()))

    document_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return document_id


def store_chunks(document_id, chunks, embeddings):
    conn = get_connection()
    cur = conn.cursor()

    for chunk, embedding in zip(chunks, embeddings):
        embedding_str = "[" + ",".join([str(x) for x in embedding]) + "]"
        cur.execute("""
            INSERT INTO document_chunks (document_id, chunk_text, embedding)
            VALUES (%s, %s, %s)
        """, (document_id, chunk, embedding_str))

    conn.commit()
    conn.close()
