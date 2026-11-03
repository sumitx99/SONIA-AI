# app/embeddings.py

import os
import requests
from typing import List
import logging
import time

logger = logging.getLogger(__name__)

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
MODEL_NAME = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
# Must match the vector(768) columns in app/schema.sql.
EMBEDDING_DIMENSIONS = 768


def _normalize(values: List[float]) -> List[float]:
    # Reduced-size Gemini embeddings aren't unit length; retrieval uses L2 distance,
    # so normalise to keep distances comparable across texts.
    norm = sum(v * v for v in values) ** 0.5
    return [v / norm for v in values] if norm else values

# --- THIS IS THE CRITICAL CONSTANT ---
# Small batches reduce request size and make transient failures cheaper to retry.
GOOGLE_EMBEDDING_BATCH_SIZE = 20


def _embed_request(operation, data):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:{operation}"
    for attempt in range(4):
        try:
            response = requests.post(url, headers={"x-goog-api-key": GOOGLE_API_KEY or ""},
                                     json=data, timeout=(10, 60))
            if response.status_code not in (429, 500, 502, 503, 504) or attempt == 3:
                response.raise_for_status()
                return response.json()
            retry_after = response.headers.get("Retry-After", "")
            delay = min(float(retry_after), 10) if retry_after.isdigit() else 2 ** attempt
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 3:
                raise
            delay = 2 ** attempt
        logger.warning("Retrying embedding request after transient failure (attempt %s)", attempt + 1)
        time.sleep(delay)

def get_embedding(text: str) -> List[float]:
    """Generates an embedding for a SINGLE text string."""
    data = {"content": {"parts": [{"text": text}]}, "outputDimensionality": EMBEDDING_DIMENSIONS}

    return _normalize(_embed_request("embedContent", data)["embedding"]["values"])


def get_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """
    Generates embeddings for a large list of texts by automatically splitting them
    into smaller, compliant batches to respect the API's rate limit.
    """
    all_embeddings = []
    
    # --- THIS IS THE NEW LOGIC: "CHUNKING THE CHUNKS" ---
    # We iterate through the list of texts in steps of our batch size.
    for i in range(0, len(texts), GOOGLE_EMBEDDING_BATCH_SIZE):
        # Get the current sub-batch of texts
        batch_texts = texts[i:i + GOOGLE_EMBEDDING_BATCH_SIZE]
        
        logger.info(f"Processing batch {i//GOOGLE_EMBEDDING_BATCH_SIZE + 1} with {len(batch_texts)} chunks...")

        # Prepare the request for the current sub-batch
        requests_list = [{"model": f"models/{MODEL_NAME}", "content": {"parts": [{"text": text}]},
                          "outputDimensionality": EMBEDDING_DIMENSIONS} for text in batch_texts]
        data = {"requests": requests_list}

        # Make the API call for this specific sub-batch
        payload = _embed_request("batchEmbedContents", data)
        batch_embeddings = [_normalize(entry["values"]) for entry in payload["embeddings"]]
        if len(batch_embeddings) != len(batch_texts):
            raise ValueError("The embedding service returned an incomplete batch")
        all_embeddings.extend(batch_embeddings)
        
        # A short pause between batches (not after the last) to stay under rate limits.
        if i + GOOGLE_EMBEDDING_BATCH_SIZE < len(texts):
            time.sleep(0.5)

    logger.info(f"Successfully generated embeddings for all {len(all_embeddings)} chunks.")
    return all_embeddings
