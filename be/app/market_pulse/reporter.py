"""
reporter.py
-----------
Generates extremely premium, self-contained, responsive HTML reports with 
Tailwind CSS and Chart.js embedded, saved to /truebacktest_output.
"""

import os
from datetime import datetime
import json
import pandas as pd

def generate_html_report(results: dict,
                         ticker: str,
                         market: str,
                         timeframe: str,
                         start_date: str,
                         end_date: str,
                         initial_capital: float,
                         commission: float,
                         slippage: float,
                         indicator_configs: list,
                         entry_rules: list,
                         exit_rules: list,
                         sl_pct: float,
                         tp_pct: float) -> str:
    """
    Generates a professional HTML report and saves it.
    Returns the path to the saved file.
    """
    metrics = results["metrics"]
    trades_df = results["trades"]
    equity_curve = results["equity_curve"]
    
    # Create output dir
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_dir = os.path.join(base_dir, "truebacktest_output")
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_ticker = ticker.replace("-", "_").replace("/", "_")
    filename = f"report_{safe_ticker}_{timeframe}_{timestamp}.html"
    file_path = os.path.join(output_dir, filename)
    
    # Prepare data for Chart.js
    labels = [str(d) for d in equity_curve.index]
    equity_data = list(equity_curve.values)
    
    # Calculate daily drawdowns
    rolling_max = equity_curve.cummax()
    drawdown_data = list(((equity_curve - rolling_max) / rolling_max * 100).values)
    
    # Format trade log rows
    trades_rows = ""
    if not trades_df.empty:
        for idx, row in trades_df.iterrows():
            pnl_color = "text-emerald-400" if row["pnl_val"] > 0 else "text-rose-400"
            pnl_prefix = "+" if row["pnl_val"] > 0 else ""
            trades_rows += f"""
            <tr class="border-b border-slate-800 hover:bg-slate-850 transition-colors">
                <td class="px-4 py-3 font-mono text-sm text-slate-300">{idx + 1}</td>
                <td class="px-4 py-3 font-mono text-sm text-slate-300">{row["entry_date"]}</td>
                <td class="px-4 py-3 font-mono text-sm text-slate-300">{row["exit_date"]}</td>
                <td class="px-4 py-3 font-mono text-sm text-slate-300">{row["entry_price"]:,.2f}</td>
                <td class="px-4 py-3 font-mono text-sm text-slate-300">{row["exit_price"]:,.2f}</td>
                <td class="px-4 py-3 font-mono text-sm text-slate-300">{row["shares"]:.4f}</td>
                <td class="px-4 py-3 font-mono text-sm font-semibold {pnl_color}">{pnl_prefix}{row["pnl_val"]:,.2f}</td>
                <td class="px-4 py-3 font-mono text-sm font-semibold {pnl_color}">{pnl_prefix}{row["pnl_pct"]:.2f}%</td>
                <td class="px-4 py-3 font-mono text-sm text-slate-300">{row["duration_days"]}</td>
                <td class="px-4 py-3 text-sm"><span class="px-2 py-0.5 rounded text-xs font-semibold bg-slate-800 text-slate-300">{row["exit_reason"]}</span></td>
            </tr>
            """
    else:
        trades_rows = """
        <tr>
            <td colspan="10" class="px-4 py-8 text-center text-slate-500">No trades executed during backtest period</td>
        </tr>
        """
        
    # Format indicator configurations list
    ind_badges = ""
    for config in indicator_configs:
        badge_text = f"{config['type'].upper()} ({config.get('period', '')}"
        if 'multiplier' in config:
            badge_text += f", {config['multiplier']}"
        elif 'std_dev' in config:
            badge_text += f", {config['std_dev']}"
        badge_text += ")"
        ind_badges += f"""
        <span class="inline-block px-3 py-1 mr-2 mb-2 rounded bg-indigo-900/40 text-indigo-300 border border-indigo-800/40 font-mono text-xs font-semibold">{badge_text}</span>
        """
        
    # Format entry rules list
    entry_rules_html = ""
    for r in entry_rules:
        entry_rules_html += f"""
        <div class="flex items-center space-x-2 py-1.5 border-b border-slate-850">
            <span class="text-slate-400 font-mono text-sm">{r['left']}</span>
            <span class="text-emerald-400 font-semibold px-1">{r['op']}</span>
            <span class="text-slate-300 font-mono text-sm">{r['right_val']}</span>
        </div>
        """
    if not entry_rules:
        entry_rules_html = "<div class='text-slate-550 italic text-sm'>No entry rules defined.</div>"
        
    # Format exit rules list
    exit_rules_html = ""
    for r in exit_rules:
        exit_rules_html += f"""
        <div class="flex items-center space-x-2 py-1.5 border-b border-slate-850">
            <span class="text-slate-400 font-mono text-sm">{r['left']}</span>
            <span class="text-rose-400 font-semibold px-1">{r['op']}</span>
            <span class="text-slate-300 font-mono text-sm">{r['right_val']}</span>
        </div>
        """
    if not exit_rules:
        exit_rules_html = "<div class='text-slate-550 italic text-sm'>No signal-based exit rules defined.</div>"

    # HTML Template
    html_content = f"""<!DOCTYPE html>
<html lang="en" class="h-full bg-slate-950 text-slate-100">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Backtest Report: {ticker}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <script>
        tailwind.config = {{
            theme: {{
                extend: {{
                    colors: {{
                        slate: {{
                            850: '#1e293b80',
                            950: '#020617',
                        }}
                    }}
                }}
            }}
        }}
    </script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Outfit:wght@300;400;500;600;700&display=swap');
        body {{
            font-family: 'Outfit', sans-serif;
        }}
        pre, code, .font-mono {{
            font-family: 'JetBrains Mono', monospace;
        }}
    </style>
</head>
<body class="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 py-10 px-4 md:px-8">
    <div class="max-w-7xl mx-auto space-y-8">
        
        <!-- Header -->
        <div class="flex flex-col md:flex-row justify-between items-start md:items-center p-8 bg-slate-900/60 border border-slate-800 rounded-2xl backdrop-blur-md">
            <div>
                <div class="flex items-center space-x-3">
                    <span class="px-2.5 py-1 text-xs font-bold uppercase tracking-wider rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">{market}</span>
                    <span class="px-2.5 py-1 text-xs font-bold uppercase tracking-wider rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">{timeframe}</span>
                </div>
                <h1 class="text-3xl font-extrabold text-white mt-3 font-mono tracking-tight">{ticker} Backtest Report</h1>
                <p class="text-slate-400 mt-1 text-sm"><i class="far fa-calendar-alt mr-2"></i> {start_date} &rarr; {end_date}</p>
            </div>
            <div class="mt-4 md:mt-0 text-left md:text-right font-mono text-xs text-slate-500 space-y-1">
                <p>Report Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
                <p>Engine Version: TrueBacktester v1.2</p>
            </div>
        </div>

        <!-- Metrics Grid -->
        <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <div class="p-6 bg-slate-900/40 border border-slate-800/80 rounded-2xl">
                <div class="text-xs font-semibold text-slate-400 uppercase tracking-wider">Total Return</div>
                <div class="text-3xl font-bold mt-2 font-mono text-emerald-400">+{metrics["total_return_pct"]}%</div>
                <div class="text-xs text-slate-500 mt-1">Final: {metrics["final_capital"]:,.2f}</div>
            </div>
            <div class="p-6 bg-slate-900/40 border border-slate-800/80 rounded-2xl">
                <div class="text-xs font-semibold text-slate-400 uppercase tracking-wider">CAGR</div>
                <div class="text-3xl font-bold mt-2 font-mono text-indigo-400">{metrics["cagr_pct"]}%</div>
                <div class="text-xs text-slate-500 mt-1">Compounded Annual Return</div>
            </div>
            <div class="p-6 bg-slate-900/40 border border-slate-800/80 rounded-2xl">
                <div class="text-xs font-semibold text-slate-400 uppercase tracking-wider">Sharpe Ratio</div>
                <div class="text-3xl font-bold mt-2 font-mono text-sky-400">{metrics["sharpe_ratio"]}</div>
                <div class="text-xs text-slate-500 mt-1">Risk Adjusted Standard</div>
            </div>
            <div class="p-6 bg-slate-900/40 border border-slate-800/80 rounded-2xl">
                <div class="text-xs font-semibold text-slate-400 uppercase tracking-wider">Max Drawdown</div>
                <div class="text-3xl font-bold mt-2 font-mono text-rose-500">{metrics["max_drawdown_pct"]}%</div>
                <div class="text-xs text-slate-500 mt-1">Calmar Ratio: {metrics["calmar_ratio"]}</div>
            </div>
            <div class="p-6 bg-slate-900/40 border border-slate-800/80 rounded-2xl">
                <div class="text-xs font-semibold text-slate-400 uppercase tracking-wider">Profit Factor</div>
                <div class="text-3xl font-bold mt-2 font-mono text-amber-400">{metrics["profit_factor"]}</div>
                <div class="text-xs text-slate-500 mt-1">Gross Profit / Gross Loss</div>
            </div>
            <div class="p-6 bg-slate-900/40 border border-slate-800/80 rounded-2xl">
                <div class="text-xs font-semibold text-slate-400 uppercase tracking-wider">Win Rate</div>
                <div class="text-3xl font-bold mt-2 font-mono text-emerald-400">{metrics["win_rate_pct"]}%</div>
                <div class="text-xs text-slate-500 mt-1">Of {metrics["n_trades"]} total trades</div>
            </div>
            <div class="p-6 bg-slate-900/40 border border-slate-800/80 rounded-2xl">
                <div class="text-xs font-semibold text-slate-400 uppercase tracking-wider">Avg Win / Loss</div>
                <div class="text-2xl font-bold mt-2.5 font-mono text-slate-200">+{metrics["avg_win_pct"]}% / {metrics["avg_loss_pct"]}%</div>
                <div class="text-xs text-slate-500 mt-1">Best Trade: +{metrics["best_trade_pct"]}%</div>
            </div>
            <div class="p-6 bg-slate-900/40 border border-slate-800/80 rounded-2xl">
                <div class="text-xs font-semibold text-slate-400 uppercase tracking-wider">Avg Hold Duration</div>
                <div class="text-3xl font-bold mt-2 font-mono text-slate-200">{metrics["avg_hold_days"]} <span class="text-xs text-slate-400 font-sans">Days</span></div>
                <div class="text-xs text-slate-500 mt-1">Worst Trade: {metrics["worst_trade_pct"]}%</div>
            </div>
        </div>

        <!-- Strategy Logic Details -->
        <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div class="md:col-span-1 p-6 bg-slate-900/40 border border-slate-800/80 rounded-2xl space-y-4">
                <h3 class="text-lg font-bold text-white"><i class="fas fa-sliders-h text-indigo-400 mr-2"></i> Custom Indicators</h3>
                <div class="flex flex-wrap pt-2">
                    {ind_badges}
                </div>
                <div class="border-t border-slate-800/60 pt-4 space-y-2">
                    <p class="text-xs font-semibold uppercase text-slate-500">Capital Protection Settings</p>
                    <p class="text-sm font-mono"><span class="text-slate-400">Stop Loss (SL):</span> <span class="font-semibold text-rose-400">{sl_pct}%</span></p>
                    <p class="text-sm font-mono"><span class="text-slate-400">Take Profit (TP):</span> <span class="font-semibold text-emerald-400">{tp_pct}%</span></p>
                    <p class="text-xs text-slate-500 mt-1">Brokerage & Slippage: {commission*100:.2f}% / {slippage*100:.2f}%</p>
                </div>
            </div>
            <div class="p-6 bg-slate-900/40 border border-slate-800/80 rounded-2xl space-y-3">
                <h3 class="text-lg font-bold text-white"><i class="fas fa-sign-in-alt text-emerald-400 mr-2"></i> Entry rules (BUY)</h3>
                <div class="space-y-1 mt-2">
                    {entry_rules_html}
                </div>
            </div>
            <div class="p-6 bg-slate-900/40 border border-slate-800/80 rounded-2xl space-y-3">
                <h3 class="text-lg font-bold text-white"><i class="fas fa-sign-out-alt text-rose-400 mr-2"></i> Exit rules (SELL)</h3>
                <div class="space-y-1 mt-2">
                    {exit_rules_html}
                </div>
            </div>
        </div>

        <!-- Equity Curve Chart -->
        <div class="p-6 bg-slate-900/40 border border-slate-800/80 rounded-2xl">
            <h3 class="text-xl font-bold text-white mb-6 font-mono"><i class="fas fa-chart-line text-indigo-400 mr-2"></i> Portfolio Equity Curve</h3>
            <div class="h-96 w-full">
                <canvas id="equityChart"></canvas>
            </div>
        </div>

        <!-- Trades Log -->
        <div class="p-6 bg-slate-900/40 border border-slate-800/80 rounded-2xl">
            <h3 class="text-xl font-bold text-white mb-6 font-mono"><i class="fas fa-list text-indigo-400 mr-2"></i> Execution Trade Log</h3>
            <div class="overflow-x-auto">
                <table class="w-full text-left border-collapse">
                    <thead>
                        <tr class="border-b border-slate-800 text-xs font-bold text-slate-400 uppercase bg-slate-900/40">
                            <th class="px-4 py-3">#</th>
                            <th class="px-4 py-3">Entry Date</th>
                            <th class="px-4 py-3">Exit Date</th>
                            <th class="px-4 py-3">Entry Price</th>
                            <th class="px-4 py-3">Exit Price</th>
                            <th class="px-4 py-3">Shares</th>
                            <th class="px-4 py-3">P&L ($ / ₹)</th>
                            <th class="px-4 py-3">P&L (%)</th>
                            <th class="px-4 py-3">Hold Days</th>
                            <th class="px-4 py-3">Exit trigger</th>
                        </tr>
                    </thead>
                    <tbody>
                        {trades_rows}
                    </tbody>
                </table>
            </div>
        </div>

    </div>

    <!-- Chart JS Initialization Script -->
    <script>
        const ctx = document.getElementById('equityChart').getContext('2d');
        const labels = {json.dumps(labels)};
        const equityData = {json.dumps(equity_data)};
        const ddData = {json.dumps(drawdown_data)};

        new Chart(ctx, {{
            type: 'line',
            data: {{
                labels: labels,
                datasets: [
                    {{
                        label: 'Portfolio Equity',
                        data: equityData,
                        borderColor: '#00d09c',
                        backgroundColor: 'rgba(0, 208, 156, 0.05)',
                        borderWidth: 2.5,
                        fill: true,
                        yAxisID: 'y',
                        tension: 0.15,
                        pointRadius: 0
                    }},
                    {{
                        label: 'Drawdown %',
                        data: ddData,
                        borderColor: '#ef4444',
                        backgroundColor: 'rgba(239, 68, 68, 0.03)',
                        borderWidth: 1.5,
                        fill: true,
                        yAxisID: 'y1',
                        tension: 0.1,
                        pointRadius: 0,
                        borderDash: [5, 5]
                    }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                interaction: {{
                    mode: 'index',
                    intersect: false,
                }},
                scales: {{
                    x: {{
                        grid: {{
                            color: '#1e293b40',
                        }},
                        ticks: {{
                            color: '#64748b',
                            font: {{ family: 'JetBrains Mono', size: 10 }}
                        }}
                    }},
                    y: {{
                        type: 'linear',
                        display: true,
                        position: 'left',
                        grid: {{
                            color: '#1e293b60',
                        }},
                        ticks: {{
                            color: '#00d09c',
                            font: {{ family: 'JetBrains Mono', size: 10 }}
                        }}
                    }},
                    y1: {{
                        type: 'linear',
                        display: true,
                        position: 'right',
                        grid: {{
                            drawOnChartArea: false,
                        }},
                        ticks: {{
                            color: '#ef4444',
                            font: {{ family: 'JetBrains Mono', size: 10 }}
                        }}
                    }}
                }},
                plugins: {{
                    legend: {{
                        labels: {{
                            color: '#94a3b8',
                            font: {{ family: 'Outfit', size: 12 }}
                        }}
                    }}
                }}
            }}
        }});
    </script>
</body>
</html>
"""
    with open(file_path, "w", encoding="utf-8") as f_out:
        f_out.write(html_content)
        
    return file_path

