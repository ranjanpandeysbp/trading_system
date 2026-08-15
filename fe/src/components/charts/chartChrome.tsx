import type { ReactNode } from 'react'

/** Labeled control row — keeps chart chrome scannable without removing tools. */
export function ChartToolbarRow({
  label,
  children,
  right,
  className = '',
}: {
  label?: string
  children: ReactNode
  right?: ReactNode
  className?: string
}) {
  return (
    <div
      className={`flex flex-wrap items-center gap-x-2 gap-y-1.5 ${className}`}
    >
      {label ? (
        <span className="w-14 shrink-0 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
          {label}
        </span>
      ) : null}
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">{children}</div>
      {right ? <div className="ml-auto flex flex-wrap items-center gap-1.5">{right}</div> : null}
    </div>
  )
}

/**
 * Stacked chart chrome: symbol → time → view → tools → optional extras.
 * Commentary / drawings sit in dedicated slots so primary pickers stay clear.
 */
export function ChartChrome({
  symbol,
  time,
  view,
  tools,
  drawings,
  overlays,
  commentary,
  className = '',
}: {
  symbol?: ReactNode
  time?: ReactNode
  view?: ReactNode
  tools?: ReactNode
  drawings?: ReactNode
  overlays?: ReactNode
  commentary?: ReactNode
  className?: string
}) {
  return (
    <div className={`space-y-2 ${className}`}>
      {symbol ? (
        <div className="rounded-lg border border-slate-800/70 bg-slate-950/50 px-2.5 py-2">
          {symbol}
        </div>
      ) : null}
      {time ? (
        <div className="rounded-lg border border-slate-800/50 bg-slate-900/30 px-2.5 py-2">
          <ChartToolbarRow label="Time">{time}</ChartToolbarRow>
        </div>
      ) : null}
      {view ? (
        <div className="rounded-lg border border-slate-800/40 bg-slate-900/20 px-2.5 py-2">
          <ChartToolbarRow label="View">{view}</ChartToolbarRow>
        </div>
      ) : null}
      {tools ? (
        <div className="px-0.5">
          <ChartToolbarRow label="Tools">{tools}</ChartToolbarRow>
        </div>
      ) : null}
      {drawings ? <div className="px-0.5">{drawings}</div> : null}
      {overlays ? <div className="px-0.5">{overlays}</div> : null}
      {commentary ? <div>{commentary}</div> : null}
    </div>
  )
}
