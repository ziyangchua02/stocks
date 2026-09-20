import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client.js'
import { MacdPanel, RsiPanel } from '../charts/IndicatorPanels.jsx'
import PriceChart from '../charts/PriceChart.jsx'
import { ContributionBars, SentimentBar } from '../charts/ScoreCharts.jsx'
import {
  Card,
  Chip,
  Empty,
  ErrorNotice,
  Freshness,
  Loading,
  SourceLinks,
  StatTile,
} from '../components/Primitives.jsx'
import { useApi } from '../hooks/useApi.js'
import { buildCases, labelTone } from '../lib/derive.js'
import { MISSING, number, percent, price, ratio, timestamp } from '../lib/format.js'

export default function TickerDetail() {
  const { ticker } = useParams()
  const indicators = useApi(() => api.indicators(ticker), [ticker])
  const score = useApi(() => api.score(ticker), [ticker])
  const news = useApi(() => api.newsAnalysis(ticker), [ticker])
  const quote = useApi(() => api.quote(ticker).catch(() => null), [ticker])

  if (indicators.loading || score.loading || news.loading) return <Loading what={ticker} />
  if (indicators.error) return <ErrorNotice error={indicators.error} onRetry={indicators.reload} />
  if (score.error) return <ErrorNotice error={score.error} onRetry={score.reload} />

  const technicals = indicators.data?.data?.technicals
  const fundamentals = indicators.data?.data?.fundamentals
  const series = technicals?.series || []
  const payload = score.data?.data
  const analysis = news.data?.data
  const cases = buildCases(payload, analysis)
  const quoteData = quote.data?.data

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-center gap-3">
        <Link className="text-xs text-ink-secondary underline-offset-2 hover:underline" to="/">
          ← Overview
        </Link>
        <h2 className="text-lg font-semibold">{ticker}</h2>
        {payload?.label ? <Chip tone={labelTone(payload.label)}>{payload.label}</Chip> : null}
        <Freshness
          status={indicators.data?.status}
          at={technicals?.source_fetched_at}
          reason={`session ${technicals?.as_of_session || 'unknown'}`}
        />
      </header>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label="Last quote"
          value={quoteData ? price(quoteData.price, quoteData.currency) : MISSING}
          sub={quoteData ? percent(quoteData.change_percent) : 'No cached quote'}
          status={quote.data?.status}
          at={quoteData?.source_as_of}
        />
        <StatTile
          label="Composite score"
          value={payload?.score !== null && payload?.score !== undefined ? number(payload.score, 1) : MISSING}
          sub={payload?.status === 'scored' ? `coverage ${ratio(payload.weight_coverage)}` : payload?.reason}
          status={payload?.status}
          at={payload?.computed_at}
        />
        <StatTile
          label="Last close"
          value={technicals?.last_close ? price(technicals.last_close) : MISSING}
          sub={`completed session ${technicals?.as_of_session || MISSING}`}
          status={technicals?.freshness}
        />
        <StatTile
          label="Next earnings"
          value={
            fundamentals?.fields?.next_earnings_date?.value ||
            fundamentals?.fields?.next_earnings_date?.window_start ||
            MISSING
          }
          sub={fundamentals?.fields?.next_earnings_date?.reason || ''}
          status={fundamentals?.fields?.next_earnings_date?.status}
        />
      </div>

      <Card title="Price and indicators" subtitle={technicals?.price_basis}>
        {series.length ? (
          <>
            <PriceChart series={series} currency={fundamentals?.currency} />
            <div className="mt-4 grid gap-4 lg:grid-cols-2">
              <div>
                <p className="mb-1 text-xs font-medium text-ink">RSI(14)</p>
                <RsiPanel series={series} />
              </div>
              <div>
                <p className="mb-1 text-xs font-medium text-ink">MACD histogram (12/26/9)</p>
                <MacdPanel series={series} />
              </div>
            </div>
            {technicals?.warnings?.length ? (
              <ul className="mt-3 space-y-1">
                {technicals.warnings.map((warning) => (
                  <li key={warning} className="text-xs text-serious">
                    ▲ {warning}
                  </li>
                ))}
              </ul>
            ) : null}
          </>
        ) : (
          <Empty
            title="No computed indicator series"
            detail={indicators.data?.reason || 'Refresh to fetch daily history for this ticker.'}
          />
        )}
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card
          title="Score breakdown"
          subtitle={payload ? payload.label_rationale : 'No score was produced.'}
        >
          {payload?.breakdown?.length ? (
            <>
              <ContributionBars breakdown={payload.breakdown} total={payload.score} />
              <p className="mt-3 text-xs text-ink-muted">
                Weights come from config/scoring.yaml ({payload.config_version}). Components with no
                data are excluded and the rest renormalized, never filled in.
              </p>
            </>
          ) : (
            <Empty title="Not scored" detail={payload?.reason || score.data?.reason} />
          )}
          {payload?.cautions?.length ? (
            <ul className="mt-3 space-y-2 border-t border-hairline pt-3">
              {payload.cautions.map((flag) => (
                <li key={flag.flag} className="text-xs">
                  <Chip tone={flag.downgrades_label ? 'warning' : 'neutral'}>{flag.flag}</Chip>
                  <span className="ml-2 text-ink-secondary">{flag.message}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </Card>

        <Card
          title="AI news summary"
          subtitle={news.data?.disclaimer}
          actions={
            analysis ? (
              <Freshness status={news.data.status} at={analysis.generated_at} />
            ) : null
          }
        >
          {analysis ? (
            <div className="space-y-3">
              <p className="text-sm text-ink">{analysis.payload.summary}</p>
              <SourceLinks sources={analysis.payload.claims.summary.sources} />
              <div className="flex flex-wrap items-center gap-3 border-t border-hairline pt-3">
                <SentimentBar value={analysis.payload.sentiment} impact={analysis.payload.impact} />
                <span className="text-xs text-ink-secondary">
                  horizon: {analysis.payload.time_horizon} · model {analysis.model}
                </span>
              </div>
              <p className="text-xs text-ink-muted">
                {news.data.coverage.selected_count} of {news.data.coverage.eligible_count} eligible
                article(s) analyzed from the last {news.data.coverage.lookback_hours}h.
                {news.data.coverage.omitted_count
                  ? ` ${news.data.coverage.omitted_count} omitted by the configured cap.`
                  : ''}
              </p>
              {news.data.warnings?.map((warning) => (
                <p key={warning} className="text-xs text-serious">
                  ▲ {warning}
                </p>
              ))}
            </div>
          ) : (
            <Empty
              title="No current news analysis"
              detail={
                news.data?.reason
                  ? `${news.data.reason}. Sentiment is left out of the score rather than assumed neutral.`
                  : 'Refresh to analyze recent articles.'
              }
            />
          )}
        </Card>
      </div>

      <Card title="Bull case vs bear case" subtitle={cases.note}>
        <div className="grid gap-4 lg:grid-cols-2">
          <CaseColumn title="Bull case" items={cases.bull} empty="No supporting evidence on this page." />
          <CaseColumn title="Bear case" items={cases.bear} empty="No opposing evidence on this page." />
        </div>
      </Card>
    </div>
  )
}

function CaseColumn({ title, items, empty }) {
  return (
    <div>
      <h3 className="text-xs font-semibold text-ink">{title}</h3>
      {items.length === 0 ? (
        <p className="mt-2 text-xs text-ink-muted">{empty}</p>
      ) : (
        <ul className="mt-2 space-y-2">
          {items.map((item, index) => (
            <li key={`${item.kind}-${index}`} className="text-xs">
              <span className="text-ink-muted">[{item.kind}]</span>{' '}
              <span className="text-ink-secondary">{item.text}</span>
              {item.sources ? (
                <div className="mt-0.5">
                  <SourceLinks sources={item.sources} />
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