def generate_sentiment_html_report(
    valid_sent: pd.DataFrame,
    market: str,
    tickers: list,
    timeframes: list
) -> str:
    """
    Generates a professional HTML report for the Market Sentiment Scanner.
    Returns the path to the saved file.
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_dir = os.path.join(base_dir, "truebacktest_output")
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_market = market.replace(" ", "_").replace("(", "").replace(")", "").replace("-", "_")
    filename = f"sentiment_report_{safe_market}_{timestamp}.html"
    file_path = os.path.join(output_dir, filename)

    def get_overall_rating(avg_score):
        if avg_score >= 65: return "🔥 STRONG BUY / VERY BULLISH"
        elif avg_score >= 35: return "📈 BUY / BULLISH"
        elif avg_score >= 10: return "🟢 LEAN BULLISH"
        elif avg_score <= -65: return "💀 STRONG SELL / VERY BEARISH"
        elif avg_score <= -35: return "📉 SELL / BEARISH"
        elif avg_score <= -10: return "🔴 LEAN BEARISH"
        else: return "⚖️ NEUTRAL"

    df_grouped = valid_sent.groupby("Ticker").apply(lambda g: pd.Series({
        "Avg_Score": g["Score"].mean(),
        "Bullish_Count": (g["Score"] >= 10).sum(),
        "Bearish_Count": (g["Score"] <= -10).sum(),
        "Total_Scans": len(g),
        "Bullish_Timeframes": ", ".join(g[g["Score"] >= 10]["Timeframe"].tolist()),
        "Bearish_Timeframes": ", ".join(g[g["Score"] <= -10]["Timeframe"].tolist()),
        "Key_Reasons": " | ".join(list(dict.fromkeys([i for sublist in g["Insights"].tolist() for i in sublist]))[:3])
    })).reset_index()

    df_grouped["Overall Rating"] = df_grouped["Avg_Score"].apply(get_overall_rating)
    df_grouped["Avg_Score"] = df_grouped["Avg_Score"].round(1)
    
    df_overall_bullish = df_grouped.sort_values(by="Avg_Score", ascending=False)
    
    # Format Leaderboard Rows
    leaderboard_rows = ""
    for idx, row in df_overall_bullish.iterrows():
        color_class = "text-emerald-400" if row["Avg_Score"] > 0 else "text-rose-400" if row["Avg_Score"] < 0 else "text-slate-400"
        leaderboard_rows += f"""
        <tr class="border-b border-slate-800 hover:bg-slate-850 transition-colors">
            <td class="px-4 py-3 font-mono text-sm text-white font-bold">{{row["Ticker"]}}</td>
            <td class="px-4 py-3 font-mono text-sm font-semibold {{color_class}}">{{row["Avg_Score"]}}%</td>
            <td class="px-4 py-3 text-sm text-slate-300">{{row["Overall Rating"]}}</td>
            <td class="px-4 py-3 text-sm text-slate-300">{{row["Bullish_Count"]}}/{{row["Total_Scans"]}} <span class="text-xs text-slate-500">({{row["Bullish_Timeframes"]}})</span></td>
            <td class="px-4 py-3 text-sm text-slate-300">{{row["Bearish_Count"]}}/{{row["Total_Scans"]}} <span class="text-xs text-slate-500">({{row["Bearish_Timeframes"]}})</span></td>
            <td class="px-4 py-3 text-xs text-slate-400">{{row["Key_Reasons"]}}</td>
        </tr>
        """
        
    full_data_rows = ""
    for idx, row in valid_sent.sort_values(by=["Ticker", "Score"], ascending=[True, False]).iterrows():
        color_class = "text-emerald-400" if row["Score"] > 0 else "text-rose-400" if row["Score"] < 0 else "text-slate-400"
        trade_sig = row.get("Trade Signal", "N/A")
        sig_class = "text-emerald-400" if trade_sig == "BUY" else ("text-rose-400" if trade_sig == "SELL" else "text-amber-400")
        sl_val = row.get('SL %', 0.0)
        tp_val = row.get('TP %', 0.0)
        atr_val = row.get('ATR %', 0.0)
        adx_val = row.get('ADX', 0.0)
        trend_val = row.get('Trend', 'N/A')
        insights_html = "<ul class='list-disc pl-4'>"
        for insight in row["Insights"]:
            insights_html += f"<li>{{insight}}</li>"
        insights_html += "</ul>"
        
        full_data_rows += f"""
        <tr class="border-b border-slate-800 hover:bg-slate-850 transition-colors">
            <td class="px-4 py-3 font-mono text-sm text-white font-bold">{{row["Ticker"]}}</td>
            <td class="px-4 py-3 font-mono text-sm text-slate-300">{{row["Timeframe"]}}</td>
            <td class="px-4 py-3 font-mono text-sm font-semibold {{color_class}}">{{row["Score"]}}%</td>
            <td class="px-4 py-3 text-sm text-slate-300">{{row["Rating"]}}</td>
            <td class="px-4 py-3 font-mono text-sm font-bold {{sig_class}}">{{trade_sig}}</td>
            <td class="px-4 py-3 font-mono text-sm text-slate-300">{{sl_val:.2f}}%</td>
            <td class="px-4 py-3 font-mono text-sm text-slate-300">{{tp_val:.2f}}%</td>
            <td class="px-4 py-3 font-mono text-sm text-slate-300">{{atr_val:.2f}}%</td>
            <td class="px-4 py-3 font-mono text-sm text-slate-300">{{row["RSI"]:.1f}}</td>
            <td class="px-4 py-3 font-mono text-sm text-slate-300">{{adx_val:.1f}}</td>
            <td class="px-4 py-3 font-mono text-sm text-slate-300">{{trend_val}}</td>
            <td class="px-4 py-3 font-mono text-sm text-slate-300">{{row["Vol Ratio"]:.2f}}</td>
            <td class="px-4 py-3 text-xs text-slate-400">{{insights_html}}</td>
        </tr>
        """

    # HTML Template
    html_content = f"""<!DOCTYPE html>
