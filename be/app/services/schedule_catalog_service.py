"""Unified Alerts Setup & Schedule strategy catalog (namespaced ids)."""

from __future__ import annotations

from typing import Any

from app.market_pulse.ta_screener_registry import TA_SCREENERS
from app.strategies.registry import list_scanner_categories
from app.trading_hubs.registry import HUB_META, HUB_SECTIONS, list_hubs_payload

# Prefixes persisted on AlertSchedule.strategies_json
RUNNABLE_PREFIXES = frozenset({"scanner", "hub", "ta", "etf"})

_COMMAND_CENTER_SECTIONS: list[tuple[str, str]] = [
    ("playbook", "Trading Playbook"),
    ("tomorrow_outlook", "Tomorrow & Today Market Outlook"),
    ("mega_analyser", "Mega Analyser"),
    ("buy_sell", "Buy or Sell (India · US · Crypto · Commodity)"),
    ("investigation", "Ticker Investigation"),
    ("global_market_mood", "Global Market Mood"),
    ("momentum", "Momentum Scanner"),
    ("ema_position", "EMA Position Scanner"),
    ("divergences", "Divergences"),
    ("candlestick_chart_patterns", "Candlestick & Chart Patterns"),
    ("stop_hunt", "Stoploss Hunting"),
    ("take_profit", "Take Profit Targets"),
    ("real_bottom", "Real Bottom"),
    ("weak_strong", "Weak / Strong"),
    ("sma_20_200", "200SMA-20SMA — Bounce & Rejection"),
    ("copy_trade", "Copy Trade"),
    ("take_trade", "Take Trade"),
    ("trade_setup", "Trade Setup — Oversold/Overbought"),
    ("one_click_intraday", "One-Click Intraday Setup"),
    ("one_click_scalping", "One-Click Scalping Setup"),
    ("one_click_swing", "One-Click Swing Setup"),
    ("fundamental_analysis", "Fundamental Analysis (screener.in)"),
    ("mutual_fund_holdings", "Mutual Fund Holdings Tracker"),
    ("etf_holdings", "ETF Holdings — Stock-Level Trend (India · US · Crypto)"),
    ("smart_money_activity", "Check Smart Money Activity — MF/ETF stake flow"),
    ("detect_sector_rotation", "Detect Sector Rotation — CRS · Hull · Pullback"),
    ("stock_upgrade_downgrade", "Upgrade/Downgrade & Corporate Actions"),
    ("investigation_strategies", "Ticker Investigation — Select Strategy"),
    ("mega_setup_advisor", "Mega Setup Advisor"),
    ("option_chain", "Option Chain — Bias, PCR & Trade Signal (NSE)"),
    ("option_short_long", "Option-Short-Long — OI Buildup · Buy/Sell Call/Put"),
    ("india_market_heatmap", "IN-US-Crypto Market Heatmap"),
    ("advance_decline_graph", "Advance Decline (Multi Asset) — Breadth + Options PCR"),
    ("comparative_strength", "Comparative Strength — Relative Long/Short vs Base"),
    ("oil_dollar_bond", "Oil-Dollar-Bond — macro + India sector ETFs (Bank · IT · Mid/Small · …)"),
    ("nse_world_indices", "NSE and World Indices"),
    ("coindcx_24h_volatility", "24Hrs Volatile Crypto"),
    ("quick_analyzer", "Quick Analyzer (India · US · Crypto)"),
]

_MARKET_PULSE_SECTIONS: list[tuple[str, str]] = [
    ("tomorrow_outlook", "Tomorrow's Market Outlook"),
    ("intelligence", "News Scanner & Market Intelligence"),
    ("nifty_breadth", "Nifty Index Breadth"),
    ("nifty_monthly", "Nifty 1-Month Performance"),
    ("nifty_movers", "Nifty Gainers & Losers"),
    ("gainers_losers", "Gainers & Losers (India multi-TF)"),
    ("stock_rotation", "Stock Price Rotation"),
    ("commodity_screener", "Commodity Screener (Nifty)"),
    ("accurate_strategy", "Accurate Strategy — OB + FVG + S/R"),
    ("pump_dump_breakout", "Pump/Dump Breakout"),
    ("big_whale_pump_dump", "Big Whale Pump & Dump"),
    ("sector_rotation", "Sector Rotation (HTF)"),
    ("sector_rotation_intraday", "Sector Rotation (Intraday)"),
    ("sector_rotation_us", "Sector Rotation — US (HTF)"),
    ("sector_rotation_us_intraday", "Sector Rotation — US (Intraday)"),
    ("sector_rotation_crypto", "Sector Rotation — Crypto (HTF)"),
    ("sector_rotation_crypto_intraday", "Sector Rotation — Crypto (Intraday)"),
    ("stock_rotation_us", "Stock Price Rotation — US"),
    ("stock_rotation_crypto", "Stock Price Rotation — Crypto"),
    ("opposite_hedge", "Opposite Hedge-MTF"),
    ("mtf_bias", "MTF Intraday Bias"),
    ("mtf_bias_crypto", "MTF Intraday Bias — Crypto"),
    ("week52", "52-Week High & Low"),
    ("heatmap", "Live Heatmap (India)"),
]

_OPTIONS_SECTIONS: list[tuple[str, str]] = [
    ("double_calendar", "Double Calendar — Theta-Positive Income Spread"),
    ("delta_neutral", "Delta Neutral — Iron Condor / Iron Fly"),
    ("gokul_chhabra", "Gokul Chhabra — 3m VWAP · VWMA · SuperTrend ITM"),
]

