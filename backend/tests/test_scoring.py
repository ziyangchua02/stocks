from datetime import date, timedelta

import pytest

from app.models import iso, utcnow
from app.services.scoring import evaluate, interpolate
from app.settings import ScoringConfig, load_scoring


@pytest.fixture
def scoring():
    return load_scoring()


def technicals(**metrics):
    defaults = {
        "sma20": 100.0,
        "sma50": 95.0,
        "sma200": 90.0,
        "rsi14": 55.0,
        "macd_histogram": 0.5,
        "volume_ratio20": 1.4,
        "high52w": 120.0,
        "low52w": 80.0,
    }
    defaults.update(metrics)
    return {
        "status": "available",
        "as_of_session": "2026-09-18",
        "last_close": metrics.get("last_close", 105.0),
        "source": "yfinance",
        "metrics": {
            key: {
                "value": value,
                "source": "yfinance",
                "reason": None if value is not None else "insufficient_data",
            }
            for key, value in defaults.items()
            if key != "last_close"
        },
    }


def fundamentals(**values):
    defaults = {"pe": 22.0, "forward_pe": 18.0, "revenue_growth": 0.12, "profit_margin": 0.24}
    defaults.update(values)
    earnings = defaults.pop("next_earnings_date", None)
    fields = {
        key: {"value": value, "source": "yfinance", "reason": None}
        for key, value in defaults.items()
    }
    fields["next_earnings_date"] = earnings or {"status": "unavailable", "value": None}
    return {"status": "available", "fields": fields}


def view(technical=None, fundamental=None, status="available"):
    return {
        "status": status,
        "data": {
            "snapshot_id": 7,
            "technicals": technical if technical is not None else technicals(),
            "fundamentals": fundamental if fundamental is not None else fundamentals(),
        },
    }


def news_view(sentiment=0.4, impact="medium", age_hours=1, status="cached"):
    return {
        "status": status,
        "data": {
            "id": 11,
            "model": "gemini-3.1-flash-lite",
            "generated_at": iso(utcnow() - timedelta(hours=age_hours)),
            "payload": {"sentiment": sentiment, "impact": impact, "summary": "Example."},
        },
    }


def test_interpolate_clamps_and_interpolates_linearly():
    points = [[0, 0], [10, 100]]
    assert interpolate(points, -5) == 0
    assert interpolate(points, 0) == 0
    assert interpolate(points, 5) == 50
    assert interpolate(points, 10) == 100
    assert interpolate(points, 99) == 100


def test_full_inputs_produce_a_scored_breakdown(scoring):
    result = evaluate("AAPL", view(), news_view(), scoring)
    assert result["status"] == "scored"
    assert 0 <= result["score"] <= 100
    assert result["weight_coverage"] == 1.0
    assert {row["component"] for row in result["breakdown"]} == set(scoring.weights)
    assert all(row["status"] == "scored" for row in result["breakdown"])
    # The composite is exactly the weighted mean of the component scores.
    expected = sum(
        row["score"] * scoring.weights[row["component"]] for row in result["breakdown"]
    ) / sum(scoring.weights.values())
    assert result["score"] == pytest.approx(expected, abs=0.02)
    assert sum(row["contribution"] for row in result["breakdown"]) == pytest.approx(
        result["score"], abs=0.05
    )


def test_missing_inputs_are_reported_not_imputed(scoring):
    bare = technicals(sma50=None, sma200=None, rsi14=None, macd_histogram=None, high52w=None)
    result = evaluate("AAPL", view(bare, fundamentals(pe=None, forward_pe=None)), None, scoring)
    unavailable = {row["component"]: row for row in result["breakdown"] if row["score"] is None}
    assert "valuation" in unavailable and "news_sentiment" in unavailable
    assert unavailable["valuation"]["reason"]
    assert all(row["effective_weight"] == 0.0 for row in unavailable.values())
    for row in result["breakdown"]:
        for item in row["inputs"]:
            assert item["value"] is not None or item["reason"]


def test_score_is_withheld_below_minimum_coverage(scoring):
    empty = technicals(
        sma20=None,
        sma50=None,
        sma200=None,
        rsi14=None,
        macd_histogram=None,
        volume_ratio20=None,
        high52w=None,
        low52w=None,
    )
    blank = fundamentals(pe=None, forward_pe=None, revenue_growth=None, profit_margin=None)
    result = evaluate("AAPL", view(empty, blank), None, scoring)
    assert result["status"] == "insufficient_data"
    assert result["score"] is None and result["label"] is None
    assert "minimum" in result["reason"]
    assert result["weight_coverage"] < scoring.min_weight_coverage


