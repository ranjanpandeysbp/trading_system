/** Shared BUY / SELL / WAIT trade setup block (confidence · SL% · TP% · explanation). */

type Row = Record<string, unknown>

function fmtNum(v: unknown, digits = 2): string {
  if (v == null || v === '') return '—'
  const n = Number(v)
  return Number.isFinite(n) ? n.toLocaleString(undefined, { maximumFractionDigits: digits }) : '—'
}

function tradeActionBadgeClass(action: string): string {
  const a = action.toUpperCase()
  if (a === 'BUY') return 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300'
  if (a === 'SELL') return 'border-rose-500/40 bg-rose-500/15 text-rose-300'
  return 'border-slate-600/60 bg-slate-800/60 text-slate-300'
}

/** Resolve trade_suggestion from result / live / top-level fields. */
export function resolveTradeSuggestion(result: Row, fallbackSl?: number | null, fallbackTp?: number | null): Row {
  const fromResult = result.trade_suggestion as Row | undefined
  const live = (result.live as Row | undefined) ?? {}
  const fromLive = live.trade_suggestion as Row | undefined
  if (fromResult && fromResult.action != null) return fromResult
  if (fromLive && fromLive.action != null) return fromLive

  const direction = String(live.direction ?? result.direction ?? '').toUpperCase()
  const take = Boolean(live.take_trade ?? result.take_trade)
  let action = String(result.action ?? live.action ?? result.signal ?? 'WAIT').toUpperCase()
  let actionLabel = String(result.action_label ?? action)
  if (take && (direction === 'LONG' || action === 'BUY')) {
    action = 'BUY'
    actionLabel = String(live.option_action ?? result.action_label ?? 'BUY')
  } else if (take && (direction === 'SHORT' || action === 'SELL')) {
    action = 'SELL'
    actionLabel = String(live.option_action ?? result.action_label ?? 'SELL')
  } else if (!take && (action === 'BUY' || action === 'SELL') && live.take_trade === false && result.take_trade !== true) {
    // Keep directional bias visible when prediction says BUY/SELL even if not yet actionable
    actionLabel = action
  } else if (action !== 'BUY' && action !== 'SELL') {
    action = 'WAIT'
    actionLabel = 'WAIT'
  }

  const pred = (result.prediction as Row | undefined) ?? {}
  const conf = live.confidence_pct ?? result.confidence_pct ?? pred.confidence_pct
  const sl = live.sl_pct ?? result.sl_pct ?? fallbackSl ?? null
  const tp = live.tp_pct ?? result.tp_pct ?? fallbackTp ?? null
  const rr = sl != null && tp != null && Number(sl) > 0 ? Number(tp) / Number(sl) : null

  return {
    action,
    action_label: actionLabel,
    confidence_pct: conf,
    sl_pct: sl,
    tp_pct: tp,
    rr: rr != null ? Math.round(rr * 100) / 100 : null,
    entry_price: live.entry_price ?? result.entry_price ?? result.ltp,
    stop_price: live.stop_price ?? result.stop_price,
    target_price: live.target_price ?? result.target_price,
    plain_english: result.plain_english ?? live.plain_english ?? pred.plain_english,
    confidence_reasons:
      (fromResult?.reasons as string[] | undefined)
      ?? (fromLive?.reasons as string[] | undefined)
      ?? (live.reasons as string[] | undefined)?.slice(0, 4)
      ?? [],
  }
}

export function TradeSignalBlock({
  trade,
  currency = '',
  legend,
  entryLabel = 'Entry',
}: {
  trade: Row
  currency?: string
  legend?: string
  entryLabel?: string
}) {
  const action = String(trade.action ?? 'WAIT').toUpperCase()
  const actionLabel = String(trade.action_label ?? action)
  const confReasons =
    (trade.confidence_reasons as string[] | undefined)
    ?? (trade.reasons as string[] | undefined)
    ?? []

  return (
    <div className="rounded-xl border border-slate-700/50 bg-slate-950/40 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`inline-flex items-center rounded-lg border px-3 py-1 text-sm font-semibold ${tradeActionBadgeClass(action)}`}>
          {action}
        </span>
        <span className="text-xs font-medium text-slate-300">{actionLabel}</span>
        {trade.confidence_pct != null && (
          <span className="text-xs font-medium text-teal-300">{fmtNum(trade.confidence_pct, 0)}% confidence</span>
        )}
        {trade.grade != null && (
          <span className="inline-flex items-center rounded-md border border-slate-700/60 bg-slate-800/50 px-2 py-0.5 text-xs font-semibold text-slate-300">
            Grade {String(trade.grade)}
          </span>
        )}
      </div>
      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div>
          <p className="text-xs text-slate-500">{entryLabel}</p>
          <p className="font-medium text-white">{currency}{fmtNum(trade.entry_price, 4)}</p>
        </div>
        <div>
          <p className="text-xs text-slate-500">Stop-loss</p>
          <p className="font-medium text-rose-400">
            {trade.sl_pct != null ? `−${fmtNum(trade.sl_pct, 1)}%` : '—'}
            {trade.stop_price != null && (
              <span className="ml-1 text-xs font-normal text-slate-500">({currency}{fmtNum(trade.stop_price, 4)})</span>
            )}
          </p>
        </div>
        <div>
          <p className="text-xs text-slate-500">Target</p>
          <p className="font-medium text-emerald-400">
            {trade.tp_pct != null ? `+${fmtNum(trade.tp_pct, 1)}%` : '—'}
            {trade.target_price != null && (
              <span className="ml-1 text-xs font-normal text-slate-500">({currency}{fmtNum(trade.target_price, 4)})</span>
            )}
          </p>
        </div>
        <div>
          <p className="text-xs text-slate-500">Reward : Risk</p>
          <p className="font-medium text-white">{trade.rr != null ? `1 : ${fmtNum(trade.rr, 2)}` : '—'}</p>
        </div>
      </div>
      {(trade.plain_english != null || trade.advice != null) && (
        <p className="mt-3 text-xs leading-relaxed text-slate-300">{String(trade.plain_english ?? trade.advice)}</p>
      )}
      {confReasons.length > 0 && (
        <ul className="mt-2 space-y-0.5 border-t border-slate-800/60 pt-2">
          {confReasons.slice(0, 6).map((r) => (
            <li key={r} className="text-xs text-slate-500">· {r}</li>
          ))}
        </ul>
      )}
      {legend && <p className="mt-2 text-[11px] text-slate-500">{legend}</p>}
    </div>
  )
}
