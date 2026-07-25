"""
week52_high_low.py
------------------
52-week high / low scanner for Nifty index constituents.
Shows stocks at/near 52W extremes plus % distance from ATH and ATL.
"""

from __future__ import annotations

import logging
import time
from typing import Optional
from urllib.parse import quote

import pandas as pd
import requests
import yfinance as yf

from app.market_pulse.news_scanner import (
    _NIFTY_BREADTH_GROUP_LABELS,
    _NIFTY_BREADTH_GROUP_ORDER,
    _render_news_scanner_styles,
    _yf_ohlcv_from_download,
    fetch_nse_market_breadth,
    fmt_last_pct,
)
from app.market_pulse.nifty_index_constituents import (
    constituent_key_for_index as _constituent_key_for_index,
    get_index_constituent_symbols,
)
from app.market_pulse.nse_index_yfinance import stock_symbol_to_yf
from app.market_pulse.ticker_utils import INDEX_OPTIONS

logger = logging.getLogger(__name__)

_W52_DEFAULT_TOLERANCE = 1.5


def _warm_nse_session(session: requests.Session, referer_path: str = "/market-data/live-equity-market") -> None:
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"https://www.nseindia.com{referer_path}",
    })
    session.get(f"https://www.nseindia.com{referer_path}", timeout=15)


def _parse_nse_float(item: dict, *keys: str) -> float | None:
    for key in keys:
        val = item.get(key)
        if val is None or val == "" or val == "-":
            continue
        try:
            return float(str(val).replace(",", "").strip())
        except (TypeError, ValueError):
            continue
    return None


def fetch_nse_index_constituent_quotes(index_name: str) -> list[dict]:
    """Fetch live quote + 52-week high/low for each EQ constituent in an NSE index."""
    from app.market_pulse.nse_index_yfinance import normalize_index_name

    for candidate in dict.fromkeys([index_name, normalize_index_name(index_name)]):
        rows = _fetch_nse_index_constituent_quotes_once(candidate)
        if rows:
            return rows
    return []


def _fetch_nse_index_constituent_quotes_once(index_name: str) -> list[dict]:
    try:
        session = requests.Session()
        _warm_nse_session(session)
        url = f"https://www.nseindia.com/api/equity-stockIndices?index={quote(index_name)}"
        resp = session.get(url, timeout=20)
        if resp.status_code != 200:
            return []
        rows: list[dict] = []
        for item in resp.json().get("data", []):
            symbol = (item.get("symbol") or "").strip()
            if not symbol or symbol.upper() == index_name.upper():
                continue
            meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
            last = _parse_nse_float(item, "lastPrice", "ltp", "last")
            year_high = _parse_nse_float(
                item, "yearHigh", "52WeekHigh", "high52", "weekHighLow",
            )
            year_low = _parse_nse_float(
                item, "yearLow", "52WeekLow", "low52",
            )
            if year_high is None and meta:
                year_high = _parse_nse_float(meta, "yearHigh", "52WeekHigh", "high52")
            if year_low is None and meta:
                year_low = _parse_nse_float(meta, "yearLow", "52WeekLow", "low52")
            if last is None:
                continue
            pct_chg = _parse_nse_float(item, "pChange", "percentChange", "change")
            rows.append({
                "symbol": symbol,
                "last": last,
                "year_high": year_high,
                "year_low": year_low,
                "pct_chg": pct_chg,
            })
        return rows
    except Exception as e:
        logger.error(f"52W constituent quotes error ({index_name}): {e}")
        return []


def _yf_extremes_from_df(df: pd.DataFrame) -> dict[str, float] | None:
    if df is None or df.empty:
        return None
    if not {"high", "low", "close"}.issubset(df.columns):
        return None
    hi = pd.to_numeric(df["high"], errors="coerce").dropna()
    lo = pd.to_numeric(df["low"], errors="coerce").dropna()
    closes = pd.to_numeric(df["close"], errors="coerce").dropna()
    if hi.empty or lo.empty or closes.empty:
        return None
    return {
        "last": float(closes.iloc[-1]),
        "year_high": float(hi.max()),
        "year_low": float(lo.min()),
    }


