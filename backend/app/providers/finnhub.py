from datetime import UTC, datetime, timedelta

from pydantic import ValidationError

from app.models import Article, Bar, Quote, number, utcnow
from app.providers.common import ProviderError, plain_text


class Finnhub:
    BASE = "https://finnhub.io/api/v1"

    def __init__(self, key, http, market, config):
        self.key = key
        self.http = http
        self.market = market
        self.config = config

    async def get(self, path, **params):
        if not self.key:
            raise ProviderError("api_key_missing", retry_seconds=60)
        response = await self.http.get(
            self.BASE + path, params=params, headers={"X-Finnhub-Token": self.key}, finnhub=True
        )
        try:
            data = response.json()
        except ValueError:
            raise ProviderError("invalid_json") from None
        if isinstance(data, dict) and data.get("error"):
            raise ProviderError("provider_rejected_request", retry_seconds=900)
        return data

    async def quote(self, ticker):
        data = await self.get("/quote", symbol=ticker)
        price, stamp = number(data.get("c")), number(data.get("t"))
        if not price or price <= 0 or not stamp or stamp <= 0:
            raise ProviderError("quote_missing_price_or_timestamp")
        previous = number(data.get("pc"))
        previous = previous if previous and previous > 0 else None
        return Quote(
            ticker=ticker,
            price=price,
            previous_close=previous,
            change=price - previous if previous else None,
            change_percent=(price / previous - 1) * 100 if previous else None,
            source="finnhub",
            source_url="https://finnhub.io/docs/api/quote",
            source_as_of=datetime.fromtimestamp(stamp, UTC),
            fetched_at=utcnow(),
            currency=None,  # Quote endpoint does not provide currency or volume.
            session="provider_unspecified",
        ).model_dump(mode="json")

    async def fundamentals(self, ticker):
        data = await self.get("/stock/metric", symbol=ticker, metric="all")
        raw = data.get("metric")
        if not isinstance(raw, dict) or not raw:
            raise ProviderError("fundamentals_unavailable")
        return {
            "ticker": ticker,
            "source": "finnhub",
            "source_url": "https://finnhub.io/docs/api/basic-financials",
            "source_as_of": None,
            "fetched_at": utcnow().isoformat(),
            "as_of_note": "Raw provider metrics have mixed periods; date fields are preserved.",
            "raw": raw,
        }

    async def history(self, ticker):
        now = utcnow()
        data = await self.get(
            "/stock/candle",
            symbol=ticker,
            resolution="D",
            **{"from": int((now - timedelta(days=730)).timestamp()), "to": int(now.timestamp())},
        )
        if data.get("s") != "ok":
            raise ProviderError("history_unavailable")
        keys = ["t", "o", "h", "l", "c", "v"]
        if any(not isinstance(data.get(k), list) for k in keys):
            raise ProviderError("invalid_candle_response")
        if len({len(data[k]) for k in keys}) != 1:
            raise ProviderError("invalid_candle_response")
        bars = []
        for stamp, opening, high, low, close, volume in zip(*(data[k] for k in keys), strict=True):
            # Finnhub daily timestamps label the session by their UTC date.
            day = datetime.fromtimestamp(stamp, UTC).date().isoformat()
            bar = Bar(
                ticker=ticker,
                session_date=day,
                open=opening,
                high=high,
                low=low,
                close=close,
                volume=volume,
                source="finnhub",
                source_url="https://finnhub.io/docs/api/stock-candles",
                source_as_of=self.market.bar_label(day),
                fetched_at=now,
                is_complete=self.market.is_complete(day, now),
                adjustment="Provider OHLC; dividend-adjusted close unavailable",
            )
            bars.append(bar.model_dump(mode="json"))
        if not bars:
            raise ProviderError("history_unavailable")
        return bars

    async def news(self, ticker):
        now = utcnow()
        since = now - timedelta(hours=self.config.news_lookback_hours)
        data = await self.get(
            "/company-news",
            symbol=ticker,
            **{"from": since.date().isoformat(), "to": now.date().isoformat()},
        )
        if not isinstance(data, list):
            raise ProviderError("invalid_news_response")
        articles = []
        rejected = 0
        for item in data:
            try:
                published = datetime.fromtimestamp(float(item["datetime"]), UTC)
                if not since <= published <= now:
                    continue
                article = Article(
                    title=plain_text(item.get("headline"), 500),
                    url=item["url"],
                    publisher=plain_text(item.get("source", "Finnhub"), 120),
                    summary=plain_text(item.get("summary")),
                    published_at=published,
                    fetched_at=now,
                    provider="finnhub",
                )
                articles.append(article.model_dump(mode="json"))
            except (KeyError, TypeError, ValueError, OverflowError, OSError, ValidationError):
                rejected += 1
        return {"articles": articles, "rejected_items": rejected}
