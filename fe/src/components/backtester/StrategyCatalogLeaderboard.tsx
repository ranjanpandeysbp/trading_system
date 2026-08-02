import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { Play, Save, Trash2, FolderOpen, X } from 'lucide-react'
import {
  apiErrorMessage,
  deleteBacktesterReport,
  fetchBacktesterLeaderboardCatalog,
  fetchBacktesterLeaderboardJob,
  fetchBacktesterLeaderboardJobs,
  fetchBacktesterReport,
  fetchBacktesterReports,
  saveBacktesterReport,
  startBacktesterLeaderboardJob,
  type StrategyCategoryInfo,
} from '../../api/client'
import { Card } from '../ui/Card'
import { Button } from '../ui/Button'
import { Chip } from '../ui/Chip'
import { FormField, Input, Select } from '../ui/Form'
import { Alert, Loading } from '../ui/Feedback'
import { DataTable, SortableTh, Td, Th, useSort } from '../ui/Table'
import { AddToWatchlistButton } from '../watchlist/AddToWatchlistButton'
import { AssetClassTickerPicker, type TickerPickerValue } from '../command-center/AssetClassTickerPicker'
import { AdvancedBacktestReportPanel, type AdvancedReport } from './AdvancedBacktestReportPanel'
import { backtestRecommendation } from '../../lib/backtestRecommendation'

const PERIOD_OPTIONS = [
  { value: '30d', label: '30 days' },
  { value: '90d', label: '90 days' },
  { value: '180d', label: '180 days' },
  { value: '1y', label: '1 year' },
  { value: '2y', label: '2 years' },
  { value: '5y', label: '5 years' },
  { value: '10y', label: '10 years' },
]

// Minutes -> hours -> days -> weeks -> months, in one selector.
const TIMEFRAME_OPTIONS = [
  { value: '1m', label: '1 minute' },
  { value: '3m', label: '3 minutes' },
  { value: '5m', label: '5 minutes' },
  { value: '15m', label: '15 minutes' },
  { value: '30m', label: '30 minutes' },
  { value: '1h', label: '1 hour' },
  { value: '4h', label: '4 hours' },
  { value: '1d', label: '1 day' },
  { value: '1wk', label: '1 week' },
  { value: '1M', label: '1 month' },
]

interface BtRow {
  ticker: string
  strategy_id: string
  strategy_label: string
  category: string
  timeframe: string | null
  period: string | null
  num_trades: number
  win_rate_pct: number | null
  total_return_pct: number | null
  max_drawdown_pct: number | null
  avg_return_per_trade_pct: number | null
  cagr_pct?: number | null
  payoff_ratio?: number | null
  profit_factor?: number | null
  expectancy_pct?: number | null
  sharpe_ratio?: number | null
  sortino_ratio?: number | null
  calmar_ratio?: number | null
  rank_score: number
  thin_sample: boolean
  summary: string | null
  advanced?: AdvancedReport | null
  error: string | null
}

interface BtResult {
  asset_class?: string
  tickers?: string[]
  strategy_count?: number
  timeframe?: string | null
  period?: string | null
  rows: BtRow[]
  best_per_ticker: BtRow[]
  advanced_report?: AdvancedReport | null
  generated_at?: string
  error?: string
  saved_report_id?: number
  saved_report_name?: string
}

interface ReportSummary {
  ticker_count?: number
  strategy_count?: number
  combo_count?: number
  period?: string | null
  timeframe?: string | null
  best_return_pct?: number | null
  best_strategy?: string | null
  best_ticker?: string | null
  best_per_ticker_count?: number
  error_count?: number
  cagr_pct?: number | null
  sharpe_ratio?: number | null
  profit_factor?: number | null
  assessment_verdict?: string | null
  assessment_score?: number | null
}

interface SavedReportSummary {
  id: number
  name: string
  asset_class: string
  tickers: string[]
  timeframes: string[]
  created_at: string
  summary?: ReportSummary
}

interface BgJobStatus {
  job_id: string
  status: string
  progress?: number
  progress_note?: string
  name?: string | null
  report_id?: number | null
  error?: string | null
  result?: BtResult
  meta?: {
    tickers?: string[]
    strategy_count?: number
    asset_class?: string
    period?: string | null
    timeframe?: string | null
  }
  created_at?: number
}

