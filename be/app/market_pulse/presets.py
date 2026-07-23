"""
presets.py
----------
50 preset strategy templates organized by market (Groww India / CoinDCX Crypto)
and style (Scalping / Swing Trading).

Each preset contains:
  - indicators: list of indicator configs
  - entry_rules: list of entry rule dicts
  - exit_rules: list of exit rule dicts
  - description: human-readable explanation
  - recommended_timeframe: ideal candle interval
  - recommended_sl: stop loss %
  - recommended_tp: take profit %

Outlook presets (🔴 Bearish Open Expected / 🟢 Bullish Open Expected) pair with
Command Center tomorrow-outlook banners for Multi-Combo scans.
"""

# ===========================================================================
# GROWW INDIA — SCALPING STRATEGIES (15)
# ===========================================================================

GROWW_SCALPING = {
    "🇮🇳 [SCALP] EMA 9/21 Crossover + RSI Filter": {
        "description": "Fast EMA crossover with RSI momentum confirmation. Classic intraday scalp for liquid NSE stocks.",
        "recommended_timeframe": "5m",
        "recommended_sl": 0.8,
        "recommended_tp": 1.5,
        "indicators": [
            {"type": "ema", "period": 9},
            {"type": "ema", "period": 21},
            {"type": "rsi", "period": 14},
        ],
        "entry_rules": [
            {"left": "ema_9", "op": "crosses above", "right_type": "indicator", "right_val": "ema_21"},
            {"left": "rsi_14", "op": "<", "right_type": "value", "right_val": "65"},
        ],
        "exit_rules": [
            {"left": "ema_9", "op": "crosses below", "right_type": "indicator", "right_val": "ema_21"},
        ],
    },
    "🇮🇳 [SCALP] VWAP Bounce + RSI Oversold": {
        "description": "Buys when price bounces off VWAP and RSI is oversold. Strong mean-reversion intraday play on Nifty stocks.",
        "recommended_timeframe": "5m",
        "recommended_sl": 0.5,
        "recommended_tp": 1.0,
        "indicators": [
            {"type": "vwap"},
            {"type": "rsi", "period": 7},
        ],
        "entry_rules": [
            {"left": "close", "op": "crosses above", "right_type": "indicator", "right_val": "vwap"},
            {"left": "rsi_7", "op": "<", "right_type": "value", "right_val": "35"},
        ],
        "exit_rules": [
            {"left": "rsi_7", "op": ">", "right_type": "value", "right_val": "70"},
        ],
    },
    "🇮🇳 [SCALP] Bollinger Band Squeeze Breakout": {
        "description": "Enters when price breaks above upper Bollinger Band after a squeeze period with volume confirmation.",
        "recommended_timeframe": "5m",
        "recommended_sl": 0.7,
        "recommended_tp": 1.5,
        "indicators": [
            {"type": "bb", "period": 20, "std_dev": 2.0},
            {"type": "rsi", "period": 14},
        ],
        "entry_rules": [
            {"left": "close", "op": "crosses above", "right_type": "indicator", "right_val": "bb_upper_20_2.0"},
            {"left": "rsi_14", "op": ">", "right_type": "value", "right_val": "50"},
        ],
        "exit_rules": [
            {"left": "close", "op": "crosses below", "right_type": "indicator", "right_val": "bb_middle_20_2.0"},
        ],
    },
    "🇮🇳 [SCALP] Supertrend 7/2 Fast Scalp": {
        "description": "Uses a tight Supertrend (7, 2.0) for rapid directional signals in volatile Nifty stocks.",
        "recommended_timeframe": "3m",
        "recommended_sl": 0.5,
        "recommended_tp": 1.0,
        "indicators": [
            {"type": "supertrend", "period": 7, "multiplier": 2.0},
            {"type": "rsi", "period": 9},
        ],
        "entry_rules": [
            {"left": "supertrend_dir_7_2.0", "op": "==", "right_type": "value", "right_val": "1"},
            {"left": "rsi_9", "op": ">", "right_type": "value", "right_val": "40"},
        ],
        "exit_rules": [
            {"left": "supertrend_dir_7_2.0", "op": "==", "right_type": "value", "right_val": "-1"},
        ],
    },
    "🇮🇳 [SCALP] MACD Histogram Flip + EMA 9": {
        "description": "Enters when MACD histogram crosses from negative to positive while price is above EMA 9. Captures momentum ignition.",
        "recommended_timeframe": "5m",
        "recommended_sl": 0.6,
        "recommended_tp": 1.2,
        "indicators": [
            {"type": "macd", "fast": 12, "slow": 26, "signal": 9},
            {"type": "ema", "period": 9},
        ],
        "entry_rules": [
            {"left": "macd_hist_12_26_9", "op": "crosses above", "right_type": "value", "right_val": "0"},
            {"left": "close", "op": ">", "right_type": "indicator", "right_val": "ema_9"},
        ],
        "exit_rules": [
            {"left": "macd_hist_12_26_9", "op": "crosses below", "right_type": "value", "right_val": "0"},
        ],
    },
    "🇮🇳 [SCALP] Stochastic Oversold Bounce": {
        "description": "Classic stochastic %K/%D crossover from the oversold zone. Ideal for range-bound Nifty 50 stocks.",
        "recommended_timeframe": "5m",
        "recommended_sl": 0.5,
        "recommended_tp": 1.0,
        "indicators": [
            {"type": "stochastic", "k_period": 14, "d_period": 3},
            {"type": "ema", "period": 20},
        ],
        "entry_rules": [
            {"left": "stoch_k_14", "op": "crosses above", "right_type": "indicator", "right_val": "stoch_d_14_3"},
            {"left": "stoch_k_14", "op": "<", "right_type": "value", "right_val": "25"},
        ],
        "exit_rules": [
            {"left": "stoch_k_14", "op": ">", "right_type": "value", "right_val": "80"},
        ],
    },
    "🇮🇳 [SCALP] RSI 5 Divergence Snap": {
        "description": "Ultra-fast RSI(5) mean-reversion on extreme oversold readings. Snap trade for high-liquidity bank nifty stocks.",
        "recommended_timeframe": "1m",
        "recommended_sl": 0.3,
        "recommended_tp": 0.6,
        "indicators": [
            {"type": "rsi", "period": 5},
            {"type": "ema", "period": 9},
        ],
        "entry_rules": [
            {"left": "rsi_5", "op": "<", "right_type": "value", "right_val": "15"},
            {"left": "close", "op": ">", "right_type": "indicator", "right_val": "ema_9"},
        ],
        "exit_rules": [
            {"left": "rsi_5", "op": ">", "right_type": "value", "right_val": "55"},
        ],
    },
    "🇮🇳 [SCALP] Donchian Channel Breakout + ATR": {
        "description": "Enters on Donchian upper breakout with ATR-based volatility confirmation. Turtle trading adapted for Indian markets.",
        "recommended_timeframe": "15m",
        "recommended_sl": 1.0,
        "recommended_tp": 2.0,
        "indicators": [
            {"type": "donchian", "period": 20},
            {"type": "atr", "period": 14},
            {"type": "rsi", "period": 14},
        ],
        "entry_rules": [
            {"left": "close", "op": "crosses above", "right_type": "indicator", "right_val": "donchian_upper_20"},
            {"left": "rsi_14", "op": ">", "right_type": "value", "right_val": "50"},
        ],
        "exit_rules": [
            {"left": "close", "op": "crosses below", "right_type": "indicator", "right_val": "donchian_middle_20"},
        ],
    },
    "🇮🇳 [SCALP] EMA 5/13 + MFI Volume Pulse": {
        "description": "Tight EMA crossover with Money Flow Index confirmation. Detects institutional volume-driven micro-moves.",
        "recommended_timeframe": "5m",
        "recommended_sl": 0.5,
        "recommended_tp": 1.0,
        "indicators": [
            {"type": "ema", "period": 5},
            {"type": "ema", "period": 13},
            {"type": "mfi", "period": 14},
        ],
        "entry_rules": [
            {"left": "ema_5", "op": "crosses above", "right_type": "indicator", "right_val": "ema_13"},
            {"left": "mfi_14", "op": ">", "right_type": "value", "right_val": "40"},
        ],
        "exit_rules": [
            {"left": "ema_5", "op": "crosses below", "right_type": "indicator", "right_val": "ema_13"},
        ],
    },
    "🇮🇳 [SCALP] CCI Zero-Line Cross + SMA 20": {
        "description": "Enters when CCI crosses above zero with price above SMA 20. Momentum-based scalp for trending stocks.",
        "recommended_timeframe": "5m",
        "recommended_sl": 0.6,
        "recommended_tp": 1.2,
        "indicators": [
            {"type": "cci", "period": 20},
            {"type": "sma", "period": 20},
        ],
        "entry_rules": [
            {"left": "cci_20", "op": "crosses above", "right_type": "value", "right_val": "0"},
            {"left": "close", "op": ">", "right_type": "indicator", "right_val": "sma_20"},
        ],
        "exit_rules": [
            {"left": "cci_20", "op": "crosses below", "right_type": "value", "right_val": "100"},
        ],
    },
    "🇮🇳 [SCALP] Order Flow + Footprint Scalping": {
        "description": (
            "Intermediate · Win rate ~65–72% (live DOM/footprint; backtest uses OHLCV proxy). "
            "Core tools: DOM/L2, footprint, CVD — proxied here via VWAP zones, MFI (buying pressure), "
            "OBV/volume ratio (absorption). Timeframe: 1m–2m (preset backtest: 5m). "
            "Best: NIFTY F&O, BANKNIFTY, liquid NSE names. Sessions: 9:15–10:30, 14:30–15:30 IST. "
            "LONG: bid stacking at S/R → CVD up → price holds support → enter on rejection (close reclaims VWAP). "
            "SHORT (manual): ask absorption at resistance, CVD down while flat, exhaustion print — exit long on VWAP loss. "
            "SL: 0.12% beyond zone · T1: ~2R (0.24%) · T2: next S/R (trail via VWAP/EMA)."
        ),
        "recommended_timeframe": "5m",
        "recommended_sl": 0.12,
        "recommended_tp": 0.24,
        "indicators": [
            {"type": "vwap"},
            {"type": "mfi", "period": 14},
            {"type": "obv"},
            {"type": "vol_sma", "period": 20},
            {"type": "ema", "period": 9},
            {"type": "bb", "period": 20, "std_dev": 2.0},
        ],
        "entry_rules": [
            {"left": "close", "op": "crosses above", "right_type": "indicator", "right_val": "vwap"},
            {"left": "mfi_14", "op": "crosses above", "right_type": "value", "right_val": "50"},
            {"left": "vol_ratio_20", "op": ">", "right_type": "value", "right_val": "1.25"},
            {"left": "close", "op": ">", "right_type": "indicator", "right_val": "bb_lower_20_2.0"},
        ],
        "exit_rules": [
            {"left": "close", "op": "crosses below", "right_type": "indicator", "right_val": "vwap"},
        ],
    },
    "🇮🇳 [SCALP] VWAP Band Reversion + Trend Continuation": {
        "description": (
            "Beginner-friendly · Win rate ~60–68%. TF: 3m/5m intraday VWAP (backtest: 5m). "
            "Markets: BANKNIFTY, NIFTY50, large caps. Best: first 30m & last 60m IST; avoid 12–1PM. "
            "Indicators: VWAP + 1–2SD bands (BB proxy), EMA 9, RSI 14. "
            "REVERSION: tag -1SD band, RSI<30, volume spike → long, target VWAP, stop below band. "
            "CONTINUATION: bullish day above VWAP, pullback to VWAP/+0.5SD, EMA 9 turns up → long on close above EMA-9. "
            "⚠ Do not fade VWAP on strong trend days — if VWAP rejected 2+ times or clean break, skip reversion."
        ),
        "recommended_timeframe": "5m",
        "recommended_sl": 0.35,
        "recommended_tp": 0.75,
        "indicators": [
            {"type": "vwap"},
            {"type": "bb", "period": 20, "std_dev": 2.0},
            {"type": "ema", "period": 9},
            {"type": "rsi", "period": 14},
            {"type": "vol_sma", "period": 20},
        ],
        "entry_rules": [
            {"left": "close", "op": "crosses above", "right_type": "indicator", "right_val": "bb_lower_20_2.0"},
            {"left": "rsi_14", "op": "<", "right_type": "value", "right_val": "32"},
            {"left": "vol_ratio_20", "op": ">", "right_type": "value", "right_val": "1.2"},
        ],
        "exit_rules": [
            {"left": "close", "op": "crosses above", "right_type": "indicator", "right_val": "vwap"},
        ],
    },
    "🇮🇳 [SCALP] Opening Range Breakout (ORB) + Volume": {
        "description": (
            "Win rate ~58–65% · India equities/F&O. Range: first 15m (9:15–9:30) on 5m chart "
            "(Donchian-3 proxy). Markets: NIFTY, BANKNIFTY, large-cap NSE. "
            "Skip gap >0.3% days unless gap filled. Buy: 5m CLOSE above range high + vol >1.5× range avg. "
            "Sell breakdown (manual): close below range low with volume. "
            "Stop: range midpoint (aggressive) or opposite side (conservative). "
            "T1: measured move (range height); T2: prior day H/L. Avoid RBI/Budget/FOMC. "
            "False-break filter: retest + hold 1 candle. Max 2 ORB trades/day."
        ),
        "recommended_timeframe": "5m",
        "recommended_sl": 0.5,
        "recommended_tp": 1.0,
        "indicators": [
            {"type": "donchian", "period": 3},
            {"type": "vol_sma", "period": 20},
            {"type": "rsi", "period": 14},
        ],
        "entry_rules": [
            {"left": "close", "op": "crosses above", "right_type": "indicator", "right_val": "donchian_upper_3"},
            {"left": "vol_ratio_20", "op": ">", "right_type": "value", "right_val": "1.5"},
            {"left": "rsi_14", "op": ">", "right_type": "value", "right_val": "45"},
        ],
        "exit_rules": [
            {"left": "close", "op": "crosses below", "right_type": "indicator", "right_val": "donchian_middle_3"},
        ],
    },
    "🇮🇳 [SCALP] Momentum Tape — EMA Stack + RSI Dip": {
        "description": (
            "Advanced · Win rate ~55–63%. Top-down: 15m trend + 5m entry (backtest: 5m stack proxy). "
            "EMA 5>13>34 bullish stack, RSI 7 dip on pullback (not crash). "
            "Markets: NIFTY50, FINNIFTY, liquid banks. "
            "LONG: 15m bull stack → pullback to EMA 13 zone → 2m/5m RSI 40–45 + hammer/engulfing at EMA cluster → "
            "enter close above EMA-9, stop below signal low. "
            "EXIT: 2m RSI bearish divergence (lower high vs price) — exit before breakdown. "
            "Only trade when 15m trend clear; do not chase extended moves."
        ),
        "recommended_timeframe": "5m",
        "recommended_sl": 0.4,
        "recommended_tp": 0.9,
        "indicators": [
            {"type": "ema", "period": 5},
            {"type": "ema", "period": 13},
            {"type": "ema", "period": 34},
            {"type": "rsi", "period": 7},
            {"type": "atr", "period": 14},
        ],
        "entry_rules": [
            {"left": "ema_5", "op": ">", "right_type": "indicator", "right_val": "ema_13"},
            {"left": "ema_13", "op": ">", "right_type": "indicator", "right_val": "ema_34"},
            {"left": "close", "op": ">", "right_type": "indicator", "right_val": "ema_13"},
            {"left": "rsi_7", "op": ">", "right_type": "value", "right_val": "38"},
            {"left": "rsi_7", "op": "<", "right_type": "value", "right_val": "48"},
            {"left": "close", "op": "crosses above", "right_type": "indicator", "right_val": "ema_5"},
        ],
        "exit_rules": [
            {"left": "close", "op": "crosses below", "right_type": "indicator", "right_val": "ema_13"},
        ],
    },
    "🇮🇳 [SCALP] Liquidity Hunt — Stop Sweep Reversal": {
        "description": (
            "Advanced SMC/ICT · Win rate ~60–70% with practice. TF: 15m structure, 1m entry (backtest: 5m). "
            "Concepts: equal highs/lows liquidity, sweep, CHoCH, FVG. Markets: BANKNIFTY intraday, liquid index names. "
            "Killzones: 9:15–10:30, 14:30–15:30 IST. "
            "SHORT (manual): sweep above equal highs → bearish rejection → 1m CHoCH down. "
            "LONG proxy: sweep below range low (Donchian) → reclaim + volume → target demand/FVG below. "
            "⚠ Do NOT enter on sweep candle — wait for CHoCH/reclaim confirmation."
        ),
        "recommended_timeframe": "5m",
        "recommended_sl": 0.45,
        "recommended_tp": 1.0,
        "indicators": [
            {"type": "donchian", "period": 20},
            {"type": "ema", "period": 9},
            {"type": "rsi", "period": 14},
            {"type": "vol_sma", "period": 20},
            {"type": "atr", "period": 14},
        ],
        "entry_rules": [
            {"left": "close", "op": "crosses above", "right_type": "indicator", "right_val": "donchian_lower_20"},
            {"left": "vol_ratio_20", "op": ">", "right_type": "value", "right_val": "1.35"},
            {"left": "rsi_14", "op": "crosses above", "right_type": "value", "right_val": "42"},
        ],
        "exit_rules": [
            {"left": "close", "op": "crosses below", "right_type": "indicator", "right_val": "ema_9"},
        ],
    },
}

