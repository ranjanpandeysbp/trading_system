from datetime import datetime, timezone

import asyncio

import pandas as pd

from app.data.factory import DataProviderFactory
from app.data.market_price import MarketQuote, fetch_market_quote
from app.models.schemas import ScanRequest, ScanSignal
from app.services.settings_service import SettingsService
from app.services.signal_enricher import enrich_signal
from app.strategies.registry import (
    STRATEGY_META,
    category_for_timeframe,
    get_strategy,
    needs_benchmark,
)


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


class ScannerService:
    def __init__(self, settings: SettingsService):
        self.settings = settings

    async def scan(self, request: ScanRequest) -> list[ScanSignal]:
        provider = await DataProviderFactory.get_provider(self.settings)
        costs_pct = await self.settings.get_costs_pct()
        benchmark_ticker = await self.settings.get_benchmark_ticker()
        benchmark_df: pd.DataFrame | None = None

        groww_token = await self.settings.get_groww_token() or ""
        groww_exchange = await self.settings.get_groww_exchange()
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
                    )
                    return quote_cache[ticker]
                except Exception:
                    return None

        unique_tickers = list(dict.fromkeys(request.tickers))
        await asyncio.gather(*(_ensure_quote(t) for t in unique_tickers))

        async def _market_fields(ticker: str, df: pd.DataFrame | None = None) -> dict:
            q = await _ensure_quote(ticker)
            if q:
                fields = {"price": q.price, "day_high": q.day_high, "day_low": q.day_low}
            else:
                fields = {"price": 0.0, "day_high": None, "day_low": None}

            if df is not None and (fields["day_high"] is None or fields["day_low"] is None):
                hi, lo = _ohlcv_day_range(df)
                if fields["day_high"] is None and hi is not None:
                    fields["day_high"] = hi
                if fields["day_low"] is None and lo is not None:
                    fields["day_low"] = lo

            return fields

        signals: list[ScanSignal] = []

        for ticker in request.tickers:
            for timeframe in request.timeframes:
                category = category_for_timeframe(timeframe)
                if not category:
                    continue

                try:
                    df = await provider.fetch_ohlcv(ticker, interval=timeframe)
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
                    continue

                if df.empty or len(df) < 30:
                    continue

                if benchmark_df is None and any(
                    needs_benchmark(s) for s in request.strategies if s in STRATEGY_META
                ):
                    try:
                        benchmark_df = await provider.fetch_ohlcv(benchmark_ticker, interval=timeframe)
                    except Exception:
                        benchmark_df = None

                for strategy_id in request.strategies:
                    if strategy_id not in STRATEGY_META:
                        continue
                    meta = STRATEGY_META[strategy_id]
                    if meta["category"] != category:
                        continue

                    try:
                        fn = get_strategy(strategy_id)
                        if needs_benchmark(strategy_id):
                            if benchmark_df is None:
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

                    enriched = enrich_signal(result, last_signal, strategy_id, category, costs_pct)
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

        signals.sort(key=lambda s: s.confidence_pct, reverse=True)
        return signals
