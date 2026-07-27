"""
swing_trend_breakout_engine.py
-----------------------------------
Swing Trading — Trend Following Breakout: a mechanical distillation of the
index-filter -> momentum-leader -> weekly-confirmed swing-high breakout setup
described at https://www.youtube.com/watch?v=MytrwMIFwDM (India · US · Crypto ·
Commodities — including sectoral/index ETFs, the video's own suggested
lower-risk alternative to individual stocks).

1. Market filter — only take swing entries when the market benchmark (Nifty
   50 / SPY / BTC, resolved per asset class the same way Weak/Strong does)
   is trading above its own daily 20 SMA. Below it, every ticker in the scan
   is forced to WAIT regardless of its own setup — this mirrors the video's
   explicit rule that stop-losses get hit far more often when the broader
   market isn't trending.
2. Momentum/strength proxy — the video's "strong sector -> 52-week/ATH
   momentum leaders -> structurally strong on the weekly" funnel is
   mechanized per-ticker as: price within `high_52w_proximity_pct` of its
   trailing 52-week high, AND the last COMPLETED weekly candle closed above
   its own weekly SMA, AND (the video's own optional "double filter") the
   daily close is above its own daily SMA. A true sector-rotation scan needs
   a sector-mapped universe this per-ticker engine doesn't have — that's a
   separate, larger feature and is not reproduced here; this is disclosed
   rather than faked.
3. Entry — find the most recent daily swing high (a local high vs
   `swing_window` bars either side), require at least `consolidation_min_bars`
   of pullback/consolidation since that swing high, then trigger LONG the
   moment daily close freshly closes back above it (within `recent_bars`).
4. Stop-loss — configurable: the triggering breakout candle's low (tighter,
   default), or the most recent swing low before the breakout (wider) — the
   video frames both as valid trader choices.
5. Target — fixed risk:reward off that stop (video suggests 1:2-1:3; default
   2.5).

Long-only, as framed in the source. Confidence is a heuristic confluence
score, not a statistical win probability. Research / education only — NOT
FINANCIAL ADVICE.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.indicators import add_sma
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan
from app.market_pulse.sr_breakout import _find_swing_points
from app.market_pulse.weak_strong_engine import _benchmark_symbol
from app.trading_hubs.intraday_shared import enrich_intra_live
from app.trading_hubs.swing_trading_st_mtf_mss_engine import build_weekly_from_daily

logger = logging.getLogger(__name__)

YOUTUBE_URL = "https://www.youtube.com/watch?v=MytrwMIFwDM"

STOP_BREAKOUT_CANDLE = "breakout_candle_low"
STOP_SWING_LOW = "swing_low"
STOP_METHOD_OPTIONS = [STOP_BREAKOUT_CANDLE, STOP_SWING_LOW]

MARKET_FILTER_ON = "on"
MARKET_FILTER_OFF = "off"
MARKET_FILTER_OPTIONS = [MARKET_FILTER_ON, MARKET_FILTER_OFF]

HOLD_SWING_TREND_BREAKOUT = "1-4 weeks (trend-following swing — trail or exit at the fixed target)"


@dataclass
class SwingTrendBreakoutConfig:
    market_filter: str = MARKET_FILTER_ON
    stop_method: str = STOP_BREAKOUT_CANDLE
    market_sma_period: int = 20
    daily_sma_period: int = 20
    weekly_sma_period: int = 20
    swing_window: int = 5
    consolidation_min_bars: int = 2
    consolidation_max_bars: int = 20
    high_52w_proximity_pct: float = 15.0
    rr_ratio: float = 2.5
    recent_bars: int = 1
    take_confidence_threshold: float = 55.0
    daily_lookback: int = 320
    min_bars: int = 270


def _fetch_daily(ticker: str, market: str, *, groww_token: str = "", exchange: str = "NSE", limit: int = 320) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    df = fetch_data_for_gap_scan(ticker, "1d", market, groww_token, exchange, limit=limit)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < 60:
        df = normalize_ohlcv(fetch_ohlcv_yfinance(ticker, "1d", is_crypto=is_crypto, limit=limit, market=market))
    return df


def _volume_ratio(df: pd.DataFrame, *, at: int = -1, window: int = 20) -> float:
    if len(df) < window + 1:
        return 1.0
    avg = df["volume"].iloc[-(window + 1):-1].mean()
    if avg <= 0:
        return 1.0
    return float(df["volume"].iloc[at]) / float(avg)


def _market_trend_ok(
    market: str, cfg: SwingTrendBreakoutConfig, *, groww_token: str = "", exchange: str = "NSE",
) -> tuple[bool, dict[str, Any]]:
    """Fetch the benchmark once per scan and check it's above its own daily SMA."""
    bench_sym, _ = _benchmark_symbol(market)
    info: dict[str, Any] = {"benchmark": bench_sym, "available": False, "above_sma": None, "close": None, "sma": None}
    if cfg.market_filter != MARKET_FILTER_ON:
        return True, info
    try:
        df = _fetch_daily(bench_sym, market, groww_token=groww_token, exchange=exchange, limit=max(cfg.market_sma_period + 30, 60))
        if df.empty or len(df) < cfg.market_sma_period + 5:
            return True, info  # can't evaluate — don't block the whole scan on missing benchmark data
        df = add_sma(df, cfg.market_sma_period)
        close = float(df["close"].iloc[-1])
        sma = float(df[f"sma_{cfg.market_sma_period}"].iloc[-1])
        info.update({"available": True, "above_sma": close > sma, "close": close, "sma": sma})
        return bool(close > sma), info
    except Exception as exc:
        logger.debug("Swing trend breakout market filter failed for %s: %s", bench_sym, exc)
        return True, info


