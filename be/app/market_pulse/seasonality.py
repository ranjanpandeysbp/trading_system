from contextlib import nullcontext
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
import plotly.express as px
from scipy import stats
from datetime import datetime, timedelta
import time

from app.market_pulse.ai_view import (
    render_ai_config,
    ai_view_button,
    render_ai_view_report,
    build_seasonality_ai_prompt,
    SEASONALITY_AI_SYSTEM,
    MONTH_NAMES,
)
from app.market_pulse.price_extremes import render_price_extremes_for_ticker
from app.market_pulse.groww_auth import get_active_groww_token
from app.market_pulse.run_summary import render_run_summary, summarize_seasonality

def fetch_seasonality_data(tickers, years=10, market: str = ""):
    """Fetch historical daily OHLCV data for multiple tickers."""
    from app.market_pulse.ticker_utils import is_crypto_market, is_us_market
    from app.market_pulse.us_market_yfinance import us_symbol_to_yf

    end_date = datetime.now()
    start_date = end_date - timedelta(days=years * 365.25)
    
    all_data = {}
    for ticker in tickers:
        yf_ticker = ticker
        if is_crypto_market(market) or ticker.startswith("B-") or "-USDT" in ticker.upper():
            if ticker.startswith("B-"):
                symbol = ticker.replace("B-", "").replace("USDT", "")
                yf_ticker = f"{symbol}-USD"
            elif "-USDT" in ticker.upper():
                symbol = ticker.upper().replace("-USDT", "")
                yf_ticker = f"{symbol}-USD"
        elif is_us_market(market):
            yf_ticker = us_symbol_to_yf(ticker)
        elif ticker.endswith(".NS"):
            yf_ticker = ticker
        elif not ticker.endswith(".NS") and ticker.isupper():
            yf_ticker = f"{ticker}.NS"

        try:
            df = yf.download(yf_ticker, start=start_date, end=end_date, interval="1d", progress=False)
            if not df.empty:
                all_data[ticker] = df
        except Exception as e:
            st.error(f"Error fetching {ticker}: {e}")
    return all_data

def compute_seasonality(df):
    """Compute monthly returns, win rates, and statistical significance."""
    # Ensure we have Close prices
    if 'Close' not in df.columns:
        return None
    
    # Resample to monthly returns
    monthly_prices = df['Close'].resample('ME').last()
    monthly_returns = monthly_prices.pct_change().dropna()
    
    # Create a dataframe for analysis
    returns_df = pd.DataFrame(monthly_returns)
    returns_df.columns = ['Return']
    returns_df['Year'] = returns_df.index.year
    returns_df['Month'] = returns_df.index.month
    
    # Pivot for heatmap: Years x Months
    pivot_table = returns_df.pivot(index='Year', columns='Month', values='Return')
    
    # Metrics per month
    stats_data = []
    for month in range(1, 13):
        month_rets = returns_df[returns_df['Month'] == month]['Return']
        if len(month_rets) < 2:
            continue
            
        avg_ret = month_rets.mean()
        std_dev = month_rets.std()
        win_rate = (month_rets > 0).mean()
        
        # T-test for significance (null hypothesis: mean return is 0)
        t_stat, p_val = stats.ttest_1samp(month_rets, 0)
        
        stats_data.append({
            'Month': month,
            'Avg Return': avg_ret,
            'Std Dev': std_dev,
            'Win Rate': win_rate,
            'P-Value': p_val,
            'Count': len(month_rets)
        })
        
    return pivot_table, pd.DataFrame(stats_data)

def generate_signals(stats_df):
    """Flag strong seasonal signals based on win rate and p-value."""
    signals = []
    for _, row in stats_df.iterrows():
        action = "NEUTRAL"
        strength = 0
        
        if row['Win Rate'] >= 0.65 and row['P-Value'] < 0.05:
            action = "STRONG BUY"
            strength = 2
        elif row['Win Rate'] >= 0.65:
            action = "BUY"
            strength = 1
        elif row['Win Rate'] <= 0.35 and row['P-Value'] < 0.05:
            action = "STRONG SELL"
            strength = -2
        elif row['Win Rate'] <= 0.35:
            action = "SELL"
            strength = -1
            
        signals.append({
            'Month': int(row['Month']),
            'Action': action,
            'Strength': strength,
            'Win Rate': row['Win Rate'],
            'P-Value': row['P-Value']
        })
    return pd.DataFrame(signals)

