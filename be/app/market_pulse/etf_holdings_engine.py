"""
etf_holdings_engine.py
----------------------
ETF analogue of mutual_fund_holdings_engine.

India  — StockEdge public API, equity schemes filtered to ETFs (month-end holdings).
US     — INDMoney US ETF catalog + per-ETF "Companies" composition
         (https://www.indmoney.com/us-stocks/etfs[/<ticker>]), with local snapshots
         for date-range trends (INDMoney exposes the latest cut only).
Crypto — SEC Form NPORT-P via edgartools (series-filtered historical periods).
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable

import pandas as pd
import requests

from app.core.config import BASE_DIR
from app.market_pulse.holdings_trend_views import attach_sector_views
from app.market_pulse.mutual_fund_holdings_engine import (
    HoldingsChangeConfig,
    analyze_holdings_change,
    fetch_amc_list,
    fetch_schemes_for_amc,
)

logger = logging.getLogger(__name__)

_TREND_FLAT_PCT = 0.05
_EDGAR_IDENTITY = "TrueBacktester truebacktester@local.dev"
_SNAPSHOT_DB = str(BASE_DIR / "data" / "etf_holdings_snapshots.db")

_INDMONEY_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json",
    "Accept-Language": "en-US,en;q=0.9",
}
_INDMONEY_ENTITY_URL = (
    "https://apixt-us.indmoney.com/us-stock-broker/us/catalog/get-entity-details"
    "?response_format=web&catalog-required=true&id={ticker}&currency=USD"
)
_INDMONEY_ETFS_URL = "https://www.indmoney.com/us-stocks/etfs"
_TIMEOUT = 45

# Crypto still uses curated issuers + SEC NPORT (INDMoney coverage is US-focused).
CRYPTO_ETF_ISSUERS: dict[str, list[dict[str, str]]] = {
    "Amplify": [
        {"symbol": "BLOK", "name": "Amplify Blockchain Technology ETF"},
    ],
    "Bitwise": [
        {"symbol": "BITQ", "name": "Bitwise Crypto Industry Innovators ETF"},
    ],
    "VanEck": [
        {"symbol": "DAPP", "name": "VanEck Digital Transformation ETF"},
    ],
    "Global X": [
        {"symbol": "BKCH", "name": "Global X Blockchain ETF"},
        {"symbol": "BITS", "name": "Global X Blockchain & Bitcoin Strategy ETF"},
    ],
    "Valkyrie / CoinShares": [
        {"symbol": "WGMI", "name": "CoinShares Valkyrie Bitcoin Miners ETF"},
    ],
    "First Trust": [
        {"symbol": "CRPT", "name": "First Trust SkyBridge Crypto Industry ETF"},
    ],
    "ARK (crypto-adjacent)": [
        {"symbol": "ARKK", "name": "ARK Innovation ETF"},
        {"symbol": "ARKW", "name": "ARK Next Generation Internet ETF"},
    ],
}

# Back-compat aliases
US_ETF_ISSUERS: dict[str, list[dict[str, str]]] = {}  # filled live from INDMoney
US_ETF_CATALOG = US_ETF_ISSUERS
CRYPTO_ETF_CATALOG = CRYPTO_ETF_ISSUERS

_ETF_NAME_RE = re.compile(r"\b(etf|bees)\b", re.I)
_edgar_ready = False


def _ensure_edgar() -> None:
    global _edgar_ready
    if _edgar_ready:
        return
    from edgar import set_identity

    set_identity(_EDGAR_IDENTITY)
    _edgar_ready = True


def is_etf_scheme(scheme: dict) -> bool:
    """True when a StockEdge equity scheme looks like an ETF."""
    name = str(scheme.get("Name") or "")
    desc = str(scheme.get("Description") or "")
    if "etf" in desc.lower():
        return True
    return bool(_ETF_NAME_RE.search(name))


def fetch_etf_schemes_for_amc(amc_id: int) -> list[dict]:
    """Equity schemes for one AMC, filtered to ETFs."""
    return [s for s in fetch_schemes_for_amc(amc_id) if is_etf_scheme(s)]


# ---------------------------------------------------------------------------
# INDMoney US ETFs
# ---------------------------------------------------------------------------

def _indmoney_next_page_props(url: str) -> dict:
    resp = requests.get(url, headers=_INDMONEY_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        resp.text,
        flags=re.S,
    )
    if not m:
        raise RuntimeError(f"INDMoney page has no __NEXT_DATA__: {url}")
    return json.loads(m.group(1))["props"]["pageProps"]


def _normalize_etf_row(item: dict, *, category: str) -> dict | None:
    ticker = str(item.get("ticker") or item.get("ind_key") or "").strip().upper()
    if not ticker:
        return None
    name = str(item.get("company_name") or item.get("name") or ticker)
    return {
        "ID": ticker,
        "Name": name,
        "Description": category,
        "NAV": item.get("price"),
        "Return": item.get("return_3yrs"),
        "AUM": item.get("aum"),
        "symbol": ticker,
        "relative_path": item.get("relative_path") or f"etfs/{ticker.lower()}",
    }


def fetch_indmoney_etf_categories() -> list[dict]:
    """Category list from https://www.indmoney.com/us-stocks/etfs (AMC-style groups)."""
    pp = _indmoney_next_page_props(_INDMONEY_ETFS_URL)
    out: list[dict] = []
    # Featured / all list on the landing page
    featured = ((pp.get("stocksData") or {}).get("stock_list") or [])
    out.append({
        "ID": 0,
        "Name": "All ETFs (featured)",
        "SchemeCount": len(featured),
        "path": "/us-stocks/etfs",
    })
    navs = (pp.get("categoriesData") or {}).get("navigations") or []
    i = 1
    for block in navs:
        for sub in block.get("sub_headers") or []:
            name = str(sub.get("header") or "").strip()
            path = str(sub.get("header_link") or "").strip()
            if not name or not path:
                continue
            out.append({"ID": i, "Name": name, "SchemeCount": None, "path": path})
            i += 1
    return out


