"""
scalp_a_plus_engine.py
----------------------
Scalp A+ — Waqar Asim "smart money traps" 5-minute scalping playbook.

Top-down: Daily trading range + qualified POIs (extreme / decisional) →
1H narrative / trap filter → 1m or 5m two-leg protocol + FVG limit entry.

Video: https://www.youtube.com/watch?v=O3Jn0U0ftgM — Waqar Asim.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.intraday_shared import enrich_intra_live
from app.trading_hubs.smc_engine.adapters import to_smc_ohlc
from app.trading_hubs.smc_engine.config import SMCConfig
from app.trading_hubs.smc_engine.imbalances import detect_fvgs, detect_order_blocks
from app.trading_hubs.smc_engine.liquidity import detect_crt_sweeps
from app.trading_hubs.smc_engine.models import Bias, StructureEvent, SwingType
from app.trading_hubs.smc_engine.structure import (
    current_bias,
    detect_structure_breaks,
    find_fractal_swings,
)

logger = logging.getLogger(__name__)

YOUTUBE_SCALP_A_PLUS_URL = "https://www.youtube.com/watch?v=O3Jn0U0ftgM"

EXECUTION_TF_OPTIONS = ["1m", "5m"]
PHASE_NONE = "NO_SETUP"
PHASE_RANGE = "RANGE_MAPPED"
PHASE_POI = "POI_QUALIFIED"
PHASE_IN_POI = "PRICE_IN_POI"
PHASE_TRAP = "TRAP_FILTER"
PHASE_TWO_LEG = "TWO_LEG"
PHASE_ENTRY = "FVG_ENTRY"

GUIDE_MARKDOWN = f"""
### Scalp A+ — Smart Money Traps (Waqar Asim)
[Video reference]({YOUTUBE_SCALP_A_PLUS_URL}) — evolved from trading **smart money concepts** to trading **smart money traps**.

#### 1. Higher timeframe (Daily)
| Step | Rule |
|------|------|
| **Trading range** | Last structural impulse — mark **external high** and **external low**; only trade inside this range |
| **POIs (2–3 max)** | **Extreme** (origin of the move) · **Decisional** (zone that caused the break of structure) |
| **Liquidity** | Resting (equal highs/lows) or engineered (fresh resistance / trendline) as fuel before the move |

#### 2. Qualifying the decisional POI
All three required — otherwise treat as a trap:
| Filter | Rule |
|--------|------|
| **Depth** | Retracement before BOS must cross **50%** of the previous leg |
| **Duration** | Zone / battle lasts (multi-bar / multi-session), not a single tiny stall |
| **Inducement** | Zone grabbed liquidity (e.g. sweep of equal highs/lows) before the impulse |

#### 3. Intraday narrative (1H → 15m)
| Step | Rule |
|------|------|
| **Complex pullback** | Wait for price to work toward the HTF POI |
| **Smart money traps** | Avoid early / obvious BOS reactions that run stops the other way |
| **Magnets** | Prior news spike, daily external extreme, Asia low/high as targets |

#### 4. Execution (1m or 5m)
| Step | Rule |
|------|------|
| **Shift in control** | Inducement(s) + trend shift matching HTF bias |
| **Two-leg protocol** | Two distinct structure breaks in your direction in session |
| **Entry** | Limit into the resulting **Fair Value Gap** |
| **Risk** | SL beyond recent swing extreme · BE after key structural break |
| **Targets** | Intrasession **1:3 R:R** · runner toward **1:10 R:R** / magnet |