def _fetch_52w_extremes_yfinance(symbols: tuple[str, ...]) -> dict[str, dict]:
    """1-year daily high/low/last via Yahoo Finance (.NS tickers)."""
    if not symbols:
        return {}
    out: dict[str, dict] = {}
    unique = list(dict.fromkeys(symbols))
    chunk_size = 40
    for start in range(0, len(unique), chunk_size):
        chunk = unique[start:start + chunk_size]
        tickers = [stock_symbol_to_yf(s) for s in chunk]
        try:
            raw = yf.download(
                tickers,
                period="1y",
                interval="1d",
                group_by="ticker",
                progress=False,
                auto_adjust=True,
                threads=True,
            )
        except Exception as e:
            logger.warning(f"52W yfinance batch error: {e}")
            continue
        if raw is None or raw.empty:
            continue
        for sym in chunk:
            tkr = stock_symbol_to_yf(sym)
            df = _yf_ohlcv_from_download(raw, tkr)
            stats = _yf_extremes_from_df(df)
            if stats:
                out[sym] = {
                    "symbol": sym,
                    "last": stats["last"],
                    "year_high": stats["year_high"],
                    "year_low": stats["year_low"],
                    "pct_chg": None,
                    "source": "yfinance",
                }

    for sym in unique:
        if sym in out:
            continue
        try:
            raw = yf.download(
                stock_symbol_to_yf(sym),
                period="1y",
                interval="1d",
                progress=False,
                auto_adjust=True,
            )
            df = _yf_ohlcv_from_download(raw, stock_symbol_to_yf(sym))
            stats = _yf_extremes_from_df(df)
            if stats:
                out[sym] = {
                    "symbol": sym,
                    "last": stats["last"],
                    "year_high": stats["year_high"],
                    "year_low": stats["year_low"],
                    "pct_chg": None,
                    "source": "yfinance",
                }
        except Exception:
            continue
    return out


def fetch_ath_atl_for_symbols(symbols: tuple[str, ...]) -> dict[str, dict]:
    """All-time high/low from yfinance max daily history."""
    if not symbols:
        return {}
    out: dict[str, dict] = {}
    unique = list(dict.fromkeys(symbols))
    chunk_size = 40
    for start in range(0, len(unique), chunk_size):
        chunk = unique[start:start + chunk_size]
        tickers = [stock_symbol_to_yf(s) for s in chunk]
        try:
            raw = yf.download(
                tickers,
                period="max",
                interval="1d",
                group_by="ticker",
                progress=False,
                auto_adjust=True,
                threads=True,
            )
        except Exception as e:
            logger.warning(f"ATH/ATL batch error: {e}")
            continue
        if raw is None or raw.empty:
            continue
        for sym in chunk:
            tkr = stock_symbol_to_yf(sym)
            df = _yf_ohlcv_from_download(raw, tkr)
            if df is None or df.empty:
                continue
            hi = pd.to_numeric(df["high"], errors="coerce").dropna()
            lo = pd.to_numeric(df["low"], errors="coerce").dropna()
            if hi.empty or lo.empty:
                continue
            out[sym] = {"ath": float(hi.max()), "atl": float(lo.min())}

    for sym in unique:
        if sym in out:
            continue
        try:
            raw = yf.download(
                stock_symbol_to_yf(sym),
                period="max",
                interval="1d",
                progress=False,
                auto_adjust=True,
            )
            df = _yf_ohlcv_from_download(raw, stock_symbol_to_yf(sym))
            if df is None or df.empty:
                continue
            hi = pd.to_numeric(df["high"], errors="coerce").dropna()
            lo = pd.to_numeric(df["low"], errors="coerce").dropna()
            if not hi.empty and not lo.empty:
                out[sym] = {"ath": float(hi.max()), "atl": float(lo.min())}
        except Exception:
            continue
    return out


def _merge_yfinance_52w(stocks: list[dict]) -> list[dict]:
    """Fill missing 52W high/low from yfinance when NSE omits them."""
    need = [
        s["symbol"] for s in stocks
        if not s.get("year_high") or not s.get("year_low")
    ]
    if not need:
        return stocks
    yf_map = _fetch_52w_extremes_yfinance(tuple(need))
    merged: list[dict] = []
    for s in stocks:
        row = dict(s)
        yf = yf_map.get(row["symbol"])
        if yf:
            row.setdefault("year_high", yf.get("year_high"))
            row.setdefault("year_low", yf.get("year_low"))
            if row.get("last") is None:
                row["last"] = yf.get("last")
        merged.append(row)
    return merged


