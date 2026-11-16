# Future requirements (R&D)

Status: **research notes, nothing here is built yet.** Each item says what the code does today
(with the file), what has to change, and what is still an open question.

Goals:
1. **More document types:** Word, PowerPoint, CSV, Excel, and more, not just PDF.
2. **Scale to 1 lakh (100,000) users.**
3. **Stronger agents:** tools, long tasks, and calculations.
4. **Visual understanding:** the model actually sees charts, diagrams and scanned pages.

Related: [rag.md](rag.md) explains today's RAG step by step. Update both files when this work lands.

---

## Where we are today (production)

From `render.yaml` and `DEPLOY.md`:

| Part | Today |
| --- | --- |
| API | One Render **free** instance, 512 MB RAM, sleeps after 15 min idle |
| PDF parsing | `PDF_PARSER=pymupdf`: plain text, **no Markdown headings**, so the heading-based section split in `chunk_text()` does not happen in production |
| Docling | **Not installed** in production (`requirements.txt`); needs about 2 GB RAM (`requirements-full.txt`) |
| Re-ranker | `RERANKER=off`: the top 5 come straight from vector order |
| Database | Supabase Postgres + pgvector, pool of 4 connections per instance (`DB_POOL_SIZE`) |
| Files | Cloudflare R2 |
| Frontend | Vercel Hobby |
| Models | Gemini (answers and embeddings) with a Groq free-tier backup |

---

## 1. More document types

### Today
Only PDF, blocked in three places:
- `frontend/app/chat/page.tsx`: file picker `accept=".pdf"` and a `.pdf` name check.
- `backend/app/api/documents.py`: the file must start with `%PDF-`.
- `backend/app/services/parsing/docling_utils.py`: Docling is given only `InputFormat.PDF`; the PyMuPDF fallback reads only PDF.

### Plan
Convert every format to **Markdown** first. After that, chunking, embeddings, search and
citations stay exactly as they are.

| Format | Converter (no torch, fits a small server) | Section split | Notes |
| --- | --- | --- | --- |
| PDF | PyMuPDF (today) or Docling on a bigger worker | Only with Docling | Keep as is |
| Word `.docx` | `python-docx` / `mammoth` | Yes, real headings | Best quick win |
| PowerPoint `.pptx` | `python-pptx` | One section per slide | Include speaker notes |
| CSV | built-in `csv` | One section per file | See "Spreadsheets" |
| Excel `.xlsx` | `openpyxl` | One section per sheet | See "Spreadsheets" |
| Text / Markdown | read directly | Markdown headings | Easy |
| Old `.doc` `.ppt` `.xls` | LibreOffice | – | Too heavy for a small server; ask users to re-save, or run in a separate worker |

`markitdown` (Microsoft) covers most of these in one package. **R&D:** measure its memory and
speed against the separate libraries before choosing.

### Changes needed
1. Detect the type from the **file content** (magic bytes / zip contents), not from the file name.
2. One `to_markdown(file) → text` step with a converter per type; keep size limits per type.
3. Images: the image pipeline only reads PDF pages. Skip images for other formats in version 1.
4. "Open original": PDFs open in the browser; other formats download.
5. UI text: "Add a PDF" → "Add a file", plus the error messages.
6. Update `rag.md`.

### Spreadsheets: the real limitation
RAG sends only **5 chunks** to the model. That works for "what is the value in row X", but
**totals, averages, max/min or filters will be wrong or incomplete**, because the model never
sees the whole sheet.
- Version 1: index rows for lookup questions only, and say so in the answer.
- Proper fix: a calculation tool (see "Agents", item 4) that runs real queries on the sheet.
- Large sheets create many chunks, and every chunk costs an embedding call, so cap the number of rows/cells.

---

## 2. Scaling to 1 lakh users

### Assumption (to confirm)
1 lakh **registered** users is not 1 lakh at the same time. A working assumption is about
10% active per day and 1–2% at peak, i.e. **1,000–2,000 people chatting at the same moment**.
Replace this with real numbers from analytics before buying capacity.

### Bottlenecks in today's code

