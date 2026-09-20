"""Deterministic composite scoring. No provider or LLM calls; missing inputs are never imputed.

Every sub-score records the input value, the curve or condition applied, the source
of the value, and a reason when it is unavailable. Weights come from
`config/scoring.yaml` and are renormalized over the components that actually had data.
"""

from datetime import date

from app.models import iso, number, parse_time, utcnow

VERSION = "composite-v1"
LABELS = ("Strong setup", "Watch", "Neutral", "Caution")
DISCLAIMER = (
    "Not financial advice. A score is a weighted summary of the observed inputs below, "
    "not a prediction, recommendation, or measure of expected return."
)


def interpolate(points, value):
    """Piecewise-linear curve, clamped outside the configured range."""
    if value <= points[0][0]:
        return float(points[0][1])
    if value >= points[-1][0]:
        return float(points[-1][1])
    for (x0, y0), (x1, y1) in zip(points, points[1:], strict=False):
        if x0 <= value <= x1:
            return float(y0 + (y1 - y0) * (value - x0) / (x1 - x0))
    return float(points[-1][1])  # Unreachable for ascending curves.


class Reading:
    """One measured input plus the sub-score it produced, or why it produced none."""

    def __init__(self, name, value, unit, source, sub_score=None, reason=None, detail=None):
        self.name, self.value, self.unit, self.source = name, value, unit, source
        self.sub_score, self.reason, self.detail = sub_score, reason, detail

    def json(self):
        return {
            "input": self.name,
            "value": self.value,
            "unit": self.unit,
            "sub_score": round(self.sub_score, 2) if self.sub_score is not None else None,
            "status": "scored" if self.sub_score is not None else "unavailable",
            "reason": self.reason,
            "source": self.source,
            **(self.detail or {}),
        }


def metric(technicals, key):
    field = (technicals.get("metrics") or {}).get(key) or {}
    return number(field.get("value")), field


def fundamental(fundamentals, key):
    field = (fundamentals.get("fields") or {}).get(key) or {}
    return number(field.get("value")), field


def curve_readings(config, values):
    """Apply each configured curve to its named input; unavailable inputs stay unscored."""
    readings, weighted, weight_total = [], 0.0, 0.0
    for name, settings in config.curves.items():
        value, unit, source, reason = values.get(name, (None, None, None, "not_supplied"))
        if value is None:
            readings.append(Reading(name, None, unit, source, reason=reason).json())
            continue
        sub = interpolate(settings.curve, value)
        weighted += sub * settings.weight
        weight_total += settings.weight
        readings.append(
            Reading(
                name,
                round(value, 6),
                unit,
                source,
                sub_score=sub,
                detail={"curve": settings.curve, "input_weight": settings.weight},
            ).json()
        )
    score = weighted / weight_total if weight_total else None
    return score, readings


def component(name, score, readings, *, reason=None, note=None):
    return {
        "component": name,
        "score": round(score, 2) if score is not None else None,
        "status": "scored" if score is not None else "unavailable",
        "reason": reason if score is None else None,
        "note": note,
        "inputs": readings,
    }


def trend(config, technicals):
    close = number(technicals.get("last_close"))
    sma20, f20 = metric(technicals, "sma20")
    sma50, f50 = metric(technicals, "sma50")
    sma200, f200 = metric(technicals, "sma200")
    source = f20.get("source") or f50.get("source") or f200.get("source")
    checks = {
        "price_above_sma20": (close, sma20, "last close", "SMA(20)"),
        "price_above_sma50": (close, sma50, "last close", "SMA(50)"),
        "price_above_sma200": (close, sma200, "last close", "SMA(200)"),
        "sma20_above_sma50": (sma20, sma50, "SMA(20)", "SMA(50)"),
        "sma50_above_sma200": (sma50, sma200, "SMA(50)", "SMA(200)"),
    }
    readings, satisfied, available = [], 0.0, 0.0
    for name, weight in config.conditions.items():
        left, right, left_label, right_label = checks[name]
        if left is None or right is None:
            readings.append(
                Reading(
                    name,
                    None,
                    "boolean",
                    source,
                    reason=f"{left_label if left is None else right_label} is unavailable.",
                ).json()
            )
            continue
        holds = left > right
        satisfied += weight * holds
        available += weight
        readings.append(
            Reading(
                name,
                holds,
                "boolean",
                source,
                sub_score=100.0 if holds else 0.0,
                detail={
                    "comparison": f"{left_label} {left:.4f} vs {right_label} {right:.4f}",
                    "input_weight": weight,
                },
            ).json()
        )
    scored = sum(1 for row in readings if row["status"] == "scored")
    if scored < config.min_conditions or not available:
        return component(
            "trend",
            None,
            readings,
            reason=f"Needs {config.min_conditions} moving-average comparisons; have {scored}.",
        )
    return component(
        "trend",
        100 * satisfied / available,
        readings,
        note="Share of available moving-average structure checks that hold.",
    )


