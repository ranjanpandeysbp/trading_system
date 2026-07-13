"""
demo_trading.py
---------------
Paper / demo trading for learning — unlimited virtual capital, per logged-in user.
"""

from __future__ import annotations

from contextlib import nullcontext

import re
from datetime import date, datetime, timedelta

import pandas as pd
from app.market_pulse.database import (
    close_demo_trade,
    create_demo_trade,
    delete_all_demo_trades,
    get_demo_trades,
)
from backtesting.data_fetcher import get_historical_data, get_live_quote
from app.market_pulse.groww_auth import get_active_groww_token
from app.market_pulse.nse_index_yfinance import stock_symbol_to_yf


def get_logged_in_mobile() -> str:
    return (st.session_state.get("logged_in_mobile") or "").strip()


def normalize_market_type(market: str) -> str:
    m = (market or "").lower()
    if "coindcx" in m or "crypto" in m:
        return "crypto"
    return "india"


def market_label_for_type(market_type: str) -> str:
    return "CoinDCX Futures" if market_type == "crypto" else "Groww (India Stocks)"


def currency_for_market_type(market_type: str) -> str:
    return "$" if market_type == "crypto" else "₹"


def _safe_key(key: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", key)


def _market_for_fetch(market_label: str, market_type: str) -> str:
    if market_type == "crypto":
        return "CoinDCX Futures"
    label = (market_label or "").strip()
    if "coindcx" in label.lower():
        return "CoinDCX Futures"
    return label or "Groww (India Stocks)"


def clear_demo_price_cache(market_type: str | None = None) -> int:
    """Drop cached demo prices (all markets or one market_type suffix)."""
    removed = 0
    suffix = f"_{market_type}" if market_type else None
    for key in list(st.session_state.keys()):
        if not key.startswith("demo_px_"):
            continue
        if suffix is None or key.endswith(suffix):
            del st.session_state[key]
            removed += 1
    return removed


def _yf_quick_price(ticker: str, market_type: str, timeframe: str) -> float | None:
    try:
        import yfinance as yf

        sym = ticker.upper().strip()
        if market_type == "crypto":
            base = sym.replace("B-", "").replace("-USDT", "").replace("-", "").replace("_", "")
            yf_sym = f"{base}-USD"
        else:
            yf_sym = stock_symbol_to_yf(sym)

        period = "5d" if timeframe in ("1m", "5m", "15m", "30m", "1h", "4h") else "1mo"
        interval = timeframe if timeframe in ("1m", "5m", "15m", "30m", "1h", "1d") else "1d"
        if timeframe == "4h":
            interval = "1h"

        raw = yf.download(
            yf_sym,
            period=period,
            interval=interval,
            progress=False,
            auto_adjust=True,
        )
        if raw is None or raw.empty:
            hist = yf.Ticker(yf_sym).history(period=period, interval=interval, auto_adjust=True)
            if hist is None or hist.empty:
                return None
            return float(hist["Close"].iloc[-1])

        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        close_col = "Close" if "Close" in raw.columns else "close"
        return float(raw[close_col].iloc[-1])
    except Exception:
        return None


def fetch_latest_price(
    ticker: str,
    market: str,
    timeframe: str = "1d",
    groww_token: str = "",
    exchange: str = "NSE",
    *,
    force_refresh: bool = False,
) -> dict:
    """
    Return {price, source, change_pct, fetched_at} for a demo position mark.
    Uses live quote API first, then historical / yfinance fallback.
    """
    market_type = normalize_market_type(market)
    cache_key = f"demo_px_{ticker}_{timeframe}_{market_type}"
    if not force_refresh and cache_key in st.session_state:
        return st.session_state[cache_key]

    mkt = _market_for_fetch(market, market_type)
    price: float | None = None
    source = ""
    change_pct: float | None = None

    quote = get_live_quote(
        ticker,
        mkt,
        exchange=exchange,
        groww_token=groww_token,
    )
    if quote and quote.get("ltp"):
        try:
            price = float(quote["ltp"])
            if price > 0:
                source = "live"
                change_pct = quote.get("change_pct")
        except (TypeError, ValueError):
            price = None

    if price is None:
        try:
            df = get_historical_data(
                symbol=ticker,
                start_date=str(date.today() - timedelta(days=30)),
                end_date=str(date.today()),
                market=mkt,
                timeframe=timeframe,
                groww_token=groww_token,
                groww_exchange=exchange,
            )
            if df is not None and not df.empty:
                price = float(df["close"].iloc[-1])
                source = "historical"
        except Exception:
            price = None

    if price is None:
        price = _yf_quick_price(ticker, market_type, timeframe)
        if price is not None:
            source = "yfinance"

    payload = {
        "price": price,
        "source": source or "unavailable",
        "change_pct": change_pct,
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if price is not None:
        st.session_state[cache_key] = payload
    return payload


def compute_trade_pnl(trade: dict, current_price: float | dict | None) -> dict:
    if isinstance(current_price, dict):
        current_price = current_price.get("price")
    if current_price is not None:
        try:
            current_price = float(current_price)
        except (TypeError, ValueError):
            current_price = None
    entry = float(trade["entry_price"])
    qty = float(trade["quantity"])
    direction = trade["direction"].upper()
    if entry <= 0 or current_price is None:
        return {
            "pnl_pct": 0.0,
            "pnl_amount": 0.0,
            "current_price": current_price,
            "sl_hit": False,
            "sl_price": None,
        }

    if direction == "LONG":
        pnl_pct = ((current_price - entry) / entry) * 100
    else:
        pnl_pct = ((entry - current_price) / entry) * 100
    pnl_amount = (pnl_pct / 100) * entry * qty

    sl_hit = False
    sl_price = None
    sl_pct = trade.get("stop_loss_pct")
    sl_amt = trade.get("stop_loss_amount")
    if sl_pct is not None and sl_pct > 0:
        if direction == "LONG":
            sl_price = entry * (1 - sl_pct / 100)
            sl_hit = current_price <= sl_price
        else:
            sl_price = entry * (1 + sl_pct / 100)
            sl_hit = current_price >= sl_price
    elif sl_amt is not None and sl_amt > 0:
        if direction == "LONG":
            sl_price = entry - sl_amt
            sl_hit = current_price <= sl_price
        else:
            sl_price = entry + sl_amt
            sl_hit = current_price >= sl_price

    return {
        "pnl_pct": pnl_pct,
        "pnl_amount": pnl_amount,
        "current_price": current_price,
        "sl_hit": sl_hit,
        "sl_price": sl_price,
    }


def _closed_trade_pnl(trade: dict) -> tuple[float, float]:
    entry = float(trade["entry_price"])
    exit_p = float(trade["exit_price"] or entry)
    qty = float(trade["quantity"])
    if trade["direction"].upper() == "LONG":
        pnl_pct = ((exit_p - entry) / entry) * 100
    else:
        pnl_pct = ((entry - exit_p) / entry) * 100
    return pnl_pct, (pnl_pct / 100) * entry * qty


def _portfolio_stats(
    open_rows: list[dict],
    closed_trades: list[dict],
    currency: str,
) -> dict:
    realized = sum(_closed_trade_pnl(t)[1] for t in closed_trades)
    wins = sum(1 for t in closed_trades if _closed_trade_pnl(t)[1] > 0)
    losses = sum(1 for t in closed_trades if _closed_trade_pnl(t)[1] < 0)
    closed_n = len(closed_trades)
    win_rate = (wins / closed_n * 100) if closed_n else None
    unrealized = sum(r.get("pnl_amount", 0) for r in open_rows)
    sl_alerts = sum(1 for r in open_rows if r.get("sl_hit"))
    return {
        "open_count": len(open_rows),
        "closed_count": closed_n,
        "unrealized": unrealized,
        "realized": realized,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "sl_alerts": sl_alerts,
        "currency": currency,
    }


def render_demo_trade_panel(
    session_prefix: str,
    result_key: str,
    ticker: str,
    timeframe: str,
    market: str,
    strategy_name: str,
    current_price: float = None,
    source_tab: str = "",
    groww_token: str = "",
    exchange: str = "NSE",
):
    """Paper-trade entry form — place alongside AI View per ticker/timeframe."""
    mobile = get_logged_in_mobile()
    if not mobile:
        return

    market_type = normalize_market_type(market)
    currency = currency_for_market_type(market_type)
    safe = _safe_key(result_key)
    form_key = f"{session_prefix}_demo_{safe}"

    if current_price is None:
        quote = fetch_latest_price(ticker, market, timeframe, groww_token, exchange)
        current_price = quote.get("price")

    with st.expander("📝 Demo Trade (Paper · Unlimited Capital)", expanded=False):
        st.caption(
            "⚠️ **Learning only** — virtual money, no real orders. "
            "Trades are saved to your logged-in profile."
        )
        if current_price is None:
            st.warning("Could not fetch current price. Check symbol and data connection.")
            return

        st.markdown(f"**{ticker}** · `{timeframe}` · **{currency}{current_price:,.4f}**")

        with st.form(form_key):
            c1, c2 = st.columns(2)
            with c1:
                direction = st.selectbox("Direction", ["LONG", "SHORT"], key=f"{form_key}_dir")
            with c2:
                quantity = st.number_input(
                    "Quantity", min_value=0.0001, value=1.0, step=1.0, key=f"{form_key}_qty",
                )

            st.markdown("**Stop Loss (optional)**")
            sl_col1, sl_col2 = st.columns(2)
            with sl_col1:
                use_sl_pct = st.checkbox("SL in %", value=False, key=f"{form_key}_sl_pct_on")
                sl_pct = st.number_input(
                    "Stop Loss %", min_value=0.1, max_value=50.0, value=2.0, step=0.1,
                    disabled=not use_sl_pct, key=f"{form_key}_sl_pct",
                )
            with sl_col2:
                use_sl_amt = st.checkbox("SL in amount", value=False, key=f"{form_key}_sl_amt_on")
                sl_amount = st.number_input(
                    f"Stop Loss ({currency})", min_value=0.01, value=10.0, step=1.0,
                    disabled=not use_sl_amt, key=f"{form_key}_sl_amt",
                )

            strategy_display = st.text_input(
                "Strategy / Signal Source",
                value=strategy_name or "Manual",
                key=f"{form_key}_strat",
            )

            submitted = st.form_submit_button("✅ Take Demo Trade at Market Price", width='stretch')
            if submitted:
                final_sl_pct = sl_pct if use_sl_pct else None
                final_sl_amt = sl_amount if use_sl_amt else None
                ok = create_demo_trade(
                    mobile_number=mobile,
                    market_type=market_type,
                    market_label=market,
                    ticker=ticker,
                    timeframe=timeframe,
                    direction=direction,
                    quantity=quantity,
                    entry_price=current_price,
                    strategy_name=strategy_display.strip(),
                    source_tab=source_tab,
                    stop_loss_pct=final_sl_pct,
                    stop_loss_amount=final_sl_amt,
                )
                if ok:
                    clear_demo_price_cache(market_type)
                    st.success(
                        f"Demo {direction} trade opened: {quantity} × {ticker} @ "
                        f"{currency}{current_price:,.4f}"
                    )
                    st.toast("Demo trade registered!", icon="📝")
                    st.rerun()
                else:
                    st.error("Failed to save demo trade.")


def render_demo_trading_portfolio(market_type: str):
    """Full portfolio page — separate for India stocks vs crypto."""
    mobile = get_logged_in_mobile()
    label = market_label_for_type(market_type)
    currency = currency_for_market_type(market_type)

    if not mobile:
        st.warning("Please **log in** to view and manage demo trades.")
        return

    st.markdown(
        f"### {'🪙 Crypto' if market_type == 'crypto' else '🇮🇳 India'} · Paper Portfolio",
    )
    st.caption(
        f"Account **{mobile}** · {label} · virtual capital · "
        "prices from live quote API with yfinance fallback"
    )

    groww_token = get_active_groww_token()
    exchange = st.session_state.get("mega_exchange", "NSE") if market_type == "india" else "NSE"

    force_refresh = False
    col_refresh, col_clear_cache, col_reset = st.columns([2, 1, 1])
    with col_refresh:
        if st.button(
            "🔄 Refresh Live P&L",
            key=f"demo_refresh_{market_type}",
            type="primary",
            width='stretch',
        ):
            cleared = clear_demo_price_cache(market_type)
            st.session_state[f"demo_last_refresh_{market_type}"] = datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            st.session_state[f"demo_last_clear_count_{market_type}"] = cleared
            st.toast(f"Refreshing {cleared} cached quote(s)…", icon="🔄")
            force_refresh = True
    with col_clear_cache:
        if st.button("Clear quote cache", key=f"demo_clear_cache_{market_type}", width='stretch'):
            n = clear_demo_price_cache(market_type)
            st.toast(f"Cleared {n} cached quote(s)", icon="🧹")
            force_refresh = True
    with col_reset:
        if st.button("🗑️ Delete All", key=f"demo_reset_{market_type}", width='stretch'):
            st.session_state[f"demo_confirm_reset_{market_type}"] = True

    last_refresh = st.session_state.get(f"demo_last_refresh_{market_type}", "—")
    st.caption(f"Last refresh: **{last_refresh}**")

    if st.session_state.get(f"demo_confirm_reset_{market_type}"):
        st.warning("This will permanently delete ALL demo trades for this market. Continue?")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Yes, delete all", key=f"demo_reset_yes_{market_type}"):
                n = delete_all_demo_trades(mobile, market_type)
                clear_demo_price_cache(market_type)
                st.session_state[f"demo_confirm_reset_{market_type}"] = False
                st.success(f"Deleted {n} demo trade(s).")
        with c2:
            if st.button("Cancel", key=f"demo_reset_no_{market_type}"):
                st.session_state[f"demo_confirm_reset_{market_type}"] = False

    open_trades = get_demo_trades(mobile, market_type=market_type, status="OPEN")
    closed_trades = get_demo_trades(mobile, market_type=market_type, status="CLOSED")

    if not open_trades and not closed_trades:
        st.info(
            "No demo trades yet. Open trades from **Technical Analysis** or scanner tabs using "
            "**📝 Demo Trade (Paper)** under each signal."
        )
        return

    open_rows: list[dict] = []
    fetch_errors: list[str] = []

    if open_trades:
        with nullcontext():
            for trade in open_trades:
                mkt = _market_for_fetch(trade.get("market_label"), market_type)
                quote = fetch_latest_price(
                    trade["ticker"],
                    mkt,
                    trade["timeframe"],
                    groww_token,
                    exchange,
                    force_refresh=force_refresh,
                )
                px = quote.get("price")
                if px is None:
                    fetch_errors.append(f"{trade['ticker']} ({trade['timeframe']})")
                pnl = compute_trade_pnl(trade, px)
                row = {
                    **trade,
                    "current_price": px,
                    "price_source": quote.get("source", "—"),
                    "quote_time": quote.get("fetched_at", "—"),
                    **pnl,
                }
                open_rows.append(row)

        if force_refresh:
            cleared = st.session_state.get(f"demo_last_clear_count_{market_type}", 0)
            st.success(
                f"Live P&L updated at {last_refresh} "
                f"({len(open_rows)} open position(s), {cleared} cache entries cleared)."
            )

    stats = _portfolio_stats(open_rows, closed_trades, currency)

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Open", stats["open_count"])
    m2.metric("Unrealized P&L", f"{currency}{stats['unrealized']:+,.2f}")
    m3.metric("Realized P&L", f"{currency}{stats['realized']:+,.2f}")
    if stats["win_rate"] is not None:
        m4.metric("Win rate", f"{stats['win_rate']:.0f}%", delta=f"{stats['wins']}W / {stats['losses']}L")
    else:
        m4.metric("Win rate", "—")
    m5.metric("SL alerts", stats["sl_alerts"])

    if fetch_errors:
        st.warning(
            "Could not price: " + ", ".join(fetch_errors[:8])
            + ("…" if len(fetch_errors) > 8 else "")
            + " — check ticker symbol or Groww token / market hours."
        )

    if open_rows:
        st.markdown("#### 📂 Open positions")
        table_rows = []
        for row in open_rows:
            table_rows.append({
                "ID": row["id"],
                "Ticker": row["ticker"],
                "TF": row["timeframe"],
                "Dir": row["direction"],
                "Qty": row["quantity"],
                "Entry": f"{currency}{float(row['entry_price']):,.2f}",
                "Last": f"{currency}{(row.get('current_price') or 0):,.2f}",
                "P&L %": f"{row.get('pnl_pct', 0):+.2f}%",
                "P&L": f"{currency}{row.get('pnl_amount', 0):+,.2f}",
                "Source": row.get("price_source", "—"),
                "Strategy": (row.get("strategy_name") or "")[:24],
            })
        st.dataframe(pd.DataFrame(table_rows), width='stretch', hide_index=True)

        for row in open_rows:
            pnl_color = "#10b981" if row.get("pnl_pct", 0) >= 0 else "#ef4444"
            sl_warn = " 🔴 **STOP LOSS HIT**" if row.get("sl_hit") else ""
            with st.container(border=True):
                h1, h2 = st.columns([4, 1])
                with h1:
                    st.markdown(
                        f"**#{row['id']} {row['ticker']}** · `{row['timeframe']}` · "
                        f"**{row['direction']}** × {row['quantity']}"
                    )
                    st.caption(
                        f"Entry {currency}{float(row['entry_price']):,.4f} → "
                        f"Now {currency}{(row.get('current_price') or 0):,.4f} "
                        f"({row.get('price_source', '—')} @ {row.get('quote_time', '—')}) · "
                        f"From: {row.get('source_tab') or '—'} · {row.get('strategy_name') or 'Manual'}"
                    )
                with h2:
                    st.markdown(
                        f"<span style='color:{pnl_color};font-size:1.15rem;font-weight:700;'>"
                        f"{row.get('pnl_pct', 0):+.2f}%</span>{sl_warn}",
                        unsafe_allow_html=True,
                    )
                    st.caption(f"{currency}{row.get('pnl_amount', 0):+,.2f}")

                if row.get("stop_loss_pct"):
                    st.caption(f"SL: {row['stop_loss_pct']}%")
                elif row.get("stop_loss_amount"):
                    st.caption(f"SL: {currency}{row['stop_loss_amount']:,.2f} from entry")
                if row.get("sl_price"):
                    st.caption(f"SL trigger: {currency}{row['sl_price']:,.4f}")

                if st.button(
                    "Close at market",
                    key=f"demo_close_{row['id']}",
                    width='stretch',
                ):
                    px = row.get("current_price")
                    if px is not None and close_demo_trade(row["id"], mobile, float(px)):
                        clear_demo_price_cache(market_type)
                        st.toast(f"Closed {row['ticker']} @ {currency}{px:,.4f}", icon="✅")
                    else:
                        st.error("Could not close — live price unavailable. Try Refresh Live P&L.")

    if closed_trades:
        st.markdown("#### 📁 Closed positions")
        rows = []
        total_realized = 0.0
        for trade in closed_trades[:100]:
            pnl_pct, pnl_amt = _closed_trade_pnl(trade)
            total_realized += pnl_amt
            rows.append({
                "ID": trade["id"],
                "Ticker": trade["ticker"],
                "TF": trade["timeframe"],
                "Dir": trade["direction"],
                "Qty": float(trade["quantity"]),
                "Entry": f"{currency}{float(trade['entry_price']):,.2f}",
                "Exit": f"{currency}{float(trade['exit_price'] or 0):,.2f}",
                "P&L %": f"{pnl_pct:+.2f}%",
                "P&L": f"{currency}{pnl_amt:+,.2f}",
                "Strategy": trade.get("strategy_name", ""),
                "Source": trade.get("source_tab", ""),
                "Opened": (trade.get("created_at") or "")[:16],
                "Closed": (trade.get("closed_at") or "")[:16],
            })
        if rows:
            st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)
            st.caption(f"Realized P&L (shown): **{currency}{total_realized:+,.2f}** across {len(rows)} trade(s)")

    section_id = "demo_crypto" if market_type == "crypto" else "demo_india"
    from app.market_pulse.ask_ai_context import snapshot_section_for_ask_ai
    snapshot_section_for_ask_ai(section_id)
