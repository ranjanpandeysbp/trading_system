type Props = {
  data?: Record<string, unknown> | null
  /** Fallback when the API did not stamp an actual fetch vendor */
  assetClass?: string | null
  className?: string
}

const LABELS: Record<string, string> = {
  groww: 'Groww',
  yfinance: 'yfinance',
  coindcx: 'CoinDCX',
}

function normalizeSource(raw: unknown): string | null {
  if (raw == null || raw === '') return null
  return String(raw).trim().toLowerCase()
}

function inferFromAssetClass(assetClass?: string | null): string | null {
  const ac = (assetClass || '').toLowerCase()
  if (ac === 'us' || ac === 'commodity') return 'yfinance'
  if (ac === 'crypto') return 'coindcx'
  if (ac === 'india') return 'groww'
  return null
}

function tone(source: string): string {
  if (source === 'groww') return 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/30'
  if (source === 'yfinance') return 'bg-sky-500/15 text-sky-300 ring-sky-500/30'
  if (source === 'coindcx') return 'bg-amber-500/15 text-amber-300 ring-amber-500/30'
  return 'bg-slate-500/15 text-slate-300 ring-slate-500/30'
}

/** Compact chip for a single vendor name. */
export function DataSourceChip({ source }: { source: string }) {
  const key = normalizeSource(source) || source
  const label = LABELS[key] || source
  return (
    <span className={`inline-flex rounded-md px-2 py-0.5 text-[11px] font-semibold ring-1 ${tone(key)}`}>
      {label}
    </span>
  )
}

/**
 * Top-of-strategy bar showing which OHLCV vendor served the scan
 * (Groww / yfinance / CoinDCX). Uses API `data_source` when present.
 */
export function StrategyDataSourceBar({ data, assetClass, className = '' }: Props) {
  const primary =
    normalizeSource(data?.data_source) ||
    normalizeSource(data?.data_feed) ||
    inferFromAssetClass(assetClass)

  if (!primary) return null

  const usedRaw = data?.data_sources_used
  const used = Array.isArray(usedRaw)
    ? usedRaw.map((s) => normalizeSource(s)).filter((s): s is string => Boolean(s))
    : []
  const extras = used.filter((s) => s !== primary)
  const label = String(data?.data_source_label || LABELS[primary] || primary)
  const inferredOnly = !data?.data_source && !data?.data_feed

  return (
    <div
      className={`mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-slate-800/70 bg-slate-950/50 px-3 py-2 text-xs text-slate-400 ${className}`}
    >
      <span className="font-medium uppercase tracking-wider text-slate-500">Data source</span>
      <DataSourceChip source={primary} />
      <span className="text-slate-300">{label}</span>
      {extras.length > 0 && (
        <span className="text-slate-500">
          also used {extras.map((s) => LABELS[s] || s).join(', ')}
        </span>
      )}
      {inferredOnly && assetClass === 'india' && (
        <span className="text-slate-600">primary · yfinance used when Groww is unavailable</span>
      )}
      {inferredOnly && assetClass === 'crypto' && (
        <span className="text-slate-600">primary · yfinance used when CoinDCX is unavailable</span>
      )}
    </div>
  )
}
