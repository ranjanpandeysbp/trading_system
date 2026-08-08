import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { FolderOpen, Save, Trash2, X } from 'lucide-react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  apiErrorMessage,
  deleteIndiaFiiDiiHoldingsReport,
  fetchIndiaFiiDiiHoldingsJob,
  fetchIndiaFiiDiiHoldingsJobs,
  fetchIndiaFiiDiiHoldingsReport,
  fetchIndiaFiiDiiHoldingsReports,
  runIndiaFiiDiiHoldings,
  saveIndiaFiiDiiHoldingsReport,
  startIndiaFiiDiiHoldingsJob,
} from '../../api/client'
import {
  AssetClassTickerPicker,
  type TickerPickerValue,
} from './AssetClassTickerPicker'
import { AddToWatchlistButton } from '../watchlist/AddToWatchlistButton'
import { AskAIPanel } from '../ai/AskAIPanel'
import { Alert, Loading } from '../ui/Feedback'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { FormField, Input } from '../ui/Form'
import { DataTable, Td, Th } from '../ui/Table'
import { HowToBox } from '../ui/CopyAllButton'

const FII_DII_HOW_TO = `India FII-DII Holdings — How to read

Trade bias from ownership:
- YES — FII/DII accumulating + supportive fundamentals → long bias
- NO — institutions reducing / rich valuation → avoid or short bias
- WAIT — mixed ownership or valuation not aligned

Daily cash-market FII/DII flows (net ₹ Cr) live under Market Pulse → News Scanner, not this tab.`

type Row = Record<string, unknown>

interface FiiDiiSavedReportSummary {
  id: number
  name: string
  tickers: string[]
  from_date: string | null
  to_date: string | null
  created_at: string
  summary?: {
    ticker_count?: number
    yes_count?: number
    no_count?: number
    tickers?: string[]
  }
}

interface FiiDiiBgJobStatus {
  job_id: string
  status: string
  progress?: number
  progress_note?: string
  name?: string | null
  report_id?: number | null
  error?: string | null
  result?: Row
  meta?: {
    tickers?: string[]
    from_date?: string
    to_date?: string
  }
  created_at?: number
}

function isoDaysAgo(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() - days)
  return d.toISOString().slice(0, 10)
}

