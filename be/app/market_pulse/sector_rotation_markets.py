"""
sector_rotation_markets.py
--------------------------
US (SPDR) and Crypto (CoinDCX) sector rotation — HTF & intraday windows.
Shared ticker / sector filter UI (same pattern as equity index pickers).
"""

from __future__ import annotations

import logging
from typing import Literal

import pandas as pd
import yfinance as yf

from app.market_pulse.crypto_session import (
    CRYPTO_FEED_BANNER,
    CRYPTO_MOVERS_CAPTION_SUFFIX,
    CRYPTO_SESSION_CAPTION_SHORT,
    render_crypto_session_caption,
)
from app.market_pulse.heatmap import fetch_coindcx_ohlcv
from app.market_pulse.nse_index_yfinance import sector_fallback_index_names
from app.market_pulse.news_scanner import (
    _SECTOR_ROTATION_TOP_N,
    _render_rotation_bar_chart,
    _render_rotation_intraday_timeframe_block,
    _render_rotation_timeframe_block,
    fmt_last_pct,
)

logger = logging.getLogger(__name__)

MarketKind = Literal["us", "crypto"]

# ─── US SPDR sector ETFs ───────────────────────────────────────────────────

US_SPDR_SECTORS: dict[str, str] = {
    "Communication (XLC)": "XLC",
    "Consumer Discretionary (XLY)": "XLY",
    "Consumer Staples (XLP)": "XLP",
    "Energy (XLE)": "XLE",
    "Financials (XLF)": "XLF",
    "Health Care (XLV)": "XLV",
    "Industrials (XLI)": "XLI",
    "Materials (XLB)": "XLB",
    "Real Estate (XLRE)": "XLRE",
    "Technology (XLK)": "XLK",
    "Utilities (XLU)": "XLU",
}

US_SECTOR_FILTER_GROUPS: dict[str, list[str]] = {
    "All SPDR Sector ETFs": list(US_SPDR_SECTORS.keys()),
    "Cyclicals": [
        "Consumer Discretionary (XLY)",
        "Industrials (XLI)",
        "Materials (XLB)",
        "Energy (XLE)",
        "Financials (XLF)",
    ],
    "Defensives": [
        "Consumer Staples (XLP)",
        "Health Care (XLV)",
        "Utilities (XLU)",
        "Real Estate (XLRE)",
    ],
    "Growth / Tech": [
        "Technology (XLK)",
        "Communication (XLC)",
        "Consumer Discretionary (XLY)",
    ],
}

US_BENCHMARK_SYMBOL = "SPY"
US_BENCHMARK_LABEL = "S&P 500 (SPY)"

# ─── Crypto sector buckets (CoinDCX USDT futures) ───────────────────────────

CRYPTO_SECTOR_SYMBOLS: dict[str, str] = {
    "Bitcoin (BTC)": "B-BTCUSDT",
    "Ethereum (ETH)": "B-ETHUSDT",
    "Solana (SOL)": "B-SOLUSDT",
    "XRP": "B-XRPUSDT",
    "Celestia (TIA)": "B-TIAUSDT",
    "Cardano (ADA)": "B-ADAUSDT",
    "Avalanche (AVAX)": "B-AVAXUSDT",
    "Chainlink (LINK)": "B-LINKUSDT",
    "Polkadot (DOT)": "B-DOTUSDT",
    "NEAR": "B-NEARUSDT",
    "Litecoin (LTC)": "B-LTCUSDT",
    "Dogecoin (DOGE)": "B-DOGEUSDT",
    "Shiba (SHIB)": "B-SHIBUSDT",
    "Pepe (PEPE)": "B-PEPEUSDT",
    "Sui (SUI)": "B-SUIUSDT",
    "Injective (INJ)": "B-INJUSDT",
    "Arbitrum (ARB)": "B-ARBUSDT",
    "Optimism (OP)": "B-OPUSDT",
    "Uniswap (UNI)": "B-UNIUSDT",
    "Aave (AAVE)": "B-AAVEUSDT",
    "Render (RNDR)": "B-RENDERUSDT",
    "Fetch (FET)": "B-FETUSDT",
    "Worldcoin (WLD)": "B-WLDUSDT",
}

