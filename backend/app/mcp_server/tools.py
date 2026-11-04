"""Read-only MCP tools over the signed-in user's own documents."""

import asyncio

from mcp.types import ToolAnnotations

from app.core.db import list_user_documents, owned_document_ids, search_document_chunks
from app.services.context import answer_context
from app.services.embeddings import get_embedding
from app.services.images.image_db import find_document_images
from app.services.images.image_pipeline import image_attachments
from app.services.images.image_storage import R2ImageStorage
from app.services.llm import get_llm_response
from app.services.answer_verification import check_citations, with_footnotes
from app.mcp_server.server import current_mcp_user, mcp

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)


@mcp.tool(title="List documents", annotations=READ_ONLY)
async def list_documents() -> list[dict]:
    """List the PDFs the user has uploaded to Sonia (id, filename, upload time), newest first."""
    return await list_user_documents(current_mcp_user())


@mcp.tool(title="Search documents", annotations=READ_ONLY)
async def search_documents(query: str, document_ids: list[int] | None = None, top_k: int = 5) -> list[dict]:
    """Find the passages in the user's documents most relevant to `query`.

    Args:
        query: What to look for, in natural language.
        document_ids: Limit the search to these documents (from list_documents); all when omitted.
        top_k: How many passages to return (1-20).
    """
    scope = await owned_document_ids(current_mcp_user(), document_ids)
    embedding = await asyncio.to_thread(get_embedding, query)
    return await search_document_chunks(embedding, scope, max(1, min(top_k, 20)))


@mcp.tool(title="Ask Sonia", annotations=READ_ONLY)
async def ask_sonia(question: str, document_ids: list[int] | None = None) -> dict:
    """Ask Sonia a question; she answers from the user's documents (Markdown, with tables and maths).

    Args:
        question: The question, in any language.
        document_ids: Answer from these documents only (from list_documents); all when omitted.
    """
    context, meta = await answer_context(question, document_ids, document_ids is not None, False,
                                          current_mcp_user())
    answer = await asyncio.to_thread(get_llm_response, question, context)
    answer = with_footnotes(*await asyncio.to_thread(check_citations, answer, context))
    return {"answer": answer, "images": [
        {"document_id": image["document_id"], "page_number": image["page_number"],
         "caption": image["caption"], "url": image["url"]} for image in meta["images"]]}


@mcp.tool(title="Get image", annotations=READ_ONLY)
async def get_image(document_id: int, page_number: int, image_number: int | None = None) -> list[dict]:
    """Get figures from a page of one of the user's documents: caption and a temporary link (15 min).

    Args:
        document_id: The document (from list_documents).
        page_number: The page, starting at 1.
        image_number: Which image on that page (1 = first); all images on the page when omitted.
    """
    if not await owned_document_ids(current_mcp_user(), [document_id]):
        raise ValueError("No such document")
    storage = R2ImageStorage.from_env()
    if storage is None:
        raise ValueError("Image storage is not configured on this server")
    images = await find_document_images(document_ids=[document_id], page_number=page_number,
                                        image_number=image_number, limit=10)
    return [{"page_number": image["page_number"], "image_number": image["image_number"],
             "caption": image["caption"], "url": image["url"]}
            for image in image_attachments(images, storage)]
