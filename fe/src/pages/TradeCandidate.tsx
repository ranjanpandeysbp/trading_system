import { useEffect, useMemo, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, Save, Trash2 } from 'lucide-react'
import {
  apiErrorMessage,
  checkTradeCandidate,
  createTradeCandidate,
  deleteTradeCandidate,
  deleteTradeCandidateHit,
  deleteTradeCandidateHits,
  fetchBacktesterLeaderboardCatalog,
  fetchTradeCandidateHits,
  fetchTradeCandidates,
  updateTradeCandidate,
  type TradeCandidate as TradeCandidateRow,
  type TradeCandidateCheckResult,
} from '../api/client'
import {
  AssetClassTickerPicker,
  type AssetClass,
  type TickerPickerValue,
} from '../components/command-center/AssetClassTickerPicker'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Chip } from '../components/ui/Chip'
import { Badge } from '../components/ui/Badge'
import { FormField, Input, Select } from '../components/ui/Form'
import { Alert, Loading } from '../components/ui/Feedback'
import { DataTable, Th, Td } from '../components/ui/Table'

const TIMEFRAMES = ['1m', '3m', '5m', '15m', '30m', '1h', '4h', '1d', '1wk', '1M']

// How often Live Signals re-checks a candidate — matched to its own timeframe,
// per the ask that this tab "refreshes at the chosen timeframe."
const TF_REFRESH_MS: Record<string, number> = {
  '1m': 60_000,
  '3m': 180_000,
  '5m': 300_000,
  '15m': 900_000,
  '30m': 1_800_000,
  '1h': 3_600_000,
  '4h': 14_400_000,
  '1d': 86_400_000,
  '1wk': 604_800_000,
  '1M': 2_592_000_000,
}

// Backend timestamps are naive UTC (`datetime.utcnow()`, no "Z"/offset suffix) —
// append "Z" so Date parses them as UTC, then format explicitly in IST so the
// displayed time is correct regardless of the viewing browser's own timezone.
function formatIST(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso.endsWith('Z') || /[+-]\d{2}:\d{2}$/.test(iso) ? iso : `${iso}Z`)
  if (Number.isNaN(d.getTime())) return iso
  return `${d.toLocaleString('en-IN', {
    timeZone: 'Asia/Kolkata',
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  })} IST`
}

const TABS = [
  { id: 'configure', label: 'Configure' },
  { id: 'signals-crypto', label: 'Live Signals · Crypto' },
  { id: 'signals-india', label: 'Live Signals · India' },
  { id: 'signals-us', label: 'Live Signals · US' },
  { id: 'signals-commodity', label: 'Live Signals · Commodities' },
  { id: 'setups', label: 'Saved Setups' },
  { id: 'history-crypto', label: 'Trigger History · Crypto' },
  { id: 'history-india', label: 'Trigger History · India' },
  { id: 'history-us', label: 'Trigger History · US' },
  { id: 'history-commodity', label: 'Trigger History · Commodities' },
] as const
type TabId = (typeof TABS)[number]['id']
type AssetClassFilter = 'india' | 'us' | 'crypto' | 'commodity'

const SIGNALS_TAB_ASSET_CLASS: Partial<Record<TabId, AssetClassFilter>> = {
  'signals-crypto': 'crypto',
  'signals-india': 'india',
  'signals-us': 'us',
  'signals-commodity': 'commodity',
}

const HISTORY_TAB_ASSET_CLASS: Partial<Record<TabId, AssetClassFilter>> = {
  'history-crypto': 'crypto',
  'history-india': 'india',
  'history-us': 'us',
  'history-commodity': 'commodity',
}

export default function TradeCandidate() {
  const params = useParams<{ tab: string }>()
  const navigate = useNavigate()
  const tab: TabId = (TABS.find((t) => t.id === params.tab)?.id ?? 'configure')

  return (
    <div>
      <PageHeader
        title="Trade Candidate"
        description="Configure a ticker + timeframe + strategy set, then watch it live for BUY/SELL triggers"
      />

      <div className="mb-4 flex flex-wrap gap-2">
        {TABS.map((t) => (
          <Chip key={t.id} selected={tab === t.id} onClick={() => navigate(`/trade-candidate/${t.id}`)}>
            {t.label}
          </Chip>
        ))}
      </div>

      {tab === 'configure' && <ConfigurePanel onSaved={() => navigate('/trade-candidate/setups')} />}
      {SIGNALS_TAB_ASSET_CLASS[tab] && <LiveSignalsPanel assetClass={SIGNALS_TAB_ASSET_CLASS[tab]!} />}
      {tab === 'setups' && <SavedSetupsPanel />}
      {HISTORY_TAB_ASSET_CLASS[tab] && <TriggerHistoryPanel assetClass={HISTORY_TAB_ASSET_CLASS[tab]!} />}
    </div>
  )
}

