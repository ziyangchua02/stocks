import asyncio
import logging
from datetime import timedelta
from uuid import uuid4

from app.models import iso, parse_time, utcnow
from app.providers.common import ProviderError
from app.providers.rss import RSS
from app.services.analysis import Analysis

logger = logging.getLogger(__name__)


class Ingestion:
    def __init__(
        self, store, config, market, yahoo, finnhub, rss, feeds, news_analysis=None, signals=None
    ):
        self.store = store
        self.config = config
        self.market = market
        self.providers = [("yfinance", yahoo), ("finnhub", finnhub)]
        self.finnhub = finnhub
        self.rss = rss
        self.feeds = feeds
        self.task = None
        self.active_run_id = None
        self.analysis = Analysis(store, market, config)
        self.news_analysis = news_analysis
        self.signals = signals
        self.alerts = None

    async def cached(self, key, ttl, fetch, force=False):
        cached = self.store.cache(key)
        now = utcnow()
        provider = key.split(":", 1)[0]
        cooldown_key = f"provider-cooldown:{provider}"
        if provider in {"finnhub", "yfinance"}:
            cooldown = self.store.cache(cooldown_key)
            if cooldown and cooldown["retry_at"] and parse_time(cooldown["retry_at"]) > now:
                # Fresh cache remains usable during a provider-wide cooldown.
                if (
                    not force
                    and cached
                    and cached["payload"] is not None
                    and cached["expires_at"]
                    and parse_time(cached["expires_at"]) > now
                ):
                    return cached["payload"], "cached"
                raise ProviderError("rate_limited")
        if cached:
            # Explicit refresh bypasses normal TTLs, but never a provider cooldown.
            if cached["error"] and cached["retry_at"] and parse_time(cached["retry_at"]) > now:
                raise ProviderError(cached["error"])
            if (
                not force
                and cached["payload"] is not None
                and cached["expires_at"]
                and parse_time(cached["expires_at"]) > now
                and not cached["error"]
            ):
                return cached["payload"], "cached"
        try:
            value = await fetch()
        except ProviderError as exc:
            self.store.cache_failure(key, exc.code, exc.retry_seconds)
            if exc.code == "rate_limited" and provider in {"finnhub", "yfinance"}:
                self.store.cache_failure(cooldown_key, exc.code, exc.retry_seconds)
            raise
        except Exception:
            # Do not persist request URLs, headers, or provider response bodies in error messages.
            self.store.cache_failure(key, "invalid_or_failed_response", 60)
            raise ProviderError("invalid_or_failed_response") from None
        self.store.cache_success(key, value, ttl)
        return value, "fetched"

    def quote_current(self, quote, now=None):
        now = now or utcnow()
        state = self.market.state(now)
        expected = now if state["is_open"] else parse_time(state["last_close"])
        stamp = parse_time(quote["source_as_of"])
        return (
            expected - timedelta(minutes=self.config.refresh_minutes + 5)
            <= stamp
            <= now + timedelta(minutes=5)
        )

    def history_current(self, bars):
        complete = [bar["session_date"] for bar in bars if bar["is_complete"]]
        expected = self.market.state()["last_completed_session"]
        return bool(complete) and max(complete) >= expected

    async def resource(self, ticker, kind, force):
        errors = []
        ttl = getattr(self.config.cache_seconds, kind)
        for name, provider in self.providers:
            try:
                payload, state = await self.cached(
                    f"{name}:{kind}:{ticker}",
                    ttl,
                    lambda p=provider: getattr(p, kind)(ticker),
                    force,
                )
                if kind == "history":
                    self.store.save_bars(payload)
                    current = self.history_current(payload)
                else:
                    self.store.save_snapshot(kind, payload)
                    current = self.quote_current(payload) if kind == "quote" else True
                if not current:
                    errors.append({"provider": name, "error": "observation_outdated"})
                    continue
                return {
                    "status": state,
                    "provider": name,
                    "warnings": errors,
                    "count": len(payload) if kind == "history" else 1,
                }
            except ProviderError as exc:
                errors.append({"provider": name, "error": exc.code})
        previous = (
            self.store.bars(ticker, 1) if kind == "history" else self.store.snapshot(ticker, kind)
        )
        return {"status": "stale" if previous else "unavailable", "warnings": errors}

    def start(self, tickers, force=False, trigger="manual", analysis_only=False):
        if self.task and not self.task.done():
            return None
        run_id = uuid4().hex
        self.store.begin_run(run_id, trigger, tickers)
        self.active_run_id = run_id
        self.task = asyncio.create_task(
            self.refresh(run_id, tickers, force, analysis_only=analysis_only)
        )
        return run_id

    async def refresh(self, run_id, tickers, force, analysis_only=False):
        results = {"feeds": {}, "tickers": {}}
        try:
            feed_articles = []
            for feed in self.feeds if tickers and not analysis_only else []:
                try:
                    payload, status = await self.cached(
                        "rss:" + feed.url,
                        self.config.cache_seconds.rss,
                        lambda f=feed: self.rss.fetch(f),
                        force,
                    )
                    feed_articles.extend(payload["articles"])
                    results["feeds"][feed.name] = {
                        "status": status,
                        "count": len(payload["articles"]),
                        "rejected_items": payload["rejected_items"],
                        "parse_warning": payload.get("parse_warning", False),
                    }
                except ProviderError as exc:
                    results["feeds"][feed.name] = {"status": "unavailable", "error": exc.code}
            if tickers and not analysis_only:
                results["indices"] = await self.indices(force)
            watchlist = {row["ticker"]: row for row in self.store.watchlist()}
            for ticker in tickers:
                # A removal during a refresh takes effect without deleting historical research data.
                if ticker not in {x["ticker"] for x in self.store.watchlist()}:
                    results["tickers"][ticker] = {"status": "removed_from_watchlist"}
                    continue
                item = {}
                if analysis_only:
                    item["news_analysis"] = await self.news_analysis.build(ticker)
                    item["signal"] = await self.score(ticker)
                    item["alerts"] = await self.alert(ticker)
                    results["tickers"][ticker] = item
                    continue
                for kind in ["quote", "history", "fundamentals"]:
                    item[kind] = await self.resource(ticker, kind, force)
                item["indicators"] = await asyncio.to_thread(self.analysis.build, ticker)
                news = {}
                try:
                    payload, status = await self.cached(
                        f"finnhub:news:{ticker}",
                        self.config.cache_seconds.news,
                        lambda t=ticker: self.finnhub.news(t),
                        force,
                    )
                    self.store.save_articles(ticker, payload["articles"])
                    news["finnhub"] = {
                        "status": status,
                        "count": len(payload["articles"]),
                        "rejected_items": payload["rejected_items"],
                    }
                except ProviderError as exc:
                    news["finnhub"] = {"status": "unavailable", "error": exc.code}
                name = watchlist.get(ticker, {}).get("company_name", "")
                relevant = [a for a in feed_articles if RSS.relevant(a, ticker, name)]
                self.store.save_articles(ticker, relevant)
                news["rss"] = {
                    "matched_count": len(relevant),
                    "note": "Rule-based company-name/ticker matching; not AI analysis.",
                }
                item["news"] = news
                if self.news_analysis:
                    item["news_analysis"] = await self.news_analysis.build(ticker)
                item["signal"] = await self.score(ticker)
                item["alerts"] = await self.alert(ticker)
                results["tickers"][ticker] = item
            degraded = any(
                row.get("status") in {"unavailable", "stale"}
                for data in results["tickers"].values()
                for row in [
                    data.get("quote", {}),
                    data.get("history", {}),
                    data.get("fundamentals", {}),
                    data.get("news", {}).get("finnhub", {}),
                    data.get("news_analysis", {}),
                    data.get("signal", {}),
                ]
            ) or any(
                x["status"] == "unavailable"
                for section in ("feeds", "indices")
                for x in results.get(section, {}).values()
            )
            self.store.finish_run(run_id, "partial" if degraded else "completed", results)
        except asyncio.CancelledError:
            self.store.finish_run(run_id, "interrupted", results)
            raise
        except Exception as exc:
            logger.error("Refresh failed: %s", type(exc).__name__)
            results["error"] = "internal_refresh_error"
            self.store.finish_run(run_id, "failed", results)
        finally:
            self.active_run_id = None

    async def indices(self, force=False):
        """Index quotes for the market snapshot. Yahoo only; no Finnhub fallback exists."""
        results = {}
        yahoo = dict(self.providers)["yfinance"]
        for index in self.config.market_indices:
            try:
                payload, status = await self.cached(
                    f"yfinance:quote:{index.symbol}",
                    self.config.cache_seconds.quote,
                    lambda s=index.symbol: yahoo.quote(s),
                    force,
                )
                self.store.save_snapshot("quote", payload)
                results[index.symbol] = {"status": status, "provider": "yfinance"}
                try:
                    # Daily index bars are the benchmark for signal performance.
                    bars, history_status = await self.cached(
                        f"yfinance:history:{index.symbol}",
                        self.config.cache_seconds.history,
                        lambda s=index.symbol: yahoo.history(s),
                        force,
                    )
                    self.store.save_bars(bars)
                    results[index.symbol]["history"] = {
                        "status": history_status,
                        "count": len(bars),
                    }
                except ProviderError as exc:
                    results[index.symbol]["history"] = {
                        "status": "unavailable",
                        "error": exc.code,
                    }
            except ProviderError as exc:
                previous = self.store.snapshot(index.symbol, "quote")
                results[index.symbol] = {
                    "status": "stale" if previous else "unavailable",
                    "error": exc.code,
                }
        return results

    async def score(self, ticker):
        # Scoring reads only what ingestion just persisted; it never calls a provider.
        if not self.signals:
            return {"status": "disabled", "reason": "Scoring is not configured."}
        return await asyncio.to_thread(self.signals.build, ticker)

    async def alert(self, ticker):
        # Alerts compare the signal just written with the previous one.
        if not self.alerts:
            return {"status": "disabled"}
        created = await asyncio.to_thread(self.alerts.evaluate, ticker)
        return {"status": "evaluated", "created": created}

    def view(self, ticker, kind, limit=600):
        now = utcnow()
        payload = (
            self.store.bars(ticker, limit)
            if kind == "history"
            else self.store.snapshot(ticker, kind)
        )
        if not payload:
            return {
                "ticker": ticker,
                "status": "unavailable",
                "data": [] if kind == "history" else None,
                "reason": "No cached data. Run POST /api/refresh.",
                "provider_status": self.store.cache_status(ticker),
            }
        fetched_at = payload[-1]["fetched_at"] if kind == "history" else payload["fetched_at"]
        cache_expired = (now - parse_time(fetched_at)).total_seconds() > getattr(
            self.config.cache_seconds, kind
        )
        if kind == "quote":
            outdated = not self.quote_current(payload, now)
            reason = "Quote predates the expected session time." if outdated else None
        elif kind == "history":
            # Freshness uses the full stored history, even if the caller asks for one partial bar.
            outdated = not self.history_current(self.store.bars(ticker, 5))
            reason = "Latest completed market session is missing." if outdated else None
        else:
            outdated = cache_expired
            reason = "Fundamental cache expired." if outdated else payload["as_of_note"]
        return {
            "ticker": ticker,
            "status": "stale" if outdated else "cached",
            "cache_expired": cache_expired,
            "checked_at": iso(now),
            "reason": reason,
            "data": payload,
            "provider_status": self.store.cache_status(ticker),
        }

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
