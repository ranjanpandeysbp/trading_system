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
        return await self.settings.prepare_market_data()

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
                    "id": "fibonacci_pro",
                    "label": "Fibonacci Pro",
                    "path": "/pro-trade/fibonacci-pro",
                    "youtube": None,
                },
                {
                    "id": "bb_mean_reversion",
                    "label": "BB Mean Reversion",
                    "path": "/pro-trade/bb-mean-reversion",
                    "youtube": None,
                },
                {
                    "id": "traffic_light_indicator",
                    "label": "Traffic Light Indicator",
                    "path": "/pro-trade/traffic-light-indicator",
                    "youtube": "https://www.youtube.com/watch?v=xIKoYISD6mY&t=29s",
                },
                {
                    "id": "buy_low_sell_high",
                    "label": "Buy Low Sell High",
                    "path": "/pro-trade/buy-low-sell-high",
                    "youtube": None,
                },
                {
                    "id": "rlb_breakout",
                    "label": "RLB - Breakout",
                    "path": "/pro-trade/rlb-breakout",
                    "youtube": "https://www.youtube.com/watch?v=pBQ1oVDVe3M",
                },
                {
                    "id": "three_in_one_trade_system",
                    "label": "3-in-1 Trade System",
                    "path": "/pro-trade/3-in-1-trade-system",
                    "youtube": None,
                },
                {
                    "id": "simple_effective",
                    "label": "Simple Effective",
                    "path": "/pro-trade/simple-effective",
                    "youtube": None,
                },
                {
                    "id": "bb_rsi_vol",
                    "label": "BB-RSI-VOL",
                    "path": "/pro-trade/bb-rsi-vol",
                    "youtube": None,
                },
                {
                    "id": "btst",
                    "label": "Buy Today Sell Tomorrow",
                    "path": "/pro-trade/btst",
                    "youtube": None,
                },
                {
                    "id": "ticker_chart",
                    "label": "Ticker Chart",
                    "path": "/pro-trade/ticker-chart",
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

    async def fibonacci_pro(
        self,
        tickers: list[str],
        *,
        asset_class: str = "india",
        exchange: str | None = None,
        cfg_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.fibonacci_pro_engine import (
            FIBONACCI_PRO_AI_SYSTEM,
            FibonacciProConfig,
            build_fibonacci_pro_ai_prompt,
            scan_universe,
        )
        from app.market_pulse.ticker_utils import market_currency

        if not tickers:
            return {"error": "Select at least one ticker", "results": [], "entry_count": 0}

        market, default_exchange = await self._asset_ctx(asset_class)
        token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, tickers)
        overrides = dict(cfg_overrides or {})
        if not overrides.get("strategies"):
            overrides.pop("strategies", None)
        cfg = FibonacciProConfig(**overrides)
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
            r["ai_context"] = build_fibonacci_pro_ai_prompt(r)
        payload["ai_system_prompt"] = FIBONACCI_PRO_AI_SYSTEM
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

    async def traffic_light_indicator(
        self,
        tickers: list[str],
        *,
        asset_class: str = "india",
        exchange: str | None = None,
        cfg_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.traffic_light_indicator_engine import (
            TRAFFIC_LIGHT_AI_SYSTEM,
            TrafficLightConfig,
            build_traffic_light_ai_prompt,
            scan_universe,
        )
        from app.market_pulse.ticker_utils import market_currency

        if not tickers:
            return {"error": "Select at least one ticker", "results": [], "entry_count": 0}

        market, default_exchange = await self._asset_ctx(asset_class)
        token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, tickers)
        ov = dict(cfg_overrides or {})
        if "further_analysis" in ov and ov["further_analysis"] is None:
            ov["further_analysis"] = []
        cfg = TrafficLightConfig(**{
            k: v for k, v in ov.items()
            if k in {
                "timeframe", "lookback_bars", "sma_green", "sma_yellow", "sma_red",
                "min_bars", "rr_min", "sl_atr_mult", "tp_atr_mult",
                "take_confidence_threshold", "further_analysis", "chart_bars",
            }
        })
        resolved_exchange = exchange or default_exchange

        def _run():
            return scan_universe(
                resolved, market, cfg=cfg, groww_token=token, exchange=resolved_exchange,
            )

        payload = await asyncio.to_thread(_run)
        payload["asset_class"] = asset_class
        payload["market"] = market
        payload["currency"] = market_currency(market)
        for r in payload.get("results", []):
            if isinstance(r, dict):
                r["ai_context"] = build_traffic_light_ai_prompt(r)
        payload["ai_system_prompt"] = TRAFFIC_LIGHT_AI_SYSTEM
        return json_safe(payload)

    async def buy_low_sell_high(
        self,
        tickers: list[str],
        *,
        asset_class: str = "india",
        exchange: str | None = None,
        cfg_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.buy_low_sell_high_engine import (
            BUY_LOW_SELL_HIGH_AI_SYSTEM,
            BuyLowSellHighConfig,
            build_buy_low_sell_high_ai_prompt,
            scan_universe,
        )
        from app.market_pulse.ticker_utils import market_currency

        if not tickers:
            return {"error": "Select at least one ticker", "results": [], "entry_count": 0}

        market, default_exchange = await self._asset_ctx(asset_class)
        token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, tickers)
        ov = dict(cfg_overrides or {})
        cfg = BuyLowSellHighConfig(**{
            k: v for k, v in ov.items()
            if k in {
                "timeframe", "lookback_bars", "low_lookback", "buy_buffer_pct",
                "sell_target_pct", "add_on_drop_pct", "min_bars", "chart_bars",
                "near_trigger_pct",
            }
        })
        resolved_exchange = exchange or default_exchange

        def _run():
            return scan_universe(
                resolved, market, cfg=cfg, groww_token=token, exchange=resolved_exchange,
            )

        payload = await asyncio.to_thread(_run)
        payload["asset_class"] = asset_class
        payload["market"] = market
        payload["currency"] = market_currency(market)
        for r in payload.get("results", []):
            if isinstance(r, dict):
                r["ai_context"] = build_buy_low_sell_high_ai_prompt(r)
        payload["ai_system_prompt"] = BUY_LOW_SELL_HIGH_AI_SYSTEM
        return json_safe(payload)

    async def rlb_breakout(
        self,
        tickers: list[str],
        *,
        asset_class: str = "india",
        exchange: str | None = None,
        cfg_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.rlb_breakout_engine import (
            RLB_AI_SYSTEM,
            RlbBreakoutConfig,
            build_rlb_breakout_ai_prompt,
            scan_universe,
        )
        from app.market_pulse.ticker_utils import market_currency

        if not tickers:
            return {"error": "Select at least one ticker", "results": [], "entry_count": 0}

        market, default_exchange = await self._asset_ctx(asset_class)
        token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, tickers)
        ov = dict(cfg_overrides or {})
        cfg = RlbBreakoutConfig(**{
            k: v for k, v in ov.items()
            if k in {
                "timeframe", "lookback_bars", "ema_fast", "ema_slow", "rsi_period",
                "rsi_min", "rsi_prefer", "min_day_chg_pct", "volume_sma_period",
                "min_bars", "chart_bars", "sl_atr_mult", "tp_atr_mult",
                "take_confidence_threshold", "require_all_seven",
            }
        })
        resolved_exchange = exchange or default_exchange

        def _run():
            return scan_universe(
                resolved, market, cfg=cfg, groww_token=token, exchange=resolved_exchange,
            )

        payload = await asyncio.to_thread(_run)
        payload["asset_class"] = asset_class
        payload["market"] = market
        payload["currency"] = market_currency(market)
        for r in payload.get("results", []):
            if isinstance(r, dict):
                r["ai_context"] = build_rlb_breakout_ai_prompt(r)
        payload["ai_system_prompt"] = RLB_AI_SYSTEM
        return json_safe(payload)

    async def three_in_one_trade_system(
        self,
        tickers: list[str],
        *,
        asset_class: str = "india",
        exchange: str | None = None,
        cfg_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.three_in_one_trade_system_engine import (
            THREE_IN_ONE_AI_SYSTEM,
            ThreeInOneConfig,
            build_three_in_one_ai_prompt,
            scan_universe,
        )
        from app.market_pulse.ticker_utils import market_currency

        if not tickers:
            return {"error": "Select at least one ticker", "results": [], "entry_count": 0}

        market, default_exchange = await self._asset_ctx(asset_class)
        token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, tickers)
        ov = dict(cfg_overrides or {})
        cfg = ThreeInOneConfig(**{
            k: v for k, v in ov.items()
            if k in {
                "timeframe", "lookback_bars", "sma_fast", "sma_mid", "sma_slow",
                "max_pct_above_200", "car_rising_days", "week52_bars",
                "volume_sma_period", "require_volume_breakout", "profit_target_pct",
                "sip_drawdown_pct", "sip_gap_days", "new_buy_capital_pct",
                "reserve_capital_pct", "max_holdings", "min_bars", "chart_bars",
                "take_confidence_threshold",
            }
        })
        resolved_exchange = exchange or default_exchange

        def _run():
            return scan_universe(
                resolved, market, cfg=cfg, groww_token=token, exchange=resolved_exchange,
            )

        payload = await asyncio.to_thread(_run)
        payload["asset_class"] = asset_class
        payload["market"] = market
        payload["currency"] = market_currency(market)
        for r in payload.get("results", []):
            if isinstance(r, dict):
                r["ai_context"] = build_three_in_one_ai_prompt(r)
        payload["ai_system_prompt"] = THREE_IN_ONE_AI_SYSTEM
        return json_safe(payload)

    async def simple_effective(
        self,
        tickers: list[str],
        *,
        asset_class: str = "india",
        exchange: str | None = None,
        timeframes: list[str] | None = None,
        cfg_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.simple_effective_engine import (
            SIMPLE_EFFECTIVE_AI_SYSTEM,
            SimpleEffectiveConfig,
            build_simple_effective_ai_prompt,
            scan_universe,
        )
        from app.market_pulse.ticker_utils import market_currency

        if not tickers:
            return {"error": "Select at least one ticker", "results": [], "entry_count": 0}

        market, default_exchange = await self._asset_ctx(asset_class)
        token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, tickers)
        ov = dict(cfg_overrides or {})
        cfg = SimpleEffectiveConfig(**{
            k: v for k, v in ov.items()
            if k in {
                "timeframe", "lookback_bars", "ma_fast", "ma_slow", "use_ema",
                "macd_fast", "macd_slow", "macd_signal", "rr_multiple",
                "signal_lookback", "open_low_eps_pct", "min_bars", "chart_bars",
                "take_confidence_threshold",
            }
        })
        resolved_exchange = exchange or default_exchange
        tfs = timeframes or ([cfg.timeframe] if cfg.timeframe else ["15m"])

        def _run():
            return scan_universe(
                resolved, market, cfg=cfg, groww_token=token, exchange=resolved_exchange, timeframes=tfs,
            )

        payload = await asyncio.to_thread(_run)
        payload["asset_class"] = asset_class
        payload["market"] = market
        payload["currency"] = market_currency(market)
        for r in payload.get("results", []):
            if isinstance(r, dict):
                r["ai_context"] = build_simple_effective_ai_prompt(r)
        payload["ai_system_prompt"] = SIMPLE_EFFECTIVE_AI_SYSTEM
        return json_safe(payload)

    async def bb_rsi_vol(
        self,
        tickers: list[str],
        *,
        asset_class: str = "india",
        exchange: str | None = None,
        timeframes: list[str] | None = None,
        cfg_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.bb_rsi_vol_engine import (
            BB_RSI_VOL_AI_SYSTEM,
            BbRsiVolConfig,
            build_bb_rsi_vol_ai_prompt,
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
        ov = dict(cfg_overrides or {})
        cfg = BbRsiVolConfig(**{
            k: v for k, v in ov.items()
            if k in {
                "timeframe", "lookback_bars", "bb_period", "bb_std", "rsi_period",
                "rsi_buy", "rsi_sell", "vol_ma_period", "ema_fast", "ema_ultra_fast", "ema_trend",
                "zone_tolerance_pct", "min_rr", "sl_atr_mult", "er_hard_block",
                "take_confidence_threshold", "min_bars", "chart_bars",
                "require_sr", "require_ema_cross_close",
                "history_days", "continuation_bars", "intensity_lookback_bars",
            }
        })
        resolved_exchange = exchange or default_exchange

        def _run():
            return scan_universe(
                resolved, market, cfg=cfg, groww_token=token, exchange=resolved_exchange, timeframes=timeframes,
            )

        payload = await asyncio.to_thread(_run)
        payload["asset_class"] = asset_class
        payload["market"] = market
        payload["currency"] = market_currency(market)
        for r in payload.get("results", []):
            if isinstance(r, dict):
                r["ai_context"] = build_bb_rsi_vol_ai_prompt(r)
        payload["ai_system_prompt"] = BB_RSI_VOL_AI_SYSTEM
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

    async def ticker_chart(
        self,
        *,
        ticker: str,
        asset_class: str = "india",
        mode: str = "daily",
        from_date: str | None = None,
        to_date: str | None = None,
        session_date: str | None = None,
        interval: str = "1d",
        indicators: list[str] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.ticker_chart_engine import compute_ticker_chart

        market, _ = await self._asset_ctx(asset_class)

        def _run():
            return compute_ticker_chart(
                ticker=ticker,
                asset_class=asset_class,
                mode=mode,
                from_date=from_date,
                to_date=to_date,
                session_date=session_date,
                interval=interval,
                market=market,
                indicators=indicators,
            )

        return json_safe(await asyncio.to_thread(_run))

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
