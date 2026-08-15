import { useMemo, useState } from 'react'
import { Bot } from 'lucide-react'
import { AskAIPanel, buildAskContext } from '../ai/AskAIPanel'
import { Button } from '../ui/Button'

/** Shared PA / SMC coach prompt for chart Investigate with AI. */
export const CHART_INVESTIGATE_SYSTEM = `You are a Price Action and Smart Money Concepts (SMC) expert.
Use ONLY the chart/context data provided. Be concise and actionable.
Decide whether to take a trade right now.

Structure your reply EXACTLY as:

## DECISION
TAKE | NO TRADE

## SIDE
LONG | SHORT | NONE

## CONFIDENCE
NN%

## SL %
N.N%

## TP %
N.N%

## THESIS
2-4 sentences using price action + smart money language (structure, liquidity, BOS/CHOCH,
order blocks / supply-demand, sweeps, displacement, volume). Cite levels from the context only.

## INVALIDATION
What kills the idea (level or condition from the data).

Do not invent prices or indicators not present in the context.
Research / education only — not financial advice.`

export const CHART_INVESTIGATE_QUESTION =
  'You are a price action & smart money expert looking at this chart. ' +
  'Should I take a trade now? If yes, LONG or SHORT with %SL, %TP, and %Confidence. ' +
  'If no, explain why to wait.'

type ChartBar = {
  time?: string
  open?: number
  high?: number
  low?: number
  close?: number
  volume?: number | null
}

/** Compact OHLC summary for AI (keeps token use reasonable). */
export function buildChartInvestigateContext(opts: {
  title?: string
  ticker?: string | null
  assetClass?: string | null
  bars?: ChartBar[] | null
  levels?: Array<{ label?: string; price?: number }> | null
  extra?: Record<string, unknown> | null
}): string {
  const bars = (opts.bars || []).filter((b) => b && b.close != null)
  const tail = bars.slice(-80)
  const first = tail[0]
  const last = tail[tail.length - 1]
  const highs = tail.map((b) => Number(b.high)).filter(Number.isFinite)
  const lows = tail.map((b) => Number(b.low)).filter(Number.isFinite)
  const hi = highs.length ? Math.max(...highs) : null
  const lo = lows.length ? Math.min(...lows) : null
  const netPct =
    first?.close && last?.close && Number(first.close) > 0
      ? (((Number(last.close) / Number(first.close)) - 1) * 100).toFixed(2)
      : null

  const sample = tail.slice(-24).map((b) => ({
    t: b.time,
    o: b.open,
    h: b.high,
    l: b.low,
    c: b.close,
    v: b.volume ?? undefined,
  }))

  return buildAskContext(opts.title || 'Chart Investigate with AI', {
    ticker: opts.ticker,
    asset_class: opts.assetClass,
    bars_in_context: tail.length,
    last_close: last?.close,
    window_high: hi,
    window_low: lo,
    net_change_pct: netPct,
    levels: opts.levels || [],
    recent_ohlc: sample,
    ...(opts.extra || {}),
  })
}

/** Inline panel opened from chart "Investigate with AI". */
export function ChartInvestigateAiPanel({
  open,
  onClose,
  context,
  section = 'chart/investigate',
  className = '',
}: {
  open: boolean
  onClose?: () => void
  context: string
  section?: string
  className?: string
}) {
  if (!open || !context.trim()) return null
  return (
    <div className={className}>
      <AskAIPanel
        context={context}
        section={section}
        systemPrompt={CHART_INVESTIGATE_SYSTEM}
        title="Investigate with AI"
        buttonLabel="Investigate with AI"
        defaultQuestion={CHART_INVESTIGATE_QUESTION}
        showPredictNextMove
      />
      {onClose && (
        <div className="mt-2">
          <Button variant="ghost" onClick={onClose}>
            Close AI panel
          </Button>
        </div>
      )}
    </div>
  )
}

/** Toolbar chip + panel for charts that already have OHLC in memory. */
export function useChartInvestigateAi(opts: {
  ticker?: string | null
  assetClass?: string | null
  bars?: ChartBar[] | null
  levels?: Array<{ label?: string; price?: number }> | null
  section?: string
  extra?: Record<string, unknown> | null
}) {
  const [open, setOpen] = useState(false)
  const context = useMemo(
    () =>
      buildChartInvestigateContext({
        ticker: opts.ticker,
        assetClass: opts.assetClass,
        bars: opts.bars,
        levels: opts.levels,
        extra: opts.extra,
      }),
    [opts.ticker, opts.assetClass, opts.bars, opts.levels, opts.extra],
  )

  const openInvestigate = () => setOpen(true)
  const closeInvestigate = () => setOpen(false)

  const ToolbarButton = (
    <button
      type="button"
      onClick={openInvestigate}
      className="inline-flex items-center gap-1.5 rounded-full border border-violet-500/35 bg-violet-500/10 px-2.5 py-1 text-[11px] font-medium text-violet-200 hover:bg-violet-500/20"
      title="Price action & smart money — TAKE/NO TRADE · LONG/SHORT · %SL · %TP · %Confidence"
    >
      <Bot size={13} />
      Investigate with AI
    </button>
  )

  const Panel = (
    <ChartInvestigateAiPanel
      open={open}
      onClose={closeInvestigate}
      context={context}
      section={opts.section || 'chart/investigate'}
      className="mt-3"
    />
  )

  return { open, setOpen, openInvestigate, closeInvestigate, ToolbarButton, Panel, context }
}
