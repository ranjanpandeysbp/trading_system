"""
mutual_fund_holdings_engine.py
--------------------------------
StockEdge public API client for AMC / scheme lists and per-scheme domestic-equity
holdings, plus holdings-change-over-time analysis across a user-selected date range.

Endpoints (public, CORS-open, no auth required):
- GetMfAmcList                         — all AMCs
- GetPrimaryMfSchemeListByAmc/{amcId}  — equity schemes for one AMC
- GetDomesticEquityHoldings/{schemeId}/{date}  — per-stock holding % as of a date

Holdings snapshots only exist for month-end dates — a mid-month date returns an empty
list — so date-range analysis snaps to month-end dates within the selected range.

India-only (StockEdge covers Indian mutual funds / NSE-listed equities).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable

import pandas as pd
import requests

logger = logging.getLogger(__name__)

_BASE = "https://api.stockedge.com/Api"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}
_TIMEOUT = 20
_TREND_FLAT_PCT = 0.05  # |change in holding %| below this counts as STABLE


def _get(url: str, params: dict) -> list[dict]:
    try:
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []
    except Exception as exc:
        logger.debug("StockEdge API call failed %s %s: %s", url, params, exc)
        return []


def _paginate(url: str, extra_params: dict, *, page_size: int, max_pages: int) -> list[dict]:
    out: list[dict] = []
    for page in range(1, max_pages + 1):
        params = {**extra_params, "page": page, "pageSize": page_size, "lang": "en"}
        batch = _get(url, params)
        out.extend(batch)
        if len(batch) < page_size:
            break
    return out


def fetch_amc_list() -> list[dict]:
    """All Mutual Fund AMCs — ID, Name, AUM, AUMDate, SchemeCount, Slug."""
    return _paginate(f"{_BASE}/MfAmcDashboardApi/GetMfAmcList", {}, page_size=50, max_pages=5)


def fetch_schemes_for_amc(amc_id: int, *, asset_type_id: int = 1, nav_period: int = 1095) -> list[dict]:
    """Equity schemes for one AMC — ID, Name, Description, NAV, Return, AUM, Slug."""
    url = f"{_BASE}/MfAmcDashboardApi/GetPrimaryMfSchemeListByAmc/{amc_id}"
    return _paginate(
        url, {"MfSchemeAssetTypeID": asset_type_id, "MfNAVChangePeriodType": nav_period},
        page_size=50, max_pages=6,
    )


def fetch_scheme_holdings(scheme_id: int, as_of: str) -> list[dict]:
    """Domestic equity holdings for one scheme as of a month-end date ('YYYY-MM-DD')."""
    url = f"{_BASE}/MfSchemeDashboardApi/GetDomesticEquityHoldings/{scheme_id}/{as_of}"
    return _paginate(url, {}, page_size=100, max_pages=5)


def month_end_dates(from_date: date, to_date: date, *, max_points: int = 24) -> list[date]:
    """Month-end dates within [from_date, to_date], downsampled to at most max_points."""
    if from_date > to_date:
        from_date, to_date = to_date, from_date
    out: list[date] = []
    cur = date(from_date.year, from_date.month, 1)
    while cur <= to_date:
        nxt = date(cur.year + 1, 1, 1) if cur.month == 12 else date(cur.year, cur.month + 1, 1)
        month_end = nxt - timedelta(days=1)
        if month_end >= from_date:
            out.append(month_end)
        cur = nxt
    if not out:
        out = [to_date]
    if len(out) > max_points and max_points > 1:
        step = (len(out) - 1) / (max_points - 1)
        idxs = sorted({round(i * step) for i in range(max_points)})
        out = [out[i] for i in idxs]
    return out


@dataclass
class HoldingsChangeConfig:
    max_snapshot_points: int = 18


def analyze_holdings_change(
    scheme_ids: list[int],
    scheme_names: dict[int, str],
    from_date: date,
    to_date: date,
    *,
    cfg: HoldingsChangeConfig | None = None,
    progress_callback: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    """Fetch per-scheme domestic-equity holdings across month-end snapshots in the
    date range and summarize each stock's holding-% trend per scheme and overall."""
    cfg = cfg or HoldingsChangeConfig()
    dates = month_end_dates(from_date, to_date, max_points=cfg.max_snapshot_points)
    if not dates or not scheme_ids:
        return {"error": "No valid schemes or dates selected."}

    records: list[dict] = []
    total = len(scheme_ids) * len(dates)
    done = 0
    for sid in scheme_ids:
        sname = scheme_names.get(sid, str(sid))
        for d in dates:
            holdings = fetch_scheme_holdings(sid, d.isoformat())
            for h in holdings:
                pct = h.get("HoldingPercentage")
                if pct is None:
                    continue
                records.append({
                    "date": d,
                    "scheme_id": sid,
                    "scheme_name": sname,
                    "stock": h.get("Name"),
                    "security_slug": h.get("SecuritySlug"),
                    "sector": h.get("SectorName") or h.get("EquitySectorName") or "—",
                    "mcap_category": h.get("McapCategory") or "—",
                    "holding_pct": float(pct),
                })
            done += 1
            if progress_callback:
                progress_callback(done / total, f"{sname} — {d.isoformat()}")

    if not records:
        return {"error": "No holdings data returned for the selected schemes/date range (data may not exist that far back)."}

    df = pd.DataFrame(records)

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
            "scheme_name": scheme_names.get(sid, str(sid)),
            "stock": stock,
            "sector": grp["sector"].iloc[-1],
            "mcap_category": grp["mcap_category"].iloc[-1],
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
            "sector": grp["sector"].iloc[0],
            "mcap_category": grp["mcap_category"].iloc[0],
            "n_schemes": int(n_schemes),
            "schemes_increasing": n_inc,
            "schemes_decreasing": n_dec,
            "schemes_stable": n_stable,
            "avg_change_pct": round(float(grp["change_pct"].mean()), 3),
            "total_change_pct": round(float(grp["change_pct"].sum()), 3),
            "overall_trend": overall_trend,
        })
    overall = pd.DataFrame(overall_rows).sort_values("avg_change_pct", ascending=False)

    return {
        "dates": dates,
        "raw": df,
        "per_scheme": per_scheme,
        "overall": overall,
        "scheme_ids": scheme_ids,
        "scheme_names": scheme_names,
    }
