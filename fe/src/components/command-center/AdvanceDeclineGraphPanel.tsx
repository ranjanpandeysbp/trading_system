import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  Bar,
  Cell,
} from 'recharts'
import {
  apiErrorMessage,
  fetchAdvanceDeclineGraphIndices,
  runAdvanceDeclineGraph,
} from '../../api/client'
import { AskAIPanel, buildAskContext } from '../ai/AskAIPanel'
import { Alert, Loading } from '../ui/Feedback'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { FormField, Input, Select } from '../ui/Form'
import { StatCard } from '../ui/StatCard'

type Row = Record<string, unknown>

const INTRADAY_TFS = ['5m', '10m', '15m', '30m', '1h'] as const

function isoDaysAgo(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() - days)
  return d.toISOString().slice(0, 10)
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

function fmtNum(v: unknown, digits = 0): string {
  if (v == null || v === '') return '—'
  const n = Number(v)
  return Number.isFinite(n) ? n.toLocaleString(undefined, { maximumFractionDigits: digits }) : '—'
}

function withChartRatio(series: Row[]): Row[] {
  return series.map((row) => {
    const ratio = row.ad_ratio != null ? Number(row.ad_ratio) : null
    const volRatio = row.vol_ratio != null ? Number(row.vol_ratio) : null
    return {
      ...row,
      ad_ratio: ratio != null && Number.isFinite(ratio) ? ratio : null,
      vol_ratio: volRatio != null && Number.isFinite(volRatio) ? volRatio : null,
    }
  })
}

function AdRatioChart({
  series,
  title,
  xKey = 'label',
}: {
  series: Row[]
  title: string
  xKey?: string
}) {
  const chartData = useMemo(() => withChartRatio(series), [series])
  if (!chartData.length) {
    return <p className="text-sm text-slate-500">No points to chart yet.</p>
  }

  const ratios = chartData
    .flatMap((r) => [Number(r.ad_ratio), Number(r.vol_ratio)])
    .filter((n) => Number.isFinite(n))
  const yMax = Math.min(10, Math.max(2, ...(ratios.length ? ratios : [2]), 1.2))
  const latest = chartData[chartData.length - 1]
  const latestRatio = latest?.ad_ratio != null ? Number(latest.ad_ratio) : null
  const latestVol = latest?.vol_ratio != null ? Number(latest.vol_ratio) : null

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm font-medium text-slate-200">{title}</p>
        <div className="flex flex-wrap gap-3 text-xs text-slate-400">
          {latestRatio != null && (
            <span>
              A/D:{' '}
              <strong className={latestRatio >= 1 ? 'text-emerald-300' : 'text-rose-300'}>
                {fmtNum(latestRatio, 2)}
              </strong>
            </span>
          )}
          {latestVol != null && (
            <span>
              Vol:{' '}
              <strong className={latestVol >= 1 ? 'text-amber-300' : 'text-slate-400'}>
                {fmtNum(latestVol, 2)}
              </strong>
            </span>
          )}
        </div>
      </div>
      <div className="h-80 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chartData} margin={{ top: 8, right: 16, left: 4, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey={xKey} tick={{ fill: '#94a3b8', fontSize: 11 }} minTickGap={28} />
            <YAxis
              yAxisId="ratio"
              domain={[0, yMax]}
              tick={{ fill: '#94a3b8', fontSize: 11 }}
              width={44}
              label={{ value: 'Ratio', angle: -90, position: 'insideLeft', fill: '#64748b', fontSize: 11 }}
            />
            <Tooltip
              content={({ active, payload, label }) => {
                if (!active || !payload?.length) return null
                const row = payload[0]?.payload as Row | undefined
                if (!row) return null
                return (
                  <div className="rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-xs text-slate-200">
                    <p className="mb-1 font-medium text-white">{String(label)}</p>
                    <p>
                      A/D ratio:{' '}
                      <strong className={Number(row.ad_ratio) >= 1 ? 'text-emerald-300' : 'text-rose-300'}>
                        {fmtNum(row.ad_ratio, 2)}
                      </strong>
                      <span className="text-slate-500">
                        {' '}({fmtNum(row.advances)}↑ / {fmtNum(row.declines)}↓)
                      </span>
                    </p>
                    <p>
                      Vol ratio:{' '}
                      <strong className={Number(row.vol_ratio) >= 1 ? 'text-amber-300' : 'text-slate-300'}>
                        {fmtNum(row.vol_ratio, 2)}
                      </strong>
                      <span className="text-slate-500">
                        {' '}({fmtNum(row.volume_up)} vol↑ / {fmtNum(row.volume_down)} vol↓)
                      </span>
                    </p>
                  </div>
                )
              }}
            />
            <Legend />
            <ReferenceLine
              yAxisId="ratio"
              y={1}
              stroke="#94a3b8"
              strokeDasharray="4 4"
              label={{ value: '1.0 even', fill: '#94a3b8', fontSize: 10, position: 'insideTopRight' }}
            />
            <Bar yAxisId="ratio" dataKey="ad_ratio" name="A/D ratio" fill="#34d399" radius={[3, 3, 0, 0]}>
              {chartData.map((row, i) => {
                const r = Number(row.ad_ratio)
                const bullish = Number.isFinite(r) && r >= 1
                return (
                  <Cell
                    key={`${String(row[xKey])}-${i}`}
                    fill={bullish ? '#34d399' : '#f87171'}
                    fillOpacity={0.55}
                  />
                )
              })}
            </Bar>
            <Line
              yAxisId="ratio"
              type="monotone"
              dataKey="ad_ratio"
              name="A/D trend"
              stroke="#a78bfa"
              strokeWidth={2}
              dot={{ r: 2, fill: '#c4b5fd' }}
              connectNulls
              legendType="line"
            />
            <Line
              yAxisId="ratio"
              type="monotone"
              dataKey="vol_ratio"
              name="Volume ratio"
              stroke="#fbbf24"
              strokeWidth={2.25}
              dot={{ r: 2, fill: '#fcd34d' }}
              connectNulls
              legendType="line"
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <p className="text-[11px] text-slate-500">
        Green/red bars + violet = A/D ratio (price breadth). Amber line = volume ratio (activity breadth).
        Both above 1 = healthier move; A/D up + volume down = hollow rally; A/D down + volume up = aggressive selling.
      </p>
    </div>
  )
}