def fetch_indmoney_etfs_for_category(path: str) -> list[dict]:
    """ETF rows for one INDMoney category path (or the main /us-stocks/etfs page)."""
    path = path if path.startswith("/") else f"/{path}"
    url = "https://www.indmoney.com" + path
    try:
        pp = _indmoney_next_page_props(url)
    except Exception as exc:
        logger.warning("INDMoney category fetch failed %s: %s", path, exc)
        return []
    stock_list = ((pp.get("stocksData") or {}).get("stock_list") or [])
    # Derive a short category label from the path
    cat = path.rstrip("/").split("/")[-1].replace("-", " ").title()
    if path.rstrip("/") == "/us-stocks/etfs":
        cat = "All ETFs (featured)"
    out: list[dict] = []
    seen: set[str] = set()
    for item in stock_list:
        row = _normalize_etf_row(item, category=cat)
        if not row or row["ID"] in seen:
            continue
        seen.add(row["ID"])
        out.append(row)
    return out


def fetch_indmoney_etf_holdings(ticker: str) -> list[dict]:
    """Companies / Holding % for one US ETF from INDMoney entity catalog API.

    Same data shown under "Companies in <ETF name>" on
    https://www.indmoney.com/us-stocks/etfs/<ticker>.
    """
    ticker = ticker.strip().upper()
    url = _INDMONEY_ENTITY_URL.format(ticker=ticker)
    try:
        resp = requests.get(
            url,
            headers={**_INDMONEY_HEADERS, "Accept": "application/json"},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("INDMoney holdings fetch failed for %s: %s", ticker, exc)
        return []

    details = ((data.get("catalog") or {}).get("etf_details") or {})
    composition = details.get("stock_composition") or []
    rows: list[dict] = []
    for item in composition:
        stock = str(item.get("ind_key") or "").strip().upper()
        name = str(item.get("stock_name") or stock)
        if not stock:
            continue
        pct = item.get("percentage_composition")
        if pct is None:
            continue
        try:
            pct_f = float(pct)
        except (TypeError, ValueError):
            continue
        sector = str(item.get("sector") or "").strip() or "—"
        rows.append({
            "stock": stock,
            "stock_name": name,
            "holding_pct": round(pct_f, 4),
            "sector": sector,
            "mcap_category": "—",
        })
    return rows


def list_issuers(market: str) -> list[dict[str, Any]]:
    """AMC-style issuer/category list for US (INDMoney) or crypto (curated)."""
    if market == "crypto":
        out = []
        for i, (name, etfs) in enumerate(CRYPTO_ETF_ISSUERS.items()):
            out.append({"ID": i, "Name": name, "SchemeCount": len(etfs), "etfs": etfs, "path": None})
        return out
    # US — live INDMoney categories
    cats = fetch_indmoney_etf_categories()
    # Fill SchemeCount lazily left as-is for featured; others unknown until load
    return cats


def fetch_schemes_for_issuer(market: str, issuer_name: str) -> list[dict]:
    """ETF 'schemes' under one issuer/category."""
    if market == "crypto":
        etfs = CRYPTO_ETF_ISSUERS.get(issuer_name) or []
        return [
            {
                "ID": e["symbol"],
                "Name": e["name"],
                "Description": issuer_name,
                "NAV": None,
                "Return": None,
                "AUM": None,
                "symbol": e["symbol"],
            }
            for e in etfs
        ]

    cats = fetch_indmoney_etf_categories()
    path = next((c["path"] for c in cats if c["Name"] == issuer_name), None)
    if not path:
        return []
    return fetch_indmoney_etfs_for_category(path)


def list_catalog_etfs(market: str) -> list[dict[str, str]]:
    """Flat catalog helper (crypto curated / US featured page)."""
    if market == "crypto":
        out: list[dict[str, str]] = []
        for issuer, items in CRYPTO_ETF_ISSUERS.items():
            for item in items:
                out.append({**item, "category": issuer, "issuer": issuer})
        return out
    rows = fetch_indmoney_etfs_for_category("/us-stocks/etfs")
    return [
        {"symbol": r["ID"], "name": r["Name"], "category": r["Description"], "issuer": r["Description"]}
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Local snapshots (INDMoney is latest-cut only)
# ---------------------------------------------------------------------------

def _db_connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_SNAPSHOT_DB), exist_ok=True)
    conn = sqlite3.connect(_SNAPSHOT_DB)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS etf_holding_snapshots (
            market TEXT NOT NULL,
            symbol TEXT NOT NULL,
            as_of TEXT NOT NULL,
            stock TEXT NOT NULL,
            stock_name TEXT,
            sector TEXT,
            holding_pct REAL NOT NULL,
            PRIMARY KEY (market, symbol, as_of, stock)
        )
        """
    )
    # Migrate older snapshot DBs that predate the sector column.
    cols = {row[1] for row in conn.execute("PRAGMA table_info(etf_holding_snapshots)").fetchall()}
    if "sector" not in cols:
        conn.execute("ALTER TABLE etf_holding_snapshots ADD COLUMN sector TEXT")
    conn.commit()
    return conn


def save_holdings_snapshot(
    market: str,
    symbol: str,
    holdings: list[dict],
    as_of: date | None = None,
) -> None:
    if not holdings:
        return
    as_of = as_of or date.today()
    as_of_s = as_of.isoformat()
    with _db_connect() as conn:
        for h in holdings:
            conn.execute(
                """
                INSERT OR REPLACE INTO etf_holding_snapshots
                    (market, symbol, as_of, stock, stock_name, sector, holding_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    market,
                    symbol,
                    as_of_s,
                    h["stock"],
                    h.get("stock_name") or h["stock"],
                    h.get("sector") or "—",
                    float(h["holding_pct"]),
                ),
            )
        conn.commit()


