"""Trading Hubs and Technical Analysis strategies for the backtester."""

from __future__ import annotations

from typing import Any

from app.trading_hubs.registry import HUB_META, HUB_SECTIONS
from app.market_pulse.ta_screener_registry import TA_SCREENERS

ENGINE_CATEGORY_DESCRIPTIONS: dict[str, str] = {
    "th_swing": "Swing Trading Hub engines — multi-day ST systems migrated from truebacktesting.",
    "th_intraday": "Intraday Trading Hub engines — session-timed NSE scanners and opening-range setups.",
    "th_scalping": "Scalping Hub engines — 1m rectangle sniper and high-frequency setups.",
    "th_smart_money": "Smart Money Hub engines — SMC liquidity, sweep, and institutional delivery models.",
    "pro_trade": "Pro Trade engines — Volume Profile, PA+VP, VSA next-candle, and PA-VP-SMC confluence.",
    "etf_ta": "ETF TA IN — ETF Shop 4.0 systematic 20 DMA swing / SIP proxy (India · US · Crypto · Commodity ETFs).",
    "technical_analysis": "Technical Analysis tools — sentiment scoring, MTF confluence, and investigation composites.",
    "ta_screeners": "TA screener engines — S-R, fakeout, SMC, crypto wave, and confluence scanners.",
}

_HUB_CATEGORY_MAP = {
    "swing": "th_swing",
    "intraday": "th_intraday",
    "scalping": "th_scalping",
    "smart_money": "th_smart_money",
}

# Default timeframes per hub section (from engine configs).
_HUB_TIMEFRAMES: dict[str, list[str]] = {
    "swing_trading_st": ["1d"],
    "swing_trading_st_mtf_mss": ["15m"],
    "swing_trading_st_supertrend": ["1d", "1wk"],
    "swing_trading_st_kiss": ["1h", "4h"],
    "swing_trading_st_ha_ema": ["5m", "15m"],
    "intraday_alpha_945": ["5m", "15m"],
    "intraday_fib_945": ["5m", "1m"],
    "intraday_vwap_fade": ["5m", "1m"],
    "intraday_london_breakout": ["5m"],
    "scalp_rectangle": ["1m"],
    "smc_cisd": ["15m", "5m"],
    "smc_weekly_sweep_cisd": ["15m"],
    "smc_mtf_day_plan": ["15m", "5m"],
    "smc_golden_bullet": ["15m"],
    "scalp_ichimoku_crash": ["1h", "4h", "1d"],
    "swing_trend_velocity": ["1d"],
    "swing_bb_vwap_reversal": ["5m", "15m"],
    "smc_liquidity_silver_bullet": ["5m", "15m"],
    "scalp_ny_open_bias": ["1m"],
    "scalp_a_plus": ["1m", "5m"],
    "scalp_gold": ["15m", "1h"],
    "smc_five_filter": ["1m", "5m", "15m", "30m", "1h"],
    "support_resistance": ["1m", "5m", "15m"],
    "footprint": ["1m", "5m", "15m"],
    "reversal_strategy": ["4h", "1d", "1wk"],
    "intra_hedging": ["5m", "15m", "30m"],
}

_HUB_MIN_BARS: dict[str, int] = {
    "swing_trading_st": 80,
    "swing_trading_st_mtf_mss": 100,
    "swing_trading_st_supertrend": 30,
    "swing_trading_st_kiss": 80,
    "swing_trading_st_ha_ema": 100,
    "intraday_alpha_945": 50,
    "intraday_fib_945": 80,
    "intraday_vwap_fade": 80,
    "intraday_london_breakout": 80,
    "scalp_rectangle": 80,
    "smc_cisd": 60,
    "smc_weekly_sweep_cisd": 80,
    "smc_mtf_day_plan": 60,
    "smc_golden_bullet": 80,
    "scalp_ichimoku_crash": 120,
    "swing_trend_velocity": 280,
    "swing_bb_vwap_reversal": 30,
    "smc_liquidity_silver_bullet": 60,
    "scalp_ny_open_bias": 40,
    "scalp_a_plus": 80,
    "scalp_gold": 80,
    "smc_five_filter": 80,
    "support_resistance": 80,
    "footprint": 80,
    "reversal_strategy": 100,
    "intra_hedging": 30,
}