def run_seasonal_backtest(df, signals_df):
    """Simulate trading based on seasonal signals."""
    monthly_prices = df['Close'].resample('ME').last()
    monthly_returns = monthly_prices.pct_change().dropna().squeeze()
    
    # Ensure it's a Series just in case squeeze returns a single value or behaves unexpectedly
    if isinstance(monthly_returns, pd.DataFrame):
        monthly_returns = monthly_returns.iloc[:, 0]
    
    backtest_results = []
    current_val = 100.0
    
    for date, ret in monthly_returns.items():
        month = date.month
        sig = signals_df[signals_df['Month'] == month]
        
        if not sig.empty:
            action = sig.iloc[0]['Action']
            if "BUY" in action:
                current_val *= (1 + ret)
            elif "SELL" in action:
                # Assuming inverse for sell or stay cash. Let's stay cash (no change) 
                # or short (-ret). Institutional scanners often show 'Short' potential.
                current_val *= (1 - ret)
        
        backtest_results.append({'Date': date, 'Value': current_val})
        
    bt_df = pd.DataFrame(backtest_results).set_index('Date')
    
    # Compute metrics
    total_ret = (bt_df['Value'].iloc[-1] / 100.0) - 1
    days = (bt_df.index[-1] - bt_df.index[0]).days
    cagr = (bt_df['Value'].iloc[-1] / 100.0) ** (365.25 / days) - 1
    
    daily_rets = bt_df['Value'].pct_change().dropna()
    sharpe = (daily_rets.mean() / daily_rets.std()) * np.sqrt(12) if len(daily_rets) > 0 else 0
    
    # Drawdown
    rolling_max = bt_df['Value'].cummax()
    drawdown = (bt_df['Value'] / rolling_max) - 1
    max_dd = drawdown.min()
    
    return {
        'Total Return': total_ret,
        'CAGR': cagr,
        'Sharpe': sharpe,
        'Max Drawdown': max_dd,
        'Equity Curve': bt_df
    }

