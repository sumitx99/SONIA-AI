from app.db import get_connection
from app.embeddings import get_embedding

def rag_query(query: str):
    query_embedding = get_embedding(query)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT content, embedding <=> %s::vector AS distance
        FROM embeddings
        ORDER BY distance
        LIMIT 3;
        """,
        (query_embedding,)
    )
    results = cursor.fetchall()
    cursor.close()
    conn.close()

    return {"results": [{"content": r[0], "score": r[1]} for r in results]}
