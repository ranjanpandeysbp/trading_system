import { useMemo, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Crosshair, Droplets, ExternalLink, Newspaper } from 'lucide-react'
import { apiErrorMessage, askAI, runOilDollarBond } from '../../api/client'
import { AskAIPanel, buildAskContext } from '../ai/AskAIPanel'
import {
  AnalysisBackgroundControls,
  AnalysisBackgroundJobsAndReports,
  useAnalysisBackground,
} from '../analysis/AnalysisBackground'
import { Alert, Loading } from '../ui/Feedback'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { FormField, Select } from '../ui/Form'
import { StatCard } from '../ui/StatCard'
import { ChartStreamControls } from '../charts/chartStreaming'
import { ChartExpandControls, ChartExpandFrame, useChartExpand } from '../charts/chartExpand'
import {
  ChartContextMenu,
  ChartZoomControls,
  copyChartImage,
  useChartContextMenu,
  useChartPointerZoom,
  useIndexZoom,
} from '../charts/chartZoom'
import { StrategyDataSourceBar } from '../ui/StrategyDataSourceBar'
import { HowToBox, CopyAllButton } from '../ui/CopyAllButton'
import { VolumeSrSummaryCard, type VolumeSrSummary } from '../ui/VolumeSrSummaryCard'

type Row = Record<string, unknown>
type ChartMode = 'daily' | 'intraday'
type SeriesGroup = 'all' | 'macro' | 'india_etf'

const UPSTOX_MARKET_NEWS = 'https://upstox.com/news/market-news/'

const OIL_DOLLAR_HOW_TO = `Oil · Dollar · Bond — How to

How to run
1. Choose Daily (date range) or Intraday (one session).
2. For intraday, pick session date + bar size (1m–1h). Yahoo only keeps a limited window of intraday history.
3. Filter: Global macro · India sector ETFs · All.
4. Click Load charts.

Global macro
- DXY → DX-Y.NYB · Brent → BZ=F · US 2Y/10Y · Gold/Silver · Nifty 50 · Dow · Nasdaq · BTC/ETH

India sector & breadth ETFs
- BANKBEES · PSUBNKBEES · ITBEES · AUTOBEES · PHARMABEES · HEALTHY
- FMCGIETF · CONSUMBEES · METALIETF · GROWWPOWER · ENERGY · INFRABEES
- MODEFENCE · MOREALTY · GROWWEV
- Nifty 500 · JUNIORBEES · Midcap 150 · Smallcap 250

Note: METALBEES does not exist — Metal uses METALIETF / GROWWMETAL.

Each panel shows S1/S2 support (green), R1/R2 resistance (red), volume bars, and a break-probability summary from volume + S/R proximity.`

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

type SrLevel = { key?: string; label: string; kind: string; price: number }
type SupportResistance = {
  s1?: number | null
  s2?: number | null
  r1?: number | null
  r2?: number | null
  levels?: SrLevel[]
}

