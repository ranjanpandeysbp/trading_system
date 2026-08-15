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
import { Wifi } from 'lucide-react'
import { apiErrorMessage, fetchPaperPrice, runProTradeTickerChart } from '../../api/client'
import {
  ChartDrawingLayer,
  ChartDrawingToolbar,
  useChartDrawings,
} from '../charts/ChartDrawingLayer'
import { ChartExpandControls, ChartExpandFrame, useChartExpand } from '../charts/chartExpand'
import {
  ChartContextMenu,
  ChartZoomControls,
  copyChartImage,
  useChartContextMenu,
  useChartPanDrag,
  useChartPointerZoom,
  useIndexZoom,
} from '../charts/chartZoom'
import { useChartInvestigateAi } from '../charts/ChartInvestigateAi'
import { useChartAxisLayout } from '../charts/chartLayout'
import { ChartSrToggle, useAutoSrVisible } from '../charts/chartSrToggle'
import { ChartCommentaryPanel } from '../charts/ChartCommentaryPanel'
import { ChartChrome, ChartToolbarRow } from '../charts/chartChrome'
import { AskAIPanel, buildAskContext } from '../ai/AskAIPanel'
import { Alert, Loading } from '../ui/Feedback'
import { Card } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { FormField, Select } from '../ui/Form'
import { PageHeader } from '../ui/PageHeader'
import { StrategyDataSourceBar } from '../ui/StrategyDataSourceBar'
import { TickerAutosuggest } from '../ui/TickerAutosuggest'
import { CopyAllButton } from '../ui/CopyAllButton'
import { VolumeSrSummaryCard, type VolumeSrSummary } from '../ui/VolumeSrSummaryCard'
import { TradeSetupBanner, tradeSetupFromResult } from './TradeSetupBanner'
import { FallRiseForecastCards, forecastFromResult } from './FallRiseForecastCards'
import { UseAiCheckbox, useTradeSetupAi } from './UseAiCheckbox'
import type { AssetClass } from '../command-center/AssetClassTickerPicker'

type Row = Record<string, unknown>
type ChartMode = 'daily' | 'intraday'
type ChartStyle = 'candles' | 'line'

type Candle = {
  t?: string
  label?: string
  open?: number
  high?: number
  low?: number
  close?: number
  volume?: number | null
}

type SrLevel = { key?: string; label: string; kind: string; price: number }
type SupportResistance = {
  s1?: number | null
  s2?: number | null
  r1?: number | null
  r2?: number | null
  levels?: SrLevel[]
}

type IndicatorReading = {
  id?: string
  label?: string
  detail?: string
  signal?: string
  bias?: string
  value?: number
  levels?: SrLevel[]
}

type IndicatorId =
  | 'rsi'
  | 'macd'
  | 'supertrend'
  | 'vwap'
  | 'volume'
  | 'bollinger'
  | 'fibonacci'
  | 'ema_5'
  | 'ema_9'
  | 'ema_20'
  | 'ema_50'
  | 'ema_200'

const INDICATOR_OPTIONS: { id: IndicatorId; label: string }[] = [
  { id: 'rsi', label: 'RSI' },
  { id: 'macd', label: 'MACD' },
  { id: 'supertrend', label: 'Supertrend' },
  { id: 'vwap', label: 'VWAP' },
  { id: 'volume', label: 'Volume' },
  { id: 'bollinger', label: 'Bollinger' },
  { id: 'fibonacci', label: 'Fibonacci' },
  { id: 'ema_5', label: 'EMA 5' },
  { id: 'ema_9', label: 'EMA 9' },
  { id: 'ema_20', label: 'EMA 20' },
  { id: 'ema_50', label: 'EMA 50' },
  { id: 'ema_200', label: 'EMA 200' },
]

const DEFAULT_INDICATORS: IndicatorId[] = ['volume', 'ema_9', 'ema_20', 'bollinger', 'rsi']

const BAR_COUNT_OPTIONS = [40, 60, 80, 100, 120, 150, 200, 300] as const
const RIGHT_PAD_BARS = 6
/** ComposedChart margin + YAxis widths — kept in sync via useChartAxisLayout */
const DESKTOP_TICKER_AXIS = {
  desktopLeftMargin: 0,
  desktopRightMargin: 20,
  desktopPriceAxisWidth: 56,
  desktopSecondaryAxisWidth: 44,
  bottomPad: 0,
} as const

const OVERLAY_COLORS: Record<string, string> = {
  ema_5: '#fbbf24',
  ema_9: '#a78bfa',
  ema_20: '#34d399',
  ema_50: '#fb923c',
  ema_200: '#f472b6',
  vwap: '#eab308',
  supertrend: '#22d3ee',
  bb_upper: '#64748b',
  bb_mid: '#94a3b8',
  bb_lower: '#64748b',
}

const BULL = '#10b981'
const BEAR = '#f43f5e'

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

const ASSET_CLASSES: { id: AssetClass; label: string }[] = [
  { id: 'india', label: 'India' },
  { id: 'us', label: 'US' },
  { id: 'crypto', label: 'Crypto' },
  { id: 'commodity', label: 'Commodities' },
]

const INTRADAY_INTERVALS = [
  { value: '1m', label: '1m' },
  { value: '5m', label: '5m' },
  { value: '15m', label: '15m' },
  { value: '30m', label: '30m' },
  { value: '1h', label: '1h' },
] as const

function isoDaysAgo(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() - days)
  return d.toISOString().slice(0, 10)
}

function fmtNum(v: unknown, digits = 2): string {
  if (v == null || v === '') return '—'
  const n = Number(v)
  return Number.isFinite(n) ? n.toLocaleString(undefined, { maximumFractionDigits: digits }) : '—'
}