# ===========================================================================
# GROWW INDIA — SWING TRADING STRATEGIES (10)
# ===========================================================================

GROWW_SWING = {
    "🇮🇳 [SWING] Golden Cross EMA 50/200 + RSI": {
        "description": "Classic golden cross with RSI confirmation. The backbone of institutional swing trading on Indian equities.",
        "recommended_timeframe": "1d",
        "recommended_sl": 3.0,
        "recommended_tp": 8.0,
        "indicators": [
            {"type": "ema", "period": 50},
            {"type": "sma", "period": 200},
            {"type": "rsi", "period": 14},
        ],
        "entry_rules": [
            {"left": "ema_50", "op": "crosses above", "right_type": "indicator", "right_val": "sma_200"},
            {"left": "rsi_14", "op": "<", "right_type": "value", "right_val": "70"},
        ],
        "exit_rules": [
            {"left": "ema_50", "op": "crosses below", "right_type": "indicator", "right_val": "sma_200"},
        ],
    },
    "🇮🇳 [SWING] Supertrend 10/3 Trend Rider": {
        "description": "Rides medium-term trends using Supertrend (10, 3.0). Proven performer on Nifty 50 and midcap stocks since 2024.",
        "recommended_timeframe": "1d",
        "recommended_sl": 3.0,
        "recommended_tp": 7.0,
        "indicators": [
            {"type": "supertrend", "period": 10, "multiplier": 3.0},
            {"type": "adx", "period": 14},
        ],
        "entry_rules": [
            {"left": "supertrend_dir_10_3.0", "op": "==", "right_type": "value", "right_val": "1"},
            {"left": "adx_14", "op": ">", "right_type": "value", "right_val": "20"},
        ],
        "exit_rules": [
            {"left": "supertrend_dir_10_3.0", "op": "==", "right_type": "value", "right_val": "-1"},
        ],
    },
    "🇮🇳 [SWING] Bollinger Band Mean Reversion + MACD": {
        "description": "Buys lower BB touch with MACD histogram flip positive. Mean-reversion swing setup for range-bound markets.",
        "recommended_timeframe": "1d",
        "recommended_sl": 2.5,
        "recommended_tp": 5.0,
        "indicators": [
            {"type": "bb", "period": 20, "std_dev": 2.0},
            {"type": "macd", "fast": 12, "slow": 26, "signal": 9},
            {"type": "rsi", "period": 14},
        ],
        "entry_rules": [
            {"left": "close", "op": "<=", "right_type": "indicator", "right_val": "bb_lower_20_2.0"},
            {"left": "rsi_14", "op": "<", "right_type": "value", "right_val": "35"},
        ],
        "exit_rules": [
            {"left": "close", "op": ">=", "right_type": "indicator", "right_val": "bb_upper_20_2.0"},
        ],
    },
    "🇮🇳 [SWING] Fibonacci 0.618 Pullback + ADX Trend": {
        "description": "Buys at the golden pocket Fibonacci retracement (0.618) in confirmed trending markets using ADX > 25.",
        "recommended_timeframe": "1d",
        "recommended_sl": 3.0,
        "recommended_tp": 6.0,
        "indicators": [
            {"type": "fibonacci", "lookback": 50},
            {"type": "adx", "period": 14},
            {"type": "rsi", "period": 14},
        ],
        "entry_rules": [
            {"left": "close", "op": "<=", "right_type": "indicator", "right_val": "fib_0.618_50"},
            {"left": "adx_14", "op": ">", "right_type": "value", "right_val": "25"},
        ],
        "exit_rules": [
            {"left": "close", "op": ">=", "right_type": "indicator", "right_val": "fib_0.236_50"},
        ],
    },
    "🇮🇳 [SWING] EMA 20/50 + MACD Signal Cross": {
        "description": "Dual confirmation: EMA 20 crosses above EMA 50 while MACD line crosses above signal. Robust multi-week hold.",
        "recommended_timeframe": "1d",
        "recommended_sl": 3.0,
        "recommended_tp": 8.0,
        "indicators": [
            {"type": "ema", "period": 20},
            {"type": "ema", "period": 50},
            {"type": "macd", "fast": 12, "slow": 26, "signal": 9},
        ],
        "entry_rules": [
            {"left": "ema_20", "op": "crosses above", "right_type": "indicator", "right_val": "ema_50"},
            {"left": "macd_12_26", "op": ">", "right_type": "indicator", "right_val": "macd_signal_12_26_9"},
        ],
        "exit_rules": [
            {"left": "ema_20", "op": "crosses below", "right_type": "indicator", "right_val": "ema_50"},
        ],
    },
    "🇮🇳 [SWING] RSI Reversal + SMA 50 Support": {
        "description": "Buys oversold RSI reversal (< 30) near SMA 50 support. Time-tested value entry on blue-chip Nifty stocks.",
        "recommended_timeframe": "1d",
        "recommended_sl": 2.0,
        "recommended_tp": 5.0,
        "indicators": [
            {"type": "rsi", "period": 14},
            {"type": "sma", "period": 50},
        ],
        "entry_rules": [
            {"left": "rsi_14", "op": "crosses above", "right_type": "value", "right_val": "30"},
            {"left": "close", "op": ">", "right_type": "indicator", "right_val": "sma_50"},
        ],
        "exit_rules": [
            {"left": "rsi_14", "op": ">", "right_type": "value", "right_val": "70"},
        ],
    },
    "🇮🇳 [SWING] Williams %R + EMA 50 Trend Filter": {
        "description": "Enters from oversold Williams %R zone with EMA 50 trend confirmation. Great for catching pullback bottoms.",
        "recommended_timeframe": "1d",
        "recommended_sl": 2.5,
        "recommended_tp": 5.0,
        "indicators": [
            {"type": "williams_r", "period": 14},
            {"type": "ema", "period": 50},
        ],
        "entry_rules": [
            {"left": "williams_r_14", "op": "crosses above", "right_type": "value", "right_val": "-80"},
            {"left": "close", "op": ">", "right_type": "indicator", "right_val": "ema_50"},
        ],
        "exit_rules": [
            {"left": "williams_r_14", "op": ">", "right_type": "value", "right_val": "-20"},
        ],
    },
    "🇮🇳 [SWING] ADX Breakout + Donchian 50": {
        "description": "Trend-following using ADX strength > 30 with Donchian 50-period breakout. High conviction multi-week momentum play.",
        "recommended_timeframe": "1d",
        "recommended_sl": 3.0,
        "recommended_tp": 8.0,
        "indicators": [
            {"type": "adx", "period": 14},
            {"type": "donchian", "period": 50},
        ],
        "entry_rules": [
            {"left": "close", "op": "crosses above", "right_type": "indicator", "right_val": "donchian_upper_50"},
            {"left": "adx_14", "op": ">", "right_type": "value", "right_val": "30"},
        ],
        "exit_rules": [
            {"left": "close", "op": "crosses below", "right_type": "indicator", "right_val": "donchian_middle_50"},
        ],
    },
    "🇮🇳 [SWING] Pivot Point Breakout + Volume SMA": {
        "description": "Buys when price breaks above Pivot R1 with elevated volume (vol ratio > 1.5). Classic institutional breakout confirmation.",
        "recommended_timeframe": "1d",
        "recommended_sl": 2.0,
        "recommended_tp": 4.0,
        "indicators": [
            {"type": "pivots"},
            {"type": "vol_sma", "period": 20},
            {"type": "rsi", "period": 14},
        ],
        "entry_rules": [
            {"left": "close", "op": "crosses above", "right_type": "indicator", "right_val": "pivot_r1"},
            {"left": "vol_ratio_20", "op": ">", "right_type": "value", "right_val": "1.5"},
        ],
        "exit_rules": [
            {"left": "close", "op": "crosses below", "right_type": "indicator", "right_val": "pivot"},
        ],
    },
    "🇮🇳 [SWING] ROC Momentum + SMA 100 Trend": {
        "description": "Rate of Change momentum surge above SMA 100 trend filter. Catches early-stage momentum breakouts in midcap India.",
        "recommended_timeframe": "1d",
        "recommended_sl": 3.0,
        "recommended_tp": 7.0,
        "indicators": [
            {"type": "roc", "period": 14},
            {"type": "sma", "period": 100},
        ],
        "entry_rules": [
            {"left": "roc_14", "op": "crosses above", "right_type": "value", "right_val": "5"},
            {"left": "close", "op": ">", "right_type": "indicator", "right_val": "sma_100"},
        ],
        "exit_rules": [
            {"left": "roc_14", "op": "crosses below", "right_type": "value", "right_val": "0"},
        ],
    },
    "🇮🇳 [SWING] EMA 5/9/20/50/200 Full Stack Alignment": {
        "description": "Enters when EMA 5 > 9 > 20 > 50 > 200 (full bullish stack, mirrors EMA Position hub) and price closes above EMA 5. Strong-trend continuation hold.",
        "recommended_timeframe": "1d",
        "recommended_sl": 3.0,
        "recommended_tp": 8.0,
        "indicators": [
            {"type": "ema", "period": 5},
            {"type": "ema", "period": 9},
            {"type": "ema", "period": 20},
            {"type": "ema", "period": 50},
            {"type": "ema", "period": 200},
        ],
        "entry_rules": [
            {"left": "ema_5", "op": ">", "right_type": "indicator", "right_val": "ema_9"},
            {"left": "ema_9", "op": ">", "right_type": "indicator", "right_val": "ema_20"},
            {"left": "ema_20", "op": ">", "right_type": "indicator", "right_val": "ema_50"},
            {"left": "ema_50", "op": ">", "right_type": "indicator", "right_val": "ema_200"},
            {"left": "close", "op": "crosses above", "right_type": "indicator", "right_val": "ema_5"},
        ],
        "exit_rules": [
            {"left": "close", "op": "crosses below", "right_type": "indicator", "right_val": "ema_20"},
        ],
    },
}

