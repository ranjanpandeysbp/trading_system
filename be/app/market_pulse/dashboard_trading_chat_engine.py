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
    """Liquid scan universe for top-picks mode (capped for latency)."""
    ac = (asset_class or "india").lower()
    if ac == "india":
        from app.market_pulse.ticker_utils import NIFTY_50

        return list(NIFTY_50)[:limit]
    if ac == "us":
        return [
            "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AMD", "NFLX", "AVGO",
            "SPY", "QQQ", "JPM", "V", "MA", "COST", "CRM", "ORCL", "INTC", "BA",
        ][:limit]
    if ac == "crypto":
        return [
            "B-BTCUSDT", "B-ETHUSDT", "B-SOLUSDT", "B-XRPUSDT", "B-DOGEUSDT",
            "B-BNBUSDT", "B-ADAUSDT", "B-AVAXUSDT", "B-LINKUSDT", "B-DOTUSDT",
            "B-MATICUSDT", "B-LTCUSDT", "B-UNIUSDT", "B-ATOMUSDT", "B-NEARUSDT",
        ][:limit]
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
    top_n: int = 10,
    action_bias: str = "both",
) -> list[dict[str, Any]]:
    """Prefer actionable trades; fill with best WAIT reads to reach top_n."""
    clean = [r for r in results if not r.get("error")]
    actionable = [r for r in clean if r.get("take_trade")]
    if action_bias == "buy":
        actionable = [r for r in actionable if str(r.get("direction") or "").upper() == "LONG"]
    elif action_bias == "sell":
        actionable = [r for r in actionable if str(r.get("direction") or "").upper() == "SHORT"]

    actionable.sort(key=lambda r: -(r.get("confidence_pct") or 0))
    rest = [r for r in clean if r not in actionable]
    rest.sort(key=lambda r: -(r.get("confidence_pct") or 0))

    ordered = (actionable + rest)[:top_n]
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
