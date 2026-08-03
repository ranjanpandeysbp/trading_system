"""
suggestion_engine.py — "Auto Trade"
------------------------------------
Institutional-style automated suggestion engine. For each (asset_class,
style) bucket it scans a curated universe, runs that bucket's curated set of
engines per ticker, combines them via genuine N-of-M confluence
(`one_click_common.combine_confluence`), folds in fundamentals/FII-DII where
that data exists (India only), applies a trading-judgment layer (reward:risk
floor, ATR-sane stops, momentum-exhaustion guard, liquidity floor, A/B/C
quality grade), and produces a ranked, plain-English-explained shortlist of
BUY/SELL/WAIT suggestions with %confidence, %SL, %TP, entry and target.

Engine sets per bucket are declared as data below so more can be added later
without touching the scoring/combination logic.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

from app.market_pulse import pro_trade_shared as pts
from app.market_pulse.one_click_common import STRICT, LOOSE, Vote, combine_confluence, vote_from_live_schema
from app.models.schemas import ScanRequest
from app.services.scanner_service import ScannerService
from app.services.settings_service import SettingsService
from app.services.trading_hub_service import TradingHubService

logger = logging.getLogger(__name__)

ASSET_CLASSES = ("india", "us", "crypto", "commodity")
STYLES = ("scalping", "intraday", "swing", "investing")

_TIMEFRAME_BY_STYLE: dict[str, str] = {
    "scalping": "3m", "intraday": "15m", "swing": "1d", "investing": "1d",
}

# Base rule strategies (asset-agnostic OHLCV, run live via ScannerService).
_BASE_STRATEGIES_BY_STYLE: dict[str, list[str]] = {
    "scalping": ["vwap_bounce_scalp", "orb_1min_scalp", "ema_crossover_scalp", "bollinger_squeeze_breakout_scalp"],
    "intraday": ["orb_15min_with_retest", "vwap_trend_intraday", "rsi_divergence_intraday", "sr_breakout_pullback_intraday"],
    "swing": ["golden_death_cross_swing", "weekly_rsi_pullback_swing", "consolidation_breakout_swing"],
    "investing": [],  # base strategies aren't a fit at this horizon
}

# Trading Hub engines confirmed to work across Groww India / US / Crypto / Commodity.
_HUB_SECTIONS_BY_STYLE: dict[str, list[str]] = {
    "scalping": [],
    "intraday": ["intraday_london_breakout", "support_resistance"],
    "swing": ["support_resistance", "reversal_strategy", "swing_trend_breakout"],
    "investing": ["swing_trend_velocity"],
}

# PA-VP-SMC (Pro Trade) confluence engine only tags itself intraday/swing.
_PRO_TRADE_LTF_BY_STYLE: dict[str, str] = {"intraday": "15m", "swing": "1d"}

# Institutional desks rarely take a setup below this reward:risk — below the
# floor, direction may be right but the trade itself isn't (downgraded to WAIT).
_RR_FLOOR_BY_STYLE: dict[str, float] = {"scalping": 1.2, "intraday": 1.5, "swing": 2.0, "investing": 2.0}

_DEFAULT_UNIVERSE_CAP = 20
_DEFAULT_TOP_N = 8


def default_universe(asset_class: str, cap: int = _DEFAULT_UNIVERSE_CAP) -> list[str]:
    """Curated liquid universe per asset class — not the whole market, an
    institutional desk works a watchlist, not every listed name."""
    if asset_class == "india":
        from app.market_pulse.ticker_utils import NIFTY_50
        return list(NIFTY_50[:cap])
    if asset_class == "crypto":
        from app.market_pulse.ticker_utils import COINDCX_USDT_TICKERS
        return list(COINDCX_USDT_TICKERS[:cap])
    if asset_class == "commodity":
        from app.market_pulse.commodity_screener_engine import COMMODITY_META
        return [str(meta["yf"]) for meta in COMMODITY_META.values()][:cap]
    try:
        from app.market_pulse.us_index_constituents import get_dow_30
        return list(get_dow_30()[:cap])
    except Exception:
        return ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "SPY", "QQQ", "AMD"][:cap]


def _fetch_df(ticker: str, timeframe: str, asset_class: str, groww_token: str, exchange: str, limit: int = 300):
    from app.market_pulse.asset_class_config import ASSET_CLASS_CONFIG
    from app.market_pulse.gap_trading import fetch_data_for_gap_scan
    from app.market_pulse.mtf_scanner_engine import normalize_ohlcv

    market = str((ASSET_CLASS_CONFIG.get(asset_class) or ASSET_CLASS_CONFIG["india"])["market"])
    df = fetch_data_for_gap_scan(ticker, timeframe, market, groww_token, exchange, limit=limit)
    return normalize_ohlcv(df)


async def _base_strategy_votes(
    ticker: str, strategy_ids: list[str], *, asset_class: str, timeframe: str, settings: SettingsService,
) -> list[Vote]:
    if not strategy_ids:
        return []
    try:
        signals = await ScannerService(settings).scan(ScanRequest(
            tickers=[ticker], strategies=strategy_ids, timeframes=[timeframe], asset_class=asset_class,
        ))
    except Exception as exc:
        logger.debug("Base strategy scan failed for %s: %s", ticker, exc)
        return []

    votes: list[Vote] = []
    for sig in signals:
        direction = "LONG" if sig.action == "BUY" else "SHORT" if sig.action == "SELL" else "WAIT"
        take = sig.action in ("BUY", "SELL")
        entry = sig.price
        sl = tp = None
        if entry and take:
            sl = entry * (1 - sig.sl_pct / 100) if direction == "LONG" else entry * (1 + sig.sl_pct / 100)
            tp = entry * (1 + sig.tp_pct / 100) if direction == "LONG" else entry * (1 - sig.tp_pct / 100)
        votes.append(Vote(
            engine=sig.strategy, direction=direction, confidence=sig.confidence_pct, take=take,
            entry=entry, sl=sl, tp1=tp, tp2=tp, reasons=[sig.rationale] if sig.rationale else [],
        ))
    return votes


async def _hub_votes(
    ticker: str, section_ids: list[str], *, asset_class: str, settings: SettingsService, db: Any,
) -> list[Vote]:
    if not section_ids:
        return []
    svc = TradingHubService(settings, db)
    votes: list[Vote] = []
    for sid in section_ids:
        try:
            payload = await svc.scan(sid, [ticker], asset_class=asset_class)
        except Exception as exc:
            logger.debug("Hub scan %s failed for %s: %s", sid, ticker, exc)
            continue
        rows = payload.get("results") or []
        if not rows or rows[0].get("error"):
            continue
        row = rows[0]
        live = row.get("live") if isinstance(row.get("live"), dict) else row
        votes.append(vote_from_live_schema(sid, {"live": live}))
    return votes


async def _pro_trade_vote(
    ticker: str, style: str, *, asset_class: str, groww_token: str, exchange: str,
) -> Vote | None:
    ltf = _PRO_TRADE_LTF_BY_STYLE.get(style)
    if not ltf:
        return None
    from app.market_pulse.asset_class_config import ASSET_CLASS_CONFIG
    from app.market_pulse.pa_vp_smc_engine import PaVpSmcConfig, analyze_ticker as pa_vp_smc_analyze

    market = str((ASSET_CLASS_CONFIG.get(asset_class) or ASSET_CLASS_CONFIG["india"])["market"])
    try:
        result = await asyncio.to_thread(
            pa_vp_smc_analyze, ticker, market, cfg=PaVpSmcConfig(ltf=ltf),
            groww_token=groww_token, exchange=exchange,
        )
    except Exception as exc:
        logger.debug("PA-VP-SMC failed for %s: %s", ticker, exc)
        return None
    if result.get("error"):
        return None
    return vote_from_live_schema("pa_vp_smc", {"live": result})


async def _fundamentals_note(ticker: str, direction: str, confidence: float) -> tuple[float, str | None]:
    """India-only. Returns (confidence_delta, plain-english note)."""
    try:
        from app.market_pulse.fundamentals_combine import combine_with_fundamentals
        result = await asyncio.to_thread(combine_with_fundamentals, ticker, direction, confidence)
    except Exception as exc:
        logger.debug("Fundamentals combine failed for %s: %s", ticker, exc)
        return 0.0, None
    if result.get("error"):
        return 0.0, None
    new_conf = result.get("combined_confidence_pct")
    delta = (new_conf - confidence) if new_conf is not None else 0.0
    return delta, result.get("note")


async def _fii_dii_note(ticker: str) -> tuple[float, str | None]:
    """India-only, "investing" style — folds in FII/DII/promoter ownership
    trend + revenue/profit/valuation timing verdict."""
    try:
        from app.market_pulse.india_fii_dii_holdings_engine import analyze_ticker_shareholding
        today = date.today()
        result = await asyncio.to_thread(
            analyze_ticker_shareholding, ticker, today - timedelta(days=365), today,
        )
    except Exception as exc:
        logger.debug("FII/DII fetch failed for %s: %s", ticker, exc)
        return 0.0, None
    if result.get("error"):
        return 0.0, None
    timing = result.get("timing") or {}
    verdict = timing.get("verdict")
    delta = 6.0 if verdict == "YES" else (-6.0 if verdict == "NO" else 0.0)
    return delta, timing.get("tone")


def explain_suggestion_plain_english(
    *, ticker: str, action: str, confidence: float, grade: str, rr: float | None,
    n_agree: int, n_total: int, sl_pct: float | None, tp_pct: float | None,
) -> str:
    """One short narrative paragraph per suggestion — not a list of jargon
    reason strings. This is what lets someone who isn't a trader understand
    (and correctly trust or distrust) what the engine is telling them."""
    if action == "WAIT":
        return (
            f"{ticker} — not a clean enough setup right now. Some signals point one way, but the risk/reward "
            f"or overall trade quality doesn't clear the bar, so this is a WAIT rather than a real entry."
        )
    verb = "BUY" if action == "BUY" else "SELL"
    agree_txt = f"{n_agree} of {n_total} independent signals agree on the direction" if n_total > 1 else "the read agrees on direction"
    if sl_pct and tp_pct and rr:
        quality = "a strong" if rr >= 2.5 else ("a solid" if rr >= 2.0 else "an acceptable")
        risk_txt = f"you'd be risking about {sl_pct:.1f}% to make roughly {tp_pct:.1f}% — {quality} {rr:.1f}-to-1 reward for the risk"
    else:
        risk_txt = "risk/reward could not be precisely sized from the available data"
    grade_txt = {
        "A": "a high-quality setup on every check — confidence, risk/reward, and liquidity all line up",
        "B": "a solid setup, with at least one caveat worth knowing before sizing the trade",
        "C": "a marginal setup that only just cleared the bar — size small, or skip it if you're selective",
    }[grade]
    return (
        f"{ticker} looks like a {verb} here — {agree_txt}. {risk_txt.capitalize()}. "
        f"Confidence: {confidence:.0f}/100, grade {grade} — {grade_txt}."
    )


async def evaluate_ticker(
    ticker: str, asset_class: str, style: str, *, settings: SettingsService, db: Any,
    direction_filter: str = "both",
) -> dict[str, Any] | None:
    """Full pipeline for one ticker: vote, combine, fold in fundamentals,
    apply the trading-judgment layer, grade, and explain. Returns None when
    there's no directional agreement, or when the combined direction doesn't
    match `direction_filter` ("both" | "long_only" | "short_only") — a
    suggestion list only shows real, wanted ideas, not a dump of every
    ticker scanned."""
    timeframe = _TIMEFRAME_BY_STYLE[style]
    is_india = asset_class == "india"
    groww_token = (await settings.get_groww_token() or "") if is_india else ""
    exchange = (await settings.get_groww_exchange()) if is_india else "NSE"

    votes: list[Vote] = []
    votes += await _base_strategy_votes(
        ticker, _BASE_STRATEGIES_BY_STYLE.get(style, []), asset_class=asset_class, timeframe=timeframe, settings=settings,
    )
    votes += await _hub_votes(ticker, _HUB_SECTIONS_BY_STYLE.get(style, []), asset_class=asset_class, settings=settings, db=db)
    pt_vote = await _pro_trade_vote(ticker, style, asset_class=asset_class, groww_token=groww_token, exchange=exchange)
    if pt_vote:
        votes.append(pt_vote)

    if not votes:
        return None

    combined = combine_confluence(votes, strictness=LOOSE if style == "scalping" else STRICT)
    direction = combined["direction"]
    if direction == "WAIT":
        return None
    if direction_filter == "long_only" and direction != "LONG":
        return None
    if direction_filter == "short_only" and direction != "SHORT":
        return None

    confidence = combined["confidence_pct"]
    reasons: list[str] = list(combined["reasons"])
    fundamentals_delta = 0.0

    if is_india and style in ("swing", "investing"):
        delta, note = await _fundamentals_note(ticker, direction, confidence)
        fundamentals_delta += delta * (1.0 if style == "investing" else 0.5)
        if note:
            reasons.append(note)

    if is_india and style == "investing":
        delta, note = await _fii_dii_note(ticker)
        fundamentals_delta += delta
        if note:
            reasons.append(f"FII/DII & fundamentals timing: {note}")

    confidence = max(0.0, min(96.0, confidence + fundamentals_delta))

    entry = combined["entry_price"]
    stop = combined["stop_price"]
    target = combined["target1_price"] or combined["target2_price"]

    df = await asyncio.to_thread(_fetch_df, ticker, timeframe, asset_class, groww_token, exchange)
    atr_value = rsi_value = vol_z = None
    if df is not None and not df.empty and len(df) >= 20:
        try:
            atr_value = float(pts.atr(df).iloc[-1])
            rsi_value = float(pts.rsi(df["close"]).iloc[-1])
            if "volume" in df.columns:
                vol_z = float(pts.volume_zscore(df["volume"]).iloc[-1])
        except Exception:
            pass

    stop_adjusted = False
    if entry and stop and atr_value:
        new_stop, new_target, stop_adjusted = pts.atr_sane_stop_target(direction, entry, stop, target, atr_value)
        if stop_adjusted:
            reasons.append(
                "Stop/target re-derived from this instrument's actual volatility (ATR) — "
                "the raw engine stop looked too tight or too wide for real conditions."
            )
        stop, target = new_stop, new_target

    momentum_delta, momentum_note = pts.momentum_exhaustion_note(rsi_value, direction)
    if momentum_note:
        confidence = max(0.0, confidence + momentum_delta)
        reasons.append(momentum_note)

    liquidity_is_ok = pts.liquidity_ok(vol_z) if style in ("scalping", "intraday") else True
    if not liquidity_is_ok:
        reasons.append("Volume is abnormally thin vs. this ticker's own recent history — real slippage risk for a fast-timeframe trade.")

    sl_pct, tp_pct = pts.sl_tp_pct(direction, entry, stop, target) if entry else (None, None)
    rr = pts.rr_ratio(sl_pct, tp_pct)
    rr_floor = _RR_FLOOR_BY_STYLE[style]

    action = "BUY" if direction == "LONG" else "SELL"
    if not pts.meets_rr_floor(sl_pct, tp_pct, rr_floor):
        action = "WAIT"
        reasons.append(
            f"Direction looks {direction.lower()}, but reward-for-risk ({rr or 0:.1f}:1) doesn't clear "
            f"this style's {rr_floor}:1 bar — not acted on."
        )
    elif style in ("scalping", "intraday") and not liquidity_is_ok:
        action = "WAIT"

    grade = pts.quality_grade(confidence, rr, liquidity_is_ok, stop_adjusted)
    plain_english = explain_suggestion_plain_english(
        ticker=ticker, action=action, confidence=confidence, grade=grade, rr=rr,
        n_agree=combined["n_agree"], n_total=combined["n_total"], sl_pct=sl_pct, tp_pct=tp_pct,
    )

    return {
        "ticker": ticker,
        "action": action,
        "confidence_pct": round(confidence, 1),
        "grade": grade,
        "entry_price": entry,
        "sl_pct": sl_pct,
        "tp_pct": tp_pct,
        "stop_price": stop,
        "target_price": target,
        "reasons": reasons,
        "plain_english": plain_english,
    }


async def run_bucket(
    asset_class: str,
    style: str,
    *,
    settings: SettingsService,
    db: Any,
    universe_cap: int = _DEFAULT_UNIVERSE_CAP,
    top_n: int = _DEFAULT_TOP_N,
    direction_filter: str = "both",
    progress_cb: Any = None,
) -> list[dict[str, Any]]:
    universe = await asyncio.to_thread(default_universe, asset_class, universe_cap)
    suggestions: list[dict[str, Any]] = []
    for i, ticker in enumerate(universe):
        try:
            row = await evaluate_ticker(ticker, asset_class, style, settings=settings, db=db, direction_filter=direction_filter)
            if row:
                suggestions.append(row)
        except Exception:
            logger.exception("Suggestion engine failed for %s/%s/%s", asset_class, style, ticker)
        if progress_cb:
            progress_cb((i + 1) / max(1, len(universe)), f"{asset_class}/{style}: {ticker}")
        await asyncio.sleep(0.2)  # stagger — good citizen with NSE/Yahoo/CoinDCX rate limits

    suggestions.sort(key=lambda s: s["confidence_pct"], reverse=True)
    ranked = suggestions[:top_n]
    for i, s in enumerate(ranked, start=1):
        s["rank"] = i
    return ranked
