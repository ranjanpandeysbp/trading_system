import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Play, Save, Trash2, FolderOpen, X } from 'lucide-react'
import {
  apiErrorMessage,
  deleteLeaderboardReport,
  fetchLeaderboardCatalog,
  fetchLeaderboardJob,
  fetchLeaderboardReport,
  fetchLeaderboardReports,
  saveLeaderboardReport,
  startLeaderboardJob,
} from '../../api/client'
import { AssetClassTickerPicker, type AssetClass, type TickerPickerValue } from '../command-center/AssetClassTickerPicker'
import { Card } from '../ui/Card'
import { Button } from '../ui/Button'
import { Chip } from '../ui/Chip'
import { FormField, Input } from '../ui/Form'
import { Alert, Loading } from '../ui/Feedback'
import { DataTable, SortableTh, Td, Th, useSort } from '../ui/Table'
import { AddToWatchlistButton } from '../watchlist/AddToWatchlistButton'

const TFS = ['5m', '15m', '1h', '4h', '1d']

interface CatalogStrategy {
  id: string
  label: string
  hub: string
  timeframes: string[]
  multi_tf: boolean
  needs_benchmark: boolean
  notes: string
}

interface LeaderboardRow {
  ticker: string
  strategy_id: string
  strategy_label: string
  hub: string
  timeframe: string
  total_signals: number
  overall_win_rate_pct: number | null
  avg_forward_return_pct: number | null
  rank_score: number
  thin_sample: boolean
  notes: string
  error: string | null
}

interface LeaderboardResult {
  market?: string
  asset_class?: string
  tickers?: string[]
  timeframes?: string[]
  bars?: number
  forward_bars?: number
  rows: LeaderboardRow[]
  best_per_ticker: LeaderboardRow[]
  generated_at?: string
  error?: string
}

interface SavedReportSummary {
  id: number
  name: string
  asset_class: string
  tickers: string[]
  timeframes: string[]
  created_at: string
}

function fmtPct(v: number | null | undefined, digits = 1): string {
  return typeof v === 'number' && Number.isFinite(v) ? `${v.toFixed(digits)}%` : '—'
}

