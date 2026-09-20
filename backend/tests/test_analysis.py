import sqlite3
from datetime import timedelta
from pathlib import Path

from conftest import refresh_and_wait

from app.db.store import Store
from app.jobs.market import MarketClock
from app.models import iso, utcnow
from app.services.analysis import Analysis


def test_indicators_persist_and_reads_are_free_of_provider_calls(client, providers):
    assert client.get("/api/tickers/AAPL/indicators").json()["status"] == "unavailable"
    run = refresh_and_wait(client)
    assert run["results"]["tickers"]["AAPL"]["indicators"]["status"] == "computed"
    calls = list(providers[0].calls), list(providers[1].calls)
    result = client.get("/api/tickers/AAPL/indicators?include_series=true&limit=1").json()
    assert result["data"]["technicals"]["metrics"]["sma200"]["value"] is None
    assert len(result["data"]["technicals"]["series"]) == 1
    snapshot_id = result["data"]["snapshot_id"]
    assert (providers[0].calls, providers[1].calls) == calls
    assert client.get("/api/tickers/AAPL/indicators?limit=0").status_code == 422
    refresh_and_wait(client)
    assert client.get("/api/tickers/AAPL/indicators").json()["data"]["snapshot_id"] == snapshot_id
    assert client.get("/api/tickers/ZZZZ/indicators").status_code == 404


def test_new_input_creates_new_snapshot_and_keeps_previous_values(client):
    refresh_and_wait(client)
    analysis, store = client.app.state.analysis, client.app.state.store
    previous = store.indicators("AAPL")
    raw = store.snapshot("AAPL", "fundamentals")
    raw["raw"]["trailingPE"] = 30
    raw["fetched_at"] = iso(utcnow() + timedelta(seconds=1))
    store.save_snapshot("fundamentals", raw)
    analysis.build("AAPL")
    current = store.indicators("AAPL")
    assert current["snapshot_id"] != previous["snapshot_id"]
    assert current["fundamentals"]["fields"]["pe"]["value"] == 30
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM indicator_snapshots").fetchone()[0] == 2


def test_indicator_freshness_ages_without_refreshing_or_writing(client):
    refresh_and_wait(client)
    analysis = client.app.state.analysis
    before = analysis.view("AAPL")
    later = analysis.view("AAPL", now=utcnow() + timedelta(days=7))
    assert later["status"] == "stale"
    assert later["data"]["technicals"]["freshness"] == "stale"
    assert later["data"]["fundamentals"]["freshness"] == "stale"
    assert later["data"]["snapshot_id"] == before["data"]["snapshot_id"]


def test_schema_one_migrates_without_losing_existing_watchlist(tmp_path, config):
    path = tmp_path / "old.sqlite3"
    migration = Path(__file__).parents[1] / "app/db/migrations/001_initial.sql"
    with sqlite3.connect(path) as db:
        db.executescript(migration.read_text())
        db.execute("PRAGMA user_version=1")
        db.execute("INSERT INTO metadata VALUES('seeded','true')")
        db.execute("INSERT INTO watchlist VALUES('MSFT','Microsoft',?)", (iso(),))
    store = Store(path)
    store.initialize(config.seed_watchlist)
    assert [x["ticker"] for x in store.watchlist()] == ["MSFT"]
    with store.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 5
    assert Analysis(store, MarketClock(), config).view("MSFT")["status"] == "unavailable"
