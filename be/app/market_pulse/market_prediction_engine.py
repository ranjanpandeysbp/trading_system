"""
market_prediction_engine.py
-----------------------------
"Market Prediction" — checks whether today's index price move (Nifty / Bank
Nifty / Fin Nifty) is actually backed by real conviction in the derivatives
data, or is a "hollow" move at risk of reversing — the same desk-level read
described in the reference walkthrough: a rally (or decline) is only as
trustworthy as the futures premium, OI buildup, and options IV skew backing
it, not the headline candle color alone.

Reuses, rather than re-derives, everything already proven in this app:
  - option_chain_engine.fetch_option_chain — live NSE/Groww option chain.
  - option_short_long_engine.classify_oi_buildup / synthetic_futures_premium /
    iv_skew_read / fetch_fii_dii_sentiment — this app's already-honest,
    already-disclosed stand-ins for a live futures-OI/futures-price feed
    (Put-Call-Parity synthetic futures, options-chain OI as an OI-buildup
    proxy, ATM Put/Call IV skew, and NSE/StockEdge cash-segment FII/DII flow).

New here (nothing wired into this app computes these yet):
  - India VIX level + day change (yfinance ^INDIAVIX — no Groww/NSE VIX feed
    exists in this app).
  - A "late-session jump" check — today's last-N-minute move compared
    against the day's own distribution of N-minute moves, flagging an
    outsized, low-context late move the way a trading desk would eyeball it.

Two real derivative-market data points this app has no feed for at all —
actual NSE index-futures LTP and FII index-derivative (not cash) net
positioning — are accepted as OPTIONAL manual inputs (`futures_price`,
`fii_index_position_cut`) rather than being silently ignored or faked; when
omitted, the synthetic-futures-premium and cash-market FII/DII reads above
stand in for them, clearly labeled as such in every reason string.

Research / education only — NOT FINANCIAL ADVICE.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from app.market_pulse.pro_trade_shared import (
    ConfidenceScore,
    atr as _atr_ind,
    liquidity_ok,
    momentum_exhaustion_note,
    quality_grade,
    rr_ratio,
    rsi as _rsi_ind,
    sl_tp_pct,
    volume_zscore,
)

logger = logging.getLogger(__name__)

# Pulled from NSE's own underlying-information API (the same data
# nseindia.com/option-chain itself uses) and verified live — this is the
# authoritative, current list of indices NSE actually lists F&O contracts
# for, not a guess. Kept in sync with option_chain_engine.INDEX_CHOICES.
# BSE's Sensex/Bankex are deliberately NOT included: this app has no working
# options-chain data source for them (BSE's own derivatives API returned a
# 503 when tested live, and Groww's option-chain endpoint returns nothing
# for BSE index symbols even with a valid token — verified live, not
# assumed), so listing them would silently produce a "could not fetch
# option chain" error rather than a real read.
INDEX_CHOICES: list[dict[str, str]] = [
    {"value": "NIFTY", "label": "Nifty 50"},
    {"value": "BANKNIFTY", "label": "Bank Nifty"},
    {"value": "FINNIFTY", "label": "Nifty Financial Services"},
    {"value": "MIDCPNIFTY", "label": "Nifty Midcap Select"},
    {"value": "NIFTYNXT50", "label": "Nifty Next 50"},
]


@dataclass
class MarketPredictionConfig:
    late_jump_lookback_minutes: int = 5
    late_jump_zscore_threshold: float = 2.0
    premium_abnormal_pct: float = 0.5
    skew_threshold: float = 3.0
    vix_rise_threshold_pct: float = 3.0
    divergence_score_threshold: float = -20.0
    caution_score_threshold: float = 0.0


# Optional extra confluence checks a user can opt into — stocks only (an
# index symbol like NIFTY isn't a chartable single-name ticker for these
# engines the way a stock is). Each runs its own live single-ticker read on
# the symbol and adds/subtracts trade-suggestion confidence based on whether
# it agrees with the BUY/SELL direction this read already settled on, the
# same "extra confirmation, not a new filter" pattern used for Intra-Hedging.
FURTHER_ANALYSIS_OPTIONS: list[dict[str, str]] = [
    {"id": "pa_vp_smc", "label": "PA-VP-SMC"},
    {"id": "volume_spread_next_candle", "label": "Volume Spread - Next Candle"},
    {"id": "elliott_wave", "label": "Elliott Wave"},
    {"id": "bb_mean_reversion", "label": "BB Mean Reversion"},
    {"id": "support_resistance", "label": "Support & Resistance"},
    {"id": "mtf_trend_strength", "label": "Trend & Strength (MTF)"},
]
_FURTHER_ANALYSIS_CONFIRM_POINTS = 6.0
_FURTHER_ANALYSIS_DISAGREE_POINTS = 4.0


def _apply_further_analysis(
    symbol: str, direction_wanted: str, checks: list[str],
    *, market: str = "India", groww_token: str = "", exchange: str = "NSE",
) -> tuple[list[str], float]:
    """Runs every user-selected optional check against this symbol. Reuses
    Intra-Hedging's own per-check dispatcher rather than re-deriving the same
    6 engine calls a second time. Never raises — an opt-in extra never breaks
    the core Market Prediction read."""
    valid_ids = {o["id"] for o in FURTHER_ANALYSIS_OPTIONS}
    valid = [c for c in (checks or []) if c in valid_ids]
    if not valid:
        return [], 0.0

    from app.trading_hubs.intra_hedging_engine import _run_one_further_check

    reasons: list[str] = []
    delta = 0.0
    for check_id in valid:
        confirmed, note = _run_one_further_check(
            check_id, symbol, market, direction_wanted,
            momentum_timeframe="1d", groww_token=groww_token, exchange=exchange,
        )
        if note:
            reasons.append(note)
        if confirmed is True:
            delta += _FURTHER_ANALYSIS_CONFIRM_POINTS
        elif confirmed is False:
            delta -= _FURTHER_ANALYSIS_DISAGREE_POINTS
    return reasons, delta


def _vix_read() -> dict[str, Any]:
    """India VIX level + day-over-day change — no Groww/NSE VIX feed exists
    in this app, so this is the one place that goes to yfinance directly for
    an index reading (^INDIAVIX has no tradeable Groww equivalent)."""
    try:
        import yfinance as yf

        hist = yf.Ticker("^INDIAVIX").history(period="5d", interval="1d", auto_adjust=True)
        if hist is None or hist.empty:
            return {"available": False}
        closes = hist["Close"].dropna()
        if len(closes) < 1:
            return {"available": False}
        last = float(closes.iloc[-1])
        prev = float(closes.iloc[-2]) if len(closes) > 1 else None
        change_pct = round((last - prev) / prev * 100, 2) if prev else None
        return {"available": True, "level": round(last, 2), "change_pct": change_pct}
    except Exception as exc:
        logger.debug("India VIX fetch failed: %s", exc)
        return {"available": False}


def _late_session_jump_read(df_intraday: pd.DataFrame | None, cfg: MarketPredictionConfig) -> dict[str, Any]:
    """Flags today's most recent N-minute move as unusual when it's a
    statistical outlier vs the day's own N-minute moves so far — the
    programmatic form of "a 150-point jump in the last 5 minutes on average
    volume" (this app has no per-minute index *volume* series to check
    directly, so the move's size relative to the day's own typical move is
    used as the anomaly signal instead)."""
    if df_intraday is None or df_intraday.empty or "close" not in df_intraday.columns:
        return {"available": False}
    closes = df_intraday["close"].astype(float).dropna()
    n = cfg.late_jump_lookback_minutes
    if len(closes) < n + 15:
        return {"available": False}
    rolling_ret = (closes.pct_change(n) * 100).dropna()
    if len(rolling_ret) < 10:
        return {"available": False}
    last_move = float(rolling_ret.iloc[-1])
    baseline = rolling_ret.iloc[:-1]
    mean, std = float(baseline.mean()), float(baseline.std() or 0.0)
    z = (last_move - mean) / std if std > 0 else 0.0
    unusual = abs(z) >= cfg.late_jump_zscore_threshold
    direction = "up" if last_move > 0 else "down"
    reason = (
        f"Last {n} minutes moved {last_move:+.2f}% — {abs(z):.1f}× the day's typical {n}-minute swing"
        + (f", an unusually sharp late {direction}-move for the volume/context seen so far today." if unusual
           else ", within the day's normal range.")
    )
    return {
        "available": True, "last_move_pct": round(last_move, 3), "zscore": round(z, 2),
        "unusual": unusual, "direction": direction, "reason": reason,
    }


def _synthesize_view(
    *, symbol: str, spot: float, price_chg_pct: float | None,
    buildup: dict[str, Any], premium: dict[str, Any], skew: dict[str, Any],
    fii_dii: dict[str, Any], vix: dict[str, Any], late_jump: dict[str, Any],
    chain_signal: dict[str, Any] | None,
    manual_basis: dict[str, Any] | None, fii_index_position_cut: bool | None,
    cfg: MarketPredictionConfig,
) -> dict[str, Any]:
    if price_chg_pct is None or abs(price_chg_pct) < 0.1:
        move_direction = "FLAT"
    elif price_chg_pct > 0:
        move_direction = "UP"
    else:
        move_direction = "DOWN"

    score = 0.0
    warnings: list[str] = []
    confirmations: list[str] = []

    def _aligned(bias: str) -> bool:
        return (bias == "BULLISH" and move_direction == "UP") or (bias == "BEARISH" and move_direction == "DOWN")

    def _opposed(bias: str) -> bool:
        return (bias == "BEARISH" and move_direction == "UP") or (bias == "BULLISH" and move_direction == "DOWN")

    # 1. Real futures basis, if the user supplied today's actual NSE futures LTP.
    if manual_basis:
        basis_pct = manual_basis["basis_pct"]
        bias = "BULLISH" if basis_pct > 0.05 else "BEARISH" if basis_pct < -0.05 else "NEUTRAL"
        note = (
            f"[Futures Basis] NIFTY futures {manual_basis['futures_price']:,.1f} vs spot "
            f"{manual_basis['spot']:,.1f} — {basis_pct:+.2f}% ({'premium/contango' if basis_pct > 0 else 'discount/backwardation' if basis_pct < 0 else 'flat'})."
        )
        if move_direction != "FLAT" and _opposed(bias):
            score -= 18
            warnings.append(note + " This directly contradicts today's move — a classic bearish-divergence tell when it's a discount during a rally, or a premium during a selloff.")
        elif move_direction != "FLAT" and _aligned(bias):
            score += 8
            confirmations.append(note)
        else:
            confirmations.append(note)
    elif premium.get("available"):
        note = f"[Synthetic Futures] {premium['reason']}"
        if move_direction != "FLAT" and _opposed(premium.get("bias", "NEUTRAL")):
            score -= 15
            warnings.append(note)
        elif move_direction != "FLAT" and _aligned(premium.get("bias", "NEUTRAL")):
            score += 8
            confirmations.append(note)
        else:
            confirmations.append(note)

    # 2. OI buildup — fresh conviction (Buildup) vs stale covering/unwinding.
    label = buildup.get("label", "Mixed / Flat")
    b_bias = buildup.get("bias", "NEUTRAL")
    if move_direction != "FLAT":
        if label in ("Long Buildup", "Short Buildup") and _aligned(b_bias):
            score += 10
            confirmations.append(f"[OI Buildup] {buildup['reason']}")
        elif label in ("Short Covering", "Long Unwinding") and _aligned(b_bias):
            score -= 10
            warnings.append(f"[OI Buildup] {buildup['reason']}")
        elif _opposed(b_bias):
            score -= 12
            warnings.append(f"[OI Buildup] {buildup['reason']}")
        else:
            confirmations.append(f"[OI Buildup] {buildup['reason']}")

    # 3. IV skew — elevated put IV during a rally / elevated call IV during a selloff.
    if skew.get("available"):
        note = f"[IV Skew] {skew['reason']}"
        if move_direction != "FLAT" and _opposed(skew.get("bias", "NEUTRAL")):
            score -= 6
            warnings.append(note)
        elif move_direction != "FLAT" and _aligned(skew.get("bias", "NEUTRAL")):
            score += 4
            confirmations.append(note)
        else:
            confirmations.append(note)

    # 3b. PCR (OI) + fresh OI tilt + Max Pain pull — this app's existing, already-tested
    # option-chain signal classifier (option_chain_engine.classify_option_chain_signal),
    # reused here as an independent cross-check rather than re-deriving the same logic.
    if chain_signal:
        cs_bias = chain_signal.get("bias", "NEUTRAL")
        pcr_note = f"PCR(OI) {chain_signal['pcr_oi']:.2f}" if chain_signal.get("pcr_oi") is not None else ""
        pain_note = f", Max Pain {chain_signal['max_pain']:,.0f}" if chain_signal.get("max_pain") else ""
        note = (
            f"[PCR / Max Pain] Options-chain read is {cs_bias} ({chain_signal.get('confidence_pct', 0):.0f}% "
            f"confidence) — {pcr_note}{pain_note}."
        )
        if move_direction != "FLAT" and _opposed(cs_bias):
            score -= 8
            warnings.append(note + " This chain-level read is fighting today's price move.")
        elif move_direction != "FLAT" and _aligned(cs_bias):
            score += 6
            confirmations.append(note)
        else:
            confirmations.append(note)

    # 4. VIX — rising fear alongside a rally (or falling fear alongside a selloff) is a mismatch.
    if vix.get("available") and vix.get("change_pct") is not None:
        chg = vix["change_pct"]
        note = f"[India VIX] {vix['level']:.2f} ({chg:+.2f}% today)."
        if move_direction == "UP" and chg >= cfg.vix_rise_threshold_pct:
            score -= 5
            warnings.append(note + " VIX rising alongside a rally is a mismatch — the options market isn't relaxing despite the up-move.")
        elif move_direction == "DOWN" and chg <= -cfg.vix_rise_threshold_pct:
            score -= 3
            warnings.append(note + " VIX falling alongside a selloff is a mild mismatch.")
        else:
            confirmations.append(note)

    # 5. Late-session jump anomaly.
    if late_jump.get("available") and late_jump.get("unusual") and move_direction != "FLAT":
        score -= 8
        warnings.append(f"[Late-Session Move] {late_jump['reason']}")
    elif late_jump.get("available"):
        confirmations.append(f"[Late-Session Move] {late_jump['reason']}")

    # 6. Cash-segment FII/DII flow (real data — proxy for index-derivative positioning
    # when the user hasn't supplied that directly).
    fd_score = float(fii_dii.get("score") or 0.0)
    if move_direction == "UP" and fd_score < -5:
        score -= 6
        warnings.append("[FII/DII Flow] " + "; ".join(fii_dii.get("reasons") or ["Net institutional cash selling despite the rally."]))
    elif move_direction == "DOWN" and fd_score > 5:
        score -= 4
        warnings.append("[FII/DII Flow] " + "; ".join(fii_dii.get("reasons") or ["Net institutional cash buying despite the selloff."]))
    elif fii_dii.get("reasons"):
        confirmations.append("[FII/DII Flow] " + "; ".join(fii_dii["reasons"]))

    # 7. Optional manual FII index-derivative-positioning input.
    if fii_index_position_cut is not None:
        if fii_index_position_cut and move_direction == "UP":
            score -= 6
            warnings.append("[FII Index Positions] Reported as being cut today despite the rally — large players stepping back from the move.")
        elif fii_index_position_cut and move_direction == "DOWN":
            score -= 3
            warnings.append("[FII Index Positions] Reported as being cut today alongside the selloff.")
        elif not fii_index_position_cut:
            confirmations.append("[FII Index Positions] Not reported as being cut today.")

    score = round(score, 1)

    if move_direction == "FLAT":
        market_view = "NEUTRAL — No Directional Conviction Either Way"
        risk_stance = "LOW"
        guidance = (
            "Price is essentially flat today, so there's no rally or decline to stress-test against the "
            "derivatives data. Wait for a clearer directional move before applying this read."
        )
    elif score <= cfg.divergence_score_threshold:
        opposite = "Bearish Reversal" if move_direction == "UP" else "Bullish Reversal"
        move_word = "Rally" if move_direction == "UP" else "Decline"
        market_view = f"{opposite.upper()} RISK — Hollow {move_word}"
        risk_stance = "HIGH"
        guidance = (
            f"Today's {move_word.lower()} looks fragile: the options-market data (futures premium/discount, OI "
            f"buildup, IV skew{', VIX' if vix.get('available') else ''}) mostly contradicts or fails to confirm the "
            f"price move rather than supporting it. This has the signature of a move driven by short-covering/"
            f"unwinding or last-minute repositioning rather than fresh conviction. "
            f"{'Avoid chasing fresh longs' if move_direction == 'UP' else 'Avoid chasing fresh shorts'} into this "
            f"move, keep tight stops on existing positions in the move's direction, and watch for a sharp reversal "
            f"once whatever is driving the move (covering, expiry positioning, event pricing) runs its course."
        )
    elif score < cfg.caution_score_threshold:
        market_view = "CAUTIOUS — Mixed Conviction"
        risk_stance = "MODERATE"
        guidance = (
            "The derivatives data is mixed — some signals support today's move, others don't. Not a clean "
            "divergence, but not a fully convicted move either. Size new positions conservatively and lean on "
            "the specific warnings below rather than the headline price action alone."
        )
    else:
        market_view = f"HEALTHY {move_direction} — Move Well-Supported"
        risk_stance = "LOW"
        guidance = (
            f"Today's {'rally' if move_direction == 'UP' else 'decline'} is backed by the derivatives data — "
            f"futures premium/discount, OI buildup, and IV skew broadly line up with the price direction rather "
            f"than fighting it. This looks like a genuine, participation-backed move rather than a hollow one."
        )

    # A genuinely jargon-free version — no "PCR", "IV skew", "OI buildup" — for anyone who
    # doesn't trade options. The detailed reason strings above stay available for those who do.
    n_warn, n_confirm = len(warnings), len(confirmations)
    move_word = {"UP": "went up", "DOWN": "went down", "FLAT": "stayed flat"}[move_direction]
    chg_txt = f" by {abs(price_chg_pct):.1f}%" if price_chg_pct is not None else ""
    if move_direction == "FLAT":
        plain_english = (
            f"{symbol} {move_word} today{chg_txt} — not enough of a move to say whether it's genuine or not. "
            "Nothing actionable here; check back once price actually breaks one way or the other."
        )
    elif score <= cfg.divergence_score_threshold:
        plain_english = (
            f"{symbol} {move_word} today{chg_txt}, but the options market doesn't seem to believe it. Out of "
            f"{n_warn + n_confirm} independent checks on how options traders are actually positioned, "
            f"{n_warn} disagree with this move and only {n_confirm} support it. In plain terms: this looks like "
            f"a move that could run out of steam and reverse, not one driven by real conviction. "
            f"{'Be cautious chasing this rally' if move_direction == 'UP' else 'Be cautious chasing this decline'} — "
            "it has the hallmarks of short-term positioning unwinding rather than a genuine trend."
        )
    elif score < cfg.caution_score_threshold:
        plain_english = (
            f"{symbol} {move_word} today{chg_txt}. The options market is split — {n_confirm} checks support "
            f"the move, {n_warn} don't. It's not a clear red flag, but it's not a strong green light either. "
            "Worth treating any new position here conservatively rather than betting big on the move continuing."
        )
    else:
        plain_english = (
            f"{symbol} {move_word} today{chg_txt}, and the options market broadly agrees — {n_confirm} out of "
            f"{n_warn + n_confirm} independent checks support this move, with little pushing against it. In "
            "plain terms: this looks like a real, participation-backed move rather than something likely to "
            "snap back quickly."
        )

    return {
        "symbol": symbol,
        "spot": round(spot, 2) if spot else None,
        "price_chg_pct": round(price_chg_pct, 2) if price_chg_pct is not None else None,
        "move_direction": move_direction,
        "composite_score": score,
        "market_view": market_view,
        "risk_stance": risk_stance,
        "trading_guidance": guidance,
        "plain_english": plain_english,
        "warnings": warnings,
        "confirmations": confirmations,
        "buildup": buildup,
        "premium": premium,
        "skew": skew,
        "fii_dii": fii_dii,
        "vix": vix,
        "late_session_jump": late_jump,
        "chain_signal": chain_signal,
        "manual_futures_basis": manual_basis,
        "fii_index_position_cut": fii_index_position_cut,
    }


def _approx_next_trading_date(as_of: str) -> str:
    """Next calendar trading day after `as_of` (YYYY-MM-DD), skipping
    weekends only — this app has no NSE trading-holiday calendar, so this is
    an approximation, always labeled as such in the response rather than
    presented as exact."""
    try:
        d = datetime.strptime(as_of, "%Y-%m-%d").date()
    except Exception:
        return as_of
    nd = d + timedelta(days=1)
    while nd.weekday() >= 5:  # Sat=5, Sun=6
        nd += timedelta(days=1)
    return str(nd)


def _build_outlook(symbol: str, *, groww_token: str, exchange: str) -> dict[str, Any]:
    """Forward-looking trend/strength/reversal read for the days-to-weeks
    ahead — layered on top of the same-day divergence read above, which only
    judges whether TODAY's move is trustworthy, not where price goes next.
    Reuses mtf_trend_strength_engine (ADX + Kaufman Efficiency Ratio trend
    strength, multi-factor reversal probability), already proven elsewhere in
    this app, on the daily (near-term, next few sessions) and weekly
    (medium-term, coming weeks) timeframes rather than re-deriving trend
    logic here."""
    try:
        from app.market_pulse.mtf_trend_strength_engine import analyze_ticker as _mtf_analyze_ticker

        mtf = _mtf_analyze_ticker(symbol, ["1d", "1w"], "india", groww_token=groww_token, exchange=exchange)
    except Exception as exc:
        logger.debug("Outlook MTF fetch failed for %s: %s", symbol, exc)
        return {"available": False}

    tfs = mtf.get("timeframes") or {}

    def _leg(r: dict | None, horizon: str) -> dict[str, Any] | None:
        if not r:
            return None
        plain = r.get("plain_english")
        return {
            "horizon": horizon,
            "direction": r.get("direction", "NEUTRAL"),
            "bias": r.get("bias", "Neutral"),
            "strength_score": r.get("strength_score"),
            "strength_label": r.get("strength_label"),
            "reversal_probability_pct": r.get("reversal_probability_pct"),
            "reversal_reasons": r.get("reversal_reasons", []),
            # mtf_trend_strength_engine's TIMEFRAMES labels carry column-alignment
            # padding (e.g. "Daily     (Position)") meant for a dropdown, not prose.
            "plain_english": re.sub(r" {2,}", " ", plain) if plain else plain,
        }

    near = _leg(tfs.get("1d"), "Next few trading sessions (days)")
    medium = _leg(tfs.get("1w"), "Coming weeks")

    parts = []
    if near:
        parts.append(f"Over the next few sessions: {near['plain_english']}")
    if medium:
        parts.append(f"Zooming out to the coming weeks: {medium['plain_english']}")
    summary = " ".join(parts) if parts else "Not enough daily/weekly history to project a forward trend for this symbol yet."

    return {"available": bool(near or medium), "near_term": near, "medium_term": medium, "summary": summary}


def _build_trade_suggestion(
    result: dict[str, Any], df_daily: pd.DataFrame, outlook: dict[str, Any], cfg: MarketPredictionConfig,
    *, is_index: bool = True, further_analysis: list[str] | None = None,
    groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    """Turns the divergence read + forward outlook above into an actual
    risk-managed trade idea — action, %confidence, %SL/%TP, entry/stop/
    target, an A/B/C grade and a plain advice line — using the same
    ConfidenceScore + ATR-derived-stop + reward:risk-floor + momentum-
    exhaustion + liquidity machinery the rest of Pro Trade uses, so this
    isn't just a jargon read with no actionable levels attached."""
    symbol = result["symbol"]
    move_direction = result["move_direction"]
    score = result["composite_score"]
    view = result["market_view"]
    entry = result.get("spot")

    trade: dict[str, Any] = {
        "action": "WAIT", "direction": "NONE", "entry_price": round(entry, 2) if entry else None,
        "confidence_pct": None, "sl_pct": None, "tp_pct": None,
        "stop_price": None, "target_price": None, "rr": None, "grade": None,
        "reasons": [], "advice": "",
    }

    if not entry or move_direction == "FLAT":
        trade["advice"] = (
            "Price is essentially flat, so there's no directional move to build a trade around yet. "
            "Wait for price to break one way or the other before considering a position."
        )
        return trade

    if score < cfg.caution_score_threshold:
        hollow = score <= cfg.divergence_score_threshold
        trade["advice"] = (
            f"The {'rally' if move_direction == 'UP' else 'decline'} itself looks "
            f"{'hollow and at real reversal risk' if hollow else 'mixed / not clearly confirmed'} per the "
            "derivatives read above — not clean enough to size a fresh position either with or against the "
            "move right now. Wait for the divergence to resolve (price catches down/up to what the options "
            "data is saying) or for the data to flip to genuine confirmation before entering."
        )
        return trade

    action = "BUY" if move_direction == "UP" else "SELL"
    direction = "LONG" if action == "BUY" else "SHORT"

    atr_series = _atr_ind(df_daily, 14)
    atr_val = float(atr_series.iloc[-1]) if len(atr_series) and pd.notna(atr_series.iloc[-1]) else entry * 0.01
    is_long = direction == "LONG"
    stop = entry - 1.5 * atr_val if is_long else entry + 1.5 * atr_val
    target = entry + 3.0 * atr_val if is_long else entry - 3.0 * atr_val

    sl_pct, tp_pct = sl_tp_pct(direction, entry, stop, target)
    rr = rr_ratio(sl_pct, tp_pct)

    conf = ConfidenceScore(45, f"Composite market-prediction score {score:+.1f} ({view})")
    conf.add(
        abs(score) >= 25, 15,
        "Strong composite conviction — the derivatives data lines up clearly with today's move",
        "Composite conviction is only moderate, not overwhelming",
    )

    near = (outlook or {}).get("near_term") if outlook else None
    if near:
        near_dir = near.get("direction")
        aligned = (near_dir == "LONG" and is_long) or (near_dir == "SHORT" and not is_long)
        conf.add(
            aligned, 12,
            f"Daily trend-strength read agrees ({near.get('strength_label', '')} {near_dir or 'trend'})",
            "The daily trend-strength read doesn't clearly agree with this trade's direction",
        )
        reversal_pct = near.get("reversal_probability_pct")
        if reversal_pct is not None:
            conf.add(
                reversal_pct < 40, 8,
                f"Low reversal risk on the daily trend ({reversal_pct:.0f}%)",
                f"Elevated reversal risk on the daily trend ({reversal_pct:.0f}%) — this move may be running out of room",
            )

    conf.add(
        rr is not None and rr >= 1.5, 10,
        f"Reward:risk of {rr:.1f}:1 clears the 1.5:1 floor" if rr else "Reward:risk floor cleared",
        "Reward:risk is thin for this setup",
    )

    rsi_val = None
    try:
        rsi_series = _rsi_ind(df_daily["close"], 14).dropna()
        if not rsi_series.empty:
            rsi_val = float(rsi_series.iloc[-1])
    except Exception:
        pass
    exhaustion_pts, exhaustion_note = momentum_exhaustion_note(rsi_val, direction)
    if exhaustion_note:
        conf.score += exhaustion_pts
        conf.reasons.append(exhaustion_note)

    confidence_pct, reasons = conf.finalize()

    fa_reasons: list[str] = []
    if not is_index and further_analysis:
        fa_reasons, fa_delta = _apply_further_analysis(
            symbol, direction, further_analysis, groww_token=groww_token, exchange=exchange,
        )
        if fa_reasons:
            confidence_pct = round(min(95.0, max(10.0, confidence_pct + fa_delta)), 1)
            reasons = reasons + fa_reasons

    liquidity = True
    try:
        vz = volume_zscore(df_daily["volume"], 20).dropna()
        liquidity = liquidity_ok(float(vz.iloc[-1]) if not vz.empty else None)
    except Exception:
        pass
    grade = quality_grade(confidence_pct, rr, liquidity, False)

    advice = (
        f"{action} {symbol} near {entry:,.2f} — stop {stop:,.2f} ({sl_pct:.1f}%), target {target:,.2f} "
        f"({tp_pct:.1f}%), reward:risk ~{rr:.1f}:1, grade {grade} at {confidence_pct:.0f}% confidence. "
        "Size the position for the stop distance, not a fixed amount, and treat this as one read among "
        "several to confirm — not a standalone signal to act on blindly."
    )
    if not liquidity:
        advice += " Note: recent volume is unusually thin — expect wider slippage on entry/exit."

    trade.update({
        "action": action, "direction": direction,
        "confidence_pct": confidence_pct, "sl_pct": sl_pct, "tp_pct": tp_pct,
        "stop_price": round(stop, 4), "target_price": round(target, 4), "rr": rr, "grade": grade,
        "reasons": reasons, "advice": advice,
    })
    return trade


