import { NavLink } from 'react-router-dom'
import { DEMO, api } from '../api/client.js'
import { useApi, useRefreshRun, useTheme } from '../hooks/useApi.js'
import { timestamp } from '../lib/format.js'
import { Button, Freshness } from './Primitives.jsx'

const TABS = [
  { to: '/', label: 'Overview', end: true },
  { to: '/news', label: 'News feed' },
  { to: '/brief', label: 'Daily brief' },
  { to: '/alerts', label: 'Alerts', badge: 'alerts' },
  { to: '/signals', label: 'Signal log' },
]

export default function AppShell({ children }) {
  const health = useApi(() => api.health(), [])
  const [theme, setTheme] = useTheme()
  const refresh = useRefreshRun(api)
  const unread = health.data?.alerts?.unacknowledged || 0

  return (
    <div className="min-h-screen">
      <header className="border-b border-hairline bg-surface">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-3 px-4 py-3">
          <h1 className="text-sm font-semibold">Stock research</h1>
          <nav className="flex gap-1">
            {TABS.map((tab) => (
              <NavLink
                key={tab.to}
                to={tab.to}
                end={tab.end}
                className={({ isActive }) =>
                  `rounded-md px-2.5 py-1 text-xs ${
                    isActive ? 'bg-plane text-ink' : 'text-ink-secondary hover:text-ink'
                  }`
                }
              >
                {tab.label}
                {tab.badge === 'alerts' && unread ? (
                  <span
                    className="ml-1.5 rounded-full border border-warning px-1.5 text-[11px]"
                    title={`${unread} unacknowledged alert(s)`}
                  >
                    {unread}
                  </span>
                ) : null}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3">
            {health.data ? (
              <span className="hidden text-xs text-ink-secondary sm:inline">
                {health.data.market.is_open ? 'Market open' : 'Market closed'} ·{' '}
                {health.data.watchlist_count} tickers
              </span>
            ) : null}
            <select
              aria-label="Colour theme"
              className="rounded-md border border-hairline bg-surface px-2 py-1 text-xs"
              value={theme}
              onChange={(event) => setTheme(event.target.value)}
            >
              <option value="system">System theme</option>
              <option value="light">Light</option>
              <option value="dark">Dark</option>
            </select>
            <Button
              kind="primary"
              disabled={refresh.busy || DEMO}
              title={DEMO ? 'The demo has no backend to refresh from.' : undefined}
              onClick={() => refresh.start(undefined, () => window.location.reload())}
            >
              {refresh.busy ? 'Refreshing…' : 'Refresh data'}
            </Button>
          </div>
        </div>
        {refresh.run ? (
          <div className="mx-auto max-w-7xl px-4 pb-2">
            <Freshness
              status={refresh.run.status}
              reason={
                refresh.run.status === 'running'
                  ? 'Fetching providers and re-scoring; the page reloads when it finishes.'
                  : `Run ${refresh.run.id?.slice(0, 8)} finished at ${timestamp(
                      refresh.run.completed_at,
                    )}`
              }
            />
          </div>
        ) : null}
        {refresh.error ? (
          <div className="mx-auto max-w-7xl px-4 pb-2 text-xs text-critical">
            Refresh failed: {refresh.error.message}
          </div>
        ) : null}
      </header>

      {DEMO ? <DemoBanner capturedAt={health.data?.market?.checked_at} /> : null}

      <div className="border-b border-hairline bg-plane">
        <p className="mx-auto max-w-7xl px-4 py-2 text-xs text-ink-secondary">
          <strong className="text-ink">Not financial advice.</strong> This is a personal research
          tool. It holds no brokerage connection and places no trades. Scores and AI summaries are
          interpretations of cached data and can be wrong or out of date.
        </p>
      </div>

      <main className="mx-auto max-w-7xl px-4 py-5">{children}</main>

      <footer className="mx-auto max-w-7xl px-4 pb-8 text-xs text-ink-muted">
        Data from Yahoo Finance, Finnhub and public RSS feeds, summarized by Gemini. Every figure on
        this page carries its own retrieval time; nothing is filled in when a source is missing.
      </footer>
    </div>
  )
}

/** The demo is a frozen capture, so say so before anyone reads a number as live. */
function DemoBanner({ capturedAt }) {
  return (
    <div className="border-b border-warning bg-plane">
      <p className="mx-auto max-w-7xl px-4 py-2 text-xs text-ink-secondary">
        <strong className="text-ink">Demo snapshot.</strong> This page has no backend: it serves
        a frozen capture{capturedAt ? ` from ${timestamp(capturedAt)}` : ''}, so prices, scores
        and news are out of date and nothing here refreshes. Buttons that would fetch or write
        are disabled.{' '}
        <a
          className="underline decoration-hairline underline-offset-2 hover:text-ink"
          href="https://github.com/ziyangchua02/stocks"
          target="_blank"
          rel="noreferrer"
        >
          Run it locally for live data →
        </a>
      </p>
    </div>
  )
}
