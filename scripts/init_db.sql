CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY, filename TEXT NOT NULL, source_type TEXT DEFAULT 'patent',
    total_pages INT, total_chunks INT, ocr_applied BOOLEAN DEFAULT FALSE,
    ocr_engine TEXT, file_size_kb REAL, tags TEXT DEFAULT '',
    ingested_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS query_logs (
    qid SERIAL PRIMARY KEY, query TEXT NOT NULL, answer TEXT, top_k INT DEFAULT 5,
    sources JSONB, model TEXT, total_tokens INT DEFAULT 0, latency_ms REAL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS feedback (
    id SERIAL PRIMARY KEY, query_log_id INT REFERENCES query_logs(qid),
    rating INT CHECK (rating IN (-1, 1)), comment TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS eval_results (
    eval_id SERIAL PRIMARY KEY, eval_set TEXT, question TEXT, expected TEXT,
    actual TEXT, recall_at_5 REAL, faithfulness REAL, latency_ms REAL,
    passed BOOLEAN, created_at TIMESTAMPTZ DEFAULT NOW()
);
