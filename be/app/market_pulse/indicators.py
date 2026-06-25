"""
indicators.py
-------------
Pure-pandas indicators supporting custom parameters dynamically.
Expanded to support a comprehensive suite of professional technical analysis indicators.
"""

import pandas as pd
import numpy as np

def add_ema(df: pd.DataFrame, period: int, col: str = "close") -> pd.DataFrame:
    df[f"ema_{period}"] = df[col].ewm(span=period, adjust=False).mean()
    return df

def add_sma(df: pd.DataFrame, period: int, col: str = "close") -> pd.DataFrame:
    df[f"sma_{period}"] = df[col].rolling(period).mean()
    return df

def add_vwap(df: pd.DataFrame) -> pd.DataFrame:
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    tp_vol = typical_price * df["volume"]
    try:
        if isinstance(df.index, pd.DatetimeIndex) and len(np.unique(df.index.date)) > 1:
            df["vwap"] = (tp_vol.groupby(df.index.date).cumsum()) / (df["volume"].groupby(df.index.date).cumsum().replace(0, np.nan))
        else:
            df["vwap"] = tp_vol.cumsum() / df["volume"].cumsum().replace(0, np.nan)
    except Exception:
        df["vwap"] = tp_vol.cumsum() / df["volume"].cumsum().replace(0, np.nan)
    return df

def add_rsi(df: pd.DataFrame, period: int = 14, col: str = "close") -> pd.DataFrame:
    delta = df[col].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df[f"rsi_{period}"] = 100 - (100 / (1 + rs))
    return df

def add_bollinger_bands(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0, col: str = "close") -> pd.DataFrame:
    sma = df[col].rolling(period).mean()
    std = df[col].rolling(period).std()
    df[f"bb_upper_{period}_{std_dev}"] = sma + std_dev * std
    df[f"bb_middle_{period}_{std_dev}"] = sma
    df[f"bb_lower_{period}_{std_dev}"] = sma - std_dev * std
    return df

def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df[f"atr_{period}"] = tr.ewm(com=period - 1, adjust=False).mean()
    return df

def add_supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    atr_col = f"atr_{period}"
    if atr_col not in df.columns:
        df = add_atr(df, period)
        
    hl2 = (df["high"] + df["low"]) / 2
    basic_ub = hl2 + multiplier * df[atr_col]
    basic_lb = hl2 - multiplier * df[atr_col]
    
    final_ub = basic_ub.copy()
    final_lb = basic_lb.copy()
    
    for i in range(1, len(df)):
        if basic_ub.iloc[i] < final_ub.iloc[i-1] or df["close"].iloc[i-1] > final_ub.iloc[i-1]:
            final_ub.iloc[i] = basic_ub.iloc[i]
        else:
            final_ub.iloc[i] = final_ub.iloc[i-1]
            
        if basic_lb.iloc[i] > final_lb.iloc[i-1] or df["close"].iloc[i-1] < final_lb.iloc[i-1]:
            final_lb.iloc[i] = basic_lb.iloc[i]
        else:
            final_lb.iloc[i] = final_lb.iloc[i-1]
            
    supertrend = pd.Series(0.0, index=df.index)
    direction = pd.Series(1, index=df.index)
    
    supertrend.iloc[0] = final_ub.iloc[0]
    direction.iloc[0] = -1
    
    for i in range(1, len(df)):
        prev_st = supertrend.iloc[i-1]
        prev_dir = direction.iloc[i-1]
        close = df["close"].iloc[i]
        
        if prev_dir == 1:
            if close < final_lb.iloc[i]:
                supertrend.iloc[i] = final_ub.iloc[i]
                direction.iloc[i] = -1
            else:
                supertrend.iloc[i] = final_lb.iloc[i]
                direction.iloc[i] = 1
        else:
            if close > final_ub.iloc[i]:
                supertrend.iloc[i] = final_lb.iloc[i]
                direction.iloc[i] = 1
            else:
                supertrend.iloc[i] = final_ub.iloc[i]
                direction.iloc[i] = -1
                
    df[f"supertrend_{period}_{multiplier}"] = supertrend
    df[f"supertrend_dir_{period}_{multiplier}"] = direction
    return df

