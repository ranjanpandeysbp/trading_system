"""
fakeout_4h_engine.py
--------------------
4H Range Breakout-Fakeout Scalping Strategy (5M execution).

Rules:
- Identify HIGH and LOW of the first 4H candle of each session
  · Groww (India): first 4H from 09:15 IST, trades until 15:30 IST
  · CoinDCX / global: first 4H from NY midnight (00:00–04:00 NY)
- On 5M chart: wait for breakout (body close outside range)
- Then wait for re-entry (body close back inside range)
- Enter with SL at breakout extreme, TP at configurable R:R
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Literal, Optional

import numpy as np
import pandas as pd
import pytz

NY_TZ = pytz.timezone("America/New_York")
IST_TZ = pytz.timezone("Asia/Kolkata")

SessionMode = Literal["india", "ny"]

# NSE/BSE cash market hours (IST)
INDIA_MARKET_OPEN = time(9, 15)
INDIA_MARKET_CLOSE = time(15, 30)
INDIA_RANGE_HOURS = 4


@dataclass
class DayRange:
    date: pd.Timestamp
    high: float
    low: float


@dataclass
class Trade:
    entry_time: pd.Timestamp
    direction: str
    entry_price: float
    stop_loss: float
    take_profit: float
    exit_time: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    result: Optional[str] = None
    pnl_r: Optional[float] = None
    range_high: Optional[float] = None
    range_low: Optional[float] = None

    @property
    def risk(self) -> float:
        return abs(self.entry_price - self.stop_loss)

    @property
    def reward(self) -> float:
        return abs(self.take_profit - self.entry_price)


def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure lowercase OHLCV columns and UTC DatetimeIndex."""
    if df.empty:
        return df
    out = df.copy()
    out.columns = [str(c).lower() for c in out.columns]
    required = {"open", "high", "low", "close"}
    if not required.issubset(set(out.columns)):
        return pd.DataFrame()
    if out.index.tzinfo is None:
        out.index = out.index.tz_localize("UTC")
    else:
        out.index = out.index.tz_convert("UTC")
    return out


def _session_tz(mode: SessionMode):
    return IST_TZ if mode == "india" else NY_TZ


def _ist_time_on_date(date_val: pd.Timestamp, t: time) -> pd.Timestamp:
    """Build tz-aware IST timestamp on a calendar date."""
    local = date_val.tz_convert(IST_TZ) if date_val.tzinfo else date_val.tz_localize(IST_TZ)
    day = local.normalize()
    return day + pd.Timedelta(hours=t.hour, minutes=t.minute)


def _in_india_market_hours(ts: pd.Timestamp) -> bool:
    local = ts.tz_convert(IST_TZ)
    t = local.time()
    return INDIA_MARKET_OPEN <= t <= INDIA_MARKET_CLOSE


def _india_session_bounds(day: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]:
    """
    Return (market_open, range_end, market_close) for an IST calendar day.
    Range = first 4H from 09:15 IST → 13:15 IST.
    """
    open_ts = _ist_time_on_date(day, INDIA_MARKET_OPEN)
    range_end = open_ts + pd.Timedelta(hours=INDIA_RANGE_HOURS)
    close_ts = _ist_time_on_date(day, INDIA_MARKET_CLOSE)
    return open_ts, range_end, close_ts


def get_india_trading_days(df_5m: pd.DataFrame) -> list[pd.Timestamp]:
    """Unique IST calendar dates that have candles inside market hours."""
    df = normalize_ohlcv(df_5m)
    if df.empty:
        return []
    local = df.copy()
    local.index = local.index.tz_convert(IST_TZ)
    in_hours = local[[_in_india_market_hours(ts) for ts in local.index]]
    if in_hours.empty:
        return []
    return sorted(in_hours.index.normalize().unique())


def get_india_day_range(df_5m: pd.DataFrame, ist_day: pd.Timestamp) -> Optional[DayRange]:
    """High/low of 5M candles in the first 4H window (09:15–13:15 IST)."""
    df = normalize_ohlcv(df_5m)
    if df.empty:
        return None

    open_ts, range_end, _ = _india_session_bounds(ist_day)
    local = df.copy()
    local.index = local.index.tz_convert(IST_TZ)
    range_candles = local[(local.index >= open_ts) & (local.index < range_end)]
    if range_candles.empty:
        return None

    return DayRange(
        date=ist_day.normalize(),
        high=float(range_candles["high"].max()),
        low=float(range_candles["low"].min()),
    )


