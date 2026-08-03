"""Auto Trade — schedule CRUD + sweep execution + suggestion retrieval.

A "sweep" runs `suggestion_engine.run_full_sweep()` across all 16
(asset_class, style) buckets and persists the ranked results as
`TradeSuggestion` rows, superseding the previous batch. It's fire-and-forget
(mirrors `backtester_leaderboard_jobs.run_backtester_job`'s pattern of
building its own independent DB session, since the request-scoped one may
be closed by the time a multi-minute sweep finishes) rather than something
the caller awaits directly.

Unlike the backtester's named background jobs, an interrupted sweep doesn't
need explicit resume-on-restart: this is an anonymous recurring system job,
not a user-named report someone is waiting to revisit — the next scheduled
tick (within `interval_minutes`) naturally re-runs it, which is functionally
equivalent to resuming for this use case.
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
from app.models.db_models import SuggestionEngineSchedule, TradeSuggestion
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)


class SuggestionEngineService:
    def __init__(self, settings: SettingsService, db: AsyncSession):
        self.settings = settings
        self.db = db

    def _schedule_to_dict(self, row: SuggestionEngineSchedule) -> dict[str, Any]:
        return {
            "enabled": row.enabled,
            "interval_minutes": row.interval_minutes,
            "universe_cap": row.universe_cap,
            "top_n": row.top_n,
            "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None,
            "next_run_at": row.next_run_at.isoformat() if row.next_run_at else None,
            "last_status": row.last_status,
        }

    async def get_or_create_schedule(self, user_id: int) -> SuggestionEngineSchedule:
        result = await self.db.execute(
            select(SuggestionEngineSchedule).where(SuggestionEngineSchedule.user_id == user_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = SuggestionEngineSchedule(user_id=user_id)
            self.db.add(row)
            await self.db.commit()
            await self.db.refresh(row)
        return row

    async def get_schedule(self, user_id: int) -> dict[str, Any]:
        return self._schedule_to_dict(await self.get_or_create_schedule(user_id))

    async def update_schedule(
        self,
        user_id: int,
        *,
        interval_minutes: int | None = None,
        universe_cap: int | None = None,
        top_n: int | None = None,
    ) -> dict[str, Any]:
        row = await self.get_or_create_schedule(user_id)
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
        return self._schedule_to_dict(row)

    async def start(self, user_id: int) -> dict[str, Any]:
        row = await self.get_or_create_schedule(user_id)
        row.enabled = True
        row.next_run_at = datetime.utcnow()  # due immediately — worker picks it up within 30s
        await self.db.commit()
        await self.db.refresh(row)
        return self._schedule_to_dict(row)

    async def stop(self, user_id: int) -> dict[str, Any]:
        row = await self.get_or_create_schedule(user_id)
        row.enabled = False
        row.next_run_at = None
        await self.db.commit()
        await self.db.refresh(row)
        return self._schedule_to_dict(row)

    async def list_suggestions(
        self, user_id: int, *, asset_class: str | None = None, style: str | None = None,
    ) -> list[dict[str, Any]]:
        stmt = select(TradeSuggestion).where(TradeSuggestion.user_id == user_id)
        if asset_class:
            stmt = stmt.where(TradeSuggestion.asset_class == asset_class)
        if style:
            stmt = stmt.where(TradeSuggestion.style == style)
        stmt = stmt.order_by(TradeSuggestion.asset_class, TradeSuggestion.style, TradeSuggestion.rank)
        rows = (await self.db.execute(stmt)).scalars().all()
        return [
            json_safe({
                "id": r.id,
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


def run_suggestion_sweep(user_id: int) -> None:
    """Fire-and-forget: kicks off a full 16-bucket sweep for `user_id` on the
    running event loop, building its own DB session (see module docstring)."""

    async def _run() -> None:
        from app.core.database import AsyncSessionLocal

        batch_id = uuid.uuid4().hex[:16]
        async with AsyncSessionLocal() as db:
            settings = SettingsService(db)
            svc = SuggestionEngineService(settings, db)
            row = await svc.get_or_create_schedule(user_id)
            row.last_status = "Running…"
            await db.commit()

            def _progress(p: float, note: str) -> None:
                logger.info("Auto Trade sweep %s: %.0f%% — %s", batch_id, p * 100, note)

            try:
                results = await se.run_full_sweep(
                    settings=settings, db=db, universe_cap=row.universe_cap, top_n=row.top_n,
                    progress_cb=_progress,
                )
            except Exception as exc:
                logger.exception("Auto Trade sweep %s failed", batch_id)
                row.last_status = f"Failed: {exc}"[:256]
                row.last_run_at = datetime.utcnow()
                if row.enabled:
                    row.next_run_at = row.last_run_at + timedelta(minutes=row.interval_minutes)
                await db.commit()
                return

            total = 0
            for key, bucket_rows in results.items():
                asset_class, style = key.split(":", 1)
                for r in bucket_rows:
                    db.add(TradeSuggestion(
                        user_id=user_id, batch_id=batch_id, asset_class=asset_class, style=style,
                        ticker=r["ticker"], action=r["action"], confidence_pct=r["confidence_pct"],
                        grade=r["grade"], entry_price=r.get("entry_price"), sl_pct=r.get("sl_pct"),
                        tp_pct=r.get("tp_pct"), stop_price=r.get("stop_price"), target_price=r.get("target_price"),
                        reasons_json=json.dumps(r.get("reasons") or []), plain_english=r.get("plain_english", ""),
                        rank=r["rank"],
                    ))
                    total += 1

            await db.execute(
                delete(TradeSuggestion).where(
                    TradeSuggestion.user_id == user_id, TradeSuggestion.batch_id != batch_id,
                )
            )

            row.last_run_at = datetime.utcnow()
            row.last_status = f"OK — {total} suggestion(s) across {len(results)} buckets"
            if row.enabled:
                row.next_run_at = row.last_run_at + timedelta(minutes=row.interval_minutes)
            await db.commit()

    asyncio.create_task(_run(), name=f"auto-trade-sweep-{user_id}")
