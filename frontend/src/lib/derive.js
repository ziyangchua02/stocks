import { sentimentWord } from './format.js'

// The bull and bear cases are assembled from data the backend already produced:
// model key points and risks (each with article sources) and scoring components
// above or below the neutral 50 midpoint. Nothing new is asserted here.
export function buildCases(score, analysis) {
  const bull = []
  const bear = []
  const claims = analysis?.payload?.claims
  for (const item of claims?.key_points || []) {
    bull.push({ kind: 'news', text: item.text, sources: item.sources })
  }
  for (const item of claims?.risks || []) {
    bear.push({ kind: 'news', text: item.text, sources: item.sources })
  }
  for (const row of score?.breakdown || []) {
    if (row.score === null || row.score === undefined) continue
    const target = row.score >= 50 ? bull : bear
    target.push({
      kind: 'score',
      component: row.component,
      value: row.score,
      text: describeComponent(row),
    })
  }
  for (const flag of score?.cautions || []) {
    bear.push({ kind: 'caution', text: flag.message, flag: flag.flag })
  }
  return {
    bull,
    bear,
    note:
      'Assembled from the model key points and risks above and from scoring ' +
      'components either side of the neutral midpoint of 50. It is a restatement ' +
      'of the evidence on this page, not an additional opinion.',
  }
}

export function describeComponent(row) {
  const values = (row.inputs || [])
    .filter((input) => input.status === 'scored')
    .map((input) => `${input.input.replaceAll('_', ' ')} ${formatInput(input.value)}`)
  const direction = row.score >= 50 ? 'supports' : 'weighs against'
  return values.length
    ? `${row.component.replaceAll('_', ' ')} ${direction} the score: ${values.join(', ')}.`
    : `${row.component.replaceAll('_', ' ')} ${direction} the score.`
}

function formatInput(value) {
  if (typeof value === 'boolean') return value ? 'holds' : 'does not hold'
  if (typeof value === 'number') return Number(value.toFixed(2)).toString()
  return String(value)
}

// Chart series carry only points the backend actually computed; a null stays a
// gap in the line rather than being bridged.
export function chartSeries(series = [], keys) {
  return series.map((point) => {
    const row = { session_date: point.session_date }
    for (const key of keys) row[key] = point[key] ?? null
    return row
  })
}

export function labelTone(label) {
  switch (label) {
    case 'Strong setup':
      return 'good'
    case 'Caution':
      return 'warning'
    case 'Watch':
      return 'info'
    default:
      return 'neutral'
  }
}

export function sentimentSummary(assessment) {
  if (!assessment) return { word: 'not analyzed', value: null, impact: null }
  return {
    word: sentimentWord(assessment.sentiment),
    value: assessment.sentiment,
    impact: assessment.impact,
  }
}

export function filterArticles(items, { ticker, sentiment, impact }) {
  return items.filter((article) => {
    if (ticker && !(article.tickers || []).includes(ticker)) return false
    const assessment = article.assessment
    if (sentiment && sentiment !== 'any') {
      if (!assessment) return sentiment === 'unanalyzed'
      if (sentiment === 'unanalyzed') return false
      if (sentiment === 'positive' && !(assessment.sentiment >= 0.15)) return false
      if (sentiment === 'negative' && !(assessment.sentiment <= -0.15)) return false
      if (
        sentiment === 'neutral' &&
        !(assessment.sentiment > -0.15 && assessment.sentiment < 0.15)
      )
        return false
    }
    if (impact && impact !== 'any') {
      if (!assessment) return false
      if (assessment.impact !== impact) return false
    }
    return true
  })
}

// Outcome rendering. A horizon that has not elapsed is shown as pending with the
// date it becomes measurable; nothing is estimated or back-filled.
export function outcomeText(outcome) {
  if (!outcome) return { text: 'not computed', tone: 'muted', detail: null }
  if (outcome.status === 'pending') {
    // Keep the row short: the horizon date is the useful part, the full
    // explanation stays in the cell's tooltip.
    return {
      text: 'pending',
      tone: 'muted',
      detail: outcome.target_date ? `from ${outcome.target_date}` : null,
      title: outcome.reason,
    }
  }
  if (outcome.status !== 'measured') {
    return { text: 'unavailable', tone: 'muted', detail: null, title: outcome.reason }
  }
  const excess =
    outcome.excess_return_percent === undefined
      ? null
      : `${outcome.excess_return_percent >= 0 ? '+' : ''}${outcome.excess_return_percent.toFixed(2)}% vs ${outcome.benchmark_symbol}`
  return {
    text: `${outcome.return_percent >= 0 ? '+' : ''}${outcome.return_percent.toFixed(2)}%`,
    tone: outcome.return_percent >= 0 ? 'up' : 'down',
    detail: [`session ${outcome.observed_session}`, excess, outcome.note]
      .filter(Boolean)
      .join(' · '),
  }
}

export function alertTone(severity) {
  return severity === 'attention' ? 'warning' : 'neutral'
}

export function countUnacknowledged(alerts) {
  return (alerts || []).filter((alert) => !alert.acknowledged_at).length
}
