"""Strategy Lab preset templates exposed in the backtester."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from app.market_pulse.presets import get_presets_by_category, get_presets_for_market
from app.market_pulse.ticker_utils import CRYPTO_MARKET, GROWW_MARKET

PRESET_ID_PREFIX = "sl_preset_"

_TF_ALIASES: dict[str, list[str]] = {
    "1m": ["1m", "3m"],
    "3m": ["3m", "5m"],
    "5m": ["5m", "15m"],
    "15m": ["15m", "30m", "1h"],
    "30m": ["30m", "1h"],
    "1h": ["1h", "4h"],
    "4h": ["4h", "1d"],
    "1d": ["1d", "1wk"],
    "1wk": ["1wk", "1d"],
}

PRESET_STRATEGY_META: dict[str, dict[str, Any]] = {}
PRESET_ID_TO_NAME: dict[str, str] = {}
PRESET_ID_TO_MARKET: dict[str, str] = {}


def _preset_id(name: str, market: str) -> str:
    tag = "crypto" if market == CRYPTO_MARKET else "india"
    digest = hashlib.sha256(f"{market}:{name}".encode()).hexdigest()[:10]
    return f"{PRESET_ID_PREFIX}{tag}_{digest}"


def _timeframes_for_preset(tf: str) -> list[str]:
    base = (tf or "1d").strip().lower()
    return _TF_ALIASES.get(base, [base])


def _register_market_presets(market: str, market_label: str) -> None:
    by_cat = get_presets_by_category(market)
    for cat_label, presets in by_cat.items():
        for name, preset in presets.items():
            pid = _preset_id(name, market)
            tf = preset.get("recommended_timeframe", "1d")
            PRESET_ID_TO_NAME[pid] = name
            PRESET_ID_TO_MARKET[pid] = market
            PRESET_STRATEGY_META[pid] = {
                "id": pid,
                "name": name,
                "category": f"sl_presets_{market_label}",
                "category_label": cat_label,
                "timeframes": _timeframes_for_preset(tf),
                "summary": preset.get("description", ""),
                "description": preset.get("description", ""),
                "indicators": preset.get("indicators", []),
                "entry_rules": preset.get("entry_rules", []),
                "exit_rules": preset.get("exit_rules", []),
                "needs_benchmark": False,
                "min_bars": 30,
                "engine": True,
                "preset": True,
                "recommended_sl": preset.get("recommended_sl"),
                "recommended_tp": preset.get("recommended_tp"),
                "recommended_timeframe": tf,
            }


_register_market_presets(GROWW_MARKET, "india")
_register_market_presets(CRYPTO_MARKET, "crypto")

PRESET_STRATEGY_CATEGORIES: dict[str, dict[str, Any]] = {}
for market, label in ((GROWW_MARKET, "india"), (CRYPTO_MARKET, "crypto")):
    for cat_label, presets in get_presets_by_category(market).items():
        cat_key = re.sub(r"[^a-z0-9]+", "_", cat_label.lower()).strip("_")
        cat_id = f"sl_{label}_{cat_key}"[:64]
        ids = [_preset_id(n, market) for n in presets]
        PRESET_STRATEGY_CATEGORIES.setdefault(cat_id, {
            "label": cat_label,
            "description": f"Strategy Lab preset templates ({label}).",
            "timeframes": ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"],
            "strategy_ids": [],
        })
        PRESET_STRATEGY_CATEGORIES[cat_id]["strategy_ids"].extend(ids)


def is_preset_strategy(name: str) -> bool:
    return name in PRESET_STRATEGY_META


def preset_for_id(strategy_id: str) -> dict[str, Any] | None:
    name = PRESET_ID_TO_NAME.get(strategy_id)
    if not name:
        return None
    market = PRESET_ID_TO_MARKET[strategy_id]
    return get_presets_for_market(market).get(name)


def list_preset_categories() -> list[dict[str, Any]]:
    categories = []
    for cat_id, info in PRESET_STRATEGY_CATEGORIES.items():
        strategies = [PRESET_STRATEGY_META[sid] for sid in info["strategy_ids"] if sid in PRESET_STRATEGY_META]
        if not strategies:
            continue
        categories.append({
            "id": cat_id,
            "label": info["label"],
            "description": info["description"],
            "timeframes": info["timeframes"],
            "strategy_count": len(strategies),
            "strategies": strategies,
        })
    return categories