def evaluate_ticker(
    df: pd.DataFrame, cfg: SwingTrendBreakoutConfig, *, market_ok: bool, market_info: dict[str, Any],
) -> dict[str, Any]:
    if df.empty or len(df) < cfg.min_bars:
        return {
            "signal": "NO_DATA", "direction": "WAIT", "verdict": "NO DATA", "take_trade": False,
            "reasons": [f"Need {cfg.min_bars}+ daily bars, have {len(df)}."],
        }

    work = df.copy()
    work = add_sma(work, cfg.daily_sma_period)
    daily_sma_col = f"sma_{cfg.daily_sma_period}"

    price = float(work["close"].iloc[-1])
    last_idx = len(work) - 1
    reasons: list[str] = []

    if cfg.market_filter == MARKET_FILTER_ON:
        if market_info.get("available"):
            reasons.append(
                f"Market filter ({market_info['benchmark']}): index is "
                f"{'above' if market_ok else 'BELOW'} its {cfg.market_sma_period} SMA "
                f"({market_info['close']:,.4g} vs {market_info['sma']:,.4g})."
            )
        else:
            reasons.append("Market filter: benchmark data unavailable — filter skipped for this scan.")
        if not market_ok:
            return {
                "signal": "NONE", "direction": "WAIT", "take_trade": False,
                "verdict": "WAIT — market filter", "confidence_pct": 15.0,
                "reasons": reasons + ["Skipping swing entries market-wide until the index reclaims its SMA."],
            }

    # 52-week-high proximity (momentum-leader proxy for the video's sector/52w-high scan)
    lookback_52w = min(last_idx, 252)
    high_52w = float(work["high"].iloc[-(lookback_52w + 1):-1].max()) if lookback_52w > 0 else price
    dist_52w_pct = (high_52w - price) / high_52w * 100 if high_52w else 0.0
    near_52w_high = dist_52w_pct <= cfg.high_52w_proximity_pct
    reasons.append(
        f"{dist_52w_pct:.1f}% below the trailing 52-week high — "
        f"{'within' if near_52w_high else 'outside'} the {cfg.high_52w_proximity_pct:.0f}% momentum-leader band."
    )

    # Weekly structural strength — last COMPLETED week vs its own SMA.
    weekly = build_weekly_from_daily(work)
    weekly_ok = False
    if len(weekly) > cfg.weekly_sma_period + 1:
        wk = add_sma(weekly.copy(), cfg.weekly_sma_period)
        wk_closed = wk.iloc[:-1]  # exclude the still-forming current week
        wk_close = float(wk_closed["close"].iloc[-1])
        wk_sma = float(wk_closed[f"sma_{cfg.weekly_sma_period}"].iloc[-1])
        weekly_ok = wk_close > wk_sma
        reasons.append(
            f"Weekly close {'above' if weekly_ok else 'below'} its {cfg.weekly_sma_period}-week SMA "
            f"({wk_close:,.4g} vs {wk_sma:,.4g})."
        )
    else:
        reasons.append("Not enough weekly history yet to confirm structural strength.")

    daily_sma_ok = bool(price > float(work[daily_sma_col].iloc[-1]))
    reasons.append(f"Daily close {'above' if daily_sma_ok else 'below'} its own {cfg.daily_sma_period} SMA (double filter).")

    if not (near_52w_high and weekly_ok and daily_sma_ok):
        missing = []
        if not near_52w_high:
            missing.append("not near its 52-week high")
        if not weekly_ok:
            missing.append("weekly trend not confirmed")
        if not daily_sma_ok:
            missing.append("below its own daily SMA")
        return {
            "signal": "NONE", "direction": "WAIT", "take_trade": False,
            "verdict": f"WAIT — {', '.join(missing)}", "confidence_pct": 25.0, "reasons": reasons,
        }

    # Entry: fresh breakout above the most recent qualifying swing high.
    swing_highs, swing_lows = _find_swing_points(work.iloc[:-1], window=cfg.swing_window)
    if not swing_highs:
        return {
            "signal": "NONE", "direction": "WAIT", "take_trade": False,
            "verdict": "WAIT — no swing high found", "confidence_pct": 30.0,
            "reasons": reasons + ["No clean swing high in the lookback window yet."],
        }

    idx_pos = {ts: i for i, ts in enumerate(work.index)}
    candidate: tuple[Any, float, int] | None = None
    for ts, lvl in reversed(swing_highs):
        bar_pos = idx_pos.get(ts)
        if bar_pos is None:
            continue
        bars_since = last_idx - bar_pos
        if bars_since < cfg.consolidation_min_bars:
            continue  # too recent — no consolidation pause yet
        if bars_since > cfg.consolidation_max_bars:
            break  # older candidates only get further away too
        candidate = (ts, lvl, bar_pos)
        break

    if candidate is None:
        return {
            "signal": "NONE", "direction": "WAIT", "take_trade": False,
            "verdict": "WAIT — no qualifying swing high in range", "confidence_pct": 30.0,
            "reasons": reasons + [
                f"No swing high {cfg.consolidation_min_bars}-{cfg.consolidation_max_bars} bars back to break out of."
            ],
        }

    _swing_high_ts, swing_high_price, swing_high_pos = candidate

    # Fresh crossing only — search the last `recent_bars` bars for a bar that
    # closes above the level while the prior bar didn't (a true crossing, not
    # a stale break from many bars ago that's since drifted further above it).
    breakout_bar_pos: int | None = None
    start = max(swing_high_pos + 1, last_idx - cfg.recent_bars + 1)
    for pos in range(last_idx, start - 1, -1):
        if pos <= swing_high_pos:
            break
        cur_close = float(work["close"].iloc[pos])
        prev_close = float(work["close"].iloc[pos - 1])
        if cur_close > swing_high_price and prev_close <= swing_high_price:
            breakout_bar_pos = pos
            break

    if breakout_bar_pos is None:
        stale_break = any(
            float(work["close"].iloc[p]) > swing_high_price for p in range(swing_high_pos + 1, last_idx + 1)
        )
        reason = (
            f"Broke above the swing high ({swing_high_price:,.4g}) earlier but not within the last "
            f"{cfg.recent_bars} bar(s) — no longer a fresh trigger."
            if stale_break else
            f"Consolidating below the recent swing high ({swing_high_price:,.4g}) — no breakout close yet."
        )
        return {
            "signal": "NONE", "direction": "WAIT", "take_trade": False,
            "verdict": "WAIT — no fresh breakout", "confidence_pct": 35.0, "reasons": reasons + [reason],
        }

    entry = float(work["close"].iloc[-1])
    breakout_bar_low = float(work["low"].iloc[breakout_bar_pos])
    if cfg.stop_method == STOP_SWING_LOW:
        prior_swing_lows = [lvl for ts, lvl in swing_lows if idx_pos.get(ts, 10 ** 9) < breakout_bar_pos]
        stop = prior_swing_lows[-1] if prior_swing_lows else breakout_bar_low
    else:
        stop = breakout_bar_low
    risk = max(entry - stop, entry * 0.003)
    target = entry + risk * cfg.rr_ratio

    vol_ratio = _volume_ratio(work)
    consolidation_bars = breakout_bar_pos - swing_high_pos

    confidence = cfg.take_confidence_threshold
    confidence += min(15.0, max(0.0, (cfg.high_52w_proximity_pct - dist_52w_pct) * 0.8))
    if vol_ratio >= 1.3:
        confidence += 10
    elif vol_ratio < 0.8:
        confidence -= 6
    if consolidation_bars >= cfg.consolidation_min_bars + 2:
        confidence += 5
    take = confidence >= cfg.take_confidence_threshold

    sl_pct = round(abs(entry - stop) / entry * 100, 2) if entry else 1.0
    tp_pct = round(abs(target - entry) / entry * 100, 2) if entry else sl_pct * cfg.rr_ratio

    plan = make_trade_plan(
        direction="LONG" if take else "—", timeframe="1d", stop_loss_pct=sl_pct, take_profit_pct=tp_pct,
        confidence_pct=confidence, style="swing",
        exit_rule=f"Exit at the fixed 1:{cfg.rr_ratio:.1f} target, or trail the stop once price is comfortably in profit.",
        max_hold_exit="Reassess if the target isn't reached within a few weeks — trend-following breakouts that stall usually aren't working.",
    )

    reasons.append(
        f"Fresh breakout above the recent swing high ({swing_high_price:,.4g}), {consolidation_bars} bar(s) after "
        f"that swing high — {'a real consolidation pause' if consolidation_bars >= cfg.consolidation_min_bars + 2 else 'a brief pause'} before the break."
    )
    reasons.append(f"Breakout-bar volume {vol_ratio:.2f}x its 20-bar average.")
    reasons.append(
        f"Stop at the {'recent swing low' if cfg.stop_method == STOP_SWING_LOW else 'breakout candle low'} ({stop:,.4g})."
    )

    live = enrich_intra_live({
        "signal": "LONG" if take else "NONE", "direction": "LONG", "take_trade": take,
        "verdict": "TAKE LONG — trend-following breakout" if take else "WATCH — breakout confirmed, confidence below threshold",
        "confidence_pct": round(confidence, 1), "sl_pct": sl_pct, "tp_pct": tp_pct,
        "entry_price": round(entry, 6), "stop_price": round(stop, 6), "target_price": round(target, 6),
        "swing_high": round(swing_high_price, 6), "dist_from_52w_high_pct": round(dist_52w_pct, 2),
        "reasons": reasons, "trade_plan": {**plan, "holding_period": HOLD_SWING_TREND_BREAKOUT},
    }, hold_duration=HOLD_SWING_TREND_BREAKOUT)

    return live


