import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Eye, Plus, RefreshCw, Trash2 } from 'lucide-react'
import {
  addWatchlistItem,
  apiErrorMessage,
  createWatchlist,
  deleteWatchlist,
  fetchWatchlistItems,
  fetchWatchlists,
  removeWatchlistItem,
} from '../api/client'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Chip } from '../components/ui/Chip'
import { FormField, Input, Select } from '../components/ui/Form'
import { Alert, Loading } from '../components/ui/Feedback'
import { DataTable, Td, Th } from '../components/ui/Table'

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

  const listsQ = useQuery({ queryKey: ['watchlists'], queryFn: fetchWatchlists })
  const lists = listsQ.data?.watchlists ?? []

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
      addWatchlistItem(selectedId as number, { ticker: ticker.toUpperCase(), display_name: ticker.toUpperCase() }),
    onSuccess: () => {
      setError('')
      setTicker('')
      qc.invalidateQueries({ queryKey: ['watchlist-items', selectedId] })
    },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const removeItemMut = useMutation({
    mutationFn: (itemId: number) => removeWatchlistItem(selectedId as number, itemId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['watchlist-items', selectedId] }),
  })

  const items = itemsQ.data?.items ?? []

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
                  <Input
                    value={ticker}
                    onChange={(e) => setTicker(e.target.value.toUpperCase())}
                    placeholder="e.g. RELIANCE"
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
                      <Th>Ticker</Th>
                      <Th>LTP</Th>
                      <Th>Change %</Th>
                      <Th>Since added</Th>
                      <Th />
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((it) => (
                      <tr key={it.id}>
                        <Td className="font-medium">{it.display_name || it.ticker}</Td>
                        <Td>{it.ltp != null ? it.ltp.toLocaleString(undefined, { maximumFractionDigits: 4 }) : '—'}</Td>
                        <Td className={pctClass(it.change_pct)}>{fmtPct(it.change_pct)}</Td>
                        <Td className={pctClass(it.change_since_added_pct)}>{fmtPct(it.change_since_added_pct)}</Td>
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
                    ))}
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
