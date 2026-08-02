import type { ReactNode } from 'react'

function fmt(v: number | null | undefined, digits = 2, suffix = ''): string {
  if (typeof v !== 'number' || !Number.isFinite(v)) return '—'
  return `${v.toFixed(digits)}${suffix}`
}

function Metric({ label, value, plain }: { label: string; value: string; plain?: string }) {
  return (
    <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-3">
      <p className="text-[11px] uppercase tracking-wider text-slate-500">{label}</p>
      <p className="mt-1 text-lg font-semibold text-slate-100">{value}</p>
      {plain && <p className="mt-1.5 text-[11px] leading-relaxed text-slate-400">{plain}</p>}
    </div>
  )
}

function Section({
  title,
  plainEnglish,
  children,
}: {
  title: string
  plainEnglish: string
  children: ReactNode
}) {
  return (
    <div className="space-y-3">
      <div>
        <h4 className="text-sm font-semibold text-white">{title}</h4>
        <p className="mt-1 text-sm leading-relaxed text-slate-400">{plainEnglish}</p>
      </div>
      {children}
    </div>
  )
}

function AdviceList({
  title,
  items,
  empty,
  tone,
}: {
  title: string
  items: string[]
  empty: string
  tone: 'good' | 'bad' | 'improve'
}) {
  const styles = {
    good: 'border-teal-500/30 bg-teal-500/5 text-teal-400',
    bad: 'border-rose-500/30 bg-rose-500/5 text-rose-400',
    improve: 'border-amber-500/30 bg-amber-500/5 text-amber-400',
  }[tone]
  return (
    <div className={`rounded-lg border p-3 ${styles.split(' ').slice(0, 2).join(' ')}`}>
      <p className={`text-xs font-semibold uppercase tracking-wider ${styles.split(' ').slice(2).join(' ')}`}>
        {title}
      </p>
      <ul className="mt-2 list-disc space-y-2 pl-4 text-sm leading-relaxed text-slate-200">
        {items.map((g) => (
          <li key={g}>{g}</li>
        ))}
        {!items.length && <li className="text-slate-500">{empty}</li>}
      </ul>
    </div>
  )
}

export interface AdvancedReport {
  label?: string | null
  context?: Record<string, unknown>
  core_performance?: Record<string, number | string | null | undefined>
  risk_drawdown?: Record<string, number | null | undefined>
  risk_adjusted?: Record<string, number | null | undefined>
  execution_costs?: {
    costs_pct?: number | null
    costs_bps?: number | null
    slippage_note?: string
  }
  robustness?: {
    out_of_sample?: Record<string, unknown>
    monte_carlo?: Record<string, unknown>
  }
  assessment?: {
    score?: number
    verdict?: string
    good?: string[]
    bad?: string[]
    improve?: string[]
  }
}