CRYPTO_SECTOR_FILTER_GROUPS: dict[str, list[str]] = {
    "Major L1 / Large Cap": [
        "Bitcoin (BTC)",
        "Ethereum (ETH)",
        "Solana (SOL)",
        "XRP",
        "Celestia (TIA)",
        "Cardano (ADA)",
        "Avalanche (AVAX)",
    ],
    "DeFi & Infrastructure": [
        "Chainlink (LINK)",
        "Polkadot (DOT)",
        "Uniswap (UNI)",
        "Aave (AAVE)",
        "Arbitrum (ARB)",
        "Optimism (OP)",
        "Injective (INJ)",
        "Render (RNDR)",
        "Fetch (FET)",
    ],
    "High Beta / Meme": [
        "Dogecoin (DOGE)",
        "Shiba (SHIB)",
        "Pepe (PEPE)",
        "NEAR",
        "Sui (SUI)",
        "Worldcoin (WLD)",
    ],
    "All tracked pairs": list(CRYPTO_SECTOR_SYMBOLS.keys()),
}

CRYPTO_BENCHMARK_SYMBOL = "B-BTCUSDT"
CRYPTO_BENCHMARK_LABEL = "Bitcoin (BTC)"

CRYPTO_DYNAMIC_BUCKETS: tuple[str, ...] = (
    "Top Volume",
    "Top Volatile",
    "Top Risen",
    "Top Fallen",
)


def _crypto_filter_group_options() -> list[str]:
    return list(CRYPTO_SECTOR_FILTER_GROUPS.keys()) + list(CRYPTO_DYNAMIC_BUCKETS) + ["Custom symbols"]


def _render_crypto_movers_panel(
    symbol_filter: set[str] | None = None,
    top_n: int = 10,
    *,
    title: str = "📊 Live CoinDCX movers",
) -> None:
    from app.market_pulse.heatmap import coindcx_leader_tables

    tables = coindcx_leader_tables(symbol_filter, top_n=top_n)
    if not tables:
        st.caption("Live mover data unavailable — check CoinDCX connectivity.")
        return

    scope = (
        f"within **{len(symbol_filter)}** selected pair(s)"
        if symbol_filter
        else "across **all** CoinDCX USDT futures"
    )
    st.markdown(f"##### {title}")
    st.caption(f"{CRYPTO_MOVERS_CAPTION_SUFFIX} · {scope} · refreshed every ~60s")

    c1, c2, c3, c4 = st.columns(4)
    panels = (
        (c1, "Top Volume", "📈"),
        (c2, "Top Volatile", "⚡"),
        (c3, "Top Risen", "🟢"),
        (c4, "Top Fallen", "🔴"),
    )
    for col, key, icon in panels:
        with col:
            st.markdown(f"**{icon} {key}**")
            rows = tables.get(key) or []
            if not rows:
                st.caption("No data.")
                continue
            display_rows = []
            for r in rows:
                row = {"Pair": r["Pair"], "Change %": r["Change %"]}
                if key == "Top Volume":
                    row["Volume"] = r["Volume"]
                elif key == "Top Volatile":
                    row["Range %"] = r["Range %"]
                else:
                    row["Price ($)"] = r["Price ($)"]
                display_rows.append(row)
            st.dataframe(pd.DataFrame(display_rows), hide_index=True, width="stretch")


def _symbols_from_rotation_payload(payload: dict) -> set[str]:
    syms: set[str] = set()
    for wk in ("minutes", "hours", "days"):
        w = payload.get(wk) or {}
        for s in w.get("sectors") or []:
            sym = s.get("yf") or s.get("name")
            if sym:
                syms.add(sym)
    return syms


def _pct_return_over_bars(close_series: pd.Series, bars: int) -> float | None:
    closes = close_series.dropna()
    if closes is None or len(closes) < 2:
        return None
    bars = min(int(bars), len(closes) - 1)
    if bars < 1:
        return None
    start = float(closes.iloc[-1 - bars])
    end = float(closes.iloc[-1])
    if start <= 0:
        return None
    return (end / start - 1) * 100


def _yf_close_series(raw: pd.DataFrame, yf_sym: str) -> pd.Series | None:
    if raw is None or raw.empty:
        return None
    try:
        if isinstance(raw.columns, pd.MultiIndex):
            if yf_sym in raw.columns.get_level_values(0):
                col = raw[yf_sym]["Close"] if "Close" in raw[yf_sym].columns else raw[yf_sym]["close"]
            else:
                return None
        elif "Close" in raw.columns and len(raw.columns) <= 6:
            col = raw["Close"]
        elif yf_sym in raw.columns:
            col = raw[yf_sym]
        else:
            return None
        closes = pd.to_numeric(col, errors="coerce").dropna()
        return closes if not closes.empty else None
    except Exception:
        return None


