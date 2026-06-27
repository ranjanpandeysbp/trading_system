import pandas as pd
import numpy as np
from datetime import date, timedelta
import plotly.graph_objects as go
import json

from app.market_pulse.database import save_screener, get_screeners_by_mobile, delete_screener
from backtesting.data_fetcher import get_historical_data, POPULAR_NSE_STOCKS
from app.market_pulse.indicators import calculate_dynamic_indicators
from app.market_pulse.presets import POPULAR_CRYPTO_PAIRS
from app.market_pulse.ticker_selection_ui import (
    render_coindcx_ticker_selection,
    render_equity_index_ticker_selection,
)
from app.market_pulse.ticker_utils import (
    GROWW_MARKET,
    MARKET_OPTIONS,
    is_crypto_market,
    is_india_market,
    market_currency,
)
from app.market_pulse.price_extremes import render_price_extremes_for_ticker
from app.market_pulse.groww_auth import get_active_groww_token
from app.market_pulse.run_summary import render_run_digest, render_run_summary, summarize_screener_match
from app.market_pulse.ta_screener_ui import render_strategy_mtf_panel
from app.market_pulse.ai_view import (
    render_ai_config,
    show_ai_view_block,
    build_multi_combo_ai_prompt,
    MULTI_COMBO_AI_SYSTEM,
)

# Extended list of NIFTY 50 stocks for the screener
NIFTY_50_TICKERS = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "ITC", "SBIN", "BHARTIARTL", 
    "BAJFINANCE", "L&T", "KOTAKBANK", "AXISBANK", "HINDUNILVR", "LT", "ASIANPAINT",
    "SUNPHARMA", "MARUTI", "TITAN", "ULTRACEMCO", "NTPC", "TATASTEEL", "POWERGRID",
    "M&M", "BAJAJFINSV", "TATAMOTORS", "NESTLEIND", "ONGC", "HCLTECH", "ADANIENT",
    "JSWSTEEL", "COALINDIA", "HINDALCO", "GRASIM", "TECHM", "DRREDDY", "WIPRO", 
    "CIPLA", "APOLLOHOSP", "BAJAJ-AUTO", "BRITANNIA", "EICHERMOT", "DIVISLAB", 
    "HEROMOTOCO", "INDUSINDBK", "SBILIFE", "HDFCLIFE", "ADANIPORTS", "BPCL", "LTIM"
]

def build_advanced_chart(df: pd.DataFrame, ticker: str):
    """Builds a Plotly chart with advanced S/R, Trendlines, and SMC heuristics."""
    fig = go.Figure()

    # 1. Candlestick
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['open'], high=df['high'], low=df['low'], close=df['close'],
        name="Price", increasing_line_color='#26a69a', decreasing_line_color='#ef5350'
    ))

    # 2. Support & Resistance (Simple Extrema Heuristic)
    window = 20
    df['local_max'] = df['high'][(df['high'].shift(1) < df['high']) & (df['high'].shift(-1) < df['high'])]
    df['local_min'] = df['low'][(df['low'].shift(1) > df['low']) & (df['low'].shift(-1) > df['low'])]
    
    recent_max = df['local_max'].dropna().tail(3)
    recent_min = df['local_min'].dropna().tail(3)
    
    for val in recent_max:
        fig.add_hline(y=val, line_dash="dash", line_color="rgba(255,0,0,0.5)", annotation_text="Resistance")
    for val in recent_min:
        fig.add_hline(y=val, line_dash="dash", line_color="rgba(0,255,0,0.5)", annotation_text="Support")

    # 3. Simple Trendline (Linear Regression on last 50 bars)
    if len(df) >= 50:
        tail_df = df.tail(50).copy()
        x = np.arange(len(tail_df))
        y = tail_df['close'].values
        m, b = np.polyfit(x, y, 1)
        trend_y = m * x + b
        fig.add_trace(go.Scatter(
            x=tail_df.index, y=trend_y, mode='lines', name='Trendline',
            line=dict(color='black', width=2, dash='dot')
        ))

    # 4. Fair Value Gaps (Basic SMC)
    # FVG happens when candle 1 high < candle 3 low (Bullish FVG) or candle 1 low > candle 3 high (Bearish FVG)
    bullish_fvgs = []
    bearish_fvgs = []
    for i in range(2, len(df)):
        if df['high'].iloc[i-2] < df['low'].iloc[i]:
            bullish_fvgs.append((df.index[i-2], df.index[i], df['high'].iloc[i-2], df['low'].iloc[i]))
        if df['low'].iloc[i-2] > df['high'].iloc[i]:
            bearish_fvgs.append((df.index[i-2], df.index[i], df['low'].iloc[i-2], df['high'].iloc[i]))

    # Draw the most recent 3 FVGs
    for fvg in bullish_fvgs[-3:]:
        fig.add_shape(type="rect", x0=fvg[0], x1=fvg[1], y0=fvg[2], y1=fvg[3],
                      fillcolor="rgba(0, 255, 0, 0.2)", line_width=0, layer="below")
    for fvg in bearish_fvgs[-3:]:
        fig.add_shape(type="rect", x0=fvg[0], x1=fvg[1], y0=fvg[2], y1=fvg[3],
                      fillcolor="rgba(255, 0, 0, 0.2)", line_width=0, layer="below")

    fig.update_layout(
        title=f"Advanced Chart: {ticker}",
        template="plotly_dark",
        xaxis_rangeslider_visible=False,
        height=600,
        margin=dict(l=40, r=40, t=40, b=40)
    )
    return fig

