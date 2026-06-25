"""Trading hubs service — Swing, Intraday, Scalping, Smart Money."""

from __future__ import annotations

import asyncio
from typing import Any

from app.market_pulse.groww_auth import set_groww_token
from app.market_pulse.serialize import json_safe
from app.market_pulse.ticker_utils import GROWW_MARKET
from app.services.settings_service import SettingsService
from app.trading_hubs.registry import list_hubs_payload, run_section_scan


class TradingHubService:
    def __init__(self, settings: SettingsService):
        self.settings = settings

    async def _groww_token(self) -> str:
        return await self.settings.get_groww_token() or ""

    async def _exchange(self) -> str:
        return await self.settings.get_groww_exchange()

    def hubs(self) -> dict:
        return list_hubs_payload()

    async def scan(
        self,
        section_id: str,
        tickers: list[str],
        *,
        config: dict[str, Any] | None = None,
        run_bt: bool = False,
    ) -> dict:
        token = await self._groww_token()
        exchange = await self._exchange()

        def _run():
            set_groww_token(token)
            try:
                return run_section_scan(
                    section_id,
                    tickers[:20],
                    market=GROWW_MARKET,
                    groww_token=token,
                    exchange=exchange,
                    config=config,
                    run_bt=run_bt,
                )
            except Exception as exc:
                return {"error": str(exc), "results": [], "entries": []}

        return json_safe(await asyncio.to_thread(_run))
