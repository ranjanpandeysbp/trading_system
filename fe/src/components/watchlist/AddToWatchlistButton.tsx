import { useCallback, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, X } from 'lucide-react'
import {
  addWatchlistItem,
  apiErrorMessage,
  createWatchlist,
  fetchTickerSuggestions,
  fetchWatchlists,
} from '../../api/client'
import { Card } from '../ui/Card'
import { Button } from '../ui/Button'
import { FormField, Input, Select, Textarea } from '../ui/Form'
import { Alert } from '../ui/Feedback'
import { useWatchlistMarket, type WatchlistMarket } from './WatchlistMarketContext'

type Props = {
  /** Symbol or company name to add. */
  ticker: string
  /** Optional display label (defaults to ticker). */
  displayName?: string
  /** Optional default note stored on the watchlist item — editable in the popup. */
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

function AddToWatchlistModal({
  ticker,
  displayName,
  notes,
  market,
  resolveName,
  onClose,
}: {
  ticker: string
  displayName?: string
  notes?: string
  market: WatchlistMarket
  resolveName: boolean
  onClose: () => void
}) {
  const qc = useQueryClient()
  const listsQ = useQuery({ queryKey: ['watchlists'], queryFn: fetchWatchlists, staleTime: 30_000 })
  const marketLists = useMemo(
    () => (listsQ.data?.watchlists ?? []).filter((w) => w.market_type === market),
    [listsQ.data, market],
  )

  const [mode, setMode] = useState<'existing' | 'new'>(marketLists.length ? 'existing' : 'new')
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [newName, setNewName] = useState('')
  const [comment, setComment] = useState(notes ?? '')
  const [done, setDone] = useState(false)
  const [err, setErr] = useState('')

  const effectiveSelectedId = selectedId ?? marketLists[0]?.id ?? null

  const addMut = useMutation({
    mutationFn: async () => {
      const symbol = resolveName ? await resolveToSymbol(market, ticker) : ticker.trim().toUpperCase()
      if (!symbol) throw new Error('Could not resolve ticker')

      let watchlistId: number
      if (mode === 'new') {
        const name = newName.trim() || `${market.toUpperCase()} Watchlist`
        const wl = await createWatchlist({ market_type: market, name })
        watchlistId = wl.id
      } else {
        if (!effectiveSelectedId) throw new Error('Choose a watchlist')
        watchlistId = effectiveSelectedId
      }

      return addWatchlistItem(watchlistId, {
        ticker: symbol,
        display_name: displayName || ticker.trim(),
        notes: comment.trim() || undefined,
      })
    },
    onSuccess: () => {
      setDone(true)
      setErr('')
      qc.invalidateQueries({ queryKey: ['watchlists'] })
    },
    onError: (e) => setErr(apiErrorMessage(e)),
  })

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4" onClick={onClose}>
      <div className="w-full max-w-sm" onClick={(e: React.MouseEvent) => e.stopPropagation()}>
      <Card>
        <div className="mb-4 flex items-center justify-between">
          <h3 className="font-semibold text-white">Add {ticker} to watchlist</h3>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-white">
            <X size={18} />
          </button>
        </div>

        {done ? (
          <div className="space-y-3">
            <Alert type="success">Added {ticker} to your watchlist.</Alert>
            <Button onClick={onClose}>Done</Button>
          </div>
        ) : (
          <div className="space-y-3">
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setMode('existing')}
                disabled={!marketLists.length}
                className={`flex-1 rounded-lg border px-3 py-1.5 text-xs font-medium transition disabled:cursor-not-allowed disabled:opacity-40 ${
                  mode === 'existing' ? 'border-teal-400 bg-teal-500/10 text-teal-300' : 'border-slate-700 text-slate-400 hover:text-slate-200'
                }`}
              >
                Existing watchlist
              </button>
              <button
                type="button"
                onClick={() => setMode('new')}
                className={`flex-1 rounded-lg border px-3 py-1.5 text-xs font-medium transition ${
                  mode === 'new' ? 'border-teal-400 bg-teal-500/10 text-teal-300' : 'border-slate-700 text-slate-400 hover:text-slate-200'
                }`}
              >
                Create new
              </button>
            </div>

            {mode === 'existing' ? (
              marketLists.length ? (
                <FormField label="Watchlist">
                  <Select value={String(effectiveSelectedId ?? '')} onChange={(e) => setSelectedId(Number(e.target.value))}>
                    {marketLists.map((wl) => (
                      <option key={wl.id} value={wl.id}>{wl.name}</option>
                    ))}
                  </Select>
                </FormField>
              ) : (
                <p className="text-sm text-slate-500">No watchlists yet for this market — create one instead.</p>
              )
            ) : (
              <FormField label="New watchlist name">
                <Input
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder={`${market.toUpperCase()} Watchlist`}
                  autoFocus
                />
              </FormField>
            )}

            <FormField label="Comment (optional)">
              <Textarea rows={2} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Why this ticker, entry idea, etc." />
            </FormField>

            {err && <Alert type="error">{err}</Alert>}

            <div className="flex justify-end gap-2 pt-1">
              <Button variant="ghost" onClick={onClose}>Cancel</Button>
              <Button
                onClick={() => addMut.mutate()}
                disabled={addMut.isPending || (mode === 'existing' && !effectiveSelectedId)}
              >
                {addMut.isPending ? 'Adding…' : 'Add to watchlist'}
              </Button>
            </div>
          </div>
        )}
      </Card>
      </div>
    </div>
  )
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
  const [open, setOpen] = useState(false)

  const handleClick = useCallback(
    (e: React.MouseEvent) => {
      if (stopPropagation) {
        e.preventDefault()
        e.stopPropagation()
      }
      if (!ticker?.trim()) return
      setOpen(true)
    },
    [stopPropagation, ticker],
  )

  if (!ticker?.trim() || ticker === '—') return null

  return (
    <div className={`inline-flex ${className}`}>
      <button
        type="button"
        title={`Add ${ticker} to watchlist`}
        onClick={handleClick}
        className={`inline-flex items-center gap-1 rounded-lg border border-slate-700/80 bg-slate-800/50 font-medium text-slate-200 transition hover:border-blue-500/50 hover:bg-slate-800 hover:text-white ${
          compact ? 'px-1.5 py-1 text-[10px]' : 'px-2 py-1 text-xs'
        }`}
      >
        <Plus size={compact ? 12 : 14} />
        {!compact && <span>Add to watchlist</span>}
      </button>

      {open && (
        <AddToWatchlistModal
          ticker={ticker}
          displayName={displayName}
          notes={notes}
          market={market}
          resolveName={resolveName}
          onClose={() => setOpen(false)}
        />
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
