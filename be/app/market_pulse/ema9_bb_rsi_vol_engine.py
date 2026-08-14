"""
ema9_bb_rsi_vol_engine.py
-------------------------
N EMA Cross — Pro Trade momentum strategy with BB / RSI / Volume filters.

Core rule (N defaults to 9; also used for 5 EMA Cross):
  · Close crosses **above** N EMA → LONG bias
  · Close crosses **below** N EMA → SHORT bias

Confirmations (raise confidence; missing ones keep the row as WATCH / low-conf):
  · Bollinger Bands — prefer room to the outer band; avoid chasing the extreme band
  · RSI(14) — momentum zone (not washed-out shorts / not overbought longs)
  · Volume vs MA20 — expansion on the cross confirms participation

Targets: Mid BB (T1) · opposite / outer band (T2)
Stop: beyond swing + N EMA (ATR-sane)

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

# Legacy aliases (9 EMA Cross remains the default desk)
STRATEGY_ID = "ema9_bb_rsi_vol"
STRATEGY_NAME = "9 EMA Cross"

TIMEFRAME_OPTIONS = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1wk"]


def strategy_id_for(period: int) -> str:
    return f"ema{int(period)}_bb_rsi_vol"


def strategy_name_for(period: int) -> str:
    return f"{int(period)} EMA Cross"


def how_it_works_for(period: int) -> str:
    n = int(period)
    return f"""
### How {n} EMA Cross works

Find tickers that **just jumped above** (or **fell below**) the **{n} EMA** and have **already closed one candle** on that side.

| Side | Trigger |
|------|---------|
| **ABOVE / LONG** | Prior close ≤ {n} EMA · latest close **>** {n} EMA (fresh jump + closed above) |
| **BELOW / SHORT** | Prior close ≥ {n} EMA · latest close **<** {n} EMA (fresh jump + closed below) |

Optional filters: Bollinger room · RSI zone · volume expansion.

**Defaults:** EMA{n} · BB(20, 2) · RSI(14) · Vol MA20

