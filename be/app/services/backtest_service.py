import pandas as pd

from app.data.factory import DataProviderFactory
from app.data.ohlcv_utils import normalize_ohlcv_index
from app.models.schemas import BacktestRequest
from app.services.engine_backtest_service import EngineBacktestService
from app.services.settings_service import SettingsService
from app.strategies.backtest import backtest_signals
from app.strategies.engine_strategies import is_engine_strategy
from app.strategies.registry import (
    default_backtest_period,
    get_strategy,
    min_bars_for_strategy,
    needs_benchmark,
)


class BacktestService:
    def __init__(self, settings: SettingsService):
        self.settings = settings

    async def run(self, request: BacktestRequest) -> dict:
        if is_engine_strategy(request.strategy):
            return await EngineBacktestService(self.settings).run(request)

        provider = await DataProviderFactory.get_provider(self.settings)
        costs_pct = request.costs_pct or await self.settings.get_costs_pct()
        benchmark_ticker = await self.settings.get_benchmark_ticker()
        period = request.period or default_backtest_period(request.timeframe)
        min_bars = min_bars_for_strategy(request.strategy)

        df = normalize_ohlcv_index(
            await provider.fetch_ohlcv(request.ticker, interval=request.timeframe, period=period),
            request.timeframe,
        )
        if df.empty:
            raise ValueError(f"No data for {request.ticker} (period={period}, timeframe={request.timeframe})")

        if len(df) < min_bars:
            raise ValueError(
                f"Not enough bars for {request.strategy}: got {len(df)}, need at least {min_bars}. "
                f"Try a longer period (currently {period})."
            )

        fn = get_strategy(request.strategy)
        try:
            if needs_benchmark(request.strategy):
                benchmark_df = normalize_ohlcv_index(
                    await provider.fetch_ohlcv(benchmark_ticker, interval=request.timeframe, period=period),
                    request.timeframe,
                )
                if benchmark_df.empty:
                    raise ValueError(f"No benchmark data for {benchmark_ticker}")
                if len(benchmark_df) < min_bars:
                    raise ValueError(
                        f"Not enough benchmark bars for {benchmark_ticker}: got {len(benchmark_df)}, "
                        f"need at least {min_bars}. Try a longer period."
                    )
                result = fn(df, benchmark_df)
            else:
                result = fn(df)
        except Exception as exc:
            raise ValueError(f"Strategy evaluation failed: {exc}") from exc

        if "signal" not in result.columns:
            raise ValueError("Strategy did not produce a signal column")

        signal_count = int((result["signal"] != 0).sum())
        stats = backtest_signals(result, costs_pct=costs_pct)
        recent = result[result["signal"] != 0].tail(10)
        recent_signals = [
            {
                "timestamp": str(idx),
                "close": round(float(row["close"]), 2),
                "signal": int(row["signal"]),
                "action": "BUY" if row["signal"] == 1 else "SELL",
            }
            for idx, row in recent.iterrows()
        ]

        summary = None
        if signal_count == 0:
            summary = (
                f"No buy/sell signals in the selected period ({period}, {len(df)} bars). "
                "Try a longer period or a different strategy."
            )
        elif stats["num_trades"] == 0:
            summary = "Signals were found but no completed round-trip trades in this period."

        return {
            "ticker": request.ticker,
            "strategy": request.strategy,
            "timeframe": request.timeframe,
            "period": period,
            "bars_evaluated": len(df),
            "signal_count": signal_count,
            "benchmark_ticker": benchmark_ticker if needs_benchmark(request.strategy) else None,
            "summary": summary,
            "stats": stats,
            "recent_signals": recent_signals,
        }
