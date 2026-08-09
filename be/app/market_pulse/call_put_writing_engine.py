"""
call_put_writing_engine.py
--------------------------
Options → Call Put Writing — desk read of who is writing Calls vs Puts.

Inspired by weekly index outlooks that frame resistance from aggressive Call
writing (OI walls at key strikes), support from Put writing, short-covering
risk if Call walls break, and the contrast between institutional-style
bearish hedges (buy Puts / sell Calls) vs retail Put selling.

Computes from live India F&O option chain:
  - Top Call / Put OI walls (resistance / support)
  - Fresh writing (ΔOI) tilt Call vs Put
  - PCR(OI), Max Pain, OI buildup quadrant
  - Short-covering rally risk if spot approaches / breaks Call wall
  - Cash FII/DII context (participant OI FII/Pro/Client is not auto-fetched)

Research / education only — not financial advice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.market_pulse.option_chain_engine import (
    INDEX_CHOICES,
    classify_option_chain_signal,
    fetch_option_chain,
)
from app.market_pulse.option_short_long_engine import (
    classify_oi_buildup,
    fetch_fii_dii_sentiment,
)
from app.market_pulse.news_scanner import analyze_options_sentiment

logger = logging.getLogger(__name__)

# No durable public URL was found in-repo for "Stock Market Outlook for Next Week: 10 to 14 Aug".
VIDEO_TITLE = "Stock Market Outlook for Next Week (Call / Put Writing · OI walls)"

CALL_PUT_WRITING_AI_SYSTEM = (
    "You are an Options Call/Put Writing desk analyst. Explain resistance from Call OI walls, "
    "support from Put writing, fresh ΔOI tilt, PCR, max pain, and short-covering risk if Call "
    "walls break. Be clear that FII/Pro/Client participant OI is not auto-fetched unless provided. "
    "Research/education only — not financial advice."
)

GUIDE_MARKDOWN = f"""
### Options — Call Put Writing
Desk-style read of **who is writing what** on the India F&O option chain.

| Concept | How we read it |
|---------|----------------|
| **Call writing wall** | Highest Call OI / fresh Call ΔOI overhead → near-term **resistance** (hard to cross while writers defend) |
| **Put writing floor** | Highest Put OI / fresh Put ΔOI below → near-term **support** |
| **PCR (OI)** | High PCR → more Put writing (often bullish undertone); low PCR → Call writing dominance (bearish / ceiling) |
| **Max Pain** | Expiry gravitational pull for writers |
| **OI buildup** | Long/Short Buildup · Covering · Unwinding from price × OI change |
| **Short covering risk** | If spot **breaks above** the Call wall, Call writers may scramble → squeeze / covering rally |

**Video framing** ({VIDEO_TITLE}): heavy Call writing at a strike (e.g. 24,600) can pin resistance;
Puts written by retail can sit opposite institutional-style Put buys / Call sells. This desk uses
chain OI (not a substitute for NSE `fao_participant_oi` FII/Pro/Client cuts).