PRO_TRADE_STRATEGIES: list[dict[str, Any]] = [
    {
        "id": "volume_profile_ce",
        "name": "Volume Profile CE",
        "description": "Value Area reversal · POC compression · I-profile LVN — Abhishek Kar masterclass.",
        "timeframes": ["15m", "30m", "1h", "4h", "1d"],
        "min_bars": 80,
        "youtube": "https://youtu.be/67u8mdQ8f08",
        "indicators": ["Session Volume Profile", "POC", "VAH/VAL", "Hammer / Shooting Star"],
        "entry_rules": [
            "VA reversal: price tags VAL/VAH with rejection candle confirmation.",
            "POC compression breakout when multi-day POCs sit in a tight band then break.",
            "I-profile LVN: price enters a low-volume void and slices through.",
        ],
        "exit_rules": [
            "Stop beyond rejection wick / LVN invalidation.",
            "Targets: POC then opposite value-area edge.",
        ],
    },
    {
        "id": "volume_profile_poc",
        "name": "Volume Profile POC",
        "description": "First-touch pullback to HVN zone edge after breakout · LVN stops · next-HVN targets.",
        "timeframes": ["15m", "30m", "1h", "4h", "1d"],
        "min_bars": 100,
        "youtube": "https://www.youtube.com/watch?v=ooHX6tf5RVI",
        "indicators": ["Fixed-range Volume Profile", "POC / HVN zone", "LVN"],
        "entry_rules": [
            "Build HVN zone around POC.",
            "Wait for breakout beyond the zone, then enter on the FIRST retest of the zone edge.",
        ],
        "exit_rules": [
            "Stop in an LVN behind the HVN barrier.",
            "Target just before the next HVN shelf.",
        ],
    },
    {
        "id": "pa_volume_profile",
        "name": "PA - Volume Profile",
        "description": "FVG + VP cluster · S/R flip first retest — Trader Dale institutional volume filter.",
        "timeframes": ["5m", "15m", "30m", "1h"],
        "min_bars": 80,
        "youtube": "https://www.youtube.com/watch?v=FVoXWlNkdhs",
        "indicators": ["3-candle FVG", "Fixed-range VP / POC", "Pivot S/R"],
        "entry_rules": [
            "Bullish/bearish FVG with VP POC clustered at the gap start.",
            "S/R flip with volume cluster at the break — trade the first retest only.",
        ],
        "exit_rules": [
            "Stop beyond the VP cluster / flipped level.",
            "Target from gap extension or measured move from the flip.",
        ],
    },
    {
        "id": "pa_vp_smc",
        "name": "PA-VP-SMC",
        "description": "Price Action + Volume Profile + Smart Money Concepts confluence · confidence-scored trades.",
        "timeframes": ["15m", "30m", "1h", "4h"],
        "min_bars": 100,
        "youtube": None,
        "indicators": ["EMA trend", "Liquidity sweep", "Order Block / FVG", "Volume Profile", "VSA thrust"],
        "entry_rules": [
            "Require multiple independent pillars to agree (trend, sweep, VP level, SMC zone).",
            "Backtest uses a single-TF confluence proxy (EMA + sweep + VSA).",
        ],
        "exit_rules": [
            "Stop beyond confluence zone; target next VP level or R:R floor.",
        ],
    },
    {
        "id": "volume_spread_next_candle",
        "name": "Volume Spread - Next Candle",
        "description": "VSA Downthrust · No Supply · Upthrust · No Demand — Wyckoff next-candle edge.",
        "timeframes": ["5m", "15m", "30m", "1h"],
        "min_bars": 80,
        "youtube": "https://www.youtube.com/watch?v=ncrqXFCQKOU&list=PLXWi52aRZnNF_HW-TedxAE1Tyx1C8XrGn",
        "indicators": ["Candle spread (|C−O|)", "Volume 20 MA", "Ultra-high volume peak"],
        "entry_rules": [
            "SOS (Downthrust / No Supply) → long next candle.",
            "SOW (Upthrust / No Demand) → short next candle.",
        ],
        "exit_rules": [
            "Primary edge is the next candle; stop beyond signal extreme; R:R target.",
        ],
    },
    {
        "id": "bb_mean_reversion",
        "name": "BB Mean Reversion",
        "description": "Bollinger %B stretch, confirmed by a range-bound market (Kaufman Efficiency Ratio) and RSI extreme — up to 13 optional confluence checks on the live scanner.",
        "timeframes": ["15m", "30m", "1h", "4h", "1d"],
        "min_bars": 60,
        "youtube": None,
        "indicators": ["Bollinger Bands (%B)", "Kaufman Efficiency Ratio", "RSI(14)"],
        "entry_rules": [
            "Price stretched to %B >= 1.0 (short) or <= 0.0 (long) beyond the 20-bar, 2σ Bollinger Band.",
            "Market must be genuinely range-bound (Efficiency Ratio < 0.5) — good conditions to fade a stretch.",
            "RSI must echo the same extreme (>=60 confirms the short, <=40 confirms the long).",
        ],
        "exit_rules": [
            "Target: reversion back toward the 20-bar mean (band midline).",
            "Stop: ATR-sane distance beyond the stretch extreme.",
        ],
    },
    {
        "id": "bb_rsi_vol",
        "name": "BB-RSI-VOL",
        "description": "Lower BB + RSI≤35 + low volume → Buy; Upper BB + RSI≥70 + high volume → Sell. Filtered by S/R and 9/50 EMA. Reports conf% · SL% · TP%.",
        "timeframes": ["5m", "15m", "30m", "1h", "4h", "1d"],
        "min_bars": 80,
        "youtube": None,
        "indicators": ["Bollinger Bands(20,2)", "RSI(14)", "Volume MA20", "EMA9", "EMA50", "Swing S/R"],
        "entry_rules": [
            "BUY: touch/pierce Lower BB, RSI ≤ 35, volume below MA20, near Support, close above 9 EMA.",
            "SELL: touch/pierce Upper BB, RSI ≥ 70, volume above MA20, near Resistance, close below 9 EMA.",
            "Skip falling-knife longs / melt-up shorts (steep 50 EMA or high Efficiency Ratio).",
        ],
        "exit_rules": [
            "T1: mid Bollinger Band (20 SMA). T2: opposite band or next S/R.",
            "SL below swing low + support (long) or above climax wick (short).",
        ],
    },
    {
        "id": "ema9_vol_rsi_momentum",
        "name": "9 EMA Vol RSI Scalp",
        "description": (
            "5m momentum scalp with 15m EMA bias · score ≥7 · 9 EMA hold · "
            "vol > SMA50 · RSI momentum · prior high/low break · structure SL · min 1:2 RR."
        ),
        "timeframes": ["1m", "5m", "15m", "30m", "1h"],
        "min_bars": 80,
        "youtube": None,
        "indicators": ["EMA9", "Volume SMA50", "RSI(14)", "ATR(14)"],
        "entry_rules": [
            "BUY: ≥4 closes above 9 EMA · HH/HL · vol > SMA50 · RSI>40 rising · close > prior high · score ≥7.",
            "SELL: ≥4 closes below 9 EMA · LH/LL · vol > SMA50 · RSI falling · close < prior low · score ≥7.",
            "Skip EMA chop, RSI>70 long chase, and huge ATR-sized impulse candles.",
        ],
        "exit_rules": [
            "SL beyond recent swing (+ ATR buffer).",
            "T1 at 1:2 RR; scale T2/T3; invalidate on close back through 9 EMA.",
        ],
    },
    {
        "id": "elliott_wave_pro",
        "name": "Elliott Wave (Pro Trade)",
        "description": "Algorithmic ZigZag 5-wave impulse / ABC corrective count — trades only on a completed Wave 5 or Wave C. (Distinct from the separate 'Elliott Wave Screener' under TA Screeners.)",
        "timeframes": ["1h", "4h", "1d", "1wk"],
        "min_bars": 60,
        "youtube": None,
        "indicators": ["ZigZag pivots", "Fibonacci wave targets"],
        "entry_rules": [
            "Valid 5-wave impulse just completed (Wave 5) → fade the move, expect an ABC correction.",
            "Valid ABC correction just completed (Wave C) → trade resumption of the original trend.",
        ],
        "exit_rules": [
            "Stop beyond the signal wave's extreme (ATR buffer).",
            "Target: nearest Fibonacci wave projection.",
        ],
    },
]

