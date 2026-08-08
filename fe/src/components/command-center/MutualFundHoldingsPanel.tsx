import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { FolderOpen, Save, Trash2, X } from 'lucide-react'
import {
  apiErrorMessage,
  deleteMutualFundHoldingsReport,
  fetchMutualFundAmcs,
  fetchMutualFundHoldingsJob,
  fetchMutualFundHoldingsJobs,
  fetchMutualFundHoldingsReport,
  fetchMutualFundHoldingsReports,
  fetchMutualFundSchemes,
  runMutualFundHoldingsChange,
  saveMutualFundHoldingsReport,
  startMutualFundHoldingsJob,
  type MutualFundAmc,
  type MutualFundScheme,
} from '../../api/client'
import { CollapsibleScrollSection } from './CollapsibleScrollSection'
import { HoldingsTrendResults, type HoldingsAnalysisResult } from './HoldingsTrendResults'
import { Alert, Loading } from '../ui/Feedback'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { FormField, Input } from '../ui/Form'
import { DataTable, Td, Th } from '../ui/Table'
import { HowToBox } from '../ui/CopyAllButton'

const MF_HOW_TO = `Mutual Fund Holdings — How this works

1. Load All AMCs — Indian mutual fund houses with AUM and scheme counts (StockEdge).
2. Pick AMC(s) → Get MF funds — equity schemes (NAV, trailing return, AUM) in a selectable table per AMC.
3. Select funds + date range → Analyze — fetches domestic equity holdings (% of portfolio) at each month-end in the range (disclosures are monthly), then tracks each stock's holding % from first to last snapshot.

Output: Stock-wise and Sector-wise tabs — trend tables and charts across selected funds.

Research / education only — not financial advice.`

interface MfSavedReportSummary {
  id: number
  name: string
  asset_class: string
  scheme_names: string[]
  from_date: string | null
  to_date: string | null
  created_at: string
  summary?: {
    stock_count?: number
    increasing_count?: number
    decreasing_count?: number
    top_increase?: Array<{ stock: string; avg_change_pct: number }>
    top_decrease?: Array<{ stock: string; avg_change_pct: number }>
  }
}

interface MfBgJobStatus {
  job_id: string
  status: string
  progress?: number
  progress_note?: string
  name?: string | null
  report_id?: number | null
  error?: string | null
  result?: HoldingsAnalysisResult
  meta?: {
    scheme_names?: string[]
    from_date?: string
    to_date?: string
  }
  created_at?: number
}

function formatWhen(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

function isoDaysAgo(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() - days)
  return d.toISOString().slice(0, 10)
}

function amcKey(a: MutualFundAmc): number {
  return Number(a.ID ?? a.Id)
}

function schemeKey(s: MutualFundScheme): number {
  return Number(s.ID ?? s.Id)
}

function fmtAum(v: unknown): string {
  if (v == null || v === '') return '—'
  const n = Number(v)
  return Number.isFinite(n) ? n.toLocaleString('en-IN', { maximumFractionDigits: 0 }) : String(v)
}

function fmtPct(v: unknown, digits = 2): string {
  if (v == null || v === '') return '—'
  const n = Number(v)
  return Number.isFinite(n) ? n.toFixed(digits) : String(v)
}

/**
 * Command Center — Mutual Fund Holdings: AMC → equity schemes → stock/sector
 * holding-% trend across selected funds (StockEdge public API via backend).
 */
