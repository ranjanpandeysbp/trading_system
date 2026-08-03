import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { FolderOpen, Save, Trash2, X } from 'lucide-react'
import {
  apiErrorMessage,
  deleteBestMfReport,
  fetchBestMfJob,
  fetchBestMfJobs,
  fetchBestMfOptions,
  fetchBestMfReport,
  fetchBestMfReports,
  fetchMutualFundAmcs,
  runBestMf,
  saveBestMfReport,
  startBestMfJob,
  type BestMfOption,
  type MutualFundAmc,
} from '../api/client'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Chip } from '../components/ui/Chip'
import { FormField, Input, Select } from '../components/ui/Form'
import { Alert, Loading } from '../components/ui/Feedback'
import { DataTable, SortableTh, Td, useSort } from '../components/ui/Table'
import { CollapsibleScrollSection } from '../components/command-center/CollapsibleScrollSection'

interface BestMfRow {
  rank: number
  scheme_id: number | string
  scheme_name: string
  amc_id: number
  amc_name: string
  category: string
  nav: number | null
  return_pct: number
  aum_cr: number | null
}

interface BestMfResult {
  error?: string
  amc_ids?: number[]
  asset_type_id?: number
  category_filter?: string | null
  rank_period?: number
  universe_count?: number
  top?: BestMfRow[]
  generated_at?: string
}

interface SavedReportSummary {
  id: number
  name: string
  top_scheme_names: string[]
  created_at: string
  summary?: {
    universe_count?: number
    category_filter?: string | null
    rank_period?: number
    asset_type_id?: number
    best_scheme?: string | null
    best_return_pct?: number | null
  }
}

interface BgJobStatus {
  job_id: string
  status: string
  progress?: number
  progress_note?: string
  name?: string | null
  report_id?: number | null
  error?: string | null
  result?: BestMfResult
  meta?: {
    amc_count?: number
    asset_type_id?: number
    category_filter?: string | null
    rank_period?: number
  }
  created_at?: number
}

function amcKey(a: MutualFundAmc): number {
  return Number(a.ID ?? a.Id)
}

function fmtPct(v: number | null | undefined, digits = 2): string {
  return typeof v === 'number' && Number.isFinite(v) ? `${v.toFixed(digits)}%` : '—'
}

function fmtAum(v: number | null | undefined): string {
  return typeof v === 'number' && Number.isFinite(v) ? v.toLocaleString('en-IN', { maximumFractionDigits: 0 }) : '—'
}