TA_STRATEGIES: list[dict[str, Any]] = [
    {
        "id": "ta_sentiment_screener",
        "name": "Trend & Sentiment Screener",
        "label": "Trend & Sentiment Screener",
        "description": "Composite multi-indicator sentiment score with ATR-based BUY/SELL signals.",
        "timeframes": ["5m", "15m", "1h", "4h", "1d"],
        "min_bars": 80,
        "runner": "rolling_sentiment",
    },
    {
        "id": "ta_mtf_scanner",
        "name": "MTF Scanner",
        "label": "MTF Scanner",
        "description": "Multi-timeframe confluence — bullish/bearish composite score crossovers.",
        "timeframes": ["5m", "15m", "1h", "4h", "1d"],
        "min_bars": 60,
        "runner": "rolling_mtf",
    },
    {
        "id": "ta_ticker_investigation",
        "name": "Ticker Investigation (Composite)",
        "label": "Ticker Investigation",
        "description": "Rolling composite sentiment proxy aligned with investigation scoring on historical bars.",
        "timeframes": ["1d", "4h", "1h"],
        "min_bars": 80,
        "runner": "rolling_sentiment",
    },
]

ENGINE_STRATEGY_META: dict[str, dict[str, Any]] = {}
ENGINE_RUNNER_KIND: dict[str, str] = {}

