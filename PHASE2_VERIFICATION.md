# Phase 2 verification — September 20, 2026

The user can read daily technicals and normalized fundamentals from SQLite,
inspect their methods and provenance, and retrieve historical chart values.

| Boundary | Result | Evidence |
| --- | --- | --- |
| Existing data → schema 2 | Pass | Additive migration preserved 3 tickers, 1,503 bars, 6 raw snapshots, and 280 articles |
| Cached inputs → calculations | Pass | All 13 technical values available for AAPL, NVDA, and MSFT |
| Normalized fundamentals | Pass | Trailing/forward P/E, quarterly YoY revenue growth, TTM profit margin, and earnings dates available for all three |
| Calculations → SQLite | Pass | Three persisted indicator snapshots with input hashes and calculation versions |
| SQLite → browser API | Pass | All three indicator endpoints returned HTTP 200 and 200 requested chart points |
| Refresh integration | Pass | A normal refresh completed; all three indicator snapshots returned `cached` with their original IDs |
| Documentation browser | Pass | Phase 2 `/docs` and indicator endpoint rendered; no page errors reported |
| Database integrity | Pass | `PRAGMA integrity_check` returned `ok` |

## Data context

The latest completed market session was Friday, September 18, 2026. Technicals
use that session's completed daily bars, even though the API also offers quotes.
Each ticker has 501 cached daily bars; indicator values use the available warm-up
history before truncating the chart response to the requested limit.

Provider earnings dates were returned as October 29 (AAPL), November 17 (NVDA),
and October 28 (MSFT), 2026. They are explicitly marked estimated or unconfirmed;
they are not represented as company-confirmed announcements.

A read-only Finnhub AAPL fundamentals request verified that the fallback supplies
`peTTM`, `forwardPE`, `revenueGrowthQuarterlyYoy`, and `netProfitMarginTTM`.
Its percentage values are normalized to fractions with raw values retained.

## Automated verification

57 tests passed. New cases cover:

- Reference Wilder RSI values and rising, falling, and flat-price edge cases.
- SMA values and MACD/EMA initialization on analytically solvable series.
- Volume baselines excluding the measured session and zero-volume denominators.
- 52 calendar weeks of daily highs/lows and signed distance formulas.
- Missing-session resets, short histories, invalid/future/incomplete bars,
  incompatible sources, and no use of future data in earlier chart points.
- Provider units, negative or missing P/E, negative margins, and zero growth.
- Earnings timezone conversion, estimated windows, overlapping windows, and
  avoiding past earnings dates or substituting a different growth period.
- Schema migration, persistent snapshots, unchanged-input reuse, read-time
  staleness, and API reads without provider calls.

Ruff and compilation checks passed. Two upstream deprecation warnings from the
FastAPI/Starlette test client remain non-blocking, as in Phase 1.

A pre-migration backup is retained at `data/research.before-phase2.sqlite3`.
Screenshot: `data/phase2-docs.png`. Method details: [INDICATORS.md](INDICATORS.md).

The local backend remains at http://127.0.0.1:8000/docs. Gemini analysis, scoring,
the React dashboard, and alerts have not been implemented in this phase.
Gemini and Telegram were not called.
