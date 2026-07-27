"""
strategy_registry.py
---------------------
Catalog of real, named app strategies wired up to the walk-forward
calibration harness (`calibration_engine.py`) — the backbone of the
Strategy Lab leaderboard. Each entry describes what timeframe(s) a
strategy needs and provides a signal-function factory that adapts the
strategy's own engine code into the harness's
`fn(history) -> {"direction","confidence_pct"} | None` contract, without
modifying the engine itself.

Scope, honestly stated: this covers a curated, growing set of strategies
that (a) have a genuine per-bar signal (not a static/display-only section)
and (b) fit a rolling walk-forward test — daily/weekly swing-style and
higher-timeframe SMC strategies. Session-boundary strategies (opening-range,
VWAP session resets, kill-zone-gated scalps) need a specialized per-session
harness this doesn't attempt yet and are intentionally excluded rather than
silently mis-tested — the UI should say so, not pretend coverage it doesn't
have.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd

SingleSignalFn = Callable[[pd.DataFrame], dict[str, Any] | None]
MultiSignalFn = Callable[[dict[str, pd.DataFrame]], dict[str, Any] | None]


@dataclass
class StrategyDef:
    id: str
    label: str
    hub: str
    timeframes: list[str]  # for multi-tf strategies, timeframes[0] is the primary/execution tf
    make_signal_fn: Callable[[], SingleSignalFn | MultiSignalFn]
    multi_tf: bool = False
    needs_benchmark: bool = False  # fetch an extra market-benchmark series under history["benchmark"]
    fixed_timeframe: bool = False  # ignore the caller's selected timeframes and always use timeframes[0] —
    # true for Trading Hub strategies, whose internal math (hold durations, pyramid-add cadence, session
    # logic) is tuned for one specific timeframe; false for generic scanners (Momentum, Divergences, ...)
    # that are genuinely timeframe-flexible and should be tested on whichever timeframes the caller picks.
    default_target_atr_mult: float = 1.5
    default_stop_atr_mult: float = 1.5
    walk_forward_step: int = 1  # evaluate every bar by default; raised for strategies whose adapter
    # recomputes non-vectorized (Python-loop) indicator state from scratch at every step — profiled at
    # 40-90x slower per-step than the vectorized Command Center engines, so a coarser step keeps a full
    # leaderboard run in the tens-of-seconds-per-strategy range instead of minutes, at the cost of fewer
    # (but still statistically meaningful) samples.
    notes: str = ""


_REGISTRY: dict[str, StrategyDef] = {}


def register(strategy: StrategyDef) -> None:
    _REGISTRY[strategy.id] = strategy


def all_strategies() -> list[StrategyDef]:
    return list(_REGISTRY.values())


def get_strategy(strategy_id: str) -> StrategyDef | None:
    return _REGISTRY.get(strategy_id)


# ---------------------------------------------------------------------------
# Command Center
# ---------------------------------------------------------------------------

def _make_momentum_signal() -> SingleSignalFn:
    from app.market_pulse.momentum_engine import MomentumConfig, analyze_timeframe

    cfg = MomentumConfig()

    def fn(history: pd.DataFrame) -> dict[str, Any] | None:
        r = analyze_timeframe(history, "1d", cfg)
        if not r:
            return None
        if r.get("confidence_continue_pct") is not None and r.get("trend_direction") in ("UP", "DOWN"):
            return {"direction": r["trend_direction"], "confidence_pct": r["confidence_continue_pct"]}
        up = r.get("breakout_up_pct")
        if up is not None:
            if up >= 50:
                return {"direction": "UP", "confidence_pct": up}
            return {"direction": "DOWN", "confidence_pct": r.get("breakout_down_pct")}
        return None

    return fn


register(StrategyDef(
    id="cc_momentum", label="Momentum Scanner (trend-continue / breakout-lean)",
    hub="Command Center", timeframes=["1d"], make_signal_fn=_make_momentum_signal,
    notes="Calibration on file: pooled 9,315 signals showed no discriminative confidence (flat ~48-51% across buckets).",
))


def _make_weak_strong_signal() -> MultiSignalFn:
    from app.market_pulse.weak_strong_engine import WeakStrongConfig, _score_ticker

    cfg = WeakStrongConfig()

    def fn(history: dict[str, pd.DataFrame]) -> dict[str, Any] | None:
        primary = history.get("primary")
        bench = history.get("benchmark")
        if primary is None or primary.empty:
            return None
        scored = _score_ticker(primary, bench, cfg)
        if not scored:
            return None
        score = scored["score"]
        if score >= cfg.strong_threshold:
            direction = "LONG"
        elif score <= cfg.weak_threshold:
            direction = "SHORT"
        else:
            return None
        confidence = min(92.0, 50.0 + abs(score) * 0.42)
        return {"direction": direction, "confidence_pct": confidence}

    return fn


def benchmark_ticker_for_market(market: str) -> str:
    """The service layer calls this (not the signal function) to know which
    extra ticker to fetch for a `needs_benchmark` strategy — the signal
    function itself only ever sees the resulting price series, never the
    symbol, so it doesn't need to know the market at all."""
    from app.market_pulse.weak_strong_engine import _benchmark_symbol

    bench_sym, _ = _benchmark_symbol(market)
    return bench_sym


