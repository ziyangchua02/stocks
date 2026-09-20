# Dashboard (Phase 5)

**Not financial advice.** The disclaimer is fixed below the header on every page.
Nothing in the interface is a recommendation to buy or sell, and no page can
place a trade: the browser only ever talks to the local backend.

## Running it

Start the backend first, then the dev server:

```sh
.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --workers 1
cd frontend && npm install && npm run dev     # http://localhost:5173
```

Vite proxies `/api` to `127.0.0.1:8000`, so the page is same-origin and no key
ever reaches the browser. `npm run build` emits a static bundle in
`frontend/dist`; `npm test` runs the unit tests.

**Refresh data** in the header starts the same `POST /api/refresh` the scheduler
uses, polls the run, and reloads when it finishes. Every other view reads cache
only, so browsing never calls a provider or the model.

## Pages

**Overview** — index quotes for the configured indices, the watchlist ranked by
score with each label and coverage, the biggest movers within the watchlist, the
most important analyzed headlines, and watchlist add/remove. Tickers that could
not be scored are listed separately with the reason rather than sorted to the
bottom silently.

**Ticker detail** — quote, score, last close and next earnings as stat tiles;
the price chart with its moving-average overlays; RSI and MACD panels; the full
score breakdown; the AI news summary with source links; and a bull/bear split.

**News feed** — every stored article for the chosen window, filterable by
ticker, sentiment and impact, 25 at a time. Each article shows publisher,
publication time and retrieval time, and either its AI assessment or an explicit
"this article was not analyzed".

**Signal log** — the append-only record of every score, with the weights in
force at the time, each row's 1-week and 1-month outcome, and a grouped summary
that states when the sample is too small to mean anything. A horizon that has
not elapsed reads "pending" with the date it becomes measurable.

**Daily brief** — one button writes a summary of the last 24 hours. The figures
beside every note are the locally computed ones the model was given, and a
news-based note carries its article links.

**Alerts** — threshold crossings raised during refreshes, each with its measured
value, the threshold and a link to the record behind it. The header carries an
unread count.

## Rules the interface follows

- **Missing data is stated, never filled in.** A null renders as `—` with the
  backend's reason beside it. An unanalyzed article is never shown as neutral
  sentiment, and a filter on sentiment or impact matches only articles that
  actually have an assessment.
- **Every figure carries its own time.** Each panel shows a status word plus a
  glyph and the age of the observation, using one vocabulary throughout:
  `cached`, `stale`, `unavailable`, `partial`.
- **Every AI claim links to its article.** The summary, each key point, each
  risk and each per-article assessment render with their source links, taken
  from the backend's stored citations rather than from the model's text.
- **The bull and bear split restates evidence already on the page**: model key
  points versus risks, and scoring components either side of the neutral 50
  midpoint, plus the caution flags. It adds no new judgement, and components
  with no data appear on neither side.
- **A failed load replaces the panel.** Stale content is never left on screen
  looking current.

## Chart decisions

Charts follow the project's data-visualization rules; the palette was validated
for both themes with the colorblind-separation and contrast checks before use.

- **Price chart**: four lines (close plus SMA 20/50/200), 2px, with a legend and
  a crosshair tooltip. Two of the four light-mode hues sit below 3:1 contrast on
  the surface, so a **Show values** table of the most recent 30 sessions is
  available as the documented relief. Missing indicator values stay gaps, so the
  200-day average simply starts where it becomes computable.
- **RSI** is a single series, so it carries no legend box; reference lines mark
  the 30 and 70 levels the scoring curve bends around.
- **MACD** is drawn as the histogram alone — a quantity either side of zero, so
  a diverging bar rather than a third overlaid line — with the MACD and signal
  values in the tooltip. Nothing uses a second y-axis anywhere.
- **Score contributions** are one hue, since they are a magnitude comparison,
  with each value labelled and unavailable components keeping their row and
  showing the reason instead of a zero-length bar.
- **Sentiment** is polarity, so it reads as a diverging bar from a neutral
  centre, always beside the numeric value and the impact word.
- **Labels and statuses never rely on color.** Every chip carries its text, and
  every freshness marker carries a word and a glyph.
- Chart animation is off: a partly drawn line reads as missing data.

Light and dark are two selected palettes defined as CSS custom properties, each
stepped for its own surface, not an automatic inversion. The theme follows the
system setting unless overridden in the header.

## Known limitations

- Movers are computed across the watchlist only. This is not a market-wide scan,
  and the panel says so.
- The news feed loads the newest 200 articles in the window and says when more
  are stored.
- Indices come from Yahoo with no fallback provider; an index that fails to
  fetch shows as unavailable rather than being hidden.
- The interface is built for one local user on one machine. It has no
  authentication and should not be exposed beyond localhost.
