"""
velez_retracement_engine.py
-----------------------------
Oliver Velez retracement scalping — 20/200 SMA, sharp-move retracement rules.
Scenario A: counter-trend scalp to 25% retrace.
Scenario B: trend trade after 50%+ bounce + engulfing entry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.mtf_scanner_engine import TIMEFRAMES, normalize_ohlcv

VELEZ_TF_OPTIONS = ["2m", "5m"]

PHASE_PRIORITY = {
    "ENTRY_READY": 100,
    "WATCH": 60,
    "NO_SETUP": 15,
    "NO_DATA": 0,
}


class TradeType(Enum):
    SCALP = "scalp"
    TREND = "trend"


class TradeDirection(Enum):
    LONG = "long"
    SHORT = "short"


@dataclass
class StrategyConfig:
    short_sma: int = 20
    long_sma: int = 200
    sharp_move_lookback: int = 10
    sharp_move_threshold: float = 0.005
    scalp_target_pct: float = 0.25
    mid_retracement_pct: float = 0.50
    stop_loss_pct: float = 0.003
    risk_reward_trend: float = 2.0


@dataclass
class Move:
    direction: str
    start_idx: int
    end_idx: int
    start_price: float
    end_price: float

    @property
    def magnitude(self) -> float:
        return abs(self.end_price - self.start_price)

    def retracement_price(self, fraction: float) -> float:
        if self.direction == "down":
            return self.end_price + self.magnitude * fraction
        return self.end_price - self.magnitude * fraction


@dataclass
class TradeSignal:
    index: int
    timestamp: object
    trade_type: TradeType
    direction: TradeDirection
    entry_price: float
    target_price: float
    stop_price: float
    move: Move
    notes: str = ""

    @property
    def risk(self) -> float:
        return abs(self.entry_price - self.stop_price)

    @property
    def reward(self) -> float:
        return abs(self.target_price - self.entry_price)

    @property
    def risk_reward(self) -> float:
        return self.reward / self.risk if self.risk > 0 else 0.0


@dataclass
class TradeResult:
    signal: TradeSignal
    exit_price: float
    exit_index: int
    outcome: str
    pnl_pct: float


def compute_smas(df: pd.DataFrame, short: int, long: int) -> pd.DataFrame:
    out = df.copy()
    out[f"sma{short}"] = out["close"].rolling(short).mean()
    out[f"sma{long}"] = out["close"].rolling(long).mean()
    return out


def detect_sharp_moves(df: pd.DataFrame, lookback: int, threshold: float) -> list[Move]:
    moves: list[Move] = []
    closes = df["close"].values

    for i in range(lookback, len(closes)):
        window = closes[i - lookback: i + 1]
        net_change = window[-1] - window[0]
        pct_change = net_change / window[0]

        if abs(pct_change) < threshold:
            continue

        direction = "down" if net_change < 0 else "up"

        if moves and moves[-1].end_idx >= i - lookback // 2:
            prev = moves[-1]
            if prev.direction == direction and prev.magnitude < abs(net_change):
                moves.pop()
            elif prev.direction == direction:
                continue

        moves.append(Move(
            direction=direction,
            start_idx=i - lookback,
            end_idx=i,
            start_price=float(window[0]),
            end_price=float(window[-1]),
        ))

    return moves


def generate_signals(df: pd.DataFrame, cfg: StrategyConfig | None = None) -> list[TradeSignal]:
    cfg = cfg or StrategyConfig()
    required_bars = max(cfg.long_sma, cfg.short_sma) + cfg.sharp_move_lookback
    if len(df) < required_bars:
        raise ValueError(f"Need at least {required_bars} bars; got {len(df)}.")

    df = compute_smas(df, cfg.short_sma, cfg.long_sma)
    sma_short_col = f"sma{cfg.short_sma}"
    sma_long_col = f"sma{cfg.long_sma}"

    moves = detect_sharp_moves(df, cfg.sharp_move_lookback, cfg.sharp_move_threshold)
    signals: list[TradeSignal] = []
    processed_move_ends: set[int] = set()

    closes = df["close"].values
    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    sma20 = df[sma_short_col].values
    sma200 = df[sma_long_col].values

    for move in moves:
        end_i = move.end_idx
        if np.isnan(sma20[end_i]) or np.isnan(sma200[end_i]):
            continue

        sma_aligned = (
            (move.direction == "down" and closes[end_i] < sma20[end_i])
            or (move.direction == "up" and closes[end_i] > sma20[end_i])
        )
        sma_note = "" if sma_aligned else " [SMA misaligned — lower confidence]"

        target_25 = move.retracement_price(cfg.scalp_target_pct)
        target_50 = move.retracement_price(cfg.mid_retracement_pct)

        scan_start = end_i + 1
        scan_end = min(end_i + cfg.sharp_move_lookback * 2, len(df) - 1)

        in_scenario_b = False
        scenario_b_bounce_extreme: float | None = None

        for i in range(scan_start, scan_end + 1):
            if end_i in processed_move_ends:
                break

            c = closes[i]
            o = opens[i]
            h = highs[i]
            lo = lows[i]
            c_prev = closes[i - 1]
            o_prev = opens[i - 1]

            if move.direction == "down":
                bounce_size = c - move.end_price
                if scenario_b_bounce_extreme is None or c > scenario_b_bounce_extreme:
                    scenario_b_bounce_extreme = c

                if (not in_scenario_b
                        and scenario_b_bounce_extreme is not None
                        and scenario_b_bounce_extreme >= target_50):
                    in_scenario_b = True

                if (not in_scenario_b
                        and bounce_size > 0
                        and bounce_size < move.magnitude * cfg.mid_retracement_pct):
                    entry = c
                    target = target_25
                    stop = entry - entry * cfg.stop_loss_pct
                    if target > entry and (entry - stop) > 0:
                        signals.append(TradeSignal(
                            index=i,
                            timestamp=df.index[i],
                            trade_type=TradeType.SCALP,
                            direction=TradeDirection.LONG,
                            entry_price=entry,
                            target_price=target,
                            stop_price=stop,
                            move=move,
                            notes=f"Scalp long after sharp drop. Target=25% retrace ({target:.2f}).{sma_note}",
                        ))
                        processed_move_ends.add(end_i)
                        break

                if in_scenario_b:
                    is_green = c > o
                    was_red = c_prev < o_prev
                    engulfs = is_green and was_red and c > o_prev and o < c_prev
                    if engulfs:
                        entry = c
                        stop = lo - lo * cfg.stop_loss_pct
                        risk = entry - stop
                        target = entry + risk * cfg.risk_reward_trend
                        signals.append(TradeSignal(
                            index=i,
                            timestamp=df.index[i],
                            trade_type=TradeType.TREND,
                            direction=TradeDirection.LONG,
                            entry_price=entry,
                            target_price=target,
                            stop_price=stop,
                            move=move,
                            notes=(
                                f"Trend long: bounce exceeded 50%, pullback engulfing entry. "
                                f"R:R ≥ {cfg.risk_reward_trend}x.{sma_note}"
                            ),
                        ))
                        processed_move_ends.add(end_i)
                        break

            elif move.direction == "up":
                pullback_size = move.end_price - c
                if scenario_b_bounce_extreme is None or c < scenario_b_bounce_extreme:
                    scenario_b_bounce_extreme = c

                if (not in_scenario_b
                        and scenario_b_bounce_extreme is not None
                        and scenario_b_bounce_extreme <= target_50):
                    in_scenario_b = True

                if (not in_scenario_b
                        and pullback_size > 0
                        and pullback_size < move.magnitude * cfg.mid_retracement_pct):
                    entry = c
                    target = target_25
                    stop = entry + entry * cfg.stop_loss_pct
                    if target < entry and (stop - entry) > 0:
                        signals.append(TradeSignal(
                            index=i,
                            timestamp=df.index[i],
                            trade_type=TradeType.SCALP,
                            direction=TradeDirection.SHORT,
                            entry_price=entry,
                            target_price=target,
                            stop_price=stop,
                            move=move,
                            notes=f"Scalp short after sharp spike. Target=25% retrace ({target:.2f}).{sma_note}",
                        ))
                        processed_move_ends.add(end_i)
                        break

                if in_scenario_b:
                    is_red = c < o
                    was_green = c_prev > o_prev
                    engulfs = is_red and was_green and c < o_prev and o > c_prev
                    if engulfs:
                        entry = c
                        stop = h + h * cfg.stop_loss_pct
                        risk = stop - entry
                        target = entry - risk * cfg.risk_reward_trend
                        signals.append(TradeSignal(
                            index=i,
                            timestamp=df.index[i],
                            trade_type=TradeType.TREND,
                            direction=TradeDirection.SHORT,
                            entry_price=entry,
                            target_price=target,
                            stop_price=stop,
                            move=move,
                            notes=(
                                f"Trend short: pullback exceeded 50%, bearish engulfing entry. "
                                f"R:R ≥ {cfg.risk_reward_trend}x.{sma_note}"
                            ),
                        ))
                        processed_move_ends.add(end_i)
                        break

    return signals


def backtest(df: pd.DataFrame, signals: list[TradeSignal]) -> tuple[list[TradeResult], pd.DataFrame]:
    closes = df["close"].values
    results: list[TradeResult] = []

    for sig in signals:
        outcome = "open"
        exit_price = float(closes[-1])
        exit_index = len(df) - 1

        for i in range(sig.index + 1, len(df)):
            c = closes[i]
            if sig.direction == TradeDirection.LONG:
                if c >= sig.target_price:
                    outcome, exit_price, exit_index = "win", sig.target_price, i
                    break
                if c <= sig.stop_price:
                    outcome, exit_price, exit_index = "loss", sig.stop_price, i
                    break
            else:
                if c <= sig.target_price:
                    outcome, exit_price, exit_index = "win", sig.target_price, i
                    break
                if c >= sig.stop_price:
                    outcome, exit_price, exit_index = "loss", sig.stop_price, i
                    break

        if sig.direction == TradeDirection.LONG:
            pnl_pct = (exit_price - sig.entry_price) / sig.entry_price * 100
        else:
            pnl_pct = (sig.entry_price - exit_price) / sig.entry_price * 100

        results.append(TradeResult(
            signal=sig,
            exit_price=exit_price,
            exit_index=exit_index,
            outcome=outcome,
            pnl_pct=pnl_pct,
        ))

    rows = []
    for r in results:
        s = r.signal
        rows.append({
            "timestamp": s.timestamp,
            "type": s.trade_type.value,
            "direction": s.direction.value,
            "entry": round(s.entry_price, 4),
            "target": round(s.target_price, 4),
            "stop": round(s.stop_price, 4),
            "exit": round(r.exit_price, 4),
            "outcome": r.outcome,
            "pnl_%": round(r.pnl_pct, 3),
            "R:R": round(s.risk_reward, 2),
            "notes": s.notes,
        })

    return results, pd.DataFrame(rows)


def _hold_for_signal(sig: TradeSignal, chart_tf: str) -> str:
    if sig.trade_type == TradeType.SCALP:
        return "5–30 minutes (Velez scalp)" if chart_tf in ("2m", "5m") else TIMEFRAMES.get(chart_tf, {}).get("hold", "15–60 min")
    return TIMEFRAMES.get(chart_tf, {}).get("hold", "1 – 3 hours")


def _signal_to_plan(sig: TradeSignal, chart_tf: str) -> dict[str, Any]:
    entry = sig.entry_price
    sl = sig.stop_price
    tp = sig.target_price
    sl_pct = abs(entry - sl) / entry * 100 if entry else 0
    tp_pct = abs(tp - entry) / entry * 100 if entry else 0
    direction = "LONG" if sig.direction == TradeDirection.LONG else "SHORT"
    return {
        "direction": direction,
        "scenario": sig.trade_type.value.upper(),
        "entry": round(entry, 4),
        "stop_loss": round(sl, 4),
        "take_profit": round(tp, 4),
        "sl_pct": round(sl_pct, 2),
        "tp_pct": round(tp_pct, 2),
        "rr_ratio": round(sig.risk_reward, 2),
        "hold_duration": _hold_for_signal(sig, chart_tf),
        "entry_timeframe": chart_tf,
        "notes": sig.notes,
    }


def _serialize_signal(sig: TradeSignal) -> dict[str, Any]:
    return {
        "index": sig.index,
        "timestamp": str(sig.timestamp),
        "trade_type": sig.trade_type.value,
        "direction": sig.direction.value,
        "entry_price": sig.entry_price,
        "target_price": sig.target_price,
        "stop_price": sig.stop_price,
        "notes": sig.notes,
        "risk_reward": round(sig.risk_reward, 2),
    }


def _backtest_stats(summary: pd.DataFrame) -> dict[str, Any]:
    if summary.empty:
        return {"total": 0, "win_rate": 0.0, "total_pnl_pct": 0.0}
    closed = summary[summary["outcome"].isin(["win", "loss"])]
    wins = closed[closed["outcome"] == "win"]
    win_rate = len(wins) / len(closed) * 100 if len(closed) else 0.0
    return {
        "total": len(summary),
        "closed": len(closed),
        "win_rate": round(win_rate, 1),
        "total_pnl_pct": round(closed["pnl_%"].sum(), 2) if len(closed) else 0.0,
        "scalps": int((closed["type"] == "scalp").sum()),
        "trends": int((closed["type"] == "trend").sum()),
    }


def _resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    if df.empty:
        return df
    return df.resample(rule).agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna()


def fetch_velez_data(
    symbol: str,
    chart_tf: str,
    market: str,
    groww_token: str = "",
    exchange: str = "NSE",
    limit: int = 600,
) -> pd.DataFrame:
    if chart_tf == "2m":
        raw = fetch_data_for_gap_scan(symbol, "1m", market, groww_token, exchange, limit=limit * 3)
        raw = normalize_ohlcv(raw)
        if raw.empty:
            raw = normalize_ohlcv(
                fetch_data_for_gap_scan(symbol, "5m", market, groww_token, exchange, limit=limit)
            )
            return raw.tail(limit)
        return _resample_ohlcv(raw, "2min").tail(limit)

    df = fetch_data_for_gap_scan(symbol, chart_tf, market, groww_token, exchange, limit=limit)
    return normalize_ohlcv(df).tail(limit)


def analyze_velez(
    df: pd.DataFrame,
    *,
    chart_tf: str = "5m",
    cfg: StrategyConfig | None = None,
    live_lookback_bars: int = 15,
) -> dict[str, Any]:
    """Run Velez retracement scanner on OHLCV data."""
    cfg = cfg or StrategyConfig()
    df = normalize_ohlcv(df)
    required = max(cfg.long_sma, cfg.short_sma) + cfg.sharp_move_lookback

    if df.empty or len(df) < required:
        return {
            "phase": "NO_DATA",
            "primary_label": f"Insufficient data ({len(df)} bars, need {required}+)",
            "priority": 0,
            "actionable": False,
            "confidence": 0.0,
            "chart_tf": chart_tf,
        }

    try:
        signals = generate_signals(df, cfg)
    except ValueError as exc:
        return {
            "phase": "NO_DATA",
            "primary_label": str(exc),
            "priority": 0,
            "actionable": False,
            "confidence": 0.0,
            "chart_tf": chart_tf,
        }

    _, summary = backtest(df, signals)
    stats = _backtest_stats(summary)

    live_signal: TradeSignal | None = None
    tail_start = max(0, len(df) - live_lookback_bars)
    for sig in reversed(signals):
        if sig.index >= tail_start:
            live_signal = sig
            break

    enriched = compute_smas(df, cfg.short_sma, cfg.long_sma)
    last = enriched.iloc[-1]
    cur = float(last["close"])
    sma20 = float(last[f"sma{cfg.short_sma}"]) if not pd.isna(last[f"sma{cfg.short_sma}"]) else None
    sma200 = float(last[f"sma{cfg.long_sma}"]) if not pd.isna(last[f"sma{cfg.long_sma}"]) else None

    moves = detect_sharp_moves(df, cfg.sharp_move_lookback, cfg.sharp_move_threshold)
    recent_move = moves[-1] if moves and moves[-1].end_idx >= len(df) - cfg.sharp_move_lookback * 2 else None

    phase = "NO_SETUP"
    primary_label = "No Velez retracement setup on latest bars"
    priority = PHASE_PRIORITY["NO_SETUP"]
    actionable = False
    confidence = 40.0
    trade_plan: dict[str, Any] | None = None

    if live_signal:
        phase = "ENTRY_READY"
        scenario = "A Scalp" if live_signal.trade_type == TradeType.SCALP else "B Trend"
        dir_label = live_signal.direction.value.upper()
        primary_label = (
            f"{scenario} {dir_label} — {live_signal.trade_type.value} "
            f"@ {chart_tf} (R:R {live_signal.risk_reward:.1f})"
        )
        priority = PHASE_PRIORITY["ENTRY_READY"]
        actionable = True
        confidence = 88.0 if live_signal.trade_type == TradeType.SCALP else 78.0
        if "misaligned" in live_signal.notes.lower():
            confidence -= 12.0
        trade_plan = _signal_to_plan(live_signal, chart_tf)
    elif recent_move:
        phase = "WATCH"
        mv = recent_move
        retrace_25 = mv.retracement_price(cfg.scalp_target_pct)
        retrace_50 = mv.retracement_price(cfg.mid_retracement_pct)
        primary_label = (
            f"Sharp {mv.direction} move detected — watch for "
            f"{'bounce' if mv.direction == 'down' else 'pullback'} "
            f"(25% @ {retrace_25:.2f} · 50% flip @ {retrace_50:.2f})"
        )
        priority = PHASE_PRIORITY["WATCH"]
        confidence = 55.0

    return {
        "phase": phase,
        "primary_label": primary_label,
        "priority": priority,
        "actionable": actionable,
        "confidence": round(confidence, 1),
        "trade_plan": trade_plan,
        "live_signal": _serialize_signal(live_signal) if live_signal else None,
        "recent_move": {
            "direction": recent_move.direction,
            "start_price": recent_move.start_price,
            "end_price": recent_move.end_price,
            "magnitude_pct": round(recent_move.magnitude / recent_move.start_price * 100, 2),
        } if recent_move else None,
        "signals_count": len(signals),
        "recent_signals": [_serialize_signal(s) for s in signals[-5:]],
        "backtest_summary": stats,
        "backtest_trades": summary.to_dict(orient="records") if not summary.empty else [],
        "chart_tf": chart_tf,
        "price": cur,
        "sma20": sma20,
        "sma200": sma200,
        "result_df": enriched,
    }
