BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS news_analyses (
    id INTEGER PRIMARY KEY,
    ticker TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    inputs TEXT NOT NULL,
    payload TEXT NOT NULL,
    UNIQUE(ticker, input_hash)
);
CREATE INDEX IF NOT EXISTS news_analyses_ticker ON news_analyses(ticker, id DESC);
CREATE TABLE IF NOT EXISTS llm_attempts (
    id INTEGER PRIMARY KEY,
    ticker TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    model TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    error TEXT,
    usage TEXT
);
CREATE INDEX IF NOT EXISTS llm_attempts_started ON llm_attempts(started_at);
PRAGMA user_version=3;
COMMIT;
