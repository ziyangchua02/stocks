import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.jobs.market import MarketClock
from app.main import create_app
from app.models import Bar, Quote, iso, utcnow
from app.services.alerts import Alerts
from app.services.brief import Brief
from app.services.performance import Performance, forward
from app.settings import AlertsConfig, Environment, Index
from tests.conftest import FakeProvider, refresh_and_wait


@pytest.fixture
def alert_rules():
    return AlertsConfig.model_validate(
        {
            "enabled": True,
            "rules": {
                "score_threshold": {"enabled": True, "crosses_above": 70, "crosses_below": 42},
                "score_change": {"enabled": True, "minimum_change": 8},
                "label_change": {"enabled": True},
                "price_move": {"enabled": True, "percent": 4},
                "high_impact_news": {
                    "enabled": True,
                    "impacts": ["high"],
                    "minimum_abs_sentiment": 0.3,
                },
            },
            "brief": {"enabled": True, "lookback_hours": 24},
        }
    )


def record_signal(store, ticker, score, label, session="2026-09-18", close=100.0):
    payload = {
        "ticker": ticker,
        "scoring_version": "composite-v1",
        "config_version": "scoring-v1",
        "computed_at": iso(),
        "score": score,
        "label": label,
        "status": "scored",
        "weight_coverage": 1.0,
        "cautions": [],
        "inputs": {"indicator_as_of_session": session, "last_close": close},
    }
    return store.save_signal(payload, f"hash-{ticker}-{score}-{session}", "config-hash")


def save_quote(store, ticker, price, previous):
    store.save_snapshot(
        "quote",
        Quote(
            ticker=ticker,
            price=price,
            previous_close=previous,
            change=price - previous,
            change_percent=(price / previous - 1) * 100,
            source="yfinance",
            source_url="https://example.com/quote",
            source_as_of=utcnow(),
            fetched_at=utcnow(),
        ).model_dump(mode="json"),
    )


def save_bars(store, ticker, start, closes):
    market = MarketClock()
    sessions = market.sessions(
        date.fromisoformat(start), date.fromisoformat(start) + timedelta(days=90)
    )
    rows = []
    for day, close in zip(sessions, closes, strict=False):
        rows.append(
            Bar(
                ticker=ticker,
                session_date=day,
                open=close,
                high=close * 1.01,
                low=close * 0.99,
                close=close,
                adjusted_close=close,
                volume=1000,
                source="yfinance",
                source_url="https://example.com/history",
                source_as_of=market.bar_label(day),
                fetched_at=utcnow(),
                is_complete=True,
                adjustment="test",
            ).model_dump(mode="json")
        )
    store.save_bars(rows)
    return [row["session_date"] for row in rows]


# --- performance ------------------------------------------------------------


def test_forward_uses_first_session_on_or_after_the_horizon():
    prices = {"2026-09-18": 100.0, "2026-09-25": 110.0, "2026-09-28": 120.0}
    result = forward(prices, "2026-09-18", 100.0, 7, "2026-09-28")
    assert result["status"] == "measured"
    assert result["observed_session"] == "2026-09-25"
    assert result["return_percent"] == pytest.approx(10.0)
    assert result["sessions_after_target_days"] == 0


def test_forward_reports_a_later_session_when_the_horizon_date_has_no_bar():
    prices = {"2026-09-18": 100.0, "2026-09-28": 120.0}
    result = forward(prices, "2026-09-18", 100.0, 7, "2026-09-28")
    assert result["observed_session"] == "2026-09-28"
    assert result["sessions_after_target_days"] == 3
    assert "3 day(s) after" in result["note"]


def test_forward_stays_pending_rather_than_estimating():
    prices = {"2026-09-18": 100.0, "2026-09-21": 105.0}
    result = forward(prices, "2026-09-18", 100.0, 30, "2026-09-21")
    assert result["status"] == "pending"
    assert "return_percent" not in result
    assert "2026-09-21" in result["reason"]


