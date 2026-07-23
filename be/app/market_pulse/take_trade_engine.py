"""
take_trade_engine.py
----------------------
Command Center — Take Trade: runs every drill-down analysis already offered as a
checkbox in the Trade Setup section (momentum, volume, quick analyzer, candlestick/
chart patterns, smart money, scalping, time series, divergences, support/resistance,
stock upgrade/downgrade, fundamentals, option chain), combines them into one
BUY / SELL / WAIT verdict with a composite confidence %, and pairs that verdict with
a recommended stop-loss and take-profit (each in price and % from current price) from
this app's Stop Loss Hunting and Take Profit Targets engines.

Nothing here reimplements indicator logic — every check is a call into the same
engine Trade Setup's matching checkbox already uses. The only new code is the
vote-extraction glue and the final confluence combine (reusing one_click_common.py's
Vote / combine_confluence framework, the same one behind the One-Click Trade Setup
and Smart Money/Scalping/Time Series combos already in this app).
"""

from __future__ import annotations

import logging
from typing import Any

from app.market_pulse.divergence_engine import analyze_ticker as divergence_analyze_ticker
from app.market_pulse.fundamental_analysis_engine import analyze_ticker as fa_analyze_ticker
from app.market_pulse.momentum_engine import MomentumConfig
from app.market_pulse.momentum_engine import analyze_ticker as momentum_analyze_ticker
from app.market_pulse.one_click_common import (
    STRICT,
    Vote,
    combine_confluence,
    fundamental_gate,
    normalize_direction,
    vote_from_live_schema,
)
from app.market_pulse.option_chain_engine import classify_option_chain_signal, fetch_option_chain
from app.market_pulse.pattern_engine import analyze_ticker as pattern_analyze_ticker
from app.market_pulse.quick_analyzer_engine import analyze_quick, detect_breakout_breakdown
from app.market_pulse.sma_20_200_engine import Sma20200Config
from app.market_pulse.sma_20_200_engine import analyze_ticker as sma_20_200_analyze_ticker
from app.market_pulse.stock_upgrade_downgrade_engine import scan_ticker as scan_upgrade_downgrade_ticker
from app.market_pulse.stop_hunt_engine import analyze_ticker as stop_hunt_analyze_ticker
from app.market_pulse.take_profit_engine import analyze_ticker as take_profit_analyze_ticker
from app.market_pulse.trade_setup_engine import _fetch_ohlcv as _sr_fetch_ohlcv
from app.market_pulse.trade_setup_engine import (
    analyze_intra_hwp_one,
    analyze_scalping_confluence_one,
    analyze_smart_money_one,
    analyze_time_series_one,
    analyze_weak_strong_one,
)

logger = logging.getLogger(__name__)

__all__ = ["analyze_ticker", "analyze_ticker_multi_tf", "analyze_tickers_multi_tf"]

MIN_AGREE_STRICT = 4
MIN_AGREE_LOOSE = 2
TAKE_THRESHOLD_STRICT = 62.0
TAKE_THRESHOLD_LOOSE = 52.0


def _vote_from_combo(engine: str, combo: dict | None) -> Vote:
    if not combo:
        return Vote(engine=engine, direction="WAIT", confidence=0.0, take=False, error="No result")
    return Vote(
        engine=engine,
        direction=combo.get("direction", "WAIT"),
        confidence=float(combo.get("confidence_pct") or 0.0),
        take=bool(combo.get("take_trade")),
        entry=combo.get("entry_price"),
        sl=combo.get("stop_price"),
        tp1=combo.get("target1_price"),
        tp2=combo.get("target2_price"),
        reasons=(combo.get("reasons") or [])[:2],
    )


