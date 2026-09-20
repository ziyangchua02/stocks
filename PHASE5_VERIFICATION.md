# Phase 5 verification — React dashboard

Completed September 20, 2026 against the live database at
`data/research.sqlite3` and the local backend on port 8000.

**Not financial advice.** The figures below are evidence that the interface
renders real cached data, not research conclusions.

## Automated checks

```sh
.venv/bin/python -m pytest backend/tests -q   # 125 passed
.venv/bin/ruff check backend                  # All checks passed
cd frontend && npm test                       # 13 passed
cd frontend && npm run build                  # built, no errors
```

Phase 5 adds six backend tests for the new endpoints — the overview makes no
provider calls, index quotes are fetched and reported with freshness, a missing
index is reported rather than omitted, movers rank and count gaps, news
assessments attach or stay explicitly null, and headlines include only analyzed
articles — plus 13 frontend unit tests over the formatting and derivation
helpers.

## Rendered and checked in a browser

All four pages were loaded in Chromium at 1440×1100 in both light and dark
themes and inspected: `docs/screenshots/phase5-overview.png`, `docs/screenshots/phase5-ticker.png` and
`docs/screenshots/phase5-signals.png`. No console or page errors in either theme.

- **Overview** showed the three configured indices (S&P 500 7,650.50, Nasdaq
  26,522.55, Dow 51,682.64, each with its own observation time), the watchlist
  ranked NVDA 80.4 / AAPL 77.4 / MSFT 72.6 with labels and 100% coverage, the
  movers panel, and eight analyzed headlines each with sentiment, impact, the
  model name, generation time and a link to the article.
- **Ticker detail** for NVDA and AAPL showed the price chart with all four
  overlays, RSI with its 30/70 references, the MACD histogram either side of
  zero, the seven-component score breakdown summing to the composite, the AI
  summary with source links and its three coverage warnings, and the bull/bear
  split.
- **News feed** showed filters, pagination and per-article assessments, with
  unanalyzed articles reading "No sentiment: this article was not analyzed."
- **Signal log** showed the nine recorded signals including the three from
  before the Phase 4 caution-rule change, each with the weights version, and the
  1-week and 1-month columns reading "not tracked yet".

Interaction was exercised, not just rendered: the price chart's **Show values**
table opened with the most recent 30 sessions, and a ticker was added through
the watchlist form and removed again, with the list updating both times.

## Problems found and fixed during verification

1. **Charts drew axes but no lines.** Recharts writes colors as SVG presentation
   attributes, where a raw `var(--series-1)` does not paint. Series colors are
   now resolved from the computed style and re-read when the theme changes, so
   both palettes stay selected rather than one being an inverted copy.
2. **Lines looked truncated** in captures because the draw animation was still
   running. Animation is now off: on a dashboard that redraws after every
   refresh, a partly drawn line reads as missing data.
3. **The same ticker appeared as both a gainer and a loser** on a three-ticker
   watchlist, because the movers panel took the top three and bottom three of
   one sorted list. Gainers and losers are now split by the sign of the change,
   and unchanged tickers are listed separately.
4. **The news feed rendered all 200 articles at once** in a single 30,000-pixel
   scroll. It now loads 25 at a time and states how many of the stored articles
   are shown.
5. **Legend text wore the series color.** Text now uses an ink token, with the
   colored key beside it carrying identity.

## Palette validation

The categorical slots used for the price overlays were checked with the
project's palette validator against each theme's own surface: light passes the
lightness band, chroma floor, colorblind separation (worst adjacent ΔE 9.1) and
normal-vision floor (22.9), with a contrast warning on two hues; dark passes all
five checks. The documented relief for that warning — a table of the plotted
values — ships on the price chart.

## Not verified

- Any predictive value of the scores. The signal log's outcome columns are
  deliberately empty until Phase 6 measures them.
- Behavior on a large watchlist. Everything here ran with three tickers; the
  overview issues one scoring pass per ticker per request.
- Cross-browser and mobile rendering. Only Chromium at desktop widths was
  checked.
- Alerts and the daily brief, which are Phase 6 and are not present in the
  interface.
