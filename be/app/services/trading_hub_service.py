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
    def __init__(self, settings: SettingsService, db: Any = None):
        self.settings = settings
        self.universe = TickerUniverseService()
        self.db = db

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

    async def scan_swing5(
        self,
        tickers: list[str],
        timeframes: list[str],
        strategies: list[str],
        *,
        asset_class: str = "india",
        config: dict[str, Any] | None = None,
    ) -> dict:
        """Swing Trading — 5 Strategies: a multi-strategy/multi-timeframe scan
        that doesn't fit the generic single-config run_section_scan flow."""
        from app.trading_hubs.registry import build_config
        from app.trading_hubs.swing_5_strategies_engine import Swing5Config
        from app.trading_hubs.swing_5_strategies_engine import scan_universe as swing5_scan_universe

        token = await self._groww_token()
        market, exchange = await self._asset_ctx(asset_class)
        resolved = list(self.universe.resolve(asset_class, tickers))
        cfg = build_config(Swing5Config, config)

        def _run():
            set_groww_token(token)
            try:
                return swing5_scan_universe(
                    resolved, timeframes, market, strategies,
                    cfg=cfg, groww_token=token, exchange=exchange,
                )
            except Exception as exc:
                return {"error": str(exc)}

        results = await asyncio.to_thread(_run)
        return json_safe({
            "market": market, "asset_class": asset_class, "tickers": resolved,
            "timeframes": timeframes, "strategies": strategies, "results": results,
        })

    async def scan(
        self,
        section_id: str,
        tickers: list[str],
        *,
        asset_class: str = "india",
        config: dict[str, Any] | None = None,
        run_bt: bool = False,
        user_id: int | None = None,
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

        payload = await asyncio.to_thread(_run)
        portfolio = await self._attach_position_sizing(payload, market)
        if portfolio is not None:
            payload["portfolio"] = portfolio
        return json_safe(payload)

    async def _attach_position_sizing(self, payload: dict[str, Any], market: str) -> dict[str, Any] | None:
        """Add a `position_size` block to each result's `live` dict using real
        account equity/cash and current open-position risk — every one of the
        31 Trading Hub strategies answers "what to buy" and stops there; none
        compute a quantity. India-only for now (paper trading is
        INR-denominated). Never raises — a sizing failure shouldn't break the
        scan itself."""
        results = payload.get("results") if isinstance(payload, dict) else None
        if not results or self.db is None:
            return None
        try:
            from app.data.yfinance_provider import normalize_ticker
            from app.market_pulse.risk_engine import portfolio_open_risk, size_position
            from app.market_pulse.ticker_utils import is_crypto_market, is_us_market
            from app.services.paper_trading_service import PaperTradingService

            if is_us_market(market) or is_crypto_market(market):
                return None

            pts = PaperTradingService(self.db, self.settings)
            account = await pts._get_or_create_account()
            portfolio = await portfolio_open_risk(self.db, account.id)
            if not portfolio.get("available"):
                return None
            equity = portfolio["equity"]
            cash = portfolio["cash_balance"]
            held_normalized = {normalize_ticker(t) for t in portfolio["same_ticker_counts"]}

            for r in results:
                live = r.get("live") if isinstance(r, dict) else None
                if not isinstance(live, dict) or live.get("direction") not in ("LONG", "SHORT"):
                    continue
                entry = live.get("entry_price")
                sl_pct = live.get("sl_pct")
                if not entry or not sl_pct:
                    continue
                stop = entry * (1 - sl_pct / 100.0) if live["direction"] == "LONG" else entry * (1 + sl_pct / 100.0)
                sized = size_position(entry, stop, equity, available_cash=cash)
                if sized:
                    live["position_size"] = {
                        "quantity": sized.quantity,
                        "notional": sized.notional,
                        "risk_amount": sized.risk_amount,
                        "risk_pct_of_equity": sized.risk_pct_of_equity,
                        "capped_by_cash": sized.capped_by_cash,
                        "portfolio_open_risk_pct": portfolio["total_open_risk_pct"],
                        "already_holding": normalize_ticker(str(r.get("ticker") or "")) in held_normalized,
                        "portfolio_at_risk_cap": portfolio["at_risk_cap"],
                    }
            return portfolio
        except Exception as exc:
            import logging
            logging.getLogger(__name__).debug("Trading Hub position sizing failed: %s", exc)
            return None
