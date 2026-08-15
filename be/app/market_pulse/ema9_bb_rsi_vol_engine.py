"""
ema9_bb_rsi_vol_engine.py
-------------------------
N EMA Cross — Pro Trade BB / RSI eligibility desk (EMA for structure).

Eligibility:
  · LONG  — price near Lower Bollinger Band AND RSI < 35
  · SHORT — price at Upper Bollinger Band AND RSI > 65
  · WAIT  — price at Middle Bollinger Band (or neither outer setup)

On every suggested trade, classify the last ~1000 bars as **upward** or **descent**
(sideways if flat) and surface that phase in the plan / confidence.

EMA N (5/9/20/50/200) is used for structure, stops, and optional fresh-cross boost.
Targets: Mid BB (T1) · opposite / outer band (T2)

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
ALLOWED_EMA_PERIODS = (5, 9, 20, 50, 200)


def strategy_id_for(period: int) -> str:
    return f"ema{int(period)}_bb_rsi_vol"


def strategy_name_for(period: int) -> str:
    return f"{int(period)} EMA Cross"


def how_it_works_for(period: int) -> str:
    n = int(period)
    return f"""
### How {n} EMA Cross works

Eligibility is driven by **Bollinger + RSI**. EMA{n} is used for structure / stops / optional cross boost.

| Side | Eligible when |
|------|----------------|
| **LONG** | Price **near Lower BB** · RSI **< 35** |
| **SHORT** | Price **at Upper BB** · RSI **> 65** |
| **WAIT** | Price **at Middle BB** (or no outer setup) |

Every suggested trade also reports the **last ~1000 bars phase**: upward vs descent (or sideways).

**Defaults:** EMA{n} · BB(20, 2) · RSI(14) · phase lookback 1000 bars

