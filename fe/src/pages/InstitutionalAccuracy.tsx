import { Link, Navigate, useParams } from 'react-router-dom'
import { ArrowRight, Landmark, Sparkles, Crosshair, Clock, FlaskConical } from 'lucide-react'
import { PageHeader } from '../components/ui/PageHeader'
import { Card } from '../components/ui/Card'
import { CollapsibleGuide as CollapsibleSection } from '../components/ui/CopyAllButton'

export type InstMarketId = 'india' | 'us' | 'crypto' | 'commodities'

type Setup = {
  title: string
  why: string
  howTo: string[]
  status: 'available' | 'partial' | 'planned'
  links?: { label: string; to: string }[]
}

type MarketDef = {
  id: InstMarketId
  title: string
  subtitle: string
  thesis: string
  icon: typeof Landmark
  setups: Setup[]
}

/** Cross-asset upgrades shown on every market page */
const QUANT_UPGRADES: Setup[] = [
  {
    title: 'Regime-Switching Models (Hidden Markov)',
    why:
      'A static “trend vs range” filter is too blunt. An HMM estimates the probability the market has flipped from low-vol trend into high-vol chop — and can auto-disable mean-reversion or breakout bots accordingly.',
    howTo: [
      'Define observable features (returns, realized vol, A/D or CVD slope, range expansion).',
      'Fit a 2–3 state Hidden Markov Model on rolling history; label states (e.g. Trend / Chop / Shock).',
      'Gate strategies: only run breakouts in Trend, mean-reversion in Chop, flat or hedges in Shock.',
      'In this app today: use Oil·Dollar·Bond + Advance Decline / Comparative Strength as a manual regime read until HMM automation is wired.',
      'Log false regime flips — recalibrate transition priors when vol clustering changes.',
    ],
    status: 'partial',
    links: [
      { label: 'Oil · Dollar · Bond', to: '/command-center?tab=oil_dollar_bond' },
      { label: 'Advance Decline', to: '/command-center?tab=advance_decline_graph' },
    ],
  },
  {
    title: 'Dynamic Volatility Sizing (GARCH / clustering)',
    why:
      'Static 1–2% risk ignores variance clustering. Forecast tomorrow’s vol and shrink size when variance expands — institutional default.',
    howTo: [
      'Estimate tomorrow’s σ via GARCH(1,1) or EWMA on the underlying’s returns.',
      'Position size ∝ (risk budget) / (stop distance × forecast σ) — not a flat % of equity.',
      'Widen structural stops with ~0.5 ATR buffer on SMC sweeps; cut contracts when forecast vol spikes.',
      'In this app today: use ATR-based SL from Pro Trade / TA desks and manually reduce size on high-vol days (VIX / India VIX / crypto funding extremes).',
    ],
    status: 'partial',
    links: [
      { label: 'PA-VP-SMC', to: '/pro-trade/pa-vp-smc' },
      { label: 'Stoploss Hunting', to: '/command-center?tab=stop_hunt' },
    ],
  },
]

