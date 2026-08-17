"""
strategy_encyclopedia_guide.py
------------------------------
Full application reference for the Strategy Encyclopedia tab:
hub map, workflows, when-to-use matrix, and every section explained.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from app.market_pulse.section_strategy_guides import SECTION_GUIDES

# Hub → (section_id, display title) — mirrors hub_tabs.py
HUB_SECTIONS: dict[str, list[tuple[str, str]]] = {
    "🚀 Command Center": [
        ("command_outlook", "Tomorrow & Today Market Outlook"),
        ("global_market_mood", "Global Market Mood — regions · sectors · geopolitics"),
        ("mega_analyser", "Mega Analyser — unified multi-engine scan"),
        ("buy_sell_advisor", "Buy or Sell — Crypto · India · US · Commodity"),
        ("ticker_investigation", "Ticker Investigation — Crypto · India · US · Commodity"),
        ("ticker_investigation_strategy", "Ticker Investigation — Select Strategy"),
        ("stock_upgrade_downgrade", "Stock Upgrade Downgrade — Block Deals · M&A · Analyst Calls"),
        ("momentum", "Momentum — Multi-Timeframe Strength & Direction"),
        ("trade_setup", "Trade Setup — Oversold/Overbought Screener"),
        ("time_series_strategy", "Time Series Trading Strategy — MA Crossover + Bollinger + Breakout"),
        ("divergences", "Divergences — Price vs RSI · Price vs Volume"),
        ("candlestick_chart_patterns", "Candlestick & Chart Patterns"),
        ("real_bottom", "Real Bottom — 5-Step Selling Exhaustion / Trap / Displacement"),
        ("weak_strong", "Weak / Strong — Relative Strength & Trend Classifier"),
        ("copy_trade", "Copy Trade — High-Beta / 3x Leveraged ETF Momentum Scalp"),
        ("stop_hunt", "Stop Loss Hunting"),
        ("take_profit", "Take Profit Targets"),
        ("take_trade", "Take Trade — All Trade Setup Analyses Combined"),
        ("playbook", "Trading Playbook — Scalping · Intraday · Swing"),
        ("sma_20_200", "200SMA-20SMA — Bounce & Rejection"),
        ("mutual_fund_holdings", "Mutual Fund Holdings — Stock-Level Trend Across Funds"),
        ("etf_holdings", "ETF Holdings — Stock-Level Trend Across Funds (India · US · Crypto)"),
        ("india_fii_dii_holdings", "India FII-DII Holding — Ownership · P&L · Valuation · Deals"),
        ("next_day_move", "Next Day Move — Smart Money vs Retail (India · US · Crypto)"),
        ("detect_sector_rotation", "Detect Sector Rotation — CRS · Hull · Pullback (India · US · Crypto)"),
        ("ema_position", "EMA Position — Crossovers, Status & Next S/R"),
        ("fundamental_analysis", "Fundamental Analysis — Valuation · Holdings · Profit & Revenue Trend (India)"),
        ("one_click_setup", "One-Click Trade Setup — Scalping · Intraday · Swing (Multi-Engine Confluence)"),
        ("one_click_intraday", "One-Click Intraday Setup"),
        ("one_click_scalping", "One-Click Scalping Setup"),
        ("one_click_swing", "One-Click Swing Setup"),
        ("mega_setup_advisor", "Mega Setup Advisor — multi-engine confluence pick"),
        ("todays_indian_tickers", "Today's Indian Tickers — Live Market Movers (Dhan.co)"),
        ("option_chain", "Option Chain — Bias, PCR & Trade Signal (NSE)"),
        ("option_short_long", "Option-Short-Long — OI Buildup · Premium/Discount · Buy/Sell Call/Put (NSE)"),
        ("quick_analyzer", "Quick Analyzer — Momentum + EMA + Technical Indicators (India)"),
        ("quick_analyzer_crypto", "Quick Analyzer Crypto — Momentum + EMA + Technical Indicators (CoinDCX)"),
        ("quick_analyzer_us", "Quick Analyzer US — Momentum + EMA + Technical Indicators (Yahoo)"),
        ("nse_world_indices", "NSE and World Indices"),
        ("india_market_heatmap", "IN-US-Crypto Market Heatmap — Index/Sector Constituent Heatmap"),
        ("advance_decline_graph", "Advance Decline (Multi Asset) — Breadth + Options PCR"),
        ("comparative_strength", "Comparative Strength — Relative Long/Short vs Base"),
        ("oil_dollar_bond", "Oil · Dollar · Bond — Macro + India sector ETFs"),
        ("mtf_trend_strength", "MTF Trend and Strength — Multi-TF Trend Stack"),
        ("market_movers", "Market Movers — Index Gainers/Losers · Multi-Asset"),
        ("smart_money_activity", "Check Smart Money Activity — Institutional Footprints"),
        ("coindcx_24h_volatility", "24Hrs Volatile Crypto — CoinDCX Futures Heatmap"),
    ],
    "📊 Market Pulse": [
        ("news_scanner", "News Scanner & Market Intelligence"),
        ("nifty_breadth", "Nifty Index Breadth"),
        ("nifty_monthly", "Nifty 1-Month Performance"),
        ("nifty_gainers_losers", "Nifty Gainers & Losers"),
        ("market_gainers_losers", "Gainers & Losers — Multi-Market"),
        ("stock_price_rotation", "Stock Price Rotation — index constituents"),
        ("stock_price_rotation_us", "US Stock Price Rotation"),
        ("stock_price_rotation_crypto", "Crypto Price Rotation — CoinDCX"),
        ("commodity_screener", "Commodity Screener — buy / sell · Nifty indices"),
        ("accurate_strategy", "Accurate Strategy — OB + FVG + S/R confluence"),
        ("pump_dump_breakout", "Pump/Dump Breakout — consolidation breakdown & breakout"),
        ("big_whale_pump_dump", "Big Whale Pump & Dump — DEX whale flow"),
        ("sector_rotation", "Sector Rotation — daily · weekly · monthly"),
        ("sector_rotation_intraday", "Sector Rotation — mins · hours · days"),
        ("sector_rotation_us", "Sector Rotation (US) — daily · weekly · monthly"),
        ("sector_rotation_us_intraday", "Sector Rotation (US) — mins · hours · days"),
        ("sector_rotation_crypto", "Sector Rotation (Crypto) — daily · weekly · monthly"),
        ("sector_rotation_crypto_intraday", "Sector Rotation (Crypto) — mins · hours · days"),
        ("opposite_hedge_mtf", "Opposite Hedge-MTF — long leader · short laggard"),
        ("mtf_intraday_bias", "MTF Intraday Bias — Equities"),
        ("mtf_intraday_bias_crypto", "MTF Intraday Bias — Crypto"),
        ("week52", "52-Week High & Low"),
        ("heatmap", "Live Heatmap"),
    ],
    "🔬 Technical Analysis": [
        ("price_action", "Price Action Screener"),
        ("pump_dump_predictor", "Pump & Dump Screener"),
        ("find_sr", "Find S/R Screener"),
        ("weak_strong_sr", "Weak Strong S-R"),
        ("pattern_breakout", "Pattern & Breakout Screener"),
        ("fakeout_4h", "5min – 4hrs Breakout (4H fakeout)"),
        ("fakeout_15m", "1min – 15min Breakout (15M fakeout)"),
        ("mtf_scanner", "Institutional MTF Scanner"),
        ("mtf_hedging", "Multi-Timeframe Hedging — Groww · US · Crypto"),
        ("top_down_mtf", "Top Down MTF (SMC)"),
        ("topdown_mtf", "TOPDOWN - MTF (Liquidity + OB)"),
        ("weekly_stoch_sweet_spot", "Weekly Stoch Sweet Spot"),
        ("kn_smart_rsi_mtf", "KN Smart DP SL + RSI MTF + VWMA"),
        ("velez_retracement", "Velez Retracement Scalping"),
        ("smart_wave_crypto", "Smart Wave Crypto (CoinDCX only)"),
        ("crypto_scalping", "Crypto Scalping — EMA · VWAP · RSI (CoinDCX)"),
        ("smc_fake_market_shift", "SMC Fake Market Shift — BOS · POI · sweep"),
        ("confluence_strategy", "Confluence Screener"),
        ("strategy_scheduler", "Strategy Scheduler Screener"),
        ("elliott_wave", "Elliott Wave Screener"),
        ("sentiment", "Trend & Sentiment Screener"),
        ("top_bottom", "Top/Bottom Screener"),
        ("smc_options", "SMC · Options Flow Screener"),
        ("bb_exposed", "BB Exposed — Free Bar + Squeeze"),
        ("breakout_mtf", "Breakout MTF — Multi-Period Daily Scanner"),
        ("one_ta", "ONE TA — Golden Zone Fib + EMA"),
        ("box_trading", "Box Trading — Prev-Day Range (TradingLab)"),
    ],
    "🇮🇳 ETF TA IN": [
        ("stf_shop", "ETF Shop 4.0 — 20 DMA · dynamic SIP · FIFO · 39 distinct ETFs"),
        ("etf_28_sma", "ETF 28 SMA Momentum — FIRE · 3.14% · averaging · FIFO/LIFO"),
        ("etf_top_down", "ETF Top Down — dual P&F RS (max 18) · Renko + D-Smart 10 · weekly"),
    ],
    "⚡ Strategy Lab": [
        ("strategy_builder", "Strategy Builder & Tester"),
        ("saved_strategies", "Saved Strategies Archive"),
        ("multi_combo", "Multi-Combo Scanner"),
        ("strategy_encyclopedia", "Strategy Encyclopedia (this page)"),
        ("ai_strategy_creator", "AI Strategy Creator"),
    ],
    "🔎 Screen & Scan": [
        ("screener", "Advanced Screener"),
        ("gap_scanner", "Gap Trading Scanner"),
    ],
    "📅 Seasonality": [
        ("seasonality", "Seasonality Analyzer"),
    ],
    "📈 Swing Trading": [
        ("swing_trading_st", "ST — Capitulation & Continuation Breakout"),
        ("swing_trading_st_mtf_mss", "ST — Weekly Fakeout + 15m MSS"),
        ("swing_trading_st_supertrend", "ST — SuperTrend + SMA 10 Swing & Pyramiding"),
        ("swing_trading_st_kiss", "ST — KISS Swing Systematic"),
        ("swing_trading_st_ha_ema", "ST — Daily HA Bias + 34 EMA Intraday"),
        ("swing_trading_st_simple_steal", "SW — Simple Steal · Little Rizzy Projection"),
        ("swing_trend_breakout", "Trend Following Breakout — index filter + 52w leaders"),
        ("swing_trend_velocity", "Trend Velocity — 50/250 MA + ROC scale-out"),
        ("swing_bb_vwap_reversal", "BB + VWAP Reversal"),
        ("swing_fire", "Swing - FIRE — ATH/VCP/IPO · 21 EMA trail · monthly ROC"),
    ],
    "⚡ Intraday": [
        ("intraday_alpha_945", "INTRA — 9:45 AM Alpha Scanner"),
        ("intraday_fib_945", "INTRA — 9:45 Fib 50% + 10 EMA"),
        ("intraday_vwap_fade", "INTRA — VWAP Fade Value Area Extremes"),
        ("intraday_mtf_breakout_retest", "INTRA — MTF Breakout & Retest (Daniel Holmes)"),
        ("intraday_7_wasted", "INTRA — 7+wasted · 5m OR Breakout & Retest"),
        ("intra_hwp", "INTRA — HWP · Two-Sided Gap Fill + 21 EMA"),
    ],
    "🎯 Scalping": [
        ("scalp_rectangle", "Scalp — 1m Rectangle Sniper Entry"),
        ("scalp_smc", "Scalp — SMC Rule of Three (OTE · FVG · OB · CRT)"),
        ("scalp_arc", "Scalp — ARC Method (Area · Range · Candle)"),
        ("scalp_sr_mss", "Scalp — A+ S/R Zone + 1m MSS (Joovier)"),
        ("scalp_a_plus", "Scalp A+ — Smart Money Traps (Waqar Asim)"),
        ("scalp_gold", "Scalping — Gold (The Trading Geek 5-step)"),
        ("scalp_multi_indicator", "Scalp — Multi Indicator (UT Bot · QQE · VAE)"),
        ("scalp_crt_fvg", "Scalp — CRT-FVG (Market Structure, Liquidity & CRT)"),
        ("scalp_livefree_fx", "Scalp — LiveFree FX 5m (HTF Bias · Sessions · London Sweep · BoS)"),
        ("scalp_heikin_ashi", "Scalp — Heikin Ashi (100 EMA Pullback + High-Volume Doji)"),
        ("scalp_2min", "Scalp — 2-Minute Momentum Burst"),
    ],
    "💰 Smart Money": [
        ("smc_cisd", "SMC — CISD Entry Rule (Golden Rule)"),
        ("smc_weekly_sweep_cisd", "SMC — Weekly Liquidity Sweep & CISD"),
        ("smc_mtf_day_plan", "SMC — MTF Day Plan (OB · FVG · CHoCH)"),
        ("smc_golden_bullet", "SMC — Golden Bullet (Liquidity + Timing)"),
        ("smc_liquidity", "SMC — Liquidity (Sweeps · Grabs · FVG)"),
        ("smc_ttg_sniper", "SM — TTG Sniper Entry (Sweep · Order Block · FVG)"),
        ("smb_snp", "SMB — SnP Fashionably Late (VWAP × 9 EMA)"),
        ("sc_fvg", "SC — FVG (Reversal at Key Levels + Fair Value Gap)"),
        ("smc_sc_best", "SMC — SC Best (Structure · Liquidity · Displacement)"),
        ("smc_lewiskelly", "SMC — Lewis Kelly (Kill Zone · Sweep · MSS)"),
    ],
    "📐 Pro Trade": [
        ("volume_profile_ce", "Volume Profile CE — VA reversal · POC compression · I-profile LVN"),
        ("volume_profile_poc", "Volume Profile POC — first-touch HVN pullback"),
        ("pa_volume_profile", "PA - Volume Profile — FVG + VP cluster · S/R flip"),
        ("pa_vp_smc", "PA-VP-SMC — Price Action + Volume Profile + Smart Money confluence"),
        ("volume_spread_next_candle", "Volume Spread - Next Candle — VSA Downthrust / Upthrust"),
        ("elliott_wave_pro", "Elliott Wave — impulse / corrective Pro Trade scanner"),
        ("fibonacci_pro", "Fibonacci Pro — golden-zone pullback · multi-strategy Fib"),
        ("bb_mean_reversion", "BB Mean Reversion — %B stretch · squeeze · S/R confluence"),
        ("bb_rsi_vol", "BB-RSI-VOL — Lower BB+RSI≤35+low vol Buy · Upper+RSI≥70+high vol Sell"),
        ("ema_cross", "EMA Cross — Lower BB+RSI<35 long · Upper BB+RSI>65 short · mid wait · 1000-bar phase"),
        ("ema9_bb_rsi_vol", "EMA Cross (legacy) — same as ema_cross"),
        ("ema5_bb_rsi_vol", "EMA Cross (legacy 5) — same as ema_cross"),
        ("ema5_9_crossover", "5/9 EMA Cross — EMA5×EMA9 crossover · price confirm · BB/RSI/Vol"),
        ("ema9_vol_rsi_momentum", "9 EMA Vol RSI Scalp — 5m score≥7 · 15m bias · vol SMA50 · structure SL · 1:2 RR"),
        ("flat_retest", "Flat Retest — post-flat break→retest hold / reject→break low→failed retest"),
        ("traffic_light_indicator", "Traffic Light Indicator — SMA 20/50/200 stack · next-morning buy/sell"),
        ("buy_low_sell_high", "Buy Low Sell High — 25 DL GTT ladder · avg+5% exit · no SL"),
        ("rlb_breakout", "RLB - Breakout — Rocket Launcher · 7 confirmations"),
        ("three_in_one_trade_system", "3-in-1 Trade System — DMA + CAR + Volume · +6.28%"),
        ("simple_effective", "Simple Effective — MA band + MACD hist-zone · 1:1–1.5 RRR"),
        ("btst", "Buy Today Sell Tomorrow — closing-strength BTST / STBT"),
        ("ticker_chart", "Ticker Chart — daily / intraday with S1/S2 · R1/R2"),
    ],
    "₿ Crypto Trading": [
        ("crypto_multibagger_reversal", "Multibagger Reversal — ≥40% 24h · 5m EMA280 + ST RED SHORT · −10% TP"),
        ("crypto_advance_bb_reversal", "Advance BB Reversal — 30m pierce→inside · opposite BB · ₹200/₹600 · ~80%"),
        ("crypto_ema_crossover", "EMA Crossover — per-coin TF/EMA/SL%/TP% · BTC ETH SOL XRP BNB"),
        ("crypto_supertrend", "SuperTrend — S2 Archit · GREEN/RED flip · per-coin ATR/factor · BTC ETH SOL XRP"),
    ],
    "🔥 MF FIRE": [
        ("mf_fire", "MF FIRE — 25× FI · 1% rule · equity MF accumulation"),
    ],
    "📉 Options": [
        ("double_calendar", "Double Calendar — dual-expiry premium capture"),
        ("delta_neutral", "Delta Neutral — volatility / premium strategies"),
        ("hedging", "Hedging — protective overlays · beta · pairs"),
        ("gokul_chhabra", "Gokul Chhabra — 3m VWAP · VWMA · SuperTrend ITM options"),
        ("zero_to_hero", "Zero to Hero — high-conviction options progression"),
        ("market_prediction", "Market Prediction — derivatives conviction vs hollow move"),
        ("call_put_writing", "Call Put Writing — OI walls · short covering"),
        ("profitable", "Profitable — Overnight options buy-stop (₹50–75 · +50% · overnight DNA)"),
    ],
    "📓 Demo Trading": [
        ("demo_india", "Demo Trading — India (Groww)"),
        ("demo_crypto", "Demo Trading — Crypto (CoinDCX)"),
    ],
    "🔔 Alerts": [
        ("alerts", "Strategy Alert Monitors"),
    ],
    "🔖 Watchlist": [
        ("watchlist", "Watchlist — Track Tickers · % Change Since Added"),
    ],
}

_OVERVIEW = """
### What is TrueBacktester?

