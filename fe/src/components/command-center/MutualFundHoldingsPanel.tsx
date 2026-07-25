import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  apiErrorMessage,
  fetchMutualFundAmcs,
  fetchMutualFundSchemes,
  runMutualFundHoldingsChange,
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
  const [selectedAmcIds, setSelectedAmcIds] = useState<number[]>([])
  const [schemesByAmc, setSchemesByAmc] = useState<Record<number, MutualFundScheme[]>>({})
  const [selectedSchemeIds, setSelectedSchemeIds] = useState<Record<number, number[]>>({})
  const [fromDate, setFromDate] = useState(isoDaysAgo(180))
  const [toDate, setToDate] = useState(isoDaysAgo(0))
  const [amcFilter, setAmcFilter] = useState('')
  const [showHow, setShowHow] = useState(false)
  const [loadError, setLoadError] = useState('')

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

  const analysis = analyzeMutation.data as HoldingsAnalysisResult | undefined
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
          <div className="mt-2 space-y-2 rounded-lg border border-slate-800 bg-slate-900/50 p-3 text-xs text-slate-400">
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
          </div>
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
          <div className="mt-4 space-y-3">
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
                    <Chip key={id} selected={selectedAmcIds.includes(id)} onClick={() => toggleAmc(id)}>
                      {a.Name}
                      {a.AUM != null ? ` · ₹${fmtAum(a.AUM)} Cr` : ''}
                    </Chip>
                  )
                })}
              </div>
            </FormField>
            {selectedAmcIds.length > 0 && (
              <p className="text-xs text-slate-500">{selectedAmcIds.length} AMC(s) selected</p>
            )}
          </div>
        )}
      </Card>

      {loadedAmcIds.length > 0 && (
        <Card>
          <p className="mb-3 text-xs text-slate-500">
            {selectedSchemes.length} fund(s) selected across AMCs.
          </p>
          <div className="space-y-6">
            {loadedAmcIds.map((amcId) => {
              const schemes = schemesByAmc[amcId] ?? []
              const selected = selectedSchemeIds[amcId] ?? []
              const amcName = amcNames.get(amcId) ?? String(amcId)
              return (
                <div key={amcId}>
                  <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <h4 className="text-sm font-semibold text-white">
                      {amcName} — {schemes.length} equity scheme(s)
                    </h4>
                    <div className="flex gap-2">
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
                </div>
              )
            })}
          </div>

          {selectedSchemes.length > 0 ? (
            <div className="mt-6 space-y-4 border-t border-slate-800 pt-4">
              <p className="text-sm text-emerald-400/90">
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
                    onClick={() => analyzeMutation.mutate()}
                    disabled={analyzeMutation.isPending}
                  >
                    {analyzeMutation.isPending ? 'Analyzing…' : 'Analyze Holding Change'}
                  </Button>
                </div>
              </div>
              {analyzeMutation.isError && (
                <Alert type="error">{apiErrorMessage(analyzeMutation.error)}</Alert>
              )}
            </div>
          ) : (
            <p className="mt-4 text-sm text-slate-500">Select one or more mutual funds from the table(s) above.</p>
          )}
        </Card>
      )}

      {analyzeMutation.isPending && <Loading message="Fetching month-end holdings across selected funds…" />}

      {analysis && !analyzeMutation.isPending && (
        <Card>
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
        </Card>
      )}
    </div>
  )
}
