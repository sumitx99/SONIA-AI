# app/app.py

import logging
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from requests.exceptions import HTTPError

# --- MODIFIED IMPORTS ---
from app.db import insert_file, insert_embeddings
from app.embeddings import get_embedding, get_embeddings_batch
from app.llm import get_llm_response
from app.pdf_utils import chunk_text
from app.llamaparse_utils import process_pdf_with_llamaparse # Replaced Docling with LlamaParse
from app.retriever import get_reranked_context

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Sonia Advanced RAG API")

origins = [ "http://localhost:3000" ]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", tags=["General"])
async def root():
    return {"message": "Sonia Advanced RAG Chatbot API is running 🚀"}

@app.post("/upload", tags=["Document Handling"])
async def upload_pdf(file: UploadFile = File(...)):
    try:
        logger.info(f"Receiving file: {file.filename}")
        file_bytes = await file.read()
        
        file_id = insert_file(file.filename, file_bytes)
        logger.info(f"File '{file.filename}' stored with ID: {file_id}")

        # --- QUALITY UPGRADE: Use LlamaParse for layout-aware parsing ---
        logger.info("Processing document with LlamaParse...")
        # THIS IS THE MAIN LOGIC CHANGE
        rich_content = process_pdf_with_llamaparse(file_bytes, file.filename)
        
        if not rich_content:
            raise HTTPException(status_code=500, detail="Failed to process document with LlamaParse.")
        
        # --- Chunk the high-quality Markdown content ---
        chunks = chunk_text(rich_content)
        logger.info(f"Extracted {len(chunks)} chunks from the LlamaParse output.")

        # --- SPEED UPGRADE: Generate all embeddings in one batch ---
        logger.info(f"Generating embeddings for {len(chunks)} chunks in a single batch.")
        all_embeddings = get_embeddings_batch(chunks)
        
        # --- Store the results ---
        logger.info("Storing chunks and embeddings in the database.")
        for i, chunk in enumerate(chunks):
            insert_embeddings(file_id, chunk, all_embeddings[i])

        return {"file_id": file_id, "filename": file.filename, "chunks_stored": len(chunks)}

    except HTTPError as e:
        logger.error(f"HTTPError during API call: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to communicate with an external AI service: {e.response.text}")
    except Exception as e:
        logger.error(f"An unexpected error occurred during file upload: {e}")
        raise HTTPException(status_code=500, detail=f"An internal server error occurred: {str(e)}")


# The /chat endpoint does not need to be changed. It works perfectly with the new system.
@app.post("/chat", tags=["Chat"])
async def chat(query: str = Form(...)):
    try:
        logger.info(f"Received query: '{query}'")
        query_embedding = get_embedding(query)
        logger.info("Starting advanced retrieval with re-ranking...")
        context = get_reranked_context(query, query_embedding)
        
        if not context:
            logger.warning("No relevant context found after re-ranking for the query.")
        else:
            logger.info("Retrieved and re-ranked context successfully.")

        answer = get_llm_response(query, context)
        logger.info("Generated LLM response.")
        return {"query": query, "answer": answer}
        
    except HTTPError as e:
        logger.error(f"HTTPError during LLM call: {e}")
        raise HTTPException(status_code=503, detail=f"The AI service is temporarily unavailable: {e.response.text}")
    except Exception as e:
        logger.error(f"An unexpected error occurred during chat: {e}")
        raise HTTPException(status_code=500, detail=f"An internal server error occurred: {str(e)}")