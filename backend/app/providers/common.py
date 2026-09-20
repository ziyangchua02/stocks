import asyncio
import random
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser

import httpx


class ProviderError(Exception):
    """Controlled messages only; never expose provider bodies or request headers."""

    def __init__(self, code, retry_seconds=60):
        self.code = code
        self.retry_seconds = retry_seconds
        super().__init__(code)


class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(value, limit=4000):
    parser = TextOnly()
    parser.feed(str(value or ""))
    return " ".join(unescape(" ".join(parser.parts)).split())[:limit]


def retry_delay(value):
    try:
        return max(1, float(value))
    except (ValueError, TypeError):
        try:
            return max(1, (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return 60


class Http:
    def __init__(self, config, client=None):
        self.config = config
        self.client = client or httpx.AsyncClient(
            timeout=config.request_timeout_seconds,
            headers={"User-Agent": "PersonalStockResearch/0.1"},
            follow_redirects=True,
        )
        self._lock = asyncio.Lock()
        self._next_finnhub = 0.0

    async def get(self, url, *, params=None, headers=None, finnhub=False):
        for attempt in range(self.config.retry_attempts):
            if finnhub:
                async with self._lock:
                    await asyncio.sleep(max(0, self._next_finnhub - time.monotonic()))
                    self._next_finnhub = (
                        time.monotonic() + 60 / self.config.finnhub_requests_per_minute
                    )
            try:
                response = await self.client.get(url, params=params, headers=headers)
            except httpx.RequestError:
                if attempt + 1 == self.config.retry_attempts:
                    raise ProviderError("network_or_timeout") from None
            else:
                if response.status_code == 429:
                    delay = retry_delay(response.headers.get("Retry-After"))
                    # Long server cooldowns are persisted instead of blocking the refresh worker.
                    if delay > 5 or attempt + 1 == self.config.retry_attempts:
                        raise ProviderError("rate_limited", retry_seconds=delay)
                    await asyncio.sleep(delay)
                    continue
                if response.status_code in {401, 403}:
                    raise ProviderError("unauthorized_or_plan_restricted", retry_seconds=3600)
                if 500 <= response.status_code < 600:
                    if attempt + 1 == self.config.retry_attempts:
                        raise ProviderError("provider_server_error")
                elif response.is_error:
                    raise ProviderError(f"http_{response.status_code}", retry_seconds=900)
                else:
                    return response
            await asyncio.sleep(2**attempt + random.uniform(0, 0.25))
        raise ProviderError("request_failed")

    async def close(self):
        await self.client.aclose()