def _vote_from_momentum(mom_res: dict) -> Vote:
    if not mom_res or mom_res.get("error"):
        return Vote(engine="Momentum", direction="WAIT", confidence=0.0, take=False,
                     error=mom_res.get("error") if mom_res else "No result")
    action = mom_res.get("actionability") or {}
    bucket = action.get("bucket")
    direction = normalize_direction(action.get("direction"))
    conf = float(mom_res.get("confidence_continue_pct") or 0.0)
    if direction in ("LONG", "SHORT") and conf <= 0.0:
        # A CONSOLIDATING-with-breakout-lean read still yields a direction, but
        # confidence_continue_pct only gets populated for a genuine UP/DOWN trend —
        # fall back to the breakout-lean strength itself rather than reporting a
        # misleading 0%, which would otherwise drag the composite average down for
        # what is still a real (if lower-conviction) directional read.
        bo_up = mom_res.get("breakout_up_pct")
        bo_down = mom_res.get("breakout_down_pct")
        lean = bo_up if direction == "LONG" else bo_down
        conf = float(lean) if lean is not None else 45.0
    take = bucket == "ACTIONABLE"
    reasons = [action.get("reason")] if action.get("reason") else []
    if mom_res.get("overall_direction") == "CONSOLIDATING":
        bo_up = mom_res.get("breakout_up_pct")
        bo_down = mom_res.get("breakout_down_pct")
        if bo_up is not None and bo_down is not None:
            # Always lead with the numeric breakout odds — action.get("reason") only mentions
            # a % when the lean already clears the WATCH threshold, so a below-threshold
            # consolidation (still directionally interesting) would otherwise show no numbers.
            reasons.insert(0, f"⚖️ Breakout lean: {bo_up:.0f}% chance of breaking UP vs {bo_down:.0f}% DOWN")
    return Vote(engine="Momentum", direction=direction, confidence=conf, take=take, reasons=reasons)


def _volume_note(mom_res: dict) -> str | None:
    per_tf = (mom_res or {}).get("per_tf") or []
    if not per_tf:
        return None
    ratio = per_tf[0].get("volume_ratio")
    if ratio is None:
        return None
    tier = (
        "very high" if ratio >= 2.0 else "high" if ratio >= 1.5 else "above average" if ratio >= 1.1
        else "average" if ratio >= 0.9 else "below average" if ratio >= 0.7 else "very low"
    )
    return f"📊 Volume: {ratio:.2f}x average ({tier}) — confirms conviction when it agrees with the verdict's direction."


def _vote_from_quick_analyzer(qa_res: dict) -> Vote:
    if not qa_res or qa_res.get("error"):
        return Vote(engine="Quick Analyzer", direction="WAIT", confidence=0.0, take=False,
                     error=qa_res.get("error") if qa_res else "No result")
    setup = qa_res.get("setup") or {}
    direction = normalize_direction(setup.get("direction"))
    conf = float(setup.get("confidence_pct") or 0.0)
    return Vote(engine="Quick Analyzer", direction=direction, confidence=conf,
                take=direction in ("LONG", "SHORT"), reasons=(setup.get("reasons") or [])[:2])


def _vote_from_pattern(pat_res: dict) -> Vote:
    if not pat_res or pat_res.get("error"):
        return Vote(engine="Candlestick/Chart Patterns", direction="WAIT", confidence=0.0, take=False,
                     error=pat_res.get("error") if pat_res else "No result")
    direction = normalize_direction(pat_res.get("bias"))
    conf = float(pat_res.get("confidence_pct") or 0.0)
    return Vote(engine="Candlestick/Chart Patterns", direction=direction, confidence=conf,
                take=False, reasons=(pat_res.get("reasons") or [])[:2])


def _vote_from_divergence(div_res: dict) -> Vote:
    if not div_res or div_res.get("error"):
        return Vote(engine="Divergences", direction="WAIT", confidence=0.0, take=False,
                     error=div_res.get("error") if div_res else "No result")
    direction = normalize_direction(div_res.get("bias"))
    conf = float(div_res.get("confidence_pct") or 0.0)
    return Vote(engine="Divergences", direction=direction, confidence=conf,
                take=False, reasons=(div_res.get("reasons") or [])[:2])


def _sr_vote(ticker: str, market: str, tf: str, groww: str, exchange: str) -> Vote:
    try:
        cfg = MomentumConfig(timeframes=[tf])
        df = _sr_fetch_ohlcv(ticker, market, tf, cfg, groww_token=groww, exchange=exchange)
    except Exception as exc:
        return Vote(engine="Support/Resistance", direction="WAIT", confidence=0.0, take=False, error=str(exc)[:200])
    if df.empty:
        return Vote(engine="Support/Resistance", direction="WAIT", confidence=0.0, take=False, error="No data")
    breakout = detect_breakout_breakdown(df)
    event = breakout.get("event", "NONE")
    vol_confirmed = bool(breakout.get("volume_confirmed"))
    if event == "RESISTANCE_BREAKOUT":
        return Vote(engine="Support/Resistance", direction="LONG", confidence=70.0 if vol_confirmed else 55.0,
                     take=vol_confirmed, reasons=["Resistance breakout" + (" (volume-confirmed)" if vol_confirmed else "")])
    if event == "SUPPORT_BREAKDOWN":
        return Vote(engine="Support/Resistance", direction="SHORT", confidence=70.0 if vol_confirmed else 55.0,
                     take=vol_confirmed, reasons=["Support breakdown" + (" (volume-confirmed)" if vol_confirmed else "")])
    return Vote(engine="Support/Resistance", direction="WAIT", confidence=0.0, take=False,
                reasons=["No fresh breakout/breakdown — price inside its recent range"])