Always pair with price structure. Research / education only.
"""


@dataclass
class CallPutWritingConfig:
    top_n_strikes: int = 8
    wall_break_tol_pct: float = 0.15  # how close to Call wall counts as "testing"
    short_cover_break_pct: float = 0.05  # spot above wall by this % → covering risk


def _sum_fresh(rows: list[dict[str, Any]], key: str) -> float:
    total = 0.0
    for r in rows or []:
        try:
            v = float(r.get(key) or 0)
        except (TypeError, ValueError):
            v = 0.0
        if v > 0:
            total += v
    return total


def _writing_tilt(chain: dict[str, Any]) -> dict[str, Any]:
    top_call_chg = chain.get("top_call_chg_oi") or []
    top_put_chg = chain.get("top_put_chg_oi") or []
    fresh_call = _sum_fresh(top_call_chg, "ce_chg_oi")
    fresh_put = _sum_fresh(top_put_chg, "pe_chg_oi")
    if fresh_call <= 0 and fresh_put <= 0:
        tilt = "BALANCED"
        bias = "NEUTRAL"
        note = "No meaningful fresh Call/Put writing in top ΔOI strikes."
    elif fresh_call > fresh_put * 1.35:
        tilt = "CALL_WRITING_DOMINANT"
        bias = "BEARISH"
        note = (
            f"Fresh Call writing ({fresh_call:,.0f}) dominates Put writing ({fresh_put:,.0f}) — "
            "writers expect upside to stall under Call walls."
        )
    elif fresh_put > fresh_call * 1.35:
        tilt = "PUT_WRITING_DOMINANT"
        bias = "BULLISH"
        note = (
            f"Fresh Put writing ({fresh_put:,.0f}) dominates Call writing ({fresh_call:,.0f}) — "
            "writers expect downside to hold above Put floors."
        )
    else:
        tilt = "BALANCED"
        bias = "NEUTRAL"
        note = f"Fresh writing roughly balanced — Call {fresh_call:,.0f} vs Put {fresh_put:,.0f}."

    return {
        "fresh_call_writing": round(fresh_call, 0),
        "fresh_put_writing": round(fresh_put, 0),
        "tilt": tilt,
        "bias": bias,
        "note": note,
    }


def _walls(chain: dict[str, Any], cfg: CallPutWritingConfig) -> dict[str, Any]:
    top_call = list(chain.get("top_call_oi") or [])[: cfg.top_n_strikes]
    top_put = list(chain.get("top_put_oi") or [])[: cfg.top_n_strikes]
    call_wall = top_call[0] if top_call else None
    put_floor = top_put[0] if top_put else None
    return {
        "call_resistance_strikes": top_call,
        "put_support_strikes": top_put,
        "primary_call_wall": {
            "strike": call_wall.get("strike") if call_wall else None,
            "ce_oi": call_wall.get("ce_oi") if call_wall else None,
            "ce_chg_oi": call_wall.get("ce_chg_oi") if call_wall else None,
        },
        "primary_put_floor": {
            "strike": put_floor.get("strike") if put_floor else None,
            "pe_oi": put_floor.get("pe_oi") if put_floor else None,
            "pe_chg_oi": put_floor.get("pe_chg_oi") if put_floor else None,
        },
    }


def _short_covering_risk(
    spot: float,
    call_wall_strike: float | None,
    cfg: CallPutWritingConfig,
) -> dict[str, Any]:
    if not call_wall_strike or spot <= 0:
        return {"active": False, "level": None, "note": "No Call wall to evaluate."}
    dist_pct = (call_wall_strike - spot) / spot * 100
    if spot >= call_wall_strike * (1 + cfg.short_cover_break_pct / 100):
        return {
            "active": True,
            "severity": True,
            "level": call_wall_strike,
            "distance_pct": round(dist_pct, 3),
            "note": (
                f"Spot {spot:,.1f} is above Call wall {call_wall_strike:,.0f} — "
                "Call writers may be forced into short covering (squeeze risk toward higher magnets)."
            ),
        }
    if abs(dist_pct) <= cfg.wall_break_tol_pct or (0 < dist_pct <= 0.35):
        return {
            "active": True,
            "threatened": False,
            "level": call_wall_strike,
            "distance_pct": round(dist_pct, 3),
            "note": (
                f"Spot testing Call wall {call_wall_strike:,.0f} ({dist_pct:+.2f}% away) — "
                "crossing this ceiling is hard while Call writing remains heavy; a clean break invites covering."
            ),
        }
    return {
        "active": False,
        "threatened": False,
        "level": call_wall_strike,
        "distance_pct": round(dist_pct, 3),
        "note": f"Spot {dist_pct:+.2f}% from primary Call wall {call_wall_strike:,.0f}.",
    }


def _trade_suggestion(
    *,
    writing: dict[str, Any],
    walls: dict[str, Any],
    covering: dict[str, Any],
    sentiment: dict[str, Any],
    buildup: dict[str, Any] | None,
    spot: float,
) -> dict[str, Any]:
    reasons: list[str] = []
    action = "WAIT"
    conf = 48.0

    wall = walls.get("primary_call_wall") or {}
    floor = walls.get("primary_put_floor") or {}
    if wall.get("strike"):
        reasons.append(f"Primary Call wall (resistance) at {wall['strike']:,.0f} (OI {wall.get('ce_oi') or 0:,.0f})")
    if floor.get("strike"):
        reasons.append(f"Primary Put floor (support) at {floor['strike']:,.0f} (OI {floor.get('pe_oi') or 0:,.0f})")
    reasons.append(writing.get("note") or "")
    if covering.get("note"):
        reasons.append(str(covering["note"]))
    if sentiment.get("verdict"):
        reasons.append(f"Options sentiment: {sentiment.get('verdict')} (score {sentiment.get('score')})")
    if buildup and buildup.get("label"):
        reasons.append(f"OI buildup: {buildup.get('label')} ({buildup.get('bias')})")

    if covering.get("threatened"):
        action = "BUY"
        conf = 66.0
        advice = (
            "Call wall broken — watch short-covering continuation; trail risk tightly; "
            "do not assume writers still hold the ceiling."
        )
    elif writing.get("tilt") == "CALL_WRITING_DOMINANT" and not covering.get("threatened"):
        action = "SELL"
        conf = 62.0
        advice = (
            "Heavy Call writing caps upside near the Call wall — fade strength into the wall / stay light on breakouts "
            "until OI unwinds or wall breaks."
        )
    elif writing.get("tilt") == "PUT_WRITING_DOMINANT":
        action = "BUY"
        conf = 60.0
        advice = (
            "Put writing dominates — dips toward the Put floor are more likely to be defended; "
            "buy weakness only with structure confirmation."
        )
    else:
        advice = "Writing balanced / unclear — wait for wall test or fresh ΔOI tilt before committing."

    # Soften with sentiment conflict
    sv = str(sentiment.get("verdict") or "").upper()
    if action == "BUY" and "BEARISH" in sv:
        conf -= 8
        reasons.append("Sentiment conflicts with BUY lean — confidence cut")
    if action == "SELL" and "BULLISH" in sv:
        conf -= 8
        reasons.append("Sentiment conflicts with SELL lean — confidence cut")

    sl = tp = None
    if action == "SELL" and wall.get("strike") and spot > 0:
        # Fade into wall: invalidation above wall, target toward put floor / mid
        sl_pct = max(0.25, (float(wall["strike"]) * 1.002 - spot) / spot * 100)
        tgt = float(floor["strike"]) if floor.get("strike") else spot * 0.992
        tp_pct = max(0.35, (spot - tgt) / spot * 100)
        sl, tp = round(sl_pct, 2), round(tp_pct, 2)
    elif action == "BUY" and floor.get("strike") and spot > 0:
        sl_pct = max(0.25, (spot - float(floor["strike"]) * 0.998) / spot * 100)
        tgt = float(wall["strike"]) if wall.get("strike") else spot * 1.008
        tp_pct = max(0.35, (tgt - spot) / spot * 100)
        sl, tp = round(sl_pct, 2), round(tp_pct, 2)

    return {
        "action": action,
        "side": "LONG" if action == "BUY" else ("SHORT" if action == "SELL" else "WAIT"),
        "confidence_pct": round(max(35.0, min(85.0, conf)), 1),
        "sl_pct": sl,
        "tp_pct": tp,
        "plain_english": advice,
        "advice": advice,
        "reasons": [r for r in reasons if r],
    }


def analyze_call_put_writing(
    symbol: str,
    *,
    is_index: bool = True,
    groww_token: str = "",
    exchange: str = "NSE",
    cfg: CallPutWritingConfig | None = None,
) -> dict[str, Any]:
    cfg = cfg or CallPutWritingConfig()
    sym = (symbol or "NIFTY").strip().upper()

    chain = fetch_option_chain(sym, is_index=is_index, groww_token=groww_token, exchange=exchange)
    if not chain or chain.get("error"):
        return {
            "symbol": sym,
            "is_index": is_index,
            "error": (chain or {}).get("error") or "Could not fetch option chain",
            "guide": GUIDE_MARKDOWN,
        }

    spot = float(chain.get("underlying") or 0)
    writing = _writing_tilt(chain)
    walls = _walls(chain, cfg)
    call_strike = walls["primary_call_wall"].get("strike")
    covering = _short_covering_risk(spot, float(call_strike) if call_strike else None, cfg)
    sentiment = analyze_options_sentiment(chain)
    chain_signal = classify_option_chain_signal(chain)

    # Price change proxy for buildup: use chain meta if present else 0
    price_chg = float(chain.get("underlying_chg_pct") or chain.get("price_chg_pct") or 0)
    try:
        buildup = classify_oi_buildup(chain, price_chg)
    except Exception:
        logger.debug("OI buildup failed", exc_info=True)
        buildup = None

    try:
        fii_dii = fetch_fii_dii_sentiment()
    except Exception:
        fii_dii = {"available": False, "note": "Cash FII/DII unavailable"}

    trade = _trade_suggestion(
        writing=writing,
        walls=walls,
        covering=covering,
        sentiment=sentiment,
        buildup=buildup if isinstance(buildup, dict) else None,
        spot=spot,
    )

    view = writing["bias"]
    if covering.get("threatened"):
        view = "SHORT_COVERING"
    risk = "HIGH" if covering.get("threatened") or writing["tilt"] == "CALL_WRITING_DOMINANT" else "MODERATE"

    plain = (
        f"{sym} spot {spot:,.1f}. {writing['note']} "
        f"Call wall {call_strike or '—'} · Put floor {walls['primary_put_floor'].get('strike') or '—'}. "
        f"{covering.get('note', '')} "
        f"PCR(OI) {chain.get('pcr_oi')} · Max Pain {chain.get('max_pain')}. "
        "Heavy Call writing can pin resistance until broken — then covering risk rises."
    )

    return {
        "symbol": sym,
        "is_index": is_index,
        "spot": spot,
        "expiry": chain.get("current_expiry") or chain.get("expiry"),
        "pcr_oi": chain.get("pcr_oi"),
        "pcr_vol": chain.get("pcr_vol"),
        "max_pain": chain.get("max_pain"),
        "total_call_oi": chain.get("total_call_oi"),
        "total_put_oi": chain.get("total_put_oi"),
        "writing": writing,
        "walls": walls,
        "short_covering": covering,
        "buildup": buildup,
        "sentiment": sentiment,
        "chain_signal": chain_signal,
        "fii_dii_cash": fii_dii,
        "participant_oi_note": (
            "NSE FII / Pro / Client participant OI (fao_participant_oi) is not auto-fetched in this app. "
            "Interpret Call/Put writing from the option chain; treat any FII/Pro vs retail narrative from "
            "external participant files as manual context only."
        ),
        "top_call_oi": walls["call_resistance_strikes"],
        "top_put_oi": walls["put_support_strikes"],
        "top_call_chg_oi": (chain.get("top_call_chg_oi") or [])[: cfg.top_n_strikes],
        "top_put_chg_oi": (chain.get("top_put_chg_oi") or [])[: cfg.top_n_strikes],
        "strikes": chain.get("strikes") or [],
        "market_view": view,
        "risk_stance": risk,
        "plain_english": plain,
        "trade_suggestion": trade,
        "guide": GUIDE_MARKDOWN,
        "video_title": VIDEO_TITLE,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "disclaimer": "Research / education only — not financial advice.",
        "ai_system_prompt": CALL_PUT_WRITING_AI_SYSTEM,
    }
