"""Seasonality analyzer service."""

from __future__ import annotations

import asyncio
from typing import Any

from app.market_pulse.seasonality import (
    compute_seasonality,
    fetch_seasonality_data,
    generate_signals,
    run_seasonal_backtest,
)
from app.market_pulse.serialize import json_safe
from app.services.settings_service import SettingsService

_MONTH_NAMES = [
    "", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


class SeasonalityService:
    def __init__(self, settings: SettingsService):
        self.settings = settings

    async def analyze(self, tickers: list[str], *, years: int = 10) -> dict[str, Any]:
        market = await self.settings.get_default_market()

        def _run():
            data = fetch_seasonality_data(tickers[:8], years=years, market=market)
            results: list[dict] = []
            for symbol, df in data.items():
                if df is None or df.empty:
                    results.append({"symbol": symbol, "error": "No data"})
                    continue
                if isinstance(df.columns, __import__("pandas").MultiIndex):
                    df.columns = [str(c[0]).lower() for c in df.columns]
                if "close" not in df.columns and "Close" in df.columns:
                    df = df.rename(columns={"Close": "close"})
                pivot, stats_df = compute_seasonality(df)
                if stats_df is None or stats_df.empty:
                    results.append({"symbol": symbol, "error": "Could not compute seasonality"})
                    continue
                signals_df = generate_signals(stats_df)
                bt = run_seasonal_backtest(df, signals_df)
                stats_rows = stats_df.to_dict(orient="records")
                for row in stats_rows:
                    m = int(row.get("Month", 0))
                    row["MonthName"] = _MONTH_NAMES[m] if 0 < m < 13 else str(m)
                results.append({
                    "symbol": symbol,
                    "stats": stats_rows,
                    "signals": signals_df.to_dict(orient="records"),
                    "backtest": bt if isinstance(bt, dict) else {},
                    "heatmap": pivot.to_dict() if pivot is not None else {},
                })
            return {"market": market, "years": years, "results": results}

        return json_safe(await asyncio.to_thread(_run))
