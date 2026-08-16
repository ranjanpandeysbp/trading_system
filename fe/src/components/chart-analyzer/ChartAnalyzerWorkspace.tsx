import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import {
  ChartCandlestick,
  History,
  Maximize2,
  Minimize2,
  PanelRightClose,
  PanelRightOpen,
  Wifi,
  WifiOff,
} from 'lucide-react'
import { apiErrorMessage, fetchPaperPrice, runProTradeTickerChart } from '../../api/client'
import { AskAIPanel, buildAskContext } from '../ai/AskAIPanel'
import {
  ChartDrawingToolbar,
  useChartDrawings,
} from '../charts/ChartDrawingLayer'
import type { AssetClass } from '../command-center/AssetClassTickerPicker'
import { useLayoutChrome } from '../layout/LayoutChromeContext'
import { PriceChart } from '../pro-trade/TickerChartPanel'
import { FallRiseForecastCards, forecastFromResult } from '../pro-trade/FallRiseForecastCards'
import { TradeSetupBanner, tradeSetupFromResult } from '../pro-trade/TradeSetupBanner'
import { Alert, Loading } from '../ui/Feedback'
import { Chip } from '../ui/Chip'
import { Select } from '../ui/Form'
import { StrategyDataSourceBar } from '../ui/StrategyDataSourceBar'
import { TickerAutosuggest } from '../ui/TickerAutosuggest'
import { CopyAllButton } from '../ui/CopyAllButton'
import type { VolumeSrSummary } from '../ui/VolumeSrSummaryCard'
import { VolumeSrSummaryCard } from '../ui/VolumeSrSummaryCard'

type Row = Record<string, unknown>
type ChartMode = 'daily' | 'intraday'

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
}

type TimeframeId =
  | '1m'
  | '5m'
  | '15m'
  | '30m'
  | '1h'
  | '1D'
  | '5D'
  | '1M'
  | '3M'
  | '6M'
  | '1Y'
  | '5Y'

type Timeframe = {
  id: TimeframeId
  label: string
  mode: ChartMode
  interval?: string
  rangeDays?: number
}

const ASSET_CLASSES: { id: AssetClass; label: string }[] = [
  { id: 'india', label: 'India' },
  { id: 'us', label: 'US' },
  { id: 'crypto', label: 'Crypto' },
  { id: 'commodity', label: 'Commodities' },
]

const TIMEFRAMES: Timeframe[] = [
  { id: '1m', label: '1m', mode: 'intraday', interval: '1m' },
  { id: '5m', label: '5m', mode: 'intraday', interval: '5m' },
  { id: '15m', label: '15m', mode: 'intraday', interval: '15m' },
  { id: '30m', label: '30m', mode: 'intraday', interval: '30m' },
  { id: '1h', label: '1H', mode: 'intraday', interval: '1h' },
  { id: '1D', label: '1D', mode: 'daily', rangeDays: 120 },
  { id: '5D', label: '5D', mode: 'daily', rangeDays: 10 },
  { id: '1M', label: '1M', mode: 'daily', rangeDays: 45 },
  { id: '3M', label: '3M', mode: 'daily', rangeDays: 100 },
  { id: '6M', label: '6M', mode: 'daily', rangeDays: 200 },
  { id: '1Y', label: '1Y', mode: 'daily', rangeDays: 380 },
  { id: '5Y', label: '5Y', mode: 'daily', rangeDays: 365 * 5 + 30 },
]

const INDICATOR_OPTIONS: { id: IndicatorId; label: string; group: 'overlay' | 'oscillator' | 'levels' }[] = [
  { id: 'volume', label: 'Volume', group: 'overlay' },
  { id: 'vwap', label: 'VWAP', group: 'overlay' },
  { id: 'supertrend', label: 'Supertrend', group: 'overlay' },
  { id: 'bollinger', label: 'Bollinger Band', group: 'overlay' },
  { id: 'ema_5', label: 'EMA 5', group: 'overlay' },
  { id: 'ema_9', label: 'EMA 9', group: 'overlay' },
  { id: 'ema_20', label: 'EMA 20', group: 'overlay' },
  { id: 'ema_50', label: 'EMA 50', group: 'overlay' },
  { id: 'ema_200', label: 'EMA 200', group: 'overlay' },
  { id: 'rsi', label: 'RSI', group: 'oscillator' },
  { id: 'macd', label: 'MACD', group: 'oscillator' },
  { id: 'fibonacci', label: 'Fibonacci', group: 'levels' },
]

