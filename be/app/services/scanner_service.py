"""Strategy Scanner — live BUY/SELL signals across strategies and timeframes."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pandas as pd

from app.data.market_price import MarketQuote, fetch_market_quote
from app.market_pulse.asset_class_config import ASSET_CLASS_CONFIG
from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.groww_auth import set_groww_token
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.models.schemas import ScanRequest, ScanSignal
from app.services.engine_backtest_service import EngineBacktestService
from app.services.settings_service import SettingsService
from app.services.signal_enricher import enrich_signal
from app.strategies.engine_strategies import is_engine_strategy
from app.strategies.preset_strategies import is_preset_strategy
from app.strategies.registry import (
    STRATEGY_META,
    STRATEGY_MIN_BARS,
    category_for_timeframe,
    get_strategy,
    get_strategy_meta,
    needs_benchmark,
)

_TF_LIMIT = {
    "1m": 500,
    "3m": 400,
    "5m": 400,
    "15m": 350,
    "30m": 300,
    "1h": 300,
    "4h": 300,
    "1d": 400,
}

_BENCHMARK_BY_ASSET = {
    "india": None,  # use settings
    "us": "SPY",
    "commodity": "CL=F",
    "crypto": "B-BTCUSDT",
}


def _ohlcv_day_range(df: pd.DataFrame) -> tuple[float | None, float | None]:
    """Session high/low from the latest trading day in OHLCV data."""
    if df is None or df.empty:
        return None, None
    try:
        idx = df.index
        last_date = pd.Timestamp(idx[-1]).date()
        session = df[idx.date == last_date] if hasattr(idx, "date") else df.tail(26)
        if session.empty:
            session = df.tail(26)
        return float(session["high"].max()), float(session["low"].min())
    except Exception:
        return None, None


def _fetch_bars(
    ticker: str,
    timeframe: str,
    market: str,
    groww_token: str,
    exchange: str,
    bars_override: int | None = None,
) -> pd.DataFrame:
    limit = bars_override or _TF_LIMIT.get(timeframe, 350)
    df = fetch_data_for_gap_scan(ticker, timeframe, market, groww_token, exchange, limit=limit)
    return normalize_ohlcv(df)


class ScannerService:
    def __init__(self, settings: SettingsService):
        self.settings = settings
        self.engine_service = EngineBacktestService(settings)

    async def scan(self, request: ScanRequest) -> list[ScanSignal]:
        asset_class = getattr(request, "asset_class", None) or "india"
        bars_override = getattr(request, "bars", None)
        cfg = ASSET_CLASS_CONFIG.get(asset_class) or ASSET_CLASS_CONFIG["india"]
        market = str(cfg["market"])
        groww_token = await self.settings.get_groww_token() or ""
        groww_exchange = (
            await self.settings.get_groww_exchange()
            if asset_class == "india"
            else str(cfg.get("exchange") or "NSE")
        )
        costs_pct = await self.settings.get_costs_pct()

        settings_bench = await self.settings.get_benchmark_ticker()
        benchmark_ticker = _BENCHMARK_BY_ASSET.get(asset_class) or settings_bench
        benchmark_cache: dict[str, pd.DataFrame | None] = {}

        # No ticker count limit — scan the full list.
        unique_tickers = list(dict.fromkeys(t.strip() for t in request.tickers if t and str(t).strip()))

        quote_cache: dict[str, MarketQuote] = {}
        quote_lock = asyncio.Lock()

        async def _ensure_quote(ticker: str) -> MarketQuote | None:
            if ticker in quote_cache:
                return quote_cache[ticker]
            async with quote_lock:
                if ticker in quote_cache:
                    return quote_cache[ticker]
                try:
                    quote_cache[ticker] = await fetch_market_quote(
                        ticker,
                        groww_token=groww_token,
                        exchange=groww_exchange,
                        asset_class=asset_class,
                        market=market,
                    )
                    return quote_cache[ticker]
                except Exception:
                    return None

        await asyncio.gather(*(_ensure_quote(t) for t in unique_tickers))

        async def _market_fields(ticker: str, df: pd.DataFrame | None = None) -> dict:
            q = await _ensure_quote(ticker)
            if q:
                fields = {"price": q.price, "day_high": q.day_high, "day_low": q.day_low}
            else:
                fields = {"price": 0.0, "day_high": None, "day_low": None}
                if df is not None and not df.empty and "close" in df.columns:
                    try:
                        fields["price"] = float(df["close"].iloc[-1])
                    except Exception:
                        pass

            if df is not None and (fields["day_high"] is None or fields["day_low"] is None):
                hi, lo = _ohlcv_day_range(df)
                if fields["day_high"] is None and hi is not None:
                    fields["day_high"] = hi
                if fields["day_low"] is None and lo is not None:
                    fields["day_low"] = lo

            return fields

        def _load_bars(ticker: str, timeframe: str) -> pd.DataFrame:
            set_groww_token(groww_token)
            return _fetch_bars(ticker, timeframe, market, groww_token, groww_exchange, bars_override)

        signals: list[ScanSignal] = []

        for ticker in unique_tickers:
            for timeframe in request.timeframes:
                category = category_for_timeframe(timeframe)
                rule_ids = [s for s in request.strategies if s in STRATEGY_META]
                engine_ids = [
                    s for s in request.strategies
                    if s not in STRATEGY_META and (is_engine_strategy(s) or is_preset_strategy(s))
                ]

                # --- rule-based indicator strategies (unchanged behaviour) ---
                if category and rule_ids:
                    try:
                        df = await asyncio.to_thread(_load_bars, ticker, timeframe)
                    except Exception as exc:
                        signals.append(
                            ScanSignal(
                                ticker=ticker,
                                strategy="—",
                                strategy_label="Data Error",
                                category=category,
                                timeframe=timeframe,
                                action="HOLD",
                                signal=0,
                                price=0,
                                day_high=None,
                                day_low=None,
                                sl_pct=0,
                                tp_pct=0,
                                confidence_pct=0,
                                timestamp=datetime.now(timezone.utc).isoformat(),
                                rationale=str(exc),
                            )
                        )
                        df = None

                    if df is not None and not df.empty:
                        min_needed = 30
                        for sid in rule_ids:
                            min_needed = max(min_needed, STRATEGY_MIN_BARS.get(sid, 30))
                        if len(df) >= min(min_needed, 30):
                            needs_any_bench = any(needs_benchmark(s) for s in rule_ids)
                            if needs_any_bench and timeframe not in benchmark_cache:
                                try:
                                    benchmark_cache[timeframe] = await asyncio.to_thread(
                                        _load_bars, benchmark_ticker, timeframe
                                    )
                                except Exception:
                                    benchmark_cache[timeframe] = None
                            benchmark_df = benchmark_cache.get(timeframe)

                            for strategy_id in rule_ids:
                                meta = STRATEGY_META[strategy_id]
                                if meta["category"] != category:
                                    continue

                                need_bars = STRATEGY_MIN_BARS.get(strategy_id, 30)
                                if len(df) < need_bars:
                                    continue

                                try:
                                    fn = get_strategy(strategy_id)
                                    if needs_benchmark(strategy_id):
                                        if benchmark_df is None or benchmark_df.empty:
                                            continue
                                        result = fn(df, benchmark_df)
                                    else:
                                        result = fn(df)
                                except Exception as exc:
                                    signals.append(
                                        ScanSignal(
                                            ticker=ticker,
                                            strategy=strategy_id,
                                            strategy_label=meta["name"],
                                            category=category,
                                            timeframe=timeframe,
                                            action="HOLD",
                                            signal=0,
                                            **(await _market_fields(ticker, df)),
                                            sl_pct=0,
                                            tp_pct=0,
                                            confidence_pct=0,
                                            timestamp=str(df.index[-1]),
                                            rationale=f"Strategy error: {exc}",
                                        )
                                    )
                                    continue

                                last_signal = int(result["signal"].iloc[-1])
                                fields = await _market_fields(ticker, df)
                                price = fields["price"]
                                action = "BUY" if last_signal == 1 else "SELL" if last_signal == -1 else "HOLD"

                                if last_signal == 0:
                                    recent = result[result["signal"] != 0]
                                    if not recent.empty:
                                        last_signal = int(recent["signal"].iloc[-1])
                                        action = "BUY" if last_signal == 1 else "SELL"

                                if last_signal == 0:
                                    signals.append(
                                        ScanSignal(
                                            ticker=ticker,
                                            strategy=strategy_id,
                                            strategy_label=meta["name"],
                                            category=category,
                                            timeframe=timeframe,
                                            action="HOLD",
                                            signal=0,
                                            price=price,
                                            day_high=fields["day_high"],
                                            day_low=fields["day_low"],
                                            sl_pct=0,
                                            tp_pct=0,
                                            confidence_pct=0,
                                            timestamp=str(result.index[-1]),
                                            rationale="No active signal on latest bar",
                                        )
                                    )
                                    continue

                                enriched = enrich_signal(result, last_signal, meta["name"], category, costs_pct)
                                signals.append(
                                    ScanSignal(
                                        ticker=ticker,
                                        strategy=strategy_id,
                                        strategy_label=meta["name"],
                                        category=category,
                                        timeframe=timeframe,
                                        action=action,
                                        signal=last_signal,
                                        price=price,
                                        day_high=fields["day_high"],
                                        day_low=fields["day_low"],
                                        sl_pct=enriched["sl_pct"],
                                        tp_pct=enriched["tp_pct"],
                                        confidence_pct=enriched["confidence_pct"],
                                        timestamp=str(result.index[-1]),
                                        rationale=enriched["rationale"],
                                    )
                                )

                # --- Trading Hub engines, TA screeners, and presets — live
                # "latest bar" evaluation via EngineBacktestService, independent
                # of the rule-based category/timeframe gate above. ---
                for strategy_id in engine_ids:
                    meta = get_strategy_meta(strategy_id)
                    if not meta or timeframe not in (meta.get("timeframes") or []):
                        continue
                    label = meta.get("name", strategy_id)
                    eng_category = meta.get("category_label") or meta.get("category") or "Engine"

                    try:
                        sig = await self.engine_service.latest_signal(
                            strategy_id, ticker, timeframe,
                            market=market, groww_token=groww_token, exchange=groww_exchange,
                            bars=bars_override or _TF_LIMIT.get(timeframe, 350),
                            costs_pct=costs_pct,
                        )
                    except Exception as exc:
                        signals.append(
                            ScanSignal(
                                ticker=ticker,
                                strategy=strategy_id,
                                strategy_label=label,
                                category=eng_category,
                                timeframe=timeframe,
                                action="HOLD",
                                signal=0,
                                **(await _market_fields(ticker)),
                                sl_pct=0,
                                tp_pct=0,
                                confidence_pct=0,
                                timestamp=datetime.now(timezone.utc).isoformat(),
                                rationale=f"Strategy error: {exc}",
                            )
                        )
                        continue

                    action = sig["action"]
                    fields = await _market_fields(ticker)
                    price = fields["price"] or float(sig.get("price") or 0)
                    signals.append(
                        ScanSignal(
                            ticker=ticker,
                            strategy=strategy_id,
                            strategy_label=label,
                            category=eng_category,
                            timeframe=timeframe,
                            action=action,
                            signal=1 if action == "BUY" else -1 if action == "SELL" else 0,
                            price=price,
                            day_high=fields["day_high"],
                            day_low=fields["day_low"],
                            sl_pct=float(sig.get("sl_pct") or 0),
                            tp_pct=float(sig.get("tp_pct") or 0),
                            confidence_pct=float(sig.get("confidence_pct") or 0),
                            timestamp=sig.get("timestamp") or datetime.now(timezone.utc).isoformat(),
                            rationale=sig.get("rationale") or "",
                        )
                    )

        signals.sort(key=lambda s: s.confidence_pct, reverse=True)
        return signals
