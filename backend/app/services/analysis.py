import hashlib
import json
from datetime import date

from app.models import iso, parse_time, utcnow
from app.services.fundamentals import normalize
from app.services.technicals import VERSION, calculate


class Analysis:
    def __init__(self, store, market, config):
        self.store, self.market, self.config = store, market, config

    def build(self, ticker, now=None):
        now = now or utcnow()
        bars = self.store.bars(ticker, 2000)
        fundamental = self.store.snapshot(ticker, "fundamentals")
        if not bars and not fundamental:
            return {"status": "unavailable", "reason": "No cached source data."}
        # Use a coherent provider batch so pre-split rows outside the current download
        # cannot be spliced into a newly adjusted history.
        if bars:
            cache = self.store.cache(f"{bars[-1]['source']}:history:{ticker}")
            if cache and cache["payload"]:
                bars = cache["payload"]
        inputs = {
            "bars": bars,
            "fundamentals": fundamental,
            "version": VERSION,
            "market_calendar": self.config.market_calendar,
            "market_timezone": self.config.market_timezone,
            "local_date": now.astimezone(self.market.timezone).date().isoformat(),
            "last_completed_session": self.market.state(now)["last_completed_session"],
        }
        fingerprint = hashlib.sha256(
            json.dumps(inputs, sort_keys=True, allow_nan=False).encode()
        ).hexdigest()
        existing = self.store.indicators(ticker)
        if existing and existing["input_hash"] == fingerprint:
            return {"status": "cached", "snapshot_id": existing["snapshot_id"]}
        technicals = calculate(bars, self.market, now)
        series = technicals.pop("series")
        fundamentals = normalize(fundamental, now, self.config.market_timezone)
        payload = {
            "ticker": ticker,
            "calculation_version": VERSION,
            "computed_at": iso(now),
            "technicals": technicals,
            "fundamentals": fundamentals,
            "input_references": {
                "bar_count": len(bars),
                "history_source": bars[-1]["source"] if bars else None,
                "history_fetched_at": bars[-1]["fetched_at"] if bars else None,
                "fundamentals_source": fundamental.get("source") if fundamental else None,
                "fundamentals_fetched_at": fundamental.get("fetched_at") if fundamental else None,
            },
            "disclaimer": "Not financial advice. Indicators describe observed data; "
            "no score or recommendation.",
        }
        snapshot_id = self.store.save_indicators(ticker, fingerprint, payload, series)
        return {
            "status": "computed",
            "snapshot_id": snapshot_id,
            "technical_coverage": technicals["status"],
            "fundamental_coverage": fundamentals["status"],
        }

    def view(self, ticker, include_series=False, limit=600, now=None):
        now = now or utcnow()
        result = self.store.indicators(ticker, include_series, limit)
        if result is None:
            return {
                "ticker": ticker,
                "status": "unavailable",
                "data": None,
                "reason": "No indicator snapshot. Run POST /api/refresh.",
                "provider_status": self.store.cache_status(ticker),
            }
        technical = result["technicals"]
        expected = self.market.state(now)["last_completed_session"]
        technical["expected_latest_session"] = expected
        technical["freshness"] = (
            "unavailable"
            if not technical["as_of_session"]
            else "stale"
            if technical["as_of_session"] < expected
            else "current"
        )
        for field in technical["metrics"].values():
            field["freshness"] = (
                technical["freshness"] if field["value"] is not None else "unavailable"
            )
        fundamental = result["fundamentals"]
        fetched_at = fundamental.get("source_fetched_at")
        fundamental["freshness"] = (
            "unavailable"
            if not fetched_at
            else "stale"
            if (now - parse_time(fetched_at)).total_seconds()
            > self.config.cache_seconds.fundamentals
            else "current_cache_observation_time_unknown"
        )
        for field in fundamental["fields"].values():
            field["freshness"] = (
                fundamental["freshness"]
                if field["status"] in {"available", "date_range"}
                else "unavailable"
            )
        upcoming = fundamental["fields"]["next_earnings_date"]
        end = upcoming.get("window_end")
        if end and date.fromisoformat(end) < now.astimezone(self.market.timezone).date():
            upcoming.update(
                value=None,
                status="unavailable",
                freshness="expired_event",
                reason="The cached earnings date has passed; refresh for an upcoming date.",
            )
            fundamental["status"] = "partial"
        sections = [technical, fundamental]
        status = (
            "stale"
            if any(s["freshness"] == "stale" for s in sections)
            else "available"
            if all(s["status"] == "available" for s in sections)
            else "unavailable"
            if all(s["status"] == "unavailable" for s in sections)
            else "partial"
        )
        return {
            "ticker": ticker,
            "status": status,
            "checked_at": iso(now),
            "data": result,
            "provider_status": self.store.cache_status(ticker),
        }