def build_range_chart_meta(
    df_5m: pd.DataFrame,
    session_mode: SessionMode,
    day_range: DayRange,
    session_day: pd.Timestamp,
) -> dict:
    """Timestamps + OHLC for drawing 4H range top/bottom on the 5M screener chart."""
    df = normalize_ohlcv(df_5m)
    meta: dict = {
        "range_high": day_range.high,
        "range_low": day_range.low,
        "candle_high": day_range.high,
        "candle_low": day_range.low,
    }

    if session_mode == "india":
        open_ts, range_end, close_ts = _india_session_bounds(session_day)
        local = df.copy()
        local.index = local.index.tz_convert(IST_TZ)
        range_candles = local[(local.index >= open_ts) & (local.index < range_end)]
        meta.update({
            "range_start": open_ts,
            "range_end": range_end,
            "session_end": close_ts,
            "range_tz": "Asia/Kolkata",
            "range_label": "09:15–13:15 IST",
        })
        if not range_candles.empty:
            meta["candle_open"] = float(range_candles.iloc[0]["open"])
            meta["candle_close"] = float(range_candles.iloc[-1]["close"])
    else:
        day = session_day.tz_convert(NY_TZ) if session_day.tzinfo else session_day.tz_localize(NY_TZ)
        day = day.normalize()
        range_start = day
        range_end = day + pd.Timedelta(hours=4)
        last_local = df.index[-1].tz_convert(NY_TZ) if not df.empty else range_end
        meta.update({
            "range_start": range_start,
            "range_end": range_end,
            "session_end": last_local,
            "range_tz": "America/New_York",
            "range_label": "00:00–04:00 NY",
        })
        df_4h = build_4h_candles(df_5m, mode="ny")
        mask = (df_4h.index >= range_start) & (df_4h.index < range_end)
        candles = df_4h[mask]
        if not candles.empty:
            row = candles.iloc[0]
            meta["candle_open"] = float(row["open"])
            meta["candle_close"] = float(row["close"])

    return meta


def build_4h_candles(df_5m: pd.DataFrame, mode: SessionMode = "ny") -> pd.DataFrame:
    """Resample 5M OHLCV into 4H candles (NY midnight alignment for global mode)."""
    df = normalize_ohlcv(df_5m)
    if df.empty or mode == "india":
        return pd.DataFrame()

    tz = _session_tz(mode)
    df_local = df.copy()
    df_local.index = df_local.index.tz_convert(tz)
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in df_local.columns:
        agg["volume"] = "sum"
    return df_local.resample("4h", origin="start_day").agg(agg).dropna()


def get_first_4h_candle_range(
    df_4h: pd.DataFrame,
    day_start: pd.Timestamp,
    mode: SessionMode = "ny",
) -> Optional[DayRange]:
    """First 4H candle range for NY-mode sessions (00:00–04:00 local)."""
    if mode == "india":
        return None
    day_start = day_start.tz_convert(NY_TZ) if day_start.tzinfo else day_start.tz_localize(NY_TZ)
    mask = (df_4h.index >= day_start) & (df_4h.index < day_start + pd.Timedelta(hours=4))
    candles = df_4h[mask]
    if candles.empty:
        return None
    first = candles.iloc[0]
    return DayRange(date=day_start, high=float(first["high"]), low=float(first["low"]))