def momentum(config, technicals):
    rsi, rsi_field = metric(technicals, "rsi14")
    histogram, hist_field = metric(technicals, "macd_histogram")
    close = number(technicals.get("last_close"))
    percent = 100 * histogram / close if histogram is not None and close else None
    score, readings = curve_readings(
        config,
        {
            "rsi14": (
                rsi,
                "index_0_100",
                rsi_field.get("source"),
                rsi_field.get("reason") or "unavailable",
            ),
            "macd_histogram_percent_of_price": (
                percent,
                "percent_of_last_close",
                hist_field.get("source"),
                hist_field.get("reason") or "MACD histogram or last close is unavailable.",
            ),
        },
    )
    return component(
        "momentum",
        score,
        readings,
        reason="No momentum input was available.",
        note="MACD histogram is expressed as a percent of the last close so it compares "
        "across share prices.",
    )


def volume(config, technicals):
    ratio, field = metric(technicals, "volume_ratio20")
    score, readings = curve_readings(
        config,
        {
            "volume_ratio20": (
                ratio,
                "multiple",
                field.get("source"),
                field.get("reason") or "unavailable",
            )
        },
    )
    return component(
        "volume",
        score,
        readings,
        reason="Volume against its 20-session average was unavailable.",
        note="Participation only. This input has no direction: heavy selling scores "
        "the same as heavy buying.",
    )


def range_position(config, technicals):
    high, high_field = metric(technicals, "high52w")
    low, _ = metric(technicals, "low52w")
    close = number(technicals.get("last_close"))
    percent = None
    if high is not None and low is not None and close is not None and high > low:
        percent = 100 * (close - low) / (high - low)
    score, readings = curve_readings(
        config,
        {
            "percent_of_52w_range": (
                percent,
                "percent",
                high_field.get("source"),
                high_field.get("reason") or "A complete 52-week window is unavailable.",
            )
        },
    )
    return component(
        "range_position",
        score,
        readings,
        reason="The 52-week range was unavailable.",
        note="0 sits at the 52-week low and 100 at the 52-week high.",
    )


def valuation(config, fundamentals):
    pe, pe_field = fundamental(fundamentals, "pe")
    forward, forward_field = fundamental(fundamentals, "forward_pe")
    discount = 100 * (1 - forward / pe) if pe and forward else None
    score, readings = curve_readings(
        config,
        {
            "pe": (
                pe,
                "multiple",
                pe_field.get("source"),
                pe_field.get("reason") or "unavailable",
            ),
            "forward_pe_discount_percent": (
                discount,
                "percent",
                forward_field.get("source"),
                forward_field.get("reason")
                or "Needs a positive trailing and forward P/E from the same snapshot.",
            ),
        },
    )
    return component(
        "valuation",
        score,
        readings,
        reason="No valuation multiple was available.",
        note="A positive forward discount means the provider's forward P/E is below the "
        "trailing P/E. Forward figures are provider estimates, not reported results.",
    )


def growth_quality(config, fundamentals):
    growth, growth_field = fundamental(fundamentals, "revenue_growth")
    margin, margin_field = fundamental(fundamentals, "profit_margin")
    score, readings = curve_readings(
        config,
        {
            "revenue_growth_percent": (
                100 * growth if growth is not None else None,
                "percent",
                growth_field.get("source"),
                growth_field.get("reason") or "unavailable",
            ),
            "profit_margin_percent": (
                100 * margin if margin is not None else None,
                "percent",
                margin_field.get("source"),
                margin_field.get("reason") or "unavailable",
            ),
        },
    )
    return component(
        "growth_quality",
        score,
        readings,
        reason="Neither revenue growth nor profit margin was available.",
        note="Revenue growth is quarterly year over year; margin is trailing twelve months.",
    )


