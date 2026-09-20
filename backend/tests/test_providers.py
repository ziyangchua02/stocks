from datetime import timedelta
from email.utils import format_datetime

import httpx
import pytest

from app.jobs.market import MarketClock
from app.models import utcnow
from app.providers.common import Http, ProviderError
from app.providers.finnhub import Finnhub
from app.providers.rss import RSS
from app.settings import Feed


async def test_http_rate_limit_respects_retry_after(config):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(429, headers={"Retry-After": "120"})
        )
    )
    http = Http(config, client)
    with pytest.raises(ProviderError) as error:
        await http.get("https://example.com")
    assert error.value.code == "rate_limited"
    assert error.value.retry_seconds == 120
    await http.close()


async def test_transient_server_error_retried(config, monkeypatch):
    attempts = []

    def handler(request):
        attempts.append(request)
        return httpx.Response(503 if len(attempts) == 1 else 200, json={"ok": True})

    async def no_sleep(seconds):
        pass

    monkeypatch.setattr("app.providers.common.asyncio.sleep", no_sleep)
    http = Http(config, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert (await http.get("https://example.com")).json() == {"ok": True}
    assert len(attempts) == 2
    await http.close()


async def test_finnhub_auth_uses_header_and_rejects_zero_quote(config):
    def handler(request):
        assert request.headers["X-Finnhub-Token"] == "private-test-key"
        assert "private-test-key" not in str(request.url)
        return httpx.Response(200, json={"c": 0, "t": 0})

    http = Http(config, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    provider = Finnhub("private-test-key", http, MarketClock(), config)
    with pytest.raises(ProviderError, match="missing_price_or_timestamp"):
        await provider.quote("AAPL")
    await http.close()


async def test_finnhub_news_enforces_48_hours(config):
    now = utcnow()
    items = [
        {
            "datetime": int((now - timedelta(hours=hours)).timestamp()),
            "headline": f"Article {hours}",
            "url": f"https://example.com/{hours}",
        }
        for hours in [1, 49, -1]
    ]
    http = Http(
        config,
        httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=items))
        ),
    )
    result = await Finnhub("key", http, MarketClock(), config).news("AAPL")
    assert len(result["articles"]) == 1
    assert result["articles"][0]["title"] == "Article 1"
    await http.close()


async def test_rss_missing_date_is_not_replaced_with_now(config):
    stamp = format_datetime(utcnow() - timedelta(hours=1))
    xml = f"""<rss version="2.0"><channel><title>Example</title>
      <item><title>Apple reports results</title><link>https://example.com/good</link>
      <pubDate>{stamp}</pubDate><description>&lt;b&gt;Summary&lt;/b&gt;</description></item>
      <item><title>Undated</title><link>https://example.com/undated</link></item>
    </channel></rss>"""
    http = Http(
        config,
        httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, text=xml))
        ),
    )
    result = await RSS(http, config).fetch(Feed(name="Example", url="https://example.com/rss"))
    assert len(result["articles"]) == 1
    assert result["rejected_items"] == 1
    assert result["articles"][0]["summary"] == "Summary"
    assert RSS.relevant(result["articles"][0], "AAPL", "Apple")
    assert not RSS.relevant({"title": "A story about T cells", "summary": ""}, "T", "")
    await http.close()