def _vote_from_upgrade_downgrade(ud_res: dict) -> Vote:
    if not ud_res or ud_res.get("error"):
        return Vote(engine="Stock Upgrade Downgrade", direction="WAIT", confidence=0.0, take=False,
                     error=ud_res.get("error") if ud_res else "No result")
    consensus = ud_res.get("consensus") or {}
    label = consensus.get("consensus", "NO DATA")
    direction = normalize_direction(label)
    buy, sell = consensus.get("buy", 0), consensus.get("sell", 0)
    conf = min(85.0, 45.0 + abs(buy - sell) * 8.0) if (buy or sell) else 0.0
    reasons = [f"Analyst consensus: {label} ({buy} buy / {sell} sell / {consensus.get('hold', 0)} hold calls)"]
    return Vote(engine="Stock Upgrade Downgrade", direction=direction, confidence=conf, take=False, reasons=reasons)


def _vote_from_option_chain(ticker: str, groww: str) -> Vote:
    try:
        chain = fetch_option_chain(ticker, False, groww)
    except Exception as exc:
        return Vote(engine="Option Chain", direction="WAIT", confidence=0.0, take=False, error=str(exc)[:200])
    if not chain:
        return Vote(engine="Option Chain", direction="WAIT", confidence=0.0, take=False,
                     error="No listed F&O contracts, or NSE is rate-limiting")
    res = classify_option_chain_signal(chain)
    direction = normalize_direction(res.get("trade_signal") or res.get("bias"))
    conf = float(res.get("confidence_pct") or 0.0)
    return Vote(engine="Option Chain", direction=direction, confidence=conf,
                take=res.get("trade_signal") in ("BUY", "SELL"), reasons=(res.get("reasons") or [])[:2])


def _pick_stop(sh_res: dict, direction: str) -> dict | None:
    if not sh_res or sh_res.get("error") or direction not in ("LONG", "SHORT"):
        return None
    stops = sh_res.get("long_stops") if direction == "LONG" else sh_res.get("short_stops")
    if not stops:
        return None
    return {
        "recommended": stops["safe"],
        "aggressive": stops["tight"],
        "anchor_label": stops["anchor"]["label"],
        "hunt_status": sh_res.get("hunt_status"),
    }


def _pick_target(tp_res: dict, direction: str) -> dict | None:
    if not tp_res or tp_res.get("error") or direction not in ("LONG", "SHORT"):
        return None
    targets = tp_res.get("long_targets") if direction == "LONG" else tp_res.get("short_targets")
    if not targets:
        return None
    return {
        "recommended": targets["tp1"],
        "extended": targets["tp2"],
        "anchor_label": targets["tp1_anchor"]["label"],
        "tp_status": tp_res.get("tp_status"),
    }


