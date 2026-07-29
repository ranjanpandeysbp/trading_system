"""Trade Candidate hub — save a single ticker + timeframe + strategy-set
setup, then live-check it for BUY/SELL triggers on demand (the frontend
polls the check endpoint at an interval matched to the candidate's own
timeframe). Reuses ScannerService.scan(), the same engine backing the
Scanner page and Alerts schedules, so rule-based, Trading Hub engine, and
Strategy Lab preset strategies all work identically here."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import TradeCandidate, TradeCandidateHit
from app.models.schemas import ScanRequest
from app.services.scanner_service import ScannerService
from app.services.settings_service import SettingsService


def _parse_json_list(raw: str | None) -> list[str]:
    try:
        data = json.loads(raw or "[]")
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]
    except json.JSONDecodeError:
        pass
    return []


class TradeCandidateService:
    def __init__(self, db: AsyncSession, settings: SettingsService):
        self.db = db
        self.settings = settings

    # ── CRUD ──────────────────────────────────────────────────────────────

    async def list_candidates(self, user_id: int) -> list[dict[str, Any]]:
        result = await self.db.execute(
            select(TradeCandidate).where(TradeCandidate.user_id == user_id).order_by(TradeCandidate.id.desc())
        )
        return [self._dict(c) for c in result.scalars().all()]

    async def create_candidate(self, user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        ticker = str(payload["ticker"]).strip().upper()
        timeframe = str(payload["timeframe"]).strip()
        strategies = list(payload.get("strategies") or [])
        if not ticker or not timeframe or not strategies:
            raise ValueError("Ticker, timeframe, and at least one strategy are required")

        name = (payload.get("name") or "").strip() or f"{ticker} · {timeframe} · {len(strategies)} strategies"

        cand = TradeCandidate(
            user_id=user_id,
            name=name,
            asset_class=payload.get("asset_class") or "india",
            ticker=ticker,
            timeframe=timeframe,
            strategies_json=json.dumps(strategies),
            enabled=bool(payload.get("enabled", True)),
        )
        self.db.add(cand)
        await self.db.commit()
        await self.db.refresh(cand)
        return self._dict(cand)

    async def update_candidate(self, user_id: int, candidate_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
        cand = await self._get(user_id, candidate_id)
        if not cand:
            return None
        if "name" in payload and payload["name"]:
            cand.name = str(payload["name"]).strip()
        if "ticker" in payload and payload["ticker"]:
            cand.ticker = str(payload["ticker"]).strip().upper()
        if "timeframe" in payload and payload["timeframe"]:
            cand.timeframe = str(payload["timeframe"]).strip()
        if "strategies" in payload and payload["strategies"] is not None:
            cand.strategies_json = json.dumps(list(payload["strategies"]))
        if "enabled" in payload and payload["enabled"] is not None:
            cand.enabled = bool(payload["enabled"])
        await self.db.commit()
        await self.db.refresh(cand)
        return self._dict(cand)

    async def delete_candidate(self, user_id: int, candidate_id: int) -> bool:
        cand = await self._get(user_id, candidate_id)
        if not cand:
            return False
        await self.db.delete(cand)
        await self.db.commit()
        return True

    async def _get(self, user_id: int, candidate_id: int) -> TradeCandidate | None:
        result = await self.db.execute(
            select(TradeCandidate).where(TradeCandidate.id == candidate_id, TradeCandidate.user_id == user_id)
        )
        return result.scalar_one_or_none()

    # ── live check ────────────────────────────────────────────────────────

    async def check_candidate(self, user_id: int, candidate_id: int) -> dict[str, Any]:
        cand = await self._get(user_id, candidate_id)
        if not cand:
            return {"error": "Trade candidate not found"}

        strategies = _parse_json_list(cand.strategies_json)
        if not strategies:
            return {"error": "No strategies configured"}

        signals = await ScannerService(self.settings).scan(
            ScanRequest(
                tickers=[cand.ticker],
                strategies=strategies,
                timeframes=[cand.timeframe],
                asset_class=cand.asset_class,  # type: ignore[arg-type]
            )
        )

        results = []
        hits_created = 0
        for sig in signals:
            action = sig.action
            results.append({
                "strategy_id": sig.strategy,
                "strategy_label": sig.strategy_label,
                "action": action,
                "confidence_pct": sig.confidence_pct,
                "sl_pct": sig.sl_pct,
                "tp_pct": sig.tp_pct,
                "price": sig.price,
                "rationale": sig.rationale,
                "timestamp": sig.timestamp,
            })
            if action in ("BUY", "SELL"):
                created = await self._persist_hit(cand, sig)
                hits_created += created

        cand.last_checked_at = datetime.utcnow()
        await self.db.commit()

        return {
            "candidate_id": cand.id,
            "name": cand.name,
            "ticker": cand.ticker,
            "timeframe": cand.timeframe,
            "asset_class": cand.asset_class,
            "results": results,
            "hits_created": hits_created,
            "checked_at": cand.last_checked_at.isoformat(),
        }

    async def _persist_hit(self, cand: TradeCandidate, sig: Any) -> int:
        dedupe = f"{cand.id}|{sig.strategy}|{sig.action}|{sig.timestamp}"
        exists = await self.db.execute(
            select(TradeCandidateHit).where(TradeCandidateHit.dedupe_key == dedupe)
        )
        if exists.scalar_one_or_none():
            return 0
        self.db.add(TradeCandidateHit(
            candidate_id=cand.id,
            user_id=cand.user_id,
            candidate_name=cand.name,
            ticker=sig.ticker,
            timeframe=sig.timeframe,
            asset_class=cand.asset_class,
            strategy_id=sig.strategy,
            strategy_label=sig.strategy_label,
            verdict=sig.action,
            confidence_pct=sig.confidence_pct,
            price=sig.price,
            rationale=sig.rationale,
            bar_asof=sig.timestamp,
            dedupe_key=dedupe,
        ))
        return 1

    # ── hits ──────────────────────────────────────────────────────────────

    async def list_hits(self, user_id: int, *, limit: int = 100, candidate_id: int | None = None) -> list[dict[str, Any]]:
        q = select(TradeCandidateHit).where(TradeCandidateHit.user_id == user_id)
        if candidate_id is not None:
            q = q.where(TradeCandidateHit.candidate_id == candidate_id)
        q = q.order_by(TradeCandidateHit.id.desc()).limit(limit)
        result = await self.db.execute(q)
        return [self._hit_dict(h) for h in result.scalars().all()]

    async def delete_hit(self, user_id: int, hit_id: int) -> bool:
        result = await self.db.execute(
            select(TradeCandidateHit).where(TradeCandidateHit.id == hit_id, TradeCandidateHit.user_id == user_id)
        )
        row = result.scalar_one_or_none()
        if not row:
            return False
        await self.db.delete(row)
        await self.db.commit()
        return True

    async def delete_hits(self, user_id: int, hit_ids: list[int]) -> int:
        ids = [int(i) for i in hit_ids if i is not None]
        if not ids:
            return 0
        result = await self.db.execute(
            delete(TradeCandidateHit).where(
                TradeCandidateHit.user_id == user_id, TradeCandidateHit.id.in_(ids),
            )
        )
        await self.db.commit()
        return int(result.rowcount or 0)

    async def delete_all_hits(self, user_id: int, *, candidate_id: int | None = None) -> int:
        q = delete(TradeCandidateHit).where(TradeCandidateHit.user_id == user_id)
        if candidate_id is not None:
            q = q.where(TradeCandidateHit.candidate_id == candidate_id)
        result = await self.db.execute(q)
        await self.db.commit()
        return int(result.rowcount or 0)

    @staticmethod
    def _dict(c: TradeCandidate) -> dict[str, Any]:
        return {
            "id": c.id,
            "name": c.name,
            "asset_class": c.asset_class,
            "ticker": c.ticker,
            "timeframe": c.timeframe,
            "strategies": _parse_json_list(c.strategies_json),
            "enabled": c.enabled,
            "last_checked_at": c.last_checked_at.isoformat() if c.last_checked_at else None,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }

    @staticmethod
    def _hit_dict(h: TradeCandidateHit) -> dict[str, Any]:
        return {
            "id": h.id,
            "candidate_id": h.candidate_id,
            "candidate_name": h.candidate_name,
            "ticker": h.ticker,
            "timeframe": h.timeframe,
            "asset_class": h.asset_class,
            "strategy_id": h.strategy_id,
            "strategy_label": h.strategy_label,
            "verdict": h.verdict,
            "confidence_pct": h.confidence_pct,
            "price": h.price,
            "rationale": h.rationale,
            "bar_asof": h.bar_asof,
            "created_at": h.created_at.isoformat() if h.created_at else None,
        }
