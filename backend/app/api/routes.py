from datetime import timedelta

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.models import RefreshRequest, WatchlistCreate, iso, symbol, utcnow
from app.services.fundamentals import normalize
from app.services.scoring import VERSION as SCORING_VERSION

router = APIRouter(prefix="/api")


def valid_ticker(ticker):
    try:
        return symbol(ticker)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


def tracked(request, ticker):
    ticker = valid_ticker(ticker)
    if ticker not in {x["ticker"] for x in request.app.state.store.watchlist()}:
        raise HTTPException(404, "Ticker is not on your watchlist")
    return ticker


@router.get("/health")
def health(request: Request):
    state = request.app.state
    return {
        "status": "ok",
        "phase": 6,
        "disclaimer": "Not financial advice. Research only.",
        "database": "connected",
        "watchlist_count": len(state.store.watchlist()),
        "scheduler_enabled": state.config.scheduler_enabled,
        "refresh_minutes": state.config.refresh_minutes,
        "active_refresh": state.ingestion.active_run_id,
        "finnhub_configured": bool(state.env.finnhub_api_key.get_secret_value()),
        "gemini": {
            "enabled": state.config.news_analysis.enabled,
            "configured": state.news_analysis.provider.configured,
            "model": state.config.news_analysis.model,
            "max_calls_per_day": state.config.news_analysis.max_calls_per_day,
        },
        "scoring": {
            "config_version": state.scoring.version,
            "scoring_version": SCORING_VERSION,
            "min_weight_coverage": state.scoring.min_weight_coverage,
        },
        "alerts": {
            "enabled": state.alert_rules.enabled,
            "rules": sorted(
                name for name in state.alert_rules.rules if state.alert_rules.rule(name)
            ),
            "unacknowledged": state.store.alerts(limit=1)["unacknowledged"],
            "brief_enabled": state.alert_rules.brief.enabled,
        },
        "telegram": "disabled; no client installed",
        "market": state.market.state(),
    }


@router.get("/watchlist")
def watchlist(request: Request):
    return {"items": request.app.state.store.watchlist()}


