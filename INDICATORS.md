# Phase 2 indicator conventions

These are descriptive calculations, not predictions or financial advice.
The API contains no opportunity score, trade instruction, or AI-generated claim.

## Technicals

Calculations use completed exchange sessions on the configured NYSE calendar.
The close, high, and low share the provider's price adjustment basis. Yahoo
OHLC is split-adjusted; the separate dividend-adjusted close is not used here.
This keeps the moving averages, latest close, and 52-week range comparable.
The chosen basis and source are included in every technical snapshot.

| Field | Definition | Minimum consecutive sessions |
| --- | --- | ---: |
| `sma20`, `sma50`, `sma200` | Arithmetic mean of the last N daily closes, including the measured session | 20 / 50 / 200 |
| `rsi14` | Wilder RSI using 14 price changes | 15 |
| `macd` | EMA(12) minus EMA(26) of closes | 26 |
| `macd_signal` | EMA(9) of valid MACD observations | 34 |
| `macd_histogram` | MACD minus signal | 34 |
| `volume_average20` | Mean volume of the prior 20 sessions, excluding the measured session | 21 |
| `volume_ratio20` | Measured session volume / prior 20-session mean | 21 |
| `high52w`, `low52w` | Maximum daily high / minimum daily low over 52 calendar weeks | Full window |
| `distance_from_high52w_pct` | `100 * (latest close / high52w - 1)` | Full window |
| `distance_from_low52w_pct` | `100 * (latest close / low52w - 1)` | Full window |

Each EMA begins with a simple-average seed, then uses `alpha = 2 / (N + 1)`.
RSI begins with the average gain and loss over 14 changes, then updates each
average as `(previous_average * 13 + current_gain_or_loss) / 14`.
RSI is `100 - 100 / (1 + average_gain / average_loss)`.
All-gain and all-loss series return 100 and 0. A completely flat series returns
50 by an explicitly chosen neutral convention, avoiding a division by zero.

The 52-week interval is `(latest_session - 364 days, latest_session]`.
Its expected session count comes from the exchange calendar, rather than
assuming 252 days. An incomplete window produces null values with an explanation.
The range uses daily highs/lows, not just closing prices. Distances use the
latest completed close and are expressed in percentage points, not fractions.

Missing sessions restart rolling and recursive calculations; they are never
forward-filled. Invalid OHLCV, unfinished sessions, future sessions, and
non-trading dates are excluded. Insufficient history yields null values, not
zero or an average over a shorter period. Zero prior volume makes the volume
ratio unavailable. Chart points use only data available through their own session.
These choices can differ from chart packages using different EMA seeds,
dividend adjustment, calendar windows, or warm-up histories.

## Fundamentals

The raw provider response remains available from `/fundamentals`; the
`normalized` object and the combined `/indicators` endpoint use these conventions:

| Field | Unit | Period / handling |
| --- | --- | --- |
| `pe` | Multiple | Trailing twelve months; non-positive values are `not_meaningful` |
| `forward_pe` | Multiple | Provider's forward estimate; not a realized earnings figure |
| `revenue_growth` | Fraction | Quarterly year-over-year growth |
| `profit_margin` | Fraction | Trailing twelve months net profit margin |
| `next_earnings_date` | ISO exchange-local date | Provider date or estimated window |

For example, `0.164` revenue growth means 16.4%; `display_percent` exposes
that display value. Yahoo supplies fractional rates. Finnhub's
`revenueGrowthQuarterlyYoy` and `netProfitMarginTTM` are divided by 100.
TTM growth is not substituted for quarterly growth. Negative growth/margins and
zero growth are valid data; missing values stay null. Every normalized field
retains its provider field name, raw numeric value, unit, period, and provenance.

Yahoo may supply a past `earningsTimestamp` alongside future
`earningsTimestampStart` / `earningsTimestampEnd`. The future window is used
when present. A multi-day range stays a range (`value: null`, `status: date_range`)
instead of inventing a single date. Windows overlapping today remain visible
until their end date. Dates use `America/New_York`, and are marked
`estimated_or_unconfirmed` unless the provider explicitly marks them confirmed.
Past dates are not projected into the next quarter. Finnhub basic metrics do
not supply an earnings calendar; that field is unavailable on this fallback.

Provider fields can have different reporting periods. `source_as_of: null`
means no common publication/observation timestamp was supplied; `source_fetched_at`
is retrieval time, not an invented statement publication time.

## Freshness, persistence, and API

- `/api/tickers/AAPL/indicators` returns the latest persisted summary.
- Add `?include_series=true&limit=200` to include the last 200 chart points.
  Full history is used for calculations before the response is truncated.
- A calculation version and input hash identify each snapshot. A new snapshot
  is saved when inputs or date/session context change. Unchanged refreshes do
  not duplicate snapshots. Summary values remain archived; the chart series
  cache stores only the latest snapshot to limit database growth.
- Freshness is evaluated when reading: technicals are stale when a newer
  completed market session is expected. Fundamental cache age is shown
  separately from its unknown publication time. A date that passes while the
  server is idle is marked expired on the next read.
- A metric being `available` means it was calculable; it does not imply current
  data. Inspect its `freshness` and the response-level status as well.
- Provider failures stay visible under `provider_status`. Read endpoints never
  fetch providers or generate new research signals.

These snapshots are descriptive indicator records. Immutable scoring inputs,
opportunity labels, and prospective performance evaluation will be implemented
in Phases 4 and 6; no historical AI backtest is implied.

Formula references: [Fidelity RSI](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/RSI),
[StockCharts Wilder initialization](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/relative-strength-index-rsi),
[Fidelity MACD](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/macd).