# These sections are "current-state" evaluators (they return the latest
# signal, not a vectorized full-history series) and are multi-strategy or
# multi-dataframe shaped — none of the existing runner kinds (analyze_bt's
# run_bt flag, signal_df's single-df builder, rolling_sentiment's generic
# composite score) actually exercise their real logic. Showing a backtest
# for them via the generic fallback would silently test the WRONG thing, so
# they're excluded here rather than faked; they still have a proper live
# scan via /trading-hubs/scan.
_NO_GENERIC_BACKTEST: frozenset[str] = frozenset({
    "swing_5_strategies", "scalp_weekly", "swing_trend_breakout",
    "smc_htf_zone_sweep", "weekly_candle_continuation",
})

for section in HUB_SECTIONS:
    sid = section["id"]
    if sid in _NO_GENERIC_BACKTEST:
        continue
    hub = section["hub"]
    cat_id = _HUB_CATEGORY_MAP[hub]
    hub_label = HUB_META[hub]["label"]
    tfs = _HUB_TIMEFRAMES.get(sid, ["1d"])
    min_bars = _HUB_MIN_BARS.get(sid, 60)

    if sid == "swing_trading_st":
        runner = "analyze_bt"
    elif sid in {
        "swing_trading_st_supertrend",
        "swing_trading_st_kiss",
        "swing_trading_st_ha_ema",
        "scalp_ny_open_bias",
        "smc_five_filter",
        "support_resistance",
        "footprint",
        "reversal_strategy",
        "intra_hedging",
    }:
        runner = "analyze_bt"
    elif sid in {
        "intraday_vwap_fade",
        "intraday_fib_945",
        "intraday_london_breakout",
        "scalp_rectangle",
        "smc_cisd",
        "smc_weekly_sweep_cisd",
        "smc_golden_bullet",
        "scalp_ichimoku_crash",
        "swing_trend_velocity",
        "swing_bb_vwap_reversal",
        "smc_liquidity_silver_bullet",
        "scalp_a_plus",
        "scalp_gold",
    }:
        runner = "signal_df"
    else:
        runner = "rolling_sentiment"

    if sid == "support_resistance":
        # analyze_ticker/scan_universe never populate result["backtest"] (the
        # "analyze_bt" runner's requirement) — run_bt is a dead/unused param
        # on scan_universe, not analyze_ticker. Reuse the pro_trade_signal_df
        # runner instead: build_support_resistance_signals (pro_trade_backtest.py)
        # replays the engine's own run_sr_pipeline/evaluate_live_signal against
        # a synthesized HTF, so this is a real historical replay, not a proxy.
        runner = "pro_trade_signal_df"

    ENGINE_RUNNER_KIND[sid] = runner
    ENGINE_STRATEGY_META[sid] = {
        "id": sid,
        "name": section["label"],
        "category": cat_id,
        "category_label": f"Trading Hubs — {hub_label}",
        "timeframes": tfs,
        "summary": section["description"],
        "description": section["description"],
        "indicators": [],
        "entry_rules": [],
        "exit_rules": [],
        "needs_benchmark": False,
        "min_bars": min_bars,
        "engine": True,
        "hub": hub,
    }

