"""
swing_5_strategies_engine.py
--------------------------------
Swing Trading — 5 Strategies: the five highest risk/reward swing setups from
a professional trader's breakdown, made mechanical and scannable across
India / US / Crypto / Commodities.

Source: https://www.youtube.com/shorts/SFCzyK908zI

1. Breakouts          — weeks/months of range contraction, then a demand>supply
                         break of the range; more contraction legs = stronger break.
2. Episodic Pivots     — a huge-volume catalyst gap-up, stronger above major resistance.
   (Gap and Go)
3. Pullbacks           — a low-volume retrace back to the original breakout level
                         after missing the initial move (a safer second entry).
4. Uptrending Bounces  — an established uptrend sells off to support/a moving
                         average, then a bullish, high-volume candle confirms the bounce.
5. Bottom Bounces      — a "falling knife": a sequence of gap-downs on rising
   (falling knife)       volume, culminating in one huge gap-down that closes
                         BULLISH on huge volume (institutional capitulation-buying).

All five are LONG-only continuation/reversal setups (as framed in the source),
reusing this app's existing gap detection (gap_trading.py), S/R breakout
classifier (sr_breakout.py), and the 20/200 SMA bounce engine
(sma_20_200_engine.py) rather than re-deriving them.

No confidence % here is a statistical win probability — it's a heuristic
confluence score, same convention as every other "verdict" engine in this app.
Bottom Bounces in particular is explicitly the highest-risk of the five (a
countertrend "catch the knife" trade) and is scored/labeled accordingly.
Research / education only — NOT FINANCIAL ADVICE.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.market_pulse.gap_trading import calculate_two_level_sr, detect_gaps, fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan
from app.market_pulse.sma_20_200_engine import Sma20200Config, scan_sma_signals
from app.market_pulse.sr_breakout import analyze_sr_breakout
from app.trading_hubs.intraday_shared import enrich_intra_live

logger = logging.getLogger(__name__)

TIMEFRAME_OPTIONS = ["1h", "4h", "1d", "1w"]
DEFAULT_TIMEFRAMES = ["1d"]

BREAKOUT = "breakout"
EPISODIC_PIVOT = "episodic_pivot"
PULLBACK = "pullback"
UPTREND_BOUNCE = "uptrend_bounce"
BOTTOM_BOUNCE = "bottom_bounce"

STRATEGY_KEYS = [BREAKOUT, EPISODIC_PIVOT, PULLBACK, UPTREND_BOUNCE, BOTTOM_BOUNCE]

STRATEGY_LABELS: dict[str, str] = {
    BREAKOUT: "1. Breakouts",
    EPISODIC_PIVOT: "2. Episodic Pivots (Gap and Go)",
    PULLBACK: "3. Pullbacks",
    UPTREND_BOUNCE: "4. Uptrending Bounces",
    BOTTOM_BOUNCE: "5. Bottom Bounces (falling knife)",
}

_MIN_BARS = 230  # covers the 200 SMA warmup used by Uptrending Bounces


@dataclass
class Swing5Config:
    # Shared
    risk_free_lookback: int = 300

    # 1. Breakouts
    breakout_lookback: int = 40
    breakout_contraction_legs: int = 3
    breakout_volume_ratio: float = 1.3
    breakout_rr_ratio: float = 2.5
    breakout_min_confidence: float = 45.0

    # 2. Episodic Pivots
    ep_min_gap_pct: float = 4.0
    ep_min_gap_pct_crypto: float = 3.0
    ep_volume_ratio: float = 2.0
    ep_rr_ratio: float = 2.2

    # 3. Pullbacks
    pullback_lookback: int = 60
    pullback_recency_bars: int = 15
    pullback_breakout_margin_pct: float = 1.5
    pullback_proximity_pct: float = 2.5
    pullback_violation_pct: float = 1.0
    pullback_max_volume_ratio: float = 0.85
    pullback_rr_ratio: float = 2.5

    # 4. Uptrending Bounces
    bounce_fast_sma: int = 20
    bounce_slow_sma: int = 200
    bounce_volume_ratio: float = 1.4
    bounce_rr_ratio: float = 2.0

    # 5. Bottom Bounces
    bb_sequence_bars: int = 8
    bb_min_gap_pct: float = 1.5
    bb_min_sequence_len: int = 3
    bb_volume_ratio: float = 2.5
    bb_rr_ratio: float = 2.5


# ---------------------------------------------------------------------------
# Shared fetch
# ---------------------------------------------------------------------------

def _fetch_ohlcv(
    ticker: str, market: str, timeframe: str, *, groww_token: str = "", exchange: str = "NSE", limit: int = 300,
) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market or "crypto" in market.lower()
    df = fetch_data_for_gap_scan(ticker, timeframe, market, groww_token, exchange, limit=limit)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < _MIN_BARS:
        df = normalize_ohlcv(fetch_ohlcv_yfinance(ticker, timeframe, is_crypto=is_crypto, limit=limit, market=market))
    return df


def _volume_ratio(df: pd.DataFrame, *, at: int = -1, window: int = 20) -> float:
    if len(df) < window + 1:
        return 1.0
    avg = df["volume"].iloc[-(window + 1):-1].mean()
    if avg <= 0:
        return 1.0
    return float(df["volume"].iloc[at]) / float(avg)


def _empty_result(strategy: str, reason: str) -> dict[str, Any]:
    return {"strategy": strategy, "setup_found": False, "direction": "WAIT", "reasons": [reason], "live": {}}


def _finalize(
    *, strategy: str, direction: str, confidence: float, entry: float, stop: float, target: float,
    reasons: list[str], timeframe: str, hold_override: str | None = None, risk_note: str = "",
) -> dict[str, Any]:
    confidence = round(max(5.0, min(92.0, confidence)), 1)
    sl_pct = round(abs(entry - stop) / entry * 100, 2) if entry else 1.0
    tp_pct = round(abs(target - entry) / entry * 100, 2) if entry else sl_pct * 2
    plan = make_trade_plan(
        direction=direction, timeframe=timeframe, stop_loss_pct=sl_pct, take_profit_pct=tp_pct,
        confidence_pct=confidence, style="swing",
    )
    if hold_override:
        plan = {**plan, "holding_period": hold_override}
    live = enrich_intra_live({
        "signal": direction, "direction": direction, "take_trade": True, "verdict": direction,
        "confidence_pct": confidence, "sl_pct": sl_pct, "tp_pct": tp_pct,
        "entry_price": round(entry, 6), "stop_price": round(stop, 6), "target_price": round(target, 6),
        "reasons": reasons + ([risk_note] if risk_note else []),
        "trade_plan": plan,
    }, hold_duration=hold_override or "")
    return {
        "strategy": strategy, "setup_found": True, "direction": direction,
        "confidence_pct": confidence, "reasons": reasons, "risk_note": risk_note, "live": live,
    }


# ---------------------------------------------------------------------------
# 1. Breakouts
# ---------------------------------------------------------------------------

def detect_breakout(df: pd.DataFrame, timeframe: str, cfg: Swing5Config) -> dict[str, Any]:
    lookback = cfg.breakout_lookback
    if len(df) < lookback + 10:
        return _empty_result(BREAKOUT, f"Need {lookback + 10}+ bars, have {len(df)}.")

    sr = analyze_sr_breakout(df, timeframe=timeframe, lookback=lookback)
    if sr.get("event") != "BREAKOUT":
        return _empty_result(
            BREAKOUT,
            f"No fresh breakout — current read is {sr.get('event_label', sr.get('event'))}.",
        )

    # Contraction count: split the pre-breakout window into N legs and count how
    # many consecutive legs (oldest -> newest) show a shrinking high-low range —
    # the video's "several price contractions -> most explosive breakouts" tell.
    window = df.iloc[-(lookback + 3):-3] if len(df) > lookback + 3 else df.iloc[-lookback:]
    legs = cfg.breakout_contraction_legs
    seg_len = max(3, len(window) // legs)
    ranges = []
    for i in range(legs):
        seg = window.iloc[i * seg_len:(i + 1) * seg_len]
        if seg.empty:
            continue
        seg_close = float(seg["close"].iloc[-1]) or 1.0
        ranges.append((float(seg["high"].max()) - float(seg["low"].min())) / seg_close * 100)
    contraction_count = 0
    for i in range(1, len(ranges)):
        if ranges[i] < ranges[i - 1] * 0.95:
            contraction_count += 1
        else:
            break

    vol_ratio = _volume_ratio(df)
    volume_confirmed = vol_ratio >= cfg.breakout_volume_ratio

    confidence = float(sr.get("confidence") or 50)
    confidence += contraction_count * 6
    confidence += 12 if volume_confirmed else -5
    if confidence < cfg.breakout_min_confidence:
        return _empty_result(BREAKOUT, f"Breakout detected but confidence too low ({confidence:.0f}%) to act on.")

    price = float(df["close"].iloc[-1])
    broken_level = sr.get("broken_level") or sr.get("resistance") or price
    entry = price
    stop = min(broken_level, sr.get("support") or broken_level) * 0.99
    risk = max(entry - stop, entry * 0.005)
    target = entry + risk * cfg.breakout_rr_ratio

    reasons = [
        f"Fresh breakout above {broken_level:,.4g} (S/R classifier confidence {sr.get('confidence')}%).",
        f"{contraction_count} consecutive range-contraction leg(s) into the break — "
        + ("more contraction typically means a more explosive move." if contraction_count else "no clean contraction pattern found, treat as a weaker breakout."),
        f"Breakout-bar volume is {vol_ratio:.2f}x its 20-bar average — "
        + ("confirmed by volume." if volume_confirmed else "NOT volume-confirmed, a real risk of a false break."),
    ]
    return _finalize(
        strategy=BREAKOUT, direction="LONG", confidence=confidence, entry=entry, stop=stop, target=target,
        reasons=reasons, timeframe=timeframe,
    )


# ---------------------------------------------------------------------------
# 2. Episodic Pivots (Gap and Go)
# ---------------------------------------------------------------------------

def detect_episodic_pivot(df: pd.DataFrame, timeframe: str, cfg: Swing5Config, *, is_crypto: bool = False) -> dict[str, Any]:
    if len(df) < 25:
        return _empty_result(EPISODIC_PIVOT, "Not enough bars for a gap read.")

    min_gap = cfg.ep_min_gap_pct_crypto if is_crypto else cfg.ep_min_gap_pct
    gapped = detect_gaps(df, min_gap_pct=min_gap)
    last = gapped.iloc[-1]
    if last.get("gap_type") != "gap_up":
        return _empty_result(EPISODIC_PIVOT, f"No qualifying gap-up on the last bar (need >= {min_gap}%).")

    vol_ratio = _volume_ratio(df)
    if vol_ratio < cfg.ep_volume_ratio:
        return _empty_result(
            EPISODIC_PIVOT,
            f"Gapped up {last['gap_pct']:.1f}% but volume is only {vol_ratio:.2f}x average — "
            f"needs >= {cfg.ep_volume_ratio:.1f}x to count as a catalyst-driven Episodic Pivot.",
        )

    sr = calculate_two_level_sr(df.iloc[:-1])
    price = float(last["close"])
    above_major_resistance = bool(sr.get("r1")) and price > sr["r1"]

    confidence = 55.0 + min(25.0, (vol_ratio - cfg.ep_volume_ratio) * 10)
    confidence += 15 if above_major_resistance else 0
    confidence += min(10.0, (last["gap_pct"] - min_gap) * 1.5)

    entry = price
    stop = float(last["low"])
    risk = max(entry - stop, entry * 0.005)
    target = entry + risk * cfg.ep_rr_ratio

    reasons = [
        f"Gapped up {last['gap_pct']:.1f}% on {vol_ratio:.2f}x average volume — a catalyst-sized, volume-confirmed gap.",
        (
            f"Gap closed above major resistance ({sr['r1']:,.4g}) — the stronger EP signature."
            if above_major_resistance else "Gap did not clear a major resistance level — a somewhat weaker EP."
        ),
        "EPs move fast — this is a shorter, more actively-monitored hold than a normal swing position.",
    ]
    return _finalize(
        strategy=EPISODIC_PIVOT, direction="LONG", confidence=confidence, entry=entry, stop=stop, target=target,
        reasons=reasons, timeframe=timeframe,
        hold_override="2–10 trading days (fast-moving — check daily, don't set-and-forget)",
    )


# ---------------------------------------------------------------------------
# 3. Pullbacks
# ---------------------------------------------------------------------------

def detect_pullback(df: pd.DataFrame, timeframe: str, cfg: Swing5Config) -> dict[str, Any]:
    lookback, recency = cfg.pullback_lookback, cfg.pullback_recency_bars
    if len(df) < lookback + recency + 5:
        return _empty_result(PULLBACK, f"Need {lookback + recency + 5}+ bars, have {len(df)}.")

    base = df.iloc[-(lookback + recency + 1):-(recency + 1)]
    recent = df.iloc[-recency:-1]
    if base.empty or recent.empty:
        return _empty_result(PULLBACK, "Not enough bars to establish a prior breakout level.")

    prior_high = float(base["high"].max())
    breakout_confirmed = float(recent["close"].max()) > prior_high * (1 + cfg.pullback_breakout_margin_pct / 100)
    if not breakout_confirmed:
        return _empty_result(PULLBACK, f"No confirmed breakout above {prior_high:,.4g} in the last {recency} bars to pull back to.")

    current = df.iloc[-1]
    price = float(current["close"])
    dist_pct = (price - prior_high) / prior_high * 100
    near_level = abs(dist_pct) <= cfg.pullback_proximity_pct and price >= prior_high * (1 - cfg.pullback_violation_pct / 100)
    if not near_level:
        return _empty_result(
            PULLBACK,
            f"Broke out above {prior_high:,.4g} but price is {dist_pct:+.1f}% away — not currently retesting the level.",
        )

    vol_ratio = _volume_ratio(df)
    low_volume = vol_ratio <= cfg.pullback_max_volume_ratio
    if not low_volume:
        return _empty_result(
            PULLBACK,
            f"Retesting {prior_high:,.4g} but on {vol_ratio:.2f}x volume — the video calls for a LOW-volume "
            f"pullback (<= {cfg.pullback_max_volume_ratio:.2f}x); this one has real selling behind it, riskier.",
        )

    confidence = 55.0 + (12 if vol_ratio <= cfg.pullback_max_volume_ratio * 0.7 else 0)
    confidence += (10 if abs(dist_pct) <= 1.0 else 0)

    entry = price
    stop = prior_high * (1 - cfg.pullback_violation_pct / 100 - 0.005)
    risk = max(entry - stop, entry * 0.005)
    target = entry + risk * cfg.pullback_rr_ratio

    reasons = [
        f"Confirmed breakout above {prior_high:,.4g} within the last {recency} bars, now retesting it ({dist_pct:+.1f}% away).",
        f"Pullback volume is {vol_ratio:.2f}x average — low volume means little real selling pressure, a healthier/safer retest.",
    ]
    return _finalize(
        strategy=PULLBACK, direction="LONG", confidence=confidence, entry=entry, stop=stop, target=target,
        reasons=reasons, timeframe=timeframe,
        hold_override="3–10 trading days (secondary entry — resolves faster once the level holds)",
    )


# ---------------------------------------------------------------------------
# 4. Uptrending Bounces
# ---------------------------------------------------------------------------

def detect_uptrend_bounce(df: pd.DataFrame, timeframe: str, cfg: Swing5Config) -> dict[str, Any]:
    sma_cfg = Sma20200Config(fast_period=cfg.bounce_fast_sma, slow_period=cfg.bounce_slow_sma)
    if len(df) < sma_cfg.slow_period + 10:
        return _empty_result(UPTREND_BOUNCE, f"Need {sma_cfg.slow_period + 10}+ bars for the {sma_cfg.slow_period} SMA, have {len(df)}.")

    work = scan_sma_signals(df, sma_cfg)
    fast_col, slow_col = f"sma_{sma_cfg.fast_period}", f"sma_{sma_cfg.slow_period}"
    last = work.iloc[-1]
    if last.get("signal") != 1:
        return _empty_result(UPTREND_BOUNCE, f"No fresh bounce off the {sma_cfg.fast_period} SMA in an established uptrend right now.")

    bullish_candle = float(last["close"]) > float(last["open"])
    vol_ratio = _volume_ratio(df)
    volume_confirmed = vol_ratio >= cfg.bounce_volume_ratio
    if not (bullish_candle and volume_confirmed):
        missing = []
        if not bullish_candle:
            missing.append("candle closed red, not bullish")
        if not volume_confirmed:
            missing.append(f"volume only {vol_ratio:.2f}x average (need >= {cfg.bounce_volume_ratio:.1f}x)")
        return _empty_result(UPTREND_BOUNCE, f"SMA bounce triggered but unconfirmed — {', '.join(missing)}.")

    confidence = 60.0 + min(20.0, (vol_ratio - cfg.bounce_volume_ratio) * 10)
    price = float(last["close"])
    sma_fast = float(last[fast_col])
    entry = price
    stop = sma_fast * 0.995
    risk = max(entry - stop, entry * 0.005)
    target = entry + risk * cfg.bounce_rr_ratio

    reasons = [
        f"Established uptrend (above {sma_cfg.slow_period} SMA, {sma_cfg.fast_period} SMA rising) sold off to the {sma_cfg.fast_period} SMA and bounced.",
        f"Bounce candle closed bullish on {vol_ratio:.2f}x average volume — confirms real demand at the average, not just a wick.",
    ]
    return _finalize(
        strategy=UPTREND_BOUNCE, direction="LONG", confidence=confidence, entry=entry, stop=stop, target=target,
        reasons=reasons, timeframe=timeframe,
    )


# ---------------------------------------------------------------------------
# 5. Bottom Bounces (falling knife)
# ---------------------------------------------------------------------------

def detect_bottom_bounce(df: pd.DataFrame, timeframe: str, cfg: Swing5Config) -> dict[str, Any]:
    n = cfg.bb_sequence_bars
    if len(df) < n + 25:
        return _empty_result(BOTTOM_BOUNCE, f"Need {n + 25}+ bars, have {len(df)}.")

    gapped = detect_gaps(df, min_gap_pct=cfg.bb_min_gap_pct)
    window = gapped.iloc[-n:]
    last = window.iloc[-1]

    if last.get("gap_type") != "gap_down":
        return _empty_result(BOTTOM_BOUNCE, "Last bar did not gap down — no capitulation candle to evaluate.")
    if not (float(last["close"]) > float(last["open"])):
        return _empty_result(BOTTOM_BOUNCE, "Last bar gapped down but closed red — no bullish reversal yet.")

    gap_down_flags = (window["gap_type"] == "gap_down").tolist()
    streak = 0
    for f in reversed(gap_down_flags):
        if f:
            streak += 1
        else:
            break
    if streak < cfg.bb_min_sequence_len:
        return _empty_result(
            BOTTOM_BOUNCE,
            f"Only {streak} consecutive gap-down bar(s) — need >= {cfg.bb_min_sequence_len} for a falling-knife sequence.",
        )

    volumes = window["volume"].tolist()[-streak:]
    final_has_highest_volume = bool(volumes) and volumes[-1] == max(volumes)
    volume_trending_up = len(volumes) >= 2 and volumes[-1] > volumes[0]
    if not final_has_highest_volume:
        return _empty_result(
            BOTTOM_BOUNCE,
            "Gap-down sequence found, but the final (reversal) bar does NOT carry the sequence's highest "
            "volume — the capitulation-buying signature isn't confirmed.",
        )

    vol_ratio = _volume_ratio(df)
    confidence = 45.0 + (streak - cfg.bb_min_sequence_len) * 8
    confidence += 15 if volume_trending_up else 0
    confidence += min(15.0, max(0.0, (vol_ratio - cfg.bb_volume_ratio) * 6))
    confidence = min(confidence, 80.0)  # capped below the other 4 — this is the riskiest setup by design

    price = float(last["close"])
    entry = price
    stop = float(last["low"])
    risk = max(entry - stop, entry * 0.008)
    target = entry + risk * cfg.bb_rr_ratio

    reasons = [
        f"{streak} consecutive gap-down bars culminating in one final, biggest gap-down bar that closed BULLISH on {vol_ratio:.2f}x average volume.",
        (
            "Volume built through the sequence into the reversal bar — a classic institutional capitulation-buying footprint."
            if volume_trending_up else
            "Volume did not clearly build through the sequence — a weaker version of the pattern, treat with extra caution."
        ),
    ]
    risk_note = (
        "⚠️ HIGHEST RISK of the 5 setups — this is a countertrend 'catch the falling knife' trade. Many gap-down "
        "sequences keep falling with no reversal. Size this smaller than the other 4 strategies and respect the stop strictly."
    )
    return _finalize(
        strategy=BOTTOM_BOUNCE, direction="LONG", confidence=confidence, entry=entry, stop=stop, target=target,
        reasons=reasons, timeframe=timeframe, risk_note=risk_note,
        hold_override="2–15 trading days (sharp mean-reversion attempt — monitor closely)",
    )


_DETECTORS = {
    BREAKOUT: lambda df, tf, cfg, is_crypto: detect_breakout(df, tf, cfg),
    EPISODIC_PIVOT: lambda df, tf, cfg, is_crypto: detect_episodic_pivot(df, tf, cfg, is_crypto=is_crypto),
    PULLBACK: lambda df, tf, cfg, is_crypto: detect_pullback(df, tf, cfg),
    UPTREND_BOUNCE: lambda df, tf, cfg, is_crypto: detect_uptrend_bounce(df, tf, cfg),
    BOTTOM_BOUNCE: lambda df, tf, cfg, is_crypto: detect_bottom_bounce(df, tf, cfg),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_ticker(
    ticker: str, market: str, timeframe: str, strategies: list[str], *,
    cfg: Swing5Config | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    """Fetch OHLCV once, then run every selected strategy detector against it."""
    cfg = cfg or Swing5Config()
    is_crypto = "CoinDCX" in market or "crypto" in market.lower()
    df = _fetch_ohlcv(ticker, market, timeframe, groww_token=groww_token, exchange=exchange, limit=max(cfg.risk_free_lookback, 300))

    base = {"ticker": ticker, "market": market, "timeframe": timeframe}
    if df is None or df.empty or len(df) < 30:
        err = f"Insufficient {timeframe} data ({0 if df is None else len(df)} bars)."
        return {**base, "error": err}

    price = float(df["close"].iloc[-1])
    results: dict[str, dict] = {}
    for key in strategies:
        detector = _DETECTORS.get(key)
        if not detector:
            continue
        try:
            results[key] = detector(df, timeframe, cfg, is_crypto)
        except Exception as exc:
            logger.debug("Swing strategy %s failed for %s (%s): %s", key, ticker, timeframe, exc)
            results[key] = _empty_result(key, f"Detector error: {exc}")

    return {**base, "price": price, "strategies": results}


def scan_universe(
    tickers: list[str], timeframes: list[str], market: str, strategies: list[str], *,
    cfg: Swing5Config | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    """Returns {strategy_key: {"hits": [...], "misses": [...], "errors": [...]}}."""
    cfg = cfg or Swing5Config()
    out: dict[str, dict[str, list]] = {k: {"hits": [], "misses": [], "errors": []} for k in strategies}

    for ticker in tickers:
        for tf in timeframes:
            res = analyze_ticker(ticker, market, tf, strategies, cfg=cfg, groww_token=groww_token, exchange=exchange)
            if res.get("error"):
                for key in strategies:
                    out[key]["errors"].append({"ticker": ticker, "timeframe": tf, "error": res["error"]})
                continue
            for key, strat_res in (res.get("strategies") or {}).items():
                row = {"ticker": ticker, "timeframe": tf, "price": res.get("price"), **strat_res}
                if strat_res.get("setup_found"):
                    out[key]["hits"].append(row)
                else:
                    out[key]["misses"].append(row)

    for key in strategies:
        out[key]["hits"].sort(key=lambda r: -(r.get("confidence_pct") or 0))
    return out
