type VolumeSrSummary = {
  summary?: string | null
  plain_english?: string | null
  volume_trend?: string | null
  volume_label?: string | null
  volume_change_pct?: number | null
  approach?: string | null
  approach_label?: string | null
  approach_level?: number | null
  distance_pct?: number | null
  break_bias?: string | null
  break_probability_pct?: number | null
  break_target?: string | null
}

function biasTone(bias: string | null | undefined): string {
  if (!bias) return 'border-slate-700/60 bg-slate-900/40 text-slate-300'
  if (bias.includes('break_resistance') || bias.includes('break_support')) {
    return 'border-amber-500/40 bg-amber-500/10 text-amber-200'
  }
  if (bias.includes('hold_')) {
    return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200'
  }
  if (bias.includes('consolidat') || bias.includes('quiet') || bias.includes('range')) {
    return 'border-slate-600/50 bg-slate-800/40 text-slate-300'
  }
  return 'border-sky-500/30 bg-sky-500/10 text-sky-200'
}

/** Compact card under each instrument chart: volume trend + S/R break heuristic. */
export function VolumeSrSummaryCard({ data }: { data?: VolumeSrSummary | null }) {
  if (!data) return null
  const prob = data.break_probability_pct
  const bias = data.break_bias
  return (
    <div className={`mt-2 rounded-lg border px-2.5 py-2 text-[11px] leading-relaxed ${biasTone(bias)}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold text-white/90">{data.summary ?? 'Volume / S/R read'}</span>
        {prob != null && Number.isFinite(Number(prob)) && (
          <span className="rounded bg-black/30 px-1.5 py-0.5 font-semibold tabular-nums text-white">
            ~{Math.round(Number(prob))}% break
          </span>
        )}
        {data.volume_label && (
          <span className="text-[10px] opacity-80">
            {data.volume_label}
            {data.volume_change_pct != null ? ` (${Number(data.volume_change_pct) >= 0 ? '+' : ''}${data.volume_change_pct}%)` : ''}
          </span>
        )}
      </div>
      {data.plain_english && (
        <p className="mt-1 text-[11px] opacity-90">{data.plain_english}</p>
      )}
    </div>
  )
}

export type { VolumeSrSummary }
