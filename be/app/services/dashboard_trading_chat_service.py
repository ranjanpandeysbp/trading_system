"""Dashboard Trading Chat — BB + confluence; optional Deep mode (backtest → Strategies catalog → live)."""

from __future__ import annotations

import logging
from typing import Any

from app.market_pulse.dashboard_trading_chat_engine import (
    DEEP_CHAT_SYSTEM,
    PRO_TRADE_LIVE_IDS,
    SCREEN_CHAT_SYSTEM,
    TRADING_CHAT_SYSTEM,
    all_extra_checks,
    build_chat_ai_context,
    build_deep_ai_context,
    build_screen_ai_context,
    compact_break_pick,
    compact_mover_pick,
    compact_pick,
    compact_scan_signal,
    default_mover_index,
    default_universe,
    is_screen_mode,
    load_strategy_guides,
    merge_live_picks,
    parse_intent,
    rank_picks,
    select_deep_candidates,
    summarize_strategy_ranking,
)
from app.market_pulse.serialize import json_safe
from app.services.ai_service import AIService
from app.services.pro_trade_service import ProTradeService
from app.services.settings_service import SettingsService
from app.services.ticker_universe_service import TickerUniverseService
from app.strategies.registry import ALL_STRATEGIES, default_backtest_period

logger = logging.getLogger(__name__)


