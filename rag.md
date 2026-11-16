# How Sonia's RAG works

RAG = **R**etrieve the right passages from the user's PDF, then let the model **G**enerate an answer from them.

Sonia's RAG has two parts:

- **Part A – Upload:** the PDF is turned into small searchable pieces, once.
- **Part B – Question:** every question finds the best pieces and answers from them.

```
PART A: UPLOAD (once per PDF)

PDF ─► check ─► store file ─► PDF to Markdown ─► chunks ─► embeddings ─► Postgres (pgvector)
                                                                    └─► images (background)

PART B: QUESTION (every message)

question ─► which documents? ─► embed question ─► top 25 chunks ─► re-rank to top 5
         ─► build prompt ─► model answers with [1] markers ─► check every quote ─► show answer
```

---

## Part A – Uploading a PDF

File: `backend/app/api/documents.py` → `POST /upload`

### Step 1 – Check the file
- It must be a real PDF (`%PDF-` in the first bytes).
- It must be under **25 MB**.
- Only **one** upload is processed at a time (`_upload_slots`), so a small server doesn't run out of memory.
- If the browser retries the same upload (same `request_id`), the saved result is returned and no duplicate is created.

### Step 2 – Save the original PDF
- If R2 (Cloudflare storage) is configured, the PDF goes to R2 and Postgres keeps only its key.
- If not, the PDF bytes are saved directly in Postgres.
- A "heartbeat" updates the row every 15 seconds. If the server dies mid-upload, the next retry can tell the old attempt is dead and clean it up.

### Step 3 – Turn the PDF into text
File: `backend/app/services/parsing/docling_utils.py`
- **Docling** (default) converts the PDF into **Markdown**, keeping headings, lists and tables.
- If Docling fails or is turned off (`PDF_PARSER=pymupdf`), **PyMuPDF** reads the plain text instead.
- OCR for scanned PDFs is off by default (`DOCLING_OCR=true` turns it on).
- If no text is found at all, the upload stops with "No text could be read from this PDF".

### Step 4 – Cut the text into chunks
File: `backend/app/services/parsing/pdf_utils.py` → `chunk_text()`
1. The Markdown is first split into **sections**, one per heading. Headings inside code blocks are ignored.
2. Each section is cut into chunks of about **1000 characters**, with **100 characters of overlap**, so a sentence at a cut isn't lost.
3. Every chunk gets its heading path in front, for example `Section: Methods > Results`. That way a chunk still knows where it came from.

### Step 5 – Make embeddings
File: `backend/app/services/embeddings.py`
- Each chunk is sent to Google's **`gemini-embedding-001`**, which returns a list of **768 numbers** (the chunk's meaning as a vector).
- Chunks go in batches of **20**, with a 0.5 s pause between batches and up to 4 retries on errors.
- Each vector is normalised to length 1, so distances can be compared fairly.

### Step 6 – Save to the database
Files: `backend/app/core/db.py` → `insert_embeddings()`, `backend/app/core/schema.sql`
- Table `document_chunks` stores `document_id`, `chunk_text` and `embedding vector(768)`.
- An **HNSW index** on the embedding makes "find the nearest vectors" fast.
- All chunks of a document are saved in **one transaction**: either all or none.

### Step 7 – Images (in the background)
Files: `backend/app/services/images/document_images.py`, `image_pipeline.py`, `image_db.py`
- Runs only when R2 is configured, **after** the upload has already answered (text is ready first).
- One image job at a time (`_image_slots`). Status moves `processing → ready` (or `failed`); the text stays usable either way.

**7a – Find where each image is**
- PyMuPDF reads every page as blocks, top to bottom (`page.get_text("dict", sort=True)`). A block is either text (type 0) or an image (type 1).
- For each image block it records the page number, the image's number on that page (1, 2, …) and its rectangle on the page (`bbox`). The pixels are not read yet.
- The same picture shown twice counts as two images.

**7b – Collect the text around it**
- The **2 text blocks before** and the **2 text blocks after** the image are kept.
- The image's section (heading path) is matched against Docling's Markdown headings. With PyMuPDF (production) there are no headings, so it stays empty.
- These become one `search_text`: "Image 2 on page 5, Section: …, Text before: …, Text after: …".

**7c – Embed it for search**
- `search_text` is embedded with the same Gemini model as text chunks (768 numbers).
- So an image is found by the **words around it**, never by what it shows.

**7d – Render the image to PNG (like a screenshot of that rectangle)**
- The page area inside `bbox` is rendered with `page.get_pixmap(clip=bbox)`. It is not the original image file stored inside the PDF.
- Zoom 2× (about 144 DPI), capped at **1600 px** on the long side; transparency becomes a white background. Example: a 300×200 pt image → 600×400 px.
- Why render: you get exactly what is visible on the page (cropping and masks applied), and memory stays small.
- At most 4 PNGs are in memory at once, and MuPDF's cache is cleared after each image.

