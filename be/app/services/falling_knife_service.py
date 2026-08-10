"""Falling Knife scanner service."""

from __future__ import annotations

import asyncio
from typing import Any

from app.market_pulse.falling_knife_engine import scan_falling_knives, session_info
from app.market_pulse.groww_auth import set_groww_token
from app.market_pulse.serialize import json_safe
from app.services.settings_service import SettingsService


class FallingKnifeService:
    def __init__(self, settings: SettingsService):
        self.settings = settings

    async def _groww_token(self) -> str:
        token, _ = await self.settings.prepare_market_data()
        return token

    async def _exchange(self) -> str:
        return await self.settings.get_groww_exchange()

    async def session(self, asset_class: str = "india") -> dict[str, Any]:
        return json_safe({"session": session_info(asset_class), "asset_class": asset_class})

    async def scan(self, payload: dict[str, Any]) -> dict[str, Any]:
        token = await self._groww_token()
        exchange = str(payload.get("exchange") or await self._exchange() or "NSE")
        asset_class = str(payload.get("asset_class") or "india")
        tickers = list(payload.get("tickers") or [])
        drop_pct = float(payload.get("drop_pct") or 10.0)
        lookback_hours = float(payload.get("lookback_hours") or 24.0)

        def _run():
            set_groww_token(token)
            return scan_falling_knives(
                asset_class=asset_class,
                tickers=tickers,
                drop_pct=drop_pct,
                lookback_hours=lookback_hours,
                groww_token=token,
                exchange=exchange,
            )

        return json_safe(await asyncio.to_thread(_run))
