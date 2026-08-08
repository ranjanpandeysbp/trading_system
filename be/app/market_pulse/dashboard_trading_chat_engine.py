"""
dashboard_trading_chat_engine.py
--------------------------------
Intent parse + pick compaction for the Dashboard trading chatbot.
Analysis itself runs via BB Mean Reversion with all EXTRA_CHECK_OPTIONS confluence.
"""

from __future__ import annotations

import re
from typing import Any

from app.market_pulse.bb_mean_reversion_engine import EXTRA_CHECK_OPTIONS

ALL_EXTRA_CHECK_IDS: list[str] = [str(x["value"]) for x in EXTRA_CHECK_OPTIONS]

# Trading style → primary BB timeframe
STYLE_TIMEFRAMES: dict[str, str] = {
    "scalping": "5m",
    "intraday": "15m",
    "swing": "1d",
    "investing": "1wk",
}

STYLE_LABELS: dict[str, str] = {
    "scalping": "Scalping",
    "intraday": "Intraday",
    "swing": "Swing trade",
    "investing": "Investing / positional",
}

# Common free-text aliases → (asset_class, ticker_or_None for universe)
_NAME_ALIASES: dict[str, tuple[str, str | None]] = {
    "bitcoin": ("crypto", "B-BTCUSDT"),
    "btc": ("crypto", "B-BTCUSDT"),
    "ethereum": ("crypto", "B-ETHUSDT"),
    "eth": ("crypto", "B-ETHUSDT"),
    "solana": ("crypto", "B-SOLUSDT"),
    "sol": ("crypto", "B-SOLUSDT"),
    "xrp": ("crypto", "B-XRPUSDT"),
    "dogecoin": ("crypto", "B-DOGEUSDT"),
    "doge": ("crypto", "B-DOGEUSDT"),
    "gold": ("commodity", "GC=F"),
    "silver": ("commodity", "SI=F"),
    "crude": ("commodity", "CL=F"),
    "oil": ("commodity", "CL=F"),
    "brent": ("commodity", "BZ=F"),
    "natgas": ("commodity", "NG=F"),
    "natural gas": ("commodity", "NG=F"),
    "copper": ("commodity", "HG=F"),
    "apple": ("us", "AAPL"),
    "microsoft": ("us", "MSFT"),
    "nvidia": ("us", "NVDA"),
    "tesla": ("us", "TSLA"),
    "amazon": ("us", "AMZN"),
    "google": ("us", "GOOGL"),
    "meta": ("us", "META"),
    "reliance": ("india", "RELIANCE"),
    "tcs": ("india", "TCS"),
    "infosys": ("india", "INFY"),
    "hdfc": ("india", "HDFCBANK"),
    "nifty": ("india", None),
    "sensex": ("india", None),
}

_ASSET_KEYWORDS: list[tuple[str, list[str]]] = [
    ("crypto", ["crypto", "coin", "bitcoin", "ethereum", "altcoin", "coindcx"]),
    ("commodity", ["commodity", "commodities", "gold", "silver", "crude", "oil", "natgas", "copper", "futures"]),
    ("us", ["us stock", "us stocks", "nasdaq", "nyse", "s&p", "american stock", "wall street"]),
    ("india", ["india", "indian", "nse", "bse", "nifty", "sensex", "equity"]),
]

_STYLE_KEYWORDS: list[tuple[str, list[str]]] = [
    ("scalping", ["scalp", "scalping", "1m", "3m", "5 min", "5min"]),
    ("intraday", ["intraday", "day trade", "daytrading", "same day", "intra-day", "intra day"]),
    ("swing", ["swing", "positional", "multi-day", "few days", "week trade"]),
    ("investing", ["invest", "investing", "long term", "long-term", "hold", "portfolio"]),
]


def all_extra_checks() -> list[str]:
    return list(ALL_EXTRA_CHECK_IDS)


