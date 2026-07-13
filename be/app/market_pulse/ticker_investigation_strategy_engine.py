"""
ticker_investigation_strategy_engine.py
---------------------------------------
Ticker investigation + user-selected strategy engines (news/TA investigation unchanged).

Hub strategies (swing/intraday/scalping/smart_money) are dispatched dynamically via
app.trading_hubs.registry.get_section() — the module + analyze_ticker(ticker, market,
groww_token=, exchange=) call convention is uniform across all of them — so this file
never needs a hardcoded id -> module map that could drift from the registry.

TA screener strategies each have their own analyzer function signature (some take an
already-fetched OHLCV frame, some fetch internally, some are crypto-only), so those are
dispatched explicitly below, mirroring the original truebacktesting source. A handful of
TA screener ids registered in app.market_pulse.ta_screener_registry (pump_dump_breakout,
big_whale, zireman_confluence, sentiment_screener) have no equivalent dispatch wired here
— they weren't wired in the original source either and have custom, non-single-ticker
signatures — so selecting them degrades gracefully to `{"error": "Unknown strategy: ..."}`
rather than crashing the whole investigation.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from app.market_pulse.fakeout_15m_engine import normalize_ohlcv, run_fakeout_screener as run_fakeout_15m
from app.market_pulse.fakeout_4h_engine import run_fakeout_screener as run_fakeout_4h, session_mode_for_market
from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.mtf_scanner_engine import analyze_ticker as analyze_mtf_ticker
from app.market_pulse.ticker_investigation_engine import ASSET_CONFIG, investigate_ticker
from app.market_pulse.market_pulse_feeds import fetch_analyst_calls_pool
from app.market_pulse.ticker_investigation_strategy_catalog import strategy_label
from app.market_pulse.ticker_utils import is_crypto_market
from app.trading_hubs.registry import get_section

logger = logging.getLogger(__name__)


def _run_hub_analyze(strategy_id: str, ticker: str, market: str, *, groww_token: str, exchange: str) -> dict:
    """Dispatch to a trading_hubs strategy section registered in HUB_SECTIONS — looked
    up live so this never drifts from the registry's actual catalog."""
    section = get_section(strategy_id)
    if not section:
        return {"error": f"Unknown hub strategy: {strategy_id}"}
    return section["module"].analyze_ticker(ticker, market, groww_token=groww_token, exchange=exchange)


