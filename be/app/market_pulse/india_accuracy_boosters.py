"""
india_accuracy_boosters.py
--------------------------
Expert-level accuracy signals for India pump/dump: institutional flow, vol+candle,
relative strength, EMA ribbon, OI matrix, second entry, session traps.
"""

from __future__ import annotations

from datetime import datetime, time as dt_time
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from app.market_pulse.indicators import add_ema, add_vwap
from app.market_pulse.news_scanner import fetch_nse_bulk_block_deals
from app.market_pulse.pump_dump_predictor import _prep_indicators

IST = ZoneInfo("Asia/Kolkata")

EXPERT_PUMP_KEYS = (
    "vol_absorption",
    "institutional_support",
    "relative_strength",
    "ema_ribbon_bull",
    "oi_long_buildup",
    "second_entry_long",
    "coil_breakout_ready",
    "global_absorption",
)

EXPERT_DUMP_KEYS = (
    "weak_green_trap",
    "wick_rejection",
    "institutional_supply",
    "relative_weakness",
    "ema_ribbon_bear",
    "oi_short_buildup",
    "second_entry_short",
    "max_pain_expiry_fade",
)

EXPERT_TIME_WINDOWS: list[tuple[dt_time, dt_time, str, str, int]] = [
    (dt_time(9, 15), dt_time(9, 20), "AVOID", "9:15–9:20 trap candle — algos hunt stops; observe only", -15),
    (dt_time(9, 20), dt_time(9, 45), "WAIT", "Opening range forming — wait for 15m close", -5),
    (dt_time(9, 45), dt_time(10, 15), "PRIME", "10:00–10:15 institutional wave — best morning entries", 8),
    (dt_time(10, 15), dt_time(11, 0), "GOOD", "Morning trend continuation window", 5),
    (dt_time(11, 0), dt_time(11, 15), "CAUTION", "11:00–11:15 minor reversal — tighten stops", -5),
    (dt_time(11, 30), dt_time(13, 0), "AVOID", "Dead zone — low volume whipsaws", -12),
    (dt_time(14, 0), dt_time(14, 15), "GOOD", "14:00–14:15 European flow — fresh directional move", 6),
    (dt_time(15, 0), dt_time(15, 15), "CAUTION", "3:00–3:15 institutional squaring — day close bias", 0),
    (dt_time(15, 10), dt_time(15, 30), "AVOID", "After 15:10 — no new MIS entries", -20),
]


