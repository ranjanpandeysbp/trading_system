import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, FolderOpen, Save, Trash2 } from 'lucide-react'
import {
  apiErrorMessage,
  deleteSmartMoneyActivityReport,
  fetchEtfHoldingsAmcs,
  fetchEtfHoldingsIssuers,
  fetchEtfHoldingsSchemes,
  fetchEtfIssuerSchemes,
  fetchMutualFundAmcs,
  fetchMutualFundSchemes,
  fetchSmartMoneyActivityJob,
  fetchSmartMoneyActivityJobs,
  fetchSmartMoneyActivityReport,
  fetchSmartMoneyActivityReports,
  runSmartMoneyActivity,
  saveSmartMoneyActivityReport,
  startSmartMoneyActivityJob,
  type EtfIssuer,
  type EtfIssuerScheme,
  type MutualFundAmc,
  type MutualFundScheme,
  type SmartMoneyActivityResult,
  type SmartMoneyActivityRunPayload,
  type SmartMoneyTickerResult,
} from '../../api/client'
import {
  AssetClassTickerPicker,
  type AssetClass,
  type TickerPickerValue,
} from './AssetClassTickerPicker'
import { AddToWatchlistButton } from '../watchlist/AddToWatchlistButton'
import type { WatchlistMarket } from '../watchlist/WatchlistMarketContext'
import { AskAIPanel } from '../ai/AskAIPanel'
import { Alert, Loading } from '../ui/Feedback'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { FormField, Input } from '../ui/Form'
import { DataTable, Td, Th } from '../ui/Table'

interface SmaSavedReportSummary {
  id: number
  name: string
  tickers: string[]
  from_date: string | null
  to_date: string | null
  created_at: string
  summary?: {
    ticker_count?: number
    found_count?: number
    bullish_count?: number
    bearish_count?: number
    wait_count?: number
    tickers?: string[]
  }
}

