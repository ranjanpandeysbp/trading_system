"""
swing_trading_st_shared.py
--------------------------
Shared trade metrics for all ST Swing Trading sections.
"""

from __future__ import annotations

# Strategy-specific expected hold windows
HOLD_CAPITULATION = "3–8 trading days (capitulation bounce)"
HOLD_CONTINUATION = "2–6 weeks (breakout swing)"
HOLD_MTF_MSS = "Same session – 2 days (15m MSS)"
HOLD_MTF_WATCH = "1–2 sessions (await 15m MSS)"
HOLD_SUPERTREND_SWING = "5–15 trading days (SMA trail exit)"
HOLD_SUPERTREND_PYRAMID = "4–12 weeks (structural SuperTrend)"
HOLD_KISS_1H = "Up to 15 trading days (1h KISS swing)"
HOLD_KISS_4H = "2–8 weeks (4h structural KISS)"
HOLD_HA_EMA_5M = "Same session (2–6 hrs intraday)"
HOLD_HA_EMA_15M = "Same session – 1 day (intraday)"


def enrich_st_live(live: dict | None, *, hold_duration: str = "") -> dict:
    """Ensure live payload exposes SL%, TP%, confidence%, and hold duration."""
    if not live:
        return {}
    out = dict(live)
    plan = out.get("trade_plan") or {}
    hold = hold_duration or out.get("hold_duration") or plan.get("holding_period") or "—"
    out["hold_duration"] = hold
    out["confidence_pct"] = out.get("confidence_pct", plan.get("confidence_pct"))
    out["sl_pct"] = out.get("sl_pct", plan.get("stop_loss_pct"))
    out["tp_pct"] = out.get("tp_pct", plan.get("take_profit_pct"))
    if out.get("trade_plan"):
        out["trade_plan"] = {**plan, "holding_period": hold}
    return out


def st_scan_table_row(live: dict) -> dict:
    """Standard scan table columns for all ST sections."""
    live = enrich_st_live(live)
    return {
        "Conf %": live.get("confidence_pct"),
        "SL %": f"-{live.get('sl_pct')}" if live.get("sl_pct") is not None else "—",
        "TP %": f"+{live.get('tp_pct')}" if live.get("tp_pct") is not None else "—",
        "Hold": (live.get("hold_duration") or "—")[:36],
    }