function placeholderFor(ac: AssetClass): string {
  if (ac === 'us') return 'e.g. AAPL'
  if (ac === 'crypto') return 'e.g. B-BTCUSDT'
  if (ac === 'commodity') return 'e.g. Gold, Silver, GC=F'
  return 'e.g. RELIANCE'
}

function buildSignalDescription(opts: {
  ticker: string
  rangeTxt: string
  changePct: number | null
  volSrPlain: string
  selected: IndicatorId[]
  readings: Record<string, IndicatorReading>
}): string {
  const { ticker, rangeTxt, changePct, volSrPlain, selected, readings } = opts
  const parts: string[] = [
    `${ticker} · ${rangeTxt}${changePct != null ? ` · Δ ${changePct >= 0 ? '+' : ''}${changePct.toFixed(2)}%` : ''}.`,
  ]
  if (volSrPlain) parts.push(volSrPlain)

  const order: IndicatorId[] = [
    'ema_5',
    'ema_9',
    'ema_20',
    'ema_50',
    'ema_200',
    'vwap',
    'bollinger',
    'supertrend',
    'rsi',
    'macd',
    'volume',
    'fibonacci',
  ]
  let bull = 0
  let bear = 0
  const lines: string[] = []
  for (const key of order) {
    if (!selected.includes(key)) continue
    const r = readings[key]
    if (!r) continue
    const detail = String(r.detail || r.signal || '').trim()
    if (detail) lines.push(detail)
    const bias = String(r.bias || 'neutral')
    if (bias === 'bullish') bull += 1
    else if (bias === 'bearish') bear += 1
  }
  if (lines.length) parts.push(`Indicators: ${lines.join(' · ')}`)
  if (bull || bear) {
    let tilt = 'Overall indicator tilt: mixed / neutral'
    if (bull > bear + 1) tilt = 'Overall indicator tilt: bullish'
    else if (bear > bull + 1) tilt = 'Overall indicator tilt: bearish'
    parts.push(`${tilt} (${bull} bullish · ${bear} bearish of ${bull + bear} scored).`)
  }
  parts.push('Educational read only — not a buy/sell signal.')
  return parts.filter(Boolean).join(' ')
}

