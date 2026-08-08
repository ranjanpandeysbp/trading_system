"""Dashboard Trading Chat — BB Mean Reversion + all confluence + Manage-tab AI."""

from __future__ import annotations

import logging
from typing import Any

from app.market_pulse.dashboard_trading_chat_engine import (
    TRADING_CHAT_SYSTEM,
    all_extra_checks,
    build_chat_ai_context,
    compact_pick,
    default_universe,
    parse_intent,
    rank_picks,
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
        """Resolve free-text symbols for the data layer."""
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
        top_n: int = 10,
        skip_ai: bool = False,
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
            scan_tickers = default_universe(ac, limit=20)

        if not scan_tickers:
            return {
                "error": "Could not resolve any tickers for this question.",
                "intent": intent,
                "picks": [],
                "ai": None,
            }

        if mode == "top_picks":
            scan_tickers = scan_tickers[:20]
        else:
            scan_tickers = scan_tickers[:5]

        cfg_overrides = {"extra_checks": checks}
        try:
            bb = await self.pro.bb_mean_reversion(
                scan_tickers,
                asset_class=ac,
                timeframes=[tf],
                cfg_overrides=cfg_overrides,
            )
        except Exception as exc:
            logger.exception("Dashboard trading chat BB scan failed")
            return {
                "error": f"Scan failed: {exc}",
                "intent": intent,
                "picks": [],
                "ai": None,
            }

        results = list(bb.get("results") or [])
        if mode == "single":
            picks = [compact_pick(r, rank=i + 1) for i, r in enumerate(results[:top_n])]
            picks = sorted(
                picks,
                key=lambda p: (
                    0 if p.get("take_trade") else 1,
                    -(p.get("confidence_pct") or 0),
                ),
            )
            for i, p in enumerate(picks):
                p["rank"] = i + 1
            picks = picks[: max(1, min(top_n, len(picks)))]
        else:
            picks = rank_picks(results, top_n=top_n, action_bias=str(intent.get("action_bias") or "both"))

        ai_payload: dict[str, Any] | None = None
        if not skip_ai and picks:
            ctx = build_chat_ai_context(intent, picks)
            q = (
                "Conclude with BUY/SELL/WAIT per ticker, %confidence, %SL, %TP, and a short reason. "
                f"User asked: {message}"
            )
            try:
                ai_payload = await self.ai.ask(
                    context=ctx,
                    question=q,
                    system_prompt=TRADING_CHAT_SYSTEM,
                    section="dashboard/trading-chat",
                    max_tokens=3500,
                    mode="ask" if mode == "top_picks" else "next_move",
                )
            except Exception as exc:
                logger.exception("Dashboard trading chat AI failed")
                ai_payload = {
                    "report": f"AI conclusion unavailable: {exc}. Engine picks below still apply.",
                    "verdict": None,
                    "confidence_pct": None,
                    "provider": None,
                    "model": None,
                    "error": True,
                }

        if ai_payload is None and not skip_ai:
            cfg = await self.ai.provider_config()
            ai_payload = {
                "report": (
                    "Configure an AI provider in Manage → AI Settings to get a written conclusion. "
                    "Engine picks below are ready."
                ),
                "verdict": None,
                "confidence_pct": None,
                "provider": cfg.get("provider"),
                "model": cfg.get("model"),
                "error": not cfg.get("ready"),
            }

        summary_lines = []
        for p in picks[:10]:
            summary_lines.append(
                f"{p.get('rank')}. {p.get('ticker')} — {p.get('action')} ({p.get('side')}) · "
                f"{p.get('confidence_pct') or '—'}% · SL {p.get('sl_pct') or '—'}% · TP {p.get('tp_pct') or '—'}% · "
                f"{p.get('reason')}"
            )

        return json_safe(
            {
                "intent": intent,
                "mode": mode,
                "asset_class": ac,
                "style": intent.get("style"),
                "timeframe": tf,
                "scanned": len(results),
                "scan_tickers": scan_tickers,
                "extra_checks": checks,
                "picks": picks,
                "summary": "\n".join(summary_lines),
                "ai": ai_payload,
                "bb_entry_count": bb.get("entry_count"),
                "disclaimer": bb.get("disclaimer")
                or "Research / education only — not financial advice.",
                "how_to_read": [
                    "Engine: BB Mean Reversion core + all confluence checks (Fib, EMA, Stoch RSI, VWAP, "
                    "Volume Profile, Smart Money, Reversal, MACD, S/R, ADX, MTF, Candlestick patterns).",
                    "BUY/SELL = actionable take_trade; WAIT = stretch or mixed confluence — stand aside.",
                    "AI conclusion uses the provider saved in Manage → AI Settings.",
                    "SL%/TP% come from the engine trade plan (band edge → mean).",
                ],
            }
        )
