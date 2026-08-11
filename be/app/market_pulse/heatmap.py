"""
heatmap.py
----------
Market Heatmap functionality for TrueBacktester.
Supports Groww Indian Stocks (with yfinance fallback) and CoinDCX Futures.
Includes sectoral heatmaps with support/resistance, PCR, volume analysis.
"""

import pandas as pd
import numpy as np
import requests
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)
logging.getLogger("yfinance").setLevel(logging.ERROR)

# ─── Configuration ──────────────────────────────────────────────────────────

GROWW_BASE = "https://api.groww.in"

# Timeframe mapping: key -> (groww_minutes, max_days, coindcx_resolution)
TF_INDIA = {
    "1m": (1, 7, "1"),
    "5m": (5, 15, "5"),
    "10m": (10, 30, "10"),
    "15m": (15, 60, "15"),
    "30m": (30, 90, "30"),
    "1h": (60, 150, "60"),
    "4h": (240, 300, "240"),
    "1d": (1440, 1080, "1D"),
    "1w": (10080, 3650, "1W"),
    "1M": (43200, 7300, "1M"),
}

TF_CRYPTO = {
    "1m": "1",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "4h": "240",
    "1d": "1D",
    "1w": "1W",
    "1M": "1M",
}

# Sectoral indices with their symbols
SECTORAL_INDICES = {
    "NIFTY 50": ["NIFTY"],
    "NIFTY NEXT 50": ["NIFTYJR", "NIFTYNEXT50"],
    "NIFTY BANK": ["BANKNIFTY", "NIFTYBANK"],
    "NIFTY IT": ["NIFTYIT"],
    "NIFTY FINANCIAL SERVICES": ["FINNIFTY", "NIFTYFIN", "NIFTYFINSERVICE"],
    "NIFTY AUTO": ["NIFTYAUTO"],
    "NIFTY FMCG": ["NIFTYFMCG", "CNXFMCG"],
    "NIFTY METAL": ["NIFTYMETAL", "CNXMETAL"],
    "NIFTY REALTY": ["NIFTYREALTY", "CNXREALTY"],
    "NIFTY ENERGY": ["NIFTYENERGY", "CNXENERGY"],
    "NIFTY MIDCAP 150": ["NIFTYMIDCAP150", "NIFTYM150", "NIFTYMID150"],
    "NIFTY SMALLCAP 250": ["NIFTYSMALLCAP250", "NIFTYSML250", "NIFTYSMLCAP250"]
}

# ─── Groww API Functions ─────────────────────────────────────────────────────

def fetch_groww_ticker_stats(symbol: str, exchange: str, api_token: str):
    """Fetches real-time price, 24h change, and volume for a single Groww stock ticker."""
    try:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {api_token.strip()}",
            "X-API-VERSION": "1.0",
        }
        params = {
            "exchange": exchange.upper(),
            "segment": "CASH",
            "trading_symbol": symbol.upper()
        }
        r = requests.get(
            "https://api.groww.in/v1/live-data/quote",
            headers=headers,
            params=params,
            timeout=10
        )
        if r.status_code == 200:
            res = r.json()
            if res.get("status") == "SUCCESS":
                payload = res.get("payload", {})
                last_price = payload.get("last_price")
                day_change = payload.get("day_change_perc")
                volume = payload.get("volume")
                
                try:
                    price = float(last_price) if last_price is not None else 0.0
                    change = float(day_change) if day_change is not None else 0.0
                    vol = float(volume) if volume is not None else 0.0
                    
                    if price > 0:
                        return price, change, vol
                except (ValueError, TypeError) as e:
                    logger.debug(f"Error converting Groww response for {symbol}: {e}, payload={payload}")
                    return 0.0, 0.0, 0.0
            else:
                logger.debug(f"Groww API error for {symbol}: {res.get('message', 'Unknown error')}")
        else:
            logger.debug(f"Groww API error {r.status_code} for {symbol}")
    except Exception as e:
        logger.debug(f"Error fetching live quote for {symbol}: {e}")
    
    return 0.0, 0.0, 0.0

