#
# Final app/main.py with Stateless Querying
#

import shutil
import hashlib
from pathlib import Path
from fastapi import FastAPI, File, UploadFile, HTTPException
from pydantic import BaseModel

# We import two distinct functions from our pipeline now
from .rag_pipeline import process_and_cache_file, load_rag_chain

# Initialize FastAPI app
app = FastAPI(
    title="Persistent RAG Bot API",
    description="Upload a PDF and query it anytime using its unique file_id.",
    version="5.0.0"
)

# --- Pydantic Models ---
class ProcessResponse(BaseModel):
    file_id: str
    filename: str
    message: str
    is_new: bool

class QueryRequest(BaseModel):
    file_id: str
    query: str

class QueryResponse(BaseModel):
    response: str

# --- Helper Function ---
def calculate_file_hash(file_path: Path) -> str:
    """Calculates the SHA256 hash of a file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            hasher.update(chunk)
    return hasher.hexdigest()

# --- API Endpoints ---
@app.get("/", summary="Root endpoint")
async def root():
    return {"message": "Welcome to the Persistent RAG Bot API!"}

@app.post("/process_pdf", response_model=ProcessResponse, summary="Upload a PDF to make it queryable")
async def process_pdf(file: UploadFile = File(...)):
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload a PDF.")

    temp_dir = Path("temp_files")
    temp_dir.mkdir(exist_ok=True)
    # Use a generic name as it will be deleted shortly
    temp_file_path = temp_dir / "upload.pdf"

    try:
        with temp_file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        file_id = calculate_file_hash(temp_file_path)

        # The pipeline function will now handle creating the vector store on disk if it doesn't exist
        is_new = process_and_cache_file(temp_file_path, file_id)
        
        message = "File processed successfully and saved." if is_new else "File was already processed. Ready to be queried."
        
        return {
            "file_id": file_id,
            "filename": file.filename,
            "message": message,
            "is_new": is_new
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process file: {str(e)}")
    finally:
        if temp_file_path.exists():
            temp_file_path.unlink()
        file.file.close()


@app.post("/query", response_model=QueryResponse, summary="Ask a question about a previously processed PDF")
async def process_query(request: QueryRequest):
    """
    This endpoint is now stateless. It loads the required vector store from disk for every query.
    """
    try:
        # Load the RAG chain on-demand using the file_id
        rag_chain = load_rag_chain(request.file_id)
        
        if not rag_chain:
            raise HTTPException(status_code=404, detail="File ID not found. Please process the PDF first via the /process_pdf endpoint.")

        response_text = rag_chain.invoke(request.query)
        return {"response": response_text}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error during query processing: {str(e)}")