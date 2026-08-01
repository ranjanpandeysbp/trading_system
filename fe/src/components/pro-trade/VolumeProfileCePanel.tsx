import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { Badge } from '../ui/Badge'
import { Card } from '../ui/Card'
import { AddToWatchlistButton } from '../watchlist/AddToWatchlistButton'
import type { WatchlistMarket } from '../watchlist/WatchlistMarketContext'
import { VolumeProfileChart, type VpChartBar, type VpHistBin, type VpLevel } from './VolumeProfileChart'

type Row = Record<string, unknown>

function signalTone(signal: string): string {
  const s = signal.toUpperCase()
  if (s.includes('BUY') || s.includes('LONG') || s === 'BREAKOUT_BUY' || s === 'FAST_LONG') return 'BUY'
  if (s.includes('SELL') || s.includes('SHORT') || s === 'BREAKDOWN_SELL' || s === 'FAST_SHORT') return 'SELL'
  return 'HOLD'
}

function SetupCard({ setup }: { setup: Row }) {
  const signal = String(setup.signal ?? 'WAIT')
  const levels = (setup.levels as Row) || {}
  const reasons = (setup.reasons as string[]) ?? []
  return (
    <div className="rounded-lg border border-slate-800/70 bg-slate-950/40 p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-slate-200">{String(setup.setup ?? 'setup')}</span>
        <Badge action={signalTone(signal)} />
        <span className="text-xs text-slate-500">{signal}</span>
        {setup.direction ? (
          <span className="text-xs text-slate-400">{String(setup.direction)}</span>
        ) : null}
        {setup.confidence_pct != null && (
          <span className="text-xs font-medium text-emerald-300">{String(setup.confidence_pct)}% confidence</span>
        )}
      </div>
      <p className="text-xs leading-relaxed text-slate-400">{String(setup.logic ?? '')}</p>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
        {setup.entry != null && <span>Entry: {String(setup.entry)}</span>}
        {setup.stop_loss != null && <span>SL: {String(setup.stop_loss)}</span>}
        {setup.target_1 != null && <span>T1: {String(setup.target_1)}</span>}
        {setup.target_2 != null && <span>T2: {String(setup.target_2)}</span>}
        {levels.val != null && <span>VAL: {String(levels.val)}</span>}
        {levels.poc != null && <span>POC: {String(levels.poc)}</span>}
        {levels.vah != null && <span>VAH: {String(levels.vah)}</span>}
        {setup.merged_poc_low != null && (
          <span>
            Merged POC: {String(setup.merged_poc_low)}–{String(setup.merged_poc_high)}
          </span>
        )}
        {setup.poc_span_pct != null && <span>POC span: {String(setup.poc_span_pct)}%</span>}
      </div>
      {(setup.sl_pct != null || setup.tp_pct != null || setup.hold_duration != null) && (
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 border-t border-slate-800/60 pt-2 text-xs">
          {setup.sl_pct != null && <span className="text-rose-400">SL: -{String(setup.sl_pct)}%</span>}
          {setup.tp_pct != null && <span className="text-emerald-400">TP: +{String(setup.tp_pct)}%</span>}
          {setup.tp2_pct != null && <span className="text-emerald-300/80">TP2: +{String(setup.tp2_pct)}%</span>}
          {setup.hold_duration != null && <span className="text-slate-400">Hold: {String(setup.hold_duration)}</span>}
        </div>
      )}
      {reasons.length > 0 && (
        <div className="mt-2 space-y-0.5">
          {reasons.map((r, i) => (
            <p key={i} className="text-[11px] text-slate-500">
              · {r}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}

function vpLevelsFromSession(vp: Row): VpLevel[] {
  const levels: VpLevel[] = []
  if (vp.val != null) levels.push({ label: 'VAL', price: Number(vp.val), color: '#34d399' })
  if (vp.poc != null) levels.push({ label: 'POC', price: Number(vp.poc), color: '#fbbf24' })
  if (vp.vah != null) levels.push({ label: 'VAH', price: Number(vp.vah), color: '#f87171' })
  return levels
}

function TickerResultCard({
  result,
  index,
  currency,
  assetClass,
}: {
  result: Row
  index: number
  currency: string
  assetClass: WatchlistMarket
}) {
  const [open, setOpen] = useState(index === 0 || Boolean(result.take_trade))
  const setups = (result.setups as Row[]) ?? []
  const vp = (result.session_vp as Row) || {}
  const execution = (result.execution as Row) || null
  const rules = (result.rules as string[]) ?? []
  const take = Boolean(result.take_trade)
  const chartData = useMemo(
    () => ((result.chart_data as VpChartBar[]) ?? []).filter((b) => b && b.time != null),
    [result.chart_data],
  )
  const histogram = useMemo(
    () => ((result.vp_histogram as VpHistBin[]) ?? []).filter((b) => b && b.price != null),
    [result.vp_histogram],
  )
  const levels = useMemo(() => vpLevelsFromSession(vp), [vp])

  return (
    <div className="rounded-xl border border-slate-800/80 bg-slate-900/50">
      <div className="flex w-full items-center gap-3 px-4 py-3">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="flex flex-1 items-center gap-3 text-left"
        >
          {open ? <ChevronDown size={16} className="text-slate-500" /> : <ChevronRight size={16} className="text-slate-500" />}
          <span className="font-semibold text-white">{String(result.ticker)}</span>
          {result.ltp != null && (
            <span className="text-sm text-slate-400">
              {currency}
              {String(result.ltp)}
            </span>
          )}
          <Badge action={take ? signalTone(String(result.direction ?? '')) : 'HOLD'} />
          <span className="text-xs text-slate-500">{String(result.verdict ?? (take ? 'TAKE' : 'WAIT'))}</span>
          {result.error ? <span className="text-xs text-amber-400">{String(result.error)}</span> : null}
        </button>
        <AddToWatchlistButton ticker={String(result.ticker ?? '')} marketType={assetClass} compact />
      </div>
      {open && (
        <div className="space-y-3 border-t border-slate-800/70 px-4 py-3">
          {vp.poc != null && (
            <div className="flex flex-wrap gap-3 text-xs text-slate-400">
              <span>
                Session VP ({String(vp.tf)} · {String(vp.bars)} bars
                {vp.session_date ? ` · ${String(vp.session_date)}` : ''})
              </span>
              <span>
                VAL <strong className="text-slate-200">{String(vp.val)}</strong>
              </span>
              <span>
                POC <strong className="text-slate-200">{String(vp.poc)}</strong>
              </span>
              <span>
                VAH <strong className="text-slate-200">{String(vp.vah)}</strong>
              </span>
            </div>
          )}

          {chartData.length > 0 && (
            <div className="rounded-lg border border-slate-800/60 bg-slate-950/40 p-3">
              <VolumeProfileChart chartData={chartData} levels={levels} histogram={histogram} />
            </div>
          )}

          <div className="space-y-2">
            {setups.map((s, i) => (
              <SetupCard key={`${String(s.setup)}-${i}`} setup={s} />
            ))}
          </div>
          {execution && (
            <Card className="!bg-slate-950/50">
              <p className="text-xs font-medium text-emerald-300/90">Execution / hedging hint</p>
              {Boolean(execution.structure) && (
                <p className="mt-1 text-sm text-slate-200">{String(execution.structure)}</p>
              )}
              {Boolean(execution.leg_1) && <p className="mt-1 text-xs text-slate-400">{String(execution.leg_1)}</p>}
              {Boolean(execution.leg_2) && <p className="text-xs text-slate-400">{String(execution.leg_2)}</p>}
              {Boolean(execution.note) && <p className="mt-2 text-xs text-slate-500">{String(execution.note)}</p>}
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

export function VolumeProfileCePanel({ data }: { data: Row }) {
  const results = (data.results as Row[]) ?? []
  const currency = String(data.currency ?? '₹')
  const assetClass = (String(data.asset_class ?? 'india') as WatchlistMarket)
  if (!results.length) return <p className="text-sm text-slate-500">No results yet.</p>

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-3 text-sm text-slate-400">
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
        {data.youtube != null && (
          <a
            href={String(data.youtube)}
            target="_blank"
            rel="noreferrer"
            className="text-blue-400 hover:underline"
          >
            Source video
          </a>
        )}
      </div>
      <div className="space-y-2">
        {results.map((res, i) => (
          <TickerResultCard key={String(res.ticker ?? i)} result={res} index={i} currency={currency} assetClass={assetClass} />
        ))}
      </div>
      {Boolean(data.disclaimer) && <p className="text-xs text-slate-600">{String(data.disclaimer)}</p>}
    </div>
  )
}
