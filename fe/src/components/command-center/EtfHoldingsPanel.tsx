import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQueries, useQuery, useQueryClient, type UseMutationResult } from '@tanstack/react-query'
import { FolderOpen, Save, Trash2, X } from 'lucide-react'
import {
  apiErrorMessage,
  deleteEtfHoldingsReport,
  fetchEtfHoldingsAmcs,
  fetchEtfHoldingsIssuers,
  fetchEtfHoldingsJob,
  fetchEtfHoldingsJobs,
  fetchEtfHoldingsReport,
  fetchEtfHoldingsReports,
  fetchEtfHoldingsSchemes,
  fetchEtfIssuerSchemes,
  runEtfIndiaHoldingsChange,
  runEtfYahooHoldingsChange,
  saveEtfHoldingsReport,
  startEtfIndiaHoldingsJob,
  startEtfYahooHoldingsJob,
  type EtfHoldingsJobStartResponse,
  type EtfIssuer,
  type EtfIssuerScheme,
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

type MarketTab = 'india' | 'us' | 'crypto'
type Row = Record<string, unknown>

interface EtfSavedReportSummary {
  id: number
  name: string
  asset_class: string
  names: string[]
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

interface EtfBgJobStatus {
  job_id: string
  status: string
  progress?: number
  progress_note?: string
  name?: string | null
  report_id?: number | null
  error?: string | null
  result?: Row
  meta?: {
    asset_class?: string
    names?: string[]
    from_date?: string
    to_date?: string
  }
  created_at?: number
}

/** Shared background-run + save controls, threaded down into whichever tab (India / US / Crypto) is active. */
interface BgControls {
  runInBackground: boolean
  setRunInBackground: (v: boolean) => void
  bgReportName: string
  setBgReportName: (v: string) => void
  bgError: string
  bgMsg: string
  startIndiaMutation: UseMutationResult<EtfHoldingsJobStartResponse, unknown, Parameters<typeof startEtfIndiaHoldingsJob>[0]>
  startYahooMutation: UseMutationResult<EtfHoldingsJobStartResponse, unknown, Parameters<typeof startEtfYahooHoldingsJob>[0]>
  saveReportMutation: UseMutationResult<unknown, unknown, { name: string; payload: Record<string, unknown> }>
  saveName: string
  setSaveName: (v: string) => void
  showSaveForm: boolean
  setShowSaveForm: (v: boolean) => void
  saveMsg: string
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

function BackgroundRunBlock({
  bg, disabled, defaultName, onStart,
}: {
  bg: BgControls
  disabled: boolean
  defaultName: string
  onStart: () => void
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
            Name the run — it keeps going if you leave this page, then auto-saves into Saved reports below
            when done. You can start several background runs at once.
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
                placeholder={defaultName}
                maxLength={200}
              />
            </FormField>
          </div>
          <Button onClick={onStart} disabled={disabled}>
            {disabled ? 'Starting…' : 'Start background run'}
          </Button>
        </div>
      )}
      {bg.bgError && <Alert type="error">{bg.bgError}</Alert>}
      {bg.bgMsg && <Alert type="success">{bg.bgMsg}</Alert>}
    </div>
  )
}

function SaveResultBlock({
  bg, analysis, defaultName,
}: {
  bg: BgControls
  analysis: HoldingsAnalysisResult
  defaultName: string
}) {
  return (
    <div className="mt-3">
      {!bg.showSaveForm ? (
        <Button variant="secondary" size="sm" onClick={() => bg.setShowSaveForm(true)}>
          <span className="inline-flex items-center gap-1.5"><Save size={14} />Save for future reference</span>
        </Button>
      ) : (
        <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-3">
          <FormField label="Report name">
            <div className="flex gap-2">
              <Input value={bg.saveName} onChange={(e) => bg.setSaveName(e.target.value)} placeholder={defaultName} />
              <Button
                onClick={() => bg.saveReportMutation.mutate({
                  name: bg.saveName.trim() || defaultName,
                  payload: analysis as unknown as Record<string, unknown>,
                })}
                disabled={bg.saveReportMutation.isPending}
              >
                <span className="inline-flex items-center gap-1.5"><Save size={14} />Save</span>
              </Button>
              <Button variant="ghost" onClick={() => bg.setShowSaveForm(false)}>Cancel</Button>
            </div>
          </FormField>
          {bg.saveMsg && <p className="mt-2 text-xs text-emerald-400">{bg.saveMsg}</p>}
        </div>
      )}
    </div>
  )
}

function IndiaEtfTab({ bg }: { bg: BgControls }) {
  const [selectedAmcIds, setSelectedAmcIds] = useState<number[]>([])
  const [schemesByAmc, setSchemesByAmc] = useState<Record<number, MutualFundScheme[]>>({})
  const [selectedSchemeIds, setSelectedSchemeIds] = useState<Record<number, number[]>>({})
  const [fromDate, setFromDate] = useState(isoDaysAgo(365))
  const [toDate, setToDate] = useState(isoDaysAgo(0))
  const [amcFilter, setAmcFilter] = useState('')
  const [loadError, setLoadError] = useState('')
  const [amcsOpen, setAmcsOpen] = useState(true)
  const [fundsOpen, setFundsOpen] = useState(true)
  const [resultsOpen, setResultsOpen] = useState(true)
  const [fundSectionOpen, setFundSectionOpen] = useState<Record<number, boolean>>({})

  const amcsQuery = useQuery({
    queryKey: ['etf-amcs'],
    queryFn: fetchEtfHoldingsAmcs,
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
        const res = await fetchEtfHoldingsSchemes(id)
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
      if (!selectedSchemes.length) throw new Error('Select at least one ETF')
      if (fromDate > toDate) throw new Error('From date must be on or before To date')
      const scheme_names: Record<string, string> = {}
      for (const s of selectedSchemes) scheme_names[String(s.id)] = s.label
      return runEtfIndiaHoldingsChange({
        scheme_ids: selectedSchemes.map((s) => s.id),
        scheme_names,
        from_date: fromDate,
        to_date: toDate,
      })
    },
  })

  const startBackgroundRun = () => {
    if (!selectedSchemes.length || fromDate > toDate || !bg.bgReportName.trim()) return
    const scheme_names: Record<string, string> = {}
    for (const s of selectedSchemes) scheme_names[String(s.id)] = s.label
    bg.startIndiaMutation.mutate({
      scheme_ids: selectedSchemes.map((s) => s.id),
      scheme_names,
      from_date: fromDate,
      to_date: toDate,
      run_in_background: true,
      report_name: bg.bgReportName.trim(),
    })
  }

  const analysis = analyzeMutation.data as HoldingsAnalysisResult | undefined
  const loadedAmcIds = Object.keys(schemesByAmc).map(Number)
  const defaultName = `${selectedSchemes.slice(0, 2).map((s) => s.label).join(' + ') || 'India ETF holdings'} · ${fromDate}→${toDate}`

  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-400">
        Browse AMCs → pick <strong className="text-slate-300">ETF</strong> fund(s) → month-end holding % trends (StockEdge).
      </p>
      <div className="flex flex-wrap gap-2">
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
          {schemesMutation.isPending ? 'Fetching ETFs…' : 'Get ETF funds'}
        </Button>
      </div>
      {(loadError || amcsQuery.isError) && (
        <Alert type="error">{loadError || apiErrorMessage(amcsQuery.error)}</Alert>
      )}
      {amcs.length > 0 && (
        <CollapsibleScrollSection
          title={`AMC list — ${amcs.length} loaded`}
          subtitle={`${selectedAmcIds.length} selected · scroll inside`}
          open={amcsOpen}
          onToggle={() => setAmcsOpen((v) => !v)}
          maxHeightClass="max-h-56"
        >
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
                <Chip
                  key={id}
                  selected={selectedAmcIds.includes(id)}
                  onClick={() => setSelectedAmcIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))}
                >
                  {a.Name}{a.AUM != null ? ` · ₹${fmtAum(a.AUM)} Cr` : ''}
                </Chip>
              )
            })}
          </div>
        </CollapsibleScrollSection>
      )}
      {loadedAmcIds.length > 0 && (
        <CollapsibleScrollSection
          title={`ETF schemes — ${selectedSchemes.length} selected`}
          subtitle={`${loadedAmcIds.length} AMC(s) · collapse to reduce page length`}
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
                  title={`${amcName} — ${schemes.length} ETF scheme(s)`}
                  subtitle={`${selected.length} selected`}
                  open={sectionOpen}
                  onToggle={() => setFundSectionOpen((prev) => ({ ...prev, [amcId]: !sectionOpen }))}
                  maxHeightClass="max-h-64"
                >
                  <div className="mb-2 flex flex-wrap gap-2">
                    <Button size="sm" variant="ghost" disabled={!schemes.length} onClick={() => setSelectedSchemeIds((prev) => ({ ...prev, [amcId]: schemes.map(schemeKey) }))}>Select all</Button>
                    <Button size="sm" variant="ghost" disabled={!selected.length} onClick={() => setSelectedSchemeIds((prev) => ({ ...prev, [amcId]: [] }))}>Clear</Button>
                  </div>
                  {!schemes.length ? (
                    <p className="text-xs text-slate-500">No ETF schemes found for this AMC.</p>
                  ) : (
                    <DataTable minWidth={720}>
                      <thead>
                        <tr>
                          <Th>Select</Th><Th>Scheme</Th><Th>Category</Th><Th>NAV</Th><Th>Return %</Th><Th>AUM (₹ Cr)</Th>
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
                                  onChange={() => setSelectedSchemeIds((prev) => {
                                    const cur = prev[amcId] ?? []
                                    return { ...prev, [amcId]: checked ? cur.filter((x) => x !== sid) : [...cur, sid] }
                                  })}
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
              <div className="grid gap-4 sm:grid-cols-[1fr_1fr_auto]">
                <FormField label="From date">
                  <input type="date" className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100" value={fromDate} onChange={(e) => setFromDate(e.target.value)} />
                </FormField>
                <FormField label="To date">
                  <input type="date" className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100" value={toDate} onChange={(e) => setToDate(e.target.value)} />
                </FormField>
                <div className="flex items-end">
                  <Button className="w-full" onClick={() => { setResultsOpen(true); analyzeMutation.mutate() }} disabled={analyzeMutation.isPending || bg.runInBackground}>
                    {analyzeMutation.isPending ? 'Analyzing…' : 'Analyze Holding Change'}
                  </Button>
                </div>
              </div>
              {analyzeMutation.isError && <Alert type="error">{apiErrorMessage(analyzeMutation.error)}</Alert>}
              <BackgroundRunBlock bg={bg} disabled={bg.startIndiaMutation.isPending} defaultName={defaultName} onStart={startBackgroundRun} />
            </div>
          ) : (
            <p className="mt-3 text-sm text-slate-500">Select one or more ETF schemes from the table(s) above.</p>
          )}
        </CollapsibleScrollSection>
      )}
      {analyzeMutation.isPending && <Loading message="Fetching month-end ETF holdings…" />}
      {analysis && !analyzeMutation.isPending && (
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
            <>
              <SaveResultBlock bg={bg} analysis={analysis} defaultName={`India ETF holdings — ${new Date().toLocaleDateString()}`} />
              <HoldingsTrendResults data={analysis} fundNoun="ETFs" askSection="command-center/etf_holdings" askTitle="ETF Holdings (India)" marketType="india" resolveName />
            </>
          )}
        </CollapsibleScrollSection>
      )}
    </div>
  )
}

