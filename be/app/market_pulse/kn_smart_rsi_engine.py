"""
kn_smart_rsi_engine.py
----------------------
KN Smart DP SL + RSI MTF + VWMA Master Trend Strategy.

Intraday (3m/5m) entries filtered by daily VWMA master trend and
multi-timeframe EMA ribbon alignment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv

MTF_DEFAULT = ["1m", "5m", "15m", "1h"]
INTRADAY_OPTIONS = ["3m", "5m"]

PHASE_PRIORITY = {
    "BUY_SIGNAL": 100,
    "SELL_SIGNAL": 100,
    "EXIT_SIGNAL": 85,
    "APPROACHING_BUY": 72,
    "APPROACHING_SELL": 72,
    "TREND_ALIGNED": 55,
    "SIDEWAYS": 20,
    "NEUTRAL": 15,
    "NO_DATA": 0,
}


class Trend(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    SIDEWAYS = "sideways"


class Signal(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    EXIT = "EXIT"


@dataclass
class StrategyConfig:
    fast_ema: int = 5
    slow_ema: int = 12
    atr_period: int = 14
    atr_multiplier: float = 1.5
    rsi_length: int = 14
    rsi_upper: float = 80.0
    rsi_middle: float = 50.0
    rsi_lower: float = 30.0
    rsi_sma_period: int = 14
    vwma_period: int = 20
    tp_ratios: list[float] = field(default_factory=lambda: [1.0, 2.0, 3.0])
    mtf_min_bullish: int = 3
    mtf_min_bearish: int = 3


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


def atr(df: pd.DataFrame, period: int) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def vwma(df: pd.DataFrame, period: int) -> pd.Series:
    vol = df["volume"].replace(0, np.nan)
    pv = df["close"] * vol
    return pv.rolling(period).sum() / vol.rolling(period).sum()


def _resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    if df.empty:
        return df
    return df.resample(rule).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()


def fetch_tf_data(
    symbol: str,
    tf: str,
    market: str,
    groww_token: str = "",
    exchange: str = "NSE",
    limit: int = 400,
) -> pd.DataFrame:
    if tf == "3m":
        raw = fetch_data_for_gap_scan(symbol, "1m", market, groww_token, exchange, limit=limit * 3)
        raw = normalize_ohlcv(raw)
        if raw.empty:
            raw = fetch_data_for_gap_scan(symbol, "5m", market, groww_token, exchange, limit=limit)
            raw = normalize_ohlcv(raw)
            if not raw.empty:
                return raw.tail(limit)
        return _resample_ohlcv(raw, "3min").tail(limit)

    df = fetch_data_for_gap_scan(symbol, tf, market, groww_token, exchange, limit=limit)
    return normalize_ohlcv(df).tail(limit)


def kn_smart_signals(df: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    out = df.copy()
    out["fast_ema"] = ema(out["close"], cfg.fast_ema)
    out["slow_ema"] = ema(out["close"], cfg.slow_ema)
    out["atr_val"] = atr(out, cfg.atr_period)
    out["entry_line"] = (out["fast_ema"] + out["slow_ema"]) / 2

    trail_sl = [np.nan] * len(out)
    for i in range(1, len(out)):
        atr_v = out["atr_val"].iloc[i] * cfg.atr_multiplier
        if out["close"].iloc[i] > out["entry_line"].iloc[i]:
            sl = out["close"].iloc[i] - atr_v
            prev = trail_sl[i - 1]
            trail_sl[i] = max(sl, prev if not np.isnan(prev) else sl)
        else:
            sl = out["close"].iloc[i] + atr_v
            prev = trail_sl[i - 1]
            trail_sl[i] = min(sl, prev if not np.isnan(prev) else sl)
    out["trail_sl"] = trail_sl
    out["tp1"] = out["close"] + out["atr_val"] * cfg.tp_ratios[0]
    out["tp2"] = out["close"] + out["atr_val"] * cfg.tp_ratios[1]
    out["tp3"] = out["close"] + out["atr_val"] * cfg.tp_ratios[2]
    return out


def rsi_sma_signals(df: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    out = df.copy()
    out["rsi"] = rsi(out["close"], cfg.rsi_length)
    out["rsi_sma"] = sma(out["rsi"], cfg.rsi_sma_period)
    out["rsi_bullish"] = (out["rsi"] > out["rsi_sma"]) & (out["rsi"] > cfg.rsi_middle)
    out["rsi_bearish"] = (out["rsi"] < out["rsi_sma"]) & (out["rsi"] < cfg.rsi_middle)
    out["rsi_overbought"] = out["rsi"] >= cfg.rsi_upper
    out["rsi_oversold"] = out["rsi"] <= cfg.rsi_lower
    return out


def master_trend(daily_df: pd.DataFrame, cfg: StrategyConfig) -> Trend:
    daily = daily_df.copy()
    if "volume" not in daily.columns or daily["volume"].sum() == 0:
        daily["volume"] = 1.0
    daily["vwma"] = vwma(daily, cfg.vwma_period)

    if daily["vwma"].iloc[-1] != daily["vwma"].iloc[-1]:  # NaN check
        return Trend.SIDEWAYS

    last_close = float(daily["close"].iloc[-1])
    last_vwma = float(daily["vwma"].iloc[-1])

    slope_window = 5
    if len(daily) >= slope_window:
        vwma_vals = daily["vwma"].iloc[-slope_window:]
        slope = (vwma_vals.iloc[-1] - vwma_vals.iloc[0]) / slope_window
        price_range = daily["close"].iloc[-slope_window:].max() - daily["close"].iloc[-slope_window:].min()
        flat_threshold = price_range * 0.05 if price_range > 0 else 0
        if abs(slope) < flat_threshold:
            return Trend.SIDEWAYS

    if last_close > last_vwma:
        return Trend.BULLISH
    if last_close < last_vwma:
        return Trend.BEARISH
    return Trend.SIDEWAYS


def mtf_dashboard(timeframe_dfs: dict[str, pd.DataFrame], cfg: StrategyConfig) -> dict[str, Any]:
    results: dict[str, str] = {}
    for tf, df in timeframe_dfs.items():
        if df is None or df.empty or len(df) < cfg.slow_ema + 2:
            results[tf] = "unknown"
            continue
        enriched = kn_smart_signals(df, cfg)
        last = enriched.iloc[-1]
        results[tf] = "bullish" if last["fast_ema"] > last["slow_ema"] else "bearish"

    known = {k: v for k, v in results.items() if v != "unknown"}
    bullish_count = sum(1 for v in known.values() if v == "bullish")
    bearish_count = sum(1 for v in known.values() if v == "bearish")
    return {
        "timeframes": results,
        "bullish_count": bullish_count,
        "bearish_count": bearish_count,
        "total": len(known),
    }


class Strategy:
    def __init__(self, cfg: StrategyConfig | None = None):
        self.cfg = cfg or StrategyConfig()

    def run(
        self,
        intraday_df: pd.DataFrame,
        daily_df: pd.DataFrame,
        timeframe_dfs: dict[str, pd.DataFrame] | None = None,
    ) -> pd.DataFrame:
        cfg = self.cfg
        trend = master_trend(daily_df, cfg)
        df = rsi_sma_signals(kn_smart_signals(intraday_df, cfg), cfg)

        if timeframe_dfs:
            mtf = mtf_dashboard(timeframe_dfs, cfg)
            mtf_bull = mtf["bullish_count"]
            mtf_bear = mtf["bearish_count"]
        else:
            mtf_bull = cfg.mtf_min_bullish
            mtf_bear = cfg.mtf_min_bearish
            mtf = {"timeframes": {}, "bullish_count": mtf_bull, "bearish_count": mtf_bear, "total": 0}

        signals: list[str] = []
        actions: list[str] = []

        for i in range(len(df)):
            row = df.iloc[i]
            signal = Signal.HOLD
            action = ""

            if trend == Trend.SIDEWAYS:
                signals.append(Signal.HOLD.value)
                actions.append("AVOID: Market sideways (VWMA flat)")
                continue

            if row["rsi_overbought"] and trend == Trend.BULLISH:
                signal = Signal.EXIT
                action = "EXIT LONG: RSI > 80 overbought"
            elif row["rsi_oversold"] and trend == Trend.BEARISH:
                signal = Signal.EXIT
                action = "EXIT SHORT: RSI < 30 oversold"
            elif trend == Trend.BULLISH:
                ribbon_ok = row["fast_ema"] > row["slow_ema"]
                candle_ok = row["close"] > row["entry_line"] and (row["close"] - row["open"]) > 0
                rsi_ok = bool(row["rsi_bullish"])
                mtf_ok = mtf_bull >= cfg.mtf_min_bullish
                if ribbon_ok and candle_ok and rsi_ok and mtf_ok:
                    signal = Signal.BUY
                    action = (
                        f"BUY | entry={row['close']:.4f} | SL={row['trail_sl']:.4f} | "
                        f"TP1={row['tp1']:.4f} | TP2={row['tp2']:.4f} | TP3={row['tp3']:.4f}"
                    )
            elif trend == Trend.BEARISH:
                ribbon_ok = row["slow_ema"] > row["fast_ema"]
                candle_ok = row["close"] < row["entry_line"] and (row["open"] - row["close"]) > 0
                rsi_ok = bool(row["rsi_bearish"])
                mtf_ok = mtf_bear >= cfg.mtf_min_bearish
                if ribbon_ok and candle_ok and rsi_ok and mtf_ok:
                    signal = Signal.SELL
                    short_tp1 = row["close"] - row["atr_val"] * cfg.tp_ratios[0]
                    short_tp2 = row["close"] - row["atr_val"] * cfg.tp_ratios[1]
                    short_tp3 = row["close"] - row["atr_val"] * cfg.tp_ratios[2]
                    action = (
                        f"SELL | entry={row['close']:.4f} | SL={row['trail_sl']:.4f} | "
                        f"TP1={short_tp1:.4f} | TP2={short_tp2:.4f} | TP3={short_tp3:.4f}"
                    )

            signals.append(signal.value)
            actions.append(action)

        df = df.copy()
        df["master_trend"] = trend.value
        df["signal"] = signals
        df["action"] = actions
        df.attrs["mtf"] = mtf
        return df

    def evaluate_bar(
        self,
        intraday_df: pd.DataFrame,
        daily_df: pd.DataFrame,
        timeframe_dfs: dict[str, pd.DataFrame] | None = None,
    ) -> dict[str, Any]:
        result_df = self.run(intraday_df, daily_df, timeframe_dfs)
        last = result_df.iloc[-1]
        mtf = result_df.attrs.get("mtf", {})
        cfg = self.cfg
        trend = Trend(last["master_trend"])

        short_tp = None
        if trend == Trend.BEARISH:
            short_tp = {
                "tp1": float(last["close"] - last["atr_val"] * cfg.tp_ratios[0]),
                "tp2": float(last["close"] - last["atr_val"] * cfg.tp_ratios[1]),
                "tp3": float(last["close"] - last["atr_val"] * cfg.tp_ratios[2]),
            }

        return {
            "timestamp": str(last.name),
            "close": float(last["close"]),
            "master_trend": last["master_trend"],
            "signal": last["signal"],
            "action": last["action"],
            "fast_ema": float(last["fast_ema"]),
            "slow_ema": float(last["slow_ema"]),
            "entry_line": float(last["entry_line"]),
            "rsi": float(last["rsi"]),
            "rsi_sma": float(last["rsi_sma"]),
            "trail_sl": float(last["trail_sl"]) if last["trail_sl"] == last["trail_sl"] else None,
            "tp1": float(last["tp1"]),
            "tp2": float(last["tp2"]),
            "tp3": float(last["tp3"]),
            "short_tp": short_tp,
            "atr": float(last["atr_val"]),
            "overbought": bool(last["rsi_overbought"]),
            "oversold": bool(last["rsi_oversold"]),
            "rsi_bullish": bool(last["rsi_bullish"]),
            "rsi_bearish": bool(last["rsi_bearish"]),
            "mtf": mtf,
            "conditions": _entry_conditions(last, trend, mtf, cfg),
        }


def _entry_conditions(row: pd.Series, trend: Trend, mtf: dict, cfg: StrategyConfig) -> dict[str, bool]:
    if trend == Trend.BULLISH:
        return {
            "master_trend": True,
            "ema_ribbon": row["fast_ema"] > row["slow_ema"],
            "candle": row["close"] > row["entry_line"] and (row["close"] - row["open"]) > 0,
            "rsi": bool(row["rsi_bullish"]),
            "mtf": mtf.get("bullish_count", 0) >= cfg.mtf_min_bullish,
        }
    if trend == Trend.BEARISH:
        return {
            "master_trend": True,
            "ema_ribbon": row["slow_ema"] > row["fast_ema"],
            "candle": row["close"] < row["entry_line"] and (row["open"] - row["close"]) > 0,
            "rsi": bool(row["rsi_bearish"]),
            "mtf": mtf.get("bearish_count", 0) >= cfg.mtf_min_bearish,
        }
    return {
        "master_trend": False,
        "ema_ribbon": False,
        "candle": False,
        "rsi": False,
        "mtf": False,
    }


def _confidence_from_conditions(conds: dict[str, bool], signal: str) -> float:
    if signal in ("BUY", "SELL"):
        return 88.0
    if signal == "EXIT":
        return 80.0
    n = sum(1 for v in conds.values() if v)
    return round(min(75.0, 25.0 + n * 12), 1)


def _phase_from_live(live: dict[str, Any]) -> tuple[str, str, bool]:
    signal = live.get("signal", "HOLD")
    trend = live.get("master_trend", "sideways")
    conds = live.get("conditions") or {}

    if signal == "BUY":
        return "BUY_SIGNAL", live.get("action") or "Intraday BUY — all conditions met", True
    if signal == "SELL":
        return "SELL_SIGNAL", live.get("action") or "Intraday SELL — all conditions met", True
    if signal == "EXIT":
        return "EXIT_SIGNAL", live.get("action") or "Exit signal on latest bar", True

    if trend == "sideways":
        return "SIDEWAYS", "Daily VWMA flat — avoid new trades", False

    n_met = sum(1 for v in conds.values() if v)
    if trend == "bullish":
        if n_met >= 4:
            return "APPROACHING_BUY", f"Bullish master trend — {n_met}/5 entry filters aligned", True
        if n_met >= 2:
            return "TREND_ALIGNED", f"Bullish bias — {n_met}/5 filters (waiting for full setup)", False
    if trend == "bearish":
        if n_met >= 4:
            return "APPROACHING_SELL", f"Bearish master trend — {n_met}/5 entry filters aligned", True
        if n_met >= 2:
            return "TREND_ALIGNED", f"Bearish bias — {n_met}/5 filters (waiting for full setup)", False

    return "NEUTRAL", "No aligned KN Smart setup on latest bar", False


def _build_trade_plan(live: dict[str, Any]) -> dict | None:
    signal = live.get("signal")
    price = live.get("close", 0)
    sl = live.get("trail_sl")
    if not price or sl is None:
        return None

    if signal == "SELL" or live.get("master_trend") == "bearish":
        stp = live.get("short_tp") or {}
        tp1 = stp.get("tp1", live.get("tp1"))
        direction = "SHORT"
    elif signal == "BUY" or live.get("master_trend") == "bullish":
        tp1 = live.get("tp1")
        direction = "LONG"
    else:
        return None

    tp2 = live.get("short_tp", {}).get("tp2") if direction == "SHORT" else live.get("tp2")
    tp3 = live.get("short_tp", {}).get("tp3") if direction == "SHORT" else live.get("tp3")
    if signal not in ("BUY", "SELL") and live.get("master_trend") not in ("bullish", "bearish"):
        return None

    sl_pct = abs(price - sl) / price * 100 if price else 0
    tp_pct = abs(tp1 - price) / price * 100 if tp1 and price else 0
    return {
        "direction": direction,
        "entry": round(price, 4),
        "stop_loss": round(sl, 4),
        "take_profit": round(tp1, 4) if tp1 else None,
        "tp2": round(tp2, 4) if tp2 else None,
        "tp3": round(tp3, 4) if tp3 else None,
        "sl_pct": round(sl_pct, 2),
        "tp_pct": round(tp_pct, 2),
        "tp2_pct": round(abs(tp2 - price) / price * 100, 2) if tp2 and price else None,
        "tp3_pct": round(abs(tp3 - price) / price * 100, 2) if tp3 and price else None,
        "hold_duration": "15 min – 3 hours (intraday)",
        "atr": live.get("atr"),
    }


def _signal_counts(result_df: pd.DataFrame) -> dict[str, int]:
    if result_df.empty or "signal" not in result_df.columns:
        return {"buy": 0, "sell": 0, "exit": 0}
    tail = result_df.tail(min(120, len(result_df)))
    return {
        "buy": int((tail["signal"] == "BUY").sum()),
        "sell": int((tail["signal"] == "SELL").sum()),
        "exit": int((tail["signal"] == "EXIT").sum()),
    }


def analyze_kn_smart(
    symbol: str,
    market: str,
    intraday_tf: str = "5m",
    mtf_timeframes: list[str] | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
    bars: int = 400,
    cfg: StrategyConfig | None = None,
) -> dict[str, Any]:
    """Full KN Smart analysis for one ticker."""
    cfg = cfg or StrategyConfig()
    mtf_tfs = mtf_timeframes or MTF_DEFAULT

    try:
        daily = fetch_tf_data(symbol, "1d", market, groww_token, exchange, limit=max(60, bars // 4))
        intraday = fetch_tf_data(symbol, intraday_tf, market, groww_token, exchange, limit=bars)
        mtf_dfs: dict[str, pd.DataFrame] = {}
        for tf in mtf_tfs:
            mtf_dfs[tf] = fetch_tf_data(symbol, tf, market, groww_token, exchange, limit=min(bars, 300))
    except Exception as exc:
        return {
            "symbol": symbol,
            "error": str(exc)[:200],
            "phase": "NO_DATA",
            "priority": 0,
            "confidence": 0,
            "actionable": False,
        }

    min_intraday = cfg.slow_ema + cfg.rsi_length + 10
    if intraday.empty or len(intraday) < min_intraday:
        return {
            "symbol": symbol,
            "error": f"Insufficient {intraday_tf} data ({len(intraday)} bars, need {min_intraday}+).",
            "phase": "NO_DATA",
            "priority": 0,
            "confidence": 0,
            "actionable": False,
        }
    if daily.empty or len(daily) < cfg.vwma_period + 5:
        return {
            "symbol": symbol,
            "error": f"Insufficient daily data for VWMA ({len(daily)} bars).",
            "phase": "NO_DATA",
            "priority": 0,
            "confidence": 0,
            "actionable": False,
        }

    strategy = Strategy(cfg)
    result_df = strategy.run(intraday, daily, mtf_dfs)
    live = strategy.evaluate_bar(intraday, daily, mtf_dfs)
    phase, primary_label, actionable = _phase_from_live(live)
    confidence = _confidence_from_conditions(live.get("conditions") or {}, live.get("signal", "HOLD"))
    trade_plan = _build_trade_plan(live)
    counts = _signal_counts(result_df)

    daily_vwma = vwma(daily if daily["volume"].sum() > 0 else daily.assign(volume=1.0), cfg.vwma_period)

    return {
        "symbol": symbol,
        "intraday_tf": intraday_tf,
        "mtf_timeframes": mtf_tfs,
        "phase": phase,
        "primary_label": primary_label,
        "priority": PHASE_PRIORITY.get(phase, 0),
        "confidence": confidence,
        "actionable": actionable,
        "live": live,
        "trade_plan": trade_plan,
        "signal_counts": counts,
        "result_df": result_df,
        "daily_df": daily,
        "master_trend": live.get("master_trend"),
        "daily_vwma": float(daily_vwma.iloc[-1]) if len(daily_vwma) else None,
        "price": live.get("close"),
    }
