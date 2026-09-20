import { Link } from 'react-router-dom'
import { api } from '../api/client.js'
import { SentimentBar } from '../charts/ScoreCharts.jsx'
import WatchlistEditor from '../components/WatchlistEditor.jsx'
import {
  Card,
  Chip,
  Empty,
  ErrorNotice,
  Freshness,
  Loading,
  StatTile,
} from '../components/Primitives.jsx'
import { useApi } from '../hooks/useApi.js'
import { labelTone } from '../lib/derive.js'
import { MISSING, number, percent, price, ratio, timestamp } from '../lib/format.js'

export default function Overview() {
  const overview = useApi(() => api.overview(), [])
  if (overview.loading) return <Loading what="the market snapshot" />
  if (overview.error) return <ErrorNotice error={overview.error} onRetry={overview.reload} />

  const data = overview.data
  const ranked = [...data.tickers].sort((a, b) => (b.score ?? -1) - (a.score ?? -1))
  const scored = ranked.filter((row) => row.score !== null && row.score !== undefined)
  const unscored = ranked.filter((row) => row.score === null || row.score === undefined)

  return (
    <div className="space-y-5">
      <section>
        <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-sm font-semibold">Market snapshot</h2>
          <Freshness
            status={data.market.is_open ? 'cached' : 'closed'}
            reason={
              data.market.is_open
                ? `Session open · next close ${timestamp(data.market.last_close)}`
                : `Last completed session ${data.market.last_completed_session} · next open ${timestamp(
                    data.market.next_open,
                  )}`
            }
          />
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {data.indices.map((index) => (
            <StatTile
              key={index.symbol}
              label={`${index.name} (${index.symbol})`}
              value={index.data ? price(index.data.price) : MISSING}
              sub={
                index.data
                  ? `${percent(index.data.change_percent)} · prev close ${price(
                      index.data.previous_close,
                    )}`
                  : 'No cached quote for this index'
              }
              status={index.status}
              at={index.data?.source_as_of}
              tone={index.data ? 'default' : 'muted'}
            />
          ))}
          {data.indices.length === 0 ? (
            <p className="text-xs text-ink-muted">No indices configured in config/settings.yaml.</p>
          ) : null}
        </div>
      </section>

      <div className="grid gap-5 lg:grid-cols-3">
        <Card
          className="lg:col-span-2"
          title="Top scored tickers"
          subtitle={`Ranked by the current weighted score (${data.scoring.config_version}). A score summarizes cached inputs; it is not a prediction.`}
        >
          {scored.length === 0 ? (
            <Empty
              title="Nothing is scored yet"
              detail="Refresh to fetch prices and news, then the scoring runs automatically."
            />
          ) : (
            <table className="w-full text-left text-xs">
              <thead className="text-ink-secondary">
                <tr>
                  <th className="py-1 pr-3 font-medium">Ticker</th>
                  <th className="py-1 pr-3 font-medium">Score</th>
                  <th className="py-1 pr-3 font-medium">Label</th>
                  <th className="py-1 pr-3 font-medium">Coverage</th>
                  <th className="py-1 pr-3 font-medium">Last close</th>
                  <th className="py-1 font-medium">Session</th>
                </tr>
              </thead>
              <tbody>
                {scored.map((row) => (
                  <tr key={row.ticker} className="border-t border-hairline">
                    <td className="py-2 pr-3">
                      <Link className="font-medium text-ink underline-offset-2 hover:underline" to={`/ticker/${row.ticker}`}>
                        {row.ticker}
                      </Link>
                      <span className="ml-1 text-ink-muted">{row.company_name}</span>
                    </td>
                    <td className="tabular py-2 pr-3">{number(row.score, 1)}</td>
                    <td className="py-2 pr-3">
                      <Chip tone={labelTone(row.label)}>{row.label}</Chip>
                      {row.cautions.length ? (
                        <span className="ml-2 text-ink-muted">{row.cautions.length} caution(s)</span>
                      ) : null}
                    </td>
                    <td className="tabular py-2 pr-3">{ratio(row.weight_coverage)}</td>
                    <td className="tabular py-2 pr-3">
                      {row.quote.data ? price(row.quote.data.price, row.quote.data.currency) : MISSING}
                      <Freshness status={row.quote.status} at={row.quote.data?.source_as_of} className="ml-2" />
                    </td>
                    <td className="tabular py-2 text-ink-secondary">{row.as_of_session || MISSING}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {unscored.length ? (
            <div className="mt-3 border-t border-hairline pt-3">
              <p className="text-xs font-medium text-ink">Not scored</p>
              <ul className="mt-1 space-y-1">
                {unscored.map((row) => (
                  <li key={row.ticker} className="text-xs text-ink-secondary">
                    <Link className="text-ink underline-offset-2 hover:underline" to={`/ticker/${row.ticker}`}>
                      {row.ticker}
                    </Link>{' '}
                    — {row.score_reason || 'No score produced.'}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </Card>

        <Card title="Biggest movers" subtitle={data.movers.scope}>
          {data.movers.counted === 0 ? (
            <p className="text-xs text-ink-muted">No cached quotes yet.</p>
          ) : (
            <div className="space-y-3">
              <MoverList title="Up" rows={data.movers.gainers} />
              <MoverList title="Down" rows={data.movers.losers} />
              {data.movers.missing_quotes ? (
                <p className="text-xs text-ink-muted">
                  {data.movers.missing_quotes} ticker(s) excluded: no cached quote.
                </p>
              ) : null}
            </div>
          )}
        </Card>
      </div>

      <Card
        title="Most important news"
        subtitle={data.headlines.note}
        actions={
          <Link className="text-xs text-ink-secondary underline-offset-2 hover:underline" to="/news">
            All news →
          </Link>
        }
      >
        {data.headlines.items.length === 0 ? (
          <Empty
            title="No analyzed articles in the window"
            detail={`${data.headlines.article_count} article(s) are cached but none has a stored AI assessment yet. Refresh to analyze them.`}
          />
        ) : (
          <ul className="space-y-3">
            {data.headlines.items.map((article) => (
              <li key={article.id} className="border-b border-hairline pb-3 last:border-0 last:pb-0">
                <a
                  className="text-sm text-ink underline decoration-hairline underline-offset-2 hover:decoration-current"
                  href={article.url}
                  target="_blank"
                  rel="noreferrer"
                >
                  {article.title}
                </a>
                <p className="mt-1 text-xs text-ink-secondary">
                  {article.publisher} · {timestamp(article.published_at)} ·{' '}
                  {(article.tickers || []).join(', ')}
                </p>
                <div className="mt-1.5 flex flex-wrap items-center gap-3">
                  <SentimentBar value={article.assessment.sentiment} impact={article.assessment.impact} />
                  <span className="text-xs text-ink-muted">
                    {article.assessment.model} · {timestamp(article.assessment.generated_at)}
                  </span>
                </div>
                <p className="mt-1 text-xs text-ink-secondary">{article.assessment.rationale}</p>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="Watchlist" subtitle="Add or remove the tickers this dashboard tracks.">
        <WatchlistEditor tickers={data.tickers} onChanged={overview.reload} />
      </Card>
    </div>
  )
}

function MoverList({ title, rows }) {
  return (
    <div>
      <p className="text-xs font-medium text-ink">{title}</p>
      <ul className="mt-1 space-y-1">
        {rows.map((row) => (
          <li key={`${title}-${row.ticker}`} className="flex items-baseline justify-between text-xs">
            <Link className="text-ink underline-offset-2 hover:underline" to={`/ticker/${row.ticker}`}>
              {row.ticker}
            </Link>
            <span className="tabular text-ink-secondary">
              {percent(row.change_percent)} · {price(row.price, row.currency)}
            </span>
          </li>
        ))}
        {rows.length === 0 ? <li className="text-xs text-ink-muted">None</li> : null}
      </ul>
    </div>
  )
}