def _load_yf_closes(symbols: list[str], period: str, interval: str = "1d") -> dict[str, pd.Series]:
    sym_closes: dict[str, pd.Series] = {}
    unique = list(dict.fromkeys(s for s in symbols if s))
    if not unique:
        return sym_closes
    try:
        raw = yf.download(
            unique,
            period=period,
            interval=interval,
            group_by="ticker",
            progress=False,
            auto_adjust=True,
            threads=True,
        )
    except Exception as exc:
        logger.warning("yfinance batch download failed: %s", exc)
        raw = pd.DataFrame()

    for sym in unique:
        closes = _yf_close_series(raw, sym)
        if closes is not None:
            sym_closes[sym] = closes

    for sym in unique:
        if sym in sym_closes:
            continue
        try:
            tdf = yf.download(sym, period=period, interval=interval, progress=False, auto_adjust=True)
            closes = _yf_close_series(tdf, sym)
            if closes is not None:
                sym_closes[sym] = closes
        except Exception:
            continue
    return sym_closes


def _load_crypto_closes(symbols: list[str], interval: str, limit: int) -> dict[str, pd.Series]:
    out: dict[str, pd.Series] = {}
    for sym in symbols:
        df = fetch_coindcx_ohlcv(sym, interval, limit=limit)
        if df is None or df.empty or "close" not in df.columns:
            continue
        closes = pd.to_numeric(df["close"], errors="coerce").dropna()
        if not closes.empty:
            out[sym] = closes
    return out


def _build_rotation_window(
    index_closes: dict[str, pd.Series],
    name_by_symbol: dict[str, str],
    benchmark_closes: pd.Series | None,
    bars: int,
) -> dict:
    bench = _pct_return_over_bars(benchmark_closes, bars) if benchmark_closes is not None else None
    rows: list[dict] = []
    for sym, closes in index_closes.items():
        pct = _pct_return_over_bars(closes, bars)
        if pct is None:
            continue
        rel = pct - bench if bench is not None else pct
        closes_clean = closes.dropna()
        last_px = float(closes_clean.iloc[-1]) if len(closes_clean) else None
        rows.append({
            "name": name_by_symbol.get(sym, sym),
            "pct": pct,
            "relative": rel,
            "last": last_px,
            "yf": sym,
        })
    rows.sort(key=lambda x: x["pct"], reverse=True)
    return {
        "benchmark_pct": bench,
        "sectors": rows,
        "inflow": rows[:_SECTOR_ROTATION_TOP_N],
        "outflow": list(reversed(rows[-_SECTOR_ROTATION_TOP_N:])),
    }


def _instruments_to_maps(
    instruments: list[tuple[str, str]],
) -> tuple[list[str], dict[str, str]]:
    symbols: list[str] = []
    name_by_symbol: dict[str, str] = {}
    for name, sym in instruments:
        if not sym:
            continue
        symbols.append(sym)
        name_by_symbol[sym] = name
    return symbols, name_by_symbol


def compute_market_sector_rotation_htf(
    instruments: tuple[tuple[str, str], ...],
    benchmark_symbol: str,
    days: int,
    weeks: int,
    months: int,
    market: str,
) -> dict | None:
    """Daily-bar sector rotation for US (yfinance) or Crypto (CoinDCX 1d)."""
    if not instruments:
        return None

    symbols, name_by_symbol = _instruments_to_maps(list(instruments))
    all_syms = list(dict.fromkeys([benchmark_symbol] + symbols))
    fetch_months = max(int(months) + 1, 2)
    period = f"{fetch_months}mo"

    if market == "crypto":
        limit = max(int(months) * 21 + 30, 90)
        sym_closes = _load_crypto_closes(all_syms, "1d", limit=limit)
    else:
        sym_closes = _load_yf_closes(all_syms, period=period, interval="1d")

    bench_closes = sym_closes.get(benchmark_symbol)
    if bench_closes is None or bench_closes.dropna().empty:
        logger.error("Sector rotation HTF (%s): benchmark %s unavailable", market, benchmark_symbol)
        return None

    index_closes = {s: sym_closes[s] for s in symbols if s in sym_closes}
    if not index_closes:
        return None

    day_bars = max(1, int(days))
    week_bars = max(1, int(weeks) * 5)
    month_bars = max(1, int(months) * 21)

    return {
        "daily": _build_rotation_window(index_closes, name_by_symbol, bench_closes, day_bars),
        "weekly": _build_rotation_window(index_closes, name_by_symbol, bench_closes, week_bars),
        "monthly": _build_rotation_window(index_closes, name_by_symbol, bench_closes, month_bars),
        "sector_count": len(index_closes),
        "days": days,
        "weeks": weeks,
        "months": months,
        "data_feed": "coindcx" if market == "crypto" else "yfinance",
        "market": market,
        "benchmark_symbol": benchmark_symbol,
    }


