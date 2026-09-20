"""Deterministic end-of-day indicators; no provider or LLM calls."""

from datetime import date, timedelta
from math import fsum

from app.models import number, parse_time, utcnow

VERSION = "daily-v1"
METHODS = {
    "sma20": (20, "price", "Arithmetic mean of the latest 20 completed session closes."),
    "sma50": (50, "price", "Arithmetic mean of the latest 50 completed session closes."),
    "sma200": (200, "price", "Arithmetic mean of the latest 200 completed session closes."),
    "rsi14": (
        15,
        "index_0_100",
        "Wilder RSI: 14-change SMA seed, then 1/14 smoothing. "
        "All-flat series uses the explicit neutral convention 50.",
    ),
    "macd": (26, "price", "EMA(12) minus EMA(26); each EMA starts with its period's SMA."),
    "macd_signal": (34, "price", "EMA(9) of valid MACD values, seeded with their SMA."),
    "macd_histogram": (34, "price", "MACD minus its signal line."),
    "volume_average20": (
        21,
        "shares",
        "Mean volume of the prior 20 completed sessions, excluding the session being measured.",
    ),
    "volume_ratio20": (
        21,
        "multiple",
        "Latest completed session volume / prior 20-session "
        "mean volume. Unavailable when the denominator is zero.",
    ),
    "high52w": (None, "price", "Highest daily high within the trailing 52 calendar weeks."),
    "low52w": (None, "price", "Lowest daily low within the trailing 52 calendar weeks."),
    "distance_from_high52w_pct": (None, "percent", "100 * (latest close / 52-week high - 1)."),
    "distance_from_low52w_pct": (None, "percent", "100 * (latest close / 52-week low - 1)."),
}


def sma(values, period):
    return [
        None if i + 1 < period else fsum(values[i - period + 1 : i + 1]) / period
        for i in range(len(values))
    ]


def ema(values, period):
    result = [None] * len(values)
    if len(values) >= period:
        previous = fsum(values[:period]) / period
        result[period - 1] = previous
        alpha = 2 / (period + 1)
        for i in range(period, len(values)):
            previous += alpha * (values[i] - previous)
            result[i] = previous
    return result


def rsi(values, period=14):
    result = [None] * len(values)
    if len(values) <= period:
        return result
    changes = [b - a for a, b in zip(values, values[1:], strict=False)]
    gain = fsum(max(0, x) for x in changes[:period]) / period
    loss = fsum(max(0, -x) for x in changes[:period]) / period

    def value():
        if loss == 0:
            return 100.0 if gain > 0 else 50.0
        return 100 - 100 / (1 + gain / loss)

    result[period] = value()
    for i in range(period + 1, len(values)):
        change = changes[i - 1]
        gain = (gain * (period - 1) + max(0, change)) / period
        loss = (loss * (period - 1) + max(0, -change)) / period
        result[i] = value()
    return result


def vectors(bars):
    closes, volumes = [b["close"] for b in bars], [b["volume"] for b in bars]
    fast, slow = ema(closes, 12), ema(closes, 26)
    macd = [
        a - b if a is not None and b is not None else None for a, b in zip(fast, slow, strict=True)
    ]
    signal = [None] * min(25, len(bars)) + ema(macd[25:], 9)
    averages = [None if i < 20 else fsum(volumes[i - 20 : i]) / 20 for i in range(len(bars))]
    values = {
        "sma20": sma(closes, 20),
        "sma50": sma(closes, 50),
        "sma200": sma(closes, 200),
        "rsi14": rsi(closes),
        "macd": macd,
        "macd_signal": signal,
        "macd_histogram": [
            a - b if a is not None and b is not None else None
            for a, b in zip(macd, signal, strict=True)
        ],
        "volume_average20": averages,
        "volume_ratio20": [
            v / avg if avg else None for v, avg in zip(volumes, averages, strict=True)
        ],
    }
    return [
        {
            "session_date": bar["session_date"],
            "close": bar["close"],
            "volume": bar["volume"],
            "source_fetched_at": bar["fetched_at"],
            **{key: series[i] for key, series in values.items()},
        }
        for i, bar in enumerate(bars)
    ]


