import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Pencil, Trash2, Wifi } from 'lucide-react'
import { apiErrorMessage, fetchPaperPrice, runProTradeTickerChart } from '../../api/client'
import { Chip } from '../ui/Chip'
import { Button } from '../ui/Button'
import { Input, Select } from '../ui/Form'
import { Alert, Loading } from '../ui/Feedback'

type Row = Record<string, unknown>
type ChartStyle = 'candles' | 'line'
type DrawMode = 'none' | 'sr' | 'trendline'

type Candle = {
  t?: string
  label?: string
  open?: number
  high?: number
  low?: number
  close?: number
  volume?: number | null
}

type CustomSr = { id: string; price: number; label: string }
type TrendLine = {
  id: string
  i1: number
  i2: number
  p1: number
  p2: number
}

type IndicatorId =
  | 'rsi'
  | 'supertrend'
  | 'volume'
  | 'bollinger'
  | 'ema_5'
  | 'ema_9'
  | 'ema_20'
  | 'ema_50'
  | 'ema_200'

const INDICATOR_OPTIONS: { id: IndicatorId; label: string }[] = [
  { id: 'rsi', label: 'RSI' },
  { id: 'supertrend', label: 'Supertrend' },
  { id: 'volume', label: 'Volume' },
  { id: 'bollinger', label: 'Bollinger' },
  { id: 'ema_5', label: 'EMA 5' },
  { id: 'ema_9', label: 'EMA 9' },
  { id: 'ema_20', label: 'EMA 20' },
  { id: 'ema_50', label: 'EMA 50' },
  { id: 'ema_200', label: 'EMA 200' },
]

const DEFAULT_INDICATORS: IndicatorId[] = ['volume', 'ema_9', 'ema_20', 'bollinger', 'rsi']

const BAR_COUNT_OPTIONS = [40, 60, 80, 100, 120, 150, 200, 300] as const
const RIGHT_PAD_BARS = 8

const OVERLAY_COLORS: Record<string, string> = {
  ema_5: '#fbbf24',
  ema_9: '#a78bfa',
  ema_20: '#34d399',
  ema_50: '#fb923c',
  ema_200: '#f472b6',
  supertrend: '#22d3ee',
  bb_upper: '#64748b',
  bb_mid: '#94a3b8',
  bb_lower: '#64748b',
}

const BULL = '#10b981'
const BEAR = '#f43f5e'
const INTERVALS = [
  { value: '1m', label: '1m' },
  { value: '5m', label: '5m' },
  { value: '15m', label: '15m' },
  { value: '30m', label: '30m' },
  { value: '1h', label: '1h' },
  { value: '1d', label: '1d' },
] as const

/** Must match ComposedChart margin + YAxis widths used below */
const PLOT_MARGIN = { top: 12, right: 72, left: 8, bottom: 28 }
const PRICE_AXIS_WIDTH = 56

function fmtNum(v: unknown, digits = 2): string {
  if (v == null || v === '') return '—'
  const n = Number(v)
  return Number.isFinite(n) ? n.toLocaleString(undefined, { maximumFractionDigits: digits }) : '—'
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

function isoDaysAgo(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() - days)
  return d.toISOString().slice(0, 10)
}

function CandlestickShape(props: {
  x?: number
  y?: number
  width?: number
  height?: number
  payload?: Record<string, unknown>
}) {
  const { x = 0, y = 0, width = 0, height = 0, payload } = props
  if (payload?.__pad) return null
  const open = Number(payload?.open)
  const high = Number(payload?.high)
  const low = Number(payload?.low)
  const close = Number(payload?.close)
  if (![open, high, low, close].every(Number.isFinite) || high === low) return null
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
      <rect x={x + (width - bodyW) / 2} y={bodyTop} width={bodyW} height={bodyHeight} fill={color} stroke={color} />
    </g>
  )
}

