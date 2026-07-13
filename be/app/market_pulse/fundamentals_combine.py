"""
fundamentals_combine.py
--------------------------
Combiner used across Command Center / Swing Trading sections that suggest a
directional trade for Groww (India) tickers: a section's own technical
direction + confidence is combined with fundamental_analysis_engine's
BULLISH/NEUTRAL/BEARISH read for the same ticker (screener.in + Dhan.co) —
confidence is boosted when they agree, reduced when they conflict, and a
technical call downgraded to WAIT if the conflict drags confidence below a
floor. India/Groww only, since Fundamental Analysis itself is India-only.
"""

from __future__ import annotations

from typing import Any

from app.market_pulse.fundamental_analysis_engine import analyze_ticker as fa_analyze_ticker

_AGREE_BOOST_CAP = 15.0
_CONFLICT_PENALTY = 15.0
_DOWNGRADE_FLOOR = 50.0

_LONG_TOKENS = ("LONG", "BUY", "BULLISH")
_SHORT_TOKENS = ("SHORT", "SELL", "BEARISH")


def is_groww_india_market(market: str) -> bool:
    """True for the Groww/India equity market string used across tabs."""
    m = (market or "").strip()
    return m == "Groww (India Stocks)" or ("Groww" in m and "India" in m)


def _normalize_direction(raw: Any) -> str:
    if raw is None:
        return "WAIT"
    s = str(raw).upper()
    if any(tok in s for tok in _LONG_TOKENS):
        return "LONG"
    if any(tok in s for tok in _SHORT_TOKENS):
        return "SHORT"
    return "WAIT"


def combine_with_fundamentals(ticker: str, direction: Any, confidence: float) -> dict[str, Any]:
    """Fetch Fundamental Analysis for `ticker` and combine with a technical
    verdict's direction + confidence (0-100). `direction` may be any of the
    LONG/SHORT/WAIT-ish strings used across the app's engines (BUY/SELL,
    BULLISH/BEARISH, etc.) — normalized internally to LONG/SHORT/WAIT."""
    tech_dir = _normalize_direction(direction)
    fa_result = fa_analyze_ticker(ticker)
    if fa_result.get("error"):
        return {
            "available": False, "error": fa_result["error"],
            "combined_direction": tech_dir, "combined_confidence_pct": confidence,
        }

    overall = fa_result.get("overall") or {}
    fa_signal = overall.get("signal", "NEUTRAL")
    fa_confidence = overall.get("confidence_pct", 50.0)
    fa_dir = "LONG" if fa_signal == "BULLISH" else "SHORT" if fa_signal == "BEARISH" else "WAIT"

    agree = fa_dir != "WAIT" and fa_dir == tech_dir
    conflict = fa_dir != "WAIT" and tech_dir != "WAIT" and fa_dir != tech_dir

    combined_direction = tech_dir
    if agree:
        boost = min(_AGREE_BOOST_CAP, max(0.0, (fa_confidence - 50.0) * 0.3 + 6.0))
        combined_confidence = min(96.0, confidence + boost)
        note = f"✅ Fundamentals agree ({fa_signal}, {fa_confidence:.0f}% confidence) — combined confidence boosted."
    elif conflict:
        combined_confidence = max(5.0, confidence - _CONFLICT_PENALTY)
        note = f"⚠️ Fundamentals disagree ({fa_signal}, {fa_confidence:.0f}% confidence) — combined confidence reduced."
        if combined_confidence < _DOWNGRADE_FLOOR:
            combined_direction = "WAIT"
            note += " Technical call downgraded to WAIT."
    else:
        combined_confidence = confidence
        note = f"➖ Fundamentals neutral ({fa_signal}) — no material adjustment."

    return {
        "available": True,
        "fundamental_signal": fa_signal,
        "fundamental_confidence_pct": fa_confidence,
        "fundamental_valuation": (fa_result.get("valuation") or {}).get("label"),
        "agree": agree,
        "conflict": conflict,
        "combined_direction": combined_direction,
        "combined_confidence_pct": round(combined_confidence, 1),
        "note": note,
        "fundamental_result": fa_result,
    }


def rebucket_after_fundamentals(
    combo: dict[str, Any], *, actionable_threshold: float = 62.0,
) -> str:
    """Re-derive a 3-way ACTIONABLE/WATCH/NO_TRADE (or BULLISH/WATCH/BEARISH-style)
    bucket after combining with fundamentals — the original bucket was decided on
    the pre-combination confidence, so a fundamentals conflict/boost can legitimately
    move a result between buckets (e.g. a WATCH promoted to ACTIONABLE once
    fundamentals confirm it, or an ACTIONABLE downgraded to WATCH/NO_TRADE once
    fundamentals meaningfully disagree)."""
    if not combo.get("available"):
        return "WATCH"
    direction = combo.get("combined_direction")
    confidence = combo.get("combined_confidence_pct") or 0.0
    if direction == "WAIT":
        return "NO_TRADE" if combo.get("conflict") else "WATCH"
    return "ACTIONABLE" if confidence >= actionable_threshold else "WATCH"
