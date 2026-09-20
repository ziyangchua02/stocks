import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { number } from '../lib/format.js'
import { LINE, axisProps, sessionTick, tooltipStyle, useChartColors } from './chartTheme.jsx'

/** One series, so no legend box: the heading names it. Reference lines mark the
 *  conventional 30/70 levels the scoring curve bends around. */
export function RsiPanel({ series }) {
  const colors = useChartColors()
  const axis = axisProps(colors)
  if (!series?.length) return null
  return (
    <ResponsiveContainer width="100%" height={140}>
      <LineChart data={series} margin={{ top: 4, right: 12, bottom: 4, left: 4 }}>
        <CartesianGrid stroke={colors.grid} vertical={false} />
        <XAxis dataKey="session_date" tickFormatter={sessionTick} minTickGap={40} {...axis} />
        <YAxis {...axis} width={58} domain={[0, 100]} ticks={[0, 30, 70, 100]} />
        <ReferenceLine y={70} stroke={colors.axis} />
        <ReferenceLine y={30} stroke={colors.axis} />
        <Tooltip {...tooltipStyle(colors)} formatter={(value) => number(value, 1)} />
        <Line
          type="monotone"
          dataKey="rsi14"
          name="RSI(14)"
          stroke={colors.rsi}
          connectNulls={false}
          {...LINE}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}

/** The histogram is MACD minus its signal line: a quantity either side of zero,
 *  so it is a diverging bar rather than a third overlaid line. Both underlying
 *  lines stay available in the tooltip. */
export function MacdPanel({ series }) {
  const colors = useChartColors()
  const axis = axisProps(colors)
  if (!series?.length) return null
  const data = series.filter((point) => point.macd_histogram !== null)
  if (!data.length) return null
  return (
    <ResponsiveContainer width="100%" height={140}>
      <BarChart data={data} margin={{ top: 4, right: 12, bottom: 4, left: 4 }}>
        <CartesianGrid stroke={colors.grid} vertical={false} />
        <XAxis dataKey="session_date" tickFormatter={sessionTick} minTickGap={40} {...axis} />
        <YAxis {...axis} width={58} tickFormatter={(value) => number(value, 1)} />
        <ReferenceLine y={0} stroke={colors.axis} />
        <Tooltip
          {...tooltipStyle(colors)}
          formatter={(value, name) => [number(value, 3), name]}
          labelFormatter={(label, payload) => {
            const point = payload?.[0]?.payload
            if (!point) return label
            return `${label} · MACD ${number(point.macd, 3)} · signal ${number(point.macd_signal, 3)}`
          }}
        />
        <Bar dataKey="macd_histogram" name="MACD histogram" maxBarSize={5} isAnimationActive={false}>
          {data.map((point) => (
            <Cell
              key={point.session_date}
              fill={point.macd_histogram >= 0 ? colors.positive : colors.negative}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
