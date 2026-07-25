"""
gokul_chhabra_engine.py
-----------------------
Dr. Gokul Chhabra — FREE Option Buying Masterclass strategy.

Source: https://www.youtube.com/watch?v=2RnBT9DDDNI&t=6s

Rules (as taught):
  - Analyse Nifty (futures proxy via index) on a **3-minute** chart.
  - Indicators: session **VWAP**, **VWMA(20)**, **SuperTrend(10, 3)**.
  - Trading window: **09:45–15:15 IST** (ignore the first 30 minutes; no BTST).
  - LONG (Buy Call): close strictly **above** VWAP, VWMA, and SuperTrend.
  - SHORT (Buy Put): close strictly **below** all three.
  - Sideways / mixed alignment → no trade.
  - Prefer entries on a **VWMA pullback** when the trend is already aligned.
  - Initial SL: 3m candle close beyond SuperTrend; trail to cost at 1:1; target ≥ 1:2.
  - Execute via **ITM options**, target delta **0.60–0.75**.

Implementation notes:
  - No native 3m feed — 1m bars are resampled to 3m.
  - Nifty futures OHLC is proxied with the Nifty 50 index (same directional structure).
  - ITM option legs come from the live NSE option chain; delta via Black-Scholes N(d1).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, time as dtime
from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.indicators import add_supertrend, add_vwap
from app.market_pulse.index_ohlcv import fetch_index_ohlcv_for_interval
from app.market_pulse.option_chain_engine import INDEX_CHOICES, fetch_option_chain

logger = logging.getLogger(__name__)

YOUTUBE_GOKUL_CHHABRA_URL = "https://www.youtube.com/watch?v=2RnBT9DDDNI&t=6s"

INDEX_NAMES = ["Nifty 50", "Bank Nifty"]
_INDEX_TO_OPTION_SYMBOL = {"Nifty 50": "NIFTY", "Bank Nifty": "BANKNIFTY"}
_MIN_BARS = 40


def _norm_cdf(x: float) -> float:
    """Standard normal CDF (Abramowitz & Stegun approximation)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


@dataclass
class GokulChhabraConfig:
    vwma_length: int = 20
    st_period: int = 10
    st_multiplier: float = 3.0
    session_start: str = "09:45"
    session_end: str = "15:15"
    pullback_tol_pct: float = 0.08  # % of price — how close to VWMA counts as a pullback touch
    min_rr: float = 2.0
    trail_be_rr: float = 1.0
    target_delta_min: float = 0.60
    target_delta_max: float = 0.75
    risk_free_rate: float = 0.065


def _parse_hhmm(s: str) -> dtime:
    return datetime.strptime(s.strip(), "%H:%M").time()


def _add_vwma(df: pd.DataFrame, length: int = 20) -> pd.DataFrame:
    vol = df["volume"].replace(0, np.nan)
    df["vwma"] = (df["close"] * df["volume"]).rolling(length).sum() / vol.rolling(length).sum()
    return df


def _fetch_3min_ohlcv(
    index_name: str, *, groww_token: str = "", exchange: str = "NSE", limit: int = 300,
) -> pd.DataFrame:
    """1-minute index OHLC resampled to 3-minute bars (futures proxy)."""
    df_1m = fetch_index_ohlcv_for_interval(
        index_name, "1m", limit=limit * 3 + 90, groww_token=groww_token, exchange=exchange,
    )
    if df_1m is None or df_1m.empty:
        return pd.DataFrame()
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in df_1m.columns:
        agg["volume"] = "sum"
    else:
        df_1m = df_1m.copy()
        df_1m["volume"] = 1.0
        agg["volume"] = "sum"
    resampled = df_1m.resample("3min").agg(agg).dropna(subset=["open", "high", "low", "close"])
    return resampled.tail(limit)