const EQUITY_SETUPS: Setup[] = [
  {
    title: 'Gamma Exposure (GEX) & Dealer Positioning',
    why:
      'Market makers hedge options books and often dictate index path. GEX maps magnetic pins and levels where dealers must aggressively buy or sell the underlying to stay delta-neutral.',
    howTo: [
      'Build / ingest a GEX surface by strike for Nifty / Bank Nifty (India) or SPX / QQQ / major single names (US).',
      'Mark positive-gamma “pin” zones (dealers dampen moves) vs negative-gamma zones (dealers amplify moves).',
      'Pair with Option Chain PCR / Max Pain and Call Put Writing walls — GEX explains *why* walls hold or cascade.',
      'Only fade hollow rallies when GEX says dealers will sell into strength; only chase breakouts when negative gamma forces covering.',
      'In this app today: Option Chain + Call Put Writing are the live proxies — treat GEX as the next data layer to add.',
    ],
    status: 'partial',
    links: [
      { label: 'Option Chain', to: '/command-center?tab=option_chain' },
      { label: 'Call Put Writing', to: '/options?section=call_put_writing' },
      { label: 'Market Prediction', to: '/options?section=market_prediction' },
    ],
  },
  {
    title: 'Market By Order (MBO) & Dark Pool Prints',
    why:
      'OHLCV volume profiles miss off-exchange absorption. Level 3 MBO + dark-pool blocks show where institutional limit orders rest — stopping you from buying fake retail breakouts into hidden sell liquidity.',
    howTo: [
      'Integrate MBO / Level 3 where available (or broker footprint) — watch resting bid/ask size changes, not just trades.',
      'Overlay dark-pool / block prints on your Volume Profile CE / POC levels.',
      'If price breaks a retail HVN but dark prints show heavy sell absorption, stand aside or fade — do not chase.',
      'Use Smart Money Activity / MF·ETF flow desks as a *coarse* institutional footprint until true MBO feeds are connected.',
      'Execution rule: PA-VP-SMC entry only when VP + visible flow agree; cancel if MBO shows opposite absorption.',
    ],
    status: 'partial',
    links: [
      { label: 'Volume Profile CE', to: '/pro-trade/volume-profile-ce' },
      { label: 'Volume Profile POC', to: '/pro-trade/volume-profile-poc' },
      { label: 'PA-VP-SMC', to: '/pro-trade/pa-vp-smc' },
      { label: 'Smart Money Activity', to: '/command-center?tab=smart_money_activity' },
    ],
  },
  {
    title: 'Earnings Surprise & Text Sentiment (NLP)',
    why:
      'For swings, NLP on earnings calls and filings often precedes re-ratings better than static P/E. Quantified executive tone is a leading structural input.',
    howTo: [
      'Wire NLP over earnings transcripts + SEC filings / India exchange filings (or news APIs with sentiment scores).',
      'Score surprise vs consensus and tone delta vs prior call — not just “beat/miss”.',
      'Only add swing risk when Comparative Strength / Top-Down MTF already agree and sentiment is confirmatory.',
      'Avoid initiating into binary events without defined hedge (MTF Hedging / options).',
      'In this app today: Upgrade/Downgrade + Fundamental Analysis are partial substitutes — full transcript NLP is the upgrade path.',
    ],
    status: 'planned',
    links: [
      { label: 'Upgrade / Downgrade', to: '/command-center?tab=stock_upgrade_downgrade' },
      { label: 'Fundamental Analysis', to: '/command-center?tab=fundamental_analysis' },
      { label: 'Comparative Strength', to: '/command-center?tab=comparative_strength' },
    ],
  },
]

