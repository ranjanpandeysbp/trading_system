"""
top_down_mtf_engine.py
----------------------
Top-Down Multi-Timeframe Trading Strategy (SMC-Based).

  Step 1 — HTF: trend & key levels → directional bias
  Step 2 — MTF: CHoCH + Fair Value Gap / Order Block
  Step 3 — LTF: precise entry trigger with SL/TP
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.mtf_scanner_engine import MIN_BARS, TIMEFRAMES, normalize_ohlcv

TF_ORDER = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"]

PHASE_PRIORITY = {
    "ENTRY_READY": 100,
    "APPROACHING_LTF": 85,
    "MTF_SETUP": 70,
    "HTF_BIAS": 45,
    "NEUTRAL": 15,
    "NO_DATA": 0,
}


class Bias(Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class EntryTrigger(Enum):
    BULLISH_MARUBOZU = "Bullish Marubozu"
    BEARISH_MARUBOZU = "Bearish Marubozu"
    HAMMER = "Hammer / Pin Bar"
    MINI_CHOCH = "Mini CHoCH"
    NONE = "None"


@dataclass
class KeyLevel:
    price: float
    label: str


@dataclass
class FairValueGap:
    high: float
    low: float
    direction: Bias
    timeframe: str


@dataclass
class OrderBlock:
    high: float
    low: float
    direction: Bias
    timeframe: str


@dataclass
class TradeSetup:
    bias: Bias
    entry_price: float
    stop_loss: float
    take_profit: float
    trigger: EntryTrigger
    risk_reward: float = field(init=False)

    def __post_init__(self) -> None:
        risk = abs(self.entry_price - self.stop_loss)
        reward = abs(self.take_profit - self.entry_price)
        self.risk_reward = round(reward / risk, 2) if risk > 0 else 0.0


# ── Step 1 — HTF ────────────────────────────────────────────────────────────

def identify_trend(df: pd.DataFrame) -> Bias:
    highs = df["high"].values
    lows = df["low"].values
    n = len(highs)
    if n < 4:
        return Bias.NEUTRAL

    swing_highs = [
        highs[i] for i in range(1, n - 1)
        if highs[i] > highs[i - 1] and highs[i] > highs[i + 1]
    ]
    swing_lows = [
        lows[i] for i in range(1, n - 1)
        if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]
    ]

    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        hh = swing_highs[-1] > swing_highs[-2]
        hl = swing_lows[-1] > swing_lows[-2]
        lh = swing_highs[-1] < swing_highs[-2]
        ll = swing_lows[-1] < swing_lows[-2]
        if hh and hl:
            return Bias.BULLISH
        if lh and ll:
            return Bias.BEARISH
    return Bias.NEUTRAL


def _round_step(price: float, is_crypto: bool = False) -> float:
    if is_crypto:
        if price >= 10000:
            return 500.0
        if price >= 1000:
            return 50.0
        if price >= 100:
            return 5.0
        return 1.0
    if price >= 10000:
        return 500.0
    if price >= 1000:
        return 50.0
    return 10.0


def mark_key_levels(
    df: pd.DataFrame,
    round_number_step: float | None = None,
    is_crypto: bool = False,
) -> list[KeyLevel]:
    levels: list[KeyLevel] = []
    if df.empty:
        return levels

    work = df.copy()
    if not isinstance(work.index, pd.DatetimeIndex):
        try:
            work.index = pd.to_datetime(work.index)
        except Exception:
            pass

    today = work.index[-1].date()
    today_df = work[work.index.date == today]
    prev_df = work[work.index.date < today]

    if not today_df.empty:
        levels.append(KeyLevel(float(today_df["high"].max()), "Day High"))
        levels.append(KeyLevel(float(today_df["low"].min()), "Day Low"))

    if not prev_df.empty:
        prev_day = prev_df[prev_df.index.date == prev_df.index[-1].date()]
        if not prev_day.empty:
            levels.append(KeyLevel(float(prev_day["high"].max()), "PDH"))
            levels.append(KeyLevel(float(prev_day["low"].min()), "PDL"))

    price_range = work["close"].values
    lo, hi = float(price_range.min()), float(price_range.max())
    step = round_number_step or _round_step(float(work["close"].iloc[-1]), is_crypto)
    round_num = np.arange(
        np.floor(lo / step) * step,
        np.ceil(hi / step) * step + step,
        step,
    )
    for r in round_num:
        if lo <= r <= hi:
            levels.append(KeyLevel(float(r), f"Round ({r:.0f})"))
    return levels


def determine_bias(trend: Bias, current_price: float, key_levels: list[KeyLevel]) -> Bias:
    if trend == Bias.NEUTRAL:
        return Bias.NEUTRAL
    if not key_levels:
        return trend

    closest = min(key_levels, key=lambda lvl: abs(lvl.price - current_price))
    proximity_pct = abs(closest.price - current_price) / current_price if current_price else 1.0

    if proximity_pct <= 0.005:
        if trend == Bias.BULLISH and current_price >= closest.price:
            return Bias.BULLISH
        if trend == Bias.BEARISH and current_price <= closest.price:
            return Bias.BEARISH
    return trend


# ── Step 2 — MTF ────────────────────────────────────────────────────────────

def detect_choch(df: pd.DataFrame, bias: Bias) -> bool:
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    if len(closes) < 5:
        return False

    if bias == Bias.BULLISH:
        minor_swing_high = max(highs[-5:-1])
        return closes[-1] > minor_swing_high
    if bias == Bias.BEARISH:
        minor_swing_low = min(lows[-5:-1])
        return closes[-1] < minor_swing_low
    return False


def find_fvg(df: pd.DataFrame, bias: Bias, tf_label: str = "MTF") -> Optional[FairValueGap]:
    if len(df) < 3:
        return None

    for i in range(len(df) - 3, 0, -1):
        c0_high, c0_low = df["high"].iloc[i], df["low"].iloc[i]
        c2_high, c2_low = df["high"].iloc[i + 2], df["low"].iloc[i + 2]

        if bias == Bias.BULLISH and c2_low > c0_high:
            return FairValueGap(high=c2_low, low=c0_high, direction=Bias.BULLISH, timeframe=tf_label)
        if bias == Bias.BEARISH and c2_high < c0_low:
            return FairValueGap(high=c0_low, low=c2_high, direction=Bias.BEARISH, timeframe=tf_label)
    return None


def find_order_block(df: pd.DataFrame, bias: Bias, tf_label: str = "MTF") -> Optional[OrderBlock]:
    if len(df) < 3:
        return None

    bodies = df["close"] - df["open"]
    for i in range(len(df) - 2, 0, -1):
        candle_body = bodies.iloc[i]
        impulse_body = bodies.iloc[i + 1]

        if bias == Bias.BULLISH and candle_body < 0 and impulse_body > 0:
            return OrderBlock(
                high=df["high"].iloc[i], low=df["low"].iloc[i],
                direction=Bias.BULLISH, timeframe=tf_label,
            )
        if bias == Bias.BEARISH and candle_body > 0 and impulse_body < 0:
            return OrderBlock(
                high=df["high"].iloc[i], low=df["low"].iloc[i],
                direction=Bias.BEARISH, timeframe=tf_label,
            )
    return None


# ── Step 3 — LTF ──────────────────────────────────────────────────────────────

def is_price_in_zone(
    price: float, zone_high: float, zone_low: float, buffer_pct: float = 0.001,
) -> bool:
    buf = (zone_high - zone_low) * buffer_pct
    return (zone_low - buf) <= price <= (zone_high + buf)


def _distance_to_zone_pct(price: float, zone_high: float, zone_low: float) -> float:
    if zone_low <= price <= zone_high:
        return 0.0
    if price > zone_high:
        return (price - zone_high) / price * 100
    return (zone_low - price) / price * 100


def detect_entry_trigger(df: pd.DataFrame, bias: Bias) -> EntryTrigger:
    if df.empty:
        return EntryTrigger.NONE

    last = df.iloc[-1]
    o, h, l, c = last["open"], last["high"], last["low"], last["close"]
    body = abs(c - o)
    candle = h - l
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l

    if candle == 0:
        return EntryTrigger.NONE

    body_ratio = body / candle
    lower_wick_ratio = lower_wick / candle
    upper_wick_ratio = upper_wick / candle

    if body_ratio >= 0.80:
        if bias == Bias.BULLISH and c > o:
            return EntryTrigger.BULLISH_MARUBOZU
        if bias == Bias.BEARISH and c < o:
            return EntryTrigger.BEARISH_MARUBOZU

    if bias == Bias.BULLISH and lower_wick_ratio >= 0.55 and body_ratio <= 0.30:
        return EntryTrigger.HAMMER
    if bias == Bias.BEARISH and upper_wick_ratio >= 0.55 and body_ratio <= 0.30:
        return EntryTrigger.HAMMER

    if len(df) >= 5:
        closes = df["close"].values
        if bias == Bias.BULLISH and closes[-1] > max(closes[-5:-1]):
            return EntryTrigger.MINI_CHOCH
        if bias == Bias.BEARISH and closes[-1] < min(closes[-5:-1]):
            return EntryTrigger.MINI_CHOCH
    return EntryTrigger.NONE


def calculate_sl_tp(
    bias: Bias,
    entry: float,
    zone_high: float,
    zone_low: float,
    htf_target: float,
    sl_buffer_pct: float = 0.001,
) -> tuple[float, float]:
    buf = (zone_high - zone_low) * sl_buffer_pct
    if bias == Bias.BULLISH:
        sl = zone_low - buf
        tp = htf_target
    else:
        sl = zone_high + buf
        tp = htf_target
    return round(sl, 4), round(tp, 4)


# ── Mistake validators ────────────────────────────────────────────────────────

def validate_no_timeframe_mismatch(ltf_signal: Bias, htf_bias: Bias) -> bool:
    return ltf_signal == htf_bias or htf_bias == Bias.NEUTRAL


def validate_mtf_setup_exists(choch: bool, zone: Any) -> bool:
    return bool(choch and zone is not None)


def validate_htf_level_clear(
    entry: float, key_levels: list[KeyLevel], bias: Bias, buffer_pct: float = 0.003,
) -> bool:
    for kl in key_levels:
        dist = abs(kl.price - entry) / entry if entry else 1.0
        if dist <= buffer_pct:
            if bias == Bias.BULLISH and kl.price > entry:
                return False
            if bias == Bias.BEARISH and kl.price < entry:
                return False
    return True


# ── Confidence & phase ────────────────────────────────────────────────────────

def _compute_confidence(
    *,
    trend: Bias,
    bias: Bias,
    choch: bool,
    zone: Any,
    in_zone: bool,
    trigger: EntryTrigger,
    zone_distance_pct: float,
    validators_ok: bool,
) -> float:
    score = 0.0
    if trend != Bias.NEUTRAL:
        score += 12
    if bias != Bias.NEUTRAL:
        score += 18
    if choch:
        score += 22
    if zone is not None:
        score += 18
    if in_zone:
        score += 12
    elif zone is not None and zone_distance_pct <= 0.35:
        score += 8
    if trigger != EntryTrigger.NONE:
        score += 18
    if not validators_ok:
        score *= 0.65
    return round(min(100.0, max(0.0, score)), 1)


def _determine_phase(
    bias: Bias,
    choch: bool,
    zone: Any,
    in_zone: bool,
    trigger: EntryTrigger,
    zone_distance_pct: float,
) -> tuple[str, str]:
    if bias == Bias.NEUTRAL:
        return "NEUTRAL", "No clear HTF bias — wait for structure"

    if not choch or zone is None:
        return "HTF_BIAS", f"HTF {bias.value} bias — waiting for MTF CHoCH + FVG/OB"

    if trigger != EntryTrigger.NONE and in_zone:
        return "ENTRY_READY", f"LTF entry confirmed — {trigger.value}"

    if in_zone and trigger == EntryTrigger.NONE:
        return "APPROACHING_LTF", "Price in zone — waiting for LTF trigger candle"

    if zone_distance_pct <= 0.5:
        return "APPROACHING_LTF", f"Price within {zone_distance_pct:.2f}% of setup zone — retest approaching"

    return "MTF_SETUP", "MTF CHoCH + zone identified — wait for LTF retest"


def _hold_duration(ltf_tf: str) -> str:
    return TIMEFRAMES.get(ltf_tf, {}).get("hold", "15 min – 2 hours")


def _zone_dict(zone: FairValueGap | OrderBlock | None) -> dict | None:
    if zone is None:
        return None
    kind = "FVG" if isinstance(zone, FairValueGap) else "Order Block"
    return {
        "type": kind,
        "high": round(zone.high, 4),
        "low": round(zone.low, 4),
        "direction": zone.direction.value,
        "timeframe": zone.timeframe,
    }


# ── Data fetch ────────────────────────────────────────────────────────────────

def fetch_td_data(
    symbol: str,
    tf: str,
    market: str,
    groww_token: str = "",
    exchange: str = "NSE",
    limit: int = 300,
) -> pd.DataFrame:
    df = fetch_data_for_gap_scan(symbol, tf, market, groww_token, exchange, limit=limit)
    return normalize_ohlcv(df).tail(limit)


# ── Master runner ─────────────────────────────────────────────────────────────

class TopDownStrategy:
    def __init__(
        self,
        htf_df: pd.DataFrame,
        mtf_df: pd.DataFrame,
        ltf_df: pd.DataFrame,
        *,
        htf_tf: str = "15m",
        mtf_tf: str = "5m",
        ltf_tf: str = "1m",
        round_number_step: float | None = None,
        is_crypto: bool = False,
    ):
        self.htf_df = htf_df
        self.mtf_df = mtf_df
        self.ltf_df = ltf_df
        self.htf_tf = htf_tf
        self.mtf_tf = mtf_tf
        self.ltf_tf = ltf_tf
        self.round_number_step = round_number_step
        self.is_crypto = is_crypto

    @staticmethod
    def _validate_df(df: pd.DataFrame, name: str) -> None:
        required = {"open", "high", "low", "close"}
        if not required.issubset(df.columns):
            raise ValueError(f"{name} DataFrame must have columns: {required}")

    def run(self) -> dict[str, Any]:
        for df, name in [(self.htf_df, "HTF"), (self.mtf_df, "MTF"), (self.ltf_df, "LTF")]:
            self._validate_df(df, name)

        mtf_label = TIMEFRAMES.get(self.mtf_tf, {}).get("label", self.mtf_tf)

        trend = identify_trend(self.htf_df)
        key_levels = mark_key_levels(
            self.htf_df, self.round_number_step, is_crypto=self.is_crypto,
        )
        curr_price = float(self.htf_df["close"].iloc[-1])
        bias = determine_bias(trend, curr_price, key_levels)

        choch = detect_choch(self.mtf_df, bias) if bias != Bias.NEUTRAL else False
        fvg = find_fvg(self.mtf_df, bias, mtf_label) if bias != Bias.NEUTRAL else None
        ob = find_order_block(self.mtf_df, bias, mtf_label) if bias != Bias.NEUTRAL else None
        zone = fvg or ob

        ltf_price = float(self.ltf_df["close"].iloc[-1])
        in_zone = False
        zone_distance_pct = 999.0
        trigger = EntryTrigger.NONE

        if zone is not None:
            in_zone = is_price_in_zone(ltf_price, zone.high, zone.low)
            zone_distance_pct = _distance_to_zone_pct(ltf_price, zone.high, zone.low)
            trigger = detect_entry_trigger(self.ltf_df, bias) if in_zone else EntryTrigger.NONE

        validators_ok = (
            validate_no_timeframe_mismatch(bias, bias)
            and validate_mtf_setup_exists(choch, zone)
            and (bias == Bias.NEUTRAL or validate_htf_level_clear(ltf_price, key_levels, bias))
        )

        confidence = _compute_confidence(
            trend=trend,
            bias=bias,
            choch=choch,
            zone=zone,
            in_zone=in_zone,
            trigger=trigger,
            zone_distance_pct=zone_distance_pct,
            validators_ok=validators_ok,
        )

        phase, message = _determine_phase(bias, choch, zone, in_zone, trigger, zone_distance_pct)

        trade_setup: dict | None = None
        setup: TradeSetup | None = None

        if (
            bias != Bias.NEUTRAL
            and choch
            and zone is not None
            and in_zone
            and trigger != EntryTrigger.NONE
            and validators_ok
        ):
            if bias == Bias.BULLISH:
                targets = [kl.price for kl in key_levels if kl.price > ltf_price]
                htf_target = min(targets) if targets else ltf_price * 1.01
            else:
                targets = [kl.price for kl in key_levels if kl.price < ltf_price]
                htf_target = max(targets) if targets else ltf_price * 0.99

            sl, tp = calculate_sl_tp(bias, ltf_price, zone.high, zone.low, htf_target)
            setup = TradeSetup(
                bias=bias,
                entry_price=round(ltf_price, 4),
                stop_loss=sl,
                take_profit=tp,
                trigger=trigger,
            )
            risk_pct = abs(setup.entry_price - setup.stop_loss) / setup.entry_price * 100
            reward_pct = abs(setup.take_profit - setup.entry_price) / setup.entry_price * 100
            trade_setup = {
                "direction": "LONG" if bias == Bias.BULLISH else "SHORT",
                "entry": setup.entry_price,
                "stop_loss": setup.stop_loss,
                "take_profit": setup.take_profit,
                "sl_pct": round(risk_pct, 2),
                "tp_pct": round(reward_pct, 2),
                "rr_ratio": setup.risk_reward,
                "trigger": trigger.value,
                "hold_duration": _hold_duration(self.ltf_tf),
            }

        elif bias != Bias.NEUTRAL and zone is not None:
            # Projective plan for approaching setups
            proj_entry = ltf_price
            if bias == Bias.BULLISH:
                targets = [kl.price for kl in key_levels if kl.price > proj_entry]
                htf_target = min(targets) if targets else proj_entry * 1.008
            else:
                targets = [kl.price for kl in key_levels if kl.price < proj_entry]
                htf_target = max(targets) if targets else proj_entry * 0.992
            sl, tp = calculate_sl_tp(bias, proj_entry, zone.high, zone.low, htf_target)
            risk_pct = abs(proj_entry - sl) / proj_entry * 100 if proj_entry else 0
            reward_pct = abs(tp - proj_entry) / proj_entry * 100 if proj_entry else 0
            trade_setup = {
                "direction": "LONG" if bias == Bias.BULLISH else "SHORT",
                "entry": round(proj_entry, 4),
                "stop_loss": sl,
                "take_profit": tp,
                "sl_pct": round(risk_pct, 2),
                "tp_pct": round(reward_pct, 2),
                "rr_ratio": round(reward_pct / risk_pct, 2) if risk_pct > 0 else 0,
                "trigger": trigger.value if trigger != EntryTrigger.NONE else "Pending",
                "hold_duration": _hold_duration(self.ltf_tf),
                "projected": True,
            }

        return {
            "symbol": None,
            "htf_tf": self.htf_tf,
            "mtf_tf": self.mtf_tf,
            "ltf_tf": self.ltf_tf,
            "htf_label": TIMEFRAMES.get(self.htf_tf, {}).get("label", self.htf_tf),
            "mtf_label": mtf_label,
            "ltf_label": TIMEFRAMES.get(self.ltf_tf, {}).get("label", self.ltf_tf),
            "price": curr_price,
            "ltf_price": ltf_price,
            "step1": {
                "trend": trend.value,
                "bias": bias.value,
                "key_levels": [{"label": kl.label, "price": round(kl.price, 4)} for kl in key_levels[:12]],
            },
            "step2": {
                "choch": choch,
                "fvg": _zone_dict(fvg),
                "order_block": _zone_dict(ob),
                "zone": _zone_dict(zone),
                "zone_distance_pct": round(zone_distance_pct, 3),
            },
            "step3": {
                "in_zone": in_zone,
                "trigger": trigger.value,
            },
            "phase": phase,
            "primary_label": message,
            "priority": PHASE_PRIORITY.get(phase, 0),
            "confidence": confidence,
            "validators_ok": validators_ok,
            "trade_plan": trade_setup,
            "actionable": phase in ("ENTRY_READY", "APPROACHING_LTF", "MTF_SETUP"),
        }


def analyze_top_down(
    symbol: str,
    htf_tf: str,
    mtf_tf: str,
    ltf_tf: str,
    market: str,
    groww_token: str = "",
    exchange: str = "NSE",
    limit: int = 300,
    round_number_step: float | None = None,
) -> dict[str, Any]:
    """Fetch HTF/MTF/LTF data and run the top-down SMC strategy for one ticker."""
    is_crypto = "CoinDCX" in market

    htf_df = fetch_td_data(symbol, htf_tf, market, groww_token, exchange, limit)
    mtf_df = fetch_td_data(symbol, mtf_tf, market, groww_token, exchange, limit)
    ltf_df = fetch_td_data(symbol, ltf_tf, market, groww_token, exchange, limit)

    min_needed = max(20, MIN_BARS // 2)
    errors = []
    if len(htf_df) < min_needed:
        errors.append(f"HTF ({htf_tf}): {len(htf_df)} bars")
    if len(mtf_df) < min_needed:
        errors.append(f"MTF ({mtf_tf}): {len(mtf_df)} bars")
    if len(ltf_df) < min_needed:
        errors.append(f"LTF ({ltf_tf}): {len(ltf_df)} bars")

    if errors:
        return {
            "symbol": symbol,
            "error": f"Insufficient data — {', '.join(errors)}",
            "phase": "NO_DATA",
            "priority": 0,
            "confidence": 0,
            "actionable": False,
        }

    try:
        engine = TopDownStrategy(
            htf_df, mtf_df, ltf_df,
            htf_tf=htf_tf,
            mtf_tf=mtf_tf,
            ltf_tf=ltf_tf,
            round_number_step=round_number_step,
            is_crypto=is_crypto,
        )
        result = engine.run()
        result["symbol"] = symbol
        return result
    except Exception as exc:
        return {
            "symbol": symbol,
            "error": str(exc)[:200],
            "phase": "NO_DATA",
            "priority": 0,
            "confidence": 0,
            "actionable": False,
        }
