"""Pro Trade — Volume Profile CE and related professional setups."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.market_pulse.serialize import json_safe
from app.services.settings_service import SettingsService
from app.services.ticker_universe_service import TickerUniverseService

BTST_SOURCE = "btst"


class ProTradeService:
    def __init__(self, settings: SettingsService, db: Any = None):
        self.settings = settings
        self.universe = TickerUniverseService()
        self.db = db

    async def _ctx(self) -> tuple[str, str]:
        token = await self.settings.get_groww_token() or ""
        exchange = await self.settings.get_groww_exchange()
        return token, exchange

    async def _asset_ctx(self, asset_class: str) -> tuple[str, str]:
        from app.market_pulse.asset_class_config import ASSET_CLASS_CONFIG

        cfg = ASSET_CLASS_CONFIG.get(asset_class) or ASSET_CLASS_CONFIG["india"]
        if asset_class == "india":
            return str(cfg["market"]), await self.settings.get_groww_exchange()
        return str(cfg["market"]), str(cfg.get("exchange") or "NSE")

    async def sections(self) -> dict[str, Any]:
        return {
            "sections": [
                {
                    "id": "volume_profile_ce",
                    "label": "Volume Profile CE",
                    "path": "/pro-trade/volume-profile-ce",
                    "youtube": "https://youtu.be/67u8mdQ8f08",
                },
                {
                    "id": "volume_profile_poc",
                    "label": "Volume Profile POC",
                    "path": "/pro-trade/volume-profile-poc",
                    "youtube": "https://www.youtube.com/watch?v=ooHX6tf5RVI",
                },
                {
                    "id": "pa_volume_profile",
                    "label": "PA - Volume Profile",
                    "path": "/pro-trade/pa-volume-profile",
                    "youtube": "https://www.youtube.com/watch?v=FVoXWlNkdhs",
                },
                {
                    "id": "pa_vp_smc",
                    "label": "PA-VP-SMC",
                    "path": "/pro-trade/pa-vp-smc",
                    "youtube": None,
                },
                {
                    "id": "volume_spread_next_candle",
                    "label": "Volume Spread - Next Candle",
                    "path": "/pro-trade/volume-spread-next-candle",
                    "youtube": "https://www.youtube.com/watch?v=ncrqXFCQKOU&list=PLXWi52aRZnNF_HW-TedxAE1Tyx1C8XrGn",
                },
                {
                    "id": "elliott_wave",
                    "label": "Elliott Wave",
                    "path": "/pro-trade/elliott-wave",
                    "youtube": None,
                },
                {
                    "id": "bb_mean_reversion",
                    "label": "BB Mean Reversion",
                    "path": "/pro-trade/bb-mean-reversion",
                    "youtube": None,
                },
                {
                    "id": "btst",
                    "label": "Buy Today Sell Tomorrow",
                    "path": "/pro-trade/btst",
                    "youtube": None,
                },
            ],
        }

    async def volume_profile_ce(
        self,
        tickers: list[str],
        *,
        asset_class: str = "india",
        exchange: str | None = None,
        cfg_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.ticker_utils import market_currency
        from app.market_pulse.volume_profile_ce_engine import (
            VOLUME_PROFILE_CE_AI_SYSTEM,
            VolumeProfileCeConfig,
            build_volume_profile_ce_ai_prompt,
            scan_universe,
        )

        if not tickers:
            return {"error": "Select at least one ticker", "results": [], "entry_count": 0}

        market, default_exchange = await self._asset_ctx(asset_class)
        token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, tickers)
        cfg = VolumeProfileCeConfig(**(cfg_overrides or {}))
        resolved_exchange = exchange or default_exchange

        def _run():
            return scan_universe(
                resolved,
                market,
                cfg=cfg,
                groww_token=token,
                exchange=resolved_exchange,
            )

        payload = await asyncio.to_thread(_run)
        payload["asset_class"] = asset_class
        payload["market"] = market
        payload["currency"] = market_currency(market)
        for r in payload.get("results", []):
            r["ai_context"] = build_volume_profile_ce_ai_prompt(r)
        payload["ai_system_prompt"] = VOLUME_PROFILE_CE_AI_SYSTEM
        return json_safe(payload)

    async def volume_profile_poc(
        self,
        tickers: list[str],
        *,
        asset_class: str = "india",
        exchange: str | None = None,
        cfg_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.ticker_utils import market_currency
        from app.market_pulse.volume_profile_poc_engine import (
            VOLUME_PROFILE_POC_AI_SYSTEM,
            VolumeProfilePocConfig,
            build_volume_profile_poc_ai_prompt,
            scan_universe,
        )

        if not tickers:
            return {"error": "Select at least one ticker", "results": [], "entry_count": 0}

        market, default_exchange = await self._asset_ctx(asset_class)
        token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, tickers)
        cfg = VolumeProfilePocConfig(**(cfg_overrides or {}))
        resolved_exchange = exchange or default_exchange

        def _run():
            return scan_universe(
                resolved,
                market,
                cfg=cfg,
                groww_token=token,
                exchange=resolved_exchange,
            )

        payload = await asyncio.to_thread(_run)
        payload["asset_class"] = asset_class
        payload["market"] = market
        payload["currency"] = market_currency(market)
        for r in payload.get("results", []):
            r["ai_context"] = build_volume_profile_poc_ai_prompt(r)
        payload["ai_system_prompt"] = VOLUME_PROFILE_POC_AI_SYSTEM
        return json_safe(payload)

    async def pa_vp_smc(
        self,
        tickers: list[str],
        *,
        asset_class: str = "india",
        exchange: str | None = None,
        cfg_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.pa_vp_smc_engine import (
            PA_VP_SMC_AI_SYSTEM,
            PaVpSmcConfig,
            build_pa_vp_smc_ai_prompt,
            scan_universe,
        )
        from app.market_pulse.ticker_utils import market_currency

        if not tickers:
            return {"error": "Select at least one ticker", "results": [], "entry_count": 0}

        market, default_exchange = await self._asset_ctx(asset_class)
        token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, tickers)
        cfg = PaVpSmcConfig(**(cfg_overrides or {}))
        resolved_exchange = exchange or default_exchange

        def _run():
            return scan_universe(
                resolved,
                market,
                cfg=cfg,
                groww_token=token,
                exchange=resolved_exchange,
            )

        payload = await asyncio.to_thread(_run)
        payload["asset_class"] = asset_class
        payload["market"] = market
        payload["currency"] = market_currency(market)
        for r in payload.get("results", []):
            r["ai_context"] = build_pa_vp_smc_ai_prompt(r)
        payload["ai_system_prompt"] = PA_VP_SMC_AI_SYSTEM
        return json_safe(payload)

    async def pa_volume_profile(
        self,
        tickers: list[str],
        *,
        asset_class: str = "india",
        exchange: str | None = None,
        cfg_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.pa_volume_profile_engine import (
            PA_VOLUME_PROFILE_AI_SYSTEM,
            PaVolumeProfileConfig,
            build_pa_volume_profile_ai_prompt,
            scan_universe,
        )
        from app.market_pulse.ticker_utils import market_currency

        if not tickers:
            return {"error": "Select at least one ticker", "results": [], "entry_count": 0}

        market, default_exchange = await self._asset_ctx(asset_class)
        token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, tickers)
        cfg = PaVolumeProfileConfig(**(cfg_overrides or {}))
        resolved_exchange = exchange or default_exchange

        def _run():
            return scan_universe(
                resolved,
                market,
                cfg=cfg,
                groww_token=token,
                exchange=resolved_exchange,
            )

        payload = await asyncio.to_thread(_run)
        payload["asset_class"] = asset_class
        payload["market"] = market
        payload["currency"] = market_currency(market)
        for r in payload.get("results", []):
            r["ai_context"] = build_pa_volume_profile_ai_prompt(r)
        payload["ai_system_prompt"] = PA_VOLUME_PROFILE_AI_SYSTEM
        return json_safe(payload)

    async def elliott_wave(
        self,
        tickers: list[str],
        *,
        asset_class: str = "india",
        exchange: str | None = None,
        cfg_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.elliott_wave_engine import (
            ELLIOTT_WAVE_AI_SYSTEM,
            ElliottWaveConfig,
            build_elliott_wave_ai_prompt,
            scan_universe,
        )
        from app.market_pulse.ticker_utils import market_currency

        if not tickers:
            return {"error": "Select at least one ticker", "results": [], "entry_count": 0}

        market, default_exchange = await self._asset_ctx(asset_class)
        token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, tickers)
        cfg = ElliottWaveConfig(**(cfg_overrides or {}))
        resolved_exchange = exchange or default_exchange

        def _run():
            return scan_universe(
                resolved,
                market,
                cfg=cfg,
                groww_token=token,
                exchange=resolved_exchange,
            )

        payload = await asyncio.to_thread(_run)
        payload["asset_class"] = asset_class
        payload["market"] = market
        payload["currency"] = market_currency(market)
        for r in payload.get("results", []):
            r["ai_context"] = build_elliott_wave_ai_prompt(r)
        payload["ai_system_prompt"] = ELLIOTT_WAVE_AI_SYSTEM
        return json_safe(payload)

    async def bb_mean_reversion(
        self,
        tickers: list[str],
        *,
        asset_class: str = "india",
        exchange: str | None = None,
        timeframes: list[str] | None = None,
        cfg_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.bb_mean_reversion_engine import (
            BB_MEAN_REVERSION_AI_SYSTEM,
            BbMeanReversionConfig,
            build_bb_mean_reversion_ai_prompt,
            scan_universe,
        )
        from app.market_pulse.ticker_utils import market_currency

        if not tickers:
            return {"error": "Select at least one ticker", "results": [], "entry_count": 0}
        if not timeframes:
            return {"error": "Select at least one timeframe", "results": [], "entry_count": 0}

        market, default_exchange = await self._asset_ctx(asset_class)
        token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, tickers)
        cfg_base = BbMeanReversionConfig(**(cfg_overrides or {}))
        resolved_exchange = exchange or default_exchange

        def _run():
            return scan_universe(
                resolved,
                timeframes,
                market,
                cfg_base=cfg_base,
                groww_token=token,
                exchange=resolved_exchange,
            )

        payload = await asyncio.to_thread(_run)
        payload["asset_class"] = asset_class
        payload["market"] = market
        payload["currency"] = market_currency(market)
        for r in payload.get("results", []):
            r["ai_context"] = build_bb_mean_reversion_ai_prompt(r)
        payload["ai_system_prompt"] = BB_MEAN_REVERSION_AI_SYSTEM
        return json_safe(payload)

    async def btst(
        self,
        tickers: list[str],
        *,
        asset_class: str = "india",
        exchange: str | None = None,
        cfg_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.btst_engine import (
            BTST_AI_SYSTEM,
            BtstConfig,
            build_btst_ai_prompt,
            scan_universe,
        )
        from app.market_pulse.ticker_utils import market_currency

        if not tickers:
            return {"error": "Select at least one ticker", "results": [], "entry_count": 0}

        market, default_exchange = await self._asset_ctx(asset_class)
        token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, tickers)
        cfg = BtstConfig(**(cfg_overrides or {}))
        resolved_exchange = exchange or default_exchange

        def _run():
            return scan_universe(resolved, market, cfg=cfg, groww_token=token, exchange=resolved_exchange)

        payload = await asyncio.to_thread(_run)
        payload["asset_class"] = asset_class
        payload["market"] = market
        payload["currency"] = market_currency(market)
        for r in payload.get("results", []):
            r["ai_context"] = build_btst_ai_prompt(r)
        payload["ai_system_prompt"] = BTST_AI_SYSTEM
        return json_safe(payload)

    # ------------------------------------------------------------------
    # Saved BTST/STBT reports — shares the SavedBacktestReport table
    # (source="btst") with the other background-job features.
    # ------------------------------------------------------------------

    @staticmethod
    def _btst_summary(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "entry_count": payload.get("entry_count"),
            "btst_count": payload.get("btst_count"),
            "stbt_count": payload.get("stbt_count"),
            "scanned": payload.get("scanned"),
        }

    async def save_btst_report(
        self, name: str, tickers: list[str], asset_class: str, payload: dict[str, Any], *, user_id: int | None,
    ) -> dict[str, Any]:
        from datetime import datetime as datetime_cls

        from app.models.db_models import SavedBacktestReport

        if self.db is None:
            return {"error": "No database session available."}
        report = SavedBacktestReport(
            user_id=user_id,
            name=name.strip()[:200] or f"BTST {datetime_cls.utcnow().isoformat()}",
            asset_class=asset_class,
            tickers=",".join(tickers or []),
            timeframes="",
            payload_json=json.dumps(json_safe(payload)),
            source=BTST_SOURCE,
        )
        self.db.add(report)
        await self.db.commit()
        await self.db.refresh(report)
        return {"id": report.id, "name": report.name, "created_at": report.created_at.isoformat()}

    async def list_btst_reports(self, *, user_id: int | None) -> dict[str, Any]:
        from sqlalchemy import select

        from app.models.db_models import SavedBacktestReport

        if self.db is None:
            return {"reports": []}
        stmt = select(SavedBacktestReport).where(
            SavedBacktestReport.source == BTST_SOURCE
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
                "summary": self._btst_summary(payload if isinstance(payload, dict) else {}),
            })
        return {"reports": reports}

    async def get_btst_report(self, report_id: int, *, user_id: int | None) -> dict[str, Any]:
        from app.models.db_models import SavedBacktestReport

        if self.db is None:
            return {"error": "No database session available."}
        report = await self.db.get(SavedBacktestReport, report_id)
        if not report or report.source != BTST_SOURCE or (user_id is not None and report.user_id not in (None, user_id)):
            return {"error": "Report not found."}
        return {
            "id": report.id, "name": report.name, "created_at": report.created_at.isoformat(),
            "payload": json.loads(report.payload_json),
        }

    async def delete_btst_report(self, report_id: int, *, user_id: int | None) -> dict[str, Any]:
        from app.models.db_models import SavedBacktestReport

        if self.db is None:
            return {"error": "No database session available."}
        report = await self.db.get(SavedBacktestReport, report_id)
        if not report or report.source != BTST_SOURCE or (user_id is not None and report.user_id not in (None, user_id)):
            return {"error": "Report not found."}
        await self.db.delete(report)
        await self.db.commit()
        return {"deleted": True}

    async def volume_spread_next_candle(
        self,
        tickers: list[str],
        *,
        asset_class: str = "india",
        exchange: str | None = None,
        cfg_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.ticker_utils import market_currency
        from app.market_pulse.volume_spread_next_candle_engine import (
            VOLUME_SPREAD_NEXT_CANDLE_AI_SYSTEM,
            VolumeSpreadConfig,
            build_volume_spread_next_candle_ai_prompt,
            scan_universe,
        )

        if not tickers:
            return {"error": "Select at least one ticker", "results": [], "entry_count": 0}

        market, default_exchange = await self._asset_ctx(asset_class)
        token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, tickers)
        cfg = VolumeSpreadConfig(**(cfg_overrides or {}))
        resolved_exchange = exchange or default_exchange

        def _run():
            return scan_universe(
                resolved,
                market,
                cfg=cfg,
                groww_token=token,
                exchange=resolved_exchange,
            )

        payload = await asyncio.to_thread(_run)
        payload["asset_class"] = asset_class
        payload["market"] = market
        payload["currency"] = market_currency(market)
        for r in payload.get("results", []):
            r["ai_context"] = build_volume_spread_next_candle_ai_prompt(r)
        payload["ai_system_prompt"] = VOLUME_SPREAD_NEXT_CANDLE_AI_SYSTEM
        return json_safe(payload)
