"""
option_chain_engine.py
------------------------
Full NSE option chain (indices + individual stocks) with PCR, max pain, OI-based
support/resistance, and a bullish/bearish/neutral trade-signal classifier with
plain-English reasoning.

Reuses the already-proven NSE v3 / Groww fetch-and-parse plumbing from
news_scanner.py (session warming, payload normalization, max-pain calc) —
generalized here to also cover individual-stock ("Equity") option chains,
which news_scanner.py's fetch_nse_option_chain only does for indices.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from app.market_pulse.news_scanner import (
    _fetch_groww_option_chain,
    _parse_option_chain_payload,
    _warm_nse_session,
    fetch_nse_option_chain as fetch_index_option_chain,
)

logger = logging.getLogger(__name__)

# Common index option chains (NSE) — verified live against NSE's own
# underlying-information API, matches what NSE actually lists F&O for today.
INDEX_CHOICES: list[str] = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"]


def _fetch_nse_equity_option_chain_v3(symbol: str) -> dict[str, Any] | None:
    """Fetch a single stock's option chain via NSE option-chain-v3 (type=Equity)."""
    try:
        session = requests.Session()
        _warm_nse_session(session, "/option-chain")

        info_url = (
            "https://www.nseindia.com/api/option-chain-contract-info"
            f"?symbol={symbol}&instrument=Stocks"
        )
        info_resp = session.get(info_url, timeout=15)
        if info_resp.status_code != 200:
            logger.warning("NSE equity contract-info status %s for %s", info_resp.status_code, symbol)
            return None

        info = info_resp.json()
        expiry_dates = info.get("expiryDates") or []
        if not expiry_dates:
            return None

        nearest_expiry = expiry_dates[0]
        time.sleep(0.2)
        oc_url = (
            "https://www.nseindia.com/api/option-chain-v3"
            f"?type=Equity&symbol={symbol}&expiry={nearest_expiry}"
        )
        resp = session.get(oc_url, timeout=20)
        if resp.status_code != 200 or len(resp.text) < 50:
            logger.warning("NSE equity option-chain-v3 status %s for %s", resp.status_code, symbol)
            return None

        parsed = _parse_option_chain_payload(resp.json(), source="NSE")
        if parsed and not parsed.get("current_expiry"):
            parsed["current_expiry"] = nearest_expiry
        return parsed
    except Exception as exc:
        logger.error("NSE equity option-chain error for %s: %s", symbol, exc)
        return None


def fetch_option_chain(symbol: str, is_index: bool, groww_token: str = "") -> dict[str, Any] | None:
    """Full option-chain snapshot for an index or individual stock.

    Returns the same normalized shape as news_scanner.fetch_nse_option_chain:
    underlying, expiry_dates, current_expiry, total_call_oi/put_oi, pcr_oi, pcr_vol,
    max_pain, strikes, top_call_oi/top_put_oi/top_call_chg_oi/top_put_chg_oi, source.

    When data provider is IndMoney, try IndMoney OC first (API may still be
    rolling out), then fall back to NSE / Groww.
    """
    symbol = (symbol or "").strip().upper()
    if not symbol:
        return None

    try:
        from app.data.provider_ctx import get_active_data_provider, get_active_indmoney_token

        if get_active_data_provider() == "indmoney":
            im = get_active_indmoney_token()
            if im:
                from app.data.indmoney_client import fetch_indmoney_option_chain

                im_chain = fetch_indmoney_option_chain(symbol, im)
                if im_chain and (im_chain.get("strikes") or im_chain.get("strikes_raw")):
                    return im_chain
    except Exception as exc:
        logger.debug("IndMoney option-chain skip: %s", exc)

    if is_index:
        return fetch_index_option_chain(symbol, groww_token)

    data = _fetch_nse_equity_option_chain_v3(symbol)
    if data:
        return data
    groww_data = _fetch_groww_option_chain(symbol, groww_token, exchange="NSE")
    if groww_data:
        return groww_data
    try:
        session = requests.Session()
        _warm_nse_session(session, "/option-chain")
        legacy_url = f"https://www.nseindia.com/api/option-chain-equities?symbol={symbol}"
        resp = session.get(legacy_url, timeout=15)
        if resp.status_code == 200 and len(resp.text) > 50:
            return _parse_option_chain_payload(resp.json(), source="NSE-legacy")
    except Exception as exc:
        logger.error("Legacy NSE equity option chain error for %s: %s", symbol, exc)
    return None


