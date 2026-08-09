import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { apiErrorMessage, runOptionsDeltaNeutralPnl, runOptionsDoubleCalendarPnl, runOptionsHedgingPnl } from '../../api/client'
import { Button } from '../ui/Button'
import { Input, Label } from '../ui/Form'

type Row = Record<string, unknown>

function fmtNum(v: unknown, digits = 2): string {
  if (v == null || v === '') return '—'
  const n = Number(v)
  return Number.isFinite(n) ? n.toLocaleString(undefined, { maximumFractionDigits: digits }) : '—'
}

function ltpStr(ltp: Row | undefined, currency: string): string {
  const price = ltp?.price
  return price != null ? `${currency}${fmtNum(price, 4)}` : '—'
}

const DOUBLE_CALENDAR_LEG_ORDER: Array<[string, string]> = [
  ['short_call', 'Short Call'],
  ['short_put', 'Short Put'],
  ['long_call', 'Long Call'],
  ['long_put', 'Long Put'],
]

const DELTA_NEUTRAL_LEG_ORDER: Array<[string, string]> = [
  ['short_call', 'Short Call'],
  ['short_put', 'Short Put'],
  ['long_call', 'Long Call (wing)'],
  ['long_put', 'Long Put (wing)'],
]

const HEDGING_LEG_ORDER: Array<[string, string]> = [
  ['short_call', 'Short ATM Call'],
  ['short_put', 'Short ATM Put'],
  ['long_call', 'Long Call (hedge)'],
  ['long_put', 'Long Put (hedge)'],
]

const ADJUSTMENT_BADGE: Record<string, string> = {
  ADJUST_CALL: '🔴 Adjust — exit Call leg',
  ADJUST_PUT: '🔴 Adjust — exit Put leg',
  WATCH_DEMAND: '🟡 Watching Demand',
  WATCH_SUPPLY: '🟡 Watching Supply',
  HOLD: '🟢 Hold',
  NO_DATA: '⚪ No data',
}

function tradeActionBadgeClass(action: string): string {
  const a = action.toUpperCase()
  if (a === 'BUY') return 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300'
  if (a === 'SELL') return 'border-rose-500/40 bg-rose-500/15 text-rose-300'
  return 'border-slate-600/60 bg-slate-800/60 text-slate-300'
}

/** Resolve trade_suggestion from result / live / top-level fields. */
function resolveTradeSuggestion(result: Row, fallbackSl?: number | null, fallbackTp?: number | null): Row {
  const fromResult = result.trade_suggestion as Row | undefined
  const live = (result.live as Row | undefined) ?? {}
  const fromLive = live.trade_suggestion as Row | undefined
  if (fromResult && fromResult.action != null) return fromResult
  if (fromLive && fromLive.action != null) return fromLive

  const direction = String(live.direction ?? result.direction ?? '').toUpperCase()
  const take = Boolean(live.take_trade ?? result.take_trade)
  let action = String(result.action ?? live.action ?? 'WAIT').toUpperCase()
  let actionLabel = String(result.action_label ?? 'WAIT')
  if (take && (direction === 'LONG' || action === 'BUY')) {
    action = 'BUY'
    actionLabel = String(live.option_action ?? 'BUY CALL')
  } else if (take && (direction === 'SHORT' || action === 'SELL')) {
    action = 'SELL'
    actionLabel = String(live.option_action ?? 'BUY PUT')
  } else if (!take && (action === 'BUY' || action === 'SELL') && live.take_trade === false) {
    action = 'WAIT'
    actionLabel = 'WAIT'
  } else if (action !== 'BUY' && action !== 'SELL') {
    action = 'WAIT'
    actionLabel = actionLabel === 'WAIT' ? 'WAIT' : actionLabel
  }

  const conf = live.confidence_pct ?? result.confidence_pct
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
    entry_price: live.entry_price ?? result.entry_price ?? result.net_debit ?? result.net_credit,
    stop_price: live.stop_price ?? result.stop_price ?? result.stop_loss_price ?? result.defensive_close_price ?? result.loss_limit,
    target_price: live.target_price ?? result.target_price ?? result.take_profit_start_price ?? result.close_at_price ?? result.profit_target,
    plain_english: result.plain_english ?? live.plain_english,
    confidence_reasons: (live.reasons as string[] | undefined)?.slice(0, 4) ?? [],
  }
}

