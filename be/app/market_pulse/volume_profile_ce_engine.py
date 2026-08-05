"""
volume_profile_ce_engine.py
---------------------------
Volume Profile CE — professional setups from Abhishek Kar masterclass.

Source: https://youtu.be/67u8mdQ8f08

Strategies:
  1. Value Area Reversal — touch VAL/VAH + hammer/shooting-star confirmation
  2. POC Compression Breakout — multi-day POC cluster then break
  3. 'I' Profile / Liquidity Void — enter LVN and target far edge
  4. Synthetic Futures — ATM CE+PE structure suggestion for execution/hedging

Research / education only — not financial advice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.pro_trade_shared import ConfidenceScore, atr as _atr_ind, rsi as _rsi_ind, sl_tp_pct
from app.trading_hubs.smart_money_shared import hold_for_tf

logger = logging.getLogger(__name__)

YOUTUBE_URL = "https://youtu.be/67u8mdQ8f08"
STRATEGY_NAME = "Volume Profile CE"


@dataclass
class VolumeProfileCeConfig:
    num_bins: int = 50
    value_area_pct: float = 0.70
    # Session / intraday VP for Value Area Reversal + LVN
    intraday_tf: str = "15m"
    intraday_limit: int = 400
    val_touch_tol_pct: float = 0.15  # % of price — how close to VAL/VAH counts as touch
    hammer_wick_body_mult: float = 2.0
    # Daily POC compression
    daily_tf: str = "1d"
    daily_limit: int = 60
    compression_days: int = 3
    compression_threshold_pct: float = 0.20  # max POC range as % of min POC (0.2% ≈ Nifty 10–20 pts at 20k)
    # LVN
    lvn_threshold_pct: float = 0.10
    lvn_edge_frac: float = 0.15  # fraction of bin height considered "entering" the void
    # Synthetic futures (optional chain lookup for known indices)
    suggest_synthetic: bool = True


def calculate_volume_profile(
    df: pd.DataFrame,
    *,
    num_bins: int = 50,
    value_area_pct: float = 0.70,
) -> tuple[float | None, float | None, float | None, pd.DataFrame]:
    """
    POC / VAH / VAL for a session (or day) of OHLCV bars.
    Expects lowercase columns: open, high, low, close, volume.
    """
    if df is None or df.empty:
        return None, None, None, pd.DataFrame()

    work = df.copy()
    for col in ("close", "volume"):
        if col not in work.columns:
            return None, None, None, pd.DataFrame()

    min_price = float(work["low"].min() if "low" in work.columns else work["close"].min())
    max_price = float(work["high"].max() if "high" in work.columns else work["close"].max())
    if not np.isfinite(min_price) or not np.isfinite(max_price) or max_price <= min_price:
        return None, None, None, pd.DataFrame()

    bins = np.linspace(min_price, max_price, max(num_bins, 5) + 1)
    work = work.copy()
    work["price_bin"] = pd.cut(work["close"], bins=bins, include_lowest=True)
    vp = work.groupby("price_bin", observed=False)["volume"].sum().reset_index()
    vp = vp.rename(columns={"volume": "Volume", "price_bin": "Price_Bin"})
    vp["Mid_Price"] = vp["Price_Bin"].apply(lambda x: float(x.mid) if pd.notna(x) else np.nan)
    vp = vp.dropna(subset=["Mid_Price"]).reset_index(drop=True)
    if vp.empty or float(vp["Volume"].sum()) <= 0:
        return None, None, None, vp

    poc_idx = int(vp["Volume"].idxmax())
    poc = float(vp.loc[poc_idx, "Mid_Price"])

    total_volume = float(vp["Volume"].sum())
    va_volume_target = total_volume * value_area_pct
    va_volume = float(vp.loc[poc_idx, "Volume"])
    up_idx = poc_idx + 1
    down_idx = poc_idx - 1

    while va_volume < va_volume_target:
        up_vol = float(vp.loc[up_idx, "Volume"]) if up_idx < len(vp) else 0.0
        down_vol = float(vp.loc[down_idx, "Volume"]) if down_idx >= 0 else 0.0
        if up_vol <= 0 and down_vol <= 0:
            break
        if up_vol >= down_vol:
            va_volume += up_vol
            up_idx += 1
        else:
            va_volume += down_vol
            down_idx -= 1

    vah_i = min(max(up_idx - 1, 0), len(vp) - 1)
    val_i = max(down_idx + 1, 0)
    vah = float(vp.loc[vah_i, "Mid_Price"])
    val = float(vp.loc[val_i, "Mid_Price"])
    if val > vah:
        val, vah = vah, val
    return poc, vah, val, vp


def _is_hammer(candle: pd.Series, wick_body_mult: float) -> bool:
    o = float(candle["open"])
    h = float(candle["high"])
    l = float(candle["low"])
    c = float(candle["close"])
    body = abs(c - o)
    if body <= 0:
        body = max((h - l) * 0.01, 1e-9)
    lower_wick = min(o, c) - l
    upper_wick = h - max(o, c)
    mid = (h + l) / 2.0
    return lower_wick >= wick_body_mult * body and c >= mid and upper_wick <= body


def _is_shooting_star(candle: pd.Series, wick_body_mult: float) -> bool:
    o = float(candle["open"])
    h = float(candle["high"])
    l = float(candle["low"])
    c = float(candle["close"])
    body = abs(c - o)
    if body <= 0:
        body = max((h - l) * 0.01, 1e-9)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    mid = (h + l) / 2.0
    return upper_wick >= wick_body_mult * body and c <= mid and lower_wick <= body


def setup_va_reversal(
    candle: pd.Series,
    *,
    val: float,
    poc: float,
    vah: float,
    tolerance_pct: float,
    wick_body_mult: float,
    context_df: pd.DataFrame | None = None,
    intraday_tf: str = "15m",
) -> dict[str, Any] | None:
    """Bounce at VAL (long) or rejection at VAH (short), confidence-scored on
    volume strength, RSI extreme, wick quality, and touch precision — not
    just a binary pattern match."""
    close_price = float(candle["close"])
    low_price = float(candle["low"])
    high_price = float(candle["high"])
    open_price = float(candle["open"])
    body = abs(close_price - open_price)

    near_val = abs(low_price - val) / max(val, 1e-9) * 100.0 <= tolerance_pct
    near_vah = abs(high_price - vah) / max(vah, 1e-9) * 100.0 <= tolerance_pct

    # Confluence context: recent volume average and RSI, computed on the
    # fuller intraday series (not just the session slice) for a stable read
    # even early in the session.
    vol_ratio = None
    rsi_val = None
    if context_df is not None and len(context_df) >= 10 and "volume" in context_df.columns:
        recent_vol = context_df["volume"].iloc[-20:]
        avg_vol = float(recent_vol.mean()) if len(recent_vol) else 0.0
        last_vol = float(candle.get("volume") or 0)
        if avg_vol > 0:
            vol_ratio = last_vol / avg_vol
        rsi_series = _rsi_ind(context_df["close"], 14).dropna()
        if not rsi_series.empty:
            rsi_val = float(rsi_series.iloc[-1])

    if near_val and _is_hammer(candle, wick_body_mult):
        lower_wick = min(open_price, close_price) - low_price
        touch_dist_pct = abs(low_price - val) / max(val, 1e-9) * 100.0
        score = ConfidenceScore(40, "VAL touch + hammer/pin-bar rejection candle")
        score.add(vol_ratio is not None and vol_ratio >= 1.3, 15, f"rejection volume {vol_ratio:.1f}x the 20-bar average" if vol_ratio else "")
        score.add(rsi_val is not None and rsi_val <= 35, 15, f"RSI({14}) at {rsi_val:.0f} — oversold, momentum extended down" if rsi_val is not None else "")
        score.add(body > 0 and lower_wick >= wick_body_mult * 1.5 * body, 10, "exceptionally long rejection wick, well beyond the minimum")
        score.add(touch_dist_pct <= tolerance_pct / 2, 10, "very precise touch of VAL, not a loose match")
        confidence, reasons = score.finalize()
        entry, stop_loss, target = close_price, round(low_price * 0.999, 4), round(poc, 4)
        sl_pct, tp_pct = sl_tp_pct("LONG", entry, stop_loss, target)
        _, tp2_pct = sl_tp_pct("LONG", entry, None, vah)
        return {
            "setup": "value_area_reversal",
            "signal": "BUY",
            "direction": "LONG",
            "entry": entry,
            "stop_loss": stop_loss,
            "target_1": target,
            "target_2": round(vah, 4),
            "confidence_pct": confidence,
            "sl_pct": sl_pct,
            "tp_pct": tp_pct,
            "tp2_pct": tp2_pct,
            "hold_duration": hold_for_tf(intraday_tf, "intraday"),
            "logic": "VAL touch + hammer/pin-bar rejection → mean reversion toward POC then VAH",
            "reasons": reasons,
            "levels": {"val": val, "poc": poc, "vah": vah},
        }
    if near_vah and _is_shooting_star(candle, wick_body_mult):
        upper_wick = high_price - max(open_price, close_price)
        touch_dist_pct = abs(high_price - vah) / max(vah, 1e-9) * 100.0
        score = ConfidenceScore(40, "VAH touch + shooting-star rejection candle")
        score.add(vol_ratio is not None and vol_ratio >= 1.3, 15, f"rejection volume {vol_ratio:.1f}x the 20-bar average" if vol_ratio else "")
        score.add(rsi_val is not None and rsi_val >= 65, 15, f"RSI(14) at {rsi_val:.0f} — overbought, momentum extended up" if rsi_val is not None else "")
        score.add(body > 0 and upper_wick >= wick_body_mult * 1.5 * body, 10, "exceptionally long rejection wick, well beyond the minimum")
        score.add(touch_dist_pct <= tolerance_pct / 2, 10, "very precise touch of VAH, not a loose match")
        confidence, reasons = score.finalize()
        entry, stop_loss, target = close_price, round(high_price * 1.001, 4), round(poc, 4)
        sl_pct, tp_pct = sl_tp_pct("SHORT", entry, stop_loss, target)
        _, tp2_pct = sl_tp_pct("SHORT", entry, None, val)
        return {
            "setup": "value_area_reversal",
            "signal": "SELL",
            "direction": "SHORT",
            "entry": entry,
            "stop_loss": stop_loss,
            "target_1": target,
            "target_2": round(val, 4),
            "confidence_pct": confidence,
            "sl_pct": sl_pct,
            "tp_pct": tp_pct,
            "tp2_pct": tp2_pct,
            "hold_duration": hold_for_tf(intraday_tf, "intraday"),
            "logic": "VAH touch + shooting-star rejection → mean reversion toward POC then VAL",
            "reasons": reasons,
            "levels": {"val": val, "poc": poc, "vah": vah},
        }
    return None


def setup_poc_compression(
    historical_pocs: list[float],
    current_price: float,
    *,
    days: int,
    compression_threshold_pct: float,
    daily_df: pd.DataFrame | None = None,
    daily_tf: str = "1d",
) -> dict[str, Any] | None:
    if len(historical_pocs) < days:
        return None
    recent = historical_pocs[-days:]
    max_poc = max(recent)
    min_poc = min(recent)
    if min_poc <= 0:
        return None
    span_pct = (max_poc - min_poc) / min_poc * 100.0
    is_compressed = span_pct <= compression_threshold_pct
    if not is_compressed:
        return {
            "setup": "poc_compression",
            "signal": "WAIT",
            "direction": None,
            "compressed": False,
            "poc_span_pct": round(span_pct, 4),
            "merged_poc_low": round(min_poc, 4),
            "merged_poc_high": round(max_poc, 4),
            "logic": f"POCs not compressed (span {span_pct:.3f}% > {compression_threshold_pct}%)",
        }

    # Confluence context: breakout-day volume vs recent average, and whether
    # a short EMA trend already leans the same direction as the break.
    vol_ratio = None
    trend_up = None
    atr_last = None
    if daily_df is not None and len(daily_df) >= 10 and "volume" in daily_df.columns:
        recent_vol = daily_df["volume"].iloc[-20:]
        avg_vol = float(recent_vol.mean()) if len(recent_vol) else 0.0
        last_vol = float(daily_df["volume"].iloc[-1] or 0)
        if avg_vol > 0:
            vol_ratio = last_vol / avg_vol
        ema20 = daily_df["close"].ewm(span=20, adjust=False).mean()
        if not ema20.dropna().empty:
            trend_up = float(daily_df["close"].iloc[-1]) > float(ema20.iloc[-1])
        atr_series = _atr_ind(daily_df, 14).dropna()
        if not atr_series.empty:
            atr_last = float(atr_series.iloc[-1])

    hold = hold_for_tf(daily_tf, "swing" if daily_tf not in ("1m", "5m", "15m", "30m", "1h") else "intraday")

    if current_price > max_poc:
        score = ConfidenceScore(45, f"POC compression breakout above merged zone (span {span_pct:.3f}%)")
        score.add(span_pct <= compression_threshold_pct / 2, 15, "extremely tight compression before the break — more explosive potential")
        score.add(vol_ratio is not None and vol_ratio >= 1.4, 15, f"breakout volume {vol_ratio:.1f}x the 20-day average, not a fakeout" if vol_ratio else "")
        score.add(atr_last is not None and (current_price - max_poc) > atr_last * 0.15, 10, "clean break with room beyond the zone, not a marginal poke")
        score.add(bool(trend_up), 5, "short-term (20 EMA) trend already leans bullish")
        confidence, reasons = score.finalize()
        entry, stop_loss = current_price, round(min_poc, 4)
        sl_pct, _ = sl_tp_pct("LONG", entry, stop_loss, None)
        target = round(entry + (entry - stop_loss) * 2, 4)
        _, tp_pct = sl_tp_pct("LONG", entry, None, target)
        return {
            "setup": "poc_compression",
            "signal": "BREAKOUT_BUY",
            "direction": "LONG",
            "compressed": True,
            "entry": entry,
            "stop_loss": stop_loss,
            "target_1": target,
            "target_2": None,
            "confidence_pct": confidence,
            "sl_pct": sl_pct,
            "tp_pct": tp_pct,
            "hold_duration": hold,
            "poc_span_pct": round(span_pct, 4),
            "merged_poc_low": round(min_poc, 4),
            "merged_poc_high": round(max_poc, 4),
            "recent_pocs": [round(p, 4) for p in recent],
            "logic": "POC compression breakout above merged zone — prefer synthetic futures over naked option buying",
            "reasons": reasons,
        }
    if current_price < min_poc:
        score = ConfidenceScore(45, f"POC compression breakdown below merged zone (span {span_pct:.3f}%)")
        score.add(span_pct <= compression_threshold_pct / 2, 15, "extremely tight compression before the break — more explosive potential")
        score.add(vol_ratio is not None and vol_ratio >= 1.4, 15, f"breakdown volume {vol_ratio:.1f}x the 20-day average, not a fakeout" if vol_ratio else "")
        score.add(atr_last is not None and (min_poc - current_price) > atr_last * 0.15, 10, "clean break with room beyond the zone, not a marginal poke")
        score.add(trend_up is False, 5, "short-term (20 EMA) trend already leans bearish")
        confidence, reasons = score.finalize()
        entry, stop_loss = current_price, round(max_poc, 4)
        sl_pct, _ = sl_tp_pct("SHORT", entry, stop_loss, None)
        target = round(entry - (stop_loss - entry) * 2, 4)
        _, tp_pct = sl_tp_pct("SHORT", entry, None, target)
        return {
            "setup": "poc_compression",
            "signal": "BREAKDOWN_SELL",
            "direction": "SHORT",
            "compressed": True,
            "entry": entry,
            "stop_loss": stop_loss,
            "target_1": target,
            "target_2": None,
            "confidence_pct": confidence,
            "sl_pct": sl_pct,
            "tp_pct": tp_pct,
            "hold_duration": hold,
            "poc_span_pct": round(span_pct, 4),
            "merged_poc_low": round(min_poc, 4),
            "merged_poc_high": round(max_poc, 4),
            "recent_pocs": [round(p, 4) for p in recent],
            "logic": "POC compression breakdown below merged zone — prefer synthetic futures over naked option buying",
            "reasons": reasons,
        }
    return {
        "setup": "poc_compression",
        "signal": "WATCH",
        "direction": None,
        "compressed": True,
        "entry": current_price,
        "poc_span_pct": round(span_pct, 4),
        "merged_poc_low": round(min_poc, 4),
        "merged_poc_high": round(max_poc, 4),
        "recent_pocs": [round(p, 4) for p in recent],
        "logic": "POCs compressed — wait for decisive break of merged zone",
    }


def setup_liquidity_void(
    vp_df: pd.DataFrame,
    current_price: float,
    *,
    lvn_threshold_pct: float,
    edge_frac: float,
    context_df: pd.DataFrame | None = None,
    intraday_tf: str = "15m",
) -> dict[str, Any] | None:
    if vp_df is None or vp_df.empty or "Volume" not in vp_df.columns:
        return None
    max_vol = float(vp_df["Volume"].max())
    if max_vol <= 0:
        return None
    work = vp_df.copy()
    work["is_lvn"] = work["Volume"] < (max_vol * lvn_threshold_pct)
    lvns = work[work["is_lvn"]]
    if lvns.empty:
        return None

    atr_last = None
    momentum_up = None
    vol_ratio = None
    if context_df is not None and len(context_df) >= 5:
        atr_series = _atr_ind(context_df, 14).dropna()
        if not atr_series.empty:
            atr_last = float(atr_series.iloc[-1])
        tail3 = context_df["close"].iloc[-4:]
        if len(tail3) >= 2:
            momentum_up = float(tail3.iloc[-1]) > float(tail3.iloc[0])
        if "volume" in context_df.columns and len(context_df) >= 20:
            recent_vol = context_df["volume"].iloc[-20:]
            avg_vol = float(recent_vol.mean())
            last_vol = float(context_df["volume"].iloc[-1] or 0)
            if avg_vol > 0:
                vol_ratio = last_vol / avg_vol

    hold = hold_for_tf(intraday_tf, "intraday")

    for _, row in lvns.iterrows():
        bin_obj = row["Price_Bin"]
        try:
            bin_top = float(bin_obj.right)
            bin_bottom = float(bin_obj.left)
        except Exception:
            continue
        height = max(bin_top - bin_bottom, 1e-9)
        void_width_pct = (height / current_price * 100) if current_price else 0
        # Entering from below → fast long toward top of void
        if bin_bottom <= current_price <= bin_bottom + height * edge_frac:
            score = ConfidenceScore(40, "price entering a low-volume 'I' profile void from below")
            score.add(atr_last is not None and height >= atr_last * 0.8, 20, f"void spans {void_width_pct:.2f}% of price — a wide, tradeable gap" if atr_last else "")
            score.add(bool(momentum_up), 15, "recent bars already moving up into the void")
            score.add(vol_ratio is not None and vol_ratio < 0.8, 15, "current volume is thin, confirming little resistance ahead" if vol_ratio is not None else "")
            confidence, reasons = score.finalize()
            entry, stop_loss, target = current_price, round(bin_bottom * 0.998, 4), round(bin_top, 4)
            sl_pct, tp_pct = sl_tp_pct("LONG", entry, stop_loss, target)
            return {
                "setup": "i_profile_lvn",
                "signal": "FAST_LONG",
                "direction": "LONG",
                "entry": entry,
                "stop_loss": stop_loss,
                "target_1": target,
                "target_2": None,
                "confidence_pct": confidence,
                "sl_pct": sl_pct,
                "tp_pct": tp_pct,
                "hold_duration": hold,
                "logic": "Price entering low-volume 'I' profile / liquidity void from below — expect fast slice upward",
                "reasons": reasons,
                "void": {"low": round(bin_bottom, 4), "high": round(bin_top, 4)},
            }
        # Entering from above → fast short toward bottom
        if bin_top - height * edge_frac <= current_price <= bin_top:
            score = ConfidenceScore(40, "price entering a low-volume 'I' profile void from above")
            score.add(atr_last is not None and height >= atr_last * 0.8, 20, f"void spans {void_width_pct:.2f}% of price — a wide, tradeable gap" if atr_last else "")
            score.add(momentum_up is False, 15, "recent bars already moving down into the void")
            score.add(vol_ratio is not None and vol_ratio < 0.8, 15, "current volume is thin, confirming little resistance ahead" if vol_ratio is not None else "")
            confidence, reasons = score.finalize()
            entry, stop_loss, target = current_price, round(bin_top * 1.002, 4), round(bin_bottom, 4)
            sl_pct, tp_pct = sl_tp_pct("SHORT", entry, stop_loss, target)
            return {
                "setup": "i_profile_lvn",
                "signal": "FAST_SHORT",
                "direction": "SHORT",
                "entry": entry,
                "stop_loss": stop_loss,
                "target_1": target,
                "target_2": None,
                "confidence_pct": confidence,
                "sl_pct": sl_pct,
                "tp_pct": tp_pct,
                "hold_duration": hold,
                "logic": "Price entering low-volume 'I' profile / liquidity void from above — expect fast slice downward",
                "reasons": reasons,
                "void": {"low": round(bin_bottom, 4), "high": round(bin_top, 4)},
            }
    return None


def suggest_synthetic_future(direction: str, underlying_price: float) -> dict[str, Any]:
    """ATM synthetic future structure (no live premiums required)."""
    # Round to nearest 50 for index-like, else 1% step heuristic for stocks
    if underlying_price >= 5000:
        step = 50.0
    elif underlying_price >= 500:
        step = 5.0
    else:
        step = 1.0
    atm = round(underlying_price / step) * step
    if direction == "LONG":
        return {
            "structure": "synthetic_long",
            "leg_1": f"BUY {atm:g} CE (ATM)",
            "leg_2": f"SELL {atm:g} PE (ATM)",
            "note": "Synthetic long future — capital efficient vs naked futures; hedge overnight; prefer ITM single-leg only for VA/POC bounces",
        }
    return {
        "structure": "synthetic_short",
        "leg_1": f"BUY {atm:g} PE (ATM)",
        "leg_2": f"SELL {atm:g} CE (ATM)",
        "note": "Synthetic short future — capital efficient vs naked futures; always hedge overnight swings",
    }


def _session_slice(df: pd.DataFrame) -> pd.DataFrame:
    """Prefer today's bars; else last calendar day present in the frame."""
    if df.empty:
        return df
    idx = df.index
    if not isinstance(idx, pd.DatetimeIndex):
        return df.tail(min(len(df), 40))
    try:
        # Localize-naive comparison on date
        dates = idx.normalize()
        last_day = dates[-1]
        session = df.loc[dates == last_day]
        if len(session) >= 8:
            return session
    except Exception:
        pass
    return df.tail(min(len(df), 40))


