# Personal AI Stock Research Dashboard

**Not financial advice. Research only.** No brokerage connections or trading.

**[Live demo →](https://ziyangchua02.github.io/stocks/)** — the dashboard running
on a frozen snapshot of one local session. It has no backend and no API key: the
data is fixed at the moment it was captured, and anything that would fetch or
write is disabled. Run it locally for live data.

All six phases are implemented: a local FastAPI data service with SQLite
caching, technical/fundamental indicators, Gemini news analysis with source
links, a configurable composite score recorded as append-only signals, a React
dashboard over all of it, and in-app alerts, a daily brief, and forward
performance tracking for every recorded signal. The initial watchlist is AAPL,
NVDA, and MSFT. Telegram is disabled; alerts are in-app only.

## Run locally (macOS / Linux, Python 3.12+)

From the project root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.lock
.venv/bin/python -m pip install --no-deps -e ./backend
```

If `.env` does not already exist, copy `.env.example` to `.env`. Keep existing
credentials when updating configuration. Set `FINNHUB_API_KEY` for company news
and market data fallbacks. Set `GEMINI_API_KEY` for news analysis. No Telegram
credentials are needed; leave `TELEGRAM_ENABLED=false`.

```sh
.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --workers 1
```

Then start the dashboard in a second terminal:

```sh
cd frontend && npm install && npm run dev
```

Open **http://localhost:5173** for the dashboard, or
**http://127.0.0.1:8000/docs** for the interactive API. Its description
includes the research disclaimer. Use one worker: a process lock prevents two
instances from scheduling refreshes against the same database.

Trigger the initial fetch, including outside market hours:

```sh
curl -X POST http://127.0.0.1:8000/api/refresh \
  -H 'Content-Type: application/json' -d '{}'
```

The response is HTTP 202 with a `run_id` and `status_url`. Follow that URL or
`GET /api/refresh` until the run is `completed`, `partial`, or `failed`. A
`partial` run preserves successful data and reports each unavailable provider.
Initial history fetching can take a few minutes when providers retry.

For subsequent refreshes, valid caches are reused. `{"force":true}` bypasses
market-data cache lifetimes but still respects rate-limit cooldowns. Unchanged
news inputs always reuse their AI analysis, including with `force`. Overlapping refresh
requests return HTTP 409 with the active run ID. Reads never call providers.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Status, market session, provider configuration (no keys) |
| GET | `/api/overview` | Market snapshot, watchlist scores, movers and analyzed headlines |
| GET / POST | `/api/watchlist` | List or add tickers |
| DELETE | `/api/watchlist/{ticker}` | Remove ticker; retain historical cached data |
| GET | `/api/tickers/{ticker}/quote` | Latest cached quote and freshness |
| GET | `/api/tickers/{ticker}/history?limit=600` | Daily OHLCV and adjusted close |
| GET | `/api/tickers/{ticker}/fundamentals` | Raw fields plus normalized metrics and earnings date/window |
| GET | `/api/tickers/{ticker}/indicators` | Persisted technicals and normalized fundamentals with freshness |
| GET | `/api/news?ticker=AAPL&hours=48` | Deduplicated news, source links and provider status |
| GET | `/api/news?include_assessments=true` | The same feed with each article's stored AI assessment or an explicit null |
| GET | `/api/tickers/{ticker}/news-analysis` | Cached Gemini summary, sentiment, impact, risks, citations and coverage |
| GET | `/api/tickers/{ticker}/news-analysis/{analysis_id}` | Immutable historical output and its exact input excerpts |
| POST | `/api/news-analysis` | Analyze already-cached news for all or selected watchlist tickers |
| GET | `/api/news-analysis/attempts?ticker=AAPL` | API attempt status, sanitized failures and token usage |
| GET | `/api/tickers/{ticker}/score` | Current composite score, weighted breakdown and caution flags |
| GET | `/api/scores` | Watchlist ranked by current score; unscored tickers listed last |
| GET | `/api/scoring/config` | Weights, curves, thresholds and caution rules in force |
| GET | `/api/signals?ticker=AAPL` | Append-only log of every recorded signal |
| GET | `/api/signals/{signal_id}` | One immutable signal with the weights used at the time |
| GET | `/api/performance` | Forward outcomes grouped by label, with sample-size caveats |
| GET | `/api/alerts` | In-app alerts, newest first; `unacknowledged_only=true` to filter |
| POST | `/api/alerts/{id}/acknowledge` | Mark one alert read; the observation is unchanged |
| POST | `/api/alerts/acknowledge` | Mark every alert read |
| GET / POST | `/api/daily-brief` | Read the stored brief and current facts, or write today's |
| GET | `/api/daily-brief/history` | Previously written briefs |
| POST | `/api/refresh` | Start refresh of all or selected watchlist tickers |
| GET | `/api/refresh` | Latest refresh runs and per-provider results |
| GET | `/api/refresh/{run_id}` | Poll one refresh |

Add a ticker with `{"ticker":"AMZN","company_name":"Amazon"}`. A company
name helps match general RSS stories. Syntax is checked immediately; provider
coverage is checked on refresh. Refresh selected tickers with
`{"tickers":["AAPL"],"force":false}`. News supports `limit` and `offset`.

## Indicators (Phase 2)

Open `/api/tickers/AAPL/indicators` for the current snapshot. Add
`?include_series=true&limit=200` for chart-ready historical SMA, RSI, MACD,
and volume values. Indicators are computed during refresh and backfilled from
existing cache at startup. Reading them makes no external calls.

Included: SMA(20/50/200), Wilder RSI(14), MACD(12/26/9), volume against the prior
20-session average, the 52-week high/low and signed distances, trailing/forward
P/E, quarterly YoY revenue growth, TTM profit margin, and the next earnings
date or estimated window. All technicals use completed daily bars, not a live
partial session. Each metric includes units, source, observation session or
reporting period, retrieval time, and missing-data reasons.

See [indicator methods and API conventions](INDICATORS.md). New inputs create
persisted indicator snapshots; unchanged inputs reuse the existing snapshot.
Schema migration 2 adds these tables without replacing Phase 1 data.

## News analysis (Phase 3)

Normal refreshes now analyze news after ingestion. To analyze existing cached
articles without fetching market data, use:

```sh
curl -X POST http://127.0.0.1:8000/api/news-analysis \
  -H 'Content-Type: application/json' -d '{"tickers":["AAPL","NVDA","MSFT"]}'
```

Poll the returned `status_url`, then open `/api/tickers/AAPL/news-analysis`.
The six requested fields are in `data.payload`: `summary`, `sentiment`, `impact`,
`time_horizon`, `key_points`, and `risks`. Its `claims` object pairs each text or
classification explanation with original article URLs. `article_assessments`
adds sentiment, impact, rationale, and source per selected article. All remain
model interpretations that need human review; citation validation checks source
identity, not the factual correctness of the reasoning.

The default analyzes the **12 newest deduplicated articles in the last 48 hours
that explicitly mention the ticker or company** in the headline or excerpt,
using up to 1,200 characters of each excerpt. It does not fetch full articles.
`coverage` reports total, excluded, eligible, selected, and omitted counts, and
`warnings` reports truncated excerpts or stale/incomplete news retrieval.
Older but important news can be omitted by this cap; tune it in
`config/settings.yaml`. General articles without a direct mention stay in the
news feed but are excluded from AI input to avoid inventing company connections.
This conservative matching can also miss relevant context. There is no
fabricated sentiment when analysis is missing.

Only public news excerpts and ticker/company context go to Google. Keys stay in
backend headers. The configured model is `gemini-3.1-flash-lite`; availability,
quotas and any billing depend on your Google project. Local limits cap calls at
100 attempts per UTC day, 6 seconds apart, with at most 2 attempts on transient
network/server failures. Failed requests count too. Google's free tier is not
enforced by this local cap; check your project plan in AI Studio.

Identical selected inputs, model, schema and prompt reuse the saved result across
restarts. A new selected article or configuration change requires a new analysis.
Expired articles cannot be presented as current. Failed or rate-limited analysis
keeps prior output under `previous_analysis`; `data` is null if it does not match
current inputs. Reads and startup never trigger Gemini. See [NEWS_ANALYSIS.md](NEWS_ANALYSIS.md)
for provenance, validation and failure behavior.

## Scoring and signals (Phase 4)

Every refresh scores each ticker from the indicator snapshot and news analysis
it just persisted, then records the result. Reads recompute from cache and call
no provider and no model.

```sh
curl -s http://127.0.0.1:8000/api/scores            # ranked watchlist
curl -s http://127.0.0.1:8000/api/tickers/AAPL/score # full breakdown
curl -s http://127.0.0.1:8000/api/signals            # append-only log
```

A 0–100 composite combines seven weighted components: trend, momentum, volume,
52-week range position, valuation, growth and quality, and news sentiment.
Continuous inputs pass through piecewise-linear curves; the curve, the input
value, its source and its sub-score are returned for every number, and each
component reports its configured weight, effective weight and contribution.

Components without data are excluded and the remaining weights renormalized,
never filled with a neutral value. If the available components cover less than
`min_weight_coverage` of total weight, no score is produced: the response
reports `insufficient_data` and the coverage achieved. News sentiment is scaled
by the analysis's impact rating and is not scored once the analysis passes
`max_age_hours`.

Labels are "Strong setup", "Watch", "Neutral", and "Caution", from configurable
thresholds. Separate caution flags carry their own evidence — stale inputs,
negative medium/high-impact news, overbought RSI, extension above the 200-day
average, earnings within a week, and thin weight coverage. A flag can lower a
label to Caution but never raises one.

Signals are append-only. Each row keeps its score, label, full breakdown, the
weights and thresholds in force, the caution flags, the indicator snapshot and
news analysis IDs, and the reference session and close, so editing weights later
cannot rewrite earlier records. Identical inputs, configuration and session
reuse the existing record; a completed session, a newly analyzed article or an
edited `config/scoring.yaml` creates a new one. Intraday quotes are excluded
from that identity so 15-minute refreshes do not fill the log with duplicates.
The reference close is what the 1-week and 1-month performance measurement uses
as its starting point.

Tune `config/scoring.yaml` and restart. Invalid weights, unordered label
thresholds, and non-ascending curves are rejected at startup. See
[scoring methods, flags and limitations](SCORING.md), including why the volume
component has no direction and why these weights are preferences rather than
fitted parameters. Schema migration 4 adds the `signals` table without altering
Phase 1–3 data.

## Dashboard (Phase 5)

`npm run dev` in `frontend/` serves the React interface on
**http://localhost:5173** and proxies `/api` to the backend, so the page is
same-origin and no key reaches the browser. Six pages: **Overview** (indices,
ranked watchlist, movers, analyzed headlines, watchlist editing), **Ticker
detail** (price chart with SMA overlays, RSI and MACD panels, score breakdown,
AI summary with source links, bull vs bear), **News feed** (filter by ticker,
sentiment and impact), **Daily brief**, **Alerts** (with an unread count in the
header), and **Signal log** (every recorded score with the weights used at the
time and its forward outcomes).

The "Not financial advice" disclaimer is fixed below the header on every page.
Reads never call a provider; the header's **Refresh data** button runs the same
refresh the scheduler does and reloads when it finishes.

Missing data is stated rather than filled in: nulls render as `—` with the
backend's reason, an unanalyzed article is never shown as neutral sentiment, and
every figure carries its own observation time and freshness word. Every AI claim
renders with the article links stored beside it. See
[dashboard pages, chart decisions and limitations](DASHBOARD.md).

Index quotes for the market snapshot come from Yahoo with no fallback provider;
configure them under `market_indices` in `config/settings.yaml`.

## Alerts, daily brief and performance (Phase 6)

Each refresh evaluates alert rules against the data it just stored: a score
crossing a threshold, a score or label change, a price move beyond a percentage,
or high-impact analyzed news. Every alert carries the measured value, the
threshold it crossed and a link to the signal, quote or article behind it.
Alerts are append-only and deduplicated, so repeating a refresh never raises the
same one twice, and acknowledging one records that it was read without editing
the observation. Delivery is in-app only; no Telegram client is installed.

```sh
curl -s http://127.0.0.1:8000/api/alerts
curl -s -X POST http://127.0.0.1:8000/api/daily-brief   # one model call
curl -s http://127.0.0.1:8000/api/performance
```

The daily brief summarizes the last 24 hours. Every figure in it is computed
locally — score changes against the last signal from before the window, closing
moves from stored bars, alerts raised — and the model only writes the wording
around those numbers. A news-based note must cite a supplied article, which is
resolved to a real link from SQLite; a market-data note must cite none. Output
using unknown citations, unknown tickers or certainty language is rejected and
not stored. Unchanged inputs reuse the stored brief, and an empty period is
reported rather than described.

Every recorded signal is measured forward from its reference session close to
the first completed session on or after 1 week and 1 month, using stored bars
only. A horizon that has not elapsed stays pending with the date it becomes
measurable, and where index history exists each outcome also shows the benchmark
return and the excess. `GET /api/performance` groups these by label and leads
with a verdict that says plainly when the sample is too small to claim anything,
which it will be for some time. Tune thresholds in `config/alerts.yaml`. See
[alert rules, brief provenance and performance caveats](ALERTS_AND_BRIEF.md).

## Data and scheduling

- Yahoo Finance via yfinance supplies regular-session quotes, two years of daily
  bars, and raw fundamentals. Finnhub provides fallback quotes, fundamentals,
  and daily candles when the account has endpoint access. Candle access may
  require a paid plan; inaccessible data is reported, never synthesized.
- Finnhub company news and public CNBC/MarketWatch RSS excerpts cover the last
  48 hours. Feeds are fetched once per refresh and matched to company names or
  tickers. Matching is a conservative text heuristic, not semantic analysis.
  Undated articles are skipped and counted. Paywalled full text is not fetched.
- URLs lose known tracking parameters for deduplication. Matching headlines on
  the same UTC day are also deduplicated. All associated ticker and source links
  are retained. Older news stays archived but is excluded from the default feed.
- Each quote has `source_as_of` and `fetched_at`. Each article has `published_at`
  and `fetched_at`. Daily bars have a `session_date` and a timestamp explicitly
  labelled `session_label`, not an exact trade time. Incomplete daily bars are
  flagged. Fundamentals have no fabricated common observation time: their raw
  reporting dates remain available and `source_as_of` is null.
- Quote freshness uses the most recent expected market session, so Friday's
  closing quote is not automatically stale on Saturday. During open sessions,
  tolerance is the refresh interval plus five minutes. `cache_expired` is
  distinct from an outdated market observation. Provider failures remain visible.
- APScheduler checks every 15 minutes, using the NYSE calendar in
  `America/New_York` (holidays, early closes, daylight saving). It refreshes only
  during regular hours plus the closing tick. Manual refresh works at any time.
  The application must remain running and the computer awake. Startup serves
  cache without a network refresh unless `refresh_on_startup` is enabled.
- Request timeouts, bounded retries with backoff, provider-wide rate-limit
  cooldowns, and a Finnhub request budget limit repeated calls. Failed refreshes
  retain previous data and do not relabel it with a new observation timestamp.
- Free provider access and a 15-minute polling interval do not guarantee real-time
  prices. Market delays and unavailable fields are surfaced explicitly.

Tune intervals and cache lifetimes in `config/settings.yaml`; feeds are in
`config/feeds.yaml`, scoring weights in `config/scoring.yaml`, and alert
thresholds in `config/alerts.yaml`. Restart after configuration changes. `DATABASE_PATH` in
`.env` can override the default database location. The default database is
`data/research.sqlite3` (WAL mode); source response caches and quote/fundamental
snapshots persist. Daily bar corrections update stored bars; recorded
signals are never rewritten.

## The published demo

GitHub Pages serves static files, so it cannot run the FastAPI backend, the
SQLite database, the scheduler, or hold an API key. The published page is
therefore the real dashboard bundled in **demo mode**: reads come from the JSON
in `frontend/public/demo-data`, captured from a local run, and every action that
would fetch or write is disabled behind a banner saying the data is frozen.

Refresh the snapshot after a local run, then push:

```sh
.venv/bin/python scripts/capture_demo_snapshot.py   # backend must be running
cd frontend && VITE_DEMO=true npm run build         # what Pages builds
```

The capture script only reads endpoints, and refuses to write a file whose
response mentions a credential field. `.env` is git-ignored and no key appears in
any committed file. Publishing the backend itself would need authentication
first: the API has none, so anyone with the URL could trigger refreshes and spend
your model quota.

`.github/workflows/pages.yml` rebuilds and deploys the demo on every push to
`main` that touches `frontend/`; `.github/workflows/tests.yml` runs the backend
and frontend test suites, which need no network access or keys.

## Verification

```sh
.venv/bin/python -m pytest backend/tests -q
.venv/bin/ruff check backend
cd frontend && npm test && npm run build
```

Tests use temporary databases and mocked providers: no real keys or network calls.
They cover watchlist persistence, cache expiry, retained data on failure, provider
fallbacks, news deduplication, timestamps, rate limits, refresh concurrency, and
holiday/half-day/DST scheduling, numerical indicator reference cases, gap and
warm-up handling, fundamental unit/date normalization, curve interpolation,
weight renormalization, withheld scores below minimum coverage, caution flags
and label downgrades, signal immutability and deduplication, forward-return
measurement and pending horizons, alert thresholds and deduplication, and
rejection of uncited or overconfident brief output.
`backend/requirements.lock` records the exact
dependency versions used for verification. The frontend tests cover the
formatting and derivation helpers: placeholders for missing values, the
freshness vocabulary, the bull/bear split, and filters that never treat an
unanalyzed article as neutral.

See [the Phase 1 verification report](PHASE1_VERIFICATION.md) for the live data,
browser, restart, and provider access checks completed on September 20, 2026.
The [Phase 2 report](PHASE2_VERIFICATION.md) covers indicator calculations,
57 passing tests, migration, and browser/API verification. The
[Phase 4 report](PHASE4_VERIFICATION.md) covers live scoring of the three
watchlist tickers, signal immutability across a weight change, and 119 passing
tests. The [Phase 5 report](PHASE5_VERIFICATION.md) covers the dashboard
rendered in both themes against live data, the watchlist round trip, and 125
backend plus 13 frontend tests. The [Phase 6 report](PHASE6_VERIFICATION.md)
covers a live alert, a generated brief with resolved citations, pending forward
outcomes, and 145 backend plus 18 frontend tests.

## Layout and remaining phases

- `config/`: application, RSS and scoring configuration.
- `backend/app/api/`: routes and request validation.
- `backend/app/db/`: SQLite repository and packaged SQL migrations.
- `backend/app/providers/`: Yahoo, Finnhub, RSS, and Gemini adapters.
- `backend/app/services/`: ingestion, caching, indicators, validated news
  analysis, composite scoring, and signal records.
- `backend/app/prompts/`: versioned news prompt included in the package.
- `backend/app/jobs/`: exchange session calendar.
- `backend/tests/`: isolated backend tests.
- `frontend/src/`: React dashboard — `api/` client, `hooks/`, `lib/` helpers
  with unit tests, `components/`, `charts/`, and `pages/`.
- `data/`: local SQLite files, provider caches, and verification artifacts (Git ignored).

All six planned phases are complete. Natural next steps, none of them started:
longer signal history before the performance page means anything, a second
opinion on news from another model, and per-ticker alert thresholds.

Source API references: [yfinance](https://ranaroussi.github.io/yfinance/),
[Finnhub](https://finnhub.io/docs/api),
[APScheduler](https://apscheduler.readthedocs.io/en/3.x/userguide.html),
[market calendars](https://pandas-market-calendars.readthedocs.io/en/latest/usage.html).
