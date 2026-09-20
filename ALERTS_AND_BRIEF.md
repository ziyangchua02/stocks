# Alerts, daily brief, and signal performance (Phase 6)

**Not financial advice.** An alert reports that a threshold you configured was
crossed in cached data. A brief describes changes the system already computed.
Neither is a recommendation, and the performance page exists to test the scoring,
not to defend it.

## Alerts

Alerts are evaluated during each refresh, from data that refresh just stored. No
alert calls a provider or the model. Rules live in `config/alerts.yaml`:

| Rule | Fires when | Default |
| --- | --- | --- |
| `score_threshold` | The score crosses a threshold from one side to the other | above 70, below 42 |
| `score_change` | The score moves at least this many points since the previous signal | 8 points |
| `label_change` | The label differs from the previous signal's | on |
| `price_move` | The cached quote differs from its previous close by at least this much | 4% |
| `high_impact_news` | An analyzed article in the news window is rated at this impact and sentiment | high impact, abs sentiment 0.3 |

Every alert stores the measured value, the threshold it crossed, and a link to
the record behind it: the signal, the quote, or the article. A crossing needs an
earlier signal to cross from, so the first score recorded for a ticker never
fires one.

Alerts are append-only and deduplicated by a natural key, so repeating a refresh
does not raise the same alert twice. The keys are the signal ID for score and
label rules, the quote's observation time for price moves, and the article ID for
news. Acknowledging an alert records that it was read; it never edits or deletes
the observation.

**Delivery is in-app only.** No Telegram client is installed and
`TELEGRAM_ENABLED` stays false, matching the rest of the project. Adding a
channel later means a sender module reading the same `alerts` table; nothing in
the rules depends on the delivery method.

## Daily brief

`POST /api/daily-brief`, or the **Write brief** button, summarizes what changed
over the configured window (24 hours by default).

The division of labour matters: **every number comes from local records**, and
the model only writes the wording around them. The service computes score
changes against the last signal from before the window, closing-price changes
from stored bars, alerts raised, and which articles were analyzed. That JSON,
plus the article headlines and IDs, is what the model receives. It is never
asked for a figure.

Each note declares its basis. A `news` or `both` note must cite at least one
supplied article ID, which is resolved to a real link from SQLite; a
`market_data` note must cite none, because it rests on the figures shown beside
it. Output is rejected if it cites an unknown article, names a ticker outside the
supplied facts, or uses certainty language. A rejected brief is not stored.

Identical inputs reuse the stored brief, so clicking twice does not spend a
second model call. A brief is not written for an empty period: if nothing changed
and nothing was analyzed, the API says so instead of generating filler. Briefs
share the same daily call budget and provider cooldown as news analysis.

## Signal performance

Each recorded signal is measured forward from its reference session close to the
first completed session on or after the horizon date, at 1 week and 1 month. The
measurement uses stored daily bars only.

- A horizon that has not elapsed, or whose bars have not been downloaded, stays
  **pending** with the date it becomes measurable. Nothing is estimated.
- When the horizon date is not a trading day, the first later session is used and
  the row says how many days late it was.
- Where index bars exist, the outcome also carries the benchmark's return over
  the same window and the excess. The benchmark is the first entry in
  `market_indices`, currently `^GSPC`, whose daily history is fetched alongside
  its quote.

`GET /api/performance` groups outcomes by label. It leads with a verdict, and
while any group holds fewer than 30 signals that verdict says plainly that there
is not enough evidence to claim predictive value. The caveats travel with the
numbers:

- A recorded signal is not a trade: no entry rule, position size, costs, or exit.
- Signals for the same ticker on consecutive sessions overlap, so their returns
  are not independent.
- The watchlist is self-selected and changes, so this is not a survivorship-free
  sample.
- Excess return uses one index and no risk adjustment.
- No significance test is applied, so differences between labels may be noise.

## What this cannot tell you

The performance page answers "what happened after signals like this one?" for a
handful of tickers over a short history. It cannot establish that the scoring
works, and a favourable average over a few weeks of a rising market is not
evidence that it does. Changing weights starts a new population of signals rather
than re-scoring old ones, so honest comparison across weight changes needs enough
records under each version.
