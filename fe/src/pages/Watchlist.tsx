import { Fragment, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bot, ChartCandlestick, Check, ChevronDown, ChevronRight, Copy, Eye, LineChart, Pencil, Plus, RefreshCw, Share2, Trash2, X } from 'lucide-react'
import {
  addWatchlistItem,
  apiErrorMessage,
  createWatchlist,
  deleteWatchlist,
  fetchTickerSuggestions,
  fetchWatchlistItems,
  fetchWatchlists,
  removeWatchlistItem,
  updateWatchlistItem,
  type WatchlistItemInfo,
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

function itemTicker(it: WatchlistItemInfo) {
  return (it.display_name || it.ticker || '').trim()
}

/** Comma-separated — good for pasting into scanners / other apps. */
function tickersCsv(items: WatchlistItemInfo[]) {
  return items.map(itemTicker).filter(Boolean).join(', ')
}

/** WhatsApp-friendly message with watchlist name + one ticker per line. */
function watchlistShareText(name: string, market: string, items: WatchlistItemInfo[]) {
  const lines = items.map((it) => {
    const t = itemTicker(it)
    const bits: string[] = [t]
    if (it.ltp != null) bits.push(`LTP ${it.ltp.toLocaleString(undefined, { maximumFractionDigits: 4 })}`)
    if (it.change_pct != null) bits.push(fmtPct(it.change_pct))
    if (it.notes?.trim()) bits.push(`— ${it.notes.trim()}`)
    return bits.join('  ')
  })
  return [
    `*${name}*`,
    `Market: ${market} · ${items.length} ticker${items.length === 1 ? '' : 's'}`,
    '',
    ...lines,
    '',
    `Tickers: ${tickersCsv(items)}`,
  ].join('\n')
}

function chartAnalyzerHref(ticker: string, market: string, timeframe?: string) {
  const params = new URLSearchParams({
    ticker: ticker.trim(),
    assetClass: market || 'india',
  })
  if (timeframe) params.set('tf', timeframe)
  return `/chart-analyzer?${params.toString()}`
}

/** Open Trading Agent (Technical / Price Action) for this ticker and auto-run. */
function tradingAgentHref(ticker: string, market: string, timeframe?: string) {
  const params = new URLSearchParams({
    ticker: ticker.trim(),
    assetClass: market || 'india',
    auto: '1',
  })
  if (timeframe) params.set('tf', timeframe)
  return `/trading-agent?${params.toString()}`
}

/** Open Investing Agent (Fundamental Analyst) for this ticker and auto-run. */
function investingAgentHref(ticker: string) {
  const params = new URLSearchParams({
    ticker: ticker.trim(),
    auto: '1',
  })
  return `/investing-agent?${params.toString()}`
}

const agentLinkClass =
  'inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] font-medium transition-colors'

async function copyText(text: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text)
    return
  }
  const ta = document.createElement('textarea')
  ta.value = text
  ta.style.position = 'fixed'
  ta.style.left = '-9999px'
  document.body.appendChild(ta)
  ta.select()
  document.execCommand('copy')
  document.body.removeChild(ta)
}

