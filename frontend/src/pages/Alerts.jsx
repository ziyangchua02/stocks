import { useState } from 'react'
import { Link } from 'react-router-dom'
import { DEMO, api } from '../api/client.js'
import { Button, Card, Chip, Empty, ErrorNotice, Loading } from '../components/Primitives.jsx'
import { useApi } from '../hooks/useApi.js'
import { alertTone } from '../lib/derive.js'
import { number, timestamp } from '../lib/format.js'

export default function Alerts() {
  const [unreadOnly, setUnreadOnly] = useState(false)
  const alerts = useApi(() => api.alerts({ unacknowledgedOnly: unreadOnly }), [unreadOnly])
  const [busy, setBusy] = useState(false)

  if (alerts.loading) return <Loading what="alerts" />
  if (alerts.error) return <ErrorNotice error={alerts.error} onRetry={alerts.reload} />

  async function acknowledge(id) {
    setBusy(true)
    try {
      await api.acknowledgeAlert(id)
      alerts.reload()
    } finally {
      setBusy(false)
    }
  }

  async function acknowledgeAll() {
    setBusy(true)
    try {
      await api.acknowledgeAllAlerts()
      alerts.reload()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <Card
        title="Alerts"
        subtitle={alerts.data.disclaimer}
        actions={
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-1.5 text-xs text-ink-secondary">
              <input
                type="checkbox"
                checked={unreadOnly}
                onChange={(event) => setUnreadOnly(event.target.checked)}
              />
              Unread only
            </label>
            <Button onClick={acknowledgeAll} disabled={busy || DEMO || !alerts.data.unacknowledged}>
              Mark all read
            </Button>
          </div>
        }
      >
        <p className="text-xs text-ink-secondary">
          {alerts.data.unacknowledged} unread of {alerts.data.total} recorded. Raised during
          refreshes from cached data; delivery is {alerts.data.delivery}.
        </p>
        <p className="mt-1 text-xs text-ink-muted">
          Active rules: {alerts.data.rules_enabled.join(', ') || 'none'} — edit thresholds in
          config/alerts.yaml and restart. Marking an alert read never edits the observation.
        </p>
      </Card>

      {alerts.data.items.length === 0 ? (
        <Empty
          title={unreadOnly ? 'No unread alerts' : 'No alerts recorded yet'}
          detail="Alerts are created during a refresh when a configured threshold is crossed."
        />
      ) : (
        <ul className="space-y-3">
          {alerts.data.items.map((alert) => (
            <li key={alert.id} className="card p-4">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <div className="flex items-center gap-2">
                  <Chip tone={alertTone(alert.severity)}>{alert.rule.replaceAll('_', ' ')}</Chip>
                  <span className="text-sm text-ink">{alert.title}</span>
                </div>
                <span className="text-xs text-ink-muted">{timestamp(alert.created_at)}</span>
              </div>
              <p className="mt-2 text-xs text-ink-secondary">{alert.detail}</p>
              <dl className="tabular mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-muted">
                {Object.entries(alert.evidence)
                  .filter(([key]) => !['link', 'url'].includes(key))
                  .map(([key, value]) => (
                    <div key={key} className="flex gap-1">
                      <dt>{key.replaceAll('_', ' ')}:</dt>
                      <dd className="text-ink-secondary">
                        {typeof value === 'number' ? number(value, 2) : String(value)}
                      </dd>
                    </div>
                  ))}
              </dl>
              <div className="mt-3 flex flex-wrap items-center gap-3">
                {alert.ticker ? (
                  <Link
                    className="text-xs text-ink underline-offset-2 hover:underline"
                    to={`/ticker/${alert.ticker}`}
                  >
                    Open {alert.ticker} →
                  </Link>
                ) : null}
                {alert.evidence.url ? (
                  <a
                    className="text-xs text-ink underline-offset-2 hover:underline"
                    href={alert.evidence.url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Read the article →
                  </a>
                ) : null}
                {alert.acknowledged_at ? (
                  <span className="text-xs text-ink-muted">
                    read {timestamp(alert.acknowledged_at)}
                  </span>
                ) : (
                  <Button onClick={() => acknowledge(alert.id)} disabled={busy || DEMO}>
                    Mark read
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