/** Primary analysis indicators shown as quick-toggle chips on the chart toolbar. */
const TOOLBAR_INDICATORS: { id: IndicatorId; label: string }[] = [
  { id: 'rsi', label: 'RSI' },
  { id: 'macd', label: 'MACD' },
  { id: 'supertrend', label: 'Supertrend' },
  { id: 'vwap', label: 'VWAP' },
  { id: 'bollinger', label: 'Bollinger Band' },
  { id: 'ema_5', label: 'EMA 5' },
  { id: 'ema_9', label: 'EMA 9' },
  { id: 'ema_20', label: 'EMA 20' },
  { id: 'ema_50', label: 'EMA 50' },
  { id: 'ema_200', label: 'EMA 200' },
]

const DEFAULT_INDICATORS: IndicatorId[] = ['volume', 'ema_9', 'ema_20', 'bollinger', 'rsi']
const BAR_COUNT_OPTIONS = [60, 80, 100, 120, 150, 200, 300, 500] as const
const RECENT_KEY = 'chart-analyzer-recent'
const RIGHT_TAB_KEY = 'chart-analyzer-right-tab'

type RecentItem = { assetClass: AssetClass; ticker: string; at: number }
type RightTab = 'indicators' | 'levels' | 'setup' | 'ai'

function isoDaysAgo(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() - days)
  return d.toISOString().slice(0, 10)
}

function todayIso(): string {
  return isoDaysAgo(0)
}

function fmtNum(v: unknown, digits = 2): string {
  if (v == null || v === '') return '—'
  const n = Number(v)
  return Number.isFinite(n) ? n.toLocaleString(undefined, { maximumFractionDigits: digits }) : '—'
}

function placeholderFor(ac: AssetClass): string {
  if (ac === 'us') return 'Search US ticker…'
  if (ac === 'crypto') return 'Search crypto…'
  if (ac === 'commodity') return 'Search commodity…'
  return 'Search NSE ticker…'
}

function loadRecent(): RecentItem[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as RecentItem[]
    return Array.isArray(parsed) ? parsed.slice(0, 12) : []
  } catch {
    return []
  }
}

function saveRecent(item: RecentItem) {
  const prev = loadRecent().filter(
    (r) => !(r.assetClass === item.assetClass && r.ticker.toUpperCase() === item.ticker.toUpperCase()),
  )
  localStorage.setItem(RECENT_KEY, JSON.stringify([{ ...item, at: Date.now() }, ...prev].slice(0, 12)))
}

const ASSET_CLASS_IDS = new Set<string>(ASSET_CLASSES.map((a) => a.id))
const TIMEFRAME_IDS = new Set<string>(TIMEFRAMES.map((t) => t.id))

/** Map common aliases (e.g. watchlist `1d`) onto Chart Analyzer timeframe ids. */
function normalizeTfParam(raw: string | null): TimeframeId | null {
  if (!raw) return null
  const v = raw.trim()
  if (TIMEFRAME_IDS.has(v)) return v as TimeframeId
  const lower = v.toLowerCase()
  if (lower === '1d' || lower === 'd' || lower === 'daily') return '1D'
  if (lower === '1w' || lower === 'w' || lower === 'weekly') return '5D'
  if (lower === '4h') return '1h'
  return null
}