def analyze_ticker(
    ticker: str, timeframe: str, asset_class: str, market: str, *, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    india = asset_class == "india"
    votes: list[Vote] = []
    context_notes: list[str] = []

    mom_res = momentum_analyze_ticker(
        ticker, market, cfg=MomentumConfig(timeframes=[timeframe]), groww_token=groww_token, exchange=exchange,
    )
    votes.append(_vote_from_momentum(mom_res))
    vol_note = _volume_note(mom_res)
    if vol_note:
        context_notes.append(vol_note)

    qa_res = analyze_quick(ticker, [timeframe], market, groww_token=groww_token, exchange=exchange)
    votes.append(_vote_from_quick_analyzer(qa_res))

    pat_res = pattern_analyze_ticker(ticker, timeframe, market, groww_token=groww_token, exchange=exchange)
    votes.append(_vote_from_pattern(pat_res))

    sm_res = analyze_smart_money_one(ticker, timeframe, market, groww_token=groww_token, exchange=exchange)
    votes.append(_vote_from_combo("Smart Money", sm_res.get("combo") if sm_res else None))

    scalp_res = analyze_scalping_confluence_one(ticker, timeframe, market, groww_token=groww_token, exchange=exchange)
    votes.append(_vote_from_combo("Scalping", scalp_res.get("combo") if scalp_res else None))

    ts_res = analyze_time_series_one(ticker, timeframe, market, groww_token=groww_token, exchange=exchange)
    votes.append(_vote_from_combo("Time Series", ts_res.get("combo") if ts_res else None))

    div_res = divergence_analyze_ticker(ticker, timeframe, market, groww_token=groww_token, exchange=exchange)
    votes.append(_vote_from_divergence(div_res))

    votes.append(_sr_vote(ticker, market, timeframe, groww_token, exchange))

    # Fixed 5m strategy per its own definition — ignores the row's selected
    # timeframe, same convention as other fixed-TF composites in this engine.
    hwp_res = analyze_intra_hwp_one(ticker, timeframe, market, groww_token=groww_token, exchange=exchange)
    votes.append(vote_from_live_schema("Intra HWP", hwp_res))

    ws_res = analyze_weak_strong_one(ticker, timeframe, market, groww_token=groww_token, exchange=exchange)
    votes.append(vote_from_live_schema("Weak / Strong", ws_res))

    sma_res = sma_20_200_analyze_ticker(
        ticker, market, timeframe, cfg=Sma20200Config(), groww_token=groww_token, exchange=exchange,
    )
    votes.append(vote_from_live_schema("200SMA-20SMA", sma_res))

    ud_res = scan_upgrade_downgrade_ticker(ticker, market, max_items=8)
    votes.append(_vote_from_upgrade_downgrade(ud_res))

    fundamental_note = None
    if india:
        fa_res = fa_analyze_ticker(ticker)
        lean, conf, note = fundamental_gate(fa_res)
        votes.append(Vote(engine="Fundamentals", direction=lean, confidence=conf, take=False, reasons=[note]))
        fundamental_note = note

        votes.append(_vote_from_option_chain(ticker, groww_token))

    combo = combine_confluence(
        votes, strictness=STRICT,
        min_agree_strict=MIN_AGREE_STRICT, min_agree_loose=MIN_AGREE_LOOSE,
        take_threshold_strict=TAKE_THRESHOLD_STRICT, take_threshold_loose=TAKE_THRESHOLD_LOOSE,
        fundamental_note=fundamental_note,
    )
    direction = combo["direction"]

    sh_res = stop_hunt_analyze_ticker(ticker, timeframe, market, groww_token=groww_token, exchange=exchange)
    tp_res = take_profit_analyze_ticker(ticker, timeframe, market, groww_token=groww_token, exchange=exchange)
    stop = _pick_stop(sh_res, direction)
    target = _pick_target(tp_res, direction)

    price = None
    per_tf_mom = (mom_res or {}).get("per_tf") or []
    if per_tf_mom:
        price = per_tf_mom[0].get("price")
    if price is None:
        price = sh_res.get("price") if sh_res and not sh_res.get("error") else None

    return {
        "ticker": ticker, "market": market, "timeframe": timeframe, "asset_class": asset_class,
        "price": price,
        "verdict": combo["verdict"],
        "direction": direction,
        "take_trade": combo["take_trade"],
        "confidence_pct": combo["confidence_pct"],
        "n_agree": combo["n_agree"],
        "n_total": combo["n_total"],
        "min_agree_required": combo["min_agree_required"],
        "take_threshold": combo["take_threshold"],
        "stop": stop,
        "target": target,
        "votes": combo["votes"],
        "reasons": combo["reasons"],
        "context_notes": context_notes,
    }


def analyze_ticker_multi_tf(
    ticker: str, timeframes: list[str], asset_class: str, market: str, *, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    per_tf: dict[str, dict[str, Any]] = {}
    for tf in timeframes:
        try:
            per_tf[tf] = analyze_ticker(ticker, tf, asset_class, market, groww_token=groww_token, exchange=exchange)
        except Exception as exc:
            logger.debug("Take-trade analysis failed for %s %s: %s", ticker, tf, exc)
            per_tf[tf] = {"ticker": ticker, "market": market, "timeframe": tf, "error": str(exc)[:200]}
    return {"ticker": ticker, "market": market, "per_tf": per_tf}


def analyze_tickers_multi_tf(
    tickers: list[str], timeframes: list[str], asset_class: str, market: str, *, groww_token: str = "", exchange: str = "NSE",
) -> list[dict[str, Any]]:
    return [
        analyze_ticker_multi_tf(ticker, timeframes, asset_class, market, groww_token=groww_token, exchange=exchange)
        for ticker in tickers
    ]
