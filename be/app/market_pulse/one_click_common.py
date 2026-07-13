"""
one_click_common.py
--------------------
Shared plumbing for the "One-Click Trade Setup" composite engines
(one_click_scalping_engine / one_click_intraday_engine / one_click_swing_engine).

Design: rather than re-implementing indicator logic, each composite calls a small,
deliberately curated set of ALREADY-BUILT, structurally-independent strategy engines'
`analyze_ticker()` functions (liquidity-sweep vs. multi-indicator trend vs. fundamentals,
etc.) and combines their votes into one confluence verdict. Requiring genuinely
independent primitives to agree — rather than many indicator-flavored engines that
share the same underlying inputs — is what makes the combined signal more trustworthy
than any single engine alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

STRICT = "strict"
LOOSE = "loose"

STRICTNESS_OPTIONS = [
    ("strict", "Fewer / High Quality"),
    ("loose", "More / Lower Quality"),
]

_LONG_TOKENS = {"LONG", "BUY", "BULLISH", "TAKE LONG"}
_SHORT_TOKENS = {"SHORT", "SELL", "BEARISH", "TAKE SHORT"}


@dataclass
class Vote:
    engine: str
    direction: str  # "LONG" | "SHORT" | "WAIT"
    confidence: float
    take: bool
    entry: float | None = None
    sl: float | None = None
    tp1: float | None = None
    tp2: float | None = None
    reasons: list[str] = field(default_factory=list)
    error: str | None = None


def normalize_direction(raw: Any) -> str:
    """Map an engine-specific direction/verdict string to LONG / SHORT / WAIT."""
    if raw is None:
        return "WAIT"
    s = str(raw).upper()
    for tok in _LONG_TOKENS:
        if tok in s:
            return "LONG"
    for tok in _SHORT_TOKENS:
        if tok in s:
            return "SHORT"
    return "WAIT"


def vote_from_live_schema(engine: str, result: dict[str, Any]) -> Vote:
    """Extract a Vote from the common `{"live": {...}}` schema shared by scalp_*,
    intraday_mtf_breakout_retest, and swing_trading_st_* engines."""
    if not result or result.get("error"):
        return Vote(engine=engine, direction="WAIT", confidence=0.0, take=False,
                     error=result.get("error") if result else "No result")
    live = result.get("live") or {}
    if not live or live.get("signal") == "NO_DATA":
        return Vote(engine=engine, direction="WAIT", confidence=0.0, take=False, error="No live signal")

    direction = normalize_direction(live.get("direction") or live.get("verdict"))
    confidence = float(live.get("confidence_pct") or 0.0)
    take = bool(live.get("take_trade")) and direction in ("LONG", "SHORT")
    entry = live.get("entry_price")
    sl = live.get("stop_price")
    tp1 = live.get("target1_price") or live.get("target_price")
    tp2 = live.get("target2_price") or live.get("target_price")
    reasons = list(live.get("reasons") or [])
    return Vote(engine=engine, direction=direction, confidence=confidence, take=take,
                entry=entry, sl=sl, tp1=tp1, tp2=tp2, reasons=reasons)


def vote_from_mtf_bias(result: dict[str, Any]) -> Vote:
    """Extract a Vote from mtf_intraday_bias_engine.analyze_ticker's top-level schema."""
    if not result or result.get("error"):
        return Vote(engine="mtf_intraday_bias", direction="WAIT", confidence=0.0, take=False,
                     error=result.get("error") if result else "No result")
    direction = normalize_direction(result.get("direction"))
    confidence = float(result.get("confidence") or 0.0)
    setup = result.get("trade_setup") or {}
    take = bool(setup.get("actionable")) and direction in ("LONG", "SHORT")
    reasons = [f"MTF weighted bias: {result.get('close_bias', '—')}"]
    return Vote(
        engine="mtf_intraday_bias", direction=direction, confidence=confidence, take=take,
        entry=result.get("current_price"),
        sl=setup.get("stop_loss") or setup.get("sl"),
        tp1=setup.get("target1") or setup.get("target") or setup.get("take_profit"),
        tp2=setup.get("target2") or setup.get("target") or setup.get("take_profit"),
        reasons=reasons,
    )


