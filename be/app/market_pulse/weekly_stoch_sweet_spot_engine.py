"""
weekly_stoch_sweet_spot_engine.py
---------------------------------
Weekly Stochastic "Sweet Spot" strategy:
  Enter when weekly %K crosses above %D into the 32–80% zone (from below),
  with daily volume confirmation. Hold through overbought; exit when %K
  crosses below %D beneath the 80% threshold.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv

SWEET_BOTTOM = 32.0
SWEET_TOP = 80.0

PERIOD_BARS: dict[str, int] = {
    "2y": 504,
    "5y": 1260,
    "10y": 2520,
}

PHASE_PRIORITY = {
    "ENTRY_SIGNAL": 100,
    "IN_TRADE": 90,
    "EXIT_SIGNAL": 85,
    "APPROACHING": 70,
    "SWEET_WATCH": 55,
    "NEUTRAL": 15,
    "NO_DATA": 0,
}


def stochastic(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    k_period: int = 14,
    d_period: int = 3,
) -> pd.DataFrame:
    lowest_low = low.rolling(k_period).min()
    highest_high = high.rolling(k_period).max()
    k = 100 * (close - lowest_low) / (highest_high - lowest_low + 1e-10)
    d = k.rolling(d_period).mean()
    return pd.DataFrame({"K": k, "D": d})


def _resample_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    if daily.empty:
        return pd.DataFrame()
    work = daily.copy()
    work.columns = [str(c).lower() for c in work.columns]
    weekly = work.resample("W").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()
    return weekly


def fetch_daily_weekly(
    symbol: str,
    market: str,
    groww_token: str = "",
    exchange: str = "NSE",
    period: str = "5y",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch daily OHLCV and resample to weekly (Groww/CoinDCX + yfinance fallback)."""
    is_crypto = "CoinDCX" in market
    limit = PERIOD_BARS.get(period, 1260)

    daily = fetch_data_for_gap_scan(
        symbol, "1d", market, groww_token, exchange, limit=limit,
    )
    daily = normalize_ohlcv(daily)

    if daily.empty or len(daily) < 80:
        daily = normalize_ohlcv(
            fetch_ohlcv_yfinance(symbol, "1d", is_crypto=is_crypto, limit=limit),
        )

    if daily.empty or len(daily) < 80:
        try:
            import yfinance as yf
            from app.market_pulse.gap_trading import _yfinance_symbol

            yf_sym = _yfinance_symbol(symbol, is_crypto)
            yf_period = period if period in PERIOD_BARS else "5y"
            raw = yf.download(
                yf_sym, period=yf_period, interval="1d",
                progress=False, auto_adjust=True, threads=False,
            )
            if not raw.empty:
                if isinstance(raw.columns, pd.MultiIndex):
                    raw.columns = [c[0].lower() for c in raw.columns]
                else:
                    raw.columns = [c.lower() for c in raw.columns]
                daily = normalize_ohlcv(raw[["open", "high", "low", "close", "volume"]])
        except Exception:
            pass

    weekly = _resample_weekly(daily)
    return daily, weekly


def _vol_confirm_for_week(
    week_end: pd.Timestamp,
    daily: pd.DataFrame,
    daily_vol_above: pd.Series,
) -> bool:
    week_start = week_end - pd.Timedelta(days=6)
    mask = (daily_vol_above.index > week_start) & (daily_vol_above.index <= week_end)
    vals = daily_vol_above[mask]
    return bool(vals.mean() >= 0.5) if len(vals) > 0 else False


def generate_signals(
    weekly: pd.DataFrame,
    daily: pd.DataFrame,
    k_period: int = 14,
    d_period: int = 3,
    vol_lookback: int = 20,
) -> pd.DataFrame:
    stoch = stochastic(weekly["high"], weekly["low"], weekly["close"], k_period, d_period)
    df = weekly.copy()
    df["K"] = stoch["K"]
    df["D"] = stoch["D"]
    df["in_sweet_spot"] = (df["K"] >= SWEET_BOTTOM) & (df["K"] <= SWEET_TOP)

    daily_vol = daily["volume"] if "volume" in daily.columns else pd.Series(0, index=daily.index)
    daily_vol_ma = daily_vol.rolling(vol_lookback).mean()
    daily_vol_above = daily_vol > daily_vol_ma
    df["vol_confirm"] = [_vol_confirm_for_week(idx, daily, daily_vol_above) for idx in df.index]

    position = 0
    positions: list[int] = []
    entry_sig = [False] * len(df)
    exit_sig = [False] * len(df)

    for i in range(1, len(df)):
        k_now, d_now = df["K"].iloc[i], df["D"].iloc[i]
        k_prev, d_prev = df["K"].iloc[i - 1], df["D"].iloc[i - 1]
        vol_ok = df["vol_confirm"].iloc[i]

        if position == 0:
            crossed_up = (k_now > d_now) and (k_prev <= d_prev)
            entered_zone = SWEET_BOTTOM <= k_now <= SWEET_TOP
            came_from_below = k_prev < SWEET_BOTTOM
            if crossed_up and entered_zone and came_from_below and vol_ok:
                position = 1
                entry_sig[i] = True
        elif position == 1:
            crossed_down = (k_now < d_now) and (k_prev >= d_prev)
            below_threshold = k_now < SWEET_TOP
            if crossed_down and below_threshold:
                position = 0
                exit_sig[i] = True
        positions.append(position)

    positions.insert(0, 0)
    df["position"] = positions
    df["entry_signal"] = entry_sig
    df["exit_signal"] = exit_sig
    return df


