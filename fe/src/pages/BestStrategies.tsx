import { Link, Navigate, useParams } from 'react-router-dom'
import { ArrowRight, Landmark, Sparkles, Crosshair, Clock, Wrench } from 'lucide-react'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { CollapsibleGuide as CollapsibleSection } from '../components/ui/CopyAllButton'

export type BestMarketId = 'india' | 'us' | 'crypto' | 'commodities'

type StrategyCard = {
  title: string
  why: string
  howTo: string[]
  links: { label: string; to: string }[]
}

type MarketDef = {
  id: BestMarketId
  title: string
  subtitle: string
  thesis: string
  icon: typeof Landmark
  strategies: StrategyCard[]
}

const PRO_CALIBRATIONS = {
  title: 'Pro-Level Calibrations — institutional grade',
  intro:
    'Take these desks from advanced retail to institutional grade by adjusting execution, not by adding more indicators.',
  items: [
    {
      title: 'Replace proxies with real order flow (Level 2/3)',
      body:
        'Footprint / volume-delta in many OHLCV tools are approximations. For highest accuracy, integrate tick-level Bid/Ask delta to see whether buyers are trapped at resistance or sellers are being passively absorbed.',
    },
    {
      title: 'Dynamic risk / volatility sizing',
      body:
        'Stop using fixed 1:2 or 1:3 R:R as gospel. Pros use volatility-adjusted sizing (VaR-style): place stops off ATR of the underlying, and shrink position size as volatility expands.',
    },
    {
      title: 'Incorporate macro & funding rates',
      body:
        'Crypto: add perpetual funding rates and OI sweeps. US / India: overlay central-bank liquidity (repo, balance-sheet expansion) to decide mean-reversion vs trend-following regimes.',
    },
    {
      title: 'Avoid fixed time stops on sweeps',
      body:
        'In SMC, if you buy a liquidity sweep (CISD), do not park a hard stop exactly at the wick low — algos often double-sweep it. Place the stop at structural invalidation below the sweep zone, buffered by ~0.5 ATR.',
    },
  ],
}

