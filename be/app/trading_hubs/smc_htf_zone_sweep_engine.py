"""
smc_htf_zone_sweep_engine.py
---------------------------------
Smart Money — HTF Zone + LTF Liquidity Sweep: a multi-timeframe SMC strategy
that trades with institutional flow rather than against it
(https://www.youtube.com/watch?v=4hX3o8V6G8g).

1. HTF direction (1h/4h) — a clear trend via consecutive structural swings
   (reusing `identify_trend`'s HH/HL vs LH/LL read, the same mechanism a
   sequence of Breaks of Structure encodes); the bias holds until the trend
   itself flips.
2. HTF institutional zone — the nearest fresh Fair Value Gap (preferred) or
   Order Block aligned with that bias (reusing `find_fvg`/`find_order_block`,
   which scan backward for the nearest matching zone — inherently the
   "freshest" one relative to current price).
3. Wait for the pullback — do nothing until price actually retraces into
   that HTF zone.
4. LTF confirmation (15m/5m) — once price is inside the zone, require a
   liquidity grab: a wick through the most recent LTF swing low (longs) or
   swing high (shorts) that closes back on the favorable side, trapping the
   early breakout/breakdown traders. This reuses the same swing/wick-ratio
   primitives `smc_liquidity_engine.py` uses for its own sweep detection.
5. Entry on the grab. Stop beyond the sweep extreme. Target the next major
   HTF structural level (day/prior-day high-low, round numbers — reusing
   `mark_key_levels`), falling back to a fixed risk:reward if no level gives
   an adequate one.

Long or short, symmetric. Confidence is a heuristic confluence score, not a
statistical win probability. Research / education only — NOT FINANCIAL ADVICE.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.smart_money_shared import enrich_smc_live, hold_for_tf
from app.trading_hubs.smc_liquidity_engine import _identify_swings, _wick_ratio
from app.trading_hubs.top_down_mtf_engine import (
    Bias,
    FairValueGap,
    _distance_to_zone_pct,
    determine_bias,
    fetch_td_data,
    find_fvg,
    find_order_block,
    identify_trend,
    is_price_in_zone,
    mark_key_levels,
)

logger = logging.getLogger(__name__)

YOUTUBE_URL = "https://www.youtube.com/watch?v=4hX3o8V6G8g"

HTF_OPTIONS = ["1h", "4h"]
LTF_OPTIONS = ["5m", "15m"]


@dataclass
class SMCZoneSweepConfig:
    htf_tf: str = "1h"
    ltf_tf: str = "15m"
    ltf_swing_window: int = 5
    zone_buffer_pct: float = 0.0015
    recent_bars: int = 3          # LTF liquidity-grab freshness window
    wick_ratio_grab: float = 0.5
    rr_ratio: float = 2.0
    sl_buffer_pct: float = 0.15   # % beyond the sweep extreme
    take_confidence_threshold: float = 60.0
    htf_bars: int = 300
    ltf_bars: int = 400
    min_htf_bars: int = 60
    min_ltf_bars: int = 60


def _detect_ltf_liquidity_grab(ltf_df: pd.DataFrame, bias: Bias, cfg: SMCZoneSweepConfig) -> dict[str, Any] | None:
    """A wick through the most recent swing low/high that closes back on the
    favorable side, within the last `recent_bars` — the video's "liquidity
    grab trapping early traders." Same math as smc_liquidity_engine's own
    sweep detection, scoped to one bias direction and a freshness window."""
    work = _identify_swings(ltf_df.copy(), cfg.ltf_swing_window)
    work["bsl_level"] = work["high"].where(work["is_swing_high"]).ffill().shift(1)
    work["ssl_level"] = work["low"].where(work["is_swing_low"]).ffill().shift(1)

    last_idx = len(work) - 1
    earliest = max(last_idx - cfg.recent_bars + 1, 1)
    for pos in range(last_idx, earliest - 1, -1):
        row = work.iloc[pos]
        if bias == Bias.BULLISH:
            ssl = work["ssl_level"].iloc[pos]
            if pd.notna(ssl) and float(row["low"]) < float(ssl) and float(row["close"]) > float(ssl):
                return {
                    "direction": "LONG", "sweep_extreme": float(row["low"]), "level": float(ssl),
                    "bar_index": pos, "bars_ago": last_idx - pos, "wick_ratio": _wick_ratio(row),
                }
        elif bias == Bias.BEARISH:
            bsl = work["bsl_level"].iloc[pos]
            if pd.notna(bsl) and float(row["high"]) > float(bsl) and float(row["close"]) < float(bsl):
                return {
                    "direction": "SHORT", "sweep_extreme": float(row["high"]), "level": float(bsl),
                    "bar_index": pos, "bars_ago": last_idx - pos, "wick_ratio": _wick_ratio(row),
                }
    return None


def evaluate_ticker(
    htf_df: pd.DataFrame, ltf_df: pd.DataFrame, cfg: SMCZoneSweepConfig, *, is_crypto: bool = False,
) -> dict[str, Any]:
    reasons: list[str] = []

    trend = identify_trend(htf_df)
    if trend == Bias.NEUTRAL:
        return {
            "signal": "NONE", "direction": "WAIT", "take_trade": False,
            "verdict": "WAIT — no clear HTF trend", "confidence_pct": 20.0,
            "reasons": ["No clean sequence of higher-highs/higher-lows (or lower-highs/lower-lows) on the HTF yet."],
        }

    key_levels = mark_key_levels(htf_df, is_crypto=is_crypto)
    htf_price = float(htf_df["close"].iloc[-1])
    bias = determine_bias(trend, htf_price, key_levels)
    reasons.append(f"HTF structure: {trend.value} trend, bias {bias.value}.")
    if bias == Bias.NEUTRAL:
        return {
            "signal": "NONE", "direction": "WAIT", "take_trade": False,
            "verdict": "WAIT — HTF bias neutral", "confidence_pct": 25.0, "reasons": reasons,
        }

    fvg = find_fvg(htf_df, bias, cfg.htf_tf)
    ob = find_order_block(htf_df, bias, cfg.htf_tf)
    zone = fvg or ob
    if zone is None:
        return {
            "signal": "NONE", "direction": "WAIT", "take_trade": False,
            "verdict": f"WAIT — no fresh HTF zone ({bias.value})", "confidence_pct": 30.0,
            "reasons": reasons + ["No fresh Fair Value Gap or Order Block aligned with the HTF bias yet."],
        }
    zone_kind = "Fair Value Gap" if isinstance(zone, FairValueGap) else "Order Block"
    reasons.append(f"HTF institutional zone: {zone_kind} {zone.low:,.4g}-{zone.high:,.4g}.")

    ltf_price = float(ltf_df["close"].iloc[-1])
    in_zone = is_price_in_zone(ltf_price, zone.high, zone.low, buffer_pct=cfg.zone_buffer_pct)
    zone_distance_pct = _distance_to_zone_pct(ltf_price, zone.high, zone.low)

    if not in_zone:
        return {
            "signal": "NONE", "direction": "WAIT", "take_trade": False,
            "verdict": f"WAIT — awaiting pullback into the zone ({zone_distance_pct:.2f}% away)",
            "confidence_pct": 35.0,
            "reasons": reasons + [f"Price is {zone_distance_pct:.2f}% away from the HTF zone — waiting for the retrace, not chasing."],
        }
    reasons.append("Price has retraced directly into the HTF zone.")

    grab = _detect_ltf_liquidity_grab(ltf_df, bias, cfg)
    if grab is None:
        return {
            "signal": "NONE", "direction": "WAIT", "take_trade": False,
            "verdict": f"WATCH {bias.value} — in zone, awaiting LTF liquidity grab", "confidence_pct": 45.0,
            "reasons": reasons + ["In the HTF zone now — waiting for the LTF liquidity grab (stop-hunt wick) before entering."],
        }

    reasons.append(
        f"LTF liquidity grab {grab['bars_ago']} bar(s) ago — wick through "
        f"{'the recent swing low' if bias == Bias.BULLISH else 'the recent swing high'} "
        f"({grab['level']:,.4g}), closed back inside (trapping the early move)."
    )

    entry = ltf_price
    if bias == Bias.BULLISH:
        stop = grab["sweep_extreme"] * (1 - cfg.sl_buffer_pct / 100)
        targets = [kl.price for kl in key_levels if kl.price > entry]
        target = min(targets) if targets else None
    else:
        stop = grab["sweep_extreme"] * (1 + cfg.sl_buffer_pct / 100)
        targets = [kl.price for kl in key_levels if kl.price < entry]
        target = max(targets) if targets else None

    risk = max(abs(entry - stop), entry * 0.002)
    reward = abs(target - entry) if target is not None else 0.0
    if target is None or risk <= 0 or reward / risk < cfg.rr_ratio:
        target = entry + risk * cfg.rr_ratio if bias == Bias.BULLISH else entry - risk * cfg.rr_ratio
        reasons.append(f"No HTF structural level gave a full 1:{cfg.rr_ratio:.1f} — using the fixed R:R target instead.")
    else:
        reasons.append(f"Target set at the next major HTF structural level ({target:,.4g}).")

    confidence = 55.0
    confidence += 10 if zone_kind == "Fair Value Gap" else 5
    confidence += 15 if grab["wick_ratio"] >= cfg.wick_ratio_grab else 5
    confidence += 8 if grab["bars_ago"] == 0 else 0
    take = confidence >= cfg.take_confidence_threshold

    sl_pct = round(abs(entry - stop) / entry * 100, 2) if entry else 1.0
    tp_pct = round(abs(target - entry) / entry * 100, 2) if entry else sl_pct * cfg.rr_ratio
    direction = "LONG" if bias == Bias.BULLISH else "SHORT"
    hold = hold_for_tf(cfg.ltf_tf, "intraday" if cfg.ltf_tf in ("5m", "15m") else "swing")

    plan = make_trade_plan(
        direction=direction if take else "—", timeframe=cfg.ltf_tf,
        stop_loss_pct=sl_pct, take_profit_pct=tp_pct, confidence_pct=confidence,
        style="intraday" if cfg.ltf_tf in ("5m", "15m") else "swing",
        exit_rule="Exit if the LTF closes back through the sweep extreme against the trade.",
        max_hold_exit=f"Time stop: {hold.split('(')[0].strip()}.",
    )

    return enrich_smc_live({
        "signal": direction if take else "NONE", "direction": direction, "take_trade": take,
        "verdict": f"TAKE {direction} — HTF zone + LTF liquidity grab" if take else f"WATCH {direction} — grab found, confidence below threshold",
        "confidence_pct": round(confidence, 1), "sl_pct": sl_pct, "tp_pct": tp_pct,
        "entry_price": round(entry, 6), "stop_price": round(stop, 6), "target_price": round(target, 6),
        "zone_type": zone_kind, "zone_high": round(zone.high, 6), "zone_low": round(zone.low, 6),
        "reasons": reasons, "trade_plan": {**plan, "holding_period": hold},
    }, hold_duration=hold)


def analyze_ticker(
    ticker: str, market: str, *, cfg: SMCZoneSweepConfig | None = None,
    groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or SMCZoneSweepConfig()
    is_crypto = "CoinDCX" in market

    htf_df = fetch_td_data(ticker, cfg.htf_tf, market, groww_token, exchange, limit=cfg.htf_bars)
    ltf_df = fetch_td_data(ticker, cfg.ltf_tf, market, groww_token, exchange, limit=cfg.ltf_bars)

    if htf_df.empty or len(htf_df) < cfg.min_htf_bars:
        return {"ticker": ticker, "market": market, "error": f"Insufficient {cfg.htf_tf} data ({len(htf_df)} bars)."}
    if ltf_df.empty or len(ltf_df) < cfg.min_ltf_bars:
        return {"ticker": ticker, "market": market, "error": f"Insufficient {cfg.ltf_tf} data ({len(ltf_df)} bars)."}

    live = evaluate_ticker(htf_df, ltf_df, cfg, is_crypto=is_crypto)
    return {
        "ticker": ticker, "market": market, "htf_tf": cfg.htf_tf, "ltf_tf": cfg.ltf_tf,
        "bars": len(ltf_df), "last_close": float(ltf_df["close"].iloc[-1]), "live": live,
    }


def scan_universe(
    tickers: list[str], market: str, *, cfg: SMCZoneSweepConfig | None = None,
    groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or SMCZoneSweepConfig()
    results = []
    for ticker in tickers:
        try:
            results.append(analyze_ticker(ticker, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            logger.debug("SMC HTF Zone + Sweep failed for %s: %s", ticker, exc)
            results.append({"ticker": ticker, "market": market, "error": str(exc)[:200]})

    entries = [r for r in results if not r.get("error") and (r.get("live") or {}).get("take_trade")]
    watches = [
        r for r in results
        if not r.get("error") and not (r.get("live") or {}).get("take_trade")
        and str((r.get("live") or {}).get("verdict", "")).startswith("WATCH")
    ]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))
    watches.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market, "htf_tf": cfg.htf_tf, "ltf_tf": cfg.ltf_tf, "results": results,
        "entries": entries, "watchlist": watches,
        "entry_count": len(entries), "watch_count": len(watches),
    }
