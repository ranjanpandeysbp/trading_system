"""
mtf_analysis.py
---------------
Shared multitimeframe (MTF) context for any strategy tab — 7-component
alignment ladder (HTF → ULTF) using the institutional MTF scanner engine.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from app.market_pulse.mtf_scanner_engine import (
    TF_ORDER,
    TIMEFRAMES,
    analyze_timeframe,
    bias_label,
    build_confluence,
    fetch_mtf_data,
    trend_arrow_label,
)

ROLE_LABELS = ("HTF", "MTF", "LTF", "ULTF")

# Primary chart TF → slow→fast ladder (4 bars)
_LADDER_BY_PRIMARY: dict[str, list[str]] = {
    "1m": ["1h", "15m", "5m", "1m"],
    "2m": ["1h", "15m", "5m", "5m"],
    "3m": ["1h", "15m", "5m", "5m"],
    "5m": ["1d", "1h", "15m", "5m"],
    "15m": ["1d", "1h", "15m", "5m"],
    "30m": ["1d", "4h", "1h", "30m"],
    "1h": ["1d", "4h", "1h", "15m"],
    "4h": ["1w", "1d", "4h", "1h"],
    "1d": ["1w", "1d", "4h", "1h"],
    "1w": ["1w", "1d", "4h", "1h"],
    "1wk": ["1w", "1d", "4h", "1h"],
    "weekly": ["1w", "1d", "4h", "1h"],
}

_DEFAULT_LADDER = ["1d", "1h", "15m", "5m"]


def ladder_for_primary_tf(primary_tf: str | None) -> list[str]:
    """Return up to 4 timeframes slow→fast for MTF context."""
    if not primary_tf:
        return list(_DEFAULT_LADDER)
    key = str(primary_tf).strip().lower()
    if key in _LADDER_BY_PRIMARY:
        return list(_LADDER_BY_PRIMARY[key])
    if key in TF_ORDER:
        idx = TF_ORDER.index(key)
        picks: list[str] = []
        for delta in (3, 2, 1, 0):
            i = max(0, min(len(TF_ORDER) - 1, idx + delta - 1))
            tf = TF_ORDER[i]
            if tf not in picks:
                picks.append(tf)
        while len(picks) < 4 and picks[-1] != TF_ORDER[0]:
            i = TF_ORDER.index(picks[-1]) - 1
            if i < 0:
                break
            if TF_ORDER[i] not in picks:
                picks.append(TF_ORDER[i])
        return picks[:4] if picks else list(_DEFAULT_LADDER)
    return list(_DEFAULT_LADDER)


def _role_for_index(i: int, n: int) -> str:
    if n <= 1:
        return "MTF"
    if n == 2:
        return ROLE_LABELS[0] if i == 0 else ROLE_LABELS[-1]
    if n == 3:
        return (ROLE_LABELS[0], ROLE_LABELS[1], ROLE_LABELS[-1])[i]
    return ROLE_LABELS[min(i, len(ROLE_LABELS) - 1)]


def analyze_mtf_context(
    symbol: str,
    market: str,
    groww_token: str,
    exchange: str,
    primary_tf: str,
    limit: int = 250,
) -> dict[str, Any]:
    """
    Run lightweight MTF alignment for a symbol (4-TF ladder from primary_tf).
    Uses the same 7-component scorer as the MTF Scanner tab.
    """
    symbol = (symbol or "").strip().upper()
    ladder = ladder_for_primary_tf(primary_tf)
    tf_results: dict[str, dict] = {}
    errors: dict[str, str] = {}

    for i, tf in enumerate(ladder):
        try:
            df = fetch_mtf_data(symbol, tf, market, groww_token or "", exchange, limit=limit)
            row = analyze_timeframe(df, tf)
            if row is None:
                errors[tf] = "Insufficient bars"
                continue
            row["role"] = _role_for_index(i, len(ladder))
            tf_results[tf] = row
        except Exception as exc:
            errors[tf] = str(exc)[:100]

    confluence = build_confluence(tf_results) if tf_results else {
        "verdict": "NO DATA",
        "avg_score": 0,
        "bull_count": 0,
        "bear_count": 0,
        "neutral_count": 0,
        "total_tfs": 0,
        "suggested_play": ["Could not load MTF data — check token / symbol."],
        "actionable": False,
    }

    return {
        "symbol": symbol,
        "primary_tf": primary_tf,
        "ladder": ladder,
        "timeframes": tf_results,
        "confluence": confluence,
        "errors": errors,
    }


def mtf_context_aligns_with_direction(ctx: dict[str, Any], direction: str) -> bool | None:
    """True if MTF confluence supports LONG/BUY or SHORT/SELL direction."""
    if not ctx or not ctx.get("timeframes"):
        return None
    conf = ctx.get("confluence") or {}
    vtype = conf.get("verdict_type", "")
    d = (direction or "").upper()
    if d in ("LONG", "BUY"):
        return vtype in ("strong_bull", "mild_bull")
    if d in ("SHORT", "SELL"):
        return vtype in ("strong_bear", "mild_bear")
    return None


def format_mtf_context_for_ai(ctx: dict[str, Any]) -> str:
    """Text block for AI prompts."""
    if not ctx:
        return ""
    lines = [
        "=== MULTITIMEFRAME CONTEXT (7-component engine) ===",
        f"Primary TF: {ctx.get('primary_tf', '—')} · Ladder: {', '.join(ctx.get('ladder') or [])}",
    ]
    conf = ctx.get("confluence") or {}
    lines.append(
        f"MTF Verdict: {conf.get('verdict', '—')} · Avg score {conf.get('avg_score', 0)}/100 · "
        f"Bull {conf.get('bull_count', 0)} · Bear {conf.get('bear_count', 0)} · "
        f"Neutral {conf.get('neutral_count', 0)}"
    )
    for tf, row in (ctx.get("timeframes") or {}).items():
        meta = TIMEFRAMES.get(tf, {})
        lines.append(
            f"  [{row.get('role', 'TF')}] {meta.get('label', tf)}: "
            f"composite {row.get('composite', 0):.0f}/100 · "
            f"{row.get('bias', '—')} · conf {row.get('confidence', 0):.0f}%"
        )
    for hint in (conf.get("suggested_play") or [])[:3]:
        lines.append(f"  → {hint}")
    errs = ctx.get("errors") or {}
    if errs:
        lines.append("Skipped: " + ", ".join(f"{k}: {v}" for k, v in list(errs.items())[:3]))
    return "\n".join(lines)


def render_mtf_context_panel(
    ctx: dict[str, Any] | None,
    *,
    primary_tf: str | None = None,
    strategy_direction: str | None = None,
    expanded: bool = False,
) -> None:
    """Collapsible MTF alignment panel (standard across strategy tabs)."""
    if not ctx or not ctx.get("timeframes"):
        with st.expander("📊 Multitimeframe Analysis", expanded=expanded):
            st.caption("MTF context unavailable — insufficient data across ladder TFs.")
            errs = (ctx or {}).get("errors") or {}
            if errs:
                st.caption(" · ".join(f"{k}: {v}" for k, v in list(errs.items())[:4]))
        return

    conf = ctx.get("confluence") or {}
    aligns = mtf_context_aligns_with_direction(ctx, strategy_direction or "") if strategy_direction else None

    with st.expander("📊 Multitimeframe Analysis", expanded=expanded):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("MTF Verdict", conf.get("verdict", "—")[:28])
        c2.metric("Avg Score", f"{conf.get('avg_score', 0)}/100")
        c3.metric("Bull / Bear TFs", f"{conf.get('bull_count', 0)} / {conf.get('bear_count', 0)}")
        c4.metric("Avg Confidence", f"{conf.get('avg_confidence', 0):.0f}%")

        if aligns is True:
            st.success("✅ MTF ladder **aligns** with this strategy's directional bias.")
        elif aligns is False:
            st.warning("⚠️ MTF ladder **conflicts** with this setup — size down or wait for alignment.")

        rows = []
        for tf in ctx.get("ladder") or []:
            row = (ctx.get("timeframes") or {}).get(tf)
            if not row:
                continue
            meta = TIMEFRAMES.get(tf, {})
            rows.append({
                "Role": row.get("role", "—"),
                "Timeframe": meta.get("label", tf),
                "Score": f"{row.get('composite', 0):.0f}",
                "Bias": row.get("bias", bias_label(row.get("composite", 50))),
                "Trend": trend_arrow_label(row.get("composite", 50)),
                "Confidence": f"{row.get('confidence', 0):.0f}%",
                "Style": meta.get("style", "—"),
            })
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')

        hints = conf.get("suggested_play") or []
        if hints:
            st.markdown("**Suggested play (MTF):**")
            for h in hints[:3]:
                st.markdown(f"- {h}")

        st.caption(
            f"Ladder from primary **{primary_tf or ctx.get('primary_tf', '—')}** · "
            "Same 7-component engine as MTF Scanner (trend · momentum · PA · S/R · volume · volatility · structure)."
        )
