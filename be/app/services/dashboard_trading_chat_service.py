"""Dashboard Trading Chat (Technical Agent) — pure Price Action desk
(Support/Resistance · Volume · RSI · Bollinger Bands). Deep = broader universe."""

from __future__ import annotations

import logging
from typing import Any

from app.market_pulse.dashboard_trading_chat_engine import (
    DEEP_CHAT_SYSTEM,
    EXPLAIN_CHAT_SYSTEM,
    PRICE_ACTION_STRATEGY_ID,
    PRICE_ACTION_STRATEGY_LABEL,
    SCREEN_CHAT_SYSTEM,
    TRADING_CHAT_SYSTEM,
    all_extra_checks,
    build_chat_ai_context,
    build_deep_ai_context,
    build_explain_ai_context,
    build_screen_ai_context,
    compact_break_pick,
    compact_mover_pick,
    compact_pick,
    default_ad_index,
    default_mover_index,
    default_universe,
    is_explain_followup,
    is_screen_mode,
    parse_intent,
    rank_picks,
    summarize_enrichment_payload,
)
from app.market_pulse.serialize import json_safe
from app.services.ai_service import AIService
from app.services.pro_trade_service import ProTradeService
from app.services.settings_service import SettingsService
from app.services.ticker_universe_service import TickerUniverseService

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

    def _tag_price_action_picks(self, picks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for p in picks:
            p["strategy_id"] = p.get("strategy_id") or PRICE_ACTION_STRATEGY_ID
            p["strategy_label"] = PRICE_ACTION_STRATEGY_LABEL
        return picks

    async def _run_price_action_scan(
        self,
        tickers: list[str],
        *,
        asset_class: str,
        timeframe: str,
        checks: list[str] | None = None,
    ) -> dict[str, Any]:
        """Single Price Action desk scan (BB core + S/R extra check)."""
        return await self.pro.bb_mean_reversion(
            tickers,
            asset_class=asset_class,
            timeframes=[timeframe],
            cfg_overrides={"extra_checks": list(checks) if checks is not None else all_extra_checks()},
        )

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
        explain_only: bool = False,
        prior_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # Follow-up: explain prior desk result without a new BB / options scan
        if prior_result and (explain_only or is_explain_followup(message)):
            return await self._chat_explain(
                message=message,
                prior_result=prior_result,
                skip_ai=skip_ai,
            )

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

    async def _chat_explain(
        self,
        *,
        message: str,
        prior_result: dict[str, Any],
        skip_ai: bool,
    ) -> dict[str, Any]:
        """Answer why / explain using the prior packed desk payload (no re-scan)."""
        prior = prior_result if isinstance(prior_result, dict) else {}
        picks = [p for p in (prior.get("picks") or []) if isinstance(p, dict)]
        enrichments = [e for e in (prior.get("enrichments") or []) if isinstance(e, dict)]
        hedge_pairs = [p for p in (prior.get("hedge_pairs") or []) if isinstance(p, dict)]

        if skip_ai:
            ai_payload = None
        else:
            cfg = await self.ai.provider_config()
            if not picks and not enrichments and not prior.get("summary"):
                ai_payload = {
                    "report": (
                        "No prior desk result to explain. Ask a trading question first "
                        "(e.g. Indian intraday buys), then follow up with “why?”."
                    ),
                    "verdict": None,
                    "confidence_pct": None,
                    "provider": cfg.get("provider"),
                    "model": cfg.get("model"),
                    "error": False,
                }
            else:
                ctx = build_explain_ai_context(message, prior)
                try:
                    ai_payload = await self.ai.ask(
                        context=ctx,
                        question=(
                            "Explain why the Technical Agent gave this result. Cover picks, "
                            "%confidence, %SL, %TP using Price Action pillars only "
                            f"(S/R · Volume · RSI · Bollinger Bands). User asked: {message}"
                        ),
                        system_prompt=EXPLAIN_CHAT_SYSTEM,
                        section="dashboard/trading-chat-explain",
                        max_tokens=3500,
                        mode="ask",
                    )
                except Exception as exc:
                    logger.exception("Trading chat explain AI failed")
                    ai_payload = {
                        "report": f"Explanation unavailable: {exc}",
                        "verdict": None,
                        "confidence_pct": None,
                        "provider": None,
                        "model": None,
                        "error": True,
                    }

        return json_safe({
            "intent": {
                "raw_message": message,
                "mode": "explain",
                "asset_class": prior.get("asset_class"),
                "style": prior.get("style"),
                "timeframe": prior.get("timeframe"),
            },
            "mode": "explain",
            "explain_only": True,
            "deep_mode": False,
            "asset_class": prior.get("asset_class"),
            "style": prior.get("style"),
            "timeframe": prior.get("timeframe"),
            "scanned": prior.get("scanned") or 0,
            "scan_tickers": prior.get("scan_tickers") or [],
            "extra_checks": prior.get("extra_checks") or [],
            "enrichments": enrichments,
            "hedge_pairs": hedge_pairs,
            "picks": picks,
            "summary": prior.get("summary") or "",
            "ai": ai_payload,
            "bb_entry_count": prior.get("bb_entry_count"),
            "disclaimer": prior.get("disclaimer") or "Research / education only — not financial advice.",
            "how_to_read": [
                "Explain mode — no new scan. Answer uses the prior desk result only.",
                "Ask another market question to refresh picks and options desks.",
            ],
        })

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

        # Optional deep enrich: Price Action (BB · RSI · Volume · S/R) on top movers
        if deep_mode and picks:
            try:
                enrich_syms = [str(p.get("ticker")) for p in picks[:5] if p.get("ticker")]
                if enrich_syms:
                    bb = await self._run_price_action_scan(
                        enrich_syms, asset_class=ac, timeframe=tf,
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
            "BUY/SELL here tags direction of the move or break — not a full Price Action trade plan unless Deep enrich added SL/TP.",
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
        # Keep Technical Agent pure: only Price Action pillars (S/R on top of BB/RSI/Volume).
        allowed = set(all_extra_checks())
        checks = [c for c in checks if c in allowed] or all_extra_checks()
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
            bb = await self._run_price_action_scan(
                scan_tickers, asset_class=ac, timeframe=tf, checks=checks,
            )
        except Exception as exc:
            logger.exception("Technical Agent Price Action scan failed")
            return {"error": f"Scan failed: {exc}", "intent": intent, "picks": [], "ai": None}

        results = list(bb.get("results") or [])

        if mode == "single":
            picks = [compact_pick(r, rank=i + 1) for i, r in enumerate(results)]
            self._tag_price_action_picks(picks)
            picks = sorted(picks, key=lambda p: (0 if p.get("take_trade") else 1, -(p.get("confidence_pct") or 0)))
            eligible = [p for p in picks if p.get("take_trade")]
            picks = eligible if eligible else picks
            if top_n is not None:
                picks = picks[:top_n]
            for i, p in enumerate(picks):
                p["rank"] = i + 1
        else:
            picks = rank_picks(results, top_n=top_n, action_bias=str(intent.get("action_bias") or "both"))
            self._tag_price_action_picks(picks)

        enrichments: list[dict[str, Any]] = []

        ai_payload = await self._conclude_ai(
            intent=intent,
            picks=picks,
            message=message,
            skip_ai=skip_ai,
            deep=False,
            ranking=None,
            selected=None,
            enrichments=enrichments,
        )

        packed = self._pack_response(
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
            enrichments=enrichments,
        )
        packed["core_engines"] = ["price_action_bb_rsi_volume_sr"]
        return json_safe(packed)

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
        """Deep = broader Price Action universe (same pillars), not multi-strategy backtest."""
        intent = parse_intent(message, asset_class=asset_class, style=style, tickers=tickers)
        checks = list(extra_checks) if extra_checks else all_extra_checks()
        allowed = set(all_extra_checks())
        checks = [c for c in checks if c in allowed] or all_extra_checks()
        intent["extra_checks"] = checks
        intent["deep_mode"] = True

        ac = str(intent["asset_class"])
        tf = str(intent["timeframe"])
        mode = str(intent["mode"])

        if mode == "single" and intent.get("tickers"):
            scan_tickers = self._resolve_named_tickers(ac, list(intent["tickers"]))
        else:
            mode = "top_picks"
            intent["mode"] = mode
            scan_tickers = default_universe(ac, limit=80)

        if not scan_tickers:
            return {"error": "Could not resolve any tickers for this question.", "intent": intent, "picks": [], "ai": None, "deep_mode": True}

        live_tickers = scan_tickers if mode == "top_picks" else scan_tickers[:8]

        try:
            bb = await self._run_price_action_scan(
                live_tickers, asset_class=ac, timeframe=tf, checks=checks,
            )
            results = list(bb.get("results") or [])
            if mode == "single":
                picks = [compact_pick(r, rank=i + 1) for i, r in enumerate(results)]
                self._tag_price_action_picks(picks)
                picks = sorted(picks, key=lambda p: (0 if p.get("take_trade") else 1, -(p.get("confidence_pct") or 0)))
                eligible = [p for p in picks if p.get("take_trade")]
                picks = eligible if eligible else picks
            else:
                picks = rank_picks(results, top_n=top_n, action_bias=str(intent.get("action_bias") or "both"))
                self._tag_price_action_picks(picks)
            if top_n is not None:
                picks = picks[:top_n]
            for i, p in enumerate(picks):
                p["rank"] = i + 1
            bb_entry_count = bb.get("entry_count")
            disclaimer = bb.get("disclaimer")
            bt_error = None
        except Exception as exc:
            logger.exception("Deep Price Action scan failed")
            return {"error": f"Scan failed: {exc}", "intent": intent, "picks": [], "ai": None, "deep_mode": True}

        ranking = [{
            "rank": 1,
            "strategy_id": PRICE_ACTION_STRATEGY_ID,
            "strategy_label": PRICE_ACTION_STRATEGY_LABEL,
            "avg_rank_score": None,
            "note": "Deep mode uses a broader Price Action universe — same S/R · Volume · RSI · BB pillars.",
        }]
        selected = [{
            "strategy_id": PRICE_ACTION_STRATEGY_ID,
            "strategy_label": PRICE_ACTION_STRATEGY_LABEL,
            "summary": (
                "Pure Price Action desk: Bollinger Band stretch/squeeze, RSI extremes, "
                "volume climax, support/resistance zones, and candlestick reversal at the band."
            ),
            "entry_rules": [
                "Prefer BB %B stretch with RSI confirmation",
                "Require volume participation and/or S/R confluence",
                "SL beyond band/S-R invalidation; TP toward mean / opposite band",
            ],
            "guide_excerpt": (
                "Technical Agent Deep mode scans a larger universe with the same Price Action "
                "pillars only — it does not backtest unrelated strategies."
            ),
        }]

        ai_payload = await self._conclude_ai(
            intent=intent,
            picks=picks,
            message=message,
            skip_ai=skip_ai,
            deep=True,
            ranking=ranking,
            selected=selected,
        )

        summary_parts = [
            f"Deep Price Action scan · {len(live_tickers)} names · {len(picks)} eligible:",
        ]
        for p in picks:
            summary_parts.append(
                f"{p.get('rank')}. {p.get('ticker')} — {p.get('action')} ({p.get('side')}) · "
                f"{p.get('confidence_pct') or '—'}% · SL {p.get('sl_pct') or '—'}% · TP {p.get('tp_pct') or '—'}% · "
                f"{p.get('reason')}"
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
            scanned=len(live_tickers),
            deep_mode=True,
        )
        payload.update({
            "summary": "\n".join(summary_parts),
            "candidate_strategies": [{
                "id": PRICE_ACTION_STRATEGY_ID,
                "label": PRICE_ACTION_STRATEGY_LABEL,
                "category": "Price Action",
            }],
            "strategy_ranking": ranking,
            "selected_strategies": selected,
            "backtest_period": None,
            "backtest_error": bt_error,
            "hedge_pairs": [],
            "core_engines": ["price_action_bb_rsi_volume_sr"],
            "how_to_read": [
                "Deep mode: broader Price Action universe with the same pillars — "
                "Support/Resistance · Volume · RSI · Bollinger Bands.",
                "SL%/TP% come from the Price Action trade plan (band edge → mean / S/R invalidation).",
                "AI conclusion uses Manage → AI Settings.",
                "Research / education only — not financial advice.",
            ],
        })
        return json_safe(payload)

    async def _run_normal_enrichments(
        self,
        planned: list[dict[str, Any]],
        *,
        asset_class: str,
        timeframe: str,
        style: str,
        tickers: list[str],
        message: str = "",
    ) -> list[dict[str, Any]]:
        import asyncio

        if not planned:
            return []

        async def _one(plan: dict[str, Any]) -> dict[str, Any]:
            eid = str(plan.get("id") or "")
            try:
                payload = await self._run_one_normal_enrichment(
                    eid,
                    asset_class=asset_class,
                    timeframe=timeframe,
                    style=style,
                    tickers=tickers,
                    message=message,
                    plan_config=plan.get("config") if isinstance(plan.get("config"), dict) else None,
                )
                compact = summarize_enrichment_payload(eid, payload if isinstance(payload, dict) else None)
                if eid == "intra_hedging" and isinstance(payload, dict):
                    compact["pair_recommendations"] = payload.get("pair_recommendations") or []
                    compact["config_used"] = plan.get("config")
            except Exception as exc:
                logger.exception("Normal enrichment %s failed", eid)
                compact = {
                    "id": eid,
                    "label": plan.get("label") or eid,
                    "summary": f"Failed: {exc}"[:240],
                    "error": str(exc)[:240],
                    "ticker_signals": [],
                }
            compact["why"] = plan.get("why")
            compact["score"] = plan.get("score")
            return compact

        return list(await asyncio.gather(*[_one(p) for p in planned]))

    async def _run_one_normal_enrichment(
        self,
        eid: str,
        *,
        asset_class: str,
        timeframe: str,
        style: str,
        tickers: list[str],
        message: str = "",
        plan_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from datetime import date, timedelta

        if eid == "intra_hedging":
            from app.market_pulse.dashboard_trading_chat_engine import adapt_intra_hedging_config
            from app.services.trading_hub_service import TradingHubService

            cfg = plan_config or adapt_intra_hedging_config(style, message, timeframe)
            hub = TradingHubService(self.settings, db=self.db)
            # Sector mode uses fixed universe; tickers arg is ignored. Stock mode ignores tickers too.
            seed = tickers[:1] or ["NIFTY BANK"]
            return await hub.scan(
                "intra_hedging",
                seed,
                asset_class="india",
                config=cfg,
            )

        if eid == "elliott_wave":
            tf = timeframe if timeframe in ("1d", "1wk", "4h", "1h") else ("1d" if style in ("swing", "investing") else "1h")
            return await self.pro.elliott_wave(
                tickers[:6],
                asset_class=asset_class,
                cfg_overrides={"timeframe": tf},
            )

        if eid == "volume_spread_next_candle":
            tf = timeframe if timeframe in ("5m", "15m", "30m", "1h") else ("5m" if style == "scalping" else "15m")
            return await self.pro.volume_spread_next_candle(
                tickers[:6],
                asset_class=asset_class,
                cfg_overrides={"timeframe": tf},
            )

        if eid == "advance_decline":
            from app.services.command_center_service import CommandCenterService

            cc = CommandCenterService(self.settings, self.db)
            today = date.today()
            return await cc.advance_decline_graph(
                default_ad_index(asset_class),
                asset_class=asset_class,
                from_date=(today - timedelta(days=30)).isoformat(),
                to_date=today.isoformat(),
                timeframe="1d",
            )

        if eid == "comparative_strength":
            from app.market_pulse.comparative_strength_engine import list_base_presets
            from app.services.command_center_service import CommandCenterService

            presets = list_base_presets(asset_class)
            base = str((presets[0] or {}).get("symbol") if presets else "")
            if not base:
                return {"error": "No comparative-strength base preset for this asset class", "rows": []}
            peers = [t for t in tickers if t and t.upper() != base.upper()][:8]
            if not peers:
                return {"error": "Need peer tickers for comparative strength", "rows": []}
            cs_tf = timeframe if timeframe in ("5m", "15m", "30m", "1h", "4h", "1d", "1w") else "1d"
            if timeframe in ("1wk", "1w"):
                cs_tf = "1w"
            elif style in ("swing", "investing") and cs_tf in ("5m", "15m", "30m"):
                cs_tf = "1d"
            cc = CommandCenterService(self.settings, self.db)
            return await cc.comparative_strength(
                asset_class=asset_class,
                base_symbol=base,
                compare_symbols=peers,
                timeframe=cs_tf,
                lookback_bars=20 if style in ("swing", "investing") else 12,
            )

        if eid == "oil_dollar_bond":
            from app.services.command_center_service import CommandCenterService

            cc = CommandCenterService(self.settings, self.db)
            mode = "intraday" if style in ("scalping", "intraday") else "daily"
            return await cc.oil_dollar_bond(
                mode=mode,
                interval="1h" if mode == "intraday" else "1d",
                session_date=date.today().isoformat() if mode == "intraday" else None,
            )

        if eid == "options_market_prediction":
            from app.services.options_service import OptionsService

            # Prefer NIFTY for India market prediction unless a named index pick
            symbol = "NIFTY"
            upper_set = {str(t).upper() for t in tickers}
            for cand, sym in (
                ("BANKNIFTY", "BANKNIFTY"),
                ("NIFTY BANK", "BANKNIFTY"),
                ("FINNIFTY", "FINNIFTY"),
                ("NIFTY", "NIFTY"),
                ("NIFTY 50", "NIFTY"),
            ):
                if cand in upper_set:
                    symbol = sym
                    break
            opt = OptionsService(self.settings, self.db)
            return await opt.market_prediction(symbol, is_index=True)

        if eid == "options_call_put_writing":
            from app.services.options_service import OptionsService

            symbol = "NIFTY"
            upper_set = {str(t).upper() for t in tickers}
            for cand, sym in (
                ("BANKNIFTY", "BANKNIFTY"),
                ("NIFTY BANK", "BANKNIFTY"),
                ("FINNIFTY", "FINNIFTY"),
                ("MIDCPNIFTY", "MIDCPNIFTY"),
                ("NIFTYNXT50", "NIFTYNXT50"),
                ("NIFTY", "NIFTY"),
                ("NIFTY 50", "NIFTY"),
            ):
                if cand in upper_set:
                    symbol = sym
                    break
            opt = OptionsService(self.settings, self.db)
            return await opt.call_put_writing(symbol, is_index=True)

        if eid == "pa_vp_smc":
            cfg: dict[str, Any] = {}
            if timeframe in ("1m", "3m", "5m", "15m", "30m", "1h", "4h"):
                cfg["ltf"] = timeframe
                if style in ("swing", "investing"):
                    cfg["htf"] = "4h" if timeframe in ("15m", "30m", "1h") else "1d"
                elif timeframe in ("1m", "3m", "5m"):
                    cfg["htf"] = "15m"
                else:
                    cfg["htf"] = "1h"
            return await self.pro.pa_vp_smc(
                tickers[:8],
                asset_class=asset_class,
                cfg_overrides=cfg or None,
            )

        return {"error": f"Unknown enrichment: {eid}"}

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
        enrichments: list[dict[str, Any]] | None = None,
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
                "Deep mode: conclude BUY/SELL/WAIT per ticker with %confidence %SL %TP "
                "using Price Action pillars only (S/R · Volume · RSI · Bollinger Bands). "
                f"User asked: {message}"
            )
            mode = "ask"
        else:
            ctx = build_chat_ai_context(intent, picks, enrichments=enrichments)
            sys = TRADING_CHAT_SYSTEM
            q = (
                "Conclude with BUY/SELL/WAIT per ticker, %confidence, %SL, %TP, and a short reason "
                "using Price Action only: Support/Resistance, Volume, RSI, and Bollinger Bands. "
                "Include a brief **Why this result** explanation. "
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
        enrichments: list[dict[str, Any]] | None = None,
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
            "Technical Agent uses a pure Price Action desk only:",
            "Support/Resistance · Volume · RSI · Bollinger Bands (plus candlestick reversal at the band).",
            "BUY/SELL = eligible actionable setups from that Price Action scan.",
            "AI conclusion uses the provider saved in Manage → AI Settings and includes a Why section.",
            "Ask “why?” or “explain this result” as a follow-up to dig into the rationale without re-scanning.",
            "SL%/TP% come from the Price Action trade plan (band edge → mean / S/R invalidation).",
        ]
        if deep_mode:
            how = [
                "Deep mode: broader Price Action universe — same S/R · Volume · RSI · BB pillars.",
                "No multi-strategy backtest desks — still pure Price Action.",
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
            "enrichments": enrichments or [],
            "hedge_pairs": next(
                (
                    e.get("pair_recommendations") or []
                    for e in (enrichments or [])
                    if e.get("id") == "intra_hedging"
                ),
                [],
            ),
            "picks": picks,
            "summary": "\n".join(summary_lines),
            "ai": ai_payload,
            "bb_entry_count": bb_entry_count,
            "disclaimer": disclaimer or "Research / education only — not financial advice.",
            "how_to_read": how,
        }
