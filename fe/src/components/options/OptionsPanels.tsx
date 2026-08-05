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
        className="flex w-full items-center gap-2 px-3 py-2.5 text-left text-sm text-slate-300 hover:bg-slate-800/30"
      >
        {open ? <ChevronDown size={14} className="shrink-0 text-slate-500" /> : <ChevronRight size={14} className="shrink-0 text-slate-500" />}
        <span className="font-semibold text-white">{ticker}</span>
        <span className="text-slate-500">
          · LTP {ltpStr(ltp, currency)} · {isDiagonal ? 'Double Diagonal' : 'Double Calendar'} · {entryOk ? '✅ Favorable' : '❌ Unfavorable'} IV/vol ·
          {' '}Net debit {currency}{fmtNum(netDebit, 4)}
        </span>
      </button>
      {open && (
        <div className="space-y-3 border-t border-slate-800/60 px-3 py-3 text-sm">
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
        className="flex w-full items-center gap-2 px-3 py-2.5 text-left text-sm text-slate-300 hover:bg-slate-800/30"
      >
        {open ? <ChevronDown size={14} className="shrink-0 text-slate-500" /> : <ChevronRight size={14} className="shrink-0 text-slate-500" />}
        <span className="font-semibold text-white">{ticker}</span>
        <span className="text-slate-500">
          · LTP {ltpStr(ltp, currency)} · {String(result.structure ?? '—')} · {entryOk ? '✅ Favorable' : '❌ Unfavorable'} ·
          {' '}Net credit {currency}{fmtNum(netCredit, 4)} · POP ~{fmtNum(result.pop_pct, 0)}%
        </span>
      </button>
      {open && (
        <div className="space-y-3 border-t border-slate-800/60 px-3 py-3 text-sm">
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
        className="flex w-full items-center gap-2 px-3 py-2.5 text-left text-sm text-slate-300 hover:bg-slate-800/30"
      >
        {open ? <ChevronDown size={14} className="shrink-0 text-slate-500" /> : <ChevronRight size={14} className="shrink-0 text-slate-500" />}
        <span className="font-semibold text-white">{ticker}</span>
        <span className="text-slate-500">
          · LTP {ltpStr(ltp, currency)} · {ADJUSTMENT_BADGE[adjStatus] ?? adjStatus} ·{' '}
          Net credit {currency}{fmtNum(netCredit, 4)}
        </span>
      </button>
      {open && (
        <div className="space-y-3 border-t border-slate-800/60 px-3 py-3 text-sm">
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
  const take = Boolean(live.take_trade)
  const badge = take
    ? (String(live.direction) === 'SHORT' ? '🔴 BUY PUT' : '🟢 BUY CALL')
    : '⚪ WAIT'

  return (
    <div className="rounded-lg border border-slate-800/60 bg-slate-900/40">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-2 px-3 py-2.5 text-left"
      >
        <span className="text-sm font-medium text-white">
          {String(result.ticker ?? '—')} · {badge} · align {String(result.alignment ?? live.phase ?? '—')} · conf {fmtNum(live.confidence_pct, 0)}%
        </span>
        {open ? <ChevronDown size={14} className="text-slate-500" /> : <ChevronRight size={14} className="text-slate-500" />}
      </button>
      {open && (
        <div className="space-y-2 border-t border-slate-800/60 px-3 py-3 text-sm text-slate-300">
          <p>
            Spot {currency}{fmtNum(result.last_close ?? live.entry_price)} · Verdict <strong className="text-white">{verdict}</strong>
            {live.sl_pct != null && <> · SL -{fmtNum(live.sl_pct)}%</>}
            {live.tp_pct != null && <> · TP +{fmtNum(live.tp_pct)}%</>}
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
  const badge = take
    ? (String(live.direction) === 'SHORT' ? '🔴 BUY PUT' : '🟢 BUY CALL')
    : '⚪ WAIT'

  return (
    <div className="rounded-lg border border-slate-800/60 bg-slate-900/40">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-2 px-3 py-2.5 text-left"
      >
        <span className="text-sm font-medium text-white">
          {String(result.ticker ?? '—')} · {badge} · bias {String(live.phase ?? '—')} · conf {fmtNum(live.confidence_pct, 0)}%
        </span>
        {open ? <ChevronDown size={14} className="text-slate-500" /> : <ChevronRight size={14} className="text-slate-500" />}
      </button>
      {open && (
        <div className="space-y-2 border-t border-slate-800/60 px-3 py-3 text-sm text-slate-300">
          <p>
            Spot {currency}{fmtNum(result.last_close)} · Verdict <strong className="text-white">{verdict}</strong>
            {live.sl_pct != null && <> · SL -{fmtNum(live.sl_pct)}%</>}
            {live.tp_pct != null && <> · 1:1 book +{fmtNum(live.tp_pct)}%</>}
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
  if (view.startsWith('BEARISH') || view.startsWith('BULLISH')) return 'border-rose-500/30 bg-rose-500/10 text-rose-400'
  if (view.startsWith('CAUTIOUS')) return 'border-amber-500/30 bg-amber-500/10 text-amber-400'
  return 'border-slate-700/60 bg-slate-800/50 text-slate-300'
}

function riskStanceBadgeClass(stance: string): string {
  if (stance === 'HIGH') return 'border-rose-500/30 bg-rose-500/10 text-rose-400'
  if (stance === 'MODERATE') return 'border-amber-500/30 bg-amber-500/10 text-amber-400'
  return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
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
  const generatedAt = data.generated_at != null ? String(data.generated_at) : null
  const expiry = data.option_chain_expiry != null ? String(data.option_chain_expiry) : null
  const plainEnglish = data.plain_english != null ? String(data.plain_english) : null
  const chainSignal = (data.chain_signal as Row | null) ?? null

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
          <p className="mt-2 text-xs text-slate-500">
            {asOfDate && <>Showing results for <strong className="text-slate-300">{asOfDate}</strong> (last completed trading session)</>}
            {expiry && <> · Option chain expiry: <strong className="text-slate-300">{expiry}</strong></>}
            {generatedAt && <> · Generated {generatedAt}</>}
          </p>
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
