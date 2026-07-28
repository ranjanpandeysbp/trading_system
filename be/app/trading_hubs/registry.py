"""Registry of Swing / Intraday / Scalping / Smart Money hub sections."""

from __future__ import annotations

import dataclasses
import inspect
from typing import Any

from app.trading_hubs import (
    intra_hwp_engine,
    intraday_7_wasted_engine,
    intraday_alpha_945_engine,
    intraday_fib945_engine,
    intraday_mtf_breakout_retest_engine,
    intraday_vwap_fade_engine,
    scalp_2min_engine,
    scalp_arc_engine,
    scalp_crt_fvg_engine,
    scalp_ichimoku_crash_engine,
    scalp_multi_indicator_engine,
    scalp_ny_open_bias_engine,
    scalp_rectangle_engine,
    scalp_heikin_ashi_engine,
    scalp_livefree_fx_engine,
    scalp_smc_engine,
    scalp_sr_mss_engine,
    scalp_weekly_engine,
    weekly_candle_continuation_engine,
    sc_fvg_engine,
    smb_snp_engine,
    smc_cisd_engine,
    smc_htf_zone_sweep_engine,
    smc_golden_bullet_engine,
    smc_lewiskelly_engine,
    smc_liquidity_engine,
    smc_liquidity_silver_bullet_engine,
    smc_mtf_day_plan_engine,
    smc_sc_best_engine,
    smc_ttg_sniper_engine,
    smc_weekly_sweep_cisd_engine,
    swing_5_strategies_engine,
    swing_bb_vwap_reversal_engine,
    swing_trading_st_engine,
    swing_trend_breakout_engine,
    swing_trend_velocity_engine,
    swing_trading_st_ha_ema_engine,
    swing_trading_st_kiss_engine,
    swing_trading_st_mtf_mss_engine,
    swing_trading_st_simple_steal_engine,
    swing_trading_st_supertrend_engine,
)
from app.trading_hubs.swing_trading_st_engine import STRATEGY_CONTINUATION, STRATEGY_MEAN_REVERSION

HubSection = dict[str, Any]


def _section(
    *,
    id: str,
    hub: str,
    label: str,
    description: str,
    module: Any,
    config_cls: type,
    config_options: dict[str, Any] | None = None,
    fixed_universe: list[str] | None = None,
    fixed_universe_label: str | None = None,
    multi_strategy: bool = False,
    strategy_keys: list[str] | None = None,
    strategy_labels: dict[str, str] | None = None,
    timeframe_options: list[str] | None = None,
) -> HubSection:
    return {
        "id": id,
        "hub": hub,
        "label": label,
        "description": description,
        "module": module,
        "config_cls": config_cls,
        "config_options": config_options or {},
        # When set, the FE hides the asset-class / ticker picker and the scan
        # ignores client-selected tickers (engine uses this fixed list instead).
        "fixed_universe": fixed_universe,
        "fixed_universe_label": fixed_universe_label,
        # When set, this section is a multi-strategy/multi-timeframe scanner
        # (e.g. Swing 5 Strategies) that doesn't fit the generic single-config
        # scan flow — the FE routes it to a dedicated panel + endpoint instead
        # of the standard run_section_scan path.
        "multi_strategy": multi_strategy,
        "strategy_keys": strategy_keys or [],
        "strategy_labels": strategy_labels or {},
        "timeframe_options": timeframe_options or [],
    }