export function MutualFundHoldingsPanel() {
  const queryClient = useQueryClient()
  const [selectedAmcIds, setSelectedAmcIds] = useState<number[]>([])
  const [schemesByAmc, setSchemesByAmc] = useState<Record<number, MutualFundScheme[]>>({})
  const [selectedSchemeIds, setSelectedSchemeIds] = useState<Record<number, number[]>>({})
  const [fromDate, setFromDate] = useState(isoDaysAgo(180))
  const [toDate, setToDate] = useState(isoDaysAgo(0))
  const [amcFilter, setAmcFilter] = useState('')
  const [showHow, setShowHow] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [amcsOpen, setAmcsOpen] = useState(true)
  const [fundsOpen, setFundsOpen] = useState(true)
  const [resultsOpen, setResultsOpen] = useState(true)
  const [fundSectionOpen, setFundSectionOpen] = useState<Record<number, boolean>>({})

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

  const reportsQuery = useQuery({
    queryKey: ['mf-holdings-reports'],
    queryFn: fetchMutualFundHoldingsReports,
  })
  const reports = ((reportsQuery.data as { reports?: MfSavedReportSummary[] } | undefined)?.reports) ?? []

  const runningJobsQuery = useQuery({
    queryKey: ['mf-holdings-jobs-running'],
    queryFn: () => fetchMutualFundHoldingsJobs('running'),
    refetchInterval: 2000,
  })

  const recentJobsQuery = useQuery({
    queryKey: ['mf-holdings-jobs-recent'],
    queryFn: () => fetchMutualFundHoldingsJobs('all'),
  })
  const recentJobs = ((recentJobsQuery.data as { jobs?: MfBgJobStatus[] } | undefined)?.jobs) ?? []
  const recentFinished = recentJobs.filter((j) => j.status !== 'running').slice(0, 8)

  useEffect(() => {
    const serverJobs = ((runningJobsQuery.data as { jobs?: MfBgJobStatus[] } | undefined)?.jobs) ?? []
    const ids = serverJobs.map((j) => j.job_id)
    if (!ids.length) return
    setBgJobIds((prev) => Array.from(new Set([...ids, ...prev])))
  }, [runningJobsQuery.data])

  const jobQueries = useQueries({
    queries: bgJobIds.map((id) => ({
      queryKey: ['mf-holdings-job', id],
      queryFn: () => fetchMutualFundHoldingsJob(id) as Promise<MfBgJobStatus>,
      refetchInterval: (q: { state: { data?: MfBgJobStatus } }) =>
        q.state.data?.status === 'running' ? 1500 : false,
      refetchIntervalInBackground: true,
      retry: false,
    })),
  })

  const jobById = useMemo(() => {
    const map = new Map<string, MfBgJobStatus>()
    jobQueries.forEach((q, i) => {
      const id = bgJobIds[i]
      if (id && q.data) map.set(id, q.data as MfBgJobStatus)
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
      queryClient.invalidateQueries({ queryKey: ['mf-holdings-reports'] })
      queryClient.invalidateQueries({ queryKey: ['mf-holdings-jobs-running'] })
      queryClient.invalidateQueries({ queryKey: ['mf-holdings-jobs-recent'] })
    }
  }, [bgJobIds, jobById, queryClient])

  const ongoingBg = bgJobIds
    .map((id) => jobById.get(id))
    .filter((j): j is MfBgJobStatus => !!j && j.status === 'running')
  const serverRunning = ((runningJobsQuery.data as { jobs?: MfBgJobStatus[] } | undefined)?.jobs) ?? []
  const ongoingMap = new Map<string, MfBgJobStatus>()
  for (const j of [...serverRunning, ...ongoingBg]) {
    if (j.status === 'running') ongoingMap.set(j.job_id, j)
  }
  const ongoingList = Array.from(ongoingMap.values()).sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0))

  const reportDetailQuery = useQuery({
    queryKey: ['mf-holdings-report', viewedReportId],
    queryFn: () => fetchMutualFundHoldingsReport(viewedReportId as number),
    enabled: viewedReportId != null,
  })

  const startBgMutation = useMutation({
    mutationFn: startMutualFundHoldingsJob,
    onSuccess: (data) => {
      const id = data.job_id as string
      setBgError('')
      setBgMsg(`Background analysis started${data.name ? `: ${data.name}` : ''}.`)
      setBgReportName('')
      setBgJobIds((prev) => Array.from(new Set([id, ...prev])))
      queryClient.invalidateQueries({ queryKey: ['mf-holdings-jobs-running'] })
    },
    onError: (e) => setBgError(apiErrorMessage(e)),
  })

  const saveReportMutation = useMutation({
    mutationFn: saveMutualFundHoldingsReport,
    onSuccess: () => {
      setSaveMsg('Report saved.')
      setShowSaveForm(false)
      setSaveName('')
      queryClient.invalidateQueries({ queryKey: ['mf-holdings-reports'] })
    },
    onError: (e) => setBgError(apiErrorMessage(e)),
  })

  const deleteReportMutation = useMutation({
    mutationFn: deleteMutualFundHoldingsReport,
    onSuccess: (_data, reportId) => {
      if (viewedReportId === reportId) setViewedReportId(null)
      queryClient.invalidateQueries({ queryKey: ['mf-holdings-reports'] })
    },
  })

  const amcsQuery = useQuery({
    queryKey: ['mf-amcs'],
    queryFn: fetchMutualFundAmcs,
    enabled: false,
  })

  const amcs = amcsQuery.data?.amcs ?? []
  const amcNames = useMemo(() => {
    const m = new Map<number, string>()
    for (const a of amcs) m.set(amcKey(a), a.Name)
    return m
  }, [amcs])

  const filteredAmcs = useMemo(() => {
    const q = amcFilter.trim().toLowerCase()
    if (!q) return amcs
    return amcs.filter((a) => a.Name.toLowerCase().includes(q))
  }, [amcs, amcFilter])

  const schemesMutation = useMutation({
    mutationFn: async (amcIds: number[]) => {
      const next: Record<number, MutualFundScheme[]> = { ...schemesByAmc }
      for (const id of amcIds) {
        const res = await fetchMutualFundSchemes(id)
        next[id] = res.schemes ?? []
      }
      return next
    },
    onSuccess: (next) => {
      setSchemesByAmc(next)
      setLoadError('')
    },
    onError: (e) => setLoadError(apiErrorMessage(e)),
  })

  const selectedSchemes = useMemo(() => {
    const out: { id: number; label: string }[] = []
    for (const [amcIdStr, ids] of Object.entries(selectedSchemeIds)) {
      const amcId = Number(amcIdStr)
      const amcName = amcNames.get(amcId) ?? String(amcId)
      const schemes = schemesByAmc[amcId] ?? []
      for (const sid of ids) {
        const scheme = schemes.find((s) => schemeKey(s) === sid)
        out.push({ id: sid, label: `${amcName} — ${scheme?.Name ?? sid}` })
      }
    }
    return out
  }, [selectedSchemeIds, schemesByAmc, amcNames])

  const analyzeMutation = useMutation({
    mutationFn: () => {
      if (!selectedSchemes.length) throw new Error('Select at least one mutual fund')
      if (fromDate > toDate) throw new Error('From date must be on or before To date')
      const scheme_names: Record<string, string> = {}
      for (const s of selectedSchemes) scheme_names[String(s.id)] = s.label
      return runMutualFundHoldingsChange({
        scheme_ids: selectedSchemes.map((s) => s.id),
        scheme_names,
        from_date: fromDate,
        to_date: toDate,
      })
    },
  })

  const toggleAmc = (id: number) => {
    setSelectedAmcIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  const toggleScheme = (amcId: number, schemeId: number) => {
    setSelectedSchemeIds((prev) => {
      const cur = prev[amcId] ?? []
      const has = cur.includes(schemeId)
      const next = has ? cur.filter((x) => x !== schemeId) : [...cur, schemeId]
      return { ...prev, [amcId]: next }
    })
  }

  const selectAllSchemes = (amcId: number, schemes: MutualFundScheme[]) => {
    setSelectedSchemeIds((prev) => ({
      ...prev,
      [amcId]: schemes.map(schemeKey),
    }))
  }

  const clearSchemes = (amcId: number) => {
    setSelectedSchemeIds((prev) => ({ ...prev, [amcId]: [] }))
  }

  const startBackgroundRun = () => {
    if (!selectedSchemes.length) {
      setBgError('Select at least one mutual fund')
      return
    }
    if (fromDate > toDate) {
      setBgError('From date must be on or before To date')
      return
    }
    if (!bgReportName.trim()) {
      setBgError('Enter a report name for the background run')
      return
    }
    const scheme_names: Record<string, string> = {}
    for (const s of selectedSchemes) scheme_names[String(s.id)] = s.label
    setBgError('')
    setBgMsg('')
    startBgMutation.mutate({
      scheme_ids: selectedSchemes.map((s) => s.id),
      scheme_names,
      from_date: fromDate,
      to_date: toDate,
      run_in_background: true,
      report_name: bgReportName.trim(),
    })
  }

  const viewedReport = reportDetailQuery.data as { name?: string; payload?: HoldingsAnalysisResult; created_at?: string; error?: string } | undefined
  const liveAnalysis = analyzeMutation.data as HoldingsAnalysisResult | undefined
  const analysis: HoldingsAnalysisResult | undefined = viewedReportId != null ? viewedReport?.payload : liveAnalysis
  const loadedAmcIds = Object.keys(schemesByAmc).map(Number)

  return (
    <div className="space-y-4">
      <Card>
        <h3 className="text-base font-semibold text-white">
          Mutual Fund Holdings — Stock-Level Trend Across Funds
        </h3>
        <p className="mt-1 text-sm text-slate-400">
          Browse AMCs → pick fund(s) → see whether they&apos;re increasing or decreasing
          individual stock holdings over your chosen date range.
        </p>

        <button
          type="button"
          className="mt-3 text-xs font-medium text-blue-400 hover:text-blue-300"
          onClick={() => setShowHow((v) => !v)}
        >
          {showHow ? 'Hide' : 'How this works'}
        </button>
        {showHow && (
          <HowToBox copyText={MF_HOW_TO} className="mt-2 mb-0">
            <p>
              <strong className="text-slate-300">1. Load All AMCs</strong> — Indian mutual fund houses
              with AUM and scheme counts (StockEdge).
            </p>
            <p>
              <strong className="text-slate-300">2. Pick AMC(s) → Get MF funds</strong> — equity schemes
              (NAV, trailing return, AUM) in a selectable table per AMC.
            </p>
            <p>
              <strong className="text-slate-300">3. Select funds + date range → Analyze</strong> — fetches
              domestic equity holdings (% of portfolio) at each month-end in the range (disclosures are
              monthly), then tracks each stock&apos;s holding % from first to last snapshot.
            </p>
            <p>
              Output: Stock-wise and Sector-wise tabs — trend tables and charts across selected funds.
            </p>
            <p className="text-amber-400/90">Research / education only — not financial advice.</p>
          </HowToBox>
        )}

        <div className="mt-4 flex flex-wrap gap-2">
          <Button
            onClick={() => {
              setLoadError('')
              amcsQuery.refetch().then((r) => {
                if (r.isError) setLoadError(apiErrorMessage(r.error))
              })
            }}
            disabled={amcsQuery.isFetching}
          >
            {amcsQuery.isFetching ? 'Loading AMCs…' : 'Load All AMCs'}
          </Button>
          <Button
            variant="secondary"
            disabled={!selectedAmcIds.length || schemesMutation.isPending}
            onClick={() => schemesMutation.mutate(selectedAmcIds)}
          >
            {schemesMutation.isPending ? 'Fetching schemes…' : 'Get MF funds'}
          </Button>
        </div>

        {(loadError || amcsQuery.isError) && (
          <div className="mt-3">
            <Alert type="error">{loadError || apiErrorMessage(amcsQuery.error)}</Alert>
          </div>
        )}

        {amcs.length > 0 && (
          <div className="mt-4">
            <CollapsibleScrollSection
              title={`AMC list — ${amcs.length} loaded`}
              subtitle={`${selectedAmcIds.length} selected · filter + scroll inside`}
              open={amcsOpen}
              onToggle={() => setAmcsOpen((v) => !v)}
              maxHeightClass="max-h-56"
            >
              <FormField label="Filter AMCs">
                <input
                  className="mb-2 w-full max-w-md rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                  placeholder="Filter by name…"
                  value={amcFilter}
                  onChange={(e) => setAmcFilter(e.target.value)}
                />
                <div className="flex flex-wrap gap-1.5">
                  {filteredAmcs.map((a) => {
                    const id = amcKey(a)
                    return (
                      <Chip key={id} selected={selectedAmcIds.includes(id)} onClick={() => toggleAmc(id)}>
                        {a.Name}
                        {a.AUM != null ? ` · ₹${fmtAum(a.AUM)} Cr` : ''}
                      </Chip>
                    )
                  })}
                </div>
              </FormField>
            </CollapsibleScrollSection>
          </div>
        )}
      </Card>

      {loadedAmcIds.length > 0 && (
        <Card>
          <CollapsibleScrollSection
            title={`Fund schemes — ${selectedSchemes.length} selected`}
            subtitle={`${loadedAmcIds.length} AMC(s) with schemes · collapse to skip scrolling`}
            open={fundsOpen}
            onToggle={() => setFundsOpen((v) => !v)}
            scroll={false}
          >
            <div className="space-y-3">
              {loadedAmcIds.map((amcId) => {
                const schemes = schemesByAmc[amcId] ?? []
                const selected = selectedSchemeIds[amcId] ?? []
                const amcName = amcNames.get(amcId) ?? String(amcId)
                const sectionOpen = fundSectionOpen[amcId] ?? true
                return (
                  <CollapsibleScrollSection
                    key={amcId}
                    title={`${amcName} — ${schemes.length} equity scheme(s)`}
                    subtitle={`${selected.length} selected`}
                    open={sectionOpen}
                    onToggle={() => setFundSectionOpen((prev) => ({ ...prev, [amcId]: !sectionOpen }))}
                    maxHeightClass="max-h-64"
                  >
                    <div className="mb-2 flex flex-wrap gap-2">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => selectAllSchemes(amcId, schemes)}
                        disabled={!schemes.length}
                      >
                        Select all
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => clearSchemes(amcId)}
                        disabled={!selected.length}
                      >
                        Clear
                      </Button>
                    </div>
                    {!schemes.length ? (
                      <p className="text-xs text-slate-500">No schemes found for this AMC.</p>
                    ) : (
                      <DataTable minWidth={720}>
                        <thead>
                          <tr>
                            <Th>Select</Th>
                            <Th>Scheme</Th>
                            <Th>Category</Th>
                            <Th>NAV</Th>
                            <Th>Return %</Th>
                            <Th>AUM (₹ Cr)</Th>
                          </tr>
                        </thead>
                        <tbody>
                          {schemes.map((s) => {
                            const sid = schemeKey(s)
                            const checked = selected.includes(sid)
                            return (
                              <tr key={sid} className="border-t border-slate-800/80">
                                <Td>
                                  <input
                                    type="checkbox"
                                    checked={checked}
                                    onChange={() => toggleScheme(amcId, sid)}
                                  />
                                </Td>
                                <Td className="font-medium text-slate-100">{s.Name}</Td>
                                <Td>{s.Description ?? '—'}</Td>
                                <Td>{fmtPct(s.NAV)}</Td>
                                <Td>{fmtPct(s.Return)}</Td>
                                <Td>{fmtAum(s.AUM)}</Td>
                              </tr>
                            )
                          })}
                        </tbody>
                      </DataTable>
                    )}
                  </CollapsibleScrollSection>
                )
              })}
            </div>

            {selectedSchemes.length > 0 ? (
              <div className="mt-4 space-y-4 border-t border-slate-800 pt-4">
                <p className="max-h-16 overflow-y-auto text-sm text-emerald-400/90">
                  Selected {selectedSchemes.length} fund(s):{' '}
                  <span className="text-slate-300">{selectedSchemes.map((s) => s.label).join(', ')}</span>
                </p>
                <div className="grid gap-4 sm:grid-cols-[1fr_1fr_auto]">
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
                  <div className="flex items-end">
                    <Button
                      className="w-full"
                      onClick={() => {
                        setResultsOpen(true)
                        setViewedReportId(null)
                        analyzeMutation.mutate()
                      }}
                      disabled={analyzeMutation.isPending || runInBackground}
                    >
                      {analyzeMutation.isPending ? 'Analyzing…' : 'Analyze Holding Change'}
                    </Button>
                  </div>
                </div>
                {analyzeMutation.isError && (
                  <Alert type="error">{apiErrorMessage(analyzeMutation.error)}</Alert>
                )}

                <div className="space-y-3 rounded-xl border border-slate-800/60 bg-slate-900/30 p-3">
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
                        Name the run — it keeps going if you leave this page, then auto-saves into Saved
                        reports below when done. You can start several background runs at once.
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
                          placeholder={`${selectedSchemes.slice(0, 2).map((s) => s.label).join(' + ') || 'MF holdings'} · ${fromDate}→${toDate}`}
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
              </div>
            ) : (
              <p className="mt-4 text-sm text-slate-500">Select one or more mutual funds from the table(s) above.</p>
            )}
          </CollapsibleScrollSection>
        </Card>
      )}

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
                  {(job.meta?.scheme_names ?? []).slice(0, 4).join(', ')}
                  {(job.meta?.scheme_names?.length ?? 0) > 4 ? '…' : ''}
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
                    {(job.meta?.scheme_names ?? []).slice(0, 4).join(', ')}
                    {(job.meta?.scheme_names?.length ?? 0) > 4 ? '…' : ''}
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
                    {(r.scheme_names ?? []).slice(0, 6).join(', ')}
                    {(r.scheme_names?.length ?? 0) > 6 ? '…' : ''}
                  </p>
                  {s && (s.increasing_count != null || s.decreasing_count != null) && (
                    <p className="mt-1 text-xs text-teal-400/90">
                      {s.stock_count ?? 0} stocks · {s.increasing_count ?? 0} increasing · {s.decreasing_count ?? 0} decreasing
                      {s.top_increase?.[0] ? ` · top: ${s.top_increase[0].stock} (+${fmtPct(s.top_increase[0].avg_change_pct)}%)` : ''}
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

      {analyzeMutation.isPending && <Loading message="Fetching month-end holdings across selected funds…" />}

      {analysis && !analyzeMutation.isPending && (
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
              {viewedReportId == null && !analysis.error && (
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
                    placeholder={`${selectedSchemes.slice(0, 2).map((s) => s.label).join(' + ') || 'MF holdings'} — ${new Date().toLocaleDateString()}`}
                  />
                  <Button
                    onClick={() => saveReportMutation.mutate({
                      name: saveName.trim() || `MF holdings ${new Date().toLocaleString()}`,
                      payload: analysis as unknown as Record<string, unknown>,
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

          <CollapsibleScrollSection
            title="Analysis results"
            subtitle={analysis.error ? 'Error' : `${analysis.overall?.length ?? 0} stocks · scroll or collapse`}
            open={resultsOpen}
            onToggle={() => setResultsOpen((v) => !v)}
            maxHeightClass="max-h-[70vh]"
          >
            {analysis.error ? (
              <Alert type="error">{analysis.error}</Alert>
            ) : (
              <HoldingsTrendResults
                data={analysis}
                fundNoun="Funds"
                askSection="command-center/mutual_fund_holdings"
                askTitle="Mutual Fund Holdings"
                marketType="india"
                resolveName
              />
            )}
          </CollapsibleScrollSection>
        </Card>
      )}
    </div>
  )
}