TrueBacktester is an **all-in-one trading research platform** for **India (NSE/BSE via Groww)**, **US equities**,
**CoinDCX crypto futures**, and **commodities**.
It combines live market intelligence, **90+** technical screeners and hub sections, strategy backtesting, batch scanning,
paper trading, and alert monitors — with **Ask AI / AI View** on most Command Center and screener results.

### The main hubs (top tabs)

| Hub | Purpose | Start here if… |
|-----|---------|----------------|
| **Command Center** | Morning briefing + multi-engine scans + breadth/RS + options PCR + holdings/rotation + One-Click setups + heatmaps | Fast morning briefing, breadth check, or unified scan |
| **Market Pulse** | News, flows, breadth, rotation, gainers/losers, heatmaps | Macro context before picking trades |
| **Technical Analysis** | Live screeners — price action, patterns, SMC, fakeout, BB, breakout MTF, ONE TA, **TOPDOWN-MTF**, **Box Trading**, confluence | You have a setup type in mind |
| **ETF TA IN** | India NSE ETF systematic strategies (ETF Shop 4.0) | ETF rotation / SIP playbook |
| **Strategy Lab** | Build, backtest, batch-scan, AI-generate strategies + **Encyclopedia** (this page) | Test or create systematic rules |
| **Screen & Scan** | Rule-based universe scan + gap events | Filter hundreds of tickers by rules |
| **Seasonality** | Monthly historical edge patterns | Statistical seasonal confirmation |
| **Swing Trading** | ST capitulation, MSS, SuperTrend, KISS, HA+EMA | Multi-day swing on India / US / crypto |
| **Intraday** | 9:45 scanners, Fib bias, VWAP fade, MTF breakout-retest | Session-timed NSE / global intraday |
| **Scalping** | Rectangle sniper · SMC Rule of Three · ARC · A+ S/R MSS · CRT-FVG | High-frequency LTF entries |
| **Smart Money** | CISD, weekly sweep, MTF day plan, Golden Bullet, Liquidity, SMB SnP | Institutional liquidity models |
| **Pro Trade** | Volume Profile CE/POC · PA+VP · PA-VP-SMC · VSA · Elliott · Fib Pro · BB Mean Rev · BTST · **Ticker Chart** | Institutional VP / PA / VSA / charting |
| **Options** | Double Calendar · Delta Neutral · Hedging · Gokul Chhabra · Zero to Hero · **Market Prediction** · Call Put Writing · **Profitable** | F&O structures & derivatives conviction |
| **Demo Trading** | Paper portfolio (India + crypto) | Practice without real money |
| **Alerts** | Telegram/email when saved setups fire | Hands-off monitoring after research |
| **Watchlist** | Per-user, per-market saved tickers with live price & % change since added | Track a shortlist without re-scanning |
| **Trading Agent (TA)** | Technical Agent chat — pure Price Action (S/R · Volume · RSI · BB) | Ask what to buy/sell with %SL/%TP |
| **Investing Agent** | Fundamental Analyst chat (JWT) | Fundamentals / scorecards |