def get_expert_time_bias(now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(IST)
    t = now.time()
    for start, end, action, note, adj in EXPERT_TIME_WINDOWS:
        if start <= t < end:
            return {
                "action": action,
                "note": note,
                "score_adj": adj,
                "allow_entry": action in ("PRIME", "GOOD"),
            }
    if t < dt_time(9, 15) or t > dt_time(15, 30):
        return {"action": "CLOSED", "note": "Market closed", "score_adj": 0, "allow_entry": False}
    return {"action": "OK", "note": "Standard session window", "score_adj": 0, "allow_entry": True}


def _session_change_pct(df: pd.DataFrame) -> float | None:
    if df is None or df.empty or not isinstance(df.index, pd.DatetimeIndex):
        return None
    last_day = df.index[-1].date()
    day = df[df.index.date == last_day]
    if len(day) < 2:
        return None
    o, c = float(day["open"].iloc[0]), float(day["close"].iloc[-1])
    if o <= 0:
        return None
    return (c - o) / o * 100


def _relative_strength(stock_df: pd.DataFrame, index_df: pd.DataFrame) -> tuple[bool, bool, str]:
    stock_chg = _session_change_pct(stock_df)
    idx_chg = _session_change_pct(index_df)
    if stock_chg is None or idx_chg is None:
        return False, False, "RS vs Nifty — insufficient intraday bars"
    rs = stock_chg - idx_chg
    note = f"Stock {stock_chg:+.2f}% vs Nifty {idx_chg:+.2f}% · RS {rs:+.2f}%"
    strong = rs >= 0.15 and stock_chg > -0.05
    weak = rs <= -0.15 and stock_chg < 0.05
    if strong:
        note += " — outperforming (long bias)"
    elif weak:
        note += " — underperforming (short bias)"
    return strong, weak, note


def _ema_ribbon_state(df: pd.DataFrame) -> tuple[bool, bool, bool, str]:
    if len(df) < 30:
        return False, False, False, "EMA ribbon — need more bars"
    d = add_ema(add_ema(df.copy(), 9), 21)
    e9, e21 = d["ema_9"], d["ema_21"]
    close = float(d["close"].iloc[-1])
    sep = abs(float(e9.iloc[-1]) - float(e21.iloc[-1])) / (close + 1e-12) * 100
    sep_prev = abs(float(e9.iloc[-5]) - float(e21.iloc[-5])) / (close + 1e-12) * 100
    compressing = sep < sep_prev * 0.85 and sep < 0.2
    bull = float(e9.iloc[-1]) > float(e21.iloc[-1]) and close > float(e21.iloc[-1])
    bear = float(e9.iloc[-1]) < float(e21.iloc[-1]) and close < float(e21.iloc[-1])
    widening_bull = bull and sep > sep_prev * 1.05 and sep > 0.08
    widening_bear = bear and sep > sep_prev * 1.05 and sep > 0.08
    touch_9_support = bull and abs(close - float(e9.iloc[-1])) / close < 0.003
    note = f"EMA9/21 sep {sep:.2f}%"
    if compressing:
        note += " — compressing (breakout coil)"
    elif widening_bull or touch_9_support:
        note += " — bullish ribbon / 9 EMA support"
    elif widening_bear:
        note += " — bearish ribbon widening"
    return widening_bull or touch_9_support, widening_bear, compressing, note


def _candle_volume_patterns(df: pd.DataFrame, at_support: bool, at_resistance: bool) -> dict[str, tuple[bool, str]]:
    out: dict[str, tuple[bool, str]] = {}
    if len(df) < 20:
        return out
    row = df.iloc[-1]
    vol_avg = float(df["volume"].iloc[-21:-1].mean())
    vol_ratio = float(row["volume"]) / (vol_avg + 1e-9)
    body = float(row["close"] - row["open"])
    body_pct = abs(body) / (float(row["close"]) + 1e-12) * 100
    rng = float(row["high"] - row["low"]) + 1e-12
    upper_wick = float(row["high"] - max(row["open"], row["close"])) / rng
    green = body > 0

    weak_trap = green and body_pct >= 0.35 and vol_ratio < 0.85
    out["weak_green_trap"] = (
        weak_trap,
        f"Green {body_pct:.2f}% body but vol only {vol_ratio:.1f}x avg — weak chase",
    )
    strong_green = green and body_pct >= 0.25 and vol_ratio >= 1.4
    out["strong_green_vol"] = (
        strong_green,
        f"Green {body_pct:.2f}% + vol {vol_ratio:.1f}x — institutional buying",
    )
    absorption = body < 0 and body_pct < 0.25 and vol_ratio >= 1.5 and at_support
    out["vol_absorption"] = (
        absorption,
        f"Small red + vol {vol_ratio:.1f}x at support — absorption",
    )
    wick_rej = upper_wick >= 0.55 and vol_ratio >= 1.3 and at_resistance
    out["wick_rejection"] = (
        wick_rej,
        f"Upper wick {upper_wick:.0%} + vol {vol_ratio:.1f}x at resistance",
    )
    prev = df.iloc[-2]
    inside = (
        row["high"] <= prev["high"] and row["low"] >= prev["low"]
        and vol_ratio < 0.75
    )
    out["coil_breakout_ready"] = (
        inside,
        f"Inside bar + shrinking vol ({vol_ratio:.1f}x) — energy coiling",
    )
    return out


def _oi_price_matrix(oc: dict | None, price_chg_pct: float | None) -> tuple[bool, bool, str]:
    if not oc or price_chg_pct is None:
        return False, False, "OI matrix — data n/a"
    strikes = oc.get("strikes") or []
    if not strikes:
        return False, False, "OI matrix — no strikes"
    d_oi = sum(
        (s.get("ce_chg_oi", 0) or 0) + (s.get("pe_chg_oi", 0) or 0) for s in strikes
    )
    price_up = price_chg_pct > 0.05
    price_down = price_chg_pct < -0.05
    oi_up = d_oi > 0
    oi_down = d_oi < 0
    if price_up and oi_up:
        return True, False, f"Long buildup — price {price_chg_pct:+.2f}% · ΔOI {d_oi:+,.0f}"
    if price_down and oi_up:
        return False, True, f"Short buildup — price {price_chg_pct:+.2f}% · ΔOI {d_oi:+,.0f}"
    if price_up and oi_down:
        return False, False, f"Short covering (weaker) — price {price_chg_pct:+.2f}% · ΔOI {d_oi:+,.0f}"
    if price_down and oi_down:
        return False, False, f"Long unwinding — price {price_chg_pct:+.2f}% · ΔOI {d_oi:+,.0f}"
    return False, False, f"Mixed OI — price {price_chg_pct:+.2f}% · ΔOI {d_oi:+,.0f}"


def _institutional_levels(
    symbol: str,
    price: float,
    deals: list[dict],
) -> tuple[bool, bool, str]:
    sym = symbol.upper().replace(".NS", "")
    sym_deals = [d for d in deals if (d.get("symbol") or "").upper() == sym]
    if not sym_deals:
        return False, False, "No bulk/block deals for symbol today"
    supports: list[float] = []
    resistances: list[float] = []
    notes: list[str] = []
    for d in sym_deals[:5]:
        dp = float(d.get("price") or 0)
        if dp <= 0:
            continue
        side = (d.get("side") or d.get("buy_sell") or "").upper()
        dist = abs(price - dp) / price
        tag = f"{'BUY' if 'B' in side[:1] else 'SELL'} @ ₹{dp:,.2f}"
        if dist <= 0.02:
            notes.append(tag)
            if not side or "B" in side[:1] or side == "BUY":
                supports.append(dp)
            else:
                resistances.append(dp)
    sup_ok = bool(supports) and price >= min(supports) * 0.995
    res_ok = bool(resistances) and price <= max(resistances) * 1.005
    note = " · ".join(notes[:3]) if notes else f"{len(sym_deals)} deal(s) — none at current price"
    return sup_ok, res_ok, note


def _opening_range_levels(df_15m: pd.DataFrame) -> tuple[float | None, float | None]:
    if df_15m.empty or not isinstance(df_15m.index, pd.DatetimeIndex):
        return None, None
    last_day = df_15m.index[-1].date()
    day = df_15m[df_15m.index.date == last_day]
    if day.empty:
        day = df_15m.tail(1)
    bar = day.iloc[0]
    return float(bar["high"]), float(bar["low"])


def _second_entry(
    df_entry: pd.DataFrame,
    df_15m: pd.DataFrame,
    direction: str,
) -> tuple[bool, str]:
    or_high, or_low = _opening_range_levels(df_15m)
    if or_high is None or len(df_entry) < 25:
        return False, "Second entry — ORB levels n/a"
    d = df_entry.tail(20)
    price = float(d["close"].iloc[-1])
    vol = d["volume"]
    if direction == "long":
        broke = (d["close"] > or_high).any()
        if not broke:
            return False, f"No ORB breakout above {or_high:,.2f} yet"
        pullback = price <= or_high * 1.004 and price >= or_high * 0.996
        vol_drop = float(vol.iloc[-3:].mean()) < float(vol.iloc[-10:-3].mean()) * 0.85
        ok = pullback and vol_drop and price > or_low
        return ok, f"Retest OR high {or_high:,.2f} · vol fade on pullback"
    broke = (d["close"] < or_low).any()
    if not broke:
        return False, f"No ORB breakdown below {or_low:,.2f} yet"
    pullback = price >= or_low * 0.996 and price <= or_low * 1.004
    vol_drop = float(vol.iloc[-3:].mean()) < float(vol.iloc[-10:-3].mean()) * 0.85
    ok = pullback and vol_drop and price < or_high
    return ok, f"Retest OR low {or_low:,.2f} · vol fade on pullback"


def _max_pain_expiry_bias(oc: dict | None, price: float) -> tuple[bool, str]:
    if not oc:
        return False, "Max pain n/a"
    mp = oc.get("max_pain")
    if not mp or price <= 0:
        return False, "Max pain n/a"
    dist_pct = (price - mp) / price * 100
    expiry = oc.get("current_expiry", "")
    if abs(dist_pct) < 0.35:
        return False, f"At max pain {mp:,.0f} — pin risk"
    if dist_pct > 0.8:
        return True, f"Spot {price:,.0f} above max pain {mp:,.0f} ({dist_pct:+.1f}%) — expiry fade down bias"
    return False, f"Max pain {mp:,.0f} vs spot {price:,.0f}"


def _global_absorption(gift_chg: float | None, stock_chg: float | None) -> tuple[bool, str]:
    if gift_chg is None or stock_chg is None:
        return False, "Global cue — Gift Nifty n/a"
    if gift_chg <= -0.25 and stock_chg > gift_chg + 0.2:
        return True, f"Gift {gift_chg:+.2f}% but stock {stock_chg:+.2f}% — absorbing weak global cue"
    return False, f"Gift {gift_chg:+.2f}% · stock {stock_chg:+.2f}%"


def detect_expert_india_signals(
    symbol: str,
    df_entry: pd.DataFrame,
    df_15m: pd.DataFrame,
    oc: dict | None,
    price: float,
    *,
    index_df: pd.DataFrame | None = None,
    gift_chg: float | None = None,
    price_chg_pct: float | None = None,
    at_support: bool = False,
    at_resistance: bool = False,
    bulk_deals: list[dict] | None = None,
) -> tuple[dict[str, dict], dict[str, dict], list[str], dict[str, Any]]:
    """Return (expert_pump_signals, expert_dump_signals, warnings, time_bias)."""
    pump: dict[str, dict] = {}
    dump: dict[str, dict] = {}
    warnings: list[str] = []

    time_bias = get_expert_time_bias()
    if time_bias["action"] in ("AVOID", "WAIT"):
        warnings.append(f"⏱ {time_bias['note']}")
    elif time_bias["action"] == "CAUTION":
        warnings.append(f"⚠️ {time_bias['note']}")

    if bulk_deals is None:
        try:
            bulk_deals = fetch_nse_bulk_block_deals()
        except Exception:
            bulk_deals = []

    cv = _candle_volume_patterns(df_entry, at_support, at_resistance)
    ok, note = cv.get("vol_absorption", (False, ""))
    pump["vol_absorption"] = {"active": ok, "note": note}
    ok, note = cv.get("coil_breakout_ready", (False, ""))
    pump["coil_breakout_ready"] = {"active": ok, "note": note}
    ok, note = cv.get("strong_green_vol", (False, ""))
    if ok:
        pump["vol_absorption"] = {"active": True, "note": note}

    ok, note = cv.get("weak_green_trap", (False, ""))
    dump["weak_green_trap"] = {"active": ok, "note": note}
    if ok:
        warnings.append("Trap: big green candle on low volume — don't chase longs")
    ok, note = cv.get("wick_rejection", (False, ""))
    dump["wick_rejection"] = {"active": ok, "note": note}

    sup, res, note = _institutional_levels(symbol, price, bulk_deals or [])
    pump["institutional_support"] = {"active": sup, "note": note}
    dump["institutional_supply"] = {"active": res, "note": note}

    if index_df is not None and not index_df.empty:
        rs_long, rs_short, rs_note = _relative_strength(df_entry, index_df)
        pump["relative_strength"] = {"active": rs_long, "note": rs_note}
        dump["relative_weakness"] = {"active": rs_short, "note": rs_note}
    else:
        pump["relative_strength"] = {"active": False, "note": "RS vs Nifty — index data n/a"}
        dump["relative_weakness"] = {"active": False, "note": "RS vs Nifty — index data n/a"}

    bull, bear, coil, rib_note = _ema_ribbon_state(df_entry)
    pump["ema_ribbon_bull"] = {"active": bull or coil, "note": rib_note}
    dump["ema_ribbon_bear"] = {"active": bear, "note": rib_note}

    lb, sb, oi_note = _oi_price_matrix(oc, price_chg_pct)
    pump["oi_long_buildup"] = {"active": lb, "note": oi_note}
    dump["oi_short_buildup"] = {"active": sb, "note": oi_note}

    ok, note = _second_entry(df_entry, df_15m, "long")
    pump["second_entry_long"] = {"active": ok, "note": note}
    ok, note = _second_entry(df_entry, df_15m, "short")
    dump["second_entry_short"] = {"active": ok, "note": note}

    stock_chg = _session_change_pct(df_entry)
    ok, note = _global_absorption(gift_chg, stock_chg)
    pump["global_absorption"] = {"active": ok, "note": note}

    ok, note = _max_pain_expiry_bias(oc, price)
    dump["max_pain_expiry_fade"] = {"active": ok, "note": note}

    return pump, dump, warnings, time_bias


def expert_score_adjustment(
    direction: str,
    pump: dict,
    dump: dict,
    time_bias: dict,
    opposing_trap: bool,
) -> tuple[int, list[str]]:
    """Trap penalties and high-quality entry bonuses (signals already score via stack)."""
    sigs = pump if direction == "long" else dump
    details: list[str] = []
    bonus = 0
    penalty = 0

    second_key = "second_entry_long" if direction == "long" else "second_entry_short"
    if sigs.get(second_key, {}).get("active"):
        bonus += 5
        details.append("+5 second-entry retest")
    if sigs.get("institutional_support" if direction == "long" else "institutional_supply", {}).get("active"):
        bonus += 4
        details.append("+4 institutional footprint at price")
    if sigs.get("resistance_breakout" if direction == "long" else "support_breakdown", {}).get("active"):
        bonus += 4
        details.append("+4 S/R breakout/breakdown confirmation")

    if not time_bias.get("allow_entry", True):
        penalty += abs(min(0, time_bias.get("score_adj", 0)))
        details.append(f"time window {time_bias.get('action')}")
    if direction == "long" and dump.get("weak_green_trap", {}).get("active"):
        penalty += 10
        details.append("weak green trap vs long")
    if direction == "short" and pump.get("vol_absorption", {}).get("active"):
        penalty += 6
        details.append("absorption vs short")
    if opposing_trap:
        penalty += 5

    return bonus - penalty, details


def apply_expert_to_confluence(conf: dict, adj: int, min_verdict_thresholds: bool = True) -> dict:
    """Apply expert adjustment and recompute verdict."""
    conf = dict(conf)
    conf["expert_adj"] = adj
    conf["total"] = max(0, min(100, conf.get("total", 0) + adj))
    sig = conf.get("signal_count", 0)
    total = conf["total"]
    if total >= 75 and sig >= 3:
        conf["verdict"] = "STRONG"
    elif total >= 55 and sig >= 3:
        conf["verdict"] = "TRADE"
    elif total >= 38:
        conf["verdict"] = "WATCH"
    else:
        conf["verdict"] = "SKIP"
    if min_verdict_thresholds and not conf.get("min_signals_met"):
        if conf["verdict"] in ("TRADE", "STRONG"):
            conf["verdict"] = "WATCH"
    return conf