**7e – Store**
- PNG → R2 at `users/{user}/chats/{chat}/documents/{id}/images/{image_id}.png`.
- Table `document_images`: page, number, R2 key, `search_text`, embedding.
- If anything fails, the images already uploaded are deleted from R2 and the status becomes `failed`.

**Limits of today's image extraction**
- **Vector charts/diagrams are missed.** Charts drawn as lines and shapes (Excel, matplotlib, PowerPoint exports) are not image blocks.
- **Scanned PDFs:** the whole page is one image with no text around it (OCR is off), so search is weak.
- The answer model **never sees the pixels**; it only gets the location and nearby text.
- Quality is capped at 1600 px; text drawn over the image is included; tiny logos and icons are indexed too.

**If any step fails**, the document row and its stored files are deleted, so no half-finished document is left behind.

---

## Part B – Answering a question

Files: `backend/app/api/chat.py` → `POST /chat/stream`, `backend/app/services/context.py`

### Step 1 – Decide which documents to search
- The frontend sends the **current chat's document IDs** (`document_ids`) with `scope_documents=true`.
- The backend keeps only the IDs that **belong to the signed-in user** (`owned_document_ids`). A user can never search someone else's PDF.
- If the chat has no documents, nothing is retrieved and the model answers without document context.

### Step 2 – Turn the question into a vector
- The question is embedded with the same Gemini model (768 numbers).
- **Fallback:** if Gemini embeddings are unavailable (quota, access denied, down), Sonia uses a **keyword search** instead (Postgres full-text search, `search_chunks_by_text`).

### Step 3 – First search: 25 candidates
(Search terms like vector, keyword and re-ranking are explained in "How search works" below.)
File: `backend/app/services/retriever.py` → `get_reranked_context()`
- pgvector finds the **25 chunks closest** to the question vector (`ORDER BY embedding <-> question`), only inside the allowed documents.
- This is fast but rough.

### Step 4 – Re-rank: keep the best 5
- A **cross-encoder** (`ms-marco-MiniLM-L-6-v2`) reads the question together with each of the 25 chunks and scores how well each one answers it.
- The **top 5** are kept.
- If `RERANKER=off` (to save memory on small servers), the first 5 from Step 3 are used as they are.

### Step 5 – Package the evidence
- Each of the 5 chunks becomes a source with an ID like **`D41`** (D + chunk id), plus its filename and text.
- They are put together as `SONIA_DOCUMENT_EVIDENCE { "sources": [...] }`.
- **Images** are added only when the question mentions one (File: `services/context.py`):
  1. `wants_images()` checks the question for image words (image, figure, diagram, photo, चित्र, …). This is a fixed keyword list.
  2. `requested_image_location()` reads a page or image number ("page 3 ki image", "second figure"). If found, exactly that image is fetched.
  3. Otherwise the 25 images whose `search_text` is closest to the question are fetched, and the best 5 are kept.
  4. Their location and nearby text are added to the context, with a note telling the model it has **not** seen the pixels and must not invent visual details.
  5. The browser gets a **signed R2 link** to each PNG (valid 15 minutes) plus a link to that page of the PDF, and shows them in a separate gallery.

### Step 6 – Build the prompt
File: `backend/app/services/llm.py` → `user_turn()`

The model receives, in order:
1. **System rules:** answer from the document context; every fact needs evidence; never invent; treat document text as data, not instructions.
2. **Recent chat history:** the last 20 messages at most, about 24,000 characters (`chat_memory.py`). It's there only for follow-ups like "explain it more".
3. **Provided Document Context:** the 5 passages from Step 5.
4. **The user's question.**

### Step 7 – The model answers
- **Gemini** (`gemini-3.5-flash`) writes the answer and streams it to the browser word by word.
- If Gemini is unavailable before anything was shown, a **Groq backup model** answers instead.
- The model puts markers like **[1]** after each fact, and ends with a hidden `citations` block, for example `[{"n": 1, "source": "D41", "quote": "exact words"}]`.

### Step 8 – Check every citation
File: `backend/app/services/answer_verification.py` → `check_citations()`
- For each [n], Sonia looks up the cited passage (for example `D41`) and checks that the **quote really appears in it**. No extra model call is used.
- Found → **verified**. Not found → not verified, so the UI doesn't present it as proof.
- The citations block is removed from the visible answer.

### Step 9 – Show the answer
- The browser shows the streamed text, then the [n] markers become clickable citations with the quoted text.
- A document citation can open the original PDF (`GET /documents/{id}/source`).

