"""Create the database schema (tables, pgvector, image table). Run: python -m app.init_db"""

from pathlib import Path

from app.db import get_connection, ensure_document_schema
from app.image_db import ensure_image_schema


def main():
    # Drop comment lines first so a ";" inside a comment cannot split a statement.
    sql = "\n".join(line for line in Path(__file__).with_name("schema.sql").read_text().splitlines()
                    if not line.strip().startswith("--"))
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    conn = get_connection()
    try:
        cursor = conn.cursor()
        for statement in statements:
            cursor.execute(statement)
        conn.commit()
    finally:
        conn.close()
    ensure_document_schema()
    ensure_image_schema()
    conn = get_connection()
    try:
        conn.cursor().execute("ALTER TABLE document_images ENABLE ROW LEVEL SECURITY")
        conn.commit()
    finally:
        conn.close()
    print("Database schema is ready.")


if __name__ == "__main__":
    main()
