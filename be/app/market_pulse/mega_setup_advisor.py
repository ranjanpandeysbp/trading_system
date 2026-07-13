"""
mega_setup_advisor.py
---------------------
Rule-based and AI-assisted Mega Analyser setup recommendations
(asset class, timeframes, engines/strategies).

UI (Streamlit) rendering and session_state application from the original source have
been stripped — only the computational recommendation logic is ported here:
  - `recommend_mega_setup_rule_based()` — pure heuristic scoring, no AI call.
  - `recommend_mega_setup_ai()` — calls the AI provider via the already-existing
    `app.market_pulse.ai_view.call_ai_report()` helper (reused, not reimplemented)
    and falls back to the rule-based recommendation (with a reason noted) if no API
    key is configured or the AI call/JSON-parse fails, so this never hard-fails.

`MEGA_SCENARIOS` is imported from `app.market_pulse.mega_analyser`, which already
ports the same scenario catalog (timeframes + module on/off maps) used by the
original Mega Analyser tab — not duplicated here.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.market_pulse.ticker_utils import (
    CRYPTO_MARKET,
    GROWW_MARKET,
    US_MARKET,
    is_crypto_market,
    is_india_market,
)

logger = logging.getLogger(__name__)

MEGA_MODULE_LABELS: dict[str, str] = {
    "backtest": "Strategy Builder backtest",
    "saved_strategies": "Saved Strategies",
    "screener": "Screener rules",
    "seasonality": "Seasonality",
    "sentiment": "Trend & Sentiment",
    "price_action": "Price Action",
    "find_sr": "Find S/R (S1/S2/R1/R2)",
    "weak_strong_sr": "Weak Strong S-R",
    "pattern_breakout": "Pattern & Breakout",
    "confluence": "Confluence (Fib·VWAP·ST·ATR·Vol·S/R)",
    "elliott_wave": "Elliott Wave",
    "top_bottom": "Top/Bottom",
    "tb_forecast": "Top/Bottom breakout forecast",
    "smc_flow": "SMC Flow (India stocks)",
    "gap": "Gap Scanner",
    "pump_dump": "Pump & Dump Predictor",
    "fakeout_15m": "1min–15min Breakout Fakeout",
    "fakeout_4h": "5min–4h Breakout Fakeout",
    "mtf_scanner": "MTF Scanner (7-component)",
    "top_down_mtf": "Top-Down MTF SMC",
    "topdown_mtf": "TOPDOWN - MTF (Liquidity + OB)",
    "weekly_stoch": "Weekly Stoch Sweet Spot",
    "kn_smart_rsi": "KN Smart DP SL + RSI MTF",
    "velez_retracement": "Velez Retracement Scalping",
    "mtf_intraday_bias": "MTF Intraday Session Bias",
    "smart_wave_crypto": "Smart Wave Crypto",
    "crypto_scalping": "Crypto Scalping",
    "smc_fake_market_shift": "SMC Fake Market Shift",
    "bb_exposed": "BB Exposed",
    "breakout_mtf": "Breakout MTF (daily BO)",
    "one_ta": "ONE TA (Golden Zone)",
    "box_trading": "Box Trading (TradingLab)",
    "scalp_rectangle": "Scalp Rectangle",
    "scalp_smc": "Scalp SMC Rule of Three",
    "scalp_arc": "Scalp ARC Method",
    "scalp_sr_mss": "Scalp S/R Zone + MSS",
    "scalp_multi_indicator": "Scalp Multi Indicator",
    "smc_cisd": "SMC CISD Entry",
    "smc_weekly_sweep_cisd": "SMC Weekly Sweep CISD",
    "smc_mtf_day_plan": "SMC MTF Day Plan",
    "smc_golden_bullet": "SMC Golden Bullet",
    "smc_liquidity": "SMC Liquidity (sweep/FVG)",
    "smb_snp": "SMB SnP Fashionably Late",
    "intraday_alpha_945": "Intraday Alpha 9:45",
    "intraday_fib_945": "Intraday Fib 9:45",
    "intraday_vwap_fade": "Intraday VWAP Fade",
    "intraday_mtf_breakout_retest": "Intraday MTF Breakout-Retest",
    "intraday_7_wasted": "Intraday 7+wasted OR Retest",
    "swing_trading_st_simple_steal": "SW Simple Steal Little Rizzy",
}

MARKET_BY_ASSET_CLASS: dict[str, str] = {
    "crypto": CRYPTO_MARKET,
    "india": GROWW_MARKET,
    "us": US_MARKET,
    "commodity": US_MARKET,
}

DEFAULT_TFS_BY_ASSET: dict[str, list[str]] = {
    "crypto": ["15m", "1h", "4h"],
    "india": ["5m", "15m", "1h"],
    "us": ["1h", "4h", "1d"],
    "commodity": ["1h", "4h", "1d"],
}

INTRADAY_TFS = frozenset({"1m", "5m", "15m", "30m"})
SWING_TFS = frozenset({"4h", "1d", "1w"})

MEGA_SETUP_AI_SYSTEM = """You are an elite trading-platform setup advisor for Mega Analyser — a unified multi-engine scan.