Conf / SL% / TP% (1:3 primary) / hold on every scan row.
"""


@dataclass
class ScalpAPlusConfig:
    execution_tf: str = "5m"
    min_depth_pct: float = 0.50
    min_poi_bars: int = 3
    rr_intrasession: float = 3.0
    rr_runner: float = 10.0
    take_confidence_threshold: float = 68.0
    lookback_htf: int = 180
    lookback_narrative: int = 220
    lookback_ltf: int = 500
    poi_touch_tol_pct: float = 0.40
    recent_confirm_bars: int = 16
    fractal_window: int = 2
    min_htf_bars: int = 40
    min_ltf_bars: int = 80


def _fetch(
    ticker: str,
    timeframe: str,
    market: str,
    *,
    limit: int,
    groww_token: str,
    exchange: str,
) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market or "crypto" in market.lower()
    df = normalize_ohlcv(
        fetch_data_for_gap_scan(ticker, timeframe, market, groww_token, exchange, limit=limit)
    )
    if df is None or df.empty or len(df) < max(20, limit // 20):
        df = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, timeframe, is_crypto=is_crypto, limit=limit, market=market)
        )
    return df if df is not None else pd.DataFrame()


def _equal_levels(df: pd.DataFrame, kind: str, tol_pct: float = 0.15, lookback: int = 40) -> list[float]:
    """Cluster recent swing highs/lows into resting liquidity pools."""
    work = df.tail(lookback)
    if work.empty:
        return []
    series = work["High"] if kind == "high" else work["Low"]
    vals = series.astype(float).values
    pools: list[float] = []
    for v in vals:
        if not pools:
            pools.append(float(v))
            continue
        if any(abs(v - p) / max(abs(p), 1e-9) * 100 <= tol_pct for p in pools):
            continue
        # keep only if another bar is near (equal highs/lows)
        near = sum(1 for x in vals if abs(x - v) / max(abs(v), 1e-9) * 100 <= tol_pct)
        if near >= 2:
            pools.append(float(v))
    return pools[:4]


def _find_trading_range(df_htf: pd.DataFrame, cfg: ScalpAPlusConfig) -> dict[str, Any] | None:
    smc = to_smc_ohlc(df_htf)
    swings = find_fractal_swings(smc, cfg.fractal_window)
    if len(swings) < 2:
        return None
    breaks = detect_structure_breaks(smc, swings)
    bias = current_bias(breaks)
    a, b = swings[-2], swings[-1]
    # Prefer last completed impulse matching bias when possible
    if bias == Bias.BEARISH:
        highs = [s for s in swings if s.kind == SwingType.HIGH]
        lows = [s for s in swings if s.kind == SwingType.LOW]
        if highs and lows and highs[-1].index < lows[-1].index:
            a, b = highs[-1], lows[-1]
        elif len(swings) >= 2:
            a, b = swings[-2], swings[-1]
    elif bias == Bias.BULLISH:
        highs = [s for s in swings if s.kind == SwingType.HIGH]
        lows = [s for s in swings if s.kind == SwingType.LOW]
        if lows and highs and lows[-1].index < highs[-1].index:
            a, b = lows[-1], highs[-1]

    external_high = max(a.price, b.price)
    external_low = min(a.price, b.price)
    if external_high <= external_low:
        return None

    return {
        "df": smc,
        "swings": swings,
        "breaks": breaks,
        "bias": bias,
        "leg_start": a,
        "leg_end": b,
        "external_high": float(external_high),
        "external_low": float(external_low),
        "equilibrium": float((external_high + external_low) / 2.0),
        "range_pct": float((external_high - external_low) / external_high * 100.0),
    }


def _poi_depth_ok(
    df: pd.DataFrame,
    leg_start_i: int,
    leg_end_i: int,
    bias: Bias,
    min_depth: float,
) -> tuple[bool, float]:
    """Retracement into the impulse must have crossed ~50% of the prior leg."""
    if leg_end_i <= leg_start_i + 1:
        return False, 0.0
    segment = df.iloc[leg_start_i : leg_end_i + 1]
    hi = float(segment["High"].max())
    lo = float(segment["Low"].min())
    rng = hi - lo
    if rng <= 0:
        return False, 0.0
    if bias == Bias.BEARISH:
        # bearish impulse from high→low: pullback depth from low toward high before continuation
        # Use how deep price came back from the start of the drop
        start = float(df["Close"].iloc[leg_start_i])
        end = float(df["Close"].iloc[leg_end_i])
        if start <= end:
            # wrong orientation — measure generic retrace within segment
            retrace = (float(segment["High"].iloc[-3:].max()) - lo) / rng if len(segment) >= 3 else 0.0
        else:
            pull_high = float(segment["High"].max())
            retrace = (pull_high - end) / max(start - end, 1e-9)
    else:
        start = float(df["Close"].iloc[leg_start_i])
        end = float(df["Close"].iloc[leg_end_i])
        if end <= start:
            retrace = (hi - float(segment["Low"].iloc[-3:].min())) / rng if len(segment) >= 3 else 0.0
        else:
            pull_low = float(segment["Low"].min())
            retrace = (end - pull_low) / max(end - start, 1e-9)
    # Also compute classic 50% of range occupancy
    mid_cross = float(segment["Low"].min()) <= (lo + rng * 0.5) <= float(segment["High"].max())
    depth = max(retrace, 0.55 if mid_cross else 0.0)
    # Prefer measuring max adverse excursion vs impulse direction
    if bias == Bias.BEARISH:
        mae = (float(segment["High"].max()) - float(segment["Close"].iloc[-1])) / rng
    else:
        mae = (float(segment["Close"].iloc[-1]) - float(segment["Low"].min())) / rng
    depth = max(depth, mae)
    return depth >= min_depth, float(depth)


def _qualify_decisional_poi(
    rng: dict[str, Any],
    cfg: ScalpAPlusConfig,
) -> dict[str, Any] | None:
    df: pd.DataFrame = rng["df"]
    bias: Bias = rng["bias"]
    breaks = rng["breaks"]
    if bias == Bias.NEUTRAL or not breaks:
        return None

    last = breaks[-1]
    bullish = bias == Bias.BULLISH
    smc_cfg = SMCConfig(fractal_window=cfg.fractal_window, displacement_multiplier=1.4)
    obs = detect_order_blocks(df, smc_cfg)
    sweeps = detect_crt_sweeps(df, smc_cfg)

    # Decisional = last unmitigated OB in bias direction before last BOS
    candidates = [
        o for o in obs
        if o.bullish == bullish and o.impulse_index <= last.index and not o.mitigated
    ]
    if not candidates:
        candidates = [o for o in obs if o.bullish == bullish and o.impulse_index <= last.index]
    if not candidates:
        # Extreme POI fallback: origin of the move
        if bullish:
            zone_lo, zone_hi = rng["external_low"], rng["equilibrium"]
            poi_type = "extreme"
        else:
            zone_lo, zone_hi = rng["equilibrium"], rng["external_high"]
            poi_type = "extreme"
        depth_ok, depth = _poi_depth_ok(df, rng["leg_start"].index, rng["leg_end"].index, bias, cfg.min_depth_pct)
        return {
            "poi_type": poi_type,
            "zone_low": float(zone_lo),
            "zone_high": float(zone_hi),
            "depth_ok": depth_ok,
            "depth": depth,
            "duration_ok": True,
            "duration_bars": abs(rng["leg_end"].index - rng["leg_start"].index) + 1,
            "inducement_ok": any(s.validated for s in sweeps[-6:]),
            "qualified": depth_ok,
        }

    ob = max(candidates, key=lambda o: o.impulse_index)
    zone_lo, zone_hi = float(ob.low), float(ob.high)
    # Duration: bars from OB candle to impulse
    duration_bars = max(1, ob.impulse_index - ob.index + 1)
    # Expand with consolidation width around OB
    left = max(0, ob.index - 2)
    right = min(len(df) - 1, ob.impulse_index)
    duration_bars = max(duration_bars, right - left + 1)
    duration_ok = duration_bars >= cfg.min_poi_bars

    depth_ok, depth = _poi_depth_ok(df, rng["leg_start"].index, rng["leg_end"].index, bias, cfg.min_depth_pct)

    # Inducement: validated sweep into / through the POI before impulse
    inducement_ok = False
    for s in sweeps:
        if s.index > ob.impulse_index:
            continue
        if not s.validated:
            continue
        if zone_lo * 0.998 <= s.swept_level <= zone_hi * 1.002:
            inducement_ok = True
            break
        if bullish and s.direction == "sell_side" and s.swept_level <= zone_hi:
            inducement_ok = True
            break
        if (not bullish) and s.direction == "buy_side" and s.swept_level >= zone_lo:
            inducement_ok = True
            break

    qualified = depth_ok and duration_ok and inducement_ok
    return {
        "poi_type": "decisional",
        "zone_low": zone_lo,
        "zone_high": zone_hi,
        "ob_index": ob.index,
        "depth_ok": depth_ok,
        "depth": depth,
        "duration_ok": duration_ok,
        "duration_bars": duration_bars,
        "inducement_ok": inducement_ok,
        "qualified": qualified,
    }


def _price_in_poi(price: float, poi: dict[str, Any], tol_pct: float) -> bool:
    lo, hi = poi["zone_low"], poi["zone_high"]
    pad = max(abs(hi - lo) * 0.15, price * tol_pct / 100.0)
    return (lo - pad) <= price <= (hi + pad)


def _narrative_trap_filter(
    df_1h: pd.DataFrame,
    bias: Bias,
    poi: dict[str, Any],
    cfg: ScalpAPlusConfig,
) -> dict[str, Any]:
    """Flag early false BOS away from POI as smart-money trap risk."""
    smc = to_smc_ohlc(df_1h)
    swings = find_fractal_swings(smc, cfg.fractal_window)
    breaks = detect_structure_breaks(smc, swings)
    price = float(smc["Close"].iloc[-1])
    in_pullback = _price_in_poi(price, poi, cfg.poi_touch_tol_pct * 2) or (
        (bias == Bias.BEARISH and price > poi["zone_low"])
        or (bias == Bias.BULLISH and price < poi["zone_high"])
    )

    trap_risk = False
    reasons = []
    if breaks:
        last = breaks[-1]
        recent = last.index >= len(smc) - 8
        # Trap: early BOS opposite to eventual HTF bias while still far from POI
        if recent and not _price_in_poi(price, poi, cfg.poi_touch_tol_pct):
            if bias == Bias.BEARISH and last.event in (StructureEvent.BOS_BULL, StructureEvent.CHOCH_BULL):
                trap_risk = True
                reasons.append("1H early bullish BOS away from bearish POI — classic long trap risk")
            if bias == Bias.BULLISH and last.event in (StructureEvent.BOS_BEAR, StructureEvent.CHOCH_BEAR):
                trap_risk = True
                reasons.append("1H early bearish BOS away from bullish POI — classic short trap risk")

    magnets = {
        "external_high": None,
        "external_low": None,
        "equal_highs": _equal_levels(smc, "high"),
        "equal_lows": _equal_levels(smc, "low"),
    }
    return {
        "in_pullback": in_pullback,
        "trap_risk": trap_risk,
        "trap_reasons": reasons,
        "price": price,
        "magnets": magnets,
        "breaks": breaks,
    }


def _two_leg_and_fvg(
    df_ltf: pd.DataFrame,
    bias: Bias,
    cfg: ScalpAPlusConfig,
) -> dict[str, Any]:
    smc = to_smc_ohlc(df_ltf)
    swings = find_fractal_swings(smc, cfg.fractal_window)
    breaks = detect_structure_breaks(smc, swings)
    smc_cfg = SMCConfig(fractal_window=cfg.fractal_window)
    fvgs = detect_fvgs(smc, smc_cfg)
    sweeps = detect_crt_sweeps(smc, smc_cfg)

    cutoff = max(0, len(smc) - cfg.recent_confirm_bars)
    if bias == Bias.BULLISH:
        legs = [b for b in breaks if b.index >= cutoff and b.event in (StructureEvent.BOS_BULL, StructureEvent.CHOCH_BULL)]
        want_bull_fvg = True
        want_sweep = "sell_side"
    elif bias == Bias.BEARISH:
        legs = [b for b in breaks if b.index >= cutoff and b.event in (StructureEvent.BOS_BEAR, StructureEvent.CHOCH_BEAR)]
        want_bull_fvg = False
        want_sweep = "buy_side"
    else:
        return {"two_leg": False, "legs": 0, "fvg": None, "sweep_ok": False}

    recent_sweeps = [
        s for s in sweeps
        if s.index >= cutoff and s.validated and s.direction == want_sweep
    ]
    # Prefer unmitigated FVG after the second leg
    fvg = None
    if len(legs) >= 2:
        after = legs[1].index
        cands = [
            g for g in fvgs
            if g.bullish == want_bull_fvg and g.index >= after and not g.mitigated
        ]
        if not cands:
            cands = [g for g in fvgs if g.bullish == want_bull_fvg and g.index >= cutoff and not g.mitigated]
        if cands:
            fvg = cands[-1]

    return {
        "two_leg": len(legs) >= 2,
        "legs": len(legs),
        "fvg": fvg,
        "sweep_ok": bool(recent_sweeps),
        "recent_sweeps": len(recent_sweeps),
        "df": smc,
        "swings": swings,
    }


def evaluate_live_signal(ctx: dict[str, Any], cfg: ScalpAPlusConfig) -> dict[str, Any]:
    reasons: list[str] = []
    conf = 18.0
    phase = PHASE_NONE
    verdict = "WAIT"
    take = False
    direction = "WAIT"

    rng = ctx.get("range")
    poi = ctx.get("poi")
    narrative = ctx.get("narrative") or {}
    ltf = ctx.get("ltf") or {}
    price = float(ctx.get("ltp") or 0)

    if not rng:
        return enrich_intra_live({
            "signal": "NONE", "direction": "WAIT", "take_trade": False,
            "verdict": "WAIT", "phase": PHASE_NONE, "confidence_pct": 0.0,
            "sl_pct": 0.0, "tp_pct": 0.0, "reasons": ["Could not map daily trading range."],
        }, hold_duration="—")

    bias: Bias = rng["bias"]
    bias_label = bias.value.upper()
    reasons.append(
        f"Daily trading range **{rng['external_low']:,.4g}–{rng['external_high']:,.4g}** "
        f"(EQ {rng['equilibrium']:,.4g}, width {rng['range_pct']:.2f}%) · bias **{bias_label}**"
    )
    phase = PHASE_RANGE
    if bias != Bias.NEUTRAL:
        conf += 12

    if not poi:
        reasons.append("No decisional / extreme POI identified")
        return _pack_live(direction, take, verdict, phase, conf, reasons, price, price, price, cfg, bias_label, poi, ltf)

    tags = []
    tags.append("depth✓" if poi["depth_ok"] else "depth✗")
    tags.append("duration✓" if poi["duration_ok"] else "duration✗")
    tags.append("inducement✓" if poi["inducement_ok"] else "inducement✗")
    reasons.append(
        f"{poi['poi_type'].title()} POI **{poi['zone_low']:,.4g}–{poi['zone_high']:,.4g}** · "
        f"depth {poi['depth']:.0%} · {poi['duration_bars']} bars · {', '.join(tags)}"
    )
    if poi["qualified"]:
        conf += 18
        phase = PHASE_POI
    else:
        conf += 6
        reasons.append("POI incomplete — Waqar: missing depth/duration/inducement = trap risk")

    in_poi = _price_in_poi(price, poi, cfg.poi_touch_tol_pct)
    if in_poi:
        conf += 10
        phase = PHASE_IN_POI
        reasons.append("Price tapping HTF POI (tolerance applied)")
    elif narrative.get("in_pullback"):
        conf += 4
        reasons.append("Complex pullback progressing toward POI (1H narrative)")

    if narrative.get("trap_risk"):
        conf -= 12
        phase = PHASE_TRAP
        reasons.extend(narrative.get("trap_reasons") or ["Smart-money trap filter tripped"])
    else:
        conf += 4

    magnets = narrative.get("magnets") or {}
    eq_h = magnets.get("equal_highs") or []
    eq_l = magnets.get("equal_lows") or []
    if eq_h or eq_l:
        bits = []
        if eq_h:
            bits.append("eq highs " + ", ".join(f"{x:,.4g}" for x in eq_h[:2]))
        if eq_l:
            bits.append("eq lows " + ", ".join(f"{x:,.4g}" for x in eq_l[:2]))
        reasons.append("Liquidity magnets: " + " · ".join(bits))

    two_leg = bool(ltf.get("two_leg"))
    sweep_ok = bool(ltf.get("sweep_ok"))
    fvg = ltf.get("fvg")
    if sweep_ok:
        conf += 8
        reasons.append(f"LTF inducement / CRT sweep ({ltf.get('recent_sweeps', 0)}) in bias direction")
    if two_leg:
        conf += 14
        phase = PHASE_TWO_LEG
        reasons.append(f"Two-leg protocol: **{ltf.get('legs', 0)}** structure breaks in {bias_label} direction")
    else:
        reasons.append(f"Awaiting two-leg BOS on {cfg.execution_tf} (have {ltf.get('legs', 0)})")

    entry = price
    stop = price
    target = price
    runner = price

    if bias == Bias.BULLISH:
        direction = "LONG"
    elif bias == Bias.BEARISH:
        direction = "SHORT"
    else:
        direction = "WAIT"

    if two_leg and fvg is not None and poi.get("qualified") and in_poi and not narrative.get("trap_risk") and bias != Bias.NEUTRAL:
        phase = PHASE_ENTRY
        conf += 16
        entry = float((fvg.floor + fvg.ceiling) / 2.0)
        # SL beyond recent swing extreme
        swings = ltf.get("swings") or []
        if direction == "LONG":
            swing_lows = [s.price for s in swings if s.kind == SwingType.LOW]
            stop = min(swing_lows[-3:]) if swing_lows else float(fvg.floor) * 0.998
            stop = min(stop, float(fvg.floor) * 0.999)
            risk = max(entry - stop, entry * 0.0015)
            target = entry + risk * cfg.rr_intrasession
            runner = entry + risk * cfg.rr_runner
        else:
            swing_highs = [s.price for s in swings if s.kind == SwingType.HIGH]
            stop = max(swing_highs[-3:]) if swing_highs else float(fvg.ceiling) * 1.002
            stop = max(stop, float(fvg.ceiling) * 1.001)
            risk = max(stop - entry, entry * 0.0015)
            target = entry - risk * cfg.rr_intrasession
            runner = entry - risk * cfg.rr_runner
        reasons.append(
            f"Limit into {cfg.execution_tf} FVG **{fvg.floor:,.4g}–{fvg.ceiling:,.4g}** · "
            f"TP1 {cfg.rr_intrasession:.0f}R · runner {cfg.rr_runner:.0f}R"
        )
        verdict = f"TAKE {direction}"
    elif direction in ("LONG", "SHORT") and poi.get("qualified"):
        verdict = f"WATCH {direction}"
        reasons.append("Qualified POI — wait for LTF inducement + two-leg + FVG")
    else:
        verdict = "WAIT"
        direction = "WAIT"

    conf = max(15.0, min(93.0, conf))
    take = phase == PHASE_ENTRY and conf >= cfg.take_confidence_threshold and direction in ("LONG", "SHORT")

    return _pack_live(
        direction, take, verdict, phase, conf, reasons, entry, stop, target, cfg, bias_label, poi, ltf,
        runner=runner, external_high=rng["external_high"], external_low=rng["external_low"],
    )


def _pack_live(
    direction: str,
    take: bool,
    verdict: str,
    phase: str,
    conf: float,
    reasons: list[str],
    entry: float,
    stop: float,
    target: float,
    cfg: ScalpAPlusConfig,
    bias_label: str,
    poi: dict[str, Any] | None,
    ltf: dict[str, Any],
    *,
    runner: float | None = None,
    external_high: float | None = None,
    external_low: float | None = None,
) -> dict[str, Any]:
    price = entry
    if direction == "LONG" and stop < entry:
        sl_pct = max(0.25, (entry - stop) / entry * 100)
        tp_pct = max(0.4, (target - entry) / entry * 100)
    elif direction == "SHORT" and stop > entry:
        sl_pct = max(0.25, (stop - entry) / entry * 100)
        tp_pct = max(0.4, (entry - target) / entry * 100)
    else:
        sl_pct = 0.8
        tp_pct = sl_pct * cfg.rr_intrasession

    hold = f"15–90 min scalp · BE after structural break · runner to {cfg.rr_runner:.0f}R / magnet"
    plan = make_trade_plan(
        direction=direction if take else "—",
        timeframe=cfg.execution_tf,
        stop_loss_pct=round(sl_pct, 2),
        take_profit_pct=round(tp_pct, 2),
        confidence_pct=round(conf, 1),
        style="scalp",
        exit_rule="Move to BE after key structural low/high break; scale at 3R; trail runner toward magnet / 10R.",
        max_hold_exit="Intrasession — flatten if HTF POI thesis fails or trap resumes.",
    )
    return enrich_intra_live({
        "signal": direction if take else "NONE",
        "direction": direction if direction in ("LONG", "SHORT") else None,
        "take_trade": take,
        "verdict": verdict,
        "phase": phase,
        "confidence_pct": round(conf, 1),
        "sl_pct": round(sl_pct, 2),
        "tp_pct": round(tp_pct, 2),
        "rr_ratio": cfg.rr_intrasession,
        "rr_runner": cfg.rr_runner,
        "entry_price": round(entry, 6),
        "stop_price": round(stop, 6),
        "target_price": round(target, 6),
        "runner_price": round(runner, 6) if runner is not None else None,
        "htf_bias": bias_label,
        "poi_type": (poi or {}).get("poi_type"),
        "poi_low": (poi or {}).get("zone_low"),
        "poi_high": (poi or {}).get("zone_high"),
        "poi_qualified": bool((poi or {}).get("qualified")),
        "two_leg": bool(ltf.get("two_leg")),
        "execution_tf": cfg.execution_tf,
        "external_high": external_high,
        "external_low": external_low,
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": hold},
        "hold_duration": hold,
    }, hold_duration=hold)


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: ScalpAPlusConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or ScalpAPlusConfig()
    if cfg.execution_tf not in EXECUTION_TF_OPTIONS:
        cfg.execution_tf = "5m"

    df_d = _fetch(ticker, "1d", market, limit=cfg.lookback_htf, groww_token=groww_token, exchange=exchange)
    if df_d.empty or len(df_d) < cfg.min_htf_bars:
        return {"ticker": ticker, "error": "Insufficient daily data for trading-range map."}

    rng = _find_trading_range(df_d, cfg)
    if not rng:
        return {"ticker": ticker, "error": "Could not identify daily impulse / trading range."}

    poi = _qualify_decisional_poi(rng, cfg)

    df_1h = _fetch(
        ticker, "1h", market, limit=cfg.lookback_narrative, groww_token=groww_token, exchange=exchange,
    )
    narrative = _narrative_trap_filter(df_1h, rng["bias"], poi or {
        "zone_low": rng["external_low"], "zone_high": rng["external_high"],
    }, cfg) if not df_1h.empty else {"in_pullback": False, "trap_risk": False, "magnets": {}}

    df_ltf = _fetch(
        ticker, cfg.execution_tf, market, limit=cfg.lookback_ltf, groww_token=groww_token, exchange=exchange,
    )
    if df_ltf.empty or len(df_ltf) < cfg.min_ltf_bars:
        return {"ticker": ticker, "error": f"Insufficient {cfg.execution_tf} data for two-leg / FVG entry."}

    ltf = _two_leg_and_fvg(df_ltf, rng["bias"], cfg)
    ltp = float(to_smc_ohlc(df_ltf)["Close"].iloc[-1])

    # Prefer LTF price; attach magnets from daily extremes
    if narrative.get("magnets") is not None:
        narrative["magnets"]["external_high"] = rng["external_high"]
        narrative["magnets"]["external_low"] = rng["external_low"]

    live = evaluate_live_signal(
        {"range": rng, "poi": poi, "narrative": narrative, "ltf": ltf, "ltp": ltp},
        cfg,
    )

    return {
        "ticker": ticker,
        "market": market,
        "execution_tf": cfg.execution_tf,
        "htf": "1d",
        "narrative_tf": "1h",
        "bars_htf": len(df_d),
        "bars_narrative": len(df_1h),
        "bars_ltf": len(df_ltf),
        "last_close": ltp,
        "bias": rng["bias"].value,
        "external_high": rng["external_high"],
        "external_low": rng["external_low"],
        "poi": {
            k: v for k, v in (poi or {}).items()
            if k in ("poi_type", "zone_low", "zone_high", "qualified", "depth", "duration_bars",
                     "depth_ok", "duration_ok", "inducement_ok")
        } if poi else None,
        "youtube": YOUTUBE_SCALP_A_PLUS_URL,
        "live": live,
    }


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: ScalpAPlusConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or ScalpAPlusConfig()
    results = []
    for ticker in tickers:
        try:
            results.append(analyze_ticker(ticker, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            logger.exception("Scalp A+ failed for %s", ticker)
            results.append({"ticker": ticker, "error": str(exc)[:220]})

    entries = [r for r in results if not r.get("error") and (r.get("live") or {}).get("take_trade")]
    watches = [
        r for r in results
        if not r.get("error")
        and not (r.get("live") or {}).get("take_trade")
        and str((r.get("live") or {}).get("verdict") or "").startswith("WATCH")
    ]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))
    watches.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market,
        "strategy": "Scalp A+ — Smart Money Traps (Waqar Asim)",
        "youtube": YOUTUBE_SCALP_A_PLUS_URL,
        "execution_tf": cfg.execution_tf,
        "results": results,
        "entries": entries,
        "watchlist": watches,
        "entry_count": len(entries),
        "watch_count": len(watches),
        "disclaimer": "Research / education only — not financial advice.",
    }
