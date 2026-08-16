"""
profitable_engine.py
--------------------
Profitable — Overnight Options Buy-Stop (reactive CE/PE).

Source interview: https://www.youtube.com/watch?v=w_8cVFZ1iZE

Market DNA (foundation — not curve-fit fluff):
  Over a ~10y Nifty path, most of the net point gain came from **overnight**
  gaps; buying the index only in the cash session (09:15→15:15) was a net
  *loser*. Money is made by **reacting**, not anticipating. Plan both sides
  before the open; never "today will only go up".

Rules (as taught):
  1. At **09:20 IST**, scan the option chain for **CE and PE** premiums in
     **₹50–₹75** (midpoint preference **₹62.5**). Outside that band → skip
     that side for the day.
  2. Do **not** buy at the mark. Place a **buy-stop at +50%** of the 09:20
     mark (₹50 → trigger ₹75). Trigger can fire any time after 09:20.
  3. Once filled, **stop-loss = 50% below entry premium** (buy @75 → SL @37.5).
  4. Both sides are independent — CE can fill then SL, then PE can fill later
     (and vice versa). Worst case both fill and both SL on a "rickshaw-man"
     day — rare but expected in long samples.
  5. Intent is **overnight carry** of the option (capture overnight DNA),
     not scalp 10–20 points of premium.

Live scan notes:
  Exact historical 09:20 option ticks are not always available. This engine
  uses the **live NSE chain premium** as today's mark proxy, labels whether
  we are before/after 09:20 IST, and computes buy-stop / SL from that mark.
  Prefer running the scan near/after 09:20 for mark fidelity.

Universe: Nifty 50 · Bank Nifty · Midcap Nifty (robustness across indices).

Research / education only — not financial advice. Options buying is hard.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time as dtime
from typing import Any
from zoneinfo import ZoneInfo

from app.market_pulse.option_chain_engine import INDEX_CHOICES, fetch_option_chain

logger = logging.getLogger(__name__)

YOUTUBE_PROFITABLE_URL = "https://www.youtube.com/watch?v=w_8cVFZ1iZE"
IST = ZoneInfo("Asia/Kolkata")

STRATEGY_NAME = "Profitable — Overnight Options Buy-Stop"

INDEX_NAMES = ["Nifty 50", "Bank Nifty", "Midcap Nifty"]
_INDEX_TO_OPTION_SYMBOL = {
    "Nifty 50": "NIFTY",
    "Bank Nifty": "BANKNIFTY",
    "Midcap Nifty": "MIDCPNIFTY",
}


@dataclass
class ProfitableConfig:
    mark_time: str = "09:20"  # IST — when the day's trading strike is chosen
    premium_min: float = 50.0
    premium_max: float = 75.0
    premium_mid: float = 62.5  # prefer nearest to this
    trigger_pct: float = 50.0  # buy-stop = mark * (1 + trigger_pct/100)
    stop_pct: float = 50.0  # SL = entry * (1 - stop_pct/100)
    hold_overnight: bool = True


def _parse_hhmm(s: str) -> dtime:
    return datetime.strptime(s.strip(), "%H:%M").time()


def _now_ist() -> datetime:
    return datetime.now(tz=IST)


def _select_side_candidate(
    strikes: list[dict[str, Any]],
    *,
    side: str,
    cfg: ProfitableConfig,
) -> dict[str, Any] | None:
    """Pick CE or PE for the Profitable desk.

    Prefer live premium in [min, max] (arm buy-stop). Also accept legs whose
    implied 09:20 mark (live / 1.5) sits in-band and live already ≥ buy-stop
    — so a midday re-scan can still report TRIGGERED.
    """
    key = "ce_ltp" if side == "CE" else "pe_ltp"
    waiting_pool: list[dict[str, Any]] = []
    triggered_pool: list[dict[str, Any]] = []
    trig_mult = 1.0 + cfg.trigger_pct / 100.0

    for row in strikes:
        strike = row.get("strike")
        ltp = row.get(key)
        try:
            premium = float(ltp) if ltp is not None else 0.0
            strike_f = float(strike) if strike is not None else None
        except (TypeError, ValueError):
            continue
        if strike_f is None or premium <= 0:
            continue

        base = {
            "option_type": side,
            "strike": strike_f,
            "oi": row.get(f"{'ce' if side == 'CE' else 'pe'}_oi"),
            "iv": row.get(f"{'ce' if side == 'CE' else 'pe'}_iv"),
            "live_premium": round(premium, 2),
        }

        if cfg.premium_min <= premium <= cfg.premium_max:
            waiting_pool.append({
                **base,
                "mark_premium": round(premium, 2),
                "distance_to_mid": abs(premium - cfg.premium_mid),
                "implied_from_trigger": False,
            })
            continue

        # Reverse: if already +50% from an in-band mark, treat as triggered
        implied_mark = premium / trig_mult
        if cfg.premium_min <= implied_mark <= cfg.premium_max:
            triggered_pool.append({
                **base,
                "mark_premium": round(implied_mark, 2),
                "distance_to_mid": abs(implied_mark - cfg.premium_mid),
                "implied_from_trigger": True,
            })

    def _finish(c: dict[str, Any]) -> dict[str, Any]:
        mark = float(c["mark_premium"])
        buy_stop = round(mark * trig_mult, 2)
        planned_sl = round(buy_stop * (1.0 - cfg.stop_pct / 100.0), 2)
        c.update({
            "buy_stop": buy_stop,
            "planned_stop": planned_sl,
            "trigger_pct": cfg.trigger_pct,
            "stop_pct": cfg.stop_pct,
        })
        return c

    if waiting_pool:
        best = min(waiting_pool, key=lambda c: (c["distance_to_mid"], -float(c.get("oi") or 0)))
        return _finish(best)
    if triggered_pool:
        best = min(triggered_pool, key=lambda c: (c["distance_to_mid"], -float(c.get("oi") or 0)))
        return _finish(best)
    return None


def _leg_status(leg: dict[str, Any], live_premium: float | None) -> dict[str, Any]:
    """WAITING / TRIGGERED / NO_CANDIDATE based on live premium vs buy-stop."""
    if not leg:
        return {"status": "NO_CANDIDATE", "take_trade": False}
    buy_stop = float(leg["buy_stop"])
    mark = float(leg["mark_premium"])
    live = float(live_premium) if live_premium is not None else float(leg.get("live_premium") or mark)
    triggered = live + 1e-9 >= buy_stop or bool(leg.get("implied_from_trigger"))
    entry = buy_stop if triggered else None
    stop = round(entry * (1.0 - float(leg["stop_pct"]) / 100.0), 2) if entry else leg["planned_stop"]
    return {
        "status": "TRIGGERED" if triggered else "WAITING_BUY_STOP",
        "take_trade": triggered,
        "live_premium": round(live, 2),
        "entry_premium": entry,
        "stop_premium": stop,
        "r_multiple_to_stop": -0.5 if triggered else None,
        "action": "BUY" if triggered else "WAIT",
        "side": "LONG",
    }


def analyze_profitable(
    index_name: str,
    *,
    cfg: ProfitableConfig | None = None,
    groww_token: str = "",
) -> dict[str, Any]:
    cfg = cfg or ProfitableConfig()
    symbol = _INDEX_TO_OPTION_SYMBOL.get(index_name, "")
    out: dict[str, Any] = {
        "ticker": index_name,
        "option_symbol": symbol,
        "strategy": STRATEGY_NAME,
        "youtube": YOUTUBE_PROFITABLE_URL,
        "hold_overnight": cfg.hold_overnight,
        "mark_time_ist": cfg.mark_time,
        "premium_band": [cfg.premium_min, cfg.premium_max],
        "premium_mid": cfg.premium_mid,
        "trigger_pct": cfg.trigger_pct,
        "stop_pct": cfg.stop_pct,
        "ce": None,
        "pe": None,
        "live": {
            "take_trade": False,
            "verdict": "WAIT",
            "reasons": [],
            "phase": "pre_mark",
        },
        "trade_suggestion": None,
        "legs": [],
    }

    if not symbol or symbol not in INDEX_CHOICES:
        out["error"] = f"Unsupported index for NSE chain: {index_name}"
        out["live"]["reasons"] = [out["error"]]
        return out

    now = _now_ist()
    mark_t = _parse_hhmm(cfg.mark_time)
    after_mark = now.time() >= mark_t
    out["asof_ist"] = now.strftime("%Y-%m-%d %H:%M IST")
    out["after_mark_time"] = after_mark
    out["live"]["phase"] = "post_mark" if after_mark else "pre_mark_proxy"

    try:
        chain = fetch_option_chain(symbol, True, groww_token)
    except Exception as exc:
        logger.exception("Profitable chain fetch failed for %s", symbol)
        out["error"] = f"Option chain failed: {exc}"
        out["live"]["reasons"] = [out["error"]]
        return out

    if not chain:
        out["error"] = "Empty option chain"
        out["live"]["reasons"] = [out["error"]]
        return out

    strikes = list(chain.get("strikes") or [])
    spot = chain.get("spot") or chain.get("underlying_value") or chain.get("ltp")
    try:
        out["spot"] = float(spot) if spot is not None else None
    except (TypeError, ValueError):
        out["spot"] = None
    out["expiry"] = chain.get("current_expiry")
    out["chain_source"] = chain.get("source")

    ce = _select_side_candidate(strikes, side="CE", cfg=cfg)
    pe = _select_side_candidate(strikes, side="PE", cfg=cfg)
    out["ce"] = ce
    out["pe"] = pe

    reasons: list[str] = [
        "Foundation: overnight DNA — react with buy-stops on both CE & PE; do not anticipate direction.",
        f"Premium band ₹{cfg.premium_min:.0f}–₹{cfg.premium_max:.0f} (prefer ~₹{cfg.premium_mid:.1f}) at mark {cfg.mark_time} IST.",
        f"Buy-stop = mark +{cfg.trigger_pct:.0f}% · SL = entry −{cfg.stop_pct:.0f}% · prefer overnight hold.",
    ]
    if not after_mark:
        reasons.append(
            f"Before {cfg.mark_time} IST — using live premiums as mark proxy; re-scan after mark for fidelity."
        )

    legs_out: list[dict[str, Any]] = []
    actionable: list[dict[str, Any]] = []

    for leg in (ce, pe):
        if not leg:
            continue
        st = _leg_status(leg, leg.get("live_premium") or leg.get("mark_premium"))
        packed = {**leg, **st, "expiry": out["expiry"]}
        legs_out.append(packed)
        side = leg["option_type"]
        if st["status"] == "WAITING_BUY_STOP":
            reasons.append(
                f"{side} {leg['strike']:.0f} mark ₹{leg['mark_premium']} → buy-stop ₹{leg['buy_stop']} "
                f"(SL ₹{leg['planned_stop']} if filled). Waiting for +{cfg.trigger_pct:.0f}% conviction."
            )
        elif st["status"] == "TRIGGERED":
            reasons.append(
                f"{side} {leg['strike']:.0f} live ₹{st['live_premium']} ≥ buy-stop ₹{leg['buy_stop']} — "
                f"ENTRY. SL ₹{st['stop_premium']}. Prefer overnight carry."
            )
            actionable.append(packed)

    if ce is None:
        reasons.append(f"No CE in ₹{cfg.premium_min:.0f}–₹{cfg.premium_max:.0f} band — skip calls today.")
    if pe is None:
        reasons.append(f"No PE in ₹{cfg.premium_min:.0f}–₹{cfg.premium_max:.0f} band — skip puts today.")

    out["legs"] = legs_out
    take = bool(actionable)
    out["live"] = {
        "take_trade": take,
        "verdict": "BUY" if take else "WAIT",
        "reasons": reasons,
        "phase": out["live"]["phase"],
        "actionable_count": len(actionable),
        "candidate_count": len(legs_out),
    }

    if actionable:
        # Primary suggestion = highest live premium stretch past stop (most conviction)
        best = max(actionable, key=lambda x: float(x.get("live_premium") or 0))
        out["trade_suggestion"] = {
            "action": "BUY",
            "action_label": f"BUY {best['option_type']}",
            "side": "LONG",
            "option_type": best["option_type"],
            "strike": best["strike"],
            "expiry": best.get("expiry"),
            "entry_premium": best.get("entry_premium") or best.get("buy_stop"),
            "stop_premium": best.get("stop_premium"),
            "confidence_pct": 62.0,
            "plain_english": (
                f"Reactive overnight desk: {best['option_type']} {best['strike']:.0f} triggered "
                f"(+{cfg.trigger_pct:.0f}% from mark). SL {cfg.stop_pct:.0f}% below entry. "
                "Do not invent direction — follow the filled side; other side may still arm."
            ),
        }
        out["live"]["entry_price"] = out["trade_suggestion"]["entry_premium"]
        out["live"]["stop_price"] = out["trade_suggestion"]["stop_premium"]
        out["live"]["confidence_pct"] = 62.0
    elif legs_out:
        # Waiting — show first waiting leg as plan
        w = legs_out[0]
        out["trade_suggestion"] = {
            "action": "WAIT",
            "action_label": f"ARM {w['option_type']} buy-stop",
            "side": "WAIT",
            "option_type": w["option_type"],
            "strike": w["strike"],
            "expiry": w.get("expiry"),
            "entry_premium": w["buy_stop"],
            "stop_premium": w["planned_stop"],
            "confidence_pct": 40.0,
            "plain_english": (
                f"Arm buy-stops on candidate legs. {w['option_type']} {w['strike']:.0f}: "
                f"mark ₹{w['mark_premium']} → buy-stop ₹{w['buy_stop']} / planned SL ₹{w['planned_stop']}."
            ),
        }

    out["plain_english"] = " ".join(reasons[:3])
    return out


def scan_universe(
    tickers: list[str] | None = None,
    market: str = "india",
    *,
    cfg: ProfitableConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or ProfitableConfig()
    names = [n for n in (tickers or INDEX_NAMES) if n in INDEX_NAMES] or list(INDEX_NAMES)
    results: list[dict[str, Any]] = []
    for name in names:
        try:
            results.append(analyze_profitable(name, cfg=cfg, groww_token=groww_token))
        except Exception as exc:
            logger.exception("Profitable failed for %s", name)
            results.append({"ticker": name, "error": str(exc)[:240], "live": {"take_trade": False, "verdict": "WAIT", "reasons": [str(exc)[:200]]}})

    entries = [r for r in results if (r.get("live") or {}).get("take_trade")]
    return {
        "market": market,
        "exchange": exchange,
        "strategy": STRATEGY_NAME,
        "youtube": YOUTUBE_PROFITABLE_URL,
        "fixed_universe": True,
        "how_to_read": [
            "At ~09:20 IST pick CE & PE with premium in ₹50–₹75 (prefer ~₹62.5).",
            "Arm buy-stop at +50% of that mark; do not buy the mark itself.",
            "If filled, SL = 50% below entry premium. Both sides can fire the same day.",
            "Edge thesis = overnight DNA (react, don't anticipate). Prefer carrying winners overnight.",
            "Research / education only — not financial advice.",
        ],
        "results": results,
        "entries": entries,
        "entry_count": len(entries),
        "disclaimer": "Research / education only — not financial advice. Option buying is high-risk.",
    }
