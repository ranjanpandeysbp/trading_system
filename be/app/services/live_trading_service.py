"""Live Trade service — portfolio + orders across registered brokers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.brokers.base import BrokerError
from app.brokers.registry import get_broker_adapter, list_broker_catalog
from app.models.db_models import LiveOrder
from app.services.settings_service import SettingsService


class LiveTradingService:
    def __init__(self, db: AsyncSession, settings: SettingsService, user_id: int):
        self.db = db
        self.settings = settings
        self.user_id = user_id

    async def list_brokers(self) -> dict[str, Any]:
        default = await self.settings.get_live_default_broker()
        brokers = []
        for meta in list_broker_catalog():
            adapter = get_broker_adapter(meta["id"], self.settings)
            status = await adapter.connection_status()
            brokers.append({**meta, **status.as_dict()})
        return {"default_broker": default, "brokers": brokers}

    async def get_account(self, broker_id: str) -> dict[str, Any]:
        adapter = get_broker_adapter(broker_id, self.settings)
        status = await adapter.connection_status()
        portfolio = None
        error = None
        if status.connected or status.credentials_configured:
            try:
                portfolio = (await adapter.get_portfolio()).as_dict()
            except BrokerError as exc:
                error = {"code": exc.code, "message": exc.message}
            except Exception as exc:
                error = {"code": "portfolio_error", "message": str(exc)}
        else:
            error = {"code": "not_configured", "message": status.message}

        local_orders = await self._recent_orders(broker_id)
        broker_day_orders: list[dict[str, Any]] = []
        if status.connected and hasattr(adapter, "list_day_orders"):
            try:
                broker_day_orders = await adapter.list_day_orders()  # type: ignore[attr-defined]
            except Exception as exc:
                if error is None:
                    error = {"code": "order_book_error", "message": f"Day order book: {exc}"}

        # Prefer local audit rows; append broker day orders not already mirrored
        seen_ids = {str(o.get("broker_order_id") or "") for o in local_orders if o.get("broker_order_id")}
        merged = list(local_orders)
        for bo in broker_day_orders or []:
            bid = str(bo.get("broker_order_id") or "")
            if bid and bid in seen_ids:
                continue
            merged.append(bo)

        return {
            "broker": status.as_dict(),
            "portfolio": portfolio,
            "error": error,
            "recent_orders": merged,
            "broker_day_orders": broker_day_orders,
        }

    async def place_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        broker_id = str(payload.get("broker") or "").strip().lower()
        adapter = get_broker_adapter(broker_id, self.settings)
        symbol = str(payload.get("ticker") or payload.get("symbol") or "").strip()
        side = str(payload.get("side") or "").strip().lower()
        quantity = float(payload.get("quantity") or 0)
        order_type = str(payload.get("order_type") or "market").strip().lower()
        if not symbol or side not in ("buy", "sell") or quantity <= 0:
            return {
                "ok": False,
                "error": {
                    "code": "invalid_request",
                    "message": "ticker, side (buy/sell), and positive quantity are required",
                },
            }

        limit_price = payload.get("limit_price")
        trigger_price = payload.get("trigger_price")
        price = float(limit_price) if limit_price not in (None, "") else None
        trigger = float(trigger_price) if trigger_price not in (None, "") else None

        row = LiveOrder(
            user_id=self.user_id,
            broker=broker_id,
            ticker=symbol.upper(),
            side=side,
            quantity=quantity,
            order_type=order_type,
            status="submitting",
            limit_price=price,
            trigger_price=trigger,
            product=str(payload.get("product") or "") or None,
            exchange=str(payload.get("exchange") or "") or None,
            notes=str(payload.get("notes") or "") or None,
        )
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)

        try:
            result = await adapter.place_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                order_type=order_type,
                price=price,
                trigger_price=trigger,
                product=payload.get("product"),
                exchange=payload.get("exchange"),
                notes=payload.get("notes"),
            )
            row.status = result.status or ("filled" if result.ok else "rejected")
            row.broker_order_id = result.broker_order_id
            row.message = result.message
            row.raw_response = str(result.raw)[:4000]
            if result.ok:
                row.filled_at = datetime.utcnow()
            await self.db.commit()
            await self.db.refresh(row)
            return {
                "ok": result.ok,
                "order": self._order_dict(row),
                "broker_result": result.as_dict(),
            }
        except BrokerError as exc:
            row.status = "rejected"
            row.message = exc.message
            await self.db.commit()
            await self.db.refresh(row)
            return {
                "ok": False,
                "error": {"code": exc.code, "message": exc.message},
                "order": self._order_dict(row),
            }
        except Exception as exc:
            row.status = "error"
            row.message = str(exc)
            await self.db.commit()
            await self.db.refresh(row)
            return {
                "ok": False,
                "error": {"code": "order_failed", "message": str(exc)},
                "order": self._order_dict(row),
            }

    async def cancel_order(self, broker_id: str, order_id: int) -> dict[str, Any]:
        result = await self.db.execute(
            select(LiveOrder).where(
                LiveOrder.id == order_id,
                LiveOrder.user_id == self.user_id,
                LiveOrder.broker == broker_id,
            )
        )
        row = result.scalar_one_or_none()
        if not row:
            raise BrokerError("Order not found", code="not_found")
        if not row.broker_order_id:
            raise BrokerError("No broker order id to cancel", code="invalid_order")

        adapter = get_broker_adapter(broker_id, self.settings)
        try:
            br = await adapter.cancel_order(row.broker_order_id)
            if br.ok:
                row.status = "cancelled"
                row.cancelled_at = datetime.utcnow()
                row.message = br.message
                await self.db.commit()
            return {"ok": br.ok, "broker_result": br.as_dict(), "order": self._order_dict(row)}
        except BrokerError as exc:
            return {
                "ok": False,
                "error": {"code": exc.code, "message": exc.message},
                "order": self._order_dict(row),
            }

    async def _recent_orders(self, broker_id: str, limit: int = 40) -> list[dict[str, Any]]:
        result = await self.db.execute(
            select(LiveOrder)
            .where(LiveOrder.user_id == self.user_id, LiveOrder.broker == broker_id)
            .order_by(LiveOrder.id.desc())
            .limit(limit)
        )
        return [self._order_dict(r) for r in result.scalars().all()]

    @staticmethod
    def _order_dict(row: LiveOrder) -> dict[str, Any]:
        return {
            "id": row.id,
            "broker": row.broker,
            "broker_order_id": row.broker_order_id,
            "ticker": row.ticker,
            "side": row.side,
            "quantity": row.quantity,
            "order_type": row.order_type,
            "status": row.status,
            "limit_price": row.limit_price,
            "trigger_price": row.trigger_price,
            "product": row.product,
            "exchange": row.exchange,
            "notes": row.notes,
            "message": row.message,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "filled_at": row.filled_at.isoformat() if row.filled_at else None,
            "cancelled_at": row.cancelled_at.isoformat() if row.cancelled_at else None,
        }
