import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { Badge } from '../ui/Badge'
import { AddToWatchlistButton } from '../watchlist/AddToWatchlistButton'
import type { WatchlistMarket } from '../watchlist/WatchlistMarketContext'
import {
  SupportResistanceChart,
  type SRChartBar,
  type SRFibonacci,
  type SRLevel,
} from '../trading-hubs/SupportResistanceChart'
import { AskAIPanel } from '../ai/AskAIPanel'

type Row = Record<string, unknown>

function SignalBadge({ signal }: { signal: string }) {
  const s = signal.toUpperCase()
  const cls =
    s === 'BULLISH'
      ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
      : s === 'BEARISH'
        ? 'border-rose-500/40 bg-rose-500/10 text-rose-300'
        : 'border-slate-700/60 bg-slate-800/40 text-slate-400'
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-semibold ${cls}`}>
      {s}
    </span>
  )
}

function signalTone(direction: string): string {
  const d = direction.toUpperCase()
  if (d === 'LONG') return 'BUY'
  if (d === 'SHORT') return 'SELL'
  return 'HOLD'
}

function fmtNum(v: unknown, digits = 2) {
  const n = Number(v)
  return Number.isFinite(n) ? n.toLocaleString('en-IN', { maximumFractionDigits: digits }) : '—'
}

function SetupCard({ setup, currency }: { setup: Row; currency: string }) {
  return (
    <div className="rounded-lg border border-slate-800/70 bg-slate-950/40 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold text-white">{String(setup.strategy_label ?? setup.strategy_id)}</span>
        <SignalBadge signal={String(setup.signal ?? 'NEUTRAL')} />
        <Badge action={signalTone(String(setup.direction ?? ''))} />
        {setup.confidence_pct != null && (
          <span className="text-xs font-medium text-teal-300">{fmtNum(setup.confidence_pct, 0)}% confidence</span>
        )}
        {setup.style != null && <span className="text-xs text-slate-500">{String(setup.style)}</span>}
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
        <div>
          <p className="text-slate-500">Entry</p>
          <p className="font-medium text-slate-100">{currency}{fmtNum(setup.entry_price, 4)}</p>
        </div>
        <div>
          <p className="text-slate-500">Stop (SL%)</p>
          <p className="font-medium text-rose-300">
            {currency}{fmtNum(setup.stop_price, 4)}
            {setup.sl_pct != null ? ` · ${fmtNum(setup.sl_pct, 1)}%` : ''}
          </p>
        </div>
        <div>
          <p className="text-slate-500">Target (TP%)</p>
          <p className="font-medium text-emerald-300">
            {currency}{fmtNum(setup.target_price, 4)}
            {setup.tp_pct != null ? ` · ${fmtNum(setup.tp_pct, 1)}%` : ''}
          </p>
        </div>
        <div>
          <p className="text-slate-500">Reward : Risk</p>
          <p className="font-medium text-slate-100">{setup.rr != null ? `1 : ${fmtNum(setup.rr, 2)}` : '—'}</p>
        </div>
      </div>
      {setup.when_to_use != null && (
        <p className="mt-2 text-xs leading-relaxed text-slate-400">
          <span className="font-medium text-slate-300">When to use: </span>
          {String(setup.when_to_use)}
        </p>
      )}
      {Array.isArray(setup.confidence_reasons) && (setup.confidence_reasons as string[]).length > 0 && (
        <ul className="mt-2 space-y-0.5 border-t border-slate-800/60 pt-2">
          {(setup.confidence_reasons as string[]).slice(0, 6).map((r) => (
            <li key={r} className="text-xs text-slate-500">· {r}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

function TickerResultCard({
  result,
  index,
  currency,
  assetClass,
  showCharts,
  aiSystemPrompt,
}: {
  result: Row
  index: number
  currency: string
  assetClass: WatchlistMarket
  showCharts: boolean
  aiSystemPrompt: string
}) {
  const [open, setOpen] = useState(index === 0 || Boolean(result.take_trade))
  const take = Boolean(result.take_trade)
  const setups = (result.setups as Row[]) ?? []
  const fib = result.fibonacci as SRFibonacci | null | undefined

  const chartData = useMemo(
    () => ((result.chart_data as SRChartBar[]) ?? []).filter((b) => b && b.time != null),
    [result.chart_data],
  )

  const levels = useMemo<SRLevel[]>(() => {
    const out: SRLevel[] = []
    if (take) {
      if (result.entry_price != null) out.push({ label: 'Entry', price: Number(result.entry_price), color: '#38bdf8' })
      if (result.stop_price != null) out.push({ label: 'SL', price: Number(result.stop_price), color: '#f87171' })
      if (result.target_price != null) out.push({ label: 'TP', price: Number(result.target_price), color: '#34d399' })
    }
    const gz = result.golden_zone as Row | undefined
    if (gz?.lower != null && gz?.upper != null) {
      out.push({ label: 'GZ lo', price: Number(gz.lower), color: '#a78bfa' })
      out.push({ label: 'GZ hi', price: Number(gz.upper), color: '#a78bfa' })
    }
    return out
  }, [take, result.entry_price, result.stop_price, result.target_price, result.golden_zone])

  return (
    <div className="rounded-xl border border-slate-800/80 bg-slate-900/50">
      <div className="flex w-full flex-wrap items-center gap-3 px-4 py-3">
        <button type="button" onClick={() => setOpen((o) => !o)} className="flex flex-1 flex-wrap items-center gap-3 text-left">
          {open ? <ChevronDown size={16} className="text-slate-500" /> : <ChevronRight size={16} className="text-slate-500" />}
          <span className="font-semibold text-white">{String(result.ticker)}</span>
          {result.ltp != null && (
            <span className="text-sm text-slate-400">
              {currency}
              {fmtNum(result.ltp, 4)}
            </span>
          )}
          <SignalBadge signal={String(result.signal ?? 'NEUTRAL')} />
          {take && <Badge action={signalTone(String(result.direction ?? ''))} />}
          {result.confidence_pct != null && (
            <span className="text-xs font-medium text-slate-300">{fmtNum(result.confidence_pct, 0)}% confidence</span>
          )}
          {result.best_strategy_label != null && (
            <span className="text-xs text-violet-300">{String(result.best_strategy_label)}</span>
          )}
          {result.sl_pct != null && result.tp_pct != null && (
            <span className="text-xs text-slate-500">
              SL {fmtNum(result.sl_pct, 1)}% · TP {fmtNum(result.tp_pct, 1)}%
            </span>
          )}
          {result.error ? <span className="text-xs text-amber-400">{String(result.error)}</span> : null}
        </button>
        <AddToWatchlistButton ticker={String(result.ticker)} market={assetClass} />
      </div>

      {open && (
        <div className="space-y-3 border-t border-slate-800/60 px-4 py-3">
          {result.plain_english != null && (
            <p className="text-sm leading-relaxed text-slate-300">{String(result.plain_english)}</p>
          )}
          {result.when_to_use != null && take && (
            <p className="rounded-lg border border-violet-500/20 bg-violet-500/5 px-3 py-2 text-xs leading-relaxed text-violet-200/90">
              <span className="font-medium">When to use this setup: </span>
              {String(result.when_to_use)}
            </p>
          )}

          {setups.length > 0 ? (
            <div className="space-y-2">
              <p className="text-xs font-medium uppercase tracking-wider text-slate-500">
                Active Fib setups ({setups.length})
              </p>
              {setups.map((s, i) => (
                <SetupCard key={`${String(s.strategy_id)}-${i}`} setup={s} currency={currency} />
              ))}
            </div>
          ) : (
            !result.error && (
              <p className="text-sm text-slate-500">No Fib strategy currently in an entry zone for this ticker.</p>
            )
          )}

          {showCharts && chartData.length > 0 && (
            <div className="overflow-hidden rounded-lg border border-slate-800/60">
              <SupportResistanceChart
                chartData={chartData}
                lastClose={result.ltp != null ? Number(result.ltp) : undefined}
                fibonacci={fib ?? null}
                levels={levels}
              />
            </div>
          )}

          {result.ai_context != null && (
            <AskAIPanel context={String(result.ai_context)} section="pro-trade/fibonacci-pro" systemPrompt={aiSystemPrompt} />
          )}
        </div>
      )}
    </div>
  )
}

export function FibonacciProPanel({ data, showCharts = false }: { data: Row; showCharts?: boolean }) {
  const results = (data.results as Row[]) ?? []
  const currency = String(data.currency ?? '₹')
  const assetClass = (data.asset_class as WatchlistMarket) || 'india'
  const aiSystemPrompt = String(data.ai_system_prompt ?? '')
  const catalog = (data.strategy_catalog as Row[]) ?? []

  if (data.error) return <p className="text-sm text-rose-400">{String(data.error)}</p>
  if (!results.length) return <p className="text-sm text-slate-500">No results yet.</p>

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-slate-700/50 bg-slate-900/40 px-3 py-2.5 text-sm leading-relaxed text-slate-300">
        <p className="font-medium text-slate-100">Results in plain English</p>
        <p className="mt-1 text-xs text-slate-400">
          <strong className="text-slate-300">Actionable ({String(data.entry_count ?? 0)})</strong> means at least one
          Fib tactic says price is in its entry zone with trend + reward:risk OK — look for BUY/SELL badges.
          Everything else is WAIT: useful levels may still show on the chart, but there is no ready trade case yet.
          Confidence % is a confluence score (not a promise). SL% is what you risk; TP% is what you aim to make;
          Reward:Risk tells you if the juice is worth the squeeze. Prefer the highest-confidence card whose
          &quot;When to use&quot; matches the current market mood.
        </p>
      </div>

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
        {data.timeframe != null && (
          <span>
            TF: <strong className="text-white">{String(data.timeframe)}</strong>
          </span>
        )}
      </div>

      {catalog.length > 0 && (
        <div className="rounded-xl border border-slate-800/60 bg-slate-950/30 p-3">
          <p className="mb-2 text-xs font-medium uppercase tracking-wider text-slate-500">Strategy playbook — when to use which</p>
          <div className="grid gap-2 sm:grid-cols-2">
            {catalog.map((s) => (
              <div key={String(s.id)} className="rounded-lg border border-slate-800/50 bg-slate-900/40 p-2.5">
                <p className="text-sm font-medium text-slate-100">{String(s.label)}</p>
                <p className="mt-0.5 text-[11px] text-violet-300/90">{String(s.style)} · typical R:R {String(s.typical_rr)}</p>
                <p className="mt-1 text-xs leading-relaxed text-slate-400">{String(s.when_to_use)}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="space-y-2">
        {results.map((res, i) => (
          <TickerResultCard
            key={String(res.ticker ?? i)}
            result={res}
            index={i}
            currency={currency}
            assetClass={assetClass}
            showCharts={showCharts}
            aiSystemPrompt={aiSystemPrompt}
          />
        ))}
      </div>
    </div>
  )
}
