"""
golden_death_cross_engine.py
----------------------------
Golden & Death Cross — Pro Trade multi-ticker / multi-TF EMA crossover desk.

Golden cross: fast EMA crosses **above** slow EMA → bullish bias / LONG setups.
Death cross:  fast EMA crosses **below** slow EMA → bearish bias / SHORT setups.

Confirmation stack (all asset classes):
  · Swing Support / Resistance
  · RSI(14) zone filters
  · Bollinger Bands — at upper/lower extremes, require VWAP alignment
  · Commentary + Conf% / SL% / TP% trade setup + optional chart overlays

Research / education only — not financial advice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.indicators import add_bollinger_bands, add_vwap
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
    rsi as _rsi,
    sl_tp_pct,
)
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.smart_money_shared import hold_for_tf

logger = logging.getLogger(__name__)

STRATEGY_ID = "golden_death_cross"
STRATEGY_NAME = "Golden & Death Cross"

TIMEFRAME_OPTIONS = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1wk"]
FAST_EMA_CHOICES = [5, 9, 10, 12, 20, 21, 50]
SLOW_EMA_CHOICES = [20, 21, 26, 50, 55, 100, 200]

HOW_IT_WORKS = """
### How Golden & Death Cross works

| Event | Meaning |
|-------|---------|
| **Golden cross** | Fast EMA closes **above** slow EMA → **bullish** bias · look for LONG |
| **Death cross** | Fast EMA closes **below** slow EMA → **bearish** bias · look for SHORT |

**Confirmation stack**
1. **S/R** — prefer longs near/above support; shorts near/below resistance
2. **RSI(14)** — longs not overbought; shorts not oversold (block extremes)
3. **Bollinger** — if price hugs Upper/Lower BB, require **VWAP** alignment (long above VWAP near lower band; short below VWAP near upper band)
4. Fresh cross preferred for TAKE; holding after cross = WATCH / bias only

