import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchTickerSuggestions } from '../../api/client'

const fieldClass =
  'w-full rounded-xl border border-slate-700/80 bg-slate-800/50 px-4 py-2.5 text-sm text-slate-100 placeholder:text-slate-500 transition-colors focus:border-blue-500/50 focus:outline-none focus:ring-2 focus:ring-blue-500/20'

/** Single-ticker text input with a live dropdown of matching symbols as the
 * user types, backed by the same suggestion API the watchlist button uses. */
export function TickerAutosuggest({
  value,
  onChange,
  assetClass,
  placeholder = 'e.g. RELIANCE',
  className = '',
}: {
  value: string
  onChange: (v: string) => void
  assetClass: 'india' | 'us' | 'crypto' | 'commodity'
  placeholder?: string
  className?: string
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState(value)
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => setQuery(value), [value])

  const suggestQ = useQuery({
    queryKey: ['ticker-suggest', assetClass, query],
    queryFn: () => fetchTickerSuggestions(assetClass, query, 10),
    enabled: open && query.trim().length >= 1,
    staleTime: 30_000,
  })
  const suggestions = suggestQ.data?.tickers ?? []

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  const pick = (t: string) => {
    onChange(t)
    setQuery(t)
    setOpen(false)
  }

  return (
    <div ref={rootRef} className={`relative ${className}`}>
      <input
        className={fieldClass}
        value={query}
        placeholder={placeholder}
        onChange={(e) => {
          const v = e.target.value.toUpperCase()
          setQuery(v)
          onChange(v)
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        autoComplete="off"
        spellCheck={false}
      />
      {open && query.trim().length >= 1 && suggestions.length > 0 && (
        <div className="absolute left-0 right-0 top-full z-30 mt-1 max-h-56 overflow-y-auto rounded-xl border border-slate-700 bg-slate-900 py-1 shadow-xl">
          {suggestions.map((t) => (
            <button
              key={t}
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => pick(t)}
              className="flex w-full items-center px-3 py-1.5 text-left text-sm text-slate-200 hover:bg-slate-800"
            >
              {t}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
