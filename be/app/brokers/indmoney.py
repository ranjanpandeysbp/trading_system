"""INDMoney / INDstocks live-trade adapter — https://api-docs.indstocks.com/"""

from __future__ import annotations

import asyncio
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

IND_BASE = "https://api.indstocks.com"


def _auth_headers(token: str) -> dict[str, str]:
    # Docs require raw token — NOT "Bearer …"
    # https://api-docs.indstocks.com/conventions/
    tok = (token or "").strip()
    if tok.lower().startswith("bearer "):
        tok = tok[7:].strip()
    return {
        "Authorization": tok,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _num(val: Any) -> float | None:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _map_product(product: str | None) -> str:
    p = (product or "CNC").upper()
    if p in ("MIS", "INTRADAY"):
        return "INTRADAY"
    if p in ("NRML", "MARGIN"):
        return "MARGIN"
    return "CNC"


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
                "docs": "https://api-docs.indstocks.com/introduction/",
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

    async def _get(self, path: str, *, params: dict[str, Any] | None = None) -> tuple[int, Any]:
        token = await self._token()
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.get(
                f"{IND_BASE}{path}",
                headers=_auth_headers(token),
                params=params,
            )
        try:
            data = resp.json() if resp.content else {}
        except Exception:
            data = {"raw": resp.text[:500]}
        return resp.status_code, data

    async def _post(self, path: str, body: dict[str, Any]) -> tuple[int, Any]:
        token = await self._token()
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(
                f"{IND_BASE}{path}",
                headers=_auth_headers(token),
                json=body,
            )
        try:
            data = resp.json() if resp.content else {}
        except Exception:
            data = {"raw": resp.text[:500]}
        return resp.status_code, data

    @staticmethod
    def _ok(data: Any) -> bool:
        if not isinstance(data, dict):
            return False
        st = str(data.get("status") or "").lower()
        return st in ("success", "ok", "true", "")

    async def get_portfolio(self) -> BrokerPortfolio:
        holdings: list[BrokerHolding] = []
        positions: list[dict[str, Any]] = []
        available: float | None = None
        used_margin: float | None = None
        notes: list[str] = []

        # Funds — GET /funds
        status, funds_data = await self._get("/funds")
        if status == 200 and self._ok(funds_data):
            data = funds_data.get("data") if isinstance(funds_data, dict) else None
            if isinstance(data, dict):
                detailed = data.get("detailed_avl_balance") if isinstance(data.get("detailed_avl_balance"), dict) else {}
                available = (
                    _num(detailed.get("eq_cnc"))
                    or _num(detailed.get("eq_mis"))
                    or _num(data.get("withdrawal_balance"))
                    or _num(data.get("sod_balance"))
                )
                used = _num(data.get("realized_pnl"))
                used_margin = abs(used) if used is not None and used < 0 else None
        else:
            notes.append(f"funds HTTP {status}: {_ind_err(funds_data)}")

        # Holdings — GET /portfolio/holdings
        status, hold_data = await self._get("/portfolio/holdings")
        if status == 200 and self._ok(hold_data):
            rows = hold_data.get("data") if isinstance(hold_data, dict) else None
            if isinstance(rows, list):
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    qty = float(row.get("total_qty") or 0)
                    if qty == 0:
                        continue
                    holdings.append(
                        BrokerHolding(
                            symbol=str(row.get("symbol") or "").upper(),
                            quantity=qty,
                            avg_price=_num(row.get("avg_price")),
                            product="CNC",
                            exchange=None,
                            raw=row,
                        )
                    )
        else:
            notes.append(f"holdings HTTP {status}: {_ind_err(hold_data)}")

        # Equity positions (CNC + intraday)
        for product in ("cnc", "intraday"):
            status, pos_data = await self._get(
                "/portfolio/positions",
                params={"segment": "equity", "product": product},
            )
            if status == 200 and self._ok(pos_data):
                rows = pos_data.get("data") if isinstance(pos_data, dict) else None
                if isinstance(rows, list):
                    for row in rows:
                        if isinstance(row, dict):
                            positions.append(row)
            elif status not in (200, 204):
                notes.append(f"positions({product}) HTTP {status}")

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
        status, data = await self._get("/order-book")
        if status != 200 or not self._ok(data):
            return []
        rows = data.get("data") if isinstance(data, dict) else None
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
                    "broker_order_id": row.get("id"),
                    "ticker": row.get("name") or row.get("security_id"),
                    "side": str(row.get("txn_type") or "").lower(),
                    "quantity": row.get("requested_qty") or row.get("traded_qty"),
                    "order_type": str(row.get("order_type") or "").lower(),
                    "status": str(row.get("status") or "").lower(),
                    "limit_price": _num(row.get("requested_price")),
                    "product": row.get("product"),
                    "exchange": row.get("exchange"),
                    "notes": row.get("remarks"),
                    "message": row.get("extra_info") or row.get("remarks"),
                    "created_at": row.get("created_at"),
                    "source": "broker",
                    "segment": row.get("segment"),
                }
            )
        return out

    async def _resolve_security_id(self, symbol: str, exchange: str) -> str:
        token = await self._token()

        def _resolve() -> str | None:
            from app.data.indmoney_client import resolve_scrip_code

            scrip = resolve_scrip_code(symbol, token, exchange=exchange)
            if not scrip:
                return None
            # scrip like NSE_2885 → security_id 2885
            if "_" in scrip:
                return scrip.split("_", 1)[1]
            return scrip

        sec = await asyncio.to_thread(_resolve)
        if not sec:
            raise BrokerError(
                f"Could not resolve security_id for {symbol} on {exchange}. "
                "Use an NSE/BSE equity symbol that exists in INDstocks instruments.",
                code="symbol_not_found",
            )
        return sec

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
        exch = (exchange or "NSE").upper()
        prod = _map_product(product)
        ot = order_type.upper()
        if ot not in ("MARKET", "LIMIT"):
            ot = "LIMIT" if price is not None else "MARKET"
        security_id = await self._resolve_security_id(symbol, exch)
        algo_id = "99999" if exch == "NSE" else "9999999999999999"

        body: dict[str, Any] = {
            "txn_type": side.upper(),
            "exchange": exch,
            "segment": "EQUITY",
            "product": prod,
            "order_type": ot,
            "validity": "DAY",
            "security_id": str(security_id),
            "qty": int(quantity) if float(quantity).is_integer() else int(quantity),
            "algo_id": algo_id,
            "is_amo": False,
        }
        if ot == "LIMIT":
            if price is None:
                raise BrokerError("Limit orders require a price", code="invalid_price")
            body["limit_price"] = float(price)
        if notes:
            body["remarks"] = str(notes)[:100]
        # trigger_price unused for standard equity MARKET/LIMIT

        status, data = await self._post("/order", body)
        if status in (200, 201) and self._ok(data):
            payload = data.get("data") if isinstance(data, dict) else None
            oid = None
            if isinstance(payload, dict):
                oid = payload.get("order_id") or payload.get("id")
            if oid:
                return BrokerOrderResult(
                    ok=True,
                    broker_order_id=str(oid),
                    status=str((payload or {}).get("order_status") or "submitted").lower(),
                    message="Order submitted to INDMoney / INDstocks.",
                    raw=data if isinstance(data, dict) else {},
                )
        raise BrokerError(
            f"INDMoney order failed (HTTP {status}): {_ind_err(data)}",
            code="order_rejected",
        )

    async def cancel_order(self, broker_order_id: str) -> BrokerOrderResult:
        # Equity order ids typically EQ-… ; derivatives DRV-…
        segment = "DERIVATIVE" if str(broker_order_id).upper().startswith("DRV") else "EQUITY"
        status, data = await self._post(
            "/order/cancel",
            {"order_id": broker_order_id, "segment": segment},
        )
        if status in (200, 201) and self._ok(data):
            return BrokerOrderResult(
                ok=True,
                broker_order_id=broker_order_id,
                status="cancelled",
                message="Cancel requested on INDMoney.",
                raw=data if isinstance(data, dict) else {},
            )
        raise BrokerError(
            f"INDMoney cancel failed (HTTP {status}): {_ind_err(data)}",
            code="cancel_failed",
        )


def _ind_err(data: Any) -> str:
    if isinstance(data, dict):
        for key in ("message", "error", "detail", "exception"):
            val = data.get(key)
            if isinstance(val, dict):
                return str(val.get("message") or val)
            if val:
                return str(val)
        return str(data)[:300]
    return str(data)[:300]
