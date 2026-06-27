"""Live bar signal evaluation for strategy entry/exit rules."""

from __future__ import annotations

import pandas as pd

from app.market_pulse.indicators import calculate_dynamic_indicators


def _eval_rule_on_row(df: pd.DataFrame, rule: dict, row_idx: int = -1) -> bool:
    if df.empty or len(df) < 2:
        return False
    row = df.iloc[row_idx]
    prev = df.iloc[row_idx - 1] if row_idx < 0 else (df.iloc[row_idx - 1] if row_idx > 0 else None)

    l_val = row.get(rule["left"])
    if rule.get("right_type") == "value":
        r_val = float(rule["right_val"])
    else:
        r_val = row.get(rule["right_val"])

    if l_val is None or r_val is None:
        return False

    op = rule.get("op", "")
    if op == ">":
        return l_val > r_val
    if op == "<":
        return l_val < r_val
    if op == ">=":
        return l_val >= r_val
    if op == "<=":
        return l_val <= r_val
    if op == "==":
        return l_val == r_val
    if "crosses" in op and prev is not None:
        prev_l = prev.get(rule["left"])
        prev_r = float(rule["right_val"]) if rule.get("right_type") == "value" else prev.get(rule["right_val"])
        if prev_l is None or prev_r is None:
            return False
        if op == "crosses above":
            return prev_l < prev_r and l_val > r_val
        if op == "crosses below":
            return prev_l > prev_r and l_val < r_val
    return False


def eval_rules_on_last_bar(df: pd.DataFrame, rules: list, mode: str = "AND") -> bool:
    if not rules:
        return False
    matched = [_eval_rule_on_row(df, r) for r in rules]
    if not matched:
        return False
    if "ALL" in (mode or "AND").upper() or mode.upper() == "AND":
        return all(matched)
    return any(matched)


def evaluate_trade_setup(
    df: pd.DataFrame,
    indicators: list,
    entry_rules: list,
    exit_rules: list | None = None,
    entry_mode: str = "AND",
    exit_mode: str = "AND",
) -> dict:
    """
    Evaluate latest candle for entry (BUY setup) and optional exit (SELL setup).
    Returns {signal, entry_active, exit_active, close, bar_time}.
    """
    if df is None or df.empty or len(df) < 10:
        return {
            "signal": "NONE",
            "entry_active": False,
            "exit_active": False,
            "close": None,
            "bar_time": None,
        }

    df_ind = calculate_dynamic_indicators(df.copy(), indicators)
    entry_active = eval_rules_on_last_bar(df_ind, entry_rules, entry_mode)
    exit_active = False
    if exit_rules:
        exit_active = eval_rules_on_last_bar(df_ind, exit_rules, exit_mode)

    signal = "NONE"
    if entry_active:
        signal = "BUY"
    elif exit_active:
        signal = "EXIT"

    close = float(df_ind["close"].iloc[-1])
    bar_time = str(df_ind.index[-1]) if len(df_ind.index) else None

    return {
        "signal": signal,
        "entry_active": entry_active,
        "exit_active": exit_active,
        "close": close,
        "bar_time": bar_time,
    }
