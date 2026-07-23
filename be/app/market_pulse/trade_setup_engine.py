"""
trade_setup_engine.py
------------------------
Command Center — Trade Setup: Oversold / Overbought screener across
Groww (India), Crypto, Commodities, and US stocks.

For each ticker and each selected timeframe, computes RSI(14) on that
timeframe's own OHLCV (reusing momentum_engine's indicator pipeline so the
RSI zone matches the Momentum section exactly), then buckets the ticker into
one of 5 categories per timeframe: Extended Overbought, Overbought, Neutral,
Oversold, Extended Oversold.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.momentum_engine import DEFAULT_TIMEFRAMES, MomentumConfig, TIMEFRAME_OPTIONS, analyze_timeframe
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_TIMEFRAMES",
    "TIMEFRAME_OPTIONS",
    "BUCKET_ORDER",
    "analyze_trade_setup_one",
    "analyze_trade_setup_many",
    "group_by_timeframe_bucket",
    "analyze_patterns_one",
    "analyze_support_resistance_one",
    "analyze_smart_money_one",
    "analyze_scalping_confluence_one",
    "analyze_time_series_one",
    "analyze_divergence_one",
    "analyze_stop_hunt_one",
    "analyze_take_profit_one",
    "analyze_real_bottom_one",
    "analyze_intra_hwp_one",
    "analyze_weak_strong_one",
    "analyze_copy_trade_one",
    "analyze_sma_20_200_one",
]

BUCKET_ORDER = ["Extended Overbought", "Overbought", "Neutral", "Oversold", "Extended Oversold"]

_ZONE_TO_BUCKET = {
    "Extended overbought": "Extended Overbought",
    "Overbought": "Overbought",
    "Bullish": "Neutral",
    "Neutral": "Neutral",
    "Bearish": "Neutral",
    "Oversold": "Oversold",
    "Extended oversold": "Extended Oversold",
}


def _fetch_ohlcv(
    ticker: str, market: str, timeframe: str, cfg: MomentumConfig, *, groww_token: str, exchange: str,
) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    df = fetch_data_for_gap_scan(ticker, timeframe, market, groww_token, exchange, limit=cfg.lookback_bars)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < cfg.min_bars:
        df = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, timeframe, is_crypto=is_crypto, limit=cfg.lookback_bars, market=market),
        )
    return df


def analyze_trade_setup_one(
    ticker: str, timeframes: list[str], market: str, *, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    """One ticker: RSI + zone/bucket independently per selected timeframe."""
    cfg = MomentumConfig(timeframes=timeframes)
    per_tf: dict[str, dict[str, Any]] = {}

    for tf in timeframes:
        try:
            df = _fetch_ohlcv(ticker, market, tf, cfg, groww_token=groww_token, exchange=exchange)
        except Exception as exc:
            logger.debug("Trade Setup OHLCV fetch failed for %s %s: %s", ticker, tf, exc)
            continue
        try:
            res = analyze_timeframe(df, tf, cfg)
        except Exception as exc:
            logger.debug("Trade Setup RSI compute failed for %s %s: %s", ticker, tf, exc)
            continue
        if not res:
            continue
        per_tf[tf] = {
            "timeframe": tf,
            "price": res["price"],
            "rsi": res["rsi"],
            "rsi_zone": res["rsi_zone"],
            "bucket": _ZONE_TO_BUCKET.get(res["rsi_zone"], "Neutral"),
            "trend_direction": res["trend_direction"],
            "volume_ratio": res["volume_ratio"],
        }

    if not per_tf:
        return {"ticker": ticker, "market": market, "error": f"Insufficient data across {', '.join(timeframes)}."}

    return {"ticker": ticker, "market": market, "per_tf": per_tf}


def analyze_trade_setup_many(
    tickers: list[str], timeframes: list[str], market: str, *, groww_token: str = "", exchange: str = "NSE",
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for ticker in tickers:
        try:
            results.append(analyze_trade_setup_one(
                ticker, timeframes, market, groww_token=groww_token, exchange=exchange,
            ))
        except Exception as exc:
            logger.debug("Trade Setup failed for %s: %s", ticker, exc)
            results.append({"ticker": ticker, "market": market, "error": str(exc)[:200]})
    return results


def group_by_timeframe_bucket(
    results: list[dict[str, Any]], timeframes: list[str],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Reshape [{ticker, per_tf: {tf: {...}}}] into {tf: {bucket: [ticker entries]}},
    sorted so the most extreme RSI reading in each bucket surfaces first."""
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {
        tf: {b: [] for b in BUCKET_ORDER} for tf in timeframes
    }
    for r in results:
        if r.get("error"):
            continue
        for tf, entry in (r.get("per_tf") or {}).items():
            if tf not in grouped:
                grouped[tf] = {b: [] for b in BUCKET_ORDER}
            grouped[tf][entry["bucket"]].append({"ticker": r["ticker"], **entry})

    for buckets in grouped.values():
        for bucket, items in buckets.items():
            reverse = bucket in ("Extended Overbought", "Overbought")
            items.sort(key=lambda e: e["rsi"] if e["rsi"] is not None else 50.0, reverse=reverse)

    return grouped


