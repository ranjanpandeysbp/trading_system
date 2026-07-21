"""
delta_neutral_engine.py
--------------------------
Delta-Neutral Iron Condor / Iron Fly — a defined-risk premium-selling strategy
that profits if the underlying simply stays inside a range, regardless of
direction. You act as "the casino": collect Theta (time decay) from OTM option
buyers, with your probability of winning approximated by Delta.

Rules:
  - Sell an OTM Put and an OTM Call at the same expiry ("sell the inner range")
    — both expire worthless, you keep the premium, as long as price stays
    between the two short strikes.
  - Target short-strike Delta ~0.15-0.25 (~70-80% mathematical probability of
    profit), not a chart read — the whole edge is the risk premium baked into
    option pricing, not direction prediction.
  - Buy further OTM "wings" (long call above the short call, long put below
    the short put) immediately after — this caps max loss at (wing width -
    net credit), turning the naked strangle into a defined-risk Iron Condor
    (or Iron Fly, if the short strikes are placed at-the-money instead of OTM).
  - Best in a choppy/range-bound market — avoid holding through major
    macro events (FOMC, earnings, geopolitical shocks).
  - Take profit early: close at 30-50% of max credit captured. Don't hold to
    expiry, and don't chase the last few % of premium.

Data sources (real where available, otherwise a disclosed simulation) —
identical convention to double_calendar_engine.py:
  - India (NSE indices/stocks): live NSE option-chain-v3 strikes/premiums/IV
    for the nearest listed expiry to the target DTE; short strikes chosen by
    matching each strike's own listed IV -> Black-Scholes delta to the target.
  - US: live Yahoo Finance option chain (yfinance), same delta-matching.
  - Crypto / Commodities: no listed options-chain feed is integrated for these
    markets here, so strikes are placed by *inverting* Black-Scholes delta
    (solving directly for the strike at the target delta) and priced with
    Black-Scholes using the underlying's own realized volatility as an IV
    proxy — labeled "Simulated" wherever used.
  - VIX / choppy-market gate: reuses double_calendar_engine's real India VIX
    (^INDIAVIX) / US VIX (^VIX) check, with a realized-volatility percentile
    proxy for Crypto/Commodities, plus a trend-strength (ADX) read so a
    strongly-trending market is flagged as a poor fit for a range-bound trade.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import NormalDist
from typing import Any

from app.market_pulse.double_calendar_engine import (
    _bs_price,
    _fetch_daily_ohlcv,
    _fetch_nse_chain_for_expiry,
    _fetch_nse_expiries,
    _fetch_tf_ohlcv,
    _nearest_expiry,
    _norm_cdf,
    _parse_nse_date,
    _realized_vol,
    _round_strike,
    check_volatility_environment,
)
from app.market_pulse.momentum_engine import MomentumConfig, analyze_timeframe
from app.market_pulse.option_chain_engine import INDEX_CHOICES

logger = logging.getLogger(__name__)

TIMEFRAME_OPTIONS = ["15m", "1h", "4h", "1d", "1w"]
_MIN_BARS = 60
_LEG_KEYS = ("short_call", "short_put", "long_call", "long_put")


@dataclass
class DeltaNeutralConfig:
    dte: int = 30
    short_delta_target: float = 0.20  # ~0.15-0.25 => ~70-80% mathematical probability of profit
    wing_width_pct: float = 5.0  # long-wing strikes this % further OTM than the short strikes
    iron_fly: bool = False  # True = short strikes at-the-money (Iron Fly) instead of OTM (Iron Condor)
    profit_target_pct: float = 0.50  # close at this fraction of max credit captured
    stop_loss_multiple: float = 1.0  # optional: flag a defensive close if loss reaches this multiple of credit received (0 = off)
    vix_max_threshold: float = 20.0
    vol_percentile_max: float = 40.0
    adx_trend_max: float = 25.0  # daily ADX above this = not a "choppy" market
    risk_free_rate: float = 0.065
    realized_vol_window: int = 20


# ---------------------------------------------------------------------------
# Delta helpers
# ---------------------------------------------------------------------------

def _bs_delta_from_iv(spot: float, strike: float, t_years: float, iv_pct: float, r: float, option_type: str) -> float:
    vol = max(iv_pct or 0, 1.0) / 100.0
    if vol <= 0 or t_years <= 0 or spot <= 0 or strike <= 0:
        return 0.0
    d1 = (math.log(spot / strike) + (r + 0.5 * vol ** 2) * t_years) / (vol * math.sqrt(t_years))
    delta = _norm_cdf(d1)
    return delta if option_type == "call" else delta - 1.0


def _strike_at_delta(spot: float, vol: float, t_years: float, target_delta: float, r: float, side: str) -> float:
    """Invert Black-Scholes delta to solve for the strike at a target |delta|,
    used when no real option chain is available (Crypto/Commodities).

    Call delta = N(d1) = target  => d1 = Phi^-1(target)      (target < 0.5 => d1 < 0 => strike > spot)
    Put delta  = N(d1)-1 = -target => N(d1) = 1-target => d1 = Phi^-1(1-target) (=> d1 > 0 => strike < spot)
    """
    target_delta = min(max(target_delta, 0.01), 0.99)
    p = target_delta if side == "call" else (1 - target_delta)
    d1 = NormalDist().inv_cdf(p)
    return spot / math.exp(d1 * vol * math.sqrt(max(t_years, 1 / 365.0)) - (r + 0.5 * vol ** 2) * t_years)


# ---------------------------------------------------------------------------
# India: real NSE option-chain leg selection
# ---------------------------------------------------------------------------

def _select_strike_by_delta_india(chain: dict, spot: float, t_years: float, target_delta: float, r: float, side: str) -> dict | None:
    price_key = "ce_ltp" if side == "call" else "pe_ltp"
    iv_key = "ce_iv" if side == "call" else "pe_iv"
    candidates = []
    for s in chain.get("strikes") or []:
        strike = s.get("strike")
        if strike is None:
            continue
        if side == "call" and strike <= spot:
            continue
        if side == "put" and strike >= spot:
            continue
        ltp = s.get(price_key) or 0
        if ltp <= 0:
            continue
        iv = s.get(iv_key) or 0
        delta = abs(_bs_delta_from_iv(spot, strike, t_years, iv, r, side))
        candidates.append({"strike": strike, "premium": ltp, "iv": iv, "delta": delta})
    if not candidates:
        return None
    return min(candidates, key=lambda c: abs(c["delta"] - target_delta))


def _select_atm_strike_india(chain: dict, spot: float, side: str) -> dict | None:
    price_key = "ce_ltp" if side == "call" else "pe_ltp"
    iv_key = "ce_iv" if side == "call" else "pe_iv"
    valid = [s for s in (chain.get("strikes") or []) if (s.get(price_key) or 0) > 0]
    if not valid:
        return None
    nearest = min(valid, key=lambda s: abs(s["strike"] - spot))
    return {"strike": nearest["strike"], "premium": nearest.get(price_key) or 0, "iv": nearest.get(iv_key) or 0}


def _select_wing_strike_india(chain: dict, target_strike: float, side: str) -> dict | None:
    price_key = "ce_ltp" if side == "call" else "pe_ltp"
    iv_key = "ce_iv" if side == "call" else "pe_iv"
    strikes = chain.get("strikes") or []
    if not strikes:
        return None
    nearest = min(strikes, key=lambda s: abs(s["strike"] - target_strike))
    return {"strike": nearest["strike"], "premium": nearest.get(price_key) or 0, "iv": nearest.get(iv_key) or 0}


def _price_legs_india(ticker: str, spot: float, cfg: DeltaNeutralConfig, target_expiry: date) -> dict[str, dict]:
    symbol = ticker.upper()
    is_index = symbol in INDEX_CHOICES
    expiries = _fetch_nse_expiries(symbol, is_index)
    if not expiries:
        return {}
    expiry = _nearest_expiry(expiries, target_expiry)
    if expiry is None:
        return {}
    expiry_date = _parse_nse_date(expiry)
    chain = _fetch_nse_chain_for_expiry(symbol, expiry, is_index)
    if not chain:
        return {}
    t_years = max(((expiry_date - date.today()).days if expiry_date else cfg.dte), 1) / 365.0

    if cfg.iron_fly:
        short_call = _select_atm_strike_india(chain, spot, "call")
        short_put = _select_atm_strike_india(chain, spot, "put")
    else:
        short_call = _select_strike_by_delta_india(chain, spot, t_years, cfg.short_delta_target, cfg.risk_free_rate, "call")
        short_put = _select_strike_by_delta_india(chain, spot, t_years, cfg.short_delta_target, cfg.risk_free_rate, "put")
    if not short_call or not short_put:
        return {}

    long_call = _select_wing_strike_india(chain, short_call["strike"] * (1 + cfg.wing_width_pct / 100), "call")
    long_put = _select_wing_strike_india(chain, short_put["strike"] * (1 - cfg.wing_width_pct / 100), "put")
    if not long_call or not long_put:
        return {}

    for leg in (short_call, short_put, long_call, long_put):
        leg["expiry"] = expiry
        leg["source"] = "NSE live chain"
    return {"short_call": short_call, "short_put": short_put, "long_call": long_call, "long_put": long_put}


# ---------------------------------------------------------------------------
# US: real Yahoo Finance option-chain leg selection
# ---------------------------------------------------------------------------

def _price_legs_us(ticker: str, spot: float, cfg: DeltaNeutralConfig, target_expiry: date) -> dict[str, dict]:
    try:
        import yfinance as yf
        tk = yf.Ticker(ticker)
        options = tk.options
        if not options:
            return {}
        parsed = sorted((datetime.strptime(o, "%Y-%m-%d").date(), o) for o in options)
        match = min(parsed, key=lambda x: abs((x[0] - target_expiry).days))
        chain = tk.option_chain(match[1])
        calls, puts = chain.calls, chain.puts
        t_years = max((match[0] - date.today()).days, 1) / 365.0

        def _mid(row) -> float:
            bid, ask = float(row.get("bid", 0) or 0), float(row.get("ask", 0) or 0)
            if bid > 0 and ask > 0:
                return (bid + ask) / 2
            return float(row.get("lastPrice", 0) or 0)

        def _row_dict(row) -> dict:
            return {"strike": float(row["strike"]), "premium": _mid(row), "iv": float(row.get("impliedVolatility") or 0) * 100}

        def _select_by_delta(df, side: str, target: float) -> dict | None:
            if df is None or df.empty:
                return None
            sub = df[df["strike"] > spot] if side == "call" else df[df["strike"] < spot]
            if sub.empty:
                sub = df
            best_row, best_diff = None, None
            for _, row in sub.iterrows():
                iv = float(row.get("impliedVolatility") or 0) * 100
                d = abs(_bs_delta_from_iv(spot, float(row["strike"]), t_years, iv, cfg.risk_free_rate, side))
                diff = abs(d - target)
                if best_diff is None or diff < best_diff:
                    best_diff, best_row = diff, row
            return _row_dict(best_row) if best_row is not None else None

        def _select_atm(df, side: str) -> dict | None:
            if df is None or df.empty:
                return None
            idx = (df["strike"] - spot).abs().idxmin()
            return _row_dict(df.loc[idx])

        def _select_wing(df, target_strike: float) -> dict | None:
            if df is None or df.empty:
                return None
            idx = (df["strike"] - target_strike).abs().idxmin()
            return _row_dict(df.loc[idx])

        if cfg.iron_fly:
            short_call, short_put = _select_atm(calls, "call"), _select_atm(puts, "put")
        else:
            short_call = _select_by_delta(calls, "call", cfg.short_delta_target)
            short_put = _select_by_delta(puts, "put", cfg.short_delta_target)
        if not short_call or not short_put:
            return {}

        long_call = _select_wing(calls, short_call["strike"] * (1 + cfg.wing_width_pct / 100))
        long_put = _select_wing(puts, short_put["strike"] * (1 - cfg.wing_width_pct / 100))
        if not long_call or not long_put:
            return {}

        for leg in (short_call, short_put, long_call, long_put):
            leg["expiry"] = match[1]
            leg["source"] = "Yahoo live chain"
        return {"short_call": short_call, "short_put": short_put, "long_call": long_call, "long_put": long_put}
    except Exception as exc:
        logger.debug("US delta-neutral leg pricing failed for %s: %s", ticker, exc)
        return {}


# ---------------------------------------------------------------------------
# Crypto / Commodity: fully simulated strikes (inverse-delta placement + BS pricing)
# ---------------------------------------------------------------------------

def _synthetic_strikes(spot: float, vol: float, t_years: float, cfg: DeltaNeutralConfig, r: float) -> dict[str, float]:
    if cfg.iron_fly:
        short_call_strike = short_put_strike = _round_strike(spot)
    else:
        short_call_strike = _round_strike(_strike_at_delta(spot, vol, t_years, cfg.short_delta_target, r, "call"))
        short_put_strike = _round_strike(_strike_at_delta(spot, vol, t_years, cfg.short_delta_target, r, "put"))
    return {
        "short_call": short_call_strike, "short_put": short_put_strike,
        "long_call": _round_strike(short_call_strike * (1 + cfg.wing_width_pct / 100)),
        "long_put": _round_strike(short_put_strike * (1 - cfg.wing_width_pct / 100)),
    }


def _fill_missing_legs(
    legs: dict[str, dict], *, spot: float, cfg: DeltaNeutralConfig, target_expiry: date, vol: float,
) -> dict[str, dict]:
    today = date.today()
    if not legs:
        t_years = max((target_expiry - today).days, 1) / 365.0
        strikes = _synthetic_strikes(spot, vol, t_years, cfg, cfg.risk_free_rate)
        legs = {key: {"strike": strikes[key], "premium": 0, "iv": None, "expiry": str(target_expiry)} for key in _LEG_KEYS}

    option_types = {"short_call": "call", "short_put": "put", "long_call": "call", "long_put": "put"}
    for key in _LEG_KEYS:
        leg = legs.get(key)
        if leg and (leg.get("premium") or 0) > 0:
            continue
        expiry_date = target_expiry
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
        strike = leg["strike"] if leg else _round_strike(spot)
        price = _bs_price(spot, strike, t_years, vol, cfg.risk_free_rate, option_types[key])
        legs[key] = {
            "strike": strike, "premium": round(price, 4), "iv": round(vol * 100, 2),
            "expiry": str(expiry_date), "source": "Simulated (Black-Scholes, realized-vol proxy)",
        }
    return legs


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def build_delta_neutral(
    ticker: str, asset_class: str, market: str, timeframes: list[str], *,
    cfg: DeltaNeutralConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or DeltaNeutralConfig()

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
            logger.debug("Delta-Neutral trend context failed for %s %s: %s", ticker, tf, exc)

    strong_trend_count = sum(1 for t in per_tf_trend if t.get("strength") == "STRONG")
    choppy = not per_tf_trend or strong_trend_count <= len(per_tf_trend) / 2

    today = date.today()
    target_expiry = today + timedelta(days=cfg.dte)
    t_years = max((target_expiry - today).days, 1) / 365.0

    legs: dict[str, dict] = {}
    if asset_class == "india":
        try:
            legs = _price_legs_india(ticker, spot, cfg, target_expiry)
        except Exception as exc:
            logger.debug("India delta-neutral leg pricing failed for %s: %s", ticker, exc)
    elif asset_class == "us":
        try:
            legs = _price_legs_us(ticker, spot, cfg, target_expiry)
        except Exception as exc:
            logger.debug("US delta-neutral leg pricing failed for %s: %s", ticker, exc)

    legs = _fill_missing_legs(legs, spot=spot, cfg=cfg, target_expiry=target_expiry, vol=realized_vol)

    short_call, short_put = legs["short_call"], legs["short_put"]
    long_call, long_put = legs["long_call"], legs["long_put"]

    net_credit = (short_call["premium"] + short_put["premium"]) - (long_call["premium"] + long_put["premium"])
    net_credit = round(max(net_credit, 0.01), 4)

    call_wing_width = abs(long_call["strike"] - short_call["strike"])
    put_wing_width = abs(short_put["strike"] - long_put["strike"])
    max_loss = round(max(max(call_wing_width, put_wing_width) - net_credit, 0.01), 4)
    max_profit = net_credit

    call_delta = abs(_bs_delta_from_iv(spot, short_call["strike"], t_years, short_call.get("iv") or realized_vol * 100, cfg.risk_free_rate, "call"))
    put_delta = abs(_bs_delta_from_iv(spot, short_put["strike"], t_years, short_put.get("iv") or realized_vol * 100, cfg.risk_free_rate, "put"))
    pop_pct = round(max(0.0, min(100.0, (1 - (call_delta + put_delta)) * 100)), 1)

    close_at_price = round(net_credit * (1 - cfg.profit_target_pct), 4)
    defensive_close_price = round(net_credit * (1 + cfg.stop_loss_multiple), 4) if cfg.stop_loss_multiple else None

    structure_label = "Iron Fly" if cfg.iron_fly else "Iron Condor"
    reasons: list[str] = [
        f"{structure_label} on {ticker}: sell {short_call['strike']} Call (Δ≈{call_delta:.2f}) + "
        f"{short_put['strike']} Put (Δ≈{put_delta:.2f}) ~{cfg.dte}d out, buy {long_call['strike']} Call + "
        f"{long_put['strike']} Put wings ({cfg.wing_width_pct:.1f}% further OTM) for a defined-risk spread.",
        f"Net credit **{net_credit}** · Max profit **{max_profit}** (both short legs expire worthless) · "
        f"Max loss **{max_loss}** (capped by the wings, not open-ended).",
        f"Estimated probability of profit (from short-strike deltas): **~{pop_pct:.0f}%**.",
        vol_env["reason"],
    ]
    if per_tf_trend:
        if choppy:
            reasons.append(
                f"Market context: {len(per_tf_trend) - strong_trend_count}/{len(per_tf_trend)} selected timeframe(s) "
                "not strongly trending — supportive of a range-bound premium-selling trade."
            )
        else:
            reasons.append(
                f"⚠️ {strong_trend_count}/{len(per_tf_trend)} selected timeframe(s) show a STRONG trend — this "
                "strategy profits from the underlying staying range-bound; a strongly trending market raises the "
                "odds of a short strike being breached."
            )
    reasons.append(
        f"Take profit early: close at **{close_at_price}** cost-to-close (captures "
        f"{cfg.profit_target_pct * 100:.0f}% of max credit) — don't hold to expiry chasing the last few % of premium."
    )
    if defensive_close_price is not None:
        reasons.append(
            f"Optional defensive exit: consider closing if cost-to-close rises to **{defensive_close_price}** "
            f"({cfg.stop_loss_multiple:.1f}x credit received) — the wings already cap the hard max loss at "
            f"{max_loss}, this is just an earlier, gentler exit."
        )
    any_simulated = any(leg.get("source", "").startswith("Simulated") for leg in legs.values())
    if any_simulated:
        reasons.append(
            "One or more legs used simulated (Black-Scholes) pricing — no live/liquid option quote was available "
            "at that strike/expiry. Treat premiums as an estimate, not a fillable quote."
        )

    entry_ok = bool(vol_env["favorable"] and choppy)

    return {
        "ticker": ticker, "asset_class": asset_class, "market": market,
        "spot": round(spot, 4), "realized_vol_pct": round(realized_vol * 100, 2),
        "vol_environment": vol_env,
        "trend_context": per_tf_trend, "strong_trend_count": strong_trend_count, "choppy": choppy,
        "structure": structure_label, "target_expiry": str(target_expiry),
        "short_delta_target": cfg.short_delta_target, "wing_width_pct": cfg.wing_width_pct,
        "legs": legs,
        "net_credit": net_credit, "max_profit": max_profit, "max_loss": max_loss, "pop_pct": pop_pct,
        "close_at_price": close_at_price, "defensive_close_price": defensive_close_price,
        "entry_ok": entry_ok,
        "reasons": reasons,
    }


def build_delta_neutral_many(
    tickers: list[str], asset_class: str, market: str, timeframes: list[str], *,
    cfg: DeltaNeutralConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> list[dict[str, Any]]:
    results = []
    for ticker in tickers:
        try:
            results.append(build_delta_neutral(
                ticker, asset_class, market, timeframes,
                cfg=cfg, groww_token=groww_token, exchange=exchange,
            ))
        except Exception as exc:
            logger.debug("Delta-Neutral failed for %s: %s", ticker, exc)
            results.append({"ticker": ticker, "asset_class": asset_class, "error": str(exc)[:200]})
    return results


def evaluate_delta_neutral_pnl(net_credit: float, current_cost_to_close: float, cfg: DeltaNeutralConfig | None = None) -> dict[str, Any]:
    """current_cost_to_close = what it would cost right now to buy back the spread.
    Profit = net_credit - current_cost_to_close (you received the credit, you pay this to close)."""
    cfg = cfg or DeltaNeutralConfig()
    if net_credit is None or net_credit <= 0:
        return {"error": "Invalid net credit."}
    pnl_pct = (net_credit - current_cost_to_close) / net_credit

    if pnl_pct >= cfg.profit_target_pct:
        action = "CLOSE_PROFIT"
        message = (
            f"🔵 Profit target hit — captured {pnl_pct * 100:.1f}% of max credit. Close now; don't hold to "
            "expiry chasing the last few % of premium."
        )
    elif cfg.stop_loss_multiple and pnl_pct <= -cfg.stop_loss_multiple:
        action = "DEFENSIVE_CLOSE"
        message = (
            f"🔴 Loss has grown to {abs(pnl_pct) * 100:.0f}% of credit received — consider closing before the "
            "wings absorb the full defined max loss."
        )
    else:
        action = "HOLD"
        message = f"⚪ Hold — {pnl_pct * 100:+.1f}% of max credit captured so far; risk stays capped by the wings regardless."
    return {"pnl_pct": round(pnl_pct * 100, 2), "action": action, "message": message}
