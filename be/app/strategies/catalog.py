"""Human-readable strategy catalog for API and UI."""

CATEGORY_DESCRIPTIONS = {
    "scalping": "Very short-term trades on 1m–3m charts. Targets small moves with tight risk; best during liquid market hours.",
    "intraday": "Same-day setups on 5m–15m charts. Holds from minutes to a few hours; closes before session end.",
    "swing": "Multi-day positions on daily charts. Captures larger trends and mean-reversion over days to weeks.",
}

STRATEGY_DETAILS: dict[str, dict] = {
    "vwap_bounce_scalp": {
        "summary": "Fade back to VWAP in the direction of intraday slope.",
        "description": "Uses session VWAP as dynamic support/resistance. Enters when price returns near VWAP while slope confirms trend direction.",
        "indicators": ["VWAP", "ATR"],
        "entry_rules": [
            "BUY: VWAP slope positive, price near VWAP (within 0.25× ATR), close at/above VWAP.",
            "SELL: VWAP slope negative, price near VWAP, close at/below VWAP.",
        ],
        "exit_rules": ["Opposite signal or manual exit before session close."],
    },
    "orb_1min_scalp": {
        "summary": "First 5-minute opening range breakout with volume confirmation.",
        "description": "Defines the opening range from the first bars of the session and trades the first breakout above/below with rising volume.",
        "indicators": ["Opening Range High/Low", "Volume"],
        "entry_rules": [
            "BUY: First close above OR high after range forms, volume above 20-bar average.",
            "SELL: First close below OR low after range forms, volume above average.",
        ],
        "exit_rules": ["Opposite breakout signal or end of scalp target."],
    },
    "orderflow_imbalance_scalp": {
        "summary": "Trades extreme buy/sell volume imbalance via candle close position.",
        "description": "Estimates aggressive buy vs sell volume from where the close sits in the bar range. Signals when rolling delta z-score exceeds threshold.",
        "indicators": ["Volume Delta", "Z-Score"],
        "entry_rules": [
            "BUY: Delta z-score > +1.5 (buying pressure).",
            "SELL: Delta z-score < −1.5 (selling pressure).",
        ],
        "exit_rules": ["Mean reversion of delta or opposite signal."],
    },
    "ema_crossover_scalp": {
        "summary": "Fast/slow EMA cross with volume filter on 1m–3m bars.",
        "description": "Classic 5/9 EMA crossover filtered by above-average volume to avoid low-conviction crosses.",
        "indicators": ["EMA(5)", "EMA(9)", "Volume"],
        "entry_rules": [
            "BUY: Fast EMA crosses above slow EMA with rising volume.",
            "SELL: Fast EMA crosses below slow EMA with rising volume.",
        ],
        "exit_rules": ["Opposite EMA cross."],
    },
    "bollinger_squeeze_breakout_scalp": {
        "summary": "Volatility squeeze then Bollinger band breakout.",
        "description": "Waits for bandwidth to rank in the lowest 15% of recent history, then trades expansion break above upper or below lower band.",
        "indicators": ["Bollinger Bands", "Bandwidth Percentile"],
        "entry_rules": [
            "BUY: Prior bar in squeeze, close breaks above upper band.",
            "SELL: Prior bar in squeeze, close breaks below lower band.",
        ],
        "exit_rules": ["Band mean reversion or opposite breakout."],
    },
    "orb_15min_with_retest": {
        "summary": "15-minute opening range breakout with retest entry.",
        "description": "After the first 15 minutes define the range, waits for a breakout then a retest of the broken level before entering.",
        "indicators": ["Opening Range", "Retest Level"],
        "entry_rules": [
            "BUY: Broke above OR high, retest holds, close back above OR high.",
            "SELL: Broke below OR low, retest fails, close back below OR low.",
        ],
        "exit_rules": ["Opposite retest signal or session target."],
    },
    "vwap_trend_intraday": {
        "summary": "Trend follow using VWAP side as bias.",
        "description": "Simple intraday trend: go long when price crosses above VWAP, short when crossing below.",
        "indicators": ["VWAP"],
        "entry_rules": [
            "BUY: Close crosses above VWAP.",
            "SELL: Close crosses below VWAP.",
        ],
        "exit_rules": ["VWAP recross."],
    },
    "rsi_divergence_intraday": {
        "summary": "Classic bullish/bearish RSI divergence at swing pivots.",
        "description": "Detects price vs RSI divergence at rolling pivot highs/lows — bullish when price makes lower low but RSI higher low.",
        "indicators": ["RSI(14)", "Pivot High/Low"],
        "entry_rules": [
            "BUY: Bullish divergence at pivot low (price ↓, RSI ↑).",
            "SELL: Bearish divergence at pivot high (price ↑, RSI ↓).",
        ],
        "exit_rules": ["Opposite divergence or RSI extreme reversal."],
    },
    "macd_volume_confirm_intraday": {
        "summary": "MACD signal-line cross confirmed by volume.",
        "description": "MACD line crossing signal line with volume above 20-bar average to filter weak momentum shifts.",
        "indicators": ["MACD", "Signal Line", "Volume"],
        "entry_rules": [
            "BUY: MACD crosses above signal with volume confirmation.",
            "SELL: MACD crosses below signal with volume confirmation.",
        ],
        "exit_rules": ["Opposite MACD cross."],
    },
    "sr_breakout_pullback_intraday": {
        "summary": "Support/resistance breakout then pullback entry.",
        "description": "Uses 20-bar rolling high/low as S/R. After breakout, enters on first pullback that holds the broken level.",
        "indicators": ["Rolling Resistance", "Rolling Support"],
        "entry_rules": [
            "BUY: Broke resistance, pullback to level, close back above resistance.",
            "SELL: Broke support, pullback to level, close back below support.",
        ],
        "exit_rules": ["Level failure or opposite signal."],
    },
    "golden_death_cross_swing": {
        "summary": "50/200 EMA golden cross and death cross with volume.",
        "description": "Long-term trend following on daily charts using classic golden/death cross filtered by above-average volume.",
        "indicators": ["EMA(50)", "EMA(200)", "Volume"],
        "entry_rules": [
            "BUY: Golden cross (50 EMA above 200 EMA) with volume confirm.",
            "SELL: Death cross (50 EMA below 200 EMA) with volume confirm.",
        ],
        "exit_rules": ["Opposite cross."],
    },
    "weekly_rsi_pullback_swing": {
        "summary": "Buy RSI pullback in uptrend above 200 MA.",
        "description": "Only buys when price is above 200-day MA and RSI enters 40–50 pullback zone; sells on RSI overbought entry.",
        "indicators": ["SMA(200)", "RSI(14)"],
        "entry_rules": [
            "BUY: Uptrend (above MA200), RSI enters 40–50 zone.",
            "SELL: RSI crosses into overbought (≥70).",
        ],
        "exit_rules": ["RSI overbought or trend break below MA200."],
    },
    "consolidation_breakout_swing": {
        "summary": "Tight base breakout on daily charts.",
        "description": "Identifies 25-day consolidation (range ≤8%), then trades volume-backed breakout above base high or below base low.",
        "indicators": ["Base High/Low", "Volume"],
        "entry_rules": [
            "BUY: Tight base, close breaks above base high on 1.5× volume.",
            "SELL: Tight base, close breaks below base low on 1.5× volume.",
        ],
        "exit_rules": ["Return inside base or opposite breakout."],
    },
    "bollinger_mean_reversion_swing": {
        "summary": "Mean reversion at Bollinger bands in range-bound markets.",
        "description": "When 100-day trend slope is flat, buys touches of lower band and sells upper band touches.",
        "indicators": ["Bollinger Bands(20)", "SMA(100) Slope"],
        "entry_rules": [
            "BUY: Range-bound market, close at/below lower Bollinger band.",
            "SELL: Range-bound market, close at/above upper Bollinger band.",
        ],
        "exit_rules": ["Mid-band touch or trend breakout."],
    },
    "relative_strength_sector_rotation_swing": {
        "summary": "Relative strength vs benchmark index with RS line breakout.",
        "description": "Compares stock to NSE benchmark (^NSEI by default). Buys when RS line crosses above its MA at a new 63-day RS high.",
        "indicators": ["RS Line", "RS MA(20)", "63-day RS High"],
        "entry_rules": [
            "BUY: RS line crosses above RS MA while at 63-day RS high.",
            "SELL: RS line crosses below RS MA.",
        ],
        "exit_rules": ["RS MA cross down or benchmark underperformance."],
        "needs_benchmark": True,
    },
}
