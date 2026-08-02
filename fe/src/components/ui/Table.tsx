import { type MouseEvent, type ReactNode, useEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronUp, ChevronsUpDown } from 'lucide-react'

export type SortDir = 'asc' | 'desc'

/**
 * Generic client-side table sort. Pass the row array plus one accessor per
 * sortable column key; `handleSort(key)` (wired to a SortableTh's onSort)
 * toggles asc/desc on repeat clicks and defaults to asc on a new column.
 * Nullish values always sort to the bottom regardless of direction.
 */
export function useSort<T>(
  rows: T[],
  accessors: Record<string, (row: T) => string | number | null | undefined>,
  initialKey: string | null = null,
  initialDir: SortDir = 'asc',
) {
  const [sortKey, setSortKey] = useState<string | null>(initialKey)
  const [sortDir, setSortDir] = useState<SortDir>(initialDir)

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('asc')
    }
  }

  let sorted = rows
  const accessor = sortKey ? accessors[sortKey] : undefined
  if (accessor) {
    sorted = [...rows].sort((a, b) => {
      const av = accessor(a)
      const bv = accessor(b)
      if (av == null && bv == null) return 0
      if (av == null) return 1
      if (bv == null) return -1
      const cmp = typeof av === 'number' && typeof bv === 'number'
        ? av - bv
        : String(av).localeCompare(String(bv), undefined, { numeric: true })
      return sortDir === 'asc' ? cmp : -cmp
    })
  }

  return { sorted, sortKey, sortDir, handleSort }
}

/**
 * Horizontally-scrollable table wrapper. On mobile, wide tables (many columns)
 * scroll sideways within this container instead of breaking the page layout.
 * Shows a subtle inset shadow on whichever edge still has more columns to
 * scroll to, so it's obvious there's more content off-screen.
 */
export function DataTable({ children, minWidth = 640 }: { children: ReactNode; minWidth?: number }) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const [shadowLeft, setShadowLeft] = useState(false)
  const [shadowRight, setShadowRight] = useState(false)

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const update = () => {
      setShadowLeft(el.scrollLeft > 4)
      setShadowRight(el.scrollLeft < el.scrollWidth - el.clientWidth - 4)
    }
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    el.addEventListener('scroll', update, { passive: true })
    return () => {
      ro.disconnect()
      el.removeEventListener('scroll', update)
    }
  }, [])

  const shadows = [
    shadowLeft ? 'inset 10px 0 10px -10px rgba(0,0,0,0.45)' : '',
    shadowRight ? 'inset -10px 0 10px -10px rgba(0,0,0,0.45)' : '',
  ].filter(Boolean).join(', ')

  return (
    <div
      ref={wrapRef}
      className="-mx-1 overflow-x-auto rounded-xl border border-slate-800/60 sm:mx-0"
      style={shadows ? { boxShadow: shadows } : undefined}
    >
      <table className="w-full text-sm" style={{ minWidth }}>{children}</table>
    </div>
  )
}

const thBase =
  'whitespace-nowrap border-b border-slate-800/80 bg-slate-800/30 px-3 py-2.5 text-left text-[10px] font-semibold uppercase tracking-wider text-slate-500 sm:px-4 sm:py-3 sm:text-xs'

export function Th({ children, className = '' }: { children?: ReactNode; className?: string }) {
  return <th className={`${thBase} ${className}`}>{children}</th>
}

export function SortableTh({
  children,
  active,
  direction,
  onSort,
  className = '',
}: {
  children: ReactNode
  active: boolean
  direction: 'asc' | 'desc'
  onSort: () => void
  className?: string
}) {
  return (
    <th
      className={`${thBase} cursor-pointer select-none hover:text-slate-300 ${active ? 'text-slate-300' : ''} ${className}`}
      onClick={onSort}
      aria-sort={active ? (direction === 'asc' ? 'ascending' : 'descending') : 'none'}
    >
      <span className="inline-flex items-center gap-1">
        {children}
        {active ? (
          direction === 'asc' ? <ChevronUp size={14} /> : <ChevronDown size={14} />
        ) : (
          <ChevronsUpDown size={14} className="opacity-40" />
        )}
      </span>
    </th>
  )
}

export function Td({
  children,
  className = '',
  colSpan,
  onClick,
}: {
  children: ReactNode
  className?: string
  colSpan?: number
  onClick?: (e: MouseEvent<HTMLTableCellElement>) => void
}) {
  return (
    <td
      colSpan={colSpan}
      onClick={onClick}
      className={`whitespace-nowrap border-b border-slate-800/40 px-3 py-2.5 text-xs text-slate-300 sm:px-4 sm:py-3 sm:text-sm ${className}`}
    >
      {children}
    </td>
  )
}
