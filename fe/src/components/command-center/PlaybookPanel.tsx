import { Card } from '../ui/Card'

/**
 * Static reference panel — no live data, no API calls. Maps which Command
 * Center sections to use for each trading style, what to screen/enter/stop/
 * target with, and what to leave alone. Content mirrors truebacktesting's
 * playbook_tab.py, adapted to reference only tools that actually exist in
 * this app's Command Center (its source lists ~55 sections; this app has a
 * smaller, focused set built around the composite engines below).
 */

const PRINCIPLES = [
  '**Agreement beats precision** — a TAKE needs several independent reads, not one indicator repeated.',
  '**Structure beats flat %** — price stops and targets off actual liquidity, not a round number.',
  '**Match the clock** — a scalp read on a swing name mis-prices risk, and vice versa.',
]

const RULES: [string, string][] = [
  ['On strictness',
    'Default to Strict / High-Quality everywhere. Only drop to Loose in a regime you can already see is strongly trending and can absorb more noise in.'],
  ['On a TAKE call',
    "It's a probability tilt, not a promise. Open the vote breakdown before sizing up — 4/11 agree and 8/11 agree are different trades wearing the same label."],
  ['On stops and targets',
    'Never use a flat percentage when Stoploss Hunting and Take Profit Targets are one click away — structure-anchored levels avoid both getting hunted and leaving money on the table.'],
  ['On position size',
    'Size inversely with holding-period risk: many small scalps, moderate intraday size, fewer but larger swing positions carrying wider stops.'],
  ['On AI View',
    'Use it as the narrative gut-check after the numbers, never before them. The confluence engines are the primary decision — AI View is the second opinion.'],
  ['On session timing',
    "Heed Stoploss Hunting's session-risk flag near the open/close. For scalping and intraday specifically, either skip new entries in that window or size down."],
]

type Style = {
  title: string
  period: string
  tf: string
  blocks: { label: string; tags: string[]; note?: string }[]
  workflow: string[]
}

