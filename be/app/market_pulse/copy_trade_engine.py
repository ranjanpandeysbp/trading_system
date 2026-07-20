"""
copy_trade_engine.py
----------------------
COPY TRADE — high-beta / 3x leveraged ETF momentum scalp.
Video: https://www.youtube.com/watch?v=-d4jDhTRBV0

Core idea (aggressive small-account momentum strategy): trade only high-beta
stocks or 3x leveraged ETFs (TQQQ, SQQQ, LABU, LABD, SOXL, SOXS, etc.) on the
15-minute chart. The "sweet spot" is a Stochastic %K breaking above 80 (long)
or below 20 (short) — strong one-sided momentum — confirmed by an Engulfing
candle (bullish for longs, bearish for shorts) printing on above-average
volume. There is no fixed stop-loss to wait out: the moment %K stops
extending (a pullback in momentum) the trade is exited immediately, and a
fresh entry is taken again a few bars later if a new engulfing candle prints
while the zone is still active.

This engine reports, for the latest bar:
  - ENTRY_TRIGGERED: a fresh engulfing + volume + Stochastic-extreme setup
    just fired — take it.
  - WATCHING_ZONE: Stochastic is in the 80+/20- zone but no trigger candle
    has printed yet — stay ready for the next engulfing candle.
  - EXIT_SIGNAL: Stochastic was extended and just turned back — if you're in
    a position from a recent bar, this is the "get out now" cue the video
    describes; not a new entry.
  - NO_SETUP: Stochastic is inside the 20-80 band — no edge either way.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.indicators import add_stochastic, add_vol_sma
from app.trading_hubs.intraday_shared import enrich_intra_live
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.price_action import _calc_atr, detect_candlestick_patterns
from app.market_pulse.run_summary import make_trade_plan
from app.market_pulse.ticker_utils import is_crypto_market

logger = logging.getLogger(__name__)

YOUTUBE_COPY_TRADE_URL = "https://www.youtube.com/watch?v=-d4jDhTRBV0"

EXEC_TF = "15m"
HOLD_COPY_TRADE = (
    "Same session — exit immediately on the first pullback sign (Stochastic momentum "
    "turning), no fixed stop-loss wait; re-enter on a fresh engulfing candle if the "
    "zone/trend is still intact."
)

PHASE_NO_SETUP = "NO_SETUP"
PHASE_WATCHING = "WATCHING_ZONE"
PHASE_ENTRY = "ENTRY_TRIGGERED"
PHASE_EXIT_SIGNAL = "EXIT_SIGNAL"

# Tickers the video's strategy is built around — high beta / 3x leveraged ETFs.
SUGGESTED_TICKERS = ["TQQQ", "SQQQ", "LABU", "LABD", "SOXL", "SOXS", "TNA", "TZA"]


@dataclass
class CopyTradeConfig:
    k_period: int = 14
    d_period: int = 3
    upper_band: float = 80.0
    lower_band: float = 20.0
    vol_ratio_min: float = 1.1
    vol_sma_period: int = 20
    fresh_bars: int = 2
    atr_period: int = 14
    rr_ratio: float = 1.5
    take_confidence_threshold: float = 60.0
    min_bars: int = 60


def _fetch_ohlcv(
    ticker: str, market: str, *, groww_token: str = "", exchange: str = "NSE", limit: int = 300,
) -> pd.DataFrame:
    is_crypto = is_crypto_market(market)
    df = fetch_data_for_gap_scan(ticker, EXEC_TF, market, groww_token, exchange, limit=limit)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < 30:
        df = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, EXEC_TF, is_crypto=is_crypto, limit=limit, market=market),
        )
    return df


def _volume_ratio(df: pd.DataFrame, period: int) -> float:
    work = add_vol_sma(df.copy(), period)
    vol = float(work["volume"].iloc[-1])
    avg_raw = work[f"vol_sma_{period}"].iloc[-1]
    avg = float(avg_raw) if pd.notna(avg_raw) else vol
    return vol / avg if avg > 0 else 1.0


def analyze_ticker(
    ticker: str, market: str, *, cfg: CopyTradeConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or CopyTradeConfig()
    df = _fetch_ohlcv(ticker, market, groww_token=groww_token, exchange=exchange)
    if df.empty or len(df) < cfg.min_bars:
        return {"ticker": ticker, "market": market, "error": f"Insufficient {EXEC_TF} data ({len(df)} bars, need {cfg.min_bars}+)."}

    work = add_stochastic(df.copy(), k_period=cfg.k_period, d_period=cfg.d_period)
    k_col = f"stoch_k_{cfg.k_period}"
    work = work.dropna(subset=[k_col])
    if len(work) < 3:
        return {"ticker": ticker, "market": market, "error": "Not enough clean Stochastic data after warmup."}

    price = float(work["close"].iloc[-1])
    atr = _calc_atr(work, cfg.atr_period)
    if not atr or atr <= 0:
        atr = max(price * 0.003, 1e-6)

    k_now = float(work[k_col].iloc[-1])
    k_prev = float(work[k_col].iloc[-2])

    vol_ratio = _volume_ratio(df, cfg.vol_sma_period)
    vol_confirm = vol_ratio >= cfg.vol_ratio_min

    patterns = detect_candlestick_patterns(df)
    bullish_engulf = next((p for p in patterns if p["name"] == "Bullish Engulfing" and p["bars_ago"] <= cfg.fresh_bars), None)
    bearish_engulf = next((p for p in patterns if p["name"] == "Bearish Engulfing" and p["bars_ago"] <= cfg.fresh_bars), None)

    base = {
        "ticker": ticker, "market": market, "timeframe": EXEC_TF,
        "price": price, "atr": round(float(atr), 6),
        "stoch_k": round(k_now, 1), "stoch_k_prev": round(k_prev, 1),
        "vol_ratio": round(vol_ratio, 2),
    }

    def _live(*, phase: str, direction: str, verdict: str, confidence: float,
              take: bool, reasons: list[str], entry=None, stop=None, target=None) -> dict:
        payload: dict[str, Any] = {
            "signal": "BUY" if direction == "LONG" else ("SELL" if direction == "SHORT" else "NONE"),
            "direction": direction, "take_trade": take, "verdict": verdict,
            "phase": phase, "confidence_pct": confidence, "reasons": reasons,
        }
        if entry is not None:
            sl_dist = abs(entry - stop)
            tp_dist = abs(target - entry)
            sl_pct = round(sl_dist / entry * 100, 2) if entry else 0.0
            tp_pct = round(tp_dist / entry * 100, 2) if entry else 0.0
            plan = make_trade_plan(
                direction=direction if take else "—",
                timeframe=EXEC_TF, stop_loss_pct=sl_pct, take_profit_pct=tp_pct,
                confidence_pct=confidence, style="scalping",
                exit_rule="Exit the instant Stochastic %K stops extending (turns down for "
                          "longs, up for shorts) — do not wait for the stop-loss to be hit.",
                max_hold_exit="Time stop: same session, exit by close.",
            )
            payload.update({
                "entry_price": round(entry, 6), "stop_price": round(stop, 6),
                "target_price": round(target, 6), "sl_pct": sl_pct, "tp_pct": tp_pct,
                "trade_plan": {**plan, "direction": direction if take else "—", "holding_period": HOLD_COPY_TRADE},
            })
        return enrich_intra_live(payload, hold_duration=HOLD_COPY_TRADE)

    if k_now >= cfg.upper_band:
        if k_now >= k_prev:
            if bullish_engulf and vol_confirm:
                bar_idx = bullish_engulf["bar_idx"]
                swing_low = float(df["low"].iloc[max(0, bar_idx - 2):bar_idx + 1].min())
                stop = swing_low - atr * 0.25
                target = price + cfg.rr_ratio * (price - stop)
                extremity = min(1.0, abs(k_now - 50) / 50)
                conf = round(min(92.0, 55 + 20 * extremity + 15 * min(1.0, max(0.0, vol_ratio - 1))), 1)
                take = conf >= cfg.take_confidence_threshold and (price - stop) > 0
                base["phase"] = PHASE_ENTRY
                base["live"] = _live(
                    phase=PHASE_ENTRY, direction="LONG",
                    verdict=f"{'TAKE' if take else 'WATCH'} LONG", confidence=conf, take=take,
                    reasons=[
                        f"Stochastic %K {k_now:.1f} — in the 80+ 'sweet spot' and still rising.",
                        f"Bullish Engulfing printed {bullish_engulf['bars_ago']} bar(s) ago on "
                        f"{vol_ratio:.1f}x average volume — momentum + participation confirmed.",
                        "Exit rule: the moment %K stops rising, exit immediately — don't wait for the stop.",
                    ],
                    entry=price, stop=stop, target=target,
                )
            else:
                base["phase"] = PHASE_WATCHING
                missing = []
                if not bullish_engulf:
                    missing.append("no fresh Bullish Engulfing yet")
                if not vol_confirm:
                    missing.append(f"volume only {vol_ratio:.1f}x average (need ≥{cfg.vol_ratio_min}x)")
                base["live"] = _live(
                    phase=PHASE_WATCHING, direction="LONG", verdict="WATCH LONG", confidence=38.0, take=False,
                    reasons=[
                        f"Stochastic %K {k_now:.1f} — in the 80+ 'sweet spot', trend still intact.",
                        f"Waiting for trigger: {', '.join(missing)}.",
                    ],
                )
        else:
            base["phase"] = PHASE_EXIT_SIGNAL
            base["live"] = _live(
                phase=PHASE_EXIT_SIGNAL, direction="LONG", verdict="EXIT LONG", confidence=45.0, take=False,
                reasons=[
                    f"Stochastic %K just turned down ({k_prev:.1f} → {k_now:.1f}) after being extended above "
                    f"{cfg.upper_band:.0f} — this is the pullback-exit cue: if you're in a long from a recent "
                    f"bar, the strategy says get out now, not a fresh entry.",
                ],
            )
    elif k_now <= cfg.lower_band:
        if k_now <= k_prev:
            if bearish_engulf and vol_confirm:
                bar_idx = bearish_engulf["bar_idx"]
                swing_high = float(df["high"].iloc[max(0, bar_idx - 2):bar_idx + 1].max())
                stop = swing_high + atr * 0.25
                target = price - cfg.rr_ratio * (stop - price)
                extremity = min(1.0, abs(k_now - 50) / 50)
                conf = round(min(92.0, 55 + 20 * extremity + 15 * min(1.0, max(0.0, vol_ratio - 1))), 1)
                take = conf >= cfg.take_confidence_threshold and (stop - price) > 0
                base["phase"] = PHASE_ENTRY
                base["live"] = _live(
                    phase=PHASE_ENTRY, direction="SHORT",
                    verdict=f"{'TAKE' if take else 'WATCH'} SHORT", confidence=conf, take=take,
                    reasons=[
                        f"Stochastic %K {k_now:.1f} — in the 20- 'sweet spot' and still falling.",
                        f"Bearish Engulfing printed {bearish_engulf['bars_ago']} bar(s) ago on "
                        f"{vol_ratio:.1f}x average volume — momentum + participation confirmed.",
                        "Exit rule: the moment %K stops falling, exit immediately — don't wait for the stop.",
                    ],
                    entry=price, stop=stop, target=target,
                )
            else:
                base["phase"] = PHASE_WATCHING
                missing = []
                if not bearish_engulf:
                    missing.append("no fresh Bearish Engulfing yet")
                if not vol_confirm:
                    missing.append(f"volume only {vol_ratio:.1f}x average (need ≥{cfg.vol_ratio_min}x)")
                base["live"] = _live(
                    phase=PHASE_WATCHING, direction="SHORT", verdict="WATCH SHORT", confidence=38.0, take=False,
                    reasons=[
                        f"Stochastic %K {k_now:.1f} — in the 20- 'sweet spot', trend still intact.",
                        f"Waiting for trigger: {', '.join(missing)}.",
                    ],
                )
        else:
            base["phase"] = PHASE_EXIT_SIGNAL
            base["live"] = _live(
                phase=PHASE_EXIT_SIGNAL, direction="SHORT", verdict="EXIT SHORT", confidence=45.0, take=False,
                reasons=[
                    f"Stochastic %K just turned up ({k_prev:.1f} → {k_now:.1f}) after being extended below "
                    f"{cfg.lower_band:.0f} — this is the pullback-exit cue: if you're in a short from a recent "
                    f"bar, the strategy says get out now, not a fresh entry.",
                ],
            )
    else:
        base["phase"] = PHASE_NO_SETUP
        base["live"] = _live(
            phase=PHASE_NO_SETUP, direction="WAIT", verdict="WAIT", confidence=0.0, take=False,
            reasons=[f"Stochastic %K {k_now:.1f} — inside the 20-80 band, no directional 'sweet spot' active."],
        )

    return base


def scan_universe(
    tickers: list[str], market: str, *, cfg: CopyTradeConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or CopyTradeConfig()
    results = []
    for ticker in tickers:
        try:
            results.append(analyze_ticker(ticker, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            logger.debug("Copy Trade scan failed for %s: %s", ticker, exc)
            results.append({"ticker": ticker, "market": market, "error": str(exc)[:200]})

    entries = [r for r in results if not r.get("error") and (r.get("live") or {}).get("take_trade")]
    watches = [
        r for r in results
        if not r.get("error")
        and not (r.get("live") or {}).get("take_trade")
        and r.get("phase") in (PHASE_WATCHING, PHASE_EXIT_SIGNAL)
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