def momentum_context(result: dict[str, Any], direction: str) -> dict[str, Any]:
    """Read momentum_engine's multi-timeframe direction + ADX-based strength as a
    non-voting confirmation/strength filter — not a directional vote, since its
    EMA/ADX read would be correlated with EMA-trend-based votes already cast
    elsewhere. Returns a confidence adjustment (+/-) and a note for transparency.

    NOTE: `momentum_engine` has no counterpart ported into this backend yet (it is
    not one of app.trading_hubs.* or app.market_pulse.* engines). Callers that have
    no momentum result should pass `result=None`; this returns a neutral no-op
    adjustment so composites degrade gracefully instead of failing."""
    if not result or result.get("error") or direction not in ("LONG", "SHORT"):
        return {"adjustment": 0.0, "note": "Momentum: unavailable", "strength": "—", "mom_direction": "—"}

    mom_dir = result.get("overall_direction", "NO_DATA")
    strength = result.get("overall_strength", "—")
    want_dir = "UP" if direction == "LONG" else "DOWN"

    if mom_dir == want_dir:
        adj = {"STRONG": 10.0, "MEDIUM": 4.0}.get(strength, 0.0)
        note = f"📶 Momentum: {mom_dir} · {strength} trend strength — agrees with {direction}"
    elif mom_dir in ("CONSOLIDATING", "MIXED", "NO_DATA"):
        adj = -5.0
        note = f"📶 Momentum: {mom_dir} — no clear multi-timeframe trend backing {direction}"
    else:
        adj = -12.0
        note = f"📶 Momentum: {mom_dir} · {strength} — actively disagrees with {direction}"

    return {"adjustment": adj, "note": note, "strength": strength, "mom_direction": mom_dir}


def fundamental_gate(result: dict[str, Any]) -> tuple[str, float, str]:
    """Returns (direction_lean, confidence_pct, note) from fundamental_analysis_engine —
    used as a non-technical non-contradiction check, not a primary vote.

    NOTE: `fundamental_analysis_engine` has no counterpart ported into this backend
    yet. Callers with no fundamental result should pass `result=None`; this returns
    a neutral WAIT lean so composites degrade gracefully instead of failing."""
    if not result or result.get("error"):
        return "WAIT", 0.0, "Fundamentals unavailable."
    overall = result.get("overall") or {}
    signal = overall.get("signal", "NEUTRAL")
    conf = float(overall.get("confidence_pct") or 50.0)
    lean = "LONG" if signal == "BULLISH" else "SHORT" if signal == "BEARISH" else "WAIT"
    note = f"Fundamentals: {signal} ({conf:.0f}% confidence) — {result.get('valuation', {}).get('label', 'N/A')}"
    return lean, conf, note


