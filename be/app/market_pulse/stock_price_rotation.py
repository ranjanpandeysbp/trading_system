"""
stock_price_rotation.py
-----------------------
Market Pulse — constituent stock price rotation vs a chosen Nifty index.
Ranks stocks by return over a user-selected candle interval and lookback window.
"""

from __future__ import annotations

import logging
from typing import Iterable

import pandas as pd
from app.market_pulse.groww_auth import get_active_groww_token
from app.market_pulse.heatmap import TF_INDIA
from app.market_pulse.index_ohlcv import (
    download_stock_ohlcv_batch_interval,
    fetch_index_interval_close_series,
)
from app.market_pulse.nifty_index_constituents import get_index_constituent_symbols
from app.market_pulse.news_scanner import (
    _NIFTY_BREADTH_GROUP_LABELS,
    _NIFTY_BREADTH_GROUP_ORDER,
    _fetch_nse_index_constituent_symbols,
    _pct_return_over_bars,
    _render_market_pulse_feed_banner,
    _render_news_scanner_styles,
    _render_rotation_bar_chart,
    _sector_rotation_feed_mode,
    fetch_nse_market_breadth,
    fmt_last_pct,
)
from app.market_pulse.week52_high_low import _get_index_names_by_group

logger = logging.getLogger(__name__)

# No hard ticker/constituent caps — return the full ranked universe.
_ROTATION_TOP_N: int | None = None
_MAX_CONSTITUENTS: int | None = None
_PREFIX = "spr"

_TIMEFRAME_OPTIONS: tuple[tuple[str, str], ...] = (
    ("1 minute", "1m"),
    ("5 minutes", "5m"),
    ("15 minutes", "15m"),
    ("30 minutes", "30m"),
    ("1 hour", "1h"),
    ("4 hours", "4h"),
    ("1 day", "1d"),
    ("1 week", "1w"),
    ("1 month", "1M"),
)

_LOOKBACK_PRESETS: tuple[tuple[str, int], ...] = (
    ("15 minutes", 15),
    ("30 minutes", 30),
    ("1 hour", 60),
    ("2 hours", 120),
    ("4 hours", 240),
    ("1 session (~6.5h)", 390),
    ("1 day", 1440),
    ("3 days", 4320),
    ("1 week", 10080),
    ("2 weeks", 20160),
    ("1 month (~21 sessions)", 30240),
)

_BAR_DEFAULTS: dict[str, tuple[int, int, int]] = {
    "1m": (15, 5, 390),
    "5m": (12, 3, 78),
    "15m": (8, 2, 52),
    "30m": (8, 2, 26),
    "1h": (6, 2, 168),
    "4h": (6, 2, 42),
    "1d": (5, 1, 63),
    "1w": (4, 1, 52),
    "1M": (3, 1, 24),
}


def _tf_yf_interval(tf_key: str) -> str:
    mapping = {
        "1m": "1m",
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1h": "1h",
        "4h": "1h",
        "1d": "1d",
        "1w": "1wk",
        "1M": "1mo",
    }
    return mapping.get(tf_key, "1d")


