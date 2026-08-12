"""
ema5_9_crossover_engine.py
--------------------------
5 / 9 EMA Crossover — Pro Trade momentum strategy with BB / RSI / Volume filters.

Core rule:
  · EMA5 crosses **above** EMA9 → LONG bias (bullish stack)
  · EMA5 crosses **below** EMA9 → SHORT bias (bearish stack)

Confirmations:
  · Close ideally on the trade side of both EMAs (price confirms the cross)
  · Bollinger Bands — prefer room to the outer band
  · RSI(14) — momentum zone
  · Volume vs MA20 — expansion on the cross

Targets: Mid BB (T1) · outer band (T2)
Stop: beyond swing + EMA9 (ATR-sane)

Research / education only — not financial advice.
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
    ema as _ema,
    liquidity_ok,
    pro_trade_ai_system,
    quality_grade,
    rr_ratio,
    rsi as _rsi_ind,
    sl_tp_pct,
)
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.smart_money_shared import hold_for_tf

logger = logging.getLogger(__name__)

STRATEGY_ID = "ema5_9_crossover"
STRATEGY_NAME = "5/9 EMA Cross"

TIMEFRAME_OPTIONS = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1wk"]

HOW_IT_WORKS = """
### How 5/9 EMA Cross works

Classic **fast/slow EMA crossover**, filtered by **Bollinger Bands**, **RSI**, and **volume**.

| Side | Trigger | Price confirm | BB | RSI | Volume |
|------|---------|---------------|----|-----|--------|
| **LONG** | EMA5 **crosses above** EMA9 | Prefer close **above** both | Room under Upper BB | Prefer ~45–70 | Prefer vol **above** MA |
| **SHORT** | EMA5 **crosses below** EMA9 | Prefer close **below** both | Room above Lower BB | Prefer ~30–55 | Prefer vol **above** MA |

**Defaults:** EMA5 · EMA9 · BB(20, 2) · RSI(14) · Vol MA20

**Targets / risk**
- T1 = Mid BB · T2 = outer band in trade direction
- SL = beyond recent swing / other side of EMA9 (ATR-sane)
- Output: **% confidence · %SL · %TP**

