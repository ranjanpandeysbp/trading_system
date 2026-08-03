from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.market_price import fetch_market_price
from app.data.yfinance_provider import normalize_ticker
from app.models.db_models import PaperAccount, PaperOrder, PaperPosition
from app.models.schemas import ModifyOrderRequest, PlaceOrderRequest
from app.services.settings_service import SettingsService


class PaperTradingService:
    def __init__(self, db: AsyncSession, settings: SettingsService, user_id: int | None = None):
        self.db = db
        self.settings = settings
        self.user_id = user_id

    async def _get_or_create_account(self) -> PaperAccount:
        if self.user_id is not None:
            result = await self.db.execute(
                select(PaperAccount).where(PaperAccount.user_id == self.user_id)
            )
        else:
            result = await self.db.execute(select(PaperAccount).limit(1))
        account = result.scalar_one_or_none()
        if account:
            return account
        capital = await self.settings.get_initial_capital()
        account = PaperAccount(
            user_id=self.user_id,
            name="Default",
            cash_balance=capital,
            initial_capital=capital,
        )
        self.db.add(account)
        await self.db.commit()
        await self.db.refresh(account)
        return account

    async def _get_market_price(self, ticker: str, asset_class: str = "india") -> float:
        return await fetch_market_price(
            ticker,
            groww_token=await self.settings.get_groww_token() or "",
            exchange=await self.settings.get_groww_exchange(),
            asset_class=asset_class,
        )

    @staticmethod
    def _normalize_for_asset_class(ticker: str, asset_class: str) -> str:
        return normalize_ticker(ticker) if asset_class == "india" else ticker.strip().upper()

    async def get_price(self, ticker: str, asset_class: str = "india") -> dict:
        ticker = self._normalize_for_asset_class(ticker, asset_class)
        price = await self._get_market_price(ticker, asset_class)
        return {"ticker": ticker, "price": round(price, 2)}

    @staticmethod
    def _stop_triggered(side: str, price: float, trigger_price: float) -> bool:
        return price >= trigger_price if side == "buy" else price <= trigger_price

    @staticmethod
    def _limit_fillable(side: str, price: float, limit_price: float) -> bool:
        return price <= limit_price if side == "buy" else price >= limit_price

    @staticmethod
    def _merge_notes(existing: str | None, new: str | None) -> str | None:
        """Averaging into a position layers a new note under the original rather
        than overwriting it, so the reasoning behind each add is preserved."""
        new = (new or "").strip()
        if not new:
            return existing
        return f"{existing}\n---\n{new}" if existing else new

    async def _apply_fill(
        self,
        account: PaperAccount,
        ticker: str,
        side: str,
        quantity: int,
        price: float,
        *,
        strategy: str | None,
        sl_pct: float | None,
        tp_pct: float | None,
        notes: str | None = None,
        asset_class: str = "india",
    ) -> int:
        """Mutates cash balance + position for a fill. Returns actual filled quantity."""
        cost = price * quantity
        pos_result = await self.db.execute(
            select(PaperPosition).where(
                PaperPosition.account_id == account.id,
                PaperPosition.ticker == ticker,
                PaperPosition.asset_class == asset_class,
            )
        )
        position = pos_result.scalar_one_or_none()
        filled_qty = quantity

        if side == "buy":
            if position and position.side == "short":
                if quantity > position.quantity:
                    raise ValueError(
                        f"Buy quantity {quantity} exceeds short position of {position.quantity}"
                    )
                account.cash_balance -= cost
                position.quantity -= quantity
                if position.quantity == 0:
                    await self.db.delete(position)
            else:
                if account.cash_balance < cost:
                    raise ValueError("Insufficient cash balance")
                account.cash_balance -= cost
                if position and position.side == "long":
                    total_qty = position.quantity + quantity
                    position.avg_price = (position.avg_price * position.quantity + price * quantity) / total_qty
                    position.quantity = total_qty
                    position.sl_pct = sl_pct or position.sl_pct
                    position.tp_pct = tp_pct or position.tp_pct
                    position.notes = self._merge_notes(position.notes, notes)
                else:
                    self.db.add(
                        PaperPosition(
                            account_id=account.id,
                            ticker=ticker,
                            quantity=quantity,
                            avg_price=price,
                            side="long",
                            sl_pct=sl_pct,
                            tp_pct=tp_pct,
                            strategy=strategy,
                            notes=(notes or "").strip() or None,
                            asset_class=asset_class,
                        )
                    )
        else:
            if position and position.side == "long":
                filled_qty = min(quantity, position.quantity)
                if filled_qty == 0:
                    raise ValueError(f"No shares to sell for {ticker}")
                account.cash_balance += price * filled_qty
                position.quantity -= filled_qty
                if position.quantity == 0:
                    await self.db.delete(position)
            elif position and position.side == "short":
                account.cash_balance += cost
                total_qty = position.quantity + quantity
                position.avg_price = (position.avg_price * position.quantity + price * quantity) / total_qty
                position.quantity = total_qty
                position.notes = self._merge_notes(position.notes, notes)
            else:
                account.cash_balance += cost
                self.db.add(
                    PaperPosition(
                        account_id=account.id,
                        ticker=ticker,
                        quantity=quantity,
                        avg_price=price,
                        side="short",
                        sl_pct=sl_pct,
                        tp_pct=tp_pct,
                        strategy=strategy,
                        notes=(notes or "").strip() or None,
                        asset_class=asset_class,
                    )
                )
        return filled_qty

    async def _check_pending_orders(self, account: PaperAccount) -> None:
        result = await self.db.execute(
            select(PaperOrder).where(PaperOrder.account_id == account.id, PaperOrder.status == "pending")
        )
        for o in result.scalars().all():
            try:
                price = await self._get_market_price(o.ticker, o.asset_class)
            except Exception:
                continue

            fill_price: float | None = None
            if o.order_type == "limit" and o.limit_price is not None:
                if self._limit_fillable(o.side, price, o.limit_price):
                    fill_price = o.limit_price
            elif o.order_type == "stop" and o.trigger_price is not None:
                if self._stop_triggered(o.side, price, o.trigger_price):
                    fill_price = price
            elif o.order_type == "stop_limit" and o.trigger_price is not None and o.limit_price is not None:
                if self._stop_triggered(o.side, price, o.trigger_price) and self._limit_fillable(o.side, price, o.limit_price):
                    fill_price = o.limit_price
            if fill_price is None:
                continue

            try:
                filled_qty = await self._apply_fill(
                    account, o.ticker, o.side, o.quantity, fill_price,
                    strategy=o.strategy, sl_pct=o.sl_pct, tp_pct=o.tp_pct, notes=o.notes,
                    asset_class=o.asset_class,
                )
            except ValueError:
                o.status = "cancelled"
                o.cancelled_at = datetime.utcnow()
                continue

            o.status = "filled"
            o.quantity = filled_qty
            o.filled_price = fill_price
            o.filled_at = datetime.utcnow()
        await self.db.commit()

    async def _check_position_stops(self, account: PaperAccount) -> None:
        result = await self.db.execute(
            select(PaperPosition).where(PaperPosition.account_id == account.id)
        )
        for p in result.scalars().all():
            if not p.sl_pct and not p.tp_pct:
                continue
            try:
                price = await self._get_market_price(p.ticker, p.asset_class)
            except Exception:
                continue

            hit: str | None = None
            if p.side == "long":
                if p.sl_pct and price <= p.avg_price * (1 - p.sl_pct / 100):
                    hit = "sl"
                elif p.tp_pct and price >= p.avg_price * (1 + p.tp_pct / 100):
                    hit = "tp"
            else:
                if p.sl_pct and price >= p.avg_price * (1 + p.sl_pct / 100):
                    hit = "sl"
                elif p.tp_pct and price <= p.avg_price * (1 - p.tp_pct / 100):
                    hit = "tp"
            if hit is None:
                continue

            close_side = "sell" if p.side == "long" else "buy"
            qty = p.quantity
            strategy = p.strategy
            await self._apply_fill(
                account, p.ticker, close_side, qty, price,
                strategy=strategy, sl_pct=None, tp_pct=None, asset_class=p.asset_class,
            )
            self.db.add(
                PaperOrder(
                    account_id=account.id,
                    ticker=p.ticker,
                    side=close_side,
                    quantity=qty,
                    price=price,
                    order_type=f"auto_{hit}",
                    status="filled",
                    strategy=strategy,
                    notes=f"Auto {'stop-loss' if hit == 'sl' else 'take-profit'} exit.",
                    filled_price=price,
                    filled_at=datetime.utcnow(),
                    asset_class=p.asset_class,
                )
            )
        await self.db.commit()

    async def get_summary(self) -> dict:
        account = await self._get_or_create_account()
        await self._check_pending_orders(account)
        await self._check_position_stops(account)

        pos_result = await self.db.execute(
            select(PaperPosition).where(PaperPosition.account_id == account.id)
        )
        positions = pos_result.scalars().all()
        ord_result = await self.db.execute(
            select(PaperOrder).where(PaperOrder.account_id == account.id).order_by(PaperOrder.created_at.desc()).limit(20)
        )
        orders = ord_result.scalars().all()
        pending_result = await self.db.execute(
            select(PaperOrder)
            .where(PaperOrder.account_id == account.id, PaperOrder.status == "pending")
            .order_by(PaperOrder.created_at.desc())
        )
        pending_orders = pending_result.scalars().all()

        position_value = 0.0
        position_rows = []
        for p in positions:
            try:
                ltp = await self._get_market_price(p.ticker, p.asset_class)
            except Exception:
                ltp = p.avg_price
            mv = ltp * p.quantity
            pnl = (ltp - p.avg_price) * p.quantity if p.side == "long" else (p.avg_price - ltp) * p.quantity
            position_value += mv if p.side == "long" else -mv
            position_rows.append({
                "id": p.id,
                "ticker": p.ticker,
                "quantity": p.quantity,
                "avg_price": round(p.avg_price, 2),
                "ltp": round(ltp, 2),
                "side": p.side,
                "market_value": round(mv, 2),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl / (p.avg_price * p.quantity) * 100, 2) if p.avg_price else 0,
                "sl_pct": p.sl_pct,
                "tp_pct": p.tp_pct,
                "strategy": p.strategy,
                "notes": p.notes,
                "opened_at": p.opened_at.isoformat() if p.opened_at else None,
                "asset_class": p.asset_class,
            })

        portfolio_value = account.cash_balance + position_value
        total_pnl = portfolio_value - account.initial_capital
        total_pnl_pct = (total_pnl / account.initial_capital * 100) if account.initial_capital else 0

        def _order_row(o: PaperOrder) -> dict:
            return {
                "id": o.id,
                "ticker": o.ticker,
                "side": o.side,
                "quantity": o.quantity,
                "price": round(o.price, 2),
                "order_type": o.order_type,
                "status": o.status,
                "limit_price": o.limit_price,
                "trigger_price": o.trigger_price,
                "filled_price": round(o.filled_price, 2) if o.filled_price is not None else None,
                "strategy": o.strategy,
                "notes": o.notes,
                "created_at": o.created_at.isoformat(),
                "filled_at": o.filled_at.isoformat() if o.filled_at else None,
                "cancelled_at": o.cancelled_at.isoformat() if o.cancelled_at else None,
                "asset_class": o.asset_class,
            }

        return {
            "id": account.id,
            "name": account.name,
            "cash_balance": round(account.cash_balance, 2),
            "initial_capital": account.initial_capital,
            "portfolio_value": round(portfolio_value, 2),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl_pct, 2),
            "positions": position_rows,
            "recent_orders": [_order_row(o) for o in orders],
            "pending_orders": [_order_row(o) for o in pending_orders],
        }

    async def place_order(self, req: PlaceOrderRequest) -> dict:
        account = await self._get_or_create_account()
        asset_class = req.asset_class or "india"
        ticker = self._normalize_for_asset_class(req.ticker, asset_class)

        if req.order_type == "market":
            price = req.price
            if price is None:
                price = await self._get_market_price(ticker, asset_class)
            filled_qty = await self._apply_fill(
                account, ticker, req.side, req.quantity, price,
                strategy=req.strategy, sl_pct=req.sl_pct, tp_pct=req.tp_pct, notes=req.notes,
                asset_class=asset_class,
            )
            order = PaperOrder(
                account_id=account.id,
                ticker=ticker,
                side=req.side,
                quantity=filled_qty,
                price=price,
                order_type="market",
                status="filled",
                strategy=req.strategy,
                notes=(req.notes or "").strip() or None,
                sl_pct=req.sl_pct,
                tp_pct=req.tp_pct,
                filled_price=price,
                filled_at=datetime.utcnow(),
                asset_class=asset_class,
            )
            self.db.add(order)
            await self.db.commit()
            return {"ok": True, "order_id": order.id, "status": "filled", "price": round(price, 2)}

        if req.order_type == "limit":
            if req.limit_price is None:
                raise ValueError("limit_price is required for limit orders")
        elif req.order_type in ("stop", "stop_limit"):
            if req.trigger_price is None:
                raise ValueError("trigger_price is required for stop orders")
            if req.order_type == "stop_limit" and req.limit_price is None:
                raise ValueError("limit_price is required for stop-limit orders")
        else:
            raise ValueError(f"Unknown order_type {req.order_type}")

        reference_price = req.limit_price if req.order_type == "limit" else (req.limit_price or req.trigger_price)
        order = PaperOrder(
            account_id=account.id,
            ticker=ticker,
            side=req.side,
            quantity=req.quantity,
            price=reference_price or 0.0,
            order_type=req.order_type,
            status="pending",
            strategy=req.strategy,
            notes=(req.notes or "").strip() or None,
            sl_pct=req.sl_pct,
            tp_pct=req.tp_pct,
            limit_price=req.limit_price,
            trigger_price=req.trigger_price,
            asset_class=asset_class,
        )
        self.db.add(order)
        await self.db.commit()
        await self.db.refresh(order)
        return {"ok": True, "order_id": order.id, "status": "pending"}

    async def cancel_order(self, order_id: int) -> dict:
        account = await self._get_or_create_account()
        result = await self.db.execute(
            select(PaperOrder).where(PaperOrder.id == order_id, PaperOrder.account_id == account.id)
        )
        order = result.scalar_one_or_none()
        if order is None:
            raise ValueError("Order not found")
        if order.status != "pending":
            raise ValueError(f"Cannot cancel a {order.status} order")
        order.status = "cancelled"
        order.cancelled_at = datetime.utcnow()
        await self.db.commit()
        return {"ok": True, "order_id": order.id, "status": "cancelled"}

    async def modify_order(self, order_id: int, req: ModifyOrderRequest) -> dict:
        account = await self._get_or_create_account()
        result = await self.db.execute(
            select(PaperOrder).where(PaperOrder.id == order_id, PaperOrder.account_id == account.id)
        )
        order = result.scalar_one_or_none()
        if order is None:
            raise ValueError("Order not found")
        if order.status != "pending":
            raise ValueError(f"Cannot modify a {order.status} order")
        if req.quantity is not None:
            order.quantity = req.quantity
        if req.limit_price is not None:
            order.limit_price = req.limit_price
        if req.trigger_price is not None:
            order.trigger_price = req.trigger_price
        if order.order_type == "limit":
            order.price = order.limit_price or order.price
        else:
            order.price = order.limit_price or order.trigger_price or order.price
        await self.db.commit()
        return {"ok": True, "order_id": order.id, "status": "pending"}

    async def delete_orders(self, order_ids: list[int]) -> dict:
        """Removes order-history rows only — a filled/cancelled order's cash
        effect already happened at fill time and isn't re-derived from this
        log, so deleting the record has no bookkeeping impact. Pending orders
        aren't deletable here (cancel them first) since deleting a still-live
        order would silently drop it without ever resolving it."""
        account = await self._get_or_create_account()
        result = await self.db.execute(
            select(PaperOrder).where(PaperOrder.id.in_(order_ids), PaperOrder.account_id == account.id)
        )
        orders = result.scalars().all()
        found_ids = {o.id for o in orders}
        missing = [oid for oid in order_ids if oid not in found_ids]
        pending = [o.id for o in orders if o.status == "pending"]
        if pending:
            raise ValueError(f"Order(s) {pending} are still pending — cancel them first, then delete.")
        for o in orders:
            await self.db.delete(o)
        await self.db.commit()
        return {"ok": True, "deleted": sorted(found_ids), "not_found": missing}

    async def close_positions(self, position_ids: list[int]) -> dict:
        """"Delete" for an open position means closing it at the current
        market price (sell a long / buy-to-cover a short) so cash is credited
        correctly — silently dropping the row would leave the cost basis it
        was holding unaccounted for. Logs a closing PaperOrder row per
        position, same as the automatic SL/TP exit path."""
        account = await self._get_or_create_account()
        result = await self.db.execute(
            select(PaperPosition).where(PaperPosition.id.in_(position_ids), PaperPosition.account_id == account.id)
        )
        positions = result.scalars().all()
        found_ids = {p.id for p in positions}
        missing = [pid for pid in position_ids if pid not in found_ids]
        closed: list[dict] = []
        for p in positions:
            try:
                price = await self._get_market_price(p.ticker, p.asset_class)
            except Exception as exc:
                raise ValueError(f"Could not fetch a price for {p.ticker}: {exc}") from exc
            close_side = "sell" if p.side == "long" else "buy"
            qty = p.quantity
            ticker = p.ticker
            asset_class = p.asset_class
            strategy = p.strategy
            await self._apply_fill(
                account, ticker, close_side, qty, price,
                strategy=strategy, sl_pct=None, tp_pct=None, asset_class=asset_class,
            )
            self.db.add(
                PaperOrder(
                    account_id=account.id,
                    ticker=ticker,
                    side=close_side,
                    quantity=qty,
                    price=price,
                    order_type="market",
                    status="filled",
                    strategy=strategy,
                    notes="Position closed (deleted) by user.",
                    filled_price=price,
                    filled_at=datetime.utcnow(),
                    asset_class=asset_class,
                )
            )
            closed.append({"position_id": p.id, "ticker": ticker, "close_price": round(price, 2)})
        await self.db.commit()
        return {"ok": True, "closed": closed, "not_found": missing}

    async def reset_account(self) -> dict:
        account = await self._get_or_create_account()
        capital = await self.settings.get_initial_capital()
        account.cash_balance = capital
        account.initial_capital = capital
        pos_result = await self.db.execute(
            select(PaperPosition).where(PaperPosition.account_id == account.id)
        )
        for p in pos_result.scalars().all():
            await self.db.delete(p)
        ord_result = await self.db.execute(
            select(PaperOrder).where(PaperOrder.account_id == account.id, PaperOrder.status == "pending")
        )
        for o in ord_result.scalars().all():
            o.status = "cancelled"
            o.cancelled_at = datetime.utcnow()
        await self.db.commit()
        return {"ok": True, "message": "Paper account reset"}

    async def execute_from_signal(self, signal: dict) -> dict:
        if signal.get("action") not in ("BUY", "SELL"):
            raise ValueError("Signal action must be BUY or SELL")
        qty = max(1, int(10000 / signal["price"]))
        asset_class = signal.get("asset_class") or "india"
        return await self.place_order(
            PlaceOrderRequest(
                ticker=signal["ticker"],
                side="buy" if signal["action"] == "BUY" else "sell",
                quantity=qty,
                price=signal.get("price"),
                strategy=signal.get("strategy"),
                sl_pct=signal.get("sl_pct"),
                tp_pct=signal.get("tp_pct"),
                asset_class=asset_class,
            )
        )
