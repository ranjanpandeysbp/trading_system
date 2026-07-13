"""
scalp_sr_mss_engine.py
----------------------
HTF Support/Resistance zones + 1m Market Structure Shift (MSS) execution.

Zone (1H/4H): support = wick low → body low; resistance = body high → wick high.
LTF (1m): tap zone after session open → MSS → break recent swing for entry.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import time
from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.fakeout_4h_engine import (
    INDIA_MARKET_CLOSE,
    INDIA_MARKET_OPEN,
    IST_TZ,
    NY_TZ,
    session_mode_for_market,
)
from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.trading_hubs.intraday_shared import enrich_intra_live
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan

logger = logging.getLogger(__name__)

YOUTUBE_SCALP_SR_MSS_URL = "https://www.youtube.com/watch?v=SdbBbc8lFQ8&t=82s"

HTF_OPTIONS = ["1h", "4h"]
EXEC_TF = "1m"

PHASE_NONE = "NO_SETUP"
PHASE_PRE_SESSION = "PRE_SESSION"
PHASE_IN_SUPPORT = "IN_SUPPORT_ZONE"
PHASE_IN_RESISTANCE = "IN_RESISTANCE_ZONE"
PHASE_MSS_LONG = "MSS_LONG_ARMED"
PHASE_MSS_SHORT = "MSS_SHORT_ARMED"
PHASE_ENTRY = "MSS_ENTRY"

SIGNAL_BUY = 1
SIGNAL_SELL = -1

HOLD_SR_MSS = "S/R MSS scalp · 2.4:1 R:R · exit on SL/TP or session end"

# Session open — trades only after this (per market)
SESSION_OPEN_BY_MODE: dict[str, time] = {
    "india": INDIA_MARKET_OPEN,  # 09:15 IST
    "ny": time(9, 30),           # 09:30 US/Eastern (Groww US-style / CoinDCX NY)
}

SESSION_CLOSE_BY_MODE: dict[str, time] = {
    "india": INDIA_MARKET_CLOSE,
    "ny": time(16, 0),
}


@dataclass
class SrMssConfig:
    htf: str = "1h"
    execution_tf: str = EXEC_TF
    swing_window: int = 5
    rr_ratio: float = 2.4
    take_confidence_threshold: float = 58.0
    lookback_bars: int = 800
    min_bars: int = 120
    mss_lookback_swings: int = 3


def _session_tz(mode: str):
    return IST_TZ if mode == "india" else NY_TZ


def _ensure_market_tz(df: pd.DataFrame, market: str) -> pd.DataFrame:
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


def _after_session_open(ts: pd.Timestamp, mode: str) -> bool:
    open_t = SESSION_OPEN_BY_MODE.get(mode, time(9, 30))
    close_t = SESSION_CLOSE_BY_MODE.get(mode, time(16, 0))
    t = ts.time()
    return open_t <= t <= close_t


def _build_htf_zones(df_htf: pd.DataFrame) -> pd.DataFrame:
    """Per HTF bar: support zone (low → body low), resistance (body high → high)."""
    htf = normalize_ohlcv(df_htf)
    if htf.empty:
        return htf
    out = htf.copy()
    lowest_body = np.minimum(out["open"].values, out["close"].values)
    highest_body = np.maximum(out["open"].values, out["close"].values)
    out["support_top"] = lowest_body
    out["support_bottom"] = out["low"].values
    out["resistance_top"] = out["high"].values
    out["resistance_bottom"] = highest_body
    return out[["support_top", "support_bottom", "resistance_top", "resistance_bottom"]]


def _resample_htf(df_1m: pd.DataFrame, htf: str) -> pd.DataFrame:
    rule = "1h" if htf == "1h" else "4h"
    return df_1m.resample(rule).agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna()


def _overlay_zones(df_1m: pd.DataFrame, zones_htf: pd.DataFrame) -> pd.DataFrame:
    work = df_1m.copy()
    if zones_htf.empty:
        for col in ("support_top", "support_bottom", "resistance_top", "resistance_bottom"):
            work[col] = np.nan
        return work
    zones = zones_htf.copy()
    if work.index.tz != zones.index.tz:
        if work.index.tz is not None:
            zones.index = zones.index.tz_localize("UTC").tz_convert(work.index.tz) if zones.index.tz is None else zones.index.tz_convert(work.index.tz)
        elif zones.index.tz is not None:
            zones.index = zones.index.tz_convert(None)
    aligned = zones.reindex(work.index, method="ffill")
    for col in aligned.columns:
        work[col] = aligned[col].values
    return work


def _compute_swing_columns(work: pd.DataFrame, window: int) -> pd.DataFrame:
    out = work.copy()
    half = max(1, window // 2)
    highs = out["high"].values
    lows = out["low"].values
    n = len(out)
    swing_hi = np.full(n, np.nan)
    swing_lo = np.full(n, np.nan)

    for i in range(half, n - half):
        w_hi = highs[i - half : i + half + 1].max()
        w_lo = lows[i - half : i + half + 1].min()
        if highs[i] == w_hi:
            swing_hi[i] = highs[i]
        if lows[i] == w_lo:
            swing_lo[i] = lows[i]

    out["swing_high"] = swing_hi
    out["swing_low"] = swing_lo
    out["recent_swing_high"] = pd.Series(swing_hi, index=out.index).ffill()
    out["recent_swing_low"] = pd.Series(swing_lo, index=out.index).ffill()
    return out


def _collect_swing_points(series: pd.Series, limit: int = 4) -> list[float]:
    vals = [float(v) for v in series.dropna().values[-limit * 3 :]]
    points: list[float] = []
    for v in vals:
        if not points or v != points[-1]:
            points.append(v)
    return points[-limit:]


def _has_hh_hl(swing_highs: list[float], swing_lows: list[float]) -> bool:
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return False
    return swing_highs[-1] > swing_highs[-2] and swing_lows[-1] > swing_lows[-2]


def _has_lh_ll(swing_highs: list[float], swing_lows: list[float]) -> bool:
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return False
    return swing_highs[-1] < swing_highs[-2] and swing_lows[-1] < swing_lows[-2]


def _in_support(price: float, top: float, bot: float) -> bool:
    if np.isnan(top) or np.isnan(bot):
        return False
    lo, hi = min(bot, top), max(bot, top)
    return lo <= price <= hi


def _in_resistance(price: float, top: float, bot: float) -> bool:
    return _in_support(price, top, bot)


def _target_from_older_swings(
    direction: str,
    entry: float,
    swing_highs: pd.Series,
    swing_lows: pd.Series,
    risk: float,
    rr: float,
) -> float:
    if direction == "LONG":
        older = [float(v) for v in swing_highs.dropna().values if float(v) > entry]
        if older:
            return max(older[-3:]) if len(older) >= 1 else entry + risk * rr
        return entry + risk * rr
    older = [float(v) for v in swing_lows.dropna().values if float(v) < entry]
    if older:
        return min(older[-3:]) if len(older) >= 1 else entry - risk * rr
    return entry - risk * rr


def implement_sr_mss_strategy(
    df_1m: pd.DataFrame,
    df_htf: pd.DataFrame,
    cfg: SrMssConfig,
    market: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    mode = session_mode_for_market(market)
    work = _ensure_market_tz(df_1m, market)
    if work.empty:
        return work, {}

    zones_htf = _build_htf_zones(
        _ensure_market_tz(df_htf, market) if not df_htf.empty else _resample_htf(work, cfg.htf)
    )
    if not zones_htf.empty and work.index.tz is not None:
        if zones_htf.index.tz is None:
            zones_htf.index = zones_htf.index.tz_localize(work.index.tz)
        else:
            zones_htf.index = zones_htf.index.tz_convert(work.index.tz)
    work = _overlay_zones(work, zones_htf)
    work = _compute_swing_columns(work, cfg.swing_window)

    work["signal"] = 0
    work["stop_loss"] = np.nan
    work["take_profit"] = np.nan
    work["setup_phase"] = PHASE_NONE
    work["zone_side"] = ""

    state: dict[str, Any] = {"setups": [], "mode": mode, "htf": cfg.htf}

    for i in range(1, len(work)):
        ts = work.index[i]
        if not _after_session_open(ts, mode):
            work.at[ts, "setup_phase"] = PHASE_PRE_SESSION
            continue

        row = work.iloc[i]
        prev = work.iloc[i - 1]
        price = float(row["close"])
        prev_sh = float(prev["recent_swing_high"]) if pd.notna(prev["recent_swing_high"]) else np.nan
        prev_sl = float(prev["recent_swing_low"]) if pd.notna(prev["recent_swing_low"]) else np.nan

        sup_top = float(row["support_top"]) if pd.notna(row["support_top"]) else np.nan
        sup_bot = float(row["support_bottom"]) if pd.notna(row["support_bottom"]) else np.nan
        res_top = float(row["resistance_top"]) if pd.notna(row["resistance_top"]) else np.nan
        res_bot = float(row["resistance_bottom"]) if pd.notna(row["resistance_bottom"]) else np.nan

        sh_pts = _collect_swing_points(work["swing_high"].iloc[:i], cfg.mss_lookback_swings)
        sl_pts = _collect_swing_points(work["swing_low"].iloc[:i], cfg.mss_lookback_swings)

        in_sup = _in_support(price, sup_top, sup_bot)
        in_res = _in_resistance(price, res_top, res_bot)

        if in_sup:
            work.at[ts, "zone_side"] = "support"
            work.at[ts, "setup_phase"] = PHASE_IN_SUPPORT
            if _has_lh_ll(sh_pts, sl_pts) and not np.isnan(prev_sh) and price > prev_sh:
                sl = prev_sl if not np.isnan(prev_sl) else price * 0.995
                risk = max(price - sl, price * 0.002)
                tp = _target_from_older_swings(
                    "LONG", price, work["swing_high"].iloc[:i], work["swing_low"].iloc[:i], risk, cfg.rr_ratio,
                )
                if tp < price + risk * (cfg.rr_ratio * 0.8):
                    tp = price + risk * cfg.rr_ratio
                work.at[ts, "signal"] = SIGNAL_BUY
                work.at[ts, "stop_loss"] = sl
                work.at[ts, "take_profit"] = tp
                work.at[ts, "setup_phase"] = PHASE_ENTRY
                state["setups"].append({"direction": "LONG", "index": i})
            elif _has_lh_ll(sh_pts, sl_pts):
                work.at[ts, "setup_phase"] = PHASE_MSS_LONG
        elif in_res:
            work.at[ts, "zone_side"] = "resistance"
            work.at[ts, "setup_phase"] = PHASE_IN_RESISTANCE
            if _has_hh_hl(sh_pts, sl_pts) and not np.isnan(prev_sl) and price < prev_sl:
                sl = prev_sh if not np.isnan(prev_sh) else price * 1.005
                risk = max(sl - price, price * 0.002)
                tp = _target_from_older_swings(
                    "SHORT", price, work["swing_high"].iloc[:i], work["swing_low"].iloc[:i], risk, cfg.rr_ratio,
                )
                if tp > price - risk * (cfg.rr_ratio * 0.8):
                    tp = price - risk * cfg.rr_ratio
                work.at[ts, "signal"] = SIGNAL_SELL
                work.at[ts, "stop_loss"] = sl
                work.at[ts, "take_profit"] = tp
                work.at[ts, "setup_phase"] = PHASE_ENTRY
                state["setups"].append({"direction": "SHORT", "index": i})
            elif _has_hh_hl(sh_pts, sl_pts):
                work.at[ts, "setup_phase"] = PHASE_MSS_SHORT

    return work, state


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
            "zone": str(work["zone_side"].iloc[i] or "—"),
            "sl": round(float(work["stop_loss"].iloc[i]), 4) if pd.notna(work["stop_loss"].iloc[i]) else None,
            "tp": round(float(work["take_profit"].iloc[i]), 4) if pd.notna(work["take_profit"].iloc[i]) else None,
        })
        if len(rows) >= limit:
            break
    return rows


def evaluate_live_signal(
    work: pd.DataFrame,
    state: dict[str, Any],
    cfg: SrMssConfig,
    market: str,
) -> dict[str, Any]:
    if work.empty:
        return {"signal": "NO_DATA"}

    mode = state.get("mode") or session_mode_for_market(market)
    price = float(work["close"].iloc[-1])
    latest_sig = int(work["signal"].iloc[-1]) if not pd.isna(work["signal"].iloc[-1]) else 0
    phase = str(work["setup_phase"].iloc[-1])
    zone_side = str(work["zone_side"].iloc[-1] or "")
    ts = work.index[-1]

    row = work.iloc[-1]
    prev = work.iloc[-2] if len(work) > 1 else row
    prev_sh = float(prev["recent_swing_high"]) if pd.notna(prev["recent_swing_high"]) else price
    prev_sl = float(prev["recent_swing_low"]) if pd.notna(prev["recent_swing_low"]) else price

    sup_top = float(row["support_top"]) if pd.notna(row["support_top"]) else np.nan
    sup_bot = float(row["support_bottom"]) if pd.notna(row["support_bottom"]) else np.nan
    res_top = float(row["resistance_top"]) if pd.notna(row["resistance_top"]) else np.nan
    res_bot = float(row["resistance_bottom"]) if pd.notna(row["resistance_bottom"]) else np.nan

    sh_pts = _collect_swing_points(work["swing_high"], cfg.mss_lookback_swings)
    sl_pts = _collect_swing_points(work["swing_low"], cfg.mss_lookback_swings)

    reasons: list[str] = []
    conf = 20.0
    direction = "WAIT"
    verdict = "WAIT"
    take = False
    stop = price
    target = price

    open_label = "09:15 IST" if mode == "india" else "09:30 NY (US session)"
    reasons.append(f"HTF **{cfg.htf}** S/R zones mapped to **1m** · trades after **{open_label}**")

    if not _after_session_open(ts, mode):
        phase = PHASE_PRE_SESSION
        verdict = "PRE-SESSION"
        reasons.append(f"Waiting for session window (after {open_label})")
        conf = 15.0
    else:
        if not np.isnan(sup_bot):
            reasons.append(f"Support zone {sup_bot:,.4g} – {sup_top:,.4g}")
        if not np.isnan(res_bot):
            reasons.append(f"Resistance zone {res_bot:,.4g} – {res_top:,.4g}")

        in_sup = _in_support(price, sup_top, sup_bot)
        in_res = _in_resistance(price, res_top, res_bot)

        if in_sup:
            zone_side = "support"
            conf += 14
            reasons.append("Price tapping HTF **support** zone (wick low → body low)")
            if _has_lh_ll(sh_pts, sl_pts):
                conf += 18
                phase = PHASE_MSS_LONG
                reasons.append("MSS: lower highs + lower lows into support")
                if price > prev_sh:
                    direction = "LONG"
                    phase = PHASE_ENTRY
                    verdict = "TAKE LONG"
                    conf += 26
                    stop = prev_sl
                    risk = max(price - stop, price * 0.002)
                    target = price + risk * cfg.rr_ratio
                    reasons.append("Trigger: 1m close broke above recent swing high")
                else:
                    verdict = "WATCH LONG"
                    reasons.append(f"Await break above recent swing high ({prev_sh:,.4g})")
                    stop = prev_sl
                    target = price + max(price - stop, price * 0.002) * cfg.rr_ratio
            else:
                phase = PHASE_IN_SUPPORT
                reasons.append("In support — need LH/LL micro structure before MSS trigger")
        elif in_res:
            zone_side = "resistance"
            conf += 14
            reasons.append("Price tapping HTF **resistance** zone (body high → wick high)")
            if _has_hh_hl(sh_pts, sl_pts):
                conf += 18
                phase = PHASE_MSS_SHORT
                reasons.append("MSS: higher highs + higher lows into resistance")
                if price < prev_sl:
                    direction = "SHORT"
                    phase = PHASE_ENTRY
                    verdict = "TAKE SHORT"
                    conf += 26
                    stop = prev_sh
                    risk = max(stop - price, price * 0.002)
                    target = price - risk * cfg.rr_ratio
                    reasons.append("Trigger: 1m close broke below recent swing low")
                else:
                    verdict = "WATCH SHORT"
                    reasons.append(f"Await break below recent swing low ({prev_sl:,.4g})")
                    stop = prev_sh
                    target = price - max(stop - price, price * 0.002) * cfg.rr_ratio
            else:
                phase = PHASE_IN_RESISTANCE
                reasons.append("In resistance — need HH/HL micro structure before MSS trigger")
        else:
            reasons.append("Price outside HTF S/R zones — no tap, no trade")

        if latest_sig == SIGNAL_BUY:
            direction = "LONG"
            phase = PHASE_ENTRY
            verdict = "TAKE LONG"
            stop = float(work["stop_loss"].iloc[-1]) if pd.notna(work["stop_loss"].iloc[-1]) else stop
            target = float(work["take_profit"].iloc[-1]) if pd.notna(work["take_profit"].iloc[-1]) else target
        elif latest_sig == SIGNAL_SELL:
            direction = "SHORT"
            phase = PHASE_ENTRY
            verdict = "TAKE SHORT"
            stop = float(work["stop_loss"].iloc[-1]) if pd.notna(work["stop_loss"].iloc[-1]) else stop
            target = float(work["take_profit"].iloc[-1]) if pd.notna(work["take_profit"].iloc[-1]) else target

    conf = max(15.0, min(92.0, conf))
    take = phase == PHASE_ENTRY and conf >= cfg.take_confidence_threshold

    if direction == "LONG" and stop < price:
        sl_pct = max(0.15, (price - stop) / price * 100)
        tp_pct = max(0.25, (target - price) / price * 100) if target > price else sl_pct * cfg.rr_ratio
    elif direction == "SHORT" and stop > price:
        sl_pct = max(0.15, (stop - price) / price * 100)
        tp_pct = max(0.25, (price - target) / price * 100) if target < price else sl_pct * cfg.rr_ratio
    else:
        sl_pct = 0.4
        tp_pct = sl_pct * cfg.rr_ratio

    hold = HOLD_SR_MSS
    plan = make_trade_plan(
        direction=direction if take and direction in ("LONG", "SHORT") else "—",
        timeframe=cfg.execution_tf,
        stop_loss_pct=round(sl_pct, 2),
        take_profit_pct=round(tp_pct, 2),
        confidence_pct=round(conf, 1),
        style="intraday",
        exit_rule=f"SL beyond 1m swing extreme · TP ~{cfg.rr_ratio}:1 R:R or older swing pool.",
        max_hold_exit="Session scalp — flatten by cash-market close if flat.",
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
        "support_top": sup_top,
        "support_bottom": sup_bot,
        "resistance_top": res_top,
        "resistance_bottom": res_bot,
        "zone_side": zone_side,
        "htf": cfg.htf,
        "session_mode": mode,
        "execution_tf": cfg.execution_tf,
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": hold},
    }, hold_duration=hold)


def fetch_exec_data(
    ticker: str,
    market: str,
    cfg: SrMssConfig,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    is_crypto = "CoinDCX" in market
    df_1m = fetch_data_for_gap_scan(
        ticker, cfg.execution_tf, market, groww_token, exchange, limit=cfg.lookback_bars,
    )
    df_1m = normalize_ohlcv(df_1m)
    if df_1m.empty or len(df_1m) < cfg.min_bars:
        df_1m = normalize_ohlcv(
            fetch_ohlcv_yfinance(
                ticker, cfg.execution_tf, is_crypto=is_crypto, limit=cfg.lookback_bars, market=market,
            ),
        )

    df_htf = fetch_data_for_gap_scan(
        ticker, cfg.htf, market, groww_token, exchange, limit=max(120, cfg.lookback_bars // 10),
    )
    df_htf = normalize_ohlcv(df_htf)
    if df_htf.empty:
        work_tz = _ensure_market_tz(df_1m, market)
        df_htf = _resample_htf(work_tz, cfg.htf)

    return df_1m, df_htf


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: SrMssConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or SrMssConfig()
    df_1m, df_htf = fetch_exec_data(ticker, market, cfg, groww_token=groww_token, exchange=exchange)
    if df_1m.empty or len(df_1m) < cfg.min_bars:
        return {"ticker": ticker, "error": f"Insufficient {cfg.execution_tf} data."}

    work, state = implement_sr_mss_strategy(df_1m, df_htf, cfg, market)
    live = evaluate_live_signal(work, state, cfg, market)

    return {
        "ticker": ticker,
        "market": market,
        "execution_tf": cfg.execution_tf,
        "htf": cfg.htf,
        "bars": len(work),
        "last_close": float(work["close"].iloc[-1]) if not work.empty else 0.0,
        "signal_history": _signal_history(work),
        "live": live,
    }


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: SrMssConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or SrMssConfig()
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
            PHASE_IN_SUPPORT, PHASE_IN_RESISTANCE, PHASE_MSS_LONG, PHASE_MSS_SHORT,
        )
    ]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))
    watches.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market,
        "execution_tf": cfg.execution_tf,
        "htf": cfg.htf,
        "results": results,
        "entries": entries,
        "watchlist": watches,
        "entry_count": len(entries),
        "watch_count": len(watches),
    }