def parse_intent(
    message: str,
    *,
    asset_class: str | None = None,
    style: str | None = None,
    tickers: list[str] | None = None,
) -> dict[str, Any]:
    """Rule-based intent from free text (+ optional explicit overrides)."""
    text = (message or "").strip()
    lower = text.lower()

    detected_style = (style or "").strip().lower() or None
    if detected_style not in STYLE_TIMEFRAMES:
        detected_style = None
        for sid, keys in _STYLE_KEYWORDS:
            if any(k in lower for k in keys):
                detected_style = sid
                break
    if not detected_style:
        detected_style = "intraday"

    detected_ac = (asset_class or "").strip().lower() or None
    if detected_ac not in ("india", "us", "crypto", "commodity"):
        detected_ac = None
        for ac, keys in _ASSET_KEYWORDS:
            if any(k in lower for k in keys):
                detected_ac = ac
                break

    explicit = [t.strip() for t in (tickers or []) if (t or "").strip()]
    found: list[str] = list(explicit)

    # Multi-word aliases first
    for alias in sorted(_NAME_ALIASES.keys(), key=len, reverse=True):
        if alias in lower:
            ac, sym = _NAME_ALIASES[alias]
            if not detected_ac:
                detected_ac = ac
            if sym and sym not in found:
                found.append(sym)

    _STOP = {
        "BUY", "SELL", "WAIT", "LONG", "SHORT", "WHAT", "WHICH", "STOCK", "STOCKS",
        "CRYPTO", "NOW", "FOR", "THE", "AND", "WITH", "FROM", "THIS", "THAT", "ABOUT",
        "TRADE", "TRADES", "SCALP", "SWING", "TODAY", "GIVE", "TOP", "BEST", "ANALYZE",
        "SHOULD", "CAN", "PLEASE", "HELP", "ME", "SOME", "ANY", "IDEA", "IDEAS", "NAME",
        "COMMODITY", "COMMODITIES", "INVEST", "INVESTING", "INTRADAY", "SCALPING",
        "INDIAN", "INDIA", "EQUITY", "EQUITIES", "MARKET", "MARKETS", "PRICE", "CHART",
        "CONFIDENCE", "REASON", "REASONS", "SUGGEST", "SUGGESTION", "LIST", "PICK",
        "PICKS", "WANT", "NEED", "LOOK", "LOOKING", "TELL", "SHOW", "FIND", "GOOD",
        "AMERICAN", "DOLLAR", "RUPEE", "WEEK", "MONTH", "YEAR", "DAYS", "HOUR",
    }
    # Token scan: aliases + ALL-CAPS / crypto-commodity shaped symbols only
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9.=&-]{0,14}", text)
    for tok in tokens:
        key = tok.lower()
        if key in _NAME_ALIASES:
            ac, sym = _NAME_ALIASES[key]
            if not detected_ac:
                detected_ac = ac
            if sym and sym not in found:
                found.append(sym)
            continue
        up = tok.upper()
        if up in _STOP or len(up) < 2 or len(up) > 12:
            continue
        looks_symbol = (
            tok.isupper()
            or tok.startswith("B-")
            or up.endswith("USDT")
            or "=" in tok
            or up.endswith("=F")
            or (
                tok.isalpha()
                and 2 <= len(up) <= 6
                and any(
                    p in lower
                    for p in ("analyze", "analyse", "check ", "should i", "long ", "short ", " about ")
                )
            )
        )
        if looks_symbol and up not in found:
            found.append(up)

    if not detected_ac:
        # Heuristic from ticker shape
        if any(t.startswith("B-") or t.endswith("USDT") for t in found):
            detected_ac = "crypto"
        elif any("=" in t or t.endswith("=F") for t in found):
            detected_ac = "commodity"
        else:
            detected_ac = "india"

    mode = "single" if found else "top_picks"
    # Phrases that force universe scan even if a sector word matched as ticker
    if any(p in lower for p in ("which stock", "which crypto", "what to buy", "what to sell", "top 10", "top ten", "suggest")):
        if len(found) <= 1 and (not found or found[0] in ("NIFTY", "SENSEX")):
            mode = "top_picks"
            found = []

    action_bias = "both"
    if re.search(r"\b(buy|long|go long)\b", lower) and not re.search(r"\b(sell|short)\b", lower):
        action_bias = "buy"
    elif re.search(r"\b(sell|short|go short)\b", lower) and not re.search(r"\b(buy|long)\b", lower):
        action_bias = "sell"

    return {
        "raw_message": text,
        "mode": mode,  # single | top_picks
        "asset_class": detected_ac,
        "style": detected_style,
        "style_label": STYLE_LABELS.get(detected_style, detected_style),
        "timeframe": STYLE_TIMEFRAMES.get(detected_style, "15m"),
        "tickers": found[:8],
        "action_bias": action_bias,
        "extra_checks": all_extra_checks(),
    }