HUB_SECTIONS: list[HubSection] = [
    _section(
        id="swing_trading_st",
        hub="swing",
        label="Capitulation & Continuation Breakout",
        description="Daily swing — mean reversion capitulation or continuation breakout.",
        module=swing_trading_st_engine,
        config_cls=swing_trading_st_engine.STConfig,
        config_options={
            "strategy": {
                "type": "select",
                "label": "Strategy",
                "choices": [
                    {"value": STRATEGY_MEAN_REVERSION, "label": "Mean Reversion (Capitulation)"},
                    {"value": STRATEGY_CONTINUATION, "label": "Continuation Breakout"},
                ],
                "default": STRATEGY_CONTINUATION,
            },
        },
    ),
    _section(
        id="swing_trading_st_mtf_mss",
        hub="swing",
        label="Weekly Fakeout + 15m MSS",
        description="Weekly levels, daily fakeout screen, 15m market structure shift.",
        module=swing_trading_st_mtf_mss_engine,
        config_cls=swing_trading_st_mtf_mss_engine.MTFMSSConfig,
    ),
    _section(
        id="swing_trading_st_supertrend",
        hub="swing",
        label="SuperTrend + SMA 10 Swing & Pyramiding",
        description="SuperTrend with SMA trail — swing or pyramid mode.",
        module=swing_trading_st_supertrend_engine,
        config_cls=swing_trading_st_supertrend_engine.STSuperTrendConfig,
        config_options={
            "mode": {
                "type": "select",
                "label": "Mode",
                "choices": [
                    {"value": swing_trading_st_supertrend_engine.MODE_SWING, "label": "Swing"},
                    {"value": swing_trading_st_supertrend_engine.MODE_PYRAMID, "label": "Pyramid"},
                ],
                "default": swing_trading_st_supertrend_engine.MODE_SWING,
            },
        },
    ),
    _section(
        id="swing_trading_st_kiss",
        hub="swing",
        label="KISS Swing Systematic",
        description="Weekly HA filter with 1h/4h KISS systematic entries.",
        module=swing_trading_st_kiss_engine,
        config_cls=swing_trading_st_kiss_engine.KISSConfig,
    ),
    _section(
        id="swing_trading_st_ha_ema",
        hub="swing",
        label="Daily HA Bias + 34 EMA Intraday",
        description="Daily Heikin-Ashi bias with 5m/15m 34 EMA execution.",
        module=swing_trading_st_ha_ema_engine,
        config_cls=swing_trading_st_ha_ema_engine.HAEmaConfig,
    ),
    _section(
        id="intraday_alpha_945",
        hub="intraday",
        label="9:45 AM Alpha Scanner",
        description="Opening 30m range breakout after 9:45 IST with relative strength filters.",
        module=intraday_alpha_945_engine,
        config_cls=intraday_alpha_945_engine.Alpha945Config,
    ),
    _section(
        id="intraday_fib_945",
        hub="intraday",
        label="9:45 Fib 50% Bias + 10 EMA",
        description="Post-9:45 Fibonacci 50% bias with 10 EMA alignment.",
        module=intraday_fib945_engine,
        config_cls=intraday_fib945_engine.Fib945Config,
    ),
    _section(
        id="intraday_vwap_fade",
        hub="intraday",
        label="VWAP Fade Value Area",
        description="Fade extensions from VWAP value area with time stop.",
        module=intraday_vwap_fade_engine,
        config_cls=intraday_vwap_fade_engine.VwapFadeConfig,
    ),
    _section(
        id="scalp_rectangle",
        hub="scalping",
        label="1m Rectangle Sniper Entry",
        description="1-minute rectangle consolidation breakout sniper entries.",
        module=scalp_rectangle_engine,
        config_cls=scalp_rectangle_engine.RectangleConfig,
    ),
    _section(
        id="smc_cisd",
        hub="smart_money",
        label="CISD Entry Rule",
        description="Liquidity sweep → CISD break → institutional entry.",
        module=smc_cisd_engine,
        config_cls=smc_cisd_engine.CISDConfig,
    ),
    _section(
        id="smc_weekly_sweep_cisd",
        hub="smart_money",
        label="Weekly Liquidity Sweep & CISD",
        description="Previous week high/low sweep with lower-TF CISD confirmation.",
        module=smc_weekly_sweep_cisd_engine,
        config_cls=smc_weekly_sweep_cisd_engine.WeeklySweepCISDConfig,
    ),
    _section(
        id="smc_mtf_day_plan",
        hub="smart_money",
        label="MTF Day Plan OB · FVG · CHoCH",
        description="HTF trend + OB/FVG zones with LTF CHoCH day plan.",
        module=smc_mtf_day_plan_engine,
        config_cls=smc_mtf_day_plan_engine.DayPlanConfig,
    ),
    _section(
        id="smc_golden_bullet",
        hub="smart_money",
        label="Golden Bullet (Liquidity + Kill Zone)",
        description="Liquidity sweep in NY kill zones with HTF bias.",
        module=smc_golden_bullet_engine,
        config_cls=smc_golden_bullet_engine.GoldenBulletConfig,
    ),
    _section(
        id="smc_liquidity_silver_bullet",
        hub="smart_money",
        label="Liquidity, Inducement & Silver Bullet",
        description=(
            "HTF structure bias, then the executable Silver Bullet sequence: liquidity sweep of the day's "
            "high/low during the London or NY session, Market Structure Shift confirmation, entry on the "
            "Fair Value Gap formed during that shift, stop beyond the order block. Min 1:2 R:R. "
            "Video: https://www.youtube.com/watch?v=xnEioNLgNMM"
        ),
        module=smc_liquidity_silver_bullet_engine,
        config_cls=smc_liquidity_silver_bullet_engine.LiquiditySilverBulletConfig,
        config_options={
            "htf_tf": {
                "type": "select",
                "label": "Higher timeframe (structure bias)",
                "choices": [{"value": v, "label": v} for v in smc_liquidity_silver_bullet_engine.HTF_OPTIONS],
                "default": "4h",
            },
            "execution_tf": {
                "type": "select",
                "label": "Execution timeframe (sweep/MSS/FVG)",
                "choices": [{"value": v, "label": v} for v in smc_liquidity_silver_bullet_engine.LTF_OPTIONS],
                "default": "15m",
            },
        },
    ),
    _section(
        id="scalp_arc",
        hub="scalping",
        label="ARC Method Scalping",
        description="Area/Range/Candle boundary fades with John Wick hammer trigger at the four institutional zones.",
        module=scalp_arc_engine,
        config_cls=scalp_arc_engine.ArcConfig,
    ),
    _section(
        id="scalp_crt_fvg",
        hub="scalping",
        label="CRT + FVG Scalping",
        description="HTF Candle-Range-Theory liquidity sweep confirmed by an LTF Fair Value Gap entry.",
        module=scalp_crt_fvg_engine,
        config_cls=scalp_crt_fvg_engine.CrtFvgConfig,
    ),
    _section(
        id="scalp_multi_indicator",
        hub="scalping",
        label="Multi-Indicator Confluence Scalp",
        description="UT Bot + QQE + Vaddah Attar momentum + EMA pullback + volume delta confluence.",
        module=scalp_multi_indicator_engine,
        config_cls=scalp_multi_indicator_engine.MultiIndicatorConfig,
    ),
    _section(
        id="scalp_smc",
        hub="scalping",
        label="SMC Rule-of-3-TFs Scalp",
        description="Premium/discount/OTE zone plus FVG/order-block/CRT-sweep signal fusion across HTF/MTF/LTF.",
        module=scalp_smc_engine,
        config_cls=scalp_smc_engine.ScalpSMCConfig,
    ),
    _section(
        id="scalp_sr_mss",
        hub="scalping",
        label="HTF S/R + 1m MSS Scalp",
        description="1H/4H support/resistance zone tap confirmed by a 1-minute market structure shift.",
        module=scalp_sr_mss_engine,
        config_cls=scalp_sr_mss_engine.SrMssConfig,
    ),
    _section(
        id="scalp_weekly",
        hub="scalping",
        label="Scalp - Weekly",
        description="Previous week's high/low as a liquidity box — false-breakout fade on a lower timeframe.",
        module=scalp_weekly_engine,
        config_cls=scalp_weekly_engine.ScalpWeeklyConfig,
        config_options={
            "execution_tf": {
                "type": "select",
                "label": "Execution timeframe",
                "choices": [{"value": v, "label": v} for v in scalp_weekly_engine.LTF_OPTIONS],
                "default": "1h",
            },
        },
    ),
    _section(
        id="scalp_ichimoku_crash",
        hub="scalping",
        label="Ichimoku Crash Predictor",
        description=(
            "4-condition Ichimoku Cloud alignment (Tenkan/Kijun cross, Chikou confirmation, cloud "
            "resistance) for catching crash-scale moves — AbhishekXTrades. "
            "Video: https://www.youtube.com/watch?v=TqqqxCpPxoM"
        ),
        module=scalp_ichimoku_crash_engine,
        config_cls=scalp_ichimoku_crash_engine.IchimokuCrashConfig,
        config_options={
            "execution_tf": {
                "type": "select",
                "label": "Execution timeframe",
                "choices": [{"value": v, "label": v} for v in scalp_ichimoku_crash_engine.EXECUTION_TF_OPTIONS],
                "default": "4h",
            },
        },
    ),
    _section(
        id="scalp_ny_open_bias",
        hub="scalping",
        label="NY Open 1H Bias",
        description=(
            "The 9:00 AM ET 1-hour candle sets the day's bias (green -> longs only, red -> shorts only), "
            "executed on the 1-minute chart via one of three entry styles: first-5-minute break & retest, "
            "previous day high/low break & retest, or the one-candle-rule support/resistance hold. "
            "Min 1:2 R:R. Video: https://www.youtube.com/watch?v=qhF61rJBOyE — Scarface Trades."
        ),
        module=scalp_ny_open_bias_engine,
        config_cls=scalp_ny_open_bias_engine.NyOpenBiasConfig,
        config_options={
            "entry_style": {
                "type": "select",
                "label": "Entry style",
                "choices": [
                    {"value": v, "label": scalp_ny_open_bias_engine.ENTRY_STYLE_LABELS[v]}
                    for v in scalp_ny_open_bias_engine.ENTRY_STYLE_OPTIONS
                ],
                "default": "five_min_break_retest",
            },
        },
    ),
    _section(
        id="weekly_candle_continuation",
        hub="scalping",
        label="Weekly Candle Continuation",
        description=(
            "Trades WITH market makers extending a trend, not against it: first break of the weekly "
            "high/low is not an entry — wait for a pullback off that push, then a strong displacement "
            "close beyond the confirmation level triggers continuation in the original direction."
        ),
        module=weekly_candle_continuation_engine,
        config_cls=weekly_candle_continuation_engine.WeeklyCandleContinuationConfig,
        config_options={
            "entry_tf": {
                "type": "select",
                "label": "Entry timeframe",
                "choices": [{"value": v, "label": v} for v in weekly_candle_continuation_engine.ENTRY_TF_OPTIONS],
                "default": "1h",
            },
        },
    ),
    _section(
        id="smc_htf_zone_sweep",
        hub="smart_money",
        label="HTF Zone + LTF Liquidity Sweep",
        description=(
            "HTF (1h/4h) trend + fresh FVG/Order Block zone -> wait for pullback into the zone -> "
            "LTF (5m/15m) liquidity grab (stop-hunt wick) confirms entry. Trades with institutional flow, "
            "not against it — never enters at the obvious level, only after the sweep."
        ),
        module=smc_htf_zone_sweep_engine,
        config_cls=smc_htf_zone_sweep_engine.SMCZoneSweepConfig,
        config_options={
            "htf_tf": {
                "type": "select",
                "label": "HTF (structure + zone)",
                "choices": [{"value": v, "label": v} for v in smc_htf_zone_sweep_engine.HTF_OPTIONS],
                "default": "1h",
            },
            "ltf_tf": {
                "type": "select",
                "label": "LTF (liquidity grab confirmation)",
                "choices": [{"value": v, "label": v} for v in smc_htf_zone_sweep_engine.LTF_OPTIONS],
                "default": "15m",
            },
        },
    ),
    _section(
        id="smc_liquidity",
        hub="smart_money",
        label="SMC Liquidity (Sweeps/Grabs/FVG)",
        description="Structural BSL/SSL sweep-vs-grab classification, liquidity runs, and fair-value-gap rebalance entries.",
        module=smc_liquidity_engine,
        config_cls=smc_liquidity_engine.LiquidityConfig,
    ),
    _section(
        id="smc_ttg_sniper",
        hub="smart_money",
        label="SM - TTG - Sniper Entry",
        description="Liquidity sweep + displacement + Order Block + Fair Value Gap tap, HTF-trend-aligned, aggressive or conservative (MSS-confirmed) entry.",
        module=smc_ttg_sniper_engine,
        config_cls=smc_ttg_sniper_engine.TTGSniperConfig,
        config_options={
            "ltf": {
                "type": "select",
                "label": "Execution timeframe (LTF)",
                "choices": [{"value": v, "label": v} for v in smc_ttg_sniper_engine.LTF_OPTIONS],
                "default": "15m",
            },
            "htf": {
                "type": "select",
                "label": "HTF trend bias",
                "choices": [{"value": v, "label": v} for v in smc_ttg_sniper_engine.HTF_OPTIONS],
                "default": "1h",
            },
            "entry_mode": {
                "type": "select",
                "label": "Entry mode",
                "choices": [{"value": v, "label": v} for v in smc_ttg_sniper_engine.ENTRY_MODE_OPTIONS],
                "default": "Aggressive",
            },
        },
    ),
    _section(
        id="smb_snp",
        hub="smart_money",
        label="SMB \"Fashionably Late\"",
        description="9 EMA x VWAP cross-up after a low-of-day grind inside a session time window, sized off the LOD unit at 3:1 R:R.",
        module=smb_snp_engine,
        config_cls=smb_snp_engine.SmbSnpConfig,
    ),
    _section(
        id="swing_trading_st_simple_steal",
        hub="swing",
        label="Little Rizzy (Trendline Measured Move)",
        description="Trendline across swing highs/lows projects a measured-move target, confirmed by Bollinger Bands.",
        module=swing_trading_st_simple_steal_engine,
        config_cls=swing_trading_st_simple_steal_engine.SimpleStealConfig,
    ),
    _section(
        id="swing_5_strategies",
        hub="swing",
        label="Swing Trading — 5 Strategies",
        description=(
            "Breakouts · Episodic Pivots (Gap and Go) · Pullbacks · Uptrending Bounces · Bottom Bounces "
            "(falling knife) — five long-only swing setups from a professional trader's breakdown. Pick "
            "one or more strategies and one or more timeframes to scan."
        ),
        module=swing_5_strategies_engine,
        config_cls=swing_5_strategies_engine.Swing5Config,
        multi_strategy=True,
        strategy_keys=swing_5_strategies_engine.STRATEGY_KEYS,
        strategy_labels=swing_5_strategies_engine.STRATEGY_LABELS,
        timeframe_options=swing_5_strategies_engine.TIMEFRAME_OPTIONS,
    ),
    _section(
        id="swing_trend_breakout",
        hub="swing",
        label="Trend Following Breakout (Index Filter)",
        description=(
            "Index above its 20 SMA -> momentum leader near its 52-week high with a confirmed weekly "
            "uptrend -> daily swing-high breakout after a pullback. Long-only; works just as well on "
            "sectoral/index ETFs as individual stocks."
        ),
        module=swing_trend_breakout_engine,
        config_cls=swing_trend_breakout_engine.SwingTrendBreakoutConfig,
        config_options={
            "market_filter": {
                "type": "select",
                "label": "Market trend filter (index 20 SMA)",
                "choices": [
                    {"value": "on", "label": "On — require Nifty/SPY/BTC above its 20 SMA"},
                    {"value": "off", "label": "Off — scan regardless of market trend"},
                ],
                "default": "on",
            },
            "stop_method": {
                "type": "select",
                "label": "Stop-loss method",
                "choices": [
                    {"value": "breakout_candle_low", "label": "Breakout candle low (tighter)"},
                    {"value": "swing_low", "label": "Recent swing low (wider)"},
                ],
                "default": "breakout_candle_low",
            },
        },
    ),
    _section(
        id="swing_trend_velocity",
        hub="swing",
        label="Trend Velocity — 50/250 MA + ROC Scale-Out",
        description=(
            "Systematic position-trading system (Malik's \"White Light\" bot): golden rule is price above "
            "BOTH the 50-day and 250-day moving averages for long (mirror for short), with a rate-of-change "
            "deceleration check that scales the position down without abandoning the trend. Low-frequency, "
            "held for months to years, no tactical stop-loss. Video: https://www.youtube.com/watch?v=pBS5vrqrUjk"
        ),
        module=swing_trend_velocity_engine,
        config_cls=swing_trend_velocity_engine.TrendVelocityConfig,
    ),
    _section(
        id="swing_bb_vwap_reversal",
        hub="swing",
        label="BB + VWAP Reversal",
        description=(
            "Bollinger Bands(20, mult 1) + VWAP(source Close) multi-timeframe reversal. HTF (1h/4h) sets "
            "the bias; on the LTF (5m/15m), a candle opening above VWAP and closing below the lower band "
            "shorts, the mirror opening below VWAP and closing above the upper band buys. Book ~50% at "
            "1:2, trail toward 1:3 while price holds the correct side of VWAP. "
            "Video: https://www.youtube.com/watch?v=5s_6CLbEa2g"
        ),
        module=swing_bb_vwap_reversal_engine,
        config_cls=swing_bb_vwap_reversal_engine.BbVwapReversalConfig,
        config_options={
            "htf_tf": {
                "type": "select",
                "label": "Higher timeframe (trend bias)",
                "choices": [{"value": v, "label": v} for v in swing_bb_vwap_reversal_engine.HTF_OPTIONS],
                "default": "1h",
            },
            "execution_tf": {
                "type": "select",
                "label": "Execution timeframe (entry trigger)",
                "choices": [{"value": v, "label": v} for v in swing_bb_vwap_reversal_engine.LTF_OPTIONS],
                "default": "15m",
            },
        },
    ),
    _section(
        id="intraday_mtf_breakout_retest",
        hub="intraday",
        label="Daniel Holmes MTF Breakout & Retest",
        description="Daily bias filter, 15m equal-body support/resistance, clean-traffic chop filter, breakout-then-retest entry.",
        module=intraday_mtf_breakout_retest_engine,
        config_cls=intraday_mtf_breakout_retest_engine.MtfBreakoutRetestConfig,
    ),
    _section(
        id="intraday_7_wasted",
        hub="intraday",
        label="7 Wasted - 5m OR Breakout & Retest",
        description="5-minute opening-range breakout with daily-bullish-bias gate and retest-of-OR-high entry at 2:1 R:R.",
        module=intraday_7_wasted_engine,
        config_cls=intraday_7_wasted_engine.Intra7WastedConfig,
    ),
    _section(
        id="intra_hwp",
        hub="intraday",
        label="Intra HWP - Two-Sided Gap Fill + 21 EMA",
        description="Fixed 5m/21 EMA gap-tag-and-reverse strategy — target Today's Open, stop beyond the swing extreme since the tag.",
        module=intra_hwp_engine,
        config_cls=intra_hwp_engine.HwpConfig,
    ),
    _section(
        id="scalp_heikin_ashi",
        hub="scalping",
        label="Scalp - Heikin Ashi",
        description="100 EMA trend filter + two-candle flat Heikin Ashi pullback confirmed by a high-volume Doji, strict 1:1 R:R, market-specific morning session window.",
        module=scalp_heikin_ashi_engine,
        config_cls=scalp_heikin_ashi_engine.HeikinAshiScalpConfig,
    ),
    _section(
        id="scalp_livefree_fx",
        hub="scalping",
        label="Scalp - LiveFree FX 5m",
        description="HTF bias (1D/4H/1H) + Asia/London/NY kill zones + London liquidity sweep + 5m Break of Structure entry. Video: https://www.youtube.com/watch?v=a74KPzR7phE",
        module=scalp_livefree_fx_engine,
        config_cls=scalp_livefree_fx_engine.LiveFreeConfig,
        config_options={
            "session_profile": {
                "type": "select",
                "label": "Session profile",
                "choices": [
                    {"value": "auto", "label": "Auto (India → IST / others → EST)"},
                    {"value": "fx_est", "label": "FX / ICT EST kill zones"},
                    {"value": "india_ist", "label": "India IST cash-session analogue"},
                ],
                "default": "auto",
            },
        },
    ),
    _section(
        id="sc_fvg",
        hub="smart_money",
        label="SC - FVG (Reversal at Key Levels)",
        description="15m HTF resistance/support zone + 5m Fair Value Gap exhaustion + 1m rejection candle & structure shift entry, fixed 3:1 R:R.",
        module=sc_fvg_engine,
        config_cls=sc_fvg_engine.ScFvgConfig,
    ),
    _section(
        id="scalp_2min",
        hub="scalping",
        label="Scalp-2mins",
        description=(
            "2-minute 10/20 EMA pullback scalp on Nifty / Bank Nifty / Sensex with ITM "
            "option-leg selection. India index options only — not available for Crypto, US, "
            "or commodities."
        ),
        module=scalp_2min_engine,
        config_cls=scalp_2min_engine.Scalp2MinConfig,
        fixed_universe=list(scalp_2min_engine.INDEX_NAMES),
        fixed_universe_label="Nifty 50 · Bank Nifty · Sensex (India index options)",
    ),
    _section(
        id="smc_sc_best",
        hub="smart_money",
        label="SC-Best (5 SMC Entry Models)",
        description="Context (HTF bias/sweep) → Confirmation (LTF MSS) → Execution via Breaker Block, Fair Value Gap, Mitigation Block, Inversion FVG, or Order Block — resting limit orders at the structural origin, never a chase.",
        module=smc_sc_best_engine,
        config_cls=smc_sc_best_engine.SCBestConfig,
        config_options={
            "ltf": {
                "type": "select",
                "label": "LTF confirmation/execution timeframe",
                "choices": [{"value": v, "label": v} for v in smc_sc_best_engine.LTF_OPTIONS],
                "default": "15m",
            },
        },
    ),
    _section(
        id="smc_lewiskelly",
        hub="smart_money",
        label="C-LewisKelly (Direction · Liquidity · Location · Confirmation)",
        description="15m external structure sets bias, session/PDH-PDL liquidity sets targets, a 15m Order Block + FVG confluence is the POI, and a 1m Change of Character at that POI confirms entry.",
        module=smc_lewiskelly_engine,
        config_cls=smc_lewiskelly_engine.LewisKellyConfig,
        config_options={
            "htf_tf": {
                "type": "select",
                "label": "Direction / POI timeframe",
                "choices": [{"value": v, "label": v} for v in smc_lewiskelly_engine.HTF_OPTIONS],
                "default": "15m",
            },
        },
    ),
]

