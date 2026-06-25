"""Transparent backtester for strategy signal evaluation."""

import numpy as np
import pandas as pd


def backtest_signals(df: pd.DataFrame, signal_col: str = "signal", costs_pct: float = 0.0005) -> dict:
    data = df.copy().dropna(subset=["close"])
    position = 0
    entry_price = None
    trades = []

    for ts, row in data.iterrows():
        sig = row[signal_col]
        price = row["close"]
        if sig == 1 and position <= 0:
            if position == -1:
                pnl = (entry_price - price) / entry_price - costs_pct
                trades.append({"exit_time": ts, "side": "short", "pnl_pct": pnl, "entry_price": entry_price, "exit_price": price})
            position = 1
            entry_price = price
        elif sig == -1 and position >= 0:
            if position == 1:
                pnl = (price - entry_price) / entry_price - costs_pct
                trades.append({"exit_time": ts, "side": "long", "pnl_pct": pnl, "entry_price": entry_price, "exit_price": price})
            position = -1
            entry_price = price

    if position != 0 and entry_price is not None:
        last_price = data["close"].iloc[-1]
        if position == 1:
            pnl = (last_price - entry_price) / entry_price - costs_pct
            trades.append({"exit_time": data.index[-1], "side": "long (open)", "pnl_pct": pnl, "entry_price": entry_price, "exit_price": last_price})
        else:
            pnl = (entry_price - last_price) / entry_price - costs_pct
            trades.append({"exit_time": data.index[-1], "side": "short (open)", "pnl_pct": pnl, "entry_price": entry_price, "exit_price": last_price})

    trades_df = pd.DataFrame(trades)
    if trades_df.empty:
        return {
            "num_trades": 0,
            "win_rate_pct": None,
            "total_return_pct": 0.0,
            "avg_return_per_trade_pct": None,
            "max_drawdown_pct": 0.0,
            "trades": [],
        }

    wins = (trades_df["pnl_pct"] > 0).sum()
    win_rate = 100 * wins / len(trades_df)
    equity_curve = (1 + trades_df["pnl_pct"]).cumprod()
    running_max = equity_curve.cummax()
    drawdown = (equity_curve - running_max) / running_max
    max_dd = drawdown.min() * 100
    total_return = (equity_curve.iloc[-1] - 1) * 100

    trade_records = []
    for _, t in trades_df.iterrows():
        trade_records.append({
            "exit_time": str(t["exit_time"]),
            "side": t["side"],
            "pnl_pct": round(float(t["pnl_pct"]) * 100, 3),
            "entry_price": round(float(t["entry_price"]), 2),
            "exit_price": round(float(t["exit_price"]), 2),
        })

    return {
        "num_trades": len(trades_df),
        "win_rate_pct": round(win_rate, 2),
        "total_return_pct": round(total_return, 2),
        "avg_return_per_trade_pct": round(trades_df["pnl_pct"].mean() * 100, 3),
        "max_drawdown_pct": round(max_dd, 2),
        "trades": trade_records,
    }
