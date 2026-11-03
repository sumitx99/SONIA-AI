# Sonia - An Advanced RAG Chatbot 🚀

**Sonia** is a high-performance, high-accuracy Retrieval-Augmented Generation (RAG) chatbot built from the ground up by **Sumit Ranjan**. It's designed to solve two major problems in traditional RAG systems: **slow document processing** and **inaccurate, out-of-context answers**.

This isn't just a demo — it's a production-grade application with a modern tech stack and an advanced retrieval pipeline that actually delivers helpful results.

<p align="center">
  <img src="https://i.ibb.co/prkhfBr7/Screenshot-2025-09-07-222958.png" alt="Sonia Demo" />
</p>

---

## ✨ Core Features

- **📄 High-Quality Document Parsing:**  
  Uses [Docling](https://github.com/docling-project/docling) locally for layout-aware parsing — no API key. Titles, paragraphs, and even tables are extracted with structure, turning PDFs into clean, AI-readable chunks. If Docling fails, plain text is extracted with PyMuPDF so uploads still work.

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
- **Parsing:** Docling (local), PyMuPDF fallback
- **Embeddings:** Google Gemini `gemini-embedding-001` (768 dimensions)
- **Re-ranking:** `sentence-transformers` Cross-Encoder
- **Generation:** Google Gemini `gemini-3.5-flash` (set `GEMINI_CHAT_MODEL` to change)
- **Other:** LangChain (chunking), Uvicorn, Pydantic

### Frontend:
- **Framework:** React + Next.js
- **UI:** shadcn/ui, Tailwind CSS
- **Icons:** Lucide React

---

## 📁 Project structure

```
SONIA-AI/
├── backend/                  FastAPI API (deployed on Render)
│   ├── app/
│   │   ├── main.py           app, routers, CORS, MCP server mounted at /mcp
│   │   ├── core/             config (.env), auth (Supabase JWT), db (asyncpg), schema.sql, init_db
│   │   ├── api/              HTTP routes: chat, documents, conversations, profiles
│   │   ├── services/         llm (Gemini), embeddings, retriever, context (what answers are grounded in)
│   │   │   ├── parsing/      PDF → text: Docling or PyMuPDF, chunking
│   │   │   └── images/       PDF images: extraction, R2 storage, search
│   │   ├── mcp_client/       Sonia using the user's MCP servers as tools
│   │   └── mcp_server/       other apps (Claude, Cursor…) using Sonia over MCP
│   ├── tests/
│   ├── scripts/              dev_notes_mcp.py, a local MCP server for testing
│   ├── requirements.txt      (requirements-full.txt adds Docling and the re-ranker)
│   └── .env.example
├── frontend/                 Next.js app (deployed on Vercel)
│   ├── app/                  pages: landing, auth, chat, oauth/consent; styles/
│   ├── components/
│   │   ├── chat/             answers: Markdown, charts (GraphComponent), images, tool calls
│   │   ├── account/          account menu, Connections
│   │   ├── landing/          landing page animations
│   │   └── ui/               shadcn primitives
│   ├── lib/                  api client, supabase; hooks/; markdown/ (chart spec, filters)
│   └── tests/
├── render.yaml               Render Blueprint (rootDir: backend)
└── DEPLOY.md
```

### Run locally

```bash
cd backend
cp .env.example .env            # then fill it in
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m app.core.init_db
.venv/bin/uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend
cp .env.example .env.local      # then fill it in
npm install
npm run dev                     # http://localhost:3000
```

# 🏛️ High-Level Architecture

This system is designed to handle document ingestion and question answering using a two-pipeline architecture.

---

## 📥 Ingestion Pipeline (Uploading a PDF)

```
PDF Upload 
   ↓
Docling 
   ↓
Smart Chunking 
   ↓
Batch Embedding 
   ↓
Store in pgvector
```

### Steps:
1. **PDF Upload**: User uploads a PDF document.
2. **Docling**: Converts the PDF into structured Markdown on the server (set `DOCLING_OCR=true` for scanned PDFs).
3. **Smart Chunking**: Splits Markdown by headings and subsections (ATX `#`–`######` and underlined headings), then recursively splits large section bodies into chunks of up to 1,000 characters with a target overlap of 100 characters. Every chunk includes its heading path, such as `Section: Handbook > Leave Policy > Annual Leave`, in the embedded and stored text. Overlap stays within the same section; documents without headings use recursive splitting. The heading prefix is additional to the body size limit. Fenced code blocks do not create sections.
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

- **Docling**: PDF parsing and text extraction
- **Vector DB**: `pgvector` extension for PostgreSQL
- **Embeddings**: Vector representations for semantic search
- **Cross-Encoder**: Improves retrieval precision via re-ranking
- **LLM**: Gemini by Google for answer generation

---

## 📌 Notes

- Optimized for semantic search and high-accuracy Q&A.
- Modular design allows replacing components (e.g., LLM or embedding model).
- Chunking changes apply to new uploads. Existing documents must be reprocessed and their old chunks replaced to use section-aware retrieval; uploading again alone does not remove old chunks.

## Document images and source context

PDF uploads can also extract displayed raster-image occurrences and upload their visible crops to a private Cloudflare R2 bucket. Each occurrence has a unique ID, document ID, page number, per-page image number, bounding box in unrotated PDF points, page size/rotation, and a best-effort Markdown heading path. Repeated images keep separate locations. The two preceding and two following extracted text blocks are saved with their own page numbers, bounding boxes and block numbers, including neighbors on adjacent pages.

Image retrieval embeds the heading and surrounding text; it does not analyze image pixels. Scans without a text layer may have empty before/after text. Geometric reading order is approximate for complex multi-column layouts. Pure vector drawings are not detected as independent images by this implementation.

### Configuration

Install `backend/requirements.txt`, copy `backend/.env.example` to `backend/.env`, and configure the existing database and model services. To enable images, set all of:

```dotenv
R2_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=<access-key-id>
R2_SECRET_ACCESS_KEY=<secret-access-key>
R2_BUCKET_NAME=<private-bucket>
R2_IMAGE_URL_TTL=900
```

The R2 credential needs object read/write/delete access to that bucket (delete supports cleanup after a failed ingestion). Leave all four connection settings blank to keep text-only uploads. Partial configuration is reported as an image-processing failure while the uploaded text remains usable. The `document_images` table and location index are created on first image ingestion or retrieval, using the existing pgvector installation; the DB user needs permission to create them. Original PDF bytes remain in the existing `documents` table. R2 object keys are stored in the DB; fresh temporary GET URLs are generated for responses.

Only new uploads extract images automatically. Documents uploaded before enabling images need reprocessing; a fresh upload creates a separate document rather than replacing the original. The frontend displays image-processing failures and offers a reload button for expired image links. Set frontend `NEXT_PUBLIC_API_URL` if the API is not at `http://localhost:8000`.

### Retrieval API

- `POST /chat`: Existing `query` form field plus optional repeated `document_ids` fields, `scope_documents=true` (an empty document list searches nothing), and `include_images=true`. Image-related queries also request images automatically, including “page 12 ki second image dikhao”. Explicit page/image numbers constrain retrieval; image numbering means occurrence order on each page, not printed figure labels. Up to five image matches are returned with fresh URLs and source metadata.
- `GET /documents/{document_id}/images?page_number=12&image_number=2`: List extracted images, with optional location filters and `limit` (1–100).
- `GET /documents/{document_id}/images/{image_id}`: Fetch a specific image's metadata and renew its URL.
- `GET /documents/{document_id}/source`: Open the original PDF; the frontend adds `#page=N` to jump to the source page.

The chat UI sends the active conversation's uploaded document IDs for text and image retrieval. Every private API route verifies a Supabase access token and checks document ownership. Images render only from verified attachments; model-generated image Markdown and image-only tables are suppressed. Cards show a caption/page reference and open a larger viewer. Stored image references receive fresh presigned URLs when an older conversation is opened.

## Persistent history and reliable uploads

Conversations are stored in PostgreSQL by the authenticated Supabase user ID through `GET /conversations`, `PUT /conversations/{id}`, and soft-delete `DELETE /conversations/{id}`. A browser backup is scoped to that account and pending saves retry when history reconnects. Signed image URLs are never persisted with messages. Documents previously uploaded under a user's `chat_id` are restored as document conversations even when the older frontend never stored their message text; unsaved historical message text cannot be reconstructed.

Uploads accept PDFs up to 25 MB. The frontend retries temporary connection/service failures with the same `request_id`; a completed upload returns its earlier response rather than inserting another document. Parsing is serialized per API process to bound memory on small servers. Embedding requests have finite timeouts, smaller batches, and bounded retries for transient failures. Failed uploads clean up their incomplete DB record and newly allocated R2 objects. Use `python -m app.core.init_db` to apply the additive schema changes before deployment (also initialized lazily on use).

### Verification

```bash
cd backend && PYTHONPATH=.:tests .venv/bin/python -m unittest discover -s tests -v
cd ../frontend
npm run typecheck
npm test
npm run build
```

Backend tests use generated PDFs and mock the model, parser service, database and R2 calls. They cover image locations/rotation, surrounding text, repeated occurrences, scoped retrieval, signed URL generation, API responses and cleanup after failed ingestion. They require `httpx` in addition to the runtime requirements for FastAPI's test client. Live R2, model and PostgreSQL connectivity must be checked separately with the configured services.

### ✅ Prerequisites
- Python 3.10+
- Node.js + npm (or yarn/pnpm)
- PostgreSQL 15+ with `pgvector` extension
- Git

---


## Account profile and avatars

The chat sidebar includes Profile, Personalization, Settings, Help and Log out. Display name, private bio, reduced motion and compact conversation preferences are stored in the account-owned `user_profiles` table. `GET /profile` and `PUT /profile` use the same Supabase Bearer authentication as conversations; the owner is derived from the verified token.

`POST /profile/avatar` accepts JPEG, PNG or WebP up to 5 MB and 16 megapixels. Images are decoded, oriented, cropped to 512×512, stripped of metadata and encoded as WebP. The existing R2 configuration is reused; objects are private under `users/{user_id}/profile/avatars/{unique_id}.webp`. Only the object key is persisted. The frontend receives a temporary signed URL and renews it before expiry. Replacing or removing an avatar cleans up the previous object; failed database writes clean up the new upload. `DELETE /profile/avatar` removes the current photo without changing other profile details. Run `python -m app.core.init_db` for the additive table, or let it initialize on the first profile request.
