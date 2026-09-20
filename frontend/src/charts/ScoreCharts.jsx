import { number } from '../lib/format.js'

/** Component contributions are a magnitude comparison, so they are one hue with
 *  the value labelled at the tip. Components with no data keep their row and
 *  state the reason instead of showing a zero-length bar. */
export function ContributionBars({ breakdown, total }) {
  const maximum = Math.max(...breakdown.map((row) => row.contribution || 0), 1)
  return (
    <ul className="space-y-2">
      {breakdown.map((row) => {
        const scored = row.score !== null && row.score !== undefined
        const width = scored ? Math.max(2, ((row.contribution || 0) / maximum) * 100) : 0
        return (
          <li key={row.component}>
            <div className="flex items-baseline justify-between gap-3 text-xs">
              <span className="text-ink">{row.component.replaceAll('_', ' ')}</span>
              <span className="tabular text-ink-secondary">
                {scored ? (
                  <>
                    {number(row.score, 1)} / 100 · weight {number(row.configured_weight * 100, 0)}%
                    · adds {number(row.contribution, 1)}
                  </>
                ) : (
                  'no data'
                )}
              </span>
            </div>
            {scored ? (
              <div className="mt-1 h-2 w-full rounded-sm bg-plane">
                <div
                  className="h-2 rounded-r-sm bg-s-1"
                  style={{ width: `${width}%` }}
                  role="img"
                  aria-label={`${row.component} contributes ${number(row.contribution, 1)} points`}
                />
              </div>
            ) : (
              <p className="mt-1 text-xs text-ink-muted">{row.reason}</p>
            )}
          </li>
        )
      })}
      {total !== null && total !== undefined ? (
        <li className="tabular border-t border-hairline pt-2 text-xs text-ink-secondary">
          Weighted total {number(total, 1)} / 100
        </li>
      ) : null}
    </ul>
  )
}

/** Sentiment is polarity, so it reads as a diverging bar from a neutral centre. */
export function SentimentBar({ value, impact }) {
  if (value === null || value === undefined) {
    return <p className="text-xs text-ink-muted">No sentiment: this article was not analyzed.</p>
  }
  const magnitude = Math.min(Math.abs(value), 1) * 50
  const positive = value >= 0
  return (
    <div className="flex items-center gap-2">
      <div className="relative h-2 w-28 rounded-sm" style={{ background: 'var(--diverging-neutral)' }}>
        <div
          className="absolute top-0 h-2"
          style={{
            left: positive ? '50%' : `${50 - magnitude}%`,
            width: `${magnitude}%`,
            background: positive ? 'var(--diverging-positive)' : 'var(--diverging-negative)',
            borderRadius: positive ? '0 2px 2px 0' : '2px 0 0 2px',
          }}
        />
        <div className="absolute left-1/2 top-[-2px] h-3 w-px" style={{ background: 'var(--axis)' }} />
      </div>
      <span className="tabular text-xs text-ink-secondary">
        {number(value, 2)}
        {impact ? ` · ${impact} impact` : ''}
      </span>
    </div>
  )
}
