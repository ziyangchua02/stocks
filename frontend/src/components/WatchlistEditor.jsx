import { useState } from 'react'
import { DEMO, api } from '../api/client.js'
import { Button } from './Primitives.jsx'

export default function WatchlistEditor({ tickers, onChanged }) {
  const [ticker, setTicker] = useState('')
  const [company, setCompany] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  async function submit(event) {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await api.addTicker(ticker.trim().toUpperCase(), company.trim())
      setTicker('')
      setCompany('')
      onChanged?.()
    } catch (problem) {
      setError(problem.message)
    } finally {
      setBusy(false)
    }
  }

  async function remove(symbol) {
    setError(null)
    try {
      await api.removeTicker(symbol)
      onChanged?.()
    } catch (problem) {
      setError(problem.message)
    }
  }

  return (
    <div>
      <form className="flex flex-wrap items-center gap-2" onSubmit={submit}>
        <input
          aria-label="Ticker"
          className="w-28 rounded-md border border-hairline bg-surface px-2 py-1.5 text-xs uppercase"
          placeholder="AMZN"
          value={ticker}
          onChange={(event) => setTicker(event.target.value)}
          required
        />
        <input
          aria-label="Company name"
          className="w-44 rounded-md border border-hairline bg-surface px-2 py-1.5 text-xs"
          placeholder="Amazon (helps match news)"
          value={company}
          onChange={(event) => setCompany(event.target.value)}
        />
        <Button type="submit" disabled={busy || DEMO || !ticker.trim()}>
          {busy ? 'Adding…' : 'Add ticker'}
        </Button>
      </form>
      {error ? <p className="mt-2 text-xs text-critical">{error}</p> : null}
      <ul className="mt-3 flex flex-wrap gap-2">
        {tickers.map((item) => (
          <li
            key={item.ticker}
            className="flex items-center gap-2 rounded-full border border-hairline px-2.5 py-1 text-xs"
          >
            <span className="text-ink">{item.ticker}</span>
            <button
              type="button"
              aria-label={`Remove ${item.ticker}`}
              className="text-ink-muted hover:text-critical disabled:opacity-40"
              disabled={DEMO}
              onClick={() => remove(item.ticker)}
            >
              ✕
            </button>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-ink-muted">
        {DEMO
          ? 'Editing the watchlist needs the local backend; the demo shows a fixed snapshot.'
          : 'A new ticker has no data until the next refresh. Removing one keeps its recorded history.'}
      </p>
    </div>
  )
}
