"""
ticker_selection_ui.py
----------------------
Shared market + INDEX / CoinDCX ticker selectors for all strategy tabs.
"""

from __future__ import annotations


try:
    from app.market_pulse.ticker_utils import (
        CRYPTO_MARKET,
        GROWW_MARKET,
        INDEX_OPTIONS,
        MARKET_OPTIONS,
        US_MARKET,
        get_coindcx_ticker_list,
        get_index_options_for_market,
        is_crypto_market,
        is_india_market,
        is_us_market,
        market_currency,
    )
except ImportError:
    INDEX_OPTIONS = {"Custom": []}
    MARKET_OPTIONS = ["Groww (India Stocks)", "US Stocks (Yahoo)", "CoinDCX Futures"]
    GROWW_MARKET = "Groww (India Stocks)"
    US_MARKET = "US Stocks (Yahoo)"
    CRYPTO_MARKET = "CoinDCX Futures"

    def get_coindcx_ticker_list():
        return []

    def get_index_options_for_market(_market: str):
        return INDEX_OPTIONS

    def is_crypto_market(market: str) -> bool:
        return "CoinDCX" in (market or "")

    def is_us_market(market: str) -> bool:
        return "US Stocks" in (market or "")

    def is_india_market(market: str) -> bool:
        return not is_crypto_market(market) and not is_us_market(market)

    def market_currency(market: str) -> str:
        return "$" if not is_india_market(market) else "₹"

COINDCX_MODE_OPTIONS = [
    "All USDT Pairs",
    "Top by Volume",
    "Top By Price",
    "Top Volatile",
    "Bottom by Price",
    "Manual Selection",
    "Custom",
]


def render_market_selectbox(
    key: str,
    *,
    label: str = "🌐 Market",
    index: int = 0,
    help_text: str | None = None,
) -> str:
    """Standard three-way market selector (India · US · Crypto)."""
    kwargs: dict = {"key": key}
    if help_text:
        kwargs["help"] = help_text
    return st.selectbox(label, MARKET_OPTIONS, index=index, **kwargs)


def render_equity_index_ticker_selection(
    market: str,
    key_prefix: str,
    *,
    multiselect: bool = True,
    default_count: int = 3,
    custom_default: str = "RELIANCE,HDFCBANK,TCS,INFY",
    us_custom_default: str = "AAPL,MSFT,NVDA,AMZN,META",
) -> list[str]:
    """
    Index / group + ticker picker for Groww (India) or US Stocks (Yahoo).
    Returns uppercase symbol list.
    """
    idx_opts = get_index_options_for_market(market)
    default_custom = us_custom_default if is_us_market(market) else custom_default

    c1, c2 = st.columns([1, 2])
    with c1:
        index_sel = st.selectbox(
            "Index / Group",
            list(idx_opts.keys()) + ["Custom"],
            index=0,
            key=f"{key_prefix}_index_sel",
        )
    with c2:
        if index_sel == "Custom":
            raw = st.text_area(
                "Custom Tickers (comma-separated)",
                value=default_custom,
                height=70,
                key=f"{key_prefix}_custom_tickers",
            )
            return [t.strip().upper() for t in raw.split(",") if t.strip()]

        all_tickers = list(idx_opts.get(index_sel, []))
        st.info(f"📊 {index_sel}: **{len(all_tickers)}** tickers")
        if len(all_tickers) > 50:
            st.caption("Large universe — consider multiselecting a subset for faster scans.")
        if not multiselect:
            pick = st.selectbox(
                "Select Ticker",
                all_tickers or ["—"],
                key=f"{key_prefix}_single_ticker",
            )
            return [pick] if pick and pick != "—" else []
        default = all_tickers[:default_count] if len(all_tickers) >= default_count else all_tickers
        return st.multiselect(
            "Select Tickers",
            all_tickers,
            default=default,
            key=f"{key_prefix}_equity_tickers",
        )


