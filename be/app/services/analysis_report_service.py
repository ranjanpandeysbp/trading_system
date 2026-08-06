"""Generic saved-report CRUD for analysis background jobs.

Stores payloads in ``SavedBacktestReport`` with source
``analysis:{domain}:{section}``.
"""

from __future__ import annotations

import json
from datetime import datetime as datetime_cls
from typing import Any

from sqlalchemy import select

from app.models.db_models import SavedBacktestReport
from app.services.analysis_jobs import analysis_source


class AnalysisReportService:
    def __init__(self, db: Any):
        self.db = db

    @staticmethod
    def _summary(domain: str, section: str, payload: dict[str, Any]) -> dict[str, Any]:
        results = payload.get("results")
        if isinstance(results, list):
            return {
                "domain": domain,
                "section": section,
                "result_count": len(results),
            }
        signals = payload.get("signals")
        if isinstance(signals, list):
            return {"domain": domain, "section": section, "result_count": len(signals)}
        recommendations = payload.get("recommendations")
        if isinstance(recommendations, list):
            return {"domain": domain, "section": section, "result_count": len(recommendations)}
        return {
            "domain": domain,
            "section": section,
            "result_count": 1 if payload else 0,
        }

    async def save(
        self,
        domain: str,
        section: str,
        name: str,
        payload: dict[str, Any],
        *,
        user_id: int | None,
        tickers: list[str] | None = None,
        asset_class: str = "india",
    ) -> dict[str, Any]:
        if self.db is None:
            return {"error": "No database session available."}
        report = SavedBacktestReport(
            user_id=user_id,
            name=name.strip()[:200] or f"{domain}/{section} {datetime_cls.utcnow().isoformat()}",
            asset_class=asset_class,
            tickers=",".join((tickers or [])[:50]),
            timeframes=f"{domain}/{section}",
            payload_json=json.dumps(payload),
            source=analysis_source(domain, section),
        )
        self.db.add(report)
        await self.db.commit()
        await self.db.refresh(report)
        return {"id": report.id, "name": report.name, "created_at": report.created_at.isoformat()}

    async def list_reports(self, domain: str, section: str, *, user_id: int | None) -> dict[str, Any]:
        if self.db is None:
            return {"reports": []}
        source = analysis_source(domain, section)
        stmt = select(SavedBacktestReport).where(
            SavedBacktestReport.source == source
        ).order_by(SavedBacktestReport.created_at.desc())
        if user_id is not None:
            stmt = stmt.where(SavedBacktestReport.user_id == user_id)
        result = await self.db.execute(stmt)
        rows = result.scalars().all()
        reports = []
        for r in rows:
            try:
                payload = json.loads(r.payload_json) if r.payload_json else {}
            except Exception:
                payload = {}
            reports.append({
                "id": r.id,
                "name": r.name,
                "asset_class": r.asset_class,
                "created_at": r.created_at.isoformat(),
                "summary": self._summary(domain, section, payload if isinstance(payload, dict) else {}),
            })
        return {"reports": reports}

    async def get_report(self, domain: str, section: str, report_id: int, *, user_id: int | None) -> dict[str, Any]:
        if self.db is None:
            return {"error": "No database session available."}
        report = await self.db.get(SavedBacktestReport, report_id)
        source = analysis_source(domain, section)
        if not report or report.source != source or (user_id is not None and report.user_id not in (None, user_id)):
            return {"error": "Report not found."}
        return {
            "id": report.id,
            "name": report.name,
            "created_at": report.created_at.isoformat(),
            "payload": json.loads(report.payload_json),
        }

    async def delete_report(self, domain: str, section: str, report_id: int, *, user_id: int | None) -> dict[str, Any]:
        if self.db is None:
            return {"error": "No database session available."}
        report = await self.db.get(SavedBacktestReport, report_id)
        source = analysis_source(domain, section)
        if not report or report.source != source or (user_id is not None and report.user_id not in (None, user_id)):
            return {"error": "Report not found."}
        await self.db.delete(report)
        await self.db.commit()
        return {"deleted": True}