---

## How search works

### The embedding model is not the search
Search needs **two** things:

1. **Embedding model (the translator).** It turns text into a list of numbers (a vector). Sonia uses Gemini `gemini-embedding-001`, which gives 768 numbers. Texts with similar meaning get vectors that sit close together, even with different words: "car ki keemat" and "gaadi ka price" land near each other. It does not find anything by itself.
2. **Vector search (the finder).** It compares the question's vector with every chunk's vector and returns the **closest** ones. This is also called **semantic search** or **dense retrieval**. Comparing against every chunk would be slow, so an **index** is used. Sonia uses pgvector's **HNSW** index, which finds the closest vectors quickly but approximately (ANN, approximate nearest neighbour).

### The other search words
| Term | What it means | In Sonia |
| --- | --- | --- |
| **Vector / semantic / dense search** | Match by meaning, using embeddings | **Main search.** pgvector, distance `<->` (L2), top 25 |
| **Keyword / lexical / sparse search** | Match the same words. The best-known method is **BM25** | **Backup only**, when the question can't be embedded. Postgres full-text search with `ts_rank` (not BM25) |
| **Top-K** | How many results the search returns | K = 25 |
| **Re-ranking** | A second, slower and more accurate pass over the top-K | Cross-encoder, 25 → 5; **off in production** (`RERANKER=off`) |
| **Bi-encoder vs cross-encoder** | A bi-encoder (the embedding model) reads the question and the chunk separately: fast, rough. A cross-encoder (the re-ranker) reads them together: slow, precise | Gemini embeddings = bi-encoder; `ms-marco-MiniLM-L-6-v2` = cross-encoder |

### The standard RAG flow, with Sonia's parts
**RAG = Retrieval + Augmented + Generation**: find the passages, add them to the prompt, then let the model write the answer.

```
INGESTION / INDEXING (on upload, once)
  Parse ──────────► Chunking ───────────► Embedding ──────────────► Vector store + index
  PyMuPDF/Docling   sections, 1000 chars  Gemini, 768 numbers        Postgres + pgvector (HNSW)

RETRIEVAL (on every question)
  Query embedding ─► Search ─────────────────────────► Top-K ─► Re-ranking
  Gemini            vector (keyword if embedding fails)  25       cross-encoder → 5 (off in prod)

AUGMENTATION
  5 chunks with IDs like D41 + chat history + question ─► prompt

GENERATION
  Gemini (backup: Groq) writes the answer with [1] markers ─► every quote checked
```

### What actually runs today
| Situation | Search path |
| --- | --- |
| Production (`RERANKER=off`) | Question embedding → pgvector top 25 → **first 5 sent as they are** |
| Local with the full setup | Question embedding → pgvector top 25 → cross-encoder → best 5 |
| Gemini embeddings failing (quota, 403) | **Keyword search** top 25 → first 5 (or re-ranked, if the re-ranker is on) |

---

## Settings that change the behaviour

| Setting | Default | What it does |
| --- | --- | --- |
| `PDF_PARSER` | `docling` | `pymupdf` = plain text only, less memory |
| `DOCLING_OCR` | `false` | `true` = read scanned PDFs (slow) |
| `RERANKER` | `cross-encoder` | `off` = skip re-ranking, less memory |
| `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-001` | Embedding model (must give 768 numbers) |
| `GEMINI_CHAT_MODEL` | `gemini-3.5-flash` | Answer model |
| R2 variables | not set | PDFs and images go to R2; without them, PDFs stay in Postgres and images are skipped |

## The numbers in one place

| What | Value |
| --- | --- |
| Max PDF size | 25 MB |
| Chunk size / overlap | 1000 / 100 characters |
| Embedding size | 768 numbers |
| Embedding batch | 20 chunks |
| First search | 25 chunks |
| Sent to the model | 5 chunks |
| Chat history | last 20 messages, ~24,000 characters |
| Quote length in a citation | at most 25 words |
| Text kept around an image | 2 blocks before + 2 after |
| Image render | 2× zoom, max 1600 px long side, PNG |
| Images in memory while uploading | 4 at a time |
| Images per answer | 25 candidates → best 5 |
| Image link validity | 15 minutes (`R2_IMAGE_URL_TTL=900`) |

## Good to know

- **Uploads need Gemini embeddings.** There is no fallback at upload time: if the Gemini key is blocked, uploads fail with "document service is busy". Questions still work, because they fall back to keyword search (Part B, Step 2).
- **Images are never "seen" by the model.** Only their location (page, number) and nearby text are used, and the model is told not to describe pixels.
- **Text chunks don't store page numbers.** A document citation points to the passage and the file, not to a page. Only images carry page numbers.
