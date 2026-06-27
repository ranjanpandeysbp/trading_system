"""
india_pump_dump_predictor.py
----------------------------
NSE/BSE pre-pump / pre-dump scalping engine — option chain, flows, ORB, VWAP, delivery.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, time as dt_time
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.indicators import add_ema, add_rsi, add_vwap
from app.market_pulse.news_scanner import (
    fetch_gift_nifty_5paisa,
    fetch_nse_fii_dii,
    fetch_nse_option_chain,
    fetch_nse_turnover_delivery,
)
from app.market_pulse.pump_dump_predictor import (
    ENTRY_MOMENTUM_BARS,
    HTF_MOMENTUM_BARS,
    HTF_OPTIONS,
    OHLCV_LIMITS,
    _finalize_confluence_score,
    _htf_trend,
    _key_level_hit,
    _prep_indicators,
    _trigger_candle,
    compute_tf_momentum,
    detect_resistance_breakout,
    detect_support_breakdown,
    detect_technical_structure_signals,
    format_active_signal_labels,
    htf_alignment_points,
    key_level_points,
    trigger_points,
)

INDIA_ENTRY_TF_OPTIONS = ["1m", "3m", "5m", "10m", "15m", "30m", "1h", "4h", "1d", "1w"]

IST = ZoneInfo("Asia/Kolkata")
GROWW_MARKET = "Groww (India Stocks)"

INDIA_PRE_PUMP = [
    ("pcr_oversold", "PCR Rising Above 1.2", "Pump signal"),
    ("oi_bullish", "Call OI Unwind + Put OI Build", "Pump signal"),
    ("max_pain_upside", "Max Pain Below Price", "Pump signal"),
    ("orb_breakout", "ORB Breakout (15m high + 2× vol)", "Pump signal"),
    ("vwap_reclaim", "VWAP Reclaim + 9 EMA", "Pump signal"),
    ("delivery_spike", "Delivery % Spike (60%+)", "Pump signal"),
    ("fii_buying", "FII Net Buying (multi-day)", "Pump signal"),
    ("gift_nifty_positive", "Gift Nifty Positive Pre-Open", "Pump signal"),
    ("resistance_breakout", "Resistance Breakout (S/R)", "Pump signal"),
    ("golden_cross", "Golden Cross (EMA)", "Pump signal"),
    ("ema_breakout", "EMA Breakout", "Pump signal"),
    ("bullish_candle", "Bullish Candle Pattern", "Pump signal"),
    ("bb_lower_zone", "Lower Bollinger Band", "Pump signal"),
    ("vol_absorption", "Volume Absorption at Support", "Expert booster"),
    ("institutional_support", "Bulk/Block Deal Support Zone", "Expert booster"),
    ("relative_strength", "Relative Strength vs Nifty", "Expert booster"),
    ("ema_ribbon_bull", "EMA 9/21 Ribbon Bullish", "Expert booster"),
    ("oi_long_buildup", "Long Buildup (Price↑ + OI↑)", "Expert booster"),
    ("second_entry_long", "Second Entry ORB Retest", "Expert booster"),
    ("coil_breakout_ready", "Vol Coil / Inside Bar", "Expert booster"),
    ("global_absorption", "Global Cue Absorption (Gift Nifty)", "Expert booster"),
]

INDIA_PRE_DUMP = [
    ("pcr_overbought", "PCR Below 0.8", "Dump signal"),
    ("oi_bearish", "Call OI Build + Put OI Unwind", "Dump signal"),
    ("vwap_rejection", "VWAP Rejection", "Dump signal"),
    ("orb_breakdown", "ORB Breakdown (15m low)", "Dump signal"),
    ("fii_selling", "FII Selling — DII Not Absorbing", "Dump signal"),
    ("distribution_candle", "Distribution at Resistance", "Dump signal"),
    ("support_breakdown", "Support Breakdown (S/R)", "Dump signal"),
    ("death_cross", "Death Cross (EMA)", "Dump signal"),
    ("ema_breakdown", "EMA Breakdown", "Dump signal"),
    ("bearish_candle", "Bearish Candle Pattern", "Dump signal"),
    ("bb_upper_zone", "Upper Bollinger Band", "Dump signal"),
    ("weak_green_trap", "Big Green + Low Volume Trap", "Expert booster"),
    ("wick_rejection", "High-Volume Wick Rejection", "Expert booster"),
    ("institutional_supply", "Bulk/Block Deal Supply Zone", "Expert booster"),
    ("relative_weakness", "Relative Weakness vs Nifty", "Expert booster"),
    ("ema_ribbon_bear", "EMA 9/21 Ribbon Bearish", "Expert booster"),
    ("oi_short_buildup", "Short Buildup (Price↓ + OI↑)", "Expert booster"),
    ("second_entry_short", "Second Entry Breakdown Retest", "Expert booster"),
    ("max_pain_expiry_fade", "Max Pain Expiry Fade Bias", "Expert booster"),
]

INDIA_MOVE_EXPECTATIONS = {
    "NIFTY": {"1m": "20–50 pts", "3m": "40–80 pts", "5m": "60–120 pts", "15m": "100–250 pts"},
    "BANKNIFTY": {"1m": "50–100 pts", "3m": "100–200 pts", "5m": "150–300 pts", "15m": "300–600 pts"},
    "DEFAULT": {
        "1m": "0.3%–0.8%", "3m": "0.5%–1.5%", "5m": "0.8%–2%", "10m": "1%–2.5%",
        "15m": "1.5%–4%", "30m": "2%–5%", "1h": "2.5%–6%", "4h": "3%–8%",
        "1d": "4%–12%", "1w": "6%–20%",
    },
}

INDIA_SCALP_STOCKS = [
    "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "SBIN", "TMPV",
    "BAJFINANCE", "ETERNAL", "AXISBANK", "ADANIPORTS", "LT",
]

INDEX_OPTION_MAP = {
    "NIFTY": "NIFTY", "NIFTY50": "NIFTY", "NIFTY 50": "NIFTY",
    "BANKNIFTY": "BANKNIFTY", "BANK NIFTY": "BANKNIFTY", "NIFTY BANK": "BANKNIFTY",
    "FINNIFTY": "FINNIFTY", "NIFTY FIN SERVICE": "FINNIFTY",
    "MIDCPNIFTY": "MIDCPNIFTY", "NIFTY MID SELECT": "MIDCPNIFTY",
}

SESSION_WINDOWS = [
    ("9:15–9:20", "Trap zone — first 5m often fakes direction"),
    ("9:45–10:15", "Prime — institutional wave 2 (best entries)"),
    ("10:15–11:00", "Morning trend continuation"),
    ("11:00–11:15", "Minor reversal window — tighten stops"),
    ("11:30–13:00", "Dead zone — reduce activity"),
    ("14:00–14:15", "European flow — fresh momentum"),
    ("15:00–15:15", "Institutional squaring — close bias"),
    ("14:15–15:10", "Power hour — exit MIS by 15:10"),
]


def _normalize_ticker(ticker: str) -> str:
    return ticker.upper().strip().replace(".NS", "").replace(".BO", "")


def _resolve_entry_tf(entry_tf: str) -> str:
    """Map UI entry TF to OHLCV resolution (3m has no native feed — use 5m bars)."""
    if entry_tf == "3m":
        return "5m"
    return entry_tf


def _option_underlying(ticker: str) -> str:
    t = _normalize_ticker(ticker)
    return INDEX_OPTION_MAP.get(t, "NIFTY")


def _move_key(ticker: str) -> str:
    t = _normalize_ticker(ticker)
    if "BANK" in t and "NIFTY" in t:
        return "BANKNIFTY"
    if t in ("NIFTY", "NIFTY50") or t.startswith("NIFTY"):
        return "NIFTY"
    return "DEFAULT"


INDIA_INDEX_SYMBOLS = frozenset({
    "NIFTY", "NIFTY50", "NIFTY 50", "BANKNIFTY", "NIFTY BANK", "BANK NIFTY",
    "FINNIFTY", "NIFTY FIN SERVICE", "MIDCPNIFTY", "NIFTY MID SELECT",
})


def _normalize_ohlcv_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    cols = {c.lower(): c for c in out.columns}
    for need in ("open", "high", "low", "close", "volume"):
        if need not in out.columns:
            for c in out.columns:
                if c.lower() == need:
                    out.rename(columns={c: need}, inplace=True)
                    break
    if "date" in out.columns and not isinstance(out.index, pd.DatetimeIndex):
        out["date"] = pd.to_datetime(out["date"])
        out.set_index("date", inplace=True)
    elif not isinstance(out.index, pd.DatetimeIndex) and "time" in out.columns:
        out["date"] = pd.to_datetime(out["time"], unit="s")
        out.set_index("date", inplace=True)
    return out.sort_index()


def fetch_india_ohlcv(
    ticker: str,
    timeframe: str,
    groww_token: str = "",
    exchange: str = "NSE",
    limit: int | None = None,
) -> pd.DataFrame:
    from app.market_pulse.nse_index_yfinance import is_nse_index_symbol, resolve_nse_equity_symbol

    sym = _normalize_ticker(ticker)
    sym = resolve_nse_equity_symbol(sym)
    is_index = sym in INDIA_INDEX_SYMBOLS or sym in INDEX_OPTION_MAP or is_nse_index_symbol(sym)
    bar_limit = limit if limit is not None else OHLCV_LIMITS.get(timeframe, 200)

    if groww_token and timeframe not in ("1w", "1M"):
        if is_index:
            from app.market_pulse.index_ohlcv import fetch_index_ohlcv_for_interval
            from app.market_pulse.nse_index_yfinance import canonical_index_name, INDEX_NAME_ALIASES, normalize_index_name

            idx_label = INDEX_NAME_ALIASES.get(normalize_index_name(sym), sym)
            idx_label = canonical_index_name(idx_label)
            df = fetch_index_ohlcv_for_interval(
                idx_label, timeframe, bar_limit,
                groww_token=groww_token, exchange=exchange,
            )
            df = _normalize_ohlcv_df(df)
            if not df.empty and len(df) >= 15:
                return df.tail(bar_limit)
        else:
            try:
                from app.market_pulse.heatmap import fetch_groww_ohlcv
                df = fetch_groww_ohlcv(sym, exchange, timeframe, groww_token, limit=bar_limit)
                df = _normalize_ohlcv_df(df)
                if not df.empty and len(df) >= 15:
                    return df.tail(bar_limit)
            except Exception:
                pass

    try:
        from app.market_pulse.heatmap import (
            fetch_ohlcv_yfinance_for_indices,
            fetch_ohlcv_yfinance_for_tickers,
        )
        if is_index:
            df = fetch_ohlcv_yfinance_for_indices(sym, timeframe, limit=bar_limit)
        else:
            df = fetch_ohlcv_yfinance_for_tickers(sym, timeframe, limit=bar_limit)
        df = _normalize_ohlcv_df(df)
        if not df.empty and len(df) >= 15:
            return df.tail(bar_limit)
    except Exception:
        pass

    df = fetch_data_for_gap_scan(sym, timeframe, GROWW_MARKET, groww_token, exchange, limit=bar_limit)
    df = _normalize_ohlcv_df(df)
    if not df.empty:
        return df.tail(bar_limit)
    return pd.DataFrame()


def current_session_phase() -> tuple[str, str]:
    now = datetime.now(IST).time()
    if now < dt_time(9, 45):
        return "9:15–9:45", "Wait — opening range forming"
    if now < dt_time(11, 30):
        return "9:45–11:30", "Prime scalping zone"
    if now < dt_time(13, 0):
        return "11:30–13:00", "Dead zone — whipsaws common"
    if now < dt_time(14, 15):
        return "13:00–14:15", "European influence — fresh momentum possible"
    if now <= dt_time(15, 30):
        return "14:15–15:30", "Power hour — plan exit by 15:10 IST"
    return "After hours", "Market closed — prep for next session"


def _opening_range_levels(df_15m: pd.DataFrame) -> tuple[float | None, float | None]:
    if df_15m.empty:
        return None, None
    if not isinstance(df_15m.index, pd.DatetimeIndex):
        return None, None
    last_day = df_15m.index[-1].date()
    day = df_15m[df_15m.index.date == last_day]
    if day.empty:
        day = df_15m.tail(1)
    bar = day.iloc[0]
    return float(bar["high"]), float(bar["low"])


def _pdh_pdl(df_daily: pd.DataFrame) -> tuple[float | None, float | None]:
    if df_daily is None or len(df_daily) < 2:
        return None, None
    prev = df_daily.iloc[-2]
    return float(prev["high"]), float(prev["low"])


def _oi_bullish_structure(oc: dict, price: float) -> tuple[bool, str]:
    strikes = oc.get("strikes") or []
    if not strikes:
        return False, "No option chain"
    res = [s for s in strikes if s["strike"] >= price * 0.995]
    sup = [s for s in strikes if s["strike"] <= price * 1.005]
    call_unwind = sum(s.get("ce_chg_oi", 0) for s in res) < 0
    put_build = sum(s.get("pe_chg_oi", 0) for s in sup) > 0
    pcr = oc.get("pcr_oi", 0)
    note = f"PCR(OI) {pcr:.2f} · call ΔOI@res {sum(s.get('ce_chg_oi',0) for s in res):,.0f}"
    if call_unwind and put_build:
        return True, note + " — bullish OI structure"
    return False, note


def _oi_bearish_structure(oc: dict, price: float) -> tuple[bool, str]:
    strikes = oc.get("strikes") or []
    if not strikes:
        return False, "No option chain"
    res = [s for s in strikes if s["strike"] >= price * 0.995]
    sup = [s for s in strikes if s["strike"] <= price * 1.005]
    call_build = sum(s.get("ce_chg_oi", 0) for s in res) > 0
    put_unwind = sum(s.get("pe_chg_oi", 0) for s in sup) < 0
    pcr = oc.get("pcr_oi", 0)
    note = f"PCR(OI) {pcr:.2f} · put ΔOI@sup {sum(s.get('pe_chg_oi',0) for s in sup):,.0f}"
    if call_build and put_unwind:
        return True, note + " — bearish OI structure"
    return False, note


def _fii_multi_day_bias(fii_data: dict | None) -> tuple[bool, bool, str]:
    if not fii_data:
        return False, False, "FII/DII data unavailable"
    hist = fii_data.get("history") or []
    if len(hist) < 2:
        fii_net = (fii_data.get("fii") or {}).get("net_cr", 0)
        dii_net = (fii_data.get("dii") or {}).get("net_cr", 0)
        if fii_net > 0:
            return True, False, f"FII net +₹{fii_net:.0f} Cr (latest)"
        if fii_net < 0 and dii_net <= abs(fii_net) * 0.3:
            return False, True, f"FII net ₹{fii_net:.0f} Cr — DII not absorbing"
        return False, False, f"FII ₹{fii_net:.0f} Cr · DII ₹{dii_net:.0f} Cr"
    last3 = hist[-3:]
    fii_nets = [h.get("fii_net", 0) for h in last3]
    dii_nets = [h.get("dii_net", 0) for h in last3]
    buying = all(x > 0 for x in fii_nets[-2:])
    selling = fii_nets[-1] < 0 and sum(fii_nets[-2:]) < 0 and dii_nets[-1] < abs(fii_nets[-1]) * 0.5
    note = f"FII 3d nets: {', '.join(f'{x:+.0f}' for x in fii_nets)} Cr"
    return buying, selling, note


def _symbol_delivery_pct(ticker: str, td_data: dict | None) -> float | None:
    if not td_data:
        return None
    sym = _normalize_ticker(ticker)
    for bucket in ("high_delivery", "low_delivery", "high_turnover"):
        for row in td_data.get(bucket, []):
            if row.get("symbol", "").upper() == sym:
                return float(row.get("deliv_per", 0))
    return td_data.get("avg_delivery_pct")


def _orb_breakout(df_entry: pd.DataFrame, df_15m: pd.DataFrame, direction: str) -> tuple[bool, str]:
    or_high, or_low = _opening_range_levels(df_15m)
    if or_high is None:
        return False, "Opening range not available"
    price = float(df_entry["close"].iloc[-1])
    vol = float(df_entry["volume"].iloc[-1])
    vol_avg = float(df_entry["volume"].iloc[-20:-1].mean()) if len(df_entry) > 20 else vol
    if direction == "up":
        ok = price > or_high and vol >= vol_avg * 1.8
        return ok, f"OR high {or_high:,.2f} · vol {vol / (vol_avg + 1e-9):.1f}x"
    ok = price < or_low and vol >= vol_avg * 1.8
    return ok, f"OR low {or_low:,.2f} · vol {vol / (vol_avg + 1e-9):.1f}x"


def _vwap_reclaim(df: pd.DataFrame) -> tuple[bool, str]:
    d = add_vwap(add_ema(df.copy(), 9))
    if "vwap" not in d.columns:
        return False, "VWAP unavailable"
    c, v, e9 = d["close"].iloc[-1], d["vwap"].iloc[-1], d["ema_9"].iloc[-1]
    prev_c, prev_v = d["close"].iloc[-2], d["vwap"].iloc[-2]
    crossed = prev_c <= prev_v and c > v and c > e9
    return bool(crossed), f"Close {c:,.2f} vs VWAP {v:,.2f} · EMA9 {e9:,.2f}"


def _vwap_rejection(df: pd.DataFrame) -> tuple[bool, str]:
    d = add_vwap(df.copy())
    if "vwap" not in d.columns:
        return False, "VWAP unavailable"
    row = d.iloc[-1]
    touched = row["high"] >= row["vwap"] * 0.999
    closed_below = row["close"] < row["vwap"]
    vol_ok = row["volume"] >= d["volume"].iloc[-10:-1].mean() * 1.2 if len(d) > 10 else True
    ok = touched and closed_below and vol_ok
    return bool(ok), f"Rejected VWAP {row['vwap']:,.2f} · close {row['close']:,.2f}"


def _distribution_candle(df: pd.DataFrame) -> tuple[bool, str]:
    if len(df) < 15:
        return False, "Need more bars"
    d = _prep_indicators(df)
    row = d.iloc[-1]
    recent_high = d["high"].iloc[-10:-1].max()
    at_res = row["high"] >= recent_high * 0.998
    body_pct = abs(row["close"] - row["open"]) / row["close"] * 100
    vol_surge = row["volume"] / (d["volume"].iloc[-20:-1].mean() + 1e-9)
    ok = at_res and vol_surge >= 1.8 and body_pct < 0.35
    return bool(ok), f"Vol {vol_surge:.1f}x at resistance · body {body_pct:.2f}%"


def detect_india_pre_pump(
    df_entry: pd.DataFrame,
    df_15m: pd.DataFrame,
    oc: dict | None,
    price: float,
    fii_data: dict | None,
    gift_chg: float | None,
    delivery_pct: float | None,
) -> dict[str, dict]:
    out: dict[str, dict] = {}
    pcr = (oc or {}).get("pcr_oi", 0)
    max_pain = (oc or {}).get("max_pain")
    out["pcr_oversold"] = {
        "active": pcr >= 1.2,
        "note": f"PCR(OI) {pcr:.2f}" + (" — oversold bounce bias" if pcr >= 1.2 else ""),
    }
    ok, note = _oi_bullish_structure(oc or {}, price)
    out["oi_bullish"] = {"active": ok, "note": note}
    mp_ok = max_pain is not None and price > 0 and max_pain < price * 0.998
    out["max_pain_upside"] = {
        "active": mp_ok,
        "note": f"Max pain {max_pain:,.0f} vs spot {price:,.2f}" if max_pain else "Max pain n/a",
    }
    ok, note = _orb_breakout(df_entry, df_15m, "up")
    out["orb_breakout"] = {"active": ok, "note": note}
    ok, note = _vwap_reclaim(df_entry)
    out["vwap_reclaim"] = {"active": ok, "note": note}
    del_ok = delivery_pct is not None and delivery_pct >= 60
    out["delivery_spike"] = {
        "active": del_ok,
        "note": f"Delivery {delivery_pct:.1f}%" if delivery_pct is not None else "Delivery n/a (check bhavcopy)",
    }
    fii_buy, _, fii_note = _fii_multi_day_bias(fii_data)
    out["fii_buying"] = {"active": fii_buy, "note": fii_note}
    gift_ok = gift_chg is not None and gift_chg > 0
    out["gift_nifty_positive"] = {
        "active": gift_ok,
        "note": f"Gift Nifty {gift_chg:+.2f}%" if gift_chg is not None else "Gift Nifty n/a",
    }
    ok, note = detect_resistance_breakout(df_entry)
    out["resistance_breakout"] = {"active": ok, "note": note}
    return out


def detect_india_pre_dump(
    df_entry: pd.DataFrame,
    df_15m: pd.DataFrame,
    oc: dict | None,
    price: float,
    fii_data: dict | None,
) -> dict[str, dict]:
    out: dict[str, dict] = {}
    pcr = (oc or {}).get("pcr_oi", 0)
    out["pcr_overbought"] = {
        "active": 0 < pcr < 0.8,
        "note": f"PCR(OI) {pcr:.2f}" + (" — crowded calls" if pcr < 0.8 else ""),
    }
    ok, note = _oi_bearish_structure(oc or {}, price)
    out["oi_bearish"] = {"active": ok, "note": note}
    ok, note = _vwap_rejection(df_entry)
    out["vwap_rejection"] = {"active": ok, "note": note}
    ok, note = _orb_breakout(df_entry, df_15m, "down")
    out["orb_breakdown"] = {"active": ok, "note": note}
    _, fii_sell, fii_note = _fii_multi_day_bias(fii_data)
    out["fii_selling"] = {"active": fii_sell, "note": fii_note}
    ok, note = _distribution_candle(df_entry)
    out["distribution_candle"] = {"active": ok, "note": note}
    ok, note = detect_support_breakdown(df_entry)
    out["support_breakdown"] = {"active": ok, "note": note}
    return out


def score_india_confluence(
    *,
    direction: str,
    htf_trend: str,
    at_key_level: bool,
    key_level_note: str,
    pump_signals: dict,
    dump_signals: dict,
    option_confirms: bool,
    flow_confirms: bool,
    trigger: dict,
    rr_ok: bool,
    session_ok: bool,
    time_bias: dict | None = None,
) -> dict[str, Any]:
    breakdown: list[dict] = []
    total = 0

    def add(label: str, pts: int, earned: int, detail: str = ""):
        nonlocal total
        total += earned
        breakdown.append({"label": label, "max": pts, "earned": earned, "detail": detail})

    htf_pts, htf_note = htf_alignment_points(direction, htf_trend)
    add("HTF trend", 15, htf_pts, htf_note)
    kl_pts, kl_note = key_level_points(at_key_level, key_level_note)
    sr_confirm = (
        pump_signals.get("resistance_breakout", {}).get("active")
        if direction == "long"
        else dump_signals.get("support_breakdown", {}).get("active")
    )
    if sr_confirm and kl_pts < 12:
        kl_pts = min(12, kl_pts + 6)
        kl_note = (kl_note + " · S/R break confirmed") if kl_note else "S/R breakout/breakdown confirmed"
    add("PDH/PDL / S/R / round", 12, kl_pts, kl_note)
    vol_sig = (
        pump_signals.get("orb_breakout", {}).get("active")
        or pump_signals.get("vwap_reclaim", {}).get("active")
        or pump_signals.get("resistance_breakout", {}).get("active")
        or dump_signals.get("orb_breakdown", {}).get("active")
        or dump_signals.get("vwap_rejection", {}).get("active")
        or dump_signals.get("distribution_candle", {}).get("active")
        or dump_signals.get("support_breakdown", {}).get("active")
    )
    vol_detail = "Includes S/R break volume" if sr_confirm and vol_sig else ""
    add("Volume / VWAP / ORB", 10, 10 if vol_sig else (6 if sr_confirm else 0), vol_detail)
    oi_pts = 12 if option_confirms else (
        6 if pump_signals.get("oi_long_buildup", {}).get("active")
        or dump_signals.get("oi_short_buildup", {}).get("active")
        else 0
    )
    add("Option chain / OI matrix", 12, oi_pts, "")
    rsi_ok = (
        pump_signals.get("vwap_reclaim", {}).get("active")
        or pump_signals.get("bullish_candle", {}).get("active")
        or pump_signals.get("golden_cross", {}).get("active")
        or pump_signals.get("ema_breakout", {}).get("active")
        if direction == "long"
        else (
            dump_signals.get("vwap_rejection", {}).get("active")
            or dump_signals.get("bearish_candle", {}).get("active")
            or dump_signals.get("death_cross", {}).get("active")
            or dump_signals.get("ema_breakdown", {}).get("active")
        )
    )
    add("Momentum / VWAP / EMA / candle", 8, 8 if rsi_ok else 0, "")
    flow_pts = 8 if flow_confirms else (
        4 if pump_signals.get("global_absorption", {}).get("active") else 0
    )
    add("FII/DII / Gift flow", 8, flow_pts, "")
    trig_pts, trig_note = trigger_points(trigger)
    add("Trigger candle", 10, trig_pts, trig_note)
    add("RR ≥ 1:2", 5, 5 if rr_ok else 0, "")

    tb = time_bias or {}
    action = tb.get("action", "OK")
    session_pts_map = {"PRIME": 8, "GOOD": 6, "OK": 4, "CAUTION": 2, "WAIT": 0, "AVOID": 0, "CLOSED": 0}
    session_pts = session_pts_map.get(action, 4 if session_ok else 0)
    if not session_ok:
        session_pts = min(session_pts, 2)
    add("Session timing", 8, session_pts, tb.get("note", ""))

    sigs = pump_signals if direction == "long" else dump_signals
    signal_count = sum(1 for v in sigs.values() if v.get("active"))
    return _finalize_confluence_score(total, breakdown, signal_count)


def build_india_trade_plan(
    direction: str,
    entry_tf: str,
    price: float,
    stop_ref: float,
    ticker: str,
) -> dict[str, Any]:
    if direction == "long":
        risk = max(price - stop_ref, price * 0.003)
        sl, tp1, tp2 = price - risk, price + risk * 1.5, price + risk * 2.5
    else:
        risk = max(stop_ref - price, price * 0.003)
        sl, tp1, tp2 = price + risk, price - risk * 1.5, price - risk * 2.5
    mk = _move_key(ticker)
    moves = INDIA_MOVE_EXPECTATIONS.get(mk, INDIA_MOVE_EXPECTATIONS["DEFAULT"])
    intraday = entry_tf in ("1m", "3m", "5m", "10m", "15m", "30m", "1h")
    return {
        "direction": "LONG" if direction == "long" else "SHORT",
        "entry": price,
        "stop_loss": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": None,
        "tp1_action": "Close 50% at 1:1.5 RR",
        "tp2_action": "Close 30% at 1:2.5 RR",
        "tp3_action": "Trail remaining 20%",
        "breakeven_rule": "Move stop to entry after TP1",
        "rr_ratio": 2.5,
        "rr_ok": True,
        "expected_move": moves.get(entry_tf, moves.get("5m", "—")),
        "entry_rule": (
            "Enter next candle open after trigger · use SL-Market"
            if intraday
            else "Enter on confirmed close · use GTT or CNC/F&O positional"
        ),
        "hard_exit": (
            "Exit all MIS by 15:10 IST (broker square-off ~15:20)"
            if intraday
            else "Swing/positional — no MIS square-off; trail or exit on TP/SL"
        ),
        "hold_duration": {
            "1m": "5–15 min · MIS only",
            "3m": "10–30 min",
            "5m": "15–45 min · typical scalp window",
            "10m": "20–60 min",
            "15m": "30–90 min · exit before 15:10 IST",
            "30m": "1–2 hours · plan exit by 15:10 IST",
            "1h": "2–4 hours · avoid new MIS after 14:00",
            "4h": "1–3 days · swing / positional",
            "1d": "3–15 days · swing",
            "1w": "2–8 weeks · positional",
        }.get(entry_tf, "15–45 min · square-off by 15:10 IST"),
        "actionable": False,
    }


@dataclass
class IndiaPumpDumpAnalysis:
    symbol: str
    entry_tf: str
    htf: str
    price: float
    htf_trend: str
    bias: str
    pump_signals: dict = field(default_factory=dict)
    dump_signals: dict = field(default_factory=dict)
    confluence_long: dict = field(default_factory=dict)
    confluence_short: dict = field(default_factory=dict)
    trade_plan_long: dict | None = None
    trade_plan_short: dict | None = None
    option_chain: dict = field(default_factory=dict)
    fii_dii: dict = field(default_factory=dict)
    gift_nifty_chg: float | None = None
    delivery_pct: float | None = None
    session_phase: str = ""
    session_note: str = ""
    key_level: str = ""
    pdh: float | None = None
    pdl: float | None = None
    price_chg_pct: float | None = None
    vol_chg_pct: float | None = None
    price_chg_1bar_pct: float | None = None
    htf_price_chg_pct: float | None = None
    momentum_bars: int = 6
    technical_context: dict = field(default_factory=dict)
    expert_warnings: list[str] = field(default_factory=list)
    expert_time_bias: dict = field(default_factory=dict)
    bulk_deals: list = field(default_factory=list)
    error: str = ""


def analyze_india_ticker(
    ticker: str,
    entry_tf: str = "5m",
    htf: str = "15m",
    groww_token: str = "",
    exchange: str = "NSE",
    *,
    oc_data: dict | None = None,
    fii_data: dict | None = None,
    td_data: dict | None = None,
    gift_chg: float | None = None,
    index_df: pd.DataFrame | None = None,
    bulk_deals: list | None = None,
) -> IndiaPumpDumpAnalysis:
    from app.market_pulse.nse_index_yfinance import resolve_nse_equity_symbol

    sym = resolve_nse_equity_symbol(_normalize_ticker(ticker))
    result = IndiaPumpDumpAnalysis(
        symbol=sym, entry_tf=entry_tf, htf=htf, price=0, htf_trend="neutral", bias="neutral",
    )
    phase, phase_note = current_session_phase()
    result.session_phase = phase
    result.session_note = phase_note

    fetch_tf = _resolve_entry_tf(entry_tf)
    df_entry = fetch_india_ohlcv(sym, fetch_tf, groww_token, exchange)
    df_htf = fetch_india_ohlcv(sym, htf, groww_token, exchange)
    df_15m = fetch_india_ohlcv(sym, "15m", groww_token, exchange)
    df_daily = fetch_india_ohlcv(sym, "1d", groww_token, exchange, limit=10)

    if df_entry.empty or len(df_entry) < 15:
        result.error = "Insufficient intraday data — yfinance/Groww returned too few bars; try 5m/15m or market hours"
        return result

    result.price = float(df_entry["close"].iloc[-1])
    mom_bars = ENTRY_MOMENTUM_BARS.get(entry_tf, 6)
    result.momentum_bars = mom_bars
    mom = compute_tf_momentum(df_entry, mom_bars)
    result.price_chg_pct = mom["price_chg_pct"]
    result.vol_chg_pct = mom["vol_chg_pct"]
    result.price_chg_1bar_pct = mom["price_chg_1bar_pct"]
    htf_mom_bars = HTF_MOMENTUM_BARS.get(htf, mom_bars)
    if not df_htf.empty and len(df_htf) >= htf_mom_bars + 2:
        htf_mom = compute_tf_momentum(df_htf, htf_mom_bars)
        result.htf_price_chg_pct = htf_mom["price_chg_pct"]
    result.htf_trend = _htf_trend(df_htf if not df_htf.empty else df_entry)
    result.pdh, result.pdl = _pdh_pdl(df_daily)

    if oc_data is None:
        oc_data = fetch_nse_option_chain(_option_underlying(sym), groww_token) or {}
    result.option_chain = oc_data

    if fii_data is None:
        fii_data = fetch_nse_fii_dii() or {}
    result.fii_dii = fii_data

    if td_data is None:
        td_data = fetch_nse_turnover_delivery() or {}
    result.delivery_pct = _symbol_delivery_pct(sym, td_data)

    if gift_chg is None:
        gift = fetch_gift_nifty_5paisa()
        gift_chg = float(gift.get("pct", 0)) if gift else None
    result.gift_nifty_chg = gift_chg

    at_level, level_note = _key_level_hit(df_entry, result.price)
    if result.pdh and abs(result.price - result.pdh) / result.price < 0.005:
        at_level, level_note = True, f"PDH {result.pdh:,.2f}"
    elif result.pdl and abs(result.price - result.pdl) / result.price < 0.005:
        at_level, level_note = True, f"PDL {result.pdl:,.2f}"
    result.key_level = level_note

    result.pump_signals = detect_india_pre_pump(
        df_entry, df_15m, oc_data, result.price, fii_data, gift_chg, result.delivery_pct,
    )
    result.dump_signals = detect_india_pre_dump(df_entry, df_15m, oc_data, result.price, fii_data)
    tech_pump, tech_dump, result.technical_context = detect_technical_structure_signals(df_entry)
    result.pump_signals.update(tech_pump)
    result.dump_signals.update(tech_dump)

    if index_df is None:
        index_df = fetch_india_ohlcv("NIFTY", fetch_tf, groww_token, exchange)
    if bulk_deals is None:
        from app.market_pulse.news_scanner import fetch_nse_bulk_block_deals
        bulk_deals = fetch_nse_bulk_block_deals()
    result.bulk_deals = bulk_deals or []

    from app.market_pulse.india_accuracy_boosters import (
        apply_expert_to_confluence,
        detect_expert_india_signals,
        expert_score_adjustment,
    )
    at_res = bool(result.pdh and result.price >= (result.pdh or 0) * 0.998)
    expert_pump, expert_dump, exp_warn, time_bias = detect_expert_india_signals(
        sym, df_entry, df_15m, oc_data, result.price,
        index_df=index_df,
        gift_chg=gift_chg,
        price_chg_pct=result.price_chg_pct,
        at_support=at_level,
        at_resistance=at_res,
        bulk_deals=result.bulk_deals,
    )
    result.pump_signals.update(expert_pump)
    result.dump_signals.update(expert_dump)
    result.expert_warnings = exp_warn
    result.expert_time_bias = time_bias

    ap = sum(1 for v in result.pump_signals.values() if v.get("active"))
    ad = sum(1 for v in result.dump_signals.values() if v.get("active"))
    result.bias = "pump" if ap > ad else "dump" if ad > ap else "neutral"

    pcr = oc_data.get("pcr_oi", 0)
    opt_long = (
        pcr >= 1.1
        or result.pump_signals.get("oi_bullish", {}).get("active")
        or result.pump_signals.get("oi_long_buildup", {}).get("active")
    )
    opt_short = (
        (0 < pcr < 0.85)
        or result.dump_signals.get("oi_bearish", {}).get("active")
        or result.dump_signals.get("oi_short_buildup", {}).get("active")
    )
    flow_long = (
        result.pump_signals.get("fii_buying", {}).get("active")
        or result.pump_signals.get("gift_nifty_positive", {}).get("active")
        or result.pump_signals.get("global_absorption", {}).get("active")
    )
    flow_short = result.dump_signals.get("fii_selling", {}).get("active")

    trig_l = _trigger_candle(_prep_indicators(df_entry), "long")
    trig_s = _trigger_candle(_prep_indicators(df_entry), "short")
    plan_l = build_india_trade_plan("long", entry_tf, result.price, trig_l["stop_ref"], sym)
    plan_s = build_india_trade_plan("short", entry_tf, result.price, trig_s["stop_ref"], sym)

    session_ok = phase not in ("11:30–13:00", "After hours") and datetime.now(IST).time() < dt_time(15, 10)

    result.confluence_long = score_india_confluence(
        direction="long", htf_trend=result.htf_trend, at_key_level=at_level, key_level_note=level_note,
        pump_signals=result.pump_signals, dump_signals=result.dump_signals,
        option_confirms=opt_long, flow_confirms=flow_long, trigger=trig_l, rr_ok=plan_l["rr_ok"],
        session_ok=session_ok, time_bias=time_bias,
    )
    result.confluence_short = score_india_confluence(
        direction="short", htf_trend=result.htf_trend, at_key_level=at_level, key_level_note=level_note,
        pump_signals=result.pump_signals, dump_signals=result.dump_signals,
        option_confirms=opt_short, flow_confirms=flow_short, trigger=trig_s, rr_ok=plan_s["rr_ok"],
        session_ok=session_ok, time_bias=time_bias,
    )
    adj_l, _ = expert_score_adjustment(
        "long", result.pump_signals, result.dump_signals, time_bias, False,
    )
    adj_s, _ = expert_score_adjustment(
        "short", result.pump_signals, result.dump_signals, time_bias, False,
    )
    result.confluence_long = apply_expert_to_confluence(result.confluence_long, adj_l)
    result.confluence_short = apply_expert_to_confluence(result.confluence_short, adj_s)
    if not time_bias.get("allow_entry", True):
        for plan in (plan_l, plan_s):
            plan["actionable"] = False
    plan_l["actionable"] = (
        result.confluence_long["verdict"] in ("TRADE", "STRONG")
        and time_bias.get("allow_entry", True)
    )
    plan_s["actionable"] = (
        result.confluence_short["verdict"] in ("TRADE", "STRONG")
        and time_bias.get("allow_entry", True)
    )
    result.trade_plan_long = plan_l
    result.trade_plan_short = plan_s
    return result


def scan_india_universe(
    tickers: list[str],
    entry_tf: str,
    htf: str,
    groww_token: str,
    exchange: str,
    mode: str = "BOTH",
    min_signals: int = 0,
) -> tuple[list[dict], dict]:
    from app.market_pulse.news_scanner import fetch_nse_bulk_block_deals

    fii = fetch_nse_fii_dii()
    td = fetch_nse_turnover_delivery()
    gift = fetch_gift_nifty_5paisa()
    gift_chg = float(gift.get("pct", 0)) if gift else None
    bulk_deals = fetch_nse_bulk_block_deals()
    fetch_tf = _resolve_entry_tf(entry_tf)
    index_df = fetch_india_ohlcv("NIFTY", fetch_tf, groww_token, exchange)
    oc_cache: dict[str, dict] = {}
    rows: list[dict] = []
    meta: dict = {"scanned": 0, "errors": [], "with_data": 0}
    for t in tickers:
        meta["scanned"] += 1
        try:
            und = _option_underlying(t)
            if und not in oc_cache:
                oc_cache[und] = fetch_nse_option_chain(und, groww_token) or {}
            a = analyze_india_ticker(
                t, entry_tf, htf, groww_token, exchange,
                oc_data=oc_cache[und], fii_data=fii, td_data=td, gift_chg=gift_chg,
                index_df=index_df, bulk_deals=bulk_deals,
            )
            if a.error:
                meta["errors"].append(f"{t}: {a.error}")
                continue
            meta["with_data"] += 1
            if mode in ("PUMP", "BOTH"):
                cl = a.confluence_long
                if cl["signal_count"] >= min_signals:
                    rows.append(_india_row(a, "LONG", cl))
            if mode in ("DUMP", "BOTH"):
                cs = a.confluence_short
                if cs["signal_count"] >= min_signals:
                    rows.append(_india_row(a, "SHORT", cs))
        except Exception as exc:
            meta["errors"].append(f"{t}: {exc}")
        time.sleep(0.08)
    return sorted(rows, key=lambda x: x["score"], reverse=True), meta


def _india_row(a: IndiaPumpDumpAnalysis, side: str, conf: dict) -> dict:
    sigs = a.pump_signals if side == "LONG" else a.dump_signals
    catalog = INDIA_PRE_PUMP if side == "LONG" else INDIA_PRE_DUMP
    active = [k for k, v in sigs.items() if v.get("active")]
    return {
        "symbol": a.symbol,
        "side": side,
        "price": a.price,
        "entry_tf": a.entry_tf,
        "htf": a.htf,
        "score": conf["total"],
        "verdict": conf["verdict"],
        "signals": len(active),
        "signal_detail": format_active_signal_labels(sigs, catalog),
        "signal_names": active,
        "price_chg_pct": a.price_chg_pct,
        "vol_chg_pct": a.vol_chg_pct,
        "price_chg_1bar_pct": a.price_chg_1bar_pct,
        "htf_price_chg_pct": a.htf_price_chg_pct,
        "momentum_bars": a.momentum_bars,
        "htf_trend": a.htf_trend,
        "pcr": a.option_chain.get("pcr_oi"),
        "session": a.session_phase,
        "bb_zone": (a.technical_context or {}).get("bb_zone", ""),
        "bb_note": (a.technical_context or {}).get("bb_note", ""),
        "analysis": a,
    }
