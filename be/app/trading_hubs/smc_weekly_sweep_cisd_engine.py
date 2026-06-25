"""
smc_weekly_sweep_cisd_engine.py
---------------------------------
Weekly Liquidity Sweep + LTF CISD model (Smart Money Trader).

Previous week high/low → sweep liquidity → lower-TF CISD failure → entry.
SL behind sweep extreme; TP at opposing weekly level.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.smart_money_shared import enrich_smc_live
from app.trading_hubs.swing_trading_st_mtf_mss_engine import (
    build_weekly_from_daily,
    calculate_weekly_levels,
)

logger = logging.getLogger(__name__)

YOUTUBE_SMC_WEEKLY_SWEEP_URL = "https://www.youtube.com/watch?v=jT6fvhZXSsw"

LTF_OPTIONS = ["5m", "15m", "30m"]

PHASE_ENTRY = "CISD_ENTRY"
PHASE_AWAIT = "AWAIT_CISD"
PHASE_SWEEP = "SWEEP_DETECTED"
PHASE_NONE = "NO_SETUP"

HOLD_WEEKLY_SWEEP = "1–2 weeks (target opposing weekly level)"


@dataclass
class WeeklySweepCISDConfig:
    execution_tf: str = "15m"
    stop_buffer_pct: float = 0.001
    take_confidence_threshold: float = 62.0
    daily_lookback: int = 504
    ltf_lookback: int = 500
    min_ltf_bars: int = 80
    min_daily_bars: int = 60


@dataclass
class WeeklySweepSetup:
    direction: str
    state: str
    sweep_extreme: float
    weekly_level: float
    opposing_level: float
    entry_price: float
    stop_price: float
    target_price: float
    bar_index: int


def _fetch_daily(
    ticker: str,
    market: str,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
    limit: int = 504,
) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    df = fetch_data_for_gap_scan(ticker, "1d", market, groww_token, exchange, limit=limit)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < 30:
        df = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, "1d", is_crypto=is_crypto, limit=limit, market=market)
        )
    return df


def fetch_ltf_data(
    ticker: str,
    tf: str,
    market: str,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
    limit: int = 500,
) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    df = fetch_data_for_gap_scan(ticker, tf, market, groww_token, exchange, limit=limit)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < 30:
        df = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, tf, is_crypto=is_crypto, limit=limit, market=market)
        )
    return df


def map_weekly_levels_to_ltf(
    df_ltf: pd.DataFrame,
    weekly_levels: pd.DataFrame,
) -> pd.DataFrame:
    """Attach previous-week high/low to each lower-TF bar."""
    work = normalize_ohlcv(df_ltf).copy()
    if work.empty or weekly_levels.empty:
        return work

    weekly = weekly_levels.copy()
    weekly["week_id"] = weekly.index.to_period("W").astype(str)
    work["week_id"] = work.index.to_period("W").astype(str)
    levels = weekly.set_index("week_id")[["pwh", "pwl"]]
    return work.join(levels, on="week_id")


def implement_weekly_sweep_cisd(
    df_ltf: pd.DataFrame,
    weekly_levels: pd.DataFrame,
    cfg: WeeklySweepCISDConfig,
) -> tuple[pd.DataFrame, list[WeeklySweepSetup]]:
    """
    Weekly sweep + LTF CISD (MSS approximation).

    No sweep, no failure, no entry — pierce PWH/PWL then reversal close inside.
    """
    work = map_weekly_levels_to_ltf(df_ltf, weekly_levels)
    if work.empty:
        return work, []

    work["signal"] = 0
    work["stop_loss"] = np.nan
    work["take_profit"] = np.nan
    work["sweep_extreme"] = np.nan
    setups: list[WeeklySweepSetup] = []

    for i in range(1, len(work)):
        row = work.iloc[i]
        prev = work.iloc[i - 1]
        pwh = row.get("pwh")
        pwl = row.get("pwl")
        if pd.isna(pwh) or pd.isna(pwl):
            continue

        pwh, pwl = float(pwh), float(pwl)
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        ph, pl = float(prev["high"]), float(prev["low"])

        swept_high = h > pwh or ph > pwh
        if swept_high and c < pwh and c < o:
            stop = max(h, ph) * (1 + cfg.stop_buffer_pct)
            work.at[work.index[i], "signal"] = -1
            work.at[work.index[i], "stop_loss"] = stop
            work.at[work.index[i], "take_profit"] = pwl
            work.at[work.index[i], "sweep_extreme"] = max(h, ph)
            setups.append(WeeklySweepSetup(
                direction="SHORT",
                state=PHASE_ENTRY,
                sweep_extreme=max(h, ph),
                weekly_level=pwh,
                opposing_level=pwl,
                entry_price=c,
                stop_price=stop,
                target_price=pwl,
                bar_index=i,
            ))

        swept_low = l < pwl or pl < pwl
        if swept_low and c > pwl and c > o:
            stop = min(l, pl) * (1 - cfg.stop_buffer_pct)
            work.at[work.index[i], "signal"] = 1
            work.at[work.index[i], "stop_loss"] = stop
            work.at[work.index[i], "take_profit"] = pwh
            work.at[work.index[i], "sweep_extreme"] = min(l, pl)
            setups.append(WeeklySweepSetup(
                direction="LONG",
                state=PHASE_ENTRY,
                sweep_extreme=min(l, pl),
                weekly_level=pwl,
                opposing_level=pwh,
                entry_price=c,
                stop_price=stop,
                target_price=pwh,
                bar_index=i,
            ))

    return work, setups


def _current_week_bars(work: pd.DataFrame) -> pd.DataFrame:
    if work.empty:
        return work
    cur_week = work.index[-1].to_period("W")
    mask = work.index.to_period("W") == cur_week
    return work.loc[mask]


def _detect_pending_sweep(work: pd.DataFrame) -> dict[str, Any] | None:
    """Sweep without CISD yet — watch state."""
    week = _current_week_bars(work)
    if week.empty:
        return None

    pwh = week["pwh"].iloc[-1]
    pwl = week["pwl"].iloc[-1]
    if pd.isna(pwh) or pd.isna(pwl):
        return None
    pwh, pwl = float(pwh), float(pwl)

    week_high = float(week["high"].max())
    week_low = float(week["low"].min())
    last = week.iloc[-1]
    lc = float(last["close"])

    if week_high > pwh and lc >= pwh:
        return {
            "direction": "SHORT",
            "phase": PHASE_SWEEP,
            "weekly_level": pwh,
            "opposing_level": pwl,
            "sweep_extreme": week_high,
            "reason": "Weekly high swept — await LTF CISD (close back below PWH)",
        }
    if week_low < pwl and lc <= pwl:
        return {
            "direction": "LONG",
            "phase": PHASE_AWAIT,
            "weekly_level": pwl,
            "opposing_level": pwh,
            "sweep_extreme": week_low,
            "reason": "Weekly low swept — await LTF CISD (close back above PWL)",
        }
    return None


def evaluate_live_signal(
    work: pd.DataFrame,
    setups: list[WeeklySweepSetup],
    cfg: WeeklySweepCISDConfig,
    *,
    weekly_levels: pd.DataFrame | None = None,
) -> dict[str, Any]:
    if work.empty:
        return {"signal": "NO_DATA"}

    price = float(work["close"].iloc[-1])
    latest_sig = int(work["signal"].iloc[-1]) if work["signal"].iloc[-1] != 0 else 0
    last_setup = setups[-1] if setups else None
    pending = _detect_pending_sweep(work)

    pwh = pwl = None
    if weekly_levels is not None and not weekly_levels.empty:
        pwh = float(weekly_levels["pwh"].iloc[-1]) if pd.notna(weekly_levels["pwh"].iloc[-1]) else None
        pwl = float(weekly_levels["pwl"].iloc[-1]) if pd.notna(weekly_levels["pwl"].iloc[-1]) else None
    elif "pwh" in work.columns:
        pwh = float(work["pwh"].iloc[-1]) if pd.notna(work["pwh"].iloc[-1]) else None
        pwl = float(work["pwl"].iloc[-1]) if pd.notna(work["pwl"].iloc[-1]) else None

    reasons: list[str] = []
    conf = 28.0
    direction = "WAIT"
    phase = PHASE_NONE
    verdict = "WAIT"
    take = False
    stop = price
    target = price
    sweep_ext = None
    weekly_lvl = None
    opposing = None

    # Entry on latest bar or very recent CISD (same week)
    recent_entry = None
    if last_setup and last_setup.bar_index >= len(work) - 3:
        recent_entry = last_setup

    if latest_sig != 0 and recent_entry:
        direction = recent_entry.direction
        phase = PHASE_ENTRY
        verdict = f"TAKE {direction}"
        conf += 38
        stop = recent_entry.stop_price
        target = recent_entry.target_price
        sweep_ext = recent_entry.sweep_extreme
        weekly_lvl = recent_entry.weekly_level
        opposing = recent_entry.opposing_level
        reasons.append("LTF CISD confirmed — sweep failed, reversal candle closed inside weekly level")
        reasons.append("Entry on CISD candle per golden weekly sweep model")
    elif pending:
        direction = pending["direction"]
        phase = pending["phase"]
        verdict = f"WATCH {direction}"
        conf += 20
        sweep_ext = pending["sweep_extreme"]
        weekly_lvl = pending["weekly_level"]
        opposing = pending["opposing_level"]
        reasons.append(pending["reason"])
        reasons.append("No sweep / no failure / no entry — waiting for CISD")
    else:
        if pwh and pwl:
            reasons.append(f"PWH {pwh:,.4g} · PWL {pwl:,.4g} — no active sweep failure this week")
        else:
            reasons.append("Weekly levels unavailable — need more daily history")

    if pwh and pwl and price > pwl and price < pwh:
        conf += 8
        reasons.append("Price inside prior week range — liquidity model context valid")

    conf = max(18.0, min(92.0, conf))
    take = phase == PHASE_ENTRY and conf >= cfg.take_confidence_threshold

    if direction == "LONG" and stop < price:
        sl_pct = max(0.4, (price - stop) / price * 100)
        tp_pct = max(0.5, (target - price) / price * 100) if target > price else sl_pct * 2
    elif direction == "SHORT" and stop > price:
        sl_pct = max(0.4, (stop - price) / price * 100)
        tp_pct = max(0.5, (price - target) / price * 100) if target < price else sl_pct * 2
    else:
        sl_pct = 2.0
        tp_pct = 4.0

    rr = tp_pct / sl_pct if sl_pct > 0 else 2.0
    hold = HOLD_WEEKLY_SWEEP

    plan_dir = direction if take and direction in ("LONG", "SHORT") else "—"
    plan = make_trade_plan(
        direction=plan_dir,
        timeframe=cfg.execution_tf,
        stop_loss_pct=round(sl_pct, 2),
        take_profit_pct=round(tp_pct, 2),
        confidence_pct=round(conf, 1),
        style="swing",
        exit_rule=(
            "SL behind sweep extreme. TP at opposing weekly level (PWH/PWL). "
            "Invalidate if price re-sweeps beyond stop."
        ),
        max_hold_exit=hold,
    )

    return enrich_smc_live({
        "signal": "BUY" if latest_sig == 1 else ("SELL" if latest_sig == -1 else "NONE"),
        "direction": direction,
        "take_trade": take,
        "verdict": verdict,
        "phase": phase,
        "confidence_pct": round(conf, 1),
        "sl_pct": round(sl_pct, 2),
        "tp_pct": round(tp_pct, 2),
        "hold_duration": hold,
        "rr_ratio": round(rr, 2),
        "entry_price": round(price, 6),
        "stop_price": round(stop, 6),
        "target_price": round(target, 6),
        "sweep_extreme": sweep_ext,
        "weekly_level": weekly_lvl,
        "opposing_weekly": opposing,
        "prev_weekly_high": pwh,
        "prev_weekly_low": pwl,
        "execution_tf": cfg.execution_tf,
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": hold},
    }, hold_duration=hold)


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: WeeklySweepCISDConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or WeeklySweepCISDConfig()
    daily = _fetch_daily(
        ticker, market, groww_token=groww_token, exchange=exchange, limit=cfg.daily_lookback,
    )
    if daily.empty or len(daily) < cfg.min_daily_bars:
        return {"ticker": ticker, "error": "Insufficient daily data for weekly levels."}

    weekly = build_weekly_from_daily(daily)
    levels = calculate_weekly_levels(weekly)
    if levels.empty:
        return {"ticker": ticker, "error": "Could not compute previous weekly high/low."}

    ltf = fetch_ltf_data(
        ticker, cfg.execution_tf, market,
        groww_token=groww_token, exchange=exchange, limit=cfg.ltf_lookback,
    )
    if ltf.empty or len(ltf) < cfg.min_ltf_bars:
        return {"ticker": ticker, "error": f"Insufficient {cfg.execution_tf} data."}

    work, setups = implement_weekly_sweep_cisd(ltf, levels, cfg)
    live = evaluate_live_signal(work, setups, cfg, weekly_levels=levels)
    entries = [s for s in setups if s.state == PHASE_ENTRY]

    cur_pwh = float(levels["pwh"].iloc[-1]) if pd.notna(levels["pwh"].iloc[-1]) else None
    cur_pwl = float(levels["pwl"].iloc[-1]) if pd.notna(levels["pwl"].iloc[-1]) else None

    return {
        "ticker": ticker,
        "market": market,
        "execution_tf": cfg.execution_tf,
        "bars": len(work),
        "last_close": float(work["close"].iloc[-1]),
        "prev_weekly_high": cur_pwh,
        "prev_weekly_low": cur_pwl,
        "setup_count": len(setups),
        "entry_signals": len(entries),
        "live": live,
    }


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: WeeklySweepCISDConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or WeeklySweepCISDConfig()
    results = []
    for ticker in tickers:
        try:
            results.append(
                analyze_ticker(ticker, market, cfg=cfg, groww_token=groww_token, exchange=exchange)
            )
        except Exception as exc:
            results.append({"ticker": ticker, "error": str(exc)[:200]})

    entries = [r for r in results if not r.get("error") and (r.get("live") or {}).get("take_trade")]
    watches = [
        r for r in results
        if not r.get("error")
        and not (r.get("live") or {}).get("take_trade")
        and (r.get("live") or {}).get("phase") in (PHASE_AWAIT, PHASE_SWEEP)
    ]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))
    watches.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market,
        "execution_tf": cfg.execution_tf,
        "results": results,
        "entries": entries,
        "watchlist": watches,
        "entry_count": len(entries),
        "watch_count": len(watches),
    }
