"""INDMoney / INDstocks live-trade adapter."""

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


class IndMoneyBrokerAdapter:
    id = "indmoney"
    label = "INDMoney"

    def __init__(self, settings: SettingsService):
        self.settings = settings

    async def connection_status(self) -> BrokerConnectionStatus:
        client_id = await self.settings.get_indmoney_client_id()
        mpin = await self.settings.get_indmoney_mpin()
        secret = await self.settings.get_indmoney_totp_secret()
        token = await self.settings.get_indmoney_access_token()
        configured = bool((client_id and mpin and secret) or token)
        connected = bool(token)
        return BrokerConnectionStatus(
            broker_id=self.id,
            label=self.label,
            credentials_configured=configured,
            connected=connected,
            trading_enabled=connected,
            message=(
                "INDMoney access token ready."
                if connected
                else "Configure Client ID, MPIN, and TOTP in Manage, then refresh the token."
            ),
            details={
                "client_id_set": bool(client_id),
                "mpin_set": bool(mpin),
                "totp_secret_set": bool(secret),
                "token_set": bool(token),
                "token_expires_at": await self.settings.get_indmoney_token_expires_at(),
            },
        )

    async def _token(self) -> str:
        token = await self.settings.get_indmoney_access_token()
        if not token:
            raise BrokerError(
                "INDMoney is not connected. Save credentials in Manage and refresh the token.",
                code="not_connected",
            )
        return token

    async def get_portfolio(self) -> BrokerPortfolio:
        token = await self._token()
        try:
            import httpx

            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(
                    "https://api.indstocks.com/portfolio/holdings",
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                )
            if resp.status_code == 200:
                data = resp.json() if resp.content else {}
                return BrokerPortfolio(
                    holdings=[],
                    positions=[],
                    funds=BrokerFunds(currency="INR", raw=data if isinstance(data, dict) else {}),
                    message="Holdings response received from INDMoney.",
                )
            return BrokerPortfolio(
                funds=BrokerFunds(currency="INR"),
                message=(
                    f"INDMoney connected (token OK) but holdings API returned HTTP {resp.status_code}. "
                    "Portfolio sync will populate when the broker endpoint is available."
                ),
            )
        except BrokerError:
            raise
        except Exception as exc:
            return BrokerPortfolio(
                funds=BrokerFunds(currency="INR"),
                message=f"INDMoney connected. Portfolio sync pending ({exc}).",
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
        payload: dict[str, Any] = {
            "symbol": symbol.upper().strip(),
            "exchange": (exchange or "NSE").upper(),
            "side": side.lower(),
            "quantity": int(quantity) if float(quantity).is_integer() else quantity,
            "order_type": order_type.lower(),
            "product": (product or "CNC").upper(),
        }
        if price is not None:
            payload["price"] = price
        if trigger_price is not None:
            payload["trigger_price"] = trigger_price
        if notes:
            payload["notes"] = notes

        try:
            import httpx

            async with httpx.AsyncClient(timeout=25.0) as client:
                resp = await client.post(
                    "https://api.indstocks.com/orders",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    json=payload,
                )
            data = resp.json() if resp.content else {}
            oid = None
            if isinstance(data, dict):
                oid = data.get("order_id") or data.get("id") or (data.get("data") or {}).get("order_id")
            if resp.status_code in (200, 201) and oid:
                return BrokerOrderResult(
                    ok=True,
                    broker_order_id=str(oid),
                    status=str((data or {}).get("status") or "submitted"),
                    message="Order submitted to INDMoney.",
                    raw=data if isinstance(data, dict) else {},
                )
            err = ""
            if isinstance(data, dict):
                err = str(data.get("message") or data.get("error") or data.get("detail") or "")
            raise BrokerError(
                f"INDMoney order failed (HTTP {resp.status_code}): {err or resp.text[:300]}",
                code="order_rejected",
            )
        except BrokerError:
            raise
        except Exception as exc:
            raise BrokerError(f"INDMoney order request failed: {exc}", code="order_failed") from exc

    async def cancel_order(self, broker_order_id: str) -> BrokerOrderResult:
        token = await self._token()
        try:
            import httpx

            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.delete(
                    f"https://api.indstocks.com/orders/{broker_order_id}",
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                )
            data = resp.json() if resp.content else {}
            if resp.status_code in (200, 201, 204):
                return BrokerOrderResult(
                    ok=True,
                    broker_order_id=broker_order_id,
                    status="cancelled",
                    message="Cancel requested on INDMoney.",
                    raw=data if isinstance(data, dict) else {},
                )
            raise BrokerError(
                f"INDMoney cancel failed (HTTP {resp.status_code})",
                code="cancel_failed",
            )
        except BrokerError:
            raise
        except Exception as exc:
            raise BrokerError(f"INDMoney cancel failed: {exc}", code="cancel_failed") from exc