if "smc_five_filter" in ENGINE_STRATEGY_META:
    ENGINE_STRATEGY_META["smc_five_filter"].update({
        "indicators": ["HTF Order Block", "Fair Value Gap", "Liquidity Sweep", "Swing High/Low (discount/premium)"],
        "entry_rules": [
            "Permission: latest UNMITIGATED HTF supply/demand zone exists (demand → longs only, supply → shorts only).",
            "Footprint: the zone's origin candle was preceded by a validated liquidity sweep of a prior HTF swing.",
            "Inefficiency: an unfilled Fair Value Gap sits in the same leg as the zone.",
            "Location: zone sits in the discount half of the leg for longs, or the premium half for shorts.",
            "Exit Test: untouched HTF liquidity ahead of price clears the minimum reward:risk.",
            "Aggressive entry: price taps the zone — enter immediately at the zone midpoint.",
            "Conservative entry: price taps the zone AND an LTF Change of Character confirms the reversal.",
            "Ultra-Conservative entry: Conservative confirmation AND a stacked same-direction LTF continuation FVG.",
        ],
        "exit_rules": [
            "Stop beyond the HTF zone edge (or the sweep extreme).",
            "Target = the Exit Test's untouched HTF liquidity level.",
            "Exit if price closes back beyond the zone stop — setup invalidated.",
        ],
    })

if "support_resistance" in ENGINE_STRATEGY_META:
    ENGINE_STRATEGY_META["support_resistance"].update({
        "indicators": ["HTF Support/Resistance Zone", "Break-and-Retest Role Flip", "LTF Swing Structure"],
        "entry_rules": [
            "HTF zone identified from wick-to-body rejection clusters, not exact price lines.",
            "Break-and-retest: a zone broken since it formed flips role (old resistance → new support, and vice versa).",
            "Price must tap back into the active zone (with a small buffer) before anything else is considered.",
            "LTF confirmation: after the tap, price must cleanly break the most recent lower high (longs) or higher low (shorts) — never enter on the tap alone.",
        ],
        "exit_rules": [
            "Stop beyond the zone edge (or the pre-entry extreme).",
            "Target = the next recent structural high/low, usually the opposing zone.",
            "Exit if price closes back beyond the zone stop — setup invalidated.",
        ],
    })

if "scalp_a_plus" in ENGINE_STRATEGY_META:
    ENGINE_STRATEGY_META["scalp_a_plus"].update({
        "indicators": ["Daily trading range", "Decisional / extreme POI", "1H trap filter", "LTF two-leg BOS", "Fair Value Gap"],
        "entry_rules": [
            "Map daily external high/low trading range and bias.",
            "Qualify a decisional POI (depth ≥50%, duration, inducement).",
            "1H narrative must not trip the smart-money trap filter.",
            "Price tapping the HTF POI + LTF two-leg structure breaks in bias + FVG limit entry.",
        ],
        "exit_rules": [
            "Stop beyond recent LTF swing / FVG extreme.",
            "Primary target ~3R intrasession; optional runner toward 10R / liquidity magnet.",
            "Flatten if HTF POI thesis fails or trap resume.",
        ],
    })

if "scalp_gold" in ENGINE_STRATEGY_META:
    ENGINE_STRATEGY_META["scalp_gold"].update({
        "indicators": ["1H structure bias", "15m demand/supply POI", "Liquidity sweep", "Internal MSS"],
        "entry_rules": [
            "1H and 15m structure bias must align.",
            "Mark extreme 15m demand (longs) / supply (shorts); wait for price inside a POI.",
            "Enter after liquidity sweep at the POI (aggressive) or after MSS + pullback (conservative).",
        ],
        "exit_rules": [
            "Stop just beyond the sweep candle extreme.",
            "Target next logical 15m swing / opposing zone (min R:R).",
            "Intrasession scalp — flatten if 15m structure breaks against you.",
        ],
    })

