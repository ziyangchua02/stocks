"""Composes the dashboard landing view from cached data only. No provider calls."""

from datetime import timedelta

from app.models import iso, utcnow
from app.services.scoring import DISCLAIMER

IMPACT_RANK = {"high": 0, "medium": 1, "low": 2}


class Overview:
    def __init__(self, store, config, market, ingestion, signals):
        self.store = store
        self.config = config
        self.market = market
        self.ingestion = ingestion
        self.signals = signals

    def indices(self, now):
        rows = []
        for index in self.config.market_indices:
            snapshot = self.store.snapshot(index.symbol, "quote")
            cache = self.store.cache(f"yfinance:quote:{index.symbol}")
            if not snapshot:
                rows.append(
                    {
                        "symbol": index.symbol,
                        "name": index.name,
                        "status": "unavailable",
                        "reason": (cache or {}).get("error") or "not_yet_refreshed",
                        "data": None,
                    }
                )
                continue
            outdated = not self.ingestion.quote_current(snapshot, now)
            rows.append(
                {
                    "symbol": index.symbol,
                    "name": index.name,
                    "status": "stale" if outdated else "cached",
                    "reason": "Quote predates the expected session time." if outdated else None,
                    "data": snapshot,
                }
            )
        return rows

    def tickers(self, now):
        rows = []
        for item in self.store.watchlist():
            ticker = item["ticker"]
            quote = self.store.snapshot(ticker, "quote")
            current = self.signals.view(ticker, now)
            payload = current["data"] or {}
            rows.append(
                {
                    "ticker": ticker,
                    "company_name": item["company_name"],
                    "quote": {
                        "status": (
                            "unavailable"
                            if not quote
                            else "cached"
                            if self.ingestion.quote_current(quote, now)
                            else "stale"
                        ),
                        "data": quote,
                    },
                    "score": payload.get("score"),
                    "label": payload.get("label"),
                    "score_status": current["status"],
                    "score_reason": payload.get("reason") or current.get("reason"),
                    "weight_coverage": payload.get("weight_coverage"),
                    "cautions": [flag["flag"] for flag in payload.get("cautions", [])],
                    "as_of_session": payload.get("inputs", {}).get("indicator_as_of_session"),
                    "news_analysis_id": payload.get("inputs", {}).get("news_analysis_id"),
                }
            )
        return rows

    def movers(self, rows):
        """Ranked by the cached session change. Watchlist only; not a market-wide scan."""
        moved = [
            row
            for row in rows
            if row["quote"]["data"] and row["quote"]["data"].get("change_percent") is not None
        ]
        moved.sort(key=lambda row: row["quote"]["data"]["change_percent"], reverse=True)
        summary = [
            {
                "ticker": row["ticker"],
                "change_percent": row["quote"]["data"]["change_percent"],
                "price": row["quote"]["data"]["price"],
                "currency": row["quote"]["data"].get("currency"),
                "source_as_of": row["quote"]["data"]["source_as_of"],
                "quote_status": row["quote"]["status"],
            }
            for row in moved
        ]
        # A ticker appears under one heading only: a small watchlist must not show
        # the same name as both a gainer and a loser.
        gainers = [row for row in summary if row["change_percent"] > 0][:3]
        losers = [row for row in summary if row["change_percent"] < 0][-3:]
        return {
            "gainers": gainers,
            "losers": list(reversed(losers)),
            "unchanged": [row["ticker"] for row in summary if row["change_percent"] == 0],
            "counted": len(summary),
            "missing_quotes": len(rows) - len(summary),
            "scope": "Watchlist tickers with a cached quote only; not a market-wide scan.",
        }

    def headlines(self, now, limit=8):
        """Recent analyzed articles, most consequential first, each with its source link."""
        tickers = [row["ticker"] for row in self.store.watchlist()]
        assessments = self.store.latest_assessments(tickers)
        since = iso(now - timedelta(hours=self.config.news_lookback_hours))
        articles = self.store.news(since, limit=200)["items"]
        rated = []
        for article in articles:
            assessment = assessments.get(article["id"])
            if assessment:
                rated.append({**article, "assessment": assessment})
        # Articles arrive newest first, and a stable sort by impact keeps that order
        # inside each impact level.
        rated.sort(key=lambda row: IMPACT_RANK.get(row["assessment"]["impact"], 3))
        return {
            "items": rated[:limit],
            "analyzed_count": len(rated),
            "article_count": len(articles),
            "note": "Ordered by the model's impact rating, then recency. Impact and "
            "sentiment are AI interpretations of the linked article only.",
        }

    def build(self, now=None):
        now = now or utcnow()
        rows = self.tickers(now)
        runs = self.store.runs(limit=1)
        last_run = runs[0] if runs else None
        return {
            "checked_at": iso(now),
            "market": self.market.state(now),
            "indices": self.indices(now),
            "tickers": rows,
            "movers": self.movers(rows),
            "headlines": self.headlines(now),
            "last_refresh": {
                "id": last_run["id"],
                "status": last_run["status"],
                "trigger": last_run["trigger"],
                "started_at": last_run["started_at"],
                "completed_at": last_run["completed_at"],
            }
            if last_run
            else None,
            "active_refresh": self.ingestion.active_run_id,
            "scoring": {
                "config_version": self.signals.scoring.version,
                "labels": self.signals.scoring.labels.model_dump(),
            },
            "disclaimer": DISCLAIMER,
        }
