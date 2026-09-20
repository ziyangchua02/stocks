from copy import deepcopy
from datetime import date, datetime

import pytest

from app.jobs.market import MarketClock
from app.services.technicals import calculate, ema, rsi

AS_OF = datetime.fromisoformat("2026-09-20T12:00:00+00:00")


@pytest.fixture
def bars():
    calendar = MarketClock()
    days = calendar.sessions(date(2024, 1, 1), date(2026, 9, 18))[-400:]
    return [
        {
            "ticker": "AAPL",
            "session_date": day,
            "open": 100 + i,
            "high": 102 + i,
            "low": 99 + i,
            "close": 100 + i,
            "volume": 100,
            "source": "yfinance",
            "source_url": "https://example.com/history",
            "fetched_at": AS_OF.isoformat(),
            "is_complete": True,
            "adjustment": "split-adjusted",
            "adjusted_close": 50 + i,
        }
        for i, day in enumerate(days)
    ]


def test_known_wilder_rsi_values_and_smoothing():
    closes = [
        44.34,
        44.09,
        44.15,
        43.61,
        44.33,
        44.83,
        45.10,
        45.42,
        45.84,
        46.08,
        45.89,
        46.03,
        45.61,
        46.28,
        46.28,
        46.00,
    ]
    values = rsi(closes)
    assert values[:14] == [None] * 14
    assert values[14] == pytest.approx(70.464135021097, abs=1e-10)
    assert values[15] == pytest.approx(66.249618553555, abs=1e-10)


@pytest.mark.parametrize(
    ("closes", "expected"),
    [
        (list(range(1, 31)), 100),
        (list(range(30, 0, -1)), 0),
        ([100] * 30, 50),
    ],
)
def test_rsi_zero_denominator_conventions(closes, expected):
    assert rsi(closes)[-1] == expected


def test_ema_seed_and_recurrence():
    assert ema([1, 2, 3, 10], 3) == [None, None, 2.0, 6.0]


def test_sma_and_macd_have_known_values_on_linear_trend(bars):
    result = calculate(bars, MarketClock(), AS_OF)
    metrics = result["metrics"]
    assert result["status"] == "available"
    assert metrics["sma20"]["value"] == 489.5
    assert metrics["sma50"]["value"] == 474.5
    assert metrics["sma200"]["value"] == 399.5
    assert metrics["macd"]["value"] == pytest.approx(7)
    assert metrics["macd_signal"]["value"] == pytest.approx(7)
    assert metrics["macd_histogram"]["value"] == pytest.approx(0)
    assert result["series"][24]["macd"] is None
    assert result["series"][25]["macd"] == pytest.approx(7)
    assert result["series"][32]["macd_signal"] is None
    assert result["series"][33]["macd_signal"] == pytest.approx(7)


def test_prior_volume_baseline_excludes_current_session(bars):
    bars[-1]["volume"] = 200
    metrics = calculate(bars, MarketClock(), AS_OF)["metrics"]
    assert metrics["volume_average20"]["value"] == 100
    assert metrics["volume_ratio20"]["value"] == 2
    for bar in bars[-21:-1]:
        bar["volume"] = 0
    metrics = calculate(bars, MarketClock(), AS_OF)["metrics"]
    assert metrics["volume_average20"]["value"] == 0
    assert metrics["volume_ratio20"]["value"] is None
    assert "zero" in metrics["volume_ratio20"]["reason"]


def test_52week_uses_high_low_and_calendar_window(bars):
    bars[0]["high"] = 10000  # Outside the 52-week window.
    bars[-10]["low"] = 1
    result = calculate(bars, MarketClock(), AS_OF)
    metrics = result["metrics"]
    assert metrics["high52w"]["value"] == 501
    assert metrics["low52w"]["value"] == 1
    assert metrics["distance_from_high52w_pct"]["value"] == pytest.approx((499 / 501 - 1) * 100)
    assert metrics["distance_from_low52w_pct"]["value"] == 49800
    assert result["window52w"]["expected_sessions"] == result["window52w"]["available_sessions"]


def test_short_history_and_empty_input_do_not_invent_values(bars):
    result = calculate(bars[-14:], MarketClock(), AS_OF)
    assert result["metrics"]["rsi14"]["value"] is None
    assert result["metrics"]["high52w"]["value"] is None
    assert result["metrics"]["sma200"]["value"] is None
    assert calculate([], MarketClock(), AS_OF)["status"] == "unavailable"


def test_missing_session_restarts_rolling_and_recursive_indicators(bars):
    del bars[-11]
    result = calculate(bars, MarketClock(), AS_OF)
    assert result["consecutive_sessions"] == 10
    assert result["metrics"]["sma20"]["value"] is None
    assert result["metrics"]["rsi14"]["value"] is None
    assert result["metrics"]["macd"]["value"] is None
    assert result["metrics"]["high52w"]["value"] is None
    assert "missing session" in result["warnings"][0]


def test_incomplete_future_and_invalid_bars_are_excluded(bars):
    baseline = calculate(bars[:-1], MarketClock(), AS_OF)
    bars[-1]["is_complete"] = False
    result = calculate(bars, MarketClock(), AS_OF)
    assert result["last_close"] == baseline["last_close"]
    assert result["incomplete_bars_excluded"] == 1
    bars[-1]["is_complete"] = True
    bars[-1]["session_date"] = "2030-01-01"
    assert calculate(bars, MarketClock(), AS_OF)["last_close"] == baseline["last_close"]
    bars[-1]["session_date"] = "2026-09-18"
    bars[-1]["high"] = 0
    assert calculate(bars, MarketClock(), AS_OF)["invalid_bars"] == 1


def test_inconsistent_adjustment_sources_are_not_spliced(bars):
    bars[-1]["source"] = "finnhub"
    result = calculate(bars, MarketClock(), AS_OF)
    assert result["status"] == "unavailable"
    assert all(metric["value"] is None for metric in result["metrics"].values())


def test_future_changes_cannot_change_earlier_indicator_points(bars):
    first = calculate(bars, MarketClock(), AS_OF)["series"]
    changed = deepcopy(bars)
    changed[-1].update(open=2000, high=2100, low=1900, close=2000, volume=300)
    second = calculate(changed, MarketClock(), AS_OF)["series"]
    assert first[:-1] == second[:-1]
    assert first[-1]["sma20"] != second[-1]["sma20"]
