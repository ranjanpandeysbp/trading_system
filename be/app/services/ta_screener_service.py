"""Dispatch TA screener engines for API backtests."""

from __future__ import annotations

import asyncio
from typing import Any

from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.groww_auth import set_groww_token
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.serialize import json_safe
from app.market_pulse.ta_screener_registry import TA_SCREENERS
from app.services.settings_service import SettingsService

_DEFAULT_TF: dict[str, str] = {
    "price_action": "15m",
    "pump_dump_predictor": "5m",
    "find_sr": "15m",
    "weak_strong_sr": "15m",
    "pattern_breakout": "15m",
    "fakeout_4h": "5m",
    "fakeout_15m": "1m",
    "top_down_mtf": "15m",
    "smc_fake_shift": "15m",
    "weekly_stoch": "1d",
    "kn_smart_rsi": "5m",
    "velez_retracement": "15m",
    "smart_wave_crypto": "30m",
    "crypto_scalping": "15m",
    "confluence_strategy": "15m",
    "elliott_wave": "1h",
    "top_bottom": "1d",
    "pump_dump_breakout": "15m",
    "big_whale": "15m",
    "zireman_confluence": "1d",
    "bb_exposed": "15m",
    "breakout_mtf": "1d",
    "box_trading": "5m",
    "one_ta": "1h",
    "topdown_mtf": "15m",
}

_LIMIT: dict[str, int] = {
    "1m": 500,
    "5m": 400,
    "15m": 350,
    "30m": 300,
    "1h": 300,
    "4h": 300,
    "1d": 400,
}


def _fetch(
    ticker: str,
    tf: str,
    market: str,
    groww_token: str,
    exchange: str,
) -> Any:
    limit = _LIMIT.get(tf, 350)
    df = fetch_data_for_gap_scan(ticker, tf, market, groww_token, exchange, limit=limit)
    return normalize_ohlcv(df)


def is_actionable_result(row: dict[str, Any]) -> bool:
    if row.get("error"):
        return False
    if row.get("actionable") or row.get("take_trade"):
        return True
    phase = str(row.get("phase", ""))
    if phase in ("ENTRY_READY", "SNIPER_ENTRY", "GOLDEN_BULLET_ENTRY"):
        return True
    verdict = str(row.get("verdict", "")).upper()
    if verdict in ("BUY", "STRONG BUY", "SELL", "WATCHLIST", "TOP PICK"):
        return True
    return verdict.startswith("TAKE") or verdict.startswith("WATCH")


def _weak_strong_sr_result(
    ticker: str,
    *,
    market: str,
    groww_token: str,
    exchange: str,
    timeframe: str | None,
    options: dict[str, Any] | None,
) -> dict[str, Any]:
    from app.market_pulse.weak_strong_sr_engine import (
        aggregate_weak_strong_mtf,
        analyze_weak_strong_sr,
    )

    opts = options or {}
    is_crypto = "CoinDCX" in market
    tfs = opts.get("timeframes")
    if isinstance(tfs, list) and len(tfs) >= 1:
        chart_tfs = [str(t) for t in tfs if t]
    else:
        chart_tfs = [timeframe or _DEFAULT_TF.get("weak_strong_sr", "15m")]

    if len(chart_tfs) == 1:
        tf = chart_tfs[0]
        df = _fetch(ticker, tf, market, groww_token, exchange)
        row = analyze_weak_strong_sr(df, chart_tf=tf, is_crypto=is_crypto)
        row["ticker"] = ticker
        row["timeframe"] = tf
        return row

    legs: list[dict[str, Any]] = []
    errors: list[str] = []
    for tf in chart_tfs:
        try:
            df = _fetch(ticker, tf, market, groww_token, exchange)
            if df is None or getattr(df, "empty", True) or len(df) < 45:
                errors.append(f"{tf}: insufficient bars")
                continue
            analysis = analyze_weak_strong_sr(df, chart_tf=tf, is_crypto=is_crypto)
            analysis["ticker"] = ticker
            analysis["timeframe"] = tf
            legs.append(analysis)
        except Exception as exc:
            errors.append(f"{tf}: {str(exc)[:80]}")

    if not legs:
        return {
            "ticker": ticker,
            "timeframe": "MTF",
            "error": "; ".join(errors) or "No valid timeframe legs",
            "verdict": "NO SETUP",
        }

    mtf = aggregate_weak_strong_mtf(legs, chart_tfs)
    verdict = str(mtf.get("verdict") or "NO SETUP")
    phase = "ENTRY_READY" if verdict in ("BUY", "SELL", "STRONG BUY") else (
        "APPROACHING" if verdict in ("MIXED", "WATCHLIST") else "MONITOR"
    )
    return {
        "ticker": ticker,
        "timeframe": "MTF",
        "verdict": verdict,
        "direction": mtf.get("direction"),
        "phase": phase,
        "confidence": mtf.get("confidence"),
        "summary": (
            f"MTF {verdict} — alignment {mtf.get('mtf_alignment_pct', 0):.0f}% · "
            f"{mtf.get('long_votes', 0)}L/{mtf.get('short_votes', 0)}S · best {mtf.get('best_tf', '—')}"
        ),
        "trade_plan": mtf.get("trade_plan"),
        "mtf": mtf,
        "legs": legs,
        "errors": errors or None,
    }


