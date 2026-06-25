"""
swing_trading_st_ha_ema_engine.py
---------------------------------
Upsurge / Animesh intraday strategy:
  Daily Heikin-Ashi bias + 34 EMA High/Low channel on 5m (or 15m) execution.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.swing_trading_st_kiss_engine import calculate_heikin_ashi
from app.trading_hubs.swing_trading_st_shared import HOLD_HA_EMA_15M, HOLD_HA_EMA_5M, enrich_st_live

logger = logging.getLogger(__name__)

YOUTUBE_ST_HA_EMA_URL = "https://www.youtube.com/watch?v=o5i8WF0UIfE"

EXEC_5M = "5m"
EXEC_15M = "15m"

SIGNAL_BUY = "BUY LONG / CALL"
SIGNAL_SHORT = "SELL SHORT / PUT"
SIGNAL_EXIT = "EXIT"
SIGNAL_HOLD = "Hold/Neutral"

BIAS_GREEN = "Green"
BIAS_RED = "Red"


@dataclass
class HAEmaConfig:
    execution_tf: str = EXEC_5M
    ema_period: int = 34
    rr_ratio: float = 2.0
    risk_per_trade_pct: float = 1.5
    take_confidence_threshold: float = 60.0
    daily_lookback: int = 120
    min_intraday_bars: int = 50


def _daily_ha_bias_map(daily_df: pd.DataFrame) -> dict:
    """Previous completed daily HA candle color → bias for next session."""
    daily_ha = calculate_heikin_ashi(daily_df)
    daily_ha["ha_color"] = np.where(daily_ha["ha_close"] >= daily_ha["ha_open"], BIAS_GREEN, BIAS_RED)
    daily_ha["prev_day_bias"] = daily_ha["ha_color"].shift(1)
    return {
        pd.Timestamp(k).date(): v
        for k, v in zip(daily_ha.index, daily_ha["prev_day_bias"])
        if pd.notna(v)
    }


def implement_ha_ema_strategy(
    daily_df: pd.DataFrame,
    intraday_df: pd.DataFrame,
    cfg: HAEmaConfig,
) -> pd.DataFrame:
    """34 EMA channel entries filtered by daily Heikin-Ashi bias."""
    intraday = normalize_ohlcv(intraday_df)
    if intraday.empty or len(intraday) < cfg.min_intraday_bars:
        return pd.DataFrame()

    bias_map = _daily_ha_bias_map(daily_df)
    intraday = intraday.copy()
    intraday["date_only"] = intraday.index.normalize().date
    intraday["market_bias"] = intraday["date_only"].map(bias_map).ffill()

    p = cfg.ema_period
    intraday["ema_high"] = intraday["high"].ewm(span=p, adjust=False).mean()
    intraday["ema_low"] = intraday["low"].ewm(span=p, adjust=False).mean()
    intraday["signal"] = SIGNAL_HOLD
    intraday["signal_code"] = 0

    position = 0
    breakout_high = 0.0
    breakout_low = 0.0

    for i in range(1, len(intraday)):
        row = intraday.iloc[i]
        prev = intraday.iloc[i - 1]
        bias = row["market_bias"]
        idx = intraday.index[i]

        if position == 0:
            # Breakout candle closes beyond band
            long_setup = (
                bias == BIAS_GREEN
                and prev["close"] <= prev["ema_high"]
                and row["close"] > row["ema_high"]
            )
            short_setup = (
                bias == BIAS_RED
                and prev["close"] >= prev["ema_low"]
                and row["close"] < row["ema_low"]
            )
            # Confirm on break of breakout candle extreme (next-bar trigger per video)
            long_trigger = (
                bias == BIAS_GREEN
                and prev["close"] > prev["ema_high"]
                and row["high"] > prev["high"]
            )
            short_trigger = (
                bias == BIAS_RED
                and prev["close"] < prev["ema_low"]
                and row["low"] < prev["low"]
            )

            if long_trigger:
                intraday.at[idx, "signal"] = SIGNAL_BUY
                intraday.at[idx, "signal_code"] = 1
                position = 1
            elif short_trigger:
                intraday.at[idx, "signal"] = SIGNAL_SHORT
                intraday.at[idx, "signal_code"] = -1
                position = -1
            elif long_setup:
                intraday.at[idx, "signal"] = "WATCH LONG"
                breakout_high = float(row["high"])
            elif short_setup:
                intraday.at[idx, "signal"] = "WATCH SHORT"
                breakout_low = float(row["low"])

        elif position == 1:
            if row["close"] < row["ema_low"]:
                intraday.at[idx, "signal"] = SIGNAL_EXIT
                intraday.at[idx, "signal_code"] = 0
                position = 0
        elif position == -1:
            if row["close"] > row["ema_high"]:
                intraday.at[idx, "signal"] = SIGNAL_EXIT
                intraday.at[idx, "signal_code"] = 0
                position = 0

    intraday["zone"] = np.where(
        intraday["close"] > intraday["ema_high"],
        "above_band",
        np.where(intraday["close"] < intraday["ema_low"], "below_band", "inside_band"),
    )
    return intraday


def _signal_history(work: pd.DataFrame, limit: int = 8) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    actionable = {SIGNAL_BUY, SIGNAL_SHORT, SIGNAL_EXIT, "WATCH LONG", "WATCH SHORT"}
    for i in range(len(work) - 1, -1, -1):
        sig = str(work["signal"].iloc[i])
        if sig not in actionable:
            continue
        ts = work.index[i]
        rows.append({
            "time": ts.strftime("%Y-%m-%d %H:%M") if hasattr(ts, "strftime") else str(ts),
            "signal": sig,
            "bias": work["market_bias"].iloc[i],
            "close": round(float(work["close"].iloc[i]), 4),
            "zone": work["zone"].iloc[i],
        })
        if len(rows) >= limit:
            break
    return rows


def _backtest_ha_ema(work: pd.DataFrame, cfg: HAEmaConfig) -> dict[str, Any]:
    trades: list[float] = []
    in_pos = False
    direction = ""
    entry = 0.0
    stop = 0.0
    target = 0.0

    for i in range(len(work)):
        row = work.iloc[i]
        sig = str(row["signal"])
        close = float(row["close"])

        if sig == SIGNAL_BUY and not in_pos:
            in_pos = True
            direction = "LONG"
            entry = close
            stop = float(row["ema_low"])
            risk = entry - stop if stop < entry else entry * 0.01
            target = entry + risk * cfg.rr_ratio
        elif sig == SIGNAL_SHORT and not in_pos:
            in_pos = True
            direction = "SHORT"
            entry = close
            stop = float(row["ema_high"])
            risk = stop - entry if stop > entry else entry * 0.01
            target = entry - risk * cfg.rr_ratio
        elif in_pos and sig == SIGNAL_EXIT:
            pnl = (close - entry) / entry * 100 if direction == "LONG" else (entry - close) / entry * 100
            trades.append(pnl)
            in_pos = False
        elif in_pos:
            if direction == "LONG" and (close <= stop or close >= target):
                trades.append((close - entry) / entry * 100)
                in_pos = False
            elif direction == "SHORT" and (close >= stop or close <= target):
                trades.append((entry - close) / entry * 100)
                in_pos = False

    if not trades:
        return {"total_trades": 0, "win_rate_pct": 0.0, "avg_pnl_pct": 0.0}
    wins = sum(1 for t in trades if t > 0)
    return {
        "total_trades": len(trades),
        "win_rate_pct": round(wins / len(trades) * 100, 1),
        "avg_pnl_pct": round(float(np.mean(trades)), 2),
    }


def evaluate_live_signal(work: pd.DataFrame, cfg: HAEmaConfig) -> dict[str, Any]:
    if work.empty or len(work) < cfg.min_intraday_bars:
        return {"signal": "NO_DATA"}

    i = len(work) - 1
    row = work.iloc[i]
    prev = work.iloc[i - 1] if i > 0 else row

    close = float(row["close"])
    bias = row.get("market_bias")
    zone = str(row.get("zone", "inside_band"))
    latest_sig = str(row["signal"])
    prev_close = float(prev["close"])
    ema_h = float(row["ema_high"])
    ema_l = float(row["ema_low"])
    prev_ema_h = float(prev["ema_high"])
    prev_ema_l = float(prev["ema_low"])

    reasons: list[str] = []
    conf = 25.0
    direction = "WAIT"
    verdict = "WAIT"
    take = False
    hold_duration = HOLD_HA_EMA_5M if cfg.execution_tf == EXEC_5M else HOLD_HA_EMA_15M

    if bias == BIAS_GREEN:
        reasons.append("Daily HA bias: Green — longs / calls only")
        conf += 22
        direction = "LONG"
    elif bias == BIAS_RED:
        reasons.append("Daily HA bias: Red — shorts / puts only")
        conf += 22
        direction = "SHORT"
    else:
        reasons.append("Daily HA bias unavailable")

    if zone == "above_band" and bias == BIAS_GREEN:
        conf += 20
        reasons.append("Price above 34 EMA High band")
    elif zone == "below_band" and bias == BIAS_RED:
        conf += 20
        reasons.append("Price below 34 EMA Low band")
    elif zone == "inside_band":
        conf -= 8
        reasons.append("Inside 34 EMA channel — avoid chop")

    if latest_sig == SIGNAL_BUY:
        verdict = "TAKE LONG"
        take = conf >= cfg.take_confidence_threshold
        stop = ema_l
    elif latest_sig == SIGNAL_SHORT:
        verdict = "TAKE SHORT"
        take = conf >= cfg.take_confidence_threshold
        stop = ema_h
    elif latest_sig == "WATCH LONG" or (
        bias == BIAS_GREEN and prev_close > prev_ema_h and close <= prev["high"]
    ):
        verdict = "WATCH LONG"
        direction = "LONG"
        reasons.append("Breakout candle formed — await break above candle high")
        stop = ema_l
    elif latest_sig == "WATCH SHORT" or (
        bias == BIAS_RED and prev_close < prev_ema_l and close >= prev["low"]
    ):
        verdict = "WATCH SHORT"
        direction = "SHORT"
        reasons.append("Breakdown candle formed — await break below candle low")
        stop = ema_h
    elif bias == BIAS_GREEN and prev_close <= prev_ema_h and close > ema_h:
        verdict = "WATCH LONG"
        direction = "LONG"
        reasons.append("Close crossed above upper band — confirm on next bar break")
        stop = ema_l
    elif bias == BIAS_RED and prev_close >= prev_ema_l and close < ema_l:
        verdict = "WATCH SHORT"
        direction = "SHORT"
        reasons.append("Close crossed below lower band — confirm on next bar break")
        stop = ema_h
    else:
        stop = ema_l if direction == "LONG" else ema_h

    conf = max(20.0, min(90.0, conf))

    if direction == "LONG" and stop < close:
        sl_pct = max(0.4, (close - stop) / close * 100)
        tp_pct = sl_pct * cfg.rr_ratio
        target = close * (1 + tp_pct / 100)
    elif direction == "SHORT" and stop > close:
        sl_pct = max(0.4, (stop - close) / close * 100)
        tp_pct = sl_pct * cfg.rr_ratio
        target = close * (1 - tp_pct / 100)
    else:
        sl_pct = 1.0
        tp_pct = sl_pct * cfg.rr_ratio
        target = close

    plan = make_trade_plan(
        direction=direction if take else "—",
        timeframe=cfg.execution_tf,
        stop_loss_pct=round(sl_pct, 2),
        take_profit_pct=round(tp_pct, 2),
        confidence_pct=round(conf, 1),
        style="intraday",
        exit_rule="; ".join(reasons[:2]) if reasons else "HA bias + 34 EMA channel",
        max_hold_exit="Close all intraday positions before session end (Friday for swings).",
    )

    option_hint = "Buy CALL" if direction == "LONG" else ("Buy PUT" if direction == "SHORT" else "—")

    return enrich_st_live({
        "signal": latest_sig if latest_sig != SIGNAL_HOLD else "NONE",
        "direction": direction,
        "take_trade": take,
        "verdict": verdict,
        "confidence_pct": round(conf, 1),
        "sl_pct": round(sl_pct, 2),
        "tp_pct": round(tp_pct, 2),
        "hold_duration": hold_duration,
        "rr_ratio": round(cfg.rr_ratio, 2),
        "entry_price": round(close, 6),
        "stop_price": round(stop, 6),
        "target_price": round(target, 6),
        "market_bias": str(bias) if pd.notna(bias) else "—",
        "zone": zone,
        "option_hint": option_hint,
        "ema_high": round(ema_h, 4),
        "ema_low": round(ema_l, 4),
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": hold_duration},
    }, hold_duration=hold_duration)


def fetch_ha_ema_data(
    ticker: str,
    market: str,
    cfg: HAEmaConfig,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    is_crypto = "CoinDCX" in market
    daily = fetch_data_for_gap_scan(
        ticker, "1d", market, groww_token, exchange, limit=cfg.daily_lookback,
    )
    daily = normalize_ohlcv(daily)
    if daily.empty or len(daily) < 20:
        daily = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, "1d", is_crypto=is_crypto, limit=cfg.daily_lookback, market=market),
        )

    limit = 400 if cfg.execution_tf == EXEC_5M else 300
    intra = fetch_data_for_gap_scan(ticker, cfg.execution_tf, market, groww_token, exchange, limit=limit)
    intra = normalize_ohlcv(intra)
    if intra.empty or len(intra) < cfg.min_intraday_bars:
        intra = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, cfg.execution_tf, is_crypto=is_crypto, limit=limit, market=market),
        )
    return daily, intra


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: HAEmaConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or HAEmaConfig()
    daily, intra = fetch_ha_ema_data(ticker, market, cfg, groww_token=groww_token, exchange=exchange)
    if daily.empty or len(daily) < 15:
        return {"ticker": ticker, "error": "Insufficient daily data for Heikin-Ashi bias."}
    if intra.empty or len(intra) < cfg.min_intraday_bars:
        return {"ticker": ticker, "error": f"Insufficient {cfg.execution_tf} intraday data."}

    work = implement_ha_ema_strategy(daily, intra, cfg)
    if work.empty:
        return {"ticker": ticker, "error": "Could not build HA + EMA channel frame."}

    live = evaluate_live_signal(work, cfg)
    return {
        "ticker": ticker,
        "market": market,
        "execution_tf": cfg.execution_tf,
        "bars": len(work),
        "last_close": float(work["close"].iloc[-1]),
        "market_bias": live.get("market_bias"),
        "zone": live.get("zone"),
        "option_hint": live.get("option_hint"),
        "signal_history": _signal_history(work),
        "live": live,
        "backtest": _backtest_ha_ema(work, cfg),
    }


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: HAEmaConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or HAEmaConfig()
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
