import { Link, Navigate, useParams } from 'react-router-dom'
import { ArrowRight, Clock, Crosshair, Landmark, Sparkles } from 'lucide-react'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { CollapsibleGuide as CollapsibleSection } from '../components/ui/CopyAllButton'

export type WorkflowId = 'india' | 'us' | 'crypto' | 'commodities'

type Step = {
  title: string
  window?: string
  what: string
  howTo: string[]
  links: { label: string; to: string }[]
}

type WorkflowDef = {
  id: WorkflowId
  title: string
  subtitle: string
  objective: string
  style: string
  icon: typeof Landmark
  steps: Step[]
  notes: string[]
}

export const WORKFLOWS: WorkflowDef[] = [
  {
    id: 'india',
    title: 'India — Equities (F&O / Intraday)',
    subtitle: 'Institutional options flow + volume structure',
    objective: 'Trade with institutional options flow and volume — not blind breakouts into Call walls.',
    style: 'Intraday · F&O · 5m / 15m',
    icon: Landmark,
    steps: [
      {
        title: '1. Macro / Breadth',
        window: '09:15 – 09:45 IST',
        what: 'Is the broader market participating? Where are Nifty Max Pain and Call/Put OI walls?',
        howTo: [
          'Open Advance Decline (Multi Asset) and set India. Confirm advances vs declines and volume breadth — thin breadth = fade chasey longs.',
          'Open Option Chain for Nifty. Note Max Pain, PCR(OI), and the heaviest Call / Put OI strikes (walls).',
          'If spot is pinned under a heavy Call wall with weak breadth, bias fades / waits — do not force breakouts.',
        ],
        links: [
          { label: 'Advance Decline', to: '/command-center?tab=advance_decline_graph' },
          { label: 'Option Chain', to: '/command-center?tab=option_chain' },
        ],
      },
      {
        title: '2. Sector Focus',
        window: '09:45 – 10:00 IST',
        what: 'Find the sector outperforming Nifty on the intraday rotation clock.',
        howTo: [
          'Run Detect Sector Rotation (intraday / short horizon) for India.',
          'Pick the sector(s) leading Nifty on relative strength — leaders, not laggards “catching up”.',
          'Write down 3–6 liquid F&O names in that sector for the next step.',
        ],
        links: [
          { label: 'Detect Sector Rotation', to: '/command-center?tab=detect_sector_rotation' },
        ],
      },
      {
        title: '3. Stock Selection · OI filter',
        what: 'Only trade liquid F&O names that are not sitting into a heavy Call writing wall.',
        howTo: [
          'For each candidate (or the index), open Call Put Writing.',
          'If primary Call wall is close overhead with fresh Call writing, skip buying into it — wait for wall break + covering or pick another name.',
          'Prefer names where Put floors support dips or writing tilt is not aggressively Call-dominant against your long.',
        ],
        links: [
          { label: 'Call Put Writing', to: '/options?section=call_put_writing' },
        ],
      },
      {
        title: '4. Execution · PA-VP-SMC',
        what: 'Enter on Volume Profile POC pullback + LTF structure shift — not mid-range FOMO.',
        howTo: [
          'Open Pro Trade → PA-VP-SMC on the shortlist (5m / 15m LTF).',
          'Mark the POC / value area. Wait for price to pull back into POC (or VA edge) in the direction of your bias.',
          'Enter only when 15m/5m structure shifts bullish (MSS / displacement) at that level. Use the desk SL%/TP% and confirm with chart.',
          'Optional: Volume Profile POC desk alone for first-touch HVN pullbacks.',
        ],
        links: [
          { label: 'PA-VP-SMC', to: '/pro-trade/pa-vp-smc' },
          { label: 'Volume Profile POC', to: '/pro-trade/volume-profile-poc' },
        ],
      },
    ],
    notes: [
      'Research / education only — not financial advice.',
      'Skip new risk near open auction chaos if Stoploss Hunting flags active sweeps against you.',
      'Index Option Chain walls matter even when trading single-stock F&O — they set the tape.',
    ],
  },
  {
    id: 'us',
    title: 'US — Equities (Swing / Pairs)',
    subtitle: 'Relative value alpha vs SPY',
    objective: 'Generate relative-value alpha — long strength vs SPY, hedge beta when size is large.',
    style: 'Swing · Pairs · Daily OB + 15m MSS',
    icon: Sparkles,
    steps: [
      {
        title: '1. Macro Filter',
        window: 'Pre-market (US)',
        what: 'Risk-On vs Risk-Off: Dollar, yields, oil tape.',
        howTo: [
          'Open Oil · Dollar · Bond on Command Center / Dashboard.',
          'Risk-On lean: DXY soft, yields easing, risk assets bid. Risk-Off: DXY up, yields up, defensives.',
          'Only force long RS longs when macro is not violently Risk-Off — or tighten size / prefer hedges.',
        ],
        links: [
          { label: 'Oil · Dollar · Bond', to: '/command-center?tab=oil_dollar_bond' },
        ],
      },
      {
        title: '2. Screening · Comparative Strength',
        what: 'Find names trending up on 1w / 1m while SPY pulls back (relative strength).',
        howTo: [
          'Open Comparative Strength. Set base ticker to SPY.',
          'Rank peers on 1w and 1m relative %. Prefer LONG leans with rising RS while SPY is soft.',
          'Shortlist 3–8 names — avoid illiquid microcaps for swing size.',
        ],
        links: [
          { label: 'Comparative Strength', to: '/command-center?tab=comparative_strength' },
        ],
      },
      {
        title: '3. Execution · Top-Down MTF',
        what: 'Daily order block → wait for retrace → 15m market structure shift (MSS).',
        howTo: [
          'Open Technical Analysis → TOPDOWN - MTF (Liquidity + OB) on the shortlist.',
          'Mark the daily order block / liquidity pool in the trade direction.',
          'Wait for price to retrace into that OB. Do not chase extension.',
          'Execute when 15m prints MSS (break of structure) with displacement. Stop beyond the OB / sweep extreme.',
        ],
        links: [
          { label: 'Technical Analysis (TOPDOWN-MTF)', to: '/technical-analysis?tab=topdown_mtf' },
        ],
      },
      {
        title: '4. Hedge · MTF Hedging',
        what: 'If directional risk is large, neutralize SPY beta with a weighted hedge.',
        howTo: [
          'Open Multi-Timeframe Hedging on Technical Analysis.',
          'Size a beta-weighted put (or short) on SPY against the long book so net beta is closer to flat.',
          'Rebalance if SPY RS or beta drifts after large moves.',
        ],
        links: [
          { label: 'MTF Hedging', to: '/technical-analysis?tab=mtf_hedging' },
        ],
      },
    ],
    notes: [
      'Relative strength can fail in broad washouts — macro step is not optional.',
      'Hedge cost eats edge on small size; use step 4 when notional risk is material.',
    ],
  },
  {
    id: 'crypto',
    title: 'Crypto — Scalp / Intraday',
    subtitle: 'Hunt retail liquidity in Kill Zones',
    objective: 'Hunt retail liquidity during high-volume sessions (London open / NY overlap).',
    style: 'Scalp · Kill Zones · 5m Fake Market Shift',
    icon: Crosshair,
    steps: [
      {
        title: '1. Timing · Kill Zones',
        what: 'Only trade London open or NY overlap — skip dead Asian mid-session drift unless your plan says otherwise.',
        howTo: [
          'Mark London open and NY session open / overlap on your clock (Kill Zones).',
          'No new scalps outside those windows unless volume is exceptional on 24h heatmap.',
        ],
        links: [
          { label: 'SMC Golden Bullet (hub)', to: '/trading-hubs?hub=smart_money&section=smc_golden_bullet' },
        ],
      },
      {
        title: '2. Screening · Volatile Crypto',
        what: 'Tokens with real volume and interest — ignore dead alts.',
        howTo: [
          'Open 24Hrs Volatile Crypto (Command Center).',
          'Pick names with elevated volume / volatility — skip thin books.',
          'Cross-check you can actually execute (CoinDCX / your venue liquidity).',
        ],
        links: [
          { label: '24Hrs Volatile Crypto', to: '/command-center?tab=coindcx_24h_volatility' },
        ],
      },
      {
        title: '3. Setup · Golden Bullet',
        what: 'Mark Asian session highs / lows as liquidity pools.',
        howTo: [
          'Run SMC — Golden Bullet on Trading Hubs (Smart Money).',
          'Mark Asian range high and low. That is the liquidity you expect NY to hunt.',
          'Bias: fade the sweep after reclaim — not the first wick blindly.',
        ],
        links: [
          { label: 'Golden Bullet', to: '/trading-hubs?hub=smart_money&section=smc_golden_bullet' },
        ],
      },
      {
        title: '4. Execution · Fake Market Shift',
        what: 'NY wick sweeps Asian high → 5m close back inside → short toward Asian lows.',
        howTo: [
          'Wait for NY session to wick (sweep) the Asian high.',
          'Wait for the 5m candle to close back inside the Asian range (Fake Market Shift / CISD-style reclaim).',
          'Enter short targeting Asian session lows. Stop above the sweep wick.',
          'Confirm with SMC Fake Market Shift screener on TA if you want a second engine read.',
        ],
        links: [
          { label: 'SMC Fake Market Shift', to: '/technical-analysis?tab=smc_fake_market_shift' },
          { label: 'Scalping hub', to: '/trading-hubs?hub=scalping' },
        ],
      },
    ],
    notes: [
      'Crypto moves fast — if the 5m does not reclaim, do not invent the short.',
      'Funding / weekend liquidity can invalidate textbook Kill Zone behavior.',
    ],
  },
  {
    id: 'commodities',
    title: 'Commodities — Gold / Oil',
    subtitle: 'HTF walls + confirmed reversal',
    objective: 'Trade HTF structural levels — only after liquidity sweep + displacement confirms the reversal.',
    style: 'Swing bias · 4H/1D zones · 15m/5m entry',
    icon: Clock,
    steps: [
      {
        title: '1. Context · Commodity Screener',
        what: 'Broader trend: Gold vs Silver divergence, oil complex lean, etc.',
        howTo: [
          'Open Market Pulse → Commodity Screener.',
          'Note trend / buy-sell lean for Gold, Silver, Crude and related indices.',
          'Only take Gold longs when context is not violently opposing (and vice versa for fades).',
        ],
        links: [
          { label: 'Commodity Screener', to: '/market-pulse?section=commodity_screener' },
        ],
      },
      {
        title: '2. Levels · Weak Strong S/R',
        what: 'Map 4H / 1D zones with 3+ touches — institutional walls only.',
        howTo: [
          'Open Technical Analysis → Weak Strong S-R on Gold (or Oil).',
          'Use 4h and 1d. Keep zones with 3+ touches; discard single-touch noise.',
          'Those walls are the only places you plan to engage.',
        ],
        links: [
          { label: 'Weak Strong S-R', to: '/technical-analysis?tab=weak_strong_sr' },
        ],
      },
      {
        title: '3. Execution · Scalping Gold',
        what: 'No limit orders into the zone — wait for sweep + FVG displacement, then pullback entry.',
        howTo: [
          'Open Trading Hubs → Scalping → Scalping Gold (Trading Geek).',
          'Wait for price to enter the HTF supply/demand wall you mapped.',
          'Do not park limits blindly. Wait for 15m/5m liquidity sweep and displacement (FVG) confirming institutional reversal.',
          'Enter on the pullback into the FVG / displacement origin. Stop beyond the sweep.',
        ],
        links: [
          { label: 'Scalping — Gold', to: '/trading-hubs?hub=scalping&section=scalp_gold' },
          { label: 'Oil · Dollar · Bond (macro)', to: '/command-center?tab=oil_dollar_bond' },
        ],
      },
    ],
    notes: [
      'Gold often reacts to DXY / real yields — peek Oil · Dollar · Bond before sizing.',
      'If displacement never prints, the “wall” may fail — standing aside is valid.',
    ],
  },
]