def _tf_yf_period(tf_key: str, lookback_bars: int) -> str:
    if tf_key == "1M":
        return f"{max(lookback_bars + 3, 12)}mo"
    if tf_key == "1w":
        return f"{max(lookback_bars + 4, 24)}mo"
    if tf_key == "1d":
        return f"{max(lookback_bars + 10, 30)}d"
    minutes = TF_INDIA.get(tf_key, (60, 150, "60"))[0]
    total_min = minutes * (lookback_bars + 20)
    days = max(7, (total_min // (24 * 60)) + 3)
    return f"{days}d"


def _minutes_to_bars(tf_key: str, minutes: int) -> int:
    if tf_key == "1d":
        return max(1, minutes // 1440)
    if tf_key == "1w":
        return max(1, minutes // 10080)
    if tf_key == "1M":
        return max(1, minutes // 43200)
    bar_minutes = TF_INDIA.get(tf_key, (5, 15, "5"))[0]
    return max(1, minutes // bar_minutes)


def _lookback_labels_for_tf(tf_key: str) -> list[tuple[str, int]]:
    if tf_key in ("1d", "1w", "1M"):
        return [(label, _minutes_to_bars(tf_key, mins)) for label, mins in _LOOKBACK_PRESETS]
    bar_minutes = TF_INDIA.get(tf_key, (5, 15, "5"))[0]
    out: list[tuple[str, int]] = []
    for label, mins in _LOOKBACK_PRESETS:
        bars = _minutes_to_bars(tf_key, mins)
        if bars * bar_minutes > TF_INDIA.get(tf_key, (5, 150, "5"))[1] * 24 * 60:
            continue
        if bars < 1:
            continue
        out.append((label, bars))
    return out or [("Default", _BAR_DEFAULTS.get(tf_key, (5, 1, 20))[0])]


def _resolve_constituent_symbols(index_name: str) -> list[str]:
    symbols = get_index_constituent_symbols(index_name)
    if not symbols:
        symbols = _fetch_nse_index_constituent_symbols(index_name)
    seen: set[str] = set()
    out: list[str] = []
    for sym in symbols:
        s = (sym or "").strip().upper()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    if _MAX_CONSTITUENTS is not None and _MAX_CONSTITUENTS > 0:
        return out[:_MAX_CONSTITUENTS]
    return out


def _build_index_picker_options(breadth: dict | None) -> list[tuple[str, str]]:
    """Return (display label, index name) sorted for selectbox."""
    by_group = _get_index_names_by_group(breadth)
    options: list[tuple[str, str]] = []
    for group in _NIFTY_BREADTH_GROUP_ORDER:
        label = _NIFTY_BREADTH_GROUP_LABELS.get(group, group.title())
        for name in by_group.get(group, []):
            options.append((f"{label} · {name}", name))
    if not options:
        from app.market_pulse.ticker_utils import INDEX_OPTIONS

        for key in INDEX_OPTIONS:
            if key == "Default Groww Tickers":
                continue
            options.append((key, key))
    return options


def _fetch_stock_closes_groww(
    symbols: Iterable[str],
    tf_key: str,
    exchange: str,
    groww_token: str,
    bar_limit: int,
) -> dict[str, pd.Series]:
    from app.market_pulse.heatmap import fetch_groww_ohlcv

    out: dict[str, pd.Series] = {}
    for sym in symbols:
        try:
            raw = fetch_groww_ohlcv(sym, exchange, tf_key, groww_token, limit=bar_limit)
            if raw is None or raw.empty:
                continue
            col = "close" if "close" in raw.columns else "Close"
            if col not in raw.columns:
                continue
            closes = pd.to_numeric(raw[col], errors="coerce").dropna()
            if not closes.empty:
                out[sym] = closes
        except Exception as exc:
            logger.debug("Groww stock closes skip %s: %s", sym, exc)
    return out


def _fetch_stock_closes_yfinance(
    symbols: list[str],
    tf_key: str,
    lookback_bars: int,
) -> dict[str, pd.Series]:
    interval = _tf_yf_interval(tf_key)
    period = _tf_yf_period(tf_key, lookback_bars)
    ohlcv_map = download_stock_ohlcv_batch_interval(
        symbols,
        interval=interval,
        period=period,
        limit=len(symbols),
    )
    out: dict[str, pd.Series] = {}
    for sym, df in ohlcv_map.items():
        if df is None or df.empty or "close" not in df.columns:
            continue
        closes = pd.to_numeric(df["close"], errors="coerce").dropna()
        if not closes.empty:
            out[sym] = closes
    return out


def _load_stock_close_map(
    symbols: list[str],
    tf_key: str,
    lookback_bars: int,
    groww_token: str,
    exchange: str,
) -> dict[str, pd.Series]:
    bar_limit = max(lookback_bars + 25, 60)
    if groww_token and tf_key in TF_INDIA:
        closes = _fetch_stock_closes_groww(symbols, tf_key, exchange, groww_token, bar_limit)
        if closes:
            return closes
    return _fetch_stock_closes_yfinance(symbols, tf_key, lookback_bars)


def compute_stock_price_rotation(
    index_name: str,
    symbols: tuple[str, ...],
    tf_key: str,
    lookback_bars: int,
    use_groww: bool = False,
    exchange: str = "NSE",
) -> dict | None:
    """Rank constituent stocks by % return vs index over lookback bars."""
    if not index_name or not symbols:
        return None

    groww_token = get_active_groww_token() if use_groww else ""
    yf_interval = _tf_yf_interval(tf_key)
    period = _tf_yf_period(tf_key, lookback_bars)
    bar_limit = max(lookback_bars + 25, 60)

    index_closes = fetch_index_interval_close_series(
        index_name,
        interval=yf_interval,
        period=period,
        groww_token=groww_token,
        exchange=exchange,
        limit=bar_limit,
    )
    if index_closes is None or index_closes.dropna().empty:
        logger.error("Stock rotation: index %s unavailable at %s", index_name, tf_key)
        return None

    stock_closes = _load_stock_close_map(
        list(symbols), tf_key, lookback_bars, groww_token, exchange,
    )
    if not stock_closes:
        logger.error("Stock rotation: no stock close data for %s", index_name)
        return None

    bench_pct = _pct_return_over_bars(index_closes, lookback_bars)
    rows: list[dict] = []
    for sym, closes in stock_closes.items():
        pct = _pct_return_over_bars(closes, lookback_bars)
        if pct is None:
            continue
        rel = pct - bench_pct if bench_pct is not None else pct
        clean = closes.dropna()
        last_px = float(clean.iloc[-1]) if len(clean) else None
        rows.append({
            "name": sym,
            "symbol": sym,
            "pct": pct,
            "relative": rel,
            "last": last_px,
        })

    if not rows:
        return None

    rows.sort(key=lambda x: x["pct"], reverse=True)
    if _ROTATION_TOP_N is not None and _ROTATION_TOP_N > 0:
        inflow = rows[:_ROTATION_TOP_N]
        outflow = list(reversed(rows[-_ROTATION_TOP_N:]))
    else:
        inflow = list(rows)
        outflow = list(reversed(rows))
    return {
        "index_name": index_name,
        "tf_key": tf_key,
        "lookback_bars": lookback_bars,
        "benchmark_pct": bench_pct,
        "stocks": rows,
        "inflow": inflow,
        "outflow": outflow,
        "stock_count": len(rows),
        "requested_count": len(symbols),
        "data_feed": "groww" if groww_token else "yfinance",
        "exchange": exchange,
    }


def _rotation_period_label(tf_key: str, lookback_bars: int) -> str:
    if tf_key == "1d":
        return f"last {lookback_bars} trading day{'s' if lookback_bars != 1 else ''}"
    if tf_key == "1w":
        return f"last {lookback_bars} week{'s' if lookback_bars != 1 else ''}"
    if tf_key == "1M":
        return f"last {lookback_bars} month{'s' if lookback_bars != 1 else ''}"
    bar_minutes = TF_INDIA.get(tf_key, (5, 15, "5"))[0]
    total_min = lookback_bars * bar_minutes
    if total_min < 60:
        return f"last {total_min} min ({lookback_bars} × {tf_key} bars)"
    if total_min < 1440:
        return f"last {total_min // 60}h {total_min % 60}m ({lookback_bars} bars)"
    days = total_min / 1440
    return f"last ~{days:.1f} day(s) ({lookback_bars} × {tf_key} bars)"


def _universe_label(payload: dict) -> str:
    return (
        payload.get("universe_name")
        or payload.get("index_name")
        or payload.get("benchmark_label")
        or "Benchmark"
    )


def _rotation_explanation(payload: dict) -> str:
    window_inflow = payload.get("inflow") or []
    window_outflow = payload.get("outflow") or []
    bench = payload.get("benchmark_pct")
    index_name = _universe_label(payload)
    tf_key = payload.get("tf_key", "1d")
    bars = payload.get("lookback_bars", 1)
    period = _rotation_period_label(tf_key, bars)

    if not window_inflow:
        return f"No constituent return data for **{index_name}** over the {period}."

    top = window_inflow[0]
    bottom = window_outflow[0] if window_outflow else window_inflow[-1]
    bench_txt = f"{bench:+.2f}%" if bench is not None else "N/A"
    tone = (
        "Broad risk-on — multiple constituents beating the index; leadership is dispersed."
        if len([s for s in payload.get("stocks", []) if s["relative"] > 0]) > len(payload.get("stocks", [])) * 0.6
        else "Defensive / narrow — index held up while most constituents lagged."
        if bench is not None and bench >= 0 and bottom["relative"] < -1
        else "Selective rotation — money is rotating between names, not lifting the whole index uniformly."
    )
    top_q = fmt_last_pct(top.get("last"), top.get("pct"))
    bottom_q = fmt_last_pct(bottom.get("last"), bottom.get("pct"))
    return (
        f"Over **{period}** on **{tf_key}** candles, **{top['symbol']}** led "
        f"**{index_name}** constituents with **{top_q}** ({top['relative']:+.2f}% vs index), while "
        f"**{bottom['symbol']}** lagged at **{bottom_q}**. "
        f"**{index_name}** returned **{bench_txt}** in the same window. {tone}"
    )


def _render_stock_rotation_table(
    stocks: list[dict],
    title: str,
    benchmark_label: str,
    *,
    asset_label: str = "Stock",
) -> None:
    st.markdown(f"**{title}**")
    if not stocks:
        st.caption("No data.")
        return
    rows = []
    for s in stocks:
        sym = s.get("symbol") or s.get("name", "")
        rows.append({
            asset_label: sym,
            "Last · Return %": fmt_last_pct(s.get("last"), s.get("pct")),
            f"vs {benchmark_label}": f"{s['relative']:+.2f}%",
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def render_rotation_timeframe_controls(prefix: str) -> tuple[str, int]:
    """Shared candle interval + lookback UI. Returns (tf_key, lookback_bars)."""
    tf_labels = [t[0] for t in _TIMEFRAME_OPTIONS]
    tf_keys = {label: key for label, key in _TIMEFRAME_OPTIONS}

    c_tf, c_lb, c_custom = st.columns([1, 2, 2])
    with c_tf:
        tf_label = st.selectbox(
            "⏱️ Candle interval",
            tf_labels,
            index=6,
            key=f"{prefix}_tf",
            help="Bar size from 1 minute through 1 month.",
        )
    tf_key = tf_keys[tf_label]

    lookback_options = _lookback_labels_for_tf(tf_key)
    lookback_labels = [x[0] for x in lookback_options]
    lookback_map = {label: bars for label, bars in lookback_options}
    default_lookback = lookback_labels[min(2, len(lookback_labels) - 1)]

    with c_lb:
        lookback_label = st.selectbox(
            "📅 Lookback duration",
            lookback_labels,
            index=lookback_labels.index(default_lookback) if default_lookback in lookback_labels else 0,
            key=f"{prefix}_lookback_{tf_key}",
        )
    lookback_bars = lookback_map[lookback_label]

    defaults = _BAR_DEFAULTS.get(tf_key, (5, 1, 20))
    with c_custom:
        use_custom_bars = st.checkbox("Custom bar count", value=False, key=f"{prefix}_custom_{tf_key}")
        if use_custom_bars:
            lookback_bars = st.slider(
                "Lookback (bars)",
                defaults[1],
                defaults[2],
                defaults[0],
                key=f"{prefix}_bars_{tf_key}",
            )

    st.caption(f"Window: **{_rotation_period_label(tf_key, lookback_bars)}**")
    return tf_key, lookback_bars


def render_rotation_results(
    payload: dict,
    *,
    asset_label: str = "Stock",
    benchmark_label: str | None = None,
) -> None:
    index_name = benchmark_label or _universe_label(payload)
    tf_key = payload.get("tf_key", "1d")
    bars = payload.get("lookback_bars", 1)
    period = _rotation_period_label(tf_key, bars)

    st.caption(
        f"**{payload.get('stock_count', 0)}** / **{payload.get('requested_count', 0)}** constituents "
        f"with data · benchmark **{index_name}** · **{tf_key}** · {period} · "
        f"Feed: **{payload.get('data_feed', 'yfinance').upper()}**"
    )
    st.markdown(_rotation_explanation(payload))
    st.markdown("<div style='margin-top:8px;'></div>", unsafe_allow_html=True)

    col_in, col_out = st.columns(2)
    with col_in:
        _render_stock_rotation_table(
            payload.get("inflow") or [],
            f"🟢 Rotating IN (top {_ROTATION_TOP_N})",
            index_name,
            asset_label=asset_label,
        )
    with col_out:
        _render_stock_rotation_table(
            payload.get("outflow") or [],
            f"🔴 Rotating OUT (weakest {_ROTATION_TOP_N})",
            index_name,
            asset_label=asset_label,
        )

    chart_window = {
        "sectors": [{"name": s["symbol"], **s} for s in (payload.get("stocks") or [])],
        "benchmark_pct": payload.get("benchmark_pct"),
    }
    _render_rotation_bar_chart(
        chart_window,
        f"All constituents — {period} returns (%)",
        benchmark_label=index_name.replace("NIFTY ", "Nifty "),
    )

    with st.expander("📋 Full ranking", expanded=False):
        all_rows = [{
            asset_label: s.get("symbol") or s.get("name", ""),
            "Return %": f"{s['pct']:+.2f}%",
            f"vs {index_name}": f"{s['relative']:+.2f}%",
            "Last": f"{s['last']:,.2f}" if s.get("last") else "N/A",
        } for s in (payload.get("stocks") or [])]
        st.dataframe(pd.DataFrame(all_rows), hide_index=True, width="stretch")


def _render_rotation_results(payload: dict) -> None:
    render_rotation_results(payload, asset_label="Stock")


def render_stock_price_rotation_tab() -> None:
    """Market Pulse — constituent stock rotation for a chosen Nifty index."""
    _render_news_scanner_styles()
    st.markdown(
        '<div class="section-header-ns">🔄 Stock Price Rotation — Index Constituents</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Pick a **Nifty index**, choose **constituent stocks**, set **candle interval** (1m → 1M) "
        "and **lookback duration**, then submit to see which names are rotating in vs out "
        "relative to the index over that window."
    )

    breadth = fetch_nse_market_breadth()
    index_options = _build_index_picker_options(breadth)
    if not index_options:
        st.error("No Nifty indices available. Check NSE connectivity and retry.")
        return

    labels = [o[0] for o in index_options]
    default_idx = next((i for i, (_, n) in enumerate(index_options) if n == "NIFTY 50"), 0)

    c_idx, _ = st.columns([2, 1])
    with c_idx:
        picked_label = st.selectbox(
            "📊 Index",
            labels,
            index=default_idx,
            key=f"{_PREFIX}_index",
        )
    index_name = dict(index_options).get(picked_label, index_options[0][1])

    all_symbols = _resolve_constituent_symbols(index_name)
    if not all_symbols:
        st.warning(f"No constituents resolved for **{index_name}**. Try another index.")
        return

    st.caption(f"**{len(all_symbols)}** constituents available for **{index_name}**")

    selected_symbols = st.multiselect(
        "Constituent stocks (subset or leave all selected)",
        all_symbols,
        default=all_symbols,
        key=f"{_PREFIX}_symbols_{index_name}",
        help="Uncheck names to exclude them from the rotation scan.",
    )

    tf_key, lookback_bars = render_rotation_timeframe_controls(_PREFIX)

    load_btn = st.button(
        "🔄 Analyse Stock Rotation",
        key=f"{_PREFIX}_load",
        type="primary",
    )

    use_groww, _, exchange = _sector_rotation_feed_mode()
    _render_market_pulse_feed_banner(use_groww)

    if load_btn:
        if not selected_symbols:
            st.warning("Select at least one constituent stock.")
        else:
            compute_stock_price_rotation.clear()
            feed_label = "Groww API" if use_groww else "yfinance"
            sym_tuple = tuple(selected_symbols)
            with st.spinner(
                f"Computing rotation for {len(sym_tuple)} stocks vs {index_name} "
                f"({tf_key}, {lookback_bars} bars) via {feed_label}…"
            ):
                result = compute_stock_price_rotation(
                    index_name,
                    sym_tuple,
                    tf_key,
                    lookback_bars,
                    use_groww=use_groww,
                    exchange=exchange,
                )
            if result:
                st.session_state["stock_price_rotation_payload"] = result
                st.session_state["stock_price_rotation_params"] = {
                    "index_name": index_name,
                    "symbols": sym_tuple,
                    "tf_key": tf_key,
                    "lookback_bars": lookback_bars,
                }
            else:
                st.session_state.pop("stock_price_rotation_payload", None)
                st.error(
                    "Unable to compute stock rotation. Check network, Groww token, "
                    "or try during market hours for intraday intervals."
                )

    payload = st.session_state.get("stock_price_rotation_payload")
    if not payload:
        st.info(
            "Choose an index and timeframe, then click **🔄 Analyse Stock Rotation**. "
            "Data is not fetched automatically on page load."
        )
        return

    params = st.session_state.get("stock_price_rotation_params") or {}
    if (
        params.get("index_name") != index_name
        or params.get("tf_key") != tf_key
        or params.get("lookback_bars") != lookback_bars
        or tuple(params.get("symbols") or ()) != tuple(selected_symbols)
    ):
        st.warning("Settings changed — click **Analyse Stock Rotation** again to refresh.")

    _render_rotation_results(payload)
    from app.market_pulse.ask_ai_context import snapshot_section_for_ask_ai

    snapshot_section_for_ask_ai("stock_price_rotation")