| # | Problem | Where | Why it breaks at scale |
| --- | --- | --- | --- |
| 1 | One free 512 MB instance that sleeps | `render.yaml` | A cold start of about 1 minute; memory runs out quickly |
| 2 | Uploads run **inside the request** (parse + embed) | `documents.py` `_process_upload` | Long requests hold memory and time out under load |
| 3 | **One upload at a time** per instance | `_upload_slots = Semaphore(1)` | Uploads queue behind each other |
| 4 | Image jobs are in-process `asyncio` tasks | `_start_image_job` | Lost if the instance restarts; can't spread across machines |
| 5 | Tool approvals kept **in memory** | `mcp_client/agent.py` `_approvals` | With 2+ instances, the approval click can reach the wrong instance |
| 6 | DB pool of 4 per instance | `core/db.py` `DB_POOL_SIZE` | Many instances × pools exceed Supabase's connection limit |
| 7 | **No per-user rate limit** | `app/main.py` | One user (or a bot) can use up the shared model quota |
| 8 | Model quota and keys | `services/llm.py`, `embeddings.py` | Gemini currently returns 403; Groq free tier returns 429 under light load |
| 9 | Vector search with a document filter | `db.py` `search_embeddings` | HNSW with a `WHERE document_id = ANY(...)` filter can return fewer than 25 results when a user's chunks are a small share of the table |
| 10 | No metrics or tracing | – | Slow or failing parts can't be found |

### What to build

**A. Split the backend into two services**
- **API service:** login, chat streaming, status. Several small instances behind a load balancer, never sleeping.
- **Worker service:** document parsing, embeddings, images. It takes jobs from a **queue** (Redis-based, or Postgres `SKIP LOCKED`). It can have more RAM, so Docling and the re-ranker can come back.
- Upload returns at once with `processing`. The frontend already polls `GET /documents/{id}/status`.

**B. Move in-memory state to shared storage**
- Approvals, upload locks, image job state and the web-search pause flag → Redis or Postgres.
- Redis is already optional for the conversation cache (`REDIS_URL`); make it required.

**C. Database**
- Use Supabase's connection pooler (transaction mode) and size pools per instance.
- Vector search R&D: pgvector iterative index scans / `hnsw.ef_search`, or filter first and then rank inside a user's documents. Test with about 100 million chunks.
- Index the tables used by every request (`documents.user_id` is already indexed; check conversation queries).

**D. Models and cost**
- Paid Gemini tier with enough quota; keep one paid backup provider (not a free tier).
- Per-user limits: messages per minute, uploads per day, pages per upload.
- Track tokens and cost per user and per feature.
- Retries with backoff already exist for embeddings; add a shared limiter so workers don't overrun the quota together.

**E. Re-ranking and parsing quality**
- Bring back the cross-encoder in the worker, or use a hosted re-rank API.
- Run Docling in the worker so production gets headings and the section split.

**F. Observability and safety**
- Metrics: request latency, time to first token, upload time, queue length, model errors and quota.
- Error tracking and structured logs with a request id.
- Before launch (from `DEPLOY.md`): rotate shared keys, turn email confirmation back on, set up custom SMTP.

**G. Load testing**
- Script a realistic mix (chat, upload, history), run it at 2× the expected peak, and fix the first thing that breaks.

---

## 3. Agents

### Today
- **Agent loop:** `backend/app/mcp_client/agent.py`. Gemini function calling, up to **5 tool rounds** (`MAX_ROUNDS`), up to **64 tools** offered (`MAX_TOOLS`), and one continuation if the answer is cut off.
- **Built-in tools:** web search, reading a linked page (with a screenshot when needed), web image search.
- **User-connected tools:** MCP servers the user adds (`connections.py`, `oauth.py`). Secrets are encrypted with `MCP_SECRET_KEY` (`store.py`). URL safety checks are in `safety.py`.
- **Approvals:** tools that need consent pause until the user clicks Approve (`POST /chat/approvals/{id}`). The pending approval lives **in memory**.
- **Backup:** if Gemini fails, a Groq model continues with the same tools.
- **Sonia as a tool for other apps:** `backend/app/mcp_server/` exposes `list_documents`, `search_documents`, `ask_sonia` and `get_image` over MCP.