function openWhatsAppShare(text: string) {
  const url = `https://wa.me/?text=${encodeURIComponent(text)}`
  window.open(url, '_blank', 'noopener,noreferrer')
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
  const [copied, setCopied] = useState(false)
  const [shareHint, setShareHint] = useState('')
  const [editingNotesId, setEditingNotesId] = useState<number | null>(null)
  const [notesDraft, setNotesDraft] = useState('')

  const listsQ = useQuery({ queryKey: ['watchlists'], queryFn: fetchWatchlists })
  const lists = listsQ.data?.watchlists ?? []
  const selectedList = lists.find((l) => l.id === selectedId)
  const currentMarket = selectedList?.market_type ?? newMarket

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

  const updateNotesMut = useMutation({
    mutationFn: ({ itemId, notes: n }: { itemId: number; notes: string }) =>
      updateWatchlistItem(selectedId as number, itemId, { notes: n }),
    onSuccess: () => {
      setEditingNotesId(null)
      qc.invalidateQueries({ queryKey: ['watchlist-items', selectedId] })
    },
    onError: (e) => setError(apiErrorMessage(e)),
  })

  const startEditNotes = (it: WatchlistItemInfo) => {
    setEditingNotesId(it.id)
    setNotesDraft(it.notes ?? '')
  }
  const saveNotes = (itemId: number) => updateNotesMut.mutate({ itemId, notes: notesDraft })
  const cancelEditNotes = () => setEditingNotesId(null)

  const items = itemsQ.data?.items ?? []
  const csvTickers = useMemo(() => tickersCsv(items), [items])

  const { sorted: sortedItems, sortKey: itemsSortKey, sortDir: itemsSortDir, handleSort: handleItemsSort } = useSort(
    items,
    {
      ticker: (r) => r.display_name || r.ticker,
      ltp: (r) => r.ltp,
      change_pct: (r) => r.change_pct,
      change_since_added_pct: (r) => r.change_since_added_pct,
    },
  )

  const handleCopyTickers = async () => {
    if (!items.length) return
    try {
      await copyText(csvTickers)
      setCopied(true)
      setShareHint('')
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      setShareHint('Could not copy — try selecting the tickers manually.')
    }
  }

  const handleWhatsAppShare = () => {
    if (!items.length || !selectedList) return
    const text = watchlistShareText(selectedList.name, selectedList.market_type, items)
    openWhatsAppShare(text)
    setShareHint('Opening WhatsApp…')
    window.setTimeout(() => setShareHint(''), 2500)
  }

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
                  {selectedList?.name} ({items.length})
                </h3>
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={handleCopyTickers}
                    disabled={!items.length}
                    title="Copy all tickers as comma-separated text"
                  >
                    {copied ? <Check size={14} className="mr-1.5 text-emerald-400" /> : <Copy size={14} className="mr-1.5" />}
                    {copied ? 'Copied!' : 'Copy tickers'}
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={handleWhatsAppShare}
                    disabled={!items.length}
                    title="Share this watchlist and all tickers on WhatsApp"
                  >
                    <Share2 size={14} className="mr-1.5" />
                    Share on WhatsApp
                  </Button>
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
              {shareHint && <p className="mb-3 text-xs text-slate-500">{shareHint}</p>}

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
                      const market = lists.find((l) => l.id === selectedId)?.market_type ?? 'india'
                      const chartHref = chartAnalyzerHref(it.ticker, market, tf)
                      const taHref = tradingAgentHref(it.ticker, market, tf)
                      const faHref = investingAgentHref(it.ticker)
                      const symbol = it.display_name || it.ticker
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
                            <Td>
                              <div className="flex flex-wrap items-center gap-1.5">
                                <span className="font-medium text-white">{symbol}</span>
                                <Link
                                  to={taHref}
                                  title={`Perform TA — open Trading Agent for ${symbol}`}
                                  className={`${agentLinkClass} border-violet-500/35 bg-violet-500/10 text-violet-200 hover:bg-violet-500/20`}
                                >
                                  <LineChart size={12} />
                                  Perform TA
                                </Link>
                                <Link
                                  to={faHref}
                                  title={`Perform FA — open Investing Agent for ${symbol}`}
                                  className={`${agentLinkClass} border-amber-500/35 bg-amber-500/10 text-amber-200 hover:bg-amber-500/20`}
                                >
                                  <Bot size={12} />
                                  Perform FA
                                </Link>
                              </div>
                            </Td>
                            <Td>{it.ltp != null ? it.ltp.toLocaleString(undefined, { maximumFractionDigits: 4 }) : '—'}</Td>
                            <Td className={pctClass(it.change_pct)}>{fmtPct(it.change_pct)}</Td>
                            <Td className={pctClass(it.change_since_added_pct)}>{fmtPct(it.change_since_added_pct)}</Td>
                            <Td className="max-w-[260px] text-slate-400">
                              {editingNotesId === it.id ? (
                                <div className="flex items-center gap-1.5">
                                  <Input
                                    autoFocus
                                    value={notesDraft}
                                    onChange={(e) => setNotesDraft(e.target.value)}
                                    onKeyDown={(e) => {
                                      if (e.key === 'Enter') { e.preventDefault(); saveNotes(it.id) }
                                      if (e.key === 'Escape') { e.preventDefault(); cancelEditNotes() }
                                    }}
                                    placeholder="Add a note…"
                                    className="!py-1 !text-xs"
                                  />
                                  <button
                                    type="button"
                                    aria-label="Save note"
                                    onClick={() => saveNotes(it.id)}
                                    disabled={updateNotesMut.isPending}
                                    className="shrink-0 text-slate-500 hover:text-emerald-400"
                                  >
                                    <Check size={15} />
                                  </button>
                                  <button
                                    type="button"
                                    aria-label="Cancel edit"
                                    onClick={cancelEditNotes}
                                    className="shrink-0 text-slate-500 hover:text-rose-400"
                                  >
                                    <X size={15} />
                                  </button>
                                </div>
                              ) : (
                                <button
                                  type="button"
                                  onClick={() => startEditNotes(it)}
                                  title="Click to edit note"
                                  className="group flex w-full items-center gap-1.5 truncate text-left hover:text-slate-200"
                                >
                                  <span className="truncate" title={it.notes ?? ''}>{it.notes || '—'}</span>
                                  <Pencil size={12} className="shrink-0 text-slate-600 opacity-0 group-hover:opacity-100" />
                                </button>
                              )}
                            </Td>
                            <Td>
                              <div className="flex flex-wrap items-center justify-end gap-2">
                                <Link
                                  to={chartHref}
                                  title={`Open ${symbol} in Chart Analyzer`}
                                  className={`${agentLinkClass} border-slate-700/70 bg-slate-900/50 text-slate-300 hover:border-teal-500/40 hover:text-teal-200`}
                                >
                                  <ChartCandlestick size={13} />
                                  Chart Analyzer
                                </Link>
                                <button
                                  type="button"
                                  aria-label="Remove ticker"
                                  onClick={() => removeItemMut.mutate(it.id)}
                                  className="text-slate-500 hover:text-rose-400"
                                >
                                  <Trash2 size={16} />
                                </button>
                              </div>
                            </Td>
                          </tr>
                          {isOpen && (
                            <tr>
                              <Td colSpan={7} className="whitespace-normal bg-slate-900/30">
                                <div className="mb-3 flex flex-wrap items-center gap-2">
                                  <span className="text-xs font-medium uppercase tracking-wide text-slate-500">Timeframe</span>
                                  <Select
                                    className="!w-28 !py-1.5"
                                    value={tf}
                                    onChange={(e) => setTimeframeByItem((prev) => ({ ...prev, [it.id]: e.target.value }))}
                                  >
                                    {TIMEFRAMES.map((t) => <option key={t} value={t}>{t}</option>)}
                                  </Select>
                                  <Link
                                    to={tradingAgentHref(it.ticker, market, tf)}
                                    className={`${agentLinkClass} border-violet-500/30 bg-violet-500/10 text-violet-200 hover:bg-violet-500/20`}
                                  >
                                    <LineChart size={14} />
                                    Perform TA → Trading Agent
                                  </Link>
                                  <Link
                                    to={investingAgentHref(it.ticker)}
                                    className={`${agentLinkClass} border-amber-500/30 bg-amber-500/10 text-amber-200 hover:bg-amber-500/20`}
                                  >
                                    <Bot size={14} />
                                    Perform FA → Investing Agent
                                  </Link>
                                  <Link
                                    to={chartAnalyzerHref(it.ticker, market, tf)}
                                    className={`${agentLinkClass} border-teal-500/30 bg-teal-500/10 text-teal-200 hover:bg-teal-500/20`}
                                  >
                                    <ChartCandlestick size={14} />
                                    Open in Chart Analyzer
                                  </Link>
                                </div>
                                <TradeSetupDrillDown
                                  ticker={it.ticker}
                                  timeframe={tf}
                                  assetClass={market}
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
