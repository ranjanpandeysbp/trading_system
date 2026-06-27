"""
fakeout_15m_engine.py
---------------------
15M Range Breakout-Fakeout Scalping Strategy (1M execution).

Rules:
- Identify HIGH and LOW of the first 15M candle of each session
  · Groww (India): first 15M from 09:15 IST (09:15–09:30 IST)
  · CoinDCX / global: first 15M from NY midnight (00:00–00:15 NY)
- On 1M chart: wait for breakout (body close outside range)
- Then wait for re-entry (body close back inside range)
- Enter with SL at breakout extreme, TP at configurable R:R
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from app.market_pulse.fakeout_4h_engine import (
    BacktestResult,
    DayRange,
    FakeoutStrategy,
    IST_TZ,
    INDIA_MARKET_CLOSE,
    INDIA_MARKET_OPEN,
    NY_TZ,
    SETUP_PRIORITY,
    SessionMode,
    _finalize_screener,
    _ist_time_on_date,
    _projected_fakeout_trade,
    _scan_session_for_signals,
    _session_tz,
    get_india_trading_days,
    normalize_ohlcv,
    session_mode_for_market,
)

INDIA_RANGE_MINUTES = 15


def _india_session_bounds(day: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]:
    """Return (market_open, range_end, market_close) for an IST calendar day."""
    open_ts = _ist_time_on_date(day, INDIA_MARKET_OPEN)
    range_end = open_ts + pd.Timedelta(minutes=INDIA_RANGE_MINUTES)
    close_ts = _ist_time_on_date(day, INDIA_MARKET_CLOSE)
    return open_ts, range_end, close_ts


def get_india_day_range(df_1m: pd.DataFrame, ist_day: pd.Timestamp) -> Optional[DayRange]:
    """High/low of 1M candles in the first 15M window (09:15–09:30 IST)."""
    df = normalize_ohlcv(df_1m)
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
    df_1m: pd.DataFrame,
    session_mode: SessionMode,
    day_range: DayRange,
    session_day: pd.Timestamp,
) -> dict:
    """Timestamps + OHLC for drawing 15M range top/bottom on the 1M screener chart."""
    df = normalize_ohlcv(df_1m)
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
            "range_label": "09:15–09:30 IST",
        })
        if not range_candles.empty:
            meta["candle_open"] = float(range_candles.iloc[0]["open"])
            meta["candle_close"] = float(range_candles.iloc[-1]["close"])
    else:
        day = session_day.tz_convert(NY_TZ) if session_day.tzinfo else session_day.tz_localize(NY_TZ)
        day = day.normalize()
        range_start = day
        range_end = day + pd.Timedelta(minutes=15)
        last_local = df.index[-1].tz_convert(NY_TZ) if not df.empty else range_end
        meta.update({
            "range_start": range_start,
            "range_end": range_end,
            "session_end": last_local,
            "range_tz": "America/New_York",
            "range_label": "00:00–00:15 NY",
        })
        df_15m = build_15m_candles(df_1m, mode="ny")
        mask = (df_15m.index >= range_start) & (df_15m.index < range_end)
        candles = df_15m[mask]
        if not candles.empty:
            row = candles.iloc[0]
            meta["candle_open"] = float(row["open"])
            meta["candle_close"] = float(row["close"])

    return meta


def build_15m_candles(df_1m: pd.DataFrame, mode: SessionMode = "ny") -> pd.DataFrame:
    """Resample 1M OHLCV into 15M candles (NY midnight alignment for global mode)."""
    df = normalize_ohlcv(df_1m)
    if df.empty or mode == "india":
        return pd.DataFrame()

    tz = _session_tz(mode)
    df_local = df.copy()
    df_local.index = df_local.index.tz_convert(tz)
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in df_local.columns:
        agg["volume"] = "sum"
    return df_local.resample("15min", origin="start_day").agg(agg).dropna()


def get_first_15m_candle_range(
    df_15m: pd.DataFrame,
    day_start: pd.Timestamp,
    mode: SessionMode = "ny",
) -> Optional[DayRange]:
    """First 15M candle range for NY-mode sessions (00:00–00:15 local)."""
    if mode == "india":
        return None
    day_start = day_start.tz_convert(NY_TZ) if day_start.tzinfo else day_start.tz_localize(NY_TZ)
    mask = (df_15m.index >= day_start) & (df_15m.index < day_start + pd.Timedelta(minutes=15))
    candles = df_15m[mask]
    if candles.empty:
        return None
    first = candles.iloc[0]
    return DayRange(date=day_start, high=float(first["high"]), low=float(first["low"]))


def detect_live_setup(
    df_1m: pd.DataFrame,
    rr_ratio: float = 2.0,
    large_breakout_threshold: float = 0.5,
    max_sl_pct: float = 0.005,
    session_mode: SessionMode = "ny",
) -> dict:
    """Analyze latest session for current 15M range, breakout state, and pending signal."""
    df_1m = normalize_ohlcv(df_1m)
    if df_1m.empty or len(df_1m) < 30:
        return {"status": "NO_DATA", "message": "Insufficient 1M data", "session_mode": session_mode}

    if session_mode == "india":
        trading_days = get_india_trading_days(df_1m)
        if not trading_days:
            return {
                "status": "NO_RANGE",
                "message": "No NSE/BSE market-hours candles found",
                "session_mode": session_mode,
            }
        today = trading_days[-1]
        day_range = get_india_day_range(df_1m, today)
        if day_range is None:
            return {
                "status": "NO_RANGE",
                "message": "First 15M range (09:15–09:30 IST) not yet complete for today",
                "session_date": str(today.date()),
                "session_mode": session_mode,
            }

        range_chart = build_range_chart_meta(df_1m, session_mode, day_range, today)

        _, range_end, close_ts = _india_session_bounds(today)
        local = df_1m.copy()
        local.index = local.index.tz_convert(IST_TZ)
        session = local[
            (local.index.normalize() == today.normalize())
            & (local.index >= range_end)
            & (local.index <= close_ts)
        ]
        wait_msg = "Waiting for first 15M range window to finish (09:15–09:30 IST)"
        session_label = str(today.date())
    else:
        df_15m = build_15m_candles(df_1m, mode="ny")
        local = df_1m.copy()
        local.index = local.index.tz_convert(NY_TZ)
        today = local.index[-1].normalize()
        day_range = get_first_15m_candle_range(df_15m, today, mode="ny")
        if day_range is None:
            return {
                "status": "NO_RANGE",
                "message": "First 15M candle not yet complete for today's NY session",
                "session_date": str(today.date()),
                "session_mode": session_mode,
            }
        range_chart = build_range_chart_meta(df_1m, session_mode, day_range, today)
        range_end = today + pd.Timedelta(minutes=15)
        session = local[local.index >= range_end]
        wait_msg = "Waiting for first 15M range window to finish (00:00–00:15 NY)"
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

    current_price = float(df_1m["close"].iloc[-1])
    status = "WATCH"
    message = "Monitoring for 15M range breakout + fakeout re-entry"

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


def scan_fakeout_screener(
    df_1m: pd.DataFrame,
    rr_ratio: float = 2.0,
    large_breakout_threshold: float = 0.5,
    max_sl_pct: float = 0.005,
    session_mode: SessionMode = "ny",
    approach_pct: float = 0.15,
    signal_fresh_bars: int = 12,
) -> dict:
    """
    Live screener: detect approaching, active, and ready fakeout setups on 1M data.
    Returns primary phase, ranked setups list, and optional trade plan.
    """
    live = detect_live_setup(
        df_1m, rr_ratio, large_breakout_threshold, max_sl_pct, session_mode,
    )
    df_1m = normalize_ohlcv(df_1m)
    setups: list[dict] = []

    rh = live.get("range_high")
    rl = live.get("range_low")
    price = live.get("current_price")
    range_size = live.get("range_size") or ((rh - rl) if rh is not None and rl is not None else 0)
    status = live.get("status", "NO_DATA")

    if session_mode == "india" and not df_1m.empty:
        last_ts = df_1m.index[-1].tz_convert(IST_TZ)
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

    sig = live.get("last_signal")
    if sig and day_range is not None:
        sig_time = sig.get("time")
        is_fresh = True
        if sig_time is not None and not df_1m.empty:
            try:
                bars_since = len(df_1m[df_1m.index > pd.Timestamp(sig_time).tz_convert("UTC")])
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
            "hint": "Watch for 1M body close back inside range",
            "breakout_extreme": extreme,
            "trade_plan": projected,
        })

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

    if live.get("price_vs_range") == "inside" and not live.get("in_breakout") and not any(
        s["phase"] in ("APPROACHING_HIGH", "APPROACHING_LOW", "ENTRY_READY") for s in setups
    ):
        setups.append({
            "phase": "MONITORING",
            "label": "Inside range — monitoring",
            "urgency": SETUP_PRIORITY["MONITORING"],
            "hint": f"Range {rl:.2f} – {rh:.2f}; waiting for breakout toward either edge",
        })

    if live.get("price_vs_range") in ("above", "below") and not live.get("in_breakout") and not sig:
        edge = "high" if live["price_vs_range"] == "above" else "low"
        setups.append({
            "phase": "BREAKOUT_ACTIVE",
            "label": f"Price outside range ({edge}) — confirm on 1M body close",
            "urgency": SETUP_PRIORITY["BREAKOUT_ACTIVE"] - 5,
            "direction": "SHORT" if edge == "high" else "LONG",
            "hint": "Body must close outside then re-enter for fakeout entry",
        })

    return _finalize_screener(live, setups)


class Fakeout15mStrategy(FakeoutStrategy):
    """15M range fakeout backtester on 1M execution candles."""

    def run(self, df_1m: pd.DataFrame) -> BacktestResult:
        df_1m = normalize_ohlcv(df_1m)
        if df_1m.empty:
            return BacktestResult([])
        if self.session_mode == "india":
            return self._run_india_15m(df_1m)
        return self._run_ny_15m(df_1m)

    def _run_india_15m(self, df_1m: pd.DataFrame) -> BacktestResult:
        local = df_1m.copy()
        local.index = local.index.tz_convert(IST_TZ)

        for ist_day in get_india_trading_days(df_1m):
            self._reset_day_state()
            day_range = get_india_day_range(df_1m, ist_day)
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

    def _run_ny_15m(self, df_1m: pd.DataFrame) -> BacktestResult:
        df_15m = build_15m_candles(df_1m, mode="ny")
        df_local = df_1m.copy()
        df_local.index = df_local.index.tz_convert(NY_TZ)
        df_local["_session_date"] = df_local.index.normalize()

        for day in sorted(df_local["_session_date"].unique()):
            self._reset_day_state()
            day_range = get_first_15m_candle_range(df_15m, day, mode="ny")
            if day_range is None:
                continue
            self._range = day_range

            day_candles = df_local[df_local["_session_date"] == day]
            first_range_end = day + pd.Timedelta(minutes=15)

            for ts, candle in day_candles.iterrows():
                if ts < first_range_end:
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


def run_fakeout_15m_backtest(
    df_1m: pd.DataFrame,
    session_mode: SessionMode = "ny",
    rr_ratio: float = 2.0,
    large_breakout_threshold: float = 0.5,
    max_sl_pct: float = 0.005,
) -> BacktestResult:
    """Historical backtest for 15M range fakeout on 1M candles."""
    strat = Fakeout15mStrategy(
        rr_ratio=rr_ratio,
        large_breakout_threshold=large_breakout_threshold,
        max_sl_pct=max_sl_pct,
        session_mode=session_mode,
    )
    return strat.run(df_1m)


def run_fakeout_screener(
    df_1m: pd.DataFrame,
    rr_ratio: float = 2.0,
    large_breakout_threshold: float = 0.5,
    max_sl_pct: float = 0.005,
    session_mode: SessionMode = "ny",
    approach_pct: float = 0.15,
) -> dict:
    """Live screener scan (no backtest)."""
    df_1m = normalize_ohlcv(df_1m)
    screener = scan_fakeout_screener(
        df_1m, rr_ratio, large_breakout_threshold, max_sl_pct,
        session_mode, approach_pct,
    )
    return {
        "screener": screener,
        "live_setup": screener,
        "current_price": float(df_1m["close"].iloc[-1]) if not df_1m.empty else None,
        "bars": len(df_1m),
        "rr_ratio": rr_ratio,
        "session_mode": session_mode,
    }
