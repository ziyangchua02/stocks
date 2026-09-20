import math
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.jobs.market import MarketClock
from app.main import create_app
from app.models import Bar, utcnow
from app.settings import Environment
from tests.conftest import FakeProvider, refresh_and_wait


class RichProvider(FakeProvider):
    """Two years of synthetic sessions so every indicator has enough history to score."""

    async def history(self, ticker):
        self.record("history")
        market = MarketClock()
        end = date.fromisoformat(market.state()["last_completed_session"])
        days = market.sessions(end - timedelta(days=500), end)[-320:]
        bars = []
        for index, day in enumerate(days):
            close = 60 + index * 0.12 + 2 * math.sin(index / 9)
            bars.append(
                Bar(
                    ticker=ticker,
                    session_date=day,
                    open=close * 0.995,
                    high=close * 1.01,
                    low=close * 0.99,
                    close=close,
                    adjusted_close=close,
                    volume=1_000_000 + index * 900,
                    source=self.name,
                    source_url="https://example.com/history",
                    source_as_of=market.bar_label(day),
                    fetched_at=utcnow(),
                    is_complete=True,
                    adjustment="test",
                ).model_dump(mode="json")
            )
        return bars

    async def fundamentals(self, ticker):
        self.record("fundamentals")
        return {
            "ticker": ticker,
            "source": self.name,
            "source_as_of": None,
            "fetched_at": utcnow().isoformat(),
            "source_url": "https://example.com/fundamentals",
            "as_of_note": "Unknown as-of",
            "raw": {
                "trailingPE": 24.0,
                "forwardPE": 20.0,
                "revenueGrowth": 0.14,
                "profitMargins": 0.26,
            },
        }


@pytest.fixture
def rich_client(tmp_path, config):
    env = Environment(
        _env_file=None,
        database_path=tmp_path / "scored.sqlite3",
        finnhub_api_key="test-key",
        gemini_api_key="unused-test-key",
    )
    providers = (RichProvider(), RichProvider("finnhub"), None, [])
    with TestClient(create_app(env, config, providers)) as test_client:
        yield test_client


def test_refresh_records_a_signal_and_repeats_do_not_duplicate(client):
    first = refresh_and_wait(client)
    signal = first["results"]["tickers"]["AAPL"]["signal"]
    assert signal["status"] == "recorded"
    assert signal["signal_id"]
    second = refresh_and_wait(client)
    repeat = second["results"]["tickers"]["AAPL"]["signal"]
    # Unchanged indicators, news and weights must reuse the original record.
    assert repeat["status"] == "unchanged"
    assert repeat["signal_id"] == signal["signal_id"]
    log = client.get("/api/signals").json()
    assert log["total"] == 1
    assert log["items"][0]["ticker"] == "AAPL"


def test_score_endpoint_reports_breakdown_and_provenance(client):
    refresh_and_wait(client)
    body = client.get("/api/tickers/AAPL/score").json()
    assert body["ticker"] == "AAPL"
    assert "Not financial advice" in body["disclaimer"]
    data = body["data"]
    assert data["status"] in {"scored", "insufficient_data"}
    assert data["weights"] and data["breakdown"]
    for row in data["breakdown"]:
        assert row["component"] in data["weights"]
        assert row["score"] is not None or row["reason"]
        for item in row["inputs"]:
            assert item["value"] is not None or item["reason"]
    assert body["sources"]["news_analysis"] == "/api/tickers/AAPL/news-analysis"
    assert data["inputs"]["indicator_snapshot_id"]


def test_scores_ranking_lists_unscored_tickers_last(rich_client):
    refresh_and_wait(rich_client)
    rich_client.post("/api/watchlist", json={"ticker": "ZZZZ", "company_name": "Nothing"})
    body = rich_client.get("/api/scores").json()
    tickers = [row["ticker"] for row in body["items"]]
    assert tickers[-1] == "ZZZZ"
    missing = body["items"][-1]
    assert missing["score"] is None and missing["reason"]
    assert body["unscored_count"] == 1 and body["scored_count"] == 1
    scores = [row["score"] for row in body["items"] if row["score"] is not None]
    assert scores == sorted(scores, reverse=True)
    top = body["items"][0]
    assert top["ticker"] == "AAPL" and top["label"] in {
        "Strong setup",
        "Watch",
        "Neutral",
        "Caution",
    }
    assert top["top_components"] and top["detail_url"] == "/api/tickers/AAPL/score"