def combine_confluence(
    votes: list[Vote],
    *,
    strictness: str = STRICT,
    min_agree_strict: int = 2,
    min_agree_loose: int = 2,
    take_threshold_strict: float = 68.0,
    take_threshold_loose: float = 55.0,
    fundamental_note: str | None = None,
    fundamental_conflict: bool = False,
) -> dict[str, Any]:
    """Genuine N-of-M confluence: count how many *independent* engines agree on
    direction, weighted by their own confidence. Returns a composite verdict dict."""
    usable = [v for v in votes if v.direction in ("LONG", "SHORT") and not v.error]

    long_votes = [v for v in usable if v.direction == "LONG"]
    short_votes = [v for v in usable if v.direction == "SHORT"]

    if len(long_votes) >= len(short_votes) and long_votes:
        agreeing, direction = long_votes, "LONG"
    elif short_votes:
        agreeing, direction = short_votes, "SHORT"
    else:
        agreeing, direction = [], "WAIT"

    n_agree = len(agreeing)
    min_agree = min_agree_strict if strictness == STRICT else min_agree_loose
    take_threshold = take_threshold_strict if strictness == STRICT else take_threshold_loose

    if not agreeing:
        composite_confidence = 0.0
    else:
        composite_confidence = sum(v.confidence for v in agreeing) / len(agreeing)
        composite_confidence += min(15.0, (n_agree - 1) * 7.0)  # confluence bonus
        composite_confidence = max(0.0, min(96.0, composite_confidence))

    if fundamental_conflict:
        if strictness == STRICT:
            composite_confidence = min(composite_confidence, take_threshold - 1)
        else:
            composite_confidence -= 10.0

    take = (
        direction in ("LONG", "SHORT")
        and n_agree >= min_agree
        and composite_confidence >= take_threshold
    )

    entries = [v.entry for v in agreeing if v.entry]
    sls = [v.sl for v in agreeing if v.sl]
    tp1s = [v.tp1 for v in agreeing if v.tp1]
    tp2s = [v.tp2 for v in agreeing if v.tp2]

    entry = float(np.mean(entries)) if entries else None
    if direction == "LONG":
        sl = min(sls) if sls else None       # widest safety margin among agreeing engines
        tp1 = min(tp1s) if tp1s else None     # nearest (conservative) partial target
        tp2 = max(tp2s) if tp2s else None     # furthest structural runner target
    elif direction == "SHORT":
        sl = max(sls) if sls else None
        tp1 = max(tp1s) if tp1s else None
        tp2 = min(tp2s) if tp2s else None
    else:
        sl = tp1 = tp2 = None

    verdict = f"TAKE {direction}" if take else ("NO TRADE" if direction == "WAIT" else f"WATCH {direction}")

    reasons: list[str] = [f"{n_agree} of {len(votes)} engines agree on {direction}" if direction != "WAIT"
                           else "No directional agreement among curated engines"]
    for v in votes:
        tag = "✅" if v in agreeing else ("❌" if v.direction in ("LONG", "SHORT") else "⚪")
        reasons.append(f"{tag} {v.engine}: {v.direction} ({v.confidence:.0f}%)" + (f" — {v.error}" if v.error else ""))
    if fundamental_note:
        reasons.append(fundamental_note)

    return {
        "direction": direction,
        "verdict": verdict,
        "take_trade": take,
        "confidence_pct": round(composite_confidence, 1),
        "n_agree": n_agree,
        "n_total": len(votes),
        "min_agree_required": min_agree,
        "take_threshold": take_threshold,
        "entry_price": round(entry, 6) if entry else None,
        "stop_price": round(sl, 6) if sl else None,
        "target1_price": round(tp1, 6) if tp1 else None,
        "target2_price": round(tp2, 6) if tp2 else None,
        "votes": [
            {
                "engine": v.engine, "direction": v.direction, "confidence": round(v.confidence, 1),
                "take": v.take, "agreed": v in agreeing, "error": v.error, "reasons": v.reasons[:3],
            }
            for v in votes
        ],
        "reasons": reasons,
        "strictness": strictness,
    }


# ---------------------------------------------------------------------------
# Shared backtest simulator — two-stage partial-TP exit model
# ---------------------------------------------------------------------------

@dataclass
class BacktestTrade:
    entry_date: Any
    exit_date: Any
    direction: str
    entry: float
    exit: float
    r_multiple: float
    outcome: str  # "TP1_BE_TP2" | "TP1_BE_SL" | "SL" | "TP2_DIRECT" | "OPEN_AT_END"


