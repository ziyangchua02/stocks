BEGIN;
CREATE TABLE IF NOT EXISTS indicator_snapshots (
    id INTEGER PRIMARY KEY,
    ticker TEXT NOT NULL,
    calculation_version TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS indicator_snapshots_latest ON indicator_snapshots(ticker, id DESC);
CREATE TABLE IF NOT EXISTS indicator_series (
    ticker TEXT PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES indicator_snapshots(id),
    payload TEXT NOT NULL
);
PRAGMA user_version=2;
COMMIT;
