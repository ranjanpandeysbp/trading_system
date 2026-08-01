export type StockCardData = {
  name?: string
  currentPrice?: number
  marketCapitalization?: number
  industry?: string
  priceToEarning?: number
  returnOver3years?: number
  currentChangePercent?: number
  score?: string | number
  labels?: {
    labels?: {
      Negative?: string | null
      Positive?: string | null
      sectorRanking?: string | number | null
      personaRanking?: string | number | null
    }
  }
}

function fmtNum(n: number | undefined | null, digits = 2): string {
  if (n == null || Number.isNaN(n)) return '—'
  return n.toLocaleString('en-IN', { maximumFractionDigits: digits })
}

function fmtPct(n: number | undefined | null): string {
  if (n == null || Number.isNaN(n)) return '—'
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(2)}%`
}

function scoreTone(score: number): string {
  if (score >= 70) return 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300'
  if (score >= 45) return 'border-amber-500/40 bg-amber-500/15 text-amber-300'
  return 'border-rose-500/40 bg-rose-500/15 text-rose-300'
}

export function StockScorecardView({ data, symbol }: { data: StockCardData; symbol: string }) {
  const scoreNum = Number(data.score)
  const hasScore = !Number.isNaN(scoreNum)
  const change = data.currentChangePercent
  const changeUp = change != null && change >= 0
  const labels = data.labels?.labels

  const metrics: { label: string; value: string; tone?: string }[] = [
    { label: 'P/E', value: fmtNum(data.priceToEarning) },
    { label: 'MCap (Cr)', value: fmtNum(data.marketCapitalization, 0) },
    {
      label: '3Y return',
      value: fmtPct(data.returnOver3years),
      tone:
        data.returnOver3years == null
          ? undefined
          : data.returnOver3years >= 0
            ? 'text-emerald-400'
            : 'text-rose-400',
    },
  ]

  return (
    <div className="mt-4 overflow-hidden rounded-xl border border-slate-700/60 bg-slate-900/60">
      <div className="flex items-start justify-between gap-3 border-b border-slate-800/80 px-4 py-3">
        <div className="min-w-0">
          <p className="text-[10px] font-medium uppercase tracking-wider text-slate-500">{symbol}</p>
          <h4 className="truncate text-base font-semibold text-white">{data.name || symbol}</h4>
          {data.industry && <p className="mt-0.5 truncate text-xs text-slate-500">{data.industry}</p>}
        </div>
        {hasScore && (
          <div
            className={`flex h-12 w-12 shrink-0 flex-col items-center justify-center rounded-xl border ${scoreTone(scoreNum)}`}
            title="Score"
          >
            <span className="text-[9px] uppercase tracking-wide opacity-70">Score</span>
            <span className="text-lg font-bold leading-none tabular-nums">{scoreNum}</span>
          </div>
        )}
      </div>

      <div className="px-4 py-3">
        <div className="flex items-baseline gap-2">
          <span className="text-2xl font-bold tabular-nums text-white">₹{fmtNum(data.currentPrice, 2)}</span>
          {change != null && (
            <span className={`text-sm font-medium tabular-nums ${changeUp ? 'text-emerald-400' : 'text-rose-400'}`}>
              {fmtPct(change)}
            </span>
          )}
        </div>

        <div className="mt-3 grid grid-cols-3 gap-2">
          {metrics.map((m) => (
            <div key={m.label} className="rounded-lg bg-slate-950/50 px-2 py-2">
              <p className="text-[10px] uppercase tracking-wide text-slate-500">{m.label}</p>
              <p className={`mt-0.5 text-sm font-semibold tabular-nums ${m.tone ?? 'text-slate-200'}`}>{m.value}</p>
            </div>
          ))}
        </div>

        {(labels?.Positive || labels?.Negative) && (
          <div className="mt-3 flex flex-wrap gap-2">
            {labels.Positive && (
              <span className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-xs text-emerald-300">
                + {labels.Positive}
              </span>
            )}
            {labels.Negative && (
              <span className="rounded-md border border-rose-500/30 bg-rose-500/10 px-2 py-1 text-xs text-rose-300">
                − {labels.Negative}
              </span>
            )}
          </div>
        )}

        {(labels?.sectorRanking != null || labels?.personaRanking != null) && (
          <div className="mt-3 flex gap-4 text-xs text-slate-500">
            {labels.sectorRanking != null && <span>Sector rank: {String(labels.sectorRanking)}</span>}
            {labels.personaRanking != null && <span>Persona rank: {String(labels.personaRanking)}</span>}
          </div>
        )}
      </div>
    </div>
  )
}
