import asyncio
import time
from datetime import UTC, datetime

import yfinance as yf

from app.models import Bar, Quote, number, utcnow
from app.providers.common import ProviderError


class Yahoo:
    def __init__(self, config, market, cache_directory):
        self.config = config
        self.market = market
        # Avoid writing cookies/timezone caches outside the project directory.
        yf.set_tz_cache_location(str(cache_directory))
        self._info = {}

    async def _call(self, function):
        for attempt in range(self.config.retry_attempts):
            try:
                return await asyncio.to_thread(function)
            except ProviderError:
                raise
            except Exception as exc:
                if attempt + 1 == self.config.retry_attempts:
                    code = "rate_limited" if "RateLimit" in type(exc).__name__ else "request_failed"
                    raise ProviderError(code, retry_seconds=120) from None
                await asyncio.sleep(2**attempt)

    async def info(self, ticker):
        cached = self._info.get(ticker)
        if cached and time.monotonic() - cached[0] < 30:
            return cached[1]
        info = await self._call(lambda: yf.Ticker(ticker).get_info())
        if not isinstance(info, dict) or not info:
            raise ProviderError("empty_response")
        self._info[ticker] = (time.monotonic(), info)
        return info

    async def quote(self, ticker):
        data = await self.info(ticker)
        price = number(data.get("regularMarketPrice"))
        timestamp = number(data.get("regularMarketTime"))
        if not price or price <= 0 or not timestamp or timestamp <= 0:
            raise ProviderError("quote_missing_price_or_timestamp")
        previous = number(data.get("regularMarketPreviousClose"))
        previous = previous if previous and previous > 0 else None
        quote = Quote(
            ticker=ticker,
            price=price,
            previous_close=previous,
            change=price - previous if previous else None,
            change_percent=(price / previous - 1) * 100 if previous else None,
            volume=number(data.get("regularMarketVolume")),
            currency=data.get("currency"),
            source="yfinance",
            source_url=f"https://finance.yahoo.com/quote/{ticker}/",
            source_as_of=datetime.fromtimestamp(timestamp, UTC),
            fetched_at=utcnow(),
        )
        return quote.model_dump(mode="json")

    async def fundamentals(self, ticker):
        data = await self.info(ticker)
        fields = [
            "shortName",
            "longName",
            "sector",
            "industry",
            "currency",
            "marketCap",
            "trailingPE",
            "forwardPE",
            "revenueGrowth",
            "profitMargins",
            "totalRevenue",
            "earningsTimestamp",
            "earningsTimestampStart",
            "earningsTimestampEnd",
            "mostRecentQuarter",
            "lastFiscalYearEnd",
        ]
        selected = {
            k: (v if isinstance(v, str) else number(v))
            for k in fields
            if (v := data.get(k)) is not None
        }
        if isinstance(data.get("isEarningsDateEstimate"), bool):
            selected["isEarningsDateEstimate"] = data["isEarningsDateEstimate"]
        if not any(k in selected for k in ["marketCap", "totalRevenue", "trailingPE", "forwardPE"]):
            raise ProviderError("fundamentals_unavailable")
        return {
            "ticker": ticker,
            "source": "yfinance",
            "source_url": f"https://finance.yahoo.com/quote/{ticker}/key-statistics/",
            "source_as_of": None,
            "fetched_at": utcnow().isoformat(),
            "as_of_note": "Provider does not supply a common observation time; raw fields may "
            "refer to different reporting periods. Missing fields are unavailable.",
            "raw": selected,
        }

    async def history(self, ticker):
        frame = await self._call(
            lambda: yf.Ticker(ticker).history(
                period=self.config.history_period,
                interval="1d",
                auto_adjust=False,
                actions=True,
                raise_errors=True,
                timeout=self.config.request_timeout_seconds,
            )
        )
        if frame is None or frame.empty:
            raise ProviderError("history_unavailable")
        now = utcnow()
        bars = []
        for stamp, row in frame.iterrows():
            prices = {key.lower(): number(row.get(key)) for key in ["Open", "High", "Low", "Close"]}
            if any(value is None or value <= 0 for value in prices.values()):
                continue
            volume = number(row.get("Volume"))
            if volume is None or volume < 0:
                continue
            day = str(stamp.date())
            bar = Bar(
                ticker=ticker,
                session_date=day,
                **prices,
                adjusted_close=number(row.get("Adj Close")),
                volume=int(volume),
                dividends=number(row.get("Dividends")),
                stock_splits=number(row.get("Stock Splits")),
                source="yfinance",
                source_url=f"https://finance.yahoo.com/quote/{ticker}/history/",
                source_as_of=self.market.bar_label(day),
                fetched_at=now,
                is_complete=self.market.is_complete(day, now),
                adjustment="Yahoo OHLC (split-adjusted); separate dividend-adjusted close",
            )
            bars.append(bar.model_dump(mode="json"))
        if not bars:
            raise ProviderError("history_has_no_valid_bars")
        return bars
