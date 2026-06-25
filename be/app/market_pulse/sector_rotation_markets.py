"""India-only sector index lists (no US/crypto sector rotation UI)."""

from __future__ import annotations

INDIA_SECTOR_INDICES: list[str] = [
    "NIFTY AUTO",
    "NIFTY BANK",
    "NIFTY FMCG",
    "NIFTY IT",
    "NIFTY METAL",
    "NIFTY PHARMA",
    "NIFTY REALTY",
    "NIFTY ENERGY",
    "NIFTY MEDIA",
    "NIFTY PSU BANK",
    "NIFTY FINANCIAL SERVICES",
    "NIFTY INFRA",
    "NIFTY COMMODITIES",
    "NIFTY CONSUMPTION",
    "NIFTY HEALTHCARE",
]


def render_india_sector_index_filter(*_args, **_kwargs) -> list[str]:
    """Stub — API passes indices directly."""
    return list(INDIA_SECTOR_INDICES)
