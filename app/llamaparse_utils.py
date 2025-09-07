# app/llamaparse_utils.py

import os
import nest_asyncio
from llama_parse import LlamaParse
import logging

logger = logging.getLogger(__name__)

# Helper to allow async LlamaParse to run in a sync FastAPI endpoint.
nest_asyncio.apply()

def process_pdf_with_llamaparse(file_bytes: bytes, filename: str) -> str:
    """
    Uses LlamaParse to extract rich, layout-aware Markdown content from a PDF.
    """
    # LlamaParse works with file paths, so we create a temporary file
    temp_file_path = f"./{filename}"
    try:
        with open(temp_file_path, "wb") as f:
            f.write(file_bytes)

        parser = LlamaParse(
            api_key=os.getenv("LLAMA_CLOUD_API_KEY"),
            result_type="markdown",
            verbose=True
        )

        documents = parser.load_data(temp_file_path)
        full_markdown_content = "\n".join([doc.get_content() for doc in documents])
        return full_markdown_content

    except Exception as e:
        logger.error(f"An error occurred with LlamaParse API: {e}")
        return ""
    finally:
        # Clean up the temporary file
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)