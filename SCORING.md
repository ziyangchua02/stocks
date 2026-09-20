# Composite scoring and signal records (Phase 4)

**Not financial advice.** A score is a weighted summary of the inputs listed
below. It is not a prediction, a recommendation, or a measure of expected
return. Whether this scoring has any predictive value is untested; the signal
log and `GET /api/performance` exist so it can be measured rather than assumed,
and they will say there is not enough evidence until there is.

## How a score is produced

Scoring is deterministic and offline. It reads the indicator snapshot and the
stored news analysis that earlier phases already persisted, and calls no
provider and no model. `GET` endpoints recompute from cache; they never fetch.

1. Each component turns its inputs into a 0–100 sub-score.
2. Components are combined using the weights in `config/scoring.yaml`.
3. Components without data are excluded and the remaining weights are
   renormalized, so a missing input is never treated as neutral.
4. If the available components cover less than `min_weight_coverage` of total
   weight, no score is produced at all: `status` is `insufficient_data` and the
   reason states the coverage achieved.
5. Caution flags are evaluated separately from the score.
6. The label comes from the configured thresholds, then a downgrading flag can
   lower it to "Caution". A flag never raises a label.

Continuous inputs are mapped through piecewise-linear curves given as
`[input, sub_score]` points, clamped outside their first and last point. The
curve used is returned with every sub-score, so any number in the dashboard can
be traced back to the input value and the rule applied to it.

## Components and default weights

| Component | Weight | Inputs |
| --- | --- | --- |
| `trend` | 0.20 | Close against SMA(20/50/200) and SMA ordering; the share of available checks that hold |
| `momentum` | 0.15 | RSI(14); MACD histogram as a percent of the last close |
| `volume` | 0.05 | Latest session volume against the prior 20-session average |
| `range_position` | 0.10 | Position of the last close within the 52-week range, 0 at the low and 100 at the high |
| `valuation` | 0.15 | Trailing P/E; forward P/E discount, `100 * (1 - forward / trailing)` |
| `growth_quality` | 0.15 | Quarterly year-over-year revenue growth; trailing twelve-month profit margin |
| `news_sentiment` | 0.20 | Model sentiment from the ticker's news analysis, scaled by its impact rating |

Technicals use completed daily sessions only, never a live partial bar, so a
score changes when a session completes rather than tick by tick. Fundamentals
keep the period labels described in [INDICATORS.md](INDICATORS.md): forward P/E
is a provider estimate, not a reported result.

News sentiment is pulled toward neutral 50 by the impact factor
(`low` 0.4, `medium` 0.7, `high` 1.0), so a low-impact story cannot dominate the
composite. An analysis older than `max_age_hours` is reported but not scored.
The sentiment sub-score carries its `analysis_id`; the article links behind it
are on `/api/tickers/{ticker}/news-analysis`.

## Labels

`Strong setup` at 70 and above, `Watch` at 58, `Neutral` at 42, and `Caution`
below that. Thresholds are configurable and must decrease in that order. No
label asserts certainty, and no output uses words such as guaranteed or
risk-free; a test enforces this on generated text.

## Caution flags

| Flag | Fires when | Lowers label |
| --- | --- | --- |
| `stale_indicators` | Price or fundamental inputs are stale or missing | yes |
| `stale_news` | News analysis is stale or missing, so its weight was excluded | no |
| `negative_news` | Sentiment below `-0.25` at medium or high impact | yes |
| `overbought` | RSI(14) above 80 | no |
| `extended_above_sma200` | Close more than 30% above the 200-day average | no |
| `earnings_soon` | Earnings expected within 7 days | no |
| `thin_coverage` | Available weight below 75% | no |

Each flag returns its own evidence: the threshold, the measured value, and the
related identifiers. Earnings proximity is measured in exchange-local days and
uses the provider's date or window, including whether it is confirmed.

## Signal records

Every score is written to the append-only `signals` table. Rows are never
updated, so changing weights later cannot rewrite what the system said at the
time. Each record keeps the score, label, status, the full breakdown, the
weights and thresholds in force, the caution flags, the indicator snapshot and
news analysis IDs, and the reference session and close used.

A signal's identity is the ticker plus a hash of: the scoring version, the
configuration hash, the indicator snapshot ID, the news analysis ID, the input
statuses, and the reference session. Rescoring identical inputs returns the
existing record and writes nothing new. A completed session, a new analyzed
article, or an edited `config/scoring.yaml` produces a new record. Intraday
quotes are deliberately excluded, so a 15-minute refresh does not fill the log
with near-duplicates.

The reference close is the last completed session close, and forward performance
is measured from it; see [ALERTS_AND_BRIEF.md](ALERTS_AND_BRIEF.md).

## Tuning

Edit `config/scoring.yaml` and restart. Validation rejects weights that do not
cover exactly the seven components, label thresholds out of order, curves whose
inputs are not strictly ascending, sub-scores outside 0–100, and impact factors
outside 0–1. `GET /api/scoring/config` returns the configuration in force, its
hash, and whether it differs from the most recent recorded signal.

Raising a weight does not make its component more predictive. The weights are
preferences about what to look at, and the curve knots are judgement calls, not
fitted parameters.

## Known limitations

- The volume component measures participation only. It has no direction, so
  heavy selling and heavy buying score identically. Read it with `trend`.
- Sub-scores are bounded, so an extreme value is clamped rather than dominating.
- Components are treated as independent although they are not; trend, momentum,
  and range position move together, which concentrates weight in price action.
- Fundamental fields come from a single provider snapshot with no common
  observation time, and forward figures are estimates.
- News sentiment is a model interpretation of headlines and excerpts, and may be
  wrong or incomplete. Articles without an explicit company mention are excluded
  from analysis entirely, so a score can miss relevant context.
- The composite is a linear combination. It cannot express conditions such as
  "cheap only if growth holds up".
- No score is a statement about future returns, and none of this has been
  validated against realized performance yet.
