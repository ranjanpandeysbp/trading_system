"""
engine.py
---------
Advanced backtesting engine parsing dynamic custom strategies, simulating trades,
and outputting professional portfolio analytics.
"""

import pandas as pd
import numpy as np

def evaluate_condition(df: pd.DataFrame, left: str, op: str, right_type: str, right_val: str) -> pd.Series:
    """
    Evaluates a single rule condition on the DataFrame and returns a boolean Series.
    """
    try:
        # Get left series
        s_left = df[left]
        
        # Get right series or value
        if right_type == "indicator":
            s_right = df[right_val]
        else:
            s_right = pd.Series(float(right_val), index=df.index)
            
        # Apply operator
        if op == ">":
            return s_left > s_right
        elif op == "<":
            return s_left < s_right
        elif op == "==":
            return s_left == s_right
        elif op == ">=":
            return s_left >= s_right
        elif op == "<=":
            return s_left <= s_right
        elif op == "crosses above":
            return (s_left > s_right) & (s_left.shift(1) <= s_right.shift(1))
        elif op == "crosses below":
            return (s_left < s_right) & (s_left.shift(1) >= s_right.shift(1))
        else:
            return pd.Series(False, index=df.index)
    except Exception as e:
        print(f"Error evaluating condition ({left} {op} {right_val}): {e}")
        return pd.Series(False, index=df.index)

def evaluate_ruleset(df: pd.DataFrame, rules: list, mode: str = "AND") -> pd.Series:
    """
    rules: list of dicts like:
        [
            {"left": "rsi_14", "op": "<", "right_type": "value", "right_val": "30"},
            {"left": "close", "op": "crosses above", "right_type": "indicator", "right_val": "ema_20"}
        ]
    mode: "AND" or "OR"
    """
    if not rules:
        return pd.Series(False, index=df.index)
        
    series_list = []
    for r in rules:
        cond_series = evaluate_condition(df, r["left"], r["op"], r["right_type"], r["right_val"])
        series_list.append(cond_series)
        
    if mode == "AND":
        result = series_list[0]
        for s in series_list[1:]:
            result = result & s
    else:
        result = series_list[0]
        for s in series_list[1:]:
            result = result | s
            
    return result

def run_true_backtest(df: pd.DataFrame,
                      entry_rules: list,
                      exit_rules: list,
                      entry_mode: str = "AND",
                      exit_mode: str = "AND",
                      initial_capital: float = 100000.0,
                      commission: float = 0.001,
                      slippage: float = 0.0005,
                      sl_pct: float = 0.0,
                      tp_pct: float = 0.0) -> dict:
    """
    Executes the strategy backtest on the dynamic indicators and rules.
    """
    # Evaluate signals
    buy_signals = evaluate_ruleset(df, entry_rules, entry_mode)
    sell_signals = evaluate_ruleset(df, exit_rules, exit_mode)
    
    capital = initial_capital
    equity_curve = []
    trades = []
    
    in_trade = False
    entry_price = 0.0
    entry_date = None
    shares = 0.0
    
    # Track positions for charting (1 for in trade, 0 for out)
    positions = []
    
    for i in range(len(df)):
        row = df.iloc[i]
        price = row["close"]
        high = row["high"]
        low = row["low"]
        date = df.index[i]
        
        buy_sig = buy_signals.iloc[i]
        sell_sig = sell_signals.iloc[i]
        
        exited_this_bar = False
        pnl = 0.0
        pnl_pct = 0.0
        
        if in_trade:
            # Check Stop Loss / Take Profit first (if enabled)
            sl_triggered = False
            tp_triggered = False
            exit_price = price
            
            if sl_pct > 0.0:
                sl_price = entry_price * (1 - sl_pct / 100.0)
                if low <= sl_price:
                    sl_triggered = True
                    exit_price = sl_price
                    
            if tp_pct > 0.0 and not sl_triggered:
                tp_price = entry_price * (1 + tp_pct / 100.0)
                if high >= tp_price:
                    tp_triggered = True
                    exit_price = tp_price
            
            if sl_triggered or tp_triggered or sell_sig:
                # Exit trade
                final_exit_price = exit_price * (1 - slippage)
                proceeds = shares * final_exit_price
                exit_cost = proceeds * commission
                capital += proceeds - exit_cost
                
                pnl = proceeds - exit_cost - (shares * entry_price) - (shares * entry_price * commission)
                pnl_pct = (pnl / (shares * entry_price)) * 100.0
                
                trades.append({
                    "entry_date": entry_date,
                    "exit_date": date,
                    "entry_price": entry_price,
                    "exit_price": final_exit_price,
                    "shares": shares,
                    "pnl_val": pnl,
                    "pnl_pct": pnl_pct,
                    "duration_days": (date - entry_date).days if hasattr(date, "days") else 0,
                    "exit_reason": "SL" if sl_triggered else "TP" if tp_triggered else "Signal"
                })
                
                in_trade = False
                shares = 0.0
                exited_this_bar = True
                
        if buy_sig and not in_trade and not exited_this_bar:
            # Enter Long trade
            buy_price = price * (1 + slippage)
            invest = capital * 0.95  # Allocate 95% of current capital
            entry_cost = invest * commission
            shares = invest / buy_price
            capital -= (invest + entry_cost)
            entry_price = buy_price
            entry_date = date
            in_trade = True
            
        # Calculate current equity value
        current_equity = capital + (shares * price if in_trade else 0.0)
        equity_curve.append(current_equity)
        positions.append(1 if in_trade else 0)
        
    equity_series = pd.Series(equity_curve, index=df.index)
    trades_df = pd.DataFrame(trades)
    
    # Calculate performance metrics
    metrics = compute_performance_metrics(equity_series, trades_df, initial_capital)
    
    df_result = df.copy()
    df_result["position"] = positions
    df_result["buy_signal"] = buy_signals
    df_result["sell_signal"] = sell_signals
    
    return {
        "df": df_result,
        "equity_curve": equity_series,
        "trades": trades_df,
        "metrics": metrics
    }

