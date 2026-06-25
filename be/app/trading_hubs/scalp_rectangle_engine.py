"""
scalp_rectangle_engine.py
-------------------------
1-Minute Rectangle Scalping Strategy (Mulham Trading — Sniper Entry).

FVG + liquidity sweep → rectangle zone → close breakout entry. Min 3:1 R:R.
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

logger = logging.getLogger(__name__)

YOUTUBE_SCALP_RECTANGLE_URL = "https://www.youtube.com/watch?v=yyYwZIMrfGI"

PHASE_NONE = "NO_SETUP"
PHASE_RECT_LONG = "RECTANGLE_LONG"
PHASE_RECT_SHORT = "RECTANGLE_SHORT"
PHASE_ENTRY = "SNIPER_ENTRY"

SIGNAL_BUY = 1
SIGNAL_SELL = -1


@dataclass
class RectangleConfig:
    execution_tf: str = "1m"
    swing_window: int = 5
    rr_ratio: float = 3.0
    take_confidence_threshold: float = 60.0
    min_bars: int = 80
    lookback_bars: int = 500


@dataclass
class RectangleSetup:
    direction: str
    phase: str
    rect_top: float
    rect_bottom: float
    stop_loss: float
    take_profit: float
    swing_level: float
    bar_index: int


def implement_rectangle_strategy(
    df: pd.DataFrame,
    *,
    swing_window: int = 5,
    rr_ratio: float = 3.0,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Rectangle scalping state machine on OHLCV bars.

    Returns annotated dataframe and trailing setup state dict.
    """
    work = normalize_ohlcv(df)
    if work.empty:
        return work, {}

    work = work.copy()
    work["signal"] = 0
    work["stop_loss"] = np.nan
    work["take_profit"] = np.nan
    work["rect_top"] = np.nan
    work["rect_bottom"] = np.nan
    work["setup_phase"] = PHASE_NONE

    half_window = max(1, swing_window // 2)
    work["swing_high"] = np.nan
    work["swing_low"] = np.nan

    highs = work["high"].values
    lows = work["low"].values
    n = len(work)

    for i in range(half_window, n - half_window):
        w_hi = highs[i - half_window : i + half_window + 1].max()
        w_lo = lows[i - half_window : i + half_window + 1].min()
        if highs[i] == w_hi:
            work.iloc[i, work.columns.get_loc("swing_high")] = highs[i]
        if lows[i] == w_lo:
            work.iloc[i, work.columns.get_loc("swing_low")] = lows[i]

    work["recent_swing_high"] = work["swing_high"].ffill()
    work["recent_swing_low"] = work["swing_low"].ffill()

    work["bearish_fvg_top"] = np.nan
    work["bearish_fvg_bottom"] = np.nan
    work["bullish_fvg_top"] = np.nan
    work["bullish_fvg_bottom"] = np.nan

    opens = work["open"].values
    closes = work["close"].values

    for i in range(2, n):
        if lows[i - 2] > highs[i] and closes[i - 1] < opens[i - 1]:
            work.iloc[i, work.columns.get_loc("bearish_fvg_top")] = lows[i - 2]
            work.iloc[i, work.columns.get_loc("bearish_fvg_bottom")] = highs[i]
        if highs[i - 2] < lows[i] and closes[i - 1] > opens[i - 1]:
            work.iloc[i, work.columns.get_loc("bullish_fvg_top")] = highs[i - 2]
            work.iloc[i, work.columns.get_loc("bullish_fvg_bottom")] = lows[i]

    work["active_bear_fvg_top"] = work["bearish_fvg_top"].ffill()
    work["active_bear_fvg_bottom"] = work["bearish_fvg_bottom"].ffill()
    work["active_bull_fvg_top"] = work["bullish_fvg_top"].ffill()
    work["active_bull_fvg_bottom"] = work["bullish_fvg_bottom"].ffill()

    short_setup_active = False
    rect_short_top = np.nan
    rect_short_bottom = np.nan

    long_setup_active = False
    rect_long_top = np.nan
    rect_long_bottom = np.nan

    setups: list[RectangleSetup] = []

    for i in range(1, n):
        current_idx = work.index[i]

        if not short_setup_active:
            prev_sh = work["recent_swing_high"].iloc[i - 1]
            fvg_bot = work["active_bear_fvg_bottom"].iloc[i - 1]
            if (
                not np.isnan(prev_sh)
                and highs[i] > prev_sh
                and closes[i] < prev_sh
                and not np.isnan(fvg_bot)
                and highs[i] >= fvg_bot
            ):
                short_setup_active = True
                rect_short_top = float(highs[i])
                rect_short_bottom = float(max(opens[i], closes[i]))
                work.at[current_idx, "setup_phase"] = PHASE_RECT_SHORT
                work.at[current_idx, "rect_top"] = rect_short_top
                work.at[current_idx, "rect_bottom"] = rect_short_bottom
        else:
            work.at[current_idx, "setup_phase"] = PHASE_RECT_SHORT
            work.at[current_idx, "rect_top"] = rect_short_top
            work.at[current_idx, "rect_bottom"] = rect_short_bottom
            if closes[i] < rect_short_bottom:
                sl = rect_short_top
                risk = sl - closes[i]
                tp = closes[i] - rr_ratio * risk
                work.at[current_idx, "signal"] = SIGNAL_SELL
                work.at[current_idx, "stop_loss"] = sl
                work.at[current_idx, "take_profit"] = tp
                work.at[current_idx, "setup_phase"] = PHASE_ENTRY
                setups.append(RectangleSetup(
                    direction="SHORT",
                    phase=PHASE_ENTRY,
                    rect_top=rect_short_top,
                    rect_bottom=rect_short_bottom,
                    stop_loss=sl,
                    take_profit=tp,
                    swing_level=float(work["recent_swing_high"].iloc[i - 1]),
                    bar_index=i,
                ))
                short_setup_active = False
            elif highs[i] > rect_short_top:
                short_setup_active = False

        if not long_setup_active:
            prev_sl = work["recent_swing_low"].iloc[i - 1]
            fvg_top = work["active_bull_fvg_top"].iloc[i - 1]
            if (
                not np.isnan(prev_sl)
                and lows[i] < prev_sl
                and closes[i] > prev_sl
                and not np.isnan(fvg_top)
                and lows[i] <= fvg_top
            ):
                long_setup_active = True
                rect_long_bottom = float(lows[i])
                rect_long_top = float(min(opens[i], closes[i]))
                if work.at[current_idx, "setup_phase"] == PHASE_NONE:
                    work.at[current_idx, "setup_phase"] = PHASE_RECT_LONG
                work.at[current_idx, "rect_top"] = rect_long_top
                work.at[current_idx, "rect_bottom"] = rect_long_bottom
        else:
            if work.at[current_idx, "setup_phase"] != PHASE_ENTRY:
                work.at[current_idx, "setup_phase"] = PHASE_RECT_LONG
            work.at[current_idx, "rect_top"] = rect_long_top
            work.at[current_idx, "rect_bottom"] = rect_long_bottom
            if closes[i] > rect_long_top:
                sl = rect_long_bottom
                risk = closes[i] - sl
                tp = closes[i] + rr_ratio * risk
                work.at[current_idx, "signal"] = SIGNAL_BUY
                work.at[current_idx, "stop_loss"] = sl
                work.at[current_idx, "take_profit"] = tp
                work.at[current_idx, "setup_phase"] = PHASE_ENTRY
                setups.append(RectangleSetup(
                    direction="LONG",
                    phase=PHASE_ENTRY,
                    rect_top=rect_long_top,
                    rect_bottom=rect_long_bottom,
                    stop_loss=sl,
                    take_profit=tp,
                    swing_level=float(work["recent_swing_low"].iloc[i - 1]),
                    bar_index=i,
                ))
                long_setup_active = False
            elif lows[i] < rect_long_bottom:
                long_setup_active = False

    state = {
        "long_active": long_setup_active,
        "short_active": short_setup_active,
        "rect_long_top": rect_long_top,
        "rect_long_bottom": rect_long_bottom,
        "rect_short_top": rect_short_top,
        "rect_short_bottom": rect_short_bottom,
        "setups": setups,
    }
    return work, state


def _active_setup(work: pd.DataFrame, state: dict[str, Any]) -> RectangleSetup | None:
    if work.empty:
        return None
    setups: list[RectangleSetup] = state.get("setups") or []
    if int(work["signal"].iloc[-1]) != 0:
        for s in reversed(setups):
            if s.phase == PHASE_ENTRY:
                return s
    phase = str(work["setup_phase"].iloc[-1])
    if phase == PHASE_RECT_LONG and state.get("long_active"):
        return RectangleSetup(
            direction="LONG",
            phase=PHASE_RECT_LONG,
            rect_top=float(state.get("rect_long_top") or work["rect_top"].iloc[-1]),
            rect_bottom=float(state.get("rect_long_bottom") or work["rect_bottom"].iloc[-1]),
            stop_loss=float(state.get("rect_long_bottom") or 0),
            take_profit=0.0,
            swing_level=float(work["recent_swing_low"].iloc[-1]) if pd.notna(work["recent_swing_low"].iloc[-1]) else 0.0,
            bar_index=len(work) - 1,
        )
    if phase == PHASE_RECT_SHORT and state.get("short_active"):
        return RectangleSetup(
            direction="SHORT",
            phase=PHASE_RECT_SHORT,
            rect_top=float(state.get("rect_short_top") or work["rect_top"].iloc[-1]),
            rect_bottom=float(state.get("rect_short_bottom") or work["rect_bottom"].iloc[-1]),
            stop_loss=float(state.get("rect_short_top") or 0),
            take_profit=0.0,
            swing_level=float(work["recent_swing_high"].iloc[-1]) if pd.notna(work["recent_swing_high"].iloc[-1]) else 0.0,
            bar_index=len(work) - 1,
        )
    return None


def _signal_history(work: pd.DataFrame, limit: int = 8) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i in range(len(work) - 1, -1, -1):
        sig = int(work["signal"].iloc[i]) if not pd.isna(work["signal"].iloc[i]) else 0
        if sig == 0:
            continue
        ts = work.index[i]
        rows.append({
            "time": ts.strftime("%Y-%m-%d %H:%M") if hasattr(ts, "strftime") else str(ts),
            "signal": "BUY" if sig == SIGNAL_BUY else "SELL",
            "close": round(float(work["close"].iloc[i]), 4),
            "rect_top": round(float(work["rect_top"].iloc[i]), 4) if pd.notna(work["rect_top"].iloc[i]) else None,
            "rect_bottom": round(float(work["rect_bottom"].iloc[i]), 4) if pd.notna(work["rect_bottom"].iloc[i]) else None,
        })
        if len(rows) >= limit:
            break
    return rows


def evaluate_live_signal(
    work: pd.DataFrame,
    state: dict[str, Any],
    cfg: RectangleConfig,
    *,
    reference_price: float | None = None,
) -> dict[str, Any]:
    if work.empty:
        return {"signal": "NO_DATA"}

    price = reference_price or float(work["close"].iloc[-1])
    latest_sig = int(work["signal"].iloc[-1]) if not pd.isna(work["signal"].iloc[-1]) else 0
    phase = str(work["setup_phase"].iloc[-1])
    active = _active_setup(work, state)

    has_bear_fvg = work["active_bear_fvg_bottom"].iloc[-10:].notna().any() if len(work) >= 10 else False
    has_bull_fvg = work["active_bull_fvg_top"].iloc[-10:].notna().any() if len(work) >= 10 else False

    reasons: list[str] = []
    conf = 22.0
    direction = "WAIT"
    verdict = "WAIT"
    take = False
    stop = price
    target = price
    rect_top = rect_bottom = None

    if has_bull_fvg or has_bear_fvg:
        conf += 14
        reasons.append("Fair Value Gap (imbalance) present in recent structure")

    if active:
        direction = active.direction
        rect_top = active.rect_top
        rect_bottom = active.rect_bottom
        if active.phase == PHASE_ENTRY or latest_sig != 0:
            phase = PHASE_ENTRY
            verdict = f"TAKE {direction}"
            conf += 38
            reasons.append("Sniper entry — candle closed through rectangle boundary")
            stop = float(work["stop_loss"].iloc[-1]) if pd.notna(work["stop_loss"].iloc[-1]) else active.stop_loss
            target = float(work["take_profit"].iloc[-1]) if pd.notna(work["take_profit"].iloc[-1]) else active.take_profit
            reasons.append(f"SL beyond rectangle wick · TP at {cfg.rr_ratio}:1 R:R minimum")
        else:
            verdict = f"WATCH {direction}"
            conf += 24
            reasons.append("Rectangle armed — liquidity sweep + rejection wick detected")
            reasons.append("Await 1m close breakout through rectangle body edge")
            if direction == "LONG":
                stop = active.rect_bottom
                risk = max(price - stop, price * 0.003)
                target = price + risk * cfg.rr_ratio
            else:
                stop = active.rect_top
                risk = max(stop - price, price * 0.003)
                target = price - risk * cfg.rr_ratio

    if direction == "LONG" and has_bull_fvg:
        conf += 8
        reasons.append("Bullish FVG aligns with long rectangle thesis")
    elif direction == "SHORT" and has_bear_fvg:
        conf += 8
        reasons.append("Bearish FVG aligns with short rectangle thesis")

    conf = max(18.0, min(92.0, conf))
    take = phase == PHASE_ENTRY and conf >= cfg.take_confidence_threshold

    if stop and price:
        if direction == "LONG":
            sl_pct = max(0.25, (price - stop) / price * 100) if stop < price else 0.8
            tp_pct = max(0.5, (target - price) / price * 100) if target > price else sl_pct * cfg.rr_ratio
        elif direction == "SHORT":
            sl_pct = max(0.25, (stop - price) / price * 100) if stop > price else 0.8
            tp_pct = max(0.5, (price - target) / price * 100) if target < price else sl_pct * cfg.rr_ratio
        else:
            sl_pct = 0.8
            tp_pct = sl_pct * cfg.rr_ratio
    else:
        sl_pct = 0.8
        tp_pct = sl_pct * cfg.rr_ratio

    hold = "1–15 minutes (1m scalp · exit on SL/TP or session end)"
    plan = make_trade_plan(
        direction=direction if take and direction in ("LONG", "SHORT") else "—",
        timeframe=cfg.execution_tf,
        stop_loss_pct=round(sl_pct, 2),
        take_profit_pct=round(tp_pct, 2),
        confidence_pct=round(conf, 1),
        style="intraday",
        exit_rule="Exit if price invalidates rectangle wick extreme before/after entry.",
        max_hold_exit="Scalp time stop — close within 15 minutes if target not hit.",
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
        "rect_top": rect_top,
        "rect_bottom": rect_bottom,
        "execution_tf": cfg.execution_tf,
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": hold},
    }, hold_duration=hold)


def fetch_exec_data(
    ticker: str,
    market: str,
    cfg: RectangleConfig,
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
    return df


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: RectangleConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or RectangleConfig()
    raw = fetch_exec_data(ticker, market, cfg, groww_token=groww_token, exchange=exchange)
    if raw.empty or len(raw) < cfg.min_bars:
        return {"ticker": ticker, "error": f"Insufficient {cfg.execution_tf} data."}

    work, state = implement_rectangle_strategy(
        raw, swing_window=cfg.swing_window, rr_ratio=cfg.rr_ratio,
    )
    live = evaluate_live_signal(work, state, cfg)
    entries = [s for s in (state.get("setups") or []) if s.phase == PHASE_ENTRY]

    return {
        "ticker": ticker,
        "market": market,
        "execution_tf": cfg.execution_tf,
        "bars": len(work),
        "last_close": float(work["close"].iloc[-1]),
        "entry_signals": len(entries),
        "rectangle_active": bool(state.get("long_active") or state.get("short_active")),
        "signal_history": _signal_history(work),
        "live": live,
    }


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: RectangleConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or RectangleConfig()
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
        and (r.get("live") or {}).get("phase") in (PHASE_RECT_LONG, PHASE_RECT_SHORT)
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
