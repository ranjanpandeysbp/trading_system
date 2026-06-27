"""
stock_price_rotation_markets.py
-------------------------------
US (yfinance) and CoinDCX crypto price rotation vs index/benchmark.
Mirrors the India constituent rotation UX in stock_price_rotation.py.
"""

from __future__ import annotations

import logging
from typing import Literal

import pandas as pd
from app.market_pulse.heatmap import TF_CRYPTO
from app.market_pulse.news_scanner import (
    _pct_return_over_bars,
    _render_news_scanner_styles,
)
from app.market_pulse.crypto_session import CRYPTO_FEED_BANNER, render_crypto_session_caption
from app.market_pulse.sector_rotation_markets import (
    CRYPTO_BENCHMARK_LABEL,
    CRYPTO_BENCHMARK_SYMBOL,
    CRYPTO_SECTOR_FILTER_GROUPS,
    CRYPTO_SECTOR_SYMBOLS,
    _load_crypto_closes,
    _load_yf_closes,
)
from app.market_pulse.stock_price_rotation import (
    _MAX_CONSTITUENTS,
    _ROTATION_TOP_N,
    _tf_yf_interval,
    _tf_yf_period,
    render_rotation_results,
    render_rotation_timeframe_controls,
)
from app.market_pulse.us_index_constituents import (
    get_dow_30,
    get_nasdaq_100,
    get_russell_2000,
    get_sp_100,
    get_sp_400_midcap,
    get_sp_500,
    get_sp_600_smallcap,
)

logger = logging.getLogger(__name__)

MarketKind = Literal["us", "crypto"]

_US_INDEX_CATALOG: tuple[dict, ...] = (
    {
        "id": "dow30",
        "label_fn": lambda: f"Dow 30 ({len(get_dow_30())} stocks)",
        "fetch": get_dow_30,
        "benchmark": "DIA",
        "benchmark_label": "Dow 30 (DIA)",
    },
    {
        "id": "ndx100",
        "label_fn": lambda: f"Nasdaq 100 ({len(get_nasdaq_100())} stocks)",
        "fetch": get_nasdaq_100,
        "benchmark": "QQQ",
        "benchmark_label": "Nasdaq 100 (QQQ)",
    },
    {
        "id": "sp500",
        "label_fn": lambda: f"S&P 500 ({len(get_sp_500())} stocks)",
        "fetch": get_sp_500,
        "benchmark": "SPY",
        "benchmark_label": "S&P 500 (SPY)",
    },
    {
        "id": "sp100",
        "label_fn": lambda: f"S&P 100 ({len(get_sp_100())} stocks)",
        "fetch": get_sp_100,
        "benchmark": "SPY",
        "benchmark_label": "S&P 100 vs S&P 500 (SPY)",
    },
    {
        "id": "sp400",
        "label_fn": lambda: f"S&P 400 MidCap ({len(get_sp_400_midcap())} stocks)",
        "fetch": get_sp_400_midcap,
        "benchmark": "IJH",
        "benchmark_label": "S&P 400 MidCap (IJH)",
    },
    {
        "id": "sp600",
        "label_fn": lambda: f"S&P 600 SmallCap ({len(get_sp_600_smallcap())} stocks)",
        "fetch": get_sp_600_smallcap,
        "benchmark": "IJR",
        "benchmark_label": "S&P 600 SmallCap (IJR)",
    },
    {
        "id": "rut2000",
        "label_fn": lambda: f"Russell 2000 ({len(get_russell_2000())} stocks)",
        "fetch": get_russell_2000,
        "benchmark": "IWM",
        "benchmark_label": "Russell 2000 (IWM)",
    },
)


def _us_index_picker_options() -> list[tuple[str, dict]]:
    return [(entry["label_fn"](), entry) for entry in _US_INDEX_CATALOG]


def _crypto_coindcx_interval(tf_key: str) -> str:
    if tf_key in TF_CRYPTO:
        return tf_key
    return "1d"


def _crypto_period_bars(tf_key: str, lookback_bars: int) -> int:
    return max(lookback_bars + 25, 60)


def _build_rotation_payload(
    universe_name: str,
    benchmark_label: str,
    symbols: list[str],
    name_by_symbol: dict[str, str],
    bench_closes: pd.Series,
    asset_closes: dict[str, pd.Series],
    tf_key: str,
    lookback_bars: int,
    data_feed: str,
    market: str,
) -> dict | None:
    bench_pct = _pct_return_over_bars(bench_closes, lookback_bars)
    rows: list[dict] = []
    for sym in symbols:
        closes = asset_closes.get(sym)
        if closes is None:
            continue
        pct = _pct_return_over_bars(closes, lookback_bars)
        if pct is None:
            continue
        rel = pct - bench_pct if bench_pct is not None else pct
        clean = closes.dropna()
        last_px = float(clean.iloc[-1]) if len(clean) else None
        display = name_by_symbol.get(sym, sym)
        rows.append({
            "name": display,
            "symbol": sym,
            "pct": pct,
            "relative": rel,
            "last": last_px,
        })

    if not rows:
        return None

    rows.sort(key=lambda x: x["pct"], reverse=True)
    return {
        "universe_name": universe_name,
        "benchmark_label": benchmark_label,
        "index_name": universe_name,
        "tf_key": tf_key,
        "lookback_bars": lookback_bars,
        "benchmark_pct": bench_pct,
        "stocks": rows,
        "inflow": rows[:_ROTATION_TOP_N],
        "outflow": list(reversed(rows[-_ROTATION_TOP_N:])),
        "stock_count": len(rows),
        "requested_count": len(symbols),
        "data_feed": data_feed,
        "market": market,
    }


