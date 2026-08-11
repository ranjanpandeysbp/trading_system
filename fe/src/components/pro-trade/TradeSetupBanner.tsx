type Row = Record<string, unknown>

function fmtNum(v: unknown, digits = 1) {
  const n = Number(v)
  return Number.isFinite(n) ? n.toFixed(digits) : '—'
}

/** Compact trade-setup strip: action · % confidence · %SL · %TP */
export function TradeSetupBanner({
  setup,
  className = '',
}: {
  setup: Row | null | undefined
  className?: string
}) {
  if (!setup || typeof setup !== 'object') return null
  const conf = setup.confidence_pct
  const sl = setup.sl_pct
  const tp = setup.tp_pct
  if (conf == null && sl == null && tp == null) return null

  const action = String(setup.action ?? setup.direction ?? 'WAIT').toUpperCase()
  const take = Boolean(setup.take_trade)
  const grade = setup.grade != null ? String(setup.grade) : null
  const isBuy = action === 'BUY' || action === 'LONG'
  const isSell = action === 'SELL' || action === 'SHORT'
  const tone = isBuy
    ? 'border-emerald-500/35 bg-emerald-500/8'
    : isSell
      ? 'border-rose-500/35 bg-rose-500/8'
      : 'border-slate-700/70 bg-slate-950/50'

  return (
    <div className={`rounded-lg border px-3 py-2.5 ${tone} ${className}`}>
      <div className="mb-1.5 flex flex-wrap items-center gap-2">
        <span className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
          Trade setup
        </span>
        <span
          className={`rounded px-1.5 py-0.5 text-[11px] font-semibold ${
            isBuy
              ? 'bg-emerald-500/20 text-emerald-300'
              : isSell
                ? 'bg-rose-500/20 text-rose-300'
                : 'bg-slate-700/50 text-slate-300'
          }`}
        >
          {isBuy ? 'BUY' : isSell ? 'SELL' : action}
        </span>
        {take && (
          <span className="rounded bg-sky-500/15 px-1.5 py-0.5 text-[10px] text-sky-300">take</span>
        )}
        {grade && (
          <span className="rounded bg-slate-700/40 px-1.5 py-0.5 text-[10px] text-slate-300">
            grade {grade}
          </span>
        )}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm tabular-nums">
        {conf != null && (
          <span className="text-slate-200">
            <span className="text-slate-500">Conf </span>
            <span className="font-semibold text-white">{fmtNum(conf, 0)}%</span>
          </span>
        )}
        {sl != null && (
          <span className="text-rose-300">
            <span className="text-slate-500">SL </span>
            <span className="font-semibold">{fmtNum(sl, 1)}%</span>
          </span>
        )}
        {tp != null && (
          <span className="text-emerald-300">
            <span className="text-slate-500">TP </span>
            <span className="font-semibold">{fmtNum(tp, 1)}%</span>
          </span>
        )}
        {setup.rr != null && (
          <span className="text-slate-400">
            RR 1:{fmtNum(setup.rr, 1)}
          </span>
        )}
      </div>
      {setup.plain_english != null && String(setup.plain_english).trim() && (
        <p className="mt-1.5 text-[11px] leading-relaxed text-slate-400">
          {String(setup.plain_english)}
        </p>
      )}
    </div>
  )
}

/** Pull trade_setup from a result, or fall back to flat conf/sl/tp fields. */
export function tradeSetupFromResult(row: Row | null | undefined): Row | null {
  if (!row) return null
  const nested = row.trade_setup
  if (nested && typeof nested === 'object') return nested as Row
  if (row.confidence_pct != null || row.sl_pct != null || row.tp_pct != null) {
    return {
      action: row.action ?? row.direction,
      direction: row.direction,
      confidence_pct: row.confidence_pct,
      sl_pct: row.sl_pct,
      tp_pct: row.tp_pct,
      rr: row.rr,
      grade: row.grade,
      take_trade: row.take_trade,
      plain_english: row.plain_english ?? row.reason,
      entry_price: row.entry_price,
      stop_price: row.stop_price,
      target_price: row.target_price,
    }
  }
  return null
}
