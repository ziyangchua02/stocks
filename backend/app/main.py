import asyncio
import fcntl
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.db.store import Store
from app.jobs.market import MarketClock
from app.providers.common import Http
from app.providers.finnhub import Finnhub
from app.providers.gemini import Gemini
from app.providers.rss import RSS
from app.providers.yahoo import Yahoo
from app.services.alerts import Alerts
from app.services.brief import Brief
from app.services.ingestion import Ingestion
from app.services.news_analysis import NewsAnalysis
from app.services.overview import Overview
from app.services.performance import Performance
from app.services.signals import Signals
from app.settings import (
    AlertsConfig,
    Config,
    Environment,
    ScoringConfig,
    load_alerts,
    load_config,
    load_feeds,
    load_scoring,
)

LOCAL_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]


def create_app(
    env: Environment | None = None,
    config: Config | None = None,
    providers=None,
    gemini_provider=None,
    scoring: ScoringConfig | None = None,
    alerts: AlertsConfig | None = None,
):
    @asynccontextmanager
    async def lifespan(app):
        settings = env or Environment()
        configuration = config or load_config()
        weights = scoring or load_scoring()
        alert_rules = alerts or load_alerts()
        settings.database_path.parent.mkdir(parents=True, exist_ok=True)
        lock = settings.database_path.with_suffix(".lock").open("a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            raise RuntimeError(
                "Another backend is using this database. Run one worker only."
            ) from None
        http = None
        ingestion = None
        scheduler = None
        gemini = None
        try:
            store = Store(settings.database_path)
            store.initialize(configuration.seed_watchlist)
            market = MarketClock(configuration.market_calendar, configuration.market_timezone)
            if providers is None:
                http = Http(configuration)
                yahoo = Yahoo(
                    configuration, market, settings.database_path.parent / "yfinance-cache"
                )
                finnhub = Finnhub(
                    settings.finnhub_api_key.get_secret_value(), http, market, configuration
                )
                rss = RSS(http, configuration)
                feeds = load_feeds()
            else:
                yahoo, finnhub, rss, feeds = providers
            gemini = gemini_provider or Gemini(
                settings.gemini_api_key.get_secret_value(), configuration.news_analysis
            )
            news_analysis = NewsAnalysis(store, configuration, gemini, feeds)
            ingestion = Ingestion(
                store, configuration, market, yahoo, finnhub, rss, feeds, news_analysis
            )
            signals = Signals(
                store, configuration, weights, ingestion.analysis, news_analysis, market
            )
            ingestion.signals = signals
            alert_service = Alerts(store, configuration, alert_rules)
            ingestion.alerts = alert_service
            performance = Performance(store, configuration)
            brief = Brief(store, configuration, alert_rules, gemini, signals)
            overview = Overview(store, configuration, market, ingestion, signals)
            for name, value in {
                "store": store,
                "market": market,
                "env": settings,
                "config": configuration,
                "scoring": weights,
                "ingestion": ingestion,
                "analysis": ingestion.analysis,
                "news_analysis": news_analysis,
                "signals": signals,
                "overview": overview,
                "alert_rules": alert_rules,
                "alerts": alert_service,
                "performance": performance,
                "brief": brief,
            }.items():
                setattr(app.state, name, value)

            # Backfill indicators and score from existing SQLite data. No provider or LLM
            # call happens at startup; scoring reads only what is already cached.
            for item in store.watchlist():
                await asyncio.to_thread(ingestion.analysis.build, item["ticker"])
                await asyncio.to_thread(signals.build, item["ticker"])

            async def scheduled_refresh():
                if market.should_refresh():
                    tickers = [x["ticker"] for x in store.watchlist()]
                    if tickers:
                        # Closing tick must replace an intraday daily bar even inside its TTL.
                        ingestion.start(
                            tickers, force=not market.state()["is_open"], trigger="scheduler"
                        )

            if configuration.scheduler_enabled:
                scheduler = AsyncIOScheduler(timezone=configuration.market_timezone)
                scheduler.add_job(
                    scheduled_refresh,
                    "cron",
                    minute=f"*/{configuration.refresh_minutes}",
                    second=0,
                    id="market-refresh",
                    max_instances=1,
                    coalesce=True,
                    misfire_grace_time=45,
                )
                scheduler.start()
            if configuration.refresh_on_startup:
                tickers = [x["ticker"] for x in store.watchlist()]
                if tickers:
                    ingestion.start(tickers, trigger="startup")
            yield
        finally:
            if scheduler:
                scheduler.shutdown(wait=False)
            if ingestion:
                await ingestion.close()
            if http:
                await http.close()
            if gemini:
                await gemini.close()
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()

    app = FastAPI(
        title="Personal Stock Research — Phase 6",
        version="0.6.0",
        lifespan=lifespan,
        description="Not financial advice. Research only. Cached data, no trading. "
        "Read endpoints never trigger provider calls. POST /api/refresh to fetch data. "
        "Scores summarize cached inputs and are not predictions.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=LOCAL_ORIGINS,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )

    @app.middleware("http")
    async def local_mutations(request: Request, call_next):
        origin = request.headers.get("origin")
        if (
            request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and origin
            and origin not in LOCAL_ORIGINS
        ):
            return JSONResponse(status_code=403, content={"detail": "Origin is not allowed"})
        return await call_next(request)

    app.include_router(router)

    @app.get("/")
    def index():
        return {
            "name": "Personal Stock Research",
            "phase": 6,
            "docs": "/docs",
            "disclaimer": "Not financial advice. Research only.",
        }

    return app


app = create_app()