register(StrategyDef(
    id="cc_weak_strong", label="Weak / Strong (relative-strength + trend structure)",
    hub="Command Center", timeframes=["1d"], multi_tf=True, needs_benchmark=True,
    make_signal_fn=_make_weak_strong_signal,
    notes="Needs a benchmark series (auto-resolved per market: NIFTY/SPY/BTC). "
          "Calibration on file: pooled 6,364 signals, flat ~48-51% across confidence buckets.",
))


def _make_divergence_signal() -> SingleSignalFn:
    from app.market_pulse.indicators import add_obv, add_rsi
    from app.market_pulse.divergence_engine import _SWING_WINDOW, _DIVERGENCE_LOOKBACK, _classify, _divergence_for

    def fn(history: pd.DataFrame) -> dict[str, Any] | None:
        if len(history) < 80:
            return None
        work = add_rsi(history.copy(), 14)
        work = add_obv(work)
        close = work["close"].values
        rsi_div = _divergence_for(close, work["rsi_14"].values, window=_SWING_WINDOW, lookback=_DIVERGENCE_LOOKBACK, min_osc_delta=2.0)
        vol = work["obv"].values
        lookback_start = max(0, len(work) - _DIVERGENCE_LOOKBACK)
        obv_window = vol[lookback_start:]
        obv_range = float(pd.Series(obv_window).max() - pd.Series(obv_window).min()) if len(obv_window) else 0.0
        vol_div = _divergence_for(close, vol, window=_SWING_WINDOW, lookback=_DIVERGENCE_LOOKBACK, min_osc_delta=obv_range * 0.03)
        bias, confidence, _reasons = _classify(rsi_div, vol_div)
        if bias == "BULLISH":
            return {"direction": "LONG", "confidence_pct": confidence}
        if bias == "BEARISH":
            return {"direction": "SHORT", "confidence_pct": confidence}
        return None

    return fn


register(StrategyDef(
    id="cc_divergences", label="Divergences (RSI + OBV vs price)",
    hub="Command Center", timeframes=["1d"], make_signal_fn=_make_divergence_signal,
))


def _make_sma_20_200_signal() -> SingleSignalFn:
    from app.market_pulse.sma_20_200_engine import Sma20200Config, scan_sma_signals

    cfg = Sma20200Config()

    def fn(history: pd.DataFrame) -> dict[str, Any] | None:
        if len(history) < 210:
            return None
        work = scan_sma_signals(history, cfg)
        if work.empty:
            return None
        sig = work["signal"].iloc[-1]
        if sig == 1:
            return {"direction": "LONG", "confidence_pct": 68.0}
        if sig == -1:
            return {"direction": "SHORT", "confidence_pct": 68.0}
        return None

    return fn


