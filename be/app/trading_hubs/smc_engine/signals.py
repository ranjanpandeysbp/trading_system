from __future__ import annotations

from typing import List, Optional

import pandas as pd

from .config import SMCConfig
from .models import Bias, FairValueGap, LiquiditySweep, OrderBlock, TradeSetup, TradeZone
from .zones import price_is_in_discount, price_is_in_ote, price_is_in_premium


def _leg_start_bar(df: pd.DataFrame, zone: TradeZone, leg_start_time: Optional[pd.Timestamp]) -> int:
    if leg_start_time is not None:
        for i in range(len(df)):
            if df.index[i] >= leg_start_time:
                return i
        return len(df)
    return min(zone.leg_start_index, zone.leg_end_index)


def generate_trade_setups(
    df: pd.DataFrame,
    zone: TradeZone,
    bias: Bias,
    fvgs: List[FairValueGap],
    order_blocks: List[OrderBlock],
    sweeps: List[LiquiditySweep],
    cfg: SMCConfig,
    *,
    leg_start_time: Optional[pd.Timestamp] = None,
) -> List[TradeSetup]:
    setups: List[TradeSetup] = []
    if zone is None or bias == Bias.NEUTRAL:
        return setups

    leg_start = _leg_start_bar(df, zone, leg_start_time)
    sweep_by_index = {s.index: s for s in sweeps if s.validated and s.index >= leg_start}
    fvgs = [g for g in fvgs if g.index >= leg_start]
    order_blocks = [o for o in order_blocks if o.index >= leg_start]

    for s in sweep_by_index.values():
        price = df["Close"].iloc[s.index]
        if bias == Bias.BULLISH and s.direction == "sell_side" and price_is_in_discount(price, zone):
            setups.append(TradeSetup(
                index=s.index, timestamp=s.timestamp, direction="long", htf_bias=bias,
                zone_type="OTE" if price_is_in_ote(price, zone) else "Discount",
                confirmation="validated sell-side liquidity sweep (CRT)",
                entry_price=price, invalidation_price=zone.leg_low,
            ))
        elif bias == Bias.BEARISH and s.direction == "buy_side" and price_is_in_premium(price, zone):
            setups.append(TradeSetup(
                index=s.index, timestamp=s.timestamp, direction="short", htf_bias=bias,
                zone_type="OTE" if price_is_in_ote(price, zone) else "Premium",
                confirmation="validated buy-side liquidity sweep (CRT)",
                entry_price=price, invalidation_price=zone.leg_high,
            ))

    for gap in fvgs:
        mid = gap.midpoint
        if bias == Bias.BULLISH and gap.bullish and price_is_in_discount(mid, zone):
            setups.append(TradeSetup(
                index=gap.index, timestamp=gap.timestamp, direction="long", htf_bias=bias,
                zone_type="OTE" if price_is_in_ote(mid, zone) else "Discount",
                confirmation="bullish Fair Value Gap inside HTF discount zone",
                entry_price=mid, invalidation_price=gap.floor,
            ))
        elif bias == Bias.BEARISH and not gap.bullish and price_is_in_premium(mid, zone):
            setups.append(TradeSetup(
                index=gap.index, timestamp=gap.timestamp, direction="short", htf_bias=bias,
                zone_type="OTE" if price_is_in_ote(mid, zone) else "Premium",
                confirmation="bearish Fair Value Gap inside HTF premium zone",
                entry_price=mid, invalidation_price=gap.ceiling,
            ))

    for ob in order_blocks:
        if ob.mitigated:
            continue
        mid = (ob.high + ob.low) / 2.0
        if bias == Bias.BULLISH and ob.bullish and price_is_in_discount(mid, zone):
            setups.append(TradeSetup(
                index=ob.index, timestamp=ob.timestamp, direction="long", htf_bias=bias,
                zone_type="OTE" if price_is_in_ote(mid, zone) else "Discount",
                confirmation="reaction at bullish (demand) Order Block",
                entry_price=mid, invalidation_price=ob.low,
            ))
        elif bias == Bias.BEARISH and not ob.bullish and price_is_in_premium(mid, zone):
            setups.append(TradeSetup(
                index=ob.index, timestamp=ob.timestamp, direction="short", htf_bias=bias,
                zone_type="OTE" if price_is_in_ote(mid, zone) else "Premium",
                confirmation="reaction at bearish (supply) Order Block",
                entry_price=mid, invalidation_price=ob.high,
            ))

    setups.sort(key=lambda s: s.index)
    return _dedupe_clustered(setups, min_gap=3)


def _dedupe_clustered(setups: List[TradeSetup], min_gap: int) -> List[TradeSetup]:
    deduped: List[TradeSetup] = []
    last_index_by_dir: dict[str, int] = {}
    for s in setups:
        last = last_index_by_dir.get(s.direction)
        if last is None or s.index - last > min_gap:
            deduped.append(s)
        last_index_by_dir[s.direction] = s.index
    return deduped