def analyze_ticker(
    ticker: str, market: str, *, cfg: SwingTrendBreakoutConfig | None = None,
    groww_token: str = "", exchange: str = "NSE",
    market_ok: bool = True, market_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = cfg or SwingTrendBreakoutConfig()
    df = _fetch_daily(ticker, market, groww_token=groww_token, exchange=exchange, limit=cfg.daily_lookback)
    if df.empty or len(df) < cfg.min_bars:
        return {"ticker": ticker, "market": market, "error": f"Insufficient daily data ({len(df)} bars, need {cfg.min_bars}+)."}

    live = evaluate_ticker(df, cfg, market_ok=market_ok, market_info=market_info or {})
    return {
        "ticker": ticker, "market": market, "bars": len(df),
        "last_close": float(df["close"].iloc[-1]), "live": live,
    }


def scan_universe(
    tickers: list[str], market: str, *, cfg: SwingTrendBreakoutConfig | None = None,
    groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or SwingTrendBreakoutConfig()
    market_ok, market_info = _market_trend_ok(market, cfg, groww_token=groww_token, exchange=exchange)

    results = []
    for ticker in tickers:
        try:
            results.append(analyze_ticker(
                ticker, market, cfg=cfg, groww_token=groww_token, exchange=exchange,
                market_ok=market_ok, market_info=market_info,
            ))
        except Exception as exc:
            logger.debug("Swing Trend Breakout failed for %s: %s", ticker, exc)
            results.append({"ticker": ticker, "market": market, "error": str(exc)[:200]})

    entries = [r for r in results if not r.get("error") and (r.get("live") or {}).get("take_trade")]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market, "market_filter": market_info, "results": results,
        "entries": entries, "entry_count": len(entries),
    }