def default_universe(asset_class: str, *, limit: int = 20) -> list[str]:
    """Liquid scan universe for top-picks mode."""
    ac = (asset_class or "india").lower()
    if ac == "india":
        from app.market_pulse.ticker_utils import NIFTY_50

        return list(NIFTY_50)[:limit]
    if ac == "us":
        pool = [
            "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AMD", "NFLX", "AVGO",
            "SPY", "QQQ", "JPM", "V", "MA", "COST", "CRM", "ORCL", "INTC", "BA",
            "DIS", "PYPL", "ADBE", "NKE", "WMT", "KO", "PEP", "MRK", "PFE", "XOM",
            "CVX", "UNH", "HD", "CSCO", "IBM", "QCOM", "TXN", "AMGN", "ISRG", "NOW",
            "SHOP", "SQ", "UBER", "ABNB", "COIN", "PLTR", "SNOW", "PANW", "CRWD", "MU",
        ]
        return pool[:limit]
    if ac == "crypto":
        pool = [
            "B-BTCUSDT", "B-ETHUSDT", "B-SOLUSDT", "B-XRPUSDT", "B-DOGEUSDT",
            "B-BNBUSDT", "B-ADAUSDT", "B-AVAXUSDT", "B-LINKUSDT", "B-DOTUSDT",
            "B-MATICUSDT", "B-LTCUSDT", "B-UNIUSDT", "B-ATOMUSDT", "B-NEARUSDT",
            "B-APTUSDT", "B-ARBUSDT", "B-OPUSDT", "B-SUIUSDT", "B-INJUSDT",
            "B-FETUSDT", "B-RENDERUSDT", "B-FILUSDT", "B-ICPUSDT", "B-AAVEUSDT",
            "B-MKRUSDT", "B-PEPEUSDT", "B-SHIBUSDT", "B-TRXUSDT", "B-TONUSDT",
        ]
        return pool[:limit]
    # commodity
    from app.market_pulse.commodity_screener_engine import COMMODITY_META

    return [str(m["yf"]) for m in COMMODITY_META.values()][:limit]


def _action_from_result(r: dict[str, Any]) -> str:
    if r.get("error"):
        return "WAIT"
    if r.get("take_trade"):
        d = str(r.get("direction") or "").upper()
        if d == "LONG":
            return "BUY"
        if d == "SHORT":
            return "SELL"
    d = str(r.get("direction") or "").upper()
    if d == "LONG":
        return "WAIT"  # stretch but not actionable yet
    if d == "SHORT":
        return "WAIT"
    return "WAIT"


def compact_pick(r: dict[str, Any], *, rank: int | None = None) -> dict[str, Any]:
    """Normalize one BB result into a chat card row."""
    action = _action_from_result(r)
    direction = str(r.get("direction") or "NONE").upper()
    if action == "BUY":
        side = "LONG"
    elif action == "SELL":
        side = "SHORT"
    else:
        side = "WAIT" if direction in ("NONE", "") else direction

    reasons: list[str] = []
    pe = r.get("plain_english") or r.get("verdict")
    if pe:
        reasons.append(str(pe)[:280])
    for line in (r.get("confidence_reasons") or [])[:4]:
        reasons.append(str(line)[:160])
    extras = r.get("extra_checks_detail") or {}
    if isinstance(extras, dict):
        for k, v in list(extras.items())[:4]:
            if isinstance(v, dict):
                bit = v.get("summary") or v.get("verdict") or v.get("note")
                if bit:
                    reasons.append(f"{k}: {str(bit)[:120]}")
            elif v:
                reasons.append(f"{k}: {str(v)[:120]}")

    conf = r.get("confidence_pct")
    try:
        conf_f = float(conf) if conf is not None else None
    except (TypeError, ValueError):
        conf_f = None

    return {
        "rank": rank,
        "ticker": r.get("ticker"),
        "timeframe": r.get("timeframe"),
        "action": action,
        "side": side,
        "confidence_pct": conf_f,
        "sl_pct": r.get("sl_pct"),
        "tp_pct": r.get("tp_pct"),
        "entry_price": r.get("entry_price") or r.get("ltp"),
        "stop_price": r.get("stop_price"),
        "target_price": r.get("target_price") or r.get("bb_mean"),
        "rr": r.get("rr"),
        "grade": r.get("grade"),
        "take_trade": bool(r.get("take_trade")),
        "signal": r.get("signal"),
        "reason": reasons[0] if reasons else (r.get("verdict") or "No clear setup"),
        "reasons": reasons[:6],
        "error": r.get("error"),
    }


