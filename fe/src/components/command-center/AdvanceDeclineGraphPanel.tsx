import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  Bar,
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

function AdChart({
  series,
  title,
  xKey = 'label',
}: {
  series: Row[]
  title: string
  xKey?: string
}) {
  if (!series.length) {
    return <p className="text-sm text-slate-500">No points to chart yet.</p>
  }

  return (
    <div className="space-y-2">
      <p className="text-sm font-medium text-slate-200">{title}</p>
      <div className="h-80 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={series} margin={{ top: 8, right: 16, left: 0, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey={xKey} tick={{ fill: '#94a3b8', fontSize: 11 }} minTickGap={28} />
            <YAxis yAxisId="count" tick={{ fill: '#94a3b8', fontSize: 11 }} width={40} />
            <YAxis yAxisId="line" orientation="right" tick={{ fill: '#94a3b8', fontSize: 11 }} width={44} />
            <Tooltip
              contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
              labelStyle={{ color: '#e2e8f0' }}
            />
            <Legend />
            <Bar yAxisId="count" dataKey="advances" name="Advances" fill="#34d399" fillOpacity={0.75} />
            <Bar yAxisId="count" dataKey="declines" name="Declines" fill="#f87171" fillOpacity={0.75} />
            <Line
              yAxisId="line"
              type="monotone"
              dataKey="ad_line"
              name="A/D line"
              stroke="#a78bfa"
              strokeWidth={2}
              dot={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <p className="text-[11px] text-slate-500">
        Bars = advances vs declines · Violet line = cumulative (advances − declines) over the window
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
          session</strong> — each bar until the optional as-of time.
        </p>
        <p className="mb-3 text-xs leading-relaxed text-slate-500">
          In plain English: this is a <strong className="text-slate-400">crowd count</strong> of how many stocks in the
          index went up vs down — not a buy/sell tip by itself. More green than red = healthier rally; more red than
          green = broader selling. After you plot, the results box explains the latest day in everyday language.
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
              <FormField label="Session date (intraday)">
                <Input type="date" value={sessionDate} onChange={(e) => setSessionDate(e.target.value)} />
              </FormField>
              <FormField label="As of time (optional)">
                <Input
                  type="time"
                  value={asOfTime}
                  onChange={(e) => setAsOfTime(e.target.value)}
                  placeholder="HH:MM"
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
                <StatCard label="Scanned (daily)" value={fmtNum(data.scanned_daily)} />
                <StatCard
                  label="Latest advances"
                  value={latest ? fmtNum(latest.advances) : '—'}
                />
                <StatCard
                  label="Latest declines"
                  value={latest ? fmtNum(latest.declines) : '—'}
                />
              </div>

              <AdChart
                series={daily}
                title={`Daily Advance / Decline — ${String(data.index_name)} (${fromDate} → ${toDate})`}
                xKey="date"
              />

              {isIntraday && (
                <AdChart
                  series={intraday}
                  title={`Intraday ${timeframe} — ${String(data.session_date ?? sessionDate)}${data.as_of_time ? ` until ${String(data.as_of_time)}` : ''}`}
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
