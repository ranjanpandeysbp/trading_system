"""CoinDCX live-trade adapter (API key + secret from Manage)."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

from app.brokers.base import (
    BrokerConnectionStatus,
    BrokerError,
    BrokerFunds,
    BrokerHolding,
    BrokerOrderResult,
    BrokerPortfolio,
)
from app.services.settings_service import SettingsService

COINDCX_BASE = "https://api.coindcx.com"


class CoinDCXBrokerAdapter:
    id = "coindcx"
    label = "CoinDCX"

    def __init__(self, settings: SettingsService):
        self.settings = settings

    async def _creds(self) -> tuple[str, str]:
        key = await self.settings.get_coindcx_api_key()
        secret = await self.settings.get_coindcx_api_secret()
        if not key or not secret:
            raise BrokerError(
                "CoinDCX credentials missing. Add API key + secret in Manage → Live Trade Brokers.",
                code="not_configured",
            )
        return key, secret

    def _sign(self, secret: str, body: dict[str, Any]) -> str:
        payload = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()

    async def _signed_post(self, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
        import httpx

        key, secret = await self._creds()
        payload = dict(body or {})
        payload.setdefault("timestamp", int(time.time() * 1000))
        json_body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        signature = hmac.new(secret.encode(), json_body.encode(), hashlib.sha256).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-AUTH-APIKEY": key,
            "X-AUTH-SIGNATURE": signature,
        }
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(f"{COINDCX_BASE}{path}", content=json_body, headers=headers)
        try:
            data = resp.json() if resp.content else {}
        except Exception:
            data = {"raw": resp.text[:500]}
        return resp.status_code, data

    async def connection_status(self) -> BrokerConnectionStatus:
        key = await self.settings.get_coindcx_api_key()
        secret = await self.settings.get_coindcx_api_secret()
        configured = bool(key and secret)
        connected = False
        message = "Configure CoinDCX API key + secret in Manage."
        details: dict[str, Any] = {"api_key_set": bool(key), "api_secret_set": bool(secret)}
        if configured:
            try:
                status, data = await self._signed_post("/exchange/v1/users/balances", {})
                connected = status == 200 and isinstance(data, (list, dict))
                message = (
                    "CoinDCX API credentials verified."
                    if connected
                    else f"CoinDCX credentials rejected (HTTP {status})."
                )
                details["balance_http"] = status
            except Exception as exc:
                message = f"CoinDCX connection check failed: {exc}"
        return BrokerConnectionStatus(
            broker_id=self.id,
            label=self.label,
            credentials_configured=configured,
            connected=connected,
            trading_enabled=connected,
            message=message,
            details=details,
        )

    async def get_portfolio(self) -> BrokerPortfolio:
        status, data = await self._signed_post("/exchange/v1/users/balances", {})
        if status != 200:
            raise BrokerError(
                f"CoinDCX balances failed (HTTP {status}): {data}",
                code="portfolio_failed",
            )
        holdings: list[BrokerHolding] = []
        available = 0.0
        rows = data if isinstance(data, list) else data.get("balances") if isinstance(data, dict) else []
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                currency = str(row.get("currency") or row.get("currency_short_name") or "").upper()
                bal = float(row.get("balance") or row.get("available") or 0)
                locked = float(row.get("locked_balance") or 0)
                qty = bal + locked
                if currency in ("INR", "USDT", "USDC", "BTC"):
                    if currency == "INR":
                        available = bal
                    elif currency == "USDT" and available == 0:
                        available = bal
                if qty <= 0 or not currency:
                    continue
                if currency in ("INR",):
                    continue
                holdings.append(
                    BrokerHolding(
                        symbol=currency,
                        quantity=qty,
                        avg_price=None,
                        product="crypto",
                        exchange="CoinDCX",
                        raw=row,
                    )
                )
        return BrokerPortfolio(
            holdings=holdings,
            positions=[],
            funds=BrokerFunds(
                available=available or None,
                currency="INR" if available else "USDT",
                raw={"count": len(holdings)},
            ),
            message=f"Loaded {len(holdings)} CoinDCX balances (docs: https://docs.coindcx.com/).",
        )

    async def list_day_orders(self) -> list[dict[str, Any]]:
        status, data = await self._signed_post("/exchange/v1/orders/active_orders", {})
        if status != 200:
            return []
        rows = data if isinstance(data, list) else data.get("orders") if isinstance(data, dict) else []
        if not isinstance(rows, list):
            return []
        out: list[dict[str, Any]] = []
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "id": -(i + 1),
                    "broker": self.id,
                    "broker_order_id": str(row.get("id") or row.get("order_id") or ""),
                    "ticker": row.get("market") or row.get("pair"),
                    "side": str(row.get("side") or "").lower(),
                    "quantity": row.get("total_quantity") or row.get("remaining_quantity"),
                    "order_type": str(row.get("order_type") or "").lower(),
                    "status": str(row.get("status") or "open").lower(),
                    "limit_price": row.get("price_per_unit"),
                    "product": "crypto",
                    "exchange": "CoinDCX",
                    "created_at": None,
                    "source": "broker",
                }
            )
        return out

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
    ) -> BrokerOrderResult:
        market = symbol.upper().replace("-", "").replace("/", "").strip()
        if not market.endswith("INR") and not market.endswith("USDT"):
            # allow BTC → BTCINR default for India crypto desk
            market = f"{market}INR"
        side_l = side.lower()
        if side_l not in ("buy", "sell"):
            raise BrokerError("side must be buy or sell", code="invalid_side")

        ot = order_type.lower()
        body: dict[str, Any] = {
            "side": side_l,
            "order_type": "market_order" if ot == "market" else "limit_order",
            "market": market,
            "total_quantity": quantity,
            "timestamp": int(time.time() * 1000),
        }
        if ot != "market":
            if price is None:
                raise BrokerError("Limit orders require a price", code="invalid_price")
            body["price_per_unit"] = price

        status, data = await self._signed_post("/exchange/v1/orders/create", body)
        if status in (200, 201) and isinstance(data, dict):
            oid = str(data.get("id") or data.get("order_id") or "")
            if oid:
                return BrokerOrderResult(
                    ok=True,
                    broker_order_id=oid,
                    status=str(data.get("status") or "submitted"),
                    message="Order submitted to CoinDCX.",
                    raw=data,
                )
        raise BrokerError(
            f"CoinDCX order failed (HTTP {status}): {data}",
            code="order_rejected",
        )

    async def cancel_order(self, broker_order_id: str) -> BrokerOrderResult:
        status, data = await self._signed_post(
            "/exchange/v1/orders/cancel",
            {"id": broker_order_id, "timestamp": int(time.time() * 1000)},
        )
        if status in (200, 201):
            return BrokerOrderResult(
                ok=True,
                broker_order_id=broker_order_id,
                status="cancelled",
                message="Cancel requested on CoinDCX.",
                raw=data if isinstance(data, dict) else {},
            )
        raise BrokerError(f"CoinDCX cancel failed (HTTP {status}): {data}", code="cancel_failed")