@router.post("/watchlist", status_code=201)
def add_watchlist(item: WatchlistCreate, request: Request, response: Response):
    try:
        added = request.app.state.store.add_ticker(
            item.ticker, item.company_name, request.app.state.config.max_watchlist_size
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    if not added:
        response.status_code = 200
    return {
        "ticker": item.ticker,
        "added": added,
        "note": "Symbol syntax validated. Provider coverage is checked during refresh.",
    }


@router.delete("/watchlist/{ticker}", status_code=204)
def remove_watchlist(ticker: str, request: Request):
    ticker = valid_ticker(ticker)
    if not request.app.state.store.remove_ticker(ticker):
        raise HTTPException(404, "Ticker is not on your watchlist")
    return Response(status_code=204)


@router.get("/tickers/{ticker}/quote")
def quote(ticker: str, request: Request):
    return request.app.state.ingestion.view(tracked(request, ticker), "quote")


@router.get("/tickers/{ticker}/history")
def history(ticker: str, request: Request, limit: int = Query(default=600, ge=1, le=2000)):
    return request.app.state.ingestion.view(tracked(request, ticker), "history", limit)


@router.get("/tickers/{ticker}/fundamentals")
def fundamentals(ticker: str, request: Request):
    """Raw provider fields plus normalized metrics, periods, units, and earnings date/window."""
    result = request.app.state.ingestion.view(tracked(request, ticker), "fundamentals")
    result["normalized"] = normalize(
        result["data"], timezone=request.app.state.config.market_timezone
    )
    result["normalized"]["cache_status"] = result["status"]
    return result


@router.get("/tickers/{ticker}/indicators")
def indicators(
    ticker: str,
    request: Request,
    include_series: bool = False,
    limit: int = Query(default=600, ge=1, le=2000),
):
    """Persisted daily technicals and normalized fundamentals. No provider calls or scoring."""
    return request.app.state.analysis.view(tracked(request, ticker), include_series, limit)


@router.get("/overview")
def overview(request: Request):
    """Market snapshot, watchlist scores, movers and analyzed headlines from cache only."""
    return request.app.state.overview.build()


@router.get("/news")
def news(
    request: Request,
    ticker: str | None = None,
    hours: int = Query(default=48, ge=1, le=168),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    include_assessments: bool = False,
):
    ticker = valid_ticker(ticker) if ticker else None
    result = request.app.state.store.news(
        iso(utcnow() - timedelta(hours=hours)), ticker, limit, offset
    )
    if include_assessments:
        # Articles with no stored assessment keep an explicit null, never a neutral guess.
        symbols = (
            [ticker] if ticker else [item["ticker"] for item in request.app.state.store.watchlist()]
        )
        assessments = request.app.state.store.latest_assessments(symbols)
        for article in result["items"]:
            article["assessment"] = assessments.get(article["id"])
        result["assessment_note"] = (
            "Sentiment and impact are AI interpretations of the linked article. "
            "A null assessment means the article was not analyzed, not that it is neutral."
        )
    statuses = [
        s
        for s in request.app.state.store.cache_status(ticker)
        if s["cache_key"].startswith("rss:") or ":news:" in s["cache_key"]
    ]
    symbols = [ticker] if ticker else [x["ticker"] for x in request.app.state.store.watchlist()]
    expected = {f"finnhub:news:{item}" for item in symbols}
    expected.update("rss:" + feed.url for feed in request.app.state.ingestion.feeds)
    present = {row["cache_key"] for row in statuses}
    statuses.extend(
        {
            "cache_key": key,
            "fetched_at": None,
            "expires_at": None,
            "attempted_at": None,
            "error": "not_yet_refreshed",
            "retry_at": None,
        }
        for key in sorted(expected - present)
    )
    result["provider_status"] = statuses
    now = utcnow()
    failures = [
        s
        for s in statuses
        if s["error"] or not s["expires_at"] or parse_expired(s["expires_at"], now)
    ]
    any_success = any(row["fetched_at"] for row in statuses)
    result["status"] = "unavailable" if not any_success else "partial" if failures else "cached"
    result["note"] = (
        "No matching articles is different from a failed provider; inspect provider_status."
    )
    return result


def parse_expired(value, now):
    from app.models import parse_time

    return parse_time(value) <= now


@router.get("/tickers/{ticker}/news-analysis")
def news_analysis(ticker: str, request: Request):
    """Cached Gemini analysis, verified citation IDs, coverage and freshness. No LLM calls."""
    return request.app.state.news_analysis.view(tracked(request, ticker))


@router.get("/tickers/{ticker}/news-analysis/{analysis_id}")
def news_analysis_snapshot(ticker: str, analysis_id: int, request: Request):
    """Immutable historical analysis and the exact article excerpts it used."""
    result = request.app.state.store.news_analysis(valid_ticker(ticker), analysis_id=analysis_id)
    if result is None:
        raise HTTPException(404, "News analysis not found")
    return {
        "historical": True,
        "data": result,
        "disclaimer": "Not financial advice. Historical analysis, not current news.",
    }


@router.get("/news-analysis/attempts")
def news_analysis_attempts(request: Request, ticker: str | None = None):
    """Recent sanitized API attempt status and token usage. Never credentials or raw errors."""
    return {"items": request.app.state.store.llm_attempts(valid_ticker(ticker) if ticker else None)}


class NewsAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tickers: list[str] | None = None


@router.post("/news-analysis", status_code=202)
async def analyze_news(body: NewsAnalysisRequest, request: Request):
    """Analyze cached news only. POST /api/refresh fetches fresh news and analyzes it too."""
    state = request.app.state
    watchlist = {x["ticker"] for x in state.store.watchlist()}
    tickers = (
        sorted({valid_ticker(t) for t in body.tickers})
        if body.tickers is not None
        else sorted(watchlist)
    )
    if not tickers or set(tickers) - watchlist:
        raise HTTPException(422, "Choose one or more tickers on your watchlist")
    run_id = state.ingestion.start(tickers, trigger="manual-analysis", analysis_only=True)
    if run_id is None:
        raise HTTPException(
            409,
            {"message": "A refresh is already running", "run_id": state.ingestion.active_run_id},
        )
    return {"run_id": run_id, "status": "running", "status_url": f"/api/refresh/{run_id}"}


@router.get("/tickers/{ticker}/score")
def score(ticker: str, request: Request):
    """Current composite score, full weighted breakdown, and caution flags. No provider calls."""
    return request.app.state.signals.view(tracked(request, ticker))


@router.get("/scores")
def scores(request: Request):
    """Watchlist ranked by current score. Tickers without enough data are listed last."""
    return request.app.state.signals.ranked()


@router.get("/scoring/config")
def scoring_config(request: Request):
    """The weights, curves, thresholds, and caution rules currently in effect."""
    return request.app.state.signals.config_view()


@router.get("/signals")
def signals(
    request: Request,
    ticker: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    include_outcomes: bool = True,
):
    """Append-only log of every recorded signal, newest first, with forward outcomes."""
    result = request.app.state.signals.history(
        valid_ticker(ticker) if ticker else None, limit, offset
    )
    if include_outcomes:
        request.app.state.performance.attach(result["items"])
        result["outcome_note"] = (
            "Forward returns are measured from stored daily closes. A horizon that has "
            "not elapsed stays pending; nothing is estimated."
        )
    return result


@router.get("/performance")
def performance(request: Request):
    """How recorded signals actually performed, grouped by label, with the caveats."""
    return request.app.state.performance.summary()


@router.get("/alerts")
def alerts(
    request: Request,
    unacknowledged_only: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
):
    """In-app alerts raised during refreshes. Reading them triggers no evaluation."""
    return request.app.state.alerts.view(unacknowledged_only, limit)


@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: int, request: Request):
    """Mark one alert read. The observation itself is never edited or deleted."""
    result = request.app.state.store.acknowledge_alert(alert_id)
    if result is None:
        raise HTTPException(404, "Alert not found")
    return result


