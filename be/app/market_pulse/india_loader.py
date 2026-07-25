"""India-only Market Intelligence payload (no US/crypto sections)."""

from __future__ import annotations

import time
from typing import Any

from app.market_pulse.cache_utils import attach_clear_stubs
from app.market_pulse.groww_auth import set_groww_token
from app.market_pulse.market_pulse_feeds import fetch_analyst_calls, fetch_india_news, get_india_events
from app.market_pulse.nse_index_yfinance import INDIA_MARKET_DISPLAY_YF
from app.market_pulse.serialize import json_safe


def _india_market_data() -> dict[str, Any]:
    import app.market_pulse.news_scanner as ns

    data: dict[str, Any] = {}
    for name, sym in INDIA_MARKET_DISPLAY_YF.items():
        price, pct, hist = ns.get_yf_data(sym)
        data[name] = {
            "price": price,
            "pct": pct,
            "hist": None,
            "symbol": sym,
            "source": "yahoo",
        }
        time.sleep(0.02)

    gift = ns.fetch_gift_nifty_5paisa()
    if gift and gift.get("price") is not None:
        data["Gift Nifty"] = {
            "price": gift["price"],
            "pct": gift.get("pct"),
            "symbol": "GIFTNIFTY",
            "source": "5paisa.com",
            "day_high": gift.get("day_high"),
            "day_low": gift.get("day_low"),
        }

    # Macro context useful for Indian traders
    for name, sym in {
        "USD/INR": "INR=X",
        "Crude Oil (WTI)": "CL=F",
        "India 10Y Yield": "^TNX",
    }.items():
        price, pct, _ = ns.get_yf_data(sym)
        data[name] = {"price": price, "pct": pct, "symbol": sym, "source": "yahoo"}

    return data


def load_india_intelligence(groww_token: str = "") -> dict[str, Any]:
    import app.market_pulse.news_scanner as ns

    attach_clear_stubs(ns)
    set_groww_token(groww_token)

    market_data = _india_market_data()
    option_data = ns.fetch_nse_option_chain("NIFTY", groww_token=groww_token)
    fii_dii_data = ns.fetch_nse_fii_dii()
    breadth_data = ns.fetch_nse_market_breadth()
    turnover_delivery_data = ns.fetch_nse_turnover_delivery()

    sentiment = ns.analyze_options_sentiment(option_data) if option_data else {}
    market_sentiment = ns.analyze_today_market_sentiment(
        market_data,
        option_data,
        fii_dii_data=fii_dii_data,
        breadth_data=breadth_data,
        turnover_delivery_data=turnover_delivery_data,
    )
    tomorrow_outlook = ns.analyze_tomorrow_market_outlook(
        market_data,
        option_data,
        fii_dii_data=fii_dii_data,
        breadth_data=breadth_data,
        turnover_delivery_data=turnover_delivery_data,
    )

    sr_names = list(INDIA_MARKET_DISPLAY_YF.keys())
    index_sr_map = ns.fetch_index_sr_levels(sr_names) or {}

    return json_safe(
        {
            "market_data": market_data,
            "index_sr_map": index_sr_map,
            "news_articles": fetch_india_news(),
            "analyst_calls": fetch_analyst_calls(),
            "india_events": get_india_events(),
            "option_data": option_data,
            "fii_dii_data": fii_dii_data,
            "breadth_data": breadth_data,
            "turnover_delivery_data": turnover_delivery_data,
            "sentiment": sentiment,
            "market_sentiment": market_sentiment,
            "tomorrow_outlook": tomorrow_outlook,
        }
    )
