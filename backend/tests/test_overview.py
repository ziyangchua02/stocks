import pytest

from app.models import Quote, utcnow
from app.settings import Index
from tests.conftest import refresh_and_wait


@pytest.fixture
def config_with_indices(config):
    config.market_indices = [Index(symbol="^GSPC", name="S&P 500")]
    return config


def test_overview_reports_cached_state_without_provider_calls(client):
    refresh_and_wait(client)
    calls = list(client.app.state.ingestion.providers[0][1].calls)
    body = client.get("/api/overview").json()
    assert client.app.state.ingestion.providers[0][1].calls == calls
    assert body["market"]["timezone"] == "America/New_York"
    assert [row["ticker"] for row in body["tickers"]] == ["AAPL"]
    assert body["tickers"][0]["quote"]["status"] in {"cached", "stale"}
    assert body["last_refresh"]["status"] in {"completed", "partial"}
    assert "Not financial advice" in body["disclaimer"]


def test_indices_are_fetched_and_reported_with_freshness(tmp_path, config_with_indices):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.settings import Environment
    from tests.conftest import FakeProvider

    env = Environment(
        _env_file=None,
        database_path=tmp_path / "indices.sqlite3",
        finnhub_api_key="test-key",
        gemini_api_key="unused",
    )
    providers = (FakeProvider(), FakeProvider("finnhub"), None, [])
    with TestClient(create_app(env, config_with_indices, providers)) as client:
        run = refresh_and_wait(client)
        assert run["results"]["indices"]["^GSPC"]["status"] == "fetched"
        index = client.get("/api/overview").json()["indices"][0]
        assert index["symbol"] == "^GSPC" and index["name"] == "S&P 500"
        assert index["data"]["price"] > 0
        assert index["data"]["source_as_of"] and index["data"]["fetched_at"]


def test_missing_index_quote_is_reported_not_omitted(client, config):
    config.market_indices = [Index(symbol="^IXIC", name="Nasdaq Composite")]
    body = client.get("/api/overview").json()
    index = body["indices"][0]
    assert index["status"] == "unavailable"
    assert index["data"] is None and index["reason"]


def test_movers_rank_watchlist_quotes_and_count_gaps(client):
    refresh_and_wait(client)
    store = client.app.state.store
    client.post("/api/watchlist", json={"ticker": "ZZZZ", "company_name": "Nothing"})
    for ticker, price, previous in (("AAPL", 110.0, 100.0),):
        store.save_snapshot(
            "quote",
            Quote(
                ticker=ticker,
                price=price,
                previous_close=previous,
                change=price - previous,
                change_percent=(price / previous - 1) * 100,
                source="yfinance",
                source_url="https://example.com/quote",
                source_as_of=utcnow(),
                fetched_at=utcnow(),
            ).model_dump(mode="json"),
        )
    movers = client.get("/api/overview").json()["movers"]
    assert movers["gainers"][0]["ticker"] == "AAPL"
    assert movers["gainers"][0]["change_percent"] == pytest.approx(10.0)
    # One ticker, one heading: a riser must not also be listed as a faller.
    assert movers["losers"] == []
    assert movers["missing_quotes"] == 1
    assert "not a market-wide scan" in movers["scope"]


def test_news_assessments_are_attached_or_explicitly_null(client, store):
    refresh_and_wait(client)
    body = client.get("/api/news?include_assessments=true").json()
    assert body["items"]
    assert all("assessment" in article for article in body["items"])
    # Analysis is disabled in tests, so every assessment must be null rather than neutral.
    assert all(article["assessment"] is None for article in body["items"])
    assert "not that it is neutral" in body["assessment_note"]
    assert "assessment" not in client.get("/api/news").json()["items"][0]


def test_headlines_only_include_analyzed_articles(client):
    refresh_and_wait(client)
    headlines = client.get("/api/overview").json()["headlines"]
    assert headlines["items"] == []
    assert headlines["article_count"] >= 1
    assert headlines["analyzed_count"] == 0
