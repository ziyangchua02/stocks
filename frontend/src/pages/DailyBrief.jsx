import { useState } from 'react'
import { Link } from 'react-router-dom'
import { DEMO, api } from '../api/client.js'
import {
  Button,
  Card,
  Empty,
  ErrorNotice,
  Freshness,
  Loading,
  SourceLinks,
} from '../components/Primitives.jsx'
import { useApi } from '../hooks/useApi.js'
import { MISSING, number, percent, timestamp } from '../lib/format.js'

export default function DailyBrief() {
  const brief = useApi(() => api.dailyBrief(), [])
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState(null)

  if (brief.loading) return <Loading what="the daily brief" />
  if (brief.error) return <ErrorNotice error={brief.error} onRetry={brief.reload} />

  async function write() {
    setBusy(true)
    setProblem(null)
    try {
      await api.writeDailyBrief()
      brief.reload()
    } catch (error) {
      setProblem(error.body || { status: 'failed', reason: error.message })
    } finally {
      setBusy(false)
    }
  }

  const stored = brief.data.data || brief.data.previous_brief
  const isCurrent = Boolean(brief.data.data)
  const facts = brief.data.current_facts

  return (
    <div className="space-y-4">
      <Card
        title="Daily brief"
        subtitle={brief.data.disclaimer}
        actions={
          <Button
            kind="primary"
            onClick={write}
            disabled={busy || DEMO}
            title={DEMO ? 'Writing a brief needs the local backend and a model key.' : undefined}
          >
            {busy ? 'Writing…' : isCurrent ? 'Rewrite brief' : 'Write brief'}
          </Button>
        }
      >
        <div className="flex flex-wrap items-center gap-3">
          <Freshness
            status={brief.data.status}
            at={stored?.generated_at}
            reason={isCurrent ? null : brief.data.reason}
          />
          <span className="text-xs text-ink-secondary">
            {brief.data.changed_tickers.length
              ? `Changed since the window opened: ${brief.data.changed_tickers.join(', ')}`
              : 'No watchlist changes in the current window'}
          </span>
        </div>
        <p className="mt-2 text-xs text-ink-muted">
          Every figure below is computed locally from your stored records over the last{' '}
          {facts.lookback_hours} hours. The model only writes the wording around them and must
          cite an article for any news-based explanation.
        </p>
        {problem ? (
          <p className="mt-2 text-xs text-critical">
            Could not write a brief: {problem.reason || problem.error}
          </p>
        ) : null}
      </Card>

      {stored ? (
        <Card
          title={stored.payload.headline}
          subtitle={`${timestamp(stored.period_start)} → ${timestamp(stored.period_end)} · ${
            stored.model
          } · ${stored.prompt_version}`}
        >
          {!isCurrent ? (
            <p className="mb-3 text-xs text-serious">
              ▲ This brief was written for an earlier set of inputs, so it may not describe the
              current data. Write a new one to cover the latest.
            </p>
          ) : null}
          <p className="text-sm text-ink">{stored.payload.overview}</p>

          <ul className="mt-4 space-y-3">
            {stored.payload.notes.map((note) => (
              <li key={note.ticker} className="border-t border-hairline pt-3">
                <div className="flex flex-wrap items-baseline gap-2">
                  <Link
                    className="text-sm font-medium text-ink underline-offset-2 hover:underline"
                    to={`/ticker/${note.ticker}`}
                  >
                    {note.ticker}
                  </Link>
                  <span className="text-xs text-ink-muted">basis: {note.basis}</span>
                </div>
                <p className="mt-1 text-xs text-ink-secondary">{note.what_changed}</p>
                <p className="mt-1 text-xs text-ink-secondary">{note.why}</p>
                <p className="tabular mt-1 text-xs text-ink-muted">
                  score {note.figures.score === null ? MISSING : number(note.figures.score, 1)}
                  {note.figures.score_change !== null
                    ? ` (${number(note.figures.score_change, 1)} since ${
                        note.figures.comparison_basis
                      })`
                    : ' (no earlier signal to compare)'}
                  {' · close '}
                  {note.figures.last_close === null
                    ? MISSING
                    : number(note.figures.last_close, 2)}{' '}
                  {note.figures.close_change_percent !== null
                    ? percent(note.figures.close_change_percent)
                    : '(no prior session close)'}
                </p>
                {note.sources.length ? (
                  <div className="mt-1">
                    <SourceLinks sources={note.sources} />
                  </div>
                ) : (
                  <p className="mt-1 text-xs text-ink-muted">
                    No article cited: this note rests on the figures above.
                  </p>
                )}
              </li>
            ))}
          </ul>

          {stored.payload.watch_items.length ? (
            <div className="mt-4 border-t border-hairline pt-3">
              <p className="text-xs font-medium text-ink">Worth watching next</p>
              <ul className="mt-1 list-inside list-disc space-y-1">
                {stored.payload.watch_items.map((item) => (
                  <li key={item} className="text-xs text-ink-secondary">
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {stored.payload.tickers_without_a_note.length ? (
            <p className="mt-3 text-xs text-ink-muted">
              Not covered by a note: {stored.payload.tickers_without_a_note.join(', ')}.
            </p>
          ) : null}
        </Card>
      ) : (
        <Empty
          title="No brief written yet"
          detail={
            brief.data.reason === 'disabled'
              ? 'Briefs are disabled in config/alerts.yaml.'
              : 'Use “Write brief” to summarize what changed since the window opened. It uses one model call and only cached data.'
          }
        />
      )}

      <Card title="The figures the brief was given" subtitle={facts.note}>
        <table className="tabular w-full text-left text-xs">
          <thead className="text-ink-secondary">
            <tr>
              <th className="py-1 pr-3 font-medium">Ticker</th>
              <th className="py-1 pr-3 font-medium">Score</th>
              <th className="py-1 pr-3 font-medium">Change</th>
              <th className="py-1 pr-3 font-medium">Label</th>
              <th className="py-1 pr-3 font-medium">Close</th>
              <th className="py-1 pr-3 font-medium">Session move</th>
              <th className="py-1 font-medium">Alerts</th>
            </tr>
          </thead>
          <tbody>
            {facts.tickers.map((row) => (
              <tr key={row.ticker} className="border-t border-hairline">
                <td className="py-2 pr-3 text-ink">{row.ticker}</td>
                <td className="py-2 pr-3">{row.score === null ? MISSING : number(row.score, 1)}</td>
                <td className="py-2 pr-3">
                  {row.score_change === null ? MISSING : number(row.score_change, 1)}
                </td>
                <td className="py-2 pr-3 text-ink-secondary">
                  {row.previous_label && row.previous_label !== row.label
                    ? `${row.previous_label} → ${row.label}`
                    : row.label || MISSING}
                </td>
                <td className="py-2 pr-3">
                  {row.last_close === null ? MISSING : number(row.last_close, 2)}
                </td>
                <td className="py-2 pr-3">
                  {row.close_change_percent === null
                    ? MISSING
                    : percent(row.close_change_percent)}
                </td>
                <td className="py-2 text-ink-secondary">{row.alerts.length || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  )
}
