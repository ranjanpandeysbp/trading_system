"""Options — Double Calendar (theta-positive income spread), Delta Neutral (Iron Condor / Iron Fly)."""

from __future__ import annotations

import asyncio
from typing import Any

from app.market_pulse.serialize import json_safe
from app.services.settings_service import SettingsService
from app.services.ticker_universe_service import TickerUniverseService


def _attach_ltp(results: list[dict[str, Any]], market: str, *, groww_token: str = "", exchange: str = "NSE") -> None:
    from app.market_pulse.live_price import get_last_traded_price

    for res in results:
        if not res.get("error"):
            res["ltp"] = get_last_traded_price(res["ticker"], market, groww_token=groww_token, exchange=exchange)


class OptionsService:
    def __init__(self, settings: SettingsService, db: Any | None = None):
        self.settings = settings
        self.db = db
        self.universe = TickerUniverseService()

    async def _ctx(self) -> tuple[str, str, str]:
        token, exchange = await self.settings.prepare_market_data()
        market = await self.settings.get_default_market()
        return market, token, exchange

    async def _asset_ctx(self, asset_class: str) -> tuple[str, str]:
        from app.market_pulse.asset_class_config import ASSET_CLASS_CONFIG

        cfg = ASSET_CLASS_CONFIG.get(asset_class) or ASSET_CLASS_CONFIG["india"]
        if asset_class == "india":
            return str(cfg["market"]), await self.settings.get_groww_exchange()
        return str(cfg["market"]), str(cfg.get("exchange") or "NSE")

    async def sections(self) -> dict[str, Any]:
        return {
            "sections": [
                {"id": "double_calendar", "label": "📅 Double Calendar — Theta-Positive Income Spread"},
                {"id": "delta_neutral", "label": "🎰 Delta Neutral — Iron Condor / Iron Fly"},
                {"id": "hedging", "label": "🛡️ Hedging — Non-Directional Delta-Neutral (Intraday)"},
                {"id": "gokul_chhabra", "label": "🎯 Gokul Chhabra — 3m VWAP · VWMA · SuperTrend ITM"},
                {"id": "zero_to_hero", "label": "🚀 Zero to Hero — Previous Day High/Low Option Buying"},
                {"id": "market_prediction", "label": "🔮 Market Prediction — Option Chain Bias"},
                {"id": "call_put_writing", "label": "✍️ Call Put Writing — OI Walls & Short Covering"},
            ],
        }

    # ------------------------------------------------------------------
    # Saved Options reports — SavedBacktestReport with source="options:{section}"
    # ------------------------------------------------------------------

    @staticmethod
    def report_source(section_id: str) -> str:
        return f"options:{section_id}"

    @staticmethod
    def _report_summary(section_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        results = payload.get("results")
        if isinstance(results, list):
            tickers = [
                str(r.get("ticker") or r.get("symbol") or "")
                for r in results[:8]
                if isinstance(r, dict)
            ]
            return {
                "section_id": section_id,
                "result_count": len(results),
                "tickers": [t for t in tickers if t],
                "asset_class": payload.get("asset_class"),
            }
        setups = payload.get("setups") or payload.get("signals") or payload.get("indices")
        if isinstance(setups, list):
            return {
                "section_id": section_id,
                "result_count": len(setups),
                "asset_class": payload.get("asset_class") or "india",
            }
        symbol = payload.get("symbol")
        bias = payload.get("bias") or payload.get("verdict") or payload.get("direction")
        return {
            "section_id": section_id,
            "symbol": symbol,
            "bias": bias,
            "result_count": 1 if symbol or bias else 0,
        }

    async def save_report(
        self,
        section_id: str,
        name: str,
        payload: dict[str, Any],
        *,
        user_id: int | None,
    ) -> dict[str, Any]:
        import json
        from datetime import datetime as datetime_cls

        from app.models.db_models import SavedBacktestReport

        if self.db is None:
            return {"error": "No database session available."}
        tickers: list[str] = []
        results = payload.get("results")
        if isinstance(results, list):
            tickers = [
                str(r.get("ticker") or r.get("symbol") or "")
                for r in results if isinstance(r, dict) and (r.get("ticker") or r.get("symbol"))
            ]
        elif payload.get("symbol"):
            tickers = [str(payload["symbol"])]
        report = SavedBacktestReport(
            user_id=user_id,
            name=name.strip()[:200] or f"Options {section_id} {datetime_cls.utcnow().isoformat()}",
            asset_class=str(payload.get("asset_class") or "india"),
            tickers=",".join(tickers[:50]),
            timeframes=section_id,
            payload_json=json.dumps(payload),
            source=self.report_source(section_id),
        )
        self.db.add(report)
        await self.db.commit()
        await self.db.refresh(report)
        return {"id": report.id, "name": report.name, "created_at": report.created_at.isoformat()}

    async def list_reports(self, section_id: str, *, user_id: int | None) -> dict[str, Any]:
        import json

        from sqlalchemy import select

        from app.models.db_models import SavedBacktestReport

        if self.db is None:
            return {"reports": []}
        source = self.report_source(section_id)
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
                "summary": self._report_summary(
                    section_id, payload if isinstance(payload, dict) else {},
                ),
            })
        return {"reports": reports}

    async def get_report(self, section_id: str, report_id: int, *, user_id: int | None) -> dict[str, Any]:
        import json

        from app.models.db_models import SavedBacktestReport

        if self.db is None:
            return {"error": "No database session available."}
        report = await self.db.get(SavedBacktestReport, report_id)
        source = self.report_source(section_id)
        if not report or report.source != source or (user_id is not None and report.user_id not in (None, user_id)):
            return {"error": "Report not found."}
        return {
            "id": report.id, "name": report.name, "created_at": report.created_at.isoformat(),
            "payload": json.loads(report.payload_json),
        }

    async def delete_report(self, section_id: str, report_id: int, *, user_id: int | None) -> dict[str, Any]:
        from app.models.db_models import SavedBacktestReport

        if self.db is None:
            return {"error": "No database session available."}
        report = await self.db.get(SavedBacktestReport, report_id)
        source = self.report_source(section_id)
        if not report or report.source != source or (user_id is not None and report.user_id not in (None, user_id)):
            return {"error": "Report not found."}
        await self.db.delete(report)
        await self.db.commit()
        return {"deleted": True}

    async def double_calendar(
        self, tickers: list[str], *, asset_class: str = "india", timeframes: list[str] | None = None,
        exchange: str | None = None, cfg_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.double_calendar_engine import DoubleCalendarConfig, build_double_calendar_many
        from app.market_pulse.ticker_utils import market_currency

        market, default_exchange = await self._asset_ctx(asset_class)
        _, token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, tickers)
        tfs = timeframes or ["1d"]
        cfg = DoubleCalendarConfig(**(cfg_overrides or {}))

        resolved_exchange = exchange or default_exchange

        def _run():
            results = build_double_calendar_many(
                resolved, asset_class, market, tfs,
                cfg=cfg, groww_token=token, exchange=resolved_exchange,
            )
            _attach_ltp(results, market, groww_token=token, exchange=resolved_exchange)
            return results

        results = await asyncio.to_thread(_run)
        return json_safe({
            "results": results, "asset_class": asset_class, "market": market,
            "currency": market_currency(market),
        })

    async def double_calendar_pnl(
        self, net_debit: float, current_mark: float, *, cfg_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.double_calendar_engine import DoubleCalendarConfig, evaluate_double_calendar_pnl

        cfg = DoubleCalendarConfig(**(cfg_overrides or {}))
        return json_safe(evaluate_double_calendar_pnl(net_debit, current_mark, cfg))

    async def delta_neutral(
        self, tickers: list[str], *, asset_class: str = "india", timeframes: list[str] | None = None,
        exchange: str | None = None, cfg_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.delta_neutral_engine import DeltaNeutralConfig, build_delta_neutral_many
        from app.market_pulse.ticker_utils import market_currency

        market, default_exchange = await self._asset_ctx(asset_class)
        _, token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, tickers)
        tfs = timeframes or ["1d"]
        cfg = DeltaNeutralConfig(**(cfg_overrides or {}))

        resolved_exchange = exchange or default_exchange

        def _run():
            results = build_delta_neutral_many(
                resolved, asset_class, market, tfs,
                cfg=cfg, groww_token=token, exchange=resolved_exchange,
            )
            _attach_ltp(results, market, groww_token=token, exchange=resolved_exchange)
            return results

        results = await asyncio.to_thread(_run)
        return json_safe({
            "results": results, "asset_class": asset_class, "market": market,
            "currency": market_currency(market),
        })

    async def delta_neutral_pnl(
        self, net_credit: float, current_cost_to_close: float, *, cfg_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.delta_neutral_engine import DeltaNeutralConfig, evaluate_delta_neutral_pnl

        cfg = DeltaNeutralConfig(**(cfg_overrides or {}))
        return json_safe(evaluate_delta_neutral_pnl(net_credit, current_cost_to_close, cfg))

    async def hedging(
        self, tickers: list[str], *, asset_class: str = "india",
        exchange: str | None = None, cfg_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.hedging_engine import HedgingConfig, build_hedging_many
        from app.market_pulse.ticker_utils import market_currency

        market, default_exchange = await self._asset_ctx(asset_class)
        _, token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, tickers)
        cfg = HedgingConfig(**(cfg_overrides or {}))

        resolved_exchange = exchange or default_exchange

        def _run():
            results = build_hedging_many(
                resolved, asset_class, market,
                cfg=cfg, groww_token=token, exchange=resolved_exchange,
            )
            _attach_ltp(results, market, groww_token=token, exchange=resolved_exchange)
            return results

        results = await asyncio.to_thread(_run)
        return json_safe({
            "results": results, "asset_class": asset_class, "market": market,
            "currency": market_currency(market),
        })

    async def hedging_pnl(
        self, total_capital: float, current_pnl: float, *, cfg_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.hedging_engine import HedgingConfig, evaluate_hedging_pnl

        cfg = HedgingConfig(**(cfg_overrides or {}))
        return json_safe(evaluate_hedging_pnl(total_capital, current_pnl, cfg))

    async def gokul_chhabra(
        self, *, tickers: list[str] | None = None, exchange: str | None = None,
        cfg_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.gokul_chhabra_engine import (
            INDEX_NAMES,
            GokulChhabraConfig,
            scan_universe,
        )
        from app.market_pulse.ticker_utils import market_currency

        market, default_exchange = await self._asset_ctx("india")
        _, token, _ = await self._ctx()
        cfg = GokulChhabraConfig(**(cfg_overrides or {}))
        resolved_exchange = exchange or default_exchange
        names = [n for n in (tickers or INDEX_NAMES) if n in INDEX_NAMES] or list(INDEX_NAMES)

        def _run():
            return scan_universe(
                names, market, cfg=cfg, groww_token=token, exchange=resolved_exchange,
            )

        payload = await asyncio.to_thread(_run)
        payload["asset_class"] = "india"
        payload["currency"] = market_currency(market)
        return json_safe(payload)

    async def market_prediction(
        self,
        symbol: str,
        *,
        is_index: bool = True,
        exchange: str | None = None,
        futures_price: float | None = None,
        fii_index_position_cut: bool | None = None,
        further_analysis: list[str] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.market_prediction_engine import (
            MarketPredictionConfig,
            analyze_market_prediction,
        )

        market, default_exchange = await self._asset_ctx("india")
        _, token, _ = await self._ctx()
        resolved_exchange = exchange or default_exchange
        cfg = MarketPredictionConfig()

        def _run():
            return analyze_market_prediction(
                symbol, is_index=is_index, groww_token=token, exchange=resolved_exchange, cfg=cfg,
                futures_price=futures_price, fii_index_position_cut=fii_index_position_cut,
                further_analysis=further_analysis,
            )

        payload = await asyncio.to_thread(_run)
        return json_safe(payload)

    async def call_put_writing(
        self,
        symbol: str,
        *,
        is_index: bool = True,
        exchange: str | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.call_put_writing_engine import (
            CallPutWritingConfig,
            analyze_call_put_writing,
        )

        market, default_exchange = await self._asset_ctx("india")
        _, token, _ = await self._ctx()
        resolved_exchange = exchange or default_exchange

        def _run():
            return analyze_call_put_writing(
                symbol,
                is_index=is_index,
                groww_token=token,
                exchange=resolved_exchange,
                cfg=CallPutWritingConfig(),
            )

        payload = await asyncio.to_thread(_run)
        payload["market"] = market
        return json_safe(payload)

    async def zero_to_hero(
        self, *, tickers: list[str] | None = None, exchange: str | None = None,
        cfg_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.ticker_utils import market_currency
        from app.market_pulse.zero_to_hero_engine import INDEX_NAMES, ZeroToHeroConfig, scan_universe

        market, default_exchange = await self._asset_ctx("india")
        _, token, _ = await self._ctx()
        cfg = ZeroToHeroConfig(**(cfg_overrides or {}))
        resolved_exchange = exchange or default_exchange
        names = [n for n in (tickers or INDEX_NAMES) if n in INDEX_NAMES] or list(INDEX_NAMES)

        def _run():
            return scan_universe(names, market, cfg=cfg, groww_token=token, exchange=resolved_exchange)

        payload = await asyncio.to_thread(_run)
        payload["asset_class"] = "india"
        payload["currency"] = market_currency(market)
        return json_safe(payload)
