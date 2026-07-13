from __future__ import annotations

from typing import List, Optional

from .config import SMCConfig
from .models import Swing, SwingType, TradeZone


def latest_impulse_leg(swings: List[Swing]) -> Optional[tuple[Swing, Swing]]:
    if len(swings) < 2:
        return None
    return swings[-2], swings[-1]


def build_trade_zone(swings: List[Swing], cfg: SMCConfig) -> Optional[TradeZone]:
    leg = latest_impulse_leg(swings)
    if leg is None:
        return None
    a, b = leg
    bullish_leg = a.kind == SwingType.LOW and b.kind == SwingType.HIGH
    bearish_leg = a.kind == SwingType.HIGH and b.kind == SwingType.LOW
    if not (bullish_leg or bearish_leg):
        return None

    leg_low = min(a.price, b.price)
    leg_high = max(a.price, b.price)
    leg_range = leg_high - leg_low
    if leg_range <= 0:
        return None

    equilibrium = leg_low + leg_range * cfg.equilibrium_pct
    if bullish_leg:
        ote_shallow = leg_high - leg_range * cfg.ote_shallow_pct
        ote_sweet = leg_high - leg_range * cfg.ote_sweet_spot_pct
        ote_deep = leg_high - leg_range * cfg.ote_deep_pct
    else:
        ote_shallow = leg_low + leg_range * cfg.ote_shallow_pct
        ote_sweet = leg_low + leg_range * cfg.ote_sweet_spot_pct
        ote_deep = leg_low + leg_range * cfg.ote_deep_pct

    return TradeZone(
        leg_low=leg_low,
        leg_high=leg_high,
        equilibrium=equilibrium,
        ote_shallow=ote_shallow,
        ote_sweet_spot=ote_sweet,
        ote_deep=ote_deep,
        bullish_leg=bullish_leg,
        leg_start_index=a.index,
        leg_end_index=b.index,
    )


def price_is_in_discount(price: float, zone: TradeZone) -> bool:
    return price < zone.equilibrium


def price_is_in_premium(price: float, zone: TradeZone) -> bool:
    return price > zone.equilibrium


def price_is_in_ote(price: float, zone: TradeZone) -> bool:
    lo, hi = zone.ote_zone()
    return lo <= price <= hi