def resolve_index_constituents(index_name: str) -> list[dict]:
    """NSE live quotes first; yfinance 52W fill; INDEX_OPTIONS fallback."""
    from app.market_pulse.nse_index_yfinance import normalize_index_name

    for candidate in dict.fromkeys([index_name, normalize_index_name(index_name)]):
        stocks = fetch_nse_index_constituent_quotes(candidate)
        if stocks:
            return _merge_yfinance_52w(stocks)

    key = _constituent_key_for_index(index_name)
    if key:
        symbols = INDEX_OPTIONS.get(key) or []
        if symbols:
            yf_stocks = _fetch_52w_extremes_yfinance(tuple(symbols))
            resolved = [yf_stocks[s] for s in symbols if s in yf_stocks]
            if resolved:
                return resolved

    static_symbols = get_index_constituent_symbols(index_name)
    if static_symbols:
        yf_stocks = _fetch_52w_extremes_yfinance(tuple(static_symbols))
        resolved = [yf_stocks[s] for s in static_symbols if s in yf_stocks]
        if resolved:
            return resolved

    from app.market_pulse.news_scanner import _fetch_nse_index_constituent_symbols

    for candidate in dict.fromkeys([index_name, normalize_index_name(index_name)]):
        symbols = _fetch_nse_index_constituent_symbols(candidate)
        if symbols:
            yf_stocks = _fetch_52w_extremes_yfinance(tuple(symbols))
            resolved = [yf_stocks[s] for s in symbols if s in yf_stocks]
            if resolved:
                return resolved
    return []


def _enrich_with_extremes(
    stocks: list[dict],
    tolerance_pct: float,
    ath_atl: dict[str, dict],
) -> dict:
    """Classify 52W high/low hits and attach ATH/ATL distance metrics."""
    at_high: list[dict] = []
    at_low: list[dict] = []
    tol = max(0.1, float(tolerance_pct))

    for s in stocks:
        last = s["last"]
        yh = s.get("year_high")
        yl = s.get("year_low")
        ext = ath_atl.get(s["symbol"]) or {}
        ath = ext.get("ath")
        atl = ext.get("atl")
        pct_below_ath = (ath - last) / ath * 100 if ath and ath > 0 else None
        pct_above_atl = (last - atl) / atl * 100 if atl and atl > 0 else None

        base = {
            "symbol": s["symbol"],
            "last": last,
            "year_high": yh,
            "year_low": yl,
            "pct_chg": s.get("pct_chg"),
            "pct_below_52w_high": None,
            "pct_above_52w_low": None,
            "pct_below_ath": pct_below_ath,
            "pct_above_atl": pct_above_atl,
            "ath": ath,
            "atl": atl,
        }

        if yh and yh > 0:
            pct_below_52h = (yh - last) / yh * 100
            if pct_below_52h <= tol:
                row_h = dict(base)
                row_h["pct_below_52w_high"] = pct_below_52h
                at_high.append(row_h)

        if yl and yl > 0:
            pct_above_52l = (last - yl) / yl * 100
            if pct_above_52l <= tol:
                row_l = dict(base)
                row_l["pct_above_52w_low"] = pct_above_52l
                at_low.append(row_l)

    at_high.sort(key=lambda x: x.get("pct_below_52w_high") or 999)
    at_low.sort(key=lambda x: x.get("pct_above_52w_low") or 999)
    return {
        "constituent_count": len(stocks),
        "at_52w_high": at_high,
        "at_52w_low": at_low,
    }


def scan_index_52w_extremes(
    index_name: str,
    tolerance_pct: float = _W52_DEFAULT_TOLERANCE,
    include_ath_atl: bool = True,
) -> dict:
    stocks = resolve_index_constituents(index_name)
    if not stocks:
        return {
            "index": index_name,
            "constituent_count": 0,
            "at_52w_high": [],
            "at_52w_low": [],
            "error": "No constituent quotes (NSE + yfinance fallback failed)",
        }

    symbols_for_ath: set[str] = set()
    pre = _enrich_with_extremes(stocks, tolerance_pct, {})
    for r in pre["at_52w_high"] + pre["at_52w_low"]:
        symbols_for_ath.add(r["symbol"])

    ath_atl: dict[str, dict] = {}
    if include_ath_atl and symbols_for_ath:
        ath_atl = fetch_ath_atl_for_symbols(tuple(sorted(symbols_for_ath)))

    return {
        "index": index_name,
        **_enrich_with_extremes(stocks, tolerance_pct, ath_atl),
    }