def rank_picks(
    results: list[dict[str, Any]],
    *,
    top_n: int | None = None,
    action_bias: str = "both",
) -> list[dict[str, Any]]:
    """Return all eligible (actionable) picks; if none, all clean reads. Optional top_n cap."""
    clean = [r for r in results if not r.get("error")]
    actionable = [r for r in clean if r.get("take_trade")]
    if action_bias == "buy":
        actionable = [r for r in actionable if str(r.get("direction") or "").upper() == "LONG"]
    elif action_bias == "sell":
        actionable = [r for r in actionable if str(r.get("direction") or "").upper() == "SHORT"]

    actionable.sort(key=lambda r: -(r.get("confidence_pct") or 0))
    rest = [r for r in clean if r not in actionable]
    rest.sort(key=lambda r: -(r.get("confidence_pct") or 0))

    # Eligible = actionable BUY/SELL; if none, surface full scan (no artificial top-10)
    ordered = actionable if actionable else rest
    if top_n is not None:
        ordered = ordered[: max(0, top_n)]
    return [compact_pick(r, rank=i + 1) for i, r in enumerate(ordered)]


def build_chat_ai_context(intent: dict[str, Any], picks: list[dict[str, Any]]) -> str:
    lines = [
        "Dashboard Trading Chat — BB Mean Reversion + full confluence suite.",
        f"User question: {intent.get('raw_message')}",
        f"Asset class: {intent.get('asset_class')} · Style: {intent.get('style_label')} · TF: {intent.get('timeframe')}",
        f"Mode: {intent.get('mode')} · Action bias: {intent.get('action_bias')}",
        f"Confluence checks: {', '.join(intent.get('extra_checks') or [])}",
        "",
        "Structured picks (engine numbers — trust these levels):",
    ]
    for p in picks:
        lines.append(
            f"{p.get('rank')}. {p.get('ticker')} | {p.get('action')}/{p.get('side')} | "
            f"conf={p.get('confidence_pct')}% | SL%={p.get('sl_pct')} | TP%={p.get('tp_pct')} | "
            f"entry={p.get('entry_price')} stop={p.get('stop_price')} tp={p.get('target_price')} | "
            f"{p.get('reason')}"
        )
    lines.append("")
    lines.append(
        "Respond with a clear ranking, BUY/SELL/WAIT per name, %confidence, %SL, %TP, "
        "and a one-line reason. Prefer engine numbers; flag risk if confluence is thin."
    )
    return "\n".join(lines)


TRADING_CHAT_SYSTEM = (
    "You are the Dashboard Trading Chat desk analyst. You only conclude from the BB Mean "
    "Reversion + confluence engine numbers provided. For each name give: action (BUY/SELL/WAIT), "
    "side (LONG/SHORT/WAIT), %confidence, %SL, %TP, and a short reason. Be concise and practical. "
    "This is research/education only — not financial advice. End with: VERDICT: BUY|SELL|WAIT "
    "(overall bias for the user's question)."
)

# ---------------------------------------------------------------------------
# Deep mode — multi-strategy backtest → encyclopedia → live analysis
# ---------------------------------------------------------------------------

_PRO_TRADE_BY_STYLE: dict[str, list[str]] = {
    "scalping": ["bb_mean_reversion", "volume_spread_next_candle", "pa_volume_profile"],
    "intraday": ["bb_mean_reversion", "pa_vp_smc", "pa_volume_profile", "volume_profile_ce", "volume_spread_next_candle"],
    "swing": ["bb_mean_reversion", "volume_profile_ce", "volume_profile_poc", "pa_vp_smc", "elliott_wave_pro"],
    "investing": ["bb_mean_reversion", "volume_profile_poc", "elliott_wave_pro"],
}

_HUB_BY_STYLE: dict[str, list[str]] = {
    "scalping": ["scalp_rectangle", "scalp_multi_indicator", "scalp_sr_mss"],
    "intraday": ["intraday_london_breakout", "support_resistance", "intraday_vwap_fade", "intraday_fib_945"],
    "swing": ["support_resistance", "reversal_strategy", "swing_trading_st", "swing_bb_vwap_reversal"],
    "investing": ["swing_trend_velocity", "support_resistance", "reversal_strategy"],
}