class FakeoutStrategy:
    """4H Range Breakout-Fakeout backtester on 5M data."""

    def __init__(
        self,
        rr_ratio: float = 2.0,
        large_breakout_threshold: float = 0.5,
        max_sl_pct: float = 0.005,
        session_mode: SessionMode = "ny",
    ):
        self.rr_ratio = rr_ratio
        self.large_breakout_threshold = large_breakout_threshold
        self.max_sl_pct = max_sl_pct
        self.session_mode = session_mode
        self.trades: list[Trade] = []

    def _reset_day_state(self):
        self._range: Optional[DayRange] = None
        self._breakout_direction: Optional[str] = None
        self._breakout_extreme: Optional[float] = None
        self._in_breakout: bool = False
        self._open_trade: Optional[Trade] = None

    def _update_breakout_extreme(self, candle, direction: str):
        if direction == "above":
            self._breakout_extreme = max(self._breakout_extreme or candle["high"], candle["high"])
        else:
            self._breakout_extreme = min(self._breakout_extreme or candle["low"], candle["low"])

    def _compute_sl(self, entry_price: float, direction: str) -> float:
        raw_sl = self._breakout_extreme
        range_size = self._range.high - self._range.low

        if direction == "short":
            raw_risk = raw_sl - entry_price
            if raw_risk > self.large_breakout_threshold * range_size:
                tightened = entry_price + entry_price * self.max_sl_pct
                return min(raw_sl, tightened)
        else:
            raw_risk = entry_price - raw_sl
            if raw_risk > self.large_breakout_threshold * range_size:
                tightened = entry_price - entry_price * self.max_sl_pct
                return max(raw_sl, tightened)
        return raw_sl

    def _process_candle(self, ts: pd.Timestamp, candle: pd.Series):
        r = self._range
        if r is None:
            return

        body_open = candle["open"]
        body_close = candle["close"]

        if self._open_trade is not None:
            t = self._open_trade
            if t.direction == "short":
                if candle["high"] >= t.stop_loss:
                    t.exit_time = ts
                    t.exit_price = t.stop_loss
                    t.result = "loss"
                    t.pnl_r = -1.0
                    self._open_trade = None
                elif candle["low"] <= t.take_profit:
                    t.exit_time = ts
                    t.exit_price = t.take_profit
                    t.result = "win"
                    t.pnl_r = self.rr_ratio
                    self._open_trade = None
            else:
                if candle["low"] <= t.stop_loss:
                    t.exit_time = ts
                    t.exit_price = t.stop_loss
                    t.result = "loss"
                    t.pnl_r = -1.0
                    self._open_trade = None
                elif candle["high"] >= t.take_profit:
                    t.exit_time = ts
                    t.exit_price = t.take_profit
                    t.result = "win"
                    t.pnl_r = self.rr_ratio
                    self._open_trade = None
            return

        if not self._in_breakout:
            if body_close > r.high and body_open > r.high:
                self._in_breakout = True
                self._breakout_direction = "above"
                self._breakout_extreme = candle["high"]
            elif body_close < r.low and body_open < r.low:
                self._in_breakout = True
                self._breakout_direction = "below"
                self._breakout_extreme = candle["low"]
        else:
            self._update_breakout_extreme(candle, self._breakout_direction)
            body_inside = (body_close > r.low) and (body_close < r.high)

            if body_inside:
                entry_price = body_close
                if self._breakout_direction == "above":
                    sl = self._compute_sl(entry_price, "short")
                    risk = sl - entry_price
                    tp = entry_price - self.rr_ratio * risk
                    t = Trade(
                        entry_time=ts,
                        direction="short",
                        entry_price=entry_price,
                        stop_loss=sl,
                        take_profit=tp,
                        range_high=r.high,
                        range_low=r.low,
                    )
                else:
                    sl = self._compute_sl(entry_price, "long")
                    risk = entry_price - sl
                    tp = entry_price + self.rr_ratio * risk
                    t = Trade(
                        entry_time=ts,
                        direction="long",
                        entry_price=entry_price,
                        stop_loss=sl,
                        take_profit=tp,
                        range_high=r.high,
                        range_low=r.low,
                    )

                self.trades.append(t)
                self._open_trade = t
                self._in_breakout = False
                self._breakout_direction = None
                self._breakout_extreme = None

    def _run_india(self, df_5m: pd.DataFrame) -> "BacktestResult":
        df_5m = normalize_ohlcv(df_5m)
        local = df_5m.copy()
        local.index = local.index.tz_convert(IST_TZ)

        for ist_day in get_india_trading_days(df_5m):
            self._reset_day_state()
            day_range = get_india_day_range(df_5m, ist_day)
            if day_range is None:
                continue
            self._range = day_range

            _, range_end, close_ts = _india_session_bounds(ist_day)
            day_candles = local[
                (local.index.normalize() == ist_day.normalize())
                & (local.index >= range_end)
                & (local.index <= close_ts)
            ]

            for ts, candle in day_candles.iterrows():
                self._process_candle(ts, candle)

            if self._open_trade is not None and not day_candles.empty:
                t = self._open_trade
                last_ts = day_candles.index[-1]
                last_price = day_candles.iloc[-1]["close"]
                t.exit_time = last_ts
                t.exit_price = last_price
                t.result = "timeout"
                if t.direction == "short":
                    t.pnl_r = (t.entry_price - last_price) / t.risk if t.risk else 0.0
                else:
                    t.pnl_r = (last_price - t.entry_price) / t.risk if t.risk else 0.0
                self._open_trade = None

        return BacktestResult(self.trades)

    def _run_ny(self, df_5m: pd.DataFrame) -> "BacktestResult":
        df_5m = normalize_ohlcv(df_5m)
        df_4h = build_4h_candles(df_5m, mode="ny")
        df_local = df_5m.copy()
        df_local.index = df_local.index.tz_convert(NY_TZ)
        df_local["_session_date"] = df_local.index.normalize()

        for day in sorted(df_local["_session_date"].unique()):
            self._reset_day_state()
            day_range = get_first_4h_candle_range(df_4h, day, mode="ny")
            if day_range is None:
                continue
            self._range = day_range

            day_candles = df_local[df_local["_session_date"] == day]
            first_4h_end = day + pd.Timedelta(hours=4)

            for ts, candle in day_candles.iterrows():
                if ts < first_4h_end:
                    continue
                self._process_candle(ts, candle)

            if self._open_trade is not None:
                t = self._open_trade
                last_ts = day_candles.index[-1]
                last_price = day_candles.iloc[-1]["close"]
                t.exit_time = last_ts
                t.exit_price = last_price
                t.result = "timeout"
                if t.direction == "short":
                    t.pnl_r = (t.entry_price - last_price) / t.risk if t.risk else 0.0
                else:
                    t.pnl_r = (last_price - t.entry_price) / t.risk if t.risk else 0.0
                self._open_trade = None

        return BacktestResult(self.trades)

    def run(self, df_5m: pd.DataFrame) -> "BacktestResult":
        df_5m = normalize_ohlcv(df_5m)
        if df_5m.empty:
            return BacktestResult([])
        if self.session_mode == "india":
            return self._run_india(df_5m)
        return self._run_ny(df_5m)


