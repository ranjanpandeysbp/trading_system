"""
intraday_mtf_breakout_retest_engine.py
----------------------------------------
Daniel Holmes — Multi-Timeframe Price Action Breakout & Retest.

Daily bias filter · 15m equal-body S/R · clean traffic · breakout close · retest entry.
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
from app.trading_hubs.session_constants import IST_TZ, NY_TZ

logger = logging.getLogger(__name__)

YOUTUBE_INTRA_MTF_BR_URL = "https://www.youtube.com/watch?v=k_DIcwgC3uQ&t=58s"

EXEC_TF = "15m"
HTF_TFS = ["30m", "1h", "4h", "1d"]


def session_mode_for_market(market: str) -> str:
    """Groww India stocks -> IST session; CoinDCX / others -> NY session.

    Local copy of app.market_pulse.fakeout_4h_engine.session_mode_for_market —
    duplicated here to keep this engine self-contained (that module may not be
    present depending on merge order with the registry wiring).
    """
    if "Groww" in market or "India" in market:
        return "india"
    return "ny"


def _session_tz(mode: str):
    """Same india/ny → tz mapping used by scalp_sr_mss_engine (not yet ported)."""
    return IST_TZ if mode == "india" else NY_TZ


def _ensure_market_tz(df: pd.DataFrame, market: str) -> pd.DataFrame:
    """Normalize OHLCV and express bar timestamps in the market's session timezone.

    Local copy of truebacktesting.scalp_sr_mss_engine._ensure_market_tz — that
    module has not been ported to this backend yet, so this helper is kept
    self-contained here.
    """
    work = normalize_ohlcv(df)
    if work.empty:
        return work
    mode = session_mode_for_market(market)
    tz = _session_tz(mode)
    work = work.copy()
    idx = pd.to_datetime(work.index)
    if idx.tz is not None:
        work.index = idx.tz_convert(tz)
    else:
        hours = idx.hour
        max_h = int(hours.max())
        median_h = float(np.median(hours))
        if mode == "india" and max_h <= 11 and median_h < 8:
            work.index = idx.tz_localize("UTC").tz_convert(tz)
        else:
            work.index = idx.tz_localize(tz)
    return work

PHASE_NONE = "NO_SETUP"
PHASE_BIAS = "DAILY_BIAS"
PHASE_RANGE = "SR_RANGE"
PHASE_TRAFFIC = "CLEAN_TRAFFIC"
PHASE_BREAKOUT = "BREAKOUT"
PHASE_RETEST = "RETEST_ARMED"
PHASE_ENTRY = "BR_ENTRY"

SIGNAL_BUY = 1
SIGNAL_SELL = -1

HOLD_MTF_BR = "MTF breakout-retest · 80% at 1:1 · 20% runner to structure"


@dataclass
class MtfBreakoutRetestConfig:
    execution_tf: str = EXEC_TF
    lookback_window: int = 15
    clean_traffic_bars: int = 10
    clean_traffic_max_mix: float = 0.55
    rr_ratio: float = 1.0
    partial_close_pct: float = 0.8
    take_confidence_threshold: float = 58.0
    lookback_bars: int = 400
    min_bars: int = 80
    require_htf_align: bool = True


def _body_high(o: float, c: float) -> float:
    return max(o, c)


def _body_low(o: float, c: float) -> float:
    return min(o, c)


def _daily_trend(df_1d: pd.DataFrame) -> str:
    if df_1d.empty:
        return "neutral"
    last = df_1d.iloc[-1]
    o, c = float(last["open"]), float(last["close"])
    if c > o:
        return "bullish"
    if c < o:
        return "bearish"
    return "neutral"


def _tf_trend(df: pd.DataFrame) -> str:
    if df is None or df.empty or len(df) < 3:
        return "neutral"
    recent = df.tail(3)
    ups = int((recent["close"] > recent["open"]).sum())
    dns = len(recent) - ups
    if ups >= 2:
        return "bullish"
    if dns >= 2:
        return "bearish"
    return "consolidating"


def _htf_alignment(market: str, htf_data: dict[str, pd.DataFrame], daily: str) -> dict[str, Any]:
    ctx: dict[str, Any] = {"daily": daily, "frames": {}, "aligned": True, "score": 0}
    if daily == "neutral":
        ctx["aligned"] = False
        return ctx

    agree = 0
    for tf in ["4h", "1h", "30m"]:
        tr = _tf_trend(htf_data.get(tf))
        ctx["frames"][tf] = tr
        if tr == daily or tr == "consolidating":
            agree += 1
            ctx["score"] += 1
        elif tr != "neutral":
            ctx["aligned"] = False
    ctx["agree_count"] = agree
    return ctx


def _clean_traffic(
    work: pd.DataFrame,
    end_idx: int,
    bars: int,
    max_mix: float,
) -> bool:
    start = max(0, end_idx - bars - 1)
    segment = work.iloc[start:end_idx - 1]
    if len(segment) < max(4, bars // 2):
        return False
    bull = int((segment["close"] > segment["open"]).sum())
    mix = min(bull, len(segment) - bull) / len(segment)
    return mix <= max_mix


def _range_levels(window: pd.DataFrame) -> tuple[float, float]:
    bodies_hi = np.maximum(window["open"].values, window["close"].values)
    bodies_lo = np.minimum(window["open"].values, window["close"].values)
    return float(bodies_hi.max()), float(bodies_lo.min())


def implement_mtf_breakout_retest(
    df_exec: pd.DataFrame,
    daily_trend: str,
    cfg: MtfBreakoutRetestConfig,
    *,
    htf_ctx: dict[str, Any] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    work = normalize_ohlcv(df_exec)
    if work.empty:
        return work, {}

    work = work.copy()
    work["signal"] = 0
    work["stop_loss"] = np.nan
    work["take_profit"] = np.nan
    work["setup_phase"] = PHASE_NONE
    work["daily_trend"] = daily_trend
    work["support_level"] = np.nan
    work["resistance_level"] = np.nan

    state: dict[str, Any] = {
        "setups": [],
        "htf": htf_ctx or {},
        "pending_breakout": None,
    }

    lb = cfg.lookback_window
    n = len(work)

    for i in range(lb + 2, n):
        ts = work.index[i]
        window = work.iloc[i - lb - 1 : i - 1]
        if len(window) < lb:
            continue

        res_lvl, sup_lvl = _range_levels(window)
        work.at[ts, "support_level"] = sup_lvl
        work.at[ts, "resistance_level"] = res_lvl

        if daily_trend == "neutral":
            work.at[ts, "setup_phase"] = PHASE_NONE
            continue

        work.at[ts, "setup_phase"] = PHASE_BIAS

        if not _clean_traffic(work, i, cfg.clean_traffic_bars, cfg.clean_traffic_max_mix):
            work.at[ts, "setup_phase"] = PHASE_RANGE
            continue

        work.at[ts, "setup_phase"] = PHASE_TRAFFIC

        prev = work.iloc[i - 1]
        row = work.iloc[i]
        po, ph, pl, pc = float(prev["open"]), float(prev["high"]), float(prev["low"]), float(prev["close"])
        co, ch, cl, cc = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])

        if cfg.require_htf_align and htf_ctx and not htf_ctx.get("aligned", True):
            continue

        if daily_trend == "bearish":
            broke = pc < sup_lvl and po >= sup_lvl
            if broke:
                work.at[ts, "setup_phase"] = PHASE_BREAKOUT
                state["pending_breakout"] = {
                    "direction": "SHORT",
                    "bar_index": i - 1,
                    "high": ph,
                    "low": pl,
                    "support": sup_lvl,
                    "resistance": res_lvl,
                }
            pending = state.get("pending_breakout")
            if pending and pending.get("direction") == "SHORT" and pending.get("bar_index") == i - 1:
                if cl < pl:
                    entry = pl
                    sl = ph
                    risk = sl - entry
                    if risk > 0:
                        tp = entry - risk * cfg.rr_ratio
                        work.at[ts, "signal"] = SIGNAL_SELL
                        work.at[ts, "stop_loss"] = sl
                        work.at[ts, "take_profit"] = tp
                        work.at[ts, "setup_phase"] = PHASE_ENTRY
                        state["setups"].append({"direction": "SHORT", "index": i})
                        state["pending_breakout"] = None
                else:
                    work.at[ts, "setup_phase"] = PHASE_RETEST
                    state["pending_breakout"] = None

        elif daily_trend == "bullish":
            broke = pc > res_lvl and po <= res_lvl
            if broke:
                work.at[ts, "setup_phase"] = PHASE_BREAKOUT
                state["pending_breakout"] = {
                    "direction": "LONG",
                    "bar_index": i - 1,
                    "high": ph,
                    "low": pl,
                    "support": sup_lvl,
                    "resistance": res_lvl,
                }
            pending = state.get("pending_breakout")
            if pending and pending.get("direction") == "LONG" and pending.get("bar_index") == i - 1:
                if ch > ph:
                    entry = ph
                    sl = pl
                    risk = entry - sl
                    if risk > 0:
                        tp = entry + risk * cfg.rr_ratio
                        work.at[ts, "signal"] = SIGNAL_BUY
                        work.at[ts, "stop_loss"] = sl
                        work.at[ts, "take_profit"] = tp
                        work.at[ts, "setup_phase"] = PHASE_ENTRY
                        state["setups"].append({"direction": "LONG", "index": i})
                        state["pending_breakout"] = None
                else:
                    work.at[ts, "setup_phase"] = PHASE_RETEST
                    state["pending_breakout"] = None

    return work, state


def evaluate_live_signal(
    work: pd.DataFrame,
    state: dict[str, Any],
    cfg: MtfBreakoutRetestConfig,
    *,
    daily_trend: str,
) -> dict[str, Any]:
    if work.empty:
        return {"signal": "NO_DATA"}

    price = float(work["close"].iloc[-1])
    latest_sig = int(work["signal"].iloc[-1]) if not pd.isna(work["signal"].iloc[-1]) else 0
    phase = str(work["setup_phase"].iloc[-1])
    row = work.iloc[-1]
    htf = state.get("htf") or {}

    sup = float(row["support_level"]) if pd.notna(row["support_level"]) else np.nan
    res = float(row["resistance_level"]) if pd.notna(row["resistance_level"]) else np.nan

    reasons: list[str] = []
    conf = 18.0
    direction = "WAIT"
    verdict = "WAIT"
    take = False
    stop = price
    target = price
    pending = state.get("pending_breakout")

    reasons.append(f"Daily bias: **{daily_trend.upper()}** (top-down filter)")
    if htf.get("frames"):
        reasons.append(
            "HTF — "
            + " · ".join(f"{tf}: {tr}" for tf, tr in htf["frames"].items())
        )

    if daily_trend == "neutral":
        verdict = "NO BIAS"
        reasons.append("Neutral daily candle — only trade clear bullish/bearish days")
        conf = 12.0
    elif cfg.require_htf_align and not htf.get("aligned", True):
        verdict = "HTF MISALIGN"
        conf += 8
        reasons.append("4H / 1H / 30m structure does not align with daily bias")
    else:
        conf += 14
        if htf.get("agree_count", 0) >= 2:
            conf += 12
            reasons.append("Higher timeframes confirm or consolidate with daily bias")

    if not np.isnan(sup) and not np.isnan(res):
        reasons.append(f"15m body range — support {sup:,.4g} · resistance {res:,.4g}")

    if len(work) >= cfg.lookback_window + 2:
        if _clean_traffic(work, len(work), cfg.clean_traffic_bars, cfg.clean_traffic_max_mix):
            conf += 10
            reasons.append("Clean traffic to the left — room for continuation")
        else:
            reasons.append("Choppy traffic left of range — caution")

    if latest_sig == SIGNAL_BUY:
        direction = "LONG"
        phase = PHASE_ENTRY
        verdict = "TAKE LONG"
        conf += 30
        stop = float(work["stop_loss"].iloc[-1])
        target = float(work["take_profit"].iloc[-1])
        reasons.append("Breakout above resistance · retest · break of breakout candle high")
        reasons.append(f"SL below breakout wick · TP {cfg.rr_ratio}:1 (80% partial, 20% runner)")
    elif latest_sig == SIGNAL_SELL:
        direction = "SHORT"
        phase = PHASE_ENTRY
        verdict = "TAKE SHORT"
        conf += 30
        stop = float(work["stop_loss"].iloc[-1])
        target = float(work["take_profit"].iloc[-1])
        reasons.append("Breakout below support · retest · break of breakout candle low")
        reasons.append(f"SL above breakout wick · TP {cfg.rr_ratio}:1 (80% partial, 20% runner)")
    elif pending:
        d = pending["direction"]
        direction = d
        phase = PHASE_RETEST
        verdict = f"WATCH {d}"
        conf += 20
        if d == "LONG":
            stop = pending["low"]
            risk = max(pending["high"] - stop, price * 0.002)
            target = pending["high"] + risk * cfg.rr_ratio
            reasons.append(f"Await break above breakout high {pending['high']:,.4g}")
        else:
            stop = pending["high"]
            risk = max(stop - pending["low"], price * 0.002)
            target = pending["low"] - risk * cfg.rr_ratio
            reasons.append(f"Await break below breakout low {pending['low']:,.4g}")
    elif phase == PHASE_BREAKOUT:
        conf += 16
        verdict = "WATCH — breakout bar closed"
        reasons.append("Breakout complete — watch for retest continuation trigger")
    elif phase in (PHASE_TRAFFIC, PHASE_RANGE):
        conf += 8
        reasons.append("Range mapped — waiting for clean breakout close outside body cluster")

    conf = max(12.0, min(92.0, conf))
    take = phase == PHASE_ENTRY and conf >= cfg.take_confidence_threshold

    if direction == "LONG" and stop < price:
        sl_pct = max(0.2, (price - stop) / price * 100)
        tp_pct = max(0.25, (target - price) / price * 100) if target > price else sl_pct * cfg.rr_ratio
    elif direction == "SHORT" and stop > price:
        sl_pct = max(0.2, (stop - price) / price * 100)
        tp_pct = max(0.25, (price - target) / price * 100) if target < price else sl_pct * cfg.rr_ratio
    else:
        sl_pct = 0.5
        tp_pct = sl_pct * cfg.rr_ratio

    hold = HOLD_MTF_BR
    plan = make_trade_plan(
        direction=direction if take and direction in ("LONG", "SHORT") else "—",
        timeframe=cfg.execution_tf,
        stop_loss_pct=round(sl_pct, 2),
        take_profit_pct=round(tp_pct, 2),
        confidence_pct=round(conf, 1),
        style="intraday",
        exit_rule=(
            f"Close {cfg.partial_close_pct:.0%} at {cfg.rr_ratio}:1 · move SL to BE · "
            "runner toward next structure."
        ),
        max_hold_exit="Session exit if targets not hit.",
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
        "partial_close_pct": cfg.partial_close_pct,
        "entry_price": round(price, 6),
        "stop_price": round(stop, 6),
        "target_price": round(target, 6),
        "support_level": sup,
        "resistance_level": res,
        "daily_trend": daily_trend,
        "execution_tf": cfg.execution_tf,
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": hold},
    }, hold_duration=hold)


def fetch_mtf_data(
    ticker: str,
    market: str,
    cfg: MtfBreakoutRetestConfig,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, pd.DataFrame]:
    is_crypto = "CoinDCX" in market
    out: dict[str, pd.DataFrame] = {}

    df_exec = fetch_data_for_gap_scan(
        ticker, cfg.execution_tf, market, groww_token, exchange, limit=cfg.lookback_bars,
    )
    df_exec = normalize_ohlcv(df_exec)
    if df_exec.empty or len(df_exec) < cfg.min_bars:
        df_exec = normalize_ohlcv(
            fetch_ohlcv_yfinance(
                ticker, cfg.execution_tf, is_crypto=is_crypto, limit=cfg.lookback_bars, market=market,
            ),
        )
    out[cfg.execution_tf] = df_exec

    for tf in HTF_TFS:
        df = fetch_data_for_gap_scan(
            ticker, tf, market, groww_token, exchange, limit=max(80, cfg.lookback_bars // 5),
        )
        df = normalize_ohlcv(df)
        if df.empty:
            df = normalize_ohlcv(
                fetch_ohlcv_yfinance(
                    ticker, tf, is_crypto=is_crypto, limit=max(80, cfg.lookback_bars // 5), market=market,
                ),
            )
        out[tf] = df

    return out


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: MtfBreakoutRetestConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or MtfBreakoutRetestConfig()
    data = fetch_mtf_data(ticker, market, cfg, groww_token=groww_token, exchange=exchange)
    df_exec = _ensure_market_tz(data.get(cfg.execution_tf, pd.DataFrame()), market)

    if df_exec.empty or len(df_exec) < cfg.min_bars:
        return {"ticker": ticker, "error": f"Insufficient {cfg.execution_tf} data."}

    daily = _daily_trend(data.get("1d", pd.DataFrame()))
    htf_ctx = _htf_alignment(market, data, daily)

    work, state = implement_mtf_breakout_retest(df_exec, daily, cfg, htf_ctx=htf_ctx)
    live = evaluate_live_signal(work, state, cfg, daily_trend=daily)

    signals = work[work["signal"].isin([SIGNAL_BUY, SIGNAL_SELL])]
    return {
        "ticker": ticker,
        "market": market,
        "execution_tf": cfg.execution_tf,
        "daily_trend": daily,
        "htf": htf_ctx,
        "bars": len(work),
        "last_close": float(work["close"].iloc[-1]),
        "signal_count": len(signals),
        "live": live,
    }


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: MtfBreakoutRetestConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or MtfBreakoutRetestConfig()
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
        and (r.get("live") or {}).get("phase") in (
            PHASE_BREAKOUT, PHASE_RETEST, PHASE_TRAFFIC, PHASE_RANGE,
        )
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
