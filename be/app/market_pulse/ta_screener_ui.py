"""
Shared Technical Analysis screener UI — alerts, grid, and digest for multi-ticker scans.
"""

from __future__ import annotations

from app.market_pulse.run_summary import (
    ERROR_VERDICTS,
    TRADE_VERDICTS,
    WATCH_VERDICTS,
    enrich_summary,
    render_run_digest,
)


def _urgency_rank(summary: dict) -> tuple[int, float]:
    """Higher tuple sorts first: trade > watch > high score > rest."""
    sig = summary.get("signal_type") or ""
    score = float(summary.get("score", 0) or 0)
    if sig == "trade":
        return (3, score)
    if sig == "watch":
        return (2, score)
    if score >= 6.5:
        return (1, score)
    return (0, score)


def sort_summaries_by_urgency(summaries: list[dict]) -> list[dict]:
    enriched = [enrich_summary(s) for s in summaries]
    return sorted(enriched, key=_urgency_rank, reverse=True)


def is_actionable_summary(summary: dict) -> bool:
    s = enrich_summary(summary)
    return s.get("signal_type") == "trade"


def is_approaching_summary(summary: dict) -> bool:
    s = enrich_summary(summary)
    if s.get("signal_type") == "trade":
        return False
    if s.get("signal_type") == "watch":
        return True
    v = (s.get("verdict") or "").upper().strip()
    if v in WATCH_VERDICTS:
        return True
    score = float(s.get("score", 0) or 0)
    return score >= 6.5 and v not in ERROR_VERDICTS


def filter_actionable_digest(summaries: list[dict], *, include_approaching: bool = True) -> list[dict]:
    out = []
    for s in summaries:
        if is_actionable_summary(s):
            out.append(s)
        elif include_approaching and is_approaching_summary(s):
            out.append(s)
    return out


def render_ta_screener_options(key_prefix: str) -> bool:
    """Checkbox: show only actionable / approaching setups in detail sections."""
    return st.checkbox(
        "Show actionable & approaching only",
        value=False,
        key=f"{key_prefix}_actionable_only",
        help="Hide tickers with no trade setup or watchlist signal.",
    )


def render_ta_screener_alerts(summaries: list[dict], *, strategy_label: str = "") -> None:
    """Top banners for ready vs approaching setups across tickers."""
    if not summaries:
        return
    enriched = sort_summaries_by_urgency(summaries)
    actionable = [s for s in enriched if is_actionable_summary(s)]
    approaching = [s for s in enriched if is_approaching_summary(s)]
    label = strategy_label or "setup"

    if actionable:
        parts = []
        for s in actionable[:12]:
            tf = s.get("timeframe") or ""
            rec = (s.get("recommendation") or s.get("verdict") or "")[:48]
            parts.append(f"**{s.get('ticker')}**" + (f" `{tf}`" if tf else "") + f" ({rec})")
        extra = f" +{len(actionable) - 12} more" if len(actionable) > 12 else ""
        st.success(
            f"**{len(actionable)} row(s) with READY {label}:** " + ", ".join(parts) + extra
        )

    if approaching:
        parts = []
        for s in approaching[:12]:
            tf = s.get("timeframe") or ""
            rec = (s.get("recommendation") or s.get("verdict") or "")[:48]
            parts.append(f"**{s.get('ticker')}**" + (f" `{tf}`" if tf else "") + f" ({rec})")
        extra = f" +{len(approaching) - 12} more" if len(approaching) > 12 else ""
        st.warning(
            f"**{len(approaching)} row(s) with APPROACHING / watchlist {label}:** "
            + ", ".join(parts)
            + extra
        )

    if not actionable and not approaching:
        st.info(
            "No immediate trade setups in this scan — re-run or expand tickers. "
            "Setups appear when engines flag Buy/Sell or watchlist conditions."
        )


def render_ta_screener_grid(summaries: list[dict]) -> None:
    """Compact grid sorted by urgency."""
    if not summaries:
        return
    enriched = sort_summaries_by_urgency(summaries)
    rows = []
    for s in enriched:
        p = s.get("trade_plan") or {}
        trade = s.get("signal_type") == "trade"
        v = (s.get("verdict") or "").upper()
        if trade:
            status = "READY"
        elif is_approaching_summary(s):
            status = "APPROACHING"
        elif v in ERROR_VERDICTS:
            status = "ERROR"
        else:
            status = "MONITOR"
        rows.append({
            "Ticker": s.get("ticker", ""),
            "TF": s.get("timeframe", "") or "—",
            "Status": status,
            "Score": s.get("score", 0),
            "Verdict": s.get("verdict", ""),
            "Recommendation": (s.get("recommendation") or "")[:50],
            "Direction": p.get("direction", "—") if trade else "—",
            "SL %": p.get("stop_loss_pct") if trade else None,
            "TP %": p.get("take_profit_pct") if trade else None,
        })
    st.markdown("### 📋 Live Screener Grid")
    st.dataframe(rows, width='stretch', hide_index=True)


def render_ta_screener_results(
    summaries: list[dict],
    *,
    title: str = "🧭 Screener Recommendations",
    strategy_label: str = "",
    actionable_only: bool = False,
    show_alerts: bool = True,
    show_grid: bool = True,
) -> list[dict]:
    """
    Render screener alerts + grid + grouped digest.
    Returns filtered digest for downstream per-ticker loops.
    """
    if not summaries:
        st.info("Run a scan to see screener results.")
        return []

    digest = sort_summaries_by_urgency(summaries)
    if actionable_only:
        digest = filter_actionable_digest(digest)

    if show_alerts:
        render_ta_screener_alerts(summaries, strategy_label=strategy_label)
    if show_grid:
        render_ta_screener_grid(digest if actionable_only else summaries)

    render_run_digest(digest, title=title, group_filter=True)
    return digest


def should_show_ticker_in_screener(
    ticker: str,
    digest: list[dict],
    *,
    actionable_only: bool,
) -> bool:
    """Filter ticker detail expanders when actionable-only mode is on."""
    if not actionable_only:
        return True
    rows = [s for s in digest if s.get("ticker") == ticker]
    if not rows:
        return True
    return any(is_actionable_summary(s) or is_approaching_summary(s) for s in rows)


def render_strategy_mtf_panel(
    *,
    symbol: str,
    market: str,
    groww_token: str = "",
    exchange: str = "NSE",
    primary_tf: str = "15m",
    strategy_direction: str | None = None,
    expanded: bool = False,
) -> dict | None:
    """
    Standard multitimeframe analysis block for any strategy tab.
    Returns MTF context dict (for AI prompts) or None on total failure.
    """
    from app.market_pulse.mtf_analysis import analyze_mtf_context, render_mtf_context_panel

    if not symbol:
        return None
    try:
        ctx = analyze_mtf_context(
            symbol.strip().upper(),
            market,
            groww_token or "",
            exchange,
            primary_tf,
        )
    except Exception:
        ctx = None
    render_mtf_context_panel(
        ctx,
        primary_tf=primary_tf,
        strategy_direction=strategy_direction,
        expanded=expanded,
    )
    return ctx
