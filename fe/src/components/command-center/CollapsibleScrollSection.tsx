import { type ReactNode } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'

/**
 * Collapsible block with an optional max-height scroll area for large AMC/fund/result tables.
 */
export function CollapsibleScrollSection({
  title,
  subtitle,
  open,
  onToggle,
  children,
  maxHeightClass = 'max-h-72',
  scroll = true,
  className = '',
}: {
  title: string
  subtitle?: string
  open: boolean
  onToggle: () => void
  children: ReactNode
  /** Tailwind max-height for the scroll body when open (default max-h-72 ≈ 18rem). */
  maxHeightClass?: string
  /** When false, children expand fully without an inner scrollbar. */
  scroll?: boolean
  className?: string
}) {
  return (
    <div className={`rounded-xl border border-slate-800/80 bg-slate-900/40 ${className}`}>
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center gap-2 px-3 py-2.5 text-left hover:bg-slate-800/40"
      >
        {open
          ? <ChevronDown size={16} className="shrink-0 text-slate-400" />
          : <ChevronRight size={16} className="shrink-0 text-slate-400" />}
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium text-white">{title}</span>
          {subtitle ? <span className="mt-0.5 block text-xs text-slate-500">{subtitle}</span> : null}
        </span>
        <span className="shrink-0 text-xs text-slate-500">{open ? 'Collapse' : 'Expand'}</span>
      </button>
      {open && (
        <div className="border-t border-slate-800 px-3 pb-3 pt-2">
          {scroll ? (
            <div className={`${maxHeightClass} overflow-auto overscroll-contain pr-1`}>
              {children}
            </div>
          ) : (
            children
          )}
        </div>
      )}
    </div>
  )
}