def run_strategy_live_analysis(
    strategy_id: str,
    ticker: str,
    market: str,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    """Run one strategy's live analyzer; returns engine payload or {error: ...}."""
    session_mode = session_mode_for_market(market)
    is_crypto = is_crypto_market(market)

    try:
        if get_section(strategy_id):
            return _run_hub_analyze(strategy_id, ticker, market, groww_token=groww_token, exchange=exchange)

        if strategy_id == "weak_strong_sr":
            from app.market_pulse.weak_strong_sr_engine import analyze_weak_strong_sr
            df = normalize_ohlcv(
                fetch_data_for_gap_scan(ticker, "15m", market, groww_token, exchange, limit=400),
            )
            if df.empty or len(df) < 25:
                return {"error": f"Insufficient 15m data ({len(df)} bars)"}
            return analyze_weak_strong_sr(df, chart_tf="15m", is_crypto=is_crypto)

        if strategy_id == "fakeout_15m":
            df = normalize_ohlcv(
                fetch_data_for_gap_scan(ticker, "1m", market, groww_token, exchange, limit=400),
            )
            if df.empty or len(df) < 25:
                return {"error": f"Insufficient 1m data ({len(df)} bars)"}
            out = run_fakeout_15m(df, session_mode=session_mode)
            out["execution_tf"] = "1m"
            return out

        if strategy_id == "fakeout_4h":
            df = normalize_ohlcv(
                fetch_data_for_gap_scan(ticker, "5m", market, groww_token, exchange, limit=400),
            )
            if df.empty or len(df) < 25:
                return {"error": f"Insufficient 5m data ({len(df)} bars)"}
            out = run_fakeout_4h(df, session_mode=session_mode)
            out["execution_tf"] = "5m"
            return out

        if strategy_id == "mtf_scanner":
            tfs = ["15m", "1h", "4h", "1d"]
            return analyze_mtf_ticker(ticker, tfs, market, groww_token, exchange, 300)

        if strategy_id == "top_down_mtf":
            from app.market_pulse.top_down_mtf_engine import analyze_top_down
            return analyze_top_down(ticker, "1h", "15m", "5m", market, groww_token, exchange, 300)

        if strategy_id == "topdown_mtf":
            from app.market_pulse.topdown_mtf_engine import TopdownMtfConfig, analyze_ticker as analyze_topdown
            return analyze_topdown(
                ticker, market, cfg=TopdownMtfConfig(), groww_token=groww_token, exchange=exchange,
            )

        if strategy_id == "weekly_stoch":
            from app.market_pulse.weekly_stoch_sweet_spot_engine import analyze_weekly_stoch
            return analyze_weekly_stoch(ticker, market, groww_token, exchange, period="5y")

        if strategy_id == "kn_smart_rsi":
            from app.market_pulse.kn_smart_rsi_engine import MTF_DEFAULT, analyze_kn_smart
            return analyze_kn_smart(ticker, market, "5m", list(MTF_DEFAULT), groww_token, exchange, 400)

        if strategy_id == "velez_retracement":
            from app.market_pulse.velez_retracement_engine import analyze_velez, fetch_velez_data
            df = fetch_velez_data(ticker, "5m", market, groww_token, exchange, limit=600)
            if df.empty or len(df) < 220:
                return {"error": f"Insufficient Velez data ({len(df)} bars)"}
            return analyze_velez(df, chart_tf="5m")

        if strategy_id == "smart_wave_crypto":
            if not is_crypto:
                return {"error": "CoinDCX market only"}
            from app.market_pulse.smart_wave_crypto_engine import STRATEGY_KEYS, analyze_smart_wave
            return analyze_smart_wave(
                ticker, market=market, strategies=list(STRATEGY_KEYS),
                primary_tf="30m", groww_token=groww_token, exchange=exchange,
            )

        if strategy_id == "crypto_scalping":
            if not is_crypto:
                return {"error": "CoinDCX market only"}
            from app.market_pulse.crypto_scalping_engine import analyze_crypto_scalping, fetch_scalping_data
            df = fetch_scalping_data(ticker, "5m", market, groww_token, exchange, limit=800)
            live = analyze_crypto_scalping(df, chart_tf="5m")
            if live.get("phase") == "NO_DATA":
                return {"error": live.get("primary_label", "No data")}
            return live

        if strategy_id == "smc_fake_shift":
            from app.market_pulse.smc_fake_market_shift_engine import analyze_smc_fake_market_shift, fetch_fms_data
            df = fetch_fms_data(ticker, "15m", market, groww_token, exchange, limit=600)
            return analyze_smc_fake_market_shift(df, chart_tf="15m")

        if strategy_id == "bb_exposed":
            from app.market_pulse.bb_exposed_engine import analyze_bb_exposed
            return analyze_bb_exposed(ticker, market, "15m", groww_token=groww_token, exchange=exchange)

        if strategy_id == "breakout_mtf":
            from app.market_pulse.breakout_mtf_engine import analyze_breakout_mtf
            return analyze_breakout_mtf(ticker, market, groww_token=groww_token, exchange=exchange)

        if strategy_id == "one_ta":
            from app.market_pulse.one_ta_engine import analyze_one_ta
            return analyze_one_ta(ticker, market, "1h", groww_token=groww_token, exchange=exchange)

        if strategy_id == "box_trading":
            from app.market_pulse.box_trading_engine import BoxTradingConfig, analyze_ticker as analyze_box
            cfg = BoxTradingConfig(execution_tf="5m")
            return analyze_box(ticker, market, cfg=cfg, groww_token=groww_token, exchange=exchange)

        return {"error": f"Unknown strategy: {strategy_id}"}
    except Exception as exc:
        logger.warning("Strategy %s failed for %s: %s", strategy_id, ticker, exc)
        return {"error": str(exc)[:200]}


def analysis_to_setup(strategy_id: str, analysis: dict[str, Any]) -> dict[str, Any] | None:
    """Convert a hub/TA engine payload → investigation setup dict."""
    if analysis.get("error"):
        return None

    live = analysis.get("live") or analysis
    plan = live.get("trade_plan") or analysis.get("trade_plan") or {}
    label = strategy_label(strategy_id)

    conf = float(
        live.get("confidence_pct")
        or live.get("confidence")
        or analysis.get("confidence")
        or plan.get("confidence_pct")
        or 0
    )
    direction = str(live.get("direction") or analysis.get("direction") or "WAIT").upper()
    verdict = str(live.get("verdict") or analysis.get("verdict") or analysis.get("primary_label") or "")
    if direction in ("WAIT", "—", "NONE", ""):
        if "LONG" in verdict.upper() or verdict.upper() == "BUY":
            direction = "LONG"
        elif "SHORT" in verdict.upper() or verdict.upper() == "SELL":
            direction = "SHORT"

    take = bool(
        live.get("take_trade")
        or analysis.get("take_trade")
        or analysis.get("actionable")
    )
    forming = take or "WATCH" in verdict.upper() or bool(live.get("forming"))

    sl = float(live.get("sl_pct") or plan.get("stop_loss_pct") or 2.0)
    tp = float(live.get("tp_pct") or plan.get("take_profit_pct") or sl * 2)
    tf = (
        analysis.get("execution_tf")
        or analysis.get("chart_tf")
        or live.get("execution_tf")
        or plan.get("timeframe")
        or "15m"
    )
    style = str(live.get("style") or plan.get("style") or "swing").lower()
    if style not in ("scalp", "swing", "intraday"):
        style = "scalp" if strategy_id.startswith(("scalp_", "intraday_", "crypto_")) else "swing"

    reasons = list(live.get("reasons") or analysis.get("reasons") or [])[:6]
    phase = str(live.get("phase") or analysis.get("phase") or "")
    if phase:
        reasons.insert(0, f"Engine phase: {phase}")

    rr = live.get("rr_ratio") or plan.get("rr_ratio")
    if rr is None and sl > 0:
        rr = round(tp / sl, 2)

    detail = verdict or phase or f"{label} scan"
    if live.get("hold_duration"):
        detail += f" · hold {live.get('hold_duration')}"

    return {
        "name": label,
        "strategy_id": strategy_id,
        "direction": direction if direction in ("LONG", "SHORT") else "WAIT",
        "take_trade": take,
        "forming": forming,
        "confidence_pct": round(max(0.0, min(92.0, conf)), 1),
        "sl_pct": round(sl, 2),
        "tp_pct": round(tp, 2),
        "rr_ratio": rr,
        "timeframe": tf,
        "style": style,
        "detail": detail,
        "reasons": reasons,
        "trade_plan": plan,
        "invalidation": live.get("invalidation") or f"Per {label} engine rules · SL -{sl:.2f}%",
    }


def _setup_to_suggested_trade(setup: dict[str, Any]) -> dict[str, Any]:
    status = "TAKE" if setup.get("take_trade") else ("WATCH" if setup.get("forming") else "MONITOR")
    return {
        "status": status,
        "direction": setup.get("direction", "WAIT"),
        "name": setup.get("name", ""),
        "confidence_pct": setup.get("confidence_pct", 0),
        "sl_pct": setup.get("sl_pct", 0),
        "tp_pct": setup.get("tp_pct", 0),
        "rr_ratio": setup.get("rr_ratio"),
        "style": setup.get("style", ""),
        "timeframe": setup.get("timeframe", ""),
        "detail": setup.get("detail", ""),
        "reasons": setup.get("reasons", []),
    }


def merge_strategy_results(
    base: dict[str, Any],
    strategy_runs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Merge selected strategy outputs into the investigation payload."""
    out = dict(base)
    extra_setups: list[dict[str, Any]] = []

    for run in strategy_runs:
        sid = run.get("strategy_id", "")
        if run.get("error"):
            continue
        setup = analysis_to_setup(sid, run.get("analysis") or {})
        if setup:
            extra_setups.append(setup)

    if not extra_setups:
        return out

    strategies = list(out.get("strategies") or [])
    for s in extra_setups:
        strategies.append({
            "name": s["name"],
            "forming": s.get("forming", False),
            "take_trade": s.get("take_trade", False),
            "direction": s.get("direction"),
            "confidence_pct": s.get("confidence_pct"),
            "sl_pct": s.get("sl_pct"),
            "tp_pct": s.get("tp_pct"),
            "rr_ratio": s.get("rr_ratio"),
            "timeframe": s.get("timeframe"),
            "style": s.get("style"),
            "detail": s.get("detail"),
            "reasons": s.get("reasons", []),
        })

    suggested = list(out.get("suggested_trades") or [])
    for s in extra_setups:
        suggested.append(_setup_to_suggested_trade(s))

    rank = {"TAKE": 3, "WATCH": 2, "MONITOR": 1}
    suggested.sort(
        key=lambda t: (rank.get(t.get("status"), 0), float(t.get("confidence_pct") or 0)),
        reverse=True,
    )
    strategies.sort(key=lambda s: (-int(s.get("take_trade", False)), -float(s.get("confidence_pct") or 0)))

    primary = out.get("trade_setup")
    best_extra = min(extra_setups, key=lambda s: (-int(s.get("take_trade", False)), -float(s.get("confidence_pct") or 0)))
    if best_extra.get("take_trade") and (
        not primary
        or not primary.get("take_trade")
        or float(best_extra.get("confidence_pct") or 0) > float(primary.get("confidence_pct") or 0)
    ):
        primary = best_extra

    out["strategies"] = strategies[:12]
    out["suggested_trades"] = suggested[:10]
    out["trade_setup"] = primary
    out["trade_setups"] = (out.get("trade_setups") or []) + extra_setups
    return out


def investigate_ticker_with_strategies(
    ticker: str,
    asset_class: str,
    *,
    market: str,
    exchange: str,
    groww_token: str = "",
    ohlc_cache: dict | None = None,
    analyst_pool: list[dict] | None = None,
    strategy_ids: list[str] | None = None,
) -> dict[str, Any]:
    base = investigate_ticker(
        ticker,
        asset_class,
        market=market,
        exchange=exchange,
        groww_token=groww_token,
        ohlc_cache=ohlc_cache,
        analyst_pool=analyst_pool,
    )
    strategy_ids = [s for s in (strategy_ids or []) if s]
    if not strategy_ids:
        return base

    runs: list[dict[str, Any]] = []
    for sid in strategy_ids:
        analysis = run_strategy_live_analysis(
            sid, ticker, market, groww_token=groww_token, exchange=exchange,
        )
        runs.append({
            "strategy_id": sid,
            "label": strategy_label(sid),
            "analysis": analysis,
            "error": analysis.get("error"),
        })

    merged = merge_strategy_results(base, runs)
    merged["selected_strategies"] = strategy_ids
    merged["strategy_runs"] = runs
    return merged


def run_ticker_investigation_with_strategies(
    asset_class: str,
    tickers: list[str],
    *,
    strategy_ids: list[str] | None = None,
    groww_token: str = "",
    progress_callback: Callable[[float, str], None] | None = None,
) -> dict | None:
    cfg = ASSET_CONFIG.get(asset_class)
    if not cfg or not tickers:
        return None

    market = str(cfg["market"])
    exchange = str(cfg.get("exchange") or "NSE")
    results: list[dict] = []
    cache: dict = {}
    analyst_pool = fetch_analyst_calls_pool(asset_class)
    total = len(tickers)
    strategy_ids = [s for s in (strategy_ids or []) if s]

    for i, ticker in enumerate(tickers):
        if progress_callback:
            progress_callback((i + 0.2) / total, f"News, TA & strategies: {ticker}")
        try:
            results.append(
                investigate_ticker_with_strategies(
                    ticker,
                    asset_class,
                    market=market,
                    exchange=exchange,
                    groww_token=groww_token,
                    ohlc_cache=cache,
                    analyst_pool=analyst_pool,
                    strategy_ids=strategy_ids,
                ),
            )
        except Exception as exc:
            logger.warning("Investigation+strategy failed %s: %s", ticker, exc)
            results.append({
                "ticker": ticker,
                "asset_class": asset_class,
                "market": market,
                "error": str(exc)[:200],
                "news": [],
                "analyst_calls": [],
                "strategies": [],
                "trade_setup": None,
                "suggested_trades": [],
                "selected_strategies": strategy_ids,
                "strategy_runs": [],
            })
        if progress_callback:
            progress_callback((i + 1) / total, f"Done: {ticker}")

    return {
        "asset_class": asset_class,
        "market": market,
        "tickers": tickers,
        "selected_strategies": strategy_ids,
        "results": results,
    }
