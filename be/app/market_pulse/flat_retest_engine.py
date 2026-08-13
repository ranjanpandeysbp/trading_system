"""
flat_retest_engine.py
---------------------
Flat Retest — Pro Trade break / reject / retest strategy.

Focus: what happens AFTER flat candles (consolidation). Do not predict the next
candle — only fire when a completed sequence is already on the tape.

LONG sequence
  1. Flat consolidation forms (tight range → resistance = box high, support = box low)
  2. Resistance breaks + volume expands + close above resistance
  3. Price retests that broken resistance
  4. Resistance holds as support → LONG

SHORT sequence
  1. Same flat consolidation
  2. Resistance rejects + bearish candle + volume expands
  3. Price breaks the consolidation low
  4. Retest of the broken low fails (close back below) → SHORT

Multi-ticker · multi-timeframe. Research / education only — not financial advice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.pro_trade_shared import (
    ConfidenceScore,
    atr as _atr_ind,
    atr_sane_stop_target,
    build_pro_trade_ai_context,
    liquidity_ok,
    pro_trade_ai_system,
    quality_grade,
    rr_ratio,
    sl_tp_pct,
)
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.smart_money_shared import hold_for_tf

logger = logging.getLogger(__name__)

STRATEGY_ID = "flat_retest"
STRATEGY_NAME = "Flat Retest"

TIMEFRAME_OPTIONS = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1wk"]

# Setup phases surfaced to UI / AI
PHASE_NONE = "NO_FLAT"
PHASE_FLAT = "FLAT"
PHASE_BREAK_UP = "BREAK_RESISTANCE"
PHASE_RETEST_SUPPORT = "RETEST_AS_SUPPORT"
PHASE_LONG = "LONG"
PHASE_REJECT = "RESISTANCE_REJECT"
PHASE_BREAK_LOW = "BREAK_CONS_LOW"
PHASE_RETEST_FAIL = "RETEST_FAIL"
PHASE_SHORT = "SHORT"

HOW_IT_WORKS = """
### How Flat Retest works

The edge is **after** the flat candles — not predicting the next bar inside the box.

| Side | Sequence (all must complete on closed bars) |
|------|-----------------------------------------------|
| **LONG** | Flat box → **break resistance** (close above + volume expand) → **retest** resistance → it **holds as support** |
| **SHORT** | Flat box → **reject resistance** (bearish + volume expand) → **break consolidation low** → **retest fails** (close back below broken low) |

**Defaults:** flat window 6–10 bars · range ≤ 1.2× ATR · volume > Vol MA20 · retest touch within 0.15× ATR

**Targets / risk**
- LONG: SL below retest wick / box mid · T1 = breakout extension (ATR) · T2 = 2R
- SHORT: SL above failed-retest wick / broken low · T1 = ATR extension · T2 = 2R
- Output: **% confidence · %SL · %TP · phase**