function fmtPct(v: number | null | undefined, digits = 2): string {
  return typeof v === 'number' && Number.isFinite(v) ? `${v.toFixed(digits)}%` : '—'
}

function formatWhen(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

export function StrategyCatalogLeaderboard({
  assetClass,
  tickerMode = 'multi',
  heading,
  runLabel = 'Run leaderboard',
  initialStrategyIds,
}: {
  assetClass: 'india' | 'us' | 'crypto' | 'commodity'
  tickerMode?: 'single' | 'multi'
  heading?: string
  runLabel?: string
  initialStrategyIds?: string[]
}) {
  const queryClient = useQueryClient()
  const [tickerList, setTickerList] = useState<string[]>([])
  const [selectedStrategies, setSelectedStrategies] = useState<string[]>(initialStrategyIds ?? [])
  const [timeframe, setTimeframe] = useState('1d')
  const [period, setPeriod] = useState('2y')
  const [bars, setBars] = useState(350)
  const [forwardBars, setForwardBars] = useState(10)
  const [runInBackground, setRunInBackground] = useState(false)
  const [bgReportName, setBgReportName] = useState('')
  /** Foreground job — keeps live result on this page. */
  const [fgJobId, setFgJobId] = useState<string | null>(null)
  /** Background job ids we are tracking (also refreshed from server). */
  const [bgJobIds, setBgJobIds] = useState<string[]>([])
  const [error, setError] = useState('')
  const [saveName, setSaveName] = useState('')
  const [showSaveForm, setShowSaveForm] = useState(false)
  const [saveMsg, setSaveMsg] = useState('')
  const [viewedReportId, setViewedReportId] = useState<number | null>(null)
  const [expandedCats, setExpandedCats] = useState<Set<string>>(new Set())
  const handledDoneRef = useRef<Set<string>>(new Set())

  const catalogQuery = useQuery({ queryKey: ['bt-catalog'], queryFn: fetchBacktesterLeaderboardCatalog })
  const categories = catalogQuery.data?.categories ?? []

  useEffect(() => {
    if (initialStrategyIds?.length) setSelectedStrategies(initialStrategyIds)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(initialStrategyIds)])

  const toggleCat = (id: string) =>
    setExpandedCats((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const reportsQuery = useQuery({
    queryKey: ['bt-reports'],
    queryFn: fetchBacktesterReports,
  })
  const reports = ((reportsQuery.data as { reports?: SavedReportSummary[] } | undefined)?.reports) ?? []

  const runningJobsQuery = useQuery({
    queryKey: ['bt-jobs-running'],
    queryFn: () => fetchBacktesterLeaderboardJobs('running'),
    refetchInterval: 2000,
  })

  useEffect(() => {
    const serverJobs = ((runningJobsQuery.data as { jobs?: BgJobStatus[] } | undefined)?.jobs) ?? []
    const ids = serverJobs.map((j) => j.job_id)
    if (!ids.length) return
    setBgJobIds((prev) => Array.from(new Set([...ids, ...prev])))
  }, [runningJobsQuery.data])

  const trackedIds = useMemo(
    () => Array.from(new Set([...bgJobIds, ...(fgJobId ? [fgJobId] : [])])),
    [bgJobIds, fgJobId],
  )

  const jobQueries = useQueries({
    queries: trackedIds.map((id) => ({
      queryKey: ['bt-job', id],
      queryFn: () => fetchBacktesterLeaderboardJob(id) as Promise<BgJobStatus>,
      refetchInterval: (q: { state: { data?: BgJobStatus } }) =>
        q.state.data?.status === 'running' ? 1500 : false,
      refetchIntervalInBackground: true,
      retry: false,
    })),
  })

  const jobById = useMemo(() => {
    const map = new Map<string, BgJobStatus>()
    jobQueries.forEach((q, i) => {
      const id = trackedIds[i]
      if (id && q.data) map.set(id, q.data as BgJobStatus)
    })
    return map
  }, [jobQueries, trackedIds])

  // When a background job finishes, drop it from ongoing and refresh reports.
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
          setSaveMsg(`Background report saved${job.name ? `: ${job.name}` : ''}.`)
        } else if (job.status === 'done') {
          setSaveMsg(job.name ? `Background run "${job.name}" finished.` : 'Background run finished.')
        } else if (job.status === 'error') {
          setError(job.error || `Background job failed: ${job.name || id}`)
        }
      }
    }
    if (stillRunning.length !== bgJobIds.length) {
      setBgJobIds(stillRunning)
    }
    if (changed) {
      queryClient.invalidateQueries({ queryKey: ['bt-reports'] })
      queryClient.invalidateQueries({ queryKey: ['bt-jobs-running'] })
    }
  }, [bgJobIds, jobById, queryClient])

  const reportDetailQuery = useQuery({
    queryKey: ['bt-report', viewedReportId],
    queryFn: () => fetchBacktesterReport(viewedReportId as number),
    enabled: viewedReportId != null,
  })

  const startMutation = useMutation({
    mutationFn: startBacktesterLeaderboardJob,
    onSuccess: (data, variables) => {
      const id = data.job_id as string
      setError('')
      setSaveMsg('')
      setViewedReportId(null)
      if (variables.run_in_background) {
        setBgJobIds((prev) => Array.from(new Set([id, ...prev])))
        setFgJobId(null)
        setSaveMsg(`Background backtest started${variables.report_name ? `: ${variables.report_name}` : ''}.`)
        setBgReportName('')
        queryClient.invalidateQueries({ queryKey: ['bt-jobs-running'] })
      } else {
        setFgJobId(id)
      }
    },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const saveMutation = useMutation({
    mutationFn: saveBacktesterReport,
    onSuccess: () => {
      setSaveMsg('Report saved.')
      setShowSaveForm(false)
      setSaveName('')
      queryClient.invalidateQueries({ queryKey: ['bt-reports'] })
    },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const deleteMutation = useMutation({
    mutationFn: deleteBacktesterReport,
    onSuccess: (_data, reportId) => {
      if (viewedReportId === reportId) setViewedReportId(null)
      queryClient.invalidateQueries({ queryKey: ['bt-reports'] })
    },
  })

  const toggleStrategy = (id: string) =>
    setSelectedStrategies((prev) => (prev.includes(id) ? prev.filter((s) => s !== id) : [...prev, id]))

  const runJob = () => {
    if (!tickerList.length) {
      setError(tickerMode === 'single' ? 'Select a ticker' : 'Enter at least one ticker')
      return
    }
    if (!selectedStrategies.length) {
      setError('Select at least one strategy')
      return
    }
    if (runInBackground && !bgReportName.trim()) {
      setError('Enter a report name for the background backtest')
      return
    }
    startMutation.mutate({
      tickers: tickerList,
      strategy_ids: selectedStrategies,
      asset_class: assetClass,
      timeframe,
      period,
      bars,
      forward_bars: forwardBars,
      run_in_background: runInBackground,
      report_name: runInBackground ? bgReportName.trim() : undefined,
    })
  }

  const fgJob = fgJobId ? jobById.get(fgJobId) : undefined
  const fgRunning = fgJob?.status === 'running'
  const liveResult = fgJob?.status === 'done' ? fgJob.result : undefined
  const viewedReport = reportDetailQuery.data as { name?: string; payload?: BtResult; created_at?: string; error?: string } | undefined
  const result: BtResult | undefined = viewedReportId != null ? viewedReport?.payload : liveResult

  const ongoingBg = bgJobIds
    .map((id) => jobById.get(id))
    .filter((j): j is BgJobStatus => !!j && j.status === 'running')

  // Also show server-listed running jobs that may not have been polled yet
  const serverRunning = ((runningJobsQuery.data as { jobs?: BgJobStatus[] } | undefined)?.jobs) ?? []
  const ongoingMap = new Map<string, BgJobStatus>()
  for (const j of [...serverRunning, ...ongoingBg]) {
    if (j.status === 'running') ongoingMap.set(j.job_id, j)
  }
  // Don't list the active foreground job as a "background" card
  if (fgJobId) ongoingMap.delete(fgJobId)
  const ongoingList = Array.from(ongoingMap.values()).sort(
    (a, b) => (b.created_at ?? 0) - (a.created_at ?? 0),
  )

  return (
    <div className="space-y-4">
      <Card>
        {heading && <p className="mb-4 text-sm text-slate-400">{heading}</p>}
        <FormField label={tickerMode === 'single' ? 'Ticker' : 'Tickers'}>
          <AssetClassTickerPicker
            key={assetClass}
            assetClass={assetClass}
            single={tickerMode === 'single'}
            showDurations={false}
            onChange={(v: TickerPickerValue) => setTickerList(v.tickers)}
          />
        </FormField>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <FormField label="Timeframe (minutes to months — used by timeframe-flexible strategies)">
            <Select value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
              {TIMEFRAME_OPTIONS.map((tf) => <option key={tf.value} value={tf.value}>{tf.label}</option>)}
            </Select>
          </FormField>
          <FormField label="Backtest period">
            <Select value={period} onChange={(e) => setPeriod(e.target.value)}>
              {PERIOD_OPTIONS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
            </Select>
          </FormField>
          <FormField label="History bars">
            <Input type="number" min={150} max={2000} step={50} value={bars} onChange={(e) => setBars(Number(e.target.value))} />
          </FormField>
          <FormField label="Forward bars (target window)">
            <Input type="number" min={3} max={60} value={forwardBars} onChange={(e) => setForwardBars(Number(e.target.value))} />
          </FormField>
        </div>

        <FormField label={`Strategies (${selectedStrategies.length} of ${categories.reduce((n, c) => n + c.strategy_count, 0)} selected)`}>
          <div className="max-h-72 space-y-1 overflow-y-auto rounded-xl border border-slate-800/60 bg-slate-800/20 p-3">
            {categories.map((cat: StrategyCategoryInfo) => {
              const open = expandedCats.has(cat.id)
              const selectedInCat = cat.strategies.filter((s) => selectedStrategies.includes(s.id)).length
              return (
                <div key={cat.id} className="border-b border-slate-800/40 pb-1 last:border-0">
                  <button
                    type="button"
                    onClick={() => toggleCat(cat.id)}
                    className="flex w-full items-center justify-between py-1.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-400 hover:text-slate-200"
                  >
                    <span>{cat.label} ({cat.strategy_count}){selectedInCat ? ` · ${selectedInCat} selected` : ''}</span>
                    <span>{open ? '▲' : '▼'}</span>
                  </button>
                  {open && (
                    <div className="flex flex-wrap gap-1.5 py-1.5">
                      {cat.strategies.map((s) => (
                        <Chip key={s.id} selected={selectedStrategies.includes(s.id)} onClick={() => toggleStrategy(s.id)}>
                          {s.name}
                        </Chip>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
            {!categories.length && <p className="text-sm text-slate-500">Loading strategy catalog…</p>}
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button variant="secondary" size="sm" onClick={() => setSelectedStrategies(categories.flatMap((c) => c.strategies.map((s) => s.id)))}>
              Select all
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setSelectedStrategies([])}>Clear</Button>
          </div>
        </FormField>

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
                Name the run — it keeps going if you leave this page, then auto-saves into Saved reports when done.
                You can start several background backtests at once.
              </span>
            </span>
          </label>
          {runInBackground && (
            <FormField label="Report name">
              <Input
                value={bgReportName}
                onChange={(e) => setBgReportName(e.target.value)}
                placeholder={`${tickerList.slice(0, 3).join('+') || 'Backtest'} · ${period} · ${new Date().toLocaleDateString()}`}
                maxLength={200}
              />
            </FormField>
          )}
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button onClick={runJob} disabled={startMutation.isPending || (!runInBackground && fgRunning)}>
            <span className="inline-flex items-center gap-1.5">
              <Play size={14} />
              {startMutation.isPending
                ? 'Starting…'
                : !runInBackground && fgRunning
                  ? 'Running…'
                  : `${runInBackground ? 'Start background' : runLabel} (${tickerList.length} × ${selectedStrategies.length} strategies)`}
            </span>
          </Button>
        </div>
        {error && <div className="mt-3"><Alert type="error">{error}</Alert></div>}
        {saveMsg && <div className="mt-3"><Alert type="success">{saveMsg}</Alert></div>}
      </Card>

      {ongoingList.length > 0 && (
        <Card>
          <h4 className="mb-3 font-medium text-white">Background backtests in progress ({ongoingList.length})</h4>
          <div className="space-y-3">
            {ongoingList.map((job) => (
              <div key={job.job_id} className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="font-medium text-amber-100">{job.name || 'Untitled background run'}</p>
                  <p className="text-xs text-slate-500">{Math.round((job.progress ?? 0) * 100)}%</p>
                </div>
                <p className="mt-1 text-xs text-slate-400">
                  {(job.meta?.tickers ?? []).slice(0, 6).join(', ')}
                  {(job.meta?.tickers?.length ?? 0) > 6 ? '…' : ''}
                  {job.meta?.strategy_count != null ? ` · ${job.meta.strategy_count} strategies` : ''}
                  {job.meta?.period ? ` · ${job.meta.period}` : ''}
                  {job.meta?.asset_class ? ` · ${job.meta.asset_class}` : ''}
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

      {fgRunning && fgJob && (
        <Card>
          <p className="mb-2 text-sm text-slate-300">{fgJob.progress_note || 'Starting…'}</p>
          <div className="h-2 w-full overflow-hidden rounded-full bg-slate-800">
            <div
              className="h-full rounded-full bg-teal-500 transition-all"
              style={{ width: `${Math.round((fgJob.progress ?? 0) * 100)}%` }}
            />
          </div>
          <p className="mt-1 text-xs text-slate-500">{Math.round((fgJob.progress ?? 0) * 100)}% complete</p>
        </Card>
      )}

      {fgJob?.status === 'error' && <Alert type="error">{fgJob.error}</Alert>}

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
            No saved reports yet. Run a backtest in the foreground and save it, or start a named background run.
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
                    onClick={() => { setViewedReportId(r.id); setFgJobId(null) }}
                  >
                    {r.name}
                  </button>
                  <p className="mt-0.5 text-xs text-slate-500">
                    Backtested {formatWhen(r.created_at)}
                    {r.asset_class ? ` · ${r.asset_class}` : ''}
                  </p>
                  <p className="mt-1 text-xs text-slate-400">
                    {(r.tickers ?? []).slice(0, 8).join(', ')}
                    {(r.tickers?.length ?? 0) > 8 ? '…' : ''}
                    {s?.strategy_count != null ? ` · ${s.strategy_count} strategies` : ''}
                    {s?.period ? ` · ${s.period}` : ''}
                    {s?.timeframe ? ` · ${s.timeframe}` : ''}
                  </p>
                  {(s?.best_strategy || s?.best_return_pct != null) && (
                    <p className="mt-1 text-xs text-teal-400/90">
                      Best: {s.best_strategy || '—'}
                      {s.best_ticker ? ` on ${s.best_ticker}` : ''}
                      {s.best_return_pct != null ? ` · ${fmtPct(s.best_return_pct)}` : ''}
                      {s.cagr_pct != null ? ` · CAGR ${fmtPct(s.cagr_pct)}` : ''}
                      {s.sharpe_ratio != null ? ` · Sharpe ${s.sharpe_ratio.toFixed(2)}` : ''}
                      {s.assessment_score != null ? ` · score ${s.assessment_score}/10` : ''}
                    </p>
                  )}
                  {s?.assessment_verdict && (
                    <p className="mt-0.5 text-[11px] text-slate-500">{s.assessment_verdict}</p>
                  )}
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    if (window.confirm(`Delete saved report "${r.name}"? This cannot be undone.`)) {
                      deleteMutation.mutate(r.id)
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

      {result?.error && <Alert type="error">{result.error}</Alert>}

      {result && !result.error && (
        <BacktesterResults
          data={result}
          reportName={viewedReportId != null ? viewedReport?.name : undefined}
          reportDate={viewedReportId != null ? viewedReport?.created_at : undefined}
          onSave={viewedReportId == null ? () => setShowSaveForm(true) : undefined}
          onClose={viewedReportId != null ? () => setViewedReportId(null) : undefined}
        />
      )}

      {showSaveForm && result && (
        <Card>
          <FormField label="Report name">
            <div className="flex gap-2">
              <Input
                value={saveName}
                onChange={(e) => setSaveName(e.target.value)}
                placeholder={`${(result.tickers ?? []).join('+')} backtest — ${new Date().toLocaleDateString()}`}
              />
              <Button
                onClick={() => saveMutation.mutate({ name: saveName.trim() || `Backtest ${new Date().toLocaleString()}`, payload: result as unknown as Record<string, unknown> })}
                disabled={saveMutation.isPending}
              >
                <span className="inline-flex items-center gap-1.5"><Save size={14} />Save</span>
              </Button>
              <Button variant="ghost" onClick={() => setShowSaveForm(false)}>Cancel</Button>
            </div>
          </FormField>
        </Card>
      )}
    </div>
  )
}

function BacktesterResults({
  data,
  reportName,
  reportDate,
  onSave,
  onClose,
}: {
  data: BtResult
  reportName?: string
  reportDate?: string
  onSave?: () => void
  onClose?: () => void
}) {
  const rows = data.rows ?? []
  const best = data.best_per_ticker ?? []
  const [focusKey, setFocusKey] = useState<string | null>(null)
  const { sorted, sortKey, sortDir, handleSort } = useSort(rows, {
    ticker: (r) => r.ticker,
    strategy: (r) => r.strategy_label,
    category: (r) => r.category,
    trades: (r) => r.num_trades,
    win_rate: (r) => r.win_rate_pct,
    total_return: (r) => r.total_return_pct,
    drawdown: (r) => r.max_drawdown_pct,
    sharpe: (r) => r.sharpe_ratio,
    rank_score: (r) => r.rank_score,
  }, 'rank_score', 'desc')

  const focused = focusKey
    ? rows.find((r) => `${r.ticker}::${r.strategy_id}` === focusKey)
    : null
  const advanced: AdvancedReport | null | undefined =
    focused?.advanced || data.advanced_report || best[0]?.advanced || sorted[0]?.advanced

  return (
    <div className="space-y-4">
      <Card>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="font-semibold text-white">{reportName || 'Backtest leaderboard result'}</h3>
            <p className="text-sm text-slate-400">
              {(data.tickers ?? []).join(', ')} · {data.strategy_count} strategies · {data.asset_class} · {data.period}
              {reportDate ? ` · saved ${formatWhen(reportDate)}` : ''}
            </p>
          </div>
          <div className="flex gap-2">
            {onSave && (
              <Button variant="secondary" onClick={onSave}>
                <span className="inline-flex items-center gap-1.5"><Save size={14} />Save this report</span>
              </Button>
            )}
            {onClose && (
              <Button variant="ghost" onClick={onClose}>
                <X size={14} />
              </Button>
            )}
          </div>
        </div>

        <p className="mb-2 text-xs font-medium uppercase tracking-wider text-slate-500">Best strategy per ticker</p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {best.map((r) => (
            <button
              key={r.ticker}
              type="button"
              onClick={() => setFocusKey(`${r.ticker}::${r.strategy_id}`)}
              className={`rounded-lg border p-3 text-left transition ${
                focusKey === `${r.ticker}::${r.strategy_id}`
                  ? 'border-teal-400 bg-teal-500/10'
                  : 'border-teal-500/30 bg-teal-500/5 hover:border-teal-400/60'
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs uppercase tracking-wider text-teal-400">{r.ticker}</p>
                <AddToWatchlistButton ticker={r.ticker} compact />
              </div>
              <p className="mt-1 font-medium text-white">{r.strategy_label}</p>
              <p className="text-xs text-slate-500">{r.category} · {r.timeframe}</p>
              <div className="mt-2 flex flex-wrap gap-3 text-xs text-slate-400">
                <span>Return {fmtPct(r.total_return_pct)}</span>
                <span>Win {fmtPct(r.win_rate_pct, 0)}</span>
                <span>{r.num_trades} trades</span>
                {r.sharpe_ratio != null && <span>Sharpe {r.sharpe_ratio.toFixed(2)}</span>}
                {r.profit_factor != null && <span>PF {r.profit_factor.toFixed(2)}</span>}
              </div>
              {r.thin_sample && (
                <p className="mt-1 text-[11px] text-amber-400">Thin sample — treat with caution ({'<'}10 trades)</p>
              )}
              <p className="mt-2 border-t border-teal-500/20 pt-2 text-[11px] leading-relaxed text-slate-400">
                {backtestRecommendation({
                  num_trades: r.num_trades, win_rate_pct: r.win_rate_pct,
                  total_return_pct: r.total_return_pct, max_drawdown_pct: r.max_drawdown_pct,
                })}
              </p>
            </button>
          ))}
          {!best.length && (
            <p className="text-sm text-slate-500">No strategy produced a completed trade for any ticker in this run.</p>
          )}
        </div>
      </Card>

      {advanced && (
        <Card>
          <AdvancedBacktestReportPanel report={advanced} />
          {focused && (
            <p className="mt-3 text-xs text-slate-500">
              Showing deep-dive for <span className="text-slate-300">{focused.ticker} · {focused.strategy_label}</span>
              {' · '}
              <button type="button" className="text-teal-400 hover:underline" onClick={() => setFocusKey(null)}>
                reset to top-ranked
              </button>
            </p>
          )}
        </Card>
      )}

      <Card>
        <p className="mb-3 text-xs font-medium uppercase tracking-wider text-slate-500">
          All results ({sorted.length} strategy × ticker combinations) — click a row for its advanced report
        </p>
        <DataTable>
          <thead>
            <tr>
              <SortableTh active={sortKey === 'ticker'} direction={sortDir} onSort={() => handleSort('ticker')}>Ticker</SortableTh>
              <SortableTh active={sortKey === 'strategy'} direction={sortDir} onSort={() => handleSort('strategy')}>Strategy</SortableTh>
              <SortableTh active={sortKey === 'category'} direction={sortDir} onSort={() => handleSort('category')}>Category</SortableTh>
              <SortableTh active={sortKey === 'trades'} direction={sortDir} onSort={() => handleSort('trades')}>Trades</SortableTh>
              <SortableTh active={sortKey === 'win_rate'} direction={sortDir} onSort={() => handleSort('win_rate')}>Win %</SortableTh>
              <SortableTh active={sortKey === 'total_return'} direction={sortDir} onSort={() => handleSort('total_return')}>Total Return</SortableTh>
              <SortableTh active={sortKey === 'drawdown'} direction={sortDir} onSort={() => handleSort('drawdown')}>Max DD</SortableTh>
              <SortableTh active={sortKey === 'sharpe'} direction={sortDir} onSort={() => handleSort('sharpe')}>Sharpe</SortableTh>
              <SortableTh active={sortKey === 'rank_score'} direction={sortDir} onSort={() => handleSort('rank_score')}>Rank score</SortableTh>
              <Th>Watch</Th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((r, i) => {
              const key = `${r.ticker}::${r.strategy_id}`
              return (
                <tr
                  key={`${key}-${i}`}
                  className={`cursor-pointer ${focusKey === key ? 'bg-teal-500/10' : 'hover:bg-slate-800/40'}`}
                  onClick={() => r.advanced && setFocusKey(key)}
                >
                  <Td>{r.ticker}</Td>
                  <Td className="max-w-[14rem] truncate"><span title={r.summary ?? ''}>{r.strategy_label}</span></Td>
                  <Td className="text-slate-500">{r.category}</Td>
                  <Td>
                    {r.num_trades}
                    {r.thin_sample && r.num_trades > 0 && <span className="ml-1 text-[10px] text-amber-400">thin</span>}
                  </Td>
                  <Td>{fmtPct(r.win_rate_pct, 0)}</Td>
                  <Td>{r.error ? <span className="text-rose-400">error</span> : fmtPct(r.total_return_pct)}</Td>
                  <Td>{fmtPct(r.max_drawdown_pct)}</Td>
                  <Td>{r.sharpe_ratio != null ? r.sharpe_ratio.toFixed(2) : '—'}</Td>
                  <Td>{r.error ? '—' : r.rank_score.toFixed(3)}</Td>
                  <Td onClick={(e) => e.stopPropagation()}><AddToWatchlistButton ticker={r.ticker} compact /></Td>
                </tr>
              )
            })}
          </tbody>
        </DataTable>
      </Card>
    </div>
  )
}