### Command Center highlights (recent)

| Section | What it adds |
|---------|----------------|
| **Advance Decline (Multi Asset)** | India / US / Crypto breadth (A/D + volume ratio + trend/strength/RSI). India F&O indices also attach live **options PCR / OI / max pain** |
| **Comparative Strength** | Rank peers vs a base index/ticker (relative % + LONG/SHORT leans + AI View) |
| **Oil · Dollar · Bond** | Macro tape: DXY · Brent · US 2Y/10Y · Gold/Silver · Nifty/Dow/Nasdaq · BTC/ETH with S/R + AI next-move (also on **Dashboard**) |
| **Option Chain / Option-Short-Long** | NSE PCR, max pain, OI walls, premium/discount buildup |
| **Detect Sector Rotation** | CRS · Hull · pullback across India / US / Crypto |
| **IN-US-Crypto Market Heatmap** | Constituent heat tiles for the chosen index universe |

### Universal UI patterns (every section)

1. **Open the hub tab** — each tool is a section/panel inside its hub.
2. **📖 Strategy Guide & Methodology** — at the top of many sections; read this first (same text as Encyclopedia).
3. **Asset / market selector** — India · US · Crypto · Commodity where supported.
4. **Run Scan / Plot / Analyze** — data is fetched on demand (heavy scans may run in the background).
5. **Ask AI / AI View** — at the bottom of results; uses your saved provider from **Manage → AI Settings**.
6. **AI View** — Generate a plain-English verdict (BUY / SELL / AVOID) with levels and invalidation.

### Manage → AI Settings (Ask AI · AI View)

| Provider | Notes |
|----------|-------|
| **Google Gemini** | Default cloud LLM |
| **Groq (LLaMA)** | Fast open models |
| **Claude (Azure)** | Anthropic Foundry on Azure (`/anthropic` endpoint) |
| **OpenAI (Azure)** | Azure AI Foundry (`…/openai/v1`). Deployments include **gpt-5.6-sol** (Responses API), **DeepSeek-V4-Flash** (chat.completions), **gpt-4o**, **o4-mini**, **gpt-4o-mini** |
| **Investing Agent** | Fundamental Analyst chat tools (JWT token) |
| **Trading Agent (TA)** | Technical Agent — pure Price Action desk (S/R · Volume · RSI · Bollinger Bands) |

Keys are stored in the app database (env fallbacks still work).

### Sidebar essentials

- **Login** — unlocks saved strategies, demo portfolio, alerts, watchlist.
- **Groww token** (optional) — faster direct NSE / options feed; falls back if absent.
- **AI provider keys** — set once in Manage; used by Ask AI / AI View across hubs.
"""

_WORKFLOWS = """
### Workflow 1 — Morning pre-market (India cash)

1. **Command Center → Tomorrow & Today Outlook** — gap risk, global cues, event calendar.
2. **Market Pulse → News Scanner** — click **Refresh Market Data**; read FII/DII, PCR, analyst calls.
3. **Sector Rotation + Heatmap** — which sectors lead/lag today.
4. **Detect Sector Rotation** — weekly CRS vs benchmark + Hull buy (video rotation framework).
4. **MTF Intraday Bias (Equities)** — session direction on your watchlist.
5. Pick a TA screener aligned with the bias (see *When to Use Which Strategy* below).

### Workflow 2 — Intraday scalp (India or crypto)

1. Confirm session bias: **MTF Intraday Bias** (equity or crypto section).
2. Run a **time-boxed screener** matching the session:
   - First 15M range → **Fakeout 15M**
   - Mid-day 4H range → **Fakeout 4H**
   - Ribbon + VWMA → **KN Smart RSI MTF**
   - Sharp retrace → **Velez Retracement**
3. Check **ENTRY_READY** phase tickers; open **AI View** for confirmation.
4. Log the idea in **Demo Trading** before going live.

### Workflow 3 — Swing / positional (days to weeks)

1. **Weekly Stoch Sweet Spot** or **MTF Scanner** on 4h/1d timeframes.
2. **Pattern & Breakout** or **Price Action** for entry levels and SL/TP.
3. **Seasonality** — confirm the current month has historical tailwind.
4. **Sentiment** multi-TF score ≥ +35 (long) or ≤ −35 (short) for confluence.

### Workflow 4 — Backtest & validate a strategy

1. **Strategy Encyclopedia → Preset Catalog** — pick a template → **Load into Builder**.
   *Or* **AI Strategy Creator** — describe strategy in plain English → parse to rules.
2. **Strategy Builder & Tester** — set ticker, timeframe, SL/TP %, date range → **Run Backtest**.
3. Review metrics: win rate, profit factor, max drawdown, equity curve.
4. **Save Strategy** (requires login) → appears in **Saved Strategies Archive**.
5. **Multi-Combo Scanner** — batch the saved strategy across many tickers × timeframes.
6. Compare results; keep only combos with consistent edge.

### Workflow 5 — Create a brand-new custom strategy

| Step | Section | Action |
|------|---------|--------|
| 1 | **AI Strategy Creator** | Paste transcript / rules; LLM outputs indicators + entry/exit JSON |
| 2 | **Strategy Builder** | Fine-tune indicators, rules, SL/TP; run backtest |
| 3 | **Saved Strategies** | Name and archive the version that backtests well |
| 4 | **Multi-Combo** | Scan universe; save promising ticker×TF combos |
| 5 | **Alerts** | Attach Telegram/email to saved combos for live polling |

### Workflow 6 — Crypto-only (CoinDCX)

1. Use **CoinDCX Futures** in market selector (not available on all sections).
2. **Smart Wave Crypto** — bootcamp EMA / SuperTrend / BB / Multi-Bagger rules.
3. **MTF Intraday Bias Crypto** — session day starts **00:00 New York (ET)**.
4. **Demo Trading → Crypto** — separate paper ledger from India.

### Workflow 7 — Options / F&O context (India)

