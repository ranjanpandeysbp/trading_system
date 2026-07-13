from __future__ import annotations

from typing import List

import pandas as pd

from .config import SMCConfig
from .models import FairValueGap, OrderBlock


def detect_fvgs(df: pd.DataFrame, cfg: SMCConfig) -> List[FairValueGap]:
    fvgs: List[FairValueGap] = []
    highs, lows = df["High"].values, df["Low"].values
    ref_price = float(df["Close"].iloc[0])
    min_size = cfg.min_fvg_size_pct * ref_price

    for i in range(1, len(df) - 1):
        if lows[i + 1] > highs[i - 1] and (lows[i + 1] - highs[i - 1]) >= min_size:
            fvgs.append(FairValueGap(i, df.index[i], floor=highs[i - 1], ceiling=lows[i + 1], bullish=True))
        elif highs[i + 1] < lows[i - 1] and (lows[i - 1] - highs[i + 1]) >= min_size:
            fvgs.append(FairValueGap(i, df.index[i], floor=highs[i + 1], ceiling=lows[i - 1], bullish=False))

    mark_fvg_mitigation(df, fvgs)
    return fvgs


def mark_fvg_mitigation(df: pd.DataFrame, fvgs: List[FairValueGap]) -> None:
    lows, highs = df["Low"].values, df["High"].values
    for gap in fvgs:
        for j in range(gap.index + 2, len(df)):
            if lows[j] <= gap.ceiling and highs[j] >= gap.floor:
                gap.mitigated = True
                gap.mitigated_index = j
                break


def _atr(df: pd.DataFrame, window: int) -> pd.Series:
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window, min_periods=1).mean()


def detect_order_blocks(df: pd.DataFrame, cfg: SMCConfig) -> List[OrderBlock]:
    atr = _atr(df, cfg.displacement_atr_window)
    ranges = df["High"] - df["Low"]
    opens, closes = df["Open"].values, df["Close"].values
    order_blocks: List[OrderBlock] = []

    for i in range(1, len(df)):
        if ranges.iloc[i] <= atr.iloc[i] * cfg.displacement_multiplier:
            continue
        impulse_bullish = closes[i] > opens[i]
        prev_idx = i - 1
        prev_bullish = closes[prev_idx] > opens[prev_idx]
        if impulse_bullish and not prev_bullish:
            order_blocks.append(OrderBlock(
                index=prev_idx, timestamp=df.index[prev_idx],
                high=df["High"].iloc[prev_idx], low=df["Low"].iloc[prev_idx],
                bullish=True, impulse_index=i,
            ))
        elif not impulse_bullish and prev_bullish:
            order_blocks.append(OrderBlock(
                index=prev_idx, timestamp=df.index[prev_idx],
                high=df["High"].iloc[prev_idx], low=df["Low"].iloc[prev_idx],
                bullish=False, impulse_index=i,
            ))

    _mark_ob_mitigation(df, order_blocks)
    return order_blocks


def _mark_ob_mitigation(df: pd.DataFrame, blocks: List[OrderBlock]) -> None:
    lows, highs = df["Low"].values, df["High"].values
    for ob in blocks:
        for j in range(ob.impulse_index + 1, len(df)):
            if lows[j] <= ob.high and highs[j] >= ob.low:
                ob.mitigated = True
                break
