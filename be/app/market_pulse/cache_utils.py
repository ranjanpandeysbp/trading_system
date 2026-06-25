"""Attach no-op .clear() to functions that lost Streamlit cache decorators."""

from __future__ import annotations

_CACHED_NAMES = (
    "fetch_all_market_data",
    "fetch_oilprice_energy_quotes",
    "fetch_gift_nifty_5paisa",
    "fetch_5paisa_global_indices",
    "fetch_nse_option_chain",
    "fetch_nse_fii_dii",
    "fetch_nse_market_breadth",
    "fetch_nse_index_stock_movers",
    "fetch_index_monthly_stock_movers",
    "fetch_nse_turnover_delivery",
    "fetch_nse_delivery_turnover_history",
    "compute_sector_rotation",
    "compute_sector_rotation_intraday",
    "fetch_index_sr_levels",
    "fetch_news",
    "fetch_global_news",
    "fetch_analyst_calls",
    "get_yf_data",
    "compute_stock_price_rotation",
)


def attach_clear_stubs(module) -> None:
    for name in _CACHED_NAMES:
        fn = getattr(module, name, None)
        if callable(fn) and not hasattr(fn, "clear"):
            fn.clear = lambda: None  # type: ignore[attr-defined]