1. **Command Center → Advance Decline (Multi Asset)** — pick **NIFTY 50** or **NIFTY BANK**; read breadth **and** the attached options PCR / max-pain snapshot.
2. **Command Center → Option Chain** — full nearest-expiry chain + Buy/Sell/Wait bias.
3. **Command Center → Option-Short-Long** — OI buildup · premium/discount · Buy/Sell Call/Put.
4. **Market Pulse → News Scanner** — PCR, max pain, OI walls in the market tape.
5. **SMC · Options Flow Screener** — delivery %, PCR, OI change + SMC structure.
6. **Options → Gokul Chhabra** — 3m VWAP / VWMA / SuperTrend ITM call/put buying (09:45–15:15 IST).
7. **Options → Double Calendar / Delta Neutral** — theta-positive income structures.

### Workflow 7b — Breadth + relative strength (multi-asset)

1. **Advance Decline (Multi Asset)** — India / US / Crypto universe → A/D ratio, volume ratio, trend, strength, RSI.
2. Confirm whether the advance is **healthy** (A/D > 1 + vol > 1 + uptrend) or **hollow**.
3. **Comparative Strength** — pick a base (e.g. Nifty 50 / SPY / BTC) and compare peers; take LONG leaders / SHORT laggards ideas.
4. Open **AI View** on both panels for a confluence verdict (breadth + RS + options when India).

### Workflow 7c — Macro tape (Oil · Dollar · Bond)

1. **Dashboard** or **Command Center → Oil · Dollar · Bond**.
2. Choose **Daily range** or **Same-day intraday** (1m–1h).
3. Read DXY · Brent · US 2Y/10Y · Gold/Silver · Nifty 50 · Dow 30 · Nasdaq · Bitcoin · Ethereum — each with **S1/S2 · R1/R2**.
4. Use the normalized % overlay for direction; open **AI Predictor — Next Move** for RISK-ON / RISK-OFF / MIXED.

### Workflow 7d — Options Market Prediction

1. **Options → Market Prediction** — pick Index or Stock.
2. Check whether today's move is backed by synthetic futures, OI buildup, IV skew, PCR/max pain, VIX, late-session move, FII/DII.
3. Prefer acting only when Market Prediction agrees with Advance Decline / Option Chain bias.

### Workflow 8 — Mega Analyser (fastest research)

1. **Command Center → Mega Analyser**.
2. Choose a **scenario preset** (Full · Pump & Dump · India intraday · Crypto momentum · Swing) or **Custom** engines.
3. One scan runs **22+ engines** — Price Action, MTF, Fakeout, Confluence, Weak Strong S-R, Velez, Crypto Scalping, SMC Fake Market Shift, Smart Wave, etc.
4. Use per-engine verdict + **AI View**; drill into the best engine's dedicated screener.

### Workflow 9 — Buy or Sell (trade decision)

1. **Command Center → Buy or Sell** — pick **Crypto · India · US · Commodity**.
2. Type/filter tickers, select timeframes, run **Analyse & suggest Buy / Sell**.
3. Get **TAKE TRADE / NO TRADE** with confidence %, SL %, TP %, plus AI View.

### Workflow 10 — Ticker Investigation (news + tape)

1. **Command Center → Ticker Investigation** — Crypto, India, US, or **Commodity** tab.
2. Enter one or more tickers → **Search & investigate**.
3. Review headlines, analyst calls, multi-window % moves, S/R strength, breakout odds, **primary trade setup (SL%/TP%/confidence%)**.
### Workflow 11 — Scalping (1m–15m)

1. **Scalping → 1m Rectangle** — FVG + liquidity sweep → rectangle → sniper close breakout (3:1 R:R).
2. **Scalping → SMC Rule of Three** — HTF BOS + premium/discount/OTE + LTF FVG/OB/CRT fusion.
3. **Scalping → ARC Method** — prev-day box + swing zones, 20% unabated move, John Wick hammer at boundary.
4. **Scalping → A+ S/R MSS** — HTF 1H/4H S/R zone tap + 1m market structure shift reversal.
5. Confirm with **MTF Intraday Bias** or **Fakeout 15M** for session direction.
6. **Demo Trading** to log fills before live orders.

### Workflow 12 — Smart Money (SMC)

1. **Smart Money → CISD** — compression → sweep → close through CISD level (golden rule).
2. **Weekly Sweep + CISD** — PWH/PWL sweep failure on 5m/15m.
3. **MTF Day Plan** — HTF OB/FVG → MTF CHoCH → LTF entry.
4. **Golden Bullet** — HTF BOS + kill-zone timing + V-shape liquidity sweep.
5. **SMC Liquidity** — BSL/SSL sweep/grab fades and FVG rebalance entries.
6. **SM — TTG Sniper Entry** — liquidity sweep → Order Block → FVG pullback entry, Aggressive or Conservative (MSS-confirmed).
7. **SMB SnP** — Fashionably Late: LOD grind → 9 EMA × VWAP cross (10:00–13:30, 3:1 R:R).
8. Pair with **Top Down MTF**, **ONE TA Golden Zone**, or **SMC Fake Market Shift** for confluence.

### Workflow 13 — Pro Trade (Volume Profile / VSA / Chart)

1. **Pro Trade → Volume Profile CE** — VA rejection, POC compression breakout, or I-profile LVN slice.
2. **Pro Trade → Volume Profile POC** — wait for HVN zone breakout, then trade the **first** retest of the zone edge.
3. **Pro Trade → PA - Volume Profile** — FVG with POC cluster at the gap start, or S/R flip first retest.
4. **Pro Trade → PA-VP-SMC** — multi-pillar confluence (trend + sweep + VP + SMC zone); prefer high-confidence rows.
5. **Pro Trade → Volume Spread - Next Candle** — SOS (Downthrust / No Supply) longs or SOW (Upthrust / No Demand) shorts for the next bar.
6. **Pro Trade → Elliott Wave / Fibonacci Pro / BB Mean Reversion** — wave count, golden-zone Fib, or %B mean-reversion setups.
7. **Pro Trade → Buy Today Sell Tomorrow** — closing-strength BTST / STBT with OI and historical edge.
8. **Pro Trade → Ticker Chart** — pick India / US / Crypto / Commodity ticker (autosuggest) + date range or intraday; chart auto-draws with **S1/S2 · R1/R2**.
9. Validate in **Strategy Lab / Backtesting** under category **Pro Trade** where available (historical approximations of live scanners).
10. **Demo Trading** before live size.
"""

_WHEN_TO_USE = """
### Quick decision matrix

