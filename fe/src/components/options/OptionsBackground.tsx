import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { FolderOpen, Trash2 } from 'lucide-react'
import {
  apiErrorMessage,
  deleteOptionsReport,
  fetchOptionsJob,
  fetchOptionsJobs,
  fetchOptionsReport,
  fetchOptionsReports,
  startOptionsJob,
} from '../../api/client'
import { Card } from '../ui/Card'
import { Button } from '../ui/Button'
import { FormField, Input } from '../ui/Form'
import { Alert, Loading } from '../ui/Feedback'

export type OptionsSectionId =
  | 'double_calendar'
  | 'delta_neutral'
  | 'hedging'
  | 'gokul_chhabra'
  | 'zero_to_hero'
  | 'market_prediction'
  | 'call_put_writing'
  | 'profitable'

interface OptionsBgJobStatus {
  job_id: string
  status: 'running' | 'done' | 'error' | string
  progress?: number
  progress_note?: string
  name?: string | null
  report_id?: number | null
  error?: string | null
  created_at?: number
  result?: Record<string, unknown>
}

interface OptionsSavedReport {
  id: number
  name: string
  asset_class: string
  created_at: string
  summary?: {
    result_count?: number
    tickers?: string[]
    symbol?: string
    bias?: string | null
  }
}

function formatWhen(iso: string): string {
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

export function useOptionsBackground(sectionId: OptionsSectionId) {
  const queryClient = useQueryClient()
  const [runInBackground, setRunInBackground] = useState(false)
  const [bgReportName, setBgReportName] = useState('')
  const [bgError, setBgError] = useState('')
  const [bgMsg, setBgMsg] = useState('')
  const [bgJobIds, setBgJobIds] = useState<string[]>([])
  const [viewedReportId, setViewedReportId] = useState<number | null>(null)
  const handledDoneRef = useRef<Set<string>>(new Set())

  useEffect(() => {
    setViewedReportId(null)
    setBgError('')
    setBgMsg('')
    setRunInBackground(false)
    setBgReportName('')
    setBgJobIds([])
    handledDoneRef.current = new Set()
  }, [sectionId])

  const runningJobsQuery = useQuery({
    queryKey: ['options-jobs-running', sectionId],
    queryFn: () => fetchOptionsJobs(sectionId, 'running'),
    refetchInterval: 2500,
    refetchIntervalInBackground: true,
  })

  const recentJobsQuery = useQuery({
    queryKey: ['options-jobs-recent', sectionId],
    queryFn: () => fetchOptionsJobs(sectionId, 'all'),
    refetchInterval: 5000,
  })

  const reportsQuery = useQuery({
    queryKey: ['options-reports', sectionId],
    queryFn: () => fetchOptionsReports(sectionId),
  })

  useEffect(() => {
    const jobs = ((runningJobsQuery.data as { jobs?: OptionsBgJobStatus[] } | undefined)?.jobs) ?? []
    const ids = jobs.map((j) => j.job_id).filter(Boolean)
    if (!ids.length) return
    setBgJobIds((prev) => Array.from(new Set([...ids, ...prev])))
  }, [runningJobsQuery.data])

  const jobQueries = useQueries({
    queries: bgJobIds.map((id) => ({
      queryKey: ['options-job', sectionId, id],
      queryFn: () => fetchOptionsJob(sectionId, id) as Promise<OptionsBgJobStatus>,
      refetchInterval: (q: { state: { data?: OptionsBgJobStatus } }) =>
        q.state.data?.status === 'running' ? 1500 : false,
      refetchIntervalInBackground: true,
      retry: false,
    })),
  })

  const jobById = useMemo(() => {
    const map = new Map<string, OptionsBgJobStatus>()
    jobQueries.forEach((q, i) => {
      const id = bgJobIds[i]
      if (id && q.data) map.set(id, q.data as OptionsBgJobStatus)
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
      queryClient.invalidateQueries({ queryKey: ['options-reports', sectionId] })
      queryClient.invalidateQueries({ queryKey: ['options-jobs-running', sectionId] })
      queryClient.invalidateQueries({ queryKey: ['options-jobs-recent', sectionId] })
    }
  }, [bgJobIds, jobById, queryClient, sectionId])

  const ongoingBg = bgJobIds
    .map((id) => jobById.get(id))
    .filter((j): j is OptionsBgJobStatus => !!j && j.status === 'running')
  const serverRunning = ((runningJobsQuery.data as { jobs?: OptionsBgJobStatus[] } | undefined)?.jobs) ?? []
  const ongoingMap = new Map<string, OptionsBgJobStatus>()
  for (const j of [...serverRunning, ...ongoingBg]) {
    if (j.status === 'running') ongoingMap.set(j.job_id, j)
  }
  const ongoingList = Array.from(ongoingMap.values()).sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0))

  const recentJobs = ((recentJobsQuery.data as { jobs?: OptionsBgJobStatus[] } | undefined)?.jobs) ?? []
  const recentFinished = recentJobs
    .filter((j) => j.status === 'done' || j.status === 'error')
    .slice(0, 8)

  const reportDetailQuery = useQuery({
    queryKey: ['options-report', sectionId, viewedReportId],
    queryFn: () => fetchOptionsReport(sectionId, viewedReportId as number),
    enabled: viewedReportId != null,
  })

  const viewedReport = reportDetailQuery.data as {
    name?: string
    payload?: Record<string, unknown>
    created_at?: string
    error?: string
  } | undefined

  const startMutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) => startOptionsJob(sectionId, payload),
    onSuccess: (data) => {
      const id = data.job_id as string
      setBgError('')
      setBgMsg(`Background run started${data.name ? `: ${data.name}` : ''}.`)
      setBgReportName('')
      setBgJobIds((prev) => Array.from(new Set([id, ...prev])))
      queryClient.invalidateQueries({ queryKey: ['options-jobs-running', sectionId] })
    },
    onError: (e) => setBgError(apiErrorMessage(e)),
  })

  const deleteMutation = useMutation({
    mutationFn: (reportId: number) => deleteOptionsReport(sectionId, reportId),
    onSuccess: (_data, reportId) => {
      if (viewedReportId === reportId) setViewedReportId(null)
      queryClient.invalidateQueries({ queryKey: ['options-reports', sectionId] })
    },
  })

  const reports = ((reportsQuery.data as { reports?: OptionsSavedReport[] } | undefined)?.reports) ?? []

  const startBackground = (payload: Record<string, unknown>, validate?: () => string | null) => {
    const err = validate?.()
    if (err) {
      setBgError(err)
      return
    }
    if (!bgReportName.trim()) {
      setBgError('Enter a report name for the background run')
      return
    }
    setBgError('')
    setBgMsg('')
    startMutation.mutate({
      ...payload,
      run_in_background: true,
      report_name: bgReportName.trim(),
    })
  }

  return {
    runInBackground,
    setRunInBackground,
    bgReportName,
    setBgReportName,
    bgError,
    bgMsg,
    startBackground,
    startPending: startMutation.isPending,
    ongoingList,
    recentFinished,
    reports,
    reportsLoading: reportsQuery.isLoading,
    reportsFetching: reportsQuery.isFetching,
    refetchReports: () => reportsQuery.refetch(),
    viewedReportId,
    setViewedReportId,
    viewedPayload: viewedReportId != null ? viewedReport?.payload : undefined,
    viewedReportMeta: viewedReportId != null ? viewedReport : undefined,
    deleteReport: (id: number, name: string) => {
      if (window.confirm(`Delete saved report "${name}"? This cannot be undone.`)) {
        deleteMutation.mutate(id)
      }
    },
  }
}

