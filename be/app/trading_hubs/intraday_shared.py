"""
intraday_shared.py
------------------
Shared trade metrics for Intraday hub sections.
"""

from __future__ import annotations

HOLD_ALPHA_945 = "Same session (9:45 entry · exit by ~15:15 IST)"
HOLD_FIB_945 = "Same session (post-9:45 Fib bias · exit ~15:15 IST)"
HOLD_VWAP_FADE = "VWAP fade · max 60 min time stop · target at VWAP"


def enrich_intra_live(live: dict | None, *, hold_duration: str = "") -> dict:
    if not live:
        return {}
    out = dict(live)
    plan = out.get("trade_plan") or {}
    hold = hold_duration or out.get("hold_duration") or plan.get("holding_period") or HOLD_ALPHA_945
    out["hold_duration"] = hold
    out["confidence_pct"] = out.get("confidence_pct", plan.get("confidence_pct"))
    out["sl_pct"] = out.get("sl_pct", plan.get("stop_loss_pct"))
    out["tp_pct"] = out.get("tp_pct", plan.get("take_profit_pct"))
    if out.get("trade_plan"):
        out["trade_plan"] = {**plan, "holding_period": hold}
    return out


def intra_scan_table_row(live: dict) -> dict:
    live = enrich_intra_live(live)
    return {
        "Conf %": live.get("confidence_pct"),
        "SL %": f"-{live.get('sl_pct')}" if live.get("sl_pct") is not None else "—",
        "TP %": f"+{live.get('tp_pct')}" if live.get("tp_pct") is not None else "—",
        "Hold": (live.get("hold_duration") or "—")[:36],
    }


