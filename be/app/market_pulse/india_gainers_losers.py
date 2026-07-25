"""India-only gainers/losers (no US/crypto)."""

from __future__ import annotations

from typing import Any

from app.market_pulse.news_scanner import _fetch_nse_index_constituent_symbols, fetch_nse_index_stock_movers
from app.market_pulse.stock_price_rotation import compute_stock_price_rotation

# No ticker count limit — return the full ranked gainer/loser lists.
TOP_N: int | None = None


def compute_india_movers(
    index_name: str,
    tf_key: str,
    lookback_bars: int,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    if tf_key == "1d" and lookback_bars == 1:
        live = fetch_nse_index_stock_movers(index_name, top_n=TOP_N)
        if live:
            return {
                "gainers": live.get("gainers", []),
                "losers": live.get("losers", []),
                "source": "NSE live",
            }

    symbols = _fetch_nse_index_constituent_symbols(index_name)
    if not symbols:
        return {"error": f"No constituents for {index_name}"}

    from app.market_pulse.groww_auth import set_groww_token

    set_groww_token(groww_token)
    payload = compute_stock_price_rotation(
        index_name,
        tuple(symbols),
        tf_key,
        lookback_bars,
        use_groww=bool(groww_token),
        exchange=exchange,
    )
    if not payload:
        return {"error": f"No price data for {index_name} @ {tf_key}"}

    gainers = [
        {"symbol": r["symbol"], "pct": r["pct"], "last": r.get("last", 0)}
        for r in (payload.get("inflow") or [])
    ]
    losers = [
        {"symbol": r["symbol"], "pct": r["pct"], "last": r.get("last", 0)}
        for r in (payload.get("outflow") or [])
    ]
    return {"gainers": gainers, "losers": losers, "source": payload.get("data_feed", "yfinance")}
