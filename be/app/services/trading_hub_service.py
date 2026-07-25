"""Trading hubs service — Swing, Intraday, Scalping, Smart Money."""

from __future__ import annotations

import asyncio
from typing import Any

from app.market_pulse.groww_auth import set_groww_token
from app.market_pulse.serialize import json_safe
from app.services.settings_service import SettingsService
from app.services.ticker_universe_service import TickerUniverseService
from app.trading_hubs.registry import list_hubs_payload, run_section_scan


class TradingHubService:
    def __init__(self, settings: SettingsService):
        self.settings = settings
        self.universe = TickerUniverseService()

    async def _groww_token(self) -> str:
        return await self.settings.get_groww_token() or ""

    async def _asset_ctx(self, asset_class: str) -> tuple[str, str]:
        from app.market_pulse.asset_class_config import ASSET_CLASS_CONFIG

        cfg = ASSET_CLASS_CONFIG.get(asset_class) or ASSET_CLASS_CONFIG["india"]
        if asset_class == "india":
            return str(cfg["market"]), await self.settings.get_groww_exchange()
        return str(cfg["market"]), str(cfg.get("exchange") or "NSE")

    def hubs(self) -> dict:
        return list_hubs_payload()

    async def scan(
        self,
        section_id: str,
        tickers: list[str],
        *,
        asset_class: str = "india",
        config: dict[str, Any] | None = None,
        run_bt: bool = False,
    ) -> dict:
        token = await self._groww_token()
        market, exchange = await self._asset_ctx(asset_class)
        from app.trading_hubs.registry import get_section

        section = get_section(section_id)
        # Fixed-universe sections (e.g. Scalp-2mins) ignore the picker — no resolve/cap.
        if section and section.get("fixed_universe"):
            resolved = list(section["fixed_universe"])
        else:
            # No ticker count limit — scan the full resolved universe.
            resolved = list(self.universe.resolve(asset_class, tickers))

        def _run():
            set_groww_token(token)
            try:
                return run_section_scan(
                    section_id,
                    resolved,
                    market=market,
                    groww_token=token,
                    exchange=exchange,
                    config=config,
                    run_bt=run_bt,
                )
            except Exception as exc:
                return {"error": str(exc), "results": [], "entries": []}

        return json_safe(await asyncio.to_thread(_run))
