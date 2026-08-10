import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Search, CornerDownLeft, ArrowUp, ArrowDown } from 'lucide-react'
import { fetchStrategies } from '../../api/client'
import {
  STATIC_STRATEGY_SEARCH_CATALOG,
  filterStrategySearch,
  ruleStrategiesToSearchItems,
  type StrategySearchItem,
} from '../../nav/strategySearchCatalog'

type Props = {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function GlobalStrategySearch({ open, onOpenChange }: Props) {
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const [query, setQuery] = useState('')
  const [activeIdx, setActiveIdx] = useState(0)

  const { data: rules } = useQuery({
    queryKey: ['strategies'],
    queryFn: fetchStrategies,
    enabled: open,
    staleTime: 5 * 60_000,
  })

  const catalog = useMemo(() => {
    const ruleItems = rules?.length ? ruleStrategiesToSearchItems(rules) : []
    // Prefer static first, then rules (dedupe by `to`)
    const seen = new Set<string>()
    const out: StrategySearchItem[] = []
    for (const item of [...STATIC_STRATEGY_SEARCH_CATALOG, ...ruleItems]) {
      if (seen.has(item.to)) continue
      seen.add(item.to)
      out.push(item)
    }
    return out
  }, [rules])

  const results = useMemo(() => filterStrategySearch(catalog, query, 48), [catalog, query])

  useEffect(() => {
    setActiveIdx(0)
  }, [query, open])

  useEffect(() => {
    if (!open) {
      setQuery('')
      return
    }
    const t = window.setTimeout(() => inputRef.current?.focus(), 30)
    return () => window.clearTimeout(t)
  }, [open])

  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>(`[data-idx="${activeIdx}"]`)
    el?.scrollIntoView({ block: 'nearest' })
  }, [activeIdx, results])

  const go = useCallback(
    (item: StrategySearchItem) => {
      onOpenChange(false)
      navigate(item.to)
    },
    [navigate, onOpenChange],
  )

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onOpenChange(false)
        return
      }
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setActiveIdx((i) => Math.min(i + 1, Math.max(0, results.length - 1)))
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setActiveIdx((i) => Math.max(i - 1, 0))
        return
      }
      if (e.key === 'Enter' && results[activeIdx]) {
        e.preventDefault()
        go(results[activeIdx])
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, results, activeIdx, go, onOpenChange])

  if (!open) return null

  return createPortal(
    <div className="fixed inset-0 z-[80] flex items-start justify-center px-3 pt-[12vh] sm:px-4">
      <button
        type="button"
        aria-label="Close search"
        className="absolute inset-0 bg-black/65 backdrop-blur-sm"
        onClick={() => onOpenChange(false)}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Search strategies"
        className="relative z-[81] flex w-full max-w-xl flex-col overflow-hidden rounded-2xl border border-slate-700/80 bg-slate-950 shadow-2xl shadow-black/50"
      >
        <div className="flex items-center gap-2 border-b border-slate-800 px-3 py-3">
          <Search size={18} className="shrink-0 text-slate-500" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search any strategy, tool, or page…"
            className="min-w-0 flex-1 bg-transparent text-sm text-white outline-none placeholder:text-slate-600"
            autoComplete="off"
            spellCheck={false}
          />
          <kbd className="hidden rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 text-[10px] text-slate-500 sm:inline">
            Esc
          </kbd>
        </div>

        <div ref={listRef} className="max-h-[min(60vh,28rem)] overflow-y-auto py-2">
          {!results.length ? (
            <p className="px-4 py-8 text-center text-sm text-slate-500">No matches for “{query}”</p>
          ) : (
            results.map((item, idx) => {
              const active = idx === activeIdx
              return (
                <button
                  key={item.id}
                  type="button"
                  data-idx={idx}
                  onMouseEnter={() => setActiveIdx(idx)}
                  onClick={() => go(item)}
                  className={`flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors ${
                    active ? 'bg-blue-500/15 text-white' : 'text-slate-300 hover:bg-slate-900/80'
                  }`}
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{item.label}</p>
                    <p className="truncate text-[11px] text-slate-500">
                      {item.group}
                      {item.kind === 'rule' ? ' · rule strategy' : ''}
                    </p>
                  </div>
                  {active ? <CornerDownLeft size={14} className="shrink-0 text-slate-500" /> : null}
                </button>
              )
            })
          )}
        </div>

        <div className="flex flex-wrap items-center gap-3 border-t border-slate-800 px-4 py-2 text-[10px] text-slate-600">
          <span className="inline-flex items-center gap-1">
            <ArrowUp size={10} />
            <ArrowDown size={10} /> navigate
          </span>
          <span className="inline-flex items-center gap-1">
            <CornerDownLeft size={10} /> open
          </span>
          <span className="ml-auto">{catalog.length} strategies & tools</span>
        </div>
      </div>
    </div>,
    document.body,
  )
}

/** Sidebar / header trigger button (palette is owned by AppLayout). */
export function GlobalStrategySearchTrigger({ onOpen }: { onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="flex w-full items-center gap-2 rounded-xl border border-slate-800/80 bg-slate-950/50 px-3 py-2 text-left text-sm text-slate-500 transition-colors hover:border-slate-700 hover:bg-slate-900/70 hover:text-slate-300"
      aria-label="Search strategies"
    >
      <Search size={15} className="shrink-0" />
      <span className="flex-1 truncate">Search strategies…</span>
      <kbd className="hidden rounded border border-slate-700/80 bg-slate-900 px-1.5 py-0.5 text-[10px] text-slate-500 sm:inline">
        Ctrl K
      </kbd>
    </button>
  )
}
