"""
Pump & Dump Consolidation-Breakout Strategy
=============================================

Implements the strategy described informally as:

  1. SCREEN for highly volatile / trending tokens that have already pumped
  2. WAIT for tight sideways CONSOLIDATION after pump (or base after dump)
  3. ENTER on confirmed BREAKOUT / BREAKDOWN (close + volume confirmation)
  4. RISK MANAGEMENT: tight SL, capped leverage, % account risk sizing

Signal generator + backtester only — does not place live orders.
NOT FINANCIAL ADVICE.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, List, Literal, Optional

import numpy as np
import pandas as pd


# ----------------------------------------------------------------------
# 1. CONFIG
# ----------------------------------------------------------------------

@dataclass
class StrategyConfig:
    consolidation_lookback: int = 20
    consolidation_max_range_pct: float = 6.0
    min_consolidation_bars: int = 6
    breakout_buffer_pct: float = 0.5
    require_volume_spike: bool = True
    volume_spike_multiplier: float = 1.5
    stop_loss_pct: float = 3.0
    take_profit_pct: float = 15.0
    leverage: int = 5
    max_leverage: int = 10
    risk_per_trade_pct: float = 1.0
    fee_pct_per_side: float = 0.04
    allow_long: bool = True
    allow_short: bool = True

    def __post_init__(self) -> None:
        if self.leverage > self.max_leverage:
            raise ValueError(
                f"leverage={self.leverage}x exceeds max_leverage={self.max_leverage}x."
            )


@dataclass
class Trade:
    side: Literal["long", "short"]
    entry_time: Any
    entry_price: float
    sl_price: float
    tp_price: float
    size_units: float
    notional: float
    margin_used: float
    exit_time: Optional[Any] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    pnl: float = 0.0
    pnl_pct_on_margin: float = 0.0


# ----------------------------------------------------------------------
# 2. TOKEN SCREENING
# ----------------------------------------------------------------------

def screen_candidate(
    symbol: str,
    change_24h_pct: float,
    is_trending_listed: bool,
    is_alpha_listed: bool,
    has_repeating_pump_dump_history: bool,
) -> bool:
    pumped_enough = change_24h_pct >= 10.0 or change_24h_pct <= -20.0
    speculative_flag = is_trending_listed or is_alpha_listed
    return bool(pumped_enough and speculative_flag and has_repeating_pump_dump_history)


def has_repeating_cycles(df: pd.DataFrame, swing_window: int = 10, min_cycles: int = 2) -> bool:
    closes = df["close"].values
    n = len(closes)
    if n < swing_window * 3:
        return False
    cycles = 0
    for i in range(swing_window, n - swing_window):
        window = closes[i - swing_window: i + swing_window]
        if closes[i] == window.max():
            future = closes[i: i + swing_window]
            if len(future) and future.min() <= closes[i] * 0.80:
                cycles += 1
    return cycles >= min_cycles


def estimate_change_24h_pct(df: pd.DataFrame, bars_24h: int | None = None) -> float:
    if len(df) < 2:
        return 0.0
    lookback = bars_24h or min(len(df) - 1, max(24, len(df) // 4))
    old = float(df["close"].iloc[-lookback - 1])
    new = float(df["close"].iloc[-1])
    if old <= 0:
        return 0.0
    return (new - old) / old * 100.0


# ----------------------------------------------------------------------
# 3. CONSOLIDATION + BREAKOUT SIGNAL ENGINE
# ----------------------------------------------------------------------

class PumpDumpStrategy:
    """Expects OHLCV DataFrame with open, high, low, close, volume."""

    def __init__(self, config: StrategyConfig):
        self.cfg = config

    def find_consolidation_zones(self, df: pd.DataFrame) -> pd.DataFrame:
        cfg = self.cfg
        n = len(df)
        zone_high = np.full(n, np.nan)
        zone_low = np.full(n, np.nan)
        is_consolidating = np.zeros(n, dtype=bool)

        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values

        for i in range(cfg.consolidation_lookback, n):
            window_high = highs[i - cfg.consolidation_lookback: i].max()
            window_low = lows[i - cfg.consolidation_lookback: i].min()
            if window_low <= 0:
                continue
            range_pct = (window_high - window_low) / window_low * 100.0
            inside = np.sum(
                (closes[i - cfg.consolidation_lookback: i] <= window_high)
                & (closes[i - cfg.consolidation_lookback: i] >= window_low)
            )
            if range_pct <= cfg.consolidation_max_range_pct and inside >= cfg.min_consolidation_bars:
                zone_high[i] = window_high
                zone_low[i] = window_low
                is_consolidating[i] = True

        out = df.copy()
        out["zone_high"] = zone_high
        out["zone_low"] = zone_low
        out["is_consolidating"] = is_consolidating
        return out

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        cfg = self.cfg
        out = self.find_consolidation_zones(df)
        out["signal"] = None
        avg_vol = out["volume"].rolling(cfg.consolidation_lookback).mean()

        for i in range(1, len(out)):
            prev = out.iloc[i - 1]
            cur = out.iloc[i]
            if not prev["is_consolidating"]:
                continue

            vol_ok = True
            if cfg.require_volume_spike:
                vol_ok = (avg_vol.iloc[i] > 0) and (
                    cur["volume"] >= avg_vol.iloc[i] * cfg.volume_spike_multiplier
                )

            zone_low, zone_high = prev["zone_low"], prev["zone_high"]

            if cfg.allow_short and zone_low > 0:
                breakdown_level = zone_low * (1 - cfg.breakout_buffer_pct / 100.0)
                if cur["close"] < breakdown_level and vol_ok:
                    out.iat[i, out.columns.get_loc("signal")] = "short"
                    continue

            if cfg.allow_long and zone_high > 0:
                breakout_level = zone_high * (1 + cfg.breakout_buffer_pct / 100.0)
                if cur["close"] > breakout_level and vol_ok:
                    out.iat[i, out.columns.get_loc("signal")] = "long"

        return out


# ----------------------------------------------------------------------
# 4. POSITION SIZING / RISK MANAGEMENT
# ----------------------------------------------------------------------

def position_size(
    equity: float,
    entry_price: float,
    stop_loss_pct: float,
    risk_per_trade_pct: float,
    leverage: int,
) -> dict:
    risk_amount = equity * (risk_per_trade_pct / 100.0)
    risk_per_unit = entry_price * (stop_loss_pct / 100.0)
    if risk_per_unit <= 0:
        return {"units": 0.0, "notional": 0.0, "margin_used": 0.0, "risk_amount": risk_amount}
    units = risk_amount / risk_per_unit
    notional = units * entry_price
    margin_required = notional / max(leverage, 1)

    if margin_required > equity and margin_required > 0:
        scale = equity / margin_required
        units *= scale
        notional *= scale
        margin_required = equity

    return {
        "units": units,
        "notional": notional,
        "margin_used": margin_required,
        "risk_amount": risk_amount,
    }


def breakeven_win_rate(rr_ratio: float) -> float:
    return 1.0 / (1.0 + rr_ratio)


# ----------------------------------------------------------------------
# 5. BACKTESTER
# ----------------------------------------------------------------------

class Backtester:
    def __init__(self, df: pd.DataFrame, config: StrategyConfig, initial_balance: float = 1000.0):
        self.cfg = config
        self.strategy = PumpDumpStrategy(config)
        self.df = self.strategy.generate_signals(df)
        self.balance = initial_balance
        self.initial_balance = initial_balance
        self.trades: List[Trade] = []
        self.equity_curve: List[float] = []

    def run(self) -> List[Trade]:
        open_trade: Optional[Trade] = None

        for ts, row in self.df.iterrows():
            if open_trade is not None:
                hit_sl = (
                    (open_trade.side == "long" and row["low"] <= open_trade.sl_price)
                    or (open_trade.side == "short" and row["high"] >= open_trade.sl_price)
                )
                hit_tp = (
                    (open_trade.side == "long" and row["high"] >= open_trade.tp_price)
                    or (open_trade.side == "short" and row["low"] <= open_trade.tp_price)
                )
                if hit_sl or hit_tp:
                    exit_price = open_trade.sl_price if hit_sl else open_trade.tp_price
                    self._close_trade(open_trade, ts, exit_price, "stop_loss" if hit_sl else "take_profit")
                    open_trade = None

            if open_trade is None and row["signal"] in ("long", "short"):
                open_trade = self._open_trade(row["signal"], ts, float(row["close"]))

            self.equity_curve.append(self.balance)

        return self.trades

    def _open_trade(self, side: str, ts, entry_price: float) -> Trade:
        cfg = self.cfg
        sizing = position_size(
            equity=self.balance,
            entry_price=entry_price,
            stop_loss_pct=cfg.stop_loss_pct,
            risk_per_trade_pct=cfg.risk_per_trade_pct,
            leverage=cfg.leverage,
        )
        if side == "long":
            sl_price = entry_price * (1 - cfg.stop_loss_pct / 100.0)
            tp_price = entry_price * (1 + cfg.take_profit_pct / 100.0)
        else:
            sl_price = entry_price * (1 + cfg.stop_loss_pct / 100.0)
            tp_price = entry_price * (1 - cfg.take_profit_pct / 100.0)

        return Trade(
            side=side,  # type: ignore[arg-type]
            entry_time=ts,
            entry_price=entry_price,
            sl_price=sl_price,
            tp_price=tp_price,
            size_units=sizing["units"],
            notional=sizing["notional"],
            margin_used=sizing["margin_used"],
        )

    def _close_trade(self, trade: Trade, ts, exit_price: float, reason: str) -> None:
        if trade.side == "long":
            raw_pnl = (exit_price - trade.entry_price) * trade.size_units
        else:
            raw_pnl = (trade.entry_price - exit_price) * trade.size_units

        fees = trade.notional * (self.cfg.fee_pct_per_side / 100.0) * 2
        pnl = raw_pnl - fees

        trade.exit_time = ts
        trade.exit_price = exit_price
        trade.exit_reason = reason
        trade.pnl = pnl
        trade.pnl_pct_on_margin = (pnl / trade.margin_used * 100.0) if trade.margin_used else 0.0
        self.balance += pnl
        self.trades.append(trade)

    def summary(self) -> dict:
        if not self.trades:
            return {"trades": 0}

        wins = [t for t in self.trades if t.pnl > 0]
        losses = [t for t in self.trades if t.pnl <= 0]
        win_rate = len(wins) / len(self.trades) * 100.0
        avg_win = float(np.mean([t.pnl for t in wins])) if wins else 0.0
        avg_loss = float(np.mean([t.pnl for t in losses])) if losses else 0.0
        rr_ratio = self.cfg.take_profit_pct / self.cfg.stop_loss_pct

        return {
            "trades": len(self.trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_pct": round(win_rate, 2),
            "avg_win_$": round(avg_win, 2),
            "avg_loss_$": round(avg_loss, 2),
            "net_pnl_$": round(self.balance - self.initial_balance, 2),
            "final_balance_$": round(self.balance, 2),
            "configured_rr_ratio": round(rr_ratio, 2),
            "breakeven_win_rate_pct_needed": round(breakeven_win_rate(rr_ratio) * 100, 2),
        }


# ----------------------------------------------------------------------
# 6. Pipeline helpers
# ----------------------------------------------------------------------

def _prepare_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).lower() for c in out.columns]
    for col in ("open", "high", "low", "close"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    if "volume" not in out.columns or out["volume"].isna().all():
        out["volume"] = 1.0
    else:
        out["volume"] = pd.to_numeric(out["volume"], errors="coerce").fillna(1.0)
    out = out.dropna(subset=["open", "high", "low", "close"], how="any")
    if not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.RangeIndex(len(out))
    return out


def _bars_for_24h(timeframe: str) -> int:
    mapping = {"1m": 1440, "5m": 288, "15m": 96, "1h": 24, "4h": 6, "1d": 1}
    return mapping.get(timeframe, 96)


def _latest_live_state(signals_df: pd.DataFrame, config: StrategyConfig) -> dict[str, Any]:
    if signals_df.empty:
        return {}
    last = signals_df.iloc[-1]
    prev = signals_df.iloc[-2] if len(signals_df) > 1 else last
    price = float(last["close"])
    consolidating = bool(last.get("is_consolidating") or prev.get("is_consolidating"))
    zone_high = last.get("zone_high") if pd.notna(last.get("zone_high")) else prev.get("zone_high")
    zone_low = last.get("zone_low") if pd.notna(last.get("zone_low")) else prev.get("zone_low")

    signal = last.get("signal")
    setup: dict[str, Any] | None = None
    if signal in ("long", "short"):
        if signal == "long":
            sl = price * (1 - config.stop_loss_pct / 100.0)
            tp = price * (1 + config.take_profit_pct / 100.0)
        else:
            sl = price * (1 + config.stop_loss_pct / 100.0)
            tp = price * (1 - config.take_profit_pct / 100.0)
        setup = {
            "side": signal.upper(),
            "entry": price,
            "sl_price": sl,
            "tp_price": tp,
            "sl_pct": config.stop_loss_pct,
            "tp_pct": config.take_profit_pct,
            "rr_ratio": round(config.take_profit_pct / config.stop_loss_pct, 2),
            "leverage": config.leverage,
            "status": "BREAKOUT_CONFIRMED",
        }

    return {
        "price": price,
        "is_consolidating": consolidating,
        "zone_high": float(zone_high) if pd.notna(zone_high) else None,
        "zone_low": float(zone_low) if pd.notna(zone_low) else None,
        "latest_signal": setup,
        "watch": consolidating and not setup,
    }


def _trade_to_dict(t: Trade, *, currency: str = "$") -> dict[str, Any]:
    return {
        "side": t.side.upper(),
        "entry": round(t.entry_price, 8),
        "exit": round(float(t.exit_price or 0), 8),
        "sl": round(t.sl_price, 8),
        "tp": round(t.tp_price, 8),
        "pnl": round(t.pnl, 2),
        "exit_reason": t.exit_reason,
        "margin": round(t.margin_used, 2),
        "pnl_pct_margin": round(t.pnl_pct_on_margin, 2),
    }


def run_analysis(
    df: pd.DataFrame,
    *,
    symbol: str,
    config: StrategyConfig | None = None,
    initial_balance: float = 1000.0,
    is_trending_listed: bool = True,
    is_alpha_listed: bool = False,
    timeframe: str = "15m",
) -> dict[str, Any]:
    """Screen → signals → backtest → live state for one symbol."""
    cfg = config or StrategyConfig()
    work = _prepare_df(df)
    if len(work) < cfg.consolidation_lookback + 10:
        return {"symbol": symbol, "error": "Insufficient bars for consolidation scan."}

    change_24h = estimate_change_24h_pct(work, _bars_for_24h(timeframe))
    repeating = has_repeating_cycles(work)
    screened = screen_candidate(
        symbol, change_24h, is_trending_listed, is_alpha_listed, repeating,
    )

    bt = Backtester(work, cfg, initial_balance=initial_balance)
    bt.run()
    live = _latest_live_state(bt.df, cfg)

    signal_counts = bt.df["signal"].value_counts().to_dict() if "signal" in bt.df.columns else {}

    return {
        "symbol": symbol,
        "screened": screened,
        "change_24h_pct": round(change_24h, 2),
        "repeating_cycles": repeating,
        "is_trending_listed": is_trending_listed,
        "is_alpha_listed": is_alpha_listed,
        "bars": len(work),
        "signal_counts": {str(k): int(v) for k, v in signal_counts.items() if k},
        "live": live,
        "backtest": bt.summary(),
        "recent_trades": [_trade_to_dict(t) for t in bt.trades[-10:]],
        "config": asdict(cfg),
    }
