"""What an answer is grounded in: the user's best-matching passages and, when asked, images."""

import asyncio
import logging

from app.core.db import owned_document_ids
from app.services.embeddings import get_embedding
from app.services.images.document_images import requested_image_location, wants_images
from app.services.images.image_db import find_document_images
from app.services.images.image_pipeline import image_attachments
from app.services.images.image_storage import R2ImageStorage
from app.services.llm import gemini_unavailable
from app.services.retriever import get_reranked_context, rank_contexts

logger = logging.getLogger(__name__)


async def answer_context(query, document_ids, scope_documents, include_images, user_id):
    """Retrieves the passages (and, when asked, images) an answer is grounded in.

    Image URLs come from retrieved metadata; the language model never invents them.
    Returns the prompt context and the image fields of the response.
    """
    try:
        query_embedding = await asyncio.to_thread(get_embedding, query)
    except Exception as error:
        if not gemini_unavailable(error):
            raise
        # Searching by meaning needs Gemini; keyword search keeps the documents usable meanwhile.
        logger.warning("Embedding service unavailable (%s); searching documents by keyword", error)
        query_embedding = None
    logger.info("Starting advanced retrieval with re-ranking...")
    requested = (document_ids or []) if scope_documents else document_ids
    # Only the signed-in user's documents are ever searched (None = all of theirs).
    scope = await owned_document_ids(user_id, requested)
    context = await get_reranked_context(query, query_embedding, document_ids=scope)

    images = []
    image_status = "not_requested"
    image_notice = None
    if include_images or wants_images(query):
        image_status = "disabled"
        image_notice = "Image storage is not configured on this server."
        try:
            storage = R2ImageStorage.from_env()
            if storage:
                page_number, image_number = requested_image_location(query)
                candidates = await find_document_images(query_embedding, document_ids=scope,
                                                         page_number=page_number, image_number=image_number)
                selected = await asyncio.to_thread(rank_contexts, query, candidates,
                                                   text_key="search_text", limit=5)
                images = image_attachments(selected, storage)
                image_status = "ready" if images else "not_found"
                image_notice = None if images else "No indexed image matched the requested document or location."
                if selected:
                    image_context = "\n\n".join(
                        f"Image ID: {image['image_id']}; document {image['document_id']}; "
                        f"page {image['page_number']}; image {image['image_number']}\n"
                        + image["search_text"] for image in selected
                    )
                    context += "\n\nImage source locations and surrounding text:\n" + image_context
        except Exception:
            logger.exception("Image retrieval failed")
            image_status = "failed"
            image_notice = "Image retrieval is temporarily unavailable."

        context += (
            "\n\nImage retrieval status: " + image_status + ". " + (image_notice or "")
            + "\nOnly the image locations and nearby text are available; the image pixels "
            "have not been analyzed. Do not invent visual details or image URLs. "
            "The application displays retrieved images separately. "
            "If no image was found, say so rather than claiming to display one."
        )

    if not context:
        logger.warning("No relevant context found after re-ranking for the query.")
    else:
        logger.info("Retrieved and re-ranked context successfully.")
    return context, {"images": images, "image_status": image_status, "image_notice": image_notice}
