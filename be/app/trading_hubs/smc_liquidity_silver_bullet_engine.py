"""
smc_liquidity_silver_bullet_engine.py
---------------------------------------
"Trade Liquidity Like the Pros" — liquidity, inducement, and market
structure, executed as the video's "Silver Bullet" sequence.

Source: https://www.youtube.com/watch?v=xnEioNLgNMM

Theory (Steps 1-3, used to frame the HTF bias reported alongside the
setup — see `reasons`):
  - Step 1, trading range: a confirmed break of structure from an impulse
    leg that pulled back into a discount (bull) / premium (bear) zone
    below/above the 50% level, validated only once price breaks the most
    recent internal swing (an inducement). Operationalized here via the
    shared `smc_engine` primitives: `find_fractal_swings` +
    `detect_structure_breaks` + `current_bias` on the HTF.
  - Step 2, liquidity map: external liquidity sits beyond major swing
    highs/lows (the "magnet"); internal liquidity is the Fair Value Gaps
    inside the range that fuel the move toward it.
  - Step 3, inducement: false moves that trap early entries — structural
    (shallow retracement <38.2%), liquidity-based (engineered small
    high/low sweeps), and time-based (London/NY session-open traps). The
    concrete, executable form of this in the video is the liquidity sweep
    in Step 4 below.

Step 4, the executable "Silver Bullet" sequence (what this engine scans
for, on the execution timeframe):
  1. Liquidity sweep: price wicks beyond the day's high (or low), during
     the London or New York session, and closes back inside.
  2. Market Structure Shift: price closes past the most recent swing low
     (bearish, after a high-sweep) or swing high (bullish, after a
     low-sweep) — confirms sellers/buyers took control.
  3. Entry on the Fair Value Gap created during that structural shift —
     a limit order at the near edge of the gap (the edge price reaches
     first on the retracement).
  4. Stop-loss beyond the order block that produced the impulse (wider,
     breathing room against wick stop-outs) — reported alongside the
     tighter "just outside the FVG" alternative for the trader's own
     choice.
  Minimum 1:2 risk:reward, sized off the wider (order-block) stop.

Session windows and the FVG/order-block/swing/structure-break detection
are reused from existing shared primitives (`scalp_livefree_fx_engine`'s
market-aware session profiles, `smc_engine`'s fractal swings, structure
breaks, FVGs, and order blocks) rather than re-implemented here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.scalp_livefree_fx_engine import (
    _ensure_tz,
    _in_window,
    _session_profile_for_market,
    _sessions_for_profile,
    _tz_for_profile,
)
from app.trading_hubs.smart_money_shared import enrich_smc_live, hold_for_tf
from app.trading_hubs.smc_engine.adapters import to_smc_ohlc
from app.trading_hubs.smc_engine.config import SMCConfig
from app.trading_hubs.smc_engine.imbalances import detect_fvgs, detect_order_blocks
from app.trading_hubs.smc_engine.models import StructureEvent
from app.trading_hubs.smc_engine.structure import current_bias, detect_structure_breaks, find_fractal_swings

logger = logging.getLogger(__name__)

YOUTUBE_LIQUIDITY_SILVER_BULLET_URL = "https://www.youtube.com/watch?v=xnEioNLgNMM"

HTF_OPTIONS = ["1h", "4h", "1d"]
LTF_OPTIONS = ["5m", "15m"]

PHASE_NONE = "NO_SETUP"
PHASE_SWEPT = "LIQUIDITY_SWEEP"
PHASE_MSS_CONFIRMED = "MSS_CONFIRMED"
PHASE_ARMED = "AWAIT_FVG_RETRACEMENT"
PHASE_ENTRY = "SILVER_BULLET_ENTRY"


@dataclass
class LiquiditySilverBulletConfig:
    htf_tf: str = "4h"
    execution_tf: str = "15m"
    fractal_window: int = 2
    displacement_atr_window: int = 14
    displacement_multiplier: float = 1.5
    min_fvg_size_pct: float = 0.0
    mss_max_bars_after_sweep: int = 12
    fvg_max_bars_after_mss: int = 6
    ob_match_window: int = 3
    min_rr: float = 2.0
    session_profile: str | None = None  # auto from market if None
    htf_lookback: int = 300
    ltf_lookback: int = 600
    min_htf_bars: int = 40
    min_ltf_bars: int = 60


def _fetch_tf(
    ticker: str, tf: str, market: str, *, groww_token: str = "", exchange: str = "NSE", limit: int = 400,
) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    df = fetch_data_for_gap_scan(ticker, tf, market, groww_token, exchange, limit=limit)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < 20:
        df = normalize_ohlcv(fetch_ohlcv_yfinance(ticker, tf, is_crypto=is_crypto, limit=limit, market=market))
    return df


def _add_day_high_low(work: pd.DataFrame) -> pd.DataFrame:
    """Day's high/low 'so far' — session-anchored (resets each local
    calendar day), using only bars strictly BEFORE the current one so a
    bar can meaningfully "sweep" that level rather than define it."""
    out = work.copy()
    dates = pd.Series(out.index.date, index=out.index)
    shifted_high = out["high"].shift(1)
    shifted_low = out["low"].shift(1)
    out["day_high_so_far"] = shifted_high.groupby(dates).cummax()
    out["day_low_so_far"] = shifted_low.groupby(dates).cummin()
    return out


def detect_liquidity_sweeps(work: pd.DataFrame, profile: str) -> pd.DataFrame:
    """Wick beyond the day's high/low, during the London or NY session,
    closing back inside — the video's liquidity-sweep trigger."""
    out = work.copy()
    sessions = _sessions_for_profile(profile)
    in_london = [_in_window(ts, *sessions["london"]) for ts in out.index]
    in_ny = [_in_window(ts, *sessions["ny"]) for ts in out.index]
    in_session = pd.Series(in_london, index=out.index) | pd.Series(in_ny, index=out.index)

    dh, dl = out["day_high_so_far"], out["day_low_so_far"]
    out["sweep_high"] = in_session & dh.notna() & (out["high"] > dh) & (out["close"] < dh)
    out["sweep_low"] = in_session & dl.notna() & (out["low"] < dl) & (out["close"] > dl)
    return out


