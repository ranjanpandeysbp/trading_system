from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.market_price import fetch_market_price
from app.data.yfinance_provider import normalize_ticker
from app.models.db_models import PaperAccount, PaperOrder, PaperPosition
from app.models.schemas import PlaceOrderRequest
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

    async def _get_market_price(self, ticker: str) -> float:
        return await fetch_market_price(
            ticker,
            groww_token=await self.settings.get_groww_token() or "",
            exchange=await self.settings.get_groww_exchange(),
        )

    async def get_summary(self) -> dict:
        account = await self._get_or_create_account()
        pos_result = await self.db.execute(
            select(PaperPosition).where(PaperPosition.account_id == account.id)
        )
        positions = pos_result.scalars().all()
        ord_result = await self.db.execute(
            select(PaperOrder).where(PaperOrder.account_id == account.id).order_by(PaperOrder.created_at.desc()).limit(20)
        )
        orders = ord_result.scalars().all()

        position_value = 0.0
        position_rows = []
        for p in positions:
            try:
                ltp = await self._get_market_price(p.ticker)
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
            })

        portfolio_value = account.cash_balance + position_value
        total_pnl = portfolio_value - account.initial_capital
        total_pnl_pct = (total_pnl / account.initial_capital * 100) if account.initial_capital else 0

        return {
            "id": account.id,
            "name": account.name,
            "cash_balance": round(account.cash_balance, 2),
            "initial_capital": account.initial_capital,
            "portfolio_value": round(portfolio_value, 2),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl_pct, 2),
            "positions": position_rows,
            "recent_orders": [
                {
                    "id": o.id,
                    "ticker": o.ticker,
                    "side": o.side,
                    "quantity": o.quantity,
                    "price": round(o.price, 2),
                    "status": o.status,
                    "strategy": o.strategy,
                    "created_at": o.created_at.isoformat(),
                }
                for o in orders
            ],
        }

    async def place_order(self, req: PlaceOrderRequest) -> dict:
        account = await self._get_or_create_account()
        ticker = normalize_ticker(req.ticker)
        price = req.price
        if price is None:
            price = await self._get_market_price(ticker)

        cost = price * req.quantity
        pos_result = await self.db.execute(
            select(PaperPosition).where(
                PaperPosition.account_id == account.id,
                PaperPosition.ticker == ticker,
            )
        )
        position = pos_result.scalar_one_or_none()
        filled_qty = req.quantity

        if req.side == "buy":
            if position and position.side == "short":
                if req.quantity > position.quantity:
                    raise ValueError(
                        f"Buy quantity {req.quantity} exceeds short position of {position.quantity}"
                    )
                account.cash_balance -= cost
                position.quantity -= req.quantity
                if position.quantity == 0:
                    await self.db.delete(position)
            else:
                if account.cash_balance < cost:
                    raise ValueError("Insufficient cash balance")
                account.cash_balance -= cost
                if position and position.side == "long":
                    total_qty = position.quantity + req.quantity
                    position.avg_price = (position.avg_price * position.quantity + price * req.quantity) / total_qty
                    position.quantity = total_qty
                    position.sl_pct = req.sl_pct or position.sl_pct
                    position.tp_pct = req.tp_pct or position.tp_pct
                else:
                    self.db.add(
                        PaperPosition(
                            account_id=account.id,
                            ticker=ticker,
                            quantity=req.quantity,
                            avg_price=price,
                            side="long",
                            sl_pct=req.sl_pct,
                            tp_pct=req.tp_pct,
                            strategy=req.strategy,
                        )
                    )
        else:
            if position and position.side == "long":
                filled_qty = min(req.quantity, position.quantity)
                if filled_qty == 0:
                    raise ValueError(f"No shares to sell for {ticker}")
                account.cash_balance += price * filled_qty
                position.quantity -= filled_qty
                if position.quantity == 0:
                    await self.db.delete(position)
            elif position and position.side == "short":
                account.cash_balance += cost
                total_qty = position.quantity + req.quantity
                position.avg_price = (position.avg_price * position.quantity + price * req.quantity) / total_qty
                position.quantity = total_qty
            else:
                account.cash_balance += cost
                self.db.add(
                    PaperPosition(
                        account_id=account.id,
                        ticker=ticker,
                        quantity=req.quantity,
                        avg_price=price,
                        side="short",
                        sl_pct=req.sl_pct,
                        tp_pct=req.tp_pct,
                        strategy=req.strategy,
                    )
                )

        order = PaperOrder(
            account_id=account.id,
            ticker=ticker,
            side=req.side,
            quantity=filled_qty,
            price=price,
            strategy=req.strategy,
            sl_pct=req.sl_pct,
            tp_pct=req.tp_pct,
        )
        self.db.add(order)
        await self.db.commit()
        return {"ok": True, "order_id": order.id, "price": round(price, 2)}

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
        await self.db.commit()
        return {"ok": True, "message": "Paper account reset"}

    async def execute_from_signal(self, signal: dict) -> dict:
        if signal.get("action") not in ("BUY", "SELL"):
            raise ValueError("Signal action must be BUY or SELL")
        qty = max(1, int(10000 / signal["price"]))
        return await self.place_order(
            PlaceOrderRequest(
                ticker=signal["ticker"],
                side="buy" if signal["action"] == "BUY" else "sell",
                quantity=qty,
                price=signal.get("price"),
                strategy=signal.get("strategy"),
                sl_pct=signal.get("sl_pct"),
                tp_pct=signal.get("tp_pct"),
            )
        )
