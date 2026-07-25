import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Eye, Loader2, Plus } from 'lucide-react'
import {
  addWatchlistItem,
  apiErrorMessage,
  createWatchlist,
  fetchTickerSuggestions,
  fetchWatchlists,
  type WatchlistInfo,
} from '../../api/client'
import { useWatchlistMarket, type WatchlistMarket } from './WatchlistMarketContext'

type Props = {
  /** Symbol or company name to add. */
  ticker: string
  /** Optional display label (defaults to ticker). */
  displayName?: string
  /** Optional note stored on the watchlist item. */
  notes?: string
  /** Override market from context. */
  marketType?: WatchlistMarket
  /**
   * When ticker is a company name (e.g. MF holdings), look up an NSE/US symbol
   * via suggestions before adding.
   */
  resolveName?: boolean
  /** Compact icon-only control for dense tables. */
  compact?: boolean
  className?: string
  stopPropagation?: boolean
}

function looksLikeSymbol(raw: string) {
  const t = raw.trim()
  if (!t) return false
  // Symbols: no spaces, short, mostly alnum / = / - /
  return !/\s/.test(t) && t.length <= 24
}

function cleanCompanyName(raw: string) {
  return raw
    .replace(/\s+(Ltd\.?|Limited|Inc\.?|Corp\.?|PLC|Co\.?)\s*$/i, '')
    .replace(/\s+/g, ' ')
    .trim()
}

async function resolveToSymbol(market: WatchlistMarket, raw: string): Promise<string> {
  const trimmed = (raw || '').trim()
  if (!trimmed) throw new Error('Empty ticker')
  if (looksLikeSymbol(trimmed)) return trimmed.toUpperCase()

  const query = cleanCompanyName(trimmed)
  const firstWord = query.split(/\s+/)[0] ?? query
  try {
    const res = await fetchTickerSuggestions(market, firstWord, 8)
    const list = res.tickers ?? []
    const upperQ = query.toUpperCase()
    const exact = list.find((t) => t.toUpperCase() === upperQ || t.toUpperCase() === firstWord.toUpperCase())
    if (exact) return exact.toUpperCase()
    if (list[0]) return list[0].toUpperCase()
  } catch {
    /* fall through */
  }
  // Last resort: strip spaces / punctuation into a pseudo-symbol
  return query.toUpperCase().replace(/[^A-Z0-9.=-]/g, '').slice(0, 24) || trimmed.toUpperCase()
}