Recommend the BEST configuration for the user's goal:
1. **Asset class** — crypto | india | us | commodity
2. **Market** (exact dropdown string) — one of:
   - Groww (India Stocks)
   - US Stocks (Yahoo)
   - CoinDCX Futures
3. **Timeframes** — pick 1–4 from: 1m, 5m, 15m, 30m, 1h, 4h, 1d, 1w
4. **Scenario preset** — one of:
   - Full analysis (default)
   - Pump & Dump pre-move
   - India intraday scalp (expert)
   - Crypto momentum
   - Swing / positional
   - Custom (use only if none fit; then list engines explicitly)
5. **Strategies / engines** — which analysis modules to enable (name the important ones and why)

Rules:
- Intraday India: 5m/15m, SMC Flow, session bias, scalp engines, intraday 9:45 systems, fakeout scanners.
- Crypto: Smart Wave, Crypto Scalping, SMC FMS, pump/dump, MTF top-down; avoid India-only SMC Flow.
- US swing: 4h/1d/1w, Breakout MTF, ONE TA, confluence, weekly stoch, Elliott; skip intraday-only engines.
- Pump hunting: enable Pump & Dump, BB Exposed, liquidity, MTF bias; shorter TFs.
- Keep total engines practical (12–22) unless user asks for exhaustive scan.

Structure your reply:
## Asset class & market
## Recommended timeframes
## Scenario preset
## Strategies to enable (grouped: Core TA · MTF · Scalp · SMC · Intraday · Special)
## Why this stack fits
## Optional tweaks