if "footprint" in ENGINE_STRATEGY_META:
    ENGINE_STRATEGY_META["footprint"].update({
        "indicators": ["OHLCV Delta Proxy", "Stacked Imbalance Detector", "Absorption Detector (volume z-score + body/ATR)", "HTF Support/Resistance Zone"],
        "entry_rules": [
            "Price must first tap into a key HTF support/resistance zone.",
            "Step 1 Delta: net estimated buy/sell volume over the recent bars must favor the reversal direction.",
            "Step 2 Imbalances: 3+ stacked bars where one side overwhelms the other, in the same direction as Delta.",
            "Step 3 Absorption: a high-volume, small-body bar confirming the opposing side is being absorbed at the zone.",
            "All three steps must confirm, in order, before entry.",
        ],
        "exit_rules": [
            "Stop beyond the zone edge.",
            "Target = the opposing key level.",
            "Exit if price closes back beyond the zone stop — setup invalidated.",
        ],
    })

if "reversal_strategy" in ENGINE_STRATEGY_META:
    ENGINE_STRATEGY_META["reversal_strategy"].update({
        "indicators": ["Swing High/Low Structure", "Horizontal S/R Zones", "Trendlines", "MACD (12,26,9)", "ATR(14)", "50/20 EMA"],
        "entry_rules": [
            "Step 1 Market Condition: bullish/bearish/ranging read from swing structure — a choppy read rejects the setup outright.",
            "Step 2 Market Phase: the latest push must be an extended 'run' (>=2x ATR since the last swing), not a fresh pullback.",
            "Step 3 Support/Resistance: price must be tapping a horizontal zone (round-number proximity and trendlines noted as extra context).",
            "Step 4 MACD Divergence: price makes a new high/low that MACD does not confirm, in the reversal direction.",
            "Step 5 Deceleration: candle bodies progressively shrinking into the level.",
            "Step 6 Candlestick Trigger: Low/High Test, Tweezer Top/Bottom, Doji, or Inside Bar on the signal candle.",
            "Divergence + Deceleration + Trigger must all confirm before entry.",
        ],
        "exit_rules": [
            "Stop just beyond the signal candle's opposite extreme (ATR-based buffer).",
            "Target: the 50 EMA in a trending market condition, or the next major level while ranging — auto-selected or pinned via config.",
            "Minimum 1:1 reward:risk enforced; target extended to hold it if the natural target falls short.",
        ],
    })

if "intra_hedging" in ENGINE_STRATEGY_META:
    ENGINE_STRATEGY_META["intra_hedging"].update({
        "indicators": ["Intraday Session Momentum (open vs. latest close)", "Beta vs. Nifty 50 (90-day daily returns)", "ATR(14)"],
        "entry_rules": [
            "Rank every tracked Nifty sector index (28 total, direct index ticker or constituent proxy) by today's intraday momentum (session open vs. latest close).",
            "Momentum spread between the strongest and weakest sector must clear the minimum divergence threshold — a flat/non-divergent day sits out.",
            "LONG the strongest sector, SHORT the weakest sector — a beta-neutral pair, not a single-sided directional bet.",
            "Capital split per leg is inverse-Beta-weighted: long_weight = short_beta / (long_beta + short_beta), short_weight = long_beta / (long_beta + short_beta).",
        ],
        "exit_rules": [
            "Stop per leg is ATR-based (roughly 1x ATR as % of price).",
            "Exit if the momentum spread between the two legs closes or reverses.",
            "Flat by end of session regardless — this is a same-day pairs trade, never held overnight.",
        ],
    })

for ta in TA_STRATEGIES:
    ENGINE_RUNNER_KIND[ta["id"]] = ta["runner"]
    ENGINE_STRATEGY_META[ta["id"]] = {
        "id": ta["id"],
        "name": ta["name"],
        "category": "technical_analysis",
        "category_label": "Technical Analysis",
        "timeframes": ta["timeframes"],
        "summary": ta["description"],
        "description": ta["description"],
        "indicators": [],
        "entry_rules": [],
        "exit_rules": [],
        "needs_benchmark": False,
        "min_bars": ta["min_bars"],
        "engine": True,
    }