def _prepare_indicators(df: pd.DataFrame, cfg: GokulChhabraConfig) -> pd.DataFrame:
    out = df.copy()
    if "volume" not in out.columns:
        out["volume"] = 1.0
    out = add_vwap(out)
    out = _add_vwma(out, cfg.vwma_length)
    out = add_supertrend(out, period=cfg.st_period, multiplier=cfg.st_multiplier)
    # Canonical short names used by the scanner
    st_col = f"supertrend_{cfg.st_period}_{cfg.st_multiplier}"
    st_dir_col = f"supertrend_dir_{cfg.st_period}_{cfg.st_multiplier}"
    out["supertrend"] = out[st_col]
    out["supertrend_dir"] = out[st_dir_col]
    return out


def _in_session(ts, start: dtime, end: dtime) -> bool:
    t = ts.time() if hasattr(ts, "time") else dtime(0, 0)
    return start <= t <= end


def _alignment(close: float, vwap: float, vwma: float, st: float) -> str:
    if close > vwap and close > vwma and close > st:
        return "BULL"
    if close < vwap and close < vwma and close < st:
        return "BEAR"
    return "SIDEWAYS"


def scan_gokul_chhabra_signals(
    df: pd.DataFrame, cfg: GokulChhabraConfig | None = None,
) -> list[dict[str, Any]]:
    """
    Scan 3m bars for aligned trend + optional VWMA pullback entries.
    Returns chronological signal dicts (not every trend bar — only entries).
    """
    cfg = cfg or GokulChhabraConfig()
    if df is None or df.empty or len(df) < _MIN_BARS:
        return []

    work = _prepare_indicators(df, cfg)
    start, end = _parse_hhmm(cfg.session_start), _parse_hhmm(cfg.session_end)
    tol = cfg.pullback_tol_pct / 100.0
    signals: list[dict[str, Any]] = []
    prev_align = "SIDEWAYS"

    for i in range(len(work)):
        ts = work.index[i]
        if not _in_session(ts, start, end):
            prev_align = "SIDEWAYS"
            continue

        row = work.iloc[i]
        close = float(row["close"])
        vwap, vwma, st = row.get("vwap"), row.get("vwma"), row.get("supertrend")
        if pd.isna(vwap) or pd.isna(vwma) or pd.isna(st):
            continue

        vwap_f, vwma_f, st_f = float(vwap), float(vwma), float(st)
        align = _alignment(close, vwap_f, vwma_f, st_f)
        if align == "SIDEWAYS":
            prev_align = align
            continue

        lo, hi = float(row["low"]), float(row["high"])
        touched_vwma = lo <= vwma_f * (1 + tol) and hi >= vwma_f * (1 - tol)
        near_vwma = abs(close - vwma_f) / max(abs(close), 1e-9) <= tol

        entry_kind = None
        if prev_align != align:
            entry_kind = "BREAKOUT"
        elif touched_vwma or near_vwma:
            entry_kind = "PULLBACK"

        if entry_kind:
            risk = abs(close - st_f)
            if risk <= 0:
                prev_align = align
                continue
            direction = "LONG" if align == "BULL" else "SHORT"
            stop = st_f
            if direction == "LONG":
                target = close + cfg.min_rr * risk
                be_level = close + cfg.trail_be_rr * risk
            else:
                target = close - cfg.min_rr * risk
                be_level = close - cfg.trail_be_rr * risk

            signals.append({
                "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                "direction": direction,
                "entry_kind": entry_kind,
                "price": round(close, 4),
                "vwap": round(vwap_f, 4),
                "vwma": round(vwma_f, 4),
                "supertrend": round(st_f, 4),
                "stop": round(stop, 4),
                "be_level": round(be_level, 4),
                "target": round(target, 4),
                "risk_points": round(risk, 4),
                "min_rr": cfg.min_rr,
                "option_action": "BUY CALL" if direction == "LONG" else "BUY PUT",
            })

        prev_align = align

    return signals


