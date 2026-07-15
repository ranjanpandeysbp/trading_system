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
    "weak_strong_sr": "15m",
    "fakeout_4h": "5m",
    "fakeout_15m": "1m",
    "top_down_mtf": "15m",
    "smc_fake_shift": "15m",
    "weekly_stoch": "1d",
    "kn_smart_rsi": "5m",
    "velez_retracement": "15m",
    "smart_wave_crypto": "30m",
    "crypto_scalping": "15m",
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
    return verdict.startswith("TAKE")


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
        if screener_id == "weak_strong_sr":
            from app.market_pulse.weak_strong_sr_engine import analyze_weak_strong_sr

            df = _fetch(ticker, tf, market, groww_token, exchange)
            is_crypto = "CoinDCX" in market
            return analyze_weak_strong_sr(df, chart_tf=tf, is_crypto=is_crypto)

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

            strategies = opts.get("strategies") or list(STRATEGY_KEYS)[:3]
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
    ) -> dict[str, Any]:
        meta = next((s for s in TA_SCREENERS if s["id"] == screener_id), None)
        if not meta:
            raise ValueError(f"Unknown screener: {screener_id}")

        market = await self.settings.get_default_market()
        token = await self.settings.get_groww_token() or ""
        exchange = await self.settings.get_groww_exchange()

        def _batch():
            set_groww_token(token)
            results = []
            for ticker in tickers:
                row = _run_one(
                    screener_id, ticker,
                    market=market, groww_token=token, exchange=exchange,
                    timeframe=timeframe, options=options,
                )
                row["ticker"] = ticker
                results.append(row)
            actionable = [
                r for r in results
                if not r.get("error")
                and (
                    r.get("actionable")
                    or r.get("take_trade")
                    or r.get("phase") in ("ENTRY_READY", "SNIPER_ENTRY", "GOLDEN_BULLET_ENTRY")
                    or str(r.get("verdict", "")).upper().startswith("TAKE")
                )
            ]
            return {
                "screener_id": screener_id,
                "label": meta["label"],
                "market": market,
                "timeframe": timeframe or _DEFAULT_TF.get(screener_id),
                "results": results,
                "actionable": actionable,
                "actionable_count": len(actionable),
            }

        return json_safe(await asyncio.to_thread(_batch))