def news_sentiment(config, news, now):
    payload = (news or {}).get("payload") or {}
    sentiment = number(payload.get("sentiment"))
    impact = payload.get("impact")
    generated_at = (news or {}).get("generated_at")
    reason, age_hours = None, None
    if not news or sentiment is None or impact not in config.impact_scaling:
        reason = "No current news analysis is available for this ticker."
        sentiment = None
    else:
        age_hours = (now - parse_time(generated_at)).total_seconds() / 3600
        if age_hours > config.max_age_hours:
            reason = (
                f"News analysis is {age_hours:.1f}h old; the limit is "
                f"{config.max_age_hours:.0f}h. Refresh to re-analyze."
            )
            sentiment = None
    source = f"gemini:{news['model']}" if news else None
    raw, readings = curve_readings(
        config, {"sentiment": (sentiment, "sentiment_-1_to_1", source, reason)}
    )
    if raw is None:
        return component("news_sentiment", None, readings, reason=reason)
    # Impact scales how far a reading may move from neutral, so a low-impact story
    # cannot dominate the composite.
    factor = config.impact_scaling[impact]
    score = 50 + (raw - 50) * factor
    readings[0]["impact"] = impact
    readings[0]["impact_scaling"] = factor
    readings[0]["scaled_sub_score"] = round(score, 2)
    readings[0]["analysis_id"] = news.get("id")
    readings[0]["analysis_generated_at"] = generated_at
    readings[0]["analysis_age_hours"] = round(age_hours, 2)
    return component(
        "news_sentiment",
        score,
        readings,
        note="Model interpretation of headlines and excerpts, pulled toward neutral 50 "
        "by the configured impact factor. Sources are on the ticker's news analysis.",
    )


def cautions(
    config, technicals, fundamentals, news, indicator_status, news_status, coverage, today
):
    """Explicit risk flags. Flags never raise a label; some lower it to Caution."""
    flags = []

    def add(name, triggered, message, evidence):
        """`message` and `evidence` are callables so they only format when triggered."""
        rule = config.cautions.get(name)
        if rule and rule.enabled and triggered:
            flags.append(
                {
                    "flag": name,
                    "message": message(),
                    "downgrades_label": rule.downgrade,
                    **evidence(),
                }
            )

    # Stale price history undermines every technical component, so it lowers the label.
    # Stale news only removes its own weight, which weight_coverage already reports.
    add(
        "stale_indicators",
        indicator_status in {"stale", "unavailable"},
        lambda: (
            f"Price and fundamental inputs are {indicator_status}; they may not include "
            "the latest completed session. Refresh before relying on this."
        ),
        lambda: {"indicator_status": indicator_status},
    )
    add(
        "stale_news",
        news_status in {"stale", "unavailable"},
        lambda: (
            f"News analysis is {news_status}, so its weight is excluded from the score "
            "rather than assumed neutral."
        ),
        lambda: {"news_status": news_status},
    )
    rule = config.cautions.get("negative_news")
    payload = (news or {}).get("payload") or {}
    sentiment, impact = number(payload.get("sentiment")), payload.get("impact")
    threshold = getattr(rule, "sentiment_below", -0.25) if rule else -0.25
    impacts = getattr(rule, "impacts", ["medium", "high"]) if rule else []
    add(
        "negative_news",
        sentiment is not None and sentiment < threshold and impact in impacts,
        lambda: (
            f"News analysis reads negative ({sentiment}) at {impact} impact. "
            "Read the linked articles before acting."
        ),
        lambda: {"sentiment": sentiment, "impact": impact, "analysis_id": (news or {}).get("id")},
    )
    rsi, _ = metric(technicals, "rsi14")
    limit = getattr(config.cautions.get("overbought"), "rsi_above", 80)
    add(
        "overbought",
        rsi is not None and rsi > limit,
        lambda: f"RSI(14) is {rsi:.1f}, above the configured {limit} threshold.",
        lambda: {"rsi14": rsi, "threshold": limit},
    )
    sma200, _ = metric(technicals, "sma200")
    close = number(technicals.get("last_close"))
    extension = 100 * (close / sma200 - 1) if sma200 and close else None
    limit = getattr(config.cautions.get("extended_above_sma200"), "percent_above", 30)
    add(
        "extended_above_sma200",
        extension is not None and extension > limit,
        lambda: (
            f"Price is {extension:.1f}% above its 200-day average, beyond the "
            f"configured {limit}% threshold."
        ),
        lambda: {"percent_above_sma200": round(extension, 2)},
    )
    earnings = (fundamentals.get("fields") or {}).get("next_earnings_date") or {}
    start = earnings.get("window_start") or earnings.get("value")
    days = getattr(config.cautions.get("earnings_soon"), "days", 7)
    within = None
    if start and earnings.get("status") in {"available", "date_range"}:
        within = (date.fromisoformat(start) - today).days
    add(
        "earnings_soon",
        within is not None and 0 <= within <= days,
        lambda: (
            f"Earnings are expected in about {within} day(s) "
            f"({earnings.get('confirmation')}). Results can move price independently "
            "of these inputs."
        ),
        lambda: {
            "window_start": earnings.get("window_start"),
            "window_end": earnings.get("window_end"),
            "days_until": within,
        },
    )
    limit = getattr(config.cautions.get("thin_coverage"), "coverage_below", 0.75)
    add(
        "thin_coverage",
        coverage < limit,
        lambda: (
            f"Only {coverage:.0%} of the configured weight had data; the score "
            "reflects a partial picture."
        ),
        lambda: {"weight_coverage": round(coverage, 4), "threshold": limit},
    )
    return flags


