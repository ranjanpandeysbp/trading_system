"""
Key-Level Rejection Strategy — signal generator + simple backtester.

A 3-step price-action strategy: trend/structure → rejection at key levels →
execution with min R:R filter. Used by the Price Action Simple UI section.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional

import numpy as np
import pandas as pd
from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.groww_auth import get_active_groww_token

STRATEGY_EXPLANATION = """
**Key-Level Rejection Strategy**

A 3-step price-action strategy:

**Step 1 — Trend & Structure**
Detect swing highs/lows to determine trend (HH/HL = uptrend, LH/LL = downtrend)
and build a list of key support/resistance levels.

**Step 2 — Prepare & Predict**
When price returns to a key level *in the direction of the trend*, wait for a
rejection candle: a Doji (indecision) or an Engulfing candle (aggressive
reversal/continuation in trend direction).

**Step 3 — Execution**
Enter on confirmation, place SL just beyond the key level (with breathing room),
place TP at the most recent opposing swing level, and only take the trade if
Reward:Risk ≥ MIN_RR (default 1:3).

**Input:** a pandas DataFrame with columns `open`, `high`, `low`, `close`
(and ideally a datetime index), e.g. from yfinance, ccxt, MT5, etc.

This is a signal generator + simple backtester, not a live order router.
Plug `run_backtest()` output into your own execution/broker layer.
"""


@dataclass
class StrategyConfig:
    swing_lookback: int = 3
    level_tolerance_pct: float = 0.0015
    sl_buffer_pct: float = 0.0015
    min_rr: float = 3.0
    doji_body_ratio: float = 0.1
    engulf_min_body_ratio: float = 1.0


@dataclass
class TradeSignal:
    index: int
    timestamp: object
    direction: Literal["buy", "sell"]
    entry: float
    stop_loss: float
    take_profit: float
    pattern: str = ""
    key_level: float = 0.0
    risk: float = field(init=False)
    reward: float = field(init=False)
    rr: float = field(init=False)

    def __post_init__(self):
        self.risk = abs(self.entry - self.stop_loss)
        self.reward = abs(self.take_profit - self.entry)
        self.rr = self.reward / self.risk if self.risk > 0 else 0.0


def _normalize_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).lower() for c in out.columns]
    for col in ("open", "high", "low", "close"):
        if col not in out.columns:
            raise ValueError(f"DataFrame missing required column: {col}")
    return out


def find_swing_points(df: pd.DataFrame, lookback: int = 3) -> pd.DataFrame:
    """Mark swing highs and swing lows."""
    df = _normalize_ohlc(df)
    highs, lows = df["high"].values, df["low"].values
    n = len(df)
    swing_high = np.zeros(n, dtype=bool)
    swing_low = np.zeros(n, dtype=bool)

    for i in range(lookback, n - lookback):
        window_h = highs[i - lookback : i + lookback + 1]
        window_l = lows[i - lookback : i + lookback + 1]
        if highs[i] == window_h.max():
            swing_high[i] = True
        if lows[i] == window_l.min():
            swing_low[i] = True

    out = df.copy()
    out["swing_high"] = swing_high
    out["swing_low"] = swing_low
    return out


def identify_trend(df: pd.DataFrame, n_swings: int = 4) -> Literal["uptrend", "downtrend", "range"]:
    """Higher highs/lows → uptrend; lower highs/lows → downtrend; else range."""
    swing_highs = df.loc[df["swing_high"], "high"].tail(n_swings)
    swing_lows = df.loc[df["swing_low"], "low"].tail(n_swings)

    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return "range"

    if (
        swing_highs.is_monotonic_increasing
        and swing_lows.is_monotonic_increasing
    ):
        return "uptrend"
    if (
        swing_highs.is_monotonic_decreasing
        and swing_lows.is_monotonic_decreasing
    ):
        return "downtrend"
    return "range"


def get_key_levels(df: pd.DataFrame, n_levels: int = 6) -> List[float]:
    """Most recent swing high/low prices as candidate S/R levels."""
    swing_prices = pd.concat([
        df.loc[df["swing_high"], "high"],
        df.loc[df["swing_low"], "low"],
    ]).sort_index()
    return swing_prices.tail(n_levels).tolist()


def _candle_metrics(o, h, l, c):
    body = abs(c - o)
    rng = max(h - l, 1e-12)
    return body, rng


def is_doji(o, h, l, c, cfg: StrategyConfig) -> bool:
    body, rng = _candle_metrics(o, h, l, c)
    return (body / rng) <= cfg.doji_body_ratio


def is_bullish_engulfing(prev, curr, cfg: StrategyConfig) -> bool:
    prev_body = abs(prev["close"] - prev["open"])
    curr_body = abs(curr["close"] - curr["open"])
    is_prev_bear = prev["close"] < prev["open"]
    is_curr_bull = curr["close"] > curr["open"]
    engulfs = curr["close"] >= prev["open"] and curr["open"] <= prev["close"]
    return (
        is_prev_bear
        and is_curr_bull
        and engulfs
        and curr_body >= prev_body * cfg.engulf_min_body_ratio
    )


def is_bearish_engulfing(prev, curr, cfg: StrategyConfig) -> bool:
    prev_body = abs(prev["close"] - prev["open"])
    curr_body = abs(curr["close"] - curr["open"])
    is_prev_bull = prev["close"] > prev["open"]
    is_curr_bear = curr["close"] < curr["open"]
    engulfs = curr["open"] >= prev["close"] and curr["close"] <= prev["open"]
    return (
        is_prev_bull
        and is_curr_bear
        and engulfs
        and curr_body >= prev_body * cfg.engulf_min_body_ratio
    )


def near_level(price: float, level: float, tolerance_pct: float) -> bool:
    return abs(price - level) / level <= tolerance_pct


def generate_signals(
    df: pd.DataFrame, cfg: StrategyConfig | None = None,
) -> List[TradeSignal]:
    """Run the full pipeline and return qualifying TradeSignal objects."""
    if cfg is None:
        cfg = StrategyConfig()
    df = find_swing_points(_normalize_ohlc(df), lookback=cfg.swing_lookback).reset_index()
    signals: List[TradeSignal] = []

    for i in range(cfg.swing_lookback * 2 + 1, len(df)):
        window = df.iloc[: i + 1]
        trend = identify_trend(window)
        if trend == "range":
            continue

        key_levels = get_key_levels(window)
        if not key_levels:
            continue

        curr = df.iloc[i]
        prev = df.iloc[i - 1]
        pattern = None
        direction = None

        for level in key_levels:
            touched = near_level(curr["low"], level, cfg.level_tolerance_pct) or near_level(
                curr["high"], level, cfg.level_tolerance_pct
            )
            if not touched:
                continue

            if trend == "uptrend" and curr["low"] <= level * (1 + cfg.level_tolerance_pct):
                if is_doji(curr["open"], curr["high"], curr["low"], curr["close"], cfg):
                    pattern, direction = "doji", "buy"
                elif is_bullish_engulfing(prev, curr, cfg):
                    pattern, direction = "bullish_engulfing", "buy"

            elif trend == "downtrend" and curr["high"] >= level * (1 - cfg.level_tolerance_pct):
                if is_doji(curr["open"], curr["high"], curr["low"], curr["close"], cfg):
                    pattern, direction = "doji", "sell"
                elif is_bearish_engulfing(prev, curr, cfg):
                    pattern, direction = "bearish_engulfing", "sell"

            if pattern is None:
                continue

            entry = curr["close"]
            opposing_levels = [
                lv for lv in key_levels
                if (lv > entry if direction == "buy" else lv < entry)
            ]

            if direction == "buy":
                stop_loss = level * (1 - cfg.sl_buffer_pct)
                take_profit = max(opposing_levels) if opposing_levels else None
            else:
                stop_loss = level * (1 + cfg.sl_buffer_pct)
                take_profit = min(opposing_levels) if opposing_levels else None

            if take_profit is None:
                continue

            sig = TradeSignal(
                index=i,
                timestamp=df.iloc[i].get("index", i),
                direction=direction,
                entry=entry,
                stop_loss=stop_loss,
                take_profit=take_profit,
                pattern=pattern,
                key_level=level,
            )
            if sig.rr >= cfg.min_rr:
                signals.append(sig)
            break

    return signals


def run_backtest(
    df: pd.DataFrame,
    cfg: StrategyConfig | None = None,
    max_hold_bars: int = 200,
) -> pd.DataFrame:
    """Walk forward each signal until SL, TP, or max_hold_bars."""
    if cfg is None:
        cfg = StrategyConfig()
    df_reset = _normalize_ohlc(df).reset_index()
    signals = generate_signals(df_reset, cfg)
    results = []

    for sig in signals:
        outcome, exit_price, bars_held = "open", None, 0
        for j in range(sig.index + 1, min(sig.index + 1 + max_hold_bars, len(df_reset))):
            bar = df_reset.iloc[j]
            bars_held += 1
            if sig.direction == "buy":
                if bar["low"] <= sig.stop_loss:
                    outcome, exit_price = "loss", sig.stop_loss
                    break
                if bar["high"] >= sig.take_profit:
                    outcome, exit_price = "win", sig.take_profit
                    break
            else:
                if bar["high"] >= sig.stop_loss:
                    outcome, exit_price = "loss", sig.stop_loss
                    break
                if bar["low"] <= sig.take_profit:
                    outcome, exit_price = "win", sig.take_profit
                    break

        r_multiple = cfg.min_rr if outcome == "win" else (-1 if outcome == "loss" else 0)

        results.append({
            "timestamp": sig.timestamp,
            "direction": sig.direction,
            "pattern": sig.pattern,
            "key_level": sig.key_level,
            "entry": sig.entry,
            "stop_loss": sig.stop_loss,
            "take_profit": sig.take_profit,
            "rr_planned": round(sig.rr, 2),
            "outcome": outcome,
            "exit_price": exit_price,
            "bars_held": bars_held,
            "r_multiple": r_multiple,
        })

    return pd.DataFrame(results)


def analyze_current_state(
    df: pd.DataFrame, cfg: StrategyConfig | None = None,
) -> dict:
    """Snapshot: trend, key levels, and most recent qualifying signal (if any)."""
    if cfg is None:
        cfg = StrategyConfig()
    if df is None or df.empty or len(df) < cfg.swing_lookback * 2 + 5:
        return {"insufficient": True}

    normed = find_swing_points(_normalize_ohlc(df), lookback=cfg.swing_lookback)
    trend = identify_trend(normed)
    key_levels = get_key_levels(normed)
    signals = generate_signals(normed, cfg)
    latest = signals[-1] if signals else None

    return {
        "insufficient": False,
        "trend": trend,
        "key_levels": key_levels,
        "latest_signal": latest,
        "signal_count": len(signals),
        "current_price": float(normed["close"].iloc[-1]),
    }


def _fmt_price(value: float | None, currency: str) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "N/A"
    if currency == "$":
        if value >= 1000:
            return f"{currency}{value:,.2f}"
        if value >= 1:
            return f"{currency}{value:.4f}"
        return f"{currency}{value:.6f}"
    return f"{currency}{value:,.2f}"


def _trend_color(trend: str) -> str:
    return {"uptrend": "#10b981", "downtrend": "#ef4444", "range": "#f59e0b"}.get(trend, "#94a3b8")


def render_price_action_simple_panel(
    analysis: dict,
    currency: str = "₹",
    compact: bool = False,
):
    """Render compact Key-Level Rejection snapshot."""
    if not analysis or analysis.get("insufficient"):
        st.caption("⚠️ Price Action Simple — insufficient data.")
        return

    title = "📉 Price Action Simple"
    if compact:
        st.markdown(f"**{title}**")
    else:
        st.markdown(f"#### {title}")

    trend = analysis.get("trend", "range")
    color = _trend_color(trend)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Trend", trend.upper())
    with c2:
        st.metric("Key Levels", len(analysis.get("key_levels", [])))
    with c3:
        st.metric("Signals (history)", analysis.get("signal_count", 0))
    with c4:
        st.metric("Price", _fmt_price(analysis.get("current_price"), currency))

    latest = analysis.get("latest_signal")
    if latest:
        dir_color = "#10b981" if latest.direction == "buy" else "#ef4444"
        st.markdown(
            f"""
            <div style="background:#0f1729;border:1px solid #1e3a5f;border-left:4px solid {dir_color};
                        border-radius:10px;padding:14px 16px;margin-top:8px;">
                <div style="font-size:0.92rem;font-weight:700;color:{dir_color};margin-bottom:6px;">
                    Latest: {latest.direction.upper()} — {latest.pattern.replace('_', ' ').title()}
                    (R:R 1:{latest.rr:.1f})
                </div>
                <div style="font-size:0.78rem;color:#94a3b8;">
                    Entry {_fmt_price(latest.entry, currency)} &nbsp;|&nbsp;
                    SL {_fmt_price(latest.stop_loss, currency)} &nbsp;|&nbsp;
                    TP {_fmt_price(latest.take_profit, currency)} &nbsp;|&nbsp;
                    Level {_fmt_price(latest.key_level, currency)}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.caption(f"No qualifying signals in lookback (trend: {trend}).")

    levels = analysis.get("key_levels", [])
    if levels:
        level_str = ", ".join(_fmt_price(lv, currency) for lv in levels[-4:])
        st.caption(f"Recent key levels: {level_str}")