function IssuerEtfTab({
  market,
  note,
  bg,
}: {
  market: 'us' | 'crypto'
  note: string
  bg: BgControls
}) {
  const [selectedIssuers, setSelectedIssuers] = useState<string[]>([])
  const [schemesByIssuer, setSchemesByIssuer] = useState<Record<string, EtfIssuerScheme[]>>({})
  const [selectedByIssuer, setSelectedByIssuer] = useState<Record<string, string[]>>({})
  const [fromDate, setFromDate] = useState(isoDaysAgo(400))
  const [toDate, setToDate] = useState(isoDaysAgo(0))
  const [issuerFilter, setIssuerFilter] = useState('')
  const [loadError, setLoadError] = useState('')
  const [issuersOpen, setIssuersOpen] = useState(true)
  const [fundsOpen, setFundsOpen] = useState(true)
  const [resultsOpen, setResultsOpen] = useState(true)
  const [fundSectionOpen, setFundSectionOpen] = useState<Record<string, boolean>>({})

  const issuersQuery = useQuery({
    queryKey: ['etf-issuers', market],
    queryFn: () => fetchEtfHoldingsIssuers(market),
    enabled: false,
  })

  const issuers = issuersQuery.data?.issuers ?? []
  const filteredIssuers = useMemo(() => {
    const q = issuerFilter.trim().toLowerCase()
    if (!q) return issuers
    return issuers.filter((a: EtfIssuer) => a.Name.toLowerCase().includes(q))
  }, [issuers, issuerFilter])

  const schemesMutation = useMutation({
    mutationFn: async (names: string[]) => {
      const next: Record<string, EtfIssuerScheme[]> = { ...schemesByIssuer }
      for (const name of names) {
        const res = await fetchEtfIssuerSchemes(market, name)
        next[name] = res.schemes ?? []
      }
      return next
    },
    onSuccess: (next) => {
      setSchemesByIssuer(next)
      setLoadError('')
    },
    onError: (e) => setLoadError(apiErrorMessage(e)),
  })

  const selected = useMemo(() => {
    const out: { id: string; label: string }[] = []
    for (const [issuer, ids] of Object.entries(selectedByIssuer)) {
      const schemes = schemesByIssuer[issuer] ?? []
      for (const sid of ids) {
        const scheme = schemes.find((s) => String(s.ID) === sid)
        out.push({ id: sid, label: `${issuer} — ${sid} — ${scheme?.Name ?? sid}` })
      }
    }
    return out
  }, [selectedByIssuer, schemesByIssuer])

  const analyzeMutation = useMutation({
    mutationFn: () => {
      if (!selected.length) throw new Error('Pick at least one ETF')
      if (fromDate > toDate) throw new Error('From date must be on or before To date')
      const symbol_names: Record<string, string> = {}
      for (const s of selected) symbol_names[s.id] = s.label
      return runEtfYahooHoldingsChange({
        market,
        symbols: selected.map((s) => s.id),
        symbol_names,
        from_date: fromDate,
        to_date: toDate,
      })
    },
  })

  const startBackgroundRun = () => {
    if (!selected.length || fromDate > toDate || !bg.bgReportName.trim()) return
    const symbol_names: Record<string, string> = {}
    for (const s of selected) symbol_names[s.id] = s.label
    bg.startYahooMutation.mutate({
      market,
      symbols: selected.map((s) => s.id),
      symbol_names,
      from_date: fromDate,
      to_date: toDate,
      run_in_background: true,
      report_name: bg.bgReportName.trim(),
    })
  }

  const analysis = analyzeMutation.data as HoldingsAnalysisResult | undefined
  const loadedIssuers = Object.keys(schemesByIssuer)
  const loadLabel = market === 'us' ? 'Load All Categories' : 'Load All Issuers'
  const defaultName = `${selected.slice(0, 2).map((s) => s.label).join(' + ') || `${market.toUpperCase()} ETF holdings`} · ${fromDate}→${toDate}`

  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-400">{note}</p>
      <div className="flex flex-wrap gap-2">
        <Button
          onClick={() => {
            setLoadError('')
            issuersQuery.refetch().then((r) => {
              if (r.isError) setLoadError(apiErrorMessage(r.error))
            })
          }}
          disabled={issuersQuery.isFetching}
        >
          {issuersQuery.isFetching ? 'Loading…' : loadLabel}
        </Button>
        <Button
          variant="secondary"
          disabled={!selectedIssuers.length || schemesMutation.isPending}
          onClick={() => schemesMutation.mutate(selectedIssuers)}
        >
          {schemesMutation.isPending ? 'Fetching ETFs…' : 'Get ETF funds'}
        </Button>
      </div>
      {(loadError || issuersQuery.isError) && (
        <Alert type="error">{loadError || apiErrorMessage(issuersQuery.error)}</Alert>
      )}
      {issuers.length > 0 && (
        <CollapsibleScrollSection
          title={`${market === 'us' ? 'Categories' : 'Issuers'} — ${issuers.length} loaded`}
          subtitle={`${selectedIssuers.length} selected · scroll inside`}
          open={issuersOpen}
          onToggle={() => setIssuersOpen((v) => !v)}
          maxHeightClass="max-h-56"
        >
          <input
            className="mb-2 w-full max-w-md rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
            placeholder="Filter…"
            value={issuerFilter}
            onChange={(e) => setIssuerFilter(e.target.value)}
          />
          <div className="flex flex-wrap gap-1.5">
            {filteredIssuers.map((a) => (
              <Chip
                key={a.Name}
                selected={selectedIssuers.includes(a.Name)}
                onClick={() => setSelectedIssuers((prev) => (prev.includes(a.Name) ? prev.filter((x) => x !== a.Name) : [...prev, a.Name]))}
              >
                {a.Name}{a.SchemeCount != null ? ` · ${a.SchemeCount}` : ''}
              </Chip>
            ))}
          </div>
        </CollapsibleScrollSection>
      )}
      {loadedIssuers.length > 0 && (
        <CollapsibleScrollSection
          title={`ETF list — ${selected.length} selected`}
          subtitle={`${loadedIssuers.length} group(s) · collapse to reduce page length`}
          open={fundsOpen}
          onToggle={() => setFundsOpen((v) => !v)}
          scroll={false}
        >
          <div className="space-y-3">
            {loadedIssuers.map((issuer) => {
              const schemes = schemesByIssuer[issuer] ?? []
              const picked = selectedByIssuer[issuer] ?? []
              const sectionOpen = fundSectionOpen[issuer] ?? true
              return (
                <CollapsibleScrollSection
                  key={issuer}
                  title={`${issuer} — ${schemes.length} ETF(s)`}
                  subtitle={`${picked.length} selected`}
                  open={sectionOpen}
                  onToggle={() => setFundSectionOpen((prev) => ({ ...prev, [issuer]: !sectionOpen }))}
                  maxHeightClass="max-h-64"
                >
                  <div className="mb-2 flex flex-wrap gap-2">
                    <Button size="sm" variant="ghost" disabled={!schemes.length} onClick={() => setSelectedByIssuer((prev) => ({ ...prev, [issuer]: schemes.map((s) => String(s.ID)) }))}>Select all</Button>
                    <Button size="sm" variant="ghost" disabled={!picked.length} onClick={() => setSelectedByIssuer((prev) => ({ ...prev, [issuer]: [] }))}>Clear</Button>
                  </div>
                  {!schemes.length ? (
                    <p className="text-xs text-slate-500">No ETFs found for this group.</p>
                  ) : (
                    <DataTable minWidth={640}>
                      <thead>
                        <tr><Th>Select</Th><Th>Scheme</Th><Th>Category</Th></tr>
                      </thead>
                      <tbody>
                        {schemes.map((s) => {
                          const sid = String(s.ID)
                          const checked = picked.includes(sid)
                          return (
                            <tr key={sid} className="border-t border-slate-800/80">
                              <Td>
                                <input
                                  type="checkbox"
                                  checked={checked}
                                  onChange={() => setSelectedByIssuer((prev) => {
                                    const cur = prev[issuer] ?? []
                                    return { ...prev, [issuer]: checked ? cur.filter((x) => x !== sid) : [...cur, sid] }
                                  })}
                                />
                              </Td>
                              <Td className="font-medium text-slate-100">{sid} — {s.Name}</Td>
                              <Td>{s.Description ?? '—'}</Td>
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
          {selected.length > 0 ? (
            <div className="mt-4 space-y-4 border-t border-slate-800 pt-4">
              <p className="text-xs text-slate-500">
                {market === 'us'
                  ? 'ETF list + latest Companies/Holding % from INDMoney. Date-range trends use SEC NPORT reporting periods (typically quarterly).'
                  : 'SEC NPORT-P public holdings are typically quarterly. First run can take a minute while filings download.'}
              </p>
              <div className="grid gap-4 sm:grid-cols-[1fr_1fr_auto]">
                <FormField label="From date">
                  <input type="date" className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100" value={fromDate} onChange={(e) => setFromDate(e.target.value)} />
                </FormField>
                <FormField label="To date">
                  <input type="date" className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100" value={toDate} onChange={(e) => setToDate(e.target.value)} />
                </FormField>
                <div className="flex items-end">
                  <Button className="w-full" onClick={() => { setResultsOpen(true); analyzeMutation.mutate() }} disabled={analyzeMutation.isPending || bg.runInBackground}>
                    {analyzeMutation.isPending ? 'Analyzing…' : 'Analyze Holding Change'}
                  </Button>
                </div>
              </div>
              {analyzeMutation.isError && <Alert type="error">{apiErrorMessage(analyzeMutation.error)}</Alert>}
              <BackgroundRunBlock bg={bg} disabled={bg.startYahooMutation.isPending} defaultName={defaultName} onStart={startBackgroundRun} />
            </div>
          ) : (
            <p className="mt-3 text-sm text-slate-500">Select one or more ETFs from the table(s) above.</p>
          )}
        </CollapsibleScrollSection>
      )}
      {analyzeMutation.isPending && <Loading message="Fetching ETF holdings…" />}
      {analysis && !analyzeMutation.isPending && (
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
            <>
              <SaveResultBlock bg={bg} analysis={analysis} defaultName={`${market.toUpperCase()} ETF holdings — ${new Date().toLocaleDateString()}`} />
              <HoldingsTrendResults data={analysis} fundNoun="ETFs" askSection="command-center/etf_holdings" askTitle={`ETF Holdings (${market.toUpperCase()})`} marketType={market === 'crypto' ? 'crypto' : market === 'us' ? 'us' : 'india'} />
            </>
          )}
        </CollapsibleScrollSection>
      )}
    </div>
  )
}

/**
 * Command Center — ETF Holdings: India (StockEdge) · US (INDMoney+NPORT) · Crypto (SEC NPORT).
 */
export function EtfHoldingsPanel() {
  const queryClient = useQueryClient()
  const [market, setMarket] = useState<MarketTab>('india')
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
  const handledDoneRef = useRef<Set<string>>(new Set())

  const reportsQuery = useQuery({
    queryKey: ['etf-holdings-reports'],
    queryFn: fetchEtfHoldingsReports,
  })
  const reports = ((reportsQuery.data as { reports?: EtfSavedReportSummary[] } | undefined)?.reports) ?? []

  const runningJobsQuery = useQuery({
    queryKey: ['etf-holdings-jobs-running'],
    queryFn: () => fetchEtfHoldingsJobs('running'),
    refetchInterval: 2000,
  })

  const recentJobsQuery = useQuery({
    queryKey: ['etf-holdings-jobs-recent'],
    queryFn: () => fetchEtfHoldingsJobs('all'),
  })
  const recentJobs = ((recentJobsQuery.data as { jobs?: EtfBgJobStatus[] } | undefined)?.jobs) ?? []
  const recentFinished = recentJobs.filter((j) => j.status !== 'running').slice(0, 8)

  useEffect(() => {
    const serverJobs = ((runningJobsQuery.data as { jobs?: EtfBgJobStatus[] } | undefined)?.jobs) ?? []
    const ids = serverJobs.map((j) => j.job_id)
    if (!ids.length) return
    setBgJobIds((prev) => Array.from(new Set([...ids, ...prev])))
  }, [runningJobsQuery.data])

  const jobQueries = useQueries({
    queries: bgJobIds.map((id) => ({
      queryKey: ['etf-holdings-job', id],
      queryFn: () => fetchEtfHoldingsJob(id) as Promise<EtfBgJobStatus>,
      refetchInterval: (q: { state: { data?: EtfBgJobStatus } }) =>
        q.state.data?.status === 'running' ? 1500 : false,
      refetchIntervalInBackground: true,
      retry: false,
    })),
  })

  const jobById = useMemo(() => {
    const map = new Map<string, EtfBgJobStatus>()
    jobQueries.forEach((q, i) => {
      const id = bgJobIds[i]
      if (id && q.data) map.set(id, q.data as EtfBgJobStatus)
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
      queryClient.invalidateQueries({ queryKey: ['etf-holdings-reports'] })
      queryClient.invalidateQueries({ queryKey: ['etf-holdings-jobs-running'] })
      queryClient.invalidateQueries({ queryKey: ['etf-holdings-jobs-recent'] })
    }
  }, [bgJobIds, jobById, queryClient])

  const ongoingBg = bgJobIds
    .map((id) => jobById.get(id))
    .filter((j): j is EtfBgJobStatus => !!j && j.status === 'running')
  const serverRunning = ((runningJobsQuery.data as { jobs?: EtfBgJobStatus[] } | undefined)?.jobs) ?? []
  const ongoingMap = new Map<string, EtfBgJobStatus>()
  for (const j of [...serverRunning, ...ongoingBg]) {
    if (j.status === 'running') ongoingMap.set(j.job_id, j)
  }
  const ongoingList = Array.from(ongoingMap.values()).sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0))

  const reportDetailQuery = useQuery({
    queryKey: ['etf-holdings-report', viewedReportId],
    queryFn: () => fetchEtfHoldingsReport(viewedReportId as number),
    enabled: viewedReportId != null,
  })
  const viewedReport = reportDetailQuery.data as { name?: string; payload?: HoldingsAnalysisResult; created_at?: string; error?: string } | undefined

  const onJobStarted = (res: EtfHoldingsJobStartResponse) => {
    setBgError('')
    setBgMsg(`Background analysis started${res.name ? `: ${res.name}` : ''}.`)
    setBgReportName('')
    setBgJobIds((prev) => Array.from(new Set([res.job_id, ...prev])))
    queryClient.invalidateQueries({ queryKey: ['etf-holdings-jobs-running'] })
  }

  const startIndiaMutation = useMutation({
    mutationFn: startEtfIndiaHoldingsJob,
    onSuccess: onJobStarted,
    onError: (e) => setBgError(apiErrorMessage(e)),
  })
  const startYahooMutation = useMutation({
    mutationFn: startEtfYahooHoldingsJob,
    onSuccess: onJobStarted,
    onError: (e) => setBgError(apiErrorMessage(e)),
  })

  const saveReportMutation = useMutation({
    mutationFn: saveEtfHoldingsReport,
    onSuccess: () => {
      setSaveMsg('Report saved.')
      setShowSaveForm(false)
      setSaveName('')
      queryClient.invalidateQueries({ queryKey: ['etf-holdings-reports'] })
    },
    onError: (e) => setBgError(apiErrorMessage(e)),
  })

  const deleteReportMutation = useMutation({
    mutationFn: deleteEtfHoldingsReport,
    onSuccess: (_data, reportId) => {
      if (viewedReportId === reportId) setViewedReportId(null)
      queryClient.invalidateQueries({ queryKey: ['etf-holdings-reports'] })
    },
  })

  const bg: BgControls = {
    runInBackground, setRunInBackground, bgReportName, setBgReportName, bgError, bgMsg,
    startIndiaMutation, startYahooMutation, saveReportMutation,
    saveName, setSaveName, showSaveForm, setShowSaveForm, saveMsg,
  }

  return (
    <div className="space-y-4">
      <Card>
        <h3 className="text-base font-semibold text-white">
          ETF Holdings — Stock-Level Trend Across Funds (India · US · Crypto)
        </h3>
        <p className="mt-1 text-sm text-slate-400">
          India via StockEdge; US via INDMoney Companies/Holding % + SEC NPORT history; crypto via SEC NPORT-P.
          Results split into Stock-wise and Sector-wise views.
        </p>
        <button type="button" className="mt-3 text-xs font-medium text-blue-400 hover:text-blue-300" onClick={() => setShowHow((v) => !v)}>
          {showHow ? 'Hide' : 'How this works'}
        </button>
        {showHow && (
          <div className="mt-2 space-y-2 rounded-lg border border-slate-800 bg-slate-900/50 p-3 text-xs text-slate-400">
            <p><strong className="text-slate-300">India</strong> — StockEdge AMCs → ETF schemes → month-end holding %.</p>
            <p><strong className="text-slate-300">US</strong> — INDMoney categories → Companies/Holding %; historical points from SEC NPORT.</p>
            <p><strong className="text-slate-300">Crypto</strong> — crypto-theme equity ETFs via SEC NPORT-P (not spot BTC products).</p>
            <p className="text-amber-400/90">Research / education only — not financial advice.</p>
          </div>
        )}
        <div className="mt-4 flex flex-wrap gap-2">
          {([
            ['india', 'Indian ETFs'],
            ['us', 'US ETFs'],
            ['crypto', 'Crypto ETFs'],
          ] as const).map(([id, label]) => (
            <Chip key={id} selected={market === id} onClick={() => setMarket(id)}>{label}</Chip>
          ))}
        </div>
      </Card>
      <Card>
        {market === 'india' && <IndiaEtfTab bg={bg} />}
        {market === 'us' && (
          <IssuerEtfTab
            market="us"
            note="Browse INDMoney US ETF categories → pick ETF(s) → analyze Companies / Holding % (with SEC NPORT history for your date range)."
            bg={bg}
          />
        )}
        {market === 'crypto' && (
          <IssuerEtfTab
            market="crypto"
            note="Crypto-theme equity ETFs via SEC NPORT-P (historical reporting periods). Spot Bitcoin products aren't used — they don't hold stocks."
            bg={bg}
          />
        )}
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
                  {(job.meta?.names ?? []).slice(0, 4).join(', ')}
                  {(job.meta?.names?.length ?? 0) > 4 ? '…' : ''}
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
                    {(job.meta?.names ?? []).slice(0, 4).join(', ')}
                    {(job.meta?.names?.length ?? 0) > 4 ? '…' : ''}
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
                    {r.asset_class.toUpperCase()} · Saved {formatWhen(r.created_at)}
                    {r.from_date && r.to_date ? ` · ${r.from_date} → ${r.to_date}` : ''}
                  </p>
                  <p className="mt-1 text-xs text-slate-400">
                    {(r.names ?? []).slice(0, 6).join(', ')}
                    {(r.names?.length ?? 0) > 6 ? '…' : ''}
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

      {viewedReportId != null && (
        <Card>
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm text-slate-400">
              Viewing saved report: <span className="text-slate-200">{viewedReport?.name}</span>
              {viewedReport?.created_at ? ` · saved ${formatWhen(viewedReport.created_at)}` : ''}
            </p>
            <Button variant="ghost" size="sm" onClick={() => setViewedReportId(null)}>
              <X size={14} />
            </Button>
          </div>
          {!reportDetailQuery.isLoading && viewedReport?.payload && (
            viewedReport.payload.error ? (
              <Alert type="error">{String(viewedReport.payload.error)}</Alert>
            ) : (
              <HoldingsTrendResults
                data={viewedReport.payload}
                fundNoun="ETFs"
                askSection="command-center/etf_holdings"
                askTitle="ETF Holdings (saved)"
                marketType={String(viewedReport.payload.market ?? 'india') === 'crypto' ? 'crypto' : String(viewedReport.payload.market ?? 'india') === 'us' ? 'us' : 'india'}
                resolveName={String(viewedReport.payload.market ?? 'india') === 'india'}
              />
            )
          )}
          {reportDetailQuery.isLoading && <Loading message="Loading saved report…" />}
        </Card>
      )}
    </div>
  )
}
