"""
option_chain_combine.py
--------------------------
Combiner used across Command Center sections that suggest a directional trade
for Groww (India) tickers: a section's own technical direction + confidence is
combined with option_chain_engine's PCR/max-pain/OI-based BULLISH/NEUTRAL/BEARISH
bias for the same ticker's nearest-expiry NSE option chain — confidence is
boosted when they agree, reduced when they conflict, and a technical call
downgraded to WAIT if the conflict drags confidence below a floor. India/Groww
only, and only meaningful for tickers with listed F&O contracts.
"""

from __future__ import annotations

from typing import Any

from app.market_pulse.option_chain_engine import classify_option_chain_signal, fetch_option_chain

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


def combine_with_option_chain(
    ticker: str, direction: Any, confidence: float, *, groww_token: str = "",
) -> dict[str, Any]:
    """Fetch the option chain for `ticker` and combine with a technical verdict's
    direction + confidence (0-100). `direction` may be any of the LONG/SHORT/WAIT-ish
    strings used across the app's engines (BUY/SELL, BULLISH/BEARISH, NEUTRAL, etc.) —
    normalized internally to LONG/SHORT/WAIT."""
    tech_dir = _normalize_direction(direction)
    chain = fetch_option_chain(ticker, False, groww_token)
    if not chain:
        return {
            "available": False,
            "error": "Could not fetch option chain (no listed F&O contracts, or NSE is rate-limiting).",
            "combined_direction": tech_dir, "combined_confidence_pct": confidence,
        }

    signal = classify_option_chain_signal(chain)
    oc_bias = signal["bias"]
    oc_confidence = signal["confidence_pct"]
    oc_dir = "LONG" if oc_bias == "BULLISH" else "SHORT" if oc_bias == "BEARISH" else "WAIT"

    agree = oc_dir != "WAIT" and oc_dir == tech_dir
    conflict = oc_dir != "WAIT" and tech_dir != "WAIT" and oc_dir != tech_dir

    combined_direction = tech_dir
    if agree:
        boost = min(_AGREE_BOOST_CAP, max(0.0, (oc_confidence - 50.0) * 0.3 + 6.0))
        combined_confidence = min(96.0, confidence + boost)
        note = f"✅ Option chain agrees ({oc_bias}, {oc_confidence:.0f}% confidence, PCR {chain.get('pcr_oi', 0):.2f}) — combined confidence boosted."
    elif conflict:
        combined_confidence = max(5.0, confidence - _CONFLICT_PENALTY)
        note = f"⚠️ Option chain disagrees ({oc_bias}, {oc_confidence:.0f}% confidence, PCR {chain.get('pcr_oi', 0):.2f}) — combined confidence reduced."
        if combined_confidence < _DOWNGRADE_FLOOR:
            combined_direction = "WAIT"
            note += " Technical call downgraded to WAIT."
    else:
        combined_confidence = confidence
        note = f"➖ Option chain neutral ({oc_bias}) — no material adjustment."

    return {
        "available": True,
        "option_chain_bias": oc_bias,
        "option_chain_trade_signal": signal["trade_signal"],
        "option_chain_confidence_pct": oc_confidence,
        "pcr_oi": chain.get("pcr_oi"),
        "max_pain": chain.get("max_pain"),
        "support": signal.get("support"),
        "resistance": signal.get("resistance"),
        "agree": agree,
        "conflict": conflict,
        "combined_direction": combined_direction,
        "combined_confidence_pct": round(combined_confidence, 1),
        "note": note,
        "option_chain_result": chain,
        "option_chain_signal": signal,
    }