for pt in PRO_TRADE_STRATEGIES:
    ENGINE_RUNNER_KIND[pt["id"]] = "pro_trade_signal_df"
    ENGINE_STRATEGY_META[pt["id"]] = {
        "id": pt["id"],
        "name": pt["name"],
        "category": "pro_trade",
        "category_label": "Pro Trade",
        "timeframes": pt["timeframes"],
        "summary": pt["description"],
        "description": pt["description"],
        "indicators": pt.get("indicators") or [],
        "entry_rules": pt.get("entry_rules") or [],
        "exit_rules": pt.get("exit_rules") or [],
        "needs_benchmark": False,
        "min_bars": pt["min_bars"],
        "engine": True,
        "youtube": pt.get("youtube"),
        "pro_trade": True,
    }

ETF_TA_STRATEGIES: list[dict[str, Any]] = [
    {
        "id": "stf_shop",
        "name": "ETF Shop 4.0 — 20 DMA · dynamic SIP · FIFO",
        "description": (
            "Single-ticker proxy of ETF Shop 4.0: buy when price is cheap vs 20 DMA, "
            "exit at ~6% profit target or when price reclaims the 20 DMA. "
            "Live shop is a multi-ETF rotator with SIP latch + FIFO lots — this backtest "
            "is the per-name swing/SIP spirit for research."
        ),
        "timeframes": ["1d"],
        "min_bars": 80,
        "youtube": "https://www.youtube.com/watch?v=xrKfKpNhkTE",
        "indicators": ["20 DMA", "Pct from DMA", "Profit target %"],
        "entry_rules": [
            "Buy when close is below the 20-day moving average (cheap vs average).",
        ],
        "exit_rules": [
            "Take profit at the configured target (default 6% from entry), or",
            "Exit when price reclaims the 20 DMA after being long.",
        ],
    },
]

for etf in ETF_TA_STRATEGIES:
    ENGINE_RUNNER_KIND[etf["id"]] = "etf_ta_signal_df"
    ENGINE_STRATEGY_META[etf["id"]] = {
        "id": etf["id"],
        "name": etf["name"],
        "category": "etf_ta",
        "category_label": "ETF TA IN",
        "timeframes": etf["timeframes"],
        "summary": etf["description"],
        "description": etf["description"],
        "indicators": etf.get("indicators") or [],
        "entry_rules": etf.get("entry_rules") or [],
        "exit_rules": etf.get("exit_rules") or [],
        "needs_benchmark": False,
        "min_bars": etf["min_bars"],
        "engine": True,
        "youtube": etf.get("youtube"),
        "etf_ta": True,
    }

_TA_SCREENER_RUNNERS: dict[str, str] = {
    "zireman_confluence": "ta_native_bt",
    "pump_dump_breakout": "ta_native_bt",
}

_TA_SCREENER_MIN_BARS: dict[str, int] = {
    "weak_strong_sr": 100,
    "fakeout_4h": 120,
    "fakeout_15m": 150,
    "top_down_mtf": 80,
    "smc_fake_shift": 100,
    "weekly_stoch": 60,
    "kn_smart_rsi": 100,
    "velez_retracement": 100,
    "smart_wave_crypto": 80,
    "crypto_scalping": 100,
    "pump_dump_breakout": 80,
    "big_whale": 60,
    "zireman_confluence": 80,
}

for screener in TA_SCREENERS:
    sid = screener["id"]
    if sid in {"ticker_investigation", "sentiment_screener", "mtf_scanner"}:
        continue
    if not screener.get("engine"):
        continue
    default_tf = screener.get("default_tf", "15m")
    tfs = [default_tf]
    if default_tf == "15m":
        tfs = ["5m", "15m", "30m", "1h"]
    elif default_tf == "5m":
        tfs = ["5m", "15m"]
    elif default_tf == "1m":
        tfs = ["1m", "5m"]
    elif default_tf == "1d":
        tfs = ["1d", "4h"]
    elif default_tf == "30m":
        tfs = ["30m", "1h", "4h"]

    runner = _TA_SCREENER_RUNNERS.get(sid, "rolling_ta_screener")
    ENGINE_RUNNER_KIND[sid] = runner
    ENGINE_STRATEGY_META[sid] = {
        "id": sid,
        "name": screener["label"],
        "category": "ta_screeners",
        "category_label": "TA Screeners",
        "timeframes": tfs,
        "summary": f"{screener['label']} — migrated TA screener engine.",
        "description": f"{screener['label']} screener backtest (rolling replay).",
        "indicators": [],
        "entry_rules": [],
        "exit_rules": [],
        "needs_benchmark": False,
        "min_bars": _TA_SCREENER_MIN_BARS.get(sid, 80),
        "engine": True,
        "screener": True,
        "default_tf": default_tf,
    }