export const BEST_MARKETS: MarketDef[] = [
  {
    id: 'india',
    title: 'India — Equities & F&O (NSE/BSE)',
    subtitle: 'Institutional flows + retail options positioning',
    thesis:
      'Indian markets are heavily driven by institutional flows (FII/DII) and massive retail options positioning. Combine derivatives data with cash-market structure — never trade F&O on chart alone.',
    icon: Landmark,
    strategies: [
      {
        title: 'Advance Decline + Option Chain (PCR / Max Pain)',
        why:
          'Institutional edge relies on breadth. If Nifty is up but A/D is negative and PCR is bearish, it is a hollow rally — fading that is a pro trade.',
        howTo: [
          'Run Command Center → Advance Decline (Multi Asset) for India. Confirm whether advances/volume support the index move.',
          'Open Option Chain on Nifty. Read PCR(OI), Max Pain, and Call/Put OI walls.',
          'Hollow rally: index green + weak A/D + Call-writing / bearish PCR skew → fade strength or stay flat; do not chase breakouts into Call walls.',
          'Healthy trend: strong A/D + Put floors / supportive PCR → allow longs on pullbacks with PA-VP confirmation.',
        ],
        links: [
          { label: 'Advance Decline', to: '/command-center?tab=advance_decline_graph' },
          { label: 'Option Chain', to: '/command-center?tab=option_chain' },
          { label: 'Call Put Writing', to: '/options?section=call_put_writing' },
        ],
      },
      {
        title: 'Pro Trade — Volume Profile CE / POC & PA-VP-SMC',
        why:
          'Institutions care where volume was transacted, not a moving-average average. HVN breakouts and first retests of POC are elite entries.',
        howTo: [
          'Scan Pro Trade → Volume Profile CE for VA reversal / POC compression / LVN setups.',
          'Use Volume Profile POC for first-touch HVN pullbacks.',
          'Confirm with PA-VP-SMC confluence (price action + VP + smart money pillars) before sizing.',
          'Enter on acceptance/rejection at HVN/POC — not mid-value FOMO.',
        ],
        links: [
          { label: 'Volume Profile CE', to: '/pro-trade/volume-profile-ce' },
          { label: 'Volume Profile POC', to: '/pro-trade/volume-profile-poc' },
          { label: 'PA-VP-SMC', to: '/pro-trade/pa-vp-smc' },
        ],
      },
      {
        title: 'Opposite Hedge-MTF (Beta-Neutral)',
        why:
          'True institutional long/short equity: buy the strongest sector / name and short the weakest to strip market beta.',
        howTo: [
          'Open Market Pulse → Opposite Hedge-MTF.',
          'Identify leader vs laggard pairs on the MTF stack.',
          'Long strongest, short weakest with similar beta / notional so net market risk is reduced.',
          'Rebalance if relative strength flips or index regime changes violently.',
        ],
        links: [
          { label: 'Opposite Hedge-MTF', to: '/market-pulse?section=opposite_hedge' },
          { label: 'Detect Sector Rotation', to: '/command-center?tab=detect_sector_rotation' },
        ],
      },
    ],
  },
  {
    id: 'us',
    title: 'US — Equities',
    subtitle: 'Algo-efficient · sector rotation · macro',
    thesis:
      'US markets are heavily algo-dominated, highly efficient, and driven by sector rotation plus macro (yields, DXY). Edge comes from relative strength and waiting for structure — not midday noise.',
    icon: Sparkles,
    strategies: [
      {
        title: 'Comparative Strength (Base SPY / QQQ)',
        why:
          'Alpha generation 101. If the S&P is dropping but a name consolidates (relative strength), buy when the index finds a floor.',
        howTo: [
          'Open Comparative Strength. Set base to SPY (or QQQ for tech book).',
          'Rank 1w / 1m relative strength. Prefer names holding up while the base pulls back.',
          'Wait for index / base to stabilize (floor), then enter the RS leader — not mid-waterfall.',
          'Confirm with Top-Down MTF so you are not buying into a broken daily structure.',
        ],
        links: [
          { label: 'Comparative Strength', to: '/command-center?tab=comparative_strength' },
          { label: 'Oil · Dollar · Bond', to: '/command-center?tab=oil_dollar_bond' },
        ],
      },
      {
        title: 'Detect Sector Rotation (CRS / Hull)',
        why:
          'Catching capital flow from Tech → Cyclicals / Defensives is how real wealth compounds in US markets.',
        howTo: [
          'Run Detect Sector Rotation with US universe / CRS · Hull settings.',
          'Identify which groups are receiving vs losing capital on your horizon.',
          'Align Comparative Strength picks with the rotating sector — do not fight the flow.',
          'Re-check Oil · Dollar · Bond for Risk-On / Risk-Off confirmation.',
        ],
        links: [
          { label: 'Detect Sector Rotation', to: '/command-center?tab=detect_sector_rotation' },
          { label: 'Comparative Strength', to: '/command-center?tab=comparative_strength' },
        ],
      },
      {
        title: 'Top-Down MTF (Liquidity + OB)',
        why:
          'Daily structure → 1H order blocks → 15m MSS keeps you out of midday algorithmic chop.',
        howTo: [
          'Open Technical Analysis → TOPDOWN - MTF (Liquidity + OB).',
          'Map daily liquidity / structure first. Only then mark 1H order blocks.',
          'Wait for price to retrace into the OB; execute on 15m Market Structure Shift (MSS).',
          'Skip entries in the dead midday zone unless a clear MSS fires at your level.',
        ],
        links: [
          { label: 'TOPDOWN-MTF', to: '/technical-analysis?tab=topdown_mtf' },
          { label: 'MTF Hedging', to: '/technical-analysis?tab=mtf_hedging' },
        ],
      },
    ],
  },
  {
    id: 'crypto',
    title: 'Crypto — Perpetual Futures',
    subtitle: '24/7 liquidity hunting · BTC dominance',
    thesis:
      'Crypto is a 24/7 liquidity-hunting machine driven by liquidations, funding, and Bitcoin dominance. Standard indicators get destroyed — trade Kill Zones, FVGs, and alts relative to BTC.',
    icon: Crosshair,
    strategies: [
      {
        title: 'SMC — Golden Bullet (Kill Zones)',
        why:
          'Massive volatility around NY / London overlap. A V-shape liquidity sweep (stop hunt) then shift is the most reliable crypto edge.',
        howTo: [
          'Only trade London open / NY overlap Kill Zones.',
          'Run Trading Hubs → Smart Money → Golden Bullet. Mark Asian highs/lows.',
          'Wait for NY/London wick to sweep that liquidity, then reclaim (V-shape).',
          'Enter on the shift; stop beyond the sweep with ~0.5 ATR buffer (see calibrations).',
        ],
        links: [
          { label: 'Golden Bullet', to: '/trading-hubs?hub=smart_money&section=smc_golden_bullet' },
          { label: '24Hrs Volatile Crypto', to: '/command-center?tab=coindcx_24h_volatility' },
        ],
      },
      {
        title: 'Scalping — CRT-FVG (Candle Range Theory)',
        why:
          'Crypto respects Fair Value Gaps (imbalances) extremely well. Fading the sweep into an FVG is high-tier.',
        howTo: [
          'Open Trading Hubs → Scalping → CRT-FVG.',
          'Identify HTF sweep into an imbalance / FVG zone.',
          'Fade only after LTF confirmation inside the FVG — not the first wick alone.',
          'Target opposing range liquidity; size down when funding is extreme against you.',
        ],
        links: [
          { label: 'CRT-FVG', to: '/trading-hubs?hub=scalping&section=scalp_crt_fvg' },
          { label: 'SMC Fake Market Shift', to: '/technical-analysis?tab=smc_fake_market_shift' },
        ],
      },
      {
        title: 'Crypto Price Rotation (vs BTC)',
        why:
          'The only disciplined way to trade alts is relative to Bitcoin. Underperforming BTC = dead money.',
        howTo: [
          'Open Market Pulse → Crypto Price Rotation (vs BTC / sector rotation crypto).',
          'Only size alts that are outperforming BTC on your horizon.',
          'If an alt lags BTC while BTC trends, skip it — rotate capital into leaders or stay in BTC.',
          'Pair with 24Hrs Volatile Crypto so you are not trading empty books.',
        ],
        links: [
          { label: 'Crypto Price Rotation', to: '/market-pulse?section=stock_rotation_crypto' },
          { label: 'Crypto Sector Rotation', to: '/market-pulse?section=sector_rotation_crypto' },
          { label: '24Hrs Volatile Crypto', to: '/command-center?tab=coindcx_24h_volatility' },
        ],
      },
    ],
  },
  {
    id: 'commodities',
    title: 'Commodities — Oil, Gold, Silver',
    subtitle: 'Pure macro · HTF institutional walls',
    thesis:
      'Commodities are macro and supply/demand driven. They trend relentlessly and respect high-timeframe institutional levels — trade walls, not noise.',
    icon: Clock,
    strategies: [
      {
        title: 'Oil · Dollar · Bond (Macro Tape)',
        why:
          'You cannot trade Gold or Oil without watching DXY and US yields. This dashboard is mandatory context.',
        howTo: [
          'Open Oil · Dollar · Bond before any Gold/Oil/Silver idea.',
          'Map Risk-On vs Risk-Off: DXY, 2Y/10Y, Brent, metals, indices.',
          'Only take Gold/Oil direction that agrees with the macro tape (or fade with tiny size when fighting it).',
          'Re-check Commodity Screener for cross-metal / energy lean.',
        ],
        links: [
          { label: 'Oil · Dollar · Bond', to: '/command-center?tab=oil_dollar_bond' },
          { label: 'Commodity Screener', to: '/market-pulse?section=commodity_screener' },
        ],
      },
      {
        title: 'Scalping — Gold (Trading Geek 5-step)',
        why:
          'Gold respects liquidity sweeps heavily. 15m sweep → LTF MSS is how many prop desks approach XAU/USD.',
        howTo: [
          'Map HTF supply/demand with Weak Strong S-R (4H/1D, 3+ touches).',
          'Open Trading Hubs → Scalping → Scalping Gold.',
          'Wait for price into the HTF wall. No blind limit orders.',
          'Require 15m/5m liquidity sweep + displacement (FVG), then enter on pullback. Buffer stop ~0.5 ATR past invalidation.',
        ],
        links: [
          { label: 'Scalping — Gold', to: '/trading-hubs?hub=scalping&section=scalp_gold' },
          { label: 'Weak Strong S-R', to: '/technical-analysis?tab=weak_strong_sr' },
        ],
      },
    ],
  },
]

