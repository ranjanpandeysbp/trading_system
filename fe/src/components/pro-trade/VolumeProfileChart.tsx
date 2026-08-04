import { useMemo, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Chip } from '../ui/Chip'

export type VpChartBar = {
  time: string
  open: number
  high: number
  low: number
  close: number
  volume?: number | null
}

export type VpLevel = { label: string; price: number; color: string }
export type VpHistBin = { price: number; volume: number }
export type VpWaveSegment = {
  label: string
  startTime: string
  endTime: string
  startPrice: number
  endPrice: number
  color: string
}

const BULL = '#10b981'
const BEAR = '#f43f5e'

function fmtTime(t: string) {
  const d = new Date(t.replace(' ', 'T'))
  if (Number.isNaN(d.getTime())) return t
  return d.toLocaleString('en-IN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function fmtNum(v: number) {
  return v.toLocaleString('en-IN', { maximumFractionDigits: 2 })
}

function PriceTooltip({ active, payload, label, chartType }: any) {
  if (!active || !payload?.length) return null
  const row = payload[0]?.payload
  if (!row) return null
  return (
    <div style={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 12, padding: '8px 10px' }}>
      <p style={{ color: '#e2e8f0', marginBottom: 4 }}>{String(label)}</p>
      {chartType === 'candles' ? (
        <>
          <p style={{ color: '#94a3b8' }}>O: <span style={{ color: '#e2e8f0' }}>{fmtNum(row.open)}</span></p>
          <p style={{ color: '#94a3b8' }}>H: <span style={{ color: '#e2e8f0' }}>{fmtNum(row.high)}</span></p>
          <p style={{ color: '#94a3b8' }}>L: <span style={{ color: '#e2e8f0' }}>{fmtNum(row.low)}</span></p>
          <p style={{ color: '#94a3b8' }}>C: <span style={{ color: '#e2e8f0' }}>{fmtNum(row.close)}</span></p>
        </>
      ) : (
        <p style={{ color: '#94a3b8' }}>Close: <span style={{ color: '#e2e8f0' }}>{fmtNum(row.close)}</span></p>
      )}
      {row.volume != null && (
        <p style={{ color: '#94a3b8' }}>Vol: <span style={{ color: '#e2e8f0' }}>{fmtNum(Number(row.volume))}</span></p>
      )}
    </div>
  )
}

function CandlestickShape(props: any) {
  const { x, y, width, height, low, high, open, close } = props
  if (high == null || low == null || high === low) return null
  const isBullish = close >= open
  const color = isBullish ? BULL : BEAR
  const ratio = height / (high - low)
  const bodyTop = y + (high - Math.max(open, close)) * ratio
  const bodyHeight = Math.max(1, Math.abs(close - open) * ratio)
  const cx = x + width / 2
  return (
    <g>
      <line x1={cx} y1={y} x2={cx} y2={y + height} stroke={color} strokeWidth={1} />
      <rect x={x} y={bodyTop} width={Math.max(1, width)} height={bodyHeight} fill={color} stroke={color} />
    </g>
  )
}

function waveDotRenderer(wave: VpWaveSegment, dataKey: string) {
  return (props: any) => {
    const { cx, cy, payload, key } = props
    if (cx == null || cy == null || payload?.[dataKey] == null) return <g key={key} />
    const isEnd = payload.time === wave.endTime
    return (
      <g key={key}>
        <circle cx={cx} cy={cy} r={isEnd ? 4 : 3} fill={wave.color} stroke="#0f172a" strokeWidth={1} />
        {isEnd && (
          <text x={cx} y={cy - 10} fill={wave.color} fontSize={11} fontWeight={700} textAnchor="middle">
            {wave.label}
          </text>
        )}
      </g>
    )
  }
}

