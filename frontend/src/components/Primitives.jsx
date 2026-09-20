import { ageLabel, freshnessTone, timestamp } from '../lib/format.js'

const TONE_CLASS = {
  ok: 'text-ink-secondary',
  stale: 'text-serious',
  missing: 'text-ink-muted',
  unknown: 'text-ink-muted',
}

const TONE_GLYPH = { ok: '●', stale: '▲', missing: '○', unknown: '○' }

/** Status is always words plus a glyph, so it never depends on color alone. */
export function Freshness({ status, at, reason, className = '' }) {
  const tone = freshnessTone(status)
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs ${TONE_CLASS[tone]} ${className}`}>
      <span aria-hidden="true">{TONE_GLYPH[tone]}</span>
      <span>{status || 'unknown'}</span>
      {at ? (
        <span className="text-ink-muted" title={timestamp(at)}>
          · {ageLabel(at)}
        </span>
      ) : null}
      {reason ? <span className="text-ink-muted">· {reason}</span> : null}
    </span>
  )
}

const CHIP_TONE = {
  good: 'border-good text-ink',
  warning: 'border-warning text-ink',
  serious: 'border-serious text-ink',
  critical: 'border-critical text-ink',
  info: 'border-s-1 text-ink',
  neutral: 'border-hairline text-ink-secondary',
}

const CHIP_DOT = {
  good: 'bg-good',
  warning: 'bg-warning',
  serious: 'bg-serious',
  critical: 'bg-critical',
  info: 'bg-s-1',
  neutral: 'bg-ink-muted',
}

export function Chip({ tone = 'neutral', children, title }) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium ${CHIP_TONE[tone]}`}
    >
      <span className={`h-2 w-2 rounded-full ${CHIP_DOT[tone]}`} aria-hidden="true" />
      {children}
    </span>
  )
}

export function Card({ title, subtitle, actions, children, className = '' }) {
  return (
    <section className={`card p-4 ${className}`}>
      {(title || actions) && (
        <header className="mb-3 flex items-start justify-between gap-3">
          <div>
            {title ? <h2 className="text-sm font-semibold text-ink">{title}</h2> : null}
            {subtitle ? <p className="mt-0.5 text-xs text-ink-secondary">{subtitle}</p> : null}
          </div>
          {actions}
        </header>
      )}
      {children}
    </section>
  )
}

export function StatTile({ label, value, sub, status, at, tone = 'neutral' }) {
  return (
    <div className="card p-3">
      <p className="text-xs text-ink-secondary">{label}</p>
      <p className={`tabular mt-1 text-2xl ${tone === 'muted' ? 'text-ink-muted' : 'text-ink'}`}>
        {value}
      </p>
      {sub ? <p className="tabular mt-0.5 text-xs text-ink-secondary">{sub}</p> : null}
      {status ? <Freshness status={status} at={at} className="mt-1" /> : null}
    </div>
  )
}

export function Empty({ title, detail, action }) {
  return (
    <div className="card p-6 text-center">
      <p className="text-sm font-medium text-ink">{title}</p>
      {detail ? <p className="mx-auto mt-1 max-w-lg text-xs text-ink-secondary">{detail}</p> : null}
      {action ? <div className="mt-3">{action}</div> : null}
    </div>
  )
}

export function ErrorNotice({ error, onRetry }) {
  return (
    <div className="card border-critical p-4">
      <p className="text-sm font-medium text-ink">Could not load this from the local backend</p>
      <p className="mt-1 text-xs text-ink-secondary">{error?.message || 'Unknown error.'}</p>
      <p className="mt-1 text-xs text-ink-muted">
        Nothing is shown from an earlier state, because it may no longer be accurate.
      </p>
      {onRetry ? (
        <button type="button" className="mt-3 rounded-md border border-hairline px-3 py-1.5 text-xs" onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </div>
  )
}

export function Loading({ what = 'data' }) {
  return <div className="card p-6 text-center text-sm text-ink-secondary">Loading {what}…</div>
}

export function Button({ children, onClick, disabled, kind = 'default', type = 'button' }) {
  const base = 'rounded-md px-3 py-1.5 text-xs font-medium transition disabled:opacity-50'
  const styles =
    kind === 'primary'
      ? 'bg-ink text-surface hover:opacity-90'
      : 'border border-hairline text-ink hover:bg-plane'
  return (
    <button type={type} className={`${base} ${styles}`} onClick={onClick} disabled={disabled}>
      {children}
    </button>
  )
}

export function SourceLinks({ sources, prefix = 'Sources' }) {
  if (!sources?.length) {
    return <span className="text-xs text-ink-muted">No linked source</span>
  }
  return (
    <span className="text-xs text-ink-secondary">
      {prefix}:{' '}
      {sources.map((source, index) => (
        <span key={source.url || index}>
          {index > 0 ? ', ' : ''}
          <a
            className="underline decoration-hairline underline-offset-2 hover:text-ink"
            href={source.url}
            target="_blank"
            rel="noreferrer"
            title={`${source.title || ''} — ${timestamp(source.published_at)}`}
          >
            {source.publisher || 'source'}
          </a>
        </span>
      ))}
    </span>
  )
}
