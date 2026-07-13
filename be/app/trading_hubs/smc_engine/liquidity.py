from __future__ import annotations

from typing import List

import pandas as pd

from .config import SMCConfig
from .models import LiquiditySweep


def detect_crt_sweeps(df: pd.DataFrame, cfg: SMCConfig) -> List[LiquiditySweep]:
    sweeps: List[LiquiditySweep] = []
    highs, lows, closes = df["High"].values, df["Low"].values, df["Close"].values

    for i in range(cfg.crt_lookback, len(df)):
        ref = i - cfg.crt_lookback
        ref_high, ref_low = highs[ref], lows[ref]

        if lows[i] < ref_low and closes[i] >= ref_low:
            sweeps.append(LiquiditySweep(i, df.index[i], swept_level=ref_low, direction="sell_side", validated=True))
        elif lows[i] < ref_low and closes[i] < ref_low:
            sweeps.append(LiquiditySweep(i, df.index[i], swept_level=ref_low, direction="sell_side", validated=False))

        if highs[i] > ref_high and closes[i] <= ref_high:
            sweeps.append(LiquiditySweep(i, df.index[i], swept_level=ref_high, direction="buy_side", validated=True))
        elif highs[i] > ref_high and closes[i] > ref_high:
            sweeps.append(LiquiditySweep(i, df.index[i], swept_level=ref_high, direction="buy_side", validated=False))

    return sweeps
