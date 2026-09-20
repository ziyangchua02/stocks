from datetime import datetime

import pytest

from app.services.fundamentals import normalize

NOW = datetime.fromisoformat("2026-09-20T12:00:00+00:00")


def snapshot(source="yfinance", **raw):
    return {
        "source": source,
        "source_as_of": None,
        "fetched_at": NOW.isoformat(),
        "source_url": "https://example.com/fundamentals",
        "raw": raw,
    }


def stamp(value):
    return datetime.fromisoformat(value).timestamp()


def test_provider_percentages_normalize_to_same_units():
    yahoo = normalize(snapshot(revenueGrowth=0.164, profitMargins=0.2762), NOW)
    finnhub = normalize(
        snapshot("finnhub", revenueGrowthQuarterlyYoy=16.4, netProfitMarginTTM=27.62), NOW
    )
    for key, expected in [("revenue_growth", 0.164), ("profit_margin", 0.2762)]:
        for result in [yahoo, finnhub]:
            assert result["fields"][key]["value"] == pytest.approx(expected)
            assert result["fields"][key]["display_percent"] == pytest.approx(expected * 100)
            assert result["fields"][key]["source_as_of"] is None
    assert finnhub["fields"]["revenue_growth"]["period"] == "quarterly_year_over_year"


def test_pe_missing_and_negative_values_remain_distinct():
    result = normalize(snapshot(trailingPE=-10, profitMargins=-0.2, revenueGrowth=0), NOW)
    fields = result["fields"]
    assert fields["pe"]["status"] == "not_meaningful"
    assert fields["pe"]["raw_value"] == -10
    assert fields["pe"]["value"] is None
    assert fields["forward_pe"]["status"] == "unavailable"
    assert fields["profit_margin"]["value"] == -0.2
    assert fields["revenue_growth"]["value"] == 0


def test_nonfinite_values_are_unavailable():
    result = normalize(snapshot(trailingPE=float("nan"), forwardPE=float("inf")), NOW)
    assert result["fields"]["pe"]["value"] is None
    assert result["fields"]["forward_pe"]["value"] is None


def test_estimated_upcoming_date_wins_over_past_release_timestamp():
    result = normalize(
        snapshot(
            earningsTimestamp=stamp("2026-07-30T20:00:00+00:00"),
            earningsTimestampStart=stamp("2026-10-29T20:00:00+00:00"),
            earningsTimestampEnd=stamp("2026-10-29T20:00:00+00:00"),
        ),
        NOW,
    )
    earnings = result["fields"]["next_earnings_date"]
    assert earnings["value"] == "2026-10-29"
    assert earnings["confirmation"] == "estimated_or_unconfirmed"


def test_earnings_range_is_not_claimed_as_exact_date():
    result = normalize(
        snapshot(
            earningsTimestampStart=stamp("2026-10-28T20:00:00+00:00"),
            earningsTimestampEnd=stamp("2026-10-30T20:00:00+00:00"),
        ),
        NOW,
    )
    field = result["fields"]["next_earnings_date"]
    assert field["value"] is None
    assert field["status"] == "date_range"
    assert (field["window_start"], field["window_end"]) == ("2026-10-28", "2026-10-30")


def test_earnings_dates_use_exchange_timezone_and_do_not_recycle_past_dates():
    result = normalize(
        snapshot(
            earningsTimestamp=stamp("2026-09-21T00:30:00+00:00"), isEarningsDateEstimate=False
        ),
        NOW,
    )
    assert result["fields"]["next_earnings_date"]["value"] == "2026-09-20"
    assert result["fields"]["next_earnings_date"]["confirmation"] == "provider_confirmed"
    old = normalize(snapshot(earningsTimestamp=stamp("2026-01-01T20:00:00+00:00")), NOW)
    assert old["fields"]["next_earnings_date"]["status"] == "unavailable"


def test_ttm_growth_not_substituted_for_missing_quarterly_growth():
    result = normalize(snapshot("finnhub", revenueGrowthTTMYoy=25), NOW)
    assert result["fields"]["revenue_growth"]["value"] is None


def test_earnings_window_that_has_started_is_retained_until_it_ends():
    result = normalize(
        snapshot(
            earningsTimestampStart=stamp("2026-09-18T20:00:00+00:00"),
            earningsTimestampEnd=stamp("2026-09-22T20:00:00+00:00"),
        ),
        NOW,
    )
    field = result["fields"]["next_earnings_date"]
    assert field["status"] == "date_range"
    assert field["value"] is None
    assert field["window_start"] == "2026-09-18"