def backtest(df: pd.DataFrame, initial_capital: float = 10_000.0) -> dict[str, Any]:
    capital = initial_capital
    shares = 0.0
    equity: list[float] = []
    trades: list[dict] = []
    entry_price = None
    entry_date = None

    for idx, row in df.iterrows():
        if row["entry_signal"] and shares == 0:
            shares = capital / row["close"]
            entry_price = row["close"]
            entry_date = idx
            capital = 0.0
        elif row["exit_signal"] and shares > 0:
            capital = shares * row["close"]
            pnl_pct = (row["close"] - entry_price) / entry_price * 100
            trades.append({
                "entry_date": entry_date,
                "exit_date": idx,
                "entry_price": round(entry_price, 4),
                "exit_price": round(row["close"], 4),
                "pnl_pct": round(pnl_pct, 2),
                "duration_wks": round((idx - entry_date).days / 7, 1),
            })
            shares = 0.0
            entry_price = None

        equity.append(capital + shares * row["close"])

    out = df.copy()
    out["equity"] = equity

    final_equity = capital + shares * df["close"].iloc[-1]
    if shares > 0 and entry_price:
        last_row = df.iloc[-1]
        pnl_pct = (last_row["close"] - entry_price) / entry_price * 100
        trades.append({
            "entry_date": entry_date,
            "exit_date": df.index[-1],
            "entry_price": round(entry_price, 4),
            "exit_price": round(last_row["close"], 4),
            "pnl_pct": round(pnl_pct, 2),
            "duration_wks": round((df.index[-1] - entry_date).days / 7, 1),
            "open": True,
        })

    trades_df = pd.DataFrame(trades)
    total_ret = (final_equity - initial_capital) / initial_capital * 100
    bh_ret = (df["close"].iloc[-1] - df["close"].iloc[0]) / df["close"].iloc[0] * 100

    win_rate = avg_win = avg_loss = None
    if not trades_df.empty:
        wins = trades_df[trades_df["pnl_pct"] > 0]["pnl_pct"]
        losses = trades_df[trades_df["pnl_pct"] <= 0]["pnl_pct"]
        win_rate = len(wins) / len(trades_df) * 100
        avg_win = wins.mean() if len(wins) > 0 else 0
        avg_loss = losses.mean() if len(losses) > 0 else 0

    metrics = {
        "total_trades": len(trades_df),
        "win_rate_pct": round(win_rate, 1) if win_rate is not None else 0,
        "avg_win_pct": round(avg_win, 2) if avg_win is not None else 0,
        "avg_loss_pct": round(avg_loss, 2) if avg_loss is not None else 0,
        "strategy_return_pct": round(total_ret, 2),
        "buy_and_hold_ret_pct": round(bh_ret, 2),
        "final_equity": round(final_equity, 2),
        "initial_capital": initial_capital,
        "open_position": shares > 0,
    }
    return {"df": out, "trades": trades_df, "metrics": metrics}


def _compute_trade_plan(row: pd.Series, df: pd.DataFrame, in_trade: bool) -> dict | None:
    price = float(row["close"])
    if price <= 0:
        return None

    recent = df.tail(8)
    swing_low = float(recent["low"].min())
    swing_high = float(recent["high"].max())

    if in_trade or row.get("entry_signal"):
        sl = swing_low * 0.995
        tp = max(swing_high, price * 1.08)
        sl_pct = abs(price - sl) / price * 100
        tp_pct = abs(tp - price) / price * 100
        return {
            "direction": "LONG",
            "entry": round(price, 4),
            "stop_loss": round(sl, 4),
            "take_profit": round(tp, 4),
            "sl_pct": round(sl_pct, 2),
            "tp_pct": round(tp_pct, 2),
            "rr_ratio": round(tp_pct / sl_pct, 2) if sl_pct > 0 else 0,
            "hold_duration": "1–12 weeks (weekly swing)",
        }
    return None