### Limits today
- Document retrieval happens **once, before** the model starts. The model can't search the documents again with a better query.
- No long-running tasks: everything must finish inside one chat request.
- No way to run calculations (for example on a spreadsheet).
- Approvals break with more than one instance (see "Scaling", #5).
- No audit history of which tool ran, with what input, for whom.

### Future requirements

1. **Document search as a tool (agentic RAG).** Give the model a `search_documents` tool (the logic already exists in `mcp_server/tools.py` and `retriever.py`) so it can search again, compare documents or follow up. Keep today's first retrieval as the starting context. Citations must still pass `check_citations()`.
2. **Persisted approvals.** Store pending approvals in Redis/Postgres with an expiry, so any instance can resume them.
3. **Tool audit log.** Record user, tool, arguments (with secrets removed), result size, status and time. Show it in the user's settings.
4. **Calculation tool.** A sandboxed run of queries or code over uploaded CSV/Excel. This is what fixes the spreadsheet limitation. **R&D:** sandbox choice, time and memory limits, no network access.
5. **Background agent tasks.** Long jobs ("summarise all 20 documents", "compare these reports") run in the worker queue, show progress, and post the result to the chat when done.
6. **Limits per agent run.** Maximum tool calls, tokens, time and cost per run and per user per day.
7. **Tool quality.** When many tools are connected, keep shortlisting them (the backup path already shortlists), and log which tools are actually useful.

### Open questions for agents
- Which external tools matter most to users (Drive, Gmail, Notion, Slack, …)?
- May an agent take actions (send, edit), or only read? Actions need approvals and an audit log first.
- Should background tasks notify by email, or only inside the app?

---

## 4. Visual understanding (images, charts, scanned pages)

### Today
Files: `backend/app/services/images/document_images.py`, `image_pipeline.py`, `services/context.py`
- Upload finds **image blocks** on each page (PyMuPDF `get_text("dict")`, block type 1) and
  renders **only that rectangle** of the page to PNG (`get_pixmap(clip=bbox)`, 2× zoom, at most
  1600 px on the long side). The PNG goes to R2.
- Each image is indexed by its **surrounding text** (2 text blocks before, 2 after), never by
  what it shows. **The model never sees the pixels.**
- Image search only runs when the question contains an image word or a page/image number, from
  **hardcoded keyword and regex lists** (`wants_images()`, `requested_image_location()`).

### Gaps
1. **Vector charts and diagrams are missed.** Charts exported from Excel, matplotlib,
   PowerPoint or draw.io are lines and shapes, not image blocks, so they are never extracted.
2. **Scanned PDFs:** the whole page is one image with no text around it (OCR is off), so search is weak.
3. The model can't answer "what does this chart show" unless the nearby text says it.
4. Original resolution is lost (capped at 1600 px), and text drawn over an image is included.
5. Tiny images (logos, icons) are indexed too; there is no size filter.
6. **Text chunks have no page numbers**, so Sonia can't say which page a passage came from or
   send "the page next to this passage".
7. The keyword-based image detection misses wording like "graph dikhao" or "visual", and goes
   against the no-hardcoding rule.

### How Claude and GPT do it (public API docs)
- **Claude:** every PDF page is sent twice: its extracted text, and the **whole page rendered as
  an image**. About 1,500–3,000 tokens per page; up to 32 MB / 600 pages per request.
  Scanned pages can be read but not cited.
  ([PDF support](https://platform.claude.com/docs/en/build-with-claude/pdf-support))
- **GPT (OpenAI API):** PDFs send extracted text plus an image of each page to vision-capable
  models (gpt-4o and later). `detail` sets the page-image quality. Other formats (DOCX, TXT)
  send text only. ([File inputs](https://developers.openai.com/api/docs/guides/file-inputs.md))
- There is **no separate vision model**: the same multimodal model reads text and image tokens
  together. Gemini (Sonia's answer model) is multimodal too.
- Their cost: whole pages go to the model on **every** question. That is too expensive to copy
  as-is at 1 lakh users.

### Target design: RAG for finding, vision for reading

**Step 0 – Prerequisite: page numbers on text chunks**
- Store the page range with every chunk (Docling gives page provenance; with PyMuPDF, extract
  text page by page).
- Also unlocks page numbers in citations.

**At upload (cost paid once per document)**
1. Render **every page** to an image and keep it in R2. The rendering code already exists;
   use the whole page instead of a clip.
2. A cheap multimodal model (for example Gemini Flash) writes a short **visual description** of
   each page that has visual content: what each chart, diagram, table or photo shows, its
   axes, labels and key values, and its label ("Figure 2", "Table 3") if any.
3. Embed those descriptions like text chunks, with the page number. Vector charts and scanned
   pages become searchable.
4. **Figure ↔ text links:** the same model lists, for each text chunk, which figures or tables
   it discusses ("as shown in Figure 2", "the chart above"). Save the links in a table
   `figure_links(figure, chunk)`. No regex: the model reads the wording.
5. Skip decorative images (logos, icons, repeated headers) using the description step.

**At question time**
1. Retrieve as today: text chunks **and** visual descriptions compete in the same search
   (top 25, re-rank to top 5).
2. **Pull partners through the links.** If a passage on page 7 discusses Figure 2 (page 3), add
   page 3's image. If Figure 2 is hit, add the passages that discuss it.
3. Send the answer model the text chunks (cheap) plus **only the 1–3 page images** that were
   hit or linked, never the whole document.
4. The model decides from the question whether to look at the images. There is no keyword
   gate, so `wants_images()` / `requested_image_location()` can go.
5. **Fallback tool:** give the model `get_page(document, page)` / `get_figure(label)` so it can
   fetch an image the links missed (ties to "Agents", item 1).

**Citations**
- Text citations stay exact-quote checked (`check_citations()`).
- For a claim read from an image, cite the **page and figure**, and say it was read from the
  image: there is no text quote to verify. Decide how the UI shows this difference.

**When the backup model answers**
- The Groq backup (`gpt-oss-120b` / `gpt-oss-20b`) is text-only. It must use the visual
  descriptions instead of images, or the backup must be a multimodal model.

### Cost and scale (R&D)
- Upload: one description call per visual page; batch it in the worker queue ("Scaling", A).
- Question: 1–3 page images ≈ a few thousand extra tokens, only when pages are hit.
- Storage: page images in R2. Pick a resolution and format (WebP/JPEG) that keeps text legible.
- Measure: answer accuracy on charts and scanned pages, cost per question, and upload time on
  100-page PDFs.

### Open questions for visual understanding
- Describe every page, or only pages with images or drawings (cheaper)?
- Turn on OCR for scanned PDFs, or rely on the vision model's description?
- Page image resolution: balance legibility of small chart text against storage and tokens.

---

## Suggested order

| Phase | Work | Why first |
| --- | --- | --- |
| 1 | Fix model access (Gemini 403, paid quota) and add per-user rate limits | Nothing else works without it |
| 2 | Worker service + job queue; move uploads and images there; shared state in Redis | Unblocks scale and heavy parsing |
| 3 | Word and PowerPoint support (plus text/Markdown) | Clear user value, low risk |
| 4 | Docling and the re-ranker in the worker; **page numbers on every chunk** | Better answers in production; needed by visual understanding and page citations |
| 5 | Persisted approvals, tool audit log, document search as a tool | Safe agents on several instances |
| 6 | Visual understanding: page images, visual descriptions, figure ↔ text links | Charts and scanned pages answered correctly |
| 7 | CSV/Excel with the calculation tool | Needs the sandbox to be correct |
| 8 | Observability, load test at 2× peak, then scale out | Prove it before launch |

## Open questions for you

1. Real numbers: expected daily active users and peak concurrent users?
2. Budget per month for hosting and models? It decides providers and instance sizes.
3. Largest file and page count we must support?
4. Are old `.doc` / `.ppt` / `.xls` files needed, or is "please re-save" acceptable?
5. Which agent tools and which actions (read-only or write) come first?
6. How important are charts and scanned PDFs for your users? It decides how early phase 6 comes.
