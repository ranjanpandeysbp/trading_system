"""
fibonacci_pro_engine.py
-----------------------
Advanced Fibonacci playbook for Pro Trade — evaluates several experienced-
trader Fib strategies on the same swing structure and returns trade setups
with confidence%, SL%, TP%, and explicit "when to use" guidance.

Strategies
~~~~~~~~~~
1. golden_pocket   — Classic 50–61.8% trend-pullback entry
2. ote_smc         — Optimal Trade Entry (61.8–78.6 discount/premium)
3. deep_786        — Deep 78.6% retrace with stop beyond the swing
4. extension_ride  — Continuation toward 127.2% / 161.8% extensions
5. fib_cluster     — Primary + secondary swing Fib levels cluster within ATR
6. rejection_fade  — Fade exhaustion after tagging a Fib extension

All asset classes (india / us / crypto / commodity) via standard fetch path.
Research / education only — not financial advice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.price_action import analyze_fibonacci
from app.market_pulse.pro_trade_shared import (
    ConfidenceScore,
    atr as _atr_ind,
    ema as _ema,
    kaufman_efficiency_ratio,
    build_pro_trade_ai_context,
    pro_trade_ai_system,
    rr_ratio,
    sl_tp_pct,
)

logger = logging.getLogger(__name__)

STRATEGY_NAME = "Fibonacci Pro"

# Catalog shown in API + FE so the user knows when to pick each strategy.
STRATEGY_CATALOG: list[dict[str, Any]] = [
    {
        "id": "golden_pocket",
        "label": "Golden Pocket Pullback (50–61.8%)",
        "when_to_use": (
            "Use after a clear impulse when price is pulling back into the 50–61.8% "
            "golden pocket and the higher-TF trend (EMA alignment) is still intact. "
            "Best on 1h–1d in trending India/US equities and liquid crypto. Skip in chop."
        ),
        "style": "trend continuation",
        "typical_rr": "1.5–2.5",
    },
    {
        "id": "ote_smc",
        "label": "OTE / Optimal Trade Entry (61.8–78.6%)",
        "when_to_use": (
            "SMC-style: wait for a liquidity sweep or deep pullback into the 61.8–78.6% "
            "discount (long) / premium (short) zone, then enter with the trend. Prefer "
            "when session structure is clean and ER shows directional efficiency."
        ),
        "style": "smart money pullback",
        "typical_rr": "2–3",
    },
    {
        "id": "deep_786",
        "label": "Deep 78.6% Retracement",
        "when_to_use": (
            "Volatile names that routinely deep-retrace before continuing. Enter near "
            "78.6% with stop beyond the swing extreme (100%). Better R:R than shallow "
            "entries, but more stop-outs — size smaller. Good for commodities & crypto."
        ),
        "style": "aggressive continuation",
        "typical_rr": "2.5–4",
    },
    {
        "id": "extension_ride",
        "label": "Extension Ride (127.2% / 161.8%)",
        "when_to_use": (
            "Price already reclaimed the swing origin (0%) after a shallow pullback and "
            "is thrusting toward measured extensions. Use in strong trends (high ER, "
            "EMA stacked). Scale out at 127.2%, trail remainder toward 161.8%."
        ),
        "style": "trend expansion",
        "typical_rr": "1.5–3",
    },
    {
        "id": "fib_cluster",
        "label": "Fib Cluster Confluence",
        "when_to_use": (
            "When a shorter secondary swing's Fib level stacks within ~1 ATR of the "
            "primary golden zone — confluence of two structures. Highest-quality "
            "entries; rarer. Ideal when you want fewer, higher-conviction trades."
        ),
        "style": "multi-swing confluence",
        "typical_rr": "2–3.5",
    },
    {
        "id": "rejection_fade",
        "label": "Extension Rejection Fade",
        "when_to_use": (
            "Price tagged 127.2%+ extension and printed a rejection (wick / engulfing) "
            "back inside the prior range — exhaustion fade. Counter-trend to the "
            "extension, so keep tight risk. Use sparingly on indices & large caps."
        ),
        "style": "exhaustion fade",
        "typical_rr": "1.5–2.5",
    },
]

ALL_STRATEGY_IDS = [s["id"] for s in STRATEGY_CATALOG]


@dataclass
class FibonacciProConfig:
    timeframe: str = "1d"
    lookback_bars: int = 250
    fib_lookback: int = 100
    secondary_lookback: int = 40
    min_bars: int = 40
    zone_tol_atr: float = 0.55  # how close price must be to a Fib zone (in ATR)
    cluster_tol_atr: float = 1.0
    min_rr: float = 1.4
    sl_buffer_atr: float = 0.35
    strategies: list[str] = field(default_factory=lambda: list(ALL_STRATEGY_IDS))
    start_date: str = ""
    end_date: str = ""


def _build_chart_data(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    # Cap for FE rendering
    view = df.tail(180)
    return [
        {
            "time": str(idx),
            "open": round(float(bar["open"]), 6),
            "high": round(float(bar["high"]), 6),
            "low": round(float(bar["low"]), 6),
            "close": round(float(bar["close"]), 6),
            "volume": round(float(bar["volume"]), 2) if "volume" in bar and pd.notna(bar["volume"]) else None,
        }
        for idx, bar in view.iterrows()
    ]


def _fib_overlay(fib: dict[str, Any], price: float) -> dict[str, Any] | None:
    sh, sl = fib.get("swing_high"), fib.get("swing_low")
    if sh is None or sl is None:
        return None
    levels: list[dict[str, Any]] = []
    ratio_map = {
        "0.0% (High)": 0.0, "0.0% (Low)": 0.0,
        "23.6%": 0.236, "38.2%": 0.382, "50.0%": 0.5,
        "61.8% (Golden)": 0.618, "78.6%": 0.786,
        "100.0% (Low)": 1.0, "100.0% (High)": 1.0,
    }
    for name, px in (fib.get("levels") or {}).items():
        levels.append({"ratio": ratio_map.get(name, 0.5), "price": float(px), "label": name})
    for name, px in (fib.get("extensions") or {}).items():
        try:
            ratio = float(name.replace("%", "")) / 100.0
        except Exception:
            ratio = 1.272
        levels.append({"ratio": ratio, "price": float(px), "label": name})

    nearest = min(levels, key=lambda lv: abs(lv["price"] - price)) if levels else {"ratio": 0.5, "price": price}
    trend = "downtrend" if fib.get("direction") == "DOWN" else "uptrend"
    return {
        "trend": trend,
        "swing_low": float(sl),
        "swing_high": float(sh),
        "levels": [{"ratio": lv["ratio"], "price": lv["price"]} for lv in levels],
        "nearest_level": {"ratio": nearest["ratio"], "price": nearest["price"]},
        "at_key_level": abs(nearest["price"] - price) / max(price, 1e-9) < 0.008,
    }


def _level(fib: dict[str, Any], *keys: str) -> float | None:
    levels = fib.get("levels") or {}
    for k in keys:
        if k in levels and levels[k] is not None:
            return float(levels[k])
    return None


def _ext(fib: dict[str, Any], key: str) -> float | None:
    ex = fib.get("extensions") or {}
    v = ex.get(key)
    return float(v) if v is not None else None


def _near(price: float, lo: float, hi: float, atr_val: float, tol_atr: float) -> bool:
    pad = atr_val * tol_atr
    return (lo - pad) <= price <= (hi + pad)


def _rejection_candle(df: pd.DataFrame, direction: str) -> bool:
    """Simple exhaustion: long upper wick for SHORT fade, long lower wick for LONG fade."""
    if len(df) < 2:
        return False
    bar = df.iloc[-1]
    o, h, l, c = float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"])
    rng = max(h - l, 1e-9)
    upper = h - max(o, c)
    lower = min(o, c) - l
    if direction == "SHORT":
        return upper / rng >= 0.45 and c < o
    return lower / rng >= 0.45 and c > o


def _trend_long(df: pd.DataFrame) -> bool:
    e21 = float(_ema(df["close"], 21).iloc[-1])
    e50 = float(_ema(df["close"], 50).iloc[-1])
    return float(df["close"].iloc[-1]) > e21 >= e50 * 0.998


def _trend_short(df: pd.DataFrame) -> bool:
    e21 = float(_ema(df["close"], 21).iloc[-1])
    e50 = float(_ema(df["close"], 50).iloc[-1])
    return float(df["close"].iloc[-1]) < e21 <= e50 * 1.002


def _finalize_setup(
    *,
    strategy_id: str,
    direction: str,
    entry: float,
    stop: float,
    target: float,
    df: pd.DataFrame,
    cfg: FibonacciProConfig,
    base_score: float,
    base_reason: str,
    extras: list[tuple[bool, float, str, str | None]],
) -> dict[str, Any] | None:
    catalog = next((s for s in STRATEGY_CATALOG if s["id"] == strategy_id), None)
    sl_pct, tp_pct = sl_tp_pct(direction, entry, stop, target)
    rr = rr_ratio(sl_pct, tp_pct)
    if rr is None or rr < cfg.min_rr:
        return None

    er = float(kaufman_efficiency_ratio(df["close"], 14).iloc[-1] or 0)
    score = ConfidenceScore(base_score, base_reason)
    score.add(rr >= cfg.min_rr + 0.3, 8, f"Solid reward:risk ({rr:g}:1)", "Reward:risk only just clears the floor")
    score.add(er >= 0.35, 8, f"Trend efficiency OK (ER {er:.2f})", f"Choppy tape (ER {er:.2f}) — Fib pullbacks less reliable")
    for cond, pts, t, f in extras:
        score.add(cond, pts, t, f)
    conf, reasons = score.finalize()

    return {
        "strategy_id": strategy_id,
        "strategy_label": catalog["label"] if catalog else strategy_id,
        "when_to_use": catalog["when_to_use"] if catalog else "",
        "style": catalog.get("style") if catalog else "",
        "take_trade": True,
        "direction": direction,
        "signal": "BULLISH" if direction == "LONG" else "BEARISH",
        "entry_price": round(entry, 6),
        "stop_price": round(stop, 6),
        "target_price": round(target, 6),
        "sl_pct": sl_pct,
        "tp_pct": tp_pct,
        "rr": rr,
        "confidence_pct": conf,
        "confidence_reasons": reasons,
        "efficiency_ratio": round(er, 3),
    }


def _evaluate_strategies(
    df: pd.DataFrame,
    fib: dict[str, Any],
    fib2: dict[str, Any],
    cfg: FibonacciProConfig,
) -> list[dict[str, Any]]:
    price = float(df["close"].iloc[-1])
    atr_series = _atr_ind(df, 14)
    atr_val = float(atr_series.iloc[-1]) if pd.notna(atr_series.iloc[-1]) else price * 0.01
    buf = atr_val * cfg.sl_buffer_atr
    enabled = set(cfg.strategies or ALL_STRATEGY_IDS)
    setups: list[dict[str, Any]] = []

    gz = fib.get("golden_zone") or {}
    gz_lo, gz_hi = float(gz.get("lower") or 0), float(gz.get("upper") or 0)
    fib_618 = _level(fib, "61.8% (Golden)")
    fib_50 = _level(fib, "50.0%")
    fib_786 = _level(fib, "78.6%")
    swing_hi = float(fib["swing_high"]) if fib.get("swing_high") is not None else None
    swing_lo = float(fib["swing_low"]) if fib.get("swing_low") is not None else None
    ext_127 = _ext(fib, "127.2%")
    ext_161 = _ext(fib, "161.8%")
    impulse_down = fib.get("direction") == "DOWN"  # retracing down from high → look for LONG continuation of prior UP move
    # Wait: analyze_fibonacci direction DOWN means high came after low (up move then retracing down)
    # so continuation of the prior UP impulse = LONG from golden zone.
    # direction UP means low came after high (down move then retracing up) → SHORT continuation.

    want_long = impulse_down  # pullback in uptrend
    want_short = not impulse_down  # pullback in downtrend
    trend_ok_long = _trend_long(df)
    trend_ok_short = _trend_short(df)

    # --- 1. Golden pocket ---
    if "golden_pocket" in enabled and gz_lo and gz_hi and swing_hi and swing_lo:
        if want_long and trend_ok_long and _near(price, gz_lo, gz_hi, atr_val, cfg.zone_tol_atr):
            entry = price
            stop = swing_lo - buf
            target = swing_hi  # back to swing high / origin of pullback
            s = _finalize_setup(
                strategy_id="golden_pocket", direction="LONG", entry=entry, stop=stop, target=target,
                df=df, cfg=cfg, base_score=48,
                base_reason="Price inside golden pocket (50–61.8%) of upswing with EMA trend support",
                extras=[
                    (bool(fib.get("price_in_golden_zone")), 12, "Strictly inside the golden zone", "Near zone but not strictly inside"),
                    (trend_ok_long, 10, "EMA 21≥50 bullish stack", None),
                ],
            )
            if s:
                setups.append(s)
        if want_short and trend_ok_short and _near(price, gz_lo, gz_hi, atr_val, cfg.zone_tol_atr):
            entry = price
            stop = swing_hi + buf
            target = swing_lo
            s = _finalize_setup(
                strategy_id="golden_pocket", direction="SHORT", entry=entry, stop=stop, target=target,
                df=df, cfg=cfg, base_score=48,
                base_reason="Price inside golden pocket of downswing with EMA trend pressure",
                extras=[
                    (bool(fib.get("price_in_golden_zone")), 12, "Strictly inside the golden zone", "Near zone but not strictly inside"),
                    (trend_ok_short, 10, "EMA 21≤50 bearish stack", None),
                ],
            )
            if s:
                setups.append(s)

    # --- 2. OTE 61.8–78.6 ---
    if "ote_smc" in enabled and fib_618 is not None and fib_786 is not None and swing_hi and swing_lo:
        ote_lo, ote_hi = min(fib_618, fib_786), max(fib_618, fib_786)
        if want_long and trend_ok_long and _near(price, ote_lo, ote_hi, atr_val, cfg.zone_tol_atr):
            entry = price
            stop = swing_lo - buf
            target = swing_hi
            s = _finalize_setup(
                strategy_id="ote_smc", direction="LONG", entry=entry, stop=stop, target=target,
                df=df, cfg=cfg, base_score=50,
                base_reason="Optimal Trade Entry zone (61.8–78.6% discount) in uptrend",
                extras=[
                    (price <= fib_618, 8, "Deeper than 61.8% — true discount", "Shallow side of OTE"),
                    (trend_ok_long, 8, "Trend filter green", None),
                ],
            )
            if s:
                setups.append(s)
        if want_short and trend_ok_short and _near(price, ote_lo, ote_hi, atr_val, cfg.zone_tol_atr):
            entry = price
            stop = swing_hi + buf
            target = swing_lo
            s = _finalize_setup(
                strategy_id="ote_smc", direction="SHORT", entry=entry, stop=stop, target=target,
                df=df, cfg=cfg, base_score=50,
                base_reason="Optimal Trade Entry zone (61.8–78.6% premium) in downtrend",
                extras=[
                    (price >= fib_618, 8, "Deeper than 61.8% — true premium", "Shallow side of OTE"),
                    (trend_ok_short, 8, "Trend filter red", None),
                ],
            )
            if s:
                setups.append(s)

    # --- 3. Deep 78.6 ---
    if "deep_786" in enabled and fib_786 is not None and swing_hi and swing_lo:
        if want_long and trend_ok_long and abs(price - fib_786) <= atr_val * cfg.zone_tol_atr:
            entry = price
            stop = swing_lo - buf
            target = fib_50 or swing_hi
            s = _finalize_setup(
                strategy_id="deep_786", direction="LONG", entry=entry, stop=stop, target=target,
                df=df, cfg=cfg, base_score=44,
                base_reason="Deep 78.6% retracement support in uptrend — aggressive R:R entry",
                extras=[
                    (abs(price - fib_786) <= atr_val * 0.35, 10, "Pinned tightly on 78.6%", "Loose proximity to 78.6%"),
                ],
            )
            if s:
                setups.append(s)
        if want_short and trend_ok_short and abs(price - fib_786) <= atr_val * cfg.zone_tol_atr:
            entry = price
            stop = swing_hi + buf
            target = fib_50 or swing_lo
            s = _finalize_setup(
                strategy_id="deep_786", direction="SHORT", entry=entry, stop=stop, target=target,
                df=df, cfg=cfg, base_score=44,
                base_reason="Deep 78.6% retracement resistance in downtrend",
                extras=[
                    (abs(price - fib_786) <= atr_val * 0.35, 10, "Pinned tightly on 78.6%", "Loose proximity to 78.6%"),
                ],
            )
            if s:
                setups.append(s)

    # --- 4. Extension ride ---
    if "extension_ride" in enabled and swing_hi and swing_lo and ext_127 is not None:
        # Long: price above prior swing high (0% of down-retracement = high) thrusting to extension
        if impulse_down and trend_ok_long and price >= swing_hi - atr_val * 0.15:
            entry = price
            stop = (fib_618 or swing_lo) - buf
            target = ext_161 or ext_127
            if target > entry:
                s = _finalize_setup(
                    strategy_id="extension_ride", direction="LONG", entry=entry, stop=stop, target=target,
                    df=df, cfg=cfg, base_score=46,
                    base_reason="Reclaimed swing high — riding toward Fib extension targets",
                    extras=[
                        (ext_161 is not None, 6, "161.8% extension mapped as stretch target", None),
                        (price > swing_hi, 8, "Already through swing origin", "Still kissing the swing high"),
                    ],
                )
                if s:
                    setups.append(s)
        if (not impulse_down) and trend_ok_short and price <= swing_lo + atr_val * 0.15:
            entry = price
            stop = (fib_618 or swing_hi) + buf
            target = ext_161 or ext_127
            if target < entry:
                s = _finalize_setup(
                    strategy_id="extension_ride", direction="SHORT", entry=entry, stop=stop, target=target,
                    df=df, cfg=cfg, base_score=46,
                    base_reason="Broke swing low — riding toward Fib extension targets",
                    extras=[
                        (ext_161 is not None, 6, "161.8% extension mapped as stretch target", None),
                        (price < swing_lo, 8, "Already through swing origin", "Still kissing the swing low"),
                    ],
                )
                if s:
                    setups.append(s)

    # --- 5. Fib cluster ---
    if "fib_cluster" in enabled and gz_lo and gz_hi and fib2.get("levels"):
        sec_levels = [float(v) for v in (fib2.get("levels") or {}).values() if v is not None]
        cluster_hits = [lv for lv in sec_levels if gz_lo - atr_val * cfg.cluster_tol_atr <= lv <= gz_hi + atr_val * cfg.cluster_tol_atr]
        if cluster_hits and _near(price, gz_lo, gz_hi, atr_val, cfg.zone_tol_atr):
            if want_long and trend_ok_long and swing_lo and swing_hi:
                entry = price
                stop = swing_lo - buf
                target = swing_hi
                s = _finalize_setup(
                    strategy_id="fib_cluster", direction="LONG", entry=entry, stop=stop, target=target,
                    df=df, cfg=cfg, base_score=55,
                    base_reason="Primary golden zone overlaps a secondary-swing Fib (cluster confluence)",
                    extras=[
                        (len(cluster_hits) >= 2, 10, f"{len(cluster_hits)} secondary levels in cluster", "Single secondary level in cluster"),
                    ],
                )
                if s:
                    setups.append(s)
            if want_short and trend_ok_short and swing_lo and swing_hi:
                entry = price
                stop = swing_hi + buf
                target = swing_lo
                s = _finalize_setup(
                    strategy_id="fib_cluster", direction="SHORT", entry=entry, stop=stop, target=target,
                    df=df, cfg=cfg, base_score=55,
                    base_reason="Primary golden zone overlaps a secondary-swing Fib (cluster confluence)",
                    extras=[
                        (len(cluster_hits) >= 2, 10, f"{len(cluster_hits)} secondary levels in cluster", "Single secondary level in cluster"),
                    ],
                )
                if s:
                    setups.append(s)

    # --- 6. Rejection fade at extension ---
    if "rejection_fade" in enabled and ext_127 is not None and swing_hi and swing_lo:
        if abs(price - ext_127) <= atr_val * 1.1 or (ext_161 and abs(price - ext_161) <= atr_val * 1.1):
            # Fade against the extension direction
            if impulse_down and _rejection_candle(df, "SHORT"):
                # Was riding up into extension → fade SHORT
                entry = price
                stop = max(ext_161 or ext_127, price) + buf
                target = swing_hi
                s = _finalize_setup(
                    strategy_id="rejection_fade", direction="SHORT", entry=entry, stop=stop, target=target,
                    df=df, cfg=cfg, base_score=42,
                    base_reason="Rejection wick at Fib extension — exhaustion fade SHORT",
                    extras=[
                        (ext_161 is not None and abs(price - ext_161) <= atr_val, 8, "Tagged 161.8% stretch", "Near 127.2% only"),
                    ],
                )
                if s:
                    setups.append(s)
            if (not impulse_down) and _rejection_candle(df, "LONG"):
                entry = price
                stop = min(ext_161 or ext_127, price) - buf
                target = swing_lo
                s = _finalize_setup(
                    strategy_id="rejection_fade", direction="LONG", entry=entry, stop=stop, target=target,
                    df=df, cfg=cfg, base_score=42,
                    base_reason="Rejection wick at Fib extension — exhaustion fade LONG",
                    extras=[
                        (ext_161 is not None and abs(price - ext_161) <= atr_val, 8, "Tagged 161.8% stretch", "Near 127.2% only"),
                    ],
                )
                if s:
                    setups.append(s)

    setups.sort(key=lambda s: -(s.get("confidence_pct") or 0))
    return setups


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: FibonacciProConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or FibonacciProConfig()
    out: dict[str, Any] = {
        "ticker": ticker,
        "strategy": STRATEGY_NAME,
        "error": None,
        "chart_data": [],
        "fibonacci": None,
        "fib_primary": None,
        "setups": [],
        "take_trade": False,
        "signal": "NEUTRAL",
        "verdict": "NO SETUP",
        "confidence_pct": None,
        "sl_pct": None,
        "tp_pct": None,
        "strategy_catalog": STRATEGY_CATALOG,
        "rules": [
            "Primary swing Fib from the configured lookback; secondary swing for cluster confluence.",
            "EMA 21/50 filter keeps pullback strategies aligned with the prevailing trend.",
            "Each strategy only fires when price is near its Fib zone (ATR tolerance) and R:R clears the floor.",
            "Read 'when_to_use' on each setup — different Fib tactics fit different market regimes.",
        ],
    }

    try:
        df = fetch_data_for_gap_scan(
            ticker, cfg.timeframe, market,
            groww_token=groww_token, exchange=exchange, limit=cfg.lookback_bars,
        )
    except Exception as exc:
        out["error"] = f"Data fetch failed: {exc}"
        return out

    df = normalize_ohlcv(df)
    if df is None or df.empty:
        out["error"] = "Insufficient OHLCV for Fibonacci analysis"
        return out

    if cfg.start_date or cfg.end_date:
        df = df.loc[(cfg.start_date or None):(cfg.end_date or None)]
        if df.empty or len(df) < cfg.min_bars:
            out["error"] = f"Only {len(df)} bars in selected date window (need ≥{cfg.min_bars})"
            return out

    if len(df) < cfg.min_bars:
        out["error"] = "Insufficient OHLCV for Fibonacci analysis"
        return out

    fib = analyze_fibonacci(df, lookback=cfg.fib_lookback)
    fib2 = analyze_fibonacci(df, lookback=cfg.secondary_lookback)
    price = float(df["close"].iloc[-1])

    out["ltp"] = round(price, 6)
    out["bars"] = len(df)
    out["chart_data"] = _build_chart_data(df)
    out["fib_primary"] = fib
    out["fibonacci"] = _fib_overlay(fib, price)
    out["golden_zone"] = fib.get("golden_zone")
    out["swing_high"] = fib.get("swing_high")
    out["swing_low"] = fib.get("swing_low")
    out["fib_direction"] = fib.get("direction")

    setups = _evaluate_strategies(df, fib, fib2, cfg)
    out["setups"] = setups

    if setups:
        best = setups[0]
        out["take_trade"] = True
        out["best_strategy_id"] = best["strategy_id"]
        out["best_strategy_label"] = best["strategy_label"]
        out["when_to_use"] = best["when_to_use"]
        out["direction"] = best["direction"]
        out["signal"] = best["signal"]
        out["entry_price"] = best["entry_price"]
        out["stop_price"] = best["stop_price"]
        out["target_price"] = best["target_price"]
        out["sl_pct"] = best["sl_pct"]
        out["tp_pct"] = best["tp_pct"]
        out["rr"] = best["rr"]
        out["confidence_pct"] = best["confidence_pct"]
        out["confidence_reasons"] = best["confidence_reasons"]
        out["verdict"] = f"{best['strategy_label']} · {best['direction']}"
        out["plain_english"] = (
            f"SIGNAL: {best['signal']} ({best['direction']}) — {best['strategy_label']}. "
            f"Confidence {best['confidence_pct']:.0f}% · SL {best['sl_pct']:.1f}% · TP {best['tp_pct']:.1f}% "
            f"(R:R 1:{best['rr']}). When to use: {best['when_to_use']}"
        )
    else:
        out["plain_english"] = (
            "SIGNAL: NEUTRAL. No Fib strategy is currently in its entry zone with trend confirmation "
            "and acceptable reward:risk. Wait for price to tag a golden pocket / OTE / 78.6 / extension "
            "level — see the strategy catalog for when each tactic applies."
        )
        out["verdict"] = "WAIT — no Fib zone entry"

    return out


def build_fibonacci_pro_ai_prompt(result: dict[str, Any]) -> str:
    extra: list[str] = []
    if result.get("best_strategy_label"):
        extra.append(f"Best Fib strategy: {result.get('best_strategy_label')}")
    if result.get("when_to_use"):
        extra.append(f"When to use: {result.get('when_to_use')}")
    setups = result.get("setups")
    if isinstance(setups, list) and setups:
        extra.append(f"Active Fib setups: {len(setups)}")
    return build_pro_trade_ai_context(result, engine_label="Fibonacci Pro", extra_lines=extra or None)


FIBONACCI_PRO_AI_SYSTEM = pro_trade_ai_system(
    "Fibonacci Pro",
    "Multi-strategy Fibonacci playbook (golden pocket, OTE/SMC 61.8–78.6, deep 78.6, extension ride, "
    "Fib cluster confluence, extension rejection fade). Each setup carries confidence%, SL%, TP%, and "
    "explicit when-to-use guidance. Trend filter is EMA 21/50; zone proximity uses ATR.",
)


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: FibonacciProConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or FibonacciProConfig()
    results: list[dict[str, Any]] = []
    for t in tickers:
        try:
            results.append(analyze_ticker(t, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            logger.exception("Fibonacci Pro failed for %s", t)
            results.append({"ticker": t, "error": str(exc)[:300], "take_trade": False, "setups": []})

    entries = [r for r in results if not r.get("error") and r.get("take_trade")]
    entries.sort(key=lambda r: -(r.get("confidence_pct") or 0))

    return {
        "strategy": STRATEGY_NAME,
        "results": results,
        "entry_count": len(entries),
        "strategy_catalog": STRATEGY_CATALOG,
        "timeframe": cfg.timeframe,
        "scanned": len(results),
    }
