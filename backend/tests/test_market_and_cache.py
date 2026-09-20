from datetime import datetime, timedelta

import pytest

from app.jobs.market import MarketClock
from app.models import iso, utcnow
from app.providers.common import ProviderError
from app.services.ingestion import Ingestion


@pytest.mark.parametrize(
    ("stamp", "expected"),
    [
        ("2026-07-03T15:00:00+00:00", False),  # Independence Day observed
        ("2026-09-19T15:00:00+00:00", False),  # Saturday
        ("2026-11-27T17:00:00+00:00", True),  # Half day
        ("2026-11-27T18:01:00+00:00", False),
        ("2026-03-06T13:45:00+00:00", False),  # Before DST
        ("2026-03-09T13:45:00+00:00", True),  # After DST
    ],
)
def test_calendar_holidays_half_days_and_dst(stamp, expected):
    assert MarketClock().state(datetime.fromisoformat(stamp))["is_open"] is expected


def test_scheduler_includes_closing_tick():
    clock = MarketClock()
    assert clock.should_refresh(datetime.fromisoformat("2026-11-27T18:00:10+00:00"))
    assert not clock.should_refresh(datetime.fromisoformat("2026-11-27T18:02:00+00:00"))


def test_weekend_quote_is_current_if_it_matches_last_close(store, config, providers):
    service = Ingestion(store, config, MarketClock(), *providers)
    saturday = datetime.fromisoformat("2026-09-19T12:00:00+00:00")
    assert service.quote_current({"source_as_of": "2026-09-18T20:00:00+00:00"}, saturday)
    assert not service.quote_current({"source_as_of": "2026-09-17T20:00:00+00:00"}, saturday)


async def test_cooldown_survives_force_and_preserves_cache(store, config, providers):
    service = Ingestion(store, config, MarketClock(), *providers)
    store.cache_success("test", {"price": 100}, 60)
    calls = 0

    async def limited():
        nonlocal calls
        calls += 1
        raise ProviderError("rate_limited", retry_seconds=120)

    for _ in range(2):
        with pytest.raises(ProviderError, match="rate_limited"):
            await service.cached("test", 60, limited, force=True)
    assert calls == 1
    assert store.cache("test")["payload"] == {"price": 100}


async def test_expired_cache_fetches_new_value(store, config, providers):
    service = Ingestion(store, config, MarketClock(), *providers)
    store.cache_success("test", {"price": 100}, -1)

    async def updated():
        return {"price": 101}

    assert await service.cached("test", 60, updated) == ({"price": 101}, "fetched")


async def test_rate_limit_cooldown_applies_across_tickers_and_resources(store, config, providers):
    service = Ingestion(store, config, MarketClock(), *providers)
    calls = 0

    async def limited():
        nonlocal calls
        calls += 1
        raise ProviderError("rate_limited", retry_seconds=120)

    for key in ["finnhub:quote:AAPL", "finnhub:news:MSFT"]:
        with pytest.raises(ProviderError, match="rate_limited"):
            await service.cached(key, 60, limited, force=True)
    assert calls == 1


def test_old_quote_is_reported_stale(store, config, providers):
    service = Ingestion(store, config, MarketClock(), *providers)
    store.save_snapshot(
        "quote",
        {
            "ticker": "AAPL",
            "source": "yfinance",
            "price": 100,
            "source_as_of": iso(utcnow() - timedelta(days=10)),
            "fetched_at": iso(),
        },
    )
    assert service.view("AAPL", "quote")["status"] == "stale"
