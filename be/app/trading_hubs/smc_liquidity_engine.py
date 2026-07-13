"""
smc_liquidity_engine.py
-----------------------
SMC Liquidity — structural sweeps/grabs, liquidity runs, and FVG rebalance.

Based on "MASTER Liquidity Concepts" order-flow framework:
BSL/SSL pools, sweep vs grab vs run, and fair value gap mitigation.
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

YOUTUBE_SMC_LIQUIDITY_URL = "https://www.youtube.com/watch?v=lSRoNosc4zw"

TF_OPTIONS = ["5m", "15m", "30m", "1h", "4h", "1d"]
STRATEGY_MODES = ("Sweep / Grab", "FVG Rebalance", "Both")

PHASE_ENTRY = "LIQUIDITY_ENTRY"
PHASE_AWAIT = "AWAIT_FVG"
PHASE_SWEEP = "SWEEP_DETECTED"
PHASE_RUN = "LIQUIDITY_RUN"
PHASE_NONE = "NO_SETUP"


@dataclass
class LiquidityConfig:
    execution_tf: str = "15m"
    bias_tf: str = "1h"
    use_mtf: bool = True
    strategy_mode: str = "Both"
    swing_window: int = 5
    structural_window: int = 15
    atr_threshold_mult: float = 1.5
    wick_ratio_grab: float = 0.55
    rr_ratio: float = 2.0
    take_confidence_threshold: float = 62.0
    min_bars: int = 80


@dataclass
class LiquidityEvent:
    event_type: str  # SWEEP, GRAB, RUN, FVG_BULL, FVG_BEAR
    direction: str  # LONG / SHORT
    bar_index: int
    bsl: float | None = None
    ssl: float | None = None
    sweep_extreme: float | None = None
    fvg_top: float | None = None
    fvg_bottom: float | None = None


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = df["high"] - df["low"]
    high_cp = (df["high"] - df["close"].shift(1)).abs()
    low_cp = (df["low"] - df["close"].shift(1)).abs()
    tr = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _identify_swings(work: pd.DataFrame, window: int) -> pd.DataFrame:
    span = window * 2 + 1
    roll_h = work["high"].rolling(span, center=True).max()
    roll_l = work["low"].rolling(span, center=True).min()
    work["is_swing_high"] = (work["high"] == roll_h) & roll_h.notna()
    work["is_swing_low"] = (work["low"] == roll_l) & roll_l.notna()
    return work


def _wick_ratio(row: pd.Series) -> float:
    rng = float(row["high"] - row["low"])
    if rng <= 0:
        return 0.0
    body_top = max(float(row["open"]), float(row["close"]))
    body_bot = min(float(row["open"]), float(row["close"]))
    upper = float(row["high"]) - body_top
    lower = body_bot - float(row["low"])
    return max(upper, lower) / rng


def generate_sweep_signals(work: pd.DataFrame, cfg: LiquidityConfig) -> tuple[pd.DataFrame, list[LiquidityEvent]]:
    """Strategy 1 — liquidity sweeps and grabs at structural BSL/SSL."""
    work = _identify_swings(work.copy(), cfg.structural_window)
    work["signal_sweep"] = 0
    work["event_type"] = ""
    work["bsl_level"] = work["high"].where(work["is_swing_high"]).ffill().shift(1)
    work["ssl_level"] = work["low"].where(work["is_swing_low"]).ffill().shift(1)

    events: list[LiquidityEvent] = []
    prev_bsl = work["bsl_level"]
    prev_ssl = work["ssl_level"]

    bearish = (work["high"] > prev_bsl) & (work["close"] < prev_bsl) & prev_bsl.notna()
    bullish = (work["low"] < prev_ssl) & (work["close"] > prev_ssl) & prev_ssl.notna()

    for i in work.index[bullish]:
        pos = work.index.get_loc(i)
        row = work.loc[i]
        wick = _wick_ratio(row)
        evt = "GRAB" if wick >= cfg.wick_ratio_grab else "SWEEP"
        work.at[i, "signal_sweep"] = 1
        work.at[i, "event_type"] = evt
        events.append(LiquidityEvent(
            event_type=evt,
            direction="LONG",
            bar_index=int(pos),
            bsl=float(prev_bsl.loc[i]) if pd.notna(prev_bsl.loc[i]) else None,
            ssl=float(prev_ssl.loc[i]) if pd.notna(prev_ssl.loc[i]) else None,
            sweep_extreme=float(row["low"]),
        ))

    for i in work.index[bearish]:
        pos = work.index.get_loc(i)
        row = work.loc[i]
        wick = _wick_ratio(row)
        evt = "GRAB" if wick >= cfg.wick_ratio_grab else "SWEEP"
        work.at[i, "signal_sweep"] = -1
        work.at[i, "event_type"] = evt
        events.append(LiquidityEvent(
            event_type=evt,
            direction="SHORT",
            bar_index=int(pos),
            bsl=float(prev_bsl.loc[i]) if pd.notna(prev_bsl.loc[i]) else None,
            ssl=float(prev_ssl.loc[i]) if pd.notna(prev_ssl.loc[i]) else None,
            sweep_extreme=float(row["high"]),
        ))

    # Liquidity run — expansion candle closes beyond structure (continuation)
    body = (work["close"] - work["open"]).abs()
    prev_body = body.shift(1)
    expansion = body >= (2.0 * prev_body)
    bull_run = (work["close"] > prev_bsl) & (work["high"] > prev_bsl) & expansion & (work["close"] > work["open"])
    bear_run = (work["close"] < prev_ssl) & (work["low"] < prev_ssl) & expansion & (work["close"] < work["open"])
    work["signal_run"] = 0
    work.loc[bull_run, "signal_run"] = 1
    work.loc[bear_run, "signal_run"] = -1

    for i in work.index[bull_run]:
        pos = work.index.get_loc(i)
        events.append(LiquidityEvent(
            event_type="RUN",
            direction="LONG",
            bar_index=int(pos),
            bsl=float(prev_bsl.loc[i]) if pd.notna(prev_bsl.loc[i]) else None,
            ssl=float(prev_ssl.loc[i]) if pd.notna(prev_ssl.loc[i]) else None,
        ))
    for i in work.index[bear_run]:
        pos = work.index.get_loc(i)
        events.append(LiquidityEvent(
            event_type="RUN",
            direction="SHORT",
            bar_index=int(pos),
            bsl=float(prev_bsl.loc[i]) if pd.notna(prev_bsl.loc[i]) else None,
            ssl=float(prev_ssl.loc[i]) if pd.notna(prev_ssl.loc[i]) else None,
        ))

    return work, events


def generate_fvg_signals(work: pd.DataFrame, cfg: LiquidityConfig) -> tuple[pd.DataFrame, list[LiquidityEvent]]:
    """Strategy 2 — fair value gap creation and rebalance entries."""
    df = work.copy()
    df["signal_fvg"] = 0
    atr = _atr(df)
    events: list[LiquidityEvent] = []
    bullish_fvgs: list[dict[str, Any]] = []
    bearish_fvgs: list[dict[str, Any]] = []

    for pos in range(2, len(df)):
        i = df.index[pos]
        mid_body = abs(float(df["close"].iloc[pos - 1]) - float(df["open"].iloc[pos - 1]))
        atr_val = float(atr.iloc[pos - 1]) if pd.notna(atr.iloc[pos - 1]) else 0.0
        momentum_ok = atr_val <= 0 or mid_body > atr_val * cfg.atr_threshold_mult

        if float(df["low"].iloc[pos]) > float(df["high"].iloc[pos - 2]) and momentum_ok:
            bullish_fvgs.append({
                "top": float(df["low"].iloc[pos]),
                "bottom": float(df["high"].iloc[pos - 2]),
                "filled": False,
            })
        elif float(df["high"].iloc[pos]) < float(df["low"].iloc[pos - 2]) and momentum_ok:
            bearish_fvgs.append({
                "top": float(df["low"].iloc[pos - 2]),
                "bottom": float(df["high"].iloc[pos]),
                "filled": False,
            })

        cur_low = float(df["low"].iloc[pos])
        cur_high = float(df["high"].iloc[pos])
        cur_close = float(df["close"].iloc[pos])

        for fvg in bullish_fvgs:
            if fvg["filled"]:
                continue
            if cur_low <= fvg["top"] and cur_close > fvg["bottom"]:
                df.at[i, "signal_fvg"] = 1
                fvg["filled"] = True
                events.append(LiquidityEvent(
                    event_type="FVG_BULL",
                    direction="LONG",
                    bar_index=pos,
                    fvg_top=fvg["top"],
                    fvg_bottom=fvg["bottom"],
                ))

        for fvg in bearish_fvgs:
            if fvg["filled"]:
                continue
            if cur_high >= fvg["bottom"] and cur_close < fvg["top"]:
                df.at[i, "signal_fvg"] = -1
                fvg["filled"] = True
                events.append(LiquidityEvent(
                    event_type="FVG_BEAR",
                    direction="SHORT",
                    bar_index=pos,
                    fvg_top=fvg["top"],
                    fvg_bottom=fvg["bottom"],
                ))

    df["active_bull_fvg"] = len([f for f in bullish_fvgs if not f["filled"]])
    df["active_bear_fvg"] = len([f for f in bearish_fvgs if not f["filled"]])
    return df, events, bullish_fvgs, bearish_fvgs


def implement_liquidity_strategy(
    df: pd.DataFrame,
    cfg: LiquidityConfig,
) -> tuple[pd.DataFrame, list[LiquidityEvent], list[dict], list[dict]]:
    """Run selected liquidity models and merge signals."""
    work = normalize_ohlcv(df)
    if work.empty:
        return work, [], [], []

    all_events: list[LiquidityEvent] = []
    bull_fvgs: list[dict] = []
    bear_fvgs: list[dict] = []
    work["signal"] = 0
    work["signal_sweep"] = 0
    work["signal_fvg"] = 0
    work["signal_run"] = 0

    use_sweep = cfg.strategy_mode in ("Sweep / Grab", "Both")
    use_fvg = cfg.strategy_mode in ("FVG Rebalance", "Both")

    if use_sweep:
        work, sweep_events = generate_sweep_signals(work, cfg)
        all_events.extend(sweep_events)
        work["signal"] = work["signal_sweep"]

    if use_fvg:
        work, fvg_events, bull_fvgs, bear_fvgs = generate_fvg_signals(work, cfg)
        all_events.extend(fvg_events)
        if use_sweep:
            # Prefer sweep on same bar; otherwise add FVG
            mask = (work["signal_sweep"] == 0) & (work["signal_fvg"] != 0)
            work.loc[mask, "signal"] = work.loc[mask, "signal_fvg"]
        else:
            work["signal"] = work["signal_fvg"]

    return work, all_events, bull_fvgs, bear_fvgs


def _htf_liquidity_bias(df_htf: pd.DataFrame, cfg: LiquidityConfig) -> dict[str, Any]:
    work, events, _, _ = implement_liquidity_strategy(df_htf, cfg)
    if work.empty:
        return {"bias": "NEUTRAL", "recent_event": None}
    bias = "NEUTRAL"
    recent = None
    for ev in reversed(events):
        if ev.event_type in ("SWEEP", "GRAB", "FVG_BULL", "FVG_BEAR"):
            bias = ev.direction
            recent = ev.event_type
            break
        if ev.event_type == "RUN":
            bias = ev.direction
            recent = "RUN"
            break
    return {"bias": bias, "recent_event": recent, "events": len(events)}


def _latest_event(events: list[LiquidityEvent], work: pd.DataFrame) -> LiquidityEvent | None:
    if not events or work.empty:
        return None
    last_bar = len(work) - 1
    for ev in reversed(events):
        if ev.bar_index >= last_bar - 3:
            return ev
    return None


def _nearest_unfilled_fvg(
    price: float,
    bull_fvgs: list[dict],
    bear_fvgs: list[dict],
) -> tuple[str, dict | None]:
    best_dist = float("inf")
    best: tuple[str, dict | None] = ("", None)
    for fvg in bull_fvgs:
        if fvg.get("filled"):
            continue
        mid = (fvg["top"] + fvg["bottom"]) / 2
        dist = abs(price - mid)
        if dist < best_dist:
            best_dist = dist
            best = ("BULL_FVG", fvg)
    for fvg in bear_fvgs:
        if fvg.get("filled"):
            continue
        mid = (fvg["top"] + fvg["bottom"]) / 2
        dist = abs(price - mid)
        if dist < best_dist:
            best_dist = dist
            best = ("BEAR_FVG", fvg)
    return best


def evaluate_live_signal(
    work: pd.DataFrame,
    events: list[LiquidityEvent],
    cfg: LiquidityConfig,
    *,
    htf: dict[str, Any] | None = None,
    bull_fvgs: list[dict] | None = None,
    bear_fvgs: list[dict] | None = None,
    reference_price: float | None = None,
) -> dict[str, Any]:
    if work.empty:
        return {"signal": "NO_DATA"}

    price = reference_price or float(work["close"].iloc[-1])
    latest_sig = int(work["signal"].iloc[-1]) if work["signal"].iloc[-1] != 0 else 0
    run_sig = int(work["signal_run"].iloc[-1]) if "signal_run" in work.columns and work["signal_run"].iloc[-1] != 0 else 0
    active = _latest_event(events, work)
    bsl = float(work["bsl_level"].iloc[-1]) if "bsl_level" in work.columns and pd.notna(work["bsl_level"].iloc[-1]) else None
    ssl = float(work["ssl_level"].iloc[-1]) if "ssl_level" in work.columns and pd.notna(work["ssl_level"].iloc[-1]) else None

    reasons: list[str] = []
    conf = 28.0
    direction = "WAIT"
    phase = PHASE_NONE
    verdict = "WAIT"
    take = False
    stop = price
    sweep_ext = None
    liquidity_level = None
    event_type = None

    fvg_kind, fvg_zone = _nearest_unfilled_fvg(price, bull_fvgs or [], bear_fvgs or [])

    if active:
        direction = active.direction
        event_type = active.event_type
        sweep_ext = active.sweep_extreme
        liquidity_level = active.bsl or active.ssl
        if active.fvg_top is not None:
            liquidity_level = (active.fvg_top + (active.fvg_bottom or active.fvg_top)) / 2

        if active.event_type in ("SWEEP", "GRAB"):
            phase = PHASE_SWEEP if active.bar_index == len(work) - 1 else PHASE_ENTRY
            if latest_sig != 0:
                phase = PHASE_ENTRY
                verdict = f"TAKE {direction}"
                conf += 32
                label = "grab" if active.event_type == "GRAB" else "sweep"
                reasons.append(f"Bearish/Bullish liquidity {label} — wick through BSL/SSL, close back inside")
                reasons.append("Fade toward opposite structural pool (SSL ↔ BSL)")
            else:
                phase = PHASE_SWEEP
                verdict = f"WATCH {direction}"
                conf += 18
                reasons.append(f"Recent {active.event_type.lower()} at structural liquidity — monitor reversal")
        elif active.event_type in ("FVG_BULL", "FVG_BEAR"):
            phase = PHASE_ENTRY if latest_sig != 0 else PHASE_AWAIT
            if latest_sig != 0:
                verdict = f"TAKE {direction}"
                conf += 30
                reasons.append("FVG rebalance — price mitigated imbalance window with support/resistance hold")
            else:
                verdict = f"WATCH {direction}"
                conf += 16
                reasons.append("FVG zone active — await retest into gap with close confirmation")
        elif active.event_type == "RUN":
            phase = PHASE_RUN
            verdict = f"RUN {direction}"
            conf += 20
            reasons.append("Liquidity run — expansion candle closed beyond structure (continuation, not fade)")

    elif fvg_zone and fvg_kind:
        phase = PHASE_AWAIT
        direction = "LONG" if fvg_kind == "BULL_FVG" else "SHORT"
        verdict = f"WATCH {direction}"
        conf += 14
        liquidity_level = (fvg_zone["top"] + fvg_zone["bottom"]) / 2
        reasons.append(f"Open {fvg_kind.replace('_', ' ')} below/above price — limit retest entry zone")

    if run_sig != 0 and phase == PHASE_NONE:
        phase = PHASE_RUN
        direction = "LONG" if run_sig == 1 else "SHORT"
        verdict = f"RUN {direction}"
        conf += 18
        reasons.append("Fresh liquidity run on latest bar")

    if htf and cfg.use_mtf:
        hb = htf.get("bias", "NEUTRAL")
        if hb == direction:
            conf += 12
            reasons.append(f"HTF ({cfg.bias_tf}) liquidity bias aligns: {hb}")
        elif hb not in ("NEUTRAL", "WAIT") and direction not in ("WAIT", "NEUTRAL") and hb != direction:
            conf -= 10
            reasons.append(f"HTF bias {hb} conflicts with LTF {direction}")

    if bsl is not None and ssl is not None:
        if price > (bsl + ssl) / 2:
            reasons.append(f"Price above range mid — BSL {bsl:,.4g} / SSL {ssl:,.4g}")
        else:
            reasons.append(f"Price below range mid — BSL {bsl:,.4g} / SSL {ssl:,.4g}")

    conf = max(18.0, min(92.0, conf))
    take = phase == PHASE_ENTRY and conf >= cfg.take_confidence_threshold and event_type != "RUN"

    if direction == "LONG" and sweep_ext is not None:
        stop = float(sweep_ext) * 0.999
        sl_pct = max(0.4, (price - stop) / price * 100) if stop < price else 1.2
        tp_pct = sl_pct * cfg.rr_ratio
        if bsl and bsl > price:
            tp_pct = max(tp_pct, (bsl - price) / price * 100 * 0.85)
        target = price * (1 + tp_pct / 100)
    elif direction == "SHORT" and sweep_ext is not None:
        stop = float(sweep_ext) * 1.001
        sl_pct = max(0.4, (stop - price) / price * 100) if stop > price else 1.2
        tp_pct = sl_pct * cfg.rr_ratio
        if ssl and ssl < price:
            tp_pct = max(tp_pct, (price - ssl) / price * 100 * 0.85)
        target = price * (1 - tp_pct / 100)
    elif direction == "LONG" and fvg_zone:
        stop = fvg_zone["bottom"] * 0.999
        sl_pct = max(0.5, (price - stop) / price * 100)
        tp_pct = sl_pct * cfg.rr_ratio
        target = price * (1 + tp_pct / 100)
    elif direction == "SHORT" and fvg_zone:
        stop = fvg_zone["top"] * 1.001
        sl_pct = max(0.5, (stop - price) / price * 100)
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
        exit_rule="Exit if close invalidates sweep extreme or FVG mitigation thesis.",
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
        "liquidity_level": liquidity_level,
        "bsl_level": bsl,
        "ssl_level": ssl,
        "sweep_extreme": sweep_ext,
        "event_type": event_type,
        "strategy_mode": cfg.strategy_mode,
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
    cfg: LiquidityConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or LiquidityConfig()
    ltf = fetch_tf_data(ticker, cfg.execution_tf, market, groww_token=groww_token, exchange=exchange)
    if ltf.empty or len(ltf) < cfg.min_bars:
        return {"ticker": ticker, "error": f"Insufficient {cfg.execution_tf} data."}

    work, events, bull_fvgs, bear_fvgs = implement_liquidity_strategy(ltf, cfg)
    htf = None
    if cfg.use_mtf and cfg.bias_tf != cfg.execution_tf:
        htf_df = fetch_tf_data(ticker, cfg.bias_tf, market, groww_token=groww_token, exchange=exchange, limit=300)
        if not htf_df.empty:
            htf = _htf_liquidity_bias(htf_df, cfg)

    live = evaluate_live_signal(
        work, events, cfg, htf=htf, bull_fvgs=bull_fvgs, bear_fvgs=bear_fvgs,
    )
    entries = [e for e in events if e.event_type in ("SWEEP", "GRAB", "FVG_BULL", "FVG_BEAR")]

    return {
        "ticker": ticker,
        "market": market,
        "execution_tf": cfg.execution_tf,
        "bias_tf": cfg.bias_tf if cfg.use_mtf else None,
        "strategy_mode": cfg.strategy_mode,
        "bars": len(work),
        "last_close": float(work["close"].iloc[-1]),
        "event_count": len(events),
        "entry_signals": len(entries),
        "htf": htf,
        "live": live,
    }


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: LiquidityConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or LiquidityConfig()
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
        and (r.get("live") or {}).get("phase") in (PHASE_AWAIT, PHASE_SWEEP, PHASE_RUN)
    ]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))
    watches.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market,
        "execution_tf": cfg.execution_tf,
        "bias_tf": cfg.bias_tf,
        "strategy_mode": cfg.strategy_mode,
        "results": results,
        "entries": entries,
        "watchlist": watches,
        "entry_count": len(entries),
        "watch_count": len(watches),
    }
