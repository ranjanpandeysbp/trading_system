"""
vol_regime.py
-------------
Shared volatility-regime layer — a single ATR%-percentile-rank field that
lets every scanning engine condition on "is this volatile *for this
instrument*" instead of comparing fixed absolute thresholds (ADX>=25,
RSI>70, a flat 1:2 reward:risk...) that mean something different in a
4%-ATR index and a 15%-ATR small-cap held to the same yardstick.

Rank, not raw ATR%, is the point: a stock's own trailing history is the
fairest baseline for "unusually calm/choppy right now," since it already
nets out the instrument's typical volatility level.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from app.market_pulse.indicators import add_atr

_DEFAULT_PERIOD = 14
_DEFAULT_LOOKBACK = 100


@dataclass
class VolRegimeReading:
    atr_pct: float          # ATR / close, as a percent, at the latest closed bar
    atr_pct_rank: float     # percentile rank (0-100) of atr_pct vs its own trailing history
    regime: str             # LOW / NORMAL / HIGH / EXTREME
    rr_multiplier: float    # scale a nominal reward:risk ratio for this regime
    size_multiplier: float  # scale a nominal position size for this regime


def _classify(rank: float) -> str:
    if rank >= 90:
        return "EXTREME"
    if rank >= 65:
        return "HIGH"
    if rank >= 25:
        return "NORMAL"
    return "LOW"


# In blow-off/panic conditions (EXTREME), trends exhaust fast — holding out
# for a wide target is how a winning trade round-trips into a loser, so R:R
# tightens even though the stop itself sits wider in price terms. LOW-vol
# grinding trends are the regime most worth letting run.
_RR_MULT = {"LOW": 1.25, "NORMAL": 1.0, "HIGH": 0.9, "EXTREME": 0.7}

# Higher realized vol -> smaller size for the same % account risk, since the
# stop has to sit farther away in price terms to avoid noise stop-outs.
_SIZE_MULT = {"LOW": 1.15, "NORMAL": 1.0, "HIGH": 0.75, "EXTREME": 0.5}


def compute_vol_regime(
    df: pd.DataFrame, *, period: int = _DEFAULT_PERIOD, lookback: int = _DEFAULT_LOOKBACK,
) -> VolRegimeReading | None:
    """Read the latest bar's ATR% and percentile-rank it against its own
    trailing history. Returns None if there isn't enough data to judge
    (callers should treat that as "assume NORMAL," not as an error)."""
    if df is None or df.empty or len(df) < period + 5 or "close" not in df.columns:
        return None
    work = df.copy()
    atr_col = f"atr_{period}"
    if atr_col not in work.columns:
        work = add_atr(work, period)

    atr_pct_series = (work[atr_col] / work["close"].replace(0, pd.NA)) * 100.0
    atr_pct_series = atr_pct_series.dropna()
    if atr_pct_series.empty:
        return None

    window = atr_pct_series.tail(lookback)
    latest = float(atr_pct_series.iloc[-1])
    if len(window) < 10:
        rank = 50.0  # not enough history to judge — default to NORMAL
    else:
        rank = float((window <= latest).sum()) / len(window) * 100.0

    regime = _classify(rank)
    return VolRegimeReading(
        atr_pct=round(latest, 3),
        atr_pct_rank=round(rank, 1),
        regime=regime,
        rr_multiplier=_RR_MULT[regime],
        size_multiplier=_SIZE_MULT[regime],
    )