def test_outcomes_measure_excess_against_the_benchmark(store, config):
    config.market_indices = [Index(symbol="^GSPC", name="S&P 500")]
    sessions = save_bars(store, "AAPL", "2026-06-01", [100 + i for i in range(40)])
    save_bars(store, "^GSPC", "2026-06-01", [1000 + i for i in range(40)])
    reference = sessions[0]
    signal_id, _ = record_signal(
        store, "AAPL", 75.0, "Strong setup", session=reference, close=100.0
    )
    performance = Performance(store, config)
    rows = performance.attach(store.signals("AAPL")["items"])
    week = rows[0]["outcomes"]["1_week"]
    assert week["status"] == "measured"
    assert week["benchmark_symbol"] == "^GSPC"
    # The ticker rises 1 per session from 100, the index 1 per session from 1000,
    # so the ticker's percentage gain is much larger.
    assert week["excess_return_percent"] > 0
    assert week["return_percent"] > week["benchmark_return_percent"]
    assert signal_id


def test_summary_refuses_to_claim_predictive_value_on_a_small_sample(store, config):
    save_bars(store, "AAPL", "2026-06-01", [100 + i for i in range(40)])
    record_signal(store, "AAPL", 75.0, "Strong setup", session="2026-06-01", close=100.0)
    summary = Performance(store, config).summary()
    assert summary["sufficient_sample"] is False
    assert "Not enough recorded outcomes" in summary["verdict"]
    assert len(summary["caveats"]) >= 4
    assert summary["groups"][0]["label"] == "Strong setup"
    assert summary["groups"][0]["horizons"]["1_week"]["measured"] == 1


# --- alerts -----------------------------------------------------------------


def test_score_crossing_needs_an_earlier_signal(store, config, alert_rules):
    alerts = Alerts(store, config, alert_rules)
    record_signal(store, "AAPL", 75.0, "Strong setup", session="2026-09-18")
    # The first recorded score has nothing to cross from.
    assert [row["rule"] for row in alerts.evaluate("AAPL")] == []
    record_signal(store, "AAPL", 60.0, "Watch", session="2026-09-17")
    record_signal(store, "AAPL", 78.0, "Strong setup", session="2026-09-19")
    rules = {row["rule"] for row in alerts.evaluate("AAPL")}
    assert "score_threshold" in rules and "label_change" in rules


def test_alerts_are_not_duplicated_across_refreshes(store, config, alert_rules):
    alerts = Alerts(store, config, alert_rules)
    save_quote(store, "AAPL", 110.0, 100.0)
    first = alerts.evaluate("AAPL")
    second = alerts.evaluate("AAPL")
    assert [row["rule"] for row in first] == ["price_move"]
    assert second == []
    assert store.alerts()["total"] == 1


def test_price_alert_carries_its_threshold_and_source(store, config, alert_rules):
    save_quote(store, "AAPL", 110.0, 100.0)
    Alerts(store, config, alert_rules).evaluate("AAPL")
    alert = store.alerts()["items"][0]
    assert alert["rule"] == "price_move" and alert["severity"] == "attention"
    assert alert["evidence"]["threshold"] == 4
    assert alert["evidence"]["change_percent"] == pytest.approx(10.0)
    assert alert["evidence"]["source_url"].startswith("https://")
    assert alert["acknowledged_at"] is None


def test_disabled_rules_raise_nothing(store, config, alert_rules):
    alert_rules.rules["price_move"].enabled = False
    save_quote(store, "AAPL", 110.0, 100.0)
    assert Alerts(store, config, alert_rules).evaluate("AAPL") == []
    alert_rules.enabled = False
    alert_rules.rules["price_move"].enabled = True
    assert Alerts(store, config, alert_rules).evaluate("AAPL") == []


