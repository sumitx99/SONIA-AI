# app/retriever.py

import logging
import os
from functools import lru_cache
from app.db import search_embeddings

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


def get_reranked_context(query: str, query_embedding: list, document_ids=None) -> str:
    """
    Performs a two-stage retrieval process for high-precision context.
    """
    # --- STAGE 1: Initial Retrieval (Broad Net) ---
    CANDIDATE_COUNT = 25
    logger.info(f"Retrieving top {CANDIDATE_COUNT} candidates from the database...")
    initial_results = search_embeddings(query_embedding, top_k=CANDIDATE_COUNT,
                                        document_ids=document_ids)

    if not initial_results:
        logger.warning("Initial retrieval from DB returned no results.")
        return ""

    # --- STAGE 2: Re-ranking with Cross-Encoder (Fine-toothed Comb) ---
    logger.info(f"Re-ranking {len(initial_results)} candidates with Cross-Encoder...")
    
    # --- Final Selection ---
    FINAL_CONTEXT_COUNT = 5
    logger.info(f"Selecting top {FINAL_CONTEXT_COUNT} results after re-ranking.")
    
    top_results = rank_contexts(query, initial_results, limit=FINAL_CONTEXT_COUNT)
    context = "\n\n---\n\n".join(result["chunk_text"] for result in top_results)
    
    return context
