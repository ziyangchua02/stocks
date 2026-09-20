"""Normalize provider fields without silently mixing reporting periods or units."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.models import number, utcnow

# Fractional rates are the public API unit. Keep period labels and source fields explicit.
MAPPINGS = {
    "yfinance": {
        "pe": ("trailingPE", "multiple", "trailing_twelve_months", 1),
        "forward_pe": ("forwardPE", "multiple", "forward_provider_estimate", 1),
        "revenue_growth": ("revenueGrowth", "fraction", "quarterly_year_over_year", 1),
        "profit_margin": ("profitMargins", "fraction", "trailing_twelve_months", 1),
    },
    "finnhub": {
        "pe": ("peTTM", "multiple", "trailing_twelve_months", 1),
        "forward_pe": ("forwardPE", "multiple", "forward_provider_estimate", 1),
        "revenue_growth": (
            "revenueGrowthQuarterlyYoy",
            "fraction",
            "quarterly_year_over_year",
            0.01,
        ),
        "profit_margin": ("netProfitMarginTTM", "fraction", "trailing_twelve_months", 0.01),
    },
}


def epoch(value):
    value = number(value)
    if value is None or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value, UTC)
    except (ValueError, OverflowError, OSError):
        return None


def earnings(raw, now, timezone):
    """Yahoo may give a past last-release timestamp plus a future estimated date/range."""
    today = now.astimezone(ZoneInfo(timezone)).date()
    start, end = epoch(raw.get("earningsTimestampStart")), epoch(raw.get("earningsTimestampEnd"))
    source_fields = ["earningsTimestampStart", "earningsTimestampEnd"]
    if start and end and end >= start and end.astimezone(ZoneInfo(timezone)).date() >= today:
        first, last = start.astimezone(ZoneInfo(timezone)), end.astimezone(ZoneInfo(timezone))
    else:
        exact = epoch(raw.get("earningsTimestamp"))
        if exact is None or exact.astimezone(ZoneInfo(timezone)).date() < today:
            return {
                "value": None,
                "status": "unavailable",
                "unit": "date",
                "reason": "No upcoming earnings date in the provider data.",
                "source_fields": source_fields + ["earningsTimestamp"],
            }
        first = last = exact.astimezone(ZoneInfo(timezone))
        source_fields = ["earningsTimestamp"]
    confirmed = raw.get("isEarningsDateEstimate") is False
    return {
        "value": first.date().isoformat() if first.date() == last.date() else None,
        "status": "available" if first.date() == last.date() else "date_range",
        "unit": "date",
        "window_start": first.date().isoformat(),
        "window_end": last.date().isoformat(),
        "timezone": timezone,
        "provider_timestamps": [first.isoformat(), last.isoformat()],
        "confirmation": "provider_confirmed" if confirmed else "estimated_or_unconfirmed",
        "reason": "Provider dates may change; a window is not collapsed to one exact date.",
        "source_fields": source_fields,
    }


def normalize(snapshot, now=None, timezone="America/New_York"):
    now = now or utcnow()
    snapshot = snapshot or {}
    provider, raw = snapshot.get("source"), snapshot.get("raw", {})
    fields = {}
    mapping = MAPPINGS.get(provider, MAPPINGS["yfinance"])
    provenance = {
        "source": provider,
        "source_url": snapshot.get("source_url"),
        "source_as_of": snapshot.get("source_as_of"),
        "source_fetched_at": snapshot.get("fetched_at"),
    }
    for name, (key, unit, period, scale) in mapping.items():
        original = number(raw.get(key)) if provider in MAPPINGS else None
        value = original * scale if original is not None else None
        status, reason = "available", None
        if value is None:
            status, reason = "unavailable", f"Provider did not supply a finite {key} value."
        elif name in {"pe", "forward_pe"} and value <= 0:
            value = None
            status, reason = (
                "not_meaningful",
                "A non-positive P/E is not a meaningful valuation multiple.",
            )
        fields[name] = {
            **provenance,
            "value": value,
            "unit": unit,
            "period": period,
            "source_field": key,
            "raw_value": original,
            "status": status,
            "reason": reason,
            "display_percent": value * 100 if value is not None and unit == "fraction" else None,
        }
    next_earnings = (
        earnings(raw, now, timezone)
        if provider == "yfinance"
        else {
            "value": None,
            "status": "unavailable",
            "unit": "date",
            "reason": "Basic financial metrics do not include an upcoming earnings calendar.",
        }
    )
    fields["next_earnings_date"] = {**provenance, **next_earnings}
    known = sum(field["status"] in {"available", "date_range"} for field in fields.values())
    quarter = epoch(raw.get("mostRecentQuarter"))
    return {
        "status": "available" if known == len(fields) else "partial" if known else "unavailable",
        "fields": fields,
        **provenance,
        "currency": raw.get("currency"),
        "latest_reported_quarter_end": quarter.date().isoformat() if quarter else None,
        "as_of_note": "Retrieval time is not a financial statement publication date. "
        "Reporting periods and forward estimates are identified per field.",
    }
