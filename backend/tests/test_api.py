import asyncio

from conftest import refresh_and_wait


def test_health_and_reads_make_no_provider_calls(client, providers):
    assert client.get("/api/health").json()["telegram"].startswith("disabled")
    assert client.get("/api/tickers/AAPL/quote").json()["status"] == "unavailable"
    assert client.get("/api/news").json()["status"] == "unavailable"
    assert not providers[0].calls and not providers[1].calls
    assert "test-key" not in client.get("/api/health").text


def test_watchlist_crud_validation_and_retention(client):
    assert client.post("/api/watchlist", json={"ticker": " msft "}).status_code == 201
    assert client.post("/api/watchlist", json={"ticker": "MSFT"}).status_code == 200
    assert (
        client.post("/api/watchlist", json={"ticker": "x'; DROP TABLE watchlist"}).status_code
        == 422
    )
    assert client.post("/api/watchlist", json={"ticker": "../.env"}).status_code == 422
    assert client.post("/api/refresh", json={"tickers": ["TSLA"]}).status_code == 422
    refresh_and_wait(client, {"tickers": ["AAPL"]})
    assert client.delete("/api/watchlist/AAPL").status_code == 204
    assert client.get("/api/tickers/AAPL/quote").status_code == 404
    assert client.app.state.store.snapshot("AAPL", "quote") is not None
    assert client.delete("/api/watchlist/MSFT").status_code == 204
    assert client.post("/api/refresh", json={}).status_code == 422


def test_refresh_persists_data_and_reuses_cache(client, providers):
    run = refresh_and_wait(client)
    assert run["status"] == "completed"
    assert client.get("/api/tickers/AAPL/quote").json()["data"]["price"] == 100
    assert len(client.get("/api/tickers/AAPL/history").json()["data"]) == 1
    assert client.get("/api/tickers/AAPL/fundamentals").json()["data"]["source_as_of"] is None
    assert client.get("/api/news?ticker=AAPL").json()["total"] == 1
    calls = len(providers[0].calls), len(providers[1].calls)
    second = refresh_and_wait(client)
    assert second["results"]["tickers"]["AAPL"]["quote"]["status"] == "cached"
    assert calls == (len(providers[0].calls), len(providers[1].calls))


def test_fallback_keeps_primary_failure_visible(client, providers):
    providers[0].fail = True
    run = refresh_and_wait(client)
    quote = client.get("/api/tickers/AAPL/quote").json()
    assert quote["data"]["source"] == "finnhub"
    assert run["results"]["tickers"]["AAPL"]["quote"]["warnings"] == [
        {"provider": "yfinance", "error": "test_provider_down"}
    ]


def test_failure_preserves_cached_data_and_reports_partial(client, providers):
    refresh_and_wait(client)
    previous = client.get("/api/tickers/AAPL/quote").json()["data"]
    providers[0].fail = providers[1].fail = True
    run = refresh_and_wait(client, {"force": True})
    assert run["status"] == "partial"
    assert client.get("/api/tickers/AAPL/quote").json()["data"] == previous
    assert client.get("/api/news").json()["status"] == "partial"


def test_concurrent_refresh_returns_conflict(client, providers):
    async def slow(ticker):
        await asyncio.sleep(30)

    providers[0].quote = slow
    first = client.post("/api/refresh", json={})
    second = client.post("/api/refresh", json={})
    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["detail"]["run_id"] == first.json()["run_id"]


def test_untrusted_browser_origin_cannot_trigger_refresh(client):
    response = client.post("/api/refresh", json={}, headers={"Origin": "https://example.com"})
    assert response.status_code == 403


def test_openapi_and_docs_exist(client):
    assert client.get("/docs").status_code == 200
    schema = client.get("/openapi.json").json()
    assert "/api/refresh" in schema["paths"]
    assert "Not financial advice" in schema["info"]["description"]


def test_unfetched_watchlist_news_is_not_reported_as_complete(client):
    refresh_and_wait(client)
    client.post("/api/watchlist", json={"ticker": "MSFT"})
    response = client.get("/api/news").json()
    assert response["status"] == "partial"
    assert any(
        row["cache_key"] == "finnhub:news:MSFT" and row["error"] == "not_yet_refreshed"
        for row in response["provider_status"]
    )
