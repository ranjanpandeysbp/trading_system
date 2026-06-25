"""
smc_cisd_engine.py
------------------
SMC CISD (Change in State of Delivery) entry model.

Compression → liquidity sweep → displacement → close through CISD level (no early entry).
Multi-timeframe: higher TF bias + lower TF execution.
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
from app.trading_hubs.smart_money_shared import enrich_smc_live, hold_for_tf

logger = logging.getLogger(__name__)

YOUTUBE_SMC_CISD_URL = "http://www.youtube.com/watch?v=srSf8Zg-F6U"

TF_OPTIONS = ["5m", "15m", "30m", "1h", "4h", "1d"]

STATE_LOOKING = "LOOKING_FOR_SWEEP"
STATE_AWAITING = "AWAITING_CISD_BREAK"
STATE_ENTERED = "ENTRY_CONFIRMED"

PHASE_ENTRY = "CISD_ENTRY"
PHASE_AWAIT = "AWAIT_CISD"
PHASE_SWEEP = "SWEEP_DETECTED"
PHASE_NONE = "NO_SETUP"


@dataclass
class CISDConfig:
    execution_tf: str = "15m"
    bias_tf: str = "1h"
    use_mtf: bool = True
    compression_window: int = 10
    compression_ratio: float = 0.8
    compression_lookback: int = 50
    rr_ratio: float = 2.0
    take_confidence_threshold: float = 62.0
    min_bars: int = 80


@dataclass
class CISDSetup:
    direction: str
    state: str
    sweep_extreme: float
    cisd_level: float
    compression_high: float
    compression_low: float
    sweep_index: int
    cisd_index: int


def _add_compression_cols(df: pd.DataFrame, cfg: CISDConfig) -> pd.DataFrame:
    work = df.copy()
    w = cfg.compression_window
    work["rolling_high"] = work["high"].shift(1).rolling(w).max()
    work["rolling_low"] = work["low"].shift(1).rolling(w).min()
    work["range_size"] = work["rolling_high"] - work["rolling_low"]
    avg = work["range_size"].rolling(cfg.compression_lookback).mean()
    work["is_compressed"] = work["range_size"] < avg * cfg.compression_ratio
    return work


def implement_cisd_strategy(df: pd.DataFrame, cfg: CISDConfig) -> tuple[pd.DataFrame, list[CISDSetup]]:
    """Run CISD state machine; returns annotated frame and completed/active setups."""
    work = _add_compression_cols(normalize_ohlcv(df), cfg)
    if work.empty:
        return work, []

    work["signal"] = 0
    work["cisd_level"] = np.nan
    work["setup_state"] = STATE_LOOKING

    setups: list[CISDSetup] = []
    state = STATE_LOOKING
    direction = ""
    sweep_extreme = 0.0
    cisd_level = 0.0
    sweep_idx = -1
    comp_high = comp_low = 0.0

    w = cfg.compression_window
    for i in range(w, len(work)):
        row = work.iloc[i]
        rh = row["rolling_high"]
        rl = row["rolling_low"]
        if pd.isna(rh) or pd.isna(rl):
            continue

        if state == STATE_LOOKING:
            if not work.iloc[i - 1]["is_compressed"]:
                continue
            comp_high, comp_low = float(rh), float(rl)

            # Bullish sweep of lows
            if row["low"] < rl and row["close"] > rl:
                direction = "LONG"
                sweep_extreme = float(row["low"])
                cisd_level = max(float(row["open"]), float(row["close"]))
                sweep_idx = i
                state = STATE_AWAITING
                work.at[work.index[i], "setup_state"] = STATE_AWAITING
                work.at[work.index[i], "cisd_level"] = cisd_level
                setups.append(CISDSetup(
                    direction=direction, state=PHASE_SWEEP, sweep_extreme=sweep_extreme,
                    cisd_level=cisd_level, compression_high=comp_high, compression_low=comp_low,
                    sweep_index=i, cisd_index=i,
                ))
            # Bearish sweep of highs
            elif row["high"] > rh and row["close"] < rh:
                direction = "SHORT"
                sweep_extreme = float(row["high"])
                cisd_level = min(float(row["open"]), float(row["close"]))
                sweep_idx = i
                state = STATE_AWAITING
                work.at[work.index[i], "setup_state"] = STATE_AWAITING
                work.at[work.index[i], "cisd_level"] = cisd_level
                setups.append(CISDSetup(
                    direction=direction, state=PHASE_SWEEP, sweep_extreme=sweep_extreme,
                    cisd_level=cisd_level, compression_high=comp_high, compression_low=comp_low,
                    sweep_index=i, cisd_index=i,
                ))

        elif state == STATE_AWAITING:
            work.at[work.index[i], "setup_state"] = STATE_AWAITING
            work.at[work.index[i], "cisd_level"] = cisd_level

            if direction == "LONG":
                if row["close"] < sweep_extreme:
                    state = STATE_LOOKING
                    continue
                if row["close"] > cisd_level:
                    work.at[work.index[i], "signal"] = 1
                    work.at[work.index[i], "setup_state"] = STATE_ENTERED
                    setups.append(CISDSetup(
                        direction="LONG", state=STATE_ENTERED, sweep_extreme=sweep_extreme,
                        cisd_level=cisd_level, compression_high=comp_high, compression_low=comp_low,
                        sweep_index=sweep_idx, cisd_index=i,
                    ))
                    state = STATE_LOOKING
            elif direction == "SHORT":
                if row["close"] > sweep_extreme:
                    state = STATE_LOOKING
                    continue
                if row["close"] < cisd_level:
                    work.at[work.index[i], "signal"] = -1
                    work.at[work.index[i], "setup_state"] = STATE_ENTERED
                    setups.append(CISDSetup(
                        direction="SHORT", state=STATE_ENTERED, sweep_extreme=sweep_extreme,
                        cisd_level=cisd_level, compression_high=comp_high, compression_low=comp_low,
                        sweep_index=sweep_idx, cisd_index=i,
                    ))
                    state = STATE_LOOKING

    return work, setups


def _htf_bias_summary(df_htf: pd.DataFrame, cfg: CISDConfig) -> dict[str, Any]:
    """Light HTF filter: recent compression + last sweep direction hint."""
    work, setups = implement_cisd_strategy(df_htf, cfg)
    if work.empty:
        return {"bias": "NEUTRAL", "compressed": False}
    compressed = bool(work["is_compressed"].iloc[-5:].any()) if len(work) >= 5 else False
    last_dir = "NEUTRAL"
    for s in reversed(setups):
        if s.state == STATE_ENTERED:
            last_dir = s.direction
            break
        if s.state == PHASE_SWEEP:
            last_dir = s.direction
            break
    return {"bias": last_dir, "compressed": compressed, "setups": len(setups)}


def _active_setup(work: pd.DataFrame, setups: list[CISDSetup]) -> CISDSetup | None:
    if work.empty or not setups:
        return None
    last_state = str(work["setup_state"].iloc[-1])
    latest_sig = int(work["signal"].iloc[-1]) if work["signal"].iloc[-1] != 0 else 0
    if latest_sig != 0:
        for s in reversed(setups):
            if s.state == STATE_ENTERED:
                return s
    if last_state == STATE_AWAITING:
        for s in reversed(setups):
            if s.state == PHASE_SWEEP:
                return s
    return None


def evaluate_live_signal(
    work: pd.DataFrame,
    setups: list[CISDSetup],
    cfg: CISDConfig,
    *,
    htf: dict[str, Any] | None = None,
    reference_price: float | None = None,
) -> dict[str, Any]:
    if work.empty:
        return {"signal": "NO_DATA"}

    price = reference_price or float(work["close"].iloc[-1])
    active = _active_setup(work, setups)
    latest_sig = int(work["signal"].iloc[-1]) if not pd.isna(work["signal"].iloc[-1]) else 0
    last_state = str(work["setup_state"].iloc[-1])
    cisd_lvl = work["cisd_level"].iloc[-1]
    cisd_lvl = float(cisd_lvl) if pd.notna(cisd_lvl) else None

    reasons: list[str] = []
    conf = 25.0
    direction = "WAIT"
    phase = PHASE_NONE
    verdict = "WAIT"
    take = False
    stop = price
    sweep_ext = None

    if work["is_compressed"].iloc[-1]:
        conf += 12
        reasons.append("Compression zone active (tight range)")

    if active:
        direction = active.direction
        sweep_ext = active.sweep_extreme
        cisd_lvl = active.cisd_level
        if active.state == STATE_ENTERED or latest_sig != 0:
            phase = PHASE_ENTRY
            verdict = f"TAKE {direction}"
            conf += 35
            reasons.append("CISD break confirmed — close through institutional block level")
        elif active.state == PHASE_SWEEP or last_state == STATE_AWAITING:
            phase = PHASE_AWAIT
            verdict = f"WATCH {direction}"
            conf += 22
            reasons.append("Sweep + displacement detected — await CISD close break (golden rule)")
            reasons.append("Do NOT enter early at sweep extreme")

    if htf and cfg.use_mtf:
        hb = htf.get("bias", "NEUTRAL")
        if hb == direction:
            conf += 15
            reasons.append(f"HTF ({cfg.bias_tf}) bias aligns: {hb}")
        elif hb != "NEUTRAL" and direction != "WAIT" and hb != direction:
            conf -= 12
            reasons.append(f"HTF bias {hb} conflicts with LTF setup {direction}")

    conf = max(18.0, min(92.0, conf))
    take = phase == PHASE_ENTRY and conf >= cfg.take_confidence_threshold

    if direction == "LONG" and sweep_ext is not None:
        stop = float(sweep_ext) * 0.999
        sl_pct = max(0.4, (price - stop) / price * 100) if stop < price else 1.2
        tp_pct = sl_pct * cfg.rr_ratio
        target = price * (1 + tp_pct / 100)
    elif direction == "SHORT" and sweep_ext is not None:
        stop = float(sweep_ext) * 1.001
        sl_pct = max(0.4, (stop - price) / price * 100) if stop > price else 1.2
        tp_pct = sl_pct * cfg.rr_ratio
        target = price * (1 - tp_pct / 100)
    else:
        sl_pct = 1.5
        tp_pct = sl_pct * cfg.rr_ratio
        target = price

    hold = hold_for_tf(cfg.execution_tf, "swing" if cfg.execution_tf in ("4h", "1d") else "intraday")
    plan_dir = direction if take and direction in ("LONG", "SHORT") else "—"
    plan = make_trade_plan(
        direction=plan_dir,
        timeframe=cfg.execution_tf,
        stop_loss_pct=round(sl_pct, 2),
        take_profit_pct=round(tp_pct, 2),
        confidence_pct=round(conf, 1),
        style="intraday" if cfg.execution_tf in ("5m", "15m", "30m") else "swing",
        exit_rule="Exit if close invalidates sweep extreme or CISD thesis breaks.",
        max_hold_exit=f"Time stop: {hold.split('(')[0].strip()}.",
    )

    return enrich_smc_live({
        "signal": "BUY" if latest_sig == 1 else ("SELL" if latest_sig == -1 else "NONE"),
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
        "cisd_level": cisd_lvl,
        "sweep_extreme": sweep_ext,
        "execution_tf": cfg.execution_tf,
        "bias_tf": cfg.bias_tf if cfg.use_mtf else None,
        "htf_bias": (htf or {}).get("bias"),
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": hold},
    }, hold_duration=hold)


def fetch_tf_data(
    ticker: str,
    tf: str,
    market: str,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
    limit: int = 400,
) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    df = fetch_data_for_gap_scan(ticker, tf, market, groww_token, exchange, limit=limit)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < 30:
        df = normalize_ohlcv(fetch_ohlcv_yfinance(ticker, tf, is_crypto=is_crypto, limit=limit, market=market))
    return df


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: CISDConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or CISDConfig()
    ltf = fetch_tf_data(ticker, cfg.execution_tf, market, groww_token=groww_token, exchange=exchange)
    if ltf.empty or len(ltf) < cfg.min_bars:
        return {"ticker": ticker, "error": f"Insufficient {cfg.execution_tf} data."}

    work, setups = implement_cisd_strategy(ltf, cfg)
    htf = None
    if cfg.use_mtf and cfg.bias_tf != cfg.execution_tf:
        htf_df = fetch_tf_data(ticker, cfg.bias_tf, market, groww_token=groww_token, exchange=exchange, limit=300)
        if not htf_df.empty:
            htf = _htf_bias_summary(htf_df, cfg)

    live = evaluate_live_signal(work, setups, cfg, htf=htf)
    entries = [s for s in setups if s.state == STATE_ENTERED]

    return {
        "ticker": ticker,
        "market": market,
        "execution_tf": cfg.execution_tf,
        "bias_tf": cfg.bias_tf if cfg.use_mtf else None,
        "bars": len(work),
        "last_close": float(work["close"].iloc[-1]),
        "setup_count": len(setups),
        "entry_signals": len(entries),
        "htf": htf,
        "live": live,
    }


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: CISDConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or CISDConfig()
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
        and (r.get("live") or {}).get("phase") in (PHASE_AWAIT, PHASE_SWEEP)
    ]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))
    watches.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market,
        "execution_tf": cfg.execution_tf,
        "bias_tf": cfg.bias_tf,
        "results": results,
        "entries": entries,
        "watchlist": watches,
        "entry_count": len(entries),
        "watch_count": len(watches),
    }
