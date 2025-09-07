# app/embeddings.py

import os
import requests
from typing import List
import logging
import time

logger = logging.getLogger(__name__)

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
MODEL_NAME = "text-embedding-004"

# --- THIS IS THE CRITICAL CONSTANT ---
# Google's API limit is 100 per batch. We'll use a slightly smaller number for safety.
GOOGLE_EMBEDDING_BATCH_SIZE = 99

def get_embedding(text: str) -> List[float]:
    """Generates an embedding for a SINGLE text string."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:embedContent?key={GOOGLE_API_KEY}"
    headers = {"Content-Type": "application/json"}
    data = {"content": {"parts": [{"text": text}]}}

    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    embedding = response.json()["embedding"]["values"]
    return embedding


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
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:batchEmbedContents?key={GOOGLE_API_KEY}"
        headers = {"Content-Type": "application/json"}
        requests_list = [{"model": f"models/{MODEL_NAME}", "content": {"parts": [{"text": text}]}} for text in batch_texts]
        data = {"requests": requests_list}

        # Make the API call for this specific sub-batch
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        
        # Extract the embeddings from the response and add them to our main list
        batch_embeddings = [entry["values"] for entry in response.json()["embeddings"]]
        all_embeddings.extend(batch_embeddings)
        
        # Optional: Add a small delay between batches to be a good API citizen
        time.sleep(0.5)

    logger.info(f"Successfully generated embeddings for all {len(all_embeddings)} chunks.")
    return all_embeddings