def compute_market_sector_rotation_intraday(
    instruments: tuple[tuple[str, str], ...],
    benchmark_symbol: str,
    minutes: int,
    hours: int,
    days: int,
    market: str,
) -> dict | None:
    """Intraday sector rotation — US via yfinance; Crypto via CoinDCX."""
    if not instruments:
        return None

    symbols, name_by_symbol = _instruments_to_maps(list(instruments))
    minute_bars = max(1, int(minutes) // 5)
    hour_bars = max(1, int(hours))
    day_bars = max(1, int(days))

    if market == "crypto":
        windows_cfg = {
            "minutes": ("5m", max(minute_bars + 20, 80)),
            "hours": ("1h", max(hour_bars + 30, 120)),
            "days": ("1d", max(day_bars + 25, 60)),
        }
    else:
        windows_cfg = {
            "minutes": ("5m", max(minute_bars + 20, 80)),
            "hours": ("1h", max(hour_bars + 30, 120)),
            "days": ("1d", max(day_bars + 25, 60)),
        }

    result_windows: dict[str, dict] = {}
    sector_count = 0

    for kind, (interval, bar_limit) in windows_cfg.items():
        if market == "crypto":
            all_syms = list(dict.fromkeys([benchmark_symbol] + symbols))
            sym_closes = _load_crypto_closes(all_syms, interval, limit=bar_limit)
        else:
            period = "5d" if kind == "minutes" else ("60d" if kind == "hours" else f"{max(day_bars + 10, 15)}d")
            all_syms = list(dict.fromkeys([benchmark_symbol] + symbols))
            sym_closes = _load_yf_closes(all_syms, period=period, interval=interval)

        bench_closes = sym_closes.get(benchmark_symbol)
        if bench_closes is None or bench_closes.dropna().empty:
            logger.error("Sector rotation intraday (%s/%s): benchmark unavailable", market, kind)
            continue

        index_closes = {s: sym_closes[s] for s in symbols if s in sym_closes}
        if not index_closes:
            continue
        sector_count = max(sector_count, len(index_closes))

        bars = minute_bars if kind == "minutes" else (hour_bars if kind == "hours" else day_bars)
        window = _build_rotation_window(index_closes, name_by_symbol, bench_closes, bars)
        window["bars"] = bars
        window["interval"] = interval
        result_windows[kind] = window

    if not result_windows:
        return None

    return {
        "minutes": result_windows.get("minutes"),
        "hours": result_windows.get("hours"),
        "days": result_windows.get("days"),
        "sector_count": sector_count,
        "minutes_lookback": minutes,
        "hours_lookback": hours,
        "days_lookback": days,
        "data_feed": "coindcx" if market == "crypto" else "yfinance",
        "market": market,
        "benchmark_symbol": benchmark_symbol,
    }


def render_sector_rotation_symbol_filter(
    market: MarketKind,
    key_prefix: str,
) -> list[tuple[str, str]]:
    """
    Sector / symbol multiselect — same Index/Group + multiselect pattern as equity tabs.
    Returns list of (display_name, symbol).
    """
    if market == "us":
        groups = US_SECTOR_FILTER_GROUPS
        symbol_map = US_SPDR_SECTORS
        custom_default = "XLK,XLF,XLE,XLV,XLY"
        group_label = "Sector universe"
        group_options = list(groups.keys()) + ["Custom symbols"]
    else:
        groups = CRYPTO_SECTOR_FILTER_GROUPS
        symbol_map = CRYPTO_SECTOR_SYMBOLS
        custom_default = "B-BTCUSDT,B-ETHUSDT,B-SOLUSDT,B-XRPUSDT"
        group_label = "Crypto sector bucket"
        group_options = _crypto_filter_group_options()

    c1, c2 = st.columns([1, 2])
    with c1:
        group_sel = st.selectbox(
            group_label,
            group_options,
            index=0,
            key=f"{key_prefix}_sr_group",
        )
    with c2:
        if group_sel == "Custom symbols":
            raw = st.text_area(
                "Custom symbols (comma-separated)",
                value=custom_default,
                height=70,
                key=f"{key_prefix}_sr_custom",
                help="US: Yahoo tickers (XLK, XLF…). Crypto: CoinDCX pairs (B-BTCUSDT…).",
            )
            picks: list[str] = []
            for part in raw.split(","):
                part = part.strip()
                if not part:
                    continue
                if market == "crypto" and not part.upper().startswith("B-"):
                    part = f"B-{part.upper().replace('_', '').replace('-', '')}"
                    if not part.endswith("USDT"):
                        part = f"{part}USDT" if "USDT" not in part else part
                picks.append(part.upper())
            return [(p, p) for p in dict.fromkeys(picks)]

        if market == "crypto" and group_sel in CRYPTO_DYNAMIC_BUCKETS:
            from app.market_pulse.heatmap import coindcx_leader_pairs

            top_n = st.selectbox(
                "Leaderboard size",
                [10, 15, 20, 25],
                index=1,
                key=f"{key_prefix}_sr_leader_n",
            )
            pairs = coindcx_leader_pairs(group_sel, top_n=int(top_n))
            if not pairs:
                st.warning(f"Could not load **{group_sel}** from CoinDCX. Try again or pick another bucket.")
                return []
            labels = [p[0] for p in pairs]
            st.info(f"📊 **{group_sel}**: {len(labels)} live leader(s) from CoinDCX")
            selected = st.multiselect(
                "Pairs to include in rotation",
                labels,
                default=labels,
                key=f"{key_prefix}_sr_ms_{group_sel}",
            )
            sym_by_label = dict(pairs)
            return [(name, sym_by_label[name]) for name in selected if name in sym_by_label]

        names = list(groups.get(group_sel, []))
        st.info(f"📊 **{group_sel}**: {len(names)} sector(s)")
        default = names if len(names) <= 11 else names[:8]
        selected = st.multiselect(
            "Sectors / symbols to include",
            names,
            default=default,
            key=f"{key_prefix}_sr_ms",
        )
        out: list[tuple[str, str]] = []
        for name in selected:
            sym = symbol_map.get(name, name)
            out.append((name, sym))
        return out


def render_india_sector_index_filter(key_prefix: str) -> list[str]:
    """Multiselect filter for Nifty sectoral indices (India sections)."""
    options = list(st.session_state.get(f"{key_prefix}_sector_options") or sector_fallback_index_names())
    payload_names: list[str] = []
    for sk in ("sector_rotation_payload", "sector_rotation_intraday_payload"):
        pl = st.session_state.get(sk) or {}
        for wk in ("daily", "weekly", "monthly", "minutes", "hours", "days"):
            w = pl.get(wk) or {}
            for s in w.get("sectors") or []:
                n = s.get("name")
                if n and n not in payload_names:
                    payload_names.append(n)
    for n in payload_names:
        if n not in options:
            options.append(n)
    options = sorted(set(options))
    st.session_state[f"{key_prefix}_sector_options"] = options

    default = st.session_state.get(f"{key_prefix}_filter_default")
    if default is None:
        default = options
    selected = st.multiselect(
        "Sector indices to include",
        options,
        default=[x for x in default if x in options] or options[: min(8, len(options))],
        key=f"{key_prefix}_sector_filter",
        help="Subset Nifty sectoral indices — same filter pattern as US/Crypto sector pickers.",
    )
    st.session_state[f"{key_prefix}_filter_default"] = selected
    return selected


def _benchmark_label(market: MarketKind) -> str:
    return US_BENCHMARK_LABEL if market == "us" else CRYPTO_BENCHMARK_LABEL


def _render_market_rotation_htf_content(payload: dict, market: MarketKind) -> None:
    days = payload.get("days", 5)
    weeks = payload.get("weeks", 4)
    months = payload.get("months", 3)
    bench = _benchmark_label(market)
    feed = payload.get("data_feed", "yfinance").upper()
    st.caption(
        f"Tracking **{payload.get('sector_count', 0)}** sectors vs **{bench}** · "
        f"Feed: **{feed}** · Last · Return % · relative strength"
    )
    for label, icon, kind in (
        ("Daily", "📅", "daily"),
        ("Weekly", "📆", "weekly"),
        ("Monthly", "🗓️", "monthly"),
    ):
        _render_rotation_timeframe_block(
            label, icon, kind, payload.get(kind), days, weeks, months,
            sr_map=None, benchmark_label=bench,
        )


def _render_market_rotation_intraday_content(payload: dict, market: MarketKind) -> None:
    minutes = payload.get("minutes_lookback", 60)
    hours = payload.get("hours_lookback", 4)
    days = payload.get("days_lookback", 3)
    bench = _benchmark_label(market)
    feed = payload.get("data_feed", "yfinance").upper()
    st.caption(
        f"Intraday rotation across **{payload.get('sector_count', 0)}** sectors vs **{bench}** · "
        f"Feed: **{feed}** · 5m / 1h / 1d bars"
    )
    for label, icon, kind in (
        ("Minutes", "⏱️", "minutes"),
        ("Hours", "🕐", "hours"),
        ("Days", "📅", "days"),
    ):
        _render_rotation_intraday_timeframe_block(
            label, icon, kind, payload.get(kind), minutes, hours, days,
            sr_map=None, benchmark_label=bench,
        )

    if market == "crypto":
        st.markdown("<div style='margin-top:16px;'></div>", unsafe_allow_html=True)
        loaded_syms = _symbols_from_rotation_payload(payload)
        _render_crypto_movers_panel(
            loaded_syms if loaded_syms else None,
            top_n=10,
            title="📊 Top Volume · Volatile · Risen · Fallen",
        )


def _market_feed_banner(market: MarketKind) -> None:
    if market == "us":
        st.info("ℹ️ **Active Feed:** Yahoo Finance — US SPDR sector ETFs vs **SPY** benchmark.")
    else:
        st.info(CRYPTO_FEED_BANNER)


def _render_market_sector_rotation_htf_tab(market: MarketKind) -> None:
    from app.market_pulse.news_scanner import _render_news_scanner_styles
    from app.market_pulse.ask_ai_context import snapshot_section_for_ask_ai

    is_us = market == "us"
    section_id = "sector_rotation_us" if is_us else "sector_rotation_crypto"
    payload_key = f"{section_id}_payload"
    flag = "🇺🇸" if is_us else "₿"
    title = (
        f"{flag} Sector Rotation — daily · weekly · monthly"
        + (" (US)" if is_us else " (Crypto)")
    )

    _render_news_scanner_styles()
    st.markdown(f'<div class="section-header-ns">🔄 {title}</div>', unsafe_allow_html=True)
    st.caption(
        "Compare sector returns over configurable **daily**, **weekly**, and **monthly** windows. "
        + ("SPDR sector ETFs vs SPY." if is_us else "Major CoinDCX pairs vs BTC.")
    )
    if not is_us:
        render_crypto_session_caption(short=True)

    st.markdown("##### 🎯 Sector / symbol filter")
    key_prefix = "sr_us" if is_us else "sr_c"
    instruments = render_sector_rotation_symbol_filter(market, key_prefix)

    c1, c2, c3 = st.columns(3)
    with c1:
        rot_days = st.slider("Daily lookback (sessions)", 1, 20, 5, key=f"{key_prefix}_days")
    with c2:
        rot_weeks = st.slider("Weekly lookback (weeks)", 1, 12, 4, key=f"{key_prefix}_weeks")
    with c3:
        rot_months = st.slider("Monthly lookback (months)", 1, 12, 3, key=f"{key_prefix}_months")

    load_btn = st.button(
        f"🔄 Load {'US' if is_us else 'Crypto'} Sector Rotation",
        key=f"{key_prefix}_load",
        type="primary",
    )
    _market_feed_banner(market)

    benchmark = US_BENCHMARK_SYMBOL if is_us else CRYPTO_BENCHMARK_SYMBOL

    if load_btn:
        compute_market_sector_rotation_htf.clear()
        if not instruments:
            st.error("Select at least one sector / symbol.")
        else:
            inst_tuple = tuple(instruments)
            with st.spinner(f"Computing {len(instruments)} sector(s)…"):
                rotation = compute_market_sector_rotation_htf(
                    inst_tuple, benchmark, rot_days, rot_weeks, rot_months, market,
                )
            if rotation:
                st.session_state[payload_key] = rotation
            else:
                st.session_state.pop(payload_key, None)
                st.error("Unable to compute sector rotation — check symbols or network.")

    payload = st.session_state.get(payload_key)
    if not payload:
        st.info("Choose sectors above, then click **Load** to analyse rotation.")
        return

    if (
        payload.get("days") != rot_days
        or payload.get("weeks") != rot_weeks
        or payload.get("months") != rot_months
    ):
        st.warning("Lookback settings changed — click **Load** again to refresh.")

    _render_market_rotation_htf_content(payload, market)
    snapshot_section_for_ask_ai(section_id)


def _render_market_sector_rotation_intraday_tab(market: MarketKind) -> None:
    from app.market_pulse.news_scanner import _render_news_scanner_styles
    from app.market_pulse.ask_ai_context import snapshot_section_for_ask_ai

    is_us = market == "us"
    section_id = "sector_rotation_us_intraday" if is_us else "sector_rotation_crypto_intraday"
    payload_key = f"{section_id}_payload"
    flag = "🇺🇸" if is_us else "₿"
    title = (
        f"{flag} Sector Rotation — mins · hours · days"
        + (" (US)" if is_us else " (Crypto)")
    )

    _render_news_scanner_styles()
    st.markdown(f'<div class="section-header-ns">🔄 {title}</div>', unsafe_allow_html=True)
    st.caption(
        "Session-style rotation over **minute** (5m), **hour** (1h), and **day** windows. "
        + (
            "US market hours for freshest SPDR data."
            if is_us
            else f"{CRYPTO_SESSION_CAPTION_SHORT} Bucket filter includes **Top Volume**, "
            "**Top Volatile**, **Top Risen**, and **Top Fallen** live leader universes."
        )
    )

    st.markdown("##### 🎯 Sector / symbol filter")
    key_prefix = "sri_us" if is_us else "sri_c"
    instruments = render_sector_rotation_symbol_filter(market, key_prefix)

    if not is_us:
        with st.expander("📊 Preview — Top Volume · Volatile · Risen · Fallen (all CoinDCX)", expanded=False):
            _render_crypto_movers_panel(None, top_n=10, title="Market-wide live leaders")

    c1, c2, c3 = st.columns(3)
    with c1:
        rot_mins = st.slider("Minutes lookback", 15, 240, 60, step=15, key=f"{key_prefix}_mins")
    with c2:
        rot_hours = st.slider("Hours lookback", 1, 24, 4, key=f"{key_prefix}_hours")
    with c3:
        rot_days = st.slider("Days lookback", 1, 10, 3, key=f"{key_prefix}_days")

    load_btn = st.button(
        f"🔄 Load {'US' if is_us else 'Crypto'} Intraday Rotation",
        key=f"{key_prefix}_load",
        type="primary",
    )
    _market_feed_banner(market)

    benchmark = US_BENCHMARK_SYMBOL if is_us else CRYPTO_BENCHMARK_SYMBOL

    if load_btn:
        compute_market_sector_rotation_intraday.clear()
        if not instruments:
            st.error("Select at least one sector / symbol.")
        else:
            inst_tuple = tuple(instruments)
            with st.spinner(f"Computing intraday rotation for {len(instruments)} sector(s)…"):
                rotation = compute_market_sector_rotation_intraday(
                    inst_tuple, benchmark, rot_mins, rot_hours, rot_days, market,
                )
            if rotation:
                st.session_state[payload_key] = rotation
            else:
                st.session_state.pop(payload_key, None)
                st.error("Unable to compute intraday rotation — check symbols or retry.")

    payload = st.session_state.get(payload_key)
    if not payload:
        st.info("Choose sectors above, then click **Load** to analyse intraday rotation.")
        return

    if (
        payload.get("minutes_lookback") != rot_mins
        or payload.get("hours_lookback") != rot_hours
        or payload.get("days_lookback") != rot_days
    ):
        st.warning("Lookback settings changed — click **Load** again to refresh.")

    _render_market_rotation_intraday_content(payload, market)
    snapshot_section_for_ask_ai(section_id)


def render_sector_rotation_us_tab() -> None:
    _render_market_sector_rotation_htf_tab("us")


def render_sector_rotation_us_intraday_tab() -> None:
    _render_market_sector_rotation_intraday_tab("us")


def render_sector_rotation_crypto_tab() -> None:
    _render_market_sector_rotation_htf_tab("crypto")


def render_sector_rotation_crypto_intraday_tab() -> None:
    _render_market_sector_rotation_intraday_tab("crypto")
