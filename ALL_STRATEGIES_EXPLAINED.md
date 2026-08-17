# TrueBacktester — All Strategies Explained

Generated catalog: **160** sections across **16** hubs.

Research / education only — not financial advice. Always confirm with your own analysis and risk rules.

# App overview

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
| **Swing Trading** | ST capitulation, MSS, SuperTrend, KISS, HA+EMA, **Swing - FIRE** | Multi-day swing on India / US / crypto |
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

# Workflows

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

# When to use what

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

## 🚀 Command Center

### Tomorrow & Today Market Outlook
*id: `command_outlook`*

### Tomorrow & Today Market Outlook
Forward-looking Command Center snapshot from the same live payload as Market Pulse.

| Input | Use |
|-------|-----|
| Global indices and Gift Nifty | Overnight / pre-open bias |
| FII/DII, breadth, turnover | Cash-market participation |
| Nifty options (PCR, max pain, OI) | Directional and pinning risk |
| Fresh news, analyst calls, events | Catalysts for today / next session |

**Today banner** = composite sentiment. **Tomorrow banner** = gap risk, global cues, and event risk into the next session.

---

### Global Market Mood — regions · sectors · geopolitics
*id: `global_market_mood`*

### Global Market Mood
Worldwide **regional mood dashboard** — one refresh for India, Asia, Europe, US stocks & futures, crypto, commodities, and gold/silver.

| Region | Instruments tracked |
|--------|---------------------|
| 🇮🇳 India | Nifty, Bank Nifty, Sensex, IT, Midcap, Gift Nifty, USD/INR, VIX |
| 🌏 Asia | Nikkei, Hang Seng, Shanghai, KOSPI, STI, ASX, Taiwan |
| 🇪🇺 Europe | FTSE, DAX, CAC |
| 🇺🇸 US | Dow, S&P, Nasdaq, Russell |
| 📈 US Futures | YM, ES, NQ |
| ₿ Crypto | BTC, ETH, SOL |
| 🛢️ Commodities | WTI crude, DXY, US 10Y |
| 🥇 Gold & Silver | GC, SI futures |

**Also includes:** geopolitical/war headline filter · **sector leading/lagging** (NSE sectoral indices) with rotation outlook · **stock movers** (Nifty 50 · S&P 500 · CoinDCX crypto).

Mood = average signed % change per region (VIX and bond yields inverted). **WATCHLIST**-style composite at top.

---

### Mega Analyser — unified multi-engine scan
*id: `mega_analyser`*

### Mega Analyser — unified multi-engine scan
One click runs **30 per-ticker TA scanners** plus core TA legs on your watchlist with scenario presets.

| Engine bucket | Includes |
|---------------|----------|
| Core TA | Price Action, Find S/R, **Weak Strong S-R**, Pattern and Breakout, Confluence, Sentiment, Elliott |
| MTF / session | MTF Scanner, Top-Down SMC, **TOPDOWN-MTF (liquidity + OB)**, **MTF Intraday Session Bias**, Weekly Stoch, KN Smart |
| TA extensions | **BB Exposed**, **Breakout MTF** (daily BO), **ONE TA** (Golden Zone), **Box Trading** (prev-day range) |
| Scalp | Fakeout 4H/15M, **Velez Retracement**, **Crypto Scalping**, **Rectangle**, **SMC Rule of Three**, **ARC**, **S/R MSS** |
| SMC / structure | **SMC Fake Market Shift**, **CISD**, **Weekly Sweep CISD**, **MTF Day Plan**, **Golden Bullet**, **Liquidity**, **SMB SnP**, SMC Flow (India stocks) |
| Intraday | **Alpha 9:45**, **Fib 9:45**, **VWAP Fade**, **MTF Breakout-Retest** |
| Crypto | **Smart Wave Crypto** (CoinDCX only) |
| Special | Pump and Dump pre-move, Gap, Seasonality, Strategy Builder backtest, Saved Strategies, Screener |

**Scenarios:** Full analysis · Pump & Dump pre-move · India intraday scalp · Crypto momentum · Swing/positional · **Custom**.

Large watchlists run in **batches of 20 tickers** — each batch shows digest + per-ticker breakdown; click **Load next 20** until the full list is done.

**Setup advisor:** Auto recommendations for your market + timeframes (no AI). Click **Ask AI for setup advice** for personalized asset class, timeframes, scenario, and engine list; **Apply** pushes settings to the controls below.

Each ticker gets per-engine verdict, mega score, trade plan, and optional **AI View**. Pair with **Buy or Sell** for asset-class presets.

**When to use:** One-click **unified scan** across **30 per-ticker TA scanners** plus core TA legs (price action, S/R, confluence, sentiment, etc.).
Use scenario presets or **Setup Advisor**; lazy-loads **20 tickers per batch**. Best for morning watchlist triage.

---

### Buy or Sell — Crypto · India · US · Commodity
*id: `buy_sell_advisor`*

### Buy or Sell — Multi-Asset Trade Advisor
Four tabs — **Crypto · Indian stocks · US stocks · Commodity** — with typed ticker search, multiselect symbols, and **multi-timeframe** analysis.

| Asset class | TA profile |
|-------------|------------|
| Crypto | Crypto momentum + Smart Wave |
| India | India intraday scalp (SMC Flow, session bias) |
| US / Commodity | Swing / positional (S/R, confluence, MTF) |

**Output:** **TAKE LONG/SHORT** or **NO TRADE**, **confidence %**, **SL %**, **TP %**, engine confluence list, and **AI View** synthesis.

Pick tickers → durations → **Analyse & suggest Buy / Sell**. Requires network; India optional Groww token.

---

### Ticker Investigation — Crypto · India · US · Commodity
*id: `ticker_investigation`*

### Ticker Investigation — News · Price Action · S/R · Strategies
Four tabs — **Crypto · Indian stocks · US stocks · Commodity**. Enter comma-separated tickers → **Search & investigate**.

| Tab | Tickers | Data |
|-----|---------|------|
| Crypto | CoinDCX USDT pairs | CoinTelegraph, CoinDesk, … |
| India | NSE symbols | Moneycontrol, LiveMint, ET Now, … |
| US | NYSE/Nasdaq | Yahoo, MarketWatch, Seeking Alpha, … |
| **Commodity** | Yahoo futures `CL=F`, `GC=F`, `SI=F`, `HG=F`, `NG=F`, `ZW=F` | Moneycontrol Commodities, macro RSS, Google News |

| Output | Detail |
|--------|--------|
| News | RSS from **Investing.com**, Moneycontrol, LiveMint, ET Now, Zee Business, NDTV Profit, Yahoo, MarketWatch, CoinTelegraph, Google News (`site:investing.com`), and more |
| Analyst calls | **Upgrades · downgrades · re-ratings · initiations · price targets** from Moneycontrol brokerage RSS, Seeking Alpha, Benzinga, Google News |
| Price moves | % change over **5d · 24h · 4h · 1h · 15m · 5m** + RSI zone per window |
| **Price Action** | Same engine as PA screener — trend, RSI div, EMA stack, Fib golden zone, **session VWAP**, **RVOL**, **MFI**, SMC OB/FVG, Elliott/candle/chart patterns, **approaching WATCHLIST** alerts |
| S/R | Nearest **weak/strong** support & resistance · **breakout %** · **breakdown %** · bias by TF |
| **Suggested trades** | Ranked ideas with **confidence % · SL % · TP % · R:R** — TAKE / WATCH / MONITOR from PA + S/R + MTF + news + analysts |
| Strategies | Alternate **scalp / swing** setups in table form |
| Trade setup | Primary **TAKE LONG / SHORT / NO TRADE** — best blended setup with trade plan |
| Ask AI | **AI Trade Setup** (SL/TP/confidence) + full investigation synthesis |

India: optional Groww token for live intraday bars. Commodity: Yahoo Finance futures (no Groww).

---

### Ticker Investigation — Select Strategy
*id: `ticker_investigation_strategy`*

### Ticker Investigation — Select Strategy
Same as **Ticker Investigation** (Crypto · India · US · Commodity) **plus** user-selected hub strategy engines.

| Step | Action |
|------|--------|
| **1** | Pick **one or more** strategies from the dropdown (all TA hub + swing engines) |
| **2** | Enter ticker(s) in any asset tab → **Search & investigate** |
| **3** | Review news · PA · S/R · analysts · **merged** suggested trades & primary setup |

Selected engines run live `analyze_ticker` per symbol; signals merge into ranked trades alongside rule-based confluence.

---

### Stock Upgrade Downgrade — Block Deals · M&A · Analyst Calls
*id: `stock_upgrade_downgrade`*

### Stock Upgrade / Downgrade — Block Deals · M&A · Analyst Calls
Fixed site checklist per region, checked via direct RSS + `site:`-scoped news search:

| Region | Sites checked |
|--------|---------------|
| **India** | Trendlyne · Moneycontrol · ET Markets · Tickertape · CNBC-TV18 · Business Standard · LiveMint · The Hindu BusinessLine · NDTV Profit |
| **US / Global / Crypto** | TipRanks · Investing.com · Bloomberg · MarketWatch · Reuters · Yahoo Finance |

Classifies each headline into **Block Deal**, **Merger/Acquisition**, **Upgrade**, **Downgrade**,
**Target Raise/Cut**, **Re-rating**, **Initiate**, **Reiterate**, or general **Recommendation** —
ranked with corporate actions and rating changes first. **Ask AI** reconciles the feed into a
TAKE/WATCH/NO SIGNAL read.

**When to use:** Before entering/exiting a position — check for fresh corporate actions or a
brokerage rating change the price hasn't fully reacted to yet.

---

### Momentum — Multi-Timeframe Strength & Direction
*id: `momentum`*

### Momentum — Multi-Timeframe Strength & Direction
Per timeframe (1m→1w), scored independently then combined into one timeframe-weighted verdict:

| Signal | Source |
|--------|--------|
| **Trend direction** | EMA(8/21/50) stack + MACD histogram → UP / DOWN / CONSOLIDATING |
| **Strength** | **ADX(14)** — ≥25 Strong, 18–25 Medium, <18 Weak (direction-agnostic) |
| **Momentum change** | ADX's own slope — rising = Increasing, falling = Decreasing |
| **Continuation confidence** | ADX level + RSI room-to-run + MACD agreement + volume |
| **Breakout odds** | Fresh close beyond prior 20-bar high/low, scored by ADX + volume + MACD |

Groww · US · Crypto. **MIXED** verdict when timeframes disagree — confidence capped lower.

---

### Trade Setup — Oversold/Overbought Screener
*id: `trade_setup`*

### Trade Setup — Oversold/Overbought Screener
Pick tickers + timeframe(s), hit Analyze — RSI(14) computed independently per selected
timeframe (same engine as Momentum), then every ticker is bucketed **per timeframe**:

| Bucket | RSI(14) |
|--------|---------|
| 🔥🔴 **Extended Overbought** | ≥ 80 |
| 🔴 **Overbought** | 70–79.9 |
| ⚪ **Neutral** | 30–69.9 |
| 🟢 **Oversold** | 20–29.9 |
| 🔥🟢 **Extended Oversold** | < 20 |

Each timeframe gets its own tab with the bucketed ticker lists, plus a ticker × timeframe
RSI matrix for a quick cross-timeframe view. Groww India · US · Crypto · Commodities.

Expand any ticker to drill down further — tick 📈 Momentum, 📊 Volume (professional
volume-price analysis: current volume vs its 20-bar average, tiered Very Low→Very High,
cross-checked against price direction for a 🟢 Bullish / 🔴 Bearish / ⚪ Neutral bias, with
accumulation/distribution and breakout volume-confirmation notes), ⚡ Quick Analyzer,
🕯️ Candlestick/Chart Patterns (bullish/bearish reversal candles + swing-point chart
patterns including Cup and Handle and Bull/Bear Flag, each with reliability and reasoning),
🧠 Smart Money (combines TTG Sniper Entry,
CISD Entry Rule, and MTF Day Plan into one confluence verdict — TAKE only when 2+ of 3
independent SMC strategies agree), ⚡ Scalping (combines Rectangle Setup, SMC Rule of Three
[CRT-FVG], ARC Method, and A+ S/R MSS into one confluence verdict — TAKE only when 2+ of
those 4 agree), 📈 Time Series (combines MA Crossover [Golden/Death Cross], Bollinger Mean
Reversion, and Momentum Breakout into one confluence verdict — TAKE only when 2+ of the 3
agree), 🔀 Divergences (Price vs RSI and Price vs Volume [OBV] — 🟢 positive/bullish or
🔴 negative/bearish, confidence rises when both agree), 🎯 Support/Resistance (nearest
levels, approaching-within-1.5% alerts, and fresh breakout/breakdown with volume
confirmation), 🏷️ Stock Upgrade Downgrade (Block Deals · M&A · Analyst Calls),
📚 Fundamentals, and/or ⛓️ Option Chain (Fundamentals/Option Chain are Groww India/NSE only,
the rest work across all 4 markets), then **Run further analysis**
to fetch and show that ticker's read for each engine checked, without leaving the screener.

---

### Time Series Trading Strategy — MA Crossover + Bollinger + Breakout
*id: `time_series_strategy`*

### Time Series Trading Strategy — MA Crossover + Bollinger + Breakout
Combines three classic time-series-theory strategies into one confluence verdict per
ticker, computed independently **per selected timeframe**:

| Strategy | Signal | Best for |
|----------|--------|----------|
| 🌟 MA Crossover | 50-period SMA crosses the 200-period SMA (Golden/Death Cross) | Trending markets |
| 🎯 Mean Reversion | Price closes outside a 20-period SMA ± 2σ Bollinger Band | Range-bound markets |
| 🚀 Momentum Breakout | Fresh close beyond multi-bar S/R, volume-confirmed | Breakouts on conviction |

TAKE only when 2+ of the 3 agree. Pick one or more timeframes — each gets its own tab,
and results bucket into ✅ TAKE / 👀 WATCH / ⛔ NO TRADE per timeframe. Groww India · US ·
Crypto · Commodities. An interactive Moving Average simulator at the bottom lets you
manipulate MA type/period live on real price history.

---

### Divergences — Price vs RSI · Price vs Volume
*id: `divergences`*

### Divergences — Price vs RSI · Price vs Volume (OBV)
Two independent divergence checks, each comparing the last two swing lows (positive/bullish)
or swing highs (negative/bearish) in price against the same points on an indicator:

| Check | Positive (Bullish) | Negative (Bearish) |
|-------|---------------------|----------------------|
| 🎯 RSI Divergence | Price lower low, RSI higher low | Price higher high, RSI lower high |
| 📊 Volume Divergence (OBV) | Price lower low, OBV higher low | Price higher high, OBV lower high |

Bias is 🟢 Bullish when either/both checks fire positive with no conflicting bearish signal,
🔴 Bearish symmetrically, ⚪ Neutral when signals conflict or neither fires — confidence rises
when RSI and Volume divergence agree. Pick one or more timeframes — each gets its own tab.
Groww India · US · Crypto · Commodities.

---

### Candlestick & Chart Patterns
*id: `candlestick_chart_patterns`*

### Candlestick & Chart Patterns
Scans each ticker for two pattern families, the same detectors used in the Trade Setup
drill-down:

| Family | Patterns | Lookback |
|--------|----------|----------|
| 🕯️ Candlestick | Hammer, Engulfing, Marubozu, Morning/Evening Star, Three White Soldiers/Black Crows, Doji, etc. | Last ~10 bars |
| 📐 Chart | Double Top/Bottom, Head & Shoulders, Rising/Falling Wedge, Cup and Handle, Bull/Bear Flag | Full swing-point history |

Each pattern is tagged Bullish/Bearish/Neutral with a reliability rating (Moderate → Very
High). A ticker's overall bias weighs all patterns found by reliability. Pick one or more
timeframes — each gets its own tab. Groww India · US · Crypto · Commodities.

---

### Real Bottom — 5-Step Selling Exhaustion / Trap / Displacement
*id: `real_bottom`*

### Real Bottom
The 5-step mechanical sequence for identifying genuine market bottoms, adapted from Smart Money
Decode X's "How to Catch a Real Market Bottom": a chain of events institutional players leave
behind, not a single indicator. If one link breaks, the setup is invalid:

| Step | What it looks for |
|------|--------------------|
| 1️⃣ Selling Exhaustion | Heavy volume through the decline, but price stops extending sharply lower |
| 2️⃣ The Retest | Price returns toward the lows on noticeably lower volume |
| 3️⃣ The Trap | A liquidity sweep — price wicks below the floor then reverses back inside |
| 4️⃣ Displacement | A strong candle breaks the recent lower high, usually leaving a Fair Value Gap |
| 5️⃣ The Entry | A pullback into the FVG/order block, confirmed by a bullish trigger candle |

Status: 🟢 Confirmed / 🟡 Pending / 🟠 Trap Confirmed / 🔵 Trap Fired (unconfirmed) / ⚪ No Setup.
Stop-loss below the trap low, target at the next resistance. A strict, multi-stage sequence by
design — most scans return No Setup, which is the point. Groww India · US · Crypto · Commodities.

---

### Weak / Strong — Relative Strength & Trend Classifier
*id: `weak_strong`*

### Weak / Strong
Multi-factor relative-strength & trend classifier. Seven independent reads combine into one
-100..+100 score:

| Factor | Weight |
|--------|--------|
| Trend structure (HH/HL vs LH/LL) | ±20 |
| EMA stack (9/21/50) alignment | ±15 |
| ADX + DI strength & direction | ±15 |
| Volume confirmation (OBV trend + relative volume) | ±20 |
| RSI(14) momentum bias | ±10 |
| MACD histogram momentum | ±10 |
| Relative strength vs benchmark (Nifty 50 / SPY / BTC) | ±10 |

Volume is a primary confirmation signal (Wyckoff/VSA-style), not a tiebreaker: OBV trending
with price on above-average volume (RVOL ≥ 1.3x) adds full weight; OBV diverging from price
contributes nothing (a warning the move lacks real participation); any move on thin volume
(RVOL ≤ 0.7x) has its score halved regardless of direction.

Score ≥ +35 → 🟢 STRONG, ≤ -35 → 🔴 WEAK, else ⚪ NEUTRAL. Every STRONG/WEAK ticker gets a
🎯 Scalping playbook (same-timeframe 21 EMA pullback, tight ATR stop) and a 📈 Swing playbook
(Daily 50 EMA pullback, wider structural stop, multi-day/week hold) — both aligned with the
verdict's direction; never fight strength or weakness. Choose one or more timeframes and one
or more tickers per scan. India · US · Crypto.

---

### Copy Trade — High-Beta / 3x Leveraged ETF Momentum Scalp
*id: `copy_trade`*

### Copy Trade
High-beta / 3x leveraged ETF momentum scalp, fixed 15m timeframe:

| Step | What it looks for |
|------|--------------------|
| Trend "sweet spot" | Stochastic %K breaks above 80 (long) or below 20 (short) |
| Volume confirmation | Current bar's volume above its 20-bar average |
| Trigger candle | Fresh Engulfing candle (Bullish for longs, Bearish for shorts) |

Exit rule is hyper-conservative: exit the instant %K stops extending (pullback in momentum) —
never wait for a stop-loss to be hit. Re-enter on a fresh engulfing candle a few bars later if
the zone/trend is still intact. Phases: NO_SETUP / WATCHING_ZONE / ENTRY_TRIGGERED / EXIT_SIGNAL
(the last one flags a pullback-exit cue for an assumed open position, not a new entry).
Suggested universe: TQQQ, SQQQ, LABU, LABD, SOXL, SOXS, TNA, TZA. India · US · Crypto.

---

### Stop Loss Hunting
*id: `stop_hunt`*

### Stop Loss Hunting
Detects whether a liquidity sweep (stop hunt) is active or likely, and recommends
hunt-resistant stop-loss levels:

| Check | What it looks for |
|-------|--------------------|
| 🎣 Sweep/grab detection | Wick-based rejection through the prior swing high/low, closing back inside range |
| 📊 Weak vs strong S/R | Touch-count classification — weak (1-2 touches) levels are hunt magnets |
| 🔢 Round-number proximity | Levels near clean numbers attract extra stop clustering |

Status: 🎣 Active Sweep Detected / ⚠️ High Hunt-Risk Zone / 🟢 Low Hunt-Risk. For each ticker,
two-tier stop recommendations (🎯 Tight/Aggressive and 🛡️ Safe/Hunt-Resistant) are given for
both LONG and SHORT scenarios, in price and % from current price, ATR-scaled by how weak the
anchor level is and nudged clear of round numbers. Groww India · US · Crypto · Commodities.

---

### Take Profit Targets
*id: `take_profit`*

### Take Profit Targets
Combines four independent target methods into two-tier take-profit levels for both a LONG and
a SHORT scenario:

| Method | What it looks for |
|--------|--------------------|
| 📊 Weak vs strong S/R | Nearest S/R level in the profit direction, tagged by touch count |
| 📐 Chart-pattern measured move | Any detected pattern's own structure-derived price projection |
| 🌀 Fibonacci extension | 127.2% / 161.8% / 261.8% projections of the most recent swing |
| 🎯 SMC liquidity draw | The opposite-side structural liquidity pool ("draw on liquidity") |

