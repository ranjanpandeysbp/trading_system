"""
scalp_multi_indicator_engine.py
--------------------------------
Multi-indicator scalp — UT Bot · QQE · Vaddah Attar · EMA pullback · volume delta.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.trading_hubs.intraday_shared import enrich_intra_live
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.scalp_sr_mss_engine import (
    SESSION_CLOSE_BY_MODE,
    SESSION_OPEN_BY_MODE,
    _ensure_market_tz,
    _session_tz,
)
from app.market_pulse.fakeout_4h_engine import session_mode_for_market

logger = logging.getLogger(__name__)

YOUTUBE_SCALP_MULTI_INDICATOR_URL = "https://www.youtube.com/watch?v=L3Zn_3ONytI&t=7s"

EXEC_TF = "1m"

PHASE_NONE = "NO_SETUP"
PHASE_PRE_SESSION = "PRE_SESSION"
PHASE_FILTER = "INDICATOR_FILTER"
PHASE_PULLBACK = "EMA_PULLBACK"
PHASE_MOMENTUM = "VAE_MOMENTUM"
PHASE_ENTRY = "MULTI_ENTRY"

SIGNAL_BUY = 1
SIGNAL_SELL = -1

HOLD_MULTI_INDICATOR = "Multi-indicator scalp · UT Bot + QQE · session exit"


@dataclass
class MultiIndicatorConfig:
    execution_tf: str = EXEC_TF
    ut_sensitivity: float = 3.0
    ut_atr_period: int = 4
    qqe_rsi_length: int = 55
    qqe_factor: float = 8.0
    ema_band_period: int = 34
    ema_fast: int = 89
    ema_medium: int = 200
    vae_lookback: int = 50
    rr_ratio: float = 2.0
    take_confidence_threshold: float = 58.0
    lookback_bars: int = 800
    min_bars: int = 220
    require_volume_delta: bool = True
    require_vae_explosion: bool = False


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _atr(df: pd.DataFrame, period: int) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


def _ut_bot_signals(close: pd.Series, atr: pd.Series, sensitivity: float) -> tuple[pd.Series, pd.Series]:
    """ATR trailing-stop UT Bot approximation (sensitivity × ATR)."""
    n = len(close)
    trail = np.full(n, np.nan)
    signal = np.zeros(n, dtype=int)
    n_loss = sensitivity * atr.values
    c = close.values

    for i in range(1, n):
        if np.isnan(n_loss[i]) or np.isnan(c[i]):
            continue
        prev_trail = trail[i - 1] if not np.isnan(trail[i - 1]) else c[i] - n_loss[i]
        if c[i] > prev_trail and c[i - 1] > prev_trail:
            trail[i] = max(prev_trail, c[i] - n_loss[i])
        elif c[i] < prev_trail and c[i - 1] < prev_trail:
            trail[i] = min(prev_trail, c[i] + n_loss[i])
        elif c[i] > prev_trail:
            trail[i] = c[i] - n_loss[i]
        else:
            trail[i] = c[i] + n_loss[i]

        if c[i] > trail[i]:
            signal[i] = 1
        elif c[i] < trail[i]:
            signal[i] = -1
        else:
            signal[i] = signal[i - 1]

    return pd.Series(trail, index=close.index), pd.Series(signal, index=close.index)


def _rsi(series: pd.Series, length: int) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0).rolling(length, min_periods=length).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(length, min_periods=length).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _qqe_signals(close: pd.Series, rsi_length: int, qqe_factor: float) -> tuple[pd.Series, pd.Series]:
    """QQE MOD — smoothed RSI with dynamic bands; returns (qqe_trend, qqe_signal)."""
    rsi = _rsi(close, rsi_length)
    wilders = rsi_length * 2 - 1
    rsi_ma = _ema(rsi, wilders)
    dar = _ema((rsi_ma - rsi_ma.shift(1)).abs(), wilders) * qqe_factor

    long_band = pd.Series(np.nan, index=close.index)
    short_band = pd.Series(np.nan, index=close.index)
    trend = pd.Series(0, index=close.index)

    for i in range(1, len(close)):
        if pd.isna(rsi_ma.iloc[i]) or pd.isna(dar.iloc[i]):
            continue
        new_short = rsi_ma.iloc[i] + dar.iloc[i]
        new_long = rsi_ma.iloc[i] - dar.iloc[i]
        if rsi_ma.iloc[i - 1] > long_band.iloc[i - 1] and rsi_ma.iloc[i] > long_band.iloc[i - 1]:
            long_band.iloc[i] = max(long_band.iloc[i - 1], new_long)
        else:
            long_band.iloc[i] = new_long
        if rsi_ma.iloc[i - 1] < short_band.iloc[i - 1] and rsi_ma.iloc[i] < short_band.iloc[i - 1]:
            short_band.iloc[i] = min(short_band.iloc[i - 1], new_short)
        else:
            short_band.iloc[i] = new_short
        if rsi_ma.iloc[i] > short_band.iloc[i - 1]:
            trend.iloc[i] = 1
        elif rsi_ma.iloc[i] < long_band.iloc[i - 1]:
            trend.iloc[i] = -1
        else:
            trend.iloc[i] = trend.iloc[i - 1]

    qqe_signal = trend.copy()
    return trend, qqe_signal


def _volume_delta(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Approximate buy/sell volume split from OHLCV candle geometry."""
    hl = (df["high"] - df["low"]).replace(0, np.nan)
    vol = df["volume"].replace(0, np.nan).fillna(1.0)
    buy = vol * (df["close"] - df["low"]) / hl
    sell = vol * (df["high"] - df["close"]) / hl
    buy = buy.fillna(vol * 0.5)
    sell = sell.fillna(vol * 0.5)
    return buy, sell, buy - sell