def _support_resistance(chain: dict[str, Any]) -> tuple[float | None, float | None]:
    """Nearest strong support (highest Put OI strike) and resistance (highest Call OI strike)."""
    top_put = chain.get("top_put_oi") or []
    top_call = chain.get("top_call_oi") or []
    support = top_put[0]["strike"] if top_put else None
    resistance = top_call[0]["strike"] if top_call else None
    return support, resistance


def classify_option_chain_signal(chain: dict[str, Any]) -> dict[str, Any]:
    """Bullish/Bearish/Neutral bias + Buy/Sell/Wait trade signal with plain-English reasons.

    Heuristics (each contributes a signed score, summed then bucketed):
    1. PCR (OI) — high PCR (more puts written) skews bullish, low PCR skews bearish.
    2. Fresh OI buildup tilt — which side (calls vs puts) added more OI today.
    3. Support/resistance proximity — closer to support = more upside room (bullish tilt),
       closer to resistance = capped upside (bearish tilt).
    4. Max pain pull — price tends to drift toward max pain into expiry.
    """
    reasons: list[str] = []
    score = 0.0

    underlying = chain.get("underlying")
    pcr_oi = chain.get("pcr_oi") or 0
    max_pain = chain.get("max_pain")
    strikes = chain.get("strikes") or []

    # 1. PCR read — who's "short" in size, and are they comfortable or squeeze-prone?
    if pcr_oi >= 1.3:
        score += 2
        reasons.append(
            f"PCR (OI) is {pcr_oi:.2f} — put open interest exceeds call OI by "
            f"{(pcr_oi - 1) * 100:.0f}%, a classic bullish tilt: far more traders are short puts "
            "(sold puts, betting price holds up) than short calls. As long as price stays above "
            "their strikes, those put-writers just sit in profit while time decay eats the premium "
            "in their favor — no reason to cover, so they're unlikely to unwind soon. But a sharp "
            "drop toward their strikes would force them to buy back / hedge fast, which can add fuel "
            "to a decline."
        )
    elif pcr_oi >= 1.05:
        score += 1
        reasons.append(
            f"PCR (OI) is {pcr_oi:.2f} — mildly more puts than calls short, a soft bullish lean; "
            "not crowded enough on either side to call it a squeeze setup."
        )
    elif pcr_oi <= 0.7:
        score -= 2
        reasons.append(
            f"PCR (OI) is {pcr_oi:.2f} — call open interest dominates puts, a classic bearish tilt: "
            "far more traders are short calls (sold calls, betting price stays capped) than short "
            "puts. As long as price stays below their strikes, those call-writers sit comfortably in "
            "profit with time decay working for them, so they're likely to just hold to expiry rather "
            "than cover. But if price breaks above their strike, they're forced to buy back in a hurry "
            "— that rush of short-covering is exactly what fuels a sharp squeeze rally."
        )
    elif pcr_oi <= 0.95:
        score -= 1
        reasons.append(
            f"PCR (OI) is {pcr_oi:.2f} — mildly more calls than puts short, a soft bearish lean; "
            "not crowded enough on either side to call it a squeeze setup."
        )
    else:
        reasons.append(
            f"PCR (OI) is {pcr_oi:.2f} — close to 1, calls and puts are roughly balanced, so neither "
            "side is crowded or at obvious risk of a squeeze right now."
        )

    # 2. Fresh OI buildup tilt (today's change in OI, summed across all strikes)
    total_call_chg = sum((s.get("ce_chg_oi") or 0) for s in strikes)
    total_put_chg = sum((s.get("pe_chg_oi") or 0) for s in strikes)
    if total_call_chg or total_put_chg:
        net = total_put_chg - total_call_chg
        denom = max(abs(total_call_chg), abs(total_put_chg), 1)
        tilt_pct = net / denom * 100
        if tilt_pct >= 25:
            score += 1.5
            reasons.append(
                "Today's fresh Put OI addition outpaces Call OI addition — new support is being "
                "built beneath the market, bullish for the near term. Since this is fresh writing "
                "(not yet sitting on a big profit cushion), these put-sellers aren't near a "
                "profit-booking exit yet — this floor has room to hold for a bit."
            )
        elif tilt_pct <= -25:
            score -= 1.5
            reasons.append(
                "Today's fresh Call OI addition outpaces Put OI addition — new resistance is being "
                "built overhead, bearish for the near term. Since this is fresh writing (not yet "
                "sitting on a big profit cushion), these call-sellers aren't near a profit-booking "
                "exit yet — this cap has room to hold for a bit."
            )
        else:
            reasons.append("Today's fresh Call vs Put OI addition is roughly balanced — no clear buildup bias.")

    # 3. Support / resistance proximity
    support, resistance = _support_resistance(chain)
    if underlying and support and resistance and resistance > support:
        pos = (underlying - support) / (resistance - support)
        if pos <= 0.4:
            score += 1
            reasons.append(
                f"Spot ({underlying:,.1f}) is trading closer to the strongest support at "
                f"{support:,.0f} (highest Put OI) than the strongest resistance at "
                f"{resistance:,.0f} (highest Call OI) — more room to the upside before hitting a wall. "
                f"If price does reach {resistance:,.0f}, the heavy Call OI sitting there would have to "
                "unwind (buy back), often accelerating the move — a short-squeeze setup, not a "
                "guaranteed ceiling."
            )
        elif pos >= 0.6:
            score -= 1
            reasons.append(
                f"Spot ({underlying:,.1f}) is trading closer to the strongest resistance at "
                f"{resistance:,.0f} (highest Call OI) than the strongest support at "
                f"{support:,.0f} (highest Put OI) — limited room before hitting a wall overhead. "
                f"If price breaks below {support:,.0f} instead, the heavy Put OI there would have to "
                "unwind (buy back), often accelerating the drop — same squeeze dynamic, just on the "
                "downside."
            )
        else:
            reasons.append(
                f"Spot ({underlying:,.1f}) sits roughly midway between support {support:,.0f} "
                f"and resistance {resistance:,.0f} — no strong pull either way from OI walls."
            )

    # 4. Max pain pull
    if underlying and max_pain:
        gap_pct = (underlying - max_pain) / max_pain * 100
        if gap_pct > 0.5:
            score -= 1
            reasons.append(
                f"Max Pain is at {max_pain:,.0f}, below spot ({underlying:,.1f}) by {gap_pct:.1f}% — "
                "option-writers (who net collect premium) profit most if price settles there, so there's "
                "a soft pull downward into expiry. This is a mild statistical tendency, not a rule — it "
                "only really tightens its grip in the last day or two before expiry as writers hedge."
            )
        elif gap_pct < -0.5:
            score += 1
            reasons.append(
                f"Max Pain is at {max_pain:,.0f}, above spot ({underlying:,.1f}) by {abs(gap_pct):.1f}% — "
                "option-writers (who net collect premium) profit most if price settles there, so there's "
                "a soft pull upward into expiry. This is a mild statistical tendency, not a rule — it "
                "only really tightens its grip in the last day or two before expiry as writers hedge."
            )
        else:
            reasons.append(f"Spot is already trading close to Max Pain ({max_pain:,.0f}) — no strong pull either way.")

    if score >= 2.5:
        bias = "BULLISH"
    elif score <= -2.5:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    confidence_pct = round(min(95.0, 50.0 + abs(score) * 7.0), 1)

    if bias == "BULLISH" and confidence_pct >= 62:
        trade_signal = "BUY"
    elif bias == "BEARISH" and confidence_pct >= 62:
        trade_signal = "SELL"
    else:
        trade_signal = "WAIT"

    return {
        "bias": bias,
        "trade_signal": trade_signal,
        "confidence_pct": confidence_pct,
        "score": round(score, 2),
        "support": support,
        "resistance": resistance,
        "reasons": reasons,
    }