# ---------------------------------------------------------------------------
# Newly Added Indicators
# ---------------------------------------------------------------------------

def add_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9, col: str = "close") -> pd.DataFrame:
    ema_fast = df[col].ewm(span=fast, adjust=False).mean()
    ema_slow = df[col].ewm(span=slow, adjust=False).mean()
    df[f"macd_{fast}_{slow}"] = ema_fast - ema_slow
    df[f"macd_signal_{fast}_{slow}_{signal}"] = df[f"macd_{fast}_{slow}"].ewm(span=signal, adjust=False).mean()
    df[f"macd_hist_{fast}_{slow}_{signal}"] = df[f"macd_{fast}_{slow}"] - df[f"macd_signal_{fast}_{slow}_{signal}"]
    return df

def add_stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> pd.DataFrame:
    low_min = df["low"].rolling(k_period).min()
    high_max = df["high"].rolling(k_period).max()
    df[f"stoch_k_{k_period}"] = 100 * (df["close"] - low_min) / (high_max - low_min).replace(0, np.nan)
    df[f"stoch_d_{k_period}_{d_period}"] = df[f"stoch_k_{k_period}"].rolling(d_period).mean()
    return df

def add_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    high = df["high"]
    low = df["low"]
    close = df["close"]

    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0
    mask = plus_dm > minus_dm
    minus_dm[mask] = 0
    mask2 = minus_dm >= plus_dm
    plus_dm[mask2] = 0

    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)

    atr = tr.ewm(com=period - 1, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(com=period - 1, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(com=period - 1, adjust=False).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    df[f"adx_{period}"] = dx.ewm(com=period - 1, adjust=False).mean()
    df[f"plus_di_{period}"] = plus_di
    df[f"minus_di_{period}"] = minus_di
    return df

def add_obv(df: pd.DataFrame) -> pd.DataFrame:
    obv = [0]
    for i in range(1, len(df)):
        if df["close"].iloc[i] > df["close"].iloc[i - 1]:
            obv.append(obv[-1] + df["volume"].iloc[i])
        elif df["close"].iloc[i] < df["close"].iloc[i - 1]:
            obv.append(obv[-1] - df["volume"].iloc[i])
        else:
            obv.append(obv[-1])
    df["obv"] = obv
    return df

def add_vol_sma(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    df[f"vol_sma_{period}"] = df["volume"].rolling(period).mean()
    df[f"vol_ratio_{period}"] = df["volume"] / df[f"vol_sma_{period}"].replace(0, np.nan)
    return df

def add_pivots(df: pd.DataFrame) -> pd.DataFrame:
    prev_high = df["high"].shift(1)
    prev_low = df["low"].shift(1)
    prev_close = df["close"].shift(1)
    pivot = (prev_high + prev_low + prev_close) / 3
    df["pivot"] = pivot
    df["pivot_r1"] = 2 * pivot - prev_low
    df["pivot_s1"] = 2 * pivot - prev_high
    df["pivot_r2"] = pivot + (prev_high - prev_low)
    df["pivot_s2"] = pivot - (prev_high - prev_low)
    return df

def add_fib_levels(df: pd.DataFrame, lookback: int = 50) -> pd.DataFrame:
    df[f"fib_high_{lookback}"] = df["high"].rolling(window=lookback, min_periods=1).max()
    df[f"fib_low_{lookback}"] = df["low"].rolling(window=lookback, min_periods=1).min()
    diff = df[f"fib_high_{lookback}"] - df[f"fib_low_{lookback}"]
    df[f"fib_0.236_{lookback}"] = df[f"fib_high_{lookback}"] - 0.236 * diff
    df[f"fib_0.382_{lookback}"] = df[f"fib_high_{lookback}"] - 0.382 * diff
    df[f"fib_0.5_{lookback}"]   = df[f"fib_high_{lookback}"] - 0.500 * diff
    df[f"fib_0.618_{lookback}"] = df[f"fib_high_{lookback}"] - 0.618 * diff
    df[f"fib_0.786_{lookback}"] = df[f"fib_high_{lookback}"] - 0.786 * diff
    return df

def add_cci(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    sma = typical_price.rolling(period).mean()
    mean_deviation = typical_price.rolling(period).apply(lambda x: np.mean(np.abs(x - x.mean())))
    df[f"cci_{period}"] = (typical_price - sma) / (0.015 * mean_deviation.replace(0, np.nan))
    return df

def add_roc(df: pd.DataFrame, period: int = 9) -> pd.DataFrame:
    df[f"roc_{period}"] = ((df["close"] - df["close"].shift(period)) / df["close"].shift(period).replace(0, np.nan)) * 100
    return df

def add_williams_r(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    highest_high = df["high"].rolling(period).max()
    lowest_low = df["low"].rolling(period).min()
    df[f"williams_r_{period}"] = ((highest_high - df["close"]) / (highest_high - lowest_low).replace(0, np.nan)) * -100
    return df

def add_mfi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    money_flow = typical_price * df["volume"]
    positive_flow = np.where(typical_price > typical_price.shift(1), money_flow, 0)
    negative_flow = np.where(typical_price < typical_price.shift(1), money_flow, 0)
    pos_mf = pd.Series(positive_flow, index=df.index).rolling(period).sum()
    neg_mf = pd.Series(negative_flow, index=df.index).rolling(period).sum()
    mfr = pos_mf / neg_mf.replace(0, np.nan)
    df[f"mfi_{period}"] = 100 - (100 / (1 + mfr))
    return df

def add_donchian_channels(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    df[f"donchian_upper_{period}"] = df["high"].rolling(period).max()
    df[f"donchian_lower_{period}"] = df["low"].rolling(period).min()
    df[f"donchian_middle_{period}"] = (df[f"donchian_upper_{period}"] + df[f"donchian_lower_{period}"]) / 2
    return df

# ---------------------------------------------------------------------------
# Master Dynamic Computation
# ---------------------------------------------------------------------------

def calculate_dynamic_indicators(df: pd.DataFrame, indicator_configs: list) -> pd.DataFrame:
    df = df.copy()
    for config in indicator_configs:
        itype = config["type"].lower()
        if itype == "ema":
            df = add_ema(df, int(config["period"]))
        elif itype == "sma":
            df = add_sma(df, int(config["period"]))
        elif itype == "vwap":
            df = add_vwap(df)
        elif itype == "rsi":
            df = add_rsi(df, int(config["period"]))
        elif itype == "bb":
            df = add_bollinger_bands(df, int(config["period"]), float(config["std_dev"]))
        elif itype == "atr":
            df = add_atr(df, int(config["period"]))
        elif itype == "supertrend":
            df = add_supertrend(df, int(config["period"]), float(config["multiplier"]))
        elif itype == "macd":
            df = add_macd(df, int(config["fast"]), int(config["slow"]), int(config["signal"]))
        elif itype == "stochastic":
            df = add_stochastic(df, int(config["k_period"]), int(config["d_period"]))
        elif itype == "adx":
            df = add_adx(df, int(config["period"]))
        elif itype == "obv":
            df = add_obv(df)
        elif itype == "vol_sma":
            df = add_vol_sma(df, int(config["period"]))
        elif itype == "pivots":
            df = add_pivots(df)
        elif itype == "fibonacci":
            df = add_fib_levels(df, int(config["lookback"]))
        elif itype == "cci":
            df = add_cci(df, int(config["period"]))
        elif itype == "roc":
            df = add_roc(df, int(config["period"]))
        elif itype == "williams_r":
            df = add_williams_r(df, int(config["period"]))
        elif itype == "mfi":
            df = add_mfi(df, int(config["period"]))
        elif itype == "donchian":
            df = add_donchian_channels(df, int(config["period"]))
    return df
