import { useEffect, useState } from 'react'

// Recharts writes colors as SVG presentation attributes, where a raw var()
// reference does not paint. Resolve the theme's variables to concrete values and
// re-read them whenever the theme changes, so both palettes stay selected rather
// than one being an inverted copy of the other.
const TOKENS = {
  close: '--series-1',
  sma20: '--series-2',
  sma50: '--series-3',
  sma200: '--series-4',
  rsi: '--series-1',
  positive: '--diverging-positive',
  negative: '--diverging-negative',
  grid: '--gridline',
  axis: '--axis',
  muted: '--text-muted',
  surface: '--surface-1',
}

function read() {
  if (typeof window === 'undefined') return {}
  const styles = getComputedStyle(document.documentElement)
  return Object.fromEntries(
    Object.entries(TOKENS).map(([name, token]) => [name, styles.getPropertyValue(token).trim()]),
  )
}

export function useChartColors() {
  const [colors, setColors] = useState(read)
  useEffect(() => {
    const update = () => setColors(read())
    update()
    const observer = new MutationObserver(update)
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    media.addEventListener('change', update)
    return () => {
      observer.disconnect()
      media.removeEventListener('change', update)
    }
  }, [])
  return colors
}

// No draw animation: a dashboard redraws on every refresh, and a partly drawn
// line reads as missing data.
export const LINE = { strokeWidth: 2, dot: false, isAnimationActive: false }

// Legend text wears an ink token; the colored key beside it carries identity.
export const legendProps = {
  wrapperStyle: { fontSize: 12 },
  formatter: (value) => <span style={{ color: 'var(--text-secondary)' }}>{value}</span>,
}

export function axisProps(colors) {
  return { stroke: colors.axis, tick: { fill: colors.muted, fontSize: 11 } }
}

export function tooltipStyle(colors) {
  return {
    contentStyle: {
      background: colors.surface,
      border: '1px solid var(--border-hairline)',
      borderRadius: 8,
      fontSize: 12,
    },
    labelStyle: { color: 'var(--text-secondary)', fontSize: 11 },
    itemStyle: { color: 'var(--text-primary)' },
  }
}

export function sessionTick(value) {
  return value?.slice(5) ?? ''
}
