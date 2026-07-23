import { Fragment, useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, Eye, Plus, RefreshCw, Trash2 } from 'lucide-react'
import {
  addWatchlistItem,
  apiErrorMessage,
  createWatchlist,
  deleteWatchlist,
  fetchTickerSuggestions,
  fetchWatchlistItems,
  fetchWatchlists,
  removeWatchlistItem,
} from '../api/client'
import { TradeSetupDrillDown } from '../components/command-center/CommandCenterPanels'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Chip } from '../components/ui/Chip'
import { FormField, Input, Select } from '../components/ui/Form'
import { Alert, Loading } from '../components/ui/Feedback'
import { DataTable, SortableTh, Td, Th, useSort } from '../components/ui/Table'

const TIMEFRAMES = ['1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w']

const MARKETS: Array<{ value: 'india' | 'us' | 'crypto'; label: string }> = [
  { value: 'india', label: '🇮🇳 India (Groww)' },
  { value: 'us', label: '🇺🇸 US (Yahoo)' },
  { value: 'crypto', label: '₿ Crypto (CoinDCX)' },
]

function pctClass(v: number | null | undefined) {
  if (v == null) return 'text-slate-500'
  return v >= 0 ? 'text-emerald-400' : 'text-rose-400'
}

function fmtPct(v: number | null | undefined) {
  if (v == null) return '—'
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`
}

export default function WatchlistPage() {
  const qc = useQueryClient()
  const [error, setError] = useState('')
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [newMarket, setNewMarket] = useState<'india' | 'us' | 'crypto'>('india')
  const [newName, setNewName] = useState('My Watchlist')
  const [ticker, setTicker] = useState('')
  const [notes, setNotes] = useState('')
  const [debouncedTicker, setDebouncedTicker] = useState('')
  const [suggestOpen, setSuggestOpen] = useState(false)
  const [analyzeId, setAnalyzeId] = useState<number | null>(null)
  const [timeframeByItem, setTimeframeByItem] = useState<Record<number, string>>({})

  const listsQ = useQuery({ queryKey: ['watchlists'], queryFn: fetchWatchlists })
  const lists = listsQ.data?.watchlists ?? []
  const currentMarket = lists.find((l) => l.id === selectedId)?.market_type ?? newMarket

  useEffect(() => {
    const t = setTimeout(() => setDebouncedTicker(ticker.trim()), 200)
    return () => clearTimeout(t)
  }, [ticker])

  const suggestQ = useQuery({
    queryKey: ['ticker-suggest', currentMarket, debouncedTicker],
    queryFn: () => fetchTickerSuggestions(currentMarket, debouncedTicker, 10),
    enabled: debouncedTicker.length >= 1,
  })
  const suggestions = suggestQ.data?.tickers ?? []

  useEffect(() => {
    if (selectedId == null && lists.length > 0) setSelectedId(lists[0].id)
    if (selectedId != null && !lists.some((l) => l.id === selectedId)) {
      setSelectedId(lists[0]?.id ?? null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lists])

  const itemsQ = useQuery({
    queryKey: ['watchlist-items', selectedId],
    queryFn: () => fetchWatchlistItems(selectedId as number),
    enabled: selectedId != null,
  })

  const createMut = useMutation({
    mutationFn: () => createWatchlist({ market_type: newMarket, name: newName }),
    onSuccess: (wl) => {
      setError('')
      qc.invalidateQueries({ queryKey: ['watchlists'] })
      setSelectedId(wl.id)
    },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const deleteListMut = useMutation({
    mutationFn: (id: number) => deleteWatchlist(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['watchlists'] })
      setSelectedId(null)
    },
  })

  const addItemMut = useMutation({
    mutationFn: () =>
      addWatchlistItem(selectedId as number, {
        ticker: ticker.toUpperCase(), display_name: ticker.toUpperCase(), notes: notes.trim() || undefined,
      }),
    onSuccess: () => {
      setError('')
      setTicker('')
      setNotes('')
      qc.invalidateQueries({ queryKey: ['watchlist-items', selectedId] })
    },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const removeItemMut = useMutation({
    mutationFn: (itemId: number) => removeWatchlistItem(selectedId as number, itemId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['watchlist-items', selectedId] }),
  })

  const items = itemsQ.data?.items ?? []

  const { sorted: sortedItems, sortKey: itemsSortKey, sortDir: itemsSortDir, handleSort: handleItemsSort } = useSort(
    items,
    {
      ticker: (r) => r.display_name || r.ticker,
      ltp: (r) => r.ltp,
      change_pct: (r) => r.change_pct,
      change_since_added_pct: (r) => r.change_since_added_pct,
    },
  )

  return (
    <div>
      <PageHeader title="Watchlists" description="Track tickers across India, US, and Crypto with live prices" />

      <Card className="mb-4">
        <h3 className="mb-4 flex items-center gap-2 font-medium text-white">
          <Plus size={16} />
          New watchlist
        </h3>
        <div className="grid gap-4 sm:grid-cols-3">
          <FormField label="Market">
            <Select value={newMarket} onChange={(e) => setNewMarket(e.target.value as typeof newMarket)}>
              {MARKETS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
            </Select>
          </FormField>
          <FormField label="Name">
            <Input value={newName} onChange={(e) => setNewName(e.target.value)} />
          </FormField>
        </div>
        <Button className="mt-4" onClick={() => createMut.mutate()} disabled={createMut.isPending}>
          Create watchlist
        </Button>
        {error && <div className="mt-3"><Alert type="error">{error}</Alert></div>}
      </Card>

      {lists.length === 0 ? (
        <Card><p className="text-sm text-slate-500">No watchlists yet. Create one above.</p></Card>
      ) : (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-2">
            {lists.map((l) => (
              <Chip key={l.id} selected={selectedId === l.id} onClick={() => setSelectedId(l.id)}>
                {l.name} · {l.market_type}
              </Chip>
            ))}
          </div>

          {selectedId != null && (
            <Card>
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                <h3 className="flex items-center gap-2 font-medium text-white">
                  <Eye size={16} />
                  {lists.find((l) => l.id === selectedId)?.name} ({items.length})
                </h3>
                <div className="flex gap-2">
                  <Button variant="secondary" size="sm" onClick={() => itemsQ.refetch()} disabled={itemsQ.isFetching}>
                    <RefreshCw size={14} className="mr-1.5" />
                    Refresh prices
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => deleteListMut.mutate(selectedId)}
                    disabled={deleteListMut.isPending}
                  >
                    <Trash2 size={14} className="mr-1.5" />
                    Delete list
                  </Button>
                </div>
              </div>

              <div className="mb-4 flex flex-wrap items-end gap-2">
                <FormField label="Add ticker">
                  <div className="relative">
                    <Input
                      value={ticker}
                      onChange={(e) => { setTicker(e.target.value.toUpperCase()); setSuggestOpen(true) }}
                      onFocus={() => setSuggestOpen(true)}
                      onBlur={() => setTimeout(() => setSuggestOpen(false), 120)}
                      onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); setSuggestOpen(false); addItemMut.mutate() } }}
                      placeholder="e.g. RELIANCE"
                      autoComplete="off"
                    />
                    {suggestOpen && debouncedTicker.length >= 1 && (suggestions.length > 0 || suggestQ.isFetching) && (
                      <ul className="absolute z-10 mt-1 max-h-56 w-full overflow-y-auto rounded-lg border border-slate-700/80 bg-slate-900 shadow-lg">
                        {suggestQ.isFetching && suggestions.length === 0 && (
                          <li className="px-3 py-2 text-xs text-slate-500">Searching…</li>
                        )}
                        {suggestions.map((s) => (
                          <li key={s}>
                            <button
                              type="button"
                              onMouseDown={(e) => { e.preventDefault(); setTicker(s); setSuggestOpen(false) }}
                              className="block w-full px-3 py-1.5 text-left text-sm text-slate-200 hover:bg-slate-800"
                            >
                              {s}
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </FormField>
                <FormField label="Notes (optional)">
                  <Input
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addItemMut.mutate() } }}
                    placeholder="Why this ticker?"
                    className="min-w-[220px]"
                  />
                </FormField>
                <Button onClick={() => addItemMut.mutate()} disabled={!ticker.trim() || addItemMut.isPending}>
                  Add
                </Button>
              </div>

              {itemsQ.isFetching && <Loading message="Fetching live prices…" />}

              {!itemsQ.isFetching && items.length === 0 && (
                <p className="text-sm text-slate-500">No tickers yet. Add one above.</p>
              )}

              {!itemsQ.isFetching && items.length > 0 && (
                <DataTable>
                  <thead>
                    <tr>
                      <Th />
                      <SortableTh active={itemsSortKey === 'ticker'} direction={itemsSortDir} onSort={() => handleItemsSort('ticker')}>Ticker</SortableTh>
                      <SortableTh active={itemsSortKey === 'ltp'} direction={itemsSortDir} onSort={() => handleItemsSort('ltp')}>LTP</SortableTh>
                      <SortableTh active={itemsSortKey === 'change_pct'} direction={itemsSortDir} onSort={() => handleItemsSort('change_pct')}>Change %</SortableTh>
                      <SortableTh active={itemsSortKey === 'change_since_added_pct'} direction={itemsSortDir} onSort={() => handleItemsSort('change_since_added_pct')}>Since added</SortableTh>
                      <Th>Notes</Th>
                      <Th />
                    </tr>
                  </thead>
                  <tbody>
                    {sortedItems.map((it) => {
                      const isOpen = analyzeId === it.id
                      const tf = timeframeByItem[it.id] ?? '1d'
                      return (
                        <Fragment key={it.id}>
                          <tr className="hover:bg-slate-800/20">
                            <Td>
                              <button
                                type="button"
                                aria-label={isOpen ? 'Collapse analysis' : 'Analyze ticker'}
                                onClick={() => setAnalyzeId(isOpen ? null : it.id)}
                                className="text-slate-500 hover:text-blue-400"
                              >
                                {isOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                              </button>
                            </Td>
                            <Td className="font-medium">{it.display_name || it.ticker}</Td>
                            <Td>{it.ltp != null ? it.ltp.toLocaleString(undefined, { maximumFractionDigits: 4 }) : '—'}</Td>
                            <Td className={pctClass(it.change_pct)}>{fmtPct(it.change_pct)}</Td>
                            <Td className={pctClass(it.change_since_added_pct)}>{fmtPct(it.change_since_added_pct)}</Td>
                            <Td className="max-w-[220px] truncate text-slate-400">
                              <span title={it.notes ?? ''}>{it.notes || '—'}</span>
                            </Td>
                            <Td>
                              <button
                                type="button"
                                aria-label="Remove ticker"
                                onClick={() => removeItemMut.mutate(it.id)}
                                className="text-slate-500 hover:text-rose-400"
                              >
                                <Trash2 size={16} />
                              </button>
                            </Td>
                          </tr>
                          {isOpen && (
                            <tr>
                              <Td colSpan={7} className="whitespace-normal bg-slate-900/30">
                                <div className="mb-3 flex items-center gap-2">
                                  <span className="text-xs font-medium uppercase tracking-wide text-slate-500">Timeframe</span>
                                  <Select
                                    className="!w-28 !py-1.5"
                                    value={tf}
                                    onChange={(e) => setTimeframeByItem((prev) => ({ ...prev, [it.id]: e.target.value }))}
                                  >
                                    {TIMEFRAMES.map((t) => <option key={t} value={t}>{t}</option>)}
                                  </Select>
                                </div>
                                <TradeSetupDrillDown
                                  ticker={it.ticker}
                                  timeframe={tf}
                                  assetClass={lists.find((l) => l.id === selectedId)?.market_type ?? 'india'}
                                />
                              </Td>
                            </tr>
                          )}
                        </Fragment>
                      )
                    })}
                  </tbody>
                </DataTable>
              )}
            </Card>
          )}
        </>
      )}
    </div>
  )
}
