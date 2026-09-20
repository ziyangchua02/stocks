import { describe, expect, it } from 'vitest'
import {
  alertTone,
  buildCases,
  chartSeries,
  countUnacknowledged,
  filterArticles,
  labelTone,
  outcomeText,
} from './derive.js'

const score = {
  score: 71,
  breakdown: [
    {
      component: 'trend',
      score: 100,
      contribution: 20,
      inputs: [{ input: 'price_above_sma20', value: true, status: 'scored' }],
    },
    {
      component: 'valuation',
      score: 41,
      contribution: 6,
      inputs: [{ input: 'pe', value: 38.59, status: 'scored' }],
    },
    { component: 'news_sentiment', score: null, reason: 'No current news analysis.', inputs: [] },
  ],
  cautions: [{ flag: 'earnings_soon', message: 'Earnings are expected in about 3 day(s).' }],
}

const analysis = {
  payload: {
    claims: {
      key_points: [{ text: 'Revenue grew.', sources: [{ url: 'https://example.com/a' }] }],
      risks: [{ text: 'Margins may compress.', sources: [{ url: 'https://example.com/b' }] }],
    },
  },
}

describe('bull and bear cases', () => {
  it('splits components at the neutral midpoint and keeps sources', () => {
    const cases = buildCases(score, analysis)
    expect(cases.bull.map((item) => item.kind)).toEqual(['news', 'score'])
    expect(cases.bull[0].sources[0].url).toBe('https://example.com/a')
    expect(cases.bull[1].component).toBe('trend')
    expect(cases.bear.map((item) => item.component ?? item.kind)).toEqual([
      'news',
      'valuation',
      'caution',
    ])
  })

  it('omits components with no data instead of guessing a side', () => {
    const cases = buildCases(score, analysis)
    const mentioned = [...cases.bull, ...cases.bear].map((item) => item.component)
    expect(mentioned).not.toContain('news_sentiment')
  })

  it('works with no analysis at all', () => {
    const cases = buildCases(score, null)
    expect(cases.bull.every((item) => item.kind === 'score')).toBe(true)
    expect(cases.bear.some((item) => item.kind === 'caution')).toBe(true)
  })
})

describe('article filters', () => {
  const items = [
    { id: 1, tickers: ['AAPL'], assessment: { sentiment: 0.5, impact: 'high' } },
    { id: 2, tickers: ['AAPL'], assessment: { sentiment: -0.4, impact: 'low' } },
    { id: 3, tickers: ['MSFT'], assessment: { sentiment: 0.05, impact: 'medium' } },
    { id: 4, tickers: ['MSFT'], assessment: null },
  ]

  it('filters by ticker, sentiment and impact', () => {
    expect(filterArticles(items, { ticker: 'AAPL' }).map((a) => a.id)).toEqual([1, 2])
    expect(filterArticles(items, { sentiment: 'positive' }).map((a) => a.id)).toEqual([1])
    expect(filterArticles(items, { sentiment: 'negative' }).map((a) => a.id)).toEqual([2])
    expect(filterArticles(items, { sentiment: 'neutral' }).map((a) => a.id)).toEqual([3])
    expect(filterArticles(items, { impact: 'high' }).map((a) => a.id)).toEqual([1])
  })

  it('never treats an unanalyzed article as neutral', () => {
    expect(filterArticles(items, { sentiment: 'neutral' }).map((a) => a.id)).not.toContain(4)
    expect(filterArticles(items, { sentiment: 'unanalyzed' }).map((a) => a.id)).toEqual([4])
    expect(filterArticles(items, { impact: 'medium' }).map((a) => a.id)).toEqual([3])
  })
})

describe('chart series', () => {
  it('keeps missing indicator values as nulls so lines break', () => {
    const rows = chartSeries(
      [
        { session_date: '2026-09-17', close: 10, sma200: null },
        { session_date: '2026-09-18', close: 11, sma200: 9 },
      ],
      ['close', 'sma200'],
    )
    expect(rows[0].sma200).toBeNull()
    expect(rows[1].sma200).toBe(9)
  })
})

describe('label tone', () => {
  it('maps labels to status tones without inventing one', () => {
    expect(labelTone('Strong setup')).toBe('good')
    expect(labelTone('Caution')).toBe('warning')
    expect(labelTone('Watch')).toBe('info')
    expect(labelTone('Neutral')).toBe('neutral')
  })
})

describe('outcome rendering', () => {
  it('shows pending horizons as pending, never as zero', () => {
    const pending = outcomeText({
      status: 'pending',
      reason: 'The horizon has not elapsed.',
      target_date: '2026-09-25',
    })
    expect(pending.text).toBe('pending')
    expect(pending.detail).toBe('from 2026-09-25')
    expect(pending.title).toContain('has not elapsed')
    expect(outcomeText(null).text).toBe('not computed')
    expect(outcomeText({ status: 'unavailable', reason: 'No history.' }).text).toBe('unavailable')
  })

  it('shows measured returns with their session and excess', () => {
    const measured = outcomeText({
      status: 'measured',
      return_percent: 3.2,
      observed_session: '2026-09-25',
      excess_return_percent: 1.1,
      benchmark_symbol: '^GSPC',
    })
    expect(measured.text).toBe('+3.20%')
    expect(measured.tone).toBe('up')
    expect(measured.detail).toContain('session 2026-09-25')
    expect(measured.detail).toContain('+1.10% vs ^GSPC')
  })

  it('omits excess when no benchmark was measured', () => {
    const measured = outcomeText({
      status: 'measured',
      return_percent: -2,
      observed_session: '2026-09-25',
    })
    expect(measured.text).toBe('-2.00%')
    expect(measured.tone).toBe('down')
    expect(measured.detail).toBe('session 2026-09-25')
  })
})

describe('alerts', () => {
  it('counts only unacknowledged alerts', () => {
    const alerts = [{ acknowledged_at: null }, { acknowledged_at: '2026-09-20T10:00:00Z' }]
    expect(countUnacknowledged(alerts)).toBe(1)
    expect(countUnacknowledged([])).toBe(0)
    expect(countUnacknowledged(undefined)).toBe(0)
  })

  it('reserves the warning tone for attention alerts', () => {
    expect(alertTone('attention')).toBe('warning')
    expect(alertTone('info')).toBe('neutral')
  })
})
