from collections.abc import Callable
from typing import Any

from app.strategies.catalog import CATEGORY_DESCRIPTIONS, STRATEGY_DETAILS
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
    return STRATEGY_MIN_BARS.get(name, 30)


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


def list_categories() -> list[dict[str, Any]]:
    categories = []
    for cat_id, info in STRATEGY_CATEGORIES.items():
        strategies = [STRATEGY_META[sid] for sid in info["strategies"]]
        categories.append({
            "id": cat_id,
            "label": info["label"],
            "description": CATEGORY_DESCRIPTIONS.get(cat_id, ""),
            "timeframes": info["timeframes"],
            "strategy_count": len(strategies),
            "strategies": strategies,
        })
    return categories