def render_seasonality_tab():
    st.markdown("""
    <style>
    .season-header {
        background: linear-gradient(135deg, #1e293b 0%, #334155 100%);
        padding: 20px;
        border-radius: 12px;
        border: 1px solid #475569;
        margin-bottom: 25px;
    }
    .metric-box-s {
        background: #0f172a;
        border: 1px solid #1e293b;
        padding: 15px;
        border-radius: 10px;
        text-align: center;
    }
    </style>
    """, unsafe_allow_html=True)

    st.markdown('<div class="season-header"><h2>🗓️ Institutional Seasonality Scanner</h2><p style="color:#94a3b8;">Identify repeating market patterns and probabilistic edges across years.</p></div>', unsafe_allow_html=True)

    provider, model, api_key = render_ai_config("season", caption="AI View generates per-ticker seasonal trade reports.")

    # ─── Sidebar/Configuration ──────────────────────────────────────────
    from app.market_pulse.ticker_utils import (
        CRYPTO_MARKET,
        GROWW_MARKET,
        US_MARKET,
        market_currency,
    )
    from app.market_pulse.ticker_selection_ui import (
        render_coindcx_ticker_selection,
        render_equity_index_ticker_selection,
    )
    
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        asset_type = st.radio("Asset Class", ["Indian Stocks", "US Stocks", "Crypto"], horizontal=True)
        if asset_type == "Crypto":
            selected_tickers = render_coindcx_ticker_selection("season")
        elif asset_type == "US Stocks":
            selected_tickers = render_equity_index_ticker_selection(US_MARKET, "season")
        else:
            selected_tickers = render_equity_index_ticker_selection(GROWW_MARKET, "season")
            
    with col2:
        lookback_years = st.slider("Analysis History (Years)", 3, 20, 10)
        
    with col3:
        st.markdown("<br>", unsafe_allow_html=True)
        run_scan = st.button("🚀 Run Seasonality Analysis", width='stretch')

    months = MONTH_NAMES

    if run_scan and selected_tickers:
        season_market = (
            CRYPTO_MARKET if asset_type == "Crypto"
            else US_MARKET if asset_type == "US Stocks"
            else GROWW_MARKET
        )
        with nullcontext():
            data_map = fetch_seasonality_data(selected_tickers, years=lookback_years, market=season_market)
            if not data_map:
                st.error("No data found for selected tickers.")
                return

            all_results = {}
            for ticker in selected_tickers:
                if ticker not in data_map:
                    continue
                df = data_map[ticker]
                pivot, stats_df = compute_seasonality(df)
                if stats_df is None or stats_df.empty:
                    all_results[ticker] = {"symbol": ticker, "error": f"Insufficient data for {ticker}"}
                    continue
                signals_df = generate_signals(stats_df)
                bt_metrics = run_seasonal_backtest(df, signals_df)
                all_results[ticker] = {
                    "symbol": ticker,
                    "df": df,
                    "pivot": pivot,
                    "stats_df": stats_df,
                    "signals_df": signals_df,
                    "bt_metrics": bt_metrics,
                }

            st.session_state.seasonality_results = all_results
            st.session_state.seasonality_asset_type = asset_type
            st.session_state.seasonality_lookback = lookback_years
            st.session_state.seasonality_market = (
                CRYPTO_MARKET if asset_type == "Crypto"
                else US_MARKET if asset_type == "US Stocks"
                else GROWW_MARKET
            )

    all_results = st.session_state.get("seasonality_results", {})
    asset_type_display = st.session_state.get("seasonality_asset_type", asset_type)
    lookback_display = st.session_state.get("seasonality_lookback", lookback_years)

    if all_results:
        if not api_key:
            st.info("💡 Set `GROQ_API_KEY` or `GEMINI_API_KEY` in your `.env` file to use **AI View**.")

        for ticker, data in all_results.items():
            if "error" in data:
                st.warning(data["error"])
                continue

            pivot = data["pivot"]
            stats_df = data["stats_df"]
            signals_df = data["signals_df"]
            bt_metrics = data["bt_metrics"]

            render_run_summary(summarize_seasonality(bt_metrics, ticker))

            hdr_col, ai_col = st.columns([5, 1])
            with hdr_col:
                st.markdown(f"### 📊 Seasonality Report: {ticker}")
            with ai_col:
                ai_view_button("season", ticker)

            season_market = st.session_state.get(
                "seasonality_market",
                CRYPTO_MARKET if asset_type_display == "Crypto"
                else US_MARKET if asset_type_display == "US Stocks"
                else GROWW_MARKET,
            )
            season_exchange = "NSE"
            groww_token = get_active_groww_token()
            currency = market_currency(season_market)
            render_price_extremes_for_ticker(
                ticker, data["df"], "1d (Seasonal)", season_market,
                exchange=season_exchange, groww_token=groww_token, currency=currency,
            )

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("CAGR (Seasonal)", f"{bt_metrics['CAGR']:.2%}")
            m2.metric("Sharpe Ratio", f"{bt_metrics['Sharpe']:.2f}")
            m3.metric("Max Drawdown", f"{bt_metrics['Max Drawdown']:.2%}")
            m4.metric("Total Return", f"{bt_metrics['Total Return']:.2%}")

            tab_heat, tab_bar, tab_bt = st.tabs(["🔥 Return Heatmap", "📊 Avg Returns & Win Rate", "📈 Strategy Backtest"])

            with tab_heat:
                heat_df = pivot * 100
                heat_df.columns = [months[m - 1] for m in heat_df.columns]
                fig_heat = px.imshow(
                    heat_df,
                    labels=dict(x="Month", y="Year", color="Return %"),
                    color_continuous_scale="RdYlGn",
                    aspect="auto",
                    title=f"{ticker} Monthly Returns (%) History",
                )
                st.plotly_chart(fig_heat, width='stretch')

            with tab_bar:
                stats_df = stats_df.copy()
                stats_df["MonthName"] = stats_df["Month"].apply(lambda x: months[x - 1])
                fig_bar = go.Figure()
                fig_bar.add_trace(go.Bar(
                    x=stats_df["MonthName"],
                    y=stats_df["Avg Return"] * 100,
                    name="Avg Return %",
                    error_y=dict(type="data", array=stats_df["Std Dev"] * 100, visible=True),
                    marker_color=["#10b981" if r > 0 else "#ef4444" for r in stats_df["Avg Return"]],
                ))
                fig_bar.update_layout(title="Average Monthly Return (%) with ±1 Std Dev", yaxis_title="Return %")
                st.plotly_chart(fig_bar, width='stretch')

                fig_win = px.bar(
                    stats_df, x="MonthName", y="Win Rate",
                    title="Probability of Positive Return (Win Rate)",
                    range_y=[0, 1], color="Win Rate", color_continuous_scale="Viridis",
                )
                fig_win.add_hline(y=0.65, line_dash="dash", line_color="green", annotation_text="Strong Buy Zone")
                fig_win.add_hline(y=0.35, line_dash="dash", line_color="red", annotation_text="Strong Sell Zone")
                st.plotly_chart(fig_win, width='stretch')

            with tab_bt:
                fig_bt = px.line(bt_metrics["Equity Curve"], y="Value", title="Seasonal Strategy Equity Growth (Start = 100)")
                st.plotly_chart(fig_bt, width='stretch')

            st.markdown("#### 📅 Seasonal Signal Calendar")
            sig_cols = st.columns(6)
            for i in range(12):
                month_num = i + 1
                month_name = months[i]
                sig = signals_df[signals_df["Month"] == month_num]
                with sig_cols[i % 6]:
                    if not sig.empty:
                        action = sig.iloc[0]["Action"]
                        win_rate = sig.iloc[0]["Win Rate"]
                        p_val = sig.iloc[0]["P-Value"]
                        color = "#10b981" if "BUY" in action else "#ef4444" if "SELL" in action else "#64748b"
                        bg = "rgba(16, 185, 129, 0.1)" if "BUY" in action else "rgba(239, 68, 68, 0.1)" if "SELL" in action else "rgba(100, 116, 139, 0.1)"
                        p_stars = "*" if p_val < 0.05 else "**" if p_val < 0.01 else ""
                        st.markdown(f"""
                        <div style="background:{bg}; border:1px solid {color}; padding:10px; border-radius:8px; text-align:center; margin-bottom:10px;">
                            <div style="font-size:0.75rem; color:#94a3b8;">{month_name}</div>
                            <div style="font-size:0.85rem; font-weight:700; color:{color};">{action}</div>
                            <div style="font-size:0.7rem; color:#cbd5e1;">WR: {win_rate:.0%}{p_stars}</div>
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        st.markdown(f"""
                        <div style="background:rgba(0,0,0,0.2); border:1px solid #1e293b; padding:10px; border-radius:8px; text-align:center; margin-bottom:10px;">
                            <div style="font-size:0.75rem; color:#475569;">{month_name}</div>
                            <div style="font-size:0.85rem; font-weight:700; color:#475569;">N/A</div>
                        </div>
                        """, unsafe_allow_html=True)

            st.markdown("#### 🏆 Top 3 Strongest Seasonal Windows")
            top_3 = signals_df.assign(abs_strength=abs(signals_df["Strength"])).sort_values(
                by=["abs_strength", "Win Rate"], ascending=False,
            ).head(3)
            for _, row in top_3.iterrows():
                m_name = months[int(row["Month"]) - 1]
                sig_text = "Bullish" if row["Strength"] > 0 else "Bearish"
                st.success(
                    f"**{m_name}** is the strongest **{sig_text}** period with a "
                    f"**{row['Win Rate']:.1%}** consistency over the last {lookback_display} years."
                )

            render_ai_view_report(
                "season", ticker, ticker, "Seasonal",
                lambda t=ticker, s=stats_df, sig=signals_df, b=bt_metrics: build_seasonality_ai_prompt(
                    t, s, sig, b, lookback_display, asset_type_display,
                ),
                SEASONALITY_AI_SYSTEM, provider, model, api_key,
            )
            st.markdown("---")

    elif not run_scan:
        st.info("👈 Select tickers and click **Run Seasonality Analysis** to begin. This tool analyzes cyclic patterns based on historical monthly performance data.")

    if st.session_state.get("seasonality_results"):
        from app.market_pulse.ask_ai_context import snapshot_section_for_ask_ai
        snapshot_section_for_ask_ai("seasonality")
