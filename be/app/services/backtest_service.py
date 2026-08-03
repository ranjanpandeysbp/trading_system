import pandas as pd

from app.market_pulse.asset_class_config import ASSET_CLASS_CONFIG
from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.models.schemas import BacktestRequest
from app.services.engine_backtest_service import EngineBacktestService
from app.services.settings_service import SettingsService
from app.strategies.backtest import backtest_signals
from app.strategies.registry import (
    default_backtest_period,
    get_strategy,
    min_bars_for_strategy,
    needs_benchmark,
    uses_engine_backtest,
)

_PERIOD_DAYS = {
    "7d": 7, "30d": 30, "60d": 60, "90d": 90, "180d": 180,
    "1y": 365, "2y": 730, "5y": 1825, "10y": 3650,
}
_BARS_PER_DAY: dict[str, float] = {
    "1m": 375, "3m": 125, "5m": 75, "15m": 25, "30m": 13, "1h": 6.5, "4h": 1.6, "1d": 1,
    "1wk": 0.2, "1w": 0.2, "1M": 1 / 21,
}


def _period_to_limit(period: str, timeframe: str) -> int:
    days = _PERIOD_DAYS.get(period, 365)
    if timeframe in ("1wk", "1w"):
        return max(52, int(days / 7) + 10)
    if timeframe == "1M":
        return max(24, int(days / 30) + 6)
    return max(100, int(days * _BARS_PER_DAY.get(timeframe, 1)) + 50)


class BacktestService:
    def __init__(self, settings: SettingsService):
        self.settings = settings

    async def _asset_ctx(self, asset_class: str) -> tuple[str, str, str]:
        """Return (market, exchange, groww_token) for the given asset class."""
        cfg = ASSET_CLASS_CONFIG.get(asset_class) or ASSET_CLASS_CONFIG["india"]
        market = str(cfg["market"])
        if asset_class == "india":
            exchange = await self.settings.get_groww_exchange()
            token = await self.settings.get_groww_token() or ""
        else:
            exchange = str(cfg.get("exchange") or "NSE")
            token = ""
        return market, exchange, token

    async def run(self, request: BacktestRequest) -> dict:
        if uses_engine_backtest(request.strategy):
            return await EngineBacktestService(self.settings).run(request)

        asset_class = request.asset_class or "india"
        market, exchange, token = await self._asset_ctx(asset_class)
        costs_pct = request.costs_pct or await self.settings.get_costs_pct()
        period = request.period or default_backtest_period(request.timeframe)
        min_bars = min_bars_for_strategy(request.strategy)
        limit = _period_to_limit(period, request.timeframe)

        df = normalize_ohlcv(
            fetch_data_for_gap_scan(request.ticker, request.timeframe, market, token, exchange, limit=limit),
        )
        if df.empty:
            raise ValueError(f"No data for {request.ticker} (period={period}, timeframe={request.timeframe})")

        if len(df) < min_bars:
            raise ValueError(
                f"Not enough bars for {request.strategy}: got {len(df)}, need at least {min_bars}. "
                f"Try a longer period (currently {period})."
            )

        fn = get_strategy(request.strategy)
        benchmark_ticker = None
        try:
            if needs_benchmark(request.strategy):
                from app.market_pulse.weak_strong_engine import _benchmark_symbol

                benchmark_ticker, _ = _benchmark_symbol(market)
                benchmark_df = normalize_ohlcv(
                    fetch_data_for_gap_scan(benchmark_ticker, request.timeframe, market, token, exchange, limit=limit),
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
        stats = backtest_signals(result, costs_pct=costs_pct, direction=request.direction)
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
