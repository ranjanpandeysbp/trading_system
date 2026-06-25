import { type ReactNode } from 'react'

export function Chip({
  selected,
  onClick,
  children,
  title,
}: {
  selected: boolean
  onClick: () => void
  children: ReactNode
  title?: string
}) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      className={`rounded-full border px-3 py-1.5 text-xs font-medium transition-all ${
        selected
          ? 'border-blue-500/50 bg-blue-500/15 text-blue-300 shadow-sm shadow-blue-500/10'
          : 'border-slate-700/80 bg-slate-800/40 text-slate-400 hover:border-slate-600 hover:text-slate-300'
      }`}
    >
      {children}
    </button>
  )
}