| Your goal | Best section(s) | Typical hold |
|-----------|-----------------|--------------|
| Pre-open / overnight bias | Command Outlook, News Scanner | — |
| Broad market health | Nifty Breadth, Sector Rotation, Heatmap, Gainers/Losers | — |
| Multi-market movers | Gainers & Losers — Multi-Market (India/US/Crypto/Commodities) | — |
| OB + FVG + S/R confluence scan | Accurate Strategy (Market Pulse) | Intraday – swing |
| Consolidation breakout box | Pump/Dump Breakout (Market Pulse) | Minutes – hours |
| DEX whale flow / on-chain | Big Whale Pump & Dump (Market Pulse) | Minutes – hours |
| Beta-neutral pair trade | Opposite Hedge-MTF, MTF Hedging (TA) | Days – weeks |
| ETF rotation / dynamic SIP | ETF Shop 4.0 (ETF TA IN) | Weeks – months |
| Today's session direction | MTF Intraday Bias (equity or crypto) | Intraday |
| First 15M range fakeout | Fakeout 15M | 5–60 min |
| 4H range fakeout fade | Fakeout 4H | 30 min – 3 hr |
| SMC structured entry (HTF→LTF) | Top Down MTF | 15 min – 5 days |
| Multi-TF confluence score | MTF Scanner | Scalp → position |
| Weekly swing entry | Weekly Stoch Sweet Spot | 1–12 weeks |
| Intraday ribbon + VWMA | KN Smart RSI MTF | 15 min – 3 hr |
| Oliver Velez retrace scalp | Velez Retracement | 2–30 min |
| Crypto bootcamp rules | Smart Wave Crypto | 30m – 1h |
| Crypto 1m/5m VWAP scalp | Crypto Scalping (or Mega Analyser · Crypto momentum) | 1–30 min |
| SMC BOS → POI → fake shift | SMC Fake Market Shift (or Mega · India/Crypto preset) | 15 min – 1d |
| 9:45 opening-range breakout | INTRA — 9:45 Alpha Scanner | Same session |
| 9:45 Fib 50% + EMA bias | INTRA — 9:45 Fib 50% + 10 EMA | Same session |
| VWAP ±1σ fade (range day) | INTRA — VWAP Fade Value Area | 15–60 min |
| 15m breakout-retest (Daniel Holmes) | INTRA — MTF Breakout & Retest | Same session |
| Daily multi-period breakout scan | Breakout MTF (10/20/50/90/200D + RSI/MACD) | Days – weeks |
| Golden Zone Fib pullback + EMA | ONE TA — Golden Zone | Hours – weeks |
| BB free bar fade / squeeze breakout | BB Exposed | Scalp – swing |
| 1m rectangle sniper scalp | Scalping → Rectangle Setup | 1–15 min |
| SMC OTE + FVG + OB + CRT scalp | Scalping → SMC Rule of Three | 15–90 min |
| ARC boundary fade (Area·Range·Candle) | Scalping → ARC Method | 5–60 min |
| HTF S/R zone + 1m MSS scalp | Scalping → A+ S/R MSS (Joovier) | 15–90 min |
| CISD golden entry (no early sweep) | SMC — CISD Entry Rule | 15 min – 1d |
| Weekly PWH/PWL + LTF CISD | SMC — Weekly Liquidity Sweep & CISD | 1–2 weeks |
| MTF day plan OB/FVG/CHoCH | SMC — MTF Day Plan | Intraday |
| Golden Bullet kill-zone sweep | SMC — Golden Bullet (Liquidity + Timing) | 15 min – 4h |
| BSL/SSL sweep · grab · FVG fade | SMC — Liquidity | 15 min – 1d |
| Sweep → Order Block → FVG sniper pullback | SM — TTG Sniper Entry | 15 min – 1d |
| VA rejection / POC compression / LVN slice | Pro Trade → Volume Profile CE | Hours – days |
| HVN breakout → first-touch pullback | Pro Trade → Volume Profile POC | Hours – days |
| FVG + VP cluster · S/R flip retest | Pro Trade → PA - Volume Profile | 15 min – 1d |
| PA + VP + SMC multi-pillar confluence | Pro Trade → PA-VP-SMC | Hours – days |
| VSA SOS/SOW next-candle edge | Pro Trade → Volume Spread - Next Candle | Next 1–3 bars |
| Elliott impulse / corrective scan | Pro Trade → Elliott Wave | Hours – days |
| Fib golden-zone pullback | Pro Trade → Fibonacci Pro | Hours – days |
| BB %B stretch / squeeze mean reversion | Pro Trade → BB Mean Reversion | Scalp – swing |
| BTST / STBT closing strength | Pro Trade → Buy Today Sell Tomorrow | Overnight |
| Quick OHLC chart + S/R levels | Pro Trade → Ticker Chart (daily or intraday) | Session – months |
| Macro FX / oil / yields / metals / indices / crypto | Command Center / Dashboard → Oil · Dollar · Bond | Session – weeks |
| Hollow vs conviction move (derivatives) | Options → Market Prediction | Same session |
| Everything-at-once scan | Mega Analyser (22+ engines incl. Crypto Scalping · SMC FMS · Weak Strong S-R · Velez · Smart Wave) | — |
| Market breadth (A/D + volume + RSI) | Advance Decline (Multi Asset) — India · US · Crypto | Session – weeks |
| Breadth + India options PCR | Advance Decline on Nifty / Bank Nifty / FinNifty / Midcap / Next 50 | Intraday – swing |
| Relative strength vs a base | Comparative Strength (Command Center) | Hours – weeks |
| Asset-class buy/sell call | Buy or Sell Advisor (Command Center) | Scalp – swing |
| News + tape on one symbol | Ticker Investigation (Command Center) | — |
| Commodity futures news + TA | Ticker Investigation → Commodity (`CL=F`, `GC=F`, …) | Intraday – swing |
| Weak vs strong S/R + confluence | Weak Strong S-R (or Mega Analyser) | Scalp – swing |
| Fib + VWAP + ST confluence | Confluence Screener | Intraday – swing |
| Full indicator composite | Sentiment Screener | Any TF |
| Reversal at extremes | Top/Bottom Screener | Hours – days |
| Chart patterns + SL/TP | Pattern & Breakout | Varies |
| S/R levels + trendlines | Find S/R, Price Action | Varies |
| Pre-pump detection | Pump & Dump Screener | Minutes – hours |
| Elliott wave count | Elliott Wave Screener | Swing – position |
| F&O + smart money | SMC · Options Flow · Option Chain · Advance Decline options block | Intraday – swing |
| Gap open play | Gap Trading Scanner | First hour |
| Rule-based universe filter | Advanced Screener | — |
| Historical monthly edge | Seasonality Analyzer | Weeks – months |
| Backtest custom rules | Strategy Builder | Historical |
| Batch backtest many tickers | Multi-Combo Scanner | Historical |
| Paper trade practice | Demo Trading | Live forward |
| Live signal alerts | Alert Monitors | Ongoing |

### By trader style

**Scalper (1m–15m):** Fakeout 15M · Velez · KN Smart · MTF Scanner (1m/5m) · Top Down MTF · **TOPDOWN-MTF** · **Box Trading** · **Scalping Rectangle** · **Scalping SMC** · **Scalping ARC** · **Scalping A+ S/R MSS** · Crypto Scalping · BB Exposed (day preset)

**Intraday (15m–4h):** Fakeout 4H · MTF Intraday Bias · Confluence · KN Smart · Price Action · **INTRA 9:45 Alpha** · **INTRA Fib 945** · **INTRA VWAP Fade** · **INTRA MTF Breakout-Retest** · **Box Trading** · **SMB SnP** · **SMC Golden Bullet** · **SMC Liquidity** · **TTG Sniper Entry** · **Advance Decline** intraday TF · **Comparative Strength** on session TF

**Swing (4h–1w):** Weekly Stoch · MTF Scanner (4h/1d) · Pattern Breakout · Sentiment · Seasonality · **Breakout MTF** · **ONE TA** · **TOPDOWN-MTF** (1d→1h→15m) · **ST Capitulation** · **ST MSS** · **ST SuperTrend** · BB Exposed (swing preset) · **TTG Sniper Entry** (HTF) · **Advance Decline** daily · **Comparative Strength** 1d/1w

**SMC / Smart Money:** Top Down MTF · **TOPDOWN-MTF** · SMC Fake Market Shift · **CISD** · **Weekly Sweep CISD** · **MTF Day Plan** · **Golden Bullet** · **SMC Liquidity** · **TTG Sniper Entry** · **SMB SnP** · Scalping SMC · ONE TA

**Pro Trade (VP / VSA / Chart):** **Volume Profile CE** · **Volume Profile POC** · **PA - Volume Profile** · **PA-VP-SMC** · **Volume Spread - Next Candle** · **Elliott Wave** · **Fibonacci Pro** · **BB Mean Reversion** · **BTST** · **Ticker Chart**

**Trading Agent / Technical Agent (chat):** Pure **Price Action** only — Support/Resistance · Volume · RSI · Bollinger Bands (candlestick confirmation at the band). Deep mode = broader universe, same pillars. No Workflow / PA-VP-SMC / options enrichments on this desk.

**Positional (1w+):** Weekly Stoch · Elliott Wave · Seasonality · Sentiment on 1d/1w · **Oil · Dollar · Bond** macro regime

### By market type

**Trending:** MTF Scanner · KN Smart · Top Down MTF · Supertrend presets in Builder · **Comparative Strength** leaders · **Oil · Dollar · Bond** risk-on tape

**Range-bound:** Fakeout 15M/4H · Confluence · BB/RSI presets · Top/Bottom · hollow A/D (A/D > 1 but volume ratio < 1) · **BB Mean Reversion**

**High volatility / crypto:** Smart Wave · Pump & Dump · MTF Crypto Bias · Demo Crypto ledger · Advance Decline Crypto Top 30/50 · **Ticker Chart** (Crypto) · Oil-Dollar-Bond BTC/ETH panels

**India F&O:** SMC Options · News PCR · Option Chain · Option-Short-Long · **Advance Decline** options snapshot · **Market Prediction** · MTF Equity Bias (PCR component)
"""

_STRATEGY_LAB_DETAIL = """
### Strategy Lab — deep dive

#### Strategy Builder & Tester
- Add indicators (EMA, RSI, MACD, BB, Supertrend, VWAP, Fib, etc.).
- Define **entry rules** (all must be true) and **exit rules**.
- Set ticker, timeframe, SL %, TP %, backtest date range.
- **Run Backtest** → equity curve, trade list, win rate, profit factor, drawdown.
- **Save** to archive (login required).

#### Saved Strategies Archive
- Reload any saved backtest by name.
- Compare metrics side-by-side.
- Re-run with updated date range.
- Source list for **Alert Monitors**.

#### Multi-Combo Scanner
- Pick saved strategies **or** built-in TA hub engines (**30 strategies** in 6 groups).
- Groups: Core MTF & session · TA extensions · Crypto · Scalping · Smart Money · Intraday.
- Includes **TOPDOWN-MTF**, **Box Trading**, **SMB SnP**, and all Scalp/SMC/Intraday hub engines.
- Batch: many tickers × many timeframes × many strategies (TA engines run **once per ticker**).
- Rank by backtest metrics; **save picks** for alerts.
- **Lazy load:** 20 tickers per batch — Load next batch until complete.
- Best for finding *which* ticker loves *which* strategy.

#### AI Strategy Creator
- Paste a YouTube transcript, PDF notes, or plain-English rules.
- LLM (Gemini / Groq / Claude Azure / OpenAI Azure — same Manage settings) outputs structured JSON: indicators, entry/exit, SL/TP, timeframe.
- Always **review in Builder** before trusting — LLM may misparse edge cases.

