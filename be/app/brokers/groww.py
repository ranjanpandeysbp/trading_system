"""Groww live-trade adapter (credentials via Manage → Groww TOTP)."""

from __future__ import annotations

from typing import Any

from app.brokers.base import (
    BrokerConnectionStatus,
    BrokerError,
    BrokerFunds,
    BrokerOrderResult,
    BrokerPortfolio,
)
from app.services.settings_service import SettingsService


class GrowwBrokerAdapter:
    id = "groww"
    label = "Groww"

    def __init__(self, settings: SettingsService):
        self.settings = settings

    async def connection_status(self) -> BrokerConnectionStatus:
        api_key = await self.settings.get_groww_api_key()
        secret = await self.settings.get_groww_totp_secret()
        token = await self.settings.get_groww_access_token()
        configured = bool((api_key and secret) or token)
        connected = bool(token)
        return BrokerConnectionStatus(
            broker_id=self.id,
            label=self.label,
            credentials_configured=configured,
            connected=connected,
            trading_enabled=connected,
            message=(
                "Groww access token ready — portfolio/orders use the live API when available."
                if connected
                else "Configure Groww API key + TOTP in Manage, then refresh the token."
            ),
            details={
                "api_key_set": bool(api_key),
                "totp_secret_set": bool(secret),
                "token_set": bool(token),
                "token_expires_at": await self.settings.get_groww_token_expires_at(),
                "exchange": await self.settings.get_groww_exchange(),
            },
        )

    async def _token(self) -> str:
        token = await self.settings.get_groww_access_token()
        if not token:
            raise BrokerError(
                "Groww is not connected. Save API key + TOTP in Manage and refresh the token.",
                code="not_connected",
            )
        return token

    async def get_portfolio(self) -> BrokerPortfolio:
        token = await self._token()
        # Groww portfolio endpoints vary by account type; attempt common path and degrade gracefully.
        try:
            import httpx

            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(
                    "https://api.groww.in/v1/portfolio/overview",
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                )
            if resp.status_code == 200:
                data = resp.json() if resp.content else {}
                return BrokerPortfolio(
                    holdings=[],
                    positions=[],
                    funds=BrokerFunds(currency="INR", raw=data if isinstance(data, dict) else {}),
                    message="Portfolio overview fetched from Groww.",
                )
            return BrokerPortfolio(
                funds=BrokerFunds(currency="INR"),
                message=(
                    f"Groww connected (token OK) but portfolio API returned HTTP {resp.status_code}. "
                    "Holdings will appear once Groww portfolio endpoints are enabled for this account."
                ),
            )
        except BrokerError:
            raise
        except Exception as exc:
            return BrokerPortfolio(
                funds=BrokerFunds(currency="INR"),
                message=f"Groww connected. Portfolio sync pending ({exc}).",
            )

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
        token = await self._token()
        exch = (exchange or await self.settings.get_groww_exchange() or "NSE").upper()
        payload: dict[str, Any] = {
            "trading_symbol": symbol.upper().strip(),
            "exchange": exch,
            "transaction_type": side.upper(),
            "quantity": int(quantity) if float(quantity).is_integer() else quantity,
            "order_type": order_type.upper(),
            "product": (product or "CNC").upper(),
        }
        if price is not None:
            payload["price"] = price
        if trigger_price is not None:
            payload["trigger_price"] = trigger_price

        try:
            import httpx

            async with httpx.AsyncClient(timeout=25.0) as client:
                resp = await client.post(
                    "https://api.groww.in/v1/order/create",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    json=payload,
                )
            data = resp.json() if resp.content else {}
            if resp.status_code in (200, 201) and (data.get("order_id") or data.get("growwOrderId") or data.get("id")):
                oid = str(data.get("order_id") or data.get("growwOrderId") or data.get("id"))
                return BrokerOrderResult(
                    ok=True,
                    broker_order_id=oid,
                    status=str(data.get("status") or "submitted"),
                    message="Order submitted to Groww.",
                    raw=data if isinstance(data, dict) else {"body": data},
                )
            err = data.get("message") or data.get("error") or data.get("detail") or resp.text[:300]
            raise BrokerError(
                f"Groww order failed (HTTP {resp.status_code}): {err}",
                code="order_rejected",
            )
        except BrokerError:
            raise
        except Exception as exc:
            raise BrokerError(f"Groww order request failed: {exc}", code="order_failed") from exc

    async def cancel_order(self, broker_order_id: str) -> BrokerOrderResult:
        token = await self._token()
        try:
            import httpx

            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    f"https://api.groww.in/v1/order/cancel/{broker_order_id}",
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                )
            data = resp.json() if resp.content else {}
            if resp.status_code in (200, 201):
                return BrokerOrderResult(
                    ok=True,
                    broker_order_id=broker_order_id,
                    status="cancelled",
                    message="Cancel requested on Groww.",
                    raw=data if isinstance(data, dict) else {},
                )
            raise BrokerError(
                f"Groww cancel failed (HTTP {resp.status_code}): {data or resp.text[:200]}",
                code="cancel_failed",
            )
        except BrokerError:
            raise
        except Exception as exc:
            raise BrokerError(f"Groww cancel failed: {exc}", code="cancel_failed") from exc
