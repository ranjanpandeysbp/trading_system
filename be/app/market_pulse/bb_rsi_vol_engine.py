"""
bb_rsi_vol_engine.py
--------------------
BB-RSI-VOL — mean-reversion with volume context + EMA + S/R filters.

Matrix (all asset classes · all timeframes):
  BUY:  Lower BB touch/pierce · RSI ≤ 35 · Low volume (below Vol MA20)
        · near Support · close above 9 EMA · 50 EMA not a steep falling knife
  SELL: Upper BB touch/pierce · RSI ≥ 70 · High volume (above Vol MA20)
        · near Resistance · close below 9 EMA · 50 EMA not a steep melt-up

Targets: Mid BB (T1) · opposite band / next S/R (T2)
Stop: below swing low + support (long) / above climax wick (short)
Boost: RSI divergence at the band

Professional desk habits are folded into ConfidenceScore (auditable %).

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
from app.market_pulse.pa_vp_smc_engine import PaVpSmcConfig, find_swing_sr_zones
from app.market_pulse.pro_trade_shared import (
    ConfidenceScore,
    atr as _atr_ind,
    atr_sane_stop_target,
    build_pro_trade_ai_context,
    ema as _ema,
    kaufman_efficiency_ratio,
    liquidity_ok,
    pro_trade_ai_system,
    quality_grade,
    rr_ratio,
    rsi as _rsi_ind,
    sl_tp_pct,
)
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.smart_money_shared import hold_for_tf
from app.trading_hubs.support_resistance_engine import (
    SupportResistanceConfig,
    detect_candlestick_patterns,
    detect_rsi_divergence,
)

logger = logging.getLogger(__name__)

STRATEGY_ID = "bb_rsi_vol"
STRATEGY_NAME = "BB-RSI-VOL"

TIMEFRAME_OPTIONS = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1wk"]

HOW_IT_WORKS = """
### How BB-RSI-VOL works

Mean-reversion desk: **Bollinger stretch + RSI extreme + volume context**, filtered by
**S/R** and **EMA** so you do not fade a waterfall trend.

| Side | BB | RSI | Volume | S/R | Entry trigger |
|------|----|-----|--------|-----|---------------|
| **BUY** | Touch/pierce **Lower** band | ≤ **35** | **Low** (below Vol MA20) | Near **Support** | Close **above 9 EMA** |
| **SELL** | Touch/pierce **Upper** band | ≥ **70** | **High** (above Vol MA20) | Near **Resistance** | Close **below 9 EMA** |

**Defaults:** BB(20, 2) · RSI(14) · Vol MA20 · EMA 5 / 9 / 50

**EMA continuation (last ~100 days)**
- Reports whether price is above/below EMA5 and EMA9
- Short-term rise/fall intensity (mild → extreme vs ATR)
- Finds similar historical EMA setups and measures whether the next 2 candles continued
- Outputs continuation bias + % confidence from that history

**Targets / risk**
- T1 = Mid BB (20 SMA) · T2 = opposite band or next S/R
- SL = below swing low + support (long) / above climax wick (short)
- Output includes **% confidence**, **%SL**, **%TP**

**Pro habits**
- Skip if floating in “empty space” (no S/R)
- Skip falling-knife longs (steep declining 50 EMA) / melt-up shorts
- Prefer RSI divergence at the band
- Prefer reversal candle (Hammer / Engulfing / Shooting Star)