#### Strategy Encyclopedia (this page)
- **App overview** — hubs, AI Settings, Command Center highlights.
- **Workflows** — morning, scalp, swing, options, breadth+RS, Mega Analyser, Buy/Sell, Investigation.
- **When to use what** — matrix by goal, style, and market type.
- **All hubs & strategies** — every section with its Strategy Guide body.
- **Preset Catalog** — documented preset strategies for the Builder.

### Ask AI / AI View (everywhere)

1. Run any scan that produces a results card.
2. Scroll to **AI View** (or Ask AI) — context is auto-built from the scan JSON.
3. Leave the default question or ask your own; click **Generate AI View**.
4. Provider/model come from **Manage → AI Settings** (not per-panel keys).
5. Treat the verdict as a second opinion — always cross-check levels against the chart.

### Screen & Scan

#### Advanced Screener
- Custom indicator conditions across an index universe or custom list.
- Preset filters + your own rules. Groww and CoinDCX.

#### Gap Trading Scanner
- Detects gap up/down vs prior close.
- S/R context, fade vs continuation bias, fill probability estimate.
- Best used in first 30–60 minutes after India open.

### Seasonality Analyzer
- Monthly win rate and average return over historical years.
- Use as **confirmation**, not standalone entry signal.

### ST — Swing Trading (Capitulation & Continuation)
- **Mean reversion:** RSI oversold + 2× volume + close above prior high; trail below prior low.
- **Continuation:** Close above 60-bar high; trail below 20 MA.
- Backtrader backtest + live scan with confidence, SL%, TP% on Groww, CoinDCX, US.

### ST — Weekly Fakeout + 15m MSS
- **Weekly PWH/PWL** — prior week range boundaries mapped to each daily bar.
- **Daily fakeout** — stop hunt above PWH or flush below PWL with close back inside.
- **15m MSS** — swing break after liquidity peak/trough; 1:1 R:R reference stop/target.

### ST — SuperTrend + SMA 10
- **Daily swing** — SMA 10 / SuperTrend (10,3) crossover entry; SMA trail exit.
- **Weekly pyramid** — core on SuperTrend flip; adds on SMA reclaim; structural ST exit.

### ST — KISS Swing Systematic
- Weekly **Heikin Ashi** trend filter; **1h** or **4h** execution.
- **55 EMA high-low band** + Signal MA Dhan + **MACD** zero cross.
- Risk 1–2%, R:R 1:3–1:4, structural SL, conf/SL%/TP%/hold time.

### ST — Daily HA + 34 EMA Intraday
- Previous daily **Heikin-Ashi** sets session bias (calls vs puts).
- **34 EMA** high/low channel on **5m/15m** for breakout entries & band exits.

### INTRA — 9:45 AM Alpha Scanner
- Run at **9:45 IST** — mcap, volume, EMA20, SuperTrend, +0.5–1.5% day change filters.
- Buy stop above first **30m** candle high; SL at low/body low; **1:2** minimum R:R.

### INTRA — 9:45 Fib 50% + 10 EMA
- **50% Fib** equilibrium of 9:15–9:45 range sets bullish/bearish bias.
- **10 EMA** cross on 5m/1m with **30 MA** confirmation; SL at prior low or Fib.

### INTRA — VWAP Fade Value Area
- **Range-day filter** — trade only when price stays inside ±1σ VWAP bands.
- Fade upper/lower band rejections back to **VWAP**; **60 min** time stop; skip first 15 min.

### INTRA — MTF Breakout & Retest (Daniel Holmes)
- **Daily bias** filter — longs only on bullish days, shorts on bearish days.
- **4H / 1H / 30m** structure alignment; **15m** equal-body S/R breakout with retest entry.
- **1:1 R:R** with 80% partial; SL beyond wick.

### BB Exposed — Free Bar + Squeeze
- **Free Bar** — full candle outside Bollinger Bands = exhaustion fade (reversal candle confirm).
- **Squeeze** — bandwidth contraction then decisive close outside bands.
- Day preset BB(10,1.5) · Swing BB(50,2.5) · 2:1 R:R minimum.

### Breakout MTF — Multi-Period Daily Scanner
- Parallel **10 / 20 / 50 / 90 / 200** day breakout & breakdown flags (current bar excluded).
- **RSI 50–70** + **MACD positive** confirmation for bullish breakouts.
- FoxTrader-style dashboard table per ticker.

### ONE TA — Golden Zone Fib + EMA
- **200 EMA** trend bias · pullback into **50%–61.8%** Golden Zone.
- **Engulfing** (2-candle body) or **50%+ wick rejection** entry at zone.
- Partials at **38.2% / 23.6%** · full target at swing origin.

### TOPDOWN-MTF — Liquidity + Order Blocks
- **HTF** trend (1d) → **ATF** order blocks & liquidity sweeps (1h) → **LTF** MSS entry (15m).
- Distinct from Top Down MTF (CHoCH/FVG on shorter default TFs).

### Box Trading — TradingLab Prev-Day Range
- **Previous day high/low** box on today's chart · **middle 50%** no-trade zone.
- Edge **reversals** (pin/engulfing) or **breakout retest** — never long at top / short at bottom.

### SMB SnP — Fashionably Late (Smart Money)
- Morning **LOD** grind → **9 EMA crosses up through VWAP** (10:00–13:30 window).
- **3:1 R:R** from LOD unit · RVOL + daily SMA filters.

### Scalp — 1m Rectangle Sniper Entry
- **FVG** imbalance + liquidity sweep → draw rectangle on rejection wick.
- **Sniper entry** when 1m candle closes through rectangle body edge.
- SL beyond wick · minimum **3:1 R:R** · hold 1–15 minutes.