def _daily_poc_proxies(daily: pd.DataFrame) -> list[float]:
    if daily is None or daily.empty:
        return []
    return [float(row["close"]) for _, row in daily.iterrows()]


def _build_chart_data(df: pd.DataFrame, *, max_bars: int = 160) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    tail = df.iloc[-max_bars:]
    rows: list[dict[str, Any]] = []
    for idx, bar in tail.iterrows():
        rows.append({
            "time": str(idx),
            "open": round(float(bar["open"]), 6),
            "high": round(float(bar["high"]), 6),
            "low": round(float(bar["low"]), 6),
            "close": round(float(bar["close"]), 6),
            "volume": round(float(bar["volume"]), 2) if "volume" in bar and pd.notna(bar["volume"]) else None,
        })
    return rows


def _vp_histogram(vp: pd.DataFrame) -> list[dict[str, Any]]:
    if vp is None or vp.empty:
        return []
    out: list[dict[str, Any]] = []
    for _, row in vp.iterrows():
        mid = row.get("Mid_Price")
        vol = row.get("Volume")
        if mid is None or pd.isna(mid):
            continue
        out.append({
            "price": round(float(mid), 4),
            "volume": round(float(vol or 0), 2),
        })
    return out


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: VolumeProfileCeConfig,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "ticker": ticker,
        "strategy": STRATEGY_NAME,
        "youtube": YOUTUBE_URL,
        "error": None,
        "session_vp": None,
        "setups": [],
        "actionable": [],
        "execution": None,
        "rules": [
            "Never swing trade naked — hedge overnight (black swan risk).",
            "POC compression: prefer synthetic futures over naked option buying (theta decay while compressed).",
            "VA / POC bounce option buys: prefer ITM options (react better to volume levels than OTM).",
        ],
    }

    try:
        intra = fetch_data_for_gap_scan(
            ticker, cfg.intraday_tf, market,
            groww_token=groww_token, exchange=exchange, limit=cfg.intraday_limit,
        )
        daily = fetch_data_for_gap_scan(
            ticker, cfg.daily_tf, market,
            groww_token=groww_token, exchange=exchange, limit=cfg.daily_limit,
        )
    except Exception as exc:
        out["error"] = f"Data fetch failed: {exc}"
        return out

    if intra is None or intra.empty:
        out["error"] = "No intraday OHLCV"
        return out

    session = _session_slice(intra)
    poc, vah, val, vp = calculate_volume_profile(
        session, num_bins=cfg.num_bins, value_area_pct=cfg.value_area_pct,
    )
    if poc is None or vah is None or val is None:
        out["error"] = "Could not build session volume profile"
        return out

    last = session.iloc[-1]
    price = float(last["close"])
    out["ltp"] = price
    out["session_vp"] = {
        "poc": round(poc, 4),
        "vah": round(vah, 4),
        "val": round(val, 4),
        "bars": int(len(session)),
        "tf": cfg.intraday_tf,
        "session_date": str(session.index[-1].date()) if isinstance(session.index, pd.DatetimeIndex) else None,
        "value_area_pct": cfg.value_area_pct,
        "bin_count": int(len(vp)),
    }
    # Prefer a wider intraday window for the chart (session + recent context)
    chart_src = intra if len(intra) > len(session) else session
    out["chart_data"] = _build_chart_data(chart_src, max_bars=160)
    out["vp_histogram"] = _vp_histogram(vp)
    try:
        from app.market_pulse.pa_vp_smc_engine import PaVpSmcConfig, find_swing_sr_zones

        sr_cfg = PaVpSmcConfig(swing_window=5, lookback_bars=min(len(chart_src), 300))
        sr_zones = find_swing_sr_zones(chart_src, sr_cfg)
    except Exception:
        sr_zones = {}
    support = sr_zones.get("support")
    resistance = sr_zones.get("resistance")
    out["support_zone"] = [round(support["bottom"], 6), round(support["top"], 6)] if support else None
    out["resistance_zone"] = [round(resistance["bottom"], 6), round(resistance["top"], 6)] if resistance else None

    setups: list[dict[str, Any]] = []

    va = setup_va_reversal(
        last,
        val=val,
        poc=poc,
        vah=vah,
        tolerance_pct=cfg.val_touch_tol_pct,
        wick_body_mult=cfg.hammer_wick_body_mult,
        context_df=intra,
        intraday_tf=cfg.intraday_tf,
    )
    if va:
        setups.append(va)
    else:
        setups.append({
            "setup": "value_area_reversal",
            "signal": "WAIT",
            "direction": None,
            "logic": "No VAL/VAH rejection candle on last bar",
            "levels": {"val": round(val, 4), "poc": round(poc, 4), "vah": round(vah, 4)},
        })

    # Daily POC series: prefer daily closes as POC proxies when each row is one day
    poc_series = _daily_poc_proxies(daily if daily is not None else pd.DataFrame())
    # Also append today's session POC as latest
    if not poc_series or abs(poc_series[-1] - poc) / max(poc, 1e-9) > 0.001:
        poc_series.append(poc)

    comp = setup_poc_compression(
        poc_series,
        price,
        days=cfg.compression_days,
        compression_threshold_pct=cfg.compression_threshold_pct,
        daily_df=daily,
        daily_tf=cfg.daily_tf,
    )
    if comp:
        setups.append(comp)

    lvn = setup_liquidity_void(
        vp,
        price,
        lvn_threshold_pct=cfg.lvn_threshold_pct,
        edge_frac=cfg.lvn_edge_frac,
        context_df=intra,
        intraday_tf=cfg.intraday_tf,
    )
    if lvn:
        setups.append(lvn)
    else:
        setups.append({
            "setup": "i_profile_lvn",
            "signal": "WAIT",
            "direction": None,
            "logic": "Price not at the edge of a low-volume node on session profile",
        })

    out["setups"] = setups
    actionable = [
        s for s in setups
        if s.get("signal") not in (None, "WAIT", "WATCH") and s.get("direction")
    ]
    out["actionable"] = actionable
    out["direction"] = actionable[0].get("direction") if actionable else None

    if cfg.suggest_synthetic and actionable:
        # Prefer first actionable direction
        direction = actionable[0].get("direction") or "LONG"
        out["execution"] = suggest_synthetic_future(direction, price)
    elif cfg.suggest_synthetic:
        out["execution"] = {
            "structure": "standby",
            "note": "No actionable VP setup — stand by. When trading overnight, use hedged / synthetic futures, not naked futures.",
        }

    out["verdict"] = "TAKE" if actionable else "WAIT"
    out["take_trade"] = bool(actionable)
    return out


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: VolumeProfileCeConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or VolumeProfileCeConfig()
    results = []
    for t in tickers:
        try:
            results.append(
                analyze_ticker(t, market, cfg=cfg, groww_token=groww_token, exchange=exchange)
            )
        except Exception as exc:
            logger.exception("Volume Profile CE failed for %s", t)
            results.append({"ticker": t, "error": str(exc), "setups": [], "actionable": [], "take_trade": False})

    entry_count = sum(1 for r in results if r.get("take_trade"))
    return {
        "strategy": STRATEGY_NAME,
        "youtube": YOUTUBE_URL,
        "results": results,
        "entry_count": entry_count,
        "scanned": len(results),
        "config": {
            "intraday_tf": cfg.intraday_tf,
            "daily_tf": cfg.daily_tf,
            "num_bins": cfg.num_bins,
            "value_area_pct": cfg.value_area_pct,
            "compression_days": cfg.compression_days,
            "compression_threshold_pct": cfg.compression_threshold_pct,
            "val_touch_tol_pct": cfg.val_touch_tol_pct,
            "lvn_threshold_pct": cfg.lvn_threshold_pct,
        },
        "disclaimer": "Research / education only — not financial advice.",
    }