def compute_us_stock_price_rotation(
    universe_id: str,
    symbols: tuple[str, ...],
    tf_key: str,
    lookback_bars: int,
) -> dict | None:
    """Rank US index constituents vs matching ETF benchmark (yfinance)."""
    entry = next((e for e in _US_INDEX_CATALOG if e["id"] == universe_id), None)
    if not entry or not symbols:
        return None

    yf_interval = _tf_yf_interval(tf_key)
    period = _tf_yf_period(tf_key, lookback_bars)
    benchmark = entry["benchmark"]
    all_syms = list(dict.fromkeys([benchmark] + list(symbols)))
    sym_closes = _load_yf_closes(all_syms, period=period, interval=yf_interval)
    bench_closes = sym_closes.get(benchmark)
    if bench_closes is None or bench_closes.dropna().empty:
        logger.error("US rotation: benchmark %s unavailable", benchmark)
        return None

    asset_closes = {s: sym_closes[s] for s in symbols if s in sym_closes}
    if not asset_closes:
        return None

    name_by_symbol = {s: s for s in symbols}
    return _build_rotation_payload(
        entry["label_fn"](),
        entry["benchmark_label"],
        list(symbols),
        name_by_symbol,
        bench_closes,
        asset_closes,
        tf_key,
        lookback_bars,
        "yfinance",
        "us",
    )


def compute_crypto_price_rotation(
    universe_name: str,
    instruments: tuple[tuple[str, str], ...],
    tf_key: str,
    lookback_bars: int,
    benchmark_symbol: str = CRYPTO_BENCHMARK_SYMBOL,
    benchmark_label: str = CRYPTO_BENCHMARK_LABEL,
) -> dict | None:
    """Rank CoinDCX pairs vs BTC over lookback bars."""
    if not instruments:
        return None

    symbols = [sym for _, sym in instruments]
    name_by_symbol = {sym: name for name, sym in instruments}
    interval = _crypto_coindcx_interval(tf_key)
    bar_limit = _crypto_period_bars(tf_key, lookback_bars)
    all_syms = list(dict.fromkeys([benchmark_symbol] + symbols))
    sym_closes = _load_crypto_closes(all_syms, interval, limit=bar_limit)

    if tf_key == "1M" and len(sym_closes) < 2:
        sym_closes = _load_crypto_closes(all_syms, "1d", limit=max(lookback_bars + 25, 60))

    bench_closes = sym_closes.get(benchmark_symbol)
    if bench_closes is None or bench_closes.dropna().empty:
        logger.error("Crypto rotation: benchmark %s unavailable", benchmark_symbol)
        return None

    asset_closes = {s: sym_closes[s] for s in symbols if s in sym_closes}
    if not asset_closes:
        return None

    return _build_rotation_payload(
        universe_name,
        benchmark_label,
        symbols,
        name_by_symbol,
        bench_closes,
        asset_closes,
        tf_key,
        lookback_bars,
        "coindcx",
        "crypto",
    )


def _render_crypto_universe_picker(prefix: str) -> tuple[str, list[tuple[str, str]]]:
    group_sel = st.selectbox(
        "₿ Universe bucket",
        list(CRYPTO_SECTOR_FILTER_GROUPS.keys()) + ["Custom pairs"],
        index=0,
        key=f"{prefix}_bucket",
    )

    if group_sel == "Custom pairs":
        raw = st.text_area(
            "Custom CoinDCX pairs (comma-separated)",
            value="B-BTCUSDT,B-ETHUSDT,B-SOLUSDT,B-XRPUSDT",
            height=70,
            key=f"{prefix}_custom",
            help="CoinDCX USDT perpetual symbols, e.g. B-ETHUSDT",
        )
        instruments: list[tuple[str, str]] = []
        for part in raw.split(","):
            part = part.strip().upper()
            if not part:
                continue
            if not part.startswith("B-"):
                part = f"B-{part.replace('_', '').replace('-', '')}"
                if not part.endswith("USDT"):
                    part = f"{part}USDT" if "USDT" not in part else part
            instruments.append((part.replace("B-", "").replace("USDT", ""), part))
        return group_sel, instruments

    names = list(CRYPTO_SECTOR_FILTER_GROUPS.get(group_sel, []))
    st.caption(f"**{len(names)}** pairs in **{group_sel}**")
    default = names if len(names) <= 12 else names[:10]
    selected = st.multiselect(
        "Pairs to include",
        names,
        default=default,
        key=f"{prefix}_pairs_{group_sel}",
    )
    instruments = [
        (name, CRYPTO_SECTOR_SYMBOLS.get(name, name))
        for name in selected
    ]
    return group_sel, instruments


