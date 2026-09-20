import calendar
import re
from datetime import UTC, datetime, timedelta

import feedparser
from pydantic import ValidationError

from app.models import Article, utcnow
from app.providers.common import ProviderError, plain_text


class RSS:
    def __init__(self, http, config):
        self.http = http
        self.config = config

    async def fetch(self, feed):
        response = await self.http.get(feed.url)
        parsed = feedparser.parse(response.content)
        if not parsed.version:
            raise ProviderError("invalid_rss_feed", retry_seconds=900)
        now = utcnow()
        since = now - timedelta(hours=self.config.news_lookback_hours)
        articles, rejected = [], 0
        for entry in parsed.entries:
            try:
                stamp = entry.get("published_parsed")
                if stamp is None:
                    rejected += 1
                    continue  # Never invent a publication time from the retrieval time.
                published = datetime.fromtimestamp(calendar.timegm(stamp), UTC)
                if not since <= published <= now:
                    continue
                article = Article(
                    title=plain_text(entry.get("title"), 500),
                    url=entry.get("link", ""),
                    publisher=feed.name,
                    summary=plain_text(entry.get("summary", "")),
                    published_at=published,
                    fetched_at=now,
                    provider="rss:" + feed.name,
                )
                articles.append(article.model_dump(mode="json"))
            except (TypeError, ValueError, OverflowError, OSError, ValidationError):
                rejected += 1
        return {
            "articles": articles,
            "rejected_items": rejected,
            "parse_warning": bool(parsed.bozo),
        }

    @staticmethod
    def relevant(article, ticker, company_name):
        text = article["title"] + " " + article["summary"]
        # Conservative rules: company name, explicit $ticker/exchange tag, or an uppercase
        # ticker of at least 3 characters. Single-letter English words must not match symbols.
        if company_name and re.search(
            r"(?<!\w)" + re.escape(company_name) + r"(?!\w)", text, flags=re.IGNORECASE
        ):
            return True
        if re.search(r"(?:\$|NASDAQ:\s*|NYSE:\s*)" + re.escape(ticker) + r"(?!\w)", text):
            return True
        return len(ticker) >= 3 and bool(
            re.search(r"(?<!\w)" + re.escape(ticker) + r"(?!\w)", text)
        )