def label_for(config, score, flags):
    if score is None:
        return None, "No composite score was produced."
    thresholds = config.labels
    if score >= thresholds.strong_setup:
        label = "Strong setup"
    elif score >= thresholds.watch:
        label = "Watch"
    elif score >= thresholds.neutral:
        label = "Neutral"
    else:
        label = "Caution"
    downgrades = [flag["flag"] for flag in flags if flag["downgrades_label"]]
    if downgrades and label != "Caution":
        return "Caution", f"Lowered to Caution by: {', '.join(downgrades)}."
    return label, (
        f"Score {score:.1f} against thresholds "
        f"strong_setup>={thresholds.strong_setup}, watch>={thresholds.watch}, "
        f"neutral>={thresholds.neutral}."
    )


def evaluate(ticker, indicators, news, config, now=None, today=None):
    """Score one ticker from an indicator view and an optional stored news analysis."""
    now = now or utcnow()
    # Earnings proximity is judged in exchange-local days, supplied by the caller.
    today = today or now.date()
    data = (indicators or {}).get("data") or {}
    technicals = data.get("technicals") or {}
    fundamentals = data.get("fundamentals") or {}
    news_view = news or {}
    analysis = news_view.get("data")
    components = {
        "trend": trend(config.components.trend, technicals),
        "momentum": momentum(config.components.momentum, technicals),
        "volume": volume(config.components.volume, technicals),
        "range_position": range_position(config.components.range_position, technicals),
        "valuation": valuation(config.components.valuation, fundamentals),
        "growth_quality": growth_quality(config.components.growth_quality, fundamentals),
        "news_sentiment": news_sentiment(config.components.news_sentiment, analysis, now),
    }
    total_weight = sum(config.weights.values())
    available = sum(
        config.weights[name] for name, item in components.items() if item["score"] is not None
    )
    coverage = available / total_weight if total_weight else 0.0
    breakdown = []
    score = None
    if coverage >= config.min_weight_coverage and available > 0:
        score = 0.0
        for name, item in components.items():
            weight = config.weights[name]
            share = weight / available if item["score"] is not None else 0.0
            contribution = (item["score"] or 0) * share
            score += contribution
            breakdown.append(
                item
                | {
                    "configured_weight": weight,
                    "effective_weight": round(share, 4),
                    "contribution": round(contribution, 2) if item["score"] is not None else None,
                }
            )
    else:
        breakdown = [
            item | {"configured_weight": config.weights[name], "effective_weight": 0.0}
            for name, item in components.items()
        ]
    flags = cautions(
        config,
        technicals,
        fundamentals,
        analysis,
        (indicators or {}).get("status"),
        news_view.get("status"),
        coverage,
        today,
    )
    label, rationale = label_for(config, score, flags)
    session = technicals.get("as_of_session")
    return {
        "ticker": ticker,
        "scoring_version": VERSION,
        "config_version": config.version,
        "computed_at": iso(now),
        "score": round(score, 2) if score is not None else None,
        "label": label,
        "label_rationale": rationale,
        "status": "scored" if score is not None else "insufficient_data",
        "reason": None
        if score is not None
        else (
            f"Available inputs cover {coverage:.0%} of scoring weight; the configured "
            f"minimum is {config.min_weight_coverage:.0%}. Missing values are not estimated."
        ),
        "weight_coverage": round(coverage, 4),
        "min_weight_coverage": config.min_weight_coverage,
        "breakdown": breakdown,
        "cautions": flags,
        "inputs": {
            "indicator_snapshot_id": data.get("snapshot_id"),
            "indicator_status": (indicators or {}).get("status"),
            "indicator_as_of_session": session,
            "technical_status": technicals.get("status"),
            "fundamental_status": fundamentals.get("status"),
            "last_close": number(technicals.get("last_close")),
            "history_source": technicals.get("source"),
            "news_analysis_id": (analysis or {}).get("id"),
            "news_status": news_view.get("status"),
            "news_generated_at": (analysis or {}).get("generated_at"),
        },
        "weights": dict(config.weights),
        "labels": config.labels.model_dump(),
        "disclaimer": DISCLAIMER,
    }