def render_groww_ticker_selection(key_prefix: str = "pdp") -> tuple[list[str], str]:
    """
    EXCHANGE + INDEX + Custom universe — India (Groww) or US (Yahoo).
    Returns (ticker_list, exchange). Exchange is NSE for US/Crypto paths.
    """
    market = GROWW_MARKET
    if f"{key_prefix}_market" in st.session_state:
        market = st.session_state[f"{key_prefix}_market"]

    if is_us_market(market):
        tickers = render_equity_index_ticker_selection(US_MARKET, key_prefix, multiselect=False)
        return tickers, "NSE"

    col1, col2, col3 = st.columns([1, 1.5, 2])
    with col1:
        exchange = st.selectbox(
            "EXCHANGE",
            ["NSE", "BSE"],
            index=0,
            key=f"{key_prefix}_groww_ex",
        )
    idx_opts = get_index_options_for_market(GROWW_MARKET)
    with col2:
        index_sel = st.selectbox(
            "INDEX",
            list(idx_opts.keys()) + ["Custom"],
            index=0,
            key=f"{key_prefix}_index_sel",
        )
    with col3:
        if index_sel == "Custom":
            raw = st.text_area(
                "SCAN UNIVERSE (comma-separated tickers)",
                value="HDFCBANK,RELIANCE,TCS,WIPRO,INFY",
                height=70,
                key=f"{key_prefix}_groww_tickers",
                placeholder="e.g., RELIANCE,TCS,INFY,HDFCBANK",
            )
            tickers = [t.strip().upper() for t in raw.split(",") if t.strip()]
        else:
            selected = idx_opts.get(index_sel, [])
            st.info(f"📊 {index_sel}: {len(selected)} tickers selected")
            tickers = list(selected)
    return tickers, exchange


def render_coindcx_ticker_selection(
    key_prefix: str = "scanner",
    *,
    show_session_note: bool = True,
) -> list[str]:
    """
    CoinDCX **Select Tickers Mode** dropdown — mirrors Strategy Lab · Multi-Combo Scanner.
    Returns list of display symbols (e.g. BTC-USDT).
    """
    if show_session_note:
        from app.market_pulse.crypto_session import render_crypto_session_caption
        render_crypto_session_caption(short=True)

    try:
        market_data = get_coindcx_ticker_list()
    except Exception:
        try:
            from app.market_pulse.presets import POPULAR_CRYPTO_PAIRS
            market_data = [{"symbol": t, "display": t} for t in POPULAR_CRYPTO_PAIRS]
        except ImportError:
            market_data = [{"symbol": t, "display": t} for t in ["BTC-USDT", "ETH-USDT", "SOL-USDT"]]

    col1, col2, col3 = st.columns([2, 2, 2])
    with col1:
        mode = st.selectbox(
            "Select Tickers Mode",
            COINDCX_MODE_OPTIONS,
            index=1,
            key=f"{key_prefix}_coindcx_mode",
        )

    sorted_data = market_data
    display_options = [item["display"] for item in sorted_data]
    tickers: list[str] = []

    if mode == "Custom":
        with col2:
            custom = st.text_area(
                "Custom Tickers (comma-separated)",
                value="BTC-USDT, ETH-USDT, SOL-USDT, XRP-USDT",
                height=70,
                key=f"{key_prefix}_custom_input",
            )
            tickers = [t.strip().upper() for t in custom.split(",") if t.strip()]
    elif mode == "Manual Selection":
        with col2:
            tickers = st.multiselect(
                "Choose Tickers",
                options=display_options,
                default=display_options[:2] if len(display_options) >= 2 else display_options,
                key=f"{key_prefix}_coindcx_multiselect",
            )
    elif mode == "Top Volatile":
        with col2:
            top_n = st.selectbox(
                "Limit Tickers (Top N)",
                [10, 15, 25, 50, 100, "All"],
                index=1,
                key=f"{key_prefix}_coindcx_volatile_top_n",
            )
        try:
            from app.market_pulse.heatmap import get_coindcx_gainers
            gainers, _ = get_coindcx_gainers()
            if gainers:
                volatile = [
                    x["sym"].replace("B-", "").replace("_USDT", "-USDT") for x in gainers
                ]
                tickers = volatile if top_n == "All" else volatile[: int(top_n)]
            else:
                st.warning("⚠️ Could not fetch volatile cryptos. Using default list.")
                fallback = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT", "ADA-USDT"]
                tickers = fallback if top_n == "All" else fallback[: int(top_n)]
        except Exception as exc:
            st.warning(f"⚠️ Error fetching volatile cryptos: {str(exc)}. Using default list.")
            tickers = ["BTC-USDT", "ETH-USDT", "SOL-USDT"]
    else:
        with col2:
            top_n = st.selectbox(
                "Limit Tickers (Top N)",
                [10, 25, 50, 100, 200, 300, 500, "All"],
                index=1,
                key=f"{key_prefix}_coindcx_top_n",
            )
        if top_n == "All":
            tickers = display_options
        else:
            tickers = display_options[: int(top_n)]

    return tickers


