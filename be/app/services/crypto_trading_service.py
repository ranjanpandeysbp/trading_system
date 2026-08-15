"""Crypto Trading desks — Multibagger Reversal and future crypto strategies."""

from __future__ import annotations

import asyncio
from typing import Any

from app.market_pulse.serialize import json_safe
from app.services.settings_service import SettingsService


class CryptoTradingService:
    def __init__(self, settings: SettingsService):
        self.settings = settings

    async def sections(self) -> dict[str, Any]:
        return {
            "sections": [
                {
                    "id": "multibagger_reversal",
                    "label": "Multibagger Reversal",
                    "path": "/crypto-trading/multibagger-reversal",
                    "youtube": None,
                },
                {
                    "id": "advance_bb_reversal",
                    "label": "Advance BB Reversal",
                    "path": "/crypto-trading/advance-bb-reversal",
                    "youtube": None,
                },
                {
                    "id": "ema_crossover",
                    "label": "EMA Crossover",
                    "path": "/crypto-trading/ema-crossover",
                    "youtube": None,
                },
            ],
        }

    async def multibagger_reversal(
        self,
        *,
        tickers: list[str] | None = None,
        cfg_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.crypto_multibagger_reversal_engine import (
            MultibaggerReversalConfig,
            scan_universe,
        )

        ov = dict(cfg_overrides or {})
        cfg = MultibaggerReversalConfig(**{
            k: v for k, v in ov.items()
            if k in {
                "move_threshold_pct", "timeframe", "ema_period", "st_period", "st_mult",
                "target_pct", "lookback_bars", "min_bars", "chart_bars",
                "max_candidates", "take_confidence_threshold",
            }
        })

        def _run():
            return scan_universe(
                cfg=cfg,
                tickers=tickers or None,
            )

        payload = await asyncio.to_thread(_run)
        return json_safe(payload)

    async def advance_bb_reversal(
        self,
        *,
        tickers: list[str] | None = None,
        cfg_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.crypto_advance_bb_reversal_engine import (
            AdvanceBbReversalConfig,
            scan_universe,
        )

        ov = dict(cfg_overrides or {})
        cfg = AdvanceBbReversalConfig(**{
            k: v for k, v in ov.items()
            if k in {
                "timeframe", "bb_period", "bb_std", "trend_ema", "lookback_bars",
                "min_bars", "chart_bars", "max_tickers", "risk_inr", "reward_inr",
                "margin_inr", "leverage", "require_trend", "require_sr",
                "sr_near_pct", "take_confidence_threshold", "side",
            }
        })

        def _run():
            return scan_universe(cfg=cfg, tickers=tickers or None)

        payload = await asyncio.to_thread(_run)
        return json_safe(payload)

    async def ema_crossover(
        self,
        *,
        tickers: list[str] | None = None,
        cfg_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.crypto_ema_crossover_engine import (
            EmaCrossoverConfig,
            scan_universe,
        )

        ov = dict(cfg_overrides or {})
        cfg = EmaCrossoverConfig(**{
            k: v for k, v in ov.items()
            if k in {
                "timeframe", "fast", "slow", "lookback_bars", "min_bars", "chart_bars",
                "rr_min", "rr_max", "risk_inr", "margin_inr", "leverage",
                "take_confidence_threshold", "side", "default_tickers",
            }
        })

        def _run():
            return scan_universe(cfg=cfg, tickers=tickers or None)

        payload = await asyncio.to_thread(_run)
        return json_safe(payload)
