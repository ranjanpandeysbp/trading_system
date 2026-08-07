interface BadgeProps {
  action: 'BUY' | 'SELL' | 'HOLD' | string
}

export function Badge({ action }: BadgeProps) {
  const normalized = action.toUpperCase()
  const styles: Record<string, string> = {
    BUY: 'bg-emerald-500/15 text-emerald-400 ring-1 ring-emerald-500/30',
    LONG: 'bg-emerald-500/15 text-emerald-400 ring-1 ring-emerald-500/30',
    'RISK-ON': 'bg-emerald-500/15 text-emerald-400 ring-1 ring-emerald-500/30',
    SELL: 'bg-rose-500/15 text-rose-400 ring-1 ring-rose-500/30',
    SHORT: 'bg-rose-500/15 text-rose-400 ring-1 ring-rose-500/30',
    'RISK-OFF': 'bg-rose-500/15 text-rose-400 ring-1 ring-rose-500/30',
    HOLD: 'bg-slate-500/15 text-slate-400 ring-1 ring-slate-500/30',
    WAIT: 'bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/30',
    MIXED: 'bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/30',
    SIDEWAYS: 'bg-slate-500/15 text-slate-300 ring-1 ring-slate-500/30',
    AVOID: 'bg-slate-500/15 text-slate-400 ring-1 ring-slate-500/30',
  }
  const style = styles[normalized] ?? styles.HOLD

  return (
    <span className={`inline-flex rounded-lg px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide ${style}`}>
      {normalized}
    </span>
  )
}
