# app/retriever.py

import logging
from sentence_transformers.cross_encoder import CrossEncoder
from app.db import search_embeddings

logger = logging.getLogger(__name__)

# --- Initialize the Cross-Encoder Model ---
logger.info("Loading Cross-Encoder model (ms-marco-MiniLM-L-6-v2)...")
cross_encoder = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
logger.info("Cross-Encoder model loaded.")


def get_reranked_context(query: str, query_embedding: list) -> str:
    """
    Performs a two-stage retrieval process for high-precision context.
    """
    # --- STAGE 1: Initial Retrieval (Broad Net) ---
    CANDIDATE_COUNT = 25
    logger.info(f"Retrieving top {CANDIDATE_COUNT} candidates from the database...")
    initial_results = search_embeddings(query_embedding, top_k=CANDIDATE_COUNT)

    if not initial_results:
        logger.warning("Initial retrieval from DB returned no results.")
        return ""

    # --- STAGE 2: Re-ranking with Cross-Encoder (Fine-toothed Comb) ---
    logger.info(f"Re-ranking {len(initial_results)} candidates with Cross-Encoder...")
    
    model_input_pairs = [[query, result["chunk_text"]] for result in initial_results]
    scores = cross_encoder.predict(model_input_pairs)
    results_with_scores = zip(scores, initial_results)
    sorted_results = sorted(results_with_scores, key=lambda x: x[0], reverse=True)

    # --- Final Selection ---
    FINAL_CONTEXT_COUNT = 5
    logger.info(f"Selecting top {FINAL_CONTEXT_COUNT} results after re-ranking.")
    
    top_results = sorted_results[:FINAL_CONTEXT_COUNT]
    context = "\n\n---\n\n".join([result["chunk_text"] for score, result in top_results])
    
    return context