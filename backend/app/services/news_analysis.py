import asyncio
import hashlib
import json
from datetime import timedelta
from importlib.resources import files

from pydantic import ValidationError

from app.models import iso, parse_time, utcnow
from app.providers.common import ProviderError, plain_text
from app.providers.gemini import generation_schema
from app.providers.rss import RSS
from app.services.news_schema import NewsResult

PROMPT_VERSION = "news-v2"
INSTRUCTION = files("app.prompts").joinpath("news_v2.txt").read_text()
SCHEMA = NewsResult.model_json_schema()
DISCLAIMER = "Not financial advice. AI interpretations of headlines and excerpts may be wrong."


class NewsAnalysis:
    def __init__(self, store, config, provider, feeds):
        self.store, self.config, self.provider, self.feeds = store, config, provider, feeds
        self.options = config.news_analysis
        self.lock = asyncio.Lock()

    def inputs(self, ticker):
        now = utcnow()
        company = next(
            (row["company_name"] for row in self.store.watchlist() if row["ticker"] == ticker), ""
        )
        candidates = self.store.news_candidates(
            iso(now - timedelta(hours=self.config.news_lookback_hours)),
            ticker,
        )
        # Company-news endpoints can include unrelated syndicated articles. Do not
        # infer that an unnamed company in an excerpt must be the requested ticker.
        relevant = [row for row in candidates if RSS.relevant(row, ticker, company)]
        articles = []
        for article in relevant[: self.options.max_articles]:
            articles.append(
                {
                    "id": article["id"],
                    "title": plain_text(article["title"], 500),
                    "excerpt": plain_text(article["summary"], self.options.max_excerpt_chars),
                    "url": article["url"],
                    "publisher": article["publisher"],
                    "published_at": article["published_at"],
                    "fetched_at": article["fetched_at"],
                    "content_scope": article["content_scope"],
                    "excerpt_truncated": len(plain_text(article["summary"]))
                    > self.options.max_excerpt_chars,
                }
            )
        inputs = {
            "ticker": ticker,
            "company_name": company,
            "selected_at": iso(now),
            "lookback_hours": self.config.news_lookback_hours,
            "selection": "Most recent deduplicated articles explicitly mentioning the ticker "
            "or company in the headline or excerpt, publication time descending.",
            "total_count": len(candidates),
            "excluded_without_company_mention": len(candidates) - len(relevant),
            "eligible_count": len(relevant),
            "selected_count": len(articles),
            "omitted_count": len(relevant) - len(articles),
            "articles": articles,
        }
        # Retrieval time and omitted counts cannot change the meaning of identical model inputs.
        material = {
            "ticker": ticker,
            "company_name": company,
            "articles": [{k: v for k, v in item.items() if k != "fetched_at"} for item in articles],
            "model": self.options.model,
            "prompt_version": PROMPT_VERSION,
            "instruction": INSTRUCTION,
            "schema": SCHEMA,
            "generation_schema": generation_schema(SCHEMA),
            "max_output_tokens": self.options.max_output_tokens,
        }
        digest = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
        return inputs, digest

    def provider_status(self, ticker):
        expected = [f"finnhub:news:{ticker}", *("rss:" + feed.url for feed in self.feeds)]
        rows = {row["cache_key"]: row for row in self.store.cache_status(ticker)}
        now = utcnow()
        result = []
        for key in expected:
            row = rows.get(
                key,
                {
                    "cache_key": key,
                    "fetched_at": None,
                    "expires_at": None,
                    "error": "not_yet_refreshed",
                    "retry_at": None,
                },
            )
            result.append(
                row | {"stale": not row["expires_at"] or parse_time(row["expires_at"]) <= now}
            )
        return result

    def gate(self):
        if not self.options.enabled:
            return "disabled"
        if not self.provider.configured:
            return "missing_gemini_key"
        return None

    def cooldown(self, key):
        row = self.store.cache(key)
        if row and row["error"] and row["retry_at"] and parse_time(row["retry_at"]) > utcnow():
            return {"error": row["error"], "retry_at": row["retry_at"]}
        return None

    async def build(self, ticker):
        # Both manual analysis and scheduled ingestion share this lock and persistent budgets.
        async with self.lock:
            if reason := self.gate():
                return {
                    "status": "disabled" if reason == "disabled" else "unavailable",
                    "reason": reason,
                }
            inputs, digest = self.inputs(ticker)
            if not inputs["articles"]:
                return {"status": "insufficient_news", "reason": self.empty_reason(inputs)}
            existing = self.store.news_analysis(ticker, input_hash=digest)
            if existing:
                return {"status": "cached", "analysis_id": existing["id"]}
            key = f"gemini-analysis:{ticker}:{digest}"
            cooldown = self.cooldown("provider-cooldown:gemini") or self.cooldown(key)
            if cooldown:
                return {"status": "unavailable", **cooldown}
            # Only public news material and ticker context are sent; no portfolio or secrets.
            prompt = json.dumps(
                {
                    "ticker": ticker,
                    "company_name": inputs["company_name"],
                    "articles": [
                        {k: v for k, v in row.items() if k not in {"url", "fetched_at"}}
                        for row in inputs["articles"]
                    ],
                },
                ensure_ascii=False,
            )
            for attempt in range(self.options.retry_attempts):
                recent = self.store.llm_attempts(limit=1)
                if recent:
                    elapsed = (utcnow() - parse_time(recent[0]["started_at"])).total_seconds()
                    await asyncio.sleep(max(0, self.options.min_interval_seconds - elapsed))
                attempt_id = self.store.begin_llm_attempt(
                    ticker, digest, self.options.model, self.options.max_calls_per_day
                )
                if attempt_id is None:
                    tomorrow = (utcnow() + timedelta(days=1)).replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )
                    self.store.cache_failure(
                        "provider-cooldown:gemini",
                        "daily_call_budget",
                        (tomorrow - utcnow()).total_seconds(),
                    )
                    return {
                        "status": "unavailable",
                        "error": "daily_call_budget",
                        "retry_at": iso(tomorrow),
                    }
                usage = None
                try:
                    response = await self.provider.generate(INSTRUCTION, prompt, SCHEMA)
                    usage = response.get("usage", {})
                    if response.get("error"):
                        raise ProviderError(response["error"], 900)
                    output = NewsResult.model_validate_json(response["text"])
                    resolved = output.resolve(inputs["articles"])
                    payload = resolved | {
                        "usage": usage,
                        "disclaimer": DISCLAIMER,
                        "interpretation": "AI interpretation, not a price forecast",
                    }
                    analysis_id = self.store.save_news_analysis(
                        ticker, digest, self.options.model, PROMPT_VERSION, inputs, payload
                    )
                except asyncio.CancelledError:
                    self.store.finish_llm_attempt(attempt_id, "interrupted", usage=usage)
                    raise
                except (ValidationError, ValueError, KeyError, TypeError):
                    error = ProviderError("invalid_analysis_or_citations", 900)
                except ProviderError as exc:
                    error = exc
                except Exception:
                    error = ProviderError("analysis_failed", 900)
                else:
                    self.store.finish_llm_attempt(attempt_id, "completed", usage=usage)
                    return {
                        "status": "generated",
                        "analysis_id": analysis_id,
                        "selected_count": inputs["selected_count"],
                        "omitted_count": inputs["omitted_count"],
                    }
                self.store.finish_llm_attempt(attempt_id, "failed", error.code, usage)
                # Malformed/safety responses are not regenerated automatically.
                if (
                    error.code in {"network_or_timeout", "provider_server_error"}
                    and attempt + 1 < self.options.retry_attempts
                ):
                    await asyncio.sleep(2**attempt)
                    continue
                self.store.cache_failure(key, error.code, error.retry_seconds)
                if error.code in {
                    "rate_limited",
                    "unauthorized_or_plan_restricted",
                    "model_unavailable",
                    "http_400",
                }:
                    self.store.cache_failure(
                        "provider-cooldown:gemini", error.code, error.retry_seconds
                    )
                return {
                    "status": "unavailable",
                    "error": error.code,
                    "retry_at": self.store.cache(key)["retry_at"],
                }

    def view(self, ticker):
        inputs, digest = self.inputs(ticker)
        data = self.store.news_analysis(ticker, input_hash=digest)
        latest = data or self.store.news_analysis(ticker)
        sources = self.provider_status(ticker)
        warnings = []
        if inputs["excluded_without_company_mention"]:
            warnings.append(
                "Articles without an explicit ticker/company mention were excluded; "
                "this conservative rule may also omit relevant context."
            )
        if any(row["error"] or row["stale"] for row in sources):
            warnings.append(
                "News retrieval is missing, stale, or incomplete; inspect provider_status."
            )
        if inputs["omitted_count"]:
            warnings.append("Only the most recent articles fit the configured analysis limit.")
        if any(row["excerpt_truncated"] for row in inputs["articles"]):
            warnings.append("Some excerpts were truncated to the configured input limit.")
        error = self.cooldown("provider-cooldown:gemini") or self.cooldown(
            f"gemini-analysis:{ticker}:{digest}"
        )
        reason = self.gate()
        if reason:
            status = "disabled" if reason == "disabled" else "unavailable"
        elif not inputs["articles"]:
            status, reason = "insufficient_news", self.empty_reason(inputs)
        elif data:
            status = "partial" if warnings else "cached"
        elif latest:
            status, reason = "stale", "selected_news_or_analysis_configuration_changed"
        else:
            status, reason = "unavailable", "analysis_not_generated"
        return {
            "ticker": ticker,
            "status": status,
            "reason": reason,
            "checked_at": iso(),
            "data": data if not reason else None,
            "previous_analysis": latest if not data or reason else None,
            "coverage": {k: v for k, v in inputs.items() if k != "articles"},
            "warnings": warnings,
            "provider_status": sources,
            "last_error": error,
            "disclaimer": DISCLAIMER,
        }

    @staticmethod
    def empty_reason(inputs):
        return "no_company_mentions_in_window" if inputs["total_count"] else "no_articles_in_window"
