"""
mtf_intraday_bias_engine.py
-----------------------------
Multi-timeframe intraday bullish / bearish composite scorer.
Indicators: RSI, MACD, Stochastic, EMA, Bollinger, Volume, Elliott,
Support/Resistance, PCR proxy, Price Action, Candlestick patterns.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
import pytz
from scipy.signal import argrelextrema

from app.market_pulse.crypto_session import CRYPTO_SESSION_LABEL, CRYPTO_SESSION_TZ
from app.market_pulse.indicators import (
    add_adx,
    add_bollinger_bands,
    add_cci,
    add_ema,
    add_macd,
    add_obv,
    add_roc,
    add_rsi,
    add_stochastic,
    add_vwap,
    add_vol_sma,
    add_williams_r,
)
from app.market_pulse.nse_index_yfinance import (
    NSE_INDEX_YF_TICKERS,
    index_yf_candidates,
    is_nse_index_symbol,
    stock_symbol_to_yf,
)

from app.market_pulse.mtf_scanner_engine import TF_ORDER, TIMEFRAMES as MTF_TF_LABELS

logger = logging.getLogger(__name__)

# Yahoo Finance fetch config per interval key
YF_FETCH_CONFIG: dict[str, dict[str, str]] = {
    "1m": {"period": "5d", "interval": "1m"},
    "5m": {"period": "5d", "interval": "5m"},
    "15m": {"period": "5d", "interval": "15m"},
    "30m": {"period": "1mo", "interval": "30m"},
    "1h": {"period": "30d", "interval": "1h"},
    "1d": {"period": "1y", "interval": "1d"},
    "1w": {"period": "2y", "interval": "1wk"},
}

TF_ROLES = ("HTF", "MTF", "LTF", "ULTF")
DEFAULT_TF_BY_ROLE: dict[str, str] = {
    "HTF": "1d",
    "MTF": "1h",
    "LTF": "15m",
    "ULTF": "5m",
}
ROLE_WEIGHTS: dict[str, float] = {
    "HTF": 0.25,
    "MTF": 0.30,
    "LTF": 0.25,
    "ULTF": 0.20,
}
SELECTABLE_INTERVALS = [tf for tf in TF_ORDER if tf in YF_FETCH_CONFIG]

# Legacy defaults (same as DEFAULT_TF_BY_ROLE values)
TIMEFRAMES = {role: YF_FETCH_CONFIG[DEFAULT_TF_BY_ROLE[role]] for role in TF_ROLES}
WEIGHTS = dict(ROLE_WEIGHTS)

BULLISH_THRESHOLD = 1.5
BEARISH_THRESHOLD = -1.5
DEFAULT_RR_RATIO = 2.0
ENTRY_ROLE_PREFERENCE = ("LTF", "ULTF", "MTF", "HTF")
NY_TZ = pytz.timezone("America/New_York")

DEFAULT_TICKERS = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
    "SBIN", "NIFTY 50", "NIFTY BANK",
]

DEFAULT_CRYPTO_TICKERS = [
    "BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT", "XRP-USDT",
]


def crypto_symbol_to_yf(ticker: str) -> str:
    """Map CoinDCX display symbol (BTC-USDT) to Yahoo Finance (BTC-USD)."""
    from app.market_pulse.gap_trading import _yfinance_symbol

    return _yfinance_symbol(ticker, is_crypto=True)


def resolve_yf_symbol(ticker: str, *, is_crypto: bool = False) -> str:
    t = (ticker or "").strip().upper()
    if not t:
        return t
    if is_crypto:
        return crypto_symbol_to_yf(t)
    if t in NSE_INDEX_YF_TICKERS:
        return NSE_INDEX_YF_TICKERS[t]
    if is_nse_index_symbol(t):
        cands = index_yf_candidates(t)
        if cands:
            return cands[0]
    if "." in t:
        return t
    return stock_symbol_to_yf(t)


def _interval_rank(interval: str) -> int:
    try:
        return TF_ORDER.index(interval)
    except ValueError:
        return -1


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = [str(c[0]).lower() if isinstance(c, tuple) else str(c).lower() for c in out.columns]
    else:
        out.columns = [str(c).lower() for c in out.columns]
    return out


def build_timeframe_config(
    htf: str = DEFAULT_TF_BY_ROLE["HTF"],
    mtf: str = DEFAULT_TF_BY_ROLE["MTF"],
    ltf: str = DEFAULT_TF_BY_ROLE["LTF"],
    ultf: str = DEFAULT_TF_BY_ROLE["ULTF"],
) -> dict[str, dict[str, Any]]:
    """Build role → yfinance fetch config for HTF / MTF / LTF / ULTF."""
    picks = {"HTF": htf, "MTF": mtf, "LTF": ltf, "ULTF": ultf}
    config: dict[str, dict[str, Any]] = {}
    for role in TF_ROLES:
        interval = picks.get(role) or DEFAULT_TF_BY_ROLE[role]
        if interval not in YF_FETCH_CONFIG:
            interval = DEFAULT_TF_BY_ROLE[role]
        yf_cfg = YF_FETCH_CONFIG[interval]
        label_meta = MTF_TF_LABELS.get(interval, {})
        config[role] = {
            "interval": interval,
            "period": yf_cfg["period"],
            "yf_interval": yf_cfg["interval"],
            "label": label_meta.get("label", interval),
            "weight": ROLE_WEIGHTS[role],
            "display": f"{role} ({interval})",
        }
    return config


def timeframe_config_summary(config: dict[str, dict[str, Any]] | None) -> str:
    cfg = config or build_timeframe_config()
    return " · ".join(f"{role} {cfg[role]['interval']}" for role in TF_ROLES if role in cfg)


def _ensure_utc_index(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index)
    if out.index.tz is None:
        out.index = out.index.tz_localize("UTC")
    return out


def get_ny_session_context(frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
    """
    Crypto session anchor: calendar day starts at 00:00 America/New_York.
    Session open = open of the first intraday bar on the latest NY date in data.
    """
    for role in ("ULTF", "LTF", "MTF", "HTF"):
        raw = frames.get(role)
        if raw is None or raw.empty:
            continue
        df = _ensure_utc_index(_normalize_columns(raw))
        df_ny = df.tz_convert(NY_TZ)
        if df_ny.empty:
            continue
        ny_days = df_ny.index.normalize().unique()
        if len(ny_days) == 0:
            continue
        day_start = ny_days[-1]
        day_bars = df_ny[df_ny.index.normalize() == day_start]
        if day_bars.empty:
            continue
        session_open = float(day_bars["open"].iloc[0])
        open_ts = day_bars.index[0]
        cur = float(df_ny["close"].iloc[-1])
        chg_pct = (cur - session_open) / session_open * 100 if session_open else 0.0
        return {
            "session_tz": CRYPTO_SESSION_TZ,
            "session_label": CRYPTO_SESSION_LABEL,
            "session_day_ny": day_start.strftime("%Y-%m-%d"),
            "session_open_time_ny": open_ts.strftime("%Y-%m-%d %H:%M %Z"),
            "session_open": session_open,
            "session_change_pct": round(chg_pct, 2),
            "source_role": role,
        }
    return {
        "session_tz": CRYPTO_SESSION_TZ,
        "session_label": CRYPTO_SESSION_LABEL,
        "session_open": None,
    }


def _crypto_close_bias_label(bias: str) -> str:
    if bias == "bullish":
        return "LIKELY TO CLOSE ABOVE NY SESSION OPEN"
    if bias == "bearish":
        return "LIKELY TO CLOSE BELOW NY SESSION OPEN"
    return "NEAR NY SESSION OPEN (INDECISIVE)"


def fetch_data(
    yf_symbol: str,
    timeframe_config: dict[str, dict[str, Any]] | None = None,
) -> dict[str, pd.DataFrame]:
    import yfinance as yf

    cfg = timeframe_config or build_timeframe_config()
    frames: dict[str, pd.DataFrame] = {}
    for role, meta in cfg.items():
        try:
            df = yf.download(
                yf_symbol,
                period=meta["period"],
                interval=meta["yf_interval"],
                progress=False,
                auto_adjust=True,
            )
            if df is None or df.empty or len(df) < 20:
                continue
            df = _normalize_columns(df)
            df = df.dropna(subset=["close"])
            if len(df) >= 20:
                frames[role] = df
        except Exception as exc:
            logger.debug("MTF bias fetch %s @ %s: %s", yf_symbol, role, exc)
    return frames


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = _normalize_columns(df)
    c = df["close"]

    df = add_ema(df, 9)
    df = add_ema(df, 21)
    df = add_ema(df, 50)
    df = add_ema(df, 200)
    df["ema9"] = df["ema_9"]
    df["ema21"] = df["ema_21"]
    df["ema50"] = df["ema_50"]
    df["ema200"] = df["ema_200"]

    df = add_macd(df, 12, 26, 9)
    df["macd"] = df["macd_12_26"]
    df["macd_s"] = df["macd_signal_12_26_9"]
    df["macd_h"] = df["macd_hist_12_26_9"]

    df = add_adx(df, 14)
    df["adx"] = df["adx_14"]
    df["dmp"] = df["plus_di_14"]
    df["dmn"] = df["minus_di_14"]

    df = add_rsi(df, 14)
    df["rsi"] = df["rsi_14"]

    df = add_stochastic(df, 14, 3)
    df["stoch_k"] = df["stoch_k_14"]
    df["stoch_d"] = df["stoch_d_14_3"]

    df = add_cci(df, 20)
    df["cci"] = df["cci_20"]

    df = add_williams_r(df, 14)
    df["williams_r"] = df["williams_r_14"]

    df = add_roc(df, 10)
    df["roc"] = df["roc_10"]

    df = add_bollinger_bands(df, 20, 2.0)
    df["bb_upper"] = df["bb_upper_20_2.0"]
    df["bb_lower"] = df["bb_lower_20_2.0"]
    df["bb_mid"] = df["bb_middle_20_2.0"]
    bw = (df["bb_upper"] - df["bb_lower"]).replace(0, np.nan)
    df["bb_pct"] = (c - df["bb_lower"]) / bw

    if "volume" in df.columns:
        df = add_obv(df)
        df = add_vwap(df)
        df = add_vol_sma(df, 20)
        df["vol_ma20"] = df["vol_sma_20"]
        df["vol_ratio"] = df["vol_ratio_20"]
    else:
        df["obv"] = 0.0
        df["vwap"] = c
        df["vol_ma20"] = 1.0
        df["vol_ratio"] = 1.0

    df["body"] = c - df["open"]
    df["body_pct"] = df["body"] / df["open"].replace(0, np.nan) * 100
    df["upper_wick"] = df["high"] - df[["close", "open"]].max(axis=1)
    df["lower_wick"] = df[["close", "open"]].min(axis=1) - df["low"]
    df["range"] = df["high"] - df["low"]

    return df.dropna(subset=["rsi", "macd", "ema9"])


def get_support_resistance(df: pd.DataFrame, current_price: float) -> tuple[list[float], list[float]]:
    hi = df["high"].values
    lo = df["low"].values

    ph = argrelextrema(hi, np.greater, order=5)[0]
    pl = argrelextrema(lo, np.less, order=5)[0]

    resistances = sorted(set(hi[ph]), reverse=True)
    supports = sorted(set(lo[pl]), reverse=False)

    res_above = [r for r in resistances if r > current_price * 1.001][:2]
    sup_below = [s for s in supports if s < current_price * 0.999][::-1][:2]

    if len(df) >= 30:
        swing_high = float(df["high"].tail(30).max())
        swing_low = float(df["low"].tail(30).min())
        diff = swing_high - swing_low
        fib_levels = [swing_low + diff * r for r in [0.236, 0.382, 0.5, 0.618, 0.786]]
        if len(res_above) < 2:
            extra = [f for f in fib_levels if f > current_price and f not in res_above]
            res_above = (res_above + extra)[:2]
        if len(sup_below) < 2:
            extra = [f for f in fib_levels if f < current_price and f not in sup_below]
            sup_below = (sup_below + extra[::-1])[:2]

    return sup_below[::-1][:2], res_above[:2]


def detect_candle_patterns(df: pd.DataFrame) -> list[tuple[str, int]]:
    patterns: list[tuple[str, int]] = []
    if len(df) < 3:
        return patterns

    o = df["open"].values
    h = df["high"].values
    lo = df["low"].values
    c = df["close"].values

    def body(i: int) -> float:
        return abs(c[i] - o[i])

    def range_(i: int) -> float:
        return h[i] - lo[i]

    i, p = -1, -2

    if body(i) / (range_(i) + 1e-9) < 0.1:
        patterns.append(("Doji (indecision)", 0))

    if df["lower_wick"].iloc[i] > 2 * body(i) and df["upper_wick"].iloc[i] < body(i):
        patterns.append(("Hammer", +1))
    if df["upper_wick"].iloc[i] > 2 * body(i) and df["lower_wick"].iloc[i] < body(i):
        patterns.append(("Shooting Star", -1) if c[i] < o[i] else ("Inverted Hammer", +1))

    if c[p] < o[p] and c[i] > o[i] and c[i] > o[p] and o[i] < c[p]:
        patterns.append(("Bullish Engulfing", +1))
    if c[p] > o[p] and c[i] < o[i] and c[i] < o[p] and o[i] > c[p]:
        patterns.append(("Bearish Engulfing", -1))

    if body(i) / (range_(i) + 1e-9) > 0.9:
        patterns.append(("Bullish Marubozu", +2) if c[i] > o[i] else ("Bearish Marubozu", -2))

    if len(df) >= 3:
        pp = -3
        if c[pp] < o[pp] and body(-2) < 0.3 * body(pp) and c[i] > o[i] and c[i] > (o[pp] + c[pp]) / 2:
            patterns.append(("Morning Star", +2))
        if c[pp] > o[pp] and body(-2) < 0.3 * body(pp) and c[i] < o[i] and c[i] < (o[pp] + c[pp]) / 2:
            patterns.append(("Evening Star", -2))

    return patterns


def elliott_wave_bias(df: pd.DataFrame) -> tuple[str, int]:
    if len(df) < 50:
        return ("Insufficient data", 0)

    closes = df["close"].tail(50).values
    highs = argrelextrema(closes, np.greater, order=3)[0]
    lows_ = argrelextrema(closes, np.less, order=3)[0]

    if len(highs) >= 3 and len(lows_) >= 2:
        if closes[highs[-3]] < closes[highs[-2]] < closes[highs[-1]] and closes[lows_[-2]] < closes[lows_[-1]]:
            return ("Likely Wave 3/5 UP (Impulse)", +2)
        if closes[highs[-3]] > closes[highs[-2]] > closes[highs[-1]] and closes[lows_[-2]] > closes[lows_[-1]]:
            return ("Likely Wave 3/5 DOWN (Impulse)", -2)

    if closes[-1] > closes[-25] > closes[-50]:
        return ("Corrective / Sideways in Uptrend", +1)
    return ("Corrective / Sideways in Downtrend", -1)


def score_timeframe(
    df: pd.DataFrame,
    *,
    session_open: float | None = None,
) -> dict[str, Any]:
    signals: dict[str, tuple[str, int]] = {}
    last = df.iloc[-1]
    prev = df.iloc[-2]
    c = float(last["close"])

    rsi = float(last["rsi"])
    if rsi < 30:
        signals["RSI"] = ("Oversold ↑", +2)
    elif rsi > 70:
        signals["RSI"] = ("Overbought ↓", -2)
    elif 40 < rsi < 60:
        signals["RSI"] = ("Neutral", 0)
    elif rsi >= 60:
        signals["RSI"] = ("Bullish momentum", +1)
    else:
        signals["RSI"] = ("Bearish momentum", -1)

    k, d = float(last["stoch_k"]), float(last["stoch_d"])
    if k < 20 and k > d:
        signals["Stochastic"] = ("Bullish crossover in oversold", +2)
    elif k > 80 and k < d:
        signals["Stochastic"] = ("Bearish crossover in overbought", -2)
    elif k > d:
        signals["Stochastic"] = ("K > D (Bullish)", +1)
    else:
        signals["Stochastic"] = ("K < D (Bearish)", -1)

    if last["macd"] > last["macd_s"] and prev["macd"] <= prev["macd_s"]:
        signals["MACD"] = ("Fresh bullish crossover", +2)
    elif last["macd"] < last["macd_s"] and prev["macd"] >= prev["macd_s"]:
        signals["MACD"] = ("Fresh bearish crossover", -2)
    elif last["macd"] > last["macd_s"]:
        signals["MACD"] = ("Above signal (Bullish)", +1)
    else:
        signals["MACD"] = ("Below signal (Bearish)", -1)

    if last["macd_h"] > 0 and last["macd_h"] > prev["macd_h"]:
        signals["MACD Hist"] = ("Expanding bullish", +1)
    elif last["macd_h"] < 0 and last["macd_h"] < prev["macd_h"]:
        signals["MACD Hist"] = ("Expanding bearish", -1)
    else:
        signals["MACD Hist"] = ("Contracting", 0)

    e9, e21, e50 = last["ema9"], last["ema21"], last["ema50"]
    if c > e9 > e21 > e50:
        signals["EMA Stack"] = ("Fully bullish (9>21>50)", +2)
    elif c < e9 < e21 < e50:
        signals["EMA Stack"] = ("Fully bearish (9<21<50)", -2)
    elif c > e21:
        signals["EMA Stack"] = ("Above EMA21 (Bullish)", +1)
    else:
        signals["EMA Stack"] = ("Below EMA21 (Bearish)", -1)

    if c > last["vwap"]:
        signals["VWAP"] = ("Price above VWAP ↑", +1)
    else:
        signals["VWAP"] = ("Price below VWAP ↓", -1)

    bp = float(last["bb_pct"])
    if bp < 0.2:
        signals["Bollinger"] = ("Near lower band (oversold)", +1)
    elif bp > 0.8:
        signals["Bollinger"] = ("Near upper band (overbought)", -1)
    else:
        signals["Bollinger"] = ("Mid-band (neutral)", 0)

    adx = float(last["adx"])
    if adx > 25:
        if last["dmp"] > last["dmn"]:
            signals["ADX/DI"] = (f"Strong trend UP (ADX={adx:.1f})", +2)
        else:
            signals["ADX/DI"] = (f"Strong trend DOWN (ADX={adx:.1f})", -2)
    else:
        signals["ADX/DI"] = (f"Weak/no trend (ADX={adx:.1f})", 0)

    cci = float(last["cci"])
    if cci > 100:
        signals["CCI"] = ("Overbought territory", -1)
    elif cci < -100:
        signals["CCI"] = ("Oversold territory", +1)
    elif cci > 0:
        signals["CCI"] = ("Positive (Bullish)", +1)
    else:
        signals["CCI"] = ("Negative (Bearish)", -1)

    wr = float(last["williams_r"])
    if wr < -80:
        signals["Williams %R"] = ("Oversold ↑", +1)
    elif wr > -20:
        signals["Williams %R"] = ("Overbought ↓", -1)
    else:
        signals["Williams %R"] = ("Neutral", 0)

    obv_slope = df["obv"].tail(5).diff().mean()
    if obv_slope > 0:
        signals["OBV"] = ("Rising (accumulation)", +1)
    else:
        signals["OBV"] = ("Falling (distribution)", -1)

    vr = float(last["vol_ratio"])
    if vr > 1.5 and last["body_pct"] > 0:
        signals["Volume"] = (f"High vol bullish bar ({vr:.1f}x avg)", +2)
    elif vr > 1.5 and last["body_pct"] < 0:
        signals["Volume"] = (f"High vol bearish bar ({vr:.1f}x avg)", -2)
    else:
        signals["Volume"] = (f"Normal volume ({vr:.1f}x avg)", 0)

    roc = float(last["roc"])
    signals["ROC"] = ("Positive momentum", +1) if roc > 0 else ("Negative momentum", -1)

    for name, val in detect_candle_patterns(df):
        signals[f"Pattern:{name}"] = (name, val)

    ew_desc, ew_val = elliott_wave_bias(df)
    signals["Elliott Wave"] = (ew_desc, ew_val)

    if session_open is not None:
        if c > session_open:
            signals["Price vs Open"] = (
                f"Above NY session open ({c:.4f} > {session_open:.4f})",
                +1,
            )
        else:
            signals["Price vs Open"] = (
                f"Below NY session open ({c:.4f} < {session_open:.4f})",
                -1,
            )
    else:
        open_price = float(last["open"])
        if c > open_price:
            signals["Price vs Open"] = (f"Above open ({c:.2f} > {open_price:.2f})", +1)
        else:
            signals["Price vs Open"] = (f"Below open ({c:.2f} < {open_price:.2f})", -1)

    total = sum(v for _, v in signals.values())
    return {"signals": signals, "raw_score": total, "last": last}


def _hold_duration_for_interval(interval: str) -> str:
    return MTF_TF_LABELS.get(interval, {}).get("hold", "—")


def _style_for_interval(interval: str) -> str:
    return MTF_TF_LABELS.get(interval, {}).get("style", "Intraday")


def _pick_entry_timeframe(
    results: dict[str, dict],
    tf_cfg: dict[str, dict[str, Any]],
    bias: str,
) -> tuple[str | None, str | None]:
    """Choose execution TF role aligned with session bias (prefer LTF → ULTF)."""
    if bias == "neutral" or not results:
        return None, None

    sign = 1 if bias == "bullish" else -1
    best_role: str | None = None
    best_aligned = -1.0

    for role in ENTRY_ROLE_PREFERENCE:
        res = results.get(role)
        if not res:
            continue
        raw = float(res.get("raw_score", 0))
        if raw * sign > 0 and abs(raw) >= best_aligned:
            best_aligned = abs(raw)
            best_role = role

    if best_role is None:
        for role in ENTRY_ROLE_PREFERENCE:
            if role in results:
                best_role = role
                break

    if not best_role:
        return None, None

    interval = tf_cfg.get(best_role, {}).get("interval", best_role)
    return best_role, interval


def _swing_stop(df: pd.DataFrame, side: str, lookback: int = 6) -> float:
    tail = df.tail(lookback)
    if side == "LONG":
        return float(tail["low"].min())
    return float(tail["high"].max())


def build_trade_setup(
    *,
    bias: str,
    cur_price: float,
    supports: list[float],
    resistances: list[float],
    entry_df: pd.DataFrame,
    entry_role: str,
    entry_interval: str,
    confidence: float,
    is_crypto: bool = False,
) -> dict[str, Any]:
    """Intraday trade plan: entry TF, SL/TP prices & %, hold duration."""
    decimals = 4 if is_crypto else 2
    base = {
        "actionable": False,
        "status": "NO SETUP",
        "direction": "—",
        "entry_timeframe_role": entry_role,
        "entry_timeframe": entry_interval,
        "entry_timeframe_label": MTF_TF_LABELS.get(entry_interval, {}).get("label", entry_interval),
        "style": _style_for_interval(entry_interval),
        "hold_duration": _hold_duration_for_interval(entry_interval),
        "entry": round(cur_price, decimals),
        "stop_loss": None,
        "take_profit": None,
        "sl_pct": None,
        "tp_pct": None,
        "rr_ratio": None,
        "note": "",
    }

    if bias == "neutral":
        base["note"] = "Neutral session bias — wait for directional alignment"
        return base

    if confidence < 52:
        base["status"] = "LOW CONFIDENCE"
        base["note"] = f"Confidence {confidence:.0f}% — reduce size or wait"
        return base

    side = "LONG" if bias == "bullish" else "SHORT"
    swing_sl = _swing_stop(entry_df, side)

    if side == "LONG":
        sr_sl = supports[0] if supports else swing_sl
        sl = min(swing_sl, sr_sl, cur_price * 0.997)
        sl = min(sl, cur_price - cur_price * 0.002)
        risk = cur_price - sl
        if risk <= 0:
            sl = cur_price * 0.985
            risk = cur_price - sl
        tp_rr = cur_price + risk * DEFAULT_RR_RATIO
        tp_sr = resistances[0] if resistances and resistances[0] > cur_price else tp_rr
        tp = min(tp_sr, tp_rr) if tp_sr > cur_price else tp_rr
        if tp <= cur_price:
            tp = tp_rr
    else:
        sr_sl = resistances[0] if resistances else swing_sl
        sl = max(swing_sl, sr_sl, cur_price * 1.003)
        sl = max(sl, cur_price + cur_price * 0.002)
        risk = sl - cur_price
        if risk <= 0:
            sl = cur_price * 1.015
            risk = sl - cur_price
        tp_rr = cur_price - risk * DEFAULT_RR_RATIO
        tp_sr = supports[0] if supports and supports[0] < cur_price else tp_rr
        tp = max(tp_sr, tp_rr) if tp_sr < cur_price else tp_rr
        if tp >= cur_price:
            tp = tp_rr

    sl_pct = abs(cur_price - sl) / cur_price * 100
    tp_pct = abs(tp - cur_price) / cur_price * 100
    rr = tp_pct / sl_pct if sl_pct > 0 else 0.0

    status = "READY" if confidence >= 62 and sl_pct > 0 and tp_pct > 0 else "WATCH"
    note = (
        f"Execute on **{entry_role} ({entry_interval})** — "
        f"{side} with SL at swing/S-R, TP at {'R1' if side == 'LONG' else 'S1'} or 1:{DEFAULT_RR_RATIO:.0f} R:R"
    )

    return {
        "actionable": status in ("READY", "WATCH") and sl_pct > 0 and tp_pct > 0,
        "status": status,
        "direction": side,
        "entry_timeframe_role": entry_role,
        "entry_timeframe": entry_interval,
        "entry_timeframe_label": MTF_TF_LABELS.get(entry_interval, {}).get("label", entry_interval),
        "style": _style_for_interval(entry_interval),
        "hold_duration": _hold_duration_for_interval(entry_interval),
        "entry": round(cur_price, decimals),
        "stop_loss": round(sl, decimals),
        "take_profit": round(tp, decimals),
        "sl_pct": round(sl_pct, 2),
        "tp_pct": round(tp_pct, 2),
        "rr_ratio": round(rr, 2),
        "note": note,
    }


def get_pcr_proxy(yf_symbol: str) -> tuple[str, int, str]:
    try:
        import yfinance as yf

        t = yf.Ticker(yf_symbol)
        exp_dates = t.options
        if not exp_dates:
            return ("N/A", 0, "No options data")
        opt = t.option_chain(exp_dates[0])
        put_vol = float(opt.puts["volume"].sum())
        call_vol = float(opt.calls["volume"].sum())
        if call_vol == 0:
            return ("N/A", 0, "Zero call volume")
        pcr = put_vol / call_vol
        if pcr > 1.2:
            return (
                f"PCR={pcr:.2f} (High — contrarian BULLISH)",
                +1,
                "Extreme put buying often marks bottoms",
            )
        if pcr < 0.7:
            return (
                f"PCR={pcr:.2f} (Low — contrarian BEARISH)",
                -1,
                "Low PCR = complacency, possible top",
            )
        return (f"PCR={pcr:.2f} (Neutral)", 0, "No strong signal")
    except Exception as exc:
        return ("PCR unavailable", 0, str(exc)[:80])


def analyze_ticker(
    ticker: str,
    timeframe_config: dict[str, dict[str, Any]] | None = None,
    *,
    is_crypto: bool = False,
) -> dict[str, Any]:
    tf_cfg = timeframe_config or build_timeframe_config()
    yf_sym = resolve_yf_symbol(ticker, is_crypto=is_crypto)
    frames = fetch_data(yf_sym, tf_cfg)
    if not frames:
        return {"error": f"No data for {ticker}", "ticker": ticker, "yf_symbol": yf_sym}

    session_ctx: dict[str, Any] = get_ny_session_context(frames) if is_crypto else {}
    session_open = session_ctx.get("session_open")

    results: dict[str, Any] = {}
    weighted_score = 0.0
    max_possible = 0.0

    for role, raw_df in frames.items():
        df = add_indicators(raw_df)
        if len(df) < 5:
            continue
        res = score_timeframe(df, session_open=session_open if is_crypto else None)
        meta = tf_cfg.get(role, {})
        res["interval"] = meta.get("interval", role)
        res["display"] = meta.get("display", role)
        results[role] = res
        w = float(meta.get("weight", ROLE_WEIGHTS.get(role, 0.25)))
        weighted_score += res["raw_score"] * w
        max_possible += len(res["signals"]) * 2 * w

    if not results:
        return {"error": f"Insufficient indicator data for {ticker}", "ticker": ticker, "yf_symbol": yf_sym}

    base_role = "HTF" if "HTF" in frames else list(frames.keys())[-1]
    base_df = add_indicators(frames[base_role])
    cur_price = float(base_df["close"].iloc[-1])
    supports, resistances = get_support_resistance(base_df, cur_price)

    if is_crypto:
        pcr_str, pcr_score, pcr_note = ("N/A (crypto)", 0, "Options PCR not used for crypto pairs")
    else:
        pcr_str, pcr_score, pcr_note = get_pcr_proxy(yf_sym)
    weighted_score += pcr_score * 0.05

    raw_pct = (weighted_score / (max_possible + 1e-9)) * 100
    confidence = max(0, min(100, 50 + raw_pct))

    if weighted_score > BULLISH_THRESHOLD:
        direction = "BULLISH"
        close_bias = _crypto_close_bias_label("bullish") if is_crypto else "LIKELY TO CLOSE ABOVE OPEN"
        bias = "bullish"
    elif weighted_score < BEARISH_THRESHOLD:
        direction = "BEARISH"
        close_bias = _crypto_close_bias_label("bearish") if is_crypto else "LIKELY TO CLOSE BELOW OPEN"
        bias = "bearish"
    else:
        direction = "NEUTRAL"
        close_bias = _crypto_close_bias_label("neutral") if is_crypto else "CLOSE NEAR OPEN (INDECISIVE)"
        bias = "neutral"

    entry_role, entry_interval = _pick_entry_timeframe(results, tf_cfg, bias)
    trade_setup: dict[str, Any] = {"actionable": False, "status": "NO SETUP", "direction": "—"}
    if entry_role and entry_role in frames:
        entry_df = add_indicators(frames[entry_role])
        trade_setup = build_trade_setup(
            bias=bias,
            cur_price=cur_price,
            supports=supports,
            resistances=resistances,
            entry_df=entry_df,
            entry_role=entry_role,
            entry_interval=entry_interval or entry_role,
            confidence=confidence,
            is_crypto=is_crypto,
        )

    return {
        "ticker": ticker,
        "yf_symbol": yf_sym,
        "current_price": cur_price,
        "direction": direction,
        "close_bias": close_bias,
        "bias": bias,
        "weighted_score": round(weighted_score, 3),
        "confidence": round(confidence, 1),
        "supports": supports,
        "resistances": resistances,
        "pcr": pcr_str,
        "pcr_note": pcr_note,
        "timeframes": results,
        "timeframe_config": tf_cfg,
        "is_crypto": is_crypto,
        "trade_setup": trade_setup,
        "trade_plan": trade_setup,
        "session": session_ctx if is_crypto else {},
    }


def analyze_universe(
    tickers: list[str],
    timeframe_config: dict[str, dict[str, Any]] | None = None,
    *,
    is_crypto: bool = False,
) -> dict[str, Any]:
    """Run analyzer on multiple tickers; split into bullish / bearish / neutral."""
    tf_cfg = timeframe_config or build_timeframe_config()
    rows: list[dict] = []
    errors: list[dict] = []
    details: dict[str, dict] = {}

    for ticker in tickers:
        t = ticker.strip().upper()
        if not t:
            continue
        res = analyze_ticker(t, tf_cfg, is_crypto=is_crypto)
        if res.get("error"):
            errors.append({"ticker": t, "error": res["error"]})
            continue
        details[t] = res
        rows.append(_row_from_result(res))

    bullish = sorted(
        [r for r in rows if r["bias"] == "bullish"],
        key=lambda x: (x["confidence"], x["weighted_score"]),
        reverse=True,
    )
    bearish = sorted(
        [r for r in rows if r["bias"] == "bearish"],
        key=lambda x: (x["confidence"], -x["weighted_score"]),
        reverse=True,
    )
    neutral = sorted(
        [r for r in rows if r["bias"] == "neutral"],
        key=lambda x: abs(x["weighted_score"]),
    )

    return {
        "bullish": bullish,
        "bearish": bearish,
        "neutral": neutral,
        "errors": errors,
        "details": details,
        "ticker_count": len(tickers),
        "analyzed_count": len(rows),
        "timeframe_config": tf_cfg,
        "timeframe_summary": timeframe_config_summary(tf_cfg),
        "is_crypto": is_crypto,
        "market": "crypto" if is_crypto else "equity",
        "session_tz": CRYPTO_SESSION_TZ if is_crypto else "Asia/Kolkata",
        "session_label": CRYPTO_SESSION_LABEL if is_crypto else "India cash session (09:15 IST)",
    }


def _row_from_result(res: dict) -> dict:
    p = res["current_price"]
    sups = res.get("supports") or []
    ress = res.get("resistances") or []
    setup = res.get("trade_setup") or {}

    def _dist(level: float | None) -> str:
        if level is None or not p:
            return "—"
        return f"{((level - p) / p) * 100:+.2f}%"

    return {
        "ticker": res["ticker"],
        "price": round(p, 2),
        "direction": res["direction"],
        "confidence": res["confidence"],
        "confidence_pct": f"{res['confidence']:.1f}%",
        "close_bias": res["close_bias"],
        "weighted_score": res["weighted_score"],
        "bias": res["bias"],
        "pcr": res.get("pcr", "—"),
        "S1": round(sups[0], 2) if len(sups) > 0 else None,
        "S2": round(sups[1], 2) if len(sups) > 1 else None,
        "R1": round(ress[0], 2) if len(ress) > 0 else None,
        "R2": round(ress[1], 2) if len(ress) > 1 else None,
        "S1_dist": _dist(sups[0] if sups else None),
        "R1_dist": _dist(ress[0] if ress else None),
        "trade_tf": setup.get("entry_timeframe") or "—",
        "trade_tf_role": setup.get("entry_timeframe_role") or "—",
        "trade_direction": setup.get("direction", "—"),
        "sl_pct": setup.get("sl_pct"),
        "tp_pct": setup.get("tp_pct"),
        "hold_duration": setup.get("hold_duration", "—"),
        "setup_status": setup.get("status", "—"),
        "trade_actionable": setup.get("actionable", False),
    }
