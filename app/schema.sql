-- Base schema for Sonia. Safe to re-run: every statement is idempotent.
-- Apply with: python -m app.init_db
CREATE EXTENSION IF NOT EXISTS vector;

-- With R2 configured, `file` is NULL and the PDF lives at `source_key` in the bucket.
CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    filename TEXT NOT NULL,
    file BYTEA,
    chat_id TEXT,
    source_key TEXT,
    user_id TEXT,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS documents_chat_idx ON documents(chat_id);
CREATE INDEX IF NOT EXISTS documents_user_idx ON documents(user_id);

-- text-embedding-004 returns 768-dimensional vectors.
CREATE TABLE IF NOT EXISTS document_chunks (
    id SERIAL PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_text TEXT NOT NULL,
    embedding vector(768) NOT NULL
);
CREATE INDEX IF NOT EXISTS document_chunks_document_idx ON document_chunks(document_id);
-- Retrieval orders by `<->` (L2 distance).
CREATE INDEX IF NOT EXISTS document_chunks_embedding_idx
    ON document_chunks USING hnsw (embedding vector_l2_ops);

-- Supabase exposes `public` tables through its Data API. With RLS on and no policies,
-- anon/authenticated API keys see nothing; the backend's postgres role bypasses RLS.
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY;

-- API access is always scoped to the verified Supabase subject, never the email string.
CREATE TABLE IF NOT EXISTS conversations (
    user_id TEXT NOT NULL,
    id TEXT NOT NULL,
    title TEXT NOT NULL,
    messages JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,
    PRIMARY KEY (user_id, id)
);
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
