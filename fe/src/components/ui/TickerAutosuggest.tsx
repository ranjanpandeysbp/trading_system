import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchTickerSuggestions } from '../../api/client'

const fieldClass =
  'w-full rounded-xl border border-slate-700/80 bg-slate-800/50 px-4 py-2.5 text-sm text-slate-100 placeholder:text-slate-500 transition-colors focus:border-blue-500/50 focus:outline-none focus:ring-2 focus:ring-blue-500/20'

function lastToken(raw: string): { prefix: string; token: string; sep: string } {
  const m = raw.match(/^(.*?)([,\s]+)([^,\s]*)$/)
  if (m) return { prefix: m[1], sep: m[2].includes(',') ? ', ' : ' ', token: m[3] }
  return { prefix: '', sep: '', token: raw }
}

type SuggestItem = { symbol: string; name: string; label: string }

/** Single-ticker text input with a live dropdown of matching symbols as the
 * user types, backed by the same suggestion API the watchlist button uses.
 * Commodities show friendly names (Gold, Silver, Wheat…) next to Yahoo symbols.
 * Set `multi` to keep prior comma/space-separated symbols and suggest only on
 * the last token. */
export function TickerAutosuggest({
  value,
  onChange,
  assetClass,
  placeholder = 'e.g. RELIANCE',
  className = '',
  multi = false,
}: {
  value: string
  onChange: (v: string) => void
  assetClass: 'india' | 'us' | 'crypto' | 'commodity'
  placeholder?: string
  className?: string
  multi?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState(value)
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => setQuery(value), [value])

  const suggestQuery = useMemo(() => {
    if (!multi) return query.trim()
    return lastToken(query).token.trim()
  }, [multi, query])

  const canSuggest =
    open && (suggestQuery.length >= 1 || assetClass === 'commodity')

  const suggestQ = useQuery({
    queryKey: ['ticker-suggest', assetClass, suggestQuery],
    queryFn: () => fetchTickerSuggestions(assetClass, suggestQuery, assetClass === 'commodity' ? 40 : 10),
    enabled: canSuggest,
    staleTime: 30_000,
  })

  const items: SuggestItem[] = useMemo(() => {
    const raw = suggestQ.data?.items
    if (raw && raw.length) return raw
    return (suggestQ.data?.tickers ?? []).map((t) => ({ symbol: t, name: t, label: t }))
  }, [suggestQ.data])

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  const pick = (symbol: string) => {
    let next = symbol
    if (multi) {
      const { prefix, sep } = lastToken(query)
      next = prefix ? `${prefix}${sep || ', '}${symbol}` : symbol
    }
    onChange(next)
    setQuery(next)
    setOpen(false)
  }

  return (
    <div ref={rootRef} className={`relative ${className}`}>
      <input
        className={fieldClass}
        value={query}
        placeholder={placeholder}
        onChange={(e) => {
          const v = assetClass === 'commodity' ? e.target.value : e.target.value.toUpperCase()
          setQuery(v)
          onChange(v)
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        autoComplete="off"
        spellCheck={false}
      />
      {canSuggest && items.length > 0 && (
        <div className="absolute left-0 right-0 top-full z-30 mt-1 max-h-56 overflow-y-auto rounded-xl border border-slate-700 bg-slate-900 py-1 shadow-xl">
          {items.map((it) => (
            <button
              key={it.symbol}
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => pick(it.symbol)}
              className="flex w-full flex-col items-start px-3 py-1.5 text-left hover:bg-slate-800"
            >
              <span className="text-sm text-slate-100">
                {it.name && it.name !== it.symbol ? it.name : it.symbol}
              </span>
              {it.name && it.name !== it.symbol && (
                <span className="text-[11px] text-slate-500">{it.symbol}</span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
