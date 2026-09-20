"""Daily brief: locally computed changes, described by the model with citations.

Every figure in a brief is computed here from stored records. The model supplies
prose and, where articles support it, an explanation. It is never asked for a
number, and its output is rejected if it cites an article or ticker that was not
supplied.
"""

import asyncio
import hashlib
import json
from datetime import timedelta
from importlib.resources import files

from pydantic import ValidationError

from app.models import iso, parse_time, utcnow
from app.providers.common import ProviderError, plain_text
from app.services.brief_schema import BriefResult

PROMPT_VERSION = "brief-v1"
INSTRUCTION = files("app.prompts").joinpath("brief_v1.txt").read_text()
SCHEMA = BriefResult.model_json_schema()
DISCLAIMER = (
    "Not financial advice. The figures are computed from your cached data; the wording "
    "around them is an AI summary that can be wrong or incomplete."
)


class Brief:
    def __init__(self, store, config, alerts_config, provider, signals):
        self.store = store
        self.config = config
        self.options = alerts_config.brief
        self.limits = config.news_analysis
        self.provider = provider
        self.signals = signals
        self.lock = asyncio.Lock()

    def facts(self, now=None):
        """Changes over the lookback window, computed from signals, bars and alerts."""
        now = now or utcnow()
        since = now - timedelta(hours=self.options.lookback_hours)
        rows, articles, seen = [], [], set()
        for item in self.store.watchlist():
            ticker = item["ticker"]
            history = self.store.signals(ticker, limit=40)["items"]
            current = history[0] if history else None
            # Prefer the last signal from before the window. With no earlier record,
            # fall back to the oldest one inside it and say so, rather than
            # reporting no change at all.
            earlier = [row for row in history[1:] if parse_time(row["created_at"]) < since]
            previous = earlier[0] if earlier else (history[-1] if len(history) > 1 else None)
            basis = (
                "last recorded signal from before the window"
                if earlier
                else "earliest signal inside the window; no earlier record exists"
                if previous
                else "no earlier signal exists, so no change can be computed"
            )
            bars = self.store.bars(ticker, 3)
            close = bars[-1]["close"] if bars else None
            prior_close = bars[-2]["close"] if len(bars) > 1 else None
            alerts = [
                row
                for row in self.store.alerts(limit=200)["items"]
                if row["ticker"] == ticker and parse_time(row["created_at"]) >= since
            ]
            analysis = self.store.news_analysis(ticker)
            fresh_analysis = bool(analysis and parse_time(analysis["generated_at"]) >= since)
            for assessment in (analysis or {}).get("payload", {}).get("article_assessments", []):
                source = (assessment.get("sources") or [{}])[0]
                published = source.get("published_at")
                if not published or parse_time(published) < since:
                    continue
                if source.get("id") in seen:
                    continue
                seen.add(source.get("id"))
                articles.append(
                    {
                        "id": source["id"],
                        "ticker": ticker,
                        "title": plain_text(source.get("title", ""), 300),
                        "publisher": source.get("publisher"),
                        "published_at": published,
                        "url": source.get("url"),
                        "impact": assessment["impact"],
                        "sentiment": assessment["sentiment"],
                        "model_rationale": plain_text(assessment["rationale"], 400),
                    }
                )
            rows.append(
                {
                    "ticker": ticker,
                    "company_name": item["company_name"],
                    "score": current["score"] if current else None,
                    "previous_score": previous["score"] if previous else None,
                    "score_change": (
                        current["score"] - previous["score"]
                        if current
                        and previous
                        and None not in (current["score"], previous["score"])
                        else None
                    ),
                    "label": current["label"] if current else None,
                    "previous_label": previous["label"] if previous else None,
                    "weight_coverage": (current["payload"]["weight_coverage"] if current else None),
                    "cautions": (
                        [flag["flag"] for flag in current["payload"].get("cautions", [])]
                        if current
                        else []
                    ),
                    "last_close": close,
                    "previous_close": prior_close,
                    "close_change_percent": (
                        100 * (close / prior_close - 1) if close and prior_close else None
                    ),
                    "reference_session": current["reference_session"] if current else None,
                    "news_analysis_refreshed_in_period": fresh_analysis,
                    "alerts": [
                        {
                            "rule": row["rule"],
                            "title": row["title"],
                            "created_at": row["created_at"],
                        }
                        for row in alerts
                    ],
                    "comparison_basis": basis,
                }
            )
        articles.sort(key=lambda row: row["published_at"], reverse=True)
        articles = articles[: self.options.max_articles]
        return {
            "period_start": iso(since),
            "period_end": iso(now),
            "lookback_hours": self.options.lookback_hours,
            "tickers": rows,
            "articles": articles,
            "note": "All figures are computed locally from stored records.",
        }

    def digest(self, facts):
        material = {
            "tickers": facts["tickers"],
            "articles": facts["articles"],
            "model": self.limits.model,
            "prompt_version": PROMPT_VERSION,
            "instruction": INSTRUCTION,
            "schema": SCHEMA,
            "max_output_tokens": self.options.max_output_tokens,
        }
        return hashlib.sha256(
            json.dumps(material, sort_keys=True, default=str).encode()
        ).hexdigest()

    def gate(self):
        if not self.options.enabled:
            return "disabled"
        if not self.provider.configured:
            return "missing_gemini_key"
        return None

    def cooldown(self):
        row = self.store.cache("provider-cooldown:gemini")
        if row and row["error"] and row["retry_at"] and parse_time(row["retry_at"]) > utcnow():
            return {"error": row["error"], "retry_at": row["retry_at"]}
        return None

    async def build(self, now=None):
        """Generate a brief, or reuse the stored one when nothing has changed."""
        async with self.lock:
            if reason := self.gate():
                return {
                    "status": "disabled" if reason == "disabled" else "unavailable",
                    "reason": reason,
                }
            facts = self.facts(now)
            if not facts["tickers"]:
                return {"status": "insufficient_data", "reason": "The watchlist is empty."}
            if (
                all(
                    row["score_change"] is None
                    and row["close_change_percent"] is None
                    and not row["alerts"]
                    for row in facts["tickers"]
                )
                and not facts["articles"]
            ):
                return {
                    "status": "insufficient_data",
                    "reason": "Nothing changed in the window and no articles were analyzed. "
                    "Refresh first; a brief is not written about an empty period.",
                }
            digest = self.digest(facts)
            existing = self.store.brief(input_hash=digest)
            if existing:
                return {"status": "cached", "brief_id": existing["id"]}
            if cooldown := self.cooldown():
                return {"status": "unavailable", **cooldown}
            prompt = json.dumps(
                {
                    "facts": {k: v for k, v in facts.items() if k != "articles"},
                    "articles": [
                        {k: v for k, v in article.items() if k != "url"}
                        for article in facts["articles"]
                    ],
                },
                ensure_ascii=False,
                default=str,
            )
            attempt_id = self.store.begin_llm_attempt(
                "__brief__", digest, self.limits.model, self.limits.max_calls_per_day
            )
            if attempt_id is None:
                return {"status": "unavailable", "error": "daily_call_budget"}
            usage = None
            try:
                response = await self.provider.generate(INSTRUCTION, prompt, SCHEMA)
                usage = response.get("usage", {})
                if response.get("error"):
                    raise ProviderError(response["error"], 900)
                output = BriefResult.model_validate_json(response["text"])
                payload = output.resolve(facts, facts["articles"]) | {
                    "usage": usage,
                    "disclaimer": DISCLAIMER,
                }
                brief_id = self.store.save_brief(
                    digest, self.limits.model, PROMPT_VERSION, facts, payload
                )
            except asyncio.CancelledError:
                self.store.finish_llm_attempt(attempt_id, "interrupted", usage=usage)
                raise
            except (ValidationError, ValueError, KeyError, TypeError):
                self.store.finish_llm_attempt(attempt_id, "failed", "invalid_brief_output", usage)
                return {"status": "unavailable", "error": "invalid_brief_output"}
            except ProviderError as exc:
                self.store.finish_llm_attempt(attempt_id, "failed", exc.code, usage)
                if exc.code in {"rate_limited", "unauthorized_or_plan_restricted"}:
                    self.store.cache_failure(
                        "provider-cooldown:gemini", exc.code, exc.retry_seconds
                    )
                return {"status": "unavailable", "error": exc.code}
            except Exception:
                self.store.finish_llm_attempt(attempt_id, "failed", "brief_failed", usage)
                return {"status": "unavailable", "error": "brief_failed"}
            self.store.finish_llm_attempt(attempt_id, "completed", usage=usage)
            return {"status": "generated", "brief_id": brief_id}

    def view(self, now=None):
        """The stored brief, plus whether it still matches the current facts."""
        now = now or utcnow()
        facts = self.facts(now)
        digest = self.digest(facts)
        current = self.store.brief(input_hash=digest)
        latest = current or self.store.brief()
        reason = self.gate()
        if current:
            status = "cached"
        elif latest:
            status, reason = "stale", "inputs_changed_since_this_brief_was_written"
        else:
            status = "disabled" if reason == "disabled" else "unavailable"
            reason = reason or "no_brief_generated"
        return {
            "status": status,
            "reason": reason,
            "checked_at": iso(now),
            "data": current,
            "previous_brief": latest if not current else None,
            "current_facts": facts,
            "changed_tickers": [
                row["ticker"]
                for row in facts["tickers"]
                if row["score_change"] or row["close_change_percent"] or row["alerts"]
            ],
            "last_error": self.cooldown(),
            "disclaimer": DISCLAIMER,
        }
