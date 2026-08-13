"""Live broker adapters — extend by registering a new BrokerAdapter in registry.py."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


BROKER_IDS = ("indmoney", "groww", "coindcx")


@dataclass
class BrokerHolding:
    symbol: str
    quantity: float
    avg_price: float | None = None
    ltp: float | None = None
    product: str | None = None
    exchange: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "quantity": self.quantity,
            "avg_price": self.avg_price,
            "ltp": self.ltp,
            "product": self.product,
            "exchange": self.exchange,
            **({"raw": self.raw} if self.raw else {}),
        }


@dataclass
class BrokerFunds:
    available: float | None = None
    used_margin: float | None = None
    currency: str = "INR"
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "used_margin": self.used_margin,
            "currency": self.currency,
            **({"raw": self.raw} if self.raw else {}),
        }


@dataclass
class BrokerPortfolio:
    holdings: list[BrokerHolding] = field(default_factory=list)
    positions: list[dict[str, Any]] = field(default_factory=list)
    funds: BrokerFunds = field(default_factory=BrokerFunds)
    message: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "holdings": [h.as_dict() for h in self.holdings],
            "positions": self.positions,
            "funds": self.funds.as_dict(),
            "message": self.message,
        }


@dataclass
class BrokerOrderResult:
    ok: bool
    broker_order_id: str | None = None
    status: str = "unknown"
    message: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "broker_order_id": self.broker_order_id,
            "status": self.status,
            "message": self.message,
            "raw": self.raw,
        }


@dataclass
class BrokerConnectionStatus:
    broker_id: str
    label: str
    credentials_configured: bool
    connected: bool
    trading_enabled: bool
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "broker_id": self.broker_id,
            "label": self.label,
            "credentials_configured": self.credentials_configured,
            "connected": self.connected,
            "trading_enabled": self.trading_enabled,
            "message": self.message,
            "details": self.details,
        }


class BrokerError(Exception):
    def __init__(self, message: str, *, code: str = "broker_error"):
        super().__init__(message)
        self.code = code
        self.message = message


class BrokerAdapter(Protocol):
    id: str
    label: str

    async def connection_status(self) -> BrokerConnectionStatus: ...

    async def get_portfolio(self) -> BrokerPortfolio: ...

    async def place_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        price: float | None = None,
        trigger_price: float | None = None,
        product: str | None = None,
        exchange: str | None = None,
        notes: str | None = None,
    ) -> BrokerOrderResult: ...

    async def cancel_order(self, broker_order_id: str) -> BrokerOrderResult: ...
