import { useMemo, useState } from 'react'
import { api } from '../api/client.js'
import { SentimentBar } from '../charts/ScoreCharts.jsx'
import { Button, Card, Empty, ErrorNotice, Freshness, Loading } from '../components/Primitives.jsx'
import { useApi } from '../hooks/useApi.js'
import { filterArticles } from '../lib/derive.js'
import { timestamp } from '../lib/format.js'

const SENTIMENTS = [
  { value: 'any', label: 'Any sentiment' },
  { value: 'positive', label: 'Positive (≥ 0.15)' },
  { value: 'neutral', label: 'Mixed or neutral' },
  { value: 'negative', label: 'Negative (≤ -0.15)' },
  { value: 'unanalyzed', label: 'Not analyzed' },
]

const IMPACTS = [
  { value: 'any', label: 'Any impact' },
  { value: 'high', label: 'High impact' },
  { value: 'medium', label: 'Medium impact' },
  { value: 'low', label: 'Low impact' },
]

const PAGE = 25

export default function NewsFeed() {
  const [hours, setHours] = useState(48)
  const [shown, setShown] = useState(PAGE)
  const [ticker, setTicker] = useState('')
  const [sentiment, setSentiment] = useState('any')
  const [impact, setImpact] = useState('any')
  const watchlist = useApi(() => api.watchlist(), [])
  const news = useApi(() => api.news({ hours, limit: 200 }), [hours])

  const filtered = useMemo(
    () => filterArticles(news.data?.items || [], { ticker, sentiment, impact }),
    [news.data, ticker, sentiment, impact],
  )
  const visible = filtered.slice(0, shown)

  if (news.loading) return <Loading what="the news feed" />
  if (news.error) return <ErrorNotice error={news.error} onRetry={news.reload} />

  const analyzed = (news.data.items || []).filter((article) => article.assessment).length
  const failing = (news.data.provider_status || []).filter((row) => row.error)

  return (
    <div className="space-y-4">
      <Card
        title="News feed"
        subtitle={news.data.assessment_note}
        actions={
          <Freshness
            status={news.data.status}
            reason={
              news.data.total > news.data.items.length
                ? `newest ${news.data.items.length} of ${news.data.total} stored in this window`
                : `${news.data.total} article(s) stored in this window`
            }
          />
        }
      >
        <div className="flex flex-wrap items-center gap-2">
          <select
            aria-label="Ticker"
            className="rounded-md border border-hairline bg-surface px-2 py-1.5 text-xs"
            value={ticker}
            onChange={(event) => {
              setTicker(event.target.value)
              setShown(PAGE)
            }}
          >
            <option value="">All tickers</option>
            {(watchlist.data?.items || []).map((item) => (
              <option key={item.ticker} value={item.ticker}>
                {item.ticker}
              </option>
            ))}
          </select>
          <select
            aria-label="Sentiment"
            className="rounded-md border border-hairline bg-surface px-2 py-1.5 text-xs"
            value={sentiment}
            onChange={(event) => {
              setSentiment(event.target.value)
              setShown(PAGE)
            }}
          >
            {SENTIMENTS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <select
            aria-label="Impact"
            className="rounded-md border border-hairline bg-surface px-2 py-1.5 text-xs"
            value={impact}
            onChange={(event) => {
              setImpact(event.target.value)
              setShown(PAGE)
            }}
          >
            {IMPACTS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <select
            aria-label="Window"
            className="rounded-md border border-hairline bg-surface px-2 py-1.5 text-xs"
            value={hours}
            onChange={(event) => {
              setHours(Number(event.target.value))
              setShown(PAGE)
            }}
          >
            <option value={24}>Last 24 h</option>
            <option value={48}>Last 48 h</option>
            <option value={168}>Last 7 days</option>
          </select>
          <span className="text-xs text-ink-secondary">
            showing {Math.min(shown, filtered.length)} of {filtered.length} matching ·{' '}
            {analyzed} of {news.data.items.length} loaded articles have an AI assessment
          </span>
        </div>
        {failing.length ? (
          <ul className="mt-2 space-y-1">
            {failing.map((row) => (
              <li key={row.cache_key} className="text-xs text-serious">
                ▲ {row.cache_key}: {row.error}
              </li>
            ))}
          </ul>
        ) : null}
      </Card>

      {filtered.length === 0 ? (
        <Empty
          title="No articles match these filters"
          detail="Filtering by sentiment or impact only matches articles that have a stored AI assessment. Unanalyzed articles are listed under 'Not analyzed'."
        />
      ) : (
        <ul className="space-y-3">
          {visible.map((article) => (
            <li key={article.id} className="card p-4">
              <a
                className="text-sm text-ink underline decoration-hairline underline-offset-2 hover:decoration-current"
                href={article.url}
                target="_blank"
                rel="noreferrer"
              >
                {article.title}
              </a>
              <p className="mt-1 text-xs text-ink-secondary">
                {article.publisher} · published {timestamp(article.published_at)} · retrieved{' '}
                {timestamp(article.fetched_at)}
                {article.tickers?.length ? ` · ${article.tickers.join(', ')}` : ''}
              </p>
              {article.summary ? (
                <p className="mt-2 text-xs text-ink-secondary">{article.summary}</p>
              ) : null}
              <div className="mt-2 flex flex-wrap items-center gap-3 border-t border-hairline pt-2">
                <SentimentBar
                  value={article.assessment?.sentiment ?? null}
                  impact={article.assessment?.impact}
                />
                {article.assessment ? (
                  <span className="text-xs text-ink-muted">
                    {article.assessment.model} · {timestamp(article.assessment.generated_at)} · for{' '}
                    {article.assessment.ticker}
                  </span>
                ) : null}
              </div>
              {article.assessment ? (
                <p className="mt-1 text-xs text-ink-secondary">{article.assessment.rationale}</p>
              ) : null}
              {article.sources?.length > 1 ? (
                <p className="mt-1 text-xs text-ink-muted">
                  Also seen via {article.sources.map((source) => source.provider).join(', ')}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {filtered.length > visible.length ? (
        <div className="text-center">
          <Button onClick={() => setShown((value) => value + PAGE)}>
            Show {Math.min(PAGE, filtered.length - visible.length)} more of {filtered.length}
          </Button>
        </div>
      ) : null}
    </div>
  )
}