def test_acknowledging_keeps_the_observation(store, config, alert_rules):
    save_quote(store, "AAPL", 110.0, 100.0)
    Alerts(store, config, alert_rules).evaluate("AAPL")
    alert_id = store.alerts()["items"][0]["id"]
    acknowledged = store.acknowledge_alert(alert_id)
    assert acknowledged["acknowledged_at"] and acknowledged["changed"] is True
    assert acknowledged["title"] == store.alerts()["items"][0]["title"]
    assert store.alerts()["unacknowledged"] == 0
    assert store.acknowledge_alert(alert_id)["changed"] is False
    assert store.acknowledge_alert(999999) is None


# --- daily brief ------------------------------------------------------------


class FakeBriefModel:
    configured = True

    def __init__(self, result=None):
        self.calls = []
        self.result = result

    async def generate(self, instruction, prompt, schema):
        self.calls.append(json.loads(prompt))
        facts = self.calls[-1]["facts"]
        ticker = facts["tickers"][0]["ticker"]
        payload = self.result or {
            "headline": f"{ticker} score moved on new inputs.",
            "overview": "One watchlist ticker changed; the rest were unchanged.",
            "notes": [
                {
                    "ticker": ticker,
                    "what_changed": "The recorded score moved by the amount in the figures.",
                    "why": "The supplied figures show the change; the cause is not identifiable.",
                    "basis": "market_data",
                    "source_ids": [],
                }
            ],
            "watch_items": ["Next earnings date in the supplied facts."],
        }
        return {"text": json.dumps(payload), "usage": {"totalTokenCount": 10}}


def brief_service(store, config, alert_rules, model):
    return Brief(store, config, alert_rules, model, None)


def test_brief_uses_local_figures_and_stores_them(store, config, alert_rules):
    record_signal(store, "AAPL", 60.0, "Watch", session="2026-09-17")
    record_signal(store, "AAPL", 75.0, "Strong setup", session="2026-09-18")
    save_bars(store, "AAPL", "2026-09-14", [100, 104])
    model = FakeBriefModel()
    service = brief_service(store, config, alert_rules, model)

    import asyncio

    result = asyncio.run(service.build())
    assert result["status"] == "generated"
    stored = store.brief(brief_id=result["brief_id"])
    figures = stored["payload"]["notes"][0]["figures"]
    assert figures["score"] == 75.0
    assert figures["close_change_percent"] == pytest.approx(4.0)
    # The model never supplies numbers: the prompt carries them and the record keeps them.
    assert model.calls[0]["facts"]["tickers"][0]["score_change"] == pytest.approx(15.0)
    assert stored["payload"]["disclaimer"].startswith("Not financial advice")


def test_brief_rejects_an_uncited_news_claim(store, config, alert_rules):
    record_signal(store, "AAPL", 60.0, "Watch", session="2026-09-17")
    record_signal(store, "AAPL", 75.0, "Strong setup", session="2026-09-18")
    model = FakeBriefModel(
        {
            "headline": "Apple moved on reported news.",
            "overview": "A news-based explanation without a citation.",
            "notes": [
                {
                    "ticker": "AAPL",
                    "what_changed": "The score rose.",
                    "why": "Coverage was positive.",
                    "basis": "news",
                    "source_ids": [],
                }
            ],
            "watch_items": [],
        }
    )
    import asyncio

    result = asyncio.run(brief_service(store, config, alert_rules, model).build())
    assert result == {"status": "unavailable", "error": "invalid_brief_output"}
    assert store.brief() is None


def test_brief_rejects_certainty_language(store, config, alert_rules):
    record_signal(store, "AAPL", 60.0, "Watch", session="2026-09-17")
    record_signal(store, "AAPL", 75.0, "Strong setup", session="2026-09-18")
    model = FakeBriefModel(
        {
            "headline": "Apple will rise from here.",
            "overview": "A confident claim about future prices.",
            "notes": [],
            "watch_items": [],
        }
    )
    import asyncio

    result = asyncio.run(brief_service(store, config, alert_rules, model).build())
    assert result["error"] == "invalid_brief_output"


