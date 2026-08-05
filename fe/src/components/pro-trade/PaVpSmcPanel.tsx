import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { Badge } from '../ui/Badge'
import { Card } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { AddToWatchlistButton } from '../watchlist/AddToWatchlistButton'
import type { WatchlistMarket } from '../watchlist/WatchlistMarketContext'
import { VolumeProfileChart, type VpChartBar, type VpHistBin, type VpLevel } from './VolumeProfileChart'

type Row = Record<string, unknown>

function signalTone(verdict: string): string {
  const v = verdict.toUpperCase()
  if (v.includes('LONG')) return 'BUY'
  if (v.includes('SHORT')) return 'SELL'
  return 'HOLD'
}

function ConfluenceMeter({ matches, minRequired }: { matches: number; minRequired: number }) {
  const total = Math.max(matches, minRequired, 5)
  const dots = Array.from({ length: total }, (_, i) => i < matches)
  return (
    <div className="flex items-center gap-1">
      {dots.map((filled, i) => (
        <span
          key={i}
          className={`h-2 w-2 rounded-full ${filled ? (matches >= minRequired ? 'bg-emerald-400' : 'bg-amber-400') : 'bg-slate-700'}`}
        />
      ))}
      <span className="ml-1 text-[11px] text-slate-500">
        {matches}/{minRequired} pillars
      </span>
    </div>
  )
}