_RULE_BY_STYLE: dict[str, list[str]] = {
    "scalping": [
        "vwap_bounce_scalp",
        "ema_crossover_scalp",
        "bollinger_squeeze_breakout_scalp",
        "orb_1min_scalp",
    ],
    "intraday": [
        "orb_15min_with_retest",
        "vwap_trend_intraday",
        "rsi_divergence_intraday",
        "sr_breakout_pullback_intraday",
        "macd_volume_confirm_intraday",
    ],
    "swing": [
        "golden_death_cross_swing",
        "weekly_rsi_pullback_swing",
        "consolidation_breakout_swing",
        "bollinger_mean_reversion_swing",
    ],
    "investing": [
        "golden_death_cross_swing",
        "weekly_rsi_pullback_swing",
        "relative_strength_sector_rotation_swing",
    ],
}

_KEYWORD_STRATEGY_BOOSTS: list[tuple[list[str], list[str]]] = [
    (["mean reversion", "bollinger", "bb "], ["bb_mean_reversion", "bollinger_mean_reversion_swing"]),
    (["vwap"], ["vwap_bounce_scalp", "vwap_trend_intraday", "intraday_vwap_fade"]),
    (["smc", "smart money", "order block"], ["pa_vp_smc", "smc_cisd", "scalp_smc"]),
    (["fib", "fibonacci"], ["intraday_fib_945", "elliott_wave_pro"]),
    (["volume profile", "poc", "vah"], ["volume_profile_ce", "volume_profile_poc", "pa_volume_profile"]),
    (["elliott", "wave"], ["elliott_wave_pro"]),
    (["reversal"], ["reversal_strategy", "bb_mean_reversion"]),
    (["breakout"], ["consolidation_breakout_swing", "sr_breakout_pullback_intraday", "intraday_london_breakout"]),
    (["ema"], ["ema_crossover_scalp"]),
    (["rsi"], ["rsi_divergence_intraday", "weekly_rsi_pullback_swing"]),
]

# Hub ids that cannot use the generic backtester
_NO_BT = frozenset({
    "swing_5_strategies", "scalp_weekly", "swing_trend_breakout",
    "smc_htf_zone_sweep", "weekly_candle_continuation",
})

PRO_TRADE_LIVE_IDS = frozenset({
    "bb_mean_reversion",
    "pa_vp_smc",
    "pa_volume_profile",
    "volume_profile_ce",
    "volume_profile_poc",
    "volume_spread_next_candle",
    "elliott_wave_pro",
    "elliott_wave",
})


def select_deep_candidates(style: str, message: str, *, limit: int = 10) -> list[str]:
    """Pick backtestable strategy ids matching style + question keywords."""
    from app.strategies.registry import get_strategy_meta

    style_key = style if style in _RULE_BY_STYLE else "intraday"
    ordered: list[str] = []
    for sid in (
        _PRO_TRADE_BY_STYLE.get(style_key, [])
        + _RULE_BY_STYLE.get(style_key, [])
        + _HUB_BY_STYLE.get(style_key, [])
    ):
        if sid not in ordered and sid not in _NO_BT:
            ordered.append(sid)

    lower = (message or "").lower()
    boosts: list[str] = []
    for keys, sids in _KEYWORD_STRATEGY_BOOSTS:
        if any(k in lower for k in keys):
            for sid in sids:
                if sid not in _NO_BT and sid not in boosts:
                    boosts.append(sid)

    merged: list[str] = []
    for sid in boosts + ordered:
        if sid in merged or sid in _NO_BT:
            continue
        meta = get_strategy_meta(sid) or get_strategy_meta(sid.replace("_pro", ""))
        if meta is None and sid not in PRO_TRADE_LIVE_IDS:
            continue
        merged.append(sid)

    if "bb_mean_reversion" not in merged:
        merged.insert(0, "bb_mean_reversion")

    return merged[:limit]


