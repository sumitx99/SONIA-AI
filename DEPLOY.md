# Deploying Sonia (free plans)

- **API** → Render free web service (512 MB), from `render.yaml`
- **Frontend** → Vercel Hobby (free), from `sonia-ai-chat-interface-main/`
- **Database / auth** → Supabase (already set up) · **Files** → Cloudflare R2 (already set up)

On the free plan the API parses PDFs with PyMuPDF and skips the re-ranker
(`PDF_PARSER=pymupdf`, `RERANKER=off`), which keeps it around 200–250 MB.
Docling and the cross-encoder need ~2 GB: use `requirements-full.txt` and unset those two
variables on a larger instance (e.g. Render Standard).

## 1. Push the code to GitHub

`.env` and `.env.local` are git-ignored; never commit them.

## 2. API on Render

1. Render → **New → Blueprint** → pick this repository. It reads `render.yaml`.
2. Fill the secret values it asks for (same as your local `.env`):
   `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `GOOGLE_API_KEY`, `SUPABASE_URL`,
   `R2_ENDPOINT_URL`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`.
   Leave `FRONTEND_ORIGINS` for step 4.
3. Deploy, then open `https://<your-api>.onrender.com/` — it should say the API is running.

The free service sleeps after 15 minutes idle; the first request after that takes ~1 minute.

## 3. Frontend on Vercel

1. Vercel → **Add New → Project** → this repository.
2. **Root Directory:** `sonia-ai-chat-interface-main` (framework: Next.js).
3. Environment variables:
   - `NEXT_PUBLIC_API_URL` = `https://<your-api>.onrender.com`
   - `NEXT_PUBLIC_SUPABASE_URL` = your Supabase project URL
   - `NEXT_PUBLIC_SUPABASE_ANON_KEY` = the publishable key
4. Deploy and note the URL, e.g. `https://sonia.vercel.app`.

## 4. Connect them

- Render → API service → Environment: `FRONTEND_ORIGINS` = your Vercel URL
  (comma-separate several, e.g. `https://sonia.vercel.app,http://localhost:3000`). Save → redeploys.
- Supabase → Authentication → URL Configuration: **Site URL** = your Vercel URL, and add
  `https://<your-site>/auth` to **Redirect URLs** (sign-up confirmation and password reset).

## Before real users

- Rotate any key that has been shared outside your machine (R2 token, DB password, Gemini key).
- Turn **Confirm email** back on (Supabase → Authentication → Sign In / Providers) and set up
  custom SMTP — the built-in mailer sends only a few emails per hour.