function TickerResultCard({
  result,
  index,
  currency,
  assetClass,
  showCharts,
}: {
  result: Row
  index: number
  currency: string
  assetClass: WatchlistMarket
  showCharts: boolean
}) {
  const [open, setOpen] = useState(index === 0 || Boolean(result.take_trade))
  const take = Boolean(result.take_trade)
  const verdict = String(result.verdict ?? 'WAIT')
  const confluence = (result.confluence as Row) || {}
  const trend = (result.trend as Row) || {}
  const pd = (result.premium_discount as Row) || {}
  const vp = (result.volume_profile as Row | null) || null
  const sweep = (result.liquidity_sweep as Row) || null
  const fvg = (result.fvg as Row) || null
  const orderBlocks = (result.order_blocks as Row[]) ?? []
  const candlePatterns = (result.candlestick_patterns as Row[]) ?? []
  const reasons = (result.reasons as string[]) ?? []
  const execution = (result.execution as Row) || null
  const rules = (result.rules as string[]) ?? []

  const chartData = useMemo(
    () => ((result.chart_data as VpChartBar[]) ?? []).filter((b) => b && b.time != null),
    [result.chart_data],
  )
  const histogram = useMemo(
    () => ((result.vp_histogram as VpHistBin[]) ?? []).filter((b) => b && b.price != null),
    [result.vp_histogram],
  )
  const levels = useMemo<VpLevel[]>(() => {
    const out: VpLevel[] = []
    if (vp?.val != null) out.push({ label: 'VAL', price: Number(vp.val), color: '#34d399' })
    if (vp?.poc != null) out.push({ label: 'POC', price: Number(vp.poc), color: '#fbbf24' })
    if (vp?.vah != null) out.push({ label: 'VAH', price: Number(vp.vah), color: '#f87171' })
    const supportZone = result.support_zone as [number, number] | null | undefined
    const resistanceZone = result.resistance_zone as [number, number] | null | undefined
    if (supportZone) out.push({ label: 'Support', price: Number(supportZone[1]), color: '#22c55e' })
    if (resistanceZone) out.push({ label: 'Resistance', price: Number(resistanceZone[0]), color: '#ef4444' })
    return out
  }, [vp, result.support_zone, result.resistance_zone])

  return (
    <div className="rounded-xl border border-slate-800/80 bg-slate-900/50">
      <div className="flex w-full flex-wrap items-center gap-3 px-4 py-3">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="flex flex-1 flex-wrap items-center gap-3 text-left"
        >
          {open ? <ChevronDown size={16} className="text-slate-500" /> : <ChevronRight size={16} className="text-slate-500" />}
          <span className="font-semibold text-white">{String(result.ticker)}</span>
          {result.ltp != null && (
            <span className="text-sm text-slate-400">
              {currency}
              {String(result.ltp)}
            </span>
          )}
          <Badge action={signalTone(verdict)} />
          <span className="text-xs text-slate-500">{verdict}</span>
          {confluence.confidence_pct != null && (
            <span className="text-xs font-medium text-slate-300">{String(confluence.confidence_pct)}% confidence</span>
          )}
          <ConfluenceMeter matches={Number(confluence.matches ?? 0)} minRequired={Number(confluence.min_required ?? 3)} />
          {result.error ? <span className="text-xs text-amber-400">{String(result.error)}</span> : null}
        </button>
        <AddToWatchlistButton ticker={String(result.ticker ?? '')} marketType={assetClass} compact />
      </div>
      {open && !result.error && (
        <div className="space-y-3 border-t border-slate-800/70 px-4 py-3">
          <div className="flex flex-wrap gap-3 text-xs text-slate-400">
            <span>
              Trend: <strong className="text-slate-200">{String(trend.trend ?? '—')}</strong>
            </span>
            <span>
              Zone: <strong className="text-slate-200">{String(pd.zone ?? '—')}</strong>
              {pd.pct != null && ` (${(Number(pd.pct) * 100).toFixed(0)}%)`}
            </span>
            {vp && (
              <span>
                VP ({String(vp.tf)}): VAL <strong className="text-emerald-300">{String(vp.val)}</strong> · POC{' '}
                <strong className="text-amber-300">{String(vp.poc)}</strong> · VAH{' '}
                <strong className="text-rose-300">{String(vp.vah)}</strong>
              </span>
            )}
          </div>

          {showCharts && chartData.length > 0 && (
            <div className="rounded-lg border border-slate-800/60 bg-slate-950/40 p-3">
              <VolumeProfileChart chartData={chartData} levels={levels} histogram={histogram} />
            </div>
          )}

          {take && (
            <div className="rounded-lg border border-slate-800/60 bg-slate-950/40 p-3">
              <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                <div>
                  <p className="text-xs text-slate-500">Entry</p>
                  <p className="font-medium text-white">
                    {currency}
                    {String(result.entry_price)}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">Stop-loss</p>
                  <p className="font-medium text-rose-400">
                    -{String(result.sl_pct)}% ({currency}
                    {String(result.stop_price)})
                  </p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">Target</p>
                  <p className="font-medium text-emerald-400">
                    +{String(result.tp_pct)}% ({currency}
                    {String(result.target_price)})
                  </p>
                </div>
                <div>
                  <p className="text-xs text-slate-500">Hold</p>
                  <p className="font-medium text-white">{String(result.hold_duration ?? '—')}</p>
                </div>
              </div>
            </div>
          )}

          <div className="space-y-1">
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Confluence reasons</p>
            {reasons.map((r, i) => (
              <p key={i} className="text-xs text-slate-400">
                · {r}
              </p>
            ))}
          </div>

          <div className="grid gap-2 text-xs text-slate-500 sm:grid-cols-2">
            {orderBlocks.length > 0 && (
              <p>
                Order blocks: {orderBlocks.length} unmitigated (
                {orderBlocks
                  .slice(0, 3)
                  .map((ob) => `${String(ob.type)} ${Number(ob.bottom).toFixed(2)}-${Number(ob.top).toFixed(2)}`)
                  .join(', ')}
                )
              </p>
            )}
            {sweep && <p>Liquidity sweep: {String(sweep.note)}</p>}
            {fvg && (
              <p>
                Fair Value Gap: {String(fvg.type)} ({Number(fvg.bottom).toFixed(2)}-{Number(fvg.top).toFixed(2)})
              </p>
            )}
            {candlePatterns.length > 0 && (
              <p>
                Candlestick: {candlePatterns.map((p) => `${String(p.name)} (${String(p.direction)})`).join(', ')}
              </p>
            )}
          </div>

          {execution && (
            <Card className="!bg-slate-950/50">
              <p className="text-xs font-medium text-emerald-300/90">Execution / options hint</p>
              {Boolean(execution.structure) && <p className="mt-1 text-sm text-slate-200">{String(execution.structure)}</p>}
              {Boolean(execution.leg_1) && <p className="mt-1 text-xs text-slate-400">{String(execution.leg_1)}</p>}
              {Boolean(execution.leg_2) && <p className="text-xs text-slate-400">{String(execution.leg_2)}</p>}
              {Boolean(execution.note) && <p className="mt-2 text-xs text-slate-500">{String(execution.note)}</p>}
              {Boolean(execution.itm_note) && <p className="mt-1 text-xs text-slate-500">{String(execution.itm_note)}</p>}
            </Card>
          )}

          {rules.length > 0 && (
            <ul className="list-disc space-y-1 pl-4 text-xs text-slate-500">
              {rules.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}

function confidenceOf(result: Row): number {
  const confluence = (result.confluence as Row) || {}
  const v = confluence.confidence_pct
  return v == null ? -1 : Number(v)
}

export function PaVpSmcPanel({ data, showCharts = false }: { data: Row; showCharts?: boolean }) {
  const results = (data.results as Row[]) ?? []
  const currency = String(data.currency ?? '₹')
  const assetClass = (String(data.asset_class ?? 'india') as WatchlistMarket)
  const [actionableOnly, setActionableOnly] = useState(false)

  const sorted = useMemo(() => {
    const filtered = actionableOnly ? results.filter((r) => Boolean(r.take_trade)) : results
    return [...filtered].sort((a, b) => confidenceOf(b) - confidenceOf(a))
  }, [results, actionableOnly])

  if (!results.length) return <p className="text-sm text-slate-500">No results yet.</p>

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 text-sm text-slate-400">
        {data.entry_count != null && (
          <span>
            Actionable: <strong className="text-white">{String(data.entry_count)}</strong>
          </span>
        )}
        {data.scanned != null && (
          <span>
            Scanned: <strong className="text-white">{String(data.scanned)}</strong>
          </span>
        )}
        <div className="ml-auto flex gap-2">
          <Chip selected={!actionableOnly} onClick={() => setActionableOnly(false)}>
            All
          </Chip>
          <Chip selected={actionableOnly} onClick={() => setActionableOnly(true)}>
            Actionable only
          </Chip>
        </div>
      </div>
      <div className="space-y-2">
        {sorted.length === 0 ? (
          <p className="text-sm text-slate-500">No actionable setups right now.</p>
        ) : (
          sorted.map((res, i) => (
            <TickerResultCard key={String(res.ticker ?? i)} result={res} index={i} currency={currency} assetClass={assetClass} showCharts={showCharts} />
          ))
        )}
      </div>
      {Boolean(data.disclaimer) && <p className="text-xs text-slate-600">{String(data.disclaimer)}</p>}
    </div>
  )
}