const STYLES: Style[] = [
  {
    title: '🩳 Scalping',
    period: 'Minutes · in and out same session',
    tf: '1m – 15m',
    blocks: [
      { label: 'Screen', tags: ['NSE and World Indices → Load Futures', 'Quick Analyzer'],
        note: 'Read the pre-market futures/GIFT Nifty lean, then use Quick Analyzer to shortlist names already showing intraday conviction on the 1m–15m timeframes.' },
      { label: 'Primary engine', tags: ['One-Click Scalping'],
        note: 'HTF trend bias is a hard gate — no counter-trend scalps. Entry fires only when the independent engines it combines agree on the same zone.' },
      { label: 'Confirm before entry', tags: ['Trade Setup → Smart Money + Support/Resistance', 'Option Chain', 'Take Trade'],
        note: "Option Chain's PCR / max-pain read is most useful here for index scalps. Take Trade on your final 1–2 candidates is a fast independent second read." },
      { label: 'Stop-loss', tags: ['Stoploss Hunting'],
        note: 'Safe / Hunt-Resistant tier by default — a scalp’s stop sits closest to price of any style, which is exactly what gets swept.' },
      { label: 'Take-profit', tags: ['Take Profit Targets'],
        note: 'TP1 / Conservative only — book and move on, don’t hold a scalp for the extended target.' },
      { label: 'Leave alone', tags: ['Fundamental Analysis', 'Upgrade/Downgrade', 'Mega Setup Advisor (EOD-cadence)'] },
    ],
    workflow: [
      '**24Hrs Volatile Crypto** or **NSE and World Indices → Load Futures** — shortlist the actual movers.',
      '**One-Click Scalping**, Strict mode, run the shortlist.',
      'On any TAKE, open **Trade Setup**’s Smart Money + Support/Resistance checkboxes for the exact zone.',
      'Pull **Stoploss Hunting** + **Take Profit Targets** on the same ticker/timeframe.',
      'Skip it if hunt status reads **Active Sweep** against your direction.',
      'Enter on Safe SL / TP1.',
    ],
  },
  {
    title: '☀️ Intraday',
    period: 'Hours · closed by end of session',
    tf: '5m – 1h',
    blocks: [
      { label: 'Screen', tags: ['NSE and World Indices → Load Futures', 'Global Market Mood', 'Momentum Scanner'],
        note: 'Read US/Asia futures + GIFT Nifty before the open to set the day’s directional lean, then use Momentum Scanner to find names already trending or about to break out.' },
      { label: 'Primary engine', tags: ['One-Click Intraday'],
        note: 'A weighted multi-indicator MTF bias sets the master direction; the composite routes you into a breakout or fade setup depending on whether the regime is trending or ranging.' },
      { label: 'Confirm before entry', tags: ['Momentum Scanner', 'Divergences', 'Take Trade'],
        note: "Momentum's breakout-odds % catches names about to break out of a consolidation. Run Take Trade on your final 2–3 candidates as an independent cross-check — want 5+ of 11 analyses agreeing." },
      { label: 'Stop-loss', tags: ['Stoploss Hunting'], note: 'Safe tier as the default working stop for the day.' },
      { label: 'Take-profit', tags: ['Take Profit Targets'],
        note: 'TP1 for the core position; let a partial runner go to TP2 only on a confirmed trending regime.' },
      { label: 'Leave alone', tags: ['Fundamental Analysis', 'Upgrade/Downgrade'] },
    ],
    workflow: [
      '**NSE and World Indices → Load Futures** each morning before the open — read the overnight bias.',
      '**Momentum Scanner** — shortlist trending/consolidating candidates.',
      '**One-Click Intraday**, Strict mode, run the shortlist.',
      'On consolidating candidates, check **Momentum Scanner**’s breakout-odds %.',
      'Run **Take Trade** on the top 2–3 as a final gate.',
      'Enter on Safe SL / TP1, trail the remainder toward TP2 if the trend holds.',
    ],
  },
  {
    title: '🌙 Swing',
    period: 'Days to weeks · held through noise',
    tf: '4h – 1d – 1w',
    blocks: [
      { label: 'Screen', tags: ['Upgrade/Downgrade', 'Fundamental Analysis', 'Indian Market Heatmap'],
        note: 'Build a watchlist where analyst activity, a healthy fundamental read, or a sector already showing strength leans your way — corroborating evidence, not a timing trigger.' },
      { label: 'Primary engine', tags: ['One-Click Swing'],
        note: 'A higher-timeframe trend gate sets the bias; for India, a bearish Fundamental Analysis read directly downgrades or vetoes a technical LONG here — the only place a non-technical signal enters the vote.' },
      { label: 'Confirm before entry', tags: ['Fundamental Analysis', 'Investigate + Strategy', 'Mega Setup Advisor'],
        note: 'If Fundamentals actively agrees, size up; if neutral, size normal; never take one it contradicts — the composite already vetoes this, treat it as a hard rule.' },
      { label: 'Stop-loss', tags: ['Stoploss Hunting'],
        note: 'Safe tier at entry, then trail as the position moves into profit rather than a static distance.' },
      { label: 'Take-profit', tags: ['Take Profit Targets'],
        note: 'The holding period earns the TP2 / Extended target — book a partial at TP1, let the rest ride to TP2 or the trailing stop.' },
      { label: 'Leave alone', tags: ['Scalping-only setups', 'Session-timing / opening-range reads'] },
    ],
    workflow: [
      '**Upgrade/Downgrade** + **Fundamental Analysis** — build a watchlist with a fundamental tailwind.',
      '**One-Click Swing**, Strict mode, run the watchlist.',
      'On any TAKE, check **Fundamental Analysis** directly to set position size.',
      'Cross-check with **Investigate + Strategy** or **Mega Setup Advisor**.',
      'Enter on Safe SL; take partial profit at TP1, trail the rest.',
      'Re-run the composite as each new daily/weekly candle closes.',
    ],
  },
]

const CONTEXT_TOOLS: [string, string[], string][] = [
  ['🌍 Market backdrop (read before any style)',
    ['Global Market Mood', 'Mega Analyser', 'Buy or Sell', 'Ticker Investigation'],
    'Mega Analyser’s multi-engine ensemble and Take Trade both make good final cross-checks — use one, not both, and only after your primary engine already fired. Buy or Sell is a guided wrapper around the same read as Mega Analyser, not a separate opinion.'],
  ['🧭 Deeper due diligence',
    ['Investigate + Strategy', 'Mega Setup Advisor', 'Indian Market Heatmap'],
    'Use these to sanity-check a candidate that already passed your primary engine — they’re confirmation tools, not screens to start from.'],
]