register(StrategyDef(
    id="cc_sma_20_200", label="200SMA-20SMA Bounce & Rejection",
    hub="Command Center", timeframes=["1d"], make_signal_fn=_make_sma_20_200_signal,
))


# ---------------------------------------------------------------------------
# Trading Hubs — Swing
# ---------------------------------------------------------------------------

def _make_st_signal(strategy_mode: str) -> Callable[[], SingleSignalFn]:
    def factory() -> SingleSignalFn:
        from app.trading_hubs.swing_trading_st_engine import STConfig, evaluate_live_signal

        cfg = STConfig(strategy=strategy_mode)

        def fn(history: pd.DataFrame) -> dict[str, Any] | None:
            try:
                r = evaluate_live_signal(history, cfg)
            except Exception:
                return None
            if not r or not r.get("take_trade"):
                return None
            direction = r.get("direction")
            if direction not in ("LONG", "SHORT"):
                return None
            return {"direction": direction, "confidence_pct": r.get("confidence_pct")}

        return fn
    return factory


register(StrategyDef(
    id="th_st_mean_reversion", label="Base ST — Mean-Reversion Capitulation",
    hub="Trading Hub / Swing", timeframes=["1d"], fixed_timeframe=True,
    make_signal_fn=_make_st_signal("mean_reversion_capitulation"),
    notes="Calibration on file: never fired once across 15 India stocks over ~3 years — entry criteria essentially unreachable together on liquid large-caps.",
))
register(StrategyDef(
    id="th_st_continuation_breakout", label="Base ST — Continuation Breakout",
    hub="Trading Hub / Swing", timeframes=["1d"], fixed_timeframe=True,
    make_signal_fn=_make_st_signal("continuation_breakout"),
    notes="Calibration on file: 334 signals, 46.9% pooled win rate at 1:1 ATR-scaled target/stop.",
))


def _make_simple_steal_signal() -> SingleSignalFn:
    from app.trading_hubs.swing_trading_st_simple_steal_engine import (
        SimpleStealConfig, evaluate_live_signal, implement_simple_steal,
    )

    cfg = SimpleStealConfig()

    def fn(history: pd.DataFrame) -> dict[str, Any] | None:
        try:
            work, projections = implement_simple_steal(history, cfg)
            r = evaluate_live_signal(work, projections, cfg)
        except Exception:
            return None
        if not r or not r.get("take_trade"):
            return None
        direction = r.get("direction")
        if direction not in ("LONG", "SHORT"):
            return None
        return {"direction": direction, "confidence_pct": r.get("confidence_pct")}

    return fn


register(StrategyDef(
    id="th_simple_steal", label="Little Rizzy (Simple Steal — trendline measured move)",
    hub="Trading Hub / Swing", timeframes=["1d"], fixed_timeframe=True, make_signal_fn=_make_simple_steal_signal,
    notes="Calibration on file: 145 signals, 43.6% pooled win rate — below breakeven at 1:1 ATR-scaled target/stop.",
))


def _make_supertrend_signal(mode: str) -> Callable[[], SingleSignalFn]:
    def factory() -> SingleSignalFn:
        from app.trading_hubs.swing_trading_st_supertrend_engine import (
            STSuperTrendConfig, compute_strategy_frame, evaluate_live_signal,
        )

        cfg = STSuperTrendConfig(mode=mode)

        def fn(history: pd.DataFrame) -> dict[str, Any] | None:
            try:
                work = compute_strategy_frame(history, cfg)
                r = evaluate_live_signal(work, cfg)
            except Exception:
                return None
            if not r or not r.get("take_trade"):
                return None
            direction = r.get("direction")
            if direction not in ("LONG", "SHORT"):
                return None
            return {"direction": direction, "confidence_pct": r.get("confidence_pct")}

        return fn
    return factory


