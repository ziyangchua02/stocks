// Every call is same-origin: the Vite dev server proxies /api to the local
// backend, so the browser never holds a key or talks to a provider directly.
//
// The GitHub Pages build sets VITE_DEMO, which swaps those calls for a frozen
// JSON snapshot in public/demo-data. The demo has no backend at all, so actions
// that would write something fail loudly instead of pretending to succeed.
export const DEMO = import.meta.env.VITE_DEMO === 'true'

export class DemoUnavailable extends Error {
  constructor(action) {
    super(
      `${action} needs the local backend. This page is a frozen snapshot — ` +
        'clone the repo and run it locally for live data.',
    )
    this.name = 'DemoUnavailable'
    this.demo = true
  }
}

async function fixture(name) {
  const response = await fetch(`${import.meta.env.BASE_URL}demo-data/${name}.json`)
  if (!response.ok) {
    throw new Error(`The demo snapshot has no ${name} data.`)
  }
  return response.json()
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  const text = await response.text()
  const body = text ? JSON.parse(text) : null
  if (!response.ok) {
    const detail = body?.detail
    const message = typeof detail === 'string' ? detail : detail?.message || response.statusText
    const error = new Error(message || `Request failed (${response.status})`)
    error.status = response.status
    error.body = body
    throw error
  }
  return body
}

const live = {
  health: () => request('/api/health'),
  overview: () => request('/api/overview'),
  watchlist: () => request('/api/watchlist'),
  addTicker: (ticker, companyName) =>
    request('/api/watchlist', {
      method: 'POST',
      body: JSON.stringify({ ticker, company_name: companyName || '' }),
    }),
  removeTicker: (ticker) => request(`/api/watchlist/${ticker}`, { method: 'DELETE' }),
  indicators: (ticker, limit = 400) =>
    request(`/api/tickers/${ticker}/indicators?include_series=true&limit=${limit}`),
  quote: (ticker) => request(`/api/tickers/${ticker}/quote`),
  score: (ticker) => request(`/api/tickers/${ticker}/score`),
  scores: () => request('/api/scores'),
  scoringConfig: () => request('/api/scoring/config'),
  newsAnalysis: (ticker) => request(`/api/tickers/${ticker}/news-analysis`),
  news: ({ ticker, hours = 48, limit = 100 } = {}) => {
    const params = new URLSearchParams({ hours, limit, include_assessments: 'true' })
    if (ticker) params.set('ticker', ticker)
    return request(`/api/news?${params}`)
  },
  signals: ({ ticker, limit = 100 } = {}) => {
    const params = new URLSearchParams({ limit })
    if (ticker) params.set('ticker', ticker)
    return request(`/api/signals?${params}`)
  },
  performance: () => request('/api/performance'),
  alerts: ({ unacknowledgedOnly = false, limit = 100 } = {}) =>
    request(`/api/alerts?unacknowledged_only=${unacknowledgedOnly}&limit=${limit}`),
  acknowledgeAlert: (id) => request(`/api/alerts/${id}/acknowledge`, { method: 'POST' }),
  acknowledgeAllAlerts: () => request('/api/alerts/acknowledge', { method: 'POST' }),
  dailyBrief: () => request('/api/daily-brief'),
  writeDailyBrief: () => request('/api/daily-brief', { method: 'POST' }),
  refresh: (tickers) =>
    request('/api/refresh', {
      method: 'POST',
      body: JSON.stringify(tickers ? { tickers } : {}),
    }),
  refreshRun: (runId) => request(`/api/refresh/${runId}`),
}

// In demo mode each read maps to a captured file and each write is refused.
const demo = {
  health: () => fixture('health'),
  overview: () => fixture('overview'),
  watchlist: () => fixture('watchlist'),
  indicators: (ticker) => fixture(`indicators--${ticker}`),
  quote: (ticker) => fixture(`quote--${ticker}`),
  score: (ticker) => fixture(`score--${ticker}`),
  scores: () => fixture('scores'),
  scoringConfig: () => fixture('scoring-config'),
  newsAnalysis: (ticker) => fixture(`news-analysis--${ticker}`),
  news: ({ ticker } = {}) => fixture(ticker ? `news--${ticker}` : 'news'),
  signals: ({ ticker } = {}) => fixture(ticker ? `signals--${ticker}` : 'signals'),
  performance: () => fixture('performance'),
  alerts: () => fixture('alerts'),
  dailyBrief: () => fixture('daily-brief'),
  manifest: () => fixture('manifest'),
  addTicker: () => Promise.reject(new DemoUnavailable('Adding a ticker')),
  removeTicker: () => Promise.reject(new DemoUnavailable('Removing a ticker')),
  refresh: () => Promise.reject(new DemoUnavailable('Refreshing data')),
  refreshRun: () => Promise.reject(new DemoUnavailable('Refreshing data')),
  acknowledgeAlert: () => Promise.reject(new DemoUnavailable('Acknowledging an alert')),
  acknowledgeAllAlerts: () => Promise.reject(new DemoUnavailable('Acknowledging alerts')),
  writeDailyBrief: () => Promise.reject(new DemoUnavailable('Writing a brief')),
}

export const api = DEMO ? demo : live
