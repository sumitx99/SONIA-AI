# Sonia - An Advanced RAG Chatbot 🚀

**Sonia** is a high-performance, high-accuracy Retrieval-Augmented Generation (RAG) chatbot built from the ground up by **Sumit Ranjan**. It's designed to solve two major problems in traditional RAG systems: **slow document processing** and **inaccurate, out-of-context answers**.

This isn't just a demo — it's a production-grade application with a modern tech stack and an advanced retrieval pipeline that actually delivers helpful results.

<p align="center">
  <img src="https://i.ibb.co/prkhfBr7/Screenshot-2025-09-07-222958.png" alt="Sonia Demo" />
</p>

---

## ✨ Core Features

- **📄 High-Quality Document Parsing:**  
  Uses [LlamaParse](https://cloud.llamaindex.ai) for layout-aware parsing. Titles, paragraphs, and even tables are extracted with structure, turning PDFs into clean, AI-readable chunks.

- **⚡ High-Speed Ingestion:**  
  Batch embedding API calls make ingestion blazingly fast, even for large multi-page PDFs.

- **🎯 High-Precision Retrieval Pipeline:**  
  A two-stage retrieval system:
  - **Fast Search:** Vector search fetches top 25 relevant chunks.
  - **Smart Re-ranking:** A Cross-Encoder model ranks them for the best 5 matches.

- **🧠 Reduced Hallucinations:**  
  The final prompt is tightly controlled — the LLM answers *only* from the retrieved document context.

- **🧰 Fully Modern Tech Stack:**  
  FastAPI backend, React/Next.js frontend, Gemini models, PostgreSQL + pgvector, and more.

---

## 🛠️ Tech Stack & Architecture

### Backend:
- **Framework:** FastAPI
- **Database:** PostgreSQL + pgvector
- **Parsing:** LlamaParse
- **Embeddings:** Google Gemini `text-embedding-004`
- **Re-ranking:** `sentence-transformers` Cross-Encoder
- **Generation:** Google Gemini `gemini-1.5-flash`
- **Other:** LangChain (chunking), Uvicorn, Pydantic

### Frontend:
- **Framework:** React + Next.js
- **UI:** shadcn/ui, Tailwind CSS
- **Icons:** Lucide React

---

# 🏛️ High-Level Architecture

This system is designed to handle document ingestion and question answering using a two-pipeline architecture.

---

## 📥 Ingestion Pipeline (Uploading a PDF)

```
PDF Upload 
   ↓
LlamaParse 
   ↓
Smart Chunking 
   ↓
Batch Embedding 
   ↓
Store in pgvector
```

### Steps:
1. **PDF Upload**: User uploads a PDF document.
2. **LlamaParse**: Parses the PDF into structured text.
3. **Smart Chunking**: Breaks down the text into semantically meaningful chunks.
4. **Batch Embedding**: Converts chunks into vector embeddings.
5. **Store in pgvector**: Saves the embeddings into a `pgvector` PostgreSQL database for efficient retrieval.

---

## ❓ Retrieval & Generation Pipeline (Asking a Question)

```
User Query 
   ↓
Embed Query 
   ↓
Fast Vector Search (Top 25) 
   ↓
Re-rank with Cross-Encoder (Top 5) 
   ↓
Build Prompt 
   ↓
Gemini LLM 
   ↓
Get Answer
```

### Steps:
1. **User Query**: A user inputs a natural language question.
2. **Embed Query**: The query is transformed into a vector embedding.
3. **Fast Vector Search**: Quickly retrieves top 25 most relevant chunks using pgvector.
4. **Re-rank with Cross-Encoder**: Applies a more accurate re-ranking to select the top 5.
5. **Build Prompt**: Constructs a context-rich prompt using the top chunks.
6. **Gemini LLM**: Passes the prompt to the Gemini Large Language Model.
7. **Get Answer**: Returns a precise and context-aware answer to the user.

---

## 🧠 Tech Stack

- **LlamaParse**: PDF parsing and text extraction
- **Vector DB**: `pgvector` extension for PostgreSQL
- **Embeddings**: Vector representations for semantic search
- **Cross-Encoder**: Improves retrieval precision via re-ranking
- **LLM**: Gemini by Google for answer generation

---

## 📌 Notes

- Optimized for semantic search and high-accuracy Q&A.
- Modular design allows replacing components (e.g., LLM or embedding model).

### ✅ Prerequisites
- Python 3.10+
- Node.js + npm (or yarn/pnpm)
- PostgreSQL 15+ with `pgvector` extension
- Git

---

