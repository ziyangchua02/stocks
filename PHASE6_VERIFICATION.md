# Phase 6 verification — alerts, daily brief, signal performance

Completed September 20, 2026 against the live database at
`data/research.sqlite3` and the local backend on port 8000.

**Not financial advice.** The outputs quoted below show the mechanism working,
not research conclusions.

## Automated checks

```sh
.venv/bin/python -m pytest backend/tests -q   # 145 passed
.venv/bin/ruff check backend                  # All checks passed
cd frontend && npm test                       # 18 passed
cd frontend && npm run build                  # built, no errors
```

Phase 6 adds 20 backend tests and 5 frontend tests covering forward-return
measurement (including a horizon that lands on a non-trading day), pending
horizons that are never estimated, benchmark excess return, the refusal to claim
predictive value on a small sample, alert thresholds needing an earlier signal to
cross, alert deduplication across refreshes, disabled rules, acknowledgement that
preserves the observation, and brief output rejected for an uncited news claim or
for certainty language.

## Migration

The live database moved from `user_version` 4 to 5 on startup, adding `alerts`
and `daily_briefs`. Existing tables and rows were untouched.

## Alerts on live data

A refresh with the shipped 4% price threshold raised no alerts, which was
correct: no watchlist ticker had moved that far and no score had changed. To
verify the rule end to end rather than only in tests, `price_move.percent` was
temporarily lowered to 1 and a refresh run. That raised one alert from real data:

> **NVDA moved 1.34% up** — The cached quote is 1.34% against its previous close,
> at or beyond the configured 1.00% threshold. Observed at 2026-09-18T20:00:00Z.

The stored evidence carried `change_percent 1.34`, `threshold 1.0`, the price,
the previous close, and the Yahoo source URL and observation time. The threshold
has been restored to 4 in `config/alerts.yaml`. **That one alert remains in the
database and records `threshold: 1.0` in its own evidence**, so it is
self-documenting rather than inconsistent with the current configuration.

In the browser, marking it read moved the counter from "1 unread of 1 recorded"
to "0 unread of 1 recorded", the unread filter then showed the empty state, and
the alert itself remained listed with its acknowledgement time.

## Daily brief on live data

`POST /api/daily-brief` produced a brief in one model call. Its figures match the
records exactly — for example AAPL "The score decreased by 4.90 to 77.39", which
is the move from the 82.29 recorded before the Phase 4 caution-rule change to the
current 77.39.

Each note behaved as designed: the AAPL note declared `basis: market_data` and
cited no article, saying the cause was not identifiable from the figures; the
MSFT and NVDA notes declared `basis: both` and carried resolved links to CNBC and
Yahoo articles. No note used certainty language, and `tickers_without_a_note` was
empty. The page shows the locally computed figures beside every note and, in a
separate table, the full fact set the model was given.

## Performance tracking

Index history is now fetched alongside index quotes: 501 daily bars for each of
`^GSPC`, `^IXIC` and `^DJI`, giving the benchmark for excess returns.

All nine recorded signals reference session 2026-09-18, so both horizons are
still in the future. Every outcome correctly reads **pending** with the date it
becomes measurable, and `GET /api/performance` reports 0 measured outcomes across
9 signals with the verdict:

> Not enough recorded outcomes to say anything about predictive value. Treat
> these numbers as a record of what happened, not as evidence.

Measured returns, non-trading-day horizons and benchmark excess are covered by
tests with synthetic bars, since no horizon has elapsed in live data yet.

## Screenshots

`docs/screenshots/phase6-alerts.png`, `docs/screenshots/phase6-brief.png`, `docs/screenshots/phase6-signals.png`.
All three pages were loaded in both themes with no console or page errors.

## Problems found and fixed during verification

1. **The signal log still said outcome tracking "arrives in Phase 6"** in the API
   note and the page text after the feature shipped. Both now describe the
   measurement.
2. **Pending rows repeated a long sentence in every cell**, making the table hard
   to scan. A pending outcome now reads "pending · from `<date>`", with the full
   explanation in the cell's tooltip.
3. **The daily brief computed no change at all on a fresh window**, because it
   only compared against a signal older than the window and a new database has
   none. It now falls back to the earliest signal inside the window and states
   that basis on the row, rather than reporting "no change".
4. **`number()` was used as a formatter** in alert text, where it only coerces
   values. Alerts now use a local formatter, so a missing figure reads "unknown"
   instead of raising.

## Not verified

- Measured (rather than pending) forward returns on live data; the first
  horizon elapses on 2026-09-25.
- Whether the scoring predicts anything. That question stays open by design, and
  the performance page will keep saying so until each label group holds at least
  30 signals.
- Telegram delivery, which is not installed. In-app alerts are the only channel,
  matching `TELEGRAM_ENABLED=false`.
- Long-run alert volume. With three tickers and a 4% threshold, alerts will be
  rare; a larger watchlist may need per-ticker thresholds.
