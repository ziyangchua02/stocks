BEGIN IMMEDIATE;
-- Alerts are append-only observations. Acknowledging one records that it was
-- read; it never edits or deletes what was observed.
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY,
    ticker TEXT,
    rule TEXT NOT NULL,
    severity TEXT NOT NULL,
    created_at TEXT NOT NULL,
    dedupe_key TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT NOT NULL,
    evidence TEXT NOT NULL,
    acknowledged_at TEXT,
    UNIQUE(dedupe_key)
);
CREATE INDEX IF NOT EXISTS alerts_recent ON alerts(created_at DESC);
CREATE INDEX IF NOT EXISTS alerts_open ON alerts(acknowledged_at, id DESC);

-- One stored brief per distinct set of inputs, like news analyses.
CREATE TABLE IF NOT EXISTS daily_briefs (
    id INTEGER PRIMARY KEY,
    input_hash TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    facts TEXT NOT NULL,
    payload TEXT NOT NULL,
    UNIQUE(input_hash)
);
CREATE INDEX IF NOT EXISTS daily_briefs_recent ON daily_briefs(id DESC);
PRAGMA user_version=5;
COMMIT;
