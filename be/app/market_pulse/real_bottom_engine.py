"""
real_bottom_engine.py
------------------------
Command Center — Real Bottom: the 5-step mechanical sequence for identifying
genuine market bottoms, adapted from "How to Catch a Real Market Bottom — The
Mechanics Nobody Teaches" (Smart Money Decode X, YouTube).
Source: https://www.youtube.com/watch?v=nkkchMHCHDo

The video's thesis: a real bottom isn't found with a single indicator — it's
read as a chain of events institutional players leave behind. If one link in
the chain breaks, the setup is invalid:

1. Selling Exhaustion (Absorption) — heavy volume, but price stops making
   meaningful new lows (buyers quietly absorbing panic selling).
2. The Retest — price returns to the lows on noticeably LOWER volume,
   proving the initial panic sellers are gone.
3. The Trap (Liquidity Sweep) — price wicks below the floor (triggering
   stops) then sharply reverses back inside. Cleanest on low volume.
4. Structural Shift (Displacement) — a strong, full-bodied candle breaks
   above the most recent lower high, typically leaving a Fair Value Gap.
5. The Entry — wait for a pullback into the Order Block or FVG, confirmed
   by a bullish trigger candle (hammer/engulfing). Stop below the trap low.

Rather than reimplementing swing/sweep/FVG detection from scratch, this
engine reuses two already-proven building blocks in this app:

- smc_liquidity_engine — structural swing-high/low tracking, wick-ratio
  sweep-vs-grab classification, and Fair Value Gap creation/tracking. This
  covers Step 3 (the trap) and the FVG half of Step 4 directly.
- price_action.detect_candlestick_patterns — the bullish trigger-candle
  check for Step 5 (hammer, bullish engulfing, morning star, etc.).

Steps 1 (absorption) and 2 (retest volume) aren't computed anywhere else in
this app, so they're implemented fresh here, ATR- and rolling-volume-scaled
rather than using fixed thresholds.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.price_action import _calc_atr, detect_candlestick_patterns, detect_support_resistance
from app.trading_hubs.smc_liquidity_engine import LiquidityConfig, implement_liquidity_strategy

logger = logging.getLogger(__name__)

__all__ = ["analyze_ticker", "analyze_ticker_multi_tf", "analyze_tickers_multi_tf"]

YOUTUBE_URL = "https://www.youtube.com/watch?v=nkkchMHCHDo"

_LOOKBACK_BARS = 400
_MIN_BARS = 80
_MAX_TRAP_AGE_BARS = 60
_DISPLACEMENT_SEARCH_AHEAD = 12
_ABSORPTION_WINDOW = 20
_RETEST_WINDOW = 15

_STATUS_LABEL = {
    "CONFIRMED_ENTRY": "🟢 Confirmed — Entry Zone Live",
    "PENDING_ENTRY": "🟡 Pending — Awaiting Pullback",
    "TRAP_CONFIRMED": "🟠 Trap Confirmed — Awaiting Displacement",
    "TRAP_UNCONFIRMED": "🔵 Trap Fired — Absorption/Retest Unconfirmed",
    "NO_SETUP": "⚪ No Setup",
}


def _fetch_ohlcv(
    ticker: str, market: str, timeframe: str, *, groww_token: str = "", exchange: str = "NSE",
) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    df = fetch_data_for_gap_scan(ticker, timeframe, market, groww_token, exchange, limit=_LOOKBACK_BARS)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < _MIN_BARS:
        df = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, timeframe, is_crypto=is_crypto, limit=_LOOKBACK_BARS, market=market),
        )
    return df


def _check_absorption(df: pd.DataFrame, trap_idx: int, atr: float) -> tuple[bool, str]:
    """Step 1 — heavy volume through the decline, but the low stops extending sharply."""
    start = max(0, trap_idx - _ABSORPTION_WINDOW)
    window = df.iloc[start:trap_idx + 1]
    if len(window) < 8:
        return False, "Not enough bars before the trap to assess absorption."

    vol = window["volume"].astype(float).values
    lows = window["low"].astype(float).values
    half = len(vol) // 2
    early_vol, late_vol = float(vol[:half].mean()), float(vol[half:].mean())
    early_low, late_low = float(lows[:half].min()), float(lows[half:].min())
    new_low_extension = early_low - late_low

    volume_held = late_vol >= early_vol * 0.7
    decelerating = new_low_extension <= atr * 1.0

    if volume_held and decelerating:
        return True, (
            f"Volume stayed elevated through the decline (avg {late_vol:,.0f} into the low vs "
            f"{early_vol:,.0f} earlier) while price only extended {new_low_extension:.4g} further — "
            f"inside 1×ATR. Panic selling being absorbed, not a fresh breakdown leg."
        )
    if not volume_held:
        return False, "Volume dried up before the low — no evidence of heavy absorption."
    return False, (
        f"Price kept extending sharply lower ({new_low_extension:.4g}, beyond 1×ATR) — still a live "
        f"panic leg, not yet being absorbed."
    )


def _check_retest(df: pd.DataFrame, trap_idx: int) -> tuple[bool, str]:
    """Step 2 — the return move into the lows must come on visibly lower volume."""
    start = max(0, trap_idx - _RETEST_WINDOW)
    window = df.iloc[start:trap_idx]
    if len(window) < 5:
        return False, "Not enough bars between the initial low and the trap to assess a retest."

    vol = window["volume"].astype(float).values
    half = len(vol) // 2
    decline_vol = float(vol[:half].mean())
    retest_vol = float(vol[half:].mean())
    if decline_vol <= 0:
        return False, "No usable volume data for the retest window."

    ratio = retest_vol / decline_vol
    if ratio <= 0.75:
        return True, f"The return move into the lows fired on {ratio * 100:.0f}% of the initial decline's volume — the panic sellers are gone."
    return False, f"Retest volume is {ratio * 100:.0f}% of the decline's — not meaningfully lower, sellers may still be present."


def _order_block_zone(df: pd.DataFrame, trap_idx: int, disp_idx: int) -> dict[str, float] | None:
    seg = df.iloc[trap_idx:disp_idx]
    bearish = seg[seg["close"] < seg["open"]]
    if bearish.empty:
        return None
    last = bearish.iloc[-1]
    return {"top": float(last["high"]), "bottom": float(last["low"])}


def _check_displacement(
    df: pd.DataFrame, work: pd.DataFrame, events: list, trap_idx: int,
) -> tuple[bool, int | None, dict[str, Any] | None, str]:
    """Step 4 — a strong bullish candle must close above the recent swing high, ideally leaving an FVG."""
    body = (df["close"] - df["open"]).abs()
    avg_body = body.rolling(20).mean()
    bsl_series = work["bsl_level"] if "bsl_level" in work.columns else None
    n = len(df)

    for j in range(trap_idx + 1, min(trap_idx + 1 + _DISPLACEMENT_SEARCH_AHEAD, n)):
        is_bull = float(df["close"].iloc[j]) > float(df["open"].iloc[j])
        ab = avg_body.iloc[j]
        strong = pd.notna(ab) and ab > 0 and float(body.iloc[j]) > float(ab) * 1.5
        prior_high = bsl_series.iloc[j] if bsl_series is not None else None
        broke = prior_high is not None and pd.notna(prior_high) and float(df["close"].iloc[j]) > float(prior_high)

        if is_bull and strong and broke:
            fvg_events = [
                e for e in events
                if e.event_type == "FVG_BULL" and j - 2 <= e.bar_index <= j + 2
            ]
            if fvg_events:
                ev = fvg_events[0]
                zone = {"top": float(ev.fvg_top), "bottom": float(ev.fvg_bottom)}
                fvg_note = " with a Fair Value Gap left behind"
            else:
                zone = _order_block_zone(df, trap_idx, j)
                fvg_note = " (no clean FVG — using the last down-close candle as the order block)" if zone else ""
            note = (
                f"A displacement candle broke above the prior swing high "
                f"({float(prior_high):,.4g}) {n - 1 - j} bar(s) ago{fvg_note}."
            )
            return True, j, zone, note

    return False, None, None, "No displacement yet — price hasn't broken the recent lower high with an impulsive candle."


def _check_entry(
    df: pd.DataFrame, zone: dict[str, float] | None, price: float, atr: float,
) -> tuple[bool, str]:
    """Step 5 — price must be back inside the FVG/order block with a fresh bullish trigger candle."""
    if not zone or zone.get("top") is None or zone.get("bottom") is None:
        return False, "No valid entry zone (FVG/order block) identified yet."

    top, bottom = zone["top"], zone["bottom"]
    in_zone = (bottom - atr * 0.15) <= price <= (top + atr * 0.15)
    patterns = detect_candlestick_patterns(df)
    bullish_trigger = [p for p in patterns if p.get("bias") == "BULLISH" and (p.get("bars_ago") or 99) <= 2]

    if in_zone and bullish_trigger:
        names = ", ".join(p["name"] for p in bullish_trigger[:2])
        return True, f"Price is inside the {bottom:,.4g}–{top:,.4g} entry zone with a fresh bullish trigger candle ({names})."
    if in_zone:
        return False, f"Price is inside the {bottom:,.4g}–{top:,.4g} entry zone but no confirmed bullish trigger candle yet."
    return False, f"Entry zone is {bottom:,.4g}–{top:,.4g}; price hasn't pulled back into it yet."


def analyze_ticker(
    ticker: str, timeframe: str, market: str, *, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    df = _fetch_ohlcv(ticker, market, timeframe, groww_token=groww_token, exchange=exchange)
    if df.empty or len(df) < _MIN_BARS:
        return {
            "ticker": ticker, "market": market, "timeframe": timeframe,
            "error": f"Insufficient {timeframe} data ({len(df)} bars, need {_MIN_BARS}+).",
        }

    price = float(df["close"].iloc[-1])
    atr = _calc_atr(df, 14)
    if not atr or atr <= 0:
        atr = max(price * 0.005, 1e-6)

    df_norm = normalize_ohlcv(df)
    n = len(df_norm)

    liq_cfg = LiquidityConfig(execution_tf=timeframe, use_mtf=False, strategy_mode="Both")
    work, events, bull_fvgs, bear_fvgs = implement_liquidity_strategy(df_norm, liq_cfg)

    trap_events = [
        e for e in events
        if e.direction == "LONG" and e.event_type in ("SWEEP", "GRAB")
        and (n - 1 - e.bar_index) <= _MAX_TRAP_AGE_BARS
    ]

    if not trap_events:
        return {
            "ticker": ticker, "market": market, "timeframe": timeframe,
            "price": price, "atr": round(float(atr), 6),
            "status": "NO_SETUP",
            "trap_low": None, "trap_bars_ago": None,
            "entry_zone": None, "stop_loss": None, "target": None,
            "reasons": [
                "No sell-side liquidity sweep/grab detected in the recent structure — the chain hasn't "
                "started (Step 3 hasn't fired yet).",
            ],
            "steps": {"selling_exhaustion": False, "retest": False, "trap": False, "displacement": False, "entry": False},
        }

    trap = trap_events[-1]
    trap_idx = trap.bar_index

    step1_ok, step1_note = _check_absorption(df_norm, trap_idx, atr)
    step2_ok, step2_note = _check_retest(df_norm, trap_idx)

    vol = df_norm["volume"].astype(float)
    avg_vol = vol.rolling(20).mean()
    trap_low_volume = False
    if trap_idx < len(avg_vol) and pd.notna(avg_vol.iloc[trap_idx]) and avg_vol.iloc[trap_idx] > 0:
        trap_low_volume = bool(vol.iloc[trap_idx] < avg_vol.iloc[trap_idx] * 0.85)

    step4_ok, disp_idx, zone, step4_note = _check_displacement(df_norm, work, events, trap_idx)

    step5_ok = False
    entry_note = "Waiting for displacement (Step 4) before an entry zone exists."
    if step4_ok:
        step5_ok, entry_note = _check_entry(df_norm, zone, price, atr)

    if step4_ok and step5_ok:
        status = "CONFIRMED_ENTRY"
    elif step4_ok:
        status = "PENDING_ENTRY"
    elif step1_ok and step2_ok:
        status = "TRAP_CONFIRMED"
    else:
        status = "TRAP_UNCONFIRMED"

    trap_label = "grab" if trap.event_type == "GRAB" else "sweep"
    trap_note = (
        f"Liquidity {trap_label} through {float(trap.ssl):,.4g} — {n - 1 - trap_idx} bar(s) ago"
        f"{', on low volume (cleanest signal)' if trap_low_volume else ''}."
        if trap.ssl is not None else
        f"Liquidity {trap_label} — {n - 1 - trap_idx} bar(s) ago"
        f"{', on low volume (cleanest signal)' if trap_low_volume else ''}."
    )

    reasons = [
        f"Step 1 (Selling Exhaustion) {'✅' if step1_ok else '❌'} — {step1_note}",
        f"Step 2 (Retest) {'✅' if step2_ok else '❌'} — {step2_note}",
        f"Step 3 (Trap) ✅ — {trap_note}",
        f"Step 4 (Displacement) {'✅' if step4_ok else '❌'} — {step4_note}",
        f"Step 5 (Entry) {'✅' if step5_ok else '❌'} — {entry_note}",
    ]

    sr = detect_support_resistance(df_norm, window=5, num_levels=3)
    resistances = sorted((sr.get("resistances") or []), key=lambda r: r["price"])
    target = next((r for r in resistances if r["price"] > price), None)
    if not target and resistances:
        target = max(resistances, key=lambda r: r["price"])

    stop_loss = None
    if trap.sweep_extreme is not None:
        sl_price = float(trap.sweep_extreme) - atr * 0.15
        stop_loss = {
            "price": round(sl_price, 6),
            "pct": round(abs(price - sl_price) / price * 100, 2) if price else None,
        }

    target_out = None
    if target:
        target_out = {
            "price": round(float(target["price"]), 6),
            "pct": round(abs(float(target["price"]) - price) / price * 100, 2) if price else None,
            "touches": target.get("touches"),
        }

    return {
        "ticker": ticker, "market": market, "timeframe": timeframe,
        "price": price, "atr": round(float(atr), 6),
        "status": status,
        "trap_low": round(float(trap.sweep_extreme), 6) if trap.sweep_extreme is not None else None,
        "trap_bars_ago": n - 1 - trap_idx,
        "entry_zone": {"top": round(zone["top"], 6), "bottom": round(zone["bottom"], 6)} if zone else None,
        "stop_loss": stop_loss,
        "target": target_out,
        "reasons": reasons,
        "steps": {
            "selling_exhaustion": step1_ok,
            "retest": step2_ok,
            "trap": True,
            "displacement": step4_ok,
            "entry": step5_ok,
        },
    }


def analyze_ticker_multi_tf(
    ticker: str, timeframes: list[str], market: str, *, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    per_tf: dict[str, dict[str, Any]] = {}
    for tf in timeframes:
        try:
            per_tf[tf] = analyze_ticker(ticker, tf, market, groww_token=groww_token, exchange=exchange)
        except Exception as exc:
            logger.debug("Real Bottom analysis failed for %s %s: %s", ticker, tf, exc)
            per_tf[tf] = {"ticker": ticker, "market": market, "timeframe": tf, "error": str(exc)[:200]}
    return {"ticker": ticker, "market": market, "per_tf": per_tf}


def analyze_tickers_multi_tf(
    tickers: list[str], timeframes: list[str], market: str, *, groww_token: str = "", exchange: str = "NSE",
) -> list[dict[str, Any]]:
    return [
        analyze_ticker_multi_tf(ticker, timeframes, market, groww_token=groww_token, exchange=exchange)
        for ticker in tickers
    ]
