"""
bb_mean_reversion_engine.py
-----------------------------
BB Mean Reversion — a Pro Trade confluence strategy built around Bollinger
Band %B stretch (reusing support_resistance_engine.detect_bollinger_mean_
reversion for the core read), hardened with the judgment checks a real
mean-reversion desk applies before fading a stretched move rather than
blindly trading every band touch:

  1. Regime filter — mean reversion only works in range-bound/choppy
     conditions. Kaufman's Efficiency Ratio measures how directly price is
     moving vs. chopping; a market trending too cleanly (high ER) gets the
     trade HARD-BLOCKED to WAIT, since fading a clean trend by "buying the
     lower band" is a classic way to get run over — the band just walks.
  2. Band-squeeze awareness — Bollinger Bandwidth (relative to its own
     recent percentile history) flags when the bands are unusually tight;
     a squeeze usually resolves with a breakout, not a reversion, so it
     lowers confidence rather than confirming it.
  3. RSI extreme confirmation — the %B stretch must be echoed by RSI
     overbought/oversold, not just price poking outside the bands alone.
  4. Candlestick reversal confirmation right at the band (reused from
     support_resistance_engine.detect_candlestick_patterns).
  5. Volume climax — a reversal off a volume spike carries more weight than
     one on quiet volume (pro_trade_shared.volume_zscore).
  6. Independent Support/Resistance confluence — the band touch should
     coincide with a genuine swing-fractal S/R zone (pa_vp_smc_engine.
     find_swing_sr_zones), a vote from pure price geometry, not the bands.
  7. ATR-sane stop just beyond the band edge, target at the mean (the
     middle band) — reward:risk floor enforced, A/B/C quality grade.

Every point is folded into pro_trade_shared.ConfidenceScore, so the final
confidence_pct is auditable, not a black box.

Works across all 4 asset classes (india/us/crypto/commodity) via
gap_trading.fetch_data_for_gap_scan, and scans one or more timeframes across
one or more tickers via scan_universe.

Research / education only — not financial advice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any

import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.pa_vp_smc_engine import PaVpSmcConfig, find_swing_sr_zones
from app.market_pulse.pro_trade_shared import (
    ConfidenceScore,
    atr as _atr_ind,
    atr_sane_stop_target,
    kaufman_efficiency_ratio,
    liquidity_ok,
    quality_grade,
    rr_ratio,
    rsi as _rsi_ind,
    sl_tp_pct,
    volume_zscore,
)
from app.trading_hubs.support_resistance_engine import detect_bollinger_mean_reversion, detect_candlestick_patterns

logger = logging.getLogger(__name__)

STRATEGY_NAME = "BB Mean Reversion"

TIMEFRAME_OPTIONS = ["5m", "15m", "30m", "1h", "4h", "1d", "1wk"]


@dataclass
class BbMeanReversionConfig:
    timeframe: str = "1d"
    lookback_bars: int = 250
    bb_period: int = 20
    bb_std: float = 2.0
    min_bars: int = 40
    er_hard_block: float = 0.65  # above this Efficiency Ratio, market is trending too cleanly to fade at all
    er_soft_ceiling: float = 0.42  # above this (but below hard block), confidence penalty rather than a block
    squeeze_pctile_floor: float = 15.0  # bandwidth percentile below which it's a tight squeeze, not a genuine stretch
    rsi_overbought: float = 65.0
    rsi_oversold: float = 35.0
    zone_tolerance_pct: float = 1.2  # how close price must be to an independent S/R zone to count as confluence
    sl_atr_mult: float = 0.4  # stop buffer beyond the band edge, in ATR
    min_rr: float = 1.3


def _build_chart_data(df: pd.DataFrame, max_bars: int = 260) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    view = df.iloc[-max_bars:] if len(df) > max_bars else df
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


def _bb_band_series(df: pd.DataFrame, period: int, std_mult: float, max_bars: int = 260) -> dict[str, list[dict[str, Any]]]:
    """Full rolling upper/mid/lower band series (not just the latest bar) so
    the chart can draw the actual bands, not a single flat reference line."""
    closes = df["close"]
    mid = closes.rolling(period).mean()
    std = closes.rolling(period).std()
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    view = df.iloc[-max_bars:] if len(df) > max_bars else df
    out: dict[str, list[dict[str, Any]]] = {"upper": [], "mid": [], "lower": []}
    for idx in view.index:
        if pd.isna(mid.loc[idx]):
            continue
        t = str(idx)
        out["upper"].append({"time": t, "value": round(float(upper.loc[idx]), 6)})
        out["mid"].append({"time": t, "value": round(float(mid.loc[idx]), 6)})
        out["lower"].append({"time": t, "value": round(float(lower.loc[idx]), 6)})
    return out


def _bandwidth_percentile(df: pd.DataFrame, period: int, std_mult: float, window: int = 100) -> float | None:
    """Where today's Bollinger Bandwidth ((upper-lower)/mean) ranks against
    its own recent history — a genuine institutional "BandWidth" percentile
    read, not an absolute threshold that would need re-tuning per instrument."""
    closes = df["close"]
    mid = closes.rolling(period).mean()
    std = closes.rolling(period).std()
    bandwidth = (2 * std_mult * std / mid.replace(0, pd.NA)).dropna()
    if bandwidth.empty:
        return None
    recent = bandwidth.iloc[-window:]
    if len(recent) < 20:
        return None
    current = float(bandwidth.iloc[-1])
    pctile = float((recent < current).mean() * 100)
    return round(pctile, 1)


def _near_zone(price: float, zone: dict[str, Any] | None, side: str, tol_pct: float) -> bool:
    if not zone or not price:
        return False
    edge = zone["top"] if side == "support" else zone["bottom"]
    return abs(price - edge) / price * 100 <= tol_pct


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: BbMeanReversionConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or BbMeanReversionConfig()
    out: dict[str, Any] = {
        "ticker": ticker,
        "strategy": STRATEGY_NAME,
        "timeframe": cfg.timeframe,
        "error": None,
        "take_trade": False,
        "signal": "NEUTRAL",
        "direction": "NONE",
        "verdict": "No read yet",
        "confidence_pct": None,
        "grade": None,
        "sl_pct": None,
        "tp_pct": None,
        "chart_data": [],
        "bb_upper": [],
        "bb_mid": [],
        "bb_lower": [],
        "support_zone": None,
        "resistance_zone": None,
        "rules": [
            "Core read: Bollinger %B — how stretched price is beyond its 20-bar, 2σ bands.",
            "Regime filter: Kaufman Efficiency Ratio blocks the trade entirely when the market is "
            "trending too cleanly to fade (mean reversion needs range-bound/choppy conditions).",
            "Confirmation layer: RSI extreme, a reversal candlestick pattern at the band, a volume "
            "climax on the reversal bar, and an independent swing Support/Resistance zone nearby — "
            "each adds to confidence, none is required alone.",
            "Target is the mean (middle band); stop sits just beyond the band edge, sanity-checked "
            "against ATR so it isn't tighter than the instrument's real noise or wider than a real stop.",
        ],
    }

    try:
        df = fetch_data_for_gap_scan(
            ticker, cfg.timeframe, market, groww_token=groww_token, exchange=exchange, limit=cfg.lookback_bars,
        )
    except Exception as exc:
        out["error"] = f"Data fetch failed: {exc}"
        return out

    df = normalize_ohlcv(df)
    if df is None or df.empty or len(df) < max(cfg.min_bars, cfg.bb_period + 5):
        out["error"] = "Insufficient OHLCV for BB Mean Reversion analysis"
        return out

    bb = detect_bollinger_mean_reversion(df, period=cfg.bb_period, std_mult=cfg.bb_std)
    if bb is None:
        out["error"] = "Could not compute Bollinger Bands"
        return out

    entry = float(df["close"].iloc[-1])
    out["ltp"] = round(entry, 6)
    out["bars"] = len(df)
    out["chart_data"] = _build_chart_data(df)
    bands = _bb_band_series(df, cfg.bb_period, cfg.bb_std)
    out["bb_upper"], out["bb_mid"], out["bb_lower"] = bands["upper"], bands["mid"], bands["lower"]
    out["percent_b"] = bb["percent_b"]
    out["bb_mean"] = bb["mean"]
    out["bb_upper_now"] = bb["upper"]
    out["bb_lower_now"] = bb["lower"]

    try:
        sr_cfg = PaVpSmcConfig(swing_window=5, lookback_bars=min(len(df), 300))
        sr_zones = find_swing_sr_zones(df, sr_cfg)
    except Exception:
        sr_zones = {}
    support = sr_zones.get("support")
    resistance = sr_zones.get("resistance")
    out["support_zone"] = [round(support["bottom"], 6), round(support["top"], 6)] if support else None
    out["resistance_zone"] = [round(resistance["bottom"], 6), round(resistance["top"], 6)] if resistance else None

    if bb["signal"] == "none":
        out["verdict"] = f"Price inside its Bollinger Bands (%B {bb['percent_b']:.2f}) — not stretched enough for a mean-reversion read."
        out["plain_english"] = f"SIGNAL: NEUTRAL. {out['verdict']} Nothing to trade here."
        return out

    direction = "LONG" if bb["signal"] == "bullish" else "SHORT"
    is_long = direction == "LONG"

    er_series = kaufman_efficiency_ratio(df["close"], 14).dropna()
    er_val = float(er_series.iloc[-1]) if not er_series.empty else 0.5

    if er_val >= cfg.er_hard_block:
        out["direction"] = direction
        out["signal"] = "BULLISH" if is_long else "BEARISH"
        out["verdict"] = (
            f"Price is stretched to %B {bb['percent_b']:.2f}, but Efficiency Ratio ({er_val:.2f}) shows the "
            "market is trending too cleanly to fade right now — mean reversion needs range-bound/choppy "
            "conditions, and this isn't one. Blocked."
        )
        out["plain_english"] = (
            f"SIGNAL: WAIT (blocked). {out['verdict']} Trading against a clean trend by fading the band here "
            "is a classic way to get run over as the band simply walks with price."
        )
        return out

    bw_pctile = _bandwidth_percentile(df, cfg.bb_period, cfg.bb_std)
    is_squeeze = bw_pctile is not None and bw_pctile <= cfg.squeeze_pctile_floor

    rsi_series = _rsi_ind(df["close"], 14).dropna()
    rsi_val = float(rsi_series.iloc[-1]) if not rsi_series.empty else None
    rsi_confirms = rsi_val is not None and ((is_long and rsi_val <= cfg.rsi_oversold) or (not is_long and rsi_val >= cfg.rsi_overbought))

    patterns = detect_candlestick_patterns(df, lookback=3)
    want_dir = "bullish" if is_long else "bearish"
    matched_pattern = next((p for p in patterns if p.get("direction") == want_dir and p.get("bars_ago", 99) <= 1), None)

    vz_series = volume_zscore(df["volume"], 20).dropna() if "volume" in df.columns else pd.Series(dtype=float)
    vz_val = float(vz_series.iloc[-1]) if not vz_series.empty else None
    vol_climax = vz_val is not None and vz_val >= 1.5

    zone_confluence = _near_zone(entry, support, "support", cfg.zone_tolerance_pct) if is_long else _near_zone(entry, resistance, "resistance", cfg.zone_tolerance_pct)

    atr_series = _atr_ind(df, 14)
    atr_val = float(atr_series.iloc[-1]) if pd.notna(atr_series.iloc[-1]) else entry * 0.01
    band_edge = bb["lower"] if is_long else bb["upper"]
    raw_stop = band_edge - atr_val * cfg.sl_atr_mult if is_long else band_edge + atr_val * cfg.sl_atr_mult
    raw_target = bb["mean"]
    stop, target, stop_adjusted = atr_sane_stop_target(direction, entry, raw_stop, raw_target, atr_val)

    sl_pct, tp_pct = sl_tp_pct(direction, entry, stop, target)
    rr = rr_ratio(sl_pct, tp_pct)

    score = ConfidenceScore(
        40, f"Price stretched to %B {bb['percent_b']:.2f} beyond its {cfg.bb_period}-bar Bollinger Band — a "
        "classic mean-reversion setup",
    )
    score.add(
        er_val <= cfg.er_soft_ceiling, 12,
        f"Market is genuinely range-bound (Efficiency Ratio {er_val:.2f}) — good conditions to fade a stretch",
        f"Efficiency Ratio {er_val:.2f} shows some trending character — fading is riskier here, though not blocked",
    )
    score.add(
        not is_squeeze, 6,
        "Bands aren't in a tight squeeze — this stretch has real room to revert" if bw_pctile is not None else "",
        f"Bands are in a tight squeeze (bandwidth at the {bw_pctile:.0f}th percentile of recent history) — a "
        "breakout is arguably as likely as a reversion from here" if bw_pctile is not None else None,
    )
    score.add(
        rsi_confirms, 10,
        f"RSI ({rsi_val:.0f}) confirms the {'oversold' if is_long else 'overbought'} extreme",
        f"RSI ({rsi_val:.0f}) doesn't confirm the extreme as strongly" if rsi_val is not None else "RSI unavailable",
    )
    score.add(
        matched_pattern is not None, 12,
        f"{matched_pattern['name']} reversal candle confirms the turn" if matched_pattern else "",
        "No confirming reversal candlestick pattern at the band yet — the stretch alone isn't enough",
    )
    score.add(
        vol_climax, 8,
        f"Volume climax on the reversal bar ({vz_val:.1f}σ above average) — real participation behind the turn" if vz_val is not None else "",
        "No volume climax — the reversal lacks a participation spike" if vz_val is not None else "Volume data unavailable",
    )
    score.add(
        zone_confluence, 10,
        f"Band touch coincides with an independent swing {'Support' if is_long else 'Resistance'} zone — extra confluence",
        f"No independent swing {'Support' if is_long else 'Resistance'} zone confirming this level",
    )
    score.add(
        rr is not None and rr >= cfg.min_rr, 8,
        f"Reward:risk of {rr:.1f}:1 clears the {cfg.min_rr:g}:1 floor" if rr else "",
        "Reward:risk is thin for this setup",
    )
    confidence_pct, reasons = score.finalize()

    liquidity = liquidity_ok(vz_val)
    grade = quality_grade(confidence_pct, rr, liquidity, stop_adjusted)

    out.update({
        "take_trade": True,
        "direction": direction,
        "signal": "BULLISH" if is_long else "BEARISH",
        "verdict": f"%B {bb['percent_b']:.2f} stretch confirmed — {'bounce' if is_long else 'pullback'} toward the mean expected",
        "entry_price": round(entry, 6),
        "stop_price": round(stop, 6) if stop is not None else None,
        "target_price": round(target, 6) if target is not None else None,
        "sl_pct": sl_pct,
        "tp_pct": tp_pct,
        "rr": rr,
        "confidence_pct": confidence_pct,
        "confidence_reasons": reasons,
        "grade": grade,
        "efficiency_ratio": round(er_val, 3),
        "bandwidth_percentile": bw_pctile,
        "is_squeeze": is_squeeze,
        "rsi": round(rsi_val, 1) if rsi_val is not None else None,
        "volume_zscore": round(vz_val, 2) if vz_val is not None else None,
        "matched_pattern": matched_pattern["name"] if matched_pattern else None,
        "zone_confluence": zone_confluence,
        "stop_adjusted_for_atr": stop_adjusted,
    })
    out["plain_english"] = _explain(out, cfg)
    return out


def _explain(out: dict[str, Any], cfg: BbMeanReversionConfig) -> str:
    signal = out.get("signal", "NEUTRAL")
    direction = out.get("direction", "NONE")
    conf = out.get("confidence_pct")
    sl, tp, rr = out.get("sl_pct"), out.get("tp_pct"), out.get("rr")

    plan = [f"SIGNAL: {signal}" + (f" ({direction})" if direction != "NONE" else "")]
    if conf is not None:
        plan.append(f"confidence {conf:.0f}%")
    if sl is not None and tp is not None:
        rr_note = f" (reward:risk 1:{rr:g})" if rr else ""
        plan.append(f"SL {sl:.1f}% · TP {tp:.1f}%{rr_note}")
    plan_line = " — ".join(plan)

    is_long = direction == "LONG"
    verb = "bounce back up toward" if is_long else "pull back down toward"
    parts = [
        f"{plan_line}. {out['ticker']} on {out['timeframe']} has stretched {'below' if is_long else 'above'} its "
        f"normal trading range (Bollinger %B {out.get('percent_b', 0):.2f}) — statistically, moves this stretched "
        f"tend to {verb} the {cfg.bb_period}-bar average rather than keep extending.",
    ]
    checks = []
    if out.get("rsi") is not None:
        checks.append(f"RSI at {out['rsi']:.0f}")
    if out.get("matched_pattern"):
        checks.append(f"a {out['matched_pattern']} reversal candle")
    if out.get("volume_zscore") is not None and out["volume_zscore"] >= 1.5:
        checks.append("a volume spike on the turn")
    if out.get("zone_confluence"):
        checks.append("an independent support/resistance level right here")
    if checks:
        parts.append("Backing this up: " + ", ".join(checks) + ".")
    else:
        parts.append(
            "No independent confirmation (RSI/candlestick/volume/S-R) lines up yet — this is the stretch alone, "
            "a lower-conviction version of the setup."
        )
    if out.get("is_squeeze"):
        parts.append(
            "Caution: the bands are unusually tight right now (a squeeze) — squeezes often resolve with a sharp "
            "breakout rather than a gentle reversion, so this setup carries extra risk of being wrong-footed."
        )
    return " ".join(parts)


def scan_universe(
    tickers: list[str],
    timeframes: list[str],
    market: str,
    *,
    cfg_base: BbMeanReversionConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg_base = cfg_base or BbMeanReversionConfig()
    timeframes = timeframes or [cfg_base.timeframe]
    results: list[dict[str, Any]] = []
    for tf in timeframes:
        cfg = replace(cfg_base, timeframe=tf)
        for t in tickers:
            try:
                results.append(analyze_ticker(t, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
            except Exception as exc:
                logger.exception("BB Mean Reversion failed for %s (%s)", t, tf)
                results.append({"ticker": t, "timeframe": tf, "error": str(exc)[:300], "take_trade": False})

    entries = [r for r in results if not r.get("error") and r.get("take_trade")]
    entries.sort(key=lambda r: -(r.get("confidence_pct") or 0))

    return {
        "strategy": STRATEGY_NAME,
        "results": results,
        "entries": entries,
        "entry_count": len(entries),
        "scanned": len(results),
        "config": {
            "timeframes": timeframes,
            "lookback_bars": cfg_base.lookback_bars,
            "bb_period": cfg_base.bb_period,
            "bb_std": cfg_base.bb_std,
        },
        "disclaimer": (
            "Mean-reversion setups can fail hard in strong trends even after passing every filter here — "
            "this is a structured, transparent framework, not a guaranteed edge. Research / education only, "
            "not financial advice."
        ),
    }