def simulate_two_stage_backtest(
    df: pd.DataFrame,
    signals: pd.DataFrame,
    *,
    sl_pct: float = 1.0,
    tp1_rr: float = 1.0,
    tp2_rr: float = 2.0,
    max_hold_bars: int = 40,
) -> dict[str, Any]:
    """
    Walk-forward simulation of a directional signal series with a two-stage
    partial-TP exit (TP1 @ tp1_rr -> book 50%, move SL to breakeven; remainder
    exits at TP2 @ tp2_rr, the SL, or after max_hold_bars).

    `signals` must have a "direction" column (LONG/SHORT/None) aligned to df.index.
    """
    trades: list[BacktestTrade] = []
    equity = [0.0]
    n = len(df)
    i = 0
    while i < n - 1:
        direction = signals["direction"].iloc[i] if i < len(signals) else None
        if direction not in ("LONG", "SHORT"):
            i += 1
            continue

        entry = float(df["close"].iloc[i])
        risk = entry * (sl_pct / 100.0)
        if direction == "LONG":
            sl = entry - risk
            tp1 = entry + risk * tp1_rr
            tp2 = entry + risk * tp2_rr
        else:
            sl = entry + risk
            tp1 = entry - risk * tp1_rr
            tp2 = entry - risk * tp2_rr

        stage = "OPEN"
        r_total = 0.0
        exit_price = entry
        exit_idx = i
        outcome = "OPEN_AT_END"
        for j in range(i + 1, min(i + 1 + max_hold_bars, n)):
            bar = df.iloc[j]
            hi, lo = float(bar["high"]), float(bar["low"])
            if stage == "OPEN":
                hit_tp1 = (hi >= tp1) if direction == "LONG" else (lo <= tp1)
                hit_sl = (lo <= sl) if direction == "LONG" else (hi >= sl)
                if hit_sl and not hit_tp1:
                    r_total = -1.0
                    exit_price, exit_idx, outcome = sl, j, "SL"
                    break
                if hit_tp1:
                    r_total += 0.5 * tp1_rr  # half position booked at TP1
                    sl = entry  # move SL to breakeven for the runner
                    stage = "RUNNER"
                    if hit_sl:  # same bar swept both — assume TP1 first (favorable order)
                        continue
            else:  # RUNNER stage — SL at breakeven, target TP2
                hit_tp2 = (hi >= tp2) if direction == "LONG" else (lo <= tp2)
                hit_be = (lo <= sl) if direction == "LONG" else (hi >= sl)
                if hit_tp2:
                    r_total += 0.5 * tp2_rr
                    exit_price, exit_idx, outcome = tp2, j, "TP1_BE_TP2"
                    break
                if hit_be:
                    exit_price, exit_idx, outcome = sl, j, "TP1_BE_SL"
                    break
        else:
            exit_idx = min(i + max_hold_bars, n - 1)
            exit_price = float(df["close"].iloc[exit_idx])
            r_total += (
                ((exit_price - entry) / risk) if direction == "LONG" else ((entry - exit_price) / risk)
            ) * (0.5 if stage == "RUNNER" else 1.0)

        trades.append(BacktestTrade(
            entry_date=df.index[i], exit_date=df.index[exit_idx], direction=direction,
            entry=entry, exit=exit_price, r_multiple=round(r_total, 3), outcome=outcome,
        ))
        equity.append(equity[-1] + r_total)
        i = exit_idx + 1

    if not trades:
        return {"trades": [], "win_rate_pct": None, "profit_factor": None, "max_drawdown_r": None,
                "total_trades": 0, "avg_r": None, "equity_curve": equity}

    wins = [t for t in trades if t.r_multiple > 0]
    losses = [t for t in trades if t.r_multiple <= 0]
    gross_win = sum(t.r_multiple for t in wins)
    gross_loss = abs(sum(t.r_multiple for t in losses))
    profit_factor = (gross_win / gross_loss) if gross_loss > 1e-9 else (float("inf") if gross_win > 0 else 0.0)

    eq = np.array(equity)
    running_max = np.maximum.accumulate(eq)
    drawdown = running_max - eq
    max_dd = float(drawdown.max()) if len(drawdown) else 0.0

    return {
        "trades": [
            {"entry_date": str(t.entry_date), "exit_date": str(t.exit_date), "direction": t.direction,
             "entry": round(t.entry, 4), "exit": round(t.exit, 4), "r_multiple": t.r_multiple, "outcome": t.outcome}
            for t in trades
        ],
        "total_trades": len(trades),
        "win_rate_pct": round(100.0 * len(wins) / len(trades), 1),
        "profit_factor": round(profit_factor, 2) if np.isfinite(profit_factor) else None,
        "avg_r": round(sum(t.r_multiple for t in trades) / len(trades), 3),
        "max_drawdown_r": round(max_dd, 2),
        "equity_curve": [round(float(e), 3) for e in equity],
    }
