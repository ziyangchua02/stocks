# Phase 4 verification — composite scoring and signal records

Completed September 20, 2026 against the live database at
`data/research.sqlite3` (backup: `data/research.before-phase4.sqlite3`).

**Not financial advice.** The scores below are examples of the mechanism
working, not research conclusions.

## Automated checks

```sh
.venv/bin/python -m pytest backend/tests -q   # 119 passed
.venv/bin/ruff check backend                  # All checks passed
```

Phase 4 adds 24 tests across `test_scoring.py` and `test_signals.py`, covering
curve interpolation and clamping, the composite as an exact weighted mean,
renormalization when components are missing, withholding a score below minimum
coverage, impact scaling of news sentiment, refusal to score an aged analysis,
label thresholds, caution flags and label downgrades, absence of certainty
language in generated text, rejection of invalid configuration, signal
deduplication, immutability across rescoring, and a new record after a weight
change.

Two pre-existing test problems were fixed while getting the suite green. One
assertion hard-coded schema version 3, which migration 4 supersedes. The other,
`test_quota_cooldown_shared_across_tickers_and_restarts`, built its two fixture
articles with the same URL and headline, so they deduplicated into one article
whose text no longer mentioned the second ticker; the fixture now uses a
distinct slug. Neither was a product defect.

## Migration

The live database moved from `user_version` 3 to 4 on startup. The watchlist,
501 daily bars per ticker, and the three stored news analyses were unchanged.
The new `signals` table was created empty and populated by the startup backfill,
which reads only cached data and calls no provider or model.

## Live scoring

`POST /api/refresh` completed for all three tickers: quotes and history fetched
from yfinance, fundamentals served from cache, indicators computed, Gemini
analyses generated, and a signal recorded for each.

| Ticker | Score | Label | Coverage | Top contributors |
| --- | --- | --- | --- | --- |
| NVDA | 80.43 | Strong setup | 100% | trend, growth_quality, news_sentiment |
| AAPL | 77.39 | Strong setup | 100% | trend, momentum, growth_quality |
| MSFT | 72.56 | Strong setup | 100% | trend, growth_quality, news_sentiment |

The AAPL breakdown was checked line by line: each of the seven components
returned its sub-score, configured weight, effective weight, and contribution,
and the contributions summed to the composite. Every input carried its value,
unit, source, and the curve applied — for example RSI(14) 64.25 → 99.63,
MACD histogram 0.477% of close → 73.84, trailing P/E 38.59 → 41.88, revenue
growth 16.4% → 76.4, and news sentiment 0.20 at medium impact → 61.14 scaled to
57.80. The response linked back to the indicator snapshot, the news analysis ID
carrying the article citations, and the quote endpoint.

`GET /api/scores` ranked the watchlist by score with no unscored tickers,
`GET /api/signals` returned the append-only log, and `GET /api/signals/{id}`
returned a past record with the weights it was scored under.

## Withholding and staleness

Before the refresh, the stored news analyses no longer matched current news
inputs. The news component was excluded rather than assumed neutral, coverage
fell to 80%, and the scores were published with that coverage stated. With a
single-bar history and only a trailing P/E available, coverage falls to 15% and
the API returns `insufficient_data` with no score and no label, which the test
suite asserts.

During verification, stale news alone was downgrading every label to "Caution",
which made the label uninformative. The rule was split: `stale_indicators`
still downgrades, because stale price history undermines every technical
component, while `stale_news` only flags, because its weight is already
excluded from the score and reported through coverage.

## Immutability across a configuration change

That configuration edit changed the config hash. The three earlier records
(IDs 1–3) kept their original labels and weights, and rescoring wrote three new
records (IDs 4–6) rather than updating them. The refresh then produced IDs 7–9
once news analysis was current. Rescoring unchanged inputs returned the existing
record and wrote nothing. `GET /api/scoring/config` reported
`differs_from_latest_signal: false` after the restart.

## Not verified

- Whether the scoring has predictive value. Nothing here measures realized
  performance; the signal log exists so Phase 6 can test it.
- Long-run signal volume. One record per ticker per completed session is the
  design intent, observed over a single session here.
- Behavior when a provider changes its adjustment basis mid-history, which
  Phase 2 already surfaces as a technicals warning.