def _vaddah_attar(df: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """Momentum histogram with dead-zone and explosion thresholds."""
    out = df.copy()
    mom_base = _ema(out["close"], 13)
    out["vae_hist"] = out["close"] - mom_base
    abs_hist = out["vae_hist"].abs()
    out["vae_dead_zone"] = abs_hist.rolling(lookback, min_periods=20).quantile(0.30)
    out["vae_explosion"] = abs_hist.rolling(lookback, min_periods=20).quantile(0.70)
    out["vae_green"] = (out["vae_hist"] > 0) & (out["vae_hist"] > out["vae_hist"].shift(1))
    out["vae_red"] = (out["vae_hist"] < 0) & (out["vae_hist"] < out["vae_hist"].shift(1))
    out["vae_above_dead"] = abs_hist > out["vae_dead_zone"]
    out["vae_above_explosion"] = abs_hist > out["vae_explosion"]
    return out


def apply_scalping_multi_indicator(df: pd.DataFrame, cfg: MultiIndicatorConfig) -> pd.DataFrame:
    work = normalize_ohlcv(df).copy()
    if work.empty:
        return work

    work["atr"] = _atr(work, cfg.ut_atr_period)
    work["ut_trail"], work["ut_signal"] = _ut_bot_signals(
        work["close"], work["atr"], cfg.ut_sensitivity,
    )
    work["rsi_55"] = _rsi(work["close"], cfg.qqe_rsi_length)
    work["qqe_trend"], work["qqe_signal"] = _qqe_signals(
        work["close"], cfg.qqe_rsi_length, cfg.qqe_factor,
    )

    work["ema_34_close"] = _ema(work["close"], cfg.ema_band_period)
    work["ema_34_high"] = _ema(work["high"], cfg.ema_band_period)
    work["ema_34_low"] = _ema(work["low"], cfg.ema_band_period)
    work["ema_89"] = _ema(work["close"], cfg.ema_fast)
    work["ema_200"] = _ema(work["close"], cfg.ema_medium)

    buy_v, sell_v, vol_delta = _volume_delta(work)
    work["buy_volume"] = buy_v
    work["sell_volume"] = sell_v
    work["volume_delta"] = vol_delta

    work = _vaddah_attar(work, cfg.vae_lookback)
    work["signal"] = 0
    work["stop_loss"] = np.nan
    work["take_profit"] = np.nan
    work["setup_phase"] = PHASE_NONE

    n = len(work)
    for i in range(cfg.min_bars, n):
        row = work.iloc[i]
        ut = int(row["ut_signal"]) if not pd.isna(row["ut_signal"]) else 0
        qqe = int(row["qqe_signal"]) if not pd.isna(row["qqe_signal"]) else 0
        c, lo, hi = float(row["close"]), float(row["low"]), float(row["high"])
        ema200 = float(row["ema_200"]) if pd.notna(row["ema_200"]) else c
        ema34_hi = float(row["ema_34_high"]) if pd.notna(row["ema_34_high"]) else c
        ema34_lo = float(row["ema_34_low"]) if pd.notna(row["ema_34_low"]) else c
        vdelta = float(row["volume_delta"]) if pd.notna(row["volume_delta"]) else 0
        vae_ok_long = bool(row["vae_green"]) and bool(row["vae_above_dead"])
        vae_ok_short = bool(row["vae_red"]) and bool(row["vae_above_dead"])
        if cfg.require_vae_explosion:
            vae_ok_long = vae_ok_long and bool(row["vae_above_explosion"])
            vae_ok_short = vae_ok_short and bool(row["vae_above_explosion"])

        vol_ok_long = vdelta > 0 if cfg.require_volume_delta else True
        vol_ok_short = vdelta < 0 if cfg.require_volume_delta else True

        long_cond = (
            ut == 1 and qqe == 1 and c > ema200
            and lo <= ema34_hi and c >= ema34_lo
            and vae_ok_long and vol_ok_long
        )
        short_cond = (
            ut == -1 and qqe == -1 and c < ema200
            and hi >= ema34_lo and c <= ema34_hi
            and vae_ok_short and vol_ok_short
        )

        ts = work.index[i]
        if long_cond:
            sl = min(lo, ema34_lo) - c * 0.0005
            risk = c - sl
            if risk > 0:
                work.at[ts, "signal"] = SIGNAL_BUY
                work.at[ts, "stop_loss"] = sl
                work.at[ts, "take_profit"] = c + risk * cfg.rr_ratio
                work.at[ts, "setup_phase"] = PHASE_ENTRY
        elif short_cond:
            sl = max(hi, ema34_hi) + c * 0.0005
            risk = sl - c
            if risk > 0:
                work.at[ts, "signal"] = SIGNAL_SELL
                work.at[ts, "stop_loss"] = sl
                work.at[ts, "take_profit"] = c - risk * cfg.rr_ratio
                work.at[ts, "setup_phase"] = PHASE_ENTRY
        elif ut == 1 and qqe == 1 and c > ema200:
            work.at[ts, "setup_phase"] = PHASE_PULLBACK
        elif ut == -1 and qqe == -1 and c < ema200:
            work.at[ts, "setup_phase"] = PHASE_PULLBACK
        elif ut != 0 and qqe == ut:
            work.at[ts, "setup_phase"] = PHASE_FILTER
        elif vae_ok_long or vae_ok_short:
            work.at[ts, "setup_phase"] = PHASE_MOMENTUM

    return work


def _in_session(ts: pd.Timestamp, market: str) -> bool:
    mode = session_mode_for_market(market)
    tz = _session_tz(mode)
    ts = ts.tz_convert(tz) if ts.tz else ts.tz_localize(tz)
    open_t = SESSION_OPEN_BY_MODE.get(mode, SESSION_OPEN_BY_MODE["ny"])
    close_t = SESSION_CLOSE_BY_MODE.get(mode, SESSION_CLOSE_BY_MODE["ny"])
    return open_t <= ts.time() <= close_t


def evaluate_live_signal(work: pd.DataFrame, cfg: MultiIndicatorConfig, *, market: str) -> dict[str, Any]:
    if work.empty or len(work) < cfg.min_bars:
        return {"signal": "NO_DATA"}

    i = len(work) - 1
    row = work.iloc[i]
    ts = work.index[i]
    price = float(row["close"])
    ema34_hi = float(row["ema_34_high"]) if pd.notna(row["ema_34_high"]) else price
    ema34_lo = float(row["ema_34_low"]) if pd.notna(row["ema_34_low"]) else price
    latest_sig = int(row["signal"]) if not pd.isna(row["signal"]) else 0
    phase = str(row.get("setup_phase", PHASE_NONE))
    ut = int(row["ut_signal"]) if not pd.isna(row["ut_signal"]) else 0
    qqe = int(row["qqe_signal"]) if not pd.isna(row["qqe_signal"]) else 0

    reasons: list[str] = []
    conf = 18.0
    direction = "WAIT"
    verdict = "WAIT"
    take = False
    stop = price
    target = price

    reasons.append(
        f"UT Bot (ATR {cfg.ut_atr_period} × sens {cfg.ut_sensitivity}) · "
        f"QQE RSI {cfg.qqe_rsi_length} factor {cfg.qqe_factor}"
    )

    if not _in_session(ts, market):
        phase = PHASE_PRE_SESSION
        verdict = "PRE-SESSION"
        conf = 12.0
        reasons.append("Wait for regular session window")
    else:
        ema200 = float(row["ema_200"]) if pd.notna(row["ema_200"]) else price
        vdelta = float(row["volume_delta"]) if pd.notna(row["volume_delta"]) else 0

        reasons.append(
            f"EMA band {ema34_lo:,.4g}–{ema34_hi:,.4g} · EMA{cfg.ema_fast} "
            f"{float(row['ema_89']):,.4g} · EMA{cfg.ema_medium} {ema200:,.4g}"
        )
        reasons.append(
            f"VAE hist {float(row['vae_hist']):+.4g} · "
            f"dead {float(row['vae_dead_zone']):,.4g} · "
            f"explosion {float(row['vae_explosion']):,.4g}"
        )
        reasons.append(
            f"Volume delta buy-sell ≈ {vdelta:+,.0f} "
            f"(buy {float(row['buy_volume']):,.0f} / sell {float(row['sell_volume']):,.0f})"
        )

        if ut == 1:
            conf += 12
            reasons.append("UT Bot **bullish**")
        elif ut == -1:
            conf += 12
            reasons.append("UT Bot **bearish**")

        if qqe == 1:
            conf += 14
            reasons.append(f"QQE trend **up** · RSI {float(row['rsi_55']):.1f}")
        elif qqe == -1:
            conf += 14
            reasons.append(f"QQE trend **down** · RSI {float(row['rsi_55']):.1f}")

        if bool(row.get("vae_above_explosion")):
            conf += 10
            reasons.append("Vaddah Attar histogram **above explosion line** — sharp momentum")
        elif bool(row.get("vae_above_dead")):
            conf += 6
            reasons.append("VAE above dead-zone — volatility sufficient")

        if latest_sig == SIGNAL_BUY:
            direction = "LONG"
            phase = PHASE_ENTRY
            verdict = "TAKE LONG"
            conf += 28
            stop = float(row["stop_loss"])
            target = float(row["take_profit"])
            reasons.append("Confluence: UT Bot + QQE + EMA pullback + VAE + volume delta")
        elif latest_sig == SIGNAL_SELL:
            direction = "SHORT"
            phase = PHASE_ENTRY
            verdict = "TAKE SHORT"
            conf += 28
            stop = float(row["stop_loss"])
            target = float(row["take_profit"])
            reasons.append("Confluence: UT Bot + QQE + EMA pullback + VAE + volume delta")
        elif ut == 1 and qqe == 1 and price > ema200:
            direction = "LONG"
            verdict = "WATCH LONG"
            phase = PHASE_PULLBACK
            conf += 16
            stop = ema34_lo
            risk = max(price - stop, price * 0.002)
            target = price + risk * cfg.rr_ratio
            reasons.append("Bullish filter — await pullback into 34 EMA band + volume confirm")
        elif ut == -1 and qqe == -1 and price < ema200:
            direction = "SHORT"
            verdict = "WATCH SHORT"
            phase = PHASE_PULLBACK
            conf += 16
            stop = ema34_hi
            risk = max(stop - price, price * 0.002)
            target = price - risk * cfg.rr_ratio
            reasons.append("Bearish filter — await pullback into 34 EMA band + volume confirm")
        elif ut != 0 and qqe == ut:
            verdict = f"WATCH — {'LONG' if ut == 1 else 'SHORT'} filter aligned"
            phase = PHASE_FILTER
            conf += 10

    conf = max(12.0, min(92.0, conf))
    take = phase == PHASE_ENTRY and conf >= cfg.take_confidence_threshold

    if direction == "LONG" and stop < price:
        sl_pct = max(0.12, (price - stop) / price * 100)
        tp_pct = max(0.2, (target - price) / price * 100) if target > price else sl_pct * cfg.rr_ratio
    elif direction == "SHORT" and stop > price:
        sl_pct = max(0.12, (stop - price) / price * 100)
        tp_pct = max(0.2, (price - target) / price * 100) if target < price else sl_pct * cfg.rr_ratio
    else:
        sl_pct = 0.35
        tp_pct = sl_pct * cfg.rr_ratio

    hold = HOLD_MULTI_INDICATOR
    plan = make_trade_plan(
        direction=direction if take else "—",
        timeframe=cfg.execution_tf,
        stop_loss_pct=round(sl_pct, 2),
        take_profit_pct=round(tp_pct, 2),
        confidence_pct=round(conf, 1),
        style="intraday",
        exit_rule="Tight scalp SL below EMA band / UT trail · min 2:1 R:R.",
        max_hold_exit="Flatten by session close if target not hit.",
    )

    return enrich_intra_live({
        "signal": "BUY" if latest_sig == SIGNAL_BUY else ("SELL" if latest_sig == SIGNAL_SELL else "NONE"),
        "direction": direction,
        "take_trade": take,
        "verdict": verdict,
        "phase": phase,
        "confidence_pct": round(conf, 1),
        "sl_pct": round(sl_pct, 2),
        "tp_pct": round(tp_pct, 2),
        "hold_duration": hold,
        "rr_ratio": cfg.rr_ratio,
        "entry_price": round(price, 6),
        "stop_price": round(stop, 6),
        "target_price": round(target, 6),
        "ut_signal": ut,
        "qqe_signal": qqe,
        "rsi_55": round(float(row["rsi_55"]), 2) if pd.notna(row.get("rsi_55")) else None,
        "volume_delta": round(float(row["volume_delta"]), 2) if pd.notna(row.get("volume_delta")) else None,
        "vae_hist": round(float(row["vae_hist"]), 4) if pd.notna(row.get("vae_hist")) else None,
        "ema_34_high": round(ema34_hi, 6),
        "ema_34_low": round(ema34_lo, 6),
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": hold},
    }, hold_duration=hold)


def fetch_data(
    ticker: str,
    market: str,
    cfg: MultiIndicatorConfig,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    df = fetch_data_for_gap_scan(
        ticker, cfg.execution_tf, market, groww_token, exchange, limit=cfg.lookback_bars,
    )
    df = normalize_ohlcv(df)
    if df.empty or len(df) < cfg.min_bars:
        df = normalize_ohlcv(
            fetch_ohlcv_yfinance(
                ticker, cfg.execution_tf, is_crypto=is_crypto, limit=cfg.lookback_bars, market=market,
            ),
        )
    return _ensure_market_tz(df, market)


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: MultiIndicatorConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or MultiIndicatorConfig()
    df = fetch_data(ticker, market, cfg, groww_token=groww_token, exchange=exchange)
    if df.empty or len(df) < cfg.min_bars:
        return {"ticker": ticker, "error": f"Insufficient {cfg.execution_tf} data."}

    work = apply_scalping_multi_indicator(df, cfg)
    live = evaluate_live_signal(work, cfg, market=market)
    signals = work[work["signal"].isin([SIGNAL_BUY, SIGNAL_SELL])]

    return {
        "ticker": ticker,
        "market": market,
        "execution_tf": cfg.execution_tf,
        "bars": len(work),
        "last_close": float(work["close"].iloc[-1]),
        "signal_count": len(signals),
        "live": live,
    }


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: MultiIndicatorConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or MultiIndicatorConfig()
    results = []
    for ticker in tickers:
        try:
            results.append(analyze_ticker(ticker, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            results.append({"ticker": ticker, "error": str(exc)[:200]})

    entries = [r for r in results if not r.get("error") and (r.get("live") or {}).get("take_trade")]
    watches = [
        r for r in results
        if not r.get("error")
        and not (r.get("live") or {}).get("take_trade")
        and (r.get("live") or {}).get("verdict", "").startswith("WATCH")
    ]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))
    watches.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market,
        "execution_tf": cfg.execution_tf,
        "results": results,
        "entries": entries,
        "watchlist": watches,
        "entry_count": len(entries),
        "watch_count": len(watches),
    }