**Outputs:** commentary · % confidence · %SL · %TP · grade · chart overlays (EMAs · BB · VWAP · S/R)
""".strip()

RULES = [
    "Choose fast & slow EMA (classic 50/200; also 9/21, 12/26, etc.).",
    "Golden = fast crosses above slow → LONG bias; Death = fast crosses below slow → SHORT bias.",
    "Confirm with swing S/R, RSI zone, and BB extremes via VWAP.",
    "TAKE only when conf / RR pass; otherwise WATCH with commentary.",
]

PRO_TIPS = [
    "Classic golden/death uses 50 & 200 on daily — shorter pairs fire more often on intraday TFs.",
    "A cross into S/R with RSI mid-zone is higher quality than a cross into RSI extremes.",
    "At Bollinger extremes, trust the cross only when VWAP agrees with the direction.",
    "Multi-TF: same golden/death on a higher TF raises conviction.",
    "Trail with the slow EMA; invalidate on a close back through it against the trade.",
]

GOLDEN_DEATH_CROSS_AI_SYSTEM = pro_trade_ai_system(
    STRATEGY_NAME,
    "Golden/Death EMA crossover with S/R, RSI, Bollinger extremes + VWAP. "
    "Report bias, conf%, SL%, TP%, and plain-English commentary.",
)


@dataclass
class GoldenDeathCrossConfig:
    timeframe: str = "15m"
    lookback_bars: int = 300
    fast_ema: int = 50
    slow_ema: int = 200
    bb_period: int = 20
    bb_std: float = 2.0
    rsi_period: int = 14
    rsi_long_min: float = 40.0
    rsi_long_max: float = 70.0
    rsi_short_min: float = 30.0
    rsi_short_max: float = 60.0
    rsi_long_block: float = 78.0
    rsi_short_block: float = 22.0
    bb_edge_pct_b: float = 0.15  # within 15% of band edge = "at extreme"
    sr_lookback: int = 40
    require_fresh_cross: bool = True
    min_rr: float = 1.2
    sl_atr_mult: float = 0.4
    tp_atr_mult: float = 1.6
    take_confidence_threshold: float = 55.0
    min_bars: int = 80
    chart_bars: int = 120

    def __post_init__(self) -> None:
        f, s = int(self.fast_ema), int(self.slow_ema)
        if f >= s:
            # Keep a valid pair — bump slow if user inverted
            self.slow_ema = max(s, f + 1)
            self.fast_ema = f


def _r(x: float | None, n: int = 6) -> float | None:
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return None
    return round(float(x), n)


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=int(period), adjust=False).mean()


def _swing_sr(work: pd.DataFrame, lookback: int) -> tuple[float, float]:
    win = work.iloc[-max(10, lookback):]
    return float(win["high"].max()), float(win["low"].min())


def _pct_b(price: float, lower: float, upper: float) -> float | None:
    span = upper - lower
    if span <= 0:
        return None
    return (price - lower) / span


def _build_chart(work: pd.DataFrame, *, max_bars: int = 120) -> list[dict[str, Any]]:
    tail = work.iloc[-max_bars:]
    rows: list[dict[str, Any]] = []
    for ts, row in tail.iterrows():
        item: dict[str, Any] = {
            "time": str(ts),
            "open": _r(float(row["open"])),
            "high": _r(float(row["high"])),
            "low": _r(float(row["low"])),
            "close": _r(float(row["close"])),
            "volume": _r(float(row["volume"]), 0) if "volume" in row and pd.notna(row.get("volume")) else None,
        }
        for k in ("ema_fast", "ema_slow", "bb_upper", "bb_mid", "bb_lower", "vwap", "support", "resistance"):
            if k in row and pd.notna(row.get(k)):
                item[k] = _r(float(row[k]))
        rows.append(item)
    return rows


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: GoldenDeathCrossConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or GoldenDeathCrossConfig()
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
        "commentary": "",
    }

    try:
        raw = fetch_data_for_gap_scan(
            ticker, cfg.timeframe, market, groww_token, exchange, limit=int(cfg.lookback_bars),
        )
        df = normalize_ohlcv(raw)
    except Exception as exc:
        out["error"] = str(exc)[:240]
        return out

    need = max(cfg.min_bars, cfg.slow_ema + 5, cfg.bb_period + 5)
    if df is None or len(df) < need:
        out["error"] = f"Need ≥{need} bars; got {0 if df is None else len(df)}"
        return out

    work = df.copy()
    close = work["close"].astype(float)
    high = work["high"].astype(float)
    low = work["low"].astype(float)

    work["ema_fast"] = _ema(close, cfg.fast_ema)
    work["ema_slow"] = _ema(close, cfg.slow_ema)
    work = add_bollinger_bands(work, period=cfg.bb_period, std_dev=cfg.bb_std, col="close")
    upper_col = f"bb_upper_{cfg.bb_period}_{cfg.bb_std}"
    mid_col = f"bb_middle_{cfg.bb_period}_{cfg.bb_std}"
    lower_col = f"bb_lower_{cfg.bb_period}_{cfg.bb_std}"
    work["bb_upper"] = work[upper_col]
    work["bb_mid"] = work[mid_col]
    work["bb_lower"] = work[lower_col]
    try:
        work = add_vwap(work)
    except Exception:
        cv = close * work["volume"].astype(float).fillna(0)
        work["vwap"] = cv.cumsum() / work["volume"].astype(float).replace(0, np.nan).cumsum()

    work["rsi"] = _rsi(close, cfg.rsi_period)
    atr_series = _atr_ind(work, 14)

    resist, support = _swing_sr(work, cfg.sr_lookback)
    work["resistance"] = resist
    work["support"] = support

    i = len(work) - 1
    if i < 1 or pd.isna(work["ema_fast"].iloc[i]) or pd.isna(work["ema_slow"].iloc[i]):
        out["error"] = "EMAs not ready"
        return out
    if pd.isna(work["ema_fast"].iloc[i - 1]) or pd.isna(work["ema_slow"].iloc[i - 1]):
        out["error"] = "Need prior bar EMAs for cross"
        return out

    price = float(close.iloc[i])
    ef = float(work["ema_fast"].iloc[i])
    es = float(work["ema_slow"].iloc[i])
    pef = float(work["ema_fast"].iloc[i - 1])
    pes = float(work["ema_slow"].iloc[i - 1])
    rsi_v = float(work["rsi"].iloc[i]) if pd.notna(work["rsi"].iloc[i]) else None
    atr_v = float(atr_series.iloc[i]) if pd.notna(atr_series.iloc[i]) else 0.0
    bb_u = float(work["bb_upper"].iloc[i]) if pd.notna(work["bb_upper"].iloc[i]) else None
    bb_m = float(work["bb_mid"].iloc[i]) if pd.notna(work["bb_mid"].iloc[i]) else None
    bb_l = float(work["bb_lower"].iloc[i]) if pd.notna(work["bb_lower"].iloc[i]) else None
    vwap = float(work["vwap"].iloc[i]) if "vwap" in work.columns and pd.notna(work["vwap"].iloc[i]) else None

    golden = pef <= pes and ef > es
    death = pef >= pes and ef < es
    above = ef > es
    below = ef < es
    fresh = golden or death

    pct_b = _pct_b(price, bb_l, bb_u) if bb_l is not None and bb_u is not None else None
    at_lower_bb = pct_b is not None and pct_b <= cfg.bb_edge_pct_b
    at_upper_bb = pct_b is not None and pct_b >= (1.0 - cfg.bb_edge_pct_b)

    # Direction from cross / hold
    side: str | None = None
    event = "HOLD"
    if golden:
        side, event = "LONG", "GOLDEN_CROSS"
    elif death:
        side, event = "SHORT", "DEATH_CROSS"
    elif above and not cfg.require_fresh_cross:
        side, event = "LONG", "ABOVE_SLOW"
    elif below and not cfg.require_fresh_cross:
        side, event = "SHORT", "BELOW_SLOW"

    # RSI filters
    rsi_ok = True
    rsi_blocked = False
    if side == "LONG" and rsi_v is not None:
        if rsi_v >= cfg.rsi_long_block:
            rsi_blocked = True
            rsi_ok = False
        elif not (cfg.rsi_long_min <= rsi_v <= cfg.rsi_long_max):
            rsi_ok = False
    if side == "SHORT" and rsi_v is not None:
        if rsi_v <= cfg.rsi_short_block:
            rsi_blocked = True
            rsi_ok = False
        elif not (cfg.rsi_short_min <= rsi_v <= cfg.rsi_short_max):
            rsi_ok = False

    # S/R alignment
    mid_box = (resist + support) / 2.0 if resist > support else price
    sr_ok = True
    if side == "LONG":
        sr_ok = price >= support * 0.995 and price <= resist * 1.02
        # Prefer not hugging resistance on a fresh long without room
        room_up = resist > price
    else:
        room_up = True
    if side == "SHORT":
        sr_ok = price <= resist * 1.005 and price >= support * 0.98
        room_down = support < price
    else:
        room_down = True

    # BB extreme → VWAP confirmation
    vwap_ok = True
    vwap_needed = False
    if side == "LONG" and at_lower_bb:
        vwap_needed = True
        vwap_ok = vwap is not None and price >= vwap * 0.998
    elif side == "LONG" and at_upper_bb:
        # Long into upper band — weak unless still above VWAP and not blocked
        vwap_needed = True
        vwap_ok = vwap is not None and price >= vwap
    if side == "SHORT" and at_upper_bb:
        vwap_needed = True
        vwap_ok = vwap is not None and price <= vwap * 1.002
    elif side == "SHORT" and at_lower_bb:
        vwap_needed = True
        vwap_ok = vwap is not None and price <= vwap

    checks: list[dict[str, Any]] = [
        {
            "id": "golden",
            "label": f"Golden cross (EMA{cfg.fast_ema} ↑ EMA{cfg.slow_ema})",
            "passed": golden,
            "detail": f"prev fast {_r(pef)} / slow {_r(pes)} → {_r(ef)} / {_r(es)}",
        },
        {
            "id": "death",
            "label": f"Death cross (EMA{cfg.fast_ema} ↓ EMA{cfg.slow_ema})",
            "passed": death,
            "detail": f"prev fast {_r(pef)} / slow {_r(pes)} → {_r(ef)} / {_r(es)}",
        },
        {
            "id": "stack",
            "label": f"Fast vs slow stack",
            "passed": above if side == "LONG" else below if side == "SHORT" else above or below,
            "detail": f"EMA{cfg.fast_ema} {_r(ef)} · EMA{cfg.slow_ema} {_r(es)} · {'above' if above else 'below' if below else 'flat'}",
        },
        {
            "id": "sr",
            "label": "Support / Resistance context",
            "passed": bool(sr_ok and (room_up if side == "LONG" else room_down if side == "SHORT" else True)),
            "detail": f"R {_r(resist)} · S {_r(support)} · mid {_r(mid_box)}",
        },
        {
            "id": "rsi",
            "label": f"RSI({cfg.rsi_period}) zone",
            "passed": bool(rsi_ok and not rsi_blocked),
            "detail": f"RSI {_r(rsi_v, 1) if rsi_v is not None else '—'} · blocked={rsi_blocked}",
        },
        {
            "id": "bb_vwap",
            "label": "BB extreme → VWAP confirm",
            "passed": bool(vwap_ok) if vwap_needed else True,
            "detail": (
                f"%B {_r(pct_b, 3) if pct_b is not None else '—'} · VWAP {_r(vwap)} · "
                f"{'required' if vwap_needed else 'not at BB edge'}"
            ),
        },
    ]

    commentary_parts = [
        f"{ticker} on {cfg.timeframe}: EMA{cfg.fast_ema}/{cfg.slow_ema} — "
        + (
            "fresh **golden cross** (bullish)."
            if golden
            else "fresh **death cross** (bearish)."
            if death
            else f"fast is {'above' if above else 'below'} slow (no fresh cross)."
        ),
        f"Price {_r(price)} sits vs swing R {_r(resist)} / S {_r(support)}.",
    ]
    if rsi_v is not None:
        commentary_parts.append(f"RSI is {_r(rsi_v, 1)}.")
    if at_upper_bb:
        commentary_parts.append("Price is at the **upper Bollinger** — VWAP alignment matters for shorts (or caution on longs).")
    elif at_lower_bb:
        commentary_parts.append("Price is at the **lower Bollinger** — VWAP alignment matters for longs (or caution on shorts).")
    if vwap is not None:
        commentary_parts.append(f"VWAP {_r(vwap)} — price is {'above' if price >= vwap else 'below'} it.")
    commentary = " ".join(commentary_parts)

    out["ltp"] = _r(price)
    out["event"] = event
    out["metrics"] = {
        "fast_ema": cfg.fast_ema,
        "slow_ema": cfg.slow_ema,
        "ema_fast": _r(ef),
        "ema_slow": _r(es),
        "rsi": _r(rsi_v, 2),
        "atr": _r(atr_v),
        "bb_upper": _r(bb_u),
        "bb_mid": _r(bb_m),
        "bb_lower": _r(bb_l),
        "pct_b": _r(pct_b, 3),
        "vwap": _r(vwap),
        "support": _r(support),
        "resistance": _r(resist),
        "golden_cross": golden,
        "death_cross": death,
        "above_slow": above,
        "at_upper_bb": at_upper_bb,
        "at_lower_bb": at_lower_bb,
        "event": event,
    }
    out["checks"] = checks
    out["commentary"] = commentary
    out["plain_english"] = commentary
    out["chart_data"] = _build_chart(work, max_bars=cfg.chart_bars)
    out["chart_series"] = [
        {"key": "ema_fast", "label": f"EMA{cfg.fast_ema}", "color": "#38bdf8"},
        {"key": "ema_slow", "label": f"EMA{cfg.slow_ema}", "color": "#fbbf24"},
        {"key": "bb_upper", "label": "BB Upper", "color": "#94a3b8"},
        {"key": "bb_mid", "label": "BB Mid", "color": "#64748b"},
        {"key": "bb_lower", "label": "BB Lower", "color": "#94a3b8"},
        {"key": "vwap", "label": "VWAP", "color": "#a78bfa"},
    ]
    out["chart_levels"] = [
        {"price": _r(ef), "label": f"EMA{cfg.fast_ema}", "color": "#38bdf8"},
        {"price": _r(es), "label": f"EMA{cfg.slow_ema}", "color": "#fbbf24"},
        {"price": _r(resist), "label": "Resistance", "color": "#f87171"},
        {"price": _r(support), "label": "Support", "color": "#34d399"},
    ]
    if vwap is not None:
        out["chart_levels"].append({"price": _r(vwap), "label": "VWAP", "color": "#a78bfa"})

    from app.market_pulse.asset_class_config import attach_ticker_name
    attach_ticker_name(out)

    if side not in ("LONG", "SHORT") or atr_v <= 0:
        out["signal"] = "WATCH" if (above or below) else "WAIT"
        out["direction"] = "NONE"
        out["reason"] = commentary
        out["status"] = "bias_only"
        return out

    if cfg.require_fresh_cross and not fresh:
        out["signal"] = "WATCH"
        out["direction"] = side
        out["reason"] = f"Holding {'above' if above else 'below'} slow EMA — no fresh cross (WATCH). {commentary}"
        out["status"] = "hold_no_fresh_cross"
        return out

    if rsi_blocked:
        out["signal"] = "WATCH"
        out["direction"] = side
        out["reason"] = f"RSI extreme blocks entry. {commentary}"
        out["status"] = "rsi_block"
        return out

    if vwap_needed and not vwap_ok:
        out["signal"] = "WATCH"
        out["direction"] = side
        out["reason"] = f"At Bollinger extreme without VWAP confirmation. {commentary}"
        out["status"] = "vwap_block"
        return out

    is_long = side == "LONG"
    entry = price
    dir_key = side
    if is_long:
        struct_stop = min(support, es, float(low.iloc[-8:].min())) - cfg.sl_atr_mult * atr_v
        t1 = min(resist, entry + cfg.tp_atr_mult * atr_v) if resist > entry else entry + cfg.tp_atr_mult * atr_v
        t2 = entry + cfg.tp_atr_mult * 1.8 * atr_v
        if bb_m is not None and bb_m > entry:
            t1 = max(t1, bb_m)
    else:
        struct_stop = max(resist, es, float(high.iloc[-8:].max())) + cfg.sl_atr_mult * atr_v
        t1 = max(support, entry - cfg.tp_atr_mult * atr_v) if support < entry else entry - cfg.tp_atr_mult * atr_v
        t2 = entry - cfg.tp_atr_mult * 1.8 * atr_v
        if bb_m is not None and bb_m < entry:
            t1 = min(t1, bb_m)

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
        out["reason"] = f"{event} but RR {rr if rr is not None else 'n/a'} below floor {cfg.min_rr}. {commentary}"
        out["entry_price"] = _r(entry)
        out["stop_price"] = _r(stop) if stop else None
        out["target_price"] = _r(target) if target else None
        out["sl_pct"] = sl_pct
        out["tp_pct"] = tp_pct
        out["rr"] = rr
        out["status"] = "rr_low"
        return out

    score = ConfidenceScore(34.0, f"{event.replace('_', ' ').title()} on EMA{cfg.fast_ema}/{cfg.slow_ema}")
    score.add(fresh, 16, "Fresh crossover on the last closed bar", "No fresh cross")
    score.add(rsi_ok, 10, "RSI in tradeable zone", "RSI off-zone")
    score.add(sr_ok, 8, "S/R context supports the side", "S/R crowded against trade")
    score.add(vwap_ok if vwap_needed else True, 10, "VWAP confirms BB extreme", "VWAP fights BB extreme")
    score.add(not at_upper_bb if is_long else not at_lower_bb, 6, "Not hugging adverse BB extreme", "Hugging adverse BB")
    score.add(not stop_adjusted, 4, "Stop fits ATR band", "Stop ATR-adjusted")
    score.add(rr is not None and rr >= 1.5, 6, "RR ≥ 1.5", "RR modest")
    if vwap is not None:
        score.add(
            (is_long and price >= vwap) or (not is_long and price <= vwap),
            4,
            "Price on correct side of VWAP",
            "Price vs VWAP mixed",
        )

    confidence_pct, reasons = score.finalize()
    grade = quality_grade(confidence_pct, rr, liquidity_ok(None), stop_adjusted)
    take = confidence_pct >= cfg.take_confidence_threshold and (rsi_ok and not rsi_blocked) and (vwap_ok or not vwap_needed)

    plan = make_trade_plan(
        direction=side,
        timeframe=cfg.timeframe,
        stop_loss_pct=round(sl_pct or 0, 2),
        take_profit_pct=round(tp_pct or 0, 2),
        confidence_pct=confidence_pct,
        style="intraday" if cfg.timeframe not in ("1d", "1w", "1wk") else "swing",
        exit_rule=(
            f"{event}: SL {_r(stop)}; T1 {_r(target)}; trail with EMA{cfg.slow_ema}. "
            f"Invalidate on close back through EMA{cfg.slow_ema}."
        ),
        max_hold_exit=f"Typical hold ({hold_for_tf(cfg.timeframe)}); book partial near S/R or mid BB.",
    )

    action = "BUY" if is_long else "SELL"
    signal = "BULLISH" if is_long else "BEARISH"
    setup_reason = (
        f"{action}: {event.replace('_', ' ').title()} EMA{cfg.fast_ema}/{cfg.slow_ema} — "
        f"conf {confidence_pct:.0f}% · SL {sl_pct:.1f}% · TP {tp_pct:.1f}% · RR 1:{rr:g}"
    )
    full_commentary = (
        f"{commentary} Suggest **{action}** with stop {_r(stop)}, target {_r(target)}. "
        f"Risk {sl_pct:.1f}% · aim {tp_pct:.1f}% · confidence {confidence_pct:.0f}% (grade {grade})."
    )

    out.update({
        "take_trade": take,
        "direction": side,
        "signal": signal,
        "action": action,
        "status": "take" if take else "setup_low_conf",
        "reason": setup_reason,
        "commentary": full_commentary,
        "plain_english": full_commentary,
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
            "action": action,
            "signal": signal,
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
            "reason": setup_reason,
            "plain_english": full_commentary,
            "timeframe": cfg.timeframe,
            "event": event,
        },
        "trade_suggestion": {
            "action": action,
            "entry": _r(entry),
            "stop": _r(stop) if stop else None,
            "target": _r(target) if target else None,
            "target2": _r(t2),
            "sl_pct": sl_pct,
            "tp_pct": tp_pct,
            "confidence_pct": confidence_pct,
        },
        "pro_checklist": [
            f"EMA{cfg.fast_ema} / EMA{cfg.slow_ema} cross or stack",
            "Swing S/R mapped",
            "RSI not in block zone",
            "BB extreme uses VWAP confirm",
            "Trade setup with Conf% / SL% / TP%",
        ],
    })
    return out


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: GoldenDeathCrossConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
    timeframes: list[str] | None = None,
) -> dict[str, Any]:
    cfg = cfg or GoldenDeathCrossConfig()
    tfs = [t.strip() for t in (timeframes or [cfg.timeframe]) if t and str(t).strip()]
    if not tfs:
        tfs = [cfg.timeframe]

    results: list[dict[str, Any]] = []
    for t in tickers:
        for tf in tfs:
            try:
                results.append(
                    analyze_ticker(
                        t, market,
                        cfg=replace(cfg, timeframe=tf),
                        groww_token=groww_token,
                        exchange=exchange,
                    )
                )
            except Exception as exc:
                logger.debug("Golden/Death Cross failed %s %s: %s", t, tf, exc)
                results.append({
                    "ticker": t, "timeframe": tf, "market": market,
                    "error": str(exc)[:200], "strategy": STRATEGY_ID,
                })

    entries = [r for r in results if not r.get("error") and r.get("take_trade")]
    entries.sort(key=lambda x: -(x.get("confidence_pct") or 0))

    return {
        "strategy": STRATEGY_ID,
        "strategy_label": STRATEGY_NAME,
        "how_it_works": HOW_IT_WORKS,
        "rules": RULES,
        "pro_tips": PRO_TIPS,
        "market": market,
        "fast_ema": cfg.fast_ema,
        "slow_ema": cfg.slow_ema,
        "timeframes": tfs,
        "results": results,
        "entries": entries,
        "entry_count": len(entries),
        "scanned": len(results),
    }


def build_golden_death_cross_ai_prompt(result: dict[str, Any]) -> str:
    extra = []
    if result.get("event"):
        extra.append(f"Event: {result.get('event')}")
    if result.get("commentary"):
        extra.append(f"Commentary: {result.get('commentary')}")
    metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
    if metrics:
        extra.append(
            f"EMA{metrics.get('fast_ema')}/{metrics.get('slow_ema')}: "
            f"{metrics.get('ema_fast')} / {metrics.get('ema_slow')} · RSI {metrics.get('rsi')} · "
            f"VWAP {metrics.get('vwap')} · S {metrics.get('support')} · R {metrics.get('resistance')}"
        )
    return build_pro_trade_ai_context(result, engine_label=STRATEGY_NAME, extra_lines=extra or None)