function SeriesChart({
  title,
  subtitle,
  points,
  color,
  unit,
  supportResistance,
  volumeSrSummary,
  streamTicker,
}: {
  title: string
  subtitle?: string
  points: Row[]
  color: string
  unit?: string
  supportResistance?: SupportResistance | null
  volumeSrSummary?: VolumeSrSummary | null
  streamTicker?: string | null
}) {
  const [streamOn, setStreamOn] = useState(true)
  const [barCount, setBarCount] = useState(100)
  const expand = useChartExpand()
  const chartRef = useRef<HTMLDivElement>(null)
  const ctxMenu = useChartContextMenu()
  const [copyStatus, setCopyStatus] = useState<string | null>(null)

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

  const windowPoints = useMemo(() => {
    if (barCount > 0 && points.length > barCount) return points.slice(-barCount)
    return points
  }, [points, barCount])

  const {
    zoomRange,
    zoomIn,
    zoomOut,
    resetZoom,
    isZoomed,
  } = useIndexZoom(windowPoints.length)

  useChartPointerZoom(chartRef, zoomIn, zoomOut, ctxMenu.openAt)

  const viewPoints = useMemo(() => {
    if (!zoomRange) return windowPoints
    return windowPoints.slice(zoomRange[0], zoomRange[1] + 1)
  }, [windowPoints, zoomRange])

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

  const hasVolume = useMemo(
    () => viewPoints.some((p) => p.volume != null && Number.isFinite(Number(p.volume)) && Number(p.volume) > 0),
    [viewPoints],
  )

  const yDomain = useMemo((): [number | string, number | string] => {
    if (!viewPoints.length) return ['auto', 'auto']
    const vals = viewPoints.map((p) => Number(p.value)).filter((n) => Number.isFinite(n))
    if (!vals.length) return ['auto', 'auto']
    let lo = Math.min(...vals)
    let hi = Math.max(...vals)
    for (const lv of levels) {
      lo = Math.min(lo, lv.price)
      hi = Math.max(hi, lv.price)
    }
    const pad = Math.max((hi - lo) * 0.06, Math.abs(hi) * 0.001, 1e-6)
    return [lo - pad, hi + pad]
  }, [viewPoints, levels])

  if (!points.length) {
    return (
      <div className="rounded-xl border border-slate-800/60 bg-slate-950/40 p-4">
        <p className="text-sm font-medium text-white">{title}</p>
        <p className="mt-2 text-xs text-slate-500">No data in range</p>
      </div>
    )
  }
  return (
    <ChartExpandFrame fullscreen={expand.fullscreen} onClose={() => expand.setFullscreen(false)} title={title}>
    <div className="rounded-xl border border-slate-800/60 bg-slate-950/40 p-3">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <p className="text-sm font-medium text-white">{title}</p>
          {subtitle && <p className="text-[11px] text-slate-500">{subtitle}</p>}
        </div>
        {unit && <span className="text-[10px] uppercase tracking-wide text-slate-500">{unit}</span>}
      </div>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <ChartStreamControls
          streamOn={streamOn}
          setStreamOn={setStreamOn}
          barCount={barCount}
          setBarCount={setBarCount}
          canStream={Boolean(streamTicker)}
          liveLtp={null}
        />
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
        {copyStatus && (
          <span className="text-[11px] text-emerald-400/90">{copyStatus}</span>
        )}
      </div>
      <div
        ref={chartRef}
        className={`relative w-full ${expand.fullscreen || expand.size !== 'normal' ? expand.heightClass : hasVolume ? 'h-60' : 'h-52'}`}
      >
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
          <ComposedChart data={viewPoints} margin={{ top: 10, right: 12, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="label" tick={{ fill: '#94a3b8', fontSize: 9 }} minTickGap={28} />
            <YAxis
              yAxisId="price"
              domain={yDomain}
              tick={{ fill: '#94a3b8', fontSize: 9 }}
              width={52}
              tickFormatter={(v) => Number(v).toFixed(v >= 100 ? 0 : 2)}
            />
            {hasVolume && (
              <YAxis
                yAxisId="vol"
                orientation="right"
                tick={{ fill: '#64748b', fontSize: 8 }}
                width={40}
                tickFormatter={(v) => {
                  const n = Number(v)
                  if (n >= 1e9) return `${(n / 1e9).toFixed(1)}B`
                  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`
                  if (n >= 1e3) return `${(n / 1e3).toFixed(0)}K`
                  return String(Math.round(n))
                }}
              />
            )}
            <Tooltip
              contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 11 }}
              labelStyle={{ color: '#e2e8f0' }}
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              formatter={((value: number, name: string) => {
                if (name === 'volume') {
                  return [Number(value).toLocaleString(undefined, { maximumFractionDigits: 0 }), 'Volume']
                }
                return [Number(value).toFixed(3), title]
              }) as any}
            />
            {levels.map((lv) => {
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
            {hasVolume && (
              <Bar yAxisId="vol" dataKey="volume" fill="#334155" opacity={0.55} name="volume" />
            )}
            <Line
              yAxisId="price"
              type="monotone"
              dataKey="value"
              stroke={color}
              strokeWidth={2}
              dot={false}
              name="price"
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      {levels.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 border-t border-slate-800/50 pt-2 text-[10px]">
          {levels.map((lv) => (
            <span
              key={`legend-${lv.label}-${lv.price}`}
              className={lv.kind === 'support' ? 'text-emerald-400' : 'text-rose-400'}
            >
              {lv.label} {fmtNum(lv.price, lv.price >= 100 ? 1 : 3)}
            </span>
          ))}
          {hasVolume && <span className="text-slate-600">· grey bars = volume</span>}
          <span className="text-slate-600">· green = support · red = resistance</span>
        </div>
      )}
      <VolumeSrSummaryCard data={volumeSrSummary} />
    </div>
    <ChartContextMenu
      menu={ctxMenu.menu}
      onClose={ctxMenu.close}
      onCopy={handleCopyChart}
      onResetZoom={resetZoom}
      onFullscreen={expand.toggleFullscreen}
      fullscreen={expand.fullscreen}
      onResetChart={handleResetChart}
    />
    </ChartExpandFrame>
  )
}

function OverlayChart({ chart, seriesMeta }: { chart: Row[]; seriesMeta: Row[] }) {
  if (!chart.length) return null
  const keys = seriesMeta.filter((s) => (s.points as Row[] | undefined)?.length && !s.error).map((s) => String(s.id))
  if (!keys.length) return null
  return (
    <div className="rounded-xl border border-slate-800/60 bg-slate-950/40 p-3">
      <p className="mb-1 text-sm font-medium text-white">Normalized % change (overlay)</p>
      <p className="mb-2 text-[11px] text-slate-500">
        Each series rebased to 0% at its first bar — compare direction only (S/R shown on instrument charts above).
      </p>
      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chart} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="label" tick={{ fill: '#94a3b8', fontSize: 9 }} minTickGap={28} />
            <YAxis tick={{ fill: '#94a3b8', fontSize: 9 }} width={40} unit="%" />
            <Tooltip
              contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 11 }}
              labelStyle={{ color: '#e2e8f0' }}
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              formatter={((value: number, name: string) => {
                const meta = seriesMeta.find((s) => String(s.id) === name)
                return [`${Number(value).toFixed(2)}%`, String(meta?.short ?? name)]
              }) as any}
            />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            {seriesMeta.map((s) => {
              const id = String(s.id)
              if (!keys.includes(id)) return null
              return (
                <Line
                  key={id}
                  type="monotone"
                  dataKey={id}
                  name={String(s.short ?? s.label)}
                  stroke={String(s.color ?? '#94a3b8')}
                  strokeWidth={2}
                  dot={false}
                  connectNulls
                />
              )
            })}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

export function OilDollarBondPanel() {
  const [mode, setMode] = useState<ChartMode>('daily')
  const [fromDate, setFromDate] = useState(() => isoDaysAgo(180))
  const [toDate, setToDate] = useState(() => isoDaysAgo(0))
  const [sessionDate, setSessionDate] = useState(() => isoDaysAgo(0))
  const [interval, setInterval] = useState('5m')
  const [groupFilter, setGroupFilter] = useState<SeriesGroup>('all')
  const [showHow, setShowHow] = useState(false)
  const [error, setError] = useState('')

  const bg = useAnalysisBackground('command_center', 'oil_dollar_bond')

  const buildPayload = () =>
    mode === 'intraday'
      ? { mode: 'intraday' as const, session_date: sessionDate, interval, from_date: sessionDate, to_date: sessionDate }
      : { mode: 'daily' as const, from_date: fromDate, to_date: toDate, interval: '1d' }

  const validate = (): string | null => {
    if (mode === 'intraday') {
      if (!sessionDate) return 'Pick a session date for same-day intraday'
      return null
    }
    if (!fromDate || !toDate) return 'From and To dates are required'
    if (fromDate > toDate) return 'From date must be on or before To date'
    return null
  }

  const runMut = useMutation({
    mutationFn: () => {
      const err = validate()
      if (err) throw new Error(err)
      return runOilDollarBond(buildPayload())
    },
    onSuccess: () => {
      setError('')
      bg.setViewedReportId(null)
    },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const data = (bg.viewedPayload ?? runMut.data) as Row | undefined
  const series = useMemo(() => ((data?.series as Row[]) ?? []), [data])
  const filteredSeries = useMemo(() => {
    if (groupFilter === 'all') return series
    return series.filter((s) => String(s.group || 'macro') === groupFilter)
  }, [series, groupFilter])
  const chart = useMemo(() => ((data?.chart as Row[]) ?? []), [data])
  const howTo = useMemo(() => ((data?.how_to_read as string[]) ?? []), [data])
  const askContext = data ? buildAskContext('Oil-Dollar-Bond', data) : ''
  const isIntradayResult = String(data?.mode ?? mode) === 'intraday'

  return (
    <div className="space-y-4">
      <Card>
        <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <p className="flex items-center gap-2 text-sm font-semibold text-white">
              <Droplets size={16} className="text-amber-400" />
              Oil · Dollar · Bond · Indices · India ETFs · Crypto
            </p>
            <p className="mt-1 text-sm leading-relaxed text-slate-300">
              Macro tape for <strong className="text-white">DXY</strong>, <strong className="text-white">Brent</strong>,{' '}
              <strong className="text-white">US 2Y / 10Y</strong>, <strong className="text-white">Gold / Silver</strong>,{' '}
              <strong className="text-white">Nifty / Dow / Nasdaq</strong>, <strong className="text-white">BTC / ETH</strong>
              {' '}plus India sector ETFs (
              <strong className="text-white">BANKBEES</strong>, <strong className="text-white">ITBEES</strong>,{' '}
              Mid/Smallcap, Pharma, Metal, Power, FMCG, …) — daily or same-day intraday.
            </p>
            <p className="mt-2 text-xs leading-relaxed text-slate-500">
              Rising DXY often pressures commodities; yields track rate expectations; India ETFs show sector rotation
              vs Nifty. Overlay chart normalizes % change across units.
            </p>
          </div>
          <button
            type="button"
            className="shrink-0 text-xs text-slate-400 hover:text-white"
            onClick={() => setShowHow((v) => !v)}
          >
            {showHow ? 'Hide guide' : 'How to'}
          </button>
        </div>

        {showHow && (
          <HowToBox copyText={OIL_DOLLAR_HOW_TO}>
            <p className="font-medium text-slate-200">How to run</p>
            <ol className="list-decimal space-y-1 pl-4">
              <li>Choose <span className="text-slate-300">Daily</span> (date range) or <span className="text-slate-300">Intraday</span> (one session).</li>
              <li>For intraday, pick session date + bar size (1m–1h). Yahoo only keeps a limited window of intraday history.</li>
              <li>Filter: <span className="text-slate-300">Global macro</span> · <span className="text-slate-300">India ETFs</span> · All.</li>
              <li>Click <span className="text-slate-300">Load charts</span>.</li>
            </ol>
            <p className="mt-2 font-medium text-slate-200">India sector ETFs</p>
            <ul className="list-disc space-y-1 pl-4">
              <li>BANKBEES · PSUBNKBEES · ITBEES · AUTOBEES · PHARMABEES · HEALTHY</li>
              <li>FMCGIETF · CONSUMBEES · METALIETF · GROWWPOWER · ENERGY · INFRABEES</li>
              <li>MODEFENCE · MOREALTY · GROWWEV · Nifty 500 · Midcap 150 · Smallcap 250</li>
              <li className="text-slate-500">METALBEES does not exist — Metal = METALIETF / GROWWMETAL</li>
            </ul>
          </HowToBox>
        )}

        <div className="mb-4 flex flex-wrap gap-2">
          <Chip selected={mode === 'daily'} onClick={() => setMode('daily')}>Daily range</Chip>
          <Chip selected={mode === 'intraday'} onClick={() => setMode('intraday')}>Same-day intraday</Chip>
        </div>

        <div className="mb-4 flex flex-wrap gap-2">
          <span className="self-center text-[11px] uppercase tracking-wide text-slate-500">Show</span>
          {(
            [
              ['all', 'All'],
              ['macro', 'Global macro'],
              ['india_etf', 'India ETFs'],
            ] as const
          ).map(([id, label]) => (
            <Chip key={id} selected={groupFilter === id} onClick={() => setGroupFilter(id)}>
              {label}
            </Chip>
          ))}
        </div>

        {mode === 'daily' ? (
          <>
            <div className="grid gap-4 sm:grid-cols-2">
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
            <div className="mt-3 flex flex-wrap gap-2">
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
            </div>
          </>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2">
            <FormField label="Session date (same day)">
              <input
                type="date"
                className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                value={sessionDate}
                onChange={(e) => setSessionDate(e.target.value)}
              />
            </FormField>
            <FormField label="Intraday bar size">
              <Select value={interval} onChange={(e) => setInterval(e.target.value)}>
                {INTRADAY_INTERVALS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </Select>
            </FormField>
          </div>
        )}

        <div className="mt-4 flex flex-wrap gap-3">
          <Button onClick={() => runMut.mutate()} disabled={runMut.isPending || bg.runInBackground}>
            {runMut.isPending ? 'Loading…' : 'Load charts'}
          </Button>
          {mode === 'intraday' && (
            <button
              type="button"
              className="rounded-lg border border-slate-700/80 px-2.5 py-1.5 text-xs text-slate-400 hover:border-slate-500 hover:text-slate-200"
              onClick={() => setSessionDate(isoDaysAgo(0))}
            >
              Today
            </button>
          )}
        </div>

        <AnalysisBackgroundControls
          bg={bg}
          placeholder={
            mode === 'intraday'
              ? `Oil-Dollar-Bond · intraday ${sessionDate} · ${interval}`
              : `Oil-Dollar-Bond · ${fromDate} → ${toDate}`
          }
          onStart={() => bg.startBackground(buildPayload(), validate)}
        />

        {(error || runMut.isError) && (
          <div className="mt-3">
            <Alert type="error">{error || apiErrorMessage(runMut.error)}</Alert>
          </div>
        )}
      </Card>

      <Card>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <p className="flex items-center gap-2 text-sm font-semibold text-white">
              <Newspaper size={16} className="text-sky-400" />
              Market news
            </p>
            <p className="mt-1 text-xs leading-relaxed text-slate-400">
              Latest stocks, Nifty, IPO, earnings, commodities and macro headlines — pair with the tape above for
              context on sector ETFs (Bank, IT, Metal, Mid/Smallcap, …).
            </p>
          </div>
          <a
            href={UPSTOX_MARKET_NEWS}
            target="_blank"
            rel="noreferrer"
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-sky-500/30 bg-sky-500/10 px-3 py-2 text-xs font-medium text-sky-200 hover:border-sky-400/50 hover:bg-sky-500/15"
          >
            Upstox Market News
            <ExternalLink size={12} />
          </a>
        </div>
        <p className="mt-2 break-all text-[11px] text-slate-500">{UPSTOX_MARKET_NEWS}</p>
      </Card>

      <AnalysisBackgroundJobsAndReports bg={bg} />

      {runMut.isPending && !bg.viewedPayload && (
        <Loading
          message={
            mode === 'intraday'
              ? `Downloading same-day ${interval} bars for DXY, Brent, bonds, metals, Nifty/Dow/Nasdaq & BTC/ETH…`
              : 'Downloading DXY, Brent, US 2Y/10Y, Gold, Silver, Nifty 50, Dow 30, Nasdaq, Bitcoin & Ethereum…'
          }
        />
      )}

      {data && (!runMut.isPending || bg.viewedPayload) && (
        <>
          <Card className="space-y-4">
            <StrategyDataSourceBar data={data} assetClass="us" />
            {Boolean(data.error) && <Alert type="error">{String(data.error)}</Alert>}

            {!data.error && (
              <>
                <div className="rounded-xl border border-slate-700/50 bg-slate-950/40 px-3 py-3 text-sm text-slate-300">
                  <p className="font-medium text-slate-100">
                    Results in plain English
                    {isIntradayResult && (
                      <span className="ml-2 text-xs font-normal text-amber-300/90">
                        · intraday {String(data.session_date ?? '')} · {String(data.interval ?? '')}
                      </span>
                    )}
                  </p>
                  <p className="mt-2 text-xs leading-relaxed text-slate-400">
                    {String(data.plain_english ?? data.summary ?? '')}
                  </p>
                  {howTo.length > 0 && (
                    <div className="mt-2 border-t border-slate-800/60 pt-2">
                      <div className="mb-1 flex justify-end">
                        <CopyAllButton text={howTo.map((line) => `· ${line}`).join('\n')} />
                      </div>
                      <ul className="space-y-0.5">
                        {howTo.map((line) => (
                          <li key={line} className="text-xs text-slate-500">· {line}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>

                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                  {filteredSeries.map((s) => {
                    const chg = s.change_pct != null ? Number(s.change_pct) : null
                    return (
                      <StatCard
                        key={String(s.id)}
                        label={`${String(s.short)} · ${String(s.symbol ?? '—')}`}
                        value={s.last != null ? fmtNum(s.last, 2) : '—'}
                        trend={chg == null ? undefined : chg >= 0 ? 'up' : 'down'}
                      />
                    )
                  })}
                </div>

                <div className="grid gap-3 lg:grid-cols-2">
                  {filteredSeries.map((s) => (
                    <SeriesChart
                      key={String(s.id)}
                      title={String(s.label)}
                      subtitle={
                        s.error
                          ? String(s.error)
                          : `${String(s.symbol ?? '')} · Δ ${fmtNum(s.change_pct, 2)}% · ${String(s.bars ?? 0)} bars`
                      }
                      points={(s.points as Row[]) ?? []}
                      color={String(s.color ?? '#94a3b8')}
                      unit={String(s.unit ?? '')}
                      supportResistance={(s.support_resistance as SupportResistance | null | undefined) ?? null}
                      volumeSrSummary={(s.volume_sr_summary as VolumeSrSummary | null | undefined) ?? null}
                    />
                  ))}
                </div>

                <OverlayChart chart={chart} seriesMeta={filteredSeries} />
              </>
            )}
          </Card>

          {askContext && (
            <>
              <MacroNextMoveCard context={askContext} />
              <AskAIPanel
                title="AI View"
                section="command-center/oil-dollar-bond"
                context={askContext}
                defaultQuestion="Given DXY, Brent, yields, metals, global indices, crypto, and India sector ETFs (Bank, IT, Mid/Smallcap, Pharma, Metal, Power, FMCG, …) over this window, what is the macro risk regime and which India sectors lead or lag?"
                showPredictNextMove
              />
            </>
          )}
        </>
      )}
    </div>
  )
}

const MACRO_NEXT_MOVE_QUESTION = `As an expert institutional macro / rates / commodities / equities / crypto desk trader, use ONLY the Oil-Dollar-Bond chart result data below.

Predict the highest-probability NEXT MOVE for the macro complex.

Structure EXACTLY as:

## NEXT MOVE
RISK-ON | RISK-OFF | MIXED | WAIT
(one word on its own line — overall regime for the next session / few days)

## CONFIDENCE
NN%
(integer 0-100)

## THESIS
2-4 sentences tying DXY, Brent, US 2Y/10Y, Gold, Silver, Nifty 50, Dow 30, Nasdaq, Bitcoin and Ethereum together.

## INSTRUMENT LEANS
- DXY: UP | DOWN | FLAT · conf NN% · one-line why
- Brent: UP | DOWN | FLAT · conf NN% · one-line why
- US 2Y: UP | DOWN | FLAT · conf NN% · one-line why
- US 10Y: UP | DOWN | FLAT · conf NN% · one-line why
- Gold: UP | DOWN | FLAT · conf NN% · one-line why
- Silver: UP | DOWN | FLAT · conf NN% · one-line why
- Nifty 50: UP | DOWN | FLAT · conf NN% · one-line why
- Dow 30: UP | DOWN | FLAT · conf NN% · one-line why
- Nasdaq: UP | DOWN | FLAT · conf NN% · one-line why
- Bitcoin: UP | DOWN | FLAT · conf NN% · one-line why
- Ethereum: UP | DOWN | FLAT · conf NN% · one-line why

## TRIGGER / ENTRY
What confirming print or level would activate the view.

## INVALIDATION
What kills the thesis.

## KEY RISKS
- 2 to 4 bullets

Be decisive but honest. Prefer WAIT / MIXED with lower confidence when signals conflict.`

function MacroNextMoveCard({ context }: { context: string }) {
  const [report, setReport] = useState<{
    report: string
    verdict?: string | null
    confidence_pct?: number | null
    provider: string
    model: string
  } | null>(null)

  const predictMut = useMutation({
    mutationFn: () =>
      askAI({
        context,
        question: MACRO_NEXT_MOVE_QUESTION,
        section: 'command-center/oil-dollar-bond/next-move',
        mode: 'next_move',
      }),
    onSuccess: (data) => setReport(data),
  })

  return (
    <Card className="mt-2 border-amber-500/20">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Crosshair className="text-amber-400" size={18} />
        <h3 className="font-semibold text-white">AI Predictor — Next Move</h3>
        {report && (
          <span className="text-xs text-slate-500">
            {report.provider} · {report.model}
          </span>
        )}
      </div>
      <p className="mb-3 text-xs leading-relaxed text-slate-500">
        Institutional macro desk read of DXY, Brent, US 2Y/10Y, Gold, Silver, Nifty 50, Dow 30, Nasdaq, Bitcoin and
        Ethereum — overall regime plus per-instrument UP / DOWN / FLAT leans with % confidence. Uses Manage → AI Settings.
      </p>
      <Button onClick={() => predictMut.mutate()} disabled={!context.trim() || predictMut.isPending}>
        <Crosshair size={16} />
        {predictMut.isPending ? 'Predicting next move…' : 'Predict Next Move'}
      </Button>

      {predictMut.isError && (
        <div className="mt-3">
          <Alert type="error">{apiErrorMessage(predictMut.error)}</Alert>
        </div>
      )}
      {predictMut.isPending && <Loading message="Institutional macro next-move prediction…" />}

      {report && !predictMut.isPending && (
        <div className="mt-4 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            {report.verdict && <Badge action={report.verdict} />}
            {report.confidence_pct != null && Number.isFinite(Number(report.confidence_pct)) && (
              <span className="inline-flex rounded-lg bg-amber-500/15 px-2.5 py-0.5 text-xs font-semibold tabular-nums text-amber-300 ring-1 ring-amber-500/30">
                {Math.round(Number(report.confidence_pct))}% confidence
              </span>
            )}
          </div>
          <pre className="max-h-[480px] overflow-auto whitespace-pre-wrap rounded-xl border border-amber-500/20 bg-slate-900/60 p-4 text-sm leading-relaxed text-slate-300">
            {report.report}
          </pre>
        </div>
      )}
    </Card>
  )
}
