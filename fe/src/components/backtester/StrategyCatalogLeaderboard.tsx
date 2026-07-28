import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Play, Save, Trash2, FolderOpen, X } from 'lucide-react'
import {
  apiErrorMessage,
  deleteBacktesterReport,
  fetchBacktesterLeaderboardCatalog,
  fetchBacktesterLeaderboardJob,
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
  rank_score: number
  thin_sample: boolean
  summary: string | null
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

function fmtPct(v: number | null | undefined, digits = 2): string {
  return typeof v === 'number' && Number.isFinite(v) ? `${v.toFixed(digits)}%` : '—'
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
  const [jobId, setJobId] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [saveName, setSaveName] = useState('')
  const [showSaveForm, setShowSaveForm] = useState(false)
  const [saveMsg, setSaveMsg] = useState('')
  const [viewedReportId, setViewedReportId] = useState<number | null>(null)
  const [showReports, setShowReports] = useState(false)
  const [expandedCats, setExpandedCats] = useState<Set<string>>(new Set())

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

  const jobQuery = useQuery({
    queryKey: ['bt-job', jobId],
    queryFn: () => fetchBacktesterLeaderboardJob(jobId as string),
    enabled: !!jobId,
    refetchInterval: (q) => {
      const status = (q.state.data as { status?: string } | undefined)?.status
      return status === 'running' ? 1500 : false
    },
    refetchIntervalInBackground: true,
  })

  const reportsQuery = useQuery({
    queryKey: ['bt-reports'],
    queryFn: fetchBacktesterReports,
    enabled: showReports,
  })
  const reports = ((reportsQuery.data as { reports?: SavedReportSummary[] } | undefined)?.reports) ?? []

  const reportDetailQuery = useQuery({
    queryKey: ['bt-report', viewedReportId],
    queryFn: () => fetchBacktesterReport(viewedReportId as number),
    enabled: viewedReportId != null,
  })

  const startMutation = useMutation({
    mutationFn: startBacktesterLeaderboardJob,
    onSuccess: (data) => {
      setJobId(data.job_id)
      setViewedReportId(null)
      setError('')
      setSaveMsg('')
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
    if (!tickerList.length) { setError(tickerMode === 'single' ? 'Select a ticker' : 'Enter at least one ticker'); return }
    if (!selectedStrategies.length) { setError('Select at least one strategy'); return }
    startMutation.mutate({
      tickers: tickerList, strategy_ids: selectedStrategies, asset_class: assetClass, timeframe, period,
      bars, forward_bars: forwardBars,
    })
  }

  const job = jobQuery.data as { status?: string; progress?: number; progress_note?: string; result?: BtResult; error?: string } | undefined
  const running = job?.status === 'running'
  const liveResult = job?.status === 'done' ? job.result : undefined
  const viewedReport = reportDetailQuery.data as { name?: string; payload?: BtResult; error?: string } | undefined
  const result: BtResult | undefined = viewedReportId != null ? viewedReport?.payload : liveResult

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

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button onClick={runJob} disabled={running}>
            <span className="inline-flex items-center gap-1.5">
              <Play size={14} />
              {running ? 'Running…' : `${runLabel} (${tickerList.length} × ${selectedStrategies.length} strategies)`}
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
                    {r.tickers.join(', ')} · {r.asset_class} · {new Date(r.created_at).toLocaleString()}
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
        <BacktesterResults
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
      {saveMsg && <Alert type="success">{saveMsg}</Alert>}
    </div>
  )
}

function BacktesterResults({
  data,
  reportName,
  onSave,
}: {
  data: BtResult
  reportName?: string
  onSave?: () => void
}) {
  const rows = data.rows ?? []
  const best = data.best_per_ticker ?? []
  const { sorted, sortKey, sortDir, handleSort } = useSort(rows, {
    ticker: (r) => r.ticker,
    strategy: (r) => r.strategy_label,
    category: (r) => r.category,
    trades: (r) => r.num_trades,
    win_rate: (r) => r.win_rate_pct,
    total_return: (r) => r.total_return_pct,
    drawdown: (r) => r.max_drawdown_pct,
    rank_score: (r) => r.rank_score,
  }, 'rank_score', 'desc')

  return (
    <div className="space-y-4">
      <Card>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="font-semibold text-white">{reportName || 'Backtest leaderboard result'}</h3>
            <p className="text-sm text-slate-400">
              {(data.tickers ?? []).join(', ')} · {data.strategy_count} strategies · {data.asset_class} · {data.period}
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
              <p className="text-xs text-slate-500">{r.category} · {r.timeframe}</p>
              <div className="mt-2 flex gap-3 text-xs text-slate-400">
                <span>Return {fmtPct(r.total_return_pct)}</span>
                <span>Win {fmtPct(r.win_rate_pct, 0)}</span>
                <span>{r.num_trades} trades</span>
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
            </div>
          ))}
          {!best.length && (
            <p className="text-sm text-slate-500">No strategy produced a completed trade for any ticker in this run.</p>
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
              <SortableTh active={sortKey === 'category'} direction={sortDir} onSort={() => handleSort('category')}>Category</SortableTh>
              <SortableTh active={sortKey === 'trades'} direction={sortDir} onSort={() => handleSort('trades')}>Trades</SortableTh>
              <SortableTh active={sortKey === 'win_rate'} direction={sortDir} onSort={() => handleSort('win_rate')}>Win %</SortableTh>
              <SortableTh active={sortKey === 'total_return'} direction={sortDir} onSort={() => handleSort('total_return')}>Total Return</SortableTh>
              <SortableTh active={sortKey === 'drawdown'} direction={sortDir} onSort={() => handleSort('drawdown')}>Max DD</SortableTh>
              <SortableTh active={sortKey === 'rank_score'} direction={sortDir} onSort={() => handleSort('rank_score')}>Rank score</SortableTh>
              <Th>Watch</Th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((r, i) => (
              <tr key={`${r.ticker}-${r.strategy_id}-${i}`}>
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
                <Td>{r.error ? '—' : r.rank_score.toFixed(3)}</Td>
                <Td><AddToWatchlistButton ticker={r.ticker} compact /></Td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      </Card>
    </div>
  )
}