export function AddToWatchlistButton({
  ticker,
  displayName,
  notes,
  marketType,
  resolveName = false,
  compact = false,
  className = '',
  stopPropagation = true,
}: Props) {
  const ctx = useWatchlistMarket()
  const market: WatchlistMarket = marketType ?? ctx
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [done, setDone] = useState(false)
  const [err, setErr] = useState('')
  const rootRef = useRef<HTMLDivElement>(null)

  const listsQ = useQuery({
    queryKey: ['watchlists'],
    queryFn: fetchWatchlists,
    staleTime: 30_000,
  })

  const marketLists = useMemo(
    () => (listsQ.data?.watchlists ?? []).filter((w) => w.market_type === market),
    [listsQ.data, market],
  )

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  const addMut = useMutation({
    mutationFn: async (watchlistId: number) => {
      const symbol = resolveName ? await resolveToSymbol(market, ticker) : ticker.trim().toUpperCase()
      if (!symbol) throw new Error('Could not resolve ticker')
      return addWatchlistItem(watchlistId, {
        ticker: symbol,
        display_name: displayName || ticker.trim(),
        notes: notes?.trim() || undefined,
      })
    },
    onSuccess: () => {
      setDone(true)
      setErr('')
      setOpen(false)
      qc.invalidateQueries({ queryKey: ['watchlists'] })
      window.setTimeout(() => setDone(false), 2000)
    },
    onError: (e) => setErr(apiErrorMessage(e)),
  })

  const createAndAddMut = useMutation({
    mutationFn: async () => {
      const wl = await createWatchlist({ market_type: market, name: 'Command Center' })
      await qc.invalidateQueries({ queryKey: ['watchlists'] })
      return addMut.mutateAsync(wl.id)
    },
    onError: (e) => setErr(apiErrorMessage(e)),
  })

  const busy = addMut.isPending || createAndAddMut.isPending
  const label = done ? 'Added' : compact ? 'Watch' : 'Add to watchlist'

  const handleClick = useCallback(
    async (e: React.MouseEvent) => {
      if (stopPropagation) {
        e.preventDefault()
        e.stopPropagation()
      }
      setErr('')
      if (done || busy || !ticker?.trim()) return

      if (marketLists.length === 0) {
        createAndAddMut.mutate()
        return
      }
      if (marketLists.length === 1) {
        addMut.mutate(marketLists[0].id)
        return
      }
      setOpen((v) => !v)
    },
    [stopPropagation, done, busy, ticker, marketLists, createAndAddMut, addMut],
  )

  const pickList = (wl: WatchlistInfo, e: React.MouseEvent) => {
    if (stopPropagation) {
      e.preventDefault()
      e.stopPropagation()
    }
    addMut.mutate(wl.id)
  }

  if (!ticker?.trim() || ticker === '—') return null

  return (
    <div ref={rootRef} className={`relative inline-flex ${className}`}>
      <button
        type="button"
        title={done ? 'Added to watchlist' : `Add ${ticker} to watchlist`}
        disabled={busy}
        onClick={handleClick}
        className={`inline-flex items-center gap-1 rounded-lg border border-slate-700/80 bg-slate-800/50 font-medium text-slate-200 transition hover:border-blue-500/50 hover:bg-slate-800 hover:text-white disabled:opacity-50 ${
          compact ? 'px-1.5 py-1 text-[10px]' : 'px-2 py-1 text-xs'
        } ${done ? 'border-emerald-500/40 text-emerald-400' : ''}`}
      >
        {busy ? (
          <Loader2 size={compact ? 12 : 14} className="animate-spin" />
        ) : done ? (
          <Check size={compact ? 12 : 14} />
        ) : (
          <Plus size={compact ? 12 : 14} />
        )}
        {!compact && <span>{label}</span>}
        {compact && done && <span>OK</span>}
      </button>

      {open && marketLists.length > 1 && (
        <div className="absolute right-0 z-30 mt-1 min-w-[11rem] rounded-xl border border-slate-700 bg-slate-900 py-1 shadow-xl">
          <p className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
            Choose watchlist
          </p>
          {marketLists.map((wl) => (
            <button
              key={wl.id}
              type="button"
              onClick={(e) => pickList(wl, e)}
              className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-slate-200 hover:bg-slate-800"
            >
              <Eye size={12} className="shrink-0 text-slate-500" />
              <span className="truncate">{wl.name}</span>
            </button>
          ))}
        </div>
      )}

      {err && (
        <p className="absolute left-0 top-full z-30 mt-1 max-w-[14rem] rounded-lg border border-rose-500/40 bg-slate-950 px-2 py-1 text-[10px] text-rose-300">
          {err}
        </p>
      )}
    </div>
  )
}

/** Ticker label + compact add button for table cells. */
export function TickerWithWatchlist({
  ticker,
  displayName,
  notes,
  marketType,
  resolveName,
  className = '',
}: {
  ticker: string
  displayName?: string
  notes?: string
  marketType?: WatchlistMarket
  resolveName?: boolean
  className?: string
}) {
  if (!ticker || ticker === '—') return <span className={className}>—</span>
  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <span className="font-medium text-white">{displayName || ticker}</span>
      <AddToWatchlistButton
        ticker={ticker}
        displayName={displayName}
        notes={notes}
        marketType={marketType}
        resolveName={resolveName}
        compact
      />
    </span>
  )
}
