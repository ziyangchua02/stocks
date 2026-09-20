"""What happened after each recorded signal. Measured from stored bars only.

This exists to test whether the scoring has any predictive value, so it must be
able to report that it does not. Nothing here is smoothed, back-filled, or
selected after the fact: a horizon that has not elapsed stays pending, and a
missing bar stays missing.
"""

from datetime import date, timedelta
from statistics import mean, median

HORIZONS = {"1_week": 7, "1_month": 30}
MINIMUM_SAMPLE = 30
CAVEATS = [
    "A recorded signal is not a trade: there is no entry rule, no position size, "
    "no costs, and no exit rule.",
    "Forward returns are measured from the reference session close to the first "
    "completed session on or after the horizon date.",
    "Signals for the same ticker on consecutive sessions overlap, so their "
    "returns are not independent observations.",
    "The watchlist is self-selected and changes over time, so this is not a "
    "survivorship-free sample of any market.",
    "Excess return uses a single index benchmark and no risk adjustment.",
]


def closes(bars):
    return {bar["session_date"]: bar["close"] for bar in bars if bar.get("close")}


def forward(prices, reference_session, reference_close, days, latest_session):
    """First completed session on or after the horizon date, or why it is missing."""
    target = (date.fromisoformat(reference_session) + timedelta(days=days)).isoformat()
    if not reference_close or not prices:
        return {
            "status": "unavailable",
            "target_date": target,
            "reason": "No stored price history for this ticker.",
        }
    later = sorted(session for session in prices if session >= target)
    if not later:
        return {
            "status": "pending",
            "target_date": target,
            "reason": (
                f"The horizon has not elapsed or is not yet downloaded; the newest "
                f"stored session is {latest_session}."
            ),
        }
    session = later[0]
    close = prices[session]
    gap = (date.fromisoformat(session) - date.fromisoformat(target)).days
    return {
        "status": "measured",
        "target_date": target,
        "observed_session": session,
        "sessions_after_target_days": gap,
        "close": close,
        "return_percent": 100 * (close / reference_close - 1),
        "note": (
            f"Measured {gap} day(s) after the horizon date because no session fell on it."
            if gap
            else None
        ),
    }


class Performance:
    def __init__(self, store, config):
        self.store = store
        self.config = config
        self.benchmark = config.market_indices[0].symbol if config.market_indices else None

    def prices(self, ticker):
        bars = self.store.bars(ticker, 3000)
        return closes(bars), (bars[-1]["session_date"] if bars else None)

    def outcomes(self, signal, prices, latest, benchmark_prices, benchmark_latest):
        """Absolute and benchmark-relative outcome for one signal, per horizon."""
        result = {}
        reference = signal["reference_session"]
        if not reference or not signal["reference_close"]:
            return {
                name: {"status": "unavailable", "reason": "Signal has no reference session close."}
                for name in HORIZONS
            }
        benchmark_reference = benchmark_prices.get(reference) if benchmark_prices else None
        for name, days in HORIZONS.items():
            row = forward(prices, reference, signal["reference_close"], days, latest)
            if row["status"] == "measured" and benchmark_reference:
                index = forward(
                    benchmark_prices, reference, benchmark_reference, days, benchmark_latest
                )
                if index["status"] == "measured":
                    row["benchmark_symbol"] = self.benchmark
                    row["benchmark_return_percent"] = index["return_percent"]
                    row["excess_return_percent"] = row["return_percent"] - index["return_percent"]
                    row["benchmark_session"] = index["observed_session"]
                else:
                    row["benchmark_status"] = index["status"]
                    row["benchmark_reason"] = index.get("reason")
            elif row["status"] == "measured":
                row["benchmark_status"] = "unavailable"
                row["benchmark_reason"] = (
                    "No stored benchmark close for the reference session."
                    if self.benchmark
                    else "No benchmark index is configured."
                )
            result[name] = row
        return result

    def attach(self, signals):
        """Add outcomes to signal rows, loading each ticker's prices once."""
        cache = {}
        benchmark_prices, benchmark_latest = (
            self.prices(self.benchmark) if self.benchmark else ({}, None)
        )
        for signal in signals:
            if signal["ticker"] not in cache:
                cache[signal["ticker"]] = self.prices(signal["ticker"])
            prices, latest = cache[signal["ticker"]]
            signal["outcomes"] = self.outcomes(
                signal, prices, latest, benchmark_prices, benchmark_latest
            )
        return signals

    def summary(self, limit=1000):
        """Group measured outcomes by label. Small samples are stated, not hidden."""
        signals = self.attach(self.store.signals(limit=limit)["items"])
        groups = {}
        for signal in signals:
            label = signal["label"] or "unlabelled"
            entry = groups.setdefault(
                label,
                {
                    "label": label,
                    "signals": 0,
                    "horizons": {
                        name: {"measured": 0, "pending": 0, "returns": [], "excess": []}
                        for name in HORIZONS
                    },
                },
            )
            entry["signals"] += 1
            for name, row in signal["outcomes"].items():
                bucket = entry["horizons"][name]
                if row["status"] == "measured":
                    bucket["measured"] += 1
                    bucket["returns"].append(row["return_percent"])
                    if "excess_return_percent" in row:
                        bucket["excess"].append(row["excess_return_percent"])
                elif row["status"] == "pending":
                    bucket["pending"] += 1
        rows = []
        for entry in groups.values():
            horizons = {}
            for name, bucket in entry["horizons"].items():
                returns, excess = bucket["returns"], bucket["excess"]
                horizons[name] = {
                    "measured": bucket["measured"],
                    "pending": bucket["pending"],
                    "mean_return_percent": mean(returns) if returns else None,
                    "median_return_percent": median(returns) if returns else None,
                    "positive_share": (
                        sum(1 for value in returns if value > 0) / len(returns) if returns else None
                    ),
                    "mean_excess_percent": mean(excess) if excess else None,
                    "benchmark_measured": len(excess),
                }
            rows.append(
                {"label": entry["label"], "signals": entry["signals"], **{"horizons": horizons}}
            )
        rows.sort(key=lambda row: row["label"])
        measured = sum(horizon["measured"] for row in rows for horizon in row["horizons"].values())
        smallest = min((row["signals"] for row in rows), default=0)
        return {
            "groups": rows,
            "total_signals": sum(row["signals"] for row in rows),
            "measured_outcomes": measured,
            "benchmark_symbol": self.benchmark,
            "horizons": HORIZONS,
            "sufficient_sample": bool(rows) and smallest >= MINIMUM_SAMPLE,
            "minimum_sample_per_group": MINIMUM_SAMPLE,
            "verdict": (
                "Not enough recorded outcomes to say anything about predictive value. "
                "Treat these numbers as a record of what happened, not as evidence."
                if not rows or smallest < MINIMUM_SAMPLE
                else "Sample sizes are above the configured minimum; differences between "
                "labels may still be noise, and no significance test is applied."
            ),
            "caveats": CAVEATS,
            "disclaimer": "Not financial advice. Past outcomes do not predict future ones.",
        }