type BgHook = ReturnType<typeof useOptionsBackground>

export function OptionsBackgroundControls({
  bg,
  onStart,
  placeholder,
}: {
  bg: BgHook
  onStart: () => void
  placeholder?: string
}) {
  return (
    <div className="mt-4 space-y-3 rounded-xl border border-slate-800/60 bg-slate-900/30 p-3">
      <label className="flex cursor-pointer items-start gap-3 text-sm text-slate-300">
        <input
          type="checkbox"
          className="mt-1 h-4 w-4 rounded border-slate-600 bg-slate-800 text-teal-500"
          checked={bg.runInBackground}
          onChange={(e) => bg.setRunInBackground(e.target.checked)}
        />
        <span>
          <span className="font-medium text-slate-100">Run in background</span>
          <span className="mt-0.5 block text-xs text-slate-500">
            Name the run — it keeps going if you leave this page, then auto-saves into Saved
            reports below when done. You can start several background runs at once.
          </span>
        </span>
      </label>
      {bg.runInBackground && (
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-[16rem] flex-1">
            <FormField label="Report name">
              <Input
                value={bg.bgReportName}
                onChange={(e) => bg.setBgReportName(e.target.value)}
                placeholder={placeholder || `Options · ${new Date().toLocaleDateString()}`}
                maxLength={200}
              />
            </FormField>
          </div>
          <Button onClick={onStart} disabled={bg.startPending}>
            {bg.startPending ? 'Starting…' : 'Start background run'}
          </Button>
        </div>
      )}
      {bg.bgError && <Alert type="error">{bg.bgError}</Alert>}
      {bg.bgMsg && <Alert type="success">{bg.bgMsg}</Alert>}
    </div>
  )
}

