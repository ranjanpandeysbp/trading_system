import { Fragment, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, ChevronUp, TrendingDown, TrendingUp } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import {
  apiErrorMessage,
  fetchInvestingAgentStatus,
  fetchInvestingAgentStockCard,
  runDayBias,
  runFundamentalAnalysis,
  runMomentumScan,
  runMtfTrendStrength,
  runOptionChain,
  runProTradeElliottWave,
  runProTradePaVpSmc,
  runProTradeVolumeSpreadNextCandle,
  runQuickAnalyzer,
  runTradeSetup,
  runTradeSetupCopyTrade,
  runTradeSetupDivergence,
  runTradeSetupIntraHwp,
  runTradeSetupPatterns,
  runTradeSetupRealBottom,
  runTradeSetupScalping,
  runTradeSetupSma20200,
  runTradeSetupSmartMoney,
  runTradeSetupStopHunt,
  runTradeSetupSupportResistance,
  runTradeSetupTakeProfit,
  runTradeSetupTimeSeries,
  runTradeSetupWeakStrong,
  runUpgradeDowngradeScan,
  runWeakStrong,
} from '../../api/client'
import { AskAIPanel, buildAskContext } from '../ai/AskAIPanel'
import { StockScorecardView, type StockCardData } from '../ai/InvestingAgentStockCard'
import { TomorrowOutlookPanel } from '../market-pulse/MarketPulsePanels'
import { TickerInvestigationPanel } from '../technical-analysis/TechnicalAnalysisPanels'
import { Alert } from '../ui/Feedback'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { DataTable, SortableTh, Td, Th, useSort } from '../ui/Table'
import { StatCard } from '../ui/StatCard'
import { AddToWatchlistButton } from '../watchlist/AddToWatchlistButton'
import { SupportResistanceChart, type SRChartBar } from '../trading-hubs/SupportResistanceChart'

type Row = Record<string, unknown>

function verdictClass(verdict: string) {
  const v = verdict.toUpperCase()
  if (v.includes('BUY') || v.includes('BULL') || v.includes('LONG')) return 'text-emerald-400'
  if (v.includes('SELL') || v.includes('BEAR') || v.includes('SHORT') || v.includes('AVOID')) return 'text-rose-400'
  return 'text-amber-400'
}

function fmtNum(v: unknown, digits = 2): string {
  if (v == null || v === '') return '—'
  const n = Number(v)
  return Number.isFinite(n) ? n.toFixed(digits) : String(v)
}

function DayBiasNote({ bias, className, showReasons }: { bias: Row | undefined; className?: string; showReasons?: boolean }) {
  if (!bias || bias.up_pct == null || bias.down_pct == null) return null
  const up = Number(bias.up_pct)
  const down = Number(bias.down_pct)
  const reasons = (bias.reasons as string[]) ?? []
  return (
    <div>
      <p className={className ?? 'text-[11px] text-slate-400'}>
        <span className={up >= down ? 'font-semibold text-emerald-400' : 'text-slate-500'}>⬆ {up.toFixed(0)}% toward Day High</span>
        {' · '}
        <span className={down > up ? 'font-semibold text-rose-400' : 'text-slate-500'}>⬇ {down.toFixed(0)}% toward Day Low</span>
      </p>
      {showReasons && reasons.map((rr, i) => <p key={i} className="text-xs text-slate-500">· {rr}</p>)}
    </div>
  )
}

const DAY_BIAS_TIMEFRAMES = ['5m', '15m', '1h', '4h', '1d', '1w']

function DayBiasRecalculator({
  ticker, assetClass, exchange, defaultTimeframe = '1d', showReasons,
}: { ticker: string; assetClass: string; exchange?: string; defaultTimeframe?: string; showReasons?: boolean }) {
  const [tf, setTf] = useState(defaultTimeframe)
  const mut = useMutation({
    mutationFn: () => runDayBias({ ticker, asset_class: assetClass, timeframe: tf, exchange }),
  })
  const result = mut.data as Row | undefined
  const bias = result?.day_bias as Row | undefined

  return (
    <div className="mt-1 space-y-1">
      <div className="flex flex-wrap items-center gap-1">
        {DAY_BIAS_TIMEFRAMES.map((t) => (
          <Chip key={t} selected={tf === t} onClick={() => setTf(t)}>{t}</Chip>
        ))}
        <Button size="sm" variant="secondary" disabled={mut.isPending} onClick={() => mut.mutate()}>
          {mut.isPending ? 'Recalculating…' : `🔄 Recalculate @ ${tf}`}
        </Button>
      </div>
      {mut.isError && <p className="text-xs text-rose-400">{apiErrorMessage(mut.error)}</p>}
      {result?.error != null && <p className="text-xs text-slate-500">Unavailable — {String(result.error)}</p>}
      {bias && <DayBiasNote bias={bias} showReasons={showReasons} />}
    </div>
  )
}

const VOLUME_TIERS: [number, string][] = [
  [2.0, 'Very High'],
  [1.5, 'High'],
  [1.1, 'Above Average'],
  [0.9, 'Average'],
  [0.7, 'Below Average'],
]

function volumeTier(ratio: number | null | undefined): string {
  if (ratio == null) return '—'
  for (const [threshold, label] of VOLUME_TIERS) {
    if (ratio >= threshold) return label
  }
  return 'Very Low'
}

function volumePriceAnalysis(tf0: Row) {
  const ratio = tf0.volume_ratio as number | null | undefined
  const roc = tf0.roc_pct as number | null | undefined
  const trend = String(tf0.trend_direction ?? '—')
  const momentumChange = String(tf0.momentum_change ?? '—')
  const consolidating = Boolean(tf0.is_consolidating)
  const event = tf0.breakout_event as string | null | undefined

  const tier = volumeTier(ratio)
  const tierLower = tier.toLowerCase()
  const highVol = (ratio ?? 1.0) >= 1.5
  const aboveAvg = (ratio ?? 1.0) >= 1.1
  const belowAvg = (ratio ?? 1.0) <= 0.9
  const priceUp = (roc ?? 0.0) > 0
  const priceDown = (roc ?? 0.0) < 0
  const ratioStr = ratio != null ? `${ratio}x` : '—'

  let bias: 'BULLISH' | 'BEARISH' | 'NEUTRAL' = 'NEUTRAL'
  let badge = '⚪'
  let read = ''

  if (consolidating && aboveAvg) {
    bias = 'NEUTRAL'; badge = '⚪'
    read = `Price is consolidating in a tight range, but volume is running **${tierLower}** (${ratioStr} of average) — classic **accumulation/distribution** behavior: large participants are building or unwinding a position quietly before the range resolves into a breakout or breakdown.`
  } else if (consolidating) {
    bias = 'NEUTRAL'; badge = '⚪'
    read = `Price is consolidating with **${tierLower}** volume (${ratioStr} of average) — a quiet, low-conviction range with no large participants actively pressing a direction.`
  } else if (priceUp && highVol) {
    bias = 'BULLISH'; badge = '🟢'
    read = `Price is rising on **${tierLower}** volume (${ratioStr} of average) — textbook **bullish confirmation**: genuine buying pressure/demand backs the move, not a thin drift up.`
  } else if (priceUp && belowAvg) {
    bias = 'NEUTRAL'; badge = '⚪'
    read = `Price is rising but volume is **${tierLower}** (${ratioStr} of average) — a **low-conviction rally**. Without participation behind it, the advance is more vulnerable to a quick reversal; weight this weaker than a high-volume move.`
  } else if (priceDown && highVol) {
    bias = 'BEARISH'; badge = '🔴'
    read = `Price is falling on **${tierLower}** volume (${ratioStr} of average) — textbook **bearish confirmation**: genuine selling pressure/distribution backs the decline.`
  } else if (priceDown && belowAvg) {
    bias = 'NEUTRAL'; badge = '⚪'
    read = `Price is falling but volume is **${tierLower}** (${ratioStr} of average) — a **low-conviction sell-off**, more likely profit-taking/drift than committed distribution; a low-volume pullback often resolves back in the prior direction.`
  } else {
    bias = 'NEUTRAL'; badge = '⚪'
    read = `Volume is running **${tierLower}** (${ratioStr} of average) with no strong directional bias from price right now.`
  }

  let divergenceCaption: string | null = null
  if (!consolidating && momentumChange === 'INCREASING' && aboveAvg) {
    divergenceCaption = '📶 Volume is expanding alongside a strengthening trend — a healthy sign for continuation.'
  } else if (!consolidating && momentumChange === 'DECREASING' && aboveAvg) {
    divergenceCaption = '⚠️ Volume is elevated even as trend strength fades — can flag exhaustion/climactic volume near a turning point rather than healthy continuation.'
  }

  let breakoutCaption: string | null = null
  if (event != null && event !== 'NONE' && event !== 'RANGE') {
    const confirmed = (ratio ?? 0) >= 1.15
    const directionWord = event === 'RESISTANCE_BREAK' ? 'Breakout above resistance' : 'Breakdown below support'
    breakoutCaption = `🚨 **${directionWord}** detected — ` + (
      confirmed
        ? 'volume-confirmed (≥1.15x average), the higher-probability read.'
        : '**not yet volume-confirmed** — unconfirmed breaks fail more often; wait for participation before trusting it.'
    )
  }

  return { tier, bias, badge, read, ratioStr, trend, momentumChange, divergenceCaption, breakoutCaption }
}

function mdBold(text: string) {
  const parts = text.split('**')
  return parts.map((p, i) => (i % 2 === 1 ? <strong key={i}>{p}</strong> : <Fragment key={i}>{p}</Fragment>))
}

const SR_EVENT_LABEL: Record<string, string> = {
  RESISTANCE_BREAK: '🚀 Breaking resistance',
  SUPPORT_BREAK: '🔻 Breaking support',
  RANGE: '↔️ In range',
  NONE: '—',
}

const DIVERGENCE_BADGE: Record<string, string> = {
  BULLISH: '🟢 Positive (Bullish) Divergence',
  BEARISH: '🔴 Negative (Bearish) Divergence',
  NEUTRAL: '⚪ Neutral / No Divergence',
}

const HUNT_STATUS_BADGE: Record<string, string> = {
  ACTIVE_SWEEP: '🎣 Active Sweep Detected',
  HIGH_RISK: '⚠️ High Hunt-Risk Zone',
  LOW_RISK: '🟢 Low Hunt-Risk',
}

const REAL_BOTTOM_STATUS_BADGE: Record<string, string> = {
  CONFIRMED_ENTRY: '🟢 Confirmed — Entry Zone Live',
  PENDING_ENTRY: '🟡 Pending — Awaiting Pullback',
  TRAP_CONFIRMED: '🟠 Trap Confirmed — Awaiting Displacement',
  TRAP_UNCONFIRMED: '🔵 Trap Fired — Absorption/Retest Unconfirmed',
  NO_SETUP: '⚪ No Setup',
}

// What to actually do for each status — shown directly next to results so a
// bucket label never has to be interpreted from memory.
const REAL_BOTTOM_STATUS_ACTION: Record<string, string> = {
  CONFIRMED_ENTRY: 'Actionable now — price is inside the entry zone with a confirmed trigger candle. Enter near current price, stop below the trap low, target the next resistance shown per ticker.',
  PENDING_ENTRY: "Not tradeable yet — set an alert at the entry zone shown per ticker and wait for price to pull back into it with a bullish trigger candle before entering. Don't buy the displacement candle itself.",
  TRAP_CONFIRMED: 'Watchlist only, not an entry — absorption, retest, and the liquidity trap are all validated, but price hasn\'t broken structure yet. Watch for a strong bullish candle to close above the recent swing high; that promotes it to Pending. If price rolls back below the trap low instead, drop it.',
  TRAP_UNCONFIRMED: "Lowest-confidence bucket — generally skip. A liquidity sweep fired, but the volume evidence for genuine institutional absorption/retest didn't hold up, so this is likely just noise.",
  NO_SETUP: 'Nothing in progress — no sell-side liquidity sweep detected recently.',
}

const INTRA_HWP_PHASE_BADGE: Record<string, string> = {
  NO_GAP: '⚪ No Gap',
  AWAITING_GAP_TAG: '🔵 Awaiting Gap Tag',
  AWAITING_EMA_CROSS: '🟠 Awaiting EMA Cross',
  ENTRY_TRIGGERED: '🟢 Entry Triggered',
}

const COPY_TRADE_PHASE_BADGE: Record<string, string> = {
  NO_SETUP: '⚪ No Setup',
  WATCHING_ZONE: '🔵 Watching Zone',
  EXIT_SIGNAL: '🚪 Exit Signal',
  ENTRY_TRIGGERED: '🟢 Entry Triggered',
}

function StopTierRow({ label, tier }: { label: string; tier: Row | undefined }) {
  if (!tier) return null
  return (
    <p className="text-xs text-slate-400">
      {label}: <strong>{fmtNum(tier.price, 4)}</strong> ({fmtNum(tier.pct, 2)}% from current price)
      {tier.nudged_for_round_number ? ` · nudged off round number ${fmtNum(tier.round_number_avoided, 2)}` : ''}
    </p>
  )
}

function StopHuntScenario({ label, stops }: { label: string; stops: Row | undefined }) {
  if (!stops) return null
  const anchor = (stops.anchor as Row) ?? {}
  return (
    <div className="mt-2">
      <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">{label}</p>
      <p className="text-xs text-slate-500">Anchored beyond {String(anchor.label ?? 'nearby structure')}.</p>
      <StopTierRow label="🎯 Tight / Aggressive" tier={stops.tight as Row} />
      <StopTierRow label="🛡️ Safe / Hunt-Resistant" tier={stops.safe as Row} />
    </div>
  )
}

const TP_STATUS_BADGE: Record<string, string> = {
  HIGH_CONFLUENCE: '🎯 High-Confluence Target',
  MODERATE_CONFLUENCE: '📍 Moderate-Confluence Target',
  LOW_CONFLUENCE: '🌫️ Low-Confluence — Thin Structure',
}

function TargetTierRow({ label, tier }: { label: string; tier: Row | undefined }) {
  if (!tier) return null
  return (
    <p className="text-xs text-slate-400">
      {label}: <strong>{fmtNum(tier.price, 4)}</strong> ({fmtNum(tier.pct, 2)}% from current price)
      {tier.near_round_number ? ` · near round number ${fmtNum(tier.round_number, 2)}` : ''}
    </p>
  )
}

function TakeProfitScenario({ label, targets }: { label: string; targets: Row | undefined }) {
  if (!targets) return null
  const tp1Anchor = (targets.tp1_anchor as Row) ?? {}
  const tp2Anchor = (targets.tp2_anchor as Row) ?? {}
  return (
    <div className="mt-2">
      <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">{label}</p>
      <TargetTierRow label="TP1 (Conservative)" tier={targets.tp1 as Row} />
      <p className="text-xs text-slate-500">Anchored on {String(tp1Anchor.label ?? 'nearby structure')}.</p>
      <TargetTierRow label="TP2 (Extended)" tier={targets.tp2 as Row} />
      <p className="text-xs text-slate-500">Anchored on {String(tp2Anchor.label ?? 'an extended projection')}.</p>
    </div>
  )
}

function SummaryCard({ title, row }: { title: string; row: Row }) {
  const verdict = String(row.verdict ?? '—')
  const reasons = (row.reasons as string[]) ?? []
  const plan = row.trade_plan as Row | undefined
  const ticker = row.ticker != null ? String(row.ticker) : ''

  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-slate-800/80 bg-slate-900/40 px-4 py-5 sm:px-6">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <p className="text-xs font-medium uppercase tracking-wider text-slate-500">{title}</p>
            <p className={`mt-1 text-xl font-bold sm:text-2xl ${verdictClass(verdict)}`}>
              {ticker ? `${ticker} · ` : ''}{verdict}
            </p>
          </div>
          {ticker && <AddToWatchlistButton ticker={ticker} />}
        </div>
        <div className="mt-3 flex flex-wrap gap-3 text-sm">
          {row.score != null && (
            <span className="rounded-lg bg-slate-800/60 px-3 py-1 text-slate-200">
              Score: <strong>{Number(row.score).toFixed(1)}</strong>/10
            </span>
          )}
          {row.confidence_pct != null && (
            <span className="rounded-lg bg-slate-800/60 px-3 py-1 text-slate-200">
              Confidence: <strong>{Number(row.confidence_pct).toFixed(0)}%</strong>
            </span>
          )}
          {row.direction != null && (
            <span className="rounded-lg bg-slate-800/60 px-3 py-1 text-slate-200">
              Direction: <strong>{String(row.direction)}</strong>
            </span>
          )}
          {row.take_trade != null && (
            <span className="rounded-lg bg-slate-800/60 px-3 py-1 text-slate-200">
              Take trade: <strong>{row.take_trade ? 'Yes' : 'No'}</strong>
            </span>
          )}
        </div>
        {row.summary != null && (
          <p className="mt-4 text-sm leading-relaxed text-slate-300">{String(row.summary)}</p>
        )}
        {row.meaning != null && String(row.meaning).trim() && (
          <p className="mt-2 text-sm text-slate-400">{String(row.meaning)}</p>
        )}
        {row.action != null && String(row.action).trim() && (
          <p className="mt-2 text-sm text-slate-400">{String(row.action)}</p>
        )}
      </div>

      {reasons.length > 0 && (
        <div>
          <h4 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">Engine breakdown</h4>
          <ul className="space-y-1.5 text-sm text-slate-300">
            {reasons.map((r) => (
              <li key={r} className="flex gap-2">
                <span className="text-slate-500">•</span>
                {r}
              </li>
            ))}
          </ul>
        </div>
      )}

      {plan && Object.keys(plan).length > 0 && (
        <Card className="!p-4">
          <h4 className="mb-3 text-sm font-semibold text-white">Trade plan</h4>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {plan.direction != null && <StatCard label="Direction" value={String(plan.direction)} />}
            {plan.stop_loss_pct != null && <StatCard label="Stop loss" value={`${plan.stop_loss_pct}%`} />}
            {plan.take_profit_pct != null && <StatCard label="Take profit" value={`${plan.take_profit_pct}%`} />}
            {plan.expected_profit_pct != null && (
              <StatCard label="Expected profit" value={`${plan.expected_profit_pct}%`} />
            )}
            {plan.confidence_pct != null && (
              <StatCard label="Plan confidence" value={`${plan.confidence_pct}%`} />
            )}
            {plan.holding_period != null && (
              <StatCard label="Hold period" value={String(plan.holding_period)} />
            )}
          </div>
          {plan.exit_rule != null && (
            <p className="mt-3 text-sm text-slate-400">{String(plan.exit_rule)}</p>
          )}
          {plan.max_hold_exit != null && String(plan.max_hold_exit).trim() && (
            <p className="mt-1 text-xs text-slate-500">Time stop: {String(plan.max_hold_exit)}</p>
          )}
        </Card>
      )}
    </div>
  )
}

function MegaAnalyserPanel({ data }: { data: Row }) {
  const recs = (data.recommendations as Row[]) ?? []
  const mega = (data.mega as Row | undefined) ?? recs[0]
  const summaries = (data.summaries as Row[]) ?? []
  const [filter, setFilter] = useState<'all' | 'trade' | 'watch' | 'error'>('all')
  const [idx, setIdx] = useState(0)

  if (recs.length > 1) {
    const rec = recs[idx] ?? recs[0]
    return (
      <div className="space-y-6">
        <div className="flex flex-wrap gap-2">
          {recs.map((r, i) => (
            <Chip key={String(r.ticker)} selected={idx === i} onClick={() => setIdx(i)}>
              {String(r.ticker)}
            </Chip>
          ))}
        </div>
        <SummaryCard title="Mega Analyser verdict" row={rec} />
        {summaries.length > 0 && (
          <EngineSummaryTable summaries={summaries} filter={filter} setFilter={setFilter} ticker={String(rec.ticker)} />
        )}
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {mega && <SummaryCard title="Mega Analyser verdict" row={mega} />}
      {summaries.length > 0 && (
        <EngineSummaryTable summaries={summaries} filter={filter} setFilter={setFilter} />
      )}
    </div>
  )
}

function EngineSummaryTable({
  summaries,
  filter,
  setFilter,
  ticker,
}: {
  summaries: Row[]
  filter: 'all' | 'trade' | 'watch' | 'error'
  setFilter: (f: 'all' | 'trade' | 'watch' | 'error') => void
  ticker?: string
}) {
  const [expanded, setExpanded] = useState<number | null>(null)
  const rows = ticker
    ? summaries.filter((s) => String(s.ticker) === ticker)
    : summaries
  const filtered = rows.filter((s) => {
    if (filter === 'trade') return s.signal_type === 'trade'
    if (filter === 'watch') return s.signal_type === 'no_trade' || s.signal_type === 'watch'
    if (filter === 'error') return s.signal_type === 'error'
    return true
  })

  const actionable = rows.filter((s) => s.signal_type === 'trade')
  const best = (actionable.length ? actionable : rows).reduce<Row | null>((top, s) => {
    if (!top) return s
    return Number(s.score ?? 0) > Number(top.score ?? 0) ? s : top
  }, null)
  const bestPlan = (best?.trade_plan as Row) ?? {}

  const { sorted, sortKey, sortDir, handleSort } = useSort(filtered, {
    ticker: (s) => String(s.ticker ?? ''),
    engine: (s) => String(s.tab ?? ''),
    tf: (s) => String(s.timeframe ?? ''),
    score: (s) => (s.score != null ? Number(s.score) : null),
    verdict: (s) => String(s.verdict ?? ''),
    recommendation: (s) => String(s.recommendation ?? s.summary ?? ''),
    sl: (s) => {
      const plan = (s.trade_plan as Row) ?? {}
      return s.signal_type === 'trade' && plan.stop_loss_pct != null ? Number(plan.stop_loss_pct) : null
    },
    tp: (s) => {
      const plan = (s.trade_plan as Row) ?? {}
      return s.signal_type === 'trade' && plan.take_profit_pct != null ? Number(plan.take_profit_pct) : null
    },
    exp: (s) => {
      const plan = (s.trade_plan as Row) ?? {}
      return s.signal_type === 'trade' && plan.expected_profit_pct != null ? Number(plan.expected_profit_pct) : null
    },
  })

  return (
    <div>
      {best && (
        <div className="mb-4 rounded-xl border border-emerald-500/30 bg-emerald-500/5 px-4 py-3">
          <p className="text-xs font-medium uppercase tracking-wider text-emerald-400">
            {actionable.length ? 'Best actionable' : 'Best result'}
          </p>
          <p className="mt-1 text-sm text-white">
            <strong>{String(best.ticker ?? '—')}</strong> · {String(best.timeframe ?? '—')} · {String(best.tab ?? '—')} ·
            {' '}Score {fmtNum(best.score, 1)}/10
          </p>
          <p className="mt-1 text-sm text-slate-300">{String(best.recommendation ?? best.verdict ?? '—')}</p>
          {(bestPlan.stop_loss_pct != null || bestPlan.take_profit_pct != null || bestPlan.expected_profit_pct != null) && (
            <p className="mt-1 text-xs text-slate-400">
              SL -{fmtNum(bestPlan.stop_loss_pct)}% · TP +{fmtNum(bestPlan.take_profit_pct)}% · Exp +{fmtNum(bestPlan.expected_profit_pct)}%
            </p>
          )}
        </div>
      )}
      <div className="mb-3 flex flex-wrap gap-2">
        <Chip selected={filter === 'all'} onClick={() => setFilter('all')}>All ({rows.length})</Chip>
        <Chip selected={filter === 'trade'} onClick={() => setFilter('trade')}>Actionable</Chip>
        <Chip selected={filter === 'watch'} onClick={() => setFilter('watch')}>No signal</Chip>
        <Chip selected={filter === 'error'} onClick={() => setFilter('error')}>Errors</Chip>
      </div>
      <DataTable minWidth={900}>
        <thead>
          <tr>
            <SortableTh active={sortKey === 'ticker'} direction={sortDir} onSort={() => handleSort('ticker')}>Ticker</SortableTh>
            <SortableTh active={sortKey === 'verdict'} direction={sortDir} onSort={() => handleSort('verdict')}>Verdict</SortableTh>
            <SortableTh active={sortKey === 'score'} direction={sortDir} onSort={() => handleSort('score')}>Score</SortableTh>
            <SortableTh active={sortKey === 'recommendation'} direction={sortDir} onSort={() => handleSort('recommendation')}>Recommendation</SortableTh>
            <SortableTh active={sortKey === 'tf'} direction={sortDir} onSort={() => handleSort('tf')}>TF</SortableTh>
            <SortableTh active={sortKey === 'engine'} direction={sortDir} onSort={() => handleSort('engine')}>Engine</SortableTh>
            <SortableTh active={sortKey === 'sl'} direction={sortDir} onSort={() => handleSort('sl')}>SL %</SortableTh>
            <SortableTh active={sortKey === 'tp'} direction={sortDir} onSort={() => handleSort('tp')}>TP %</SortableTh>
            <SortableTh active={sortKey === 'exp'} direction={sortDir} onSort={() => handleSort('exp')}>Exp %</SortableTh>
            <Th></Th>
          </tr>
        </thead>
        <tbody>
          {sorted.slice(0, 40).map((s, i) => {
            const plan = (s.trade_plan as Row) ?? {}
            const reasons = (s.reasons as string[]) ?? []
            const isTrade = s.signal_type === 'trade'
            return (
              <Fragment key={`${String(s.tab)}-${String(s.timeframe)}-${i}`}>
                <tr
                  className={reasons.length ? 'cursor-pointer hover:bg-slate-800/30' : undefined}
                  onClick={reasons.length ? () => setExpanded(expanded === i ? null : i) : undefined}
                >
                  <Td>{String(s.ticker ?? '—')}</Td>
                  <Td>{String(s.verdict ?? '—')}</Td>
                  <Td className={verdictClass(String(s.verdict ?? ''))}>
                    {s.score != null ? Number(s.score).toFixed(1) : '—'}
                  </Td>
                  <Td className="max-w-xs truncate text-slate-400">{String(s.recommendation ?? s.summary ?? '—')}</Td>
                  <Td>{String(s.timeframe ?? '—')}</Td>
                  <Td>{String(s.tab ?? '—')}</Td>
                  <Td>{isTrade ? fmtNum(plan.stop_loss_pct) : '—'}</Td>
                  <Td>{isTrade ? fmtNum(plan.take_profit_pct) : '—'}</Td>
                  <Td>{isTrade ? fmtNum(plan.expected_profit_pct) : '—'}</Td>
                  <Td onClick={(e) => e.stopPropagation()}>
                    <AddToWatchlistButton ticker={String(s.ticker ?? '')} compact />
                  </Td>
                </tr>
                {expanded === i && reasons.length > 0 && (
                  <tr>
                    <td colSpan={10} className="border-b border-slate-800/40 bg-slate-900/30 px-4 py-3">
                      <ul className="space-y-1 text-xs text-slate-300">
                        {reasons.map((r, ri) => <li key={ri}>• {r}</li>)}
                      </ul>
                    </td>
                  </tr>
                )}
              </Fragment>
            )
          })}
        </tbody>
      </DataTable>
    </div>
  )
}

function BuySellPanel({ data }: { data: Row }) {
  const recs = (data.recommendations as Row[]) ?? []
  const [idx, setIdx] = useState(0)
  const { sorted, sortKey, sortDir, handleSort } = useSort(recs, {
    ticker: (r) => String(r.ticker ?? ''),
    take_trade: (r) => (r.take_trade ? 1 : 0),
    verdict: (r) => String(r.verdict ?? ''),
    score: (r) => (r.score != null ? Number(r.score) : null),
    confidence_pct: (r) => (r.confidence_pct != null ? Number(r.confidence_pct) : null),
    sl_pct: (r) => (r.sl_pct != null ? Number(r.sl_pct) : null),
    tp_pct: (r) => (r.tp_pct != null ? Number(r.tp_pct) : null),
    engine_count: (r) => (r.engine_count != null ? Number(r.engine_count) : null),
  })

  if (!recs.length) {
    return <p className="text-sm text-slate-500">No recommendations returned.</p>
  }

  const rec = recs[idx] ?? recs[0]
  return (
    <div className="space-y-4">
      {recs.length > 1 && (
        <DataTable minWidth={720}>
          <thead>
            <tr>
              <SortableTh active={sortKey === 'ticker'} direction={sortDir} onSort={() => handleSort('ticker')}>Ticker</SortableTh>
              <SortableTh active={sortKey === 'take_trade'} direction={sortDir} onSort={() => handleSort('take_trade')}>Take trade?</SortableTh>
              <SortableTh active={sortKey === 'verdict'} direction={sortDir} onSort={() => handleSort('verdict')}>Verdict</SortableTh>
              <SortableTh active={sortKey === 'score'} direction={sortDir} onSort={() => handleSort('score')}>Score</SortableTh>
              <SortableTh active={sortKey === 'confidence_pct'} direction={sortDir} onSort={() => handleSort('confidence_pct')}>Confidence</SortableTh>
              <SortableTh active={sortKey === 'sl_pct'} direction={sortDir} onSort={() => handleSort('sl_pct')}>SL %</SortableTh>
              <SortableTh active={sortKey === 'tp_pct'} direction={sortDir} onSort={() => handleSort('tp_pct')}>TP %</SortableTh>
              <SortableTh active={sortKey === 'engine_count'} direction={sortDir} onSort={() => handleSort('engine_count')}>Engines</SortableTh>
              <Th></Th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((r) => {
              const i = recs.indexOf(r)
              return (
                <tr
                  key={String(r.ticker)}
                  className={`cursor-pointer hover:bg-slate-800/30 ${idx === i ? 'bg-slate-800/40' : ''}`}
                  onClick={() => setIdx(i)}
                >
                  <Td className="font-medium text-white">{String(r.ticker)}</Td>
                  <Td>{r.take_trade ? '✅' : '❌'}</Td>
                  <Td className={verdictClass(String(r.verdict ?? ''))}>{String(r.verdict ?? '—')}</Td>
                  <Td>{fmtNum(r.score, 1)}</Td>
                  <Td>{fmtNum(r.confidence_pct, 0)}%</Td>
                  <Td>{fmtNum(r.sl_pct)}</Td>
                  <Td>{fmtNum(r.tp_pct)}</Td>
                  <Td>{String(r.engine_count ?? '—')}</Td>
                  <Td onClick={(e) => e.stopPropagation()}>
                    <AddToWatchlistButton ticker={String(r.ticker ?? '')} compact />
                  </Td>
                </tr>
              )
            })}
          </tbody>
        </DataTable>
      )}
      <div className="flex flex-wrap gap-2">
        {recs.map((r, i) => (
          <Chip key={String(r.ticker)} selected={idx === i} onClick={() => setIdx(i)}>
            {String(r.ticker)}
          </Chip>
        ))}
      </div>
      <SummaryCard title={`Buy / Sell · ${String(data.asset_class ?? 'india')}`} row={rec} />
    </div>
  )
}

