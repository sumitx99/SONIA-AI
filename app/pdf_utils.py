# app/pdf_utils.py

from langchain.text_splitter import RecursiveCharacterTextSplitter

def chunk_text(text: str, chunk_size: int = 1000, chunk_overlap: int = 100) -> list:
    """
    Splits a long text into smaller, overlapping chunks using a robust method
    that is aware of Markdown and paragraph structure.
    """
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", " ", ""],
    )
    
    chunks = text_splitter.split_text(text)
    return chunks