export function AdvancedBacktestReportPanel({ report }: { report: AdvancedReport }) {
  const core = report.core_performance || {}
  const risk = report.risk_drawdown || {}
  const adj = report.risk_adjusted || {}
  const costs = report.execution_costs || {}
  const oos = (report.robustness?.out_of_sample || {}) as Record<string, any>
  const mc = (report.robustness?.monte_carlo || {}) as Record<string, any>
  const a = report.assessment || {}
  const pfDisplay = core.profit_factor_display ?? (core.profit_factor != null ? fmt(Number(core.profit_factor), 2) : '—')

  const score = a.score
  const scoreColor =
    typeof score === 'number'
      ? score >= 7.5
        ? 'text-teal-400'
        : score >= 5
          ? 'text-amber-400'
          : 'text-rose-400'
      : 'text-slate-300'

  return (
    <div className="space-y-8 rounded-xl border border-slate-800/70 bg-slate-950/40 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-2xl">
          <p className="text-xs uppercase tracking-wider text-slate-500">Advanced backtesting report</p>
          <h3 className="mt-1 text-lg font-semibold text-white">
            {report.label || 'Top-ranked strategy deep dive'}
          </h3>
          <p className="mt-2 text-sm leading-relaxed text-slate-400">
            Think of this as a health check for the strategy — not just “did it make money?”, but
            “how painful was it, how lucky might those results be, and what should you change before
            risking real money?”
          </p>
        </div>
        <div className="rounded-lg border border-slate-700/60 bg-slate-900/80 px-4 py-3 text-right">
          <p className="text-[11px] uppercase tracking-wider text-slate-500">Overall score</p>
          <p className={`text-2xl font-bold ${scoreColor}`}>
            {typeof score === 'number' ? `${score.toFixed(1)}/10` : '—'}
          </p>
          <p className="mt-1 max-w-xs text-xs leading-relaxed text-slate-400">{a.verdict || ''}</p>
        </div>
      </div>

      {/* Assessment first — what users care about most */}
      <Section
        title="What this means for you — strengths, risks & how to improve"
        plainEnglish="Start here. These bullets are written from the numbers below: what worked, what is dangerous, and concrete changes that usually improve results."
      >
        <div className="grid gap-3 lg:grid-cols-3">
          <AdviceList
            title="Good points (keep doing this)"
            items={a.good || []}
            empty="No clear strengths yet — gather more trades and re-run."
            tone="good"
          />
          <AdviceList
            title="Bad points / risks (do not ignore)"
            items={a.bad || []}
            empty="No major red flags in this window."
            tone="bad"
          />
          <AdviceList
            title="How to improve the strategy"
            items={a.improve || []}
            empty="Keep collecting trades and re-check after the next run."
            tone="improve"
          />
        </div>
      </Section>

      <Section
        title="1. Does it make money? (core performance)"
        plainEnglish="These numbers answer: if you had followed the rules, would you have grown the account, how often were you right, and was the average trade worth taking after costs?"
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Metric
            label="Yearly growth (CAGR)"
            value={fmt(core.cagr_pct as number, 2, '%')}
            plain="If results continued at this pace, roughly how much the account would grow per year. Lets you compare a 6-month test to a 5-year test fairly."
          />
          <Metric
            label="How often you were right (win rate)"
            value={fmt(core.win_rate_pct as number, 1, '%')}
            plain="Percent of trades that made money. A low win rate is fine if winners are much bigger than losers."
          />
          <Metric
            label="Win size vs loss size (payoff)"
            value={core.payoff_ratio != null ? `${fmt(Number(core.payoff_ratio), 2)}:1` : '—'}
            plain="Average winning trade ÷ average losing trade. Example: 3:1 means winners are about 3× larger than losers."
          />
          <Metric
            label="Money made vs money lost (profit factor)"
            value={String(pfDisplay)}
            plain="Total profits ÷ total losses. Below 1 = losing system. About 1.5–3 is healthy. Above 4 often means the test looked too perfect (curve-fitted)."
          />
          <Metric
            label="Average result per trade (expectancy)"
            value={fmt(core.expectancy_pct as number, 3, '%')}
            plain="On a typical trade, how much you expect to gain or lose after costs. Positive = edge; zero/negative = no edge."
          />
          <Metric
            label="Total return over the test"
            value={fmt(core.total_return_pct as number, 2, '%')}
            plain="Overall % change in the account for this backtest window (not annualized)."
          />
          <Metric
            label="Typical winning trade"
            value={fmt(core.avg_win_pct as number, 2, '%')}
            plain="Average size of a winning trade."
          />
          <Metric
            label="Typical losing trade"
            value={fmt(core.avg_loss_pct as number, 2, '%')}
            plain="Average size of a losing trade (usually negative)."
          />
        </div>
      </Section>

      <Section
        title="2. How painful was it? (risk & drawdowns)"
        plainEnglish="Profit on paper does not matter if the account dips so deep (or stays underwater so long) that you would have quit. This section measures the worst ‘stomach ache’ the strategy produced."
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Metric
            label="Worst drop from a peak (max drawdown)"
            value={fmt(risk.max_drawdown_pct as number, 2, '%')}
            plain="Biggest fall from a high point to a low point. A 40% drawdown means watching nearly half the account disappear before recovery."
          />
          <Metric
            label="How long you stayed underwater"
            value={risk.max_drawdown_duration_trades != null ? `${risk.max_drawdown_duration_trades} trades` : '—'}
            plain="Longest stretch of trades before the account made a new high again. Long recoveries are hard to stick with live."
          />
          <Metric
            label="Longest losing streak"
            value={risk.max_consecutive_losses != null ? String(risk.max_consecutive_losses) : '—'}
            plain="Most losses in a row. Size your risk so you can survive that streak without panic."
          />
          <Metric
            label="How bumpy the ride was (volatility)"
            value={fmt(risk.annual_volatility_pct as number, 1, '%')}
            plain="How much results swung around. Higher = choppier equity curve."
          />
        </div>
      </Section>

      <Section
        title="3. Was the return worth the stress? (risk-adjusted)"
        plainEnglish="Two strategies can make the same money — but one with wild ups and downs is worse. These ratios ask: how much reward did you get for each unit of risk / pain?"
      >
        <div className="grid gap-3 sm:grid-cols-3">
          <Metric
            label="Sharpe ratio"
            value={fmt(adj.sharpe_ratio as number, 2)}
            plain="Return compared with overall ups-and-downs. Rough guide: above 1 is okay; above 2 is strong."
          />
          <Metric
            label="Sortino ratio"
            value={fmt(adj.sortino_ratio as number, 2)}
            plain="Like Sharpe, but only punishes downside moves. Fairer for strategies that trend with big upside swings."
          />
          <Metric
            label="Calmar ratio"
            value={fmt(adj.calmar_ratio as number, 2)}
            plain="Yearly growth ÷ worst drawdown. Around 3 or higher is excellent — good return without crushing DD."
          />
        </div>
      </Section>

      <Section
        title="4. Did we include real-world friction? (costs & slippage)"
        plainEnglish="A backtest is fake if it ignores broker fees, taxes, and getting a slightly worse price than the chart shows. We dock every trade by a small cost so the result is closer to live trading."
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <Metric
            label="Cost taken off each round-trip"
            value={costs.costs_bps != null ? `${fmt(costs.costs_bps, 1)} bps` : '—'}
            plain={
              costs.slippage_note
              || 'This stands in for commission + slippage. If you trade often, raise this number and re-test — high-frequency ideas often die once fees are realistic.'
            }
          />
          <Metric
            label="How many trades we studied"
            value={core.num_trades != null ? String(core.num_trades) : '—'}
            plain={
              core.years_analyzed != null
                ? `About ${fmt(Number(core.years_analyzed), 2)} years of history. More trades = more trustworthy conclusions.`
                : 'More trades usually means you can trust the conclusion more.'
            }
          />
        </div>
      </Section>

      <Section
        title="5. Was it skill or luck? (robustness checks)"
        plainEnglish="A strategy can look great only because it was tuned to past charts. These tests ask: does it still work on ‘unseen’ trades, and what if the order of wins/losses had been unlucky?"
      >
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-3">
            <p className="text-xs font-medium uppercase tracking-wider text-slate-400">
              Practice half vs exam half (out-of-sample)
            </p>
            <p className="mt-1 text-[11px] leading-relaxed text-slate-500">
              We use the first ~70% of trades as the “study” period and the last ~30% as a blind test.
              If the blind half collapses, the strategy may have been fitted to old data.
            </p>
            {oos.available ? (
              <div className="mt-3 space-y-2 text-sm text-slate-300">
                <p>
                  Study period ({oos.in_sample_trades} trades): return {fmt(oos.in_sample?.total_return_pct, 2, '%')} ·
                  profit factor {fmt(oos.in_sample?.profit_factor, 2)}
                </p>
                <p>
                  Blind period ({oos.out_of_sample_trades} trades): return {fmt(oos.out_of_sample?.total_return_pct, 2, '%')} ·
                  profit factor {fmt(oos.out_of_sample?.profit_factor, 2)}
                </p>
                <p className={oos.looks_robust ? 'font-medium text-teal-400' : 'font-medium text-amber-400'}>
                  {oos.looks_robust
                    ? 'Good sign: the blind period still looked okay vs the study period.'
                    : 'Warning: the blind period was much weaker — treat this as a possible curve-fit.'}
                </p>
              </div>
            ) : (
              <p className="mt-3 text-sm text-slate-500">{String(oos.note || 'Need more trades before we can split the sample.')}</p>
            )}
          </div>

          <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 p-3">
            <p className="text-xs font-medium uppercase tracking-wider text-slate-400">
              Shuffle the trade order (Monte Carlo)
            </p>
            <p className="mt-1 text-[11px] leading-relaxed text-slate-500">
              We randomly reshuffle the same wins and losses hundreds of times. That shows how bad a
              losing streak could get just from unlucky timing — even if the average edge stays the same.
            </p>
            {mc.runs ? (
              <div className="mt-3 space-y-1.5 text-sm text-slate-300">
                <p>Ran {mc.runs} random reshuffles</p>
                <p>Typical ending return (median): {fmt(mc.median_final_return_pct as number, 2, '%')}</p>
                <p>
                  Unlucky → lucky return range: {fmt(mc.p5_final_return_pct as number, 1, '%')} to{' '}
                  {fmt(mc.p95_final_return_pct as number, 1, '%')}
                </p>
                <p>
                  Typical worst drop: {fmt(mc.median_max_drawdown_pct as number, 1, '%')} · very unlucky drop:{' '}
                  {fmt(mc.p5_max_drawdown_pct as number, 1, '%')}
                </p>
                <p>
                  Chance of finishing profitable: {fmt(mc.probability_profit_pct as number, 0, '%')} · chance of
                  ending below half the starting account: {fmt(mc.probability_half_equity_pct as number, 1, '%')}
                </p>
              </div>
            ) : (
              <p className="mt-3 text-sm text-slate-500">{String(mc.note || 'Need more trades for this stress test.')}</p>
            )}
          </div>
        </div>
      </Section>

      <p className="border-t border-slate-800/60 pt-3 text-[11px] leading-relaxed text-slate-500">
        Reminder: a backtest is a simulation on past data. Use the Good / Bad / Improve lists above to
        decide whether to paper-trade next — not as a promise of future profits.
      </p>
    </div>
  )
}
