"""Prediction surfaces — Pattern Analogue and related forward-looking tools."""

from __future__ import annotations

import asyncio
from typing import Any

from app.market_pulse.serialize import json_safe
from app.services.settings_service import SettingsService
from app.services.ticker_universe_service import TickerUniverseService


class PredictionService:
    def __init__(self, settings: SettingsService, db: Any = None):
        self.settings = settings
        self.universe = TickerUniverseService()
        self.db = db

    async def _ctx(self) -> tuple[str, str]:
        return await self.settings.prepare_market_data()

    async def _asset_ctx(self, asset_class: str) -> tuple[str, str]:
        from app.market_pulse.asset_class_config import ASSET_CLASS_CONFIG

        cfg = ASSET_CLASS_CONFIG.get(asset_class) or ASSET_CLASS_CONFIG["india"]
        if asset_class == "india":
            return str(cfg["market"]), await self.settings.get_groww_exchange()
        return str(cfg["market"]), str(cfg.get("exchange") or "NSE")

    async def pattern_analogue(
        self,
        tickers: list[str],
        *,
        asset_class: str = "india",
        exchange: str | None = None,
        cfg_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.pattern_analogue_engine import (
            PATTERN_ANALOGUE_AI_SYSTEM,
            PatternAnalogueConfig,
            build_pattern_analogue_ai_prompt,
            scan_universe,
        )
        from app.market_pulse.ticker_utils import market_currency

        if not tickers:
            return {"error": "Select at least one ticker", "results": [], "entry_count": 0}

        market, default_exchange = await self._asset_ctx(asset_class)
        token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, tickers)
        cfg = PatternAnalogueConfig(**(cfg_overrides or {}))
        resolved_exchange = exchange or default_exchange

        def _run():
            return scan_universe(
                resolved,
                market,
                cfg=cfg,
                groww_token=token,
                exchange=resolved_exchange,
            )

        payload = await asyncio.to_thread(_run)
        payload["asset_class"] = asset_class
        payload["market"] = market
        payload["currency"] = market_currency(market)
        for r in payload.get("results", []):
            r["ai_context"] = build_pattern_analogue_ai_prompt(r)
        payload["ai_system_prompt"] = PATTERN_ANALOGUE_AI_SYSTEM
        return json_safe(payload)

    async def astro_finance(
        self,
        strategy: str,
        tickers: list[str],
        *,
        asset_class: str = "india",
        exchange: str | None = None,
        cfg_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.astro_finance_engine import (
            ASTRO_FINANCE_AI_SYSTEM,
            AstroFinanceConfig,
            STRATEGY_IDS,
            build_astro_ai_prompt,
            scan_astro_finance,
        )
        from app.market_pulse.ticker_utils import market_currency

        if strategy not in STRATEGY_IDS:
            return {"error": f"Unknown Astro Finance strategy: {strategy}", "results": []}

        market, default_exchange = await self._asset_ctx(asset_class)
        token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, tickers) if tickers else []
        ov = dict(cfg_overrides or {})
        ov["strategy"] = strategy
        # list field
        if "strong_moon_signs" in ov and ov["strong_moon_signs"] is None:
            ov["strong_moon_signs"] = []
        cfg = AstroFinanceConfig(**{
            k: v for k, v in ov.items()
            if k in {"strategy", "lookback_days", "forward_days", "event_window_days", "strong_moon_signs", "timezone_name"}
        })
        resolved_exchange = exchange or default_exchange

        def _run():
            return scan_astro_finance(
                strategy,
                resolved,
                asset_class=asset_class,
                market=market,
                cfg=cfg,
                groww_token=token,
                exchange=resolved_exchange,
            )

        payload = await asyncio.to_thread(_run)
        payload["asset_class"] = asset_class
        payload["market"] = market
        payload["currency"] = market_currency(market)
        for r in payload.get("results", []):
            if isinstance(r, dict) and r.get("ticker"):
                r["ai_context"] = build_astro_ai_prompt(r)
        payload["ai_system_prompt"] = ASTRO_FINANCE_AI_SYSTEM
        return json_safe(payload)