### Scalp — SMC Rule of Three
- **HTF** BOS/CHoCH + premium/discount/**OTE** matrix off latest swing leg.
- **LTF** FVG, displacement order blocks, validated **CRT** sweeps.
- Fused entries when HTF bias + zone + LTF confirmation align.

### Scalp — ARC Method (Area · Range · Candle)
- **Area** — prev-day box + swing liquidity zones define boundaries only.
- **Range** — 20% unabated move from boundary without mid-box chop.
- **Candle** — John Wick hammer rejection triggers fade entry.

### Scalp — A+ S/R Zone + 1m MSS (Joovier)
- **HTF** 1H/4H support/resistance zones mapped to session.
- **1m MSS** — market structure shift after zone tap (LH/LL into support, etc.).
- Default ~2.4:1 R:R · Groww after 09:15 IST.

### SMC — CISD Entry Rule
- **Compression** → **liquidity sweep** → displacement → **close through CISD level**.
- Golden rule: never enter at the sweep extreme; wait for CISD break.

### SMC — Weekly Liquidity Sweep & CISD
- **PWH/PWL** weekly levels · sweep · LTF CISD failure · TP at opposing weekly level.

### SMC — MTF Day Plan (OB · FVG · CHoCH)
- **HTF** trend + OB/FVG · **MTF** counter-trend into zone · **CHoCH** · LTF limit entry.

### SMC — Golden Bullet (Liquidity + Timing)
- HTF **BOS** + extreme POI liquidity pools.
- **Kill zones** (London 03–06 EST · NY overlap 08–11 EST).
- **V-shape sweep** rejection · LTF alignment · **3:1 R:R**.

### SMC — Liquidity (Sweeps · Grabs · FVG)
- **BSL/SSL** structural pools — sweep/grab fade when wick breaks structure, close inside.
- **FVG rebalance** — ATR-filtered gap retest entries.
- **Liquidity run** — expansion candle continuation watch (not a fade).

### SM — TTG Sniper Entry (Sweep · Order Block · FVG)
- **Sweep** — price pierces a prior swing high/low and closes back inside (the trap).
- **Displacement filter** — the move away from the sweep must exceed a configurable × ATR threshold, or the setup is discarded.
- **Order Block** — last opposite-colour candle before the impulsive move.
- **Fair Value Gap** — 3-candle imbalance inside the impulsive leg, overlapping the Order Block — the precise entry zone (falls back to the full Order Block if no FVG forms).
- **Entry modes** — Aggressive (enter on zone tap) or Conservative (wait for a lower-TF market structure shift after the tap).
- **Advanced stop tip** — no FVG + wide Order Block → stop tightens to just beyond the sweep candle's extreme instead of the whole block.
- **Context rule** — sweep direction must match the HTF SMA trend bias (toggleable) — not every sweep is tradeable.
- Fixed **R:R target** (2R default), configurable.

### Market Pulse — key screeners

| Section | Use |
|---------|-----|
| **Gainers & Losers Multi-Market** | Top movers across India/US/Crypto/Commodities × multiple TFs |
| **Accurate Strategy** | OB + FVG + S/R confluence score |
| **Pump/Dump Breakout** | Consolidation box breakdown & breakout |
| **Big Whale Pump & Dump** | DEX whale flow signals |
| **Sector Rotation** (India/US/Crypto) | Daily/weekly/monthly + intraday rotation |
| **Commodity Screener** | Nifty-linked commodity buy/sell bias |

### Demo Trading
- **India:** virtual NSE/BSE book tied to your login.
- **Crypto:** separate CoinDCX-style futures ledger.
- Track P&L, positions, and history without real orders.

### Alerts
- Saves **Multi-Combo picks** as monitors.
- Polls latest bar on interval; sends **Telegram** and/or **email** when entry rules match.
- Requires login + configured alert channels in sidebar/settings.
"""

# Extra detail for sections with thin SECTION_GUIDES entries
_SECTION_EXTRAS: dict[str, str] = {
    "mega_analyser": """
**When to use:** One-click **unified scan** across **30 per-ticker TA scanners** plus core TA legs (price action, S/R, confluence, sentiment, etc.).
Use scenario presets or **Setup Advisor**; lazy-loads **20 tickers per batch**. Best for morning watchlist triage.
""",
    "multi_combo": """
**When to use:** Batch **backtest ranking** — find which ticker performs best on which of the **30 TA hub engines** (6 groups in UI).
Save winners to **Alert Monitors**. Lazy-loads 20 tickers per batch.
""",
    "find_sr": """
**When to use:** Before entering any trade — know where S1/S2/R1/R2 and trendline breaks are.
**How:** Select tickers → timeframes → Run Scan. Expand ticker for chart + AI View.
""",
    "pump_dump_predictor": """
**When to use:** Hunting early movers in small/mid caps or volatile crypto alts.
**Rule of thumb:** 1 green = watch · 3+ greens + score 55+ = actionable · always confirm volume.
""",
    "smc_options": """
**When to use:** NSE F&O names where options flow (delivery, PCR, OI change) confirms SMC structure.
**India only** — requires liquid options chain data.
""",
    "bb_exposed": """
**When to use:** Volatility exhaustion fades (free bar outside bands) or squeeze breakouts after bandwidth contraction.
Day preset BB(10,1.5) for scalp; swing BB(50,2.5) for larger moves. Confirm free bars with reversal candles.
""",
    "breakout_mtf": """
**When to use:** Daily swing scanner — fresh closes breaking 10/20/50/90/200-day highs or lows with RSI + MACD filters.
FoxTrader-style dashboard for watchlist ranking. Best on liquid NSE/US names with 200+ daily bars.
""",
    "one_ta": """
**When to use:** Golden Zone pullback trades — 50–61.8% Fib retrace with 200 EMA trend bias,
engulfing or 50% wick rejection entry. Scale at 38.2%/23.6%, full target at swing origin.
""",
    "topdown_mtf": """
**When to use:** SMC **top-down** with **liquidity sweeps + order blocks** — HTF trend (1d) → ATF structure (1h) → LTF MSS entry (15m).
Distinct from Top Down MTF (CHoCH/FVG on shorter default TFs). Groww · US · CoinDCX.
""",
    "box_trading": """
**When to use:** Intraday **previous-day range** fades and breakout-retests — no indicators.
Map yesterday's high/low, avoid the midpoint 50% chop, trade edge rejections or retests only.
Best on liquid names during regular session hours.
""",
    "strategy_scheduler": """
**When to use:** Scheduled batch scan of encyclopedia-style preset packs across Groww or crypto universes.
Good for end-of-day watchlist building.
""",
    "screener": """
**When to use:** You have specific indicator conditions (e.g. RSI<30 + EMA cross) and want to filter 50–500 tickers.
**Tip:** Start from a preset, then customize rules.
""",
    "gap_scanner": """
**When to use:** First hour after open — gap continuation vs fade setups.
Pair with Find S/R for target levels.
""",
    "intraday_vwap_fade": """
**When to use:** Range-bound intraday sessions — fade ±1σ VWAP band rejections to VWAP.
Skip first 15 min; avoid on strong trend days.
""",
    "intraday_mtf_breakout_retest": """
**When to use:** Clear daily bias days — 15m equal-body S/R breakout with retest continuation.
Requires clean traffic left of range; HTF 4H/1H/30m alignment boosts confidence.
""",
    "intraday_7_wasted": """
**When to use:** Bullish daily sessions — first 5 minutes define OR; enter on 1m retest of OR high
after breakout close. Do not chase the initial breakout; wait for internal liquidity retest.
""",
    "scalp_rectangle": """
**When to use:** 1m scalps after FVG + liquidity sweep forms a clear rejection rectangle.
Best on liquid names (indices, large caps, major crypto pairs).
""",
    "scalp_smc": """
**When to use:** Structured SMC scalps when HTF bias + discount/premium OTE zone + LTF CRT/FVG/OB align.
Use 5m LTF for India; crypto/US align well with auto HTF resample.
""",
    "scalp_arc": """
**When to use:** Boundary-only institutional fades on range days — prev-day box + swing levels,
20% unabated move, John Wick hammer trigger. Avoid mid-box chop. Best on liquid NSE / US / crypto pairs.
""",
    "scalp_sr_mss": """
**When to use:** HTF S/R zone taps with 1m MSS reversal — LH/LL into support or HH/HL into resistance,
then swing break entry. Groww after 09:15 IST; US/crypto after 09:30 NY. Default ~2.4:1 R:R.
""",
    "scalp_a_plus": """
**When to use:** Waqar Asim Scalp A+ — daily range + qualified POI (depth/duration/inducement),
skip 1H smart-money traps, execute two-leg + FVG on 1m/5m toward 1:3 / 1:10. Best when HTF POI is fresh
and price is in a complex pullback into the zone.
""",
    "scalp_gold": """
**When to use:** The Trading Geek gold scalp — 1H+15m aligned, wait for 15m demand/supply POI,
enter only after a liquidity sweep (aggressive) or MSS+pullback (conservative). Best on GC=F / XAU / gold ETFs;
keep targets at the next logical pool and risk tight beyond the sweep candle.
""",
    "smc_cisd": """
**When to use:** Avoid early sweep entries — wait for CISD close break after compression + liquidity grab.
Multi-TF: execution TF + optional HTF bias filter.
""",
    "smc_weekly_sweep_cisd": """
**When to use:** Swing/intraday reversals at weekly liquidity (PWH/PWL) with 5m/15m CISD confirmation.
""",
    "swing_fire": """
**When to use:** Equity cash swing on ATH/VCP/IPO leaders — trail 21/63 EMA, monthly ROC cycle for aggression,
~10% loss cap. Skip falling knives and F&O. Best when ROC is near zero and leaders hold highs in a sideways index.
""",
    "smc_mtf_day_plan": """
**When to use:** Intraday SMC day-trading plan — HTF OB/FVG → MTF CHoCH → LTF entry with defined SL/TP.
""",
    "smc_golden_bullet": """
**When to use:** Kill-zone timed liquidity sweeps with V-shape rejection at extreme POI pools.
EST windows: London 03–06 · NY overlap 08–11. Crypto/US align best.
""",
    "smc_liquidity": """
**When to use:** Structural BSL/SSL sweeps/grabs and FVG rebalance fades — order-flow liquidity pools
from OHLCV swing structure. Modes: Sweep/Grab, FVG, or Both. Target opposite pool on reversals.
""",
    "smb_snp": """
**When to use:** Intraday **Fashionably Late** scalp — after morning LOD, wait for **9 EMA × VWAP** cross
between 10:00–13:30. 3:1 R:R from LOD unit. Best on liquid large caps with RVOL ≥ 1.5 and daily SMA support.
""",
    "market_gainers_losers": """
**When to use:** Quick scan of top gainers/losers across India, US, crypto, commodities on multiple timeframes.
""",
    "accurate_strategy": """
**When to use:** When you want OB + FVG + S/R confluence scored on a watchlist before picking a direction.
""",
    "mtf_hedging": """
**When to use:** Portfolio hedging — beta hedge, pairs trade, protective puts, index ETF overlay.
""",
    "volume_profile_ce": """
**When to use:** Session value-area fades, multi-day POC compression breakouts, or I-profile LVN vacuum moves.
Live scanner is under **Pro Trade**; Strategy Lab backtest uses a historical approximation.
""",
    "volume_profile_poc": """
**When to use:** After price breaks an HVN/POC zone — enter only on the **first** retest of the zone edge; stop in LVN.
""",
    "pa_volume_profile": """
**When to use:** Trader Dale-style FVG + volume cluster entries, or S/R flips with VP confirmation on the first retest.
""",
    "pa_vp_smc": """
**When to use:** Highest-confluence Pro Trade setups — require multiple pillars (trend, sweep, VP, SMC) before size.
""",
    "volume_spread_next_candle": """
**When to use:** Wyckoff VSA SOS/SOW bars — edge is primarily the **next candle** after Downthrust / No Supply / Upthrust / No Demand.
""",
    "advance_decline_graph": """
**When to use:** Morning or session check that an index rally/selloff is broad-based.
India F&O indices also show PCR — use when deciding if breadth and options positioning agree.
""",
    "comparative_strength": """
**When to use:** Pair trades and relative longs/shorts — who is beating the base (Nifty / SPY / BTC) over the lookback.
""",
    "oil_dollar_bond": """
**When to use:** Macro regime + India sector rotation — DXY vs oil/metals/yields, global indices/crypto,
and India ETFs (Bank, IT, Mid/Smallcap, Pharma, Metal, Power, FMCG, …).
Daily or same-day intraday with S/R on every panel; AI next-move for RISK-ON / RISK-OFF / MIXED.
Also available on the **Dashboard**.
""",
    "mtf_trend_strength": """
**When to use:** Confirm trend alignment across multiple timeframes before sizing a directional trade.
""",
    "market_movers": """
**When to use:** Quick scan of index gainers/losers across India / US / Crypto / Commodity universes.
""",
    "smart_money_activity": """
**When to use:** Check institutional / smart-money footprints on a watchlist before committing to a setup.
""",
    "elliott_wave_pro": """
**When to use:** Pro Trade Elliott impulse/corrective scanner on a watchlist — pair with Fibonacci Pro for targets.
""",
    "fibonacci_pro": """
**When to use:** Golden-zone Fib pullbacks and multi-strategy Fib evaluations on India / US / Crypto / Commodity.
""",
    "bb_mean_reversion": """
**When to use:** Mean-reversion when %B stretches and S/R + RSI + volume climax agree — avoid strong-trend (high ER) regimes.
""",
    "bb_rsi_vol": """
**When to use:** Fade Lower BB with RSI≤35 + low volume at Support (buy) or Upper BB with RSI≥70 + high volume at Resistance (sell); confirm with 9 EMA close; skip steep 50 EMA trends.
""",
    "ema_cross": """
**When to use:** Long near Lower BB with RSI<35; short at Upper BB with RSI>65; wait on mid BB; always review the last ~1000-bar upward/descent phase.
""",
    "ema9_bb_rsi_vol": """
**When to use:** Same as EMA Cross — Lower BB+RSI<35 / Upper BB+RSI>65 / mid wait + 1000-bar phase.
""",
    "ema5_bb_rsi_vol": """
**When to use:** Legacy route into EMA Cross; prefer the unified EMA Cross screen.
""",
    "ema5_9_crossover": """
**When to use:** Trade a fresh EMA5/EMA9 crossover with close confirming both EMAs, Bollinger room, RSI zone, and volume; invalidate on opposite re-cross.
""",
    "ema9_vol_rsi_momentum": """
**When to use:** Intraday scalp when 5m is established beyond 9 EMA (≥4 bars), structure+volume+RSI agree (score ≥7), HTF 15m EMA bias aligns, and the bar breaks prior high/low — not during EMA chop or after a huge chase candle.
""",
    "crypto_multibagger_reversal": """
**When to use:** Fade CoinDCX coins with |24h| ≥40% on 5m when price is below EMA 280/300 and SuperTrend flips red; exit on ST green; target −10%.
""",
    "crypto_advance_bb_reversal": """
**When to use:** 30m Bollinger pierce then close back inside — SHORT to lower BB / LONG to upper BB; size for ₹200 risk / ₹600 reward; prefer with-trend and S/R confluence (~80% claim).
""",
    "crypto_ema_crossover": """
**When to use:** Trade fresh fast×medium EMA crosses with per-coin presets — BTC 30m 9/30 (1.5%/6%), ETH/SOL 4h 10/21, XRP 1h 10/26, BNB 4h 9/30 (fixed % SL/TP).
""",
    "crypto_supertrend": """
**When to use:** Trade SuperTrend color flips (S2 Archit) — GREEN→LONG / RED→SHORT on 1h with per-coin ATR/factor (BTC 25/6.325, ETH 15/6.325, SOL 25/3.5, XRP 10/2.5) and fixed % SL/TP; exit on opposite color.
""",
    "flat_retest": """
**When to use:** After flat candles — LONG on break→retest hold as support; SHORT on reject→break cons low→failed retest. Never invent the next candle inside the box.
""",
    "traffic_light_indicator": """
**When to use:** Swing buy when SMA200>50>20 and daily close is under all three; sell when stack flips and close is above all three. Prefer large-caps; optional MTF Trend & Strength.
""",
    "buy_low_sell_high": """
**When to use:** Dip-buy liquid names with a GTT at 25-day low + 5%; update on new lows; add only after −10% vs average; sell all at average + 5%; no stop-loss.
""",
    "rlb_breakout": """
**When to use:** Screen for rocket-launcher breakouts — prior-high break + green candle + EMA20/50 + RSI>60 + >2% day + volume > 5-day SMA.
""",
    "three_in_one_trade_system": """
**When to use:** DMA 50/100/200 + CAR rising from 52w high; buy closest to 200 DMA; exit +6.28% avg; SIP only after −20% with CAR re-trigger and 30d gap.
""",
    "simple_effective": """
**When to use:** MA-band full close outside + MACD crossover inside matching histogram; enter on signal high/low break; SL opposite band; TP 1:1–1.5 RRR.
""",
    "etf_28_sma": """
**When to use:** India ETF momentum with 28 SMA two-close entry/exit, 3.14% profit floor, 5% cheaper re-breakout averaging, and FIFO/LIFO lot booking. Scan near the close.
""",
    "etf_top_down": """
**When to use:** Top-down ETF swing (Finding Edge / Jay) — noise-filter 6 macros, dual P&F RS
(0.25% daily + 1% weekly, max 18), shortlist Top 20 with score > 0, enter/exit on Renko × D-Smart 10,
rebalance weekly (Fridays). Principles: profit + don’t give it back.
""",
    "mf_fire": """
**When to use:** Size your FI number (25×/35× expenses), 1% salary-confidence portfolio, and SIP runway — then pick equity MFs on Best MF. Education only.
""",
    "btst": """
**When to use:** Overnight BTST / STBT when closing strength (CLV), volume, RS, VWAP, and optional OI buildup align.
""",
    "ticker_chart": """
**When to use:** Fast OHLC chart for any India / US / Crypto / Commodity ticker with auto S1/S2 · R1/R2.
Daily date range or same-day intraday; chart draws as soon as ticker + dates are set (autosuggest ticker box).
""",
    "hedging": """
**When to use:** Protective overlays, beta hedges, and pairs-style option hedges around an existing view.
""",
    "zero_to_hero": """
**When to use:** Structured high-conviction options progression setups (see Options → Zero to Hero guide).
""",
    "market_prediction": """
**When to use:** Before trusting today's index/stock move — check whether derivatives (synthetic futures, OI, IV skew, PCR, VIX, FII/DII) back the tape or call it hollow.
""",
    "call_put_writing": """
**When to use:** Map Call writing resistance walls and Put writing support floors; watch short-covering if Call walls break.
""",
    "profitable": """
**When to use:** Reactive overnight option-buying desk — 09:20 mark CE/PE in ₹50–75, buy-stop +50%, SL −50% of entry; prefer overnight carry. Source: https://www.youtube.com/watch?v=w_8cVFZ1iZE
""",
}


def encyclopedia_catalog() -> dict[str, Any]:
    """JSON-safe hub map + guides for Strategy Lab / API Encyclopedia."""
    hubs = []
    for hub_name, sections in HUB_SECTIONS.items():
        entries = []
        for section_id, title in sections:
            body = SECTION_GUIDES.get(section_id, "")
            extra = _SECTION_EXTRAS.get(section_id, "")
            entries.append({
                "id": section_id,
                "title": title,
                "guide": (body or "").strip() or None,
                "extra": (extra or "").strip() or None,
            })
        hubs.append({"hub": hub_name, "sections": entries, "count": len(entries)})
    return {
        "hubs": hubs,
        "hub_count": len(hubs),
        "section_count": sum(h["count"] for h in hubs),
        "overview": _OVERVIEW.strip(),
        "workflows": _WORKFLOWS.strip(),
        "when_to_use": _WHEN_TO_USE.strip(),
        "strategy_lab_detail": _STRATEGY_LAB_DETAIL.strip(),
    }


def render_application_guide() -> None:
    """Render the full application reference inside the Encyclopedia tab."""
    tab_overview, tab_workflows, tab_matrix, tab_sections, tab_lab = st.tabs([
        "🗺️ App Overview",
        "🔄 Workflows",
        "🎯 When to Use What",
        "📂 All Sections",
        "⚡ Strategy Lab & Tools",
    ])

    with tab_overview:
        st.markdown(_OVERVIEW)

    with tab_workflows:
        st.markdown(_WORKFLOWS)

    with tab_matrix:
        st.markdown(_WHEN_TO_USE)

    with tab_sections:
        st.markdown(
            f"Every hub section is listed below (**{sum(len(s) for s in HUB_SECTIONS.values())} sections** across "
            f"**{len(HUB_SECTIONS)} hubs**). "
            "The same **📖 Strategy Guide** appears at the top of each section when you use it in the app."
        )
        for hub_name, sections in HUB_SECTIONS.items():
            st.markdown(f"## {hub_name}")
            for section_id, title in sections:
                body = SECTION_GUIDES.get(section_id, "_No guide available yet._")
                extra = _SECTION_EXTRAS.get(section_id, "")
                with st.expander(f"**{title}**", expanded=False):
                    st.markdown(body.strip())
                    if extra:
                        st.markdown(extra.strip())
            st.markdown("---")

    with tab_lab:
        st.markdown(_STRATEGY_LAB_DETAIL)
        st.markdown("---")
        st.markdown(
            "For every other hub section (Market Pulse, Technical Analysis, Intraday, "
            "Scalping, Smart Money, Swing Trading), open the **📂 All Sections** tab — "
            "each entry mirrors the **📖 Strategy Guide** shown inside that section in the app."
        )
