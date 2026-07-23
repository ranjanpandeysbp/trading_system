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
    scalp_multi_indicator_engine,
    scalp_rectangle_engine,
    scalp_heikin_ashi_engine,
    scalp_smc_engine,
    scalp_sr_mss_engine,
    sc_fvg_engine,
    smb_snp_engine,
    smc_cisd_engine,
    smc_golden_bullet_engine,
    smc_lewiskelly_engine,
    smc_liquidity_engine,
    smc_mtf_day_plan_engine,
    smc_sc_best_engine,
    smc_ttg_sniper_engine,
    smc_weekly_sweep_cisd_engine,
    swing_trading_st_engine,
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
) -> HubSection:
    return {
        "id": id,
        "hub": hub,
        "label": label,
        "description": description,
        "module": module,
        "config_cls": config_cls,
        "config_options": config_options or {},
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
        description="2-minute 10/20 EMA pullback scalp on Nifty/Bank Nifty/Sensex with ITM option-leg selection — always scans these three indices regardless of the ticker picker above.",
        module=scalp_2min_engine,
        config_cls=scalp_2min_engine.Scalp2MinConfig,
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
