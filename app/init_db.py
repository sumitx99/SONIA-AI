"""Create the database schema (tables, pgvector, image table). Run: python -m app.init_db"""

import asyncio
from pathlib import Path

from app.db import close_pool, ensure_document_schema, get_pool
from app.image_db import ensure_image_schema
from app.conversations import ensure_conversation_schema
from app.profiles import ensure_profile_schema


async def main():
    sql = Path(__file__).with_name("schema.sql").read_text()
    try:
        async with (await get_pool()).acquire() as conn:
            await conn.execute(sql)  # a whole script runs as one simple query
        # Reopen the pool so new connections register the vector codec now that it exists.
        await close_pool()
        await ensure_document_schema()
        await ensure_image_schema()
        await ensure_conversation_schema()
        await ensure_profile_schema()
        async with (await get_pool()).acquire() as conn:
            await conn.execute("ALTER TABLE document_images ENABLE ROW LEVEL SECURITY")
    finally:
        await close_pool()
    print("Database schema is ready.")


if __name__ == "__main__":
    asyncio.run(main())