function uid() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function DrawOverlay({
  active,
  yMin,
  yMax,
  realBarCount,
  totalSlots,
  onPick,
}: {
  active: boolean
  yMin: number
  yMax: number
  realBarCount: number
  totalSlots: number
  onPick: (idx: number, price: number) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  if (!active || !(yMax > yMin) || realBarCount <= 0) return null

  return (
    <div
      ref={ref}
      className="absolute inset-0 z-20 cursor-crosshair"
      title="Click to place drawing"
      onClick={(e) => {
        e.preventDefault()
        e.stopPropagation()
        const el = ref.current
        if (!el) return
        const rect = el.getBoundingClientRect()
        const leftPad = PLOT_MARGIN.left + PRICE_AXIS_WIDTH
        const rightPad = PLOT_MARGIN.right
        const topPad = PLOT_MARGIN.top
        const bottomPad = PLOT_MARGIN.bottom
        const plotW = rect.width - leftPad - rightPad
        const plotH = rect.height - topPad - bottomPad
        const x = e.clientX - rect.left - leftPad
        const y = e.clientY - rect.top - topPad
        if (plotW <= 0 || plotH <= 0 || x < 0 || y < 0 || x > plotW || y > plotH) return

        const price = yMax - (y / plotH) * (yMax - yMin)
        // Map into full slot range (including right pad), then clamp to real bars
        const slot = Math.round((x / plotW) * Math.max(totalSlots - 1, 1))
        const idx = Math.max(0, Math.min(realBarCount - 1, slot))
        if (!Number.isFinite(price)) return
        onPick(idx, price)
      }}
    />
  )
}

export function PaperTradingChart({
  ticker,
  assetClass,
  liveLtp,
}: {
  ticker: string
  assetClass: string
  liveLtp?: number | null
}) {
  const [interval, setIntervalTf] = useState('15m')
  const [barCount, setBarCount] = useState(80)
  const [chartStyle, setChartStyle] = useState<ChartStyle>('candles')
  const [selected, setSelected] = useState<IndicatorId[]>(DEFAULT_INDICATORS)
  const [drawMode, setDrawMode] = useState<DrawMode>('none')
  const [customSr, setCustomSr] = useState<CustomSr[]>([])
  const [trendLines, setTrendLines] = useState<TrendLine[]>([])
  const [pendingTrend, setPendingTrend] = useState<{ i: number; price: number } | null>(null)
  const [manualSr, setManualSr] = useState<number | ''>('')
  const [streamOn, setStreamOn] = useState(true)
  const lastTicker = useRef(ticker)

  const isDaily = interval === '1d'
  const mode = isDaily ? 'daily' : 'intraday'

  const clearDrawings = useCallback(() => {
    setCustomSr([])
    setTrendLines([])
    setPendingTrend(null)
    setDrawMode('none')
  }, [])

  useEffect(() => {
    if (lastTicker.current !== ticker) {
      lastTicker.current = ticker
      clearDrawings()
    }
  }, [ticker, clearDrawings])

  useEffect(() => {
    // Indices are relative to the visible window — reset drawings when window changes
    clearDrawings()
  }, [barCount, interval, clearDrawings])

  const chartQuery = useQuery({
    queryKey: ['paper-chart', assetClass, ticker, interval, selected.join(',')],
    queryFn: () =>
      runProTradeTickerChart({
        ticker: ticker.trim(),
        asset_class: assetClass,
        mode,
        from_date: isDaily ? isoDaysAgo(180) : undefined,
        to_date: isDaily ? todayIso() : undefined,
        session_date: isDaily ? undefined : todayIso(),
        interval: isDaily ? '1d' : interval,
        indicators: selected,
        use_ai: false,
      }),
    enabled: ticker.trim().length > 0,
    refetchInterval: streamOn ? (interval === '1m' ? 8_000 : interval === '5m' ? 12_000 : 20_000) : false,
    staleTime: 5_000,
    retry: 1,
  })

  const priceQuery = useQuery({
    queryKey: ['paper-price-stream', assetClass, ticker],
    queryFn: () => fetchPaperPrice(ticker, assetClass),
    enabled: ticker.trim().length > 0 && streamOn,
    refetchInterval: streamOn ? 2_500 : false,
    staleTime: 1_000,
    retry: false,
  })

  const ltp = liveLtp ?? priceQuery.data?.price ?? null
  const data = chartQuery.data as Row | undefined
  const points = (data?.points as Row[] | undefined) ?? []
  const candles = (data?.candles as Candle[] | undefined) ?? []
  const error = chartQuery.isError
    ? apiErrorMessage(chartQuery.error)
    : data?.error
      ? String(data.error)
      : ''

  const fullRows = useMemo(() => {
    const byT = new Map<string, Candle>()
    for (const c of candles) {
      if (c?.t) byT.set(String(c.t), c)
      if (c?.label) byT.set(String(c.label), c)
    }
    return points.map((p) => {
      const t = String(p.t ?? '')
      const label = String(p.label ?? '')
      const c = byT.get(t) || byT.get(label)
      let close = Number(c?.close ?? p.value)
      let open = Number(c?.open ?? close)
      let high = Number(c?.high ?? Math.max(open, close))
      let low = Number(c?.low ?? Math.min(open, close))
      return {
        ...p,
        open,
        high,
        low,
        close,
        value: close,
        range: [low, high] as [number, number],
        __pad: false,
      } as Row
    })
  }, [points, candles])

  const chartRows = useMemo(() => {
    const sliced = fullRows.slice(-Math.max(10, barCount))
    // Stream: update forming (last real) candle with live LTP
    const rows = sliced.map((p, idx) => {
      let close = Number(p.close)
      let open = Number(p.open)
      let high = Number(p.high)
      let low = Number(p.low)
      if (idx === sliced.length - 1 && ltp != null && Number.isFinite(ltp)) {
        close = Number(ltp)
        high = Math.max(high, close, open)
        low = Math.min(low, close, open)
      }
      const row: Row = {
        ...p,
        idx,
        open,
        high,
        low,
        close,
        value: close,
        range: [low, high] as [number, number],
        __pad: false,
      }
      for (const tl of trendLines) {
        const lo = Math.min(tl.i1, tl.i2)
        const hi = Math.max(tl.i1, tl.i2)
        if (idx < lo || idx > hi) {
          row[`tl_${tl.id}`] = null
        } else if (hi === lo) {
          row[`tl_${tl.id}`] = tl.p1
        } else {
          const t = (idx - lo) / (hi - lo)
          const pStart = tl.i1 <= tl.i2 ? tl.p1 : tl.p2
          const pEnd = tl.i1 <= tl.i2 ? tl.p2 : tl.p1
          row[`tl_${tl.id}`] = pStart + (pEnd - pStart) * t
        }
      }
      return row
    })

    // Empty slots on the right so candles aren't glued to the edge
    for (let i = 0; i < RIGHT_PAD_BARS; i++) {
      const pad: Row = {
        label: '',
        idx: rows.length + i,
        open: null,
        high: null,
        low: null,
        close: null,
        value: null,
        volume: null,
        range: null,
        __pad: true,
      }
      for (const tl of trendLines) pad[`tl_${tl.id}`] = null
      rows.push(pad)
    }
    return rows
  }, [fullRows, barCount, ltp, trendLines])

  const realBarCount = Math.max(0, chartRows.length - RIGHT_PAD_BARS)

  const overlayKeys = useMemo(() => {
    const keys: { key: string; color: string; label: string; dash?: string }[] = []
    for (const id of ['ema_5', 'ema_9', 'ema_20', 'ema_50', 'ema_200'] as IndicatorId[]) {
      if (selected.includes(id)) {
        keys.push({ key: id, color: OVERLAY_COLORS[id], label: id.replace('_', ' ').toUpperCase() })
      }
    }
    if (selected.includes('supertrend')) {
      keys.push({ key: 'supertrend', color: OVERLAY_COLORS.supertrend, label: 'Supertrend', dash: '4 2' })
    }
    if (selected.includes('bollinger')) {
      keys.push(
        { key: 'bb_upper', color: OVERLAY_COLORS.bb_upper, label: 'BB Upper', dash: '3 3' },
        { key: 'bb_mid', color: OVERLAY_COLORS.bb_mid, label: 'BB Mid', dash: '2 2' },
        { key: 'bb_lower', color: OVERLAY_COLORS.bb_lower, label: 'BB Lower', dash: '3 3' },
      )
    }
    return keys
  }, [selected])

  const showVolume = selected.includes('volume')
  const showRsi = selected.includes('rsi')
  const hasVolumeData = useMemo(
    () => chartRows.some((p) => !p.__pad && p.volume != null && Number.isFinite(Number(p.volume)) && Number(p.volume) > 0),
    [chartRows],
  )
  const hasCandles = useMemo(
    () => chartRows.some((r) => !r.__pad && Number(r.high) !== Number(r.low) && Number.isFinite(Number(r.open))),
    [chartRows],
  )
  const effectiveStyle: ChartStyle = chartStyle === 'candles' && hasCandles ? 'candles' : 'line'

  const yDomainNums = useMemo((): [number, number] | null => {
    if (!realBarCount) return null
    const vals: number[] = []
    for (const p of chartRows) {
      if (p.__pad) continue
      if (effectiveStyle === 'candles') {
        if (Number.isFinite(Number(p.high))) vals.push(Number(p.high))
        if (Number.isFinite(Number(p.low))) vals.push(Number(p.low))
      } else if (Number.isFinite(Number(p.close))) {
        vals.push(Number(p.close))
      }
    }
    for (const sr of customSr) vals.push(sr.price)
    for (const tl of trendLines) {
      vals.push(tl.p1, tl.p2)
    }
    for (const ov of overlayKeys) {
      for (const p of chartRows) {
        if (p.__pad) continue
        const n = Number(p[ov.key])
        if (Number.isFinite(n)) vals.push(n)
      }
    }
    if (!vals.length) return null
    const lo = Math.min(...vals)
    const hi = Math.max(...vals)
    const pad = Math.max((hi - lo) * 0.06, Math.abs(hi) * 0.001, 1e-6)
    return [lo - pad, hi + pad]
  }, [chartRows, customSr, trendLines, overlayKeys, effectiveStyle, realBarCount])

  const yDomain = (yDomainNums ?? ['auto', 'auto']) as [number | string, number | string]

  const toggleIndicator = (id: IndicatorId) => {
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  const handlePick = useCallback(
    (idx: number, price: number) => {
      if (drawMode === 'sr') {
        setCustomSr((prev) => [
          ...prev,
          { id: uid(), price, label: `S/R ${fmtNum(price, price >= 100 ? 1 : 3)}` },
        ])
        setDrawMode('none')
        return
      }
      if (drawMode === 'trendline') {
        if (!pendingTrend) {
          setPendingTrend({ i: idx, price })
        } else {
          setTrendLines((prev) => [
            ...prev,
            { id: uid(), i1: pendingTrend.i, i2: idx, p1: pendingTrend.price, p2: price },
          ])
          setPendingTrend(null)
          setDrawMode('none')
        }
      }
    },
    [drawMode, pendingTrend],
  )

  const addManualSr = () => {
    if (manualSr === '' || !Number.isFinite(Number(manualSr))) return
    const price = Number(manualSr)
    setCustomSr((prev) => [...prev, { id: uid(), price, label: `S/R ${fmtNum(price, price >= 100 ? 1 : 3)}` }])
    setManualSr('')
  }

  if (!ticker.trim()) {
    return (
      <div className="rounded-xl border border-slate-800/60 bg-slate-950/40 p-8 text-center text-sm text-slate-500">
        Select a ticker to load the live chart
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="font-semibold text-white">{ticker}</h3>
          {ltp != null && (
            <span className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-sm font-medium text-emerald-300">
              LTP {fmtNum(ltp)}
              {streamOn && (
                <span className="ml-1.5 inline-flex items-center gap-1 text-[10px] text-emerald-400/80">
                  <Wifi size={10} /> live
                </span>
              )}
            </span>
          )}
          {data?.change_pct != null && (
            <span className={`text-xs ${Number(data.change_pct) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
              {Number(data.change_pct) >= 0 ? '+' : ''}
              {fmtNum(data.change_pct, 2)}%
            </span>
          )}
          <span className="text-[11px] text-slate-500">
            showing {realBarCount} / {fullRows.length || 0} bars
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Chip selected={streamOn} onClick={() => setStreamOn((v) => !v)}>
            {streamOn ? 'Streaming on' : 'Streaming off'}
          </Chip>
          <label className="flex items-center gap-1.5 text-xs text-slate-400">
            Bars
            <Select
              value={String(barCount)}
              onChange={(e) => setBarCount(Number(e.target.value) || 80)}
              className="!w-auto !py-1.5 text-xs"
            >
              {BAR_COUNT_OPTIONS.map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </Select>
          </label>
          <Select
            value={interval}
            onChange={(e) => setIntervalTf(e.target.value)}
            className="!w-auto !py-1.5 text-xs"
          >
            {INTERVALS.map((iv) => (
              <option key={iv.value} value={iv.value}>{iv.label}</option>
            ))}
          </Select>
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5">
        <Chip selected={effectiveStyle === 'candles'} onClick={() => setChartStyle('candles')}>Candles</Chip>
        <Chip selected={effectiveStyle === 'line'} onClick={() => setChartStyle('line')}>Line</Chip>
        {INDICATOR_OPTIONS.map((opt) => (
          <Chip key={opt.id} selected={selected.includes(opt.id)} onClick={() => toggleIndicator(opt.id)}>
            {opt.label}
          </Chip>
        ))}
      </div>

      <div className="flex flex-wrap items-end gap-2 rounded-lg border border-slate-800/60 bg-slate-950/40 p-2.5">
        <Button
          size="sm"
          variant={drawMode === 'sr' ? 'primary' : 'secondary'}
          onClick={() => {
            setDrawMode((m) => (m === 'sr' ? 'none' : 'sr'))
            setPendingTrend(null)
          }}
        >
          <Pencil size={14} /> Draw S/R
        </Button>
        <Button
          size="sm"
          variant={drawMode === 'trendline' ? 'primary' : 'secondary'}
          onClick={() => {
            setDrawMode((m) => (m === 'trendline' ? 'none' : 'trendline'))
            setPendingTrend(null)
          }}
        >
          <Pencil size={14} /> Trendline
        </Button>
        <div className="flex items-end gap-1.5">
          <div>
            <label className="mb-1 block text-[11px] text-slate-500">S/R price</label>
            <Input
              type="number"
              className="!w-28 !py-1.5"
              value={manualSr}
              onChange={(e) => setManualSr(e.target.value === '' ? '' : parseFloat(e.target.value))}
              placeholder="Price"
            />
          </div>
          <Button size="sm" variant="secondary" onClick={addManualSr}>Add</Button>
        </div>
        {(customSr.length > 0 || trendLines.length > 0 || pendingTrend) && (
          <Button size="sm" variant="ghost" onClick={clearDrawings}>
            <Trash2 size={14} /> Clear drawings
          </Button>
        )}
        {drawMode === 'sr' && (
          <span className="text-xs text-amber-300">Crosshair on — click chart height to place S/R</span>
        )}
        {drawMode === 'trendline' && (
          <span className="text-xs text-amber-300">
            {pendingTrend
              ? `Point 1 set @ ${fmtNum(pendingTrend.price)} — click second point`
              : 'Crosshair on — click first trendline point'}
          </span>
        )}
      </div>

      {error && <Alert type="error">{error}</Alert>}
      {chartQuery.isLoading && !data && <Loading message="Loading chart…" />}

      {chartRows.length > 0 && (
        <div className="rounded-xl border border-slate-800/60 bg-slate-950/40 p-3">
          <div className="relative h-[380px] w-full">
            {yDomainNums && (
              <DrawOverlay
                active={drawMode !== 'none'}
                yMin={yDomainNums[0]}
                yMax={yDomainNums[1]}
                realBarCount={realBarCount}
                totalSlots={chartRows.length}
                onPick={handlePick}
              />
            )}
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart
                data={chartRows}
                margin={{
                  top: PLOT_MARGIN.top,
                  right: PLOT_MARGIN.right,
                  left: PLOT_MARGIN.left,
                  bottom: PLOT_MARGIN.bottom,
                }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="label" tick={{ fill: '#94a3b8', fontSize: 10 }} minTickGap={28} />
                <YAxis
                  yAxisId="price"
                  domain={yDomain}
                  tick={{ fill: '#94a3b8', fontSize: 10 }}
                  width={PRICE_AXIS_WIDTH}
                  tickFormatter={(v) => Number(v).toFixed(v >= 100 ? 0 : 2)}
                />
                {showVolume && hasVolumeData && (
                  <YAxis
                    yAxisId="vol"
                    orientation="right"
                    tick={{ fill: '#64748b', fontSize: 9 }}
                    width={44}
                    tickFormatter={(v) => {
                      const n = Number(v)
                      if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`
                      if (n >= 1e3) return `${(n / 1e3).toFixed(0)}K`
                      return String(Math.round(n))
                    }}
                  />
                )}
                {drawMode === 'none' && (
                  <Tooltip
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    content={({ active, payload, label }: any) => {
                      if (!active || !payload?.length) return null
                      const row = payload[0]?.payload
                      if (!row || row.__pad) return null
                      return (
                        <div style={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 11, padding: '8px 10px' }}>
                          <p style={{ color: '#e2e8f0', marginBottom: 4 }}>{String(label)}</p>
                          {effectiveStyle === 'candles' ? (
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
                            <p style={{ color: '#94a3b8' }}>Vol: <span style={{ color: '#e2e8f0' }}>{fmtNum(row.volume, 0)}</span></p>
                          )}
                        </div>
                      )
                    }}
                  />
                )}
                {customSr.map((sr) => (
                  <ReferenceLine
                    key={sr.id}
                    yAxisId="price"
                    y={sr.price}
                    stroke="#fbbf24"
                    strokeWidth={1.5}
                    strokeDasharray="6 3"
                    ifOverflow="extendDomain"
                    label={{ value: sr.label, position: 'insideTopRight', fill: '#fbbf24', fontSize: 10 }}
                  />
                ))}
                {pendingTrend && (
                  <ReferenceLine
                    yAxisId="price"
                    y={pendingTrend.price}
                    stroke="#38bdf8"
                    strokeWidth={1}
                    strokeDasharray="2 2"
                    ifOverflow="extendDomain"
                    label={{ value: 'P1', position: 'insideTopLeft', fill: '#38bdf8', fontSize: 10 }}
                  />
                )}
                {showVolume && hasVolumeData && (
                  <Bar yAxisId="vol" dataKey="volume" fill="#334155" opacity={0.55} name="volume" isAnimationActive={false} />
                )}
                {effectiveStyle === 'candles' ? (
                  <Bar yAxisId="price" dataKey="range" name="Price" shape={CandlestickShape} isAnimationActive={false} />
                ) : (
                  <Line
                    yAxisId="price"
                    type="monotone"
                    dataKey="close"
                    stroke="#38bdf8"
                    strokeWidth={2}
                    dot={false}
                    name="Close"
                    connectNulls={false}
                    isAnimationActive={false}
                  />
                )}
                {overlayKeys.map((ov) => (
                  <Line
                    key={ov.key}
                    yAxisId="price"
                    type="monotone"
                    dataKey={ov.key}
                    stroke={ov.color}
                    strokeWidth={ov.key.startsWith('bb_') ? 1 : 1.5}
                    strokeDasharray={ov.dash}
                    dot={false}
                    name={ov.label}
                    connectNulls
                    isAnimationActive={false}
                  />
                ))}
                {trendLines.map((tl) => (
                  <Line
                    key={tl.id}
                    yAxisId="price"
                    type="linear"
                    dataKey={`tl_${tl.id}`}
                    stroke="#38bdf8"
                    strokeWidth={2}
                    dot={{ r: 3, fill: '#38bdf8' }}
                    connectNulls
                    name="Trendline"
                    isAnimationActive={false}
                  />
                ))}
              </ComposedChart>
            </ResponsiveContainer>
          </div>

          {(customSr.length > 0 || trendLines.length > 0 || overlayKeys.length > 0) && (
            <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 border-t border-slate-800/50 pt-2 text-[11px]">
              {customSr.map((sr) => (
                <button
                  key={sr.id}
                  type="button"
                  className="text-amber-300 hover:text-amber-200"
                  onClick={() => setCustomSr((prev) => prev.filter((x) => x.id !== sr.id))}
                  title="Remove"
                >
                  {sr.label} ✕
                </button>
              ))}
              {trendLines.map((tl) => (
                <button
                  key={tl.id}
                  type="button"
                  className="text-sky-300 hover:text-sky-200"
                  onClick={() => setTrendLines((prev) => prev.filter((x) => x.id !== tl.id))}
                  title="Remove"
                >
                  TL {fmtNum(tl.p1)}→{fmtNum(tl.p2)} ✕
                </button>
              ))}
              {overlayKeys.map((ov) => (
                <span key={ov.key} style={{ color: ov.color }}>{ov.label}</span>
              ))}
            </div>
          )}

          {showRsi && (
            <div className="mt-3 rounded-xl border border-slate-800/60 bg-slate-950/40 p-3">
              <p className="mb-2 text-xs font-medium text-slate-300">RSI (14)</p>
              <div className="h-28 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={chartRows} margin={{ top: 8, right: 72, left: 8, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                    <XAxis dataKey="label" tick={{ fill: '#94a3b8', fontSize: 9 }} minTickGap={40} />
                    <YAxis domain={[0, 100]} tick={{ fill: '#94a3b8', fontSize: 9 }} width={36} />
                    <ReferenceLine y={70} stroke="#f87171" strokeDasharray="4 3" />
                    <ReferenceLine y={30} stroke="#34d399" strokeDasharray="4 3" />
                    <Line type="monotone" dataKey="rsi" stroke="#c084fc" strokeWidth={1.5} dot={false} connectNulls isAnimationActive={false} />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}
        </div>
      )}

      {!chartQuery.isLoading && chartRows.length === 0 && !error && (
        <p className="py-6 text-center text-sm text-slate-500">No bars available for this ticker / interval</p>
      )}
    </div>
  )
}
