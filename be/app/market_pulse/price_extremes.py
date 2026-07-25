"""
Shared ATH/ATL, timeframe extremes, and swing-structure (HH/HL/LH/LL) helpers
for all TrueBacktesting tabs that display per-ticker analysis.
"""

from datetime import date, timedelta
from typing import Optional

import pandas as pd
from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.sma_ema_position import analyze_sma_ema_position, render_sma_ema_position_panel
from app.market_pulse.sr_breakout import analyze_sr_breakout, render_sr_breakout_panel
from app.market_pulse.ticker_utils import is_crypto_market, market_currency

SWING_MEANINGS = {
    "HH": (
        "Higher High",
        "Price formed a new swing high above the previous peak — buyers are pushing higher; "
        "uptrend momentum is strengthening.",
    ),
    "HL": (
        "Higher Low",
        "Pullback held above the prior trough — buyers are defending higher levels; "
        "classic sign of an intact uptrend.",
    ),
    "LH": (
        "Lower High",
        "Price failed to exceed the previous peak — sellers are capping upside; "
        "bearish pressure is building.",
    ),
    "LL": (
        "Lower Low",
        "Price broke below the previous trough — sellers are in control; "
        "downtrend momentum is strengthening.",
    ),
}

STRUCTURE_SUMMARIES = {
    ("HH", "HL"): ("Uptrend", "Higher highs + higher lows — bullish market structure.", "bullish"),
    ("LH", "LL"): ("Downtrend", "Lower highs + lower lows — bearish market structure.", "bearish"),
    ("HH", "LL"): ("Expansion", "Higher high but lower low — wide volatile range, trend unclear.", "mixed"),
    ("LH", "HL"): ("Contraction", "Lower high but higher low — tightening range, possible breakout setup.", "mixed"),
}


def _fmt_price(value: float, currency: str, is_crypto: bool) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "N/A"
    if is_crypto:
        if value >= 1000:
            return f"{currency}{value:,.2f}"
        if value >= 1:
            return f"{currency}{value:.4f}"
        return f"{currency}{value:.6f}"
    return f"{currency}{value:,.2f}"


def _find_swing_points(df: pd.DataFrame, window: int = 5):
    """Return lists of (index, price) for swing highs and swing lows."""
    if df is None or df.empty or len(df) < window * 2 + 1:
        return [], []

    highs = df["high"].values
    lows = df["low"].values
    idx = df.index
    swing_highs = []
    swing_lows = []

    for i in range(window, len(df) - window):
        local_high = highs[i]
        local_low = lows[i]
        if local_high == max(highs[i - window : i + window + 1]):
            swing_highs.append((idx[i], float(local_high)))
        if local_low == min(lows[i - window : i + window + 1]):
            swing_lows.append((idx[i], float(local_low)))

    return swing_highs, swing_lows


def classify_swing_structure(df: pd.DataFrame, window: int = 5) -> dict:
    """Compare the last two swing highs/lows to label HH, HL, LH, or LL."""
    swing_highs, swing_lows = _find_swing_points(df, window=window)
    result = {
        "high_label": "N/A",
        "low_label": "N/A",
        "high_meaning": "",
        "low_meaning": "",
        "prev_swing_high": None,
        "recent_swing_high": None,
        "prev_swing_low": None,
        "recent_swing_low": None,
        "structure_name": "Insufficient Data",
        "structure_detail": "Not enough swing points in this lookback window.",
        "structure_bias": "neutral",
    }

    if len(swing_highs) >= 2:
        prev_h = swing_highs[-2][1]
        recent_h = swing_highs[-1][1]
        result["prev_swing_high"] = prev_h
        result["recent_swing_high"] = recent_h
        label = "HH" if recent_h > prev_h else "LH"
        result["high_label"] = label
        result["high_meaning"] = SWING_MEANINGS[label][1]

    if len(swing_lows) >= 2:
        prev_l = swing_lows[-2][1]
        recent_l = swing_lows[-1][1]
        result["prev_swing_low"] = prev_l
        result["recent_swing_low"] = recent_l
        label = "HL" if recent_l > prev_l else "LL"
        result["low_label"] = label
        result["low_meaning"] = SWING_MEANINGS[label][1]

    h_lbl = result["high_label"]
    l_lbl = result["low_label"]
    if h_lbl != "N/A" and l_lbl != "N/A":
        summary = STRUCTURE_SUMMARIES.get((h_lbl, l_lbl))
        if summary:
            result["structure_name"] = summary[0]
            result["structure_detail"] = summary[1]
            result["structure_bias"] = summary[2]
        else:
            result["structure_name"] = f"{h_lbl} + {l_lbl}"
            result["structure_detail"] = "Mixed swing structure — watch for confirmation."
            result["structure_bias"] = "mixed"

    return result


