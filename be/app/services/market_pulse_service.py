"""Market Pulse service — India-only sections ported from truebacktesting."""

from __future__ import annotations

import asyncio
from typing import Any

from app.market_pulse.cache_utils import attach_clear_stubs
from app.market_pulse.groww_auth import set_groww_token
from app.market_pulse.india_gainers_losers import compute_india_movers
from app.market_pulse.india_loader import load_india_intelligence
from app.market_pulse.serialize import json_safe
from app.services.settings_service import SettingsService


class MarketPulseService:
    def __init__(self, settings: SettingsService):
        self.settings = settings

    async def _groww_token(self) -> str:
        return await self.settings.get_groww_token() or ""

    async def _exchange(self) -> str:
        return await self.settings.get_groww_exchange()

    async def _run(self, fn, *args, **kwargs) -> Any:
        token = await self._groww_token()
        exchange = await self._exchange()
        set_groww_token(token)

        def _wrapped():
            set_groww_token(token)
            return fn(*args, groww_token=token, exchange=exchange, **kwargs)

        return await asyncio.to_thread(_wrapped)

    async def intelligence(self) -> dict:
        token = await self._groww_token()
        return await asyncio.to_thread(load_india_intelligence, token)

    async def nifty_breadth(self, offset: int = 0, limit: int = 10, include_sr: bool = False) -> dict:
        import app.market_pulse.news_scanner as ns

        attach_clear_stubs(ns)
        token = await self._groww_token()

        def _fetch():
            set_groww_token(token)
            try:
                breadth = ns.fetch_nse_market_breadth()
                if not breadth:
                    return {"error": "NSE breadth unavailable", "items": []}
                indices_map = ns._breadth_indices_map(breadth)
                units = ns._build_nifty_breadth_work_units(breadth)
                page = units[offset : offset + limit]
                sr_map: dict = {}
                if include_sr and page:
                    try:
                        sr_map = ns.fetch_index_sr_levels(tuple(u["name"] for u in page)) or {}
                    except Exception:
                        sr_map = {}
                items = []
                for unit in page:
                    name = unit["name"]
                    b = indices_map.get(name, {})
                    items.append(
                        {
                            "index_name": name,
                            "group": unit.get("group_label"),
                            "advances": b.get("advances"),
                            "declines": b.get("declines"),
                            "unchanged": b.get("unchanged"),
                            "pct_change": b.get("pct"),
                            "last": b.get("last"),
                            "sr": sr_map.get(name, {}),
                        }
                    )
                return {
                    "total": len(units),
                    "offset": offset,
                    "limit": limit,
                    "items": items,
                }
            except Exception as e:
                return {"error": str(e), "items": [], "total": 0, "offset": offset, "limit": limit}

        return json_safe(await asyncio.to_thread(_fetch))

    async def nifty_monthly(self, offset: int = 0, limit: int = 2) -> dict:
        import app.market_pulse.news_scanner as ns

        attach_clear_stubs(ns)
        token = await self._groww_token()

        def _fetch():
            set_groww_token(token)
            try:
                breadth = ns.fetch_nse_market_breadth()
                if not breadth:
                    return {"error": "NSE breadth unavailable", "items": []}
                units = [
                    u for u in ns._build_nifty_monthly_work_units(breadth)
                    if u.get("kind") == "index"
                ]
                items = []
                for unit in units[offset : offset + limit]:
                    name = unit["name"]
                    movers = ns.fetch_index_monthly_stock_movers(name)
                    items.append(
                        {
                            "index_name": name,
                            "group": unit.get("group_label"),
                            "index_return_pct": unit.get("pct_30d"),
                            "movers": movers,
                        }
                    )
                return {"total": len(units), "offset": offset, "limit": limit, "items": items}
            except Exception as e:
                return {"error": str(e), "items": [], "total": 0, "offset": offset, "limit": limit}

        return json_safe(await asyncio.to_thread(_fetch))

    async def nifty_movers(self, index_name: str) -> dict:
        import app.market_pulse.news_scanner as ns

        attach_clear_stubs(ns)
        # No top-N cap — return the full constituent ranked list.
        data = await asyncio.to_thread(ns.fetch_nse_index_stock_movers, index_name, None)
        if not data:
            data = await self._run(compute_india_movers, index_name, "1d", 1)
        return json_safe(data or {"error": f"No movers for {index_name}", "gainers": [], "losers": []})

    async def gainers_losers(
        self, index_name: str, tf_key: str = "1d", lookback_bars: int = 1
    ) -> dict:
        return json_safe(
            await self._run(
                compute_india_movers,
                index_name,
                tf_key,
                lookback_bars,
            )
        )

    async def stock_rotation(
        self, index_name: str, tf_key: str = "1d", lookback_bars: int = 5
    ) -> dict:
        import app.market_pulse.stock_price_rotation as spr
        import app.market_pulse.news_scanner as ns

        attach_clear_stubs(spr)
        attach_clear_stubs(ns)

        def _fetch():
            try:
                from app.market_pulse.groww_auth import get_active_groww_token

                symbols = spr._resolve_constituent_symbols(index_name)
                token = get_active_groww_token()
                payload = spr.compute_stock_price_rotation(
                    index_name,
                    tuple(symbols),
                    tf_key,
                    lookback_bars,
                    use_groww=bool(token),
                )
                return payload or {"error": "No rotation data", "inflow": [], "outflow": []}
            except Exception as e:
                return {"error": str(e), "inflow": [], "outflow": []}

        token = await self._groww_token()
        set_groww_token(token)
        return json_safe(await asyncio.to_thread(_fetch))

    async def sector_rotation(self, indices: list[str] | None = None) -> dict:
        import app.market_pulse.news_scanner as ns
        from app.market_pulse.sector_rotation_markets import INDIA_SECTOR_INDICES

        attach_clear_stubs(ns)
        token = await self._groww_token()
        exchange = await self._exchange()
        names = tuple(indices or INDIA_SECTOR_INDICES)

        def _fetch():
            return ns.compute_sector_rotation(names, days=5, weeks=4, months=3, use_groww=bool(token), exchange=exchange)

        set_groww_token(token)
        return json_safe(await asyncio.to_thread(_fetch) or {"error": "Sector rotation unavailable"})

    async def sector_rotation_intraday(self, indices: list[str] | None = None) -> dict:
        import app.market_pulse.news_scanner as ns
        from app.market_pulse.sector_rotation_markets import INDIA_SECTOR_INDICES

        attach_clear_stubs(ns)
        token = await self._groww_token()
        exchange = await self._exchange()
        names = tuple(indices or INDIA_SECTOR_INDICES)

        def _fetch():
            return ns.compute_sector_rotation_intraday(
                names, minutes=15, hours=4, days=5, use_groww=bool(token), exchange=exchange
            )

        set_groww_token(token)
        return json_safe(await asyncio.to_thread(_fetch) or {"error": "Intraday rotation unavailable"})

    async def sector_rotation_market(self, market: str, indices: list[str] | None = None) -> dict:
        """Sector rotation (HTF) for 'us' or 'crypto' — India uses sector_rotation()."""
        from app.market_pulse.sector_rotation_markets import (
            CRYPTO_BENCHMARK_SYMBOL,
            CRYPTO_SECTOR_SYMBOLS,
            US_BENCHMARK_SYMBOL,
            US_SPDR_SECTORS,
            compute_market_sector_rotation_htf,
        )

        catalog = CRYPTO_SECTOR_SYMBOLS if market == "crypto" else US_SPDR_SECTORS
        benchmark = CRYPTO_BENCHMARK_SYMBOL if market == "crypto" else US_BENCHMARK_SYMBOL
        names = [n for n in (indices or list(catalog.keys())) if n in catalog]
        instruments = tuple((n, catalog[n]) for n in names)

        def _fetch():
            return compute_market_sector_rotation_htf(instruments, benchmark, 5, 4, 3, market)

        return json_safe(await asyncio.to_thread(_fetch) or {"error": "Sector rotation unavailable"})

    async def sector_rotation_market_intraday(self, market: str, indices: list[str] | None = None) -> dict:
        from app.market_pulse.sector_rotation_markets import (
            CRYPTO_BENCHMARK_SYMBOL,
            CRYPTO_SECTOR_SYMBOLS,
            US_BENCHMARK_SYMBOL,
            US_SPDR_SECTORS,
            compute_market_sector_rotation_intraday,
        )

        catalog = CRYPTO_SECTOR_SYMBOLS if market == "crypto" else US_SPDR_SECTORS
        benchmark = CRYPTO_BENCHMARK_SYMBOL if market == "crypto" else US_BENCHMARK_SYMBOL
        names = [n for n in (indices or list(catalog.keys())) if n in catalog]
        instruments = tuple((n, catalog[n]) for n in names)

        def _fetch():
            return compute_market_sector_rotation_intraday(instruments, benchmark, 15, 4, 5, market)

        return json_safe(await asyncio.to_thread(_fetch) or {"error": "Intraday rotation unavailable"})

    async def stock_rotation_market(
        self, market: str, universe_id: str, tf_key: str = "1d", lookback_bars: int = 5
    ) -> dict:
        """Stock/pair price rotation for 'us' or 'crypto' — India uses stock_rotation()."""

        def _fetch():
            if market == "crypto":
                from app.market_pulse.sector_rotation_markets import (
                    CRYPTO_SECTOR_FILTER_GROUPS,
                    CRYPTO_SECTOR_SYMBOLS,
                )
                from app.market_pulse.stock_price_rotation_markets import compute_crypto_price_rotation

                names = CRYPTO_SECTOR_FILTER_GROUPS.get(universe_id, list(CRYPTO_SECTOR_SYMBOLS.keys()))
                instruments = tuple((n, CRYPTO_SECTOR_SYMBOLS[n]) for n in names if n in CRYPTO_SECTOR_SYMBOLS)
                return compute_crypto_price_rotation(universe_id, instruments, tf_key, lookback_bars)

            from app.market_pulse.stock_price_rotation_markets import (
                _US_INDEX_CATALOG,
                compute_us_stock_price_rotation,
            )

            entry = next((e for e in _US_INDEX_CATALOG if e["id"] == universe_id), None)
            if not entry:
                return {"error": f"Unknown universe '{universe_id}'"}
            symbols = tuple(entry["fetch"]())
            return compute_us_stock_price_rotation(universe_id, symbols, tf_key, lookback_bars)

        return json_safe(await asyncio.to_thread(_fetch) or {"error": "No rotation data", "inflow": [], "outflow": []})

    async def rotation_universes(self, market: str) -> dict:
        """List available universe ids/labels for stock_rotation_market()."""
        if market == "crypto":
            from app.market_pulse.sector_rotation_markets import CRYPTO_SECTOR_FILTER_GROUPS

            return {"universes": [{"id": k, "label": k} for k in CRYPTO_SECTOR_FILTER_GROUPS]}
        from app.market_pulse.stock_price_rotation_markets import _US_INDEX_CATALOG

        return {"universes": [{"id": e["id"], "label": e["label_fn"]()} for e in _US_INDEX_CATALOG]}

    async def opposite_hedge(self, capital: float = 100_000.0, mode: str = "index") -> dict:
        import app.market_pulse.opposite_hedge_mtf_engine as eng

        try:
            htf = await self.sector_rotation()
            intraday = await self.sector_rotation_intraday()

            def _fetch():
                return eng.compute_opposite_hedge_mtf(
                    intraday if isinstance(intraday, dict) and "error" not in intraday else None,
                    htf if isinstance(htf, dict) and "error" not in htf else None,
                    capital=capital,
                    mode=mode,
                )

            result = await asyncio.to_thread(_fetch)
            return json_safe(result or {"error": "No hedge plans"})
        except Exception as e:
            return json_safe({"error": str(e), "plans": [], "consensus": None})

    async def mtf_bias(self, tickers: list[str], *, is_crypto: bool = False) -> dict:
        import app.market_pulse.mtf_intraday_bias_engine as eng

        token = "" if is_crypto else await self._groww_token()

        def _fetch():
            set_groww_token(token)
            try:
                return eng.analyze_universe(list(tickers), is_crypto=is_crypto)
            except Exception as e:
                return {"error": str(e), "bullish": [], "bearish": [], "errors": []}

        return json_safe(await asyncio.to_thread(_fetch))

    async def accurate_strategy(
        self,
        tickers: list[str],
        *,
        timeframe: str = "1h",
        min_confluence: float = 60.0,
        rr_target: float = 2.0,
        market: str = "India (Groww)",
    ) -> dict:
        from app.market_pulse.gap_trading import fetch_data_for_gap_scan
        from app.market_pulse.ticker_utils import market_currency
        from app.market_pulse.zireman_confluence_engine import (
            run_strategy,
            serialize_result,
            signal_to_dict,
        )

        bar_limits = {"15m": 400, "1h": 350, "4h": 280, "1d": 220}
        bar_limit = bar_limits.get(timeframe, 300)
        token = await self._groww_token()
        exchange = await self._exchange()

        def _fetch():
            set_groww_token(token)
            results = []
            for ticker in tickers:
                try:
                    df = fetch_data_for_gap_scan(
                        ticker, timeframe, market, token, exchange, limit=bar_limit,
                    )
                    if df is None or df.empty or len(df) < 80:
                        results.append({"ticker": ticker, "error": "Insufficient OHLCV bars"})
                        continue
                    df.columns = [str(c).lower() for c in df.columns]
                    result = run_strategy(df, min_confluence=min_confluence, rr_target=rr_target)
                    currency = market_currency(market)
                    payload = {
                        "ticker": ticker,
                        "market": market,
                        "timeframe": timeframe,
                        "min_confluence": min_confluence,
                        "rr_target": rr_target,
                        "currency": currency,
                        **serialize_result(result, currency=currency),
                    }
                    if result.get("latest_signal"):
                        payload["latest_signal"] = signal_to_dict(
                            result["latest_signal"], currency=currency,
                        )
                    payload["summary"] = result.get("summary") or {}
                    results.append(payload)
                except Exception as exc:
                    results.append({"ticker": ticker, "error": str(exc)[:200]})
            actionable = [
                r for r in results
                if not r.get("error") and r.get("latest_signal")
            ]
            return {
                "results": results,
                "actionable": actionable,
                "entry_count": len(actionable),
                "strategy": "Accurate Strategy — OB + FVG + S/R",
            }

        return json_safe(await asyncio.to_thread(_fetch))

    async def pump_dump_breakout(
        self,
        tickers: list[str],
        *,
        timeframe: str = "15m",
        market: str = "India (Groww)",
        initial_balance: float = 1000.0,
    ) -> dict:
        from app.market_pulse.gap_trading import fetch_data_for_gap_scan
        from app.market_pulse.pump_dump_breakout_engine import StrategyConfig, run_analysis

        token = await self._groww_token()
        exchange = await self._exchange()
        bar_limits = {"5m": 500, "15m": 400, "1h": 350, "4h": 280, "1d": 220}
        bar_limit = bar_limits.get(timeframe, 400)

        def _fetch():
            set_groww_token(token)
            cfg = StrategyConfig()
            results = []
            for ticker in tickers:
                try:
                    df = fetch_data_for_gap_scan(
                        ticker, timeframe, market, token, exchange, limit=bar_limit,
                    )
                    if df is None or df.empty:
                        results.append({"symbol": ticker, "error": "No OHLCV data"})
                        continue
                    payload = run_analysis(
                        df,
                        symbol=ticker,
                        config=cfg,
                        initial_balance=initial_balance,
                        timeframe=timeframe,
                    )
                    results.append(payload)
                except Exception as exc:
                    results.append({"symbol": ticker, "error": str(exc)[:200]})
            live_setups = [
                r for r in results
                if not r.get("error") and (r.get("live") or {}).get("latest_signal")
            ]
            return {
                "results": results,
                "entries": live_setups,
                "entry_count": len(live_setups),
                "strategy": "Pump/Dump Breakout",
            }

        return json_safe(await asyncio.to_thread(_fetch))

    async def big_whale_pump_dump(self) -> dict:
        from app.market_pulse.big_whale_pump_dump_engine import run_big_whale_scan

        def _fetch():
            try:
                return run_big_whale_scan()
            except Exception as e:
                return {"error": str(e), "pumped": [], "big_trades": [], "trade_recommendations": []}

        return json_safe(await asyncio.to_thread(_fetch))

    async def week52(self, index_name: str) -> dict:
        import app.market_pulse.week52_high_low as w52

        attach_clear_stubs(w52)
        token = await self._groww_token()

        def _fetch():
            set_groww_token(token)
            try:
                return w52.scan_market_52w_extremes(index_name)
            except Exception as e:
                return {"error": str(e), "at_52w_high": [], "at_52w_low": []}

        return json_safe(await asyncio.to_thread(_fetch) or {"error": "52-week scan failed"})

    async def heatmap(self, timeframe: str = "1d", mode: str = "sectoral") -> dict:
        import app.market_pulse.heatmap as hm

        token = await self._groww_token()
        exchange = await self._exchange()

        def _fetch():
            try:
                if mode == "custom":
                    # Custom mode falls back to the full sectoral heatmap (no empty stub).
                    return hm.generate_groww_sectoral_heatmap(token, exchange, timeframe)
                return hm.generate_groww_sectoral_heatmap(token, exchange, timeframe)
            except Exception:
                return []

        set_groww_token(token)
        rows = await asyncio.to_thread(_fetch)
        return json_safe({"timeframe": timeframe, "mode": mode, "rows": rows or []})

    async def commodity_screener(self, timeframes: list[str] | None = None) -> dict:
        import app.market_pulse.commodity_screener_engine as eng

        tfs = tuple(timeframes or ["1 day", "1 week"])

        def _fetch():
            try:
                payload = eng.scan_commodity_screener(tfs)
                if not payload:
                    return {"error": "Commodity scan failed", "commodities": []}
                payload.pop("crypto_signals", None)
                payload.pop("us_signals", None)
                return payload
            except Exception as e:
                return {"error": str(e), "commodities": []}

        return json_safe(await asyncio.to_thread(_fetch))

    async def tomorrow_outlook(self) -> dict:
        payload = await self.intelligence()
        outlook = payload.get("tomorrow_outlook") or {}
        if not outlook:
            return {"error": "Tomorrow outlook unavailable"}
        return json_safe(outlook)

    async def sentiment_screener(
        self,
        tickers: list[str],
        timeframes: list[str] | None = None,
        lookback_days: int = 120,
    ) -> dict:
        import app.market_pulse.sentiment_screener_engine as eng
        from app.market_pulse.ticker_utils import GROWW_MARKET

        tfs = timeframes or ["1d", "4h"]
        token = await self._groww_token()
        exchange = await self._exchange()

        def _wrapped():
            set_groww_token(token)
            try:
                return eng.run_sentiment_screener(
                    list(tickers),
                    tfs,
                    market=GROWW_MARKET,
                    groww_token=token,
                    exchange=exchange,
                    lookback_days=lookback_days,
                )
            except Exception as e:
                return {"error": str(e), "rows": []}

        return json_safe(await asyncio.to_thread(_wrapped))

    async def mtf_scanner(self, tickers: list[str], timeframes: list[str] | None = None) -> dict:
        import app.market_pulse.mtf_scanner_engine as eng
        from app.market_pulse.ticker_utils import GROWW_MARKET

        tfs = timeframes or ["15m", "1h", "4h", "1d"]
        token = await self._groww_token()
        exchange = await self._exchange()

        def _wrapped():
            set_groww_token(token)
            try:
                results = eng.run_mtf_scan(
                    list(tickers),
                    tfs,
                    GROWW_MARKET,
                    groww_token=token,
                    exchange=exchange,
                )
                return {"timeframes": tfs, "results": results}
            except Exception as e:
                return {"error": str(e), "results": {}}

        return json_safe(await asyncio.to_thread(_wrapped))

    async def ticker_investigation(self, tickers: list[str], *, asset_class: str = "india") -> dict:
        import app.market_pulse.ticker_investigation_engine as eng

        token = await self._groww_token()

        def _wrapped():
            set_groww_token(token)
            try:
                payload = eng.run_ticker_investigation(
                    asset_class,
                    list(tickers),
                    groww_token=token,
                )
                return payload or {"error": "Investigation failed", "results": []}
            except Exception as e:
                return {"error": str(e), "results": []}

        return json_safe(await asyncio.to_thread(_wrapped))

    async def index_options(self) -> dict:
        import app.market_pulse.week52_high_low as w52
        import app.market_pulse.news_scanner as ns

        attach_clear_stubs(ns)
        breadth = await asyncio.to_thread(ns.fetch_nse_market_breadth)
        groups = w52._get_index_names_by_group(breadth)
        flat = []
        for group, names in groups.items():
            for name in names:
                flat.append({"group": group, "name": name})
        return {"indices": flat}
