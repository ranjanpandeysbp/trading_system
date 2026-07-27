"""
option_short_long_engine.py
------------------------------
Command Center — Option-Short-Long: a single confluence read that combines
options-market positioning (Long/Short Buildup, PCR, OI walls, synthetic
futures premium/discount, IV skew) with price-action confluence (momentum,
Smart Money structure) into one actionable options trade recommendation per
ticker/index — direction, confidence %, BUY/SELL CALL/PUT, strike, expiry,
stop-loss and take-profit.

Reuses, rather than re-derives, everything already proven in this app:
  - option_chain_engine.fetch_option_chain / classify_option_chain_signal
    (PCR, max pain, OI-based support/resistance).
  - double_calendar_engine's NSE expiry helpers, Black-Scholes pricer, and
    the real India-VIX / realized-vol-percentile IV-environment gate.
  - delta_neutral_engine's delta-from-IV and delta-targeted strike selection.
  - momentum_engine.analyze_timeframe + the SMC engine's structure-bias
    primitives for the price-action leg of the confluence.

Two things NOT literally available from any source wired into this app and
therefore approximated honestly (both disclosed in the UI, not hidden):
  1. "Futures OI buildup" — NSE's futures-contract OI/price feed isn't
     integrated here, so Long/Short Buildup is read off the *options* chain's
     aggregate OI change vs price change instead.
  2. "Futures premium/discount" — instead of a separate futures price feed,
     this computes the Put-Call-Parity *synthetic* futures price from the
     ATM straddle (Spot + Call LTP - Put LTP), a standard professional
     technique that carries the same forward-pricing information.

No output here is a guarantee. Confidence % is a heuristic confluence score,
not a statistical win probability. Research / education only — NOT FINANCIAL
ADVICE.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable

import pandas as pd

from app.market_pulse.delta_neutral_engine import _select_strike_by_delta_india
from app.market_pulse.double_calendar_engine import (
    DoubleCalendarConfig,
    _bs_price,
    _fetch_nse_chain_for_expiry,
    _fetch_nse_expiries,
    _nearest_expiry,
    _parse_nse_date,
    check_volatility_environment,
)
from app.market_pulse.momentum_engine import MomentumConfig, analyze_timeframe
from app.market_pulse.option_chain_engine import INDEX_CHOICES, classify_option_chain_signal, fetch_option_chain

logger = logging.getLogger(__name__)

_RISK_FREE_RATE = 0.065
_MIN_DAYS_TO_EXPIRY = 2          # switch to next expiry once fewer trading days remain (gamma/theta risk)
_BUY_DELTA_TARGET = 0.40         # target delta when BUYING a call/put (defined-risk directional buy)
_SELL_DELTA_TARGET = 0.20        # target delta when SELLING a call/put (OTM premium sale)
_BUY_STOP_LOSS_PCT = 0.35        # cut a long-premium trade at 35% loss of premium paid
_BUY_TAKE_PROFIT_PCT = 0.75      # scale out of a long-premium trade at 75% gain
_SELL_TAKE_PROFIT_PCT = 0.50     # classic "buy back a short at 50% of max profit" discipline
_SELL_STOP_LOSS_MULT = 2.0       # stop-loss when cost-to-close reaches 2x the credit received
_MIN_BARS = 60

RISK_DISCLAIMER = (
    "This is a heuristic confluence read across options positioning and price action — it is NOT a "
    "statistical probability of profit and there is NO such thing as a zero-risk options trade. Buying a "
    "call/put has a defined max loss (the premium paid); selling a call/put carries open-ended risk beyond "
    "the stated stop unless you also buy a further OTM option to cap it (turning it into a credit spread). "
    "Always size positions so the stated stop-loss is a loss you can absorb. Research / education only — "
    "NOT FINANCIAL ADVICE."
)


@dataclass
class OptionShortLongConfig:
    risk_free_rate: float = _RISK_FREE_RATE
    min_days_to_expiry: int = _MIN_DAYS_TO_EXPIRY
    buy_delta_target: float = _BUY_DELTA_TARGET
    sell_delta_target: float = _SELL_DELTA_TARGET


def _with_retry(fn: Callable[[], Any], *, retries: int = 2, delay: float = 0.9) -> Any:
    """NSE's option-chain endpoints soft-rate-limit when several symbols are
    scanned back-to-back in the same process (each fetch opens a fresh session
    and re-warms it) — a symbol later in the batch can 404/empty-response even
    though the endpoint itself is fine, as confirmed by retrying it alone. One
    or two short-backoff retries clears this in practice without having to
    restructure the whole session-warming pipeline."""
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            result = fn()
            if result:
                return result
        except Exception as exc:
            last_exc = exc
        if attempt < retries:
            time.sleep(delay * (attempt + 1))
    if last_exc:
        logger.debug("Retry exhausted: %s", last_exc)
    return None


# ---------------------------------------------------------------------------
# Shared fetch / structure-bias helpers (this app has no separate
# day_range_forecast_engine.py — inlined here, reusing the same primitives)
# ---------------------------------------------------------------------------

def _fetch_ohlcv(
    ticker: str, market: str, timeframe: str, *, groww_token: str = "", exchange: str = "NSE", limit: int = 300,
) -> pd.DataFrame:
    from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
    from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
    from app.market_pulse.ticker_utils import is_crypto_market

    is_crypto = is_crypto_market(market)
    df = fetch_data_for_gap_scan(ticker, timeframe, market, groww_token, exchange, limit=limit)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < _MIN_BARS:
        df = normalize_ohlcv(fetch_ohlcv_yfinance(ticker, timeframe, is_crypto=is_crypto, limit=limit, market=market))
    return df


def _smc_structure_bias(df: pd.DataFrame) -> str:
    """Real-structure bullish/bearish/neutral read via fractal swings + BOS/CHoCH
    — the same Smart Money primitive backing SC-Best and C-LewisKelly."""
    try:
        from app.trading_hubs.smc_engine.adapters import to_smc_ohlc
        from app.trading_hubs.smc_engine.config import SMCConfig
        from app.trading_hubs.smc_engine.structure import current_bias, detect_structure_breaks, find_fractal_swings

        df_smc = to_smc_ohlc(df)
        if df_smc.empty or len(df_smc) < 10:
            return "NEUTRAL"
        smc_cfg = SMCConfig()
        swings = find_fractal_swings(df_smc, smc_cfg.fractal_window)
        breaks = detect_structure_breaks(df_smc, swings)
        return current_bias(breaks).value.upper()
    except Exception as exc:
        logger.debug("SMC structure bias failed: %s", exc)
        return "NEUTRAL"


# ---------------------------------------------------------------------------
# Building-block reads
# ---------------------------------------------------------------------------

def _daily_price_change_pct(df: pd.DataFrame) -> float | None:
    closes = df["close"].dropna()
    if len(closes) < 2:
        return None
    prev, last = float(closes.iloc[-2]), float(closes.iloc[-1])
    if prev <= 0:
        return None
    return (last - prev) / prev * 100.0


def classify_oi_buildup(chain: dict[str, Any], price_chg_pct: float | None) -> dict[str, Any]:
    """Long Buildup / Short Buildup / Short Covering / Long Unwinding read off
    the option chain's aggregate OI change vs the underlying's price change —
    the same 4-quadrant matrix NSE traders use on futures OI, applied here as
    an options-OI proxy since this app has no separate futures-OI feed."""
    strikes = chain.get("strikes") or []
    d_oi = sum((s.get("ce_chg_oi") or 0) + (s.get("pe_chg_oi") or 0) for s in strikes)
    if price_chg_pct is None or not strikes:
        return {
            "label": "Unknown", "bias": "NEUTRAL", "strength": 0.0, "d_oi": d_oi,
            "reason": "Not enough data for an OI-buildup read.",
        }

    price_up = price_chg_pct > 0.05
    price_down = price_chg_pct < -0.05
    oi_up = d_oi > 0
    oi_down = d_oi < 0

    if price_up and oi_up:
        return {
            "label": "Long Buildup", "bias": "BULLISH", "strength": 1.0, "d_oi": d_oi,
            "reason": (
                f"Long Buildup — price {price_chg_pct:+.2f}% with fresh OI addition ({d_oi:+,.0f}): "
                "new long positions are being built, the strongest bullish buildup signature. These are "
                "freshly-opened longs, not old ones sitting on a fat profit yet — so there's little "
                "profit-booking risk pressuring a reversal just yet; this move likely has room to run."
            ),
        }
    if price_down and oi_up:
        return {
            "label": "Short Buildup", "bias": "BEARISH", "strength": 1.0, "d_oi": d_oi,
            "reason": (
                f"Short Buildup — price {price_chg_pct:+.2f}% with fresh OI addition ({d_oi:+,.0f}): "
                "new short positions are being built, the strongest bearish buildup signature. These "
                "shorts are freshly opened, not yet sitting on a fat profit — so don't expect a quick "
                "short-covering bounce; this move likely has room to run before shorts start booking gains."
            ),
        }
    if price_up and oi_down:
        return {
            "label": "Short Covering", "bias": "BULLISH", "strength": 0.5, "d_oi": d_oi,
            "reason": (
                f"Short Covering — price {price_chg_pct:+.2f}% while OI unwinds ({d_oi:+,.0f}): the "
                "earlier shorts were sitting in profit and are now booking it by buying back (cutting "
                "shorts), which is what's pushing price up — a bullish but weaker/shorter-lived push than "
                "a fresh Long Buildup. Once most of that covering is done, the bounce can run out of fuel "
                "unless fresh buyers step in."
            ),
        }
    if price_down and oi_down:
        return {
            "label": "Long Unwinding", "bias": "BEARISH", "strength": 0.5, "d_oi": d_oi,
            "reason": (
                f"Long Unwinding — price {price_chg_pct:+.2f}% while OI unwinds ({d_oi:+,.0f}): the "
                "earlier longs were sitting in profit and are now booking it by selling out (cutting "
                "longs), which is what's pushing price down — a bearish but weaker/shorter-lived push "
                "than a fresh Short Buildup. Once most of that unwinding is done, the drop can run out of "
                "fuel unless fresh sellers step in."
            ),
        }
    return {
        "label": "Mixed / Flat", "bias": "NEUTRAL", "strength": 0.0, "d_oi": d_oi,
        "reason": f"Mixed OI — price {price_chg_pct:+.2f}%, ΔOI {d_oi:+,.0f} — no clean buildup signature today.",
    }


def _atm_strike_row(chain: dict[str, Any], spot: float) -> dict[str, Any] | None:
    strikes = chain.get("strikes") or []
    valid = [s for s in strikes if (s.get("ce_ltp") or 0) > 0 and (s.get("pe_ltp") or 0) > 0]
    if not valid or not spot:
        return None
    return min(valid, key=lambda s: abs(s["strike"] - spot))


def synthetic_futures_premium(chain: dict[str, Any], spot: float) -> dict[str, Any]:
    """Put-Call-Parity synthetic futures price: Spot + (ATM Call LTP - ATM Put LTP).
    Standing in for a live futures feed this app doesn't have — same forward-pricing
    information (contango = bullish carry, backwardation = bearish carry)."""
    atm = _atm_strike_row(chain, spot)
    if not atm or not spot:
        return {"available": False, "premium_pct": None, "synthetic_future": None, "reason": "ATM strike not available."}
    synthetic_future = atm["strike"] + (atm["ce_ltp"] - atm["pe_ltp"])
    premium_pct = (synthetic_future - spot) / spot * 100.0
    _abnormal = abs(premium_pct) >= 1.0
    if premium_pct >= 0.15:
        bias = "BULLISH"
        reason = (
            f"Synthetic futures (Put-Call Parity, ATM {atm['strike']:,.0f}) imply {synthetic_future:,.1f}, a "
            f"{premium_pct:+.2f}% premium to spot — contango, the options market is pricing in a bullish carry."
        )
        if _abnormal:
            reason += (
                " That gap is unusually wide for routine cost-of-carry — it often means an event "
                "(results, policy, index rebalance) is being priced in, or that call buying / put "
                "short-covering is already running hot. Treat it as a stronger but less \"free\" signal."
            )
    elif premium_pct <= -0.15:
        bias = "BEARISH"
        reason = (
            f"Synthetic futures (Put-Call Parity, ATM {atm['strike']:,.0f}) imply {synthetic_future:,.1f}, a "
            f"{premium_pct:+.2f}% discount to spot — backwardation, the options market is pricing in a bearish carry."
        )
        if _abnormal:
            reason += (
                " That gap is unusually wide for routine cost-of-carry — it often means an event "
                "(results, policy, index rebalance) is being priced in, or that put buying / call "
                "short-covering panic is already running hot. Treat it as a stronger but less \"free\" signal."
            )
    else:
        bias = "NEUTRAL"
        reason = (
            f"Synthetic futures imply {synthetic_future:,.1f}, essentially flat ({premium_pct:+.2f}%) to spot — "
            "no meaningful premium/discount skew."
        )
    return {
        "available": True, "premium_pct": round(premium_pct, 3), "synthetic_future": round(synthetic_future, 2),
        "bias": bias, "reason": reason,
    }


def iv_skew_read(chain: dict[str, Any], spot: float) -> dict[str, Any]:
    """ATM Put IV vs Call IV skew. Elevated put-side IV = crash-hedging demand
    (mild bearish tilt); elevated call-side IV = melt-up speculative demand
    (mild bullish tilt). Equity index options normally run a modest put skew,
    so only an outsized gap is treated as a signal."""
    atm = _atm_strike_row(chain, spot)
    if not atm:
        return {"available": False, "skew": None, "bias": "NEUTRAL", "reason": "ATM strike not available."}
    ce_iv, pe_iv = atm.get("ce_iv") or 0, atm.get("pe_iv") or 0
    if ce_iv <= 0 or pe_iv <= 0:
        return {"available": False, "skew": None, "bias": "NEUTRAL", "reason": "ATM IV not available."}
    skew = pe_iv - ce_iv
    if skew >= 3.0:
        bias = "BEARISH"
        reason = f"ATM Put IV ({pe_iv:.1f}%) sits {skew:.1f}pts above Call IV ({ce_iv:.1f}%) — elevated downside-hedging demand."
    elif skew <= -3.0:
        bias = "BULLISH"
        reason = f"ATM Call IV ({ce_iv:.1f}%) sits {-skew:.1f}pts above Put IV ({pe_iv:.1f}%) — unusual melt-up speculative demand."
    else:
        bias = "NEUTRAL"
        reason = f"ATM Call IV {ce_iv:.1f}% vs Put IV {pe_iv:.1f}% — a normal, unremarkable skew."
    return {"available": True, "skew": round(skew, 2), "ce_iv": ce_iv, "pe_iv": pe_iv, "bias": bias, "reason": reason}


def fetch_fii_dii_sentiment() -> dict[str, Any]:
    """Market-wide cash-segment FII/DII net buy/sell (NSE + StockEdge), scored
    for sentiment. This is index-wide institutional flow, NOT specific to any
    one symbol — callers should fetch it ONCE per scan (not per-symbol) and
    label it clearly as market-wide context, not a stock-specific read.
    Returns {"score": float, "reasons": [str, ...]} — score=0/reasons=[] if
    the feed is unavailable (never raises)."""
    try:
        from app.market_pulse.news_scanner import analyze_fii_dii_sentiment, fetch_nse_fii_dii

        data = fetch_nse_fii_dii()
        sentiment = analyze_fii_dii_sentiment(data)
        reasons = [r.replace("**", "") for r in (sentiment.get("reasons") or [])]
        return {"score": float(sentiment.get("score") or 0), "reasons": reasons}
    except Exception as exc:
        logger.debug("FII/DII sentiment fetch failed: %s", exc)
        return {"score": 0.0, "reasons": []}


def _time_decay_note(days_to_expiry: int, action: str | None) -> str:
    """Beginner-friendly theta note — decay direction and urgency depend on
    whether the plan is to buy premium (decay is the enemy) or sell/write it
    (decay is the ally), and how few days are left (decay accelerates near
    expiry, especially in the final week)."""
    is_buyer = action in ("BUY_CALL", "BUY_PUT")
    is_seller = action in ("SELL_CALL", "SELL_PUT")
    if days_to_expiry <= 3:
        urgency = (
            f"Only {days_to_expiry} day(s) to this expiry — theta decay is now brutal and accelerating "
            "by the hour."
        )
    elif days_to_expiry <= 7:
        urgency = f"{days_to_expiry} days to this expiry — inside the final week, where decay speeds up noticeably."
    else:
        urgency = f"{days_to_expiry} days to this expiry — decay is still gentle for now, picking up pace as expiry nears."

    if is_buyer:
        return (
            f"[Time Decay] {urgency} You'd be BUYING the option here, so decay works against you — the "
            "premium bleeds away daily even if the underlying goes nowhere. You need the move to happen "
            "soon, not just eventually; don't sit in a fading position hoping it turns around."
        )
    if is_seller:
        return (
            f"[Time Decay] {urgency} You'd be SELLING/writing the option here, so decay works FOR you — "
            "every day that passes without an adverse move quietly adds to your profit. The main risk "
            "isn't time, it's a sudden move against your strike."
        )
    return f"[Time Decay] {urgency} No trade is suggested right now, so decay isn't working for or against a live position."


def _beginner_bottom_line(
    direction: str, buildup: dict, action: str | None, days_to_expiry: int, fii_dii_score: float,
) -> str:
    """One synthesized, plain-English wrap-up for someone new to options — who's
    positioned where, whether that positioning looks set to get cut (covered/
    unwound) or added to, and the practical decay takeaway."""
    label = buildup.get("label", "Mixed / Flat")
    if label == "Long Buildup":
        crowd = "fresh buyers are building new long positions — conviction is building, not yet due for profit-booking."
    elif label == "Short Buildup":
        crowd = "fresh sellers are building new short positions — conviction is building, not yet due for a covering bounce."
    elif label == "Short Covering":
        crowd = "existing shorts are being cut (bought back) after sitting in profit — this bounce can fade once that covering finishes."
    elif label == "Long Unwinding":
        crowd = "existing longs are being cut (sold out) after sitting in profit — this drop can fade once that unwinding finishes."
    else:
        crowd = "positioning is mixed today with no dominant side building or unwinding."

    flow = ""
    if fii_dii_score >= 5:
        flow = " Institutional cash flows (FII/DII) are also net supportive today, adding a bit of tailwind."
    elif fii_dii_score <= -5:
        flow = " Institutional cash flows (FII/DII) are net negative today, adding a bit of headwind."

    if direction == "NEUTRAL" or not action:
        verdict = "the overall read is NEUTRAL — no clean edge either way, so WAIT is the honest call rather than forcing a trade."
    else:
        verdict = f"the overall read leans {direction}, translating to a suggested {action.replace('_', ' ')}."

    return (
        f"🧭 Bottom line: {crowd}{flow} Putting it together, {verdict} Remember confidence % is a "
        f"confluence score, not a win-rate — size any position so the stated stop-loss is a loss you "
        f"can shrug off, and keep the {days_to_expiry}-day time decay clock in mind."
    )


# ---------------------------------------------------------------------------
# Confluence score
# ---------------------------------------------------------------------------

def _score_confluence(
    oc_signal: dict, buildup: dict, premium: dict, skew: dict, mom: dict, structure_bias: str,
    fii_dii: dict | None = None,
) -> dict[str, Any]:
    reasons: list[str] = []
    score = 0.0

    conf = (oc_signal.get("confidence_pct") or 50.0) / 100.0
    if oc_signal.get("bias") == "BULLISH":
        score += 22 * conf
    elif oc_signal.get("bias") == "BEARISH":
        score -= 22 * conf
    reasons.append(f"[Options chain] {oc_signal.get('bias')} bias, {oc_signal.get('confidence_pct')}% confidence (PCR/OI-walls/max-pain).")
    for r in oc_signal.get("reasons") or []:
        reasons.append(f"  · {r}")

    if buildup.get("bias") == "BULLISH":
        score += 16 * buildup.get("strength", 1.0)
    elif buildup.get("bias") == "BEARISH":
        score -= 16 * buildup.get("strength", 1.0)
    reasons.append(f"[OI Buildup] {buildup.get('reason')}")

    if premium.get("available") and premium.get("bias") == "BULLISH":
        score += 10
        reasons.append(f"[Premium/Discount] {premium.get('reason')}")
    elif premium.get("available") and premium.get("bias") == "BEARISH":
        score -= 10
        reasons.append(f"[Premium/Discount] {premium.get('reason')}")
    elif premium.get("available"):
        reasons.append(f"[Premium/Discount] {premium.get('reason')}")

    if skew.get("available") and skew.get("bias") == "BEARISH":
        score -= 6
        reasons.append(f"[IV Skew] {skew.get('reason')}")
    elif skew.get("available") and skew.get("bias") == "BULLISH":
        score += 6
        reasons.append(f"[IV Skew] {skew.get('reason')}")
    elif skew.get("available"):
        reasons.append(f"[IV Skew] {skew.get('reason')}")

    trend = mom.get("trend_direction")
    strength = mom.get("strength")
    adx = mom.get("adx") or 0
    if trend == "UP":
        w = 20 if strength == "STRONG" else 12 if strength == "MEDIUM" else 5
        score += w
        reasons.append(f"[Momentum] {strength.lower() if strength else 'weak'} uptrend (ADX {adx}).")
    elif trend == "DOWN":
        w = 20 if strength == "STRONG" else 12 if strength == "MEDIUM" else 5
        score -= w
        reasons.append(f"[Momentum] {strength.lower() if strength else 'weak'} downtrend (ADX {adx}).")
    else:
        reasons.append("[Momentum] No clean directional edge.")

    breakout_event = mom.get("breakout_event", "NONE")
    vol_ratio = mom.get("volume_ratio") or 1.0
    if breakout_event == "RESISTANCE_BREAK":
        confirmed = vol_ratio >= 1.15
        score += 12 if confirmed else 6
        reasons.append(f"[Momentum] Fresh breakout above resistance{' — volume-confirmed' if confirmed else ' — thin volume'}.")
    elif breakout_event == "SUPPORT_BREAK":
        confirmed = vol_ratio >= 1.15
        score -= 12 if confirmed else 6
        reasons.append(f"[Momentum] Fresh breakdown below support{' — volume-confirmed' if confirmed else ' — thin volume'}.")

    if structure_bias == "BULLISH":
        score += 14
        reasons.append("[Smart Money] Bullish market structure (recent BOS/CHoCH up).")
    elif structure_bias == "BEARISH":
        score -= 14
        reasons.append("[Smart Money] Bearish market structure (recent BOS/CHoCH down).")
    else:
        reasons.append("[Smart Money] No clear structural bias.")

    if fii_dii and fii_dii.get("reasons"):
        fii_score = float(fii_dii.get("score") or 0)
        score += max(-6.0, min(6.0, fii_score * 0.3))
        for r in fii_dii["reasons"]:
            reasons.append(f"[FII/DII Flow — market-wide, not symbol-specific] {r}")

    score = max(-100.0, min(100.0, score))
    direction = "UP" if score >= 15 else "DOWN" if score <= -15 else "NEUTRAL"
    confidence_pct = round(min(88.0, 50.0 + abs(score) * 0.6), 1) if direction != "NEUTRAL" else round(50.0 + abs(score) * 0.3, 1)

    return {"direction": direction, "score": round(score, 1), "confidence_pct": confidence_pct, "reasons": reasons}


# ---------------------------------------------------------------------------
# Expiry selection + strike/stop/target build
# ---------------------------------------------------------------------------

def _pick_expiry(symbol: str, is_index: bool, chain: dict[str, Any], cfg: OptionShortLongConfig) -> tuple[str, dict[str, Any], bool]:
    """Returns (expiry, chain_for_that_expiry, switched). Avoids trading an
    expiry with too few days left (gamma/theta/spread risk near expiry)."""
    current_expiry = chain.get("current_expiry")
    today = date.today()
    d = _parse_nse_date(current_expiry) if current_expiry else None
    if d is None or (d - today).days > cfg.min_days_to_expiry:
        return current_expiry, chain, False

    expiries = _fetch_nse_expiries(symbol, is_index) or (chain.get("expiry_dates") or [])
    next_expiry = _nearest_expiry(expiries, today + timedelta(days=7), after=d)
    if not next_expiry:
        return current_expiry, chain, False
    next_chain = _fetch_nse_chain_for_expiry(symbol, next_expiry, is_index)
    if not next_chain or not next_chain.get("strikes"):
        return current_expiry, chain, False
    return next_expiry, next_chain, True


def _implied_spot_for_price(
    target_price: float, strike: float, t_years: float, vol: float, r: float, option_type: str, spot_guess: float,
) -> float | None:
    if spot_guess <= 0 or vol <= 0 or t_years <= 0:
        return None
    lo, hi = spot_guess * 0.4, spot_guess * 1.8
    for _ in range(60):
        mid = (lo + hi) / 2
        price = _bs_price(mid, strike, t_years, vol, r, option_type)
        if option_type == "call":
            if price < target_price:
                lo = mid
            else:
                hi = mid
        else:
            if price < target_price:
                hi = mid
            else:
                lo = mid
    return round((lo + hi) / 2, 2)


def _build_trade_plan(
    action: str, chain: dict, spot: float, t_years: float, expiry: str, cfg: OptionShortLongConfig,
    vol_regime: dict | None = None,
) -> dict[str, Any] | None:
    """action: BUY_CALL / BUY_PUT / SELL_CALL / SELL_PUT.

    `vol_regime` (see vol_regime.py) flexes how much profit-taking patience
    the plan allows: in a calm/trending regime it's worth waiting for a
    bigger move (buyer) or more decay (seller) before taking profit; in an
    extreme-vol regime, blow-off moves reverse fast, so both sides should
    take profit sooner rather than hold out for the full target."""
    side = "call" if "CALL" in action else "put"
    is_buy = action.startswith("BUY")
    target_delta = cfg.buy_delta_target if is_buy else cfg.sell_delta_target

    leg = _select_strike_by_delta_india(chain, spot, t_years, target_delta, cfg.risk_free_rate, side)
    if not leg or leg.get("premium", 0) <= 0:
        return None

    strike, premium, iv = leg["strike"], leg["premium"], leg.get("iv") or 0
    vol = max(iv, 1.0) / 100.0
    half_t = max(t_years * 0.5, 1 / 365.0)
    rr_mult = (vol_regime or {}).get("rr_multiplier", 1.0)
    regime_label = (vol_regime or {}).get("regime")

    if is_buy:
        stop_premium = round(premium * (1 - _BUY_STOP_LOSS_PCT), 2)
        target_premium = round(premium * (1 + _BUY_TAKE_PROFIT_PCT * rr_mult), 2)
        stop_spot = _implied_spot_for_price(stop_premium, strike, half_t, vol, cfg.risk_free_rate, side, spot)
        target_spot = _implied_spot_for_price(target_premium, strike, half_t, vol, cfg.risk_free_rate, side, spot)
        max_loss_note = f"Max loss is capped at the premium paid (₹{premium:,.2f}/share) if you never average up — defined risk."
    else:
        stop_premium = round(premium * _SELL_STOP_LOSS_MULT, 2)
        target_premium = round(premium * (1 - _SELL_TAKE_PROFIT_PCT * rr_mult), 2)
        stop_spot = _implied_spot_for_price(stop_premium, strike, half_t, vol, cfg.risk_free_rate, side, spot)
        target_spot = _implied_spot_for_price(target_premium, strike, half_t, vol, cfg.risk_free_rate, side, spot)
        max_loss_note = (
            "UNDEFINED risk beyond the stop — this is a naked short option. Cap it by also buying a further "
            "OTM option (turns it into a credit spread) if you want a hard max loss."
        )

    return {
        "action": action, "side": side, "strike": strike, "premium": premium, "iv": iv,
        "expiry": expiry, "days_to_expiry": round(t_years * 365),
        "stop_premium": stop_premium, "target_premium": target_premium,
        "stop_underlying": stop_spot, "target_underlying": target_spot,
        "is_buy": is_buy, "max_loss_note": max_loss_note,
        "vol_regime": regime_label,
        "reward_risk_ratio": (
            round(abs(target_premium - premium) / max(abs(premium - stop_premium), 0.01), 2)
        ),
    }


def build_payoff_curve(trade_plan: dict[str, Any], spot: float, cfg: OptionShortLongConfig | None = None) -> dict[str, Any]:
    """Per-share P&L vs underlying price for the recommended trade — both the
    kinked at-expiry payoff and a Black-Scholes-repriced right-now curve (same
    IV, current days-to-expiry) so the chart shows time value, not just the
    terminal payoff."""
    cfg = cfg or OptionShortLongConfig()
    strike, premium, side = trade_plan["strike"], trade_plan["premium"], trade_plan["side"]
    is_buy = trade_plan["is_buy"]
    vol = max(trade_plan.get("iv") or 20.0, 1.0) / 100.0
    t_years = max(trade_plan.get("days_to_expiry") or 1, 1) / 365.0

    lo, hi = spot * 0.85, spot * 1.15
    n = 61
    step = (hi - lo) / (n - 1)
    xs, expiry_pnl, now_pnl = [], [], []
    for i in range(n):
        s = round(lo + i * step, 2)
        intrinsic = max(0.0, s - strike) if side == "call" else max(0.0, strike - s)
        now_price = _bs_price(s, strike, t_years, vol, cfg.risk_free_rate, side)
        if is_buy:
            expiry_pnl.append(round(intrinsic - premium, 2))
            now_pnl.append(round(now_price - premium, 2))
        else:
            expiry_pnl.append(round(premium - intrinsic, 2))
            now_pnl.append(round(premium - now_price, 2))
        xs.append(s)

    breakeven = round(strike + premium if side == "call" else strike - premium, 2)
    return {"x": xs, "expiry_pnl": expiry_pnl, "now_pnl": now_pnl, "breakeven": breakeven}


def _decide_action(direction: str, vol_env: dict) -> str | None:
    favorable = vol_env.get("favorable", True)  # True = low/normal IV -> buy premium; False = elevated IV -> sell premium
    if direction == "UP":
        return "BUY_CALL" if favorable else "SELL_PUT"
    if direction == "DOWN":
        return "BUY_PUT" if favorable else "SELL_CALL"
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_ticker(
    symbol: str, is_index: bool, *, groww_token: str = "", cfg: OptionShortLongConfig | None = None,
    fii_dii: dict | None = None,
) -> dict[str, Any]:
    cfg = cfg or OptionShortLongConfig()
    symbol = (symbol or "").strip().upper()
    empty = {"symbol": symbol, "ok": False, "error": "Could not fetch option chain / price data."}

    chain = _with_retry(lambda: fetch_option_chain(symbol, is_index, groww_token))
    if not chain or not chain.get("strikes"):
        return empty

    df = _fetch_ohlcv(symbol, "india", "1d", groww_token=groww_token, exchange="NSE", limit=300)
    if df is None or df.empty:
        return empty

    spot = chain.get("underlying") or float(df["close"].iloc[-1])
    price_chg_pct = _daily_price_change_pct(df)

    oc_signal = classify_option_chain_signal(chain)
    buildup = classify_oi_buildup(chain, price_chg_pct)
    premium = synthetic_futures_premium(chain, spot)
    skew = iv_skew_read(chain, spot)
    fii_dii = fii_dii if fii_dii is not None else fetch_fii_dii_sentiment()

    from app.market_pulse.vol_regime import compute_vol_regime

    vr = compute_vol_regime(df)
    vol_regime = {"regime": vr.regime, "rr_multiplier": vr.rr_multiplier} if vr else None

    try:
        mom = analyze_timeframe(df, "1d", MomentumConfig()) or {}
    except Exception as exc:
        logger.debug("Momentum read failed for %s: %s", symbol, exc)
        mom = {}
    structure_bias = _smc_structure_bias(df)

    confluence = _score_confluence(oc_signal, buildup, premium, skew, mom, structure_bias, fii_dii)

    dc_cfg = DoubleCalendarConfig()
    vol_env = check_volatility_environment("india", df, dc_cfg)

    expiry, expiry_chain, switched_expiry = _pick_expiry(symbol, is_index, chain, cfg)
    expiry_date = _parse_nse_date(expiry) if expiry else None
    days_to_expiry = max((expiry_date - date.today()).days, 1) if expiry_date else 7
    t_years = days_to_expiry / 365.0

    action = _decide_action(confluence["direction"], vol_env)
    trade_plan = _build_trade_plan(action, expiry_chain, spot, t_years, expiry, cfg, vol_regime) if action else None
    payoff = build_payoff_curve(trade_plan, spot, cfg) if trade_plan else None

    reasons = [
        *confluence["reasons"],
        _time_decay_note(days_to_expiry, action),
        _beginner_bottom_line(confluence["direction"], buildup, action, days_to_expiry, fii_dii.get("score") or 0.0),
    ]

    strikes = sorted((chain.get("strikes") or []), key=lambda s: s.get("strike", 0))
    near_atm_strikes = [s for s in strikes if spot and abs(s.get("strike", 0) - spot) / spot <= 0.06]

    return {
        "symbol": symbol, "ok": True, "spot": spot, "price_chg_pct": price_chg_pct,
        "direction": confluence["direction"], "confidence_pct": confluence["confidence_pct"],
        "score": confluence["score"], "reasons": reasons,
        "oc_signal": oc_signal, "buildup": buildup, "premium": premium, "skew": skew,
        "momentum": mom, "structure_bias": structure_bias,
        "vol_environment": vol_env, "expiry": expiry, "switched_expiry": switched_expiry,
        "action": action, "trade_plan": trade_plan, "payoff": payoff,
        "support": oc_signal.get("support"), "resistance": oc_signal.get("resistance"),
        "max_pain": chain.get("max_pain"), "pcr_oi": chain.get("pcr_oi"),
        "oi_strikes": near_atm_strikes or strikes[:20],
    }


def scan_universe(
    symbols: list[str], is_index: bool, *, groww_token: str = "", cfg: OptionShortLongConfig | None = None,
) -> list[dict[str, Any]]:
    fii_dii = fetch_fii_dii_sentiment()  # market-wide, same for every symbol — fetch once per scan
    results = []
    for i, sym in enumerate(symbols):
        if i > 0:
            time.sleep(0.3)  # stagger NSE hits so a later symbol in the batch isn't soft-throttled
        results.append(analyze_ticker(sym, is_index, groww_token=groww_token, cfg=cfg, fii_dii=fii_dii))
    results.sort(key=lambda r: (r.get("ok", False), r.get("confidence_pct") or 0), reverse=True)
    return results


_MAX_EXPIRIES = 5


def list_expiries(symbol: str, is_index: bool, *, max_expiries: int = _MAX_EXPIRIES) -> list[str]:
    """Next N listed expiry dates for a symbol, nearest first — lets the UI
    offer a real multi-expiry picker instead of only ever analyzing whichever
    expiry _pick_expiry would have auto-selected."""
    symbol = (symbol or "").strip().upper()
    expiries = _with_retry(lambda: _fetch_nse_expiries(symbol, is_index)) or []
    return list(expiries[:max_expiries])


def analyze_ticker_expiries(
    symbol: str, is_index: bool, expiries: list[str] | None = None, *,
    groww_token: str = "", cfg: OptionShortLongConfig | None = None, max_expiries: int = _MAX_EXPIRIES,
    fii_dii: dict | None = None,
) -> dict[str, Any]:
    """Like `analyze_ticker`, but returns one confluence read PER requested
    expiry (defaulting to the next `max_expiries` listed ones) instead of only
    the single auto-picked nearest-tradeable expiry. The OHLCV-based reads
    (momentum, Smart Money structure, IV environment) don't depend on which
    expiry is chosen, so they're fetched/computed once and shared; only the
    option-chain-derived reads (chain bias, OI buildup, premium/discount, IV
    skew, strike selection, trade plan, payoff) are recomputed per expiry."""
    cfg = cfg or OptionShortLongConfig()
    symbol = (symbol or "").strip().upper()
    empty = {"symbol": symbol, "ok": False, "error": "Could not fetch option chain / price data.", "by_expiry": []}

    base_chain = _with_retry(lambda: fetch_option_chain(symbol, is_index, groww_token))
    if not base_chain or not base_chain.get("strikes"):
        return empty

    df = _fetch_ohlcv(symbol, "india", "1d", groww_token=groww_token, exchange="NSE", limit=300)
    if df is None or df.empty:
        return empty

    spot = base_chain.get("underlying") or float(df["close"].iloc[-1])
    price_chg_pct = _daily_price_change_pct(df)
    fii_dii = fii_dii if fii_dii is not None else fetch_fii_dii_sentiment()

    from app.market_pulse.vol_regime import compute_vol_regime

    vr = compute_vol_regime(df)
    vol_regime = {"regime": vr.regime, "rr_multiplier": vr.rr_multiplier} if vr else None

    try:
        mom = analyze_timeframe(df, "1d", MomentumConfig()) or {}
    except Exception as exc:
        logger.debug("Momentum read failed for %s: %s", symbol, exc)
        mom = {}
    structure_bias = _smc_structure_bias(df)
    dc_cfg = DoubleCalendarConfig()
    vol_env = check_volatility_environment("india", df, dc_cfg)

    all_expiries = _with_retry(lambda: _fetch_nse_expiries(symbol, is_index)) or (base_chain.get("expiry_dates") or [])
    target_expiries = expiries or list(all_expiries[:max_expiries])
    if not target_expiries:
        target_expiries = [base_chain.get("current_expiry")]

    by_expiry: list[dict[str, Any]] = []
    for i, expiry in enumerate(target_expiries):
        if not expiry:
            continue
        if i > 0:
            time.sleep(0.3)
        chain = (
            base_chain if expiry == base_chain.get("current_expiry")
            else _with_retry(lambda e=expiry: _fetch_nse_chain_for_expiry(symbol, e, is_index))
        )
        if not chain or not chain.get("strikes"):
            by_expiry.append({"expiry": expiry, "ok": False, "error": "Could not fetch this expiry's option chain."})
            continue

        oc_signal = classify_option_chain_signal(chain)
        buildup = classify_oi_buildup(chain, price_chg_pct)
        premium = synthetic_futures_premium(chain, spot)
        skew = iv_skew_read(chain, spot)
        confluence = _score_confluence(oc_signal, buildup, premium, skew, mom, structure_bias, fii_dii)

        expiry_date = _parse_nse_date(expiry)
        days_to_expiry = max((expiry_date - date.today()).days, 1) if expiry_date else 7
        t_years = days_to_expiry / 365.0

        action = _decide_action(confluence["direction"], vol_env)
        trade_plan = _build_trade_plan(action, chain, spot, t_years, expiry, cfg, vol_regime) if action else None
        payoff = build_payoff_curve(trade_plan, spot, cfg) if trade_plan else None

        reasons = [
            *confluence["reasons"],
            _time_decay_note(days_to_expiry, action),
            _beginner_bottom_line(confluence["direction"], buildup, action, days_to_expiry, fii_dii.get("score") or 0.0),
        ]

        strikes = sorted((chain.get("strikes") or []), key=lambda s: s.get("strike", 0))
        near_atm_strikes = [s for s in strikes if spot and abs(s.get("strike", 0) - spot) / spot <= 0.06]

        by_expiry.append({
            "expiry": expiry, "ok": True,
            "direction": confluence["direction"], "confidence_pct": confluence["confidence_pct"],
            "score": confluence["score"], "reasons": reasons,
            "oc_signal": oc_signal, "buildup": buildup, "premium": premium, "skew": skew,
            "action": action, "trade_plan": trade_plan, "payoff": payoff,
            "support": oc_signal.get("support"), "resistance": oc_signal.get("resistance"),
            "max_pain": chain.get("max_pain"), "pcr_oi": chain.get("pcr_oi"),
            "oi_strikes": near_atm_strikes or strikes[:20],
        })

    return {
        "symbol": symbol, "ok": True, "spot": spot, "price_chg_pct": price_chg_pct,
        "momentum": mom, "structure_bias": structure_bias, "vol_environment": vol_env,
        "available_expiries": list(all_expiries[:max_expiries]) if all_expiries else [],
        "by_expiry": by_expiry,
    }


def scan_universe_expiries(
    symbols: list[str], is_index: bool, expiries: list[str] | None = None, *,
    groww_token: str = "", cfg: OptionShortLongConfig | None = None,
) -> list[dict[str, Any]]:
    fii_dii = fetch_fii_dii_sentiment()  # market-wide, same for every symbol — fetch once per scan
    results = []
    for i, sym in enumerate(symbols):
        if i > 0:
            time.sleep(0.3)
        results.append(analyze_ticker_expiries(sym, is_index, expiries, groww_token=groww_token, cfg=cfg, fii_dii=fii_dii))
    return results