class BacktestResult:
    def __init__(self, trades: list[Trade]):
        self.trades = trades

    @property
    def df(self) -> pd.DataFrame:
        if not self.trades:
            return pd.DataFrame()
        rows = []
        for t in self.trades:
            rows.append({
                "entry_time": t.entry_time,
                "exit_time": t.exit_time,
                "direction": t.direction,
                "entry_price": t.entry_price,
                "stop_loss": t.stop_loss,
                "take_profit": t.take_profit,
                "exit_price": t.exit_price,
                "result": t.result,
                "pnl_r": t.pnl_r,
                "risk_pts": abs(t.entry_price - t.stop_loss),
                "range_high": t.range_high,
                "range_low": t.range_low,
            })
        return pd.DataFrame(rows)

    def summary(self) -> dict:
        df = self.df
        if df.empty:
            return {"error": "No trades found", "total_trades": 0}

        completed = df[df["result"].isin(["win", "loss"])]
        wins = completed[completed["result"] == "win"]
        losses = completed[completed["result"] == "loss"]
        total = len(completed)
        win_count = len(wins)
        loss_count = len(losses)
        win_rate = win_count / total * 100 if total else 0
        total_r = completed["pnl_r"].sum() if not completed.empty else 0.0
        avg_r = completed["pnl_r"].mean() if not completed.empty else 0.0
        max_dd_r = _max_drawdown_r(completed["pnl_r"].tolist()) if not completed.empty else 0.0
        profit_factor = (
            wins["pnl_r"].sum() / abs(losses["pnl_r"].sum())
            if loss_count and losses["pnl_r"].sum() != 0
            else float("inf")
        )

        return {
            "total_trades": total,
            "wins": win_count,
            "losses": loss_count,
            "timeouts": len(df[df["result"] == "timeout"]),
            "win_rate_%": round(win_rate, 2),
            "total_R": round(float(total_r), 2),
            "avg_R_per_trade": round(float(avg_r), 3),
            "profit_factor": round(float(profit_factor), 2) if profit_factor != float("inf") else "∞",
            "max_drawdown_R": round(float(max_dd_r), 2),
        }


def _max_drawdown_r(pnl_series: list[float]) -> float:
    if not pnl_series:
        return 0.0
    equity = np.cumsum(pnl_series)
    peak = np.maximum.accumulate(equity)
    dd = equity - peak
    return float(dd.min())