**How to use this screen**
1. Pick asset class + timeframes + tickers.
2. Scan — act only on TAKE with grade A/B and clear %SL / %TP.
3. Wait for the 9 EMA close confirmation; do not front-run the band alone.
""".strip()

RULES = [
    "BB(20,2) stretch: buy lower / sell upper.",
    "RSI(14): ≤35 long · ≥70 short.",
    "Volume vs MA20: low for buys (exhaustion) · high for sells (climax).",
    "Must align with Support (buy) or Resistance (sell).",
    "Entry only on close beyond 9 EMA in trade direction.",
    "50 EMA filter: avoid steep opposing trends.",
    "T1 mid BB · T2 opposite band/S/R · SL beyond structure.",
    "RSI divergence boosts confidence.",
]

BB_RSI_VOL_AI_SYSTEM = pro_trade_ai_system(
    STRATEGY_NAME,
    "BB stretch + RSI extreme + volume context (low buy / high sell) + S/R + "
    "9 EMA entry / 50 EMA trend filter; T1 mid-band; report conf% / SL% / TP%.",
)

PRO_TIPS = [
    "Never buy the lower band in empty space — wait for historical support.",
    "Low volume at the lows = sellers exhausted; high volume at the highs = climax.",
    "Wait for a close above/below the 9 EMA — the band touch is the setup, not the entry.",
    "If 50 EMA is steeply against you, stand aside or wait for it to flatten.",
    "RSI divergence at the band is your highest-probability filter.",
    "Book partial at mid-band (T1); trail remainder toward T2.",
    "Size so the structural stop is ≤ your max risk per trade.",
]


@dataclass
class BbRsiVolConfig:
    timeframe: str = "15m"
    lookback_bars: int = 300
    bb_period: int = 20
    bb_std: float = 2.0
    rsi_period: int = 14
    rsi_buy: float = 35.0
    rsi_sell: float = 70.0
    vol_ma_period: int = 20
    ema_fast: int = 9
    ema_ultra_fast: int = 5
    ema_trend: int = 50
    zone_tolerance_pct: float = 1.25
    min_rr: float = 1.2
    sl_atr_mult: float = 0.35
    er_hard_block: float = 0.72  # very clean trends — hard skip
    take_confidence_threshold: float = 55.0
    min_bars: int = 80
    chart_bars: int = 120
    require_sr: bool = True
    require_ema_cross_close: bool = True
    history_days: int = 100
    continuation_bars: int = 2
    intensity_lookback_bars: int = 3


def _r(x: float, n: int = 6) -> float:
    return round(float(x), n)


def _near_zone(price: float, zone: dict[str, Any] | None, side: str, tol_pct: float) -> bool:
    if not zone or price <= 0:
        return False
    top = float(zone.get("top") or 0)
    bottom = float(zone.get("bottom") or 0)
    if top <= 0 or bottom <= 0:
        return False
    lo, hi = min(bottom, top), max(bottom, top)
    pad = price * tol_pct / 100.0
    if side == "support":
        return (lo - pad) <= price <= (hi + pad)
    return (lo - pad) <= price <= (hi + pad)


def _bb_cols(close: pd.Series, period: int, std_mult: float) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    return mid + std_mult * std, mid, mid - std_mult * std


def _ema_slope_pct(ema: pd.Series, lookback: int = 5) -> float | None:
    if ema is None or len(ema) < lookback + 1:
        return None
    a, b = float(ema.iloc[-1 - lookback]), float(ema.iloc[-1])
    if not np.isfinite(a) or a == 0:
        return None
    return (b - a) / abs(a) * 100.0


def _bars_for_history_days(timeframe: str, days: int) -> int:
    """Approximate bars needed to cover ~``days`` calendar days on ``timeframe``."""
    d = max(20, int(days))
    tf = (timeframe or "15m").lower()
    if tf in ("1d", "1wk", "1w", "1M"):
        return min(2500, d + 40)
    if tf == "4h":
        return min(2500, d * 6 + 50)
    if tf == "1h":
        return min(2500, d * 8 + 60)
    if tf == "30m":
        return min(2500, d * 14 + 80)
    if tf == "15m":
        return min(2500, d * 26 + 100)
    if tf == "5m":
        return min(2500, d * 78 + 120)
    if tf == "1m":
        return min(2500, d * 200 + 150)
    return min(2500, d * 12 + 80)


def _intensity_label(abs_move_pct: float, atr_pct: float) -> str:
    """Classify short-term move strength vs ATR."""
    atr_pct = max(0.05, float(atr_pct or 0.05))
    score = abs(float(abs_move_pct)) / atr_pct
    if score < 0.6:
        return "mild"
    if score < 1.2:
        return "moderate"
    if score < 2.0:
        return "strong"
    return "extreme"


def _ema_continuation_forecast(
    work: pd.DataFrame,
    *,
    cfg: BbRsiVolConfig,
) -> dict[str, Any]:
    """
    Price vs EMA5/EMA9, short-term rise/fall intensity, and 2-candle continuation
    odds from analogues in the last ``history_days`` window.
    """
    close = work["close"].astype(float)
    n = len(work)
    i = n - 1
    hist_days = max(20, int(cfg.history_days))
    fwd = max(1, int(cfg.continuation_bars))
    look = max(2, int(cfg.intensity_lookback_bars))

    ema5 = work["ema5"] if "ema5" in work.columns else _ema(close, cfg.ema_ultra_fast)
    ema9 = work["ema9"] if "ema9" in work.columns else _ema(close, cfg.ema_fast)

    price = float(close.iloc[i])
    e5 = float(ema5.iloc[i]) if pd.notna(ema5.iloc[i]) else None
    e9 = float(ema9.iloc[i]) if pd.notna(ema9.iloc[i]) else None
    if e5 is None or e9 is None or price <= 0:
        return {"error": "EMA5/EMA9 not ready"}

    above_5 = price > e5
    above_9 = price > e9
    below_5 = price < e5
    below_9 = price < e9

    ref_i = max(0, i - look)
    ref = float(close.iloc[ref_i])
    move_pct = ((price / ref) - 1.0) * 100.0 if ref > 0 else 0.0
    if move_pct > 0.05:
        direction = "rising"
    elif move_pct < -0.05:
        direction = "falling"
    else:
        direction = "flat"

    atr_series = _atr_ind(work, 14)
    atr_v = float(atr_series.iloc[i]) if pd.notna(atr_series.iloc[i]) else 0.0
    atr_pct = (atr_v / price) * 100.0 if price > 0 else 0.0
    intensity = _intensity_label(abs(move_pct), atr_pct)
    intensity_score = round(abs(move_pct) / max(atr_pct, 0.05), 2)

    slope5 = _ema_slope_pct(ema5.dropna(), min(5, look))
    slope9 = _ema_slope_pct(ema9.dropna(), min(5, look))

    # Restrict analogue search to last ~history_days of bars (leave room for forward path).
    bars_window = _bars_for_history_days(cfg.timeframe, hist_days)
    start_j = max(look + 5, n - bars_window)
    end_j = n - 1 - fwd  # need forward path after analogue
    if end_j <= start_j:
        return {
            "price_vs_ema5": "above" if above_5 else "below",
            "price_vs_ema9": "above" if above_9 else "below",
            "above_ema5": above_5,
            "above_ema9": above_9,
            "below_ema5": below_5,
            "below_ema9": below_9,
            "ema5": _r(e5),
            "ema9": _r(e9),
            "distance_ema5_pct": _r((price / e5 - 1.0) * 100.0, 3),
            "distance_ema9_pct": _r((price / e9 - 1.0) * 100.0, 3),
            "short_term_direction": direction,
            "move_pct": _r(move_pct, 3),
            "intensity": intensity,
            "intensity_score": intensity_score,
            "ema5_slope_pct": _r(slope5, 3) if slope5 is not None else None,
            "ema9_slope_pct": _r(slope9, 3) if slope9 is not None else None,
            "history_days": hist_days,
            "continuation_bars": fwd,
            "analogues": 0,
            "error": "Not enough history for continuation sample",
        }

    # Intensity band for analogues (±40% relative or ±0.35% absolute floor)
    band = max(0.35, abs(move_pct) * 0.40)
    min_gap = max(3, look)
    spaced: list[dict[str, Any]] = []
    last_j_kept = -10**9
    for j in range(start_j, end_j + 1):
        pj = float(close.iloc[j])
        e5j = float(ema5.iloc[j]) if pd.notna(ema5.iloc[j]) else None
        e9j = float(ema9.iloc[j]) if pd.notna(ema9.iloc[j]) else None
        if e5j is None or e9j is None or pj <= 0:
            continue
        if (pj > e5j) != above_5 or (pj > e9j) != above_9:
            continue
        ref_j = float(close.iloc[j - look])
        if ref_j <= 0:
            continue
        mv = ((pj / ref_j) - 1.0) * 100.0
        if direction == "rising" and mv <= 0.05:
            continue
        if direction == "falling" and mv >= -0.05:
            continue
        if direction == "flat" and abs(mv) > 0.15:
            continue
        if abs(mv - move_pct) > band and direction != "flat":
            continue
        if j - last_j_kept < min_gap:
            continue
        fwd_close = float(close.iloc[j + fwd])
        if not np.isfinite(fwd_close) or fwd_close <= 0:
            continue
        fwd_ret = ((fwd_close / pj) - 1.0) * 100.0
        if direction == "rising":
            continued = fwd_close > pj
        elif direction == "falling":
            continued = fwd_close < pj
        else:
            continued = abs(fwd_ret) < 0.15
        try:
            t = pd.Timestamp(work.index[j]).isoformat()
        except Exception:
            t = str(work.index[j])
        spaced.append({
            "time": t,
            "move_pct": _r(mv, 3),
            "next_2_return_pct": _r(fwd_ret, 3),
            "continued": bool(continued),
        })
        last_j_kept = j

    samples = len(spaced)
    continued_n = sum(1 for a in spaced if a["continued"])
    cont_rate = (100.0 * continued_n / samples) if samples else None
    avg_fwd = float(np.mean([a["next_2_return_pct"] for a in spaced])) if samples else None
    med_fwd = float(np.median([a["next_2_return_pct"] for a in spaced])) if samples else None

    will_continue = None
    if cont_rate is not None:
        if direction == "flat":
            will_continue = cont_rate >= 55
        else:
            will_continue = cont_rate >= 55

    # Confidence: agreement with history × sample size
    if samples <= 0:
        conf = 0.0
    else:
        agreement = abs((cont_rate or 50) - 50.0) / 50.0
        conf = min(90.0, max(18.0, (cont_rate or 50) * 0.55 + agreement * 25.0 + min(15.0, samples)))
        if direction == "flat":
            conf = min(conf, 45.0)

    predicted_move = med_fwd if med_fwd is not None else avg_fwd
    predicted_intensity = (
        _intensity_label(abs(predicted_move or 0), atr_pct) if predicted_move is not None else None
    )

    if direction == "rising":
        verb = "continue to rise" if will_continue else "stall / reverse"
    elif direction == "falling":
        verb = "continue to fall" if will_continue else "stall / reverse"
    else:
        verb = "stay flat" if will_continue else "break out"

    plain = (
        f"Price is {'above' if above_5 else 'below'} EMA5 ({_r(e5)}) and "
        f"{'above' if above_9 else 'below'} EMA9 ({_r(e9)}). "
        f"Short-term {direction} {abs(move_pct):.2f}% over {look} bars ({intensity} intensity). "
    )
    if samples:
        plain += (
            f"In the last ~{hist_days}d, {samples} similar EMA setups: next {fwd} candle(s) "
            f"continued {continued_n}/{samples} times ({cont_rate:.0f}%). "
            f"Median next-{fwd} move {predicted_move:+.2f}% ({predicted_intensity}). "
            f"Bias: likely to {verb} · confidence {conf:.0f}%."
        )
    else:
        plain += f"No close historical analogues in the last ~{hist_days}d for a {fwd}-candle forecast."

    return {
        "price_vs_ema5": "above" if above_5 else ("below" if below_5 else "at"),
        "price_vs_ema9": "above" if above_9 else ("below" if below_9 else "at"),
        "above_ema5": above_5,
        "above_ema9": above_9,
        "below_ema5": below_5,
        "below_ema9": below_9,
        "ema5": _r(e5),
        "ema9": _r(e9),
        "distance_ema5_pct": _r((price / e5 - 1.0) * 100.0, 3),
        "distance_ema9_pct": _r((price / e9 - 1.0) * 100.0, 3),
        "short_term_direction": direction,
        "move_pct": _r(move_pct, 3),
        "move_lookback_bars": look,
        "intensity": intensity,
        "intensity_score": intensity_score,
        "ema5_slope_pct": _r(slope5, 3) if slope5 is not None else None,
        "ema9_slope_pct": _r(slope9, 3) if slope9 is not None else None,
        "history_days": hist_days,
        "continuation_bars": fwd,
        "analogues": samples,
        "continued_count": continued_n,
        "continuation_rate_pct": _r(cont_rate, 1) if cont_rate is not None else None,
        "will_continue": will_continue,
        "predicted_next_2_return_pct": _r(predicted_move, 3) if predicted_move is not None else None,
        "avg_next_2_return_pct": _r(avg_fwd, 3) if avg_fwd is not None else None,
        "predicted_intensity": predicted_intensity,
        "confidence_pct": _r(conf, 1),
        "bias": verb,
        "plain_english": plain,
        "recent_analogues": spaced[-8:],
    }


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
        for k in ("bb_upper", "bb_mid", "bb_lower", "ema5", "ema9", "ema50", "vol_ma"):
            if k in bar and pd.notna(bar.get(k)):
                row[k] = _r(float(bar[k]), 6)
        rows.append(row)
    return rows


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: BbRsiVolConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or BbRsiVolConfig()
    fetch_limit = max(int(cfg.lookback_bars), _bars_for_history_days(cfg.timeframe, cfg.history_days))
    out: dict[str, Any] = {
        "ticker": ticker,
        "timeframe": cfg.timeframe,
        "strategy": STRATEGY_ID,
        "signal": "WAIT",
        "direction": "NONE",
        "take_trade": False,
        "checks": [],
        "metrics": {},
        "pro_tips": PRO_TIPS[:4],
    }

    try:
        raw = fetch_data_for_gap_scan(
            ticker, cfg.timeframe, market, groww_token, exchange, limit=fetch_limit,
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
    work["ema5"] = _ema(close, cfg.ema_ultra_fast)
    work["ema9"] = _ema(close, cfg.ema_fast)
    work["ema50"] = _ema(close, cfg.ema_trend)
    work["rsi"] = _rsi_ind(close, cfg.rsi_period)
    work["vol_ma"] = vol.rolling(cfg.vol_ma_period).mean()

    i = len(work) - 1
    if pd.isna(upper.iloc[i]) or pd.isna(work["rsi"].iloc[i]) or pd.isna(work["ema9"].iloc[i]):
        out["error"] = "Indicators not ready"
        return out

    price = float(close.iloc[i])
    hi = float(high.iloc[i])
    lo = float(low.iloc[i])
    rsi_v = float(work["rsi"].iloc[i])
    ema5 = float(work["ema5"].iloc[i]) if pd.notna(work["ema5"].iloc[i]) else None
    ema9 = float(work["ema9"].iloc[i])
    ema50 = float(work["ema50"].iloc[i]) if pd.notna(work["ema50"].iloc[i]) else None
    bb_u, bb_m, bb_l = float(upper.iloc[i]), float(mid.iloc[i]), float(lower.iloc[i])
    vol_now = float(vol.iloc[i]) if pd.notna(vol.iloc[i]) else None
    vol_ma = float(work["vol_ma"].iloc[i]) if pd.notna(work["vol_ma"].iloc[i]) else None
    low_vol = vol_now is not None and vol_ma is not None and vol_now < vol_ma
    high_vol = vol_now is not None and vol_ma is not None and vol_now > vol_ma

    touch_lower = lo <= bb_l or price <= bb_l
    touch_upper = hi >= bb_u or price >= bb_u
    close_above_9 = price > ema9
    close_below_9 = price < ema9
    close_above_5 = ema5 is not None and price > ema5
    close_below_5 = ema5 is not None and price < ema5

    er = float(kaufman_efficiency_ratio(close, period=14).iloc[i] or 0)
    slope50 = _ema_slope_pct(work["ema50"].dropna(), 5)

    ema_cont = _ema_continuation_forecast(work, cfg=cfg)
    out["ema_continuation"] = ema_cont

    zones = find_swing_sr_zones(work, PaVpSmcConfig())
    support = zones.get("support")
    resistance = zones.get("resistance")
    near_sup = _near_zone(price, support, "support", cfg.zone_tolerance_pct)
    near_res = _near_zone(price, resistance, "resistance", cfg.zone_tolerance_pct)

    patterns = detect_candlestick_patterns(work, lookback=3)
    bull_candle = any(
        str(p.get("direction") or p.get("bias") or "").lower() in ("bullish", "buy", "long")
        or "hammer" in str(p.get("name") or "").lower()
        or "engulfing" in str(p.get("name") or "").lower() and "bull" in str(p.get("name") or "").lower()
        for p in (patterns or [])
    )
    bear_candle = any(
        str(p.get("direction") or p.get("bias") or "").lower() in ("bearish", "sell", "short")
        or "shooting" in str(p.get("name") or "").lower()
        or "engulfing" in str(p.get("name") or "").lower() and "bear" in str(p.get("name") or "").lower()
        for p in (patterns or [])
    )
    # softer candle match if pattern dict uses type field
    for p in patterns or []:
        name = str(p.get("name") or p.get("pattern") or "").lower()
        if any(k in name for k in ("hammer", "bullish engulfing", "morning star")):
            bull_candle = True
        if any(k in name for k in ("shooting star", "bearish engulfing", "evening star")):
            bear_candle = True

    divs = detect_rsi_divergence(work, work["rsi"], SupportResistanceConfig())
    bull_div = any(d.get("direction") == "bullish" for d in divs)
    bear_div = any(d.get("direction") == "bearish" for d in divs)

    # Falling knife / melt-up filters
    steep_down = slope50 is not None and slope50 <= -1.2
    steep_up = slope50 is not None and slope50 >= 1.2
    hard_trend = er >= cfg.er_hard_block

    buy_setup = touch_lower and rsi_v <= cfg.rsi_buy and low_vol
    sell_setup = touch_upper and rsi_v >= cfg.rsi_sell and high_vol

    checks: list[dict[str, Any]] = [
        {"id": "bb_lower", "label": "Touch/pierce Lower BB", "passed": touch_lower, "detail": f"L {_r(bb_l)} · low {_r(lo)}"},
        {"id": "bb_upper", "label": "Touch/pierce Upper BB", "passed": touch_upper, "detail": f"U {_r(bb_u)} · high {_r(hi)}"},
        {"id": "rsi_buy", "label": f"RSI ≤ {cfg.rsi_buy:g}", "passed": rsi_v <= cfg.rsi_buy, "detail": f"RSI {_r(rsi_v, 1)}"},
        {"id": "rsi_sell", "label": f"RSI ≥ {cfg.rsi_sell:g}", "passed": rsi_v >= cfg.rsi_sell, "detail": f"RSI {_r(rsi_v, 1)}"},
        {"id": "low_vol", "label": "Volume below MA20 (exhaustion)", "passed": bool(low_vol), "detail": f"vol {_r(vol_now or 0, 0)} / MA {_r(vol_ma or 0, 0)}"},
        {"id": "high_vol", "label": "Volume above MA20 (climax)", "passed": bool(high_vol), "detail": f"vol {_r(vol_now or 0, 0)} / MA {_r(vol_ma or 0, 0)}"},
        {"id": "support", "label": "Near Support", "passed": near_sup, "detail": str((support or {}).get("origin_index", "—"))},
        {"id": "resistance", "label": "Near Resistance", "passed": near_res, "detail": str((resistance or {}).get("origin_index", "—"))},
        {"id": "ema5_long", "label": "Close above 5 EMA", "passed": bool(close_above_5), "detail": f"EMA5 {_r(ema5) if ema5 else '—'}"},
        {"id": "ema5_short", "label": "Close below 5 EMA", "passed": bool(close_below_5), "detail": f"EMA5 {_r(ema5) if ema5 else '—'}"},
        {"id": "ema9_long", "label": "Close above 9 EMA", "passed": close_above_9, "detail": f"EMA9 {_r(ema9)}"},
        {"id": "ema9_short", "label": "Close below 9 EMA", "passed": close_below_9, "detail": f"EMA9 {_r(ema9)}"},
        {"id": "ema50", "label": "50 EMA not opposing steeply", "passed": not (steep_down or steep_up), "detail": f"slope5 {_r(slope50, 2) if slope50 is not None else '—'}% · ER {_r(er, 2)}"},
        {"id": "bull_div", "label": "Bullish RSI divergence", "passed": bull_div, "detail": "boost" if bull_div else "—"},
        {"id": "bear_div", "label": "Bearish RSI divergence", "passed": bear_div, "detail": "boost" if bear_div else "—"},
        {
            "id": "ema_continuation",
            "label": f"Next-{cfg.continuation_bars} candle continuation (100d hist)",
            "passed": bool(ema_cont.get("will_continue")),
            "detail": (
                f"{ema_cont.get('short_term_direction')} · {ema_cont.get('intensity')} · "
                f"{ema_cont.get('continuation_rate_pct')}% hist · conf {ema_cont.get('confidence_pct')}%"
                if not ema_cont.get("error")
                else str(ema_cont.get("error"))
            ),
        },
    ]

    out["ltp"] = _r(price)
    out["metrics"] = {
        "bb_upper": _r(bb_u), "bb_mid": _r(bb_m), "bb_lower": _r(bb_l),
        "rsi": _r(rsi_v, 1),
        "ema5": _r(ema5) if ema5 else None,
        "ema9": _r(ema9),
        "ema50": _r(ema50) if ema50 else None,
        "above_ema5": close_above_5,
        "above_ema9": close_above_9,
        "vol_vs_ma": _r((vol_now / vol_ma) if vol_now and vol_ma else 0, 2),
        "er": _r(er, 3), "ema50_slope_pct": _r(slope50, 2) if slope50 is not None else None,
        "near_support": near_sup, "near_resistance": near_res,
        "bull_div": bull_div, "bear_div": bear_div,
        "short_term_direction": ema_cont.get("short_term_direction"),
        "move_intensity": ema_cont.get("intensity"),
        "continuation_confidence_pct": ema_cont.get("confidence_pct"),
        "will_continue_next_2": ema_cont.get("will_continue"),
        "predicted_next_2_return_pct": ema_cont.get("predicted_next_2_return_pct"),
    }
    out["checks"] = checks
    out["chart_data"] = _build_chart(work, max_bars=cfg.chart_bars)
    out["chart_series"] = [
        {"key": "bb_upper", "label": "BB Upper", "color": "#94a3b8"},
        {"key": "bb_mid", "label": "BB Mid", "color": "#38bdf8"},
        {"key": "bb_lower", "label": "BB Lower", "color": "#94a3b8"},
        {"key": "ema5", "label": "EMA5", "color": "#2dd4bf"},
        {"key": "ema9", "label": "EMA9", "color": "#fbbf24"},
        {"key": "ema50", "label": "EMA50", "color": "#a78bfa"},
    ]
    out["chart_levels"] = [
        *([{"price": _r(float(support["bottom"])), "label": "Support", "color": "#34d399"}] if support else []),
        *([{"price": _r(float(resistance["top"])), "label": "Resistance", "color": "#fb7185"}] if resistance else []),
    ]

    # Fall / Rise forecasts available on every charted result (WAIT / WATCH / take).
    try:
        from app.market_pulse.falling_knife_engine import build_fall_rise_forecasts_from_df

        move_forecasts = build_fall_rise_forecasts_from_df(
            work,
            threshold_pct=10.0,
            move_side="both",
            timeframe=cfg.timeframe,
            entry=price,
        )
        out["forecast"] = move_forecasts.get("forecast") or {}
        out["primary_forecast"] = move_forecasts.get("primary_forecast")
        out["fall_count"] = move_forecasts.get("fall_count")
        out["rise_count"] = move_forecasts.get("rise_count")
    except Exception as exc:
        logger.debug("BB move forecasts skipped for %s: %s", ticker, exc)
        out["forecast"] = {}
        out["primary_forecast"] = None

    direction: str | None = None
    if buy_setup and (not cfg.require_ema_cross_close or close_above_9):
        if cfg.require_sr and not near_sup:
            out["signal"] = "WATCH"
            out["status"] = "buy_no_sr"
            out["reason"] = "Lower BB + RSI≤35 + low vol — but no Support confluence; skip (pro filter)"
            return out
        if steep_down or (hard_trend and ema50 is not None and price < ema50):
            out["signal"] = "WATCH"
            out["status"] = "falling_knife"
            out["reason"] = "Setup present but 50 EMA / ER says falling knife — stand aside"
            return out
        direction = "LONG"
    elif sell_setup and (not cfg.require_ema_cross_close or close_below_9):
        if cfg.require_sr and not near_res:
            out["signal"] = "WATCH"
            out["status"] = "sell_no_sr"
            out["reason"] = "Upper BB + RSI≥70 + high vol — but no Resistance confluence; skip"
            return out
        if steep_up or (hard_trend and ema50 is not None and price > ema50):
            out["signal"] = "WATCH"
            out["status"] = "melt_up"
            out["reason"] = "Setup present but 50 EMA / ER says melt-up — shorting is dangerous"
            return out
        direction = "SHORT"
    else:
        # Partial setups
        if touch_lower and rsi_v <= cfg.rsi_buy and not close_above_9:
            out["signal"] = "WATCH"
            out["reason"] = "Buy setup forming — wait for close above 9 EMA"
            return out
        if touch_upper and rsi_v >= cfg.rsi_sell and not close_below_9:
            out["signal"] = "WATCH"
            out["reason"] = "Sell setup forming — wait for close below 9 EMA"
            return out
        out["signal"] = "WAIT"
        out["reason"] = "No BB+RSI+volume matrix match"
        return out

    is_long = direction == "LONG"
    entry = price
    atr_series = _atr_ind(work, 14)
    atr_v = float(atr_series.iloc[i]) if pd.notna(atr_series.iloc[i]) else 0.0

    # Structure stops
    swing_low = float(low.iloc[-8:].min())
    swing_high = float(high.iloc[-8:].max())
    dir_key = "LONG" if is_long else "SHORT"
    if is_long:
        struct_stop = min(swing_low, bb_l) - cfg.sl_atr_mult * atr_v
        if support:
            struct_stop = min(struct_stop, float(support.get("bottom") or struct_stop) - cfg.sl_atr_mult * atr_v * 0.25)
        t1 = bb_m
        t2 = bb_u
        if resistance and float(resistance.get("bottom") or 0) > entry:
            t2 = min(t2, float(resistance["bottom"]))
    else:
        struct_stop = max(swing_high, bb_u) + cfg.sl_atr_mult * atr_v
        t1 = bb_m
        t2 = bb_l
        if support and float(support.get("top") or 0) < entry:
            t2 = max(t2, float(support["top"]))

    stop, target, stop_adjusted = atr_sane_stop_target(dir_key, entry, struct_stop, t1, atr_v)
    sl_pct, tp_pct = sl_tp_pct(dir_key, entry, stop, target)
    rr = rr_ratio(sl_pct, tp_pct)
    if rr is not None and rr < cfg.min_rr and abs(t2 - t1) > 1e-9:
        stop2, target2, adj2 = atr_sane_stop_target(dir_key, entry, struct_stop, t2, atr_v)
        sl2, tp2 = sl_tp_pct(dir_key, entry, stop2, target2)
        rr2 = rr_ratio(sl2, tp2)
        if rr2 is not None and (rr is None or rr2 >= rr):
            stop, target, stop_adjusted = stop2, target2, adj2
            sl_pct, tp_pct, rr = sl2, tp2, rr2

    if rr is None or rr < cfg.min_rr:
        out["signal"] = "WATCH"
        out["direction"] = direction
        out["reason"] = f"RR {rr if rr is not None else 'n/a'} below floor {cfg.min_rr} — pro desk skips thin reward"
        out["entry_price"] = _r(entry)
        out["stop_price"] = _r(stop) if stop else None
        out["target_price"] = _r(target) if target else None
        out["sl_pct"] = sl_pct
        out["tp_pct"] = tp_pct
        out["rr"] = rr
        return out

    score = ConfidenceScore(42.0, "BB+RSI+Vol matrix matched")
    score.add(True, 8, "Core BB stretch + RSI extreme + volume context aligned", "")
    score.add(near_sup if is_long else near_res, 10,
              "Price at historical S/R — not empty space",
              "S/R weak")
    score.add(close_above_9 if is_long else close_below_9, 8,
              "9 EMA close confirms buyers/sellers stepped in",
              "No 9 EMA confirmation")
    score.add(close_above_5 if is_long else close_below_5, 4,
              "5 EMA aligned with trade side",
              "5 EMA not aligned")
    cont_ok = bool(ema_cont.get("will_continue"))
    cont_dir = str(ema_cont.get("short_term_direction") or "")
    cont_agrees = (
        (is_long and cont_dir == "rising" and cont_ok)
        or ((not is_long) and cont_dir == "falling" and cont_ok)
    )
    score.add(
        cont_agrees,
        7,
        f"100d hist: next-{cfg.continuation_bars} candles likely continue ({ema_cont.get('confidence_pct')}% conf)",
        f"EMA continuation hist does not strongly agree ({ema_cont.get('bias')})",
    )
    score.add(bull_candle if is_long else bear_candle, 6,
              "Reversal candlestick agrees",
              "No clear reversal candle yet")
    score.add(bull_div if is_long else bear_div, 10,
              "RSI divergence — highest-probability boost",
              "No RSI divergence")
    score.add(not hard_trend, 6,
              "Efficiency Ratio not in hard-trend regime",
              "Market trending too cleanly — fade risk")
    score.add(not (steep_down if is_long else steep_up), 6,
              "50 EMA slope acceptable",
              "50 EMA steeply against the trade")
    if is_long:
        score.add(low_vol, 5, "Low volume = seller exhaustion", "Volume not low")
    else:
        score.add(high_vol, 5, "High volume = buying climax", "Volume not climax")

    confidence_pct, reasons = score.finalize()
    liq = liquidity_ok(None)
    grade = quality_grade(confidence_pct, rr, liq, stop_adjusted)
    take = confidence_pct >= cfg.take_confidence_threshold

    plan = make_trade_plan(
        direction=direction,
        timeframe=cfg.timeframe,
        stop_loss_pct=round(sl_pct or 0, 2),
        take_profit_pct=round(tp_pct or 0, 2),
        confidence_pct=confidence_pct,
        style="intraday" if cfg.timeframe not in ("1d", "1w", "1wk") else "swing",
        exit_rule=(
            f"BB-RSI-VOL: SL beyond structure ({_r(stop) if stop else '—'}); "
            f"T1 mid-band ({_r(t1)}); T2 opposite/S/R ({_r(t2)}). "
            f"Trail after T1; invalidate if price re-closes outside band against you."
        ),
        max_hold_exit=f"Typical hold ({hold_for_tf(cfg.timeframe)}); book partial at mid-band.",
    )

    out.update({
        "take_trade": take,
        "direction": direction,
        "signal": "BULLISH" if is_long else "BEARISH",
        "action": "BUY" if is_long else "SELL",
        "status": "take" if take else "setup_low_conf",
        "reason": (
            f"{'BUY' if is_long else 'SELL'}: BB + RSI + {'low' if is_long else 'high'} vol + S/R + 9 EMA — "
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
                f"{'BUY' if is_long else 'SELL'}: BB + RSI + vol · "
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
            f"{'Buy' if is_long else 'Sell'} setup on {ticker} ({cfg.timeframe}): price "
            f"{'pierced the lower' if is_long else 'pierced the upper'} Bollinger Band with RSI "
            f"{_r(rsi_v, 1)} and {'quiet' if is_long else 'climax'} volume"
            f"{' at support' if is_long and near_sup else ''}"
            f"{' at resistance' if not is_long and near_res else ''}. "
            f"Entry confirmed by close {'above' if is_long else 'below'} the 9 EMA"
            f"{' / above 5 EMA' if is_long and close_above_5 else ''}"
            f"{' / below 5 EMA' if (not is_long) and close_below_5 else ''}. "
            f"Risk {sl_pct:.1f}% to stop · aim {tp_pct:.1f}% to T1 (mid-band) · confidence {confidence_pct:.0f}% (grade {grade}). "
            f"{ema_cont.get('plain_english') or ''} "
            f"Pro tip: prefer RSI divergence and book partial at mid-band."
        ),
        "matched_pattern": next((p.get("name") for p in (patterns or []) if p.get("name")), None),
        "divergences": divs,
        "pro_checklist": [
            "S/R confluence checked",
            "9 EMA close confirmation",
            "50 EMA / ER trend filter",
            "Volume context (exhaustion vs climax)",
            "Structural stop beyond swing / wick",
            "T1 mid-band · T2 opposite band or S/R",
            "Size so SL ≤ max risk per trade",
        ],
    })
    return out


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: BbRsiVolConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
    timeframes: list[str] | None = None,
) -> dict[str, Any]:
    cfg = cfg or BbRsiVolConfig()
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
                logger.exception("BB-RSI-VOL failed for %s %s", t, tf)
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
            "bb_period": cfg.bb_period,
            "bb_std": cfg.bb_std,
            "rsi_buy": cfg.rsi_buy,
            "rsi_sell": cfg.rsi_sell,
            "vol_ma_period": cfg.vol_ma_period,
            "ema_ultra_fast": cfg.ema_ultra_fast,
            "ema_fast": cfg.ema_fast,
            "ema_trend": cfg.ema_trend,
            "min_rr": cfg.min_rr,
            "take_confidence_threshold": cfg.take_confidence_threshold,
            "history_days": cfg.history_days,
            "continuation_bars": cfg.continuation_bars,
        },
        "results": results,
        "entry_count": len(actionable),
        "scanned": len(results),
        "ai_system_prompt": BB_RSI_VOL_AI_SYSTEM,
        "disclaimer": (
            "Research / education only — not financial advice. "
            "Do not fade clean trends; wait for 9 EMA confirmation and S/R."
        ),
    }


def build_bb_rsi_vol_ai_prompt(result: dict[str, Any]) -> str:
    ema_c = result.get("ema_continuation") or {}
    extra = [
        f"Direction: {result.get('direction')}",
        f"Conf {result.get('confidence_pct')}% · SL {result.get('sl_pct')}% · TP {result.get('tp_pct')}%",
        f"Grade: {result.get('grade')}",
        f"Reason: {result.get('reason')}",
        f"EMA continuation: {ema_c.get('plain_english') or ema_c}",
        f"Checks: {result.get('checks')}",
        f"Pro checklist: {result.get('pro_checklist')}",
    ]
    return build_pro_trade_ai_context(result, engine_label=STRATEGY_NAME, extra_lines=extra)