def test_brief_is_not_written_about_an_empty_period(store, config, alert_rules):
    import asyncio

    model = FakeBriefModel()
    result = asyncio.run(brief_service(store, config, alert_rules, model).build())
    assert result["status"] == "insufficient_data"
    assert not model.calls


def test_unchanged_inputs_reuse_the_stored_brief(store, config, alert_rules):
    import asyncio

    record_signal(store, "AAPL", 60.0, "Watch", session="2026-09-17")
    record_signal(store, "AAPL", 75.0, "Strong setup", session="2026-09-18")
    model = FakeBriefModel()
    service = brief_service(store, config, alert_rules, model)
    first = asyncio.run(service.build())
    second = asyncio.run(service.build())
    assert second == {"status": "cached", "brief_id": first["brief_id"]}
    assert len(model.calls) == 1


# --- API --------------------------------------------------------------------


@pytest.fixture
def phase6_client(tmp_path, config):
    env = Environment(
        _env_file=None,
        database_path=tmp_path / "phase6.sqlite3",
        finnhub_api_key="test-key",
        gemini_api_key="unused",
    )
    providers = (FakeProvider(), FakeProvider("finnhub"), None, [])
    with TestClient(create_app(env, config, providers)) as client:
        yield client


def test_refresh_evaluates_alerts_and_exposes_them(phase6_client):
    run = refresh_and_wait(phase6_client)
    assert run["results"]["tickers"]["AAPL"]["alerts"]["status"] == "evaluated"
    body = phase6_client.get("/api/alerts").json()
    assert "in-app only" in body["delivery"]
    assert "Not financial advice" in body["disclaimer"]
    assert set(body["rules_enabled"]) >= {"price_move", "score_threshold"}


def test_signals_carry_outcomes_and_performance_summary(phase6_client):
    refresh_and_wait(phase6_client)
    signals = phase6_client.get("/api/signals").json()
    assert "outcome_note" in signals
    for signal in signals["items"]:
        for horizon in signal["outcomes"].values():
            assert horizon["status"] in {"pending", "measured", "unavailable"}
    summary = phase6_client.get("/api/performance").json()
    assert summary["sufficient_sample"] is False
    assert summary["horizons"] == {"1_week": 7, "1_month": 30}
    assert (
        phase6_client.get("/api/signals?include_outcomes=false").json()["items"][0].get("outcomes")
        is None
    )


def test_alert_acknowledgement_endpoints(phase6_client):
    store = phase6_client.app.state.store
    save_quote(store, "AAPL", 110.0, 100.0)
    phase6_client.app.state.alerts.evaluate("AAPL")
    alert_id = phase6_client.get("/api/alerts").json()["items"][0]["id"]
    assert phase6_client.post(f"/api/alerts/{alert_id}/acknowledge").status_code == 200
    assert phase6_client.get("/api/alerts?unacknowledged_only=true").json()["items"] == []
    assert phase6_client.post("/api/alerts/999999/acknowledge").status_code == 404
    assert phase6_client.post("/api/alerts/acknowledge").json()["acknowledged"] == 0


def test_daily_brief_endpoint_reports_missing_brief_without_calling_the_model(phase6_client):
    body = phase6_client.get("/api/daily-brief").json()
    assert body["data"] is None
    assert body["status"] in {"unavailable", "disabled"}
    assert body["current_facts"]["tickers"][0]["ticker"] == "AAPL"
    assert "Not financial advice" in body["disclaimer"]


def test_health_reports_alert_configuration(phase6_client):
    body = phase6_client.get("/api/health").json()
    assert body["phase"] == 6
    assert body["alerts"]["enabled"] is True
    assert body["alerts"]["unacknowledged"] >= 0
    assert body["telegram"] == "disabled; no client installed"
