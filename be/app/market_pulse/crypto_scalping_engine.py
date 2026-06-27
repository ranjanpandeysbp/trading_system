"""
crypto_scalping_engine.py
-------------------------
EMA trend filter + VWAP pullback + RSI confirmation scalping for crypto OHLCV.
Rule-based backtester with ATR stops, fees, slippage, and daily limits.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv

SCALPING_TF_OPTIONS = ["1m", "5m"]

PHASE_PRIORITY = {
    "ENTRY_LONG": 100,
    "ENTRY_SHORT": 100,
    "WATCH_LONG": 55,
    "WATCH_SHORT": 55,
    "NO_SIGNAL": 15,
    "NO_DATA": 0,
}


@dataclass
class BacktestConfig:
    risk_pct: float = 0.5
    atr_mult_stop: float = 1.2
    reward_risk: float = 1.5
    fee_pct: float = 0.04
    slippage_pct: float = 0.02
    starting_equity: float = 10_000.0
    max_trades_per_day: int = 10
    max_daily_loss_pct: float = 3.0
    vwap_tolerance_pct: float = 0.05
    ema_fast: int = 9
    ema_slow: int = 21
    rsi_period: int = 14
    atr_period: int = 14


@dataclass
class Trade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp | None = None
    direction: str = ""
    entry_price: float = 0.0
    exit_price: float = 0.0
    stop_price: float = 0.0
    target_price: float = 0.0
    size: float = 0.0
    pnl: float = 0.0
    exit_reason: str = ""


def load_ohlcv_csv(csv_path: str) -> pd.DataFrame:
    """Load OHLCV from CSV and return normalized datetime-indexed DataFrame."""
    df = pd.read_csv(csv_path)
    df.columns = [c.strip().lower() for c in df.columns]
    required = {"timestamp", "open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV is missing required columns: {missing}")

    ts = df["timestamp"]
    if pd.api.types.is_numeric_dtype(ts):
        unit = "ms" if ts.iloc[0] > 10**11 else "s"
        idx = pd.to_datetime(ts, unit=unit)
    else:
        idx = pd.to_datetime(ts)

    out = df[["open", "high", "low", "close", "volume"]].copy()
    out.index = idx
    out = out.sort_index()
    return normalize_ohlcv(out)


def fetch_scalping_data(
    symbol: str,
    timeframe: str,
    market: str,
    groww_token: str = "",
    exchange: str = "NSE",
    limit: int = 800,
) -> pd.DataFrame:
    df = fetch_data_for_gap_scan(symbol, timeframe, market, groww_token, exchange, limit=limit)
    return normalize_ohlcv(df).tail(limit)


def add_indicators(df: pd.DataFrame, cfg: BacktestConfig | None = None) -> pd.DataFrame:
    cfg = cfg or BacktestConfig()
    df = normalize_ohlcv(df)
    if df.empty:
        return df

    out = df.copy()
    out["ema_fast"] = out["close"].ewm(span=cfg.ema_fast, adjust=False).mean()
    out["ema_slow"] = out["close"].ewm(span=cfg.ema_slow, adjust=False).mean()

    dates = pd.Series(out.index.date, index=out.index)
    typical_price = (out["high"] + out["low"] + out["close"]) / 3
    tp_vol = typical_price * out["volume"]
    cum_tp_vol = tp_vol.groupby(dates).cumsum()
    cum_vol = out["volume"].groupby(dates).cumsum()
    out["vwap"] = cum_tp_vol / cum_vol.replace(0, np.nan)

    delta = out["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / cfg.rsi_period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / cfg.rsi_period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out["rsi"] = (100 - (100 / (1 + rs))).fillna(50)

    prev_close = out["close"].shift(1)
    tr = pd.concat([
        out["high"] - out["low"],
        (out["high"] - prev_close).abs(),
        (out["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    out["atr"] = tr.ewm(alpha=1 / cfg.atr_period, adjust=False).mean()
    return out


def generate_signal(
    row: pd.Series,
    prev_row: pd.Series,
    vwap_tolerance_pct: float = 0.05,
) -> str:
    uptrend = row["ema_fast"] > row["ema_slow"]
    downtrend = row["ema_fast"] < row["ema_slow"]

    near_vwap = abs(row["close"] - row["vwap"]) / row["close"] * 100 <= vwap_tolerance_pct
    crossed_back_above = prev_row["close"] <= prev_row["vwap"] and row["close"] > row["vwap"]
    crossed_back_below = prev_row["close"] >= prev_row["vwap"] and row["close"] < row["vwap"]

    long_trigger = uptrend and (near_vwap or crossed_back_above) and row["close"] > row["vwap"]
    short_trigger = downtrend and (near_vwap or crossed_back_below) and row["close"] < row["vwap"]

    long_confirm = 50 < row["rsi"] < 70
    short_confirm = 30 < row["rsi"] < 50

    if long_trigger and long_confirm:
        return "long"
    if short_trigger and short_confirm:
        return "short"
    return "flat"


def _build_trade_plan(signal: str, entry_price: float, atr: float, cfg: BacktestConfig) -> dict[str, Any]:
    stop_dist = atr * cfg.atr_mult_stop
    slip = entry_price * cfg.slippage_pct / 100
    if signal == "long":
        entry = entry_price + slip
        stop = entry - stop_dist
        target = entry + stop_dist * cfg.reward_risk
        direction = "LONG"
    else:
        entry = entry_price - slip
        stop = entry + stop_dist
        target = entry - stop_dist * cfg.reward_risk
        direction = "SHORT"

    sl_pct = abs(entry - stop) / entry * 100 if entry else 0
    tp_pct = abs(target - entry) / entry * 100 if entry else 0
    return {
        "direction": direction,
        "entry": round(entry, 6),
        "stop_loss": round(stop, 6),
        "take_profit": round(target, 6),
        "sl_pct": round(sl_pct, 3),
        "tp_pct": round(tp_pct, 3),
        "rr_ratio": cfg.reward_risk,
        "hold_duration": "5–45 min (scalp)",
        "notes": f"ATR stop ×{cfg.atr_mult_stop} · R:R 1:{cfg.reward_risk}",
    }


def run_backtest(df: pd.DataFrame, cfg: BacktestConfig | None = None) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    cfg = cfg or BacktestConfig()
    df = add_indicators(df, cfg)
    if len(df) < 2:
        return pd.DataFrame(), pd.DataFrame(), {}

    equity = cfg.starting_equity
    equity_curve: list[dict[str, Any]] = []
    trades: list[Trade] = []
    open_trade: Trade | None = None
    day_trade_count: dict[Any, int] = {}
    day_start_equity: dict[Any, float] = {}

    for i in range(1, len(df)):
        row = df.iloc[i]
        prev_row = df.iloc[i - 1]
        ts = df.index[i]
        day = ts.date() if hasattr(ts, "date") else ts

        day_trade_count.setdefault(day, 0)
        if day not in day_start_equity:
            day_start_equity[day] = equity

        equity_curve.append({"timestamp": ts, "equity": equity})

        if open_trade is not None:
            hit_stop = (
                (open_trade.direction == "long" and row["low"] <= open_trade.stop_price)
                or (open_trade.direction == "short" and row["high"] >= open_trade.stop_price)
            )
            hit_target = (
                (open_trade.direction == "long" and row["high"] >= open_trade.target_price)
                or (open_trade.direction == "short" and row["low"] <= open_trade.target_price)
            )

            if hit_stop or hit_target:
                exit_price = open_trade.stop_price if hit_stop else open_trade.target_price
                slip = exit_price * cfg.slippage_pct / 100
                exit_price = exit_price - slip if open_trade.direction == "long" else exit_price + slip

                gross_move = (
                    (exit_price - open_trade.entry_price)
                    if open_trade.direction == "long"
                    else (open_trade.entry_price - exit_price)
                )
                gross_pnl = gross_move * open_trade.size
                fees = (open_trade.entry_price + exit_price) * open_trade.size * (cfg.fee_pct / 100)
                pnl = gross_pnl - fees

                open_trade.exit_time = ts
                open_trade.exit_price = exit_price
                open_trade.pnl = pnl
                open_trade.exit_reason = "stop" if hit_stop else "target"

                equity += pnl
                trades.append(open_trade)
                open_trade = None
            else:
                continue

        daily_pnl_pct = (equity - day_start_equity[day]) / day_start_equity[day] * 100
        if daily_pnl_pct <= -cfg.max_daily_loss_pct:
            continue
        if day_trade_count[day] >= cfg.max_trades_per_day:
            continue

        signal = generate_signal(row, prev_row, cfg.vwap_tolerance_pct)
        if signal == "flat" or pd.isna(row["atr"]) or row["atr"] == 0:
            continue

        entry_price = row["close"]
        slip = entry_price * cfg.slippage_pct / 100
        entry_price = entry_price + slip if signal == "long" else entry_price - slip

        stop_dist = row["atr"] * cfg.atr_mult_stop
        if signal == "long":
            stop_price = entry_price - stop_dist
            target_price = entry_price + stop_dist * cfg.reward_risk
        else:
            stop_price = entry_price + stop_dist
            target_price = entry_price - stop_dist * cfg.reward_risk

        risk_amount = equity * (cfg.risk_pct / 100)
        size = risk_amount / stop_dist if stop_dist > 0 else 0
        if size <= 0:
            continue

        open_trade = Trade(
            entry_time=ts,
            direction=signal,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            size=size,
        )
        day_trade_count[day] += 1

    trades_df = pd.DataFrame([t.__dict__ for t in trades])
    equity_df = pd.DataFrame(equity_curve)
    metrics = compute_performance_metrics(trades_df, equity_df, cfg)
    return trades_df, equity_df, metrics


def compute_performance_metrics(
    trades_df: pd.DataFrame,
    equity_df: pd.DataFrame,
    cfg: BacktestConfig,
) -> dict[str, Any]:
    if trades_df.empty:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "total_return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "final_equity": cfg.starting_equity,
        }

    wins = trades_df[trades_df["pnl"] > 0]
    losses = trades_df[trades_df["pnl"] <= 0]
    win_rate = len(wins) / len(trades_df) * 100

    gross_profit = wins["pnl"].sum()
    gross_loss = -losses["pnl"].sum()
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    final_equity = cfg.starting_equity + trades_df["pnl"].sum()
    total_return_pct = (final_equity - cfg.starting_equity) / cfg.starting_equity * 100

    max_drawdown = 0.0
    if not equity_df.empty and "equity" in equity_df.columns:
        running_max = equity_df["equity"].cummax()
        drawdown = (equity_df["equity"] - running_max) / running_max * 100
        max_drawdown = float(drawdown.min())

    return {
        "total_trades": len(trades_df),
        "win_rate": round(win_rate, 1),
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else 999.0,
        "total_return_pct": round(total_return_pct, 2),
        "max_drawdown_pct": round(max_drawdown, 2),
        "avg_win": round(float(wins["pnl"].mean()), 2) if len(wins) else 0.0,
        "avg_loss": round(float(losses["pnl"].mean()), 2) if len(losses) else 0.0,
        "final_equity": round(final_equity, 2),
        "long_trades": int((trades_df["direction"] == "long").sum()),
        "short_trades": int((trades_df["direction"] == "short").sum()),
    }


def _trend_label(row: pd.Series) -> str:
    if row["ema_fast"] > row["ema_slow"]:
        return "UPTREND"
    if row["ema_fast"] < row["ema_slow"]:
        return "DOWNTREND"
    return "FLAT"


def analyze_crypto_scalping(
    df: pd.DataFrame,
    *,
    chart_tf: str = "5m",
    cfg: BacktestConfig | None = None,
) -> dict[str, Any]:
    """Run live signal + backtest on OHLCV window."""
    cfg = cfg or BacktestConfig()
    df = normalize_ohlcv(df)
    min_bars = max(cfg.ema_slow, cfg.atr_period, cfg.rsi_period) + 5

    if df.empty or len(df) < min_bars:
        return {
            "phase": "NO_DATA",
            "primary_label": f"Insufficient data ({len(df)} bars, need {min_bars}+)",
            "priority": 0,
            "actionable": False,
            "confidence": 0.0,
            "chart_tf": chart_tf,
        }

    enriched = add_indicators(df, cfg)
    trades_df, equity_df, metrics = run_backtest(df, cfg)

    last = enriched.iloc[-1]
    prev = enriched.iloc[-2]
    signal = generate_signal(last, prev, cfg.vwap_tolerance_pct)
    trend = _trend_label(last)
    price = float(last["close"])
    rsi = float(last["rsi"])
    vwap = float(last["vwap"]) if pd.notna(last["vwap"]) else price
    vwap_dist_pct = abs(price - vwap) / price * 100 if price else 0

    trade_plan = None
    phase = "NO_SIGNAL"
    confidence = 35.0
    actionable = False

    if signal == "long":
        phase = "ENTRY_LONG"
        confidence = 70 + min(20, (rsi - 50) / 2)
        actionable = True
        trade_plan = _build_trade_plan("long", price, float(last["atr"]), cfg)
        primary_label = (
            f"LONG scalp — {trend} · VWAP pullback · RSI {rsi:.1f} · "
            f"close ${price:,.4f} > VWAP ${vwap:,.4f}"
        )
    elif signal == "short":
        phase = "ENTRY_SHORT"
        confidence = 70 + min(20, (50 - rsi) / 2)
        actionable = True
        trade_plan = _build_trade_plan("short", price, float(last["atr"]), cfg)
        primary_label = (
            f"SHORT scalp — {trend} · VWAP rejection · RSI {rsi:.1f} · "
            f"close ${price:,.4f} < VWAP ${vwap:,.4f}"
        )
    elif trend == "UPTREND" and price > vwap and 45 < rsi < 70:
        phase = "WATCH_LONG"
        confidence = 50.0
        primary_label = (
            f"Watch LONG — uptrend · price above VWAP · wait for pullback "
            f"(dist {vwap_dist_pct:.2f}%) · RSI {rsi:.1f}"
        )
    elif trend == "DOWNTREND" and price < vwap and 30 < rsi < 55:
        phase = "WATCH_SHORT"
        confidence = 50.0
        primary_label = (
            f"Watch SHORT — downtrend · price below VWAP · wait for pop to VWAP "
            f"(dist {vwap_dist_pct:.2f}%) · RSI {rsi:.1f}"
        )
    else:
        primary_label = (
            f"No setup — {trend} · RSI {rsi:.1f} · "
            f"VWAP dist {vwap_dist_pct:.2f}% · filters not aligned"
        )

    trade_rows = []
    if not trades_df.empty:
        for _, t in trades_df.tail(20).iterrows():
            trade_rows.append({
                "entry_time": str(t.get("entry_time", "")),
                "exit_time": str(t.get("exit_time", "")),
                "direction": str(t.get("direction", "")).upper(),
                "entry": round(float(t.get("entry_price", 0)), 4),
                "exit": round(float(t.get("exit_price", 0)), 4),
                "pnl": round(float(t.get("pnl", 0)), 2),
                "reason": t.get("exit_reason", ""),
            })

    return {
        "phase": phase,
        "primary_label": primary_label,
        "priority": PHASE_PRIORITY.get(phase, 0),
        "actionable": actionable,
        "confidence": round(confidence, 1),
        "chart_tf": chart_tf,
        "price": price,
        "trend": trend,
        "rsi": round(rsi, 1),
        "vwap": round(vwap, 6),
        "vwap_dist_pct": round(vwap_dist_pct, 3),
        "ema_fast": round(float(last["ema_fast"]), 6),
        "ema_slow": round(float(last["ema_slow"]), 6),
        "atr": round(float(last["atr"]), 6) if pd.notna(last["atr"]) else None,
        "live_signal": signal,
        "trade_plan": trade_plan,
        "backtest_metrics": metrics,
        "backtest_trades": trade_rows,
        "result_df": enriched,
        "equity_df": equity_df,
    }
