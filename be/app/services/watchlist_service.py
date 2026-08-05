"""Watchlists — per-user ticker lists with live price resolution."""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import Watchlist, WatchlistItem
from app.services.settings_service import SettingsService

_MARKET_LABELS = {
    "india": "Groww (India Stocks)",
    "us": "US Stocks (Yahoo)",
    "crypto": "CoinDCX Futures",
}


class WatchlistService:
    def __init__(self, db: AsyncSession, settings: SettingsService):
        self.db = db
        self.settings = settings

    async def list_watchlists(self, user_id: int) -> list[dict[str, Any]]:
        result = await self.db.execute(
            select(Watchlist).where(Watchlist.user_id == user_id).order_by(Watchlist.created_at.asc())
        )
        return [self._watchlist_dict(w) for w in result.scalars().all()]

    async def create_watchlist(self, user_id: int, market_type: str, name: str) -> dict[str, Any]:
        name = (name or "").strip()
        if not name:
            raise ValueError("Watchlist name cannot be empty.")
        existing = await self.db.execute(
            select(Watchlist).where(
                Watchlist.user_id == user_id,
                Watchlist.market_type == market_type,
                Watchlist.name == name,
            )
        )
        if existing.scalar_one_or_none():
            raise ValueError(f"A watchlist named '{name}' already exists for this market.")
        wl = Watchlist(user_id=user_id, market_type=market_type, name=name)
        self.db.add(wl)
        await self.db.commit()
        await self.db.refresh(wl)
        return self._watchlist_dict(wl)

    async def delete_watchlist(self, user_id: int, watchlist_id: int) -> bool:
        wl = await self._get_owned(user_id, watchlist_id)
        if not wl:
            return False
        await self.db.execute(
            WatchlistItem.__table__.delete().where(WatchlistItem.watchlist_id == watchlist_id)
        )
        await self.db.delete(wl)
        await self.db.commit()
        return True

    async def add_item(
        self, user_id: int, watchlist_id: int, ticker: str, display_name: str = "", added_price: float | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        wl = await self._get_owned(user_id, watchlist_id)
        if not wl:
            raise ValueError("Watchlist not found.")
        ticker = ticker.upper().strip()
        if added_price is None:
            added_price = await self._fetch_ltp(wl.market_type, ticker)
        item = WatchlistItem(
            watchlist_id=watchlist_id,
            ticker=ticker,
            display_name=display_name or ticker,
            added_price=added_price,
            notes=(notes or "").strip() or None,
        )
        self.db.add(item)
        await self.db.commit()
        await self.db.refresh(item)
        return self._item_dict(item)

    async def _fetch_ltp(self, market_type: str, ticker: str) -> float | None:
        """Best-effort live LTP lookup — used to snapshot `added_price` when a
        ticker is added without one explicitly supplied."""
        market_label = _MARKET_LABELS.get(market_type, _MARKET_LABELS["india"])
        token = await self.settings.get_groww_token() or ""
        exchange = await self.settings.get_groww_exchange()

        def _fetch() -> float | None:
            from backtesting.data_fetcher import get_live_quote

            try:
                quote = get_live_quote(ticker, market_label, exchange=exchange, groww_token=token) or {}
            except Exception:
                quote = {}
            ltp = quote.get("ltp")
            return float(ltp) if ltp is not None else None

        return await asyncio.to_thread(_fetch)

    async def update_item(
        self, user_id: int, watchlist_id: int, item_id: int, *,
        display_name: str | None = None, notes: str | None = None,
    ) -> dict[str, Any]:
        wl = await self._get_owned(user_id, watchlist_id)
        if not wl:
            raise ValueError("Watchlist not found.")
        result = await self.db.execute(
            select(WatchlistItem).where(WatchlistItem.id == item_id, WatchlistItem.watchlist_id == watchlist_id)
        )
        item = result.scalar_one_or_none()
        if not item:
            raise ValueError("Item not found.")
        if display_name is not None:
            item.display_name = display_name.strip() or item.ticker
        if notes is not None:
            item.notes = notes.strip() or None
        await self.db.commit()
        await self.db.refresh(item)
        return self._item_dict(item)

    async def remove_item(self, user_id: int, watchlist_id: int, item_id: int) -> bool:
        wl = await self._get_owned(user_id, watchlist_id)
        if not wl:
            return False
        result = await self.db.execute(
            select(WatchlistItem).where(WatchlistItem.id == item_id, WatchlistItem.watchlist_id == watchlist_id)
        )
        item = result.scalar_one_or_none()
        if not item:
            return False
        await self.db.delete(item)
        await self.db.commit()
        return True

    async def get_items_with_quotes(self, user_id: int, watchlist_id: int) -> dict[str, Any]:
        """Resolve live LTP + change% for every ticker in a watchlist."""
        wl = await self._get_owned(user_id, watchlist_id)
        if not wl:
            raise ValueError("Watchlist not found.")
        result = await self.db.execute(
            select(WatchlistItem).where(WatchlistItem.watchlist_id == watchlist_id).order_by(WatchlistItem.added_at.asc())
        )
        items = list(result.scalars().all())
        market_label = _MARKET_LABELS.get(wl.market_type, _MARKET_LABELS["india"])
        token = await self.settings.get_groww_token() or ""
        exchange = await self.settings.get_groww_exchange()

        def _quote_one(item: WatchlistItem) -> dict[str, Any]:
            from backtesting.data_fetcher import get_live_quote

            quote = {}
            try:
                quote = get_live_quote(item.ticker, market_label, exchange=exchange, groww_token=token) or {}
            except Exception:
                quote = {}
            ltp = quote.get("ltp")
            change_pct = quote.get("change_pct")
            added_pct = None
            if ltp is not None and item.added_price:
                added_pct = (float(ltp) - item.added_price) / item.added_price * 100
            return {
                **self._item_dict(item),
                "ltp": ltp,
                "change_pct": change_pct,
                "change_since_added_pct": added_pct,
            }

        def _quote_all():
            from concurrent.futures import ThreadPoolExecutor

            # Each quote is its own blocking HTTP round trip (Groww + yfinance
            # fallback) — fetching them concurrently instead of one-at-a-time
            # both speeds up larger watchlists and stops one slow/failing
            # ticker from delaying (or, via a shared-timeout illusion, seeming
            # to sink) the rest of the list.
            with ThreadPoolExecutor(max_workers=min(8, max(1, len(items)))) as ex:
                return list(ex.map(_quote_one, items))

        rows = await asyncio.to_thread(_quote_all)
        return {**self._watchlist_dict(wl), "items": rows}

    async def _get_owned(self, user_id: int, watchlist_id: int) -> Watchlist | None:
        result = await self.db.execute(
            select(Watchlist).where(Watchlist.id == watchlist_id, Watchlist.user_id == user_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _watchlist_dict(w: Watchlist) -> dict[str, Any]:
        return {
            "id": w.id,
            "market_type": w.market_type,
            "name": w.name,
            "created_at": w.created_at.isoformat() if w.created_at else None,
        }

    @staticmethod
    def _item_dict(i: WatchlistItem) -> dict[str, Any]:
        return {
            "id": i.id,
            "watchlist_id": i.watchlist_id,
            "ticker": i.ticker,
            "display_name": i.display_name,
            "added_price": i.added_price,
            "notes": i.notes,
            "added_at": i.added_at.isoformat() if i.added_at else None,
        }