Status: 🎯 High-Confluence / 📍 Moderate-Confluence / 🌫️ Low-Confluence. For each ticker, two-tier
targets — 🎯 TP1 (Conservative, booked slightly ahead of the exact level) and 🚀 TP2 (Extended,
always farther than TP1) — in price and % from current price. Groww India · US · Crypto · Commodities.

---

### Take Trade — All Trade Setup Analyses Combined
*id: `take_trade`*

### Take Trade
Runs every analysis already offered as a Trade Setup checkbox (momentum, quick analyzer,
candlestick/chart patterns, smart money, scalping, time series, divergences, S/R, stock
upgrade/downgrade, fundamentals, option chain) for one ticker/timeframe, and combines up to 11
independent votes into one composite call:

| Bucket | Meaning |
|--------|---------|
| 🟢 BUY | Composite direction is LONG |
| 🔴 SELL | Composite direction is SHORT |
| ⚪ WAIT | No real agreement among the independent analyses |

Each BUY/SELL gets a **TAKE** (4+ analyses agree, composite confidence clears the take threshold)
or a lower-conviction **WATCH** verdict, with a confidence %, and a stop-loss + take-profit — each
in price and % — pulled from the Stop Loss Hunting and Take Profit Targets sections. A per-
analysis vote breakdown and AI View are shown for every ticker. Groww India · US · Crypto ·
Commodities.

---

### Trading Playbook — Scalping · Intraday · Swing
*id: `playbook`*

### Trading Playbook — Scalping · Intraday · Swing
A static reference, not an engine — grounded in a direct read of ~55 strategy engines' actual entry
mechanisms across this app, not just their titles. Maps which Command Center sections to use for
each trading style: what to screen candidates with, which composite engine to enter on, a curated
"also in the toolkit" shortlist of genuinely distinct specialized engines per style (e.g. Velez
Retracement's fade-the-exhaustion scalp, SMC Fake Market Shift's liquidity-sweep intraday reversal,
Weekly Stochastic Sweet Spot for swing), which Stop Loss Hunting / Take Profit Targets tier to use,
and what to explicitly leave alone. Also covers cross-style tools (MTF Scanner, Global Market Mood,
Mega Analyser, portfolio-level hedging) that don't belong to one style. Closes with six discipline
rules that hold across all three — strictness defaults, reading the vote breakdown before sizing,
structure-anchored stops over flat %, inverse position sizing by holding period, AI View as a
second opinion, and treating most of the remaining tabs as differently-branded variants of a
handful of ideas rather than distinct edges.

---

### 200SMA-20SMA — Bounce & Rejection
*id: `sma_20_200`*

### 200SMA–20SMA — Bounce & Rejection

Uses the **200 SMA** as the institutional trend floor/ceiling and the **20 SMA** as the near-term
mean. Scans for:

- **Bounce** — price tags the 200 SMA from above in an uptrend and reclaims the 20 SMA
- **Rejection** — price fails at the 200 SMA from below in a downtrend and rolls under the 20 SMA

**When to use:** Swing / positional timing after a pullback into the 200 SMA. Pair with Momentum
or Weak/Strong for confirmation.

---

### Mutual Fund Holdings — Stock-Level Trend Across Funds
*id: `mutual_fund_holdings`*

### Mutual Fund Holdings — Stock-Level Trend Across Funds
Browse AMC → equity schemes → track domestic-equity stock holdings (%) over a date range:

| Step | Rule |
|------|------|
| **Load AMCs** | Full list of Indian mutual fund houses (AUM, scheme count) |
| **Pick fund(s)** | Select-all/clear-all checkbox per AMC table, across one or more AMCs |
| **Date range** | Snapped to month-end snapshots — fund disclosures are monthly |
| **Per stock** | Holding % at first vs last snapshot → Increasing / Decreasing / Mixed per fund |
| **Sector-wise** | Same trend on sector weights (sum of stock holding % in each sector) |
| **Chart** | One line per fund, per stock or sector, over the snapshot dates |

**When to use:** See whether one or more mutual funds are building or trimming a position.

---

### ETF Holdings — Stock-Level Trend Across Funds (India · US · Crypto)
*id: `etf_holdings`*

### ETF Holdings — Stock-Level Trend Across Funds (India · US · Crypto)
ETF analogue of Mutual Fund Holdings — same stock-level holding-% trend idea, per market:

| Market | Source | Flow |
|--------|--------|------|
| **🇮🇳 India** | StockEdge ETF schemes | Load AMCs → **Get ETF funds** → date range → month-end holdings |
| **🇺🇸 US** | INDMoney US ETFs | Load categories → pick ETF(s) → Companies / Holding % from each ETF page |
| **₿ Crypto** | SEC NPORT-P crypto-theme equity ETFs | Same issuer → ETF flow with historical reporting periods |

**Results:** **Stock-wise** and **Sector-wise** tabs (sector weights = sum of stock holding %).

**When to use:** See whether ETFs are building or trimming the same stock / sector across funds over time.

---

### India FII-DII Holding — Ownership · P&L · Valuation · Deals
*id: `india_fii_dii_holdings`*

### India FII-DII Holding — Ownership · P&L · Valuation · Deals
Scrapes screener.in for one or more NSE tickers over a date range — seven result tabs:

| Tab | What it shows |
|-----|----------------|
| **Overview** | Combined invest-timing table across tickers |
| **Ownership** | Promoters / FII / DII / Public % — Increasing / Decreasing / Stable + charts |
| **Revenue & Profit** | Quarterly Sales & Net Profit direction in your From/To window + charts |
| **Valuation** | Is P/E justified vs ROCE? Undervalued / Fair / High / Overvalued (+ industry P/E when available) |
| **Invest Timing** | YES / WAIT / NO checklist combining ownership + P&L + valuation + deals |
| **Deals & Expansion** | Recent announcements keyword-flagged as orders, deals/M&A, capex/expansion |
| **Actions** | News, orders, deals, block/bulk mentions, upgrades/downgrades, analyst reco, credit ratings, concalls (screener Documents) |
| **How to read** | Plain-English guide for every signal |

**When to use:** Before a swing/positional entry — ownership, business momentum, valuation, and catalyst headlines in one place.

---

### Next Day Move — Smart Money vs Retail (India · US · Crypto)
*id: `next_day_move`*

