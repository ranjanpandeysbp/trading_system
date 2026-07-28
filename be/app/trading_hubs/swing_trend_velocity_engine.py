"""
swing_trend_velocity_engine.py
-------------------------------
"White Light" systematic trend-following + mean-reversion position trading
— Malik.

Source: https://www.youtube.com/watch?v=pBS5vrqrUjk

As taught, the system:
  - Trades TQQQ (3x leveraged long NASDAQ-100) when the trend is up and
    SQQQ (3x leveraged short NASDAQ-100) when the trend is down — no
    individual-stock fundamental analysis, no news, no RSI/Ichimoku, only
    the daily closing price of the index.
  - Trend-following core (the "golden rule"): massive rallies historically
    never happen unless price is above BOTH the 50-day and 250-day moving
    averages. Break above both -> buy and hold. Break below both -> the
    mirror short case.
  - Mean-reversion overlay: rate-of-change (velocity) measures whether the
    trend is decelerating. When a strong trend starts slowing down, the
    system scales OUT of part of the position to protect profits — even
    though the moving averages still say the trend is technically intact.
  - Low frequency: ~1-2 rebalances a week across a full system; once a
    trend is established the position is held for months to years. This
    is position trading, not day trading — evaluated once per day on the
    daily close (matches "10 minutes a day, 15-20 min before the close").
  - No tactical stop-loss. The only exit is a full trend reversal (price
    back through both moving averages). Backtested across 42 years of
    data (since 1985); the discipline is sitting through 20-30% drawdowns
    without turning the system off.

This app has no TQQQ/SQQQ-style leveraged instruments on Groww/CoinDCX, so
this implementation applies the identical rule set directly to whatever
ticker is scanned (India stock/index, US stock/ETF, or crypto pair) —
LONG when the golden rule says buy, SHORT when it says sell (expressed as
a directional signal on the underlying rather than a literal leveraged-ETF
allocation), exactly like every other multi-asset-class strategy in this
app. It reports a target allocation (+100% full long ... -100% full short,
0% flat/cash) and flags `take_trade` only on a day the target actually
changes (a rebalance), matching the "mostly HOLD, occasionally act"
cadence described in the video.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.intraday_shared import enrich_intra_live

logger = logging.getLogger(__name__)

YOUTUBE_TREND_VELOCITY_URL = "https://www.youtube.com/watch?v=pBS5vrqrUjk"


@dataclass
class TrendVelocityConfig:
    execution_tf: str = "1d"
    sma_fast: int = 50
    sma_slow: int = 250
    roc_period: int = 20
    roc_peak_lookback: int = 60
    scale_out_drop_pct: float = 40.0     # ROC must fall this much (relative to its own recent peak/trough) to trigger a scale-out
    full_allocation_pct: float = 100.0
    scaled_allocation_pct: float = 50.0
    lookback: int = 600
    min_bars: int = 280


def add_trend_velocity_indicators(df: pd.DataFrame, cfg: TrendVelocityConfig) -> pd.DataFrame:
    out = df.copy()
    out["sma_fast"] = out["close"].rolling(cfg.sma_fast).mean()
    out["sma_slow"] = out["close"].rolling(cfg.sma_slow).mean()
    out["roc"] = out["close"].pct_change(cfg.roc_period) * 100
    out["roc_peak"] = out["roc"].rolling(cfg.roc_peak_lookback).max()
    out["roc_trough"] = out["roc"].rolling(cfg.roc_peak_lookback).min()
    return out


def _trend_state(row: pd.Series) -> str:
    c, f, s = row["close"], row.get("sma_fast"), row.get("sma_slow")
    if pd.isna(f) or pd.isna(s):
        return "UNKNOWN"
    if c > f and c > s and f > s:
        return "BULL"
    if c < f and c < s and f < s:
        return "BEAR"
    return "NEUTRAL"


def _target_allocation(row: pd.Series, cfg: TrendVelocityConfig) -> tuple[float, str]:
    """Golden-rule trend state, then a rate-of-change deceleration check that
    scales the allocation down (not to zero) without abandoning the trend."""
    state = _trend_state(row)
    roc, roc_peak, roc_trough = row.get("roc"), row.get("roc_peak"), row.get("roc_trough")

    if state == "BULL":
        if pd.notna(roc) and pd.notna(roc_peak) and roc_peak > 0 and roc < roc_peak:
            drop = (roc_peak - roc) / roc_peak * 100
            if drop >= cfg.scale_out_drop_pct:
                return cfg.scaled_allocation_pct, "BULL_DECELERATING"
        return cfg.full_allocation_pct, "BULL_FULL"

    if state == "BEAR":
        if pd.notna(roc) and pd.notna(roc_trough) and roc_trough < 0 and roc > roc_trough:
            recover = (roc - roc_trough) / abs(roc_trough) * 100
            if recover >= cfg.scale_out_drop_pct:
                return -cfg.scaled_allocation_pct, "BEAR_DECELERATING"
        return -cfg.full_allocation_pct, "BEAR_FULL"

    return 0.0, "FLAT"


def evaluate_live_signal(work: pd.DataFrame, cfg: TrendVelocityConfig) -> dict[str, Any]:
    if work.empty or len(work) < 2 or "sma_slow" not in work.columns:
        return {"signal": "NO_DATA", "verdict": "NO DATA", "take_trade": False}

    last, prev = work.iloc[-1], work.iloc[-2]
    price = float(last["close"])
    sma_fast = float(last["sma_fast"]) if pd.notna(last.get("sma_fast")) else None
    sma_slow = float(last["sma_slow"]) if pd.notna(last.get("sma_slow")) else None
    roc = float(last["roc"]) if pd.notna(last.get("roc")) else None

    alloc, phase = _target_allocation(last, cfg)
    prev_alloc, prev_phase = _target_allocation(prev, cfg)
    rebalance = abs(alloc - prev_alloc) > 1e-9

    direction = "LONG" if alloc > 0 else "SHORT" if alloc < 0 else None
    take = rebalance and direction is not None

    reasons: list[str] = [
        f"Golden rule: massive rallies never happen unless price is above BOTH the "
        f"{cfg.sma_fast}-day and {cfg.sma_slow}-day moving averages (and the mirror for a bear trend).",
    ]
    if sma_fast is not None and sma_slow is not None:
        reasons.append(
            f"Price {price:,.4g} vs SMA{cfg.sma_fast} {sma_fast:,.4g} vs SMA{cfg.sma_slow} {sma_slow:,.4g} -> trend **{phase}**."
        )
    else:
        reasons.append(f"Not enough history yet for the {cfg.sma_slow}-day moving average.")
    if roc is not None:
        decel = "DECELERATING" in phase
        reasons.append(
            f"{cfg.roc_period}-day rate of change: {roc:+.2f}% — "
            + ("velocity has faded from its recent extreme, scaling the position down to protect profits."
               if decel else
               "momentum intact, no deceleration flagged.")
        )
    reasons.append(f"Target allocation: {alloc:+.0f}% ({'long' if alloc > 0 else 'short' if alloc < 0 else 'flat / cash'}).")
    if rebalance:
        reasons.append(
            f"Rebalance today — yesterday's target was {prev_alloc:+.0f}% ({prev_phase}), today's is {alloc:+.0f}% ({phase})."
        )
    else:
        reasons.append(
            "No change from yesterday — hold the existing position. This is a low-frequency system "
            "(~1-2 rebalances a week across a full portfolio); most days are simply HOLD."
        )
    reasons.append(
        "No tactical stop-loss — the only exit is a full trend reversal (price back through both moving "
        "averages). Backtested across 42 years of data; the discipline is sitting through 20-30% drawdowns "
        "without turning the system off."
    )

    verdict = (
        f"{'BUY / HOLD LONG' if alloc > 0 else 'SELL / HOLD SHORT' if alloc < 0 else 'FLAT / CASH'}"
        f" @ {alloc:+.0f}% allocation" + (" — REBALANCE" if rebalance else "")
    )
    confidence = 0.0
    if phase in ("BULL_FULL", "BEAR_FULL"):
        confidence = 75.0
    elif "DECELERATING" in phase:
        confidence = 55.0

    sl_pct = tp_pct = None
    if direction and sma_slow:
        # Distance to the golden-rule MA — the level that, if crossed, invalidates the trend.
        # Not a tactical stop; it's how much room the position has before the rule itself flips.
        sl_pct = round(abs(price - sma_slow) / price * 100, 2)

    hold_duration = "Position trade — months to years, held as long as the trend stays intact (no fixed exit)"

    plan = make_trade_plan(
        direction=direction or "—", timeframe=cfg.execution_tf, stop_loss_pct=sl_pct, take_profit_pct=tp_pct,
        confidence_pct=confidence, style="swing",
        exit_rule=(
            "No fixed target — ride the trend. Exit (flip to flat/opposite) only when price closes back "
            f"through both the {cfg.sma_fast}-day and {cfg.sma_slow}-day moving averages, or scale out on "
            "rate-of-change deceleration as described above."
        ),
        max_hold_exit="No time-based exit — hold for months to years while the golden rule remains satisfied.",
    )

    live = enrich_intra_live({
        "signal": direction if take else ("HOLD" if direction else "FLAT"),
        "direction": direction,
        "take_trade": take,
        "verdict": verdict,
        "phase": phase,
        "confidence_pct": confidence,
        "sl_pct": sl_pct,
        "tp_pct": tp_pct,
        "entry_price": round(price, 6),
        "stop_price": round(sma_slow, 6) if sma_slow is not None else None,
        "target_price": None,
        "target_allocation_pct": alloc,
        "prev_target_allocation_pct": prev_alloc,
        "sma_fast": round(sma_fast, 6) if sma_fast is not None else None,
        "sma_slow": round(sma_slow, 6) if sma_slow is not None else None,
        "roc_pct": round(roc, 2) if roc is not None else None,
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": hold_duration},
    }, hold_duration=hold_duration)

    return live


def analyze_ticker(
    ticker: str, market: str, *, cfg: TrendVelocityConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or TrendVelocityConfig()
    is_crypto = "CoinDCX" in market

    df = fetch_data_for_gap_scan(ticker, "1d", market, groww_token, exchange, limit=cfg.lookback)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < cfg.min_bars:
        df = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, "1d", is_crypto=is_crypto, limit=cfg.lookback, market=market)
        )
    if df.empty or len(df) < cfg.min_bars:
        return {
            "ticker": ticker, "market": market,
            "error": f"Insufficient daily data ({len(df)} bars, need {cfg.min_bars}+ for the {cfg.sma_slow}-day moving average).",
        }

    work = add_trend_velocity_indicators(df, cfg)
    live = evaluate_live_signal(work, cfg)

    return {
        "ticker": ticker, "market": market, "execution_tf": "1d",
        "bars": len(work), "last_close": float(work["close"].iloc[-1]),
        "live": live,
    }


def scan_universe(
    tickers: list[str], market: str, *, cfg: TrendVelocityConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or TrendVelocityConfig()
    results = []
    for ticker in tickers:
        try:
            results.append(analyze_ticker(ticker, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            logger.debug("Trend Velocity scan failed for %s: %s", ticker, exc)
            results.append({"ticker": ticker, "market": market, "error": str(exc)[:200]})

    entries = [r for r in results if not r.get("error") and (r.get("live") or {}).get("take_trade")]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market, "execution_tf": "1d", "results": results,
        "entries": entries, "entry_count": len(entries),
    }
