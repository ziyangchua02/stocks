BEGIN IMMEDIATE;
-- Signals are append-only research records. Rows are never updated once written,
-- so a later weight change cannot rewrite what the system said at the time.
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY,
    ticker TEXT NOT NULL,
    scoring_version TEXT NOT NULL,
    config_version TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    score REAL,
    label TEXT,
    status TEXT NOT NULL,
    reference_session TEXT,
    reference_close REAL,
    payload TEXT NOT NULL,
    UNIQUE(ticker, input_hash)
);
CREATE INDEX IF NOT EXISTS signals_ticker ON signals(ticker, id DESC);
CREATE INDEX IF NOT EXISTS signals_created ON signals(created_at DESC);
PRAGMA user_version=4;
COMMIT;