def load_snapshots(
    market: str,
    symbols: list[str],
    from_date: date,
    to_date: date,
) -> pd.DataFrame:
    if not symbols:
        return pd.DataFrame()
    if from_date > to_date:
        from_date, to_date = to_date, from_date
    placeholders = ",".join("?" * len(symbols))
    sql = f"""
        SELECT market, symbol, as_of, stock, stock_name, sector, holding_pct
        FROM etf_holding_snapshots
        WHERE market = ?
          AND symbol IN ({placeholders})
          AND as_of >= ? AND as_of <= ?
        ORDER BY as_of, symbol, stock
    """
    params: list[Any] = [market, *symbols, from_date.isoformat(), to_date.isoformat()]
    with _db_connect() as conn:
        df = pd.read_sql_query(sql, conn, params=params)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["as_of"]).dt.date
    return df


def lookup_us_equity_sector(ticker: str) -> str:
    """Yahoo sector for a US ticker (INDMoney composition sector is often blank)."""
    t = (ticker or "").strip().upper()
    if not t or len(t) > 12 or " " in t:
        return "—"
    try:
        import yfinance as yf

        info = yf.Ticker(t).info or {}
        sector = info.get("sector") or info.get("industry") or "—"
        return str(sector) if sector else "—"
    except Exception:
        return "—"