def _find_matching_order_block(order_blocks, *, bullish: bool, near_index: int, window: int):
    candidates = [
        ob for ob in order_blocks
        if ob.bullish == bullish and abs(ob.impulse_index - near_index) <= window
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda ob: abs(ob.impulse_index - near_index))


def scan_liquidity_silver_bullet_signals(
    ltf_tz: pd.DataFrame, cfg: LiquiditySilverBulletConfig, profile: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    work = _add_day_high_low(ltf_tz)
    work = detect_liquidity_sweeps(work, profile)

    smc_df = to_smc_ohlc(ltf_tz)
    smc_cfg = SMCConfig(
        fractal_window=cfg.fractal_window,
        displacement_atr_window=cfg.displacement_atr_window,
        displacement_multiplier=cfg.displacement_multiplier,
        min_fvg_size_pct=cfg.min_fvg_size_pct,
    )
    swings = find_fractal_swings(smc_df, cfg.fractal_window)
    breaks = sorted(detect_structure_breaks(smc_df, swings), key=lambda b: b.index)
    fvgs = sorted(detect_fvgs(smc_df, smc_cfg), key=lambda f: f.index)
    obs = detect_order_blocks(smc_df, smc_cfg)

    signals: list[dict[str, Any]] = []
    state = PHASE_NONE
    sweep_i: int | None = None
    sweep_dir: str | None = None
    mss_i: int | None = None
    fvg_ref = None
    entry_price: float | None = None

    highs = work["high"].to_numpy()
    lows = work["low"].to_numpy()

    for i in range(len(work)):
        if state == PHASE_SWEPT and sweep_i is not None and i - sweep_i > cfg.mss_max_bars_after_sweep:
            state, sweep_i, sweep_dir = PHASE_NONE, None, None
        if state == PHASE_MSS_CONFIRMED and mss_i is not None and i - mss_i > cfg.fvg_max_bars_after_mss:
            state, sweep_i, sweep_dir, mss_i = PHASE_NONE, None, None, None

        if state == PHASE_NONE:
            if bool(work["sweep_high"].iloc[i]):
                state, sweep_i, sweep_dir = PHASE_SWEPT, i, "SELL"
            elif bool(work["sweep_low"].iloc[i]):
                state, sweep_i, sweep_dir = PHASE_SWEPT, i, "BUY"

        elif state == PHASE_SWEPT:
            match = next((
                b for b in breaks if b.index == i and (
                    (sweep_dir == "SELL" and b.event in (StructureEvent.BOS_BEAR, StructureEvent.CHOCH_BEAR))
                    or (sweep_dir == "BUY" and b.event in (StructureEvent.BOS_BULL, StructureEvent.CHOCH_BULL))
                )
            ), None)
            if match:
                state, mss_i = PHASE_MSS_CONFIRMED, i

        elif state == PHASE_MSS_CONFIRMED:
            want_bullish = sweep_dir == "BUY"
            match = next((f for f in fvgs if sweep_i is not None and sweep_i <= f.index <= i and f.bullish == want_bullish), None)
            if match:
                fvg_ref = match
                entry_price = match.ceiling if match.bullish else match.floor
                state = PHASE_ARMED

        elif state == PHASE_ARMED and fvg_ref is not None and entry_price is not None:
            if lows[i] <= entry_price <= highs[i]:
                direction = "LONG" if sweep_dir == "BUY" else "SHORT"
                ob_match = _find_matching_order_block(
                    obs, bullish=(direction == "LONG"), near_index=fvg_ref.index, window=cfg.ob_match_window,
                )
                if direction == "LONG":
                    sl_tight = fvg_ref.floor
                    sl_wide = ob_match.low if ob_match else fvg_ref.floor
                else:
                    sl_tight = fvg_ref.ceiling
                    sl_wide = ob_match.high if ob_match else fvg_ref.ceiling
                signals.append({
                    "bar_index": i, "timestamp": str(work.index[i]), "direction": direction,
                    "entry": float(entry_price), "sl_tight": float(sl_tight), "sl_wide": float(sl_wide),
                    "sweep_index": sweep_i, "mss_index": mss_i, "fvg_index": fvg_ref.index,
                })
                state, sweep_i, sweep_dir, mss_i, fvg_ref, entry_price = PHASE_NONE, None, None, None, None, None

    return signals, {"phase": state, "sweep_dir": sweep_dir}


def evaluate_live_signal(
    work: pd.DataFrame, signals: list[dict[str, Any]], live_state: dict[str, Any],
    cfg: LiquiditySilverBulletConfig, htf_bias_label: str,
) -> dict[str, Any]:
    if work.empty:
        return {"signal": "NO_DATA", "verdict": "NO DATA", "take_trade": False}

    price = float(work["close"].iloc[-1])
    reasons: list[str] = [f"HTF ({cfg.htf_tf}) structure bias: **{htf_bias_label}**."]

    last_idx = len(work) - 1
    last_signal = signals[-1] if signals else None
    is_fresh = bool(last_signal and last_signal["bar_index"] == last_idx)

    verdict, direction, take = "WAIT", "WAIT", False
    entry = stop = target = price
    confidence = 0.0

    if is_fresh and last_signal:
        direction = last_signal["direction"]
        entry = last_signal["entry"]
        stop = last_signal["sl_wide"]
        risk = abs(entry - stop)
        target = entry + risk * cfg.min_rr if direction == "LONG" else entry - risk * cfg.min_rr

        confidence = 65.0
        take = True
        verdict = ("BUY" if direction == "LONG" else "SELL") + " — liquidity sweep + MSS + FVG entry (Silver Bullet)"
        reasons.append(
            f"Liquidity sweep of the day's {'low' if direction == 'LONG' else 'high'} during the London/NY "
            f"session (bar {last_signal['sweep_index']})."
        )
        reasons.append(
            f"Market Structure Shift confirmed at bar {last_signal['mss_index']} — "
            f"{'buyers' if direction == 'LONG' else 'sellers'} took control."
        )
        reasons.append(
            f"Entered on retracement into the Fair Value Gap formed during the shift (bar {last_signal['fvg_index']}) "
            f"at {entry:,.4g}."
        )
        reasons.append(
            f"Stop beyond the extreme order block ({stop:,.4g}) for breathing room — the tighter 'just outside "
            f"the FVG' alternative sits at {last_signal['sl_tight']:,.4g}."
        )
        reasons.append(f"Target set at a minimum 1:{cfg.min_rr:.0f} risk:reward ({target:,.4g}) toward external liquidity.")
    elif live_state.get("phase") == PHASE_ARMED:
        reasons.append("Sweep + Market Structure Shift + Fair Value Gap all confirmed — armed, waiting for price to retrace into the FVG entry zone.")
    elif live_state.get("phase") == PHASE_MSS_CONFIRMED:
        reasons.append("Liquidity sweep + Market Structure Shift confirmed — waiting for a matching Fair Value Gap to form.")
    elif live_state.get("phase") == PHASE_SWEPT:
        reasons.append("Liquidity sweep detected — waiting for a Market Structure Shift to confirm direction.")
    elif last_signal:
        reasons.append(
            f"Most recent qualifying {last_signal['direction']} setup completed at {last_signal['timestamp']} — "
            "not the current candle, so no fresh trigger right now."
        )
    else:
        reasons.append("No liquidity-sweep + MSS + FVG sequence found in the fetched window yet.")

    sl_pct = round(abs(entry - stop) / entry * 100, 2) if take and entry else None
    tp_pct = round(abs(target - entry) / entry * 100, 2) if take and entry else None

    hold_duration = hold_for_tf(cfg.execution_tf, "intraday")

    plan = make_trade_plan(
        direction=direction if take else "—", timeframe=cfg.execution_tf, stop_loss_pct=sl_pct, take_profit_pct=tp_pct,
        confidence_pct=confidence, style="intraday",
        exit_rule=(
            f"Target a minimum 1:{cfg.min_rr:.0f} R:R toward external liquidity; invalidate if price closes "
            "back beyond the order-block stop."
        ),
        max_hold_exit="Session-based (London/NY) setup — not a multi-day hold; time-box to the session.",
    )

    live = enrich_smc_live({
        "signal": direction if take else "NONE",
        "direction": direction if take else None,
        "take_trade": take,
        "verdict": verdict,
        "phase": live_state.get("phase", PHASE_NONE),
        "confidence_pct": confidence if take else 0.0,
        "sl_pct": sl_pct, "tp_pct": tp_pct,
        "entry_price": round(entry, 6) if take else None,
        "stop_price": round(stop, 6) if take else None,
        "target_price": round(target, 6) if take else None,
        "htf_bias": htf_bias_label,
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": hold_duration} if take else None,
    }, hold_duration=hold_duration)

    return live


def analyze_ticker(
    ticker: str, market: str, *, cfg: LiquiditySilverBulletConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or LiquiditySilverBulletConfig()
    profile = _session_profile_for_market(market, cfg.session_profile)

    htf_df = _fetch_tf(ticker, cfg.htf_tf, market, groww_token=groww_token, exchange=exchange, limit=cfg.htf_lookback)
    if htf_df.empty or len(htf_df) < cfg.min_htf_bars:
        return {
            "ticker": ticker, "market": market,
            "error": f"Insufficient {cfg.htf_tf} data ({len(htf_df)} bars) for the HTF trend/range bias.",
        }
    htf_smc = to_smc_ohlc(htf_df)
    htf_swings = find_fractal_swings(htf_smc, cfg.fractal_window)
    htf_breaks = detect_structure_breaks(htf_smc, htf_swings)
    htf_bias = current_bias(htf_breaks)
    htf_bias_label = htf_bias.value.upper() if htf_breaks else "NEUTRAL"

    ltf_df = _fetch_tf(ticker, cfg.execution_tf, market, groww_token=groww_token, exchange=exchange, limit=cfg.ltf_lookback)
    if ltf_df.empty or len(ltf_df) < cfg.min_ltf_bars:
        return {
            "ticker": ticker, "market": market,
            "error": f"Insufficient {cfg.execution_tf} data ({len(ltf_df)} bars).",
        }

    ltf_tz = _ensure_tz(ltf_df, _tz_for_profile(profile))
    if ltf_tz.empty:
        return {"ticker": ticker, "market": market, "error": "Could not timezone-normalize the execution timeframe data."}

    signals, live_state = scan_liquidity_silver_bullet_signals(ltf_tz, cfg, profile)
    live = evaluate_live_signal(ltf_tz, signals, live_state, cfg, htf_bias_label)

    return {
        "ticker": ticker, "market": market, "execution_tf": cfg.execution_tf, "htf_tf": cfg.htf_tf,
        "bars": len(ltf_tz), "last_close": float(ltf_tz["close"].iloc[-1]),
        "signal_history": signals[-8:], "live": live,
    }


def scan_universe(
    tickers: list[str], market: str, *, cfg: LiquiditySilverBulletConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or LiquiditySilverBulletConfig()
    results = []
    for ticker in tickers:
        try:
            results.append(analyze_ticker(ticker, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            logger.debug("Liquidity Silver Bullet scan failed for %s: %s", ticker, exc)
            results.append({"ticker": ticker, "market": market, "error": str(exc)[:200]})

    entries = [r for r in results if not r.get("error") and (r.get("live") or {}).get("take_trade")]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market, "execution_tf": cfg.execution_tf, "htf_tf": cfg.htf_tf, "results": results,
        "entries": entries, "entry_count": len(entries),
    }