function copyMarket(m: MarketDef): string {
  const lines = [
    m.title,
    m.subtitle,
    '',
    m.thesis,
    '',
    'BEST Strategies:',
    '',
  ]
  for (const s of m.strategies) {
    lines.push(`## ${s.title}`)
    lines.push(s.why)
    lines.push('How to:')
    for (const h of s.howTo) lines.push(`- ${h}`)
    lines.push('Tools: ' + s.links.map((l) => `${l.label} (${l.to})`).join(' · '))
    lines.push('')
  }
  lines.push(PRO_CALIBRATIONS.title)
  lines.push(PRO_CALIBRATIONS.intro)
  for (const c of PRO_CALIBRATIONS.items) {
    lines.push(`### ${c.title}`)
    lines.push(c.body)
    lines.push('')
  }
  return lines.join('\n')
}

function BestMarketView({ market }: { market: MarketDef }) {
  const Icon = market.icon
  const copyAll = copyMarket(market)

  return (
    <div>
      <PageHeader title={market.title} description={market.subtitle} />

      <Card className="mb-4">
        <div className="flex flex-wrap items-start gap-3">
          <div className="rounded-xl bg-slate-800/60 p-3 text-amber-300">
            <Icon size={22} />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-slate-200">Market thesis</p>
            <p className="mt-1 text-sm leading-relaxed text-slate-400">{market.thesis}</p>
          </div>
        </div>
        <div className="mt-3">
          <CollapsibleSection title="Copy all (strategies + calibrations)" copyText={copyAll} defaultOpen={false}>
            <pre className="whitespace-pre-wrap text-xs leading-relaxed text-slate-400">{copyAll}</pre>
          </CollapsibleSection>
        </div>
      </Card>

      <div className="mb-3 flex flex-wrap gap-2">
        {BEST_MARKETS.map((m) => (
          <Link
            key={m.id}
            to={`/best-strategies/${m.id}`}
            className={`rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
              m.id === market.id
                ? 'bg-amber-500/20 text-amber-200'
                : 'bg-slate-800/60 text-slate-400 hover:bg-slate-800 hover:text-slate-200'
            }`}
          >
            {m.id === 'india' ? 'India' : m.id === 'us' ? 'US' : m.id === 'crypto' ? 'Crypto' : 'Commodities'}
          </Link>
        ))}
      </div>

      <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-amber-200/80">
        Best strategies
      </p>

      <div className="space-y-4">
        {market.strategies.map((s) => (
          <Card key={s.title}>
            <h3 className="text-sm font-semibold text-white">{s.title}</h3>
            <p className="mt-2 text-sm text-slate-300">{s.why}</p>
            <div className="mt-3 rounded-xl border border-slate-800/80 bg-slate-950/40 p-3">
              <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">How to</p>
              <ol className="list-decimal space-y-1.5 pl-4 text-xs leading-relaxed text-slate-400">
                {s.howTo.map((h) => (
                  <li key={h}>{h}</li>
                ))}
              </ol>
            </div>
            {s.links.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {s.links.map((l) => (
                  <Link
                    key={l.to + l.label}
                    to={l.to}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700/80 bg-slate-900/60 px-3 py-1.5 text-xs font-medium text-amber-200/90 hover:border-amber-500/40 hover:bg-amber-500/10"
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

      <Card className="mt-6">
        <div className="mb-3 flex items-center gap-2">
          <Wrench size={16} className="text-sky-300" />
          <h3 className="text-sm font-semibold text-white">{PRO_CALIBRATIONS.title}</h3>
        </div>
        <p className="mb-4 text-sm text-slate-400">{PRO_CALIBRATIONS.intro}</p>
        <div className="space-y-3">
          {PRO_CALIBRATIONS.items.map((c) => (
            <div key={c.title} className="rounded-xl border border-slate-800/70 bg-slate-950/50 p-3">
              <p className="text-xs font-semibold text-sky-200/90">{c.title}</p>
              <p className="mt-1.5 text-xs leading-relaxed text-slate-400">{c.body}</p>
            </div>
          ))}
        </div>
        <p className="mt-4 text-[11px] text-slate-600">
          Research / education only — not financial advice. Apply calibrations on top of the desks linked above.
        </p>
      </Card>
    </div>
  )
}

export default function BestStrategiesPage() {
  const { market } = useParams<{ market?: string }>()
  if (!market) return <Navigate to="/best-strategies/india" replace />
  const def = BEST_MARKETS.find((m) => m.id === market)
  if (!def) return <Navigate to="/best-strategies/india" replace />
  return <BestMarketView market={def} />
}