def calculate(bars, market, now=None):
    now = now or utcnow()
    expected_latest = market.state(now)["last_completed_session"]
    valid, invalid, incomplete = {}, 0, 0
    for raw in bars:
        try:
            day = date.fromisoformat(raw["session_date"])
            if not raw["is_complete"] or day.isoformat() > expected_latest:
                incomplete += 1
                continue
            ohlc = [number(raw[key]) for key in ["open", "high", "low", "close"]]
            volume = number(raw["volume"])
            if (
                any(x is None or x <= 0 for x in ohlc)
                or volume is None
                or volume < 0
                or ohlc[1] < max(ohlc)
                or ohlc[2] > min(ohlc)
            ):
                invalid += 1
                continue
            parse_time(raw["fetched_at"])
            if raw["session_date"] in valid:
                invalid += 1  # Never silently choose between duplicate daily observations.
                continue
            valid[raw["session_date"]] = raw
        except (KeyError, TypeError, ValueError):
            invalid += 1
    ordered = [valid[day] for day in sorted(valid)]
    warnings = []
    if len({(b["source"], b["adjustment"]) for b in ordered}) > 1:
        ordered = []
        warnings.append("Mixed sources or adjustment conventions; technicals unavailable.")
    if ordered:
        sessions = market.sessions(
            date.fromisoformat(ordered[0]["session_date"]),
            date.fromisoformat(ordered[-1]["session_date"]),
        )
        allowed = set(sessions)
        invalid += sum(b["session_date"] not in allowed for b in ordered)
        ordered = [b for b in ordered if b["session_date"] in allowed]
    if not ordered:
        return {
            "status": "unavailable",
            "as_of_session": None,
            "last_close": None,
            "metrics": {
                key: {
                    "value": None,
                    "status": "insufficient_data",
                    "unit": unit,
                    "required_sessions": required,
                    "method": method,
                }
                for key, (required, unit, method) in METHODS.items()
            },
            "warnings": warnings + ["No valid completed daily bars."],
            "series": [],
            "invalid_bars": invalid,
            "incomplete_bars_excluded": incomplete,
        }
    # Do not bridge missing sessions: reset all rolling/recursive calculations after each gap.
    position = {day: i for i, day in enumerate(sessions)}
    segments = [[]]
    for bar in ordered:
        if segments[-1] and position[bar["session_date"]] != (
            position[segments[-1][-1]["session_date"]] + 1
        ):
            segments.append([])
        segments[-1].append(bar)
    series = [point for segment in segments for point in vectors(segment)]
    latest, last = ordered[-1], series[-1]
    count = len(segments[-1])
    as_of = date.fromisoformat(latest["session_date"])
    start = as_of - timedelta(weeks=52)
    required52 = set(market.sessions(start + timedelta(days=1), as_of))
    window = [bar for bar in ordered if start < date.fromisoformat(bar["session_date"]) <= as_of]
    covered52 = required52.issubset({bar["session_date"] for bar in window})
    high = max(b["high"] for b in window) if covered52 else None
    low = min(b["low"] for b in window) if covered52 else None
    values = {
        **last,
        "high52w": high,
        "low52w": low,
        "distance_from_high52w_pct": 100 * (last["close"] / high - 1) if high else None,
        "distance_from_low52w_pct": 100 * (last["close"] / low - 1) if low else None,
    }
    metrics = {}
    for key, (required, unit, method) in METHODS.items():
        value = values.get(key)
        reason = None
        if value is None:
            if key == "volume_ratio20" and count >= 21:
                reason = "Prior 20-session mean volume is zero."
            elif required is None:
                reason = "A full 52-week window of exchange sessions is not available."
            else:
                reason = f"Requires {required} consecutive completed sessions; have {count}."
        metrics[key] = {
            "value": value,
            "unit": unit,
            "method": method,
            "reason": reason,
            "status": "available" if value is not None else "insufficient_data",
            "required_sessions": required if required else len(required52),
            "as_of_session": as_of.isoformat(),
            "source": latest["source"],
            "source_url": latest["source_url"],
            "source_fetched_at": latest["fetched_at"],
        }
    gaps = len(sessions) - len(ordered)
    if gaps:
        warnings.append(f"{gaps} missing session(s); recursive calculations restart after gaps.")
    if invalid:
        warnings.append(f"{invalid} invalid or duplicate bar(s) excluded.")
    if latest["source"] != "yfinance":
        warnings.append(
            "Fallback history adjustment basis is provider-defined; inspect provenance."
        )
    return {
        "status": "available"
        if all(m["value"] is not None for m in metrics.values())
        else "partial",
        "as_of_session": as_of.isoformat(),
        "last_close": latest["close"],
        "price_basis": "close (not dividend-adjusted); same basis used for daily high/low",
        "adjustment": latest["adjustment"],
        "source": latest["source"],
        "source_url": latest["source_url"],
        "source_fetched_at": latest["fetched_at"],
        "completed_bars": len(ordered),
        "consecutive_sessions": count,
        "incomplete_bars_excluded": incomplete,
        "invalid_bars": invalid,
        "window52w": {
            "start_exclusive": start.isoformat(),
            "end_inclusive": as_of.isoformat(),
            "expected_sessions": len(required52),
            "available_sessions": len(window),
        },
        "metrics": metrics,
        "warnings": warnings,
        "series": series,
    }
