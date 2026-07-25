"""Options — Double Calendar (theta-positive income spread), Delta Neutral (Iron Condor / Iron Fly)."""

from __future__ import annotations

import asyncio
from typing import Any

from app.market_pulse.serialize import json_safe
from app.services.settings_service import SettingsService
from app.services.ticker_universe_service import TickerUniverseService


def _attach_ltp(results: list[dict[str, Any]], market: str, *, groww_token: str = "", exchange: str = "NSE") -> None:
    from app.market_pulse.live_price import get_last_traded_price

    for res in results:
        if not res.get("error"):
            res["ltp"] = get_last_traded_price(res["ticker"], market, groww_token=groww_token, exchange=exchange)


class OptionsService:
    def __init__(self, settings: SettingsService):
        self.settings = settings
        self.universe = TickerUniverseService()

    async def _ctx(self) -> tuple[str, str, str]:
        token = await self.settings.get_groww_token() or ""
        exchange = await self.settings.get_groww_exchange()
        market = await self.settings.get_default_market()
        return market, token, exchange

    async def _asset_ctx(self, asset_class: str) -> tuple[str, str]:
        from app.market_pulse.asset_class_config import ASSET_CLASS_CONFIG

        cfg = ASSET_CLASS_CONFIG.get(asset_class) or ASSET_CLASS_CONFIG["india"]
        if asset_class == "india":
            return str(cfg["market"]), await self.settings.get_groww_exchange()
        return str(cfg["market"]), str(cfg.get("exchange") or "NSE")

    async def sections(self) -> dict[str, Any]:
        return {
            "sections": [
                {"id": "double_calendar", "label": "📅 Double Calendar — Theta-Positive Income Spread"},
                {"id": "delta_neutral", "label": "🎰 Delta Neutral — Iron Condor / Iron Fly"},
                {"id": "gokul_chhabra", "label": "🎯 Gokul Chhabra — 3m VWAP · VWMA · SuperTrend ITM"},
            ],
        }

    async def double_calendar(
        self, tickers: list[str], *, asset_class: str = "india", timeframes: list[str] | None = None,
        exchange: str | None = None, cfg_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.double_calendar_engine import DoubleCalendarConfig, build_double_calendar_many
        from app.market_pulse.ticker_utils import market_currency

        market, default_exchange = await self._asset_ctx(asset_class)
        _, token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, tickers)
        tfs = timeframes or ["1d"]
        cfg = DoubleCalendarConfig(**(cfg_overrides or {}))

        resolved_exchange = exchange or default_exchange

        def _run():
            results = build_double_calendar_many(
                resolved, asset_class, market, tfs,
                cfg=cfg, groww_token=token, exchange=resolved_exchange,
            )
            _attach_ltp(results, market, groww_token=token, exchange=resolved_exchange)
            return results

        results = await asyncio.to_thread(_run)
        return json_safe({
            "results": results, "asset_class": asset_class, "market": market,
            "currency": market_currency(market),
        })

    async def double_calendar_pnl(
        self, net_debit: float, current_mark: float, *, cfg_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.double_calendar_engine import DoubleCalendarConfig, evaluate_double_calendar_pnl

        cfg = DoubleCalendarConfig(**(cfg_overrides or {}))
        return json_safe(evaluate_double_calendar_pnl(net_debit, current_mark, cfg))

    async def delta_neutral(
        self, tickers: list[str], *, asset_class: str = "india", timeframes: list[str] | None = None,
        exchange: str | None = None, cfg_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.delta_neutral_engine import DeltaNeutralConfig, build_delta_neutral_many
        from app.market_pulse.ticker_utils import market_currency

        market, default_exchange = await self._asset_ctx(asset_class)
        _, token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, tickers)
        tfs = timeframes or ["1d"]
        cfg = DeltaNeutralConfig(**(cfg_overrides or {}))

        resolved_exchange = exchange or default_exchange

        def _run():
            results = build_delta_neutral_many(
                resolved, asset_class, market, tfs,
                cfg=cfg, groww_token=token, exchange=resolved_exchange,
            )
            _attach_ltp(results, market, groww_token=token, exchange=resolved_exchange)
            return results

        results = await asyncio.to_thread(_run)
        return json_safe({
            "results": results, "asset_class": asset_class, "market": market,
            "currency": market_currency(market),
        })

    async def delta_neutral_pnl(
        self, net_credit: float, current_cost_to_close: float, *, cfg_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.delta_neutral_engine import DeltaNeutralConfig, evaluate_delta_neutral_pnl

        cfg = DeltaNeutralConfig(**(cfg_overrides or {}))
        return json_safe(evaluate_delta_neutral_pnl(net_credit, current_cost_to_close, cfg))

    async def gokul_chhabra(
        self, *, tickers: list[str] | None = None, exchange: str | None = None,
        cfg_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.gokul_chhabra_engine import (
            INDEX_NAMES,
            GokulChhabraConfig,
            scan_universe,
        )
        from app.market_pulse.ticker_utils import market_currency

        market, default_exchange = await self._asset_ctx("india")
        _, token, _ = await self._ctx()
        cfg = GokulChhabraConfig(**(cfg_overrides or {}))
        resolved_exchange = exchange or default_exchange
        names = [n for n in (tickers or INDEX_NAMES) if n in INDEX_NAMES] or list(INDEX_NAMES)

        def _run():
            return scan_universe(
                names, market, cfg=cfg, groww_token=token, exchange=resolved_exchange,
            )

        payload = await asyncio.to_thread(_run)
        payload["asset_class"] = "india"
        payload["currency"] = market_currency(market)
        return json_safe(payload)