def fetch_all_time_extremes(
    symbol: str,
    market: str,
    exchange: str = "NSE",
    groww_token: str = "",
) -> dict:
    """Fetch long-history daily data for all-time high/low."""
    is_crypto = is_crypto_market(market)
    df = fetch_data_for_gap_scan(
        symbol=symbol,
        timeframe="1d",
        market=market,
        groww_token=groww_token,
        exchange=exchange,
        limit=5000,
    )
    if df.empty or len(df) < 5:
        return {"ath": None, "atl": None, "ath_date": None, "atl_date": None, "bars": len(df)}

    ath_idx = df["high"].idxmax()
    atl_idx = df["low"].idxmin()
    return {
        "ath": float(df.loc[ath_idx, "high"]),
        "atl": float(df.loc[atl_idx, "low"]),
        "ath_date": ath_idx,
        "atl_date": atl_idx,
        "bars": len(df),
    }


def compute_price_extremes(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    market: str,
    exchange: str = "NSE",
    groww_token: str = "",
    swing_window: int = 5,
) -> dict:
    """Build full extremes payload from timeframe OHLCV + all-time history."""
    is_crypto = is_crypto_market(market)
    current = float(df["close"].iloc[-1]) if not df.empty else None

    tf_high = float(df["high"].max()) if not df.empty else None
    tf_low = float(df["low"].min()) if not df.empty else None
    tf_high_idx = df["high"].idxmax() if not df.empty else None
    tf_low_idx = df["low"].idxmin() if not df.empty else None

    all_time = fetch_all_time_extremes(symbol, market, exchange, groww_token)
    ath = all_time.get("ath")
    atl = all_time.get("atl")

    gap_from_ath = ((ath - current) / ath * 100) if ath and current else None
    gap_from_atl = ((current - atl) / atl * 100) if atl and current else None
    gap_from_tf_high = ((tf_high - current) / tf_high * 100) if tf_high and current else None
    gap_from_tf_low = ((current - tf_low) / tf_low * 100) if tf_low and current else None

    swing = classify_swing_structure(df, window=swing_window)

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "current": current,
        "is_crypto": is_crypto,
        "ath": ath,
        "atl": atl,
        "ath_date": all_time.get("ath_date"),
        "atl_date": all_time.get("atl_date"),
        "all_time_bars": all_time.get("bars", 0),
        "gap_from_ath_pct": gap_from_ath,
        "gap_from_atl_pct": gap_from_atl,
        "tf_high": tf_high,
        "tf_low": tf_low,
        "tf_high_date": tf_high_idx,
        "tf_low_date": tf_low_idx,
        "gap_from_tf_high_pct": gap_from_tf_high,
        "gap_from_tf_low_pct": gap_from_tf_low,
        "lookback_bars": len(df) if df is not None else 0,
        **swing,
    }


def _bias_color(bias: str) -> str:
    return {"bullish": "#10b981", "bearish": "#ef4444", "mixed": "#f59e0b"}.get(bias, "#94a3b8")


