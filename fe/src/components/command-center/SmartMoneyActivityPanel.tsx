import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight } from 'lucide-react'
import {
  apiErrorMessage,
  fetchEtfHoldingsAmcs,
  fetchEtfHoldingsIssuers,
  fetchEtfHoldingsSchemes,
  fetchEtfIssuerSchemes,
  fetchMutualFundAmcs,
  fetchMutualFundSchemes,
  runSmartMoneyActivity,
  type EtfIssuer,
  type EtfIssuerScheme,
  type MutualFundAmc,
  type MutualFundScheme,
  type SmartMoneyActivityResult,
  type SmartMoneyTickerResult,
} from '../../api/client'
import {
  AssetClassTickerPicker,
  type AssetClass,
  type TickerPickerValue,
} from './AssetClassTickerPicker'
import { AddToWatchlistButton } from '../watchlist/AddToWatchlistButton'
import type { WatchlistMarket } from '../watchlist/WatchlistMarketContext'
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

function signalBadge(signal: string) {
  const s = signal.toUpperCase()
  if (s === 'ADD_LONG' || s === 'BULLISH') {
    return <span className="rounded bg-emerald-500/15 px-2 py-0.5 text-xs font-medium text-emerald-400">{s.replace('_', ' ')}</span>
  }
  if (s === 'SELL_AVOID' || s === 'BEARISH') {
    return <span className="rounded bg-rose-500/15 px-2 py-0.5 text-xs font-medium text-rose-400">{s.replace('_', ' ')}</span>
  }
  return <span className="rounded bg-slate-500/15 px-2 py-0.5 text-xs font-medium text-slate-400">WAIT</span>
}

function ResultRow({ r, market }: { r: SmartMoneyTickerResult; market: WatchlistMarket }) {
  return (
    <tr>
      <Td className="font-medium text-white">{r.ticker}</Td>
      <Td>{signalBadge(r.signal)}</Td>
      <Td className="text-xs text-slate-300">{r.bias}</Td>
      <Td className="text-xs">{r.found ? (r.overall_trend ?? '—') : 'not found'}</Td>
      <Td className="text-xs tabular-nums">
        {r.avg_change_pct != null ? `${r.avg_change_pct > 0 ? '+' : ''}${r.avg_change_pct.toFixed(3)}%` : '—'}
      </Td>
      <Td className="text-xs">
        {r.schemes_increasing ?? 0}↑ / {r.schemes_decreasing ?? 0}↓
        {r.n_schemes != null ? ` · ${r.n_schemes} funds` : ''}
      </Td>
      <Td className="max-w-md text-xs text-slate-400" title={r.summary}>{r.summary}</Td>
      <Td>
        <AddToWatchlistButton
          ticker={r.ticker}
          displayName={r.ticker}
          notes={`Smart money · ${r.signal} · ${r.overall_trend ?? ''} · ${r.summary ?? ''}`.slice(0, 240)}
          marketType={market}
          compact
        />
      </Td>
    </tr>
  )
}

type SchemeKind = 'mf' | 'etf'

/**
 * Command Center — Check Smart Money Activity.
 * Pick fund house(s) → pick fund/ETF(s) → ticker(s) + date range → stake-flow signals.
 */
export function SmartMoneyActivityPanel() {
  const [market, setMarket] = useState<AssetClass>('india')
  const [picker, setPicker] = useState<TickerPickerValue>({ tickers: [], durations: ['1d'] })
  const [source, setSource] = useState<SourceMode>('both')
  const [fromDate, setFromDate] = useState(isoDaysAgo(180))
  const [toDate, setToDate] = useState(isoDaysAgo(0))
  const [error, setError] = useState('')
  const [result, setResult] = useState<SmartMoneyActivityResult | null>(null)

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

  const scanMutation = useMutation({
    mutationFn: () => {
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

      return runSmartMoneyActivity({
        tickers: picker.tickers,
        asset_class,
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
      })
    },
    onSuccess: (data) => {
      setError('')
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

  const summary = result?.summary
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

      {result && !scanMutation.isPending && (
        <Card>
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="font-medium text-white">Results</h3>
            {summary && (
              <p className="text-xs text-slate-500">
                {summary.found}/{summary.tickers} found · Bullish {summary.bullish} · Bearish{' '}
                {summary.bearish} · Wait {summary.wait}
              </p>
            )}
          </div>
          {(result.notes?.length ?? 0) > 0 && (
            <ul className="mb-3 list-inside list-disc text-xs text-slate-500">
              {result.notes!.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          )}
          {(result.preferred_amcs?.length ?? 0) > 0 && (
            <p className="mb-3 text-xs text-slate-500">
              AMCs: {result.preferred_amcs!.map((a) => a.name).join(' · ')}
            </p>
          )}
          {(result.results?.length ?? 0) === 0 ? (
            <p className="text-sm text-slate-500">No results.</p>
          ) : (
            <DataTable minWidth={980}>
              <thead>
                <tr>
                  <Th>Ticker</Th>
                  <Th>Signal</Th>
                  <Th>Bias</Th>
                  <Th>Trend</Th>
                  <Th>Avg Δ stake</Th>
                  <Th>Funds</Th>
                  <Th>Summary</Th>
                  <Th>Watch</Th>
                </tr>
              </thead>
              <tbody>
                {(result.results ?? []).map((r) => (
                  <ResultRow key={r.ticker} r={r} market={watchMarket} />
                ))}
              </tbody>
            </DataTable>
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
