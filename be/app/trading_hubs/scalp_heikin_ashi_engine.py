"""
scalp_heikin_ashi_engine.py
----------------------------
Scalp - Heikin Ashi — 100 EMA pullback + high-volume Doji scalp.
Video: https://www.youtube.com/watch?v=_q-VI9hGNTE

Trend-following pullback strategy for the 1-minute chart, built for the
high-volume morning session:

1. Chart setup: Heikin Ashi candles (averages price action to filter noise) +
   a 100-period EMA, traded only in a market-specific morning window.
2. Market structure: price above the 100 EMA → only look for BUYS; price below
   → only look for SELLS; price chopping through the EMA → no-trade zone.
3. Clean pullback: at least two consecutive "flat" Heikin Ashi candles —
   flat-top red candles pulling down toward the EMA (for buys), or flat-bottom
   green candles pushing up toward the EMA (for sells). "Flat" means no wick
   on the side facing the trend, i.e. no upper wick on a red pullback candle,
   no lower wick on a green pullback candle.
4. Entry trigger: the pullback ends with a high-volume Doji — a small body,
   long wicks both ways, and a total candle range bigger than at least one of
   the two preceding pullback candles (an "unhealthy"/violent indecision bar).
5. Entry the instant the Doji closes; stop just beyond the Doji's far wick.
6. Target: a strict 1:1 risk-to-reward (configurable).

Session window is adapted per market (the video's own 10:00-12:00 ET window
is built around avoiding the chaotic 9:30 ET open while still catching high
volume — the same "30 minutes after open, ~2.5 hours wide" structure is
mapped onto each market's own open):
  - US: 10:00-12:00 ET (as in the video)
  - India: 09:45-11:45 IST (NSE opens 09:15 IST; same offset/width)
  - Crypto: no session-window restriction — there is no "chaotic open" to
    avoid in 24/7 trading, so the time filter is skipped (this is a deliberate
    adaptation, not a bug: crypto is evaluated at any time of day).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import time
from typing import Any

import numpy as np
import pandas as pd

from app.trading_hubs.session_constants import IST_TZ, NY_TZ
from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.trading_hubs.intraday_shared import enrich_intra_live
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan
from app.market_pulse.ticker_utils import is_crypto_market

logger = logging.getLogger(__name__)

YOUTUBE_SCALP_HA_URL = "https://www.youtube.com/watch?v=_q-VI9hGNTE"

EXEC_TF = "1m"
HOLD_SCALP_HA = "Same session — 1:1 R:R scalp, exit at stop or target."

PHASE_OUTSIDE_WINDOW = "OUTSIDE_WINDOW"
PHASE_NO_TREND = "NO_TREND"
PHASE_AWAITING_PULLBACK = "AWAITING_PULLBACK"
PHASE_ENTRY = "ENTRY_TRIGGERED"


def session_mode_for_market(market: str) -> str:
    """Groww India stocks -> IST session; CoinDCX / others -> NY session."""
    if "Groww" in market or "India" in market:
        return "india"
    return "ny"


@dataclass
class HeikinAshiScalpConfig:
    ema_period: int = 100
    doji_body_ratio: float = 0.2
    flat_wick_tolerance: float = 0.05
    chop_lookback_bars: int = 10
    chop_cross_threshold: int = 3
    rr_ratio: float = 1.0
    take_confidence_threshold: float = 60.0
    min_bars: int = 150


def _fetch_ohlcv(
    ticker: str, market: str, *, groww_token: str = "", exchange: str = "NSE", limit: int = 400,
) -> pd.DataFrame:
    is_crypto = is_crypto_market(market)
    df = fetch_data_for_gap_scan(ticker, EXEC_TF, market, groww_token, exchange, limit=limit)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < 60:
        df = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, EXEC_TF, is_crypto=is_crypto, limit=limit, market=market),
        )
    return df


def _session_window(market: str) -> tuple[time, time] | None:
    if is_crypto_market(market):
        return None
    if session_mode_for_market(market) == "india":
        return time(9, 45), time(11, 45)
    return time(10, 0), time(12, 0)


def _localize(df: pd.DataFrame, market: str) -> pd.DataFrame:
    work = df.copy()
    tz = IST_TZ if session_mode_for_market(market) == "india" else NY_TZ
    if work.index.tz is None:
        work.index = work.index.tz_localize(tz)
    else:
        work.index = work.index.tz_convert(tz)
    return work


def _heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    ha_close = ((df["open"] + df["high"] + df["low"] + df["close"]) / 4).to_numpy()
    ha_open = np.empty(len(df))
    ha_open[0] = (df["open"].iloc[0] + df["close"].iloc[0]) / 2
    for i in range(1, len(df)):
        ha_open[i] = (ha_open[i - 1] + ha_close[i - 1]) / 2
    real_high = df["high"].to_numpy()
    real_low = df["low"].to_numpy()
    ha_high = np.maximum.reduce([real_high, ha_open, ha_close])
    ha_low = np.minimum.reduce([real_low, ha_open, ha_close])
    return pd.DataFrame(
        {"ha_open": ha_open, "ha_high": ha_high, "ha_low": ha_low, "ha_close": ha_close},
        index=df.index,
    )


def analyze_ticker(
    ticker: str, market: str, *, cfg: HeikinAshiScalpConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or HeikinAshiScalpConfig()
    df = _fetch_ohlcv(ticker, market, groww_token=groww_token, exchange=exchange)
    if df.empty or len(df) < cfg.min_bars:
        return {"ticker": ticker, "market": market, "error": f"Insufficient {EXEC_TF} data ({len(df)} bars, need {cfg.min_bars}+)."}

    work = _localize(df, market)
    ha = _heikin_ashi(work)

    ema = ha["ha_close"].ewm(span=cfg.ema_period, adjust=False).mean()
    candle_size = (ha["ha_high"] - ha["ha_low"]).to_numpy()
    body_size = (ha["ha_open"] - ha["ha_close"]).abs().to_numpy()
    upper_wick = (ha["ha_high"] - ha[["ha_open", "ha_close"]].max(axis=1)).to_numpy()
    lower_wick = (ha[["ha_open", "ha_close"]].min(axis=1) - ha["ha_low"]).to_numpy()
    is_bear = (ha["ha_close"] < ha["ha_open"]).to_numpy()
    is_bull = (ha["ha_close"] > ha["ha_open"]).to_numpy()
    safe_size = np.where(candle_size == 0, np.nan, candle_size)
    flat_top = (upper_wick <= cfg.flat_wick_tolerance * safe_size) & is_bear
    flat_bottom = (lower_wick <= cfg.flat_wick_tolerance * safe_size) & is_bull
    is_doji = body_size <= cfg.doji_body_ratio * safe_size

    real_price = float(df["close"].iloc[-1])
    n = len(work)
    last_ts = work.index[-1]

    base = {"ticker": ticker, "market": market, "timeframe": EXEC_TF, "price": real_price}

    window = _session_window(market)
    if window is not None:
        start, end = window
        t = last_ts.time()
        if not (start <= t < end):
            base["phase"] = PHASE_OUTSIDE_WINDOW
            base["live"] = enrich_intra_live({
                "direction": "WAIT", "verdict": "WAIT", "take_trade": False, "confidence_pct": 0.0,
                "reasons": [f"Outside the trading window ({start.strftime('%H:%M')}-{end.strftime('%H:%M')} "
                            f"local session time) — current bar is {t.strftime('%H:%M')}."],
            }, hold_duration=HOLD_SCALP_HA)
            return base

    i = n - 1
    ema_now = float(ema.iloc[i])
    close_now = float(ha["ha_close"].iloc[i])

    lookback = ema.iloc[max(0, i - cfg.chop_lookback_bars + 1):i + 1]
    closes_lb = ha["ha_close"].iloc[max(0, i - cfg.chop_lookback_bars + 1):i + 1]
    above = (closes_lb.to_numpy() > lookback.to_numpy())
    crossings = int(np.sum(above[1:] != above[:-1])) if len(above) > 1 else 0
    choppy = crossings >= cfg.chop_cross_threshold

    if choppy:
        base["phase"] = PHASE_NO_TREND
        base["live"] = enrich_intra_live({
            "direction": "WAIT", "verdict": "WAIT", "take_trade": False, "confidence_pct": 0.0,
            "reasons": [f"Price is chopping through the {cfg.ema_period} EMA ({crossings} crosses in the "
                        f"last {cfg.chop_lookback_bars} bars) — no-trade zone per the strategy's own rule."],
        }, hold_duration=HOLD_SCALP_HA)
        return base

    trend_up = close_now > ema_now
    direction = "LONG" if trend_up else "SHORT"

    if i < 2:
        base["phase"] = PHASE_AWAITING_PULLBACK
        base["live"] = enrich_intra_live({
            "direction": direction, "verdict": f"WATCH {direction}", "take_trade": False, "confidence_pct": 30.0,
            "reasons": ["Not enough bars yet to check for a 2-candle pullback."],
        }, hold_duration=HOLD_SCALP_HA)
        return base

    doji_now = bool(is_doji[i]) if not np.isnan(body_size[i]) and not np.isnan(candle_size[i]) else False
    bigger_than_prior = candle_size[i] > candle_size[i - 1] or candle_size[i] > candle_size[i - 2]
    pullback_ok = bool(flat_top[i - 1] and flat_top[i - 2]) if trend_up else bool(flat_bottom[i - 1] and flat_bottom[i - 2])

    if not (doji_now and bigger_than_prior and pullback_ok):
        missing = []
        if not pullback_ok:
            side = "flat-top red" if trend_up else "flat-bottom green"
            missing.append(f"no clean 2-candle {side} pullback yet")
        if not doji_now:
            missing.append("last candle isn't a Doji")
        elif not bigger_than_prior:
            missing.append("Doji isn't larger than either preceding pullback candle")
        base["phase"] = PHASE_AWAITING_PULLBACK
        base["live"] = enrich_intra_live({
            "direction": direction, "verdict": f"WATCH {direction}", "take_trade": False, "confidence_pct": 38.0,
            "reasons": [
                f"Price {'above' if trend_up else 'below'} the {cfg.ema_period} EMA — only looking for "
                f"{'BUYS' if trend_up else 'SELLS'}.",
                f"Waiting for setup: {', '.join(missing)}.",
            ],
        }, hold_duration=HOLD_SCALP_HA)
        return base

    doji_high = float(ha["ha_high"].iloc[i])
    doji_low = float(ha["ha_low"].iloc[i])
    entry = real_price
    if direction == "LONG":
        stop = doji_low * (1 - 0.0005)
        risk = entry - stop
        target = entry + risk * cfg.rr_ratio
    else:
        stop = doji_high * (1 + 0.0005)
        risk = stop - entry
        target = entry - risk * cfg.rr_ratio

    conf = 55.0
    conf += 15.0 if (candle_size[i] > candle_size[i - 1] and candle_size[i] > candle_size[i - 2]) else 5.0
    conf += 15.0 if crossings <= 1 else 0.0
    conf = round(min(90.0, conf), 1)
    take = risk > 0 and conf >= cfg.take_confidence_threshold

    sl_pct = round(abs(entry - stop) / entry * 100, 2) if entry else 0.0
    tp_pct = round(abs(target - entry) / entry * 100, 2) if entry else 0.0
    plan = make_trade_plan(
        direction=direction if take else "—", timeframe=EXEC_TF,
        stop_loss_pct=sl_pct, take_profit_pct=tp_pct, confidence_pct=conf, style="scalping",
        exit_rule="Strict 1:1 R:R — exit at stop or target, no trailing beyond that.",
        max_hold_exit="Time stop: same session, exit by close.",
    )
    reasons = [
        f"Price {'above' if trend_up else 'below'} the {cfg.ema_period} EMA — trend favors "
        f"{'BUYS' if trend_up else 'SELLS'} ({crossings} EMA cross(es) in the last {cfg.chop_lookback_bars} bars).",
        f"Clean pullback: two consecutive {'flat-top red' if trend_up else 'flat-bottom green'} Heikin Ashi candles into the EMA.",
        f"High-volume Doji just closed — range {candle_size[i]:.4g} vs prior two "
        f"{candle_size[i-1]:.4g}/{candle_size[i-2]:.4g} — indecision bar bigger than the pullback it ends.",
    ]

    base["phase"] = PHASE_ENTRY
    base["live"] = enrich_intra_live({
        "direction": direction, "take_trade": take,
        "verdict": f"{'TAKE' if take else 'WATCH'} {direction}",
        "confidence_pct": conf,
        "entry_price": round(entry, 6), "stop_price": round(stop, 6), "target_price": round(target, 6),
        "sl_pct": sl_pct, "tp_pct": tp_pct, "rr_ratio": cfg.rr_ratio,
        "reasons": reasons,
        "trade_plan": {**plan, "direction": direction if take else "—", "holding_period": HOLD_SCALP_HA},
    }, hold_duration=HOLD_SCALP_HA)
    return base


def scan_universe(
    tickers: list[str], market: str, *, cfg: HeikinAshiScalpConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or HeikinAshiScalpConfig()
    results = []
    for ticker in tickers:
        try:
            results.append(analyze_ticker(ticker, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            logger.debug("Scalp Heikin Ashi scan failed for %s: %s", ticker, exc)
            results.append({"ticker": ticker, "market": market, "error": str(exc)[:200]})

    entries = [r for r in results if not r.get("error") and (r.get("live") or {}).get("take_trade")]
    watches = [
        r for r in results
        if not r.get("error")
        and not (r.get("live") or {}).get("take_trade")
        and r.get("phase") in (PHASE_AWAITING_PULLBACK, PHASE_ENTRY)
    ]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))
    watches.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market,
        "results": results,
        "entries": entries,
        "watchlist": watches,
        "entry_count": len(entries),
        "watch_count": len(watches),
    }
