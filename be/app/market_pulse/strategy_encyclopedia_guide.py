"""
strategy_encyclopedia_guide.py
------------------------------
Full application reference for the Strategy Encyclopedia tab:
hub map, workflows, when-to-use matrix, and every section explained.
"""

from __future__ import annotations

from app.market_pulse.section_strategy_guides import SECTION_GUIDES

# Hub → (section_id, display title) — mirrors hub_tabs.py
HUB_SECTIONS: dict[str, list[tuple[str, str]]] = {
    "🚀 Command Center": [
        ("command_outlook", "Tomorrow & Today Market Outlook"),
        ("mega_analyser", "Mega Analyser — unified multi-engine scan"),
        ("buy_sell_advisor", "Buy or Sell — Crypto · India · US · Commodity"),
        ("ticker_investigation", "Ticker Investigation — Crypto · India · US · Commodity"),
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
    ],
    "🇮🇳 ETF TA IN": [
        ("stf_shop", "ETF Shop 4.0 — 20 DMA · dynamic SIP · FIFO · 39 distinct ETFs"),
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
    ],
    "⚡ Intraday": [
        ("intraday_alpha_945", "INTRA — 9:45 AM Alpha Scanner"),
        ("intraday_fib_945", "INTRA — 9:45 Fib 50% + 10 EMA"),
        ("intraday_vwap_fade", "INTRA — VWAP Fade Value Area Extremes"),
    ],
    "🎯 Scalping": [
        ("scalp_rectangle", "Scalp — 1m Rectangle Sniper Entry"),
        ("scalp_livefree_fx", "Scalp — LiveFree FX 5m"),
    ],
    "💰 Smart Money": [
        ("smc_cisd", "SMC — CISD Entry Rule (Golden Rule)"),
        ("smc_weekly_sweep_cisd", "SMC — Weekly Liquidity Sweep & CISD"),
        ("smc_mtf_day_plan", "SMC — MTF Day Plan (OB · FVG · CHoCH)"),
        ("smc_golden_bullet", "SMC — Golden Bullet (Liquidity + Timing)"),
    ],
    "📓 Demo Trading": [
        ("demo_india", "Demo Trading — India (Groww)"),
        ("demo_crypto", "Demo Trading — Crypto (CoinDCX)"),
    ],
    "🔔 Alerts": [
        ("alerts", "Strategy Alert Monitors"),
    ],
}

_OVERVIEW = """
### What is TrueBacktester?

TrueBacktester is an **all-in-one trading research platform** for **NSE/BSE (Groww)** and **CoinDCX crypto futures**.
It combines live market intelligence, 18+ technical screeners, strategy backtesting, batch scanning,
paper trading, and alert monitors — with **Ask AI** (Gemini/Groq) on most sections.

### The 8 main hubs (top tabs)

| Hub | Purpose | Start here if… |
|-----|---------|----------------|
| **Command Center** | One-click multi-engine scan + today/tomorrow outlook | You want a fast morning briefing or unified scan |
| **Market Pulse** | Live news, flows, options, breadth, heatmaps, MTF session bias | You need macro context before picking trades |
| **Technical Analysis** | Live screeners with trade setups, charts, AI View | You have a setup type in mind (scalp, swing, SMC…) |
| **Strategy Lab** | Build, backtest, batch-scan, and AI-generate strategies | You want to test or create systematic rules |
| **Screen & Scan** | Rule-based universe scan + gap events | You want to filter hundreds of tickers by rules |
| **Seasonality** | Monthly historical edge patterns | You want statistical seasonal bias confirmation |
| **Swing Trading** | ST capitulation + continuation breakouts (Backtrader) | Multi-day swing entries on India / US / crypto |
| **Intraday** | 9:45 AM Alpha scanner — opening range breakouts | NSE session-timed relative-strength intraday |
| **Demo Trading** | Paper portfolio (India + crypto) | You want to practice without real money |
| **Alerts** | Telegram/email when saved setups fire | You want hands-off monitoring after research |

### Universal UI patterns (every section)

1. **Expand the hub section** — each tool lives in a collapsible block inside its hub tab.
2. **📖 Strategy Guide & Methodology** — at the top of every section; read this first.
3. **Market selector** — most TA tools offer **Groww (India)** or **CoinDCX Futures**.
4. **Run Scan / Refresh** — data is fetched on demand (not always live-auto).
5. **Ask AI panel** — at the bottom; summarizes scan results with your chosen LLM.
6. **AI View** — per-ticker deep dive inside many screeners (configure provider in-section).

### Sidebar essentials

- **Login (mobile)** — unlocks saved strategies, demo portfolio, alerts.
- **Groww token** (optional) — faster direct NSE feed; falls back to Yahoo if absent.
- **AI provider keys** — Gemini or Groq for Ask AI / AI View.
"""

