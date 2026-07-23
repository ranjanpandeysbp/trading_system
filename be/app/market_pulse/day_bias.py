"""
day_bias.py
-------------
"Chance of the next move being toward today's high vs today's low" — a
multi-factor read combining whatever price-action, volume, order-flow, and
support/resistance signals are available, instead of a single naive "where in
the day's range does price sit" percentage.

Two entry points, for two different data budgets:

- `quote_bias(...)` — for sections that only have a single live quote per
  ticker (e.g. a heatmap scanning hundreds of tickers, where fetching full
  OHLCV per ticker would be too expensive). Uses range position, today's
  candle direction (vs open), change vs previous close, order-book buy/sell
  imbalance, and proximity to the exchange circuit band — all pulled from the
  SAME quote call already being made, at zero extra network cost.

- `ohlcv_bias(...)` — for sections that already fetch full OHLCV per ticker
  (e.g. an indicator scan). Adds real technical-analysis weight: RSI
  positioning, ADX trend strength/direction, plus the same `pro_signals(...)`
  professional layer used by the Momentum Scanner / Quick Analyzer breakout
  lean — smart-money market structure, weak/strong support-resistance
  pressure, and an independent swing-based breakout/breakdown check. All
  zero extra network calls, since the OHLCV is already on hand for the scan
  itself.

`quote_bias` deliberately stays lighter — smart money structure and
weak/strong S/R both need historical bars to compute (swing detection), and
`quote_bias` exists specifically for sections scanning hundreds of tickers
off a single live quote each, where fetching OHLCV per ticker would defeat
the point. That's a data-budget tradeoff, not an oversight.

Both are heuristic syntheses of established technical-analysis signals, not a
statistically back-tested predictive model — treat the output as a
professional-style "read of the tape", not a guarantee.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

_NEUTRAL = {"up_pct": None, "down_pct": None, "direction": None, "reasons": []}


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _fmt_price(p: float) -> str:
    """Avoids scientific notation (e.g. "6.5e+04") for large prices like crypto."""
    if p >= 1000:
        return f"{p:,.2f}"
    return f"{p:.4g}"


def _combine(signals: list[tuple[float, float]], reasons: list[str]) -> dict[str, Any]:
    """signals: list of (value in [0,1] where 1=bullish/toward-high, weight)."""
    total_w = sum(w for _, w in signals)
    if total_w <= 0:
        return dict(_NEUTRAL)
    score = sum(v * w for v, w in signals) / total_w
    up_pct = round(_clip01(score) * 100, 1)
    down_pct = round(100.0 - up_pct, 1)
    direction = "UP" if up_pct > 50.0 else "DOWN" if up_pct < 50.0 else "NEUTRAL"
    return {"up_pct": up_pct, "down_pct": down_pct, "direction": direction, "reasons": reasons}


def _apply_volume_conviction(result: dict[str, Any], ratio: float | None) -> dict[str, Any]:
    """Volume doesn't set direction on its own — it confirms or tempers whatever
    the other signals already lean toward (a professional reads volume as
    conviction, not as a standalone directional tell)."""
    if result["up_pct"] is None or ratio is None:
        return result
    conviction = max(0.6, min(1.5, 0.5 + 0.5 * ratio))
    up = 50.0 + (result["up_pct"] - 50.0) * conviction
    up = round(_clip01(up / 100.0) * 100, 1)
    down = round(100.0 - up, 1)
    direction = "UP" if up > 50.0 else "DOWN" if up < 50.0 else "NEUTRAL"
    return {**result, "up_pct": up, "down_pct": down, "direction": direction}


def quote_bias(
    price: float | None, day_high: float | None, day_low: float | None, *,
    open_price: float | None = None, prev_close: float | None = None,
    volume: float | None = None, avg_volume: float | None = None,
    buy_qty: float | None = None, sell_qty: float | None = None,
    circuit_high: float | None = None, circuit_low: float | None = None,
) -> dict[str, Any]:
    if not price or not day_high or not day_low or day_high <= day_low:
        return dict(_NEUTRAL)

    rng = day_high - day_low
    signals: list[tuple[float, float]] = []
    reasons: list[str] = []

    pos = _clip01((price - day_low) / rng)
    signals.append((pos, 1.0))
    dominant = max(pos, 1 - pos)
    reasons.append(f"Trading in the {'upper' if pos >= 0.5 else 'lower'} {dominant * 100:.0f}% of today's range ({day_low:g}–{day_high:g}).")

    if open_price:
        candle = _clip01(0.5 + (price - open_price) / (2 * rng))
        signals.append((candle, 1.0))
        move_pct = (price - open_price) / open_price * 100
        reasons.append(f"{'Up' if move_pct >= 0 else 'Down'} {abs(move_pct):.2f}% from today's open — {'bullish' if move_pct >= 0 else 'bearish'} intraday candle so far.")

    if prev_close:
        chg_pct = (price - prev_close) / prev_close * 100
        norm = _clip01(0.5 + chg_pct / 6.0)
        signals.append((norm, 0.75))
        reasons.append(f"{'Up' if chg_pct >= 0 else 'Down'} {abs(chg_pct):.2f}% vs previous close.")

    if buy_qty and sell_qty and (buy_qty + sell_qty) > 0:
        flow = buy_qty / (buy_qty + sell_qty)
        signals.append((flow, 0.75))
        reasons.append(f"Order book: {flow * 100:.0f}% buy-side interest vs {(1 - flow) * 100:.0f}% sell-side.")

    if circuit_high and circuit_low and circuit_high > circuit_low:
        cpos = _clip01((price - circuit_low) / (circuit_high - circuit_low))
        signals.append((cpos, 0.5))

    result = _combine(signals, reasons)
    ratio = (volume / avg_volume) if volume and avg_volume and avg_volume > 0 else None
    if ratio is not None:
        reasons.append(f"Volume running at {ratio:.2f}x its recent average — {'confirms' if ratio >= 1.15 else 'below-average, tempers'} conviction in the move.")
    return _apply_volume_conviction(result, ratio)


def pro_signals(df: pd.DataFrame, price: float) -> dict[str, Any]:
    """Smart-money structure bias, weak/strong support-resistance pressure, and an
    independent swing-based breakout/breakdown check. Shared by `ohlcv_bias` below
    and by momentum_engine's breakout-lean scoring — every piece reuses this app's
    existing SMC + price-action + breakout engines on the SAME already-fetched
    OHLCV, no extra network calls. Failures in any one piece are non-fatal; the
    others still contribute. Returns {"up_adj": points on a 100-pt scale,
    "reasons": [...]}."""
    out: dict[str, Any] = {"up_adj": 0.0, "reasons": []}

    try:
        from app.trading_hubs.smc_engine.adapters import to_smc_ohlc
        from app.trading_hubs.smc_engine.models import Bias as SmcBias
        from app.trading_hubs.smc_engine.structure import current_bias, detect_structure_breaks, find_fractal_swings

        smc_df = to_smc_ohlc(df)
        if len(smc_df) >= 15:
            swings = find_fractal_swings(smc_df, 2)
            breaks = detect_structure_breaks(smc_df, swings)
            bias = current_bias(breaks)
            if bias == SmcBias.BULLISH:
                out["up_adj"] += 10.0
                out["reasons"].append("Smart money structure: bullish (latest break of structure to the upside).")
            elif bias == SmcBias.BEARISH:
                out["up_adj"] -= 10.0
                out["reasons"].append("Smart money structure: bearish (latest break of structure to the downside).")
    except Exception:
        pass

    try:
        from app.market_pulse.price_action import detect_support_resistance

        sr = detect_support_resistance(df)
        nearest_res = next((r for r in sr.get("resistances") or [] if price and abs(r["price"] - price) / price <= 0.03), None)
        if nearest_res:
            cap = min(15.0, nearest_res["touches"] * 3.0)
            out["up_adj"] -= cap
            out["reasons"].append(f"Resistance overhead at {_fmt_price(nearest_res['price'])} ({nearest_res['touches']}x tested) — caps the upside.")
        nearest_sup = next((s for s in sr.get("supports") or [] if price and abs(s["price"] - price) / price <= 0.03), None)
        if nearest_sup:
            cap = min(15.0, nearest_sup["touches"] * 3.0)
            out["up_adj"] += cap
            out["reasons"].append(f"Support underneath at {_fmt_price(nearest_sup['price'])} ({nearest_sup['touches']}x tested) — cushions the downside.")
    except Exception:
        pass

    try:
        from app.market_pulse.quick_analyzer_engine import detect_breakout_breakdown

        bo = detect_breakout_breakdown(df)
        event = bo.get("event", "NONE")
        vol_confirmed = bool(bo.get("volume_confirmed"))
        if event == "RESISTANCE_BREAKOUT":
            out["up_adj"] += 12.0 if vol_confirmed else 6.0
            out["reasons"].append(f"Already breaking out above swing resistance{' (volume-confirmed)' if vol_confirmed else ''}.")
        elif event == "SUPPORT_BREAKDOWN":
            out["up_adj"] -= 12.0 if vol_confirmed else 6.0
            out["reasons"].append(f"Already breaking down below swing support{' (volume-confirmed)' if vol_confirmed else ''}.")
    except Exception:
        pass

    return out


def ohlcv_bias(df: pd.DataFrame, price: float, day_high: float | None, day_low: float | None) -> dict[str, Any]:
    """Richer version for sections that already fetch full OHLCV for their own
    indicator scan — range position, RSI, ADX trend strength/direction, plus the
    `pro_signals` professional layer (smart money structure, weak/strong S/R,
    independent breakout/breakdown), then volume-vs-its-own-average as a
    conviction multiplier rather than a standalone directional vote."""
    from app.market_pulse.indicators import add_adx, add_rsi

    if df is None or df.empty or len(df) < 20:
        return dict(_NEUTRAL)

    signals: list[tuple[float, float]] = []
    reasons: list[str] = []

    if day_high and day_low and day_high > day_low:
        pos = _clip01((price - day_low) / (day_high - day_low))
        signals.append((pos, 1.0))
        dominant = max(pos, 1 - pos)
        reasons.append(f"Trading in the {'upper' if pos >= 0.5 else 'lower'} {dominant * 100:.0f}% of today's range.")

    try:
        work = add_rsi(df.copy(), 14)
        rsi = work["rsi_14"].iloc[-1] if "rsi_14" in work.columns else None
        if rsi is not None and pd.notna(rsi):
            rsi = float(rsi)
            signals.append((_clip01(rsi / 100.0), 1.0))
            zone = "overbought" if rsi >= 70 else "oversold" if rsi <= 30 else "neutral"
            reasons.append(f"RSI(14) at {rsi:.1f} ({zone}).")
    except Exception:
        pass

    try:
        work_adx = add_adx(df.copy(), 14)
        adx = work_adx["adx_14"].iloc[-1] if "adx_14" in work_adx.columns else None
        plus_di = work_adx["plus_di_14"].iloc[-1] if "plus_di_14" in work_adx.columns else None
        minus_di = work_adx["minus_di_14"].iloc[-1] if "minus_di_14" in work_adx.columns else None
        if adx is not None and pd.notna(adx) and plus_di is not None and minus_di is not None and pd.notna(plus_di) and pd.notna(minus_di):
            adx, plus_di, minus_di = float(adx), float(plus_di), float(minus_di)
            trend_dir = 1.0 if plus_di > minus_di else 0.0
            strength_weight = 0.5 + _clip01(adx / 40.0)
            signals.append((trend_dir, strength_weight))
            if adx >= 20:
                reasons.append(f"ADX {adx:.0f} — {'up' if plus_di > minus_di else 'down'}trend in force.")
    except Exception:
        pass

    result = _combine(signals, reasons)

    if result["up_pct"] is not None:
        pro = pro_signals(df, price)
        reasons.extend(pro["reasons"])
        up = max(0.0, min(100.0, result["up_pct"] + pro["up_adj"]))
        direction = "UP" if up > 50.0 else "DOWN" if up < 50.0 else "NEUTRAL"
        result = {"up_pct": round(up, 1), "down_pct": round(100.0 - up, 1), "direction": direction, "reasons": reasons}

    ratio = None
    if "volume" in df.columns and len(df) >= 20:
        vol = float(df["volume"].iloc[-1])
        avg_vol = float(df["volume"].tail(20).mean())
        if avg_vol > 0:
            ratio = vol / avg_vol
            reasons.append(f"Volume {ratio:.2f}x its 20-bar average — {'confirms' if ratio >= 1.15 else 'unremarkable'} conviction.")

    return _apply_volume_conviction(result, ratio)


TIMEFRAME_OPTIONS = ["5m", "15m", "1h", "4h", "1d", "1w"]


def fetch_and_compute(
    ticker: str, market: str, timeframe: str, *, groww_token: str = "", exchange: str = "NSE", limit: int = 300,
) -> dict[str, Any]:
    """On-demand: fetch OHLCV for `ticker` on `timeframe` and the ticker's current
    day_high/day_low, then run `ohlcv_bias` — the same recipe sma_20_200_engine
    uses internally, exposed standalone so any section can let the user pick a
    different timeframe and recompute the bias without re-running a full scan."""
    from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
    from app.market_pulse.live_price import get_last_traded_price
    from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
    from app.market_pulse.ticker_utils import is_crypto_market

    is_crypto = is_crypto_market(market)
    df = fetch_data_for_gap_scan(ticker, timeframe, market, groww_token, exchange, limit=limit)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < 20:
        df = normalize_ohlcv(fetch_ohlcv_yfinance(ticker, timeframe, is_crypto=is_crypto, limit=limit, market=market))
    if df.empty:
        return {"ticker": ticker, "timeframe": timeframe, "error": f"Insufficient {timeframe} data for this ticker."}

    price = float(df["close"].iloc[-1])
    quote = get_last_traded_price(ticker, market, groww_token=groww_token, exchange=exchange)
    day_high, day_low = quote.get("day_high"), quote.get("day_low")
    bias = ohlcv_bias(df, price, day_high, day_low)
    return {
        "ticker": ticker, "timeframe": timeframe, "price": price,
        "day_high": day_high, "day_low": day_low, "day_bias": bias,
    }
