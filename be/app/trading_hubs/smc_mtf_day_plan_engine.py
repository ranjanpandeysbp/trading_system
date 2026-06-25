"""
smc_mtf_day_plan_engine.py
--------------------------
Smart Risk — MTF Day Trading Plan (OB · FVG · CHoCH).

HTF trend + supply/demand zone → LTF counter-structure → CHoCH → OB limit entry.
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
from app.trading_hubs.smart_money_shared import enrich_smc_live, hold_for_tf
from app.trading_hubs.top_down_mtf_engine import (
    Bias,
    FairValueGap,
    OrderBlock,
    detect_choch,
    find_fvg,
    find_order_block,
    identify_trend,
    is_price_in_zone,
    mark_key_levels,
)

logger = logging.getLogger(__name__)

YOUTUBE_SMC_MTF_DAY_PLAN_URL = "https://www.youtube.com/watch?v=795tKU5Zxu8"

HTF_OPTIONS = ["4h", "1d"]
MTF_OPTIONS = ["1h", "30m", "15m"]
LTF_OPTIONS = ["15m", "5m", "1m"]

PHASE_ENTRY = "ENTRY_READY"
PHASE_CHOCH = "CHOCH_CONFIRMED"
PHASE_AWAIT = "AWAIT_CHOCH"
PHASE_IN_ZONE = "IN_HTF_ZONE"
PHASE_BIAS = "HTF_BIAS"
PHASE_NONE = "NO_SETUP"


@dataclass
class DayPlanConfig:
    htf_tf: str = "4h"
    mtf_tf: str = "1h"
    ltf_tf: str = "15m"
    rr_ratio: float = 2.0
    take_confidence_threshold: float = 62.0
    sl_buffer_pct: float = 0.1
    min_bars: int = 60


def fetch_tf_data(
    ticker: str,
    tf: str,
    market: str,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
    limit: int = 350,
) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    df = fetch_data_for_gap_scan(ticker, tf, market, groww_token, exchange, limit=limit)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < 30:
        df = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, tf, is_crypto=is_crypto, limit=limit, market=market)
        )
    return df


def identify_fvgs_and_order_blocks(df: pd.DataFrame) -> pd.DataFrame:
    """
    Annotate 3-candle bearish/bullish FVG patterns and origin order blocks.
    Bearish FVG: Low(i-1) > High(i+1) with bearish middle candle.
    """
    work = normalize_ohlcv(df).copy()
    if work.empty:
        return work

    for col in (
        "bearish_fvg", "bullish_fvg",
        "bearish_ob_high", "bearish_ob_low",
        "bullish_ob_high", "bullish_ob_low",
    ):
        work[col] = False if "fvg" in col else np.nan
    for col in ("bearish_fvg", "bullish_fvg"):
        work[col] = work[col].astype(bool)

    for i in range(1, len(work) - 1):
        o, h, l, c = (
            float(work["open"].iloc[i]),
            float(work["high"].iloc[i]),
            float(work["low"].iloc[i]),
            float(work["close"].iloc[i]),
        )
        prev_l = float(work["low"].iloc[i - 1])
        prev_h = float(work["high"].iloc[i - 1])
        next_h = float(work["high"].iloc[i + 1])
        next_l = float(work["low"].iloc[i + 1])

        if prev_l > next_h and c < o:
            work.at[work.index[i], "bearish_fvg"] = True
            work.at[work.index[i], "bearish_ob_high"] = float(work["high"].iloc[i - 1])
            work.at[work.index[i], "bearish_ob_low"] = float(work["low"].iloc[i - 1])

        if prev_h < next_l and c > o:
            work.at[work.index[i], "bullish_fvg"] = True
            work.at[work.index[i], "bullish_ob_high"] = float(work["high"].iloc[i - 1])
            work.at[work.index[i], "bullish_ob_low"] = float(work["low"].iloc[i - 1])

    return work


def _zone_from_htf(df_htf: pd.DataFrame, bias: Bias, tf_label: str) -> FairValueGap | OrderBlock | None:
    fvg = find_fvg(df_htf, bias, tf_label)
    ob = find_order_block(df_htf, bias, tf_label)
    return fvg or ob


def _structural_target(df: pd.DataFrame, direction: str, price: float) -> float:
    levels = mark_key_levels(df)
    if direction == "SHORT":
        below = [kl.price for kl in levels if kl.price < price]
        swing_low = float(df["low"].tail(40).min()) if len(df) >= 5 else price * 0.99
        return max(below) if below else swing_low
    above = [kl.price for kl in levels if kl.price > price]
    swing_high = float(df["high"].tail(40).max()) if len(df) >= 5 else price * 1.01
    return min(above) if above else swing_high


def _counter_trend_demand_ob(mtf_df: pd.DataFrame) -> OrderBlock | None:
    """LTF/MTF demand OB that initiated the counter-trend push (bullish OB)."""
    return find_order_block(mtf_df.tail(50), Bias.BULLISH, "MTF")


def _counter_trend_supply_ob(mtf_df: pd.DataFrame) -> OrderBlock | None:
    return find_order_block(mtf_df.tail(50), Bias.BEARISH, "MTF")


def _choch_below_demand(mtf_df: pd.DataFrame, demand: OrderBlock | None) -> bool:
    if demand is None or mtf_df.empty:
        return False
    return float(mtf_df["close"].iloc[-1]) < demand.low


def _choch_above_supply(mtf_df: pd.DataFrame, supply: OrderBlock | None) -> bool:
    if supply is None or mtf_df.empty:
        return False
    return float(mtf_df["close"].iloc[-1]) > supply.high


def evaluate_day_plan(
    htf_df: pd.DataFrame,
    mtf_df: pd.DataFrame,
    ltf_df: pd.DataFrame,
    cfg: DayPlanConfig,
) -> dict[str, Any]:
    if htf_df.empty or mtf_df.empty:
        return {"signal": "NO_DATA"}

    price = float(ltf_df["close"].iloc[-1]) if not ltf_df.empty else float(mtf_df["close"].iloc[-1])
    trend = identify_trend(htf_df)
    reasons: list[str] = []
    conf = 22.0
    direction = "WAIT"
    phase = PHASE_NONE
    verdict = "WAIT"
    take = False
    entry = stop = target = price
    zone_high = zone_low = None
    ob_zone = None

    if trend == Bias.BEARISH:
        htf_zone = _zone_from_htf(htf_df, Bias.BEARISH, cfg.htf_tf)
        in_htf = htf_zone is not None and is_price_in_zone(price, htf_zone.high, htf_zone.low, 0.002)
        demand_ob = _counter_trend_demand_ob(mtf_df)
        choch = _choch_below_demand(mtf_df, demand_ob)
        breakout_ob = find_order_block(mtf_df.tail(15), Bias.BEARISH, cfg.mtf_tf)

        if htf_zone:
            zone_high, zone_low = htf_zone.high, htf_zone.low
            reasons.append(f"HTF ({cfg.htf_tf}) bearish supply zone identified")
            conf += 15
        if trend == Bias.BEARISH:
            reasons.append("HTF bearish structure — lower highs / lower lows")
            conf += 12

        if in_htf:
            phase = PHASE_IN_ZONE
            verdict = "WATCH SHORT"
            conf += 18
            reasons.append("Price in HTF supply — counter-trend rally into sell zone")
            if demand_ob:
                reasons.append("LTF demand OB located — watch for CHoCH below it")
                conf += 10
                if not choch:
                    phase = PHASE_AWAIT
                    verdict = "WATCH SHORT"
                    reasons.append("Await close below LTF demand OB (CHoCH)")
                else:
                    phase = PHASE_CHOCH
                    conf += 20
                    reasons.append("CHoCH — supply reclaimed control below demand OB")
                    if breakout_ob:
                        phase = PHASE_ENTRY
                        direction = "SHORT"
                        verdict = "TAKE SHORT"
                        entry = breakout_ob.low
                        stop = max(
                            breakout_ob.high,
                            float(mtf_df["high"].tail(8).max()),
                        ) * (1 + cfg.sl_buffer_pct / 100)
                        struct_tp = _structural_target(htf_df, "SHORT", entry)
                        risk = stop - entry
                        rr_tp = entry - cfg.rr_ratio * risk if risk > 0 else entry * 0.98
                        target = min(struct_tp, rr_tp) if struct_tp < entry else rr_tp
                        ob_zone = breakout_ob
                        reasons.append("Sell limit at bearish OB formed at breakout")
                        conf += 15

    elif trend == Bias.BULLISH:
        htf_zone = _zone_from_htf(htf_df, Bias.BULLISH, cfg.htf_tf)
        in_htf = htf_zone is not None and is_price_in_zone(price, htf_zone.high, htf_zone.low, 0.002)
        supply_ob = _counter_trend_supply_ob(mtf_df)
        choch = _choch_above_supply(mtf_df, supply_ob)
        breakout_ob = find_order_block(mtf_df.tail(15), Bias.BULLISH, cfg.mtf_tf)

        if htf_zone:
            zone_high, zone_low = htf_zone.high, htf_zone.low
            reasons.append(f"HTF ({cfg.htf_tf}) bullish demand zone identified")
            conf += 15
        reasons.append("HTF bullish structure — higher highs / higher lows")
        conf += 12

        if in_htf:
            phase = PHASE_IN_ZONE
            verdict = "WATCH LONG"
            conf += 18
            reasons.append("Price in HTF demand — counter-trend dip into buy zone")
            if supply_ob:
                reasons.append("LTF supply OB located — watch for CHoCH above it")
                conf += 10
                if not choch:
                    phase = PHASE_AWAIT
                else:
                    phase = PHASE_CHOCH
                    conf += 20
                    reasons.append("CHoCH — demand reclaimed control above supply OB")
                    if breakout_ob:
                        phase = PHASE_ENTRY
                        direction = "LONG"
                        verdict = "TAKE LONG"
                        entry = breakout_ob.high
                        stop = min(
                            breakout_ob.low,
                            float(mtf_df["low"].tail(8).min()),
                        ) * (1 - cfg.sl_buffer_pct / 100)
                        struct_tp = _structural_target(htf_df, "LONG", entry)
                        risk = entry - stop
                        rr_tp = entry + cfg.rr_ratio * risk if risk > 0 else entry * 1.02
                        target = max(struct_tp, rr_tp) if struct_tp > entry else rr_tp
                        ob_zone = breakout_ob
                        reasons.append("Buy limit at bullish OB formed at breakout")
                        conf += 15
    else:
        reasons.append("HTF trend neutral — wait for clear structure")

    # LTF trigger bonus
    if not ltf_df.empty and direction in ("LONG", "SHORT"):
        ltf_bias = Bias.BULLISH if direction == "LONG" else Bias.BEARISH
        if detect_choch(ltf_df, ltf_bias):
            conf += 8
            reasons.append(f"LTF ({cfg.ltf_tf}) mini-CHoCH confirms trigger")

    conf = max(18.0, min(92.0, conf))
    take = phase == PHASE_ENTRY and conf >= cfg.take_confidence_threshold

    if direction == "LONG" and stop < entry:
        sl_pct = max(0.35, (entry - stop) / price * 100)
        tp_pct = max(0.5, (target - entry) / price * 100)
    elif direction == "SHORT" and stop > entry:
        sl_pct = max(0.35, (stop - entry) / price * 100)
        tp_pct = max(0.5, (entry - target) / price * 100)
    else:
        sl_pct = 1.2
        tp_pct = sl_pct * cfg.rr_ratio

    hold = hold_for_tf(cfg.ltf_tf, "intraday")
    plan_dir = direction if take and direction in ("LONG", "SHORT") else "—"
    plan = make_trade_plan(
        direction=plan_dir,
        timeframe=cfg.ltf_tf,
        stop_loss_pct=round(sl_pct, 2),
        take_profit_pct=round(tp_pct, 2),
        confidence_pct=round(conf, 1),
        style="intraday",
        exit_rule="Exit if CHoCH thesis fails or HTF zone is violated.",
        max_hold_exit=f"Time stop: {hold.split('(')[0].strip()}.",
    )

    return enrich_smc_live({
        "signal": "BUY" if direction == "LONG" and take else ("SELL" if direction == "SHORT" and take else "NONE"),
        "direction": direction,
        "take_trade": take,
        "verdict": verdict,
        "phase": phase,
        "htf_trend": trend.value,
        "confidence_pct": round(conf, 1),
        "sl_pct": round(sl_pct, 2),
        "tp_pct": round(tp_pct, 2),
        "hold_duration": hold,
        "rr_ratio": cfg.rr_ratio,
        "entry_price": round(entry, 6),
        "stop_price": round(stop, 6),
        "target_price": round(target, 6),
        "htf_tf": cfg.htf_tf,
        "mtf_tf": cfg.mtf_tf,
        "ltf_tf": cfg.ltf_tf,
        "zone_high": zone_high,
        "zone_low": zone_low,
        "ob_high": ob_zone.high if ob_zone else None,
        "ob_low": ob_zone.low if ob_zone else None,
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": hold},
    }, hold_duration=hold)


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: DayPlanConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or DayPlanConfig()
    htf = fetch_tf_data(ticker, cfg.htf_tf, market, groww_token=groww_token, exchange=exchange)
    mtf = fetch_tf_data(ticker, cfg.mtf_tf, market, groww_token=groww_token, exchange=exchange)
    ltf = fetch_tf_data(ticker, cfg.ltf_tf, market, groww_token=groww_token, exchange=exchange)

    if len(htf) < cfg.min_bars or len(mtf) < cfg.min_bars:
        return {"ticker": ticker, "error": f"Insufficient HTF/MTF data ({cfg.htf_tf}/{cfg.mtf_tf})."}

    annotated = identify_fvgs_and_order_blocks(mtf)
    fvg_count = int(annotated["bearish_fvg"].sum() + annotated["bullish_fvg"].sum())
    live = evaluate_day_plan(htf, mtf, ltf, cfg)

    return {
        "ticker": ticker,
        "market": market,
        "htf_tf": cfg.htf_tf,
        "mtf_tf": cfg.mtf_tf,
        "ltf_tf": cfg.ltf_tf,
        "fvg_patterns": fvg_count,
        "live": live,
    }


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: DayPlanConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or DayPlanConfig()
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
        and (r.get("live") or {}).get("phase") in (PHASE_IN_ZONE, PHASE_AWAIT, PHASE_CHOCH)
    ]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))
    watches.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market,
        "htf_tf": cfg.htf_tf,
        "mtf_tf": cfg.mtf_tf,
        "ltf_tf": cfg.ltf_tf,
        "results": results,
        "entries": entries,
        "watchlist": watches,
        "entry_count": len(entries),
        "watch_count": len(watches),
    }
