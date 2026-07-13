"""
ticker_investigation_strategy_catalog.py
----------------------------------------
All live hub + TA screener strategies available for Ticker Investigation — Select Strategy.

Strategy ids are introspected at CALL TIME from app.trading_hubs.registry.HUB_SECTIONS and
app.market_pulse.ta_screener_registry.TA_SCREENERS (rather than a hardcoded duplicate list
copy-pasted from the original truebacktesting source), so this catalog stays in sync
automatically as more hub sections / TA screeners are registered there later.
"""

from __future__ import annotations

from app.market_pulse.ta_screener_registry import TA_SCREENERS
from app.trading_hubs.registry import HUB_META, HUB_SECTIONS

# TA screener ids excluded from "pick one strategy to run against this ticker" — these
# are composite tabs / the investigation itself, not single-engine analyzers with a
# run_strategy_live_analysis() dispatch path.
_EXCLUDED_TA_IDS = {"ticker_investigation", "sentiment_screener"}


def hub_strategy_options() -> dict[str, str]:
    """id -> label for every registered trading_hubs strategy section (swing/intraday/scalping/smart_money)."""
    return {s["id"]: s["label"] for s in HUB_SECTIONS}


def ta_strategy_options() -> dict[str, str]:
    """id -> label for every registered TA screener (excluding composite/self entries)."""
    return {s["id"]: s["label"] for s in TA_SCREENERS if s["id"] not in _EXCLUDED_TA_IDS}


def investigation_strategy_groups() -> dict[str, list[str]]:
    """Group label -> ordered list of strategy ids, rebuilt live from the two registries
    on every call (never cached/hardcoded), so newly-registered strategies show up
    automatically without touching this file."""
    groups: dict[str, list[str]] = {}
    for s in HUB_SECTIONS:
        hub_label = HUB_META.get(s["hub"], {}).get("label", s["hub"].replace("_", " ").title())
        groups.setdefault(hub_label, []).append(s["id"])
    ta_ids = [s["id"] for s in TA_SCREENERS if s["id"] not in _EXCLUDED_TA_IDS]
    if ta_ids:
        groups["TA Screeners"] = ta_ids
    return groups


def all_investigation_strategy_ids() -> list[str]:
    keys: list[str] = []
    for group_keys in investigation_strategy_groups().values():
        keys.extend(group_keys)
    return keys


def strategy_label(strategy_id: str) -> str:
    hub_opts = hub_strategy_options()
    if strategy_id in hub_opts:
        return hub_opts[strategy_id]
    ta_opts = {s["id"]: s["label"] for s in TA_SCREENERS}
    return ta_opts.get(strategy_id, strategy_id)


def strategy_group(strategy_id: str) -> str:
    for group, ids in investigation_strategy_groups().items():
        if strategy_id in ids:
            return group
    return "Other"