**How to use**
1. Pick asset class · one or more tickers · one or more timeframes.
2. Choose EMA period (5 / 9 / 20 / 50 / 200) for structure.
3. Scan — TAKE only on Lower-BB+RSI<35 (long) or Upper-BB+RSI>65 (short); mid-band = wait.
""".strip()


def rules_for(period: int) -> list[str]:
    n = int(period)
    return [
        "LONG only when price is near Lower BB and RSI < 35.",
        "SHORT only when price is at Upper BB and RSI > 65.",
        "Price at Middle BB → WAIT (no trade).",
        "On every suggestion, classify last ~1000 bars as upward or descent phase.",
        f"EMA{n}: structure / stop / optional fresh-cross confidence boost.",
        "T1 = mid BB · T2 = outer band · SL beyond swing / EMA (ATR-sane).",
        "Volume expansion preferred but optional.",
    ]


def pro_tips_for(period: int) -> list[str]:
    n = int(period)
    return [
        "Lower BB + RSI < 35 is a mean-reversion long — prefer it when the 1000-bar phase is still upward.",
        "Upper BB + RSI > 65 is a fade short — prefer it when the 1000-bar phase is already in descent.",
        "If price sits on the middle band, stand aside — no edge until an outer band extreme.",
        f"Use EMA{n} for the stop / trail, not as the primary entry trigger.",
        "Book partial at mid BB; trail remainder with the EMA.",
        "Raise lookback to ≥1100 bars so the 1000-bar phase has enough history.",
    ]


HOW_IT_WORKS = how_it_works_for(9)
RULES = rules_for(9)
PRO_TIPS = pro_tips_for(9)

EMA9_BB_RSI_VOL_AI_SYSTEM = pro_trade_ai_system(
    STRATEGY_NAME,
    "Long only near Lower BB with RSI<35; short only at Upper BB with RSI>65; "
    "mid BB = wait; report 1000-bar upward/descent phase; EMA for structure; conf% / SL% / TP%.",
)


def ai_system_for(period: int) -> str:
    name = strategy_name_for(period)
    n = int(period)
    return pro_trade_ai_system(
        name,
        f"Long only near Lower BB with RSI<35; short only at Upper BB with RSI>65; "
        f"mid BB = wait; report 1000-bar upward/descent phase; EMA{n} for structure; "
        "conf% / SL% / TP%.",
    )


@dataclass
class Ema9BbRsiVolConfig:
    timeframe: str = "15m"
    lookback_bars: int = 1100
    ema_period: int = 9
    bb_period: int = 20
    bb_std: float = 2.0
    rsi_period: int = 14
    # Long eligible when RSI is below this; short when RSI is above this
    rsi_long_max: float = 35.0
    rsi_short_min: float = 65.0
    # %B zone thresholds (0 = lower band, 1 = upper band)
    bb_lower_pct_b: float = 0.20
    bb_upper_pct_b: float = 0.80
    bb_mid_lo: float = 0.35
    bb_mid_hi: float = 0.65
    phase_lookback_bars: int = 1000
    vol_ma_period: int = 20
    min_rr: float = 1.2
    sl_atr_mult: float = 0.4
    take_confidence_threshold: float = 55.0
    min_bars: int = 80
    chart_bars: int = 120
    require_volume_expand: bool = False
    require_fresh_cross: bool = False
    # above = long only · below = short only · both
    move_side: str = "both"

    def __post_init__(self) -> None:
        p = int(self.ema_period)
        if p not in ALLOWED_EMA_PERIODS:
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
        phase_n = max(100, int(self.phase_lookback_bars or 1000))
        self.phase_lookback_bars = phase_n
        need = max(int(self.min_bars), int(self.ema_period) * 3 + 40, phase_n + 40, 120)
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


def _percent_b(price: float, lower: float, upper: float) -> float | None:
    band = float(upper) - float(lower)
    if band <= 0 or not np.isfinite(band):
        return None
    return (float(price) - float(lower)) / band


def _classify_bb_zone(
    pct_b: float | None,
    *,
    lower_max: float,
    upper_min: float,
    mid_lo: float,
    mid_hi: float,
) -> str:
    """Return lower | mid | upper | none."""
    if pct_b is None or not np.isfinite(pct_b):
        return "none"
    if mid_lo <= pct_b <= mid_hi:
        return "mid"
    if pct_b <= lower_max:
        return "lower"
    if pct_b >= upper_min:
        return "upper"
    return "none"


def _price_phase(close: pd.Series, bars: int = 1000) -> dict[str, Any]:
    """
    Classify the last ``bars`` closes as upward / descent / sideways.
    Uses net move plus trough→peak structure inside the window.
    """
    n = max(50, int(bars))
    series = close.dropna().astype(float)
    if len(series) < 50:
        return {
            "phase": "insufficient",
            "bars_used": int(len(series)),
            "net_pct": None,
            "rise_from_trough_pct": None,
            "fall_from_peak_pct": None,
            "detail": f"Need ≥50 bars for phase; got {len(series)}",
        }

    window = series.iloc[-min(n, len(series)):]
    used = int(len(window))
    start = float(window.iloc[0])
    end = float(window.iloc[-1])
    if start <= 0 or not np.isfinite(start) or not np.isfinite(end):
        return {
            "phase": "insufficient",
            "bars_used": used,
            "net_pct": None,
            "rise_from_trough_pct": None,
            "fall_from_peak_pct": None,
            "detail": "Invalid close series for phase",
        }

    vals = window.values
    trough_i = int(np.argmin(vals))
    peak_i = int(np.argmax(vals))
    trough = float(vals[trough_i])
    peak = float(vals[peak_i])
    net_pct = ((end / start) - 1.0) * 100.0
    rise_pct = ((end / trough) - 1.0) * 100.0 if trough > 0 else 0.0
    fall_pct = ((peak / end) - 1.0) * 100.0 if end > 0 else 0.0

    # Structure: peak after trough → upward bias; trough after peak → descent bias
    upward_struct = peak_i > trough_i and rise_pct >= max(2.0, abs(net_pct) * 0.35)
    descent_struct = trough_i > peak_i and fall_pct >= max(2.0, abs(net_pct) * 0.35)

    if upward_struct and net_pct >= -1.0:
        phase = "upward"
        detail = (
            f"Upward phase over last {used} bars: net {net_pct:+.1f}% · "
            f"+{rise_pct:.1f}% from trough · −{fall_pct:.1f}% off peak"
        )
    elif descent_struct and net_pct <= 1.0:
        phase = "descent"
        detail = (
            f"Descent phase over last {used} bars: net {net_pct:+.1f}% · "
            f"−{fall_pct:.1f}% from peak · +{rise_pct:.1f}% off trough"
        )
    elif net_pct >= 3.0:
        phase = "upward"
        detail = f"Upward phase over last {used} bars: net {net_pct:+.1f}%"
    elif net_pct <= -3.0:
        phase = "descent"
        detail = f"Descent phase over last {used} bars: net {net_pct:+.1f}%"
    else:
        phase = "sideways"
        detail = (
            f"Sideways / mixed over last {used} bars: net {net_pct:+.1f}% · "
            f"+{rise_pct:.1f}% off trough · −{fall_pct:.1f}% off peak"
        )

    return {
        "phase": phase,
        "bars_used": used,
        "net_pct": _r(net_pct, 2),
        "rise_from_trough_pct": _r(rise_pct, 2),
        "fall_from_peak_pct": _r(fall_pct, 2),
        "detail": detail,
    }


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
    jumped_above_closed = bool(cross_up and above)
    jumped_below_closed = bool(cross_down and below)
    pct_from_ema = ((price / ema_v) - 1.0) * 100.0 if ema_v else 0.0

    pct_b = _percent_b(price, bb_l, bb_u)
    bb_zone = _classify_bb_zone(
        pct_b,
        lower_max=float(cfg.bb_lower_pct_b),
        upper_min=float(cfg.bb_upper_pct_b),
        mid_lo=float(cfg.bb_mid_lo),
        mid_hi=float(cfg.bb_mid_hi),
    )
    near_lower_bb = bb_zone == "lower"
    at_upper_bb = bb_zone == "upper"
    at_mid_bb = bb_zone == "mid"

    rsi_long_ok = rsi_v < float(cfg.rsi_long_max)
    rsi_short_ok = rsi_v > float(cfg.rsi_short_min)

    phase = _price_phase(close, int(cfg.phase_lookback_bars))
    phase_name = str(phase.get("phase") or "insufficient")

    long_eligible = bool(near_lower_bb and rsi_long_ok)
    short_eligible = bool(at_upper_bb and rsi_short_ok)

    checks: list[dict[str, Any]] = [
        {
            "id": "near_lower_bb",
            "label": "Price near Lower Bollinger Band",
            "passed": near_lower_bb,
            "detail": f"%B {_r(pct_b, 2) if pct_b is not None else '—'} · L {_r(bb_l)} · mid {_r(bb_m)} · U {_r(bb_u)}",
        },
        {
            "id": "at_upper_bb",
            "label": "Price at Upper Bollinger Band",
            "passed": at_upper_bb,
            "detail": f"%B {_r(pct_b, 2) if pct_b is not None else '—'} · L {_r(bb_l)} · mid {_r(bb_m)} · U {_r(bb_u)}",
        },
        {
            "id": "at_mid_bb",
            "label": "Price at Middle Bollinger Band → WAIT",
            "passed": at_mid_bb,
            "detail": f"%B {_r(pct_b, 2) if pct_b is not None else '—'} (mid zone {cfg.bb_mid_lo:g}–{cfg.bb_mid_hi:g})",
        },
        {
            "id": "rsi_long",
            "label": f"RSI < {cfg.rsi_long_max:g} (long)",
            "passed": rsi_long_ok,
            "detail": f"RSI {_r(rsi_v, 1)}",
        },
        {
            "id": "rsi_short",
            "label": f"RSI > {cfg.rsi_short_min:g} (short)",
            "passed": rsi_short_ok,
            "detail": f"RSI {_r(rsi_v, 1)}",
        },
        {
            "id": "phase_1000",
            "label": f"Last {phase.get('bars_used', cfg.phase_lookback_bars)} bars phase",
            "passed": phase_name in ("upward", "descent", "sideways"),
            "detail": str(phase.get("detail") or phase_name),
        },
        {
            "id": "jumped_above_closed",
            "label": f"Optional: just jumped above {ema_label}",
            "passed": jumped_above_closed,
            "detail": f"prev {_r(prev)} / EMA{period} {_r(prev_ema)} → close {_r(price)} / {_r(ema_v)}",
        },
        {
            "id": "jumped_below_closed",
            "label": f"Optional: just fell below {ema_label}",
            "passed": jumped_below_closed,
            "detail": f"prev {_r(prev)} / EMA{period} {_r(prev_ema)} → close {_r(price)} / {_r(ema_v)}",
        },
        {
            "id": "vol_expand",
            "label": "Volume above MA20",
            "passed": bool(vol_expand),
            "detail": f"vol {_r(vol_now or 0, 0)} / MA {_r(vol_ma or 0, 0)}",
        },
    ]

    out["ltp"] = _r(price)
    out["price_phase"] = phase_name
    out["price_phase_detail"] = phase
    out["bb_zone"] = bb_zone
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
        "percent_b": _r(pct_b, 3) if pct_b is not None else None,
        "bb_zone": bb_zone,
        "rsi": _r(rsi_v, 1),
        "vol_vs_ma": _r((vol_now / vol_ma) if vol_now and vol_ma else 0, 2),
        "cross_up": cross_up,
        "cross_down": cross_down,
        "above_ema": above,
        "below_ema": below,
        f"above_ema{period}": above,
        f"below_ema{period}": below,
        "price_phase": phase_name,
        "phase_bars": phase.get("bars_used"),
        "phase_net_pct": phase.get("net_pct"),
        "phase_rise_from_trough_pct": phase.get("rise_from_trough_pct"),
        "phase_fall_from_peak_pct": phase.get("fall_from_peak_pct"),
        "long_eligible": long_eligible,
        "short_eligible": short_eligible,
    }
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

    out["jumped_above_closed"] = jumped_above_closed
    out["jumped_below_closed"] = jumped_below_closed
    out["pct_from_ema"] = _r(pct_from_ema, 2)

    # Mid band → always wait
    if at_mid_bb:
        out["signal"] = "WAIT"
        out["status"] = "mid_bb"
        out["reason"] = (
            f"Price at middle Bollinger Band (%B {_r(pct_b, 2) if pct_b is not None else '—'}) — wait. "
            f"Phase: {phase.get('detail')}"
        )
        return out

    side_filter = str(cfg.move_side or "both").lower()
    direction: str | None = None
    if long_eligible and side_filter in ("above", "both"):
        direction = "LONG"
    elif short_eligible and side_filter in ("below", "both"):
        direction = "SHORT"
    elif long_eligible and side_filter == "below":
        out["signal"] = "WAIT"
        out["status"] = "side_filtered"
        out["reason"] = "Lower BB + RSI long setup, but scan is set to Below / short only"
        return out
    elif short_eligible and side_filter == "above":
        out["signal"] = "WAIT"
        out["status"] = "side_filtered"
        out["reason"] = "Upper BB + RSI short setup, but scan is set to Above / long only"
        return out
    else:
        out["signal"] = "WAIT"
        out["status"] = "no_bb_rsi_setup"
        out["reason"] = (
            f"No eligibility: need Lower BB + RSI<{cfg.rsi_long_max:g} for long, or "
            f"Upper BB + RSI>{cfg.rsi_short_min:g} for short "
            f"(zone={bb_zone}, RSI={_r(rsi_v, 1)}). Phase: {phase.get('detail')}"
        )
        return out

    if cfg.require_volume_expand and not vol_expand:
        out["signal"] = "WATCH"
        out["direction"] = direction
        out["status"] = "thin_volume"
        out["reason"] = (
            f"{direction} BB/RSI setup ready, but volume is not expanding — wait for participation. "
            f"Phase: {phase.get('detail')}"
        )
        return out

    if cfg.require_fresh_cross:
        need_cross = jumped_above_closed if direction == "LONG" else jumped_below_closed
        if not need_cross:
            out["signal"] = "WATCH"
            out["direction"] = direction
            out["status"] = "awaiting_ema_cross"
            out["reason"] = (
                f"{direction} eligible on BB/RSI, but fresh {ema_label} jump not confirmed yet — WATCH. "
                f"Phase: {phase.get('detail')}"
            )
            return out

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
        out["reason"] = (
            f"RR {rr if rr is not None else 'n/a'} below floor {cfg.min_rr}. "
            f"Phase: {phase.get('detail')}"
        )
        out["entry_price"] = _r(entry)
        out["stop_price"] = _r(stop) if stop else None
        out["target_price"] = _r(target) if target else None
        out["sl_pct"] = sl_pct
        out["tp_pct"] = tp_pct
        out["rr"] = rr
        return out

    # Phase alignment: long prefers upward; short prefers descent
    phase_aligned = (is_long and phase_name == "upward") or ((not is_long) and phase_name == "descent")
    phase_counter = (is_long and phase_name == "descent") or ((not is_long) and phase_name == "upward")

    score = ConfidenceScore(38.0, "BB + RSI eligibility")
    score.add(long_eligible if is_long else short_eligible, 16, "Outer BB + RSI extreme", "BB/RSI not aligned")
    score.add(vol_expand, 8, "Volume expanding vs MA20", "Thin volume")
    score.add(
        jumped_above_closed if is_long else jumped_below_closed,
        8,
        f"Fresh {ema_label} jump agrees",
        f"No fresh {ema_label} jump (optional)",
    )
    score.add(phase_aligned, 12, f"1000-bar phase agrees ({phase_name})", f"Phase is {phase_name}")
    score.add(not phase_counter, 6, "Not fighting the 1000-bar phase", f"Counter to {phase_name} phase")
    score.add(atr_v > 0, 4, "ATR available for stop sanity", "No ATR")
    score.add(not stop_adjusted, 4, "Stop fits ATR band", "Stop ATR-adjusted")

    confidence_pct, reasons = score.finalize()
    grade = quality_grade(confidence_pct, rr, liquidity_ok(None), stop_adjusted)
    take = confidence_pct >= cfg.take_confidence_threshold

    setup_label = (
        f"Lower BB + RSI {_r(rsi_v, 1)} < {cfg.rsi_long_max:g}"
        if is_long
        else f"Upper BB + RSI {_r(rsi_v, 1)} > {cfg.rsi_short_min:g}"
    )
    phase_line = str(phase.get("detail") or phase_name)

    plan = make_trade_plan(
        direction=direction,
        timeframe=cfg.timeframe,
        stop_loss_pct=round(sl_pct or 0, 2),
        take_profit_pct=round(tp_pct or 0, 2),
        confidence_pct=confidence_pct,
        style="intraday" if cfg.timeframe not in ("1d", "1w", "1wk") else "swing",
        exit_rule=(
            f"{ema_label} / BB desk: SL beyond structure ({_r(stop) if stop else '—'}); "
            f"T1 mid-band ({_r(t1)}); T2 outer ({_r(t2)}). "
            f"Invalidate on close back through {ema_label} against the trade. "
            f"Phase context: {phase_line}."
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
            f"{'BUY' if is_long else 'SELL'}: {setup_label} · {phase_line} · "
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
            "price_phase": phase_name,
            "bb_zone": bb_zone,
            "reason": (
                f"{'BUY' if is_long else 'SELL'}: {setup_label} · phase {phase_name} · "
                f"conf {confidence_pct:.0f}% · SL {sl_pct:.1f}% · TP {tp_pct:.1f}%"
            ),
            "plain_english": (
                f"Risk {sl_pct:.1f}% to stop · aim {tp_pct:.1f}% to T1 · "
                f"confidence {confidence_pct:.0f}% (grade {grade}). "
                f"Last ~{phase.get('bars_used')} bars: {phase_name}."
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
            "price_phase": phase_name,
            "bb_zone": bb_zone,
        },
        "plain_english": (
            f"{'Buy' if is_long else 'Sell'} on {ticker} ({cfg.timeframe}): {setup_label}. "
            f"{phase_line}. "
            f"RSI {_r(rsi_v, 1)}; BB mid {_r(bb_m)}; EMA{period} {_r(ema_v)}. "
            f"Risk {sl_pct:.1f}% · aim {tp_pct:.1f}% to mid-band · conf {confidence_pct:.0f}% (grade {grade}). "
            f"Invalidate on a close back through the {ema_label}."
        ),
        "pro_checklist": [
            "Near Lower BB + RSI < 35 (long) OR Upper BB + RSI > 65 (short)",
            "Mid BB → wait",
            f"Check last ~{cfg.phase_lookback_bars} bars: upward vs descent",
            f"{ema_label} for stop / trail (optional fresh jump boost)",
            "Volume expansion preferred",
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
            "rsi_long_max": cfg.rsi_long_max,
            "rsi_short_min": cfg.rsi_short_min,
            "phase_lookback_bars": cfg.phase_lookback_bars,
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
            "Long only near Lower BB with RSI<35; short only at Upper BB with RSI>65; "
            "mid BB = wait; always check the ~1000-bar upward/descent phase."
        ),
    }


def build_ema9_bb_rsi_vol_ai_prompt(result: dict[str, Any]) -> str:
    period = int(result.get("ema_period") or (result.get("metrics") or {}).get("ema_period") or 9)
    label = strategy_name_for(period)
    extra = [
        f"Direction: {result.get('direction')}",
        f"BB zone: {result.get('bb_zone')} · Phase: {result.get('price_phase')}",
        f"Conf {result.get('confidence_pct')}% · SL {result.get('sl_pct')}% · TP {result.get('tp_pct')}%",
        f"Grade: {result.get('grade')}",
        f"Reason: {result.get('reason')}",
        f"Phase detail: {result.get('price_phase_detail')}",
        f"Checks: {result.get('checks')}",
        f"Pro checklist: {result.get('pro_checklist')}",
    ]
    return build_pro_trade_ai_context(result, engine_label=label, extra_lines=extra)
