# app/retriever.py

import asyncio
import logging
import os
import json
from functools import lru_cache
from app.core.db import search_embeddings

logger = logging.getLogger(__name__)

@lru_cache(maxsize=1)
def _get_cross_encoder():
    # RERANKER=off keeps torch out of memory (e.g. Render's free plan); results then keep
    # pgvector's similarity order. Also used when sentence-transformers isn't installed.
    if os.getenv("RERANKER", "cross-encoder").strip().lower() == "off":
        logger.info("Re-ranking is off; using vector similarity order.")
        return None
    try:
        from sentence_transformers.cross_encoder import CrossEncoder
    except ImportError:
        logger.warning("sentence-transformers is not installed; using vector similarity order.")
        return None

    logger.info("Loading Cross-Encoder model (ms-marco-MiniLM-L-6-v2)...")
    return CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')


def rank_contexts(query, results, text_key="chunk_text", limit=5):
    if not results:
        return []
    encoder = _get_cross_encoder()
    if encoder is None:
        return results[:limit]
    scores = encoder.predict([[query, result[text_key]] for result in results])
    return [result for _, result in sorted(zip(scores, results),
                                           key=lambda item: item[0], reverse=True)[:limit]]


async def get_reranked_context(query: str, query_embedding: list, document_ids=None) -> str:
    """
    Performs a two-stage retrieval process for high-precision context.
    """
    # --- STAGE 1: Initial Retrieval (Broad Net) ---
    CANDIDATE_COUNT = 25
    logger.info(f"Retrieving top {CANDIDATE_COUNT} candidates from the database...")
    initial_results = await search_embeddings(query_embedding, top_k=CANDIDATE_COUNT,
                                              document_ids=document_ids)

    if not initial_results:
        logger.warning("Initial retrieval from DB returned no results.")
        return ""

    # --- STAGE 2: Re-ranking with Cross-Encoder (Fine-toothed Comb) ---
    logger.info(f"Re-ranking {len(initial_results)} candidates with Cross-Encoder...")
    
    # --- Final Selection ---
    FINAL_CONTEXT_COUNT = 5
    logger.info(f"Selecting top {FINAL_CONTEXT_COUNT} results after re-ranking.")
    
    # The cross-encoder is CPU-bound; keep it off the event loop.
    top_results = await asyncio.to_thread(rank_contexts, query, initial_results, limit=FINAL_CONTEXT_COUNT)
    # Keep provenance attached to each passage; never guess pages for legacy chunks.
    sources = []
    for result in top_results:
        if not all(key in result for key in ("chunk_id", "document_id", "filename")):
            continue
        sources.append({"id": f"D{result['chunk_id']}", "title": result["filename"],
                        "document_id": result["document_id"], "chunk_id": result["chunk_id"],
                        "text": result["chunk_text"], "kind": "document"})
    context = "SONIA_DOCUMENT_EVIDENCE\n" + json.dumps({"sources": sources}, ensure_ascii=False)
    
    return context
