import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.models import Article, iso, utcnow


def encode(value) -> str:
    return json.dumps(value, allow_nan=False, separators=(",", ":"))


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_")
        and k.lower()
        not in {
            "guccounter",
            "guce_referrer",
            "guce_referrer_sig",
            "fbclid",
            "gclid",
            "mod",
            "cmpid",
            "__source",
            "ncid",
        }
    ]
    return urlunsplit(
        ("https", parts.netloc.lower(), parts.path.rstrip("/"), urlencode(sorted(query)), "")
    )


class Store:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self, seeds):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 5:
                raise RuntimeError("Database schema is newer than this application supports.")
            if version < 1:
                migration = Path(__file__).parent / "migrations/001_initial.sql"
                db.executescript(migration.read_text())
                db.execute("PRAGMA user_version=1")
            if version < 2:
                migration = Path(__file__).parent / "migrations/002_indicators.sql"
                db.executescript(migration.read_text())
            if version < 3:
                migration = Path(__file__).parent / "migrations/003_news_analysis.sql"
                db.executescript(migration.read_text())
            if version < 4:
                migration = Path(__file__).parent / "migrations/004_signals.sql"
                db.executescript(migration.read_text())
            if version < 5:
                migration = Path(__file__).parent / "migrations/005_alerts_briefs.sql"
                db.executescript(migration.read_text())
            if not db.execute("SELECT 1 FROM metadata WHERE key='seeded'").fetchone():
                db.executemany(
                    "INSERT OR IGNORE INTO watchlist VALUES(?,?,?)",
                    [(x.ticker, x.company_name, iso()) for x in seeds],
                )
                db.execute("INSERT INTO metadata VALUES('seeded','true')")
            db.execute(
                "UPDATE refresh_runs SET status='interrupted', completed_at=? "
                "WHERE status='running'",
                (iso(),),
            )
            db.execute(
                "UPDATE llm_attempts SET status='interrupted',completed_at=? "
                "WHERE status='running'",
                (iso(),),
            )

    def watchlist(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM watchlist ORDER BY ticker")]

    def add_ticker(self, ticker, company_name, maximum):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM watchlist WHERE ticker=?", (ticker,)).fetchone():
                return False
            if db.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0] >= maximum:
                raise ValueError("Watchlist capacity reached")
            db.execute("INSERT INTO watchlist VALUES(?,?,?)", (ticker, company_name, iso()))
            return True

    def remove_ticker(self, ticker):
        with self.connect() as db:
            return bool(db.execute("DELETE FROM watchlist WHERE ticker=?", (ticker,)).rowcount)

    def cache(self, key):
        with self.connect() as db:
            row = db.execute("SELECT * FROM provider_cache WHERE cache_key=?", (key,)).fetchone()
            if not row:
                return None
            result = dict(row)
            result["payload"] = json.loads(result["payload"]) if result["payload"] else None
            return result

    def cache_success(self, key, payload, ttl):
        now = utcnow()
        with self.connect() as db:
            db.execute(
                "INSERT INTO provider_cache VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(cache_key) DO UPDATE SET payload=excluded.payload, "
                "fetched_at=excluded.fetched_at, expires_at=excluded.expires_at, "
                "attempted_at=excluded.attempted_at, error=NULL, retry_at=NULL",
                (
                    key,
                    encode(payload),
                    iso(now),
                    iso(now + timedelta(seconds=ttl)),
                    iso(now),
                    None,
                    None,
                ),
            )

    def cache_failure(self, key, error, retry_seconds):
        now = utcnow()
        with self.connect() as db:
            db.execute(
                "INSERT INTO provider_cache VALUES(?,NULL,NULL,NULL,?,?,?) "
                "ON CONFLICT(cache_key) DO UPDATE SET attempted_at=excluded.attempted_at, "
                "error=excluded.error, retry_at=excluded.retry_at",
                (key, iso(now), error, iso(now + timedelta(seconds=retry_seconds))),
            )

    def cache_status(self, ticker=None):
        with self.connect() as db:
            rows = db.execute(
                "SELECT cache_key,fetched_at,expires_at,attempted_at,error,retry_at "
                "FROM provider_cache ORDER BY cache_key"
            ).fetchall()
        return [
            dict(row)
            for row in rows
            if ticker is None
            or row["cache_key"].endswith(":" + ticker)
            or row["cache_key"].startswith("rss:")
        ]

    def save_snapshot(self, kind, payload):
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO snapshots "
                "(ticker,kind,source,source_as_of,fetched_at,payload) VALUES(?,?,?,?,?,?)",
                (
                    payload["ticker"],
                    kind,
                    payload["source"],
                    payload.get("source_as_of"),
                    payload["fetched_at"],
                    encode(payload),
                ),
            )

    def snapshot(self, ticker, kind):
        with self.connect() as db:
            # Event time wins so fetching an older quote cannot regress the latest observation.
            order = "source_as_of DESC, fetched_at DESC" if kind == "quote" else "fetched_at DESC"
            row = db.execute(
                f"SELECT payload FROM snapshots WHERE ticker=? AND kind=? ORDER BY {order} LIMIT 1",
                (ticker, kind),
            ).fetchone()
            return json.loads(row[0]) if row else None

    def save_bars(self, bars):
        with self.connect() as db:
            db.executemany(
                "INSERT INTO bars VALUES(?,?,?,?,?) ON CONFLICT "
                "(ticker,session_date,source) DO UPDATE SET "
                "fetched_at=excluded.fetched_at,payload=excluded.payload",
                [
                    (x["ticker"], x["session_date"], x["source"], x["fetched_at"], encode(x))
                    for x in bars
                ],
            )

    def bars(self, ticker, limit=600):
        # Never splice histories with different adjustment conventions.
        with self.connect() as db:
            source = db.execute(
                "SELECT source FROM bars WHERE ticker=? GROUP BY source "
                "ORDER BY MAX(session_date) DESC, (source='yfinance') DESC LIMIT 1",
                (ticker,),
            ).fetchone()
            if not source:
                return []
            rows = db.execute(
                "SELECT payload FROM bars WHERE ticker=? AND source=? "
                "ORDER BY session_date DESC LIMIT ?",
                (ticker, source[0], limit),
            )
            return list(reversed([json.loads(row[0]) for row in rows]))

    def save_articles(self, ticker, articles):
        with self.connect() as db:
            for raw in articles:
                article = Article.model_validate(raw)
                data = article.model_dump(mode="json")
                url = canonical_url(article.url)
                normalized = re.sub(r"\W+", " ", article.title.casefold()).strip()
                fingerprint = hashlib.sha256(
                    f"{article.published_at.date()}:{normalized}".encode()
                ).hexdigest()
                existing = db.execute(
                    "SELECT id FROM articles WHERE canonical_url=? OR fingerprint=? LIMIT 1",
                    (url, fingerprint),
                ).fetchone()
                if existing:
                    article_id = existing[0]
                else:
                    cursor = db.execute(
                        "INSERT INTO articles (canonical_url,fingerprint,title,"
                        "url,publisher,summary,published_at,fetched_at,content_scope) "
                        "VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            url,
                            fingerprint,
                            article.title,
                            article.url,
                            article.publisher,
                            article.summary,
                            data["published_at"],
                            data["fetched_at"],
                            article.content_scope,
                        ),
                    )
                    article_id = cursor.lastrowid
                db.execute(
                    "INSERT OR IGNORE INTO article_tickers VALUES(?,?)", (article_id, ticker)
                )
                db.execute(
                    "INSERT INTO article_sources VALUES(?,?,?,?) ON CONFLICT "
                    "(article_id,provider,url) DO UPDATE SET fetched_at=excluded.fetched_at",
                    (article_id, article.provider, article.url, data["fetched_at"]),
                )

    def save_indicators(self, ticker, input_hash, payload, series):
        with self.connect() as db:
            cursor = db.execute(
                "INSERT INTO indicator_snapshots "
                "(ticker,calculation_version,input_hash,computed_at,payload) VALUES(?,?,?,?,?)",
                (
                    ticker,
                    payload["calculation_version"],
                    input_hash,
                    payload["computed_at"],
                    encode(payload),
                ),
            )
            snapshot_id = cursor.lastrowid
            db.execute(
                "INSERT INTO indicator_series VALUES(?,?,?) ON CONFLICT(ticker) "
                "DO UPDATE SET snapshot_id=excluded.snapshot_id,payload=excluded.payload",
                (ticker, snapshot_id, encode(series)),
            )
            return snapshot_id

    def indicators(self, ticker, include_series=False, limit=600):
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM indicator_snapshots WHERE ticker=? ORDER BY id DESC LIMIT 1",
                (ticker,),
            ).fetchone()
            if row is None:
                return None
            data = json.loads(row["payload"])
            data["snapshot_id"] = row["id"]
            data["input_hash"] = row["input_hash"]
            if include_series:
                series = db.execute(
                    "SELECT payload FROM indicator_series WHERE ticker=? AND snapshot_id=?",
                    (ticker, row["id"]),
                ).fetchone()
                data["technicals"]["series"] = json.loads(series[0])[-limit:] if series else []
            return data

    def news(self, since, ticker=None, limit=100, offset=0):
        with self.connect() as db:
            where = "a.published_at>=? AND a.published_at<=?"
            params = [since, iso()]
            if ticker:
                where += " AND EXISTS(SELECT 1 FROM article_tickers t "
                where += "WHERE t.article_id=a.id AND t.ticker=?)"
                params.append(ticker)
            total = db.execute(f"SELECT COUNT(*) FROM articles a WHERE {where}", params).fetchone()[
                0
            ]
            rows = db.execute(
                f"SELECT a.* FROM articles a WHERE {where} "
                "ORDER BY published_at DESC,id DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item.pop("fingerprint")
                item["tickers"] = [
                    r[0]
                    for r in db.execute(
                        "SELECT ticker FROM article_tickers WHERE article_id=? ORDER BY ticker",
                        (item["id"],),
                    )
                ]
                item["sources"] = [
                    dict(r)
                    for r in db.execute(
                        "SELECT provider,url,fetched_at FROM article_sources WHERE article_id=?",
                        (item["id"],),
                    )
                ]
                result.append(item)
            return {"items": result, "total": total, "limit": limit, "offset": offset}

    def news_candidates(self, since, ticker):
        """Article text for analysis selection, without per-article source join queries."""
        with self.connect() as db:
            rows = db.execute(
                "SELECT a.* FROM articles a JOIN article_tickers t ON t.article_id=a.id "
                "WHERE t.ticker=? AND a.published_at>=? AND a.published_at<=? "
                "ORDER BY a.published_at DESC,a.id DESC",
                (ticker, since, iso()),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_news_analysis(self, ticker, input_hash, model, version, inputs, payload):
        with self.connect() as db:
            cursor = db.execute(
                "INSERT INTO news_analyses "
                "(ticker,input_hash,model,prompt_version,generated_at,inputs,payload) "
                "VALUES(?,?,?,?,?,?,?)",
                (ticker, input_hash, model, version, iso(), encode(inputs), encode(payload)),
            )
            return cursor.lastrowid

    def news_analysis(self, ticker, *, input_hash=None, analysis_id=None):
        where, args = "ticker=?", [ticker]
        if input_hash is not None:
            where += " AND input_hash=?"
            args.append(input_hash)
        if analysis_id is not None:
            where += " AND id=?"
            args.append(analysis_id)
        with self.connect() as db:
            row = db.execute(
                f"SELECT * FROM news_analyses WHERE {where} ORDER BY id DESC LIMIT 1", args
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        for key in ("inputs", "payload"):
            result[key] = json.loads(result[key])
        return result

    def latest_assessments(self, tickers):
        """Per-article AI assessments from each ticker's most recent stored analysis."""
        result = {}
        for ticker in tickers:
            analysis = self.news_analysis(ticker)
            if not analysis:
                continue
            for item in analysis["payload"].get("article_assessments", []):
                existing = result.get(item["article_id"])
                if existing and existing["generated_at"] >= analysis["generated_at"]:
                    continue
                result[item["article_id"]] = {
                    "ticker": ticker,
                    "sentiment": item["sentiment"],
                    "impact": item["impact"],
                    "rationale": item["rationale"],
                    "analysis_id": analysis["id"],
                    "model": analysis["model"],
                    "generated_at": analysis["generated_at"],
                }
        return result

    def begin_llm_attempt(self, ticker, input_hash, model, maximum):
        # Count attempted calls (including failures/retries), atomically and across restarts.
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            since = iso(utcnow().replace(hour=0, minute=0, second=0, microsecond=0))
            count = db.execute(
                "SELECT COUNT(*) FROM llm_attempts WHERE started_at>=?", (since,)
            ).fetchone()[0]
            if count >= maximum:
                return None
            return db.execute(
                "INSERT INTO llm_attempts (ticker,input_hash,model,started_at,status) "
                "VALUES(?,?,?,?, 'running')",
                (ticker, input_hash, model, iso()),
            ).lastrowid

    def finish_llm_attempt(self, attempt_id, status, error=None, usage=None):
        with self.connect() as db:
            db.execute(
                "UPDATE llm_attempts SET completed_at=?,status=?,error=?,usage=? WHERE id=?",
                (iso(), status, error, encode(usage) if usage is not None else None, attempt_id),
            )

    def llm_attempts(self, ticker=None, limit=50):
        with self.connect() as db:
            where, args = ("WHERE ticker=?", [ticker]) if ticker else ("", [])
            rows = db.execute(
                f"SELECT * FROM llm_attempts {where} ORDER BY id DESC LIMIT ?", (*args, limit)
            ).fetchall()
        return [
            dict(row) | {"usage": json.loads(row["usage"]) if row["usage"] else None}
            for row in rows
        ]

    def save_signal(self, payload, input_hash, config_hash):
        """Append-only. An identical input hash returns the original record unchanged."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT id FROM signals WHERE ticker=? AND input_hash=?",
                (payload["ticker"], input_hash),
            ).fetchone()
            if existing:
                return existing[0], False
            cursor = db.execute(
                "INSERT INTO signals (ticker,scoring_version,config_version,config_hash,"
                "input_hash,created_at,score,label,status,reference_session,reference_close,"
                "payload) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    payload["ticker"],
                    payload["scoring_version"],
                    payload["config_version"],
                    config_hash,
                    input_hash,
                    payload["computed_at"],
                    payload["score"],
                    payload["label"],
                    payload["status"],
                    payload["inputs"]["indicator_as_of_session"],
                    payload["inputs"]["last_close"],
                    encode(payload),
                ),
            )
            return cursor.lastrowid, True

    def signal(self, signal_id, ticker=None):
        where, args = "id=?", [signal_id]
        if ticker:
            where += " AND ticker=?"
            args.append(ticker)
        with self.connect() as db:
            row = db.execute(f"SELECT * FROM signals WHERE {where}", args).fetchone()
        return self._signal(row) if row else None

    def signals(self, ticker=None, limit=100, offset=0):
        where, args = ("WHERE ticker=?", [ticker]) if ticker else ("", [])
        with self.connect() as db:
            total = db.execute(f"SELECT COUNT(*) FROM signals {where}", args).fetchone()[0]
            rows = db.execute(
                f"SELECT * FROM signals {where} ORDER BY id DESC LIMIT ? OFFSET ?",
                (*args, limit, offset),
            ).fetchall()
        return {
            "items": [self._signal(row) for row in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def latest_signals(self, tickers):
        with self.connect() as db:
            rows = [
                db.execute(
                    "SELECT * FROM signals WHERE ticker=? ORDER BY id DESC LIMIT 1", (ticker,)
                ).fetchone()
                for ticker in tickers
            ]
        return [self._signal(row) for row in rows if row]

    @staticmethod
    def _signal(row):
        result = dict(row)
        result["payload"] = json.loads(result["payload"])
        return result

    def save_alert(self, alert):
        """Append-only, deduplicated by the rule's natural key."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT id FROM alerts WHERE dedupe_key=?", (alert["dedupe_key"],)
            ).fetchone()
            if existing:
                return existing[0], False
            cursor = db.execute(
                "INSERT INTO alerts (ticker,rule,severity,created_at,dedupe_key,title,detail,"
                "evidence) VALUES(?,?,?,?,?,?,?,?)",
                (
                    alert["ticker"],
                    alert["rule"],
                    alert["severity"],
                    alert["created_at"],
                    alert["dedupe_key"],
                    alert["title"],
                    alert["detail"],
                    encode(alert["evidence"]),
                ),
            )
            return cursor.lastrowid, True

    def alerts(self, unacknowledged_only=False, limit=100):
        where = "WHERE acknowledged_at IS NULL" if unacknowledged_only else ""
        with self.connect() as db:
            rows = db.execute(
                f"SELECT * FROM alerts {where} ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            total = db.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
            unread = db.execute(
                "SELECT COUNT(*) FROM alerts WHERE acknowledged_at IS NULL"
            ).fetchone()[0]
        return {
            "items": [dict(row) | {"evidence": json.loads(row["evidence"])} for row in rows],
            "total": total,
            "unacknowledged": unread,
            "limit": limit,
        }

    def acknowledge_alert(self, alert_id):
        with self.connect() as db:
            changed = db.execute(
                "UPDATE alerts SET acknowledged_at=? WHERE id=? AND acknowledged_at IS NULL",
                (iso(), alert_id),
            ).rowcount
            row = db.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone()
        if not row:
            return None
        return dict(row) | {"evidence": json.loads(row["evidence"]), "changed": bool(changed)}

    def acknowledge_all_alerts(self):
        with self.connect() as db:
            return db.execute(
                "UPDATE alerts SET acknowledged_at=? WHERE acknowledged_at IS NULL", (iso(),)
            ).rowcount

    def save_brief(self, input_hash, model, version, facts, payload):
        with self.connect() as db:
            cursor = db.execute(
                "INSERT INTO daily_briefs (input_hash,model,prompt_version,generated_at,"
                "period_start,period_end,facts,payload) VALUES(?,?,?,?,?,?,?,?)",
                (
                    input_hash,
                    model,
                    version,
                    iso(),
                    facts["period_start"],
                    facts["period_end"],
                    encode(facts),
                    encode(payload),
                ),
            )
            return cursor.lastrowid

    def brief(self, input_hash=None, brief_id=None):
        where, args = "1=1", []
        if input_hash is not None:
            where += " AND input_hash=?"
            args.append(input_hash)
        if brief_id is not None:
            where += " AND id=?"
            args.append(brief_id)
        with self.connect() as db:
            row = db.execute(
                f"SELECT * FROM daily_briefs WHERE {where} ORDER BY id DESC LIMIT 1", args
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        for key in ("facts", "payload"):
            result[key] = json.loads(result[key])
        return result

    def briefs(self, limit=20):
        with self.connect() as db:
            rows = db.execute(
                "SELECT id,generated_at,period_start,period_end,model,prompt_version "
                "FROM daily_briefs ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def begin_run(self, run_id, trigger, tickers):
        with self.connect() as db:
            db.execute(
                "INSERT INTO refresh_runs VALUES(?,?,?,?,?,?,?)",
                (run_id, "running", trigger, iso(), None, encode(tickers), "{}"),
            )

    def finish_run(self, run_id, status, results):
        with self.connect() as db:
            db.execute(
                "UPDATE refresh_runs SET status=?,completed_at=?,results=? WHERE id=?",
                (status, iso(), encode(results), run_id),
            )

    def runs(self, limit=20):
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM refresh_runs ORDER BY started_at DESC LIMIT ?", (limit,)
            )
            return [self._run(row) for row in rows]

    def run(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM refresh_runs WHERE id=?", (run_id,)).fetchone()
            return self._run(row) if row else None

    @staticmethod
    def _run(row):
        result = dict(row)
        result["tickers"] = json.loads(result["tickers"])
        result["results"] = json.loads(result["results"])
        return result
