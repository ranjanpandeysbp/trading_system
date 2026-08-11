type Row = Record<string, unknown>

function fmtNum(v: unknown, digits = 2) {
  const n = Number(v)
  return Number.isFinite(n) ? n.toLocaleString(undefined, { maximumFractionDigits: digits }) : '—'
}

function fmtSignedPct(v: unknown, digits = 2) {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(digits)}%`
}

function fmtWhen(v: unknown) {
  if (v == null || v === '') return '—'
  const s = String(v)
  if (s.includes('IST')) return s
  return s.replace('T', ' ').slice(0, 16)
}

function fmtForecastWhen(f: Row | null | undefined) {
  if (!f) return '—'
  if (f.predicted_next_time_ist) return String(f.predicted_next_time_ist)
  return fmtWhen(f.predicted_next_time)
}

function ForecastCard({
  title,
  tone,
  forecast,
}: {
  title: string
  tone: 'fall' | 'rise'
  forecast: Row
}) {
  const border =
    tone === 'fall'
      ? 'border-rose-500/20 bg-rose-500/5'
      : 'border-emerald-500/20 bg-emerald-500/5'
  const titleCls = tone === 'fall' ? 'text-rose-200' : 'text-emerald-200'

  return (
    <div className={`rounded-lg border p-3 ${border}`}>
      <p className={`text-xs font-semibold ${titleCls}`}>{title}</p>
      {forecast.plain_english != null && (
        <p className="mt-1 text-sm text-slate-200">{String(forecast.plain_english)}</p>
      )}
      <p className="mt-2 text-xs text-slate-400">
        Confidence {String(forecast.confidence_pct ?? '—')}% · next {fmtForecastWhen(forecast)}
        {forecast.hours_until_label != null ? ` · in ${String(forecast.hours_until_label)}` : ''} · move{' '}
        {fmtSignedPct(forecast.predicted_move_pct)}
        {Number(forecast.cycles_skipped) > 0
          ? ` · rolled +${String(forecast.cycles_skipped)} past cycle(s)`
          : ''}
      </p>
      {(forecast.sl_pct != null || forecast.tp_pct != null) && (
        <p className="mt-1.5 text-xs">
          <span className="text-rose-300">SL {fmtNum(forecast.sl_pct, 1)}%</span>
          <span className="text-slate-600"> · </span>
          <span className="text-emerald-300">TP {fmtNum(forecast.tp_pct, 1)}%</span>
          {forecast.action != null ? (
            <span className="text-slate-500"> · {String(forecast.action)}</span>
          ) : null}
        </p>
      )}
    </div>
  )
}

/** Fall + Rise next-move forecast cards (Conf · next · move · SL% · TP%). */
export function FallRiseForecastCards({
  forecast,
  className = '',
  emptyHint = 'No fall/rise forecast yet — need more historical ≥threshold moves.',
}: {
  forecast: Row | null | undefined
  className?: string
  emptyHint?: string
}) {
  const fallF = (forecast?.fall as Row | undefined) ?? null
  const riseF = (forecast?.rise as Row | undefined) ?? null
  if (!fallF && !riseF) {
    return (
      <p className={`text-xs text-slate-500 ${className}`}>{emptyHint}</p>
    )
  }
  return (
    <div className={`grid gap-3 lg:grid-cols-2 ${className}`}>
      {fallF && <ForecastCard title="Fall forecast" tone="fall" forecast={fallF} />}
      {riseF && <ForecastCard title="Rise forecast" tone="rise" forecast={riseF} />}
    </div>
  )
}

export function forecastFromResult(row: Row | null | undefined): Row | null {
  if (!row) return null
  const f = row.forecast
  if (f && typeof f === 'object') return f as Row
  return null
}
