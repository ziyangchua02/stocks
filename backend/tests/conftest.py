from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.db.store import Store
from app.jobs.market import MarketClock
from app.main import create_app
from app.models import Article, Bar, Quote, iso, utcnow
from app.providers.common import ProviderError
from app.settings import Config, Environment, Seed


@pytest.fixture
def config():
    return Config(
        scheduler_enabled=False,
        seed_watchlist=[Seed(ticker="AAPL", company_name="Apple")],
        news_analysis={"enabled": False},
    )


@pytest.fixture
def store(tmp_path, config):
    db = Store(tmp_path / "test.sqlite3")
    db.initialize(config.seed_watchlist)
    return db


class FakeProvider:
    def __init__(self, name="yfinance", fail=False):
        self.name, self.fail = name, fail
        self.calls = []

    def record(self, kind):
        self.calls.append(kind)
        if self.fail:
            raise ProviderError("test_provider_down")

    async def quote(self, ticker):
        self.record("quote")
        return Quote(
            ticker=ticker,
            price=100,
            source=self.name,
            source_url="https://example.com/quote",
            source_as_of=utcnow(),
            fetched_at=utcnow(),
        ).model_dump(mode="json")

    async def history(self, ticker):
        self.record("history")
        market = MarketClock()
        day = market.state()["last_completed_session"]
        return [
            Bar(
                ticker=ticker,
                session_date=day,
                open=99,
                high=102,
                low=98,
                close=100,
                adjusted_close=100,
                volume=10000,
                source=self.name,
                source_url="https://example.com/history",
                source_as_of=market.bar_label(day),
                fetched_at=utcnow(),
                is_complete=True,
                adjustment="test",
            ).model_dump(mode="json")
        ]

    async def fundamentals(self, ticker):
        self.record("fundamentals")
        return {
            "ticker": ticker,
            "source": self.name,
            "source_as_of": None,
            "fetched_at": iso(),
            "source_url": "https://example.com/fundamentals",
            "as_of_note": "Unknown as-of",
            "raw": {"trailingPE": 20},
        }

    async def news(self, ticker):
        self.record("news")
        article = Article(
            title="Apple reports results",
            url="https://example.com/results",
            publisher="Example",
            summary="Reported results.",
            published_at=utcnow() - timedelta(hours=1),
            fetched_at=utcnow(),
            provider="finnhub",
        )
        return {"articles": [article.model_dump(mode="json")], "rejected_items": 0}


@pytest.fixture
def providers():
    return FakeProvider(), FakeProvider("finnhub"), None, []


@pytest.fixture
def client(tmp_path, config, providers):
    env = Environment(
        _env_file=None,
        database_path=tmp_path / "api.sqlite3",
        finnhub_api_key="test-key",
        gemini_api_key="unused-test-key",
    )
    app = create_app(env, config, providers)
    with TestClient(app) as test_client:
        yield test_client


def refresh_and_wait(client, body=None):
    response = client.post("/api/refresh", json=body or {})
    assert response.status_code == 202

    async def finish():
        await client.app.state.ingestion.task

    client.portal.call(finish)
    return client.get(response.json()["status_url"]).json()
