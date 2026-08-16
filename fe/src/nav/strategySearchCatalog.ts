import { appNav } from './appNav'

export type StrategySearchItem = {
  id: string
  label: string
  to: string
  group: string
  keywords: string
  kind: 'page' | 'tool' | 'rule'
}

/** Deep strategy / tool links not fully listed as sidebar children. */
const EXTRA_TOOLS: Array<{ label: string; to: string; group: string; keywords?: string }> = [
  // Command Center tabs
  { label: 'Tomorrow Outlook', to: '/command-center?tab=tomorrow_outlook', group: 'Command Center' },
  { label: 'Ticker Investigation', to: '/command-center?tab=investigation', group: 'Command Center' },
  { label: 'Global Market Mood', to: '/command-center?tab=global_market_mood', group: 'Command Center' },
  { label: 'Momentum Scanner', to: '/command-center?tab=momentum', group: 'Command Center' },
  { label: 'EMA Position', to: '/command-center?tab=ema_position', group: 'Command Center' },
  { label: 'MTF Trend and Strength', to: '/command-center?tab=mtf_trend_strength', group: 'Command Center' },
  { label: 'Market Movers', to: '/command-center?tab=market_movers', group: 'Command Center' },
  { label: 'Divergences', to: '/command-center?tab=divergences', group: 'Command Center' },
  { label: 'Candlestick & Chart Patterns', to: '/command-center?tab=candlestick_chart_patterns', group: 'Command Center', keywords: 'candle pattern' },
  { label: 'Stoploss Hunting', to: '/command-center?tab=stop_hunt', group: 'Command Center' },
  { label: 'Take Profit Targets', to: '/command-center?tab=take_profit', group: 'Command Center' },
  { label: 'Real Bottom', to: '/command-center?tab=real_bottom', group: 'Command Center' },
  { label: 'Weak / Strong', to: '/command-center?tab=weak_strong', group: 'Command Center' },
  { label: '200SMA-20SMA Bounce & Rejection', to: '/command-center?tab=sma_20_200', group: 'Command Center', keywords: 'sma bounce' },
  { label: 'Copy Trade', to: '/command-center?tab=copy_trade', group: 'Command Center' },
  { label: 'Take Trade', to: '/command-center?tab=take_trade', group: 'Command Center' },
  { label: 'Trade Setup Oversold/Overbought', to: '/command-center?tab=trade_setup', group: 'Command Center', keywords: 'rsi' },
  { label: 'One-Click Intraday', to: '/command-center?tab=one_click_intraday', group: 'Command Center' },
  { label: 'One-Click Scalping', to: '/command-center?tab=one_click_scalping', group: 'Command Center' },
  { label: 'One-Click Swing', to: '/command-center?tab=one_click_swing', group: 'Command Center' },
  { label: 'Fundamental Analysis', to: '/command-center?tab=fundamental_analysis', group: 'Command Center' },
  { label: 'India FII-DII Holding', to: '/command-center?tab=india_fii_dii_holdings', group: 'Command Center' },
  { label: 'Mutual Fund Holdings', to: '/command-center?tab=mutual_fund_holdings', group: 'Command Center' },
  { label: 'ETF Holdings', to: '/command-center?tab=etf_holdings', group: 'Command Center' },
  { label: 'Check Smart Money Activity', to: '/command-center?tab=smart_money_activity', group: 'Command Center' },
  { label: 'Detect Sector Rotation', to: '/command-center?tab=detect_sector_rotation', group: 'Command Center' },
  { label: 'Upgrade/Downgrade', to: '/command-center?tab=stock_upgrade_downgrade', group: 'Command Center' },
  { label: 'Investigate + Strategy', to: '/command-center?tab=investigation_strategies', group: 'Command Center' },
  { label: 'Mega Setup Advisor', to: '/command-center?tab=mega_setup_advisor', group: 'Command Center' },
  { label: 'Option-Short-Long', to: '/command-center?tab=option_short_long', group: 'Command Center', keywords: 'oi buildup call put' },
  { label: 'IN-US-Crypto Market Heatmap', to: '/command-center?tab=india_market_heatmap', group: 'Command Center' },
  { label: 'NSE and World Indices', to: '/command-center?tab=nse_world_indices', group: 'Command Center' },
  { label: '24Hrs Volatile Crypto', to: '/command-center?tab=coindcx_24h_volatility', group: 'Command Center' },
  { label: 'Quick Analyzer', to: '/command-center?tab=quick_analyzer', group: 'Command Center' },

  // Options desks
  { label: 'Double Calendar', to: '/options?section=double_calendar', group: 'Options' },
  { label: 'Delta Neutral', to: '/options?section=delta_neutral', group: 'Options' },
  { label: 'Hedging', to: '/options?section=hedging', group: 'Options' },
  { label: 'Gokul Chhabra 3m ITM', to: '/options?section=gokul_chhabra', group: 'Options' },
  { label: 'Zero to Hero', to: '/options?section=zero_to_hero', group: 'Options' },
  { label: 'Market Prediction', to: '/options?section=market_prediction', group: 'Options' },
  { label: 'Call Put Writing', to: '/options?section=call_put_writing', group: 'Options' },
  { label: 'Profitable Overnight Buy-Stop', to: '/options?section=profitable', group: 'Options' },

  // Trading hubs (common)
  { label: 'Scalping Hub', to: '/trading-hubs?hub=scalping', group: 'Trading Hubs' },
  { label: 'Swing Hub', to: '/trading-hubs?hub=swing', group: 'Trading Hubs' },
  { label: 'Smart Money Hub', to: '/trading-hubs?hub=smart_money', group: 'Trading Hubs', keywords: 'smc' },
  { label: 'SMC Golden Bullet', to: '/trading-hubs?hub=smart_money&section=smc_golden_bullet', group: 'Trading Hubs' },
  { label: 'Scalp Gold', to: '/trading-hubs?hub=scalping&section=scalp_gold', group: 'Trading Hubs' },

  // Technical Analysis common tabs
  { label: 'TOPDOWN-MTF', to: '/technical-analysis?tab=topdown_mtf', group: 'Technical Analysis' },
  { label: 'MTF Hedging', to: '/technical-analysis?tab=mtf_hedging', group: 'Technical Analysis' },
  { label: 'MTF Scanner', to: '/technical-analysis?tab=mtf_scanner', group: 'Technical Analysis' },
  { label: 'Weak Strong S-R', to: '/technical-analysis?tab=weak_strong_sr', group: 'Technical Analysis' },
  { label: 'SMC Fake Market Shift', to: '/technical-analysis?tab=smc_fake_market_shift', group: 'Technical Analysis' },
  { label: 'Sentiment Screener', to: '/technical-analysis?tab=sentiment_screener', group: 'Technical Analysis' },
  { label: 'Big Whale', to: '/technical-analysis?tab=big_whale', group: 'Technical Analysis' },

  // Prediction
  { label: 'Falling Knife History', to: '/prediction/falling-knife', group: 'Prediction', keywords: 'dump pump recovery forecast from top peak drawdown reverse runup descent momentum' },

  // Pro Trade deep keywords
  { label: '9 EMA Vol RSI Scalp', to: '/pro-trade/ema9-vol-rsi-momentum', group: 'Pro Trade', keywords: 'ema9 volume rsi momentum scalp 5m 15m structure score' },

  // Crypto Trading
  { label: 'Multibagger Reversal', to: '/crypto-trading/multibagger-reversal', group: 'Crypto Trading', keywords: 'crypto multibagger short ema280 ema300 supertrend 40% 24h fade' },
  { label: 'Advance BB Reversal', to: '/crypto-trading/advance-bb-reversal', group: 'Crypto Trading', keywords: 'bollinger band reversal 30m pierce inside short long support resistance 80%' },
  { label: 'EMA Crossover', to: '/crypto-trading/ema-crossover', group: 'Crypto Trading', keywords: 'ema crossover btc eth sol xrp bnb 30m 1h 4h preset sl tp' },
  { label: 'SuperTrend', to: '/crypto-trading/supertrend', group: 'Crypto Trading', keywords: 'supertrend s2 archit atr factor green red flip btc eth sol xrp 1h' },

  // Market Pulse common
  { label: 'Market Pulse Intelligence', to: '/market-pulse?section=intelligence', group: 'Market Pulse' },
  { label: 'Tomorrow Outlook (Pulse)', to: '/market-pulse?section=tomorrow_outlook', group: 'Market Pulse' },
  { label: 'Commodity Screener', to: '/market-pulse?section=commodity_screener', group: 'Market Pulse' },
  { label: 'Nifty Breadth', to: '/market-pulse?section=nifty_breadth', group: 'Market Pulse' },
  { label: 'Sector Rotation', to: '/market-pulse?section=sector_rotation', group: 'Market Pulse' },
  { label: 'Big Whale Pump Dump', to: '/market-pulse?section=big_whale_pump_dump', group: 'Market Pulse' },
]

