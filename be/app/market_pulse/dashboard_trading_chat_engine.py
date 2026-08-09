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

    # --- Open market questions (movers / broken S/R) — before BB top_picks ---
    screen_mode: str | None = None
    if any(
        p in lower
        for p in (
            "broke support", "broken support", "support breakdown", "broke down support",
            "support break", "breaking support", "broken recent support",
        )
    ):
        screen_mode = "broken_support"
    elif any(
        p in lower
        for p in (
            "broke resistance", "broken resistance", "resistance breakout",
            "broke out of resistance", "breaking resistance", "broken recent resistance",
        )
    ):
        screen_mode = "broken_resistance"
    elif any(
        p in lower
        for p in (
            "fallen most", "fell most", "top loser", "top losers", "biggest drop",
            "biggest losers", "worst performer", "worst performers", "declined most",
            "down the most", "fallen a lot", "crashed",
        )
    ):
        screen_mode = "fallen_most"
    elif any(
        p in lower
        for p in (
            "top gainer", "top gainers", "risen most", "rose most", "biggest winner",
            "biggest winners", "rallied most", "up the most", "moved up most",
        )
    ):
        screen_mode = "gainers"
    elif any(
        p in lower
        for p in (
            "moved a lot", "moved most", "biggest mover", "biggest movers",
            "most volatile", "24h", "24 hr", "24 hour", "in the last day",
            "today's mover", "todays mover", "session mover", "which moved",
            "what moved", "moved sharply", "sharp move", "volatile",
        )
    ):
        screen_mode = "movers_24h"

    # Force commodity when asking about gold/silver/commodities movers without equity wording
    if screen_mode and any(p in lower for p in ("gold", "silver", "crude", "commodity", "commodities", "oil")):
        if not any(p in lower for p in ("stock", "stocks", "nifty", "equity", "crypto", "bitcoin")):
            detected_ac = "commodity"

    mode = "single" if found else "top_picks"
    # Phrases that force universe scan even if a sector word matched as ticker
    force_universe = any(
        p in lower
        for p in (
            "which stock", "which crypto", "which commodity", "which commodities",
            "what to buy", "what to sell", "top 10", "top ten", "suggest",
            "which gold", "which silver", "what moved", "which moved",
        )
    )
    analyze_named = any(p in lower for p in ("analyze", "analyse", "check "))
    if screen_mode:
        mode = screen_mode
        if not analyze_named:
            found = []
    elif force_universe and len(found) <= 1 and (not found or found[0] in ("NIFTY", "SENSEX", "GOLD", "SILVER")):
        mode = "top_picks"
        found = []

    action_bias = "both"
    if screen_mode == "fallen_most" or screen_mode == "broken_support":
        action_bias = "sell"
    elif screen_mode == "gainers" or screen_mode == "broken_resistance":
        action_bias = "buy"
    elif re.search(r"\b(buy|long|go long)\b", lower) and not re.search(r"\b(sell|short)\b", lower):
        action_bias = "buy"
    elif re.search(r"\b(sell|short|go short)\b", lower) and not re.search(r"\b(buy|long)\b", lower):
        action_bias = "sell"

    return {
        "raw_message": text,
        "mode": mode,  # single | top_picks | movers_24h | gainers | fallen_most | broken_support | broken_resistance
        "asset_class": detected_ac,
        "style": detected_style,
        "style_label": STYLE_LABELS.get(detected_style, detected_style),
        "timeframe": STYLE_TIMEFRAMES.get(detected_style, "15m"),
        "tickers": found[:8],
        "action_bias": action_bias,
        "extra_checks": all_extra_checks(),
        "screen_mode": screen_mode,
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


def build_chat_ai_context(
    intent: dict[str, Any],
    picks: list[dict[str, Any]],
    enrichments: list[dict[str, Any]] | None = None,
) -> str:
    lines = [
        "Dashboard Trading Chat — BB Mean Reversion + confluence, plus suitability enrichments.",
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
    if enrichments:
        lines.append("")
        lines.append("Suitability enrichments (use as context; do not invent levels from them):")
        for enr in enrichments:
            label = enr.get("label") or enr.get("id")
            why = enr.get("why") or ""
            summary = enr.get("summary") or enr.get("error") or "—"
            lines.append(f"- {label}" + (f" [{why}]" if why else "") + f": {summary}")
    lines.append("")
    lines.append(
        "Respond with a clear ranking, BUY/SELL/WAIT per name, %confidence, %SL, %TP, "
        "and a one-line reason. Prefer BB engine numbers for SL/TP; cite enrichments when they "
        "confirm or conflict (especially Options Market Prediction and Call Put Writing walls). "
        "Then add a short **Why** section: explain the logic behind the top picks and any "
        "options/OI enrichment (Call walls, Put floors, short-covering risk). "
        "Flag risk if confluence is thin."
    )
    return "\n".join(lines)


TRADING_CHAT_SYSTEM = (
    "You are the Dashboard Trading Chat desk analyst. Conclude primarily from BB Mean "
    "Reversion + confluence engine numbers, and weigh suitability enrichments "
    "(Elliott Wave, Volume Spread next-candle, Advance/Decline, Comparative Strength, "
    "Oil-Dollar-Bond macro, Options Market Prediction, Options Call Put Writing OI walls, "
    "Trading Hub Intra-Hedging pairs) when provided. For hedge pairs cite LONG/SHORT legs, "
    "spread, and confidence. For Call Put Writing cite Call wall / Put floor / writing tilt / "
    "short-covering risk. For each name give: action (BUY/SELL/WAIT), side (LONG/SHORT/WAIT), "
    "%confidence, %SL, %TP, and a short reason. Always include a brief **Why this result** "
    "paragraph explaining the engine + enrichment logic in plain English. Be concise and "
    "practical. This is research/education only — not financial advice. End with: "
    "VERDICT: BUY|SELL|WAIT (overall bias for the user's question)."
)

EXPLAIN_CHAT_SYSTEM = (
    "You explain Trading Agent desk results to the user. They already have picks and "
    "enrichments — do NOT invent new tickers or levels. Cite BB confluence reasons, "
    "Options Market Prediction / Call Put Writing (OI walls, PCR, short covering), "
    "Intra-Hedging pairs, and other enrichment summaries. Answer their 'why / explain' "
    "question clearly with %confidence meaning, why SL%/TP% were chosen, and what would "
    "invalidate the setup. Research/education only — not financial advice."
)

# ---------------------------------------------------------------------------
# Normal mode — suitability enrichments (outside BB extra_checks)
# ---------------------------------------------------------------------------

NORMAL_ENRICHMENT_LABELS: dict[str, str] = {
    "elliott_wave": "Elliott Wave",
    "volume_spread_next_candle": "Volume Spread (next candle)",
    "advance_decline": "Advance / Decline breadth",
    "comparative_strength": "Comparative Strength",
    "oil_dollar_bond": "Oil · Dollar · Bond macro",
    "options_market_prediction": "Options Market Prediction",
    "options_call_put_writing": "Options Call Put Writing",
    "intra_hedging": "Trading Hub · Intra-Hedging",
}

_DEFAULT_AD_INDEX: dict[str, str] = {
    "india": "NIFTY 50",
    "us": "Dow 30",
    "crypto": "Top 30 Crypto",
    "commodity": "All Commodities",
}

_ENRICH_KEYWORD_BOOSTS: list[tuple[list[str], str, int]] = [
    (["elliott", "wave", "impulse", "corrective"], "elliott_wave", 6),
    (["volume spread", "vsa", "next candle", "no supply", "no demand", "upthrust", "downthrust"], "volume_spread_next_candle", 6),
    (["breadth", "advance decline", "advance/decline", "a/d line", "market breadth", "advancers", "decliners"], "advance_decline", 6),
    (["comparative strength", "relative strength", "stronger than", "weaker than", "outperform", "underperform", "rotation", " vs ", "versus"], "comparative_strength", 6),
    (["oil", "dollar", "dxy", "bond yield", "bonds", "macro", "risk on", "risk-off", "risk off", "gold", "silver", "crude"], "oil_dollar_bond", 5),
    (["option", "options", "pcr", "open interest", "max pain", "vix", "market prediction", "oi buildup"], "options_market_prediction", 6),
    (
        [
            "call writing", "put writing", "call put writing", "call/put writing",
            "oi wall", "call wall", "put floor", "put writing", "short covering",
            "short-covering", "writer", "writers", "resistance wall", "support floor",
        ],
        "options_call_put_writing",
        7,
    ),
    (["hedge", "hedging", "long short", "long/short", "long-short", "pairs trade", "pair trade", "sector pair", "beta neutral", "market neutral", "intra hedge", "intra-hedging"], "intra_hedging", 7),
]

_IH_STOCK_INDEX_HINTS: list[tuple[list[str], str]] = [
    (["bank nifty", "nifty bank", "banking", "bank stock"], "NIFTY BANK"),
    (["private bank"], "NIFTY PRIVATE BANK"),
    (["psu bank"], "NIFTY PSU BANK"),
    (["nifty it", " it stock", "software", "tech stock"], "NIFTY IT"),
    (["pharma", "healthcare"], "NIFTY PHARMA"),
    (["auto ", "automobile"], "NIFTY AUTO"),
    (["fmcg"], "NIFTY FMCG"),
    (["metal", "steel"], "NIFTY METAL"),
    (["realty", "real estate", "housing"], "NIFTY REALTY"),
    (["energy", "oil & gas", "oil and gas"], "NIFTY ENERGY"),
    (["financial service", "fin service", "fin nifty"], "NIFTY FINANCIAL SERVICES"),
    (["midcap"], "NIFTY MIDCAP 150"),
    (["smallcap"], "NIFTY SMALLCAP 250"),
    (["nifty 50", "nifty50", "large cap"], "NIFTY 50"),
    (["next 50"], "NIFTY NEXT 50"),
    (["cement"], "NIFTY CEMENT"),
    (["chemical"], "NIFTY CHEMICALS"),
]


def adapt_intra_hedging_config(
    style: str,
    message: str,
    timeframe: str,
) -> dict[str, Any]:
    """Map chat intent → Intra-Hedging Trading Hub config (query-adapted)."""
    from app.trading_hubs.intra_hedging_engine import (
        FURTHER_ANALYSIS_OPTIONS,
        MOMENTUM_TIMEFRAME_OPTIONS,
        STOCK_MODE_INDEX_OPTIONS,
    )

    style_key = style if style in ("scalping", "intraday", "swing", "investing") else "intraday"
    lower = f" {(message or '').lower()} "
    fa_ids = {o["id"] for o in FURTHER_ANALYSIS_OPTIONS}

    # Momentum TF
    tf = (timeframe or "").strip()
    if tf == "1w":
        tf = "1wk"
    if tf not in MOMENTUM_TIMEFRAME_OPTIONS:
        if style_key == "scalping":
            tf = "5m"
        elif style_key == "swing":
            tf = "1d"
        elif style_key == "investing":
            tf = "1wk"
        else:
            tf = "15m"
    # Explicit TF words in question override
    for cand in ("5m", "15m", "30m", "1h", "4h", "1d", "1wk", "1w"):
        if cand in lower.replace(" ", "") or f" {cand} " in lower or f" {cand}." in lower:
            mapped = "1wk" if cand == "1w" else cand
            if mapped in MOMENTUM_TIMEFRAME_OPTIONS:
                tf = mapped
                break
    if "daily" in lower or "1 day" in lower:
        tf = "1d"
    if "weekly" in lower:
        tf = "1wk"

    # Universe: sector (default) vs stock constituents
    universe_mode = "sector"
    stock_index = "NIFTY BANK"
    stock_hint = False
    for keys, idx in _IH_STOCK_INDEX_HINTS:
        if any(k in lower for k in keys):
            stock_hint = True
            stock_index = idx if idx in STOCK_MODE_INDEX_OPTIONS else "NIFTY BANK"
            break
    force_stock = any(
        k in lower
        for k in ["constituent", "individual stock", "stock mode", "by stock", "stock hedge", "stock pair"]
    )
    force_sector = any(
        k in lower
        for k in [
            "sector mode",
            "sector index",
            "all sectors",
            "nifty sector",
            "sector pair",
            "sector pairs",
            "sector rotation",
            "sector hedge",
            "across sectors",
            "between sectors",
        ]
    )
    if force_stock or (stock_hint and not force_sector):
        universe_mode = "stock"
    if force_sector and not force_stock:
        universe_mode = "sector"

    max_pairs = 3
    if any(k in lower for k in ["one pair", "single pair", "best pair", "top pair"]):
        max_pairs = 1
    elif any(k in lower for k in ["two pair", "2 pair"]):
        max_pairs = 2
    elif any(k in lower for k in ["five pair", "5 pair", "all pairs"]):
        max_pairs = 5
    elif any(k in lower for k in ["four pair", "4 pair"]):
        max_pairs = 4

    further: list[str] = []
    fa_hints = [
        (["smc", "smart money", "order block", "pa-vp", "pa vp"], "pa_vp_smc"),
        (["volume spread", "vsa", "next candle"], "volume_spread_next_candle"),
        (["elliott", "wave"], "elliott_wave"),
        (["bollinger", "mean reversion", "bb "], "bb_mean_reversion"),
        (["support", "resistance", "s/r"], "support_resistance"),
        (["mtf", "trend strength", "adx"], "mtf_trend_strength"),
    ]
    for keys, fid in fa_hints:
        if fid in fa_ids and any(k in lower for k in keys):
            further.append(fid)
    if not further:
        if style_key in ("scalping", "intraday"):
            further = [f for f in ("bb_mean_reversion", "support_resistance", "volume_spread_next_candle") if f in fa_ids]
        elif style_key == "swing":
            further = [f for f in ("elliott_wave", "mtf_trend_strength", "support_resistance") if f in fa_ids]
        else:
            further = [f for f in ("mtf_trend_strength", "bb_mean_reversion") if f in fa_ids]

    return {
        "momentum_timeframe": tf,
        "universe_mode": universe_mode,
        "stock_index": stock_index if stock_index in STOCK_MODE_INDEX_OPTIONS else "NIFTY BANK",
        "max_pairs": max(1, min(5, max_pairs)),
        "further_analysis": further[:4],
        "total_capital": 500_000.0,
    }


def select_normal_enrichments(
    style: str,
    asset_class: str,
    message: str,
    *,
    mode: str = "top_picks",
    timeframe: str = "15m",
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Pick complementary desks by style / asset / keywords (max `limit`)."""
    style_key = style if style in ("scalping", "intraday", "swing", "investing") else "intraday"
    ac = (asset_class or "india").strip().lower()
    lower = f" {(message or '').lower()} "
    scores: dict[str, float] = {}
    why: dict[str, list[str]] = {}

    def _bump(eid: str, pts: float, reason: str) -> None:
        scores[eid] = scores.get(eid, 0.0) + pts
        why.setdefault(eid, []).append(reason)

    # Style defaults
    if style_key == "scalping":
        _bump("volume_spread_next_candle", 3.5, "scalping style")
        if ac == "india":
            _bump("intra_hedging", 3.0, "Trading Hub Intra-Hedging (default)")
    elif style_key == "intraday":
        _bump("volume_spread_next_candle", 3.0, "intraday style")
        _bump("advance_decline", 1.5, "intraday market breadth")
        if ac == "india":
            _bump("options_market_prediction", 2.0, "India intraday options tape")
            _bump("options_call_put_writing", 1.8, "India Call/Put writing walls")
            _bump("intra_hedging", 4.0, "Trading Hub Intra-Hedging default")
    elif style_key == "swing":
        _bump("elliott_wave", 3.5, "swing style")
        _bump("advance_decline", 2.0, "swing market breadth")
        _bump("comparative_strength", 1.5, "swing relative strength")
        if ac == "india":
            _bump("intra_hedging", 3.0, "Intra-Hedging swing rotation")
            _bump("options_call_put_writing", 1.2, "swing OI walls context")
    else:  # investing
        _bump("elliott_wave", 3.0, "investing style")
        _bump("comparative_strength", 3.0, "investing relative strength")
        _bump("advance_decline", 2.0, "investing breadth")

    # Asset suitability
    if ac in ("commodity", "us", "crypto"):
        _bump("oil_dollar_bond", 2.5 if ac == "commodity" else 1.5, f"{ac} macro tape")
    if ac == "india" and "options_market_prediction" not in scores:
        _bump("options_market_prediction", 1.0, "India options desk available")
    if ac == "india" and "options_call_put_writing" not in scores:
        _bump("options_call_put_writing", 0.9, "India Call/Put writing desk available")

    if mode == "top_picks":
        _bump("comparative_strength", 1.0, "top-picks ranking")
        if ac in ("india", "us", "crypto"):
            _bump("advance_decline", 0.8, "universe breadth check")

    for keys, eid, pts in _ENRICH_KEYWORD_BOOSTS:
        if eid in ("options_market_prediction", "options_call_put_writing", "intra_hedging") and ac != "india":
            continue
        if any(k in lower for k in keys):
            _bump(eid, float(pts), f"question mentions {keys[0]}")

    # Options desks + Intra-Hedging are India-only
    if ac != "india":
        for oid in ("options_market_prediction", "options_call_put_writing", "intra_hedging"):
            scores.pop(oid, None)
            why.pop(oid, None)

    # Extra slots when Intra-Hedging and/or both options desks are in play
    extra = 0
    if "intra_hedging" in scores and scores["intra_hedging"] >= 1.5:
        extra += 1
    opts_hot = sum(
        1
        for oid in ("options_market_prediction", "options_call_put_writing")
        if scores.get(oid, 0) >= 1.5
    )
    if opts_hot >= 2:
        extra += 1
    eff_limit = limit + extra

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    chosen = [eid for eid, sc in ranked if sc >= 1.5][: max(1, eff_limit)]
    if not chosen and ranked:
        chosen = [ranked[0][0]]

    # Always keep Intra-Hedging when it scored (India trading default)
    if "intra_hedging" in scores and scores["intra_hedging"] >= 2.5 and "intra_hedging" not in chosen:
        if len(chosen) >= eff_limit and chosen:
            chosen[-1] = "intra_hedging"
        else:
            chosen.append("intra_hedging")

    # Keep Call Put Writing when the question heavily targets OI walls
    if (
        "options_call_put_writing" in scores
        and scores["options_call_put_writing"] >= 5.0
        and "options_call_put_writing" not in chosen
    ):
        if len(chosen) >= eff_limit and chosen:
            chosen[-1] = "options_call_put_writing"
        else:
            chosen.append("options_call_put_writing")

    out: list[dict[str, Any]] = []
    for eid in chosen:
        item: dict[str, Any] = {
            "id": eid,
            "label": NORMAL_ENRICHMENT_LABELS.get(eid, eid),
            "score": round(scores.get(eid, 0), 2),
            "why": "; ".join(why.get(eid, [])[:3]) or "suitability",
        }
        if eid == "intra_hedging":
            item["config"] = adapt_intra_hedging_config(style_key, message, timeframe)
        out.append(item)
    return out


def is_explain_followup(message: str) -> bool:
    """True when the user is asking why / for an explanation of a prior desk result."""
    lower = f" {(message or '').lower()} "
    triggers = (
        " why ",
        "why did",
        "why does",
        "why is",
        "why are",
        "explain",
        "explanation",
        "how did you",
        "how come",
        "rationale",
        "reason behind",
        "behind this",
        "behind the",
        "what makes you",
        "walk me through",
        "justify",
    )
    return any(t in lower for t in triggers)


def build_explain_ai_context(
    message: str,
    prior: dict[str, Any],
) -> str:
    """Compact prior desk payload for a follow-up why/explain question."""
    picks = list(prior.get("picks") or [])[:12]
    enrichments = list(prior.get("enrichments") or [])[:8]
    hedge = list(prior.get("hedge_pairs") or [])[:5]
    ai = prior.get("ai") if isinstance(prior.get("ai"), dict) else {}
    lines = [
        "Trading Agent — explain prior result (do not invent new tickers or levels).",
        f"User follow-up: {message}",
        f"Prior asset_class={prior.get('asset_class')} style={prior.get('style')} "
        f"TF={prior.get('timeframe')} mode={prior.get('mode')}",
        "",
        "Prior picks:",
    ]
    for p in picks:
        if not isinstance(p, dict):
            continue
        lines.append(
            f"{p.get('rank')}. {p.get('ticker')} | {p.get('action')}/{p.get('side')} | "
            f"conf={p.get('confidence_pct')}% | SL%={p.get('sl_pct')} | TP%={p.get('tp_pct')} | "
            f"{p.get('reason')}"
        )
    if enrichments:
        lines.append("")
        lines.append("Prior enrichments:")
        for enr in enrichments:
            if not isinstance(enr, dict):
                continue
            label = enr.get("label") or enr.get("id")
            why = enr.get("why") or ""
            summary = enr.get("summary") or enr.get("error") or "—"
            lines.append(f"- {label}" + (f" [{why}]" if why else "") + f": {summary}")
    if hedge:
        lines.append("")
        lines.append("Prior Intra-Hedging pairs:")
        for p in hedge:
            if not isinstance(p, dict):
                continue
            lines.append(
                f"- LONG {p.get('long_label') or p.get('long_ticker')} / "
                f"SHORT {p.get('short_label') or p.get('short_ticker')} · "
                f"conf {p.get('confidence_pct')}% · spread {p.get('spread_pct')}%"
            )
    if ai.get("report"):
        lines.append("")
        lines.append("Prior AI conclusion (for reference):")
        lines.append(str(ai.get("report"))[:1200])
    if prior.get("summary"):
        lines.append("")
        lines.append(f"Prior summary:\n{str(prior.get('summary'))[:800]}")
    lines.append("")
    lines.append(
        "Explain clearly: why these actions/confidence/SL/TP, how options desks "
        "(Market Prediction / Call Put Writing) influenced the read if present, "
        "and what would invalidate the setups."
    )
    return "\n".join(lines)


def default_ad_index(asset_class: str) -> str:
    return _DEFAULT_AD_INDEX.get((asset_class or "india").lower(), "NIFTY 50")


def summarize_enrichment_payload(eid: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    """Compact one enrichment for AI context + FE."""
    label = NORMAL_ENRICHMENT_LABELS.get(eid, eid)
    if not payload or not isinstance(payload, dict):
        return {"id": eid, "label": label, "summary": "Unavailable", "error": "empty payload", "ticker_signals": []}
    if payload.get("error"):
        return {
            "id": eid,
            "label": label,
            "summary": str(payload.get("error"))[:240],
            "error": str(payload.get("error"))[:240],
            "ticker_signals": [],
        }

    ticker_signals: list[dict[str, Any]] = []
    summary = ""

    if eid in ("elliott_wave", "volume_spread_next_candle"):
        rows = list(payload.get("results") or payload.get("entries") or [])
        bits: list[str] = []
        for r in rows[:8]:
            if not isinstance(r, dict) or r.get("error"):
                continue
            t = r.get("ticker")
            direction = str(r.get("direction") or "").upper()
            take = bool(r.get("take_trade"))
            conf = r.get("confidence_pct")
            pe = str(r.get("plain_english") or r.get("verdict") or r.get("signal") or "")[:140]
            if take or direction in ("LONG", "SHORT"):
                ticker_signals.append({
                    "ticker": t,
                    "side": "LONG" if direction == "LONG" else "SHORT" if direction == "SHORT" else "WAIT",
                    "take_trade": take,
                    "confidence_pct": conf,
                    "note": pe,
                })
            if t:
                bits.append(
                    f"{t} {direction or '—'}"
                    + (f" {conf}%" if conf is not None else "")
                    + (" ✓" if take else "")
                )
        summary = "; ".join(bits) if bits else (str(payload.get("disclaimer") or "No live setups")[:200])

    elif eid == "advance_decline":
        pe = payload.get("plain_english") or payload.get("outcome_layman") or payload.get("summary")
        latest = payload.get("latest") if isinstance(payload.get("latest"), dict) else {}
        ratio = latest.get("ad_ratio") or latest.get("advance_decline_ratio")
        summary = str(pe or "")[:280]
        if ratio is not None and "ratio" not in summary.lower():
            summary = (summary + f" · A/D ratio {ratio}").strip(" ·")

    elif eid == "comparative_strength":
        pe = payload.get("summary") or payload.get("plain_english")
        stronger = [str(x.get("symbol") if isinstance(x, dict) else x) for x in (payload.get("stronger") or [])[:5]]
        weaker = [str(x.get("symbol") if isinstance(x, dict) else x) for x in (payload.get("weaker") or [])[:5]]
        ideas = payload.get("trade_ideas") or []
        for idea in ideas[:6]:
            if not isinstance(idea, dict):
                continue
            action = str(idea.get("action") or idea.get("side") or idea.get("bias") or "WAIT").upper()
            side = "LONG" if "LONG" in action else "SHORT" if "SHORT" in action else "WAIT"
            ticker_signals.append({
                "ticker": idea.get("symbol") or idea.get("ticker"),
                "side": side,
                "take_trade": side in ("LONG", "SHORT") and "WATCH" not in action,
                "confidence_pct": idea.get("confidence_pct"),
                "note": str(idea.get("reason") or idea.get("summary") or "")[:140],
            })
        summary = str(pe or "")[:160]
        if stronger:
            summary = (summary + f" · Stronger: {', '.join(stronger)}").strip(" ·")
        if weaker:
            summary = (summary + f" · Weaker: {', '.join(weaker)}").strip(" ·")

    elif eid == "intra_hedging":
        pairs = list(payload.get("pair_recommendations") or [])
        bits: list[str] = []
        mode = payload.get("universe_mode") or ""
        desc = payload.get("universe_desc") or ""
        for p in pairs[:5]:
            if not isinstance(p, dict):
                continue
            long_t = p.get("long_label") or p.get("long_ticker")
            short_t = p.get("short_label") or p.get("short_ticker")
            conf = p.get("confidence_pct")
            spread = p.get("spread_pct")
            bits.append(
                f"#{p.get('pair_rank') or '?'} LONG {long_t} / SHORT {short_t}"
                + (f" · {conf}%" if conf is not None else "")
                + (f" · spread {spread}%" if spread is not None else "")
            )
            if p.get("long_ticker"):
                ticker_signals.append({
                    "ticker": p.get("long_ticker"),
                    "side": "LONG",
                    "take_trade": True,
                    "confidence_pct": conf,
                    "note": f"Intra-hedge LONG vs {short_t}",
                })
            if p.get("short_ticker"):
                ticker_signals.append({
                    "ticker": p.get("short_ticker"),
                    "side": "SHORT",
                    "take_trade": True,
                    "confidence_pct": conf,
                    "note": f"Intra-hedge SHORT vs {long_t}",
                })
        head = f"{mode} {desc}".strip()
        summary = (head + " · " if head else "") + ("; ".join(bits) if bits else "No hedge pairs")
        summary = summary[:400]

    elif eid == "oil_dollar_bond":
        summary = str(payload.get("plain_english") or payload.get("summary") or "")[:300]

    elif eid == "options_market_prediction":
        synth = payload.get("synthesis") if isinstance(payload.get("synthesis"), dict) else payload
        pe = (synth or {}).get("plain_english") or payload.get("plain_english")
        view = (synth or {}).get("market_view") or payload.get("market_view")
        stance = (synth or {}).get("risk_stance") or payload.get("risk_stance")
        score = (synth or {}).get("composite_score") or payload.get("composite_score")
        outlook = payload.get("outlook") if isinstance(payload.get("outlook"), dict) else {}
        bits = [str(pe or "")[:200]]
        if view:
            bits.append(f"view={view}")
        if stance:
            bits.append(f"stance={stance}")
        if score is not None:
            bits.append(f"score={score}")
        if outlook.get("plain_english"):
            bits.append(str(outlook.get("plain_english"))[:120])
        trade = payload.get("trade_suggestion")
        if isinstance(trade, dict) and trade.get("summary"):
            bits.append(str(trade.get("summary"))[:120])
        summary = " · ".join(b for b in bits if b)

    elif eid == "options_call_put_writing":
        pe = payload.get("plain_english")
        view = payload.get("market_view")
        stance = payload.get("risk_stance")
        writing = payload.get("writing") if isinstance(payload.get("writing"), dict) else {}
        walls = payload.get("walls") if isinstance(payload.get("walls"), dict) else {}
        covering = payload.get("short_covering") if isinstance(payload.get("short_covering"), dict) else {}
        trade = payload.get("trade_suggestion") if isinstance(payload.get("trade_suggestion"), dict) else {}
        call_wall = (walls.get("primary_call_wall") or {}) if isinstance(walls, dict) else {}
        put_floor = (walls.get("primary_put_floor") or {}) if isinstance(walls, dict) else {}
        bits = [str(pe or "")[:200]]
        if view:
            bits.append(f"view={view}")
        if stance:
            bits.append(f"risk={stance}")
        if writing.get("tilt"):
            bits.append(f"tilt={writing.get('tilt')}")
        if call_wall.get("strike") is not None:
            bits.append(f"Call wall {call_wall.get('strike')}")
        if put_floor.get("strike") is not None:
            bits.append(f"Put floor {put_floor.get('strike')}")
        if covering.get("note"):
            bits.append(str(covering.get("note"))[:120])
        if payload.get("pcr_oi") is not None:
            bits.append(f"PCR(OI)={payload.get('pcr_oi')}")
        if trade.get("action"):
            bits.append(
                f"trade {trade.get('action')} conf={trade.get('confidence_pct')} "
                f"SL={trade.get('sl_pct')} TP={trade.get('tp_pct')}"
            )
        summary = " · ".join(b for b in bits if b)[:400]
        # Index-level signal for nudge when user scanned NIFTY-like names
        sym = str(payload.get("symbol") or "NIFTY").upper()
        side = str(trade.get("side") or "").upper()
        act = str(trade.get("action") or "").upper()
        if act == "BUY":
            side = "LONG"
        elif act == "SELL":
            side = "SHORT"
        if side in ("LONG", "SHORT"):
            ticker_signals.append({
                "ticker": sym,
                "side": side,
                "take_trade": bool(act in ("BUY", "SELL")),
                "confidence_pct": trade.get("confidence_pct"),
                "note": str(writing.get("note") or covering.get("note") or pe or "")[:140],
            })

    else:
        summary = str(payload.get("plain_english") or payload.get("summary") or "ok")[:240]

    return {
        "id": eid,
        "label": label,
        "summary": summary or "No summary",
        "ticker_signals": ticker_signals,
        "error": None,
    }


def apply_enrichments_to_picks(
    picks: list[dict[str, Any]],
    enrichments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """When a ticker-level enrichment agrees with pick side, nudge confidence + note."""
    if not picks or not enrichments:
        return picks

    agree_boost = 4.0
    by_t: dict[str, list[dict[str, Any]]] = {}
    for enr in enrichments:
        label = str(enr.get("label") or enr.get("id") or "enrichment")
        for sig in enr.get("ticker_signals") or []:
            if not isinstance(sig, dict):
                continue
            t = str(sig.get("ticker") or "").strip().upper()
            if not t:
                continue
            by_t.setdefault(t, []).append({**sig, "_label": label})

    out: list[dict[str, Any]] = []
    for p in picks:
        row = dict(p)
        t = str(row.get("ticker") or "").strip().upper()
        side = str(row.get("side") or "").upper()
        reasons = list(row.get("reasons") or [])
        conf = row.get("confidence_pct")
        try:
            conf_f = float(conf) if conf is not None else None
        except (TypeError, ValueError):
            conf_f = None

        for sig in by_t.get(t, []):
            sig_side = str(sig.get("side") or "").upper()
            note = str(sig.get("note") or "")[:120]
            label = sig.get("_label")
            if sig_side in ("LONG", "SHORT") and side in ("LONG", "SHORT"):
                if sig_side == side and sig.get("take_trade"):
                    if conf_f is not None:
                        conf_f = min(96.0, conf_f + agree_boost)
                    reasons.append(f"{label} agrees ({sig_side})" + (f": {note}" if note else ""))
                elif sig_side != side and sig.get("take_trade"):
                    reasons.append(f"{label} conflicts ({sig_side})" + (f": {note}" if note else ""))
                    if conf_f is not None:
                        conf_f = max(20.0, conf_f - 3.0)
            elif note:
                reasons.append(f"{label}: {note}")

        if conf_f is not None:
            row["confidence_pct"] = round(conf_f, 1)
        if reasons:
            row["reasons"] = reasons[:8]
            row["reason"] = reasons[0]
        out.append(row)
    return out

# ---------------------------------------------------------------------------
# Deep mode — multi-strategy backtest → Strategies catalog → live analysis
# ---------------------------------------------------------------------------

_PRO_TRADE_BY_STYLE: dict[str, list[str]] = {
    "scalping": ["bb_mean_reversion", "volume_spread_next_candle", "pa_volume_profile"],
    "intraday": ["bb_mean_reversion", "pa_vp_smc", "pa_volume_profile", "volume_profile_ce", "volume_spread_next_candle"],
    "swing": ["bb_mean_reversion", "volume_profile_ce", "volume_profile_poc", "pa_vp_smc", "elliott_wave_pro"],
    "investing": ["bb_mean_reversion", "volume_profile_poc", "elliott_wave_pro"],
}

_HUB_BY_STYLE: dict[str, list[str]] = {
    "scalping": ["scalp_rectangle", "scalp_multi_indicator", "scalp_sr_mss"],
    "intraday": ["intra_hedging", "intraday_london_breakout", "support_resistance", "intraday_vwap_fade", "intraday_fib_945"],
    "swing": ["intra_hedging", "support_resistance", "reversal_strategy", "swing_trading_st", "swing_bb_vwap_reversal"],
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
    (["hedge", "hedging", "long short", "pairs", "beta neutral", "sector rotation"], ["intra_hedging"]),
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
    """Load strategy details from the Strategies catalog API (not encyclopedia).

    Source: STRATEGIES_CATALOG_BASE_URL (default http://31.97.237.200:2008)
    — same host as the Strategies UI at /strategies; details from /api/v1/strategies[/{id}].
    Falls back to local registry meta if remote is unreachable.
    """
    import logging

    import requests

    from app.core.config import settings
    from app.strategies.registry import get_strategy_meta

    logger = logging.getLogger(__name__)
    base = (settings.strategies_catalog_base_url or "http://31.97.237.200:2008").rstrip("/")
    by_id: dict[str, dict[str, Any]] = {}

    try:
        resp = requests.get(f"{base}/api/v1/strategies", timeout=25)
        resp.raise_for_status()
        payload = resp.json()
        rows = payload if isinstance(payload, list) else list(payload.get("strategies") or [])
        for row in rows:
            if isinstance(row, dict) and row.get("id"):
                by_id[str(row["id"])] = row
    except Exception as exc:
        logger.warning("Strategies catalog list fetch failed (%s): %s", base, exc)

    out: list[dict[str, Any]] = []
    for sid in strategy_ids:
        meta = by_id.get(sid)
        if meta is None:
            # Per-id fetch (covers ids missing from list / aliases)
            try:
                r2 = requests.get(f"{base}/api/v1/strategies/{sid}", timeout=15)
                if r2.status_code == 200:
                    meta = r2.json() if isinstance(r2.json(), dict) else None
                    if meta and meta.get("id"):
                        by_id[str(meta["id"])] = meta
                elif sid.endswith("_pro"):
                    alt = sid.replace("_pro", "")
                    r3 = requests.get(f"{base}/api/v1/strategies/{alt}", timeout=15)
                    if r3.status_code == 200 and isinstance(r3.json(), dict):
                        meta = r3.json()
            except Exception as exc:
                logger.debug("Strategies catalog detail fetch failed for %s: %s", sid, exc)

        if not meta:
            local = get_strategy_meta(sid) or get_strategy_meta(sid.replace("_pro", "")) or {}
            meta = {
                "id": sid,
                "name": local.get("name") or sid.replace("_", " ").title(),
                "category": local.get("category") or "",
                "category_label": local.get("category_label") or "",
                "summary": local.get("summary") or local.get("description") or "",
                "description": local.get("description") or local.get("summary") or "",
                "indicators": list(local.get("indicators") or []),
                "entry_rules": list(local.get("entry_rules") or []),
                "exit_rules": list(local.get("exit_rules") or []),
                "source": "local_registry_fallback",
            }
        else:
            meta = {**meta, "source": f"{base}/strategies"}

        summary = str(meta.get("summary") or meta.get("description") or "")
        desc = str(meta.get("description") or "")
        # Build a how-to style excerpt from catalog fields (no encyclopedia)
        parts: list[str] = []
        if summary:
            parts.append(summary)
        if desc and desc != summary:
            parts.append(desc)
        indicators = meta.get("indicators") or []
        if indicators:
            parts.append("Indicators: " + ", ".join(str(x) for x in indicators[:8]))
        entry_rules = list(meta.get("entry_rules") or [])
        exit_rules = list(meta.get("exit_rules") or [])
        if entry_rules:
            parts.append("Entry: " + "; ".join(str(x) for x in entry_rules[:4]))
        if exit_rules:
            parts.append("Exit: " + "; ".join(str(x) for x in exit_rules[:3]))
        excerpt = "\n".join(parts).strip()
        if excerpt and len(excerpt) > excerpt_chars:
            excerpt = excerpt[:excerpt_chars].rstrip() + "…"

        out.append({
            "strategy_id": sid,
            "strategy_label": meta.get("name") or sid.replace("_", " ").title(),
            "category": meta.get("category_label") or meta.get("category") or "",
            "summary": summary,
            "entry_rules": entry_rules[:4],
            "exit_rules": exit_rules[:3],
            "indicators": list(indicators)[:8],
            "guide_excerpt": excerpt or None,
            "has_full_guide": bool(excerpt),
            "source": meta.get("source") or f"{base}/strategies",
            "timeframes": list(meta.get("timeframes") or []),
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
        "Pipeline: (1) choose strategies for the question (2) backtest rank (3) Strategies catalog "
        "how-to from /strategies (4) live analysis on winners (5) your conclusion.",
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
    lines.append("Strategies catalog details (from Strategies page / API) for selected strategies:")
    for s in selected:
        lines.append(f"— {s.get('strategy_label')}: {s.get('summary') or ''}")
        if s.get("entry_rules"):
            lines.append(f"  Entry: {'; '.join(str(x) for x in s['entry_rules'][:2])}")
        if s.get("guide_excerpt"):
            lines.append(f"  How-to: {str(s['guide_excerpt'])[:400]}")
        if s.get("source"):
            lines.append(f"  Source: {s.get('source')}")
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
        "%confidence %SL %TP and a short reason grounded in backtest + Strategies catalog + live numbers."
    )
    return "\n".join(lines)


DEEP_CHAT_SYSTEM = (
    "You are the Dashboard Trading Chat Deep Mode desk. You receive (1) backtest-ranked strategies "
    "chosen for the user's question, (2) strategy details from the Strategies catalog "
    "(http host /strategies → /api/v1/strategies), (3) live analysis picks. "
    "First name the best strategies and why they fit using the catalog how-to. Then give BUY/SELL/WAIT "
    "per ticker with %confidence, %SL, %TP and a short reason. Research/education only — not financial "
    "advice. End with: VERDICT: BUY|SELL|WAIT."
)

# ---------------------------------------------------------------------------
# Open screens — movers / broken support-resistance
# ---------------------------------------------------------------------------

SCREEN_MODES = frozenset({
    "movers_24h", "gainers", "fallen_most", "broken_support", "broken_resistance",
})

_DEFAULT_MOVER_INDEX: dict[str, str] = {
    "india": "NIFTY 50",
    "us": "sp500",
    "crypto": "All CoinDCX USDT",
    "commodity": "All Commodities",
}


def default_mover_index(asset_class: str) -> str:
    return _DEFAULT_MOVER_INDEX.get((asset_class or "india").lower(), "NIFTY 50")


def is_screen_mode(mode: str | None) -> bool:
    return (mode or "") in SCREEN_MODES


def compact_mover_pick(
    row: dict[str, Any],
    *,
    rank: int | None = None,
    side: str = "WATCH",
    source: str = "market_movers",
) -> dict[str, Any]:
    """Normalize a gainer/loser row into a chat pick."""
    pct = row.get("pct")
    try:
        pct_f = float(pct) if pct is not None else None
    except (TypeError, ValueError):
        pct_f = None
    if side == "BUY" or (side == "WATCH" and pct_f is not None and pct_f >= 0):
        action, side_out = "BUY", "LONG"
    elif side == "SELL" or (side == "WATCH" and pct_f is not None and pct_f < 0):
        action, side_out = "SELL", "SHORT"
    else:
        action, side_out = "WAIT", "WAIT"

    conf = None
    if pct_f is not None:
        conf = round(min(95.0, max(35.0, abs(pct_f) * 8.0)), 1)

    sym = row.get("symbol") or row.get("ticker") or row.get("pair")
    last = row.get("last") or row.get("price")
    reason = f"{pct_f:+.2f}% move ({source})" if pct_f is not None else f"Mover via {source}"

    return {
        "rank": rank,
        "ticker": sym,
        "timeframe": "1d",
        "action": action,
        "side": side_out,
        "confidence_pct": conf,
        "sl_pct": None,
        "tp_pct": None,
        "entry_price": last,
        "stop_price": None,
        "target_price": None,
        "rr": None,
        "grade": None,
        "take_trade": action in ("BUY", "SELL"),
        "signal": action,
        "reason": reason,
        "reasons": [reason],
        "pct_change": pct_f,
        "strategy_id": "market_movers",
        "strategy_label": "Market Movers",
        "error": None,
    }


def compact_break_pick(result: dict[str, Any], *, rank: int | None = None) -> dict[str, Any] | None:
    """Normalize trade-setup S/R breakout result into a chat pick."""
    if result.get("error"):
        return None
    bo = result.get("breakout") or {}
    event = str(bo.get("event") or "NONE").upper()
    if event not in ("RESISTANCE_BREAKOUT", "SUPPORT_BREAKDOWN"):
        return None

    if event == "SUPPORT_BREAKDOWN":
        action, side = "SELL", "SHORT"
        label = "Support breakdown"
    else:
        action, side = "BUY", "LONG"
        label = "Resistance breakout"

    level = bo.get("level")
    vol_ok = bo.get("volume_confirmed")
    price = result.get("price")
    reason_bits = [label]
    if level is not None:
        reason_bits.append(f"level {level}")
    if vol_ok is not None:
        reason_bits.append("volume confirmed" if vol_ok else "volume weak")
    reason = " · ".join(reason_bits)

    conf = 72.0 if vol_ok else 55.0
    return {
        "rank": rank,
        "ticker": result.get("ticker"),
        "timeframe": result.get("timeframe"),
        "action": action,
        "side": side,
        "confidence_pct": conf,
        "sl_pct": None,
        "tp_pct": None,
        "entry_price": price,
        "stop_price": None,
        "target_price": None,
        "rr": None,
        "grade": None,
        "take_trade": True,
        "signal": event,
        "reason": reason,
        "reasons": [reason],
        "break_event": event,
        "break_level": level,
        "strategy_id": "support_resistance_break",
        "strategy_label": "S/R Break",
        "error": None,
    }


def build_screen_ai_context(intent: dict[str, Any], picks: list[dict[str, Any]], *, source: str = "") -> str:
    mode = str(intent.get("mode") or "")
    lines = [
        "Trading Agent — open market screen (not BB mean-reversion).",
        f"User question: {intent.get('raw_message')}",
        f"Screen mode: {mode} · Asset class: {intent.get('asset_class')} · Source: {source}",
        "",
        "Screen results:",
    ]
    for p in picks:
        extra = ""
        if p.get("pct_change") is not None:
            extra = f" · move={p.get('pct_change')}%"
        if p.get("break_event"):
            extra = f" · {p.get('break_event')} @ {p.get('break_level')}"
        lines.append(
            f"{p.get('rank')}. {p.get('ticker')} | {p.get('action')}/{p.get('side')} | "
            f"conf={p.get('confidence_pct')}%{extra} | {p.get('reason')}"
        )
    lines.append("")
    if mode in ("movers_24h", "gainers", "fallen_most"):
        lines.append(
            "Rank by absolute % move. Separate gainers vs losers. Do NOT invent SL/TP. "
            "Suggest 1–3 names worth a follow-up analyze; do not auto-BUY every gainer."
        )
    else:
        lines.append(
            "Only cite names with confirmed break events. Mention level + volume. "
            "Breakdown → SELL bias; breakout → BUY bias; WAIT if volume weak. Do not invent SL/TP."
        )
    lines.append("End with: VERDICT: BUY|SELL|WAIT")
    return "\n".join(lines)


SCREEN_CHAT_SYSTEM = (
    "You are the Trading Agent desk answering open market questions (movers, gainers/losers, "
    "broken support/resistance). Use only the screen numbers provided. Be concise. "
    "Research/education only — not financial advice. End with: VERDICT: BUY|SELL|WAIT."
)
