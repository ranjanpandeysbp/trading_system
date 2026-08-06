"""
stf_shop_backtest.py
--------------------
Single-ticker historical proxy for ETF Shop 4.0 (ETF TA IN).

Live ETF Shop is a *portfolio* rotator (rank many ETFs by cheapness vs
20 DMA, max 1 buy / 1 sell per day, SIP latch, FIFO profit booking).
The Backtester evaluates one ticker at a time, so this module approximates
the shop's per-name rules:

  1. Buy when price is below the 20 DMA (cheap vs average — Rank-1 spirit).
  2. Exit when either:
       - profit target from entry is hit (default 6%), or
       - price reclaims the 20 DMA after being long.
  3. Optional SIP-style add is *not* modeled as extra lots here; the
     signal frame is long-only with one position at a time.

Returns an OHLCV frame with ``signal`` in {-1, 0, 1} plus a ``trades``
list suitable for advanced report enrichment.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.etf_ta.stf_shop_engine import DMA_PERIOD, DEFAULT_PROFIT_TARGET_PCT
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv


def build_stf_shop_signals(
    df: pd.DataFrame,
    *,
    dma_period: int = DMA_PERIOD,
    profit_target_pct: float = DEFAULT_PROFIT_TARGET_PCT,
    costs_pct: float = 0.0008,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    work = normalize_ohlcv(df).copy()
    if work.empty or len(work) < dma_period + 5:
        if not work.empty:
            work["signal"] = 0
        return work, []

    close = work["close"].astype(float)
    sma = close.rolling(int(dma_period)).mean()
    work["sma20"] = sma
    work["pct_from_dma"] = (close - sma) / sma.replace(0, np.nan) * 100.0
    work["signal"] = 0

    signals = np.zeros(len(work), dtype=int)
    trades: list[dict[str, Any]] = []
    position = 0
    entry_price = 0.0
    entry_idx: Any = None

    for i in range(len(work)):
        px = float(close.iloc[i])
        dma = sma.iloc[i]
        if not np.isfinite(px) or not np.isfinite(dma) or dma <= 0:
            continue

        if position == 0:
            # Cheap vs 20 DMA → open long (shop Rank-1 spirit on one name)
            if px < dma:
                position = 1
                entry_price = px
                entry_idx = work.index[i]
                signals[i] = 1
            continue

        # In position — book profit at target or when price reclaims DMA
        ret_pct = (px - entry_price) / entry_price * 100.0
        reclaim = px >= dma
        hit_target = ret_pct >= float(profit_target_pct)
        if hit_target or reclaim:
            exit_px = px
            pnl_frac = (exit_px - entry_price) / entry_price - float(costs_pct)
            trades.append({
                "exit_time": str(work.index[i]),
                "entry_time": str(entry_idx),
                "side": "long",
                "pnl_pct": round(pnl_frac * 100.0, 3),
                "entry_price": round(entry_price, 4),
                "exit_price": round(exit_px, 4),
                "exit_reason": "target" if hit_target else "dma_reclaim",
            })
            signals[i] = -1
            position = 0
            entry_price = 0.0
            entry_idx = None

    work["signal"] = signals

    # Mark open trade at end of series for visibility (not counted as closed)
    if position == 1 and entry_idx is not None:
        last_px = float(close.iloc[-1])
        pnl_frac = (last_px - entry_price) / entry_price - float(costs_pct)
        trades.append({
            "exit_time": str(work.index[-1]),
            "entry_time": str(entry_idx),
            "side": "long (open)",
            "pnl_pct": round(pnl_frac * 100.0, 3),
            "entry_price": round(entry_price, 4),
            "exit_price": round(last_px, 4),
            "exit_reason": "open",
        })

    return work, trades