def _scan_session_for_signals(
    session: pd.DataFrame,
    day_range: DayRange,
    rr_ratio: float,
    large_breakout_threshold: float,
    max_sl_pct: float,
) -> tuple[dict | None, bool, str | None, float | None]:
    """Walk session candles; return (last_signal, in_breakout, breakout_dir, breakout_extreme)."""
    in_breakout = False
    breakout_dir = None
    breakout_extreme = None
    last_signal = None

    for ts, candle in session.iterrows():
        body_open = candle["open"]
        body_close = candle["close"]

        if not in_breakout:
            if body_close > day_range.high and body_open > day_range.high:
                in_breakout = True
                breakout_dir = "above"
                breakout_extreme = candle["high"]
            elif body_close < day_range.low and body_open < day_range.low:
                in_breakout = True
                breakout_dir = "below"
                breakout_extreme = candle["low"]
        else:
            if breakout_dir == "above":
                breakout_extreme = max(breakout_extreme, candle["high"])
            else:
                breakout_extreme = min(breakout_extreme, candle["low"])

            body_inside = (body_close > day_range.low) and (body_close < day_range.high)
            if body_inside:
                entry = body_close
                strat = FakeoutStrategy(rr_ratio, large_breakout_threshold, max_sl_pct)
                strat._range = day_range
                strat._breakout_extreme = breakout_extreme
                if breakout_dir == "above":
                    sl = strat._compute_sl(entry, "short")
                    risk = sl - entry
                    tp = entry - rr_ratio * risk
                    last_signal = {
                        "direction": "short",
                        "entry": entry,
                        "stop_loss": sl,
                        "take_profit": tp,
                        "time": ts,
                        "breakout_dir": "above",
                    }
                else:
                    sl = strat._compute_sl(entry, "long")
                    risk = entry - sl
                    tp = entry + rr_ratio * risk
                    last_signal = {
                        "direction": "long",
                        "entry": entry,
                        "stop_loss": sl,
                        "take_profit": tp,
                        "time": ts,
                        "breakout_dir": "below",
                    }
                in_breakout = False
                breakout_dir = None
                breakout_extreme = None

    return last_signal, in_breakout, breakout_dir, breakout_extreme


def detect_live_setup(
    df_5m: pd.DataFrame,
    rr_ratio: float = 2.0,
    large_breakout_threshold: float = 0.5,
    max_sl_pct: float = 0.005,
    session_mode: SessionMode = "ny",
) -> dict:
    """Analyze latest session for current range, breakout state, and pending signal."""
    df_5m = normalize_ohlcv(df_5m)
    if df_5m.empty or len(df_5m) < 50:
        return {"status": "NO_DATA", "message": "Insufficient 5M data", "session_mode": session_mode}

    if session_mode == "india":
        trading_days = get_india_trading_days(df_5m)
        if not trading_days:
            return {
                "status": "NO_RANGE",
                "message": "No NSE/BSE market-hours candles found",
                "session_mode": session_mode,
            }
        today = trading_days[-1]
        day_range = get_india_day_range(df_5m, today)
        if day_range is None:
            return {
                "status": "NO_RANGE",
                "message": "First 4H range (09:15–13:15 IST) not yet complete for today",
                "session_date": str(today.date()),
                "session_mode": session_mode,
            }

        range_chart = build_range_chart_meta(df_5m, session_mode, day_range, today)

        _, range_end, close_ts = _india_session_bounds(today)
        local = df_5m.copy()
        local.index = local.index.tz_convert(IST_TZ)
        session = local[
            (local.index.normalize() == today.normalize())
            & (local.index >= range_end)
            & (local.index <= close_ts)
        ]
        wait_msg = "Waiting for first 4H range window to finish (09:15–13:15 IST)"
        session_label = str(today.date())
    else:
        df_4h = build_4h_candles(df_5m, mode="ny")
        local = df_5m.copy()
        local.index = local.index.tz_convert(NY_TZ)
        today = local.index[-1].normalize()
        day_range = get_first_4h_candle_range(df_4h, today, mode="ny")
        if day_range is None:
            return {
                "status": "NO_RANGE",
                "message": "First 4H candle not yet complete for today's NY session",
                "session_date": str(today.date()),
                "session_mode": session_mode,
            }
        range_chart = build_range_chart_meta(df_5m, session_mode, day_range, today)
        range_end = today + pd.Timedelta(hours=4)
        session = local[local.index >= range_end]
        wait_msg = "Waiting for first 4H range window to finish (00:00–04:00 NY)"
        session_label = str(today.date())

    if session.empty:
        return {
            "status": "WAIT_RANGE",
            "message": wait_msg,
            "range_high": day_range.high,
            "range_low": day_range.low,
            "session_date": session_label,
            "session_mode": session_mode,
            **range_chart,
        }

    last_signal, in_breakout, breakout_dir, breakout_extreme = _scan_session_for_signals(
        session, day_range, rr_ratio, large_breakout_threshold, max_sl_pct,
    )

    current_price = float(df_5m["close"].iloc[-1])
    status = "WATCH"
    message = "Monitoring for 4H range breakout + fakeout re-entry"

    if in_breakout:
        status = "BREAKOUT_ACTIVE"
        message = f"Breakout {'above' if breakout_dir == 'above' else 'below'} range — watch for fakeout re-entry"
    elif last_signal:
        status = "SIGNAL"
        message = f"Fakeout {last_signal['direction'].upper()} signal at {last_signal['time']}"

    return {
        "status": status,
        "message": message,
        "session_date": session_label,
        "session_mode": session_mode,
        "range_high": day_range.high,
        "range_low": day_range.low,
        "range_size": day_range.high - day_range.low,
        "current_price": current_price,
        "in_breakout": in_breakout,
        "breakout_direction": breakout_dir,
        "breakout_extreme": breakout_extreme,
        "last_signal": last_signal,
        "price_vs_range": (
            "above" if current_price > day_range.high
            else "below" if current_price < day_range.low
            else "inside"
        ),
        **range_chart,
    }


