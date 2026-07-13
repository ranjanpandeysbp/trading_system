"""
topdown_mtf_engine.py
---------------------
TOPDOWN - MTF: Top Down Analysis with Liquidity and Order Blocks (SMC).

HTF  — directional bias (e.g. Daily)
ATF  — structure, liquidity sweeps, supply/demand, order blocks (e.g. 4H / 1H)
LTF  — MSS + entry on LTF order block when price taps HTF/ATF OB (e.g. 15m / 5m)

Video: https://www.youtube.com/watch?v=RvVs6n46X10

Note: this is a DIFFERENT strategy from app/market_pulse/top_down_mtf_engine.py (no
underscore between "top" and "down") — that module implements a separate HTF/MTF/LTF
CHoCH + FVG/OB pipeline. This engine reuses only its low-level structure primitives
(Bias, identify_trend, mark_key_levels, is_price_in_zone, calculate_sl_tp) and layers
its own liquidity-sweep + order-block confirmation pipeline on top.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.mtf_scanner_engine import TIMEFRAMES, normalize_ohlcv
from app.market_pulse.run_summary import holding_period_for_timeframe
from app.market_pulse.top_down_mtf_engine import (
    Bias,
    calculate_sl_tp,
    identify_trend,
    is_price_in_zone,
    mark_key_levels,
)

YOUTUBE_TOPDOWN_MTF_URL = "https://www.youtube.com/watch?v=RvVs6n46X10"

TF_OPTIONS = ["5m", "15m", "30m", "1h", "4h", "1d", "1w"]

PHASE_ENTRY = "ENTRY_READY"
PHASE_IN_ZONE = "IN_OB_ZONE"
PHASE_ATF_SETUP = "ATF_SETUP"
PHASE_HTF_BIAS = "HTF_BIAS"
PHASE_NEUTRAL = "NEUTRAL"
PHASE_NO_DATA = "NO_DATA"

PHASE_PRIORITY = {
    PHASE_ENTRY: 100,
    PHASE_IN_ZONE: 82,
    PHASE_ATF_SETUP: 68,
    PHASE_HTF_BIAS: 42,
    PHASE_NEUTRAL: 15,
    PHASE_NO_DATA: 0,
}


def _hold_for_tf(tf: str, style: str = "swing") -> str:
    return holding_period_for_timeframe(tf, style)


def _enrich_smc_live(live: dict | None, *, hold_duration: str = "") -> dict:
    """Fold trade-plan hold/SL/TP fields up onto the top-level live dict (no streamlit dep)."""
    if not live:
        return {}
    out = dict(live)
    plan = out.get("trade_plan") or {}
    hold = hold_duration or out.get("hold_duration") or plan.get("holding_period") or "—"
    out["hold_duration"] = hold
    out["confidence_pct"] = out.get("confidence_pct", plan.get("confidence_pct"))
    out["sl_pct"] = out.get("sl_pct", plan.get("stop_loss_pct"))
    out["tp_pct"] = out.get("tp_pct", plan.get("take_profit_pct"))
    if out.get("trade_plan"):
        out["trade_plan"] = {**plan, "holding_period": hold}
    return out


@dataclass
class OrderBlockZone:
    high: float
    low: float
    direction: Bias
    bar_index: int
    timeframe: str
    source: str = "BOS_OB"


@dataclass
class LiquiditySweep:
    direction: Bias
    level: float
    sweep_extreme: float
    bar_index: int


@dataclass
class TopdownMtfConfig:
    htf_tf: str = "1d"
    atf_tf: str = "1h"
    ltf_tf: str = "15m"
    swing_left: int = 3
    swing_right: int = 3
    ob_lookback: int = 12
    rr_ratio: float = 2.0
    take_confidence_threshold: float = 85.0
    min_bars: int = 80
    lookback_bars: int = 400


def fetch_tf_data(
    ticker: str,
    tf: str,
    market: str,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
    limit: int = 400,
) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    df = fetch_data_for_gap_scan(ticker, tf, market, groww_token, exchange, limit=limit)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < 30:
        df = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, tf, is_crypto=is_crypto, limit=limit, market=market),
        )
    return df.tail(limit)


def identify_swings(df: pd.DataFrame, left_bars: int = 3, right_bars: int = 3) -> pd.DataFrame:
    """Fractal swing highs/lows for market structure mapping."""
    work = df.copy()
    work["swing_high"] = False
    work["swing_low"] = False
    n = len(work)
    if n < left_bars + right_bars + 1:
        return work

    highs = work["high"].values
    lows = work["low"].values
    for i in range(left_bars, n - right_bars):
        if all(highs[i] > highs[i - left_bars:i]) and all(highs[i] > highs[i + 1: i + right_bars + 1]):
            work.iloc[i, work.columns.get_loc("swing_high")] = True
        if all(lows[i] < lows[i - left_bars:i]) and all(lows[i] < lows[i + 1: i + right_bars + 1]):
            work.iloc[i, work.columns.get_loc("swing_low")] = True
    return work


def _last_swing_high_before(df: pd.DataFrame, idx: int) -> float | None:
    sub = df.iloc[: idx + 1]
    sh = sub[sub["swing_high"]]
    return float(sh["high"].iloc[-1]) if not sh.empty else None


def _last_swing_low_before(df: pd.DataFrame, idx: int) -> float | None:
    sub = df.iloc[: idx + 1]
    sl = sub[sub["swing_low"]]
    return float(sl["low"].iloc[-1]) if not sl.empty else None


def find_order_blocks_bos(
    df: pd.DataFrame,
    bias: Bias,
    *,
    tf_label: str = "ATF",
    lookback: int = 12,
) -> OrderBlockZone | None:
    """
    Bullish OB: last bearish candle before BOS above recent swing high.
    Bearish OB: last bullish candle before BOS below recent swing low.
    """
    if len(df) < lookback + 5:
        return None

    work = identify_swings(df)
    opens = work["open"].values
    closes = work["close"].values
    highs = work["high"].values
    lows = work["low"].values

    for i in range(len(work) - 1, max(0, len(work) - lookback - 1), -1):
        if bias == Bias.BULLISH:
            swing_hi = _last_swing_high_before(work, i - 1)
            if swing_hi is None:
                continue
            if closes[i] > swing_hi:
                for j in range(i - 1, max(-1, i - 10), -1):
                    if closes[j] < opens[j]:
                        return OrderBlockZone(
                            high=float(highs[j]),
                            low=float(lows[j]),
                            direction=Bias.BULLISH,
                            bar_index=j,
                            timeframe=tf_label,
                        )
        elif bias == Bias.BEARISH:
            swing_lo = _last_swing_low_before(work, i - 1)
            if swing_lo is None:
                continue
            if closes[i] < swing_lo:
                for j in range(i - 1, max(-1, i - 10), -1):
                    if closes[j] > opens[j]:
                        return OrderBlockZone(
                            high=float(highs[j]),
                            low=float(lows[j]),
                            direction=Bias.BEARISH,
                            bar_index=j,
                            timeframe=tf_label,
                        )
    return None


def detect_liquidity_sweep(df: pd.DataFrame, bias: Bias, lookback: int = 30) -> LiquiditySweep | None:
    """Wick beyond swing pool then close back inside — liquidity grab."""
    work = identify_swings(df)
    tail = work.tail(lookback)
    if tail.empty:
        return None

    for i in range(len(tail) - 1, 0, -1):
        row = tail.iloc[i]
        prev = tail.iloc[:i]
        if bias == Bias.BULLISH:
            ssl = prev[prev["swing_low"]]
            if ssl.empty:
                continue
            level = float(ssl["low"].iloc[-1])
            if row["low"] < level and row["close"] > level:
                return LiquiditySweep(
                    direction=Bias.BULLISH,
                    level=level,
                    sweep_extreme=float(row["low"]),
                    bar_index=i,
                )
        elif bias == Bias.BEARISH:
            bsl = prev[prev["swing_high"]]
            if bsl.empty:
                continue
            level = float(bsl["high"].iloc[-1])
            if row["high"] > level and row["close"] < level:
                return LiquiditySweep(
                    direction=Bias.BEARISH,
                    level=level,
                    sweep_extreme=float(row["high"]),
                    bar_index=i,
                )
    return None


def detect_mss(df: pd.DataFrame, bias: Bias, window: int = 5) -> bool:
    """Market Structure Shift — micro BOS on LTF in bias direction."""
    if len(df) < window + 2:
        return False
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    if bias == Bias.BULLISH:
        return closes[-1] > max(highs[-window - 1:-1])
    if bias == Bias.BEARISH:
        return closes[-1] < min(lows[-window - 1:-1])
    return False


def _zone_dict(zone: OrderBlockZone | None) -> dict | None:
    if zone is None:
        return None
    return {
        "type": "Order Block",
        "high": round(zone.high, 4),
        "low": round(zone.low, 4),
        "direction": zone.direction.value,
        "timeframe": zone.timeframe,
        "source": zone.source,
    }


def _compute_confidence(
    *,
    trend: Bias,
    atf_ob: OrderBlockZone | None,
    sweep: LiquiditySweep | None,
    in_zone: bool,
    mss: bool,
    ltf_ob: OrderBlockZone | None,
) -> float:
    score = 0.0
    if trend != Bias.NEUTRAL:
        score += 15
    if atf_ob is not None:
        score += 22
    if sweep is not None:
        score += 18
    if in_zone:
        score += 15
    if mss:
        score += 20
    if ltf_ob is not None:
        score += 10
    return round(min(100.0, score), 1)


def _determine_phase(
    bias: Bias,
    atf_ob: OrderBlockZone | None,
    in_zone: bool,
    mss: bool,
    ltf_ob: OrderBlockZone | None,
) -> tuple[str, str]:
    if bias == Bias.NEUTRAL:
        return PHASE_NEUTRAL, "No clear HTF trend — wait for HH/HL or LH/LL structure"
    if atf_ob is None:
        return PHASE_HTF_BIAS, f"HTF {bias.value} — map ATF structure & order blocks"
    if not in_zone:
        return PHASE_ATF_SETUP, "ATF OB + liquidity mapped — wait for price to tap the zone"
    if not mss:
        return PHASE_IN_ZONE, "Price in HTF/ATF OB zone — wait for LTF Market Structure Shift (MSS)"
    if ltf_ob is None:
        return PHASE_IN_ZONE, "MSS confirmed — wait for LTF order block retest entry"
    return PHASE_ENTRY, "HTF bias + ATF OB tap + LTF MSS + LTF OB — entry ready"


class TopdownMtfStrategy:
    """HTF bias → ATF OB/liquidity → LTF MSS + OB entry."""

    def __init__(
        self,
        htf_df: pd.DataFrame,
        atf_df: pd.DataFrame,
        ltf_df: pd.DataFrame,
        *,
        cfg: TopdownMtfConfig,
        is_crypto: bool = False,
    ):
        self.htf_df = htf_df
        self.atf_df = atf_df
        self.ltf_df = ltf_df
        self.cfg = cfg
        self.is_crypto = is_crypto

    def run(self) -> dict[str, Any]:
        if self.htf_df.empty or self.atf_df.empty or self.ltf_df.empty:
            return {"error": "Insufficient OHLCV on one or more timeframes.", "phase": PHASE_NO_DATA}

        trend = identify_trend(self.htf_df)
        key_levels = mark_key_levels(self.htf_df, is_crypto=self.is_crypto)
        htf_price = float(self.htf_df["close"].iloc[-1])
        bias = trend if trend != Bias.NEUTRAL else Bias.NEUTRAL

        atf_label = TIMEFRAMES.get(self.cfg.atf_tf, {}).get("label", self.cfg.atf_tf)
        ltf_label = TIMEFRAMES.get(self.cfg.ltf_tf, {}).get("label", self.cfg.ltf_tf)

        atf_ob = find_order_blocks_bos(
            self.atf_df, bias, tf_label=atf_label, lookback=self.cfg.ob_lookback,
        ) if bias != Bias.NEUTRAL else None
        sweep = detect_liquidity_sweep(self.atf_df, bias) if bias != Bias.NEUTRAL else None

        ltf_price = float(self.ltf_df["close"].iloc[-1])
        in_zone = False
        zone_distance_pct = 999.0
        if atf_ob is not None:
            in_zone = is_price_in_zone(ltf_price, atf_ob.high, atf_ob.low)
            if ltf_price > atf_ob.high:
                zone_distance_pct = (ltf_price - atf_ob.high) / ltf_price * 100
            elif ltf_price < atf_ob.low:
                zone_distance_pct = (atf_ob.low - ltf_price) / ltf_price * 100
            else:
                zone_distance_pct = 0.0

        mss = detect_mss(self.ltf_df, bias) if in_zone and bias != Bias.NEUTRAL else False
        ltf_ob = (
            find_order_blocks_bos(self.ltf_df, bias, tf_label=ltf_label, lookback=8)
            if mss and bias != Bias.NEUTRAL else None
        )

        confidence = _compute_confidence(
            trend=bias,
            atf_ob=atf_ob,
            sweep=sweep,
            in_zone=in_zone,
            mss=mss,
            ltf_ob=ltf_ob,
        )
        phase, primary_label = _determine_phase(bias, atf_ob, in_zone, mss, ltf_ob)

        trade_plan: dict | None = None
        actionable = phase == PHASE_ENTRY and confidence >= self.cfg.take_confidence_threshold

        if bias != Bias.NEUTRAL and atf_ob is not None and (in_zone or actionable):
            entry_zone = ltf_ob or atf_ob
            entry = ltf_price
            if bias == Bias.BULLISH:
                targets = [kl.price for kl in key_levels if kl.price > entry]
                htf_target = min(targets) if targets else entry * (1 + 0.01 * self.cfg.rr_ratio)
            else:
                targets = [kl.price for kl in key_levels if kl.price < entry]
                htf_target = max(targets) if targets else entry * (1 - 0.01 * self.cfg.rr_ratio)

            sl, tp = calculate_sl_tp(bias, entry, entry_zone.high, entry_zone.low, htf_target)
            risk_pct = abs(entry - sl) / entry * 100 if entry else 0
            reward_pct = abs(tp - entry) / entry * 100 if entry else 0
            trade_plan = {
                "direction": "LONG" if bias == Bias.BULLISH else "SHORT",
                "entry": round(entry, 4),
                "stop_loss": sl,
                "take_profit": tp,
                "sl_pct": round(risk_pct, 2),
                "tp_pct": round(reward_pct, 2),
                "rr_ratio": round(reward_pct / risk_pct, 2) if risk_pct > 0 else self.cfg.rr_ratio,
                "hold_duration": _hold_for_tf(self.cfg.ltf_tf),
            }

        return {
            "htf_tf": self.cfg.htf_tf,
            "atf_tf": self.cfg.atf_tf,
            "ltf_tf": self.cfg.ltf_tf,
            "htf_label": TIMEFRAMES.get(self.cfg.htf_tf, {}).get("label", self.cfg.htf_tf),
            "atf_label": atf_label,
            "ltf_label": ltf_label,
            "price": htf_price,
            "ltf_price": ltf_price,
            "step_htf": {
                "trend": trend.value,
                "bias": bias.value,
                "key_levels": [{"label": kl.label, "price": round(kl.price, 4)} for kl in key_levels[:10]],
            },
            "step_atf": {
                "order_block": _zone_dict(atf_ob),
                "liquidity_sweep": {
                    "direction": sweep.direction.value,
                    "level": round(sweep.level, 4),
                    "extreme": round(sweep.sweep_extreme, 4),
                } if sweep else None,
                "zone_distance_pct": round(zone_distance_pct, 3),
            },
            "step_ltf": {
                "in_zone": in_zone,
                "mss": mss,
                "order_block": _zone_dict(ltf_ob),
            },
            "phase": phase,
            "primary_label": primary_label,
            "priority": PHASE_PRIORITY.get(phase, 0),
            "confidence": confidence,
            "actionable": actionable,
            "trade_plan": trade_plan,
        }


def evaluate_live_signal(result: dict[str, Any], cfg: TopdownMtfConfig) -> dict[str, Any]:
    phase = result.get("phase", PHASE_NO_DATA)
    confidence = float(result.get("confidence") or 0)
    plan = result.get("trade_plan") or {}
    bias = (result.get("step_htf") or {}).get("bias", "NEUTRAL")
    take = bool(result.get("actionable")) and plan.get("direction") in ("LONG", "SHORT")

    if take:
        verdict = f"TAKE {plan['direction']}"
    elif phase == PHASE_IN_ZONE:
        verdict = "WATCH — in OB zone, await MSS"
    elif phase == PHASE_ATF_SETUP:
        verdict = "WATCH — ATF OB mapped"
    elif phase == PHASE_HTF_BIAS:
        verdict = f"WATCH — HTF {bias} bias"
    else:
        verdict = "WAIT"

    live = {
        "phase": phase,
        "verdict": verdict,
        "primary_label": result.get("primary_label", ""),
        "confidence_pct": confidence,
        "take_trade": take,
        "direction": plan.get("direction", "—"),
        "trade_plan": plan,
        "htf_tf": result.get("htf_tf"),
        "atf_tf": result.get("atf_tf"),
        "ltf_tf": result.get("ltf_tf"),
        "atf_ob": (result.get("step_atf") or {}).get("order_block"),
        "ltf_mss": (result.get("step_ltf") or {}).get("mss"),
    }
    return _enrich_smc_live(live, hold_duration=_hold_for_tf(cfg.ltf_tf))


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: TopdownMtfConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or TopdownMtfConfig()
    is_crypto = "CoinDCX" in market

    htf = fetch_tf_data(ticker, cfg.htf_tf, market, groww_token=groww_token, exchange=exchange, limit=cfg.lookback_bars)
    atf = fetch_tf_data(ticker, cfg.atf_tf, market, groww_token=groww_token, exchange=exchange, limit=cfg.lookback_bars)
    ltf = fetch_tf_data(ticker, cfg.ltf_tf, market, groww_token=groww_token, exchange=exchange, limit=cfg.lookback_bars)

    if len(htf) < cfg.min_bars or len(atf) < cfg.min_bars or len(ltf) < 30:
        return {
            "ticker": ticker,
            "error": (
                f"Insufficient data (HTF {len(htf)}, ATF {len(atf)}, LTF {len(ltf)} bars; "
                f"need {cfg.min_bars}+ on HTF/ATF)."
            ),
        }

    result = TopdownMtfStrategy(htf, atf, ltf, cfg=cfg, is_crypto=is_crypto).run()
    if result.get("error"):
        return {"ticker": ticker, "error": result["error"]}

    live = evaluate_live_signal(result, cfg)
    return {
        "ticker": ticker,
        "market": market,
        "htf_tf": cfg.htf_tf,
        "atf_tf": cfg.atf_tf,
        "ltf_tf": cfg.ltf_tf,
        "last_close": result.get("ltf_price"),
        "live": live,
        **result,
    }


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: TopdownMtfConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or TopdownMtfConfig()
    results = []
    for ticker in tickers:
        try:
            results.append(analyze_ticker(ticker, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            results.append({"ticker": ticker, "error": str(exc)[:200]})

    entries = [r for r in results if not r.get("error") and (r.get("live") or {}).get("take_trade")]
    watches = [
        r for r in results
        if not r.get("error")
        and not (r.get("live") or {}).get("take_trade")
        and (r.get("live") or {}).get("phase") in (PHASE_IN_ZONE, PHASE_ATF_SETUP, PHASE_HTF_BIAS)
    ]
    return {
        "results": results,
        "entries": entries,
        "watchlist": watches,
        "entry_count": len(entries),
        "watch_count": len(watches),
        "htf_tf": cfg.htf_tf,
        "atf_tf": cfg.atf_tf,
        "ltf_tf": cfg.ltf_tf,
    }
