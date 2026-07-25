"""
section_strategy_guides.py
--------------------------
Unified collapsible strategy / methodology guides for every hub section.
Rendered automatically from hub_tabs.render_hub_section*.
"""

from __future__ import annotations

GUIDE_EXPANDER_TITLE = "📖 Strategy Guide & Methodology — what this section does"

_SENTIMENT_GUIDE = """
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
"""

SECTION_GUIDES: dict[str, str] = {
    "command_outlook": """
### Tomorrow & Today Market Outlook
Forward-looking Command Center snapshot from the same live payload as Market Pulse.

| Input | Use |
|-------|-----|
| Global indices and Gift Nifty | Overnight / pre-open bias |
| FII/DII, breadth, turnover | Cash-market participation |
| Nifty options (PCR, max pain, OI) | Directional and pinning risk |
| Fresh news, analyst calls, events | Catalysts for today / next session |

**Today banner** = composite sentiment. **Tomorrow banner** = gap risk, global cues, and event risk into the next session.
""",

    "mega_analyser": """
### Mega Analyser — unified multi-engine scan
One click runs multiple TA engines on your watchlist with scenario presets.

| Engine bucket | Includes |
|---------------|----------|
| Core TA | Price Action, Find S/R, **Weak Strong S-R**, Pattern and Breakout, Confluence, Sentiment, Elliott |
| MTF / session | MTF Scanner, Top-Down SMC, **MTF Intraday Session Bias**, Weekly Stoch, KN Smart |
| Scalp | Fakeout 4H/15M, **Velez Retracement**, **Crypto Scalping**, **1m Rectangle Sniper** |
| SMC / structure | **SMC Fake Market Shift** (BOS→POI→sweep, Groww/CoinDCX), SMC Flow (India stocks) |
| Crypto | **Smart Wave Crypto** (CoinDCX only) |
| Special | Pump and Dump pre-move, Gap, Seasonality, Strategy Builder backtest, Saved Strategies, Screener |

**Scenarios:** Full analysis · Pump & Dump pre-move · India intraday scalp · Crypto momentum · Swing/positional · **Custom**.

Each ticker gets per-engine verdict, mega score, trade plan, and optional **AI View**. Pair with **Buy or Sell** for asset-class presets.
""",

    "buy_sell_advisor": """
### Buy or Sell — Multi-Asset Trade Advisor
Four tabs — **Crypto · Indian stocks · US stocks · Commodity** — with typed ticker search, multiselect symbols, and **multi-timeframe** analysis.

| Asset class | TA profile |
|-------------|------------|
| Crypto | Crypto momentum + Smart Wave |
| India | India intraday scalp (SMC Flow, session bias) |
| US / Commodity | Swing / positional (S/R, confluence, MTF) |

**Output:** **TAKE LONG/SHORT** or **NO TRADE**, **confidence %**, **SL %**, **TP %**, engine confluence list, and **AI View** synthesis.

Pick tickers → durations → **Analyse & suggest Buy / Sell**. Requires network; India optional Groww token.
""",

    "ticker_investigation": """
### Ticker Investigation — News · Price · S/R · Strategies
Four tabs — **Crypto · Indian stocks · US stocks · Commodity**. Enter comma-separated tickers → **Search & investigate**.

| Tab | Tickers | Data |
|-----|---------|------|
| Crypto | CoinDCX USDT pairs | CoinTelegraph, CoinDesk, … |
| India | NSE symbols | Moneycontrol, LiveMint, ET Now, … |
| US | NYSE/Nasdaq | Yahoo, MarketWatch, Seeking Alpha, … |
| **Commodity** | Yahoo futures `CL=F`, `GC=F`, `SI=F`, `HG=F`, `NG=F`, `ZW=F` | Moneycontrol Commodities, macro RSS, Google News |

| Output | Detail |
|--------|--------|
| News | RSS from Moneycontrol, LiveMint, ET Now, Zee Business, NDTV Profit, Yahoo, MarketWatch, CoinTelegraph, Google News, and more |
| Analyst calls | **Upgrades · downgrades · re-ratings · initiations · price targets** from Moneycontrol brokerage RSS, Seeking Alpha, Benzinga, Google News |
| Price moves | % change over **5d · 24h · 4h · 1h · 15m · 5m** + RSI zone per window |
| S/R | Nearest **weak/strong** support & resistance · **breakout %** · **breakdown %** · bias by TF |
| Strategies | Ranked **scalp / swing** setups with **SL% · TP% · confidence%** from TA confluence |
| Trade setup | Primary **TAKE LONG / SHORT / NO TRADE** — blends S/R, RSI, MTF, news sentiment, analyst calls |
| Ask AI | **AI Trade Setup** (SL/TP/confidence) + full investigation synthesis |

India: optional Groww token for live intraday bars. Commodity: Yahoo Finance futures (no Groww).
""",

    "news_scanner": """
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
""",

    "nifty_breadth": """
### Nifty Index Breadth
Advances / declines / unchanged for major Nifty indices with S1-S2 / R1-R2 on each.

Use to confirm broad participation vs narrow index leadership. Refresh after selecting indices.
""",

    "nifty_monthly": """
### Nifty 1-Month Performance
Rolling ~21 trading-day performance for Nifty indices and top constituent movers.

Shows index return vs period range and leader/lagger tables for relative strength ideas.
""",

    "market_gainers_losers": """
### Gainers & Losers — Multi-Market
Top **10** gainers and **10** losers per selected **index × timeframe**:

| Market | Universes |
|--------|-----------|
| **India** | Any Nifty index constituents (NSE live for session) |
| **US** | S&P 500, Nasdaq 100, Dow 30, Russell 2000, etc. |
| **Crypto** | CoinDCX USDT groups or full universe |
| **Commodities** | Futures + correlated US / Nifty names |

Loads **10 sections per click**. Pick multiple timeframes (5m → 1M).
""",

    "nifty_gainers_losers": """
### Nifty Gainers and Losers
Top 10 constituents by % change for chosen Nifty indices.

Quick read on what is moving the index today. Pair with Sector Rotation.
""",

    "stock_price_rotation": """
### Stock Price Rotation
Ranks **index constituents** by return over a chosen **candle interval** (1m → 1M) and **lookback window**, vs the index benchmark.

| Step | Action |
|------|--------|
| 1 | Pick a Nifty index |
| 2 | Subset constituents (optional) |
| 3 | Set interval + duration → **Analyse** |

Top = rotating in (outperforming index); bottom = rotating out. Use for relative-strength stock picks within a sector/theme index.
""",

    "stock_price_rotation_us": """
### US Stock Price Rotation
Ranks **US index constituents** (S&P 500, Nasdaq 100, Dow 30, Russell 2000, etc.) vs the matching **ETF benchmark** (SPY, QQQ, DIA, IWM…).

Same workflow as India: pick index → subset tickers → interval + lookback → **Analyse**. Data via **Yahoo Finance**.
""",

    "stock_price_rotation_crypto": """
### Crypto Price Rotation (CoinDCX)
Ranks **CoinDCX USDT perpetual** pairs within a bucket (Major L1, DeFi, Meme, custom) vs **BTC**.

Session day starts at **00:00 New York (ET)** — day lookbacks and **1d** bars align to the NY calendar. Use to spot alt-season leadership or BTC-relative laggards.
""",

    "commodity_screener": """
### Commodity Screener — Buy / Sell Signals
Tracks **WTI, Gold, Silver, Natural Gas, Copper, Wheat, Iron Ore** (Yahoo Finance) across **15 mins · 1 hr · 4 hrs · 1 day → 3 months**.

| Output | Meaning |
|--------|---------|
| Commodity consensus | Majority **BUY** / **SELL** / **NEUTRAL** across selected durations |
| Commodity futures | Direct **LONG** / **SHORT** on CL=F, GC=F, … with **confidence %**, **SL %**, **TP %** |
| Nifty / Crypto / US | Correlated ideas with the same risk fields |

Use for **macro thematic tilt** and cross-asset ideas when commodities move beyond the min threshold.
""",

    "accurate_strategy": """
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
""",

    "pump_dump_breakout": """
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
""",

    "big_whale_pump_dump": """
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
""",

    "sector_rotation": """
### Sector Rotation
Ranks Nifty sector indices by daily, weekly, and monthly return.

Use the **sector index filter** to subset which Nifty sectoral indices are included (same pattern as US/Crypto sector pickers).

Top = inflow leadership; bottom = lags. Use for sector tilt, not single-stock entries alone.
""",

    "sector_rotation_intraday": """
### Sector Rotation — mins · hours · days
Session-style sector leadership using **5m**, **1h**, and **daily** bars.

| Window | Bars | Use |
|--------|------|-----|
| Minutes | 5m | Opening drive, first-hour rotation |
| Hours | 1h | Half-day / full-session tilt |
| Days | 1d | Short swing sector bias (1–10 sessions) |

Pair with the daily/weekly/monthly Sector Rotation section for HTF context.
""",

    "sector_rotation_us": """
### Sector Rotation (US) — daily · weekly · monthly
Ranks **SPDR sector ETFs** (XLK, XLF, XLE, …) vs **SPY** over daily, weekly, and monthly windows.

Use the **sector universe** filter (All SPDR · Cyclicals · Defensives · Custom) to subset symbols before loading.
""",

    "sector_rotation_us_intraday": """
### Sector Rotation (US) — mins · hours · days
Session-style US sector rotation on **5m**, **1h**, and **daily** bars via Yahoo Finance.

Best during **US market hours**. Same sector/symbol filter as the HTF US section.
""",

    "sector_rotation_crypto": """
### Sector Rotation (Crypto) — daily · weekly · monthly
Ranks major **CoinDCX USDT** pairs vs **BTC** over daily, weekly, and monthly windows.

Session day starts at **00:00 New York (ET)**. Filter by bucket: Major L1 · DeFi · High Beta/Meme · Custom pairs.
""",

    "sector_rotation_crypto_intraday": """
### Sector Rotation (Crypto) — mins · hours · days
Intraday crypto rotation on **5m**, **1h**, and **1d** CoinDCX bars vs BTC benchmark.

**Session day starts at 00:00 New York (ET)** — the **day** window counts NY session days, not UTC/IST.

**Crypto sector bucket** includes live leader universes:
- **Top Volume** — highest futures volume
- **Top Volatile** — largest session range / % move (NY session day)
- **Top Risen** / **Top Fallen** — session gainers and losers (CoinDCX 24h % + NY session range)

After load, **Top Volume · Volatile · Risen · Fallen** tables show movers within your selected pairs (or market-wide in the preview expander).

Use for alt-season vs BTC-dominance reads and short-term leadership shifts.
""",

    "opposite_hedge_mtf": """
### Opposite Hedge-MTF
Long the **leading** sector and short the **lagging** sector from both rotation feeds — profit the **spread delta**.

| Source | Windows |
|--------|---------|
| Intraday rotation | Minutes · Hours · Days |
| HTF rotation | Daily · Weekly · Monthly |

**Per window:** long ticker + % alloc + confidence + SL/TP + hold duration · same for short leg.

**Consensus row** votes the best pair across all six windows. Buy long in cash/ETF; short via F&O or paired instrument.
""",

    "mtf_intraday_bias": """
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
""",

    "mtf_intraday_bias_crypto": """
### MTF Intraday Crypto Bullish / Bearish
Same scoring engine as equities for **CoinDCX USDT** pairs.

| Difference | Detail |
|------------|--------|
| Session day | Starts **00:00 New York (ET)** |
| Price vs open | NY session open (not IST) |
| PCR | Omitted (no NSE chain) |
| Prices | Yahoo USD proxy |

Trade setups include entry TF, SL%, TP%, hold time. Configure HTF·MTF·LTF·ULTF like the equity scanner.
""",

    "week52": """
### 52-Week High and Low
Constituents near 52-week high/low for breakout or reversal context. Filter by index universe.
""",

    "heatmap": """
### Live Heatmap
Colour grid of sector and ticker % change. Sector mode for industries; ticker mode for constituents.
""",

    "price_action": """
### Price Action Screener
Multi-indicator live scanner: S/R, trendlines, RSI divergence, EMA crossovers, Fibonacci golden zone, Elliott wave, candlesticks, chart patterns, SMC (order blocks / FVG).

| Metric | Meaning |
|--------|---------|
| Trend | Linear regression slope — SIDEWAYS = range |
| RSI | <30 oversold, >70 overbought |
| EMA stack | 9/21/50 alignment |
| Fib Golden | 50–61.8% retrace zone |
| Smart Money | OB / FVG footprints near price |

Groww and CoinDCX · multi-TF · approaching-setup alerts · SL/TP trade plans · AI View.
""",

    "pump_dump_predictor": """
### Pump and Dump Screener
Pre-move detection (India + crypto). One green rule = signal; aim for **3+ greens** and confluence **55+** for action.

See Starter Guide tab for full rule list.
""",

    "find_sr": """
### Find S/R Screener
Two immediate supports (S1, S2) and resistances (R1, R2) with **price and % from LTP**.

**Consolidation rules**
- Tight range **under resistance → bullish** (coiling for upside break)
- Tight range **above support → bearish** (flag for downside break)

**Supply / demand** — swing-history zones: rejections at highs (supply), bounces at lows (demand).

Also: EMA ladder, patterns near S/R, volume, RSI, annotated chart, bar date/time.
Groww · US · Crypto · multi-TF · AI View.
""",

    "weak_strong_sr": """
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
""",

    "stf_shop": """
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
""",

    "pattern_breakout": """
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
""",

    "fakeout_4h": """
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
""",

    "fakeout_15m": """
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
""",

    "mtf_scanner": """
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
""",

    "mtf_hedging": """
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
""",

    "top_down_mtf": """
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
""",

    "weekly_stoch_sweet_spot": """
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
""",

    "kn_smart_rsi_mtf": """
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
""",

    "velez_retracement": """
### Velez Retracement Scalping (Oliver Velez)

- **Chart:** 2m (or 5m) · **SMA 20** short trend · **SMA 200** long trend
- **Zones:** 25% · 50% · 75% · 100% retrace

| Mode | Rule | Target |
|------|------|--------|
| A Scalp | Counter-trend after sharp move; retrace **<50%** | **25%** retrace (~90% zone) |
| B Trend | Retrace **>50%** + engulfing bar | Min **2:1 R:R** continuation |

Sharp move filter: net move > threshold (default 0.5%). Scalp stop ~0.3%; trend stop beyond engulfing extreme. Groww and CoinDCX.

**Reference:** [YouTube walkthrough](https://www.youtube.com/watch?v=MM4yzIq5Q-c&start=296)
""",

    "crypto_scalping": """
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
""",

    "smc_fake_market_shift": """
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
""",

    "smart_wave_crypto": """
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
""",

    "confluence_strategy": """
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
""",

    "strategy_scheduler": """
### Strategy Scheduler Screener
Batch preset rule packs across universes. Manual scan of encyclopedia-style strategies.
""",

    "elliott_wave": """
### Elliott Wave Screener

- **ZigZag filter** finds swing highs/lows (sensitivity = ZigZag % slider)
- **5-wave impulse** validated with classic Wave 2/3/4 rules
- **ABC correction** when impulse rules fail but 3-leg corrective fits
- **Fib targets** after impulse or extension after ABC

Probabilistic — combine with S/R, trend, volume. Multi-ticker × multi-TF + AI View. Groww and CoinDCX.
""",

    "sentiment": _SENTIMENT_GUIDE,

    "top_bottom": """
### Top/Bottom (Trough & Peak) Analyzer

Identifies price extremes where reversal is statistically likely using rolling window highs/lows.

**Long:** near bottom trough + bearish momentum exhausted.
**Short:** near peak top + bullish momentum exhausted.

**Tools:** lookback extremes · RSI exhaustion (>70 top, <30 bottom) · ATR-based SL · Fib 38.2/50/61.8% TP · candle/chart pattern confluence · crypto margin safety vs liquidation.

Counter-trend context — not trend-following alone. Groww and CoinDCX.
""",

    "smc_options": """
### SMC · Options Flow Screener
SMC structure plus NSE options flow: delivery, PCR, OI change. India F&O names.
""",

    "strategy_builder": """
### Strategy Builder & Tester
Visual strategy designer with full backtest engine.

1. Add indicators (EMA, SMA, RSI, MACD, BB, Supertrend, VWAP, Fib, ADX, etc.).
2. Define **entry rules** (ALL must be true) and **exit rules**.
3. Set ticker, timeframe, SL %, TP %, and backtest date range.
4. **Run Backtest** → equity curve, trade list, win rate, profit factor, max drawdown.
5. **Save Strategy** (login required) → Saved Strategies Archive.

Load presets from Encyclopedia or output from AI Strategy Creator.
""",

    "saved_strategies": """
### Saved Strategies Archive
Your personal library of backtested strategies (login required).

- Reload by name; re-run with updated dates.
- Compare win rate, profit factor, drawdown across versions.
- Feed into **Multi-Combo Scanner** and **Alert Monitors**.
""",

    "multi_combo": """
### Multi-Combo Scanner
Batch backtest engine: **tickers × timeframes × strategies**.

- Use saved strategies or built-in TA hub engines.
- Rank results by metrics; save best combos.
- Saved combos power **Alert Monitors** for live polling.
""",

    "strategy_encyclopedia": """
### Strategy Encyclopedia
Master reference for the entire application.

| Tab inside Encyclopedia | Contents |
|-------------------------|----------|
| **Application & Section Guide** | App overview, 8 workflows, when-to-use matrix, every hub section |
| **Preset Strategy Catalog** | Documented presets with Load into Builder |

Use **Strategy Lab → Builder** to backtest presets; **Multi-Combo** to batch-scan; **Alerts** to monitor live.
""",

    "ai_strategy_creator": """
### AI Strategy Creator
Convert plain English or transcripts into executable rules via LLM (Gemini/Groq).

1. Paste strategy description or video transcript.
2. LLM outputs JSON: indicators, entry/exit rules, SL/TP, timeframe.
3. **Always review in Strategy Builder** before backtesting.
""",

    "screener": """
### Advanced Screener
Rule-based universe filter with custom indicator conditions.

**When to use:** Filter 50–500 tickers by rules (e.g. RSI<30 + price above EMA200).
Start from a preset, customize conditions, scan Groww or CoinDCX universe.
""",

    "gap_scanner": """
### Gap Trading Scanner
Gap up/down vs prior close with S/R context, fade vs continuation bias, fill probability.

**When to use:** First 30–60 minutes after India market open. Pair with Find S/R for targets.
""",

    "seasonality": """
### Seasonality Analyzer
Historical monthly win rate and average return patterns per ticker/index.

**When to use:** Confirm swing/position trades — probabilistic edge only, not standalone entry.
""",

    "swing_trading_st": """
### ST — Swing Trading (Capitulation & Continuation)
[Video reference](https://www.youtube.com/watch?v=k-X0164r66U) — two **daily** swing systems via Backtrader:

| Strategy | Entry | Exit / stop |
|----------|-------|-------------|
| **Mean reversion capitulation** | RSI &lt; 30 + 2× volume spike + close above prior high | Stop: entry bar low · trail: close &lt; prior low |
| **Continuation breakout** | Close &gt; 60-bar high | Stop: breakout day low · trail: close &lt; 20 MA |

**Markets:** Groww India · CoinDCX · US Yahoo. Live scan outputs **TAKE LONG / WATCH** with **confidence %**, **SL %**, **TP %** plus optional Backtrader backtest.
""",

    "swing_trading_st_mtf_mss": """
### ST — Weekly Fakeout + 15m MSS
[Video reference](http://www.youtube.com/watch?v=Aq8_xZAFj0Q) — **MTF** swing/intraday trap system:

| Tier | Rule |
|------|------|
| **Weekly** | **PWH / PWL** = previous week high & low |
| **Daily** | **Fakeout** — wick beyond PWH/PWL but **close back inside** |
| **15m** | **MSS** — break of swing structure after liquidity grab · 1:1 R:R |

**Markets:** Groww · CoinDCX · US. Post-market fakeout scan → next-session 15m MSS entry.
""",

    "swing_trading_st_supertrend": """
### ST — SuperTrend + SMA 10 (Swing & Pyramiding)
[Video reference](http://www.youtube.com/watch?v=JuiWfkJukmc) — **SuperTrend (10, 3)** + **SMA 10**:

| Mode | Timeframe | Entry | Exit |
|------|-----------|-------|------|
| **Swing** | Daily | SMA crosses **above** SuperTrend (bullish) | Close crosses **below** SMA 10 |
| **Pyramid** | Weekly | SuperTrend **bullish flip** · add on close above SMA | SuperTrend **bearish flip** |

Live scan: **TAKE LONG**, **CORE BUY**, **PYRAMID ADD**, exits, holds — with confidence, SL%, TP%.
""",

    "swing_trading_st_kiss": """
### ST — KISS Swing Systematic
[Video reference](http://www.youtube.com/watch?v=2YBmiyVmNNw) — weekly **Heikin Ashi** filter + **1h/4h** execution:

| Filter | Rule |
|--------|------|
| Weekly HA | Green = longs only · Red = shorts only |
| 55 EMA band | Above high / below low · inside = no trade |
| MACD | Zero-line cross in trend direction |

Risk **1–2%** · R:R **1:3–1:4** · SL at structural swing · conf/SL%/TP%/hold on every signal.
""",

    "swing_trading_st_ha_ema": """
### ST — Daily HA Bias + 34 EMA Intraday
[Video reference](https://www.youtube.com/watch?v=o5i8WF0UIfE) — Upsurge / Animesh intraday system:

| Layer | Rule |
|-------|------|
| **Daily HA** | Prev green = **calls/long only** · prev red = **puts/short only** |
| **5m/15m** | **34 EMA** on highs/lows — channel breakout entries |
| **Exit** | Close back through opposite band · **1:2** R:R reference |

Conf / SL% / TP% / hold time on every scan row. Prefer liquid index names for options workflow.
""",

    "intraday_alpha_945": """
### INTRA — 9:45 AM Alpha Scanner
[Video reference](http://www.youtube.com/watch?v=MfGUybW4O4c) — Dhan relative-strength scan at **9:45 IST**:

| Filter | Rule |
|--------|------|
| Liquidity | Mcap &gt; ₹5,000 Cr · volume &gt; 10 lakh |
| Trend | Above **20 EMA** · **SuperTrend (10,3)** bullish |
| Momentum | Day change **+0.5% to +1.5%** |
| Trade | Buy stop above **9:15–9:45** 30m high · SL low/body · **1:2** target |

**Output:** confidence %, SL %, TP %, same-session hold time per ticker.
""",

    "smc_mtf_day_plan": """
### SMC — MTF Day Trading Plan (OB · FVG · CHoCH)
[Video reference](https://www.youtube.com/watch?v=795tKU5Zxu8) — Smart Risk 2026 day plan:

| Step | Rule |
|------|------|
| **HTF (4H/1D)** | Trend + unmitigated OB/FVG supply/demand |
| **MTF (1H↓)** | Counter-trend into HTF zone · locate demand/supply OB |
| **CHoCH** | Close through counter-trend OB — control shifts |
| **Entry** | Limit at new breakout OB · SL beyond structure · TP 1:2 + swing |

HTF/MTF/LTF selectors. Conf / SL% / TP% / hold on every row.
""",

    "smc_golden_bullet": """
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
""",

    "smc_weekly_sweep_cisd": """
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
""",

    "smc_cisd": """
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
""",

    "intraday_vwap_fade": """
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
""",

    "intraday_fib_945": """
### INTRA — 9:45 Fib 50% + 10 EMA
[Video reference](http://www.youtube.com/watch?v=5o7V6fi7mV4) — wait for **9:15–9:45** 30m range:

| Step | Rule |
|------|------|
| **Fib 50%** | Equilibrium of opening range — bias line |
| **Bias** | Above = **longs only** · below = **shorts only** |
| **Entry** | **10 EMA** cross with bias on **5m/1m** · **30 MA** confirm |
| **SL/TP** | Prior candle low / 50% Fib · **1:2** R:R |

Conf / SL% / TP% / hold time on every scan row.
""",

    "scalp_rectangle": """
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
""",

    "scalp_livefree_fx": """
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
""",

    "demo_india": """
### Demo Trading — India
Paper NSE/BSE portfolio (login required). Virtual capital, live P&L, order history.

**When to use:** Practice setups from screeners before live Groww orders.
""",

    "demo_crypto": """
### Demo Trading — Crypto
Paper CoinDCX-style futures ledger — separate from India demo book.

**When to use:** Practice Smart Wave, crypto MTF bias, and fakeout setups before live orders.
""",

    "alerts": """
### Strategy Alert Monitors
Live polling of **Multi-Combo saved picks**. Telegram/email when entry rules match latest bar.

**Setup:** Login → Multi-Combo save combos → Alerts → create monitor → configure channels.
""",
}


def get_section_guide_body(section_id: str) -> str | None:
    """Return markdown body for a section guide, or None if unknown."""
    body = SECTION_GUIDES.get(section_id)
    return body.strip() if body else None


def render_section_strategy_guide(
    section_id: str,
    *,
    expanded: bool = False,
    inline: bool = False,
) -> None:
    """Show unified strategy explainer for a hub section (no-op if unknown id)."""
    body = get_section_guide_body(section_id)
    if not body:
        return
    if inline:
        st.markdown(body)
        return
    with st.expander(GUIDE_EXPANDER_TITLE, expanded=expanded):
        st.markdown(body)