def render_coindcx_ticker_picker(
    key_prefix: str,
    *,
    single: bool = False,
    label: str = "Crypto ticker",
) -> list[str]:
    """
    CoinDCX ticker picker: universe modes + Manual multiselect/selectone + Custom.
    Returns display symbols (e.g. BTC-USDT) or API-style when from list.
    """
    try:
        market_data = get_coindcx_ticker_list()
    except Exception:
        from app.market_pulse.presets import POPULAR_CRYPTO_PAIRS
        market_data = [{"symbol": t, "display": t.replace("B-", "").replace("_USDT", "-USDT")} for t in POPULAR_CRYPTO_PAIRS]

    display_options = [item["display"] for item in market_data]
    symbol_by_display = {item["display"]: item["symbol"] for item in market_data}

    c1, c2 = st.columns([1, 2])
    with c1:
        mode = st.selectbox(
            f"{label} — source",
            COINDCX_MODE_OPTIONS,
            index=5 if single else 4,
            key=f"{key_prefix}_coindcx_mode",
        )
    tickers: list[str] = []

    if mode == "Custom":
        with c2:
            custom = st.text_area(
                "Custom tickers (comma-separated)",
                value="BTC-USDT, ETH-USDT, SOL-USDT",
                height=70,
                key=f"{key_prefix}_coindcx_custom",
            )
        tickers = [t.strip().upper() for t in custom.split(",") if t.strip()]
    elif mode == "Manual Selection":
        with c2:
            if single:
                pick = st.selectbox(
                    "Select ticker",
                    display_options or ["—"],
                    key=f"{key_prefix}_coindcx_one",
                )
                tickers = [pick] if pick and pick != "—" else []
            else:
                tickers = st.multiselect(
                    "Select tickers (one or more)",
                    display_options,
                    default=display_options[:3] if len(display_options) >= 3 else display_options,
                    key=f"{key_prefix}_coindcx_multi",
                )
    else:
        with c2:
            top_n = st.selectbox(
                "Limit (Top N)",
                [10, 25, 50, 100, 200, "All"],
                index=1,
                key=f"{key_prefix}_coindcx_top_n",
            )
        pool = display_options if top_n == "All" else display_options[: int(top_n)]
        if single:
            with c2:
                pick = st.selectbox("Pick one", pool or ["—"], key=f"{key_prefix}_coindcx_pool_one")
                tickers = [pick] if pick and pick != "—" else []
        else:
            with c2:
                tickers = st.multiselect(
                    "Select from universe",
                    pool,
                    default=pool[:3] if len(pool) >= 3 else pool,
                    key=f"{key_prefix}_coindcx_pool_multi",
                )

    out: list[str] = []
    for t in tickers:
        disp = t.replace("B-", "").replace("_USDT", "-USDT") if t.startswith("B-") else t
        out.append(symbol_by_display.get(disp, t))
    return out


def render_hedge_ticker_picker(
    market: str,
    key_prefix: str,
    *,
    single: bool = False,
    label: str = "Ticker",
    default_count: int = 3,
) -> list[str]:
    """Index/universe dropdown + multiselect or single select + Custom — all markets."""
    if is_crypto_market(market):
        return render_coindcx_ticker_picker(key_prefix, single=single, label=label)
    return render_equity_index_ticker_selection(
        market,
        key_prefix,
        multiselect=not single,
        default_count=default_count,
    )


def coindcx_display_to_api_symbol(display: str) -> str:
    """Convert BTC-USDT display label to CoinDCX API symbol B-BTC_USDT."""
    t = (display or "").strip().upper()
    if t.startswith("B-"):
        return t
    if "-USDT" in t:
        base = t.replace("-USDT", "")
        return f"B-{base}_USDT"
    if t.endswith("USDT"):
        base = t.replace("USDT", "")
        return f"B-{base}_USDT"
    return f"B-{t}_USDT"
