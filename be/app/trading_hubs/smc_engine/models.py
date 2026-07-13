from dataclasses import dataclass
from enum import Enum
from typing import Optional


class SwingType(Enum):
    HIGH = "swing_high"
    LOW = "swing_low"


class StructureEvent(Enum):
    BOS_BULL = "bullish_break_of_structure"
    BOS_BEAR = "bearish_break_of_structure"
    CHOCH_BULL = "bullish_change_of_character"
    CHOCH_BEAR = "bearish_change_of_character"


class Bias(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


@dataclass
class Swing:
    index: int
    timestamp: object
    price: float
    kind: SwingType


@dataclass
class StructureBreak:
    index: int
    timestamp: object
    price: float
    event: StructureEvent
    reference_swing: Swing


@dataclass
class FairValueGap:
    index: int
    timestamp: object
    floor: float
    ceiling: float
    bullish: bool
    mitigated: bool = False
    mitigated_index: Optional[int] = None

    @property
    def midpoint(self) -> float:
        return (self.floor + self.ceiling) / 2.0


@dataclass
class OrderBlock:
    index: int
    timestamp: object
    high: float
    low: float
    bullish: bool
    impulse_index: int
    mitigated: bool = False


@dataclass
class LiquiditySweep:
    index: int
    timestamp: object
    swept_level: float
    direction: str
    validated: bool


@dataclass
class TradeZone:
    leg_low: float
    leg_high: float
    equilibrium: float
    ote_shallow: float
    ote_sweet_spot: float
    ote_deep: float
    bullish_leg: bool
    leg_start_index: int = 0
    leg_end_index: int = 0

    def discount_zone(self):
        return (self.leg_low, self.equilibrium)

    def premium_zone(self):
        return (self.equilibrium, self.leg_high)

    def ote_zone(self):
        lo, hi = sorted([self.ote_shallow, self.ote_deep])
        return (lo, hi)


@dataclass
class TradeSetup:
    index: int
    timestamp: object
    direction: str
    htf_bias: Bias
    zone_type: str
    confirmation: str
    entry_price: float
    invalidation_price: float
    notes: str = ""
