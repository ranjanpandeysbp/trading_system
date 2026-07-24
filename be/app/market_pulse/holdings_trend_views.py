"""
holdings_trend_views.py
-----------------------
Shared stock-wise / sector-wise aggregation for Mutual Fund Holdings and ETF Holdings.
(Streamlit UI lives in the React panels — this module is analysis-only.)
"""

from __future__ import annotations

from typing import Any

import pandas as pd

_TREND_FLAT_PCT = 0.05


def _entity_trends(
    raw: pd.DataFrame,
    *,
    entity_col: str,
    scheme_names: dict[Any, str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build per-scheme + overall trend tables for stock or sector entity column.

    Returns (entity_raw, per_scheme, overall) where entity_raw uses columns
    date, scheme_id, scheme_name, entity, holding_pct (entity renamed to `stock`
    for chart reuse when entity_col == 'stock'; for sector, entity is `sector`).
    """
    if raw is None or raw.empty or entity_col not in raw.columns:
        empty = pd.DataFrame()
        return empty, empty, empty

    df = raw.copy()
    df[entity_col] = df[entity_col].fillna("—").astype(str).replace({"": "—", "nan": "—", "None": "—"})

    if entity_col == "sector":
        # Sum stock weights into sector weight per fund per date
        entity_raw = (
            df.groupby(["date", "scheme_id", "scheme_name", "sector"], as_index=False)
            .agg(holding_pct=("holding_pct", "sum"))
        )
        id_col = "sector"
    else:
        entity_raw = df[["date", "scheme_id", "scheme_name", "stock", "sector", "holding_pct"]].copy()
        if "mcap_category" in df.columns:
            entity_raw["mcap_category"] = df["mcap_category"].values
        id_col = "stock"

    scheme_names = scheme_names or {}
    per_rows: list[dict] = []
    for (sid, entity), grp in entity_raw.groupby(["scheme_id", id_col]):
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
        row = {
            "scheme_id": sid,
            "scheme_name": scheme_names.get(sid, grp["scheme_name"].iloc[0] if "scheme_name" in grp else str(sid)),
            id_col: entity,
            "first_date": grp["date"].iloc[0],
            "first_pct": round(first_pct, 3),
            "last_date": grp["date"].iloc[-1],
            "last_pct": round(last_pct, 3),
            "change_pct": round(change, 3),
            "trend": trend,
            "n_snapshots": len(grp),
        }
        if id_col == "stock" and "sector" in grp.columns:
            row["sector"] = grp["sector"].iloc[-1]
        if id_col == "stock" and "mcap_category" in grp.columns:
            row["mcap_category"] = grp["mcap_category"].iloc[-1]
        per_rows.append(row)
    per_scheme = pd.DataFrame(per_rows)

    overall_rows: list[dict] = []
    for entity, grp in per_scheme.groupby(id_col):
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
        row = {
            id_col: entity,
            "n_schemes": int(n_schemes),
            "schemes_increasing": n_inc,
            "schemes_decreasing": n_dec,
            "schemes_stable": n_stable,
            "avg_holding_pct": round(float(grp["last_pct"].mean()), 3),
            "avg_change_pct": round(float(grp["change_pct"].mean()), 3),
            "total_change_pct": round(float(grp["change_pct"].sum()), 3),
            "overall_trend": overall_trend,
            "n_names": int(grp.shape[0]),  # placeholder; overwritten for sector below
        }
        if id_col == "stock":
            row["sector"] = grp["sector"].iloc[0] if "sector" in grp.columns else "—"
            row["mcap_category"] = grp["mcap_category"].iloc[0] if "mcap_category" in grp.columns else "—"
        overall_rows.append(row)
    overall = pd.DataFrame(overall_rows)

    if id_col == "sector" and not overall.empty and not df.empty:
        # How many distinct stocks map into each sector (latest snapshot)
        last_date = df["date"].max()
        latest = df[df["date"] == last_date]
        counts = latest.groupby("sector")["stock"].nunique().to_dict()
        overall["n_stocks"] = overall["sector"].map(counts).fillna(0).astype(int)
        overall = overall.drop(columns=["n_names"], errors="ignore")
    elif "n_names" in overall.columns:
        overall = overall.drop(columns=["n_names"], errors="ignore")

    if not overall.empty:
        overall = overall.sort_values("avg_change_pct", ascending=False)
    return entity_raw, per_scheme, overall


def attach_sector_views(result: dict) -> dict:
    """Add sector-wise frames onto an existing stock-level analysis result dict."""
    if not result or result.get("error"):
        return result
    raw = result.get("raw")
    if raw is None or (isinstance(raw, pd.DataFrame) and raw.empty):
        result["raw_sector"] = pd.DataFrame()
        result["per_scheme_sector"] = pd.DataFrame()
        result["overall_sector"] = pd.DataFrame()
        return result

    scheme_names = result.get("scheme_names") or {}
    raw_sector, per_sector, overall_sector = _entity_trends(
        raw, entity_col="sector", scheme_names=scheme_names,
    )
    # Charts expect columns stock / scheme_name / holding_pct / date
    if not raw_sector.empty:
        raw_sector = raw_sector.rename(columns={"sector": "stock"})
    result["raw_sector"] = raw_sector
    result["per_scheme_sector"] = per_sector
    result["overall_sector"] = overall_sector
    return result
