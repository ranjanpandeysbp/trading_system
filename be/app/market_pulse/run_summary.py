"""Minimal trade-plan helpers for ticker investigation."""
from __future__ import annotations

def holding_period_for_timeframe(timeframe: str, style: str = "") -> str:
    """Expected holding window tied to chart interval."""
    tf = (timeframe or "1d").lower().strip()
    if "seasonal" in tf:
        return "Hold through the favourable calendar month (≈3–5 weeks)"
    if style == "Scalping" or tf == "1m":
        return "15–45 min (scalp; exit before session close)"
    mapping = {
        "5m": "1–3 hours intraday (exit same session)",
        "15m": "2–6 hours intraday (same-day hold)",
        "30m": "4–12 hours (intraday, max overnight)",
        "1h": "1–5 trading days (short swing)",
        "4h": "3–15 trading days (swing)",
        "1d": "2–6 weeks (position swing)",
        "1w": "1–3 months (long swing)",
    }
    return mapping.get(tf, "1–5 trading days (align with chart TF)")


def default_sl_tp_for_timeframe(timeframe: str) -> tuple[float, float]:
    tf = (timeframe or "1d").lower()
    defaults = {
        "1m": (0.4, 0.8), "5m": (0.7, 1.4), "15m": (1.0, 2.0),
        "30m": (1.3, 2.6), "1h": (1.8, 3.6), "4h": (2.5, 5.0), "1d": (3.5, 7.0),
    }
    return defaults.get(tf, (2.0, 4.0))


def make_trade_plan(
    *,
    direction: str = "",
    timeframe: str = "",
    stop_loss_pct: float | None = None,
    take_profit_pct: float | None = None,
    expected_profit_pct: float | None = None,
    confidence_pct: float | None = None,
    style: str = "",
    exit_rule: str = "",
    max_hold_exit: str = "",
) -> dict:
    holding = holding_period_for_timeframe(timeframe, style)
    dsl, dtp = default_sl_tp_for_timeframe(timeframe)
    sl = float(stop_loss_pct if stop_loss_pct is not None else dsl)
    tp = float(take_profit_pct if take_profit_pct is not None else dtp)
    exp = float(expected_profit_pct if expected_profit_pct is not None else tp)
    if not exit_rule:
        dir_u = (direction or "").upper()
        if dir_u in ("LONG", "BUY"):
            exit_rule = (
                f"Take profit at +{tp:.1f}% (scale 50% at TP1, trail rest). "
                f"Stop loss at -{sl:.1f}%. Exit if thesis breaks (structure/RSI flip)."
            )
        elif dir_u in ("SHORT", "SELL"):
            exit_rule = (
                f"Cover at +{tp:.1f}% profit (lower prices). "
                f"Stop at -{sl:.1f}% (higher prices). Exit on bullish reversal candle."
            )
        else:
            exit_rule = f"Stay flat until directional edge ≥6/10 with defined SL {sl:.1f}% / TP {tp:.1f}%."
    if not max_hold_exit:
        max_hold_exit = f"Close position if TP not reached within {holding.split('(')[0].strip()}."
    return {
        "direction": direction or "—",
        "holding_period": holding,
        "stop_loss_pct": round(sl, 2),
        "take_profit_pct": round(tp, 2),
        "expected_profit_pct": round(exp, 2),
        "confidence_pct": round(confidence_pct, 0) if confidence_pct is not None else None,
        "exit_rule": exit_rule,
        "max_hold_exit": max_hold_exit,
    }


def summarize_seasonality(bt_metrics: dict | None, ticker: str) -> dict:
    """Compact summary for seasonality backtest (Streamlit / API)."""
    m = bt_metrics or {}
    return {
        "ticker": ticker,
        "cagr": m.get("CAGR") or m.get("cagr_pct"),
        "sharpe": m.get("Sharpe") or m.get("sharpe_ratio"),
        "max_drawdown": m.get("Max Drawdown") or m.get("max_drawdown_pct"),
        "total_return": m.get("Total Return") or m.get("total_return_pct"),
    }


def render_run_summary(summary: dict) -> None:
    """No-op outside Streamlit; seasonality tab calls this for UI parity."""
    _ = summary
