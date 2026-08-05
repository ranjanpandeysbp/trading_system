"""
volume_spread_next_candle_engine.py
-----------------------------------
Volume Spread Analysis (VSA) — Wyckoff / smart-money supply-demand via spread vs volume.

Source playlist: https://www.youtube.com/watch?v=ncrqXFCQKOU&list=PLXWi52aRZnNF_HW-TedxAE1Tyx1C8XrGn

Signals (predict the *next* candle):
  Signs of Strength (expect next bar up):
    • Downthrust — low-spread bullish pin/doji + above-average / ultra-high volume
    • No Supply  — low-spread bearish bar with lower wick + volume < prior two bars
  Signs of Weakness (expect next bar down):
    • Upthrust   — low-spread bearish pin/doji + above-average / ultra-high volume
    • No Demand  — low-spread bullish bar with upper wick + volume < prior two bars

Research / education only — not financial advice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.pa_vp_smc_engine import PaVpSmcConfig, find_swing_sr_zones
from app.market_pulse.pro_trade_shared import (
    ConfidenceScore,
    atr as _atr_ind,
    build_pro_trade_ai_context,
    pro_trade_ai_system,
    sl_tp_pct,
)
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.smart_money_shared import hold_for_tf

logger = logging.getLogger(__name__)

YOUTUBE_URL = "https://www.youtube.com/watch?v=ncrqXFCQKOU&list=PLXWi52aRZnNF_HW-TedxAE1Tyx1C8XrGn"
STRATEGY_NAME = "Volume Spread - Next Candle"
_INTRADAY = {"1m", "3m", "5m", "15m", "30m", "1h"}


@dataclass
class VolumeSpreadConfig:
    timeframe: str = "15m"
    lookback_bars: int = 200
    vol_ma_period: int = 20
    ultra_vol_lookback: int = 50
    low_spread_factor: float = 0.75  # spread < factor × avg_spread → low spread
    pin_wick_ratio: float = 1.2  # lower/upper wick vs body for pin emphasis
    rr_ratio: float = 1.5
    take_confidence_threshold: float = 55.0
    max_setups: int = 12
    min_bars: int = 60
    context_lookback: int = 20  # swing-high/low window for absorption/distribution context


def _build_chart_data(df: pd.DataFrame, *, max_bars: int = 160) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    tail = df.iloc[-max_bars:]
    return [
        {
            "time": str(idx),
            "open": round(float(bar["open"]), 6),
            "high": round(float(bar["high"]), 6),
            "low": round(float(bar["low"]), 6),
            "close": round(float(bar["close"]), 6),
            "volume": round(float(bar["volume"]), 2) if "volume" in bar and pd.notna(bar["volume"]) else None,
        }
        for idx, bar in tail.iterrows()
    ]


def calculate_vsa(df: pd.DataFrame, cfg: VolumeSpreadConfig) -> pd.DataFrame:
    """Annotate OHLCV with VSA metrics and boolean signal columns."""
    work = normalize_ohlcv(df).copy()
    if work.empty or "volume" not in work.columns:
        return work

    o, h, l, c, v = work["open"], work["high"], work["low"], work["close"], work["volume"]
    body_top = pd.concat([o, c], axis=1).max(axis=1)
    body_bot = pd.concat([o, c], axis=1).min(axis=1)

    work["spread"] = (c - o).abs()
    work["candle_range"] = (h - l).clip(lower=0)
    work["upper_wick"] = (h - body_top).clip(lower=0)
    work["lower_wick"] = (body_bot - l).clip(lower=0)
    work["is_bullish"] = c >= o
    work["is_bearish"] = c < o

    work["vol_ma"] = v.rolling(cfg.vol_ma_period, min_periods=max(5, cfg.vol_ma_period // 2)).mean()
    prior_peak = v.rolling(cfg.ultra_vol_lookback, min_periods=10).max().shift(1)
    work["above_avg_vol"] = v > work["vol_ma"]
    work["ultra_high_vol"] = v > prior_peak
    work["high_vol"] = work["above_avg_vol"] | work["ultra_high_vol"]

    work["avg_spread"] = work["spread"].rolling(cfg.vol_ma_period, min_periods=5).mean()
    work["low_spread"] = work["spread"] < (work["avg_spread"] * cfg.low_spread_factor)

    # Pin / doji geometry: long wick relative to body, or near-doji body.
    # A doji only counts toward the side its wick actually favors — otherwise a
    # symmetric-doji bar would satisfy pin_bull AND pin_bear simultaneously and
    # let contradictory SOS/SOW tags fire off the same candle.
    body = work["spread"].replace(0, np.nan)
    is_doji = work["spread"] <= work["avg_spread"] * 0.35
    work["pin_bull"] = (work["lower_wick"] >= body * cfg.pin_wick_ratio) | (
        is_doji & (work["lower_wick"] >= work["upper_wick"])
    )
    work["pin_bear"] = (work["upper_wick"] >= body * cfg.pin_wick_ratio) | (
        is_doji & (work["upper_wick"] >= work["lower_wick"])
    )

    # Context: is this bar sitting at a recent swing extreme? Classic VSA reads
    # absorption/distribution bars relative to background — a downthrust/no-supply
    # at a fresh swing low, or an upthrust/no-demand at a fresh swing high, carries
    # far more weight than the same bar mid-range.
    recent_low = l.rolling(cfg.context_lookback, min_periods=5).min()
    recent_high = h.rolling(cfg.context_lookback, min_periods=5).max()
    work["near_recent_low"] = l <= recent_low * 1.003
    work["near_recent_high"] = h >= recent_high * 0.997

    # Signs of Strength
    work["sos_downthrust"] = (
        work["is_bullish"]
        & work["low_spread"]
        & work["high_vol"]
        & work["pin_bull"]
    )
    work["sos_no_supply"] = (
        work["is_bearish"]
        & work["low_spread"]
        & (work["lower_wick"] > 0)
        & (v < v.shift(1))
        & (v < v.shift(2))
    )

    # Signs of Weakness
    work["sow_upthrust"] = (
        work["is_bearish"]
        & work["low_spread"]
        & work["high_vol"]
        & work["pin_bear"]
    )
    work["sow_no_demand"] = (
        work["is_bullish"]
        & work["low_spread"]
        & (work["upper_wick"] > 0)
        & (v < v.shift(1))
        & (v < v.shift(2))
    )

    return work


def _support_resistance(work: pd.DataFrame, cfg: VolumeSpreadConfig) -> dict[str, Any]:
    """Nearest classic swing support/resistance around the current price —
    reuses PA-VP-SMC's swing-fractal S/R detector so this strategy's chart
    shows the same institutional-grade levels rather than a second,
    diverging notion of "support"."""
    sr_cfg = PaVpSmcConfig(swing_window=5, lookback_bars=min(cfg.lookback_bars, 300))
    try:
        zones = find_swing_sr_zones(work, sr_cfg)
    except Exception:
        return {"support": None, "resistance": None}
    support = zones.get("support")
    resistance = zones.get("resistance")
    return {
        "support": round(float(support["top"]), 6) if support else None,
        "resistance": round(float(resistance["bottom"]), 6) if resistance else None,
    }


def _trade_explanation(
    *,
    take_trade: bool,
    verdict: str,
    best: dict[str, Any] | None,
    threshold: float,
    stats: dict[str, Any],
    sr: dict[str, Any],
    ltp: float,
) -> str:
    """Plain-English "should I actually trade this" paragraph — the short
    ConfidenceScore reason strings explain the score's math, this explains
    the decision in trader language."""
    hit_rate = stats.get("hit_rate_pct")
    hit_note = (
        f" This ticker's VSA signals have hit their next-candle direction {hit_rate}% of the time "
        f"({stats.get('wins')}/{stats.get('samples')}) recently — informational, not a guarantee."
        if hit_rate is not None
        else ""
    )
    sr_note = ""
    if sr.get("support") is not None and sr.get("resistance") is not None:
        sr_note = f" Nearest swing support is {sr['support']:g}, nearest resistance is {sr['resistance']:g}."
    elif sr.get("support") is not None:
        sr_note = f" Nearest swing support is {sr['support']:g}."
    elif sr.get("resistance") is not None:
        sr_note = f" Nearest swing resistance is {sr['resistance']:g}."

    if best is None:
        return (
            "No VSA Downthrust / No Supply / Upthrust / No Demand signal printed on the latest closed candle — "
            "there is nothing here to trade right now." + sr_note + hit_note
        )

    setup_label = str(best.get("setup", "")).replace("_", " ")
    direction = str(best.get("direction", ""))
    conf = float(best.get("confidence_pct") or 0)
    rr = best.get("rr_ratio")

    if take_trade:
        verdict_line = (
            f"TRADE CASE: worth taking. Confidence {conf:.0f}% clears the {threshold:.0f}% bar for action, "
            f"and the setup targets roughly 1:{rr:g} reward-to-risk."
        )
    else:
        verdict_line = (
            f"TRADE CASE: watch only, don't size in yet. Confidence is {conf:.0f}%, below the {threshold:.0f}% bar "
            "this strategy requires before calling it actionable — the pattern is real but not yet convincing enough "
            "on volume/context to risk capital."
        )

    return (
        f"{setup_label.title()} fired on the latest closed candle, favoring {direction}. "
        f"{verdict_line} Remember this is a next-candle-only edge — if the very next bar doesn't move your way, "
        "the setup has failed and there is no reason to hold for a slower reversal." + sr_note + hit_note
    )


def _next_candle_result(work: pd.DataFrame, i: int, direction: str) -> str | None:
    """Did the next candle move in the predicted direction?"""
    if i + 1 >= len(work):
        return None
    nxt = work.iloc[i + 1]
    cur_close = float(work.iloc[i]["close"])
    nxt_close = float(nxt["close"])
    if direction == "LONG":
        return "Win" if nxt_close > cur_close else "Loss"
    return "Win" if nxt_close < cur_close else "Loss"


def extract_setups(work: pd.DataFrame, cfg: VolumeSpreadConfig) -> list[dict[str, Any]]:
    setups: list[dict[str, Any]] = []
    if work.empty or len(work) < cfg.min_bars:
        return setups

    atr_s = _atr_ind(work, 14)
    hold = hold_for_tf(cfg.timeframe, "intraday" if cfg.timeframe in _INTRADAY else "swing")
    last_i = len(work) - 1

    for i in range(max(cfg.vol_ma_period, 3), len(work)):
        row = work.iloc[i]
        tags: list[tuple[str, str, str]] = []  # (setup_id, direction, logic)
        if bool(row.get("sos_downthrust")):
            tags.append((
                "downthrust",
                "LONG",
                "Downthrust (SOS): low-spread bullish pin/doji + above-avg/ultra-high volume — demand absorbing supply",
            ))
        if bool(row.get("sos_no_supply")):
            tags.append((
                "no_supply",
                "LONG",
                "No Supply (SOS): low-spread bearish bar with lower wick + volume < prior 2 bars — sellers drying up",
            ))
        if bool(row.get("sow_upthrust")):
            tags.append((
                "upthrust",
                "SHORT",
                "Upthrust (SOW): low-spread bearish pin/doji + above-avg/ultra-high volume — supply overwhelming buyers",
            ))
        if bool(row.get("sow_no_demand")):
            tags.append((
                "no_demand",
                "SHORT",
                "No Demand (SOW): low-spread bullish bar with upper wick + volume < prior 2 bars — buyers drying up",
            ))
        if not tags:
            continue

        entry = float(row["close"])
        high = float(row["high"])
        low = float(row["low"])
        atr_v = float(atr_s.iloc[i]) if pd.notna(atr_s.iloc[i]) else entry * 0.005
        vol = float(row["volume"]) if pd.notna(row["volume"]) else 0.0
        vol_ma = float(row["vol_ma"]) if pd.notna(row.get("vol_ma")) else None
        ultra = bool(row.get("ultra_high_vol"))
        is_live_bar = i == last_i

        for setup_id, direction, logic in tags:
            if direction == "LONG":
                stop = low - atr_v * 0.15
                risk = max(entry - stop, atr_v * 0.25)
                target = entry + risk * cfg.rr_ratio
            else:
                stop = high + atr_v * 0.15
                risk = max(stop - entry, atr_v * 0.25)
                target = entry - risk * cfg.rr_ratio

            next_res = _next_candle_result(work, i, direction)
            if is_live_bar:
                signal = "BUY" if direction == "LONG" else "SELL"
                phase = "NEXT_CANDLE_ARMED"
                status_logic = f"{logic} · expect next candle {direction}"
            elif next_res == "Win":
                signal = "CONFIRMED"
                phase = "NEXT_CANDLE_HIT"
                status_logic = f"{logic} · next candle confirmed ({next_res})"
            elif next_res == "Loss":
                signal = "FAILED"
                phase = "NEXT_CANDLE_MISS"
                status_logic = f"{logic} · next candle against ({next_res})"
            else:
                signal = "WATCH"
                phase = "HISTORICAL"
                status_logic = logic

            sl_pct, tp_pct = sl_tp_pct(direction, entry, stop, target)
            score = ConfidenceScore(
                42,
                f"VSA {setup_id.replace('_', ' ')} on {cfg.timeframe}",
            )
            score.add(bool(row.get("low_spread")), 8, "low body spread vs 20-bar average")
            score.add(bool(row.get("above_avg_vol")), 8, "volume above 20 MA")
            score.add(ultra, 10, "ultra-high volume (session peak proxy)")
            score.add(setup_id in ("downthrust", "upthrust"), 6, "thrust / pin absorption bar")
            score.add(setup_id in ("no_supply", "no_demand"), 5, "no-supply / no-demand drying volume")
            if direction == "LONG":
                score.add(
                    bool(row.get("near_recent_low")),
                    7,
                    f"signal bar at/near {cfg.context_lookback}-bar swing low — absorption at demand zone",
                )
            else:
                score.add(
                    bool(row.get("near_recent_high")),
                    7,
                    f"signal bar at/near {cfg.context_lookback}-bar swing high — distribution at supply zone",
                )
            score.add(is_live_bar, 8, "signal on latest closed bar → next-candle trigger")
            score.add(next_res == "Win", 5, "historical next-candle win nearby in stream")
            conf, reasons = score.finalize()

            setups.append({
                "setup": setup_id,
                "family": "SOS" if direction == "LONG" else "SOW",
                "signal": signal,
                "phase": phase,
                "direction": direction,
                "entry": round(entry, 6),
                "stop_loss": round(stop, 6),
                "target_1": round(target, 6),
                "sl_pct": sl_pct,
                "tp_pct": tp_pct,
                "rr_ratio": cfg.rr_ratio,
                "confidence_pct": conf,
                "volume": round(vol, 2),
                "vol_ma": round(vol_ma, 2) if vol_ma is not None else None,
                "ultra_high_vol": ultra,
                "spread": round(float(row["spread"]), 6),
                "bar_time": str(work.index[i]),
                "next_candle_result": next_res,
                "is_live": is_live_bar,
                "hold_duration": hold,
                "logic": status_logic,
                "reasons": reasons,
            })

    # Prefer live + recent
    setups.sort(key=lambda s: (0 if s.get("is_live") else 1, -float(s.get("confidence_pct") or 0)))
    return setups[: cfg.max_setups]


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: VolumeSpreadConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or VolumeSpreadConfig()
    out: dict[str, Any] = {
        "ticker": ticker,
        "strategy": STRATEGY_NAME,
        "youtube": YOUTUBE_URL,
        "error": None,
        "setups": [],
        "chart_data": [],
        "take_trade": False,
        "verdict": "WAIT",
        "rules": [
            "Spread = |Close − Open|; low spread = body thinner than 75% of the 20-bar average spread.",
            "Above-average volume = Volume > 20 MA; ultra-high = highest vs prior 50 bars.",
            "SOS (Downthrust / No Supply) → expect next candle UP; SOW (Upthrust / No Demand) → next candle DOWN.",
            "Live TAKE uses the latest closed bar's VSA signal; SL beyond signal candle extreme, TP at configured R:R.",
        ],
    }

    try:
        df = fetch_data_for_gap_scan(
            ticker,
            cfg.timeframe,
            market,
            groww_token=groww_token,
            exchange=exchange,
            limit=cfg.lookback_bars,
        )
    except Exception as exc:
        out["error"] = f"Data fetch failed: {exc}"
        return out

    df = normalize_ohlcv(df)
    if df is None or df.empty or len(df) < cfg.min_bars:
        out["error"] = "Insufficient OHLCV for Volume Spread Analysis"
        return out

    work = calculate_vsa(df, cfg)
    setups = extract_setups(work, cfg)
    ltp = round(float(work["close"].iloc[-1]), 6)
    out["ltp"] = ltp
    out["chart_data"] = _build_chart_data(work)
    out["setups"] = setups
    out["bars"] = len(work)

    sr = _support_resistance(work, cfg)
    out["support_level"] = sr["support"]
    out["resistance_level"] = sr["resistance"]

    live = [s for s in setups if s.get("is_live") and s.get("signal") in ("BUY", "SELL")]
    hist = [s for s in setups if s.get("next_candle_result") in ("Win", "Loss")]
    wins = sum(1 for s in hist if s["next_candle_result"] == "Win")
    out["next_candle_stats"] = {
        "samples": len(hist),
        "wins": wins,
        "hit_rate_pct": round(100.0 * wins / len(hist), 1) if hist else None,
    }

    if live:
        best = max(live, key=lambda s: float(s.get("confidence_pct") or 0))
        take = float(best.get("confidence_pct") or 0) >= cfg.take_confidence_threshold
        direction = best["direction"]
        hold = best.get("hold_duration") or hold_for_tf(cfg.timeframe, "intraday")
        plan = make_trade_plan(
            direction=direction if take else "—",
            timeframe=cfg.timeframe,
            stop_loss_pct=round(best.get("sl_pct") or 0, 2),
            take_profit_pct=round(best.get("tp_pct") or 0, 2),
            confidence_pct=best.get("confidence_pct"),
            style="intraday" if cfg.timeframe in _INTRADAY else "swing",
            exit_rule="VSA next-candle: invalidate if next bar closes through signal extreme against the thesis.",
            max_hold_exit=f"Primary edge is the *next* candle; flatten if neither SL nor TP within {hold}.",
        )
        out["take_trade"] = take
        out["verdict"] = f"TAKE {direction}" if take else f"WATCH {direction}"
        out["direction"] = direction
        out["entry_price"] = best["entry"]
        out["stop_price"] = best["stop_loss"]
        out["target_price"] = best["target_1"]
        out["sl_pct"] = best.get("sl_pct")
        out["tp_pct"] = best.get("tp_pct")
        out["confidence_pct"] = best.get("confidence_pct")
        out["hold_duration"] = hold
        out["active_setup"] = best["setup"]
        out["trade_plan"] = {**plan, "holding_period": hold}
        out["reasons"] = best.get("reasons") or [best.get("logic")]
        out["plain_english"] = _trade_explanation(
            take_trade=take,
            verdict=out["verdict"],
            best=best,
            threshold=cfg.take_confidence_threshold,
            stats=out["next_candle_stats"],
            sr=sr,
            ltp=ltp,
        )
    else:
        watch = [s for s in setups if s.get("signal") in ("CONFIRMED", "WATCH", "FAILED")]
        out["verdict"] = "WATCH" if watch else "WAIT"
        out["take_trade"] = False
        out["reasons"] = [
            "No VSA signal on the latest closed bar — waiting for Downthrust / No Supply / Upthrust / No Demand.",
        ]
        out["plain_english"] = _trade_explanation(
            take_trade=False,
            verdict=out["verdict"],
            best=None,
            threshold=cfg.take_confidence_threshold,
            stats=out["next_candle_stats"],
            sr=sr,
            ltp=ltp,
        )

    out["profile"] = {
        "tf": cfg.timeframe,
        "vol_ma": cfg.vol_ma_period,
        "sos_count": sum(1 for s in setups if s.get("family") == "SOS"),
        "sow_count": sum(1 for s in setups if s.get("family") == "SOW"),
    }
    return out


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: VolumeSpreadConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or VolumeSpreadConfig()
    results: list[dict[str, Any]] = []
    for t in tickers:
        try:
            results.append(
                analyze_ticker(t, market, cfg=cfg, groww_token=groww_token, exchange=exchange)
            )
        except Exception as exc:
            logger.exception("VSA next-candle failed for %s", t)
            results.append({"ticker": t, "error": str(exc)[:300], "take_trade": False, "setups": []})

    entries = [r for r in results if not r.get("error") and r.get("take_trade")]
    entries.sort(key=lambda r: -(r.get("confidence_pct") or 0))

    def _rate(items: list[dict[str, Any]]) -> dict[str, Any]:
        w = sum(1 for s in items if s["next_candle_result"] == "Win")
        return {
            "samples": len(items),
            "wins": w,
            "hit_rate_pct": round(100.0 * w / len(items), 1) if items else None,
        }

    all_hist = [
        s
        for r in results
        for s in (r.get("setups") or [])
        if s.get("next_candle_result") in ("Win", "Loss")
    ]
    aggregate_stats = {
        "overall": _rate(all_hist),
        "sos": _rate([s for s in all_hist if s.get("family") == "SOS"]),
        "sow": _rate([s for s in all_hist if s.get("family") == "SOW"]),
    }

    return {
        "strategy": STRATEGY_NAME,
        "youtube": YOUTUBE_URL,
        "results": results,
        "entries": entries,
        "entry_count": len(entries),
        "scanned": len(results),
        "aggregate_next_candle_stats": aggregate_stats,
        "config": {
            "timeframe": cfg.timeframe,
            "lookback_bars": cfg.lookback_bars,
            "vol_ma_period": cfg.vol_ma_period,
            "rr_ratio": cfg.rr_ratio,
            "low_spread_factor": cfg.low_spread_factor,
        },
        "disclaimer": "Research / education only — not financial advice.",
    }


VOLUME_SPREAD_NEXT_CANDLE_AI_SYSTEM = pro_trade_ai_system(
    "Volume Spread - Next Candle",
    "Volume Spread Analysis (VSA) — classifies the most recent candle's spread/volume/close-position "
    "into a named signature (e.g. No Demand, No Supply, Stopping Volume, Sign of Weakness/Strength) and "
    "projects what that signature typically implies for the *next* candle, not just the current one.",
)


def build_volume_spread_next_candle_ai_prompt(result: dict[str, Any]) -> str:
    extra: list[str] = []
    if result.get("active_setup"):
        extra.append(f"Active VSA setup: {result.get('active_setup')}")
    reasons = result.get("reasons")
    if isinstance(reasons, list) and reasons:
        extra += ["Reasons:"] + [f"  - {r}" for r in reasons if r]
    next_candle = result.get("next_candle_stats")
    if isinstance(next_candle, dict) and next_candle:
        extra.append(f"Historical next-candle stats for this setup: {next_candle}")
    return build_pro_trade_ai_context(result, engine_label="Volume Spread - Next Candle", extra_lines=extra or None)
