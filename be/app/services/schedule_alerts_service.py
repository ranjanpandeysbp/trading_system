"""Named alert schedules — multi ticker×TF×strategy scans with notify + hit history."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.market_pulse.alert_notifier import (
    NotifyConfig,
    email_configured,
    notify_config_from_dict,
    send_trade_setup_alert,
    telegram_configured,
)
from app.market_pulse.env_config import is_alerts_enabled
from app.market_pulse.serialize import json_safe
from app.models.db_models import AlertNotifyConfig, AlertSchedule, AlertScheduleHit
from app.models.schemas import ScanRequest
from app.services.scanner_service import ScannerService
from app.services.schedule_catalog_service import parse_strategy_ref
from app.services.settings_service import SettingsService
from app.strategies.registry import STRATEGY_CATEGORIES, STRATEGY_META
from app.services.ta_screener_service import TaScreenerService, is_actionable_result
from app.services.trading_hub_service import TradingHubService
from app.trading_hubs.registry import get_section as get_hub_section
from app.market_pulse.ta_screener_registry import TA_SCREENERS

logger = logging.getLogger(__name__)

_LOCAL_TZ = ZoneInfo("Asia/Kolkata")


def _parse_json_list(raw: str | None) -> list[str]:
    try:
        data = json.loads(raw or "[]")
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]
    except json.JSONDecodeError:
        pass
    return []


def _safe_float(val: Any) -> float | None:
    try:
        if val is None or val == "":
            return None
        return float(val)
    except (TypeError, ValueError):
        return None


def schedule_is_due(sched: AlertSchedule, *, now: datetime | None = None) -> bool:
    """Whether an enabled schedule should run now."""
    if not sched.enabled:
        return False
    now = now or datetime.utcnow()
    mode = (sched.schedule_mode or "interval").lower()
    if mode == "daily_at":
        local_now = datetime.now(_LOCAL_TZ)
        hhmm = (sched.daily_time or "").strip()
        if len(hhmm) < 4 or ":" not in hhmm:
            return False
        try:
            h_s, m_s = hhmm.split(":", 1)
            target_h, target_m = int(h_s), int(m_s)
        except ValueError:
            return False
        if local_now.hour != target_h or local_now.minute != target_m:
            return False
        if sched.last_run_at:
            last_local = sched.last_run_at.replace(tzinfo=None)
            # last_run stored as UTC naive — compare calendar day in IST roughly via last 50 min
            if now - sched.last_run_at < timedelta(minutes=50):
                return False
        return True

    minutes = max(int(sched.poll_minutes or 15), 1)
    if not sched.last_run_at:
        return True
    return now - sched.last_run_at >= timedelta(minutes=minutes)


class ScheduleAlertsService:
    def __init__(self, db: AsyncSession, settings: SettingsService):
        self.db = db
        self.settings = settings

    # ── notify config ─────────────────────────────────────────────────────

    async def get_notify_config(self, user_id: int) -> dict[str, Any]:
        row = await self._notify_row(user_id)
        env_tg = telegram_configured()
        env_email = email_configured()
        cfg = self._notify_cfg_obj(row)
        return {
            "smtp_host": (row.smtp_host if row else None) or "",
            "smtp_port": row.smtp_port if row and row.smtp_port else 587,
            "smtp_user": (row.smtp_user if row else None) or "",
            "smtp_password_set": bool(row and row.smtp_password),
            "smtp_from": (row.smtp_from if row else None) or "",
            "email_to": (row.email_to if row else None) or "",
            "telegram_bot_token_set": bool(row and row.telegram_bot_token),
            "telegram_chat_ids": (row.telegram_chat_ids if row else None) or "",
            "telegram_configured": telegram_configured(cfg) or env_tg,
            "email_configured": email_configured(cfg) or env_email,
            "alerts_enabled": is_alerts_enabled(),
            "using_env_fallback": not bool(row),
        }

    async def save_notify_config(self, user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        row = await self._notify_row(user_id)
        if not row:
            row = AlertNotifyConfig(user_id=user_id)
            self.db.add(row)

        for key in ("smtp_host", "smtp_user", "smtp_from", "email_to", "telegram_chat_ids"):
            if key in payload and payload[key] is not None:
                setattr(row, key, str(payload[key]).strip() or None)

        if "smtp_port" in payload and payload["smtp_port"] is not None:
            try:
                row.smtp_port = int(payload["smtp_port"])
            except (TypeError, ValueError):
                pass

        pwd = payload.get("smtp_password")
        if pwd:
            row.smtp_password = str(pwd)
        tok = payload.get("telegram_bot_token")
        if tok:
            row.telegram_bot_token = str(tok)

        row.updated_at = datetime.utcnow()
        await self.db.commit()
        return await self.get_notify_config(user_id)

    async def _notify_row(self, user_id: int) -> AlertNotifyConfig | None:
        result = await self.db.execute(
            select(AlertNotifyConfig).where(AlertNotifyConfig.user_id == user_id)
        )
        return result.scalar_one_or_none()

    def _notify_cfg_obj(self, row: AlertNotifyConfig | None) -> NotifyConfig | None:
        if not row:
            return None
        return NotifyConfig(
            smtp_host=row.smtp_host,
            smtp_port=row.smtp_port,
            smtp_user=row.smtp_user,
            smtp_password=row.smtp_password,
            smtp_from=row.smtp_from,
            email_to=row.email_to,
            telegram_bot_token=row.telegram_bot_token,
            telegram_chat_ids=row.telegram_chat_ids,
        )

    # ── schedules CRUD ────────────────────────────────────────────────────

    async def list_schedules(self, user_id: int) -> list[dict[str, Any]]:
        result = await self.db.execute(
            select(AlertSchedule).where(AlertSchedule.user_id == user_id).order_by(AlertSchedule.id.desc())
        )
        return [self._schedule_dict(s) for s in result.scalars().all()]

    async def create_schedule(self, user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload["name"]).strip()
        existing = await self.db.execute(
            select(AlertSchedule).where(AlertSchedule.user_id == user_id, AlertSchedule.name == name)
        )
        if existing.scalar_one_or_none():
            raise ValueError(f"Schedule named '{name}' already exists")

        sched = AlertSchedule(
            user_id=user_id,
            name=name,
            market=payload.get("market") or "india",
            tickers_json=json.dumps([t.upper() for t in payload.get("tickers") or []]),
            timeframes_json=json.dumps(list(payload.get("timeframes") or [])),
            strategies_json=json.dumps(list(payload.get("strategies") or [])),
            schedule_mode=payload.get("schedule_mode") or "interval",
            poll_minutes=int(payload.get("poll_minutes") or 15),
            daily_time=payload.get("daily_time"),
            notify_telegram=bool(payload.get("notify_telegram", True)),
            notify_email=bool(payload.get("notify_email", False)),
            enabled=bool(payload.get("enabled", False)),
        )
        self.db.add(sched)
        await self.db.commit()
        await self.db.refresh(sched)
        return self._schedule_dict(sched)

    async def update_schedule(self, user_id: int, schedule_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
        sched = await self._get(user_id, schedule_id)
        if not sched:
            return None
        if "name" in payload and payload["name"]:
            sched.name = str(payload["name"]).strip()
        if "tickers" in payload and payload["tickers"] is not None:
            sched.tickers_json = json.dumps([str(t).upper() for t in payload["tickers"]])
        if "timeframes" in payload and payload["timeframes"] is not None:
            sched.timeframes_json = json.dumps(list(payload["timeframes"]))
        if "strategies" in payload and payload["strategies"] is not None:
            sched.strategies_json = json.dumps(list(payload["strategies"]))
        if "schedule_mode" in payload and payload["schedule_mode"]:
            sched.schedule_mode = payload["schedule_mode"]
        if "poll_minutes" in payload and payload["poll_minutes"] is not None:
            sched.poll_minutes = int(payload["poll_minutes"])
        if "daily_time" in payload:
            sched.daily_time = payload["daily_time"]
        if "notify_telegram" in payload and payload["notify_telegram"] is not None:
            sched.notify_telegram = bool(payload["notify_telegram"])
        if "notify_email" in payload and payload["notify_email"] is not None:
            sched.notify_email = bool(payload["notify_email"])
        if "enabled" in payload and payload["enabled"] is not None:
            sched.enabled = bool(payload["enabled"])
        await self.db.commit()
        await self.db.refresh(sched)
        return self._schedule_dict(sched)

    async def delete_schedule(self, user_id: int, schedule_id: int) -> bool:
        sched = await self._get(user_id, schedule_id)
        if not sched:
            return False
        await self.db.delete(sched)
        await self.db.commit()
        return True

    async def set_enabled(self, user_id: int, schedule_id: int, enabled: bool) -> bool:
        sched = await self._get(user_id, schedule_id)
        if not sched:
            return False
        sched.enabled = enabled
        await self.db.commit()
        return True

    async def _get(self, user_id: int, schedule_id: int) -> AlertSchedule | None:
        result = await self.db.execute(
            select(AlertSchedule).where(AlertSchedule.id == schedule_id, AlertSchedule.user_id == user_id)
        )
        return result.scalar_one_or_none()

    # ── hits ──────────────────────────────────────────────────────────────

    async def list_hits(self, user_id: int, *, limit: int = 100, schedule_id: int | None = None) -> list[dict[str, Any]]:
        q = select(AlertScheduleHit).where(AlertScheduleHit.user_id == user_id)
        if schedule_id is not None:
            q = q.where(AlertScheduleHit.schedule_id == schedule_id)
        q = q.order_by(AlertScheduleHit.id.desc()).limit(limit)
        result = await self.db.execute(q)
        out = []
        for h in result.scalars().all():
            out.append({
                "id": h.id,
                "schedule_id": h.schedule_id,
                "schedule_name": h.schedule_name,
                "strategy_name": h.strategy_name,
                "ticker": h.ticker,
                "timeframe": h.timeframe,
                "market": h.market,
                "verdict": h.verdict,
                "reasons": json.loads(h.reasons_json or "[]"),
                "bar_asof": h.bar_asof,
                "notified_telegram": h.notified_telegram,
                "notified_email": h.notified_email,
                "created_at": h.created_at.isoformat() if h.created_at else None,
            })
        return out

    async def delete_hit(self, user_id: int, hit_id: int) -> bool:
        result = await self.db.execute(
            select(AlertScheduleHit).where(
                AlertScheduleHit.id == hit_id,
                AlertScheduleHit.user_id == user_id,
            )
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
            delete(AlertScheduleHit).where(
                AlertScheduleHit.user_id == user_id,
                AlertScheduleHit.id.in_(ids),
            )
        )
        await self.db.commit()
        return int(result.rowcount or 0)

    async def delete_all_hits(self, user_id: int, *, schedule_id: int | None = None) -> int:
        q = delete(AlertScheduleHit).where(AlertScheduleHit.user_id == user_id)
        if schedule_id is not None:
            q = q.where(AlertScheduleHit.schedule_id == schedule_id)
        result = await self.db.execute(q)
        await self.db.commit()
        return int(result.rowcount or 0)

    # ── run ───────────────────────────────────────────────────────────────

    async def run_schedule(self, user_id: int, schedule_id: int, *, force: bool = True) -> dict[str, Any]:
        sched = await self._get(user_id, schedule_id)
        if not sched:
            return {"error": "Schedule not found"}
        if not force and not schedule_is_due(sched):
            return {"skipped": True, "message": "Not due yet", "schedule_id": schedule_id}
        return await self._execute_schedule(sched)

    async def run_due_for_user(self, user_id: int) -> dict[str, Any]:
        result = await self.db.execute(
            select(AlertSchedule).where(AlertSchedule.user_id == user_id, AlertSchedule.enabled == True)  # noqa: E712
        )
        ran = []
        for sched in result.scalars().all():
            if schedule_is_due(sched):
                ran.append(await self._execute_schedule(sched))
        return {"ran": len(ran), "results": ran}

    async def _execute_schedule(self, sched: AlertSchedule) -> dict[str, Any]:
        tickers = _parse_json_list(sched.tickers_json)
        timeframes = _parse_json_list(sched.timeframes_json)
        strategies = _parse_json_list(sched.strategies_json)
        market = (sched.market or "india").lower()
        if market not in ("india", "us", "crypto"):
            market = "india"

        if not tickers or not timeframes or not strategies:
            sched.last_run_at = datetime.utcnow()
            sched.last_status = "Invalid config (empty tickers/TFs/strategies)"
            await self.db.commit()
            return {"schedule_id": sched.id, "error": sched.last_status}

        buckets = self._bucket_strategies(strategies)
        scanner_ids = self._resolve_scanner_strategies(buckets["scanner"])
        hub_ids = [sid for sid in buckets["hub"] if get_hub_section(sid)]
        ta_ids = [sid for sid in buckets["ta"] if any(s["id"] == sid for s in TA_SCREENERS)]
        skipped = list(buckets["skipped"])
        for sid in buckets["hub"]:
            if sid not in hub_ids:
                skipped.append(f"hub:{sid}")
        for sid in buckets["ta"]:
            if sid not in ta_ids:
                skipped.append(f"ta:{sid}")

        if not scanner_ids and not hub_ids and not ta_ids:
            sched.last_run_at = datetime.utcnow()
            sched.last_status = (
                "No runnable strategies — pick Scanner / Trading Hubs / Technical Analysis. "
                f"Skipped catalog-only: {skipped[:6] or strategies[:5]}"
            )[:240]
            await self.db.commit()
            return {"schedule_id": sched.id, "error": sched.last_status}

        notify_row = await self._notify_row(sched.user_id)
        cfg = self._notify_cfg_obj(notify_row)

        hits_created = 0
        notified = 0
        buy_n = sell_n = 0
        signals_n = 0
        scan_tfs: list[str] = []
        errors: list[str] = []

        # ── Scanner ──────────────────────────────────────────────────────
        if scanner_ids:
            scan_tfs = self._effective_scan_timeframes(scanner_ids, timeframes)
            if not scan_tfs:
                errors.append("scanner: no matching TFs")
            else:
                try:
                    signals = await ScannerService(self.settings).scan(
                        ScanRequest(
                            tickers=tickers,
                            strategies=scanner_ids,
                            timeframes=scan_tfs,
                            asset_class=market,  # type: ignore[arg-type]
                        )
                    )
                    signals_n += len(signals)
                    for sig in signals:
                        action = getattr(sig, "action", None)
                        if action not in ("BUY", "SELL"):
                            continue
                        if action == "BUY":
                            buy_n += 1
                        else:
                            sell_n += 1
                        created, note = await self._persist_hit(
                            sched,
                            market=market,
                            strategy_name=getattr(sig, "strategy_label", None) or sig.strategy,
                            strategy_id=f"scanner:{sig.strategy}",
                            ticker=sig.ticker,
                            timeframe=sig.timeframe,
                            verdict=action,
                            reasons=[getattr(sig, "rationale", "") or f"{action} · conf {sig.confidence_pct}%"],
                            bar_asof=str(getattr(sig, "timestamp", "") or ""),
                            payload={
                                "strategy_id": sig.strategy,
                                "confidence_pct": sig.confidence_pct,
                                "price": sig.price,
                                "sl_pct": sig.sl_pct,
                                "tp_pct": sig.tp_pct,
                            },
                            price=float(sig.price) if sig.price else None,
                            cfg=cfg,
                        )
                        hits_created += created
                        notified += note
                except Exception as exc:
                    logger.exception("Schedule %s scanner failed", sched.id)
                    errors.append(f"scanner: {exc}")

        # ── Trading Hubs ─────────────────────────────────────────────────
        if hub_ids:
            hub_svc = TradingHubService(self.settings)
            for hid in hub_ids:
                try:
                    payload = await hub_svc.scan(hid, tickers, asset_class=market)
                    rows = payload.get("results") or []
                    signals_n += len(rows)
                    section = get_hub_section(hid) or {}
                    label = section.get("label") or hid
                    for row in rows:
                        if row.get("error"):
                            continue
                        live = row.get("live") if isinstance(row.get("live"), dict) else row
                        if not self._hub_row_actionable(live):
                            continue
                        verdict = self._normalize_verdict(live)
                        if verdict not in ("BUY", "SELL"):
                            continue
                        if verdict == "BUY":
                            buy_n += 1
                        else:
                            sell_n += 1
                        tf = str(live.get("timeframe") or (timeframes[0] if timeframes else "15m"))
                        ticker = str(row.get("ticker") or live.get("ticker") or "")
                        reasons = live.get("reasons") or [str(live.get("verdict") or verdict)]
                        if isinstance(reasons, str):
                            reasons = [reasons]
                        created, note = await self._persist_hit(
                            sched,
                            market=market,
                            strategy_name=label,
                            strategy_id=f"hub:{hid}",
                            ticker=ticker,
                            timeframe=tf,
                            verdict=verdict,
                            reasons=[str(r) for r in reasons[:6]],
                            bar_asof=str(live.get("bar_time") or live.get("asof") or ""),
                            payload={"hub": hid, "live": {k: live.get(k) for k in ("phase", "signal", "verdict", "take_trade")}},
                            price=_safe_float(live.get("close") or live.get("price")),
                            cfg=cfg,
                        )
                        hits_created += created
                        notified += note
                except Exception as exc:
                    logger.exception("Schedule %s hub %s failed", sched.id, hid)
                    errors.append(f"hub:{hid}: {exc}")

        # ── Technical Analysis ───────────────────────────────────────────
        if ta_ids:
            ta_svc = TaScreenerService(self.settings)
            default_tf = timeframes[0] if timeframes else None
            for tid in ta_ids:
                try:
                    payload = await ta_svc.run(
                        tid, tickers, timeframe=default_tf, asset_class=market,
                    )
                    rows = payload.get("results") or []
                    signals_n += len(rows)
                    label = payload.get("label") or tid
                    tf = str(payload.get("timeframe") or default_tf or "15m")
                    for row in rows:
                        if not is_actionable_result(row):
                            continue
                        verdict = self._normalize_verdict(row)
                        if verdict not in ("BUY", "SELL"):
                            # keep WATCH/TAKE as BUY-ish notify candidates when take_trade
                            if row.get("take_trade") or str(row.get("verdict", "")).upper().startswith("TAKE"):
                                verdict = "BUY" if "SHORT" not in str(row.get("verdict", "")).upper() else "SELL"
                            else:
                                continue
                        if verdict == "BUY":
                            buy_n += 1
                        else:
                            sell_n += 1
                        ticker = str(row.get("ticker") or "")
                        reasons = [str(row.get("summary") or row.get("verdict") or verdict)]
                        created, note = await self._persist_hit(
                            sched,
                            market=market,
                            strategy_name=label,
                            strategy_id=f"ta:{tid}",
                            ticker=ticker,
                            timeframe=tf,
                            verdict=verdict,
                            reasons=reasons,
                            bar_asof=str(row.get("bar_time") or row.get("asof") or ""),
                            payload={"ta": tid, "verdict": row.get("verdict"), "phase": row.get("phase")},
                            price=_safe_float(row.get("close") or row.get("price")),
                            cfg=cfg,
                        )
                        hits_created += created
                        notified += note
                except Exception as exc:
                    logger.exception("Schedule %s ta %s failed", sched.id, tid)
                    errors.append(f"ta:{tid}: {exc}")

        parts = [
            f"OK · {signals_n} scanned",
            f"BUY {buy_n}",
            f"SELL {sell_n}",
            f"{hits_created} hits",
            f"{notified} notified",
        ]
        if scanner_ids:
            parts.append(f"scanner {len(scanner_ids)}")
        if hub_ids:
            parts.append(f"hub {len(hub_ids)}")
        if ta_ids:
            parts.append(f"ta {len(ta_ids)}")
        if scan_tfs:
            parts.append(f"TFs {','.join(scan_tfs)}")
        if skipped:
            parts.append(f"skipped {len(skipped)} catalog-only")
        if errors:
            parts.append(f"errors {len(errors)}")

        sched.last_run_at = datetime.utcnow()
        sched.last_status = " · ".join(parts)[:240]
        await self.db.commit()
        return json_safe({
            "schedule_id": sched.id,
            "name": sched.name,
            "scanner": scanner_ids,
            "hubs": hub_ids,
            "ta": ta_ids,
            "skipped": skipped[:20],
            "timeframes_used": scan_tfs,
            "signals": signals_n,
            "buy": buy_n,
            "sell": sell_n,
            "hits_created": hits_created,
            "notified": notified,
            "errors": errors[:10],
            "status": sched.last_status,
        })

    async def _persist_hit(
        self,
        sched: AlertSchedule,
        *,
        market: str,
        strategy_name: str,
        strategy_id: str,
        ticker: str,
        timeframe: str,
        verdict: str,
        reasons: list[str],
        bar_asof: str,
        payload: dict[str, Any],
        price: float | None,
        cfg: NotifyConfig | None,
    ) -> tuple[int, int]:
        """Insert hit + optional notify. Returns (hits_created, notified)."""
        if not ticker:
            return 0, 0
        dedupe = f"{sched.id}|{ticker}|{timeframe}|{strategy_id}|{verdict}|{bar_asof}"
        exists = await self.db.execute(
            select(AlertScheduleHit).where(AlertScheduleHit.dedupe_key == dedupe)
        )
        if exists.scalar_one_or_none():
            return 0, 0

        tg_ok = email_ok = False
        notified = 0
        if is_alerts_enabled() and (sched.notify_telegram or sched.notify_email):
            send_res = send_trade_setup_alert(
                ticker=ticker,
                timeframe=timeframe,
                strategy=strategy_name,
                market=market,
                signal=verdict,
                close=price,
                bar_time=bar_asof,
                monitor_name=sched.name,
                via_telegram=sched.notify_telegram,
                via_email=sched.notify_email,
                reasons=reasons,
                cfg=cfg,
            )
            tg = send_res.get("telegram")
            em = send_res.get("email")
            tg_ok = bool(tg and tg[0])
            email_ok = bool(em and em[0])
            if tg_ok or email_ok:
                notified = 1

        self.db.add(AlertScheduleHit(
            schedule_id=sched.id,
            user_id=sched.user_id,
            schedule_name=sched.name,
            strategy_name=strategy_name,
            ticker=ticker,
            timeframe=timeframe,
            market=market,
            verdict=verdict,
            reasons_json=json.dumps(reasons),
            payload_json=json.dumps(payload),
            bar_asof=bar_asof,
            dedupe_key=dedupe,
            notified_telegram=tg_ok,
            notified_email=email_ok,
        ))
        return 1, notified

    @staticmethod
    def _bucket_strategies(raw: list[str]) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {
            "scanner": [], "hub": [], "ta": [], "skipped": [],
        }
        seen: set[str] = set()
        for item in raw:
            prefix, sid = parse_strategy_ref(item)
            if not sid:
                continue
            key = f"{prefix}:{sid}"
            if key in seen:
                continue
            seen.add(key)
            if prefix == "scanner":
                out["scanner"].append(sid)
            elif prefix == "hub":
                out["hub"].append(sid)
            elif prefix == "ta":
                out["ta"].append(sid)
            else:
                out["skipped"].append(key if prefix else sid)
        return out

    @staticmethod
    def _hub_row_actionable(live: dict[str, Any] | None) -> bool:
        if not live or not isinstance(live, dict):
            return False
        if live.get("take_trade") or live.get("actionable"):
            return True
        if is_actionable_result(live):
            return True
        sig = str(live.get("signal") or "").upper()
        return sig in ("BUY", "SELL", "LONG", "SHORT")

    @staticmethod
    def _normalize_verdict(row: dict[str, Any]) -> str:
        sig = str(row.get("signal") or "").upper()
        if sig in ("BUY", "LONG", "1"):
            return "BUY"
        if sig in ("SELL", "SHORT", "-1"):
            return "SELL"
        v = str(row.get("verdict") or "").upper()
        if "SHORT" in v or v == "SELL":
            return "SELL"
        if v in ("BUY", "STRONG BUY") or v.startswith("TAKE") or "LONG" in v:
            return "BUY"
        return ""

    @staticmethod
    def _resolve_scanner_strategies(raw: list[str]) -> list[str]:
        """Map saved ids/names to STRATEGY_META keys (Scanner-runnable only)."""
        by_name = {meta["name"].strip().lower(): sid for sid, meta in STRATEGY_META.items()}
        by_id_lower = {sid.lower(): sid for sid in STRATEGY_META}
        out: list[str] = []
        seen: set[str] = set()
        for item in raw:
            s = (item or "").strip()
            if not s:
                continue
            # strip optional scanner: prefix
            if s.lower().startswith("scanner:"):
                s = s.split(":", 1)[1].strip()
            sid = None
            if s in STRATEGY_META:
                sid = s
            elif s.lower() in by_id_lower:
                sid = by_id_lower[s.lower()]
            elif s.lower() in by_name:
                sid = by_name[s.lower()]
            else:
                slug = s.lower().replace(" ", "_").replace("-", "_")
                if slug in STRATEGY_META:
                    sid = slug
            if sid and sid not in seen:
                seen.add(sid)
                out.append(sid)
        return out

    @staticmethod
    def _normalize_scan_timeframes(raw: list[str]) -> list[str]:
        """Map UI timeframes onto Scanner category TFs."""
        alias = {
            "1m": "1m",
            "3m": "3m",
            "5m": "5m",
            "15m": "15m",
            "30m": "15m",
            "1h": "15m",
            "4h": "15m",
            "1d": "1d",
            "1w": "1d",
        }
        out: list[str] = []
        seen: set[str] = set()
        for tf in raw:
            mapped = alias.get((tf or "").strip().lower())
            if mapped and mapped not in seen:
                seen.add(mapped)
                out.append(mapped)
        return out

    @classmethod
    def _effective_scan_timeframes(cls, strategies: list[str], raw_tfs: list[str]) -> list[str]:
        """Ensure each strategy has at least one TF in its Scanner category."""
        requested = cls._normalize_scan_timeframes(raw_tfs)
        out: list[str] = []
        seen: set[str] = set()
        for sid in strategies:
            meta = STRATEGY_META.get(sid) or {}
            cat = meta.get("category")
            allowed = list((STRATEGY_CATEGORIES.get(cat) or {}).get("timeframes") or meta.get("timeframes") or [])
            overlap = [tf for tf in requested if tf in allowed]
            pick = overlap if overlap else allowed[:1]
            for tf in pick:
                if tf not in seen:
                    seen.add(tf)
                    out.append(tf)
        return out

    @staticmethod
    def _schedule_dict(s: AlertSchedule) -> dict[str, Any]:
        return {
            "id": s.id,
            "name": s.name,
            "market": s.market,
            "tickers": _parse_json_list(s.tickers_json),
            "timeframes": _parse_json_list(s.timeframes_json),
            "strategies": _parse_json_list(s.strategies_json),
            "schedule_mode": s.schedule_mode,
            "poll_minutes": s.poll_minutes,
            "daily_time": s.daily_time,
            "notify_telegram": s.notify_telegram,
            "notify_email": s.notify_email,
            "enabled": s.enabled,
            "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
            "last_status": s.last_status,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