@router.post("/alerts/acknowledge")
def acknowledge_alerts(request: Request):
    return {"acknowledged": request.app.state.store.acknowledge_all_alerts()}


@router.get("/daily-brief")
def daily_brief(request: Request):
    """The stored brief plus the current computed facts. Never calls the model."""
    return request.app.state.brief.view()


@router.get("/daily-brief/history")
def daily_brief_history(request: Request):
    return {"items": request.app.state.store.briefs()}


@router.post("/daily-brief", status_code=201)
async def write_daily_brief(request: Request):
    """Write today's brief from cached data. Unchanged inputs reuse the stored one."""
    result = await request.app.state.brief.build()
    if result["status"] in {"generated", "cached"}:
        return result | {"brief": request.app.state.store.brief(brief_id=result["brief_id"])}
    return JSONResponse(status_code=409 if result.get("error") else 422, content=result)


@router.get("/signals/{signal_id}")
def signal(signal_id: int, request: Request):
    """One immutable signal exactly as it was recorded, with the weights used at the time."""
    record = request.app.state.store.signal(signal_id)
    if record is None:
        raise HTTPException(404, "Signal not found")
    return {
        "historical": True,
        "data": record,
        "disclaimer": "Not financial advice. A past signal is a record of what the "
        "configured weights produced from the data available then.",
    }


@router.post("/refresh", status_code=202)
async def refresh(body: RefreshRequest, request: Request):
    state = request.app.state
    watchlist = {x["ticker"] for x in state.store.watchlist()}
    tickers = body.tickers if body.tickers is not None else sorted(watchlist)
    if set(tickers) - watchlist:
        raise HTTPException(422, "Add requested tickers to the watchlist before refreshing")
    if not tickers:
        raise HTTPException(422, "Watchlist is empty")
    run_id = state.ingestion.start(tickers, body.force)
    if run_id is None:
        raise HTTPException(
            409,
            {"message": "A refresh is already running", "run_id": state.ingestion.active_run_id},
        )
    return {"run_id": run_id, "status": "running", "status_url": f"/api/refresh/{run_id}"}


@router.get("/refresh")
def refresh_runs(request: Request):
    return {"items": request.app.state.store.runs()}


@router.get("/refresh/{run_id}")
def refresh_run(run_id: str, request: Request):
    run = request.app.state.store.run(run_id)
    if not run:
        raise HTTPException(404, "Refresh run not found")
    return run