def summarize_strategy_ranking(rows: list[dict[str, Any]], *, top_n: int | None = None) -> list[dict[str, Any]]:
    """Aggregate backtester rows by strategy_id (avg rank_score / win rate)."""
    by_sid: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if r.get("error"):
            continue
        sid = str(r.get("strategy_id") or "")
        if not sid:
            continue
        by_sid.setdefault(sid, []).append(r)

    ranked: list[dict[str, Any]] = []
    for sid, group in by_sid.items():
        trades = sum(int(x.get("num_trades") or 0) for x in group)
        if trades < 1:
            continue
        scores = [float(x.get("rank_score") or 0) for x in group]
        rets = [float(x.get("total_return_pct") or 0) for x in group]
        wins = [float(x.get("win_rate_pct") or 0) for x in group if x.get("win_rate_pct") is not None]
        sharpes = [float(x.get("sharpe_ratio") or 0) for x in group if x.get("sharpe_ratio") is not None]
        label = str(group[0].get("strategy_label") or sid)
        category = str(group[0].get("category") or "")
        ranked.append({
            "strategy_id": sid,
            "strategy_label": label,
            "category": category,
            "tickers_tested": len(group),
            "num_trades": trades,
            "avg_rank_score": round(sum(scores) / max(len(scores), 1), 4),
            "avg_return_pct": round(sum(rets) / max(len(rets), 1), 2),
            "avg_win_rate_pct": round(sum(wins) / max(len(wins), 1), 1) if wins else None,
            "avg_sharpe": round(sum(sharpes) / max(len(sharpes), 1), 2) if sharpes else None,
        })

    ranked.sort(key=lambda x: -(x.get("avg_rank_score") or 0))
    if top_n is not None:
        ranked = ranked[: max(0, top_n)]
    for i, row in enumerate(ranked):
        row["rank"] = i + 1
    return ranked


def load_strategy_guides(strategy_ids: list[str], *, excerpt_chars: int = 900) -> list[dict[str, Any]]:
    """Encyclopedia / section guide excerpts + catalog meta for selected strategies."""
    from app.market_pulse.section_strategy_guides import get_section_guide_body
    from app.strategies.registry import get_strategy_meta

    out: list[dict[str, Any]] = []
    for sid in strategy_ids:
        meta = get_strategy_meta(sid) or {}
        # elliott_wave_pro guide may live under elliott_wave
        body = get_section_guide_body(sid) or get_section_guide_body(sid.replace("_pro", ""))
        excerpt = (body or "").strip()
        if excerpt and len(excerpt) > excerpt_chars:
            excerpt = excerpt[:excerpt_chars].rstrip() + "…"
        out.append({
            "strategy_id": sid,
            "strategy_label": meta.get("name") or sid.replace("_", " ").title(),
            "category": meta.get("category") or meta.get("category_label") or "",
            "summary": meta.get("summary") or meta.get("description") or "",
            "entry_rules": list(meta.get("entry_rules") or [])[:4],
            "exit_rules": list(meta.get("exit_rules") or [])[:3],
            "guide_excerpt": excerpt or None,
            "has_full_guide": bool(body),
        })
    return out


def compact_scan_signal(sig: Any, *, rank: int | None = None) -> dict[str, Any]:
    """Normalize a ScannerService ScanSignal (model or dict) into a chat pick."""
    if hasattr(sig, "model_dump"):
        d = sig.model_dump()
    elif isinstance(sig, dict):
        d = sig
    else:
        d = {
            "ticker": getattr(sig, "ticker", None),
            "strategy": getattr(sig, "strategy", None),
            "action": getattr(sig, "action", "HOLD"),
            "confidence_pct": getattr(sig, "confidence_pct", None),
            "sl_pct": getattr(sig, "sl_pct", None),
            "tp_pct": getattr(sig, "tp_pct", None),
            "price": getattr(sig, "price", None),
            "rationale": getattr(sig, "rationale", None),
            "timeframe": getattr(sig, "timeframe", None),
        }
    action = str(d.get("action") or "HOLD").upper()
    if action == "BUY":
        side = "LONG"
    elif action == "SELL":
        side = "SHORT"
    else:
        action, side = "WAIT", "WAIT"
    return {
        "rank": rank,
        "ticker": d.get("ticker"),
        "timeframe": d.get("timeframe"),
        "action": action,
        "side": side,
        "confidence_pct": d.get("confidence_pct"),
        "sl_pct": d.get("sl_pct"),
        "tp_pct": d.get("tp_pct"),
        "entry_price": d.get("price"),
        "stop_price": None,
        "target_price": None,
        "rr": None,
        "grade": None,
        "take_trade": action in ("BUY", "SELL"),
        "signal": action,
        "reason": d.get("rationale") or f"{d.get('strategy')}: {action}",
        "reasons": [d.get("rationale")] if d.get("rationale") else [],
        "strategy_id": d.get("strategy"),
        "strategy_label": d.get("strategy_label") or d.get("strategy"),
        "error": None,
    }