export function VolumeProfileChart({
  chartData,
  levels = [],
  histogram = [],
  waves = [],
}: {
  chartData: VpChartBar[]
  levels?: VpLevel[]
  histogram?: VpHistBin[]
  waves?: VpWaveSegment[]
}) {
  const [chartType, setChartType] = useState<'candles' | 'line'>('candles')

  const merged = useMemo(() => {
    const base = chartData.map((b) => ({ ...b, range: [b.low, b.high] as [number, number] }))
    if (!waves.length) return base
    return base.map((row) => {
      const extra: Record<string, number | null> = {}
      waves.forEach((w, i) => {
        const key = `__wave_${i}`
        if (row.time === w.startTime) extra[key] = w.startPrice
        else if (row.time === w.endTime) extra[key] = w.endPrice
        else extra[key] = null
      })
      return { ...row, ...extra }
    })
  }, [chartData, waves])

  if (!chartData.length) {
    return <p className="text-xs text-slate-500">No chart data for this ticker.</p>
  }

  const lows = merged.map((b) => b.low)
  const highs = merged.map((b) => b.high)
  const levelPrices = levels.map((l) => l.price)
  const wavePrices = waves.flatMap((w) => [w.startPrice, w.endPrice])
  const pad = (Math.max(...highs) - Math.min(...lows)) * 0.05 || 1
  const yMin = Math.min(...lows, ...levelPrices, ...wavePrices) - pad
  const yMax = Math.max(...highs, ...levelPrices, ...wavePrices) + pad

  const histSorted = useMemo(
    () => [...histogram].sort((a, b) => a.price - b.price),
    [histogram],
  )

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Chip selected={chartType === 'candles'} onClick={() => setChartType('candles')}>
          Candles
        </Chip>
        <Chip selected={chartType === 'line'} onClick={() => setChartType('line')}>
          Line
        </Chip>
        <div className="ml-auto flex flex-wrap gap-3 text-[11px] text-slate-500">
          {waves.map((w, i) => (
            <span key={`wave-legend-${i}`} className="inline-flex items-center gap-1">
              <span className="inline-block h-2 w-2 rounded-full" style={{ background: w.color }} />
              Wave {w.label}
            </span>
          ))}
          {levels.map((l) => (
            <span key={l.label} className="inline-flex items-center gap-1">
              <span className="inline-block h-2 w-2 rounded-full" style={{ background: l.color }} />
              {l.label} {fmtNum(l.price)}
            </span>
          ))}
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-[1fr_160px]">
        <div className="h-72 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={merged} margin={{ top: 8, right: 12, left: 4, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="time" tickFormatter={fmtTime} tick={{ fill: '#94a3b8', fontSize: 10 }} minTickGap={36} />
              <YAxis
                domain={[yMin, yMax]}
                tick={{ fill: '#94a3b8', fontSize: 10 }}
                width={60}
                tickFormatter={fmtNum}
              />
              <Tooltip content={<PriceTooltip chartType={chartType} />} />
              {levels.map((l) => (
                <ReferenceLine
                  key={l.label}
                  y={l.price}
                  stroke={l.color}
                  strokeDasharray="4 3"
                  strokeWidth={1.5}
                  label={{ value: l.label, position: 'insideTopRight', fill: l.color, fontSize: 10 }}
                />
              ))}
              {chartType === 'candles' ? (
                <Bar dataKey="range" name="Price" shape={CandlestickShape} isAnimationActive={false} />
              ) : (
                <Line
                  type="monotone"
                  dataKey="close"
                  stroke="#38bdf8"
                  strokeWidth={1.75}
                  dot={false}
                  isAnimationActive={false}
                  name="Close"
                />
              )}
              {waves.map((w, i) => {
                const key = `__wave_${i}`
                return (
                  <Line
                    key={key}
                    dataKey={key}
                    stroke={w.color}
                    strokeWidth={2.5}
                    dot={waveDotRenderer(w, key)}
                    connectNulls
                    isAnimationActive={false}
                    legendType="none"
                    name={`Wave ${w.label}`}
                  />
                )
              })}
            </ComposedChart>
          </ResponsiveContainer>
        </div>

        {histSorted.length > 0 && (
          <div className="h-72 w-full">
            <p className="mb-1 text-center text-[10px] uppercase tracking-wide text-slate-500">Volume profile</p>
            <ResponsiveContainer width="100%" height="90%">
              <BarChart
                data={histSorted}
                layout="vertical"
                margin={{ top: 4, right: 8, left: 4, bottom: 4 }}
              >
                <XAxis type="number" hide />
                <YAxis
                  type="number"
                  dataKey="price"
                  domain={[yMin, yMax]}
                  tick={{ fill: '#64748b', fontSize: 9 }}
                  width={44}
                  tickFormatter={fmtNum}
                />
                <Tooltip
                  formatter={(v: any) => [fmtNum(Number(v)), 'Volume']}
                  labelFormatter={(_, p: any) => `Price ${fmtNum(Number(p?.[0]?.payload?.price ?? 0))}`}
                  contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 11 }}
                />
                <Bar dataKey="volume" fill="#6366f1" fillOpacity={0.75} isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </div>
  )
}