interface SmaBgJobStatus {
  job_id: string
  status: string
  progress?: number
  progress_note?: string
  name?: string | null
  report_id?: number | null
  error?: string | null
  result?: SmartMoneyActivityResult
  meta?: {
    tickers?: string[]
    asset_class?: string
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

type SourceMode = 'mutual_fund' | 'etf' | 'both'

const PREFERRED_AMC_KEYWORDS = ['SBI', 'HDFC', 'ICICI', 'NIPPON'] as const

function amcKey(a: MutualFundAmc): number {
  return Number(a.ID ?? a.Id)
}

function schemeKey(s: MutualFundScheme): number {
  return Number(s.ID ?? s.Id)
}

function isPreferredAmc(name: string): boolean {
  const n = name.toUpperCase()
  return PREFERRED_AMC_KEYWORDS.some((k) => n.includes(k))
}

function CollapsibleSection({
  title,
  subtitle,
  open,
  onToggle,
  children,
}: {
  title: string
  subtitle?: string
  open: boolean
  onToggle: () => void
  children: ReactNode
}) {
  return (
    <Card>
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center gap-2 text-left"
      >
        {open ? <ChevronDown size={16} className="shrink-0 text-slate-400" /> : <ChevronRight size={16} className="shrink-0 text-slate-400" />}
        <span className="min-w-0 flex-1">
          <span className="block font-medium text-white">{title}</span>
          {subtitle ? <span className="mt-0.5 block text-xs text-slate-500">{subtitle}</span> : null}
        </span>
        <span className="shrink-0 text-xs text-slate-500">{open ? 'Collapse' : 'Expand'}</span>
      </button>
      {open && <div className="mt-3 border-t border-slate-800 pt-3">{children}</div>}
    </Card>
  )
}

function toTradeBias(signal: string, bias: string): 'LONG' | 'SHORT' | 'WAIT' {
  const s = (signal || bias || '').toUpperCase()
  if (s === 'ADD_LONG' || s === 'BULLISH' || s === 'LONG') return 'LONG'
  if (s === 'SELL_AVOID' || s === 'BEARISH' || s === 'SHORT') return 'SHORT'
  return 'WAIT'
}

function signalBadge(signal: string, bias?: string) {
  const trade = toTradeBias(signal, bias ?? '')
  if (trade === 'LONG') {
    return (
      <span className="rounded-md bg-emerald-500/15 px-2 py-0.5 text-xs font-semibold text-emerald-300">
        LONG
      </span>
    )
  }
  if (trade === 'SHORT') {
    return (
      <span className="rounded-md bg-rose-500/15 px-2 py-0.5 text-xs font-semibold text-rose-300">
        SHORT
      </span>
    )
  }
  return (
    <span className="rounded-md bg-slate-500/20 px-2 py-0.5 text-xs font-semibold text-slate-300">
      WAIT
    </span>
  )
}

function ResultRow({
  r,
  market,
  aiSystemPrompt,
}: {
  r: SmartMoneyTickerResult
  market: WatchlistMarket
  aiSystemPrompt: string
}) {
  const [showAi, setShowAi] = useState(false)
  const trade = toTradeBias(r.signal, r.bias)
  const detail =
    r.summary
    || (!r.found
      ? 'Ticker not found in selected fund/ETF holdings for this date range.'
      : 'No clear stake-flow edge.')
  return (
    <>
      <tr className="align-top">
        <Td className="font-medium text-white">{r.ticker}</Td>
        <Td>
          {signalBadge(r.signal, r.bias)}
          {(r.signal === 'ADD_LONG' || r.signal === 'SELL_AVOID') && (
            <div className="mt-1 text-[10px] uppercase tracking-wide text-slate-500">
              {r.signal.replace('_', ' ')}
            </div>
          )}
        </Td>
        <Td className="text-xs text-slate-300">{trade}</Td>
        <Td className="text-xs">{r.found ? (r.overall_trend ?? '—') : 'not found'}</Td>
        <Td className="text-xs tabular-nums">
          {r.avg_change_pct != null ? `${r.avg_change_pct > 0 ? '+' : ''}${r.avg_change_pct.toFixed(3)}%` : '—'}
        </Td>
        <Td className="text-xs">
          {r.schemes_increasing ?? 0}↑ / {r.schemes_decreasing ?? 0}↓
          {r.n_schemes != null ? ` · ${r.n_schemes} funds` : ''}
        </Td>
        <Td className="max-w-md text-xs leading-relaxed text-slate-400" title={detail}>{detail}</Td>
        <Td>
          <div className="flex items-center gap-1">
            <AddToWatchlistButton
              ticker={r.ticker}
              displayName={r.ticker}
              notes={`Smart money · ${trade} · ${r.overall_trend ?? ''} · ${detail}`.slice(0, 240)}
              marketType={market}
              compact
            />
            <Button variant="ghost" size="sm" onClick={() => setShowAi((v) => !v)}>
              {showAi ? 'Hide AI' : 'Ask AI'}
            </Button>
          </div>
        </Td>
      </tr>
      {showAi && (
        <tr>
          <td colSpan={8} className="bg-slate-950/40 px-4 py-3">
            <AskAIPanel
              context={String(r.ai_context ?? '')}
              systemPrompt={aiSystemPrompt}
              section={`command-center/smart-money-activity/${r.ticker}`}
              className="mt-0"
            />
          </td>
        </tr>
      )}
    </>
  )
}

type SchemeKind = 'mf' | 'etf'

/**
 * Command Center — Check Smart Money Activity.
 * Pick fund house(s) → pick fund/ETF(s) → ticker(s) + date range → stake-flow signals.
 */
export function SmartMoneyActivityPanel() {
  const queryClient = useQueryClient()
  const [market, setMarket] = useState<AssetClass>('india')
  const [picker, setPicker] = useState<TickerPickerValue>({ tickers: [], durations: ['1d'] })
  const [source, setSource] = useState<SourceMode>('both')
  const [fromDate, setFromDate] = useState(isoDaysAgo(180))
  const [toDate, setToDate] = useState(isoDaysAgo(0))
  const [error, setError] = useState('')
  const [result, setResult] = useState<SmartMoneyActivityResult | null>(null)

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

  // India fund houses + schemes
  const [selectedAmcIds, setSelectedAmcIds] = useState<number[]>([])
  const [amcFilter, setAmcFilter] = useState('')
  const [mfSchemesByAmc, setMfSchemesByAmc] = useState<Record<number, MutualFundScheme[]>>({})
  const [etfSchemesByAmc, setEtfSchemesByAmc] = useState<Record<number, MutualFundScheme[]>>({})
  const [selectedMfByAmc, setSelectedMfByAmc] = useState<Record<number, number[]>>({})
  const [selectedEtfByAmc, setSelectedEtfByAmc] = useState<Record<number, number[]>>({})

  // US / crypto issuers + ETFs
  const [selectedIssuers, setSelectedIssuers] = useState<string[]>([])
  const [issuerFilter, setIssuerFilter] = useState('')
  const [schemesByIssuer, setSchemesByIssuer] = useState<Record<string, EtfIssuerScheme[]>>({})
  const [selectedByIssuer, setSelectedByIssuer] = useState<Record<string, string[]>>({})
  const [housesOpen, setHousesOpen] = useState(true)
  const [fundsOpen, setFundsOpen] = useState(true)
  const [resultSearch, setResultSearch] = useState('')

  const indiaMarket = market === 'india'
  const usCryptoMarket = market === 'us' || market === 'crypto'

  const mfAmcsQuery = useQuery({
    queryKey: ['sma-mf-amcs'],
    queryFn: fetchMutualFundAmcs,
    enabled: false,
  })
  const etfAmcsQuery = useQuery({
    queryKey: ['sma-etf-amcs'],
    queryFn: fetchEtfHoldingsAmcs,
    enabled: false,
  })
  const issuersQuery = useQuery({
    queryKey: ['sma-etf-issuers', market],
    queryFn: () => fetchEtfHoldingsIssuers(market as 'us' | 'crypto'),
    enabled: false,
  })

  const indiaAmcs = useMemo(() => {
    const wantMf = source === 'mutual_fund' || source === 'both'
    const wantEtf = source === 'etf' || source === 'both'
    const map = new Map<number, MutualFundAmc>()
    if (wantMf) {
      for (const a of mfAmcsQuery.data?.amcs ?? []) map.set(amcKey(a), a)
    }
    if (wantEtf) {
      for (const a of etfAmcsQuery.data?.amcs ?? []) {
        if (!map.has(amcKey(a))) map.set(amcKey(a), a)
      }
    }
    const all = [...map.values()]
    all.sort((a, b) => {
      const ap = isPreferredAmc(a.Name) ? 0 : 1
      const bp = isPreferredAmc(b.Name) ? 0 : 1
      if (ap !== bp) return ap - bp
      return a.Name.localeCompare(b.Name)
    })
    return all
  }, [mfAmcsQuery.data, etfAmcsQuery.data, source])

  const filteredAmcs = useMemo(() => {
    const q = amcFilter.trim().toLowerCase()
    if (!q) return indiaAmcs
    return indiaAmcs.filter((a) => a.Name.toLowerCase().includes(q))
  }, [indiaAmcs, amcFilter])

  const amcNames = useMemo(() => {
    const m = new Map<number, string>()
    for (const a of indiaAmcs) m.set(amcKey(a), a.Name)
    return m
  }, [indiaAmcs])

  const issuers = issuersQuery.data?.issuers ?? []
  const filteredIssuers = useMemo(() => {
    const q = issuerFilter.trim().toLowerCase()
    if (!q) return issuers
    return issuers.filter((a: EtfIssuer) => a.Name.toLowerCase().includes(q))
  }, [issuers, issuerFilter])

  const loadHousesMutation = useMutation({
    mutationFn: async () => {
      if (indiaMarket) {
        const tasks: Promise<unknown>[] = []
        if (source === 'mutual_fund' || source === 'both') tasks.push(mfAmcsQuery.refetch())
        if (source === 'etf' || source === 'both') tasks.push(etfAmcsQuery.refetch())
        await Promise.all(tasks)
        return
      }
      await issuersQuery.refetch()
    },
    onError: (e) => setError(apiErrorMessage(e)),
    onSuccess: () => setError(''),
  })

  const loadFundsMutation = useMutation({
    mutationFn: async () => {
      if (indiaMarket) {
        if (!selectedAmcIds.length) throw new Error('Select at least one fund house')
        const wantMf = source === 'mutual_fund' || source === 'both'
        const wantEtf = source === 'etf' || source === 'both'
        const nextMf: Record<number, MutualFundScheme[]> = { ...mfSchemesByAmc }
        const nextEtf: Record<number, MutualFundScheme[]> = { ...etfSchemesByAmc }
        for (const id of selectedAmcIds) {
          if (wantMf) {
            const res = await fetchMutualFundSchemes(id)
            nextMf[id] = res.schemes ?? []
          }
          if (wantEtf) {
            const res = await fetchEtfHoldingsSchemes(id)
            nextEtf[id] = res.schemes ?? []
          }
        }
        setMfSchemesByAmc(nextMf)
        setEtfSchemesByAmc(nextEtf)
        return
      }
      if (!selectedIssuers.length) throw new Error('Select at least one issuer / fund house')
      const next: Record<string, EtfIssuerScheme[]> = { ...schemesByIssuer }
      for (const name of selectedIssuers) {
        const res = await fetchEtfIssuerSchemes(market as 'us' | 'crypto', name)
        next[name] = res.schemes ?? []
      }
      setSchemesByIssuer(next)
    },
    onError: (e) => setError(apiErrorMessage(e)),
    onSuccess: () => setError(''),
  })

  const selectedMf = useMemo(() => {
    const out: { id: number; label: string }[] = []
    for (const [amcIdStr, ids] of Object.entries(selectedMfByAmc)) {
      const amcId = Number(amcIdStr)
      const amcName = amcNames.get(amcId) ?? String(amcId)
      const schemes = mfSchemesByAmc[amcId] ?? []
      for (const sid of ids) {
        const scheme = schemes.find((s) => schemeKey(s) === sid)
        out.push({ id: sid, label: `${amcName} — ${scheme?.Name ?? sid}` })
      }
    }
    return out
  }, [selectedMfByAmc, mfSchemesByAmc, amcNames])

  const selectedIndiaEtfs = useMemo(() => {
    const out: { id: number; label: string }[] = []
    for (const [amcIdStr, ids] of Object.entries(selectedEtfByAmc)) {
      const amcId = Number(amcIdStr)
      const amcName = amcNames.get(amcId) ?? String(amcId)
      const schemes = etfSchemesByAmc[amcId] ?? []
      for (const sid of ids) {
        const scheme = schemes.find((s) => schemeKey(s) === sid)
        out.push({ id: sid, label: `${amcName} — ${scheme?.Name ?? sid}` })
      }
    }
    return out
  }, [selectedEtfByAmc, etfSchemesByAmc, amcNames])

  const selectedUsEtfs = useMemo(() => {
    const out: { id: string; label: string }[] = []
    for (const [issuer, ids] of Object.entries(selectedByIssuer)) {
      const schemes = schemesByIssuer[issuer] ?? []
      for (const sid of ids) {
        const scheme = schemes.find((s) => String(s.ID) === sid || s.symbol === sid)
        const sym = scheme?.symbol || sid
        out.push({ id: sym, label: `${issuer} — ${scheme?.Name ?? sym}` })
      }
    }
    return out
  }, [selectedByIssuer, schemesByIssuer])

  const selectedFundCount = indiaMarket
    ? selectedMf.length + selectedIndiaEtfs.length
    : selectedUsEtfs.length

  const buildPayload = (): SmartMoneyActivityRunPayload => {
    if (!picker.tickers.length) throw new Error('Select at least one ticker')
    if (selectedFundCount === 0) {
      throw new Error('Select one or more fund houses, then one or more funds/ETFs')
    }
    const asset_class = market === 'commodity' ? 'india' : market
    const effectiveSource: SourceMode =
      market === 'india' ? source : source === 'mutual_fund' ? 'etf' : source

    const mf_scheme_names: Record<number, string> = {}
    for (const s of selectedMf) mf_scheme_names[s.id] = s.label
    const etf_scheme_names: Record<number, string> = {}
    for (const s of selectedIndiaEtfs) etf_scheme_names[s.id] = s.label
    const etf_symbol_names: Record<string, string> = {}
    for (const s of selectedUsEtfs) etf_symbol_names[s.id] = s.label

    return {
      tickers: picker.tickers,
      asset_class: asset_class as 'india' | 'us' | 'crypto',
      source: effectiveSource,
      from_date: fromDate,
      to_date: toDate,
      amc_ids: indiaMarket ? selectedAmcIds : undefined,
      mf_scheme_ids: indiaMarket && (source === 'mutual_fund' || source === 'both')
        ? selectedMf.map((s) => s.id)
        : undefined,
      mf_scheme_names: indiaMarket ? mf_scheme_names : undefined,
      etf_scheme_ids: indiaMarket && (source === 'etf' || source === 'both')
        ? selectedIndiaEtfs.map((s) => s.id)
        : undefined,
      etf_scheme_names: indiaMarket ? etf_scheme_names : undefined,
      etf_symbols: usCryptoMarket ? selectedUsEtfs.map((s) => s.id) : undefined,
      etf_symbol_names: usCryptoMarket ? etf_symbol_names : undefined,
    }
  }

  const scanMutation = useMutation({
    mutationFn: () => runSmartMoneyActivity(buildPayload()),
    onSuccess: (data) => {
      setError('')
      setViewedReportId(null)
      if (data.error) {
        setError(String(data.error))
        setResult(data)
        return
      }
      setResult(data)
    },
    onError: (e) => {
      setError(apiErrorMessage(e))
      setResult(null)
    },
  })

  const reportsQuery = useQuery({
    queryKey: ['smart-money-activity-reports'],
    queryFn: fetchSmartMoneyActivityReports,
  })
  const reports = ((reportsQuery.data as { reports?: SmaSavedReportSummary[] } | undefined)?.reports) ?? []

  const runningJobsQuery = useQuery({
    queryKey: ['smart-money-activity-jobs-running'],
    queryFn: () => fetchSmartMoneyActivityJobs('running'),
    refetchInterval: 2000,
  })

  const recentJobsQuery = useQuery({
    queryKey: ['smart-money-activity-jobs-recent'],
    queryFn: () => fetchSmartMoneyActivityJobs('all'),
  })
  const recentJobs = ((recentJobsQuery.data as { jobs?: SmaBgJobStatus[] } | undefined)?.jobs) ?? []
  const recentFinished = recentJobs.filter((j) => j.status !== 'running').slice(0, 8)

  useEffect(() => {
    const serverJobs = ((runningJobsQuery.data as { jobs?: SmaBgJobStatus[] } | undefined)?.jobs) ?? []
    const ids = serverJobs.map((j) => j.job_id)
    if (!ids.length) return
    setBgJobIds((prev) => Array.from(new Set([...ids, ...prev])))
  }, [runningJobsQuery.data])

  const jobQueries = useQueries({
    queries: bgJobIds.map((id) => ({
      queryKey: ['smart-money-activity-job', id],
      queryFn: () => fetchSmartMoneyActivityJob(id) as Promise<SmaBgJobStatus>,
      refetchInterval: (q: { state: { data?: SmaBgJobStatus } }) =>
        q.state.data?.status === 'running' ? 1500 : false,
      refetchIntervalInBackground: true,
      retry: false,
    })),
  })

  const jobById = useMemo(() => {
    const map = new Map<string, SmaBgJobStatus>()
    jobQueries.forEach((q, i) => {
      const id = bgJobIds[i]
      if (id && q.data) map.set(id, q.data as SmaBgJobStatus)
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
      queryClient.invalidateQueries({ queryKey: ['smart-money-activity-reports'] })
      queryClient.invalidateQueries({ queryKey: ['smart-money-activity-jobs-running'] })
      queryClient.invalidateQueries({ queryKey: ['smart-money-activity-jobs-recent'] })
    }
  }, [bgJobIds, jobById, queryClient])

  const ongoingBg = bgJobIds
    .map((id) => jobById.get(id))
    .filter((j): j is SmaBgJobStatus => !!j && j.status === 'running')
  const serverRunning = ((runningJobsQuery.data as { jobs?: SmaBgJobStatus[] } | undefined)?.jobs) ?? []
  const ongoingMap = new Map<string, SmaBgJobStatus>()
  for (const j of [...serverRunning, ...ongoingBg]) {
    if (j.status === 'running') ongoingMap.set(j.job_id, j)
  }
  const ongoingList = Array.from(ongoingMap.values()).sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0))

  const reportDetailQuery = useQuery({
    queryKey: ['smart-money-activity-report', viewedReportId],
    queryFn: () => fetchSmartMoneyActivityReport(viewedReportId as number),
    enabled: viewedReportId != null,
  })
  const viewedReport = reportDetailQuery.data as
    | { name?: string; payload?: SmartMoneyActivityResult; created_at?: string; error?: string }
    | undefined
  const effectiveData: SmartMoneyActivityResult | null =
    viewedReportId != null ? (viewedReport?.payload ?? null) : result

  const startBgMutation = useMutation({
    mutationFn: startSmartMoneyActivityJob,
    onSuccess: (res) => {
      const id = res.job_id as string
      setBgError('')
      setBgMsg(`Background scan started${res.name ? `: ${res.name}` : ''}.`)
      setBgReportName('')
      setBgJobIds((prev) => Array.from(new Set([id, ...prev])))
      queryClient.invalidateQueries({ queryKey: ['smart-money-activity-jobs-running'] })
    },
    onError: (e) => setBgError(apiErrorMessage(e)),
  })

  const saveReportMutation = useMutation({
    mutationFn: saveSmartMoneyActivityReport,
    onSuccess: () => {
      setSaveMsg('Report saved.')
      setShowSaveForm(false)
      setSaveName('')
      queryClient.invalidateQueries({ queryKey: ['smart-money-activity-reports'] })
    },
    onError: (e) => setBgError(apiErrorMessage(e)),
  })

  const deleteReportMutation = useMutation({
    mutationFn: deleteSmartMoneyActivityReport,
    onSuccess: (_data, reportId) => {
      if (viewedReportId === reportId) setViewedReportId(null)
      queryClient.invalidateQueries({ queryKey: ['smart-money-activity-reports'] })
    },
  })

  const startBackgroundRun = () => {
    let payload: SmartMoneyActivityRunPayload
    try {
      payload = buildPayload()
    } catch (e) {
      setBgError(e instanceof Error ? e.message : String(e))
      return
    }
    if (!bgReportName.trim()) {
      setBgError('Enter a report name for the background run')
      return
    }
    setBgError('')
    setBgMsg('')
    startBgMutation.mutate({ ...payload, run_in_background: true, report_name: bgReportName.trim() })
  }

  const resetHouseSelection = () => {
    setSelectedAmcIds([])
    setMfSchemesByAmc({})
    setEtfSchemesByAmc({})
    setSelectedMfByAmc({})
    setSelectedEtfByAmc({})
    setSelectedIssuers([])
    setSchemesByIssuer({})
    setSelectedByIssuer({})
    setResult(null)
  }

  const toggleAmc = (id: number) => {
    setSelectedAmcIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  const toggleIssuer = (name: string) => {
    setSelectedIssuers((prev) => (prev.includes(name) ? prev.filter((x) => x !== name) : [...prev, name]))
  }

  const toggleScheme = (kind: SchemeKind, amcId: number, schemeId: number) => {
    const setter = kind === 'mf' ? setSelectedMfByAmc : setSelectedEtfByAmc
    setter((prev) => {
      const cur = prev[amcId] ?? []
      const has = cur.includes(schemeId)
      return { ...prev, [amcId]: has ? cur.filter((x) => x !== schemeId) : [...cur, schemeId] }
    })
  }

  const selectAllSchemes = (kind: SchemeKind, amcId: number, schemes: MutualFundScheme[]) => {
    const setter = kind === 'mf' ? setSelectedMfByAmc : setSelectedEtfByAmc
    setter((prev) => ({ ...prev, [amcId]: schemes.map(schemeKey) }))
  }

  const clearSchemes = (kind: SchemeKind, amcId: number) => {
    const setter = kind === 'mf' ? setSelectedMfByAmc : setSelectedEtfByAmc
    setter((prev) => ({ ...prev, [amcId]: [] }))
  }

  const filteredResults = useMemo(() => {
    const rows = effectiveData?.results ?? []
    const q = resultSearch.trim().toLowerCase()
    if (!q) return rows
    return rows.filter((r) => r.ticker.toLowerCase().includes(q))
  }, [effectiveData, resultSearch])

  const summary = effectiveData?.summary
  const aiSystemPrompt = String(effectiveData?.ai_system_prompt ?? '')
  const housesLoaded = indiaMarket
    ? indiaAmcs.length > 0
    : issuers.length > 0
  const fundsLoaded = indiaMarket
    ? Object.keys(mfSchemesByAmc).length + Object.keys(etfSchemesByAmc).length > 0
    : Object.keys(schemesByIssuer).length > 0
  const watchMarket: WatchlistMarket =
    market === 'us' || market === 'commodity' ? 'us' : market === 'crypto' ? 'crypto' : 'india'

  useEffect(() => {
    if (housesLoaded) setHousesOpen(true)
  }, [housesLoaded])

  useEffect(() => {
    if (fundsLoaded) setFundsOpen(true)
  }, [fundsLoaded])

  return (
    <div className="space-y-4">
      <Card>
        <h3 className="mb-1 font-medium text-white">Check Smart Money Activity</h3>
        <p className="mb-4 text-xs text-slate-500">
          Select fund house(s), then fund/ETF(s), then tickers and a date range. Signals: ADD LONG ·
          BULLISH · WAIT · BEARISH · SELL/AVOID. Preferred India houses (SBI · HDFC · ICICI · Nippon)
          appear first.
        </p>

        <div className="mb-3 flex flex-wrap gap-1.5">
          {(['india', 'us', 'crypto'] as AssetClass[]).map((m) => (
            <Chip
              key={m}
              selected={market === m}
              onClick={() => {
                setMarket(m)
                setPicker({ tickers: [], durations: ['1d'] })
                if (m !== 'india' && source === 'mutual_fund') setSource('etf')
                resetHouseSelection()
              }}
            >
              {m}
            </Chip>
          ))}
        </div>

        <AssetClassTickerPicker
          key={market}
          assetClass={market === 'commodity' ? 'india' : market}
          onChange={setPicker}
          showDurations={false}
        />

        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <FormField label="Source">
            <div className="flex flex-wrap gap-1.5 pt-1">
              {(
                [
                  ['both', 'MF + ETF'],
                  ['mutual_fund', 'Mutual Fund'],
                  ['etf', 'ETF'],
                ] as const
              ).map(([id, label]) => (
                <Chip
                  key={id}
                  selected={source === id}
                  onClick={() => {
                    setSource(id)
                    resetHouseSelection()
                  }}
                  title={market !== 'india' && id === 'mutual_fund' ? 'India only' : undefined}
                >
                  {label}
                </Chip>
              ))}
            </div>
          </FormField>
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
              disabled={
                scanMutation.isPending
                || runInBackground
                || picker.tickers.length === 0
                || selectedFundCount === 0
                || !fromDate
                || !toDate
              }
              onClick={() => scanMutation.mutate()}
            >
              {scanMutation.isPending ? 'Scanning funds…' : 'Check smart money'}
            </Button>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <Button
            onClick={() => loadHousesMutation.mutate()}
            disabled={loadHousesMutation.isPending}
          >
            {loadHousesMutation.isPending
              ? 'Loading…'
              : indiaMarket
                ? 'Load fund houses'
                : 'Load issuers'}
          </Button>
          <Button
            variant="secondary"
            disabled={
              loadFundsMutation.isPending
              || (indiaMarket ? !selectedAmcIds.length : !selectedIssuers.length)
            }
            onClick={() => loadFundsMutation.mutate()}
          >
            {loadFundsMutation.isPending
              ? 'Fetching…'
              : indiaMarket
                ? 'Get funds / ETFs'
                : 'Get ETFs'}
          </Button>
          {selectedFundCount > 0 && (
            <span className="self-center text-xs text-slate-500">
              {selectedFundCount} fund(s)/ETF(s) selected
            </span>
          )}
        </div>

        {error && (
          <div className="mt-3"><Alert type="error">{error}</Alert></div>
        )}
        {scanMutation.isPending && (
          <div className="mt-4"><Loading message="Fetching holdings snapshots…" /></div>
        )}

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
                    placeholder={`${picker.tickers.slice(0, 2).join(' + ') || 'Smart money activity'} · ${fromDate}→${toDate}`}
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

      {housesLoaded && indiaMarket && (
        <CollapsibleSection
          title={`Fund houses — ${filteredAmcs.length} shown`}
          subtitle={`${selectedAmcIds.length} selected · ★ preferred (SBI / HDFC / ICICI / Nippon)`}
          open={housesOpen}
          onToggle={() => setHousesOpen((o) => !o)}
        >
          <FormField label="Filter">
            <input
              type="search"
              placeholder="Filter fund houses…"
              className="mb-2 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200"
              value={amcFilter}
              onChange={(e) => setAmcFilter(e.target.value)}
            />
            <div className="max-h-56 overflow-y-auto rounded-lg border border-slate-800 p-2">
              <div className="grid gap-1 sm:grid-cols-2 lg:grid-cols-3">
                {filteredAmcs.map((a) => {
                  const id = amcKey(a)
                  const checked = selectedAmcIds.includes(id)
                  const preferred = isPreferredAmc(a.Name)
                  return (
                    <label
                      key={id}
                      className={`flex cursor-pointer items-start gap-2 rounded px-2 py-1.5 text-xs hover:bg-slate-800/60 ${preferred ? 'text-emerald-300' : 'text-slate-300'}`}
                    >
                      <input type="checkbox" checked={checked} onChange={() => toggleAmc(id)} className="mt-0.5" />
                      <span>
                        {a.Name}
                        {preferred ? ' ★' : ''}
                      </span>
                    </label>
                  )
                })}
              </div>
            </div>
          </FormField>
        </CollapsibleSection>
      )}

      {housesLoaded && usCryptoMarket && (
        <CollapsibleSection
          title={`Issuers / fund houses — ${filteredIssuers.length} shown`}
          subtitle={`${selectedIssuers.length} selected`}
          open={housesOpen}
          onToggle={() => setHousesOpen((o) => !o)}
        >
          <FormField label="Filter">
            <input
              type="search"
              placeholder="Filter issuers…"
              className="mb-2 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200"
              value={issuerFilter}
              onChange={(e) => setIssuerFilter(e.target.value)}
            />
            <div className="max-h-56 overflow-y-auto rounded-lg border border-slate-800 p-2">
              <div className="grid gap-1 sm:grid-cols-2 lg:grid-cols-3">
                {filteredIssuers.map((a: EtfIssuer) => {
                  const checked = selectedIssuers.includes(a.Name)
                  return (
                    <label
                      key={a.Name}
                      className="flex cursor-pointer items-start gap-2 rounded px-2 py-1.5 text-xs text-slate-300 hover:bg-slate-800/60"
                    >
                      <input type="checkbox" checked={checked} onChange={() => toggleIssuer(a.Name)} className="mt-0.5" />
                      <span>{a.Name}{a.SchemeCount != null ? ` (${a.SchemeCount})` : ''}</span>
                    </label>
                  )
                })}
              </div>
            </div>
          </FormField>
        </CollapsibleSection>
      )}

      {fundsLoaded && indiaMarket && (
        <CollapsibleSection
          title="Funds / ETFs"
          subtitle={`${selectedFundCount} selected across ${selectedAmcIds.length} fund house(s)`}
          open={fundsOpen}
          onToggle={() => setFundsOpen((o) => !o)}
        >
          <div className="max-h-[28rem] space-y-4 overflow-y-auto pr-1">
            {selectedAmcIds.map((amcId) => {
              const amcName = amcNames.get(amcId) ?? String(amcId)
              const mfSchemes = mfSchemesByAmc[amcId] ?? []
              const etfSchemes = etfSchemesByAmc[amcId] ?? []
              const showMf = (source === 'mutual_fund' || source === 'both') && amcId in mfSchemesByAmc
              const showEtf = (source === 'etf' || source === 'both') && amcId in etfSchemesByAmc
              if (!showMf && !showEtf) return null
              return (
                <div key={amcId} className="space-y-3 border-b border-slate-800 pb-3 last:border-0">
                  <h4 className="text-sm font-semibold text-white">{amcName}</h4>
                  {showMf && (
                    <SchemeCheckboxTable
                      title={`Mutual funds (${mfSchemes.length})`}
                      schemes={mfSchemes}
                      selected={selectedMfByAmc[amcId] ?? []}
                      onToggle={(sid) => toggleScheme('mf', amcId, sid)}
                      onSelectAll={() => selectAllSchemes('mf', amcId, mfSchemes)}
                      onClear={() => clearSchemes('mf', amcId)}
                    />
                  )}
                  {showEtf && (
                    <SchemeCheckboxTable
                      title={`ETFs (${etfSchemes.length})`}
                      schemes={etfSchemes}
                      selected={selectedEtfByAmc[amcId] ?? []}
                      onToggle={(sid) => toggleScheme('etf', amcId, sid)}
                      onSelectAll={() => selectAllSchemes('etf', amcId, etfSchemes)}
                      onClear={() => clearSchemes('etf', amcId)}
                    />
                  )}
                </div>
              )
            })}
          </div>
        </CollapsibleSection>
      )}

      {fundsLoaded && usCryptoMarket && (
        <CollapsibleSection
          title="ETFs"
          subtitle={`${selectedFundCount} selected across ${selectedIssuers.length} issuer(s)`}
          open={fundsOpen}
          onToggle={() => setFundsOpen((o) => !o)}
        >
          <div className="max-h-[28rem] space-y-4 overflow-y-auto pr-1">
            {selectedIssuers.map((issuer) => {
              const schemes = schemesByIssuer[issuer] ?? []
              const selected = selectedByIssuer[issuer] ?? []
              if (!(issuer in schemesByIssuer)) return null
              return (
                <div key={issuer}>
                  <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <h4 className="text-sm font-semibold text-white">{issuer} — {schemes.length} ETF(s)</h4>
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={!schemes.length}
                        onClick={() => setSelectedByIssuer((prev) => ({
                          ...prev,
                          [issuer]: schemes.map((s) => String(s.symbol || s.ID)),
                        }))}
                      >
                        Select all
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={!selected.length}
                        onClick={() => setSelectedByIssuer((prev) => ({ ...prev, [issuer]: [] }))}
                      >
                        Clear
                      </Button>
                    </div>
                  </div>
                  {!schemes.length ? (
                    <p className="text-xs text-slate-500">No ETFs for this issuer.</p>
                  ) : (
                    <div className="max-h-56 overflow-y-auto rounded-lg border border-slate-800">
                      <DataTable minWidth={640}>
                        <thead>
                          <tr>
                            <Th>Select</Th>
                            <Th>Symbol</Th>
                            <Th>Name</Th>
                          </tr>
                        </thead>
                        <tbody>
                          {schemes.map((s) => {
                            const sid = String(s.symbol || s.ID)
                            const checked = selected.includes(sid)
                            return (
                              <tr key={sid} className="border-t border-slate-800/80">
                                <Td>
                                  <input
                                    type="checkbox"
                                    checked={checked}
                                    onChange={() => setSelectedByIssuer((prev) => {
                                      const cur = prev[issuer] ?? []
                                      return {
                                        ...prev,
                                        [issuer]: checked ? cur.filter((x) => x !== sid) : [...cur, sid],
                                      }
                                    })}
                                  />
                                </Td>
                                <Td className="font-medium text-slate-100">{s.symbol || s.ID}</Td>
                                <Td className="text-xs text-slate-400">{s.Name}</Td>
                              </tr>
                            )
                          })}
                        </tbody>
                      </DataTable>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </CollapsibleSection>
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
                  {(job.meta?.tickers ?? []).slice(0, 4).join(', ')}
                  {(job.meta?.tickers?.length ?? 0) > 4 ? '…' : ''}
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
            No saved reports yet. Run a scan and save it, or start a named background run.
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
                  {s && (s.bullish_count != null || s.bearish_count != null) && (
                    <p className="mt-1 text-xs text-teal-400/90">
                      {s.ticker_count ?? 0} tickers · {s.found_count ?? 0} found ·{' '}
                      {s.bullish_count ?? 0} long · {s.bearish_count ?? 0} short
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

      {effectiveData && !scanMutation.isPending && (
        <Card>
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
            <div>
              <h3 className="font-medium text-white">Trade bias by ticker</h3>
              <p className="mt-0.5 text-xs text-slate-500">
                LONG = funds accumulating · SHORT = funds distributing · WAIT = mixed/flat or not found.
              </p>
              {viewedReportId != null && viewedReport?.name && (
                <p className="mt-1 text-xs text-slate-400">
                  Viewing saved report: <span className="text-slate-200">{viewedReport.name}</span>
                  {viewedReport.created_at ? ` · saved ${formatWhen(viewedReport.created_at)}` : ''}
                </p>
              )}
            </div>
            <div className="flex items-center gap-2">
              {summary && (
                <p className="text-xs text-slate-500">
                  {summary.found}/{summary.tickers} found ·{' '}
                  <span className="text-emerald-400">{summary.bullish} long</span>
                  {' · '}
                  <span className="text-rose-400">{summary.bearish} short</span>
                  {' · '}
                  <span className="text-slate-400">{summary.wait} wait</span>
                </p>
              )}
              {viewedReportId == null && !effectiveData.error && (
                <Button variant="secondary" size="sm" onClick={() => setShowSaveForm(true)}>
                  <span className="inline-flex items-center gap-1.5"><Save size={14} />Save</span>
                </Button>
              )}
              {viewedReportId != null && (
                <Button variant="ghost" size="sm" onClick={() => setViewedReportId(null)}>Back to live result</Button>
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
                    placeholder={`${picker.tickers.slice(0, 2).join(' + ') || 'Smart money activity'} — ${new Date().toLocaleDateString()}`}
                  />
                  <Button
                    onClick={() => saveReportMutation.mutate({
                      name: saveName.trim() || `Smart money activity ${new Date().toLocaleString()}`,
                      tickers: picker.tickers,
                      from_date: fromDate,
                      to_date: toDate,
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

          {(effectiveData.notes?.length ?? 0) > 0 && (
            <ul className="mb-3 list-inside list-disc text-xs text-slate-500">
              {effectiveData.notes!.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          )}
          {(effectiveData.preferred_amcs?.length ?? 0) > 0 && (
            <p className="mb-3 text-xs text-slate-500">
              AMCs: {effectiveData.preferred_amcs!.map((a) => a.name).join(' · ')}
            </p>
          )}
          {(effectiveData.results?.length ?? 0) === 0 ? (
            <p className="text-sm text-slate-500">No results.</p>
          ) : (
            <>
              <div className="relative mb-3 max-w-xs">
                <input
                  type="search"
                  placeholder="Search ticker…"
                  className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200"
                  value={resultSearch}
                  onChange={(e) => setResultSearch(e.target.value)}
                />
              </div>
              {filteredResults.length === 0 ? (
                <p className="text-sm text-slate-500">No tickers match "{resultSearch}".</p>
              ) : (
                <DataTable minWidth={980}>
                  <thead>
                    <tr>
                      <Th>Ticker</Th>
                      <Th>Bias</Th>
                      <Th>View</Th>
                      <Th>Trend</Th>
                      <Th>Avg Δ stake</Th>
                      <Th>Funds</Th>
                      <Th>Reasoning</Th>
                      <Th>Watch</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredResults.map((r) => (
                      <ResultRow key={r.ticker} r={r} market={watchMarket} aiSystemPrompt={aiSystemPrompt} />
                    ))}
                  </tbody>
                </DataTable>
              )}
            </>
          )}
        </Card>
      )}
    </div>
  )
}

function SchemeCheckboxTable({
  title,
  schemes,
  selected,
  onToggle,
  onSelectAll,
  onClear,
}: {
  title: string
  schemes: MutualFundScheme[]
  selected: number[]
  onToggle: (id: number) => void
  onSelectAll: () => void
  onClear: () => void
}) {
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h5 className="text-xs font-medium text-slate-300">{title}</h5>
        <div className="flex gap-2">
          <Button size="sm" variant="ghost" disabled={!schemes.length} onClick={onSelectAll}>Select all</Button>
          <Button size="sm" variant="ghost" disabled={!selected.length} onClick={onClear}>Clear</Button>
        </div>
      </div>
      {!schemes.length ? (
        <p className="text-xs text-slate-500">None found.</p>
      ) : (
        <div className="max-h-56 overflow-y-auto rounded-lg border border-slate-800">
          <DataTable minWidth={640}>
            <thead>
              <tr>
                <Th>Select</Th>
                <Th>Scheme</Th>
                <Th>Category</Th>
              </tr>
            </thead>
            <tbody>
              {schemes.map((s) => {
                const sid = schemeKey(s)
                const checked = selected.includes(sid)
                return (
                  <tr key={sid} className="border-t border-slate-800/80">
                    <Td>
                      <input type="checkbox" checked={checked} onChange={() => onToggle(sid)} />
                    </Td>
                    <Td className="font-medium text-slate-100">{s.Name}</Td>
                    <Td className="text-xs text-slate-400">{s.Description ?? '—'}</Td>
                  </tr>
                )
              })}
            </tbody>
          </DataTable>
        </div>
      )}
    </div>
  )
}
