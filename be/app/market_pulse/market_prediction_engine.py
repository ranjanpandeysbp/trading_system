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
from dataclasses import dataclass
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

INDEX_CHOICES: list[dict[str, str]] = [
    {"value": "NIFTY", "label": "Nifty 50"},
    {"value": "BANKNIFTY", "label": "Bank Nifty"},
    {"value": "FINNIFTY", "label": "Nifty Financial Services"},
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

    return {
        "symbol": symbol,
        "spot": round(spot, 2) if spot else None,
        "price_chg_pct": round(price_chg_pct, 2) if price_chg_pct is not None else None,
        "move_direction": move_direction,
        "composite_score": score,
        "market_view": market_view,
        "risk_stance": risk_stance,
        "trading_guidance": guidance,
        "warnings": warnings,
        "confirmations": confirmations,
        "buildup": buildup,
        "premium": premium,
        "skew": skew,
        "fii_dii": fii_dii,
        "vix": vix,
        "late_session_jump": late_jump,
        "manual_futures_basis": manual_basis,
        "fii_index_position_cut": fii_index_position_cut,
    }


def analyze_market_prediction(
    symbol: str,
    *,
    is_index: bool = True,
    groww_token: str = "",
    exchange: str = "NSE",
    cfg: MarketPredictionConfig | None = None,
    futures_price: float | None = None,
    fii_index_position_cut: bool | None = None,
) -> dict[str, Any]:
    """Full Market Prediction read for one India index/ticker."""
    from app.market_pulse.option_chain_engine import fetch_option_chain
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

    df_intraday = _fetch_ohlcv(symbol, "india", "1m", groww_token=groww_token, exchange=exchange, limit=375)
    late_jump = _late_session_jump_read(df_intraday, cfg)

    manual_basis = None
    if futures_price and spot:
        manual_basis = {
            "futures_price": round(float(futures_price), 2), "spot": round(spot, 2),
            "basis_pct": round((float(futures_price) - spot) / spot * 100, 3),
        }

    return _synthesize_view(
        symbol=symbol, spot=spot, price_chg_pct=price_chg_pct,
        buildup=buildup, premium=premium, skew=skew, fii_dii=fii_dii, vix=vix,
        late_jump=late_jump, manual_basis=manual_basis,
        fii_index_position_cut=fii_index_position_cut, cfg=cfg,
    )
