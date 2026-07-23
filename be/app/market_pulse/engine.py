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

def _position_notional(capital: float, sl_frac: float, position_sizing: str,
                        capital_allocation_pct: float, risk_pct: float) -> float:
    """Notional exposure to open a new trade with.

    - "pct_of_capital" (default, matches original hard-coded behavior): a fixed
      fraction of current capital, regardless of stop distance.
    - "risk_pct": size so that a stop-loss hit loses exactly `risk_pct`% of
      capital (standard professional risk management) — requires a nonzero
      stop distance; falls back to "pct_of_capital" when no SL is set, since
      risk can't be sized off a stop that doesn't exist.
    """
    max_notional = capital * (capital_allocation_pct / 100.0)
    if position_sizing == "risk_pct" and sl_frac > 0:
        risk_amount = capital * (risk_pct / 100.0)
        return min(risk_amount / sl_frac, max_notional)
    return max_notional


def run_true_backtest(df: pd.DataFrame,
                      entry_rules: list,
                      exit_rules: list,
                      entry_mode: str = "AND",
                      exit_mode: str = "AND",
                      initial_capital: float = 100000.0,
                      commission: float = 0.001,
                      slippage: float = 0.0005,
                      sl_pct: float = 0.0,
                      tp_pct: float = 0.0,
                      *,
                      short_entry_rules: list | None = None,
                      short_exit_rules: list | None = None,
                      short_entry_mode: str = "AND",
                      short_exit_mode: str = "AND",
                      position_sizing: str = "pct_of_capital",
                      capital_allocation_pct: float = 95.0,
                      risk_pct: float = 1.0,
                      benchmark_prices: pd.Series | None = None) -> dict:
    """
    Executes the strategy backtest on the dynamic indicators and rules.

    Long-only callers (the default: `short_entry_rules=None`) see byte-identical
    behavior to the original engine — every new parameter is additive and
    keyword-only, so existing call sites don't need to change.

    Optional professional-grade extensions, all opt-in:
      - Short-selling: pass `short_entry_rules`/`short_exit_rules` to allow the
        engine to also open short positions (single position slot — long and
        short never overlap, same as the original single-slot long model).
      - Risk-based position sizing: `position_sizing="risk_pct"` sizes each
        trade so a stop-loss hit loses a fixed `risk_pct`% of capital, instead
        of always risking a fixed % of capital regardless of stop distance.
      - `benchmark_prices` (defaults to this df's own close) drives a
        buy-and-hold comparison / alpha in the returned metrics.

    The simulation is inherently sequential (each bar's action depends on
    whether a position is already open, which depends on every prior bar), so
    the loop itself can't be vectorized away — but it's driven off raw numpy
    arrays instead of `df.iloc[i]` / `Series.iloc[i]` scalar access. Row-wise
    `.iloc[i]` rebuilds a whole (boxed, mixed-dtype) Series on every call;
    indexing a numpy array is a direct memory read, ~10-20x faster per
    iteration for a loop of this shape.
    """
    shorting_enabled = bool(short_entry_rules)

    # Evaluate signals
    buy_signals = evaluate_ruleset(df, entry_rules, entry_mode)
    sell_signals = evaluate_ruleset(df, exit_rules, exit_mode)
    short_buy_signals = evaluate_ruleset(df, short_entry_rules or [], short_entry_mode)
    short_sell_signals = evaluate_ruleset(df, short_exit_rules or [], short_exit_mode)

    n = len(df)
    close_arr = df["close"].to_numpy(dtype=float)
    high_arr = df["high"].to_numpy(dtype=float)
    low_arr = df["low"].to_numpy(dtype=float)
    buy_arr = buy_signals.to_numpy(dtype=bool)
    sell_arr = sell_signals.to_numpy(dtype=bool)
    short_buy_arr = short_buy_signals.to_numpy(dtype=bool)
    short_sell_arr = short_sell_signals.to_numpy(dtype=bool)
    dates = df.index

    sl_frac = sl_pct / 100.0
    tp_frac = tp_pct / 100.0

    capital = initial_capital
    equity_curve = np.empty(n, dtype=float)
    positions = np.empty(n, dtype=np.int8)
    trades = []

    in_trade = False
    is_short = False
    entry_price = 0.0
    entry_date = None
    entry_notional = 0.0
    capital_before_entry = 0.0
    shares = 0.0  # signed: positive = long qty, negative = short qty
    sl_price = 0.0
    tp_price = 0.0

    for i in range(n):
        price = close_arr[i]
        high = high_arr[i]
        low = low_arr[i]
        date = dates[i]

        exited_this_bar = False

        if in_trade:
            # Check Stop Loss / Take Profit first (if enabled). sl_price/tp_price
            # are fixed at entry (see below) rather than recomputed every bar,
            # since they only depend on entry_price, which doesn't change mid-trade.
            # A short's SL sits ABOVE entry (price rising hurts the short) and its
            # TP sits BELOW entry — the mirror image of a long.
            if is_short:
                sl_triggered = sl_pct > 0.0 and high >= sl_price
                tp_triggered = (not sl_triggered) and tp_pct > 0.0 and low <= tp_price
                cover_signal = short_sell_arr[i]
            else:
                sl_triggered = sl_pct > 0.0 and low <= sl_price
                tp_triggered = (not sl_triggered) and tp_pct > 0.0 and high >= tp_price
                cover_signal = sell_arr[i]

            if sl_triggered or tp_triggered or cover_signal:
                exit_price = sl_price if sl_triggered else tp_price if tp_triggered else price
                if is_short:
                    # Buying back to cover costs more than quoted (slippage against us).
                    final_exit_price = exit_price * (1 + slippage)
                    cost_to_cover = abs(shares) * final_exit_price
                    exit_cost = cost_to_cover * commission
                    capital -= (cost_to_cover + exit_cost)
                else:
                    # Selling to close fetches less than quoted (slippage against us).
                    final_exit_price = exit_price * (1 - slippage)
                    proceeds = shares * final_exit_price
                    exit_cost = proceeds * commission
                    capital += proceeds - exit_cost

                # Round-trip P&L = net cash impact of this trade's entry + exit.
                # Between entry and exit, `capital` is only ever touched by these
                # two events, so this difference is exactly the trade's P&L —
                # for a long-only run with position_sizing="pct_of_capital" this
                # is algebraically identical to the original explicit formula.
                pnl = capital - capital_before_entry
                pnl_pct = (pnl / entry_notional) * 100.0 if entry_notional else 0.0

                trades.append({
                    "entry_date": entry_date,
                    "exit_date": date,
                    "entry_price": entry_price,
                    "exit_price": final_exit_price,
                    "shares": shares,
                    "pnl_val": pnl,
                    "pnl_pct": pnl_pct,
                    "duration_days": (date - entry_date).days if hasattr(date, "days") else 0,
                    "exit_reason": "SL" if sl_triggered else "TP" if tp_triggered else "Signal",
                    "direction": "SHORT" if is_short else "LONG",
                })

                in_trade = False
                is_short = False
                shares = 0.0
                exited_this_bar = True

        if not in_trade and not exited_this_bar:
            if buy_arr[i]:
                # Enter Long trade
                capital_before_entry = capital
                buy_price = price * (1 + slippage)
                notional = _position_notional(capital, sl_frac, position_sizing, capital_allocation_pct, risk_pct)
                entry_cost = notional * commission
                shares = notional / buy_price
                capital -= (notional + entry_cost)
                entry_price = buy_price
                entry_notional = notional
                entry_date = date
                in_trade = True
                is_short = False
                sl_price = entry_price * (1 - sl_frac)
                tp_price = entry_price * (1 + tp_frac)
            elif shorting_enabled and short_buy_arr[i]:
                # Enter Short trade — sell borrowed shares now, buy them back later.
                capital_before_entry = capital
                sell_price = price * (1 - slippage)
                notional = _position_notional(capital, sl_frac, position_sizing, capital_allocation_pct, risk_pct)
                entry_cost = notional * commission
                shares = -(notional / sell_price)
                capital += (notional - entry_cost)
                entry_price = sell_price
                entry_notional = notional
                entry_date = date
                in_trade = True
                is_short = True
                sl_price = entry_price * (1 + sl_frac)
                tp_price = entry_price * (1 - tp_frac)

        # Calculate current equity value (works for both signs of `shares`:
        # a short's negative shares*price correctly nets off its liability).
        equity_curve[i] = capital + (shares * price if in_trade else 0.0)
        positions[i] = 1 if in_trade else 0

    equity_series = pd.Series(equity_curve, index=df.index)
    trades_df = pd.DataFrame(trades)

    # Calculate performance metrics
    metrics = compute_performance_metrics(
        equity_series, trades_df, initial_capital,
        positions=positions, benchmark_prices=benchmark_prices if benchmark_prices is not None else df["close"],
    )

    df_result = df.copy()
    df_result["position"] = positions
    df_result["buy_signal"] = buy_signals
    df_result["sell_signal"] = sell_signals
    if shorting_enabled:
        df_result["short_buy_signal"] = short_buy_signals
        df_result["short_sell_signal"] = short_sell_signals

    return {
        "df": df_result,
        "equity_curve": equity_series,
        "trades": trades_df,
        "metrics": metrics
    }

