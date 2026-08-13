import { useMemo, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { ChartStreamControls, useLiveChartData } from '../charts/chartStreaming'
import {
  ChartStyleIndicatorControls,
  enrichBarsWithIndicators,
  overlayKeysFor,
  useChartIndicators,
} from '../charts/chartIndicators'

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
export type VpSeries = { key: string; label: string; color: string }
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
  const { x, y, width, height, payload } = props
  const open = Number(payload?.open ?? props.open)
  const high = Number(payload?.high ?? props.high)
  const low = Number(payload?.low ?? props.low)
  const close = Number(payload?.close ?? props.close)
  if (
    !Number.isFinite(high) ||
    !Number.isFinite(low) ||
    !Number.isFinite(open) ||
    !Number.isFinite(close) ||
    high === low
  ) {
    return null
  }
  const isBullish = close >= open
  const color = isBullish ? BULL : BEAR
  const ratio = height / (high - low)
  const bodyTop = y + (high - Math.max(open, close)) * ratio
  const bodyHeight = Math.max(1, Math.abs(close - open) * ratio)
  const cx = x + width / 2
  const bodyW = Math.max(1, width * 0.7)
  return (
    <g>
      <line x1={cx} y1={y} x2={cx} y2={y + height} stroke={color} strokeWidth={1} />
      <rect
        x={x + (width - bodyW) / 2}
        y={bodyTop}
        width={bodyW}
        height={bodyHeight}
        fill={color}
        stroke={color}
      />
    </g>
  )
}

function waveDotRenderer(wave: VpWaveSegment, dataKey: string) {
  // Elliott/impulse legs alternate direction by construction (peak, trough,
  // peak, ...), so anchoring the label on the opposite side of the swing
  // it ends on — above a peak, below a trough — keeps consecutive wave
  // labels from stacking on top of each other without needing full
  // multi-point collision detection.
  const isPeak = wave.endPrice >= wave.startPrice
  return (props: any) => {
    const { cx, cy, payload, key } = props
    if (cx == null || cy == null || payload?.[dataKey] == null) return <g key={key} />
    const isEnd = payload.time === wave.endTime
    if (!isEnd) {
      return <circle key={key} cx={cx} cy={cy} r={2.5} fill={wave.color} stroke="#0f172a" strokeWidth={1} />
    }
    const labelY = isPeak ? cy - 16 : cy + 20
    return (
      <g key={key}>
        <circle cx={cx} cy={cy} r={4} fill={wave.color} stroke="#0f172a" strokeWidth={1.5} />
        <rect x={cx - 8} y={labelY - 10} width={16} height={14} rx={3} fill="#0f172a" fillOpacity={0.85} />
        <text x={cx} y={labelY} fill={wave.color} fontSize={11} fontWeight={700} textAnchor="middle">
          {wave.label}
        </text>
      </g>
    )
  }
}

const CHART_HEIGHT = 288 // matches the fixed `h-72` container below
const PLOT_MARGIN_TOP = 8
const PLOT_MARGIN_BOTTOM = 4
const XAXIS_HEIGHT_ESTIMATE = 28 // recharts' default single-line category axis reservation

function priceToPixelY(price: number, yMin: number, yMax: number): number {
  const plotHeight = CHART_HEIGHT - PLOT_MARGIN_TOP - PLOT_MARGIN_BOTTOM - XAXIS_HEIGHT_ESTIMATE
  const ratio = (yMax - price) / (yMax - yMin || 1)
  return PLOT_MARGIN_TOP + ratio * plotHeight
}

/** Reference-line labels that sit close in price (e.g. clustered Fibonacci
 * targets) otherwise render on top of each other — nudge apart any that
 * are closer than `minGapPx` once sorted by their approximate pixel Y. */
function declutterLabelY(
  items: { key: string; price: number }[],
  yMin: number,
  yMax: number,
  minGapPx = 14,
): Record<string, number> {
  const withY = items
    .map((it) => ({ ...it, y: priceToPixelY(it.price, yMin, yMax) }))
    .sort((a, b) => a.y - b.y)
  for (let i = 1; i < withY.length; i++) {
    if (withY[i].y - withY[i - 1].y < minGapPx) {
      withY[i].y = withY[i - 1].y + minGapPx
    }
  }
  const out: Record<string, number> = {}
  withY.forEach((it) => { out[it.key] = it.y })
  return out
}