function TagRow({ tags }: { tags: string[] }) {
  if (!tags.length) return null
  return (
    <p className="mt-1 flex flex-wrap gap-1.5">
      {tags.map((t, i) => (
        <span key={i} className="rounded-md bg-slate-800/80 px-1.5 py-0.5 font-mono text-[11px] text-slate-300">
          {t}
        </span>
      ))}
    </p>
  )
}

function mdBold(text: string) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g)
  return parts.map((p, i) =>
    p.startsWith('**') && p.endsWith('**') ? <strong key={i} className="text-slate-200">{p.slice(2, -2)}</strong> : <span key={i}>{p}</span>
  )
}

function StyleColumn({ style }: { style: Style }) {
  return (
    <div className="min-w-0">
      <h4 className="text-sm font-semibold text-white">{style.title}</h4>
      <p className="mt-0.5 text-xs text-slate-500">{style.period} · <span className="font-mono">{style.tf}</span></p>

      <div className="mt-3 space-y-3">
        {style.blocks.map((b, i) => (
          <div key={i}>
            <p className="text-xs font-semibold text-slate-300">{b.label}</p>
            <TagRow tags={b.tags} />
            {b.note && <p className="mt-1 text-xs text-slate-500">{b.note}</p>}
          </div>
        ))}
      </div>

      <div className="mt-4 border-t border-slate-800/60 pt-3">
        <p className="text-xs font-semibold text-slate-300">Workflow</p>
        <ol className="mt-1.5 space-y-1 text-xs text-slate-400">
          {style.workflow.map((step, i) => (
            <li key={i} className="flex gap-1.5">
              <span className="text-slate-600">{i + 1}.</span>
              <span>{mdBold(step)}</span>
            </li>
          ))}
        </ol>
      </div>
    </div>
  )
}

export function PlaybookPanel() {
  return (
    <div className="space-y-6">
      <Card>
        <p className="text-sm text-slate-400">
          A practical map of which Command Center sections to use for scalping, intraday, and swing
          trading — what to screen with, enter on, size and stop with, and what to leave alone.
        </p>
        <ul className="mt-3 space-y-1 text-sm text-slate-300">
          {PRINCIPLES.map((p, i) => (
            <li key={i} className="flex gap-2"><span className="text-slate-600">•</span><span>{mdBold(p)}</span></li>
          ))}
        </ul>
      </Card>

      <Card>
        <div className="grid gap-6 lg:grid-cols-3">
          {STYLES.map((s) => <StyleColumn key={s.title} style={s} />)}
        </div>
      </Card>

      <Card>
        <h3 className="text-sm font-semibold text-white">Beyond the three styles</h3>
        <p className="mt-1 text-xs text-slate-500">Tools that support every style rather than belonging to one.</p>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          {CONTEXT_TOOLS.map(([title, tags, note], i) => (
            <div key={i} className="rounded-xl border border-slate-800/80 bg-slate-900/40 p-4">
              <p className="text-sm font-semibold text-slate-200">{title}</p>
              <TagRow tags={tags} />
              <p className="mt-2 text-xs text-slate-500">{note}</p>
            </div>
          ))}
        </div>
      </Card>

      <Card>
        <h3 className="text-sm font-semibold text-white">Rules that hold across all three</h3>
        <p className="mt-1 text-xs text-slate-500">The sections change with the clock. These don't.</p>
        <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {RULES.map(([k, v], i) => (
            <div key={i} className="rounded-xl border border-slate-800/80 bg-slate-900/40 p-4">
              <p className="text-sm font-medium italic text-slate-300">{k}</p>
              <p className="mt-1.5 text-xs text-slate-500">{v}</p>
            </div>
          ))}
        </div>
      </Card>

      <p className="text-xs text-slate-600">
        Research / education reference only — not financial advice. Section names reflect this app's
        Command Center as of the last update.
      </p>
    </div>
  )
}