### Next Day Move — Smart Money vs Retail (India · US · Crypto)
Fade retail when it leans against smart money — Amit Dhamija participant-wise OI framework
([video](https://www.youtube.com/watch?v=65_-M-icfK0&t=1360s)):

| Market | Data | Retail | Smart money | Horizon |
|--------|------|--------|-------------|---------|
| **🇮🇳 India** | NSE `fao_participant_oi` daily | Client | FII + Pro | Next session |
| **🇺🇸 US** | CFTC Legacy COT | Non-reportable | Non-commercial | Until next weekly report |
| **₿ Crypto** | Binance global vs top-trader L/S + funding | Global accounts | Top traders | Next ~24h |

**Bias:** Retail bullish + smart bearish → Sell on rise · Retail bearish + smart bullish → Buy on dips · else conflicting/range.

**When to use:** After India F&O close (~evening) for the next NSE session; weekly for US; anytime for crypto.

---

### Detect Sector Rotation — CRS · Hull · Pullback (India · US · Crypto)
*id: `detect_sector_rotation`*

### Detect Sector Rotation — CRS · Hull · Cyclical Pullback (India · US · Crypto)
[Video](https://www.youtube.com/watch?v=IfMDd2XlArU&t=123s) top-down weekly rotation detector:

| Step | Rule |
|------|------|
| **1. Pullback setup** | Sector negative for 2–3 consecutive months (or quarters) |
| **2. CRS trigger** | Sector÷Benchmark RS line **above** its 50-week SMA |
| **3. Hull confirm** | Sector close **above** HMA(9) — absolute uptrend |
| **BUY / ROTATE IN** | Steps 2 + 3 true (higher conviction with pullback / fresh CRS cross) |

🇮🇳 Nifty sectors vs Nifty 50 · 🇺🇸 SPDR ETFs vs SPY · ₿ CoinDCX themes vs BTC.
Each sector row also lists **linked ETFs** and **top 20 stocks** (index weight / SPDR holdings / crypto theme peers).

---

### EMA Position — Crossovers, Status & Next S/R
*id: `ema_position`*

### EMA Position — Crossovers, Status & Next S/R
For one or more tickers, one or more timeframes, across a **from → to** date range:

| Signal | Rule |
|--------|------|
| **EMAs tracked** | 5 · 9 · 20 · 50 · 200, with ~400 bars of warm-up before "from" date |
| **Status@From / Status@To** | ABOVE or BELOW each EMA at each end of the range |
| **Verdict** | Crossed Above / Crossed Below (flipped) vs Stayed Above / Stayed Below |
| **Crossover count** | How many times price crossed that EMA in the range (clean vs choppy) |
| **Next S/R** | Nearest swing-based support/resistance below/above latest close |

Groww · US · Crypto. Candlestick chart per ticker/timeframe with ▲/▼ crossover markers.

---

### Fundamental Analysis — Valuation · Holdings · Profit & Revenue Trend (India)
*id: `fundamental_analysis`*

### Fundamental Analysis — Valuation · Holdings · Profit & Revenue Trend (India)
Scrapes screener.in's public company page — no login required:

| Signal | How it's derived |
|--------|-------------------|
| **Valuation** | P/E ÷ ROCE ratio — near 1.0 is fair; well below is attractive; well above is rich/expensive |
| **Shareholding trend** | Promoter / FII / DII / Public % change over the last ~4 quarters (~12 months), with implication |
| **Profit & Revenue** | Screener's own **TTM** compounded growth, plus 3/5/10-year CAGR context |
| **Debt** | Borrowings trend from the balance sheet (Increasing / Decreasing / Debt-free) |
| **Overall signal** | Point-scored across valuation, growth, holdings, debt, and screener's own Pros/Cons checklist → BULLISH / NEUTRAL / BEARISH with confidence % |

**When to use:** Before a swing/positional entry — sanity-check the business fundamentals behind a technical setup.

---

### One-Click Trade Setup — Scalping · Intraday · Swing (Multi-Engine Confluence)
*id: `one_click_setup`*

### One-Click Trade Setup — Scalping · Intraday · Swing (Genuine Multi-Engine Confluence)
Combines a small, deliberately curated set of **structurally-independent** existing engines
per style — not many indicator variants of the same idea — and only calls a trade when they
independently agree:

| Style | Combines | Take rule |
|-------|----------|-----------|
| **Scalping** | CRT-FVG sweep + HTF S/R zone/1m MSS, session kill-zone, RVOL, Momentum (1m/5m/15m/1h) | Both liquidity detectors agree (strict) or ≥1 (loose) |
| **Intraday** | Weighted MTF bias + regime-routed breakout-retest (trending days only), Momentum confirms regime + strength | Bias agrees with the regime-appropriate trigger |
| **Swing** | Weekly KISS bias + weekly PWH/PWL liquidity-grab/MSS, SuperTrend trailing stop, measured-move TP2, Momentum (1h/4h/1d/1w), fundamentals gate (India) | Both directional votes agree; fundamentals can downgrade a contradicted call |

**Momentum — Multi-Timeframe Strength & Direction** is used in all three styles as a
**non-voting confidence adjuster** (never a third direction vote, to avoid double-counting
the same trend information) — timeframe-matched per style and boosting/penalizing confidence
based on whether its trend direction + ADX strength agree with the combo's direction.

**Strictness toggle:** *Fewer/High Quality* requires more engines to agree and hard-gates on
regime/session filters; *More/Lower Quality* relaxes both — trades trade frequency for quality.

**Risk model:** two-stage partial take-profit — TP1 books half the position at ~1:1 and moves
the stop to breakeven (caps the loss), TP2 is a further structural/measured-move runner target.

**Backtest panel:** validates a simplified daily-bar proxy of each style's core trend+trigger
logic (win rate, profit factor, max drawdown, equity curve) before you trust the live scan.

**When to use:** As a second opinion before entering — the per-engine vote breakdown shows
exactly which independent signals agree/disagree, so it's never a black box.

---

### One-Click Intraday Setup
*id: `one_click_intraday`*

### One-Click Intraday Setup

Runs the intraday multi-engine confluence pack (opening-range / VWAP / MTF bias engines) and
returns ENTRY_READY / WATCH setups for the current session.

**When to use:** 9:45–11:30 IST when you want a fast shortlist without configuring each scanner.

---

### One-Click Scalping Setup
*id: `one_click_scalping`*

### One-Click Scalping Setup

Aggregates scalping hub engines (rectangle, ARC, CRT-FVG, LiveFree, Heikin Ashi, etc.) into one
ranked list for LTF entries.

**When to use:** Liquid names during kill-zones when you want confluence across scalp playbooks.

---

### One-Click Swing Setup
*id: `one_click_swing`*

### One-Click Swing Setup

Aggregates swing hub engines (capitulation, MSS, SuperTrend, KISS, HA+EMA, Simple Steal) into one
ranked multi-day shortlist.

**When to use:** EOD / weekend planning for positional entries.

---

### Mega Setup Advisor — multi-engine confluence pick
*id: `mega_setup_advisor`*

### Mega Setup Advisor — multi-engine confluence pick

Ranks tickers by how many independent engines (TA screeners + hub strategies) agree on the same
direction / phase. Surfaces the **highest-confluence** setups with a compact trade plan.

**When to use:** After Mega Analyser or a multi-section morning scan — narrow to the 3–5 best
ideas instead of reading every engine separately.

---

### Today's Indian Tickers — Live Market Movers (Dhan.co)
*id: `todays_indian_tickers`*

### Today's Indian Tickers — Live Market Movers (Dhan.co)
Six one-click buttons, each pulled directly from Dhan.co's live market-mover pages:

| Button | What it shows |
|--------|----------------|
| 📈 Top Gainers | Biggest % gainers today (NSE) |
| 📉 Top Losers | Biggest % losers today (NSE) |
| 🚀 52-Week High | Stocks trading at/near their 52-week high |
| 🔻 52-Week Low | Stocks trading at/near their 52-week low |
| 💰 Most Active by Value | Highest ₹ turnover today |
| 📊 Most Active by Volume | Highest share volume today |

Each row includes P/E, industry P/E, ROE/ROCE, dividend yield, and 1w/1m/1y returns — so a
big mover can be immediately sanity-checked against its underlying fundamentals rather than
taken at face value. Data is a live snapshot, cached for 15 minutes.

**When to use:** A fast daily scan for what's moving and why — pair with Fundamental Analysis
or One-Click Trade Setup before acting on any single name.

---

### Option Chain — Bias, PCR & Trade Signal (NSE)
*id: `option_chain`*

### Option Chain — Bias & Trade Signal (NSE)

Pick an **Index** (Nifty, Bank Nifty, FinNifty, Midcap Nifty) or a **Stock**, hit
**Analyze Option Chain**, and get the full nearest-expiry chain (NSE v3 API, Groww
fallback) plus a scored bullish/bearish/neutral read:

| Metric | What it means |
|--------|----------------|
| **PCR (OI)** | Put OI ÷ Call OI. High = more puts written = bullish tilt; low = bearish tilt |
| **Max Pain** | Strike where option writers profit most — price tends to drift toward it into expiry |
| **Support / Resistance** | Highest-OI Put strike (support) / highest-OI Call strike (resistance) |
| **Fresh OI buildup** | Which side (calls vs puts) added more OI today |

These four factors combine into a scored **Bullish / Bearish / Neutral** bias with a
**Buy / Sell / Wait** suggestion and a confidence %, each backed by a plain-English reason —
never a black box. Full strike-by-strike chain and top-5 Call/Put OI tables are shown for
verification.

**When to use:** Before any F&O trade — confirm the technical direction isn't fighting
heavy OI positioning on the other side. Pair with **Ticker Investigation** or **One-Click
Trade Setup** for a non-options confirmation before acting. Also pair with
**Advance Decline (Multi Asset)** on the same index for breadth + PCR confluence.

---

### Option-Short-Long — OI Buildup · Premium/Discount · Buy/Sell Call/Put (NSE)
*id: `option_short_long`*

### Option-Short-Long — OI Buildup · Premium/Discount · Buy/Sell Call/Put (NSE)

Reads NSE option-chain **open interest** buildup / unwinding, call vs put **premium vs discount**
to underlying, and surfaces **Buy Call / Buy Put / Sell Call / Sell Put** bias with PCR context.

**When to use:** NSE F&O names around event days or when spot is stuck at S/R — OI tells you
whether the move is being supported or faded by dealers.

---

### Quick Analyzer — Momentum + EMA + Technical Indicators (India)
*id: `quick_analyzer`*

### Quick Analyzer (India)

Combines these reads into one table, per ticker, every one computed independently **per
selected timeframe** from that timeframe's own OHLCV:

| Component | Detail |
|-----------|--------|
| **Momentum** | Trend, strength (ADX), RSI, MACD, ROC — same engine as the Momentum section |
| **Volume** | Volume vs its 20-bar average |
| **EMA / SMA + oscillators** | 5/10/20/50/100/200-period EMA/SMA, RSI, Stochastic, MACD, ADX, ROC, Williams %R |
| **Bollinger Bands (20, 2σ)** | Position vs upper/mid/lower band |
| **Fibonacci retracement** | Auto swing high/low, golden-zone bounce read |
| **EMA Crossover strategy** | 9/21, 20/50, 50/200 stack + recent cross events |
| **VWAP** | Price vs volume-weighted average price |
| **Price Action** | The most **critical** (highest-reliability) recent candlestick pattern, not just the latest one |
| **RSI / MACD Divergence** | Bullish/bearish divergence vs the last two swing highs/lows, with a plain-English trade interpretation |
| **S/R Breakout/Breakdown** | Support/resistance computed on prior bars, checked against the latest close for a breakout/breakdown, with volume confirmation |

**Flow:** Pick an Index/Group → pick one or more tickers → pick a **From/To date range** → pick
one or more timeframes → **Analyze**. Each row's combined **Trade Setup** (Long/Short/Neutral +
confidence %) weighs a strong (ACTIONABLE) momentum read more heavily, then confirms or
discounts it against how many of the EMA/oscillator/strategy reads agree **across the
timeframes you picked** — including any divergence or breakout/breakdown signals, which are
also called out explicitly in the setup's reasons. When a **Long** or **Short** fires, **%SL /
%TP** are shown too (ATR-based stop on the finest selected timeframe, fixed 1:2 R:R target). A
separate **Daily reference (Dhan.co)** table is shown per ticker for cross-checking — Dhan's
technical-analysis page has no timeframe selector, so that read is always daily and isn't fed
into the score.

**Charts:** OHLCV is fetched for the picked date range (plus a warm-up buffer so the largest
EMA is meaningful from day one of the visible window) — each timeframe tab shows a 4-panel
chart: price + EMA20/50/200 + Bollinger Bands + VWAP, Volume (green/red bars vs its 20-bar
average), RSI(14), and MACD(12,26,9), all over that period, not just the latest bar.

**When to use:** A fast, single-table screen across an index's constituents before drilling
into individual sections (Momentum, EMA Position, Fundamental Analysis) for deeper confirmation.

---

### Quick Analyzer Crypto — Momentum + EMA + Technical Indicators (CoinDCX)
*id: `quick_analyzer_crypto`*

### Quick Analyzer Crypto (CoinDCX)

Identical model to **Quick Analyzer** (Momentum + Volume + EMA/oscillators + Bollinger Bands +
Fibonacci + EMA Crossover + VWAP + critical Price Action pattern + RSI/MACD Divergence +
S/R Breakout/Breakdown, all computed independently per selected timeframe over a picked
**From/To date range**, with a 4-panel chart — price, Volume, RSI, MACD — per timeframe)
applied to CoinDCX USDT-margined pairs instead of Indian stocks.

**Flow:** Pick one or more pairs → pick a date range → pick one or more timeframes →
**Analyze** → combined **Trade Setup** (Long/Short/Neutral + confidence %) with **%SL/%TP**
on any Long/Short.

**Difference from the India version:** no Dhan.co daily-reference table (that source only
covers Indian large/mid-caps) — the score here comes purely from the per-timeframe technical
computation.

---

### Quick Analyzer US — Momentum + EMA + Technical Indicators (Yahoo)
*id: `quick_analyzer_us`*

### Quick Analyzer US (Yahoo)

Identical model to **Quick Analyzer** (Momentum + Volume + EMA/oscillators + Bollinger Bands +
Fibonacci + EMA Crossover + VWAP + critical Price Action pattern + RSI/MACD Divergence +
S/R Breakout/Breakdown, all computed independently per selected timeframe over a picked
**From/To date range**, with a 4-panel chart — price, Volume, RSI, MACD — per timeframe)
applied to US-listed stocks via Yahoo Finance instead of Indian stocks.

**Flow:** Pick an Index/Group → pick one or more tickers → pick a date range → pick one or
more timeframes → **Analyze** → combined **Trade Setup** (Long/Short/Neutral + confidence %)
with **%SL/%TP** on any Long/Short.

**Difference from the India version:** no Dhan.co daily-reference table (India-only coverage)
— the score here comes purely from the per-timeframe technical computation.

---

### NSE and World Indices
*id: `nse_world_indices`*

### NSE and World Indices

Three one-click buttons:

| Button | What it shows | Source |
|--------|----------------|--------|
| 📥 Load NSE Indices | All ~119 NSE indices — Nifty 50, sectoral, thematic, strategy indices | Dhan.co |
| 🌍 Load Global Indices | Major world indices — US, Europe, Asia | Dhan.co |
| 🚀 Load Futures | US & Europe index futures + GIFT Nifty (formerly SGX Nifty) | investing.com · 5paisa |

**NSE Indices** table: Index Name, LTP, trend arrow, Change %, Open, Prev. Close, 52W High,
52W Low, and 1Y/3Y/5Y returns — a quick read on which timeframes an index is winning/losing on.

**Global Indices** table: Index Name, LTP, Change, Change %, trend arrow, Open, Prev. Close,
Day High, Day Low.

**Futures**: GIFT Nifty as a headline metric card (LTP, change, day/52-week range, open, prev
close, 1W/1M/1Y returns) — the primary pre-market read for where NSE will open — plus separate
US and Europe index futures tables (Name, LTP, Change %, Day High/Low, last update time).

**When to use:** Pre-market or intraday — check overnight US/Europe futures and GIFT Nifty
for where Indian markets are likely to open, alongside where Indian sectoral/thematic indices
stand on both short (today) and long (1Y/3Y/5Y) horizons, before picking a sector or
index-linked trade.

---

### IN-US-Crypto Market Heatmap — Index/Sector Constituent Heatmap
*id: `india_market_heatmap`*

### Indian Market Heatmap / IN-US-Crypto Market Heatmap

Pick an index or sector universe (India NSE/BSE, and where enabled US / Crypto), hit **Submit**,
and see every constituent as a green/red heatmap tile.

- 🟩 **Green** = positive % change, 🟥 **Red** = negative — intensity scales with the move.
- Each tile shows the ticker, name, last price, and % change.
- Summary strip: constituents, gainers, losers, unchanged.

**When to use:** Visual breadth inside one universe. Pair with **Advance Decline** for quantified
A/D ratios and (on India F&O indices) options PCR.

---

### Advance Decline (Multi Asset) — Breadth + Options PCR
*id: `advance_decline_graph`*

### Advance Decline (Multi Asset) — Breadth + Options

Reconstructs **advances / declines / unchanged** for an index universe from constituent OHLCV
(NSE does not publish a historical A/D API). Works across **India · US · Crypto**.

| Mode | What you get |
|------|----------------|
| **Daily** | Per session: A/D ratio, volume ratio, cumulative A/D line, trend, strength, RSI |
| **Intraday** | Same metrics per bar inside local session hours (IST / ET / UTC) until optional as-of time |

**How to read**

| Signal | Meaning |
|--------|---------|
| **A/D ratio > 1** | More stocks rose than fell |
| **Volume ratio > 1** | More stocks got busier (volume up) than quieter |
| **UPTREND + rising strength** | Breadth improving and decisive |
| **RSI** | Internals hot (>60) or washed out (<40) |
| **Healthy advance** | A/D > 1 **and** volume ratio > 1 **and** uptrend |
| **Hollow rally** | A/D > 1 but volume ratio < 1 (price up without participation) |

**India options snapshot (automatic on F&O indices)**

For **NIFTY 50 · NIFTY BANK · FINNIFTY · MIDCPNIFTY · NIFTY NEXT 50**, the same run attaches:

- PCR (OI) & PCR (Volume)
- Total Call / Put OI
- Max pain
- OI support / resistance (highest Put OI / Call OI strikes)
- Bias · trade signal · confidence

**Universes:** India Nifty family · US Dow/Nasdaq/S&P (capped) · Crypto Top 30/50/100 / Majors.

**AI View:** Asks whether the advance is healthy or hollow given breadth **and** options (when present).

**When to use:** Pre-market / mid-session breadth check; F&O confluence with Option Chain;
confirm Comparative Strength leaders aren't riding a hollow tape.

**When to use:** Morning or session check that an index rally/selloff is broad-based.
India F&O indices also show PCR — use when deciding if breadth and options positioning agree.

---

### Comparative Strength — Relative Long/Short vs Base
*id: `comparative_strength`*

### Comparative Strength — Relative Long / Short vs Base

Pick a **base** (index or ticker) and one or more **compare** symbols. The scan ranks who is
**stronger / weaker / inline** vs the base by relative % return over a lookback, then suggests
LONG / SHORT leans with confidence.

| Concept | Meaning |
|---------|---------|
| **Relative strength %** | Peer return − base return (positive = peer beat the base) |
| **Confidence** | Blend of RS size, multi-horizon agreement, CRS slope, EMA stack, volume |
| **Trade ideas** | Relative long leaders / short laggards vs the base |

**Asset classes:** India · US · Crypto · Commodity. Presets load common bases (Nifty 50, SPY, BTC, …).
**Timeframes:** 1m → 1w. Runs can execute in the background like other heavy Command Center scans.

**How to use with Advance Decline**

1. Confirm breadth is healthy on the base universe (Advance Decline).
2. Run Comparative Strength vs that base.
3. Prefer LONG ideas only when breadth + RS agree; prefer SHORT ideas when breadth is weak and peers lag further.

**AI View:** Default question picks the best relative long/short risk/reward and invalidation.

**When to use:** Pairs / relative value, sector vs index, crypto majors vs BTC, stock vs SPY.
Educational lean only — not a broker order ticket.

**When to use:** Pair trades and relative longs/shorts — who is beating the base (Nifty / SPY / BTC) over the lookback.

---

### Oil · Dollar · Bond — Macro Tape · Metals · Indices · Crypto
*id: `oil_dollar_bond`*

### Oil · Dollar · Bond — Macro Tape

Command Center (and **Dashboard**) macro panel for:

| Instrument | Typical Yahoo symbol |
|------------|----------------------|
| US Dollar Index | DX-Y.NYB |
| Brent Crude | BZ=F |
| US 2Y / US 10Y | ^UST2Y / ^TNX (futures fallbacks) |
| Gold / Silver | GC=F / SI=F |
| Nifty 50 · Dow 30 · Nasdaq | ^NSEI · ^DJI · ^IXIC |
| Bitcoin · Ethereum | BTC-USD · ETH-USD |

**Modes**

| Mode | Controls |
|------|----------|
| **Daily** | From / To date range → 1d bars |
| **Intraday** | One session date + 1m / 5m / 15m / 30m / 1h |

Each instrument chart draws **S1/S2 (support)** and **R1/R2 (resistance)** from swing pivots in the window.
A normalized **% change overlay** compares direction across units (no S/R on the overlay).

**AI Predictor — Next Move:** RISK-ON / RISK-OFF / MIXED / WAIT with per-instrument UP/DOWN/FLAT leans.

**When to use:** Morning or overnight macro regime; pair with Advance Decline + Comparative Strength before equity size.

**When to use:** Macro regime read — DXY vs oil/metals/yields plus Nifty/Dow/Nasdaq and BTC/ETH.
Daily or same-day intraday with S/R on every panel; AI next-move for RISK-ON / RISK-OFF / MIXED.
Also available on the **Dashboard**.

---

### MTF Trend and Strength — Multi-TF Trend Stack
*id: `mtf_trend_strength`*

### MTF Trend and Strength

Scores trend direction and strength across multiple timeframes for a ticker list
(asset class: India · US · Crypto · Commodity).

Use when you need **alignment** (e.g. 1d up + 1h up + 15m pullback) before taking a directional
setup from Trade Setup, Take Trade, or One-Click styles.

**When to use:** Confirm trend alignment across multiple timeframes before sizing a directional trade.

---

### Market Movers — Index Gainers/Losers · Multi-Asset
*id: `market_movers`*

### Market Movers

Index / universe gainers and losers across **India · US · Crypto · Commodity** with timeframe
selection. Fast tape of what is moving today — pair with Fundamental Analysis or One-Click
before acting on any single name.

**When to use:** Quick scan of index gainers/losers across India / US / Crypto / Commodity universes.

---

### Check Smart Money Activity — Institutional Footprints
*id: `smart_money_activity`*

### Check Smart Money Activity

Surfaces institutional / smart-money style footprints on selected tickers (activity, positioning
context). Use as a confirmation layer after breadth (Advance Decline) and relative strength
(Comparative Strength), not as a standalone entry trigger.

**When to use:** Check institutional / smart-money footprints on a watchlist before committing to a setup.

---

### 24Hrs Volatile Crypto — CoinDCX Futures Heatmap
*id: `coindcx_24h_volatility`*

### 24Hrs Volatile Crypto

Every CoinDCX USDT-margined futures pair as a green/red heatmap tile, ranked from the
**biggest 24h gainer to the biggest 24h loser** — sourced live from CoinDCX's derivatives
instrument API (a single call returns `change_24_hour` for the whole exchange).

- 🟩 **Green** = positive 24h % change, 🟥 **Red** = negative — tile color intensity scales
  with the size of the move (crypto moves are scaled to ±15% for full color range, vs ±6%
  for equities, since crypto routinely moves much more in a day).
- Each tile shows the pair, 24h % change, 24h high, 24h low, and 24h volume.
- **Show top N** limits the grid to the top N by % change; **Refresh** bypasses the 60-second cache.
- The advances/declines summary and A/D ratio are computed across the **full** universe, not just
  the tiles currently shown.

**When to use:** A fast visual scan of the whole CoinDCX futures universe for what's moving —
pair with **Buy or Sell** or **Ticker Investigation** (Crypto) before acting on any single pair.

---

## 📊 Market Pulse

### News Scanner & Market Intelligence
*id: `news_scanner`*

### News Scanner and Market Intelligence
Live global and India market board with institutional-style context.

- Markets: Yahoo + Gift Nifty
- NSE flows: FII/DII, turnover, delivery, breadth
- Options: PCR, max pain, OI walls
- News: Moneycontrol-heavy RSS, **96h freshness**
- Analyst calls: brokerage recos and stock ideas
- Events: macro calendar, **future dates only (IST)**
- AI summary: Gemini/Groq over full payload

Click **Refresh Market Data** — not auto-fetched on every load.

---

### Nifty Index Breadth
*id: `nifty_breadth`*

### Nifty Index Breadth
Advances / declines / unchanged for major Nifty indices with S1-S2 / R1-R2 on each.

Use to confirm broad participation vs narrow index leadership. Refresh after selecting indices.

---

### Nifty 1-Month Performance
*id: `nifty_monthly`*

### Nifty 1-Month Performance
Rolling ~21 trading-day performance for Nifty indices and top constituent movers.

Shows index return vs period range and leader/lagger tables for relative strength ideas.

---

### Nifty Gainers & Losers
*id: `nifty_gainers_losers`*

### Nifty Gainers and Losers
Top 10 constituents by % change for chosen Nifty indices.

Quick read on what is moving the index today. Pair with Sector Rotation.

---

### Gainers & Losers — Multi-Market
*id: `market_gainers_losers`*

### Gainers & Losers — Multi-Market
Top **10** gainers and **10** losers per selected **index × timeframe**:

| Market | Universes |
|--------|-----------|
| **India** | Any Nifty index constituents (NSE live for session) |
| **US** | S&P 500, Nasdaq 100, Dow 30, Russell 2000, etc. |
| **Crypto** | CoinDCX USDT groups or full universe |
| **Commodities** | Futures + correlated US / Nifty names |

Loads **10 sections per click**. Pick multiple timeframes (5m → 1M).

**When to use:** Quick scan of top gainers/losers across India, US, crypto, commodities on multiple timeframes.

---

### Stock Price Rotation — index constituents
*id: `stock_price_rotation`*

### Stock Price Rotation
Ranks **index constituents** by return over a chosen **candle interval** (1m → 1M) and **lookback window**, vs the index benchmark.

| Step | Action |
|------|--------|
| 1 | Pick a Nifty index |
| 2 | Subset constituents (optional) |
| 3 | Set interval + duration → **Analyse** |

Top = rotating in (outperforming index); bottom = rotating out. Use for relative-strength stock picks within a sector/theme index.

---

### US Stock Price Rotation
*id: `stock_price_rotation_us`*

### US Stock Price Rotation
Ranks **US index constituents** (S&P 500, Nasdaq 100, Dow 30, Russell 2000, etc.) vs the matching **ETF benchmark** (SPY, QQQ, DIA, IWM…).

Same workflow as India: pick index → subset tickers → interval + lookback → **Analyse**. Data via **Yahoo Finance**.

---

### Crypto Price Rotation — CoinDCX
*id: `stock_price_rotation_crypto`*

### Crypto Price Rotation (CoinDCX)
Ranks **CoinDCX USDT perpetual** pairs within a bucket (Major L1, DeFi, Meme, custom) vs **BTC**.

Session day starts at **00:00 New York (ET)** — day lookbacks and **1d** bars align to the NY calendar. Use to spot alt-season leadership or BTC-relative laggards.

---

### Commodity Screener — buy / sell · Nifty indices
*id: `commodity_screener`*

### Commodity Screener — Buy / Sell Signals
Tracks **WTI, Gold, Silver, Natural Gas, Copper, Wheat, Iron Ore** (Yahoo Finance) across **15 mins · 1 hr · 4 hrs · 1 day → 3 months**.

| Output | Meaning |
|--------|---------|
| Commodity consensus | Majority **BUY** / **SELL** / **NEUTRAL** across selected durations |
| Commodity futures | Direct **LONG** / **SHORT** on CL=F, GC=F, … with **confidence %**, **SL %**, **TP %** |
| Nifty / Crypto / US | Correlated ideas with the same risk fields |

Use for **macro thematic tilt** and cross-asset ideas when commodities move beyond the min threshold.

---

### Accurate Strategy — OB + FVG + S/R confluence
*id: `accurate_strategy`*

### Accurate Strategy — Zireman-style Confluence
**Market Pulse** section combining three ranked zone detectors into one confluence engine:

| Layer | Detector |
|-------|----------|
| Order Blocks | Last opposite candle before ATR displacement (volume + EMA scored) |
| FVG | 3-candle imbalance gaps with buy/sell pressure % |
| S/R | Clustered swing pivots by touches + recency |

**Signal:** price first retests a ranked OB or FVG **and** same-direction S/R overlaps → LONG/SHORT with stop beyond zone, target at configured R:R.

| Output | Use |
|--------|-----|
| Latest setup | Entry · stop · target · confluence % · SL%/TP% |
| Zone tables | Top-ranked OB / FVG / S/R on loaded window |
| Backtest | Win rate on historical window (one position at a time) |

Expand **Strategy explanation** for full methodology. Educational interpretation — not proprietary Zireman Pine Script.

**When to use:** When you want OB + FVG + S/R confluence scored on a watchlist before picking a direction.

---

### Pump/Dump Breakout — consolidation breakdown & breakout
*id: `pump_dump_breakout`*

### Pump/Dump Breakout — Consolidation Box Strategy
**Market Pulse** — screen volatile trending tokens, wait for **tight consolidation** after pump/dump, enter on **confirmed breakout or breakdown**.

| Step | Rule |
|------|------|
| Screen | 24h pump ≥10% (or dump) · trending/Alpha flag · repeating pump-dump cycles |
| Wait | Box range ≤ max % over lookback · min bars inside |
| Short | Close below box − buffer · volume spike |
| Long | Close above box + buffer · volume spike |
| Risk | SL 2–4% · TP 10–20% · leverage ≤10x · size by % equity risked |

Outputs: screen pass/fail · live consolidation box · latest signal · backtest stats.

High risk on thin meme books — backtest only. See collapsible **Strategy explanation**.

---

### Big Whale Pump & Dump — DEX whale flow
*id: `big_whale_pump_dump`*

### Big Whale Pump & Dump — On-chain discovery
**Market Pulse** — video playbook for finding coins **before** the next pump:

1. **24h pumped tokens** — DexScreener boosted + high `priceChange.h24`
2. **Big trades** — top 24h volume on those pairs (open DexScreener for swap size)
3. **Wallet trace** — links to **Solscan** / **BscScan** Holders & Transfers (manual)
4. **Accumulation** — buy pressure + moderate pump + volume (whale entry proxy)
5. **Liquidity inflows** — highest USD liquidity + volume (capital gathering)

Chains: **Solana**, **BNB**, optional Base/Ethereum. Requires network. Not live wallet API — explorer deep-links for steps 3–4.

| Trade | When |
|-------|------|
| **BUY** | Accumulation / pre-pump watch / liquidity inflow + buy pressure |
| **SELL** | Extended 24h pump + distribution volume / sell pressure |
| **SL / TP** | ~3% / 15% base; wider on thin pools or extreme pumps |

---

### Sector Rotation — daily · weekly · monthly
*id: `sector_rotation`*

### Sector Rotation
Ranks Nifty sector indices by daily, weekly, and monthly return.

Use the **sector index filter** to subset which Nifty sectoral indices are included (same pattern as US/Crypto sector pickers).

Top = inflow leadership; bottom = lags. Use for sector tilt, not single-stock entries alone.

---

### Sector Rotation — mins · hours · days
*id: `sector_rotation_intraday`*

### Sector Rotation — mins · hours · days
Session-style sector leadership using **5m**, **1h**, and **daily** bars.

| Window | Bars | Use |
|--------|------|-----|
| Minutes | 5m | Opening drive, first-hour rotation |
| Hours | 1h | Half-day / full-session tilt |
| Days | 1d | Short swing sector bias (1–10 sessions) |

Pair with the daily/weekly/monthly Sector Rotation section for HTF context.

---

### Sector Rotation (US) — daily · weekly · monthly
*id: `sector_rotation_us`*

### Sector Rotation (US) — daily · weekly · monthly
Ranks **SPDR sector ETFs** (XLK, XLF, XLE, …) vs **SPY** over daily, weekly, and monthly windows.

Use the **sector universe** filter (All SPDR · Cyclicals · Defensives · Custom) to subset symbols before loading.

---

### Sector Rotation (US) — mins · hours · days
*id: `sector_rotation_us_intraday`*

### Sector Rotation (US) — mins · hours · days
Session-style US sector rotation on **5m**, **1h**, and **daily** bars via Yahoo Finance.

Best during **US market hours**. Same sector/symbol filter as the HTF US section.

---

### Sector Rotation (Crypto) — daily · weekly · monthly
*id: `sector_rotation_crypto`*

### Sector Rotation (Crypto) — daily · weekly · monthly
Ranks major **CoinDCX USDT** pairs vs **BTC** over daily, weekly, and monthly windows.

Session day starts at **00:00 New York (ET)**. Filter by bucket: Major L1 · DeFi · High Beta/Meme · Custom pairs.

---

### Sector Rotation (Crypto) — mins · hours · days
*id: `sector_rotation_crypto_intraday`*

### Sector Rotation (Crypto) — mins · hours · days
Intraday crypto rotation on **5m**, **1h**, and **1d** CoinDCX bars vs BTC benchmark.

**Session day starts at 00:00 New York (ET)** — the **day** window counts NY session days, not UTC/IST.

**Crypto sector bucket** includes live leader universes:
- **Top Volume** — highest futures volume
- **Top Volatile** — largest session range / % move (NY session day)
- **Top Risen** / **Top Fallen** — session gainers and losers (CoinDCX 24h % + NY session range)

After load, **Top Volume · Volatile · Risen · Fallen** tables show movers within your selected pairs (or market-wide in the preview expander).

Use for alt-season vs BTC-dominance reads and short-term leadership shifts.

---

### Opposite Hedge-MTF — long leader · short laggard
*id: `opposite_hedge_mtf`*

### Opposite Hedge-MTF
Long the **leading** sector and short the **lagging** sector from both rotation feeds — profit the **spread delta**.

| Source | Windows |
|--------|---------|
| Intraday rotation | Minutes · Hours · Days |
| HTF rotation | Daily · Weekly · Monthly |

**Per window:** long ticker + % alloc + confidence + SL/TP + hold duration · same for short leg.

**Consensus row** votes the best pair across all six windows. Buy long in cash/ETF; short via F&O or paired instrument.

---

### MTF Intraday Bias — Equities
*id: `mtf_intraday_bias`*

### MTF Intraday Bullish / Bearish (Equities)
Multi-timeframe session bias for NSE stocks and Nifty indices.

| Layer | Default | Role |
|-------|---------|------|
| HTF | 1d | Daily trend context |
| MTF | 1h | Session structure |
| LTF | 15m | Setup timing |
| ULTF | 5m | Fine entry |

**Indicators scored:** RSI, MACD, Stochastic, EMA stack, Bollinger, ADX, volume, Elliott wave, S/R proximity, NSE PCR (equities).

**Output:** Bullish / Bearish / Neutral per ticker with **trade setup** — entry timeframe (LTF→ULTF), SL%, TP%, hold duration, READY vs WATCH status.

**Session:** India cash hours for price-vs-open and close-bias labels. Configure HTF·MTF·LTF·ULTF in the timeframe settings expander.

---

### MTF Intraday Bias — Crypto
*id: `mtf_intraday_bias_crypto`*

### MTF Intraday Crypto Bullish / Bearish
Same scoring engine as equities for **CoinDCX USDT** pairs.

| Difference | Detail |
|------------|--------|
| Session day | Starts **00:00 New York (ET)** |
| Price vs open | NY session open (not IST) |
| PCR | Omitted (no NSE chain) |
| Prices | Yahoo USD proxy |

Trade setups include entry TF, SL%, TP%, hold time. Configure HTF·MTF·LTF·ULTF like the equity scanner.

---

### 52-Week High & Low
*id: `week52`*

### 52-Week High and Low
Constituents near 52-week high/low for breakout or reversal context. Filter by index universe.

---

### Live Heatmap
*id: `heatmap`*

### Live Heatmap
Colour grid of sector and ticker % change. Sector mode for industries; ticker mode for constituents.

---

## 🔬 Technical Analysis

### Price Action Screener
*id: `price_action`*

### Price Action Screener
Multi-indicator live scanner: S/R, trendlines, RSI divergence, EMA crossovers, Fibonacci golden zone, Elliott wave, candlesticks, chart patterns, SMC (order blocks / FVG), **session VWAP**, and **relative volume**.

| Metric | Meaning |
|--------|---------|
| Trend | Linear regression slope — SIDEWAYS = range |
| RSI | <30 oversold, >70 overbought |
| EMA stack | 9/21/50 alignment |
| Fib Golden | 50–61.8% retrace zone |
| **VWAP** | Session-reset fair value — above/below bias; **AT VWAP** = test/reclaim zone |
| **RVOL** | Volume vs 20-bar avg — **≥1.5×** spike confirms S/R or breakout; **<0.7×** = thin |
| **MFI** | Money Flow Index — volume-weighted momentum |
| Smart Money | OB / FVG footprints near price |

**Approaching alerts** fire when price is within ~0.4% of S/R, testing VWAP reclaim/loss, volume spikes at a level, or in Fib golden zone without a ready setup — surfaced as **WATCHLIST** in the screener digest.

Groww and CoinDCX · multi-TF · approaching-setup alerts · SL/TP trade plans · AI View.

---

### Pump & Dump Screener
*id: `pump_dump_predictor`*

### Pump and Dump Screener
Pre-move detection (India + crypto). One green rule = signal; aim for **3+ greens** and confluence **55+** for action.

See Starter Guide tab for full rule list.

**When to use:** Hunting early movers in small/mid caps or volatile crypto alts.
**Rule of thumb:** 1 green = watch · 3+ greens + score 55+ = actionable · always confirm volume.

---

### Find S/R Screener
*id: `find_sr`*

### Find S/R Screener
Two immediate supports (S1, S2) and resistances (R1, R2) with **price and % from LTP**.

**Consolidation rules**
- Tight range **under resistance → bullish** (coiling for upside break)
- Tight range **above support → bearish** (flag for downside break)

**Supply / demand** — swing-history zones: rejections at highs (supply), bounces at lows (demand).

Also: EMA ladder, patterns near S/R, volume, RSI, annotated chart, bar date/time.
Groww · US · Crypto · multi-TF · AI View.

**When to use:** Before entering any trade — know where S1/S2/R1/R2 and trendline breaks are.
**How:** Select tickers → timeframes → Run Scan. Expand ticker for chart + AI View.

---

### Weak Strong S-R
*id: `weak_strong_sr`*

### Weak Strong S-R (Institutional S/R Framework)

| Level type | Strength | Action |
|------------|----------|--------|
| Support | **Strong** (≥3 touches) | **BUY** — institutional floor |
| Support | **Weak** (1–2 touches) | **SELL** — breakdown risk |
| Resistance | **Weak** | **BUY** — breakout through thin supply |
| Resistance | **Strong** | **SELL** — rejection at heavy supply |

**Confluence filters:** VWAP bias · volume ratio · Supertrend · RSI (14) · **consolidation at S/R** · **supply/demand zones**.

**Consolidation rule:** coiling under resistance → bullish; above support → bearish.
**Supply/demand:** swing-history zones (rejections = supply, bounces = demand).

**Output per ticker:** MTF alignment % · **SL %** · **TP %** · **confidence %** · hold duration.

Groww · US · Crypto · hub LTF/MTF/HTF timeframes · AI View.

---

### Pattern & Breakout Screener
*id: `pattern_breakout`*

### Pattern & Breakout Screener

| Category | Detection |
|----------|-----------|
| S/R events | Breakout, breakdown, fakeout, reversal |
| Trendlines | Ascending/descending + regression bias |
| Retracement | Fib levels & golden zone |
| Candles | Engulfing, hammer, doji, marubozu, stars |
| Patterns | H&S, double top/bottom, wedges, flags, cup & handle |
| Trade plan | Entry, SL, TP1/TP2, R:R, hold duration, stay-in vs exit |

Groww and CoinDCX · multi-TF · AI View.

---

### 5min – 4hrs Breakout (4H fakeout)
*id: `fakeout_4h`*

### 5min – 4hrs Breakout Screener (4H range fakeout fade)

**Reference:** [YouTube walkthrough](https://www.youtube.com/watch?v=O5eC5lY7ZXY&start=65)

| Phase | Meaning |
|-------|---------|
| ENTRY_READY | Fakeout confirmed — fade entry active |
| BREAKOUT_ACTIVE | Breakout in progress — watch body re-entry |
| APPROACHING HIGH/LOW | Near range edge |
| MONITORING | Inside range |
| WAIT_RANGE | 4H range still forming |

| Market | Range | Signal window |
|--------|-------|---------------|
| Groww | 09:15–13:15 IST | 13:15–15:30 IST |
| CoinDCX | 00:00–04:00 NY | After NY range |

Groww and CoinDCX · 1M execution on 4H range fakeouts.

---

### 1min – 15min Breakout (15M fakeout)
*id: `fakeout_15m`*

### 1min – 15min Breakout Scanner (15M range fakeout fade)

**Reference:** [YouTube walkthrough](https://www.youtube.com/watch?v=O5eC5lY7ZXY&start=65)

| Phase | Meaning |
|-------|---------|
| ENTRY_READY | Fakeout confirmed — fade entry active |
| BREAKOUT_ACTIVE | Breakout in progress — watch body re-entry |
| APPROACHING HIGH/LOW | Near range edge |
| MONITORING | Inside range |
| WAIT_RANGE | 15M range still forming |

| Market | Range | Signal window |
|--------|-------|---------------|
| Groww | 09:15–09:30 IST | 09:30–15:30 IST |
| CoinDCX | 00:00–00:15 NY | After 15M NY range |

Groww and CoinDCX · 1M execution on first 15M range fakeouts.

---

### Institutional MTF Scanner
*id: `mtf_scanner`*

### Institutional MTF Scanner — 7-component engine

| Component | Weight | Contents |
|-----------|--------|----------|
| Trend | 25% | SMA20/50/200, EMA9/21, golden cross, regression |
| Momentum | 20% | RSI, Stoch, MACD, ROC, Williams %R |
| Price action | 15% | Engulfing, hammer, pin bar, doji, soldiers/crows |
| S/R | 15% | Pivots, swing fractals, 52-period range |
| Volume | 10% | Vol ratio, OBV, Force Index, VWAP, CMF |
| Volatility | 10% | BB %B, ATR%, Donchian, ADX+DI |
| Structure | 5% | HH/HL vs LH/LL, Ichimoku, market structure |

**Confluence:** ≥65% TFs bullish (score ≥60) = STRONG BULLISH; bearish mirror.

Per-TF setup: SL%, TP1/TP2%, confidence%, hold duration. Buckets: Scalp / Intraday / Swing / Position.

**Pro tips:** Top-down 1d→4h→1h→15m; skip confidence <40%; size up when >70% + composite >65%.

---

### Multi-Timeframe Hedging — Groww · US · Crypto
*id: `mtf_hedging`*

### Multi-Timeframe Hedging
**Groww India**, **US stocks**, and **crypto** — pick tickers from **index/universe dropdown**, **multiselect**, or **Custom**.

Set **LTF · MTF · HTF** chart timeframes (e.g. 1h / 1d / 1wk) — each role runs all hedge techniques on that bar size.

| Technique | India | US | Crypto |
|-----------|-------|-----|--------|
| Beta hedge | Sell NIFTYBEES/BANKBEES | Short SPY/QQQ | vs BTC |
| Pairs trade | NSE pairs | US pairs | BTC/ETH |
| Put delta | NSE F&O estimate | US options | — |
| Index/Inverse ETF | Sell index ETF | Buy SH/PSQ | — |
| Min-var hedge | — | — | Short ETH vs BTC |
| Portfolio risk | VaR / Sharpe basket | same | same |

Compare hedge ratios across lookbacks — stable beta/hedge ratio = more reliable sizing.

**When to use:** Portfolio hedging — beta hedge, pairs trade, protective puts, index ETF overlay.

---

### Top Down MTF (SMC)
*id: `top_down_mtf`*

### Top-Down MTF (SMC 3-step)

**Reference:** [YouTube walkthrough](https://www.youtube.com/watch?v=5ameUmO4tuc)

| Step | TF (default) | Look for |
|------|--------------|----------|
| 1 HTF | 15m | HH/HL or LH/LL, PDH/PDL, day H/L → **bias** |
| 2 MTF | 5m | **CHoCH** + **FVG** or **Order Block** |
| 3 LTF | 1m | Retest + Marubozu / Hammer / Mini CHoCH |

| Phase | Meaning |
|-------|---------|
| ENTRY_READY | All 3 steps — SL/TP active |
| APPROACHING_LTF | Zone exists, trigger pending |
| MTF_SETUP | CHoCH + FVG/OB, wait retest |
| HTF_BIAS | Direction only |
| NEUTRAL | No clear bias |

Avoid: LTF vs HTF conflict, skipping MTF, HTF level blocking path. Groww and CoinDCX.

---

### TOPDOWN - MTF (Liquidity + OB)
*id: `topdown_mtf`*

### TOPDOWN - MTF — Liquidity & Order Blocks

**Reference:** [YouTube — Top Down Analysis with Liquidity and Order Blocks](https://www.youtube.com/watch?v=RvVs6n46X10)

| Tier | Default TF | Role |
|------|------------|------|
| **HTF** | 1d | Trend direction (HH/HL · LH/LL) |
| **ATF** | 1h / 4h | Swings, **liquidity sweeps**, **order blocks** after BOS |
| **LTF** | 15m / 5m | Price taps OB → **MSS** → entry on LTF OB |

| Phase | Meaning |
|-------|---------|
| ENTRY_READY | HTF + ATF OB + LTF MSS — SL/TP active |
| IN_OB_ZONE | Inside OB — wait for MSS |
| ATF_SETUP | OB mapped — wait for retest |
| HTF_BIAS | Trend only |

Distinct from **Top Down MTF** (shorter default TFs + CHoCH/FVG). Groww, CoinDCX, US.

**When to use:** SMC **top-down** with **liquidity sweeps + order blocks** — HTF trend (1d) → ATF structure (1h) → LTF MSS entry (15m).
Distinct from Top Down MTF (CHoCH/FVG on shorter default TFs). Groww · US · CoinDCX.

---

### Weekly Stoch Sweet Spot
*id: `weekly_stoch_sweet_spot`*

### Weekly Stochastic Sweet Spot

**Reference:** [YouTube walkthrough](https://www.youtube.com/watch?v=Tr_RXi6wQko)

| Element | Rule |
|---------|------|
| Sweet spot | Weekly %K between **32%** and **80%** |
| BUY entry | %K crosses above %D **into** zone from below 32% + volume confirm |
| Hold | While %K > %D — can ride above 80% |
| SELL exit | %K crosses below %D while %K < 80% |

Volume: majority of daily sessions in the week above 20-day avg at entry.

Phases: ENTRY_SIGNAL · IN_TRADE · EXIT_SIGNAL · APPROACHING · SWEET_WATCH. Typical hold **1–12 weeks**. Groww and CoinDCX.

---

### KN Smart DP SL + RSI MTF + VWMA
*id: `kn_smart_rsi_mtf`*

### KN Smart DP SL + RSI MTF + VWMA

**Reference:** [YouTube walkthrough](https://www.youtube.com/watch?v=2bAwEz12MrE)

| Layer | Role |
|-------|------|
| Daily VWMA(20) | Master trend — above=bull, below=bear |
| KN Smart ribbon | EMA5/12 midpoint entry + ATR×1.5 chandelier SL |
| RSI(14) vs SMA(RSI) | Bull above 50, bear below 50 |
| MTF dashboard | Fast>slow EMA on **≥3 of 4** TFs (1m,5m,15m,1h) |

**LONG:** bullish master + ribbon bull + green close above entry + RSI>50 + MTF≥3.

**Exit:** trail SL, RSI>80/<30, TP1/2/3 at 1×/2×/3× ATR. Hold **15 min – 3 hours** on 3m/5m. Groww and CoinDCX.

---

### Velez Retracement Scalping
*id: `velez_retracement`*

### Velez Retracement Scalping (Oliver Velez)

- **Chart:** 2m (or 5m) · **SMA 20** short trend · **SMA 200** long trend
- **Zones:** 25% · 50% · 75% · 100% retrace

| Mode | Rule | Target |
|------|------|--------|
| A Scalp | Counter-trend after sharp move; retrace **<50%** | **25%** retrace (~90% zone) |
| B Trend | Retrace **>50%** + engulfing bar | Min **2:1 R:R** continuation |

Sharp move filter: net move > threshold (default 0.5%). Scalp stop ~0.3%; trend stop beyond engulfing extreme. Groww and CoinDCX.

**Reference:** [YouTube walkthrough](https://www.youtube.com/watch?v=MM4yzIq5Q-c&start=296)

---

### Smart Wave Crypto (CoinDCX only)
*id: `smart_wave_crypto`*

### Smart Wave Crypto (CoinDCX only — Smart Wave Academy)

Session day starts at **00:00 New York (ET)**.

| # | Strategy | TF | Rule |
|---|----------|-----|------|
| S1 | EMA Crossover | 30m/1h | EMA10×EMA30 cross; SL prev candle; TP 1:3 |
| S2 | SuperTrend | 30m/1h | Period 10, mult 3 — GREEN long, RED short |
| S3 | BB Reversal | 30m | Pierce band → close inside; target opposite band |
| S4 | Multi-Bagger SHORT | 5m | +40% in 24h, price < EMA280, ST turns RED |
| S5 | Volume filter | — | Vol > 20-bar MA confirms signal |

**Risk:** ₹200/trade max · 1:3 R:R minimum · max **5X** leverage · max 2 concurrent trades. Educational — SL first.

---

### Crypto Scalping — EMA · VWAP · RSI (CoinDCX)
*id: `crypto_scalping`*

### Crypto Scalping — EMA + VWAP Pullback + RSI (CoinDCX)
Session day starts at **00:00 New York (ET)**. 1m/5m scalping on CoinDCX USDT perpetuals.

Rule-based **1m / 5m** scalping with three agreeing filters:

| Step | Rule |
|------|------|
| Trend | EMA9 vs EMA21 — longs only in uptrend, shorts only in downtrend |
| Entry | VWAP pullback — dip to/near VWAP then close back above (long) or pop then below (short) |
| Confirm | RSI(14): long 50–70 · short 30–50 |

**Risk:** fixed fractional sizing · ATR × stop multiplier · R:R take-profit · fees + slippage · max trades/day · daily loss cutoff.

Backtest on loaded bars or upload CSV (`timestamp, open, high, low, close, volume`). Profit factor > 1 with reasonable trade count is the minimum bar for paper-trading — **not** a guarantee. Educational only.

---

### SMC Fake Market Shift — BOS · POI · sweep
*id: `smc_fake_market_shift`*

### SMC — Fake Market Shift (Groww & CoinDCX)

**3-step SMC model:**

| Step | What it does |
|------|----------------|
| 1 Structure | Causal fractal swings → HH/HL/LH/LL → **Break of Structure (BOS)** sets trend bias |
| 2 POI | Map **extreme zone** / order block that originated the BOS leg (demand after bullish BOS, supply after bearish) |
| 3 Fake shift | Pullback into POI → internal structure → inducement breakout → **liquidity sweep** → reversal |

**Entry models:**
- **A Aggressive** — stop at sweep candle extreme; SL beyond liquidity-grab wick; default R:R 1:2
- **B Conservative** — wait for **Market Structure Shift** (close breaks internal high/low), limit entry on **flip-zone** mitigation; default R:R 1:3

Backtester simulates pending stop/limit fills, then SL vs TP. Tune swing left/right, POI lookahead, and entry model to your timeframe (5m–1d). Educational — sweep detection is heuristic.

---

### Confluence Screener
*id: `confluence_strategy`*

### Confluence Screener

| Factor | Bullish | Bearish |
|--------|---------|---------|
| Supertrend | Price above ST (+1) | Price below ST (−1) |
| VWAP | Close above session VWAP | Close below |
| Volume | Up bar + ratio ≥1.15× | Down bar + high vol |
| OBV | Rising 5 bars | Falling 5 bars |
| Fibonacci | Golden zone bounce | Golden zone rejection |
| S/R | Near support / above S1 | Near resistance / below R1 |

**Verdict:** STRONG BUY / BUY when bull ≥45 pts, net ≥25. **Plan:** entry at close, SL beyond S1 or 1.5×ATR, TP at R1/Fib 127.2%. Groww and CoinDCX.

---

### Strategy Scheduler Screener
*id: `strategy_scheduler`*

### Strategy Scheduler Screener
Batch preset rule packs across universes. Manual scan of encyclopedia-style strategies.

**When to use:** Scheduled batch scan of encyclopedia-style preset packs across Groww or crypto universes.
Good for end-of-day watchlist building.

---

### Elliott Wave Screener
*id: `elliott_wave`*

### Elliott Wave Screener

- **ZigZag filter** finds swing highs/lows (sensitivity = ZigZag % slider)
- **5-wave impulse** validated with classic Wave 2/3/4 rules
- **ABC correction** when impulse rules fail but 3-leg corrective fits
- **Fib targets** after impulse or extension after ABC

Probabilistic — combine with S/R, trend, volume. Multi-ticker × multi-TF + AI View. Groww and CoinDCX.

---

### Trend & Sentiment Screener
*id: `sentiment`*

### Institutional-Grade Sentiment Engine — Full Breakdown

Combines **25+ technical checks** into a composite score from **-100 (Extreme Bearish)** to **+100 (Extreme Bullish)**.

#### Core categories
1. **EMA stack** (9/21/50/200) — trend backbone
2. **Bollinger Bands** — squeeze, band rejection, breakout
3. **RSI(14)** — momentum zones + divergence
4. **MACD(12,26,9)** — histogram shift signals
5. **ADX(14)** — trend strength (>25 = strong)
6. **Stochastic(14,3,3)** — OB/OS cross confirmation
7. **Volume** — ratio vs 20MA, OBV, spike/dry filters
8. **VWAP** — institutional buy/sell side
9. **Supertrend(10,3)** — ATR trail direction
10. **Pivot points** — R1/R2/S1/S2 breaks
11. **Fibonacci** — golden zone 0.618–0.65
12. **Candlesticks** — 10+ bullish/bearish patterns
13. **S/R breakouts** — volume-confirmed only
14. **SMC** — order blocks, FVG, liquidity sweeps
15. **Reversals** — RSI extreme + pattern + volume

#### Trade signals (ATR-based)
| Score | Signal |
|-------|--------|
| ≥ +15 | BUY — SL = entry − 1.5×ATR, TP = entry + 2×ATR |
| ≤ −15 | SELL — inverted |
| −15 to +15 | WAIT |

#### Score ratings
| Range | Rating |
|-------|--------|
| +65 to +100 | STRONG BUY |
| +35 to +65 | BUY / BULLISH |
| −10 to +10 | NEUTRAL |
| −65 to −35 | SELL / BEARISH |
| −100 to −65 | STRONG SELL |

Multi-TF ranking on Groww and CoinDCX. Educational use only — confirm with risk management.

---

### Top/Bottom Screener
*id: `top_bottom`*

### Top/Bottom (Trough & Peak) Analyzer

Identifies price extremes where reversal is statistically likely using rolling window highs/lows.

**Long:** near bottom trough + bearish momentum exhausted.
**Short:** near peak top + bullish momentum exhausted.

**Tools:** lookback extremes · RSI exhaustion (>70 top, <30 bottom) · ATR-based SL · Fib 38.2/50/61.8% TP · candle/chart pattern confluence · crypto margin safety vs liquidation.

Counter-trend context — not trend-following alone. Groww and CoinDCX.

---

### SMC · Options Flow Screener
*id: `smc_options`*

### SMC · Options Flow Screener
SMC structure plus NSE options flow: delivery, PCR, OI change. India F&O names.

**When to use:** NSE F&O names where options flow (delivery, PCR, OI change) confirms SMC structure.
**India only** — requires liquid options chain data.

---

### BB Exposed — Free Bar + Squeeze
*id: `bb_exposed`*

### BB Exposed — Bollinger Free Bar + Squeeze (Mind Math Money)
[Video reference](https://www.youtube.com/watch?v=dnSoD4iO0YU&t=148s):

| Strategy | Rule |
|----------|------|
| **Free Bar** | Full candle outside bands = exhaustion fade (with reversal candle) |
| **Squeeze** | Bandwidth contraction → breakout close outside bands |
| **Day preset** | BB **10** · std **1.5** |
| **Swing preset** | BB **50** · std **2.5** |
| **SL / TP** | Beyond trigger wick · **2:1 R:R** minimum |

Groww · CoinDCX · US · multi-TF chart. Conf / SL% / TP% on every row.

**When to use:** Volatility exhaustion fades (free bar outside bands) or squeeze breakouts after bandwidth contraction.
Day preset BB(10,1.5) for scalp; swing BB(50,2.5) for larger moves. Confirm free bars with reversal candles.

---

### Breakout MTF — Multi-Period Daily Scanner
*id: `breakout_mtf`*

### Breakout MTF — Multi-Period Daily Scanner
[FoxTrader breakout scanner](http://www.youtube.com/watch?v=kQyruEPH108) — Reliable Software Systems:

| Rule | Detail |
|------|--------|
| **Lookbacks** | 10 / 20 / 50 / 90 / 200 days — parallel flags |
| **Exclude current bar** | Rolling max/min on **prior** bars only (`shift(1)`) |
| **Breakout** | Close > highest high of N days → **BUY** |
| **Breakdown** | Close < lowest low of N days → **SELL** |
| **RSI** | Bullish continuation **50–70** |
| **MACD** | Positive for breakouts · negative for breakdowns |

Dashboard shows per-period BO/BD columns. Conf / SL% / TP% on actionable rows.

**When to use:** Daily swing scanner — fresh closes breaking 10/20/50/90/200-day highs or lows with RSI + MACD filters.
FoxTrader-style dashboard for watchlist ranking. Best on liquid NSE/US names with 200+ daily bars.

---

### ONE TA — Golden Zone Fib + EMA
*id: `one_ta`*

### ONE TA — Golden Zone (Fib + EMA + VPA)
[Professional trading blueprint](https://www.youtube.com/watch?v=UbmSxPOQRb4&t=14s):

| Layer | Rule |
|-------|------|
| **Trend** | **200 EMA** bias — long above · short below |
| **Golden Zone** | Pullback into **50%–61.8%** Fib of swing range |
| **Confluence** | Zone overlaps **EMA** / supply-demand |
| **Entry** | **Engulfing** (2-candle body) or **50%+ wick rejection** |
| **SL** | Past **61.8%** / swing extreme |
| **TP** | Partials **38.2% / 23.6%** · full at swing origin (100%) |

Multi-TF chart. Conf / SL% / TP% / momentum ROC on every row.

**When to use:** Golden Zone pullback trades — 50–61.8% Fib retrace with 200 EMA trend bias,
engulfing or 50% wick rejection entry. Scale at 38.2%/23.6%, full target at swing origin.

---

### Box Trading — Prev-Day Range (TradingLab)
*id: `box_trading`*

### Box Trading — TradingLab Box Strategy
[Alex Ruiz / TradingLab](https://www.youtube.com/watch?v=oXb2lySZhCU&t=40s) — pure price-action day trade:

| Rule | Detail |
|------|--------|
| **Box** | Prev day **high** + **low** extended on today's chart |
| **No-trade** | Middle **50%** of box — chop zone |
| **Never** | Long at top · Short at bottom |
| **Long** | Bottom test + bullish rejection (pin / engulfing) |
| **Short** | Top test + bearish rejection |
| **Breakout** | Break → **retest** → enter with trend (no chase) |

5m/15m execution. Conf / SL% / TP% / box levels on every row.

**When to use:** Intraday **previous-day range** fades and breakout-retests — no indicators.
Map yesterday's high/low, avoid the midpoint 50% chop, trade edge rejections or retests only.
Best on liquid names during regular session hours.

---

## 🇮🇳 ETF TA IN

### ETF Shop 4.0 — 20 DMA · dynamic SIP · FIFO · 39 distinct ETFs
*id: `stf_shop`*

### ETF Shop 4.0 — Programmatic India ETF Swing + Dynamic SIP (FIFO)

A **mechanical, sheet-driven** ETF business model (FIRE in India) — **<5 minutes/day**.
Methodology rooted in strategies popularised by **Mahesh Chandra Kaushik**.
This tab replaces the automated **Google Sheet** shop engine.

---

#### 1. Core concept

| Topic | Rule |
|-------|------|
| **Goal** | Regular income via a rule-based rotation engine |
| **Instrument** | **ETFs only** — basket risk, not single-stock blow-ups |
| **Operation** | Programmatic tracker — rank, buy, FIFO sell when targets hit |
| **Time** | One daily check (before close) — no chart-watching |

---

#### 2. Standard buying — Rank 1 vs 20 DMA (max 1/day)

1. Sheet tracks **CMP** and **20 DMA** for every ETF in the primary list.  
2. Ranks by **cheapness vs 20 DMA** — lowest % vs DMA = **Rank 1**.  
3. Each day buy **exactly 1 ETF** — the **Rank 1** name when not in SIP mode.  

**39 ETFs** mapped to **39 distinct underlying assets** — no index overlap pile-up.

---

#### 3. Weakness & SIP mode (−10% rule)

| Step | Rule |
|------|------|
| **Initial purchase** | You pick your ETF underlyings and buy per standard rules |
| **−10% threshold** | If CMP falls **10% below initial purchase price**, standard averaging **stops** |
| **SIP latch** | That ETF enters **SIP mode** (stays latched) |
| **SIP budget** | **10%** of **total invested** in that ETF — fixed for the SIP cycle |

**Old calendar SIP:** fixed monthly date per ETF.  
**New dynamic fall model (4.0):** sort by **fall from last buy price** — buy the **cheapest vs last purchase** first.

| SIP rule | Detail |
|----------|--------|
| **Frequency** | Exactly **1 SIP per day** (across all SIP-mode ETFs) |
| **Selection** | ETF at top of **Sorted by Fall from Last Buy** |
| **Plus-zone filter** | If price is **above** last SIP buy (positive %), **skip** — buy only what is dynamically cheap |

---

#### 4. Selling — FIFO profit booking (max 1/day)

**FIFO (First-In, First-Out):** exit the **oldest lot** first.

| Trigger (4.0 default) | Rule |
|-----------------------|------|
| **Combined** | **Both** % target (e.g. **5–6%**) **and** minimum ₹ profit (e.g. **₹500**) |
| **Legacy % only** | Latest lot hits % gain |
| **Legacy ₹ only** | Latest lot hits flat ₹ gain |

- Sell **max 1 ETF/day** — book profits sequentially.  
- Eligible lots show as **green**; after sell, move row **Bought → Sold** (Bika Hua Maal).

---

#### 5. Capital & portfolio management

| Feature | Detail |
|---------|--------|
| **Deposited capital** | Your base pool in Capital Management |
| **Growth amount** | Net profits reinvested after STCG tax + brokerage |
| **Dynamic slot size** | Scales with **effective capital** ÷ 60 |
| **Shop start date** | Auto-locks on first transaction for **annualized return** |
| **Profit analyzer** | **Bika Hua Maal** tab — rankings by symbol profit & bookings |

---

#### 6. Downturn discipline

| Rule | Detail |
|------|--------|
| **Process** | Continue dynamic SIP while allocated capital lasts |
| **No panic exits** | Do not book losses from fear |
| **No leverage** | Never borrow or use emergency funds |
| **Capital exhausted** | **Stop buying**, wait patiently — ETFs recover over cycles |

---

#### 7. Daily workflow in this tab

1. Set **deposited capital**, sell mode (**combined** recommended), min ₹ profit, dividend %.  
2. Use preset **ETF Shop 4.0 — 39 distinct**.  
3. Maintain **open lots** (Khareeda Hua Maal).  
4. **RUN ETF SHOP SCAN** → standard Rank 1 or dynamic SIP buy + FIFO sell.  
5. Execute **max 1 buy + 1 sell** in broker; **record** to update growth/dividend pools.

References:
- [ETF Shop 4.0 FIFO launch (YouTube)](https://www.youtube.com/watch?v=xrKfKpNhkTE)
- [ETF Shop 4.0 dynamic falling-market update (YouTube)](https://www.youtube.com/watch?v=xrKfKpNhkTE)

---

## ⚡ Strategy Lab

### Strategy Builder & Tester
*id: `strategy_builder`*

### Strategy Builder & Tester
Visual strategy designer with full backtest engine.

1. Add indicators (EMA, SMA, RSI, MACD, BB, Supertrend, VWAP, Fib, ADX, etc.).
2. Define **entry rules** (ALL must be true) and **exit rules**.
3. Set ticker, timeframe, SL %, TP %, and backtest date range.
4. **Run Backtest** → equity curve, trade list, win rate, profit factor, max drawdown.
5. **Save Strategy** (login required) → Saved Strategies Archive.

Load presets from Encyclopedia or output from AI Strategy Creator.

---

### Saved Strategies Archive
*id: `saved_strategies`*

### Saved Strategies Archive
Your personal library of backtested strategies (login required).

- Reload by name; re-run with updated dates.
- Compare win rate, profit factor, drawdown across versions.
- Feed into **Multi-Combo Scanner** and **Alert Monitors**.

---

### Multi-Combo Scanner
*id: `multi_combo`*

### Multi-Combo Scanner
Batch backtest engine: **tickers × timeframes × strategies**.

- Preset/custom backtests plus **all 30 TA hub engines** (grouped below).
- Rank results by metrics; save best combos for **Alert Monitors**.
- Large watchlists use **lazy loading — 20 tickers per batch** with per-batch digest + combined results.

**TA engine groups (once per ticker):**

| Group | Engines |
|-------|---------|
| Core MTF & session | Fakeout 15m/4h · MTF Scanner · Top Down MTF · **TOPDOWN-MTF** · Weekly Stoch · KN Smart · Velez · MTF Intraday Bias |
| TA extensions | SMC Fake Market Shift · BB Exposed · Breakout MTF · ONE TA · **Box Trading** |
| Crypto | Smart Wave · Crypto Scalping |
| Scalping | Rectangle · SMC Rule of Three · ARC · S/R MSS |
| Smart Money | CISD · Weekly Sweep CISD · MTF Day Plan · Golden Bullet · Liquidity · **SMB SnP** |
| Intraday | Alpha 9:45 · Fib 9:45 · VWAP Fade · MTF Breakout-Retest |

Use **Strategy Lab → Builder** to backtest presets; **Multi-Combo** to batch-scan; **Alerts** to monitor live.

**When to use:** Batch **backtest ranking** — find which ticker performs best on which of the **30 TA hub engines** (6 groups in UI).
Save winners to **Alert Monitors**. Lazy-loads 20 tickers per batch.

---

### Strategy Encyclopedia (this page)
*id: `strategy_encyclopedia`*

### Strategy Encyclopedia
Master reference for the entire application (Strategy Lab → Encyclopedia tab).

| Block | Contents |
|-------|----------|
| **App overview** | Hubs, Command Center highlights, Manage → AI Settings (Gemini · Groq · Claude Azure · OpenAI Azure) |
| **Workflows** | Morning, scalp, swing, options/F&O, breadth + relative strength, Mega Analyser, Buy/Sell, Investigation |
| **When to use what** | Goal × tool matrix, trader style, market type |
| **All hubs & strategies** | Every section id with its Strategy Guide |
| **Strategy Lab & tools detail** | Builder, Multi-Combo, AI Creator, Ask AI / AI View |
| **Preset Strategy Catalog** | Documented presets for the Builder |

**Recent docs coverage:** Advance Decline (Multi Asset + options PCR), Comparative Strength,
OpenAI Azure deployments (`gpt-5.6-sol`, `DeepSeek-V4-Flash`, `gpt-4o`, `o4-mini`, `gpt-4o-mini`).

Use **Strategy Lab → Builder** to backtest presets; **Multi-Combo** to batch-scan; **Alerts** to monitor live.

---

### AI Strategy Creator
*id: `ai_strategy_creator`*

### AI Strategy Creator
Convert plain English or transcripts into executable rules via LLM
(Gemini · Groq · Claude Azure · OpenAI Azure — same as Manage → AI Settings).

1. Paste strategy description or video transcript.
2. LLM outputs JSON: indicators, entry/exit rules, SL/TP, timeframe.
3. **Always review in Strategy Builder** before backtesting.

---

## 🔎 Screen & Scan

### Advanced Screener
*id: `screener`*

### Advanced Screener
Rule-based universe filter with custom indicator conditions.

**When to use:** Filter 50–500 tickers by rules (e.g. RSI<30 + price above EMA200).
Start from a preset, customize conditions, scan Groww or CoinDCX universe.

**When to use:** You have specific indicator conditions (e.g. RSI<30 + EMA cross) and want to filter 50–500 tickers.
**Tip:** Start from a preset, then customize rules.

---

### Gap Trading Scanner
*id: `gap_scanner`*

### Gap Trading Scanner
Gap up/down vs prior close with S/R context, fade vs continuation bias, fill probability.

**When to use:** First 30–60 minutes after India market open. Pair with Find S/R for targets.

**When to use:** First hour after open — gap continuation vs fade setups.
Pair with Find S/R for target levels.

---

## 📅 Seasonality

### Seasonality Analyzer
*id: `seasonality`*

### Seasonality Analyzer
Historical monthly win rate and average return patterns per ticker/index.

**When to use:** Confirm swing/position trades — probabilistic edge only, not standalone entry.

---

## 📈 Swing Trading

### ST — Capitulation & Continuation Breakout
*id: `swing_trading_st`*

### ST — Swing Trading (Capitulation & Continuation)
[Video reference](https://www.youtube.com/watch?v=k-X0164r66U) — two **daily** swing systems via Backtrader:

| Strategy | Entry | Exit / stop |
|----------|-------|-------------|
| **Mean reversion capitulation** | RSI &lt; 30 + 2× volume spike + close above prior high | Stop: entry bar low · trail: close &lt; prior low |
| **Continuation breakout** | Close &gt; 60-bar high | Stop: breakout day low · trail: close &lt; 20 MA |

**Markets:** Groww India · CoinDCX · US Yahoo. Live scan outputs **TAKE LONG / WATCH** with **confidence %**, **SL %**, **TP %** plus optional Backtrader backtest.

---

### ST — Weekly Fakeout + 15m MSS
*id: `swing_trading_st_mtf_mss`*

### ST — Weekly Fakeout + 15m MSS
[Video reference](http://www.youtube.com/watch?v=Aq8_xZAFj0Q) — **MTF** swing/intraday trap system:

| Tier | Rule |
|------|------|
| **Weekly** | **PWH / PWL** = previous week high & low |
| **Daily** | **Fakeout** — wick beyond PWH/PWL but **close back inside** |
| **15m** | **MSS** — break of swing structure after liquidity grab · 1:1 R:R |

**Markets:** Groww · CoinDCX · US. Post-market fakeout scan → next-session 15m MSS entry.

---

### ST — SuperTrend + SMA 10 Swing & Pyramiding
*id: `swing_trading_st_supertrend`*

### ST — SuperTrend + SMA 10 (Swing & Pyramiding)
[Video reference](http://www.youtube.com/watch?v=JuiWfkJukmc) — **SuperTrend (10, 3)** + **SMA 10**:

| Mode | Timeframe | Entry | Exit |
|------|-----------|-------|------|
| **Swing** | Daily | SMA crosses **above** SuperTrend (bullish) | Close crosses **below** SMA 10 |
| **Pyramid** | Weekly | SuperTrend **bullish flip** · add on close above SMA | SuperTrend **bearish flip** |

Live scan: **TAKE LONG**, **CORE BUY**, **PYRAMID ADD**, exits, holds — with confidence, SL%, TP%.

---

### ST — KISS Swing Systematic
*id: `swing_trading_st_kiss`*

### ST — KISS Swing Systematic
[Video reference](http://www.youtube.com/watch?v=2YBmiyVmNNw) — weekly **Heikin Ashi** filter + **1h/4h** execution:

| Filter | Rule |
|--------|------|
| Weekly HA | Green = longs only · Red = shorts only |
| 55 EMA band | Above high / below low · inside = no trade |
| MACD | Zero-line cross in trend direction |

Risk **1–2%** · R:R **1:3–1:4** · SL at structural swing · conf/SL%/TP%/hold on every signal.

---

### ST — Daily HA Bias + 34 EMA Intraday
*id: `swing_trading_st_ha_ema`*

### ST — Daily HA Bias + 34 EMA Intraday
[Video reference](https://www.youtube.com/watch?v=o5i8WF0UIfE) — Upsurge / Animesh intraday system:

| Layer | Rule |
|-------|------|
| **Daily HA** | Prev green = **calls/long only** · prev red = **puts/short only** |
| **5m/15m** | **34 EMA** on highs/lows — channel breakout entries |
| **Exit** | Close back through opposite band · **1:2** R:R reference |

Conf / SL% / TP% / hold time on every scan row. Prefer liquid index names for options workflow.

---

### SW — Simple Steal · Little Rizzy Projection
*id: `swing_trading_st_simple_steal`*

### SW — Simple Steal · Little Rizzy Projection
[Video reference](https://www.youtube.com/watch?v=AVVM-FyewLg&t=12s) — trendline measured moves + **Bollinger Bands (20, 2σ)**:

| Step | Rule |
|------|------|
| **Bearish** | Descending trendline on bounce highs · lowest low under line |
| **Measure** | Vertical distance low → trendline · **project down** by same distance |
| **Bullish** | Ascending trendline on pullback lows · highest high above line · **project up** |
| **BB context** | Outer-band touch = out of reality · favors reversion toward target |
| **Invalidation** | Close **across** trendline = hard stop |

Daily / 4h execution. Conf / SL% / TP% / hold on every row.

---

### Swing - FIRE (Harsh)
*id: `swing_fire` · Trading Hubs → Swing*

Equity **cash** swing (not F&O): concentrate, ~**10%** loss cap, book faster in sideways markets.

| Layer | Rule |
|-------|------|
| **Leaders** | Prefer **ATH / near-high** names printing highs while the index is sideways — avoid falling knives |
| **Setup** | **VCP** (contracting pullbacks → tightness → breakout) and/or **IPO base** (listing-high breakout / retest) |
| **Trail** | **21 EMA** (or 63) — exit on **2 consecutive red closes** below; **reclaim** = re-entry |
| **Cycle** | Monthly **ROC**: Small-cap length **20** (~0 buy / ~100 de-risk); Large-cap length **18** (~0 / ~45) |
| **Macro** | **Equity/Gold** ratio near channel bottom → favor equity; near top → caution |

Human/AI overlay: ROE/ROC &gt;20%, niche product, RHP / Chittorgarh IPO list. Live scan + Backtester (`signal_df`).

**When to use:** Swing leaders on India / US / Crypto cash — momentum bases, not mean-reversion dips.

---

## ⚡ Intraday

### INTRA — 9:45 AM Alpha Scanner
*id: `intraday_alpha_945`*

### INTRA — 9:45 AM Alpha Scanner
[Video reference](http://www.youtube.com/watch?v=MfGUybW4O4c) — Dhan relative-strength scan at **9:45 IST**:

| Filter | Rule |
|--------|------|
| Liquidity | Mcap &gt; ₹5,000 Cr · volume &gt; 10 lakh |
| Trend | Above **20 EMA** · **SuperTrend (10,3)** bullish |
| Momentum | Day change **+0.5% to +1.5%** |
| Trade | Buy stop above **9:15–9:45** 30m high · SL low/body · **1:2** target |

**Output:** confidence %, SL %, TP %, same-session hold time per ticker.

---

### INTRA — 9:45 Fib 50% + 10 EMA
*id: `intraday_fib_945`*

### INTRA — 9:45 Fib 50% + 10 EMA
[Video reference](http://www.youtube.com/watch?v=5o7V6fi7mV4) — wait for **9:15–9:45** 30m range:

| Step | Rule |
|------|------|
| **Fib 50%** | Equilibrium of opening range — bias line |
| **Bias** | Above = **longs only** · below = **shorts only** |
| **Entry** | **10 EMA** cross with bias on **5m/1m** · **30 MA** confirm |
| **SL/TP** | Prior candle low / 50% Fib · **1:2** R:R |

Conf / SL% / TP% / hold time on every scan row.

---

### INTRA — VWAP Fade Value Area Extremes
*id: `intraday_vwap_fade`*

### INTRA — VWAP Fade Value Area Extremes
[Video reference](http://www.youtube.com/watch?v=Z2uJRbkb2pA) — **Setup #2** fade at ±1σ VWAP bands:

| Rule | Detail |
|------|--------|
| **Range only** | Trade when price stays inside bands — avoid trend days |
| **Short** | Upper band rejection (wick > body) · target **VWAP** |
| **Long** | Lower band rejection · target **VWAP** |
| **SL** | Beyond rejection wick · **60 min** time stop |
| **Skip** | First **15 min** after open |

MTF 15m/30m range filter. Conf / SL% / TP% / hold on every row.

**When to use:** Range-bound intraday sessions — fade ±1σ VWAP band rejections to VWAP.
Skip first 15 min; avoid on strong trend days.

---

### INTRA — MTF Breakout & Retest (Daniel Holmes)
*id: `intraday_mtf_breakout_retest`*

### INTRA — MTF Breakout & Retest (Daniel Holmes)
[Video reference](https://www.youtube.com/watch?v=k_DIcwgC3uQ&t=58s) — top-down price action on **15m**:

| Step | Rule |
|------|------|
| **Daily bias** | Bullish day = **longs only** · bearish = **shorts only** |
| **HTF** | 4H / 1H / 30m structure aligned or consolidating |
| **S/R** | Equal **body** cluster — resistance above bodies · support below bodies |
| **Traffic** | Clean left-side movement — avoid messy chop |
| **Entry** | Breakout **close** outside range · retest · break breakout candle extreme |
| **Exit** | SL beyond wick · **1:1** (80% partial, 20% runner to structure) |

Groww · CoinDCX · US. Conf / SL% / TP% / hold on every row.

**When to use:** Clear daily bias days — 15m equal-body S/R breakout with retest continuation.
Requires clean traffic left of range; HTF 4H/1H/30m alignment boosts confidence.

---

### INTRA — 7+wasted · 5m OR Breakout & Retest
*id: `intraday_7_wasted`*

### INTRA — 7+wasted · 5m Opening Range Breakout & Retest
[Video reference](https://www.youtube.com/watch?v=Bl0CQnhSbgo&t=12s) — Break & Retest framework on **1m**:

| Step | Rule |
|------|------|
| **Daily bias** | **Bullish** daily = longs only · mark prev-day high/low |
| **Opening range** | First **5 minutes** of session — absolute high & low |
| **Breakout** | 1m **close above** 5m high (external liquidity swept) |
| **Retest** | Pullback touches 5m high (internal liquidity) · close reclaims above |
| **Risk** | SL below entry candle low · **1:2** R:R minimum |

Groww · CoinDCX · US. Conf / SL% / TP% / hold on every row.

**When to use:** Bullish daily sessions — first 5 minutes define OR; enter on 1m retest of OR high
after breakout close. Do not chase the initial breakout; wait for internal liquidity retest.

---

### INTRA — HWP · Two-Sided Gap Fill + 21 EMA
*id: `intra_hwp`*

### INTRA — HWP · Two-Sided Gap Fill + 21 EMA
[Video reference](https://www.youtube.com/watch?v=Q_TY4lQrSZc&t=24s) — the market rarely fills an
opening gap in only one direction:

| Step | Rule |
|------|------|
| **Mark the gap** | Previous Day's Close (PDC) vs Today's Open (TO) |
| **Side 1 fill** | Price tags the PDC (wick or full candle) |
| **Side 2 timing** | 5m candle **closes back through the 21 EMA** — short below on a gap down, long above on a gap up |
| **Target / SL** | Target = Today's Open · SL beyond the swing high/low since the tag (ATR-buffered) |

Groww India · US · Crypto (crypto shows "No Gap" most of the time — 24/7 trading has no real
overnight gap, which is expected). Conf / SL% / TP% / gap % / hold time on every scan row.

---

## 🎯 Scalping

### Scalp — 1m Rectangle Sniper Entry
*id: `scalp_rectangle`*

### Scalp — 1m Rectangle Sniper Entry (Mulham Trading)
[Video reference](https://www.youtube.com/watch?v=yyYwZIMrfGI) — **Rectangle Setup** on **1-minute** chart:

| Step | Rule |
|------|------|
| **Range filter** | Anchored structure · BOS strength · fresh impulse · **FVG imbalance** |
| **Sweep** | Wick through internal swing, body fails — rejection wick |
| **Rectangle** | Body top/bottom to wick extreme |
| **Entry** | 1m **close** through rectangle (sniper breakout) |
| **SL/TP** | Beyond wick extreme · min **3:1 R:R** |

Conf / SL% / TP% / hold (1–15 min) on every row.

**When to use:** 1m scalps after FVG + liquidity sweep forms a clear rejection rectangle.
Best on liquid names (indices, large caps, major crypto pairs).

---

### Scalp — SMC Rule of Three (OTE · FVG · OB · CRT)
*id: `scalp_smc`*

### Scalp — SMC Rule of Three (OTE · FVG · OB · CRT)
[Video reference](https://www.youtube.com/watch?v=8avLqVtKAhk&t=257s) — modular SMC engine:

| Layer | Rule |
|-------|------|
| **HTF** | Fractal swings · **BOS/CHoCH** · premium/discount/OTE off latest leg |
| **LTF** | **FVG** · displacement **Order Blocks** · **CRT** validated sweeps |
| **Fusion** | Long only in discount/OTE + bullish bias · short in premium + bearish |
| **Entry** | LTF confirmation inside HTF zone · deduped clustered signals |
| **SL/TP** | Structure invalidation · configurable **R:R** |

Groww · CoinDCX · US. Conf / SL% / TP% / hold on every row.

**When to use:** Structured SMC scalps when HTF bias + discount/premium OTE zone + LTF CRT/FVG/OB align.
Use 5m LTF for India; crypto/US align well with auto HTF resample.

---

### Scalp — ARC Method (Area · Range · Candle)
*id: `scalp_arc`*

### Scalp — ARC Method (Area · Range · Candle)
[Video reference](https://www.youtube.com/watch?v=T7QN-yqryr4&t=329s) — Doug's institutional boundary system:

| Step | Rule |
|------|------|
| **A · Area** | Prev-day box high/low + swing high/low — **four zones only**; no mid-box trades |
| **Gap** | Full gap above/below box → rebuild from **pre-market** high/low |
| **R · Range** | Unabated move ≥ **20%** of box range before fade is valid |
| **Target** | **50%–100%** of measured box range (default 75%) |
| **C · Candle** | **John Wick** hammer at zone → enter on **next** candle break |
| **SL** | Beyond confirmation wick tip |

Groww · CoinDCX · US. Conf / SL% / TP% / hold on every row.

**When to use:** Boundary-only institutional fades on range days — prev-day box + swing levels,
20% unabated move, John Wick hammer trigger. Avoid mid-box chop. Best on liquid NSE / US / crypto pairs.

---

### Scalp — A+ S/R Zone + 1m MSS (Joovier)
*id: `scalp_sr_mss`*

### Scalp — HTF S/R Zone + 1m MSS (Joovier A+ 3-Step)
[Video reference](https://www.youtube.com/watch?v=SdbBbc8lFQ8&t=82s) — **1H / 4H** zones forward-filled to **1-minute** execution:

| Step | Rule |
|------|------|
| **Support zone** | HTF wick **low** → lowest **body** (min open/close) |
| **Resistance zone** | Highest **body** → wick **high** |
| **Time filter** | Groww **09:15 IST** · US / Crypto **09:30 NY** |
| **Long MSS** | Support tap + **LH/LL** → break recent 1m swing **high** |
| **Short MSS** | Resistance tap + **HH/HL** → break recent 1m swing **low** |
| **SL / TP** | Beyond swing extreme · **~2.4:1 R:R** or older swing pool |

Conf / SL% / TP% / hold on every row.

**When to use:** HTF S/R zone taps with 1m MSS reversal — LH/LL into support or HH/HL into resistance,
then swing break entry. Groww after 09:15 IST; US/crypto after 09:30 NY. Default ~2.4:1 R:R.

---

### Scalp A+ — Smart Money Traps (Waqar Asim)
*id: `scalp_a_plus`*

### Scalp A+ — Smart Money Traps (Waqar Asim)
[Video reference](https://www.youtube.com/watch?v=O3Jn0U0ftgM) — from trading **smart money concepts** to trading **smart money traps**.

#### Daily map
| Step | Rule |
|------|------|
| **Trading range** | Last structural impulse — **external high / external low**; trade only inside |
| **POIs** | **Extreme** (origin) · **Decisional** (zone that caused BOS) — keep 2–3 max |
| **Liquidity** | Equal highs/lows or engineered levels as fuel |

#### POI qualification (all required)
| Filter | Rule |
|--------|------|
| **Depth** | Retrace before BOS crosses **50%** of prior leg |
| **Duration** | Multi-bar battle forming the zone (not a one-candle stall) |
| **Inducement** | Liquidity grab into the zone before the impulse |

#### Intraday → execution
| Step | Rule |
|------|------|
| **1H narrative** | Complex pullback into POI · skip early false BOS (traps) |
| **Magnets** | Prior spike / daily extreme / Asia high-low |
| **Two-leg** | Two BOS legs in bias on **1m or 5m** |
| **Entry** | Limit into resulting **FVG** |
| **Risk / TP** | SL beyond swing · **1:3** intrasession · runner **1:10** |

Conf / SL% / TP% / hold on every row.

**When to use:** Waqar Asim Scalp A+ — daily range + qualified POI (depth/duration/inducement),
skip 1H smart-money traps, execute two-leg + FVG on 1m/5m toward 1:3 / 1:10. Best when HTF POI is fresh
and price is in a complex pullback into the zone.

---

### Scalping — Gold (The Trading Geek 5-step)
*id: `scalp_gold`*

### Scalping — Gold (The Trading Geek)
[Video reference](https://www.youtube.com/watch?v=en8RMFRqSME) — 5-step high-probability **gold** scalp.

**Mindset:** Gold moves fast and respects liquidity — take the highest-probability section, in fast / out faster.

| Step | Rule |
|------|------|
| **1. Trend** | **1H** and **15m** must align (BOS → HH/HL or LH/LL) |
| **2. Markup** | Extreme demand (buys) / supply (sells) + swing liquidity (retail stops) |
| **3. Patience** | Only when price is inside a **15m POI** — never mid-nowhere |
| **4. Entry** | After **liquidity sweep** at POI: **Aggressive** = enter on sweep · **Conservative** = internal MSS then pullback to new zone |
| **5. Target** | Next 15m swing / opposite zone · SL beyond the sweep candle |

Suggested: `GC=F`, `XAUUSD=X`, `GLD`, `GOLDBEES`, … Conf / SL% / TP% / hold on every row.

**When to use:** The Trading Geek gold scalp — 1H+15m aligned, wait for 15m demand/supply POI,
enter only after a liquidity sweep (aggressive) or MSS+pullback (conservative). Best on GC=F / XAU / gold ETFs;
keep targets at the next logical pool and risk tight beyond the sweep candle.

---

### Scalp — Multi Indicator (UT Bot · QQE · VAE)
*id: `scalp_multi_indicator`*

### Scalp — Multi Indicator (UT Bot · QQE · VAE · EMA · Volume Delta)
[Video reference](https://www.youtube.com/watch?v=L3Zn_3ONytI&t=7s) — **1m** five-indicator stack:

| Indicator | Settings / Rule |
|-----------|-----------------|
| **UT Bot** | Sensitivity **3** · ATR **4** |
| **QQE** | RSI **55** · factor **8** — filter UT signals |
| **Vaddah Attar V2** | Green/red histogram · dead zone · explosion line |
| **EMA pullback** | **34** band (H/L/C) · **89** fast · **200** medium |
| **Volume delta** | Buy vs sell volume confirm at S/R |

**Long:** UT buy + QQE up + >EMA200 + pullback to 34 band + VAE + buy vol. **SL/TP:** band extreme · **2:1** R:R.

---

### Scalp — CRT-FVG (Market Structure, Liquidity & CRT)
*id: `scalp_crt_fvg`*

### Scalp — CRT-FVG (Market Structure, Liquidity & Candle Range Theory)
[Video reference](https://www.youtube.com/watch?v=o8YajmBv1-0&t=4s) — HTF liquidity sweep, LTF FVG entry:

| Step | Rule |
|------|------|
| **Trend** | SMA-based HTF bias (**1H/4H**) — trade only with prevailing trend |
| **CRT sweep** | Pullback candle's high/low = liquidity; next candle sweeps it but **closes back inside** |
| **Invalidation** | Sweeping candle closes **fully outside** the range → expansion, not rejection |
| **LTF entry** | First **Fair Value Gap** (3-candle imbalance) after the sweep, on **5m/15m** |
| **SL / TP** | Beyond the FVG · **TP1 @1:1** (close 50%, SL→BE) · **TP2** next structural high/low |

Groww · US · Crypto. Conf / SL% / TP% / hold on every row.

---

### Scalp — LiveFree FX 5m (HTF Bias · Sessions · London Sweep · BoS)
*id: `scalp_livefree_fx`*

### Scalp — LiveFree FX 5-Minute Strategy
[Video](https://www.youtube.com/watch?v=a74KPzR7phE) — HTF bias + kill zones + London liquidity sweep + 5m BoS:

| Step | Rule |
|------|------|
| **HTF bias** | Daily / 4H / 1H structure (HH/HL vs LH/LL) — trade only with the majority |
| **Sessions** | Asia → London → NY kill zones (EST for US/Crypto; IST analogue for India) |
| **Sweep** | NY wicks London high (shorts) or low (longs) and closes back inside |
| **Entry** | 5m Break of Structure + SMA-5 momentum back with HTF |
| **Risk** | SL beyond sweep extreme · TP1 @1:1 (50%, SL→BE) · TP2 next liquidity · first-win walk-away |

Groww · US · Crypto.

---

### Scalp — Heikin Ashi (100 EMA Pullback + High-Volume Doji)
*id: `scalp_heikin_ashi`*

### Scalp — Heikin Ashi (100 EMA Pullback + High-Volume Doji)
[Video reference](https://www.youtube.com/watch?v=_q-VI9hGNTE&t=28s) — trend-following 1m pullback scalp:

| Step | Rule |
|------|------|
| **Chart setup** | Heikin Ashi candles + 100 EMA, fixed 1m execution |
| **Trend filter** | Above EMA → BUYS only · Below EMA → SELLS only · Chopping through → no-trade zone |
| **Pullback** | ≥2 consecutive flat-top red (buys) / flat-bottom green (sells) HA candles — no trend-facing wick |
| **Entry trigger** | High-volume Doji ends the pullback — range bigger than at least one of the 2 preceding candles |
| **Stop / Target** | Stop beyond the Doji's far wick · strict **1:1** R:R (configurable) |

**Session window (adapted per market):** 🇺🇸 US 10:00–12:00 ET (as in the video) · 🇮🇳 India
09:45–11:45 IST (same offset/width mapped onto NSE's open) · ₿ Crypto — no restriction (24/7,
no chaotic open to avoid). Phases: OUTSIDE_WINDOW / NO_TREND / AWAITING_PULLBACK / ENTRY_TRIGGERED.

---

### Scalp — 2-Minute Momentum Burst
*id: `scalp_2min`*

### Scalp — 2-Minute Momentum Burst

Ultra-short **2m** momentum burst entries with volume and micro-structure filters. Designed for
highly liquid India / crypto pairs during active sessions.

**When to use:** Only when spreads are tight and you can manage exits within minutes.

---

## 💰 Smart Money

### SMC — CISD Entry Rule (Golden Rule)
*id: `smc_cisd`*

### SMC — CISD Entry Rule (Golden Rule)
[Video reference](http://www.youtube.com/watch?v=srSf8Zg-F6U) — avoid **early entries** on liquidity sweeps:

| Step | Rule |
|------|------|
| **Compression** | Tight rolling range — liquidity on both sides |
| **Sweep** | Wick through range edge, close back inside (stop hunt) |
| **Displacement** | Aggressive reversal into range — failure to continue |
| **CISD** | Institutional block level from reversal candle |
| **Entry** | **Close through CISD** — never buy the sweep low directly |

Multi-TF: execution TF + optional HTF bias. Conf / SL% / TP% / hold on every row.

**When to use:** Avoid early sweep entries — wait for CISD close break after compression + liquidity grab.
Multi-TF: execution TF + optional HTF bias filter.

---

### SMC — Weekly Liquidity Sweep & CISD
*id: `smc_weekly_sweep_cisd`*

### SMC — Weekly Liquidity Sweep & CISD
[Video reference](https://www.youtube.com/watch?v=jT6fvhZXSsw) — institutional reversals at **weekly liquidity**:

| Step | Rule |
|------|------|
| **Levels** | Mark **previous weekly high (PWH)** and **low (PWL)** |
| **Sweep** | Price crosses PWH/PWL — **do not enter** until failure confirmed |
| **LTF CISD** | On **5m/15m** — close back inside level on reversal candle |
| **Entry** | Immediate on CISD confirmation candle |
| **SL** | Behind sweep extreme · **TP** = opposing weekly level |

No sweep, no failure, no entry. Conf / SL% / TP% / hold on every row.

**When to use:** Swing/intraday reversals at weekly liquidity (PWH/PWL) with 5m/15m CISD confirmation.

---

### SMC — MTF Day Plan (OB · FVG · CHoCH)
*id: `smc_mtf_day_plan`*

### SMC — MTF Day Trading Plan (OB · FVG · CHoCH)
[Video reference](https://www.youtube.com/watch?v=795tKU5Zxu8) — Smart Risk 2026 day plan:

| Step | Rule |
|------|------|
| **HTF (4H/1D)** | Trend + unmitigated OB/FVG supply/demand |
| **MTF (1H↓)** | Counter-trend into HTF zone · locate demand/supply OB |
| **CHoCH** | Close through counter-trend OB — control shifts |
| **Entry** | Limit at new breakout OB · SL beyond structure · TP 1:2 + swing |

HTF/MTF/LTF selectors. Conf / SL% / TP% / hold on every row.

**When to use:** Intraday SMC day-trading plan — HTF OB/FVG → MTF CHoCH → LTF entry with defined SL/TP.

---

### SMC — Golden Bullet (Liquidity + Timing)
*id: `smc_golden_bullet`*

### SMC — Golden Bullet (Liquidity Sweep + Kill-Zone Timing)
[Liquidity Sweep](https://www.youtube.com/watch?v=2vrb_LMQeW0) ·
[Liquidity + Timing](https://www.youtube.com/watch?v=wFo4UTOPbNo):

| Step | Rule |
|------|------|
| **HTF BOS** | Map 1h/4h/1d structure — bullish/bearish break of structure |
| **Extreme POI** | Equal highs/lows · extreme supply/demand liquidity pools |
| **Kill zones** | **London 03–06 EST** · **NY overlap 08–11 EST** only |
| **V-shape sweep** | Wick invalidates inducement · close snaps back inside |
| **LTF align** | Internal structure flips back with HTF direction |
| **R:R** | Minimum **3:1** · SL beyond sweep wick |

Conf / SL% / TP% / hold / kill-zone status on every row.

**When to use:** Kill-zone timed liquidity sweeps with V-shape rejection at extreme POI pools.
EST windows: London 03–06 · NY overlap 08–11. Crypto/US align best.

---

### SMC — Liquidity (Sweeps · Grabs · FVG)
*id: `smc_liquidity`*

### SMC — Liquidity (Sweeps · Grabs · FVG)
[MASTER Liquidity Concepts](https://www.youtube.com/watch?v=lSRoNosc4zw) — order-flow structural pools:

| Concept | Rule |
|---------|------|
| **BSL / SSL** | Buy-side liquidity above swing highs · sell-side below swing lows |
| **Sweep / Grab** | Wick through structure, **close back inside** → fade toward opposite pool |
| **Liquidity run** | Expansion body ≥ 2× prior · close beyond level → continuation watch |
| **FVG** | 3-candle imbalance + ATR momentum filter · enter on gap retest |
| **Internal vs external** | Minor internal pools often swept before external extremes |

Modes: Sweep/Grab · FVG Rebalance · Both. Conf / SL% / TP% / hold on every row.

**When to use:** Structural BSL/SSL sweeps/grabs and FVG rebalance fades — order-flow liquidity pools
from OHLCV swing structure. Modes: Sweep/Grab, FVG, or Both. Target opposite pool on reversals.

---

### SM — TTG Sniper Entry (Sweep · Order Block · FVG)
*id: `smc_ttg_sniper`*

### SM — TTG Sniper Entry (Liquidity Sweep + Order Block + FVG)
[TTG Sniper Entry methodology](https://www.youtube.com/watch?v=MypSrcfiqtM&t=32s) — mechanical 5-step entry:

| Step | Rule |
|------|------|
| **1. Sweep** | Price pierces a prior swing high/low, closes back inside — liquidity trapped |
| **2. Displacement** | Move away from the sweep must exceed a configurable **× ATR** threshold, or the setup is discarded |
| **3. Order Block** | Last opposite-colour candle before the impulsive move |
| **4. Fair Value Gap** | 3-candle imbalance inside the leg, overlapping the Order Block — the precise entry zone (falls back to the full Order Block if none forms) |
| **5. Pullback entry** | **Aggressive** — enter on zone tap, SL beyond zone, fixed R:R. **Conservative** — same tap, but wait for a lower-TF market structure shift first |

**Advanced stop tip:** no FVG + wide Order Block → stop tightens to just beyond the sweep candle's
extreme instead of the whole block (that level is "protected" — a break invalidates the idea anyway).

**Context rule:** sweep direction must align with the HTF SMA trend bias (toggleable) — not every
sweep/FVG is tradeable in isolation.

Groww · US · CoinDCX. Conf / SL% / TP% / hold on every row.

---

### SMB — SnP Fashionably Late (VWAP × 9 EMA)
*id: `smb_snp`*

### SMB — SnP · Fashionably Late Scalp
[Video reference](https://www.youtube.com/watch?v=zm4ehSDIr0k&t=98s) — intraday momentum-reversal after morning LOD grind:

| Rule | Detail |
|------|--------|
| **Trigger** | **9 EMA crosses up through VWAP** after LOD established |
| **Windows** | 10:00–10:45 · 10:46–13:30 (liquidity only) |
| **Unit** | Entry (VWAP) − LOD |
| **Target** | Entry + Unit · **SL** = Entry − Unit÷3 → **3:1** R:R |
| **HTF** | Above daily 5 & 10 SMA · RVOL ≥ 1.5 |
| **Chop** | Abort if <20% of target in 10 bars post-cross |

Groww · US · CoinDCX. 1m / 5m execution.

**When to use:** Intraday **Fashionably Late** scalp — after morning LOD, wait for **9 EMA × VWAP** cross
between 10:00–13:30. 3:1 R:R from LOD unit. Best on liquid large caps with RVOL ≥ 1.5 and daily SMA support.

---

### SC — FVG (Reversal at Key Levels + Fair Value Gap)
*id: `sc_fvg`*

### SC — FVG · Reversal at Key Levels
[Video reference](https://www.youtube.com/watch?v=-xuQXmQWMCk) — "How I'd Trade $4 Into $2,000
In Only 5 Days" (Riley Coleman). Trade reversals exclusively at pre-mapped key levels, never
the middle of the range, for a mechanically favorable R:R:

| Step | What it looks for |
|------|--------------------|
| **1. HTF zones** | 15m swing highs/lows → Resistance / Support |
| **2. Unhealthy move** | A rapid, unchecked spike into the zone leaves a Fair Value Gap on the 5m chart |
| **3. Confirm the reversal** | A failed-continuation rejection candle on 1m **plus** market structure starting to shift (LH/LL for short, HH/HL for long) |
| **4. Entry** | Stop-market break of the rejection candle's structural extreme |
| **5. Risk** | Fixed **1:3** R:R (configurable), stop just beyond the rejection extreme (ATR-buffered) |

Phases: NO_ZONE / AT_ZONE_NO_FVG / AWAITING_REJECTION / ENTRY_TRIGGERED. Structure-shift
confirmation is treated as a hard requirement — a rejection candle alone does not trigger TAKE.
Groww · US · CoinDCX. Fixed 15m/5m/1m multi-timeframe (not user-selectable).

---

### SMC — SC Best (Structure · Liquidity · Displacement)
*id: `smc_sc_best`*

### SMC — SC Best (Structure · Liquidity · Displacement)

Smart-money confluence of market structure, liquidity sweeps, and displacement candles into a
single ranked entry model.

**When to use:** When you want a stricter SMC filter than CISD alone.

---

### SMC — Lewis Kelly (Kill Zone · Sweep · MSS)
*id: `smc_lewiskelly`*

### SMC — Lewis Kelly (Kill Zone · Sweep · MSS)

Session **kill-zone** liquidity sweep + market structure shift model (Lewis Kelly framework).

**When to use:** London / NY kill zones on FX-style or liquid equity index futures proxies.

---

## 📐 Pro Trade

### Volume Profile CE — VA reversal · POC compression · I-profile LVN
*id: `volume_profile_ce`*

### Volume Profile CE — VA · POC · I-profile
[Abhishek Kar masterclass](https://youtu.be/67u8mdQ8f08)

Three Volume Profile playbooks in one Pro Trade scanner:

| Setup | Rule |
|-------|------|
| **VA reversal** | Price tags VAL/VAH with hammer / shooting-star rejection → fade toward POC then opposite VA edge |
| **POC compression** | Multi-day POCs sit in a tight band → trade the breakout of the band |
| **I-profile LVN** | Price enters a low-volume void and slices through — ride the vacuum move |

**Backtest note:** Strategy Lab uses a historical OHLCV approximation of the live scanner — research / education only.

**When to use:** Liquid names with clear session volume profiles (indices, large caps, majors).

**When to use:** Session value-area fades, multi-day POC compression breakouts, or I-profile LVN vacuum moves.
Live scanner is under **Pro Trade**; Strategy Lab backtest uses a historical approximation.

---

### Volume Profile POC — first-touch HVN pullback
*id: `volume_profile_poc`*

### Volume Profile POC — first-touch HVN pullback
[Video reference](https://www.youtube.com/watch?v=ooHX6tf5RVI)

| Step | Rule |
|------|------|
| **1. Build HVN zone** | Fixed-range Volume Profile around POC |
| **2. Breakout** | Price closes beyond the HVN zone |
| **3. Entry** | **First** retest of the zone edge only — no second chances |
| **4. Risk** | Stop in an LVN behind the HVN barrier; target just before the next HVN shelf |

**Backtest note:** Historical signal-frame approximation of the live Pro Trade scanner.

**When to use:** After a clean HVN break when you want a high-probability pullback entry.

**When to use:** After price breaks an HVN/POC zone — enter only on the **first** retest of the zone edge; stop in LVN.

---

### PA - Volume Profile — FVG + VP cluster · S/R flip
*id: `pa_volume_profile`*

### PA - Volume Profile — FVG + VP · S/R flip
[Trader Dale institutional volume filter](https://www.youtube.com/watch?v=FVoXWlNkdhs)

| Setup | Rule |
|-------|------|
| **FVG + VP** | 3-candle fair value gap with fixed-range POC clustered at the gap start |
| **S/R flip** | Broken pivot support/resistance with volume cluster — trade the **first** retest only |

Stops sit beyond the VP cluster / flipped level. Targets from gap extension or measured move.

**Backtest note:** Formation-bar + first-retest proxy of the live scanner.

**When to use:** When you want Price Action entries filtered by institutional volume location.

**When to use:** Trader Dale-style FVG + volume cluster entries, or S/R flips with VP confirmation on the first retest.

---

### PA-VP-SMC — Price Action + Volume Profile + Smart Money confluence
*id: `pa_vp_smc`*

### PA-VP-SMC — Price Action + Volume Profile + Smart Money
The "best of everything" Pro Trade confluence model:

| Pillar | What it checks |
|--------|----------------|
| **Trend** | EMA / structure bias |
| **Liquidity** | Sweep / stop-hunt failure |
| **SMC zone** | Order Block / FVG |
| **Volume Profile** | POC / HVN / VA levels |
| **VSA** | Thrust / no-supply / no-demand confirmation |

Prefer high-confidence rows where multiple independent pillars agree.

**Backtest note:** Single-TF confluence proxy (EMA + sweep + VSA) — not a perfect replay of the live multi-engine score.

**When to use:** Highest-conviction Pro Trade setups when you want confluence before size.

**When to use:** Highest-confluence Pro Trade setups — require multiple pillars (trend, sweep, VP, SMC) before size.

---

### Volume Spread - Next Candle — VSA Downthrust / Upthrust
*id: `volume_spread_next_candle`*

### Volume Spread - Next Candle — VSA SOS / SOW
[Wyckoff VSA playlist](https://www.youtube.com/watch?v=ncrqXFCQKOU&list=PLXWi52aRZnNF_HW-TedxAE1Tyx1C8XrGn)

| Signal | Meaning | Bias |
|--------|---------|------|
| **Downthrust** | Wide spread down on ultra-high volume that closes strong | SOS → long next candle |
| **No Supply** | Narrow/down bar on low volume after selling | SOS → long next candle |
| **Upthrust** | Wide spread up that fails near highs on volume | SOW → short next candle |
| **No Demand** | Narrow/up bar on low volume after buying | SOW → short next candle |

Primary edge is the **next candle** after the signal bar. Stop beyond the signal extreme.

**Backtest note:** Maps SOS/SOW flags to ±1 signals for Strategy Lab.

**When to use:** Short-hold VSA confirmation after climactic volume events.

**When to use:** Wyckoff VSA SOS/SOW bars — edge is primarily the **next candle** after Downthrust / No Supply / Upthrust / No Demand.

---

### Elliott Wave — impulse / corrective Pro Trade scanner
*id: `elliott_wave_pro`*

### Elliott Wave (Pro Trade)

Pro Trade watchlist scanner for impulse / corrective wave structure on India · US · Crypto · Commodity
tickers. Complements the Technical Analysis **Elliott Wave Screener** with the Pro Trade asset-class
picker and Ask AI / Predict Next Move flow.

**When to use:** Swing / positional wave counts; pair with **Fibonacci Pro** for golden-zone targets.

**When to use:** Pro Trade Elliott impulse/corrective scanner on a watchlist — pair with Fibonacci Pro for targets.

---

### Fibonacci Pro — golden-zone pullback · multi-strategy Fib
*id: `fibonacci_pro`*

### Fibonacci Pro

Multi-strategy Fib toolkit (golden-zone pullbacks and related Fib evaluations) across
India · US · Crypto · Commodity.

**When to use:** Pullback entries into 0.618–0.65 after an impulse; combine with Ticker Chart S/R.

**When to use:** Golden-zone Fib pullbacks and multi-strategy Fib evaluations on India / US / Crypto / Commodity.

---

### BB Mean Reversion — %B stretch · squeeze · S/R confluence
*id: `bb_mean_reversion`*

### BB Mean Reversion

Bollinger %B stretch confirmed by regime filter (Efficiency Ratio), RSI, candlestick reversal,
volume climax, and Support/Resistance confluence.

**When to use:** Range / mean-reversion days — skip when ER shows a strong trend (hard block).

**When to use:** Mean-reversion when %B stretches and S/R + RSI + volume climax agree — avoid strong-trend (high ER) regimes.

---

### Buy Today Sell Tomorrow — closing-strength BTST / STBT
*id: `btst`*

### Buy Today Sell Tomorrow (BTST / STBT)

Closing-strength (CLV) signature confirmed by trend, volume, relative strength vs Nifty, VWAP,
RSI chase-risk guard, options OI buildup, late-session fade check, and this ticker's own
historical follow-through rate.

**When to use:** Overnight India cash/F&O carries when multiple confirmation pillars agree.
Supports background jobs and saved reports.

**When to use:** Overnight BTST / STBT when closing strength (CLV), volume, RS, VWAP, and optional OI buildup align.

---

### Ticker Chart — daily / intraday with S1/S2 · R1/R2
*id: `ticker_chart`*

### Ticker Chart — OHLC + Support / Resistance

Pro Trade charting for **India · US · Crypto · Commodities**.

| Control | Behavior |
|---------|----------|
| **Asset class** | India / US / Crypto / Commodities |
| **Ticker** | Autosuggest as you type (same suggestion API as watchlist) |
| **Daily range** | From / To — chart loads automatically once ticker + dates are set |
| **Same-day intraday** | Session date + bar size (1m–1h); Yahoo history windows apply |

**Levels:** Green dashed **S1/S2** (nearer / deeper support) · Red dashed **R1/R2** (nearer / higher resistance).

**When to use:** Quick visual of any ticker before running a scanner; confirm levels for SL/TP placement.
Educational chart only — not a trade signal by itself.

**When to use:** Fast OHLC chart for any India / US / Crypto / Commodity ticker with auto S1/S2 · R1/R2.
Daily date range or same-day intraday; chart draws as soon as ticker + dates are set (autosuggest ticker box).

---

## 📉 Options

### Double Calendar — dual-expiry premium capture
*id: `double_calendar`*

### Double Calendar — dual-expiry premium capture

Options strategy that sells a nearer-expiry calendar and buys a farther one (or dual calendars)
to harvest theta while defining directional/volatility exposure.

**When to use:** Elevated IV environments around events when you expect IV crush after the event.

---

### Delta Neutral — volatility / premium strategies
*id: `delta_neutral`*

### Delta Neutral — volatility / premium strategies

Constructs near **delta-neutral** option structures (straddles / strangles / iron flies as
configured) to trade volatility rather than direction.

**When to use:** When implied vol is mispriced vs expected realized move and you can hedge delta.

---

### Hedging — protective overlays · beta · pairs
*id: `hedging`*

### Options Hedging

Protective overlays and hedge constructions around an existing directional or portfolio view
(beta, pairs, or defined-risk option hedges depending on configuration).

**When to use:** After a bullish/bearish view is set — reduce tail risk without fully exiting.

**When to use:** Protective overlays, beta hedges, and pairs-style option hedges around an existing view.

---

### Gokul Chhabra — 3m VWAP · VWMA · SuperTrend ITM options
*id: `gokul_chhabra`*

### Gokul Chhabra — 3m VWAP · VWMA · SuperTrend ITM Option Buying

[Masterclass](https://www.youtube.com/watch?v=2RnBT9DDDNI&t=6s) by Dr. Gokul Chhabra.

| Piece | Rule |
|-------|------|
| Chart | 3-minute (1m resampled) Nifty / Bank Nifty index as futures proxy |
| Indicators | Session VWAP · VWMA(20) · SuperTrend(10, 3) |
| Window | 09:45–15:15 IST only · flat by close · no BTST |
| Buy Call | Close strictly above VWAP, VWMA, and SuperTrend |
| Buy Put | Close strictly below all three |
| Sideways | Mixed alignment → no trade |
| Entry polish | Prefer VWMA pullback if the breakout was missed |
| Risk | SL = 3m close beyond SuperTrend · trail to cost at 1:1 · target ≥ 1:2 |
| Execution | Buy ITM options targeting delta **0.60–0.75** (live NSE chain) |

**How to use:** Open **Options → Gokul Chhabra**, pick Nifty 50 / Bank Nifty, scan. Expand a
**BUY CALL / BUY PUT** row for SuperTrend SL/TP and the suggested ITM strike.

---

### Zero to Hero — high-conviction options progression
*id: `zero_to_hero`*

### Zero to Hero

Structured high-conviction options progression playbook (see in-app guide on Options → Zero to Hero).

**When to use:** When you want a staged options plan rather than a one-shot directional buy.

**When to use:** Structured high-conviction options progression setups (see Options → Zero to Hero guide).

---

### Market Prediction — derivatives conviction vs hollow move
*id: `market_prediction`*

### Market Prediction — derivatives conviction vs hollow move

Checks whether today's index or stock move is backed by conviction in the NSE options chain
(and related context), or is a **hollow** move — price rising while derivatives quietly price doubt.

| Signal | Idea |
|--------|------|
| Synthetic futures premium/discount | Put-call parity stand-in for futures LTP |
| OI buildup | Long/Short Buildup vs covering/unwinding |
| IV skew | Put vs Call ATM IV (hedging demand) |
| PCR / Max pain | Broader positioning picture |
| India VIX | Fear rising into a rally (or vice versa) |
| Late-session move | Outsized last-5-minute swing |
| FII/DII cash flow | Institutional cash vs the move |

**When to use:** Before trusting a big day on Nifty / Bank Nifty / F&O stocks — pair with
**Advance Decline** and **Option Chain**. Open from Dashboard quick link or Options → Market Prediction.

**When to use:** Before trusting today's index/stock move — check whether derivatives (synthetic futures, OI, IV skew, PCR, VIX, FII/DII) back the tape or call it hollow.

---

### Call Put Writing — OI walls · short covering
*id: `call_put_writing`*

### Call Put Writing — OI walls & short covering

Desk-style read of **who is writing Calls vs Puts** on the India F&O option chain.

| Signal | Idea |
|--------|------|
| Call OI / fresh Call ΔOI walls | Near-term **resistance** — writers defend the ceiling |
| Put OI / fresh Put ΔOI floors | Near-term **support** |
| Writing tilt | Call-writing dominant (bearish ceiling) vs Put-writing dominant (bullish floor) |
| PCR (OI) / Max Pain | Broader positioning + expiry magnet |
| OI buildup | Long/Short Buildup vs covering / unwinding |
| Short-covering risk | Spot testing or breaking the Call wall → squeeze / covering rally |

**Video framing:** Weekly outlooks that highlight heavy Call writing at a strike (e.g. 24,600)
as hard resistance, Put writing as support, and short-covering if the Call wall breaks.
FII/Pro vs retail participant OI is **not** auto-fetched — use chain OI; treat external
participant files as manual context only.

**When to use:** Options → Call Put Writing before fading a ceiling or buying a floor on Nifty / Bank Nifty / F&O stocks.

### Profitable — Overnight Options Buy-Stop
*id: `profitable`*

Source: https://www.youtube.com/watch?v=w_8cVFZ1iZE

**Market DNA:** Overnight gaps drove most of a long Nifty sample’s net points; cash-session-only longs could lose. React — don’t anticipate. Plan CE and PE before the open.

| Step | Rule |
|------|------|
| 09:20 IST | CE & PE premium in ₹50–₹75 (prefer ~₹62.5) |
| Entry | Buy-stop +50% of mark (not the mark itself) |
| Stop | −50% of entry premium |
| Hold | Prefer overnight carry |
| Universe | Nifty · Bank Nifty · Midcap Nifty |

**When to use:** Options → Profitable for a reactive overnight option-buy desk.

---

## 📓 Demo Trading

### Demo Trading — India (Groww)
*id: `demo_india`*

### Demo Trading — India
Paper NSE/BSE portfolio (login required). Virtual capital, live P&L, order history.

**When to use:** Practice setups from screeners before live Groww orders.

---

### Demo Trading — Crypto (CoinDCX)
*id: `demo_crypto`*

### Demo Trading — Crypto
Paper CoinDCX-style futures ledger — separate from India demo book.

**When to use:** Practice Smart Wave, crypto MTF bias, and fakeout setups before live orders.

---

## 🔔 Alerts

### Strategy Alert Monitors
*id: `alerts`*

### Strategy Alert Monitors
Live polling of **Multi-Combo saved picks**. Telegram/email when entry rules match latest bar.

**Setup:** Login → Multi-Combo save combos → Alerts → create monitor → configure channels.

---

## 🔖 Watchlist

### Watchlist — Track Tickers · % Change Since Added
*id: `watchlist`*

### Watchlist — Track Tickers · % Change Since Added
Per-user, per-market (India / US / Crypto) watchlists — login required.

**Flow:** Create a named watchlist → search & add a ticker (its price is captured at add-time) →
table shows **last traded price** and **% change since added** (color-coded) → 🔄 refresh prices ·
🗑️ remove a ticker · delete the whole watchlist.

**When to use:** Track a shortlist of tickers without re-running a scanner each time.

---

_Trading hubs registry skipped: 'list' object has no attribute 'items'_

## Additional desks & guides

### Prediction — Astro Finance
*id: `astro_finance`*

### Prediction — Astro Finance
Financial astrology timing desks (Harshubh Shah · Rahul Bhatnagar):

| Desk | Rule |
|------|------|
| **Lunar Cycle** | Amavasya / Poornima windows + historical forward stats |
| **Amavasya S/R** | Permanent S/R from New-Moon session highs/lows |
| **Bhadra Timing** | Vishti Karana windows overlapping cash session |
| **Transit Gaps** | Mars/Venus Gochar ingress ±1d vs overnight gaps |
| **Trading Calendar** | Ashtakvarga-lite Moon days + Muhurat + commodity↔planet map |

Videos: https://www.youtube.com/watch?v=xP-rt9tU79U · https://www.youtube.com/watch?v=xZ84XDFInEI · https://www.youtube.com/watch?v=G1WYa0VgA7A

Always double-confirm with technical analysis. Research / education only.

---

### Big Whale
*id: `big_whale`*

### Big Whale Pump & Dump — On-chain discovery
**Market Pulse** — video playbook for finding coins **before** the next pump:

1. **24h pumped tokens** — DexScreener boosted + high `priceChange.h24`
2. **Big trades** — top 24h volume on those pairs (open DexScreener for swap size)
3. **Wallet trace** — links to **Solscan** / **BscScan** Holders & Transfers (manual)
4. **Accumulation** — buy pressure + moderate pump + volume (whale entry proxy)
5. **Liquidity inflows** — highest USD liquidity + volume (capital gathering)

Chains: **Solana**, **BNB**, optional Base/Ethereum. Requires network. Not live wallet API — explorer deep-links for steps 3–4.

| Trade | When |
|-------|------|
| **BUY** | Accumulation / pre-pump watch / liquidity inflow + buy pressure |
| **SELL** | Extended 24h pump + distribution volume / sell pressure |
| **SL / TP** | ~3% / 15% base; wider on thin pools or extreme pumps |

---

### Buy Sell
*id: `buy_sell`*

### Buy or Sell — Multi-Asset Trade Advisor
Four tabs — **Crypto · Indian stocks · US stocks · Commodity** — with typed ticker search, multiselect symbols, and **multi-timeframe** analysis.

| Asset class | TA profile |
|-------------|------------|
| Crypto | Crypto momentum + Smart Wave |
| India | India intraday scalp (SMC Flow, session bias) |
| US / Commodity | Swing / positional (S/R, confluence, MTF) |

**Output:** **TAKE LONG/SHORT** or **NO TRADE**, **confidence %**, **SL %**, **TP %**, engine confluence list, and **AI View** synthesis.

Pick tickers → durations → **Analyse & suggest Buy / Sell**. Requires network; India optional Groww token.

---

### Elliott Wave Pro Trade
*id: `elliott_wave_pro_trade`*

### Elliott Wave (Pro Trade)

Pro Trade watchlist scanner for impulse / corrective wave structure on India · US · Crypto · Commodity
tickers. Complements the Technical Analysis **Elliott Wave Screener** with the Pro Trade asset-class
picker and Ask AI / Predict Next Move flow.

**When to use:** Swing / positional wave counts; pair with **Fibonacci Pro** for golden-zone targets.

---

### Footprint
*id: `footprint`*

### Footprint — order-flow confirmation at key levels
[I Studied Order Flow Trading for 5 Years — Footprint Charts Beat Everything](https://www.youtube.com/watch?v=kcglxDJ_ZF0)

**Important:** this app has OHLCV candles, not real bid/ask tick data. Buy/sell volume per bar is estimated from
where the close sits within its own high-low range (the same proxy the Scanner's Order Flow Imbalance strategy
already uses) — an honest approximation, not real Level 2 depth.

| Step | What it checks |
|------|------|
| **1. Delta** | Buyers minus estimated sellers over the recent bars — who's winning. |
| **2. Imbalances** | 3+ stacked bars where one side overwhelms the other — an institutional "fingerprint". |
| **3. Absorption** | High volume, small body — a wall quietly absorbing the aggressive side at the level. |

**Strict order of operations:** only fires once price taps a key HTF level AND all three steps confirm, in order.
Partial confirmation shows as WATCH with exactly which step is still missing.

**When to use:** as confirmation at levels you already care about — not a standalone signal generator.

---

### Intra Hedging
*id: `intra_hedging`*

### Intra-Hedging — sector relative-strength long/short (beta-neutral)

**The core idea:** a classic institutional Long/Short Equity approach applied to Nifty sectors — buy the strongest
sector, short the weakest, sized so their Beta-weighted exposure matches. This strips out the broad Nifty's own
direction and trades only the DIFFERENCE in momentum between the two sectors — if the whole market suddenly moves,
the other leg offsets it.

| Step | What it does |
|---|---|
| **1. Universe** | Every major Nifty sectoral index this app can resolve OHLC for (28 sectors) — heavyweights (Banking, IT, Financial Services, Energy) and smaller/thematic ones (Defence, Tourism, Housing, ...) alike; newer indices without a listed Yahoo ticker fall back to a constituent-stock proxy. |
| **2. Momentum ranking** | Ranks every tracked sector strongest to weakest. Intraday timeframes (5m/15m/30m/1h) use today's session open vs. now; swing timeframes (4h/1d/1wk) use a close-to-close return over a timeframe-appropriate lookback (roughly 4 trading days/1 week/1 month respectively). |
| **3. Divergence gate** | Too small a spread between the strongest and weakest = no clear rotation today — sits out rather than forcing a weak pair. |
| **4. Long/Short pair** | Strongest sector = LONG leg; weakest sector = SHORT leg. |
| **5. Beta-neutral sizing** | Each leg's Beta vs. Nifty 50 (90-day daily returns) sets its capital split — the higher-Beta leg gets less capital so both sides carry equal volatility-weighted exposure. |
| **6. Execution** | ETF route (every verified, liquid ETF for that sector listed, not just one) or the Stock route (buy/short the sector's top 5 weighted constituents directly). Cash-market shorting is broker-restricted intraday and can't be carried overnight for swing — the short leg typically needs sector futures either way. |

**Intraday vs. swing:** pick the momentum timeframe to match how you want to trade. 5m-1h runs same-day,
flat-by-close, after the first 30 minutes of trading. 4h/1d/1wk runs as a multi-day/week rotation — hold per the
timeframe's guidance and re-run the scan periodically to rotate into new leaders as the ranking shifts. Either way,
if the spread is below the divergence threshold, there's no clean pairs setup right now — wait rather than forcing
a trade.

**Math:** Beta = `covariance(sector, Nifty 50) / variance(Nifty 50)`; capital split =
`long_weight = short_beta / (long_beta + short_beta)`, `short_weight = long_beta / (long_beta + short_beta)`.
Not a backtested edge — a structured framework for a well-known relative-strength pairs concept. Research /
education only, not financial advice.

---

### Investigation
*id: `investigation`*

### Ticker Investigation — News · Price Action · S/R · Strategies
Four tabs — **Crypto · Indian stocks · US stocks · Commodity**. Enter comma-separated tickers → **Search & investigate**.

| Tab | Tickers | Data |
|-----|---------|------|
| Crypto | CoinDCX USDT pairs | CoinTelegraph, CoinDesk, … |
| India | NSE symbols | Moneycontrol, LiveMint, ET Now, … |
| US | NYSE/Nasdaq | Yahoo, MarketWatch, Seeking Alpha, … |
| **Commodity** | Yahoo futures `CL=F`, `GC=F`, `SI=F`, `HG=F`, `NG=F`, `ZW=F` | Moneycontrol Commodities, macro RSS, Google News |

| Output | Detail |
|--------|--------|
| News | RSS from **Investing.com**, Moneycontrol, LiveMint, ET Now, Zee Business, NDTV Profit, Yahoo, MarketWatch, CoinTelegraph, Google News (`site:investing.com`), and more |
| Analyst calls | **Upgrades · downgrades · re-ratings · initiations · price targets** from Moneycontrol brokerage RSS, Seeking Alpha, Benzinga, Google News |
| Price moves | % change over **5d · 24h · 4h · 1h · 15m · 5m** + RSI zone per window |
| **Price Action** | Same engine as PA screener — trend, RSI div, EMA stack, Fib golden zone, **session VWAP**, **RVOL**, **MFI**, SMC OB/FVG, Elliott/candle/chart patterns, **approaching WATCHLIST** alerts |
| S/R | Nearest **weak/strong** support & resistance · **breakout %** · **breakdown %** · bias by TF |
| **Suggested trades** | Ranked ideas with **confidence % · SL % · TP % · R:R** — TAKE / WATCH / MONITOR from PA + S/R + MTF + news + analysts |
| Strategies | Alternate **scalp / swing** setups in table form |
| Trade setup | Primary **TAKE LONG / SHORT / NO TRADE** — best blended setup with trade plan |
| Ask AI | **AI Trade Setup** (SL/TP/confidence) + full investigation synthesis |

India: optional Groww token for live intraday bars. Commodity: Yahoo Finance futures (no Groww).

---

### Investigation Strategies
*id: `investigation_strategies`*

### Ticker Investigation — Select Strategy
Same as **Ticker Investigation** (Crypto · India · US · Commodity) **plus** user-selected hub strategy engines.

| Step | Action |
|------|--------|
| **1** | Pick **one or more** strategies from the dropdown (all TA hub + swing engines) |
| **2** | Enter ticker(s) in any asset tab → **Search & investigate** |
| **3** | Review news · PA · S/R · analysts · **merged** suggested trades & primary setup |

Selected engines run live `analyze_ticker` per symbol; signals merge into ranked trades alongside rule-based confluence.

---

### Kn Smart Rsi
*id: `kn_smart_rsi`*

### KN Smart DP SL + RSI MTF + VWMA

**Reference:** [YouTube walkthrough](https://www.youtube.com/watch?v=2bAwEz12MrE)

| Layer | Role |
|-------|------|
| Daily VWMA(20) | Master trend — above=bull, below=bear |
| KN Smart ribbon | EMA5/12 midpoint entry + ATR×1.5 chandelier SL |
| RSI(14) vs SMA(RSI) | Bull above 50, bear below 50 |
| MTF dashboard | Fast>slow EMA on **≥3 of 4** TFs (1m,5m,15m,1h) |

**LONG:** bullish master + ribbon bull + green close above entry + RSI>50 + MTF≥3.

**Exit:** trail SL, RSI>80/<30, TP1/2/3 at 1×/2×/3× ATR. Hold **15 min – 3 hours** on 3m/5m. Groww and CoinDCX.

---

### Oil Dollar Bond Macro
*id: `oil_dollar_bond_macro`*

### Oil · Dollar · Bond — Macro Tape

Command Center (and **Dashboard**) macro panel for:

| Instrument | Typical Yahoo symbol |
|------------|----------------------|
| US Dollar Index | DX-Y.NYB |
| Brent Crude | BZ=F |
| US 2Y / US 10Y | ^UST2Y / ^TNX (futures fallbacks) |
| Gold / Silver | GC=F / SI=F |
| Nifty 50 · Dow 30 · Nasdaq | ^NSEI · ^DJI · ^IXIC |
| Bitcoin · Ethereum | BTC-USD · ETH-USD |

**Modes**

| Mode | Controls |
|------|----------|
| **Daily** | From / To date range → 1d bars |
| **Intraday** | One session date + 1m / 5m / 15m / 30m / 1h |

Each instrument chart draws **S1/S2 (support)** and **R1/R2 (resistance)** from swing pivots in the window.
A normalized **% change overlay** compares direction across units (no S/R on the overlay).

**AI Predictor — Next Move:** RISK-ON / RISK-OFF / MIXED / WAIT with per-instrument UP/DOWN/FLAT leans.

**When to use:** Morning or overnight macro regime; pair with Advance Decline + Comparative Strength before equity size.

---

### Opposite Hedge
*id: `opposite_hedge`*

### Opposite Hedge-MTF
Long the **leading** sector and short the **lagging** sector from both rotation feeds — profit the **spread delta**.

| Source | Windows |
|--------|---------|
| Intraday rotation | Minutes · Hours · Days |
| HTF rotation | Daily · Weekly · Monthly |

**Per window:** long ticker + % alloc + confidence + SL/TP + hold duration · same for short leg.

**Consensus row** votes the best pair across all six windows. Buy long in cash/ETF; short via F&O or paired instrument.

---

### Pro Trade Elliott Wave
*id: `pro_trade_elliott_wave`*

### Elliott Wave (Pro Trade)

Pro Trade watchlist scanner for impulse / corrective wave structure on India · US · Crypto · Commodity
tickers. Complements the Technical Analysis **Elliott Wave Screener** with the Pro Trade asset-class
picker and Ask AI / Predict Next Move flow.

**When to use:** Swing / positional wave counts; pair with **Fibonacci Pro** for golden-zone targets.

---

### Pro Trade Ticker Chart
*id: `pro_trade_ticker_chart`*

### Ticker Chart — OHLC + Support / Resistance

Pro Trade charting for **India · US · Crypto · Commodities**.

| Control | Behavior |
|---------|----------|
| **Asset class** | India / US / Crypto / Commodities |
| **Ticker** | Autosuggest as you type (same suggestion API as watchlist) |
| **Daily range** | From / To — chart loads automatically once ticker + dates are set |
| **Same-day intraday** | Session date + bar size (1m–1h); Yahoo history windows apply |

**Levels:** Green dashed **S1/S2** (nearer / deeper support) · Red dashed **R1/R2** (nearer / higher resistance).

**When to use:** Quick visual of any ticker before running a scanner; confirm levels for SL/TP placement.
Educational chart only — not a trade signal by itself.

---

### Reversal Strategy
*id: `reversal_strategy`*

### Reversal Strategy — the 6-step counter-trend/range checklist
[The ONLY Reversal Trading Strategy You'll Ever Need (Step-by-Step)](https://www.youtube.com/watch?v=Lz9XmfDLXxI&t=155s)

**The core idea:** reversal trading leans on momentum divergence and exhaustion at a level, not moving-average
trend-following — you're betting the current move is running out of steam.

| Step | What it checks |
|---|---|
| **1. Market Condition** | Bullish (HH/HL), bearish (LL/LH), ranging (oscillating between a top and bottom), or choppy — choppy markets are skipped outright. |
| **2. Market Phase** | A reversal wants the exhaustion of a run (an extended push, measured against ATR), not a fresh pullback. |
| **3. Support/Resistance** | Horizontal zones from swing rejection clusters (with a round-number "handle" note), plus angular trendlines from the last two swing points. |
| **4. MACD Divergence** | Price makes a new high/low that MACD does not confirm — momentum fading at the level. |
| **5. Deceleration** | Candle bodies progressively shrinking on approach to the level. |
| **6. Candlestick Trigger** | Low/High Test candle, Tweezer Top/Bottom, Doji, or Inside Bar on the signal candle. |

**Execution:** entry a touch beyond the signal candle's extreme; stop just beyond its opposite extreme (ATR-based
buffer stands in for the video's "3-5 pips" since this app trades equities/crypto/commodities, not forex). Minimum
1:1 reward:risk enforced.

**Take profit:** Auto targets the 50 EMA in a trending market condition (price reverting to the mean), or the next
major level while ranging — or pin it to one mode directly.

**When to use:** a patience-first strategy that deliberately sits out choppy markets — pending setups can go
unconfirmed for days. Works across Groww India, US, Crypto, and Commodities.

---

### Sentiment Screener
*id: `sentiment_screener`*

### Institutional-Grade Sentiment Engine — Full Breakdown

Combines **25+ technical checks** into a composite score from **-100 (Extreme Bearish)** to **+100 (Extreme Bullish)**.

#### Core categories
1. **EMA stack** (9/21/50/200) — trend backbone
2. **Bollinger Bands** — squeeze, band rejection, breakout
3. **RSI(14)** — momentum zones + divergence
4. **MACD(12,26,9)** — histogram shift signals
5. **ADX(14)** — trend strength (>25 = strong)
6. **Stochastic(14,3,3)** — OB/OS cross confirmation
7. **Volume** — ratio vs 20MA, OBV, spike/dry filters
8. **VWAP** — institutional buy/sell side
9. **Supertrend(10,3)** — ATR trail direction
10. **Pivot points** — R1/R2/S1/S2 breaks
11. **Fibonacci** — golden zone 0.618–0.65
12. **Candlesticks** — 10+ bullish/bearish patterns
13. **S/R breakouts** — volume-confirmed only
14. **SMC** — order blocks, FVG, liquidity sweeps
15. **Reversals** — RSI extreme + pattern + volume

#### Trade signals (ATR-based)
| Score | Signal |
|-------|--------|
| ≥ +15 | BUY — SL = entry − 1.5×ATR, TP = entry + 2×ATR |
| ≤ −15 | SELL — inverted |
| −15 to +15 | WAIT |

#### Score ratings
| Range | Rating |
|-------|--------|
| +65 to +100 | STRONG BUY |
| +35 to +65 | BUY / BULLISH |
| −10 to +10 | NEUTRAL |
| −65 to −35 | SELL / BEARISH |
| −100 to −65 | STRONG SELL |

Multi-TF ranking on Groww and CoinDCX. Educational use only — confirm with risk management.

---

### Smc Fake Shift
*id: `smc_fake_shift`*

### SMC — Fake Market Shift (Groww & CoinDCX)

**3-step SMC model:**

| Step | What it does |
|------|----------------|
| 1 Structure | Causal fractal swings → HH/HL/LH/LL → **Break of Structure (BOS)** sets trend bias |
| 2 POI | Map **extreme zone** / order block that originated the BOS leg (demand after bullish BOS, supply after bearish) |
| 3 Fake shift | Pullback into POI → internal structure → inducement breakout → **liquidity sweep** → reversal |

**Entry models:**
- **A Aggressive** — stop at sweep candle extreme; SL beyond liquidity-grab wick; default R:R 1:2
- **B Conservative** — wait for **Market Structure Shift** (close breaks internal high/low), limit entry on **flip-zone** mitigation; default R:R 1:3

Backtester simulates pending stop/limit fills, then SL vs TP. Tune swing left/right, POI lookahead, and entry model to your timeframe (5m–1d). Educational — sweep detection is heuristic.

---

### Smc Five Filter
*id: `smc_five_filter`*

### 5 SMC Filter — the 5 checks that separate A+ trades from bad ones
[The 5 Smart Money Filters That Separate A+ Trades From Bad Trades](https://www.youtube.com/watch?v=uzeLz80FVVY&t=54s)

| Filter | What it checks |
|---|---|
| **1. Permission** | Price must come from an UNMITIGATED higher-timeframe supply/demand zone — that zone alone tells you which side you're allowed to trade (demand = buys only, supply = sells only). |
| **2. Footprint** | The zone's origin must be a liquidity sweep of a prior swing, followed by a sharp displacement — the real fingerprint of smart money, not random consolidation. |
| **3. Inefficiency** | An unfilled Fair Value Gap must sit in the same leg — the imbalance that makes the zone "magnetic". |
| **4. Location** | The zone must sit in the discount half of the range for buys, or the premium half for sells. Mid-range setups are rejected outright. |
| **5. Exit Test** | There must be untouched higher-timeframe liquidity ahead of price, far enough away to clear a minimum reward:risk. No target room = no trade. |

All 5 must pass together for a setup to count as A+ — the live scan shows each filter's pass/fail individually.

**3 entry models, once a setup passes all 5 filters:**
- **Aggressive** — enter the moment price is inside the zone (limit at the zone midpoint), stop just beyond the zone. Rarely misses a trade, but no reversal confirmation.
- **Conservative** — wait for price to tap the zone AND a lower-timeframe Change of Character (ChoCh) to confirm the reversal. Tighter stop, better R:R.
- **Ultra-Conservative** — stacks a second confirmation on top of Conservative: after the ChoCh, also wait for a same-direction lower-timeframe continuation Fair Value Gap. Exceptional R:R and precision, but the most frequently missed entries of the three.

**When to use:** when you want the strategy to say no far more often than yes.

---

### Support Resistance
*id: `support_resistance`*

### Support and Resistance — break, retest, confirm
[The Strategy That Made Me My First $1,000,000 Trading](https://www.youtube.com/watch?v=d5T-k_-ejd0&t=29s)

**The core idea:** resistance is a "roof" where sellers have stepped in before; support is a "floor" where buyers
have stepped in before. A strongly-broken roof often becomes the new floor on the next visit (and the mirror image
for a broken floor becoming a new roof).

| Step | Rule |
|------|------|
| **1. Draw zones, not lines** | HTF resistance zone = highest wick down to highest body in a rejection cluster; support zone = lowest wick up to lowest body. |
| **2. Break and retest** | A strongly broken zone flips role for the next visit — old resistance becomes new support, and vice versa. |
| **3. Alert, don't stare** | Nothing happens until price actually taps back into a zone. |
| **4. LTF confirmation** | After the tap, wait for a clean break of the most recent LTF lower high (longs) or higher low (shorts) — never enter on the tap alone. |
| **5. Entry** | At the structure break. Stop beyond the zone. Target the next recent structural high/low. |

**When to use:** a deliberately low-screen-time strategy across every asset class this hub supports (India via Groww,
US, Crypto, Commodities) — set the zone, walk away, engage only once price taps it and structure confirms.

---

### Ticker Investigation Strategies
*id: `ticker_investigation_strategies`*

### Ticker Investigation — Select Strategy
Same as **Ticker Investigation** (Crypto · India · US · Commodity) **plus** user-selected hub strategy engines.

| Step | Action |
|------|--------|
| **1** | Pick **one or more** strategies from the dropdown (all TA hub + swing engines) |
| **2** | Enter ticker(s) in any asset tab → **Search & investigate** |
| **3** | Review news · PA · S/R · analysts · **merged** suggested trades & primary setup |

Selected engines run live `analyze_ticker` per symbol; signals merge into ranked trades alongside rule-based confluence.

---

### Tomorrow Outlook
*id: `tomorrow_outlook`*

### Tomorrow & Today Market Outlook
Forward-looking Command Center snapshot from the same live payload as Market Pulse.

| Input | Use |
|-------|-----|
| Global indices and Gift Nifty | Overnight / pre-open bias |
| FII/DII, breadth, turnover | Cash-market participation |
| Nifty options (PCR, max pain, OI) | Directional and pinning risk |
| Fresh news, analyst calls, events | Catalysts for today / next session |

**Today banner** = composite sentiment. **Tomorrow banner** = gap risk, global cues, and event risk into the next session.

---

### Weekly Stoch
*id: `weekly_stoch`*

### Weekly Stochastic Sweet Spot

**Reference:** [YouTube walkthrough](https://www.youtube.com/watch?v=Tr_RXi6wQko)

| Element | Rule |
|---------|------|
| Sweet spot | Weekly %K between **32%** and **80%** |
| BUY entry | %K crosses above %D **into** zone from below 32% + volume confirm |
| Hold | While %K > %D — can ride above 80% |
| SELL exit | %K crosses below %D while %K < 80% |

Volume: majority of daily sessions in the week above 20-day avg at entry.

Phases: ENTRY_SIGNAL · IN_TRADE · EXIT_SIGNAL · APPROACHING · SWEET_WATCH. Typical hold **1–12 weeks**. Groww and CoinDCX.

---

# Strategy Lab & tools detail

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
