"""Command Center — Tomorrow outlook, Buy/Sell advisor, Mega analyser."""

from __future__ import annotations

import asyncio
import importlib
from typing import Any

from app.market_pulse.serialize import json_safe
from app.services.settings_service import SettingsService
from app.services.ticker_universe_service import TickerUniverseService

_ONE_CLICK_MODULES = {
    "intraday": "app.market_pulse.one_click_intraday_engine",
    "scalping": "app.market_pulse.one_click_scalping_engine",
    "swing": "app.market_pulse.one_click_swing_engine",
}


class CommandCenterService:
    def __init__(self, settings: SettingsService):
        self.settings = settings
        self.universe = TickerUniverseService()

    async def _ctx(self) -> tuple[str, str, str]:
        token = await self.settings.get_groww_token() or ""
        exchange = await self.settings.get_groww_exchange()
        market = await self.settings.get_default_market()
        return market, token, exchange

    async def tomorrow_outlook(self) -> dict[str, Any]:
        from app.services.market_pulse_service import MarketPulseService

        mp = MarketPulseService(self.settings)
        return await mp.tomorrow_outlook()

    async def ticker_universe(self, asset_class: str) -> dict[str, Any]:
        return self.universe.config(asset_class)

    async def buy_sell_advisor(
        self,
        tickers: list[str],
        *,
        asset_class: str = "india",
        scenario: str = "balanced",
        durations: list[str] | None = None,
    ) -> dict[str, Any]:
        _ = scenario
        _, token, _ = await self._ctx()
        try:
            from app.market_pulse.buy_sell_advisor_engine import ASSET_CLASS_CONFIG, run_buy_sell_advisor
        except ImportError as exc:
            return {"error": f"Buy/Sell advisor not loaded: {exc}", "recommendations": []}

        cfg = ASSET_CLASS_CONFIG.get(asset_class) or ASSET_CLASS_CONFIG["india"]
        dur = durations or list(cfg.get("default_durations") or ["1d"])
        resolved = self.universe.resolve(asset_class, tickers)

        def _run():
            return run_buy_sell_advisor(
                asset_class,
                resolved,
                dur,
                groww_token=token,
            )

        result = await asyncio.to_thread(_run)
        if not result:
            return {"error": "Buy/Sell advisor returned no results.", "recommendations": []}
        return result

    async def mega_analyser(
        self,
        tickers: list[str],
        *,
        asset_class: str = "india",
        durations: list[str] | None = None,
    ) -> dict[str, Any]:
        resolved = self.universe.resolve(asset_class, tickers)
        bs = await self.buy_sell_advisor(
            resolved,
            asset_class=asset_class,
            durations=durations,
        )
        if bs.get("error") and not bs.get("recommendations"):
            return bs

        recs = bs.get("recommendations") or []
        by_ticker = {r["ticker"]: r for r in recs}
        return {
            "tickers": resolved,
            "asset_class": asset_class,
            "mega_by_ticker": by_ticker,
            "mega": recs[0] if len(recs) == 1 else None,
            "recommendations": recs,
            "summaries": bs.get("summaries") or [],
            "by_ticker": bs.get("by_ticker") or {},
            "market": bs.get("market"),
        }

    async def _asset_ctx(self, asset_class: str) -> tuple[str, str]:
        from app.market_pulse.asset_class_config import ASSET_CLASS_CONFIG

        cfg = ASSET_CLASS_CONFIG.get(asset_class) or ASSET_CLASS_CONFIG["india"]
        return str(cfg["market"]), str(cfg.get("exchange") or "NSE")

    async def global_market_mood(self) -> dict[str, Any]:
        from app.market_pulse.global_market_mood_engine import scan_global_market_mood

        return json_safe(await asyncio.to_thread(scan_global_market_mood))

    async def momentum(
        self, tickers: list[str], *, asset_class: str = "india", timeframes: list[str] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.momentum_engine import MomentumConfig, scan_universe

        market, exchange = await self._asset_ctx(asset_class)
        _, token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, tickers)
        cfg = MomentumConfig(timeframes=timeframes) if timeframes else None

        def _run():
            return scan_universe(resolved, market, cfg=cfg, groww_token=token, exchange=exchange)

        results = await asyncio.to_thread(_run)
        return json_safe({"market": market, "results": results})

    async def trade_setup(
        self, tickers: list[str], *, asset_class: str = "india", timeframes: list[str] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.trade_setup_engine import (
            DEFAULT_TIMEFRAMES,
            analyze_trade_setup_many,
            group_by_timeframe_bucket,
        )

        market, exchange = await self._asset_ctx(asset_class)
        _, token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, tickers)
        tfs = timeframes or list(DEFAULT_TIMEFRAMES)

        def _run():
            results = analyze_trade_setup_many(resolved, tfs, market, groww_token=token, exchange=exchange)
            grouped = group_by_timeframe_bucket(results, tfs)
            return results, grouped

        results, grouped = await asyncio.to_thread(_run)
        return json_safe({"market": market, "timeframes": tfs, "results": results, "grouped": grouped})

    async def trade_setup_patterns(
        self, ticker: str, *, asset_class: str = "india", timeframe: str = "15m",
    ) -> dict[str, Any]:
        from app.market_pulse.trade_setup_engine import analyze_patterns_one

        market, exchange = await self._asset_ctx(asset_class)
        _, token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, [ticker])[0]
        result = await asyncio.to_thread(
            analyze_patterns_one, resolved, timeframe, market, groww_token=token, exchange=exchange,
        )
        return json_safe(result)

    async def trade_setup_support_resistance(
        self, ticker: str, *, asset_class: str = "india", timeframe: str = "15m",
    ) -> dict[str, Any]:
        from app.market_pulse.trade_setup_engine import analyze_support_resistance_one

        market, exchange = await self._asset_ctx(asset_class)
        _, token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, [ticker])[0]
        result = await asyncio.to_thread(
            analyze_support_resistance_one, resolved, timeframe, market, groww_token=token, exchange=exchange,
        )
        return json_safe(result)

    async def trade_setup_smart_money(
        self, ticker: str, *, asset_class: str = "india", timeframe: str = "15m",
    ) -> dict[str, Any]:
        from app.market_pulse.trade_setup_engine import analyze_smart_money_one

        market, exchange = await self._asset_ctx(asset_class)
        _, token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, [ticker])[0]
        result = await asyncio.to_thread(
            analyze_smart_money_one, resolved, timeframe, market, groww_token=token, exchange=exchange,
        )
        return json_safe(result)

    async def trade_setup_scalping(
        self, ticker: str, *, asset_class: str = "india", timeframe: str = "15m",
    ) -> dict[str, Any]:
        from app.market_pulse.trade_setup_engine import analyze_scalping_confluence_one

        market, exchange = await self._asset_ctx(asset_class)
        _, token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, [ticker])[0]
        result = await asyncio.to_thread(
            analyze_scalping_confluence_one, resolved, timeframe, market, groww_token=token, exchange=exchange,
        )
        return json_safe(result)

    async def trade_setup_time_series(
        self, ticker: str, *, asset_class: str = "india", timeframe: str = "15m",
    ) -> dict[str, Any]:
        from app.market_pulse.trade_setup_engine import analyze_time_series_one

        market, exchange = await self._asset_ctx(asset_class)
        _, token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, [ticker])[0]
        result = await asyncio.to_thread(
            analyze_time_series_one, resolved, timeframe, market, groww_token=token, exchange=exchange,
        )
        return json_safe(result)

    async def trade_setup_divergence(
        self, ticker: str, *, asset_class: str = "india", timeframe: str = "15m",
    ) -> dict[str, Any]:
        from app.market_pulse.trade_setup_engine import analyze_divergence_one

        market, exchange = await self._asset_ctx(asset_class)
        _, token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, [ticker])[0]
        result = await asyncio.to_thread(
            analyze_divergence_one, resolved, timeframe, market, groww_token=token, exchange=exchange,
        )
        return json_safe(result)

    async def divergences(
        self, tickers: list[str], *, asset_class: str = "india", timeframes: list[str] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.divergence_engine import analyze_tickers_multi_tf
        from app.market_pulse.trade_setup_engine import DEFAULT_TIMEFRAMES

        market, exchange = await self._asset_ctx(asset_class)
        _, token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, tickers)
        tfs = timeframes or list(DEFAULT_TIMEFRAMES)
        results = await asyncio.to_thread(
            analyze_tickers_multi_tf, resolved, tfs, market, groww_token=token, exchange=exchange,
        )
        return json_safe({"results": results, "timeframes": tfs, "market": market})

    async def patterns(
        self, tickers: list[str], *, asset_class: str = "india", timeframes: list[str] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.pattern_engine import analyze_tickers_multi_tf as analyze_patterns_multi_tf
        from app.market_pulse.trade_setup_engine import DEFAULT_TIMEFRAMES

        market, exchange = await self._asset_ctx(asset_class)
        _, token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, tickers)
        tfs = timeframes or list(DEFAULT_TIMEFRAMES)
        results = await asyncio.to_thread(
            analyze_patterns_multi_tf, resolved, tfs, market, groww_token=token, exchange=exchange,
        )
        return json_safe({"results": results, "timeframes": tfs, "market": market})

    async def trade_setup_stop_hunt(
        self, ticker: str, *, asset_class: str = "india", timeframe: str = "15m",
    ) -> dict[str, Any]:
        from app.market_pulse.trade_setup_engine import analyze_stop_hunt_one

        market, exchange = await self._asset_ctx(asset_class)
        _, token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, [ticker])[0]
        result = await asyncio.to_thread(
            analyze_stop_hunt_one, resolved, timeframe, market, groww_token=token, exchange=exchange,
        )
        return json_safe(result)

    async def stop_hunt(
        self, tickers: list[str], *, asset_class: str = "india", timeframes: list[str] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.stop_hunt_engine import analyze_tickers_multi_tf as analyze_stop_hunt_multi_tf
        from app.market_pulse.trade_setup_engine import DEFAULT_TIMEFRAMES

        market, exchange = await self._asset_ctx(asset_class)
        _, token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, tickers)
        tfs = timeframes or list(DEFAULT_TIMEFRAMES)
        results = await asyncio.to_thread(
            analyze_stop_hunt_multi_tf, resolved, tfs, market, groww_token=token, exchange=exchange,
        )
        return json_safe({"results": results, "timeframes": tfs, "market": market})

    async def trade_setup_take_profit(
        self, ticker: str, *, asset_class: str = "india", timeframe: str = "15m",
    ) -> dict[str, Any]:
        from app.market_pulse.trade_setup_engine import analyze_take_profit_one

        market, exchange = await self._asset_ctx(asset_class)
        _, token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, [ticker])[0]
        result = await asyncio.to_thread(
            analyze_take_profit_one, resolved, timeframe, market, groww_token=token, exchange=exchange,
        )
        return json_safe(result)

    async def trade_setup_real_bottom(
        self, ticker: str, *, asset_class: str = "india", timeframe: str = "15m",
    ) -> dict[str, Any]:
        from app.market_pulse.trade_setup_engine import analyze_real_bottom_one

        market, exchange = await self._asset_ctx(asset_class)
        _, token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, [ticker])[0]
        result = await asyncio.to_thread(
            analyze_real_bottom_one, resolved, timeframe, market, groww_token=token, exchange=exchange,
        )
        return json_safe(result)

    async def real_bottom(
        self, tickers: list[str], *, asset_class: str = "india", timeframes: list[str] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.real_bottom_engine import analyze_tickers_multi_tf as analyze_real_bottom_multi_tf
        from app.market_pulse.trade_setup_engine import DEFAULT_TIMEFRAMES

        market, exchange = await self._asset_ctx(asset_class)
        _, token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, tickers)
        tfs = timeframes or list(DEFAULT_TIMEFRAMES)
        results = await asyncio.to_thread(
            analyze_real_bottom_multi_tf, resolved, tfs, market, groww_token=token, exchange=exchange,
        )
        return json_safe({"results": results, "timeframes": tfs, "market": market})

    async def take_profit(
        self, tickers: list[str], *, asset_class: str = "india", timeframes: list[str] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.take_profit_engine import analyze_tickers_multi_tf as analyze_take_profit_multi_tf
        from app.market_pulse.trade_setup_engine import DEFAULT_TIMEFRAMES

        market, exchange = await self._asset_ctx(asset_class)
        _, token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, tickers)
        tfs = timeframes or list(DEFAULT_TIMEFRAMES)
        results = await asyncio.to_thread(
            analyze_take_profit_multi_tf, resolved, tfs, market, groww_token=token, exchange=exchange,
        )
        return json_safe({"results": results, "timeframes": tfs, "market": market})

    async def take_trade(
        self, tickers: list[str], *, asset_class: str = "india", timeframes: list[str] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.take_trade_engine import analyze_tickers_multi_tf as analyze_take_trade_multi_tf
        from app.market_pulse.trade_setup_engine import DEFAULT_TIMEFRAMES

        market, exchange = await self._asset_ctx(asset_class)
        _, token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, tickers)
        tfs = timeframes or list(DEFAULT_TIMEFRAMES)
        results = await asyncio.to_thread(
            analyze_take_trade_multi_tf, resolved, tfs, asset_class, market, groww_token=token, exchange=exchange,
        )
        return json_safe({"results": results, "timeframes": tfs, "market": market})

    async def ema_position(
        self, tickers: list[str], *, asset_class: str = "india", timeframes: list[str] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.ema_position_engine import EmaPositionConfig, scan_universe

        market, exchange = await self._asset_ctx(asset_class)
        _, token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, tickers)
        cfg = EmaPositionConfig(timeframes=timeframes) if timeframes else None

        def _run():
            return scan_universe(resolved, market, cfg=cfg, groww_token=token, exchange=exchange)

        results = await asyncio.to_thread(_run)
        return json_safe({"market": market, "results": results})

    async def one_click(self, style: str, tickers: list[str], *, asset_class: str = "india") -> dict[str, Any]:
        mod_name = _ONE_CLICK_MODULES.get(style)
        if not mod_name:
            return {"error": f"Unknown one-click style: {style}. Choose intraday, scalping, or swing."}
        mod = importlib.import_module(mod_name)
        market, exchange = await self._asset_ctx(asset_class)
        _, token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, tickers)

        def _run():
            return mod.analyze_tickers(resolved, market, groww_token=token, exchange=exchange)

        results = await asyncio.to_thread(_run)
        return json_safe({"style": style, "market": market, "results": results})

    async def mutual_fund_amc_list(self) -> dict[str, Any]:
        from app.market_pulse.mutual_fund_holdings_engine import fetch_amc_list

        return json_safe({"amcs": await asyncio.to_thread(fetch_amc_list)})

    async def mutual_fund_schemes(self, amc_id: int) -> dict[str, Any]:
        from app.market_pulse.mutual_fund_holdings_engine import fetch_schemes_for_amc

        return json_safe({"schemes": await asyncio.to_thread(fetch_schemes_for_amc, amc_id)})

    async def mutual_fund_holdings_change(
        self,
        scheme_ids: list[int],
        scheme_names: dict[int, str],
        from_date: str,
        to_date: str,
    ) -> dict[str, Any]:
        from datetime import date as date_cls

        from app.market_pulse.mutual_fund_holdings_engine import analyze_holdings_change

        def _run():
            return analyze_holdings_change(
                scheme_ids,
                scheme_names,
                date_cls.fromisoformat(from_date),
                date_cls.fromisoformat(to_date),
            )

        return json_safe(await asyncio.to_thread(_run))

    async def fundamental_analysis(self, tickers: list[str]) -> dict[str, Any]:
        from app.market_pulse.fundamental_analysis_engine import analyze_tickers

        results = await asyncio.to_thread(analyze_tickers, tickers)
        return json_safe({"results": results})

    async def stock_upgrade_downgrade(self, tickers: list[str], *, asset_class: str = "india") -> dict[str, Any]:
        from app.market_pulse.stock_upgrade_downgrade_engine import scan_tickers

        market, _ = await self._asset_ctx(asset_class)
        resolved = self.universe.resolve(asset_class, tickers)
        results = await asyncio.to_thread(scan_tickers, resolved, market)
        return json_safe({"market": market, "results": results})

    async def investigation_strategy_catalog(self) -> dict[str, Any]:
        from app.market_pulse.ticker_investigation_strategy_catalog import investigation_strategy_groups

        return json_safe({"groups": investigation_strategy_groups()})

    async def investigate_with_strategies(
        self,
        asset_class: str,
        tickers: list[str],
        *,
        strategy_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        from app.market_pulse.ticker_investigation_strategy_engine import (
            run_ticker_investigation_with_strategies,
        )

        _, token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, tickers)

        def _run():
            return run_ticker_investigation_with_strategies(
                asset_class, resolved, strategy_ids=strategy_ids, groww_token=token,
            )

        result = await asyncio.to_thread(_run)
        return json_safe(result or {"error": "No results for the selected tickers."})

    async def mega_setup_advice(
        self,
        market: str,
        timeframes: list[str],
        *,
        ticker_count: int = 0,
        use_ai: bool = False,
        user_goal: str = "",
    ) -> dict[str, Any]:
        from app.market_pulse.mega_setup_advisor import (
            recommend_mega_setup_ai,
            recommend_mega_setup_rule_based,
        )

        if not use_ai:
            return json_safe(
                await asyncio.to_thread(recommend_mega_setup_rule_based, market, timeframes, ticker_count=ticker_count)
            )

        provider = await self.settings.get_ai_provider()
        api_key = await self.settings.get_api_key_for_provider(provider)
        model = await self.settings.get_ai_model(provider)
        if not api_key:
            return json_safe(
                await asyncio.to_thread(recommend_mega_setup_rule_based, market, timeframes, ticker_count=ticker_count)
            )

        def _run():
            return recommend_mega_setup_ai(
                market=market,
                timeframes=timeframes,
                ticker_count=ticker_count,
                user_goal=user_goal,
                provider=provider,
                model=model,
                api_key=api_key,
            )

        return json_safe(await asyncio.to_thread(_run))

    async def coindcx_24h_volatility(self) -> dict[str, Any]:
        from app.market_pulse.coindcx_24h_volatility_engine import fetch_change_24h

        return json_safe({"rows": await asyncio.to_thread(fetch_change_24h)})

    async def nse_indices(self) -> dict[str, Any]:
        from app.market_pulse.dhan_indices_engine import fetch_nse_indices

        return json_safe({"rows": await asyncio.to_thread(fetch_nse_indices)})

    async def global_indices(self) -> dict[str, Any]:
        from app.market_pulse.dhan_indices_engine import fetch_global_indices

        return json_safe({"rows": await asyncio.to_thread(fetch_global_indices)})

    async def futures_indices(self) -> dict[str, Any]:
        from app.market_pulse.futures_indices_engine import fetch_futures_indices

        return json_safe({"rows": await asyncio.to_thread(fetch_futures_indices)})

    async def gift_nifty(self) -> dict[str, Any]:
        from app.market_pulse.futures_indices_engine import fetch_gift_nifty

        return json_safe({"data": await asyncio.to_thread(fetch_gift_nifty)})

    async def india_market_heatmap_indices(self) -> dict[str, Any]:
        from app.market_pulse.india_market_heatmap_engine import INDEX_NAMES

        return json_safe({"index_names": INDEX_NAMES})

    async def india_market_heatmap(self, index_name: str) -> dict[str, Any]:
        from app.market_pulse.india_market_heatmap_engine import (
            INDEX_NAME_TO_SYMBOL,
            fetch_heatmap,
        )

        symbol = INDEX_NAME_TO_SYMBOL.get(index_name, index_name)
        rows = await asyncio.to_thread(fetch_heatmap, symbol)
        return json_safe({"index_name": index_name, "symbol": symbol, "rows": rows})

    async def quick_analyzer(
        self,
        tickers: list[str],
        timeframes: list[str],
        *,
        asset_class: str = "india",
        from_date: str | None = None,
        to_date: str | None = None,
        include_fundamentals: bool = False,
        include_option_chain: bool = False,
    ) -> dict[str, Any]:
        from datetime import date as date_cls, timedelta

        from app.market_pulse.quick_analyzer_engine import (
            analyze_quick_many,
            apply_combined_signals_to_quick_results,
        )

        market, exchange = await self._asset_ctx(asset_class)
        _, token, _ = await self._ctx()
        resolved = self.universe.resolve(asset_class, tickers)

        parsed_to = date_cls.fromisoformat(to_date) if to_date else date_cls.today()
        parsed_from = date_cls.fromisoformat(from_date) if from_date else parsed_to - timedelta(days=90)

        def _run():
            results = analyze_quick_many(
                resolved, timeframes, market,
                groww_token=token, exchange=exchange,
                from_date=parsed_from, to_date=parsed_to,
            )
            apply_combined_signals_to_quick_results(
                results, market,
                include_fundamentals=include_fundamentals,
                include_option_chain=include_option_chain,
                groww_token=token,
            )
            return results

        results = await asyncio.to_thread(_run)
        return json_safe({"market": market, "results": results})

    async def option_chain(self, symbol: str, is_index: bool) -> dict[str, Any]:
        from app.market_pulse.option_chain_engine import (
            classify_option_chain_signal,
            fetch_option_chain,
        )

        _, token, _ = await self._ctx()

        def _run():
            chain = fetch_option_chain(symbol, is_index, token)
            if not chain:
                return None
            return {"symbol": symbol, "chain": chain, "signal": classify_option_chain_signal(chain)}

        result = await asyncio.to_thread(_run)
        return json_safe(result or {"error": f"Could not fetch the option chain for {symbol} right now."})

    def sections(self) -> dict[str, Any]:
        return {
            "sections": [
                {"id": "tomorrow_outlook", "label": "Tomorrow & Today Market Outlook"},
                {"id": "mega_analyser", "label": "Mega Analyser"},
                {"id": "buy_sell", "label": "Buy or Sell (India · US · Crypto · Commodity)"},
                {"id": "investigation", "label": "Ticker Investigation"},
                {"id": "global_market_mood", "label": "Global Market Mood"},
                {"id": "momentum", "label": "Momentum Scanner"},
                {"id": "ema_position", "label": "EMA Position Scanner"},
                {"id": "one_click_intraday", "label": "One-Click Intraday Setup"},
                {"id": "one_click_scalping", "label": "One-Click Scalping Setup"},
                {"id": "one_click_swing", "label": "One-Click Swing Setup"},
                {"id": "mutual_fund_holdings", "label": "Mutual Fund Holdings Tracker"},
                {"id": "fundamental_analysis", "label": "Fundamental Analysis (screener.in)"},
                {"id": "stock_upgrade_downgrade", "label": "Upgrade/Downgrade & Corporate Actions"},
                {"id": "investigation_strategies", "label": "Ticker Investigation — Select Strategy"},
                {"id": "mega_setup_advisor", "label": "Mega Setup Advisor"},
                {"id": "option_chain", "label": "Option Chain — Bias, PCR & Trade Signal (NSE)"},
                {"id": "india_market_heatmap", "label": "Indian Market Heatmap"},
                {"id": "nse_world_indices", "label": "NSE and World Indices"},
                {"id": "coindcx_24h_volatility", "label": "24Hrs Volatile Crypto"},
                {"id": "quick_analyzer", "label": "Quick Analyzer (India · US · Crypto)"},
            ]
        }