# Screener phase priority (higher = more urgent)
SETUP_PRIORITY = {
    "ENTRY_READY": 100,
    "BREAKOUT_ACTIVE": 85,
    "APPROACHING_HIGH": 70,
    "APPROACHING_LOW": 70,
    "MONITORING": 40,
    "WAIT_RANGE": 20,
    "SESSION_CLOSED": 10,
    "NO_RANGE": 5,
    "NO_DATA": 0,
}


def _projected_fakeout_trade(
    day_range: DayRange,
    breakout_dir: str,
    breakout_extreme: float,
    entry_price: float,
    rr_ratio: float,
    large_breakout_threshold: float,
    max_sl_pct: float,
) -> dict:
    """Project SL/TP if fakeout re-entry happens at entry_price."""
    strat = FakeoutStrategy(rr_ratio, large_breakout_threshold, max_sl_pct)
    strat._range = day_range
    strat._breakout_extreme = breakout_extreme
    if breakout_dir == "above":
        sl = strat._compute_sl(entry_price, "short")
        risk = sl - entry_price
        tp = entry_price - rr_ratio * risk
        direction = "short"
    else:
        sl = strat._compute_sl(entry_price, "long")
        risk = entry_price - sl
        tp = entry_price + rr_ratio * risk
        direction = "long"
    risk_pct = abs(entry_price - sl) / entry_price * 100 if entry_price else 0
    reward_pct = abs(tp - entry_price) / entry_price * 100 if entry_price else 0
    return {
        "direction": direction,
        "entry": entry_price,
        "stop_loss": sl,
        "take_profit": tp,
        "risk_pct": round(risk_pct, 3),
        "reward_pct": round(reward_pct, 3),
        "rr_ratio": rr_ratio,
    }


