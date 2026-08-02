"""ETF TA IN service — India NSE ETF Shop 4.0.

Two layers:
  - Stateless `scan`/`recommend` — quick "what-if" checks, portfolio passed in by caller.
  - Persisted portfolio (`EtfShopConfig` + `EtfShopLot`) — the real, durable per-user
    shop ledger used by the UI's one-click buy/sell and by the daily schedule worker,
    so capital settings, open lots and the latched SIP-locked symbol set survive
    across devices/browsers instead of living only in localStorage.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.models.db_models import EtfShopConfig, EtfShopLot
from app.services.settings_service import SettingsService

_CONFIG_FIELDS = (
    "deposited_capital",
    "growth_amount",
    "dividend_withdrawn",
    "shop_start_date",
    "preset",
    "custom_symbols",
    "exchange",
    "sell_mode",
    "profit_target_pct",
    "profit_target_inr",
    "min_profit_inr",
    "slots_divisor",
    "prefer_sip",
    "notify_telegram",
    "notify_email",
)


class EtfTaService:
    def __init__(self, settings: SettingsService, db: AsyncSession | None = None):
        self.settings = settings
        self.db = db

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
        """Stateless what-if recommendation — portfolio supplied by the caller."""
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

    # ── Persisted portfolio ────────────────────────────────────────────────

    def _config_to_dict(self, cfg: EtfShopConfig) -> dict[str, Any]:
        return {
            "deposited_capital": cfg.deposited_capital,
            "growth_amount": cfg.growth_amount,
            "dividend_withdrawn": cfg.dividend_withdrawn,
            "shop_start_date": cfg.shop_start_date,
            "preset": cfg.preset,
            "custom_symbols": cfg.custom_symbols,
            "exchange": cfg.exchange,
            "sell_mode": cfg.sell_mode,
            "profit_target_pct": cfg.profit_target_pct,
            "profit_target_inr": cfg.profit_target_inr,
            "min_profit_inr": cfg.min_profit_inr,
            "slots_divisor": cfg.slots_divisor,
            "prefer_sip": cfg.prefer_sip,
            "sip_locked_symbols": sorted(json.loads(cfg.sip_locked_json or "[]")),
            "notify_telegram": cfg.notify_telegram,
            "notify_email": cfg.notify_email,
        }

    def _lot_to_dict(self, lot: EtfShopLot) -> dict[str, Any]:
        return {
            "id": lot.id,
            "slot_id": str(lot.id),
            "symbol": lot.symbol,
            "purchase_price": lot.purchase_price,
            "purchase_date": lot.purchase_date,
            "amount": lot.amount,
            "quantity": lot.quantity,
            "lot_type": lot.lot_type,
            "status": lot.status,
            "closed_date": lot.closed_date,
            "sale_price": lot.sale_price,
            "sale_amount": lot.sale_amount,
            "gross_profit": lot.gross_profit,
            "net_profit": lot.net_profit,
        }

    def _resolve_symbols(self, cfg: EtfShopConfig) -> list[str]:
        if cfg.custom_symbols and cfg.custom_symbols.strip():
            return [s.strip().upper() for s in cfg.custom_symbols.replace("\n", ",").split(",") if s.strip()]
        return ETF_PRESETS.get(cfg.preset) or default_etf_universe()

    async def get_or_create_config(self, user_id: int) -> EtfShopConfig:
        assert self.db is not None, "EtfTaService requires a db session for persisted-portfolio methods"
        row = await self.db.execute(select(EtfShopConfig).where(EtfShopConfig.user_id == user_id))
        cfg = row.scalar_one_or_none()
        if cfg is None:
            cfg = EtfShopConfig(user_id=user_id)
            self.db.add(cfg)
            await self.db.commit()
            await self.db.refresh(cfg)
        return cfg

    async def update_config(self, user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        cfg = await self.get_or_create_config(user_id)
        for field in _CONFIG_FIELDS:
            if field in payload and payload[field] is not None:
                setattr(cfg, field, payload[field])
        await self.db.commit()
        await self.db.refresh(cfg)
        return self._config_to_dict(cfg)

    async def list_lots(self, user_id: int, status: str | None = None) -> list[dict[str, Any]]:
        stmt = select(EtfShopLot).where(EtfShopLot.user_id == user_id)
        if status:
            stmt = stmt.where(EtfShopLot.status == status)
        stmt = stmt.order_by(EtfShopLot.purchase_date, EtfShopLot.id)
        rows = (await self.db.execute(stmt)).scalars().all()
        return [self._lot_to_dict(r) for r in rows]

    async def portfolio(self, user_id: int) -> dict[str, Any]:
        cfg = await self.get_or_create_config(user_id)
        lots = await self.list_lots(user_id)
        return {"config": self._config_to_dict(cfg), "lots": lots}

    async def add_lot(
        self,
        user_id: int,
        *,
        symbol: str,
        price: float,
        amount: float,
        lot_type: str = "standard",
        purchase_date: str | None = None,
    ) -> dict[str, Any]:
        if not symbol.strip():
            raise ValueError("Symbol is required")
        if price <= 0:
            raise ValueError("Buy price must be > 0")
        if amount <= 0:
            raise ValueError("Amount must be > 0")

        qty = amount / price
        pdate = purchase_date or datetime.now().strftime("%Y-%m-%d")
        lot = EtfShopLot(
            user_id=user_id,
            symbol=symbol.upper().strip(),
            purchase_price=round(float(price), 4),
            purchase_date=pdate,
            amount=round(float(amount), 2),
            quantity=round(qty, 4),
            lot_type=lot_type,
            status="open",
        )
        self.db.add(lot)

        cfg = await self.get_or_create_config(user_id)
        if not cfg.shop_start_date:
            cfg.shop_start_date = pdate

        await self.db.commit()
        await self.db.refresh(lot)
        return self._lot_to_dict(lot)

    async def close_lot(
        self,
        user_id: int,
        lot_id: int,
        *,
        sale_price: float,
        sale_date: str | None = None,
        dividend_pct: float = 0.0,
    ) -> dict[str, Any]:
        """Book a FIFO sell — records real sale price/profit and feeds the
        realized gain back into the capital pool (growth reinvested vs
        personal dividend draw), so the shop actually compounds."""
        if sale_price <= 0:
            raise ValueError("Sale price must be > 0")

        lot = await self.db.get(EtfShopLot, lot_id)
        if lot is None or lot.user_id != user_id:
            raise ValueError("Lot not found")
        if lot.status == "closed":
            raise ValueError("Lot already closed")

        sale_amount = round(float(sale_price) * lot.quantity, 2)
        gross_profit = round(sale_amount - lot.amount, 2)
        net = eng.net_profit_after_costs(gross_profit, sale_amount=sale_amount)

        lot.status = "closed"
        lot.closed_date = sale_date or datetime.now().strftime("%Y-%m-%d")
        lot.sale_price = round(float(sale_price), 4)
        lot.sale_amount = sale_amount
        lot.gross_profit = gross_profit
        lot.net_profit = net["net_profit"]

        split = eng.split_profit_reinvestment(net["net_profit"], dividend_pct)
        cfg = await self.get_or_create_config(user_id)
        cfg.growth_amount = round(cfg.growth_amount + split["growth_add"], 2)
        if split["dividend"]:
            cfg.dividend_withdrawn = round(cfg.dividend_withdrawn + split["dividend"], 2)

        await self.db.commit()
        await self.db.refresh(lot)
        out = self._lot_to_dict(lot)
        out["net_after_costs"] = net
        out["reinvest_split"] = split
        return out

    async def daily(self, user_id: int) -> dict[str, Any]:
        """Run today's buy/sell recommendation from the persisted config + lot
        ledger (no client-shuttled portfolio needed) and latch any newly-triggered
        SIP-locked symbols back into the config. Closed lots are included too —
        the engine's own open/closed filters need both for FIFO sell candidates
        (open) and the realized-profit summary (closed) to work correctly."""
        cfg = await self.get_or_create_config(user_id)
        lots = await self.list_lots(user_id)
        portfolio = [
            {
                "slot_id": str(lot["id"]),
                "symbol": lot["symbol"],
                "purchase_price": lot["purchase_price"],
                "purchase_date": lot["purchase_date"],
                "amount": lot["amount"],
                "quantity": lot["quantity"],
                "status": lot["status"],
                "lot_type": lot["lot_type"],
                "gross_profit": lot["gross_profit"],
                "net_profit": lot["net_profit"],
                "sale_amount": lot["sale_amount"],
            }
            for lot in lots
        ]
        symbols = self._resolve_symbols(cfg)
        token = await self._groww_token()
        ex = cfg.exchange or await self._exchange()
        sip_locked = set(json.loads(cfg.sip_locked_json or "[]"))

        def _run():
            set_groww_token(token)
            analyses = eng.scan_etf_universe(symbols, groww_token=token, exchange=ex)
            for row in analyses:
                sym = row.get("symbol")
                if sym:
                    row["underlying"] = underlying_for_symbol(str(sym))

            rec = eng.daily_stf_recommendation(
                deposited_capital=cfg.deposited_capital,
                growth_amount=cfg.growth_amount,
                dividend_withdrawn=cfg.dividend_withdrawn,
                portfolio=portfolio,
                analyses=analyses,
                sell_mode=cfg.sell_mode,
                profit_target_pct=cfg.profit_target_pct,
                profit_target_inr=cfg.profit_target_inr,
                min_profit_inr=cfg.min_profit_inr,
                slots_divisor=cfg.slots_divisor,
                sip_locked=sip_locked,
                shop_start_date=cfg.shop_start_date,
                prefer_sip_when_available=cfg.prefer_sip,
            )
            rec["analyses"] = analyses
            rec["symbols"] = symbols
            return rec

        rec = json_safe(await asyncio.to_thread(_run))

        new_locked = set(rec.get("sip_locked_symbols") or [])
        if new_locked != sip_locked:
            cfg.sip_locked_json = json.dumps(sorted(new_locked))
            await self.db.commit()

        return rec