class DashboardTradingChatService:
    def __init__(self, settings: SettingsService, db: Any = None):
        self.settings = settings
        self.db = db
        self.pro = ProTradeService(settings, db=db)
        self.ai = AIService(settings)
        self.universe = TickerUniverseService()

    def _resolve_named_tickers(self, asset_class: str, raw: list[str]) -> list[str]:
        if not raw:
            return []
        return self.universe.resolve(asset_class, raw)[:8]

    async def chat(
        self,
        *,
        message: str,
        asset_class: str | None = None,
        style: str | None = None,
        tickers: list[str] | None = None,
        extra_checks: list[str] | None = None,
        top_n: int | None = None,
        skip_ai: bool = False,
        deep_mode: bool = False,
    ) -> dict[str, Any]:
        # Peek intent — open screens (movers / S&R breaks) bypass BB / deep backtest
        peek = parse_intent(message, asset_class=asset_class, style=style, tickers=tickers)
        if is_screen_mode(str(peek.get("mode") or "")):
            return await self._chat_screen(
                message=message,
                asset_class=asset_class,
                style=style,
                tickers=tickers,
                top_n=top_n,
                skip_ai=skip_ai,
                deep_mode=deep_mode,
            )
        if deep_mode:
            return await self._chat_deep(
                message=message,
                asset_class=asset_class,
                style=style,
                tickers=tickers,
                extra_checks=extra_checks,
                top_n=top_n,
                skip_ai=skip_ai,
            )
        return await self._chat_standard(
            message=message,
            asset_class=asset_class,
            style=style,
            tickers=tickers,
            extra_checks=extra_checks,
            top_n=top_n,
            skip_ai=skip_ai,
        )

    async def _chat_screen(
        self,
        *,
        message: str,
        asset_class: str | None,
        style: str | None,
        tickers: list[str] | None,
        top_n: int | None,
        skip_ai: bool,
        deep_mode: bool,
    ) -> dict[str, Any]:
        """Answer movers / broken S/R open questions via Command Center screens."""
        from app.services.command_center_service import CommandCenterService

        intent = parse_intent(message, asset_class=asset_class, style=style, tickers=tickers)
        mode = str(intent["mode"])
        ac = str(intent["asset_class"])
        tf = str(intent["timeframe"])
        cc = CommandCenterService(self.settings, db=self.db)

        picks: list[dict[str, Any]] = []
        source = ""
        scan_tickers: list[str] = []

        try:
            if mode in ("movers_24h", "gainers", "fallen_most"):
                picks, source, scan_tickers = await self._screen_movers(cc, intent, top_n=top_n)
            else:
                picks, source, scan_tickers = await self._screen_breaks(cc, intent, top_n=top_n)
        except Exception as exc:
            logger.exception("Trading Agent screen failed")
            return {
                "error": f"Screen failed: {exc}",
                "intent": intent,
                "mode": mode,
                "picks": [],
                "ai": None,
                "deep_mode": deep_mode,
            }

        # Optional deep enrich: BB on top movers only (small set)
        if deep_mode and picks:
            try:
                enrich_syms = [str(p.get("ticker")) for p in picks[:5] if p.get("ticker")]
                if enrich_syms:
                    bb = await self.pro.bb_mean_reversion(
                        enrich_syms,
                        asset_class=ac,
                        timeframes=[tf],
                        cfg_overrides={"extra_checks": all_extra_checks()},
                    )
                    by_t = {
                        str(r.get("ticker")): r
                        for r in (bb.get("results") or [])
                        if isinstance(r, dict) and r.get("ticker")
                    }
                    for p in picks:
                        r = by_t.get(str(p.get("ticker")))
                        if not r:
                            continue
                        if r.get("sl_pct") is not None:
                            p["sl_pct"] = r.get("sl_pct")
                        if r.get("tp_pct") is not None:
                            p["tp_pct"] = r.get("tp_pct")
                        if r.get("plain_english"):
                            p["reasons"] = list(p.get("reasons") or []) + [str(r.get("plain_english"))[:180]]
            except Exception:
                logger.exception("Deep enrich on screen picks failed")

        ai_payload = None
        if not skip_ai:
            ctx = build_screen_ai_context(intent, picks, source=source)
            try:
                ai_payload = await self.ai.ask(
                    context=ctx,
                    question=f"Answer the user's open market question. User asked: {message}",
                    system_prompt=SCREEN_CHAT_SYSTEM,
                    section="dashboard/trading-chat-screen",
                    max_tokens=3500,
                    mode="ask",
                )
            except Exception as exc:
                logger.exception("Screen AI failed")
                ai_payload = {
                    "report": f"AI conclusion unavailable: {exc}. Screen results below still apply.",
                    "verdict": None,
                    "confidence_pct": None,
                    "provider": None,
                    "model": None,
                    "error": True,
                }

        summary_lines = [f"Screen ({mode}) · {source} · {len(picks)} eligible:"]
        for p in picks:
            summary_lines.append(
                f"{p.get('rank')}. {p.get('ticker')} — {p.get('action')} ({p.get('side')}) · "
                f"{p.get('confidence_pct') or '—'}% · {p.get('reason')}"
            )

        payload = self._pack_response(
            intent=intent,
            mode=mode,
            ac=ac,
            tf=tf,
            scan_tickers=scan_tickers,
            checks=[],
            picks=picks,
            ai_payload=ai_payload,
            bb_entry_count=len(picks),
            disclaimer="Research / education only — not financial advice. Movers/breaks are screens, not auto-trades.",
            scanned=len(scan_tickers) or len(picks),
            deep_mode=deep_mode,
        )
        payload["summary"] = "\n".join(summary_lines)
        payload["screen_source"] = source
        payload["how_to_read"] = [
            "Open question screen: market movers (24h / session) or recent support/resistance breaks.",
            "BUY/SELL here tags direction of the move or break — not a full BB trade plan unless Deep enrich added SL/TP.",
            "AI conclusion uses Manage → AI Settings.",
            "Research / education only — not financial advice.",
        ]
        return json_safe(payload)

    async def _screen_movers(
        self,
        cc: Any,
        intent: dict[str, Any],
        *,
        top_n: int | None,
    ) -> tuple[list[dict[str, Any]], str, list[str]]:
        mode = str(intent["mode"])
        ac = str(intent["asset_class"])
        picks: list[dict[str, Any]] = []
        source = "market_movers"
        scan_tickers: list[str] = []

        if ac == "crypto":
            data = await cc.coindcx_24h_volatility()
            rows = list(data.get("rows") or [])
            source = "CoinDCX 24h"
            norm: list[dict[str, Any]] = []
            for r in rows:
                if not isinstance(r, dict):
                    continue
                pct = r.get("percent_change")
                try:
                    pct_f = float(pct) if pct is not None else None
                except (TypeError, ValueError):
                    pct_f = None
                if pct_f is None:
                    continue
                norm.append({
                    "symbol": r.get("ticker") or r.get("pair"),
                    "pct": pct_f,
                    "last": r.get("price"),
                })
            gainers = sorted([x for x in norm if x["pct"] >= 0], key=lambda x: -x["pct"])
            losers = sorted([x for x in norm if x["pct"] < 0], key=lambda x: x["pct"])
        else:
            index = default_mover_index(ac)
            # Gold/silver-specific questions can narrow commodity index when available
            raw = str(intent.get("raw_message") or "").lower()
            if ac == "commodity" and "gold" in raw and "silver" not in raw:
                index = "Gold Spot"
            elif ac == "commodity" and "silver" in raw and "gold" not in raw:
                index = "Silver Spot"
            data = await cc.market_movers(ac, index, "1d")
            source = str(data.get("source") or f"market_movers:{index}:1d")
            gainers = [x for x in (data.get("gainers") or []) if isinstance(x, dict)]
            losers = [x for x in (data.get("losers") or []) if isinstance(x, dict)]

        if mode == "gainers":
            ordered = [(g, "BUY") for g in gainers]
        elif mode == "fallen_most":
            ordered = [(g, "SELL") for g in losers]
        else:
            # movers_24h — merge by abs pct
            merged = [(g, "BUY") for g in gainers] + [(g, "SELL") for g in losers]
            merged.sort(key=lambda pair: -abs(float(pair[0].get("pct") or 0)))
            ordered = merged

        if top_n is not None:
            ordered = ordered[:top_n]

        for i, (row, side) in enumerate(ordered):
            picks.append(compact_mover_pick(row, rank=i + 1, side=side, source=source))
            if row.get("symbol"):
                scan_tickers.append(str(row["symbol"]))

        return picks, source, scan_tickers

    async def _screen_breaks(
        self,
        cc: Any,
        intent: dict[str, Any],
        *,
        top_n: int | None,
    ) -> tuple[list[dict[str, Any]], str, list[str]]:
        import asyncio

        mode = str(intent["mode"])
        ac = str(intent["asset_class"])
        tf = str(intent.get("timeframe") or "15m")
        want = "SUPPORT_BREAKDOWN" if mode == "broken_support" else "RESISTANCE_BREAKOUT"

        named = list(intent.get("tickers") or [])
        if named:
            universe = self._resolve_named_tickers(ac, named)
        else:
            universe = default_universe(ac, limit=20)

        async def _one(sym: str) -> dict[str, Any]:
            try:
                return await cc.trade_setup_support_resistance(sym, asset_class=ac, timeframe=tf)
            except Exception as exc:
                return {"ticker": sym, "error": str(exc)[:200]}

        results = await asyncio.gather(*[_one(s) for s in universe])
        picks: list[dict[str, Any]] = []
        for r in results:
            if not isinstance(r, dict):
                continue
            bo = r.get("breakout") or {}
            if str(bo.get("event") or "").upper() != want:
                continue
            cp = compact_break_pick(r)
            if cp:
                picks.append(cp)

        # Prefer volume-confirmed first
        picks.sort(
            key=lambda p: (
                0 if "volume confirmed" in str(p.get("reason") or "") else 1,
                -(p.get("confidence_pct") or 0),
            )
        )
        if top_n is not None:
            picks = picks[:top_n]
        for i, p in enumerate(picks):
            p["rank"] = i + 1

        source = f"trade_setup_support_resistance:{tf}"
        return picks, source, universe

    async def _chat_standard(
        self,
        *,
        message: str,
        asset_class: str | None,
        style: str | None,
        tickers: list[str] | None,
        extra_checks: list[str] | None,
        top_n: int | None,
        skip_ai: bool,
    ) -> dict[str, Any]:
        intent = parse_intent(message, asset_class=asset_class, style=style, tickers=tickers)
        checks = list(extra_checks) if extra_checks else all_extra_checks()
        intent["extra_checks"] = checks

        ac = str(intent["asset_class"])
        tf = str(intent["timeframe"])
        mode = str(intent["mode"])

        if mode == "single" and intent.get("tickers"):
            scan_tickers = self._resolve_named_tickers(ac, list(intent["tickers"]))
        else:
            mode = "top_picks"
            intent["mode"] = mode
            scan_tickers = default_universe(ac, limit=50)

        if not scan_tickers:
            return {"error": "Could not resolve any tickers for this question.", "intent": intent, "picks": [], "ai": None}

        scan_tickers = scan_tickers if mode == "top_picks" else scan_tickers[:8]

        try:
            bb = await self.pro.bb_mean_reversion(
                scan_tickers,
                asset_class=ac,
                timeframes=[tf],
                cfg_overrides={"extra_checks": checks},
            )
        except Exception as exc:
            logger.exception("Dashboard trading chat BB scan failed")
            return {"error": f"Scan failed: {exc}", "intent": intent, "picks": [], "ai": None}

        results = list(bb.get("results") or [])
        if mode == "single":
            picks = [compact_pick(r, rank=i + 1) for i, r in enumerate(results)]
            picks = sorted(picks, key=lambda p: (0 if p.get("take_trade") else 1, -(p.get("confidence_pct") or 0)))
            eligible = [p for p in picks if p.get("take_trade")]
            picks = eligible if eligible else picks
            if top_n is not None:
                picks = picks[:top_n]
            for i, p in enumerate(picks):
                p["rank"] = i + 1
        else:
            picks = rank_picks(results, top_n=top_n, action_bias=str(intent.get("action_bias") or "both"))

        ai_payload = await self._conclude_ai(
            intent=intent,
            picks=picks,
            message=message,
            skip_ai=skip_ai,
            deep=False,
            ranking=None,
            selected=None,
        )

        return json_safe(self._pack_response(
            intent=intent,
            mode=mode,
            ac=ac,
            tf=tf,
            scan_tickers=scan_tickers,
            checks=checks,
            picks=picks,
            ai_payload=ai_payload,
            bb_entry_count=bb.get("entry_count"),
            disclaimer=bb.get("disclaimer"),
            scanned=len(results),
            deep_mode=False,
        ))

    async def _chat_deep(
        self,
        *,
        message: str,
        asset_class: str | None,
        style: str | None,
        tickers: list[str] | None,
        extra_checks: list[str] | None,
        top_n: int | None,
        skip_ai: bool,
    ) -> dict[str, Any]:
        intent = parse_intent(message, asset_class=asset_class, style=style, tickers=tickers)
        checks = list(extra_checks) if extra_checks else all_extra_checks()
        intent["extra_checks"] = checks
        intent["deep_mode"] = True

        ac = str(intent["asset_class"])
        tf = str(intent["timeframe"])
        mode = str(intent["mode"])
        style_key = str(intent.get("style") or "intraday")

        if mode == "single" and intent.get("tickers"):
            scan_tickers = self._resolve_named_tickers(ac, list(intent["tickers"]))
        else:
            mode = "top_picks"
            intent["mode"] = mode
            # Broader universe so more eligible live picks can surface after ranking
            scan_tickers = default_universe(ac, limit=20)

        if not scan_tickers:
            return {"error": "Could not resolve any tickers for this question.", "intent": intent, "picks": [], "ai": None, "deep_mode": True}

        # Backtest on a subset for latency; live-scan the fuller list
        bt_tickers = scan_tickers[:8] if mode == "top_picks" else scan_tickers[:5]
        live_tickers = scan_tickers if mode == "top_picks" else scan_tickers[:5]

        candidates = select_deep_candidates(style_key, message, limit=10)
        candidate_meta = []
        from app.strategies.registry import get_strategy_meta
        for sid in candidates:
            meta = get_strategy_meta(sid) or {}
            candidate_meta.append({
                "id": sid,
                "label": meta.get("name") or sid.replace("_", " ").title(),
                "category": meta.get("category") or meta.get("category_label") or "",
            })

        action_bias = str(intent.get("action_bias") or "both")
        direction = "long_only" if action_bias == "buy" else "short_only" if action_bias == "sell" else "both"
        period = default_backtest_period(tf)

        # --- 1) Backtest rank ---
        ranking: list[dict[str, Any]] = []
        bt_rows: list[dict[str, Any]] = []
        bt_error: str | None = None
        try:
            from app.services.backtester_leaderboard_service import BacktesterLeaderboardService

            bt = await BacktesterLeaderboardService(self.settings, self.db).run(
                tickers=bt_tickers,
                strategy_ids=candidates,
                asset_class=ac,
                timeframe=tf,
                period=period,
                direction=direction,
                bars=220,
            )
            bt_rows = list(bt.get("rows") or [])
            ranking = summarize_strategy_ranking(bt_rows, top_n=None)
        except Exception as exc:
            logger.exception("Deep mode backtest failed")
            bt_error = str(exc)[:300]
            ranking = [{"rank": i + 1, "strategy_id": sid, "strategy_label": sid, "avg_rank_score": 0,
                        "note": "backtest unavailable — using style defaults"} for i, sid in enumerate(candidates[:5])]

        top_strategy_ids = [str(r["strategy_id"]) for r in ranking[:3]] or candidates[:3]

        # --- 2) Strategies catalog details (http://…/strategies → /api/v1/strategies) ---
        import asyncio

        selected = await asyncio.to_thread(load_strategy_guides, top_strategy_ids)

        # --- 3) Live analysis on winners ---
        pick_lists: list[list[dict[str, Any]]] = []

        # Always run BB with full confluence as desk baseline
        try:
            bb = await self.pro.bb_mean_reversion(
                live_tickers,
                asset_class=ac,
                timeframes=[tf],
                cfg_overrides={"extra_checks": checks},
            )
            bb_results = list(bb.get("results") or [])
            bb_picks = [compact_pick(r) for r in bb_results]
            for p in bb_picks:
                p["strategy_id"] = "bb_mean_reversion"
                p["strategy_label"] = "BB Mean Reversion"
            pick_lists.append(bb_picks)
            bb_entry_count = bb.get("entry_count")
            disclaimer = bb.get("disclaimer")
        except Exception as exc:
            logger.exception("Deep mode BB live failed")
            bb_entry_count = 0
            disclaimer = None
            bt_error = (bt_error or "") + f" | BB live: {exc}"

        rule_ids = [sid for sid in top_strategy_ids if sid in ALL_STRATEGIES]
        hub_ids = [
            sid for sid in top_strategy_ids
            if sid not in ALL_STRATEGIES and sid not in PRO_TRADE_LIVE_IDS and sid != "elliott_wave_pro"
        ]
        pro_ids = [sid for sid in top_strategy_ids if sid in PRO_TRADE_LIVE_IDS or sid == "elliott_wave_pro"]

        if rule_ids:
            try:
                from app.models.schemas import ScanRequest
                from app.services.scanner_service import ScannerService

                signals = await ScannerService(self.settings).scan(
                    ScanRequest(
                        tickers=live_tickers,
                        strategies=rule_ids,
                        timeframes=[tf if tf in ("1m", "3m", "5m", "15m", "1d") else ("15m" if style_key in ("scalping", "intraday") else "1d")],
                        asset_class=ac,  # type: ignore[arg-type]
                    )
                )
                pick_lists.append([compact_scan_signal(s) for s in signals])
            except Exception:
                logger.exception("Deep mode scanner live failed")

        if hub_ids:
            try:
                from app.services.trading_hub_service import TradingHubService

                hubs = TradingHubService(self.settings, db=self.db)
                for sid in hub_ids[:2]:
                    try:
                        payload = await hubs.scan(sid, live_tickers, asset_class=ac)
                        entries = list(payload.get("entries") or payload.get("results") or [])
                        hub_picks = []
                        for e in entries:
                            live = e.get("live") if isinstance(e, dict) else None
                            src = live if isinstance(live, dict) else (e if isinstance(e, dict) else {})
                            if not src:
                                continue
                            # Normalize hub live schema toward compact_pick fields
                            fake = {
                                "ticker": src.get("ticker") or e.get("ticker"),
                                "timeframe": src.get("timeframe") or tf,
                                "take_trade": bool(src.get("take_trade") or src.get("action") in ("BUY", "SELL", "LONG", "SHORT")),
                                "direction": src.get("direction") or (
                                    "LONG" if str(src.get("action") or "").upper() in ("BUY", "LONG") else
                                    "SHORT" if str(src.get("action") or "").upper() in ("SELL", "SHORT") else "NONE"
                                ),
                                "confidence_pct": src.get("confidence_pct") or src.get("confidence"),
                                "sl_pct": src.get("sl_pct"),
                                "tp_pct": src.get("tp_pct"),
                                "entry_price": src.get("entry_price") or src.get("ltp") or src.get("price"),
                                "stop_price": src.get("stop_price"),
                                "target_price": src.get("target_price"),
                                "plain_english": src.get("plain_english") or src.get("verdict") or src.get("rationale"),
                                "verdict": src.get("verdict"),
                                "confidence_reasons": src.get("confidence_reasons") or [],
                                "error": src.get("error"),
                            }
                            cp = compact_pick(fake)
                            cp["strategy_id"] = sid
                            cp["strategy_label"] = sid.replace("_", " ").title()
                            hub_picks.append(cp)
                        if hub_picks:
                            pick_lists.append(hub_picks)
                    except Exception:
                        logger.exception("Deep mode hub %s failed", sid)
            except Exception:
                logger.exception("Deep mode hub service failed")

        for sid in pro_ids:
            if sid == "bb_mean_reversion":
                continue  # already ran
            try:
                live = await self._run_pro_live(sid, live_tickers, ac, tf, checks)
                if live:
                    pick_lists.append(live)
            except Exception:
                logger.exception("Deep mode pro live %s failed", sid)

        picks = merge_live_picks(pick_lists, top_n=top_n)
        if mode == "single" and picks:
            # Prefer named tickers
            named = set(live_tickers)
            named_picks = [p for p in picks if p.get("ticker") in named]
            if named_picks:
                picks = named_picks
                for i, p in enumerate(picks):
                    p["rank"] = i + 1

        ai_payload = await self._conclude_ai(
            intent=intent,
            picks=picks,
            message=message,
            skip_ai=skip_ai,
            deep=True,
            ranking=ranking,
            selected=selected,
        )

        summary_parts = []
        if ranking:
            summary_parts.append("Best strategies (backtest):")
            for r in ranking:
                summary_parts.append(
                    f"  {r.get('rank')}. {r.get('strategy_label')} — score {r.get('avg_rank_score')} · "
                    f"ret {r.get('avg_return_pct')}% · win {r.get('avg_win_rate_pct')}%"
                )
        summary_parts.append(f"Live picks ({len(picks)} eligible):")
        for p in picks:
            summary_parts.append(
                f"{p.get('rank')}. {p.get('ticker')} — {p.get('action')} ({p.get('side')}) · "
                f"{p.get('confidence_pct') or '—'}% · SL {p.get('sl_pct') or '—'}% · TP {p.get('tp_pct') or '—'}% · "
                f"[{p.get('strategy_id') or '—'}] {p.get('reason')}"
            )

        payload = self._pack_response(
            intent=intent,
            mode=mode,
            ac=ac,
            tf=tf,
            scan_tickers=live_tickers,
            checks=checks,
            picks=picks,
            ai_payload=ai_payload,
            bb_entry_count=bb_entry_count,
            disclaimer=disclaimer,
            scanned=len(live_tickers) * max(len(candidates), 1),
            deep_mode=True,
        )
        payload.update({
            "summary": "\n".join(summary_parts),
            "candidate_strategies": candidate_meta,
            "strategy_ranking": ranking,
            "selected_strategies": selected,
            "backtest_period": period,
            "backtest_error": bt_error,
            "how_to_read": [
                "Deep mode: (1) pick strategies for your question (2) backtest-rank them "
                "(3) load Strategies catalog how-to from /strategies (4) live-scan winners "
                "(5) Manage AI conclusion.",
                "Strategy ranking uses Backtester leaderboard rank_score (return × sample factor).",
                "Live picks merge BB Mean Reversion + winning rule/hub/pro engines.",
                "Research / education only — not financial advice.",
            ],
        })
        return json_safe(payload)

    async def _run_pro_live(
        self,
        sid: str,
        tickers: list[str],
        asset_class: str,
        timeframe: str,
        checks: list[str],
    ) -> list[dict[str, Any]]:
        method_map = {
            "bb_mean_reversion": "bb_mean_reversion",
            "pa_vp_smc": "pa_vp_smc",
            "pa_volume_profile": "pa_volume_profile",
            "volume_profile_ce": "volume_profile_ce",
            "volume_profile_poc": "volume_profile_poc",
            "volume_spread_next_candle": "volume_spread_next_candle",
            "elliott_wave_pro": "elliott_wave",
            "elliott_wave": "elliott_wave",
        }
        method = method_map.get(sid)
        if not method:
            return []
        fn = getattr(self.pro, method, None)
        if not fn:
            return []

        kwargs: dict[str, Any] = {"asset_class": asset_class}
        if method == "bb_mean_reversion":
            kwargs["timeframes"] = [timeframe]
            kwargs["cfg_overrides"] = {"extra_checks": checks}
        elif method in ("pa_vp_smc", "pa_volume_profile", "volume_profile_ce", "volume_profile_poc",
                        "volume_spread_next_candle", "elliott_wave"):
            # Most pro methods accept timeframes or cfg — pass lightly
            try:
                payload = await fn(tickers, **kwargs, timeframes=[timeframe])
            except TypeError:
                try:
                    payload = await fn(tickers, **kwargs)
                except TypeError:
                    payload = await fn(tickers, asset_class=asset_class)
            results = list(payload.get("results") or payload.get("entries") or [])
            out = []
            for r in results:
                if not isinstance(r, dict):
                    continue
                cp = compact_pick(r)
                cp["strategy_id"] = sid
                cp["strategy_label"] = sid.replace("_", " ").title()
                out.append(cp)
            return out

        payload = await fn(tickers, **kwargs)
        results = list(payload.get("results") or [])
        out = []
        for r in results:
            if not isinstance(r, dict):
                continue
            cp = compact_pick(r)
            cp["strategy_id"] = sid
            cp["strategy_label"] = sid.replace("_", " ").title()
            out.append(cp)
        return out

    async def _conclude_ai(
        self,
        *,
        intent: dict[str, Any],
        picks: list[dict[str, Any]],
        message: str,
        skip_ai: bool,
        deep: bool,
        ranking: list[dict[str, Any]] | None,
        selected: list[dict[str, Any]] | None,
    ) -> dict[str, Any] | None:
        if skip_ai:
            return None
        if not picks and not (deep and ranking):
            cfg = await self.ai.provider_config()
            return {
                "report": "No live picks to conclude on. Try another asset class or style.",
                "verdict": None,
                "confidence_pct": None,
                "provider": cfg.get("provider"),
                "model": cfg.get("model"),
                "error": False,
            }

        if deep:
            ctx = build_deep_ai_context(intent, ranking=ranking or [], selected=selected or [], picks=picks)
            sys = DEEP_CHAT_SYSTEM
            q = (
                "Deep mode: name best strategies from the backtest, cite Strategies catalog briefly, "
                f"then BUY/SELL/WAIT per ticker with %confidence %SL %TP. User asked: {message}"
            )
            mode = "ask"
        else:
            ctx = build_chat_ai_context(intent, picks)
            sys = TRADING_CHAT_SYSTEM
            q = (
                "Conclude with BUY/SELL/WAIT per ticker, %confidence, %SL, %TP, and a short reason. "
                f"User asked: {message}"
            )
            mode = "ask" if intent.get("mode") == "top_picks" else "next_move"

        try:
            return await self.ai.ask(
                context=ctx,
                question=q,
                system_prompt=sys,
                section="dashboard/trading-chat-deep" if deep else "dashboard/trading-chat",
                max_tokens=4000 if deep else 3500,
                mode=mode,
            )
        except Exception as exc:
            logger.exception("Dashboard trading chat AI failed")
            return {
                "report": f"AI conclusion unavailable: {exc}. Engine / backtest results below still apply.",
                "verdict": None,
                "confidence_pct": None,
                "provider": None,
                "model": None,
                "error": True,
            }

    def _pack_response(
        self,
        *,
        intent: dict[str, Any],
        mode: str,
        ac: str,
        tf: str,
        scan_tickers: list[str],
        checks: list[str],
        picks: list[dict[str, Any]],
        ai_payload: dict[str, Any] | None,
        bb_entry_count: Any,
        disclaimer: Any,
        scanned: int,
        deep_mode: bool,
    ) -> dict[str, Any]:
        if ai_payload is None:
            # Caller may skip AI; FE still shows engine / deep ranking.
            pass

        summary_lines = []
        for p in picks:
            summary_lines.append(
                f"{p.get('rank')}. {p.get('ticker')} — {p.get('action')} ({p.get('side')}) · "
                f"{p.get('confidence_pct') or '—'}% · SL {p.get('sl_pct') or '—'}% · TP {p.get('tp_pct') or '—'}% · "
                f"{p.get('reason')}"
            )

        how = [
            "Engine: BB Mean Reversion core + all confluence checks.",
            "BUY/SELL = eligible actionable setups (all of them — no top-10 cut).",
            "AI conclusion uses the provider saved in Manage → AI Settings.",
            "SL%/TP% come from the engine trade plan (band edge → mean).",
        ]
        if deep_mode:
            how = [
                "Deep mode: backtest-ranked strategies → Strategies catalog (/strategies) → live analysis → AI.",
                "See strategy_ranking and selected_strategies (catalog how-to) in the response.",
                "AI conclusion uses Manage → AI Settings.",
                "Research / education only — not financial advice.",
            ]

        return {
            "intent": intent,
            "mode": mode,
            "deep_mode": deep_mode,
            "asset_class": ac,
            "style": intent.get("style"),
            "timeframe": tf,
            "scanned": scanned,
            "scan_tickers": scan_tickers,
            "extra_checks": checks,
            "picks": picks,
            "summary": "\n".join(summary_lines),
            "ai": ai_payload,
            "bb_entry_count": bb_entry_count,
            "disclaimer": disclaimer or "Research / education only — not financial advice.",
            "how_to_read": how,
        }
