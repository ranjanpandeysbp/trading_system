import { useMemo, useState, type ReactNode } from 'react'
import {
  Bar, BarChart, CartesianGrid, ComposedChart, Line, ReferenceArea, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'

export type SRChartBar = { time: string; open: number; high: number; low: number; close: number; volume?: number | null }
export type SRTrendlinePoint = { time: string; price: number }
export type SRTrendline = { type: 'ascending' | 'descending'; points: SRTrendlinePoint[] }
export type SRFibonacciLevel = { ratio: number; price: number }
export type SRFibonacci = {
  trend: 'uptrend' | 'downtrend'
  swing_low: number
  swing_high: number
  levels: SRFibonacciLevel[]
  nearest_level: SRFibonacciLevel
  at_key_level: boolean
}
export type SRZone = { top: number; bottom: number; type: 'demand' | 'supply' | 'bullish' | 'bearish'; origin_time: string; mitigated: boolean }
export type SRLevel = { price: number; label: string; color?: string }
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

// A custom tooltip content is needed because the candlestick Bar's `dataKey`
// is a [low, high] array (so recharts can size the bar via the y-axis scale)
// — the default Tooltip formatter calls Number() on that array and renders
// NaN. This reads open/high/low/close straight off the row instead.
function PriceTooltip({ active, payload, label, chartType }: any) {
  if (!active || !payload || !payload.length) return null
  const row = payload[0]?.payload
  if (!row) return null
  const overlays = payload.filter((p: any) => p.dataKey !== 'range' && p.dataKey !== 'close' && p.value != null)
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
      {overlays.map((p: any) => (
        <p key={p.dataKey} style={{ color: p.color }}>{p.name}: {fmtNum(Number(p.value))}</p>
      ))}
    </div>
  )
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
  chartData, supportZone = null, resistanceZone = null, trendlines = [], lastClose, emas = {}, rsi, chartType = 'candles', fibonacci = null,
  supplyDemandZones = [], orderBlocks = [], levels = [], readingGuide,
}: {
  chartData: Bar_[]
  supportZone?: [number, number] | null
  resistanceZone?: [number, number] | null
  trendlines?: Trendline[]
  lastClose?: number | null
  emas?: Record<string, Array<{ time: string; value: number }>>
  rsi?: Array<{ time: string; value: number }> | null
  chartType?: 'candles' | 'line'
  fibonacci?: SRFibonacci | null
  supplyDemandZones?: SRZone[]
  orderBlocks?: SRZone[]
  /** Extra labeled reference lines (e.g. entry/SL/TP) — generic, any strategy can pass these. */
  levels?: SRLevel[]
  /** Short laymen "how to read this chart" caption, shown below it. */
  readingGuide?: string
}) {
  const [refLeft, setRefLeft] = useState<string | null>(null)
  const [refRight, setRefRight] = useState<string | null>(null)
  const [zoomRange, setZoomRange] = useState<[number, number] | null>(null)
  const [hidden, setHidden] = useState<Set<string>>(new Set())
  const toggleHidden = (key: string) => {
    setHidden((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }
  const isHidden = (key: string) => hidden.has(key)

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
  const visibleEmaPeriods = emaPeriods.filter((p) => !isHidden(`ema:${p}`))
  const emaValues = visibleEmaPeriods.flatMap((p) => (emas[p] || []).filter((pt) => pt.time >= (viewStart ?? '') && pt.time <= (viewEnd ?? '')).map((pt) => pt.value))
  const fibValues = fibonacci && !isHidden('fibonacci') ? (fibonacci.levels ?? []).map((lv) => lv.price) : []
  const visibleSupplyDemand = isHidden('supplyDemand') ? [] : (supplyDemandZones ?? [])
  const visibleOrderBlocks = isHidden('orderBlocks') ? [] : (orderBlocks ?? [])
  const zoneValues = [...visibleSupplyDemand, ...visibleOrderBlocks].flatMap((z) => [z.top, z.bottom])
  const visibleLevels = (levels ?? []).filter((lv) => !isHidden(`level:${lv.label}`))
  const levelValues = visibleLevels.map((lv) => lv.price)
  const visibleSupportZone = supportZone && !isHidden('supportZone') ? supportZone : null
  const visibleResistanceZone = resistanceZone && !isHidden('resistanceZone') ? resistanceZone : null
  const visibleTrendlines = isHidden('trendlines') ? [] : (trendlines ?? [])
  const padding = (Math.max(...highs) - Math.min(...lows)) * 0.05 || 1
  const yMin = Math.min(...lows, ...emaValues, ...fibValues, ...zoneValues, ...levelValues, ...(visibleSupportZone ?? []), ...(visibleResistanceZone ?? [])) - padding
  const yMax = Math.max(...highs, ...emaValues, ...fibValues, ...zoneValues, ...levelValues, ...(visibleSupportZone ?? []), ...(visibleResistanceZone ?? [])) + padding

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
            <Tooltip content={<PriceTooltip chartType={chartType} />} />

            {visibleSupportZone && (
              <ReferenceArea
                y1={visibleSupportZone[0]} y2={visibleSupportZone[1]}
                fill="#10b981" fillOpacity={0.15} stroke="#10b981" strokeOpacity={0.4} strokeDasharray="3 3"
                label={{
                  value: visibleSupportZone[0] === visibleSupportZone[1]
                    ? `Support ${fmtNum(visibleSupportZone[0])}`
                    : `Support ${fmtNum(visibleSupportZone[0])}–${fmtNum(visibleSupportZone[1])}`,
                  position: 'insideBottomLeft', fill: '#34d399', fontSize: 11,
                }}
              />
            )}
            {visibleResistanceZone && (
              <ReferenceArea
                y1={visibleResistanceZone[0]} y2={visibleResistanceZone[1]}
                fill="#f43f5e" fillOpacity={0.15} stroke="#f43f5e" strokeOpacity={0.4} strokeDasharray="3 3"
                label={{
                  value: visibleResistanceZone[0] === visibleResistanceZone[1]
                    ? `Resistance ${fmtNum(visibleResistanceZone[0])}`
                    : `Resistance ${fmtNum(visibleResistanceZone[0])}–${fmtNum(visibleResistanceZone[1])}`,
                  position: 'insideTopLeft', fill: '#fb7185', fontSize: 11,
                }}
              />
            )}

            {visibleSupplyDemand.map((z, i) => (
              <ReferenceArea
                key={`sd-${i}`}
                y1={z.bottom} y2={z.top}
                fill={z.type === 'demand' ? '#2dd4bf' : '#fbbf24'}
                fillOpacity={0.12}
                stroke={z.type === 'demand' ? '#2dd4bf' : '#fbbf24'}
                strokeOpacity={0.5}
                strokeDasharray="2 4"
                label={{ value: z.type === 'demand' ? 'Demand' : 'Supply', position: 'insideBottomRight', fill: z.type === 'demand' ? '#5eead4' : '#fcd34d', fontSize: 10 }}
              />
            ))}

            {visibleOrderBlocks.map((ob, i) => (
              <ReferenceArea
                key={`ob-${i}`}
                y1={ob.bottom} y2={ob.top}
                fill={ob.type === 'bullish' ? '#22d3ee' : '#818cf8'}
                fillOpacity={0.12}
                stroke={ob.type === 'bullish' ? '#22d3ee' : '#818cf8'}
                strokeOpacity={0.5}
                strokeDasharray="1 3"
                label={{ value: ob.type === 'bullish' ? 'Bull OB' : 'Bear OB', position: 'insideTopRight', fill: ob.type === 'bullish' ? '#67e8f9' : '#a5b4fc', fontSize: 10 }}
              />
            ))}

            {visibleTrendlines.map((tl, i) => {
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

            {!isHidden('fibonacci') && (fibonacci?.levels ?? []).map((lv) => (
              <ReferenceLine
                key={`fib-${lv.ratio}`}
                y={lv.price}
                stroke="#a78bfa"
                strokeOpacity={0.5}
                strokeDasharray="4 2"
                label={{ value: `${(lv.ratio * 100).toFixed(1)}% ${fmtNum(lv.price)}`, position: 'insideBottomRight', fill: '#c4b5fd', fontSize: 10 }}
                ifOverflow="extendDomain"
              />
            ))}

            {lastClose != null && !isHidden('lastClose') && (
              <ReferenceLine
                y={lastClose}
                stroke="#e2e8f0"
                strokeDasharray="2 2"
                label={{ value: `Now ${fmtNum(lastClose)}`, position: 'insideTopRight', fill: '#e2e8f0', fontSize: 11 }}
              />
            )}

            {visibleLevels.map((lv, i) => (
              <ReferenceLine
                key={`level-${i}-${lv.price}`}
                y={lv.price}
                stroke={lv.color ?? '#facc15'}
                strokeWidth={1.5}
                strokeDasharray="5 3"
                label={{ value: lv.label, position: 'insideBottomRight', fill: lv.color ?? '#facc15', fontSize: 11 }}
                ifOverflow="extendDomain"
              />
            ))}

            {visibleEmaPeriods.map((period) => (
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
      <p className="text-[10px] text-slate-600">
        Drag across the chart to zoom into a section. Click a chip below to hide/show that line.
      </p>

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

      <div className="flex flex-wrap items-center gap-2 text-[11px]">
        {(supportZone || resistanceZone || trendlines.length > 0 || fibonacci || supplyDemandZones.length > 0 ||
          orderBlocks.length > 0 || levels.length > 0 || emaPeriods.length > 0) && (
          <>
            <button
              type="button"
              onClick={() => setHidden(new Set())}
              className="rounded-full border border-slate-700/80 bg-slate-800/40 px-2.5 py-1 text-slate-400 hover:border-slate-600 hover:text-slate-300"
            >
              Show all
            </button>
            <button
              type="button"
              onClick={() => {
                const all = new Set<string>()
                if (supportZone) all.add('supportZone')
                if (resistanceZone) all.add('resistanceZone')
                if (trendlines.length) all.add('trendlines')
                if (fibonacci) all.add('fibonacci')
                if (supplyDemandZones.length) all.add('supplyDemand')
                if (orderBlocks.length) all.add('orderBlocks')
                if (lastClose != null) all.add('lastClose')
                emaPeriods.forEach((p) => all.add(`ema:${p}`))
                levels.forEach((lv) => all.add(`level:${lv.label}`))
                setHidden(all)
              }}
              className="rounded-full border border-slate-700/80 bg-slate-800/40 px-2.5 py-1 text-slate-400 hover:border-slate-600 hover:text-slate-300"
            >
              Hide all
            </button>
          </>
        )}
        {chartType === 'candles' ? (
          <>
            <span className="inline-flex items-center gap-1 text-slate-500"><span className="h-2 w-2 rounded-sm" style={{ backgroundColor: BULL_COLOR }} /> Bullish candle</span>
            <span className="inline-flex items-center gap-1 text-slate-500"><span className="h-2 w-2 rounded-sm" style={{ backgroundColor: BEAR_COLOR }} /> Bearish candle</span>
          </>
        ) : null}
        {supportZone && (
          <LegendToggle active={!isHidden('supportZone')} color="#34d399" onClick={() => toggleHidden('supportZone')}>
            Support zone
          </LegendToggle>
        )}
        {resistanceZone && (
          <LegendToggle active={!isHidden('resistanceZone')} color="#fb7185" onClick={() => toggleHidden('resistanceZone')}>
            Resistance zone
          </LegendToggle>
        )}
        {trendlines.length > 0 && (
          <LegendToggle active={!isHidden('trendlines')} color="#38bdf8" onClick={() => toggleHidden('trendlines')}>
            Trendlines
          </LegendToggle>
        )}
        {emaPeriods.map((p) => (
          <LegendToggle key={p} active={!isHidden(`ema:${p}`)} color={EMA_COLORS[p] ?? '#94a3b8'} onClick={() => toggleHidden(`ema:${p}`)}>
            {p} EMA
          </LegendToggle>
        ))}
        {fibonacci && (
          <LegendToggle active={!isHidden('fibonacci')} color="#a78bfa" onClick={() => toggleHidden('fibonacci')}>
            Fibonacci ({fibonacci.trend})
          </LegendToggle>
        )}
        {supplyDemandZones.length > 0 && (
          <LegendToggle active={!isHidden('supplyDemand')} color="#2dd4bf" onClick={() => toggleHidden('supplyDemand')}>
            Supply / Demand zones
          </LegendToggle>
        )}
        {orderBlocks.length > 0 && (
          <LegendToggle active={!isHidden('orderBlocks')} color="#818cf8" onClick={() => toggleHidden('orderBlocks')}>
            Order blocks
          </LegendToggle>
        )}
        {lastClose != null && (
          <LegendToggle active={!isHidden('lastClose')} color="#e2e8f0" onClick={() => toggleHidden('lastClose')}>
            Now line
          </LegendToggle>
        )}
        {levels.map((lv) => (
          <LegendToggle
            key={lv.label}
            active={!isHidden(`level:${lv.label}`)}
            color={lv.color ?? '#facc15'}
            onClick={() => toggleHidden(`level:${lv.label}`)}
          >
            {lv.label}
          </LegendToggle>
        ))}
      </div>
      {readingGuide && (
        <p className="rounded-lg border border-slate-800/60 bg-slate-950/40 px-3 py-2 text-xs leading-relaxed text-slate-400">
          💡 <strong className="font-medium text-slate-300">How to read this chart:</strong> {readingGuide}
        </p>
      )}
    </div>
  )
}

function LegendToggle({
  active,
  color,
  onClick,
  children,
}: {
  active: boolean
  color: string
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title="Click to toggle this line"
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 transition-colors ${
        active ? 'border-slate-700/70 text-slate-400' : 'border-slate-800 text-slate-600 line-through'
      }`}
    >
      <span className="inline-block h-2 w-2 rounded-full" style={{ background: active ? color : '#475569' }} />
      {children}
    </button>
  )
}
