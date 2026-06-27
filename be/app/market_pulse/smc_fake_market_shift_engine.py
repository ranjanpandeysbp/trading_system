"""
smc_fake_market_shift_engine.py
---------------------------------
Smart Money Concepts — Fake Market Shift entry model.
Steps: market structure (BOS) → POI mapping → liquidity sweep → entry models A/B.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv

FMS_TF_OPTIONS = ["5m", "15m", "30m", "1h", "4h", "1d"]

PHASE_PRIORITY = {
    "ENTRY_READY": 100,
    "WATCH_SWEEP": 65,
    "STRUCTURE_ONLY": 40,
    "NO_SETUP": 15,
    "NO_DATA": 0,
}


class Trend(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class SwingLabel(Enum):
    HH = "HH"
    HL = "HL"
    LH = "LH"
    LL = "LL"
    H = "H"
    L = "L"


@dataclass
class SwingPoint:
    index: int
    timestamp: object
    price: float
    kind: str
    label: SwingLabel | None = None


@dataclass
class BOSEvent:
    index: int
    timestamp: object
    direction: Trend
    broken_swing: SwingPoint
    close_price: float


@dataclass
class POIZone:
    start_index: int
    end_index: int
    top: float
    bottom: float
    direction: Trend
    is_extreme: bool = True

    def contains(self, price: float, overshoot_pct: float = 0.5) -> bool:
        height = self.top - self.bottom
        lo = self.bottom - height * overshoot_pct
        hi = self.top + height * overshoot_pct
        return lo <= price <= hi


@dataclass
class LiquiditySweepEvent:
    index: int
    timestamp: object
    direction: Trend
    internal_high: SwingPoint
    internal_low: SwingPoint
    sweep_candle_index: int
    sweep_extreme_price: float


@dataclass
class TradeSignal:
    model: Literal["aggressive", "conservative"]
    direction: Trend
    entry_index: int
    entry_price: float
    stop_loss: float
    take_profit: float | None
    timestamp: object
    poi: POIZone | None = None
    notes: str = ""


@dataclass
class StrategyConfig:
    swing_left: int = 2
    swing_right: int = 2
    internal_left: int = 1
    internal_right: int = 1
    poi_lookahead: int = 80
    rr_aggressive: float = 2.0
    rr_conservative: float = 3.0
    max_fill_wait: int = 30
    max_trade_duration: int = 200
    live_lookback_bars: int = 25
    entry_model: Literal["both", "aggressive", "conservative"] = "both"


@dataclass
class TradeResult:
    signal: TradeSignal
    filled: bool
    fill_index: int | None
    outcome: Literal["tp", "sl", "open"] | None
    r_multiple: float | None


def find_fractal_swings(df: pd.DataFrame, left: int = 2, right: int = 2) -> list[SwingPoint]:
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    n = len(df)
    swings: list[SwingPoint] = []

    for i in range(left, n - right):
        window_high = highs[i - left: i + right + 1]
        if highs[i] >= window_high.max() and np.argmax(window_high) == left:
            swings.append(SwingPoint(index=i, timestamp=df.index[i], price=highs[i], kind="high"))

        window_low = lows[i - left: i + right + 1]
        if lows[i] <= window_low.min() and np.argmin(window_low) == left:
            swings.append(SwingPoint(index=i, timestamp=df.index[i], price=lows[i], kind="low"))

    swings.sort(key=lambda s: s.index)
    return swings


def reduce_to_zigzag(swings: list[SwingPoint]) -> list[SwingPoint]:
    if not swings:
        return []
    zz: list[SwingPoint] = [swings[0]]
    for s in swings[1:]:
        last = zz[-1]
        if s.kind == last.kind:
            if s.kind == "high" and s.price >= last.price:
                zz[-1] = s
            elif s.kind == "low" and s.price <= last.price:
                zz[-1] = s
        else:
            zz.append(s)
    return zz


def label_zigzag(zz: list[SwingPoint]) -> list[SwingPoint]:
    last_high: SwingPoint | None = None
    last_low: SwingPoint | None = None
    for s in zz:
        if s.kind == "high":
            if last_high is None:
                s.label = SwingLabel.H
            else:
                s.label = SwingLabel.HH if s.price > last_high.price else SwingLabel.LH
            last_high = s
        else:
            if last_low is None:
                s.label = SwingLabel.L
            else:
                s.label = SwingLabel.HL if s.price > last_low.price else SwingLabel.LL
            last_low = s
    return zz


def detect_bos(df: pd.DataFrame, zz: list[SwingPoint], right: int = 2) -> list[BOSEvent]:
    closes = df["close"].to_numpy()
    n = len(df)
    by_confirm = sorted(zz, key=lambda s: s.index + right)
    ptr = 0
    active_high: SwingPoint | None = None
    active_low: SwingPoint | None = None
    bos_events: list[BOSEvent] = []

    for t in range(n):
        while ptr < len(by_confirm) and by_confirm[ptr].index + right <= t:
            sp = by_confirm[ptr]
            if sp.kind == "high":
                active_high = sp
            else:
                active_low = sp
            ptr += 1

        if active_high is not None and closes[t] > active_high.price:
            bos_events.append(BOSEvent(
                index=t, timestamp=df.index[t], direction=Trend.BULLISH,
                broken_swing=active_high, close_price=closes[t],
            ))
            active_high = None

        if active_low is not None and closes[t] < active_low.price:
            bos_events.append(BOSEvent(
                index=t, timestamp=df.index[t], direction=Trend.BEARISH,
                broken_swing=active_low, close_price=closes[t],
            ))
            active_low = None

    return bos_events


def map_poi_zones(zz: list[SwingPoint], bos_events: list[BOSEvent]) -> list[tuple[BOSEvent, POIZone]]:
    pairs: list[tuple[BOSEvent, POIZone]] = []

    for bos in bos_events:
        if bos.direction == Trend.BULLISH:
            broken_high = bos.broken_swing
            prior_low = next((s for s in reversed(zz) if s.index < broken_high.index and s.kind == "low"), None)
            if prior_low is None:
                continue
            prior_high_before_low = next(
                (s for s in reversed(zz) if s.index < prior_low.index and s.kind == "high"), None)
            if prior_high_before_low is None:
                continue
            zone = POIZone(
                start_index=prior_high_before_low.index, end_index=prior_low.index,
                top=prior_high_before_low.price, bottom=prior_low.price,
                direction=Trend.BULLISH, is_extreme=True,
            )
            pairs.append((bos, zone))
        else:
            broken_low = bos.broken_swing
            prior_high = next((s for s in reversed(zz) if s.index < broken_low.index and s.kind == "high"), None)
            if prior_high is None:
                continue
            prior_low_before_high = next(
                (s for s in reversed(zz) if s.index < prior_high.index and s.kind == "low"), None)
            if prior_low_before_high is None:
                continue
            zone = POIZone(
                start_index=prior_low_before_high.index, end_index=prior_high.index,
                top=prior_high.price, bottom=prior_low_before_high.price,
                direction=Trend.BEARISH, is_extreme=True,
            )
            pairs.append((bos, zone))

    return pairs


def detect_fake_market_shift(
    df: pd.DataFrame,
    poi: POIZone,
    search_start_index: int,
    max_lookahead: int = 80,
    internal_left: int = 1,
    internal_right: int = 1,
) -> LiquiditySweepEvent | None:
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    closes = df["close"].to_numpy()
    n = len(df)
    end = min(n, search_start_index + max_lookahead)

    touch_idx = None
    for t in range(search_start_index, end):
        if poi.direction == Trend.BULLISH and poi.contains(lows[t]):
            touch_idx = t
            break
        if poi.direction == Trend.BEARISH and poi.contains(highs[t]):
            touch_idx = t
            break
    if touch_idx is None:
        return None

    sub = df.iloc[touch_idx:end].reset_index(drop=True)
    internal_raw = find_fractal_swings(sub, left=internal_left, right=internal_right)
    for s in internal_raw:
        s.index += touch_idx
    internal_zz = reduce_to_zigzag(internal_raw)

    if poi.direction == Trend.BULLISH:
        for i in range(len(internal_zz) - 1):
            h, l = internal_zz[i], internal_zz[i + 1]
            if h.kind != "high" or l.kind != "low" or l.index <= h.index:
                continue
            breakout_idx = next((t for t in range(l.index + 1, end) if closes[t] > h.price), None)
            if breakout_idx is None:
                continue
            sweep_idx = next((t for t in range(breakout_idx + 1, end) if lows[t] < l.price), None)
            if sweep_idx is not None:
                return LiquiditySweepEvent(
                    index=sweep_idx, timestamp=df.index[sweep_idx], direction=Trend.BULLISH,
                    internal_high=h, internal_low=l,
                    sweep_candle_index=sweep_idx, sweep_extreme_price=lows[sweep_idx],
                )
        return None

    for i in range(len(internal_zz) - 1):
        l, h = internal_zz[i], internal_zz[i + 1]
        if l.kind != "low" or h.kind != "high" or h.index <= l.index:
            continue
        breakout_idx = next((t for t in range(h.index + 1, end) if closes[t] < l.price), None)
        if breakout_idx is None:
            continue
        sweep_idx = next((t for t in range(breakout_idx + 1, end) if highs[t] > h.price), None)
        if sweep_idx is not None:
            return LiquiditySweepEvent(
                index=sweep_idx, timestamp=df.index[sweep_idx], direction=Trend.BEARISH,
                internal_high=h, internal_low=l,
                sweep_candle_index=sweep_idx, sweep_extreme_price=highs[sweep_idx],
            )
    return None


def generate_aggressive_signal(
    df: pd.DataFrame, sweep: LiquiditySweepEvent, poi: POIZone, rr: float = 2.0,
) -> TradeSignal:
    candle = df.iloc[sweep.sweep_candle_index]
    if sweep.direction == Trend.BULLISH:
        entry = float(candle["high"])
        sl = sweep.sweep_extreme_price
        risk = entry - sl
        tp = entry + risk * rr if risk > 0 else None
    else:
        entry = float(candle["low"])
        sl = sweep.sweep_extreme_price
        risk = sl - entry
        tp = entry - risk * rr if risk > 0 else None

    return TradeSignal(
        model="aggressive", direction=sweep.direction, entry_index=sweep.sweep_candle_index,
        entry_price=entry, stop_loss=sl, take_profit=tp,
        timestamp=df.index[sweep.sweep_candle_index], poi=poi,
        notes="Stop order at sweep candle extreme; SL beyond liquidity-grab wick.",
    )


def generate_conservative_signal(
    df: pd.DataFrame,
    sweep: LiquiditySweepEvent,
    poi: POIZone,
    max_lookahead: int = 80,
    rr: float = 3.0,
) -> TradeSignal | None:
    opens = df["open"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    closes = df["close"].to_numpy()
    n = len(df)
    end = min(n, sweep.sweep_candle_index + max_lookahead)

    if sweep.direction == Trend.BULLISH:
        target = sweep.internal_high.price
        confirm_idx = next((t for t in range(sweep.sweep_candle_index + 1, end) if closes[t] > target), None)
        if confirm_idx is None:
            return None

        flip_idx = next(
            (t for t in range(confirm_idx - 1, sweep.sweep_candle_index - 1, -1) if closes[t] < opens[t]),
            sweep.sweep_candle_index,
        )
        flip_top = max(opens[flip_idx], closes[flip_idx])
        flip_bottom = lows[flip_idx]
        entry = flip_top
        sl = min(flip_bottom, sweep.sweep_extreme_price)
        risk = entry - sl
        tp = entry + risk * rr if risk > 0 else None
        notes = (
            f"MSS confirmed at bar {confirm_idx} (close > internal high {target:.5f}). "
            f"Limit entry on flip zone [{flip_bottom:.5f}, {flip_top:.5f}]."
        )
        return TradeSignal(
            model="conservative", direction=Trend.BULLISH, entry_index=confirm_idx,
            entry_price=entry, stop_loss=sl, take_profit=tp,
            timestamp=df.index[confirm_idx], poi=poi, notes=notes,
        )

    target = sweep.internal_low.price
    confirm_idx = next((t for t in range(sweep.sweep_candle_index + 1, end) if closes[t] < target), None)
    if confirm_idx is None:
        return None

    flip_idx = next(
        (t for t in range(confirm_idx - 1, sweep.sweep_candle_index - 1, -1) if closes[t] > opens[t]),
        sweep.sweep_candle_index,
    )
    flip_bottom = min(opens[flip_idx], closes[flip_idx])
    flip_top = highs[flip_idx]
    entry = flip_bottom
    sl = max(flip_top, sweep.sweep_extreme_price)
    risk = sl - entry
    tp = entry - risk * rr if risk > 0 else None
    notes = (
        f"MSS confirmed at bar {confirm_idx} (close < internal low {target:.5f}). "
        f"Limit entry on flip zone [{flip_bottom:.5f}, {flip_top:.5f}]."
    )
    return TradeSignal(
        model="conservative", direction=Trend.BEARISH, entry_index=confirm_idx,
        entry_price=entry, stop_loss=sl, take_profit=tp,
        timestamp=df.index[confirm_idx], poi=poi, notes=notes,
    )


class FakeMarketShiftStrategy:
    def __init__(self, cfg: StrategyConfig | None = None):
        self.cfg = cfg or StrategyConfig()

    def analyze(self, df: pd.DataFrame) -> dict[str, Any]:
        required = {"open", "high", "low", "close"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"DataFrame is missing required columns: {missing}")

        raw = find_fractal_swings(df, self.cfg.swing_left, self.cfg.swing_right)
        zz = label_zigzag(reduce_to_zigzag(raw))
        bos_events = detect_bos(df, zz, right=self.cfg.swing_right)
        bos_poi_pairs = map_poi_zones(zz, bos_events)

        sweeps: list[LiquiditySweepEvent] = []
        signals: list[TradeSignal] = []
        for bos, poi in bos_poi_pairs:
            sweep = detect_fake_market_shift(
                df, poi, search_start_index=bos.index,
                max_lookahead=self.cfg.poi_lookahead,
                internal_left=self.cfg.internal_left,
                internal_right=self.cfg.internal_right,
            )
            if sweep is None:
                continue
            sweeps.append(sweep)
            if self.cfg.entry_model in ("both", "aggressive"):
                signals.append(generate_aggressive_signal(
                    df, sweep, poi, rr=self.cfg.rr_aggressive,
                ))
            if self.cfg.entry_model in ("both", "conservative"):
                conservative = generate_conservative_signal(
                    df, sweep, poi, max_lookahead=self.cfg.poi_lookahead,
                    rr=self.cfg.rr_conservative,
                )
                if conservative is not None:
                    signals.append(conservative)

        deduped_signals: list[TradeSignal] = []
        seen: set[tuple] = set()
        for sig in signals:
            key = (sig.model, sig.direction, sig.entry_index, round(sig.entry_price, 6))
            if key not in seen:
                seen.add(key)
                deduped_signals.append(sig)

        deduped_sweeps: list[LiquiditySweepEvent] = []
        seen_sweeps: set[tuple] = set()
        for sw in sweeps:
            key = (sw.direction, sw.sweep_candle_index, round(sw.sweep_extreme_price, 6))
            if key not in seen_sweeps:
                seen_sweeps.add(key)
                deduped_sweeps.append(sw)

        return {
            "swings": zz,
            "bos_events": bos_events,
            "poi_zones": [poi for _, poi in bos_poi_pairs],
            "sweeps": deduped_sweeps,
            "signals": deduped_signals,
        }


class Backtester:
    def __init__(self, max_fill_wait: int = 30, max_trade_duration: int = 200):
        self.max_fill_wait = max_fill_wait
        self.max_trade_duration = max_trade_duration

    def run(self, df: pd.DataFrame, signals: list[TradeSignal]) -> list[TradeResult]:
        highs = df["high"].to_numpy()
        lows = df["low"].to_numpy()
        n = len(df)
        results: list[TradeResult] = []

        for sig in signals:
            start = sig.entry_index + 1
            fill_idx = None
            for t in range(start, min(n, start + self.max_fill_wait)):
                if sig.direction == Trend.BULLISH and highs[t] >= sig.entry_price:
                    fill_idx = t
                    break
                if sig.direction == Trend.BEARISH and lows[t] <= sig.entry_price:
                    fill_idx = t
                    break
            if fill_idx is None:
                results.append(TradeResult(sig, False, None, None, None))
                continue

            outcome: Literal["tp", "sl", "open"] = "open"
            risk = abs(sig.entry_price - sig.stop_loss)
            for t in range(fill_idx, min(n, fill_idx + self.max_trade_duration)):
                if sig.direction == Trend.BULLISH:
                    if lows[t] <= sig.stop_loss:
                        outcome = "sl"
                        break
                    if sig.take_profit and highs[t] >= sig.take_profit:
                        outcome = "tp"
                        break
                else:
                    if highs[t] >= sig.stop_loss:
                        outcome = "sl"
                        break
                    if sig.take_profit and lows[t] <= sig.take_profit:
                        outcome = "tp"
                        break

            r = -1.0 if outcome == "sl" else (
                abs(sig.take_profit - sig.entry_price) / risk if outcome == "tp" and risk > 0 else None
            )
            results.append(TradeResult(sig, True, fill_idx, outcome, r))

        return results

    @staticmethod
    def summarize(results: list[TradeResult]) -> dict[str, Any]:
        closed = [r for r in results if r.outcome in ("tp", "sl")]
        wins = [r for r in closed if r.outcome == "tp"]
        total_r = sum(r.r_multiple for r in closed if r.r_multiple is not None)
        return {
            "total_signals": len(results),
            "filled": sum(1 for r in results if r.filled),
            "closed_trades": len(closed),
            "wins": len(wins),
            "win_rate": round((len(wins) / len(closed)) * 100, 1) if closed else 0.0,
            "total_R": round(total_r, 2),
            "avg_R": round(total_r / len(closed), 2) if closed else 0.0,
        }


def _signal_to_plan(sig: TradeSignal, price: float) -> dict[str, Any]:
    entry = sig.entry_price
    sl = sig.stop_loss
    tp = sig.take_profit or entry
    sl_pct = abs(entry - sl) / entry * 100 if entry else 0
    tp_pct = abs(tp - entry) / entry * 100 if entry else 0
    direction = "LONG" if sig.direction == Trend.BULLISH else "SHORT"
    rr = tp_pct / sl_pct if sl_pct > 0 else 0
    return {
        "direction": direction,
        "model": sig.model.upper(),
        "entry": round(entry, 6),
        "stop_loss": round(sl, 6),
        "take_profit": round(tp, 6) if sig.take_profit else None,
        "sl_pct": round(sl_pct, 3),
        "tp_pct": round(tp_pct, 3),
        "rr_ratio": round(rr, 2),
        "hold_duration": "15 min – 4 hours (SMC scalp/swing)",
        "notes": sig.notes,
        "entry_index": sig.entry_index,
    }


def _serialize_backtest_results(results: list[TradeResult]) -> list[dict[str, Any]]:
    rows = []
    for r in results[-30:]:
        sig = r.signal
        rows.append({
            "model": sig.model,
            "direction": sig.direction.value.upper(),
            "entry": round(sig.entry_price, 4),
            "sl": round(sig.stop_loss, 4),
            "tp": round(sig.take_profit, 4) if sig.take_profit else None,
            "filled": r.filled,
            "outcome": r.outcome or "—",
            "R": round(r.r_multiple, 2) if r.r_multiple is not None else None,
        })
    return rows


def fetch_fms_data(
    symbol: str,
    timeframe: str,
    market: str,
    groww_token: str = "",
    exchange: str = "NSE",
    limit: int = 600,
) -> pd.DataFrame:
    df = fetch_data_for_gap_scan(symbol, timeframe, market, groww_token, exchange, limit=limit)
    return normalize_ohlcv(df).tail(limit)


def analyze_smc_fake_market_shift(
    df: pd.DataFrame,
    *,
    chart_tf: str = "15m",
    cfg: StrategyConfig | None = None,
) -> dict[str, Any]:
    cfg = cfg or StrategyConfig()
    df = normalize_ohlcv(df)
    min_bars = max(50, cfg.swing_left + cfg.swing_right + cfg.poi_lookahead // 2)

    if df.empty or len(df) < min_bars:
        return {
            "phase": "NO_DATA",
            "primary_label": f"Insufficient data ({len(df)} bars, need {min_bars}+)",
            "priority": 0,
            "actionable": False,
            "confidence": 0.0,
            "chart_tf": chart_tf,
        }

    strategy = FakeMarketShiftStrategy(cfg)
    analysis = strategy.analyze(df)
    backtester = Backtester(cfg.max_fill_wait, cfg.max_trade_duration)
    bt_results = backtester.run(df, analysis["signals"])
    bt_summary = Backtester.summarize(bt_results)

    n = len(df)
    lookback_start = max(0, n - cfg.live_lookback_bars)
    recent_signals = [s for s in analysis["signals"] if s.entry_index >= lookback_start]
    recent_sweeps = [s for s in analysis["sweeps"] if s.sweep_candle_index >= lookback_start]

    live_signal: TradeSignal | None = None
    if recent_signals:
        live_signal = max(recent_signals, key=lambda s: s.entry_index)
    elif analysis["signals"]:
        live_signal = analysis["signals"][-1]

    price = float(df["close"].iloc[-1])
    bos_events = analysis["bos_events"]
    trend_bias = bos_events[-1].direction.value.upper() if bos_events else "NEUTRAL"

    phase = "NO_SETUP"
    confidence = 35.0
    actionable = False
    trade_plan = None
    primary_label = f"No fake market shift setup · trend bias {trend_bias}"

    if live_signal and live_signal.entry_index >= lookback_start:
        phase = "ENTRY_READY"
        confidence = 75.0 if live_signal.model == "conservative" else 65.0
        actionable = True
        trade_plan = _signal_to_plan(live_signal, price)
        dir_label = "LONG" if live_signal.direction == Trend.BULLISH else "SHORT"
        primary_label = (
            f"{dir_label} · {live_signal.model.title()} entry · fake market shift confirmed · "
            f"bias {trend_bias}"
        )
    elif recent_sweeps:
        sw = recent_sweeps[-1]
        phase = "WATCH_SWEEP"
        confidence = 55.0
        dir_label = "LONG" if sw.direction == Trend.BULLISH else "SHORT"
        primary_label = (
            f"Watch {dir_label} — liquidity sweep at bar {sw.sweep_candle_index}; "
            f"await MSS / flip-zone entry (conservative model)"
        )

    elif bos_events or analysis["poi_zones"]:
        phase = "STRUCTURE_ONLY"
        confidence = 45.0
        primary_label = (
            f"Structure mapped — {len(bos_events)} BOS · {len(analysis['poi_zones'])} POI zones · "
            f"no recent sweep in last {cfg.live_lookback_bars} bars"
        )

    return {
        "phase": phase,
        "primary_label": primary_label,
        "priority": PHASE_PRIORITY.get(phase, 0),
        "actionable": actionable,
        "confidence": confidence,
        "chart_tf": chart_tf,
        "price": price,
        "trend_bias": trend_bias,
        "bos_count": len(bos_events),
        "poi_count": len(analysis["poi_zones"]),
        "sweep_count": len(analysis["sweeps"]),
        "signal_count": len(analysis["signals"]),
        "live_signal": live_signal,
        "trade_plan": trade_plan,
        "backtest_summary": bt_summary,
        "backtest_trades": _serialize_backtest_results(bt_results),
        "swings": analysis["swings"],
        "bos_events": bos_events,
        "poi_zones": analysis["poi_zones"],
        "sweeps": analysis["sweeps"],
        "signals": analysis["signals"],
        "result_df": df,
    }