End with a fenced JSON block ONLY (valid JSON):
```json
{"asset_class":"india","market":"Groww (India Stocks)","timeframes":["5m","15m"],"scenario":"India intraday scalp (expert)","priority_engines":["mtf_scanner","smc_flow","scalp_arc"],"rationale":"One line summary"}
```
"""


def asset_class_for_market(market: str) -> str:
    if is_crypto_market(market):
        return "crypto"
    if is_india_market(market):
        return "india"
    if market == US_MARKET or "US" in market:
        return "us"
    return "us"


def _is_intraday_profile(timeframes: list[str]) -> bool:
    if not timeframes:
        return False
    tf_set = set(timeframes)
    return bool(tf_set & INTRADAY_TFS) and not bool(tf_set & SWING_TFS)


def _is_swing_profile(timeframes: list[str]) -> bool:
    if not timeframes:
        return False
    tf_set = set(timeframes)
    return bool(tf_set & SWING_TFS) and not bool(tf_set & INTRADAY_TFS)


def _pick_scenario(market: str, timeframes: list[str]) -> str:
    if is_crypto_market(market):
        return "Crypto momentum"
    if is_india_market(market):
        if _is_intraday_profile(timeframes):
            return "India intraday scalp (expert)"
        if _is_swing_profile(timeframes):
            return "Swing / positional"
        return "Full analysis (default)"
    if _is_swing_profile(timeframes):
        return "Swing / positional"
    if _is_intraday_profile(timeframes):
        return "Pump & Dump pre-move"
    return "Full analysis (default)"


def _refine_modules_for_context(
    modules: dict[str, bool],
    *,
    market: str,
    timeframes: list[str],
) -> dict[str, bool]:
    """Turn off engines that clearly mismatch market or selected TFs."""
    out = dict(modules)
    tf_set = set(timeframes or [])
    intraday = bool(tf_set & INTRADAY_TFS)
    swing = bool(tf_set & SWING_TFS)

    if not is_crypto_market(market):
        out["smart_wave_crypto"] = False
        out["crypto_scalping"] = False
    if is_crypto_market(market):
        out["smc_flow"] = False

    if not intraday:
        for key in (
            "fakeout_15m", "fakeout_4h", "kn_smart_rsi", "velez_retracement",
            "scalp_rectangle", "scalp_smc", "scalp_arc", "scalp_sr_mss",
            "intraday_alpha_945", "intraday_fib_945", "intraday_vwap_fade",
            "intraday_mtf_breakout_retest", "smb_snp", "box_trading",
        ):
            out[key] = False

    if not swing and not (tf_set & {"1d"}):
        out["breakout_mtf"] = False
        out["weekly_stoch"] = False
        out["seasonality"] = False

    if not is_india_market(market) and not is_crypto_market(market):
        out["smc_flow"] = False
        out["gap"] = False

    if not (is_india_market(market) or is_crypto_market(market)):
        out["smc_fake_market_shift"] = False

    return out


def recommend_mega_setup_rule_based(
    market: str,
    timeframes: list[str],
    *,
    ticker_count: int = 0,
) -> dict[str, Any]:
    """Heuristic setup for current market + timeframes (no AI call)."""
    from app.market_pulse.mega_analyser import MEGA_SCENARIOS

    asset_class = asset_class_for_market(market)
    scenario = _pick_scenario(market, timeframes)
    scenario_cfg = MEGA_SCENARIOS.get(scenario) or MEGA_SCENARIOS["Full analysis (default)"]
    if timeframes:
        suggested_tfs = list(timeframes)
    else:
        suggested_tfs = list(scenario_cfg.get("timeframes") or DEFAULT_TFS_BY_ASSET.get(asset_class, ["1h", "1d"]))

    modules = _refine_modules_for_context(
        dict(scenario_cfg.get("modules") or {}),
        market=market,
        timeframes=suggested_tfs,
    )

    enabled = [MEGA_MODULE_LABELS[k] for k, v in modules.items() if v and k in MEGA_MODULE_LABELS]
    optional_off = [
        MEGA_MODULE_LABELS[k]
        for k, v in modules.items()
        if not v and k in MEGA_MODULE_LABELS
    ][:8]

    rationale: list[str] = [
        f"Asset class **{asset_class}** from market **{market}**.",
        f"Scenario **{scenario}** matches your timeframe profile.",
    ]
    if _is_intraday_profile(suggested_tfs):
        rationale.append("Intraday TFs → scalp, fakeout, session bias, and India opening-range engines prioritized.")
    elif _is_swing_profile(suggested_tfs):
        rationale.append("Swing TFs → Breakout MTF, ONE TA, weekly stoch, and positional confluence prioritized.")
    else:
        rationale.append("Mixed TFs → balanced core TA + MTF stack; intraday-only engines trimmed.")

    if is_crypto_market(market):
        rationale.append("Crypto → Smart Wave + Crypto Scalping + SMC Fake Market Shift; no India SMC Flow.")
    elif is_india_market(market):
        rationale.append("India → SMC Flow, gap, and NSE session systems included where relevant.")

    if ticker_count > 20:
        rationale.append(
            f"**{ticker_count}** tickers selected — lazy load runs 20/batch; prefer fewer heavy engines if speed matters."
        )

    return {
        "source": "rule_based",
        "asset_class": asset_class,
        "market": market,
        "timeframes": suggested_tfs,
        "scenario": scenario,
        "modules": modules,
        "enabled_labels": enabled,
        "skipped_labels": optional_off,
        "rationale": rationale,
    }


def build_mega_setup_ai_prompt(
    *,
    market: str,
    timeframes: list[str],
    scenario: str,
    ticker_count: int,
    user_goal: str,
) -> str:
    from app.market_pulse.mega_analyser import MEGA_SCENARIOS

    rule = recommend_mega_setup_rule_based(market, timeframes, ticker_count=ticker_count)
    catalog_lines = []
    for name, cfg in MEGA_SCENARIOS.items():
        if not cfg:
            continue
        tfs = ", ".join(cfg.get("timeframes") or [])
        on = sum(1 for v in (cfg.get("modules") or {}).values() if v)
        catalog_lines.append(f"- {name}: TFs [{tfs}] · ~{on} engines on")

    return "\n".join([
        "=== MEGA ANALYSER SETUP REQUEST ===",
        f"User goal: {user_goal or 'Best multi-engine scan setup for my watchlist'}",
        f"Current market: {market}",
        f"Current timeframes: {', '.join(timeframes) or '(none selected)'}",
        f"Current scenario dropdown: {scenario}",
        f"Ticker count: {ticker_count}",
        "",
        "Rule-based baseline (you may improve on this):",
        f"  Asset class: {rule['asset_class']}",
        f"  Suggested scenario: {rule['scenario']}",
        f"  Suggested TFs: {', '.join(rule['timeframes'])}",
        f"  Engines on ({len(rule['enabled_labels'])}): {', '.join(rule['enabled_labels'][:14])}…",
        "",
        "Scenario catalog:",
        *catalog_lines,
        "",
        "All engine keys available:",
        ", ".join(sorted(MEGA_MODULE_LABELS.keys())),
    ])


def parse_mega_setup_ai_json(report: str) -> dict[str, Any] | None:
    if not report:
        return None
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", report, re.DOTALL | re.IGNORECASE)
    if not match:
        match = re.search(r"(\{[^{}]*\"asset_class\"[^{}]*\})", report, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def ai_json_to_recommendation(ai_json: dict[str, Any], report: str) -> dict[str, Any]:
    from app.market_pulse.mega_analyser import MEGA_SCENARIOS

    asset_class = str(ai_json.get("asset_class") or "india")
    market = str(ai_json.get("market") or MARKET_BY_ASSET_CLASS.get(asset_class, GROWW_MARKET))
    timeframes = list(ai_json.get("timeframes") or [])
    scenario = str(ai_json.get("scenario") or "Full analysis (default)")

    modules: dict[str, bool] = {}
    if scenario in MEGA_SCENARIOS and MEGA_SCENARIOS[scenario].get("modules"):
        modules = dict(MEGA_SCENARIOS[scenario]["modules"])
    if not timeframes and scenario in MEGA_SCENARIOS:
        timeframes = list(MEGA_SCENARIOS[scenario].get("timeframes") or [])

    modules = _refine_modules_for_context(modules, market=market, timeframes=timeframes)
    priority = ai_json.get("priority_engines") or []
    for key in priority:
        if key in MEGA_MODULE_LABELS:
            modules[key] = True

    enabled = [MEGA_MODULE_LABELS[k] for k, v in modules.items() if v and k in MEGA_MODULE_LABELS]
    return {
        "source": "ai",
        "asset_class": asset_class,
        "market": market,
        "timeframes": timeframes,
        "scenario": scenario,
        "modules": modules,
        "enabled_labels": enabled,
        "skipped_labels": [],
        "rationale": [str(ai_json.get("rationale") or "AI personalized setup.")],
        "ai_report": report,
    }


def recommend_mega_setup_ai(
    *,
    market: str,
    timeframes: list[str],
    scenario: str = "Full analysis (default)",
    ticker_count: int = 0,
    user_goal: str = "",
    provider: str,
    model: str,
    api_key: str,
) -> dict[str, Any]:
    """AI-personalized Mega Setup recommendation.

    Reuses the existing `app.market_pulse.ai_view.call_ai_report()` helper for the
    actual LLM call (Groq/Gemini, per the caller's provider/model/api_key) rather than
    reimplementing AI-provider integration. Always falls back to the rule-based
    recommendation — with `ai_unavailable_reason` set — if no API key is configured,
    the AI call raises, or the AI response has no parseable JSON block, so this never
    hard-fails the setup-advisor endpoint.
    """
    if not api_key:
        rec = recommend_mega_setup_rule_based(market, timeframes, ticker_count=ticker_count)
        rec["ai_unavailable_reason"] = "No AI provider API key configured (GROQ_API_KEY / GEMINI_API_KEY)."
        return rec

    from app.market_pulse.ai_view import call_ai_report

    prompt = build_mega_setup_ai_prompt(
        market=market, timeframes=timeframes, scenario=scenario,
        ticker_count=ticker_count, user_goal=user_goal,
    )
    try:
        report = call_ai_report(
            prompt,
            MEGA_SETUP_AI_SYSTEM,
            provider,
            model,
            api_key,
            user_intro="Recommend Mega Analyser configuration:",
            max_tokens=2500,
        )
    except Exception as exc:
        logger.warning("Mega setup AI call failed: %s", exc)
        rec = recommend_mega_setup_rule_based(market, timeframes, ticker_count=ticker_count)
        rec["ai_unavailable_reason"] = f"AI call failed: {exc}"[:200]
        return rec

    ai_json = parse_mega_setup_ai_json(report)
    if not ai_json:
        rec = recommend_mega_setup_rule_based(market, timeframes, ticker_count=ticker_count)
        rec["ai_report"] = report
        rec["ai_unavailable_reason"] = "AI response did not include a parseable JSON block."
        return rec

    return ai_json_to_recommendation(ai_json, report)
