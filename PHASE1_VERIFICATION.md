# Phase 1 verification — September 20, 2026

The user can request a watchlist refresh through the local API, fetch market
data and news, save it in SQLite, and read those results after restarting.

| Boundary | Result | Evidence |
| --- | --- | --- |
| Browser documentation | Pass | `/docs` renders the disclaimer and all API operations; no page errors reported |
| Browser → API | Pass | Browser POST to `/api/refresh` returned HTTP 202 and a run ID |
| API → providers | Pass | Yahoo quotes, history, and raw fundamentals; Finnhub news; both RSS feeds fetched successfully |
| Providers → SQLite | Pass | 1,503 daily bars, six quote/fundamental snapshots, 280 deduplicated news articles |
| SQLite → API | Pass | Quotes, histories, news, and refresh results returned successfully for all three tickers |
| Repeated refresh | Pass | All resources and feeds returned `cached`; no duplicate snapshots created |
| Restart persistence | Pass | Same watchlist, 501 bars per ticker, 280 articles, and two completed refresh runs after restart |
| SQLite integrity | Pass | `PRAGMA integrity_check` returned `ok` |

## Live dataset

| Ticker | Daily bars | Latest session | Quote source | Fundamentals |
| --- | ---: | --- | --- | --- |
| AAPL | 501 | 2026-09-18 | yfinance | Available, raw provider fields |
| NVDA | 501 | 2026-09-18 | yfinance | Available, raw provider fields |
| MSFT | 501 | 2026-09-18 | yfinance | Available, raw provider fields |

Verification occurred on Sunday. Quotes and daily histories refer to Friday's
session, and the market calendar correctly reports the exchange as closed.
Article totals are a snapshot of the rolling 48-hour feed and will change.

## Finnhub account access

Read-only AAPL endpoint checks confirmed that the configured key can retrieve
quotes and basic financials. The candle endpoint returned an access restriction.
Yahoo supplies history; when Yahoo is unavailable and Finnhub denies candle
access, the service preserves old history or reports it unavailable. No paid
subscription was added.

## Automated checks

- 32 tests passed using isolated databases and mock providers.
- Ruff checks and Python compilation passed.
- Dependency consistency check passed; versions are recorded in
  `backend/requirements.lock` (Python 3.12+).
- Source files were checked for accidental copies of the configured API keys;
  no copies were found. `.env` retains owner-only permissions.
- Tests emitted two upstream deprecation warnings from the FastAPI/Starlette
  test client. These did not affect the test results or live requests.

Holiday, daylight-saving, half-day, cooldown, fallback, and failure cases are
covered by automated tests. The real exchange was closed during verification,
so an automatic live market-hours tick was not observed.

Gemini and Telegram were not called. Indicator calculation, scoring, the React
dashboard, alerts, daily briefs, and signal performance remain for later phases.