**How to use**
1. Pick asset class + one or more timeframes + tickers.
2. Scan — act on TAKE when the full sequence is already complete.
3. Mid-sequence rows stay WATCH (e.g. broke resistance, waiting for retest hold).
""".strip()

RULES = [
    "Detect a flat consolidation first (tight range after equal-ish candles).",
    "LONG: break resistance + volume expand + close above → retest → resistance becomes support.",
    "SHORT: reject resistance + bearish + volume expand → break cons low → retest fails.",
    "Never invent the next candle — only signal on completed closed-bar sequences.",
    "Mid-sequence = WATCH; full sequence = TAKE when conf / RR pass.",
]

PRO_TIPS = [
    "Flat first — without a clear box, skips are correct.",
    "Volume on the break/reject separates real flips from limp drifts.",
    "LONG entry is the hold of old resistance as support — not the breakout chase.",
    "SHORT entry is the failed reclaim of the broken consolidation low — not the first rejection wick.",
    "Prefer the same sequence aligning on a higher TF for conviction.",
]

FLAT_RETEST_AI_SYSTEM = pro_trade_ai_system(
    STRATEGY_NAME,
    "Flat consolidation then LONG (break → retest hold as support) or SHORT "
    "(reject → break low → failed retest). Report phase, conf%, SL%, TP%. "
    "Do not invent unfinished sequence steps.",
)


@dataclass
class FlatRetestConfig:
    timeframe: str = "15m"
    lookback_bars: int = 300
    flat_min_bars: int = 6
    flat_max_bars: int = 12
    flat_atr_mult: float = 1.2
    flat_body_atr_max: float = 0.55
    vol_ma_period: int = 20
    vol_expand_mult: float = 1.05
    touch_atr_mult: float = 0.2
    hold_close_atr_buffer: float = 0.05
    break_lookback: int = 40
    min_rr: float = 1.2
    sl_atr_mult: float = 0.35
    tp_atr_mult: float = 1.6
    take_confidence_threshold: float = 55.0
    min_bars: int = 80
    chart_bars: int = 120


def _r(x: float, n: int = 6) -> float:
    return round(float(x), n)


def _is_flat_window(
    work: pd.DataFrame,
    start: int,
    end: int,
    atr_v: float,
    cfg: FlatRetestConfig,
) -> bool:
    """end is exclusive. Flat = tight high-low range vs ATR + mostly small bodies."""
    if end - start < cfg.flat_min_bars or atr_v <= 0:
        return False
    win = work.iloc[start:end]
    box_high = float(win["high"].max())
    box_low = float(win["low"].min())
    box_range = box_high - box_low
    if box_range > cfg.flat_atr_mult * atr_v:
        return False
    bodies = (win["close"] - win["open"]).abs()
    avg_body = float(bodies.mean())
    if avg_body > cfg.flat_body_atr_max * atr_v:
        return False
    # Prefer overlapping / equal-ish candles: most closes inside the box mid band
    mid = (box_high + box_low) / 2.0
    band = max(box_range * 0.55, atr_v * 0.15)
    inside = int(((win["close"] - mid).abs() <= band).sum())
    return inside >= max(3, int(0.55 * len(win)))


def _find_latest_flat(
    work: pd.DataFrame,
    atr_series: pd.Series,
    cfg: FlatRetestConfig,
    *,
    before_i: int,
) -> dict[str, Any] | None:
    """Search for the most recent flat box ending at or before before_i-1."""
    lo_len, hi_len = cfg.flat_min_bars, cfg.flat_max_bars
    best: dict[str, Any] | None = None
    search_from = max(lo_len, before_i - cfg.break_lookback - hi_len)
    for end in range(before_i, search_from, -1):
        atr_v = float(atr_series.iloc[end - 1]) if pd.notna(atr_series.iloc[end - 1]) else 0.0
        if atr_v <= 0:
            continue
        for length in range(hi_len, lo_len - 1, -1):
            start = end - length
            if start < 0:
                continue
            if not _is_flat_window(work, start, end, atr_v, cfg):
                continue
            win = work.iloc[start:end]
            box_high = float(win["high"].max())
            box_low = float(win["low"].min())
            cand = {
                "start": start,
                "end": end,  # exclusive — first bar after flat is end
                "resistance": box_high,
                "support": box_low,
                "mid": (box_high + box_low) / 2.0,
                "bars": length,
                "atr": atr_v,
            }
            # Prefer the flat that ends closest to current action
            if best is None or cand["end"] > best["end"]:
                best = cand
            break  # longest valid at this end is enough
        if best and best["end"] >= before_i - 2:
            break
    return best


def _vol_expand(vol: pd.Series, vol_ma: pd.Series, i: int, mult: float) -> bool:
    if pd.isna(vol.iloc[i]) or pd.isna(vol_ma.iloc[i]) or float(vol_ma.iloc[i]) <= 0:
        return False
    return float(vol.iloc[i]) >= mult * float(vol_ma.iloc[i])


def _build_chart(work: pd.DataFrame, *, max_bars: int) -> list[dict[str, Any]]:
    if work is None or work.empty:
        return []
    has_vol = "volume" in work.columns
    tail = work.iloc[-max_bars:]
    rows: list[dict[str, Any]] = []
    for idx, bar in tail.iterrows():
        row: dict[str, Any] = {
            "time": str(idx),
            "open": _r(float(bar["open"])),
            "high": _r(float(bar["high"])),
            "low": _r(float(bar["low"])),
            "close": _r(float(bar["close"])),
            "volume": _r(float(bar["volume"]), 2) if has_vol and pd.notna(bar.get("volume")) else None,
        }
        for k in ("vol_ma", "resistance", "support"):
            if k in bar and pd.notna(bar.get(k)):
                row[k] = _r(float(bar[k]), 6)
        rows.append(row)
    return rows


def _evaluate_sequences(
    work: pd.DataFrame,
    flat: dict[str, Any],
    cfg: FlatRetestConfig,
    *,
    i: int,
) -> dict[str, Any]:
    """Walk bars after the flat box and classify the best completed / in-progress path."""
    resist = float(flat["resistance"])
    support = float(flat["support"])
    atr_v = float(flat["atr"])
    touch = max(atr_v * cfg.touch_atr_mult, abs(resist) * 0.0004)
    hold_buf = max(atr_v * cfg.hold_close_atr_buffer, abs(resist) * 0.0002)

    vol = work["volume"] if "volume" in work.columns else pd.Series(np.nan, index=work.index)
    vol_ma = work["vol_ma"] if "vol_ma" in work.columns else pd.Series(np.nan, index=work.index)

    start_scan = int(flat["end"])
    if start_scan >= i:
        return {"phase": PHASE_FLAT, "side": None, "detail": "Flat box just formed — waiting for post-flat action"}

    # --- LONG path state ---
    break_up_i: int | None = None
    retest_long_i: int | None = None
    long_hold_i: int | None = None

    # --- SHORT path state ---
    reject_i: int | None = None
    break_low_i: int | None = None
    retest_fail_i: int | None = None

    for j in range(start_scan, i + 1):
        o = float(work["open"].iloc[j])
        h = float(work["high"].iloc[j])
        l = float(work["low"].iloc[j])
        c = float(work["close"].iloc[j])
        bull = c > o
        bear = c < o
        vol_ok = _vol_expand(vol, vol_ma, j, cfg.vol_expand_mult)

        # LONG: break resistance
        if break_up_i is None and c > resist + hold_buf and vol_ok:
            break_up_i = j

        # LONG: retest after break (low tags resistance zone, not a full reclaim fail)
        if break_up_i is not None and j > break_up_i and retest_long_i is None:
            if l <= resist + touch and l >= support - touch:
                retest_long_i = j
                # Same bar can also hold as support
                if c >= resist - hold_buf and (bull or c > o * 0.999):
                    long_hold_i = j

        # LONG: hold after retest armed
        if retest_long_i is not None and long_hold_i is None and j >= retest_long_i:
            if c >= resist - hold_buf and (bull or c >= resist):
                long_hold_i = j
            # Invalidation: close back deep inside box
            if c < support:
                break_up_i = None
                retest_long_i = None

        # SHORT: reject at resistance (before any successful breakout)
        if break_up_i is None and reject_i is None:
            near_res = h >= resist - touch
            closed_below = c < resist - hold_buf
            if near_res and closed_below and bear and vol_ok:
                reject_i = j

        # SHORT: break consolidation low after rejection
        if reject_i is not None and j > reject_i and break_low_i is None:
            if c < support - hold_buf:
                break_low_i = j

        # SHORT: retest of broken low fails (high tags broken support, close back below)
        if break_low_i is not None and j > break_low_i and retest_fail_i is None:
            if h >= support - touch and c < support - hold_buf:
                retest_fail_i = j
            # Invalidation: strong reclaim back above resistance
            if c > resist + hold_buf:
                reject_i = None
                break_low_i = None

    # Prefer completed signals on the latest bar when both somehow complete
    if long_hold_i is not None and long_hold_i == i:
        return {
            "phase": PHASE_LONG,
            "side": "LONG",
            "break_i": break_up_i,
            "retest_i": retest_long_i,
            "entry_i": long_hold_i,
            "detail": "Resistance broke → retested → held as support",
        }
    if retest_fail_i is not None and retest_fail_i == i:
        return {
            "phase": PHASE_SHORT,
            "side": "SHORT",
            "reject_i": reject_i,
            "break_i": break_low_i,
            "entry_i": retest_fail_i,
            "detail": "Resistance rejected → cons low broke → retest failed",
        }

    # Completed earlier in lookback but still valid context → treat as WATCH unless entry bar is recent
    if long_hold_i is not None and i - long_hold_i <= 2:
        return {
            "phase": PHASE_LONG,
            "side": "LONG",
            "break_i": break_up_i,
            "retest_i": retest_long_i,
            "entry_i": long_hold_i,
            "detail": "Resistance broke → retested → held as support",
        }
    if retest_fail_i is not None and i - retest_fail_i <= 2:
        return {
            "phase": PHASE_SHORT,
            "side": "SHORT",
            "reject_i": reject_i,
            "break_i": break_low_i,
            "entry_i": retest_fail_i,
            "detail": "Resistance rejected → cons low broke → retest failed",
        }

    # In-progress WATCH phases (most advanced wins)
    if break_low_i is not None:
        return {
            "phase": PHASE_BREAK_LOW,
            "side": None,
            "reject_i": reject_i,
            "break_i": break_low_i,
            "detail": "Cons low broken after resistance reject — waiting for failed retest",
        }
    if reject_i is not None:
        return {
            "phase": PHASE_REJECT,
            "side": None,
            "reject_i": reject_i,
            "detail": "Resistance rejected with volume — waiting for consolidation low break",
        }
    if retest_long_i is not None:
        return {
            "phase": PHASE_RETEST_SUPPORT,
            "side": None,
            "break_i": break_up_i,
            "retest_i": retest_long_i,
            "detail": "Retesting broken resistance — waiting for hold as support",
        }
    if break_up_i is not None:
        return {
            "phase": PHASE_BREAK_UP,
            "side": None,
            "break_i": break_up_i,
            "detail": "Resistance broken with volume — waiting for retest as support",
        }
    return {
        "phase": PHASE_FLAT,
        "side": None,
        "detail": "Flat consolidation mapped — waiting for break or reject",
    }


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: FlatRetestConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or FlatRetestConfig()
    out: dict[str, Any] = {
        "ticker": ticker,
        "timeframe": cfg.timeframe,
        "strategy": STRATEGY_ID,
        "strategy_label": STRATEGY_NAME,
        "signal": "WAIT",
        "direction": "NONE",
        "take_trade": False,
        "phase": PHASE_NONE,
        "checks": [],
        "metrics": {},
        "pro_tips": PRO_TIPS[:4],
    }

    try:
        raw = fetch_data_for_gap_scan(
            ticker, cfg.timeframe, market, groww_token, exchange, limit=int(cfg.lookback_bars),
        )
        df = normalize_ohlcv(raw)
    except Exception as exc:
        out["error"] = str(exc)[:240]
        return out

    if df is None or len(df) < cfg.min_bars:
        out["error"] = f"Need ≥{cfg.min_bars} bars; got {0 if df is None else len(df)}"
        return out

    work = df.copy()
    close = work["close"].astype(float)
    high = work["high"].astype(float)
    low = work["low"].astype(float)
    vol = work["volume"].astype(float) if "volume" in work.columns else pd.Series(np.nan, index=work.index)
    work["vol_ma"] = vol.rolling(cfg.vol_ma_period).mean()
    atr_series = _atr_ind(work, 14)

    i = len(work) - 1
    atr_v = float(atr_series.iloc[i]) if pd.notna(atr_series.iloc[i]) else 0.0
    if atr_v <= 0:
        out["error"] = "ATR not ready"
        return out

    flat = _find_latest_flat(work, atr_series, cfg, before_i=i)
    if flat is None:
        out["signal"] = "WAIT"
        out["phase"] = PHASE_NONE
        out["reason"] = "No flat consolidation found in lookback — sit out"
        out["checks"] = [{
            "id": "flat",
            "label": "Flat consolidation detected",
            "passed": False,
            "detail": f"Need {cfg.flat_min_bars}–{cfg.flat_max_bars} tight bars ≤ {cfg.flat_atr_mult:g}×ATR",
        }]
        out["ltp"] = _r(float(close.iloc[i]))
        out["chart_data"] = _build_chart(work, max_bars=cfg.chart_bars)
        out["chart_series"] = []
        out["chart_levels"] = []
        from app.market_pulse.asset_class_config import attach_ticker_name
        attach_ticker_name(out)
        return out

    resist = float(flat["resistance"])
    support = float(flat["support"])
    work["resistance"] = resist
    work["support"] = support

    seq = _evaluate_sequences(work, flat, cfg, i=i)
    phase = str(seq.get("phase") or PHASE_FLAT)
    side = seq.get("side")

    price = float(close.iloc[i])
    vol_now = float(vol.iloc[i]) if pd.notna(vol.iloc[i]) else None
    vol_ma = float(work["vol_ma"].iloc[i]) if pd.notna(work["vol_ma"].iloc[i]) else None
    vol_expand_now = vol_now is not None and vol_ma is not None and vol_now >= cfg.vol_expand_mult * vol_ma

    checks: list[dict[str, Any]] = [
        {
            "id": "flat",
            "label": "Flat consolidation (post-flat focus)",
            "passed": True,
            "detail": (
                f"{flat['bars']} bars · R {_r(resist)} · S {_r(support)} · "
                f"range {_r(resist - support)}"
            ),
        },
        {
            "id": "break_resistance",
            "label": "Resistance broke + volume + close above",
            "passed": bool(side == "LONG" or phase in {PHASE_BREAK_UP, PHASE_RETEST_SUPPORT, PHASE_LONG}),
            "detail": seq.get("detail", ""),
        },
        {
            "id": "retest_as_support",
            "label": "Retest: resistance becoming support",
            "passed": bool(side == "LONG" or phase in {PHASE_RETEST_SUPPORT, PHASE_LONG}),
            "detail": f"phase={phase}",
        },
        {
            "id": "long_hold",
            "label": "LONG: retest held as support",
            "passed": side == "LONG",
            "detail": "Completed LONG sequence" if side == "LONG" else "Not complete",
        },
        {
            "id": "reject_resistance",
            "label": "Resistance reject + bearish + volume",
            "passed": bool(
                seq.get("reject_i") is not None
                or phase in {PHASE_REJECT, PHASE_BREAK_LOW, PHASE_RETEST_FAIL, PHASE_SHORT}
            ),
            "detail": seq.get("detail", ""),
        },
        {
            "id": "break_cons_low",
            "label": "Consolidation low broken",
            "passed": bool(side == "SHORT" or phase in {PHASE_BREAK_LOW, PHASE_RETEST_FAIL, PHASE_SHORT}),
            "detail": f"support {_r(support)}",
        },
        {
            "id": "retest_fail",
            "label": "SHORT: retest failed",
            "passed": side == "SHORT",
            "detail": "Completed SHORT sequence" if side == "SHORT" else "Not complete",
        },
        {
            "id": "vol_expand",
            "label": f"Volume ≥ {cfg.vol_expand_mult:g}× MA{cfg.vol_ma_period}",
            "passed": bool(vol_expand_now),
            "detail": f"vol {_r(vol_now or 0, 0)} / MA {_r(vol_ma or 0, 0)}",
        },
    ]

    out["ltp"] = _r(price)
    out["phase"] = phase
    out["metrics"] = {
        "resistance": _r(resist),
        "support": _r(support),
        "flat_bars": int(flat["bars"]),
        "flat_range": _r(resist - support),
        "atr": _r(atr_v),
        "vol_vs_ma": _r((vol_now / vol_ma) if vol_now and vol_ma else 0, 2),
        "phase": phase,
        "sequence": seq.get("detail"),
    }
    out["checks"] = checks
    out["chart_data"] = _build_chart(work, max_bars=cfg.chart_bars)
    out["chart_series"] = [
        {"key": "resistance", "label": "Resistance", "color": "#f87171"},
        {"key": "support", "label": "Support", "color": "#34d399"},
    ]
    out["chart_levels"] = [
        {"price": _r(resist), "label": "Resistance", "color": "#f87171"},
        {"price": _r(support), "label": "Cons low", "color": "#34d399"},
        {"price": _r(float(flat["mid"])), "label": "Box mid", "color": "#94a3b8"},
    ]

    from app.market_pulse.asset_class_config import attach_ticker_name
    attach_ticker_name(out)

    if side not in ("LONG", "SHORT"):
        out["signal"] = "WATCH" if phase != PHASE_NONE else "WAIT"
        out["status"] = phase.lower()
        out["reason"] = str(seq.get("detail") or f"Phase {phase} — sequence incomplete")
        out["direction"] = "NONE"
        return out

    is_long = side == "LONG"
    entry = price
    dir_key = "LONG" if is_long else "SHORT"
    swing_low = float(low.iloc[-8:].min())
    swing_high = float(high.iloc[-8:].max())

    if is_long:
        struct_stop = min(swing_low, support, float(work["low"].iloc[seq.get("retest_i") or i])) - cfg.sl_atr_mult * atr_v
        t1 = entry + cfg.tp_atr_mult * atr_v
        t2 = entry + cfg.tp_atr_mult * 1.8 * atr_v
    else:
        struct_stop = max(swing_high, support, float(work["high"].iloc[seq.get("entry_i") or i])) + cfg.sl_atr_mult * atr_v
        t1 = entry - cfg.tp_atr_mult * atr_v
        t2 = entry - cfg.tp_atr_mult * 1.8 * atr_v

    stop, target, stop_adjusted = atr_sane_stop_target(dir_key, entry, struct_stop, t1, atr_v)
    sl_pct, tp_pct = sl_tp_pct(dir_key, entry, stop, target)
    rr = rr_ratio(sl_pct, tp_pct)
    if rr is not None and rr < cfg.min_rr:
        stop2, target2, adj2 = atr_sane_stop_target(dir_key, entry, struct_stop, t2, atr_v)
        sl2, tp2 = sl_tp_pct(dir_key, entry, stop2, target2)
        rr2 = rr_ratio(sl2, tp2)
        if rr2 is not None and (rr is None or rr2 >= rr):
            stop, target, stop_adjusted = stop2, target2, adj2
            sl_pct, tp_pct, rr = sl2, tp2, rr2

    if rr is None or rr < cfg.min_rr:
        out["signal"] = "WATCH"
        out["direction"] = side
        out["phase"] = phase
        out["reason"] = f"Sequence complete but RR {rr if rr is not None else 'n/a'} below floor {cfg.min_rr}"
        out["entry_price"] = _r(entry)
        out["stop_price"] = _r(stop) if stop else None
        out["target_price"] = _r(target) if target else None
        out["sl_pct"] = sl_pct
        out["tp_pct"] = tp_pct
        out["rr"] = rr
        return out

    score = ConfidenceScore(36.0, "Completed post-flat retest sequence")
    score.add(True, 14, seq.get("detail") or "Sequence complete", None)
    score.add(vol_expand_now or True, 8, "Volume participated on key bar", "Thin volume")
    score.add(flat["bars"] >= cfg.flat_min_bars, 8, f"Flat box {flat['bars']} bars", "Short flat")
    score.add((resist - support) <= cfg.flat_atr_mult * atr_v, 6, "Tight consolidation range", "Wide box")
    score.add(atr_v > 0, 4, "ATR available", "No ATR")
    score.add(not stop_adjusted, 4, "Stop fits ATR band", "Stop ATR-adjusted")
    score.add(rr is not None and rr >= 1.5, 6, "RR ≥ 1.5", "RR modest")

    confidence_pct, reasons = score.finalize()
    grade = quality_grade(confidence_pct, rr, liquidity_ok(None), stop_adjusted)
    take = confidence_pct >= cfg.take_confidence_threshold

    plan = make_trade_plan(
        direction=side,
        timeframe=cfg.timeframe,
        stop_loss_pct=round(sl_pct or 0, 2),
        take_profit_pct=round(tp_pct or 0, 2),
        confidence_pct=confidence_pct,
        style="intraday" if cfg.timeframe not in ("1d", "1w", "1wk") else "swing",
        exit_rule=(
            f"Flat Retest {side}: SL {_r(stop) if stop else '—'}; T1 {_r(t1)}; T2 {_r(t2)}. "
            + (
                "Invalidate on close back below old resistance / box mid."
                if is_long
                else "Invalidate on close back above broken consolidation low."
            )
        ),
        max_hold_exit=f"Typical hold ({hold_for_tf(cfg.timeframe)}); trail after T1.",
    )

    out.update({
        "take_trade": take,
        "direction": side,
        "signal": "BULLISH" if is_long else "BEARISH",
        "action": "BUY" if is_long else "SELL",
        "status": "take" if take else "setup_low_conf",
        "phase": phase,
        "reason": (
            f"{'BUY' if is_long else 'SELL'}: Flat Retest — {seq.get('detail')} — "
            f"conf {confidence_pct:.0f}% · SL {sl_pct:.1f}% · TP {tp_pct:.1f}% · RR 1:{rr:g}"
        ),
        "entry_price": _r(entry),
        "stop_price": _r(stop) if stop else None,
        "target_price": _r(target) if target else None,
        "target2_price": _r(t2),
        "sl_pct": sl_pct,
        "tp_pct": tp_pct,
        "rr": rr,
        "confidence_pct": confidence_pct,
        "confidence_reasons": reasons,
        "grade": grade,
        "trade_plan": plan,
        "trade_setup": {
            "direction": side,
            "action": "BUY" if is_long else "SELL",
            "signal": "BULLISH" if is_long else "BEARISH",
            "entry_price": _r(entry),
            "stop_price": _r(stop) if stop else None,
            "target_price": _r(target) if target else None,
            "sl_pct": sl_pct,
            "tp_pct": tp_pct,
            "rr": rr,
            "confidence_pct": confidence_pct,
            "confidence_reasons": reasons,
            "grade": grade,
            "take_trade": take,
            "reason": (
                f"{'BUY' if is_long else 'SELL'}: Flat Retest · "
                f"conf {confidence_pct:.0f}% · SL {sl_pct:.1f}% · TP {tp_pct:.1f}%"
            ),
            "plain_english": (
                f"Risk {sl_pct:.1f}% to stop · aim {tp_pct:.1f}% to T1 · "
                f"confidence {confidence_pct:.0f}% (grade {grade})."
            ),
            "timeframe": cfg.timeframe,
        },
        "trade_suggestion": {
            "action": "BUY" if is_long else "SELL",
            "entry": _r(entry),
            "stop": _r(stop) if stop else None,
            "target": _r(target) if target else None,
            "target2": _r(t2),
            "sl_pct": sl_pct,
            "tp_pct": tp_pct,
            "confidence_pct": confidence_pct,
        },
        "plain_english": (
            f"{'Buy' if is_long else 'Sell'} on {ticker} ({cfg.timeframe}): after flat candles, "
            f"{seq.get('detail')}. Box R {_r(resist)} / S {_r(support)}. "
            f"Risk {sl_pct:.1f}% · aim {tp_pct:.1f}% · conf {confidence_pct:.0f}% (grade {grade}). "
            "Do not chase unfinished sequences."
        ),
        "pro_checklist": [
            "Flat consolidation mapped",
            "Post-flat action (break or reject) with volume",
            "Retest completed (hold as support OR failed reclaim)",
            "No next-candle prediction — sequence already on tape",
            "SL beyond structure · T1 ATR extension",
        ],
    })
    return out


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: FlatRetestConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
    timeframes: list[str] | None = None,
) -> dict[str, Any]:
    cfg = cfg or FlatRetestConfig()
    tfs = [t.strip() for t in (timeframes or [cfg.timeframe]) if t and str(t).strip()]
    if not tfs:
        tfs = [cfg.timeframe]

    results: list[dict[str, Any]] = []
    for t in tickers:
        for tf in tfs:
            try:
                local = replace(cfg, timeframe=tf)
                results.append(
                    analyze_ticker(t, market, cfg=local, groww_token=groww_token, exchange=exchange)
                )
            except Exception as exc:
                logger.exception("Flat Retest failed for %s %s", t, tf)
                results.append({
                    "ticker": t, "timeframe": tf, "strategy": STRATEGY_ID,
                    "error": str(exc)[:240], "signal": "WAIT", "take_trade": False,
                    "phase": PHASE_NONE,
                })

    actionable = [r for r in results if r.get("take_trade")]
    return {
        "strategy": STRATEGY_ID,
        "strategy_label": STRATEGY_NAME,
        "how_it_works": HOW_IT_WORKS,
        "rules": RULES,
        "pro_tips": PRO_TIPS,
        "timeframes": tfs,
        "config": {
            "flat_min_bars": cfg.flat_min_bars,
            "flat_max_bars": cfg.flat_max_bars,
            "flat_atr_mult": cfg.flat_atr_mult,
            "vol_ma_period": cfg.vol_ma_period,
            "vol_expand_mult": cfg.vol_expand_mult,
            "min_rr": cfg.min_rr,
            "take_confidence_threshold": cfg.take_confidence_threshold,
        },
        "results": results,
        "entry_count": len(actionable),
        "scanned": len(results),
        "ai_system_prompt": FLAT_RETEST_AI_SYSTEM,
        "disclaimer": (
            "Research / education only — not financial advice. "
            "Trade only completed post-flat sequences — never the next candle inside the box."
        ),
    }


def build_flat_retest_ai_prompt(result: dict[str, Any]) -> str:
    extra = [
        f"Phase: {result.get('phase')}",
        f"Direction: {result.get('direction')}",
        f"Conf {result.get('confidence_pct')}% · SL {result.get('sl_pct')}% · TP {result.get('tp_pct')}%",
        f"Grade: {result.get('grade')}",
        f"Reason: {result.get('reason')}",
        f"Checks: {result.get('checks')}",
        f"Pro checklist: {result.get('pro_checklist')}",
    ]
    return build_pro_trade_ai_context(result, engine_label=STRATEGY_NAME, extra_lines=extra)