function formatWhen(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

export default function BestMf() {
  const queryClient = useQueryClient()

  const [amcFilter, setAmcFilter] = useState('')
  const [selectedAmcIds, setSelectedAmcIds] = useState<number[]>([])
  const [assetTypeId, setAssetTypeId] = useState(1)
  const [categoryFilter, setCategoryFilter] = useState('')
  const [rankPeriod, setRankPeriod] = useState(365)
  const [topN, setTopN] = useState(30)

  const [runInBackground, setRunInBackground] = useState(false)
  const [bgReportName, setBgReportName] = useState('')
  const [bgJobIds, setBgJobIds] = useState<string[]>([])
  const [bgError, setBgError] = useState('')
  const [bgMsg, setBgMsg] = useState('')
  const [saveName, setSaveName] = useState('')
  const [showSaveForm, setShowSaveForm] = useState(false)
  const [saveMsg, setSaveMsg] = useState('')
  const [viewedReportId, setViewedReportId] = useState<number | null>(null)
  const handledDoneRef = useRef<Set<string>>(new Set())

  const amcsQuery = useQuery({ queryKey: ['best-mf-amcs'], queryFn: fetchMutualFundAmcs })
  const amcs = amcsQuery.data?.amcs ?? []
  const filteredAmcs = useMemo(() => {
    const q = amcFilter.trim().toLowerCase()
    if (!q) return amcs
    return amcs.filter((a) => a.Name.toLowerCase().includes(q))
  }, [amcs, amcFilter])

  const optionsQuery = useQuery({ queryKey: ['best-mf-options'], queryFn: fetchBestMfOptions })
  const assetTypes = optionsQuery.data?.asset_types ?? []
  const returnPeriods = optionsQuery.data?.return_periods ?? []
  const categoryHints = (optionsQuery.data?.category_hints ?? {})[String(assetTypeId)] ?? []

  const reportsQuery = useQuery({ queryKey: ['best-mf-reports'], queryFn: fetchBestMfReports })
  const reports = ((reportsQuery.data as { reports?: SavedReportSummary[] } | undefined)?.reports) ?? []

  const runningJobsQuery = useQuery({
    queryKey: ['best-mf-jobs-running'],
    queryFn: () => fetchBestMfJobs('running'),
    refetchInterval: 2000,
  })
  const recentJobsQuery = useQuery({
    queryKey: ['best-mf-jobs-recent'],
    queryFn: () => fetchBestMfJobs('all'),
  })
  const recentJobs = ((recentJobsQuery.data as { jobs?: BgJobStatus[] } | undefined)?.jobs) ?? []
  const recentFinished = recentJobs.filter((j) => j.status !== 'running').slice(0, 8)

  useEffect(() => {
    const serverJobs = ((runningJobsQuery.data as { jobs?: BgJobStatus[] } | undefined)?.jobs) ?? []
    const ids = serverJobs.map((j) => j.job_id)
    if (!ids.length) return
    setBgJobIds((prev) => Array.from(new Set([...ids, ...prev])))
  }, [runningJobsQuery.data])

  const jobQueries = useQueries({
    queries: bgJobIds.map((id) => ({
      queryKey: ['best-mf-job', id],
      queryFn: () => fetchBestMfJob(id) as Promise<BgJobStatus>,
      refetchInterval: (q: { state: { data?: BgJobStatus } }) =>
        q.state.data?.status === 'running' ? 1500 : false,
      refetchIntervalInBackground: true,
      retry: false,
    })),
  })
  const jobById = useMemo(() => {
    const map = new Map<string, BgJobStatus>()
    jobQueries.forEach((q, i) => {
      const id = bgJobIds[i]
      if (id && q.data) map.set(id, q.data as BgJobStatus)
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
    if (stillRunning.length !== bgJobIds.length) setBgJobIds(stillRunning)
    if (changed) {
      queryClient.invalidateQueries({ queryKey: ['best-mf-reports'] })
      queryClient.invalidateQueries({ queryKey: ['best-mf-jobs-running'] })
      queryClient.invalidateQueries({ queryKey: ['best-mf-jobs-recent'] })
    }
  }, [bgJobIds, jobById, queryClient])

  const ongoingBg = bgJobIds
    .map((id) => jobById.get(id))
    .filter((j): j is BgJobStatus => !!j && j.status === 'running')
  const serverRunning = ((runningJobsQuery.data as { jobs?: BgJobStatus[] } | undefined)?.jobs) ?? []
  const ongoingMap = new Map<string, BgJobStatus>()
  for (const j of [...serverRunning, ...ongoingBg]) {
    if (j.status === 'running') ongoingMap.set(j.job_id, j)
  }
  const ongoingList = Array.from(ongoingMap.values()).sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0))

  const reportDetailQuery = useQuery({
    queryKey: ['best-mf-report', viewedReportId],
    queryFn: () => fetchBestMfReport(viewedReportId as number),
    enabled: viewedReportId != null,
  })

  const runMutation = useMutation({
    mutationFn: () => {
      if (!selectedAmcIds.length) throw new Error('Select at least one AMC')
      return runBestMf({
        amc_ids: selectedAmcIds,
        asset_type_id: assetTypeId,
        category_filter: categoryFilter.trim(),
        rank_period: rankPeriod,
        top_n: topN,
      })
    },
  })

  const startBgMutation = useMutation({
    mutationFn: startBestMfJob,
    onSuccess: (data) => {
      const id = data.job_id as string
      setBgError('')
      setBgMsg(`Background run started${data.name ? `: ${data.name}` : ''}.`)
      setBgReportName('')
      setBgJobIds((prev) => Array.from(new Set([id, ...prev])))
      queryClient.invalidateQueries({ queryKey: ['best-mf-jobs-running'] })
    },
    onError: (e) => setBgError(apiErrorMessage(e)),
  })

  const saveReportMutation = useMutation({
    mutationFn: saveBestMfReport,
    onSuccess: () => {
      setSaveMsg('Report saved.')
      setShowSaveForm(false)
      setSaveName('')
      queryClient.invalidateQueries({ queryKey: ['best-mf-reports'] })
    },
    onError: (e) => setBgError(apiErrorMessage(e)),
  })

  const deleteReportMutation = useMutation({
    mutationFn: deleteBestMfReport,
    onSuccess: (_data, reportId) => {
      if (viewedReportId === reportId) setViewedReportId(null)
      queryClient.invalidateQueries({ queryKey: ['best-mf-reports'] })
    },
  })

  const toggleAmc = (id: number) => {
    setSelectedAmcIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  const startBackgroundRun = () => {
    if (!selectedAmcIds.length) {
      setBgError('Select at least one AMC')
      return
    }
    if (!bgReportName.trim()) {
      setBgError('Enter a report name for the background run')
      return
    }
    setBgError('')
    setBgMsg('')
    startBgMutation.mutate({
      amc_ids: selectedAmcIds,
      asset_type_id: assetTypeId,
      category_filter: categoryFilter.trim(),
      rank_period: rankPeriod,
      top_n: topN,
      run_in_background: true,
      report_name: bgReportName.trim(),
    })
  }

  const viewedReport = reportDetailQuery.data as { name?: string; payload?: BestMfResult; created_at?: string; error?: string } | undefined
  const liveResult = runMutation.data as BestMfResult | undefined
  const result: BestMfResult | undefined = viewedReportId != null ? viewedReport?.payload : liveResult

  const rows = result?.top ?? []
  const { sorted, sortKey, sortDir, handleSort } = useSort(rows, {
    rank: (r) => r.rank,
    scheme: (r) => r.scheme_name,
    amc: (r) => r.amc_name,
    category: (r) => r.category,
    return_pct: (r) => r.return_pct,
    nav: (r) => r.nav,
    aum: (r) => r.aum_cr,
  }, 'rank', 'asc')

  return (
    <div>
      <PageHeader
        title="Best MF"
        description="Pick one or more AMCs and an asset class, optionally narrow to a category, and rank schemes by trailing NAV return — run live or as a named background job."
      />

      <div className="space-y-4">
        <Card>
          <FormField label={`AMCs (${selectedAmcIds.length} selected)`}>
            <input
              className="mb-2 w-full max-w-md rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
              placeholder="Filter by name…"
              value={amcFilter}
              onChange={(e) => setAmcFilter(e.target.value)}
            />
            <div className="mb-2 flex flex-wrap gap-2">
              <Button variant="ghost" size="sm" onClick={() => setSelectedAmcIds(filteredAmcs.map(amcKey))}>
                Select all {amcFilter ? '(filtered)' : ''}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setSelectedAmcIds([])} disabled={!selectedAmcIds.length}>
                Clear
              </Button>
            </div>
            {amcsQuery.isLoading && <Loading message="Loading AMCs…" />}
            <div className="max-h-56 overflow-y-auto rounded-lg border border-slate-800/60 bg-slate-900/30 p-2">
              <div className="flex flex-wrap gap-1.5">
                {filteredAmcs.map((a) => {
                  const id = amcKey(a)
                  return (
                    <Chip key={id} selected={selectedAmcIds.includes(id)} onClick={() => toggleAmc(id)}>
                      {a.Name}
                    </Chip>
                  )
                })}
              </div>
            </div>
          </FormField>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <FormField label="Asset class">
              <Select value={assetTypeId} onChange={(e) => setAssetTypeId(Number(e.target.value))}>
                {(assetTypes.length ? assetTypes : [{ value: 1, label: 'Equity' }]).map((o: BestMfOption) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </Select>
            </FormField>
            <FormField label="Rank by trailing return">
              <Select value={rankPeriod} onChange={(e) => setRankPeriod(Number(e.target.value))}>
                {(returnPeriods.length ? returnPeriods : [{ value: 365, label: '1 Year' }]).map((o: BestMfOption) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </Select>
            </FormField>
            <FormField label="Top N funds">
              <Input type="number" min={1} max={100} value={topN} onChange={(e) => setTopN(Number(e.target.value))} />
            </FormField>
            <FormField label="Category filter (optional)">
              <Input
                value={categoryFilter}
                onChange={(e) => setCategoryFilter(e.target.value)}
                placeholder="e.g. Flexi Cap, Credit Risk…"
              />
            </FormField>
          </div>

          {categoryHints.length > 0 && (
            <div className="-mt-2 mb-4 flex flex-wrap gap-1.5">
              {categoryHints.map((hint) => (
                <Chip key={hint} selected={categoryFilter === hint} onClick={() => setCategoryFilter(categoryFilter === hint ? '' : hint)}>
                  {hint}
                </Chip>
              ))}
            </div>
          )}

          <div className="flex flex-wrap items-center gap-3">
            <Button
              onClick={() => runMutation.mutate()}
              disabled={runMutation.isPending || runInBackground}
            >
              {runMutation.isPending ? 'Ranking…' : `Rank funds (${selectedAmcIds.length} AMC(s))`}
            </Button>
          </div>
          {runMutation.isError && <div className="mt-3"><Alert type="error">{apiErrorMessage(runMutation.error)}</Alert></div>}

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
                      placeholder={`Best ${(assetTypes.find((a) => a.value === assetTypeId)?.label) || 'MF'} · ${new Date().toLocaleDateString()}`}
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
                    {job.meta?.amc_count != null ? `${job.meta.amc_count} AMC(s)` : ''}
                    {job.meta?.category_filter ? ` · ${job.meta.category_filter}` : ''}
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
                      <button className="font-medium text-slate-200 hover:text-teal-400" onClick={() => setViewedReportId(job.report_id as number)}>
                        {job.name || 'Untitled background run'}
                      </button>
                    ) : (
                      <span className="font-medium text-slate-200">{job.name || 'Untitled background run'}</span>
                    )}
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
            <p className="text-sm text-slate-500">No saved reports yet. Run a ranking and save it, or start a named background run.</p>
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
                    <button className="font-medium text-slate-200 hover:text-teal-400" onClick={() => setViewedReportId(r.id)}>
                      {r.name}
                    </button>
                    <p className="mt-0.5 text-xs text-slate-500">
                      Saved {formatWhen(r.created_at)}
                      {s?.category_filter ? ` · ${s.category_filter}` : ''}
                      {s?.universe_count != null ? ` · ${s.universe_count} schemes scanned` : ''}
                    </p>
                    {s?.best_scheme && (
                      <p className="mt-1 text-xs text-teal-400/90">
                        Best: {s.best_scheme}{s.best_return_pct != null ? ` · ${fmtPct(s.best_return_pct)}` : ''}
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

        {runMutation.isPending && <Loading message="Ranking funds across selected AMC(s)…" />}

        {result && (
          <Card>
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <div>
                {viewedReportId != null && viewedReport?.name ? (
                  <p className="text-sm text-slate-400">
                    Viewing saved report: <span className="text-slate-200">{viewedReport.name}</span>
                    {viewedReport.created_at ? ` · saved ${formatWhen(viewedReport.created_at)}` : ''}
                  </p>
                ) : (
                  <p className="text-sm text-slate-400">
                    {result.universe_count ?? 0} schemes scanned
                    {result.category_filter ? ` · filtered to "${result.category_filter}"` : ''}
                  </p>
                )}
              </div>
              <div className="flex gap-2">
                {viewedReportId == null && !result.error && (
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
                      placeholder={`Best ${(assetTypes.find((a) => a.value === assetTypeId)?.label) || 'MF'} — ${new Date().toLocaleDateString()}`}
                    />
                    <Button
                      onClick={() => saveReportMutation.mutate({
                        name: saveName.trim() || `Best MF ${new Date().toLocaleString()}`,
                        payload: result as unknown as Record<string, unknown>,
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

            {result.error ? (
              <Alert type="error">{result.error}</Alert>
            ) : (
              <CollapsibleScrollSection
                title="Ranked funds"
                subtitle={`${rows.length} shown · scroll or collapse`}
                open
                onToggle={() => {}}
                maxHeightClass="max-h-[70vh]"
              >
                <DataTable minWidth={800}>
                  <thead>
                    <tr>
                      <SortableTh active={sortKey === 'rank'} direction={sortDir} onSort={() => handleSort('rank')}>Rank</SortableTh>
                      <SortableTh active={sortKey === 'scheme'} direction={sortDir} onSort={() => handleSort('scheme')}>Scheme</SortableTh>
                      <SortableTh active={sortKey === 'amc'} direction={sortDir} onSort={() => handleSort('amc')}>AMC</SortableTh>
                      <SortableTh active={sortKey === 'category'} direction={sortDir} onSort={() => handleSort('category')}>Category</SortableTh>
                      <SortableTh active={sortKey === 'return_pct'} direction={sortDir} onSort={() => handleSort('return_pct')}>Return</SortableTh>
                      <SortableTh active={sortKey === 'nav'} direction={sortDir} onSort={() => handleSort('nav')}>NAV</SortableTh>
                      <SortableTh active={sortKey === 'aum'} direction={sortDir} onSort={() => handleSort('aum')}>AUM (₹ Cr)</SortableTh>
                    </tr>
                  </thead>
                  <tbody>
                    {sorted.map((r) => (
                      <tr key={`${r.amc_id}-${r.scheme_id}`} className="border-t border-slate-800/80">
                        <Td className="text-slate-500">#{r.rank}</Td>
                        <Td className="font-medium text-slate-100">{r.scheme_name}</Td>
                        <Td className="text-slate-400">{r.amc_name}</Td>
                        <Td className="text-slate-400">{r.category}</Td>
                        <Td className={r.return_pct >= 0 ? 'text-emerald-400' : 'text-rose-400'}>{fmtPct(r.return_pct)}</Td>
                        <Td>{r.nav != null ? r.nav.toFixed(2) : '—'}</Td>
                        <Td>{fmtAum(r.aum_cr)}</Td>
                      </tr>
                    ))}
                  </tbody>
                </DataTable>
              </CollapsibleScrollSection>
            )}
          </Card>
        )}
      </div>
    </div>
  )
}