def scan_fakeout_screener(
    df_5m: pd.DataFrame,
    rr_ratio: float = 2.0,
    large_breakout_threshold: float = 0.5,
    max_sl_pct: float = 0.005,
    session_mode: SessionMode = "ny",
    approach_pct: float = 0.15,
    signal_fresh_bars: int = 6,
) -> dict:
    """
    Live screener: detect approaching, active, and ready fakeout setups on 5M data.
    Returns primary phase, ranked setups list, and optional trade plan.
    """
    live = detect_live_setup(
        df_5m, rr_ratio, large_breakout_threshold, max_sl_pct, session_mode,
    )
    df_5m = normalize_ohlcv(df_5m)
    setups: list[dict] = []

    rh = live.get("range_high")
    rl = live.get("range_low")
    price = live.get("current_price")
    range_size = live.get("range_size") or ((rh - rl) if rh is not None and rl is not None else 0)
    status = live.get("status", "NO_DATA")

    # ── India: session closed after 15:30 IST ──
    if session_mode == "india" and not df_5m.empty:
        last_ts = df_5m.index[-1].tz_convert(IST_TZ)
        if last_ts.time() > INDIA_MARKET_CLOSE and status not in ("SIGNAL", "BREAKOUT_ACTIVE"):
            live["status"] = "SESSION_CLOSED"
            live["message"] = "NSE/BSE session closed (after 15:30 IST)"
            setups.append({
                "phase": "SESSION_CLOSED",
                "label": "Session closed",
                "urgency": SETUP_PRIORITY["SESSION_CLOSED"],
                "hint": "Scan again next trading session",
            })
            return _finalize_screener(live, setups)

    if status == "NO_DATA":
        setups.append({"phase": "NO_DATA", "label": "No data", "urgency": 0, "hint": live.get("message", "")})
        return _finalize_screener(live, setups)

    if status in ("NO_RANGE", "WAIT_RANGE"):
        phase = "WAIT_RANGE" if status == "WAIT_RANGE" else "NO_RANGE"
        setups.append({
            "phase": phase,
            "label": "Range building" if phase == "WAIT_RANGE" else "No range",
            "urgency": SETUP_PRIORITY[phase],
            "hint": live.get("message", ""),
        })
        return _finalize_screener(live, setups)

    day_range = DayRange(
        date=pd.Timestamp(live.get("session_date", "")),
        high=rh,
        low=rl,
    ) if rh is not None and rl is not None else None

    # ── 1. Entry ready (recent fakeout signal) ──
    sig = live.get("last_signal")
    if sig and day_range is not None:
        sig_time = sig.get("time")
        is_fresh = True
        if sig_time is not None and not df_5m.empty:
            try:
                bars_since = len(df_5m[df_5m.index > pd.Timestamp(sig_time).tz_convert("UTC")])
                is_fresh = bars_since <= signal_fresh_bars
            except Exception:
                is_fresh = True
        if is_fresh:
            trade = {
                "direction": sig["direction"],
                "entry": sig["entry"],
                "stop_loss": sig["stop_loss"],
                "take_profit": sig["take_profit"],
                "risk_pct": round(abs(sig["entry"] - sig["stop_loss"]) / sig["entry"] * 100, 3),
                "reward_pct": round(abs(sig["take_profit"] - sig["entry"]) / sig["entry"] * 100, 3),
                "rr_ratio": rr_ratio,
            }
            setups.append({
                "phase": "ENTRY_READY",
                "label": f"FAKEOUT {sig['direction'].upper()} — enter now",
                "urgency": SETUP_PRIORITY["ENTRY_READY"],
                "direction": sig["direction"].upper(),
                "hint": f"Re-entry confirmed at {sig.get('time', '')}",
                "trade_plan": trade,
            })
            live["trade_plan"] = trade

    # ── 2. Breakout active — fakeout imminent ──
    if live.get("in_breakout") and day_range is not None:
        bdir = live.get("breakout_direction")
        extreme = live.get("breakout_extreme")
        mid_entry = (rh + rl) / 2
        projected = _projected_fakeout_trade(
            day_range, bdir, extreme, mid_entry,
            rr_ratio, large_breakout_threshold, max_sl_pct,
        )
        setups.append({
            "phase": "BREAKOUT_ACTIVE",
            "label": f"Breakout {'above' if bdir == 'above' else 'below'} — fakeout pending",
            "urgency": SETUP_PRIORITY["BREAKOUT_ACTIVE"],
            "direction": "SHORT" if bdir == "above" else "LONG",
            "hint": "Watch for 5M body close back inside range",
            "breakout_extreme": extreme,
            "trade_plan": projected,
        })

    # ── 3. Approaching range edges (from inside) ──
    if (
        price is not None
        and rh is not None
        and rl is not None
        and range_size > 0
        and live.get("price_vs_range") == "inside"
        and not live.get("in_breakout")
    ):
        dist_high_pct = (rh - price) / range_size
        dist_low_pct = (price - rl) / range_size

        if dist_high_pct <= approach_pct:
            setups.append({
                "phase": "APPROACHING_HIGH",
                "label": "Approaching range HIGH — breakout watch",
                "urgency": SETUP_PRIORITY["APPROACHING_HIGH"],
                "direction": "SHORT",
                "hint": f"Price {dist_high_pct * 100:.1f}% of range from high — watch false breakout above {rh:.2f}",
                "distance_pct": round(dist_high_pct * 100, 2),
                "trigger_level": rh,
            })
        if dist_low_pct <= approach_pct:
            setups.append({
                "phase": "APPROACHING_LOW",
                "label": "Approaching range LOW — breakdown watch",
                "urgency": SETUP_PRIORITY["APPROACHING_LOW"],
                "direction": "LONG",
                "hint": f"Price {dist_low_pct * 100:.1f}% of range from low — watch false breakdown below {rl:.2f}",
                "distance_pct": round(dist_low_pct * 100, 2),
                "trigger_level": rl,
            })

    # ── 4. Inside range monitoring ──
    if live.get("price_vs_range") == "inside" and not live.get("in_breakout") and not any(
        s["phase"] in ("APPROACHING_HIGH", "APPROACHING_LOW", "ENTRY_READY") for s in setups
    ):
        setups.append({
            "phase": "MONITORING",
            "label": "Inside range — monitoring",
            "urgency": SETUP_PRIORITY["MONITORING"],
            "hint": f"Range {rl:.2f} – {rh:.2f}; waiting for breakout toward either edge",
        })

    # ── 5. Price already outside range (potential breakout without full body rule yet) ──
    if live.get("price_vs_range") in ("above", "below") and not live.get("in_breakout") and not sig:
        edge = "high" if live["price_vs_range"] == "above" else "low"
        setups.append({
            "phase": "BREAKOUT_ACTIVE",
            "label": f"Price outside range ({edge}) — confirm on 5M body close",
            "urgency": SETUP_PRIORITY["BREAKOUT_ACTIVE"] - 5,
            "direction": "SHORT" if edge == "high" else "LONG",
            "hint": "Body must close outside then re-enter for fakeout entry",
        })

    return _finalize_screener(live, setups)