# --- Per-ticker "further analysis" drill-down (Trade Setup expander checkboxes) ---
# These four mirror the source's inline drill-down blocks — each combines a handful
# of already-built strategy engines for a single ticker/timeframe on demand, rather
# than running across the whole screened universe.

def analyze_patterns_one(
    ticker: str, timeframe: str, market: str, *, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    """Candlestick + chart pattern scan on one ticker/timeframe."""
    from app.market_pulse.pattern_breakout_tab import detect_extended_chart_patterns
    from app.market_pulse.price_action import detect_candlestick_patterns, detect_chart_patterns

    cfg = MomentumConfig(timeframes=[timeframe])
    try:
        df = _fetch_ohlcv(ticker, market, timeframe, cfg, groww_token=groww_token, exchange=exchange)
        return {
            "ticker": ticker, "market": market, "timeframe": timeframe,
            "candles": detect_candlestick_patterns(df),
            "charts": detect_chart_patterns(df) + detect_extended_chart_patterns(df),
        }
    except Exception as exc:
        logger.debug("Trade Setup pattern scan failed for %s %s: %s", ticker, timeframe, exc)
        return {"ticker": ticker, "market": market, "timeframe": timeframe, "error": str(exc)[:200]}


def analyze_support_resistance_one(
    ticker: str, timeframe: str, market: str, *, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    """Support/Resistance levels + breakout/breakdown check on one ticker/timeframe."""
    from app.market_pulse.price_action import detect_support_resistance
    from app.market_pulse.quick_analyzer_engine import detect_breakout_breakdown

    cfg = MomentumConfig(timeframes=[timeframe])
    try:
        df = _fetch_ohlcv(ticker, market, timeframe, cfg, groww_token=groww_token, exchange=exchange)
        return {
            "ticker": ticker, "market": market, "timeframe": timeframe,
            "sr": detect_support_resistance(df),
            "breakout": detect_breakout_breakdown(df),
            "price": float(df["close"].iloc[-1]) if not df.empty else None,
        }
    except Exception as exc:
        logger.debug("Trade Setup S/R scan failed for %s %s: %s", ticker, timeframe, exc)
        return {"ticker": ticker, "market": market, "timeframe": timeframe, "error": str(exc)[:200]}


def analyze_smart_money_one(
    ticker: str, timeframe: str, market: str, *, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    """Smart Money combo: TTG Sniper Entry + CISD Entry Rule + MTF Day Plan, combined
    via confluence voting (2-of-3 agreement at 65%+ confidence to TAKE)."""
    from app.market_pulse.one_click_common import STRICT, combine_confluence, vote_from_live_schema
    from app.trading_hubs.smc_cisd_engine import TF_OPTIONS as CISD_TF_OPTIONS
    from app.trading_hubs.smc_cisd_engine import CISDConfig
    from app.trading_hubs.smc_cisd_engine import analyze_ticker as cisd_analyze_ticker
    from app.trading_hubs.smc_mtf_day_plan_engine import analyze_ticker as dayplan_analyze_ticker
    from app.trading_hubs.smc_ttg_sniper_engine import HTF_OPTIONS as TTG_HTF_OPTIONS
    from app.trading_hubs.smc_ttg_sniper_engine import LTF_OPTIONS as TTG_LTF_OPTIONS
    from app.trading_hubs.smc_ttg_sniper_engine import TTGSniperConfig
    from app.trading_hubs.smc_ttg_sniper_engine import analyze_ticker as ttg_analyze_ticker

    try:
        ttg_cfg = (
            TTGSniperConfig(ltf=timeframe) if timeframe in TTG_LTF_OPTIONS
            else TTGSniperConfig(htf=timeframe) if timeframe in TTG_HTF_OPTIONS
            else TTGSniperConfig()
        )
        cisd_cfg = CISDConfig(execution_tf=timeframe) if timeframe in CISD_TF_OPTIONS else CISDConfig()

        ttg_res = ttg_analyze_ticker(ticker, market, cfg=ttg_cfg, groww_token=groww_token, exchange=exchange)
        cisd_res = cisd_analyze_ticker(ticker, market, cfg=cisd_cfg, groww_token=groww_token, exchange=exchange)
        # MTF Day Plan is an intraday-only tool (fixed HTF/MTF/LTF triple) — run with its
        # own defaults regardless of the timeframe the ticker was screened on.
        dayplan_res = dayplan_analyze_ticker(ticker, market, groww_token=groww_token, exchange=exchange)

        votes = [
            vote_from_live_schema("SM — TTG Sniper Entry", ttg_res),
            vote_from_live_schema("SMC — CISD Entry Rule", cisd_res),
            vote_from_live_schema("SMC — MTF Day Plan", dayplan_res),
        ]
        combo = combine_confluence(
            votes, strictness=STRICT,
            min_agree_strict=2, min_agree_loose=1,
            take_threshold_strict=65.0, take_threshold_loose=55.0,
        )
        return {"ticker": ticker, "market": market, "timeframe": timeframe, "combo": combo}
    except Exception as exc:
        logger.debug("Trade Setup smart money scan failed for %s %s: %s", ticker, timeframe, exc)
        return {"ticker": ticker, "market": market, "timeframe": timeframe, "error": str(exc)[:200]}


def analyze_scalping_confluence_one(
    ticker: str, timeframe: str, market: str, *, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    """Scalping combo: Rectangle Setup + SMC Rule of Three (CRT-FVG) + ARC Method +
    A+ S/R MSS, combined via confluence voting (2-of-4 agreement at 65%+ confidence)."""
    from app.market_pulse.one_click_common import STRICT, combine_confluence, vote_from_live_schema
    from app.trading_hubs.scalp_arc_engine import ArcConfig
    from app.trading_hubs.scalp_arc_engine import analyze_ticker as arc_analyze_ticker
    from app.trading_hubs.scalp_crt_fvg_engine import HTF_OPTIONS as CRT_HTF_OPTIONS
    from app.trading_hubs.scalp_crt_fvg_engine import LTF_OPTIONS as CRT_LTF_OPTIONS
    from app.trading_hubs.scalp_crt_fvg_engine import CrtFvgConfig
    from app.trading_hubs.scalp_crt_fvg_engine import analyze_ticker as crtfvg_analyze_ticker
    from app.trading_hubs.scalp_rectangle_engine import RectangleConfig
    from app.trading_hubs.scalp_rectangle_engine import analyze_ticker as rectangle_analyze_ticker
    from app.trading_hubs.scalp_sr_mss_engine import HTF_OPTIONS as SRMSS_HTF_OPTIONS
    from app.trading_hubs.scalp_sr_mss_engine import SrMssConfig
    from app.trading_hubs.scalp_sr_mss_engine import analyze_ticker as srmss_analyze_ticker

    try:
        # Rectangle Setup is a fixed 1m sniper tool — always run at its own default.
        rect_cfg = RectangleConfig()
        crt_cfg = (
            CrtFvgConfig(ltf=timeframe) if timeframe in CRT_LTF_OPTIONS
            else CrtFvgConfig(htf=timeframe) if timeframe in CRT_HTF_OPTIONS
            else CrtFvgConfig()
        )
        arc_cfg = ArcConfig(execution_tf=timeframe) if timeframe in ("1m", "5m") else ArcConfig()
        # A+ S/R MSS's execution TF is fixed by design — only its HTF S/R reference is configurable.
        srmss_cfg = SrMssConfig(htf=timeframe) if timeframe in SRMSS_HTF_OPTIONS else SrMssConfig()

        rect_res = rectangle_analyze_ticker(ticker, market, cfg=rect_cfg, groww_token=groww_token, exchange=exchange)
        crt_res = crtfvg_analyze_ticker(ticker, market, cfg=crt_cfg, groww_token=groww_token, exchange=exchange)
        arc_res = arc_analyze_ticker(ticker, market, cfg=arc_cfg, groww_token=groww_token, exchange=exchange)
        srmss_res = srmss_analyze_ticker(ticker, market, cfg=srmss_cfg, groww_token=groww_token, exchange=exchange)

        votes = [
            vote_from_live_schema("Rectangle Setup", rect_res),
            vote_from_live_schema("SMC Rule of Three", crt_res),
            vote_from_live_schema("ARC Method", arc_res),
            vote_from_live_schema("A+ S/R MSS (Joovier)", srmss_res),
        ]
        combo = combine_confluence(
            votes, strictness=STRICT,
            min_agree_strict=2, min_agree_loose=1,
            take_threshold_strict=65.0, take_threshold_loose=55.0,
        )
        return {"ticker": ticker, "market": market, "timeframe": timeframe, "combo": combo}
    except Exception as exc:
        logger.debug("Trade Setup scalping scan failed for %s %s: %s", ticker, timeframe, exc)
        return {"ticker": ticker, "market": market, "timeframe": timeframe, "error": str(exc)[:200]}


_TS_ENGINE_MA_CROSS = "MA Crossover (Golden/Death Cross)"
_TS_ENGINE_BOLLINGER = "Mean Reversion (Bollinger Bands)"
_TS_ENGINE_BREAKOUT = "Momentum Breakout"
_TS_FAST_SMA = 50
_TS_SLOW_SMA = 200
_TS_BB_PERIOD = 20
_TS_BB_STD = 2.0
_TS_BREAKOUT_WINDOW = 5
_TS_BREAKOUT_NUM_LEVELS = 3
_TS_BREAKOUT_LOOKBACK = 5
_TS_RR_RATIO = 2.0
_TS_TAKE_THRESHOLD = 65.0
_TS_LOOKBACK_BARS = 500
_TS_MIN_BARS = 210


def _ts_ma_crossover_vote(df: pd.DataFrame, timeframe: str) -> Any:
    from app.market_pulse.indicators import add_sma
    from app.market_pulse.one_click_common import Vote

    work = add_sma(df.copy(), _TS_FAST_SMA)
    work = add_sma(work, _TS_SLOW_SMA)
    fast_col, slow_col = f"sma_{_TS_FAST_SMA}", f"sma_{_TS_SLOW_SMA}"

    if len(work) < _TS_SLOW_SMA + 2 or pd.isna(work[slow_col].iloc[-1]) or pd.isna(work[slow_col].iloc[-2]):
        return Vote(engine=_TS_ENGINE_MA_CROSS, direction="WAIT", confidence=0.0, take=False,
                     error=f"Insufficient {timeframe} bars for the {_TS_SLOW_SMA}-period SMA.")

    price = float(work["close"].iloc[-1])
    curr_diff = float(work[fast_col].iloc[-1] - work[slow_col].iloc[-1])
    prev_diff = float(work[fast_col].iloc[-2] - work[slow_col].iloc[-2])
    fresh_golden = prev_diff <= 0 < curr_diff
    fresh_death = prev_diff >= 0 > curr_diff

    if fresh_golden:
        direction, confidence = "LONG", 82.0
        reason = (
            f"🌟 Golden Cross just fired — the {_TS_FAST_SMA}-period SMA crossed above the "
            f"{_TS_SLOW_SMA}-period SMA on the latest {timeframe} bar, the classic long-term bullish trend signal."
        )
    elif fresh_death:
        direction, confidence = "SHORT", 82.0
        reason = (
            f"☠️ Death Cross just fired — the {_TS_FAST_SMA}-period SMA crossed below the "
            f"{_TS_SLOW_SMA}-period SMA on the latest {timeframe} bar, the classic long-term bearish trend signal."
        )
    elif curr_diff > 0:
        direction, confidence = "LONG", 58.0
        reason = (
            f"{_TS_FAST_SMA}-period SMA has been sitting above the {_TS_SLOW_SMA}-period SMA (bullish stack) "
            f"on {timeframe} — an established uptrend, but no fresh cross today."
        )
    else:
        direction, confidence = "SHORT", 58.0
        reason = (
            f"{_TS_FAST_SMA}-period SMA has been sitting below the {_TS_SLOW_SMA}-period SMA (bearish stack) "
            f"on {timeframe} — an established downtrend, but no fresh cross today."
        )

    slow_sma_val = float(work[slow_col].iloc[-1])
    sl = slow_sma_val * (0.99 if direction == "LONG" else 1.01)
    risk = (price - sl) if direction == "LONG" else (sl - price)
    if risk <= 0:
        sl = tp1 = None
    else:
        tp1 = price + risk * _TS_RR_RATIO if direction == "LONG" else price - risk * _TS_RR_RATIO
        if tp1 <= 0:
            sl = tp1 = None

    take = confidence >= _TS_TAKE_THRESHOLD
    return Vote(
        engine=_TS_ENGINE_MA_CROSS, direction=direction, confidence=confidence, take=take,
        entry=price, sl=round(sl, 6) if sl else None, tp1=round(tp1, 6) if tp1 else None,
        tp2=round(tp1, 6) if tp1 else None, reasons=[reason],
    )


def _ts_bollinger_vote(df: pd.DataFrame) -> Any:
    from app.market_pulse.indicators import add_bollinger_bands
    from app.market_pulse.one_click_common import Vote

    work = add_bollinger_bands(df.copy(), _TS_BB_PERIOD, _TS_BB_STD)
    upper_col = f"bb_upper_{_TS_BB_PERIOD}_{_TS_BB_STD}"
    lower_col = f"bb_lower_{_TS_BB_PERIOD}_{_TS_BB_STD}"
    mid_col = f"bb_middle_{_TS_BB_PERIOD}_{_TS_BB_STD}"

    if len(work) < _TS_BB_PERIOD + 2 or pd.isna(work[upper_col].iloc[-1]):
        return Vote(engine=_TS_ENGINE_BOLLINGER, direction="WAIT", confidence=0.0, take=False,
                     error=f"Insufficient bars for the {_TS_BB_PERIOD}-period Bollinger Bands.")

    price = float(work["close"].iloc[-1])
    upper = float(work[upper_col].iloc[-1])
    lower = float(work[lower_col].iloc[-1])
    mid = float(work[mid_col].iloc[-1])
    band_width = upper - lower

    if price < lower:
        pct = ((lower - price) / band_width * 100) if band_width else 0.0
        direction, confidence = "LONG", min(90.0, 60.0 + pct * 1.5)
        reason = (
            f"Price ({price:,.4g}) is below the lower Bollinger Band ({lower:,.4g}) — "
            f"{pct:.1f}% beyond the band, an oversold extension theory says should mean-revert."
        )
        sl, tp1 = price * 0.98, mid
    elif price > upper:
        pct = ((price - upper) / band_width * 100) if band_width else 0.0
        direction, confidence = "SHORT", min(90.0, 60.0 + pct * 1.5)
        reason = (
            f"Price ({price:,.4g}) is above the upper Bollinger Band ({upper:,.4g}) — "
            f"{pct:.1f}% beyond the band, an overbought extension theory says should mean-revert."
        )
        sl, tp1 = price * 1.02, mid
    else:
        direction, confidence = "WAIT", 0.0
        reason = f"Price ({price:,.4g}) is inside the Bollinger Bands ({lower:,.4g} – {upper:,.4g}) — no mean-reversion extreme right now."
        sl = tp1 = None

    take = direction in ("LONG", "SHORT") and confidence >= _TS_TAKE_THRESHOLD
    return Vote(
        engine=_TS_ENGINE_BOLLINGER, direction=direction, confidence=round(confidence, 1), take=take,
        entry=price if direction != "WAIT" else None,
        sl=round(sl, 6) if sl else None, tp1=round(tp1, 6) if tp1 else None,
        tp2=round(tp1, 6) if tp1 else None, reasons=[reason],
    )


def _ts_breakout_vote(df: pd.DataFrame) -> Any:
    from app.market_pulse.one_click_common import Vote
    from app.market_pulse.quick_analyzer_engine import detect_breakout_breakdown

    bo = detect_breakout_breakdown(
        df, window=_TS_BREAKOUT_WINDOW, num_levels=_TS_BREAKOUT_NUM_LEVELS, breakout_lookback=_TS_BREAKOUT_LOOKBACK,
    )
    event = bo.get("event", "NONE")
    price = float(df["close"].iloc[-1]) if not df.empty else None

    if event == "NONE" or price is None:
        return Vote(
            engine=_TS_ENGINE_BREAKOUT, direction="WAIT", confidence=0.0, take=False,
            reasons=["No fresh breakout above resistance or breakdown below support in the recent range."],
        )

    level = bo.get("level") or {}
    lvl_price = level.get("price")
    vol_confirmed = bool(bo.get("volume_confirmed"))
    confidence = 78.0 if vol_confirmed else 55.0
    vol_note = "confirmed by above-average volume (≥1.15× 20-bar average)" if vol_confirmed else "not yet confirmed by volume — watch for follow-through"

    if event == "RESISTANCE_BREAKOUT":
        direction = "LONG"
        reason = f"Price closed above resistance {lvl_price:,.4g} — breakout {vol_note}."
        sl = lvl_price * 0.99 if lvl_price else price * 0.97
        risk = price - sl
        tp1 = price + risk * _TS_RR_RATIO if risk > 0 else None
    else:  # SUPPORT_BREAKDOWN
        direction = "SHORT"
        reason = f"Price closed below support {lvl_price:,.4g} — breakdown {vol_note}."
        sl = lvl_price * 1.01 if lvl_price else price * 1.03
        risk = sl - price
        tp1 = price - risk * _TS_RR_RATIO if risk > 0 else None

    if tp1 is not None and tp1 <= 0:
        sl = tp1 = None

    take = confidence >= _TS_TAKE_THRESHOLD
    return Vote(
        engine=_TS_ENGINE_BREAKOUT, direction=direction, confidence=confidence, take=take,
        entry=price, sl=round(sl, 6), tp1=round(tp1, 6) if tp1 else None,
        tp2=round(tp1, 6) if tp1 else None, reasons=[reason],
    )


def analyze_time_series_one(
    ticker: str, timeframe: str, market: str, *, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    """Time Series combo: MA Crossover (Golden/Death Cross) + Bollinger Mean Reversion +
    Momentum Breakout, combined via confluence voting (2-of-3 agreement at 65%+ confidence)."""
    from app.market_pulse.one_click_common import STRICT, combine_confluence

    cfg = MomentumConfig(timeframes=[timeframe], lookback_bars=_TS_LOOKBACK_BARS, min_bars=_TS_MIN_BARS)
    try:
        df = _fetch_ohlcv(ticker, market, timeframe, cfg, groww_token=groww_token, exchange=exchange)
        if df.empty or len(df) < _TS_MIN_BARS:
            return {
                "ticker": ticker, "market": market, "timeframe": timeframe,
                "error": f"Insufficient {timeframe} data ({len(df)} bars, need {_TS_MIN_BARS}+ for the {_TS_SLOW_SMA}-period SMA).",
            }

        votes = [
            _ts_ma_crossover_vote(df, timeframe),
            _ts_bollinger_vote(df),
            _ts_breakout_vote(df),
        ]
        combo = combine_confluence(
            votes, strictness=STRICT,
            min_agree_strict=2, min_agree_loose=1,
            take_threshold_strict=_TS_TAKE_THRESHOLD, take_threshold_loose=50.0,
        )
        return {
            "ticker": ticker, "market": market, "timeframe": timeframe,
            "price": float(df["close"].iloc[-1]), "bars": len(df), "combo": combo,
        }
    except Exception as exc:
        logger.debug("Trade Setup time series scan failed for %s %s: %s", ticker, timeframe, exc)
        return {"ticker": ticker, "market": market, "timeframe": timeframe, "error": str(exc)[:200]}


def analyze_divergence_one(
    ticker: str, timeframe: str, market: str, *, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    """Divergences: Price vs RSI and Price vs Volume (OBV), comparing the last two
    swing lows/highs — bullish (positive) when price falls but the oscillator rises,
    bearish (negative) when price rises but the oscillator falls."""
    from app.market_pulse.divergence_engine import analyze_ticker as divergence_analyze_ticker

    return divergence_analyze_ticker(ticker, timeframe, market, groww_token=groww_token, exchange=exchange)


def analyze_stop_hunt_one(
    ticker: str, timeframe: str, market: str, *, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    """Stop Loss Hunting: detects an active/likely liquidity sweep and recommends
    hunt-resistant stop-loss levels (price + % from current price) for both a LONG
    and a SHORT scenario, anchored beyond the sweep wick / strong S/R / structural
    swing level, ATR-scaled, and nudged off nearby round numbers."""
    from app.market_pulse.stop_hunt_engine import analyze_ticker as stop_hunt_analyze_ticker

    return stop_hunt_analyze_ticker(ticker, timeframe, market, groww_token=groww_token, exchange=exchange)


def analyze_take_profit_one(
    ticker: str, timeframe: str, market: str, *, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    """Take Profit Targets: combines S/R strength, chart-pattern measured moves,
    Fibonacci extensions, and SMC liquidity draw into two-tier (TP1 conservative,
    TP2 extended) profit targets — price + % from current price — for both a LONG
    and a SHORT scenario."""
    from app.market_pulse.take_profit_engine import analyze_ticker as take_profit_analyze_ticker

    return take_profit_analyze_ticker(ticker, timeframe, market, groww_token=groww_token, exchange=exchange)


def analyze_real_bottom_one(
    ticker: str, timeframe: str, market: str, *, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    """Real Bottom: the 5-step mechanical sequence (absorption → retest → trap →
    displacement → entry) for identifying genuine market bottoms vs fake ones,
    anchored on smc_liquidity_engine sweep/grab/FVG detection and a bullish
    trigger-candle confirmation for the final entry."""
    from app.market_pulse.real_bottom_engine import analyze_ticker as real_bottom_analyze_ticker

    return real_bottom_analyze_ticker(ticker, timeframe, market, groww_token=groww_token, exchange=exchange)


def analyze_intra_hwp_one(
    ticker: str, timeframe: str, market: str, *, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    """Intra HWP — Two-Sided Gap Fill + 21 EMA: waits for price to tag the
    previous day's close (Side 1 of the gap), then enters on the 5m 21-EMA
    cross-back toward today's open (Side 2). Always evaluated on a fixed 5m
    timeframe regardless of the passed-in timeframe — per the strategy's own
    definition, the same convention used elsewhere in this app for fixed-TF
    composites."""
    from app.trading_hubs.intra_hwp_engine import HwpConfig
    from app.trading_hubs.intra_hwp_engine import analyze_ticker as hwp_analyze_ticker

    return hwp_analyze_ticker(ticker, market, cfg=HwpConfig(), groww_token=groww_token, exchange=exchange)


def analyze_weak_strong_one(
    ticker: str, timeframe: str, market: str, *, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    """Weak / Strong: six-factor relative-strength & trend-confluence
    classifier (trend structure, EMA stack, ADX/DI, RSI, MACD histogram, and
    relative strength vs. a market benchmark) — buckets the ticker as STRONG,
    WEAK, or NEUTRAL with paired scalping and swing playbooks."""
    from app.market_pulse.weak_strong_engine import WeakStrongConfig
    from app.market_pulse.weak_strong_engine import analyze_ticker as weak_strong_analyze_ticker

    return weak_strong_analyze_ticker(ticker, market, timeframe, cfg=WeakStrongConfig(), groww_token=groww_token, exchange=exchange)


def analyze_sma_20_200_one(
    ticker: str, timeframe: str, market: str, *, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    """200SMA-20SMA — Bounce & Rejection: mechanical trend-following strategy —
    price above/below the 200 SMA sets the trend bias, and a bounce (long) or
    rejection (short) off the 20 SMA (wick through, close back on the trend
    side) triggers entry with a fixed 1:2 stop/target."""
    from app.market_pulse.sma_20_200_engine import Sma20200Config
    from app.market_pulse.sma_20_200_engine import analyze_ticker as sma_20_200_analyze_ticker

    return sma_20_200_analyze_ticker(ticker, market, timeframe, cfg=Sma20200Config(), groww_token=groww_token, exchange=exchange)


def analyze_copy_trade_one(
    ticker: str, timeframe: str, market: str, *, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    """Copy Trade — high-beta / 3x leveraged ETF momentum scalp: Stochastic
    %K 80/20 'sweet spot' confirmed by a fresh Engulfing candle on
    above-average volume, exiting the instant momentum pulls back. Always
    evaluated on a fixed 15m timeframe regardless of the passed-in
    timeframe — per the strategy's own definition, the same convention used
    elsewhere in this app for fixed-TF composites."""
    from app.market_pulse.copy_trade_engine import CopyTradeConfig
    from app.market_pulse.copy_trade_engine import analyze_ticker as copy_trade_analyze_ticker

    return copy_trade_analyze_ticker(ticker, market, cfg=CopyTradeConfig(), groww_token=groww_token, exchange=exchange)