function tokenize(...parts: Array<string | undefined | null>): string {
  return parts
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
    .replace(/[^a-z0-9+.#\s-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function flattenNav(): StrategySearchItem[] {
  const items: StrategySearchItem[] = []
  const seen = new Set<string>()

  const push = (item: StrategySearchItem) => {
    if (seen.has(item.to)) return
    seen.add(item.to)
    items.push(item)
  }

  for (const entry of appNav) {
    if (entry.children?.length) {
      for (const child of entry.children) {
        push({
          id: `nav:${child.to}`,
          label: child.label,
          to: child.to,
          group: entry.label,
          keywords: tokenize(child.label, entry.label, child.to),
          kind: 'page',
        })
      }
    } else {
      push({
        id: `nav:${entry.to}`,
        label: entry.label,
        to: entry.to,
        group: 'App',
        keywords: tokenize(entry.label, entry.shortLabel, entry.to),
        kind: 'page',
      })
    }
  }

  for (const extra of EXTRA_TOOLS) {
    push({
      id: `tool:${extra.to}`,
      label: extra.label,
      to: extra.to,
      group: extra.group,
      keywords: tokenize(extra.label, extra.group, extra.keywords, extra.to),
      kind: 'tool',
    })
  }

  return items
}

/** Static catalog (nav + deep tool links). Rule strategies are merged at runtime. */
export const STATIC_STRATEGY_SEARCH_CATALOG: StrategySearchItem[] = flattenNav()

export function ruleStrategiesToSearchItems(
  strategies: Array<{ id: string; name: string; category?: string; category_label?: string; summary?: string }>,
): StrategySearchItem[] {
  return strategies.map((s) => ({
    id: `rule:${s.id}`,
    label: s.name,
    to: `/strategies/${s.id}`,
    group: s.category_label || s.category || 'Rule strategies',
    keywords: tokenize(s.name, s.category, s.category_label, s.summary, s.id),
    kind: 'rule' as const,
  }))
}

export function filterStrategySearch(
  items: StrategySearchItem[],
  query: string,
  limit = 40,
): StrategySearchItem[] {
  const q = query.trim().toLowerCase()
  if (!q) {
    return items.slice(0, limit)
  }
  const tokens = q.split(/\s+/).filter(Boolean)

  const scored = items
    .map((item) => {
      const hay = `${item.label} ${item.group} ${item.keywords} ${item.to}`.toLowerCase()
      let score = 0
      for (const t of tokens) {
        if (item.label.toLowerCase().startsWith(t)) score += 40
        else if (item.label.toLowerCase().includes(t)) score += 24
        else if (item.group.toLowerCase().includes(t)) score += 12
        else if (hay.includes(t)) score += 8
        else return null
      }
      // Prefer shorter / exact-ish labels
      score += Math.max(0, 20 - item.label.length / 4)
      if (item.kind === 'rule') score += 2
      return { item, score }
    })
    .filter((x): x is { item: StrategySearchItem; score: number } => x != null)

  scored.sort((a, b) => b.score - a.score || a.item.label.localeCompare(b.item.label))
  return scored.slice(0, limit).map((x) => x.item)
}