ENGINE_STRATEGY_CATEGORIES: dict[str, dict[str, Any]] = {
    "th_swing": {
        "label": "Trading Hubs — Swing Trading",
        "description": ENGINE_CATEGORY_DESCRIPTIONS["th_swing"],
        "timeframes": ["1d", "1wk", "4h", "1h", "15m", "5m"],
        "strategy_ids": [s["id"] for s in HUB_SECTIONS if s["hub"] == "swing"],
    },
    "th_intraday": {
        "label": "Trading Hubs — Intraday",
        "description": ENGINE_CATEGORY_DESCRIPTIONS["th_intraday"],
        "timeframes": ["5m", "15m", "1m"],
        "strategy_ids": [s["id"] for s in HUB_SECTIONS if s["hub"] == "intraday"],
    },
    "th_scalping": {
        "label": "Trading Hubs — Scalping",
        "description": ENGINE_CATEGORY_DESCRIPTIONS["th_scalping"],
        "timeframes": ["1m"],
        "strategy_ids": [s["id"] for s in HUB_SECTIONS if s["hub"] == "scalping"],
    },
    "th_smart_money": {
        "label": "Trading Hubs — Smart Money",
        "description": ENGINE_CATEGORY_DESCRIPTIONS["th_smart_money"],
        "timeframes": ["15m", "5m"],
        "strategy_ids": [s["id"] for s in HUB_SECTIONS if s["hub"] == "smart_money"],
    },
    "pro_trade": {
        "label": "Pro Trade",
        "description": ENGINE_CATEGORY_DESCRIPTIONS["pro_trade"],
        "timeframes": ["5m", "15m", "30m", "1h", "4h", "1d"],
        "strategy_ids": [p["id"] for p in PRO_TRADE_STRATEGIES],
    },
    "etf_ta": {
        "label": "ETF TA IN",
        "description": ENGINE_CATEGORY_DESCRIPTIONS["etf_ta"],
        "timeframes": ["1d"],
        "strategy_ids": [e["id"] for e in ETF_TA_STRATEGIES],
    },
    "technical_analysis": {
        "label": "Technical Analysis",
        "description": ENGINE_CATEGORY_DESCRIPTIONS["technical_analysis"],
        "timeframes": ["5m", "15m", "1h", "4h", "1d"],
        "strategy_ids": [t["id"] for t in TA_STRATEGIES],
    },
    "ta_screeners": {
        "label": "TA Screeners",
        "description": ENGINE_CATEGORY_DESCRIPTIONS["ta_screeners"],
        "timeframes": ["1m", "5m", "15m", "30m", "1h", "4h", "1d"],
        "strategy_ids": [
            s["id"] for s in TA_SCREENERS
            if s.get("engine") and s["id"] not in {"ticker_investigation", "sentiment_screener", "mtf_scanner"}
        ],
    },
}


def is_engine_strategy(name: str) -> bool:
    return name in ENGINE_STRATEGY_META


def engine_min_bars(name: str) -> int:
    return int(ENGINE_STRATEGY_META.get(name, {}).get("min_bars", 60))


def engine_runner_kind(name: str) -> str:
    return ENGINE_RUNNER_KIND.get(name, "rolling_sentiment")


def list_engine_categories() -> list[dict[str, Any]]:
    categories = []
    for cat_id, info in ENGINE_STRATEGY_CATEGORIES.items():
        strategies = [ENGINE_STRATEGY_META[sid] for sid in info["strategy_ids"] if sid in ENGINE_STRATEGY_META]
        categories.append({
            "id": cat_id,
            "label": info["label"],
            "description": info["description"],
            "timeframes": info["timeframes"],
            "strategy_count": len(strategies),
            "strategies": strategies,
        })
    return categories