def evaluate_screener_on_df(
    screener_id: str,
    ticker: str,
    df: Any,
    *,
    market: str,
    timeframe: str | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate a TA screener on a pre-loaded OHLCV window (for rolling backtests)."""
    opts = options or {}
    tf = timeframe or _DEFAULT_TF.get(screener_id, "15m")
    work = normalize_ohlcv(df)
    if work.empty:
        return {"ticker": ticker, "error": "Empty dataframe"}

    try:
        if screener_id == "weak_strong_sr":
            from app.market_pulse.weak_strong_sr_engine import analyze_weak_strong_sr

            is_crypto = "CoinDCX" in market
            return analyze_weak_strong_sr(work, chart_tf=tf, is_crypto=is_crypto)

        if screener_id == "fakeout_4h":
            from app.market_pulse.fakeout_4h_engine import run_fakeout_screener, session_mode_for_market

            return run_fakeout_screener(
                work, rr_ratio=float(opts.get("rr_ratio", 2.0)),
                session_mode=session_mode_for_market(market),
            )

        if screener_id == "fakeout_15m":
            from app.market_pulse.fakeout_15m_engine import run_fakeout_screener, session_mode_for_market

            return run_fakeout_screener(
                work, rr_ratio=float(opts.get("rr_ratio", 2.0)),
                session_mode=session_mode_for_market(market),
            )

        if screener_id == "smc_fake_shift":
            from app.market_pulse.smc_fake_market_shift_engine import analyze_smc_fake_market_shift

            return analyze_smc_fake_market_shift(work, chart_tf=tf)

        if screener_id == "velez_retracement":
            from app.market_pulse.velez_retracement_engine import analyze_velez

            return analyze_velez(work, chart_tf=tf)

        if screener_id == "crypto_scalping":
            from app.market_pulse.crypto_scalping_engine import analyze_crypto_scalping

            return analyze_crypto_scalping(work, chart_tf=tf)

        if screener_id == "pump_dump_breakout":
            from app.market_pulse.pump_dump_breakout_engine import run_analysis

            return run_analysis(work, symbol=ticker, timeframe=tf)

        if screener_id == "zireman_confluence":
            from app.market_pulse.zireman_confluence_engine import run_strategy

            if len(work) < 80:
                return {"ticker": ticker, "error": "Insufficient bars for confluence."}
            return run_strategy(
                work,
                min_confluence=float(opts.get("min_confluence", 60)),
                rr_target=float(opts.get("rr_target", 2.0)),
            )

        return _run_one(
            screener_id, ticker, market=market, groww_token=groww_token,
            exchange=exchange, timeframe=timeframe, options=options,
        )
    except Exception as exc:
        return {"ticker": ticker, "error": str(exc)[:300]}


def _run_one(
    screener_id: str,
    ticker: str,
    *,
    market: str,
    groww_token: str,
    exchange: str,
    timeframe: str | None,
    options: dict[str, Any] | None,
) -> dict[str, Any]:
    opts = options or {}
    tf = timeframe or _DEFAULT_TF.get(screener_id, "15m")

    try:
        if screener_id == "price_action":
            from app.market_pulse.price_action import run_full_analysis

            df = _fetch(ticker, tf, market, groww_token, exchange)
            if df.empty or len(df) < 40:
                return {"ticker": ticker, "error": "Insufficient bars for price-action scan."}
            out = run_full_analysis(df, is_crypto="CoinDCX" in market)
            out["ticker"] = ticker
            out["timeframe"] = tf
            return out

        if screener_id == "pump_dump_predictor":
            from dataclasses import asdict, is_dataclass

            if "CoinDCX" in market:
                from app.market_pulse.pump_dump_predictor import analyze_crypto_pair

                result = analyze_crypto_pair(ticker, entry_tf=tf, htf=opts.get("htf", "15m"))
            else:
                from app.market_pulse.india_pump_dump_predictor import analyze_india_ticker

                result = analyze_india_ticker(
                    ticker, entry_tf=tf, htf=opts.get("htf", "15m"),
                    groww_token=groww_token, exchange=exchange,
                )
            payload = asdict(result) if is_dataclass(result) else dict(result.__dict__)
            payload["ticker"] = ticker
            if payload.get("error"):
                return payload
            # Surface a verdict the results panel can highlight.
            bias = str(payload.get("bias") or "neutral").upper()
            if bias in ("PUMP", "BULLISH", "LONG"):
                payload["verdict"] = "WATCH LONG"
                payload["actionable"] = True
            elif bias in ("DUMP", "BEARISH", "SHORT"):
                payload["verdict"] = "WATCH SHORT"
                payload["actionable"] = True
            else:
                payload["verdict"] = "WAIT"
            return payload

        if screener_id == "find_sr":
            from app.market_pulse.find_sr_tab import run_find_sr_analysis

            df = _fetch(ticker, tf, market, groww_token, exchange)
            if df.empty or len(df) < 40:
                return {"ticker": ticker, "error": "Insufficient bars for Find S/R."}
            out = run_find_sr_analysis(df, timeframe=tf)
            out["ticker"] = ticker
            stand = out.get("stand") or {}
            if stand.get("verdict"):
                out["verdict"] = stand["verdict"]
            return out

        if screener_id == "pattern_breakout":
            from app.market_pulse.pattern_engine import analyze_ticker as analyze_patterns

            return analyze_patterns(
                ticker, tf, market, groww_token=groww_token, exchange=exchange,
            )

        if screener_id == "confluence_strategy":
            from app.market_pulse.confluence_strategy_tab import analyze_confluence_strategy

            df = _fetch(ticker, tf, market, groww_token, exchange)
            out = analyze_confluence_strategy(df, is_crypto="CoinDCX" in market)
            out["ticker"] = ticker
            out["timeframe"] = tf
            return out

        if screener_id == "elliott_wave":
            from app.market_pulse.price_action import analyze_elliott_waves

            df = _fetch(ticker, tf, market, groww_token, exchange)
            if df.empty or len(df) < 50:
                return {"ticker": ticker, "error": "Insufficient bars for Elliott Wave."}
            zigzag = 2.0 if len(df) > 200 else 3.0
            ew = analyze_elliott_waves(df, zigzag_pct=zigzag)
            return {
                "ticker": ticker,
                "timeframe": tf,
                "price": float(df["close"].iloc[-1]),
                "elliott": ew,
                "verdict": str((ew or {}).get("current_wave") or (ew or {}).get("label") or "—"),
            }

        if screener_id == "top_bottom":
            from app.market_pulse.top_bottom import (
                calculate_top_bottom_metrics,
                detect_candlestick_patterns,
                detect_chart_patterns,
            )

            df = _fetch(ticker, tf, market, groww_token, exchange)
            metrics = calculate_top_bottom_metrics(df)
            if not metrics:
                return {"ticker": ticker, "error": "Insufficient bars for Top/Bottom."}
            candles = detect_candlestick_patterns(df)
            charts = detect_chart_patterns(df)
            label = str(metrics.get("label") or metrics.get("signal") or metrics.get("stance") or "—")
            return {
                "ticker": ticker,
                "timeframe": tf,
                "metrics": metrics,
                "candle_patterns": candles,
                "chart_patterns": charts,
                "verdict": label,
                "confidence_pct": metrics.get("confidence") or metrics.get("top_probability") or metrics.get("bottom_probability"),
                "actionable": "TOP" in label.upper() or "BOTTOM" in label.upper(),
            }

        if screener_id == "weak_strong_sr":
            return _weak_strong_sr_result(
                ticker,
                market=market,
                groww_token=groww_token,
                exchange=exchange,
                timeframe=tf,
                options=opts,
            )

        if screener_id == "fakeout_4h":
            from app.market_pulse.fakeout_4h_engine import run_fakeout_screener, session_mode_for_market

            df = _fetch(ticker, "5m", market, groww_token, exchange)
            return run_fakeout_screener(
                df,
                rr_ratio=float(opts.get("rr_ratio", 2.0)),
                session_mode=session_mode_for_market(market),
            )

        if screener_id == "fakeout_15m":
            from app.market_pulse.fakeout_15m_engine import run_fakeout_screener, session_mode_for_market

            df = _fetch(ticker, "1m", market, groww_token, exchange)
            return run_fakeout_screener(
                df,
                rr_ratio=float(opts.get("rr_ratio", 2.0)),
                session_mode=session_mode_for_market(market),
            )

        if screener_id == "top_down_mtf":
            from app.market_pulse.top_down_mtf_engine import analyze_top_down

            return analyze_top_down(
                ticker,
                opts.get("htf_tf", "4h"),
                opts.get("mtf_tf", "1h"),
                opts.get("ltf_tf", tf),
                market,
                groww_token,
                exchange,
            )

        if screener_id == "smc_fake_shift":
            from app.market_pulse.smc_fake_market_shift_engine import analyze_smc_fake_market_shift

            df = _fetch(ticker, tf, market, groww_token, exchange)
            return analyze_smc_fake_market_shift(df, chart_tf=tf)

        if screener_id == "weekly_stoch":
            from app.market_pulse.weekly_stoch_sweet_spot_engine import analyze_weekly_stoch

            return analyze_weekly_stoch(ticker, market, groww_token, exchange)

        if screener_id == "kn_smart_rsi":
            from app.market_pulse.kn_smart_rsi_engine import analyze_kn_smart

            return analyze_kn_smart(
                ticker, market, intraday_tf=tf, groww_token=groww_token, exchange=exchange,
            )

        if screener_id == "velez_retracement":
            from app.market_pulse.velez_retracement_engine import analyze_velez

            df = _fetch(ticker, tf, market, groww_token, exchange)
            return analyze_velez(df, chart_tf=tf)

        if screener_id == "smart_wave_crypto":
            from app.market_pulse.smart_wave_crypto_engine import analyze_smart_wave, STRATEGY_KEYS

            strategies = opts.get("strategies") or list(STRATEGY_KEYS)
            return analyze_smart_wave(
                ticker, market=market, strategies=strategies, primary_tf=tf,
                groww_token=groww_token, exchange=exchange,
            )

        if screener_id == "crypto_scalping":
            from app.market_pulse.crypto_scalping_engine import analyze_crypto_scalping

            df = _fetch(ticker, tf, market, groww_token, exchange)
            return analyze_crypto_scalping(df, chart_tf=tf)

        if screener_id == "pump_dump_breakout":
            from app.market_pulse.pump_dump_breakout_engine import run_analysis

            df = _fetch(ticker, tf, market, groww_token, exchange)
            return run_analysis(df, symbol=ticker, timeframe=tf)

        if screener_id == "big_whale":
            from app.market_pulse.big_whale_pump_dump_engine import WhaleScanConfig, run_big_whale_scan

            return run_big_whale_scan(WhaleScanConfig())

        if screener_id == "zireman_confluence":
            from app.market_pulse.zireman_confluence_engine import run_strategy

            df = _fetch(ticker, "1d", market, groww_token, exchange)
            if df.empty or len(df) < 80:
                return {"ticker": ticker, "error": "Insufficient daily bars for confluence scan."}
            return run_strategy(
                df,
                min_confluence=float(opts.get("min_confluence", 60)),
                rr_target=float(opts.get("rr_target", 2.0)),
            )

        if screener_id == "bb_exposed":
            from app.market_pulse.bb_exposed_engine import analyze_bb_exposed

            return analyze_bb_exposed(ticker, market, tf, groww_token=groww_token, exchange=exchange)

        if screener_id == "breakout_mtf":
            from app.market_pulse.breakout_mtf_engine import analyze_breakout_mtf

            return analyze_breakout_mtf(ticker, market, groww_token=groww_token, exchange=exchange)

        if screener_id == "box_trading":
            from app.market_pulse.box_trading_engine import analyze_ticker as analyze_box_trading

            row = analyze_box_trading(ticker, market, groww_token=groww_token, exchange=exchange)
            if row.get("error"):
                return row
            return {**row, **(row.get("live") or {})}

        if screener_id == "one_ta":
            from app.market_pulse.one_ta_engine import analyze_one_ta

            return analyze_one_ta(ticker, market, tf, groww_token=groww_token, exchange=exchange)

        if screener_id == "topdown_mtf":
            from app.market_pulse.topdown_mtf_engine import analyze_ticker as analyze_topdown_mtf

            return analyze_topdown_mtf(ticker, market, groww_token=groww_token, exchange=exchange)

        return {"ticker": ticker, "error": f"Unknown screener engine: {screener_id}"}
    except Exception as exc:
        return {"ticker": ticker, "error": str(exc)[:300]}


class TaScreenerService:
    def __init__(self, settings: SettingsService):
        self.settings = settings

    def catalog(self) -> dict[str, Any]:
        from app.market_pulse.ta_screener_registry import list_ta_screeners

        return list_ta_screeners()

    async def run(
        self,
        screener_id: str,
        tickers: list[str],
        *,
        timeframe: str | None = None,
        options: dict[str, Any] | None = None,
        asset_class: str = "india",
    ) -> dict[str, Any]:
        meta = next((s for s in TA_SCREENERS if s["id"] == screener_id), None)
        if not meta:
            raise ValueError(f"Unknown screener: {screener_id}")

        from app.market_pulse.asset_class_config import ASSET_CLASS_CONFIG

        cfg = ASSET_CLASS_CONFIG.get(asset_class) or ASSET_CLASS_CONFIG["india"]
        market = str(cfg["market"])
        token = await self.settings.get_groww_token() or ""
        exchange = (
            await self.settings.get_groww_exchange()
            if asset_class == "india"
            else str(cfg.get("exchange") or "NSE")
        )

        # No ticker count limit — scan the full list.
        resolved = list(tickers)

        def _batch():
            set_groww_token(token)
            results = []
            for ticker in resolved:
                row = _run_one(
                    screener_id, ticker,
                    market=market, groww_token=token, exchange=exchange,
                    timeframe=timeframe, options=options,
                )
                row["ticker"] = ticker
                results.append(row)
            actionable = [r for r in results if is_actionable_result(r)]
            tfs = (options or {}).get("timeframes") if options else None
            return {
                "screener_id": screener_id,
                "label": meta["label"],
                "market": market,
                "asset_class": asset_class,
                "timeframe": timeframe or _DEFAULT_TF.get(screener_id),
                "timeframes": tfs if isinstance(tfs, list) else None,
                "results": results,
                "actionable": actionable,
                "actionable_count": len(actionable),
            }

        return json_safe(await asyncio.to_thread(_batch))
