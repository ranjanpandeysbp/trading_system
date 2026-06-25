interface BadgeProps {
  action: 'BUY' | 'SELL' | 'HOLD' | string
}

export function Badge({ action }: BadgeProps) {
  const normalized = action.toUpperCase()
  const styles = {
    BUY: 'bg-emerald-500/15 text-emerald-400 ring-1 ring-emerald-500/30',
    SELL: 'bg-rose-500/15 text-rose-400 ring-1 ring-rose-500/30',
    HOLD: 'bg-slate-500/15 text-slate-400 ring-1 ring-slate-500/30',
  }
  const style = styles[normalized as keyof typeof styles] ?? styles.HOLD

  return (
    <span className={`inline-flex rounded-lg px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide ${style}`}>
      {normalized}
    </span>
  )
}