export function ChartAnalyzerWorkspace() {
  const [searchParams] = useSearchParams()
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [ticker, setTicker] = useState('')
  const [tfId, setTfId] = useState<TimeframeId>('15m')
  const [sessionDate, setSessionDate] = useState(todayIso())
  const [selectedIndicators, setSelectedIndicators] = useState<IndicatorId[]>(DEFAULT_INDICATORS)
  const [streamOn, setStreamOn] = useState(true)
  const [barCount, setBarCount] = useState(150)
  const [error, setError] = useState('')
  const [rightOpen, setRightOpen] = useState(true)
  const [rightTab, setRightTab] = useState<RightTab>(() => {
    try {
      const v = localStorage.getItem(RIGHT_TAB_KEY) as RightTab | null
      return v && ['indicators', 'levels', 'setup', 'ai'].includes(v) ? v : 'indicators'
    } catch {
      return 'indicators'
    }
  })
  const [recent, setRecent] = useState<RecentItem[]>(() => loadRecent())
  const drawingsApi = useChartDrawings()
  const { immersive, setImmersive, toggleImmersive } = useLayoutChrome()

  useEffect(() => {
    return () => setImmersive(false)
  }, [setImmersive])

  // Deep-link from Watchlist / other pages: /chart-analyzer?ticker=RELIANCE&assetClass=india&tf=15m
  useEffect(() => {
    const t = (searchParams.get('ticker') || searchParams.get('symbol') || '').trim()
    const acRaw = (searchParams.get('assetClass') || searchParams.get('asset') || '').trim().toLowerCase()
    const tf = normalizeTfParam(searchParams.get('tf') || searchParams.get('timeframe'))
    if (acRaw && ASSET_CLASS_IDS.has(acRaw)) setAssetClass(acRaw as AssetClass)
    if (tf) setTfId(tf)
    if (t) {
      setTicker(t.toUpperCase())
      setError('')
    }
  }, [searchParams])

  const tf = TIMEFRAMES.find((t) => t.id === tfId) ?? TIMEFRAMES[2]
  const mode = tf.mode
  const interval = tf.interval ?? '15m'
  const fromDate = isoDaysAgo(tf.rangeDays ?? 120)
  const toDate = todayIso()

  const ready = ticker.trim().length >= 1

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
      'chart-analyzer',
      assetClass,
      ticker.trim(),
      mode,
      fromDate,
      toDate,
      sessionDate,
      interval,
      selectedIndicators.join(','),
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
        use_ai: false,
      }),
    enabled: ready,
    refetchInterval: chartPollMs,
    refetchIntervalInBackground: true,
    staleTime: 4_000,
    retry: 1,
  })

  const priceQuery = useQuery({
    queryKey: ['chart-analyzer-ltp', assetClass, ticker.trim()],
    queryFn: () => fetchPaperPrice(ticker.trim(), assetClass),
    enabled: ready && streamOn,
    refetchInterval: streamOn ? 2_500 : false,
    refetchIntervalInBackground: true,
    staleTime: 1_000,
    retry: false,
  })

  useEffect(() => {
    if (chartQuery.isError) setError(apiErrorMessage(chartQuery.error))
    else if (chartQuery.data?.error) setError(String(chartQuery.data.error))
    else if (chartQuery.data) setError('')
  }, [chartQuery.isError, chartQuery.error, chartQuery.data])

  useEffect(() => {
    if (!ready || !chartQuery.data || chartQuery.data.error) return
    const t = String(chartQuery.data.ticker ?? ticker).trim()
    if (!t) return
    saveRecent({ assetClass, ticker: t, at: Date.now() })
    setRecent(loadRecent())
  }, [chartQuery.data, ready, assetClass, ticker])

  useEffect(() => {
    try {
      localStorage.setItem(RIGHT_TAB_KEY, rightTab)
    } catch {
      /* ignore */
    }
  }, [rightTab])

  useEffect(() => {
    drawingsApi.clear()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker, assetClass, tfId])

  const data = chartQuery.data as Row | undefined
  const points = (data?.points as Row[] | undefined) ?? []
  const candles = (data?.candles as { t?: string; label?: string; open?: number; high?: number; low?: number; close?: number; volume?: number | null }[] | undefined) ?? []
  const sr = (data?.support_resistance as SupportResistance | null | undefined) ?? null
  const volSr = (data?.volume_sr_summary as VolumeSrSummary | null | undefined) ?? null
  const howTo = (data?.how_to_read as string[] | undefined) ?? []
  const readings = (data?.indicator_readings as Record<string, IndicatorReading> | undefined) ?? {}
  const fibLevels = (data?.fib_levels as SrLevel[] | undefined) ?? []
  const liveLtp = priceQuery.data?.price ?? (data?.last != null ? Number(data.last) : null)
  const tradeSetup = useMemo(() => tradeSetupFromResult(data), [data])
  const askContext = data
    ? buildAskContext('Chart Analyzer', {
        ...data,
        timeframe: tf.label,
        indicators: selectedIndicators,
      })
    : ''

  const srLevels = useMemo(() => {
    if (sr?.levels?.length) {
      return sr.levels
        .map((lv) => ({
          label: String(lv.label),
          kind: String(lv.kind),
          price: Number(lv.price),
        }))
        .filter((lv) => Number.isFinite(lv.price))
    }
    const out: { label: string; kind: string; price: number }[] = []
    if (sr?.s2 != null) out.push({ label: 'S2', kind: 'support', price: Number(sr.s2) })
    if (sr?.s1 != null) out.push({ label: 'S1', kind: 'support', price: Number(sr.s1) })
    if (sr?.r1 != null) out.push({ label: 'R1', kind: 'resistance', price: Number(sr.r1) })
    if (sr?.r2 != null) out.push({ label: 'R2', kind: 'resistance', price: Number(sr.r2) })
    return out
  }, [sr])

  function toggleIndicator(id: IndicatorId) {
    setSelectedIndicators((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    )
  }

  function applyTicker(next: string, ac: AssetClass = assetClass) {
    setAssetClass(ac)
    setTicker(next)
    setError('')
  }

  return (
    <div
      className={
        immersive
          ? 'flex h-dvh min-h-0 flex-col bg-slate-950'
          : '-mx-4 -mb-4 flex min-h-[calc(100dvh-7.5rem)] flex-col sm:-mx-6 lg:-mx-8 lg:min-h-[calc(100dvh-6rem)]'
      }
    >
      {/* Top symbol / timeframe bar */}
      <div className="sticky top-0 z-20 shrink-0 border-b border-slate-800/80 bg-slate-950/95 px-3 py-2 backdrop-blur-xl sm:px-4">
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1.5 text-slate-200">
            <ChartCandlestick size={18} className="text-sky-400" />
            <span className="text-sm font-semibold tracking-tight">Chart Analyzer</span>
          </div>
          <div className="hidden h-5 w-px bg-slate-800 sm:block" />
          <div className="flex flex-wrap gap-1">
            {ASSET_CLASSES.map((ac) => (
              <button
                key={ac.id}
                type="button"
                onClick={() => {
                  setAssetClass(ac.id)
                  setTicker('')
                  setError('')
                }}
                className={`rounded-md px-2 py-1 text-[11px] font-medium transition-colors ${
                  assetClass === ac.id
                    ? 'bg-sky-500/20 text-sky-300 ring-1 ring-sky-500/40'
                    : 'text-slate-500 hover:bg-slate-800/60 hover:text-slate-300'
                }`}
              >
                {ac.label}
              </button>
            ))}
          </div>
          <div className="min-w-[10rem] flex-1 sm:max-w-xs">
            <TickerAutosuggest
              key={assetClass}
              value={ticker}
              onChange={setTicker}
              assetClass={assetClass}
              placeholder={placeholderFor(assetClass)}
            />
          </div>
          {liveLtp != null && ready && (
            <span className="inline-flex items-center gap-1.5 rounded-md bg-emerald-500/10 px-2 py-1 text-xs font-semibold tabular-nums text-emerald-300 ring-1 ring-emerald-500/25">
              {fmtNum(liveLtp, liveLtp >= 100 ? 2 : 4)}
              {data?.change_pct != null && (
                <span className={Number(data.change_pct) >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                  {Number(data.change_pct) >= 0 ? '+' : ''}
                  {fmtNum(data.change_pct, 2)}%
                </span>
              )}
            </span>
          )}
          <button
            type="button"
            onClick={() => setStreamOn((v) => !v)}
            className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] ring-1 ${
              streamOn
                ? 'bg-emerald-500/10 text-emerald-300 ring-emerald-500/30'
                : 'bg-slate-800/50 text-slate-400 ring-slate-700'
            }`}
            title="Live streaming"
          >
            {streamOn ? <Wifi size={12} /> : <WifiOff size={12} />}
            {streamOn ? 'Live' : 'Paused'}
          </button>
          <label className="inline-flex items-center gap-1 text-[11px] text-slate-500">
            Bars
            <Select
              value={String(barCount)}
              onChange={(e) => setBarCount(Number(e.target.value) || 150)}
              className="!w-auto !py-1 text-[11px]"
            >
              {BAR_COUNT_OPTIONS.map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </Select>
          </label>
          <button
            type="button"
            onClick={() => setRightOpen((v) => !v)}
            className="inline-flex items-center gap-1 rounded-md border border-slate-800 px-2 py-1 text-[11px] text-slate-400 hover:border-slate-600 hover:text-slate-200"
            title={rightOpen ? 'Hide side panel' : 'Show side panel'}
          >
            {rightOpen ? <PanelRightClose size={13} /> : <PanelRightOpen size={13} />}
            Panel
          </button>
          <button
            type="button"
            onClick={toggleImmersive}
            className={`ml-auto inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[11px] font-medium ring-1 transition-colors ${
              immersive
                ? 'bg-amber-500/15 text-amber-200 ring-amber-500/40 hover:bg-amber-500/25'
                : 'border border-slate-800 bg-slate-900/60 text-slate-300 ring-transparent hover:border-sky-500/40 hover:text-sky-200'
            }`}
            title={immersive ? 'Exit fullscreen (Esc) — restore sidebar & ticker' : 'Fullscreen — hide sidebar & top ticker'}
          >
            {immersive ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
            {immersive ? 'Exit fullscreen' : 'Fullscreen'}
          </button>
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-1">
          {TIMEFRAMES.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setTfId(t.id)}
              className={`rounded px-2 py-0.5 text-[11px] font-medium tabular-nums transition-colors ${
                tfId === t.id
                  ? 'bg-blue-500/20 text-blue-300 ring-1 ring-blue-500/40'
                  : 'text-slate-500 hover:bg-slate-800/70 hover:text-slate-300'
              }`}
            >
              {t.label}
            </button>
          ))}
          {mode === 'intraday' && (
            <div className="ml-2 inline-flex items-center gap-1.5">
              <span className="text-[10px] uppercase tracking-wide text-slate-600">Session</span>
              <input
                type="date"
                value={sessionDate}
                onChange={(e) => setSessionDate(e.target.value)}
                className="rounded border border-slate-700 bg-slate-900 px-2 py-0.5 text-[11px] text-slate-200"
              />
            </div>
          )}
          <span className="ml-auto text-[10px] text-slate-600 sm:ml-0">
            {immersive
              ? 'Fullscreen · Esc exits · drag to pan · Ctrl+scroll zoom'
              : 'Hold & drag to pan · Ctrl+scroll zoom · Fullscreen hides sidebar'}
          </span>
        </div>

        {/* Indicator quick toggles — apply one or more */}
        <div className="mt-2 flex flex-wrap items-center gap-1.5 border-t border-slate-800/60 pt-2">
          <span className="mr-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
            Indicators
          </span>
          {TOOLBAR_INDICATORS.map((opt) => (
            <Chip
              key={opt.id}
              selected={selectedIndicators.includes(opt.id)}
              onClick={() => toggleIndicator(opt.id)}
              title={
                selectedIndicators.includes(opt.id)
                  ? `Remove ${opt.label}`
                  : `Apply ${opt.label}`
              }
            >
              {opt.label}
            </Chip>
          ))}
          <span className="mx-1 hidden h-4 w-px bg-slate-800 sm:inline-block" />
          <Chip
            selected={selectedIndicators.includes('volume')}
            onClick={() => toggleIndicator('volume')}
            title="Volume bars"
          >
            Volume
          </Chip>
          <Chip
            selected={selectedIndicators.includes('fibonacci')}
            onClick={() => toggleIndicator('fibonacci')}
            title="Fibonacci levels"
          >
            Fib
          </Chip>
          <button
            type="button"
            className="rounded-md px-2 py-0.5 text-[10px] text-slate-500 hover:text-slate-300"
            onClick={() => setSelectedIndicators(DEFAULT_INDICATORS)}
            title="Reset to default indicators"
          >
            Defaults
          </button>
          <button
            type="button"
            className="rounded-md px-2 py-0.5 text-[10px] text-slate-500 hover:text-slate-300"
            onClick={() =>
              setSelectedIndicators((prev) => {
                const ids = TOOLBAR_INDICATORS.map((o) => o.id)
                const allOn = ids.every((id) => prev.includes(id))
                if (allOn) return prev.filter((id) => !ids.includes(id))
                const next = new Set(prev)
                ids.forEach((id) => next.add(id))
                return Array.from(next)
              })
            }
            title="Toggle all analysis indicators"
          >
            {TOOLBAR_INDICATORS.every((o) => selectedIndicators.includes(o.id))
              ? 'Clear indicators'
              : 'All indicators'}
          </button>
        </div>
      </div>

      {/* Workspace body */}
      <div className={`flex min-h-0 flex-1 ${immersive ? 'overflow-hidden' : ''}`}>
        {/* Left drawing tools */}
        <aside className="hidden w-12 shrink-0 flex-col items-center gap-2 border-r border-slate-800/80 bg-slate-950/60 py-3 sm:flex">
          <p className="mb-1 rotate-0 text-[9px] font-medium uppercase tracking-wider text-slate-600">
            Draw
          </p>
          <ChartDrawingToolbar
            orientation="vertical"
            tool={drawingsApi.tool}
            setTool={drawingsApi.setTool}
            selectedId={drawingsApi.selectedId}
            drawings={drawingsApi.drawings}
            patch={drawingsApi.patch}
            removeSelected={drawingsApi.removeSelected}
            clear={drawingsApi.clear}
          />
        </aside>

        {/* Main chart */}
        <div className={`min-w-0 flex-1 overflow-auto p-2 sm:p-3 ${immersive ? 'min-h-0' : ''}`}>
          {error && (
            <div className="mb-3">
              <Alert type="error">{error}</Alert>
            </div>
          )}

          {!ready && (
            <div className="flex h-[min(70vh,560px)] flex-col items-center justify-center rounded-xl border border-dashed border-slate-800 bg-slate-950/40 px-6 text-center">
              <ChartCandlestick className="mb-3 text-slate-600" size={40} />
              <p className="text-sm font-medium text-slate-300">Pick a ticker to start analyzing</p>
              <p className="mt-1 max-w-md text-xs text-slate-500">
                India · US · Crypto · Commodities — all timeframes, indicators, Fibonacci, trend tools,
                live LTP streaming, zoom, and fullscreen — TradingView-style workflow.
              </p>
              {recent.length > 0 && (
                <div className="mt-5 w-full max-w-lg">
                  <p className="mb-2 flex items-center justify-center gap-1 text-[11px] uppercase tracking-wide text-slate-600">
                    <History size={12} /> Recent
                  </p>
                  <div className="flex flex-wrap justify-center gap-1.5">
                    {recent.map((r) => (
                      <button
                        key={`${r.assetClass}-${r.ticker}`}
                        type="button"
                        onClick={() => applyTicker(r.ticker, r.assetClass)}
                        className="rounded-lg border border-slate-800 bg-slate-900/80 px-2.5 py-1.5 text-xs text-slate-300 hover:border-sky-500/40 hover:text-sky-300"
                      >
                        <span className="text-slate-500">{r.assetClass}/</span>
                        {r.ticker}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {ready && chartQuery.isLoading && !data && (
            <Loading message="Loading OHLC + indicators…" />
          )}

          {ready && data && !data.error && (
            <div className="space-y-3">
              <div className="sm:hidden">
                <ChartDrawingToolbar
                  tool={drawingsApi.tool}
                  setTool={drawingsApi.setTool}
                  selectedId={drawingsApi.selectedId}
                  drawings={drawingsApi.drawings}
                  patch={drawingsApi.patch}
                  removeSelected={drawingsApi.removeSelected}
                  clear={drawingsApi.clear}
                />
              </div>
              <StrategyDataSourceBar data={data} assetClass={assetClass} />
              <PriceChart
                points={points}
                candles={candles}
                supportResistance={sr}
                title={`${String(data.ticker ?? ticker)} · ${tf.label}`}
                volumeSrSummary={volSr}
                selected={selectedIndicators}
                fibLevels={fibLevels}
                liveLtp={streamOn ? liveLtp : null}
                maxBars={barCount}
                workspace
                hideDrawingToolbar
                externalDrawings={drawingsApi}
              />
            </div>
          )}
        </div>

        {/* Right analysis panel — desktop sidebar */}
        {rightOpen && (
          <aside className="hidden w-[min(100%,320px)] shrink-0 flex-col border-l border-slate-800/80 bg-slate-950/70 xl:flex">
            <RightPanelBody
              rightTab={rightTab}
              setRightTab={setRightTab}
              selectedIndicators={selectedIndicators}
              toggleIndicator={toggleIndicator}
              setSelectedIndicators={setSelectedIndicators}
              readings={readings}
              volSr={volSr}
              srLevels={srLevels}
              fibLevels={fibLevels}
              recent={recent}
              applyTicker={applyTicker}
              data={data}
              tradeSetup={tradeSetup}
              howTo={howTo}
              askContext={askContext}
            />
          </aside>
        )}
      </div>

      {/* Mobile / tablet analysis panel */}
      {rightOpen && (
        <div className="border-t border-slate-800/80 bg-slate-950/80 xl:hidden">
          <RightPanelBody
            rightTab={rightTab}
            setRightTab={setRightTab}
            selectedIndicators={selectedIndicators}
            toggleIndicator={toggleIndicator}
            setSelectedIndicators={setSelectedIndicators}
            readings={readings}
            volSr={volSr}
            srLevels={srLevels}
            fibLevels={fibLevels}
            recent={recent}
            applyTicker={applyTicker}
            data={data}
            tradeSetup={tradeSetup}
            howTo={howTo}
            askContext={askContext}
          />
        </div>
      )}
    </div>
  )
}

function RightPanelBody({
  rightTab,
  setRightTab,
  selectedIndicators,
  toggleIndicator,
  setSelectedIndicators,
  readings,
  volSr,
  srLevels,
  fibLevels,
  recent,
  applyTicker,
  data,
  tradeSetup,
  howTo,
  askContext,
}: {
  rightTab: RightTab
  setRightTab: (t: RightTab) => void
  selectedIndicators: IndicatorId[]
  toggleIndicator: (id: IndicatorId) => void
  setSelectedIndicators: (v: IndicatorId[] | ((p: IndicatorId[]) => IndicatorId[])) => void
  readings: Record<string, IndicatorReading>
  volSr: VolumeSrSummary | null
  srLevels: { label: string; kind: string; price: number }[]
  fibLevels: SrLevel[]
  recent: RecentItem[]
  applyTicker: (ticker: string, ac?: AssetClass) => void
  data: Row | undefined
  tradeSetup: ReturnType<typeof tradeSetupFromResult>
  howTo: string[]
  askContext: string
}) {
  return (
    <>
      <div className="flex border-b border-slate-800/80">
        {(
          [
            { id: 'indicators' as const, label: 'Indicators' },
            { id: 'levels' as const, label: 'Levels' },
            { id: 'setup' as const, label: 'Setup' },
            { id: 'ai' as const, label: 'AI' },
          ] as const
        ).map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setRightTab(tab.id)}
            className={`flex-1 px-1 py-2.5 text-[11px] font-medium ${
              rightTab === tab.id
                ? 'border-b-2 border-sky-400 text-sky-300'
                : 'text-slate-500 hover:text-slate-300'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3 xl:max-h-none max-h-[50vh]">
        {rightTab === 'indicators' && (
          <div className="space-y-4">
            {(['overlay', 'oscillator', 'levels'] as const).map((group) => (
              <div key={group}>
                <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                  {group === 'overlay' ? 'Overlays' : group === 'oscillator' ? 'Oscillators' : 'Levels'}
                </p>
                <div className="flex flex-col gap-1">
                  {INDICATOR_OPTIONS.filter((o) => o.group === group).map((opt) => (
                    <label
                      key={opt.id}
                      className="flex cursor-pointer items-center justify-between rounded-lg px-2 py-1.5 text-xs hover:bg-slate-900"
                    >
                      <span className="text-slate-300">{opt.label}</span>
                      <input
                        type="checkbox"
                        checked={selectedIndicators.includes(opt.id)}
                        onChange={() => toggleIndicator(opt.id)}
                        className="h-3.5 w-3.5 rounded border-slate-600 bg-slate-900 text-sky-500 focus:ring-sky-500/40"
                      />
                    </label>
                  ))}
                </div>
              </div>
            ))}
            <div className="flex flex-wrap gap-1.5 border-t border-slate-800/60 pt-3">
              <Chip selected={false} onClick={() => setSelectedIndicators(DEFAULT_INDICATORS)}>
                Defaults
              </Chip>
              <Chip
                selected={false}
                onClick={() => setSelectedIndicators(INDICATOR_OPTIONS.map((o) => o.id))}
              >
                All
              </Chip>
              <Chip selected={false} onClick={() => setSelectedIndicators([])}>
                Clear
              </Chip>
            </div>
            {Object.keys(readings).length > 0 && (
              <div className="space-y-1.5 border-t border-slate-800/60 pt-3">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                  Readings
                </p>
                {selectedIndicators.map((id) => {
                  const r = readings[id]
                  if (!r) return null
                  const bias = String(r.bias || 'neutral')
                  const tone =
                    bias === 'bullish'
                      ? 'text-emerald-400'
                      : bias === 'bearish'
                        ? 'text-rose-400'
                        : 'text-slate-400'
                  return (
                    <div key={id} className="rounded-lg border border-slate-800/60 bg-slate-900/40 px-2 py-1.5">
                      <p className={`text-[11px] font-medium ${tone}`}>
                        {r.label || id}: {r.signal || '—'}
                      </p>
                      {r.detail && (
                        <p className="mt-0.5 text-[10px] leading-snug text-slate-500">{r.detail}</p>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}

        {rightTab === 'levels' && (
          <div className="space-y-3">
            <VolumeSrSummaryCard data={volSr} />
            {srLevels.length === 0 ? (
              <p className="text-xs text-slate-500">Load a chart to see S/R levels.</p>
            ) : (
              <>
                <p className="text-[11px] text-slate-500">
                  Use the <span className="text-slate-300">S/R on/off</span> chip on the chart toolbar to hide or show automatic support &amp; resistance lines.
                </p>
                <div className="space-y-1">
                  {srLevels.map((lv) => (
                    <div
                      key={`${lv.label}-${lv.price}`}
                      className="flex items-center justify-between rounded-lg border border-slate-800/60 bg-slate-900/40 px-2.5 py-1.5 text-xs"
                    >
                      <span className={lv.kind === 'support' ? 'text-emerald-400' : 'text-rose-400'}>
                        {lv.label}
                      </span>
                      <span className="tabular-nums text-slate-200">
                        {fmtNum(lv.price, lv.price >= 100 ? 2 : 4)}
                      </span>
                    </div>
                  ))}
                </div>
              </>
            )}
            {fibLevels.length > 0 && (
              <div>
                <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                  Fibonacci
                </p>
                <div className="space-y-1">
                  {fibLevels.map((lv) => (
                    <div
                      key={`${lv.label}-${lv.price}`}
                      className="flex justify-between text-[11px] text-amber-300/90"
                    >
                      <span>{lv.label}</span>
                      <span className="tabular-nums">{fmtNum(lv.price, 2)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {recent.length > 0 && (
              <div>
                <p className="mb-1.5 flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                  <History size={11} /> Recent symbols
                </p>
                <div className="flex flex-col gap-1">
                  {recent.map((r) => (
                    <button
                      key={`${r.assetClass}-${r.ticker}`}
                      type="button"
                      onClick={() => applyTicker(r.ticker, r.assetClass)}
                      className="rounded-lg px-2 py-1.5 text-left text-xs text-slate-300 hover:bg-slate-900"
                    >
                      <span className="text-slate-600">{r.assetClass} · </span>
                      {r.ticker}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {rightTab === 'setup' && (
          <div className="space-y-3">
            {!data && <p className="text-xs text-slate-500">Chart data appears here after load.</p>}
            {tradeSetup && <TradeSetupBanner setup={tradeSetup} />}
            {forecastFromResult(data) && (
              <FallRiseForecastCards forecast={forecastFromResult(data)} />
            )}
            {howTo.length > 0 && (
              <div>
                <div className="mb-1 flex items-center justify-between">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                    How to read
                  </p>
                  <CopyAllButton text={howTo.map((l) => `· ${l}`).join('\n')} />
                </div>
                <ul className="space-y-1">
                  {howTo.map((line) => (
                    <li key={line} className="text-[11px] leading-relaxed text-slate-400">
                      · {line}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {rightTab === 'ai' && (
          <div>
            {askContext ? (
              <AskAIPanel
                context={askContext}
                section="chart-analyzer"
                title="Investigate with AI"
                buttonLabel="Investigate with AI"
                defaultQuestion="You are a price action & smart money expert looking at this chart. Should I take a trade now? If yes, LONG or SHORT with %SL, %TP, and %Confidence. If no, explain why to wait."
                showPredictNextMove
              />
            ) : (
              <p className="text-xs text-slate-500">Load a ticker to ask AI about the chart.</p>
            )}
          </div>
        )}
      </div>
    </>
  )
}