def _finalize_screener(live: dict, setups: list[dict]) -> dict:
    setups = sorted(setups, key=lambda s: s.get("urgency", 0), reverse=True)
    primary = setups[0] if setups else {"phase": "NO_DATA", "label": "No setup", "urgency": 0}
    live["setups"] = setups
    live["primary_phase"] = primary.get("phase", "NO_DATA")
    live["primary_label"] = primary.get("label", "")
    live["priority"] = primary.get("urgency", 0)
    live["actionable"] = primary.get("phase") in (
        "ENTRY_READY", "BREAKOUT_ACTIVE", "APPROACHING_HIGH", "APPROACHING_LOW",
    )
    for key in ("trade_plan",):
        plan = live.get(key)
        if plan and plan.get("entry"):
            entry = float(plan["entry"])
            if entry > 0:
                if plan.get("stop_loss") is not None and not plan.get("risk_pct"):
                    plan["risk_pct"] = round(abs(entry - float(plan["stop_loss"])) / entry * 100, 2)
                if plan.get("take_profit") is not None and not plan.get("reward_pct"):
                    plan["reward_pct"] = round(abs(float(plan["take_profit"]) - entry) / entry * 100, 2)
    for su in setups:
        tp = su.get("trade_plan")
        if tp and tp.get("entry"):
            entry = float(tp["entry"])
            if entry > 0:
                if tp.get("stop_loss") is not None and not tp.get("risk_pct"):
                    tp["risk_pct"] = round(abs(entry - float(tp["stop_loss"])) / entry * 100, 2)
                if tp.get("take_profit") is not None and not tp.get("reward_pct"):
                    tp["reward_pct"] = round(abs(float(tp["take_profit"]) - entry) / entry * 100, 2)
    if primary.get("trade_plan") and "trade_plan" not in live:
        live["trade_plan"] = primary["trade_plan"]
    return live


def run_fakeout_screener(
    df_5m: pd.DataFrame,
    rr_ratio: float = 2.0,
    large_breakout_threshold: float = 0.5,
    max_sl_pct: float = 0.005,
    session_mode: SessionMode = "ny",
    approach_pct: float = 0.15,
) -> dict:
    """Live screener scan (no backtest)."""
    df_5m = normalize_ohlcv(df_5m)
    screener = scan_fakeout_screener(
        df_5m, rr_ratio, large_breakout_threshold, max_sl_pct,
        session_mode, approach_pct,
    )
    return {
        "screener": screener,
        "live_setup": screener,
        "current_price": float(df_5m["close"].iloc[-1]) if not df_5m.empty else None,
        "bars": len(df_5m),
        "rr_ratio": rr_ratio,
        "session_mode": session_mode,
    }


def session_mode_for_market(market: str) -> SessionMode:
    """Groww India stocks → IST session; CoinDCX / others → NY session."""
    if "Groww" in market or "India" in market:
        return "india"
    return "ny"
