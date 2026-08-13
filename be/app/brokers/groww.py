"""Groww live-trade adapter — https://groww.in/trade-api/docs/curl"""

from __future__ import annotations

import secrets
import string
from typing import Any

import httpx

from app.brokers.base import (
    BrokerConnectionStatus,
    BrokerError,
    BrokerFunds,
    BrokerHolding,
    BrokerOrderResult,
    BrokerPortfolio,
)
from app.services.settings_service import SettingsService

GROWW_BASE = "https://api.groww.in"


def _groww_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-API-VERSION": "1.0",
    }


def _payload(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    if data.get("status") == "FAILURE":
        return data
    payload = data.get("payload")
    return payload if isinstance(payload, dict) else data


def _err_msg(data: Any, fallback: str = "") -> str:
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or err.get("code") or "")
        if isinstance(err, str):
            return err
        return str(data.get("message") or fallback)
    return fallback


def _ref_id() -> str:
    alphabet = string.ascii_letters + string.digits
    core = "".join(secrets.choice(alphabet) for _ in range(12))
    return f"LT-{core}"


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
                "Groww access token ready."
                if connected
                else "Configure Groww API key + TOTP in Manage, then refresh the token."
            ),
            details={
                "api_key_set": bool(api_key),
                "totp_secret_set": bool(secret),
                "token_set": bool(token),
                "token_expires_at": await self.settings.get_groww_token_expires_at(),
                "exchange": await self.settings.get_groww_exchange(),
                "docs": "https://groww.in/trade-api/docs/curl",
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

    async def _get(self, path: str, *, params: dict[str, Any] | None = None) -> tuple[int, Any]:
        token = await self._token()
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.get(
                f"{GROWW_BASE}{path}",
                headers=_groww_headers(token),
                params=params,
            )
        try:
            data = resp.json() if resp.content else {}
        except Exception:
            data = {"raw": resp.text[:500]}
        return resp.status_code, data

    async def _post(self, path: str, body: dict[str, Any] | list[Any]) -> tuple[int, Any]:
        token = await self._token()
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(
                f"{GROWW_BASE}{path}",
                headers=_groww_headers(token),
                json=body,
            )
        try:
            data = resp.json() if resp.content else {}
        except Exception:
            data = {"raw": resp.text[:500]}
        return resp.status_code, data

    async def get_portfolio(self) -> BrokerPortfolio:
        holdings: list[BrokerHolding] = []
        positions: list[dict[str, Any]] = []
        available: float | None = None
        used_margin: float | None = None
        notes: list[str] = []

        # Funds / margin — GET /v1/margins/detail/user
        status, margin_data = await self._get("/v1/margins/detail/user")
        if status == 200 and isinstance(margin_data, dict) and margin_data.get("status") != "FAILURE":
            payload = _payload(margin_data)
            eq = payload.get("equity_margin_details") if isinstance(payload.get("equity_margin_details"), dict) else {}
            available = (
                _num(eq.get("cnc_balance_available"))
                or _num(eq.get("mis_balance_available"))
                or _num(payload.get("clear_cash"))
            )
            used_margin = _num(payload.get("net_margin_used")) or _num(eq.get("net_equity_margin_used"))
        else:
            notes.append(f"margin HTTP {status}: {_err_msg(margin_data) or 'unavailable'}")

        # Holdings — GET /v1/holdings/user
        status, hold_data = await self._get("/v1/holdings/user")
        if status == 200 and isinstance(hold_data, dict) and hold_data.get("status") != "FAILURE":
            payload = _payload(hold_data)
            rows = payload.get("holdings") if isinstance(payload.get("holdings"), list) else []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                qty = float(row.get("quantity") or 0)
                if qty == 0:
                    continue
                holdings.append(
                    BrokerHolding(
                        symbol=str(row.get("trading_symbol") or row.get("isin") or "").upper(),
                        quantity=qty,
                        avg_price=_num(row.get("average_price")),
                        product="CNC",
                        exchange=None,
                        raw=row,
                    )
                )
        else:
            notes.append(f"holdings HTTP {status}: {_err_msg(hold_data) or 'unavailable'}")

        # Positions — GET /v1/positions/user
        status, pos_data = await self._get("/v1/positions/user", params={"segment": "CASH"})
        if status == 200 and isinstance(pos_data, dict) and pos_data.get("status") != "FAILURE":
            payload = _payload(pos_data)
            rows = payload.get("positions") if isinstance(payload.get("positions"), list) else []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                positions.append(row)
                qty = float(row.get("quantity") or 0)
                sym = str(row.get("trading_symbol") or "").upper()
                if qty and sym and not any(h.symbol == sym for h in holdings):
                    holdings.append(
                        BrokerHolding(
                            symbol=sym,
                            quantity=qty,
                            avg_price=_num(row.get("net_price")),
                            product=str(row.get("product") or "CNC"),
                            exchange=str(row.get("exchange") or "") or None,
                            raw=row,
                        )
                    )
        else:
            notes.append(f"positions HTTP {status}: {_err_msg(pos_data) or 'unavailable'}")

        ok_parts = []
        if available is not None:
            ok_parts.append(f"funds ₹{available:,.2f}")
        ok_parts.append(f"{len(holdings)} holdings")
        ok_parts.append(f"{len(positions)} positions")
        message = " · ".join(ok_parts)
        if notes:
            message = f"{message}. Notes: {'; '.join(notes)}"

        return BrokerPortfolio(
            holdings=holdings,
            positions=positions,
            funds=BrokerFunds(
                available=available,
                used_margin=used_margin,
                currency="INR",
                raw={"notes": notes},
            ),
            message=message,
        )

    async def list_day_orders(self) -> list[dict[str, Any]]:
        status, data = await self._get(
            "/v1/order/list",
            params={"segment": "CASH", "page": 0, "page_size": 100},
        )
        if status != 200 or not isinstance(data, dict) or data.get("status") == "FAILURE":
            return []
        payload = _payload(data)
        rows = payload.get("order_list") if isinstance(payload.get("order_list"), list) else []
        out: list[dict[str, Any]] = []
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "id": -(i + 1),
                    "broker": self.id,
                    "broker_order_id": row.get("groww_order_id"),
                    "ticker": row.get("trading_symbol"),
                    "side": str(row.get("transaction_type") or "").lower(),
                    "quantity": row.get("quantity"),
                    "order_type": str(row.get("order_type") or "").lower(),
                    "status": str(row.get("order_status") or "").lower(),
                    "limit_price": row.get("price"),
                    "product": row.get("product"),
                    "exchange": row.get("exchange"),
                    "notes": row.get("remark"),
                    "message": row.get("remark"),
                    "created_at": row.get("created_at"),
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
        exch = (exchange or await self.settings.get_groww_exchange() or "NSE").upper()
        ot = order_type.upper()
        if ot in ("STOP", "STOP_LIMIT", "SL", "SL-M"):
            ot = "SL" if trigger_price is not None else "LIMIT"
        elif ot not in ("MARKET", "LIMIT", "SL", "SL-M"):
            ot = "MARKET"

        body: dict[str, Any] = {
            "trading_symbol": symbol.upper().strip().replace("-EQ", ""),
            "quantity": int(quantity) if float(quantity).is_integer() else int(quantity),
            "validity": "DAY",
            "exchange": exch,
            "segment": "CASH",
            "product": (product or "CNC").upper(),
            "order_type": ot,
            "transaction_type": side.upper(),
            "order_reference_id": _ref_id(),
            "price": float(price or 0),
            "trigger_price": float(trigger_price or 0),
        }
        if notes:
            # Groww has no free-text remarks field on create; keep reference stable.
            pass

        status, data = await self._post("/v1/order/create", body)
        payload = _payload(data) if isinstance(data, dict) else {}
        if status in (200, 201) and isinstance(data, dict) and data.get("status") != "FAILURE":
            oid = str(payload.get("groww_order_id") or "")
            if oid:
                return BrokerOrderResult(
                    ok=True,
                    broker_order_id=oid,
                    status=str(payload.get("order_status") or "submitted").lower(),
                    message=str(payload.get("remark") or "Order submitted to Groww."),
                    raw=data if isinstance(data, dict) else {},
                )
        raise BrokerError(
            f"Groww order failed (HTTP {status}): {_err_msg(data) or data}",
            code="order_rejected",
        )

    async def cancel_order(self, broker_order_id: str) -> BrokerOrderResult:
        status, data = await self._post(
            "/v1/order/cancel",
            {"segment": "CASH", "groww_order_id": broker_order_id},
        )
        payload = _payload(data) if isinstance(data, dict) else {}
        if status in (200, 201) and isinstance(data, dict) and data.get("status") != "FAILURE":
            return BrokerOrderResult(
                ok=True,
                broker_order_id=broker_order_id,
                status=str(payload.get("order_status") or "cancelled").lower(),
                message="Cancel requested on Groww.",
                raw=data if isinstance(data, dict) else {},
            )
        raise BrokerError(
            f"Groww cancel failed (HTTP {status}): {_err_msg(data) or data}",
            code="cancel_failed",
        )


def _num(val: Any) -> float | None:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
