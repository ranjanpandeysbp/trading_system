"""
Shared UI helpers — per-ticker collapsible sections for Technical Analysis tabs.
"""

from __future__ import annotations

from typing import Any

_VERDICT_ICONS: dict[str, str] = {
    "BUY": "🟢",
    "SELL": "🔴",
    "TOP PICK": "🟢",
    "DEPLOY": "🟢",
    "SEASONAL BUY": "🟢",
    "LONG": "🟢",
    "SHORT": "🔴",
    "HOLD": "🟡",
    "WAIT": "🟡",
    "WATCH": "🟡",
    "MIXED": "🟠",
    "AVOID": "⚪",
    "ERROR": "❌",
    "NO SETUP": "⚪",
}


def verdict_icon(verdict: str | None) -> str:
    return _VERDICT_ICONS.get((verdict or "").upper(), "📊")


def ticker_section_label(ticker: str, summaries: list[dict]) -> str:
    """One-line expander title for a ticker's combined multi-timeframe results."""
    n = len(summaries)
    if not n:
        return f"📊 **{ticker}**"
    errs = sum(1 for s in summaries if s.get("verdict") == "ERROR")
    tfs = ", ".join(sorted({str(s.get("timeframe") or "?") for s in summaries}))
    if errs == n:
        return f"❌ **{ticker}** — {n} timeframe(s) failed"
    valid = [s for s in summaries if s.get("verdict") != "ERROR"]
    best = max(valid, key=lambda x: float(x.get("score", 0) or 0))
    icon = verdict_icon(best.get("verdict"))
    verdict = best.get("verdict", "—")
    score = float(best.get("score", 0) or 0)
    ok = n - errs
    if errs:
        return f"{icon} **{ticker}** — {verdict} ({score:.1f}/10) · {ok}/{n} OK · `{tfs}`"
    return f"{icon} **{ticker}** — {verdict} ({score:.1f}/10) · {n} TF · `{tfs}`"


def tf_section_label(tf: str, summary: dict | None, *, extra: str = "") -> str:
    """One-line expander title for a single ticker × timeframe block."""
    if not summary or summary.get("verdict") == "ERROR":
        msg = (summary or {}).get("action") or (summary or {}).get("summary") or "failed"
        return f"❌ **{tf}** — {str(msg)[:80]}"
    icon = verdict_icon(summary.get("verdict"))
    verdict = summary.get("verdict", "—")
    score = float(summary.get("score", 0) or 0)
    headline = (summary.get("summary") or summary.get("action") or "")[:70]
    label = f"{icon} **{tf}** — {verdict} ({score:.1f}/10)"
    if extra:
        label += f" · {extra}"
    elif headline:
        label += f" · {headline}"
    return label


def should_expand_ticker(index: int, *, max_open: int = 2) -> bool:
    """Expand only the first few ticker sections by default."""
    return index < max_open