def enrich_dataframe_sectors(df: pd.DataFrame, *, max_lookups: int = 400) -> pd.DataFrame:
    """Fill blank/unknown sector from Yahoo for ticker-like stock keys."""
    if df is None or df.empty or "stock" not in df.columns:
        return df
    out = df.copy()
    if "sector" not in out.columns:
        out["sector"] = "—"
    need = out["sector"].isna() | out["sector"].astype(str).isin(["—", "", "nan", "None"])
    tickers = out.loc[need, "stock"].astype(str).str.strip().str.upper().unique().tolist()
    tickers = [t for t in tickers if t and " " not in t and len(t) <= 12][:max_lookups]
    if not tickers:
        return out
    mapping = {t: lookup_us_equity_sector(t) for t in tickers}
    out.loc[need, "sector"] = (
        out.loc[need, "stock"].astype(str).str.strip().str.upper().map(mapping).fillna("—")
    )
    out["sector"] = out["sector"].fillna("—")
    return out


# ---------------------------------------------------------------------------
# Crypto — SEC NPORT (unchanged path)
# ---------------------------------------------------------------------------

def _stock_key(ticker: Any, name: Any) -> str | None:
    if ticker is not None and not (isinstance(ticker, float) and pd.isna(ticker)):
        t = str(ticker).strip().upper()
        if t and t not in ("NAN", "NONE", "NAT", "N/A", "-"):
            return t
    if name is not None and not (isinstance(name, float) and pd.isna(name)):
        n = str(name).strip()
        if n and n.lower() not in ("nan", "none"):
            return n
    return None


def _holdings_from_report(report) -> list[dict]:
    try:
        df = report.investment_data()
    except Exception as exc:
        logger.debug("investment_data failed: %s", exc)
        return []
    if df is None or df.empty:
        return []
    if "asset_category" in df.columns:
        df = df[df["asset_category"].astype(str).str.upper() == "EC"]
    rows: list[dict] = []
    for _, row in df.iterrows():
        stock = _stock_key(row.get("ticker"), row.get("name"))
        if not stock:
            continue
        pct = row.get("pct_value")
        if pct is None or (isinstance(pct, float) and pd.isna(pct)):
            continue
        try:
            pct_f = float(pct)
        except (TypeError, ValueError):
            continue
        name = str(row.get("name") or stock)
        rows.append({
            "stock": stock,
            "stock_name": name,
            "holding_pct": round(pct_f, 4),
            "sector": "—",
            "mcap_category": "—",
        })
    return rows


def _parse_period(val: Any) -> date | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    try:
        return pd.to_datetime(val).date()
    except Exception:
        return None


def fetch_etf_nport_history(symbol: str, *, max_filings: int = 16) -> dict[str, list[dict]]:
    """SEC NPORT-P equity holdings by reporting period (crypto path)."""
    _ensure_edgar()
    from edgar import Fund

    symbol = symbol.strip().upper()
    try:
        fund = Fund(symbol)
        filings = fund.get_filings(series_only=True, form="NPORT-P")
    except Exception as exc:
        logger.warning("NPORT fetch failed for %s: %s", symbol, exc)
        return {}
    if filings is None or len(filings) == 0:
        return {}

    by_period: dict[str, list[dict]] = {}
    for i in range(min(len(filings), max_filings * 2)):
        if len(by_period) >= max_filings:
            break
        try:
            report = filings[i].obj()
        except Exception as exc:
            logger.debug("NPORT obj() failed %s[%s]: %s", symbol, i, exc)
            continue
        period = _parse_period(getattr(report, "reporting_period", None))
        if period is None:
            continue
        key = period.isoformat()
        if key in by_period:
            continue
        holdings = _holdings_from_report(report)
        if holdings:
            by_period[key] = holdings
    return by_period


