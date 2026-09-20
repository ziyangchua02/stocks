import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client.js'
import { Card, Chip, Empty, ErrorNotice, Loading } from '../components/Primitives.jsx'
import { useApi } from '../hooks/useApi.js'
import { labelTone, outcomeText } from '../lib/derive.js'
import { MISSING, number, ratio, timestamp } from '../lib/format.js'

export default function SignalLog() {
  const [ticker, setTicker] = useState('')
  const watchlist = useApi(() => api.watchlist(), [])
  const signals = useApi(() => api.signals({ ticker: ticker || undefined, limit: 200 }), [ticker])
  const scoring = useApi(() => api.scoringConfig(), [])
  const performance = useApi(() => api.performance(), [])

  if (signals.loading) return <Loading what="the signal log" />
  if (signals.error) return <ErrorNotice error={signals.error} onRetry={signals.reload} />

  return (
    <div className="space-y-4">
      <Card
        title="Signal log"
        subtitle={signals.data.note}
        actions={
          <select
            aria-label="Ticker"
            className="rounded-md border border-hairline bg-surface px-2 py-1.5 text-xs"
            value={ticker}
            onChange={(event) => setTicker(event.target.value)}
          >
            <option value="">All tickers</option>
            {(watchlist.data?.items || []).map((item) => (
              <option key={item.ticker} value={item.ticker}>
                {item.ticker}
              </option>
            ))}
          </select>
        }
      >
        <p className="text-xs text-ink-secondary">
          Every score the system has recorded, with the weights it used at the time. Records are
          never rewritten, so changing weights creates new rows instead of altering old ones.
          {scoring.data ? ` Weights in force: ${scoring.data.config_version}.` : ''}
        </p>
        <p className="mt-1 text-xs text-ink-muted">
          Forward returns are measured from stored daily closes, from the reference session to
          the first completed session on or after the horizon. A horizon that has not elapsed
          stays pending rather than being estimated.
        </p>
      </Card>

      {performance.data ? <PerformancePanel summary={performance.data} /> : null}

      {signals.data.items.length === 0 ? (
        <Empty title="No signals recorded yet" detail="Refresh to score the watchlist." />
      ) : (
        <div className="card overflow-x-auto p-4">
          <table className="w-full text-left text-xs">
            <thead className="text-ink-secondary">
              <tr>
                <th className="py-1 pr-3 font-medium">Recorded</th>
                <th className="py-1 pr-3 font-medium">Ticker</th>
                <th className="py-1 pr-3 font-medium">Score</th>
                <th className="py-1 pr-3 font-medium">Label</th>
                <th className="py-1 pr-3 font-medium">Coverage</th>
                <th className="py-1 pr-3 font-medium">Reference session</th>
                <th className="py-1 pr-3 font-medium">Reference close</th>
                <th className="py-1 pr-3 font-medium">Weights</th>
                <th className="py-1 pr-3 font-medium">1 week</th>
                <th className="py-1 font-medium">1 month</th>
              </tr>
            </thead>
            <tbody>
              {signals.data.items.map((signal) => (
                <tr key={signal.id} className="border-t border-hairline">
                  <td className="py-2 pr-3 text-ink-secondary">{timestamp(signal.created_at)}</td>
                  <td className="py-2 pr-3">
                    <Link className="text-ink underline-offset-2 hover:underline" to={`/ticker/${signal.ticker}`}>
                      {signal.ticker}
                    </Link>
                  </td>
                  <td className="tabular py-2 pr-3">
                    {signal.score === null ? MISSING : number(signal.score, 1)}
                  </td>
                  <td className="py-2 pr-3">
                    {signal.label ? <Chip tone={labelTone(signal.label)}>{signal.label}</Chip> : MISSING}
                  </td>
                  <td className="tabular py-2 pr-3">{ratio(signal.payload.weight_coverage)}</td>
                  <td className="tabular py-2 pr-3">{signal.reference_session || MISSING}</td>
                  <td className="tabular py-2 pr-3">
                    {signal.reference_close === null ? MISSING : number(signal.reference_close, 2)}
                  </td>
                  <td className="py-2 pr-3 text-ink-muted">{signal.config_version}</td>
                  <OutcomeCell outcome={signal.outcomes?.['1_week']} />
                  <OutcomeCell outcome={signal.outcomes?.['1_month']} />
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

const TONE_CLASS = { up: 'text-ink', down: 'text-ink', muted: 'text-ink-muted' }

function OutcomeCell({ outcome }) {
  const { text, tone, detail, title } = outcomeText(outcome)
  return (
    <td className="py-2 pr-3">
      <span className={`tabular ${TONE_CLASS[tone]}`} title={title || detail || undefined}>
        {text}
      </span>
      {detail ? <span className="block text-[11px] text-ink-muted">{detail}</span> : null}
    </td>
  )
}

/** Grouped outcomes. The verdict leads, because a small sample is the finding. */
function PerformancePanel({ summary }) {
  return (
    <Card
      title="Has the scoring predicted anything?"
      subtitle={summary.verdict}
      actions={
        <span className="text-xs text-ink-muted">
          benchmark {summary.benchmark_symbol || 'none configured'}
        </span>
      }
    >
      <table className="tabular w-full text-left text-xs">
        <thead className="text-ink-secondary">
          <tr>
            <th className="py-1 pr-3 font-medium">Label</th>
            <th className="py-1 pr-3 font-medium">Signals</th>
            <th className="py-1 pr-3 font-medium">1w measured</th>
            <th className="py-1 pr-3 font-medium">1w mean</th>
            <th className="py-1 pr-3 font-medium">1w vs benchmark</th>
            <th className="py-1 pr-3 font-medium">1m measured</th>
            <th className="py-1 font-medium">1m mean</th>
          </tr>
        </thead>
        <tbody>
          {summary.groups.map((group) => (
            <tr key={group.label} className="border-t border-hairline">
              <td className="py-2 pr-3 text-ink">{group.label}</td>
              <td className="py-2 pr-3">{group.signals}</td>
              <td className="py-2 pr-3">
                {group.horizons['1_week'].measured}
                <span className="text-ink-muted"> ({group.horizons['1_week'].pending} pending)</span>
              </td>
              <td className="py-2 pr-3">{formatMean(group.horizons['1_week'].mean_return_percent)}</td>
              <td className="py-2 pr-3">
                {formatMean(group.horizons['1_week'].mean_excess_percent)}
              </td>
              <td className="py-2 pr-3">
                {group.horizons['1_month'].measured}
                <span className="text-ink-muted"> ({group.horizons['1_month'].pending} pending)</span>
              </td>
              <td className="py-2">{formatMean(group.horizons['1_month'].mean_return_percent)}</td>
            </tr>
          ))}
          {summary.groups.length === 0 ? (
            <tr>
              <td className="py-2 text-ink-muted" colSpan={7}>
                No signals recorded yet.
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
      <p className="mt-3 text-xs text-ink-secondary">
        {summary.measured_outcomes} measured outcome(s) across {summary.total_signals} signal(s).
        A group needs at least {summary.minimum_sample_per_group} signals before these averages
        are worth reading at all.
      </p>
      <ul className="mt-2 list-inside list-disc space-y-1">
        {summary.caveats.map((caveat) => (
          <li key={caveat} className="text-xs text-ink-muted">
            {caveat}
          </li>
        ))}
      </ul>
    </Card>
  )
}

function formatMean(value) {
  if (value === null || value === undefined) return MISSING
  return `${value > 0 ? '+' : ''}${number(value, 2)}%`
}
