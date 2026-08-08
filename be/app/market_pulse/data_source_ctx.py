"""Track which OHLCV vendor actually served bars during a request.

Groww / CoinDCX / yfinance decisions happen inside ``fetch_data_for_gap_scan``.
We record them on a shared list held by a ContextVar so ``asyncio.to_thread``
workers (which copy the context) mutate the same list the parent can read.
"""

from __future__ import annotations

from collections import Counter
from contextvars import ContextVar
from typing import Any

import pandas as pd

_bucket: ContextVar[list[str] | None] = ContextVar("ohlcv_data_sources", default=None)

SOURCE_LABELS = {
    "groww": "Groww",
    "indmoney": "IndMoney",
    "yfinance": "yfinance",
    "coindcx": "CoinDCX",
}


def start_tracking() -> list[str]:
    bucket: list[str] = []
    _bucket.set(bucket)
    return bucket


def clear_tracking() -> None:
    _bucket.set(None)


def note_source(source: str) -> None:
    name = (source or "").strip().lower()
    if not name:
        return
    bucket = _bucket.get()
    if bucket is None:
        return
    bucket.append(name)


def mark_source(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """Stamp ``df.attrs['data_source']`` and record the source for this request."""
    name = (source or "").strip().lower() or "unknown"
    if df is None or getattr(df, "empty", True):
        return df
    try:
        df.attrs["data_source"] = name
    except Exception:
        pass
    note_source(name)
    return df


def read_df_source(df: pd.DataFrame | None) -> str | None:
    if df is None or getattr(df, "empty", True):
        return None
    try:
        value = df.attrs.get("data_source")
    except Exception:
        return None
    return str(value) if value else None


def summarize_sources() -> dict[str, Any]:
    bucket = _bucket.get() or []
    if not bucket:
        return {}
    counts = Counter(bucket)
    primary, _ = counts.most_common(1)[0]
    return {
        "data_source": primary,
        "data_sources_used": list(counts.keys()),
        "data_source_counts": dict(counts),
        "data_source_label": SOURCE_LABELS.get(primary, primary),
    }


def attach_data_source(payload: Any) -> Any:
    """Merge tracked source metadata onto a top-level result dict."""
    if not isinstance(payload, dict):
        return payload
    meta = summarize_sources()
    if not meta:
        return payload
    if payload.get("data_source"):
        # Keep explicit engine-provided source; still expose used list if missing.
        out = dict(payload)
        if "data_sources_used" not in out and meta.get("data_sources_used"):
            out["data_sources_used"] = meta["data_sources_used"]
        if "data_source_label" not in out:
            src = str(out.get("data_source") or "")
            out["data_source_label"] = SOURCE_LABELS.get(src, src)
        return out
    return {**payload, **meta}
