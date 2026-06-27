"""
crypto_session.py
-----------------
CoinDCX / crypto calendar — session day starts at 00:00 America/New_York (ET).
Used for daily bars, day lookbacks, session open, and user-facing copy.
"""

from __future__ import annotations

CRYPTO_SESSION_TZ = "America/New_York"
CRYPTO_SESSION_DAY_START = "00:00 New York (ET)"
CRYPTO_SESSION_LABEL = "NY session (00:00 ET day start)"
CRYPTO_SESSION_SHORT = "🗽 00:00 NY (ET) session day"

CRYPTO_SESSION_DAY_MD = f"Session day starts at **{CRYPTO_SESSION_DAY_START}**"

CRYPTO_SESSION_CAPTION = (
    f"{CRYPTO_SESSION_DAY_MD} — daily candles, day lookbacks, and session-vs-open "
    "logic use the New York calendar day (not UTC or IST)."
)

CRYPTO_SESSION_CAPTION_SHORT = (
    f"🗽 {CRYPTO_SESSION_DAY_MD} · markets trade 24/7; the session day resets at NY midnight."
)

CRYPTO_FEED_BANNER = (
    "ℹ️ **Active Feed:** CoinDCX Futures — USDT perpetuals. "
    f"{CRYPTO_SESSION_DAY_MD}."
)

CRYPTO_MOVERS_CAPTION_SUFFIX = (
    f"{CRYPTO_SESSION_DAY_MD} for session range · "
    "**Change %** from CoinDCX exchange 24h ticker."
)


def render_crypto_session_caption(*, short: bool = False) -> None:
    """Standard session-day note for CoinDCX sections."""
    st.caption(CRYPTO_SESSION_CAPTION_SHORT if short else CRYPTO_SESSION_CAPTION)


def crypto_session_market_suffix() -> str:
    """Inline suffix for captions (e.g. MTF crypto tab)."""
    return f" · {CRYPTO_SESSION_SHORT}"
