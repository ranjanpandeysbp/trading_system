import { type ReactNode } from 'react'
import { ChevronDown, ChevronUp, ChevronsUpDown } from 'lucide-react'

export function DataTable({ children, minWidth = 640 }: { children: ReactNode; minWidth?: number }) {
  return (
    <div className="-mx-1 overflow-x-auto rounded-xl border border-slate-800/60 sm:mx-0">
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

export function Td({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <td className={`whitespace-nowrap border-b border-slate-800/40 px-3 py-2.5 text-xs text-slate-300 sm:px-4 sm:py-3 sm:text-sm ${className}`}>
      {children}
    </td>
  )
}
