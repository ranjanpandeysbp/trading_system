import numpy as np
import pandas as pd

from app.strategies.backtest import backtest_signals
from app.strategies.indicators import atr, rsi


def compute_sl_tp(df: pd.DataFrame, signal: int, category: str) -> tuple[float, float]:
    """ATR-based stop-loss and take-profit as percentages."""
    atr_series = atr(df)
    last_atr = float(atr_series.iloc[-1]) if not atr_series.empty else 0
    price = float(df["close"].iloc[-1])
    atr_pct = (last_atr / price * 100) if price > 0 else 1.0

    multipliers = {
        "scalping": (1.0, 1.8),
        "intraday": (1.5, 2.5),
        "swing": (2.0, 4.0),
    }
    sl_mult, tp_mult = multipliers.get(category, (1.5, 2.5))
    sl_pct = round(max(0.3, atr_pct * sl_mult), 2)
    tp_pct = round(max(sl_pct * 1.5, atr_pct * tp_mult), 2)
    return sl_pct, tp_pct


def compute_confidence(
    df: pd.DataFrame,
    signal: int,
    strategy_label: str,
    category: str,
    mini_backtest_win_rate: float | None = None,
) -> tuple[float, str]:
    """Derive confidence from volume, RSI, signal recency, and mini-backtest."""
    price = float(df["close"].iloc[-1])
    vol = df["volume"]
    vol_ratio = float(vol.iloc[-1] / vol.rolling(20, min_periods=1).mean().iloc[-1]) if len(vol) else 1.0
    rsi_val = float(rsi(df["close"]).iloc[-1])

    base = 45.0
    if signal == 1:
        rsi_boost = max(0, min(15, (50 - rsi_val) * 0.5)) if rsi_val < 50 else max(0, min(10, (70 - rsi_val) * 0.3))
    elif signal == -1:
        rsi_boost = max(0, min(15, (rsi_val - 50) * 0.5)) if rsi_val > 50 else max(0, min(10, (rsi_val - 30) * 0.3))
    else:
        rsi_boost = 0

    vol_boost = min(20, max(0, (vol_ratio - 1) * 15))
    category_boost = {"scalping": 5, "intraday": 8, "swing": 12}.get(category, 5)
    backtest_boost = 0.0
    if mini_backtest_win_rate is not None and not np.isnan(mini_backtest_win_rate):
        backtest_boost = min(20, max(-10, (mini_backtest_win_rate - 50) * 0.4))

    confidence = base + rsi_boost + vol_boost + category_boost + backtest_boost
    confidence = round(min(95, max(25, confidence)), 1)

    action = "buy" if signal == 1 else "sell"
    rationale = (
        f"{strategy_label} triggered {action} on latest bar. "
        f"RSI={rsi_val:.1f}, volume {vol_ratio:.1f}x avg"
    )
    if mini_backtest_win_rate is not None:
        rationale += f", recent win rate {mini_backtest_win_rate:.0f}%"
    return confidence, rationale


def enrich_signal(
    df: pd.DataFrame,
    signal: int,
    strategy_label: str,
    category: str,
    costs_pct: float = 0.0008,
) -> dict:
    sl_pct, tp_pct = compute_sl_tp(df, signal, category)
    mini_stats = backtest_signals(df.tail(min(500, len(df))), costs_pct=costs_pct)
    win_rate = mini_stats.get("win_rate_pct")
    confidence, rationale = compute_confidence(df, signal, strategy_label, category, win_rate)
    return {
        "sl_pct": sl_pct,
        "tp_pct": tp_pct,
        "confidence_pct": confidence,
        "rationale": rationale,
    }
