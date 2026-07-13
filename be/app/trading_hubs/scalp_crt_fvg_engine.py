"""
scalp_crt_fvg_engine.py
-----------------------
Advanced Scalping — Market Structure, Liquidity & Candle Range Theory (CRT).

HTF (1h/4h): SMA trend bias -> Candle Range Theory sweep (a pullback candle's high/low
is liquidity; the next candle sweeps it but closes back inside the range = rejection).
LTF (5m/15m): Fair Value Gap (FVG) formed after the HTF sweep -> limit entry inside the FVG.

SL beyond the FVG · TP1 at 1:1 R:R (close 50%, move SL to break-even) · TP2 at the next
major structural high/low.
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

YOUTUBE_SCALP_CRT_FVG_URL = "https://www.youtube.com/watch?v=o8YajmBv1-0&t=4s"

HTF_OPTIONS = ["1h", "4h"]
LTF_OPTIONS = ["5m", "15m"]

PHASE_NONE = "NO_SETUP"
PHASE_CRT_SWEEP = "CRT_SWEEP_CONFIRMED"
PHASE_FVG_ARMED = "FVG_ENTRY_ARMED"
PHASE_ENTRY = "CRT_FVG_ENTRY"

SIGNAL_BUY = 1
SIGNAL_SELL = -1

HOLD_CRT_FVG = "CRT-FVG scalp · TP1 @1:1 (50%, SL→BE) · TP2 next structure · exit on SL/TP2"


@dataclass
class CrtFvgConfig:
    htf: str = "1h"
    ltf: str = "5m"
    trend_lookback: int = 20
    swing_window: int = 5
    rr_ratio: float = 2.0
    max_sweep_age_bars: int = 4
    take_confidence_threshold: float = 60.0
    lookback_bars: int = 600
    min_bars: int = 60


# ---------------------------------------------------------------------------
# 1. Market structure / trend (HTF)
# ---------------------------------------------------------------------------

def identify_trend(df: pd.DataFrame, lookback: int = 20) -> pd.DataFrame:
    """SMA-based trend bias. 1 = Uptrend (HH/HL context), -1 = Downtrend (LH/LL context)."""
    out = df.copy()
    out["sma"] = out["close"].rolling(window=lookback, min_periods=max(2, lookback // 4)).mean()
    out["trend"] = np.where(out["close"] > out["sma"], 1, -1)
    return out


# ---------------------------------------------------------------------------
# 2. Candle Range Theory (CRT) sweep detection (HTF)
# ---------------------------------------------------------------------------

def detect_crt_sweep(df: pd.DataFrame) -> pd.DataFrame:
    """
    The prior (pullback) candle's high/low is the liquidity range (CRH/CRL).
    Sweep = next candle pierces that range but closes back inside it (rejection).
    Invalidation = next candle closes fully outside the range (expansion, not rejection).
    """
    out = df.copy()
    out["crt_signal"] = 0  # 1 = bullish sweep (uptrend continuation), -1 = bearish sweep
    out["crt_invalid"] = False
    out["crh"] = np.nan
    out["crl"] = np.nan

    sig_col = out.columns.get_loc("crt_signal")
    inv_col = out.columns.get_loc("crt_invalid")
    crh_col = out.columns.get_loc("crh")
    crl_col = out.columns.get_loc("crl")

    for i in range(1, len(out)):
        prev = out.iloc[i - 1]
        curr = out.iloc[i]
        trend = out["trend"].iloc[i]

        if trend == 1 and prev["close"] < prev["open"]:
            # Bearish pullback candle inside an uptrend -> CRL is its low.
            crl = prev["low"]
            crh = prev["high"]
            if curr["low"] < crl and curr["close"] > crl:
                out.iat[i, sig_col] = SIGNAL_BUY
                out.iat[i, crh_col] = crh
                out.iat[i, crl_col] = crl
            elif curr["close"] < crl:
                out.iat[i, inv_col] = True

        elif trend == -1 and prev["close"] > prev["open"]:
            # Bullish pullback candle inside a downtrend -> CRH is its high.
            crh = prev["high"]
            crl = prev["low"]
            if curr["high"] > crh and curr["close"] < crh:
                out.iat[i, sig_col] = SIGNAL_SELL
                out.iat[i, crh_col] = crh
                out.iat[i, crl_col] = crl
            elif curr["close"] > crh:
                out.iat[i, inv_col] = True

    return out


# ---------------------------------------------------------------------------
# 3. Fair Value Gap detection (LTF)
# ---------------------------------------------------------------------------

def find_fair_value_gaps(df: pd.DataFrame) -> pd.DataFrame:
    """3-candle FVG: candle[i].low > candle[i-2].high (bullish); candle[i].high < candle[i-2].low (bearish)."""
    out = df.copy()
    out["bullish_fvg"] = False
    out["bearish_fvg"] = False
    out["fvg_top"] = np.nan
    out["fvg_bottom"] = np.nan

    bull_col = out.columns.get_loc("bullish_fvg")
    bear_col = out.columns.get_loc("bearish_fvg")
    top_col = out.columns.get_loc("fvg_top")
    bot_col = out.columns.get_loc("fvg_bottom")

    for i in range(2, len(out)):
        if out["low"].iloc[i] > out["high"].iloc[i - 2]:
            out.iat[i, bull_col] = True
            out.iat[i, top_col] = out["low"].iloc[i]
            out.iat[i, bot_col] = out["high"].iloc[i - 2]
        if out["high"].iloc[i] < out["low"].iloc[i - 2]:
            out.iat[i, bear_col] = True
            out.iat[i, top_col] = out["low"].iloc[i - 2]
            out.iat[i, bot_col] = out["high"].iloc[i]

    return out


def _swing_columns(df: pd.DataFrame, window: int) -> pd.DataFrame:
    out = df.copy()
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
    return out


def _next_structure_target(direction: str, entry: float, htf_swings: pd.DataFrame, risk: float, rr: float) -> float:
    if direction == "LONG":
        older = sorted(v for v in htf_swings["swing_high"].dropna().values if v > entry)
        if older:
            return float(older[0])
        return entry + risk * rr
    older = sorted((v for v in htf_swings["swing_low"].dropna().values if v < entry), reverse=True)
    if older:
        return float(older[0])
    return entry - risk * rr


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_crt_fvg_pipeline(df_ltf: pd.DataFrame, df_htf: pd.DataFrame, cfg: CrtFvgConfig) -> dict[str, Any]:
    ltf = normalize_ohlcv(df_ltf)
    htf = normalize_ohlcv(df_htf)
    if ltf.empty or len(ltf) < cfg.min_bars:
        return {"error": f"Insufficient {cfg.ltf} data."}
    if htf.empty or len(htf) < max(cfg.trend_lookback, 10):
        return {"error": f"Insufficient {cfg.htf} data."}

    htf = identify_trend(htf, cfg.trend_lookback)
    htf = detect_crt_sweep(htf)
    htf = _swing_columns(htf, cfg.swing_window)
    ltf = find_fair_value_gaps(ltf)

    return {"df_ltf": ltf, "df_htf": htf}


def _latest_crt_sweep(htf: pd.DataFrame, max_age: int) -> dict[str, Any] | None:
    recent = htf.iloc[-max_age:]
    nonzero = recent[recent["crt_signal"] != 0]
    if nonzero.empty:
        return None
    ts = nonzero.index[-1]
    row = nonzero.iloc[-1]
    return {
        "timestamp": ts,
        "direction": "LONG" if int(row["crt_signal"]) == SIGNAL_BUY else "SHORT",
        "crh": float(row["crh"]),
        "crl": float(row["crl"]),
        "trend": int(row["trend"]),
    }


def _matching_fvg_after(ltf: pd.DataFrame, sweep_ts, direction: str) -> dict[str, Any] | None:
    after = ltf[ltf.index > sweep_ts]
    if after.empty:
        return None
    col = "bullish_fvg" if direction == "LONG" else "bearish_fvg"
    matches = after[after[col]]
    if matches.empty:
        return None
    ts = matches.index[0]  # the FVG that forms right after the sweep, not a later one
    row = matches.loc[ts]
    return {
        "timestamp": ts,
        "top": float(row["fvg_top"]),
        "bottom": float(row["fvg_bottom"]),
    }


def evaluate_live_signal(pipeline: dict[str, Any], cfg: CrtFvgConfig) -> dict[str, Any]:
    if pipeline.get("error"):
        return {"signal": "NO_DATA"}

    ltf = pipeline["df_ltf"]
    htf = pipeline["df_htf"]
    price = float(ltf["close"].iloc[-1])
    trend = int(htf["trend"].iloc[-1])
    trend_label = "UPTREND" if trend == 1 else "DOWNTREND"

    reasons: list[str] = [f"HTF **{cfg.htf}** trend bias (SMA-{cfg.trend_lookback}): **{trend_label}**"]
    conf = 22.0
    direction = "WAIT"
    phase = PHASE_NONE
    verdict = "WAIT"
    take = False
    stop = price
    target1 = price
    target2 = price
    fvg_top = fvg_bottom = None
    sweep_info: dict[str, Any] | None = None
    fvg_info: dict[str, Any] | None = None

    sweep = _latest_crt_sweep(htf, cfg.max_sweep_age_bars)
    if sweep is None:
        reasons.append("No fresh CRT sweep (pullback candle swept & rejected) on HTF")
        conf = 20.0
    else:
        sweep_info = sweep
        direction = sweep["direction"]
        phase = PHASE_CRT_SWEEP
        conf += 20
        rng_label = "CRL" if direction == "LONG" else "CRH"
        rng_val = sweep["crl"] if direction == "LONG" else sweep["crh"]
        reasons.append(
            f"CRT sweep confirmed **{direction}** — pullback range swept below/above **{rng_label} {rng_val:,.4g}** "
            f"and closed back inside (rejection, not expansion)"
        )

        fvg = _matching_fvg_after(ltf, sweep["timestamp"], direction)
        if fvg is None:
            verdict = f"WATCH {direction}"
            reasons.append(f"Waiting for a **{cfg.ltf}** Fair Value Gap to form after the sweep")
            conf += 6
        else:
            fvg_info = fvg
            fvg_top, fvg_bottom = fvg["top"], fvg["bottom"]
            phase = PHASE_FVG_ARMED
            conf += 22
            reasons.append(f"FVG entry zone **{fvg_bottom:,.4g} – {fvg_top:,.4g}** formed on **{cfg.ltf}** after the sweep")

            risk_buffer = max((fvg_top - fvg_bottom) * 0.15, price * 0.0005)
            entry = (fvg_top + fvg_bottom) / 2.0

            if direction == "LONG":
                stop = fvg_bottom - risk_buffer
                risk = max(entry - stop, price * 0.001)
                target1 = entry + risk  # TP1 @ 1:1
                target2 = _next_structure_target("LONG", entry, htf, risk, cfg.rr_ratio)
                invalidated = price < stop
                in_zone = fvg_bottom <= price <= fvg_top
            else:
                stop = fvg_top + risk_buffer
                risk = max(stop - entry, price * 0.001)
                target1 = entry - risk
                target2 = _next_structure_target("SHORT", entry, htf, risk, cfg.rr_ratio)
                invalidated = price > stop
                in_zone = fvg_bottom <= price <= fvg_top

            if invalidated:
                phase = PHASE_NONE
                direction = "WAIT"
                verdict = "INVALIDATED"
                reasons.append("Price closed beyond the FVG stop level — setup invalidated")
                conf = 18.0
            elif in_zone:
                phase = PHASE_ENTRY
                verdict = f"TAKE {direction}"
                conf += 24
                reasons.append(
                    f"Price is trading inside the FVG limit zone — buy/sell limit filled · "
                    f"TP1 @1:1 (close 50%, SL→BE), TP2 @ next structure"
                )
            else:
                verdict = f"WATCH {direction}"
                reasons.append("Price has not yet tapped back into the FVG limit zone")

    conf = max(15.0, min(93.0, conf))
    take = phase == PHASE_ENTRY and conf >= cfg.take_confidence_threshold

    if direction == "LONG" and stop < price:
        sl_pct = max(0.15, (price - stop) / price * 100)
        tp_pct = max(0.2, (target1 - price) / price * 100) if target1 > price else sl_pct
    elif direction == "SHORT" and stop > price:
        sl_pct = max(0.15, (stop - price) / price * 100)
        tp_pct = max(0.2, (price - target1) / price * 100) if target1 < price else sl_pct
    else:
        sl_pct = 0.4
        tp_pct = sl_pct

    plan = make_trade_plan(
        direction=direction if take and direction in ("LONG", "SHORT") else "—",
        timeframe=cfg.ltf,
        stop_loss_pct=round(sl_pct, 2),
        take_profit_pct=round(tp_pct, 2),
        confidence_pct=round(conf, 1),
        style="intraday",
        exit_rule="TP1 @1:1 R:R — close 50%, move SL to break-even. TP2 @ next structural high/low.",
        max_hold_exit="Scalp time stop — exit if FVG is invalidated (closes beyond SL).",
    )

    return enrich_intra_live({
        "signal": direction if phase == PHASE_ENTRY else "NONE",
        "direction": direction,
        "take_trade": take,
        "verdict": verdict,
        "phase": phase,
        "confidence_pct": round(conf, 1),
        "sl_pct": round(sl_pct, 2),
        "tp_pct": round(tp_pct, 2),
        "hold_duration": HOLD_CRT_FVG,
        "rr_ratio": cfg.rr_ratio,
        "entry_price": round(price, 6),
        "stop_price": round(stop, 6),
        "target_price": round(target1, 6),
        "target1_price": round(target1, 6),
        "target2_price": round(target2, 6),
        "fvg_top": fvg_top,
        "fvg_bottom": fvg_bottom,
        "trend": trend_label,
        "htf": cfg.htf,
        "ltf": cfg.ltf,
        "sweep": sweep_info,
        "fvg": fvg_info,
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": HOLD_CRT_FVG},
    }, hold_duration=HOLD_CRT_FVG)


def _signal_history(htf: pd.DataFrame, limit: int = 8) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i in range(len(htf) - 1, -1, -1):
        sig = int(htf["crt_signal"].iloc[i]) if not pd.isna(htf["crt_signal"].iloc[i]) else 0
        if sig == 0:
            continue
        ts = htf.index[i]
        rows.append({
            "time": ts.strftime("%Y-%m-%d %H:%M") if hasattr(ts, "strftime") else str(ts),
            "signal": "BUY" if sig == SIGNAL_BUY else "SELL",
            "close": round(float(htf["close"].iloc[i]), 4),
            "crh": round(float(htf["crh"].iloc[i]), 4) if pd.notna(htf["crh"].iloc[i]) else None,
            "crl": round(float(htf["crl"].iloc[i]), 4) if pd.notna(htf["crl"].iloc[i]) else None,
        })
        if len(rows) >= limit:
            break
    return rows


def fetch_exec_data(
    ticker: str,
    market: str,
    cfg: CrtFvgConfig,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    is_crypto = "CoinDCX" in market
    df_ltf = fetch_data_for_gap_scan(
        ticker, cfg.ltf, market, groww_token, exchange, limit=cfg.lookback_bars,
    )
    df_ltf = normalize_ohlcv(df_ltf)
    if df_ltf.empty or len(df_ltf) < cfg.min_bars:
        df_ltf = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, cfg.ltf, is_crypto=is_crypto, limit=cfg.lookback_bars, market=market),
        )

    df_htf = fetch_data_for_gap_scan(
        ticker, cfg.htf, market, groww_token, exchange, limit=max(120, cfg.lookback_bars // 4),
    )
    df_htf = normalize_ohlcv(df_htf)
    if df_htf.empty:
        df_htf = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, cfg.htf, is_crypto=is_crypto, limit=max(120, cfg.lookback_bars // 4), market=market),
        )

    return df_ltf, df_htf


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: CrtFvgConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or CrtFvgConfig()
    df_ltf, df_htf = fetch_exec_data(ticker, market, cfg, groww_token=groww_token, exchange=exchange)
    if df_ltf.empty or len(df_ltf) < cfg.min_bars:
        return {"ticker": ticker, "error": f"Insufficient {cfg.ltf} data."}
    if df_htf.empty:
        return {"ticker": ticker, "error": f"Insufficient {cfg.htf} data."}

    pipeline = run_crt_fvg_pipeline(df_ltf, df_htf, cfg)
    if pipeline.get("error"):
        return {"ticker": ticker, "error": pipeline["error"]}

    live = evaluate_live_signal(pipeline, cfg)

    return {
        "ticker": ticker,
        "market": market,
        "htf": cfg.htf,
        "ltf": cfg.ltf,
        "bars_htf": len(pipeline["df_htf"]),
        "bars_ltf": len(pipeline["df_ltf"]),
        "last_close": float(pipeline["df_ltf"]["close"].iloc[-1]),
        "signal_history": _signal_history(pipeline["df_htf"]),
        "live": live,
    }


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: CrtFvgConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or CrtFvgConfig()
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
        "htf": cfg.htf,
        "ltf": cfg.ltf,
        "results": results,
        "entries": entries,
        "watchlist": watches,
        "entry_count": len(entries),
        "watch_count": len(watches),
    }