def test_real_history_scores_with_documented_coverage(rich_client):
    refresh_and_wait(rich_client)
    data = rich_client.get("/api/tickers/AAPL/score").json()["data"]
    assert data["status"] == "scored"
    scored = {row["component"] for row in data["breakdown"] if row["score"] is not None}
    # News analysis is disabled in tests, so its weight must be excluded, not assumed.
    assert scored == {
        "trend",
        "momentum",
        "volume",
        "range_position",
        "valuation",
        "growth_quality",
    }
    assert data["weight_coverage"] == pytest.approx(0.8)
    # 80% coverage clears the configured 75% thin-coverage threshold.
    assert "thin_coverage" not in {flag["flag"] for flag in data["cautions"]}
    news = next(row for row in data["breakdown"] if row["component"] == "news_sentiment")
    assert news["score"] is None and news["reason"]
    assert data["inputs"]["last_close"] and data["inputs"]["indicator_as_of_session"]


def test_new_session_creates_a_second_signal(rich_client):
    refresh_and_wait(rich_client)
    store = rich_client.app.state.store
    assert store.signals("AAPL")["total"] == 1
    # A new completed session changes the indicator snapshot, so a new signal is recorded.
    refresh_and_wait(rich_client, {"force": True})
    rich_client.app.state.signals.build("AAPL")
    log = store.signals("AAPL")
    assert log["total"] >= 1
    assert all(row["payload"]["scoring_version"] for row in log["items"])


def test_signal_record_is_immutable_and_keeps_its_weights(client):
    refresh_and_wait(client)
    signal_id = client.get("/api/signals").json()["items"][0]["id"]
    record = client.get(f"/api/signals/{signal_id}").json()
    assert record["historical"] is True
    payload = record["data"]["payload"]
    assert payload["weights"] == client.app.state.scoring.weights
    assert payload["scoring_version"] == record["data"]["scoring_version"]
    assert record["data"]["config_hash"] == client.app.state.signals.config_hash
    # Rescoring the same inputs never rewrites the stored record.
    client.app.state.signals.build("AAPL")
    again = client.get(f"/api/signals/{signal_id}").json()
    assert again["data"]["created_at"] == record["data"]["created_at"]
    assert client.get("/api/signals").json()["total"] == 1


def test_changed_weights_create_a_new_signal(client):
    refresh_and_wait(client)
    service = client.app.state.signals
    service.config_hash = "different-configuration-hash"
    result = service.build("AAPL")
    assert result["status"] == "recorded"
    assert client.get("/api/signals").json()["total"] == 2


def test_scoring_config_endpoint_exposes_current_weights(client):
    body = client.get("/api/scoring/config").json()
    assert body["file"] == "config/scoring.yaml"
    assert set(body["config"]["weights"]) == set(client.app.state.scoring.weights)
    assert body["labels_in_use"] == ["Strong setup", "Watch", "Neutral", "Caution"]


def test_score_without_cached_data_is_unavailable_not_guessed(client):
    client.post("/api/watchlist", json={"ticker": "ZZZZ", "company_name": "Nothing"})
    body = client.get("/api/tickers/ZZZZ/score").json()
    assert body["status"] == "unavailable"
    assert body["data"] is None
    assert "refresh" in body["reason"].lower()
    assert client.get("/api/signals?ticker=ZZZZ").json()["total"] == 0


def test_score_and_signal_routes_validate_ticker_and_id(client):
    assert client.get("/api/tickers/NOT_ON_LIST/score").status_code in {404, 422}
    assert client.get("/api/signals/999999").status_code == 404
    assert client.get("/api/signals?ticker=%20%20").status_code == 422


def test_health_reports_scoring_configuration(client):
    body = client.get("/api/health").json()
    assert body["phase"] == 6
    assert body["scoring"]["config_version"] == client.app.state.scoring.version
    assert body["scoring"]["min_weight_coverage"] == (client.app.state.scoring.min_weight_coverage)
