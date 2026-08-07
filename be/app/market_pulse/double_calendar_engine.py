"""
double_calendar_engine.py
---------------------------
Double Calendar (and Double Diagonal) options income strategy — a delta-neutral,
theta-positive spread that sells near-term calls/puts and buys further-dated
calls/puts at the same (Double Calendar) or wider (Double Diagonal) strikes,
profiting from the difference in time decay between the two expiries.

Setup:
  - Sell a Call + Put ~2 weeks out (short legs).
  - Buy a Call + Put ~1 week later, ~3 weeks out (long legs).
  - Strikes: short legs a fixed % out of the money; long legs the same strike
    (Double Calendar) or further out (Double Diagonal, widens the profit zone).
  - Entry gate: only in a low-IV environment (VIX in its lower range, not spiking) —
    this is a positive-Vega strategy that loses fast if IV crashes after entry.
  - Management: scale out from 20% profit, close by 40%; a 30% *mental* stop
    (no hard broker stop — wide bid/ask spreads can trigger it prematurely).

Data sources (real where available, otherwise a disclosed simulation):
  - India (NSE indices/stocks): live NSE option-chain-v3 strikes/premiums/IV for
    the nearest listed expiries to the target short/long DTE.
  - US: live Yahoo Finance option chain (yfinance) for the nearest listed expiries.
  - Crypto / Commodities: no listed options-chain feed is integrated for these
    markets in this app, so legs are priced with Black-Scholes using the
    underlying's own realized volatility as an IV proxy — clearly labeled as
    "Simulated" wherever it's used.
  - VIX entry gate: real India VIX (^INDIAVIX) / US VIX (^VIX) via yfinance.
    Crypto/Commodities have no listed vol index, so the entry gate instead uses
    a realized-volatility percentile rank of the ticker's own history.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
import requests

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.momentum_engine import MomentumConfig, analyze_timeframe
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.news_scanner import _parse_option_chain_payload, _warm_nse_session
from app.market_pulse.option_chain_engine import INDEX_CHOICES

logger = logging.getLogger(__name__)

TIMEFRAME_OPTIONS = ["15m", "1h", "4h", "1d", "1w"]
_MIN_BARS = 60


@dataclass
class DoubleCalendarConfig:
    short_dte: int = 14
    long_dte: int = 21
    otm_offset_pct: float = 1.5
    diagonal_widen_pct: float = 0.0  # 0 = pure Double Calendar; >0 = Double Diagonal
    take_profit_start: float = 0.20
    take_profit_max: float = 0.40
    stop_loss: float = -0.30
    vix_max_threshold: float = 20.0
    vix_low_threshold: float = 15.0
    vol_percentile_max: float = 40.0
    risk_free_rate: float = 0.065
    realized_vol_window: int = 20


# ---------------------------------------------------------------------------
# Data fetch helpers
# ---------------------------------------------------------------------------

def _fetch_daily_ohlcv(ticker: str, market: str, *, groww_token: str = "", exchange: str = "NSE") -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    df = fetch_data_for_gap_scan(ticker, "1d", market, groww_token, exchange, limit=300)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < _MIN_BARS:
        df = normalize_ohlcv(fetch_ohlcv_yfinance(ticker, "1d", is_crypto=is_crypto, limit=300, market=market))
    return df


def _fetch_tf_ohlcv(ticker: str, market: str, timeframe: str, *, groww_token: str = "", exchange: str = "NSE") -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    df = fetch_data_for_gap_scan(ticker, timeframe, market, groww_token, exchange, limit=300)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < _MIN_BARS:
        df = normalize_ohlcv(fetch_ohlcv_yfinance(ticker, timeframe, is_crypto=is_crypto, limit=300, market=market))
    return df


def _fetch_yf_series(symbol: str, period: str = "5d") -> pd.Series | None:
    try:
        import yfinance as yf
        hist = yf.Ticker(symbol).history(period=period)
        if hist is None or hist.empty:
            return None
        return hist["Close"]
    except Exception as exc:
        logger.debug("yfinance fetch failed for %s: %s", symbol, exc)
        return None


# ---------------------------------------------------------------------------
# Math: Black-Scholes pricer + realized volatility
# ---------------------------------------------------------------------------

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _bs_price(spot: float, strike: float, t_years: float, vol: float, r: float, option_type: str) -> float:
    """Black-Scholes European option price. Falls back to intrinsic value when
    inputs degenerate (expired/zero vol) rather than raising."""
    intrinsic = max(0.0, (spot - strike) if option_type == "call" else (strike - spot))
    if t_years <= 0 or vol <= 0 or spot <= 0 or strike <= 0:
        return intrinsic
    d1 = (math.log(spot / strike) + (r + 0.5 * vol ** 2) * t_years) / (vol * math.sqrt(t_years))
    d2 = d1 - vol * math.sqrt(t_years)
    if option_type == "call":
        price = spot * _norm_cdf(d1) - strike * math.exp(-r * t_years) * _norm_cdf(d2)
    else:
        price = strike * math.exp(-r * t_years) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)
    return max(price, intrinsic, 0.01)


def _realized_vol(df: pd.DataFrame, window: int) -> float | None:
    closes = df["close"].dropna()
    if len(closes) < window + 1:
        return None
    log_ret = np.log(closes / closes.shift(1)).dropna().tail(window)
    std = log_ret.std()
    if std is None or pd.isna(std):
        return None
    return float(std * math.sqrt(252))


def _vol_percentile(df: pd.DataFrame, window: int, lookback: int = 250) -> tuple[float, float] | None:
    closes = df["close"].dropna()
    if len(closes) < window + 20:
        return None
    log_ret = np.log(closes / closes.shift(1))
    roll_vol = (log_ret.rolling(window).std() * math.sqrt(252)).dropna().tail(lookback)
    if len(roll_vol) < 20:
        return None
    current = float(roll_vol.iloc[-1])
    pct = float((roll_vol <= current).mean() * 100)
    return current, pct


def _round_strike(spot: float) -> float:
    if spot <= 0:
        return spot
    if spot < 50:
        step = 0.5
    elif spot < 200:
        step = 1
    elif spot < 1000:
        step = 5
    elif spot < 5000:
        step = 10
    elif spot < 20000:
        step = 50
    else:
        step = 100
    return round(spot / step) * step


# ---------------------------------------------------------------------------
# Volatility / IV-environment gate
# ---------------------------------------------------------------------------

def check_volatility_environment(asset_class: str, daily_df: pd.DataFrame, cfg: DoubleCalendarConfig) -> dict[str, Any]:
    """Real VIX/India VIX gate for india/us; realized-vol percentile proxy otherwise."""
    if asset_class == "india":
        series, source = _fetch_yf_series("^INDIAVIX"), "India VIX (^INDIAVIX)"
    elif asset_class == "us":
        series, source = _fetch_yf_series("^VIX"), "CBOE VIX (^VIX)"
    else:
        series, source = None, None

    if series is not None and len(series) >= 2:
        current = float(series.iloc[-1])
        spiking = current > float(series.iloc[0]) * 1.10
        favorable = current <= cfg.vix_max_threshold and not spiking
        if spiking:
            reason = (
                f"{source} at {current:.2f} is spiking (>10% above its level {len(series) - 1} session(s) ago) — "
                "avoid entering into a vol spike; IV-crush risk cuts both ways here."
            )
        elif favorable:
            reason = (
                f"{source} at {current:.2f} — at/below the {cfg.vix_max_threshold:.0f} favorable ceiling and not "
                "spiking, a reasonable low-IV environment for a net-debit calendar."
            )
        else:
            reason = (
                f"{source} at {current:.2f} is above the {cfg.vix_max_threshold:.0f} ceiling — IV is elevated. "
                "Rich premium looks attractive, but this is a positive-Vega trade: a falling-VIX regime after "
                "entry will bleed the position even if price stays range-bound."
            )
        return {
            "favorable": favorable, "level": round(current, 2), "spiking": spiking,
            "source": source, "label": f"{current:.2f}", "reason": reason,
        }

    vol_result = _vol_percentile(daily_df, cfg.realized_vol_window)
    if vol_result is None:
        return {
            "favorable": True, "level": None, "spiking": False, "source": "Unavailable",
            "label": "—",
            "reason": (
                "No listed volatility index for this asset and insufficient price history for a "
                "realized-volatility percentile read — entry gate skipped; verify IV manually before entering."
            ),
        }
    current_vol, pct = vol_result
    favorable = pct <= cfg.vol_percentile_max
    reason = (
        f"No listed volatility index for this asset — using {cfg.realized_vol_window}-day realized volatility "
        f"({current_vol * 100:.1f}% annualized) ranked against its own trailing ~1yr history: currently at the "
        f"{pct:.0f}th percentile. "
        + (
            "That's in the calmer, lower range — a reasonable proxy for a favorable IV environment."
            if favorable else
            "That's an elevated reading for this ticker — treat as a proxy for a rich-IV environment; "
            "be cautious entering a long-Vega spread here."
        )
    )
    return {
        "favorable": favorable, "level": round(current_vol * 100, 2), "percentile": round(pct, 1), "spiking": False,
        "source": f"Realized-volatility percentile ({cfg.realized_vol_window}d, no listed vol index available)",
        "label": f"{current_vol * 100:.1f}% ({pct:.0f}th pct)", "reason": reason,
    }


# ---------------------------------------------------------------------------
# India: real NSE option-chain leg pricing
# ---------------------------------------------------------------------------

def _parse_nse_date(s: str) -> date | None:
    for fmt in ("%d-%b-%Y", "%d-%b-%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _fetch_nse_expiries(symbol: str, is_index: bool) -> list[str]:
    try:
        session = requests.Session()
        _warm_nse_session(session, "/option-chain")
        instrument = "Indices" if is_index else "Stocks"
        url = f"https://www.nseindia.com/api/option-chain-contract-info?symbol={symbol}&instrument={instrument}"
        resp = session.get(url, timeout=15)
        if resp.status_code != 200:
            return []
        return resp.json().get("expiryDates") or []
    except Exception as exc:
        logger.debug("NSE expiries fetch failed for %s: %s", symbol, exc)
        return []


def _fetch_nse_chain_for_expiry(symbol: str, expiry: str, is_index: bool) -> dict | None:
    try:
        session = requests.Session()
        _warm_nse_session(session, "/option-chain")
        type_param = "Indices" if is_index else "Equity"
        time.sleep(0.2)
        url = f"https://www.nseindia.com/api/option-chain-v3?type={type_param}&symbol={symbol}&expiry={expiry}"
        resp = session.get(url, timeout=20)
        if resp.status_code != 200 or len(resp.text) < 50:
            return None
        return _parse_option_chain_payload(resp.json(), source="NSE")
    except Exception as exc:
        logger.debug("NSE chain fetch failed for %s @ %s: %s", symbol, expiry, exc)
        return None


def _nearest_expiry(expiries: list[str], target: date, *, after: date | None = None) -> str | None:
    parsed = []
    for e in expiries:
        d = _parse_nse_date(e)
        if d is None:
            continue
        if after is not None and d <= after:
            continue
        parsed.append((d, e))
    if not parsed:
        return None
    parsed.sort(key=lambda x: abs((x[0] - target).days))
    return parsed[0][1]


def _find_nearest_strike(chain: dict, target_strike: float) -> dict | None:
    strikes = chain.get("strikes") or []
    if not strikes:
        return None
    return min(strikes, key=lambda s: abs(s["strike"] - target_strike))


def _price_legs_india(
    ticker: str, *, call_strike_short: float, put_strike_short: float,
    call_strike_long: float, put_strike_long: float, short_target: date, long_target: date,
) -> dict[str, dict]:
    symbol = ticker.upper()
    is_index = symbol in INDEX_CHOICES
    expiries = _fetch_nse_expiries(symbol, is_index)
    if not expiries:
        return {}
    short_expiry = _nearest_expiry(expiries, short_target)
    if short_expiry is None:
        return {}
    short_expiry_date = _parse_nse_date(short_expiry)
    long_expiry = _nearest_expiry(expiries, long_target, after=short_expiry_date)
    if long_expiry is None:
        return {}

    short_chain = _fetch_nse_chain_for_expiry(symbol, short_expiry, is_index)
    long_chain = _fetch_nse_chain_for_expiry(symbol, long_expiry, is_index)
    if not short_chain or not long_chain:
        return {}

    sc = _find_nearest_strike(short_chain, call_strike_short)
    sp = _find_nearest_strike(short_chain, put_strike_short)
    lc = _find_nearest_strike(long_chain, call_strike_long)
    lp = _find_nearest_strike(long_chain, put_strike_long)
    if not all([sc, sp, lc, lp]):
        return {}

    return {
        "short_call": {"strike": sc["strike"], "premium": sc.get("ce_ltp") or 0, "iv": sc.get("ce_iv"), "expiry": short_expiry, "source": "NSE live chain"},
        "short_put": {"strike": sp["strike"], "premium": sp.get("pe_ltp") or 0, "iv": sp.get("pe_iv"), "expiry": short_expiry, "source": "NSE live chain"},
        "long_call": {"strike": lc["strike"], "premium": lc.get("ce_ltp") or 0, "iv": lc.get("ce_iv"), "expiry": long_expiry, "source": "NSE live chain"},
        "long_put": {"strike": lp["strike"], "premium": lp.get("pe_ltp") or 0, "iv": lp.get("pe_iv"), "expiry": long_expiry, "source": "NSE live chain"},
    }


# ---------------------------------------------------------------------------
# US: real Yahoo Finance option-chain leg pricing
# ---------------------------------------------------------------------------

def _price_legs_us(
    ticker: str, *, call_strike_short: float, put_strike_short: float,
    call_strike_long: float, put_strike_long: float, short_target: date, long_target: date,
) -> dict[str, dict]:
    try:
        import yfinance as yf
        tk = yf.Ticker(ticker)
        options = tk.options
        if not options:
            return {}
        parsed = sorted((datetime.strptime(o, "%Y-%m-%d").date(), o) for o in options)
        short_match = min(parsed, key=lambda x: abs((x[0] - short_target).days))
        later = [p for p in parsed if p[0] > short_match[0]]
        pool = later or parsed
        long_match = min(pool, key=lambda x: abs((x[0] - long_target).days))

        short_chain = tk.option_chain(short_match[1])
        long_chain = tk.option_chain(long_match[1])

        def _mid(row) -> float:
            bid = float(row.get("bid", 0) or 0)
            ask = float(row.get("ask", 0) or 0)
            if bid > 0 and ask > 0:
                return (bid + ask) / 2
            return float(row.get("lastPrice", 0) or 0)

        def _find(df: pd.DataFrame, target_strike: float):
            if df is None or df.empty:
                return None
            idx = (df["strike"] - target_strike).abs().idxmin()
            return df.loc[idx]

        sc = _find(short_chain.calls, call_strike_short)
        sp = _find(short_chain.puts, put_strike_short)
        lc = _find(long_chain.calls, call_strike_long)
        lp = _find(long_chain.puts, put_strike_long)
        if sc is None or sp is None or lc is None or lp is None:
            return {}

        return {
            "short_call": {"strike": float(sc["strike"]), "premium": _mid(sc), "iv": float(sc.get("impliedVolatility") or 0) * 100, "expiry": short_match[1], "source": "Yahoo live chain"},
            "short_put": {"strike": float(sp["strike"]), "premium": _mid(sp), "iv": float(sp.get("impliedVolatility") or 0) * 100, "expiry": short_match[1], "source": "Yahoo live chain"},
            "long_call": {"strike": float(lc["strike"]), "premium": _mid(lc), "iv": float(lc.get("impliedVolatility") or 0) * 100, "expiry": long_match[1], "source": "Yahoo live chain"},
            "long_put": {"strike": float(lp["strike"]), "premium": _mid(lp), "iv": float(lp.get("impliedVolatility") or 0) * 100, "expiry": long_match[1], "source": "Yahoo live chain"},
        }
    except Exception as exc:
        logger.debug("US option chain fetch failed for %s: %s", ticker, exc)
        return {}


def _fill_missing_legs(
    legs: dict[str, dict], *, spot: float,
    call_strike_short: float, put_strike_short: float, call_strike_long: float, put_strike_long: float,
    short_expiry_target: date, long_expiry_target: date, vol: float, r: float,
) -> dict[str, dict]:
    today = date.today()
    targets = {
        "short_call": (call_strike_short, short_expiry_target, "call"),
        "short_put": (put_strike_short, short_expiry_target, "put"),
        "long_call": (call_strike_long, long_expiry_target, "call"),
        "long_put": (put_strike_long, long_expiry_target, "put"),
    }
    for key, (strike, expiry_default, opt_type) in targets.items():
        leg = legs.get(key)
        if leg and (leg.get("premium") or 0) > 0:
            continue
        expiry_date = expiry_default
        if leg and leg.get("expiry"):
            parsed = _parse_nse_date(leg["expiry"])
            if parsed is None:
                try:
                    parsed = datetime.strptime(leg["expiry"], "%Y-%m-%d").date()
                except ValueError:
                    parsed = None
            if parsed:
                expiry_date = parsed
        t_years = max((expiry_date - today).days, 1) / 365.0
        price = _bs_price(spot, strike, t_years, vol, r, opt_type)
        legs[key] = {
            "strike": strike, "premium": round(price, 4), "iv": round(vol * 100, 2),
            "expiry": str(expiry_date), "source": "Simulated (Black-Scholes, realized-vol proxy)",
        }
    return legs


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def build_double_calendar(
    ticker: str, asset_class: str, market: str, timeframes: list[str], *,
    cfg: DoubleCalendarConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or DoubleCalendarConfig()

    daily_df = _fetch_daily_ohlcv(ticker, market, groww_token=groww_token, exchange=exchange)
    if daily_df is None or daily_df.empty or len(daily_df) < _MIN_BARS:
        return {"ticker": ticker, "asset_class": asset_class, "error": f"Insufficient daily data ({0 if daily_df is None else len(daily_df)} bars, need {_MIN_BARS}+)."}

    spot = float(daily_df["close"].iloc[-1])
    realized_vol = _realized_vol(daily_df, cfg.realized_vol_window) or 0.25
    vol_env = check_volatility_environment(asset_class, daily_df, cfg)

    per_tf_trend: list[dict] = []
    for tf in timeframes:
        try:
            tf_df = _fetch_tf_ohlcv(ticker, market, tf, groww_token=groww_token, exchange=exchange)
            res = analyze_timeframe(tf_df, tf, MomentumConfig())
            if res:
                per_tf_trend.append(res)
        except Exception as exc:
            logger.debug("Double Calendar trend context failed for %s %s: %s", ticker, tf, exc)

    strong_trend_count = sum(1 for t in per_tf_trend if t.get("strength") == "STRONG")

    today = date.today()
    short_expiry_target = today + timedelta(days=cfg.short_dte)
    long_expiry_target = today + timedelta(days=cfg.long_dte)

    call_strike_short = _round_strike(spot * (1 + cfg.otm_offset_pct / 100))
    put_strike_short = _round_strike(spot * (1 - cfg.otm_offset_pct / 100))
    long_offset = cfg.otm_offset_pct + cfg.diagonal_widen_pct
    call_strike_long = _round_strike(spot * (1 + long_offset / 100))
    put_strike_long = _round_strike(spot * (1 - long_offset / 100))

    legs: dict[str, dict] = {}
    if asset_class == "india":
        try:
            legs = _price_legs_india(
                ticker, call_strike_short=call_strike_short, put_strike_short=put_strike_short,
                call_strike_long=call_strike_long, put_strike_long=put_strike_long,
                short_target=short_expiry_target, long_target=long_expiry_target,
            )
        except Exception as exc:
            logger.debug("India leg pricing failed for %s: %s", ticker, exc)
    elif asset_class == "us":
        try:
            legs = _price_legs_us(
                ticker, call_strike_short=call_strike_short, put_strike_short=put_strike_short,
                call_strike_long=call_strike_long, put_strike_long=put_strike_long,
                short_target=short_expiry_target, long_target=long_expiry_target,
            )
        except Exception as exc:
            logger.debug("US leg pricing failed for %s: %s", ticker, exc)

    legs = _fill_missing_legs(
        legs, spot=spot,
        call_strike_short=call_strike_short, put_strike_short=put_strike_short,
        call_strike_long=call_strike_long, put_strike_long=put_strike_long,
        short_expiry_target=short_expiry_target, long_expiry_target=long_expiry_target,
        vol=realized_vol, r=cfg.risk_free_rate,
    )

    net_debit = (legs["long_call"]["premium"] + legs["long_put"]["premium"]) - (legs["short_call"]["premium"] + legs["short_put"]["premium"])
    net_debit = round(max(net_debit, 0.01), 4)

    reasons: list[str] = []
    is_diagonal = cfg.diagonal_widen_pct > 0
    reasons.append(
        f"{'Double Diagonal' if is_diagonal else 'Double Calendar'} on {ticker}: sell {short_expiry_target.strftime('%d-%b')} "
        f"({cfg.short_dte}d) call/put, buy {long_expiry_target.strftime('%d-%b')} ({cfg.long_dte}d) call/put "
        f"{cfg.otm_offset_pct:.1f}% OTM" + (f" (long legs widened {cfg.diagonal_widen_pct:.1f}% further OTM)" if is_diagonal else " at the same strikes") + "."
    )
    reasons.append(vol_env["reason"])
    if per_tf_trend:
        if strong_trend_count > len(per_tf_trend) / 2:
            reasons.append(
                f"⚠️ {strong_trend_count}/{len(per_tf_trend)} selected timeframe(s) show a STRONG trend — this is a "
                "range-bound, theta-positive strategy that performs best when price is NOT trending strongly. "
                "Consider skipping or waiting for consolidation."
            )
        else:
            reasons.append(
                f"Trend context: {sum(1 for t in per_tf_trend if t.get('trend_direction') == 'CONSOLIDATING')}/"
                f"{len(per_tf_trend)} selected timeframe(s) reading consolidating/non-trending — supportive of a "
                "range-bound spread."
            )
    any_simulated = any(leg.get("source", "").startswith("Simulated") for leg in legs.values())
    if any_simulated:
        reasons.append(
            "One or more legs used simulated (Black-Scholes) pricing — no live/liquid option quote was available "
            "at that strike/expiry. Treat premiums as an estimate, not a fillable quote."
        )

    entry_ok = bool(vol_env["favorable"])
    majority_strong = bool(per_tf_trend) and strong_trend_count > len(per_tf_trend) / 2
    tp_pct = round(cfg.take_profit_start * 100, 2)
    sl_pct = round(abs(cfg.stop_loss) * 100, 2)
    rr = round(tp_pct / sl_pct, 2) if sl_pct > 0 else None

    conf_bits: list[str] = []
    confidence = 40.0
    if entry_ok and not majority_strong:
        action, action_label = "BUY", "BUY SPREAD"
        confidence = 68.0
        conf_bits.append("IV/vol environment favorable for calendar")
        if per_tf_trend and not majority_strong:
            conf_bits.append("Trend context not majority-strong (range-friendly)")
            confidence += 6.0
        plain = (
            f"BUY the {'Double Diagonal' if is_diagonal else 'Double Calendar'} — "
            f"debit environment looks workable. Scale out from +{tp_pct:g}% of debit; "
            f"mental stop around −{sl_pct:g}% of debit."
        )
    elif majority_strong:
        action, action_label = "WAIT", "WAIT"
        confidence = 52.0
        conf_bits.append("Majority of timeframes show a strong trend — poor for theta calendars")
        if not entry_ok:
            confidence -= 8.0
            conf_bits.append("IV/vol also unfavorable")
        plain = (
            "WAIT — strong trend across timeframes fights a range-bound calendar. "
            "Prefer consolidation before buying the debit spread."
        )
    else:
        action, action_label = "WAIT", "WAIT"
        confidence = 45.0
        conf_bits.append("IV/vol environment unfavorable")
        plain = (
            "WAIT — IV/vol filter does not favor buying this calendar right now. "
            f"Keep mental SL −{sl_pct:g}% / TP +{tp_pct:g}% ready for when conditions improve."
        )
    confidence = round(max(15.0, min(92.0, confidence)), 1)

    trade = {
        "action": action,
        "action_label": action_label,
        "confidence_pct": confidence,
        "confidence_reasons": conf_bits,
        "sl_pct": sl_pct,
        "tp_pct": tp_pct,
        "rr": rr,
        "entry_price": net_debit,
        "entry_basis": "net_debit",
        "stop_price": round(net_debit * (1 + cfg.stop_loss), 4),
        "target_price": round(net_debit * (1 + cfg.take_profit_start), 4),
        "target_max_price": round(net_debit * (1 + cfg.take_profit_max), 4),
        "plain_english": plain,
    }

    return {
        "ticker": ticker, "asset_class": asset_class, "market": market,
        "spot": round(spot, 4), "realized_vol_pct": round(realized_vol * 100, 2),
        "vol_environment": vol_env,
        "trend_context": per_tf_trend,
        "strong_trend_count": strong_trend_count,
        "short_expiry_target": str(short_expiry_target), "long_expiry_target": str(long_expiry_target),
        "is_diagonal": is_diagonal,
        "otm_offset_pct": cfg.otm_offset_pct,
        "legs": legs,
        "net_debit": net_debit,
        "take_profit_start_price": round(net_debit * (1 + cfg.take_profit_start), 4),
        "take_profit_max_price": round(net_debit * (1 + cfg.take_profit_max), 4),
        "stop_loss_price": round(net_debit * (1 + cfg.stop_loss), 4),
        "entry_ok": entry_ok,
        "trade_suggestion": trade,
        "action": trade["action"],
        "confidence_pct": trade["confidence_pct"],
        "sl_pct": trade["sl_pct"],
        "tp_pct": trade["tp_pct"],
        "reasons": reasons,
    }


def build_double_calendar_many(
    tickers: list[str], asset_class: str, market: str, timeframes: list[str], *,
    cfg: DoubleCalendarConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> list[dict[str, Any]]:
    results = []
    for ticker in tickers:
        try:
            results.append(build_double_calendar(
                ticker, asset_class, market, timeframes,
                cfg=cfg, groww_token=groww_token, exchange=exchange,
            ))
        except Exception as exc:
            logger.debug("Double Calendar failed for %s: %s", ticker, exc)
            results.append({"ticker": ticker, "asset_class": asset_class, "error": str(exc)[:200]})
    return results


def evaluate_double_calendar_pnl(net_debit: float, current_mark: float, cfg: DoubleCalendarConfig | None = None) -> dict[str, Any]:
    """30% mental stop, 20-40% scale-out/close management lifecycle."""
    cfg = cfg or DoubleCalendarConfig()
    if net_debit is None or net_debit <= 0:
        return {"error": "Invalid entry debit."}
    pnl_pct = (current_mark - net_debit) / net_debit

    if pnl_pct <= cfg.stop_loss:
        action = "STOP_LOSS"
        message = (
            f"🔴 Stop-loss zone — down {abs(pnl_pct) * 100:.1f}% (mental {abs(cfg.stop_loss) * 100:.0f}% stop). "
            "Close the full position; don't set a hard broker stop on this — wide bid/ask spreads can trigger it prematurely."
        )
    elif pnl_pct >= cfg.take_profit_max:
        action = "CLOSE_MAX_PROFIT"
        message = f"🔵 Max take-profit hit — up {pnl_pct * 100:.1f}%. Close the full remaining position; don't hold into expiration."
    elif pnl_pct >= cfg.take_profit_start:
        action = "SCALE_OUT"
        message = (
            f"🟡 Scale-out zone — up {pnl_pct * 100:.1f}%. Start closing partial contracts here, let the rest ride "
            f"toward the {cfg.take_profit_max * 100:.0f}% target."
        )
    else:
        action = "HOLD"
        message = (
            f"⚪ Hold — {pnl_pct * 100:+.1f}% P&L, inside the {cfg.stop_loss * 100:.0f}%/+{cfg.take_profit_start * 100:.0f}% "
            "management band."
        )
    return {"pnl_pct": round(pnl_pct * 100, 2), "action": action, "message": message}