# ===========================================================================
# COINDCX CRYPTO — SCALPING STRATEGIES (15)
# ===========================================================================

CRYPTO_SCALPING = {
    "₿ [SCALP] EMA 8/21 Fast Cross + RSI 9": {
        "description": "Ultra-fast EMA crossover with short RSI filter. Optimized for BTC and high-cap altcoins on 5m charts.",
        "recommended_timeframe": "5m",
        "recommended_sl": 0.5,
        "recommended_tp": 1.0,
        "indicators": [
            {"type": "ema", "period": 8},
            {"type": "ema", "period": 21},
            {"type": "rsi", "period": 9},
        ],
        "entry_rules": [
            {"left": "ema_8", "op": "crosses above", "right_type": "indicator", "right_val": "ema_21"},
            {"left": "rsi_9", "op": "<", "right_type": "value", "right_val": "60"},
        ],
        "exit_rules": [
            {"left": "ema_8", "op": "crosses below", "right_type": "indicator", "right_val": "ema_21"},
        ],
    },
    "₿ [SCALP] Supertrend 5/1.5 Turbo": {
        "description": "Very tight Supertrend parameters for crypto scalping. Captures micro-trends in volatile markets like SOL and ETH.",
        "recommended_timeframe": "1m",
        "recommended_sl": 0.3,
        "recommended_tp": 0.6,
        "indicators": [
            {"type": "supertrend", "period": 5, "multiplier": 1.5},
            {"type": "rsi", "period": 7},
        ],
        "entry_rules": [
            {"left": "supertrend_dir_5_1.5", "op": "==", "right_type": "value", "right_val": "1"},
            {"left": "rsi_7", "op": ">", "right_type": "value", "right_val": "30"},
        ],
        "exit_rules": [
            {"left": "supertrend_dir_5_1.5", "op": "==", "right_type": "value", "right_val": "-1"},
        ],
    },
    "₿ [SCALP] VWAP Reclaim + Volume Spike": {
        "description": "Enters when price reclaims VWAP with above-average volume. Captures institutional crypto flow on intraday charts.",
        "recommended_timeframe": "5m",
        "recommended_sl": 0.5,
        "recommended_tp": 1.0,
        "indicators": [
            {"type": "vwap"},
            {"type": "vol_sma", "period": 20},
            {"type": "rsi", "period": 9},
        ],
        "entry_rules": [
            {"left": "close", "op": "crosses above", "right_type": "indicator", "right_val": "vwap"},
            {"left": "vol_ratio_20", "op": ">", "right_type": "value", "right_val": "1.5"},
        ],
        "exit_rules": [
            {"left": "close", "op": "crosses below", "right_type": "indicator", "right_val": "vwap"},
        ],
    },
    "₿ [SCALP] BB Lower Band Bounce + RSI 7": {
        "description": "Mean-reversion on lower Bollinger Band touch with ultra-short RSI. Works well on range-bound crypto pairs.",
        "recommended_timeframe": "5m",
        "recommended_sl": 0.5,
        "recommended_tp": 1.0,
        "indicators": [
            {"type": "bb", "period": 20, "std_dev": 2.0},
            {"type": "rsi", "period": 7},
        ],
        "entry_rules": [
            {"left": "close", "op": "crosses above", "right_type": "indicator", "right_val": "bb_lower_20_2.0"},
            {"left": "rsi_7", "op": "<", "right_type": "value", "right_val": "25"},
        ],
        "exit_rules": [
            {"left": "close", "op": ">=", "right_type": "indicator", "right_val": "bb_middle_20_2.0"},
        ],
    },
    "₿ [SCALP] MACD Zero Cross + EMA 13": {
        "description": "MACD line crosses zero with EMA 13 trend confirmation. Strong momentum ignition scalp for altcoins.",
        "recommended_timeframe": "5m",
        "recommended_sl": 0.5,
        "recommended_tp": 1.0,
        "indicators": [
            {"type": "macd", "fast": 12, "slow": 26, "signal": 9},
            {"type": "ema", "period": 13},
        ],
        "entry_rules": [
            {"left": "macd_12_26", "op": "crosses above", "right_type": "value", "right_val": "0"},
            {"left": "close", "op": ">", "right_type": "indicator", "right_val": "ema_13"},
        ],
        "exit_rules": [
            {"left": "macd_12_26", "op": "crosses below", "right_type": "value", "right_val": "0"},
        ],
    },
    "₿ [SCALP] Stochastic + SMA 9 Micro Trend": {
        "description": "Stochastic %K/%D crossover from oversold zone with SMA 9 trend. Great for meme coin and altcoin scalps.",
        "recommended_timeframe": "5m",
        "recommended_sl": 0.5,
        "recommended_tp": 1.0,
        "indicators": [
            {"type": "stochastic", "k_period": 9, "d_period": 3},
            {"type": "sma", "period": 9},
        ],
        "entry_rules": [
            {"left": "stoch_k_9", "op": "crosses above", "right_type": "indicator", "right_val": "stoch_d_9_3"},
            {"left": "stoch_k_9", "op": "<", "right_type": "value", "right_val": "20"},
        ],
        "exit_rules": [
            {"left": "stoch_k_9", "op": ">", "right_type": "value", "right_val": "80"},
        ],
    },
    "₿ [SCALP] CCI + EMA 8 Momentum Snap": {
        "description": "CCI(14) crosses above zero while price is above EMA 8. Captures sharp momentum bursts in crypto.",
        "recommended_timeframe": "5m",
        "recommended_sl": 0.5,
        "recommended_tp": 1.0,
        "indicators": [
            {"type": "cci", "period": 14},
            {"type": "ema", "period": 8},
        ],
        "entry_rules": [
            {"left": "cci_14", "op": "crosses above", "right_type": "value", "right_val": "0"},
            {"left": "close", "op": ">", "right_type": "indicator", "right_val": "ema_8"},
        ],
        "exit_rules": [
            {"left": "cci_14", "op": ">", "right_type": "value", "right_val": "200"},
        ],
    },
    "₿ [SCALP] Donchian 10 Breakout + RSI": {
        "description": "Short-term Donchian channel breakout with RSI filter. Captures crypto breakouts on 15m charts.",
        "recommended_timeframe": "15m",
        "recommended_sl": 0.8,
        "recommended_tp": 1.5,
        "indicators": [
            {"type": "donchian", "period": 10},
            {"type": "rsi", "period": 14},
        ],
        "entry_rules": [
            {"left": "close", "op": "crosses above", "right_type": "indicator", "right_val": "donchian_upper_10"},
            {"left": "rsi_14", "op": ">", "right_type": "value", "right_val": "50"},
        ],
        "exit_rules": [
            {"left": "close", "op": "crosses below", "right_type": "indicator", "right_val": "donchian_middle_10"},
        ],
    },
    "₿ [SCALP] Williams %R Snap + EMA 5": {
        "description": "Snaps from oversold Williams %R zone with EMA 5 micro trend. Quick reversal scalp on volatile crypto.",
        "recommended_timeframe": "5m",
        "recommended_sl": 0.4,
        "recommended_tp": 0.8,
        "indicators": [
            {"type": "williams_r", "period": 9},
            {"type": "ema", "period": 5},
        ],
        "entry_rules": [
            {"left": "williams_r_9", "op": "crosses above", "right_type": "value", "right_val": "-80"},
            {"left": "close", "op": ">", "right_type": "indicator", "right_val": "ema_5"},
        ],
        "exit_rules": [
            {"left": "williams_r_9", "op": ">", "right_type": "value", "right_val": "-20"},
        ],
    },
    "₿ [SCALP] MFI + EMA 9/21 Double Confirm": {
        "description": "Money Flow Index > 50 with EMA 9/21 bullish crossover. Volume + trend confirmation for clean crypto scalps.",
        "recommended_timeframe": "5m",
        "recommended_sl": 0.5,
        "recommended_tp": 1.0,
        "indicators": [
            {"type": "mfi", "period": 14},
            {"type": "ema", "period": 9},
            {"type": "ema", "period": 21},
        ],
        "entry_rules": [
            {"left": "ema_9", "op": "crosses above", "right_type": "indicator", "right_val": "ema_21"},
            {"left": "mfi_14", "op": ">", "right_type": "value", "right_val": "50"},
        ],
        "exit_rules": [
            {"left": "ema_9", "op": "crosses below", "right_type": "indicator", "right_val": "ema_21"},
        ],
    },
    "₿ [SCALP] Order Flow + Footprint Scalping": {
        "description": (
            "Intermediate · Win rate ~65–72% (live DOM/footprint; backtest uses OHLCV proxy). "
            "Core tools: DOM/L2, footprint, CVD — proxied via VWAP, MFI, OBV/volume ratio. "
            "Timeframe: 1m–2m (preset backtest: 1m). Best: BTC/USDT, ETH/USDT. "
            "Sessions: NY open, London open (UTC overlap). "
            "LONG: bid absorption at support, CVD turning up, price holds (≤2 ticks below zone), "
            "enter on rejection — close reclaims VWAP with volume spike. "
            "SHORT (manual): ask absorption at resistance, CVD down while price flat, high-volume no follow-through. "
            "SL: 0.12% beyond zone · T1: 1.5–2× risk (0.18–0.24%) · T2: next major S/R."
        ),
        "recommended_timeframe": "1m",
        "recommended_sl": 0.12,
        "recommended_tp": 0.24,
        "indicators": [
            {"type": "vwap"},
            {"type": "mfi", "period": 14},
            {"type": "obv"},
            {"type": "vol_sma", "period": 20},
            {"type": "ema", "period": 9},
            {"type": "bb", "period": 20, "std_dev": 2.0},
        ],
        "entry_rules": [
            {"left": "close", "op": "crosses above", "right_type": "indicator", "right_val": "vwap"},
            {"left": "mfi_14", "op": "crosses above", "right_type": "value", "right_val": "50"},
            {"left": "vol_ratio_20", "op": ">", "right_type": "value", "right_val": "1.25"},
            {"left": "close", "op": ">", "right_type": "indicator", "right_val": "bb_lower_20_2.0"},
        ],
        "exit_rules": [
            {"left": "close", "op": "crosses below", "right_type": "indicator", "right_val": "vwap"},
        ],
    },
    "₿ [SCALP] VWAP Band Reversion + Trend Continuation": {
        "description": (
            "Beginner-friendly · Win rate ~60–68%. TF: 3m/5m intraday VWAP (backtest: 5m). "
            "Markets: BTC, ETH, SOL. Best: NY open, London open; avoid low-liquidity midday. "
            "REVERSION: -1SD VWAP band touch, RSI<30, vol spike → target VWAP midline (1:2+ R:R). "
            "CONTINUATION: price above VWAP, pullback to VWAP, EMA 9 turns up → long on close above EMA-9. "
            "Inverse for shorts on bearish days (manual). ⚠ Never fade VWAP on strong trend days."
        ),
        "recommended_timeframe": "5m",
        "recommended_sl": 0.35,
        "recommended_tp": 0.75,
        "indicators": [
            {"type": "vwap"},
            {"type": "bb", "period": 20, "std_dev": 2.0},
            {"type": "ema", "period": 9},
            {"type": "rsi", "period": 14},
            {"type": "vol_sma", "period": 20},
        ],
        "entry_rules": [
            {"left": "close", "op": "crosses above", "right_type": "indicator", "right_val": "bb_lower_20_2.0"},
            {"left": "rsi_14", "op": "<", "right_type": "value", "right_val": "32"},
            {"left": "vol_ratio_20", "op": ">", "right_type": "value", "right_val": "1.2"},
        ],
        "exit_rules": [
            {"left": "close", "op": "crosses above", "right_type": "indicator", "right_val": "vwap"},
        ],
    },
    "₿ [SCALP] Opening Range Breakout (ORB) + Volume": {
        "description": (
            "Win rate ~58–65%. Range: first 15m (Donchian-3 on 5m) or hourly for BTC (00:00 UTC). "
            "Breakout candle vol >1.5× range average. Close above range high (not wick only). "
            "Stop: range mid or opposite side. T1: measured move; T2: prior session H/L. "
            "Skip large gap days; wait for retest + hold. Max 2 ORB setups per session."
        ),
        "recommended_timeframe": "5m",
        "recommended_sl": 0.5,
        "recommended_tp": 1.0,
        "indicators": [
            {"type": "donchian", "period": 3},
            {"type": "vol_sma", "period": 20},
            {"type": "rsi", "period": 14},
        ],
        "entry_rules": [
            {"left": "close", "op": "crosses above", "right_type": "indicator", "right_val": "donchian_upper_3"},
            {"left": "vol_ratio_20", "op": ">", "right_type": "value", "right_val": "1.5"},
            {"left": "rsi_14", "op": ">", "right_type": "value", "right_val": "45"},
        ],
        "exit_rules": [
            {"left": "close", "op": "crosses below", "right_type": "indicator", "right_val": "donchian_middle_3"},
        ],
    },
    "₿ [SCALP] Momentum Tape — EMA Stack + RSI Dip": {
        "description": (
            "Advanced · Win rate ~55–63%. 15m context + 2m entry (backtest: 5m). "
            "EMA 5>13>34 stack required. Markets: BTC, ETH, SOL/USDT. "
            "LONG: bull stack on higher TF, pullback to EMA 13, RSI 40–45 on dip, "
            "hammer/engulfing at EMA cluster → enter close above EMA-5/9, tight stop below candle low. "
            "EXIT on 2m RSI bearish divergence (price HH, RSI LH) — exit before breakdown."
        ),
        "recommended_timeframe": "5m",
        "recommended_sl": 0.4,
        "recommended_tp": 0.9,
        "indicators": [
            {"type": "ema", "period": 5},
            {"type": "ema", "period": 13},
            {"type": "ema", "period": 34},
            {"type": "rsi", "period": 7},
            {"type": "atr", "period": 14},
        ],
        "entry_rules": [
            {"left": "ema_5", "op": ">", "right_type": "indicator", "right_val": "ema_13"},
            {"left": "ema_13", "op": ">", "right_type": "indicator", "right_val": "ema_34"},
            {"left": "close", "op": ">", "right_type": "indicator", "right_val": "ema_13"},
            {"left": "rsi_7", "op": ">", "right_type": "value", "right_val": "38"},
            {"left": "rsi_7", "op": "<", "right_type": "value", "right_val": "48"},
            {"left": "close", "op": "crosses above", "right_type": "indicator", "right_val": "ema_5"},
        ],
        "exit_rules": [
            {"left": "close", "op": "crosses below", "right_type": "indicator", "right_val": "ema_13"},
        ],
    },
    "₿ [SCALP] Liquidity Hunt — Stop Sweep Reversal": {
        "description": (
            "Advanced SMC/ICT · Win rate ~60–70%. 15m structure, 1m precision (backtest: 5m). "
            "Markets: BTC, ETH liquid pairs. Killzones: NY/London (2–5 AM IST, 7–10 PM IST). "
            "Identify equal highs/lows → wait for sweep → CHoCH confirmation (do NOT enter on sweep bar). "
            "LONG proxy: sweep below Donchian low + reclaim + vol. SHORT: sweep highs + CHoCH down (manual)."
        ),
        "recommended_timeframe": "5m",
        "recommended_sl": 0.45,
        "recommended_tp": 1.0,
        "indicators": [
            {"type": "donchian", "period": 20},
            {"type": "ema", "period": 9},
            {"type": "rsi", "period": 14},
            {"type": "vol_sma", "period": 20},
            {"type": "atr", "period": 14},
        ],
        "entry_rules": [
            {"left": "close", "op": "crosses above", "right_type": "indicator", "right_val": "donchian_lower_20"},
            {"left": "vol_ratio_20", "op": ">", "right_type": "value", "right_val": "1.35"},
            {"left": "rsi_14", "op": "crosses above", "right_type": "value", "right_val": "42"},
        ],
        "exit_rules": [
            {"left": "close", "op": "crosses below", "right_type": "indicator", "right_val": "ema_9"},
        ],
    },
}