export function VolumeProfileChart({
  chartData,
  levels = [],
  histogram = [],
  waves = [],
  series = [],
  readingGuide,
  ticker,
  assetClass,
}: {
  chartData: VpChartBar[]
  levels?: VpLevel[]
  histogram?: VpHistBin[]
  waves?: VpWaveSegment[]
  /** Optional overlay series whose keys already exist on each chartData row (e.g. SMAs). */
  series?: VpSeries[]
  /** Short laymen "how to read this chart" caption, shown below it. */
  readingGuide?: string
  /** When set, enables live LTP streaming (on by default). */
  ticker?: string | null
  assetClass?: string | null
}) {
  const [chartType, setChartType] = useState<'candles' | 'line'>('candles')
  const [hidden, setHidden] = useState<Set<string>>(new Set())
  const [refLeft, setRefLeft] = useState<string | null>(null)
  const [refRight, setRefRight] = useState<string | null>(null)
  const [zoomRange, setZoomRange] = useState<[number, number] | null>(null)
  const { selected: indicators, toggle: toggleIndicator } = useChartIndicators()

  const {
    bars: liveChartData,
    streamOn,
    setStreamOn,
    barCount,
    setBarCount,
    liveLtp,
    canStream,
  } = useLiveChartData(chartData, { ticker, assetClass, defaultBars: 100, defaultStreamOn: true })

  const enriched = useMemo(() => enrichBarsWithIndicators(liveChartData), [liveChartData])
  const indOverlays = useMemo(() => overlayKeysFor(indicators), [indicators])
  const showVolume = indicators.includes('volume')
  const showRsi = indicators.includes('rsi')

  const merged = useMemo(() => {
    const base = enriched.map((b) => ({ ...b, range: [b.low, b.high] as [number, number] }))
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
  }, [enriched, waves])

  // Reset any in-flight/applied zoom whenever the underlying series changes
  // (new ticker, refreshed scan) so a stale index range never gets applied
  // to a differently-sized dataset.
  const dataKeyForReset = liveChartData.length
    ? `${liveChartData[0].time}|${liveChartData[liveChartData.length - 1].time}|${liveChartData.length}|${barCount}`
    : ''
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

  const toggleHidden = (key: string) => {
    setHidden((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  if (!chartData.length) {
    return <p className="text-xs text-slate-500">No chart data for this ticker.</p>
  }

  const visibleLevels = levels.filter((l) => !hidden.has(`level:${l.label}`))
  const visibleWaves = waves.filter((_, i) => !hidden.has(`wave:${i}`))
  const visibleSeries = series.filter((s) => !hidden.has(`series:${s.key}`))
  const anyHideable = levels.length > 0 || waves.length > 0 || series.length > 0

  const lows = view.map((b) => b.low)
  const highs = view.map((b) => b.high)
  const levelPrices = visibleLevels.map((l) => l.price)
  const wavePrices = visibleWaves.flatMap((w) => [w.startPrice, w.endPrice])
  const seriesPrices = visibleSeries.flatMap((s) =>
    view
      .map((b) => Number((b as Record<string, unknown>)[s.key]))
      .filter((n) => Number.isFinite(n)),
  )
  const indPrices = indOverlays.flatMap((ov) =>
    view
      .map((b) => Number((b as Record<string, unknown>)[ov.key]))
      .filter((n) => Number.isFinite(n)),
  )
  const liveExtras = liveLtp != null ? [liveLtp] : []
  const pad = (Math.max(...highs) - Math.min(...lows)) * 0.05 || 1
  const yMin = Math.min(...lows, ...levelPrices, ...wavePrices, ...seriesPrices, ...indPrices, ...liveExtras) - pad
  const yMax = Math.max(...highs, ...levelPrices, ...wavePrices, ...seriesPrices, ...indPrices, ...liveExtras) + pad

  const hasVolumeData = view.some(
    (b) => b.volume != null && Number.isFinite(Number(b.volume)) && Number(b.volume) > 0,
  )

  const histSorted = useMemo(
    () => [...histogram].sort((a, b) => a.price - b.price),
    [histogram],
  )

  const levelLabelY = useMemo(
    () => declutterLabelY(visibleLevels.map((l) => ({ key: l.label, price: l.price })), yMin, yMax),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [visibleLevels, yMin, yMax],
  )

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <ChartStyleIndicatorControls
          chartType={chartType}
          setChartType={setChartType}
          selected={indicators}
          toggle={toggleIndicator}
        />
        <ChartStreamControls
          streamOn={streamOn}
          setStreamOn={setStreamOn}
          barCount={barCount}
          setBarCount={setBarCount}
          canStream={canStream}
          liveLtp={liveLtp}
        />
        {anyHideable && (
          <>
            <button
              type="button"
              onClick={() => setHidden(new Set())}
              className="rounded-full border border-slate-700/80 bg-slate-800/40 px-2.5 py-1 text-[11px] text-slate-400 hover:border-slate-600 hover:text-slate-300"
            >
              Show all
            </button>
            <button
              type="button"
              onClick={() => {
                const all = new Set<string>()
                waves.forEach((_, i) => all.add(`wave:${i}`))
                levels.forEach((l) => all.add(`level:${l.label}`))
                series.forEach((s) => all.add(`series:${s.key}`))
                setHidden(all)
              }}
              className="rounded-full border border-slate-700/80 bg-slate-800/40 px-2.5 py-1 text-[11px] text-slate-400 hover:border-slate-600 hover:text-slate-300"
            >
              Hide all
            </button>
          </>
        )}
        <div className="ml-auto flex flex-wrap gap-2 text-[11px]">
          {series.map((s) => {
            const key = `series:${s.key}`
            const isHidden = hidden.has(key)
            return (
              <button
                type="button"
                key={key}
                onClick={() => toggleHidden(key)}
                title="Click to toggle this series"
                className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 transition-colors ${
                  isHidden ? 'border-slate-800 text-slate-600 line-through' : 'border-slate-700/70 text-slate-400'
                }`}
              >
                <span className="inline-block h-2 w-2 rounded-full" style={{ background: isHidden ? '#475569' : s.color }} />
                {s.label}
              </button>
            )
          })}
          {waves.map((w, i) => {
            const key = `wave:${i}`
            const isHidden = hidden.has(key)
            return (
              <button
                type="button"
                key={key}
                onClick={() => toggleHidden(key)}
                title="Click to toggle this wave line"
                className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 transition-colors ${
                  isHidden ? 'border-slate-800 text-slate-600 line-through' : 'border-slate-700/70 text-slate-400'
                }`}
              >
                <span className="inline-block h-2 w-2 rounded-full" style={{ background: isHidden ? '#475569' : w.color }} />
                Wave {w.label}
              </button>
            )
          })}
          {levels.map((l) => {
            const key = `level:${l.label}`
            const isHidden = hidden.has(key)
            return (
              <button
                type="button"
                key={key}
                onClick={() => toggleHidden(key)}
                title="Click to toggle this line"
                className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 transition-colors ${
                  isHidden ? 'border-slate-800 text-slate-600 line-through' : 'border-slate-700/70 text-slate-400'
                }`}
              >
                <span className="inline-block h-2 w-2 rounded-full" style={{ background: isHidden ? '#475569' : l.color }} />
                {l.label} {fmtNum(l.price)}
              </button>
            )
          })}
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-[1fr_160px]">
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
              margin={{ top: 8, right: 12, left: 4, bottom: 4 }}
              onMouseDown={handleMouseDown}
              onMouseMove={handleMouseMove}
              onMouseUp={handleMouseUp}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="time" tickFormatter={fmtTime} tick={{ fill: '#94a3b8', fontSize: 10 }} minTickGap={36} allowDataOverflow />
              <YAxis
                domain={[yMin, yMax]}
                tick={{ fill: '#94a3b8', fontSize: 10 }}
                width={60}
                tickFormatter={fmtNum}
                allowDataOverflow
              />
              <Tooltip content={<PriceTooltip chartType={chartType} />} />
              {visibleLevels.map((l) => (
                <ReferenceLine
                  key={l.label}
                  y={l.price}
                  stroke={l.color}
                  strokeDasharray="4 3"
                  strokeWidth={1.5}
                  ifOverflow="extendDomain"
                  label={(props: any) => {
                    const vb = props.viewBox
                    const y = levelLabelY[l.label] ?? vb.y
                    const x = vb.x + vb.width - 4
                    const textWidth = 8 + l.label.length * 5.2
                    return (
                      <g>
                        <rect x={x - textWidth} y={y - 9} width={textWidth} height={13} rx={2} fill="#0f172a" fillOpacity={0.85} />
                        <text x={x - 3} y={y + 1} textAnchor="end" fill={l.color} fontSize={10}>
                          {l.label}
                        </text>
                      </g>
                    )
                  }}
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
              {visibleSeries.map((s) => (
                <Line
                  key={s.key}
                  type="monotone"
                  dataKey={s.key}
                  stroke={s.color}
                  strokeWidth={1.75}
                  dot={false}
                  connectNulls
                  isAnimationActive={false}
                  name={s.label}
                />
              ))}
              {indOverlays.map((ov) => (
                <Line
                  key={ov.key}
                  type="monotone"
                  dataKey={ov.key}
                  stroke={ov.color}
                  strokeWidth={ov.key.startsWith('bb_') ? 1 : 1.5}
                  strokeDasharray={ov.dash}
                  dot={false}
                  connectNulls
                  isAnimationActive={false}
                  name={ov.label}
                />
              ))}
              {visibleWaves.map((w) => {
                const i = waves.indexOf(w)
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
              {refLeft != null && refRight != null && (
                <ReferenceArea x1={refLeft} x2={refRight} strokeOpacity={0.3} fill="#38bdf8" fillOpacity={0.15} />
              )}
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
      {(showVolume && hasVolumeData) || showRsi ? (
        <div className="space-y-2">
          {showVolume && hasVolumeData && (
            <div className="h-20 w-full">
              <p className="mb-1 text-[10px] uppercase tracking-wider text-slate-500">Volume</p>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={view} margin={{ top: 0, right: 12, left: 4, bottom: 0 }}>
                  <XAxis dataKey="time" hide allowDataOverflow />
                  <YAxis
                    tick={{ fill: '#94a3b8', fontSize: 9 }}
                    width={48}
                    tickFormatter={(v: number) =>
                      v >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `${(v / 1e3).toFixed(0)}K` : String(v)
                    }
                  />
                  <Bar dataKey="volume" fill="#334155" opacity={0.7} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
          {showRsi && (
            <div className="h-24 w-full">
              <p className="mb-1 text-[10px] uppercase tracking-wider text-slate-500">RSI (14)</p>
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={view} margin={{ top: 0, right: 12, left: 4, bottom: 0 }}>
                  <XAxis dataKey="time" hide allowDataOverflow />
                  <YAxis domain={[0, 100]} ticks={[0, 30, 50, 70, 100]} tick={{ fill: '#94a3b8', fontSize: 9 }} width={36} />
                  <ReferenceLine y={70} stroke="#f43f5e" strokeDasharray="3 3" strokeOpacity={0.6} />
                  <ReferenceLine y={30} stroke="#10b981" strokeDasharray="3 3" strokeOpacity={0.6} />
                  <Line type="monotone" dataKey="rsi" stroke="#c084fc" strokeWidth={1.5} dot={false} connectNulls isAnimationActive={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      ) : null}
      <p className="text-[10px] text-slate-600">
        Drag across the chart to zoom into a section. Click a line's chip above to hide/show it.
      </p>
      {readingGuide && (
        <p className="rounded-lg border border-slate-800/60 bg-slate-950/40 px-3 py-2 text-xs leading-relaxed text-slate-400">
          💡 <strong className="font-medium text-slate-300">How to read this chart:</strong> {readingGuide}
        </p>
      )}
    </div>
  )
}