def fetch_groww_ohlcv(symbol: str, exchange: str, tf_key: str,
                      api_token: str, limit: int = 300) -> pd.DataFrame:
    """Fetch OHLCV from Groww API (authenticated) or public charting service."""
    try:
        if tf_key not in TF_INDIA:
            logger.error(f"Invalid timeframe '{tf_key}'")
            return pd.DataFrame()

        minutes, max_days, _ = TF_INDIA[tf_key]

        now = datetime.now()
        trading_days_needed = max(1, (minutes * limit) // 375 + 1)
        calendar_days_needed = trading_days_needed + (trading_days_needed // 5) * 2 + 5

        if tf_key != "1d":
            calendar_days_needed = max(7, calendar_days_needed)

        lookback_min = min(calendar_days_needed * 24 * 60, max_days * 24 * 60)
        start_dt = now - timedelta(minutes=lookback_min)

        if api_token and api_token.strip():
            start_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
            end_str = now.strftime("%Y-%m-%d %H:%M:%S")

            headers = {
                "Accept": "application/json",
                "Authorization": f"Bearer {api_token.strip()}",
                "X-API-VERSION": "1.0",
            }

            groww_symbol = f"{exchange.upper()}-{symbol.upper()}"

            try:
                r = requests.get(
                    f"{GROWW_BASE}/v1/historical/candles",
                    headers=headers,
                    params={
                        "exchange": exchange.upper(),
                        "segment": "CASH",
                        "groww_symbol": groww_symbol,
                        "start_time": start_str,
                        "end_time": end_str,
                        "candle_interval": f"{minutes}minute",
                    },
                    timeout=15,
                )

                if r.status_code == 200:
                    payload = r.json().get("payload", {})
                    candles = payload.get("candles", [])
                    if candles:
                        return _parse_groww_candles(candles)
            except Exception as e:
                logger.debug(f"Groww endpoint failed: {e}")

        # Unauthenticated charting service (works without API token)
        try:
            url = f"https://groww.in/v1/api/charting_service/v2/chart/exchange/{exchange.upper()}/segment/CASH/{symbol.upper()}"
            params = {
                "endTimeInMillis": int(now.timestamp() * 1000),
                "intervalInMinutes": minutes,
                "startTimeInMillis": int(start_dt.timestamp() * 1000),
            }
            r2 = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, params=params, timeout=15)
            if r2.status_code == 200:
                candles = r2.json().get("candles", [])
                if candles:
                    return _parse_groww_candles(candles)
        except Exception as e:
            logger.debug(f"Charting Service fallback failed: {e}")

    except Exception as e:
        logger.error(f"Error fetching Groww OHLCV: {e}")
    
    return pd.DataFrame()

def _parse_groww_candles(candles: list) -> pd.DataFrame:
    """Parse Groww candle data into DataFrame."""
    rows = []
    for c in candles:
        try:
            ts = c[0]
            if isinstance(ts, str):
                ts = int(datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").timestamp())
            
            rows.append({
                "time": int(ts),
                "open": float(c[1]) if len(c) > 1 else 0,
                "high": float(c[2]) if len(c) > 2 else 0,
                "low": float(c[3]) if len(c) > 3 else 0,
                "close": float(c[4]) if len(c) > 4 else 0,
                "volume": float(c[5]) if len(c) > 5 else 0.0
            })
        except Exception:
            continue

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).sort_values("time").reset_index(drop=True)
    df["date"] = pd.to_datetime(df["time"], unit="s")
    df.set_index("date", inplace=True)
    df.drop(columns=["time"], errors="ignore", inplace=True)
    return df

# ─── yfinance Fallback ───────────────────────────────────────────────────────

def fetch_ohlcv_yfinance_for_indices(symbol: str, tf_key: str, limit: int = 300) -> pd.DataFrame:
    """Fallback: fetch OHLCV via verified Yahoo tickers or constituent proxy."""
    try:
        from app.market_pulse.index_ohlcv import fetch_index_ohlcv_for_interval

        df = fetch_index_ohlcv_for_interval(symbol, tf_key, limit=limit)
        if df is not None and not df.empty:
            return df
        logger.debug(f"No index OHLC for {symbol} ({tf_key})")
        return pd.DataFrame()
    except Exception as e:
        logger.debug(f"yfinance fallback failed for index {symbol}: {e}")
        return pd.DataFrame()

def fetch_ohlcv_yfinance_for_tickers(symbol: str, tf_key: str, limit: int = 300) -> pd.DataFrame:
    """Fallback: fetch OHLCV via yfinance for individual stock tickers (not just indices).
    Supports weekly (1w) and monthly (1M) timeframes that Groww API does not provide."""
    try:
        import yfinance as yf
        from app.market_pulse.nse_index_yfinance import stock_symbol_to_yf

        sym = symbol.upper().strip()
        yf_ticker = sym if sym.endswith(".BO") else stock_symbol_to_yf(sym)
        yf_candidates = [yf_ticker]

        yf_map = {
            "1m": ("7d", "1m"),
            "5m": ("60d", "5m"),
            "10m": ("60d", "5m"),   # resample from 5m
            "15m": ("60d", "15m"),
            "30m": ("60d", "30m"),
            "1h": ("730d", "1h"),
            "4h": ("730d", "1h"),   # resample from 1h
            "1d": ("5y", "1d"),
            "1w": ("10y", "1wk"),
            "1M": ("max", "1mo"),
        }
        period, interval = yf_map.get(tf_key, ("1y", "1d"))

        data = pd.DataFrame()
        for try_ticker in yf_candidates:
            data = yf.download(
                try_ticker, period=period, interval=interval,
                progress=False, auto_adjust=True, threads=False,
            )
            if not data.empty:
                yf_ticker = try_ticker
                break

        if data.empty:
            logger.debug(f"yfinance returned empty for ticker {symbol} (tried {yf_candidates})")
            return pd.DataFrame()

        # Flatten MultiIndex columns if present
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = [c[0] for c in data.columns]

        df = data[["Open", "High", "Low", "Close", "Volume"]].rename(columns={
            "Open": "open", "High": "high", "Low": "low",
            "Close": "close", "Volume": "volume"
        }).tail(limit)

        # Resample for 4h/10m if needed
        if tf_key == "4h" and interval == "1h":
            df = df.resample("4h").agg({
                "open": "first", "high": "max",
                "low": "min", "close": "last", "volume": "sum"
            }).dropna().tail(limit)

        logger.debug(f"Successfully fetched {len(df)} candles for ticker {symbol} ({tf_key}) from yfinance")
        return df
    except Exception as e:
        logger.debug(f"yfinance fallback failed for ticker {symbol}: {e}")
        return pd.DataFrame()

def calculate_pcr_estimate(df: pd.DataFrame, price_change: float) -> float:
    """Estimate PCR (Put Call Ratio) based on volatility and price movement.
    
    PCR typically ranges from 0.5 (bullish) to 2.0+ (bearish).
    We estimate it from:
    - Volatility (standard deviation of returns)
    - Price momentum (positive change = lower PCR, negative = higher PCR)
    """
    try:
        if df.empty or len(df) < 3:
            return 1.0
        
        # Calculate returns
        closes = df['close'].values
        returns = np.diff(closes) / closes[:-1] * 100
        
        # Calculate volatility (annualized-like metric)
        volatility = np.std(returns) if len(returns) > 0 else 0
        
        # Base PCR influenced by volatility (higher vol = higher PCR = more protective puts)
        base_pcr = 0.8 + (volatility / 100)  # Range ~0.8 to 2.0+ based on vol
        
        # Adjust based on price momentum
        # Positive momentum reduces PCR (bullish sentiment), negative increases it (bearish)
        momentum_factor = 1.0 - (price_change / 100)  # Convert change % to adjustment
        pcr = max(0.5, min(3.0, base_pcr * momentum_factor))
        
        return pcr
    except Exception as e:
        logger.debug(f"PCR calculation failed: {e}")
        return 1.0

# ─── Support & Resistance ───────────────────────────────────────────────────

def calculate_support_resistance(df: pd.DataFrame, lookback: int = 20) -> tuple:
    """Calculate support and resistance levels from recent data."""
    if df.empty or len(df) < lookback:
        return None, None
    
    recent = df.tail(lookback)
    support = recent['low'].min()
    resistance = recent['high'].max()
    
    return support, resistance

# ─── CoinDCX API Functions ───────────────────────────────────────────────────

def fetch_coindcx_ohlcv(symbol, resolution, limit=1000, start_ts=None, end_ts=None):
    """Fetch OHLCV data from CoinDCX Futures API (USDT-margined perpetuals).

    Optional ``start_ts`` / ``end_ts`` (unix seconds) pin the candle window;
    otherwise lookback is derived from ``limit`` × resolution.
    """
    if symbol:
        clean_base = symbol.replace("B-", "").replace("-", "").replace("_", "").replace("USDT", "").upper()
        symbol = f"B-{clean_base}_USDT"

    url = "https://public.coindcx.com/market_data/candlesticks"
    
    res_map = {"1m": "1", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "60m": "60", "4h": "240", "1d": "1D", "1w": "1W"}
    res = res_map.get(resolution, resolution)

    _res_secs = {
        "1": 60, "5": 300, "15": 900, "30": 1800, "60": 3600,
        "240": 14400, "1D": 86400, "1W": 604800,
    }
    res_sec = _res_secs.get(res, 3600)
    lookback = max(int(limit), 1) * res_sec
    
    import time
    end = int(end_ts) if end_ts is not None else int(time.time())
    start = int(start_ts) if start_ts is not None else (end - lookback)
    if start >= end:
        start = end - lookback

    params = {
        "pair": symbol,
        "from": start,
        "to": end,
        "resolution": res,
        "pcode": "f"
    }

    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        if data.get("s") != "ok":
            logger.warning(f"CoinDCX API error: {data.get('message')}")
            return pd.DataFrame()

        candles = data.get("data", [])
        if not candles:
            return pd.DataFrame()

        rows = []
        for c in candles:
            rows.append({
                "time": int(c["time"] / 1000),
                "open": float(c["open"]),
                "high": float(c["high"]),
                "low": float(c["low"]),
                "close": float(c["close"]),
                "volume": float(c["volume"])
            })

        df = pd.DataFrame(rows).sort_values("time").reset_index(drop=True)
        if limit and len(df) > int(limit):
            df = df.tail(int(limit)).reset_index(drop=True)
        logger.info(f"✅ Fetched {len(df)} candles for {symbol}")
        return df
    except Exception as e:
        logger.error(f"Error fetching CoinDCX candles: {e}")
        return pd.DataFrame()


def coindcx_ohlcv_indexed(
    symbol: str,
    resolution: str,
    limit: int = 1000,
    *,
    start_ts: float | int | None = None,
    end_ts: float | int | None = None,
) -> pd.DataFrame:
    """CoinDCX futures OHLCV with a datetime index (open/high/low/close/volume)."""
    from app.market_pulse.data_source_ctx import mark_source

    raw = fetch_coindcx_ohlcv(symbol, resolution, limit=limit, start_ts=start_ts, end_ts=end_ts)
    if raw is None or raw.empty:
        return pd.DataFrame()

    df = raw.copy()
    if "time" in df.columns:
        df["date"] = pd.to_datetime(df["time"], unit="s", utc=True).dt.tz_localize(None)
        df = df.set_index("date")
        df = df.drop(columns=["time"], errors="ignore")
    else:
        df.index = pd.to_datetime(df.index)

    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    out = df.dropna(subset=["close"])
    if out.empty:
        return pd.DataFrame()
    keep = [c for c in ("open", "high", "low", "close", "volume") if c in out.columns]
    return mark_source(out[keep].sort_index(), "coindcx")

def _coindcx_sym_key(sym: str) -> str:
    """Canonical key for matching B-BTCUSDT vs B-BTC_USDT."""
    return (sym or "").upper().replace("_", "").replace("-", "")


def fetch_coindcx_futures_snapshot() -> list[dict]:
    """Live CoinDCX USDT futures snapshot — price, exchange 24h % change, volume, NY-session range %."""
    try:
        url = "https://public.coindcx.com/market_data/v3/current_prices/futures/rt"
        resp = requests.get(url, timeout=12).json()
        prices = resp.get("prices", {}) or {}
        rows: list[dict] = []
        for sym, item in prices.items():
            if not sym or not isinstance(item, dict):
                continue
            price = float(item.get("ls", 0) or 0)
            if price <= 0:
                continue
            change = float(item.get("pc", 0) or 0)
            volume = float(item.get("v", 0) or 0)
            hi = float(item.get("h", 0) or 0)
            lo = float(item.get("l", 0) or 0)
            range_pct = ((hi - lo) / lo * 100) if lo > 0 and hi >= lo else abs(change)
            base = sym.replace("B-", "").replace("_USDT", "").replace("USDT", "")
            rows.append({
                "sym": sym,
                "display": f"{base}-USDT",
                "name": base,
                "price": price,
                "change": change,
                "volume": volume,
                "range_pct": range_pct,
                "high": hi if hi > 0 else None,
                "low": lo if lo > 0 else None,
            })
        return rows
    except Exception as exc:
        logger.error("CoinDCX futures snapshot failed: %s", exc)
        return []


def coindcx_leader_pairs(bucket: str, top_n: int = 15) -> list[tuple[str, str]]:
    """Map leader bucket label to (display_name, api_symbol) pairs."""
    snap = fetch_coindcx_futures_snapshot()
    if not snap:
        return []
    n = max(1, int(top_n))
    if bucket == "Top Volume":
        ranked = sorted(snap, key=lambda x: x["volume"], reverse=True)
    elif bucket == "Top Volatile":
        ranked = sorted(snap, key=lambda x: max(abs(x["change"]), x["range_pct"]), reverse=True)
    elif bucket == "Top Risen":
        ranked = sorted([x for x in snap if x["change"] > 0], key=lambda x: x["change"], reverse=True)
    elif bucket == "Top Fallen":
        ranked = sorted([x for x in snap if x["change"] < 0], key=lambda x: x["change"])
    else:
        return []
    return [(r["display"], r["sym"]) for r in ranked[:n]]


def coindcx_leader_tables(
    symbols: set[str] | None = None,
    top_n: int = 10,
) -> dict[str, list[dict]]:
    """Top Volume / Volatile / Risen / Fallen rows, optionally filtered to symbol set."""
    snap = fetch_coindcx_futures_snapshot()
    if symbols:
        keys = {_coindcx_sym_key(s) for s in symbols}
        snap = [r for r in snap if _coindcx_sym_key(r["sym"]) in keys]
    if not snap:
        return {}

    n = max(1, int(top_n))

    def _row(r: dict) -> dict:
        return {
            "Pair": r["display"],
            "Price ($)": f"${r['price']:.6f}",
            "Change %": f"{r['change']:+.2f}%",
            "Volume": f"{r['volume']:,.0f}",
            "Range %": f"{r['range_pct']:.2f}%",
        }

    top_vol = sorted(snap, key=lambda x: x["volume"], reverse=True)[:n]
    top_volatile = sorted(
        snap, key=lambda x: max(abs(x["change"]), x["range_pct"]), reverse=True,
    )[:n]
    top_risen = sorted([x for x in snap if x["change"] > 0], key=lambda x: x["change"], reverse=True)[:n]
    top_fallen = sorted([x for x in snap if x["change"] < 0], key=lambda x: x["change"])[:n]

    return {
        "Top Volume": [_row(r) for r in top_vol],
        "Top Volatile": [_row(r) for r in top_volatile],
        "Top Risen": [_row(r) for r in top_risen],
        "Top Fallen": [_row(r) for r in top_fallen],
    }


def get_coindcx_gainers():
    """Get top gainers from CoinDCX."""
    snap = fetch_coindcx_futures_snapshot()
    if not snap:
        return [], []
    gainers = sorted([x for x in snap if x["change"] > 0], key=lambda x: x["change"], reverse=True)
    losers = sorted([x for x in snap if x["change"] <= 0], key=lambda x: x["change"])
    gainers_out = [{"sym": x["sym"], "change": x["change"], "price": x["price"]} for x in gainers]
    losers_out = [{"sym": x["sym"], "change": x["change"], "price": x["price"]} for x in losers]
    return gainers_out, losers_out

# ─── Heatmap Data Generators ────────────────────────────────────────────────

def generate_groww_sectoral_heatmap(groww_token: str, exchange: str, timeframe: str) -> list:
    """Generate heatmap data for all 12 sectoral indices with enhanced metrics."""
    indices_to_scan = list(SECTORAL_INDICES.keys())
    data_list = []
    
    logger.info(f"Starting heatmap generation for {len(indices_to_scan)} indices with timeframe={timeframe}, token={'provided' if groww_token else 'missing'}")
    
    for idx_num, name in enumerate(indices_to_scan, 1):
        try:
            syms = SECTORAL_INDICES.get(name, ["NIFTY"])
            price, change, vol_change = 0.0, 0.0, 0.0
            success = False
            support, resistance = None, None
            
            logger.debug(f"[{idx_num}/{len(indices_to_scan)}] Processing {name}, symbol variants: {syms}")
            
            for sym in syms:
                try:
                    price, change, vol = fetch_groww_ticker_stats(sym, exchange, groww_token)
                    df_candles = fetch_groww_ohlcv(sym, exchange, timeframe, groww_token, limit=30)
                    
                    # Fallback to yfinance for indices if Groww OHLCV fails
                    if df_candles.empty:
                        logger.debug(f"Groww OHLCV failed for {name}, trying yfinance...")
                        df_candles = fetch_ohlcv_yfinance_for_indices(sym, timeframe, limit=30)
                    
                    ch_val = float(change) if change else 0.0
                    
                    # Always try to use OHLCV for intraday change calculation (more accurate)
                    if timeframe != "1d" and not df_candles.empty and len(df_candles) >= 2:
                        c_last = float(df_candles['close'].iloc[-1])
                        c_prev = float(df_candles['close'].iloc[-2])
                        if c_prev > 0:
                            ch_val = ((c_last - c_prev) / c_prev) * 100
                            # If stats fetch failed but we have OHLCV data, use it
                            if price == 0.0:
                                price = c_last
                    
                    vol_ch = 0.0
                    if not df_candles.empty and len(df_candles) >= 2:
                        # Calculate volume change using recent candles
                        lookback_v = min(10, len(df_candles) - 1)
                        if lookback_v >= 1:
                            try:
                                avg_v = df_candles['volume'].iloc[-lookback_v-1:-1].mean()
                                latest_v = df_candles['volume'].iloc[-1]
                                if avg_v > 0 and latest_v > 0:
                                    vol_ch = ((latest_v - avg_v) / avg_v) * 100
                                    logger.debug(f"Volume change for {name}: latest_v={latest_v:.0f}, avg_v={avg_v:.0f}, vol_ch={vol_ch:.0f}%")
                            except Exception as e:
                                logger.debug(f"Volume calculation failed for {name}: {e}")
                                vol_ch = 0.0
                    
                    # Calculate support and resistance
                    if not df_candles.empty:
                        support, resistance = calculate_support_resistance(df_candles, lookback=20)
                    
                    # Accept data if we have price from live API or calculated from OHLCV
                    # For indices, live_price might be 0.0 if they're derivative, use OHLCV price
                    final_price = price if price > 0 else (float(df_candles['close'].iloc[-1]) if not df_candles.empty else 0.0)
                    
                    if final_price > 0:
                        price = final_price
                        change = ch_val
                        vol_change = vol_ch
                        success = True
                        logger.debug(f"✓ {name} ({sym}): price={price:.2f}, change={change:+.2f}%, vol_change={vol_change:+.0f}%")
                        break
                    elif not df_candles.empty:
                        # If we have OHLCV data but no live price, still use it
                        price = float(df_candles['close'].iloc[-1])
                        change = ch_val
                        vol_change = vol_ch
                        success = True
                        logger.debug(f"✓ {name} ({sym}, OHLCV only): price={price:.2f}, change={change:+.2f}%, vol_change={vol_change:+.0f}%")
                        break
                except Exception as sym_err:
                    logger.debug(f"Failed for {name} with symbol {sym}: {sym_err}")
            
            if success:
                # Calculate PCR based on volatility and momentum
                pcr = calculate_pcr_estimate(df_candles, change) if not df_candles.empty else 1.0
                
                data_list.append({
                    "ticker": name,
                    "price": price,
                    "change": change,
                    "vol_change": vol_change,
                    "support": support,
                    "resistance": resistance,
                    "pcr": pcr,
                    "last_price": price
                })
            else:
                # Log when we couldn't get data for an index
                logger.warning(f"✗ No data retrieved for index {name} - all symbol variants failed")
        except Exception as e:
            logger.error(f"Error processing {name}: {e}")
    
    logger.info(f"Heatmap generation complete: {len(data_list)}/{len(indices_to_scan)} indices retrieved successfully")
    if len(data_list) == 0:
        logger.error("CRITICAL: No heatmap data retrieved! Check token validity and API connectivity")
    return data_list

def generate_groww_ticker_heatmap(tickers: list, groww_token: str, exchange: str, timeframe: str) -> list:
    """Generate heatmap data for selected tickers."""
    data_list = []
    
    for t in tickers:
        try:
            price, change, volume = fetch_groww_ticker_stats(t, exchange, groww_token)
            df_candles = fetch_groww_ohlcv(t, exchange, timeframe, groww_token, limit=30)
            
            ch_val = 0.0
            if change:
                ch_val = float(change)
            
            # Always try to use OHLCV for intraday change calculation (more accurate)
            if timeframe != "1d" and not df_candles.empty and len(df_candles) >= 2:
                c_last = float(df_candles['close'].iloc[-1])
                c_prev = float(df_candles['close'].iloc[-2])
                if c_prev > 0:
                    ch_val = ((c_last - c_prev) / c_prev) * 100
                    # If stats fetch failed but we have OHLCV data, use it
                    if price == 0.0:
                        price = c_last
            
            v_ch_val = 0.0
            if not df_candles.empty and len(df_candles) >= 2:
                # Calculate volume change using recent candles
                lookback_v = min(10, len(df_candles) - 1)
                if lookback_v >= 1:
                    try:
                        avg_v = df_candles['volume'].iloc[-lookback_v-1:-1].mean()
                        latest_v = df_candles['volume'].iloc[-1]
                        if avg_v > 0 and latest_v > 0:
                            v_ch_val = ((latest_v - avg_v) / avg_v) * 100
                    except Exception:
                        v_ch_val = 0.0
            
            support, resistance = None, None
            if not df_candles.empty:
                support, resistance = calculate_support_resistance(df_candles, lookback=20)
            
            # Only add if we have valid price data
            if price > 0:
                pcr = calculate_pcr_estimate(df_candles, ch_val) if not df_candles.empty else 1.0
                
                data_list.append({
                    "ticker": t,
                    "price": price,
                    "change": ch_val,
                    "vol_change": v_ch_val,
                    "support": support,
                    "resistance": resistance,
                    "pcr": pcr,
                    "last_price": price
                })
        except Exception as e:
            logger.error(f"Heatmap fetch failed for {t}: {e}")
    
    return data_list

def generate_crypto_heatmap(crypto_tickers: list, timeframe: str) -> list:
    """Generate heatmap data for crypto pairs."""
    crypto_data_list = []
    
    # Fetch real-time prices
    real_market_data = []
    try:
        url_rt = "https://public.coindcx.com/market_data/v3/current_prices/futures/rt"
        resp_rt = requests.get(url_rt, timeout=10).json()
        prices = resp_rt.get("prices", {})
        for sym, data in prices.items():
            real_market_data.append({
                "symbol": sym,
                "price": float(data.get("ls", 0)),
                "change_24h": float(data.get("pc", 0))
            })
    except Exception as e:
        logger.error(f"Live CoinDCX price fetch failed: {e}")
    
    for sym in crypto_tickers:
        try:
            disp = sym.replace("B-", "").replace("_", "")
            price_val = 0.0
            change_val = 0.0
            
            for item in real_market_data:
                if item["symbol"] == sym:
                    price_val = item["price"]
                    change_val = item["change_24h"]
                    break
            
            df_candles = fetch_coindcx_ohlcv(sym, timeframe, limit=30)
            
            ch_val = 0.0
            if change_val:
                ch_val = float(change_val)
            
            # Always try to use OHLCV for intraday change calculation (more accurate)
            if timeframe != "1d" and not df_candles.empty and len(df_candles) >= 2:
                c_last = float(df_candles['close'].iloc[-1])
                c_prev = float(df_candles['close'].iloc[-2])
                if c_prev > 0:
                    ch_val = ((c_last - c_prev) / c_prev) * 100
                    # If real-time price fetch failed but we have OHLCV data, use it
                    if price_val == 0.0:
                        price_val = c_last
            
            v_ch_val = 0.0
            if not df_candles.empty and len(df_candles) >= 2:
                # Calculate volume change using recent candles
                lookback_v = min(10, len(df_candles) - 1)
                if lookback_v >= 1:
                    try:
                        avg_v = df_candles['volume'].iloc[-lookback_v-1:-1].mean()
                        latest_v = df_candles['volume'].iloc[-1]
                        if avg_v > 0 and latest_v > 0:
                            v_ch_val = ((latest_v - avg_v) / avg_v) * 100
                    except Exception:
                        v_ch_val = 0.0
            
            support, resistance = None, None
            if not df_candles.empty:
                support, resistance = calculate_support_resistance(df_candles, lookback=20)
            
            # Only add if we have valid price data
            if price_val > 0:
                pcr = calculate_pcr_estimate(df_candles, ch_val) if not df_candles.empty else 1.0
                crypto_data_list.append({
                    "ticker": disp,
                    "price": price_val,
                    "change": ch_val,
                    "vol_change": v_ch_val,
                    "support": support,
                    "resistance": resistance,
                    "pcr": pcr,
                    "last_price": price_val
                })
        except Exception as e:
            logger.error(f"Crypto heatmap fetch failed: {e}")
    
    return crypto_data_list