def _live_phase_and_confidence(
    df: pd.DataFrame,
    k_now: float,
    d_now: float,
    k_prev: float,
    d_prev: float,
) -> tuple[str, str, float, bool]:
    last = df.iloc[-1]
    in_trade = bool(last.get("position", 0) == 1)
    vol_ok = bool(last.get("vol_confirm", False))
    in_sweet = SWEET_BOTTOM <= k_now <= SWEET_TOP

    if last.get("entry_signal"):
        return "ENTRY_SIGNAL", "Weekly entry — K crossed above D into sweet spot with volume", 92.0, True
    if last.get("exit_signal"):
        return "EXIT_SIGNAL", "Weekly exit — K crossed below D under 80% threshold", 88.0, True
    if in_trade:
        conf = 70.0 + min(20.0, max(0, k_now - d_now))
        if k_now > SWEET_TOP:
            msg = "In trade — riding overbought (K > 80); hold until bearish cross below 80"
        else:
            msg = "In trade — K above D inside/approaching sweet spot; hold position"
        return "IN_TRADE", msg, min(95.0, conf), True

    crossed_up_pending = (k_now > d_now) or (k_now >= d_now - 3 and k_prev <= d_prev)
    came_from_below = k_prev < SWEET_BOTTOM or k_now < SWEET_BOTTOM + 5
    if crossed_up_pending and in_sweet and came_from_below:
        if vol_ok:
            return "APPROACHING", "Near entry — K/D aligned in sweet spot; watch for confirmed cross", 72.0, True
        return "SWEET_WATCH", "Sweet spot + K>D but volume not confirmed on daily chart", 48.0, False

    if k_now < SWEET_BOTTOM and k_now > k_prev and k_now > d_now - 8:
        return "APPROACHING", f"Stochastic rising ({k_now:.0f}) — approaching sweet spot from below", 58.0, True

    if in_sweet and k_now > d_now:
        return "SWEET_WATCH", "Inside sweet spot with K>D — awaiting volume confirmation", 52.0, False

    return "NEUTRAL", "No active sweet-spot setup on latest weekly bar", 25.0, False


def analyze_weekly_stoch(
    symbol: str,
    market: str,
    groww_token: str = "",
    exchange: str = "NSE",
    period: str = "5y",
    k_period: int = 14,
    d_period: int = 3,
    vol_lookback: int = 20,
    initial_capital: float = 10_000.0,
) -> dict[str, Any]:
    """Run full sweet-spot analysis for one ticker."""
    try:
        daily, weekly = fetch_daily_weekly(symbol, market, groww_token, exchange, period)
    except Exception as exc:
        return {
            "symbol": symbol,
            "error": str(exc)[:200],
            "phase": "NO_DATA",
            "priority": 0,
            "confidence": 0,
            "actionable": False,
        }

    min_weekly = k_period + d_period + 5
    if weekly.empty or len(weekly) < min_weekly:
        return {
            "symbol": symbol,
            "error": f"Insufficient weekly data ({len(weekly)} bars, need {min_weekly}+).",
            "phase": "NO_DATA",
            "priority": 0,
            "confidence": 0,
            "actionable": False,
        }

    signals_df = generate_signals(weekly, daily, k_period, d_period, vol_lookback)
    bt = backtest(signals_df, initial_capital)
    df = bt["df"]
    trades_df = bt["trades"]
    metrics = bt["metrics"]

    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else last
    k_now, d_now = float(last["K"]), float(last["D"])
    k_prev, d_prev = float(prev["K"]), float(prev["D"])

    phase, primary_label, confidence, actionable = _live_phase_and_confidence(
        df, k_now, d_now, k_prev, d_prev,
    )

    in_trade = bool(last.get("position", 0) == 1)
    trade_plan = _compute_trade_plan(last, df, in_trade or bool(last.get("entry_signal")))

    recent_trades = []
    if not trades_df.empty:
        for _, tr in trades_df.tail(5).iterrows():
            recent_trades.append({
                "entry_date": str(tr.get("entry_date", ""))[:10],
                "exit_date": str(tr.get("exit_date", ""))[:10],
                "entry_price": tr.get("entry_price"),
                "exit_price": tr.get("exit_price"),
                "pnl_pct": tr.get("pnl_pct"),
                "duration_wks": tr.get("duration_wks"),
                "open": bool(tr.get("open", False)),
            })

    return {
        "symbol": symbol,
        "phase": phase,
        "primary_label": primary_label,
        "priority": PHASE_PRIORITY.get(phase, 0),
        "confidence": round(confidence, 1),
        "actionable": actionable,
        "k": round(k_now, 2),
        "d": round(d_now, 2),
        "in_sweet_spot": bool(SWEET_BOTTOM <= k_now <= SWEET_TOP),
        "vol_confirm": bool(last.get("vol_confirm", False)),
        "position": int(last.get("position", 0)),
        "price": round(float(last["close"]), 4),
        "trade_plan": trade_plan,
        "metrics": metrics,
        "trades": recent_trades,
        "signals_df": df,
        "daily_df": daily,
        "k_period": k_period,
        "d_period": d_period,
        "period": period,
    }
