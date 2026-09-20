"""In-app alerts derived from data already stored. No provider or model calls.

An alert is an observation that something crossed a threshold the user configured,
never a suggestion to act. Each one carries the numbers and the threshold that
produced it, plus a link to the record it came from.
"""

from datetime import timedelta

from app.models import iso, number, parse_time, utcnow


def fmt(value, digits=1):
    """Format a figure for alert text; `number` only coerces, it does not render."""
    value = number(value)
    return "unknown" if value is None else f"{value:.{digits}f}"


DISCLAIMER = (
    "Not financial advice. An alert reports that a configured threshold was crossed "
    "in cached data; it is not a recommendation to buy or sell."
)


class Alerts:
    def __init__(self, store, config, alerts_config):
        self.store = store
        self.config = config
        self.rules = alerts_config

    def evaluate(self, ticker):
        """Create any new alerts for one ticker. Repeat refreshes do not duplicate."""
        if not self.rules.enabled:
            return []
        created = []
        for candidate in (
            *self.score_alerts(ticker),
            *self.price_alerts(ticker),
            *self.news_alerts(ticker),
        ):
            alert_id, is_new = self.store.save_alert(candidate)
            if is_new:
                created.append({"id": alert_id, "rule": candidate["rule"]})
        return created

    def score_alerts(self, ticker):
        history = self.store.signals(ticker, limit=2)["items"]
        if not history:
            return []
        current = history[0]
        previous = history[1] if len(history) > 1 else None
        if current["score"] is None:
            return []
        alerts = []
        rule = self.rules.rule("score_threshold")
        if rule:
            for direction, attribute in (("above", "crosses_above"), ("below", "crosses_below")):
                threshold = number(getattr(rule, attribute, None))
                if threshold is None:
                    continue
                now_side = current["score"] >= threshold
                # Without an earlier signal a crossing cannot be established, so the
                # first recorded score never fires a crossing alert.
                if previous is None or previous["score"] is None:
                    continue
                before_side = previous["score"] >= threshold
                crossed = now_side != before_side and now_side == (direction == "above")
                if crossed:
                    alerts.append(
                        self.build(
                            ticker,
                            "score_threshold",
                            "attention",
                            f"{ticker} score crossed {direction} {fmt(threshold, 0)}",
                            f"Score moved from {fmt(previous['score'])} to "
                            f"{fmt(current['score'])}, crossing the configured "
                            f"{direction} threshold of {fmt(threshold, 0)}.",
                            {
                                "signal_id": current["id"],
                                "previous_signal_id": previous["id"],
                                "score": current["score"],
                                "previous_score": previous["score"],
                                "threshold": threshold,
                                "direction": direction,
                                "link": f"/api/signals/{current['id']}",
                            },
                            f"score_threshold:{ticker}:{current['id']}:{direction}",
                        )
                    )
        rule = self.rules.rule("score_change")
        if rule and previous and previous["score"] is not None:
            minimum = number(getattr(rule, "minimum_change", None)) or 0
            change = current["score"] - previous["score"]
            if abs(change) >= minimum:
                alerts.append(
                    self.build(
                        ticker,
                        "score_change",
                        "info",
                        f"{ticker} score moved {fmt(change)} points",
                        f"Score changed from {fmt(previous['score'])} to "
                        f"{fmt(current['score'])}, at or beyond the configured "
                        f"{fmt(minimum)}-point threshold. A score change can come "
                        f"from new inputs as easily as from a change in the company.",
                        {
                            "signal_id": current["id"],
                            "previous_signal_id": previous["id"],
                            "change": change,
                            "threshold": minimum,
                            "link": f"/api/signals/{current['id']}",
                        },
                        f"score_change:{ticker}:{current['id']}",
                    )
                )
        if self.rules.rule("label_change") and previous and previous["label"] != current["label"]:
            alerts.append(
                self.build(
                    ticker,
                    "label_change",
                    "attention" if current["label"] == "Caution" else "info",
                    f"{ticker} label changed to {current['label']}",
                    f"The label moved from {previous['label']} to {current['label']} "
                    f"under weights {current['config_version']}.",
                    {
                        "signal_id": current["id"],
                        "previous_label": previous["label"],
                        "label": current["label"],
                        "link": f"/api/signals/{current['id']}",
                    },
                    f"label_change:{ticker}:{current['id']}",
                )
            )
        return alerts

    def price_alerts(self, ticker):
        rule = self.rules.rule("price_move")
        quote = self.store.snapshot(ticker, "quote")
        if not rule or not quote:
            return []
        threshold = number(getattr(rule, "percent", None)) or 0
        move = number(quote.get("change_percent"))
        if move is None or abs(move) < threshold:
            return []
        direction = "up" if move > 0 else "down"
        return [
            self.build(
                ticker,
                "price_move",
                "attention",
                f"{ticker} moved {fmt(move, 2)}% {direction}",
                f"The cached quote is {fmt(move, 2)}% against its previous close, "
                f"at or beyond the configured {fmt(threshold, 2)}% threshold. "
                f"Observed at {quote['source_as_of']}.",
                {
                    "change_percent": move,
                    "threshold": threshold,
                    "price": quote["price"],
                    "previous_close": quote.get("previous_close"),
                    "source": quote["source"],
                    "source_url": quote["source_url"],
                    "source_as_of": quote["source_as_of"],
                    "link": f"/api/tickers/{ticker}/quote",
                },
                f"price_move:{ticker}:{quote['source_as_of']}",
            )
        ]

    def news_alerts(self, ticker):
        rule = self.rules.rule("high_impact_news")
        if not rule:
            return []
        impacts = set(getattr(rule, "impacts", ["high"]))
        floor = number(getattr(rule, "minimum_abs_sentiment", None)) or 0
        analysis = self.store.news_analysis(ticker)
        if not analysis:
            return []
        since = utcnow() - timedelta(hours=self.config.news_lookback_hours)
        alerts = []
        for item in analysis["payload"].get("article_assessments", []):
            if item["impact"] not in impacts or abs(item["sentiment"]) < floor:
                continue
            source = (item.get("sources") or [{}])[0]
            published = source.get("published_at")
            if not published or parse_time(published) < since:
                continue
            direction = "positive" if item["sentiment"] > 0 else "negative"
            alerts.append(
                self.build(
                    ticker,
                    "high_impact_news",
                    "attention",
                    f"{item['impact'].capitalize()}-impact {direction} news for {ticker}",
                    f"{source.get('title', 'An article')} — the model rated this "
                    f"{item['impact']} impact at sentiment {fmt(item['sentiment'], 2)}. "
                    f"{item['rationale']} Read the article before acting on it.",
                    {
                        "article_id": item["article_id"],
                        "analysis_id": analysis["id"],
                        "model": analysis["model"],
                        "impact": item["impact"],
                        "sentiment": item["sentiment"],
                        "url": source.get("url"),
                        "publisher": source.get("publisher"),
                        "published_at": published,
                        "link": f"/api/tickers/{ticker}/news-analysis",
                    },
                    f"high_impact_news:{ticker}:{item['article_id']}",
                )
            )
        return alerts

    @staticmethod
    def build(ticker, rule, severity, title, detail, evidence, dedupe_key):
        return {
            "ticker": ticker,
            "rule": rule,
            "severity": severity,
            "created_at": iso(),
            "dedupe_key": dedupe_key,
            "title": title,
            "detail": detail,
            "evidence": evidence,
        }

    def view(self, unacknowledged_only=False, limit=100):
        result = self.store.alerts(unacknowledged_only, limit)
        result["rules_enabled"] = sorted(name for name in self.rules.rules if self.rules.rule(name))
        result["delivery"] = "in-app only; Telegram is not installed"
        result["disclaimer"] = DISCLAIMER
        return result