function MomentumPanel({ data }: { data: Row }) {
  const results = (data.results as Row[]) ?? []
  const [idx, setIdx] = useState(0)
  const r = results[idx] ?? results[0] ?? {}
  const perTf = (r.per_tf as Row[]) ?? []
  const { sorted: sortedPerTf, sortKey: perTfSortKey, sortDir: perTfSortDir, handleSort: handlePerTfSort } = useSort(perTf, {
    tf: (t) => String(t.timeframe ?? ''),
    direction: (t) => String(t.trend_direction ?? ''),
    strength: (t) => String(t.strength ?? ''),
    momentum: (t) => String(t.momentum_change ?? ''),
    sr_event: (t) => String(t.breakout_event ?? ''),
    adx: (t) => (t.adx != null ? Number(t.adx) : null),
    adx_delta: (t) => (t.adx_delta != null ? Number(t.adx_delta) : null),
    rsi: (t) => (t.rsi != null ? Number(t.rsi) : null),
    rsi_zone: (t) => String(t.rsi_zone ?? ''),
    macd_hist: (t) => (t.macd_hist != null ? Number(t.macd_hist) : null),
    roc: (t) => (t.roc_pct != null ? Number(t.roc_pct) : null),
    vol: (t) => (t.volume_ratio != null ? Number(t.volume_ratio) : null),
    conf: (t) => (t.confidence_continue_pct != null ? Number(t.confidence_continue_pct) : null),
    breakout: (t) => (t.breakout_up_pct != null ? Number(t.breakout_up_pct) : null),
  })
  if (!results.length) return <p className="text-sm text-slate-500">No results.</p>
  const combo = r.fundamentals_combo as Row | undefined
  const action = (r.actionability as Row) ?? {}
  const upPct = r.breakout_up_pct

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {results.map((res, i) => (
          <Chip key={`${String(res.ticker)}-${i}`} selected={idx === i} onClick={() => setIdx(i)}>
            {String(res.ticker)}
          </Chip>
        ))}
      </div>

      {r.error ? (
        <Alert type="error">{String(r.error)}</Alert>
      ) : (
        <>
          <div className="rounded-2xl border border-slate-800/80 bg-slate-900/40 px-4 py-5 sm:px-6">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs font-medium uppercase tracking-wider text-slate-500">Momentum · {String(r.ticker)}</p>
              <AddToWatchlistButton ticker={String(r.ticker ?? '')} compact />
            </div>
            <p className={`mt-1 text-xl font-bold sm:text-2xl ${verdictClass(String(r.overall_direction ?? ''))}`}>
              {String(r.overall_direction ?? '—')}
            </p>
            {action.reason != null && (
              <p className="mt-2 text-sm text-slate-300"><strong>Verdict:</strong> {String(action.reason)}</p>
            )}
            {combo && (
              <div className="mt-2 text-sm text-slate-400">
                <p>{String(combo.note ?? '')}</p>
                <p className="text-xs text-slate-500">Technical-only confidence was {fmtNum(r.technical_confidence_pct, 0)}%.</p>
              </div>
            )}
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label="Direction" value={String(r.overall_direction ?? '—')} />
            <StatCard label="Strength" value={String(r.overall_strength ?? '—')} />
            <StatCard label="Momentum" value={String(r.overall_momentum_change ?? '—')} />
            <StatCard
              label={upPct != null ? 'Breakout odds' : 'Confidence continues'}
              value={upPct != null ? `↑${fmtNum(upPct, 0)}% / ↓${fmtNum(r.breakout_down_pct, 0)}%` : `${fmtNum(r.confidence_continue_pct, 0)}%`}
            />
          </div>

          <p className="text-xs text-amber-500/80">
            Calibration check (walk-forward, 15 India stocks, ~9,300 signals, 2%/10-day target-stop): this
            confidence score showed no meaningful difference in realized win rate between its highest bucket
            (48.4%) and lowest (50.5%) — treat the number as a rough directional lean, not a validated
            probability, until it's been recalibrated.
          </p>

          {r.alignment != null && <p className="text-sm text-slate-400">{String(r.alignment)}</p>}

          {((r.reasons as string[]) ?? []).length > 0 && (
            <div>
              <h4 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">Engine breakdown</h4>
              <ul className="space-y-1.5 text-sm text-slate-300">
                {(r.reasons as string[]).map((rr, i) => (
                  <li key={i} className="flex gap-2"><span className="text-slate-500">•</span>{rr}</li>
                ))}
              </ul>
            </div>
          )}

          {perTf.length > 0 && (
            <div>
              <h4 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">Per-timeframe breakdown</h4>
              <DataTable minWidth={960}>
                <thead>
                  <tr>
                    <SortableTh active={perTfSortKey === 'tf'} direction={perTfSortDir} onSort={() => handlePerTfSort('tf')}>TF</SortableTh>
                    <SortableTh active={perTfSortKey === 'direction'} direction={perTfSortDir} onSort={() => handlePerTfSort('direction')}>Direction</SortableTh>
                    <SortableTh active={perTfSortKey === 'strength'} direction={perTfSortDir} onSort={() => handlePerTfSort('strength')}>Strength</SortableTh>
                    <SortableTh active={perTfSortKey === 'momentum'} direction={perTfSortDir} onSort={() => handlePerTfSort('momentum')}>Momentum</SortableTh>
                    <SortableTh active={perTfSortKey === 'sr_event'} direction={perTfSortDir} onSort={() => handlePerTfSort('sr_event')}>S/R Event</SortableTh>
                    <SortableTh active={perTfSortKey === 'adx'} direction={perTfSortDir} onSort={() => handlePerTfSort('adx')}>ADX</SortableTh>
                    <SortableTh active={perTfSortKey === 'adx_delta'} direction={perTfSortDir} onSort={() => handlePerTfSort('adx_delta')}>ADX Δ</SortableTh>
                    <SortableTh active={perTfSortKey === 'rsi'} direction={perTfSortDir} onSort={() => handlePerTfSort('rsi')}>RSI</SortableTh>
                    <SortableTh active={perTfSortKey === 'rsi_zone'} direction={perTfSortDir} onSort={() => handlePerTfSort('rsi_zone')}>RSI zone</SortableTh>
                    <SortableTh active={perTfSortKey === 'macd_hist'} direction={perTfSortDir} onSort={() => handlePerTfSort('macd_hist')}>MACD hist</SortableTh>
                    <SortableTh active={perTfSortKey === 'roc'} direction={perTfSortDir} onSort={() => handlePerTfSort('roc')}>ROC %</SortableTh>
                    <SortableTh active={perTfSortKey === 'vol'} direction={perTfSortDir} onSort={() => handlePerTfSort('vol')}>Vol x</SortableTh>
                    <SortableTh active={perTfSortKey === 'conf'} direction={perTfSortDir} onSort={() => handlePerTfSort('conf')}>Conf %</SortableTh>
                    <SortableTh active={perTfSortKey === 'breakout'} direction={perTfSortDir} onSort={() => handlePerTfSort('breakout')}>Breakout ↑/↓ %</SortableTh>
                  </tr>
                </thead>
                <tbody>
                  {sortedPerTf.map((tf, i) => (
                    <tr key={i}>
                      <Td>{String(tf.timeframe)}</Td>
                      <Td className={verdictClass(String(tf.trend_direction ?? ''))}>{String(tf.trend_direction ?? '—')}</Td>
                      <Td>{String(tf.strength ?? '—')}</Td>
                      <Td>{String(tf.momentum_change ?? '—')}</Td>
                      <Td>{SR_EVENT_LABEL[String(tf.breakout_event ?? 'NONE')] ?? '—'}</Td>
                      <Td>{fmtNum(tf.adx)}</Td>
                      <Td>{fmtNum(tf.adx_delta)}</Td>
                      <Td>{fmtNum(tf.rsi)}</Td>
                      <Td>{String(tf.rsi_zone ?? '—')}</Td>
                      <Td>{fmtNum(tf.macd_hist)}</Td>
                      <Td>{fmtNum(tf.roc_pct)}</Td>
                      <Td>{fmtNum(tf.volume_ratio)}</Td>
                      <Td>{fmtNum(tf.confidence_continue_pct, 0)}</Td>
                      <Td>{tf.breakout_up_pct != null ? `${fmtNum(tf.breakout_up_pct, 0)}/${fmtNum(tf.breakout_down_pct, 0)}` : '—'}</Td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function DivergencesPanel({ data }: { data: Row }) {
  const results = (data.results as Row[]) ?? []
  const [idx, setIdx] = useState(0)
  const r = results[idx] ?? results[0] ?? {}
  const perTf = (r.per_tf as Record<string, Row>) ?? {}
  const tfEntries = Object.entries(perTf)
  if (!results.length) return <p className="text-sm text-slate-500">No results.</p>

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {results.map((res, i) => (
          <Chip key={`${String(res.ticker)}-${i}`} selected={idx === i} onClick={() => setIdx(i)}>
            {String(res.ticker)}
          </Chip>
        ))}
      </div>

      {!tfEntries.length ? (
        <Alert type="error">{String(r.error ?? 'No results.')}</Alert>
      ) : (
        <div className="grid gap-3">
          {tfEntries.map(([tf, res]) => (
            <div key={tf} className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-3">
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">{tf}{res.price != null ? ` · ${fmtNum(res.price, 4)}` : ''}</p>
              {res.error != null ? (
                <p className="mt-1 text-xs text-slate-500">Unavailable — {String(res.error)}</p>
              ) : (
                <>
                  <p className="mt-1 text-sm text-slate-300">
                    {DIVERGENCE_BADGE[String(res.bias ?? 'NEUTRAL')] ?? String(res.bias ?? '—')} · {fmtNum(res.confidence_pct, 0)}% confidence
                  </p>
                  {((res.reasons as string[]) ?? []).map((rr, i) => <p key={i} className="mt-1 text-xs text-slate-500">· {mdBold(rr)}</p>)}
                </>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function StopHuntPanel({ data }: { data: Row }) {
  const results = (data.results as Row[]) ?? []
  const [idx, setIdx] = useState(0)
  const r = results[idx] ?? results[0] ?? {}
  const perTf = (r.per_tf as Record<string, Row>) ?? {}
  const tfEntries = Object.entries(perTf)
  if (!results.length) return <p className="text-sm text-slate-500">No results.</p>

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {results.map((res, i) => (
          <Chip key={`${String(res.ticker)}-${i}`} selected={idx === i} onClick={() => setIdx(i)}>
            {String(res.ticker)}
          </Chip>
        ))}
      </div>

      {!tfEntries.length ? (
        <Alert type="error">{String(r.error ?? 'No results.')}</Alert>
      ) : (
        <div className="grid gap-3">
          {tfEntries.map(([tf, res]) => (
            <div key={tf} className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-3">
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">{tf}{res.price != null ? ` · ${fmtNum(res.price, 4)}` : ''}</p>
              {res.error != null ? (
                <p className="mt-1 text-xs text-slate-500">Unavailable — {String(res.error)}</p>
              ) : (
                <>
                  <p className="mt-1 text-sm text-slate-300">
                    {HUNT_STATUS_BADGE[String(res.hunt_status ?? 'LOW_RISK')] ?? String(res.hunt_status ?? '—')}
                    {res.atr != null ? ` · ATR ${fmtNum(res.atr, 4)}` : ''}
                  </p>
                  {((res.reasons as string[]) ?? []).map((rr, i) => <p key={i} className="mt-1 text-xs text-slate-500">· {mdBold(rr)}</p>)}
                  <StopHuntScenario label="If LONG" stops={res.long_stops as Row} />
                  <StopHuntScenario label="If SHORT" stops={res.short_stops as Row} />
                </>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function TakeProfitPanel({ data }: { data: Row }) {
  const results = (data.results as Row[]) ?? []
  const [idx, setIdx] = useState(0)
  const r = results[idx] ?? results[0] ?? {}
  const perTf = (r.per_tf as Record<string, Row>) ?? {}
  const tfEntries = Object.entries(perTf)
  if (!results.length) return <p className="text-sm text-slate-500">No results.</p>

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {results.map((res, i) => (
          <Chip key={`${String(res.ticker)}-${i}`} selected={idx === i} onClick={() => setIdx(i)}>
            {String(res.ticker)}
          </Chip>
        ))}
      </div>

      {!tfEntries.length ? (
        <Alert type="error">{String(r.error ?? 'No results.')}</Alert>
      ) : (
        <div className="grid gap-3">
          {tfEntries.map(([tf, res]) => (
            <div key={tf} className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-3">
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">{tf}{res.price != null ? ` · ${fmtNum(res.price, 4)}` : ''}</p>
              {res.error != null ? (
                <p className="mt-1 text-xs text-slate-500">Unavailable — {String(res.error)}</p>
              ) : (
                <>
                  <p className="mt-1 text-sm text-slate-300">
                    {TP_STATUS_BADGE[String(res.tp_status ?? 'LOW_CONFLUENCE')] ?? String(res.tp_status ?? '—')}
                    {res.atr != null ? ` · ATR ${fmtNum(res.atr, 4)}` : ''}
                  </p>
                  {((res.reasons as string[]) ?? []).map((rr, i) => <p key={i} className="mt-1 text-xs text-slate-500">· {rr}</p>)}
                  <TakeProfitScenario label="If LONG" targets={res.long_targets as Row} />
                  <TakeProfitScenario label="If SHORT" targets={res.short_targets as Row} />
                </>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

const REAL_BOTTOM_STATUS_ORDER = ['CONFIRMED_ENTRY', 'PENDING_ENTRY', 'TRAP_CONFIRMED', 'TRAP_UNCONFIRMED', 'NO_SETUP']

function RealBottomTickerRow({ res }: { res: Row }) {
  const [open, setOpen] = useState(false)
  const priceStr = res.price != null ? fmtNum(res.price, 4) : '—'
  const entryZone = res.entry_zone as Row | undefined
  const stopLoss = res.stop_loss as Row | undefined
  const target = res.target as Row | undefined
  return (
    <div className="rounded-lg border border-slate-800/60 bg-slate-900/40">
      <button
        type="button"
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-slate-300 hover:bg-slate-800/30"
        onClick={() => setOpen((o) => !o)}
      >
        {open ? <ChevronDown size={14} className="shrink-0 text-slate-500" /> : <ChevronRight size={14} className="shrink-0 text-slate-500" />}
        <span className="font-semibold text-white">{String(res.ticker)}</span>
        <span className="text-slate-500">· {priceStr}{res.atr != null ? ` · ATR ${fmtNum(res.atr, 4)}` : ''}</span>
        <span className="ml-auto" onClick={(e) => e.stopPropagation()}>
          <AddToWatchlistButton ticker={String(res.ticker ?? '')} compact />
        </span>
      </button>
      {open && (
        <div className="border-t border-slate-800/60 px-3 py-2">
          {((res.reasons as string[]) ?? []).map((rr, i) => <p key={i} className="text-xs text-slate-500">· {rr}</p>)}
          <div className="mt-2 grid gap-3 sm:grid-cols-3">
            <div>
              <p className="text-xs font-semibold text-slate-300">Entry Zone</p>
              {entryZone ? (
                <p className="text-xs text-slate-400">{fmtNum(entryZone.bottom, 4)} – {fmtNum(entryZone.top, 4)}</p>
              ) : (
                <p className="text-xs text-slate-500">Not yet formed.</p>
              )}
            </div>
            <div>
              <p className="text-xs font-semibold text-slate-300">Stop-Loss</p>
              {stopLoss ? (
                <p className="text-xs text-slate-400">{fmtNum(stopLoss.price, 4)} ({fmtNum(stopLoss.pct, 2)}%) — below the trap low</p>
              ) : (
                <p className="text-xs text-slate-500">No trap detected yet.</p>
              )}
            </div>
            <div>
              <p className="text-xs font-semibold text-slate-300">Target</p>
              {target ? (
                <p className="text-xs text-slate-400">{fmtNum(target.price, 4)} ({fmtNum(target.pct, 2)}%) — next resistance</p>
              ) : (
                <p className="text-xs text-slate-500">No resistance level found.</p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function RealBottomPanel({ data }: { data: Row }) {
  const results = (data.results as Row[]) ?? []
  const timeframes = (data.timeframes as string[]) ?? []
  const [tf, setTf] = useState(timeframes[0] ?? '')
  const activeTf = timeframes.includes(tf) ? tf : timeframes[0] ?? ''
  if (!results.length) return <p className="text-sm text-slate-500">No results.</p>

  const tfResults = results.map((r) => {
    const perTf = (r.per_tf as Record<string, Row>) ?? {}
    return perTf[activeTf] ?? { ticker: r.ticker, error: 'No data for this timeframe.' }
  })
  const errored = tfResults.filter((r) => r.error != null)
  const valid = tfResults.filter((r) => r.error == null)
  const buckets: Record<string, Row[]> = { CONFIRMED_ENTRY: [], PENDING_ENTRY: [], TRAP_CONFIRMED: [], TRAP_UNCONFIRMED: [], NO_SETUP: [] }
  for (const r of valid) {
    const status = String(r.status ?? 'NO_SETUP')
    ;(buckets[status] ?? buckets.NO_SETUP).push(r)
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-400">{results.length} ticker(s) analyzed across {timeframes.length} timeframe(s)</p>

      <div className="flex flex-wrap gap-2">
        {timeframes.map((t) => (
          <Chip key={t} selected={activeTf === t} onClick={() => setTf(t)}>{t}</Chip>
        ))}
      </div>

      {errored.length > 0 && (
        <Alert type="error">
          {errored.map((r) => `${String(r.ticker)}: ${String(r.error)}`).join(' · ')}
        </Alert>
      )}

      <div className="grid gap-4">
        {REAL_BOTTOM_STATUS_ORDER.map((status) => {
          const items = buckets[status] ?? []
          return (
            <div key={status} className="min-w-0">
              <p className="text-sm font-semibold text-slate-300">
                {REAL_BOTTOM_STATUS_BADGE[status] ?? status} — {items.length}
              </p>
              <p className="mb-2 text-xs text-slate-500">👉 {REAL_BOTTOM_STATUS_ACTION[status] ?? ''}</p>
              {items.length === 0 ? (
                <p className="text-xs text-slate-500">None.</p>
              ) : (
                <div className="space-y-1.5">
                  {items.map((r, i) => <RealBottomTickerRow key={i} res={r} />)}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

const WEAK_STRONG_BADGE: Record<string, string> = {
  STRONG: '🟢 Strong',
  WEAK: '🔴 Weak',
  NEUTRAL: '⚪ Neutral',
}

function WeakStrongPlaybookCard({ label, plan }: { label: string; plan: Row | undefined }) {
  if (!plan) return null
  const take = Boolean(plan.take_trade)
  return (
    <div className="rounded-lg border border-slate-800/60 bg-slate-900/30 p-2.5">
      <p className="text-xs font-semibold text-slate-300">{label}</p>
      <p className={`text-xs ${verdictClass(String(plan.verdict ?? ''))}`}>
        {String(plan.verdict ?? '—')} · {fmtNum(plan.confidence_pct, 0)}% confidence
      </p>
      {take ? (
        <p className="mt-1 text-xs text-slate-400">
          Entry: <strong>{fmtNum(plan.entry_price, 4)}</strong>
          {' · '}Stop: <strong>{fmtNum(plan.stop_price, 4)}</strong>
          {' · '}Target: <strong>{fmtNum(plan.target_price, 4)}</strong>
          {plan.rr_ratio != null ? ` · R:R ${fmtNum(plan.rr_ratio, 2)}` : ''}
        </p>
      ) : (
        <p className="mt-1 text-xs text-slate-500">
          {String(plan.hold_duration ?? '')}
          {((plan.reasons as string[]) ?? []).slice(-1).map((rr, i) => <span key={i}> — {rr}</span>)}
        </p>
      )}
    </div>
  )
}

function WeakStrongResultRow({ res, compact = false }: { res: Row; compact?: boolean }) {
  const [open, setOpen] = useState(false)
  const meta = (
    <>
      {String(res.timeframe)} · {WEAK_STRONG_BADGE[String(res.verdict ?? 'NEUTRAL')] ?? String(res.verdict ?? '—')}
      {' · score '}{fmtNum(res.score, 0)}{' · '}{fmtNum(res.confidence_pct, 0)}% confidence
      {res.rel_pct != null ? ` · RS ${fmtNum(res.rel_pct, 1)}%` : ''}
      {res.vol_ratio != null ? ` · vol ${fmtNum(res.vol_ratio, 1)}x` : ''}
    </>
  )
  return (
    <div className="rounded-lg border border-slate-800/60 bg-slate-900/40">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={compact
          ? 'flex w-full flex-col gap-1 px-3 py-2 text-left text-xs text-slate-300 hover:bg-slate-800/30'
          : 'flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-slate-300 hover:bg-slate-800/30'}
      >
        {compact ? (
          <>
            <span className="flex items-center gap-1.5">
              {open ? <ChevronDown size={14} className="shrink-0 text-slate-500" /> : <ChevronRight size={14} className="shrink-0 text-slate-500" />}
              <span className="font-semibold text-white">{String(res.ticker)}</span>
              <span onClick={(e) => e.stopPropagation()}>
                <AddToWatchlistButton ticker={String(res.ticker ?? '')} compact />
              </span>
            </span>
            <span className="text-slate-500 leading-snug">{meta}</span>
          </>
        ) : (
          <>
            {open ? <ChevronDown size={14} className="shrink-0 text-slate-500" /> : <ChevronRight size={14} className="shrink-0 text-slate-500" />}
            <span className="font-semibold text-white">{String(res.ticker)}</span>
            <span className="text-slate-500">· {meta}</span>
            <span className="ml-auto" onClick={(e) => e.stopPropagation()}>
              <AddToWatchlistButton ticker={String(res.ticker ?? '')} compact />
            </span>
          </>
        )}
      </button>
      {open && (
        <div className="border-t border-slate-800/60 px-3 py-2">
          {((res.reasons as string[]) ?? []).map((rr, i) => <p key={i} className="text-xs text-slate-500">· {rr}</p>)}
          <div className={compact ? 'mt-2 space-y-2' : 'mt-2 grid gap-2 sm:grid-cols-2'}>
            <WeakStrongPlaybookCard label="🎯 Scalping" plan={res.scalp_plan as Row | undefined} />
            <WeakStrongPlaybookCard label="📈 Swing" plan={res.swing_plan as Row | undefined} />
          </div>
          <AskAIPanel
            context={buildAskContext(`Weak / Strong · ${String(res.ticker ?? '')} · ${String(res.timeframe ?? '')}`, res)}
            section={`command-center/weak_strong/${String(res.ticker ?? '')}`}
            className="mt-3"
          />
        </div>
      )}
    </div>
  )
}

function WeakStrongPanel({ data }: { data: Row }) {
  const strong = (data.strong as Row[]) ?? []
  const weak = (data.weak as Row[]) ?? []
  const neutral = (data.neutral as Row[]) ?? []
  const errors = (data.errors as Row[]) ?? []
  if (!strong.length && !weak.length && !neutral.length && !errors.length) {
    return <p className="text-sm text-slate-500">No results.</p>
  }

  return (
    <div className="space-y-4">
      {errors.length > 0 && (
        <Alert type="error">
          {errors.map((e) => `${String(e.ticker)} · ${String(e.timeframe)}: ${String(e.error)}`).join(' · ')}
        </Alert>
      )}

      <p className="text-xs text-amber-500/80">
        Calibration check (walk-forward, 15 India stocks, ~6,400 signals, ATR-scaled target/stop): confidence
        showed no meaningful difference in realized win rate between its highest bucket (50.0%) and the bulk
        of the distribution (~49–51%) — treat the score as a rough directional lean, not a validated
        probability, until it's been recalibrated.
      </p>

      <div>
        <p className="mb-2 text-sm font-semibold text-slate-300">🟢 Strong — {strong.length}</p>
        {strong.length === 0 ? <p className="text-xs text-slate-500">None.</p> : (
          <div className="space-y-1.5">{strong.map((r, i) => <WeakStrongResultRow key={i} res={r} />)}</div>
        )}
      </div>

      <div>
        <p className="mb-2 text-sm font-semibold text-slate-300">🔴 Weak — {weak.length}</p>
        {weak.length === 0 ? <p className="text-xs text-slate-500">None.</p> : (
          <div className="space-y-1.5">{weak.map((r, i) => <WeakStrongResultRow key={i} res={r} />)}</div>
        )}
      </div>

      <div>
        <p className="mb-2 text-sm font-semibold text-slate-300">⚪ Neutral / mixed — {neutral.length}</p>
        {neutral.length === 0 ? <p className="text-xs text-slate-500">None.</p> : (
          <div className="space-y-1.5">{neutral.map((r, i) => <WeakStrongResultRow key={i} res={r} />)}</div>
        )}
      </div>
    </div>
  )
}

function CopyTradeResultRow({ res }: { res: Row }) {
  const [open, setOpen] = useState(false)
  const live = (res.live as Row) ?? {}
  return (
    <div className="rounded-lg border border-slate-800/60 bg-slate-900/40">
      <button
        type="button"
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-slate-300 hover:bg-slate-800/30"
        onClick={() => setOpen((o) => !o)}
      >
        {open ? <ChevronDown size={14} className="shrink-0 text-slate-500" /> : <ChevronRight size={14} className="shrink-0 text-slate-500" />}
        <span className="font-semibold text-white">{String(res.ticker)}</span>
        <span className="text-slate-500">
          · {COPY_TRADE_PHASE_BADGE[String(res.phase ?? 'NO_SETUP')] ?? String(res.phase ?? '—')}
          {' · '}{String(live.verdict ?? 'WAIT')}
          {' · '}{fmtNum(live.confidence_pct, 0)}% confidence
          {' · %K '}{fmtNum(res.stoch_k, 1)}
          {' · vol '}{fmtNum(res.vol_ratio, 1)}x
        </span>
        <span className="ml-auto" onClick={(e) => e.stopPropagation()}>
          <AddToWatchlistButton ticker={String(res.ticker ?? '')} compact />
        </span>
      </button>
      {open && (
        <div className="border-t border-slate-800/60 px-3 py-2">
          {((live.reasons as string[]) ?? []).map((rr, i) => <p key={i} className="text-xs text-slate-500">· {rr}</p>)}
          {live.entry_price != null && (
            <p className="mt-1 text-xs text-slate-400">
              Entry: <strong>{fmtNum(live.entry_price, 4)}</strong>
              {' · '}Stop: <strong>{fmtNum(live.stop_price, 4)}</strong> ({fmtNum(live.sl_pct, 2)}%)
              {' · '}Target: <strong>{fmtNum(live.target_price, 4)}</strong> ({fmtNum(live.tp_pct, 2)}%)
            </p>
          )}
          <AskAIPanel
            context={buildAskContext(`Copy Trade · ${String(res.ticker ?? '')}`, res)}
            section={`command-center/copy_trade/${String(res.ticker ?? '')}`}
            className="mt-3"
          />
        </div>
      )}
    </div>
  )
}

function CopyTradePanel({ data }: { data: Row }) {
  const entries = (data.entries as Row[]) ?? []
  const watches = (data.watchlist as Row[]) ?? []
  const results = (data.results as Row[]) ?? []
  const errors = results.filter((r) => r.error != null)
  if (!entries.length && !watches.length && !errors.length) {
    return <p className="text-sm text-slate-500">No results.</p>
  }

  return (
    <div className="space-y-4">
      {errors.length > 0 && (
        <Alert type="error">
          {errors.map((e) => `${String(e.ticker)}: ${String(e.error)}`).join(' · ')}
        </Alert>
      )}

      <div>
        <p className="mb-2 text-sm font-semibold text-slate-300">🎯 Fresh momentum entries — {entries.length}</p>
        {entries.length === 0 ? <p className="text-xs text-slate-500">None.</p> : (
          <div className="space-y-1.5">{entries.map((r, i) => <CopyTradeResultRow key={i} res={r} />)}</div>
        )}
      </div>

      <div>
        <p className="mb-2 text-sm font-semibold text-slate-300">👁️ Watching zone / exit cues — {watches.length}</p>
        {watches.length === 0 ? <p className="text-xs text-slate-500">None.</p> : (
          <div className="space-y-1.5">{watches.map((r, i) => <CopyTradeResultRow key={i} res={r} />)}</div>
        )}
      </div>
    </div>
  )
}

function Sma20200ResultRow({ res, assetClass }: { res: Row; assetClass: string }) {
  const [open, setOpen] = useState(false)
  const live = (res.live as Row) ?? {}
  return (
    <div className="rounded-lg border border-slate-800/60 bg-slate-900/40">
      <button
        type="button"
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-slate-300 hover:bg-slate-800/30"
        onClick={() => setOpen((o) => !o)}
      >
        {open ? <ChevronDown size={14} className="shrink-0 text-slate-500" /> : <ChevronRight size={14} className="shrink-0 text-slate-500" />}
        <span className="font-semibold text-white">{String(res.ticker)}</span>
        <span className="text-slate-500">
          · {String(res.timeframe)}
          {' · '}{String(live.verdict ?? 'WAIT')}
          {' · '}{fmtNum(live.confidence_pct, 0)}% confidence
          {' · price '}{fmtNum(res.price, 4)}
        </span>
        <span className="ml-auto" onClick={(e) => e.stopPropagation()}>
          <AddToWatchlistButton ticker={String(res.ticker ?? '')} compact />
        </span>
      </button>
      {open && (
        <div className="border-t border-slate-800/60 px-3 py-2">
          <p className="text-xs text-slate-400">
            Price <strong>{fmtNum(res.price, 4)}</strong> · 20 SMA <strong>{fmtNum(live.sma_fast, 4)}</strong> ·{' '}
            200 SMA <strong>{fmtNum(live.sma_slow, 4)}</strong> · signals in window: <strong>{String(res.signal_count ?? 0)}</strong>
          </p>
          {(res.day_high != null || res.day_low != null) && (
            <p className="mt-1 text-xs text-slate-400">
              Day High <strong>{fmtNum(res.day_high, 4)}</strong> · Day Low <strong>{fmtNum(res.day_low, 4)}</strong>
            </p>
          )}
          <DayBiasNote bias={res.day_bias as Row | undefined} className="mt-1 text-xs text-slate-400" showReasons />
          <DayBiasRecalculator
            ticker={String(res.ticker ?? '')} assetClass={assetClass}
            defaultTimeframe={String(res.timeframe ?? '1d')} showReasons
          />
          {((live.reasons as string[]) ?? []).map((rr, i) => <p key={i} className="mt-1 text-xs text-slate-500">· {rr}</p>)}
          {live.entry_price != null && (
            <p className="mt-1 text-xs text-slate-400">
              Entry: <strong>{fmtNum(live.entry_price, 4)}</strong>
              {' · '}Stop: <strong>{fmtNum(live.stop_price, 4)}</strong> ({fmtNum(live.sl_pct, 2)}%)
              {' · '}Target: <strong>{fmtNum(live.target_price, 4)}</strong> ({fmtNum(live.tp_pct, 2)}%)
            </p>
          )}
          <AskAIPanel
            context={buildAskContext(`200SMA-20SMA · ${String(res.ticker ?? '')} · ${String(res.timeframe ?? '')}`, res)}
            section={`command-center/sma_20_200/${String(res.ticker ?? '')}`}
            className="mt-3"
          />
        </div>
      )}
    </div>
  )
}

function Sma20200Panel({ data, assetClass }: { data: Row; assetClass: string }) {
  const long = (data.long as Row[]) ?? []
  const short = (data.short as Row[]) ?? []
  const wait = (data.wait as Row[]) ?? []
  const errors = (data.errors as Row[]) ?? []
  if (!long.length && !short.length && !wait.length && !errors.length) {
    return <p className="text-sm text-slate-500">No results.</p>
  }

  return (
    <div className="space-y-4">
      {errors.length > 0 && (
        <Alert type="error">
          {errors.map((e) => `${String(e.ticker)} · ${String(e.timeframe)}: ${String(e.error)}`).join(' · ')}
        </Alert>
      )}

      <div>
        <p className="mb-2 text-sm font-semibold text-slate-300">🟢 Long — {long.length}</p>
        {long.length === 0 ? <p className="text-xs text-slate-500">Nothing on a live bounce right now.</p> : (
          <div className="space-y-1.5">{long.map((r, i) => <Sma20200ResultRow key={i} res={r} assetClass={assetClass} />)}</div>
        )}
      </div>

      <div>
        <p className="mb-2 text-sm font-semibold text-slate-300">🔴 Short — {short.length}</p>
        {short.length === 0 ? <p className="text-xs text-slate-500">Nothing on a live rejection right now.</p> : (
          <div className="space-y-1.5">{short.map((r, i) => <Sma20200ResultRow key={i} res={r} assetClass={assetClass} />)}</div>
        )}
      </div>

      {wait.length > 0 && (
        <details className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-2.5">
          <summary className="cursor-pointer text-sm font-semibold text-slate-300">⚪ No fresh trigger — {wait.length}</summary>
          <div className="mt-2 space-y-1.5">{wait.map((r, i) => <Sma20200ResultRow key={i} res={r} assetClass={assetClass} />)}</div>
        </details>
      )}
    </div>
  )
}

function TakeTradeVotesTable({ votes }: { votes: Row[] }) {
  const { sorted, sortKey, sortDir, handleSort } = useSort(votes, {
    engine: (v) => String(v.engine ?? ''),
    direction: (v) => String(v.direction ?? ''),
    confidence: (v) => (v.confidence != null ? Number(v.confidence) : null),
    take: (v) => (v.take ? 1 : 0),
    agreed: (v) => (v.agreed ? 1 : v.direction === 'WAIT' ? 0 : -1),
    note: (v) => (v.error != null ? String(v.error) : String(((v.reasons as string[]) ?? [])[0] ?? '')),
  })
  if (!votes.length) return null
  return (
    <div>
      <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">📋 Per-analysis vote breakdown</h4>
      <DataTable minWidth={720}>
        <thead>
          <tr>
            <SortableTh active={sortKey === 'engine'} direction={sortDir} onSort={() => handleSort('engine')}>Engine</SortableTh>
            <SortableTh active={sortKey === 'direction'} direction={sortDir} onSort={() => handleSort('direction')}>Direction</SortableTh>
            <SortableTh active={sortKey === 'take'} direction={sortDir} onSort={() => handleSort('take')}>Take</SortableTh>
            <SortableTh active={sortKey === 'agreed'} direction={sortDir} onSort={() => handleSort('agreed')}>Agreed</SortableTh>
            <SortableTh active={sortKey === 'confidence'} direction={sortDir} onSort={() => handleSort('confidence')}>Confidence</SortableTh>
            <SortableTh active={sortKey === 'note'} direction={sortDir} onSort={() => handleSort('note')}>Note</SortableTh>
          </tr>
        </thead>
        <tbody>
          {sorted.map((v, i) => (
            <tr key={i}>
              <Td>{String(v.engine ?? '—')}</Td>
              <Td className={verdictClass(String(v.direction ?? ''))}>{String(v.direction ?? '—')}</Td>
              <Td>{v.take ? '✅' : '—'}</Td>
              <Td>{v.agreed ? '✅' : (v.direction === 'WAIT' ? '⚪' : '❌')}</Td>
              <Td>{v.confidence != null ? `${fmtNum(v.confidence, 0)}%` : '—'}</Td>
              <Td className="max-w-xs truncate text-slate-400">
                {v.error != null ? String(v.error) : String(((v.reasons as string[]) ?? [])[0] ?? '')}
              </Td>
            </tr>
          ))}
        </tbody>
      </DataTable>
    </div>
  )
}

const TAKE_TRADE_DIRECTION_LABEL: Record<string, string> = {
  LONG: '🟢 BUY',
  SHORT: '🔴 SELL',
  WAIT: '⚪ WAIT',
}

function TakeTradePanel({ data }: { data: Row }) {
  const results = (data.results as Row[]) ?? []
  const [idx, setIdx] = useState(0)
  const r = results[idx] ?? results[0] ?? {}
  const perTf = (r.per_tf as Record<string, Row>) ?? {}
  const tfEntries = Object.entries(perTf)
  if (!results.length) return <p className="text-sm text-slate-500">No results.</p>
  const takeTradeAiContext = tfEntries.length ? buildAskContext(`Take Trade · ${String(r.ticker ?? '')}`, r) : ''

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {results.map((res, i) => (
          <Chip key={`${String(res.ticker)}-${i}`} selected={idx === i} onClick={() => setIdx(i)}>
            {String(res.ticker)}
          </Chip>
        ))}
      </div>

      {!tfEntries.length ? (
        <Alert type="error">{String(r.error ?? 'No results.')}</Alert>
      ) : (
        <div className="grid gap-4">
          {tfEntries.map(([tf, res]) => {
            const stop = res.stop as Row | undefined
            const target = res.target as Row | undefined
            return (
              <div key={tf} className="rounded-2xl border border-slate-800/80 bg-slate-900/40 p-4">
                <p className="text-xs font-medium uppercase tracking-wider text-slate-500">{tf}{res.price != null ? ` · ${fmtNum(res.price, 4)}` : ''}</p>
                {res.error != null ? (
                  <p className="mt-1 text-xs text-slate-500">Unavailable — {String(res.error)}</p>
                ) : (
                  <>
                    <p className={`mt-1 text-xl font-bold ${verdictClass(String(res.verdict ?? ''))}`}>
                      {TAKE_TRADE_DIRECTION_LABEL[String(res.direction ?? 'WAIT')] ?? String(res.verdict ?? '—')} · {String(res.verdict ?? '—')}
                    </p>
                    <p className="mt-1 text-sm text-slate-300">
                      {fmtNum(res.confidence_pct, 0)}% confidence ({fmtNum(res.n_agree, 0)}/{fmtNum(res.n_total, 0)} agree, need {fmtNum(res.min_agree_required, 0)}+ at {fmtNum(res.take_threshold, 0)}%+)
                    </p>
                    {((res.context_notes as string[]) ?? []).map((rr, i) => <p key={i} className="mt-1 text-xs text-slate-500">{rr}</p>)}
                    {((res.reasons as string[]) ?? []).map((rr, i) => <p key={i} className="mt-1 text-xs text-slate-500">· {mdBold(rr)}</p>)}

                    {stop && (
                      <div className="mt-3">
                        <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">🛡️ Stop Loss{stop.hunt_status != null ? ` · ${HUNT_STATUS_BADGE[String(stop.hunt_status)] ?? String(stop.hunt_status)}` : ''}</p>
                        <p className="text-xs text-slate-500">Anchored on {String(stop.anchor_label ?? 'nearby structure')}.</p>
                        <StopTierRow label="🛡️ Recommended (Safe)" tier={stop.recommended as Row} />
                        <StopTierRow label="🎯 Aggressive (Tight)" tier={stop.aggressive as Row} />
                      </div>
                    )}
                    {target && (
                      <div className="mt-3">
                        <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">🎯 Take Profit{target.tp_status != null ? ` · ${TP_STATUS_BADGE[String(target.tp_status)] ?? String(target.tp_status)}` : ''}</p>
                        <p className="text-xs text-slate-500">Anchored on {String(target.anchor_label ?? 'nearby structure')}.</p>
                        <TargetTierRow label="Recommended (TP1)" tier={target.recommended as Row} />
                        <TargetTierRow label="Extended (TP2)" tier={target.extended as Row} />
                      </div>
                    )}

                    <div className="mt-3">
                      <TakeTradeVotesTable votes={(res.votes as Row[]) ?? []} />
                    </div>
                  </>
                )}
              </div>
            )
          })}
        </div>
      )}

      {takeTradeAiContext && (
        <AskAIPanel context={takeTradeAiContext} section={`command-center/take_trade/${String(r.ticker ?? '')}`} />
      )}
    </div>
  )
}

const PATTERN_BIAS_ORDER = ['BULLISH', 'BEARISH', 'NEUTRAL']
const PATTERN_BIAS_LABEL: Record<string, string> = {
  BULLISH: '🟢 Bullish',
  BEARISH: '🔴 Bearish',
  NEUTRAL: '⚪ Neutral / Mixed',
}

function PatternTickerRow({ res }: { res: Row }) {
  const [open, setOpen] = useState(false)
  const nBull = ((res.bullish_patterns as Row[]) ?? []).length
  const nBear = ((res.bearish_patterns as Row[]) ?? []).length
  const priceStr = res.price != null ? fmtNum(res.price, 2) : '—'
  return (
    <div className="rounded-lg border border-slate-800/60 bg-slate-900/40">
      <button
        type="button"
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-slate-300 hover:bg-slate-800/30"
        onClick={() => setOpen((o) => !o)}
      >
        {open ? <ChevronDown size={14} className="shrink-0 text-slate-500" /> : <ChevronRight size={14} className="shrink-0 text-slate-500" />}
        <span className="font-semibold text-white">{String(res.ticker)}</span>
        <span className="text-slate-500">· {priceStr} · {fmtNum(res.confidence_pct, 0)}% confidence · 🟢{nBull} / 🔴{nBear} pattern(s)</span>
        <span className="ml-auto" onClick={(e) => e.stopPropagation()}>
          <AddToWatchlistButton ticker={String(res.ticker ?? '')} compact />
        </span>
      </button>
      {open && (
        <div className="border-t border-slate-800/60 px-3 py-2">
          {((res.reasons as string[]) ?? []).map((rr, i) => <p key={i} className="text-xs text-slate-500">· {mdBold(rr)}</p>)}
        </div>
      )}
    </div>
  )
}

function PatternsPanel({ data }: { data: Row }) {
  const results = (data.results as Row[]) ?? []
  const timeframes = (data.timeframes as string[]) ?? []
  const [tf, setTf] = useState(timeframes[0] ?? '')
  const activeTf = timeframes.includes(tf) ? tf : timeframes[0] ?? ''
  if (!results.length) return <p className="text-sm text-slate-500">No results.</p>

  const tfResults = results.map((r) => {
    const perTf = (r.per_tf as Record<string, Row>) ?? {}
    return perTf[activeTf] ?? { ticker: r.ticker, error: 'No data for this timeframe.' }
  })
  const errored = tfResults.filter((r) => r.error != null)
  const valid = tfResults.filter((r) => r.error == null)
  const buckets: Record<string, Row[]> = { BULLISH: [], BEARISH: [], NEUTRAL: [] }
  for (const r of valid) {
    const bias = String(r.bias ?? 'NEUTRAL')
    ;(buckets[bias] ?? buckets.NEUTRAL).push(r)
  }
  for (const bias of PATTERN_BIAS_ORDER) buckets[bias].sort((a, b) => Number(b.confidence_pct ?? 0) - Number(a.confidence_pct ?? 0))

  return (
    <div className="space-y-4">
      <p className="text-sm font-semibold uppercase tracking-wider text-slate-400">
        {results.length} ticker(s) analyzed across {timeframes.length} timeframe(s)
      </p>
      <div className="flex flex-wrap gap-2">
        {timeframes.map((t) => (
          <Chip key={t} selected={activeTf === t} onClick={() => setTf(t)}>{t}</Chip>
        ))}
      </div>

      {errored.length > 0 && (
        <Alert type="error">{errored.map((r) => `${String(r.ticker)}: ${String(r.error)}`).join(' · ')}</Alert>
      )}

      <div className="space-y-4">
        {PATTERN_BIAS_ORDER.map((bias) => (
          <div key={bias}>
            <p className="mb-2 text-sm font-semibold text-white">{PATTERN_BIAS_LABEL[bias]} — {buckets[bias].length}</p>
            {buckets[bias].length === 0 ? (
              <p className="text-xs text-slate-500">None.</p>
            ) : (
              <div className="space-y-2">
                {buckets[bias].map((r, i) => <PatternTickerRow key={`${String(r.ticker)}-${i}`} res={r} />)}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function EmaPositionPanel({ data, showCharts = false }: { data: Row; showCharts?: boolean }) {
  const results = (data.results as Row[]) ?? []
  const [idx, setIdx] = useState(0)
  const [chartType, setChartType] = useState<'candles' | 'line'>('candles')
  const r = results[idx] ?? results[0] ?? {}
  const emaSummary = (r.ema_summary as Row[]) ?? []
  const { sorted: sortedEmaSummary, sortKey: emaSortKey, sortDir: emaSortDir, handleSort: handleEmaSort } = useSort(emaSummary, {
    ema: (e) => (e.ema_period != null ? Number(e.ema_period) : null),
    status_from: (e) => String(e.status_from ?? ''),
    status_to: (e) => String(e.status_to ?? ''),
    verdict: (e) => String(e.verdict_label ?? e.verdict ?? ''),
    crossings: (e) => (e.crossover_count != null ? Number(e.crossover_count) : null),
    ema_value: (e) => (e.ema_value_now != null ? Number(e.ema_value_now) : null),
    dist: (e) => (e.distance_pct != null ? Number(e.distance_pct) : null),
  })
  if (!results.length) return <p className="text-sm text-slate-500">No results.</p>
  const action = (r.actionability as Row) ?? {}
  const combo = r.fundamentals_combo as Row | undefined
  const ns = r.next_support as Row | undefined
  const nr = r.next_resistance as Row | undefined

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {results.map((res, i) => (
          <Chip key={`${String(res.ticker)}-${String(res.timeframe)}-${i}`} selected={idx === i} onClick={() => setIdx(i)}>
            {String(res.ticker)} · {String(res.timeframe ?? '')}
          </Chip>
        ))}
      </div>

      {r.error ? (
        <Alert type="error">{String(r.error)}</Alert>
      ) : (
        <>
          <div className="rounded-2xl border border-slate-800/80 bg-slate-900/40 px-4 py-5 sm:px-6">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs font-medium uppercase tracking-wider text-slate-500">
                EMA Position · {String(r.ticker)} · {String(r.timeframe ?? '')}
              </p>
              <AddToWatchlistButton ticker={String(r.ticker ?? '')} compact />
            </div>
            <p className={`mt-1 text-xl font-bold sm:text-2xl ${verdictClass(String(action.bucket ?? ''))}`}>
              {String(action.bucket ?? '—')}{action.direction != null ? ` · ${String(action.direction)}` : ''}
            </p>
            {r.note != null && String(r.note).trim() !== '' && (
              <p className="mt-2 text-sm text-amber-300">{String(r.note)}</p>
            )}
            {action.reason != null && (
              <p className="mt-2 text-sm text-slate-300"><strong>Verdict:</strong> {String(action.reason)}</p>
            )}
            {combo && (
              <div className="mt-2 text-sm text-slate-400">
                <p>{String(combo.note ?? '')}</p>
                <p className="text-xs text-slate-500">Technical-only confidence was {fmtNum(r.technical_confidence_pct, 0)}%.</p>
              </div>
            )}
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <StatCard label="Last price" value={fmtNum(r.last_price, 4)} />
            <StatCard label="Next support" value={ns ? fmtNum(ns.price, 4) : '—'} />
            <StatCard label="Next resistance" value={nr ? fmtNum(nr.price, 4) : '—'} />
          </div>

          {showCharts && Boolean((r.chart_data as SRChartBar[] | undefined)?.length) && (
            <div className="rounded-2xl border border-slate-800/80 bg-slate-900/40 p-4">
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <span className="text-xs text-slate-500">Chart:</span>
                <Chip selected={chartType === 'candles'} onClick={() => setChartType('candles')}>Candlestick</Chip>
                <Chip selected={chartType === 'line'} onClick={() => setChartType('line')}>Line</Chip>
              </div>
              <SupportResistanceChart
                chartData={r.chart_data as SRChartBar[]}
                supportZone={(r.support_zone as [number, number] | null | undefined) ?? null}
                resistanceZone={(r.resistance_zone as [number, number] | null | undefined) ?? null}
                trendlines={[]}
                lastClose={r.last_price as number | undefined}
                emas={r.emas as Record<string, Array<{ time: string; value: number }>> | undefined}
                chartType={chartType}
              />
            </div>
          )}

          {emaSummary.length > 0 && (
            <div>
              <h4 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">EMA breakdown</h4>
              <DataTable minWidth={720}>
                <thead>
                  <tr>
                    <SortableTh active={emaSortKey === 'ema'} direction={emaSortDir} onSort={() => handleEmaSort('ema')}>EMA</SortableTh>
                    <SortableTh active={emaSortKey === 'verdict'} direction={emaSortDir} onSort={() => handleEmaSort('verdict')}>Verdict</SortableTh>
                    <SortableTh active={emaSortKey === 'status_from'} direction={emaSortDir} onSort={() => handleEmaSort('status_from')}>Status@From</SortableTh>
                    <SortableTh active={emaSortKey === 'status_to'} direction={emaSortDir} onSort={() => handleEmaSort('status_to')}>Status@To</SortableTh>
                    <SortableTh active={emaSortKey === 'dist'} direction={emaSortDir} onSort={() => handleEmaSort('dist')}>Dist %</SortableTh>
                    <SortableTh active={emaSortKey === 'crossings'} direction={emaSortDir} onSort={() => handleEmaSort('crossings')}># Crossings</SortableTh>
                    <SortableTh active={emaSortKey === 'ema_value'} direction={emaSortDir} onSort={() => handleEmaSort('ema_value')}>EMA value now</SortableTh>
                  </tr>
                </thead>
                <tbody>
                  {sortedEmaSummary.map((e, i) => (
                    <tr key={i}>
                      <Td>{String(e.ema_period)}</Td>
                      <Td className={verdictClass(String(e.verdict ?? ''))}>{String(e.verdict_label ?? e.verdict ?? '—')}</Td>
                      <Td>{String(e.status_from ?? '—')}</Td>
                      <Td>{String(e.status_to ?? '—')}</Td>
                      <Td>{fmtNum(e.distance_pct)}</Td>
                      <Td>{String(e.crossover_count ?? 0)}</Td>
                      <Td>{fmtNum(e.ema_value_now, 4)}</Td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            </div>
          )}
        </>
      )}
    </div>
  )
}

const BUCKET_ORDER = ['Extended Overbought', 'Overbought', 'Neutral', 'Oversold', 'Extended Oversold']

const BUCKET_CLASS: Record<string, string> = {
  'Extended Overbought': 'border-rose-500/40 bg-rose-500/10 text-rose-300',
  Overbought: 'border-rose-500/25 bg-rose-500/5 text-rose-300',
  Neutral: 'border-slate-700/60 bg-slate-800/30 text-slate-400',
  Oversold: 'border-emerald-500/25 bg-emerald-500/5 text-emerald-300',
  'Extended Oversold': 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300',
}

function isoDaysAgo(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() - days)
  return d.toISOString().slice(0, 10)
}

type DrillCheck =
  | 'momentum' | 'volume' | 'quick_analyzer' | 'patterns' | 'smart_money'
  | 'scalping' | 'support_resistance' | 'time_series' | 'divergence' | 'stop_hunt' | 'take_profit' | 'real_bottom' | 'intra_hwp' | 'weak_strong' | 'sma_20_200' | 'copy_trade' | 'upgrade_downgrade' | 'fundamentals' | 'option_chain'
  | 'pa_vp_smc' | 'volume_spread_next_candle' | 'elliott_wave' | 'mtf_trend_strength'

const DRILL_CHECK_KEYS: DrillCheck[] = [
  'momentum', 'volume', 'quick_analyzer', 'patterns', 'smart_money',
  'scalping', 'support_resistance', 'time_series', 'divergence', 'stop_hunt', 'take_profit', 'real_bottom', 'intra_hwp', 'weak_strong', 'sma_20_200', 'copy_trade', 'upgrade_downgrade', 'fundamentals', 'option_chain',
  'pa_vp_smc', 'volume_spread_next_candle', 'elliott_wave', 'mtf_trend_strength',
]

export function TradeSetupDrillDown({ ticker, timeframe, assetClass }: { ticker: string; timeframe: string; assetClass: string }) {
  const isIndia = assetClass === 'india'
  const [checked, setChecked] = useState<Record<DrillCheck, boolean>>({
    momentum: false, volume: false, quick_analyzer: false, patterns: false, smart_money: false,
    scalping: false, support_resistance: false, time_series: false, divergence: false, stop_hunt: false, take_profit: false, real_bottom: false, intra_hwp: false, weak_strong: false, sma_20_200: false, copy_trade: false, upgrade_downgrade: false, fundamentals: false, option_chain: false,
    pa_vp_smc: false, volume_spread_next_candle: false, elliott_wave: false, mtf_trend_strength: false,
  })
  const [ran, setRan] = useState(false)

  const momentumMut = useMutation({ mutationFn: () => runMomentumScan({ tickers: [ticker], asset_class: assetClass, timeframes: [timeframe] }) })
  const qaMut = useMutation({ mutationFn: () => runQuickAnalyzer({ tickers: [ticker], timeframes: [timeframe], asset_class: assetClass as 'india' | 'us' | 'crypto', from_date: isoDaysAgo(90), to_date: isoDaysAgo(0) }) })
  const patternsMut = useMutation({ mutationFn: () => runTradeSetupPatterns({ ticker, asset_class: assetClass, timeframe }) })
  const smartMoneyMut = useMutation({ mutationFn: () => runTradeSetupSmartMoney({ ticker, asset_class: assetClass, timeframe }) })
  const scalpingMut = useMutation({ mutationFn: () => runTradeSetupScalping({ ticker, asset_class: assetClass, timeframe }) })
  const srMut = useMutation({ mutationFn: () => runTradeSetupSupportResistance({ ticker, asset_class: assetClass, timeframe }) })
  const tsMut = useMutation({ mutationFn: () => runTradeSetupTimeSeries({ ticker, asset_class: assetClass, timeframe }) })
  const divMut = useMutation({ mutationFn: () => runTradeSetupDivergence({ ticker, asset_class: assetClass, timeframe }) })
  const stopHuntMut = useMutation({ mutationFn: () => runTradeSetupStopHunt({ ticker, asset_class: assetClass, timeframe }) })
  const takeProfitMut = useMutation({ mutationFn: () => runTradeSetupTakeProfit({ ticker, asset_class: assetClass, timeframe }) })
  const realBottomMut = useMutation({ mutationFn: () => runTradeSetupRealBottom({ ticker, asset_class: assetClass, timeframe }) })
  const intraHwpMut = useMutation({ mutationFn: () => runTradeSetupIntraHwp({ ticker, asset_class: assetClass, timeframe }) })
  const weakStrongMut = useMutation({ mutationFn: () => runTradeSetupWeakStrong({ ticker, asset_class: assetClass, timeframe }) })
  const sma20200Mut = useMutation({ mutationFn: () => runTradeSetupSma20200({ ticker, asset_class: assetClass, timeframe }) })
  const copyTradeMut = useMutation({ mutationFn: () => runTradeSetupCopyTrade({ ticker, asset_class: assetClass, timeframe }) })
  const udMut = useMutation({ mutationFn: () => runUpgradeDowngradeScan({ tickers: [ticker], asset_class: assetClass }) })
  const faMut = useMutation({ mutationFn: () => runFundamentalAnalysis({ tickers: [ticker], asset_class: assetClass }) })
  const ocMut = useMutation({ mutationFn: () => runOptionChain({ symbol: ticker, is_index: false }) })
  const paVpSmcMut = useMutation({ mutationFn: () => runProTradePaVpSmc({ tickers: [ticker], asset_class: assetClass, ltf: timeframe }) })
  const vsaMut = useMutation({ mutationFn: () => runProTradeVolumeSpreadNextCandle({ tickers: [ticker], asset_class: assetClass, timeframe }) })
  const ewMut = useMutation({ mutationFn: () => runProTradeElliottWave({ tickers: [ticker], asset_class: assetClass, timeframe }) })
  const mtfTrendMut = useMutation({ mutationFn: () => runMtfTrendStrength({ tickers: [ticker], asset_class: assetClass, timeframes: [timeframe] }) })

  const toggle = (key: DrillCheck) => setChecked((prev) => ({ ...prev, [key]: !prev[key] }))
  const allSelected = DRILL_CHECK_KEYS.every((k) => checked[k])
  const toggleAll = () => {
    const next = !allSelected
    setChecked(Object.fromEntries(DRILL_CHECK_KEYS.map((k) => [k, next])) as Record<DrillCheck, boolean>)
  }

  const runAnalysis = () => {
    setRan(true)
    if (checked.momentum || checked.volume) momentumMut.mutate()
    if (checked.quick_analyzer) qaMut.mutate()
    if (checked.patterns) patternsMut.mutate()
    if (checked.smart_money) smartMoneyMut.mutate()
    if (checked.scalping) scalpingMut.mutate()
    if (checked.support_resistance) srMut.mutate()
    if (checked.time_series) tsMut.mutate()
    if (checked.divergence) divMut.mutate()
    if (checked.stop_hunt) stopHuntMut.mutate()
    if (checked.take_profit) takeProfitMut.mutate()
    if (checked.real_bottom) realBottomMut.mutate()
    if (checked.intra_hwp) intraHwpMut.mutate()
    if (checked.weak_strong) weakStrongMut.mutate()
    if (checked.sma_20_200) sma20200Mut.mutate()
    if (checked.copy_trade) copyTradeMut.mutate()
    if (checked.upgrade_downgrade) udMut.mutate()
    if (checked.fundamentals && isIndia) faMut.mutate()
    if (checked.option_chain && isIndia) ocMut.mutate()
    if (checked.pa_vp_smc) paVpSmcMut.mutate()
    if (checked.volume_spread_next_candle) vsaMut.mutate()
    if (checked.elliott_wave) ewMut.mutate()
    if (checked.mtf_trend_strength) mtfTrendMut.mutate()
  }

  const anyChecked = Object.values(checked).some(Boolean)
  const momentumRow = (momentumMut.data as Row | undefined)?.results as Row[] | undefined
  const m = momentumRow?.[0]
  const qaRow = (qaMut.data as Row | undefined)?.results as Row[] | undefined
  const qa = qaRow?.[0]
  const qaSetup = (qa?.setup as Row) ?? {}
  const udRow = (udMut.data as Row | undefined)?.results as Row[] | undefined
  const ud = udRow?.[0]
  const udConsensus = (ud?.consensus as Row) ?? {}
  const faRow = (faMut.data as Row | undefined)?.results as Row[] | undefined
  const fa = faRow?.[0]
  const faOverall = (fa?.overall as Row) ?? {}
  const faValuation = (fa?.valuation as Row) ?? {}
  const ocSignal = (ocMut.data as Row | undefined)?.signal as Row | undefined
  const ocChain = (ocMut.data as Row | undefined)?.chain as Row | undefined
  const mPerTf = (m?.per_tf as Row[]) ?? []
  const mTf = mPerTf[0]
  const vpa = mTf ? volumePriceAnalysis(mTf) : null
  const patData = patternsMut.data as Row | undefined
  const patterns = [...((patData?.candles as Row[]) ?? []), ...((patData?.charts as Row[]) ?? [])]
  const patBullish = patterns.filter((p) => p.bias === 'BULLISH')
  const patBearish = patterns.filter((p) => p.bias === 'BEARISH')
  const patNeutral = patterns.filter((p) => p.bias !== 'BULLISH' && p.bias !== 'BEARISH')
  const smCombo = (smartMoneyMut.data as Row | undefined)?.combo as Row | undefined
  const scalpCombo = (scalpingMut.data as Row | undefined)?.combo as Row | undefined
  const srData = srMut.data as Row | undefined
  const srSr = (srData?.sr as Row) ?? {}
  const srBreakout = (srData?.breakout as Row) ?? {}
  const srSupports = (srSr.supports as Row[]) ?? []
  const srResistances = (srSr.resistances as Row[]) ?? []
  const srPrice = srData?.price as number | undefined
  const srLevel = (srBreakout.level as Row) ?? {}
  const tsCombo = (tsMut.data as Row | undefined)?.combo as Row | undefined
  const divRes = divMut.data as Row | undefined
  const stopHuntRes = stopHuntMut.data as Row | undefined
  const takeProfitRes = takeProfitMut.data as Row | undefined
  const realBottomRes = realBottomMut.data as Row | undefined
  const intraHwpRes = intraHwpMut.data as Row | undefined
  const weakStrongRes = weakStrongMut.data as Row | undefined
  const sma20200Res = sma20200Mut.data as Row | undefined
  const copyTradeRes = copyTradeMut.data as Row | undefined
  const paVpSmcRow = (paVpSmcMut.data as Row | undefined)?.results as Row[] | undefined
  const paVpSmcRes = paVpSmcRow?.[0]
  const vsaRow = (vsaMut.data as Row | undefined)?.results as Row[] | undefined
  const vsaRes = vsaRow?.[0]
  const ewRow = (ewMut.data as Row | undefined)?.results as Row[] | undefined
  const ewRes = ewRow?.[0]
  const mtfTrendByTicker = (mtfTrendMut.data as Row | undefined)?.results as Record<string, Row> | undefined
  const mtfTrendRes = mtfTrendByTicker?.[ticker]
  const mtfTrendConfluence = (mtfTrendRes?.confluence as Row) ?? {}
  const mtfTrendTf = ((mtfTrendRes?.timeframes as Row)?.[timeframe] as Row) ?? {}

  const drillAiData: Row = { ticker, timeframe, asset_class: assetClass }
  if (checked.momentum && m) drillAiData.momentum = m
  if (checked.volume && mTf) drillAiData.volume = mTf
  if (checked.quick_analyzer && qa) drillAiData.quick_analyzer = qa
  if (checked.patterns && patData) drillAiData.patterns = patData
  if (checked.smart_money && smCombo) drillAiData.smart_money = smCombo
  if (checked.scalping && scalpCombo) drillAiData.scalping = scalpCombo
  if (checked.support_resistance && srData) drillAiData.support_resistance = srData
  if (checked.time_series && tsCombo) drillAiData.time_series = tsCombo
  if (checked.divergence && divRes) drillAiData.divergence = divRes
  if (checked.stop_hunt && stopHuntRes) drillAiData.stop_hunt = stopHuntRes
  if (checked.take_profit && takeProfitRes) drillAiData.take_profit = takeProfitRes
  if (checked.real_bottom && realBottomRes) drillAiData.real_bottom = realBottomRes
  if (checked.intra_hwp && intraHwpRes) drillAiData.intra_hwp = intraHwpRes
  if (checked.weak_strong && weakStrongRes) drillAiData.weak_strong = weakStrongRes
  if (checked.sma_20_200 && sma20200Res) drillAiData.sma_20_200 = sma20200Res
  if (checked.copy_trade && copyTradeRes) drillAiData.copy_trade = copyTradeRes
  if (checked.upgrade_downgrade && ud) drillAiData.upgrade_downgrade = ud
  if (checked.fundamentals && fa) drillAiData.fundamentals = fa
  if (checked.option_chain && ocSignal) drillAiData.option_chain = { signal: ocSignal, chain: ocChain }
  if (checked.pa_vp_smc && paVpSmcRes) drillAiData.pa_vp_smc = paVpSmcRes
  if (checked.volume_spread_next_candle && vsaRes) drillAiData.volume_spread_next_candle = vsaRes
  if (checked.elliott_wave && ewRes) drillAiData.elliott_wave = ewRes
  if (checked.mtf_trend_strength && mtfTrendRes) drillAiData.mtf_trend_strength = mtfTrendRes
  const drillAiContext = ran && Object.keys(drillAiData).length > 3 ? buildAskContext(`Trade Setup · ${ticker} · ${timeframe}`, drillAiData) : ''

  return (
    <div className="space-y-3 border-t border-slate-800/60 pt-3">
      <label className="flex items-center gap-1.5 text-xs font-semibold text-slate-200">
        <input type="checkbox" checked={allSelected} onChange={toggleAll} />
        {allSelected ? '☑️ Unselect all' : '✅ Select all'}
      </label>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
        <label className="flex items-center gap-1.5 text-xs text-slate-300">
          <input type="checkbox" checked={checked.momentum} onChange={() => toggle('momentum')} />📈 Momentum
        </label>
        <label className="flex items-center gap-1.5 text-xs text-slate-300">
          <input type="checkbox" checked={checked.volume} onChange={() => toggle('volume')} />📊 Volume
        </label>
        <label className="flex items-center gap-1.5 text-xs text-slate-300">
          <input type="checkbox" checked={checked.quick_analyzer} onChange={() => toggle('quick_analyzer')} />⚡ Quick Analyzer
        </label>
        <label className="flex items-center gap-1.5 text-xs text-slate-300">
          <input type="checkbox" checked={checked.patterns} onChange={() => toggle('patterns')} />🕯️ Candlestick/Chart Patterns
        </label>
        <label className="flex items-center gap-1.5 text-xs text-slate-300">
          <input type="checkbox" checked={checked.smart_money} onChange={() => toggle('smart_money')} />🧠 Smart Money
        </label>
        <label className="flex items-center gap-1.5 text-xs text-slate-300">
          <input type="checkbox" checked={checked.scalping} onChange={() => toggle('scalping')} />⚡ Scalping
        </label>
        <label className="flex items-center gap-1.5 text-xs text-slate-300">
          <input type="checkbox" checked={checked.support_resistance} onChange={() => toggle('support_resistance')} />🎯 Support/Resistance
        </label>
        <label className="flex items-center gap-1.5 text-xs text-slate-300">
          <input type="checkbox" checked={checked.time_series} onChange={() => toggle('time_series')} />📈 Time Series
        </label>
        <label className="flex items-center gap-1.5 text-xs text-slate-300">
          <input type="checkbox" checked={checked.divergence} onChange={() => toggle('divergence')} />🔀 Divergences
        </label>
        <label className="flex items-center gap-1.5 text-xs text-slate-300">
          <input type="checkbox" checked={checked.stop_hunt} onChange={() => toggle('stop_hunt')} />🎣 Stop Loss Hunting
        </label>
        <label className="flex items-center gap-1.5 text-xs text-slate-300">
          <input type="checkbox" checked={checked.take_profit} onChange={() => toggle('take_profit')} />🎯 Take Profit Targets
        </label>
        <label className="flex items-center gap-1.5 text-xs text-slate-300">
          <input type="checkbox" checked={checked.real_bottom} onChange={() => toggle('real_bottom')} />🔻 Real Bottom
        </label>
        <label className="flex items-center gap-1.5 text-xs text-slate-300">
          <input type="checkbox" checked={checked.intra_hwp} onChange={() => toggle('intra_hwp')} />↔️ Intra HWP
        </label>
        <label className="flex items-center gap-1.5 text-xs text-slate-300">
          <input type="checkbox" checked={checked.weak_strong} onChange={() => toggle('weak_strong')} />↔️ Weak / Strong
        </label>
        <label className="flex items-center gap-1.5 text-xs text-slate-300">
          <input type="checkbox" checked={checked.sma_20_200} onChange={() => toggle('sma_20_200')} />📉 200SMA-20SMA
        </label>
        <label className="flex items-center gap-1.5 text-xs text-slate-300">
          <input type="checkbox" checked={checked.copy_trade} onChange={() => toggle('copy_trade')} />🚀 Copy Trade
        </label>
        <label className="flex items-center gap-1.5 text-xs text-slate-300">
          <input type="checkbox" checked={checked.upgrade_downgrade} onChange={() => toggle('upgrade_downgrade')} />🏷️ Stock Upgrade Downgrade
        </label>
        <label className={`flex items-center gap-1.5 text-xs ${isIndia ? 'text-slate-300' : 'text-slate-600'}`}>
          <input type="checkbox" checked={checked.fundamentals} disabled={!isIndia} onChange={() => toggle('fundamentals')} />📚 Fundamentals
        </label>
        <label className={`flex items-center gap-1.5 text-xs ${isIndia ? 'text-slate-300' : 'text-slate-600'}`}>
          <input type="checkbox" checked={checked.option_chain} disabled={!isIndia} onChange={() => toggle('option_chain')} />⛓️ Option Chain
        </label>
        <label className="flex items-center gap-1.5 text-xs text-slate-300">
          <input type="checkbox" checked={checked.pa_vp_smc} onChange={() => toggle('pa_vp_smc')} />🌊 PA-VP-SMC
        </label>
        <label className="flex items-center gap-1.5 text-xs text-slate-300">
          <input type="checkbox" checked={checked.volume_spread_next_candle} onChange={() => toggle('volume_spread_next_candle')} />📶 Volume Spread - Next Candle
        </label>
        <label className="flex items-center gap-1.5 text-xs text-slate-300">
          <input type="checkbox" checked={checked.elliott_wave} onChange={() => toggle('elliott_wave')} />🌊 Elliott Wave
        </label>
        <label className="flex items-center gap-1.5 text-xs text-slate-300">
          <input type="checkbox" checked={checked.mtf_trend_strength} onChange={() => toggle('mtf_trend_strength')} />📶 MTF Trend and Strength
        </label>
      </div>
      {!isIndia && <p className="text-xs text-slate-500">Fundamentals and Option Chain are Groww India (NSE) only.</p>}

      <Button size="sm" variant="secondary" onClick={runAnalysis} disabled={!anyChecked}>
        🔍 Run further analysis
      </Button>

      {ran && (
        <div className="space-y-2 text-sm text-slate-300">
          {(checked.momentum || checked.volume) && (
            momentumMut.isPending ? <p className="text-xs text-slate-500">Loading momentum…</p> :
            momentumMut.isError ? <p className="text-xs text-rose-400">Momentum failed: {apiErrorMessage(momentumMut.error)}</p> :
            m ? (
              <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-2.5">
                {checked.momentum && (
                  <>
                    <p><strong>📈 Momentum:</strong> <span className={verdictClass(String(m.overall_direction ?? ''))}>{String(m.overall_direction ?? '—')}</span> · {String(m.overall_strength ?? '—')}
                      {m.overall_direction === 'CONSOLIDATING' ? '' : ` · ${fmtNum(m.confidence_continue_pct, 0)}% confidence`}
                    </p>
                    {m.overall_direction === 'CONSOLIDATING' && m.breakout_up_pct != null && (
                      <p className="text-xs text-amber-400">
                        ⚖️ Breakout lean: <strong>{fmtNum(m.breakout_up_pct, 0)}% chance of breaking UP</strong> vs <strong>{fmtNum(m.breakout_down_pct, 0)}% DOWN</strong>
                      </p>
                    )}
                    {(m.actionability as Row)?.reason != null && <p className="text-xs text-slate-400">Verdict: {String((m.actionability as Row).reason)}</p>}
                    {((m.reasons as string[]) ?? []).slice(0, 3).map((rr, i) => <p key={i} className="text-xs text-slate-500">• {rr}</p>)}
                  </>
                )}
                {checked.volume && mTf && vpa && (
                  <div className={checked.momentum ? 'mt-2 border-t border-slate-800/60 pt-2' : ''}>
                    <p className="font-semibold text-white">📊 Volume — Volume-Price Analysis</p>
                    <p className="text-xs text-slate-300">{vpa.badge} <strong>Volume Bias: {vpa.bias}</strong></p>
                    <p className="text-xs text-slate-400">
                      Volume vs 20-bar Avg: <strong>{vpa.ratioStr}</strong> · Participation: <strong>{vpa.tier}</strong> · Trend Context: <strong>{vpa.trend} · {vpa.momentumChange}</strong>
                    </p>
                    <p className="text-xs text-slate-500">{mdBold(vpa.read)}</p>
                    {mTf.breakout_up_pct != null && (
                      <p className="text-xs text-amber-400">
                        ⚖️ Breakout lean: <strong>{fmtNum(mTf.breakout_up_pct, 0)}% chance of breaking UP</strong> vs <strong>{fmtNum(mTf.breakout_down_pct, 0)}% DOWN</strong>
                      </p>
                    )}
                    {vpa.divergenceCaption && <p className="text-xs text-slate-500">{vpa.divergenceCaption}</p>}
                    {vpa.breakoutCaption && <p className="text-xs text-slate-500">{mdBold(vpa.breakoutCaption)}</p>}
                  </div>
                )}
              </div>
            ) : null
          )}

          {checked.quick_analyzer && (
            qaMut.isPending ? <p className="text-xs text-slate-500">Loading Quick Analyzer…</p> :
            qaMut.isError ? <p className="text-xs text-rose-400">Quick Analyzer failed: {apiErrorMessage(qaMut.error)}</p> :
            qa ? (
              <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-2.5">
                <p><strong>⚡ Quick Analyzer:</strong> Setup <span className={verdictClass(String(qaSetup.direction ?? ''))}>{String(qaSetup.direction ?? '—')}</span> · {fmtNum(qaSetup.confidence_pct, 0)}% confidence
                  {qaSetup.sl_pct != null ? ` · SL ${fmtNum(qaSetup.sl_pct, 2)}% / TP ${fmtNum(qaSetup.tp_pct, 2)}%` : ''}</p>
                {qaSetup.breakout_up_pct != null && (
                  <p className="text-xs text-amber-400">
                    ⚖️ Breakout lean: <strong>{fmtNum(qaSetup.breakout_up_pct, 0)}% chance of breaking UP</strong> vs <strong>{fmtNum(qaSetup.breakout_down_pct, 0)}% DOWN</strong>
                  </p>
                )}
                {((qaSetup.reasons as string[]) ?? []).filter((rr) => !rr.startsWith('⚖️ Breakout lean')).slice(0, 3).map((rr, i) => <p key={i} className="text-xs text-slate-500">• {rr}</p>)}
              </div>
            ) : null
          )}

          {checked.patterns && (
            patternsMut.isPending ? <p className="text-xs text-slate-500">Scanning candlestick &amp; chart patterns…</p> :
            patternsMut.isError ? <p className="text-xs text-rose-400">Patterns failed: {apiErrorMessage(patternsMut.error)}</p> :
            patData ? (
              <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-2.5">
                <p className="font-semibold text-white">🕯️ Candlestick / Chart Patterns</p>
                {!patterns.length && <p className="text-xs text-slate-500">No notable bullish or bearish candlestick/chart pattern formed in the recent bars.</p>}
                {patBullish.length > 0 && (
                  <>
                    <p className="mt-1 text-xs text-emerald-400">🟢 {patBullish.length} bullish pattern(s) formed:</p>
                    {patBullish.map((p, i) => (
                      <p key={i} className="text-xs text-slate-500">· <strong>{String(p.name ?? '—')}</strong> [{String(p.reliability ?? '—')} reliability{p.volume_confirmed === true ? ', volume-confirmed' : p.volume_confirmed === false ? ', thin volume' : ''}]{p.bars_ago != null ? ` (${String(p.bars_ago)} bar(s) ago)` : ''} — {String(p.description ?? p.notes ?? '')}</p>
                    ))}
                  </>
                )}
                {patBearish.length > 0 && (
                  <>
                    <p className="mt-1 text-xs text-rose-400">🔴 {patBearish.length} bearish pattern(s) formed:</p>
                    {patBearish.map((p, i) => (
                      <p key={i} className="text-xs text-slate-500">· <strong>{String(p.name ?? '—')}</strong> [{String(p.reliability ?? '—')} reliability{p.volume_confirmed === true ? ', volume-confirmed' : p.volume_confirmed === false ? ', thin volume' : ''}]{p.bars_ago != null ? ` (${String(p.bars_ago)} bar(s) ago)` : ''} — {String(p.description ?? p.notes ?? '')}</p>
                    ))}
                  </>
                )}
                {patNeutral.length > 0 && (
                  <>
                    <p className="mt-1 text-xs text-slate-400">⚪ {patNeutral.length} neutral/indecision pattern(s):</p>
                    {patNeutral.map((p, i) => (
                      <p key={i} className="text-xs text-slate-500">· <strong>{String(p.name ?? '—')}</strong> [{String(p.reliability ?? '—')} reliability{p.volume_confirmed === true ? ', volume-confirmed' : p.volume_confirmed === false ? ', thin volume' : ''}]{p.bars_ago != null ? ` (${String(p.bars_ago)} bar(s) ago)` : ''} — {String(p.description ?? p.notes ?? '')}</p>
                    ))}
                  </>
                )}
              </div>
            ) : null
          )}

          {checked.smart_money && (
            smartMoneyMut.isPending ? <p className="text-xs text-slate-500">Combining Smart Money strategies…</p> :
            smartMoneyMut.isError ? <p className="text-xs text-rose-400">Smart Money failed: {apiErrorMessage(smartMoneyMut.error)}</p> :
            smCombo ? (
              <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-2.5">
                <p className="font-semibold text-white">🧠 Smart Money — TTG Sniper + CISD Entry + MTF Day Plan (combined)</p>
                <p className="text-xs text-slate-400">
                  Verdict: <strong className={verdictClass(String(smCombo.verdict ?? ''))}>{String(smCombo.verdict ?? '—')}</strong> · {fmtNum(smCombo.confidence_pct, 0)}% confidence
                  {' '}({fmtNum(smCombo.n_agree, 0)}/{fmtNum(smCombo.n_total, 0)} strategies agree, need {fmtNum(smCombo.min_agree_required, 0)}+ at {fmtNum(smCombo.take_threshold, 0)}%+)
                  {smCombo.entry_price != null ? ` · Entry ${fmtNum(smCombo.entry_price, 4)} · SL ${fmtNum(smCombo.stop_price, 4)} · TP1 ${fmtNum(smCombo.target1_price, 4)} · TP2 ${fmtNum(smCombo.target2_price, 4)}` : ''}
                </p>
                {((smCombo.reasons as string[]) ?? []).map((rr, i) => <p key={i} className="text-xs text-slate-500">· {rr}</p>)}
              </div>
            ) : null
          )}

          {checked.scalping && (
            scalpingMut.isPending ? <p className="text-xs text-slate-500">Combining scalping strategies…</p> :
            scalpingMut.isError ? <p className="text-xs text-rose-400">Scalping failed: {apiErrorMessage(scalpingMut.error)}</p> :
            scalpCombo ? (
              <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-2.5">
                <p className="font-semibold text-white">⚡ Scalping — Rectangle Setup + SMC Rule of Three (CRT-FVG) + ARC Method + A+ S/R MSS (combined)</p>
                <p className="text-xs text-slate-400">
                  Verdict: <strong className={verdictClass(String(scalpCombo.verdict ?? ''))}>{String(scalpCombo.verdict ?? '—')}</strong> · {fmtNum(scalpCombo.confidence_pct, 0)}% confidence
                  {' '}({fmtNum(scalpCombo.n_agree, 0)}/{fmtNum(scalpCombo.n_total, 0)} strategies agree, need {fmtNum(scalpCombo.min_agree_required, 0)}+ at {fmtNum(scalpCombo.take_threshold, 0)}%+)
                  {scalpCombo.entry_price != null ? ` · Entry ${fmtNum(scalpCombo.entry_price, 4)} · SL ${fmtNum(scalpCombo.stop_price, 4)} · TP1 ${fmtNum(scalpCombo.target1_price, 4)} · TP2 ${fmtNum(scalpCombo.target2_price, 4)}` : ''}
                </p>
                {((scalpCombo.reasons as string[]) ?? []).map((rr, i) => <p key={i} className="text-xs text-slate-500">· {rr}</p>)}
              </div>
            ) : null
          )}

          {checked.support_resistance && (
            srMut.isPending ? <p className="text-xs text-slate-500">Scanning support/resistance…</p> :
            srMut.isError ? <p className="text-xs text-rose-400">Support/Resistance failed: {apiErrorMessage(srMut.error)}</p> :
            srData ? (
              <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-2.5">
                <p className="font-semibold text-white">🎯 Support / Resistance — Approaching, Breakout &amp; Breakdown</p>
                {srBreakout.event === 'RESISTANCE_BREAKOUT' && srPrice != null ? (
                  <p className="text-xs text-emerald-400">🚀 Breakout — price ({fmtNum(srPrice, 2)}) has closed above prior resistance {fmtNum(srLevel.price, 2)} ({fmtNum(srLevel.touches, 0)} prior touch(es)) — {srBreakout.volume_confirmed ? 'volume confirms the move' : 'not yet volume-confirmed, watch for follow-through'}.</p>
                ) : srBreakout.event === 'SUPPORT_BREAKDOWN' && srPrice != null ? (
                  <p className="text-xs text-rose-400">🔻 Breakdown — price ({fmtNum(srPrice, 2)}) has closed below prior support {fmtNum(srLevel.price, 2)} ({fmtNum(srLevel.touches, 0)} prior touch(es)) — {srBreakout.volume_confirmed ? 'volume confirms the move' : 'not yet volume-confirmed, watch for follow-through'}.</p>
                ) : (
                  <p className="text-xs text-slate-500">No fresh breakout/breakdown on this timeframe — price is still inside its recent range.</p>
                )}
                {srResistances.length > 0 && (
                  <p className="text-xs text-slate-500">Resistance levels: {srResistances.map((r) => `${fmtNum(r.price, 2)} (${fmtNum(r.touches, 0)}x)`).join(', ')}</p>
                )}
                {srSupports.length > 0 && (
                  <p className="text-xs text-slate-500">Support levels: {srSupports.map((s) => `${fmtNum(s.price, 2)} (${fmtNum(s.touches, 0)}x)`).join(', ')}</p>
                )}
              </div>
            ) : null
          )}

          {checked.time_series && (
            tsMut.isPending ? <p className="text-xs text-slate-500">Combining time-series strategies…</p> :
            tsMut.isError ? <p className="text-xs text-rose-400">Time Series failed: {apiErrorMessage(tsMut.error)}</p> :
            tsCombo ? (
              <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-2.5">
                <p className="font-semibold text-white">📈 Time Series — MA Crossover (Golden/Death Cross) + Bollinger Mean Reversion + Momentum Breakout (combined)</p>
                <p className="text-xs text-slate-400">
                  Verdict: <strong className={verdictClass(String(tsCombo.verdict ?? ''))}>{String(tsCombo.verdict ?? '—')}</strong> · {fmtNum(tsCombo.confidence_pct, 0)}% confidence
                  {' '}({fmtNum(tsCombo.n_agree, 0)}/{fmtNum(tsCombo.n_total, 0)} strategies agree, need {fmtNum(tsCombo.min_agree_required, 0)}+ at {fmtNum(tsCombo.take_threshold, 0)}%+)
                  {tsCombo.entry_price != null ? ` · Entry ${fmtNum(tsCombo.entry_price, 4)} · SL ${fmtNum(tsCombo.stop_price, 4)} · TP1 ${fmtNum(tsCombo.target1_price, 4)} · TP2 ${fmtNum(tsCombo.target2_price, 4)}` : ''}
                </p>
                {((tsCombo.reasons as string[]) ?? []).map((rr, i) => <p key={i} className="text-xs text-slate-500">· {rr}</p>)}
              </div>
            ) : null
          )}

          {checked.divergence && (
            divMut.isPending ? <p className="text-xs text-slate-500">Scanning for divergences…</p> :
            divMut.isError ? <p className="text-xs text-rose-400">Divergences failed: {apiErrorMessage(divMut.error)}</p> :
            divRes ? (
              divRes.error != null ? (
                <p className="text-xs text-slate-500">Unavailable — {String(divRes.error)}</p>
              ) : (
                <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-2.5">
                  <p className="font-semibold text-white">🔀 Divergences — Price vs RSI · Price vs Volume (OBV)</p>
                  <p className="text-xs text-slate-400">
                    {DIVERGENCE_BADGE[String(divRes.bias ?? 'NEUTRAL')] ?? String(divRes.bias ?? '—')} · {fmtNum(divRes.confidence_pct, 0)}% confidence
                  </p>
                  {((divRes.reasons as string[]) ?? []).map((rr, i) => <p key={i} className="text-xs text-slate-500">· {mdBold(rr)}</p>)}
                </div>
              )
            ) : null
          )}

          {checked.stop_hunt && (
            stopHuntMut.isPending ? <p className="text-xs text-slate-500">Scanning for stop-loss hunting…</p> :
            stopHuntMut.isError ? <p className="text-xs text-rose-400">Stop Loss Hunting failed: {apiErrorMessage(stopHuntMut.error)}</p> :
            stopHuntRes ? (
              stopHuntRes.error != null ? (
                <p className="text-xs text-slate-500">Unavailable — {String(stopHuntRes.error)}</p>
              ) : (
                <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-2.5">
                  <p className="font-semibold text-white">🎣 Stop Loss Hunting — Liquidity Sweep Detection &amp; Hunt-Resistant Stops</p>
                  <p className="text-xs text-slate-400">
                    {HUNT_STATUS_BADGE[String(stopHuntRes.hunt_status ?? 'LOW_RISK')] ?? String(stopHuntRes.hunt_status ?? '—')}
                    {stopHuntRes.atr != null ? ` · ATR ${fmtNum(stopHuntRes.atr, 4)}` : ''}
                  </p>
                  {((stopHuntRes.reasons as string[]) ?? []).map((rr, i) => <p key={i} className="text-xs text-slate-500">· {mdBold(rr)}</p>)}
                  <StopHuntScenario label="If LONG" stops={stopHuntRes.long_stops as Row} />
                  <StopHuntScenario label="If SHORT" stops={stopHuntRes.short_stops as Row} />
                </div>
              )
            ) : null
          )}

          {checked.take_profit && (
            takeProfitMut.isPending ? <p className="text-xs text-slate-500">Computing take-profit targets…</p> :
            takeProfitMut.isError ? <p className="text-xs text-rose-400">Take Profit Targets failed: {apiErrorMessage(takeProfitMut.error)}</p> :
            takeProfitRes ? (
              takeProfitRes.error != null ? (
                <p className="text-xs text-slate-500">Unavailable — {String(takeProfitRes.error)}</p>
              ) : (
                <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-2.5">
                  <p className="font-semibold text-white">🎯 Take Profit Targets — S/R · Pattern · Fibonacci · Liquidity Draw</p>
                  <p className="text-xs text-slate-400">
                    {TP_STATUS_BADGE[String(takeProfitRes.tp_status ?? 'LOW_CONFLUENCE')] ?? String(takeProfitRes.tp_status ?? '—')}
                    {takeProfitRes.atr != null ? ` · ATR ${fmtNum(takeProfitRes.atr, 4)}` : ''}
                  </p>
                  {((takeProfitRes.reasons as string[]) ?? []).map((rr, i) => <p key={i} className="text-xs text-slate-500">· {rr}</p>)}
                  <TakeProfitScenario label="If LONG" targets={takeProfitRes.long_targets as Row} />
                  <TakeProfitScenario label="If SHORT" targets={takeProfitRes.short_targets as Row} />
                </div>
              )
            ) : null
          )}

          {checked.real_bottom && (
            realBottomMut.isPending ? <p className="text-xs text-slate-500">Checking the real-bottom sequence…</p> :
            realBottomMut.isError ? <p className="text-xs text-rose-400">Real Bottom failed: {apiErrorMessage(realBottomMut.error)}</p> :
            realBottomRes ? (
              realBottomRes.error != null ? (
                <p className="text-xs text-slate-500">Unavailable — {String(realBottomRes.error)}</p>
              ) : (
                <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-2.5">
                  <p className="font-semibold text-white">🔻 Real Bottom — Absorption → Retest → Trap → Displacement → Entry</p>
                  <p className="text-xs text-slate-400">
                    {REAL_BOTTOM_STATUS_BADGE[String(realBottomRes.status ?? 'NO_SETUP')] ?? String(realBottomRes.status ?? '—')}
                    {realBottomRes.atr != null ? ` · ATR ${fmtNum(realBottomRes.atr, 4)}` : ''}
                  </p>
                  <p className="text-xs text-slate-500">👉 {REAL_BOTTOM_STATUS_ACTION[String(realBottomRes.status ?? 'NO_SETUP')] ?? ''}</p>
                  {((realBottomRes.reasons as string[]) ?? []).map((rr, i) => <p key={i} className="text-xs text-slate-500">· {rr}</p>)}
                  {realBottomRes.entry_zone != null && (
                    <p className="text-xs text-slate-400">
                      Entry zone: <strong>{fmtNum((realBottomRes.entry_zone as Row).bottom, 4)}–{fmtNum((realBottomRes.entry_zone as Row).top, 4)}</strong>
                    </p>
                  )}
                  {realBottomRes.stop_loss != null && (
                    <p className="text-xs text-slate-400">
                      Stop loss: <strong>{fmtNum((realBottomRes.stop_loss as Row).price, 4)}</strong> ({fmtNum((realBottomRes.stop_loss as Row).pct, 2)}%)
                    </p>
                  )}
                  {realBottomRes.target != null && (
                    <p className="text-xs text-slate-400">
                      Target: <strong>{fmtNum((realBottomRes.target as Row).price, 4)}</strong> ({fmtNum((realBottomRes.target as Row).pct, 2)}%, {fmtNum((realBottomRes.target as Row).touches, 0)}x touched)
                    </p>
                  )}
                </div>
              )
            ) : null
          )}

          {checked.intra_hwp && (
            intraHwpMut.isPending ? <p className="text-xs text-slate-500">Checking the two-sided gap fill…</p> :
            intraHwpMut.isError ? <p className="text-xs text-rose-400">Intra HWP failed: {apiErrorMessage(intraHwpMut.error)}</p> :
            intraHwpRes ? (
              intraHwpRes.error != null ? (
                <p className="text-xs text-slate-500">Unavailable — {String(intraHwpRes.error)}</p>
              ) : (
                <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-2.5">
                  <p className="font-semibold text-white">↔️ Intra HWP — Two-Sided Gap Fill + 21 EMA</p>
                  <p className="text-xs text-slate-400">
                    {INTRA_HWP_PHASE_BADGE[String(intraHwpRes.phase ?? 'NO_GAP')] ?? String(intraHwpRes.phase ?? '—')}
                    {' · '}{String(((intraHwpRes.live as Row)?.verdict) ?? 'WAIT')}
                    {' · '}{fmtNum(((intraHwpRes.live as Row)?.confidence_pct), 0)}% confidence
                    {intraHwpRes.atr != null ? ` · ATR ${fmtNum(intraHwpRes.atr, 4)}` : ''}
                  </p>
                  <p className="text-xs text-slate-500">
                    Gap {fmtNum(intraHwpRes.gap_pct, 2)}% · Today's open {fmtNum(intraHwpRes.today_open, 4)} · Prior close {fmtNum(intraHwpRes.prior_close, 4)}
                  </p>
                  {(((intraHwpRes.live as Row)?.reasons as string[]) ?? []).map((rr, i) => <p key={i} className="text-xs text-slate-500">· {rr}</p>)}
                  {(intraHwpRes.live as Row)?.entry_price != null && (
                    <p className="text-xs text-slate-400">
                      Entry: <strong>{fmtNum((intraHwpRes.live as Row).entry_price, 4)}</strong>
                      {' · '}Stop: <strong>{fmtNum((intraHwpRes.live as Row).stop_price, 4)}</strong> ({fmtNum((intraHwpRes.live as Row).sl_pct, 2)}%)
                      {' · '}Target: <strong>{fmtNum((intraHwpRes.live as Row).target_price, 4)}</strong> ({fmtNum((intraHwpRes.live as Row).tp_pct, 2)}%)
                    </p>
                  )}
                </div>
              )
            ) : null
          )}

          {checked.weak_strong && (
            weakStrongMut.isPending ? <p className="text-xs text-slate-500">Scoring relative strength…</p> :
            weakStrongMut.isError ? <p className="text-xs text-rose-400">Weak / Strong failed: {apiErrorMessage(weakStrongMut.error)}</p> :
            weakStrongRes ? (
              weakStrongRes.error != null ? (
                <p className="text-xs text-slate-500">Unavailable — {String(weakStrongRes.error)}</p>
              ) : (
                <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-2.5">
                  <p className="font-semibold text-white">↔️ Weak / Strong — Relative Strength & Trend Classifier</p>
                  <p className="text-xs text-slate-400">
                    {WEAK_STRONG_BADGE[String(weakStrongRes.verdict ?? 'NEUTRAL')] ?? String(weakStrongRes.verdict ?? '—')}
                    {' · score '}{fmtNum(weakStrongRes.score, 0)}{' · '}{fmtNum(weakStrongRes.confidence_pct, 0)}% confidence
                    {weakStrongRes.rel_pct != null ? ` · RS ${fmtNum(weakStrongRes.rel_pct, 1)}%` : ''}
                    {weakStrongRes.vol_ratio != null ? ` · vol ${fmtNum(weakStrongRes.vol_ratio, 1)}x` : ''}
                  </p>
                  {((weakStrongRes.reasons as string[]) ?? []).map((rr, i) => <p key={i} className="text-xs text-slate-500">· {rr}</p>)}
                  <div className="mt-2 grid gap-2 sm:grid-cols-2">
                    <WeakStrongPlaybookCard label="🎯 Scalping" plan={weakStrongRes.scalp_plan as Row | undefined} />
                    <WeakStrongPlaybookCard label="📈 Swing" plan={weakStrongRes.swing_plan as Row | undefined} />
                  </div>
                </div>
              )
            ) : null
          )}

          {checked.sma_20_200 && (
            sma20200Mut.isPending ? <p className="text-xs text-slate-500">Checking 200 SMA trend filter + 20 SMA bounce/rejection…</p> :
            sma20200Mut.isError ? <p className="text-xs text-rose-400">200SMA-20SMA failed: {apiErrorMessage(sma20200Mut.error)}</p> :
            sma20200Res ? (
              sma20200Res.error != null ? (
                <p className="text-xs text-slate-500">Unavailable — {String(sma20200Res.error)}</p>
              ) : (
                <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-2.5">
                  <p className="font-semibold text-white">📉 200SMA-20SMA — Bounce &amp; Rejection</p>
                  <p className="text-xs text-slate-400">
                    {String(((sma20200Res.live as Row)?.verdict) ?? 'WAIT')}
                    {' · '}{fmtNum(((sma20200Res.live as Row)?.confidence_pct), 0)}% confidence
                    {' · price '}{fmtNum(sma20200Res.price, 4)}
                  </p>
                  <p className="text-xs text-slate-500">
                    20 SMA <strong>{fmtNum((sma20200Res.live as Row)?.sma_fast, 4)}</strong> · 200 SMA <strong>{fmtNum((sma20200Res.live as Row)?.sma_slow, 4)}</strong> · signals in window: <strong>{String(sma20200Res.signal_count ?? 0)}</strong>
                  </p>
                  {(((sma20200Res.live as Row)?.reasons as string[]) ?? []).map((rr, i) => <p key={i} className="text-xs text-slate-500">· {rr}</p>)}
                  {(sma20200Res.live as Row)?.entry_price != null && (
                    <p className="text-xs text-slate-400">
                      Entry: <strong>{fmtNum((sma20200Res.live as Row).entry_price, 4)}</strong>
                      {' · '}Stop: <strong>{fmtNum((sma20200Res.live as Row).stop_price, 4)}</strong> ({fmtNum((sma20200Res.live as Row).sl_pct, 2)}%)
                      {' · '}Target: <strong>{fmtNum((sma20200Res.live as Row).target_price, 4)}</strong> ({fmtNum((sma20200Res.live as Row).tp_pct, 2)}%)
                    </p>
                  )}
                </div>
              )
            ) : null
          )}

          {checked.copy_trade && (
            copyTradeMut.isPending ? <p className="text-xs text-slate-500">Checking Stochastic 80/20 + Engulfing + volume…</p> :
            copyTradeMut.isError ? <p className="text-xs text-rose-400">Copy Trade failed: {apiErrorMessage(copyTradeMut.error)}</p> :
            copyTradeRes ? (
              copyTradeRes.error != null ? (
                <p className="text-xs text-slate-500">Unavailable — {String(copyTradeRes.error)}</p>
              ) : (
                <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-2.5">
                  <p className="font-semibold text-white">🚀 Copy Trade — High-Beta / 3x Leveraged ETF Momentum Scalp</p>
                  <p className="text-xs text-slate-400">
                    {COPY_TRADE_PHASE_BADGE[String(copyTradeRes.phase ?? 'NO_SETUP')] ?? String(copyTradeRes.phase ?? '—')}
                    {' · '}{String(((copyTradeRes.live as Row)?.verdict) ?? 'WAIT')}
                    {' · '}{fmtNum(((copyTradeRes.live as Row)?.confidence_pct), 0)}% confidence
                  </p>
                  <p className="text-xs text-slate-500">
                    Stochastic %K {fmtNum(copyTradeRes.stoch_k, 1)} (prev {fmtNum(copyTradeRes.stoch_k_prev, 1)}) · Volume {fmtNum(copyTradeRes.vol_ratio, 1)}x average
                  </p>
                  {(((copyTradeRes.live as Row)?.reasons as string[]) ?? []).map((rr, i) => <p key={i} className="text-xs text-slate-500">· {rr}</p>)}
                  {(copyTradeRes.live as Row)?.entry_price != null && (
                    <p className="text-xs text-slate-400">
                      Entry: <strong>{fmtNum((copyTradeRes.live as Row).entry_price, 4)}</strong>
                      {' · '}Stop: <strong>{fmtNum((copyTradeRes.live as Row).stop_price, 4)}</strong> ({fmtNum((copyTradeRes.live as Row).sl_pct, 2)}%)
                      {' · '}Target: <strong>{fmtNum((copyTradeRes.live as Row).target_price, 4)}</strong> ({fmtNum((copyTradeRes.live as Row).tp_pct, 2)}%)
                    </p>
                  )}
                </div>
              )
            ) : null
          )}

          {checked.upgrade_downgrade && (
            udMut.isPending ? <p className="text-xs text-slate-500">Loading Upgrade/Downgrade…</p> :
            udMut.isError ? <p className="text-xs text-rose-400">Upgrade/Downgrade failed: {apiErrorMessage(udMut.error)}</p> :
            ud ? (
              <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-2.5">
                <p><strong>🏷️ Stock Upgrade Downgrade:</strong> 🧱 Block deals: {fmtNum(ud.block_deal_or_ma_count, 0)} · ⬆️ Upgrades: {fmtNum(udConsensus.upgrades, 0)} · ⬇️ Downgrades: {fmtNum(udConsensus.downgrades, 0)}
                  {udConsensus.consensus != null ? <> · Consensus: <strong className={verdictClass(String(udConsensus.consensus ?? ''))}>{String(udConsensus.consensus)}</strong></> : ''}
                  {udConsensus.latest_target != null ? ` · Latest target: ${fmtNum(udConsensus.latest_target)}` : ''}</p>
                {!((ud.items as Row[]) ?? []).length && <p className="text-xs text-slate-500">No block deals, M&A, or analyst coverage found in the lookback window.</p>}
                {((ud.items as Row[]) ?? []).slice(0, 5).map((it, i) => (
                  <p key={i} className="text-xs text-slate-500">· [{String(it.category_label ?? it.action ?? '—')}] {String(it.brokerage ?? it.source ?? '')} — {String(it.title ?? '').slice(0, 100)}</p>
                ))}
              </div>
            ) : null
          )}

          {checked.fundamentals && isIndia && (
            faMut.isPending ? <p className="text-xs text-slate-500">Loading Fundamentals…</p> :
            faMut.isError ? <p className="text-xs text-rose-400">Fundamentals failed: {apiErrorMessage(faMut.error)}</p> :
            fa ? (
              <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-2.5">
                <p><strong>📚 Fundamentals:</strong> Signal: <span className={verdictClass(String(faOverall.signal ?? ''))}>{String(faOverall.signal ?? '—')}</span> ({fmtNum(faOverall.confidence_pct, 0)}% confidence) · Valuation: {String(faValuation.label ?? '—')}</p>
                {((faOverall.factors as string[]) ?? []).slice(0, 4).map((f, i) => <p key={i} className="text-xs text-slate-500">• {f}</p>)}
              </div>
            ) : null
          )}

          {checked.option_chain && isIndia && (
            ocMut.isPending ? <p className="text-xs text-slate-500">Loading Option Chain…</p> :
            ocMut.isError ? <p className="text-xs text-rose-400">Option Chain failed: {apiErrorMessage(ocMut.error)}</p> :
            ocSignal ? (
              <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-2.5">
                <p><strong>⛓️ Option Chain:</strong> Bias: <span className={verdictClass(String(ocSignal.bias ?? ''))}>{String(ocSignal.bias ?? '—')}</span> · Trade signal: {String(ocSignal.trade_signal ?? '—')} · {fmtNum(ocSignal.confidence_pct, 0)}% confidence
                  {ocChain?.pcr_oi != null ? ` · PCR: ${fmtNum(ocChain.pcr_oi, 2)}` : ''}
                  {ocChain?.max_pain != null ? ` · Max Pain: ${fmtNum(ocChain.max_pain, 0)}` : ''}</p>
                {((ocSignal.reasons as string[]) ?? []).slice(0, 3).map((rr, i) => <p key={i} className="text-xs text-slate-500">• {rr}</p>)}
              </div>
            ) : ocMut.isSuccess ? <p className="text-xs text-slate-500">Could not fetch option chain — no listed F&amp;O contracts, or NSE is rate-limiting.</p> : null
          )}

          {checked.pa_vp_smc && (
            paVpSmcMut.isPending ? <p className="text-xs text-slate-500">Loading PA-VP-SMC…</p> :
            paVpSmcMut.isError ? <p className="text-xs text-rose-400">PA-VP-SMC failed: {apiErrorMessage(paVpSmcMut.error)}</p> :
            paVpSmcRes && !paVpSmcRes.error ? (
              <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-2.5">
                <p><strong>🌊 PA-VP-SMC:</strong> <span className={verdictClass(String(paVpSmcRes.verdict ?? ''))}>{String(paVpSmcRes.verdict ?? '—')}</span>
                  {(paVpSmcRes.confluence as Row)?.confidence_pct != null ? ` · ${fmtNum((paVpSmcRes.confluence as Row).confidence_pct, 0)}% confidence` : ''}</p>
                {((paVpSmcRes.reasons as string[]) ?? []).slice(0, 3).map((rr, i) => <p key={i} className="text-xs text-slate-500">• {rr}</p>)}
              </div>
            ) : paVpSmcRes?.error ? <p className="text-xs text-rose-400">{String(paVpSmcRes.error)}</p> : null
          )}

          {checked.volume_spread_next_candle && (
            vsaMut.isPending ? <p className="text-xs text-slate-500">Loading Volume Spread - Next Candle…</p> :
            vsaMut.isError ? <p className="text-xs text-rose-400">Volume Spread failed: {apiErrorMessage(vsaMut.error)}</p> :
            vsaRes && !vsaRes.error ? (
              <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-2.5">
                <p><strong>📶 Volume Spread - Next Candle:</strong> <span className={verdictClass(String(vsaRes.verdict ?? ''))}>{String(vsaRes.verdict ?? '—')}</span>
                  {vsaRes.confidence_pct != null ? ` · ${fmtNum(vsaRes.confidence_pct, 0)}% confidence` : ''}</p>
                {vsaRes.plain_english != null && <p className="text-xs text-slate-500">{String(vsaRes.plain_english)}</p>}
              </div>
            ) : vsaRes?.error ? <p className="text-xs text-rose-400">{String(vsaRes.error)}</p> : null
          )}

          {checked.elliott_wave && (
            ewMut.isPending ? <p className="text-xs text-slate-500">Loading Elliott Wave…</p> :
            ewMut.isError ? <p className="text-xs text-rose-400">Elliott Wave failed: {apiErrorMessage(ewMut.error)}</p> :
            ewRes && !ewRes.error ? (
              <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-2.5">
                <p><strong>🌊 Elliott Wave:</strong> <span className={verdictClass(String(ewRes.signal ?? ''))}>{String(ewRes.signal ?? 'NEUTRAL')}</span>
                  {' '}({String(ewRes.pattern ?? '—')}){ewRes.confidence_pct != null ? ` · ${fmtNum(ewRes.confidence_pct, 0)}% confidence` : ''}
                  {ewRes.sl_pct != null && ewRes.tp_pct != null ? ` · SL ${fmtNum(ewRes.sl_pct, 1)}% / TP ${fmtNum(ewRes.tp_pct, 1)}%` : ''}</p>
                {ewRes.plain_english != null && <p className="text-xs text-slate-500">{String(ewRes.plain_english)}</p>}
              </div>
            ) : ewRes?.error ? <p className="text-xs text-rose-400">{String(ewRes.error)}</p> : null
          )}

          {checked.mtf_trend_strength && (
            mtfTrendMut.isPending ? <p className="text-xs text-slate-500">Loading MTF Trend and Strength…</p> :
            mtfTrendMut.isError ? <p className="text-xs text-rose-400">MTF Trend and Strength failed: {apiErrorMessage(mtfTrendMut.error)}</p> :
            mtfTrendRes ? (
              <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-2.5">
                <p><strong>📶 MTF Trend and Strength:</strong> <span className={verdictClass(String(mtfTrendConfluence.verdict ?? ''))}>{String(mtfTrendConfluence.verdict ?? '—')}</span>
                  {mtfTrendTf.strength_label != null ? ` · Strength: ${String(mtfTrendTf.strength_label)}` : ''}
                  {mtfTrendTf.reversal_probability_pct != null ? ` · Reversal risk ${fmtNum(mtfTrendTf.reversal_probability_pct, 0)}%` : ''}</p>
                {mtfTrendTf.plain_english != null && <p className="text-xs text-slate-500">{String(mtfTrendTf.plain_english)}</p>}
              </div>
            ) : null
          )}

          {drillAiContext && (
            <AskAIPanel context={drillAiContext} section={`command-center/trade_setup/${ticker}`} className="mt-2" />
          )}
        </div>
      )}
    </div>
  )
}

function TradeSetupBucketTable({ items, timeframe, assetClass }: { items: Row[]; timeframe: string; assetClass: string }) {
  const { sorted, sortKey, sortDir, handleSort } = useSort(items, {
    ticker: (r) => String(r.ticker ?? ''),
    price: (r) => (r.price != null ? Number(r.price) : null),
    rsi: (r) => (r.rsi != null ? Number(r.rsi) : null),
    trend: (r) => String(r.trend_direction ?? ''),
    volume: (r) => (r.volume_ratio != null ? Number(r.volume_ratio) : null),
  })
  const [expanded, setExpanded] = useState<string | null>(null)
  return (
    <DataTable minWidth={480}>
      <thead>
        <tr>
          <Th />
          <SortableTh active={sortKey === 'ticker'} direction={sortDir} onSort={() => handleSort('ticker')}>Ticker</SortableTh>
          <SortableTh active={sortKey === 'price'} direction={sortDir} onSort={() => handleSort('price')}>Price</SortableTh>
          <SortableTh active={sortKey === 'rsi'} direction={sortDir} onSort={() => handleSort('rsi')}>RSI(14)</SortableTh>
          <SortableTh active={sortKey === 'trend'} direction={sortDir} onSort={() => handleSort('trend')}>Trend</SortableTh>
          <SortableTh active={sortKey === 'volume'} direction={sortDir} onSort={() => handleSort('volume')}>Volume x</SortableTh>
          <Th></Th>
        </tr>
      </thead>
      <tbody>
        {sorted.map((r, i) => {
          const ticker = String(r.ticker)
          const isOpen = expanded === ticker
          return (
            <Fragment key={`${ticker}-${i}`}>
              <tr className="cursor-pointer hover:bg-slate-800/20" onClick={() => setExpanded(isOpen ? null : ticker)}>
                <Td className="w-6 text-slate-500">{isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</Td>
                <Td className="font-medium text-white">{ticker}</Td>
                <Td>{fmtNum(r.price, 4)}</Td>
                <Td className={verdictClass(String(r.bucket ?? ''))}>{fmtNum(r.rsi, 1)}</Td>
                <Td>{String(r.trend_direction ?? '—')}</Td>
                <Td>{fmtNum(r.volume_ratio)}</Td>
                <Td onClick={(e) => e.stopPropagation()}>
                  <AddToWatchlistButton ticker={ticker} compact />
                </Td>
              </tr>
              {isOpen && (
                <tr>
                  <Td colSpan={6} className="whitespace-normal bg-slate-900/30">
                    <TradeSetupDrillDown ticker={ticker} timeframe={timeframe} assetClass={assetClass} />
                  </Td>
                </tr>
              )}
            </Fragment>
          )
        })}
      </tbody>
    </DataTable>
  )
}

function TradeSetupPanel({ data, assetClass }: { data: Row; assetClass: string }) {
  const timeframes = (data.timeframes as string[]) ?? []
  const grouped = (data.grouped as Record<string, Record<string, Row[]>>) ?? {}
  const results = (data.results as Row[]) ?? []
  const [activeTf, setActiveTf] = useState<string | null>(null)
  const tf = activeTf && timeframes.includes(activeTf) ? activeTf : timeframes[0]

  if (!timeframes.length) return <p className="text-sm text-slate-500">No results.</p>
  const errored = results.filter((r) => r.error)
  const buckets = (tf && grouped[tf]) || {}

  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-400">{results.length - errored.length} of {results.length} tickers analyzed · {String(data.market ?? '')}</p>

      <div className="flex flex-wrap gap-2">
        {timeframes.map((t) => (
          <Chip key={t} selected={tf === t} onClick={() => setActiveTf(t)}>{t}</Chip>
        ))}
      </div>

      {errored.length > 0 && (
        <Alert type="error">
          {errored.map((r) => `${String(r.ticker)}: ${String(r.error)}`).join(' · ')}
        </Alert>
      )}

      <div className="grid gap-4">
        {BUCKET_ORDER.map((bucket) => {
          const items = buckets[bucket] ?? []
          return (
            <div key={bucket} className="min-w-0">
              <div className={`mb-2 inline-flex items-center gap-2 rounded-lg border px-2.5 py-1 text-xs font-semibold uppercase tracking-wider ${BUCKET_CLASS[bucket] ?? ''}`}>
                {bucket} <span className="opacity-70">({items.length})</span>
              </div>
              {items.length > 0 && tf ? (
                <TradeSetupBucketTable items={items} timeframe={tf} assetClass={assetClass} />
              ) : (
                <p className="text-xs text-slate-500">No tickers in this zone on {tf}.</p>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function FundamentalAnalysisPanel({ data }: { data: Row }) {
  const results = (data.results as Row[]) ?? []
  const [idx, setIdx] = useState(0)
  const r = results[idx] ?? results[0] ?? {}
  const holdingTrend = (r.holding_trend as Record<string, Row>) ?? {}
  const holdingRows: (Row & { label: string })[] = Object.entries(holdingTrend).map(([label, info]) => ({ label, ...info }))
  const dhan = r.dhan as Row | undefined
  const peers = (dhan?.peers as Row) ?? {}
  const peerRows = (peers.peers as Row[]) ?? []
  const corpActs = (dhan?.corporate_actions as Row[]) ?? []

  const { sorted: sortedHolding, sortKey: holdingSortKey, sortDir: holdingSortDir, handleSort: handleHoldingSort } = useSort(holdingRows, {
    category: (h) => String(h.label ?? ''),
    latest: (h) => (h.latest_pct != null ? Number(h.latest_pct) : null),
    delta: (h) => (h.delta_pp_12m != null ? Number(h.delta_pp_12m) : null),
    trend: (h) => String(h.trend ?? ''),
    implication: (h) => String(h.implication ?? ''),
  })
  const { sorted: sortedPeers, sortKey: peersSortKey, sortDir: peersSortDir, handleSort: handlePeersSort } = useSort(peerRows, {
    symbol: (p) => String(p.symbol ?? ''),
    name: (p) => String(p.name ?? ''),
    price: (p) => (p.price != null ? Number(p.price) : null),
    pe: (p) => (p.pe != null ? Number(p.pe) : null),
    pb: (p) => (p.pb != null ? Number(p.pb) : null),
    roe: (p) => (p.roe_pct != null ? Number(p.roe_pct) : null),
    roce: (p) => (p.roce_pct != null ? Number(p.roce_pct) : null),
    div_yield: (p) => (p.div_yield_pct != null ? Number(p.div_yield_pct) : null),
    mkt_cap: (p) => (p.market_cap_cr != null ? Number(p.market_cap_cr) : null),
    ret_1y: (p) => (p.return_1y_pct != null ? Number(p.return_1y_pct) : null),
    qtr_growth: (p) => (p.qtr_profit_growth_pct != null ? Number(p.qtr_profit_growth_pct) : null),
  })
  const { sorted: sortedCorpActs, sortKey: corpActsSortKey, sortDir: corpActsSortDir, handleSort: handleCorpActsSort } = useSort(corpActs, {
    type: (a) => String(a.type ?? ''),
    announced: (a) => String(a.announced ?? ''),
    ex_date: (a) => String(a.ex_date ?? ''),
    record_date: (a) => String(a.record_date ?? ''),
    dividend_type: (a) => String(a.dividend_type ?? ''),
  })

  const ticker = String(r.ticker ?? '')
  const iaStatus = useQuery({ queryKey: ['investing-agent-status'], queryFn: fetchInvestingAgentStatus })
  const iaTokenSet = Boolean(iaStatus.data?.token_set)
  const iaStockCard = useQuery({
    queryKey: ['ia-stock-card', ticker],
    queryFn: () => fetchInvestingAgentStockCard(ticker),
    enabled: iaTokenSet && Boolean(ticker) && !r.error,
    retry: false,
  })
  const aiContext = String(r.ai_context ?? '')
  const aiSystemPrompt = String(data.ai_system_prompt ?? '')

  if (!results.length) return <p className="text-sm text-slate-500">No results.</p>
  const overall = (r.overall as Row) ?? {}
  const valuation = (r.valuation as Row) ?? {}
  const prTrend = (r.profit_revenue_trend as Row) ?? {}
  const debt = (r.debt as Row) ?? {}
  const prosCons = (r.pros_cons as Row) ?? {}
  const pros = (prosCons.pros as string[]) ?? []
  const cons = (prosCons.cons as string[]) ?? []
  const profile = (dhan?.profile as Row) ?? {}
  const industryPe = peers.industry_pe as number | undefined
  const opts = dhan?.options_snapshot as Row | undefined
  const rating = dhan?.analyst_rating as Row | undefined
  const returns = (dhan?.investment_returns as Row) ?? {}
  const salesCagr = (prTrend.sales_cagr as Row) ?? {}
  const profitCagr = (prTrend.profit_cagr as Row) ?? {}

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {results.map((res, i) => (
          <Chip key={`${String(res.ticker)}-${i}`} selected={idx === i} onClick={() => setIdx(i)}>
            {String(res.ticker)}
          </Chip>
        ))}
      </div>

      {r.error ? (
        <Alert type="error">{String(r.error)}</Alert>
      ) : (
        <>
          <div className="rounded-2xl border border-slate-800/80 bg-slate-900/40 px-4 py-5 sm:px-6">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs font-medium uppercase tracking-wider text-slate-500">Fundamental Analysis · {String(r.ticker)}</p>
              <AddToWatchlistButton ticker={String(r.ticker ?? '')} compact />
            </div>
            <p className={`mt-1 text-xl font-bold sm:text-2xl ${verdictClass(String(overall.signal ?? r.verdict ?? ''))}`}>
              {String(overall.signal ?? r.verdict ?? '—')} · {fmtNum(overall.confidence_pct, 0)}% confidence
            </p>
            {((overall.factors as string[]) ?? []).length > 0 && (
              <ul className="mt-2 space-y-1 text-sm text-slate-300">
                {(overall.factors as string[]).map((f, i) => <li key={i} className="flex gap-2"><span className="text-slate-500">•</span>{f}</li>)}
              </ul>
            )}
          </div>

          <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <StatCard label="Price" value={`₹${fmtNum(r.current_price, 2)}`} />
            <StatCard label="Market Cap" value={`₹${fmtNum(r.market_cap_cr, 0)} Cr`} />
            <StatCard label="P/E" value={fmtNum(r.pe, 1)} />
            <StatCard label="ROCE" value={`${fmtNum(r.roce_pct, 1)}%`} />
            <StatCard label="ROE" value={`${fmtNum(r.roe_pct, 1)}%`} />
            <StatCard label="Div Yield" value={`${fmtNum(r.dividend_yield_pct, 2)}%`} />
          </div>

          {valuation.label != null && (
            <div className="rounded-xl border border-slate-800/80 bg-slate-900/40 px-4 py-3">
              <p className={`font-semibold ${verdictClass(String(valuation.label ?? ''))}`}>{String(valuation.label)}</p>
              <p className="mt-1 text-sm text-slate-400">{String(valuation.reason ?? '')}</p>
            </div>
          )}

          {Object.keys(holdingTrend).length > 0 && (
            <div>
              <h4 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">Shareholding trend (~12 months)</h4>
              <DataTable minWidth={640}>
                <thead>
                  <tr>
                    <SortableTh active={holdingSortKey === 'category'} direction={holdingSortDir} onSort={() => handleHoldingSort('category')}>Category</SortableTh>
                    <SortableTh active={holdingSortKey === 'implication'} direction={holdingSortDir} onSort={() => handleHoldingSort('implication')}>Implication</SortableTh>
                    <SortableTh active={holdingSortKey === 'trend'} direction={holdingSortDir} onSort={() => handleHoldingSort('trend')}>Trend</SortableTh>
                    <SortableTh active={holdingSortKey === 'latest'} direction={holdingSortDir} onSort={() => handleHoldingSort('latest')}>Latest %</SortableTh>
                    <SortableTh active={holdingSortKey === 'delta'} direction={holdingSortDir} onSort={() => handleHoldingSort('delta')}>Δ 12m (pp)</SortableTh>
                  </tr>
                </thead>
                <tbody>
                  {sortedHolding.map((info) => (
                    <tr key={String(info.label)}>
                      <Td>{String(info.label)}</Td>
                      <Td className="max-w-xs truncate">{String(info.implication ?? '—')}</Td>
                      <Td>{String(info.trend ?? '—')}</Td>
                      <Td>{fmtNum(info.latest_pct, 1)}</Td>
                      <Td>{fmtNum(info.delta_pp_12m, 1)}</Td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            </div>
          )}

          <div>
            <h4 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">Profit &amp; Revenue trend (TTM)</h4>
            <div className="grid gap-3 sm:grid-cols-3">
              <StatCard label="Revenue TTM growth" value={`${fmtNum(prTrend.revenue_ttm_growth_pct, 1)}%`} />
              <StatCard label="Profit TTM growth" value={`${fmtNum(prTrend.profit_ttm_growth_pct, 1)}%`} />
              <StatCard label="Debt trend" value={String(debt.trend ?? 'N/A')} />
            </div>
            <div className="mt-3">
              <DataTable minWidth={480}>
                <thead><tr><Th>Period</Th><Th>Sales CAGR %</Th><Th>Profit CAGR %</Th></tr></thead>
                <tbody>
                  {['10 Years', '5 Years', '3 Years', 'TTM'].map((period) => (
                    <tr key={period}>
                      <Td>{period}</Td>
                      <Td>{fmtNum(salesCagr[period], 1)}</Td>
                      <Td>{fmtNum(profitCagr[period], 1)}</Td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            </div>
          </div>

          {(pros.length > 0 || cons.length > 0) && (
            <div className="grid gap-4">
              <div>
                <h4 className="mb-2 text-sm font-semibold text-emerald-400">✅ Pros (screener.in)</h4>
                {pros.length > 0 ? (
                  <ul className="space-y-1 text-sm text-slate-300">{pros.map((p, i) => <li key={i}>- {p}</li>)}</ul>
                ) : <p className="text-sm text-slate-500">None flagged.</p>}
              </div>
              <div>
                <h4 className="mb-2 text-sm font-semibold text-rose-400">⚠️ Cons (screener.in)</h4>
                {cons.length > 0 ? (
                  <ul className="space-y-1 text-sm text-slate-300">{cons.map((c, i) => <li key={i}>- {c}</li>)}</ul>
                ) : <p className="text-sm text-slate-500">None flagged.</p>}
              </div>
            </div>
          )}

          {dhan ? (
            <>
              <div>
                <h4 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">Company Profile &amp; Peer Comparison (Dhan.co)</h4>
                <div className="grid gap-3 sm:grid-cols-4">
                  <StatCard label="Sector" value={String(profile.sector ?? '—')} />
                  <StatCard label="Industry" value={String(profile.industry ?? '—')} />
                  <StatCard label="Classification" value={String(profile.classification ?? '—')} />
                  <StatCard label="Industry P/E" value={industryPe != null ? `${fmtNum(industryPe, 1)}x` : '—'} />
                </div>
                {peerRows.length > 0 && (
                  <div className="mt-3">
                    <DataTable minWidth={900}>
                      <thead>
                        <tr>
                          <SortableTh active={peersSortKey === 'symbol'} direction={peersSortDir} onSort={() => handlePeersSort('symbol')}>Symbol</SortableTh>
                          <SortableTh active={peersSortKey === 'name'} direction={peersSortDir} onSort={() => handlePeersSort('name')}>Name</SortableTh>
                          <SortableTh active={peersSortKey === 'price'} direction={peersSortDir} onSort={() => handlePeersSort('price')}>Price</SortableTh>
                          <SortableTh active={peersSortKey === 'pe'} direction={peersSortDir} onSort={() => handlePeersSort('pe')}>P/E</SortableTh>
                          <SortableTh active={peersSortKey === 'pb'} direction={peersSortDir} onSort={() => handlePeersSort('pb')}>P/B</SortableTh>
                          <SortableTh active={peersSortKey === 'roe'} direction={peersSortDir} onSort={() => handlePeersSort('roe')}>ROE %</SortableTh>
                          <SortableTh active={peersSortKey === 'roce'} direction={peersSortDir} onSort={() => handlePeersSort('roce')}>ROCE %</SortableTh>
                          <SortableTh active={peersSortKey === 'div_yield'} direction={peersSortDir} onSort={() => handlePeersSort('div_yield')}>Div Yield %</SortableTh>
                          <SortableTh active={peersSortKey === 'mkt_cap'} direction={peersSortDir} onSort={() => handlePeersSort('mkt_cap')}>Mkt Cap (Cr)</SortableTh>
                          <SortableTh active={peersSortKey === 'ret_1y'} direction={peersSortDir} onSort={() => handlePeersSort('ret_1y')}>1Y Return %</SortableTh>
                          <SortableTh active={peersSortKey === 'qtr_growth'} direction={peersSortDir} onSort={() => handlePeersSort('qtr_growth')}>Qtr Profit Growth %</SortableTh>
                        </tr>
                      </thead>
                      <tbody>
                        {sortedPeers.map((p, i) => (
                          <tr key={i}>
                            <Td>{String(p.symbol ?? '—')}</Td>
                            <Td>{String(p.name ?? '—')}</Td>
                            <Td>{fmtNum(p.price)}</Td>
                            <Td>{fmtNum(p.pe, 1)}</Td>
                            <Td>{fmtNum(p.pb, 1)}</Td>
                            <Td>{fmtNum(p.roe_pct, 1)}</Td>
                            <Td>{fmtNum(p.roce_pct, 1)}</Td>
                            <Td>{fmtNum(p.div_yield_pct, 1)}</Td>
                            <Td>{fmtNum(p.market_cap_cr, 0)}</Td>
                            <Td>{fmtNum(p.return_1y_pct, 1)}</Td>
                            <Td>{fmtNum(p.qtr_profit_growth_pct, 1)}</Td>
                          </tr>
                        ))}
                      </tbody>
                    </DataTable>
                  </div>
                )}
              </div>

              {rating && (
                <div>
                  <h4 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">Analyst Rating Consensus</h4>
                  <div className="grid gap-3 sm:grid-cols-4">
                    <StatCard label="Consensus" value={String(rating.rating ?? '—')} />
                    <StatCard label="Buy" value={`${String(rating.buy ?? 0)} (${fmtNum(rating.buy_pct, 0)}%)`} />
                    <StatCard label="Hold" value={`${String(rating.hold ?? 0)} (${fmtNum(rating.hold_pct, 0)}%)`} />
                    <StatCard label="Sell" value={`${String(rating.sell ?? 0)} (${fmtNum(rating.sell_pct, 0)}%)`} />
                  </div>
                  <p className="mt-2 text-xs text-slate-500">Based on {String(rating.total_analysts ?? 0)} analysts.</p>
                </div>
              )}

              {Object.keys(returns).length > 0 && (
                <div>
                  <h4 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">Investment Returns</h4>
                  <div className="grid grid-cols-3 gap-3 sm:grid-cols-5 lg:grid-cols-10">
                    {Object.entries(returns).map(([period, val]) => (
                      <StatCard key={period} label={period.toUpperCase()} value={val != null ? `${Number(val) >= 0 ? '+' : ''}${fmtNum(val, 1)}%` : '—'} />
                    ))}
                  </div>
                </div>
              )}

              {opts && (
                <div>
                  <h4 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">
                    Options Snapshot ({String(opts.expiry_days ?? '—')} days to nearest expiry)
                  </h4>
                  <div className="grid gap-3 sm:grid-cols-4">
                    <StatCard label="PCR" value={fmtNum(opts.pcr, 2)} />
                    <StatCard label="ATM IV" value={`${fmtNum(opts.atm_iv, 1)}%`} />
                    <StatCard label="Max Pain" value={String(opts.max_pain_strike ?? '—')} />
                    <StatCard label="ATM Strike" value={String(opts.atm_strike ?? '—')} />
                  </div>
                  <div className="mt-3 grid gap-3 sm:grid-cols-4">
                    <StatCard label="OI Support" value={String(opts.oi_support ?? '—')} />
                    <StatCard label="OI Resistance" value={String(opts.oi_resistance ?? '—')} />
                    <StatCard label="Total Call OI" value={fmtNum(opts.total_call_oi, 0)} />
                    <StatCard label="Total Put OI" value={fmtNum(opts.total_put_oi, 0)} />
                  </div>
                  <p className="mt-2 text-xs text-slate-500">PCR and max pain are sentiment/positioning indicators, not standalone trade signals.</p>
                </div>
              )}

              {corpActs.length > 0 && (
                <div>
                  <h4 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">Corporate Actions</h4>
                  <DataTable minWidth={640}>
                    <thead>
                      <tr>
                        <SortableTh active={corpActsSortKey === 'type'} direction={corpActsSortDir} onSort={() => handleCorpActsSort('type')}>Type</SortableTh>
                        <SortableTh active={corpActsSortKey === 'announced'} direction={corpActsSortDir} onSort={() => handleCorpActsSort('announced')}>Announced</SortableTh>
                        <SortableTh active={corpActsSortKey === 'ex_date'} direction={corpActsSortDir} onSort={() => handleCorpActsSort('ex_date')}>Ex-Date</SortableTh>
                        <SortableTh active={corpActsSortKey === 'record_date'} direction={corpActsSortDir} onSort={() => handleCorpActsSort('record_date')}>Record Date</SortableTh>
                        <SortableTh active={corpActsSortKey === 'dividend_type'} direction={corpActsSortDir} onSort={() => handleCorpActsSort('dividend_type')}>Dividend Type</SortableTh>
                      </tr>
                    </thead>
                    <tbody>
                      {sortedCorpActs.map((a, i) => (
                        <tr key={i}>
                          <Td>{String(a.type ?? '—')}</Td>
                          <Td>{String(a.announced ?? '—')}</Td>
                          <Td>{String(a.ex_date ?? '—')}</Td>
                          <Td>{String(a.record_date ?? '—')}</Td>
                          <Td>{String(a.dividend_type ?? '—')}</Td>
                        </tr>
                      ))}
                    </tbody>
                  </DataTable>
                </div>
              )}

              {dhan.source_url != null && (
                <p className="text-xs text-slate-500">
                  Dhan source: <a href={String(dhan.source_url)} target="_blank" rel="noreferrer" className="underline hover:text-slate-300">{String(dhan.source_url)}</a>
                </p>
              )}
            </>
          ) : (
            <p className="text-xs text-slate-500">
              ℹ️ Dhan.co enrichment (peers/industry P/E, options snapshot, analyst rating, corporate actions) isn't available for this ticker — showing screener.in data only.
            </p>
          )}

          {r.source_url != null && (
            <p className="text-xs text-slate-500">
              Source: <a href={String(r.source_url)} target="_blank" rel="noreferrer" className="underline hover:text-slate-300">{String(r.source_url)}</a>
            </p>
          )}

          <div>
            <h4 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">Investing Agent scorecard</h4>
            {!iaTokenSet && !iaStatus.isLoading && (
              <p className="text-xs text-slate-500">
                ℹ️ Save a SuperInvesting Bearer token under Manage → AI Settings to pull the Investing Agent's
                sentiment score, sector/persona ranking, and 3Y return alongside screener.in/Dhan data.
              </p>
            )}
            {iaTokenSet && iaStockCard.isLoading && <p className="text-xs text-slate-500">Loading Investing Agent scorecard…</p>}
            {iaTokenSet && iaStockCard.isError && (
              <p className="text-xs text-amber-400">Investing Agent scorecard unavailable: {apiErrorMessage(iaStockCard.error)}</p>
            )}
            {iaTokenSet && iaStockCard.data && (
              <StockScorecardView data={iaStockCard.data as StockCardData} symbol={ticker} />
            )}
          </div>

          <AskAIPanel context={aiContext} systemPrompt={aiSystemPrompt} section={`command-center/fundamental_analysis/${ticker}`} />
        </>
      )}
    </div>
  )
}

function OneClickPanel({ data, style }: { data: Row; style: 'intraday' | 'scalping' | 'swing' }) {
  const results = (data.results as Row[]) ?? []
  const [idx, setIdx] = useState(0)
  const r = results[idx] ?? results[0] ?? {}
  const combo = (r.combo as Row) ?? {}
  const votes = (combo.votes as Row[]) ?? []
  const { sorted: sortedVotes, sortKey: votesSortKey, sortDir: votesSortDir, handleSort: handleVotesSort } = useSort(votes, {
    engine: (v) => String(v.engine ?? ''),
    direction: (v) => String(v.direction ?? ''),
    confidence: (v) => (v.confidence != null ? Number(v.confidence) : null),
    take: (v) => (v.take ? 1 : 0),
    agreed: (v) => (v.agreed ? 1 : v.direction === 'WAIT' ? 0 : -1),
    note: (v) => (v.error != null ? String(v.error) : String(((v.reasons as string[]) ?? [])[0] ?? '')),
  })
  if (!results.length) return <p className="text-sm text-slate-500">No results.</p>
  const combofa = r.fundamentals_combo as Row | undefined

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {results.map((res, i) => (
          <Chip key={`${String(res.ticker)}-${i}`} selected={idx === i} onClick={() => setIdx(i)}>
            {String(res.ticker)}
          </Chip>
        ))}
      </div>

      {r.error ? (
        <Alert type="error">{String(r.error)}</Alert>
      ) : (
        <>
          <div className="rounded-2xl border border-slate-800/80 bg-slate-900/40 px-4 py-5 sm:px-6">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs font-medium uppercase tracking-wider text-slate-500">
                One-Click {style.charAt(0).toUpperCase() + style.slice(1)} · {String(r.ticker)}
              </p>
              <AddToWatchlistButton ticker={String(r.ticker ?? '')} compact />
            </div>
            <p className={`mt-1 text-xl font-bold sm:text-2xl ${verdictClass(String(combo.verdict ?? ''))}`}>
              {String(combo.verdict ?? '—')}
            </p>
            <p className="mt-2 text-sm text-slate-300">
              {String(combo.n_agree ?? 0)} of {String(combo.n_total ?? 0)} engines agree
              {combo.min_agree_required != null ? ` (need ${String(combo.min_agree_required)})` : ''}
              {' '}· confidence {fmtNum(combo.confidence_pct, 0)}% · take threshold {fmtNum(combo.take_threshold, 0)}%
            </p>
            {combofa && (
              <div className="mt-2 text-sm text-slate-400">
                <p>{String(combofa.note ?? '')}</p>
                <p className="text-xs text-slate-500">Technical-only confidence was {fmtNum(r.technical_confidence_pct, 0)}%.</p>
              </div>
            )}
            <div className="mt-3 flex flex-wrap gap-3 text-sm">
              <span className="rounded-lg bg-slate-800/60 px-3 py-1 text-slate-200">
                Direction: <strong>{String(combo.direction ?? '—')}</strong>
              </span>
              <span className="rounded-lg bg-slate-800/60 px-3 py-1 text-slate-200">
                Take trade: <strong>{combo.take_trade ? 'Yes' : 'No'}</strong>
              </span>
              {combo.strictness != null && (
                <span className="rounded-lg bg-slate-800/60 px-3 py-1 text-slate-200">
                  Strictness: <strong>{String(combo.strictness)}</strong>
                </span>
              )}
              {style === 'intraday' && r.regime != null && (
                <span className="rounded-lg bg-slate-800/60 px-3 py-1 text-slate-200">
                  Regime: <strong>{String(r.regime)}</strong>
                </span>
              )}
              {style === 'scalping' && (
                <>
                  <span className="rounded-lg bg-slate-800/60 px-3 py-1 text-slate-200">
                    Session OK: <strong>{r.session_ok ? 'Yes' : 'No'}</strong>
                  </span>
                  {r.rvol != null && (
                    <span className="rounded-lg bg-slate-800/60 px-3 py-1 text-slate-200">
                      RVOL: <strong>{fmtNum(r.rvol, 2)}x</strong>
                    </span>
                  )}
                  {r.htf != null && (
                    <span className="rounded-lg bg-slate-800/60 px-3 py-1 text-slate-200">
                      HTF/LTF: <strong>{String(r.htf)}/{String(r.ltf)}</strong>
                    </span>
                  )}
                </>
              )}
            </div>
          </div>

          {(combo.entry_price != null || combo.stop_price != null || combo.target1_price != null || combo.target2_price != null) && (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <StatCard label="Entry" value={fmtNum(combo.entry_price, 4)} />
              <StatCard label="Stop" value={fmtNum(combo.stop_price, 4)} />
              <StatCard label="TP1 (partial, SL→BE)" value={fmtNum(combo.target1_price, 4)} />
              <StatCard label="TP2 (runner)" value={fmtNum(combo.target2_price, 4)} />
            </div>
          )}

          {votes.length > 0 && (
            <div>
              <h4 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">Engine votes</h4>
              <DataTable minWidth={720}>
                <thead>
                  <tr>
                    <SortableTh active={votesSortKey === 'engine'} direction={votesSortDir} onSort={() => handleVotesSort('engine')}>Engine</SortableTh>
                    <SortableTh active={votesSortKey === 'direction'} direction={votesSortDir} onSort={() => handleVotesSort('direction')}>Direction</SortableTh>
                    <SortableTh active={votesSortKey === 'take'} direction={votesSortDir} onSort={() => handleVotesSort('take')}>Take</SortableTh>
                    <SortableTh active={votesSortKey === 'agreed'} direction={votesSortDir} onSort={() => handleVotesSort('agreed')}>Agreed</SortableTh>
                    <SortableTh active={votesSortKey === 'confidence'} direction={votesSortDir} onSort={() => handleVotesSort('confidence')}>Confidence</SortableTh>
                    <SortableTh active={votesSortKey === 'note'} direction={votesSortDir} onSort={() => handleVotesSort('note')}>Note</SortableTh>
                  </tr>
                </thead>
                <tbody>
                  {sortedVotes.map((v, i) => (
                    <tr key={i}>
                      <Td>{String(v.engine ?? '—')}</Td>
                      <Td className={verdictClass(String(v.direction ?? ''))}>{String(v.direction ?? '—')}</Td>
                      <Td>{v.take ? '✅' : '—'}</Td>
                      <Td>{v.agreed ? '✅' : (v.direction === 'WAIT' ? '⚪' : '❌')}</Td>
                      <Td>{v.confidence != null ? `${fmtNum(v.confidence, 0)}%` : '—'}</Td>
                      <Td className="max-w-xs truncate text-slate-400">
                        {v.error != null ? String(v.error) : String(((v.reasons as string[]) ?? [])[0] ?? '')}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            </div>
          )}

          {((combo.reasons as string[]) ?? []).length > 0 && (
            <div>
              <h4 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">Full reasoning</h4>
              <ul className="space-y-1.5 text-sm text-slate-300">
                {(combo.reasons as string[]).map((rr, i) => (
                  <li key={i} className="flex gap-2"><span className="text-slate-500">•</span>{rr}</li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function MoversTable({ label, bundle }: { label: string; bundle: Row | undefined }) {
  if (!bundle) return null
  const gainers = (bundle.gainers as Row[]) ?? []
  const losers = (bundle.losers as Row[]) ?? []
  if (bundle.error != null && !gainers.length && !losers.length) {
    return (
      <div>
        <h5 className="mb-2 text-sm font-semibold text-white">{label}</h5>
        <p className="text-xs text-amber-300">{String(bundle.error)}</p>
      </div>
    )
  }
  const rowLabel = (row: Row) => String(row.symbol ?? row.name ?? '—')
  return (
    <div>
      <h5 className="mb-2 text-sm font-semibold text-white">
        {label}{bundle.source != null ? <span className="ml-2 text-xs font-normal text-slate-500">({String(bundle.source)})</span> : null}
      </h5>
      <div className="grid gap-4">
        <div>
          <p className="mb-1 text-xs font-medium uppercase tracking-wider text-emerald-400">Gainers</p>
          <ul className="space-y-1 text-sm text-slate-300">
            {gainers.slice(0, 8).map((g, i) => (
              <li key={i} className="flex justify-between"><span>{rowLabel(g)}</span><span className="text-emerald-400">+{fmtNum(g.pct, 2)}%</span></li>
            ))}
            {!gainers.length && <li className="text-slate-500">—</li>}
          </ul>
        </div>
        <div>
          <p className="mb-1 text-xs font-medium uppercase tracking-wider text-rose-400">Losers</p>
          <ul className="space-y-1 text-sm text-slate-300">
            {losers.slice(0, 8).map((l, i) => (
              <li key={i} className="flex justify-between"><span>{rowLabel(l)}</span><span className="text-rose-400">{fmtNum(l.pct, 2)}%</span></li>
            ))}
            {!losers.length && <li className="text-slate-500">—</li>}
          </ul>
        </div>
      </div>
    </div>
  )
}

function GlobalMarketMoodPanel({ data }: { data: Row }) {
  const composite = (data.composite as Row) ?? {}
  const regions = (data.regions as Record<string, Row>) ?? {}
  const sectors = (data.sectors as Row) ?? {}
  const news = (data.geopolitical_news as Row[]) ?? []
  const indiaSentiment = data.india_sentiment as Row | undefined
  const movers = (data.stock_movers as Row) ?? {}
  const [moversTab, setMoversTab] = useState<'india' | 'us' | 'crypto'>('india')
  const leadingRows = ((sectors.leading as Row[]) ?? []).slice(0, 8)
  const laggingRows = ((sectors.lagging as Row[]) ?? []).slice(0, 8)
  const sectorAccessors = {
    sector: (s: Row) => String(s.name ?? ''),
    pct: (s: Row) => (s.pct != null ? Number(s.pct) : null),
    adv: (s: Row) => (s.advances != null ? Number(s.advances) : null),
    dec: (s: Row) => (s.declines != null ? Number(s.declines) : null),
  }
  const { sorted: sortedLeading, sortKey: leadingSortKey, sortDir: leadingSortDir, handleSort: handleLeadingSort } = useSort(leadingRows, sectorAccessors)
  const { sorted: sortedLagging, sortKey: laggingSortKey, sortDir: laggingSortDir, handleSort: handleLaggingSort } = useSort(laggingRows, sectorAccessors)

  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-slate-800/80 bg-slate-900/40 px-4 py-5 sm:px-6">
        <p className="text-xs font-medium uppercase tracking-wider text-slate-500">Composite mood</p>
        <p className={`mt-1 text-2xl font-bold ${verdictClass(String(composite.mood ?? ''))}`}>
          {String(composite.mood_emoji ?? '')} {String(composite.mood ?? '—')}
          {composite.avg_pct != null ? ` (${Number(composite.avg_pct).toFixed(2)}%)` : ''}
        </p>
        {indiaSentiment && (
          <p className="mt-2 text-sm text-slate-400">
            India sentiment: <strong>{String(indiaSentiment.label ?? indiaSentiment.sentiment ?? '—')}</strong>
            {indiaSentiment.score != null ? ` (${fmtNum(indiaSentiment.score, 1)})` : ''}
          </p>
        )}
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {Object.values(regions).map((r) => (
          <div key={String(r.region_id)} className="rounded-2xl border border-slate-800/80 bg-slate-900/40 p-4">
            <p className="text-xs font-medium uppercase tracking-wider text-slate-500">
              {String(r.emoji ?? '')} {String(r.label ?? r.region_id ?? '—')}
            </p>
            <p className={`mt-1 text-lg font-bold ${verdictClass(String(r.mood ?? ''))}`}>
              {String(r.mood_emoji ?? '')} {String(r.mood ?? '—')}
            </p>
            <p className="mt-1 text-xs text-slate-400">
              {fmtNum(r.avg_pct, 2)}% avg · 🟢{String(r.green_count ?? 0)} 🔴{String(r.red_count ?? 0)}
            </p>
            {r.headline != null && String(r.headline).trim() && (
              <p className="mt-1 text-xs text-amber-300">{String(r.headline)}</p>
            )}
            {((r.instruments as Row[]) ?? []).length > 0 && (
              <ul className="mt-2 space-y-0.5 text-xs text-slate-400">
                {((r.instruments as Row[]) ?? []).slice(0, 3).map((inst, i) => (
                  <li key={i} className="flex justify-between">
                    <span>{String(inst.name ?? '—')}</span>
                    <span className={Number(inst.pct ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                      {fmtNum(inst.pct, 2)}%
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>

      {((sectors.leading as Row[]) ?? []).length > 0 && (
        <div>
          <div className="grid gap-4">
            <div className="min-w-0">
              <h4 className="mb-2 text-sm font-semibold text-emerald-400">Leading sectors</h4>
              <DataTable minWidth={360}>
                <thead>
                  <tr>
                    <SortableTh active={leadingSortKey === 'sector'} direction={leadingSortDir} onSort={() => handleLeadingSort('sector')}>Sector</SortableTh>
                    <SortableTh active={leadingSortKey === 'pct'} direction={leadingSortDir} onSort={() => handleLeadingSort('pct')}>% Chg</SortableTh>
                    <SortableTh active={leadingSortKey === 'adv'} direction={leadingSortDir} onSort={() => handleLeadingSort('adv')}>Adv</SortableTh>
                    <SortableTh active={leadingSortKey === 'dec'} direction={leadingSortDir} onSort={() => handleLeadingSort('dec')}>Dec</SortableTh>
                  </tr>
                </thead>
                <tbody>
                  {sortedLeading.map((s, i) => (
                    <tr key={i}>
                      <Td>{String(s.name)}</Td>
                      <Td className="text-emerald-400">{fmtNum(s.pct, 2)}%</Td>
                      <Td>{String(s.advances ?? '—')}</Td>
                      <Td>{String(s.declines ?? '—')}</Td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            </div>
            <div className="min-w-0">
              <h4 className="mb-2 text-sm font-semibold text-rose-400">Lagging sectors</h4>
              <DataTable minWidth={360}>
                <thead>
                  <tr>
                    <SortableTh active={laggingSortKey === 'sector'} direction={laggingSortDir} onSort={() => handleLaggingSort('sector')}>Sector</SortableTh>
                    <SortableTh active={laggingSortKey === 'pct'} direction={laggingSortDir} onSort={() => handleLaggingSort('pct')}>% Chg</SortableTh>
                    <SortableTh active={laggingSortKey === 'adv'} direction={laggingSortDir} onSort={() => handleLaggingSort('adv')}>Adv</SortableTh>
                    <SortableTh active={laggingSortKey === 'dec'} direction={laggingSortDir} onSort={() => handleLaggingSort('dec')}>Dec</SortableTh>
                  </tr>
                </thead>
                <tbody>
                  {sortedLagging.map((s, i) => (
                    <tr key={i}>
                      <Td>{String(s.name)}</Td>
                      <Td className="text-rose-400">{fmtNum(s.pct, 2)}%</Td>
                      <Td>{String(s.advances ?? '—')}</Td>
                      <Td>{String(s.declines ?? '—')}</Td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            </div>
          </div>
          {sectors.prediction != null && String(sectors.prediction).trim() && (
            <p className="mt-3 text-sm text-slate-300">{String(sectors.prediction)}</p>
          )}
        </div>
      )}

      {Boolean(movers.india || movers.us || movers.crypto) && (
        <div>
          <h4 className="mb-2 text-sm font-semibold text-white">Stock Leaders &amp; Laggards</h4>
          <div className="mb-3 flex flex-wrap gap-2">
            <Chip selected={moversTab === 'india'} onClick={() => setMoversTab('india')}>🇮🇳 India</Chip>
            <Chip selected={moversTab === 'us'} onClick={() => setMoversTab('us')}>🇺🇸 US</Chip>
            <Chip selected={moversTab === 'crypto'} onClick={() => setMoversTab('crypto')}>₿ Crypto</Chip>
          </div>
          {moversTab === 'india' && <MoversTable label={String((movers.india as Row)?.label ?? 'India')} bundle={movers.india as Row | undefined} />}
          {moversTab === 'us' && <MoversTable label={String((movers.us as Row)?.label ?? 'US')} bundle={movers.us as Row | undefined} />}
          {moversTab === 'crypto' && <MoversTable label={String((movers.crypto as Row)?.label ?? 'Crypto')} bundle={movers.crypto as Row | undefined} />}
        </div>
      )}

      {news.length > 0 && (
        <div>
          <h4 className="mb-2 text-sm font-semibold text-white">Geopolitical headlines</h4>
          <ul className="space-y-2 text-sm text-slate-300">
            {news.slice(0, 10).map((n, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-slate-500">•</span>
                <span>
                  {n.link != null ? (
                    <a href={String(n.link)} target="_blank" rel="noreferrer" className="text-blue-400 hover:underline">
                      {String(n.title ?? n.headline ?? '')}
                    </a>
                  ) : String(n.title ?? n.headline ?? '')}
                  <span className="ml-1.5 text-xs text-slate-500">
                    {n.source != null ? `(${String(n.source)})` : ''}{n.age_hours != null ? ` · ${fmtNum(n.age_hours, 0)}h ago` : ''}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {data.built_at != null && (
        <p className="text-xs text-slate-500">Built at {String(data.built_at)}</p>
      )}
    </div>
  )
}

function MegaSetupAdvisorPanel({ data }: { data: Row }) {
  const enabled = (data.enabled_labels as string[]) ?? []
  const rationale = (data.rationale as string[]) ?? []
  const timeframes = (data.timeframes as string[]) ?? []
  const aiReport = data.ai_report as string | undefined
  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-slate-800/80 bg-slate-900/40 px-4 py-5 sm:px-6">
        <p className="text-xs font-medium uppercase tracking-wider text-slate-500">Recommended scenario</p>
        <p className="mt-1 text-xl font-bold text-white">{String(data.scenario ?? '—')}</p>
        <p className="mt-1 text-sm text-slate-400">Source: {String(data.source ?? 'rule_based')}</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <StatCard label="Asset class" value={String(data.asset_class ?? '—')} />
        <StatCard label="Market" value={String(data.market ?? '—')} />
        <StatCard label="Timeframes" value={timeframes.length ? timeframes.join(', ') : '—'} />
      </div>
      {rationale.length > 0 && (
        <ul className="space-y-1.5 text-sm text-slate-300">
          {rationale.map((r, i) => <li key={i} className="flex gap-2"><span className="text-slate-500">•</span>{r}</li>)}
        </ul>
      )}
      {enabled.length > 0 && (
        <div>
          <h4 className="mb-2 text-sm font-semibold text-white">Enabled modules ({enabled.length})</h4>
          <div className="flex flex-wrap gap-1.5">
            {enabled.map((l) => <span key={l} className="rounded-lg bg-slate-800/60 px-2.5 py-1 text-xs text-slate-300">{l}</span>)}
          </div>
        </div>
      )}
      {aiReport != null && String(aiReport).trim() && (
        <div>
          <h4 className="mb-2 text-sm font-semibold text-white">AI report</h4>
          <p className="whitespace-pre-wrap rounded-xl border border-slate-800/60 bg-slate-900/30 p-4 text-sm leading-relaxed text-slate-300">
            {aiReport}
          </p>
        </div>
      )}
    </div>
  )
}

const _CATEGORY_LABELS: Record<string, string> = {
  BLOCK_DEAL: '🧱 Block Deal',
  MERGER_ACQUISITION: '🤝 Merger / Acquisition',
  UPGRADE: '⬆️ Upgrade',
  DOWNGRADE: '⬇️ Downgrade',
  TARGET_RAISE: '🎯 Target Raise',
  TARGET_CUT: '🎯 Target Cut',
  RERATING: '🔁 Re-rating',
  INITIATE: '🆕 Coverage Initiated',
  REITERATE: '🔂 Reiterated',
  RECOMMENDATION: '📋 Analyst Recommendation',
}

function StockUpgradeDowngradePanel({ data }: { data: Row }) {
  const results = (data.results as Row[]) ?? []
  const [idx, setIdx] = useState(0)
  const r = results[idx] ?? results[0] ?? {}
  const items = (r.items as Row[]) ?? []
  const { sorted: sortedItems, sortKey: itemsSortKey, sortDir: itemsSortDir, handleSort: handleItemsSort } = useSort(items, {
    category: (it) => String(it.category_label ?? it.call_type ?? ''),
    action: (it) => String(it.action ?? ''),
    brokerage: (it) => String(it.brokerage ?? ''),
    target: (it) => String(it.price_target ?? ''),
    title: (it) => String(it.title ?? ''),
    published: (it) => String(it.published ?? ''),
  })
  if (!results.length) return <p className="text-sm text-slate-500">No results.</p>
  const consensus = (r.consensus as Row) ?? {}
  const sitesChecked = (r.sites_checked as string[]) ?? []
  const categoryCounts = (r.category_counts as Record<string, number>) ?? {}

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {results.map((res, i) => (
          <Chip key={`${String(res.ticker)}-${i}`} selected={idx === i} onClick={() => setIdx(i)}>
            {String(res.ticker)}
          </Chip>
        ))}
      </div>

      <div className="rounded-2xl border border-slate-800/80 bg-slate-900/40 px-4 py-5 sm:px-6">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs font-medium uppercase tracking-wider text-slate-500">Upgrade/Downgrade · {String(r.ticker)}</p>
          <AddToWatchlistButton ticker={String(r.ticker ?? '')} compact />
        </div>
        <p className={`mt-1 text-xl font-bold sm:text-2xl ${verdictClass(String(consensus.consensus ?? ''))}`}>
          {String(consensus.consensus ?? 'NO DATA')}
        </p>
        <p className="mt-1 text-sm text-slate-400">
          {String(r.item_count ?? 0)} item(s) · Latest target {String(consensus.latest_target ?? '—')} ·
          {' '}Buy/Sell/Hold {String(consensus.buy ?? 0)}/{String(consensus.sell ?? 0)}/{String(consensus.hold ?? 0)}
        </p>
        {consensus.weighted_buy != null && (
          <p className="mt-1 text-xs text-slate-500">
            Brokerage-tier &amp; recency-weighted (bulge-bracket &amp; same-day calls count more than an unrated/older one): Buy {fmtNum(consensus.weighted_buy, 1)} · Sell {fmtNum(consensus.weighted_sell, 1)} · Hold {fmtNum(consensus.weighted_hold, 1)}
          </p>
        )}
        {sitesChecked.length > 0 && (
          <p className="mt-2 text-xs text-slate-500">Sites checked: {sitesChecked.map((s) => `✅ ${s}`).join('  ')}</p>
        )}
      </div>

      {Object.keys(categoryCounts).length > 0 && (
        <div className="grid gap-3 sm:grid-cols-4">
          {Object.entries(categoryCounts)
            .filter(([, count]) => count > 0)
            .map(([key, count]) => (
              <StatCard key={key} label={_CATEGORY_LABELS[key] ?? key} value={count} />
            ))}
          {Object.values(categoryCounts).every((c) => !c) && (
            <p className="col-span-full text-sm text-slate-500">No categorized items found.</p>
          )}
        </div>
      )}

      {items.length > 0 ? (
        <DataTable minWidth={900}>
          <thead>
            <tr>
              <SortableTh active={itemsSortKey === 'category'} direction={itemsSortDir} onSort={() => handleItemsSort('category')}>Category</SortableTh>
              <SortableTh active={itemsSortKey === 'action'} direction={itemsSortDir} onSort={() => handleItemsSort('action')}>Action</SortableTh>
              <SortableTh active={itemsSortKey === 'brokerage'} direction={itemsSortDir} onSort={() => handleItemsSort('brokerage')}>Brokerage</SortableTh>
              <SortableTh active={itemsSortKey === 'target'} direction={itemsSortDir} onSort={() => handleItemsSort('target')}>Target</SortableTh>
              <SortableTh active={itemsSortKey === 'title'} direction={itemsSortDir} onSort={() => handleItemsSort('title')}>Title</SortableTh>
              <SortableTh active={itemsSortKey === 'published'} direction={itemsSortDir} onSort={() => handleItemsSort('published')}>Published</SortableTh>
            </tr>
          </thead>
          <tbody>
            {sortedItems.map((it, i) => (
              <tr key={i}>
                <Td>{String(it.category_label ?? it.call_type ?? '—')}</Td>
                <Td className={verdictClass(String(it.action ?? ''))}>{String(it.action ?? '—')}</Td>
                <Td>{String(it.brokerage ?? '—')}</Td>
                <Td>{String(it.price_target ?? '—')}</Td>
                <Td className="max-w-xs truncate">
                  {it.link != null ? (
                    <a href={String(it.link)} target="_blank" rel="noreferrer" className="text-blue-400 hover:underline">
                      {String(it.title ?? '—')}
                    </a>
                  ) : String(it.title ?? '—')}
                </Td>
                <Td>{String(it.published ?? '—')}</Td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      ) : (
        <p className="text-sm text-slate-500">No upgrade/downgrade items found for this ticker.</p>
      )}
    </div>
  )
}

function heatmapTileStyle(pct: number | null | undefined, maxAbs: number): { bg: string; fg: string } {
  if (pct == null) return { bg: 'rgba(148,163,184,0.18)', fg: '#94a3b8' }
  const magnitude = Math.min(Math.abs(pct), maxAbs) / maxAbs
  const alpha = 0.18 + magnitude * 0.72
  if (pct > 0) return { bg: `rgba(22,163,74,${alpha.toFixed(2)})`, fg: alpha > 0.45 ? '#ffffff' : '#166534' }
  if (pct < 0) return { bg: `rgba(220,38,38,${alpha.toFixed(2)})`, fg: alpha > 0.45 ? '#ffffff' : '#991b1b' }
  return { bg: 'rgba(148,163,184,0.18)', fg: '#94a3b8' }
}

function AdvanceDecline({ rows, pctKey }: { rows: Row[]; pctKey: string }) {
  if (!rows.length) return null
  const advances = rows.filter((r) => Number(r[pctKey] ?? 0) > 0).length
  const declines = rows.filter((r) => Number(r[pctKey] ?? 0) < 0).length
  const unchanged = rows.length - advances - declines
  const total = rows.length || 1
  const adRatio = declines ? (advances / declines).toFixed(2) : advances ? '∞' : '—'
  const advPct = (advances / total) * 100
  const decPct = (declines / total) * 100
  return (
    <div className="mb-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        <StatCard label="Total" value={rows.length} />
        <StatCard label="🟢 Advances" value={advances} />
        <StatCard label="🔴 Declines" value={declines} />
        <StatCard label="⚪ Unchanged" value={unchanged} />
        <StatCard label="A/D Ratio" value={adRatio} />
      </div>
      <div className="mt-3 flex h-2.5 w-full overflow-hidden rounded-md">
        <div style={{ width: `${advPct}%`, background: '#16a34a' }} />
        <div style={{ width: `${decPct}%`, background: '#dc2626' }} />
        <div style={{ width: `${100 - advPct - decPct}%`, background: '#94a3b8' }} />
      </div>
    </div>
  )
}

function fmtVol(v: unknown): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  for (const [suffix, threshold] of [['B', 1e9], ['M', 1e6], ['K', 1e3]] as const) {
    if (Math.abs(n) >= threshold) return `${(n / threshold).toFixed(2)}${suffix}`
  }
  return n.toFixed(0)
}

function QuickAnalyzerMiniResult({ result }: { result: Row }) {
  if (result.error) return <p className="text-xs text-slate-500">⚠️ {String(result.error)}</p>
  const setup = (result.setup as Row) ?? {}
  const direction = String(setup.direction ?? '—')
  const cls = direction === 'LONG' ? 'text-emerald-400' : direction === 'SHORT' ? 'text-rose-400' : 'text-amber-400'
  return (
    <div className="text-xs">
      <p className={cls}>
        {_SETUP_BADGE[direction] ?? direction} · {fmtNum(setup.confidence_pct, 0)}% conf
        {setup.sl_pct != null ? ` · SL ${fmtNum(setup.sl_pct, 2)}% / TP ${fmtNum(setup.tp_pct, 2)}%` : ''}
      </p>
      {((setup.reasons as string[]) ?? []).slice(0, 2).map((r, i) => <p key={i} className="text-slate-500">· {r}</p>)}
    </div>
  )
}

const RSI_BUCKET_TEXT: Record<string, string> = {
  'Extended Overbought': 'text-rose-400',
  Overbought: 'text-rose-300',
  Neutral: 'text-slate-400',
  Oversold: 'text-emerald-300',
  'Extended Oversold': 'text-emerald-400',
}

function TradeSetupMiniResult({ result }: { result: Row }) {
  if (result.error) return <p className="text-xs text-slate-500">⚠️ {String(result.error)}</p>
  const entries = Object.values((result.per_tf as Record<string, Row>) ?? {})
  if (!entries.length) return null
  return (
    <div className="space-y-0.5">
      {entries.map((e, i) => (
        <p key={i} className={`text-xs ${RSI_BUCKET_TEXT[String(e.bucket ?? '')] ?? 'text-slate-400'}`}>
          {String(e.timeframe)} · RSI {fmtNum(e.rsi, 1)} · {String(e.bucket ?? '—')}
        </p>
      ))}
    </div>
  )
}

function CoinDcxTile({ row }: { row: Row }) {
  const apiSymbol = String(row.pair ?? row.ticker ?? '')
  const { bg, fg } = heatmapTileStyle(row.percent_change as number | null, 15)
  const pct = row.percent_change as number | null
  const [timeframes, setTimeframes] = useState<string[]>(['1d'])

  const wsMut = useMutation({ mutationFn: () => runWeakStrong({ tickers: [apiSymbol], asset_class: 'crypto', timeframes }) })
  const qaMut = useMutation({ mutationFn: () => runQuickAnalyzer({ tickers: [apiSymbol], timeframes, asset_class: 'crypto' }) })
  const tsMut = useMutation({ mutationFn: () => runTradeSetup({ tickers: [apiSymbol], asset_class: 'crypto', timeframes }) })

  const wsResult = wsMut.data as Row | undefined
  const strong = (wsResult?.strong as Row[]) ?? []
  const weak = (wsResult?.weak as Row[]) ?? []
  const neutral = (wsResult?.neutral as Row[]) ?? []
  const wsErrors = (wsResult?.errors as Row[]) ?? []
  const qaResult = ((qaMut.data as Row | undefined)?.results as Row[] | undefined)?.[0]
  const tsResult = ((tsMut.data as Row | undefined)?.results as Row[] | undefined)?.[0]

  const toggleTf = (tf: string) => {
    setTimeframes((prev) => (prev.includes(tf) ? prev.filter((t) => t !== tf) : [...prev, tf]))
  }

  return (
    <div className="flex flex-col overflow-hidden rounded-lg border border-slate-800/60 bg-slate-900/40 shadow-sm">
      <div className="flex min-h-[128px] flex-col justify-between p-2.5" style={{ background: bg, color: fg }}>
        <div>
          <div className="text-base font-bold">{pct != null ? `${pct > 0 ? '+' : ''}${pct.toFixed(2)}%` : '—'}</div>
          {row.volatility_pct != null && (
            <div className="text-[10px] opacity-85">{(row.volatility_pct as number).toFixed(2)}% 24h range</div>
          )}
        </div>
        <div>
          <div className="text-[10px] opacity-85">Ticker name</div>
          <div className="flex items-center gap-1.5">
            <div className="text-sm font-bold leading-tight">{String(row.ticker ?? '—')}</div>
            <AddToWatchlistButton
              ticker={apiSymbol}
              displayName={String(row.ticker ?? apiSymbol)}
              marketType="crypto"
              compact
              className="!border-white/30 !bg-black/20 !text-inherit hover:!bg-black/35"
            />
          </div>
          <div className="text-sm font-semibold">LTP {fmtNum(row.price, 4)}</div>
        </div>
        <div className="text-[10px] leading-relaxed">
          High {fmtNum(row.high, 4)}<br />Low {fmtNum(row.low, 4)}<br />Vol {fmtVol(row.vol)}
        </div>
      </div>
      <div className="space-y-1.5 p-2">
        <DayBiasNote bias={row.day_bias as Row | undefined} />
        <DayBiasRecalculator ticker={apiSymbol} assetClass="crypto" defaultTimeframe="1h" />
        <div className="flex flex-wrap gap-1">
          {HEATMAP_TIMEFRAME_OPTIONS.map((tf) => (
            <Chip key={tf} selected={timeframes.includes(tf)} onClick={() => toggleTf(tf)}>{tf}</Chip>
          ))}
        </div>
        <div className="flex flex-col gap-1">
          <Button size="sm" variant="secondary" disabled={!apiSymbol || !timeframes.length || wsMut.isPending} onClick={() => wsMut.mutate()}>
            {wsMut.isPending ? '…' : '↔️ Weak/Strong'}
          </Button>
          <Button size="sm" variant="secondary" disabled={!apiSymbol || !timeframes.length || qaMut.isPending} onClick={() => qaMut.mutate()}>
            {qaMut.isPending ? '…' : '⚡ Quick Analyzer'}
          </Button>
          <Button size="sm" variant="secondary" disabled={!apiSymbol || !timeframes.length || tsMut.isPending} onClick={() => tsMut.mutate()}>
            {tsMut.isPending ? '…' : '📊 Overbought/Oversold'}
          </Button>
        </div>
        {wsMut.isError ? <p className="text-xs text-rose-400">{apiErrorMessage(wsMut.error)}</p> : null}
        {wsResult ? (
          <div className="space-y-1">
            {strong.map((r, i) => <WeakStrongResultRow key={`s${i}`} res={r} compact />)}
            {weak.map((r, i) => <WeakStrongResultRow key={`w${i}`} res={r} compact />)}
            {neutral.map((r, i) => <WeakStrongResultRow key={`n${i}`} res={r} compact />)}
            {wsErrors.map((e, i) => <p key={`e${i}`} className="text-xs text-slate-500">⚠️ {String(e.timeframe)}: {String(e.error)}</p>)}
          </div>
        ) : null}
        {qaMut.isError ? <p className="text-xs text-rose-400">{apiErrorMessage(qaMut.error)}</p> : null}
        {qaResult ? <QuickAnalyzerMiniResult result={qaResult} /> : null}
        {tsMut.isError ? <p className="text-xs text-rose-400">{apiErrorMessage(tsMut.error)}</p> : null}
        {tsResult ? <TradeSetupMiniResult result={tsResult} /> : null}
      </div>
    </div>
  )
}

function CoinDcx24hVolatilityPanel({ data }: { data: Row }) {
  const rows = (data.rows as Row[]) ?? []
  const [direction, setDirection] = useState<'gainers' | 'losers' | 'volatile'>('gainers')
  const [topN, setTopN] = useState<number | 'all'>(50)

  if (!rows.length) return <p className="text-sm text-slate-500">No data returned right now.</p>

  // "Most volatile" ranks by real 24h high-low range %, not signed % change —
  // a pair can close flat with a huge intraday swing; gainers/losers alone
  // would never surface that, despite this tab being named for volatility.
  const byVolatility = [...rows].sort((a, b) => {
    const av = a.volatility_pct as number | null
    const bv = b.volatility_pct as number | null
    return (bv ?? -1) - (av ?? -1)
  })

  const shown = direction === 'losers'
    ? [...rows].reverse().slice(0, topN === 'all' ? undefined : topN)
    : direction === 'volatile'
      ? byVolatility.slice(0, topN === 'all' ? undefined : topN)
      : rows.slice(0, topN === 'all' ? undefined : topN)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex gap-1.5">
          <Chip selected={direction === 'gainers'} onClick={() => setDirection('gainers')}>Top gainers</Chip>
          <Chip selected={direction === 'losers'} onClick={() => setDirection('losers')}>Top losers</Chip>
          <Chip selected={direction === 'volatile'} onClick={() => setDirection('volatile')}>Most volatile (range %)</Chip>
        </div>
        <div className="flex gap-1.5">
          {[25, 50, 100, 200].map((n) => (
            <Chip key={n} selected={topN === n} onClick={() => setTopN(n)}>{n}</Chip>
          ))}
          <Chip selected={topN === 'all'} onClick={() => setTopN('all')}>All</Chip>
        </div>
      </div>
      <p className="text-sm text-slate-400">{shown.length} of {rows.length} pairs shown ({direction})</p>
      <AdvanceDecline rows={rows} pctKey="percent_change" />
      <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(170px, 1fr))' }}>
        {shown.map((r, i) => <CoinDcxTile key={i} row={r} />)}
      </div>
    </div>
  )
}

const HEATMAP_TIMEFRAME_OPTIONS = ['5m', '15m', '1h', '4h', '1d', '1w']

const HEATMAP_CURRENCY_PREFIX: Record<string, string> = { india: '₹ ', us: '$ ', crypto: '' }

function IndiaMarketHeatmapTile({ row, exchange, assetClass }: { row: Row; exchange: string; assetClass: 'india' | 'us' | 'crypto' }) {
  const ticker = String(row.ticker ?? '—')
  const { bg, fg } = heatmapTileStyle(row.change_pct as number | null, 6)
  const pct = row.change_pct as number | null
  const price = row.price as number | null
  const dayHigh = row.day_high as number | null
  const dayLow = row.day_low as number | null
  const [timeframes, setTimeframes] = useState<string[]>(['1d'])
  const mut = useMutation({
    mutationFn: () => runWeakStrong({ tickers: [ticker], asset_class: assetClass, timeframes, exchange }),
  })
  const tsMut = useMutation({
    mutationFn: () => runTradeSetup({ tickers: [ticker], asset_class: assetClass, timeframes, exchange }),
  })
  const qaMut = useMutation({
    mutationFn: () => runQuickAnalyzer({ tickers: [ticker], timeframes, asset_class: assetClass }),
  })
  const result = mut.data as Row | undefined
  const strong = (result?.strong as Row[]) ?? []
  const weak = (result?.weak as Row[]) ?? []
  const neutral = (result?.neutral as Row[]) ?? []
  const errors = (result?.errors as Row[]) ?? []
  const tsResult = ((tsMut.data as Row | undefined)?.results as Row[] | undefined)?.[0]
  const qaResult = ((qaMut.data as Row | undefined)?.results as Row[] | undefined)?.[0]

  const toggleTf = (tf: string) => {
    setTimeframes((prev) => (prev.includes(tf) ? prev.filter((t) => t !== tf) : [...prev, tf]))
  }

  return (
    <div className="flex flex-col overflow-hidden rounded-lg border border-slate-800/60 bg-slate-900/40 shadow-sm">
      <div className="flex min-h-[96px] flex-col justify-between p-2.5" style={{ background: bg, color: fg }}>
        <div className="text-base font-bold">{pct != null ? `${pct > 0 ? '+' : ''}${pct.toFixed(2)}%` : '—'}</div>
        <div>
          <div className="text-[10px] opacity-85">Ticker name</div>
          <div className="flex items-center gap-1.5">
            <div className="text-sm font-bold leading-tight">{ticker}</div>
            <AddToWatchlistButton ticker={ticker} compact className="!border-white/30 !bg-black/20 !text-inherit hover:!bg-black/35" />
          </div>
          <div className="truncate text-[10px] opacity-85" title={String(row.company ?? '')}>{String(row.company ?? '')}</div>
        </div>
        <div className="text-sm font-semibold">{price != null ? `${HEATMAP_CURRENCY_PREFIX[assetClass] ?? ''}${Number(price).toLocaleString(undefined, { maximumFractionDigits: 4 })}` : '—'}</div>
        {(dayHigh != null || dayLow != null) && (
          <div className="text-[10px] opacity-85">
            H {dayHigh != null ? Number(dayHigh).toLocaleString(undefined, { maximumFractionDigits: 4 }) : '—'}
            {' · '}L {dayLow != null ? Number(dayLow).toLocaleString(undefined, { maximumFractionDigits: 4 }) : '—'}
          </div>
        )}
      </div>
      <div className="space-y-1.5 p-2">
        <DayBiasNote bias={row.day_bias as Row | undefined} />
        <DayBiasRecalculator ticker={ticker} assetClass={assetClass} exchange={exchange} defaultTimeframe="1d" />
        <div className="flex flex-wrap gap-1">
          {HEATMAP_TIMEFRAME_OPTIONS.map((tf) => (
            <Chip key={tf} selected={timeframes.includes(tf)} onClick={() => toggleTf(tf)}>{tf}</Chip>
          ))}
        </div>
        <div className="flex flex-col gap-1">
          <Button
            size="sm"
            variant="secondary"
            disabled={ticker === '—' || !timeframes.length || mut.isPending}
            onClick={() => mut.mutate()}
          >
            {mut.isPending ? 'Scanning…' : '↔️ Check Weak / Strong'}
          </Button>
          <Button
            size="sm"
            variant="secondary"
            disabled={ticker === '—' || !timeframes.length || tsMut.isPending}
            onClick={() => tsMut.mutate()}
          >
            {tsMut.isPending ? 'Scanning…' : '📊 Overbought/Oversold'}
          </Button>
          <Button
            size="sm"
            variant="secondary"
            disabled={ticker === '—' || !timeframes.length || qaMut.isPending}
            onClick={() => qaMut.mutate()}
          >
            {qaMut.isPending ? 'Scanning…' : '⚡ Quick Analyzer'}
          </Button>
        </div>
        {mut.isError ? <p className="text-xs text-rose-400">{apiErrorMessage(mut.error)}</p> : null}
        {result ? (
          <div className="space-y-1">
            {strong.map((r, i) => <WeakStrongResultRow key={`s${i}`} res={r} compact />)}
            {weak.map((r, i) => <WeakStrongResultRow key={`w${i}`} res={r} compact />)}
            {neutral.map((r, i) => <WeakStrongResultRow key={`n${i}`} res={r} compact />)}
            {errors.map((e, i) => <p key={`e${i}`} className="text-xs text-slate-500">⚠️ {String(e.timeframe)}: {String(e.error)}</p>)}
          </div>
        ) : null}
        {tsMut.isError ? <p className="text-xs text-rose-400">{apiErrorMessage(tsMut.error)}</p> : null}
        {tsResult ? <TradeSetupMiniResult result={tsResult} /> : null}
        {qaMut.isError ? <p className="text-xs text-rose-400">{apiErrorMessage(qaMut.error)}</p> : null}
        {qaResult ? <QuickAnalyzerMiniResult result={qaResult} /> : null}
      </div>
    </div>
  )
}

function IndiaMarketHeatmapPanel({ data, assetClass }: { data: Row; assetClass: 'india' | 'us' | 'crypto' }) {
  const rows = (data.rows as Row[]) ?? []
  const exchange = String(data.exchange ?? 'NSE')
  if (!rows.length) return <p className="text-sm text-slate-500">No data returned for this index right now.</p>

  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-400">{String(data.index_name ?? '—')} — {rows.length} stocks</p>
      <AdvanceDecline rows={rows} pctKey="change_pct" />
      <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(170px, 1fr))' }}>
        {rows.map((r, i) => <IndiaMarketHeatmapTile key={i} row={r} exchange={exchange} assetClass={assetClass} />)}
      </div>
    </div>
  )
}

const FUTURES_REGION_EMOJI: Record<string, string> = {
  US: '🇺🇸', Europe: '🇪🇺', Asia: '🌏', Commodities: '🛢️', Crypto: '₿', Currency: '💵',
}
const FUTURES_REGION_KIND: Record<string, string> = {
  US: 'Futures', Europe: 'Indices', Asia: 'Futures & Indices',
  Commodities: 'Futures', Crypto: 'Futures', Currency: 'Index',
}

function FuturesTable({ rows, region }: { rows: Row[]; region: string }) {
  const filtered = rows.filter((r) => r.region === region)
  const { sorted, sortKey, sortDir, handleSort } = useSort(filtered, {
    name: (r) => String(r.name ?? ''),
    change_pct: (r) => (r.change_pct != null ? Number(r.change_pct) : null),
    last: (r) => (r.last != null ? Number(r.last) : null),
    high: (r) => (r.high != null ? Number(r.high) : null),
    low: (r) => (r.low != null ? Number(r.low) : null),
  })
  const kind = FUTURES_REGION_KIND[region] ?? 'Data'
  const allFutures = filtered.length > 0 && filtered.every((r) => Boolean(r.is_future))
  return (
    <div>
      <h4 className="mb-2 text-sm font-semibold text-white">{FUTURES_REGION_EMOJI[region] ?? '🌐'} {region} {kind} — {filtered.length}</h4>
      {filtered.length > 0 && !allFutures && (
        <p className="mb-2 text-xs text-slate-500">
          Yahoo Finance has no free continuous futures contract for one or more of these — shown as the underlying cash index instead, still a genuine overnight pre-market read.
        </p>
      )}
      {!filtered.length ? (
        <p className="text-xs text-slate-500">No {region} data returned right now.</p>
      ) : (
        <DataTable minWidth={720}>
          <thead>
            <tr>
              <SortableTh active={sortKey === 'name'} direction={sortDir} onSort={() => handleSort('name')}>Name</SortableTh>
              <SortableTh active={sortKey === 'change_pct'} direction={sortDir} onSort={() => handleSort('change_pct')}>Change %</SortableTh>
              <SortableTh active={sortKey === 'last'} direction={sortDir} onSort={() => handleSort('last')}>LTP</SortableTh>
              <SortableTh active={sortKey === 'high'} direction={sortDir} onSort={() => handleSort('high')}>Day High</SortableTh>
              <SortableTh active={sortKey === 'low'} direction={sortDir} onSort={() => handleSort('low')}>Day Low</SortableTh>
            </tr>
          </thead>
          <tbody>
            {sorted.map((r, i) => (
              <tr key={i}>
                <Td className="font-medium">{String(r.name ?? '—')}{r.country ? <span className="ml-1 text-xs text-slate-500">({String(r.country)})</span> : null}</Td>
                <Td className={Number(r.change_pct ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}>{fmtNum(r.change_pct)}</Td>
                <Td>{fmtNum(r.last)}</Td>
                <Td>{fmtNum(r.high)}</Td>
                <Td>{fmtNum(r.low)}</Td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      )}
    </div>
  )
}

function GiftNiftyCard({ gn }: { gn: Row | undefined | null }) {
  if (!gn || gn.ltp == null) {
    return (
      <div>
        <h4 className="mb-2 text-sm font-semibold text-white">🇮🇳 GIFT Nifty (formerly SGX Nifty)</h4>
        <p className="text-xs text-slate-500">GIFT Nifty data unavailable right now.</p>
      </div>
    )
  }
  const r1w = (gn.return_1w as Row) ?? {}
  const r1m = (gn.return_1m as Row) ?? {}
  const r1y = (gn.return_1y as Row) ?? {}
  return (
    <div>
      <h4 className="mb-2 text-sm font-semibold text-white">🇮🇳 GIFT Nifty (formerly SGX Nifty)</h4>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="LTP" value={fmtNum(gn.ltp, 2)} trend={Number(gn.change ?? 0) >= 0 ? 'up' : 'down'} />
        <StatCard label="Open" value={gn.open != null ? fmtNum(gn.open, 2) : '—'} />
        <StatCard label="Prev. Close" value={gn.prev_close != null ? fmtNum(gn.prev_close, 2) : '—'} />
        <StatCard label="Day Range" value={gn.day_low != null ? `${fmtNum(gn.day_low, 0)} – ${fmtNum(gn.day_high, 0)}` : '—'} />
        <StatCard label="52W Range" value={gn.week52_low != null ? `${fmtNum(gn.week52_low, 0)} – ${fmtNum(gn.week52_high, 0)}` : '—'} />
        <StatCard label="1W Return" value={r1w.pct != null ? `${fmtNum(r1w.pct, 2)}%` : '—'} trend={Number(r1w.pct ?? 0) >= 0 ? 'up' : 'down'} />
        <StatCard label="1M Return" value={r1m.pct != null ? `${fmtNum(r1m.pct, 2)}%` : '—'} trend={Number(r1m.pct ?? 0) >= 0 ? 'up' : 'down'} />
        <StatCard label="1Y Return" value={r1y.pct != null ? `${fmtNum(r1y.pct, 2)}%` : '—'} trend={Number(r1y.pct ?? 0) >= 0 ? 'up' : 'down'} />
      </div>
      {gn.as_of != null && <p className="mt-1 text-xs text-slate-500">As on {String(gn.as_of)}</p>}
    </div>
  )
}

function NseWorldIndicesPanel({ data }: { data: Row }) {
  const nseRows = (data.nse_rows as Row[] | undefined) ?? []
  const globalRows = (data.global_rows as Row[] | undefined) ?? []
  const futuresRows = (data.futures_rows as Row[] | undefined) ?? []
  const giftNifty = data.gift_nifty as Row | undefined | null
  const { sorted: sortedNseRows, sortKey: nseSortKey, sortDir: nseSortDir, handleSort: handleNseSort } = useSort(nseRows, {
    name: (r) => String(r.name ?? ''),
    ltp: (r) => (r.ltp != null ? Number(r.ltp) : null),
    trend: (r) => (r.change_pct != null ? Number(r.change_pct) : null),
    change_pct: (r) => (r.change_pct != null ? Number(r.change_pct) : null),
    open: (r) => (r.open != null ? Number(r.open) : null),
    prev_close: (r) => (r.prev_close != null ? Number(r.prev_close) : null),
    high_52w: (r) => (r.high_52w != null ? Number(r.high_52w) : null),
    low_52w: (r) => (r.low_52w != null ? Number(r.low_52w) : null),
    return_1y: (r) => (r.return_1y_pct != null ? Number(r.return_1y_pct) : null),
    return_3y: (r) => (r.return_3y_pct != null ? Number(r.return_3y_pct) : null),
    return_5y: (r) => (r.return_5y_pct != null ? Number(r.return_5y_pct) : null),
  })
  const { sorted: sortedGlobalRows, sortKey: globalSortKey, sortDir: globalSortDir, handleSort: handleGlobalSort } = useSort(globalRows, {
    name: (r) => String(r.name ?? ''),
    ltp: (r) => (r.ltp != null ? Number(r.ltp) : null),
    change: (r) => (r.change != null ? Number(r.change) : null),
    change_pct: (r) => (r.change_pct != null ? Number(r.change_pct) : null),
    trend: (r) => (r.change_pct != null ? Number(r.change_pct) : null),
    open: (r) => (r.open != null ? Number(r.open) : null),
    prev_close: (r) => (r.prev_close != null ? Number(r.prev_close) : null),
    day_high: (r) => (r.day_high != null ? Number(r.day_high) : null),
    day_low: (r) => (r.day_low != null ? Number(r.day_low) : null),
  })
  const arrow = (pct: unknown) => {
    const n = Number(pct)
    if (!Number.isFinite(n) || n === 0) return <span className="text-slate-500">—</span>
    return n > 0 ? (
      <TrendingUp size={14} className="inline text-emerald-400" />
    ) : (
      <TrendingDown size={14} className="inline text-rose-400" />
    )
  }

  if (!nseRows.length && !globalRows.length && !futuresRows.length && !giftNifty) {
    return <p className="text-sm text-slate-500">Click a button above to load live index data.</p>
  }

  return (
    <div className="space-y-6">
      {nseRows.length > 0 && (
        <div>
          <h4 className="mb-2 text-sm font-semibold text-white">🇮🇳 NSE Indices — {nseRows.length}</h4>
          <DataTable minWidth={960}>
            <thead>
              <tr>
                <SortableTh active={nseSortKey === 'name'} direction={nseSortDir} onSort={() => handleNseSort('name')}>Index Name</SortableTh>
                <SortableTh active={nseSortKey === 'change_pct'} direction={nseSortDir} onSort={() => handleNseSort('change_pct')}>Change %</SortableTh>
                <SortableTh active={nseSortKey === 'trend'} direction={nseSortDir} onSort={() => handleNseSort('trend')}>Trend</SortableTh>
                <SortableTh active={nseSortKey === 'ltp'} direction={nseSortDir} onSort={() => handleNseSort('ltp')}>LTP</SortableTh>
                <SortableTh active={nseSortKey === 'open'} direction={nseSortDir} onSort={() => handleNseSort('open')}>Open</SortableTh>
                <SortableTh active={nseSortKey === 'prev_close'} direction={nseSortDir} onSort={() => handleNseSort('prev_close')}>Prev. Close</SortableTh>
                <SortableTh active={nseSortKey === 'high_52w'} direction={nseSortDir} onSort={() => handleNseSort('high_52w')}>52W High</SortableTh>
                <SortableTh active={nseSortKey === 'low_52w'} direction={nseSortDir} onSort={() => handleNseSort('low_52w')}>52W Low</SortableTh>
                <SortableTh active={nseSortKey === 'return_1y'} direction={nseSortDir} onSort={() => handleNseSort('return_1y')}>1Yr Return %</SortableTh>
                <SortableTh active={nseSortKey === 'return_3y'} direction={nseSortDir} onSort={() => handleNseSort('return_3y')}>3Yr Returns %</SortableTh>
                <SortableTh active={nseSortKey === 'return_5y'} direction={nseSortDir} onSort={() => handleNseSort('return_5y')}>5Yr Returns %</SortableTh>
              </tr>
            </thead>
            <tbody>
              {sortedNseRows.map((r, i) => (
                <tr key={i}>
                  <Td className="font-medium">{String(r.name ?? '—')}</Td>
                  <Td className={Number(r.change_pct ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}>{fmtNum(r.change_pct)}</Td>
                  <Td className={Number(r.change_pct ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}>{arrow(r.change_pct)}</Td>
                  <Td>{fmtNum(r.ltp)}</Td>
                  <Td>{fmtNum(r.open)}</Td>
                  <Td>{fmtNum(r.prev_close)}</Td>
                  <Td>{fmtNum(r.high_52w)}</Td>
                  <Td>{fmtNum(r.low_52w)}</Td>
                  <Td>{fmtNum(r.return_1y_pct)}</Td>
                  <Td>{fmtNum(r.return_3y_pct)}</Td>
                  <Td>{fmtNum(r.return_5y_pct)}</Td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        </div>
      )}
      {globalRows.length > 0 && (
        <div>
          <h4 className="mb-2 text-sm font-semibold text-white">🌍 Global Indices — {globalRows.length}</h4>
          <DataTable minWidth={800}>
            <thead>
              <tr>
                <SortableTh active={globalSortKey === 'name'} direction={globalSortDir} onSort={() => handleGlobalSort('name')}>Index Name</SortableTh>
                <SortableTh active={globalSortKey === 'change_pct'} direction={globalSortDir} onSort={() => handleGlobalSort('change_pct')}>Change %</SortableTh>
                <SortableTh active={globalSortKey === 'trend'} direction={globalSortDir} onSort={() => handleGlobalSort('trend')}>Trend</SortableTh>
                <SortableTh active={globalSortKey === 'change'} direction={globalSortDir} onSort={() => handleGlobalSort('change')}>Change</SortableTh>
                <SortableTh active={globalSortKey === 'ltp'} direction={globalSortDir} onSort={() => handleGlobalSort('ltp')}>LTP</SortableTh>
                <SortableTh active={globalSortKey === 'open'} direction={globalSortDir} onSort={() => handleGlobalSort('open')}>Open</SortableTh>
                <SortableTh active={globalSortKey === 'prev_close'} direction={globalSortDir} onSort={() => handleGlobalSort('prev_close')}>Prev. Close</SortableTh>
                <SortableTh active={globalSortKey === 'day_high'} direction={globalSortDir} onSort={() => handleGlobalSort('day_high')}>Day High</SortableTh>
                <SortableTh active={globalSortKey === 'day_low'} direction={globalSortDir} onSort={() => handleGlobalSort('day_low')}>Day Low</SortableTh>
              </tr>
            </thead>
            <tbody>
              {sortedGlobalRows.map((r, i) => (
                <tr key={i}>
                  <Td className="font-medium">{String(r.name ?? '—')}{r.country ? <span className="ml-1 text-xs text-slate-500">({String(r.country)})</span> : null}</Td>
                  <Td className={Number(r.change_pct ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}>{fmtNum(r.change_pct)}</Td>
                  <Td className={Number(r.change_pct ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}>{arrow(r.change_pct)}</Td>
                  <Td className={Number(r.change_pct ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}>{fmtNum(r.change)}</Td>
                  <Td>{fmtNum(r.ltp)}</Td>
                  <Td>{fmtNum(r.open)}</Td>
                  <Td>{fmtNum(r.prev_close)}</Td>
                  <Td>{fmtNum(r.day_high)}</Td>
                  <Td>{fmtNum(r.day_low)}</Td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        </div>
      )}
      {(giftNifty || futuresRows.length > 0) && (
        <div className="space-y-6">
          <GiftNiftyCard gn={giftNifty} />
          <FuturesTable rows={futuresRows} region="US" />
          <FuturesTable rows={futuresRows} region="Europe" />
          <FuturesTable rows={futuresRows} region="Asia" />
          <FuturesTable rows={futuresRows} region="Commodities" />
          <FuturesTable rows={futuresRows} region="Crypto" />
          <FuturesTable rows={futuresRows} region="Currency" />
        </div>
      )}
    </div>
  )
}

function OptionChainPanel({ data }: { data: Row }) {
  const chain = (data.chain as Row) ?? {}
  const signal = (data.signal as Row) ?? {}
  const strikes = (chain.strikes as Row[]) ?? []
  const topCallOi = (chain.top_call_oi as Row[]) ?? []
  const topPutOi = (chain.top_put_oi as Row[]) ?? []
  const [showFullChain, setShowFullChain] = useState(false)
  const { sorted: sortedTopCallOi, sortKey: topCallSortKey, sortDir: topCallSortDir, handleSort: handleTopCallSort } = useSort(topCallOi, {
    strike: (r) => (r.strike != null ? Number(r.strike) : String(r.strike ?? '')),
    ce_oi: (r) => (r.ce_oi != null ? Number(r.ce_oi) : null),
    ce_chg_oi: (r) => (r.ce_chg_oi != null ? Number(r.ce_chg_oi) : null),
  })
  const { sorted: sortedTopPutOi, sortKey: topPutSortKey, sortDir: topPutSortDir, handleSort: handleTopPutSort } = useSort(topPutOi, {
    strike: (r) => (r.strike != null ? Number(r.strike) : String(r.strike ?? '')),
    pe_oi: (r) => (r.pe_oi != null ? Number(r.pe_oi) : null),
    pe_chg_oi: (r) => (r.pe_chg_oi != null ? Number(r.pe_chg_oi) : null),
  })
  const { sorted: sortedStrikes, sortKey: strikesSortKey, sortDir: strikesSortDir, handleSort: handleStrikesSort } = useSort(strikes, {
    ce_oi: (s) => (s.ce_oi != null ? Number(s.ce_oi) : null),
    ce_chg_oi: (s) => (s.ce_chg_oi != null ? Number(s.ce_chg_oi) : null),
    ce_vol: (s) => (s.ce_vol != null ? Number(s.ce_vol) : null),
    ce_iv: (s) => (s.ce_iv != null ? Number(s.ce_iv) : null),
    ce_ltp: (s) => (s.ce_ltp != null ? Number(s.ce_ltp) : null),
    strike: (s) => (s.strike != null ? Number(s.strike) : null),
    pe_ltp: (s) => (s.pe_ltp != null ? Number(s.pe_ltp) : null),
    pe_iv: (s) => (s.pe_iv != null ? Number(s.pe_iv) : null),
    pe_vol: (s) => (s.pe_vol != null ? Number(s.pe_vol) : null),
    pe_chg_oi: (s) => (s.pe_chg_oi != null ? Number(s.pe_chg_oi) : null),
    pe_oi: (s) => (s.pe_oi != null ? Number(s.pe_oi) : null),
  })

  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-slate-800/80 bg-slate-900/40 px-4 py-5 sm:px-6">
        <p className="text-xs font-medium uppercase tracking-wider text-slate-500">Option Chain · {String(data.symbol ?? '—')}</p>
        <p className={`mt-1 text-xl font-bold sm:text-2xl ${verdictClass(String(signal.bias ?? ''))}`}>
          {String(signal.bias ?? '—')} · {String(signal.trade_signal ?? '—')} · {fmtNum(signal.confidence_pct, 0)}% confidence
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-4">
        <StatCard label="Underlying LTP" value={fmtNum(chain.underlying, 2)} />
        <StatCard label="PCR (OI)" value={fmtNum(chain.pcr_oi, 2)} />
        <StatCard label="PCR (Volume)" value={fmtNum(chain.pcr_vol, 2)} />
        <StatCard label="Max Pain" value={fmtNum(chain.max_pain, 0)} />
      </div>
      <div className="grid gap-3 sm:grid-cols-4">
        <StatCard label="Support (highest Put OI)" value={fmtNum(signal.support, 0)} />
        <StatCard label="Resistance (highest Call OI)" value={fmtNum(signal.resistance, 0)} />
        <StatCard label="Expiry" value={String(chain.current_expiry ?? '—')} />
        <StatCard label="Source" value={String(chain.source ?? '—')} />
      </div>

      {((signal.reasons as string[]) ?? []).length > 0 && (
        <div>
          <h4 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">Why this signal</h4>
          <ul className="space-y-1.5 text-sm text-slate-300">
            {(signal.reasons as string[]).map((r, i) => (
              <li key={i} className="flex gap-2"><span className="text-slate-500">•</span>{r}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="grid gap-4">
        <div className="min-w-0">
          <h4 className="mb-2 text-sm font-semibold text-white">Top 5 Call OI (resistance zones)</h4>
          <DataTable minWidth={320}>
            <thead>
              <tr>
                <SortableTh active={topCallSortKey === 'strike'} direction={topCallSortDir} onSort={() => handleTopCallSort('strike')}>Strike</SortableTh>
                <SortableTh active={topCallSortKey === 'ce_oi'} direction={topCallSortDir} onSort={() => handleTopCallSort('ce_oi')}>Call OI</SortableTh>
                <SortableTh active={topCallSortKey === 'ce_chg_oi'} direction={topCallSortDir} onSort={() => handleTopCallSort('ce_chg_oi')}>Chg OI</SortableTh>
              </tr>
            </thead>
            <tbody>
              {sortedTopCallOi.map((r, i) => (
                <tr key={i}><Td>{String(r.strike ?? '—')}</Td><Td>{fmtNum(r.ce_oi, 0)}</Td><Td>{fmtNum(r.ce_chg_oi, 0)}</Td></tr>
              ))}
            </tbody>
          </DataTable>
        </div>
        <div className="min-w-0">
          <h4 className="mb-2 text-sm font-semibold text-white">Top 5 Put OI (support zones)</h4>
          <DataTable minWidth={320}>
            <thead>
              <tr>
                <SortableTh active={topPutSortKey === 'strike'} direction={topPutSortDir} onSort={() => handleTopPutSort('strike')}>Strike</SortableTh>
                <SortableTh active={topPutSortKey === 'pe_oi'} direction={topPutSortDir} onSort={() => handleTopPutSort('pe_oi')}>Put OI</SortableTh>
                <SortableTh active={topPutSortKey === 'pe_chg_oi'} direction={topPutSortDir} onSort={() => handleTopPutSort('pe_chg_oi')}>Chg OI</SortableTh>
              </tr>
            </thead>
            <tbody>
              {sortedTopPutOi.map((r, i) => (
                <tr key={i}><Td>{String(r.strike ?? '—')}</Td><Td>{fmtNum(r.pe_oi, 0)}</Td><Td>{fmtNum(r.pe_chg_oi, 0)}</Td></tr>
              ))}
            </tbody>
          </DataTable>
        </div>
      </div>

      {strikes.length > 0 && (
        <div>
          <button
            className="mb-2 text-sm font-semibold text-white underline decoration-slate-600 hover:decoration-slate-400"
            onClick={() => setShowFullChain((v) => !v)}
          >
            {showFullChain ? 'Hide' : 'Show'} full option chain — {strikes.length} strikes
          </button>
          {showFullChain && (
            <DataTable minWidth={900}>
              <thead>
                <tr>
                  <SortableTh active={strikesSortKey === 'ce_oi'} direction={strikesSortDir} onSort={() => handleStrikesSort('ce_oi')}>Call OI</SortableTh>
                  <SortableTh active={strikesSortKey === 'ce_chg_oi'} direction={strikesSortDir} onSort={() => handleStrikesSort('ce_chg_oi')}>Call Chg OI</SortableTh>
                  <SortableTh active={strikesSortKey === 'ce_vol'} direction={strikesSortDir} onSort={() => handleStrikesSort('ce_vol')}>Call Vol</SortableTh>
                  <SortableTh active={strikesSortKey === 'ce_iv'} direction={strikesSortDir} onSort={() => handleStrikesSort('ce_iv')}>Call IV</SortableTh>
                  <SortableTh active={strikesSortKey === 'ce_ltp'} direction={strikesSortDir} onSort={() => handleStrikesSort('ce_ltp')}>Call LTP</SortableTh>
                  <SortableTh active={strikesSortKey === 'strike'} direction={strikesSortDir} onSort={() => handleStrikesSort('strike')}>Strike</SortableTh>
                  <SortableTh active={strikesSortKey === 'pe_ltp'} direction={strikesSortDir} onSort={() => handleStrikesSort('pe_ltp')}>Put LTP</SortableTh>
                  <SortableTh active={strikesSortKey === 'pe_iv'} direction={strikesSortDir} onSort={() => handleStrikesSort('pe_iv')}>Put IV</SortableTh>
                  <SortableTh active={strikesSortKey === 'pe_vol'} direction={strikesSortDir} onSort={() => handleStrikesSort('pe_vol')}>Put Vol</SortableTh>
                  <SortableTh active={strikesSortKey === 'pe_chg_oi'} direction={strikesSortDir} onSort={() => handleStrikesSort('pe_chg_oi')}>Put Chg OI</SortableTh>
                  <SortableTh active={strikesSortKey === 'pe_oi'} direction={strikesSortDir} onSort={() => handleStrikesSort('pe_oi')}>Put OI</SortableTh>
                </tr>
              </thead>
              <tbody>
                {sortedStrikes.map((s, i) => (
                  <tr key={i}>
                    <Td>{fmtNum(s.ce_oi, 0)}</Td><Td>{fmtNum(s.ce_chg_oi, 0)}</Td><Td>{fmtNum(s.ce_vol, 0)}</Td>
                    <Td>{fmtNum(s.ce_iv, 1)}</Td><Td>{fmtNum(s.ce_ltp, 2)}</Td>
                    <Td className="font-semibold">{String(s.strike ?? '—')}</Td>
                    <Td>{fmtNum(s.pe_ltp, 2)}</Td><Td>{fmtNum(s.pe_iv, 1)}</Td><Td>{fmtNum(s.pe_vol, 0)}</Td>
                    <Td>{fmtNum(s.pe_chg_oi, 0)}</Td><Td>{fmtNum(s.pe_oi, 0)}</Td>
                  </tr>
                ))}
              </tbody>
            </DataTable>
          )}
        </div>
      )}
    </div>
  )
}

const OSL_DIRECTION_BADGE: Record<string, string> = { UP: '🟢 UP', DOWN: '🔴 DOWN', NEUTRAL: '🟡 NEUTRAL' }
const OSL_ACTION_BADGE: Record<string, string> = {
  BUY_CALL: '🟢 BUY CALL', BUY_PUT: '🔴 BUY PUT', SELL_CALL: '🟠 SELL CALL', SELL_PUT: '🟠 SELL PUT',
}
const OSL_RISK_DISCLAIMER = (
  'This is a heuristic confluence read across options positioning and price action — it is NOT a statistical '
  + 'probability of profit and there is NO such thing as a zero-risk options trade. Buying a call/put has a '
  + 'defined max loss (the premium paid); selling a call/put carries open-ended risk beyond the stated stop '
  + 'unless you also buy a further OTM option to cap it (turning it into a credit spread). Always size positions '
  + 'so the stated stop-loss is a loss you can absorb. Research / education only — NOT FINANCIAL ADVICE.'
)

/** Payoff P&L chart with collision-avoiding marker labels: nearby Spot/Strike/
 * Stop/Target/Breakeven lines get stacked into different vertical lanes
 * instead of rendering their text at the same height (which is what made the
 * source Streamlit/Plotly version unreadable when levels sit close together). */
function PayoffChart({ payoff, plan, spot }: { payoff: Row; plan: Row; spot: number | null }) {
  const xs = (payoff.x as number[]) ?? []
  const expiryPnl = (payoff.expiry_pnl as number[]) ?? []
  const nowPnl = (payoff.now_pnl as number[]) ?? []
  const breakeven = payoff.breakeven as number | null
  if (!xs.length || xs.length !== expiryPnl.length) return null

  const width = 700
  const height = 360
  const padL = 52
  const padR = 16
  const padT = 94
  const padB = 28
  const chartW = width - padL - padR
  const chartH = height - padT - padB

  const xMin = xs[0]
  const xMax = xs[xs.length - 1]
  const allPnl = [...expiryPnl, ...nowPnl, 0]
  const yMinRaw = Math.min(...allPnl)
  const yMaxRaw = Math.max(...allPnl)
  const yPad = (yMaxRaw - yMinRaw) * 0.1 || 1
  const yLo = yMinRaw - yPad
  const yHi = yMaxRaw + yPad

  const xScale = (v: number) => padL + ((v - xMin) / (xMax - xMin || 1)) * chartW
  const yScale = (v: number) => padT + chartH - ((v - yLo) / (yHi - yLo || 1)) * chartH
  const pathFor = (values: number[]) => values.map((v, i) => `${i === 0 ? 'M' : 'L'} ${xScale(xs[i]).toFixed(1)} ${yScale(v).toFixed(1)}`).join(' ')
  const zeroY = yScale(0)

  const isBuy = Boolean(plan.is_buy)
  const lineColor = isBuy ? '#22c55e' : '#f97316'
  const fillColor = isBuy ? 'rgba(34,197,94,0.10)' : 'rgba(249,115,22,0.10)'
  const areaPath = `${pathFor(expiryPnl)} L ${xScale(xMax).toFixed(1)} ${zeroY.toFixed(1)} L ${xScale(xMin).toFixed(1)} ${zeroY.toFixed(1)} Z`

  type Marker = { key: string; label: string; price: number; color: string }
  const rawMarkers: Marker[] = []
  if (spot != null) rawMarkers.push({ key: 'spot', label: 'Spot', price: spot, color: '#e2e8f0' })
  if (plan.strike != null) rawMarkers.push({ key: 'strike', label: 'Strike', price: Number(plan.strike), color: '#a78bfa' })
  if (plan.stop_underlying != null) rawMarkers.push({ key: 'stop', label: 'Stop', price: Number(plan.stop_underlying), color: '#ef4444' })
  if (plan.target_underlying != null) rawMarkers.push({ key: 'target', label: 'Target', price: Number(plan.target_underlying), color: '#22c55e' })
  if (breakeven != null) rawMarkers.push({ key: 'breakeven', label: 'Breakeven', price: breakeven, color: '#facc15' })

  const sortedMarkers = [...rawMarkers].sort((a, b) => a.price - b.price)
  // One lane per marker (≤5 here) guarantees every label gets its own row —
  // with a lane count below the marker count, tightly clustered levels (e.g.
  // a near-ATM low-premium trade where Spot/Strike/Stop/Target/Breakeven all
  // sit within a hair of each other) could still be forced to share a lane
  // and collide; sizing lanes to the marker count rules that out entirely.
  const numLanes = Math.max(1, sortedMarkers.length)
  const laneLastPx = new Array(numLanes).fill(-Infinity)
  const minGapPx = 56
  const placed = sortedMarkers.map((m) => {
    const px = xScale(m.price)
    let lane = laneLastPx.findIndex((lastPx) => px - lastPx >= minGapPx)
    if (lane === -1) lane = laneLastPx.indexOf(Math.min(...laneLastPx))
    laneLastPx[lane] = px
    return { ...m, px, lane }
  })
  const laneY = Array.from({ length: numLanes }, (_, i) => (padT - 8) - (numLanes - 1 - i) * 15)

  return (
    <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-3">
      <p className="mb-1 text-sm font-semibold text-white">
        Payoff — {String(plan.action ?? '').replace(/_/g, ' ')} {fmtNum(plan.strike, 0)} ({String(plan.expiry ?? '')})
      </p>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" style={{ maxHeight: height }}>
        <line x1={padL} y1={zeroY} x2={width - padR} y2={zeroY} stroke="#475569" strokeWidth={1} />
        <path d={areaPath} fill={fillColor} stroke="none" />
        <path d={pathFor(expiryPnl)} fill="none" stroke={lineColor} strokeWidth={2.5} />
        <path d={pathFor(nowPnl)} fill="none" stroke="#38bdf8" strokeWidth={1.75} strokeDasharray="3,3" />

        {placed.map((m) => (
          <g key={m.key}>
            <line x1={m.px} y1={padT - 4} x2={m.px} y2={height - padB} stroke={m.color} strokeWidth={1} strokeDasharray="4,3" opacity={0.85} />
            <text x={m.px} y={laneY[m.lane]} fill={m.color} fontSize={10.5} textAnchor="middle" fontWeight={600}>{m.label}</text>
          </g>
        ))}

        <text x={padL - 8} y={yScale(yHi) + 4} fill="#94a3b8" fontSize={10} textAnchor="end">{yHi.toFixed(0)}</text>
        <text x={padL - 8} y={zeroY + 4} fill="#94a3b8" fontSize={10} textAnchor="end">0</text>
        <text x={padL - 8} y={yScale(yLo) + 4} fill="#94a3b8" fontSize={10} textAnchor="end">{yLo.toFixed(0)}</text>
        <text x={padL} y={height - 8} fill="#94a3b8" fontSize={10} textAnchor="start">{xMin.toFixed(0)}</text>
        <text x={width - padR} y={height - 8} fill="#94a3b8" fontSize={10} textAnchor="end">{xMax.toFixed(0)}</text>
      </svg>
      <div className="mt-1 flex flex-wrap items-center gap-3 text-[10px] text-slate-400">
        <span className="flex items-center gap-1"><span className="inline-block h-0.5 w-3" style={{ background: '#38bdf8' }} />P&amp;L right now</span>
        <span className="flex items-center gap-1"><span className="inline-block h-0.5 w-3" style={{ background: lineColor }} />P&amp;L at expiry</span>
      </div>
      <p className="mt-1 text-xs text-slate-500">
        Dotted blue = mark-to-market P&amp;L if price moves right now (time value intact). Solid line = P&amp;L if held to
        expiry (pure intrinsic value). Model estimate, not a live quote.
      </p>
    </div>
  )
}

function OiByStrikeBars({ rows }: { rows: Row[] }) {
  if (!rows.length) return null
  const data = rows.map((r) => ({
    strike: String(r.strike ?? ''),
    callOi: Number(r.ce_oi ?? 0),
    putOi: -(Number(r.pe_oi ?? 0)),
  }))
  return (
    <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-3">
      <p className="mb-2 text-sm font-semibold text-white">Open Interest by strike — Call OI (resistance) vs Put OI (support)</p>
      <div style={{ width: '100%', height: 280 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis dataKey="strike" tick={{ fontSize: 10, fill: '#94a3b8' }} />
            <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} />
            <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #334155', fontSize: 12 }} labelStyle={{ color: '#e2e8f0' }} />
            <Bar dataKey="callOi" name="Call OI" fill="#ef4444" />
            <Bar dataKey="putOi" name="Put OI" fill="#22c55e" />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

function OslActionCard({ result }: { result: Row }) {
  const direction = String(result.direction ?? 'NEUTRAL')
  const action = result.action as string | undefined
  const plan = result.trade_plan as Row | undefined

  return (
    <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-4">
      <p className="text-lg font-bold">
        <span className={verdictClass(direction)}>{OSL_DIRECTION_BADGE[direction] ?? direction}</span>
        {' · '}{fmtNum(result.confidence_pct, 1)}% confidence
      </p>

      {!action || !plan ? (
        <p className="mt-2 rounded-lg bg-amber-500/10 p-3 text-sm text-amber-300">
          🟡 WAIT — no clear confluence either way today. No trade suggested for this symbol.
        </p>
      ) : (
        <>
          <p className="mt-2 text-lg font-bold text-white sm:text-xl">
            {OSL_ACTION_BADGE[action] ?? action} — {String(result.symbol ?? '')} {fmtNum(plan.strike, 0)} {String(plan.side ?? '').toUpperCase()}
            {' · Expiry '}<span className="text-blue-300">{String(plan.expiry ?? '')}</span>
          </p>
          {result.switched_expiry ? (
            <p className="text-xs text-slate-500">⏭️ Nearest expiry had &lt;2 trading days left — automatically rolled to the next listed expiry.</p>
          ) : null}
          <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatCard label="Entry premium" value={`₹${fmtNum(plan.premium, 2)}`} />
            <StatCard label="Stop-loss (premium)" value={`₹${fmtNum(plan.stop_premium, 2)}`} />
            <StatCard label="Take-profit (premium)" value={`₹${fmtNum(plan.target_premium, 2)}`} />
            <StatCard label="Reward : Risk" value={`${fmtNum(plan.reward_risk_ratio, 2)} : 1`} />
          </div>
          <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatCard label="Spot" value={fmtNum(result.spot, 2)} />
            <StatCard label="Stop ~ underlying" value={fmtNum(plan.stop_underlying, 1)} />
            <StatCard label="Target ~ underlying" value={fmtNum(plan.target_underlying, 1)} />
            <StatCard label="Days to expiry" value={String(plan.days_to_expiry ?? '—')} />
          </div>
          <p className={`mt-3 rounded-lg p-3 text-xs ${plan.is_buy ? 'bg-emerald-500/10 text-emerald-300' : 'bg-amber-500/10 text-amber-300'}`}>
            {plan.is_buy ? '✅ ' : '⚠️ '}{String(plan.max_loss_note ?? '')}
          </p>
        </>
      )}
    </div>
  )
}

function OslSupportingMetrics({ result }: { result: Row }) {
  const buildup = (result.buildup as Row) ?? {}
  const premium = (result.premium as Row) ?? {}
  const skew = (result.skew as Row) ?? {}
  const volEnv = (result.vol_environment as Row) ?? {}
  return (
    <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="Price chg (1d)" value={result.price_chg_pct != null ? `${fmtNum(result.price_chg_pct, 2)}%` : '—'} />
        <StatCard label="PCR (OI)" value={fmtNum(result.pcr_oi, 2)} />
        <StatCard label="Max Pain" value={fmtNum(result.max_pain, 0)} />
        <StatCard label="OI Buildup" value={String(buildup.label ?? '—')} />
      </div>
      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="Support" value={fmtNum(result.support, 0)} />
        <StatCard label="Resistance" value={fmtNum(result.resistance, 0)} />
        <StatCard label="Synthetic Fut Premium" value={premium.available ? `${fmtNum(premium.premium_pct, 2)}%` : '—'} />
        <StatCard label="IV Skew (Put−Call)" value={skew.available ? `${fmtNum(skew.skew, 1)}pt` : '—'} />
      </div>
      <p className="mt-3 text-xs text-slate-500">
        <strong className="text-slate-400">IV environment:</strong> {String(volEnv.label ?? '—')} ({String(volEnv.source ?? '—')}) — {String(volEnv.reason ?? '')}
      </p>
    </div>
  )
}

function OslReasons({ result }: { result: Row }) {
  const [open, setOpen] = useState(false)
  const reasons = (result.reasons as string[]) ?? []
  if (!reasons.length) return null
  return (
    <div className="rounded-lg border border-slate-800/60 bg-slate-900/40">
      <button type="button" onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm font-semibold text-white">
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />} 🔍 Why this signal — every contributing factor
      </button>
      {open && (
        <div className="space-y-1 border-t border-slate-800/60 px-3 py-2">
          {reasons.map((r, i) => (
            <p key={i} className={r.startsWith('  ') ? 'pl-4 text-xs text-slate-500' : 'text-xs text-slate-300'}>
              {r.startsWith('  ') ? r.trim() : `• ${r}`}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}

function OptionShortLongStrategyExplainer() {
  const [open, setOpen] = useState(false)
  return (
    <div className="rounded-lg border border-slate-800/60 bg-slate-900/40">
      <button type="button" onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm font-semibold text-white">
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />} 📖 What this shows
      </button>
      {open && (
        <div className="space-y-2 border-t border-slate-800/60 px-3 py-3 text-xs text-slate-300">
          <p>Pick one or more indices or stocks, hit Analyze, and get one combined options-trade recommendation per symbol built from six independent reads:</p>
          <ul className="list-disc space-y-1 pl-4">
            <li><strong className="text-white">Options chain bias</strong> — PCR, fresh OI tilt, OI-wall support/resistance, max-pain pull (Bullish/Bearish/Neutral)</li>
            <li><strong className="text-white">OI Buildup</strong> — Long Buildup / Short Buildup / Short Covering / Long Unwinding — price change × OI change (an options-OI proxy — no separate NSE futures-OI feed is wired into this app)</li>
            <li><strong className="text-white">Premium / Discount</strong> — synthetic futures price via Put-Call Parity (Spot + ATM Call − ATM Put) — contango (premium) = bullish carry, backwardation (discount) = bearish carry</li>
            <li><strong className="text-white">IV Skew</strong> — ATM Put IV vs Call IV — an outsized gap flags elevated hedging demand (or unusual melt-up speculation)</li>
            <li><strong className="text-white">Momentum &amp; structure</strong> — trend/ADX/breakout (momentum engine) + Smart Money BOS/CHoCH structure bias</li>
            <li><strong className="text-white">IV environment</strong> — real India VIX / realized-vol percentile — decides whether to buy premium (cheap) or sell premium (rich)</li>
          </ul>
          <p>These combine into a signed confluence score → <strong className="text-white">UP / DOWN / NEUTRAL</strong> direction with a confidence %, then a specific action:</p>
          <ul className="list-disc space-y-1 pl-4">
            <li><strong className="text-emerald-400">Direction UP + IV cheap</strong> → BUY CALL (defined risk: max loss = premium paid)</li>
            <li><strong className="text-amber-400">Direction UP + IV rich</strong> → SELL PUT (collects rich premium; undefined risk below the strike unless capped with a further OTM put)</li>
            <li><strong className="text-rose-400">Direction DOWN + IV cheap</strong> → BUY PUT</li>
            <li><strong className="text-amber-400">Direction DOWN + IV rich</strong> → SELL CALL (same undefined-risk caveat)</li>
            <li><strong className="text-slate-400">NEUTRAL</strong> → WAIT, no trade suggested</li>
          </ul>
          <p>
            Expiry is the nearest listed one unless fewer than 2 trading days remain (gamma/theta/spread risk near expiry),
            in which case it automatically rolls to the next listed expiry. Strike is chosen by target delta (~0.40 when
            buying, ~0.20 when selling). Stop-loss and take-profit are given both as an option-premium level and an
            approximate underlying level (Black-Scholes-implied, assuming roughly half the remaining time has passed).
          </p>
          <p className="text-amber-400">
            No confidence % here is a guarantee, and no options trade — bought or sold — has zero risk. Buying options caps
            risk at the premium paid; selling options is open-ended unless converted to a spread. Live snapshot.
            Research / education only — NOT FINANCIAL ADVICE.
          </p>
        </div>
      )}
    </div>
  )
}

function OptionShortLongExpirySection({ merged, defaultOpen }: { merged: Row; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  if (!merged.ok) {
    return (
      <Alert type="error">
        ⚠️ {String(merged.expiry ?? 'This expiry')}: {String(merged.error ?? "Could not fetch this expiry's option chain.")}
      </Alert>
    )
  }
  const plan = merged.trade_plan as Row | undefined
  const payoff = merged.payoff as Row | undefined
  const action = merged.action as string | undefined
  const direction = String(merged.direction ?? 'NEUTRAL')

  return (
    <div className="rounded-lg border border-slate-800/60 bg-slate-900/40">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full flex-wrap items-center gap-2 px-3 py-2.5 text-left hover:bg-slate-800/30"
      >
        {open ? <ChevronDown size={14} className="shrink-0 text-slate-500" /> : <ChevronRight size={14} className="shrink-0 text-slate-500" />}
        <span className="font-semibold text-white">{String(merged.expiry ?? '—')}</span>
        <span className="text-sm text-slate-400">
          <span className={verdictClass(direction)}>{OSL_DIRECTION_BADGE[direction] ?? direction}</span>
          {' · '}{fmtNum(merged.confidence_pct, 0)}% confidence
          {action ? <> · <span className="font-medium text-white">{OSL_ACTION_BADGE[action] ?? action}</span>{plan ? ` ${fmtNum(plan.strike, 0)} ${String(plan.side ?? '').toUpperCase()}` : ''}</> : ' · WAIT'}
        </span>
      </button>
      {open && (
        <div className="space-y-4 border-t border-slate-800/60 p-3">
          <OslActionCard result={merged} />
          {plan && payoff ? <PayoffChart payoff={payoff} plan={plan} spot={merged.spot as number | null} /> : null}
          <OslSupportingMetrics result={merged} />
          <OiByStrikeBars rows={(merged.oi_strikes as Row[]) ?? []} />
          <OslReasons result={merged} />
        </div>
      )}
    </div>
  )
}

function OptionShortLongResult({ result }: { result: Row }) {
  if (!result.ok) {
    return (
      <Alert type="error">
        ⚠️ Could not fetch full option-chain/price data for <strong>{String(result.symbol ?? '')}</strong> right now —
        NSE may be rate-limiting or the symbol may not have listed F&amp;O contracts. Try again in a moment.
      </Alert>
    )
  }
  const byExpiry = (result.by_expiry as Row[]) ?? []
  return (
    <div className="space-y-3">
      {byExpiry.length === 0 ? (
        <p className="text-sm text-slate-500">No expiry data returned for this symbol.</p>
      ) : (
        byExpiry.map((e, i) => (
          <OptionShortLongExpirySection key={i} merged={{ ...result, ...e }} defaultOpen={i === 0} />
        ))
      )}
      <p className="text-xs text-slate-600">{OSL_RISK_DISCLAIMER}</p>
    </div>
  )
}

function OptionShortLongPanel({ data }: { data: Row }) {
  const results = (data.results as Row[]) ?? []
  const [activeIdx, setActiveIdx] = useState(0)
  if (!results.length) return <p className="text-sm text-slate-500">No results.</p>
  const active = results[Math.min(activeIdx, results.length - 1)]

  return (
    <div className="space-y-4">
      <OptionShortLongStrategyExplainer />
      {results.length > 1 && (
        <div className="flex flex-wrap gap-1.5">
          {results.map((r, i) => (
            <Chip key={i} selected={activeIdx === i} onClick={() => setActiveIdx(i)}>{String(r.symbol ?? `#${i + 1}`)}</Chip>
          ))}
        </div>
      )}
      <h4 className="text-sm font-semibold text-white">{String(active?.symbol ?? '—')}</h4>
      <OptionShortLongResult result={active} />
    </div>
  )
}

const _SETUP_BADGE: Record<string, string> = { LONG: '🟢 LONG', SHORT: '🔴 SHORT', NEUTRAL: '🟡 NEUTRAL' }

function EmaSmaIndicatorTables({ snap }: { snap: Row }) {
  const emaSma = [...((snap.ema as Row[]) ?? []), ...((snap.sma as Row[]) ?? [])]
  const indicators = (snap.indicators as Row[]) ?? []
  const { sorted: sortedEmaSma, sortKey: emaSmaSortKey, sortDir: emaSmaSortDir, handleSort: handleEmaSmaSort } = useSort(emaSma, {
    indicator: (e) => String(e.indicator ?? ''),
    value: (e) => (e.value != null ? Number(e.value) : null),
    action: (e) => String(e.action ?? ''),
  })
  const { sorted: sortedIndicators, sortKey: indicatorsSortKey, sortDir: indicatorsSortDir, handleSort: handleIndicatorsSort } = useSort(indicators, {
    indicator: (e) => String(e.indicator ?? ''),
    value: (e) => {
      if (e.value == null) return null
      const n = Number(e.value)
      return Number.isFinite(n) ? n : String(e.value)
    },
    action: (e) => String(e.action ?? ''),
    description: (e) => String(e.description ?? ''),
  })
  return (
    <div className="grid gap-4">
      <div className="min-w-0">
        <h5 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
          EMA/SMA {snap.price != null ? `· price ${fmtNum(snap.price, 4)}` : ''}
        </h5>
        {emaSma.length > 0 ? (
          <DataTable minWidth={320}>
            <thead>
              <tr>
                <SortableTh active={emaSmaSortKey === 'indicator'} direction={emaSmaSortDir} onSort={() => handleEmaSmaSort('indicator')}>Indicator</SortableTh>
                <SortableTh active={emaSmaSortKey === 'action'} direction={emaSmaSortDir} onSort={() => handleEmaSmaSort('action')}>Action</SortableTh>
                <SortableTh active={emaSmaSortKey === 'value'} direction={emaSmaSortDir} onSort={() => handleEmaSmaSort('value')}>Value</SortableTh>
              </tr>
            </thead>
            <tbody>
              {sortedEmaSma.map((e, i) => (
                <tr key={i}>
                  <Td>{String(e.indicator ?? '—')}</Td>
                  <Td className={verdictClass(String(e.action ?? ''))}>{String(e.action ?? '—')}</Td>
                  <Td>{fmtNum(e.value, 4)}</Td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        ) : <p className="text-xs text-slate-500">—</p>}
      </div>
      <div className="min-w-0">
        <h5 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">Technical Indicators</h5>
        {indicators.length > 0 ? (
          <DataTable minWidth={480}>
            <thead>
              <tr>
                <SortableTh active={indicatorsSortKey === 'indicator'} direction={indicatorsSortDir} onSort={() => handleIndicatorsSort('indicator')}>Indicator</SortableTh>
                <SortableTh active={indicatorsSortKey === 'action'} direction={indicatorsSortDir} onSort={() => handleIndicatorsSort('action')}>Action</SortableTh>
                <SortableTh active={indicatorsSortKey === 'value'} direction={indicatorsSortDir} onSort={() => handleIndicatorsSort('value')}>Value</SortableTh>
                <SortableTh active={indicatorsSortKey === 'description'} direction={indicatorsSortDir} onSort={() => handleIndicatorsSort('description')}>Description</SortableTh>
              </tr>
            </thead>
            <tbody>
              {sortedIndicators.map((e, i) => (
                <tr key={i}>
                  <Td>{String(e.indicator ?? '—')}</Td>
                  <Td className={verdictClass(String(e.action ?? ''))}>{String(e.action ?? '—')}</Td>
                  <Td>{e.value == null ? '—' : String(e.value)}</Td>
                  <Td className="max-w-sm !whitespace-normal text-slate-400">{String(e.description ?? '—')}</Td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        ) : <p className="text-xs text-slate-500">—</p>}
      </div>
    </div>
  )
}

function QuickAnalyzerPanel({ data }: { data: Row }) {
  const results = (data.results as Row[]) ?? []
  const [idx, setIdx] = useState(0)
  const [tfTab, setTfTab] = useState<string | null>(null)
  const r = results[idx] ?? results[0] ?? {}
  const momentum = (r.momentum as Row) ?? {}
  const perTf = (momentum.per_tf as Row[]) ?? []
  const showCombos = results.some((res) => res.fundamentals_combo != null || res.option_chain_combo != null)

  const { sorted: sortedResults, sortKey: resultsSortKey, sortDir: resultsSortDir, handleSort: handleResultsSort } = useSort(results, {
    ticker: (res) => String(res.ticker ?? ''),
    direction: (res) => String((res.setup as Row)?.direction ?? ''),
    confidence: (res) => ((res.setup as Row)?.confidence_pct != null ? Number((res.setup as Row).confidence_pct) : null),
    sl: (res) => ((res.setup as Row)?.sl_pct != null ? Number((res.setup as Row).sl_pct) : null),
    tp: (res) => ((res.setup as Row)?.tp_pct != null ? Number((res.setup as Row).tp_pct) : null),
    momentum_dir: (res) => String((res.momentum as Row)?.overall_direction ?? ''),
    momentum_strength: (res) => String((res.momentum as Row)?.overall_strength ?? ''),
    momentum_conf: (res) => ((res.momentum as Row)?.confidence_continue_pct != null ? Number((res.momentum as Row).confidence_continue_pct) : null),
    ema_bull: (res) => ((res.setup as Row)?.ema_bullish != null ? Number((res.setup as Row).ema_bullish) : null),
    indicator_bull: (res) => ((res.setup as Row)?.indicator_bullish != null ? Number((res.setup as Row).indicator_bullish) : null),
    fundamentals: (res) => (res.fundamentals_combo ? String((res.fundamentals_combo as Row).fundamental_signal ?? '') : ''),
    option_chain: (res) => (res.option_chain_combo ? String((res.option_chain_combo as Row).option_chain_bias ?? '') : ''),
  })
  const { sorted: sortedPerTf, sortKey: perTfSortKey, sortDir: perTfSortDir, handleSort: handlePerTfSort } = useSort(perTf, {
    tf: (t) => String(t.timeframe ?? ''),
    direction: (t) => String(t.trend_direction ?? ''),
    strength: (t) => String(t.strength ?? ''),
    adx: (t) => (t.adx != null ? Number(t.adx) : null),
    rsi: (t) => (t.rsi != null ? Number(t.rsi) : null),
    macd_hist: (t) => (t.macd_hist != null ? Number(t.macd_hist) : null),
    roc: (t) => (t.roc_pct != null ? Number(t.roc_pct) : null),
    vol: (t) => (t.volume_ratio != null ? Number(t.volume_ratio) : null),
    conf: (t) => (t.confidence_continue_pct != null ? Number(t.confidence_continue_pct) : null),
  })

  if (!results.length) return <p className="text-sm text-slate-500">No results.</p>

  const valid = results.filter((r) => !r.error)
  const setup = (r.setup as Row) ?? {}
  const technicalByTf = (r.technical_by_tf as Record<string, Row>) ?? {}
  const dailyRef = r.daily_reference as Row | undefined
  const tfKeys = Object.keys(technicalByTf)
  const activeTf = tfTab && tfKeys.includes(tfTab) ? tfTab : tfKeys[0]
  const faCombo = r.fundamentals_combo as Row | undefined
  const ocCombo = r.option_chain_combo as Row | undefined

  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-400">{valid.length} of {results.length} tickers analyzed</p>

      <DataTable minWidth={1000}>
        <thead>
          <tr>
            <SortableTh active={resultsSortKey === 'ticker'} direction={resultsSortDir} onSort={() => handleResultsSort('ticker')}>Ticker</SortableTh>
            <SortableTh active={resultsSortKey === 'direction'} direction={resultsSortDir} onSort={() => handleResultsSort('direction')}>Trade Setup</SortableTh>
            <SortableTh active={resultsSortKey === 'confidence'} direction={resultsSortDir} onSort={() => handleResultsSort('confidence')}>Confidence %</SortableTh>
            <SortableTh active={resultsSortKey === 'sl'} direction={resultsSortDir} onSort={() => handleResultsSort('sl')}>SL %</SortableTh>
            <SortableTh active={resultsSortKey === 'tp'} direction={resultsSortDir} onSort={() => handleResultsSort('tp')}>TP %</SortableTh>
            <SortableTh active={resultsSortKey === 'momentum_dir'} direction={resultsSortDir} onSort={() => handleResultsSort('momentum_dir')}>Momentum</SortableTh>
            <SortableTh active={resultsSortKey === 'momentum_strength'} direction={resultsSortDir} onSort={() => handleResultsSort('momentum_strength')}>Mom. Strength</SortableTh>
            <SortableTh active={resultsSortKey === 'momentum_conf'} direction={resultsSortDir} onSort={() => handleResultsSort('momentum_conf')}>Mom. Confidence %</SortableTh>
            <SortableTh active={resultsSortKey === 'ema_bull'} direction={resultsSortDir} onSort={() => handleResultsSort('ema_bull')}>EMA Bull/Bear</SortableTh>
            <SortableTh active={resultsSortKey === 'indicator_bull'} direction={resultsSortDir} onSort={() => handleResultsSort('indicator_bull')}>Indicators Bull/Bear</SortableTh>
            {showCombos && (
              <>
                <SortableTh active={resultsSortKey === 'fundamentals'} direction={resultsSortDir} onSort={() => handleResultsSort('fundamentals')}>Fundamentals</SortableTh>
                <SortableTh active={resultsSortKey === 'option_chain'} direction={resultsSortDir} onSort={() => handleResultsSort('option_chain')}>Option Chain</SortableTh>
              </>
            )}
            <Th></Th>
          </tr>
        </thead>
        <tbody>
          {sortedResults.map((res) => {
            const i = results.indexOf(res)
            const s = (res.setup as Row) ?? {}
            const m = (res.momentum as Row) ?? {}
            const rFa = res.fundamentals_combo as Row | undefined
            const rOc = res.option_chain_combo as Row | undefined
            return (
              <tr
                key={String(res.ticker) + i}
                className={`cursor-pointer hover:bg-slate-800/30 ${idx === i ? 'bg-slate-800/40' : ''}`}
                onClick={() => { setIdx(i); setTfTab(null) }}
              >
                <Td className="font-medium text-white">{String(res.ticker ?? '—')}</Td>
                {res.error ? (
                  <Td colSpan={showCombos ? 12 : 10} className="text-rose-400">ERROR — {String(res.error)}</Td>
                ) : (
                  <>
                    <Td className={verdictClass(String(s.direction ?? ''))}>{_SETUP_BADGE[String(s.direction ?? '')] ?? String(s.direction ?? '—')}</Td>
                    <Td>{fmtNum(s.confidence_pct, 1)}</Td>
                    <Td>{s.sl_pct != null ? fmtNum(s.sl_pct, 2) : '—'}</Td>
                    <Td>{s.tp_pct != null ? fmtNum(s.tp_pct, 2) : '—'}</Td>
                    <Td>{String(m.overall_direction ?? '—')}</Td>
                    <Td>{String(m.overall_strength ?? '—')}</Td>
                    <Td>{fmtNum(m.confidence_continue_pct, 0)}</Td>
                    <Td>{s.ema_total ? `${s.ema_bullish}/${s.ema_bearish}` : '—'}</Td>
                    <Td>{s.indicator_total ? `${s.indicator_bullish}/${s.indicator_bearish}` : '—'}</Td>
                    {showCombos && (
                      <>
                        <Td>{rFa ? (rFa.available ? String(rFa.fundamental_signal ?? '—') : 'unavailable') : '—'}</Td>
                        <Td>{rOc ? (rOc.available ? String(rOc.option_chain_bias ?? '—') : 'unavailable') : '—'}</Td>
                      </>
                    )}
                  </>
                )}
                <Td onClick={(e) => e.stopPropagation()}>
                  <AddToWatchlistButton ticker={String(res.ticker ?? '')} compact />
                </Td>
              </tr>
            )
          })}
        </tbody>
      </DataTable>

      <div className="flex flex-wrap gap-2">
        {results.map((res, i) => (
          <Chip key={`${String(res.ticker)}-${i}`} selected={idx === i} onClick={() => { setIdx(i); setTfTab(null) }}>
            {String(res.ticker)}
          </Chip>
        ))}
      </div>

      {r.error ? (
        <Alert type="error">{String(r.error)}</Alert>
      ) : (
        <>
          <div className="rounded-2xl border border-slate-800/80 bg-slate-900/40 px-4 py-5 sm:px-6">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs font-medium uppercase tracking-wider text-slate-500">Quick Analyzer · {String(r.ticker)}</p>
              <AddToWatchlistButton ticker={String(r.ticker ?? '')} compact />
            </div>
            <p className={`mt-1 text-xl font-bold sm:text-2xl ${verdictClass(String(setup.direction ?? ''))}`}>
              {_SETUP_BADGE[String(setup.direction ?? '')] ?? String(setup.direction ?? '—')} · {fmtNum(setup.confidence_pct, 1)}% confidence
              {setup.sl_pct != null ? ` · SL ${fmtNum(setup.sl_pct, 2)}% / TP ${fmtNum(setup.tp_pct, 2)}%` : ''}
            </p>
            {((setup.reasons as string[]) ?? []).length > 0 && (
              <ul className="mt-2 space-y-1 text-sm text-slate-300">
                {(setup.reasons as string[]).map((rr, i) => <li key={i} className="flex gap-2"><span className="text-slate-500">•</span>{rr}</li>)}
              </ul>
            )}
            {setup.position_size != null && (
              <div className="mt-3 rounded-lg border border-slate-800/60 bg-slate-900/40 p-3">
                <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Suggested position — sized off your paper account</p>
                <div className="mt-2 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                  <div><p className="text-xs text-slate-500">Quantity</p><p className="font-medium text-white">{fmtNum((setup.position_size as Row).quantity, 0)}</p></div>
                  <div><p className="text-xs text-slate-500">Notional</p><p className="font-medium text-white">₹{fmtNum((setup.position_size as Row).notional, 0)}</p></div>
                  <div><p className="text-xs text-slate-500">Risk if stopped</p><p className="font-medium text-white">₹{fmtNum((setup.position_size as Row).risk_amount, 0)} ({fmtNum((setup.position_size as Row).risk_pct_of_equity, 2)}%)</p></div>
                  <div><p className="text-xs text-slate-500">Portfolio risk already open</p><p className="font-medium text-white">{fmtNum((setup.position_size as Row).portfolio_open_risk_pct, 2)}%</p></div>
                </div>
                {Boolean((setup.position_size as Row).already_holding) && (
                  <p className="mt-2 text-xs text-amber-400">You already hold a position in this ticker — check total exposure before adding more.</p>
                )}
                {Boolean((setup.position_size as Row).portfolio_at_risk_cap) && (
                  <p className="mt-2 text-xs text-rose-400">Total open portfolio risk is already at/above the 6% cap — consider skipping new entries until existing risk comes down.</p>
                )}
                {Boolean((setup.position_size as Row).capped_by_cash) && (
                  <p className="mt-2 text-xs text-slate-500">Size capped by available cash, not the risk formula.</p>
                )}
              </div>
            )}
            {(faCombo || ocCombo) && setup.technical_direction != null && (
              <p className="mt-2 text-xs text-slate-500">
                Technical-only: {_SETUP_BADGE[String(setup.technical_direction ?? '')] ?? String(setup.technical_direction ?? '—')} · {fmtNum(setup.technical_confidence_pct, 0)}% confidence
              </p>
            )}
            {faCombo && (
              <div className="mt-2 text-sm text-slate-400">
                {faCombo.available ? (
                  <p>📚 <strong>Combined with Fundamentals:</strong> {String(faCombo.note ?? '')} (Signal: {String(faCombo.fundamental_signal ?? '—')} · {fmtNum(faCombo.fundamental_confidence_pct, 0)}% · Valuation: {String(faCombo.fundamental_valuation ?? '—')})</p>
                ) : (
                  <p className="text-xs text-slate-500">📚 Fundamentals unavailable for this ticker: {String(faCombo.error ?? 'unknown error')}</p>
                )}
              </div>
            )}
            {ocCombo && (
              <div className="mt-2 text-sm text-slate-400">
                {ocCombo.available ? (
                  <p>⛓️ <strong>Combined with Option Chain:</strong> {String(ocCombo.note ?? '')} (Bias: {String(ocCombo.option_chain_bias ?? '—')} · {fmtNum(ocCombo.option_chain_confidence_pct, 0)}%{ocCombo.pcr_oi != null ? ` · PCR: ${fmtNum(ocCombo.pcr_oi, 2)}` : ''}{ocCombo.max_pain != null ? ` · Max Pain: ${fmtNum(ocCombo.max_pain, 0)}` : ''})</p>
                ) : (
                  <p className="text-xs text-slate-500">⛓️ Option Chain unavailable for this ticker: {String(ocCombo.error ?? 'unknown error')}</p>
                )}
              </div>
            )}
          </div>

          {perTf.length > 0 && (
            <div>
              <h4 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">Momentum — per timeframe</h4>
              <DataTable minWidth={800}>
                <thead>
                  <tr>
                    <SortableTh active={perTfSortKey === 'tf'} direction={perTfSortDir} onSort={() => handlePerTfSort('tf')}>TF</SortableTh>
                    <SortableTh active={perTfSortKey === 'direction'} direction={perTfSortDir} onSort={() => handlePerTfSort('direction')}>Direction</SortableTh>
                    <SortableTh active={perTfSortKey === 'strength'} direction={perTfSortDir} onSort={() => handlePerTfSort('strength')}>Strength</SortableTh>
                    <SortableTh active={perTfSortKey === 'adx'} direction={perTfSortDir} onSort={() => handlePerTfSort('adx')}>ADX</SortableTh>
                    <SortableTh active={perTfSortKey === 'rsi'} direction={perTfSortDir} onSort={() => handlePerTfSort('rsi')}>RSI</SortableTh>
                    <SortableTh active={perTfSortKey === 'macd_hist'} direction={perTfSortDir} onSort={() => handlePerTfSort('macd_hist')}>MACD Hist</SortableTh>
                    <SortableTh active={perTfSortKey === 'roc'} direction={perTfSortDir} onSort={() => handlePerTfSort('roc')}>ROC %</SortableTh>
                    <SortableTh active={perTfSortKey === 'vol'} direction={perTfSortDir} onSort={() => handlePerTfSort('vol')}>Volume x</SortableTh>
                    <SortableTh active={perTfSortKey === 'conf'} direction={perTfSortDir} onSort={() => handlePerTfSort('conf')}>Confidence %</SortableTh>
                  </tr>
                </thead>
                <tbody>
                  {sortedPerTf.map((tf, i) => (
                    <tr key={i}>
                      <Td>{String(tf.timeframe)}</Td>
                      <Td className={verdictClass(String(tf.trend_direction ?? ''))}>{String(tf.trend_direction ?? '—')}</Td>
                      <Td>{String(tf.strength ?? '—')}</Td>
                      <Td>{fmtNum(tf.adx)}</Td>
                      <Td>{fmtNum(tf.rsi)}</Td>
                      <Td>{fmtNum(tf.macd_hist)}</Td>
                      <Td>{fmtNum(tf.roc_pct)}</Td>
                      <Td>{fmtNum(tf.volume_ratio)}</Td>
                      <Td>{fmtNum(tf.confidence_continue_pct, 0)}</Td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            </div>
          )}

          {tfKeys.length > 0 ? (
            <div>
              <h4 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">EMA / Technical Indicators — per timeframe</h4>
              <div className="mb-3 flex flex-wrap gap-1.5">
                {tfKeys.map((tf) => (
                  <Chip key={tf} selected={activeTf === tf} onClick={() => setTfTab(tf)}>{tf}</Chip>
                ))}
              </div>
              {activeTf && <EmaSmaIndicatorTables snap={technicalByTf[activeTf]} />}
            </div>
          ) : (
            <p className="text-xs text-slate-500">EMA / Technical Indicators unavailable — insufficient OHLCV on the selected timeframe(s).</p>
          )}

          <div>
            <h4 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-400">📌 Daily reference (Dhan.co) — not timeframe-specific</h4>
            {dailyRef ? <EmaSmaIndicatorTables snap={dailyRef} /> : (
              <p className="text-xs text-slate-500">Unavailable for this ticker (outside Dhan's coverage).</p>
            )}
          </div>
        </>
      )}
    </div>
  )
}

function StrategyRunsTable({ runs }: { runs: Row[] }) {
  const extract = (run: Row) => {
    const analysis = (run.analysis as Row) ?? {}
    const live = (analysis.live as Row) ?? analysis
    const verdict = live.verdict ?? analysis.verdict ?? analysis.primary_label
    const confidence = live.confidence_pct ?? live.confidence ?? analysis.confidence
    const take = live.take_trade ?? analysis.take_trade ?? analysis.actionable
    return { verdict, confidence, take }
  }
  const { sorted, sortKey, sortDir, handleSort } = useSort(runs, {
    strategy: (run) => String(run.label ?? run.strategy_id ?? ''),
    verdict: (run) => String(extract(run).verdict ?? run.error ?? ''),
    confidence: (run) => {
      const c = extract(run).confidence
      return c != null ? Number(c) : null
    },
    take: (run) => (extract(run).take ? 1 : 0),
  })
  return (
    <DataTable>
      <thead>
        <tr>
          <SortableTh active={sortKey === 'strategy'} direction={sortDir} onSort={() => handleSort('strategy')}>Strategy</SortableTh>
          <SortableTh active={sortKey === 'verdict'} direction={sortDir} onSort={() => handleSort('verdict')}>Verdict</SortableTh>
          <SortableTh active={sortKey === 'confidence'} direction={sortDir} onSort={() => handleSort('confidence')}>Confidence</SortableTh>
          <SortableTh active={sortKey === 'take'} direction={sortDir} onSort={() => handleSort('take')}>Take</SortableTh>
        </tr>
      </thead>
      <tbody>
        {sorted.map((run, i) => {
          const { verdict, confidence, take } = extract(run)
          return (
            <tr key={i}>
              <Td>{String(run.label ?? run.strategy_id)}</Td>
              <Td className={verdictClass(String(verdict ?? ''))}>{String(verdict ?? run.error ?? '—')}</Td>
              <Td>{confidence != null ? `${fmtNum(confidence, 0)}%` : '—'}</Td>
              <Td>{take ? '✅' : '—'}</Td>
            </tr>
          )
        })}
      </tbody>
    </DataTable>
  )
}

function MtfTimeframeCard({ r }: { r: Row }) {
  const [showReasons, setShowReasons] = useState(false)
  const bias = String(r.bias ?? '—')
  const strengthLabel = String(r.strength_label ?? '—')
  const reversalPct = Number(r.reversal_probability_pct ?? 0)
  const reasons = (r.reversal_reasons as string[]) ?? []
  const components = (r.strength_components as Row) ?? {}

  return (
    <div className="rounded-xl border border-slate-800/60 bg-slate-900/40 p-4">
      <div className="flex items-center justify-between gap-2">
        <p className="font-semibold text-white">{String(r.label ?? r.timeframe ?? '—')}</p>
        <span className={`text-xs font-semibold ${verdictClass(bias)}`}>{String(r.bias_arrow ?? bias)}</span>
      </div>
      <div className="mt-2 grid grid-cols-3 gap-2 text-center text-xs">
        <div>
          <p className="uppercase tracking-wide text-slate-500">Composite</p>
          <p className="mt-0.5 font-medium text-white">{fmtNum(r.composite, 1)}</p>
        </div>
        <div>
          <p className="uppercase tracking-wide text-slate-500">Strength</p>
          <p className="mt-0.5 font-medium text-white">{fmtNum(r.strength_score, 0)} · {strengthLabel}</p>
        </div>
        <div>
          <p className="uppercase tracking-wide text-slate-500">Reversal risk</p>
          <p className={`mt-0.5 font-medium ${reversalPct >= 55 ? 'text-amber-400' : 'text-white'}`}>{reversalPct.toFixed(0)}%</p>
        </div>
      </div>
      <p className="mt-3 text-[12px] leading-relaxed text-slate-300">{String(r.plain_english ?? '')}</p>
      <p className="mt-2 text-[11px] text-slate-500">
        ADX {fmtNum(components.adx, 1)} · Efficiency ratio {fmtNum(components.efficiency_ratio, 2)} · Directional conviction {fmtNum(components.directional_conviction, 0)}
      </p>
      {reasons.length > 0 && (
        <div className="mt-2 border-t border-slate-800/60 pt-2">
          <button
            type="button"
            onClick={() => setShowReasons((v) => !v)}
            className="flex items-center gap-1 text-[11px] text-slate-500 hover:text-slate-300"
          >
            {showReasons ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            Reversal signal breakdown ({reasons.length})
          </button>
          {showReasons && (
            <ul className="mt-1.5 space-y-0.5 text-[11px] text-slate-500">
              {reasons.map((reason, i) => <li key={i}>• {reason}</li>)}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}

function MtfTrendStrengthPanel({ data }: { data: Row }) {
  const resultsMap = (data.results as Record<string, Row>) ?? {}
  const tickers = Object.keys(resultsMap)
  const [idx, setIdx] = useState(0)
  if (!tickers.length) return <p className="text-sm text-slate-500">No results.</p>

  const ticker = tickers[Math.min(idx, tickers.length - 1)]
  const r = resultsMap[ticker] ?? {}
  const tfMap = (r.timeframes as Record<string, Row>) ?? {}
  const tfKeys = Object.keys(tfMap)
  const errors = (r.errors as Record<string, string>) ?? {}
  const confluence = (r.confluence as Row) ?? {}
  const elevated = (r.elevated_reversal_timeframes as string[]) ?? []

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {tickers.map((t, i) => (
          <Chip key={t} selected={idx === i} onClick={() => setIdx(i)}>{t}</Chip>
        ))}
      </div>

      <div className="rounded-2xl border border-slate-800/80 bg-slate-900/40 px-4 py-5 sm:px-6">
        <p className="text-xs font-medium uppercase tracking-wider text-slate-500">Cross-timeframe confluence — {ticker}</p>
        <p className={`mt-1 text-xl font-bold sm:text-2xl ${verdictClass(String(confluence.verdict ?? ''))}`}>
          {String(confluence.verdict ?? '—')}
        </p>
        <p className="mt-1 text-sm text-slate-400">
          Avg score {fmtNum(confluence.avg_score, 1)}/100 · Avg confidence {fmtNum(confluence.avg_confidence, 1)}% ·{' '}
          {String(confluence.bull_count ?? 0)} bullish / {String(confluence.bear_count ?? 0)} bearish / {String(confluence.neutral_count ?? 0)} neutral of {String(confluence.total_tfs ?? 0)} timeframes
        </p>
        <p className={`mt-2 text-sm ${elevated.length ? 'text-amber-400' : 'text-slate-400'}`}>
          {String(r.reversal_summary ?? '')}
        </p>
      </div>

      {Object.keys(errors).length > 0 && (
        <Alert type="error">{Object.entries(errors).map(([tf, e]) => `${tf}: ${e}`).join(' · ')}</Alert>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {tfKeys.map((tf) => <MtfTimeframeCard key={tf} r={tfMap[tf]} />)}
      </div>
    </div>
  )
}

function MarketMoversPanel({ data }: { data: Row }) {
  const gainers = (data.gainers as Row[]) ?? []
  const losers = (data.losers as Row[]) ?? []
  if (!gainers.length && !losers.length) {
    return <p className="text-sm text-slate-500">No movers data for this selection.</p>
  }
  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-500">
        {String(data.index ?? '')} · {String(data.timeframe ?? '')}
        {data.source ? ` · source: ${String(data.source)}` : ''}
        {data.benchmark != null && data.benchmark_pct != null ? ` · benchmark ${String(data.benchmark)} ${fmtNum(data.benchmark_pct, 2)}%` : ''}
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <h4 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-emerald-400">
            <TrendingUp size={14} /> Top gainers
          </h4>
          <DataTable minWidth={280}>
            <thead><tr><Th>Symbol</Th><Th>Change %</Th><Th>Last</Th></tr></thead>
            <tbody>
              {gainers.map((g, i) => (
                <tr key={i}>
                  <Td className="font-medium text-white">{String(g.symbol ?? '—')}</Td>
                  <Td className="text-emerald-400">+{fmtNum(g.pct, 2)}%</Td>
                  <Td className="tabular-nums">{fmtNum(g.last, 2)}</Td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        </div>
        <div>
          <h4 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-rose-400">
            <TrendingDown size={14} /> Top losers
          </h4>
          <DataTable minWidth={280}>
            <thead><tr><Th>Symbol</Th><Th>Change %</Th><Th>Last</Th></tr></thead>
            <tbody>
              {losers.map((l, i) => (
                <tr key={i}>
                  <Td className="font-medium text-white">{String(l.symbol ?? '—')}</Td>
                  <Td className="text-rose-400">{fmtNum(l.pct, 2)}%</Td>
                  <Td className="tabular-nums">{fmtNum(l.last, 2)}</Td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        </div>
      </div>
    </div>
  )
}

export function CommandCenterResults({
  tab, data, assetClass, showCharts = false,
}: {
  tab: string
  data: Row
  assetClass?: string
  showCharts?: boolean
}) {
  if (data.error && tab !== 'investigation' && tab !== 'investigation_strategies') {
    return <Alert type="error">{String(data.error)}</Alert>
  }

  switch (tab) {
    case 'tomorrow_outlook':
      return <TomorrowOutlookPanel data={data} />
    case 'mega_analyser':
      return <MegaAnalyserPanel data={data} />
    case 'buy_sell':
      return <BuySellPanel data={data} />
    case 'investigation':
      return <TickerInvestigationPanel data={data} />
    case 'global_market_mood':
      return <GlobalMarketMoodPanel data={data} />
    case 'mega_setup_advisor':
      return <MegaSetupAdvisorPanel data={data} />
    case 'option_chain':
      return <OptionChainPanel data={data} />
    case 'option_short_long':
      return <OptionShortLongPanel data={data} />
    case 'india_market_heatmap':
      return <IndiaMarketHeatmapPanel data={data} assetClass={assetClass === 'us' || assetClass === 'crypto' ? assetClass : 'india'} />
    case 'nse_world_indices':
      return <NseWorldIndicesPanel data={data} />
    case 'coindcx_24h_volatility':
      return <CoinDcx24hVolatilityPanel data={data} />
    case 'quick_analyzer':
      return <QuickAnalyzerPanel data={data} />
    case 'momentum':
      return <MomentumPanel data={data} />
    case 'divergences':
      return <DivergencesPanel data={data} />
    case 'candlestick_chart_patterns':
      return <PatternsPanel data={data} />
    case 'stop_hunt':
      return <StopHuntPanel data={data} />
    case 'take_profit':
      return <TakeProfitPanel data={data} />
    case 'real_bottom':
      return <RealBottomPanel data={data} />
    case 'weak_strong':
      return <WeakStrongPanel data={data} />
    case 'copy_trade':
      return <CopyTradePanel data={data} />
    case 'sma_20_200':
      return <Sma20200Panel data={data} assetClass={assetClass ?? 'india'} />
    case 'take_trade':
      return <TakeTradePanel data={data} />
    case 'ema_position':
      return <EmaPositionPanel data={data} showCharts={showCharts} />
    case 'mtf_trend_strength':
      return <MtfTrendStrengthPanel data={data} />
    case 'market_movers':
      return <MarketMoversPanel data={data} />
    case 'trade_setup':
      return <TradeSetupPanel data={data} assetClass={assetClass ?? 'india'} />
    case 'fundamental_analysis':
      return <FundamentalAnalysisPanel data={data} />
    case 'stock_upgrade_downgrade':
      return <StockUpgradeDowngradePanel data={data} />
    case 'one_click_intraday':
      return <OneClickPanel data={data} style="intraday" />
    case 'one_click_scalping':
      return <OneClickPanel data={data} style="scalping" />
    case 'one_click_swing':
      return <OneClickPanel data={data} style="swing" />
    case 'investigation_strategies':
      return (
        <TickerInvestigationPanel
          data={data}
          renderExtra={(r) => {
            const selected = (r.selected_strategies as string[]) ?? []
            const runs = (r.strategy_runs as Row[]) ?? []
            if (!selected.length && !runs.length) return null
            return (
              <div className="space-y-2">
                {selected.length > 0 && (
                  <p className="text-xs text-slate-500">Strategies combined: {selected.join(', ')}</p>
                )}
                {runs.length > 0 && (
                  <div>
                    <h4 className="mb-2 text-sm font-semibold text-white">Selected strategy runs</h4>
                    <StrategyRunsTable runs={runs} />
                  </div>
                )}
              </div>
            )
          }}
        />
      )
    default:
      return <p className="text-sm text-slate-500">Unknown section.</p>
  }
}