# ===========================================================================
# COINDCX CRYPTO — SWING TRADING STRATEGIES (10)
# ===========================================================================

CRYPTO_SWING = {
    "₿ [SWING] EMA 21/55 Golden Cross + ADX": {
        "description": "Medium-term EMA golden cross with ADX trend strength confirmation. Core crypto swing strategy for BTC and ETH.",
        "recommended_timeframe": "1d",
        "recommended_sl": 5.0,
        "recommended_tp": 15.0,
        "indicators": [
            {"type": "ema", "period": 21},
            {"type": "ema", "period": 55},
            {"type": "adx", "period": 14},
        ],
        "entry_rules": [
            {"left": "ema_21", "op": "crosses above", "right_type": "indicator", "right_val": "ema_55"},
            {"left": "adx_14", "op": ">", "right_type": "value", "right_val": "20"},
        ],
        "exit_rules": [
            {"left": "ema_21", "op": "crosses below", "right_type": "indicator", "right_val": "ema_55"},
        ],
    },
    "₿ [SWING] Supertrend 10/3 + RSI Trend": {
        "description": "Standard Supertrend with RSI > 40 filter. Rides multi-day crypto trends while avoiding choppy markets.",
        "recommended_timeframe": "4h",
        "recommended_sl": 4.0,
        "recommended_tp": 12.0,
        "indicators": [
            {"type": "supertrend", "period": 10, "multiplier": 3.0},
            {"type": "rsi", "period": 14},
        ],
        "entry_rules": [
            {"left": "supertrend_dir_10_3.0", "op": "==", "right_type": "value", "right_val": "1"},
            {"left": "rsi_14", "op": ">", "right_type": "value", "right_val": "40"},
        ],
        "exit_rules": [
            {"left": "supertrend_dir_10_3.0", "op": "==", "right_type": "value", "right_val": "-1"},
        ],
    },
    "₿ [SWING] BB Width Expansion + MACD Confirm": {
        "description": "Enters on Bollinger Band expansion with MACD histogram positive. Catches volatile crypto breakouts.",
        "recommended_timeframe": "1d",
        "recommended_sl": 5.0,
        "recommended_tp": 15.0,
        "indicators": [
            {"type": "bb", "period": 20, "std_dev": 2.0},
            {"type": "macd", "fast": 12, "slow": 26, "signal": 9},
        ],
        "entry_rules": [
            {"left": "close", "op": "crosses above", "right_type": "indicator", "right_val": "bb_upper_20_2.0"},
            {"left": "macd_hist_12_26_9", "op": ">", "right_type": "value", "right_val": "0"},
        ],
        "exit_rules": [
            {"left": "close", "op": "crosses below", "right_type": "indicator", "right_val": "bb_middle_20_2.0"},
        ],
    },
    "₿ [SWING] Fibonacci 0.5 Pullback + RSI": {
        "description": "Buys crypto at Fibonacci 0.5 retracement level with RSI oversold confirmation. Golden pocket swing entry.",
        "recommended_timeframe": "1d",
        "recommended_sl": 5.0,
        "recommended_tp": 12.0,
        "indicators": [
            {"type": "fibonacci", "lookback": 60},
            {"type": "rsi", "period": 14},
        ],
        "entry_rules": [
            {"left": "close", "op": "<=", "right_type": "indicator", "right_val": "fib_0.5_60"},
            {"left": "rsi_14", "op": "<", "right_type": "value", "right_val": "40"},
        ],
        "exit_rules": [
            {"left": "close", "op": ">=", "right_type": "indicator", "right_val": "fib_0.236_60"},
        ],
    },
    "₿ [SWING] MACD Signal Cross + EMA 50": {
        "description": "MACD bullish signal crossover confirmed by price above EMA 50. Strong multi-day momentum signal.",
        "recommended_timeframe": "1d",
        "recommended_sl": 5.0,
        "recommended_tp": 15.0,
        "indicators": [
            {"type": "macd", "fast": 12, "slow": 26, "signal": 9},
            {"type": "ema", "period": 50},
        ],
        "entry_rules": [
            {"left": "macd_12_26", "op": "crosses above", "right_type": "indicator", "right_val": "macd_signal_12_26_9"},
            {"left": "close", "op": ">", "right_type": "indicator", "right_val": "ema_50"},
        ],
        "exit_rules": [
            {"left": "macd_12_26", "op": "crosses below", "right_type": "indicator", "right_val": "macd_signal_12_26_9"},
        ],
    },
    "₿ [SWING] RSI 40 Bounce + SMA 100": {
        "description": "Buys when RSI bounces above 40 with SMA 100 support. Trend continuation play for top-cap crypto.",
        "recommended_timeframe": "1d",
        "recommended_sl": 4.0,
        "recommended_tp": 10.0,
        "indicators": [
            {"type": "rsi", "period": 14},
            {"type": "sma", "period": 100},
        ],
        "entry_rules": [
            {"left": "rsi_14", "op": "crosses above", "right_type": "value", "right_val": "40"},
            {"left": "close", "op": ">", "right_type": "indicator", "right_val": "sma_100"},
        ],
        "exit_rules": [
            {"left": "rsi_14", "op": ">", "right_type": "value", "right_val": "75"},
        ],
    },
    "₿ [SWING] Donchian 55 Turtle Breakout": {
        "description": "Classic Richard Dennis Turtle Trading breakout adapted for crypto. Donchian 55 upper channel break with ADX confirmation.",
        "recommended_timeframe": "1d",
        "recommended_sl": 5.0,
        "recommended_tp": 20.0,
        "indicators": [
            {"type": "donchian", "period": 55},
            {"type": "adx", "period": 14},
        ],
        "entry_rules": [
            {"left": "close", "op": "crosses above", "right_type": "indicator", "right_val": "donchian_upper_55"},
            {"left": "adx_14", "op": ">", "right_type": "value", "right_val": "25"},
        ],
        "exit_rules": [
            {"left": "close", "op": "crosses below", "right_type": "indicator", "right_val": "donchian_middle_55"},
        ],
    },
    "₿ [SWING] Stochastic Weekly Reset + EMA 21": {
        "description": "Stochastic cross from deep oversold (<15) on 4h chart with EMA 21 trend. Catches weekly swing lows in crypto.",
        "recommended_timeframe": "4h",
        "recommended_sl": 4.0,
        "recommended_tp": 10.0,
        "indicators": [
            {"type": "stochastic", "k_period": 14, "d_period": 3},
            {"type": "ema", "period": 21},
        ],
        "entry_rules": [
            {"left": "stoch_k_14", "op": "crosses above", "right_type": "indicator", "right_val": "stoch_d_14_3"},
            {"left": "stoch_k_14", "op": "<", "right_type": "value", "right_val": "15"},
        ],
        "exit_rules": [
            {"left": "stoch_k_14", "op": ">", "right_type": "value", "right_val": "85"},
        ],
    },
    "₿ [SWING] ROC Momentum + EMA 50 Filter": {
        "description": "Rate of Change above 10% with EMA 50 trend confirmation. Catches explosive altcoin rallies early.",
        "recommended_timeframe": "1d",
        "recommended_sl": 5.0,
        "recommended_tp": 15.0,
        "indicators": [
            {"type": "roc", "period": 14},
            {"type": "ema", "period": 50},
        ],
        "entry_rules": [
            {"left": "roc_14", "op": "crosses above", "right_type": "value", "right_val": "10"},
            {"left": "close", "op": ">", "right_type": "indicator", "right_val": "ema_50"},
        ],
        "exit_rules": [
            {"left": "roc_14", "op": "crosses below", "right_type": "value", "right_val": "0"},
        ],
    },
    "₿ [SWING] ADX + DI Directional System": {
        "description": "Classic Welles Wilder directional system: +DI crosses above -DI with ADX > 25. Definitive crypto trend entry.",
        "recommended_timeframe": "1d",
        "recommended_sl": 5.0,
        "recommended_tp": 15.0,
        "indicators": [
            {"type": "adx", "period": 14},
        ],
        "entry_rules": [
            {"left": "plus_di_14", "op": "crosses above", "right_type": "indicator", "right_val": "minus_di_14"},
            {"left": "adx_14", "op": ">", "right_type": "value", "right_val": "25"},
        ],
        "exit_rules": [
            {"left": "plus_di_14", "op": "crosses below", "right_type": "indicator", "right_val": "minus_di_14"},
        ],
    },
    "₿ [SWING] EMA 5/9/20/50/200 Full Stack Alignment": {
        "description": "Enters when EMA 5 > 9 > 20 > 50 > 200 (full bullish stack, mirrors EMA Position hub) and price closes above EMA 5. Strong-trend continuation hold for BTC/majors.",
        "recommended_timeframe": "1d",
        "recommended_sl": 5.0,
        "recommended_tp": 15.0,
        "indicators": [
            {"type": "ema", "period": 5},
            {"type": "ema", "period": 9},
            {"type": "ema", "period": 20},
            {"type": "ema", "period": 50},
            {"type": "ema", "period": 200},
        ],
        "entry_rules": [
            {"left": "ema_5", "op": ">", "right_type": "indicator", "right_val": "ema_9"},
            {"left": "ema_9", "op": ">", "right_type": "indicator", "right_val": "ema_20"},
            {"left": "ema_20", "op": ">", "right_type": "indicator", "right_val": "ema_50"},
            {"left": "ema_50", "op": ">", "right_type": "indicator", "right_val": "ema_200"},
            {"left": "close", "op": "crosses above", "right_type": "indicator", "right_val": "ema_5"},
        ],
        "exit_rules": [
            {"left": "close", "op": "crosses below", "right_type": "indicator", "right_val": "ema_20"},
        ],
    },
}

