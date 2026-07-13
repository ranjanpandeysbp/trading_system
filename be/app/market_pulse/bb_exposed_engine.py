"""
bb_exposed_engine.py
--------------------
Mind Math Money — Bollinger Band Exposed strategies.

Free Bar reversal (full candle outside bands) + Squeeze breakout after volatility contraction.
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

logger = logging.getLogger(__name__)

YOUTUBE_BB_EXPOSED_URL = "https://www.youtube.com/watch?v=dnSoD4iO0YU&t=148s"

PRESET_DAY = "day"
PRESET_SWING = "swing"
PRESETS: dict[str, dict[str, Any]] = {
    PRESET_DAY: {"bb_length": 10, "bb_std": 1.5, "label": "Day trading / Scalp"},
    PRESET_SWING: {"bb_length": 50, "bb_std": 2.5, "label": "Swing / Institutional"},
}

PHASE_NONE = "NO_SETUP"
PHASE_FREE_BAR_LONG = "FREE_BAR_LONG"
PHASE_FREE_BAR_SHORT = "FREE_BAR_SHORT"
PHASE_SQUEEZE = "SQUEEZE"
PHASE_SQUEEZE_LONG = "SQUEEZE_BREAKOUT_LONG"
PHASE_SQUEEZE_SHORT = "SQUEEZE_BREAKOUT_SHORT"

SIGNAL_BUY = 1
SIGNAL_SELL = -1

PHASE_PRIORITY = {
    PHASE_SQUEEZE_LONG: 95,
    PHASE_SQUEEZE_SHORT: 95,
    PHASE_FREE_BAR_LONG: 90,
    PHASE_FREE_BAR_SHORT: 90,
    PHASE_SQUEEZE: 55,
    PHASE_NONE: 10,
}


@dataclass
class BbExposedConfig:
    preset: str = PRESET_DAY
    bb_length: int = 10
    bb_std: float = 1.5
    rr_ratio: float = 2.0
    require_reversal_candle: bool = True
    squeeze_lookback: int = 50
    squeeze_pctile: float = 0.2
    squeeze_recent_bars: int = 5
    take_confidence_threshold: float = 58.0
    limit: int = 400
    min_bars: int = 80

    def apply_preset(self) -> None:
        p = PRESETS.get(self.preset)
        if p:
            self.bb_length = int(p["bb_length"])
            self.bb_std = float(p["bb_std"])


def _is_doji(o: float, h: float, l: float, c: float) -> bool:
    rng = max(h - l, 1e-12)
    return abs(c - o) / rng < 0.25


def _is_hammer(o: float, h: float, l: float, c: float) -> bool:
    body = max(abs(c - o), rng * 0.08) if (rng := h - l) else 0.01
    lower = min(o, c) - l
    upper = h - max(o, c)
    return lower >= 2 * body and lower > upper


def _is_inverted_hammer(o: float, h: float, l: float, c: float) -> bool:
    body = max(abs(c - o), rng * 0.08) if (rng := h - l) else 0.01
    lower = min(o, c) - l
    upper = h - max(o, c)
    return upper >= 2 * body and upper > lower


def _reversal_candle(o: float, h: float, l: float, c: float, side: str) -> bool:
    if side == "LONG":
        return _is_doji(o, h, l, c) or _is_hammer(o, h, l, c)
    return _is_doji(o, h, l, c) or _is_inverted_hammer(o, h, l, c)


def implement_bollinger_strategies(df: pd.DataFrame, cfg: BbExposedConfig) -> pd.DataFrame:
    """Annotate OHLCV with BB bands, free-bar and squeeze signals."""
    work = normalize_ohlcv(df)
    if work.empty:
        return work

    length = cfg.bb_length
    num_std = cfg.bb_std
    work = work.copy()
    work["middle_band"] = work["close"].rolling(length).mean()
    work["std_dev"] = work["close"].rolling(length).std()
    work["upper_band"] = work["middle_band"] + num_std * work["std_dev"]
    work["lower_band"] = work["middle_band"] - num_std * work["std_dev"]
    work["bandwidth"] = (work["upper_band"] - work["lower_band"]) / work["middle_band"].replace(0, np.nan)

    work["free_bar_signal"] = 0
    work["squeeze_signal"] = 0
    work["setup_phase"] = PHASE_NONE
    work["stop_loss"] = np.nan
    work["take_profit"] = np.nan

    bw_pctile = work["bandwidth"].rolling(cfg.squeeze_lookback).quantile(cfg.squeeze_pctile)

    for i in range(max(length + 2, cfg.squeeze_lookback), len(work)):
        ts = work.index[i]
        o, h, l, c = (
            float(work["open"].iloc[i]),
            float(work["high"].iloc[i]),
            float(work["low"].iloc[i]),
            float(work["close"].iloc[i]),
        )
        ub = float(work["upper_band"].iloc[i])
        lb = float(work["lower_band"].iloc[i])
        mb = float(work["middle_band"].iloc[i])

        if np.isnan(ub) or np.isnan(lb):
            continue

        phase = PHASE_NONE
        sig = 0
        sl = tp = np.nan

        if l > ub:
            phase = PHASE_FREE_BAR_SHORT
            sig = SIGNAL_SELL
            sl = h * 1.001
            risk = max(sl - c, c * 0.003)
            tp = c - risk * cfg.rr_ratio
            work.at[ts, "free_bar_signal"] = SIGNAL_SELL
        elif h < lb:
            phase = PHASE_FREE_BAR_LONG
            sig = SIGNAL_BUY
            sl = l * 0.999
            risk = max(c - sl, c * 0.003)
            tp = c + risk * cfg.rr_ratio
            work.at[ts, "free_bar_signal"] = SIGNAL_BUY

        recent = work["bandwidth"].iloc[max(0, i - cfg.squeeze_recent_bars) : i]
        pct = float(bw_pctile.iloc[i]) if pd.notna(bw_pctile.iloc[i]) else np.nan
        is_squeezed = (
            not recent.empty
            and pct == pct
            and float(recent.mean()) <= pct
        )

        if is_squeezed:
            if phase == PHASE_NONE:
                phase = PHASE_SQUEEZE
            if c > ub:
                phase = PHASE_SQUEEZE_LONG
                sig = SIGNAL_BUY
                sl = mb if mb < c else l
                risk = max(c - sl, c * 0.003)
                tp = c + risk * cfg.rr_ratio
                work.at[ts, "squeeze_signal"] = SIGNAL_BUY
            elif c < lb:
                phase = PHASE_SQUEEZE_SHORT
                sig = SIGNAL_SELL
                sl = mb if mb > c else h
                risk = max(sl - c, c * 0.003)
                tp = c - risk * cfg.rr_ratio
                work.at[ts, "squeeze_signal"] = SIGNAL_SELL

        if sig != 0:
            work.at[ts, "setup_phase"] = phase
            work.at[ts, "stop_loss"] = sl
            work.at[ts, "take_profit"] = tp
        elif phase == PHASE_SQUEEZE:
            work.at[ts, "setup_phase"] = phase

    return work


def evaluate_live(
    work: pd.DataFrame,
    cfg: BbExposedConfig,
) -> dict[str, Any]:
    if work.empty:
        return {"error": "No data"}

    row = work.iloc[-1]
    price = float(row["close"])
    o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), price
    ub = float(row["upper_band"]) if pd.notna(row["upper_band"]) else price
    lb = float(row["lower_band"]) if pd.notna(row["lower_band"]) else price
    mb = float(row["middle_band"]) if pd.notna(row["middle_band"]) else price
    bw = float(row["bandwidth"]) if pd.notna(row["bandwidth"]) else 0.0

    free_sig = int(row["free_bar_signal"]) if pd.notna(row["free_bar_signal"]) else 0
    sq_sig = int(row["squeeze_signal"]) if pd.notna(row["squeeze_signal"]) else 0
    phase = str(row["setup_phase"]) if pd.notna(row["setup_phase"]) else PHASE_NONE

    reasons: list[str] = []
    conf = 18.0
    direction = "WAIT"
    verdict = "WAIT"
    strategy = "—"
    stop = price
    target = price

    reasons.append(f"BB({cfg.bb_length}, {cfg.bb_std}) · bandwidth {bw:.4f}")

    if l > ub:
        phase = PHASE_FREE_BAR_SHORT
        strategy = "Free Bar Reversal"
        direction = "SHORT"
        conf += 28
        reasons.append("Free bar — entire candle above upper band (volatility exhaustion)")
        if cfg.require_reversal_candle:
            if _reversal_candle(o, h, l, c, "SHORT"):
                conf += 18
                verdict = "TAKE SHORT"
                reasons.append("Reversal candle (doji / inverted hammer) confirms fade")
            else:
                verdict = "WATCH SHORT"
                reasons.append("Await reversal price action — do not fade blindly")
        else:
            verdict = "TAKE SHORT"
        stop = h * 1.001
        risk = max(stop - price, price * 0.003)
        target = price - risk * cfg.rr_ratio
        reasons.append("SL beyond free-bar wick high · target 2:1 R:R")

    elif h < lb:
        phase = PHASE_FREE_BAR_LONG
        strategy = "Free Bar Reversal"
        direction = "LONG"
        conf += 28
        reasons.append("Free bar — entire candle below lower band (volatility exhaustion)")
        if cfg.require_reversal_candle:
            if _reversal_candle(o, h, l, c, "LONG"):
                conf += 18
                verdict = "TAKE LONG"
                reasons.append("Reversal candle (doji / hammer) confirms fade")
            else:
                verdict = "WATCH LONG"
                reasons.append("Await reversal price action — do not fade blindly")
        else:
            verdict = "TAKE LONG"
        stop = l * 0.999
        risk = max(price - stop, price * 0.003)
        target = price + risk * cfg.rr_ratio
        reasons.append("SL beyond free-bar wick low · target 2:1 R:R")

    elif phase == PHASE_SQUEEZE or (sq_sig == 0 and bw > 0):
        recent_bw = work["bandwidth"].tail(cfg.squeeze_recent_bars)
        pct_ser = work["bandwidth"].rolling(cfg.squeeze_lookback).quantile(cfg.squeeze_pctile)
        pct_val = float(pct_ser.iloc[-1]) if pd.notna(pct_ser.iloc[-1]) else np.nan
        if not recent_bw.empty and pct_val == pct_val and float(recent_bw.mean()) <= pct_val:
            phase = PHASE_SQUEEZE
            strategy = "BB Squeeze"
            conf += 16
            reasons.append("Squeeze — bandwidth contracted (low volatility → breakout pending)")
            if c > ub:
                phase = PHASE_SQUEEZE_LONG
                direction = "LONG"
                verdict = "TAKE LONG"
                conf += 26
                stop = mb if mb < price else l
                risk = max(price - stop, price * 0.003)
                target = price + risk * cfg.rr_ratio
                reasons.append("Bullish squeeze breakout — close above upper band")
            elif c < lb:
                phase = PHASE_SQUEEZE_SHORT
                direction = "SHORT"
                verdict = "TAKE SHORT"
                conf += 26
                stop = mb if mb > price else h
                risk = max(stop - price, price * 0.003)
                target = price - risk * cfg.rr_ratio
                reasons.append("Bearish squeeze breakout — close below lower band")
            else:
                verdict = "WATCH SQUEEZE"
                reasons.append("Inside squeeze — wait for decisive close outside bands")

    if free_sig == SIGNAL_BUY or sq_sig == SIGNAL_BUY:
        direction = "LONG"
    elif free_sig == SIGNAL_SELL or sq_sig == SIGNAL_SELL:
        direction = "SHORT"

    if pd.notna(row.get("stop_loss")):
        stop = float(row["stop_loss"])
    if pd.notna(row.get("take_profit")):
        target = float(row["take_profit"])

    conf = max(12.0, min(92.0, conf))
    actionable = verdict.startswith("TAKE") and conf >= cfg.take_confidence_threshold

    if direction == "LONG" and stop < price:
        sl_pct = max(0.2, (price - stop) / price * 100)
        tp_pct = max(0.35, (target - price) / price * 100) if target > price else sl_pct * cfg.rr_ratio
    elif direction == "SHORT" and stop > price:
        sl_pct = max(0.2, (stop - price) / price * 100)
        tp_pct = max(0.35, (price - target) / price * 100) if target < price else sl_pct * cfg.rr_ratio
    else:
        sl_pct = 0.5
        tp_pct = sl_pct * cfg.rr_ratio

    hold = "Free bar fade or squeeze breakout · session/swing per preset"
    plan = make_trade_plan(
        direction=direction if actionable and direction in ("LONG", "SHORT") else "—",
        timeframe="chart",
        stop_loss_pct=round(sl_pct, 2),
        take_profit_pct=round(tp_pct, 2),
        confidence_pct=round(conf, 1),
        style="intraday" if cfg.preset == PRESET_DAY else "swing",
        exit_rule=f"SL beyond trigger wick · TP {cfg.rr_ratio}:1 R:R minimum.",
        max_hold_exit="Trail or exit on opposite band touch.",
    )

    primary = verdict if actionable else (
        verdict if verdict.startswith("WATCH") else f"{phase} — no trigger"
    )

    return {
        "phase": phase,
        "strategy": strategy,
        "primary_label": primary,
        "direction": direction,
        "verdict": verdict,
        "actionable": actionable,
        "confidence": round(conf, 1),
        "price": price,
        "upper_band": ub,
        "lower_band": lb,
        "middle_band": mb,
        "bandwidth": bw,
        "free_bar_signal": free_sig,
        "squeeze_signal": sq_sig,
        "bb_length": cfg.bb_length,
        "bb_std": cfg.bb_std,
        "preset": cfg.preset,
        "priority": PHASE_PRIORITY.get(phase, 15),
        "trade_plan": {
            "direction": direction if actionable else "—",
            "entry": price,
            "stop_loss": stop,
            "take_profit": target,
            "sl_pct": round(sl_pct, 2),
            "tp_pct": round(tp_pct, 2),
            "rr_ratio": cfg.rr_ratio,
            "hold_duration": hold,
            "exit_rule": plan.get("exit_rule"),
            "notes": f"{strategy} · BB({cfg.bb_length},{cfg.bb_std})",
        },
        "signals_df": work,
        "reasons": reasons,
        "signal_count": int((work["free_bar_signal"] != 0).sum() + (work["squeeze_signal"] != 0).sum()),
    }


def fetch_chart_data(
    ticker: str,
    timeframe: str,
    market: str,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
    limit: int = 400,
) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    df = fetch_data_for_gap_scan(ticker, timeframe, market, groww_token, exchange, limit=limit)
    df = normalize_ohlcv(df)
    if df.empty:
        df = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, timeframe, is_crypto=is_crypto, limit=limit, market=market),
        )
    return df


def analyze_bb_exposed(
    ticker: str,
    market: str,
    timeframe: str,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
    cfg: BbExposedConfig | None = None,
) -> dict[str, Any]:
    cfg = cfg or BbExposedConfig()
    cfg.apply_preset()
    raw = fetch_chart_data(
        ticker, timeframe, market, groww_token=groww_token, exchange=exchange, limit=cfg.limit,
    )
    if raw.empty or len(raw) < cfg.min_bars:
        return {
            "error": f"Insufficient {timeframe} data (need {cfg.min_bars}+ bars).",
            "symbol": ticker,
        }

    work = implement_bollinger_strategies(raw, cfg)
    live = evaluate_live(work, cfg)
    live["symbol"] = ticker
    live["chart_tf"] = timeframe
    live["market"] = market
    return live


def scan_universe(
    tickers: list[str],
    market: str,
    timeframe: str,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
    cfg: BbExposedConfig | None = None,
) -> dict[str, dict[str, Any]]:
    cfg = cfg or BbExposedConfig()
    cfg.apply_preset()
    results: dict[str, dict[str, Any]] = {}
    for ticker in tickers:
        try:
            results[ticker] = analyze_bb_exposed(
                ticker, market, timeframe,
                groww_token=groww_token, exchange=exchange, cfg=cfg,
            )
        except Exception as exc:
            results[ticker] = {"error": str(exc)[:200], "symbol": ticker}
    return results