def _parse_nse_expiry(s: str) -> date | None:
    for fmt in ("%d-%b-%Y", "%d-%b-%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def select_itm_option_leg(
    index_name: str, direction: str, spot: float, cfg: GokulChhabraConfig, groww_token: str = "",
) -> dict[str, Any] | None:
    """Pick an ITM CE/PE near the 0.60–0.75 delta band from the live NSE chain."""
    symbol = _INDEX_TO_OPTION_SYMBOL.get(index_name, "")
    if not symbol or symbol not in INDEX_CHOICES:
        return None
    chain = fetch_option_chain(symbol, True, groww_token)
    if not chain:
        return None
    strikes = chain.get("strikes") or []
    if not strikes:
        return None

    expiry = chain.get("current_expiry")
    expiry_date = _parse_nse_expiry(expiry) if expiry else None
    dte = max(((expiry_date - date.today()).days if expiry_date else 7), 1)
    t_years = dte / 365.0
    opt_side = "ce" if direction == "LONG" else "pe"

    candidates: list[dict[str, Any]] = []
    for s in strikes:
        strike = s.get("strike")
        if strike is None:
            continue
        itm_points = (spot - strike) if direction == "LONG" else (strike - spot)
        if itm_points <= 0:
            continue
        ltp = s.get(f"{opt_side}_ltp") or 0
        if ltp <= 0:
            continue
        iv_raw = s.get(f"{opt_side}_iv") or 0
        vol = max(float(iv_raw), 1.0) / 100.0
        try:
            d1 = (math.log(spot / strike) + (cfg.risk_free_rate + 0.5 * vol ** 2) * t_years) / (
                vol * math.sqrt(t_years)
            )
            delta = _norm_cdf(d1) if opt_side == "ce" else _norm_cdf(d1) - 1
        except (ValueError, ZeroDivisionError):
            continue
        candidates.append({
            "strike": strike, "premium": float(ltp), "iv": iv_raw,
            "delta": round(abs(delta), 3), "itm_points": round(float(itm_points), 1),
        })

    if not candidates:
        return None

    mid = (cfg.target_delta_min + cfg.target_delta_max) / 2
    in_band = [c for c in candidates if cfg.target_delta_min <= c["delta"] <= cfg.target_delta_max]
    pool = in_band or candidates
    best = min(pool, key=lambda c: abs(c["delta"] - mid))
    entry = best["premium"]
    # Map underlying R:R onto option premium as a reference (delta-scaled, heuristic).
    delta_scale = max(best["delta"], 0.5)
    # Without underlying risk in this helper alone, use a modest premium R:R frame;
    # analyze_* overwrites stop/target using the SuperTrend risk when available.
    return {
        "option_type": "CE" if direction == "LONG" else "PE",
        "strike": best["strike"], "expiry": expiry, "premium": entry,
        "iv": best["iv"], "delta": best["delta"], "itm_points": best["itm_points"],
        "delta_scale": delta_scale,
        "in_target_delta_band": bool(in_band),
        "source": "NSE live chain",
    }