<html lang="en" class="h-full bg-slate-950 text-slate-100">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Market Sentiment Report: {{market}}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <script>
        tailwind.config = {{{{
            theme: {{{{
                extend: {{{{
                    colors: {{{{
                        slate: {{{{
                            850: '#1e293b80',
                            950: '#020617',
                        }}}}
                    }}}}
                }}}}
            }}}}
        }}}}
    </script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Outfit:wght@300;400;500;600;700&display=swap');
        body {{{{ font-family: 'Outfit', sans-serif; }}}}
        pre, code, .font-mono {{{{ font-family: 'JetBrains Mono', monospace; }}}}
    </style>
</head>
<body class="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 py-10 px-4 md:px-8">
    <div class="max-w-7xl mx-auto space-y-8">
        
        <!-- Header -->
        <div class="flex flex-col md:flex-row justify-between items-start md:items-center p-8 bg-slate-900/60 border border-slate-800 rounded-2xl backdrop-blur-md">
            <div>
                <div class="flex items-center space-x-3">
                    <span class="px-2.5 py-1 text-xs font-bold uppercase tracking-wider rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">SENTIMENT SCANNER</span>
                    <span class="px-2.5 py-1 text-xs font-bold uppercase tracking-wider rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">{{market}}</span>
                </div>
                <h1 class="text-3xl font-extrabold text-white mt-3 font-mono tracking-tight">Market Sentiment Report</h1>
                <p class="text-slate-400 mt-1 text-sm"><i class="fas fa-list mr-2"></i> {{len(tickers)}} Assets | {{len(timeframes)}} Timeframes</p>
            </div>
            <div class="mt-4 md:mt-0 text-left md:text-right font-mono text-xs text-slate-500 space-y-1">
                <p>Report Generated: {{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}}</p>
                <p>Engine Version: TrueBacktester v1.2</p>
            </div>
        </div>

        <!-- Leaderboard -->
        <div class="p-6 bg-slate-900/40 border border-slate-800/80 rounded-2xl">
            <h3 class="text-xl font-bold text-white mb-6 font-mono"><i class="fas fa-trophy text-amber-400 mr-2"></i> Consolidated Overall Ticker Sentiment Leaderboard</h3>
            <div class="overflow-x-auto">
                <table class="w-full text-left border-collapse">
                    <thead>
                        <tr class="border-b border-slate-800 text-xs font-bold text-slate-400 uppercase bg-slate-900/40">
                            <th class="px-4 py-3">Ticker</th>
                            <th class="px-4 py-3">Avg Score</th>
                            <th class="px-4 py-3">Overall Rating</th>
                            <th class="px-4 py-3">Bullish Alignments</th>
                            <th class="px-4 py-3">Bearish Alignments</th>
                            <th class="px-4 py-3">Key Reasons (Top Insights)</th>
                        </tr>
                    </thead>
                    <tbody>
                        {{leaderboard_rows}}
                    </tbody>
                </table>
            </div>
        </div>
        
        <!-- Detailed Breakdown -->
        <div class="p-6 bg-slate-900/40 border border-slate-800/80 rounded-2xl">
            <h3 class="text-xl font-bold text-white mb-6 font-mono"><i class="fas fa-search text-sky-400 mr-2"></i> Detailed Sentiment Breakdown</h3>
            <div class="overflow-x-auto">
                <table class="w-full text-left border-collapse">
                    <thead>
                        <tr class="border-b border-slate-800 text-xs font-bold text-slate-400 uppercase bg-slate-900/40">
                            <th class="px-4 py-3">Ticker</th>
                            <th class="px-4 py-3">Timeframe</th>
                            <th class="px-4 py-3">Score</th>
                            <th class="px-4 py-3">Rating</th>
                            <th class="px-4 py-3">Trade Signal</th>
                            <th class="px-4 py-3">SL %</th>
                            <th class="px-4 py-3">TP %</th>
                            <th class="px-4 py-3">ATR %</th>
                            <th class="px-4 py-3">RSI</th>
                            <th class="px-4 py-3">ADX</th>
                            <th class="px-4 py-3">Trend</th>
                            <th class="px-4 py-3">Vol Ratio</th>
                            <th class="px-4 py-3">Technical Insights</th>
                        </tr>
                    </thead>
                    <tbody>
                        {{full_data_rows}}
                    </tbody>
                </table>
            </div>
        </div>

    </div>
</body>
</html>
"""
    with open(file_path, "w", encoding="utf-8") as f_out:
        f_out.write(html_content)
        
    return file_path