function ConfigurePanel({ onSaved }: { onSaved: () => void }) {
  const qc = useQueryClient()
  const [assetClass, setAssetClass] = useState<AssetClass>('india')
  const [picker, setPicker] = useState<TickerPickerValue>({ tickers: [], durations: [] })
  const [timeframe, setTimeframe] = useState('15m')
  const [selectedStrategies, setSelectedStrategies] = useState<string[]>([])
  const [name, setName] = useState('')
  const [error, setError] = useState('')

  const {
    data: catalog,
    isLoading: categoriesLoading,
    isError: categoriesError,
    error: categoriesFetchError,
  } = useQuery({ queryKey: ['bt-catalog'], queryFn: fetchBacktesterLeaderboardCatalog })

  const categories = catalog?.categories ?? []
  const strategies = categories.flatMap((c) => c.strategies)
  const totalStrategyCount = categories.reduce((n, c) => n + c.strategy_count, 0)

  const ticker = picker.tickers[0] ?? ''

  const toggleStrategy = (id: string) =>
    setSelectedStrategies((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))

  const createMut = useMutation({
    mutationFn: () =>
      createTradeCandidate({
        name: name.trim() || undefined,
        asset_class: assetClass,
        ticker,
        timeframe,
        strategies: selectedStrategies,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['trade-candidates'] })
      setError('')
      setSelectedStrategies([])
      setName('')
      onSaved()
    },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const handleSave = () => {
    if (!ticker || !timeframe || !selectedStrategies.length) {
      setError('Select an asset class ticker, a timeframe, and at least one strategy')
      return
    }
    createMut.mutate()
  }

  return (
    <Card>
      <h3 className="mb-4 font-medium text-white">New trade candidate setup</h3>

      <div className="grid gap-4 sm:grid-cols-2">
        <FormField label="Asset class">
          <Select value={assetClass} onChange={(e) => { setAssetClass(e.target.value as AssetClass); setPicker({ tickers: [], durations: [] }) }}>
            <option value="india">🇮🇳 Indian stocks (Groww / NSE)</option>
            <option value="us">🇺🇸 US stocks (Yahoo)</option>
            <option value="crypto">₿ Crypto (CoinDCX)</option>
            <option value="commodity">🛢️ Commodity futures</option>
          </Select>
        </FormField>
        <FormField label="Timeframe">
          <Select value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
            {TIMEFRAMES.map((tf) => (
              <option key={tf} value={tf}>{tf}</option>
            ))}
          </Select>
        </FormField>
      </div>

      <div className="mt-4">
        <AssetClassTickerPicker key={assetClass} assetClass={assetClass} single showDurations={false} onChange={setPicker} />
      </div>

      <div className="mt-4">
        <FormField label="Setup name (optional)">
          <Input
            placeholder={ticker ? `${ticker} · ${timeframe}` : 'Auto-generated from ticker + timeframe'}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </FormField>
      </div>

      <div className="mt-4">
        <FormField label={`Strategies (${selectedStrategies.length} of ${totalStrategyCount} selected)`}>
          {categoriesLoading && <Loading message="Loading strategies…" />}
          {categoriesError && <Alert type="error">{apiErrorMessage(categoriesFetchError)}</Alert>}
          {!categoriesLoading && !categoriesError && (
            <>
              <div className="max-h-72 space-y-3 overflow-y-auto rounded-xl border border-slate-800/60 bg-slate-800/20 p-3">
                {categories.map((cat) => (
                  <div key={cat.id}>
                    <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
                      {cat.label} · {cat.timeframes.join(', ')}
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {cat.strategies.map((s) => (
                        <Chip
                          key={s.id}
                          selected={selectedStrategies.includes(s.id)}
                          onClick={() => toggleStrategy(s.id)}
                          title={s.summary}
                        >
                          {s.name}
                        </Chip>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button variant="secondary" size="sm" onClick={() => setSelectedStrategies(strategies.map((s) => s.id))}>
                  Select All
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setSelectedStrategies([])}>
                  Clear
                </Button>
              </div>
            </>
          )}
        </FormField>
      </div>

      <Button className="mt-4" onClick={handleSave} disabled={createMut.isPending}>
        <Save size={16} />
        {createMut.isPending ? 'Saving…' : 'Save setup'}
      </Button>
      {error && <div className="mt-3"><Alert type="error">{error}</Alert></div>}
    </Card>
  )
}

function useCandidateCheck(candidate: TradeCandidateRow) {
  const refreshMs = TF_REFRESH_MS[candidate.timeframe] ?? 900_000
  return useQuery<TradeCandidateCheckResult>({
    queryKey: ['trade-candidate-check', candidate.id],
    queryFn: () => checkTradeCandidate(candidate.id),
    refetchInterval: refreshMs,
    refetchIntervalInBackground: true,
  })
}

function LiveSignalsPanel({ assetClass }: { assetClass: AssetClassFilter }) {
  const candidatesQ = useQuery({ queryKey: ['trade-candidates'], queryFn: fetchTradeCandidates })
  const candidates = (candidatesQ.data?.candidates ?? []).filter(
    (c) => c.enabled && c.asset_class === assetClass,
  )

  if (candidatesQ.isLoading) return <Loading message="Loading saved setups…" />

  if (!candidates.length) {
    return (
      <Card>
        <p className="text-sm text-slate-500">
          No enabled {assetClass} trade candidates yet. Create one in Configure, or enable one in Saved Setups.
        </p>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      {candidates.map((c) => (
        <CandidateSignalCard key={c.id} candidate={c} />
      ))}
    </div>
  )
}

function CandidateSignalCard({ candidate }: { candidate: TradeCandidateRow }) {
  const { data, isFetching, isError, error, refetch } = useCandidateCheck(candidate)
  const refreshMs = TF_REFRESH_MS[candidate.timeframe] ?? 900_000
  const refreshLabel = refreshMs >= 3_600_000 ? `${Math.round(refreshMs / 3_600_000)}h` : `${Math.round(refreshMs / 60_000)}m`

  return (
    <Card>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="font-medium text-white">{candidate.name}</h3>
          <p className="text-xs text-slate-500">
            {candidate.ticker} · {candidate.timeframe} · {candidate.asset_class} · auto-refresh every {refreshLabel}
            {data?.checked_at && ` · last checked ${new Date(data.checked_at).toLocaleTimeString()}`}
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={() => refetch()} disabled={isFetching}>
          <RefreshCw size={14} className={isFetching ? 'animate-spin' : ''} />
          Refresh now
        </Button>
      </div>

      {isError && <Alert type="error">{apiErrorMessage(error)}</Alert>}

      {data && (
        <DataTable minWidth={640}>
          <thead>
            <tr>
              <Th>Strategy</Th>
              <Th>Signal</Th>
              <Th>Confidence</Th>
              <Th>SL%</Th>
              <Th>TP%</Th>
              <Th>Price</Th>
              <Th>Reason</Th>
            </tr>
          </thead>
          <tbody>
            {data.results.map((r) => (
              <tr key={r.strategy_id}>
                <Td className="font-medium">{r.strategy_label}</Td>
                <Td><Badge action={r.action} /></Td>
                <Td>{r.confidence_pct ? `${r.confidence_pct.toFixed(0)}%` : '—'}</Td>
                <Td>{r.sl_pct ? `${r.sl_pct.toFixed(1)}%` : '—'}</Td>
                <Td>{r.tp_pct ? `${r.tp_pct.toFixed(1)}%` : '—'}</Td>
                <Td>{r.price ? r.price.toFixed(2) : '—'}</Td>
                <Td className="max-w-xs truncate text-xs text-slate-400" title={r.rationale}>{r.rationale || '—'}</Td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      )}
    </Card>
  )
}

function SavedSetupsPanel() {
  const qc = useQueryClient()
  const candidatesQ = useQuery({ queryKey: ['trade-candidates'], queryFn: fetchTradeCandidates })
  const candidates = candidatesQ.data?.candidates ?? []

  const toggleMut = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) => updateTradeCandidate(id, { enabled }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['trade-candidates'] }),
  })
  const deleteMut = useMutation({
    mutationFn: (id: number) => deleteTradeCandidate(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['trade-candidates'] }),
  })

  if (candidatesQ.isLoading) return <Loading message="Loading saved setups…" />

  return (
    <Card>
      <h3 className="mb-4 font-medium text-white">Saved setups ({candidates.length})</h3>
      {candidates.length === 0 ? (
        <p className="text-sm text-slate-500">No trade candidates saved yet — create one in Configure.</p>
      ) : (
        <DataTable minWidth={760}>
          <thead>
            <tr>
              <Th>Name</Th>
              <Th>Ticker</Th>
              <Th>TF</Th>
              <Th>Asset class</Th>
              <Th>Strategies</Th>
              <Th>Last checked</Th>
              <Th>Status</Th>
              <Th />
            </tr>
          </thead>
          <tbody>
            {candidates.map((c) => (
              <tr key={c.id}>
                <Td className="font-medium">{c.name}</Td>
                <Td>{c.ticker}</Td>
                <Td>{c.timeframe}</Td>
                <Td>{c.asset_class}</Td>
                <Td className="max-w-[10rem] truncate text-xs" title={c.strategies.join(', ')}>{c.strategies.length}</Td>
                <Td className="text-xs text-slate-400">
                  {c.last_checked_at ? new Date(c.last_checked_at).toLocaleString() : 'Never'}
                </Td>
                <Td>
                  <button
                    type="button"
                    onClick={() => toggleMut.mutate({ id: c.id, enabled: !c.enabled })}
                    className="text-sm text-blue-400 hover:underline"
                  >
                    {c.enabled ? 'Enabled' : 'Disabled'}
                  </button>
                </Td>
                <Td>
                  <button type="button" aria-label="Delete setup" onClick={() => deleteMut.mutate(c.id)} className="text-slate-500 hover:text-rose-400">
                    <Trash2 size={16} />
                  </button>
                </Td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      )}
    </Card>
  )
}

function TriggerHistoryPanel({ assetClass }: { assetClass: AssetClassFilter }) {
  const qc = useQueryClient()
  const [selected, setSelected] = useState<number[]>([])
  const hitsQ = useQuery({ queryKey: ['trade-candidate-hits'], queryFn: () => fetchTradeCandidateHits({ limit: 200 }) })
  const hits = useMemo(
    () => (hitsQ.data?.hits ?? []).filter((h) => h.asset_class === assetClass),
    [hitsQ.data, assetClass],
  )

  useEffect(() => {
    setSelected((prev) => prev.filter((id) => hits.some((h) => h.id === id)))
  }, [hits])

  const deleteMut = useMutation({
    mutationFn: (id: number) => deleteTradeCandidateHit(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['trade-candidate-hits'] }),
  })
  const deleteBulkMut = useMutation({
    mutationFn: (payload: { ids?: number[]; delete_all?: boolean }) => deleteTradeCandidateHits(payload),
    onSuccess: () => {
      setSelected([])
      qc.invalidateQueries({ queryKey: ['trade-candidate-hits'] })
    },
  })

  const ids = hits.map((h) => h.id)
  const allSelected = ids.length > 0 && ids.every((id) => selected.includes(id))
  const toggle = (id: number) => setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  const toggleAll = () => setSelected(allSelected ? [] : ids)

  if (hitsQ.isLoading) return <Loading message="Loading trigger history…" />

  return (
    <Card>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-medium text-white">Trigger history ({hits.length})</h3>
        {hits.length > 0 && (
          <div className="flex flex-wrap gap-2">
            <Button
              variant="secondary"
              disabled={selected.length === 0 || deleteBulkMut.isPending}
              onClick={() => deleteBulkMut.mutate({ ids: selected })}
            >
              <Trash2 size={14} className="mr-1.5" />
              Delete selected ({selected.length})
            </Button>
            <Button
              variant="danger"
              disabled={deleteBulkMut.isPending}
              onClick={() => {
                if (window.confirm(`Delete ALL ${assetClass} trigger history? This cannot be undone.`)) {
                  deleteBulkMut.mutate({ ids: ids })
                }
              }}
            >
              Delete all
            </Button>
          </div>
        )}
      </div>

      {hits.length === 0 ? (
        <p className="text-sm text-slate-500">No triggers yet. Check a candidate in Live Signals to populate.</p>
      ) : (
        <DataTable minWidth={780} title={`Trigger History - ${assetClass}`}>
          <thead>
            <tr>
              <Th>
                <input type="checkbox" checked={allSelected} onChange={toggleAll} aria-label="Select all hits" />
              </Th>
              <Th>When</Th>
              <Th>Setup</Th>
              <Th>Strategy</Th>
              <Th>Ticker</Th>
              <Th>TF</Th>
              <Th>Signal</Th>
              <Th>Confidence</Th>
              <Th />
            </tr>
          </thead>
          <tbody>
            {hits.map((h) => (
              <tr key={h.id}>
                <Td>
                  <input type="checkbox" checked={selected.includes(h.id)} onChange={() => toggle(h.id)} aria-label={`Select hit ${h.id}`} />
                </Td>
                <Td className="text-xs">{formatIST(h.created_at)}</Td>
                <Td>{h.candidate_name}</Td>
                <Td className="text-xs">{h.strategy_label}</Td>
                <Td className="font-medium">{h.ticker}</Td>
                <Td>{h.timeframe}</Td>
                <Td><Badge action={h.verdict} /></Td>
                <Td>{h.confidence_pct ? `${h.confidence_pct.toFixed(0)}%` : '—'}</Td>
                <Td>
                  <button type="button" aria-label="Delete hit" onClick={() => deleteMut.mutate(h.id)} className="text-slate-500 hover:text-rose-400">
                    <Trash2 size={16} />
                  </button>
                </Td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      )}
    </Card>
  )
}
