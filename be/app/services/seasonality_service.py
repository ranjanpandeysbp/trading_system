"""Seasonality analyzer service."""

from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd

from app.market_pulse.asset_class_config import ASSET_CLASS_CONFIG
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

    async def analyze(
        self,
        tickers: list[str],
        *,
        years: int = 10,
        asset_class: str = "india",
    ) -> dict[str, Any]:
        cfg = ASSET_CLASS_CONFIG.get(asset_class) or ASSET_CLASS_CONFIG["india"]
        market = str(cfg["market"])

        # No ticker count limit — analyze the full list.
        resolved = list(dict.fromkeys(t.strip() for t in tickers if t and str(t).strip()))

        def _run():
            data = fetch_seasonality_data(resolved, years=years, market=market)
            results: list[dict] = []
            for symbol in resolved:
                df = data.get(symbol)
                if df is None or (isinstance(df, pd.DataFrame) and df.empty):
                    results.append({"symbol": symbol, "error": "No data"})
                    continue
                pivot, stats_df = compute_seasonality(df)
                if stats_df is None or stats_df.empty:
                    results.append({"symbol": symbol, "error": "Could not compute seasonality"})
                    continue
                signals_df = generate_signals(stats_df)
                bt = run_seasonal_backtest(df, signals_df)
                if not isinstance(bt, dict):
                    bt = {}

                stats_rows = []
                for row in stats_df.to_dict(orient="records"):
                    m = int(row.get("Month", 0) or 0)
                    avg = row.get("Avg Return")
                    win = row.get("Win Rate")
                    stats_rows.append({
                        "Month": m,
                        "MonthName": _MONTH_NAMES[m] if 0 < m < 13 else str(m),
                        "AvgReturn": round(float(avg) * 100, 2) if avg is not None else None,
                        "WinRate": round(float(win) * 100, 1) if win is not None else None,
                        "StdDev": row.get("Std Dev"),
                        "PValue": row.get("P-Value"),
                        "Count": row.get("Count"),
                        # Keep originals for Ask AI / guides
                        "Avg Return": avg,
                        "Win Rate": win,
                    })

                signal_rows = []
                for row in signals_df.to_dict(orient="records"):
                    action = row.get("Action") or row.get("Signal") or "NEUTRAL"
                    signal_rows.append({
                        "Month": int(row.get("Month", 0) or 0),
                        "Action": action,
                        "Signal": action,  # FE alias
                        "Strength": row.get("Strength"),
                        "Win Rate": row.get("Win Rate"),
                        "P-Value": row.get("P-Value"),
                    })

                heatmap = {}
                if pivot is not None and not pivot.empty:
                    # JSON-safe: year keys as strings, month cols as ints/strings
                    heatmap = {
                        str(year): {str(month): (None if pd.isna(val) else float(val))
                                    for month, val in months.items()}
                        for year, months in pivot.to_dict(orient="index").items()
                    }

                results.append({
                    "symbol": symbol,
                    "stats": stats_rows,
                    "signals": signal_rows,
                    "backtest": {
                        "total_return_pct": bt.get("total_return_pct"),
                        "cagr_pct": bt.get("cagr_pct"),
                        "sharpe": bt.get("sharpe"),
                        "max_drawdown_pct": bt.get("max_drawdown_pct"),
                        "Total Return": bt.get("Total Return"),
                        "CAGR": bt.get("CAGR"),
                        "Sharpe": bt.get("Sharpe"),
                        "Max Drawdown": bt.get("Max Drawdown"),
                    },
                    "heatmap": heatmap,
                })
            return {
                "market": market,
                "asset_class": asset_class,
                "years": years,
                "ticker_count": len(resolved),
                "results": results,
            }

        return json_safe(await asyncio.to_thread(_run))
