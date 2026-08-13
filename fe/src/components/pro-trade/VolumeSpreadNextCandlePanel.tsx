import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { Badge } from '../ui/Badge'
import { Chip } from '../ui/Chip'
import { AddToWatchlistButton } from '../watchlist/AddToWatchlistButton'
import type { WatchlistMarket } from '../watchlist/WatchlistMarketContext'
import { VolumeProfileChart, type VpChartBar, type VpLevel } from './VolumeProfileChart'
import { AskAIPanel } from '../ai/AskAIPanel'

type Row = Record<string, unknown>

const SETUP_LABEL: Record<string, string> = {
  downthrust: 'Downthrust (SOS)',
  no_supply: 'No Supply (SOS)',
  upthrust: 'Upthrust (SOW)',
  no_demand: 'No Demand (SOW)',
}

function signalTone(signal: string): string {
  const s = signal.toUpperCase()
  if (s.includes('BUY') || s.includes('LONG') || s === 'CONFIRMED') return 'BUY'
  if (s.includes('SELL') || s.includes('SHORT') || s === 'FAILED') return 'SELL'
  return 'HOLD'
}

function SetupCard({ setup }: { setup: Row }) {
  const signal = String(setup.signal ?? 'WAIT')
  const setupId = String(setup.setup ?? '')
  return (
    <div className="rounded-lg border border-slate-800/70 bg-slate-950/40 p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-slate-200">{SETUP_LABEL[setupId] ?? setupId}</span>
        <Badge action={signalTone(signal)} />
        <span className="text-xs text-slate-500">{signal}</span>
        {setup.direction ? <span className="text-xs text-slate-400">{String(setup.direction)}</span> : null}
        {setup.family ? <span className="text-[11px] text-slate-500">{String(setup.family)}</span> : null}
        {setup.confidence_pct != null && (
          <span className="text-xs text-slate-400">{String(setup.confidence_pct)}% conf</span>
        )}
        {setup.is_live ? <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-[10px] text-emerald-300">LIVE → next candle</span> : null}
      </div>
      <p className="text-xs leading-relaxed text-slate-400">{String(setup.logic ?? '')}</p>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
        {setup.entry != null && <span>Entry: {String(setup.entry)}</span>}
        {setup.stop_loss != null && <span>SL: {String(setup.stop_loss)}</span>}
        {setup.target_1 != null && <span>TP: {String(setup.target_1)}</span>}
        {setup.bar_time != null && <span>Bar: {String(setup.bar_time)}</span>}
        {setup.next_candle_result != null && <span>Next candle: {String(setup.next_candle_result)}</span>}
        {setup.ultra_high_vol ? <span className="text-amber-400">Ultra-high vol</span> : null}
      </div>
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
  const setups = (result.setups as Row[]) ?? []
  const take = Boolean(result.take_trade)
  const stats = (result.next_candle_stats as Row) || {}
  const chartData = useMemo(
    () => ((result.chart_data as VpChartBar[]) ?? []).filter((b) => b && b.time != null),
    [result.chart_data],
  )
  const chartLevels = useMemo(() => {
    const out: VpLevel[] = []
    if (result.support_level != null) out.push({ label: 'Support', price: Number(result.support_level), color: '#34d399' })
    if (result.resistance_level != null) out.push({ label: 'Resistance', price: Number(result.resistance_level), color: '#f87171' })
    if (result.entry_price != null) out.push({ label: 'Entry', price: Number(result.entry_price), color: '#38bdf8' })
    if (result.stop_price != null) out.push({ label: 'SL', price: Number(result.stop_price), color: '#94a3b8' })
    if (result.target_price != null) out.push({ label: 'TP', price: Number(result.target_price), color: '#a78bfa' })
    return out
  }, [result.support_level, result.resistance_level, result.entry_price, result.stop_price, result.target_price])

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
          <Badge action={take ? signalTone(String(result.direction ?? '')) : 'HOLD'} />
          <span className="text-xs text-slate-500">{String(result.verdict ?? 'WAIT')}</span>
          {result.confidence_pct != null && (
            <span className="text-xs text-slate-400">{String(result.confidence_pct)}%</span>
          )}
          {stats.hit_rate_pct != null && (
            <span className="text-xs text-slate-500">
              Next-candle hit {String(stats.hit_rate_pct)}% ({String(stats.wins)}/{String(stats.samples)})
            </span>
          )}
          {result.error ? <span className="text-xs text-amber-400">{String(result.error)}</span> : null}
        </button>
        <AddToWatchlistButton ticker={String(result.ticker ?? '')} marketType={assetClass} compact />
      </div>
      {open && (
        <div className="space-y-3 border-t border-slate-800/70 px-4 py-3">
          {result.plain_english != null && (
            <div
              className={`rounded-lg border px-3 py-2.5 text-sm leading-relaxed ${
                take
                  ? 'border-emerald-500/30 bg-emerald-500/5 text-emerald-100'
                  : 'border-slate-700/60 bg-slate-950/50 text-slate-300'
              }`}
            >
              {String(result.plain_english)}
            </div>
          )}

          {((result.reasons as string[]) ?? []).length > 0 && (
            <ul className="list-disc space-y-1 pl-4 text-xs text-slate-500">
              {(result.reasons as string[]).map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          )}

          {showCharts && chartData.length > 0 && (
            <div className="rounded-lg border border-slate-800/60 bg-slate-950/40 p-3">
              <VolumeProfileChart
                chartData={chartData}
                ticker={String(result.ticker ?? '')}
                assetClass={assetClass}
                levels={chartLevels}
                histogram={[]}
                readingGuide="Candles show recent price and volume behavior. VSA compares each candle's range (wide vs narrow) against its volume (high vs low) — a wide-range candle on high volume shows real conviction, while a narrow-range candle on low volume shows indecision; that spread-vs-volume pattern is what's used to anticipate the next candle. The green/red Support/Resistance band marks the nearest level price is expected to react to."
              />
            </div>
          )}

          <div className="space-y-2">
            {setups.length === 0 && !result.error && (
              <p className="text-xs text-slate-500">No VSA Downthrust / No Supply / Upthrust / No Demand setups in lookback.</p>
            )}
            {setups.map((s, i) => (
              <SetupCard key={`${String(s.setup)}-${String(s.bar_time)}-${i}`} setup={s} />
            ))}
          </div>

          {((result.rules as string[]) ?? []).length > 0 && (
            <ul className="list-disc space-y-1 pl-4 text-xs text-slate-500">
              {(result.rules as string[]).map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          )}

          <AskAIPanel
            context={String(result.ai_context ?? '')}
            systemPrompt={aiSystemPrompt}
            section={`pro-trade/volume-spread-next-candle/${String(result.ticker ?? '')}`}
            className="mt-0"
          />
        </div>
      )}
    </div>
  )
}

type FilterMode = 'all' | 'actionable' | 'sos' | 'sow'

function AggregateStatsBar({ stats }: { stats: Row }) {
  const overall = (stats.overall as Row) || {}
  const sos = (stats.sos as Row) || {}
  const sow = (stats.sow as Row) || {}
  if (overall.samples == null || Number(overall.samples) === 0) return null

  const fmt = (r: Row, label: string) =>
    r.samples != null && Number(r.samples) > 0 ? (
      <span key={label} className="text-xs text-slate-400">
        {label} next-candle hit: <strong className="text-white">{String(r.hit_rate_pct)}%</strong> ({String(r.wins)}/
        {String(r.samples)})
      </span>
    ) : null

  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 rounded-lg border border-slate-800/70 bg-slate-950/40 px-3 py-2">
      {fmt(overall, 'Overall')}
      {fmt(sos, 'SOS')}
      {fmt(sow, 'SOW')}
    </div>
  )
}

export function VolumeSpreadNextCandlePanel({ data, showCharts = false }: { data: Row; showCharts?: boolean }) {
  const allResults = (data.results as Row[]) ?? []
  const currency = String(data.currency ?? '₹')
  const assetClass = (String(data.asset_class ?? 'india') as WatchlistMarket)
  const aggregateStats = data.aggregate_next_candle_stats as Row | undefined
  const aiSystemPrompt = String(data.ai_system_prompt ?? '')
  const [filter, setFilter] = useState<FilterMode>('all')

  const results = useMemo(() => {
    const withSetups = allResults.map((r) => {
      const setups = (r.setups as Row[]) ?? []
      if (filter === 'sos') return { ...r, setups: setups.filter((s) => s.family === 'SOS') }
      if (filter === 'sow') return { ...r, setups: setups.filter((s) => s.family === 'SOW') }
      return r
    })
    if (filter === 'actionable') return withSetups.filter((r) => Boolean(r.take_trade))
    if (filter === 'sos' || filter === 'sow')
      return withSetups.filter((r) => ((r.setups as Row[]) ?? []).length > 0)
    return withSetups
  }, [allResults, filter])

  const sorted = useMemo(
    () =>
      [...results].sort((a, b) => {
        const at = a.take_trade ? 1 : 0
        const bt = b.take_trade ? 1 : 0
        if (at !== bt) return bt - at
        return Number(b.confidence_pct ?? 0) - Number(a.confidence_pct ?? 0)
      }),
    [results],
  )

  if (!allResults.length) return <p className="text-sm text-slate-500">No results yet.</p>

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
        {data.youtube != null && (
          <a href={String(data.youtube)} target="_blank" rel="noreferrer" className="text-blue-400 hover:underline">
            Source video
          </a>
        )}
      </div>

      {aggregateStats && <AggregateStatsBar stats={aggregateStats} />}

      <div className="flex flex-wrap gap-2">
        <Chip selected={filter === 'all'} onClick={() => setFilter('all')}>
          All ({allResults.length})
        </Chip>
        <Chip selected={filter === 'actionable'} onClick={() => setFilter('actionable')}>
          Actionable ({allResults.filter((r) => r.take_trade).length})
        </Chip>
        <Chip selected={filter === 'sos'} onClick={() => setFilter('sos')}>
          SOS only
        </Chip>
        <Chip selected={filter === 'sow'} onClick={() => setFilter('sow')}>
          SOW only
        </Chip>
      </div>

      <div className="space-y-2">
        {sorted.length === 0 && <p className="text-sm text-slate-500">No tickers match this filter.</p>}
        {sorted.map((res, i) => (
          <TickerResultCard key={String(res.ticker ?? i)} result={res} index={i} currency={currency} assetClass={assetClass} showCharts={showCharts} aiSystemPrompt={aiSystemPrompt} />
        ))}
      </div>
      {data.disclaimer != null && <p className="text-xs text-slate-600">{String(data.disclaimer)}</p>}
    </div>
  )
}
