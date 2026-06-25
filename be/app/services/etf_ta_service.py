"""ETF TA IN service — India NSE ETF Shop 4.0."""

from __future__ import annotations

import asyncio
from typing import Any

from app.etf_ta.india_etf_universe import (
    ETF_PRESETS,
    ETF_SHOP_39_PRIMARY,
    MASTER_INDIA_ETFS,
    default_etf_universe,
    underlying_for_symbol,
)
from app.etf_ta import stf_shop_engine as eng
from app.market_pulse.groww_auth import set_groww_token
from app.market_pulse.serialize import json_safe
from app.services.settings_service import SettingsService


class EtfTaService:
    def __init__(self, settings: SettingsService):
        self.settings = settings

    async def _groww_token(self) -> str:
        return await self.settings.get_groww_token() or ""

    async def _exchange(self) -> str:
        return await self.settings.get_groww_exchange()

    def universe(self) -> dict:
        return {
            "presets": {k: v for k, v in ETF_PRESETS.items()},
            "default_symbols": default_etf_universe(),
            "shop_39": ETF_SHOP_39_PRIMARY,
            "master_backup": MASTER_INDIA_ETFS,
        }

    async def scan(self, symbols: list[str] | None = None, exchange: str = "NSE") -> dict:
        syms = symbols or default_etf_universe()
        token = await self._groww_token()
        ex = exchange or await self._exchange()

        def _run():
            set_groww_token(token)
            analyses = eng.scan_etf_universe(syms, groww_token=token, exchange=ex)
            for row in analyses:
                sym = row.get("symbol")
                if sym:
                    row["underlying"] = underlying_for_symbol(str(sym))
            return {
                "symbols": syms,
                "exchange": ex,
                "analyses": analyses,
                "data_errors": eng.data_error_symbols(analyses),
            }

        return json_safe(await asyncio.to_thread(_run))

    async def recommend(self, payload: dict[str, Any]) -> dict:
        token = await self._groww_token()
        ex = payload.get("exchange") or await self._exchange()
        symbols = payload.get("symbols") or default_etf_universe()
        portfolio = payload.get("portfolio") or []
        sip_locked = set(payload.get("sip_locked") or [])

        def _run():
            set_groww_token(token)
            analyses = eng.scan_etf_universe(symbols, groww_token=token, exchange=ex)
            for row in analyses:
                sym = row.get("symbol")
                if sym:
                    row["underlying"] = underlying_for_symbol(str(sym))

            rec = eng.daily_stf_recommendation(
                deposited_capital=float(payload.get("deposited_capital") or 500_000),
                growth_amount=float(payload.get("growth_amount") or 0),
                dividend_withdrawn=float(payload.get("dividend_withdrawn") or 0),
                portfolio=portfolio,
                analyses=analyses,
                sell_mode=payload.get("sell_mode") or "combined",
                profit_target_pct=float(payload.get("profit_target_pct") or eng.DEFAULT_PROFIT_TARGET_PCT),
                profit_target_inr=float(payload.get("profit_target_inr") or eng.DEFAULT_PROFIT_TARGET_INR),
                min_profit_inr=float(payload.get("min_profit_inr") or eng.DEFAULT_MIN_PROFIT_INR),
                slots_divisor=int(payload.get("slots_divisor") or eng.SLOTS_DIVISOR),
                sip_locked=sip_locked,
                shop_start_date=payload.get("shop_start_date"),
                prefer_sip_when_available=bool(payload.get("prefer_sip", True)),
            )
            rec["analyses"] = analyses
            rec["symbols"] = symbols
            return rec

        return json_safe(await asyncio.to_thread(_run))