function OptionsSignalHeaderChips({ trade }: { trade: Row }) {
  const action = String(trade.action ?? 'WAIT').toUpperCase()
  return (
    <>
      <span className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-semibold uppercase tracking-wide ${tradeActionBadgeClass(action)}`}>
        {action}
      </span>
      {trade.confidence_pct != null && (
        <span className="text-xs font-medium text-teal-300">{fmtNum(trade.confidence_pct, 0)}% conf</span>
      )}
      <span className="text-xs text-slate-500">
        SL {trade.sl_pct != null ? `${fmtNum(trade.sl_pct, 1)}%` : '—'} · TP {trade.tp_pct != null ? `${fmtNum(trade.tp_pct, 1)}%` : '—'}
      </span>
    </>
  )
}

function OptionsTradeSignalBlock({
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

function OptionLegsTable({ legs, currency, legOrder }: { legs: Row; currency: string; legOrder: Array<[string, string]> }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-800/60">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-slate-800/60 text-left text-slate-500">
            <th className="px-2 py-1.5">Leg</th>
            <th className="px-2 py-1.5">Strike</th>
            <th className="px-2 py-1.5">Expiry</th>
            <th className="px-2 py-1.5">Premium</th>
            <th className="px-2 py-1.5">IV</th>
            <th className="px-2 py-1.5">Source</th>
          </tr>
        </thead>
        <tbody>
          {legOrder.map(([key, label]) => {
            const leg = (legs[key] as Row) ?? {}
            const iv = leg.iv as number | null
            const simulated = String(leg.source ?? '').startsWith('Simulated')
            return (
              <tr key={key} className="border-b border-slate-800/40 last:border-0 text-slate-300">
                <td className="px-2 py-1.5 font-medium text-white">{label}</td>
                <td className="px-2 py-1.5">{currency}{fmtNum(leg.strike, 4)}</td>
                <td className="px-2 py-1.5">{String(leg.expiry ?? '—')}</td>
                <td className="px-2 py-1.5">{currency}{fmtNum(leg.premium, 4)}</td>
                <td className="px-2 py-1.5">{iv != null ? `${fmtNum(iv, 1)}%` : '—'}</td>
                <td className={`px-2 py-1.5 ${simulated ? 'text-amber-400' : 'text-slate-500'}`}>{String(leg.source ?? '—')}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function DoubleCalendarResultCard({
  result, index, currency, stopLoss, takeProfitStart, takeProfitMax,
}: {
  result: Row
  index: number
  currency: string
  stopLoss: number
  takeProfitStart: number
  takeProfitMax: number
}) {
  const [open, setOpen] = useState(index === 0)
  const ticker = String(result.ticker ?? '?')

  if (result.error) {
    return (
      <div className="rounded-lg border border-rose-500/30 bg-rose-500/5 px-3 py-2 text-sm text-rose-300">
        <strong>{ticker}</strong> — {String(result.error)}
      </div>
    )
  }

  const volEnv = (result.vol_environment as Row) ?? {}
  const entryOk = Boolean(result.entry_ok)
  const isDiagonal = Boolean(result.is_diagonal)
  const trendContext = (result.trend_context as Row[]) ?? []
  const reasons = (result.reasons as string[]) ?? []
  const netDebit = Number(result.net_debit ?? 0)
  const ltp = result.ltp as Row | undefined
  const trade = resolveTradeSuggestion(result, Math.abs(stopLoss) * 100, takeProfitStart * 100)

  const [mark, setMark] = useState(netDebit)
  const pnlMut = useMutation({
    mutationFn: () => runOptionsDoubleCalendarPnl({
      net_debit: netDebit, current_mark: mark,
      stop_loss: stopLoss, take_profit_start: takeProfitStart, take_profit_max: takeProfitMax,
    }),
  })
  const pnl = pnlMut.data as Row | undefined

  return (
    <div className="rounded-lg border border-slate-800/60 bg-slate-900/40">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full flex-wrap items-center gap-2 px-3 py-2.5 text-left text-sm text-slate-300 hover:bg-slate-800/30"
      >
        {open ? <ChevronDown size={14} className="shrink-0 text-slate-500" /> : <ChevronRight size={14} className="shrink-0 text-slate-500" />}
        <span className="font-semibold text-white">{ticker}</span>
        <OptionsSignalHeaderChips trade={trade} />
        <span className="text-slate-500">
          · LTP {ltpStr(ltp, currency)} · {isDiagonal ? 'Double Diagonal' : 'Double Calendar'} · {entryOk ? '✅ Favorable' : '❌ Unfavorable'} IV/vol ·
          {' '}Net debit {currency}{fmtNum(netDebit, 4)}
        </span>
      </button>
      {open && (
        <div className="space-y-3 border-t border-slate-800/60 px-3 py-3 text-sm">
          <OptionsTradeSignalBlock
            trade={trade}
            currency={currency}
            entryLabel="Entry (net debit)"
            legend="BUY = enter the calendar · WAIT = skip until IV/range improves · SL/TP are % of debit paid"
          />

          <p className="text-slate-300">
            <strong>LTP {ltpStr(ltp, currency)}</strong> {ltp?.price != null ? <span className="text-xs text-slate-500">(live quote)</span> : null} ·{' '}
            Spot (last close) <strong>{currency}{fmtNum(result.spot, 4)}</strong> · Realized vol <strong>{fmtNum(result.realized_vol_pct, 2)}%</strong>
          </p>
          <div>
            <p className="text-slate-300">
              <strong>IV/Vol environment ({String(volEnv.source ?? '—')}):</strong> {String(volEnv.label ?? '—')} — {entryOk ? '✅ Favorable' : '❌ Unfavorable'}
            </p>
            <p className="text-xs text-slate-500">{String(volEnv.reason ?? '')}</p>
          </div>

          {trendContext.length > 0 && (
            <div>
              <p className="mb-1 font-medium text-slate-300">Trend / range context</p>
              <div className="overflow-x-auto rounded-lg border border-slate-800/60">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-slate-800/60 text-left text-slate-500">
                      <th className="px-2 py-1">TF</th>
                      <th className="px-2 py-1">Direction</th>
                      <th className="px-2 py-1">Strength</th>
                      <th className="px-2 py-1">ADX</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trendContext.map((t, i) => (
                      <tr key={i} className="border-b border-slate-800/40 last:border-0 text-slate-300">
                        <td className="px-2 py-1">{String(t.timeframe)}</td>
                        <td className="px-2 py-1">{String(t.trend_direction)}</td>
                        <td className="px-2 py-1">{String(t.strength)}</td>
                        <td className="px-2 py-1">{fmtNum(t.adx, 1)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div>
            <p className="mb-1 text-slate-300">
              <strong>Legs</strong> — short ~{String(result.short_expiry_target)} · long ~{String(result.long_expiry_target)} ·
              {' '}{fmtNum(result.otm_offset_pct, 1)}% OTM
            </p>
            <OptionLegsTable legs={(result.legs as Row) ?? {}} currency={currency} legOrder={DOUBLE_CALENDAR_LEG_ORDER} />
          </div>

          <p className="text-slate-300">
            <strong>Net debit: {currency}{fmtNum(netDebit, 4)}</strong> ·{' '}
            Scale-out ≥ {currency}{fmtNum(result.take_profit_start_price, 4)} ·{' '}
            Close by {currency}{fmtNum(result.take_profit_max_price, 4)} ·{' '}
            Mental stop ≤ {currency}{fmtNum(result.stop_loss_price, 4)}
          </p>

          {reasons.map((r, i) => (
            <p key={i} className="text-xs text-slate-500">· {r}</p>
          ))}

          <div className="rounded-lg border border-slate-800/60 bg-slate-900/30 p-2.5">
            <Label>Check current spread value</Label>
            <div className="flex flex-wrap items-center gap-2">
              <Input
                type="number"
                step="0.01"
                value={mark}
                onChange={(e) => setMark(Number(e.target.value))}
                className="max-w-[160px]"
              />
              <Button size="sm" variant="secondary" onClick={() => pnlMut.mutate()} disabled={pnlMut.isPending}>
                {pnlMut.isPending ? 'Checking…' : 'Check P&L'}
              </Button>
            </div>
            {pnlMut.isError && <p className="mt-2 text-xs text-rose-400">{apiErrorMessage(pnlMut.error)}</p>}
            {pnl && !pnl.error && (
              <div className="mt-2">
                <p className="font-semibold text-white">P&L: {Number(pnl.pnl_pct) >= 0 ? '+' : ''}{fmtNum(pnl.pnl_pct, 1)}%</p>
                <p className="text-xs text-slate-400">{String(pnl.message ?? '')}</p>
              </div>
            )}
            {Boolean(pnl?.error) && <p className="mt-2 text-xs text-amber-400">{String(pnl?.error)}</p>}
          </div>
        </div>
      )}
    </div>
  )
}

export function DoubleCalendarPanel({
  data, stopLoss, takeProfitStart, takeProfitMax,
}: {
  data: Row
  stopLoss: number
  takeProfitStart: number
  takeProfitMax: number
}) {
  const results = (data.results as Row[]) ?? []
  const currency = String(data.currency ?? '')
  if (!results.length) return <p className="text-sm text-slate-500">No results yet.</p>

  return (
    <div className="space-y-2">
      {results.map((res, i) => (
        <DoubleCalendarResultCard
          key={i} result={res} index={i} currency={currency}
          stopLoss={stopLoss} takeProfitStart={takeProfitStart} takeProfitMax={takeProfitMax}
        />
      ))}
    </div>
  )
}

function DeltaNeutralResultCard({
  result, index, currency, profitTargetPct, stopLossMultiple,
}: {
  result: Row
  index: number
  currency: string
  profitTargetPct: number
  stopLossMultiple: number
}) {
  const [open, setOpen] = useState(index === 0)
  const ticker = String(result.ticker ?? '?')

  if (result.error) {
    return (
      <div className="rounded-lg border border-rose-500/30 bg-rose-500/5 px-3 py-2 text-sm text-rose-300">
        <strong>{ticker}</strong> — {String(result.error)}
      </div>
    )
  }

  const volEnv = (result.vol_environment as Row) ?? {}
  const entryOk = Boolean(result.entry_ok)
  const choppy = Boolean(result.choppy)
  const trendContext = (result.trend_context as Row[]) ?? []
  const reasons = (result.reasons as string[]) ?? []
  const netCredit = Number(result.net_credit ?? 0)
  const defensiveClose = result.defensive_close_price as number | null
  const ltp = result.ltp as Row | undefined
  const trade = resolveTradeSuggestion(result, stopLossMultiple * 100, profitTargetPct * 100)

  const [mark, setMark] = useState(netCredit)
  const pnlMut = useMutation({
    mutationFn: () => runOptionsDeltaNeutralPnl({
      net_credit: netCredit, current_cost_to_close: mark,
      profit_target_pct: profitTargetPct, stop_loss_multiple: stopLossMultiple,
    }),
  })
  const pnl = pnlMut.data as Row | undefined

  return (
    <div className="rounded-lg border border-slate-800/60 bg-slate-900/40">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full flex-wrap items-center gap-2 px-3 py-2.5 text-left text-sm text-slate-300 hover:bg-slate-800/30"
      >
        {open ? <ChevronDown size={14} className="shrink-0 text-slate-500" /> : <ChevronRight size={14} className="shrink-0 text-slate-500" />}
        <span className="font-semibold text-white">{ticker}</span>
        <OptionsSignalHeaderChips trade={trade} />
        <span className="text-slate-500">
          · LTP {ltpStr(ltp, currency)} · {String(result.structure ?? '—')} · {entryOk ? '✅ Favorable' : '❌ Unfavorable'} ·
          {' '}Net credit {currency}{fmtNum(netCredit, 4)} · POP ~{fmtNum(result.pop_pct, 0)}%
        </span>
      </button>
      {open && (
        <div className="space-y-3 border-t border-slate-800/60 px-3 py-3 text-sm">
          <OptionsTradeSignalBlock
            trade={trade}
            currency={currency}
            entryLabel="Entry (net credit)"
            legend="BUY = sell the iron structure · WAIT = skip until vol is high and tape is choppy · TP/SL vs credit received"
          />

          <p className="text-slate-300">
            <strong>LTP {ltpStr(ltp, currency)}</strong> {ltp?.price != null ? <span className="text-xs text-slate-500">(live quote)</span> : null} ·{' '}
            Spot (last close) <strong>{currency}{fmtNum(result.spot, 4)}</strong> · Realized vol <strong>{fmtNum(result.realized_vol_pct, 2)}%</strong>
          </p>
          <div>
            <p className="text-slate-300">
              <strong>IV/Vol environment ({String(volEnv.source ?? '—')}):</strong> {String(volEnv.label ?? '—')} — {Boolean(volEnv.favorable) ? '✅ favorable' : '❌ unfavorable'}
            </p>
            <p className="text-xs text-slate-500">{String(volEnv.reason ?? '')}</p>
          </div>
          <p className="text-slate-300">
            <strong>Market context:</strong> {choppy ? '✅ choppy/range-bound' : '⚠️ trending'}
          </p>

          {trendContext.length > 0 && (
            <div>
              <p className="mb-1 font-medium text-slate-300">Trend / range context</p>
              <div className="overflow-x-auto rounded-lg border border-slate-800/60">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-slate-800/60 text-left text-slate-500">
                      <th className="px-2 py-1">TF</th>
                      <th className="px-2 py-1">Direction</th>
                      <th className="px-2 py-1">Strength</th>
                      <th className="px-2 py-1">ADX</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trendContext.map((t, i) => (
                      <tr key={i} className="border-b border-slate-800/40 last:border-0 text-slate-300">
                        <td className="px-2 py-1">{String(t.timeframe)}</td>
                        <td className="px-2 py-1">{String(t.trend_direction)}</td>
                        <td className="px-2 py-1">{String(t.strength)}</td>
                        <td className="px-2 py-1">{fmtNum(t.adx, 1)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div>
            <p className="mb-1 text-slate-300">
              <strong>Legs</strong> — expiry ~{String(result.target_expiry)} · target Δ {fmtNum(result.short_delta_target, 2)} ·
              {' '}wing {fmtNum(result.wing_width_pct, 1)}% OTM
            </p>
            <OptionLegsTable legs={(result.legs as Row) ?? {}} currency={currency} legOrder={DELTA_NEUTRAL_LEG_ORDER} />
          </div>

          <p className="text-slate-300">
            <strong>Net credit: {currency}{fmtNum(netCredit, 4)}</strong> ·{' '}
            Max profit {currency}{fmtNum(result.max_profit, 4)} ·{' '}
            Max loss {currency}{fmtNum(result.max_loss, 4)} ·{' '}
            Est. POP {fmtNum(result.pop_pct, 0)}%
          </p>
          <p className="text-slate-300">
            Close at ≤ {currency}{fmtNum(result.close_at_price, 4)} (target)
            {defensiveClose != null ? <> · Defensive close ≥ {currency}{fmtNum(defensiveClose, 4)}</> : null}
          </p>

          {reasons.map((r, i) => (
            <p key={i} className="text-xs text-slate-500">· {r}</p>
          ))}

          <div className="rounded-lg border border-slate-800/60 bg-slate-900/30 p-2.5">
            <Label>Check current cost to close the spread</Label>
            <div className="flex flex-wrap items-center gap-2">
              <Input
                type="number"
                step="0.01"
                value={mark}
                onChange={(e) => setMark(Number(e.target.value))}
                className="max-w-[160px]"
              />
              <Button size="sm" variant="secondary" onClick={() => pnlMut.mutate()} disabled={pnlMut.isPending}>
                {pnlMut.isPending ? 'Checking…' : 'Check P&L'}
              </Button>
            </div>
            {pnlMut.isError && <p className="mt-2 text-xs text-rose-400">{apiErrorMessage(pnlMut.error)}</p>}
            {pnl && !pnl.error && (
              <div className="mt-2">
                <p className="font-semibold text-white">P&L: {Number(pnl.pnl_pct) >= 0 ? '+' : ''}{fmtNum(pnl.pnl_pct, 1)}% of max credit</p>
                <p className="text-xs text-slate-400">{String(pnl.message ?? '')}</p>
              </div>
            )}
            {Boolean(pnl?.error) && <p className="mt-2 text-xs text-amber-400">{String(pnl?.error)}</p>}
          </div>
        </div>
      )}
    </div>
  )
}

export function DeltaNeutralPanel({
  data, profitTargetPct, stopLossMultiple,
}: {
  data: Row
  profitTargetPct: number
  stopLossMultiple: number
}) {
  const results = (data.results as Row[]) ?? []
  const currency = String(data.currency ?? '')
  if (!results.length) return <p className="text-sm text-slate-500">No results yet.</p>

  return (
    <div className="space-y-2">
      {results.map((res, i) => (
        <DeltaNeutralResultCard
          key={i} result={res} index={i} currency={currency}
          profitTargetPct={profitTargetPct} stopLossMultiple={stopLossMultiple}
        />
      ))}
    </div>
  )
}

function HedgingResultCard({
  result, index, currency, totalCapital, profitTargetPctOfCapital, maxLossPctOfCapital,
}: {
  result: Row
  index: number
  currency: string
  totalCapital: number
  profitTargetPctOfCapital: number
  maxLossPctOfCapital: number
}) {
  const [open, setOpen] = useState(index === 0)
  const ticker = String(result.ticker ?? '?')

  if (result.error) {
    return (
      <div className="rounded-lg border border-rose-500/30 bg-rose-500/5 px-3 py-2 text-sm text-rose-300">
        <strong>{ticker}</strong> — {String(result.error)}
      </div>
    )
  }

  const netCredit = Number(result.net_credit ?? 0)
  const demand = result.demand_zone as Row | null
  const supply = result.supply_zone as Row | null
  const adjustment = (result.adjustment_signal as Row) ?? {}
  const adjStatus = String(adjustment.status ?? 'NO_DATA')
  const trade = resolveTradeSuggestion(result, maxLossPctOfCapital * 100, profitTargetPctOfCapital * 100)
  const reasons = (result.reasons as string[]) ?? []
  const ltp = result.ltp as Row | undefined

  const [currentPnl, setCurrentPnl] = useState(0)
  const pnlMut = useMutation({
    mutationFn: () => runOptionsHedgingPnl({
      total_capital: totalCapital, current_pnl: currentPnl,
      profit_target_pct_of_capital: profitTargetPctOfCapital, max_loss_pct_of_capital: maxLossPctOfCapital,
    }),
  })
  const pnl = pnlMut.data as Row | undefined

  return (
    <div className="rounded-lg border border-slate-800/60 bg-slate-900/40">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full flex-wrap items-center gap-2 px-3 py-2.5 text-left text-sm text-slate-300 hover:bg-slate-800/30"
      >
        {open ? <ChevronDown size={14} className="shrink-0 text-slate-500" /> : <ChevronRight size={14} className="shrink-0 text-slate-500" />}
        <span className="font-semibold text-white">{ticker}</span>
        <OptionsSignalHeaderChips trade={trade} />
        <span className="text-slate-500">
          · LTP {ltpStr(ltp, currency)} · {ADJUSTMENT_BADGE[adjStatus] ?? adjStatus} ·{' '}
          Net credit {currency}{fmtNum(netCredit, 4)}
        </span>
      </button>
      {open && (
        <div className="space-y-3 border-t border-slate-800/60 px-3 py-3 text-sm">
          <OptionsTradeSignalBlock
            trade={trade}
            currency={currency}
            entryLabel="Entry (net credit)"
            legend="BUY = enter the hedge · SELL = exit/adjust now · WAIT = stand by (no new entry/adjustment)"
          />

          <p className="text-slate-300">
            <strong>LTP {ltpStr(ltp, currency)}</strong> {ltp?.price != null ? <span className="text-xs text-slate-500">(live quote)</span> : null} ·{' '}
            Spot (last close) <strong>{currency}{fmtNum(result.spot, 4)}</strong>
          </p>

          <div className="rounded-lg border border-slate-800/60 bg-slate-900/30 p-2.5">
            <p className="mb-1 font-medium text-slate-300">Demand / Supply zones ({String(result.zone_timeframe ?? '—')} chart{Boolean(result.zone_fallback_used) ? ', fallback timeframe' : ''})</p>
            <p className="text-xs text-slate-400">
              Session open <strong className="text-slate-200">{currency}{fmtNum(result.session_open, 4)}</strong>
              {' · '}Demand {demand ? <strong className="text-emerald-400">{currency}{fmtNum(demand.bottom, 4)}–{currency}{fmtNum(demand.top, 4)}</strong> : 'not found'}
              {' · '}Supply {supply ? <strong className="text-rose-400">{currency}{fmtNum(supply.bottom, 4)}–{currency}{fmtNum(supply.top, 4)}</strong> : 'not found'}
            </p>
            <p className="mt-1.5 text-xs text-slate-300">{ADJUSTMENT_BADGE[adjStatus] ?? adjStatus}: {String(adjustment.note ?? '')}</p>
          </div>

          <div>
            <p className="mb-1 text-slate-300">
              <strong>Legs</strong> — expiry ~{String(result.target_expiry)} · hedges {fmtNum(result.hedge_distance_pct, 1)}% away from spot
            </p>
            <OptionLegsTable legs={(result.legs as Row) ?? {}} currency={currency} legOrder={HEDGING_LEG_ORDER} />
          </div>

          <p className="text-slate-300">
            <strong>Net credit: {currency}{fmtNum(netCredit, 4)}</strong> ·{' '}
            Max profit {currency}{fmtNum(result.max_profit, 4)} ·{' '}
            Max loss {currency}{fmtNum(result.max_loss, 4)} (capped by the hedges)
          </p>
          <p className="text-slate-300">
            Profit target ≈ {currency}{fmtNum(result.profit_target, 0)} · Hard stop ≈ {currency}{fmtNum(result.loss_limit, 0)}
            {' '}(on {currency}{fmtNum(result.total_capital, 0)} total capital)
          </p>

          {reasons.map((r, i) => (
            <p key={i} className="text-xs text-slate-500">· {r}</p>
          ))}

          <div className="rounded-lg border border-slate-800/60 bg-slate-900/30 p-2.5">
            <Label>Check current running P&amp;L on the whole hedge</Label>
            <div className="flex flex-wrap items-center gap-2">
              <Input
                type="number"
                step="1"
                value={currentPnl}
                onChange={(e) => setCurrentPnl(Number(e.target.value))}
                className="max-w-[160px]"
              />
              <Button size="sm" variant="secondary" onClick={() => pnlMut.mutate()} disabled={pnlMut.isPending}>
                {pnlMut.isPending ? 'Checking…' : 'Check P&L'}
              </Button>
            </div>
            {pnlMut.isError && <p className="mt-2 text-xs text-rose-400">{apiErrorMessage(pnlMut.error)}</p>}
            {pnl && !pnl.error && (
              <div className="mt-2">
                <p className="font-semibold text-white">P&L: {Number(pnl.pnl_pct_of_capital) >= 0 ? '+' : ''}{fmtNum(pnl.pnl_pct_of_capital, 2)}% of total capital</p>
                <p className="text-xs text-slate-400">{String(pnl.message ?? '')}</p>
              </div>
            )}
            {Boolean(pnl?.error) && <p className="mt-2 text-xs text-amber-400">{String(pnl?.error)}</p>}
          </div>
        </div>
      )}
    </div>
  )
}

export function HedgingPanel({
  data, totalCapital, profitTargetPctOfCapital, maxLossPctOfCapital,
}: {
  data: Row
  totalCapital: number
  profitTargetPctOfCapital: number
  maxLossPctOfCapital: number
}) {
  const results = (data.results as Row[]) ?? []
  const currency = String(data.currency ?? '')
  if (!results.length) return <p className="text-sm text-slate-500">No results yet.</p>

  return (
    <div className="space-y-2">
      {results.map((res, i) => (
        <HedgingResultCard
          key={i} result={res} index={i} currency={currency}
          totalCapital={totalCapital} profitTargetPctOfCapital={profitTargetPctOfCapital} maxLossPctOfCapital={maxLossPctOfCapital}
        />
      ))}
    </div>
  )
}

function GokulResultCard({ result, index, currency }: { result: Row; index: number; currency: string }) {
  const [open, setOpen] = useState(index === 0)
  const live = (result.live as Row) ?? {}
  const leg = (result.option_leg as Row) ?? null
  const plan = (result.trade_plan as Row) ?? null
  const reasons = (result.reasons as string[]) ?? (live.reasons as string[]) ?? []
  const verdict = String(live.verdict ?? result.verdict ?? 'WAIT')
  const trade = resolveTradeSuggestion(result)

  return (
    <div className="rounded-lg border border-slate-800/60 bg-slate-900/40">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full flex-wrap items-center gap-2 px-3 py-2.5 text-left"
      >
        <span className="text-sm font-semibold text-white">{String(result.ticker ?? '—')}</span>
        <OptionsSignalHeaderChips trade={trade} />
        <span className="text-xs text-slate-500">
          · {String(trade.action_label ?? '')} · align {String(result.alignment ?? live.phase ?? '—')}
        </span>
        {open ? <ChevronDown size={14} className="ml-auto text-slate-500" /> : <ChevronRight size={14} className="ml-auto text-slate-500" />}
      </button>
      {open && (
        <div className="space-y-2 border-t border-slate-800/60 px-3 py-3 text-sm text-slate-300">
          <OptionsTradeSignalBlock
            trade={trade}
            currency={currency}
            entryLabel="Entry"
            legend="BUY = buy Call · SELL = buy Put (bearish) · WAIT = no setup · SL/TP on option premium where available"
          />
          <p>
            Spot {currency}{fmtNum(result.last_close ?? live.entry_price)} · Verdict <strong className="text-white">{verdict}</strong>
          </p>
          {plan && (
            <p className="text-xs text-slate-400">
              Underlying entry {fmtNum(plan.entry)} · SuperTrend stop {fmtNum(plan.stop_loss)} · BE trail {fmtNum(plan.be_trail)} · Target {fmtNum(plan.take_profit)}
            </p>
          )}
          {leg && (
            <p className="text-xs text-emerald-300/90">
              Suggested: {String(leg.option_type)} {fmtNum(leg.strike, 0)} (exp {String(leg.expiry ?? '—')}) · premium {currency}{fmtNum(leg.premium)} · delta {fmtNum(leg.delta, 3)} · ITM {fmtNum(leg.itm_points, 0)} pts
              {leg.stop_price != null && <> · opt stop {fmtNum(leg.stop_price)} · target {fmtNum(leg.target_price)}</>}
            </p>
          )}
          {reasons.map((r) => (
            <p key={r} className="text-xs text-slate-500">· {r}</p>
          ))}
          {Boolean(result.error) && <p className="text-xs text-rose-400">{String(result.error)}</p>}
        </div>
      )}
    </div>
  )
}

export function GokulChhabraPanel({ data }: { data: Row }) {
  const results = (data.results as Row[]) ?? []
  const currency = String(data.currency ?? '₹')
  if (!results.length) return <p className="text-sm text-slate-500">No results yet.</p>

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-3 text-sm text-slate-400">
        {data.entry_count != null && (
          <span>Actionable: <strong className="text-white">{String(data.entry_count)}</strong></span>
        )}
        {data.strategy != null && <span>Strategy: <strong className="text-white">{String(data.strategy)}</strong></span>}
      </div>
      <div className="space-y-2">
        {results.map((res, i) => (
          <GokulResultCard key={String(res.ticker ?? i)} result={res} index={i} currency={currency} />
        ))}
      </div>
    </div>
  )
}

function ZeroToHeroResultCard({ result, index, currency }: { result: Row; index: number; currency: string }) {
  const [open, setOpen] = useState(index === 0)
  const live = (result.live as Row) ?? {}
  const plan = (live.trade_plan as Row) ?? null
  const reasons = (live.reasons as string[]) ?? []
  const verdict = String(live.verdict ?? 'WAIT')
  const take = Boolean(live.take_trade)
  const trade = resolveTradeSuggestion(result)

  return (
    <div className="rounded-lg border border-slate-800/60 bg-slate-900/40">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full flex-wrap items-center gap-2 px-3 py-2.5 text-left"
      >
        <span className="text-sm font-semibold text-white">{String(result.ticker ?? '—')}</span>
        <OptionsSignalHeaderChips trade={trade} />
        <span className="text-xs text-slate-500">
          · {String(trade.action_label ?? '')} · bias {String(live.phase ?? '—')}
        </span>
        {open ? <ChevronDown size={14} className="ml-auto text-slate-500" /> : <ChevronRight size={14} className="ml-auto text-slate-500" />}
      </button>
      {open && (
        <div className="space-y-2 border-t border-slate-800/60 px-3 py-3 text-sm text-slate-300">
          <OptionsTradeSignalBlock
            trade={trade}
            currency={currency}
            entryLabel="Entry"
            legend="BUY = buy Call · SELL = buy Put · WAIT = no setup · TP is the 1:1 partial-book level"
          />
          <p>
            Spot {currency}{fmtNum(result.last_close)} · Verdict <strong className="text-white">{verdict}</strong>
          </p>
          <p className="text-xs text-slate-400">
            Prev day high {fmtNum(live.prev_day_high)} · Prev day low {fmtNum(live.prev_day_low)}
          </p>
          {take && (
            <p className="text-xs text-emerald-300/90">
              Entry {fmtNum(live.entry_price)} · Stop {fmtNum(live.stop_price)} · Book ~55% at {fmtNum(live.target_price)}
            </p>
          )}
          {plan && (
            <p className="text-xs text-slate-400">{String(plan.exit_rule ?? '')}</p>
          )}
          {reasons.map((r) => (
            <p key={r} className="text-xs text-slate-500">· {r}</p>
          ))}
          {Boolean(result.error) && <p className="text-xs text-rose-400">{String(result.error)}</p>}
        </div>
      )}
    </div>
  )
}

export function ZeroToHeroPanel({ data }: { data: Row }) {
  const results = (data.results as Row[]) ?? []
  const currency = String(data.currency ?? '₹')
  if (!results.length) return <p className="text-sm text-slate-500">No results yet.</p>

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-3 text-sm text-slate-400">
        {data.entry_count != null && (
          <span>Actionable: <strong className="text-white">{String(data.entry_count)}</strong></span>
        )}
        {data.strategy != null && <span>Strategy: <strong className="text-white">{String(data.strategy)}</strong></span>}
      </div>
      <div className="space-y-2">
        {results.map((res, i) => (
          <ZeroToHeroResultCard key={String(res.ticker ?? i)} result={res} index={i} currency={currency} />
        ))}
      </div>
    </div>
  )
}

function marketViewBadgeClass(view: string): string {
  if (view.startsWith('HEALTHY')) return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
  if (view === 'BULLISH') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
  if (view === 'SHORT_COVERING') return 'border-amber-500/30 bg-amber-500/10 text-amber-400'
  if (view.startsWith('BEARISH') || view.startsWith('BULLISH')) return 'border-rose-500/30 bg-rose-500/10 text-rose-400'
  if (view.startsWith('CAUTIOUS')) return 'border-amber-500/30 bg-amber-500/10 text-amber-400'
  return 'border-slate-700/60 bg-slate-800/50 text-slate-300'
}

function riskStanceBadgeClass(stance: string): string {
  if (stance === 'HIGH') return 'border-rose-500/30 bg-rose-500/10 text-rose-400'
  if (stance === 'MODERATE') return 'border-amber-500/30 bg-amber-500/10 text-amber-400'
  return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
}

function OutlookLeg({ leg }: { leg: Row }) {
  const direction = String(leg.direction ?? 'NEUTRAL')
  const dirClass =
    direction === 'LONG' ? 'text-emerald-400' : direction === 'SHORT' ? 'text-rose-400' : 'text-slate-400'
  return (
    <div className="rounded-lg border border-slate-800/60 bg-slate-950/40 p-3">
      <p className="text-xs font-medium uppercase tracking-wider text-slate-500">{String(leg.horizon ?? '')}</p>
      <p className={`mt-1 text-sm font-semibold ${dirClass}`}>
        {String(leg.bias ?? direction)}
        {leg.strength_label != null && <span className="ml-1.5 text-xs font-normal text-slate-400">({String(leg.strength_label)} trend)</span>}
      </p>
      {leg.reversal_probability_pct != null && (
        <p className="mt-0.5 text-xs text-slate-500">Reversal risk: {fmtNum(leg.reversal_probability_pct, 0)}%</p>
      )}
      {leg.plain_english != null && (
        <p className="mt-1.5 text-xs leading-relaxed text-slate-400">{String(leg.plain_english)}</p>
      )}
    </div>
  )
}

export function MarketPredictionPanel({ data }: { data: Row }) {
  if (data.error) return <p className="text-sm text-rose-400">{String(data.error)}</p>

  const marketView = String(data.market_view ?? '—')
  const riskStance = String(data.risk_stance ?? '—')
  const warnings = (data.warnings as string[]) ?? []
  const confirmations = (data.confirmations as string[]) ?? []
  const vix = (data.vix as Row) ?? {}
  const lateJump = (data.late_session_jump as Row) ?? {}
  const manualBasis = data.manual_futures_basis as Row | null
  const asOfDate = data.as_of_date != null ? String(data.as_of_date) : null
  const predictionForDate = data.prediction_for_date != null ? String(data.prediction_for_date) : null
  const generatedAt = data.generated_at != null ? String(data.generated_at) : null
  const expiry = data.option_chain_expiry != null ? String(data.option_chain_expiry) : null
  const plainEnglish = data.plain_english != null ? String(data.plain_english) : null
  const chainSignal = (data.chain_signal as Row | null) ?? null
  const outlook = (data.outlook as Row | null) ?? null
  const trade = resolveTradeSuggestion(data)

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-slate-800/60 bg-slate-900/40 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className={`inline-flex items-center rounded-lg border px-3 py-1 text-sm font-semibold ${marketViewBadgeClass(marketView)}`}>
            {marketView}
          </span>
          <span className={`inline-flex items-center rounded-lg border px-2.5 py-1 text-xs font-medium ${riskStanceBadgeClass(riskStance)}`}>
            {riskStance} risk
          </span>
          <span className="text-xs text-slate-500">
            Composite score {fmtNum(data.composite_score, 1)} · {String(data.symbol ?? '')} {fmtNum(data.spot)}
            {data.price_chg_pct != null && <> ({fmtNum(data.price_chg_pct)}%)</>}
          </span>
        </div>
        {(asOfDate || expiry) && (
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
            {asOfDate && (
              <span>
                📅 Data used: <strong className="text-slate-300">{asOfDate}</strong> (last completed NSE session)
              </span>
            )}
            {predictionForDate && (
              <span>
                🔮 Outlook applies from: <strong className="text-slate-300">{predictionForDate}</strong> onward (approx next
                trading session — doesn't account for exchange holidays)
              </span>
            )}
            {expiry && <span>Option chain expiry: <strong className="text-slate-300">{expiry}</strong></span>}
            {generatedAt && <span>Generated {generatedAt}</span>}
          </div>
        )}
        {plainEnglish != null ? (
          <p className="mt-3 rounded-lg border border-slate-700/50 bg-slate-800/40 px-3 py-2.5 text-sm leading-relaxed text-slate-200">
            {plainEnglish}
          </p>
        ) : data.trading_guidance != null ? (
          <p className="mt-3 text-sm leading-relaxed text-slate-300">{String(data.trading_guidance)}</p>
        ) : null}
        {chainSignal && (
          <p className="mt-2 text-xs text-slate-500">
            Options-chain read: <strong className="text-slate-300">{String(chainSignal.bias ?? '—')}</strong>
            {chainSignal.confidence_pct != null && <> ({fmtNum(chainSignal.confidence_pct, 0)}% confidence)</>}
            {chainSignal.pcr_oi != null && <> · PCR(OI) {fmtNum(chainSignal.pcr_oi, 2)}</>}
            {chainSignal.max_pain != null && <> · Max Pain {fmtNum(chainSignal.max_pain, 0)}</>}
          </p>
        )}
      </div>

      {trade && trade.action != null && (
        <OptionsTradeSignalBlock
          trade={{
            ...trade,
            plain_english: trade.advice ?? trade.plain_english,
            confidence_reasons: (trade.reasons as string[] | undefined) ?? (trade.confidence_reasons as string[] | undefined) ?? [],
          }}
          legend="BUY / SELL / WAIT from market prediction · SL% / TP% on the index idea"
        />
      )}

      {outlook != null && Boolean(outlook.available) && (
        <div className="rounded-xl border border-slate-800/60 bg-slate-900/40 p-4">
          <p className="mb-2 text-xs font-medium uppercase tracking-wider text-slate-500">📈 Outlook — what could happen next</p>
          <div className="grid gap-3 sm:grid-cols-2">
            {(outlook.near_term as Row | null) && (
              <OutlookLeg leg={outlook.near_term as Row} />
            )}
            {(outlook.medium_term as Row | null) && (
              <OutlookLeg leg={outlook.medium_term as Row} />
            )}
          </div>
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-3">
          <p className="text-xs font-medium uppercase tracking-wider text-slate-500">India VIX</p>
          <p className="mt-1 text-lg font-semibold text-white">{vix.available ? fmtNum(vix.level) : '—'}</p>
          {Boolean(vix.available) && vix.change_pct != null && (
            <p className={`text-xs ${Number(vix.change_pct) >= 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
              {fmtNum(vix.change_pct)}% today
            </p>
          )}
        </div>
        <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-3">
          <p className="text-xs font-medium uppercase tracking-wider text-slate-500">Late-session move</p>
          <p className="mt-1 text-lg font-semibold text-white">{lateJump.available ? `${fmtNum(lateJump.last_move_pct)}%` : '—'}</p>
          {Boolean(lateJump.available) && (
            <p className={`text-xs ${lateJump.unusual ? 'text-amber-400' : 'text-slate-500'}`}>
              {lateJump.unusual ? 'Unusual' : 'Normal'} ({fmtNum(lateJump.zscore)}σ)
            </p>
          )}
        </div>
        <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-3">
          <p className="text-xs font-medium uppercase tracking-wider text-slate-500">
            {manualBasis ? 'Futures basis (your input)' : 'Synthetic futures (options-implied)'}
          </p>
          <p className="mt-1 text-lg font-semibold text-white">
            {manualBasis
              ? `${fmtNum(manualBasis.basis_pct)}%`
              : (data.premium as Row | undefined)?.available
                ? `${fmtNum((data.premium as Row).premium_pct)}%`
                : '—'}
          </p>
        </div>
      </div>

      {warnings.length > 0 && (
        <div>
          <p className="mb-1.5 text-xs font-medium uppercase tracking-wider text-rose-400">⚠ Divergence warnings</p>
          <div className="space-y-1.5">
            {warnings.map((w) => (
              <p key={w} className="rounded-lg border border-rose-500/20 bg-rose-500/5 px-3 py-2 text-xs leading-relaxed text-rose-200/90">
                {w}
              </p>
            ))}
          </div>
        </div>
      )}

      {confirmations.length > 0 && (
        <div>
          <p className="mb-1.5 text-xs font-medium uppercase tracking-wider text-emerald-400">✓ Confirming signals</p>
          <div className="space-y-1.5">
            {confirmations.map((c) => (
              <p key={c} className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-2 text-xs leading-relaxed text-emerald-200/90">
                {c}
              </p>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function OiStrikeTable({
  title,
  rows,
  strikeKey = 'strike',
  oiKey,
  chgKey,
  accent,
}: {
  title: string
  rows: Row[]
  strikeKey?: string
  oiKey: string
  chgKey: string
  accent: 'call' | 'put'
}) {
  if (!rows.length) return null
  const border = accent === 'call' ? 'border-rose-500/20' : 'border-emerald-500/20'
  const head = accent === 'call' ? 'text-rose-400' : 'text-emerald-400'
  return (
    <div className={`rounded-xl border ${border} bg-slate-900/40 p-3`}>
      <p className={`mb-2 text-xs font-medium uppercase tracking-wider ${head}`}>{title}</p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[280px] text-left text-xs text-slate-300">
          <thead>
            <tr className="border-b border-slate-800 text-slate-500">
              <th className="px-2 py-1.5 font-medium">Strike</th>
              <th className="px-2 py-1.5 font-medium">OI</th>
              <th className="px-2 py-1.5 font-medium">ΔOI</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={`${r[strikeKey]}-${i}`} className="border-b border-slate-800/60">
                <td className="px-2 py-1.5 font-medium text-white">{fmtNum(r[strikeKey], 0)}</td>
                <td className="px-2 py-1.5">{fmtNum(r[oiKey], 0)}</td>
                <td className={`px-2 py-1.5 ${Number(r[chgKey] ?? 0) >= 0 ? 'text-amber-300' : 'text-slate-400'}`}>
                  {fmtNum(r[chgKey], 0)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export function CallPutWritingPanel({ data }: { data: Row }) {
  if (data.error) return <p className="text-sm text-rose-400">{String(data.error)}</p>

  const marketView = String(data.market_view ?? '—')
  const riskStance = String(data.risk_stance ?? '—')
  const writing = (data.writing as Row) ?? {}
  const walls = (data.walls as Row) ?? {}
  const covering = (data.short_covering as Row) ?? {}
  const buildup = (data.buildup as Row | null) ?? null
  const sentiment = (data.sentiment as Row | null) ?? null
  const chainSignal = (data.chain_signal as Row | null) ?? null
  const fiiDii = (data.fii_dii_cash as Row | null) ?? null
  const trade = resolveTradeSuggestion(data)
  const callWall = (walls.primary_call_wall as Row) ?? {}
  const putFloor = (walls.primary_put_floor as Row) ?? {}
  const topCall = (data.top_call_oi as Row[]) ?? (walls.call_resistance_strikes as Row[]) ?? []
  const topPut = (data.top_put_oi as Row[]) ?? (walls.put_support_strikes as Row[]) ?? []
  const topCallChg = (data.top_call_chg_oi as Row[]) ?? []
  const topPutChg = (data.top_put_chg_oi as Row[]) ?? []
  const plainEnglish = data.plain_english != null ? String(data.plain_english) : null
  const expiry = data.expiry != null ? String(data.expiry) : null
  const generatedAt = data.generated_at != null ? String(data.generated_at) : null

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-slate-800/60 bg-slate-900/40 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className={`inline-flex items-center rounded-lg border px-3 py-1 text-sm font-semibold ${marketViewBadgeClass(marketView)}`}>
            {marketView}
          </span>
          <span className={`inline-flex items-center rounded-lg border px-2.5 py-1 text-xs font-medium ${riskStanceBadgeClass(riskStance)}`}>
            {riskStance} risk
          </span>
          {writing.tilt != null && (
            <span className="inline-flex items-center rounded-lg border border-slate-700/60 bg-slate-800/50 px-2.5 py-1 text-xs text-slate-300">
              {String(writing.tilt).replace(/_/g, ' ')}
            </span>
          )}
          <span className="text-xs text-slate-500">
            {String(data.symbol ?? '')} {fmtNum(data.spot)}
            {expiry && <> · Exp {expiry}</>}
          </span>
        </div>
        {(generatedAt || data.video_title) && (
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
            {data.video_title != null && <span>Framing: {String(data.video_title)}</span>}
            {generatedAt && <span>Generated {generatedAt}</span>}
          </div>
        )}
        {plainEnglish != null && (
          <p className="mt-3 rounded-lg border border-slate-700/50 bg-slate-800/40 px-3 py-2.5 text-sm leading-relaxed text-slate-200">
            {plainEnglish}
          </p>
        )}
        <div className="mt-3 grid gap-2 sm:grid-cols-4">
          <div className="rounded-lg border border-slate-800/60 bg-slate-950/40 px-3 py-2">
            <p className="text-[10px] uppercase tracking-wider text-slate-500">PCR (OI)</p>
            <p className="text-sm font-semibold text-white">{fmtNum(data.pcr_oi, 2)}</p>
          </div>
          <div className="rounded-lg border border-slate-800/60 bg-slate-950/40 px-3 py-2">
            <p className="text-[10px] uppercase tracking-wider text-slate-500">Max Pain</p>
            <p className="text-sm font-semibold text-white">{fmtNum(data.max_pain, 0)}</p>
          </div>
          <div className="rounded-lg border border-rose-500/20 bg-rose-500/5 px-3 py-2">
            <p className="text-[10px] uppercase tracking-wider text-rose-400">Call wall</p>
            <p className="text-sm font-semibold text-white">{fmtNum(callWall.strike, 0)}</p>
            {callWall.ce_oi != null && <p className="text-[10px] text-slate-500">OI {fmtNum(callWall.ce_oi, 0)}</p>}
          </div>
          <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-2">
            <p className="text-[10px] uppercase tracking-wider text-emerald-400">Put floor</p>
            <p className="text-sm font-semibold text-white">{fmtNum(putFloor.strike, 0)}</p>
            {putFloor.pe_oi != null && <p className="text-[10px] text-slate-500">OI {fmtNum(putFloor.pe_oi, 0)}</p>}
          </div>
        </div>
        {writing.note != null && (
          <p className="mt-2 text-xs text-slate-400">{String(writing.note)}</p>
        )}
        {covering.note != null && (
          <p className={`mt-1.5 text-xs ${covering.threatened || covering.active ? 'text-amber-300' : 'text-slate-500'}`}>
            {String(covering.note)}
          </p>
        )}
      </div>

      {trade && trade.action != null && (
        <OptionsTradeSignalBlock
          trade={{
            ...trade,
            plain_english: trade.advice ?? trade.plain_english,
            confidence_reasons: (trade.reasons as string[] | undefined) ?? (trade.confidence_reasons as string[] | undefined) ?? [],
          }}
          legend="BUY / SELL / WAIT from Call/Put writing walls · SL% / TP% on the index / stock idea"
        />
      )}

      <div className="grid gap-3 lg:grid-cols-2">
        <OiStrikeTable title="Call resistance walls (OI)" rows={topCall} oiKey="ce_oi" chgKey="ce_chg_oi" accent="call" />
        <OiStrikeTable title="Put support floors (OI)" rows={topPut} oiKey="pe_oi" chgKey="pe_chg_oi" accent="put" />
        <OiStrikeTable title="Fresh Call writing (ΔOI)" rows={topCallChg} oiKey="ce_oi" chgKey="ce_chg_oi" accent="call" />
        <OiStrikeTable title="Fresh Put writing (ΔOI)" rows={topPutChg} oiKey="pe_oi" chgKey="pe_chg_oi" accent="put" />
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        {buildup && (
          <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-3">
            <p className="text-xs font-medium uppercase tracking-wider text-slate-500">OI buildup</p>
            <p className="mt-1 text-sm font-semibold text-white">{String(buildup.label ?? '—')}</p>
            {buildup.bias != null && <p className="text-xs text-slate-500">{String(buildup.bias)}</p>}
          </div>
        )}
        {sentiment && (
          <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-3">
            <p className="text-xs font-medium uppercase tracking-wider text-slate-500">Options sentiment</p>
            <p className="mt-1 text-sm font-semibold text-white">{String(sentiment.verdict ?? '—')}</p>
            {sentiment.score != null && <p className="text-xs text-slate-500">Score {fmtNum(sentiment.score, 1)}</p>}
          </div>
        )}
        {chainSignal && (
          <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-3">
            <p className="text-xs font-medium uppercase tracking-wider text-slate-500">Chain signal</p>
            <p className="mt-1 text-sm font-semibold text-white">{String(chainSignal.bias ?? '—')}</p>
            {chainSignal.confidence_pct != null && (
              <p className="text-xs text-slate-500">{fmtNum(chainSignal.confidence_pct, 0)}% conf</p>
            )}
          </div>
        )}
      </div>

      {fiiDii && (
        <p className="text-xs text-slate-500">
          Cash FII/DII:{' '}
          {Boolean(fiiDii.available)
            ? `${String(fiiDii.verdict ?? fiiDii.bias ?? '—')}${fiiDii.note != null ? ` — ${String(fiiDii.note)}` : ''}`
            : String(fiiDii.note ?? 'unavailable')}
        </p>
      )}
      {data.participant_oi_note != null && (
        <p className="rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-xs leading-relaxed text-amber-200/90">
          {String(data.participant_oi_note)}
        </p>
      )}
      {data.disclaimer != null && (
        <p className="text-[11px] text-slate-600">{String(data.disclaimer)}</p>
      )}
    </div>
  )
}