register(StrategyDef(
    id="th_supertrend_swing", label="SuperTrend + SMA10 — Swing mode",
    hub="Trading Hub / Swing", timeframes=["1d"], fixed_timeframe=True, make_signal_fn=_make_supertrend_signal("swing"),
    walk_forward_step=3,
))
register(StrategyDef(
    id="th_supertrend_pyramid", label="SuperTrend + SMA10 — Pyramid mode",
    hub="Trading Hub / Swing", timeframes=["1w"], fixed_timeframe=True, make_signal_fn=_make_supertrend_signal("pyramid"),
    walk_forward_step=3,
))


# ---------------------------------------------------------------------------
# Trading Hubs — Smart Money (2-timeframe: HTF bias + LTF execution)
# ---------------------------------------------------------------------------

def _make_cisd_signal() -> MultiSignalFn:
    from app.trading_hubs.smc_cisd_engine import (
        CISDConfig, _htf_bias_summary, evaluate_live_signal, implement_cisd_strategy,
    )

    cfg = CISDConfig()

    def fn(history: dict[str, pd.DataFrame]) -> dict[str, Any] | None:
        ltf = history.get(cfg.execution_tf)
        htf_df = history.get(cfg.bias_tf)
        if ltf is None or len(ltf) < cfg.min_bars:
            return None
        try:
            work, setups = implement_cisd_strategy(ltf, cfg)
            htf = _htf_bias_summary(htf_df, cfg) if htf_df is not None and not htf_df.empty else None
            r = evaluate_live_signal(work, setups, cfg, htf=htf)
        except Exception:
            return None
        if not r or not r.get("take_trade"):
            return None
        direction = r.get("direction")
        if direction not in ("LONG", "SHORT"):
            return None
        return {"direction": direction, "confidence_pct": r.get("confidence_pct")}

    return fn


register(StrategyDef(
    id="th_smc_cisd", label="SMC — CISD (Change in State of Delivery)",
    hub="Trading Hub / Smart Money", timeframes=["15m", "1h"], multi_tf=True, fixed_timeframe=True,
    make_signal_fn=_make_cisd_signal, walk_forward_step=3,
))


def _make_liquidity_signal() -> MultiSignalFn:
    from app.trading_hubs.smc_liquidity_engine import (
        LiquidityConfig, _htf_liquidity_bias, evaluate_live_signal, implement_liquidity_strategy,
    )

    cfg = LiquidityConfig()

    def fn(history: dict[str, pd.DataFrame]) -> dict[str, Any] | None:
        ltf = history.get(cfg.execution_tf)
        htf_df = history.get(cfg.bias_tf)
        if ltf is None or len(ltf) < cfg.min_bars:
            return None
        try:
            work, events, bull_fvgs, bear_fvgs = implement_liquidity_strategy(ltf, cfg)
            htf = _htf_liquidity_bias(htf_df, cfg) if htf_df is not None and not htf_df.empty else None
            r = evaluate_live_signal(work, events, cfg, htf=htf, bull_fvgs=bull_fvgs, bear_fvgs=bear_fvgs)
        except Exception:
            return None
        if not r or not r.get("take_trade"):
            return None
        direction = r.get("direction")
        if direction not in ("LONG", "SHORT"):
            return None
        return {"direction": direction, "confidence_pct": r.get("confidence_pct")}

    return fn


register(StrategyDef(
    id="th_smc_liquidity", label="SMC — Liquidity (Sweep/Grab + FVG Rebalance)",
    hub="Trading Hub / Smart Money", timeframes=["15m", "1h"], multi_tf=True, fixed_timeframe=True,
    make_signal_fn=_make_liquidity_signal, walk_forward_step=4,
))


def hub_labels() -> list[str]:
    seen: list[str] = []
    for s in _REGISTRY.values():
        if s.hub not in seen:
            seen.append(s.hub)
    return seen
