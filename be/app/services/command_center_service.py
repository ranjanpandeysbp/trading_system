"""Command Center — Tomorrow outlook, Buy/Sell advisor, Mega analyser."""

from __future__ import annotations

import asyncio
from typing import Any

from app.services.settings_service import SettingsService
from app.services.ticker_universe_service import TickerUniverseService


class CommandCenterService:
    def __init__(self, settings: SettingsService):
        self.settings = settings
        self.universe = TickerUniverseService()

    async def _ctx(self) -> tuple[str, str, str]:
        token = await self.settings.get_groww_token() or ""
        exchange = await self.settings.get_groww_exchange()
        market = await self.settings.get_default_market()
        return market, token, exchange

    async def tomorrow_outlook(self) -> dict[str, Any]:
        from app.services.market_pulse_service import MarketPulseService

        mp = MarketPulseService(self.settings)
        return await mp.tomorrow_outlook()

    async def ticker_universe(self, asset_class: str) -> dict[str, Any]:
        return self.universe.config(asset_class)

    async def buy_sell_advisor(
        self,
        tickers: list[str],
        *,
        asset_class: str = "india",
        scenario: str = "balanced",
        durations: list[str] | None = None,
    ) -> dict[str, Any]:
        _ = scenario
        _, token, _ = await self._ctx()
        try:
            from app.market_pulse.buy_sell_advisor_engine import ASSET_CLASS_CONFIG, run_buy_sell_advisor
        except ImportError as exc:
            return {"error": f"Buy/Sell advisor not loaded: {exc}", "recommendations": []}

        cfg = ASSET_CLASS_CONFIG.get(asset_class) or ASSET_CLASS_CONFIG["india"]
        dur = durations or list(cfg.get("default_durations") or ["1d"])
        resolved = self.universe.resolve(asset_class, tickers)

        def _run():
            return run_buy_sell_advisor(
                asset_class,
                resolved,
                dur,
                groww_token=token,
            )

        result = await asyncio.to_thread(_run)
        if not result:
            return {"error": "Buy/Sell advisor returned no results.", "recommendations": []}
        return result

    async def mega_analyser(
        self,
        tickers: list[str],
        *,
        asset_class: str = "india",
        durations: list[str] | None = None,
    ) -> dict[str, Any]:
        resolved = self.universe.resolve(asset_class, tickers)
        bs = await self.buy_sell_advisor(
            resolved,
            asset_class=asset_class,
            durations=durations,
        )
        if bs.get("error") and not bs.get("recommendations"):
            return bs

        recs = bs.get("recommendations") or []
        by_ticker = {r["ticker"]: r for r in recs}
        return {
            "tickers": resolved,
            "asset_class": asset_class,
            "mega_by_ticker": by_ticker,
            "mega": recs[0] if len(recs) == 1 else None,
            "recommendations": recs,
            "summaries": bs.get("summaries") or [],
            "by_ticker": bs.get("by_ticker") or {},
            "market": bs.get("market"),
        }

    def sections(self) -> dict[str, Any]:
        return {
            "sections": [
                {"id": "tomorrow_outlook", "label": "Tomorrow & Today Market Outlook"},
                {"id": "mega_analyser", "label": "Mega Analyser"},
                {"id": "buy_sell", "label": "Buy or Sell (India · US · Crypto · Commodity)"},
                {"id": "investigation", "label": "Ticker Investigation"},
            ]
        }