def render_price_action_simple_for_ticker(
    df: pd.DataFrame,
    cfg: StrategyConfig | None = None,
    currency: Optional[str] = None,
    compact: bool = False,
) -> dict:
    """Compute and render Price Action Simple analysis from OHLCV data."""
    if df is None or df.empty:
        return {"insufficient": True}
    if currency is None:
        currency = "₹"
    if cfg is None:
        cfg = StrategyConfig()
    analysis = analyze_current_state(df, cfg)
    render_price_action_simple_panel(analysis, currency=currency, compact=compact)
    return analysis


def _render_backtest_summary(trades: pd.DataFrame):
    if trades.empty:
        st.info("No qualifying trades found for the selected parameters.")
        return

    wins = (trades["outcome"] == "win").sum()
    losses = (trades["outcome"] == "loss").sum()
    open_trades = (trades["outcome"] == "open").sum()
    closed = wins + losses
    win_rate = (wins / closed * 100) if closed else 0.0
    total_r = trades["r_multiple"].sum()

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total Signals", len(trades))
    m2.metric("Win Rate", f"{win_rate:.1f}%")
    m3.metric("Wins / Losses", f"{wins} / {losses}")
    m4.metric("Open", open_trades)
    m5.metric("Total R", f"{total_r:.2f}")

    display_cols = [
        "timestamp", "direction", "pattern", "key_level", "entry",
        "stop_loss", "take_profit", "rr_planned", "outcome", "bars_held", "r_multiple",
    ]
    display_cols = [c for c in display_cols if c in trades.columns]
    st.dataframe(trades[display_cols], use_container_width=True, hide_index=True)


