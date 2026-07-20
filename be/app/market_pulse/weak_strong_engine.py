"""
weak_strong_engine.py
----------------------
Multi-factor relative-strength & trend-confluence classifier.

For a chosen ticker + timeframe, blends seven structurally-independent reads —
trend structure (HH/HL vs LH/LL), EMA stack alignment, ADX/DI trend strength
and direction, RSI momentum, MACD histogram momentum, volume (relative-volume
conviction on the current bar plus OBV accumulation/distribution trend), and
relative strength vs. a market benchmark (Nifty 50 / SPY / BTC) — into a
single -100..+100 "strength score", then buckets the ticker as STRONG, WEAK,
or NEUTRAL.

Every STRONG/WEAK verdict is paired with two independent, ready-to-use trade
playbooks:
  - Scalping: fast pullback-to-EMA entry on the SAME chosen timeframe,
    tight ATR stop, same-session target — for traders who want to ride the
    strength/weakness intraday.
  - Swing: pullback-to-EMA entry using DAILY data (always fetched fresh,
    regardless of the chosen timeframe, since a swing hold is inherently a
    daily-context decision), wider structural stop, multi-day/week target.

NEUTRAL tickers get a WAIT verdict on both playbooks — no forced trade.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.indicators import add_adx, add_atr, add_ema, add_macd, add_obv, add_rsi, add_vol_sma
from app.trading_hubs.intraday_shared import enrich_intra_live
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.price_extremes import _find_swing_points, classify_swing_structure
from app.market_pulse.run_summary import make_trade_plan
from app.market_pulse.ticker_utils import is_crypto_market, is_us_market

TIMEFRAME_OPTIONS = ["5m", "15m", "1h", "4h", "1d", "1w"]

_MIN_BARS = 60
_SWING_HOLD = "Multi-day to multi-week swing — trail stop with EMA once RR ≥ 1"
_SCALP_HOLD = "Same session — intraday scalp, exit by session close or on target"


@dataclass
class WeakStrongConfig:
    ema_fast: int = 9
    ema_mid: int = 21
    ema_slow: int = 50
    rsi_period: int = 14
    adx_period: int = 14
    atr_period: int = 14
    swing_window: int = 5
    rs_lookback_bars: int = 20
    vol_sma_period: int = 20
    vol_obv_lookback: int = 10
    vol_ratio_threshold: float = 1.3
    strong_threshold: float = 35.0
    weak_threshold: float = -35.0
    take_confidence_threshold: float = 55.0


def _benchmark_symbol(market: str) -> tuple[str, bool]:
    if is_crypto_market(market):
        return "BTC", True
    if is_us_market(market):
        return "SPY", False
    return "NIFTY 50", False


def _fetch_ohlcv(
    ticker: str, market: str, timeframe: str, *,
    groww_token: str = "", exchange: str = "NSE", limit: int = 300,
) -> pd.DataFrame:
    df = fetch_data_for_gap_scan(ticker, timeframe, market, groww_token, exchange, limit=limit)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < _MIN_BARS:
        is_crypto = is_crypto_market(market)
        df = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, timeframe, is_crypto=is_crypto, limit=limit, market=market)
        )
    return df


def _fetch_benchmark_ohlcv(market: str, timeframe: str, *, limit: int = 300) -> pd.DataFrame:
    sym, is_crypto = _benchmark_symbol(market)
    return normalize_ohlcv(
        fetch_ohlcv_yfinance(sym, timeframe, is_crypto=is_crypto, limit=limit, market=market)
    )


def _score_ticker(df: pd.DataFrame, bench_df: pd.DataFrame | None, cfg: WeakStrongConfig) -> dict | None:
    work = df.copy()
    work = add_ema(work, cfg.ema_fast)
    work = add_ema(work, cfg.ema_mid)
    work = add_ema(work, cfg.ema_slow)
    work = add_rsi(work, cfg.rsi_period)
    work = add_adx(work, cfg.adx_period)
    work = add_macd(work)
    work = add_atr(work, cfg.atr_period)
    has_volume = "volume" in work.columns and work["volume"].fillna(0).gt(0).any()
    if has_volume:
        work = add_obv(work)
        work = add_vol_sma(work, cfg.vol_sma_period)
    work = work.dropna(subset=[f"ema_{cfg.ema_slow}", f"adx_{cfg.adx_period}"])
    if work.empty:
        return None

    last = work.iloc[-1]
    price = float(last["close"])
    ema_f = float(last[f"ema_{cfg.ema_fast}"])
    ema_m = float(last[f"ema_{cfg.ema_mid}"])
    ema_s = float(last[f"ema_{cfg.ema_slow}"])
    rsi = float(last[f"rsi_{cfg.rsi_period}"])
    adx = float(last[f"adx_{cfg.adx_period}"])
    plus_di = float(last[f"plus_di_{cfg.adx_period}"])
    minus_di = float(last[f"minus_di_{cfg.adx_period}"])
    macd_hist_col = "macd_hist_12_26_9"
    macd_hist = float(last[macd_hist_col])
    macd_hist_prev = float(work[macd_hist_col].iloc[-2]) if len(work) > 1 else macd_hist

    vol_ratio = None
    obv_trend = None
    if has_volume:
        vol_ratio_col = f"vol_ratio_{cfg.vol_sma_period}"
        if vol_ratio_col in work.columns and pd.notna(last[vol_ratio_col]):
            vol_ratio = float(last[vol_ratio_col])
        obv_lookback = min(cfg.vol_obv_lookback, len(work) - 1)
        if "obv" in work.columns and obv_lookback > 0:
            obv_now = float(work["obv"].iloc[-1])
            obv_prev = float(work["obv"].iloc[-1 - obv_lookback])
            if obv_now > obv_prev:
                obv_trend = "rising"
            elif obv_now < obv_prev:
                obv_trend = "falling"
            else:
                obv_trend = "flat"

    reasons: list[str] = []
    score = 0.0

    structure = classify_swing_structure(df, window=cfg.swing_window)
    bias = structure.get("structure_bias")
    if bias == "bullish":
        score += 25
        reasons.append(f"Trend structure: {structure['structure_name']} ({structure['high_label']}/{structure['low_label']}) — bullish")
    elif bias == "bearish":
        score -= 25
        reasons.append(f"Trend structure: {structure['structure_name']} ({structure['high_label']}/{structure['low_label']}) — bearish")
    else:
        reasons.append(f"Trend structure: {structure['structure_name']} — mixed/unclear")

    if price > ema_f > ema_m > ema_s:
        score += 20
        reasons.append(f"Price above rising EMA stack ({cfg.ema_fast}>{cfg.ema_mid}>{cfg.ema_slow}) — bullish alignment")
    elif price < ema_f < ema_m < ema_s:
        score -= 20
        reasons.append(f"Price below falling EMA stack ({cfg.ema_fast}<{cfg.ema_mid}<{cfg.ema_slow}) — bearish alignment")
    elif price > ema_m:
        score += 8
        reasons.append(f"Price above {cfg.ema_mid} EMA but stack not fully aligned — mild bullish")
    elif price < ema_m:
        score -= 8
        reasons.append(f"Price below {cfg.ema_mid} EMA but stack not fully aligned — mild bearish")

    if adx >= 20:
        strength_scale = min(1.0, adx / 40.0)
        if plus_di > minus_di:
            score += 20 * strength_scale
            reasons.append(f"ADX {adx:.1f} with +DI({plus_di:.1f}) > -DI({minus_di:.1f}) — trending up")
        elif minus_di > plus_di:
            score -= 20 * strength_scale
            reasons.append(f"ADX {adx:.1f} with -DI({minus_di:.1f}) > +DI({plus_di:.1f}) — trending down")
    else:
        reasons.append(f"ADX {adx:.1f} — no strong directional trend yet")

    if rsi >= 55:
        score += 15 if rsi < 70 else 8
        reasons.append(f"RSI({cfg.rsi_period}) {rsi:.1f} — bullish momentum" + (" (approaching overbought)" if rsi >= 70 else ""))
    elif rsi <= 45:
        score -= 15 if rsi > 30 else 8
        reasons.append(f"RSI({cfg.rsi_period}) {rsi:.1f} — bearish momentum" + (" (approaching oversold)" if rsi <= 30 else ""))
    else:
        reasons.append(f"RSI({cfg.rsi_period}) {rsi:.1f} — neutral momentum")

    if macd_hist > 0 and macd_hist >= macd_hist_prev:
        score += 10
        reasons.append("MACD histogram positive and rising — bullish momentum building")
    elif macd_hist < 0 and macd_hist <= macd_hist_prev:
        score -= 10
        reasons.append("MACD histogram negative and falling — bearish momentum building")

    if vol_ratio is not None:
        bar_open = float(last.get("open", price))
        bar_up = price >= bar_open
        if vol_ratio >= cfg.vol_ratio_threshold:
            if bar_up:
                score += 8
                reasons.append(f"Volume {vol_ratio:.2f}x avg on an up bar — conviction buying")
            else:
                score -= 8
                reasons.append(f"Volume {vol_ratio:.2f}x avg on a down bar — conviction selling")
        else:
            reasons.append(f"Volume {vol_ratio:.2f}x avg — no elevated conviction")
    if obv_trend == "rising":
        score += 7
        reasons.append(f"OBV rising over last {cfg.vol_obv_lookback} bars — accumulation (smart-money buying pressure)")
    elif obv_trend == "falling":
        score -= 7
        reasons.append(f"OBV falling over last {cfg.vol_obv_lookback} bars — distribution (smart-money selling pressure)")

    rel_pct = None
    if bench_df is not None and not bench_df.empty:
        lookback = min(cfg.rs_lookback_bars, len(df) - 1, len(bench_df) - 1)
        if lookback > 3:
            t_ret = (df["close"].iloc[-1] / df["close"].iloc[-1 - lookback] - 1) * 100
            b_ret = (bench_df["close"].iloc[-1] / bench_df["close"].iloc[-1 - lookback] - 1) * 100
            rel_pct = float(t_ret - b_ret)
            if rel_pct >= 2:
                score += 10
                reasons.append(f"Outperforming benchmark by {rel_pct:+.1f}% over {lookback} bars")
            elif rel_pct <= -2:
                score -= 10
                reasons.append(f"Underperforming benchmark by {rel_pct:+.1f}% over {lookback} bars")
            else:
                reasons.append(f"Roughly in-line with benchmark ({rel_pct:+.1f}% over {lookback} bars)")

    score = max(-100.0, min(100.0, score))
    return {
        "score": score, "reasons": reasons, "price": price,
        "rsi": rsi, "adx": adx, "rel_pct": rel_pct,
        "vol_ratio": vol_ratio, "obv_trend": obv_trend,
    }


def _wait_plan(*, style: str, reasons: list[str], confidence: float) -> dict:
    live = {
        "direction": "WAIT", "verdict": "WAIT", "confidence_pct": confidence,
        "take_trade": False, "entry_price": None, "stop_price": None,
        "target_price": None, "rr_ratio": None,
        "reasons": reasons + [f"Mixed/neutral signals — no clean {style.lower()} edge; wait for a clearer trend or RS break."],
    }
    return enrich_intra_live(live, hold_duration="No trade — wait for confluence")


def _build_plan(
    *, direction: str, entry: float, stop: float, target: float,
    holding_period: str, confidence: float, reasons: list[str], style: str,
    take_threshold: float,
) -> dict:
    sl_dist = abs(entry - stop)
    tp_dist = abs(target - entry)
    sl_pct = round(sl_dist / entry * 100, 2) if entry else None
    tp_pct = round(tp_dist / entry * 100, 2) if entry else None
    rr = round(tp_dist / sl_dist, 2) if sl_dist else None
    take = bool(sl_dist > 0 and tp_dist > 0 and confidence >= take_threshold)

    plan = make_trade_plan(
        direction=direction, timeframe=style, stop_loss_pct=sl_pct,
        take_profit_pct=tp_pct, confidence_pct=confidence, style=style,
        exit_rule="Exit at target, or on a structural break beyond the stop level.",
        max_hold_exit=holding_period,
    )
    live = {
        "direction": direction,
        "verdict": f"{'TAKE ' if take else 'WATCH '}{direction}",
        "confidence_pct": confidence,
        "take_trade": take,
        "entry_price": round(entry, 6),
        "stop_price": round(stop, 6),
        "target_price": round(target, 6),
        "rr_ratio": rr,
        "reasons": reasons,
        "trade_plan": plan,
    }
    return enrich_intra_live(live, hold_duration=holding_period)


def _directional_setup(
    df: pd.DataFrame, cfg: WeakStrongConfig, direction: str, *,
    ema_period: int, style: str, holding_period: str, confidence: float, reasons: list[str],
) -> dict | None:
    work = df.copy()
    work = add_ema(work, ema_period)
    work = add_atr(work, cfg.atr_period)
    work = work.dropna(subset=[f"ema_{ema_period}", f"atr_{cfg.atr_period}"])
    if work.empty:
        return None

    last = work.iloc[-1]
    price = float(last["close"])
    ema_val = float(last[f"ema_{ema_period}"])
    atr = float(last[f"atr_{cfg.atr_period}"])
    swing_highs, swing_lows = _find_swing_points(df, window=cfg.swing_window)
    recent_high = swing_highs[-1][1] if swing_highs else price + atr * 2
    recent_low = swing_lows[-1][1] if swing_lows else price - atr * 2

    near_ema = price > 0 and abs(price - ema_val) / price < 0.08
    if direction == "LONG":
        entry = ema_val if near_ema else price
        stop = min(recent_low, entry) - atr * 0.5
        target = max(recent_high, entry + (entry - stop) * 1.5)
    else:
        entry = ema_val if near_ema else price
        stop = max(recent_high, entry) + atr * 0.5
        target = min(recent_low, entry - (stop - entry) * 1.5)

    return _build_plan(
        direction=direction, entry=entry, stop=stop, target=target,
        holding_period=holding_period, confidence=confidence, reasons=reasons,
        style=style, take_threshold=cfg.take_confidence_threshold,
    )


def analyze_ticker(
    ticker: str, market: str, timeframe: str, *,
    cfg: WeakStrongConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict:
    cfg = cfg or WeakStrongConfig()
    df = _fetch_ohlcv(ticker, market, timeframe, groww_token=groww_token, exchange=exchange)
    if df is None or df.empty or len(df) < _MIN_BARS:
        return {
            "ticker": ticker, "market": market, "timeframe": timeframe,
            "error": f"Insufficient {timeframe} data ({0 if df is None else len(df)} bars, need {_MIN_BARS}+).",
        }

    bench_sym, _ = _benchmark_symbol(market)
    bench_df = None
    if ticker.upper().replace("-USD", "").replace("USDT", "") != bench_sym.upper().replace("-USD", ""):
        try:
            bench_df = _fetch_benchmark_ohlcv(market, timeframe)
        except Exception:
            bench_df = None

    scored = _score_ticker(df, bench_df, cfg)
    if scored is None:
        return {
            "ticker": ticker, "market": market, "timeframe": timeframe,
            "error": "Not enough clean indicator data after warmup.",
        }

    score = scored["score"]
    reasons = scored["reasons"]

    if score >= cfg.strong_threshold:
        verdict, direction = "STRONG", "LONG"
    elif score <= cfg.weak_threshold:
        verdict, direction = "WEAK", "SHORT"
    else:
        verdict, direction = "NEUTRAL", "WAIT"

    if verdict == "NEUTRAL":
        confidence = round(35.0 + abs(score) * 0.3, 1)
        scalp_plan = _wait_plan(style="Scalping", reasons=reasons, confidence=confidence)
        swing_plan = _wait_plan(style="Swing", reasons=reasons, confidence=confidence)
    else:
        confidence = round(min(92.0, 50.0 + abs(score) * 0.42), 1)
        scalp_plan = _directional_setup(
            df, cfg, direction, ema_period=cfg.ema_mid, style="Scalping",
            holding_period=_SCALP_HOLD, confidence=confidence, reasons=reasons,
        )
        if timeframe == "1d":
            daily_df = df
        else:
            try:
                daily_df = _fetch_ohlcv(ticker, market, "1d", groww_token=groww_token, exchange=exchange, limit=250)
            except Exception:
                daily_df = pd.DataFrame()
        swing_source = daily_df if daily_df is not None and len(daily_df) >= _MIN_BARS else df
        swing_plan = _directional_setup(
            swing_source, cfg, direction, ema_period=cfg.ema_slow, style="Swing",
            holding_period=_SWING_HOLD, confidence=confidence, reasons=reasons,
        )

    live = swing_plan or scalp_plan or {}

    return {
        "ticker": ticker, "market": market, "timeframe": timeframe,
        "verdict": verdict, "score": round(score, 1), "direction": direction,
        "confidence_pct": confidence, "reasons": reasons,
        "rel_pct": scored.get("rel_pct"),
        "vol_ratio": scored.get("vol_ratio"), "obv_trend": scored.get("obv_trend"),
        "live": live,
        "scalp_plan": scalp_plan,
        "swing_plan": swing_plan,
    }


def scan_universe(
    tickers: list[str], timeframes: list[str], market: str, *,
    cfg: WeakStrongConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict:
    cfg = cfg or WeakStrongConfig()
    strong: list[dict] = []
    weak: list[dict] = []
    neutral: list[dict] = []
    errors: list[dict] = []

    for ticker in tickers:
        for tf in timeframes:
            try:
                res = analyze_ticker(ticker, market, tf, cfg=cfg, groww_token=groww_token, exchange=exchange)
            except Exception as e:
                errors.append({"ticker": ticker, "timeframe": tf, "error": str(e)})
                continue
            if res.get("error"):
                errors.append({"ticker": ticker, "timeframe": tf, "error": res["error"]})
                continue
            {"STRONG": strong, "WEAK": weak, "NEUTRAL": neutral}[res["verdict"]].append(res)

    strong.sort(key=lambda r: r["score"], reverse=True)
    weak.sort(key=lambda r: r["score"])
    return {"strong": strong, "weak": weak, "neutral": neutral, "errors": errors}