def _label_chip(label: str) -> str:
    colors = {"HH": "#10b981", "HL": "#34d399", "LH": "#f87171", "LL": "#ef4444"}
    color = colors.get(label, "#64748b")
    name = SWING_MEANINGS.get(label, (label, ""))[0]
    return (
        f'<span style="background:{color}22;color:{color};border:1px solid {color};'
        f'padding:2px 8px;border-radius:12px;font-size:0.75rem;font-weight:700;">{name} ({label})</span>'
    )


def render_price_extremes_panel(
    extremes: dict,
    currency: str = "₹",
    compact: bool = False,
):
    """Render ATH/ATL, timeframe extremes, and swing-structure explanation."""
    if not extremes or extremes.get("current") is None:
        st.caption("⚠️ Price extremes unavailable — insufficient data.")
        return

    is_crypto = extremes.get("is_crypto", currency == "$")
    cur = extremes["current"]
    tf = extremes.get("timeframe", "")
    symbol = extremes.get("symbol", "")

    title = f"📍 Price Extremes — {symbol}" + (f" ({tf})" if tf else "")
    if compact:
        st.markdown(f"**{title}**")
    else:
        st.markdown(f"#### {title}")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Current Price", _fmt_price(cur, currency, is_crypto))
    with c2:
        st.metric(
            "All-Time High",
            _fmt_price(extremes.get("ath"), currency, is_crypto),
            delta=f"-{extremes['gap_from_ath_pct']:.2f}% below" if extremes.get("gap_from_ath_pct") is not None else None,
            delta_color="inverse",
        )
    with c3:
        st.metric(
            "All-Time Low",
            _fmt_price(extremes.get("atl"), currency, is_crypto),
            delta=f"+{extremes['gap_from_atl_pct']:.2f}% above" if extremes.get("gap_from_atl_pct") is not None else None,
            delta_color="normal",
        )
    with c4:
        bias = extremes.get("structure_bias", "neutral")
        st.metric("Market Structure", extremes.get("structure_name", "N/A"))

    c5, c6, c7, c8 = st.columns(4)
    with c5:
        st.metric(
            f"Recent Max ({tf})" if tf else "Recent Max",
            _fmt_price(extremes.get("tf_high"), currency, is_crypto),
            delta=f"-{extremes['gap_from_tf_high_pct']:.2f}% below" if extremes.get("gap_from_tf_high_pct") is not None else None,
            delta_color="inverse",
        )
    with c6:
        st.metric(
            f"Recent Min ({tf})" if tf else "Recent Min",
            _fmt_price(extremes.get("tf_low"), currency, is_crypto),
            delta=f"+{extremes['gap_from_tf_low_pct']:.2f}% above" if extremes.get("gap_from_tf_low_pct") is not None else None,
            delta_color="normal",
        )
    with c7:
        gap_ath = extremes.get("gap_from_ath_pct")
        st.metric("Gap from ATH", f"{gap_ath:.2f}%" if gap_ath is not None else "N/A")
    with c8:
        gap_atl = extremes.get("gap_from_atl_pct")
        st.metric("Gap from ATL", f"{gap_atl:.2f}%" if gap_atl is not None else "N/A")

    high_chip = _label_chip(extremes["high_label"]) if extremes.get("high_label") != "N/A" else ""
    low_chip = _label_chip(extremes["low_label"]) if extremes.get("low_label") != "N/A" else ""
    bias_color = _bias_color(extremes.get("structure_bias", "neutral"))

    st.markdown(
        f"""
        <div style="background:#0f1729;border:1px solid #1e3a5f;border-radius:10px;padding:14px 16px;margin-top:8px;">
            <div style="font-size:0.72rem;color:#64748b;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;">
                Swing Structure ({extremes.get('lookback_bars', 0)} bars)
            </div>
            <div style="margin-bottom:8px;">
                {high_chip} {low_chip}
                <span style="color:{bias_color};font-weight:700;margin-left:8px;">
                    {extremes.get('structure_name', '')}
                </span>
            </div>
            <div style="font-size:0.82rem;color:#cbd5e1;line-height:1.55;">
                {extremes.get('structure_detail', '')}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("ℹ️ What HH / HL / LH / LL mean", expanded=False):
        for key, (name, meaning) in SWING_MEANINGS.items():
            st.markdown(f"**{name} ({key})** — {meaning}")
        if extremes.get("high_meaning"):
            st.markdown(f"**Latest swing high:** {extremes['high_meaning']}")
        if extremes.get("low_meaning"):
            st.markdown(f"**Latest swing low:** {extremes['low_meaning']}")
        if extremes.get("prev_swing_high") is not None:
            st.caption(
                f"Prev swing high: {_fmt_price(extremes['prev_swing_high'], currency, is_crypto)} → "
                f"Recent: {_fmt_price(extremes['recent_swing_high'], currency, is_crypto)}"
            )
        if extremes.get("prev_swing_low") is not None:
            st.caption(
                f"Prev swing low: {_fmt_price(extremes['prev_swing_low'], currency, is_crypto)} → "
                f"Recent: {_fmt_price(extremes['recent_swing_low'], currency, is_crypto)}"
            )


def render_price_extremes_for_ticker(
    symbol: str,
    df: pd.DataFrame,
    timeframe: str,
    market: str,
    exchange: str = "NSE",
    groww_token: str = "",
    currency: Optional[str] = None,
    compact: bool = False,
    show_structure_chart: bool = True,
):
    """Compute and render extremes from an existing OHLCV dataframe."""
    if df is None or df.empty:
        return
    if currency is None:
        currency = market_currency(market)
    extremes = compute_price_extremes(df, symbol, timeframe, market, exchange, groww_token)
    render_price_extremes_panel(extremes, currency=currency, compact=compact)

    sma_ema = analyze_sma_ema_position(df, timeframe=timeframe)
    sr_breakout = analyze_sr_breakout(df, timeframe=timeframe)

    if show_structure_chart:
        from app.market_pulse.ta_structure_chart import render_ta_structure_section

        render_ta_structure_section(
            df, symbol, timeframe, currency,
            compact=compact,
            sma_ema=sma_ema,
            ema_ladder=sma_ema.get("ema_ladder"),
            sr_breakout=sr_breakout,
            chart_height=360 if compact else 400,
        )
        st.markdown("---")

    render_sma_ema_position_panel(
        sma_ema, currency=currency, compact=compact, show_chart=False,
    )
    render_sr_breakout_panel(
        sr_breakout, currency=currency, compact=compact, show_chart=False,
    )


def render_heatmap_ticker_extremes(
    data_list: list,
    timeframe: str,
    market: str,
    exchange: str = "NSE",
    groww_token: str = "",
    limit: int = 300,
    max_tickers: int | None = None,
):
    """Render price-extreme expanders for heatmap ticker grids."""
    if not data_list:
        return

    currency = market_currency(market)
    st.markdown("---")
    st.markdown("### 📍 Price Extremes by Ticker")
    st.caption(
        "All-time high/low, % gaps, recent timeframe max/min, and swing structure "
        "(Higher High / Higher Low / Lower High / Lower Low)."
    )

    rows = data_list if max_tickers is None or max_tickers <= 0 else data_list[:max_tickers]
    for d in rows:
        tick = d.get("ticker", "")
        if not tick:
            continue
        with st.expander(f"📊 {tick} | {timeframe}", expanded=False):
            df = fetch_data_for_gap_scan(
                tick, timeframe, market,
                groww_token=groww_token, exchange=exchange, limit=limit,
            )
            if df.empty:
                st.warning("Could not load OHLCV data for this ticker.")
            else:
                render_price_extremes_for_ticker(
                    tick, df, timeframe, market,
                    exchange=exchange, groww_token=groww_token,
                    currency=currency, compact=True,
                )
