CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS watchlist (
    ticker TEXT PRIMARY KEY, company_name TEXT NOT NULL DEFAULT '', added_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS provider_cache (
    cache_key TEXT PRIMARY KEY, payload TEXT, fetched_at TEXT, expires_at TEXT,
    attempted_at TEXT NOT NULL, error TEXT, retry_at TEXT
);
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY, ticker TEXT NOT NULL, kind TEXT NOT NULL,
    source TEXT NOT NULL, source_as_of TEXT, fetched_at TEXT NOT NULL, payload TEXT NOT NULL,
    UNIQUE(ticker, kind, source, fetched_at)
);
CREATE INDEX IF NOT EXISTS snapshots_latest ON snapshots(ticker, kind, fetched_at DESC);
CREATE TABLE IF NOT EXISTS bars (
    ticker TEXT NOT NULL, session_date TEXT NOT NULL, source TEXT NOT NULL,
    fetched_at TEXT NOT NULL, payload TEXT NOT NULL,
    PRIMARY KEY(ticker, session_date, source)
);
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY, canonical_url TEXT NOT NULL UNIQUE, fingerprint TEXT NOT NULL,
    title TEXT NOT NULL, url TEXT NOT NULL, publisher TEXT NOT NULL, summary TEXT NOT NULL,
    published_at TEXT NOT NULL, fetched_at TEXT NOT NULL, content_scope TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS articles_fingerprint ON articles(fingerprint);
CREATE INDEX IF NOT EXISTS articles_recent ON articles(published_at DESC);
CREATE TABLE IF NOT EXISTS article_tickers (
    article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    ticker TEXT NOT NULL, PRIMARY KEY(article_id, ticker)
);
CREATE TABLE IF NOT EXISTS article_sources (
    article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    provider TEXT NOT NULL, url TEXT NOT NULL, fetched_at TEXT NOT NULL,
    PRIMARY KEY(article_id, provider, url)
);
CREATE TABLE IF NOT EXISTS refresh_runs (
    id TEXT PRIMARY KEY, status TEXT NOT NULL, trigger TEXT NOT NULL,
    started_at TEXT NOT NULL, completed_at TEXT, tickers TEXT NOT NULL, results TEXT NOT NULL
);
