import { describe, expect, it } from 'vitest'
import { MISSING, ageLabel, freshnessTone, percent, ratio, sentimentWord, timestamp } from './format.js'

describe('missing data is never invented', () => {
  it('renders a placeholder instead of a zero', () => {
    expect(percent(null)).toBe(MISSING)
    expect(percent(undefined)).toBe(MISSING)
    expect(ratio(null)).toBe(MISSING)
    expect(timestamp(null)).toBe(MISSING)
    expect(timestamp('not-a-date')).toBe(MISSING)
  })

  it('keeps a real zero visible', () => {
    expect(percent(0)).toBe('0.00%')
    expect(ratio(0)).toBe('0%')
  })

  it('signs percentages', () => {
    expect(percent(1.234)).toBe('+1.23%')
    expect(percent(-1.234)).toBe('-1.23%')
  })
})

describe('freshness vocabulary', () => {
  it('maps backend statuses to three tones', () => {
    expect(freshnessTone('cached')).toBe('ok')
    expect(freshnessTone('scored')).toBe('ok')
    expect(freshnessTone('stale')).toBe('stale')
    expect(freshnessTone('partial')).toBe('stale')
    expect(freshnessTone('insufficient_data')).toBe('missing')
    expect(freshnessTone('disabled')).toBe('missing')
    expect(freshnessTone('something-new')).toBe('unknown')
  })

  it('describes age without a timestamp claim it cannot make', () => {
    const now = Date.parse('2026-09-20T12:00:00Z')
    expect(ageLabel(null, now)).toBe('no timestamp')
    expect(ageLabel('2026-09-20T11:59:30Z', now)).toBe('just now')
    expect(ageLabel('2026-09-20T11:20:00Z', now)).toBe('40 min ago')
    expect(ageLabel('2026-09-19T12:00:00Z', now)).toBe('24 h ago')
    expect(ageLabel('2026-09-14T12:00:00Z', now)).toBe('6 d ago')
  })
})

describe('sentiment wording', () => {
  it('separates "not analyzed" from neutral', () => {
    expect(sentimentWord(null)).toBe('not analyzed')
    expect(sentimentWord(0)).toBe('mixed or neutral')
    expect(sentimentWord(-0.6)).toBe('strongly negative')
    expect(sentimentWord(0.6)).toBe('strongly positive')
  })
})