**How to use**
1. Pick asset class + timeframes + tickers.
2. Scan — act on TAKE with a fresh 5/9 cross + confirming filters.
3. If EMA5 is already above/below EMA9 without a fresh cross → WATCH only (stack hold).
""".strip()

RULES = [
    "EMA5 crosses above EMA9 → LONG; below → SHORT.",
    "Prefer close on the trade side of both EMAs (price confirms the stack).",
    "BB(20,2): avoid chasing the outer band; T1 mid / T2 outer.",
    "RSI(14): long prefers mid-high momentum; short prefers mid-low.",
    "Volume vs MA20: expansion on the cross improves confidence.",
    "No fresh 5/9 cross = WATCH (holding a stack is not a new entry).",
    "Structural stop beyond swing / EMA9; ATR-sane SL/TP.",
]

EMA5_9_CROSSOVER_AI_SYSTEM = pro_trade_ai_system(
    STRATEGY_NAME,
    "EMA5/EMA9 crossover for direction; Bollinger mid/outer for targets; "
    "RSI momentum zone + volume expansion as confirmation; report conf% / SL% / TP%.",
)

PRO_TIPS = [
    "Enter on the cross bar close (or next open) — do not anticipate the EMA5/9 kiss.",
    "Best when close is already on the same side as the new stack (both EMAs).",
    "Volume expansion on the cross separates real flips from whipsaw chops.",
    "RSI > 75 on a bullish 5/9 cross is often a chase — size down or skip.",
    "Book partial at mid BB; trail remainder under/over EMA9 after T1.",
]


@dataclass
class Ema59CrossoverConfig:
    timeframe: str = "15m"
    lookback_bars: int = 300
    fast_period: int = 5
    slow_period: int = 9
    bb_period: int = 20
    bb_std: float = 2.0
    rsi_period: int = 14
    rsi_long_min: float = 42.0
    rsi_long_max: float = 72.0
    rsi_short_min: float = 28.0
    rsi_short_max: float = 58.0
    rsi_long_block: float = 78.0
    rsi_short_block: float = 22.0
    vol_ma_period: int = 20
    min_rr: float = 1.2
    sl_atr_mult: float = 0.4
    take_confidence_threshold: float = 55.0
    min_bars: int = 80
    chart_bars: int = 120
    require_volume_expand: bool = False
    require_fresh_cross: bool = True
    require_price_confirm: bool = True


def _r(x: float, n: int = 6) -> float:
    return round(float(x), n)


def _bb_cols(close: pd.Series, period: int, std_mult: float) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    return mid + std_mult * std, mid, mid - std_mult * std


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
        for k in ("bb_upper", "bb_mid", "bb_lower", "ema5", "ema9", "vol_ma"):
            if k in bar and pd.notna(bar.get(k)):
                row[k] = _r(float(bar[k]), 6)
        rows.append(row)
    return rows


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: Ema59CrossoverConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or Ema59CrossoverConfig()
    fast_p = int(cfg.fast_period)
    slow_p = int(cfg.slow_period)
    out: dict[str, Any] = {
        "ticker": ticker,
        "timeframe": cfg.timeframe,
        "strategy": STRATEGY_ID,
        "strategy_label": STRATEGY_NAME,
        "signal": "WAIT",
        "direction": "NONE",
        "take_trade": False,
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

    upper, mid, lower = _bb_cols(close, cfg.bb_period, cfg.bb_std)
    work["bb_upper"], work["bb_mid"], work["bb_lower"] = upper, mid, lower
    work["ema5"] = _ema(close, fast_p)
    work["ema9"] = _ema(close, slow_p)
    work["rsi"] = _rsi_ind(close, cfg.rsi_period)
    work["vol_ma"] = vol.rolling(cfg.vol_ma_period).mean()

    i = len(work) - 1
    if (
        i < 2
        or pd.isna(work["ema5"].iloc[i])
        or pd.isna(work["ema9"].iloc[i])
        or pd.isna(work["rsi"].iloc[i])
        or pd.isna(mid.iloc[i])
    ):
        out["error"] = "Indicators not ready"
        return out
    if pd.isna(work["ema5"].iloc[i - 1]) or pd.isna(work["ema9"].iloc[i - 1]):
        out["error"] = "Need prior bar EMA5/EMA9"
        return out

    price = float(close.iloc[i])
    ema5 = float(work["ema5"].iloc[i])
    ema9 = float(work["ema9"].iloc[i])
    prev_ema5 = float(work["ema5"].iloc[i - 1])
    prev_ema9 = float(work["ema9"].iloc[i - 1])
    rsi_v = float(work["rsi"].iloc[i])
    bb_u, bb_m, bb_l = float(upper.iloc[i]), float(mid.iloc[i]), float(lower.iloc[i])
    vol_now = float(vol.iloc[i]) if pd.notna(vol.iloc[i]) else None
    vol_ma = float(work["vol_ma"].iloc[i]) if pd.notna(work["vol_ma"].iloc[i]) else None
    vol_expand = vol_now is not None and vol_ma is not None and vol_now > vol_ma

    # Classic crossover: fast vs slow
    cross_up = prev_ema5 <= prev_ema9 and ema5 > ema9
    cross_down = prev_ema5 >= prev_ema9 and ema5 < ema9
    stack_bull = ema5 > ema9
    stack_bear = ema5 < ema9
    price_above_both = price > ema5 and price > ema9
    price_below_both = price < ema5 and price < ema9

    long_bb_ok = price < bb_u * 0.998
    short_bb_ok = price > bb_l * 1.002
    near_mid_long = price >= bb_m * 0.995
    near_mid_short = price <= bb_m * 1.005

    rsi_long_ok = cfg.rsi_long_min <= rsi_v <= cfg.rsi_long_max
    rsi_short_ok = cfg.rsi_short_min <= rsi_v <= cfg.rsi_short_max
    rsi_long_block = rsi_v >= cfg.rsi_long_block
    rsi_short_block = rsi_v <= cfg.rsi_short_block

    checks: list[dict[str, Any]] = [
        {
            "id": "cross_up",
            "label": f"EMA{fast_p} crossed above EMA{slow_p}",
            "passed": cross_up,
            "detail": (
                f"prev EMA{fast_p} {_r(prev_ema5)} / EMA{slow_p} {_r(prev_ema9)} → "
                f"{_r(ema5)} / {_r(ema9)}"
            ),
        },
        {
            "id": "cross_down",
            "label": f"EMA{fast_p} crossed below EMA{slow_p}",
            "passed": cross_down,
            "detail": (
                f"prev EMA{fast_p} {_r(prev_ema5)} / EMA{slow_p} {_r(prev_ema9)} → "
                f"{_r(ema5)} / {_r(ema9)}"
            ),
        },
        {
            "id": "stack_bull",
            "label": f"EMA{fast_p} above EMA{slow_p} (bull stack)",
            "passed": stack_bull,
            "detail": f"EMA{fast_p} {_r(ema5)} · EMA{slow_p} {_r(ema9)}",
        },
        {
            "id": "stack_bear",
            "label": f"EMA{fast_p} below EMA{slow_p} (bear stack)",
            "passed": stack_bear,
            "detail": f"EMA{fast_p} {_r(ema5)} · EMA{slow_p} {_r(ema9)}",
        },
        {
            "id": "price_above_both",
            "label": "Close above both EMAs",
            "passed": price_above_both,
            "detail": f"close {_r(price)} · EMA{fast_p} {_r(ema5)} · EMA{slow_p} {_r(ema9)}",
        },
        {
            "id": "price_below_both",
            "label": "Close below both EMAs",
            "passed": price_below_both,
            "detail": f"close {_r(price)} · EMA{fast_p} {_r(ema5)} · EMA{slow_p} {_r(ema9)}",
        },
        {
            "id": "bb_room_long",
            "label": "Not hugging Upper BB (long room)",
            "passed": long_bb_ok,
            "detail": f"U {_r(bb_u)} · mid {_r(bb_m)} · L {_r(bb_l)}",
        },
        {
            "id": "bb_room_short",
            "label": "Not hugging Lower BB (short room)",
            "passed": short_bb_ok,
            "detail": f"U {_r(bb_u)} · mid {_r(bb_m)} · L {_r(bb_l)}",
        },
        {
            "id": "rsi_long",
            "label": f"RSI in long zone ({cfg.rsi_long_min:g}–{cfg.rsi_long_max:g})",
            "passed": rsi_long_ok,
            "detail": f"RSI {_r(rsi_v, 1)}",
        },
        {
            "id": "rsi_short",
            "label": f"RSI in short zone ({cfg.rsi_short_min:g}–{cfg.rsi_short_max:g})",
            "passed": rsi_short_ok,
            "detail": f"RSI {_r(rsi_v, 1)}",
        },
        {
            "id": "vol_expand",
            "label": "Volume above MA20",
            "passed": bool(vol_expand),
            "detail": f"vol {_r(vol_now or 0, 0)} / MA {_r(vol_ma or 0, 0)}",
        },
    ]

    out["ltp"] = _r(price)
    out["metrics"] = {
        "ema5": _r(ema5),
        "ema9": _r(ema9),
        "fast_period": fast_p,
        "slow_period": slow_p,
        "bb_upper": _r(bb_u),
        "bb_mid": _r(bb_m),
        "bb_lower": _r(bb_l),
        "rsi": _r(rsi_v, 1),
        "vol_vs_ma": _r((vol_now / vol_ma) if vol_now and vol_ma else 0, 2),
        "cross_up": cross_up,
        "cross_down": cross_down,
        "stack_bull": stack_bull,
        "stack_bear": stack_bear,
        "price_above_both": price_above_both,
        "price_below_both": price_below_both,
    }
    out["checks"] = checks
    out["chart_data"] = _build_chart(work, max_bars=cfg.chart_bars)
    out["chart_series"] = [
        {"key": "bb_upper", "label": "BB Upper", "color": "#94a3b8"},
        {"key": "bb_mid", "label": "BB Mid", "color": "#38bdf8"},
        {"key": "bb_lower", "label": "BB Lower", "color": "#94a3b8"},
        {"key": "ema5", "label": f"EMA{fast_p}", "color": "#34d399"},
        {"key": "ema9", "label": f"EMA{slow_p}", "color": "#fbbf24"},
    ]
    out["chart_levels"] = [
        {"price": _r(ema5), "label": f"EMA{fast_p}", "color": "#34d399"},
        {"price": _r(ema9), "label": f"EMA{slow_p}", "color": "#fbbf24"},
        {"price": _r(bb_m), "label": "BB Mid", "color": "#38bdf8"},
    ]

    from app.market_pulse.asset_class_config import attach_ticker_name

    attach_ticker_name(out)

    direction: str | None = None
    if cross_up:
        if rsi_long_block:
            out["signal"] = "WATCH"
            out["status"] = "rsi_overbought"
            out["reason"] = (
                f"EMA{fast_p} crossed above EMA{slow_p} but RSI {_r(rsi_v, 1)} is chasing overbought — stand aside"
            )
            return out
        if cfg.require_volume_expand and not vol_expand:
            out["signal"] = "WATCH"
            out["status"] = "thin_volume"
            out["reason"] = f"Bullish 5/9 cross but volume is not expanding — wait for participation"
            return out
        if not long_bb_ok:
            out["signal"] = "WATCH"
            out["status"] = "bb_extreme"
            out["reason"] = "Bullish 5/9 cross into Upper BB — little room; wait for pullback"
            return out
        if cfg.require_price_confirm and not price_above_both:
            out["signal"] = "WATCH"
            out["status"] = "price_not_confirm"
            out["reason"] = "EMA5>EMA9 cross but close is not above both EMAs — wait for price confirm"
            return out
        direction = "LONG"
    elif cross_down:
        if rsi_short_block:
            out["signal"] = "WATCH"
            out["status"] = "rsi_oversold"
            out["reason"] = (
                f"EMA{fast_p} crossed below EMA{slow_p} but RSI {_r(rsi_v, 1)} is washed out — stand aside"
            )
            return out
        if cfg.require_volume_expand and not vol_expand:
            out["signal"] = "WATCH"
            out["status"] = "thin_volume"
            out["reason"] = "Bearish 5/9 cross but volume is not expanding — wait for participation"
            return out
        if not short_bb_ok:
            out["signal"] = "WATCH"
            out["status"] = "bb_extreme"
            out["reason"] = "Bearish 5/9 cross into Lower BB — little room; wait for bounce fade"
            return out
        if cfg.require_price_confirm and not price_below_both:
            out["signal"] = "WATCH"
            out["status"] = "price_not_confirm"
            out["reason"] = "EMA5<EMA9 cross but close is not below both EMAs — wait for price confirm"
            return out
        direction = "SHORT"
    elif stack_bull and not cfg.require_fresh_cross:
        if cfg.require_price_confirm and not price_above_both:
            out["signal"] = "WATCH"
            out["status"] = "stack_hold_no_price"
            out["reason"] = "Bull stack held but close not above both — WATCH"
            return out
        direction = "LONG"
    elif stack_bear and not cfg.require_fresh_cross:
        if cfg.require_price_confirm and not price_below_both:
            out["signal"] = "WATCH"
            out["status"] = "stack_hold_no_price"
            out["reason"] = "Bear stack held but close not below both — WATCH"
            return out
        direction = "SHORT"
    elif stack_bull:
        out["signal"] = "WATCH"
        out["status"] = "holding_bull_stack"
        out["reason"] = f"EMA{fast_p} already above EMA{slow_p} but no fresh cross this bar — WATCH only"
        return out
    elif stack_bear:
        out["signal"] = "WATCH"
        out["status"] = "holding_bear_stack"
        out["reason"] = f"EMA{fast_p} already below EMA{slow_p} but no fresh cross this bar — WATCH only"
        return out
    else:
        out["signal"] = "WAIT"
        out["reason"] = "No 5/9 EMA cross / EMAs flat"
        return out

    is_long = direction == "LONG"
    entry = price
    atr_series = _atr_ind(work, 14)
    atr_v = float(atr_series.iloc[i]) if pd.notna(atr_series.iloc[i]) else 0.0
    swing_low = float(low.iloc[-8:].min())
    swing_high = float(high.iloc[-8:].max())
    dir_key = "LONG" if is_long else "SHORT"

    if is_long:
        struct_stop = min(swing_low, ema9, bb_l) - cfg.sl_atr_mult * atr_v
        t1 = bb_m if bb_m > entry else entry + max(atr_v * 1.2, entry * 0.008)
        t2 = bb_u if bb_u > t1 else t1 + max(atr_v * 1.5, entry * 0.01)
    else:
        struct_stop = max(swing_high, ema9, bb_u) + cfg.sl_atr_mult * atr_v
        t1 = bb_m if bb_m < entry else entry - max(atr_v * 1.2, entry * 0.008)
        t2 = bb_l if bb_l < t1 else t1 - max(atr_v * 1.5, entry * 0.01)

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
        out["direction"] = direction
        out["reason"] = f"RR {rr if rr is not None else 'n/a'} below floor {cfg.min_rr}"
        out["entry_price"] = _r(entry)
        out["stop_price"] = _r(stop) if stop else None
        out["target_price"] = _r(target) if target else None
        out["sl_pct"] = sl_pct
        out["tp_pct"] = tp_pct
        out["rr"] = rr
        return out

    score = ConfidenceScore(38.0, "Fresh 5/9 EMA cross")
    score.add(cross_up if is_long else cross_down, 16, "Fresh EMA5/EMA9 crossover", "No fresh cross")
    score.add(
        (price_above_both if is_long else price_below_both),
        10,
        "Close confirms both EMAs",
        "Close not fully confirming stack",
    )
    score.add(vol_expand, 10, "Volume expanding vs MA20", "Thin volume on the cross")
    score.add(rsi_long_ok if is_long else rsi_short_ok, 10, "RSI in momentum zone", "RSI outside preferred zone")
    score.add(long_bb_ok if is_long else short_bb_ok, 8, "BB leaves room toward outer band", "Price near chase-side band")
    score.add(near_mid_long if is_long else near_mid_short, 4, "Price aligned with BB mid", "Away from mid BB")
    score.add(atr_v > 0, 4, "ATR available for stop sanity", "No ATR")
    score.add(not stop_adjusted, 4, "Stop fits ATR band", "Stop ATR-adjusted")

    confidence_pct, reasons = score.finalize()
    grade = quality_grade(confidence_pct, rr, liquidity_ok(None), stop_adjusted)
    take = confidence_pct >= cfg.take_confidence_threshold

    plan = make_trade_plan(
        direction=direction,
        timeframe=cfg.timeframe,
        stop_loss_pct=round(sl_pct or 0, 2),
        take_profit_pct=round(tp_pct or 0, 2),
        confidence_pct=confidence_pct,
        style="intraday" if cfg.timeframe not in ("1d", "1w", "1wk") else "swing",
        exit_rule=(
            f"5/9 EMA Cross: SL beyond structure ({_r(stop) if stop else '—'}); "
            f"T1 mid-band ({_r(t1)}); T2 outer ({_r(t2)}). "
            f"Invalidate on EMA{fast_p} re-cross against the trade (or close back through EMA{slow_p})."
        ),
        max_hold_exit=f"Typical hold ({hold_for_tf(cfg.timeframe)}); trail under/over EMA{slow_p} after T1.",
    )

    out.update({
        "take_trade": take,
        "direction": direction,
        "signal": "BULLISH" if is_long else "BEARISH",
        "action": "BUY" if is_long else "SELL",
        "status": "take" if take else "setup_low_conf",
        "reason": (
            f"{'BUY' if is_long else 'SELL'}: 5/9 EMA cross + BB/RSI/Vol — "
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
            "direction": direction,
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
                f"{'BUY' if is_long else 'SELL'}: 5/9 EMA cross · "
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
            f"{'Buy' if is_long else 'Sell'} on {ticker} ({cfg.timeframe}): EMA{fast_p} crossed "
            f"{'above' if is_long else 'below'} EMA{slow_p} "
            f"({'with expanding volume' if vol_expand else 'on quiet volume'}). "
            f"RSI {_r(rsi_v, 1)}; BB mid {_r(bb_m)}. "
            f"Risk {sl_pct:.1f}% · aim {tp_pct:.1f}% to mid-band · conf {confidence_pct:.0f}% (grade {grade}). "
            f"Invalidate on an opposite 5/9 re-cross."
        ),
        "pro_checklist": [
            f"Fresh EMA{fast_p}/EMA{slow_p} crossover",
            "Close confirms both EMAs",
            "BB room toward outer band",
            "RSI momentum zone (not extreme chase)",
            "Volume expansion preferred",
            f"SL beyond swing / EMA{slow_p}",
            "T1 mid BB · T2 outer band",
        ],
    })
    return out


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: Ema59CrossoverConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
    timeframes: list[str] | None = None,
) -> dict[str, Any]:
    cfg = cfg or Ema59CrossoverConfig()
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
                logger.exception("5/9 EMA Cross failed for %s %s", t, tf)
                results.append({
                    "ticker": t, "timeframe": tf, "strategy": STRATEGY_ID,
                    "error": str(exc)[:240], "signal": "WAIT", "take_trade": False,
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
            "fast_period": cfg.fast_period,
            "slow_period": cfg.slow_period,
            "bb_period": cfg.bb_period,
            "bb_std": cfg.bb_std,
            "rsi_period": cfg.rsi_period,
            "vol_ma_period": cfg.vol_ma_period,
            "min_rr": cfg.min_rr,
            "take_confidence_threshold": cfg.take_confidence_threshold,
            "require_volume_expand": cfg.require_volume_expand,
            "require_fresh_cross": cfg.require_fresh_cross,
            "require_price_confirm": cfg.require_price_confirm,
        },
        "results": results,
        "entry_count": len(actionable),
        "scanned": len(results),
        "ai_system_prompt": EMA5_9_CROSSOVER_AI_SYSTEM,
        "disclaimer": (
            "Research / education only — not financial advice. "
            "Prefer fresh 5/9 EMA crosses with volume and price confirmation; "
            "do not chase outer Bollinger extremes."
        ),
    }


def build_ema5_9_crossover_ai_prompt(result: dict[str, Any]) -> str:
    extra = [
        f"Direction: {result.get('direction')}",
        f"Conf {result.get('confidence_pct')}% · SL {result.get('sl_pct')}% · TP {result.get('tp_pct')}%",
        f"Grade: {result.get('grade')}",
        f"Reason: {result.get('reason')}",
        f"Checks: {result.get('checks')}",
        f"Pro checklist: {result.get('pro_checklist')}",
    ]
    return build_pro_trade_ai_context(result, engine_label=STRATEGY_NAME, extra_lines=extra)
