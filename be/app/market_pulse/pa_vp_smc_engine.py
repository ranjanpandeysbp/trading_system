"""
pa_vp_smc_engine.py
---------------------
PA-VP-SMC — Price Action + Volume Profile + Smart Money Concepts confluence.
The "best of everything" Pro Trade strategy: rather than trading any single
technique alone, this scores how many independent, well-known institutional
concepts agree at the CURRENT price, and only calls a trade when several of
them stack up at the same level.

Pillars combined into one confluence score:
  - Price Action (PA): higher-timeframe trend (EMA stack), a liquidity sweep
    (stop-hunt wick through a prior swing high/low that closes back inside),
    and a confirming candlestick reversal pattern on the entry timeframe.
  - Volume Profile (VP): the higher-timeframe session POC / VAH / VAL —
    institutional "fair value" and the edges of where most volume traded.
  - Smart Money Concepts (SMC): unmitigated Order Blocks (the last opposite
    candle before a displacement move), a nearby unmitigated Fair Value Gap,
    and where price sits in its recent premium/discount range.
  - Classic swing structure Support/Resistance, as one more independent
    vote (not a proxy for any of the above — it comes from pure swing-high/
    swing-low geometry).
  - Options execution: a synthetic-futures structure suggestion (same
    ATM CE+PE construction used elsewhere in Pro Trade) plus an ITM-option
    note, since a Volume-Profile-anchored level reacts better to an ITM
    option's higher delta than an OTM lottery ticket.

Each pillar that lines up with the same direction at (or near) the same
price adds points to a single confidence_pct — the more independent
concepts agree, the higher the score. A trade is only marked actionable
once at least `min_confluence_factors` distinct pillars agree.

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
from app.market_pulse.pro_trade_shared import (
    ConfidenceScore,
    atr as _atr_ind,
    build_pro_trade_ai_context,
    pro_trade_ai_system,
    sl_tp_pct,
)
from app.market_pulse.run_summary import make_trade_plan
from app.market_pulse.volume_profile_ce_engine import calculate_volume_profile, suggest_synthetic_future
from app.trading_hubs.smart_money_shared import enrich_smc_live, hold_for_tf
from app.trading_hubs.support_resistance_engine import detect_candlestick_patterns

logger = logging.getLogger(__name__)

STRATEGY_NAME = "PA-VP-SMC"

HTF_OPTIONS = ["30m", "1h", "4h", "1d"]
LTF_OPTIONS = ["5m", "15m", "30m", "1h"]

PHASE_NONE = "NO_CONFLUENCE"
PHASE_PARTIAL = "PARTIAL_CONFLUENCE"
PHASE_ENTRY = "FULL_CONFLUENCE"


@dataclass
class PaVpSmcConfig:
    htf: str = "1h"
    ltf: str = "15m"
    lookback_bars: int = 300
    swing_window: int = 5
    vp_num_bins: int = 50
    vp_value_area_pct: float = 0.70
    zone_tolerance_pct: float = 0.5  # how close price must be to a level to count as "at" it
    displacement_atr_mult: float = 1.8  # order block / FVG significance filter
    min_confluence_factors: int = 3  # distinct pillars required before calling it actionable
    rr_min: float = 1.5
    min_bars: int = 80
    suggest_synthetic: bool = True


# ---------------------------------------------------------------------------
# Self-contained structural helpers (matching the style of this app's other
# hub engines rather than a shared library for the core primitives)
# ---------------------------------------------------------------------------

def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return _atr_ind(df, period)


def _swing_columns(df: pd.DataFrame, window: int) -> pd.DataFrame:
    out = df.copy()
    half = max(1, window // 2)
    highs = out["high"].values
    lows = out["low"].values
    n = len(out)
    swing_hi = np.full(n, np.nan)
    swing_lo = np.full(n, np.nan)
    for i in range(half, n - half):
        w_hi = highs[i - half : i + half + 1].max()
        w_lo = lows[i - half : i + half + 1].min()
        if highs[i] == w_hi:
            swing_hi[i] = highs[i]
        if lows[i] == w_lo:
            swing_lo[i] = lows[i]
    out["swing_high"] = swing_hi
    out["swing_low"] = swing_lo
    return out


def _zone_from_swing(df: pd.DataFrame, idx: int, is_high: bool) -> dict[str, Any]:
    bar = df.iloc[idx]
    body_top = max(bar["open"], bar["close"])
    body_bottom = min(bar["open"], bar["close"])
    if is_high:
        return {"top": float(bar["high"]), "bottom": float(body_top), "origin_index": idx}
    return {"top": float(body_bottom), "bottom": float(bar["low"]), "origin_index": idx}


def find_swing_sr_zones(df: pd.DataFrame, cfg: PaVpSmcConfig) -> dict[str, dict[str, Any] | None]:
    """Nearest classic support/resistance from swing-fractal rejection
    clusters — an independent vote from pure price geometry, separate from
    VP or SMC constructs."""
    swung = _swing_columns(df, cfg.swing_window)
    n = len(df)
    start = max(0, n - cfg.lookback_bars)
    price = float(df["close"].iloc[-1])
    closes = df["close"].values

    candidates: list[dict[str, Any]] = []
    for i in range(start, n):
        if not pd.isna(swung["swing_high"].iloc[i]):
            zone = _zone_from_swing(df, i, is_high=True)
            role = "resistance"
            after = closes[i + 1 :]
            if len(after) and after.max() > zone["top"]:
                role = "support"
            candidates.append({**zone, "role": role})
        if not pd.isna(swung["swing_low"].iloc[i]):
            zone = _zone_from_swing(df, i, is_high=False)
            role = "support"
            after = closes[i + 1 :]
            if len(after) and after.min() < zone["bottom"]:
                role = "resistance"
            candidates.append({**zone, "role": role})

    support = None
    resistance = None
    for z in sorted(candidates, key=lambda z: -z["origin_index"]):
        if z["role"] == "support" and z["top"] <= price and support is None:
            support = z
        elif z["role"] == "resistance" and z["bottom"] >= price and resistance is None:
            resistance = z
        if support and resistance:
            break
    return {"support": support, "resistance": resistance}


def detect_order_blocks(df: pd.DataFrame, cfg: PaVpSmcConfig, *, max_blocks: int = 8) -> list[dict[str, Any]]:
    """The last opposite-colour candle right before a strong displacement
    candle — the standard SMC Order Block, kept only while unmitigated."""
    n = len(df)
    if n < 6:
        return []
    atr = _atr(df, 14)
    highs, lows, opens, closes = df["high"].values, df["low"].values, df["open"].values, df["close"].values
    ranges = highs - lows

    blocks: list[dict[str, Any]] = []
    for i in range(1, n):
        a = atr.iloc[i]
        if pd.isna(a) or a <= 0 or ranges[i] < a * cfg.displacement_atr_mult:
            continue
        impulse_bullish = closes[i] > opens[i]
        prev = i - 1
        prev_bullish = closes[prev] > opens[prev]
        if impulse_bullish and not prev_bullish:
            ob_type = "bullish"
        elif not impulse_bullish and prev_bullish:
            ob_type = "bearish"
        else:
            continue
        top, bottom = float(highs[prev]), float(lows[prev])
        after = df.iloc[i + 1 :]
        mitigated = bool(not after.empty and ((after["low"] <= top) & (after["high"] >= bottom)).any())
        if mitigated:
            continue
        blocks.append({"top": round(top, 6), "bottom": round(bottom, 6), "type": ob_type, "origin_index": prev})

    blocks.sort(key=lambda b: -b["origin_index"])
    return blocks[:max_blocks]


def detect_recent_fvg(df: pd.DataFrame, *, max_lookback: int = 60) -> dict[str, Any] | None:
    """Most recent still-unfilled 3-candle Fair Value Gap."""
    n = len(df)
    start = max(2, n - max_lookback)
    for i in range(n - 1, start - 1, -1):
        c1 = df.iloc[i - 2]
        c3 = df.iloc[i]
        if float(c3["low"]) > float(c1["high"]):
            top, bottom = float(c3["low"]), float(c1["high"])
            after = df.iloc[i + 1 :]
            filled = bool(not after.empty and float(after["low"].min()) <= bottom)
            if not filled:
                return {"type": "bullish_fvg", "direction": "LONG", "top": round(top, 6), "bottom": round(bottom, 6)}
        elif float(c3["high"]) < float(c1["low"]):
            top, bottom = float(c1["low"]), float(c3["high"])
            after = df.iloc[i + 1 :]
            filled = bool(not after.empty and float(after["high"].max()) >= top)
            if not filled:
                return {"type": "bearish_fvg", "direction": "SHORT", "top": round(top, 6), "bottom": round(bottom, 6)}
    return None


def detect_liquidity_sweep(df: pd.DataFrame, swing_window: int, *, recent_swings: int = 5) -> dict[str, Any] | None:
    """Latest closed bar wicks through a prior swing high/low and closes back
    inside — the classic SMC stop-hunt / liquidity grab that precedes a
    reversal, checked only on the most recent bar (a live, not stale, read)."""
    n = len(df)
    if n < swing_window * 2 + 2:
        return None
    swung = _swing_columns(df.iloc[:-1], swing_window)
    prior_highs = swung["swing_high"].dropna().iloc[-recent_swings:]
    prior_lows = swung["swing_low"].dropna().iloc[-recent_swings:]
    last = df.iloc[-1]
    last_high, last_low, last_close = float(last["high"]), float(last["low"]), float(last["close"])

    for level in prior_highs.values:
        level = float(level)
        if last_high > level and last_close < level:
            return {
                "type": "sell_side_sweep", "direction": "SHORT", "level": round(level, 6),
                "note": f"latest bar wicked above the prior swing high ({level:,.4g}) then closed back below — sell-side liquidity swept",
            }
    for level in prior_lows.values:
        level = float(level)
        if last_low < level and last_close > level:
            return {
                "type": "buy_side_sweep", "direction": "LONG", "level": round(level, 6),
                "note": f"latest bar wicked below the prior swing low ({level:,.4g}) then closed back above — buy-side liquidity swept",
            }
    return None


def classify_trend(df: pd.DataFrame) -> dict[str, Any]:
    ema20 = df["close"].ewm(span=20, adjust=False).mean()
    ema50 = df["close"].ewm(span=50, adjust=False).mean()
    if ema20.dropna().empty or ema50.dropna().empty:
        return {"trend": "unknown"}
    price = float(df["close"].iloc[-1])
    e20, e50 = float(ema20.iloc[-1]), float(ema50.iloc[-1])
    if price > e20 > e50:
        return {"trend": "bullish", "note": "price above the 20 EMA, which is above the 50 EMA — clean bullish stack"}
    if price < e20 < e50:
        return {"trend": "bearish", "note": "price below the 20 EMA, which is below the 50 EMA — clean bearish stack"}
    return {"trend": "mixed", "note": "EMAs not cleanly stacked — no clear higher-timeframe trend"}


def premium_discount_zone(df: pd.DataFrame, swing_window: int) -> dict[str, Any]:
    swung = _swing_columns(df, swing_window)
    highs = swung["swing_high"].dropna()
    lows = swung["swing_low"].dropna()
    if highs.empty or lows.empty:
        return {"zone": "unknown", "pct": 0.5}
    range_high = float(highs.iloc[-3:].max())
    range_low = float(lows.iloc[-3:].min())
    price = float(df["close"].iloc[-1])
    if range_high <= range_low:
        return {"zone": "unknown", "pct": 0.5}
    pct = (price - range_low) / (range_high - range_low)
    zone = "discount" if pct <= 0.5 else "premium"
    return {"zone": zone, "pct": round(pct, 3), "range_high": round(range_high, 6), "range_low": round(range_low, 6)}


def _nearest_ob(order_blocks: list[dict[str, Any]], direction: str, price: float, tolerance_pct: float) -> dict[str, Any] | None:
    wanted = "bullish" if direction == "LONG" else "bearish"
    candidates = [
        ob for ob in order_blocks
        if ob["type"] == wanted and (
            ob["bottom"] <= price <= ob["top"]
            or abs(price - (ob["top"] if direction == "SHORT" else ob["bottom"])) / price * 100 <= tolerance_pct
        )
    ]
    return candidates[0] if candidates else None


def _build_chart_data(df: pd.DataFrame, *, max_bars: int = 320) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    tail = df.iloc[-max_bars:]
    return [
        {
            "time": str(idx),
            "open": round(float(bar["open"]), 6), "high": round(float(bar["high"]), 6),
            "low": round(float(bar["low"]), 6), "close": round(float(bar["close"]), 6),
            "volume": round(float(bar["volume"]), 2) if "volume" in bar and pd.notna(bar["volume"]) else None,
        }
        for idx, bar in tail.iterrows()
    ]


def _vp_histogram(vp: pd.DataFrame) -> list[dict[str, Any]]:
    if vp is None or vp.empty:
        return []
    out = []
    for _, row in vp.iterrows():
        mid = row.get("Mid_Price")
        vol = row.get("Volume")
        if mid is None or pd.isna(mid):
            continue
        out.append({"price": round(float(mid), 4), "volume": round(float(vol or 0), 2)})
    return out


# ---------------------------------------------------------------------------
# Main confluence engine
# ---------------------------------------------------------------------------

def analyze_ticker(
    ticker: str, market: str, *, cfg: PaVpSmcConfig | None = None,
    groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or PaVpSmcConfig()
    out: dict[str, Any] = {
        "ticker": ticker, "strategy": STRATEGY_NAME, "error": None,
        "confluence": None, "reasons": [], "chart_data": [], "vp_histogram": [],
        "rules": [
            "Only take a setup once several independent pillars (PA / VP / SMC / classic S/R) agree — a single technique alone isn't enough here.",
            "Prefer ITM options at Volume-Profile-anchored levels — they track the level far better than OTM lottery tickets.",
            "Synthetic futures (ATM CE bought + ATM PE sold, or the mirror) are shown as a capital-efficient execution route — always hedge overnight.",
        ],
    }

    try:
        htf_df = fetch_data_for_gap_scan(ticker, cfg.htf, market, groww_token=groww_token, exchange=exchange, limit=cfg.lookback_bars)
        htf_df = normalize_ohlcv(htf_df)
        ltf_df = fetch_data_for_gap_scan(ticker, cfg.ltf, market, groww_token=groww_token, exchange=exchange, limit=cfg.lookback_bars)
        ltf_df = normalize_ohlcv(ltf_df)
    except Exception as exc:
        out["error"] = f"Data fetch failed: {exc}"
        return out

    if htf_df.empty or len(htf_df) < cfg.min_bars:
        out["error"] = f"Insufficient {cfg.htf} data."
        return out
    if ltf_df.empty or len(ltf_df) < cfg.min_bars:
        out["error"] = f"Insufficient {cfg.ltf} data."
        return out

    price = float(ltf_df["close"].iloc[-1])
    out["ltp"] = round(price, 4)
    out["chart_data"] = _build_chart_data(ltf_df, max_bars=320)

    poc, vah, val, vp = calculate_volume_profile(htf_df, num_bins=cfg.vp_num_bins, value_area_pct=cfg.vp_value_area_pct)
    out["vp_histogram"] = _vp_histogram(vp)
    out["volume_profile"] = (
        {"poc": round(poc, 4), "vah": round(vah, 4), "val": round(val, 4), "tf": cfg.htf}
        if poc is not None else None
    )

    order_blocks = detect_order_blocks(htf_df, cfg)
    sr_zones = find_swing_sr_zones(htf_df, cfg)
    trend = classify_trend(htf_df)
    pd_zone = premium_discount_zone(htf_df, cfg.swing_window)
    sweep = detect_liquidity_sweep(ltf_df, cfg.swing_window)
    candle_patterns = detect_candlestick_patterns(ltf_df, lookback=3)
    ltf_fvg = detect_recent_fvg(ltf_df)

    out["support_zone"] = [round(sr_zones["support"]["bottom"], 6), round(sr_zones["support"]["top"], 6)] if sr_zones.get("support") else None
    out["resistance_zone"] = [round(sr_zones["resistance"]["bottom"], 6), round(sr_zones["resistance"]["top"], 6)] if sr_zones.get("resistance") else None
    out["trend"] = trend
    out["premium_discount"] = pd_zone
    out["order_blocks"] = order_blocks[:5]
    out["liquidity_sweep"] = sweep
    out["fvg"] = ltf_fvg
    out["candlestick_patterns"] = candle_patterns

    # Determine a direction candidate to evaluate: prefer a live liquidity
    # sweep (the most time-sensitive PA/SMC tell), then a fresh candlestick
    # reversal pattern, then fall back to the higher-timeframe trend.
    direction: str | None = None
    if sweep:
        direction = sweep["direction"]
    elif candle_patterns:
        first = candle_patterns[0]
        if first["direction"] in ("bullish", "bearish"):
            direction = "LONG" if first["direction"] == "bullish" else "SHORT"
    if direction is None and trend["trend"] in ("bullish", "bearish"):
        direction = "LONG" if trend["trend"] == "bullish" else "SHORT"

    if direction is None:
        out["confluence"] = {
            "direction": None, "matches": 0, "confidence_pct": None,
            "verdict": "WAIT", "phase": PHASE_NONE,
        }
        out["reasons"] = ["No liquidity sweep, candlestick trigger, or clear trend to anchor a direction right now."]
        out["verdict"] = "WAIT"
        out["take_trade"] = False
        return out

    score = ConfidenceScore(25, f"PA-VP-SMC confluence read, direction candidate {direction}")
    matches = 0

    ob = _nearest_ob(order_blocks, direction, price, cfg.zone_tolerance_pct)
    if ob:
        matches += 1
        score.add(True, 15, f"price at an unmitigated {ob['type']} Order Block ({ob['bottom']:,.4g}-{ob['top']:,.4g})")

    near_vp_level = None
    if poc is not None:
        if direction == "LONG" and val is not None and abs(price - val) / price * 100 <= cfg.zone_tolerance_pct:
            near_vp_level = "VAL"
        elif direction == "SHORT" and vah is not None and abs(price - vah) / price * 100 <= cfg.zone_tolerance_pct:
            near_vp_level = "VAH"
        elif abs(price - poc) / price * 100 <= cfg.zone_tolerance_pct * 0.7:
            near_vp_level = "POC"
    if near_vp_level:
        matches += 1
        score.add(True, 15, f"price sits right at the session Volume Profile {near_vp_level}")

    sr = sr_zones.get("support") if direction == "LONG" else sr_zones.get("resistance")
    sr_at_price = bool(sr and sr["bottom"] <= price <= sr["top"] * 1.002)
    if sr_at_price:
        matches += 1
        score.add(True, 15, f"price at a classic swing {'support' if direction == 'LONG' else 'resistance'} zone ({sr['bottom']:,.4g}-{sr['top']:,.4g})")

    if sweep and sweep["direction"] == direction:
        matches += 1
        score.add(True, 15, sweep["note"])

    trigger_match = any(
        p["direction"] == ("bullish" if direction == "LONG" else "bearish") and p["bars_ago"] <= 1
        for p in candle_patterns
    )
    if trigger_match:
        matches += 1
        name = next(p["name"] for p in candle_patterns if p["direction"] == ("bullish" if direction == "LONG" else "bearish"))
        score.add(True, 10, f"{name} candlestick trigger on the entry timeframe")

    trend_match = trend["trend"] == ("bullish" if direction == "LONG" else "bearish")
    if trend_match:
        matches += 1
        score.add(True, 10, trend.get("note", "aligned with the higher-timeframe trend"))

    wanted_zone = "discount" if direction == "LONG" else "premium"
    pd_match = pd_zone.get("zone") == wanted_zone
    if pd_match:
        matches += 1
        score.add(True, 10, f"price sits in the {wanted_zone} zone of its recent range ({pd_zone['pct'] * 100:.0f}%)")

    if ltf_fvg and ltf_fvg["direction"] == direction:
        matches += 1
        score.add(True, 10, "unmitigated Fair Value Gap in the same direction nearby")

    confidence, reasons = score.finalize()
    take = matches >= cfg.min_confluence_factors

    atr_last = float(_atr(ltf_df, 14).dropna().iloc[-1]) if not _atr(ltf_df, 14).dropna().empty else price * 0.005
    if direction == "LONG":
        candidates = [z["bottom"] for z in (ob, sr) if z] + ([sweep["level"]] if sweep and sweep["direction"] == "LONG" else [])
        stop = (min(candidates) if candidates else price - atr_last * 1.5) - atr_last * 0.3
        entry = price
        target_candidates = [lvl for lvl in (poc, vah) if lvl and lvl > entry]
        target = min(target_candidates) if target_candidates else entry + (entry - stop) * cfg.rr_min
    else:
        candidates = [z["top"] for z in (ob, sr) if z] + ([sweep["level"]] if sweep and sweep["direction"] == "SHORT" else [])
        stop = (max(candidates) if candidates else price + atr_last * 1.5) + atr_last * 0.3
        entry = price
        target_candidates = [lvl for lvl in (poc, val) if lvl and lvl < entry]
        target = max(target_candidates) if target_candidates else entry - (stop - entry) * cfg.rr_min

    sl_pct, tp_pct = sl_tp_pct(direction, entry, stop, target)
    if sl_pct and tp_pct and tp_pct / sl_pct < cfg.rr_min:
        risk = abs(entry - stop)
        target = entry + risk * cfg.rr_min if direction == "LONG" else entry - risk * cfg.rr_min
        sl_pct, tp_pct = sl_tp_pct(direction, entry, stop, target)

    hold = hold_for_tf(cfg.ltf, "intraday" if cfg.ltf in ("1m", "3m", "5m", "15m", "30m", "1h") else "swing")
    plan = make_trade_plan(
        direction=direction if take else "—", timeframe=cfg.ltf,
        stop_loss_pct=round(sl_pct or 0, 2), take_profit_pct=round(tp_pct or 0, 2),
        confidence_pct=confidence, style="intraday" if cfg.ltf in ("1m", "3m", "5m", "15m", "30m", "1h") else "swing",
        exit_rule="Exit if price closes back through the confluence zone (setup invalidated), or at the Volume Profile target.",
        max_hold_exit=f"Re-evaluate if neither stop nor target hits within {hold}.",
    )

    execution = None
    if cfg.suggest_synthetic and take:
        execution = suggest_synthetic_future(direction, price)
        execution["itm_note"] = (
            "This confluence anchors to a Volume Profile / Order Block level — prefer a single-leg ITM option "
            "(delta ~0.6-0.75) over the synthetic structure if you'd rather not manage two legs; it tracks the "
            "level almost as well with simpler execution."
        )

    out["confluence"] = {
        "direction": direction, "matches": matches, "min_required": cfg.min_confluence_factors,
        "confidence_pct": confidence, "phase": PHASE_ENTRY if take else (PHASE_PARTIAL if matches > 0 else PHASE_NONE),
    }
    out["reasons"] = reasons
    out["verdict"] = f"TAKE {direction}" if take else (f"WATCH {direction}" if matches > 0 else "WAIT")
    out["take_trade"] = take
    out["entry_price"] = round(entry, 6)
    out["stop_price"] = round(stop, 6)
    out["target_price"] = round(target, 6)
    out["sl_pct"] = sl_pct
    out["tp_pct"] = tp_pct
    out["confidence_pct"] = confidence
    out["hold_duration"] = hold
    out["direction"] = direction
    out["trade_plan"] = {**plan, "holding_period": hold}
    out["execution"] = execution
    return out


def scan_universe(
    tickers: list[str], market: str, *, cfg: PaVpSmcConfig | None = None,
    groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or PaVpSmcConfig()
    results: list[dict[str, Any]] = []
    for t in tickers:
        try:
            results.append(analyze_ticker(t, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            logger.exception("PA-VP-SMC failed for %s", t)
            results.append({"ticker": t, "error": str(exc)[:300], "take_trade": False})

    entries = [r for r in results if not r.get("error") and r.get("take_trade")]
    entries.sort(key=lambda r: -(r.get("confidence_pct") or 0))
    return {
        "strategy": STRATEGY_NAME,
        "results": results,
        "entries": entries,
        "entry_count": len(entries),
        "scanned": len(results),
        "config": {
            "htf": cfg.htf, "ltf": cfg.ltf, "min_confluence_factors": cfg.min_confluence_factors,
            "vp_num_bins": cfg.vp_num_bins, "rr_min": cfg.rr_min,
        },
        "disclaimer": "Research / education only — not financial advice.",
    }


PA_VP_SMC_AI_SYSTEM = pro_trade_ai_system(
    "PA-VP-SMC",
    "Combines Price Action (trend + candlestick trigger), Volume Profile levels, and Smart Money "
    "Concepts (unmitigated order blocks, liquidity sweeps) into one confluence score — a trade only "
    "fires once enough of those independent factors agree on the same direction (min_confluence_factors).",
)


def build_pa_vp_smc_ai_prompt(result: dict[str, Any]) -> str:
    extra: list[str] = []
    if result.get("trend"):
        extra.append(f"Trend classification: {result.get('trend')}")
    order_blocks = result.get("order_blocks")
    if isinstance(order_blocks, list) and order_blocks:
        extra.append(f"Unmitigated order blocks nearby: {len(order_blocks)}")
    confluence = result.get("confluence")
    if isinstance(confluence, dict):
        extra.append(
            f"Confluence: {confluence.get('matches')} of min {confluence.get('min_required')} required "
            f"factors, phase={confluence.get('phase')}"
        )
    reasons = result.get("reasons")
    if isinstance(reasons, list) and reasons:
        extra += ["Reasons:"] + [f"  - {r}" for r in reasons]
    return build_pro_trade_ai_context(result, engine_label="PA-VP-SMC", extra_lines=extra or None)