# ===========================================================================
# MARKET OUTLOOK — Multi-Combo presets (align with tomorrow outlook banners)
# ===========================================================================

GROWW_OUTLOOK = {
    "🔴 [OUTLOOK] Bearish Open Expected": {
        "description": (
            "For days when tomorrow's outlook is **Bearish Expectation** (bearish open). "
            "VWAP reject + bearish EMA stack + RSI weakness — weak-open follow-through "
            "on 15m (fade rallies, avoid long chase)."
        ),
        "recommended_timeframe": "15m",
        "recommended_sl": 0.6,
        "recommended_tp": 1.2,
        "indicators": [
            {"type": "vwap"},
            {"type": "ema", "period": 9},
            {"type": "ema", "period": 21},
            {"type": "rsi", "period": 14},
            {"type": "macd", "fast": 12, "slow": 26, "signal": 9},
        ],
        "entry_rules": [
            {"left": "close", "op": "crosses below", "right_type": "indicator", "right_val": "vwap"},
            {"left": "ema_9", "op": "<", "right_type": "indicator", "right_val": "ema_21"},
            {"left": "rsi_14", "op": "<", "right_type": "value", "right_val": "48"},
            {"left": "macd_hist_12_26_9", "op": "<", "right_type": "value", "right_val": "0"},
        ],
        "exit_rules": [
            {"left": "close", "op": "crosses above", "right_type": "indicator", "right_val": "vwap"},
            {"left": "rsi_14", "op": ">", "right_type": "value", "right_val": "62"},
        ],
    },
    "🟢 [OUTLOOK] Bullish Open Expected": {
        "description": (
            "For days when tomorrow's outlook is **Bullish Open Expected**. "
            "VWAP reclaim + bullish EMA cross + RSI momentum — strong-open continuation "
            "on 15m."
        ),
        "recommended_timeframe": "15m",
        "recommended_sl": 0.6,
        "recommended_tp": 1.2,
        "indicators": [
            {"type": "vwap"},
            {"type": "ema", "period": 9},
            {"type": "ema", "period": 21},
            {"type": "rsi", "period": 14},
            {"type": "macd", "fast": 12, "slow": 26, "signal": 9},
        ],
        "entry_rules": [
            {"left": "close", "op": "crosses above", "right_type": "indicator", "right_val": "vwap"},
            {"left": "ema_9", "op": "crosses above", "right_type": "indicator", "right_val": "ema_21"},
            {"left": "rsi_14", "op": ">", "right_type": "value", "right_val": "52"},
            {"left": "macd_hist_12_26_9", "op": ">", "right_type": "value", "right_val": "0"},
        ],
        "exit_rules": [
            {"left": "close", "op": "crosses below", "right_type": "indicator", "right_val": "vwap"},
            {"left": "ema_9", "op": "crosses below", "right_type": "indicator", "right_val": "ema_21"},
        ],
    },
}