export function OptionsBackgroundJobsAndReports({ bg }: { bg: BgHook }) {
  return (
    <>
      {bg.ongoingList.length > 0 && (
        <Card className="mb-4">
          <h4 className="mb-3 font-medium text-white">Background runs in progress ({bg.ongoingList.length})</h4>
          <div className="space-y-3">
            {bg.ongoingList.map((job) => (
              <div key={job.job_id} className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="font-medium text-amber-100">{job.name || 'Untitled background run'}</p>
                  <p className="text-xs text-slate-500">{Math.round((job.progress ?? 0) * 100)}%</p>
                </div>
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

      {bg.recentFinished.length > 0 && (
        <Card className="mb-4">
          <h4 className="mb-3 font-medium text-white">Recent background runs</h4>
          <div className="space-y-2">
            {bg.recentFinished.map((job) => (
              <div
                key={job.job_id}
                className={`flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2 text-sm ${
                  job.status === 'error' ? 'border-rose-500/30 bg-rose-500/5' : 'border-slate-800/60 bg-slate-900/40'
                }`}
              >
                <div>
                  {job.status === 'done' && job.report_id ? (
                    <button
                      type="button"
                      className="font-medium text-slate-200 hover:text-teal-400"
                      onClick={() => bg.setViewedReportId(job.report_id as number)}
                    >
                      {job.name || 'Untitled background run'}
                    </button>
                  ) : (
                    <span className="font-medium text-slate-200">{job.name || 'Untitled background run'}</span>
                  )}
                  {job.status === 'error' && (
                    <p className="mt-1 text-xs text-rose-400">{job.error || 'Failed — no further detail available.'}</p>
                  )}
                </div>
                <span
                  className={`text-xs font-medium ${
                    job.status === 'error' ? 'text-rose-400' : job.report_id ? 'text-emerald-400' : 'text-slate-400'
                  }`}
                >
                  {job.status === 'error' ? 'Failed' : job.report_id ? 'Saved' : 'Done (not saved)'}
                </span>
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card className="mb-4">
        <div className="mb-3 flex items-center justify-between gap-2">
          <h4 className="inline-flex items-center gap-2 font-medium text-white">
            <FolderOpen size={16} className="text-slate-400" />
            Saved reports
            <span className="text-sm font-normal text-slate-500">({bg.reports.length})</span>
          </h4>
          <Button variant="ghost" size="sm" onClick={() => bg.refetchReports()} disabled={bg.reportsFetching}>
            Refresh
          </Button>
        </div>
        {bg.reportsLoading && <Loading message="Loading saved reports…" />}
        {!bg.reportsLoading && !bg.reports.length && (
          <p className="text-sm text-slate-500">
            No saved reports yet. Start a named background run to auto-save one here.
          </p>
        )}
        <div className="space-y-2">
          {bg.reports.map((r) => {
            const s = r.summary
            return (
              <div
                key={r.id}
                className={`flex flex-wrap items-start justify-between gap-2 rounded-lg border px-3 py-2.5 text-sm ${
                  bg.viewedReportId === r.id ? 'border-teal-500/50 bg-teal-500/5' : 'border-slate-800/60 bg-slate-900/40'
                }`}
              >
                <div className="min-w-0 flex-1">
                  <button
                    type="button"
                    className="font-medium text-slate-200 hover:text-teal-400"
                    onClick={() => bg.setViewedReportId(r.id)}
                  >
                    {r.name}
                  </button>
                  <p className="mt-0.5 text-xs text-slate-500">Saved {formatWhen(r.created_at)}</p>
                  {s?.result_count != null && (
                    <p className="mt-1 text-xs text-teal-400/90">
                      {s.result_count} result{s.result_count === 1 ? '' : 's'}
                      {s.tickers?.length ? ` · ${s.tickers.slice(0, 4).join(', ')}` : ''}
                      {s.symbol ? ` · ${s.symbol}` : ''}
                      {s.bias ? ` · ${s.bias}` : ''}
                    </p>
                  )}
                </div>
                <Button variant="ghost" size="sm" onClick={() => bg.deleteReport(r.id, r.name)}>
                  <Trash2 size={14} />
                </Button>
              </div>
            )
          })}
        </div>
      </Card>
    </>
  )
}