def render_screener_tab():
    st.markdown("<h1>🔎 Advanced Sentiment & Pattern Screener</h1>", unsafe_allow_html=True)
    st.write("Scan thousands of assets to find optimal technical setups, and view SMC S/R charts.")

    # Initialize session state for screener
    if "scr_indicators" not in st.session_state:
        st.session_state.scr_indicators = [
            {"type": "ema", "period": 200},
            {"type": "rsi", "period": 14}
        ]
    if "scr_entry_rules" not in st.session_state:
        st.session_state.scr_entry_rules = [
            {"left": "close", "op": "crosses above", "right_type": "indicator", "right_val": "ema_200"},
            {"left": "rsi_14", "op": ">", "right_type": "value", "right_val": "50.0"}
        ]
    if "scr_exit_rules" not in st.session_state:
        st.session_state.scr_exit_rules = []
    if "screener_results" not in st.session_state:
        st.session_state.screener_results = {}
    if "scr_active_name" not in st.session_state:
        st.session_state.scr_active_name = "Default Setup (200 EMA + RSI > 50)"

    st.markdown("---")
    col_preset, col_saved = st.columns(2)
    
    with col_preset:
        st.markdown("### 🏆 Load Top Strategy Templates")
        try:
            from app.market_pulse.presets import get_presets_for_market
            current_market = st.session_state.get("scr_market_select", GROWW_MARKET)
            available_presets = get_presets_for_market(current_market)
            preset_names = list(available_presets.keys())
            
            selected_preset = st.selectbox("Select Popular Intraday/Swing Setup", preset_names, key="scr_preset_sel")
            if st.button("LOAD TEMPLATE", width='stretch', type="primary"):
                preset_data = available_presets[selected_preset]
                st.session_state.scr_indicators = preset_data["indicators"]
                st.session_state.scr_entry_rules = preset_data["entry_rules"]
                st.session_state.scr_exit_rules = preset_data.get("exit_rules", [])
                st.session_state.scr_active_name = selected_preset
                
                st.toast(f"Loaded '{selected_preset}'!", icon="🏆")
                st.rerun()
        except ImportError:
            st.warning("Presets module not found.")

    with col_saved:
        st.markdown("### 💾 Load Personal Saved Screener")
        load_mobile = st.session_state.get("logged_in_mobile", "")
        saved_list = get_screeners_by_mobile(load_mobile) if load_mobile else []
        scr_names = [s["name"] for s in saved_list]
        selected_scr = st.selectbox(
            "Select Saved Screener",
            scr_names if scr_names else ["No screeners found"],
            key="scr_load_sel",
        )
            
        if st.button("LOAD PERSONAL SCREENER", width='stretch') and saved_list and selected_scr != "No screeners found":
            scr_data = next(s for s in saved_list if s["name"] == selected_scr)
            st.session_state.scr_indicators = json.loads(scr_data["indicators"])
            st.session_state.scr_entry_rules = json.loads(scr_data["entry_rules"])
            st.session_state.scr_exit_rules = json.loads(scr_data["exit_rules"])
            st.session_state.scr_active_name = selected_scr
            st.toast(f"Loaded '{selected_scr}'!", icon="✅")
            st.rerun()
            
    st.markdown("---")

    col_target, col_time = st.columns(2)

    with col_target:
        scr_market = st.selectbox(
            "🌐 Top/Bottom Analysis Market",
            MARKET_OPTIONS,
            index=0,
            key="scr_market_select"
        )

        st.markdown("### 📈 Select Assets to Analyze")
        scr_tickers = []
        scr_groww_exchange = "NSE"
        scr_index_sel = "Custom"

        if is_crypto_market(scr_market):
            scr_tickers = render_coindcx_ticker_selection("scr")
        else:
            if is_india_market(scr_market):
                scr_groww_exchange = st.selectbox("EXCHANGE", ["NSE", "BSE"], index=0, key="scr_groww_ex")
            scr_tickers = render_equity_index_ticker_selection(scr_market, "scr")
                    
        # Update references for the rest of the code
        market = scr_market
        exchange = scr_groww_exchange if is_india_market(market) else "NSE"
        index_sel = scr_index_sel if is_india_market(market) else st.session_state.get("scr_coindcx_mode", "Top by Volume")
        tickers_to_scan = scr_tickers

    with col_time:
        st.markdown("### ⏱️ Time Durations & Data Detail")
        from app.market_pulse.ta_mtf_hub_ui import render_ta_multiselect_timeframes

        scr_timeframes = render_ta_multiselect_timeframes(
            "scr",
            ["1m", "5m", "15m", "30m", "1h", "4h", "1d"],
            legacy_default=["1d"],
            label="Choose Timeframes to Scan",
        )
        lookback = st.slider(
            "Candlestick Back-History Lookback",
            min_value=50,
            max_value=1500,
            value=200,
            step=50,
            key="scr_lookback_slider"
        )
        
        groww_token = get_active_groww_token()
        if is_india_market(scr_market):
            if groww_token and groww_token.strip():
                st.success("🌐 **Data Source: Groww API**")
            else:
                st.info("ℹ️ **Data Source: Yahoo Finance** (No Groww Bearer token in sidebar)")
        elif is_crypto_market(scr_market):
            st.info("🌐 **Data Source: CoinDCX Futures API**")
        else:
            st.info("🌐 **Data Source: Yahoo Finance (US Stocks)**")

    st.markdown("---")
    
    col_builder_left, col_builder_right = st.columns([1, 1])

    # Helper for dropdowns
    def get_indicator_column_names(configs):
        cols = ["open", "high", "low", "close", "volume"]
        for c in configs:
            t = c["type"].lower()
            if t in ["ema", "sma", "rsi", "atr"]: cols.append(f"{t}_{c['period']}")
            elif t == "bb":
                cols.append(f"bb_upper_{c['period']}_{c['std_dev']}")
                cols.append(f"bb_lower_{c['period']}_{c['std_dev']}")
            elif t == "macd":
                cols.append(f"macd_{c['fast']}_{c['slow']}")
                cols.append(f"macd_signal_{c['fast']}_{c['slow']}_{c['signal']}")
        return list(dict.fromkeys(cols))

    indicator_options = get_indicator_column_names(st.session_state.scr_indicators)

    # 1. Indicators Builder
    with col_builder_left:
        st.markdown("### 📊 1. Technical Indicators Builder")
        with st.expander("🛠️ Construct New Indicator", expanded=False):
            ind_type = st.selectbox("Indicator Name", ["EMA", "SMA", "RSI", "Bollinger Bands", "MACD", "ATR"], key="scr_ind_type")
            params = {}
            if ind_type in ["EMA", "SMA", "RSI", "ATR"]:
                params["period"] = st.number_input("Lookback window", min_value=1, max_value=500, value=14, key="scr_ind_p")
            elif ind_type == "Bollinger Bands":
                params["period"] = st.number_input("Lookback window", value=20, key="scr_bb_p")
                params["std_dev"] = st.number_input("Std Deviation", value=2.0, step=0.1, key="scr_bb_std")
            elif ind_type == "MACD":
                params["fast"] = st.number_input("Fast", value=12, key="scr_macd_f")
                params["slow"] = st.number_input("Slow", value=26, key="scr_macd_s")
                params["signal"] = st.number_input("Signal", value=9, key="scr_macd_sig")

            if st.button("➕ Add Selected Indicator", key="scr_add_ind"):
                new_ind = {"type": ind_type.lower().replace("bollinger bands", "bb")}
                new_ind.update(params)
                st.session_state.scr_indicators.append(new_ind)
                st.rerun()

        st.markdown("#### Configured Indicators List")
        for idx, ind in enumerate(st.session_state.scr_indicators):
            c1, c2 = st.columns([5, 1])
            with c1: st.code(f"{ind['type'].upper()} Config: {ind}")
            with c2:
                if st.button("🗑️", key=f"scr_del_ind_{idx}"):
                    st.session_state.scr_indicators.pop(idx)
                    st.rerun()

    # 2. Rules Builder
    with col_builder_right:
        st.markdown("### ⚙️ 2. Entry & Exit Rules Builder")
        entry_mode = st.radio("Entry Conditions Match Rule", ["Match ALL rules (AND)", "Match ANY rule (OR)"], index=0, horizontal=True, key="scr_em")
        exit_mode = st.radio("Exit Conditions Match Rule", ["Match ALL rules (AND)", "Match ANY rule (OR)"], index=0, horizontal=True, key="scr_xm")
        
        with st.expander("🚦 Construct Rule Set Condition", expanded=False):
            rule_type = st.selectbox("Action Target", ["Entry Rule (BUY)", "Exit Rule (SELL)"], key="scr_rt")
            r_col1, r_col2, r_col3 = st.columns([2, 1, 2])
            with r_col1: left_side = st.selectbox("Left Operand", indicator_options, key="scr_ls")
            with r_col2: operator = st.selectbox("Math Operator", [">", "<", "==", ">=", "<=", "crosses above", "crosses below"], key="scr_op")
            with r_col3:
                right_type = st.radio("Right Target Type", ["value", "indicator"], index=0, horizontal=True, key="scr_rt_type")
                if right_type == "value": right_val = st.text_input("Float Value", value="50.0", key="scr_rv_val")
                else: right_val = st.selectbox("Right Operand", indicator_options, key="scr_rv_ind")
                    
            if st.button("➕ Add Built Rule", key="scr_add_rule"):
                rule_dict = {"left": left_side, "op": operator, "right_type": right_type, "right_val": right_val}
                if rule_type == "Entry Rule (BUY)": st.session_state.scr_entry_rules.append(rule_dict)
                else: st.session_state.scr_exit_rules.append(rule_dict)
                st.rerun()

        st.markdown("#### Entry Rules (Long)")
        for idx, r in enumerate(st.session_state.scr_entry_rules):
            c1, c2 = st.columns([5,1])
            with c1: st.code(f"{r['left']} {r['op']} {r['right_val']}")
            with c2: 
                if st.button("🗑️", key=f"scr_del_er_{idx}"): 
                    st.session_state.scr_entry_rules.pop(idx); st.rerun()
                    
        st.markdown("#### Exit Rules (Long)")
        for idx, r in enumerate(st.session_state.scr_exit_rules):
            c1, c2 = st.columns([5,1])
            with c1: st.code(f"{r['left']} {r['op']} {r['right_val']}")
            with c2: 
                if st.button("🗑️", key=f"scr_del_xr_{idx}"): 
                    st.session_state.scr_exit_rules.pop(idx); st.rerun()

    st.markdown("---")
    
    col_scan, col_save = st.columns([3, 1])
    with col_scan:
        scan_btn = st.button("🔍 SCAN NOW", type="primary", width='stretch')
    with col_save:
        save_btn = st.button("💾 SAVE SCREENER", width='stretch')

    if save_btn:
        st.session_state.scr_show_save = True

    if st.session_state.get("scr_show_save", False):
        st.markdown("### 💾 Save Screener Configuration")
        with st.form("save_scr_form"):
            s_name = st.text_input("Screener Name", value="My Custom Screener")
            sub = st.form_submit_button("Confirm Save")
            if sub:
                s_mob = st.session_state.get("logged_in_mobile", "")
                if s_name.strip():
                    success = save_screener(
                        s_mob, s_name.strip(), market, exchange, index_sel, scr_timeframes, lookback,
                        st.session_state.scr_indicators, st.session_state.scr_entry_rules,
                        st.session_state.scr_exit_rules, entry_mode, exit_mode,
                    )
                    if success:
                        st.success("Screener saved successfully!")
                        st.session_state.scr_show_save = False
                    else:
                        st.error("Failed to save. Name might already exist for your account.")
                else:
                    st.error("Please enter a screener name.")

    st.markdown("---")

    # Scanning Logic
    if scan_btn:
        if not tickers_to_scan or not scr_timeframes:
            st.error("Please select at least one ticker and one timeframe.")
        else:
            results = []
            
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            all_data = {}
            total_scans = len(tickers_to_scan) * len(scr_timeframes)
            scan_count = 0
            
            for tf in scr_timeframes:
                tf_to_minutes = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}
                candle_minutes = tf_to_minutes.get(tf, 1440)
                days_needed = max(7, int((lookback * candle_minutes / 1440) * 2.5) + 1)
                yf_max = {"1m": 7, "5m": 60, "15m": 60, "30m": 60, "1h": 729, "4h": 729, "1d": 3650}
                days_needed = min(days_needed, yf_max.get(tf, 3650))
                
                start_d = str(date.today() - timedelta(days=days_needed))
                end_d = str(date.today())
                
                for tick in tickers_to_scan:
                    scan_count += 1
                    status_text.text(f"Scanning {tick} on {tf} ({scan_count}/{total_scans})...")
                    try:
                        df = get_historical_data(
                            symbol=tick, start_date=start_d, end_date=end_d,
                            market=market, timeframe=tf, groww_exchange=exchange,
                            groww_token=groww_token
                        )
                        if not df.empty and len(df) > 10:
                            df = calculate_dynamic_indicators(df, st.session_state.scr_indicators)
                            
                            last_row = df.iloc[-1]
                            
                            entry_matched = []
                            for r in st.session_state.scr_entry_rules:
                                l_val = last_row.get(r['left'])
                                r_val = float(r['right_val']) if r['right_type'] == 'value' else last_row.get(r['right_val'])
                                
                                if l_val is None or r_val is None:
                                    entry_matched.append(False)
                                    continue
                                    
                                if r['op'] == '>': entry_matched.append(l_val > r_val)
                                elif r['op'] == '<': entry_matched.append(l_val < r_val)
                                elif r['op'] == '>=': entry_matched.append(l_val >= r_val)
                                elif r['op'] == '<=': entry_matched.append(l_val <= r_val)
                                elif r['op'] == '==': entry_matched.append(l_val == r_val)
                                elif 'crosses' in r['op']:
                                    prev_l = df.iloc[-2].get(r['left'])
                                    prev_r = float(r['right_val']) if r['right_type'] == 'value' else df.iloc[-2].get(r['right_val'])
                                    if prev_l is None or prev_r is None:
                                        entry_matched.append(False)
                                    elif r['op'] == 'crosses above':
                                        entry_matched.append(prev_l < prev_r and l_val > r_val)
                                    elif r['op'] == 'crosses below':
                                        entry_matched.append(prev_l > prev_r and l_val < r_val)
                                        
                            is_entry = all(entry_matched) if "ALL" in entry_mode and entry_matched else (any(entry_matched) if entry_matched else False)
                            
                            if is_entry:
                                results.append({
                                    "Ticker": tick,
                                    "Timeframe": tf,
                                    "Close": last_row['close'],
                                    "Volume": last_row['volume'],
                                    "Signal": "BUY"
                                })
                                all_data[f"{tick}_{tf}"] = df
                    except Exception as e:
                        pass
                    progress_bar.progress(scan_count / total_scans)
                
            progress_bar.empty()
            status_text.empty()
            
            formula_strs = []
            for r in st.session_state.scr_entry_rules:
                formula_strs.append(f"({r['left']} {r['op']} {r['right_val']})")
            
            logic_op = " AND " if "ALL" in entry_mode else " OR "
            formula_text = logic_op.join(formula_strs) if formula_strs else "No Entry Rules defined"
            
            st.markdown("---")
            st.markdown(f"### 📋 Scan Results: {st.session_state.get('scr_active_name', 'Custom Screener')}")
            st.info(f"**Formula Evaluated:** `{formula_text}`")
            
            if results:
                st.success(f"✅ Found {len(results)} matches!")
                scr_digest = [
                    summarize_screener_match(r["Ticker"], r["Timeframe"], r.get("Signal", "BUY"))
                    for r in results
                ]
                render_run_digest(scr_digest, title="🧭 Run Summary — Screener Matches")
                res_df = pd.DataFrame(results)
                st.dataframe(res_df, width='stretch')
                st.session_state.screener_results = all_data
                
                # AI Expert Analysis for Multi-Combo Results
                st.markdown("---")
                st.markdown("### 🤖 AI Expert Multi-Combo Analysis (Market Expert View)")
                
                ai_combo_col1, ai_combo_col2 = st.columns([1, 3])
                with ai_combo_col1:
                    show_ai_combo = st.checkbox("🤖 AI Expert for Combos", value=False, key="ai_combo_analysis")
                
                if show_ai_combo:
                    with ai_combo_col2:
                        scr_provider, scr_model, scr_api_key = render_ai_config("screener_combo")
                    
                    if scr_api_key and scr_provider:
                        # Build combo results for top 3 matches for AI analysis
                        top_results = results[:3] if len(results) > 3 else results
                        
                        def build_screener_combo_prompt():
                            combo_analysis = []
                            for result in top_results:
                                ticker = result.get('Ticker', 'N/A')
                                combo_analysis.append({
                                    'Ticker': ticker,
                                    'Score': result.get('Score', 0),
                                    'Signal': result.get('Signal', 'NEUTRAL'),
                                    'Details': [
                                        f"{k}: {v}" for k, v in result.items() 
                                        if k not in ['Ticker', 'Score', 'Signal']
                                    ][:5]
                                })
                            
                            return build_multi_combo_ai_prompt(
                                ticker="Multi-Combo Scan",
                                timeframe=st.session_state.get("scr_tf_select", "1d"),
                                combo_results=combo_analysis,
                                market=st.session_state.get("scr_market_select", "NSE")
                            )
                        
                        for i, ticker_result in enumerate(top_results, 1):
                            ticker = ticker_result.get('Ticker', f'Result_{i}')
                            st.markdown(f"**📌 Analysis for {ticker}**")
                            
                            show_ai_view_block(
                                session_prefix=f"screener_combo_{i}",
                                result_key=f"ticker_{ticker}",
                                symbol=ticker,
                                timeframe_label=st.session_state.get("scr_tf_select", "1d"),
                                build_prompt_fn=build_screener_combo_prompt,
                                system_prompt=MULTI_COMBO_AI_SYSTEM,
                                provider=scr_provider,
                                model=scr_model,
                                api_key=scr_api_key,
                                button_in_column=True
                            )
            else:
                st.warning("No tickers matched your criteria.")

    # Display Charts for Results
    if st.session_state.screener_results:
        st.markdown("### 📈 Advanced Technical Charts (Matches)")
        
        chart_tabs = st.tabs(list(st.session_state.screener_results.keys()))
        
        for i, (key, df) in enumerate(st.session_state.screener_results.items()):
            with chart_tabs[i]:
                # key is "ticker_tf"
                parts = key.rsplit("_", 1)
                tick = parts[0] if len(parts) == 2 else key.split("_")[0]
                tf = parts[1] if len(parts) == 2 else "1d"
                render_run_summary(summarize_screener_match(tick, tf), compact=True)
                scr_market = st.session_state.get("scr_market_select", GROWW_MARKET)
                scr_exchange = st.session_state.get("scr_groww_ex", "NSE")
                groww_token = get_active_groww_token()
                render_strategy_mtf_panel(
                    symbol=tick,
                    market=scr_market,
                    groww_token=groww_token,
                    exchange=scr_exchange,
                    primary_tf=tf,
                )
                currency = market_currency(scr_market)
                render_price_extremes_for_ticker(
                    tick, df, tf, scr_market, exchange=scr_exchange,
                    groww_token=groww_token, currency=currency,
                )
                fig = build_advanced_chart(df, tick)
                st.plotly_chart(fig, width='stretch')

    if st.session_state.get("screener_results"):
        from app.market_pulse.ask_ai_context import snapshot_section_for_ask_ai
        snapshot_section_for_ask_ai("screener")
