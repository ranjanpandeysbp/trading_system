"""
smart_wave_crypto_engine.py
-----------------------------
Smart Wave Academy crypto strategies (Archit Mittal 3-Day Bootcamp).
CoinDCX-only scanners: EMA Crossover, SuperTrend, BB Reversal,
Multi-Bagger Reversal, Volume Confirmation filter.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv

# ── Risk management (bootcamp defaults) ─────────────────────────────────────

RISK_PER_TRADE_INR = 200
REWARD_PER_TRADE_INR = 600
MAX_LEVERAGE = 5
TRADE_SIZE_INR = 2500
TRADE_SIZE_BTC_INR = 5000
MAX_CONCURRENT_TRADES = 2
RR_RATIO = 3

SMART_WAVE_TF_OPTIONS = ["5m", "30m", "1h"]

STRATEGY_KEYS = [
    "ema_crossover",
    "supertrend",
    "bb_reversal",
    "multibagger",
]

STRATEGY_LABELS = {
    "ema_crossover": "S1 · EMA Crossover (10/30)",
    "supertrend": "S2 · SuperTrend Archit Trend Flow (10, 3)",
    "bb_reversal": "S3 · Bollinger Band Reversal (~80%)",
    "multibagger": "S4 · Multi-Bagger Reversal (5m SHORT)",
}

PHASE_PRIORITY = {
    "ENTRY_LONG": 100,
    "ENTRY_SHORT": 100,
    "MB_READY": 95,
    "TREND_LONG": 70,
    "TREND_SHORT": 70,
    "WATCH": 55,
    "NO_SIGNAL": 20,
    "NO_DATA": 0,
    "MB_SKIP": 10,
}


def get_position_size(capital_inr: float, leverage: int = 5) -> float:
    return capital_inr * min(leverage, MAX_LEVERAGE)


def liquidation_distance(leverage: int = 5) -> float:
    return round(100 / leverage, 2)


def ema_crossover_signals(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ema10"] = df["close"].ewm(span=10, adjust=False).mean()
    df["ema30"] = df["close"].ewm(span=30, adjust=False).mean()
    prev10 = df["ema10"].shift(1)
    prev30 = df["ema30"].shift(1)
    df["signal"] = 0
    df.loc[(df["ema10"] > df["ema30"]) & (prev10 <= prev30), "signal"] = 1
    df.loc[(df["ema10"] < df["ema30"]) & (prev10 >= prev30), "signal"] = -1
    return df


def ema_crossover_trade(df: pd.DataFrame, idx: int) -> dict:
    row, prev = df.iloc[idx], df.iloc[idx - 1]
    if row["signal"] == 1:
        sl = prev["low"]
        tgt = row["close"] + (row["close"] - sl) * RR_RATIO
        direction = "LONG"
    elif row["signal"] == -1:
        sl = prev["high"]
        tgt = row["close"] - (sl - row["close"]) * RR_RATIO
        direction = "SHORT"
    else:
        return {}
    return {
        "strategy": "EMA Crossover",
        "direction": direction,
        "entry": round(float(row["close"]), 4),
        "stoploss": round(float(sl), 4),
        "target": round(float(tgt), 4),
        "rr": f"1:{RR_RATIO}",
    }


def supertrend_signals(df: pd.DataFrame, period: int = 10, mult: float = 3.0) -> pd.DataFrame:
    df = df.copy()
    high, low, close = df["high"], df["low"], df["close"]

    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()

    hl2 = (high + low) / 2
    ub_basic = hl2 + mult * atr
    lb_basic = hl2 - mult * atr

    ub = ub_basic.copy()
    lb = lb_basic.copy()
    direction = pd.Series(0, index=df.index)
    st_line = pd.Series(np.nan, index=df.index)

    for i in range(1, len(df)):
        lb.iloc[i] = (
            lb_basic.iloc[i]
            if (lb_basic.iloc[i] > lb.iloc[i - 1] or close.iloc[i - 1] < lb.iloc[i - 1])
            else lb.iloc[i - 1]
        )
        ub.iloc[i] = (
            ub_basic.iloc[i]
            if (ub_basic.iloc[i] < ub.iloc[i - 1] or close.iloc[i - 1] > ub.iloc[i - 1])
            else ub.iloc[i - 1]
        )
        if close.iloc[i] > ub.iloc[i]:
            direction.iloc[i] = 1
            st_line.iloc[i] = lb.iloc[i]
        elif close.iloc[i] < lb.iloc[i]:
            direction.iloc[i] = -1
            st_line.iloc[i] = ub.iloc[i]
        else:
            direction.iloc[i] = direction.iloc[i - 1]
            st_line.iloc[i] = lb.iloc[i] if direction.iloc[i] == 1 else ub.iloc[i]

    df["supertrend"] = st_line
    df["st_direction"] = direction
    df["signal"] = 0
    df.loc[(direction == 1) & (direction.shift(1) == -1), "signal"] = 1
    df.loc[(direction == -1) & (direction.shift(1) == 1), "signal"] = -1
    return df


def supertrend_trade(df: pd.DataFrame, idx: int) -> dict:
    row = df.iloc[idx]
    direction = "LONG" if row["signal"] == 1 else "SHORT"
    entry = float(row["close"])
    sl = float(row["supertrend"])
    dist = abs(entry - sl)
    target = (entry + dist * RR_RATIO) if direction == "LONG" else (entry - dist * RR_RATIO)
    return {
        "strategy": "SuperTrend",
        "direction": direction,
        "entry": round(entry, 4),
        "stoploss": round(sl, 4),
        "target": round(target, 4),
        "note": "Also exit when SuperTrend color reverses",
    }


def bb_reversal_signals(df: pd.DataFrame, period: int = 20, std: float = 2.0) -> pd.DataFrame:
    df = df.copy()
    mid = df["close"].rolling(period).mean()
    sigma = df["close"].rolling(period).std()
    df["bb_upper"] = mid + std * sigma
    df["bb_lower"] = mid - std * sigma
    df["bb_mid"] = mid

    prev_close = df["close"].shift(1)
    df["signal"] = 0
    df.loc[(prev_close > df["bb_upper"].shift(1)) & (df["close"] <= df["bb_upper"]), "signal"] = -1
    df.loc[(prev_close < df["bb_lower"].shift(1)) & (df["close"] >= df["bb_lower"]), "signal"] = 1
    return df


_BB_TF = {"15m": (0.005, 0.015), "30m": (0.0075, 0.0225), "1h": (0.01, 0.03), "1d": (0.015, 0.045)}


def bb_reversal_trade(df: pd.DataFrame, idx: int, timeframe: str = "30m") -> dict:
    tf_key = timeframe.lower()
    sl_pct, _ = _BB_TF.get(tf_key, (0.0075, 0.0225))
    row = df.iloc[idx]
    entry = float(row["close"])
    direction = "LONG" if row["signal"] == 1 else "SHORT"
    sl = entry * (1 - sl_pct) if direction == "LONG" else entry * (1 + sl_pct)
    target = float(row["bb_upper"]) if direction == "LONG" else float(row["bb_lower"])
    return {
        "strategy": "BB Reversal",
        "direction": direction,
        "entry": round(entry, 4),
        "stoploss": round(sl, 4),
        "target": round(target, 4),
        "timeframe": timeframe,
        "accuracy": "~80%",
        "tip": "Trade WITH the trend. Short near resistance, Long near support.",
    }


def is_multibagger_candidate(df_daily: pd.DataFrame, threshold: float = 0.40) -> bool:
    if len(df_daily) < 2:
        return False
    prev = float(df_daily["close"].iloc[-2])
    if prev <= 0:
        return False
    pct = abs(float(df_daily["close"].iloc[-1]) - prev) / prev
    return pct >= threshold


def multibagger_signals(df_5m: pd.DataFrame) -> pd.DataFrame:
    df = df_5m.copy()
    df["ema280"] = df["close"].ewm(span=280, adjust=False).mean()
    df = supertrend_signals(df, period=10, mult=3.0)
    df["mb_signal"] = 0
    df.loc[(df["close"] < df["ema280"]) & (df["signal"] == -1), "mb_signal"] = -1
    return df


def multibagger_trade(df: pd.DataFrame, idx: int) -> dict:
    entry = float(df.iloc[idx]["close"])
    return {
        "strategy": "Multi-Bagger Reversal",
        "direction": "SHORT",
        "entry": round(entry, 4),
        "target": round(entry * 0.90, 4),
        "stoploss": "Exit when SuperTrend turns GREEN",
        "prerequisite": "Coin moved 40%+ in last 24 hrs",
    }


def volume_confirmation(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    df = df.copy()
    df["vol_ma"] = df["volume"].rolling(period).mean()
    df["vol_confirmed"] = df["volume"] > df["vol_ma"]
    return df


def calculate_trade_risk(
    entry: float,
    stoploss: float,
    margin_inr: float = TRADE_SIZE_INR,
    leverage: int = 5,
) -> dict:
    position = get_position_size(margin_inr, leverage)
    sl_pct = abs(entry - stoploss) / entry if entry else 0
    risk_inr = position * sl_pct
    ok = risk_inr <= RISK_PER_TRADE_INR
    return {
        "margin_inr": margin_inr,
        "leverage": leverage,
        "position_inr": round(position, 2),
        "sl_pct": round(sl_pct * 100, 3),
        "risk_inr": round(risk_inr, 2),
        "within_limit": ok,
        "warning": None if ok else f"₹{risk_inr:.0f} > ₹{risk_limit_display()} limit! Reduce size or tighten SL.",
    }


def risk_limit_display() -> int:
    return RISK_PER_TRADE_INR


def phase_parameters(phase: int) -> dict:
    return {
        1: {"trades": "1–50", "rr": "1:3", "trailing_sl": False},
        2: {"trades": "51–100", "rr": "1:4", "trailing_sl": False, "htf_bonus": "up to 1:7"},
        3: {"trades": "100+", "rr": "1:4+", "trailing_sl": True, "note": "Increase sizes"},
    }.get(phase, {})


def _resolve_strategy_tf(strategy_key: str, user_tf: str) -> str:
    if strategy_key == "multibagger":
        return "5m"
    if strategy_key == "bb_reversal":
        return user_tf if user_tf in ("15m", "30m", "1h", "1d") else "30m"
    if strategy_key in ("ema_crossover", "supertrend"):
        return user_tf if user_tf in ("30m", "1h") else "30m"
    return user_tf


def _latest_signal_idx(df: pd.DataFrame, col: str = "signal") -> int | None:
    if df.empty or col not in df.columns:
        return None
    positions = np.where(df[col].to_numpy() != 0)[0]
    if len(positions) == 0:
        return None
    return int(positions[-1])


def _trend_from_st(df: pd.DataFrame) -> str | None:
    if df.empty or "st_direction" not in df.columns:
        return None
    d = int(df["st_direction"].iloc[-1])
    if d == 1:
        return "LONG"
    if d == -1:
        return "SHORT"
    return None


def _run_strategy(
    strategy_key: str,
    df: pd.DataFrame,
    timeframe: str,
    *,
    vol_filter: bool,
    mb_eligible: bool | None = None,
) -> dict[str, Any]:
    if df.empty or len(df) < 30:
        return {"error": f"Insufficient {timeframe} data ({len(df)} bars)", "phase": "NO_DATA"}

    if vol_filter and "volume" in df.columns:
        df = volume_confirmation(df)

    out: dict[str, Any] = {"timeframe": timeframe, "bars": len(df)}

    if strategy_key == "ema_crossover":
        sig_df = ema_crossover_signals(df)
        idx = _latest_signal_idx(sig_df)
        last = sig_df.iloc[-1]
        st_dir = "LONG" if last["ema10"] > last["ema30"] else "SHORT"
        if idx is not None and idx > 0 and sig_df.iloc[idx]["signal"] != 0:
            if vol_filter and not bool(sig_df.iloc[idx].get("vol_confirmed", True)):
                out.update({"phase": "WATCH", "primary_label": "EMA cross — volume not confirmed"})
            else:
                trade = ema_crossover_trade(sig_df, idx)
                out.update({
                    "phase": "ENTRY_LONG" if trade.get("direction") == "LONG" else "ENTRY_SHORT",
                    "primary_label": f"Fresh EMA 10/30 cross → {trade.get('direction')}",
                    "signal": int(sig_df.iloc[idx]["signal"]),
                    "trade": trade,
                    "actionable": True,
                })
        else:
            out.update({
                "phase": "TREND_LONG" if st_dir == "LONG" else "TREND_SHORT",
                "primary_label": f"EMA ribbon {st_dir} — waiting for fresh cross",
                "signal": 0,
                "actionable": False,
            })
        out["result_df"] = sig_df.tail(120)
        return out

    if strategy_key == "supertrend":
        sig_df = supertrend_signals(df)
        idx = _latest_signal_idx(sig_df)
        trend = _trend_from_st(sig_df)
        if idx is not None and sig_df.iloc[idx]["signal"] != 0:
            if vol_filter and not bool(sig_df.iloc[idx].get("vol_confirmed", True)):
                out.update({"phase": "WATCH", "primary_label": "SuperTrend flip — volume not confirmed"})
            else:
                trade = supertrend_trade(sig_df, idx)
                out.update({
                    "phase": "ENTRY_LONG" if trade.get("direction") == "LONG" else "ENTRY_SHORT",
                    "primary_label": f"SuperTrend turned {'GREEN' if trade.get('direction') == 'LONG' else 'RED'}",
                    "signal": int(sig_df.iloc[idx]["signal"]),
                    "trade": trade,
                    "actionable": True,
                })
        elif trend:
            out.update({
                "phase": f"TREND_{trend}",
                "primary_label": f"SuperTrend {trend} — hold / wait for flip",
                "signal": 0,
                "actionable": False,
            })
        else:
            out.update({"phase": "NO_SIGNAL", "primary_label": "No SuperTrend bias", "actionable": False})
        out["result_df"] = sig_df.tail(120)
        return out

    if strategy_key == "bb_reversal":
        sig_df = bb_reversal_signals(df)
        idx = _latest_signal_idx(sig_df)
        if idx is not None and sig_df.iloc[idx]["signal"] != 0:
            if vol_filter and not bool(sig_df.iloc[idx].get("vol_confirmed", True)):
                out.update({"phase": "WATCH", "primary_label": "BB re-entry — volume not confirmed"})
            else:
                trade = bb_reversal_trade(sig_df, idx, timeframe)
                out.update({
                    "phase": "ENTRY_LONG" if trade.get("direction") == "LONG" else "ENTRY_SHORT",
                    "primary_label": f"BB band re-entry → {trade.get('direction')}",
                    "signal": int(sig_df.iloc[idx]["signal"]),
                    "trade": trade,
                    "actionable": True,
                })
        else:
            last = sig_df.iloc[-1]
            if last["close"] >= last.get("bb_upper", last["close"]):
                hint = "Price at upper band — watch for SHORT re-entry"
            elif last["close"] <= last.get("bb_lower", last["close"]):
                hint = "Price at lower band — watch for LONG re-entry"
            else:
                hint = "Inside bands — wait for pierce + re-entry"
            out.update({"phase": "WATCH", "primary_label": hint, "signal": 0, "actionable": False})
        out["result_df"] = sig_df.tail(120)
        return out

    if strategy_key == "multibagger":
        if mb_eligible is False:
            return {
                "phase": "MB_SKIP",
                "primary_label": "24h move < 40% — Multi-Bagger prerequisite not met",
                "actionable": False,
                "timeframe": timeframe,
            }
        sig_df = multibagger_signals(df)
        idx = _latest_signal_idx(sig_df, "mb_signal")
        trend_st = _trend_from_st(sig_df)
        if idx is not None and sig_df.iloc[idx]["mb_signal"] == -1:
            if vol_filter and not bool(sig_df.iloc[idx].get("vol_confirmed", True)):
                out.update({"phase": "WATCH", "primary_label": "MB setup — volume not confirmed"})
            else:
                trade = multibagger_trade(sig_df, idx)
                out.update({
                    "phase": "MB_READY",
                    "primary_label": "Price < EMA280 + SuperTrend RED → SHORT",
                    "signal": -1,
                    "trade": trade,
                    "actionable": True,
                })
        else:
            below = bool(sig_df.iloc[-1]["close"] < sig_df.iloc[-1]["ema280"]) if "ema280" in sig_df.columns else False
            out.update({
                "phase": "WATCH" if mb_eligible else "MB_SKIP",
                "primary_label": (
                    "Below EMA280 — wait for SuperTrend RED flip"
                    if below and mb_eligible
                    else "Waiting for 40%+ daily move + EMA280/ST setup"
                ),
                "signal": 0,
                "actionable": False,
                "st_trend": trend_st,
            })
        out["result_df"] = sig_df.tail(120)
        return out

    return {"error": f"Unknown strategy {strategy_key}", "phase": "NO_DATA"}


def _trade_to_plan(trade: dict, risk: dict | None) -> dict | None:
    if not trade or not trade.get("entry"):
        return None
    entry = float(trade["entry"])
    sl = trade.get("stoploss")
    tp = trade.get("target")
    direction = trade.get("direction", "LONG")
    sl_pct = tp_pct = None
    if isinstance(sl, (int, float)) and entry:
        sl_pct = round(abs(entry - float(sl)) / entry * 100, 2)
    if isinstance(tp, (int, float)) and entry:
        tp_pct = round(abs(float(tp) - entry) / entry * 100, 2)
    return {
        "direction": direction,
        "entry": entry,
        "stop_loss": sl if isinstance(sl, (int, float)) else None,
        "take_profit": tp if isinstance(tp, (int, float)) else None,
        "sl_pct": sl_pct,
        "tp_pct": tp_pct,
        "rr_ratio": trade.get("rr", f"1:{RR_RATIO}"),
        "hold_duration": trade.get("timeframe", "30m–1h") + " swing/scalp",
        "risk_inr": (risk or {}).get("risk_inr"),
        "within_risk_limit": (risk or {}).get("within_limit"),
        "strategy_name": trade.get("strategy"),
    }


def analyze_smart_wave(
    symbol: str,
    *,
    market: str = "CoinDCX Futures",
    strategies: list[str],
    primary_tf: str = "30m",
    bars: int = 400,
    groww_token: str = "",
    exchange: str = "NSE",
    margin_inr: float = TRADE_SIZE_INR,
    leverage: int = MAX_LEVERAGE,
    vol_filter: bool = True,
    mb_threshold: float = 0.40,
) -> dict[str, Any]:
    """Run selected Smart Wave strategies for one crypto ticker."""
    enabled = [s for s in strategies if s in STRATEGY_KEYS]
    if not enabled:
        return {
            "symbol": symbol,
            "error": "No strategies selected",
            "phase": "NO_DATA",
            "priority": 0,
            "confidence": 0,
            "actionable": False,
        }

    is_btc = "BTC" in symbol.upper()
    margin = TRADE_SIZE_BTC_INR if is_btc else margin_inr

    mb_eligible: bool | None = None
    if "multibagger" in enabled:
        try:
            daily = normalize_ohlcv(
                fetch_data_for_gap_scan(symbol, "1d", market, groww_token, exchange, limit=10)
            )
            mb_eligible = is_multibagger_candidate(daily, mb_threshold)
        except Exception:
            mb_eligible = False

    strategy_results: dict[str, Any] = {}
    best_key = None
    best_priority = -1

    for key in enabled:
        tf = _resolve_strategy_tf(key, primary_tf)
        try:
            df = normalize_ohlcv(
                fetch_data_for_gap_scan(symbol, tf, market, groww_token, exchange, limit=bars)
            )
        except Exception as exc:
            strategy_results[key] = {"error": str(exc)[:120], "phase": "NO_DATA", "timeframe": tf}
            continue

        result = _run_strategy(
            key, df, tf,
            vol_filter=vol_filter,
            mb_eligible=mb_eligible,
        )
        trade = result.get("trade") or {}
        sl = trade.get("stoploss")
        if trade and isinstance(sl, (int, float)):
            result["risk"] = calculate_trade_risk(
                float(trade["entry"]), float(sl), margin, leverage,
            )
        result["label"] = STRATEGY_LABELS.get(key, key)
        strategy_results[key] = result

        phase = result.get("phase", "NO_SIGNAL")
        pri = PHASE_PRIORITY.get(phase, 0)
        if result.get("actionable") and pri > best_priority:
            best_priority = pri
            best_key = key

    if not strategy_results:
        return {
            "symbol": symbol,
            "error": "No strategy results",
            "phase": "NO_DATA",
            "priority": 0,
            "confidence": 0,
            "actionable": False,
        }

    if best_key:
        best = strategy_results[best_key]
        phase = best.get("phase", "NO_SIGNAL")
        trade = best.get("trade") or {}
        plan = _trade_to_plan(trade, best.get("risk"))
        confidence = 88.0 if best.get("actionable") else 55.0
        if best.get("risk") and not best["risk"].get("within_limit"):
            confidence = min(confidence, 60.0)
        return {
            "symbol": symbol,
            "primary_tf": primary_tf,
            "strategies": strategy_results,
            "best_strategy": best_key,
            "phase": phase,
            "primary_label": best.get("primary_label", ""),
            "priority": PHASE_PRIORITY.get(phase, 0),
            "confidence": confidence,
            "actionable": bool(best.get("actionable")),
            "trade_plan": plan,
            "mb_eligible": mb_eligible,
            "margin_inr": margin,
            "leverage": leverage,
            "liquidation_pct": liquidation_distance(leverage),
        }

    # No actionable — pick highest watch/trend
    watch_key = max(
        strategy_results.keys(),
        key=lambda k: PHASE_PRIORITY.get(strategy_results[k].get("phase", ""), 0),
    )
    watch = strategy_results[watch_key]
    phase = watch.get("phase", "NO_SIGNAL")
    return {
        "symbol": symbol,
        "primary_tf": primary_tf,
        "strategies": strategy_results,
        "best_strategy": watch_key,
        "phase": phase,
        "primary_label": watch.get("primary_label", "No active Smart Wave setup"),
        "priority": PHASE_PRIORITY.get(phase, 0),
        "confidence": 45.0,
        "actionable": False,
        "trade_plan": None,
        "mb_eligible": mb_eligible,
        "margin_inr": margin,
        "leverage": leverage,
        "liquidation_pct": liquidation_distance(leverage),
    }
