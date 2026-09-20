// Presentation helpers. Nothing here invents a value: a missing input returns an
// explicit placeholder so the page can never imply data it does not have.
export const MISSING = '—'

export function number(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return MISSING
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

export function price(value, currency) {
  if (value === null || value === undefined) return MISSING
  const formatted = number(value, 2)
  return currency ? `${formatted} ${currency}` : formatted
}

export function percent(value, digits = 2) {
  if (value === null || value === undefined) return MISSING
  return `${value > 0 ? '+' : ''}${number(value, digits)}%`
}

export function ratio(value) {
  if (value === null || value === undefined) return MISSING
  return `${Math.round(value * 100)}%`
}

export function timestamp(value) {
  if (!value) return MISSING
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return MISSING
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function ageLabel(value, now = Date.now()) {
  if (!value) return 'no timestamp'
  const seconds = (now - new Date(value).getTime()) / 1000
  if (Number.isNaN(seconds)) return 'no timestamp'
  if (seconds < 90) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 48) return `${hours} h ago`
  return `${Math.round(hours / 24)} d ago`
}

// One vocabulary for freshness across every panel, so "stale" always means the
// same thing to the reader.
export function freshnessTone(status) {
  switch (status) {
    case 'cached':
    case 'current':
    case 'available':
    case 'scored':
      return 'ok'
    case 'stale':
    case 'partial':
    case 'current_cache_observation_time_unknown':
      return 'stale'
    case 'unavailable':
    case 'insufficient_data':
    case 'insufficient_news':
    case 'disabled':
      return 'missing'
    default:
      return 'unknown'
  }
}

export function sentimentWord(value) {
  if (value === null || value === undefined) return 'not analyzed'
  if (value <= -0.5) return 'strongly negative'
  if (value <= -0.15) return 'negative'
  if (value < 0.15) return 'mixed or neutral'
  if (value < 0.5) return 'positive'
  return 'strongly positive'
}
