#
# Final app/rag_pipeline.py with Stateless Loading
#

import os
from pathlib import Path
from dotenv import load_dotenv

from llama_parse import LlamaParse
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableBranch, RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from langchain_core.documents import Document

load_dotenv()

# --- Global Settings ---
VECTOR_STORE_DIR = Path("vector_stores")
VECTOR_STORE_DIR.mkdir(exist_ok=True)

# --- Reusable Helper Function to Build the Chain ---
def _build_rag_chain(retriever):
    """Builds the common RAG chain logic using a given retriever."""
    llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash-latest", temperature=0.7)
    
    PROMPT_TEMPLATE = """
**Persona and Language:**
Tumhara naam Sonia hai. Tum ek friendly AI assistant ho. Users se Hinglish (Hindi + English mix) mein baat karo if they are asking in hingish otherwise prefer to answer in English, bilkul jaise ek dost se karte hain. Your tone should be casual and helpful.
**Core Task:**
The user has uploaded a document. Your primary job is to answer questions based on the context provided below.
**Context from the document:**
{context}
**User's Question:**
{question}
**Rules for Answering:**
1.  **PDF-Related Questions:** If the user's question can be answered from the provided Context, answer it accurately. Apne jawab ko short and to-the-point rakho.
2.  **General Questions:** If the Context doesn't contain the answer, it's okay to answer general knowledge questions based on your own training.
3.  **Irrelevant & Safe Questions:** If the user asks something completely irrelevant and not in the PDF, gently steer them back.
4.  **Unethical or Malicious Questions:** If the user asks something unethical, harmful, malicious, or dangerous, refuse to answer directly. Just say, "Sorry, I can't answer that question. It seems malicious and unethical."
"""
    prompt = ChatPromptTemplate.from_template(PROMPT_TEMPLATE)

    # --- THIS IS THE CORRECTED LOGIC ---

    # This is the final part of the chain that takes the formatted dictionary and gets an answer.
    final_processing_chain = prompt | llm | StrOutputParser()

    # This chain is for the GENERAL path. It takes the dictionary from the previous step,
    # replaces the "context" with a placeholder, and then sends it for final processing.
    general_chain = RunnablePassthrough.assign(
        context=lambda x: "No relevant context found."
    ) | final_processing_chain

    # This chain is for the RAG path. It just passes the dictionary straight through
    # to the final processing since the context is already correct.
    rag_chain = final_processing_chain

    # The branch decides which of the above chains to use based on the context length.
    branch = RunnableBranch(
        (lambda x: len(x["context"]) == 0, general_chain),  # If no context, use general_chain
        rag_chain,  # Otherwise, use rag_chain
    )

    # This is the full, final chain.
    # It starts by creating the dictionary with context and the original question.
    # Then, it passes that dictionary to the branch for routing.
    return {"context": retriever, "question": RunnablePassthrough()} | branch

# --- Public Function 1: Processing New Files ---
def process_and_cache_file(file_path: Path, file_id: str) -> bool:
    """
    Processes a PDF file and saves its vector store to disk.
    Returns True if a new store was created, False if it already existed.
    """
    db_path = VECTOR_STORE_DIR / file_id
    if db_path.exists():
        print(f"Vector store for file_id {file_id} already exists. Skipping processing.")
        return False

    print(f"Creating new vector store for file_id {file_id}...")
    parser = LlamaParse(api_key=os.getenv("LLAMA_CLOUD_API_KEY"), result_type="markdown")
    documents = parser.load_data(str(file_path))
    if not documents:
        raise ValueError("LlamaParse returned zero documents.")

    langchain_documents = [Document(page_content=doc.get_content(), metadata=doc.metadata) for doc in documents]
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
    splits = text_splitter.split_documents(langchain_documents)
    if not splits:
        raise ValueError("Text splitting resulted in zero chunks.")

    embedding_model = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
    
    # This creates the vector store and saves it to disk
    Chroma.from_documents(
        documents=splits,
        embedding=embedding_model,
        persist_directory=str(db_path)
    )
    print(f"Successfully created and saved vector store at {db_path}")
    return True

# --- Public Function 2: Loading for Querying ---
def load_rag_chain(file_id: str):
    """
    Loads an existing vector store from disk and returns a runnable RAG chain.
    Returns None if the vector store does not exist.
    """
    db_path = VECTOR_STORE_DIR / file_id
    if not db_path.exists():
        return None

    print(f"Loading vector store from {db_path} for querying.")
    embedding_model = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
    vectorstore = Chroma(
        persist_directory=str(db_path),
        embedding_function=embedding_model
    )
    retriever = vectorstore.as_retriever()

    # --- THIS IS THE FIX ---
    # We no longer build part of the chain here.
    # We simply call the helper function which builds the ENTIRE chain from start to finish.
    return _build_rag_chain(retriever)