def test_news_impact_scales_the_sentiment_component(scoring):
    high = evaluate("AAPL", view(), news_view(0.8, "high"), scoring)
    low = evaluate("AAPL", view(), news_view(0.8, "low"), scoring)
    component = {row["component"]: row for row in high["breakdown"]}["news_sentiment"]
    quiet = {row["component"]: row for row in low["breakdown"]}["news_sentiment"]
    assert component["score"] > quiet["score"] > 50
    assert component["inputs"][0]["analysis_id"] == 11
    assert (
        quiet["inputs"][0]["impact_scaling"]
        == scoring.components.news_sentiment.impact_scaling["low"]
    )


def test_stale_news_analysis_is_not_scored(scoring):
    result = evaluate("AAPL", view(), news_view(age_hours=100), scoring)
    component = {row["component"]: row for row in result["breakdown"]}["news_sentiment"]
    assert component["score"] is None
    assert "old" in component["reason"]


def test_labels_follow_configured_thresholds(scoring):
    weak = technicals(sma20=120.0, sma50=130.0, sma200=140.0, rsi14=22.0, macd_histogram=-1.5)
    poor = fundamentals(pe=95.0, forward_pe=130.0, revenue_growth=-0.2, profit_margin=-0.05)
    low = evaluate("AAPL", view(weak, poor), news_view(-0.6, "high"), scoring)
    assert low["label"] == "Caution"
    strong = evaluate("AAPL", view(), news_view(0.7, "high"), scoring)
    assert strong["label"] in {"Strong setup", "Watch", "Neutral"}
    assert str(strong["score"]) in strong["label_rationale"] or "Score" in strong["label_rationale"]


def test_caution_flags_and_label_downgrade(scoring):
    soon = (date.today() + timedelta(days=2)).isoformat()
    earnings = {
        "status": "available",
        "value": soon,
        "window_start": soon,
        "window_end": soon,
        "confirmation": "estimated_or_unconfirmed",
    }
    result = evaluate(
        "AAPL",
        view(technicals(rsi14=88.0, sma200=70.0), fundamentals(next_earnings_date=earnings)),
        news_view(-0.8, "high"),
        scoring,
        today=date.today(),
    )
    flags = {flag["flag"] for flag in result["cautions"]}
    assert {"overbought", "earnings_soon", "negative_news", "extended_above_sma200"} <= flags
    assert result["label"] == "Caution"
    assert "negative_news" in result["label_rationale"]


def test_stale_indicators_downgrade_but_stale_news_only_flags(scoring):
    result = evaluate("AAPL", view(status="stale"), news_view(0.9, "high"), scoring)
    flags = {flag["flag"]: flag for flag in result["cautions"]}
    assert flags["stale_indicators"]["indicator_status"] == "stale"
    assert result["label"] == "Caution"
    # Missing news removes its own weight; it does not condemn the whole reading.
    without_news = evaluate("AAPL", view(), {"status": "stale", "data": None}, scoring)
    flags = {flag["flag"]: flag for flag in without_news["cautions"]}
    assert flags["stale_news"]["downgrades_label"] is False
    assert without_news["label"] != "Caution"
    assert without_news["weight_coverage"] == pytest.approx(0.8)


def test_no_certainty_language_in_generated_text(scoring):
    result = evaluate("AAPL", view(), news_view(), scoring)
    text = " ".join(
        [result["disclaimer"], result["label_rationale"]]
        + [row["note"] or "" for row in result["breakdown"]]
        + [flag["message"] for flag in result["cautions"]]
    ).lower()
    for phrase in ("guaranteed", "can't lose", "risk-free", "sure thing", "will rise"):
        assert phrase not in text


def test_config_rejects_weights_that_do_not_match_components(scoring):
    broken = scoring.model_dump(mode="json")
    broken["weights"].pop("volume")
    with pytest.raises(ValueError, match="weights must cover"):
        ScoringConfig.model_validate(broken)


def test_config_rejects_unordered_labels_and_curves(scoring):
    broken = scoring.model_dump(mode="json")
    broken["labels"]["watch"] = 90
    with pytest.raises(ValueError, match="decrease"):
        ScoringConfig.model_validate(broken)
    descending = scoring.model_dump(mode="json")
    descending["components"]["momentum"]["curves"]["rsi14"]["curve"] = [[50, 10], [10, 90]]
    with pytest.raises(ValueError, match="ascending"):
        ScoringConfig.model_validate(descending)


def test_weight_change_alters_the_score(scoring):
    tilted = ScoringConfig.model_validate(
        scoring.model_dump(mode="json")
        | {
            "weights": {
                "trend": 1.0,
                "momentum": 0.0,
                "volume": 0.0,
                "range_position": 0.0,
                "valuation": 0.0,
                "growth_quality": 0.0,
                "news_sentiment": 0.0,
            }
        }
    )
    base = evaluate("AAPL", view(), news_view(), scoring)
    trend_only = evaluate("AAPL", view(), news_view(), tilted)
    assert trend_only["score"] == 100.0
    assert trend_only["score"] != base["score"]
    assert trend_only["weights"]["trend"] == 1.0
