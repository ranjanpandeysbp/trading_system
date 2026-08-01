"""
pro_trade_shared.py
---------------------
Shared confluence-scoring and risk-conversion helpers for the Pro Trade
engines (Volume Profile CE, Volume Profile POC, PA + Volume Profile,
PA-VP-SMC) — kept in one place so every "actionable trade" across Pro Trade
carries a real, multi-factor confidence_pct instead of a flat/binary signal,
plus consistent sl_pct/tp_pct/hold_duration fields matching the rest of the
app's engines.
"""

from __future__ import annotations

import pandas as pd


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=max(2, period // 2)).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-12)
    return 100 - (100 / (1 + rs))


def ema(close: pd.Series, period: int) -> pd.Series:
    return close.ewm(span=period, adjust=False).mean()


def volume_zscore(volume: pd.Series, window: int = 20) -> pd.Series:
    mean = volume.rolling(window, min_periods=max(3, window // 3)).mean()
    std = volume.rolling(window, min_periods=max(3, window // 3)).std()
    return (volume - mean) / std.replace(0, pd.NA)


class ConfidenceScore:
    """Accumulates a confluence-weighted confidence score (10-95 clamp) and
    the human-readable reasons behind it — every point added is explained,
    so the final score is auditable, not a black box."""

    def __init__(self, base: float, base_reason: str):
        self.score = base
        self.reasons: list[str] = [base_reason]

    def add(self, condition: bool, points: float, reason_true: str, reason_false: str | None = None) -> "ConfidenceScore":
        if condition:
            self.score += points
            self.reasons.append(f"+{points:.0f}: {reason_true}")
        elif reason_false:
            self.reasons.append(reason_false)
        return self

    def finalize(self, lo: float = 10.0, hi: float = 92.0) -> tuple[float, list[str]]:
        return round(max(lo, min(hi, self.score)), 1), self.reasons


def sl_tp_pct(direction: str, entry: float, stop_loss: float | None, target: float | None) -> tuple[float | None, float | None]:
    """Convert absolute stop/target prices to %-of-entry, direction-aware
    (a SHORT's stop is above entry, target below — sl_pct/tp_pct are always
    reported as positive magnitudes regardless of direction)."""
    if not entry:
        return None, None
    sl_pct = round(abs(entry - stop_loss) / entry * 100, 3) if stop_loss is not None else None
    tp_pct = round(abs(target - entry) / entry * 100, 3) if target is not None else None
    return sl_pct, tp_pct


def rr_ratio(sl_pct: float | None, tp_pct: float | None) -> float | None:
    if not sl_pct or not tp_pct or sl_pct <= 0:
        return None
    return round(tp_pct / sl_pct, 2)