def analyze_gokul_chhabra(
    index_name: str, *, cfg: GokulChhabraConfig | None = None,
    groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or GokulChhabraConfig()
    df = _fetch_3min_ohlcv(index_name, groww_token=groww_token, exchange=exchange)
    if df is None or df.empty or len(df) < _MIN_BARS:
        return {
            "ticker": index_name,
            "error": f"Insufficient 3-minute data ({0 if df is None else len(df)} bars, need {_MIN_BARS}+).",
        }

    signals = scan_gokul_chhabra_signals(df, cfg)
    work = _prepare_indicators(df, cfg)
    last = work.iloc[-1]
    last_ts = work.index[-1]
    spot = float(last["close"])
    vwap = float(last["vwap"]) if not pd.isna(last.get("vwap")) else None
    vwma = float(last["vwma"]) if not pd.isna(last.get("vwma")) else None
    st = float(last["supertrend"]) if not pd.isna(last.get("supertrend")) else None

    start, end = _parse_hhmm(cfg.session_start), _parse_hhmm(cfg.session_end)
    last_bar_time = last_ts.time() if hasattr(last_ts, "time") else dtime(0, 0)
    in_window = _in_session(last_ts, start, end)

    align = "SIDEWAYS"
    if vwap is not None and vwma is not None and st is not None:
        align = _alignment(spot, vwap, vwma, st)

    today_str = date.today().isoformat()
    today_signals = [s for s in signals if s["timestamp"].startswith(today_str)]
    last_signal = today_signals[-1] if today_signals else None
    is_fresh = bool(
        last_signal
        and last_signal["timestamp"] == (last_ts.isoformat() if hasattr(last_ts, "isoformat") else str(last_ts))
    )

    reasons: list[str] = [
        f"3m chart (1m resampled) · VWAP / VWMA({cfg.vwma_length}) / SuperTrend({cfg.st_period},{cfg.st_multiplier:g}).",
        f"Session window {cfg.session_start}–{cfg.session_end} IST — last candle {last_bar_time.strftime('%H:%M')} "
        + ("inside" if in_window else "outside") + " the window.",
        f"Alignment: **{align}** — "
        + (
            "price above VWAP, VWMA, and SuperTrend."
            if align == "BULL"
            else "price below VWAP, VWMA, and SuperTrend."
            if align == "BEAR"
            else "price trapped between indicators (sideways — no trade)."
        ),
    ]
    if vwap is not None and vwma is not None and st is not None:
        reasons.append(
            f"Levels — spot {spot:,.2f} · VWAP {vwap:,.2f} · VWMA {vwma:,.2f} · SuperTrend {st:,.2f}."
        )

    verdict = "WAIT"
    option_leg = None
    trade_plan: dict[str, Any] | None = None
    confidence_pct = 0.0

    if is_fresh and in_window and last_signal and align in ("BULL", "BEAR"):
        verdict = last_signal["direction"]
        confidence_pct = 85.0 if last_signal["entry_kind"] == "PULLBACK" else 70.0
        reasons.append(
            f"Trigger: **{last_signal['entry_kind']}** {last_signal['option_action']} on the last completed 3m candle "
            f"(risk {last_signal['risk_points']} pts to SuperTrend · target {cfg.min_rr:.0f}R · trail to BE at {cfg.trail_be_rr:.0f}R)."
        )
        try:
            option_leg = select_itm_option_leg(index_name, verdict, spot, cfg, groww_token)
        except Exception as exc:
            logger.debug("Option leg selection failed for %s: %s", index_name, exc)

        risk = last_signal["risk_points"]
        if option_leg:
            premium = option_leg["premium"]
            delta_scale = option_leg.get("delta_scale") or option_leg["delta"]
            opt_risk = max(round(risk * delta_scale, 2), 1.0)
            option_leg["stop_price"] = round(premium - opt_risk, 4)
            option_leg["be_price"] = round(premium, 4)  # cost-to-cost after 1R
            option_leg["target_price"] = round(premium + cfg.min_rr * opt_risk, 4)
            option_leg["sl_points"] = opt_risk
            option_leg["rr"] = cfg.min_rr
            reasons.append(
                f"Suggested leg: {option_leg['option_type']} {option_leg['strike']} "
                f"(expiry {option_leg.get('expiry', '—')}) · premium {option_leg['premium']} · "
                f"delta {option_leg['delta']} · {option_leg.get('itm_points')} pts ITM."
            )
            if not option_leg.get("in_target_delta_band"):
                reasons.append("Closest available strike to the 0.60–0.75 delta band (exact band empty).")
        else:
            reasons.append("No NSE option-chain data for an ITM strike — underlying signal only.")

        trade_plan = {
            "direction": verdict,
            "entry": last_signal["price"],
            "stop_loss": last_signal["stop"],
            "take_profit": last_signal["target"],
            "be_trail": last_signal["be_level"],
            "risk_points": risk,
            "min_rr": cfg.min_rr,
            "holding_period": f"Intraday — flat by {cfg.session_end} IST (no BTST)",
            "exit_rule": (
                f"Exit if a 3m candle closes beyond SuperTrend; at 1:1 move SL to cost; "
                f"target ≥ 1:{cfg.min_rr:g}."
            ),
        }
    elif last_signal:
        reasons.append(
            f"Most recent qualifying setup was {last_signal['direction']} ({last_signal['entry_kind']}) "
            f"at {last_signal['timestamp']} — not the current candle."
        )
        if not in_window:
            reasons.append("Outside the 09:45–15:15 IST entry window.")
    else:
        reasons.append("No breakout or VWMA-pullback entry found in the fetched window.")

    take_trade = verdict in ("LONG", "SHORT")
    sl_pct = tp_pct = None
    if option_leg and option_leg.get("premium"):
        prem = option_leg["premium"]
        sl_pts = option_leg.get("sl_points") or 0
        sl_pct = round(sl_pts / prem * 100, 2) if prem else None
        tp_pct = round(cfg.min_rr * sl_pts / prem * 100, 2) if prem else None

    return {
        "ticker": index_name,
        "spot": round(spot, 4),
        "verdict": verdict,
        "alignment": align,
        "vwap": round(vwap, 4) if vwap is not None else None,
        "vwma": round(vwma, 4) if vwma is not None else None,
        "supertrend": round(st, 4) if st is not None else None,
        "signals_today": today_signals,
        "all_signals": signals,
        "option_leg": option_leg,
        "trade_plan": trade_plan,
        "reasons": reasons,
        "last_bar_time": last_bar_time.strftime("%H:%M"),
        "in_session": in_window,
        "data_note": "Nifty futures proxied via index OHLC (1m→3m resample).",
        "live": {
            "take_trade": take_trade,
            "verdict": "TAKE LONG" if verdict == "LONG" else "TAKE SHORT" if verdict == "SHORT" else "WAIT",
            "direction": verdict if take_trade else None,
            "phase": align,
            "confidence_pct": confidence_pct if take_trade else 0.0,
            "sl_pct": sl_pct,
            "tp_pct": tp_pct,
            "hold_duration": f"Intraday — flat by {cfg.session_end} IST (no BTST)",
            "reasons": reasons,
            "entry_price": (trade_plan or {}).get("entry"),
            "stop_price": (trade_plan or {}).get("stop_loss"),
            "target_price": (trade_plan or {}).get("target"),
        },
    }


def analyze_gokul_chhabra_many(
    index_names: list[str], *, cfg: GokulChhabraConfig | None = None,
    groww_token: str = "", exchange: str = "NSE",
) -> list[dict[str, Any]]:
    results = []
    for name in index_names:
        try:
            results.append(
                analyze_gokul_chhabra(name, cfg=cfg, groww_token=groww_token, exchange=exchange)
            )
        except Exception as exc:
            logger.debug("Gokul Chhabra scan failed for %s: %s", name, exc)
            results.append({"ticker": name, "error": str(exc)[:200]})
    return results


def scan_universe(
    tickers: list[str], market: str, *,
    cfg: GokulChhabraConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    """Trading-hubs / Options API entry — always scans INDEX_NAMES (ignores tickers)."""
    cfg = cfg or GokulChhabraConfig()
    names = [n for n in (tickers or INDEX_NAMES) if n in INDEX_NAMES] or list(INDEX_NAMES)
    raw = analyze_gokul_chhabra_many(names, cfg=cfg, groww_token=groww_token, exchange=exchange)

    results: list[dict[str, Any]] = []
    for r in raw:
        ticker = r.get("ticker", "?")
        if r.get("error"):
            results.append({"ticker": ticker, "error": r["error"]})
            continue
        live = r.get("live") or {}
        results.append({
            "ticker": ticker,
            "last_close": r.get("spot"),
            "alignment": r.get("alignment"),
            "option_leg": r.get("option_leg"),
            "trade_plan": r.get("trade_plan"),
            "signals_today": r.get("signals_today"),
            "data_note": r.get("data_note"),
            "live": live,
            "reasons": r.get("reasons"),
        })

    entries = [r for r in results if not r.get("error") and (r.get("live") or {}).get("take_trade")]
    return {
        "market": market,
        "results": results,
        "entries": entries,
        "entry_count": len(entries),
        "strategy": "Gokul Chhabra — 3m VWAP · VWMA · SuperTrend ITM Option Buying",
        "youtube": YOUTUBE_GOKUL_CHHABRA_URL,
        "fixed_universe": list(INDEX_NAMES),
    }
