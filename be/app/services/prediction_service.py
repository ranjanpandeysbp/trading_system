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
        chart_image_base64: str | None = None,
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

        overrides = dict(cfg_overrides or {})
        # Strip non-config keys that may leak from background job payloads.
        chart_image = chart_image_base64 or overrides.pop("chart_image_base64", None)
        overrides.pop("chart_image_mime", None)
        overrides.pop("template_shape_pct", None)

        market, default_exchange = await self._asset_ctx(asset_class)
        token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, tickers)
        cfg = PatternAnalogueConfig(**overrides)
        resolved_exchange = exchange or default_exchange

        template_shape_pct = None
        template_meta = None
        if chart_image:
            from app.market_pulse.chart_image_digitizer import digitize_chart_image

            gemini_key = await self.settings.get_gemini_api_key()
            gemini_model = await self.settings.get_gemini_model()
            try:
                dig = await asyncio.to_thread(
                    digitize_chart_image,
                    chart_image,
                    pattern_bars=cfg.pattern_bars,
                    gemini_api_key=gemini_key,
                    gemini_model=gemini_model,
                )
            except ValueError as exc:
                return {
                    "error": str(exc),
                    "results": [],
                    "entry_count": 0,
                    "template_source": "chart_image",
                }
            template_shape_pct = dig.get("shape_pct")
            template_meta = {
                "engine": dig.get("engine"),
                "notes": dig.get("notes"),
                "mime": dig.get("mime"),
                "net_return_pct": dig.get("net_return_pct"),
            }
            # Image mode works best on one focused ticker; keep user's selection order.
            if len(resolved) > 8:
                resolved = resolved[:8]

        def _run():
            return scan_universe(
                resolved,
                market,
                cfg=cfg,
                groww_token=token,
                exchange=resolved_exchange,
                template_shape_pct=template_shape_pct,
                template_meta=template_meta,
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
        strategy: str | None = None,
        tickers: list[str] | None = None,
        *,
        strategies: list[str] | None = None,
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

        selected: list[str] = []
        for s in strategies or []:
            sid = str(s or "").strip()
            if sid in STRATEGY_IDS and sid not in selected:
                selected.append(sid)
        if strategy:
            sid = str(strategy).strip()
            if sid in STRATEGY_IDS and sid not in selected:
                selected.append(sid)
            elif sid and sid not in STRATEGY_IDS and not selected:
                return {"error": f"Unknown Astro Finance strategy: {sid}", "results": []}
        if not selected:
            selected = list(STRATEGY_IDS)

        market, default_exchange = await self._asset_ctx(asset_class)
        token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, tickers or []) if tickers else []
        ov = dict(cfg_overrides or {})
        # Prefer first selected for cfg.strategy field (multi handled by scan)
        ov["strategy"] = selected[0]
        if "strong_moon_signs" in ov and ov["strong_moon_signs"] is None:
            ov["strong_moon_signs"] = []
        cfg = AstroFinanceConfig(**{
            k: v for k, v in ov.items()
            if k in {"strategy", "lookback_days", "forward_days", "event_window_days", "strong_moon_signs", "timezone_name"}
        })
        resolved_exchange = exchange or default_exchange

        def _run():
            return scan_astro_finance(
                strategies=selected,
                tickers=resolved,
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
            if isinstance(r, dict):
                r["ai_context"] = build_astro_ai_prompt(r)
        payload["ai_system_prompt"] = ASTRO_FINANCE_AI_SYSTEM
        return json_safe(payload)
