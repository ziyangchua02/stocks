import { useState } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { number } from '../lib/format.js'
import {
  LINE,
  axisProps,
  legendProps,
  sessionTick,
  tooltipStyle,
  useChartColors,
} from './chartTheme.jsx'

const OVERLAYS = [
  { key: 'close', name: 'Close', token: 'close' },
  { key: 'sma20', name: 'SMA 20', token: 'sma20' },
  { key: 'sma50', name: 'SMA 50', token: 'sma50' },
  { key: 'sma200', name: 'SMA 200', token: 'sma200' },
]

/** Close with its moving-average overlays. Gaps stay gaps: a session the backend
 *  could not compute is never bridged. A table view is available because two of
 *  the four light-mode series sit below 3:1 contrast on the surface. */
export default function PriceChart({ series, currency }) {
  const [showTable, setShowTable] = useState(false)
  const colors = useChartColors()
  const axis = axisProps(colors)
  if (!series?.length) return null
  const recent = series.slice(-30).reverse()

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <p className="text-xs text-ink-secondary">
          Daily close and moving averages, completed sessions only
          {currency ? ` (${currency})` : ''}
        </p>
        <button
          type="button"
          className="rounded-md border border-hairline px-2 py-1 text-xs text-ink-secondary"
          onClick={() => setShowTable((value) => !value)}
        >
          {showTable ? 'Hide values' : 'Show values'}
        </button>
      </div>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={series} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
          <CartesianGrid stroke={colors.grid} vertical={false} />
          <XAxis dataKey="session_date" tickFormatter={sessionTick} minTickGap={40} {...axis} />
          <YAxis
            {...axis}
            width={58}
            domain={['auto', 'auto']}
            tickFormatter={(value) => number(value, 0)}
          />
          <Tooltip {...tooltipStyle(colors)} formatter={(value) => number(value, 2)} />
          <Legend {...legendProps} />
          {OVERLAYS.map((overlay) => (
            <Line
              key={overlay.key}
              type="monotone"
              dataKey={overlay.key}
              name={overlay.name}
              stroke={colors[overlay.token]}
              connectNulls={false}
              {...LINE}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
      {showTable ? (
        <div className="mt-3 max-h-64 overflow-auto">
          <table className="tabular w-full text-left text-xs">
            <thead className="sticky top-0 bg-surface text-ink-secondary">
              <tr>
                <th className="py-1 pr-3 font-medium">Session</th>
                {OVERLAYS.map((overlay) => (
                  <th key={overlay.key} className="py-1 pr-3 font-medium">
                    {overlay.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {recent.map((row) => (
                <tr key={row.session_date} className="border-t border-hairline">
                  <td className="py-1 pr-3 text-ink-secondary">{row.session_date}</td>
                  {OVERLAYS.map((overlay) => (
                    <td key={overlay.key} className="py-1 pr-3">
                      {row[overlay.key] === null || row[overlay.key] === undefined
                        ? 'not computed'
                        : number(row[overlay.key], 2)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-1 text-xs text-ink-muted">Most recent 30 completed sessions.</p>
        </div>
      ) : null}
    </div>
  )
}
