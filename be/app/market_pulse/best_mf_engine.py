"""
best_mf_engine.py
--------------------
Ranks mutual fund schemes by trailing NAV return across one or more AMCs and
an asset class (equity/debt/hybrid/other), optionally filtered to a fund
category substring (e.g. "Flexi Cap", "Credit Risk", "Index Funds").

Reuses the same StockEdge AMC/scheme public API as
mutual_fund_holdings_engine.py — fetch_schemes_for_amc's `Return` field is
computed over whichever `nav_period` (days) is requested, so ranking by
1/3/5-year trailing return is just three different values of that parameter.

India-only (StockEdge covers Indian mutual funds).
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Callable

ASSET_TYPE_OPTIONS = [
    {"value": 1, "label": "Equity"},
    {"value": 2, "label": "Debt / Income"},
    {"value": 3, "label": "Hybrid"},
    {"value": 4, "label": "Other (Index / ETF / FoF / Commodity)"},
]

# Common category substrings per asset type, matched case-insensitively
# against the scheme's `Description` field — offered as quick-pick chips,
# but the category filter itself accepts any free-text substring.
CATEGORY_HINTS: dict[int, list[str]] = {
    1: [
        "Large Cap", "Mid Cap", "Small Cap", "Large & Mid Cap", "Multi Cap", "Flexi Cap",
        "ELSS", "Focused Fund", "Value Fund", "Contra Fund", "Dividend Yield",
        "Sector Funds", "Index Funds", "ETFs", "Thematic",
    ],
    2: [
        "Liquid", "Overnight", "Ultra Short Duration", "Low Duration", "Money Market",
        "Short Duration", "Medium Duration", "Long Duration", "Dynamic Bond",
        "Corporate Bond", "Credit Risk", "Banking and PSU", "Gilt Fund", "Floating Rate",
    ],
    3: [
        "Aggressive Hybrid", "Conservative Hybrid", "Balanced Hybrid",
        "Dynamic Asset Allocation", "Multi Asset Allocation", "Arbitrage Fund", "Equity Savings",
    ],
    4: ["Index Funds", "ETFs", "FoFs", "Gold", "Silver"],
}

RETURN_PERIOD_OPTIONS = [
    {"value": 365, "label": "1 Year"},
    {"value": 1095, "label": "3 Years"},
    {"value": 1825, "label": "5 Years"},
]

_TOP_N_DEFAULT = 30
_TOP_N_MAX = 100


def rank_best_funds(
    amc_ids: list[int],
    asset_type_id: int,
    *,
    category_filter: str = "",
    rank_period: int = 365,
    top_n: int = _TOP_N_DEFAULT,
    progress_callback: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    """Fetch equity/debt/hybrid/other schemes for each selected AMC at the
    chosen trailing-return period, optionally filter by category substring,
    and rank all matches by trailing return descending."""
    from app.market_pulse.mutual_fund_holdings_engine import fetch_amc_list, fetch_schemes_for_amc

    if not amc_ids:
        return {"error": "Select at least one AMC."}

    top_n = max(1, min(top_n, _TOP_N_MAX))
    amc_name_by_id = {int(a["ID"]): a["Name"] for a in fetch_amc_list() if a.get("ID") is not None}

    rows: list[dict[str, Any]] = []
    cat_q = (category_filter or "").strip().lower()
    total = len(amc_ids)
    for i, amc_id in enumerate(amc_ids):
        schemes = fetch_schemes_for_amc(amc_id, asset_type_id=asset_type_id, nav_period=rank_period)
        amc_name = amc_name_by_id.get(int(amc_id), str(amc_id))
        for s in schemes:
            desc = s.get("Description") or ""
            if cat_q and cat_q not in desc.lower():
                continue
            ret = s.get("Return")
            if ret is None:
                continue
            rows.append({
                "scheme_id": s.get("ID") or s.get("Id"),
                "scheme_name": s.get("Name"),
                "amc_id": amc_id,
                "amc_name": amc_name,
                "category": desc,
                "nav": s.get("NAV"),
                "return_pct": float(ret),
                "aum_cr": s.get("AUM"),
            })
        if progress_callback:
            progress_callback((i + 1) / total, f"{amc_name} — {len(schemes)} schemes")

    if not rows:
        return {"error": "No schemes matched the selected AMC(s), asset class, and category filter."}

    rows.sort(key=lambda r: r["return_pct"], reverse=True)
    for idx, r in enumerate(rows, start=1):
        r["rank"] = idx

    return {
        "amc_ids": amc_ids,
        "asset_type_id": asset_type_id,
        "category_filter": category_filter or None,
        "rank_period": rank_period,
        "universe_count": len(rows),
        "top": rows[:top_n],
        "generated_at": datetime.utcnow().isoformat(),
    }


async def rank_best_funds_async(
    amc_ids: list[int],
    asset_type_id: int,
    *,
    category_filter: str = "",
    rank_period: int = 365,
    top_n: int = _TOP_N_DEFAULT,
    progress_callback: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        rank_best_funds, amc_ids, asset_type_id,
        category_filter=category_filter, rank_period=rank_period, top_n=top_n,
        progress_callback=progress_callback,
    )