CRYPTO_OUTLOOK = {
    "🔴 [OUTLOOK] Bearish Expectation": {
        "description": (
            "Bearish session bias: price below VWAP, bearish Supertrend, RSI rollover. "
            "Use on 15m when global risk-off / weak Gift Nifty cues align."
        ),
        "recommended_timeframe": "15m",
        "recommended_sl": 0.8,
        "recommended_tp": 1.5,
        "indicators": [
            {"type": "vwap"},
            {"type": "supertrend", "period": 7, "multiplier": 2.0},
            {"type": "rsi", "period": 14},
            {"type": "ema", "period": 21},
        ],
        "entry_rules": [
            {"left": "close", "op": "<", "right_type": "indicator", "right_val": "vwap"},
            {"left": "supertrend_dir_7_2.0", "op": "==", "right_type": "value", "right_val": "-1"},
            {"left": "rsi_14", "op": "crosses below", "right_type": "value", "right_val": "50"},
            {"left": "close", "op": "<", "right_type": "indicator", "right_val": "ema_21"},
        ],
        "exit_rules": [
            {"left": "supertrend_dir_7_2.0", "op": "==", "right_type": "value", "right_val": "1"},
            {"left": "rsi_14", "op": ">", "right_type": "value", "right_val": "65"},
        ],
    },
    "🟢 [OUTLOOK] Bullish Open Expected": {
        "description": (
            "Bullish session bias: VWAP reclaim + Supertrend up + RSI momentum. "
            "Use on 15m when risk-on / strong overnight futures align."
        ),
        "recommended_timeframe": "15m",
        "recommended_sl": 0.8,
        "recommended_tp": 1.5,
        "indicators": [
            {"type": "vwap"},
            {"type": "supertrend", "period": 7, "multiplier": 2.0},
            {"type": "rsi", "period": 14},
            {"type": "ema", "period": 21},
        ],
        "entry_rules": [
            {"left": "close", "op": "crosses above", "right_type": "indicator", "right_val": "vwap"},
            {"left": "supertrend_dir_7_2.0", "op": "==", "right_type": "value", "right_val": "1"},
            {"left": "rsi_14", "op": ">", "right_type": "value", "right_val": "52"},
            {"left": "close", "op": ">", "right_type": "indicator", "right_val": "ema_21"},
        ],
        "exit_rules": [
            {"left": "supertrend_dir_7_2.0", "op": "==", "right_type": "value", "right_val": "-1"},
            {"left": "rsi_14", "op": "<", "right_type": "value", "right_val": "45"},
        ],
    },
}


