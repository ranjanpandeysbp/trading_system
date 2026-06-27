"""Save individual Multi-Combo scan rows for alert monitoring."""

from __future__ import annotations

import json
import re

from app.market_pulse.database import (
    get_custom_strategies_by_mobile,
    get_use_later_strategies_by_mobile,
    save_combo_outcome,
)
from app.market_pulse.presets import get_presets_for_market


def resolve_strategy_config(mobile: str, market: str, strategy_name: str) -> dict | None:
    """Resolve indicators + rules from preset or user strategy name."""
    combined = dict(get_presets_for_market(market))
    target = "Groww" if "Groww" in market else "CoinDCX"

    for s in get_custom_strategies_by_mobile(mobile):
        m = s["market"]
        if m == target or m == "Both":
            key = f"🤖 [CUSTOM] {s['name']}"
            combined[key] = {
                "indicators": json.loads(s["indicators"]),
                "entry_rules": json.loads(s["entry_rules"]),
                "exit_rules": json.loads(s["exit_rules"]),
            }

    for s in get_use_later_strategies_by_mobile(mobile):
        m = s["market"]
        if m == target or m == "Both":
            key = f"⏳ [USE LATER] {s['name']}"
            combined[key] = {
                "indicators": json.loads(s["indicators"]),
                "entry_rules": json.loads(s["entry_rules"]),
                "exit_rules": json.loads(s["exit_rules"]),
            }

    preset = combined.get(strategy_name)
    if not preset:
        return None
    return {
        "indicators": preset["indicators"],
        "entry_rules": preset["entry_rules"],
        "exit_rules": preset.get("exit_rules", []),
    }


def _parse_json_field(val, default=None):
    if default is None:
        default = []
    if val is None:
        return default
    if isinstance(val, (list, dict)):
        return val
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return default


def strategy_config_from_row(row: dict, mobile: str, market: str) -> dict | None:
    """Extract indicators + rules from a scan row or saved outcome record."""
    if row.get("_indicators"):
        return {
            "indicators": row["_indicators"],
            "entry_rules": row["_entry_rules"],
            "exit_rules": row.get("_exit_rules", []),
        }

    if row.get("indicators"):
        return {
            "indicators": _parse_json_field(row["indicators"]),
            "entry_rules": _parse_json_field(row.get("entry_rules")),
            "exit_rules": _parse_json_field(row.get("exit_rules")),
        }

    strat = row.get("Strategy") or row.get("strategy_name", "")
    cfg = resolve_strategy_config(mobile, market, strat)
    if not cfg and strat == "📐 Current Custom Strategy":
        cfg = {
            "indicators": st.session_state.get("indicators", []),
            "entry_rules": st.session_state.get("entry_rules", []),
            "exit_rules": st.session_state.get("exit_rules", []),
        }
    return cfg


def combo_outcome_label(record: dict) -> str:
    ticker = record.get("ticker") or record.get("Ticker", "?")
    tf = record.get("timeframe") or record.get("Timeframe", "?")
    strat = (record.get("strategy_name") or record.get("Strategy") or "?")[:45]
    ret = record.get("return_pct")
    if ret is None:
        ret = record.get("Return %")
    ret_s = f"{float(ret):.1f}%" if ret is not None else "—"
    return f"{ticker} | {tf} | {strat} | Ret {ret_s}"


def row_to_outcome_dict(row: dict) -> dict:
    return {
        "Ticker": row.get("Ticker") or row.get("ticker"),
        "Timeframe": row.get("Timeframe") or row.get("timeframe"),
        "Strategy": row.get("Strategy") or row.get("strategy_name"),
        "Return %": row.get("Return %", row.get("return_pct")),
        "Sharpe": row.get("Sharpe", row.get("sharpe")),
        "Win Rate %": row.get("Win Rate %", row.get("win_rate_pct")),
        "Trades": row.get("Trades", row.get("trades")),
    }


def save_scan_row_outcome(mobile: str, market: str, row: dict) -> tuple[bool, str]:
    """Persist one scan row with full strategy config for Alerts."""
    cfg = strategy_config_from_row(row, mobile, market)
    if not cfg or not cfg.get("indicators"):
        return False, "Could not resolve strategy rules for this row."

    ticker = (row.get("Ticker") or row.get("ticker") or "").strip().upper()
    timeframe = row.get("Timeframe") or row.get("timeframe") or ""
    strategy_name = row.get("Strategy") or row.get("strategy_name") or ""

    safe_strat = re.sub(r"[^a-zA-Z0-9_]", "_", strategy_name)[:24]
    name = f"{ticker}_{timeframe}_{safe_strat}"

    metrics = row_to_outcome_dict(row)
    ok = save_combo_outcome(
        mobile_number=mobile,
        name=name,
        market=market,
        ticker=ticker,
        timeframe=timeframe,
        strategy_name=strategy_name,
        indicators=cfg["indicators"],
        entry_rules=cfg["entry_rules"],
        exit_rules=cfg.get("exit_rules", []),
        return_pct=metrics.get("Return %"),
        sharpe=metrics.get("Sharpe"),
        win_rate_pct=metrics.get("Win Rate %"),
        trades=int(metrics.get("Trades") or 0),
        outcome_json=metrics,
    )
    if ok:
        return True, f"Saved **{ticker}** `{timeframe}` for Alerts"
    return False, "Failed to save (database error)."