**How to use**
1. Pick asset class · one or more tickers · one or more timeframes.
2. Choose EMA period (5 / 9 / 20 / 50 / 200).
3. Scan — TAKE when a fresh closed-candle jump above/below the EMA is confirmed.
""".strip()


def rules_for(period: int) -> list[str]:
    n = int(period)
    return [
        f"Just jumped above {n} EMA + closed candle above → LONG.",
        f"Just jumped below {n} EMA + closed candle below → SHORT.",
        "BB(20,2): avoid chasing the outer band; T1 mid / T2 outer.",
        "RSI(14): long prefers mid-high momentum; short prefers mid-low.",
        "Volume vs MA20: expansion on the jump improves confidence.",
        f"Already holding above/below {n} EMA without a fresh jump → WATCH only (unless hold mode).",
        f"Structural stop beyond swing / {n} EMA; ATR-sane SL/TP.",
    ]


def pro_tips_for(period: int) -> list[str]:
    n = int(period)
    return [
        f"Enter after the candle that closed across the {n} EMA — do not anticipate the touch.",
        "If price is already glued to the upper BB on a long jump, wait for a pullback to mid.",
        "Volume expansion on the jump separates real breaks from limp drifts.",
        "RSI > 75 on a long jump is often a chase — size down or skip.",
        f"Book partial at mid BB; trail remainder under/over the {n} EMA.",
        f"EMA200 needs more history bars — raise lookback if indicators stay blank.",
    ]


HOW_IT_WORKS = how_it_works_for(9)
RULES = rules_for(9)
PRO_TIPS = pro_tips_for(9)

EMA9_BB_RSI_VOL_AI_SYSTEM = pro_trade_ai_system(
    STRATEGY_NAME,
    "9 EMA close cross for direction; Bollinger mid/outer for targets; "
    "RSI momentum zone + volume expansion as confirmation; report conf% / SL% / TP%.",
)


def ai_system_for(period: int) -> str:
    name = strategy_name_for(period)
    n = int(period)
    return pro_trade_ai_system(
        name,
        f"{n} EMA close cross for direction; Bollinger mid/outer for targets; "
        "RSI momentum zone + volume expansion as confirmation; report conf% / SL% / TP%.",
    )


ALLOWED_EMA_PERIODS = (5, 9, 20, 50, 200)


@dataclass
class Ema9BbRsiVolConfig:
    timeframe: str = "15m"
    lookback_bars: int = 300
    ema_period: int = 9
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
    # above = jumped above only · below = jumped below only · both
    move_side: str = "both"

    def __post_init__(self) -> None:
        p = int(self.ema_period)
        if p not in ALLOWED_EMA_PERIODS:
            # nearest allowed
            self.ema_period = min(ALLOWED_EMA_PERIODS, key=lambda x: abs(x - p))
        else:
            self.ema_period = p
        side = str(self.move_side or "both").lower()
        if side in ("rise", "long", "up", "above"):
            side = "above"
        elif side in ("fall", "short", "down", "below"):
            side = "below"
        elif side not in ("above", "below", "both"):
            side = "both"
        self.move_side = side
        # Ensure enough history for slow EMAs
        need = max(int(self.min_bars), int(self.ema_period) * 3 + 40, 80)
        if int(self.lookback_bars) < need:
            self.lookback_bars = need
        if int(self.min_bars) < int(self.ema_period) + 10:
            self.min_bars = int(self.ema_period) + 10


def _r(x: float, n: int = 6) -> float:
    return round(float(x), n)


def _bb_cols(close: pd.Series, period: int, std_mult: float) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    return mid + std_mult * std, mid, mid - std_mult * std


def _build_chart(work: pd.DataFrame, *, max_bars: int, ema_key: str) -> list[dict[str, Any]]:
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
        for k in ("bb_upper", "bb_mid", "bb_lower", ema_key, "vol_ma"):
            if k in bar and pd.notna(bar.get(k)):
                row[k] = _r(float(bar[k]), 6)
        rows.append(row)
    return rows


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: Ema9BbRsiVolConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or Ema9BbRsiVolConfig()
    period = int(cfg.ema_period)
    sid = strategy_id_for(period)
    sname = strategy_name_for(period)
    tips = pro_tips_for(period)
    ema_key = f"ema{period}"
    ema_label = f"{period} EMA"

    out: dict[str, Any] = {
        "ticker": ticker,
        "timeframe": cfg.timeframe,
        "strategy": sid,
        "strategy_label": sname,
        "ema_period": period,
        "signal": "WAIT",
        "direction": "NONE",
        "take_trade": False,
        "checks": [],
        "metrics": {},
        "pro_tips": tips[:4],
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
    work[ema_key] = _ema(close, period)
    work["rsi"] = _rsi_ind(close, cfg.rsi_period)
    work["vol_ma"] = vol.rolling(cfg.vol_ma_period).mean()

    i = len(work) - 1
    if i < 2 or pd.isna(work[ema_key].iloc[i]) or pd.isna(work["rsi"].iloc[i]) or pd.isna(mid.iloc[i]):
        out["error"] = "Indicators not ready"
        return out
    if pd.isna(work[ema_key].iloc[i - 1]):
        out["error"] = f"Need prior bar EMA{period}"
        return out

    price = float(close.iloc[i])
    prev = float(close.iloc[i - 1])
    ema_v = float(work[ema_key].iloc[i])
    prev_ema = float(work[ema_key].iloc[i - 1])
    rsi_v = float(work["rsi"].iloc[i])
    bb_u, bb_m, bb_l = float(upper.iloc[i]), float(mid.iloc[i]), float(lower.iloc[i])
    vol_now = float(vol.iloc[i]) if pd.notna(vol.iloc[i]) else None
    vol_ma = float(work["vol_ma"].iloc[i]) if pd.notna(work["vol_ma"].iloc[i]) else None
    vol_expand = vol_now is not None and vol_ma is not None and vol_now > vol_ma

    cross_up = prev <= prev_ema and price > ema_v
    cross_down = prev >= prev_ema and price < ema_v
    above = price > ema_v
    below = price < ema_v
    # User wording: just jumped + already closed one candle on that side of the EMA
    jumped_above_closed = bool(cross_up and above)
    jumped_below_closed = bool(cross_down and below)
    pct_from_ema = ((price / ema_v) - 1.0) * 100.0 if ema_v else 0.0

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
            "id": "jumped_above_closed",
            "label": f"Just jumped above {ema_label} · closed candle above",
            "passed": jumped_above_closed,
            "detail": f"prev {_r(prev)} / EMA{period} {_r(prev_ema)} → close {_r(price)} / {_r(ema_v)}",
        },
        {
            "id": "jumped_below_closed",
            "label": f"Just fell below {ema_label} · closed candle below",
            "passed": jumped_below_closed,
            "detail": f"prev {_r(prev)} / EMA{period} {_r(prev_ema)} → close {_r(price)} / {_r(ema_v)}",
        },
        {
            "id": "cross_up",
            "label": f"Close crossed above {ema_label}",
            "passed": cross_up,
            "detail": f"prev {_r(prev)} / EMA{period} {_r(prev_ema)} → {_r(price)} / {_r(ema_v)}",
        },
        {
            "id": "cross_down",
            "label": f"Close crossed below {ema_label}",
            "passed": cross_down,
            "detail": f"prev {_r(prev)} / EMA{period} {_r(prev_ema)} → {_r(price)} / {_r(ema_v)}",
        },
        {
            "id": "above_ema",
            "label": f"Close above {ema_label}",
            "passed": above,
            "detail": f"close {_r(price)} · EMA{period} {_r(ema_v)} · {pct_from_ema:+.2f}%",
        },
        {
            "id": "below_ema",
            "label": f"Close below {ema_label}",
            "passed": below,
            "detail": f"close {_r(price)} · EMA{period} {_r(ema_v)} · {pct_from_ema:+.2f}%",
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
        ema_key: _r(ema_v),
        "ema": _r(ema_v),
        "ema_period": period,
        "pct_from_ema": _r(pct_from_ema, 2),
        "jumped_above_closed": jumped_above_closed,
        "jumped_below_closed": jumped_below_closed,
        "closed_above": above,
        "closed_below": below,
        "bb_upper": _r(bb_u),
        "bb_mid": _r(bb_m),
        "bb_lower": _r(bb_l),
        "rsi": _r(rsi_v, 1),
        "vol_vs_ma": _r((vol_now / vol_ma) if vol_now and vol_ma else 0, 2),
        "cross_up": cross_up,
        "cross_down": cross_down,
        "above_ema": above,
        "below_ema": below,
        f"above_ema{period}": above,
        f"below_ema{period}": below,
    }
    # Back-compat for 9 EMA panel
    if period == 9:
        out["metrics"]["ema9"] = _r(ema_v)
        out["metrics"]["above_ema9"] = above
        out["metrics"]["below_ema9"] = below
    out["checks"] = checks
    out["chart_data"] = _build_chart(work, max_bars=cfg.chart_bars, ema_key=ema_key)
    out["chart_series"] = [
        {"key": "bb_upper", "label": "BB Upper", "color": "#94a3b8"},
        {"key": "bb_mid", "label": "BB Mid", "color": "#38bdf8"},
        {"key": "bb_lower", "label": "BB Lower", "color": "#94a3b8"},
        {"key": ema_key, "label": f"EMA{period}", "color": "#fbbf24"},
    ]
    out["chart_levels"] = [
        {"price": _r(ema_v), "label": f"EMA{period}", "color": "#fbbf24"},
        {"price": _r(bb_m), "label": "BB Mid", "color": "#38bdf8"},
    ]

    from app.market_pulse.asset_class_config import attach_ticker_name

    attach_ticker_name(out)

    direction: str | None = None
    side_filter = str(cfg.move_side or "both").lower()
    if cross_up and side_filter == "below":
        out["signal"] = "WAIT"
        out["status"] = "side_filtered"
        out["reason"] = f"Jumped above {ema_label} but scan is set to Below only"
        out["jumped_above_closed"] = jumped_above_closed
        out["jumped_below_closed"] = jumped_below_closed
        out["pct_from_ema"] = _r(pct_from_ema, 2)
        return out
    if cross_down and side_filter == "above":
        out["signal"] = "WAIT"
        out["status"] = "side_filtered"
        out["reason"] = f"Fell below {ema_label} but scan is set to Above only"
        out["jumped_above_closed"] = jumped_above_closed
        out["jumped_below_closed"] = jumped_below_closed
        out["pct_from_ema"] = _r(pct_from_ema, 2)
        return out
    if cross_up:
        if rsi_long_block:
            out["signal"] = "WATCH"
            out["status"] = "rsi_overbought"
            out["reason"] = (
                f"Just jumped above {ema_label} and closed above, but RSI {_r(rsi_v, 1)} "
                "is chasing overbought — stand aside"
            )
            return out
        if cfg.require_volume_expand and not vol_expand:
            out["signal"] = "WATCH"
            out["status"] = "thin_volume"
            out["reason"] = (
                f"Just jumped above {ema_label} and closed above, but volume is not expanding — "
                "wait for participation"
            )
            return out
        if not long_bb_ok:
            out["signal"] = "WATCH"
            out["status"] = "bb_extreme"
            out["reason"] = (
                f"Just jumped above {ema_label} into Upper BB — little room; wait for pullback"
            )
            return out
        direction = "LONG"
    elif cross_down:
        if rsi_short_block:
            out["signal"] = "WATCH"
            out["status"] = "rsi_oversold"
            out["reason"] = (
                f"Just fell below {ema_label} and closed below, but RSI {_r(rsi_v, 1)} "
                "is washed out — stand aside"
            )
            return out
        if cfg.require_volume_expand and not vol_expand:
            out["signal"] = "WATCH"
            out["status"] = "thin_volume"
            out["reason"] = (
                f"Just fell below {ema_label} and closed below, but volume is not expanding — "
                "wait for participation"
            )
            return out
        if not short_bb_ok:
            out["signal"] = "WATCH"
            out["status"] = "bb_extreme"
            out["reason"] = (
                f"Just fell below {ema_label} into Lower BB — little room; wait for bounce fade"
            )
            return out
        direction = "SHORT"
    elif above and not cfg.require_fresh_cross and side_filter in ("above", "both"):
        direction = "LONG"
    elif below and not cfg.require_fresh_cross and side_filter in ("below", "both"):
        direction = "SHORT"
    elif above:
        out["signal"] = "WATCH"
        out["status"] = "holding_above"
        out["reason"] = (
            f"Closed above {ema_label} ({pct_from_ema:+.2f}%) but did not just jump this bar — WATCH only"
        )
        out["jumped_above_closed"] = False
        out["jumped_below_closed"] = False
        out["pct_from_ema"] = _r(pct_from_ema, 2)
        return out
    elif below:
        out["signal"] = "WATCH"
        out["status"] = "holding_below"
        out["reason"] = (
            f"Closed below {ema_label} ({pct_from_ema:+.2f}%) but did not just fall this bar — WATCH only"
        )
        out["jumped_above_closed"] = False
        out["jumped_below_closed"] = False
        out["pct_from_ema"] = _r(pct_from_ema, 2)
        return out
    else:
        out["signal"] = "WAIT"
        out["reason"] = f"No {ema_label} jump / flat on the EMA"
        return out

    out["jumped_above_closed"] = jumped_above_closed
    out["jumped_below_closed"] = jumped_below_closed
    out["pct_from_ema"] = _r(pct_from_ema, 2)

    is_long = direction == "LONG"
    entry = price
    atr_series = _atr_ind(work, 14)
    atr_v = float(atr_series.iloc[i]) if pd.notna(atr_series.iloc[i]) else 0.0
    swing_low = float(low.iloc[-8:].min())
    swing_high = float(high.iloc[-8:].max())
    dir_key = "LONG" if is_long else "SHORT"

    if is_long:
        struct_stop = min(swing_low, ema_v, bb_l) - cfg.sl_atr_mult * atr_v
        t1 = bb_m if bb_m > entry else entry + max(atr_v * 1.2, entry * 0.008)
        t2 = bb_u if bb_u > t1 else t1 + max(atr_v * 1.5, entry * 0.01)
    else:
        struct_stop = max(swing_high, ema_v, bb_u) + cfg.sl_atr_mult * atr_v
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

    score = ConfidenceScore(40.0, f"Fresh {ema_label} cross")
    score.add(cross_up if is_long else cross_down, 14, f"Fresh close cross of {ema_label}", "No fresh cross")
    score.add(vol_expand, 10, "Volume expanding vs MA20", "Thin volume on the cross")
    score.add(rsi_long_ok if is_long else rsi_short_ok, 10, "RSI in momentum zone", "RSI outside preferred zone")
    score.add(long_bb_ok if is_long else short_bb_ok, 8, "BB leaves room toward outer band", "Price near chase-side band")
    score.add(near_mid_long if is_long else near_mid_short, 6, "Price aligned with BB mid", "Away from mid BB")
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
            f"{ema_label} Cross: SL beyond structure ({_r(stop) if stop else '—'}); "
            f"T1 mid-band ({_r(t1)}); T2 outer ({_r(t2)}). "
            f"Invalidate on close back through {ema_label} against the trade."
        ),
        max_hold_exit=f"Typical hold ({hold_for_tf(cfg.timeframe)}); trail under/over {ema_label} after T1.",
    )

    out.update({
        "take_trade": take,
        "direction": direction,
        "signal": "BULLISH" if is_long else "BEARISH",
        "action": "BUY" if is_long else "SELL",
        "status": "take" if take else "setup_low_conf",
        "reason": (
            f"{'BUY' if is_long else 'SELL'}: {ema_label} cross + BB/RSI/Vol — "
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
                f"{'BUY' if is_long else 'SELL'}: {ema_label} cross · "
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
            f"{'Buy' if is_long else 'Sell'} on {ticker} ({cfg.timeframe}): close crossed "
            f"{'above' if is_long else 'below'} the {ema_label} "
            f"({'with expanding volume' if vol_expand else 'on quiet volume'}). "
            f"RSI {_r(rsi_v, 1)}; BB mid {_r(bb_m)}. "
            f"Risk {sl_pct:.1f}% · aim {tp_pct:.1f}% to mid-band · conf {confidence_pct:.0f}% (grade {grade}). "
            f"Invalidate on a close back through the {ema_label}."
        ),
        "pro_checklist": [
            f"Fresh {ema_label} close cross",
            "BB room toward outer band",
            "RSI momentum zone (not extreme chase)",
            "Volume expansion preferred",
            f"SL beyond swing / {ema_label}",
            "T1 mid BB · T2 outer band",
        ],
    })
    return out


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: Ema9BbRsiVolConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
    timeframes: list[str] | None = None,
) -> dict[str, Any]:
    cfg = cfg or Ema9BbRsiVolConfig()
    period = int(cfg.ema_period)
    sid = strategy_id_for(period)
    sname = strategy_name_for(period)
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
                logger.exception("%s failed for %s %s", sname, t, tf)
                results.append({
                    "ticker": t, "timeframe": tf, "strategy": sid,
                    "error": str(exc)[:240], "signal": "WAIT", "take_trade": False,
                })

    actionable = [r for r in results if r.get("take_trade")]
    return {
        "strategy": sid,
        "strategy_label": sname,
        "how_it_works": how_it_works_for(period),
        "rules": rules_for(period),
        "pro_tips": pro_tips_for(period),
        "timeframes": tfs,
        "ema_period": period,
        "move_side": str(cfg.move_side or "both"),
        "config": {
            "ema_period": period,
            "bb_period": cfg.bb_period,
            "bb_std": cfg.bb_std,
            "rsi_period": cfg.rsi_period,
            "vol_ma_period": cfg.vol_ma_period,
            "min_rr": cfg.min_rr,
            "take_confidence_threshold": cfg.take_confidence_threshold,
            "require_volume_expand": cfg.require_volume_expand,
            "require_fresh_cross": cfg.require_fresh_cross,
            "move_side": str(cfg.move_side or "both"),
        },
        "results": results,
        "entry_count": len(actionable),
        "scanned": len(results),
        "ai_system_prompt": ai_system_for(period),
        "disclaimer": (
            "Research / education only — not financial advice. "
            f"Prefer fresh {period} EMA crosses with volume; do not chase outer Bollinger extremes."
        ),
    }


def build_ema9_bb_rsi_vol_ai_prompt(result: dict[str, Any]) -> str:
    period = int(result.get("ema_period") or (result.get("metrics") or {}).get("ema_period") or 9)
    label = strategy_name_for(period)
    extra = [
        f"Direction: {result.get('direction')}",
        f"Conf {result.get('confidence_pct')}% · SL {result.get('sl_pct')}% · TP {result.get('tp_pct')}%",
        f"Grade: {result.get('grade')}",
        f"Reason: {result.get('reason')}",
        f"Checks: {result.get('checks')}",
        f"Pro checklist: {result.get('pro_checklist')}",
    ]
    return build_pro_trade_ai_context(result, engine_label=label, extra_lines=extra)
