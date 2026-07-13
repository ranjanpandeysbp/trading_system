from __future__ import annotations

import pandas as pd

from .config import SMCConfig


def resample_ohlc(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    out = df.resample(rule).agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"})
    return out.dropna()


def build_multi_timeframe(df_ltf: pd.DataFrame, cfg: SMCConfig) -> dict[str, pd.DataFrame]:
    return {
        "HTF": resample_ohlc(df_ltf, cfg.htf_rule),
        "MTF": resample_ohlc(df_ltf, cfg.mtf_rule),
        "LTF": df_ltf,
    }