export function AdvanceDeclineGraphPanel() {
  const [indexName, setIndexName] = useState('NIFTY 50')
  const [fromDate, setFromDate] = useState(isoDaysAgo(30))
  const [toDate, setToDate] = useState(todayIso())
  const [timeframe, setTimeframe] = useState('1d')
  const [sessionDate, setSessionDate] = useState(todayIso())
  const [asOfTime, setAsOfTime] = useState('')

  const indicesQuery = useQuery({
    queryKey: ['advance-decline-graph-indices'],
    queryFn: fetchAdvanceDeclineGraphIndices,
    staleTime: 60_000,
  })

  const runMut = useMutation({
    mutationFn: () =>
      runAdvanceDeclineGraph({
        index_name: indexName,
        from_date: fromDate,
        to_date: toDate,
        timeframe,
        session_date: timeframe !== '1d' ? sessionDate || toDate : undefined,
        as_of_time: timeframe !== '1d' && asOfTime.trim() ? asOfTime.trim() : undefined,
      }),
  })

  const data = runMut.data as Row | undefined
  const daily = useMemo(() => ((data?.daily as Row[]) ?? []), [data])
  const intraday = useMemo(() => ((data?.intraday as Row[]) ?? []), [data])
  const latest = (data?.latest as Row | undefined) ?? null
  const isIntraday = timeframe !== '1d'
  const askContext = data ? buildAskContext('Advance Decline Graph', data) : ''

  return (
    <div className="space-y-4">
      <Card>
        <p className="mb-3 text-sm leading-relaxed text-slate-300">
          Pick an NSE index and date range to plot <strong className="text-white">advances vs declines per day</strong>{' '}
          across constituents. Choose an intraday timeframe to also see breadth <strong className="text-white">within a
          session</strong> — each bar until the optional as-of time <strong className="text-white">(all times IST)</strong>.
        </p>
        <p className="mb-3 text-xs leading-relaxed text-slate-500">
          Charts show <strong className="text-slate-400">A/D ratio</strong> (price breadth) and{' '}
          <strong className="text-slate-400">volume ratio</strong> (how many stocks got busier vs quieter).
          Both above 1 = healthier move. After you plot, the results box explains both in plain English.
        </p>

        <div className="grid max-w-4xl gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <FormField label="Index">
            <Select value={indexName} onChange={(e) => setIndexName(e.target.value)}>
              {(indicesQuery.data?.index_names ?? [indexName]).map((name) => (
                <option key={name} value={name}>{name}</option>
              ))}
            </Select>
          </FormField>
          <FormField label="From date">
            <Input type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)} />
          </FormField>
          <FormField label="To date">
            <Input type="date" value={toDate} onChange={(e) => setToDate(e.target.value)} />
          </FormField>
          <FormField label="Timeframe">
            <Select
              value={timeframe}
              onChange={(e) => {
                const v = e.target.value
                setTimeframe(v)
                if (v !== '1d' && !sessionDate) setSessionDate(toDate)
              }}
            >
              <option value="1d">Daily (per session)</option>
              {INTRADAY_TFS.map((tf) => (
                <option key={tf} value={tf}>{tf} intraday</option>
              ))}
            </Select>
          </FormField>
          {isIntraday && (
            <>
              <FormField label="Session date (intraday, IST)">
                <Input type="date" value={sessionDate} onChange={(e) => setSessionDate(e.target.value)} />
              </FormField>
              <FormField label="As of time IST (optional)">
                <Input
                  type="time"
                  value={asOfTime}
                  onChange={(e) => setAsOfTime(e.target.value)}
                  placeholder="HH:MM IST"
                />
              </FormField>
            </>
          )}
        </div>

        <div className="mt-4">
          <Button
            onClick={() => runMut.mutate()}
            disabled={runMut.isPending || !fromDate || !toDate || !indexName}
          >
            {runMut.isPending ? 'Building A/D graph…' : 'Plot Advance / Decline'}
          </Button>
        </div>

        {runMut.isError && (
          <div className="mt-3">
            <Alert type="error">{apiErrorMessage(runMut.error)}</Alert>
          </div>
        )}
      </Card>

      {runMut.isPending && <Loading message="Fetching constituent candles and computing breadth…" />}

      {data && !runMut.isPending && (
        <>
          {Boolean(data.error) && <Alert type="error">{String(data.error)}</Alert>}
          {Boolean(data.warning) && (
            <p className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-200">
              {String(data.warning)}
            </p>
          )}

          {!data.error && (
            <Card className="space-y-4">
              {(() => {
                const outcome = (data.outcome_layman as Row | undefined) ?? null
                const howTo = (outcome?.how_to_read as string[] | undefined) ?? []
                return (
                  <div className="rounded-xl border border-slate-700/50 bg-slate-950/40 px-3 py-3 text-sm leading-relaxed text-slate-300">
                    <p className="font-medium text-slate-100">Results in plain English</p>
                    {outcome?.headline != null && (
                      <p className="mt-2 text-base font-semibold text-white">{String(outcome.headline)}</p>
                    )}
                    <p className="mt-2 text-xs text-slate-400">
                      {String(outcome?.summary ?? data.plain_english ?? '')}
                    </p>
                    {outcome?.combo_line != null && (
                      <p className="mt-2 text-xs leading-relaxed text-amber-200/90">
                        <span className="font-medium text-amber-200">Price + volume: </span>
                        {String(outcome.combo_line)}
                      </p>
                    )}
                    {outcome?.what_it_means != null && (
                      <p className="mt-2 text-xs leading-relaxed text-violet-200/90">
                        <span className="font-medium text-violet-200">What it means: </span>
                        {String(outcome.what_it_means)}
                      </p>
                    )}
                    {howTo.length > 0 && (
                      <ul className="mt-2 space-y-0.5 border-t border-slate-800/60 pt-2">
                        {howTo.map((line) => (
                          <li key={line} className="text-xs text-slate-500">· {line}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                )
              })()}

              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <StatCard label="Universe" value={fmtNum(data.universe_size)} />
                <StatCard
                  label="Latest A/D ratio"
                  value={latest?.ad_ratio != null ? fmtNum(latest.ad_ratio, 2) : '—'}
                />
                <StatCard
                  label="Latest vol ratio"
                  value={latest?.vol_ratio != null ? fmtNum(latest.vol_ratio, 2) : '—'}
                />
                <StatCard
                  label="Adv / Dec · Vol↑ / Vol↓"
                  value={
                    latest
                      ? `${fmtNum(latest.advances)}/${fmtNum(latest.declines)} · ${fmtNum(latest.volume_up)}/${fmtNum(latest.volume_down)}`
                      : '—'
                  }
                />
              </div>

              <AdRatioChart
                series={daily}
                title={`A/D + Volume ratio — ${String(data.index_name)} (${fromDate} → ${toDate})`}
                xKey="date"
              />

              {isIntraday && (
                <AdRatioChart
                  series={intraday}
                  title={`Intraday A/D + Volume (${timeframe}) — ${String(data.session_date ?? sessionDate)} IST${data.as_of_time ? ` until ${String(data.as_of_time)} IST` : ''}`}
                  xKey="label"
                />
              )}

              {isIntraday && !intraday.length && (
                <p className="text-sm text-amber-400/90">
                  No intraday bars for that session/timeframe yet — try another session date or a coarser TF.
                </p>
              )}
            </Card>
          )}

          {askContext && <AskAIPanel context={askContext} section="command-center/advance-decline-graph" />}
        </>
      )}
    </div>
  )
}