def _max_drawdown_duration_days(equity: pd.Series) -> float:
    """Longest stretch (in days) from a new equity peak until it's re-surpassed.
    An underwater period still open at the end of the series counts too."""
    if len(equity) < 2:
        return 0.0
    rolling_max = equity.cummax()
    is_underwater = equity < rolling_max
    if not is_underwater.any():
        return 0.0

    idx = equity.index
    use_days = hasattr(idx[-1], "to_pydatetime") or hasattr(idx[-1] - idx[0], "days")
    longest = 0.0
    peak_pos = 0
    for i in range(1, len(equity)):
        if not is_underwater.iloc[i]:
            peak_pos = i
            continue
        span = (idx[i] - idx[peak_pos]).days if use_days else (i - peak_pos)
        longest = max(longest, span)
    return float(longest)


def _max_streak(bools: pd.Series) -> int:
    """Longest run of consecutive True values."""
    if bools.empty:
        return 0
    longest = current = 0
    for v in bools:
        current = current + 1 if v else 0
        longest = max(longest, current)
    return int(longest)


def compute_performance_metrics(
    equity: pd.Series, trades: pd.DataFrame, initial_capital: float,
    *, positions: "np.ndarray | pd.Series | None" = None,
    benchmark_prices: pd.Series | None = None,
    risk_free_rate_pct: float = 0.0,
) -> dict:
    if equity.empty:
        return {}

    total_return = (equity.iloc[-1] - initial_capital) / initial_capital * 100.0

    # Calculate CAGR
    days = (equity.index[-1] - equity.index[0]).days if hasattr(equity.index[-1], "days") else len(equity)
    n_years = max(days / 365.25, 0.01)
    cagr = ((equity.iloc[-1] / initial_capital) ** (1 / n_years) - 1) * 100.0

    # Calculate Sharpe Ratio
    daily_returns = equity.pct_change().dropna()
    rf_daily = risk_free_rate_pct / 100.0 / 252.0
    excess_returns = daily_returns - rf_daily
    sharpe = (excess_returns.mean() / daily_returns.std() * np.sqrt(252)) if daily_returns.std() > 0 else 0.0

    # Sortino Ratio — like Sharpe, but only penalizes downside volatility
    # (upside swings shouldn't count against a strategy the way Sharpe does).
    downside = daily_returns[daily_returns < 0]
    downside_std = downside.std()
    sortino = (excess_returns.mean() / downside_std * np.sqrt(252)) if downside_std and downside_std > 0 else 0.0

    annual_vol = daily_returns.std() * np.sqrt(252) * 100.0 if not daily_returns.empty else 0.0

    # Max drawdown
    rolling_max = equity.cummax()
    drawdown = (equity - rolling_max) / rolling_max * 100.0
    max_dd = drawdown.min()
    max_dd_duration = _max_drawdown_duration_days(equity)

    # Calmar Ratio
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0.0

    # Market exposure — % of bars actually holding a position (either side)
    exposure_pct = None
    if positions is not None:
        pos_arr = np.asarray(positions)
        exposure_pct = round(float(np.mean(pos_arr != 0) * 100.0), 2) if len(pos_arr) else 0.0

    # Buy & hold benchmark / alpha
    buy_hold_return_pct = None
    alpha_pct = None
    if benchmark_prices is not None and len(benchmark_prices) > 1:
        first, last = float(benchmark_prices.iloc[0]), float(benchmark_prices.iloc[-1])
        if first:
            buy_hold_return_pct = round((last / first - 1) * 100.0, 2)
            alpha_pct = round(total_return - buy_hold_return_pct, 2)

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
        expectancy_pct = trades["pnl_pct"].mean()
        expectancy_value = trades["pnl_val"].mean()
        max_consec_wins = _max_streak(trades["pnl_val"] > 0)
        max_consec_losses = _max_streak(trades["pnl_val"] <= 0)

        long_trades = short_trades = None
        long_win_rate = short_win_rate = None
        if "direction" in trades.columns:
            long_df = trades[trades["direction"] == "LONG"]
            short_df = trades[trades["direction"] == "SHORT"]
            long_trades, short_trades = len(long_df), len(short_df)
            if long_trades:
                long_win_rate = round(len(long_df[long_df["pnl_val"] > 0]) / long_trades * 100.0, 2)
            if short_trades:
                short_win_rate = round(len(short_df[short_df["pnl_val"] > 0]) / short_trades * 100.0, 2)
    else:
        n_trades = win_rate = avg_win = avg_loss = 0
        profit_factor = avg_hold = best_trade = worst_trade = 0
        expectancy_pct = expectancy_value = 0
        max_consec_wins = max_consec_losses = 0
        long_trades = short_trades = long_win_rate = short_win_rate = None

    return {
        # --- Original core metrics (unchanged names/meaning — downstream
        # code subscripts these directly, never rename or remove) ---
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
        # --- Additive professional-grade metrics ---
        "sortino_ratio": round(sortino, 3),
        "annual_volatility_pct": round(annual_vol, 2),
        "max_drawdown_duration_days": round(max_dd_duration, 1),
        "exposure_pct": exposure_pct,
        "expectancy_pct": round(expectancy_pct, 3) if expectancy_pct is not None else 0,
        "expectancy_value": round(expectancy_value, 2) if expectancy_value is not None else 0,
        "max_consecutive_wins": max_consec_wins,
        "max_consecutive_losses": max_consec_losses,
        "buy_hold_return_pct": buy_hold_return_pct,
        "alpha_pct": alpha_pct,
        "long_trades": long_trades,
        "short_trades": short_trades,
        "long_win_rate_pct": long_win_rate,
        "short_win_rate_pct": short_win_rate,
    }
