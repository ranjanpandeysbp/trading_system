"""Auto Trade — setup CRUD + per-setup sweep execution + suggestion retrieval.

A user can create multiple named "setups", each scanning a single
(asset_class, style) bucket on its own schedule (e.g. "Crypto Scalping" every
30 minutes, "India Swing" every 6 hours) — started/stopped/deleted
independently. A "sweep" runs `suggestion_engine.run_bucket()` for one
setup's bucket and persists the ranked results as `TradeSuggestion` rows tied
to that `setup_id`, superseding that setup's previous batch.

Sweeps are fire-and-forget (mirrors `backtester_leaderboard_jobs.run_backtester_job`'s
pattern of building its own independent DB session, since the request-scoped
one may be closed by the time a multi-ticker sweep finishes). An interrupted
sweep doesn't need explicit resume-on-restart: the next scheduled tick
(within `interval_minutes`) naturally re-runs it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.market_pulse import suggestion_engine as se
from app.market_pulse.serialize import json_safe
from app.models.db_models import AutoTradeSetup, TradeSuggestion
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)


class SuggestionEngineService:
    def __init__(self, settings: SettingsService, db: AsyncSession):
        self.settings = settings
        self.db = db

    def _setup_to_dict(self, row: AutoTradeSetup) -> dict[str, Any]:
        return {
            "id": row.id,
            "name": row.name,
            "asset_class": row.asset_class,
            "style": row.style,
            "direction": row.direction,
            "enabled": row.enabled,
            "interval_minutes": row.interval_minutes,
            "universe_cap": row.universe_cap,
            "top_n": row.top_n,
            "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None,
            "next_run_at": row.next_run_at.isoformat() if row.next_run_at else None,
            "last_status": row.last_status,
        }

    async def _get_owned(self, user_id: int, setup_id: int) -> AutoTradeSetup:
        row = await self.db.get(AutoTradeSetup, setup_id)
        if row is None or row.user_id != user_id:
            raise ValueError("Auto Trade setup not found")
        return row

    async def list_setups(self, user_id: int) -> list[dict[str, Any]]:
        rows = (
            await self.db.execute(
                select(AutoTradeSetup).where(AutoTradeSetup.user_id == user_id).order_by(AutoTradeSetup.created_at)
            )
        ).scalars().all()
        return [self._setup_to_dict(r) for r in rows]

    async def create_setup(
        self,
        user_id: int,
        *,
        name: str,
        asset_class: str,
        style: str,
        direction: str = "both",
        interval_minutes: int = 360,
        universe_cap: int = 20,
        top_n: int = 8,
    ) -> dict[str, Any]:
        if asset_class not in se.ASSET_CLASSES:
            raise ValueError(f"Unknown asset class: {asset_class}")
        if style not in se.STYLES:
            raise ValueError(f"Unknown style: {style}")
        if direction not in ("both", "long_only", "short_only"):
            raise ValueError(f"Unknown direction: {direction}")
        row = AutoTradeSetup(
            user_id=user_id,
            name=(name or "").strip()[:120] or f"{asset_class.title()} {style.title()}",
            asset_class=asset_class,
            style=style,
            direction=direction,
            interval_minutes=max(15, min(1440, interval_minutes)),
            universe_cap=max(5, min(50, universe_cap)),
            top_n=max(1, min(20, top_n)),
        )
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return self._setup_to_dict(row)

    async def update_setup(
        self,
        user_id: int,
        setup_id: int,
        *,
        name: str | None = None,
        direction: str | None = None,
        interval_minutes: int | None = None,
        universe_cap: int | None = None,
        top_n: int | None = None,
    ) -> dict[str, Any]:
        row = await self._get_owned(user_id, setup_id)
        if name is not None:
            row.name = name.strip()[:120] or row.name
        if direction is not None:
            if direction not in ("both", "long_only", "short_only"):
                raise ValueError(f"Unknown direction: {direction}")
            row.direction = direction
        if interval_minutes is not None:
            row.interval_minutes = max(15, min(1440, interval_minutes))
            if row.enabled and row.last_run_at:
                row.next_run_at = row.last_run_at + timedelta(minutes=row.interval_minutes)
        if universe_cap is not None:
            row.universe_cap = max(5, min(50, universe_cap))
        if top_n is not None:
            row.top_n = max(1, min(20, top_n))
        await self.db.commit()
        await self.db.refresh(row)
        return self._setup_to_dict(row)

    async def delete_setup(self, user_id: int, setup_id: int) -> dict[str, Any]:
        row = await self._get_owned(user_id, setup_id)
        await self.db.execute(delete(TradeSuggestion).where(TradeSuggestion.setup_id == setup_id))
        await self.db.delete(row)
        await self.db.commit()
        return {"deleted": True}

    async def start_setup(self, user_id: int, setup_id: int) -> dict[str, Any]:
        row = await self._get_owned(user_id, setup_id)
        row.enabled = True
        row.next_run_at = datetime.utcnow()  # due immediately — worker picks it up within 30s
        await self.db.commit()
        await self.db.refresh(row)
        return self._setup_to_dict(row)

    async def stop_setup(self, user_id: int, setup_id: int) -> dict[str, Any]:
        row = await self._get_owned(user_id, setup_id)
        row.enabled = False
        row.next_run_at = None
        await self.db.commit()
        await self.db.refresh(row)
        return self._setup_to_dict(row)

    async def list_suggestions(
        self, user_id: int, *, setup_id: int | None = None, asset_class: str | None = None, style: str | None = None,
    ) -> list[dict[str, Any]]:
        stmt = select(TradeSuggestion).where(TradeSuggestion.user_id == user_id)
        if setup_id is not None:
            stmt = stmt.where(TradeSuggestion.setup_id == setup_id)
        if asset_class:
            stmt = stmt.where(TradeSuggestion.asset_class == asset_class)
        if style:
            stmt = stmt.where(TradeSuggestion.style == style)
        stmt = stmt.order_by(TradeSuggestion.setup_id, TradeSuggestion.rank)
        rows = (await self.db.execute(stmt)).scalars().all()
        return [
            json_safe({
                "id": r.id,
                "setup_id": r.setup_id,
                "batch_id": r.batch_id,
                "asset_class": r.asset_class,
                "style": r.style,
                "ticker": r.ticker,
                "action": r.action,
                "confidence_pct": r.confidence_pct,
                "grade": r.grade,
                "entry_price": r.entry_price,
                "sl_pct": r.sl_pct,
                "tp_pct": r.tp_pct,
                "stop_price": r.stop_price,
                "target_price": r.target_price,
                "reasons": json.loads(r.reasons_json or "[]"),
                "plain_english": r.plain_english,
                "rank": r.rank,
                "created_at": r.created_at.isoformat(),
            })
            for r in rows
        ]


def run_suggestion_sweep(setup_id: int) -> None:
    """Fire-and-forget: runs the sweep for one Auto Trade setup on the
    running event loop, building its own DB session (see module docstring)."""

    async def _run() -> None:
        from app.core.database import AsyncSessionLocal

        batch_id = uuid.uuid4().hex[:16]
        async with AsyncSessionLocal() as db:
            row = await db.get(AutoTradeSetup, setup_id)
            if row is None:
                logger.warning("Auto Trade sweep requested for missing setup %s", setup_id)
                return
            user_id = row.user_id
            asset_class, style = row.asset_class, row.style
            row.last_status = "Running…"
            await db.commit()

            settings = SettingsService(db)

            def _progress(p: float, note: str) -> None:
                logger.info("Auto Trade setup %s (%s) sweep %s: %.0f%% — %s", setup_id, row.name, batch_id, p * 100, note)

            try:
                results = await se.run_bucket(
                    asset_class, style, settings=settings, db=db,
                    universe_cap=row.universe_cap, top_n=row.top_n, direction_filter=row.direction,
                    progress_cb=_progress,
                )
            except Exception as exc:
                logger.exception("Auto Trade sweep %s (setup %s) failed", batch_id, setup_id)
                row.last_status = f"Failed: {exc}"[:256]
                row.last_run_at = datetime.utcnow()
                if row.enabled:
                    row.next_run_at = row.last_run_at + timedelta(minutes=row.interval_minutes)
                await db.commit()
                return

            for r in results:
                db.add(TradeSuggestion(
                    user_id=user_id, setup_id=setup_id, batch_id=batch_id, asset_class=asset_class, style=style,
                    ticker=r["ticker"], action=r["action"], confidence_pct=r["confidence_pct"],
                    grade=r["grade"], entry_price=r.get("entry_price"), sl_pct=r.get("sl_pct"),
                    tp_pct=r.get("tp_pct"), stop_price=r.get("stop_price"), target_price=r.get("target_price"),
                    reasons_json=json.dumps(r.get("reasons") or []), plain_english=r.get("plain_english", ""),
                    rank=r["rank"],
                ))

            await db.execute(
                delete(TradeSuggestion).where(
                    TradeSuggestion.setup_id == setup_id, TradeSuggestion.batch_id != batch_id,
                )
            )

            row.last_run_at = datetime.utcnow()
            row.last_status = f"OK — {len(results)} suggestion(s)"
            if row.enabled:
                row.next_run_at = row.last_run_at + timedelta(minutes=row.interval_minutes)
            await db.commit()

    asyncio.create_task(_run(), name=f"auto-trade-sweep-setup-{setup_id}")