def _get_index_names_by_group(breadth_data: dict | None) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {g: [] for g in _NIFTY_BREADTH_GROUP_ORDER}
    if not breadth_data:
        return groups
    raw_groups = breadth_data.get("groups") or {}
    monthly_groups = breadth_data.get("monthly_groups") or {}
    for group in _NIFTY_BREADTH_GROUP_ORDER:
        names: list[str] = []
        for bucket in (raw_groups.get(group), monthly_groups.get(group)):
            if bucket:
                for n in bucket:
                    if n not in names:
                        names.append(n)
        groups[group] = sorted(names)
    return groups


def _fmt_pct(val: Optional[float], suffix: str = "%") -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "N/A"
    return f"{val:+.2f}{suffix}"


def _stock_rows_to_df(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([{
        "Stock": r["symbol"],
        "LTP · Chg %": fmt_last_pct(r.get("last"), r.get("pct_chg")),
        "52W High": f"{r['year_high']:,.2f}" if r.get("year_high") else "N/A",
        "% below 52W H": _fmt_pct(r.get("pct_below_52w_high")),
        "52W Low": f"{r['year_low']:,.2f}" if r.get("year_low") else "N/A",
        "% above 52W L": _fmt_pct(r.get("pct_above_52w_low")),
        "% below ATH": _fmt_pct(r.get("pct_below_ath")),
        "% above ATL": _fmt_pct(r.get("pct_above_atl")),
    } for r in rows])


def _render_index_52w_block(
    result: dict,
    tolerance_pct: float,
    sr: dict | None = None,
) -> None:
    index_name = result["index"]
    if result.get("error"):
        st.warning(result["error"])
        return
    n = result.get("constituent_count", 0)
    highs = result.get("at_52w_high") or []
    lows = result.get("at_52w_low") or []
    sr = sr or {}
    from app.market_pulse.news_scanner import _fmt_sr_level

    st.caption(
        f"**{n}** constituents · tolerance **±{tolerance_pct:.1f}%** of 52W high/low · "
        f"**{len(highs)}** at/near 52W high · **{len(lows)}** at/near 52W low · "
        f"S1 {_fmt_sr_level(sr.get('s1'))} · S2 {_fmt_sr_level(sr.get('s2'))} · "
        f"R1 {_fmt_sr_level(sr.get('r1'))} · R2 {_fmt_sr_level(sr.get('r2'))}"
    )
    if not highs and not lows:
        st.info("No stocks within tolerance of 52-week high or low right now.")
        return

    col_h, col_l = st.columns(2)
    with col_h:
        st.markdown(f"**🟢 At / near 52-week HIGH ({len(highs)})**")
        if highs:
            st.dataframe(_stock_rows_to_df(highs), hide_index=True, width='stretch')
            st.caption(
                "**% below ATH** = how far price is below the all-time high. "
                "**% above ATL** = how far price is above the all-time low."
            )
        else:
            st.caption("None in this band.")
    with col_l:
        st.markdown(f"**🔴 At / near 52-week LOW ({len(lows)})**")
        if lows:
            st.dataframe(_stock_rows_to_df(lows), hide_index=True, width='stretch')
        else:
            st.caption("None in this band.")


def _render_52w_scan_summary(all_results: dict[str, dict]) -> None:
    total_h = sum(len(r.get("at_52w_high") or []) for r in all_results.values())
    total_l = sum(len(r.get("at_52w_low") or []) for r in all_results.values())
    indices_with_hits = sum(
        1 for r in all_results.values()
        if (r.get("at_52w_high") or r.get("at_52w_low"))
    )
    st.markdown(
        f"**Scan summary:** {len(all_results)} indices scanned · "
        f"**{indices_with_hits}** with 52W hits · "
        f"**{total_h}** stock slots at 52W high · **{total_l}** at 52W low "
        f"(a stock may appear in both if the range is tight)."
    )


def _stock_hit_rows_with_index(rows: list[dict], index_name: str) -> list[dict]:
    out = []
    for r in rows:
        out.append({
            "Index": index_name,
            "Stock": r["symbol"],
            "LTP · Chg %": fmt_last_pct(r.get("last"), r.get("pct_chg")),
            "52W High": f"{r['year_high']:,.2f}" if r.get("year_high") else "N/A",
            "% below 52W H": _fmt_pct(r.get("pct_below_52w_high")),
            "52W Low": f"{r['year_low']:,.2f}" if r.get("year_low") else "N/A",
            "% above 52W L": _fmt_pct(r.get("pct_above_52w_low")),
            "% below ATH": _fmt_pct(r.get("pct_below_ath")),
            "% above ATL": _fmt_pct(r.get("pct_above_atl")),
        })
    return out


def _render_52w_consolidated_hits(results: dict[str, dict]) -> None:
    """All matching stocks in one place — shown immediately after scan."""
    all_high_rows: list[dict] = []
    all_low_rows: list[dict] = []
    for idx_name, r in results.items():
        all_high_rows.extend(_stock_hit_rows_with_index(r.get("at_52w_high") or [], idx_name))
        all_low_rows.extend(_stock_hit_rows_with_index(r.get("at_52w_low") or [], idx_name))

    if not all_high_rows and not all_low_rows:
        return

    st.markdown("### 📋 Stocks at / near 52-week extremes")
    col_h, col_l = st.columns(2)
    with col_h:
        st.markdown(f"**🟢 At / near 52-week HIGH ({len(all_high_rows)})**")
        if all_high_rows:
            st.dataframe(
                pd.DataFrame(all_high_rows),
                hide_index=True,
                width='stretch',
            )
        else:
            st.caption("None in this band.")
    with col_l:
        st.markdown(f"**🔴 At / near 52-week LOW ({len(all_low_rows)})**")
        if all_low_rows:
            st.dataframe(
                pd.DataFrame(all_low_rows),
                hide_index=True,
                width='stretch',
            )
        else:
            st.caption("None in this band.")
    st.caption(
        "**% below ATH** / **% above ATL** use long Yahoo Finance history when enabled. "
        "Expand an index below for per-index detail."
    )


def render_week52_high_low_tab() -> None:
    """Market Pulse — 52-week high/low by Nifty index."""
    _render_news_scanner_styles()
    st.markdown(
        '<div class="section-header-ns">📊 52-Week High & Low — Index Constituents</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "For each Nifty index, lists constituents trading at or near their **52-week high** or "
        "**52-week low**, plus **% below all-time high (ATH)** and **% above all-time low (ATL)** "
        "from long daily history (Yahoo Finance)."
    )

    c1, c2, c3 = st.columns([2, 2, 2])
    with c1:
        tolerance = st.slider(
            "Near 52W band (%)",
            0.5, 5.0, _W52_DEFAULT_TOLERANCE, 0.5,
            key="w52_tolerance",
            help="Stocks within this % of 52-week high/low are included.",
        )
    with c2:
        include_ath_atl = st.checkbox(
            "Include ATH / ATL distances",
            value=True,
            key="w52_include_ath_atl",
            help="Fetches max history via yfinance for matched stocks (slower on first load).",
        )
    with c3:
        group_options = [
            _NIFTY_BREADTH_GROUP_LABELS.get(g, g.title())
            for g in _NIFTY_BREADTH_GROUP_ORDER
        ]
        selected_labels = st.multiselect(
            "Index groups",
            group_options,
            default=["F&O / Derivatives", "Broad Market", "Sectoral"],
            key="w52_groups",
        )

    load_btn = st.button("🔄 Load 52-Week High / Low Scan", key="w52_load_btn", type="primary")

    if load_btn:
        clear_week52_caches()
        breadth = fetch_nse_market_breadth()
        by_group = _get_index_names_by_group(breadth)
        label_to_key = {
            _NIFTY_BREADTH_GROUP_LABELS.get(g, g.title()): g
            for g in _NIFTY_BREADTH_GROUP_ORDER
        }
        indices_to_scan: list[str] = []
        for lbl in selected_labels:
            gkey = label_to_key.get(lbl, lbl)
            for name in by_group.get(gkey, []):
                if name not in indices_to_scan:
                    indices_to_scan.append(name)

        if not indices_to_scan:
            st.warning("No indices selected. Choose at least one index group.")
        else:
            results: dict[str, dict] = {}
            progress = st.progress(0, text="Starting 52-week scan...")
            for i, idx_name in enumerate(indices_to_scan):
                progress.progress(
                    (i + 1) / len(indices_to_scan),
                    text=f"Scanning {idx_name} ({i + 1}/{len(indices_to_scan)})...",
                )
                results[idx_name] = scan_index_52w_extremes(
                    idx_name,
                    tolerance_pct=tolerance,
                    include_ath_atl=include_ath_atl,
                )
                time.sleep(0.12)
            progress.empty()
            hits = sum(
                1 for r in results.values()
                if (r.get("at_52w_high") or r.get("at_52w_low"))
            )
            display_groups: list[dict] = []
            for lbl in selected_labels:
                gkey = label_to_key.get(lbl, lbl)
                group_names = [
                    n for n in by_group.get(gkey, [])
                    if n in results
                ]
                if group_names:
                    display_groups.append({
                        "group": gkey,
                        "label": lbl,
                        "names": group_names,
                    })
            st.session_state["w52_scan_results"] = results
            st.session_state["w52_scan_tolerance"] = tolerance
            st.session_state["w52_scan_groups"] = selected_labels
            st.session_state["w52_display_groups"] = display_groups
            st.rerun()

    results = st.session_state.get("w52_scan_results")
    if not results:
        st.info(
            "Click **🔄 Load 52-Week High / Low Scan** to scan selected Nifty index groups. "
            "Data is not fetched automatically on page load."
        )
        return

    total_hits = sum(
        1 for r in results.values()
        if (r.get("at_52w_high") or r.get("at_52w_low"))
    )
    if total_hits == 0:
        st.info(
            f"No constituents within **±{tolerance:.1f}%** of 52-week high/low right now. "
            "Try widening **Near 52W band (%)** and click **Load** again, or expand indices below "
            "to see per-index constituent counts."
        )

    if st.session_state.get("w52_scan_tolerance") != tolerance:
        st.warning("Tolerance changed — click **Load** again to refresh.")
    if st.session_state.get("w52_scan_groups") != selected_labels:
        st.warning("Index groups changed — click **Load** again to refresh.")

    _render_52w_scan_summary(results)
    _render_52w_consolidated_hits(results)

    display_groups: list[dict] = st.session_state.get("w52_display_groups") or []
    if not display_groups:
        label_to_key = {
            _NIFTY_BREADTH_GROUP_LABELS.get(g, g.title()): g
            for g in _NIFTY_BREADTH_GROUP_ORDER
        }
        by_group = _get_index_names_by_group(fetch_nse_market_breadth())
        for lbl in selected_labels:
            gkey = label_to_key.get(lbl, lbl)
            group_names = [n for n in by_group.get(gkey, []) if n in results]
            if group_names:
                display_groups.append({
                    "group": gkey,
                    "label": lbl,
                    "names": group_names,
                })

    hit_indices = [
        n for n, r in results.items()
        if (r.get("at_52w_high") or r.get("at_52w_low"))
    ]
    sr_map: dict[str, dict] = {}
    if hit_indices:
        from app.market_pulse.news_scanner import fetch_index_sr_levels
        with st.spinner(f"Loading S/R for {len(hit_indices)} indices with hits…"):
            sr_map = fetch_index_sr_levels(tuple(hit_indices))

    st.markdown("### 📂 By index")
    for block in display_groups:
        label = block["label"]
        names = block.get("names") or []
        if not names:
            continue
        hits = sum(
            1 for n in names
            if (results.get(n, {}).get("at_52w_high") or results.get(n, {}).get("at_52w_low"))
        )
        with st.expander(
            f"{label} — 52W highs & lows ({hits}/{len(names)} indices with hits)",
            expanded=(hits > 0),
        ):
            for name in names:
                res = results.get(name)
                if not res:
                    continue
                h_n = len(res.get("at_52w_high") or [])
                l_n = len(res.get("at_52w_low") or [])
                n_const = res.get("constituent_count", 0)
                err = res.get("error")
                icon = "🟢" if h_n else "⚪"
                if l_n:
                    icon += "🔴"
                title = (
                    f"{icon} **{name}** — {h_n} at 52W high · {l_n} at 52W low · "
                    f"{n_const} stocks"
                )
                if err:
                    title = f"⚠️ **{name}** — {err}"
                with st.expander(title, expanded=(h_n > 0 or l_n > 0)):
                    _render_index_52w_block(res, tolerance, sr_map.get(name))

    if results:
        from app.market_pulse.ask_ai_context import snapshot_section_for_ask_ai
        snapshot_section_for_ask_ai("week52")


def clear_week52_caches() -> None:
    fetch_nse_index_constituent_quotes.clear()
    fetch_ath_atl_for_symbols.clear()
    _fetch_52w_extremes_yfinance.clear()