def _render_market_price_rotation_tab(market: MarketKind) -> None:
    from app.market_pulse.ask_ai_context import snapshot_section_for_ask_ai

    is_us = market == "us"
    prefix = "spr_us" if is_us else "spr_c"
    section_id = "stock_price_rotation_us" if is_us else "stock_price_rotation_crypto"
    payload_key = f"{section_id}_payload"
    params_key = f"{section_id}_params"
    flag = "🇺🇸" if is_us else "₿"

    _render_news_scanner_styles()
    st.markdown(
        f'<div class="section-header-ns">{flag} Price Rotation — '
        f'{"US Index Constituents" if is_us else "CoinDCX Pairs"}</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Pick a **universe**, subset **symbols**, set **candle interval** (1m → 1M) "
        "and **lookback**, then analyse which names are rotating in vs out relative to the "
        + ("matching US index ETF." if is_us else "**BTC** benchmark on CoinDCX.")
    )
    if not is_us:
        render_crypto_session_caption(short=True)

    if is_us:
        options = _us_index_picker_options()
        labels = [o[0] for o in options]
        entry_by_label = {label: entry for label, entry in options}
        default_idx = next((i for i, (lbl, _) in enumerate(options) if lbl.startswith("S&P 500")), 0)
        picked = st.selectbox("📊 US index", labels, index=default_idx, key=f"{prefix}_index")
        entry = entry_by_label[picked]
        full_list = entry["fetch"]()
        all_symbols = full_list[:_MAX_CONSTITUENTS]
        universe_id = entry["id"]
        universe_name = picked
        benchmark_label = entry["benchmark_label"]

        if len(full_list) > _MAX_CONSTITUENTS:
            st.caption(
                f"Showing first **{_MAX_CONSTITUENTS}** of **{len(full_list)}** symbols "
                "(performance cap). Use multiselect to focus on a subset."
            )

        selected_symbols = st.multiselect(
            "Constituent tickers",
            all_symbols,
            default=all_symbols[: min(40, len(all_symbols))],
            key=f"{prefix}_symbols_{universe_id}",
        )
        instruments: list[tuple[str, str]] = [(s, s) for s in selected_symbols]
    else:
        universe_name, instruments = _render_crypto_universe_picker(prefix)
        universe_id = universe_name
        benchmark_label = CRYPTO_BENCHMARK_LABEL
        selected_symbols = [sym for _, sym in instruments]

    tf_key, lookback_bars = render_rotation_timeframe_controls(prefix)

    load_btn = st.button(
        f"🔄 Analyse {'US' if is_us else 'Crypto'} Rotation",
        key=f"{prefix}_load",
        type="primary",
    )

    if is_us:
        st.info("ℹ️ **Active Feed:** Yahoo Finance — US stocks vs matching index ETF benchmark.")
    else:
        st.info(CRYPTO_FEED_BANNER)

    if load_btn:
        if not selected_symbols:
            st.warning("Select at least one symbol.")
        else:
            if is_us:
                compute_us_stock_price_rotation.clear()
                sym_tuple = tuple(selected_symbols)
                with st.spinner(
                    f"Computing US rotation for {len(sym_tuple)} tickers "
                    f"({tf_key}, {lookback_bars} bars)…"
                ):
                    result = compute_us_stock_price_rotation(
                        universe_id, sym_tuple, tf_key, lookback_bars,
                    )
            else:
                compute_crypto_price_rotation.clear()
                inst_tuple = tuple(instruments)
                with st.spinner(
                    f"Computing crypto rotation for {len(inst_tuple)} pairs "
                    f"({tf_key}, {lookback_bars} bars)…"
                ):
                    result = compute_crypto_price_rotation(
                        universe_name, inst_tuple, tf_key, lookback_bars,
                    )

            if result:
                st.session_state[payload_key] = result
                st.session_state[params_key] = {
                    "universe_id": universe_id,
                    "symbols": tuple(selected_symbols),
                    "tf_key": tf_key,
                    "lookback_bars": lookback_bars,
                }
            else:
                st.session_state.pop(payload_key, None)
                st.error(
                    "Unable to compute rotation — check network"
                    + (" or try during US market hours for intraday bars." if is_us else ".")
                )

    payload = st.session_state.get(payload_key)
    if not payload:
        st.info("Configure universe and timeframe, then click **Analyse** to load results.")
        return

    params = st.session_state.get(params_key) or {}
    if (
        params.get("universe_id") != universe_id
        or params.get("tf_key") != tf_key
        or params.get("lookback_bars") != lookback_bars
        or tuple(params.get("symbols") or ()) != tuple(selected_symbols)
    ):
        st.warning("Settings changed — click **Analyse** again to refresh.")

    render_rotation_results(
        payload,
        asset_label="Ticker" if is_us else "Pair",
        benchmark_label=benchmark_label,
    )
    snapshot_section_for_ask_ai(section_id)


def render_stock_price_rotation_us_tab() -> None:
    _render_market_price_rotation_tab("us")


def render_stock_price_rotation_crypto_tab() -> None:
    _render_market_price_rotation_tab("crypto")