@dataclass
class UsHoldingsChangeConfig:
    max_snapshot_points: int = 12
    max_filings_per_etf: int = 16


def _summarize_records(
    records: list[dict],
    symbols: list[str],
    symbol_names: dict[str, str],
    *,
    market: str,
    source: str,
    snapshot_note: str,
) -> dict[str, Any]:
    df = pd.DataFrame(records)
    df = enrich_dataframe_sectors(df)
    dates = sorted(df["date"].unique().tolist())

    per_scheme_rows: list[dict] = []
    for (sid, stock), grp in df.groupby(["scheme_id", "stock"]):
        grp = grp.sort_values("date")
        first_pct = float(grp["holding_pct"].iloc[0])
        last_pct = float(grp["holding_pct"].iloc[-1])
        change = last_pct - first_pct
        if abs(change) < _TREND_FLAT_PCT:
            trend = "STABLE"
        elif change > 0:
            trend = "INCREASING"
        else:
            trend = "DECREASING"
        per_scheme_rows.append({
            "scheme_id": sid,
            "scheme_name": symbol_names.get(str(sid), str(sid)),
            "stock": stock,
            "sector": grp["sector"].iloc[-1] if "sector" in grp.columns else "—",
            "mcap_category": "—",
            "first_date": grp["date"].iloc[0],
            "first_pct": round(first_pct, 3),
            "last_date": grp["date"].iloc[-1],
            "last_pct": round(last_pct, 3),
            "change_pct": round(change, 3),
            "trend": trend,
            "n_snapshots": len(grp),
        })
    per_scheme = pd.DataFrame(per_scheme_rows)

    overall_rows: list[dict] = []
    for stock, grp in per_scheme.groupby("stock"):
        n_inc = int((grp["trend"] == "INCREASING").sum())
        n_dec = int((grp["trend"] == "DECREASING").sum())
        n_stable = int((grp["trend"] == "STABLE").sum())
        n_schemes = grp["scheme_id"].nunique()
        if n_inc and not n_dec:
            overall_trend = "INCREASING"
        elif n_dec and not n_inc:
            overall_trend = "DECREASING"
        elif n_inc and n_dec:
            overall_trend = "MIXED"
        else:
            overall_trend = "STABLE"
        overall_rows.append({
            "stock": stock,
            "sector": grp["sector"].iloc[0] if "sector" in grp.columns else "—",
            "mcap_category": "—",
            "n_schemes": int(n_schemes),
            "schemes_increasing": n_inc,
            "schemes_decreasing": n_dec,
            "schemes_stable": n_stable,
            "avg_holding_pct": round(float(grp["last_pct"].mean()), 3),
            "avg_change_pct": round(float(grp["change_pct"].mean()), 3),
            "total_change_pct": round(float(grp["change_pct"].sum()), 3),
            "overall_trend": overall_trend,
        })
    overall = pd.DataFrame(overall_rows).sort_values("avg_change_pct", ascending=False)

    return attach_sector_views({
        "dates": dates,
        "raw": df,
        "per_scheme": per_scheme,
        "overall": overall,
        "scheme_ids": symbols,
        "scheme_names": symbol_names,
        "market": market,
        "source": source,
        "snapshot_note": snapshot_note,
        "analyzed_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    })


def _nport_dated_holdings(
    symbol: str,
    from_date: date,
    to_date: date,
    *,
    cfg: UsHoldingsChangeConfig,
) -> list[tuple[date, list[dict]]]:
    """NPORT equity holdings snapshots that fall in [from_date, to_date]."""
    history = fetch_etf_nport_history(symbol, max_filings=cfg.max_filings_per_etf)
    if not history:
        return []

    dated: list[tuple[date, list[dict]]] = []
    for ps, holdings in history.items():
        d = _parse_period(ps)
        if d is None:
            continue
        if from_date <= d <= to_date:
            dated.append((d, holdings))
    dated.sort(key=lambda x: x[0])

    if not dated:
        all_dated = sorted(
            ((_parse_period(ps), h) for ps, h in history.items()),
            key=lambda x: x[0] or date.min,
        )
        all_dated = [(d, h) for d, h in all_dated if d is not None]
        if all_dated:
            before = [p for p in all_dated if p[0] <= to_date]
            after = [p for p in all_dated if p[0] >= from_date]
            pick: list[tuple[date, list[dict]]] = []
            if before:
                pick.append(before[-1])
            if after and after[0] not in pick:
                pick.append(after[0])
            # Prefer points that are at least inside a widened window around the range
            dated = sorted(pick, key=lambda x: x[0])
            # Keep only if they reasonably relate to the requested window
            dated = [p for p in dated if (from_date - timedelta(days=100)) <= p[0] <= (to_date + timedelta(days=10))]

    if len(dated) > cfg.max_snapshot_points and cfg.max_snapshot_points > 1:
        step = (len(dated) - 1) / (cfg.max_snapshot_points - 1)
        idxs = sorted({round(j * step) for j in range(cfg.max_snapshot_points)})
        dated = [dated[j] for j in idxs]
    return dated


def _analyze_indmoney_us(
    symbols: list[str],
    symbol_names: dict[str, str],
    from_date: date,
    to_date: date,
    *,
    cfg: UsHoldingsChangeConfig,
    progress_callback: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    """US analysis: INDMoney for catalog + latest Companies cut; SEC NPORT for
    historical reporting periods inside the user-selected date range.

    INDMoney only exposes the latest holdings page — without NPORT the range would
    collapse to today-only (which is what users hit before).
    """
    records: list[dict] = []
    total = max(len(symbols), 1)
    today = date.today()
    nport_dates: set[date] = set()
    indmoney_used = False

    for i, sym in enumerate(symbols):
        sname = symbol_names.get(sym, sym)
        if progress_callback:
            progress_callback(i / total, f"US holdings — {sname}")

        # 1) Historical periods in the selected date range (SEC NPORT)
        dated = _nport_dated_holdings(sym, from_date, to_date, cfg=cfg)
        for d, holdings in dated:
            nport_dates.add(d)
            for h in holdings:
                records.append({
                    "date": d,
                    "scheme_id": sym,
                    "scheme_name": sname,
                    "stock": h["stock"],
                    "security_slug": h["stock"],
                    "sector": h.get("sector") or "—",
                    "mcap_category": "—",
                    "holding_pct": float(h["holding_pct"]),
                    "stock_name": h.get("stock_name") or h["stock"],
                })

        # 2) Latest INDMoney Companies / Holding % when "to" covers today
        if from_date <= today <= to_date:
            holdings = fetch_indmoney_etf_holdings(sym)
            if holdings:
                indmoney_used = True
                save_holdings_snapshot("us", sym, holdings, as_of=today)
                for h in holdings:
                    records.append({
                        "date": today,
                        "scheme_id": sym,
                        "scheme_name": sname,
                        "stock": h["stock"],
                        "security_slug": h["stock"],
                        "sector": h.get("sector") or "—",
                        "mcap_category": "—",
                        "holding_pct": float(h["holding_pct"]),
                        "stock_name": h.get("stock_name") or h["stock"],
                    })

    if not records:
        return {
            "error": (
                "No US ETF holdings found for the selected date range. "
                "Tried SEC NPORT reporting periods in-range plus today's INDMoney "
                "Companies/Holding % cut."
            ),
        }

    # If the same (scheme, stock, date) appears twice (NPORT + INDMoney on today),
    # keep the last row (INDMoney) by de-duping.
    df_tmp = pd.DataFrame(records)
    df_tmp = df_tmp.drop_duplicates(subset=["scheme_id", "stock", "date"], keep="last")
    records = df_tmp.to_dict("records")

    dates = sorted({r["date"] for r in records})
    parts = []
    if nport_dates:
        parts.append(
            f"{len(nport_dates)} SEC NPORT period(s) in/near your range"
        )
    if indmoney_used:
        parts.append("today's INDMoney Companies/Holding % cut")
    note = (
        f"{len(dates)} snapshot date(s): {dates[0]} -> {dates[-1]}. "
        + (" + ".join(parts) if parts else "holdings snapshots")
        + ". ETF list/UI from INDMoney; historical points from SEC NPORT "
        "(INDMoney does not publish past Companies cuts)."
    )
    return _summarize_records(
        records, symbols, symbol_names,
        market="us", source="indmoney+nport", snapshot_note=note,
    )


def _analyze_nport_crypto(
    symbols: list[str],
    symbol_names: dict[str, str],
    from_date: date,
    to_date: date,
    *,
    cfg: UsHoldingsChangeConfig,
    progress_callback: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    records: list[dict] = []
    total = max(len(symbols), 1)
    for i, sym in enumerate(symbols):
        sname = symbol_names.get(sym, sym)
        if progress_callback:
            progress_callback(i / total, f"SEC NPORT — {sname}")
        dated = _nport_dated_holdings(sym, from_date, to_date, cfg=cfg)
        for d, holdings in dated:
            for h in holdings:
                records.append({
                    "date": d,
                    "scheme_id": sym,
                    "scheme_name": sname,
                    "stock": h["stock"],
                    "security_slug": h["stock"],
                    "sector": h.get("sector") or "—",
                    "mcap_category": "—",
                    "holding_pct": float(h["holding_pct"]),
                    "stock_name": h.get("stock_name") or h["stock"],
                })

    if not records:
        return {
            "error": (
                "No SEC NPORT-P equity holdings found for the selected crypto ETFs / date range. "
                "Try widening the range (NPORT public cuts are typically quarterly)."
            ),
        }
    dates = sorted({r["date"] for r in records})
    note = (
        f"{len(dates)} SEC NPORT-P reporting period(s) in range "
        f"({dates[0]} -> {dates[-1]}). Full equity holdings for crypto-theme ETFs."
    )
    return _summarize_records(
        records, symbols, symbol_names,
        market="crypto", source="sec_nport", snapshot_note=note,
    )


def analyze_us_etf_holdings_change(
    market: str,
    symbols: list[str],
    symbol_names: dict[str, str],
    from_date: date,
    to_date: date,
    *,
    cfg: UsHoldingsChangeConfig | None = None,
    progress_callback: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    """US = INDMoney Companies/Holding %; Crypto = SEC NPORT-P."""
    cfg = cfg or UsHoldingsChangeConfig()
    if not symbols:
        return {"error": "No ETFs selected."}
    if from_date > to_date:
        from_date, to_date = to_date, from_date

    if market == "us":
        return _analyze_indmoney_us(
            symbols, symbol_names, from_date, to_date,
            cfg=cfg, progress_callback=progress_callback,
        )
    return _analyze_nport_crypto(
        symbols, symbol_names, from_date, to_date,
        cfg=cfg, progress_callback=progress_callback,
    )


analyze_yahoo_etf_holdings_change = analyze_us_etf_holdings_change
YahooHoldingsChangeConfig = UsHoldingsChangeConfig


def analyze_india_etf_holdings_change(
    scheme_ids: list[int],
    scheme_names: dict[int, str],
    from_date: date,
    to_date: date,
    *,
    cfg: HoldingsChangeConfig | None = None,
    progress_callback: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    """India ETF holdings trend — same StockEdge month-end path as mutual funds."""
    result = analyze_holdings_change(
        scheme_ids,
        scheme_names,
        from_date,
        to_date,
        cfg=cfg,
        progress_callback=progress_callback,
    )
    if not result.get("error"):
        result["market"] = "india"
        result["source"] = "stockedge"
        result["snapshot_note"] = (
            f"{len(result['dates'])} month-end disclosure(s) via StockEdge "
            "(same data path as Mutual Fund Holdings)."
        )
        result = attach_sector_views(result)
    return result


__all__ = [
    "US_ETF_ISSUERS",
    "CRYPTO_ETF_ISSUERS",
    "US_ETF_CATALOG",
    "CRYPTO_ETF_CATALOG",
    "HoldingsChangeConfig",
    "UsHoldingsChangeConfig",
    "YahooHoldingsChangeConfig",
    "analyze_india_etf_holdings_change",
    "analyze_us_etf_holdings_change",
    "analyze_yahoo_etf_holdings_change",
    "fetch_amc_list",
    "fetch_etf_schemes_for_amc",
    "fetch_etf_nport_history",
    "fetch_indmoney_etf_categories",
    "fetch_indmoney_etf_holdings",
    "fetch_indmoney_etfs_for_category",
    "fetch_schemes_for_issuer",
    "is_etf_scheme",
    "list_catalog_etfs",
    "list_issuers",
]
