import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  apiErrorMessage,
  fetchEtfHoldingsAmcs,
  fetchEtfHoldingsIssuers,
  fetchEtfHoldingsSchemes,
  fetchEtfIssuerSchemes,
  runEtfIndiaHoldingsChange,
  runEtfYahooHoldingsChange,
  type EtfIssuer,
  type EtfIssuerScheme,
  type MutualFundAmc,
  type MutualFundScheme,
} from '../../api/client'
import { HoldingsTrendResults, type HoldingsAnalysisResult } from './HoldingsTrendResults'
import { Alert, Loading } from '../ui/Feedback'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { FormField } from '../ui/Form'
import { DataTable, Td, Th } from '../ui/Table'

type MarketTab = 'india' | 'us' | 'crypto'

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

function IndiaEtfTab() {
  const [selectedAmcIds, setSelectedAmcIds] = useState<number[]>([])
  const [schemesByAmc, setSchemesByAmc] = useState<Record<number, MutualFundScheme[]>>({})
  const [selectedSchemeIds, setSelectedSchemeIds] = useState<Record<number, number[]>>({})
  const [fromDate, setFromDate] = useState(isoDaysAgo(365))
  const [toDate, setToDate] = useState(isoDaysAgo(0))
  const [amcFilter, setAmcFilter] = useState('')
  const [loadError, setLoadError] = useState('')

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

  const analysis = analyzeMutation.data as HoldingsAnalysisResult | undefined
  const loadedAmcIds = Object.keys(schemesByAmc).map(Number)

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
        <FormField label={`Select AMC(s) — ${amcs.length} loaded`}>
          <input
            className="mb-2 w-full max-w-md rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
            placeholder="Filter by name…"
            value={amcFilter}
            onChange={(e) => setAmcFilter(e.target.value)}
          />
          <div className="flex max-h-40 flex-wrap gap-1.5 overflow-y-auto rounded-lg border border-slate-800 p-2">
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
        </FormField>
      )}
      {loadedAmcIds.length > 0 && (
        <div className="space-y-6">
          <p className="text-xs text-slate-500">{selectedSchemes.length} ETF(s) selected.</p>
          {loadedAmcIds.map((amcId) => {
            const schemes = schemesByAmc[amcId] ?? []
            const selected = selectedSchemeIds[amcId] ?? []
            const amcName = amcNames.get(amcId) ?? String(amcId)
            return (
              <div key={amcId}>
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <h4 className="text-sm font-semibold text-white">{amcName} — {schemes.length} ETF scheme(s)</h4>
                  <div className="flex gap-2">
                    <Button size="sm" variant="ghost" disabled={!schemes.length} onClick={() => setSelectedSchemeIds((prev) => ({ ...prev, [amcId]: schemes.map(schemeKey) }))}>Select all</Button>
                    <Button size="sm" variant="ghost" disabled={!selected.length} onClick={() => setSelectedSchemeIds((prev) => ({ ...prev, [amcId]: [] }))}>Clear</Button>
                  </div>
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
              </div>
            )
          })}
          {selectedSchemes.length > 0 ? (
            <div className="space-y-4 border-t border-slate-800 pt-4">
              <div className="grid gap-4 sm:grid-cols-[1fr_1fr_auto]">
                <FormField label="From date">
                  <input type="date" className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100" value={fromDate} onChange={(e) => setFromDate(e.target.value)} />
                </FormField>
                <FormField label="To date">
                  <input type="date" className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100" value={toDate} onChange={(e) => setToDate(e.target.value)} />
                </FormField>
                <div className="flex items-end">
                  <Button className="w-full" onClick={() => analyzeMutation.mutate()} disabled={analyzeMutation.isPending}>
                    {analyzeMutation.isPending ? 'Analyzing…' : 'Analyze Holding Change'}
                  </Button>
                </div>
              </div>
              {analyzeMutation.isError && <Alert type="error">{apiErrorMessage(analyzeMutation.error)}</Alert>}
            </div>
          ) : (
            <p className="text-sm text-slate-500">Select one or more ETF schemes from the table(s) above.</p>
          )}
        </div>
      )}
      {analyzeMutation.isPending && <Loading message="Fetching month-end ETF holdings…" />}
      {analysis && !analyzeMutation.isPending && (
        analysis.error
          ? <Alert type="error">{analysis.error}</Alert>
          : <HoldingsTrendResults data={analysis} fundNoun="ETFs" askSection="command-center/etf_holdings" askTitle="ETF Holdings (India)" />
      )}
    </div>
  )
}