_WORKFLOWS = """
### Workflow 1 — Morning pre-market (India cash)

1. **Command Center → Tomorrow & Today Outlook** — gap risk, global cues, event calendar.
2. **Market Pulse → News Scanner** — click **Refresh Market Data**; read FII/DII, PCR, analyst calls.
3. **Sector Rotation + Heatmap** — which sectors lead/lag today.
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

1. **Market Pulse → News Scanner** — PCR, max pain, OI walls.
2. **SMC · Options Flow Screener** — delivery %, PCR, OI change + SMC structure.
3. **MTF Intraday Bias** — includes PCR in equity scoring.

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
4. **AI Trade Setup** or **Ask AI** per ticker for TA + news + analyst synthesis.
"""

_WHEN_TO_USE = """
### Quick decision matrix

| Your goal | Best section(s) | Typical hold |
|-----------|-----------------|--------------|
| Pre-open / overnight bias | Command Outlook, News Scanner | — |
| Broad market health | Nifty Breadth, Sector Rotation, Heatmap | — |
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
| Everything-at-once scan | Mega Analyser (22+ engines incl. Crypto Scalping · SMC FMS · Weak Strong S-R · Velez · Smart Wave) | — |
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
| F&O + smart money | SMC · Options Flow | Intraday – swing |
| Gap open play | Gap Trading Scanner | First hour |
| Rule-based universe filter | Advanced Screener | — |
| Historical monthly edge | Seasonality Analyzer | Weeks – months |
| Backtest custom rules | Strategy Builder | Historical |
| Batch backtest many tickers | Multi-Combo Scanner | Historical |
| Paper trade practice | Demo Trading | Live forward |
| Live signal alerts | Alert Monitors | Ongoing |

### By trader style

**Scalper (1m–15m):** Fakeout 15M · Velez · KN Smart · MTF Scanner (1m/5m) · Top Down MTF (1m LTF)

**Intraday (15m–4h):** Fakeout 4H · MTF Intraday Bias · Confluence · KN Smart · Price Action

**Swing (4h–1w):** Weekly Stoch · MTF Scanner (4h/1d) · Pattern Breakout · Sentiment · Seasonality

**Positional (1w+):** Weekly Stoch · Elliott Wave · Seasonality · Sentiment on 1d/1w

### By market type

**Trending:** MTF Scanner · KN Smart · Top Down MTF · Supertrend presets in Builder

**Range-bound:** Fakeout 15M/4H · Confluence · BB/RSI presets · Top/Bottom

**High volatility / crypto:** Smart Wave · Pump & Dump · MTF Crypto Bias · Demo Crypto ledger

**India F&O:** SMC Options · News PCR · MTF Equity Bias (PCR component)
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
- Pick saved strategies **or** built-in TA hub engines.
- Batch: many tickers × many timeframes × many strategies.
- Rank by backtest metrics; **save picks** for alerts.
- Best for finding *which* ticker loves *which* strategy.

#### AI Strategy Creator
- Paste a YouTube transcript, PDF notes, or plain-English rules.
- LLM (Gemini/Groq) outputs structured JSON: indicators, entry/exit, SL/TP, timeframe.
- Always **review in Builder** before trusting — LLM may misparse edge cases.

#### Strategy Encyclopedia (this page)
- **Application Guide** — how to use the whole app (you are here).
- **Preset Catalog** — documented preset strategies with **Load into Builder** button.

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

### Scalp — 1m Rectangle Sniper Entry
- **FVG** imbalance + liquidity sweep → draw rectangle on rejection wick.
- **Sniper entry** when 1m candle closes through rectangle body edge.
- SL beyond wick · minimum **3:1 R:R** · hold 1–15 minutes.

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
            "Every hub section is listed below. "
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