export function LeaderboardPanel({ assetClass }: { assetClass: AssetClass }) {
  const queryClient = useQueryClient()
  const [tickers, setTickers] = useState<string[]>([])
  const [selectedTfs, setSelectedTfs] = useState<string[]>(['1d'])
  const [strategyIds, setStrategyIds] = useState<string[]>([])
  const [strategiesInit, setStrategiesInit] = useState(false)
  const [bars, setBars] = useState(350)
  const [forwardBars, setForwardBars] = useState(10)
  const [jobId, setJobId] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [saveName, setSaveName] = useState('')
  const [showSaveForm, setShowSaveForm] = useState(false)
  const [saveMsg, setSaveMsg] = useState('')
  const [viewedReportId, setViewedReportId] = useState<number | null>(null)
  const [showReports, setShowReports] = useState(false)

  const catalogQuery = useQuery({ queryKey: ['lb-catalog'], queryFn: fetchLeaderboardCatalog })
  const catalog = ((catalogQuery.data as { strategies?: CatalogStrategy[] } | undefined)?.strategies) ?? []
  const catalogByHub = useMemo(() => {
    const map = new Map<string, CatalogStrategy[]>()
    for (const s of catalog) {
      if (!map.has(s.hub)) map.set(s.hub, [])
      map.get(s.hub)!.push(s)
    }
    return map
  }, [catalog])

  useEffect(() => {
    if (!catalog.length || strategiesInit) return
    setStrategyIds(catalog.map((s) => s.id))
    setStrategiesInit(true)
  }, [catalog, strategiesInit])

  const jobQuery = useQuery({
    queryKey: ['lb-job', jobId],
    queryFn: () => fetchLeaderboardJob(jobId as string),
    enabled: !!jobId,
    refetchInterval: (q) => {
      const status = (q.state.data as { status?: string } | undefined)?.status
      return status === 'running' ? 1500 : false
    },
    refetchIntervalInBackground: true,
  })

  const reportsQuery = useQuery({
    queryKey: ['lb-reports'],
    queryFn: fetchLeaderboardReports,
    enabled: showReports,
  })
  const reports = ((reportsQuery.data as { reports?: SavedReportSummary[] } | undefined)?.reports) ?? []

  const reportDetailQuery = useQuery({
    queryKey: ['lb-report', viewedReportId],
    queryFn: () => fetchLeaderboardReport(viewedReportId as number),
    enabled: viewedReportId != null,
  })

  const startMutation = useMutation({
    mutationFn: startLeaderboardJob,
    onSuccess: (data) => {
      setJobId(data.job_id)
      setViewedReportId(null)
      setError('')
      setSaveMsg('')
    },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const saveMutation = useMutation({
    mutationFn: saveLeaderboardReport,
    onSuccess: () => {
      setSaveMsg('Report saved.')
      setShowSaveForm(false)
      setSaveName('')
      queryClient.invalidateQueries({ queryKey: ['lb-reports'] })
    },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const deleteMutation = useMutation({
    mutationFn: deleteLeaderboardReport,
    onSuccess: (_data, reportId) => {
      if (viewedReportId === reportId) setViewedReportId(null)
      queryClient.invalidateQueries({ queryKey: ['lb-reports'] })
    },
  })

  const toggleTf = (tf: string) =>
    setSelectedTfs((prev) => (prev.includes(tf) ? prev.filter((t) => t !== tf) : [...prev, tf]))

  const toggleStrategy = (id: string) =>
    setStrategyIds((prev) => (prev.includes(id) ? prev.filter((s) => s !== id) : [...prev, id]))

  const runJob = () => {
    if (!tickers.length) { setError('Enter at least one ticker'); return }
    if (!strategyIds.length) { setError('Select at least one strategy'); return }
    startMutation.mutate({
      tickers: tickers,
      timeframes: selectedTfs.length ? selectedTfs : ['1d'],
      asset_class: assetClass,
      strategy_ids: strategyIds,
      bars,
      forward_bars: forwardBars,
    })
  }

  const job = jobQuery.data as { status?: string; progress?: number; progress_note?: string; result?: LeaderboardResult; error?: string } | undefined
  const running = job?.status === 'running'
  const liveResult = job?.status === 'done' ? job.result : undefined
  const viewedReport = reportDetailQuery.data as { name?: string; payload?: LeaderboardResult; error?: string } | undefined

  const result: LeaderboardResult | undefined = viewedReportId != null ? viewedReport?.payload : liveResult

  return (
    <div className="space-y-4">
      <Card>
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField label="Tickers">
            <AssetClassTickerPicker
              key={assetClass}
              assetClass={assetClass}
              showDurations={false}
              onChange={(v: TickerPickerValue) => setTickers(v.tickers)}
            />
          </FormField>
          <div className="space-y-3">
            <div>
              <p className="mb-2 text-xs font-medium uppercase tracking-wider text-slate-500">
                Timeframes (used by TF-flexible strategies only)
              </p>
              <div className="flex flex-wrap gap-2">
                {TFS.map((tf) => (
                  <Chip key={tf} selected={selectedTfs.includes(tf)} onClick={() => toggleTf(tf)}>{tf}</Chip>
                ))}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <FormField label="History bars">
                <Input type="number" min={150} max={2000} step={50} value={bars} onChange={(e) => setBars(Number(e.target.value))} />
              </FormField>
              <FormField label="Forward bars (target window)">
                <Input type="number" min={3} max={60} value={forwardBars} onChange={(e) => setForwardBars(Number(e.target.value))} />
              </FormField>
            </div>
          </div>
        </div>

        <div className="mt-4">
          <FormField label={`Strategies (${strategyIds.length} of ${catalog.length} selected)`}>
            <div className="max-h-56 space-y-3 overflow-y-auto rounded-xl border border-slate-800/60 bg-slate-800/20 p-3">
              {[...catalogByHub.entries()].map(([hub, strategies]) => (
                <div key={hub}>
                  <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500">{hub}</p>
                  <div className="flex flex-wrap gap-2">
                    {strategies.map((s) => (
                      <Chip key={s.id} selected={strategyIds.includes(s.id)} onClick={() => toggleStrategy(s.id)}>
                        {s.label}
                      </Chip>
                    ))}
                  </div>
                </div>
              ))}
              {!catalog.length && <p className="text-sm text-slate-500">Loading strategy catalog…</p>}
            </div>
            <div className="mt-2 flex flex-wrap gap-2">
              <Button variant="secondary" size="sm" onClick={() => setStrategyIds(catalog.map((s) => s.id))}>
                Select all
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setStrategyIds([])}>Clear</Button>
            </div>
          </FormField>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button onClick={runJob} disabled={running}>
            <span className="inline-flex items-center gap-1.5">
              <Play size={14} />
              {running ? 'Running…' : `Run leaderboard (${tickers.length} × ${strategyIds.length} strategies)`}
            </span>
          </Button>
          <Button variant="secondary" onClick={() => setShowReports((v) => !v)}>
            <span className="inline-flex items-center gap-1.5">
              <FolderOpen size={14} />
              Saved reports {reports.length ? `(${reports.length})` : ''}
            </span>
          </Button>
        </div>
        {error && <div className="mt-3"><Alert type="error">{error}</Alert></div>}
      </Card>

      {showReports && (
        <Card>
          <div className="mb-2 flex items-center justify-between">
            <h4 className="font-medium text-white">Saved reports</h4>
            <button onClick={() => setShowReports(false)} className="text-slate-500 hover:text-slate-300">
              <X size={16} />
            </button>
          </div>
          {reportsQuery.isLoading && <Loading message="Loading saved reports…" />}
          {!reportsQuery.isLoading && !reports.length && (
            <p className="text-sm text-slate-500">No saved reports yet. Run a leaderboard and save the result.</p>
          )}
          <div className="space-y-2">
            {reports.map((r) => (
              <div
                key={r.id}
                className={`flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2 text-sm ${
                  viewedReportId === r.id ? 'border-teal-500/50 bg-teal-500/5' : 'border-slate-800/60 bg-slate-900/40'
                }`}
              >
                <div>
                  <button
                    className="font-medium text-slate-200 hover:text-teal-400"
                    onClick={() => { setViewedReportId(r.id); setJobId(null) }}
                  >
                    {r.name}
                  </button>
                  <p className="text-xs text-slate-500">
                    {r.tickers.join(', ')} · {r.timeframes.join(', ')} · {r.asset_class} · {new Date(r.created_at).toLocaleString()}
                  </p>
                </div>
                <Button variant="ghost" size="sm" onClick={() => deleteMutation.mutate(r.id)}>
                  <Trash2 size={14} />
                </Button>
              </div>
            ))}
          </div>
        </Card>
      )}

      {running && (
        <Card>
          <p className="mb-2 text-sm text-slate-300">{job?.progress_note || 'Starting…'}</p>
          <div className="h-2 w-full overflow-hidden rounded-full bg-slate-800">
            <div
              className="h-full rounded-full bg-teal-500 transition-all"
              style={{ width: `${Math.round((job?.progress ?? 0) * 100)}%` }}
            />
          </div>
          <p className="mt-1 text-xs text-slate-500">{Math.round((job?.progress ?? 0) * 100)}% complete</p>
        </Card>
      )}

      {job?.status === 'error' && <Alert type="error">{job.error}</Alert>}
      {result?.error && <Alert type="error">{result.error}</Alert>}

      {result && !result.error && (
        <LeaderboardResults
          data={result}
          reportName={viewedReportId != null ? viewedReport?.name : undefined}
          onSave={viewedReportId == null ? () => setShowSaveForm(true) : undefined}
        />
      )}

      {showSaveForm && result && (
        <Card>
          <FormField label="Report name">
            <div className="flex gap-2">
              <Input
                value={saveName}
                onChange={(e) => setSaveName(e.target.value)}
                placeholder={`${(result.tickers ?? []).join('+')} leaderboard — ${new Date().toLocaleDateString()}`}
              />
              <Button
                onClick={() => saveMutation.mutate({ name: saveName.trim() || `Leaderboard ${new Date().toLocaleString()}`, payload: result as unknown as Record<string, unknown> })}
                disabled={saveMutation.isPending}
              >
                <span className="inline-flex items-center gap-1.5"><Save size={14} />Save</span>
              </Button>
              <Button variant="ghost" onClick={() => setShowSaveForm(false)}>Cancel</Button>
            </div>
          </FormField>
        </Card>
      )}
      {saveMsg && <Alert type="success">{saveMsg}</Alert>}
    </div>
  )
}

function LeaderboardResults({
  data,
  reportName,
  onSave,
}: {
  data: LeaderboardResult
  reportName?: string
  onSave?: () => void
}) {
  const rows = data.rows ?? []
  const best = data.best_per_ticker ?? []
  const { sorted, sortKey, sortDir, handleSort } = useSort(rows, {
    ticker: (r) => r.ticker,
    strategy: (r) => r.strategy_label,
    hub: (r) => r.hub,
    tf: (r) => r.timeframe,
    signals: (r) => r.total_signals,
    win_rate: (r) => r.overall_win_rate_pct,
    avg_return: (r) => r.avg_forward_return_pct,
    rank_score: (r) => r.rank_score,
  })

  return (
    <div className="space-y-4">
      <Card>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="font-semibold text-white">
              {reportName ? reportName : 'Leaderboard result'}
            </h3>
            <p className="text-sm text-slate-400">
              {(data.tickers ?? []).join(', ')} · {(data.timeframes ?? []).join(', ')} · {data.market ?? data.asset_class} ·{' '}
              {data.bars} bars, {data.forward_bars}-bar forward window
            </p>
          </div>
          {onSave && (
            <Button variant="secondary" onClick={onSave}>
              <span className="inline-flex items-center gap-1.5"><Save size={14} />Save this report</span>
            </Button>
          )}
        </div>

        <p className="mb-2 text-xs font-medium uppercase tracking-wider text-slate-500">Best strategy per ticker</p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {best.map((r) => (
            <div key={r.ticker} className="rounded-lg border border-teal-500/30 bg-teal-500/5 p-3">
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs uppercase tracking-wider text-teal-400">{r.ticker}</p>
                <AddToWatchlistButton ticker={r.ticker} compact />
              </div>
              <p className="mt-1 font-medium text-white">{r.strategy_label}</p>
              <p className="text-xs text-slate-500">{r.hub} · {r.timeframe}</p>
              <div className="mt-2 flex gap-3 text-xs text-slate-400">
                <span>Win rate {fmtPct(r.overall_win_rate_pct)}</span>
                <span>{r.total_signals} signals</span>
              </div>
              {r.thin_sample && (
                <p className="mt-1 text-[11px] text-amber-400">Thin sample — treat with caution ({'<'}30 signals)</p>
              )}
            </div>
          ))}
          {!best.length && (
            <p className="text-sm text-slate-500">No strategy fired enough signals to rank for any ticker in this run.</p>
          )}
        </div>
      </Card>

      <Card>
        <p className="mb-3 text-xs font-medium uppercase tracking-wider text-slate-500">
          All results ({sorted.length} strategy × ticker combinations)
        </p>
        <DataTable>
          <thead>
            <tr>
              <SortableTh active={sortKey === 'ticker'} direction={sortDir} onSort={() => handleSort('ticker')}>Ticker</SortableTh>
              <SortableTh active={sortKey === 'strategy'} direction={sortDir} onSort={() => handleSort('strategy')}>Strategy</SortableTh>
              <SortableTh active={sortKey === 'hub'} direction={sortDir} onSort={() => handleSort('hub')}>Hub</SortableTh>
              <SortableTh active={sortKey === 'tf'} direction={sortDir} onSort={() => handleSort('tf')}>TF</SortableTh>
              <SortableTh active={sortKey === 'signals'} direction={sortDir} onSort={() => handleSort('signals')}>Signals</SortableTh>
              <SortableTh active={sortKey === 'win_rate'} direction={sortDir} onSort={() => handleSort('win_rate')}>Win %</SortableTh>
              <SortableTh active={sortKey === 'avg_return'} direction={sortDir} onSort={() => handleSort('avg_return')}>Avg fwd return</SortableTh>
              <SortableTh active={sortKey === 'rank_score'} direction={sortDir} onSort={() => handleSort('rank_score')}>Rank score</SortableTh>
              <Th>Watch</Th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((r, i) => (
              <tr key={`${r.ticker}-${r.strategy_id}-${i}`}>
                <Td>{r.ticker}</Td>
                <Td className="max-w-[14rem] truncate"><span title={r.notes}>{r.strategy_label}</span></Td>
                <Td className="text-slate-500">{r.hub}</Td>
                <Td>{r.timeframe}</Td>
                <Td>
                  {r.total_signals}
                  {r.thin_sample && r.total_signals > 0 && <span className="ml-1 text-[10px] text-amber-400">thin</span>}
                </Td>
                <Td>{fmtPct(r.overall_win_rate_pct)}</Td>
                <Td>{fmtPct(r.avg_forward_return_pct, 2)}</Td>
                <Td>{r.error ? <span className="text-rose-400">error</span> : r.rank_score.toFixed(3)}</Td>
                <Td><AddToWatchlistButton ticker={r.ticker} compact /></Td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      </Card>
    </div>
  )
}