POPULAR_CRYPTO_PAIRS = [
    "BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT",
    "ADA-USDT", "AVAX-USDT", "DOT-USDT", "MATIC-USDT", "LINK-USDT",
    "SHIB-USDT", "UNI-USDT", "ATOM-USDT", "LTC-USDT", "FIL-USDT",
    "NEAR-USDT", "APT-USDT", "ARB-USDT", "OP-USDT", "SUI-USDT",
    "INJ-USDT", "TIA-USDT", "SEI-USDT", "PEPE-USDT", "WIF-USDT",
    "RENDER-USDT", "FET-USDT", "JASMY-USDT", "ONDO-USDT", "BONK-USDT",
]


def get_presets_for_market(market: str) -> dict:
    """Returns the combined scalping + swing + outlook preset dictionary for a given market."""
    from app.market_pulse.ticker_utils import is_crypto_market, is_us_market
    if is_crypto_market(market):
        return {**CRYPTO_SCALPING, **CRYPTO_SWING, **CRYPTO_OUTLOOK}
    if is_us_market(market):
        return {**GROWW_SCALPING, **GROWW_SWING, **GROWW_OUTLOOK}
    return {**GROWW_SCALPING, **GROWW_SWING, **GROWW_OUTLOOK}


def get_presets_by_category(market: str) -> dict:
    """Returns presets organized by category for the encyclopedia view."""
    from app.market_pulse.ticker_utils import is_crypto_market, is_us_market
    if is_crypto_market(market):
        return {
            "₿ Scalping Strategies (Crypto)": CRYPTO_SCALPING,
            "₿ Swing Trading Strategies (Crypto)": CRYPTO_SWING,
            "🔮 Market Outlook (Crypto)": CRYPTO_OUTLOOK,
        }
    if is_us_market(market):
        return {
            "🇺🇸 Scalping Strategies (US)": GROWW_SCALPING,
            "🇺🇸 Swing Trading Strategies (US)": GROWW_SWING,
            "🔮 Market Outlook (US)": GROWW_OUTLOOK,
        }
    return {
        "🇮🇳 Scalping Strategies (India)": GROWW_SCALPING,
        "🇮🇳 Swing Trading Strategies (India)": GROWW_SWING,
        "🔮 Market Outlook (India)": GROWW_OUTLOOK,
    }
