from collections.abc import Callable
from typing import Any

from app.strategies.catalog import CATEGORY_DESCRIPTIONS, STRATEGY_DETAILS
from app.strategies.engine_strategies import (
    ENGINE_STRATEGY_META,
    engine_min_bars,
    is_engine_strategy,
    list_engine_categories,
)
from app.strategies.preset_strategies import (
    PRESET_STRATEGY_META,
    is_preset_strategy,
    list_preset_categories,
)
from app.strategies.strategies_intraday import INTRADAY_STRATEGIES
from app.strategies.strategies_scalping import SCALPING_STRATEGIES
from app.strategies.strategies_swing import SWING_STRATEGIES

STRATEGY_CATEGORIES = {
    "scalping": {
        "label": "Scalping",
        "timeframes": ["1m", "3m"],
        "strategies": SCALPING_STRATEGIES,
    },
    "intraday": {
        "label": "Intraday",
        "timeframes": ["5m", "15m"],
        "strategies": INTRADAY_STRATEGIES,
    },
    "swing": {
        "label": "Swing",
        "timeframes": ["1d"],
        "strategies": SWING_STRATEGIES,
    },
}

BENCHMARK_STRATEGIES = frozenset({"relative_strength_sector_rotation_swing"})

STRATEGY_MIN_BARS: dict[str, int] = {
    "golden_death_cross_swing": 210,
    "weekly_rsi_pullback_swing": 210,
    "consolidation_breakout_swing": 30,
    "bollinger_mean_reversion_swing": 110,
    "relative_strength_sector_rotation_swing": 70,
    "rsi_divergence_intraday": 30,
    "vwap_trend_intraday": 30,
    "macd_volume_confirm_intraday": 35,
    "sr_breakout_pullback_intraday": 25,
    "bollinger_squeeze_breakout_scalp": 110,
    "ema_crossover_scalp": 25,
}


def needs_benchmark(name: str) -> bool:
    return name in BENCHMARK_STRATEGIES


def min_bars_for_strategy(name: str) -> int:
    if is_engine_strategy(name):
        return engine_min_bars(name)
    if is_preset_strategy(name):
        return int(PRESET_STRATEGY_META.get(name, {}).get("min_bars", 30))
    return STRATEGY_MIN_BARS.get(name, 30)


def uses_engine_backtest(name: str) -> bool:
    return is_engine_strategy(name) or is_preset_strategy(name)


ALL_STRATEGIES: dict[str, Callable[..., Any]] = {}
STRATEGY_META: dict[str, dict[str, Any]] = {}

for category, info in STRATEGY_CATEGORIES.items():
    for name, fn in info["strategies"].items():
        ALL_STRATEGIES[name] = fn
        details = STRATEGY_DETAILS.get(name, {})
        STRATEGY_META[name] = {
            "id": name,
            "name": name.replace("_", " ").title(),
            "category": category,
            "category_label": info["label"],
            "timeframes": info["timeframes"],
            "summary": details.get("summary", ""),
            "description": details.get("description", ""),
            "indicators": details.get("indicators", []),
            "entry_rules": details.get("entry_rules", []),
            "exit_rules": details.get("exit_rules", []),
            "needs_benchmark": details.get("needs_benchmark", needs_benchmark(name)),
            "min_bars": min_bars_for_strategy(name),
        }


def get_strategy(name: str) -> Callable[..., Any]:
    if is_engine_strategy(name):
        raise KeyError(f"Strategy {name} is an engine strategy — use EngineBacktestService")
    if name not in ALL_STRATEGIES:
        raise KeyError(f"Unknown strategy: {name}")
    return ALL_STRATEGIES[name]


BACKTEST_PERIOD_DEFAULTS: dict[str, str] = {
    "1m": "7d",
    "3m": "30d",
    "5m": "60d",
    "15m": "60d",
    "1d": "2y",
    "1wk": "5y",
}


def default_backtest_period(timeframe: str) -> str:
    return BACKTEST_PERIOD_DEFAULTS.get(timeframe, "1y")


def category_for_timeframe(timeframe: str) -> str | None:
    for category, info in STRATEGY_CATEGORIES.items():
        if timeframe in info["timeframes"]:
            return category
    return None


def _stringify_meta_item(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        if "type" in item:
            label = str(item["type"]).upper()
            params = ", ".join(f"{k}={v}" for k, v in item.items() if k != "type")
            return f"{label}({params})" if params else label
        if "left" in item:
            right = item.get("right_val") or item.get("right", "")
            return f"{item.get('left', '')} {item.get('op', '')} {right}".strip()
    return str(item)


def strategy_meta_for_api(meta: dict[str, Any]) -> dict[str, Any]:
    """Normalize strategy metadata for StrategyInfo API responses."""
    return {
        "id": meta["id"],
        "name": meta["name"],
        "category": meta["category"],
        "category_label": meta["category_label"],
        "timeframes": list(meta["timeframes"]),
        "summary": str(meta.get("summary") or ""),
        "description": str(meta.get("description") or ""),
        "indicators": [_stringify_meta_item(x) for x in (meta.get("indicators") or [])],
        "entry_rules": [_stringify_meta_item(x) for x in (meta.get("entry_rules") or [])],
        "exit_rules": [_stringify_meta_item(x) for x in (meta.get("exit_rules") or [])],
        "needs_benchmark": bool(meta.get("needs_benchmark", False)),
        "min_bars": int(meta.get("min_bars", 30)),
    }


def _category_payload(
    cat_id: str,
    label: str,
    description: str,
    timeframes: list[str],
    strategies: list[dict[str, Any]],
) -> dict[str, Any]:
    normalized = [strategy_meta_for_api(s) for s in strategies]
    return {
        "id": cat_id,
        "label": label,
        "description": description,
        "timeframes": timeframes,
        "strategy_count": len(normalized),
        "strategies": normalized,
    }


def list_scanner_categories() -> list[dict[str, Any]]:
    """Rule-based strategies runnable by ScannerService (excludes engine/preset)."""
    categories = []
    for cat_id, info in STRATEGY_CATEGORIES.items():
        strategies = [STRATEGY_META[sid] for sid in info["strategies"]]
        categories.append(_category_payload(
            cat_id,
            info["label"],
            CATEGORY_DESCRIPTIONS.get(cat_id, ""),
            info["timeframes"],
            strategies,
        ))
    return categories


def list_categories() -> list[dict[str, Any]]:
    categories = list_scanner_categories()
    for cat in list_engine_categories():
        categories.append(_category_payload(
            cat["id"],
            cat["label"],
            cat["description"],
            cat["timeframes"],
            cat["strategies"],
        ))
    for cat in list_preset_categories():
        categories.append(_category_payload(
            cat["id"],
            cat["label"],
            cat["description"],
            cat["timeframes"],
            cat["strategies"],
        ))
    return categories


def all_strategy_meta() -> dict[str, dict[str, Any]]:
    return {**STRATEGY_META, **ENGINE_STRATEGY_META, **PRESET_STRATEGY_META}


def all_strategy_meta_for_api() -> dict[str, dict[str, Any]]:
    return {sid: strategy_meta_for_api(meta) for sid, meta in all_strategy_meta().items()}


def get_strategy_meta(strategy_id: str) -> dict[str, Any] | None:
    return all_strategy_meta().get(strategy_id)


def get_strategy_meta_for_api(strategy_id: str) -> dict[str, Any] | None:
    meta = get_strategy_meta(strategy_id)
    return strategy_meta_for_api(meta) if meta else None