def render_price_action_simple_section(
    market: str,
    tickers: list,
    timeframes: list,
    candle_count: int,
    exchange: str = "NSE",
    key_prefix: str = "pa_simple",
):
    """
    Full Price Action Simple section for the Technical Analysis tab.
    Uses shared market/ticker/timeframe inputs from the parent tab.
    """
    st.markdown("## 📉 Price Action Simple")
    st.caption(
        "Key-Level Rejection — trend-following entries at swing S/R with Doji or Engulfing confirmation."
    )

    with st.expander("📖 Key-Level Rejection Strategy — How it works", expanded=False):
        st.markdown(STRATEGY_EXPLANATION)

    with st.expander("⚙️ Strategy Parameters", expanded=False):
        p1, p2, p3 = st.columns(3)
        with p1:
            swing_lookback = st.number_input(
                "Swing lookback", min_value=2, max_value=10, value=3,
                key=f"{key_prefix}_swing_lb",
            )
            min_rr = st.number_input(
                "Min R:R", min_value=1.0, max_value=10.0, value=3.0, step=0.5,
                key=f"{key_prefix}_min_rr",
            )
        with p2:
            level_tol = st.number_input(
                "Level tolerance %", min_value=0.05, max_value=1.0, value=0.15, step=0.05,
                key=f"{key_prefix}_level_tol",
                help="How close price must be to a key level to count as a test.",
            ) / 100.0
            sl_buffer = st.number_input(
                "SL buffer %", min_value=0.05, max_value=1.0, value=0.15, step=0.05,
                key=f"{key_prefix}_sl_buf",
            ) / 100.0
        with p3:
            doji_ratio = st.number_input(
                "Doji body ratio", min_value=0.05, max_value=0.5, value=0.1, step=0.05,
                key=f"{key_prefix}_doji",
            )
            max_hold = st.number_input(
                "Max hold bars", min_value=20, max_value=500, value=200, step=10,
                key=f"{key_prefix}_max_hold",
            )

    cfg = StrategyConfig(
        swing_lookback=int(swing_lookback),
        level_tolerance_pct=level_tol,
        sl_buffer_pct=sl_buffer,
        min_rr=float(min_rr),
        doji_body_ratio=float(doji_ratio),
    )

    run_btn = st.button(
        "▶ RUN PRICE ACTION SIMPLE BACKTEST",
        key=f"{key_prefix}_run_btn",
        use_container_width=True,
    )

    if run_btn:
        if not tickers:
            st.error("Please select at least one ticker above.")
            return
        if not timeframes:
            st.error("Please select at least one timeframe above.")
            return

        groww_token = get_active_groww_token()
        is_crypto = "CoinDCX" in market
        currency = "$" if is_crypto else "₹"
        all_results = {}
        total = len(tickers) * len(timeframes)
        progress = st.progress(0, text="Running Key-Level Rejection backtest...")

        scan_n = 0
        for tick in tickers:
            for tf in timeframes:
                scan_n += 1
                progress.progress(scan_n / total, text=f"Backtesting {tick} | {tf}...")
                try:
                    df = fetch_data_for_gap_scan(
                        symbol=tick,
                        timeframe=tf,
                        market=market,
                        groww_token=groww_token,
                        exchange=exchange,
                        limit=candle_count,
                    )
                    if df.empty or len(df) < cfg.swing_lookback * 2 + 10:
                        all_results[f"{tick}|{tf}"] = {
                            "error": f"Insufficient data ({len(df)} bars).",
                            "symbol": tick,
                            "timeframe": tf,
                        }
                        continue
                    trades = run_backtest(df, cfg, max_hold_bars=int(max_hold))
                    state = analyze_current_state(df, cfg)
                    all_results[f"{tick}|{tf}"] = {
                        "symbol": tick,
                        "timeframe": tf,
                        "trades": trades,
                        "state": state,
                        "df_len": len(df),
                    }
                except Exception as exc:
                    all_results[f"{tick}|{tf}"] = {
                        "error": str(exc)[:200],
                        "symbol": tick,
                        "timeframe": tf,
                    }

        progress.empty()
        st.session_state[f"{key_prefix}_results"] = all_results
        st.session_state[f"{key_prefix}_currency"] = currency
        st.session_state[f"{key_prefix}_cfg"] = cfg

    results = st.session_state.get(f"{key_prefix}_results", {})
    currency = st.session_state.get(f"{key_prefix}_currency", "₹")

    if not results:
        return

    st.markdown("### 📋 Backtest Results")
    for key, data in results.items():
        symbol = data.get("symbol", key.split("|")[0])
        tf = data.get("timeframe", key.split("|")[-1] if "|" in key else "")
        with st.expander(f"📊 {symbol} | {tf}", expanded=len(results) == 1):
            if "error" in data:
                st.error(data["error"])
                continue
            state = data.get("state", {})
            render_price_action_simple_panel(state, currency=currency, compact=True)
            st.markdown("**Historical backtest trades**")
            _render_backtest_summary(data.get("trades", pd.DataFrame()))
