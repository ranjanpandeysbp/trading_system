import { useEffect, useMemo, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
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
import { apiErrorMessage, runProTradeTickerChart } from '../../api/client'
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
import type { AssetClass } from '../command-center/AssetClassTickerPicker'

type Row = Record<string, unknown>
type ChartMode = 'daily' | 'intraday'

type SrLevel = { key?: string; label: string; kind: string; price: number }
type SupportResistance = {
  s1?: number | null
  s2?: number | null
  r1?: number | null
  r2?: number | null
  levels?: SrLevel[]
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
  if (ac === 'commodity') return 'e.g. GC=F'
  return 'e.g. RELIANCE'
}

function PriceChart({
  points,
  supportResistance,
  title,
  volumeSrSummary,
}: {
  points: Row[]
  supportResistance?: SupportResistance | null
  title: string
  volumeSrSummary?: VolumeSrSummary | null
}) {
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

  const hasVolume = useMemo(
    () => points.some((p) => p.volume != null && Number.isFinite(Number(p.volume)) && Number(p.volume) > 0),
    [points],
  )

  const yDomain = useMemo((): [number | string, number | string] => {
    if (!points.length) return ['auto', 'auto']
    const vals = points.map((p) => Number(p.value)).filter((n) => Number.isFinite(n))
    if (!vals.length) return ['auto', 'auto']
    let lo = Math.min(...vals)
    let hi = Math.max(...vals)
    for (const lv of levels) {
      lo = Math.min(lo, lv.price)
      hi = Math.max(hi, lv.price)
    }
    const pad = Math.max((hi - lo) * 0.06, Math.abs(hi) * 0.001, 1e-6)
    return [lo - pad, hi + pad]
  }, [points, levels])

  if (!points.length) {
    return (
      <div className="rounded-xl border border-slate-800/60 bg-slate-950/40 p-6 text-center text-sm text-slate-500">
        No bars in range
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-slate-800/60 bg-slate-950/40 p-3">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm font-medium text-white">{title}</p>
        <span className="text-[10px] text-slate-500">green = support · red = resistance · grey = volume</span>
      </div>
      <div className="h-96 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={points} margin={{ top: 12, right: 16, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="label" tick={{ fill: '#94a3b8', fontSize: 10 }} minTickGap={32} />
            <YAxis
              yAxisId="price"
              domain={yDomain}
              tick={{ fill: '#94a3b8', fontSize: 10 }}
              width={56}
              tickFormatter={(v) => Number(v).toFixed(v >= 100 ? 0 : 2)}
            />
            {hasVolume && (
              <YAxis
                yAxisId="vol"
                orientation="right"
                tick={{ fill: '#64748b', fontSize: 9 }}
                width={44}
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
              formatter={(value: number, name: string) => {
                if (name === 'volume') {
                  return [Number(value).toLocaleString(undefined, { maximumFractionDigits: 0 }), 'Volume']
                }
                return [Number(value).toFixed(3), 'Close']
              }}
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
            {hasVolume && <Bar yAxisId="vol" dataKey="volume" fill="#334155" opacity={0.55} name="volume" />}
            <Line yAxisId="price" type="monotone" dataKey="value" stroke="#38bdf8" strokeWidth={2} dot={false} name="price" />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      {levels.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 border-t border-slate-800/50 pt-2 text-[11px]">
          {levels.map((lv) => (
            <span
              key={`legend-${lv.label}-${lv.price}`}
              className={lv.kind === 'support' ? 'text-emerald-400' : 'text-rose-400'}
            >
              {lv.label} {fmtNum(lv.price, lv.price >= 100 ? 1 : 3)}
            </span>
          ))}
        </div>
      )}
      <VolumeSrSummaryCard data={volumeSrSummary} />
    </div>
  )
}

export function TickerChartPage() {
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [ticker, setTicker] = useState('')
  const [mode, setMode] = useState<ChartMode>('daily')
  const [fromDate, setFromDate] = useState(isoDaysAgo(90))
  const [toDate, setToDate] = useState(isoDaysAgo(0))
  const [sessionDate, setSessionDate] = useState(isoDaysAgo(0))
  const [interval, setInterval] = useState('15m')
  const [error, setError] = useState('')

  const runMut = useMutation({
    mutationFn: () =>
      runProTradeTickerChart({
        ticker: ticker.trim(),
        asset_class: assetClass,
        mode,
        from_date: mode === 'daily' ? fromDate : undefined,
        to_date: mode === 'daily' ? toDate : undefined,
        session_date: mode === 'intraday' ? sessionDate : undefined,
        interval: mode === 'intraday' ? interval : '1d',
      }),
    onSuccess: (data) => {
      setError(data?.error ? String(data.error) : '')
    },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const ready =
    ticker.trim().length >= 1 &&
    (mode === 'daily' ? Boolean(fromDate && toDate) : Boolean(sessionDate && interval))

  // Auto-draw as soon as ticker + date range (or intraday session) are set
  useEffect(() => {
    if (!ready) return
    const handle = window.setTimeout(() => {
      runMut.mutate()
    }, 350)
    return () => window.clearTimeout(handle)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentional: refetch on control changes only
  }, [ready, ticker, assetClass, mode, fromDate, toDate, sessionDate, interval])

  const data = runMut.data as Row | undefined
  const points = (data?.points as Row[] | undefined) ?? []
  const sr = (data?.support_resistance as SupportResistance | null | undefined) ?? null
  const volSr = (data?.volume_sr_summary as VolumeSrSummary | null | undefined) ?? null
  const howTo = (data?.how_to_read as string[] | undefined) ?? []
  const askContext = data ? buildAskContext('Ticker Chart', data) : ''

  return (
    <div>
      <PageHeader
        title="Ticker Chart"
        description="India · US · Crypto · Commodities — pick a ticker and date range (or same-day intraday) and the chart draws with S1/S2 · R1/R2"
      />

      <Card className="mb-4">
        <div className="mb-3 flex flex-wrap gap-2">
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
        </div>

        <div className="mb-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <FormField label="Ticker">
            <TickerAutosuggest
              key={assetClass}
              value={ticker}
              onChange={setTicker}
              assetClass={assetClass}
              placeholder={placeholderFor(assetClass)}
            />
          </FormField>
        </div>

        <div className="mb-4 flex flex-wrap gap-2">
          <Chip selected={mode === 'daily'} onClick={() => setMode('daily')}>
            Daily range
          </Chip>
          <Chip selected={mode === 'intraday'} onClick={() => setMode('intraday')}>
            Same-day intraday
          </Chip>
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
            <FormField label="Session date">
              <input
                type="date"
                className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                value={sessionDate}
                onChange={(e) => setSessionDate(e.target.value)}
              />
            </FormField>
            <FormField label="Bar size">
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

        <p className="mt-3 text-xs text-slate-500">
          Chart loads automatically once a ticker and date range (or intraday session) are set.
        </p>
      </Card>

      {error && (
        <div className="mb-4">
          <Alert type="error">{error}</Alert>
        </div>
      )}

      {runMut.isPending && <Loading message="Drawing chart with support & resistance…" />}

      {data && !runMut.isPending && (
        <Card className="mb-4">
          <StrategyDataSourceBar data={data} assetClass={assetClass} />
          <div className="mb-3 flex flex-wrap items-center gap-2">
            {data.summary != null && <p className="text-sm text-slate-300">{String(data.summary)}</p>}
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
            {data.last != null && (
              <span className="text-xs tabular-nums text-slate-400">Last {fmtNum(data.last, 2)}</span>
            )}
            {data.yf_symbol != null && (
              <span className="text-xs text-slate-500">{String(data.yf_symbol)}</span>
            )}
          </div>
          {data.plain_english != null && (
            <p className="mb-3 text-xs leading-relaxed text-slate-400">{String(data.plain_english)}</p>
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
            supportResistance={sr}
            title={`${String(data.ticker ?? ticker)} · ${mode === 'intraday' ? interval : '1d'}`}
            volumeSrSummary={volSr}
          />
        </Card>
      )}

      {askContext && (
        <AskAIPanel
          context={askContext}
          section="pro-trade/ticker-chart"
          defaultQuestion="Read this ticker chart with S/R — what is the nearest support/resistance and bias?"
          showPredictNextMove
        />
      )}
    </div>
  )
}
