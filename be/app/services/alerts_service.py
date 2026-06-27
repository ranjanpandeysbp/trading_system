"""Strategy alert monitors — Telegram / email notifications."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.market_pulse.alert_notifier import email_configured, send_trade_setup_alert, telegram_configured
from app.market_pulse.env_config import is_alerts_enabled
from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.groww_auth import set_groww_token
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.signal_eval import evaluate_trade_setup
from app.market_pulse.serialize import json_safe
from app.models.db_models import AlertMonitor
from app.services.settings_service import SettingsService


class AlertsService:
    def __init__(self, db: AsyncSession, settings: SettingsService):
        self.db = db
        self.settings = settings

    async def config(self) -> dict[str, Any]:
        return {
            "alerts_enabled": is_alerts_enabled(),
            "telegram_configured": telegram_configured(),
            "email_configured": email_configured(),
            "poll_options": [1, 5, 15, 30, 60],
        }

    async def list_monitors(self, user_id: int) -> list[dict[str, Any]]:
        result = await self.db.execute(
            select(AlertMonitor).where(AlertMonitor.user_id == user_id).order_by(AlertMonitor.id.desc())
        )
        return [self._monitor_dict(m) for m in result.scalars().all()]

    async def create_monitor(self, user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        mon = AlertMonitor(
            user_id=user_id,
            name=payload["name"],
            market=payload.get("market") or await self.settings.get_default_market(),
            ticker=str(payload["ticker"]).upper(),
            timeframe=payload.get("timeframe", "1d"),
            strategy_name=payload.get("strategy_name", "Custom"),
            indicators_json=json.dumps(payload.get("indicators") or []),
            entry_rules_json=json.dumps(payload.get("entry_rules") or []),
            exit_rules_json=json.dumps(payload.get("exit_rules") or []),
            entry_mode=payload.get("entry_mode", "AND"),
            poll_minutes=int(payload.get("poll_minutes", 15)),
            notify_telegram=bool(payload.get("notify_telegram", True)),
            notify_email=bool(payload.get("notify_email", False)),
            enabled=bool(payload.get("enabled", True)),
        )
        self.db.add(mon)
        await self.db.commit()
        await self.db.refresh(mon)
        return self._monitor_dict(mon)

    async def delete_monitor(self, user_id: int, monitor_id: int) -> bool:
        result = await self.db.execute(
            select(AlertMonitor).where(AlertMonitor.id == monitor_id, AlertMonitor.user_id == user_id)
        )
        mon = result.scalar_one_or_none()
        if not mon:
            return False
        await self.db.delete(mon)
        await self.db.commit()
        return True

    async def toggle_monitor(self, user_id: int, monitor_id: int, enabled: bool) -> bool:
        result = await self.db.execute(
            select(AlertMonitor).where(AlertMonitor.id == monitor_id, AlertMonitor.user_id == user_id)
        )
        mon = result.scalar_one_or_none()
        if not mon:
            return False
        mon.enabled = enabled
        await self.db.commit()
        return True

    async def poll_all(self, user_id: int, *, force: bool = False) -> dict[str, Any]:
        result = await self.db.execute(
            select(AlertMonitor).where(AlertMonitor.user_id == user_id, AlertMonitor.enabled == True)  # noqa: E712
        )
        monitors = list(result.scalars().all())
        token = await self.settings.get_groww_token() or ""
        exchange = await self.settings.get_groww_exchange()

        def _run_batch():
            set_groww_token(token)
            checks = []
            for mon in monitors:
                checks.append(self._check_one(mon, token, exchange, force=force))
            return checks

        checks = await asyncio.to_thread(_run_batch)
        for mon, check in zip(monitors, checks):
            mon.last_checked_at = datetime.utcnow()
            mon.last_signal = check.get("new_state") or mon.last_signal
            if check.get("alert_sent"):
                mon.last_alert_at = datetime.utcnow()
        await self.db.commit()
        return json_safe({"polled": len(checks), "results": checks})

    def _check_one(self, mon: AlertMonitor, token: str, exchange: str, *, force: bool) -> dict[str, Any]:
        out = {
            "monitor_id": mon.id,
            "name": mon.name,
            "ticker": mon.ticker,
            "ok": False,
            "signal": "NONE",
            "alert_sent": False,
            "message": "",
        }
        if not force and mon.last_checked_at:
            due = datetime.utcnow() - mon.last_checked_at >= timedelta(minutes=mon.poll_minutes)
            if not due:
                out["message"] = "Skipped (not due yet)"
                return out

        try:
            indicators = json.loads(mon.indicators_json)
            entry_rules = json.loads(mon.entry_rules_json)
            exit_rules = json.loads(mon.exit_rules_json)
        except json.JSONDecodeError:
            out["message"] = "Invalid strategy JSON"
            return out

        try:
            df = fetch_data_for_gap_scan(
                mon.ticker, mon.timeframe, mon.market, token, exchange, limit=400,
            )
            df = normalize_ohlcv(df)
            if df.empty:
                out["message"] = "No data"
                return out
            eval_res = evaluate_trade_setup(df, indicators, entry_rules, exit_rules, entry_mode=mon.entry_mode)
        except Exception as exc:
            out["message"] = f"Data error: {exc}"
            return out

        out["ok"] = True
        out["signal"] = eval_res.get("signal", "NONE")
        prev = (mon.last_signal or "INACTIVE").upper()
        entry_active = eval_res.get("entry_active")
        new_state = "ACTIVE" if entry_active else "INACTIVE"
        out["new_state"] = new_state

        if entry_active and prev != "ACTIVE" and is_alerts_enabled():
            send_res = send_trade_setup_alert(
                ticker=mon.ticker,
                timeframe=mon.timeframe,
                strategy=mon.strategy_name,
                market=mon.market,
                signal=eval_res["signal"],
                close=eval_res["close"],
                bar_time=eval_res.get("bar_time"),
                monitor_name=mon.name,
                via_telegram=mon.notify_telegram,
                via_email=mon.notify_email,
            )
            out["alert_sent"] = True
            out["send_results"] = send_res
            out["message"] = f"Alert sent · {eval_res['signal']}"
        else:
            out["message"] = "Active" if entry_active else "No new entry"
        return out

    @staticmethod
    def _monitor_dict(m: AlertMonitor) -> dict[str, Any]:
        return {
            "id": m.id,
            "name": m.name,
            "market": m.market,
            "ticker": m.ticker,
            "timeframe": m.timeframe,
            "strategy_name": m.strategy_name,
            "poll_minutes": m.poll_minutes,
            "notify_telegram": m.notify_telegram,
            "notify_email": m.notify_email,
            "enabled": m.enabled,
            "last_signal": m.last_signal,
            "last_checked_at": m.last_checked_at.isoformat() if m.last_checked_at else None,
            "last_alert_at": m.last_alert_at.isoformat() if m.last_alert_at else None,
        }
