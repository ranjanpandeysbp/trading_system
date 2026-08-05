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

On top of that base read, the user can opt into up to 13 additional
institutional-grade confluence checks (EXTRA_CHECK_OPTIONS below) — each one
independently reused from an existing engine/indicator elsewhere in this app
(Fibonacci, EMA stack/crossover, Stochastic RSI, VWAP, Volume Profile, Smart
Money order blocks, chart-pattern/RSI-divergence reversal, MACD, classic
Support/Resistance, same-timeframe ADX trend direction/strength, a genuine
higher-timeframe MTF Trend & Strength read (mtf_trend_strength_engine), and a
broader candlestick + chart-pattern scan). None is required; selecting more
simply raises the ceiling on how much independent evidence can back a single
trade idea, exactly like a real desk building conviction from several
unrelated reads rather than one indicator alone.

Works across all 4 asset classes (india/us/crypto/commodity) via
gap_trading.fetch_data_for_gap_scan, and scans one or more timeframes across
one or more tickers via scan_universe.

Research / education only — not financial advice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import Any

import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.pa_vp_smc_engine import PaVpSmcConfig, find_swing_sr_zones
from app.market_pulse.pro_trade_shared import (
    ConfidenceScore,
    atr as _atr_ind,
    atr_sane_stop_target,
    build_pro_trade_ai_context,
    kaufman_efficiency_ratio,
    liquidity_ok,
    pro_trade_ai_system,
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

# Optional, user-selectable extra confluence factors — none required, each
# adds independent evidence on top of the core %B/regime/RSI/candlestick/
# volume read. Every one reuses an existing indicator/engine in this app
# rather than re-deriving the math.
EXTRA_CHECK_OPTIONS: list[dict[str, str]] = [
    {"value": "fibonacci", "label": "Fibonacci retracement"},
    {"value": "ema_position", "label": "EMA position (20/50 stack)"},
    {"value": "ema_crossover", "label": "EMA crossover (9/21)"},
    {"value": "stochastic_rsi", "label": "Stochastic RSI"},
    {"value": "vwap", "label": "VWAP"},
    {"value": "volume_profile", "label": "Volume Profile (POC/VAH/VAL)"},
    {"value": "smart_money", "label": "Smart Money (Order Blocks)"},
    {"value": "reversal_strategy", "label": "Reversal strategy (chart pattern + divergence)"},
    {"value": "macd", "label": "MACD"},
    {"value": "support_resistance", "label": "Support & Resistance zone"},
    {"value": "trend_direction_strength", "label": "Trend direction & strength (ADX)"},
    {"value": "mtf_trend_strength", "label": "MTF Trend & Strength"},
    {"value": "candlestick_chart_patterns", "label": "Candlestick & Chart Patterns"},
]

# For the MTF Trend & Strength check — which HIGHER timeframe to read the
# broader trend from, keyed by the scan's own timeframe. Deliberately one
# rung up (not the same timeframe again, which trend_direction_strength
# already covers) so it's a genuine multi-timeframe read: does the bigger
# picture agree with fading this stretch, or is this reversal fighting a
# larger trend the current timeframe alone can't see?
_MTF_HIGHER_TF: dict[str, str] = {
    "5m": "1h", "15m": "4h", "30m": "4h", "1h": "1d", "4h": "1d", "1d": "1w", "1wk": "1w",
}
_EXTRA_CHECK_POINTS = 6.0


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
    extra_checks: list[str] = field(default_factory=list)  # opt-in extras from EXTRA_CHECK_OPTIONS


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


def _stoch_rsi(close: pd.Series, rsi_period: int = 14, stoch_period: int = 14) -> pd.Series:
    """Stochastic RSI — the Stochastic oscillator's formula applied to RSI
    instead of price, giving a more sensitive (and more prone to whipsaw)
    overbought/oversold read than raw RSI. 0-1 scale."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / rsi_period, min_periods=rsi_period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / rsi_period, min_periods=rsi_period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-12)
    rsi = 100 - (100 / (1 + rs))
    lo = rsi.rolling(stoch_period).min()
    hi = rsi.rolling(stoch_period).max()
    return ((rsi - lo) / (hi - lo).replace(0, pd.NA)).clip(0, 1)


def _ema_crossover_recent(df: pd.DataFrame, fast: int = 9, slow: int = 21, lookback: int = 5) -> str | None:
    """Whether the fast/slow EMA pair crossed within the last `lookback`
    bars — a fresh crossover, not a stale one from many bars ago."""
    ema_f = df["close"].ewm(span=fast, adjust=False).mean()
    ema_s = df["close"].ewm(span=slow, adjust=False).mean()
    diff = (ema_f - ema_s).iloc[-lookback:]
    if len(diff) < 2:
        return None
    sign = diff.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    if sign.iloc[0] <= 0 and sign.iloc[-1] > 0:
        return "bullish"
    if sign.iloc[0] >= 0 and sign.iloc[-1] < 0:
        return "bearish"
    return None


def _apply_extra_checks(
    score: ConfidenceScore,
    df: pd.DataFrame,
    entry: float,
    direction: str,
    is_long: bool,
    checks: list[str],
    support: dict[str, Any] | None,
    resistance: dict[str, Any] | None,
    zone_tolerance_pct: float,
    *,
    ticker: str = "",
    market: str = "",
    timeframe: str = "",
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    """Applies each user-selected extra confluence factor to `score` in
    place and returns a detail dict (raw values) for display — every check
    here is optional, additive evidence on top of the core %B/regime/RSI/
    candlestick/volume read, and every one reuses an existing indicator or
    engine already proven elsewhere in this app rather than re-deriving the
    math from scratch. `ticker`/`market`/`timeframe`/`groww_token`/`exchange`
    are only needed by checks that fetch their own separate data (currently
    just mtf_trend_strength, which reads a HIGHER timeframe than the one
    being scanned)."""
    detail: dict[str, Any] = {}
    checks_set = set(checks or [])
    pts = _EXTRA_CHECK_POINTS

    if "fibonacci" in checks_set:
        from app.market_pulse.indicators import add_fib_levels

        lookback = min(100, len(df))
        fdf = add_fib_levels(df.copy(), lookback=lookback)
        last = fdf.iloc[-1]
        levels = [last.get(f"fib_{r}_{lookback}") for r in ("0.236", "0.382", "0.5", "0.618", "0.786")]
        levels = [float(v) for v in levels if v is not None and pd.notna(v)]
        near = bool(levels) and entry > 0 and any(abs(entry - lv) / entry * 100 <= zone_tolerance_pct for lv in levels)
        detail["fibonacci"] = {"near_level": near}
        score.add(
            near, pts,
            "Price sits right at a Fibonacci retracement level — extra confluence",
            "No Fibonacci retracement level near this price",
        )

    if "ema_position" in checks_set:
        from app.market_pulse.pa_vp_smc_engine import classify_trend

        trend = classify_trend(df)
        aligned = (is_long and trend.get("trend") == "bullish") or (not is_long and trend.get("trend") == "bearish")
        detail["ema_position"] = trend
        score.add(
            aligned, pts,
            f"EMA stack is {trend.get('trend')} — this reads as a pullback {'buy' if is_long else 'sell'} within "
            "the larger trend, not a pure counter-trend fade",
            f"EMA stack is {trend.get('trend', 'mixed')} — doesn't support trading with the larger trend here",
        )

    if "ema_crossover" in checks_set:
        cross = _ema_crossover_recent(df)
        confirms = (is_long and cross == "bullish") or (not is_long and cross == "bearish")
        detail["ema_crossover"] = cross
        score.add(
            confirms, pts,
            f"9/21 EMA {cross} crossover just fired — short-term momentum turning the same way",
            "No recent 9/21 EMA crossover confirming the turn",
        )

    if "stochastic_rsi" in checks_set:
        srsi = _stoch_rsi(df["close"]).dropna()
        srsi_val = float(srsi.iloc[-1]) if not srsi.empty else None
        confirms = srsi_val is not None and ((is_long and srsi_val <= 0.2) or (not is_long and srsi_val >= 0.8))
        detail["stochastic_rsi"] = round(srsi_val, 3) if srsi_val is not None else None
        score.add(
            confirms, pts,
            f"Stochastic RSI ({srsi_val:.2f}) confirms the {'oversold' if is_long else 'overbought'} extreme" if srsi_val is not None else "",
            f"Stochastic RSI ({srsi_val:.2f}) doesn't confirm the extreme" if srsi_val is not None else "Stochastic RSI unavailable",
        )

    if "vwap" in checks_set:
        from app.market_pulse.indicators import add_vwap

        vdf = add_vwap(df.copy())
        last_vwap = vdf["vwap"].iloc[-1]
        vwap_val = float(last_vwap) if pd.notna(last_vwap) else None
        confirms = vwap_val is not None and ((is_long and entry < vwap_val) or (not is_long and entry > vwap_val))
        detail["vwap"] = round(vwap_val, 6) if vwap_val is not None else None
        score.add(
            confirms, pts,
            f"Price is {'below' if is_long else 'above'} VWAP ({vwap_val:,.4g}) — room to revert back toward volume-weighted fair value" if vwap_val is not None else "",
            "Price is already on the richer side of VWAP for this trade direction" if vwap_val is not None else "VWAP unavailable",
        )

    if "volume_profile" in checks_set:
        from app.market_pulse.volume_profile_ce_engine import calculate_volume_profile

        try:
            poc, vah, val, _vp = calculate_volume_profile(df, num_bins=40, value_area_pct=0.70)
        except Exception:
            poc = vah = val = None
        confirms = False
        note = "Volume profile unavailable"
        if poc is not None:
            if is_long and val is not None and entry <= val * (1 + zone_tolerance_pct / 100):
                confirms, note = True, f"Price is at/below the Value Area Low ({val:,.4g}) — cheap relative to where most volume traded"
            elif not is_long and vah is not None and entry >= vah * (1 - zone_tolerance_pct / 100):
                confirms, note = True, f"Price is at/above the Value Area High ({vah:,.4g}) — rich relative to where most volume traded"
            else:
                note = "Price isn't at the value-area edge in this trade's direction"
        detail["volume_profile"] = {"poc": poc, "vah": vah, "val": val}
        score.add(confirms, pts, note if confirms else "", note if not confirms else "")

    if "smart_money" in checks_set:
        from app.market_pulse.pa_vp_smc_engine import PaVpSmcConfig as _ObCfg
        from app.market_pulse.pa_vp_smc_engine import detect_order_blocks

        try:
            blocks = detect_order_blocks(df, _ObCfg(lookback_bars=min(len(df), 300)))
        except Exception:
            blocks = []
        wanted = "bullish" if is_long else "bearish"
        matched_ob = next(
            (
                b for b in blocks
                if b["type"] == wanted and (
                    b["bottom"] <= entry <= b["top"]
                    or abs(entry - (b["bottom"] if is_long else b["top"])) / entry * 100 <= zone_tolerance_pct
                )
            ),
            None,
        )
        detail["smart_money"] = matched_ob
        score.add(
            matched_ob is not None, pts,
            f"Price is at an unmitigated {wanted} Order Block ({matched_ob['bottom']:,.4g}-{matched_ob['top']:,.4g}) — institutional footprint here" if matched_ob else "",
            "No unmitigated Smart Money order block near this price",
        )

    if "reversal_strategy" in checks_set:
        from app.trading_hubs.support_resistance_engine import SupportResistanceConfig, detect_chart_patterns, detect_rsi_divergence

        sr_cfg2 = SupportResistanceConfig()
        try:
            chart_patterns = detect_chart_patterns(df, sr_cfg2)
        except Exception:
            chart_patterns = []
        want_dir = "bullish" if is_long else "bearish"
        matched_chart = next((p for p in chart_patterns if p.get("direction") == want_dir), None)
        try:
            divergences = detect_rsi_divergence(df, _rsi_ind(df["close"], 14), sr_cfg2)
        except Exception:
            divergences = []
        matched_div = next((d for d in divergences if d.get("direction") == want_dir), None)
        confirms = matched_chart is not None or matched_div is not None
        detail["reversal_strategy"] = {
            "chart_pattern": matched_chart["name"] if matched_chart else None,
            "divergence": matched_div["name"] if matched_div else None,
        }
        note_true = ", ".join(x for x in [
            matched_chart["name"] if matched_chart else None,
            matched_div["name"] if matched_div else None,
        ] if x)
        score.add(
            confirms, pts,
            f"Independent reversal signal confirms: {note_true}" if note_true else "",
            "No chart-pattern reversal (double top/bottom) or RSI divergence confirming this turn",
        )

    if "macd" in checks_set:
        from app.market_pulse.indicators import add_macd

        mdf = add_macd(df.copy())
        hist_col = next((c for c in mdf.columns if c.startswith("macd_hist_")), None)
        hist = mdf[hist_col].dropna() if hist_col else pd.Series(dtype=float)
        confirms = False
        if len(hist) >= 2:
            rising = bool(hist.iloc[-1] > hist.iloc[-2])
            confirms = (is_long and rising) or (not is_long and not rising)
        detail["macd_histogram"] = round(float(hist.iloc[-1]), 6) if not hist.empty else None
        score.add(
            confirms, pts,
            "MACD histogram is turning the same way as this trade — an early momentum shift",
            "MACD histogram doesn't yet confirm a momentum shift",
        )

    if "support_resistance" in checks_set:
        near = _near_zone(entry, support, "support", zone_tolerance_pct) if is_long else _near_zone(entry, resistance, "resistance", zone_tolerance_pct)
        detail["support_resistance"] = near
        score.add(
            near, pts,
            f"Band touch coincides with an independent swing {'Support' if is_long else 'Resistance'} zone — extra confluence",
            f"No independent swing {'Support' if is_long else 'Resistance'} zone confirming this level",
        )

    if "trend_direction_strength" in checks_set:
        from app.market_pulse.indicators import add_adx

        adf = add_adx(df.copy(), 14)
        plus_di = adf["plus_di_14"].dropna()
        minus_di = adf["minus_di_14"].dropna()
        adx_series = adf["adx_14"].dropna()
        adx_val = float(adx_series.iloc[-1]) if not adx_series.empty else None
        trend_dir = None
        if not plus_di.empty and not minus_di.empty:
            trend_dir = "up" if float(plus_di.iloc[-1]) > float(minus_di.iloc[-1]) else "down"
        confirms = (is_long and trend_dir == "up") or (not is_long and trend_dir == "down")
        detail["trend_direction_strength"] = {"direction": trend_dir, "adx": round(adx_val, 1) if adx_val is not None else None}
        score.add(
            confirms, pts,
            f"Larger trend direction ({trend_dir}, ADX {adx_val:.0f}) supports this as a with-trend pullback, not a pure counter-trend bet" if trend_dir and adx_val is not None else "",
            "Larger trend direction doesn't support this as a with-trend pullback" if trend_dir else "Trend direction unavailable",
        )

    if "candlestick_chart_patterns" in checks_set:
        from app.trading_hubs.support_resistance_engine import SupportResistanceConfig, detect_chart_patterns

        want_dir = "bullish" if is_long else "bearish"
        try:
            wider_candles = detect_candlestick_patterns(df, lookback=5)
        except Exception:
            wider_candles = []
        matched_candle = next((p for p in wider_candles if p.get("direction") == want_dir and p.get("bars_ago", 99) <= 3), None)
        try:
            chart_patterns2 = detect_chart_patterns(df, SupportResistanceConfig())
        except Exception:
            chart_patterns2 = []
        matched_chart2 = next((p for p in chart_patterns2 if p.get("direction") == want_dir), None)
        confirms = matched_candle is not None or matched_chart2 is not None
        detail["candlestick_chart_patterns"] = {
            "candlestick": matched_candle["name"] if matched_candle else None,
            "chart_pattern": matched_chart2["name"] if matched_chart2 else None,
        }
        note_bits = ", ".join(x for x in [
            f"{matched_candle['name']} candle {matched_candle['bars_ago']} bar(s) ago" if matched_candle else None,
            matched_chart2["name"] if matched_chart2 else None,
        ] if x)
        score.add(
            confirms, pts,
            f"Candlestick/chart pattern backs this up: {note_bits} — visible, well-known price-action signature at this level" if note_bits else "",
            "No recognizable candlestick or chart pattern (Hammer, Engulfing, Double Top/Bottom, etc.) confirming this turn",
        )

    if "mtf_trend_strength" in checks_set:
        higher_tf = _MTF_HIGHER_TF.get(timeframe, "")
        mtf_result: dict[str, Any] | None = None
        if higher_tf and ticker and market:
            try:
                from app.market_pulse.mtf_trend_strength_engine import analyze_ticker_timeframe

                mtf_result = analyze_ticker_timeframe(
                    ticker, higher_tf, market, groww_token=groww_token, exchange=exchange, limit=300,
                )
            except Exception as exc:
                logger.debug("MTF Trend & Strength check failed for %s (%s): %s", ticker, higher_tf, exc)
                mtf_result = None
        mtf_dir = mtf_result.get("direction") if mtf_result and not mtf_result.get("error") else None
        strength_label = mtf_result.get("strength_label") if mtf_result else None
        strength_score = mtf_result.get("strength_score") if mtf_result else None
        reversal_pct = mtf_result.get("reversal_probability_pct") if mtf_result else None
        aligned = (is_long and mtf_dir == "LONG") or (not is_long and mtf_dir == "SHORT")
        strong_enough = strength_label in ("Moderate", "Strong", "Very Strong")
        confirms = bool(mtf_dir) and aligned and strong_enough
        detail["mtf_trend_strength"] = {
            "higher_timeframe": higher_tf or None,
            "direction": mtf_dir,
            "strength_label": strength_label,
            "strength_score": strength_score,
            "reversal_probability_pct": reversal_pct,
        }
        if mtf_dir:
            explain_true = (
                f"On the higher {higher_tf} timeframe, the broader trend is {mtf_dir} with {strength_label or 'unclear'} "
                f"strength ({strength_score:.0f}/100 if available) — this reversal reads as a with-trend pullback in the "
                "bigger picture, not an isolated counter-trend bet, which is the higher-probability version of a mean-"
                "reversion trade"
            )
            if mtf_dir == "NEUTRAL":
                explain_false = (
                    f"On the higher {higher_tf} timeframe there's no clear trend either way — this reversal has "
                    "no bigger-picture tailwind behind it, though it isn't fighting one either"
                )
            elif aligned and not strong_enough:
                explain_false = (
                    f"The higher {higher_tf} timeframe trend does point the same way, but only at {strength_label} "
                    "strength — too weak to lean on as real bigger-picture support for this trade"
                )
            else:
                explain_false = (
                    f"On the higher {higher_tf} timeframe, the broader trend is {mtf_dir} — the opposite direction "
                    "to this trade, so this reversal would be fighting the bigger picture rather than riding it"
                )
        else:
            explain_true, explain_false = "", f"MTF Trend & Strength read unavailable on the {higher_tf or 'higher'} timeframe"
        score.add(confirms, pts, explain_true, explain_false)

    return detail


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
            "Confirmation layer: RSI extreme, a reversal candlestick pattern at the band, and a volume "
            "climax on the reversal bar — each adds to confidence, none is required alone.",
            "Optional extra confluence (pick any): Fibonacci, EMA position/crossover, Stochastic RSI, "
            "VWAP, Volume Profile, Smart Money order blocks, chart-pattern/divergence reversal, MACD, "
            "Support & Resistance, same-timeframe ADX trend direction/strength, a genuine higher-"
            "timeframe MTF Trend & Strength read, and a broader candlestick/chart-pattern scan — each "
            "selected factor adds further independent evidence on top of the core read.",
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
        rr is not None and rr >= cfg.min_rr, 8,
        f"Reward:risk of {rr:.1f}:1 clears the {cfg.min_rr:g}:1 floor" if rr else "",
        "Reward:risk is thin for this setup",
    )

    extra_detail = _apply_extra_checks(
        score, df, entry, direction, is_long, cfg.extra_checks, support, resistance, cfg.zone_tolerance_pct,
        ticker=ticker, market=market, timeframe=cfg.timeframe, groww_token=groww_token, exchange=exchange,
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
        "extra_checks_applied": list(cfg.extra_checks or []),
        "extra_checks_detail": extra_detail,
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
    extras = out.get("extra_checks_applied") or []
    if extras:
        parts.append(
            f"{len(extras)} optional confluence check(s) selected ({', '.join(extras)}) — see the confidence "
            "reasons below for exactly which ones lined up with this trade and which didn't."
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


BB_MEAN_REVERSION_AI_SYSTEM = pro_trade_ai_system(
    "BB Mean Reversion",
    "Price stretched beyond a Bollinger Band (%B extreme) is scored for a mean-reversion trade back "
    "toward the band's middle line, using Kaufman Efficiency Ratio (is the market actually range-bound?), "
    "band-squeeze detection, RSI, and up to 13 optional user-selected confluence checks (Fibonacci, EMA "
    "position/crossover, Stochastic RSI, VWAP, Volume Profile, Smart Money order blocks, reversal-strategy "
    "patterns, MACD, Support/Resistance, trend direction & strength, higher-timeframe MTF trend & "
    "strength, and candlestick/chart patterns) — each opted-in check adds or withholds points, so the "
    "score is a transparent confluence tally, not a black box.",
)


def build_bb_mean_reversion_ai_prompt(result: dict[str, Any]) -> str:
    extra: list[str] = []
    applied = result.get("extra_checks_applied")
    if isinstance(applied, list) and applied:
        extra.append(f"Optional confluence checks applied: {', '.join(applied)}")
    if result.get("is_squeeze"):
        extra.append("Bollinger Bands are in a squeeze — breakout risk against the mean-reversion read.")
    if result.get("efficiency_ratio") is not None:
        extra.append(f"Kaufman Efficiency Ratio: {result.get('efficiency_ratio')} (near 1 = clean trend, near 0 = chop/range)")
    return build_pro_trade_ai_context(result, engine_label="BB Mean Reversion", extra_lines=extra or None)