export const INST_MARKETS: MarketDef[] = [
  {
    id: 'india',
    title: 'India — Institutional Accuracy',
    subtitle: 'Liquidity · dealer gamma · F&O hedging edge',
    thesis:
      'True institutional accuracy on NSE/BSE means leaving reactive candles behind: dealer GEX, hidden liquidity, and event sentiment on top of breadth + options walls you already run.',
    icon: Landmark,
    setups: [
      ...EQUITY_SETUPS.map((s) =>
        s.title.startsWith('Gamma')
          ? {
              ...s,
              howTo: [
                'Prioritize Nifty / Bank Nifty GEX by strike around weekly & monthly expiry.',
                ...s.howTo.slice(1),
                'Combine with Advance Decline: hollow Nifty green + negative A/D + dealers in negative gamma = fade candidate.',
              ],
              links: [
                ...(s.links || []),
                { label: 'Advance Decline', to: '/command-center?tab=advance_decline_graph' },
              ],
            }
          : s,
      ),
    ],
  },
  {
    id: 'us',
    title: 'US — Institutional Accuracy',
    subtitle: 'Dealer gamma · dark pools · earnings NLP',
    thesis:
      'US equities are algo-efficient. Precision comes from dealer positioning, off-exchange liquidity, and quantified event sentiment — then execute only on Top-Down MTF structure.',
    icon: Sparkles,
    setups: [
      ...EQUITY_SETUPS.map((s) =>
        s.title.startsWith('Gamma')
          ? {
              ...s,
              howTo: [
                'Prioritize SPX / QQQ / mega-cap single-name GEX into OPEX and CPI / FOMC weeks.',
                ...s.howTo.slice(1),
                'Pair with Oil · Dollar · Bond: Risk-Off + negative gamma = expect faster downside cascades.',
              ],
              links: [
                ...(s.links || []),
                { label: 'Oil · Dollar · Bond', to: '/command-center?tab=oil_dollar_bond' },
                { label: 'TOPDOWN-MTF', to: '/technical-analysis?tab=topdown_mtf' },
              ],
            }
          : s,
      ),
    ],
  },
  {
    id: 'crypto',
    title: 'Crypto — Institutional Accuracy',
    subtitle: 'On-chain · CVD · liquidations · funding',
    thesis:
      'Crypto is a 24/7 liquidation machine. Institutional precision needs aggressive vs passive flow (CVD), liquidation heatmaps, and funding — not RSI alone.',
    icon: Crosshair,
    setups: [
      {
        title: 'Cumulative Volume Delta (CVD) Divergences',
        why:
          'Tick-level aggressive buy vs passive absorption. Price new high + CVD lower high = limit sellers absorbing retail — elite reversal tell.',
        howTo: [
          'Stream real tick Bid/Ask aggressor data (not OHLCV proxies) into a CVD series per symbol.',
          'Flag divergence: price HH + CVD LH (distribution) or price LL + CVD HL (absorption / possible long).',
          'Only take Golden Bullet / Fake Market Shift shorts when CVD divergence confirms the sweep was retail-driven.',
          'In this app today: Volume Spread Next Candle + PA-VP-SMC approximate effort vs result — upgrade to true CVD when tick feed is live.',
        ],
        status: 'partial',
        links: [
          { label: 'Volume Spread — Next Candle', to: '/pro-trade/volume-spread-next-candle' },
          { label: 'PA-VP-SMC', to: '/pro-trade/pa-vp-smc' },
          { label: 'SMC Fake Market Shift', to: '/technical-analysis?tab=smc_fake_market_shift' },
        ],
      },
      {
        title: 'Liquidation Heatmaps',
        why:
          'Crypto moves on forced liquidations. Map where leveraged retail stops cluster — execute Golden Bullet sweeps only when those zones are hit.',
        howTo: [
          'Ingest exchange liquidation / leverage heatmap APIs (major perps venues).',
          'Mark dense long-liq and short-liq pools above/below Asian range.',
          'Rule: no Golden Bullet entry until price wicks into a mapped liq cluster and CVD/ reclaim confirms.',
          'Skip “sweeps” that never touch a real leverage pocket — those are often noise.',
          'In this app today: 24Hrs Volatile Crypto + Golden Bullet timing are the workflow shell; heatmap feed is the precision layer to add.',
        ],
        status: 'planned',
        links: [
          { label: 'Golden Bullet', to: '/trading-hubs?hub=smart_money&section=smc_golden_bullet' },
          { label: '24Hrs Volatile Crypto', to: '/command-center?tab=coindcx_24h_volatility' },
        ],
      },
      {
        title: 'Funding Rate Arbitrage',
        why:
          'When retail is aggressively long, funding spikes. Short extreme positive-funding tokens vs buy spot (or relative underweights) for mean-reversion + yield.',
        howTo: [
          'Pull perpetual funding + OI by token; rank extreme positive / negative funding.',
          'For sector rotation: underweight / short alts with sky-high positive funding that also lag BTC; prefer leaders with neutral/negative funding.',
          'Collect funding while fading crowded side only when Crypto Price Rotation vs BTC agrees.',
          'Cap size when funding flips violently — crowding can squeeze harder than the yield pays.',
        ],
        status: 'planned',
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
    title: 'Commodities — Institutional Accuracy',
    subtitle: 'Curve · real yields · CoT z-scores',
    thesis:
      'Commodities are physical + yield markets. Spot charts without term structure, real yields, and speculative positioning are incomplete.',
    icon: Clock,
    setups: [
      {
        title: 'Forward Curve Term Structure',
        why:
          'Oil, gas, and ags cannot be traded on spot alone. Contango vs backwardation encodes physical S/D and roll yield in real time.',
        howTo: [
          'Pull the full futures curve (front → deferred) for the contract you trade.',
          'Contango (upward): typically comfortable supply / negative roll for longs — favor mean-reversion or shorts into spikes.',
          'Backwardation (downward): tightness / positive roll for longs — favor trend-following with HTF walls.',
          'Only take Scalping Gold / energy ideas when curve regime matches the directional thesis.',
          'In this app today: Commodity Screener + Oil·Dollar·Bond give direction context; full curve panel is the add-on.',
        ],
        status: 'partial',
        links: [
          { label: 'Commodity Screener', to: '/market-pulse?section=commodity_screener' },
          { label: 'Oil · Dollar · Bond', to: '/command-center?tab=oil_dollar_bond' },
          { label: 'Scalping — Gold', to: '/trading-hubs?hub=scalping&section=scalp_gold' },
        ],
      },
      {
        title: 'Real Yield Differentials',
        why:
          'Capital chases the highest real (inflation-adjusted) sovereign yield — that flow drives DXY and Gold more than narratives.',
        howTo: [
          'Feed real yield spreads (e.g. US TIPS yields vs peers) into the macro tape beside DXY and nominal 10Y.',
          'Rising US real yields → headwind for Gold; falling real yields → Gold-friendly, often softer DXY.',
          'Gate commodity longs/shorts: no Gold long while real yields are aggressively breaking out without a hedge plan.',
          'Oil · Dollar · Bond is the mandatory live dashboard until a dedicated real-yield strip is added.',
        ],
        status: 'partial',
        links: [
          { label: 'Oil · Dollar · Bond', to: '/command-center?tab=oil_dollar_bond' },
        ],
      },
      {
        title: 'Commitments of Traders (CoT) Z-Scores',
        why:
          'Raw CoT is noisy. Normalize Commercial vs Managed Money net positioning with a rolling 3-year Z-score to flag mathematical extremes at macro turns.',
        howTo: [
          'Ingest weekly CoT for the commodity; compute net Commercial and Managed Money series.',
          'Z-score each series on a ~3-year rolling window. Trade extremes (e.g. |Z| > 2) as fade/continuation filters — not standalone signals.',
          'Example: Managed Money extremely long (high +Z) into HTF supply + Risk-Off tape → prefer shorts / take profit on longs.',
          'Combine with Weak Strong S-R walls and Scalping Gold confirmation — CoT times the regime, structure times the entry.',
        ],
        status: 'planned',
        links: [
          { label: 'Weak Strong S-R', to: '/technical-analysis?tab=weak_strong_sr' },
          { label: 'Scalping — Gold', to: '/trading-hubs?hub=scalping&section=scalp_gold' },
          { label: 'Oil · Dollar · Bond', to: '/command-center?tab=oil_dollar_bond' },
        ],
      },
    ],
  },
]

function statusBadge(status: Setup['status']) {
  if (status === 'available') return { label: 'In app', className: 'bg-emerald-500/15 text-emerald-300' }
  if (status === 'partial') return { label: 'Partial · upgrade path', className: 'bg-amber-500/15 text-amber-200' }
  return { label: 'Data layer to add', className: 'bg-slate-700/50 text-slate-400' }
}

function copyAll(m: MarketDef): string {
  const lines = [m.title, m.subtitle, '', m.thesis, '', 'Advanced setups:', '']
  for (const s of [...m.setups, ...QUANT_UPGRADES]) {
    lines.push(`## ${s.title} [${s.status}]`)
    lines.push(s.why)
    lines.push('How to:')
    for (const h of s.howTo) lines.push(`- ${h}`)
    if (s.links?.length) lines.push('Tools: ' + s.links.map((l) => `${l.label} (${l.to})`).join(' · '))
    lines.push('')
  }
  return lines.join('\n')
}

function SetupCard({ setup }: { setup: Setup }) {
  const badge = statusBadge(setup.status)
  return (
    <Card>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-white">{setup.title}</h3>
        <span className={`rounded-md px-1.5 py-0.5 text-[10px] font-medium ${badge.className}`}>{badge.label}</span>
      </div>
      <p className="text-sm text-slate-300">{setup.why}</p>
      <div className="mt-3 rounded-xl border border-slate-800/80 bg-slate-950/40 p-3">
        <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">How to</p>
        <ol className="list-decimal space-y-1.5 pl-4 text-xs leading-relaxed text-slate-400">
          {setup.howTo.map((h) => (
            <li key={h}>{h}</li>
          ))}
        </ol>
      </div>
      {setup.links && setup.links.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {setup.links.map((l) => (
            <Link
              key={l.to + l.label}
              to={l.to}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700/80 bg-slate-900/60 px-3 py-1.5 text-xs font-medium text-violet-200/90 hover:border-violet-500/40 hover:bg-violet-500/10"
            >
              {l.label}
              <ArrowRight size={12} />
            </Link>
          ))}
        </div>
      )}
    </Card>
  )
}

function MarketView({ market }: { market: MarketDef }) {
  const Icon = market.icon
  const text = copyAll(market)

  return (
    <div>
      <PageHeader title={market.title} description={market.subtitle} />

      <Card className="mb-4">
        <div className="flex flex-wrap items-start gap-3">
          <div className="rounded-xl bg-slate-800/60 p-3 text-violet-300">
            <Icon size={22} />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-slate-200">Precision thesis</p>
            <p className="mt-1 text-sm leading-relaxed text-slate-400">{market.thesis}</p>
          </div>
        </div>
        <div className="mt-3">
          <CollapsibleSection title="Copy all setups + quant upgrades" copyText={text} defaultOpen={false}>
            <pre className="whitespace-pre-wrap text-xs leading-relaxed text-slate-400">{text}</pre>
          </CollapsibleSection>
        </div>
      </Card>

      <div className="mb-3 flex flex-wrap gap-2">
        {INST_MARKETS.map((m) => (
          <Link
            key={m.id}
            to={`/institutional-accuracy/${m.id}`}
            className={`rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
              m.id === market.id
                ? 'bg-violet-500/20 text-violet-200'
                : 'bg-slate-800/60 text-slate-400 hover:bg-slate-800 hover:text-slate-200'
            }`}
          >
            {m.id === 'india' ? 'India' : m.id === 'us' ? 'US' : m.id === 'crypto' ? 'Crypto' : 'Commodities'}
          </Link>
        ))}
      </div>

      <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-violet-200/80">
        Asset-class precision layers
      </p>
      <div className="space-y-4">
        {market.setups.map((s) => (
          <SetupCard key={s.title} setup={s} />
        ))}
      </div>

      <div className="mt-6 mb-3 flex items-center gap-2">
        <FlaskConical size={16} className="text-sky-300" />
        <p className="text-xs font-semibold uppercase tracking-wide text-sky-200/80">
          Quantitative upgrades (cross-asset)
        </p>
      </div>
      <div className="space-y-4">
        {QUANT_UPGRADES.map((s) => (
          <SetupCard key={s.title} setup={s} />
        ))}
      </div>

      <p className="mt-4 text-[11px] text-slate-600">
        Research / education only — not financial advice. Badges mark what is live in-app vs data layers still to integrate.
      </p>
    </div>
  )
}

export default function InstitutionalAccuracyPage() {
  const { market } = useParams<{ market?: string }>()
  if (!market) return <Navigate to="/institutional-accuracy/india" replace />
  const def = INST_MARKETS.find((m) => m.id === market)
  if (!def) return <Navigate to="/institutional-accuracy/india" replace />
  return <MarketView market={def} />
}
