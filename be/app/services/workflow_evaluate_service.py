"""
workflow_evaluate_service.py
----------------------------
Run every desk in a Workflow (India / US / Crypto / Commodities) for
index or stock mode and return compact step scores + overall stance.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

from app.market_pulse.serialize import json_safe
from app.services.command_center_service import CommandCenterService
from app.services.market_pulse_service import MarketPulseService
from app.services.options_service import OptionsService
from app.services.pro_trade_service import ProTradeService
from app.services.settings_service import SettingsService
from app.services.ta_screener_service import TaScreenerService
from app.services.trading_hub_service import TradingHubService

logger = logging.getLogger(__name__)

WorkflowMarket = str  # india | us | crypto | commodities
WorkflowMode = str  # index | stock

DEFAULTS: dict[str, dict[str, Any]] = {
    "india": {
        "asset_class": "india",
        "index_tickers": ["NIFTY"],
        "stock_tickers": ["RELIANCE"],
        "ad_index": "NIFTY 50",
        "option_symbol_index": "NIFTY",
    },
    "us": {
        "asset_class": "us",
        "index_tickers": ["SPY"],
        "stock_tickers": ["AAPL"],
        "cs_base": "SPY",
        "cs_peers_index": ["QQQ", "IWM", "DIA"],
    },
    "crypto": {
        "asset_class": "crypto",
        "index_tickers": ["BTC"],
        "stock_tickers": ["ETH"],
    },
    "commodities": {
        "asset_class": "commodity",
        "index_tickers": ["GC=F"],
        "stock_tickers": ["CL=F"],
    },
}


def _iso_days_ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def _iso_today() -> str:
    return date.today().isoformat()


def make_step(
    step_id: str,
    title: str,
    *,
    status: str = "ok",
    bias: str = "WAIT",
    summary: str = "",
    score: float | None = None,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": step_id,
        "title": title,
        "status": status,
        "bias": (bias or "WAIT").upper(),
        "summary": (summary or "")[:480],
        "score": score,
        "detail": detail or {},
    }


async def _gather_named(jobs: dict[str, Any]) -> dict[str, Any]:
    keys = list(jobs.keys())
    results = await asyncio.gather(*[jobs[k] for k in keys], return_exceptions=True)
    out: dict[str, Any] = {}
    for k, r in zip(keys, results):
        if isinstance(r, Exception):
            logger.exception("Workflow step %s failed: %s", k, r)
            out[k] = {"error": str(r)[:240]}
        else:
            out[k] = r
    return out


def _bias_from_text(*parts: Any) -> str:
    blob = " ".join(str(p or "") for p in parts).upper()
    if any(x in blob for x in ("BUY", "LONG", "BULL")) and "BEAR" not in blob:
        return "BUY"
    if any(x in blob for x in ("SELL", "SHORT", "BEAR")):
        return "SELL"
    return "WAIT"


def _compact_ad(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("error"):
        return make_step("advance_decline", "Advance Decline", status="error", summary=str(payload["error"]))
    summary = payload.get("plain_english") or payload.get("summary") or ""
    bias = str(payload.get("bias") or payload.get("verdict") or _bias_from_text(summary))
    breadth = payload.get("breadth") or payload.get("latest") or {}
    if isinstance(breadth, dict) and not summary:
        summary = (
            f"A/D {breadth.get('advances', '—')}/{breadth.get('declines', '—')} · "
            f"ratio {breadth.get('ad_ratio', breadth.get('advance_decline_ratio', '—'))}"
        )
    return make_step(
        "advance_decline",
        "Advance Decline",
        bias=bias if bias in ("BUY", "SELL", "WAIT") else _bias_from_text(bias),
        summary=summary or "Breadth snapshot ready",
        detail={"advances": breadth.get("advances") if isinstance(breadth, dict) else None},
    )


def _compact_option_chain(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("error"):
        return make_step("option_chain", "Option Chain", status="error", summary=str(payload["error"]))
    sig = payload.get("signal") or payload.get("chain_signal") or {}
    if not isinstance(sig, dict):
        sig = {}
    bias = str(sig.get("trade_signal") or sig.get("bias") or payload.get("bias") or "WAIT")
    summary = (
        sig.get("plain_english")
        or f"PCR(OI) {payload.get('pcr_oi')} · Max Pain {payload.get('max_pain')} · spot {payload.get('underlying')}"
    )
    return make_step(
        "option_chain",
        "Option Chain",
        bias=_bias_from_text(bias),
        summary=str(summary),
        detail={"pcr_oi": payload.get("pcr_oi"), "max_pain": payload.get("max_pain")},
    )


def _compact_cpw(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("error"):
        return make_step("call_put_writing", "Call Put Writing", status="error", summary=str(payload["error"]))
    trade = payload.get("trade_suggestion") or {}
    writing = payload.get("writing") or {}
    bias = str(trade.get("action") or writing.get("bias") or payload.get("market_view") or "WAIT")
    summary = trade.get("plain_english") or writing.get("note") or payload.get("plain_english") or ""
    return make_step(
        "call_put_writing",
        "Call Put Writing",
        bias=_bias_from_text(bias),
        summary=str(summary),
        score=trade.get("confidence_pct"),
        detail={"tilt": writing.get("tilt"), "walls": payload.get("walls")},
    )


def _compact_pavp(payload: dict[str, Any], title: str = "PA-VP-SMC") -> dict[str, Any]:
    if payload.get("error"):
        return make_step("pa_vp_smc", title, status="error", summary=str(payload["error"]))
    results = list(payload.get("results") or [])
    actionable = [r for r in results if isinstance(r, dict) and (r.get("live") or {}).get("take_trade")]
    pick = actionable[0] if actionable else (results[0] if results else {})
    if not isinstance(pick, dict):
        pick = {}
    live = pick.get("live") or {}
    trade = pick.get("trade_suggestion") or live.get("trade_suggestion") or {}
    bias = str(trade.get("action") or live.get("signal") or live.get("verdict") or "WAIT")
    summary = (
        trade.get("plain_english")
        or pick.get("plain_english")
        or f"{pick.get('ticker', '—')}: entry_count={payload.get('entry_count', 0)}"
    )
    return make_step(
        "pa_vp_smc",
        title,
        bias=_bias_from_text(bias),
        summary=str(summary),
        score=trade.get("confidence_pct") or live.get("confidence_pct"),
        detail={
            "ticker": pick.get("ticker"),
            "entry_count": payload.get("entry_count"),
            "scanned": payload.get("scanned"),
        },
    )


def _compact_sector(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("error"):
        return make_step("sector_rotation", "Detect Sector Rotation", status="error", summary=str(payload["error"]))
    rows = list(payload.get("results") or payload.get("sectors") or [])
    leaders = []
    for r in rows[:5]:
        if not isinstance(r, dict):
            continue
        name = r.get("sector") or r.get("name") or r.get("ticker")
        lean = r.get("bias") or r.get("signal") or r.get("status")
        leaders.append(f"{name} ({lean})")
    summary = "Leaders: " + ", ".join(leaders) if leaders else (payload.get("plain_english") or "Sector scan complete")
    return make_step(
        "sector_rotation",
        "Detect Sector Rotation",
        bias="BUY" if leaders else "WAIT",
        summary=str(summary),
        detail={"top": leaders[:5]},
    )


def _compact_odb(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("error"):
        return make_step("oil_dollar_bond", "Oil · Dollar · Bond", status="error", summary=str(payload["error"]))
    regime = payload.get("regime") or payload.get("risk_regime") or payload.get("verdict") or ""
    summary = payload.get("plain_english") or payload.get("summary") or str(regime) or "Macro tape loaded"
    bias = "BUY" if "ON" in str(regime).upper() or "RISK-ON" in str(summary).upper() else (
        "SELL" if "OFF" in str(regime).upper() or "RISK-OFF" in str(summary).upper() else _bias_from_text(summary)
    )
    return make_step("oil_dollar_bond", "Oil · Dollar · Bond", bias=bias, summary=str(summary), detail={"regime": regime})


def _compact_cs(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("error"):
        return make_step("comparative_strength", "Comparative Strength", status="error", summary=str(payload["error"]))
    rows = list(payload.get("rows") or payload.get("results") or [])
    longs = []
    for r in rows[:8]:
        if not isinstance(r, dict):
            continue
        lean = str(r.get("lean") or r.get("bias") or r.get("signal") or "").upper()
        sym = r.get("symbol") or r.get("ticker")
        if "LONG" in lean or lean == "BUY":
            longs.append(str(sym))
    summary = (
        f"RS longs vs base: {', '.join(longs[:6])}" if longs else (payload.get("plain_english") or "CS scan complete")
    )
    return make_step(
        "comparative_strength",
        "Comparative Strength",
        bias="BUY" if longs else "WAIT",
        summary=str(summary),
        detail={"longs": longs[:8]},
    )


def _compact_ta(payload: dict[str, Any], step_id: str, title: str) -> dict[str, Any]:
    if payload.get("error"):
        return make_step(step_id, title, status="error", summary=str(payload["error"]))
    results = list(payload.get("results") or [])
    pick = results[0] if results and isinstance(results[0], dict) else {}
    live = pick.get("live") or pick.get("analysis") or {}
    if not isinstance(live, dict):
        live = {}
    bias = str(live.get("signal") or live.get("verdict") or pick.get("bias") or "WAIT")
    summary = pick.get("plain_english") or live.get("plain_english") or f"{title}: {len(results)} row(s)"
    return make_step(step_id, title, bias=_bias_from_text(bias), summary=str(summary), detail={"ticker": pick.get("ticker")})


def _compact_hub(payload: dict[str, Any], step_id: str, title: str) -> dict[str, Any]:
    if payload.get("error"):
        return make_step(step_id, title, status="error", summary=str(payload["error"]))
    results = list(payload.get("results") or payload.get("entries") or [])
    take = [r for r in results if isinstance(r, dict) and (r.get("live") or {}).get("take_trade")]
    pick = take[0] if take else (results[0] if results and isinstance(results[0], dict) else {})
    live = (pick.get("live") if isinstance(pick, dict) else None) or {}
    trade = (pick.get("trade_suggestion") if isinstance(pick, dict) else None) or {}
    bias = str((trade or {}).get("action") or (live or {}).get("signal") or "WAIT")
    summary = (
        (trade or {}).get("plain_english")
        or (pick or {}).get("plain_english")
        or f"{title}: {len(take)} actionable / {len(results)} scanned"
    )
    return make_step(
        step_id,
        title,
        bias=_bias_from_text(bias),
        summary=str(summary),
        score=(trade or {}).get("confidence_pct") or (live or {}).get("confidence_pct"),
        detail={"entry_count": len(take)},
    )


def _compact_commodity(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("error"):
        return make_step("commodity_screener", "Commodity Screener", status="error", summary=str(payload["error"]))
    results = list(payload.get("results") or payload.get("rows") or [])
    bits = []
    for r in results[:6]:
        if isinstance(r, dict):
            bits.append(f"{r.get('ticker') or r.get('name')}: {r.get('bias') or r.get('signal') or r.get('verdict')}")
    summary = "; ".join(bits) if bits else (payload.get("plain_english") or "Commodity screener complete")
    return make_step("commodity_screener", "Commodity Screener", bias=_bias_from_text(summary), summary=summary)


def _compact_vol_crypto(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("error"):
        return make_step("volatile_crypto", "24Hrs Volatile Crypto", status="error", summary=str(payload["error"]))
    rows = list(payload.get("results") or payload.get("tickers") or payload.get("rows") or [])
    top = []
    for r in rows[:8]:
        if isinstance(r, dict):
            top.append(str(r.get("symbol") or r.get("ticker") or r.get("name")))
        else:
            top.append(str(r))
    summary = "Hot names: " + ", ".join(top) if top else "Volatility heatmap loaded"
    return make_step("volatile_crypto", "24Hrs Volatile Crypto", bias="WAIT", summary=summary, detail={"top": top})


def _aggregate(steps: list[dict[str, Any]]) -> dict[str, Any]:
    buys = sum(1 for s in steps if s.get("bias") == "BUY" and s.get("status") == "ok")
    sells = sum(1 for s in steps if s.get("bias") == "SELL" and s.get("status") == "ok")
    errs = sum(1 for s in steps if s.get("status") == "error")
    if buys > sells and buys >= 2:
        action, conf = "BUY", min(82.0, 48 + buys * 8)
    elif sells > buys and sells >= 2:
        action, conf = "SELL", min(82.0, 48 + sells * 8)
    else:
        action, conf = "WAIT", 45.0
    explanation = (
        f"{buys} desk(s) lean BUY, {sells} lean SELL, {errs} error(s). "
        f"Overall stance **{action}** — confirm with the linked workflow how-to before sizing."
    )
    return {
        "action": action,
        "confidence_pct": round(conf, 1),
        "buy_votes": buys,
        "sell_votes": sells,
        "error_steps": errs,
        "plain_english": explanation,
    }


class WorkflowEvaluateService:
    def __init__(self, settings: SettingsService, db: Any = None):
        self.settings = settings
        self.db = db
        self.cc = CommandCenterService(settings, db)
        self.pro = ProTradeService(settings, db)
        self.opt = OptionsService(settings, db)
        self.hubs = TradingHubService(settings, db)
        self.ta = TaScreenerService(settings)
        self.mp = MarketPulseService(settings)

    def _tickers(self, market: str, mode: str, tickers: list[str] | None) -> list[str]:
        cfg = DEFAULTS[market]
        if tickers:
            return [t.strip().upper() for t in tickers if t and str(t).strip()][:8]
        key = "index_tickers" if mode == "index" else "stock_tickers"
        return list(cfg[key])

    async def evaluate(
        self,
        market: str,
        mode: str = "index",
        *,
        tickers: list[str] | None = None,
    ) -> dict[str, Any]:
        market = (market or "india").lower().strip()
        mode = (mode or "index").lower().strip()
        if market not in DEFAULTS:
            return {"error": f"Unknown market: {market}", "steps": []}
        if mode not in ("index", "stock"):
            return {"error": "mode must be index or stock", "steps": []}

        tickers_u = self._tickers(market, mode, tickers)
        cfg = DEFAULTS[market]
        asset_class = str(cfg["asset_class"])

        if market == "india":
            steps_raw = await self._eval_india(mode, tickers_u, cfg)
        elif market == "us":
            steps_raw = await self._eval_us(mode, tickers_u, cfg)
        elif market == "crypto":
            steps_raw = await self._eval_crypto(mode, tickers_u, cfg)
        else:
            steps_raw = await self._eval_commodities(mode, tickers_u, cfg)

        overall = _aggregate(steps_raw)
        return json_safe({
            "market": market,
            "mode": mode,
            "tickers": tickers_u,
            "asset_class": asset_class,
            "steps": steps_raw,
            "overall": overall,
            "disclaimer": "Research / education only — not financial advice. Workflow evaluate is a confluence snapshot.",
        })

    async def _eval_india(self, mode: str, tickers: list[str], cfg: dict[str, Any]) -> list[dict[str, Any]]:
        oc_sym = cfg["option_symbol_index"] if mode == "index" else tickers[0]
        oc_is_index = mode == "index"
        jobs = {
            "ad": self.cc.advance_decline_graph(
                cfg["ad_index"],
                asset_class="india",
                from_date=_iso_days_ago(30),
                to_date=_iso_today(),
                timeframe="1d",
            ),
            "oc": self.cc.option_chain(oc_sym if mode == "index" else "NIFTY", is_index=True),
            "sector": self.cc.detect_sector_rotation("india", pullback_mode="months", pullback_months=1),
            "cpw": self.opt.call_put_writing(oc_sym, is_index=oc_is_index),
            "pavp": self.pro.pa_vp_smc(tickers, asset_class="india", cfg_overrides={"ltf": "15m", "htf": "1h"}),
        }
        raw = await _gather_named(jobs)
        steps = [
            _compact_ad(raw.get("ad") or {}),
            _compact_option_chain(raw.get("oc") or {}),
            _compact_sector(raw.get("sector") or {}),
            _compact_cpw(raw.get("cpw") or {}),
            _compact_pavp(raw.get("pavp") or {}),
        ]
        if mode == "stock" and tickers[0].upper() not in ("NIFTY", "BANKNIFTY"):
            # Tape still uses Nifty OC above; stock CPW already targeted when oc_is_index False
            pass
        return steps

    async def _eval_us(self, mode: str, tickers: list[str], cfg: dict[str, Any]) -> list[dict[str, Any]]:
        base = cfg["cs_base"]
        peers = list(cfg["cs_peers_index"]) if mode == "index" else list(tickers)
        if mode == "stock":
            # compare selected stocks against SPY
            peers = [t for t in tickers if t.upper() != "SPY"] or list(tickers)
        jobs = {
            "odb": self.cc.oil_dollar_bond(from_date=_iso_days_ago(60), to_date=_iso_today(), mode="daily"),
            "cs": self.cc.comparative_strength(
                asset_class="us",
                base_symbol=base,
                compare_symbols=peers,
                timeframe="1d",
                lookback_bars=20,
            ),
            "topdown": self.ta.run("topdown_mtf", tickers, timeframe="15m", asset_class="us"),
            "hedge": self.ta.run("mtf_hedging", tickers[:1] or ["SPY"], timeframe="1d", asset_class="us"),
        }
        raw = await _gather_named(jobs)
        return [
            _compact_odb(raw.get("odb") or {}),
            _compact_cs(raw.get("cs") or {}),
            _compact_ta(raw.get("topdown") or {}, "topdown_mtf", "Top-Down MTF"),
            _compact_ta(raw.get("hedge") or {}, "mtf_hedging", "MTF Hedging"),
        ]

    async def _eval_crypto(self, mode: str, tickers: list[str], cfg: dict[str, Any]) -> list[dict[str, Any]]:
        jobs = {
            "vol": self.cc.coindcx_24h_volatility(),
            "golden": self.hubs.scan("smc_golden_bullet", tickers, asset_class="crypto"),
            "fake": self.ta.run("smc_fake_market_shift", tickers, timeframe="5m", asset_class="crypto"),
            "crt": self.hubs.scan("scalp_crt_fvg", tickers, asset_class="crypto"),
        }
        raw = await _gather_named(jobs)
        return [
            _compact_vol_crypto(raw.get("vol") or {}),
            _compact_hub(raw.get("golden") or {}, "smc_golden_bullet", "SMC Golden Bullet"),
            _compact_ta(raw.get("fake") or {}, "smc_fake_market_shift", "Fake Market Shift"),
            _compact_hub(raw.get("crt") or {}, "scalp_crt_fvg", "CRT-FVG"),
        ]

    async def _eval_commodities(self, mode: str, tickers: list[str], cfg: dict[str, Any]) -> list[dict[str, Any]]:
        jobs = {
            "odb": self.cc.oil_dollar_bond(from_date=_iso_days_ago(60), to_date=_iso_today(), mode="daily"),
            "comm": self.mp.commodity_screener(timeframes=["1d", "4h"]),
            "wssr": self.ta.run("weak_strong_sr", tickers, timeframe="4h", asset_class="commodity"),
            "gold": self.hubs.scan("scalp_gold", tickers, asset_class="commodity"),
        }
        raw = await _gather_named(jobs)
        return [
            _compact_odb(raw.get("odb") or {}),
            _compact_commodity(raw.get("comm") or {}),
            _compact_ta(raw.get("wssr") or {}, "weak_strong_sr", "Weak Strong S/R"),
            _compact_hub(raw.get("gold") or {}, "scalp_gold", "Scalping — Gold"),
        ]