HUB_META = {
    "swing": {
        "id": "swing",
        "label": "Swing Trading",
        "description": "Multi-day & intraday ST systems — capitulation, MSS, SuperTrend, KISS, HA+EMA.",
    },
    "intraday": {
        "id": "intraday",
        "label": "Intraday",
        "description": "Session-timed scanners and opening-range breakout systems for NSE.",
    },
    "scalping": {
        "id": "scalping",
        "label": "Scalping",
        "description": "High-frequency 1m setups — rectangle sniper entries and quick R:R scalps.",
    },
    "smart_money": {
        "id": "smart_money",
        "label": "Smart Money",
        "description": "SMC liquidity, sweep, and institutional delivery models — multi-TF for India.",
    },
}

_SECTION_BY_ID = {s["id"]: s for s in HUB_SECTIONS}


def get_section(section_id: str) -> HubSection | None:
    return _SECTION_BY_ID.get(section_id)


def build_config(config_cls: type, overrides: dict[str, Any] | None) -> Any:
    if not overrides:
        return config_cls()
    fields = {f.name for f in dataclasses.fields(config_cls)}
    return config_cls(**{k: v for k, v in overrides.items() if k in fields})


def list_hubs_payload() -> dict:
    hubs = []
    for hub_id, meta in HUB_META.items():
        sections = [
            {
                "id": s["id"],
                "label": s["label"],
                "description": s["description"],
                "config_options": s["config_options"],
                "fixed_universe": s.get("fixed_universe"),
                "fixed_universe_label": s.get("fixed_universe_label"),
                "multi_strategy": s.get("multi_strategy", False),
                "strategy_keys": s.get("strategy_keys") or [],
                "strategy_labels": s.get("strategy_labels") or {},
                "timeframe_options": s.get("timeframe_options") or [],
            }
            for s in HUB_SECTIONS
            if s["hub"] == hub_id
        ]
        hubs.append({**meta, "sections": sections})
    return {"hubs": hubs}


def run_section_scan(
    section_id: str,
    tickers: list[str],
    *,
    market: str,
    groww_token: str,
    exchange: str,
    config: dict[str, Any] | None = None,
    run_bt: bool = False,
) -> dict[str, Any]:
    section = get_section(section_id)
    if not section:
        return {"error": f"Unknown section: {section_id}"}
    if section.get("multi_strategy"):
        return {"error": f"{section_id} is a multi-strategy section — use its dedicated scan endpoint instead."}
    mod = section["module"]
    cfg = build_config(section["config_cls"], config)
    kwargs: dict[str, Any] = {
        "cfg": cfg,
        "groww_token": groww_token,
        "exchange": exchange,
    }
    if "run_bt" in inspect.signature(mod.scan_universe).parameters:
        kwargs["run_bt"] = run_bt
    payload = mod.scan_universe(tickers, market, **kwargs)
    return payload or {"error": "Scan returned no data", "results": []}