_STRATEGY_LAB_SECTIONS: list[tuple[str, str]] = [
    ("builder", "Strategy Builder & Tester"),
    ("multi_combo", "Multi-Combo Scanner"),
    ("screener", "Advanced Screener"),
    ("presets", "Strategy Encyclopedia (Presets)"),
]

_STATIC_GROUPS: list[tuple[str, str, str, list[tuple[str, str]]]] = [
    ("etf", "ETF", "etf", [("stf_shop", "ETF Shop 4.0 — 20 DMA · dynamic SIP · FIFO")]),
    (
        "screen",
        "Screen & Scan",
        "screen",
        [
            ("screener", "Advanced Screener"),
            ("gap_scanner", "Gap Trading Scanner"),
            ("rule_scanner", "Rule Scanner (Scalping / Intraday / Swing)"),
        ],
    ),
    ("seasonality", "Seasonality", "seasonality", [("seasonality", "Seasonality Analyzer")]),
    (
        "demo",
        "Demo",
        "demo",
        [
            ("demo_india", "Demo Trading — India (Groww)"),
            ("demo_crypto", "Demo Trading — Crypto (CoinDCX)"),
        ],
    ),
    ("alerts", "Alerts", "alerts", [("alerts", "Strategy Alert Monitors")]),
]


def _item(prefix: str, sid: str, label: str, *, runnable: bool | None = None) -> dict[str, Any]:
    run = bool(runnable) if runnable is not None else prefix in RUNNABLE_PREFIXES
    return {
        "id": f"{prefix}:{sid}",
        "raw_id": sid,
        "label": label,
        "runnable": run,
        "prefix": prefix,
    }


def _group(
    gid: str,
    label: str,
    *,
    subgroups: list[dict[str, Any]] | None = None,
    items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": gid,
        "label": label,
        "subgroups": subgroups or [],
        "items": items or [],
    }


def build_schedule_catalog() -> dict[str, Any]:
    """Full Alerts Setup catalog — Scanner + hubs + TA + CC/MP/Options/…"""
    groups: list[dict[str, Any]] = []

    # Scanner (runnable) — first so existing UX stays familiar
    scanner_subs = []
    for cat in list_scanner_categories():
        scanner_subs.append({
            "id": cat["id"],
            "label": cat["label"],
            "items": [
                _item("scanner", s["id"], s.get("name") or s["id"], runnable=True)
                for s in cat.get("strategies") or []
            ],
        })
    groups.append(_group("scanner", "Scanner — Scalping / Intraday / Swing", subgroups=scanner_subs))

    # Trading Hubs (runnable)
    hub_payload = list_hubs_payload()
    hub_subs = []
    for hub in hub_payload.get("hubs") or []:
        hub_subs.append({
            "id": hub["id"],
            "label": hub["label"],
            "items": [
                _item("hub", s["id"], s["label"], runnable=True)
                for s in hub.get("sections") or []
            ],
        })
    groups.append(_group("trading_hubs", "Trading Hubs", subgroups=hub_subs))

    # Technical Analysis (runnable)
    core = TA_SCREENERS[:3]
    rest = TA_SCREENERS[3:]
    groups.append(_group(
        "technical_analysis",
        "Technical Analysis",
        subgroups=[
            {
                "id": "core",
                "label": "Core TA",
                "items": [_item("ta", s["id"], s["label"], runnable=True) for s in core],
            },
            {
                "id": "screeners",
                "label": "Screeners",
                "items": [_item("ta", s["id"], s["label"], runnable=True) for s in rest],
            },
        ],
    ))

    # Command Center / Market Pulse / Options / Strategy Lab (catalog only for now)
    groups.append(_group(
        "command_center",
        "Command Center",
        items=[_item("cc", sid, label, runnable=False) for sid, label in _COMMAND_CENTER_SECTIONS],
    ))
    groups.append(_group(
        "market_pulse",
        "Market Pulse",
        items=[_item("mp", sid, label, runnable=False) for sid, label in _MARKET_PULSE_SECTIONS],
    ))
    groups.append(_group(
        "options",
        "Options",
        items=[_item("options", sid, label, runnable=False) for sid, label in _OPTIONS_SECTIONS],
    ))
    groups.append(_group(
        "strategy_lab",
        "Strategy Lab",
        items=[_item("lab", sid, label, runnable=False) for sid, label in _STRATEGY_LAB_SECTIONS],
    ))

    for gid, label, prefix, pairs in _STATIC_GROUPS:
        groups.append(_group(
            gid,
            label,
            items=[_item(prefix, sid, title, runnable=False) for sid, title in pairs],
        ))

    # Count helpers
    all_items: list[dict[str, Any]] = []
    for g in groups:
        all_items.extend(g.get("items") or [])
        for sg in g.get("subgroups") or []:
            all_items.extend(sg.get("items") or [])

    return {
        "groups": groups,
        "count": len(all_items),
        "runnable_count": sum(1 for i in all_items if i.get("runnable")),
        "runnable_prefixes": sorted(RUNNABLE_PREFIXES),
        "hub_meta": {k: v.get("label") for k, v in HUB_META.items()},
        "section_count_by_hub": {
            hub: sum(1 for s in HUB_SECTIONS if s["hub"] == hub) for hub in HUB_META
        },
    }


def parse_strategy_ref(raw: str) -> tuple[str, str]:
    """Return (prefix, id). Bare scanner ids → ('scanner', id)."""
    s = (raw or "").strip()
    if not s:
        return ("", "")
    if ":" in s:
        prefix, _, rest = s.partition(":")
        return (prefix.strip().lower(), rest.strip())
    return ("scanner", s)