function IssuerEtfTab({
  market,
  note,
}: {
  market: 'us' | 'crypto'
  note: string
}) {
  const [selectedIssuers, setSelectedIssuers] = useState<string[]>([])
  const [schemesByIssuer, setSchemesByIssuer] = useState<Record<string, EtfIssuerScheme[]>>({})
  const [selectedByIssuer, setSelectedByIssuer] = useState<Record<string, string[]>>({})
  const [fromDate, setFromDate] = useState(isoDaysAgo(400))
  const [toDate, setToDate] = useState(isoDaysAgo(0))
  const [issuerFilter, setIssuerFilter] = useState('')
  const [loadError, setLoadError] = useState('')

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

  const analysis = analyzeMutation.data as HoldingsAnalysisResult | undefined
  const loadedIssuers = Object.keys(schemesByIssuer)
  const loadLabel = market === 'us' ? 'Load All Categories' : 'Load All Issuers'

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
        <FormField label={`${market === 'us' ? 'Categories' : 'Issuers'} — ${issuers.length} loaded`}>
          <input
            className="mb-2 w-full max-w-md rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
            placeholder="Filter…"
            value={issuerFilter}
            onChange={(e) => setIssuerFilter(e.target.value)}
          />
          <div className="flex max-h-40 flex-wrap gap-1.5 overflow-y-auto rounded-lg border border-slate-800 p-2">
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
        </FormField>
      )}
      {loadedIssuers.length > 0 && (
        <div className="space-y-6">
          <p className="text-xs text-slate-500">{selected.length} ETF(s) selected.</p>
          {loadedIssuers.map((issuer) => {
            const schemes = schemesByIssuer[issuer] ?? []
            const picked = selectedByIssuer[issuer] ?? []
            return (
              <div key={issuer}>
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <h4 className="text-sm font-semibold text-white">{issuer} — {schemes.length} ETF(s)</h4>
                  <div className="flex gap-2">
                    <Button size="sm" variant="ghost" disabled={!schemes.length} onClick={() => setSelectedByIssuer((prev) => ({ ...prev, [issuer]: schemes.map((s) => String(s.ID)) }))}>Select all</Button>
                    <Button size="sm" variant="ghost" disabled={!picked.length} onClick={() => setSelectedByIssuer((prev) => ({ ...prev, [issuer]: [] }))}>Clear</Button>
                  </div>
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
              </div>
            )
          })}
          {selected.length > 0 ? (
            <div className="space-y-4 border-t border-slate-800 pt-4">
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
                  <Button className="w-full" onClick={() => analyzeMutation.mutate()} disabled={analyzeMutation.isPending}>
                    {analyzeMutation.isPending ? 'Analyzing…' : 'Analyze Holding Change'}
                  </Button>
                </div>
              </div>
              {analyzeMutation.isError && <Alert type="error">{apiErrorMessage(analyzeMutation.error)}</Alert>}
            </div>
          ) : (
            <p className="text-sm text-slate-500">Select one or more ETFs from the table(s) above.</p>
          )}
        </div>
      )}
      {analyzeMutation.isPending && <Loading message="Fetching ETF holdings…" />}
      {analysis && !analyzeMutation.isPending && (
        analysis.error
          ? <Alert type="error">{analysis.error}</Alert>
          : <HoldingsTrendResults data={analysis} fundNoun="ETFs" askSection="command-center/etf_holdings" askTitle={`ETF Holdings (${market.toUpperCase()})`} />
      )}
    </div>
  )
}

/**
 * Command Center — ETF Holdings: India (StockEdge) · US (INDMoney+NPORT) · Crypto (SEC NPORT).
 */
export function EtfHoldingsPanel() {
  const [market, setMarket] = useState<MarketTab>('india')
  const [showHow, setShowHow] = useState(false)

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
        {market === 'india' && <IndiaEtfTab />}
        {market === 'us' && (
          <IssuerEtfTab
            market="us"
            note="Browse INDMoney US ETF categories → pick ETF(s) → analyze Companies / Holding % (with SEC NPORT history for your date range)."
          />
        )}
        {market === 'crypto' && (
          <IssuerEtfTab
            market="crypto"
            note="Crypto-theme equity ETFs via SEC NPORT-P (historical reporting periods). Spot Bitcoin products aren't used — they don't hold stocks."
          />
        )}
      </Card>
    </div>
  )
}
