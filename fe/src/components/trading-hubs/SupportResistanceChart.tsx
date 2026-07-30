import { useMemo, useState } from 'react'
import {
  Bar, BarChart, CartesianGrid, ComposedChart, Line, ReferenceArea, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'

export type SRChartBar = { time: string; open: number; high: number; low: number; close: number; volume?: number | null }
export type SRTrendlinePoint = { time: string; price: number }
export type SRTrendline = { type: 'ascending' | 'descending'; points: SRTrendlinePoint[] }
type Bar_ = SRChartBar
type Trendline = SRTrendline

const EMA_COLORS: Record<string, string> = {
  '5': '#facc15', '9': '#a78bfa', '20': '#38bdf8', '50': '#fb923c', '200': '#f472b6',
}
const BULL_COLOR = '#10b981'
const BEAR_COLOR = '#f43f5e'

function fmtTime(t: string) {
  const d = new Date(t.replace(' ', 'T'))
  if (Number.isNaN(d.getTime())) return t
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function fmtNum(v: number) {
  return v.toLocaleString('en-IN', { maximumFractionDigits: 2 })
}

// Custom Recharts Bar `shape`: recharts maps the `range` (=[low, high]) prop
// to x/y/width/height via the y-axis scale same as any other Bar, so we only
// need to draw the wick (full high-low) and the body (open-close) within
// that box using the ratio between the two.
function CandlestickShape(props: any) {
  const { x, y, width, height, low, high, open, close } = props
  if (high == null || low == null || high === low) return null
  const isBullish = close >= open
  const color = isBullish ? BULL_COLOR : BEAR_COLOR
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

export function SupportResistanceChart({
  chartData, supportZone, resistanceZone, trendlines, lastClose, emas = {}, rsi, chartType = 'candles',
}: {
  chartData: Bar_[]
  supportZone: [number, number] | null
  resistanceZone: [number, number] | null
  trendlines: Trendline[]
  lastClose?: number | null
  emas?: Record<string, Array<{ time: string; value: number }>>
  rsi?: Array<{ time: string; value: number }> | null
  chartType?: 'candles' | 'line'
}) {
  const [refLeft, setRefLeft] = useState<string | null>(null)
  const [refRight, setRefRight] = useState<string | null>(null)
  const [zoomRange, setZoomRange] = useState<[number, number] | null>(null)

  const emaPeriods = Object.keys(emas).sort((a, b) => Number(a) - Number(b))
  // Merge each EMA series into the same row-per-timestamp shape the price
  // chart uses, so a single ComposedChart can plot price + every EMA line
  // together without a separate merge step per render.
  const emaByTime: Record<string, Record<string, number>> = {}
  for (const period of emaPeriods) {
    for (const pt of emas[period]) {
      emaByTime[pt.time] = emaByTime[pt.time] || {}
      emaByTime[pt.time][period] = pt.value
    }
  }
  const merged = useMemo(
    () => chartData.map((bar) => ({ ...bar, ...(emaByTime[bar.time] || {}), range: [bar.low, bar.high] })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [chartData, emas],
  )

  // Reset any in-flight/applied zoom whenever the underlying series changes
  // (new ticker, new date range, refreshed data) so a stale index range
  // can't be applied to a differently-sized dataset.
  const dataKeyForReset = chartData.length ? `${chartData[0].time}|${chartData[chartData.length - 1].time}|${chartData.length}` : ''
  const [lastResetKey, setLastResetKey] = useState(dataKeyForReset)
  if (dataKeyForReset !== lastResetKey) {
    setLastResetKey(dataKeyForReset)
    if (zoomRange) setZoomRange(null)
    if (refLeft || refRight) { setRefLeft(null); setRefRight(null) }
  }

  const timeIndex = useMemo(() => {
    const m = new Map<string, number>()
    merged.forEach((bar, i) => m.set(bar.time, i))
    return m
  }, [merged])

  const view = zoomRange ? merged.slice(zoomRange[0], zoomRange[1] + 1) : merged
  const viewStart = view[0]?.time
  const viewEnd = view[view.length - 1]?.time
  const viewChartData = zoomRange ? chartData.slice(zoomRange[0], zoomRange[1] + 1) : chartData
  const viewRsi = rsi && viewStart != null && viewEnd != null
    ? rsi.filter((p) => p.time >= viewStart && p.time <= viewEnd)
    : rsi

  const handleMouseDown = (e: any) => {
    if (e?.activeLabel != null) setRefLeft(e.activeLabel)
  }
  const handleMouseMove = (e: any) => {
    if (refLeft != null && e?.activeLabel != null) setRefRight(e.activeLabel)
  }
  const handleMouseUp = () => {
    if (refLeft != null && refRight != null && refLeft !== refRight) {
      const i1 = timeIndex.get(refLeft)
      const i2 = timeIndex.get(refRight)
      if (i1 != null && i2 != null && Math.abs(i1 - i2) >= 2) {
        setZoomRange([Math.min(i1, i2), Math.max(i1, i2)])
      }
    }
    setRefLeft(null)
    setRefRight(null)
  }
  const resetZoom = () => setZoomRange(null)

  if (!chartData?.length) return null

  const lows = view.map((b) => b.low)
  const highs = view.map((b) => b.high)
  const emaValues = emaPeriods.flatMap((p) => (emas[p] || []).filter((pt) => pt.time >= (viewStart ?? '') && pt.time <= (viewEnd ?? '')).map((pt) => pt.value))
  const padding = (Math.max(...highs) - Math.min(...lows)) * 0.05 || 1
  const yMin = Math.min(...lows, ...emaValues, ...(supportZone ?? []), ...(resistanceZone ?? [])) - padding
  const yMax = Math.max(...highs, ...emaValues, ...(supportZone ?? []), ...(resistanceZone ?? [])) + padding

  const hasVolume = chartData.some((b) => b.volume != null)
  const hasRsi = Boolean(rsi && rsi.length)

  return (
    <div className="space-y-2">
      <div className="relative h-72 w-full select-none">
        {zoomRange && (
          <button
            type="button"
            onClick={resetZoom}
            className="absolute right-2 top-0 z-10 rounded border border-slate-700 bg-slate-900/80 px-2 py-0.5 text-[11px] text-slate-300 hover:bg-slate-800"
          >
            Reset zoom
          </button>
        )}
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={view}
            margin={{ top: 8, right: 16, left: 4, bottom: 4 }}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="time" tickFormatter={fmtTime} tick={{ fill: '#94a3b8', fontSize: 11 }} minTickGap={40} allowDataOverflow />
            <YAxis
              domain={[yMin, yMax]}
              tick={{ fill: '#94a3b8', fontSize: 11 }}
              width={64}
              tickFormatter={fmtNum}
              allowDataOverflow
            />
            <Tooltip
              contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
              labelStyle={{ color: '#e2e8f0' }}
              labelFormatter={(t) => String(t)}
              formatter={(value, name) => [fmtNum(Number(value)), String(name)]}
            />

            {supportZone && (
              <ReferenceArea
                y1={supportZone[0]} y2={supportZone[1]}
                fill="#10b981" fillOpacity={0.15} stroke="#10b981" strokeOpacity={0.4} strokeDasharray="3 3"
                label={{ value: 'Support', position: 'insideBottomLeft', fill: '#34d399', fontSize: 11 }}
              />
            )}
            {resistanceZone && (
              <ReferenceArea
                y1={resistanceZone[0]} y2={resistanceZone[1]}
                fill="#f43f5e" fillOpacity={0.15} stroke="#f43f5e" strokeOpacity={0.4} strokeDasharray="3 3"
                label={{ value: 'Resistance', position: 'insideTopLeft', fill: '#fb7185', fontSize: 11 }}
              />
            )}

            {trendlines.map((tl, i) => {
              const pts = tl.points
              if (pts.length < 2) return null
              const first = pts[0]
              const last = pts[pts.length - 1]
              return (
                <ReferenceLine
                  key={`${tl.type}-${i}`}
                  segment={[{ x: first.time, y: first.price }, { x: last.time, y: last.price }]}
                  stroke={tl.type === 'ascending' ? '#38bdf8' : '#fb923c'}
                  strokeDasharray="6 3"
                  strokeWidth={1.5}
                  ifOverflow="extendDomain"
                />
              )
            })}

            {lastClose != null && (
              <ReferenceLine
                y={lastClose}
                stroke="#e2e8f0"
                strokeDasharray="2 2"
                label={{ value: `Now ${fmtNum(lastClose)}`, position: 'insideTopRight', fill: '#e2e8f0', fontSize: 11 }}
              />
            )}

            {emaPeriods.map((period) => (
              <Line
                key={period}
                type="monotone"
                dataKey={period}
                stroke={EMA_COLORS[period] ?? '#94a3b8'}
                strokeWidth={1.5}
                dot={false}
                name={`${period} EMA`}
                connectNulls
                isAnimationActive={false}
              />
            ))}

            {chartType === 'candles' ? (
              <Bar dataKey="range" name="Price" shape={CandlestickShape} isAnimationActive={false} />
            ) : (
              <Line type="monotone" dataKey="close" stroke="#f8fafc" strokeWidth={1.5} dot={false} name="Close" isAnimationActive={false} />
            )}

            {refLeft != null && refRight != null && (
              <ReferenceArea x1={refLeft} x2={refRight} strokeOpacity={0.3} fill="#38bdf8" fillOpacity={0.15} />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <p className="text-[10px] text-slate-600">Drag across the chart to zoom into a section.</p>

      {hasVolume && (
        <div className="h-20 w-full">
          <p className="mb-1 text-[10px] uppercase tracking-wider text-slate-500">Volume</p>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={viewChartData} margin={{ top: 0, right: 16, left: 4, bottom: 0 }}>
              <XAxis dataKey="time" hide allowDataOverflow />
              <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} width={64} tickFormatter={(v: number) => (v >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `${(v / 1e3).toFixed(0)}K` : String(v))} />
              <Tooltip
                contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
                labelStyle={{ color: '#e2e8f0' }}
                formatter={(value) => [fmtNum(Number(value)), 'Volume']}
              />
              <Bar dataKey="volume" fill="#475569" radius={[1, 1, 0, 0]} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {hasRsi && (
        <div className="h-24 w-full">
          <p className="mb-1 text-[10px] uppercase tracking-wider text-slate-500">RSI (14)</p>
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={viewRsi ?? []} margin={{ top: 0, right: 16, left: 4, bottom: 0 }}>
              <XAxis dataKey="time" hide allowDataOverflow />
              <YAxis domain={[0, 100]} ticks={[0, 30, 50, 70, 100]} tick={{ fill: '#94a3b8', fontSize: 10 }} width={64} />
              <ReferenceLine y={70} stroke="#f43f5e" strokeDasharray="3 3" strokeOpacity={0.6} />
              <ReferenceLine y={30} stroke="#10b981" strokeDasharray="3 3" strokeOpacity={0.6} />
              <Tooltip
                contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
                labelStyle={{ color: '#e2e8f0' }}
                formatter={(value) => [Number(value).toFixed(1), 'RSI']}
              />
              <Line type="monotone" dataKey="value" stroke="#c084fc" strokeWidth={1.5} dot={false} name="RSI" isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="flex flex-wrap gap-3 text-[11px] text-slate-500">
        {chartType === 'candles' ? (
          <>
            <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-sm" style={{ backgroundColor: BULL_COLOR }} /> Bullish candle</span>
            <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-sm" style={{ backgroundColor: BEAR_COLOR }} /> Bearish candle</span>
          </>
        ) : null}
        <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-emerald-500/60" /> Support zone</span>
        <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-rose-500/60" /> Resistance zone</span>
        {trendlines.some((t) => t.type === 'ascending') && (
          <span className="inline-flex items-center gap-1"><span className="h-0.5 w-3 bg-sky-400" /> Ascending trendline</span>
        )}
        {trendlines.some((t) => t.type === 'descending') && (
          <span className="inline-flex items-center gap-1"><span className="h-0.5 w-3 bg-orange-400" /> Descending trendline</span>
        )}
        {emaPeriods.map((p) => (
          <span key={p} className="inline-flex items-center gap-1">
            <span className="h-0.5 w-3" style={{ backgroundColor: EMA_COLORS[p] ?? '#94a3b8' }} /> {p} EMA
          </span>
        ))}
      </div>
    </div>
  )
}
