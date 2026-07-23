"""
smc_sc_best_engine.py
------------------------
SC-Best — five Smart Money Concepts entry models, each following the same
Context (HTF area of interest / liquidity sweep) -> Confirmation (LTF market
structure shift) -> Execution (limit order at the structural origin) framework.

Core philosophy: never chase the impulsive move. Retail FOMOs into expansion;
this strategy waits for price to naturally retrace back to the structural
footprint institutions left behind, and places a resting limit order there.

Models implemented:
  1. Breaker Block   — swing low -> swing high -> a LOWER low that SWEEPS the
                        first low, then an explosive close back above the
                        swing high (structure shift). Entry: the up-close
                        candle(s) between the first low and the high (mirror
                        for bearish). A failed order block that flips role.
  2. Fair Value Gap   — a 3-candle imbalance left by an impulsive leg, used as
                        a continuation entry after a reversal is confirmed.
                        Entry: the near edge of the still-unfilled gap.
  3. Mitigation Block — same shape as a Breaker, but the sweep FAILS: a
                        HIGHER low (bullish) / LOWER high (bearish) instead —
                        trapped opposite-side traders exit at breakeven when
                        price returns to the block.
  4. Inversion FVG    — a FVG that gets fully filled (mitigated), then price
                        closes decisively through its midpoint — flipping the
                        gap to the opposite polarity (support <-> resistance).
  5. Order Block      — the last opposite-colored candle immediately before
                        the impulsive (ATR-displacement) leg that actually
                        broke market structure — displacement-filtered AND
                        structure-break-confirmed (stricter than the raw
                        order-block detector used elsewhere in this app,
                        which doesn't require the impulse to break structure).

All five reuse the shared fractal-swing / structure-break / FVG / order-block
primitives in `app.trading_hubs.smc_engine` (already used by
`scalp_smc_engine.py`) rather than reimplementing swing or imbalance
detection from scratch.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.live_price import get_last_traded_price
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.smart_money_shared import enrich_smc_live, hold_for_tf
from app.trading_hubs.smc_engine.adapters import to_smc_ohlc
from app.trading_hubs.smc_engine.config import SMCConfig
from app.trading_hubs.smc_engine.data import build_multi_timeframe
from app.trading_hubs.smc_engine.imbalances import _atr, detect_fvgs, detect_order_blocks
from app.trading_hubs.smc_engine.liquidity import detect_crt_sweeps
from app.trading_hubs.smc_engine.models import Bias, FairValueGap, OrderBlock, StructureBreak, StructureEvent, Swing, SwingType
from app.trading_hubs.smc_engine.structure import current_bias, detect_structure_breaks, find_fractal_swings

logger = logging.getLogger(__name__)

YOUTUBE_SC_BEST_URL = "https://www.youtube.com/watch?v=KO3OqM7zNDQ&t=4s"

LTF_OPTIONS = ["5m", "15m", "1h"]
_TF_RESAMPLE = {
    "5m": ("1h", "4h"),
    "15m": ("1h", "4h"),
    "1h": ("4h", "1d"),
}

_MODEL_NAMES = ("Breaker Block", "Fair Value Gap", "Mitigation Block", "Inversion FVG", "Order Block")


@dataclass
class SCBestConfig:
    ltf: str = "15m"
    fractal_window: int = 2
    lookback_bars: int = 600
    min_ltf_bars: int = 120
    displacement_multiplier: float = 1.5
    atr_stop_buffer: float = 0.25  # fraction of ATR added beyond the zone for the stop
    rr_ratio: float = 2.0
    take_confidence_threshold: float = 62.0
    recent_bars: int = 40  # a candidate's trigger must be within this many LTF bars to stay "live"


def _smc_config(cfg: SCBestConfig) -> SMCConfig:
    mtf_rule, htf_rule = _TF_RESAMPLE.get(cfg.ltf, ("1h", "4h"))
    return SMCConfig(
        fractal_window=cfg.fractal_window,
        displacement_multiplier=cfg.displacement_multiplier,
        mtf_rule=mtf_rule,
        htf_rule=htf_rule,
    )


# ---------------------------------------------------------------------------
# Shared candidate helpers
# ---------------------------------------------------------------------------

def _up_close_indices(df: pd.DataFrame, start_idx: int, end_idx: int) -> list[int]:
    closes, opens = df["Close"].values, df["Open"].values
    return [i for i in range(start_idx, end_idx) if closes[i] > opens[i]]


def _down_close_indices(df: pd.DataFrame, start_idx: int, end_idx: int) -> list[int]:
    closes, opens = df["Close"].values, df["Open"].values
    return [i for i in range(start_idx, end_idx) if closes[i] < opens[i]]


def _phase_for_zone(df: pd.DataFrame, zone_bottom: float, zone_top: float, last_idx: int) -> str:
    last_low = float(df["Low"].iloc[last_idx])
    last_high = float(df["High"].iloc[last_idx])
    if last_low <= zone_top and last_high >= zone_bottom:
        return "AT_ZONE"
    return "AWAITING_RETRACE"


def _mitigated_since(df: pd.DataFrame, zone_bottom: float, zone_top: float, since_idx: int, last_idx: int) -> int | None:
    lows, highs = df["Low"].values, df["High"].values
    for j in range(since_idx, last_idx + 1):
        if lows[j] <= zone_top and highs[j] >= zone_bottom:
            return j
    return None


def _atr_at(atr_series: pd.Series, idx: int) -> float:
    if idx < 0 or idx >= len(atr_series):
        return 0.0
    val = atr_series.iloc[idx]
    return float(val) if pd.notna(val) else 0.0


def _build_candidate(
    df: pd.DataFrame, *, model: str, direction: str, zone_top: float, zone_bottom: float,
    origin_index: int, trigger_index: int, last_idx: int, atr_buffer: float, notes: str,
) -> dict[str, Any]:
    mitigated_index = _mitigated_since(df, zone_bottom, zone_top, trigger_index, last_idx)
    phase = _phase_for_zone(df, zone_bottom, zone_top, last_idx)
    if phase != "AT_ZONE" and mitigated_index is not None:
        phase = "ALREADY_TAPPED"

    if direction == "LONG":
        entry_price = zone_top
        stop_price = zone_bottom - atr_buffer
    else:
        entry_price = zone_bottom
        stop_price = zone_top + atr_buffer

    return {
        "model": model, "direction": direction,
        "zone_top": round(zone_top, 6), "zone_bottom": round(zone_bottom, 6),
        "entry_price": round(entry_price, 6), "stop_price": round(stop_price, 6),
        "origin_index": origin_index, "trigger_index": trigger_index,
        "mitigated_index": mitigated_index, "phase": phase, "notes": notes,
    }


# ---------------------------------------------------------------------------
# Model 1 (Breaker Block) + Model 3 (Mitigation Block) — same swing-triple
# scan, differing only in whether the middle swing gets swept or held.
# ---------------------------------------------------------------------------

def _find_swing_triples(swings: list[Swing]) -> list[tuple[Swing, Swing, Swing]]:
    triples = []
    for i in range(len(swings) - 2):
        a, b, c = swings[i], swings[i + 1], swings[i + 2]
        if a.kind == SwingType.LOW and b.kind == SwingType.HIGH and c.kind == SwingType.LOW:
            triples.append((a, b, c))
        elif a.kind == SwingType.HIGH and b.kind == SwingType.LOW and c.kind == SwingType.HIGH:
            triples.append((a, b, c))
    return triples


def find_breaker_and_mitigation_blocks(
    df: pd.DataFrame, swings: list[Swing], breaks: list[StructureBreak], *,
    last_idx: int, atr_series: pd.Series, atr_buffer_mult: float,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for a, b, c in _find_swing_triples(swings):
        if a.kind == SwingType.LOW:  # low -> high -> low : bullish context
            is_sweep = c.price < a.price
            is_held = c.price > a.price
            if not (is_sweep or is_held):
                continue
            trigger = next(
                (br for br in breaks if br.index > c.index and br.reference_swing.index == b.index
                 and br.event in (StructureEvent.BOS_BULL, StructureEvent.CHOCH_BULL)),
                None,
            )
            if trigger is None:
                continue
            up_candles = _up_close_indices(df, a.index, b.index)
            if not up_candles:
                continue
            origin_idx = up_candles[-1]
            zone_top, zone_bottom = float(df["High"].iloc[origin_idx]), float(df["Low"].iloc[origin_idx])
            model = "Breaker Block" if is_sweep else "Mitigation Block"
            notes = (
                f"Swing low {a.price:.6g} {'swept' if is_sweep else 'held as a higher low'} at {c.price:.6g}, "
                f"then price closed back above the {b.price:.6g} swing high — structure shift confirmed. "
                f"{'A failed (swept) order block flipping from supply to demand.' if is_sweep else 'Trapped sellers exit at breakeven when price returns here.'}"
            )
            candidates.append(_build_candidate(
                df, model=model, direction="LONG", zone_top=zone_top, zone_bottom=zone_bottom,
                origin_index=origin_idx, trigger_index=trigger.index, last_idx=last_idx,
                atr_buffer=_atr_at(atr_series, trigger.index) * atr_buffer_mult, notes=notes,
            ))
        else:  # high -> low -> high : bearish context
            is_sweep = c.price > a.price
            is_held = c.price < a.price
            if not (is_sweep or is_held):
                continue
            trigger = next(
                (br for br in breaks if br.index > c.index and br.reference_swing.index == b.index
                 and br.event in (StructureEvent.BOS_BEAR, StructureEvent.CHOCH_BEAR)),
                None,
            )
            if trigger is None:
                continue
            down_candles = _down_close_indices(df, a.index, b.index)
            if not down_candles:
                continue
            origin_idx = down_candles[-1]
            zone_top, zone_bottom = float(df["High"].iloc[origin_idx]), float(df["Low"].iloc[origin_idx])
            model = "Breaker Block" if is_sweep else "Mitigation Block"
            notes = (
                f"Swing high {a.price:.6g} {'swept' if is_sweep else 'held as a lower high'} at {c.price:.6g}, "
                f"then price closed back below the {b.price:.6g} swing low — structure shift confirmed. "
                f"{'A failed (swept) order block flipping from demand to supply.' if is_sweep else 'Trapped buyers exit at breakeven when price returns here.'}"
            )
            candidates.append(_build_candidate(
                df, model=model, direction="SHORT", zone_top=zone_top, zone_bottom=zone_bottom,
                origin_index=origin_idx, trigger_index=trigger.index, last_idx=last_idx,
                atr_buffer=_atr_at(atr_series, trigger.index) * atr_buffer_mult, notes=notes,
            ))
    return candidates


# ---------------------------------------------------------------------------
# Model 5: Order Block — displacement-filtered AND structure-break-confirmed
# ---------------------------------------------------------------------------

def find_confirmed_order_blocks(
    df: pd.DataFrame, order_blocks: list[OrderBlock], breaks: list[StructureBreak], *,
    last_idx: int, atr_series: pd.Series, atr_buffer_mult: float,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for ob in order_blocks:
        direction = "LONG" if ob.bullish else "SHORT"
        wanted = (StructureEvent.BOS_BULL, StructureEvent.CHOCH_BULL) if ob.bullish else (StructureEvent.BOS_BEAR, StructureEvent.CHOCH_BEAR)
        trigger = next((br for br in breaks if br.event in wanted and abs(br.index - ob.impulse_index) <= 2), None)
        if trigger is None:
            continue  # the displacement candle exists but never actually broke structure — skip
        notes = (
            f"Last {'up' if ob.bullish else 'down'}-close candle immediately before the displacement leg "
            f"({ob.high - ob.low:.4g} range) that broke market structure — the institutional footprint "
            "before the impulsive expansion."
        )
        candidates.append(_build_candidate(
            df, model="Order Block", direction=direction, zone_top=float(ob.high), zone_bottom=float(ob.low),
            origin_index=ob.index, trigger_index=trigger.index, last_idx=last_idx,
            atr_buffer=_atr_at(atr_series, trigger.index) * atr_buffer_mult, notes=notes,
        ))
    return candidates


# ---------------------------------------------------------------------------
# Model 2: Fair Value Gap (fresh, continuation) + Model 4: Inversion FVG
# ---------------------------------------------------------------------------

def find_fvg_candidates(
    df: pd.DataFrame, fvgs: list[FairValueGap], breaks: list[StructureBreak], *,
    last_idx: int, atr_series: pd.Series, atr_buffer_mult: float,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for gap in fvgs:
        if gap.mitigated:
            continue  # a plain FVG entry wants a still-open (unfilled) gap
        direction = "LONG" if gap.bullish else "SHORT"
        wanted = (StructureEvent.BOS_BULL, StructureEvent.CHOCH_BULL) if gap.bullish else (StructureEvent.BOS_BEAR, StructureEvent.CHOCH_BEAR)
        confirmed = any(br.index <= gap.index and br.event in wanted for br in breaks)
        if not confirmed:
            continue  # FVG works best as a CONTINUATION after a reversal is already confirmed
        entry_price = gap.ceiling if gap.bullish else gap.floor
        buf = _atr_at(atr_series, gap.index) * atr_buffer_mult
        stop_price = gap.floor - buf if gap.bullish else gap.ceiling + buf
        candidates.append({
            "model": "Fair Value Gap", "direction": direction,
            "zone_top": round(gap.ceiling, 6), "zone_bottom": round(gap.floor, 6),
            "entry_price": round(entry_price, 6), "stop_price": round(stop_price, 6),
            "origin_index": gap.index, "trigger_index": gap.index, "mitigated_index": None,
            "phase": _phase_for_zone(df, gap.floor, gap.ceiling, last_idx),
            "notes": (
                "Unfilled imbalance left by an impulsive leg — smart money treats it as an unfilled "
                "debt price tends to revisit before continuing the trend."
            ),
        })
    return candidates


def find_ifvg_candidates(
    df: pd.DataFrame, fvgs: list[FairValueGap], *, last_idx: int, atr_series: pd.Series, atr_buffer_mult: float,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    closes = df["Close"].values
    for gap in fvgs:
        if not gap.mitigated or gap.mitigated_index is None:
            continue
        mid = gap.midpoint
        inversion_idx = None
        for j in range(gap.mitigated_index, last_idx + 1):
            if gap.bullish and closes[j] < mid:
                inversion_idx = j
                break
            if not gap.bullish and closes[j] > mid:
                inversion_idx = j
                break
        if inversion_idx is None:
            continue
        direction = "SHORT" if gap.bullish else "LONG"
        buf = _atr_at(atr_series, inversion_idx) * atr_buffer_mult
        entry_price = gap.floor if direction == "SHORT" else gap.ceiling
        stop_price = gap.ceiling + buf if direction == "SHORT" else gap.floor - buf
        candidates.append({
            "model": "Inversion FVG", "direction": direction,
            "zone_top": round(gap.ceiling, 6), "zone_bottom": round(gap.floor, 6),
            "entry_price": round(entry_price, 6), "stop_price": round(stop_price, 6),
            "origin_index": gap.index, "trigger_index": inversion_idx, "mitigated_index": gap.mitigated_index,
            "phase": _phase_for_zone(df, gap.floor, gap.ceiling, last_idx),
            "notes": (
                f"{'Bullish' if gap.bullish else 'Bearish'} FVG fully filled at bar {gap.mitigated_index}, then "
                f"price closed decisively through its {mid:.6g} midpoint — flipped to "
                f"{'bearish resistance' if direction == 'SHORT' else 'bullish support'}."
            ),
        })
    return candidates


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_sc_best_pipeline(df_ltf_raw: pd.DataFrame, cfg: SCBestConfig) -> dict[str, Any]:
    smc_cfg = _smc_config(cfg)
    df_ltf = to_smc_ohlc(df_ltf_raw)
    if df_ltf.empty or len(df_ltf) < cfg.min_ltf_bars:
        return {"error": "Insufficient LTF bars."}

    timeframes = build_multi_timeframe(df_ltf, smc_cfg)
    df_htf = timeframes["HTF"]
    if df_htf.empty or len(df_htf) < 10:
        return {"error": "Insufficient HTF bars after resample."}

    # Context: HTF structural bias + recent liquidity sweeps of major swings
    htf_swings = find_fractal_swings(df_htf, smc_cfg.fractal_window)
    htf_breaks = detect_structure_breaks(df_htf, htf_swings)
    htf_bias = current_bias(htf_breaks)
    htf_sweeps = detect_crt_sweeps(df_htf, smc_cfg)

    # Confirmation + Execution: LTF structure, FVGs, order blocks
    ltf_swings = find_fractal_swings(df_ltf, smc_cfg.fractal_window)
    ltf_breaks = detect_structure_breaks(df_ltf, ltf_swings)
    fvgs = detect_fvgs(df_ltf, smc_cfg)
    order_blocks = detect_order_blocks(df_ltf, smc_cfg)
    atr_series = _atr(df_ltf, smc_cfg.displacement_atr_window)
    last_idx = len(df_ltf) - 1

    candidates: list[dict[str, Any]] = []
    candidates += find_breaker_and_mitigation_blocks(
        df_ltf, ltf_swings, ltf_breaks, last_idx=last_idx, atr_series=atr_series, atr_buffer_mult=cfg.atr_stop_buffer,
    )
    candidates += find_confirmed_order_blocks(
        df_ltf, order_blocks, ltf_breaks, last_idx=last_idx, atr_series=atr_series, atr_buffer_mult=cfg.atr_stop_buffer,
    )
    candidates += find_fvg_candidates(
        df_ltf, fvgs, ltf_breaks, last_idx=last_idx, atr_series=atr_series, atr_buffer_mult=cfg.atr_stop_buffer,
    )
    candidates += find_ifvg_candidates(
        df_ltf, fvgs, last_idx=last_idx, atr_series=atr_series, atr_buffer_mult=cfg.atr_stop_buffer,
    )

    candidates = [c for c in candidates if last_idx - c["trigger_index"] <= cfg.recent_bars]
    candidates.sort(key=lambda c: (c["phase"] != "AT_ZONE", c["phase"] != "AWAITING_RETRACE", -c["trigger_index"]))

    return {
        "df_ltf": df_ltf, "df_htf": df_htf,
        "htf_bias": htf_bias, "htf_swings": htf_swings, "htf_breaks": htf_breaks, "htf_sweeps": htf_sweeps,
        "ltf_swings": ltf_swings, "ltf_breaks": ltf_breaks,
        "fvgs": fvgs, "order_blocks": order_blocks,
        "candidates": candidates,
    }


def _aligned_with_bias(candidate: dict, bias: Bias) -> bool:
    if bias == Bias.NEUTRAL:
        return True
    return (bias == Bias.BULLISH and candidate["direction"] == "LONG") or (bias == Bias.BEARISH and candidate["direction"] == "SHORT")


def evaluate_live_signal(pipeline: dict[str, Any], cfg: SCBestConfig) -> dict[str, Any]:
    if pipeline.get("error"):
        return {"signal": "NO_DATA"}

    df_ltf = pipeline["df_ltf"]
    price = float(df_ltf["Close"].iloc[-1])
    candidates: list[dict] = pipeline.get("candidates") or []
    htf_bias: Bias = pipeline.get("htf_bias", Bias.NEUTRAL)

    reasons: list[str] = []
    if htf_bias != Bias.NEUTRAL:
        reasons.append(f"Context — HTF structural bias: **{htf_bias.value.upper()}**")
    val_sweeps = [s for s in (pipeline.get("htf_sweeps") or []) if s.validated]
    if val_sweeps:
        reasons.append(f"Context — **{len(val_sweeps)}** validated HTF liquidity sweep(s) recently.")

    at_zone = [c for c in candidates if c["phase"] == "AT_ZONE"]
    awaiting = [c for c in candidates if c["phase"] == "AWAITING_RETRACE"]

    at_zone_aligned = [c for c in at_zone if _aligned_with_bias(c, htf_bias)]
    pool = at_zone_aligned or at_zone

    direction, phase, verdict, model_name = "WAIT", "NO_SETUP", "WAIT", "—"
    entry = stop = target = price
    conf = 20.0
    take = False

    if pool:
        active = pool[0]
        direction, model_name = active["direction"], active["model"]
        entry, stop = active["entry_price"], active["stop_price"]
        risk = abs(entry - stop) if stop != entry else max(entry * 0.005, 1e-6)
        target = entry + risk * cfg.rr_ratio if direction == "LONG" else entry - risk * cfg.rr_ratio
        conf = 55.0
        if _aligned_with_bias(active, htf_bias):
            conf += 15
            reasons.append(f"Execution — **{model_name}** setup aligns with the HTF context bias.")
        else:
            reasons.append(f"Execution — **{model_name}** setup is counter to the HTF bias; treat with extra caution.")
        reasons.append(f"Confirmation/Execution — {active['notes']}")
        take = conf >= cfg.take_confidence_threshold
        phase = "EXECUTION_ZONE"
        verdict = f"{'TAKE' if take else 'WATCH'} {direction}"
    elif awaiting:
        awaiting_aligned = [c for c in awaiting if _aligned_with_bias(c, htf_bias)]
        best = (awaiting_aligned or awaiting)[0]
        direction, model_name = best["direction"], best["model"]
        entry, stop = best["entry_price"], best["stop_price"]
        conf = 35.0
        phase, verdict = "AWAITING_RETRACE", f"WATCH {direction}"
        reasons.append(f"Confirmation done via **{model_name}**, but price hasn't returned to the entry zone yet.")
        reasons.append(best["notes"])
    else:
        reasons.append("No qualifying Context → Confirmation → Execution setup found across the 5 models right now.")

    conf = round(max(15.0, min(92.0, conf)), 1)
    distance_to_entry_pct = round((entry - price) / price * 100, 2) if price else 0.0

    if entry:
        sl_pct = round(abs(entry - stop) / entry * 100, 2)
        tp_pct = round(abs(target - entry) / entry * 100, 2)
    else:
        sl_pct = tp_pct = 1.0

    hold = hold_for_tf(cfg.ltf, style="intraday")
    plan = make_trade_plan(
        direction=direction if take and direction in ("LONG", "SHORT") else "—",
        timeframe=cfg.ltf, stop_loss_pct=sl_pct, take_profit_pct=tp_pct,
        confidence_pct=conf, style="intraday",
        exit_rule="Exit if price closes back through the block/gap origin (structural invalidation).",
        max_hold_exit="Structure-based — exit if the HTF context bias flips before target is hit.",
    )

    return enrich_smc_live({
        "signal": direction if take else "NONE",
        "direction": direction, "take_trade": take, "verdict": verdict, "phase": phase,
        "model": model_name, "confidence_pct": conf, "sl_pct": sl_pct, "tp_pct": tp_pct,
        "entry_price": round(entry, 6), "stop_price": round(stop, 6), "target_price": round(target, 6),
        "current_price": round(price, 6), "distance_to_entry_pct": distance_to_entry_pct,
        "htf_bias": htf_bias.value.upper(), "rr_ratio": cfg.rr_ratio,
        "candidates": candidates, "reasons": reasons,
        "trade_plan": {**plan, "holding_period": hold},
    }, hold_duration=hold)


# ---------------------------------------------------------------------------
# Fetch + ticker/universe wrappers (same shape as scalp_smc_engine.py)
# ---------------------------------------------------------------------------

def fetch_ltf_data(
    ticker: str, market: str, cfg: SCBestConfig, *, groww_token: str = "", exchange: str = "NSE",
) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    df = fetch_data_for_gap_scan(ticker, cfg.ltf, market, groww_token, exchange, limit=cfg.lookback_bars)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < cfg.min_ltf_bars:
        df = normalize_ohlcv(fetch_ohlcv_yfinance(ticker, cfg.ltf, is_crypto=is_crypto, limit=cfg.lookback_bars, market=market))
    return df


def _candidate_history(candidates: list[dict], limit: int = 10) -> list[dict[str, Any]]:
    rows = []
    for c in candidates[:limit]:
        rows.append({
            "model": c["model"], "direction": c["direction"], "phase": c["phase"],
            "entry": c["entry_price"], "stop": c["stop_price"],
        })
    return rows


def analyze_ticker(
    ticker: str, market: str, *, cfg: SCBestConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or SCBestConfig()
    raw = fetch_ltf_data(ticker, market, cfg, groww_token=groww_token, exchange=exchange)
    if raw.empty:
        return {"ticker": ticker, "error": f"No {cfg.ltf} data."}

    pipeline = run_sc_best_pipeline(raw, cfg)
    if pipeline.get("error"):
        return {"ticker": ticker, "error": pipeline["error"]}

    live = evaluate_live_signal(pipeline, cfg)
    smc_cfg = _smc_config(cfg)
    return {
        "ticker": ticker, "market": market, "ltf": cfg.ltf,
        "htf_rule": smc_cfg.htf_rule, "mtf_rule": smc_cfg.mtf_rule,
        "bars_ltf": len(pipeline["df_ltf"]), "bars_htf": len(pipeline["df_htf"]),
        "last_close": float(pipeline["df_ltf"]["Close"].iloc[-1]),
        "htf_bias": pipeline["htf_bias"].value,
        "candidate_count": len(pipeline.get("candidates") or []),
        "candidate_history": _candidate_history(pipeline.get("candidates") or []),
        "live": live,
    }


def scan_universe(
    tickers: list[str], market: str, *, cfg: SCBestConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or SCBestConfig()
    results = []
    for ticker in tickers:
        try:
            results.append(analyze_ticker(ticker, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            results.append({"ticker": ticker, "error": str(exc)[:200]})

    for r in results:
        if r.get("error"):
            continue
        ltp = get_last_traded_price(r["ticker"], market, groww_token=groww_token, exchange=exchange)
        r["ltp"] = ltp
        if ltp.get("price") is not None:
            candle_close = r.get("last_close")
            r["last_close"] = ltp["price"]
            live = r.get("live")
            if live is not None:
                live.setdefault("reasons", []).insert(
                    0, f"LTP {ltp['price']:,.4g} (live quote) vs {cfg.ltf} candle close {candle_close:,.4g}.",
                )

    entries = [r for r in results if not r.get("error") and (r.get("live") or {}).get("take_trade")]
    watches = [
        r for r in results
        if not r.get("error") and not (r.get("live") or {}).get("take_trade")
        and (r.get("live") or {}).get("verdict", "").startswith("WATCH")
    ]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))
    watches.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market, "ltf": cfg.ltf, "results": results,
        "entries": entries, "watchlist": watches,
        "entry_count": len(entries), "watch_count": len(watches),
    }
