from __future__ import annotations

from typing import List

import pandas as pd

from .models import Bias, StructureBreak, StructureEvent, Swing, SwingType


def find_fractal_swings(df: pd.DataFrame, window: int) -> List[Swing]:
    highs, lows = df["High"].values, df["Low"].values
    n = len(df)
    raw: List[Swing] = []

    for i in range(window, n - window):
        local_high = highs[i - window : i + window + 1]
        local_low = lows[i - window : i + window + 1]
        if highs[i] == local_high.max():
            raw.append(Swing(i, df.index[i], highs[i], SwingType.HIGH))
        if lows[i] == local_low.min():
            raw.append(Swing(i, df.index[i], lows[i], SwingType.LOW))

    raw.sort(key=lambda s: s.index)
    cleaned: List[Swing] = []
    for s in raw:
        if cleaned and cleaned[-1].kind == s.kind:
            if s.kind == SwingType.HIGH and s.price > cleaned[-1].price:
                cleaned[-1] = s
            elif s.kind == SwingType.LOW and s.price < cleaned[-1].price:
                cleaned[-1] = s
        else:
            cleaned.append(s)
    return cleaned


def detect_structure_breaks(df: pd.DataFrame, swings: List[Swing]) -> List[StructureBreak]:
    breaks: List[StructureBreak] = []
    if len(swings) < 2:
        return breaks

    bias = Bias.NEUTRAL
    last_high = next((s for s in swings if s.kind == SwingType.HIGH), None)
    last_low = next((s for s in swings if s.kind == SwingType.LOW), None)
    swing_cursor = 0
    closes = df["Close"].values

    for i in range(len(df)):
        while swing_cursor < len(swings) and swings[swing_cursor].index <= i:
            s = swings[swing_cursor]
            if s.kind == SwingType.HIGH:
                last_high = s
            else:
                last_low = s
            swing_cursor += 1

        if last_high is not None and closes[i] > last_high.price:
            event = StructureEvent.BOS_BULL if bias in (Bias.BULLISH, Bias.NEUTRAL) else StructureEvent.CHOCH_BULL
            breaks.append(StructureBreak(i, df.index[i], closes[i], event, last_high))
            bias = Bias.BULLISH
            last_high = Swing(i, df.index[i], closes[i], SwingType.HIGH)

        elif last_low is not None and closes[i] < last_low.price:
            event = StructureEvent.BOS_BEAR if bias in (Bias.BEARISH, Bias.NEUTRAL) else StructureEvent.CHOCH_BEAR
            breaks.append(StructureBreak(i, df.index[i], closes[i], event, last_low))
            bias = Bias.BEARISH
            last_low = Swing(i, df.index[i], closes[i], SwingType.LOW)

    return breaks


def current_bias(breaks: List[StructureBreak]) -> Bias:
    if not breaks:
        return Bias.NEUTRAL
    last = breaks[-1].event
    return Bias.BULLISH if last in (StructureEvent.BOS_BULL, StructureEvent.CHOCH_BULL) else Bias.BEARISH