function OscillatorChart({
  points,
  title,
  lines,
  referenceYs,
  yDomain,
}: {
  points: Row[]
  title: string
  lines: { key: string; color: string; label: string }[]
  referenceYs?: { y: number; color: string; label?: string }[]
  yDomain?: [number | string, number | string]
}) {
  const axis = useChartAxisLayout({
    desktopLeftMargin: 0,
    desktopRightMargin: 12,
    desktopPriceAxisWidth: 44,
    bottomPad: 0,
  })
  return (
    <div className="mt-3 rounded-xl border border-slate-800/60 bg-slate-950/40 p-3">
      <p className="mb-2 text-xs font-medium text-slate-300">{title}</p>
      <div className="h-36 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={points} margin={axis.margin}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis
              dataKey="label"
              tick={{ fill: '#94a3b8', fontSize: axis.tickFontSize }}
              minTickGap={axis.minTickGap}
              height={axis.narrow ? 16 : 28}
            />
            <YAxis
              domain={yDomain ?? ['auto', 'auto']}
              tick={{ fill: '#94a3b8', fontSize: axis.tickFontSize }}
              width={axis.oscAxisWidth}
              tickFormatter={(v) => Number(v).toFixed(axis.narrow ? 0 : 1)}
              tickCount={axis.narrow ? 4 : undefined}
            />
            <Tooltip
              contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 11 }}
              labelStyle={{ color: '#e2e8f0' }}
            />
            {(referenceYs ?? []).map((rl) => (
              <ReferenceLine
                key={`${rl.y}-${rl.label ?? ''}`}
                y={rl.y}
                stroke={rl.color}
                strokeDasharray="4 3"
                strokeWidth={1}
              />
            ))}
            {lines.map((ln) => (
              <Line
                key={ln.key}
                type="monotone"
                dataKey={ln.key}
                stroke={ln.color}
                strokeWidth={1.5}
                dot={false}
                name={ln.label}
                connectNulls
              />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

export function PriceChart({
  points,
  candles,
  supportResistance,
  title,
  volumeSrSummary,
  selected,
  fibLevels,
  liveLtp,
  maxBars,
  workspace = false,
  hideDrawingToolbar = false,
  externalDrawings,
  onNeedOlder,
}: {
  points: Row[]
  candles?: Candle[]
  supportResistance?: SupportResistance | null
  title: string
  volumeSrSummary?: VolumeSrSummary | null
  selected: IndicatorId[]
  fibLevels?: SrLevel[]
  liveLtp?: number | null
  maxBars?: number
  /** TradingView-style workspace: taller chart, quieter chrome */
  workspace?: boolean
  hideDrawingToolbar?: boolean
  externalDrawings?: ReturnType<typeof useChartDrawings>
  onNeedOlder?: () => void
}) {
  const [chartStyle, setChartStyle] = useState<ChartStyle>('candles')
  const localDrawings = useChartDrawings()
  const drawingsApi = externalDrawings ?? localDrawings
  const expand = useChartExpand(workspace ? 'xl' : 'normal')
  const chartRef = useRef<HTMLDivElement>(null)
  const ctxMenu = useChartContextMenu()
  const [copyStatus, setCopyStatus] = useState<string | null>(null)
  const { showSr, toggleSr } = useAutoSrVisible(true)
  const axis = useChartAxisLayout({
    ...DESKTOP_TICKER_AXIS,
    bottomPad: 0,
  })
  const {
    tool: drawTool,
    drawings,
    selectedId: drawSelectedId,
    setTool: setDrawTool,
    setSelectedId: setDrawSelectedId,
    setDrawings,
    clear: clearDrawings,
    removeSelected: removeSelectedDrawing,
    patch: patchDrawing,
  } = drawingsApi
  const showVolume = selected.includes('volume')
  const showBb = selected.includes('bollinger')
  const showFib = selected.includes('fibonacci')
  const showRsi = selected.includes('rsi')
  const showMacd = selected.includes('macd')
  const plotInsets = showVolume && !axis.narrow
    ? axis.plotInsetsWithRightAxis
    : axis.plotInsets

  const levels = useMemo(() => {
    const raw = supportResistance?.levels
    if (raw?.length) {
      return raw
        .map((lv) => ({
          label: String(lv.label),
          kind: String(lv.kind),
          price: Number(lv.price),
        }))
        .filter((lv) => Number.isFinite(lv.price))
    }
    const fallback: SrLevel[] = []
    if (supportResistance?.s2 != null) fallback.push({ label: 'S2', kind: 'support', price: Number(supportResistance.s2) })
    if (supportResistance?.s1 != null) fallback.push({ label: 'S1', kind: 'support', price: Number(supportResistance.s1) })
    if (supportResistance?.r1 != null) fallback.push({ label: 'R1', kind: 'resistance', price: Number(supportResistance.r1) })
    if (supportResistance?.r2 != null) fallback.push({ label: 'R2', kind: 'resistance', price: Number(supportResistance.r2) })
    return fallback.filter((lv) => Number.isFinite(lv.price))
  }, [supportResistance])

  const visibleSrLevels = showSr ? levels : []

  const fibRefs = useMemo(() => {
    if (!showFib) return []
    return (fibLevels ?? [])
      .map((lv) => ({
        label: String(lv.label),
        kind: 'fibonacci',
        price: Number(lv.price),
      }))
      .filter((lv) => Number.isFinite(lv.price))
  }, [fibLevels, showFib])

  const overlayKeys = useMemo(() => {
    const keys: { key: string; color: string; label: string; dash?: string }[] = []
    for (const id of ['ema_5', 'ema_9', 'ema_20', 'ema_50', 'ema_200'] as IndicatorId[]) {
      if (selected.includes(id)) {
        keys.push({ key: id, color: OVERLAY_COLORS[id], label: id.replace('_', ' ').toUpperCase() })
      }
    }
    if (selected.includes('vwap')) keys.push({ key: 'vwap', color: OVERLAY_COLORS.vwap, label: 'VWAP' })
    if (selected.includes('supertrend')) {
      keys.push({ key: 'supertrend', color: OVERLAY_COLORS.supertrend, label: 'Supertrend', dash: '4 2' })
    }
    if (showBb) {
      keys.push(
        { key: 'bb_upper', color: OVERLAY_COLORS.bb_upper, label: 'BB Upper', dash: '3 3' },
        { key: 'bb_mid', color: OVERLAY_COLORS.bb_mid, label: 'BB Mid', dash: '2 2' },
        { key: 'bb_lower', color: OVERLAY_COLORS.bb_lower, label: 'BB Lower', dash: '3 3' },
      )
    }
    return keys
  }, [selected, showBb])

  const chartRowsBase = useMemo(() => {
    const byT = new Map<string, Candle>()
    for (const c of candles ?? []) {
      if (c?.t) byT.set(String(c.t), c)
      if (c?.label) byT.set(String(c.label), c)
    }
    let rows: Row[] = points.map((p) => {
      const t = String(p.t ?? '')
      const label = String(p.label ?? '')
      const c = byT.get(t) || byT.get(label)
      const close = Number(c?.close ?? p.value)
      const open = Number(c?.open ?? close)
      const high = Number(c?.high ?? Math.max(open, close))
      const low = Number(c?.low ?? Math.min(open, close))
      return {
        ...p,
        open,
        high,
        low,
        close,
        value: close,
        range: [low, high] as [number, number],
        __pad: false,
      }
    })
    // Keep full history buffer — visible window comes from useIndexZoom(visibleBars).
    if (rows.length && liveLtp != null && Number.isFinite(liveLtp)) {
      const last = { ...rows[rows.length - 1] }
      const close = Number(liveLtp)
      const open = Number(last.open)
      last.close = close
      last.value = close
      last.high = Math.max(Number(last.high), close, open)
      last.low = Math.min(Number(last.low), close, open)
      last.range = [Number(last.low), Number(last.high)] as [number, number]
      rows = [...rows.slice(0, -1), last]
    }
    return rows
  }, [points, candles, liveLtp])

  const {
    zoomRange,
    zoomIn,
    zoomOut,
    resetZoom,
    panBy,
    isZoomed,
  } = useIndexZoom(chartRowsBase.length, {
    visibleBars: maxBars && maxBars > 0 ? maxBars : 100,
    onNeedOlder,
  })

  useChartPointerZoom(chartRef, zoomIn, zoomOut, ctxMenu.openAt)
  useChartPanDrag(chartRef, {
    enabled: drawTool === 'select' && !drawSelectedId,
    totalLength: chartRowsBase.length,
    zoomRange,
    panBy,
    primaryPan: true,
  })

  const chartRows = useMemo(() => {
    const span = maxBars && maxBars > 0 ? maxBars : 100
    const real = zoomRange
      ? chartRowsBase.slice(zoomRange[0], zoomRange[1] + 1)
      : chartRowsBase.slice(-span)
    const rows = [...real]
    // Right-side breathing room
    for (let i = 0; i < RIGHT_PAD_BARS; i++) {
      rows.push({
        label: '',
        open: null,
        high: null,
        low: null,
        close: null,
        value: null,
        volume: null,
        range: null,
        __pad: true,
      })
    }
    return rows
  }, [chartRowsBase, zoomRange, maxBars])

  const handleCopyChart = async () => {
    const result = await copyChartImage(chartRef.current)
    setCopyStatus(result === 'ok' ? 'Chart copied' : 'Copy failed')
    window.setTimeout(() => setCopyStatus(null), 1800)
  }

  const handleResetChart = () => {
    resetZoom()
    expand.setSize('normal')
    expand.setFullscreen(false)
  }

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
    if (!chartRows.length) return null
    const vals: number[] = []
    for (const p of chartRows) {
      if (p.__pad) continue
      if (effectiveStyle === 'candles') {
        const hi = Number(p.high)
        const lo = Number(p.low)
        if (Number.isFinite(hi)) vals.push(hi)
        if (Number.isFinite(lo)) vals.push(lo)
      } else {
        const n = Number(p.value ?? p.close)
        if (Number.isFinite(n)) vals.push(n)
      }
    }
    if (!vals.length) return null
    let lo = Math.min(...vals)
    let hi = Math.max(...vals)
    for (const lv of visibleSrLevels) {
      lo = Math.min(lo, lv.price)
      hi = Math.max(hi, lv.price)
    }
    for (const lv of fibRefs) {
      lo = Math.min(lo, lv.price)
      hi = Math.max(hi, lv.price)
    }
    for (const ov of overlayKeys) {
      for (const p of chartRows) {
        if (p.__pad) continue
        const n = Number(p[ov.key])
        if (Number.isFinite(n)) {
          lo = Math.min(lo, n)
          hi = Math.max(hi, n)
        }
      }
    }
    for (const d of drawings) {
      if (d.kind === 'hline' || d.kind === 'hray') {
        lo = Math.min(lo, d.price)
        hi = Math.max(hi, d.price)
      }
      if (d.kind === 'trend' || d.kind === 'fib' || d.kind === 'rect') {
        lo = Math.min(lo, d.y1, d.y2)
        hi = Math.max(hi, d.y1, d.y2)
        if (d.kind === 'fib') {
          for (const r of [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1]) {
            const p = d.y1 + (d.y2 - d.y1) * r
            lo = Math.min(lo, p)
            hi = Math.max(hi, p)
          }
        }
      }
    }
    const pad = Math.max((hi - lo) * 0.06, Math.abs(hi) * 0.001, 1e-6)
    return [lo - pad, hi + pad]
  }, [chartRows, visibleSrLevels, fibRefs, overlayKeys, effectiveStyle, drawings])

  const yDomain = (yDomainNums ?? ['auto', 'auto']) as [number | string, number | string]

  const investigateBars = useMemo(
    () =>
      chartRows
        .filter((r) => !r.__pad)
        .map((r) => ({
          time: String(r.time ?? r.date ?? ''),
          open: Number(r.open),
          high: Number(r.high),
          low: Number(r.low),
          close: Number(r.close),
          volume: r.volume != null ? Number(r.volume) : null,
        })),
    [chartRows],
  )
  const investigate = useChartInvestigateAi({
    ticker: title,
    bars: investigateBars,
    levels: visibleSrLevels.map((l) => ({ label: l.label, price: l.price })),
    section: `chart/${title}`,
  })

  if (!points.length) {
    return (
      <div className="rounded-xl border border-slate-800/60 bg-slate-950/40 p-6 text-center text-sm text-slate-500">
        No bars in range
      </div>
    )
  }

  return (
    <ChartExpandFrame
      fullscreen={expand.fullscreen}
      onClose={() => expand.setFullscreen(false)}
      title={title}
    >
    <div className={workspace ? 'p-0' : 'rounded-xl border border-slate-800/60 bg-slate-950/40 p-3'}>
      <ChartChrome
        className={workspace ? 'mb-2' : 'mb-2'}
        symbol={
          !workspace ? (
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm font-medium text-white">{title}</p>
              <span className="text-[10px] text-slate-500">
                green = support · red = resistance
                {showVolume ? ' · grey = volume' : ''}
                {showFib ? ' · amber = fib' : ''}
              </span>
            </div>
          ) : undefined
        }
        view={
          <>
            <Chip selected={effectiveStyle === 'candles'} onClick={() => setChartStyle('candles')}>
              Candles
            </Chip>
            <Chip selected={effectiveStyle === 'line'} onClick={() => setChartStyle('line')}>
              Line
            </Chip>
          </>
        }
        tools={
          <>
            <ChartExpandControls
              size={expand.size}
              setSize={expand.setSize}
              fullscreen={expand.fullscreen}
              setFullscreen={expand.setFullscreen}
            />
            <ChartZoomControls
              onZoomIn={zoomIn}
              onZoomOut={zoomOut}
              onReset={resetZoom}
              isZoomed={isZoomed}
            />
            {investigate.ToolbarButton}
            {levels.length > 0 && (
              <ChartSrToggle showSr={showSr} onToggle={toggleSr} />
            )}
            {copyStatus && (
              <span className="text-[11px] text-emerald-400/90">{copyStatus}</span>
            )}
          </>
        }
        drawings={
          !hideDrawingToolbar ? (
            <ChartDrawingToolbar
              tool={drawTool}
              setTool={setDrawTool}
              selectedId={drawSelectedId}
              drawings={drawings}
              patch={patchDrawing}
              removeSelected={removeSelectedDrawing}
              clear={clearDrawings}
            />
          ) : null
        }
        commentary={
          <ChartCommentaryPanel
            bars={investigateBars}
            ticker={title}
            indicators={selected}
            levels={[...visibleSrLevels, ...fibRefs]}
            drawings={drawings as unknown as Array<Record<string, unknown>>}
          />
        }
      />
      <div ref={chartRef} className={`relative mt-2 w-full select-none ${expand.heightClass}`}>
        {yDomainNums && (
          <ChartDrawingLayer
            insets={plotInsets}
            yMin={yDomainNums[0]}
            yMax={yDomainNums[1]}
            nSlots={chartRows.length}
            drawings={drawings}
            selectedId={drawSelectedId}
            tool={drawTool}
            onSelect={setDrawSelectedId}
            onChange={setDrawings}
            setTool={setDrawTool}
          />
        )}
        {isZoomed && (
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
            data={chartRows}
            margin={{
              top: axis.margin.top + 4,
              right: showVolume && !axis.narrow ? Math.max(axis.margin.right, 20) + axis.secondaryAxisWidth : axis.margin.right,
              left: axis.margin.left,
              bottom: axis.margin.bottom,
            }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis
              dataKey="label"
              tick={{ fill: '#94a3b8', fontSize: axis.tickFontSize }}
              minTickGap={axis.minTickGap}
              height={axis.narrow ? 16 : 28}
            />
            <YAxis
              yAxisId="price"
              domain={yDomain}
              tick={{ fill: '#94a3b8', fontSize: axis.tickFontSize }}
              width={axis.priceAxisWidth}
              tickFormatter={(v) =>
                axis.narrow ? axis.compactTick(Number(v)) : Number(v).toFixed(v >= 100 ? 0 : 2)
              }
              tickCount={axis.narrow ? 4 : undefined}
            />
            {showVolume && hasVolumeData && (
              <YAxis
                yAxisId="vol"
                orientation="right"
                hide={axis.narrow}
                tick={{ fill: '#64748b', fontSize: axis.tickFontSize }}
                width={axis.narrow ? 0 : axis.secondaryAxisWidth}
                tickFormatter={(v) => {
                  const n = Number(v)
                  if (n >= 1e9) return `${(n / 1e9).toFixed(1)}B`
                  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`
                  if (n >= 1e3) return `${(n / 1e3).toFixed(0)}K`
                  return String(Math.round(n))
                }}
              />
            )}
            {drawTool === 'select' && !drawSelectedId && (
            <Tooltip
              contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 11 }}
              labelStyle={{ color: '#e2e8f0' }}
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              formatter={((value: number, name: string) => {
                if (name === 'volume') {
                  return [Number(value).toLocaleString(undefined, { maximumFractionDigits: 0 }), 'Volume']
                }
                if (name === 'Price' || name === 'range') return null
                return [Number(value).toFixed(3), name]
              }) as any}
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
                      <p style={{ color: '#94a3b8' }}>Close: <span style={{ color: '#e2e8f0' }}>{fmtNum(row.value ?? row.close)}</span></p>
                    )}
                    {row.volume != null && (
                      <p style={{ color: '#94a3b8' }}>Vol: <span style={{ color: '#e2e8f0' }}>{fmtNum(row.volume, 0)}</span></p>
                    )}
                  </div>
                )
              }}
            />
            )}
            {visibleSrLevels.map((lv) => {
              const isSupport = lv.kind === 'support'
              const stroke = isSupport ? '#34d399' : '#f87171'
              return (
                <ReferenceLine
                  key={`${lv.label}-${lv.price}`}
                  yAxisId="price"
                  y={lv.price}
                  stroke={stroke}
                  strokeWidth={1.5}
                  strokeDasharray="5 3"
                  ifOverflow="extendDomain"
                  label={{
                    value: `${lv.label} ${fmtNum(lv.price, lv.price >= 100 ? 1 : 3)}`,
                    position: isSupport ? 'insideBottomRight' : 'insideTopRight',
                    fill: stroke,
                    fontSize: 10,
                  }}
                />
              )
            })}
            {fibRefs.map((lv) => (
              <ReferenceLine
                key={`fib-${lv.label}-${lv.price}`}
                yAxisId="price"
                y={lv.price}
                stroke="#d97706"
                strokeWidth={1}
                strokeDasharray="2 4"
                ifOverflow="extendDomain"
                label={{
                  value: lv.label.replace('Fib ', ''),
                  position: 'insideTopLeft',
                  fill: '#d97706',
                  fontSize: 9,
                }}
              />
            ))}
            {showVolume && hasVolumeData && (
              <Bar yAxisId="vol" dataKey="volume" fill="#334155" opacity={0.55} name="volume" isAnimationActive={false} />
            )}
            {effectiveStyle === 'candles' ? (
              <Bar yAxisId="price" dataKey="range" name="Price" shape={CandlestickShape} isAnimationActive={false} />
            ) : (
              <Line
                yAxisId="price"
                type="monotone"
                dataKey="value"
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
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      {(visibleSrLevels.length > 0 || overlayKeys.length > 0) && (
        <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 border-t border-slate-800/50 pt-2 text-[11px]">
          {visibleSrLevels.map((lv) => (
            <span
              key={`legend-${lv.label}-${lv.price}`}
              className={lv.kind === 'support' ? 'text-emerald-400' : 'text-rose-400'}
            >
              {lv.label} {fmtNum(lv.price, lv.price >= 100 ? 1 : 3)}
            </span>
          ))}
          {overlayKeys.map((ov) => (
            <span key={`ov-${ov.key}`} style={{ color: ov.color }}>
              {ov.label}
            </span>
          ))}
        </div>
      )}
      <VolumeSrSummaryCard data={volumeSrSummary} />
      {showRsi && (
        <OscillatorChart
          points={chartRows.filter((r) => !r.__pad)}
          title="RSI (14)"
          lines={[{ key: 'rsi', color: '#c084fc', label: 'RSI' }]}
          referenceYs={[
            { y: 70, color: '#f87171' },
            { y: 30, color: '#34d399' },
            { y: 50, color: '#475569' },
          ]}
          yDomain={[0, 100]}
        />
      )}
      {showMacd && (
        <OscillatorChart
          points={chartRows.filter((r) => !r.__pad)}
          title="MACD (12, 26, 9)"
          lines={[
            { key: 'macd', color: '#38bdf8', label: 'MACD' },
            { key: 'macd_signal', color: '#fb923c', label: 'Signal' },
            { key: 'macd_hist', color: '#64748b', label: 'Hist' },
          ]}
          referenceYs={[{ y: 0, color: '#475569' }]}
        />
      )}
      {investigate.Panel}
    </div>
    <ChartContextMenu
      menu={ctxMenu.menu}
      onClose={ctxMenu.close}
      onCopy={handleCopyChart}
      onResetZoom={resetZoom}
      onFullscreen={expand.toggleFullscreen}
      fullscreen={expand.fullscreen}
      onResetChart={handleResetChart}
      onInvestigateAi={investigate.openInvestigate}
    />
    </ChartExpandFrame>
  )
}

export function TickerChartPage({ embedded = false }: { embedded?: boolean } = {}) {
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [ticker, setTicker] = useState('')
  const [mode, setMode] = useState<ChartMode>('daily')
  const [fromDate, setFromDate] = useState(isoDaysAgo(90))
  const [toDate, setToDate] = useState(isoDaysAgo(0))
  const [sessionDate, setSessionDate] = useState(isoDaysAgo(0))
  const [interval, setInterval] = useState('15m')
  const [selectedIndicators, setSelectedIndicators] = useState<IndicatorId[]>(DEFAULT_INDICATORS)
  const [streamOn, setStreamOn] = useState(true)
  const [barCount, setBarCount] = useState(100)
  const [historyBars, setHistoryBars] = useState(300)
  const [error, setError] = useState('')
  const { useAi, setUseAi } = useTradeSetupAi()

  const ready =
    ticker.trim().length >= 1 &&
    (mode === 'daily' ? Boolean(fromDate && toDate) : Boolean(sessionDate && interval))

  useEffect(() => {
    setHistoryBars((h) => Math.max(h, barCount * 3, 300))
  }, [barCount])

  const requestOlderBars = useCallback(() => {
    setHistoryBars((h) => Math.min(500, h + Math.max(40, barCount)))
  }, [barCount])

  const chartPollMs =
    !streamOn
      ? false
      : mode === 'intraday'
        ? interval === '1m'
          ? 8_000
          : interval === '5m'
            ? 12_000
            : 20_000
        : 45_000

  const chartQuery = useQuery({
    queryKey: [
      'ticker-chart',
      assetClass,
      ticker.trim(),
      mode,
      fromDate,
      toDate,
      sessionDate,
      interval,
      selectedIndicators.join(','),
      historyBars,
      streamOn ? 'no-ai' : useAi ? 'ai' : 'no-ai',
    ],
    queryFn: () =>
      runProTradeTickerChart({
        ticker: ticker.trim(),
        asset_class: assetClass,
        mode,
        from_date: mode === 'daily' ? fromDate : undefined,
        to_date: mode === 'daily' ? toDate : undefined,
        session_date: mode === 'intraday' ? sessionDate : undefined,
        interval: mode === 'intraday' ? interval : '1d',
        indicators: selectedIndicators,
        use_ai: streamOn ? false : useAi,
        max_bars: historyBars,
      }),
    enabled: ready,
    refetchInterval: chartPollMs,
    refetchIntervalInBackground: true,
    staleTime: 4_000,
    retry: 1,
  })

  const priceQuery = useQuery({
    queryKey: ['ticker-chart-ltp', assetClass, ticker.trim()],
    queryFn: () => fetchPaperPrice(ticker.trim(), assetClass),
    enabled: ready && streamOn,
    refetchInterval: streamOn ? 2_500 : false,
    refetchIntervalInBackground: true,
    staleTime: 1_000,
    retry: false,
  })

  useEffect(() => {
    if (chartQuery.isError) {
      setError(apiErrorMessage(chartQuery.error))
    } else if (chartQuery.data?.error) {
      setError(String(chartQuery.data.error))
    } else if (chartQuery.data) {
      setError('')
    }
  }, [chartQuery.isError, chartQuery.error, chartQuery.data])

  const data = chartQuery.data as Row | undefined
  const points = (data?.points as Row[] | undefined) ?? []
  const candles = (data?.candles as Candle[] | undefined) ?? []
  const sr = (data?.support_resistance as SupportResistance | null | undefined) ?? null
  const volSr = (data?.volume_sr_summary as VolumeSrSummary | null | undefined) ?? null
  const howTo = (data?.how_to_read as string[] | undefined) ?? []
  const readings = (data?.indicator_readings as Record<string, IndicatorReading> | undefined) ?? {}
  const fibLevels = (data?.fib_levels as SrLevel[] | undefined) ?? []
  const liveLtp = priceQuery.data?.price ?? (data?.last != null ? Number(data.last) : null)

  const rangeTxt = useMemo(() => {
    if (!data) return ''
    if (mode === 'intraday') return `${sessionDate} · ${interval}`
    return `${fromDate} → ${toDate} · 1d`
  }, [data, mode, sessionDate, interval, fromDate, toDate])

  const signalDescription = useMemo(() => {
    if (!data) return ''
    return buildSignalDescription({
      ticker: String(data.ticker ?? ticker),
      rangeTxt,
      changePct: data.change_pct != null ? Number(data.change_pct) : null,
      volSrPlain: String(volSr?.plain_english ?? ''),
      selected: selectedIndicators,
      readings,
    })
  }, [data, ticker, rangeTxt, volSr, selectedIndicators, readings])

  const askContext = data
    ? buildAskContext('Ticker Chart', { ...data, signal_description: signalDescription, indicators: selectedIndicators })
    : ''

  const tradeSetup = useMemo(() => tradeSetupFromResult(data), [data])

  function toggleIndicator(id: IndicatorId) {
    setSelectedIndicators((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id)
      return [...prev, id]
    })
  }

  return (
    <div>
      {!embedded && (
        <PageHeader
          title="Ticker Chart"
          description="Live streaming OHLC — India · US · Crypto · Commodities · S1/S2 · R1/R2 · RSI / EMA / Bollinger / Supertrend"
        />
      )}
      {embedded && (
        <div className="mb-3">
          <h2 className="text-lg font-semibold text-white">Ticker Chart</h2>
          <p className="text-sm text-slate-400">
            Live streaming ticker check — OHLC with S/R, indicators, and signal description
          </p>
        </div>
      )}

      <Card className="mb-4 space-y-3">
        <div className="rounded-lg border border-slate-800/70 bg-slate-950/40 px-3 py-2.5">
          <ChartToolbarRow label="Market">
            {ASSET_CLASSES.map((ac) => (
              <Chip
                key={ac.id}
                selected={assetClass === ac.id}
                onClick={() => {
                  setAssetClass(ac.id)
                  setTicker('')
                  setError('')
                }}
              >
                {ac.label}
              </Chip>
            ))}
          </ChartToolbarRow>
          <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-[minmax(0,1.4fr)_auto]">
            <FormField label="Ticker">
              <TickerAutosuggest
                key={assetClass}
                value={ticker}
                onChange={setTicker}
                assetClass={assetClass}
                placeholder={placeholderFor(assetClass)}
              />
            </FormField>
            <div className="flex flex-wrap items-end gap-2">
              <Chip selected={streamOn} onClick={() => setStreamOn((v) => !v)}>
                {streamOn ? (
                  <span className="inline-flex items-center gap-1"><Wifi size={12} /> Streaming on</span>
                ) : (
                  'Streaming off'
                )}
              </Chip>
              <label className="inline-flex items-center gap-1.5 pb-1 text-xs text-slate-400">
                Bars
                <Select
                  value={String(barCount)}
                  onChange={(e) => {
                    const next = Number(e.target.value)
                    setBarCount(Number.isFinite(next) && next > 0 ? next : 100)
                  }}
                  className="!w-auto !py-1.5 text-xs"
                >
                  {BAR_COUNT_OPTIONS.map((n) => (
                    <option key={n} value={n}>{n}</option>
                  ))}
                </Select>
              </label>
            </div>
          </div>
        </div>

        <div className="rounded-lg border border-slate-800/50 bg-slate-900/25 px-3 py-2.5">
          <ChartToolbarRow label="Mode">
            <Chip selected={mode === 'daily'} onClick={() => setMode('daily')}>
              Daily range
            </Chip>
            <Chip selected={mode === 'intraday'} onClick={() => setMode('intraday')}>
              Same-day intraday
            </Chip>
          </ChartToolbarRow>

          {mode === 'daily' ? (
            <div className="mt-3 space-y-2">
              <div className="grid gap-3 sm:grid-cols-2">
                <FormField label="From date">
                  <input
                    type="date"
                    className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                    value={fromDate}
                    onChange={(e) => setFromDate(e.target.value)}
                  />
                </FormField>
                <FormField label="To date">
                  <input
                    type="date"
                    className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                    value={toDate}
                    onChange={(e) => setToDate(e.target.value)}
                  />
                </FormField>
              </div>
              <ChartToolbarRow label="Quick">
                {[30, 90, 180, 365].map((d) => (
                  <button
                    key={d}
                    type="button"
                    className="rounded-lg border border-slate-700/80 px-2.5 py-1.5 text-xs text-slate-400 hover:border-slate-500 hover:text-slate-200"
                    onClick={() => {
                      setFromDate(isoDaysAgo(d))
                      setToDate(isoDaysAgo(0))
                    }}
                  >
                    {d === 365 ? '1Y' : `${d}D`}
                  </button>
                ))}
              </ChartToolbarRow>
            </div>
          ) : (
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <FormField label="Session date">
                <input
                  type="date"
                  className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                  value={sessionDate}
                  onChange={(e) => setSessionDate(e.target.value)}
                />
              </FormField>
              <FormField label="Timeframe">
                <Select value={interval} onChange={(e) => setInterval(e.target.value)}>
                  {INTRADAY_INTERVALS.map((iv) => (
                    <option key={iv.value} value={iv.value}>
                      {iv.label}
                    </option>
                  ))}
                </Select>
              </FormField>
            </div>
          )}
        </div>

        <div className="rounded-lg border border-slate-800/40 bg-slate-900/15 px-3 py-2.5">
          <ChartToolbarRow label="Indics">
            {INDICATOR_OPTIONS.map((opt) => (
              <Chip
                key={opt.id}
                selected={selectedIndicators.includes(opt.id)}
                onClick={() => toggleIndicator(opt.id)}
              >
                {opt.label}
              </Chip>
            ))}
          </ChartToolbarRow>
          <div className="mt-2 flex flex-wrap gap-2 pl-0 sm:pl-14">
            <button
              type="button"
              className="rounded-lg border border-slate-700/80 px-2.5 py-1 text-[11px] text-slate-400 hover:border-slate-500 hover:text-slate-200"
              onClick={() => setSelectedIndicators(DEFAULT_INDICATORS)}
            >
              Reset defaults
            </button>
            <button
              type="button"
              className="rounded-lg border border-slate-700/80 px-2.5 py-1 text-[11px] text-slate-400 hover:border-slate-500 hover:text-slate-200"
              onClick={() => setSelectedIndicators(INDICATOR_OPTIONS.map((o) => o.id))}
            >
              Select all
            </button>
            <button
              type="button"
              className="rounded-lg border border-slate-700/80 px-2.5 py-1 text-[11px] text-slate-400 hover:border-slate-500 hover:text-slate-200"
              onClick={() => setSelectedIndicators([])}
            >
              Clear
            </button>
          </div>
        </div>

        <p className="text-xs text-slate-500">
          Chart loads automatically once a ticker and date range (or intraday session) are set.
          With <span className="text-slate-300">Streaming on</span>, LTP updates the forming candle every ~2.5s
          and bars refresh on a short poll. Turn streaming off to use AI refine.
        </p>
        <UseAiCheckbox
          checked={useAi && !streamOn}
          onChange={(v) => {
            if (v) setStreamOn(false)
            setUseAi(v)
          }}
        />
        {useAi && streamOn && (
          <p className="mt-1 text-[11px] text-amber-400/90">Turn streaming off to enable AI refine.</p>
        )}
      </Card>

      {error && (
        <div className="mb-4">
          <Alert type="error">{error}</Alert>
        </div>
      )}

      {chartQuery.isLoading && !data && (
        <Loading
          message={
            useAi && !streamOn
              ? 'Drawing chart + AI-refining trade setup…'
              : 'Drawing chart with support & resistance…'
          }
        />
      )}

      {data && (
        <Card className="mb-4">
          <StrategyDataSourceBar data={data} assetClass={assetClass} />
          <div className="mb-3 flex flex-wrap items-center gap-2">
            {data.summary != null && <p className="text-sm text-slate-300">{String(data.summary)}</p>}
            {liveLtp != null && (
              <span className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500/15 px-2.5 py-0.5 text-xs font-semibold tabular-nums text-emerald-300 ring-1 ring-emerald-500/30">
                LTP {fmtNum(liveLtp, 2)}
                {streamOn && (
                  <span className="inline-flex items-center gap-0.5 text-[10px] font-normal text-emerald-400/80">
                    <Wifi size={10} /> live
                  </span>
                )}
              </span>
            )}
            {data.change_pct != null && (
              <span
                className={`inline-flex rounded-lg px-2.5 py-0.5 text-xs font-semibold tabular-nums ring-1 ${
                  Number(data.change_pct) >= 0
                    ? 'bg-emerald-500/15 text-emerald-400 ring-emerald-500/30'
                    : 'bg-rose-500/15 text-rose-400 ring-rose-500/30'
                }`}
              >
                {Number(data.change_pct) >= 0 ? '+' : ''}
                {fmtNum(data.change_pct, 2)}%
              </span>
            )}
            {chartQuery.isFetching && streamOn && (
              <span className="text-[11px] text-slate-500">refreshing…</span>
            )}
            {data.yf_symbol != null && (
              <span className="text-xs text-slate-500">{String(data.yf_symbol)}</span>
            )}
            <span className="text-[11px] text-slate-500">
              view {barCount} · loaded {historyBars}
            </span>
          </div>

          {tradeSetup && (
            <div className="mb-3">
              <TradeSetupBanner setup={tradeSetup} />
            </div>
          )}

          {forecastFromResult(data) && (
            <div className="mb-3">
              <FallRiseForecastCards forecast={forecastFromResult(data)} />
            </div>
          )}

          {signalDescription && (
            <div className="mb-3 rounded-lg border border-slate-800/70 bg-slate-950/50 p-3">
              <div className="mb-1 flex items-center justify-between gap-2">
                <p className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
                  Signal description
                </p>
                <CopyAllButton text={signalDescription} />
              </div>
              <p className="text-xs leading-relaxed text-slate-300">{signalDescription}</p>
              {selectedIndicators.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {selectedIndicators.map((id) => {
                    const r = readings[id]
                    const bias = String(r?.bias || 'neutral')
                    const tone =
                      bias === 'bullish'
                        ? 'bg-emerald-500/10 text-emerald-400 ring-emerald-500/25'
                        : bias === 'bearish'
                          ? 'bg-rose-500/10 text-rose-400 ring-rose-500/25'
                          : 'bg-slate-500/10 text-slate-400 ring-slate-500/25'
                    return (
                      <span
                        key={id}
                        className={`inline-flex rounded-md px-2 py-0.5 text-[10px] ring-1 ${tone}`}
                        title={String(r?.detail || '')}
                      >
                        {r?.label || id}: {r?.signal || '—'}
                      </span>
                    )
                  })}
                </div>
              )}
            </div>
          )}

          {howTo.length > 0 && (
            <div className="mb-3 border-b border-slate-800/60 pb-3">
              <div className="mb-1 flex justify-end">
                <CopyAllButton text={howTo.map((line) => `· ${line}`).join('\n')} />
              </div>
              <ul className="space-y-0.5">
                {howTo.map((line) => (
                  <li key={line} className="text-xs text-slate-500">
                    · {line}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <PriceChart
            points={points}
            candles={candles}
            supportResistance={sr}
            title={`${String(data.ticker ?? ticker)} · ${mode === 'intraday' ? interval : '1d'}`}
            volumeSrSummary={volSr}
            selected={selectedIndicators}
            fibLevels={fibLevels}
            liveLtp={streamOn ? liveLtp : null}
            maxBars={barCount}
            onNeedOlder={requestOlderBars}
          />
        </Card>
      )}

      {askContext && (
        <AskAIPanel
          context={askContext}
          section="pro-trade/ticker-chart"
          title="Investigate with AI"
          buttonLabel="Investigate with AI"
          defaultQuestion="You are a price action & smart money expert looking at this chart. Should I take a trade now? If yes, LONG or SHORT with %SL, %TP, and %Confidence. If no, explain why to wait."
          showPredictNextMove
        />
      )}
    </div>
  )
}