def analyze_market_prediction(
    symbol: str,
    *,
    is_index: bool = True,
    groww_token: str = "",
    exchange: str = "NSE",
    cfg: MarketPredictionConfig | None = None,
    futures_price: float | None = None,
    fii_index_position_cut: bool | None = None,
    further_analysis: list[str] | None = None,
) -> dict[str, Any]:
    """Full Market Prediction read for one India index/ticker."""
    from app.market_pulse.option_chain_engine import classify_option_chain_signal, fetch_option_chain
    from app.market_pulse.option_short_long_engine import (
        _daily_price_change_pct,
        _fetch_ohlcv,
        _with_retry,
        classify_oi_buildup,
        fetch_fii_dii_sentiment,
        iv_skew_read,
        synthetic_futures_premium,
    )

    cfg = cfg or MarketPredictionConfig()
    symbol = (symbol or "").strip().upper()
    if not symbol:
        return {"symbol": symbol, "error": "No symbol provided."}

    chain = _with_retry(lambda: fetch_option_chain(symbol, is_index, groww_token))
    if not chain or not chain.get("strikes"):
        return {"symbol": symbol, "error": "Could not fetch option chain / price data."}

    df_daily = _fetch_ohlcv(symbol, "india", "1d", groww_token=groww_token, exchange=exchange, limit=300)
    if df_daily is None or df_daily.empty:
        return {"symbol": symbol, "error": "Could not fetch daily price history."}

    spot = chain.get("underlying") or float(df_daily["close"].iloc[-1])
    price_chg_pct = _daily_price_change_pct(df_daily)

    buildup = classify_oi_buildup(chain, price_chg_pct)
    premium = synthetic_futures_premium(chain, spot)
    skew = iv_skew_read(chain, spot)
    fii_dii = fetch_fii_dii_sentiment()
    vix = _vix_read()

    chain_signal_raw = classify_option_chain_signal(chain)
    chain_signal = {
        **chain_signal_raw,
        "pcr_oi": chain.get("pcr_oi"),
        "max_pain": chain.get("max_pain"),
    }

    df_intraday = _fetch_ohlcv(symbol, "india", "1m", groww_token=groww_token, exchange=exchange, limit=375)
    late_jump = _late_session_jump_read(df_intraday, cfg)

    manual_basis = None
    if futures_price and spot:
        manual_basis = {
            "futures_price": round(float(futures_price), 2), "spot": round(spot, 2),
            "basis_pct": round((float(futures_price) - spot) / spot * 100, 3),
        }

    result = _synthesize_view(
        symbol=symbol, spot=spot, price_chg_pct=price_chg_pct,
        buildup=buildup, premium=premium, skew=skew, fii_dii=fii_dii, vix=vix,
        late_jump=late_jump, chain_signal=chain_signal, manual_basis=manual_basis,
        fii_index_position_cut=fii_index_position_cut, cfg=cfg,
    )

    # Which trading session this move is FOR (the last completed daily bar,
    # i.e. the data this whole read is built from) vs when this specific read
    # was generated (can differ if run after-hours/next morning) vs which
    # session the forward-looking outlook/trade idea below actually applies
    # to (the NEXT trading session onward) — all three shown explicitly so
    # it's never ambiguous which date the analysis is "as of" vs "for".
    last_bar = df_daily.index[-1]
    as_of_date = str(last_bar.date()) if hasattr(last_bar, "date") else str(last_bar)
    result["as_of_date"] = as_of_date
    result["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result["option_chain_expiry"] = chain.get("current_expiry")
    result["prediction_for_date"] = _approx_next_trading_date(as_of_date)

    outlook = _build_outlook(symbol, groww_token=groww_token, exchange=exchange)
    result["outlook"] = outlook
    result["trade_suggestion"] = _build_trade_suggestion(
        result, df_daily, outlook, cfg,
        is_index=is_index, further_analysis=further_analysis,
        groww_token=groww_token, exchange=exchange,
    )
    return result