function formatWhen(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

function fmt(v: unknown, digits = 2): string {
  if (v == null || v === '') return '—'
  const n = Number(v)
  return Number.isFinite(n) ? n.toFixed(digits) : String(v)
}

function trendClass(t: unknown): string {
  const s = String(t ?? '').toUpperCase()
  if (s === 'INCREASING' || s === 'YES' || s === 'GOOD') return 'text-emerald-400'
  if (s === 'DECREASING' || s === 'NO' || s === 'BAD') return 'text-rose-400'
  if (s === 'WAIT' || s === 'MIXED' || s === 'STABLE') return 'text-amber-400'
  return 'text-slate-300'
}

function timingBadge(v: unknown) {
  const s = String(v ?? '—').toUpperCase()
  if (s === 'YES') {
    return <span className="rounded-md bg-emerald-500/15 px-2 py-0.5 text-xs font-semibold text-emerald-300">YES · LONG bias</span>
  }
  if (s === 'NO') {
    return <span className="rounded-md bg-rose-500/15 px-2 py-0.5 text-xs font-semibold text-rose-300">NO · avoid / SHORT bias</span>
  }
  return <span className="rounded-md bg-amber-500/15 px-2 py-0.5 text-xs font-semibold text-amber-300">WAIT</span>
}

const CAT_COLORS: Record<string, string> = {
  Promoters: '#a78bfa',
  FIIs: '#10b981',
  DIIs: '#06b6d4',
  Public: '#f59e0b',
}

function OwnershipChart({ rows, ticker }: { rows: Row[]; ticker: string }) {
  const { data, cats } = useMemo(() => {
    const sub = rows.filter((r) => String(r.ticker) === ticker)
    const byDate = new Map<string, Record<string, string | number>>()
    const catSet = new Set<string>()
    for (const r of sub) {
      const d = String(r.date ?? '').slice(0, 10)
      const cat = String(r.category ?? '')
      if (!d || !cat || r.holding_pct == null) continue
      catSet.add(cat)
      const row = byDate.get(d) ?? { date: d }
      row[cat] = Number(r.holding_pct)
      byDate.set(d, row)
    }
    return {
      data: [...byDate.values()].sort((a, b) => String(a.date).localeCompare(String(b.date))),
      cats: [...catSet],
    }
  }, [rows, ticker])

  if (!data.length) return <p className="text-xs text-slate-500">No ownership series for {ticker}.</p>

  return (
    <div className="h-64 w-full rounded-xl border border-slate-800/80 bg-slate-950/40 p-3">
      <p className="mb-1 text-xs font-medium text-slate-300">{ticker} · ownership %</p>
      <ResponsiveContainer width="100%" height="90%">
        <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis dataKey="date" tick={{ fill: '#94a3b8', fontSize: 11 }} minTickGap={24} />
          <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} width={40} />
          <Tooltip
            contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
            formatter={(v) => [`${Number(v).toFixed(2)}%`, '']}
          />
          {cats.map((c) => (
            <Line
              key={c}
              type="monotone"
              dataKey={c}
              stroke={CAT_COLORS[c] ?? '#94a3b8'}
              strokeWidth={2}
              dot={false}
              connectNulls
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
      <ul className="mt-1 flex flex-wrap gap-3 text-[11px] text-slate-400">
        {cats.map((c) => (
          <li key={c} className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full" style={{ background: CAT_COLORS[c] ?? '#94a3b8' }} />
            {c}
          </li>
        ))}
      </ul>
    </div>
  )
}

/**
 * Command Center — India FII-DII Holding (screener.in ownership + invest timing).
 */
export function IndiaFiiDiiHoldingsPanel() {
  const queryClient = useQueryClient()
  const [picker, setPicker] = useState<TickerPickerValue>({ tickers: [], durations: ['1d'] })
  const [fromDate, setFromDate] = useState(isoDaysAgo(400))
  const [toDate, setToDate] = useState(isoDaysAgo(0))
  const [error, setError] = useState('')
  const [data, setData] = useState<Row | null>(null)
  const [selected, setSelected] = useState('')
  const [showHow, setShowHow] = useState(false)

  const [runInBackground, setRunInBackground] = useState(false)
  const [bgReportName, setBgReportName] = useState('')
  const [bgJobIds, setBgJobIds] = useState<string[]>([])
  const [bgError, setBgError] = useState('')
  const [bgMsg, setBgMsg] = useState('')
  const [saveName, setSaveName] = useState('')
  const [showSaveForm, setShowSaveForm] = useState(false)
  const [saveMsg, setSaveMsg] = useState('')
  const [viewedReportId, setViewedReportId] = useState<number | null>(null)
  const [summarySearch, setSummarySearch] = useState('')
  const handledDoneRef = useRef<Set<string>>(new Set())

  const reportsQuery = useQuery({
    queryKey: ['fii-dii-holdings-reports'],
    queryFn: fetchIndiaFiiDiiHoldingsReports,
  })
  const reports = ((reportsQuery.data as { reports?: FiiDiiSavedReportSummary[] } | undefined)?.reports) ?? []

  const runningJobsQuery = useQuery({
    queryKey: ['fii-dii-holdings-jobs-running'],
    queryFn: () => fetchIndiaFiiDiiHoldingsJobs('running'),
    refetchInterval: 2000,
  })

  const recentJobsQuery = useQuery({
    queryKey: ['fii-dii-holdings-jobs-recent'],
    queryFn: () => fetchIndiaFiiDiiHoldingsJobs('all'),
  })
  const recentJobs = ((recentJobsQuery.data as { jobs?: FiiDiiBgJobStatus[] } | undefined)?.jobs) ?? []
  const recentFinished = recentJobs.filter((j) => j.status !== 'running').slice(0, 8)

  useEffect(() => {
    const serverJobs = ((runningJobsQuery.data as { jobs?: FiiDiiBgJobStatus[] } | undefined)?.jobs) ?? []
    const ids = serverJobs.map((j) => j.job_id)
    if (!ids.length) return
    setBgJobIds((prev) => Array.from(new Set([...ids, ...prev])))
  }, [runningJobsQuery.data])

  const jobQueries = useQueries({
    queries: bgJobIds.map((id) => ({
      queryKey: ['fii-dii-holdings-job', id],
      queryFn: () => fetchIndiaFiiDiiHoldingsJob(id) as Promise<FiiDiiBgJobStatus>,
      refetchInterval: (q: { state: { data?: FiiDiiBgJobStatus } }) =>
        q.state.data?.status === 'running' ? 1500 : false,
      refetchIntervalInBackground: true,
      retry: false,
    })),
  })

  const jobById = useMemo(() => {
    const map = new Map<string, FiiDiiBgJobStatus>()
    jobQueries.forEach((q, i) => {
      const id = bgJobIds[i]
      if (id && q.data) map.set(id, q.data as FiiDiiBgJobStatus)
    })
    return map
  }, [jobQueries, bgJobIds])

  useEffect(() => {
    let changed = false
    const stillRunning: string[] = []
    for (const id of bgJobIds) {
      const job = jobById.get(id)
      if (!job || job.status === 'running') {
        stillRunning.push(id)
        continue
      }
      if (!handledDoneRef.current.has(id)) {
        handledDoneRef.current.add(id)
        changed = true
        if (job.status === 'done' && job.report_id) {
          setViewedReportId(job.report_id)
          setBgMsg(`Background report saved${job.name ? `: ${job.name}` : ''}.`)
        } else if (job.status === 'done') {
          setBgMsg(job.name ? `Background run "${job.name}" finished.` : 'Background run finished.')
        } else if (job.status === 'error') {
          setBgError(job.error || `Background job failed: ${job.name || id}`)
        }
      }
    }
    if (stillRunning.length !== bgJobIds.length) {
      setBgJobIds(stillRunning)
    }
    if (changed) {
      queryClient.invalidateQueries({ queryKey: ['fii-dii-holdings-reports'] })
      queryClient.invalidateQueries({ queryKey: ['fii-dii-holdings-jobs-running'] })
      queryClient.invalidateQueries({ queryKey: ['fii-dii-holdings-jobs-recent'] })
    }
  }, [bgJobIds, jobById, queryClient])

  const ongoingBg = bgJobIds
    .map((id) => jobById.get(id))
    .filter((j): j is FiiDiiBgJobStatus => !!j && j.status === 'running')
  const serverRunning = ((runningJobsQuery.data as { jobs?: FiiDiiBgJobStatus[] } | undefined)?.jobs) ?? []
  const ongoingMap = new Map<string, FiiDiiBgJobStatus>()
  for (const j of [...serverRunning, ...ongoingBg]) {
    if (j.status === 'running') ongoingMap.set(j.job_id, j)
  }
  const ongoingList = Array.from(ongoingMap.values()).sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0))

  const reportDetailQuery = useQuery({
    queryKey: ['fii-dii-holdings-report', viewedReportId],
    queryFn: () => fetchIndiaFiiDiiHoldingsReport(viewedReportId as number),
    enabled: viewedReportId != null,
  })

  const startBgMutation = useMutation({
    mutationFn: startIndiaFiiDiiHoldingsJob,
    onSuccess: (res) => {
      const id = res.job_id as string
      setBgError('')
      setBgMsg(`Background analysis started${res.name ? `: ${res.name}` : ''}.`)
      setBgReportName('')
      setBgJobIds((prev) => Array.from(new Set([id, ...prev])))
      queryClient.invalidateQueries({ queryKey: ['fii-dii-holdings-jobs-running'] })
    },
    onError: (e) => setBgError(apiErrorMessage(e)),
  })

  const saveReportMutation = useMutation({
    mutationFn: saveIndiaFiiDiiHoldingsReport,
    onSuccess: () => {
      setSaveMsg('Report saved.')
      setShowSaveForm(false)
      setSaveName('')
      queryClient.invalidateQueries({ queryKey: ['fii-dii-holdings-reports'] })
    },
    onError: (e) => setBgError(apiErrorMessage(e)),
  })

  const deleteReportMutation = useMutation({
    mutationFn: deleteIndiaFiiDiiHoldingsReport,
    onSuccess: (_data, reportId) => {
      if (viewedReportId === reportId) setViewedReportId(null)
      queryClient.invalidateQueries({ queryKey: ['fii-dii-holdings-reports'] })
    },
  })

  const scanMut = useMutation({
    mutationFn: () =>
      runIndiaFiiDiiHoldings({
        tickers: picker.tickers,
        from_date: fromDate,
        to_date: toDate,
      }),
    onSuccess: (res) => {
      setError('')
      setViewedReportId(null)
      setData(res as Row)
      const ok = ((res as Row).ok as Row[]) ?? []
      setSelected(String(ok[0]?.ticker ?? ''))
    },
    onError: (e) => {
      setError(apiErrorMessage(e))
      setData(null)
    },
  })

  const startBackgroundRun = () => {
    if (!picker.tickers.length) {
      setBgError('Select at least one ticker')
      return
    }
    if (!bgReportName.trim()) {
      setBgError('Enter a report name for the background run')
      return
    }
    setBgError('')
    setBgMsg('')
    startBgMutation.mutate({
      tickers: picker.tickers,
      from_date: fromDate,
      to_date: toDate,
      run_in_background: true,
      report_name: bgReportName.trim(),
    })
  }

  const viewedReport = reportDetailQuery.data as { name?: string; payload?: Row; created_at?: string; error?: string } | undefined
  const effectiveData: Row | null = viewedReportId != null ? (viewedReport?.payload ?? null) : data

  const summary = useMemo(() => {
    const s = effectiveData?.summary
    if (Array.isArray(s)) return s as Row[]
    return []
  }, [effectiveData])

  const filteredSummary = useMemo(() => {
    const q = summarySearch.trim().toLowerCase()
    if (!q) return summary
    return summary.filter((r) => String(r.Ticker ?? '').toLowerCase().includes(q))
  }, [summary, summarySearch])

  const ok = ((effectiveData?.ok as Row[]) ?? [])
  const chartAll = ((effectiveData?.chart_all as Row[]) ?? [])
  const detail = ok.find((r) => String(r.ticker) === selected) ?? ok[0]
  const categories = (detail?.categories as Record<string, Row>) ?? {}

  return (
    <div className="space-y-4">
      <Card>
        <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
          <div>
            <h3 className="font-medium text-white">India FII-DII Holding</h3>
            <p className="mt-0.5 text-xs text-slate-500">
              Promoters / FII / DII / Public stake trend · revenue &amp; profit · P/E vs ROCE · invest timing (YES / WAIT / NO).
              India NSE only · data from screener.in.
            </p>
          </div>
          <button type="button" className="text-xs text-slate-400 hover:text-white" onClick={() => setShowHow((v) => !v)}>
            {showHow ? 'Hide guide' : 'How to read'}
          </button>
        </div>
        {showHow && (
          <HowToBox copyText={FII_DII_HOW_TO}>
            <p className="mb-2 text-slate-300">Trade bias from ownership:</p>
            <ul className="list-disc space-y-1 pl-4">
              <li><span className="text-emerald-400">YES</span> — FII/DII accumulating + supportive fundamentals → long bias</li>
              <li><span className="text-rose-400">NO</span> — institutions reducing / rich valuation → avoid or short bias</li>
              <li><span className="text-amber-400">WAIT</span> — mixed ownership or valuation not aligned</li>
            </ul>
            <p className="mt-2">Daily cash-market FII/DII flows (net ₹ Cr) live under Market Pulse → News Scanner, not this tab.</p>
          </HowToBox>
        )}

        <AssetClassTickerPicker
          assetClass="india"
          onChange={setPicker}
          showDurations={false}
        />

        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <FormField label="From date">
            <input
              type="date"
              className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200"
              value={fromDate}
              onChange={(e) => setFromDate(e.target.value)}
            />
          </FormField>
          <FormField label="To date">
            <input
              type="date"
              className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200"
              value={toDate}
              onChange={(e) => setToDate(e.target.value)}
            />
          </FormField>
          <div className="flex items-end">
            <Button
              className="w-full"
              disabled={scanMut.isPending || runInBackground || !picker.tickers.length || !fromDate || !toDate}
              onClick={() => scanMut.mutate()}
            >
              {scanMut.isPending ? 'Analyzing…' : 'Analyze FII-DII holdings'}
            </Button>
          </div>
        </div>

        {error && <div className="mt-3"><Alert type="error">{error}</Alert></div>}
        {scanMut.isPending && <div className="mt-4"><Loading message="Fetching screener.in shareholding…" /></div>}

        <div className="mt-4 space-y-3 rounded-xl border border-slate-800/60 bg-slate-900/30 p-3">
          <label className="flex cursor-pointer items-start gap-3 text-sm text-slate-300">
            <input
              type="checkbox"
              className="mt-1 h-4 w-4 rounded border-slate-600 bg-slate-800 text-teal-500"
              checked={runInBackground}
              onChange={(e) => setRunInBackground(e.target.checked)}
            />
            <span>
              <span className="font-medium text-slate-100">Run in background</span>
              <span className="mt-0.5 block text-xs text-slate-500">
                Name the run — it keeps going if you leave this page, then auto-saves into Saved reports
                below when done. You can start several background runs at once.
              </span>
            </span>
          </label>
          {runInBackground && (
            <div className="flex flex-wrap items-end gap-2">
              <div className="min-w-[16rem] flex-1">
                <FormField label="Report name">
                  <Input
                    value={bgReportName}
                    onChange={(e) => setBgReportName(e.target.value)}
                    placeholder={`${picker.tickers.slice(0, 2).join(' + ') || 'FII-DII holdings'} · ${fromDate}→${toDate}`}
                    maxLength={200}
                  />
                </FormField>
              </div>
              <Button onClick={startBackgroundRun} disabled={startBgMutation.isPending}>
                {startBgMutation.isPending ? 'Starting…' : 'Start background run'}
              </Button>
            </div>
          )}
          {bgError && <Alert type="error">{bgError}</Alert>}
          {bgMsg && <Alert type="success">{bgMsg}</Alert>}
        </div>
      </Card>

      {ongoingList.length > 0 && (
        <Card>
          <h4 className="mb-3 font-medium text-white">Background runs in progress ({ongoingList.length})</h4>
          <div className="space-y-3">
            {ongoingList.map((job) => (
              <div key={job.job_id} className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="font-medium text-amber-100">{job.name || 'Untitled background run'}</p>
                  <p className="text-xs text-slate-500">{Math.round((job.progress ?? 0) * 100)}%</p>
                </div>
                <p className="mt-1 text-xs text-slate-400">
                  {(job.meta?.tickers ?? []).slice(0, 4).join(', ')}
                  {(job.meta?.tickers?.length ?? 0) > 4 ? '…' : ''}
                  {job.meta?.from_date ? ` · ${job.meta.from_date}→${job.meta.to_date}` : ''}
                </p>
                <p className="mt-1 text-sm text-slate-300">{job.progress_note || 'Starting…'}</p>
                <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-slate-800">
                  <div
                    className="h-full rounded-full bg-amber-400 transition-all"
                    style={{ width: `${Math.round((job.progress ?? 0) * 100)}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {recentFinished.length > 0 && (
        <Card>
          <h4 className="mb-3 font-medium text-white">Recent background runs</h4>
          <div className="space-y-2">
            {recentFinished.map((job) => (
              <div
                key={job.job_id}
                className={`flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2 text-sm ${
                  job.status === 'error' ? 'border-rose-500/30 bg-rose-500/5' : 'border-slate-800/60 bg-slate-900/40'
                }`}
              >
                <div>
                  {job.status === 'done' && job.report_id ? (
                    <button
                      className="font-medium text-slate-200 hover:text-teal-400"
                      onClick={() => setViewedReportId(job.report_id as number)}
                    >
                      {job.name || 'Untitled background run'}
                    </button>
                  ) : (
                    <span className="font-medium text-slate-200">{job.name || 'Untitled background run'}</span>
                  )}
                  <p className="text-xs text-slate-500">
                    {(job.meta?.tickers ?? []).slice(0, 4).join(', ')}
                    {(job.meta?.tickers?.length ?? 0) > 4 ? '…' : ''}
                  </p>
                  {job.status === 'error' && (
                    <p className="mt-1 text-xs text-rose-400">{job.error || 'Failed — no further detail available.'}</p>
                  )}
                </div>
                <span className={`text-xs font-medium ${job.status === 'error' ? 'text-rose-400' : job.report_id ? 'text-emerald-400' : 'text-slate-400'}`}>
                  {job.status === 'error' ? 'Failed' : job.report_id ? 'Saved' : 'Done (not saved)'}
                </span>
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card>
        <div className="mb-3 flex items-center justify-between gap-2">
          <h4 className="inline-flex items-center gap-2 font-medium text-white">
            <FolderOpen size={16} className="text-slate-400" />
            Saved reports
            <span className="text-sm font-normal text-slate-500">({reports.length})</span>
          </h4>
          <Button variant="ghost" size="sm" onClick={() => reportsQuery.refetch()} disabled={reportsQuery.isFetching}>
            Refresh
          </Button>
        </div>
        {reportsQuery.isLoading && <Loading message="Loading saved reports…" />}
        {!reportsQuery.isLoading && !reports.length && (
          <p className="text-sm text-slate-500">
            No saved reports yet. Run an analysis and save it, or start a named background run.
          </p>
        )}
        <div className="space-y-2">
          {reports.map((r) => {
            const s = r.summary
            return (
              <div
                key={r.id}
                className={`flex flex-wrap items-start justify-between gap-2 rounded-lg border px-3 py-2.5 text-sm ${
                  viewedReportId === r.id ? 'border-teal-500/50 bg-teal-500/5' : 'border-slate-800/60 bg-slate-900/40'
                }`}
              >
                <div className="min-w-0 flex-1">
                  <button
                    className="font-medium text-slate-200 hover:text-teal-400"
                    onClick={() => setViewedReportId(r.id)}
                  >
                    {r.name}
                  </button>
                  <p className="mt-0.5 text-xs text-slate-500">
                    Saved {formatWhen(r.created_at)}
                    {r.from_date && r.to_date ? ` · ${r.from_date} → ${r.to_date}` : ''}
                  </p>
                  <p className="mt-1 text-xs text-slate-400">
                    {(r.tickers ?? []).slice(0, 6).join(', ')}
                    {(r.tickers?.length ?? 0) > 6 ? '…' : ''}
                  </p>
                  {s && (s.yes_count != null || s.no_count != null) && (
                    <p className="mt-1 text-xs text-teal-400/90">
                      {s.ticker_count ?? 0} tickers · {s.yes_count ?? 0} YES · {s.no_count ?? 0} NO
                    </p>
                  )}
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    if (window.confirm(`Delete saved report "${r.name}"? This cannot be undone.`)) {
                      deleteReportMutation.mutate(r.id)
                    }
                  }}
                >
                  <Trash2 size={14} />
                </Button>
              </div>
            )
          })}
        </div>
      </Card>

      {effectiveData && !scanMut.isPending && (
        <Card>
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <div>
              {viewedReportId != null && viewedReport?.name && (
                <p className="text-sm text-slate-400">
                  Viewing saved report: <span className="text-slate-200">{viewedReport.name}</span>
                  {viewedReport.created_at ? ` · saved ${formatWhen(viewedReport.created_at)}` : ''}
                </p>
              )}
            </div>
            <div className="flex gap-2">
              {viewedReportId == null && !effectiveData.error && (
                <Button variant="secondary" size="sm" onClick={() => setShowSaveForm(true)}>
                  <span className="inline-flex items-center gap-1.5"><Save size={14} />Save for future reference</span>
                </Button>
              )}
              {viewedReportId != null && (
                <Button variant="ghost" size="sm" onClick={() => setViewedReportId(null)}>
                  <X size={14} />
                </Button>
              )}
            </div>
          </div>

          {showSaveForm && (
            <div className="mb-4 rounded-lg border border-slate-800/60 bg-slate-900/40 p-3">
              <FormField label="Report name">
                <div className="flex gap-2">
                  <Input
                    value={saveName}
                    onChange={(e) => setSaveName(e.target.value)}
                    placeholder={`${picker.tickers.slice(0, 2).join(' + ') || 'FII-DII holdings'} — ${new Date().toLocaleDateString()}`}
                  />
                  <Button
                    onClick={() => saveReportMutation.mutate({
                      name: saveName.trim() || `FII-DII holdings ${new Date().toLocaleString()}`,
                      payload: effectiveData as unknown as Record<string, unknown>,
                    })}
                    disabled={saveReportMutation.isPending}
                  >
                    <span className="inline-flex items-center gap-1.5"><Save size={14} />Save</span>
                  </Button>
                  <Button variant="ghost" onClick={() => setShowSaveForm(false)}>Cancel</Button>
                </div>
              </FormField>
              {saveMsg && <p className="mt-2 text-xs text-emerald-400">{saveMsg}</p>}
            </div>
          )}

          {effectiveData.error ? (
            <Alert type="error">{String(effectiveData.error)}</Alert>
          ) : (
            <div className="space-y-5">
              {Boolean(effectiveData.snapshot_note) && (
                <p className="text-xs text-slate-500">{String(effectiveData.snapshot_note)}</p>
              )}

              <div>
                <h4 className="mb-2 text-sm font-semibold text-white">Invest timing overview</h4>
                {!summary.length ? (
                  <p className="text-sm text-slate-500">No successful tickers.</p>
                ) : (
                  <>
                    <div className="mb-2 max-w-xs">
                      <Input
                        type="search"
                        placeholder="Search ticker…"
                        value={summarySearch}
                        onChange={(e) => setSummarySearch(e.target.value)}
                      />
                    </div>
                    {filteredSummary.length === 0 ? (
                      <p className="text-sm text-slate-500">No tickers match "{summarySearch}".</p>
                    ) : (
                  <DataTable minWidth={980} title="FII-DII Holdings">
                    <thead>
                      <tr>
                        <Th>Ticker</Th>
                        <Th>Timing</Th>
                        <Th>Ownership</Th>
                        <Th>FII Δ</Th>
                        <Th>DII Δ</Th>
                        <Th>Valuation</Th>
                        <Th>P/E</Th>
                        <Th>Revenue</Th>
                        <Th>Profit</Th>
                        <Th>Ownership Summary</Th>
                        <Th>Summary</Th>
                        <Th></Th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredSummary.map((r) => {
                        const t = String(r.Ticker ?? '')
                        return (
                          <tr
                            key={t}
                            className={`cursor-pointer border-t border-slate-800/80 align-top hover:bg-slate-800/40 ${selected === t ? 'bg-slate-800/50' : ''}`}
                            onClick={() => setSelected(t)}
                          >
                            <Td className="font-medium text-white">{t}</Td>
                            <Td>{timingBadge(r.Timing)}</Td>
                            <Td className={trendClass(r.Ownership)}>{String(r.Ownership ?? '—')}</Td>
                            <Td className={Number(r['FIIs Δ']) > 0 ? 'text-emerald-400' : Number(r['FIIs Δ']) < 0 ? 'text-rose-400' : ''}>
                              {fmt(r['FIIs Δ'])} pp
                            </Td>
                            <Td className={Number(r['DIIs Δ']) > 0 ? 'text-emerald-400' : Number(r['DIIs Δ']) < 0 ? 'text-rose-400' : ''}>
                              {fmt(r['DIIs Δ'])} pp
                            </Td>
                            <Td className="text-xs text-slate-300">{String(r.Valuation ?? '—')}</Td>
                            <Td>{fmt(r['P/E'], 1)}</Td>
                            <Td className={trendClass(r['Revenue trend'])}>{String(r['Revenue trend'] ?? '—')}</Td>
                            <Td className={trendClass(r['Profit trend'])}>{String(r['Profit trend'] ?? '—')}</Td>
                            <Td className="max-w-xs text-xs text-slate-400">{String(r['Ownership Summary'] ?? '—')}</Td>
                            <Td className="max-w-xs text-xs text-slate-400">{String(r.Summary ?? '—')}</Td>
                            <Td>
                              <AddToWatchlistButton
                                ticker={t}
                                displayName={t}
                                notes={`FII-DII · ${r.Timing} · FII Δ ${fmt(r['FIIs Δ'])} · DII Δ ${fmt(r['DIIs Δ'])}`}
                                marketType="india"
                                compact
                              />
                            </Td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </DataTable>
                    )}
                  </>
                )}
              </div>

              {ok.length > 0 && (
                <div className="space-y-3">
                  <div className="flex flex-wrap gap-2">
                    {ok.map((r) => (
                      <Chip
                        key={String(r.ticker)}
                        selected={selected === String(r.ticker)}
                        onClick={() => setSelected(String(r.ticker))}
                      >
                        {String(r.ticker)}
                      </Chip>
                    ))}
                  </div>

                  {detail && !detail.error && (
                    <>
                      <div className="rounded-xl border border-slate-800/80 bg-slate-900/40 p-4">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="text-sm font-semibold text-white">{String(detail.ticker)}</p>
                          {timingBadge((detail.timing as Row)?.verdict)}
                        </div>
                        <p className="mt-2 text-sm leading-relaxed text-slate-200">
                          {String(detail.ownership_summary ?? '—')}
                        </p>
                        <p className="mt-1 text-xs leading-relaxed text-slate-400">
                          {String((detail.timing as Row)?.summary ?? (detail.ownership as Row)?.summary ?? '—')}
                        </p>
                        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                          {(['Promoters', 'FIIs', 'DIIs', 'Public'] as const).map((cat) => {
                            const info = categories[cat] ?? {}
                            return (
                              <div key={cat} className="rounded-lg border border-slate-800/60 bg-slate-950/40 p-3">
                                <p className="text-[11px] uppercase tracking-wide text-slate-500">{cat}</p>
                                <p className="mt-1 text-lg font-semibold tabular-nums text-white">{fmt(info.last_pct)}%</p>
                                <p className={`text-xs ${trendClass(info.trend)}`}>
                                  {fmt(info.change_pp)} pp · {String(info.trend ?? '—')}
                                </p>
                              </div>
                            )
                          })}
                        </div>
                      </div>

                      <OwnershipChart rows={chartAll} ticker={String(detail.ticker)} />

                      <div className="grid gap-3 sm:grid-cols-2">
                        <div className="rounded-xl border border-slate-800/80 p-3">
                          <p className="text-xs font-medium text-slate-400">Valuation</p>
                          <p className="mt-1 text-sm text-white">{String((detail.valuation as Row)?.label ?? '—')}</p>
                          <p className="mt-1 text-xs text-slate-500">
                            P/E {fmt(detail.pe, 1)} · ROCE {fmt(detail.roce_pct, 1)}%
                          </p>
                        </div>
                        <div className="rounded-xl border border-slate-800/80 p-3">
                          <p className="text-xs font-medium text-slate-400">Revenue &amp; profit</p>
                          <p className="mt-1 text-sm text-slate-200">
                            Sales {(detail.revenue_profit as Row)?.sales ? String(((detail.revenue_profit as Row).sales as Row).trend) : '—'}
                            {' · '}
                            Profit {(detail.revenue_profit as Row)?.net_profit ? String(((detail.revenue_profit as Row).net_profit as Row).trend) : '—'}
                          </p>
                          <p className="mt-1 text-xs text-slate-500">
                            Deals flagged: {String((detail.deals as Row)?.n_flagged ?? 0)} · Actions: {String((detail.actions as Row)?.n_signal ?? 0)}
                          </p>
                        </div>
                      </div>

                      <AskAIPanel
                        context={String(detail.ai_context ?? '')}
                        systemPrompt={String(effectiveData.ai_system_prompt ?? '')}
                        section={`command-center/fii-dii/${String(detail.ticker)}`}
                      />
                    </>
                  )}
                  {Boolean(detail?.error) && <Alert type="error">{String(detail?.error)}</Alert>}
                </div>
              )}

              {((effectiveData.errors as Row[]) ?? []).length > 0 && (
                <div>
                  <p className="mb-1 text-xs text-slate-500">Failed tickers</p>
                  <ul className="space-y-1 text-xs text-rose-300/90">
                    {((effectiveData.errors as Row[]) ?? []).map((e) => (
                      <li key={String(e.ticker)}>{String(e.ticker)} — {String(e.error)}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </Card>
      )}
    </div>
  )
}
