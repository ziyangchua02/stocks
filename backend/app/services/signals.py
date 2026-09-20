"""Scores watchlist tickers from cached data and writes append-only signal records."""

import hashlib
import json

from app.models import iso, parse_time, utcnow
from app.services.scoring import DISCLAIMER, VERSION, evaluate


class Signals:
    def __init__(self, store, config, scoring, analysis, news_analysis, market):
        self.store = store
        self.config = config
        self.scoring = scoring
        self.analysis = analysis
        self.news_analysis = news_analysis
        self.market = market
        self.config_hash = scoring.fingerprint()

    def sources(self, ticker, now):
        indicators = self.analysis.view(ticker, now=now)
        news = self.news_analysis.view(ticker) if self.news_analysis else None
        return indicators, news

    def build(self, ticker, now=None):
        """Score one ticker. Identical inputs and weights reuse the existing record."""
        now = now or utcnow()
        indicators, news = self.sources(ticker, now)
        if not (indicators or {}).get("data"):
            return {
                "status": "unavailable",
                "reason": "No indicator snapshot to score. Run POST /api/refresh.",
            }
        today = now.astimezone(self.market.timezone).date()
        payload = evaluate(ticker, indicators, news, self.scoring, now, today)
        digest = self.fingerprint(payload)
        signal_id, created = self.store.save_signal(payload, digest, self.config_hash)
        return {
            "status": "recorded" if created else "unchanged",
            "signal_id": signal_id,
            "score": payload["score"],
            "label": payload["label"],
            "score_status": payload["status"],
            "weight_coverage": payload["weight_coverage"],
        }

    def fingerprint(self, payload):
        # Intraday quotes are deliberately excluded: signals move when the completed
        # session, the analyzed news, or the configuration changes, not every 15 minutes.
        material = {
            "ticker": payload["ticker"],
            "scoring_version": VERSION,
            "config_hash": self.config_hash,
            "indicator_snapshot_id": payload["inputs"]["indicator_snapshot_id"],
            "news_analysis_id": payload["inputs"]["news_analysis_id"],
            "indicator_status": payload["inputs"]["indicator_status"],
            "news_status": payload["inputs"]["news_status"],
            "reference_session": payload["inputs"]["indicator_as_of_session"],
        }
        return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()

    def view(self, ticker, now=None):
        """Current score for one ticker, recomputed from cached inputs. No writes."""
        now = now or utcnow()
        indicators, news = self.sources(ticker, now)
        stored = self.store.signals(ticker, limit=1)["items"]
        latest = stored[0] if stored else None
        if not (indicators or {}).get("data"):
            return {
                "ticker": ticker,
                "status": "unavailable",
                "reason": "No indicator snapshot to score. Run POST /api/refresh.",
                "data": None,
                "last_recorded_signal": latest,
                "disclaimer": DISCLAIMER,
            }
        today = now.astimezone(self.market.timezone).date()
        payload = evaluate(ticker, indicators, news, self.scoring, now, today)
        digest = self.fingerprint(payload)
        return {
            "ticker": ticker,
            "status": payload["status"],
            "checked_at": iso(now),
            "data": payload,
            "recorded": latest is not None and latest["input_hash"] == digest,
            "last_recorded_signal": {
                "id": latest["id"],
                "created_at": latest["created_at"],
                "score": latest["score"],
                "label": latest["label"],
                "matches_current_inputs": latest["input_hash"] == digest,
                "config_version": latest["config_version"],
            }
            if latest
            else None,
            "sources": {
                "indicators": f"/api/tickers/{ticker}/indicators",
                "news_analysis": f"/api/tickers/{ticker}/news-analysis",
                "quote": f"/api/tickers/{ticker}/quote",
            },
            "disclaimer": DISCLAIMER,
        }

    def ranked(self, now=None, limit=50):
        """Watchlist ranked by current score. Unscored tickers are listed, never guessed."""
        now = now or utcnow()
        rows = []
        for item in self.store.watchlist()[:limit]:
            current = self.view(item["ticker"], now)
            payload = current["data"] or {}
            rows.append(
                {
                    "ticker": item["ticker"],
                    "company_name": item["company_name"],
                    "score": payload.get("score"),
                    "label": payload.get("label"),
                    "status": current["status"],
                    "reason": payload.get("reason") or current.get("reason"),
                    "weight_coverage": payload.get("weight_coverage"),
                    "cautions": [flag["flag"] for flag in payload.get("cautions", [])],
                    "top_components": sorted(
                        (
                            {
                                "component": row["component"],
                                "score": row["score"],
                                "contribution": row.get("contribution"),
                            }
                            for row in payload.get("breakdown", [])
                            if row["score"] is not None
                        ),
                        key=lambda row: row["contribution"] or 0,
                        reverse=True,
                    )[:3],
                    "as_of_session": payload.get("inputs", {}).get("indicator_as_of_session"),
                    "last_close": payload.get("inputs", {}).get("last_close"),
                    "recorded_signal_id": (current.get("last_recorded_signal") or {}).get("id"),
                    "detail_url": f"/api/tickers/{item['ticker']}/score",
                }
            )
        scored = [row for row in rows if row["score"] is not None]
        unscored = [row for row in rows if row["score"] is None]
        scored.sort(key=lambda row: row["score"], reverse=True)
        return {
            "items": scored + unscored,
            "scored_count": len(scored),
            "unscored_count": len(unscored),
            "checked_at": iso(now),
            "config_version": self.scoring.version,
            "scoring_version": VERSION,
            "weights": dict(self.scoring.weights),
            "note": "Ranking orders the watchlist by the current weighted score only. "
            "Tickers without enough data are listed last with their reason.",
            "disclaimer": DISCLAIMER,
        }

    def config_view(self):
        last = self.store.signals(limit=1)["items"]
        changed = bool(last) and last[0]["config_hash"] != self.config_hash
        return {
            "scoring_version": VERSION,
            "config_version": self.scoring.version,
            "config_hash": self.config_hash,
            "config": self.scoring.model_dump(mode="json"),
            "file": "config/scoring.yaml",
            "note": "Edit the file and restart to change weights. Past signals keep the "
            "weights they were scored with.",
            "differs_from_latest_signal": changed,
            "labels_in_use": [
                "Strong setup",
                "Watch",
                "Neutral",
                "Caution",
            ],
            "disclaimer": DISCLAIMER,
        }

    def history(self, ticker=None, limit=100, offset=0):
        result = self.store.signals(ticker, limit, offset)
        now = utcnow()
        for item in result["items"]:
            item["age_hours"] = round(
                (now - parse_time(item["created_at"])).total_seconds() / 3600, 2
            )
        result["note"] = (
            "Append-only log of every signal generated, with the 1-week and 1-month "
            "outcome measured from stored closes once each horizon has elapsed."
        )
        result["disclaimer"] = DISCLAIMER
        return result