export function getWorkflow(id: string | undefined): WorkflowDef | undefined {
  return WORKFLOWS.find((w) => w.id === id)
}

function WorkflowCopyText(w: WorkflowDef): string {
  const lines = [
    w.title,
    w.subtitle,
    '',
    `Objective: ${w.objective}`,
    `Style: ${w.style}`,
    '',
  ]
  for (const s of w.steps) {
    lines.push(`## ${s.title}${s.window ? ` (${s.window})` : ''}`)
    lines.push(s.what)
    lines.push('How to:')
    for (const h of s.howTo) lines.push(`- ${h}`)
    if (s.links.length) {
      lines.push('Tools: ' + s.links.map((l) => `${l.label} (${l.to})`).join(' · '))
    }
    lines.push('')
  }
  lines.push('Notes:')
  for (const n of w.notes) lines.push(`- ${n}`)
  return lines.join('\n')
}

function WorkflowView({ workflow }: { workflow: WorkflowDef }) {
  const Icon = workflow.icon
  const copyAll = WorkflowCopyText(workflow)

  return (
    <div>
      <PageHeader
        title={workflow.title}
        description={`${workflow.subtitle} · ${workflow.style}`}
      />

      <Card className="mb-4">
        <div className="flex flex-wrap items-start gap-3">
          <div className="rounded-xl bg-slate-800/60 p-3 text-sky-300">
            <Icon size={22} />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-slate-200">Objective</p>
            <p className="mt-1 text-sm leading-relaxed text-slate-400">{workflow.objective}</p>
            <p className="mt-2 text-xs text-slate-500">{workflow.style}</p>
          </div>
        </div>
        <div className="mt-3">
          <CollapsibleSection title="Copy full workflow" copyText={copyAll} defaultOpen={false}>
            <pre className="whitespace-pre-wrap text-xs leading-relaxed text-slate-400">{copyAll}</pre>
          </CollapsibleSection>
        </div>
      </Card>

      <div className="mb-3 flex flex-wrap gap-2">
        {WORKFLOWS.map((w) => (
          <Link
            key={w.id}
            to={`/workflow/${w.id}`}
            className={`rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
              w.id === workflow.id
                ? 'bg-sky-500/20 text-sky-300'
                : 'bg-slate-800/60 text-slate-400 hover:bg-slate-800 hover:text-slate-200'
            }`}
          >
            {w.id === 'india' ? 'India' : w.id === 'us' ? 'US' : w.id === 'crypto' ? 'Crypto' : 'Commodities'}
          </Link>
        ))}
      </div>

      <div className="space-y-4">
        {workflow.steps.map((step) => (
          <Card key={step.title}>
            <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="text-sm font-semibold text-white">{step.title}</h3>
              {step.window ? (
                <span className="inline-flex items-center gap-1 text-[11px] text-amber-200/80">
                  <Clock size={12} /> {step.window}
                </span>
              ) : null}
            </div>
            <p className="text-sm text-slate-300">{step.what}</p>

            <div className="mt-3 rounded-xl border border-slate-800/80 bg-slate-950/40 p-3">
              <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                How to
              </p>
              <ol className="list-decimal space-y-1.5 pl-4 text-xs leading-relaxed text-slate-400">
                {step.howTo.map((h) => (
                  <li key={h}>{h}</li>
                ))}
              </ol>
            </div>

            {step.links.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {step.links.map((l) => (
                  <Link
                    key={l.to + l.label}
                    to={l.to}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700/80 bg-slate-900/60 px-3 py-1.5 text-xs font-medium text-sky-300 hover:border-sky-500/40 hover:bg-sky-500/10"
                  >
                    {l.label}
                    <ArrowRight size={12} />
                  </Link>
                ))}
              </div>
            )}
          </Card>
        ))}
      </div>

      <Card className="mt-4">
        <p className="text-xs font-medium text-slate-400">Notes</p>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-slate-500">
          {workflow.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      </Card>
    </div>
  )
}

export default function WorkflowPage() {
  const { market } = useParams<{ market?: string }>()
  if (!market) return <Navigate to="/workflow/india" replace />
  const workflow = getWorkflow(market)
  if (!workflow) return <Navigate to="/workflow/india" replace />
  return <WorkflowView workflow={workflow} />
}