def merge_live_picks(pick_lists: list[list[dict[str, Any]]], *, top_n: int | None = None) -> list[dict[str, Any]]:
    """Merge multi-strategy live picks — best confidence per ticker; all eligible (no top-10)."""
    by_ticker: dict[str, dict[str, Any]] = {}
    extras: list[dict[str, Any]] = []
    for lst in pick_lists:
        for p in lst:
            t = str(p.get("ticker") or "")
            if not t:
                continue
            cur = by_ticker.get(t)
            score = (1 if p.get("take_trade") else 0, float(p.get("confidence_pct") or 0))
            if cur is None:
                by_ticker[t] = p
            else:
                cur_score = (1 if cur.get("take_trade") else 0, float(cur.get("confidence_pct") or 0))
                if score > cur_score:
                    extras.append(cur)
                    by_ticker[t] = p
                else:
                    extras.append(p)

    primary = list(by_ticker.values())
    primary.sort(key=lambda p: (0 if p.get("take_trade") else 1, -(p.get("confidence_pct") or 0)))
    extras.sort(key=lambda p: (0 if p.get("take_trade") else 1, -(p.get("confidence_pct") or 0)))

    eligible = [p for p in primary if p.get("take_trade")]
    if not eligible:
        eligible = primary
    # Keep alternate strategy hits that are also actionable
    eligible_extras = [p for p in extras if p.get("take_trade")]
    ordered = eligible + eligible_extras
    if top_n is not None:
        ordered = ordered[: max(0, top_n)]
    for i, p in enumerate(ordered):
        p["rank"] = i + 1
    return ordered


def build_deep_ai_context(
    intent: dict[str, Any],
    *,
    ranking: list[dict[str, Any]],
    selected: list[dict[str, Any]],
    picks: list[dict[str, Any]],
) -> str:
    lines = [
        "Dashboard Trading Chat — DEEP MODE.",
        "Pipeline: (1) choose strategies for the question (2) backtest rank (3) encyclopedia how-to "
        "(4) live analysis on winners (5) your conclusion.",
        f"User question: {intent.get('raw_message')}",
        f"Asset class: {intent.get('asset_class')} · Style: {intent.get('style_label')} · TF: {intent.get('timeframe')}",
        "",
        "Backtest ranking (best strategies for this question/universe):",
    ]
    for r in ranking[:8]:
        lines.append(
            f"{r.get('rank')}. {r.get('strategy_label')} ({r.get('strategy_id')}) · "
            f"score={r.get('avg_rank_score')} · ret%={r.get('avg_return_pct')} · "
            f"win%={r.get('avg_win_rate_pct')} · sharpe={r.get('avg_sharpe')} · trades={r.get('num_trades')}"
        )
    lines.append("")
    lines.append("Encyclopedia / how-to for selected strategies:")
    for s in selected:
        lines.append(f"— {s.get('strategy_label')}: {s.get('summary') or ''}")
        if s.get("entry_rules"):
            lines.append(f"  Entry: {'; '.join(str(x) for x in s['entry_rules'][:2])}")
        if s.get("guide_excerpt"):
            lines.append(f"  Guide: {str(s['guide_excerpt'])[:400]}")
    lines.append("")
    lines.append("Live picks after analysis:")
    for p in picks:
        lines.append(
            f"{p.get('rank')}. {p.get('ticker')} | {p.get('action')}/{p.get('side')} | "
            f"conf={p.get('confidence_pct')}% | SL%={p.get('sl_pct')} | TP%={p.get('tp_pct')} | "
            f"via {p.get('strategy_id') or 'bb'} | {p.get('reason')}"
        )
    lines.append("")
    lines.append(
        "Conclude which strategies fit the question, then BUY/SELL/WAIT per ticker with "
        "%confidence %SL %TP and a short reason grounded in backtest + live numbers."
    )
    return "\n".join(lines)


DEEP_CHAT_SYSTEM = (
    "You are the Dashboard Trading Chat Deep Mode desk. You receive (1) backtest-ranked strategies "
    "chosen for the user's question, (2) encyclopedia/how-to excerpts, (3) live analysis picks. "
    "First name the best strategies and why they fit. Then give BUY/SELL/WAIT per ticker with "
    "%confidence, %SL, %TP and a short reason. Research/education only — not financial advice. "
    "End with: VERDICT: BUY|SELL|WAIT."
)