def compute_performance_metrics(equity: pd.Series, trades: pd.DataFrame, initial_capital: float) -> dict:
    if equity.empty:
        return {}
        
    total_return = (equity.iloc[-1] - initial_capital) / initial_capital * 100.0
    
    # Calculate CAGR
    days = (equity.index[-1] - equity.index[0]).days if hasattr(equity.index[-1], "days") else len(equity)
    n_years = max(days / 365.25, 0.01)
    cagr = ((equity.iloc[-1] / initial_capital) ** (1 / n_years) - 1) * 100.0
    
    # Calculate Sharpe Ratio
    daily_returns = equity.pct_change().dropna()
    sharpe = (daily_returns.mean() / daily_returns.std() * np.sqrt(252)) if daily_returns.std() > 0 else 0.0
    
    # Max drawdown
    rolling_max = equity.cummax()
    drawdown = (equity - rolling_max) / rolling_max * 100.0
    max_dd = drawdown.min()
    
    # Calmar Ratio
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0.0
    
    # Trade statistics
    if not trades.empty:
        n_trades = len(trades)
        winners = trades[trades["pnl_val"] > 0]
        win_rate = len(winners) / n_trades * 100.0
        avg_win = winners["pnl_pct"].mean() if not winners.empty else 0.0
        losers = trades[trades["pnl_val"] <= 0]
        avg_loss = losers["pnl_pct"].mean() if not losers.empty else 0.0
        profit_factor = (
            winners["pnl_val"].sum() / abs(losers["pnl_val"].sum())
            if not losers.empty and losers["pnl_val"].sum() != 0 else float("inf")
        )
        avg_hold = trades["duration_days"].mean()
        best_trade = trades["pnl_pct"].max()
        worst_trade = trades["pnl_pct"].min()
    else:
        n_trades = win_rate = avg_win = avg_loss = 0
        profit_factor = avg_hold = best_trade = worst_trade = 0
        
    return {
        "total_return_pct": round(total_return, 2),
        "cagr_pct": round(cagr, 2),
        "sharpe_ratio": round(sharpe, 3),
        "max_drawdown_pct": round(max_dd, 2),
        "calmar_ratio": round(calmar, 3),
        "n_trades": n_trades,
        "win_rate_pct": round(win_rate, 2),
        "avg_win_pct": round(avg_win, 2),
        "avg_loss_pct": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 3),
        "avg_hold_days": round(avg_hold, 1),
        "best_trade_pct": round(best_trade, 2),
        "worst_trade_pct": round(worst_trade, 2),
        "final_capital": round(equity.iloc[-1], 2),
    }
