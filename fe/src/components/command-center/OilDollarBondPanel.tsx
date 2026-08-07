import { useMemo, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Crosshair, Droplets } from 'lucide-react'
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
import { StrategyDataSourceBar } from '../ui/StrategyDataSourceBar'

type Row = Record<string, unknown>
type ChartMode = 'daily' | 'intraday'

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

function SeriesChart({
  title,
  subtitle,
  points,
  color,
  unit,
}: {
  title: string
  subtitle?: string
  points: Row[]
  color: string
  unit?: string
}) {
  if (!points.length) {
    return (
      <div className="rounded-xl border border-slate-800/60 bg-slate-950/40 p-4">
        <p className="text-sm font-medium text-white">{title}</p>
        <p className="mt-2 text-xs text-slate-500">No data in range</p>
      </div>
    )
  }
  return (
    <div className="rounded-xl border border-slate-800/60 bg-slate-950/40 p-3">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <p className="text-sm font-medium text-white">{title}</p>
          {subtitle && <p className="text-[11px] text-slate-500">{subtitle}</p>}
        </div>
        {unit && <span className="text-[10px] uppercase tracking-wide text-slate-500">{unit}</span>}
      </div>
      <div className="h-48 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="label" tick={{ fill: '#94a3b8', fontSize: 9 }} minTickGap={28} />
            <YAxis
              domain={['auto', 'auto']}
              tick={{ fill: '#94a3b8', fontSize: 9 }}
              width={48}
              tickFormatter={(v) => Number(v).toFixed(v >= 100 ? 0 : 2)}
            />
            <Tooltip
              contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 11 }}
              labelStyle={{ color: '#e2e8f0' }}
              formatter={(value: number) => [Number(value).toFixed(3), title]}
            />
            <Line type="monotone" dataKey="value" stroke={color} strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
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
        Each series rebased to 0% at its first bar in range — compare direction, not absolute levels.
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
              formatter={(value: number, name: string) => {
                const meta = seriesMeta.find((s) => String(s.id) === name)
                return [`${Number(value).toFixed(2)}%`, String(meta?.short ?? name)]
              }}
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
              Oil · Dollar · Bond · Gold · Silver
            </p>
            <p className="mt-1 text-sm leading-relaxed text-slate-300">
              Macro tape for <strong className="text-white">DXY</strong>, <strong className="text-white">Brent</strong>,{' '}
              <strong className="text-white">US 2Y / 10Y</strong>, <strong className="text-white">Gold</strong> and{' '}
              <strong className="text-white">Silver</strong> — daily range or same-day intraday (Yahoo Finance).
            </p>
            <p className="mt-2 text-xs leading-relaxed text-slate-500">
              Rising DXY often pressures commodities; yields track rate expectations. Overlay chart normalizes % change
              across units.
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
          <div className="mb-4 space-y-2 rounded-lg border border-slate-800 bg-slate-950/50 p-3 text-xs leading-relaxed text-slate-400">
            <p className="font-medium text-slate-200">How to run</p>
            <ol className="list-decimal space-y-1 pl-4">
              <li>Choose <span className="text-slate-300">Daily</span> (date range) or <span className="text-slate-300">Intraday</span> (one session).</li>
              <li>For intraday, pick session date + bar size (1m–1h). Yahoo only keeps a limited window of intraday history.</li>
              <li>Click <span className="text-slate-300">Load charts</span>.</li>
            </ol>
            <p className="mt-2 font-medium text-slate-200">Symbols</p>
            <ul className="list-disc space-y-1 pl-4">
              <li>DXY → <span className="text-slate-300">DX-Y.NYB</span></li>
              <li>Brent → <span className="text-slate-300">BZ=F</span></li>
              <li>US 2Y → <span className="text-slate-300">^UST2Y / 2YY=F / ZT=F</span></li>
              <li>US 10Y → <span className="text-slate-300">^TNX</span></li>
              <li>Gold → <span className="text-slate-300">GC=F</span></li>
              <li>Silver → <span className="text-slate-300">SI=F</span></li>
            </ul>
          </div>
        )}

        <div className="mb-4 flex flex-wrap gap-2">
          <Chip selected={mode === 'daily'} onClick={() => setMode('daily')}>Daily range</Chip>
          <Chip selected={mode === 'intraday'} onClick={() => setMode('intraday')}>Same-day intraday</Chip>
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

      <AnalysisBackgroundJobsAndReports bg={bg} />

      {runMut.isPending && !bg.viewedPayload && (
        <Loading
          message={
            mode === 'intraday'
              ? `Downloading same-day ${interval} bars for DXY, Brent, bonds, Gold & Silver…`
              : 'Downloading DXY, Brent, US 2Y/10Y, Gold & Silver from Yahoo Finance…'
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
                    <ul className="mt-2 space-y-0.5 border-t border-slate-800/60 pt-2">
                      {howTo.map((line) => (
                        <li key={line} className="text-xs text-slate-500">· {line}</li>
                      ))}
                    </ul>
                  )}
                </div>

                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {series.map((s) => {
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
                  {series.map((s) => (
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
                    />
                  ))}
                </div>

                <OverlayChart chart={chart} seriesMeta={series} />
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
                defaultQuestion="Given DXY, Brent, US 2Y/10Y, Gold and Silver over this window, what is the macro risk regime and what would invalidate it?"
                showPredictNextMove
              />
            </>
          )}
        </>
      )}
    </div>
  )
}

const MACRO_NEXT_MOVE_QUESTION = `As an expert institutional macro / rates / commodities desk trader, use ONLY the Oil-Dollar-Bond chart result data below.

Predict the highest-probability NEXT MOVE for the macro complex.

Structure EXACTLY as:

## NEXT MOVE
RISK-ON | RISK-OFF | MIXED | WAIT
(one word on its own line — overall regime for the next session / few days)

## CONFIDENCE
NN%
(integer 0-100)

## THESIS
2-4 sentences tying DXY, Brent, US 2Y/10Y, Gold and Silver together.

## INSTRUMENT LEANS
- DXY: UP | DOWN | FLAT · conf NN% · one-line why
- Brent: UP | DOWN | FLAT · conf NN% · one-line why
- US 2Y: UP | DOWN | FLAT · conf NN% · one-line why
- US 10Y: UP | DOWN | FLAT · conf NN% · one-line why
- Gold: UP | DOWN | FLAT · conf NN% · one-line why
- Silver: UP | DOWN | FLAT · conf NN% · one-line why

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
        Institutional macro desk read of DXY, Brent, US 2Y/10Y, Gold and Silver — overall regime plus per-instrument
        UP / DOWN / FLAT leans with % confidence. Uses Manage → AI Settings.
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
