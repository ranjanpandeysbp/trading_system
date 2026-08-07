"""
advance_decline_graph_engine.py
--------------------------------
Command Center — Advance Decline Graph (multi-asset).

Reconstructs market-breadth (advances / declines / unchanged) for an index
universe from constituent OHLCV — exchanges often do not publish a historical
A/D time series API.

Asset classes: india (NSE indices), us (Dow / Nasdaq / S&P / ETFs), crypto
(CoinDCX USDT majors).

Modes
  daily     — for each session date in [from_date, to_date], count how many
              constituents closed up / down / flat vs the prior session close.
  intraday  — for a chosen session date + timeframe, at each bar timestamp
              (truncated to optional as_of HH:MM in local market time), count
              how many constituents printed up / down / flat vs previous bar.

Also returns a cumulative A/D line (running sum of advances − declines).
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, time
from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.nifty_index_constituents import get_index_constituent_symbols
from app.market_pulse.ticker_utils import (
    COINDCX_USDT_TICKERS,
    CRYPTO_MARKET,
    GROWW_MARKET,
    INDEX_OPTIONS,
    US_MARKET,
)

logger = logging.getLogger(__name__)

INTRADAY_TIMEFRAMES = ["5m", "10m", "15m", "30m", "1h"]
_MAX_WORKERS = 12
# Soft cap — large universes are allowed but slow; FE warns above this.
_WARN_UNIVERSE = 120
_HARD_CAP = 100  # max constituents fetched per run (keeps multi-asset scans usable)
# Cap for charting when declines == 0 (infinite ratio) so the Y-axis stays readable.
_AD_RATIO_CAP = 10.0

# Session clocks (local market wall time after timezone normalize)
_SESSION = {
    "india": (time(9, 15), time(15, 30), "Asia/Kolkata", "IST"),
    "us": (time(9, 30), time(16, 0), "America/New_York", "ET"),
    "crypto": (None, None, "UTC", "UTC"),
}


def _ad_ratio(advances: int, declines: int) -> float | None:
    """Advances ÷ Declines. Neutral = 1.0. Capped when declines are zero."""
    if advances <= 0 and declines <= 0:
        return None
    if declines <= 0:
        return round(min(_AD_RATIO_CAP, float(max(advances, 1))), 3)
    return round(min(_AD_RATIO_CAP, advances / declines), 3)


def list_index_names(asset_class: str = "india") -> list[str]:
    """Universe picker labels for the given asset class."""
    ac = (asset_class or "india").strip().lower()
    if ac == "us":
        preferred = [
            "Dow 30",
            "Nasdaq 100",
            "S&P 100",
            "S&P 500",
            "US Index ETFs (SPY/QQQ/DIA/IWM)",
        ]
        try:
            from app.market_pulse.us_index_constituents import get_us_index_options

            opts = get_us_index_options()
        except Exception:
            opts = {}
        # Map short labels → first matching key in opts
        out: list[str] = []
        for short in preferred:
            if short in opts:
                out.append(short)
                continue
            match = next((k for k in opts if k.startswith(short) or short in k), None)
            if match and match not in out:
                out.append(match)
        for k in opts:
            if k not in out and "Russell" not in k and "Mid Cap" not in k and "Small Cap" not in k:
                # skip huge duplicates already covered
                if k.startswith("US Large") or k.startswith("US Megacap"):
                    continue
                out.append(k)
        return out or preferred

    if ac == "crypto":
        return [
            "Top 30 Crypto",
            "Top 50 Crypto",
            "Top 100 Crypto",
            "Majors (ex-BTC)",
        ]

    # india (default)
    skip = {"Default Groww Tickers", "High Vol ETF"}
    names = [k for k in INDEX_OPTIONS.keys() if k not in skip]
    preferred = [
        "NIFTY 50",
        "NIFTY BANK",
        "NIFTY NEXT 50",
        "NIFTY IT",
        "NIFTY FINANCIAL SERVICES",
        "NIFTY MIDCAP 150",
        "NIFTY SMALLCAP 250",
        "NIFTY 500",
    ]
    ordered = [n for n in preferred if n in names]
    ordered += [n for n in names if n not in ordered]
    return ordered


def resolve_universe_symbols(asset_class: str, index_name: str) -> list[str]:
    """Constituent symbols for A/D breadth (capped)."""
    ac = (asset_class or "india").strip().lower()
    name = (index_name or "").strip()

    if ac == "us":
        try:
            from app.market_pulse.us_index_constituents import get_us_index_options

            opts = get_us_index_options()
        except Exception:
            opts = {}
        symbols = list(opts.get(name) or [])
        if not symbols:
            # fuzzy: Dow 30 / Nasdaq 100 / S&P 100 / S&P 500
            for k, v in opts.items():
                if name.lower() in k.lower() or k.lower().startswith(name.lower()):
                    symbols = list(v)
                    break
        if not symbols and "ETF" in name.upper():
            symbols = ["SPY", "QQQ", "DIA", "IWM", "MDY", "XLF", "XLK", "XLE", "XLV", "XLI"]
        return symbols[:_HARD_CAP]

    if ac == "crypto":
        tickers = list(COINDCX_USDT_TICKERS)
        if name.startswith("Top 30"):
            return tickers[:30]
        if name.startswith("Top 50"):
            return tickers[:50]
        if name.startswith("Top 100"):
            return tickers[:100]
        if "Majors" in name:
            majors = [
                "B-ETHUSDT", "B-SOLUSDT", "B-XRPUSDT", "B-BNBUSDT", "B-ADAUSDT",
                "B-AVAXUSDT", "B-DOGEUSDT", "B-LINKUSDT", "B-DOTUSDT", "B-MATICUSDT",
                "B-NEARUSDT", "B-LTCUSDT", "B-ATOMUSDT", "B-UNIUSDT", "B-AAVEUSDT",
            ]
            return [t for t in majors if t in tickers] or tickers[1:16]
        return tickers[:50]

    # india
    return list(get_index_constituent_symbols(name) or [])[:_HARD_CAP]


def _currency_for(asset_class: str) -> str:
    ac = (asset_class or "india").strip().lower()
    if ac in ("us", "crypto"):
        return "$"
    return "₹"


# Display index name → NSE F&O option-chain symbol (exact INDEX_CHOICES only for live OC)
_AD_INDEX_OC: dict[str, str] = {
    "NIFTY 50": "NIFTY",
    "NIFTY BANK": "BANKNIFTY",
    "NIFTY FINANCIAL SERVICES": "FINNIFTY",
    "NIFTY FIN SERVICE": "FINNIFTY",
    "NIFTY FINANCIAL SERVICES 25/50": "FINNIFTY",
    "NIFTY MIDCAP SELECT": "MIDCPNIFTY",
    "NIFTY NEXT 50": "NIFTYNXT50",
}


def _oc_symbol_for_index(index_name: str) -> str | None:
    name = (index_name or "").strip()
    if not name:
        return None
    if name in _AD_INDEX_OC:
        return _AD_INDEX_OC[name]
    upper = name.upper()
    # Exact F&O symbols typed directly
    from app.market_pulse.option_chain_engine import INDEX_CHOICES

    if upper in INDEX_CHOICES:
        return upper
    # Soft match preferred F&O names
    for key, sym in _AD_INDEX_OC.items():
        if key in name or name in key:
            return sym
    return None


def _options_snapshot(
    asset_class: str,
    index_name: str,
    *,
    groww_token: str = "",
) -> dict[str, Any]:
    """Live index options PCR / OI snapshot (India F&O only). Soft-fails otherwise."""
    ac = (asset_class or "india").strip().lower()
    if ac == "crypto":
        return {"available": False, "reason": "Crypto has no listed options feed in this app."}
    if ac == "us":
        return {
            "available": False,
            "reason": "US options chain is not wired into Advance Decline yet — India F&O only.",
        }
    if ac != "india":
        return {"available": False, "reason": f"Options not supported for asset class '{ac}'."}

    oc_sym = _oc_symbol_for_index(index_name)
    if not oc_sym:
        return {
            "available": False,
            "reason": (
                f"No F&O option chain mapped for '{index_name}'. "
                "Try NIFTY 50, NIFTY BANK, FINNIFTY, MIDCPNIFTY, or NIFTY NEXT 50."
            ),
        }

    try:
        from app.market_pulse.option_chain_engine import (
            classify_option_chain_signal,
            fetch_option_chain,
        )

        chain = fetch_option_chain(oc_sym, True, groww_token)
    except Exception as exc:
        logger.warning("A/D options fetch failed for %s: %s", oc_sym, exc)
        return {"available": False, "oc_symbol": oc_sym, "reason": f"Option chain fetch failed: {exc}"}

    if not chain:
        return {
            "available": False,
            "oc_symbol": oc_sym,
            "reason": f"No option chain data returned for {oc_sym}.",
        }

    try:
        signal = classify_option_chain_signal(chain)
    except Exception as exc:
        logger.debug("A/D options classify failed for %s: %s", oc_sym, exc)
        signal = {}

    top_call = (chain.get("top_call_oi") or [{}])[0] if chain.get("top_call_oi") else {}
    top_put = (chain.get("top_put_oi") or [{}])[0] if chain.get("top_put_oi") else {}

    return {
        "available": True,
        "oc_symbol": oc_sym,
        "underlying": chain.get("underlying"),
        "current_expiry": chain.get("current_expiry"),
        "pcr_oi": chain.get("pcr_oi"),
        "pcr_vol": chain.get("pcr_vol"),
        "total_call_oi": chain.get("total_call_oi"),
        "total_put_oi": chain.get("total_put_oi"),
        "total_call_vol": chain.get("total_call_vol"),
        "total_put_vol": chain.get("total_put_vol"),
        "max_pain": chain.get("max_pain"),
        "support": signal.get("support"),
        "resistance": signal.get("resistance"),
        "bias": signal.get("bias"),
        "trade_signal": signal.get("trade_signal"),
        "confidence_pct": signal.get("confidence_pct"),
        "top_call_oi_strike": top_call.get("strike"),
        "top_put_oi_strike": top_put.get("strike"),
        "source": chain.get("source"),
        "plain_english": (
            f"{oc_sym} options: PCR(OI) {chain.get('pcr_oi')}, "
            f"bias {signal.get('bias') or '—'}, "
            f"max pain {chain.get('max_pain')}, "
            f"expiry {chain.get('current_expiry') or '—'}."
        ),
    }


def _market_for(asset_class: str) -> str:
    ac = (asset_class or "india").strip().lower()
    if ac == "us":
        return US_MARKET
    if ac == "crypto":
        return CRYPTO_MARKET
    return GROWW_MARKET


def _session_meta(asset_class: str) -> tuple[time | None, time | None, str, str]:
    ac = (asset_class or "india").strip().lower()
    return _SESSION.get(ac, _SESSION["india"])


def _parse_date(s: str) -> datetime:
    return datetime.strptime(s.strip()[:10], "%Y-%m-%d")


def _to_local_index(idx: pd.DatetimeIndex, tz_name: str) -> pd.DatetimeIndex:
    """Normalize bar times to market local wall clock (tz-naive).

    Upstream candles often arrive as naive UTC unix stamps — map through UTC → local.
    """
    if not isinstance(idx, pd.DatetimeIndex):
        idx = pd.to_datetime(idx)
    if getattr(idx, "tz", None) is not None:
        return idx.tz_convert(tz_name).tz_localize(None)
    return idx.tz_localize("UTC").tz_convert(tz_name).tz_localize(None)


def _in_session(ts: pd.Timestamp, asset_class: str) -> bool:
    open_t, close_t, _tz, _label = _session_meta(asset_class)
    if open_t is None or close_t is None:
        return True  # crypto 24h
    t = pd.Timestamp(ts).to_pydatetime().time()
    return open_t <= t <= close_t


def _normalize_ohlcv(df: pd.DataFrame, asset_class: str = "india") -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        if "date" in out.columns:
            out["date"] = pd.to_datetime(out["date"])
            out = out.set_index("date")
        elif "time" in out.columns:
            out["time"] = pd.to_datetime(out["time"])
            out = out.set_index("time")
        else:
            out.index = pd.to_datetime(out.index)
    out = out.sort_index()
    _o, _c, tz_name, _lbl = _session_meta(asset_class)
    out.index = _to_local_index(out.index, tz_name)
    cols = {c.lower(): c for c in out.columns}
    if "close" not in cols and "Close" in out.columns:
        out = out.rename(columns={"Close": "close", "Open": "open", "High": "high", "Low": "low"})
    if "close" not in out.columns:
        return pd.DataFrame()
    return out


def _fetch_symbol(
    symbol: str,
    timeframe: str,
    *,
    market: str,
    groww_token: str,
    exchange: str,
    limit: int,
    asset_class: str = "india",
) -> tuple[str, pd.DataFrame]:
    try:
        raw = fetch_data_for_gap_scan(
            symbol, timeframe, market, groww_token=groww_token, exchange=exchange, limit=limit,
        )
        return symbol, _normalize_ohlcv(raw, asset_class)
    except Exception as exc:
        logger.debug("A/D fetch failed for %s %s: %s", symbol, timeframe, exc)
        return symbol, pd.DataFrame()


def _fetch_many(
    symbols: list[str],
    timeframe: str,
    *,
    market: str,
    groww_token: str,
    exchange: str,
    limit: int,
    asset_class: str = "india",
) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    workers = min(_MAX_WORKERS, max(1, len(symbols)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [
            pool.submit(
                _fetch_symbol, sym, timeframe,
                market=market, groww_token=groww_token, exchange=exchange, limit=limit,
                asset_class=asset_class,
            )
            for sym in symbols
        ]
        for fut in as_completed(futs):
            sym, df = fut.result()
            if not df.empty:
                out[sym] = df
    return out


def _daily_series(
    frames: dict[str, pd.DataFrame],
    from_dt: datetime,
    to_dt: datetime,
) -> list[dict[str, Any]]:
    # date(str) -> advances/declines + volume_up/volume_down
    buckets: dict[str, dict[str, int]] = {}
    for _sym, df in frames.items():
        if "close" not in df.columns or len(df) < 2:
            continue
        closes = df["close"].astype(float)
        has_vol = "volume" in df.columns
        vols = df["volume"].astype(float) if has_vol else None
        prev_c = closes.shift(1)
        prev_v = vols.shift(1) if vols is not None else None
        for i, (ts, close, pclose) in enumerate(zip(closes.index, closes.values, prev_c.values)):
            if pd.isna(pclose):
                continue
            d = pd.Timestamp(ts).to_pydatetime().date()
            if d < from_dt.date() or d > to_dt.date():
                continue
            key = d.isoformat()
            bucket = buckets.setdefault(
                key,
                {
                    "advances": 0, "declines": 0, "unchanged": 0,
                    "volume_up": 0, "volume_down": 0, "volume_flat": 0,
                },
            )
            if close > pclose:
                bucket["advances"] += 1
            elif close < pclose:
                bucket["declines"] += 1
            else:
                bucket["unchanged"] += 1
            if vols is not None and prev_v is not None:
                vol = float(vols.iloc[i])
                pvol = float(prev_v.iloc[i]) if not pd.isna(prev_v.iloc[i]) else None
                if pvol is not None and pvol >= 0:
                    if vol > pvol:
                        bucket["volume_up"] += 1
                    elif vol < pvol:
                        bucket["volume_down"] += 1
                    else:
                        bucket["volume_flat"] += 1

    series: list[dict[str, Any]] = []
    ad_line = 0
    vol_line = 0
    for key in sorted(buckets.keys()):
        b = buckets[key]
        net = b["advances"] - b["declines"]
        ad_line += net
        v_net = b["volume_up"] - b["volume_down"]
        vol_line += v_net
        total = b["advances"] + b["declines"] + b["unchanged"]
        series.append({
            "date": key,
            "label": key,
            "advances": b["advances"],
            "declines": b["declines"],
            "unchanged": b["unchanged"],
            "net": net,
            "total": total,
            "ad_ratio": _ad_ratio(b["advances"], b["declines"]),
            "ad_line": ad_line,
            "volume_up": b["volume_up"],
            "volume_down": b["volume_down"],
            "volume_flat": b["volume_flat"],
            "vol_net": v_net,
            "vol_ratio": _ad_ratio(b["volume_up"], b["volume_down"]),
            "vol_line": vol_line,
        })
    return _enrich_breadth_indicators(series, frames, mode="daily")


def _intraday_series(
    frames: dict[str, pd.DataFrame],
    session_date: datetime,
    *,
    as_of: time | None,
    asset_class: str = "india",
) -> list[dict[str, Any]]:
    day = session_date.date()
    # timestamp -> list of price signals (+1/-1/0) and volume signals
    by_ts_px: dict[str, list[int]] = {}
    by_ts_vol: dict[str, list[int]] = {}

    for _sym, df in frames.items():
        if "close" not in df.columns or len(df) < 2:
            continue
        day_df = df[df.index.normalize() == pd.Timestamp(day)]
        if day_df.empty:
            day_df = df[[pd.Timestamp(i).date() == day for i in df.index]]
        if len(day_df) < 1:
            continue

        prior = df[df.index < day_df.index[0]]
        prev_close = float(prior["close"].iloc[-1]) if len(prior) else None
        has_vol = "volume" in day_df.columns
        prev_vol = float(prior["volume"].iloc[-1]) if has_vol and len(prior) and "volume" in prior.columns else None

        closes = day_df["close"].astype(float)
        vols = day_df["volume"].astype(float) if has_vol else None
        for i, (ts, close) in enumerate(zip(closes.index, closes.values)):
            if not _in_session(ts, asset_class):
                continue
            t = pd.Timestamp(ts).to_pydatetime().time()
            if as_of is not None and t > as_of:
                break
            prev_in_session_i = None
            for j in range(i - 1, -1, -1):
                if _in_session(closes.index[j], asset_class):
                    prev_in_session_i = j
                    break
            if prev_in_session_i is not None:
                pclose = float(closes.iloc[prev_in_session_i])
                pvol = float(vols.iloc[prev_in_session_i]) if vols is not None else None
            else:
                pclose = prev_close if prev_close is not None else close
                pvol = prev_vol

            if close > pclose:
                psig = 1
            elif close < pclose:
                psig = -1
            else:
                psig = 0

            vsig = 0
            if vols is not None and pvol is not None:
                vol = float(vols.iloc[i])
                if vol > pvol:
                    vsig = 1
                elif vol < pvol:
                    vsig = -1

            key = pd.Timestamp(ts).strftime("%Y-%m-%d %H:%M")
            by_ts_px.setdefault(key, []).append(psig)
            by_ts_vol.setdefault(key, []).append(vsig)

    series: list[dict[str, Any]] = []
    ad_line = 0
    vol_line = 0
    for key in sorted(by_ts_px.keys()):
        psigs = by_ts_px[key]
        vsigs = by_ts_vol.get(key, [])
        adv = sum(1 for s in psigs if s > 0)
        dec = sum(1 for s in psigs if s < 0)
        unc = sum(1 for s in psigs if s == 0)
        v_up = sum(1 for s in vsigs if s > 0)
        v_dn = sum(1 for s in vsigs if s < 0)
        v_flat = sum(1 for s in vsigs if s == 0)
        net = adv - dec
        ad_line += net
        v_net = v_up - v_dn
        vol_line += v_net
        hhmm = key[11:] if len(key) >= 16 else key
        series.append({
            "date": key,
            "label": f"{hhmm} IST",
            "timestamp": key,
            "timestamp_ist": key,
            "timezone": "IST",
            "advances": adv,
            "declines": dec,
            "unchanged": unc,
            "net": net,
            "total": adv + dec + unc,
            "ad_ratio": _ad_ratio(adv, dec),
            "ad_line": ad_line,
            "volume_up": v_up,
            "volume_down": v_dn,
            "volume_flat": v_flat,
            "vol_net": v_net,
            "vol_ratio": _ad_ratio(v_up, v_dn),
            "vol_line": vol_line,
        })
    return _enrich_breadth_indicators(series, frames, mode="intraday")


def _prep_indicator_frames(frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Attach EMA21 + RSI14 to each constituent frame (for universe aggregates)."""
    from app.market_pulse.indicators import add_ema, add_rsi

    out: dict[str, pd.DataFrame] = {}
    for sym, df in frames.items():
        if df is None or df.empty or "close" not in df.columns or len(df) < 20:
            continue
        try:
            w = df.copy()
            w = add_ema(w, 9)
            w = add_ema(w, 21)
            w = add_rsi(w, 14)
            out[sym] = w
        except Exception:
            continue
    return out


def _rsi_series(values: pd.Series, period: int = 14) -> pd.Series:
    delta = values.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _enrich_breadth_indicators(
    series: list[dict[str, Any]],
    frames: dict[str, pd.DataFrame] | None = None,
    *,
    mode: str = "daily",
) -> list[dict[str, Any]]:
    """
    Add trend / strength / RSI onto each A/D point.

    • rsi — RSI(14) of the cumulative A/D line (breadth momentum)
    • trend — UPTREND / DOWNTREND / SIDEWAYS from A/D-line EMA9 vs EMA21
    • trend_score — −100..+100
    • strength — 0..100 conviction (how one-sided + how stretched breadth is)
    • avg_rsi / pct_uptrend — universe internals when constituent frames available
    """
    import numpy as np

    if not series:
        return series

    df = pd.DataFrame(series)
    ad = pd.to_numeric(df.get("ad_line"), errors="coerce").astype(float)
    net = pd.to_numeric(df.get("net"), errors="coerce").astype(float)
    total = pd.to_numeric(df.get("total"), errors="coerce").astype(float).replace(0, np.nan)
    ad_ratio = pd.to_numeric(df.get("ad_ratio"), errors="coerce").astype(float)

    # Prefer A/D line RSI; fall back to net if line is too short/flat early
    rsi = _rsi_series(ad, 14)
    if rsi.notna().sum() < 3:
        rsi = _rsi_series(net.fillna(0), 14)

    ema9 = ad.ewm(span=9, adjust=False).mean()
    ema21 = ad.ewm(span=21, adjust=False).mean()
    # Short-window slope of A/D line (% over last ~5 bars)
    slope = ad.diff(min(5, max(1, len(ad) // 4)))

    # Universe internals
    uni_avg_rsi: list[float | None] = [None] * len(df)
    uni_pct_up: list[float | None] = [None] * len(df)
    uni_pct_strong: list[float | None] = [None] * len(df)

    if frames:
        ind_frames = _prep_indicator_frames(frames)
        for pos, (_, row) in enumerate(df.iterrows()):
            key = str(row.get("date") or row.get("timestamp") or "")
            rsis: list[float] = []
            ups = 0
            strong = 0
            n = 0
            for _sym, w in ind_frames.items():
                try:
                    if mode == "daily":
                        day = key[:10]
                        mask = w.index.normalize() == pd.Timestamp(day)
                        if not mask.any():
                            mask = pd.Series([pd.Timestamp(ix).date().isoformat() == day for ix in w.index], index=w.index)
                        if not mask.any():
                            continue
                        bar = w.loc[mask].iloc[-1]
                    else:
                        ts = pd.Timestamp(key)
                        # nearest bar at or before timestamp
                        prior = w[w.index <= ts]
                        if prior.empty:
                            continue
                        bar = prior.iloc[-1]
                    n += 1
                    close = float(bar["close"])
                    e21 = float(bar["ema_21"]) if "ema_21" in bar.index and pd.notna(bar["ema_21"]) else None
                    e9 = float(bar["ema_9"]) if "ema_9" in bar.index and pd.notna(bar["ema_9"]) else None
                    rv = float(bar["rsi_14"]) if "rsi_14" in bar.index and pd.notna(bar["rsi_14"]) else None
                    if rv is not None:
                        rsis.append(rv)
                        if rv >= 60 or rv <= 40:
                            strong += 1
                    trend_ref = e21 if e21 is not None else e9
                    if trend_ref is not None and close > trend_ref:
                        ups += 1
                except Exception:
                    continue
            if n > 0:
                uni_avg_rsi[pos] = round(float(np.mean(rsis)), 2) if rsis else None
                uni_pct_up[pos] = round(100.0 * ups / n, 1)
                uni_pct_strong[pos] = round(100.0 * strong / n, 1)

    enriched: list[dict[str, Any]] = []
    for i, row in enumerate(series):
        r = dict(row)
        rsi_v = float(rsi.iloc[i]) if i < len(rsi) and pd.notna(rsi.iloc[i]) else None
        e9v = float(ema9.iloc[i]) if i < len(ema9) and pd.notna(ema9.iloc[i]) else None
        e21v = float(ema21.iloc[i]) if i < len(ema21) and pd.notna(ema21.iloc[i]) else None
        sl = float(slope.iloc[i]) if i < len(slope) and pd.notna(slope.iloc[i]) else 0.0

        # Trend from EMA stack + slope
        trend = "SIDEWAYS"
        trend_score = 0.0
        if e9v is not None and e21v is not None:
            if e9v > e21v and sl >= 0:
                trend = "UPTREND"
                trend_score = 55 + min(40, abs(sl) * 0.5)
            elif e9v < e21v and sl <= 0:
                trend = "DOWNTREND"
                trend_score = -(55 + min(40, abs(sl) * 0.5))
            elif e9v > e21v:
                trend = "UPTREND"
                trend_score = 35
            elif e9v < e21v:
                trend = "DOWNTREND"
                trend_score = -35
            else:
                trend_score = max(-20, min(20, sl))
        elif sl > 0:
            trend = "UPTREND"
            trend_score = 25
        elif sl < 0:
            trend = "DOWNTREND"
            trend_score = -25

        # Strength 0-100: how decisive breadth is
        ar = float(ad_ratio.iloc[i]) if i < len(ad_ratio) and pd.notna(ad_ratio.iloc[i]) else 1.0
        net_share = abs(float(net.iloc[i]) / float(total.iloc[i])) * 100 if i < len(net) and pd.notna(total.iloc[i]) else 0.0
        ratio_stretch = min(50.0, abs(ar - 1.0) * 25.0)  # |ratio-1|=2 → 50
        rsi_stretch = abs((rsi_v if rsi_v is not None else 50) - 50) * 0.8  # 0..40
        uni_strong = float(uni_pct_strong[i] or 0) * 0.25
        strength = round(min(100.0, max(0.0, net_share * 0.45 + ratio_stretch + rsi_stretch * 0.4 + uni_strong)), 1)

        # Prefer universe avg RSI when available; else A/D-line RSI
        display_rsi = uni_avg_rsi[i] if uni_avg_rsi[i] is not None else (round(rsi_v, 2) if rsi_v is not None else None)

        r.update({
            "rsi": display_rsi,
            "breadth_rsi": round(rsi_v, 2) if rsi_v is not None else None,
            "avg_rsi": uni_avg_rsi[i],
            "trend": trend,
            "trend_score": round(float(max(-100, min(100, trend_score))), 1),
            "strength": strength,
            "pct_uptrend": uni_pct_up[i],
            "pct_strong": uni_pct_strong[i],
            "ad_ema9": round(e9v, 2) if e9v is not None else None,
            "ad_ema21": round(e21v, 2) if e21v is not None else None,
        })
        enriched.append(r)
    return enriched


def _parse_as_of(as_of_time: str | None) -> time | None:
    """Parse HH:MM as IST wall-clock (NSE session time)."""
    if not as_of_time or not str(as_of_time).strip():
        return None
    raw = str(as_of_time).strip().replace(" IST", "").replace("ist", "").strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).time()
        except ValueError:
            continue
    return None


def _volume_mood(volume_up: int, volume_down: int, volume_flat: int = 0) -> tuple[str, str]:
    """Return (mood_label, one_line) for volume-breadth layman copy."""
    total = volume_up + volume_down + volume_flat
    if total <= 0:
        return "NO VOLUME DATA", "Volume comparison was not available for enough stocks."
    if volume_down == 0 and volume_up > 0:
        return "VOLUME EXPANDING", "Almost every stock traded more than the prior period — activity is heating up."
    if volume_up == 0 and volume_down > 0:
        return "VOLUME DRYING UP", "Almost every stock traded less than the prior period — activity is fading."
    ratio = volume_up / max(volume_down, 1)
    net = volume_up - volume_down
    share_up = volume_up / total
    if share_up >= 0.65 or ratio >= 2.0:
        return "VOLUME EXPANDING", "More stocks saw higher volume than lower — participation/interest is rising."
    if share_up <= 0.35 or ratio <= 0.5:
        return "VOLUME DRYING UP", "More stocks saw lower volume — the move may lack fuel."
    if abs(net) <= max(2, int(total * 0.05)):
        return "VOLUME MIXED", "Volume up and volume down are nearly tied — no clear activity skew."
    if net > 0:
        return "VOLUME SLIGHTLY UP", "Slightly more stocks traded heavier than lighter."
    return "VOLUME SLIGHTLY DOWN", "Slightly more stocks traded lighter than heavier."


def _combine_price_volume(ad_mood: str, vol_mood: str) -> str:
    """Plain-English combo of price breadth + volume breadth."""
    bullish_px = "BULLISH" in ad_mood or ad_mood.startswith("MILDLY BULLISH")
    bearish_px = "BEARISH" in ad_mood or ad_mood.startswith("MILDLY BEARISH")
    vol_up = "EXPANDING" in vol_mood or "SLIGHTLY UP" in vol_mood
    vol_dn = "DRYING" in vol_mood or "SLIGHTLY DOWN" in vol_mood
    if bullish_px and vol_up:
        return (
            "Price breadth and volume are both expanding — a healthier, better-confirmed advance "
            "(more stocks rising on rising activity)."
        )
    if bullish_px and vol_dn:
        return (
            "Prices are advancing but volume is drying up — a softer / hollow rally that can fade "
            "(ups without growing interest)."
        )
    if bearish_px and vol_up:
        return (
            "Prices are falling with expanding volume — more aggressive selling "
            "(downs on rising activity)."
        )
    if bearish_px and vol_dn:
        return (
            "Prices are soft but volume is quiet — a drift lower rather than a panic "
            "(selling without a surge in activity)."
        )
    return (
        "Price breadth and volume breadth are mixed — wait for them to line up before trusting the move."
    )


def _breadth_mood(advances: int, declines: int, unchanged: int = 0) -> tuple[str, str]:
    """Return (mood_label, one_line) for layman copy."""
    total = advances + declines + unchanged
    if total <= 0:
        return "NO DATA", "Not enough stock closes to read breadth yet."
    if declines == 0 and advances > 0:
        return "VERY BULLISH BREADTH", "Almost everything in the basket finished higher — broad participation."
    if advances == 0 and declines > 0:
        return "VERY BEARISH BREADTH", "Almost everything finished lower — selling is widespread."
    ratio = advances / max(declines, 1)
    net = advances - declines
    share_up = advances / total
    if share_up >= 0.65 or ratio >= 2.0:
        return "BULLISH BREADTH", "More stocks rose than fell by a clear margin — buyers had the upper hand."
    if share_up <= 0.35 or ratio <= 0.5:
        return "BEARISH BREADTH", "More stocks fell than rose — selling pressure was broader than buying."
    if abs(net) <= max(2, int(total * 0.05)):
        return "MIXED / CHOPPY", "Advances and declines are nearly tied — the index move may be led by a few heavyweights."
    if net > 0:
        return "MILDLY BULLISH", "Slightly more stocks rose than fell — positive but not a stampede."
    return "MILDLY BEARISH", "Slightly more stocks fell than rose — soft under the surface."


def _build_outcome_layman(
    *,
    index_name: str,
    from_date: str,
    to_date: str,
    daily: list[dict[str, Any]],
    intraday: list[dict[str, Any]],
    is_intraday: bool,
    timeframe: str,
    session_date: str | None,
    as_of: time | None,
    universe_size: int,
) -> dict[str, Any]:
    last = daily[-1] if daily else None
    mood, mood_line = ("NO DATA", "No daily points yet.")
    vol_mood, vol_line = ("NO VOLUME DATA", "No volume points yet.")
    if last:
        mood, mood_line = _breadth_mood(
            int(last.get("advances") or 0),
            int(last.get("declines") or 0),
            int(last.get("unchanged") or 0),
        )
        vol_mood, vol_line = _volume_mood(
            int(last.get("volume_up") or 0),
            int(last.get("volume_down") or 0),
            int(last.get("volume_flat") or 0),
        )

    combo = _combine_price_volume(mood, vol_mood)

    # Trend of A/D line over the window
    ad_trend = "flat"
    ad_note = "The running A/D line did not move much across the period."
    if len(daily) >= 2:
        start_line = float(daily[0].get("ad_line") or 0)
        end_line = float(daily[-1].get("ad_line") or 0)
        delta = end_line - start_line
        if delta > 5:
            ad_trend = "rising"
            ad_note = (
                f"Over {from_date} → {to_date}, the cumulative A/D line rose "
                f"(net +{int(delta)}). Breadth improved — more days of winners than losers stacked up."
            )
        elif delta < -5:
            ad_trend = "falling"
            ad_note = (
                f"Over {from_date} → {to_date}, the cumulative A/D line fell "
                f"(net {int(delta)}). Breadth weakened — losers piled up more than winners."
            )
        else:
            ad_note = (
                f"Over {from_date} → {to_date}, the cumulative A/D line stayed roughly flat "
                f"(net {int(delta):+d}). Breadth did not clearly improve or deteriorate."
            )

    vol_trend_note = ""
    if len(daily) >= 2 and daily[-1].get("vol_line") is not None:
        v0 = float(daily[0].get("vol_line") or 0)
        v1 = float(daily[-1].get("vol_line") or 0)
        vd = v1 - v0
        if vd > 5:
            vol_trend_note = (
                f"Cumulative volume-breadth also rose (net +{int(vd)}) — activity expanded across the window."
            )
        elif vd < -5:
            vol_trend_note = (
                f"Cumulative volume-breadth fell (net {int(vd)}) — activity faded across the window."
            )
        else:
            vol_trend_note = "Cumulative volume-breadth stayed roughly flat across the window."

    intra_mood = None
    intra_line = None
    intra_vol_line = None
    if is_intraday and intraday:
        last_i = intraday[-1]
        intra_mood, intra_line = _breadth_mood(
            int(last_i.get("advances") or 0),
            int(last_i.get("declines") or 0),
            int(last_i.get("unchanged") or 0),
        )
        _vm, vline = _volume_mood(
            int(last_i.get("volume_up") or 0),
            int(last_i.get("volume_down") or 0),
            int(last_i.get("volume_flat") or 0),
        )
        until = f" until {as_of.strftime('%H:%M')} IST" if as_of else ""
        intra_line = (
            f"On {session_date} ({timeframe} bars{until}): {intra_line} "
            f"Last bar — {last_i.get('advances')} up / {last_i.get('declines')} down / "
            f"{last_i.get('unchanged')} flat (A/D ratio {last_i.get('ad_ratio', '—')})."
        )
        intra_vol_line = (
            f"Same session volume: {vline} "
            f"Last bar — {last_i.get('volume_up')} volume-up / {last_i.get('volume_down')} volume-down "
            f"(vol ratio {last_i.get('vol_ratio', '—')})."
        )

    headline = f"{index_name}: {mood} · {vol_mood}"
    summary_parts = [
        f"We checked about {universe_size} stocks that make up {index_name}.",
        "Top chart: Advance/Decline ratio (stocks up ÷ stocks down). Above 1 = more winners.",
        "Same chart also shows Volume ratio (stocks with higher volume ÷ stocks with lower volume). Above 1 = activity expanding.",
    ]
    if last:
        summary_parts.append(
            f"Latest day ({last.get('date')}): "
            f"A/D {last.get('advances')}/{last.get('declines')} (ratio {last.get('ad_ratio', '—')}) — {mood_line} "
            f"Volume-up {last.get('volume_up')}/{last.get('volume_down')} (ratio {last.get('vol_ratio', '—')}) — {vol_line}"
        )
        if last.get("trend") or last.get("rsi") is not None or last.get("strength") is not None:
            summary_parts.append(
                f"Breadth internals — trend {last.get('trend', '—')} "
                f"(score {last.get('trend_score', '—')}), "
                f"strength {last.get('strength', '—')}/100, "
                f"RSI {last.get('rsi', '—')}"
                + (f", % stocks above EMA {last.get('pct_uptrend')}%" if last.get("pct_uptrend") is not None else "")
                + "."
            )
    summary_parts.append(combo)
    summary_parts.append(ad_note)
    if vol_trend_note:
        summary_parts.append(vol_trend_note)
    if intra_line:
        summary_parts.append(intra_line)
    if intra_vol_line:
        summary_parts.append(intra_vol_line)

    what_it_means = (
        "Price breadth answers “how many stocks moved which way?” "
        "Volume breadth answers “are more stocks getting busier or quieter?” "
        "Trend is the A/D-line EMA stack (up = improving breadth). "
        "Strength (0–100) shows how one-sided / decisive that breadth is. "
        "RSI is average constituent RSI (fallback: RSI of the A/D line) — "
        "above 60 = hot internals, below 40 = washed out. "
        "Best bullish confirmation: A/D ratio > 1, volume ratio > 1, uptrend, rising strength, RSI recovering from oversold. "
        "Best bearish confirmation: A/D ratio < 1 with volume expanding and downtrend. "
        "Use with price, not instead of it."
    )

    return {
        "headline": headline,
        "mood": mood,
        "mood_line": mood_line,
        "volume_mood": vol_mood,
        "volume_mood_line": vol_line,
        "combo_line": combo,
        "ad_trend": ad_trend,
        "ad_trend_line": ad_note,
        "breadth_trend": (last or {}).get("trend"),
        "breadth_trend_score": (last or {}).get("trend_score"),
        "breadth_strength": (last or {}).get("strength"),
        "breadth_rsi": (last or {}).get("rsi"),
        "intraday_mood": intra_mood,
        "intraday_line": intra_line,
        "intraday_volume_line": intra_vol_line,
        "summary": " ".join(summary_parts),
        "what_it_means": what_it_means,
        "how_to_read": [
            "A/D ratio (green/red bars + violet line) = Advances ÷ Declines. Above 1 = more stocks rose.",
            "Volume ratio (amber line) = Volume-up ÷ Volume-down. Above 1 = more stocks got busier.",
            "Trend (sky line score) = A/D-line EMA9 vs EMA21 — UPTREND means breadth improving.",
            "Strength (orange, 0–100) = how decisive / one-sided the breadth move is.",
            "RSI (cyan, 0–100) = average stock RSI (or A/D-line RSI) — >70 hot, <30 washed out.",
            "Dashed line at 1.0 = even for A/D and volume ratios; RSI mid = 50.",
            "A/D > 1 + Vol > 1 + UPTREND → healthier advance. A/D > 1 + Vol < 1 → hollow rally.",
            "Daily chart = one reading per session. Intraday = each bar in local market session hours.",
        ],
    }


def compute_advance_decline_graph(
    index_name: str,
    *,
    asset_class: str = "india",
    from_date: str,
    to_date: str,
    timeframe: str = "1d",
    session_date: str | None = None,
    as_of_time: str | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    """Build daily and/or intraday advance–decline series for an index universe."""
    ac = (asset_class or "india").strip().lower()
    if ac not in ("india", "us", "crypto"):
        ac = "india"
    market = _market_for(ac)
    _open_t, _close_t, _tz_name, tz_label = _session_meta(ac)

    symbols = resolve_universe_symbols(ac, index_name)
    if not symbols:
        return {
            "error": f"No constituents found for '{index_name}' ({ac}).",
            "index_name": index_name,
            "asset_class": ac,
        }

    try:
        from_dt = _parse_date(from_date)
        to_dt = _parse_date(to_date)
    except ValueError:
        return {"error": "Invalid from_date / to_date — use YYYY-MM-DD.", "index_name": index_name}

    if to_dt < from_dt:
        return {"error": "to_date must be on or after from_date.", "index_name": index_name}

    tf = (timeframe or "1d").strip().lower()
    if tf in ("", "daily", "day"):
        tf = "1d"

    is_intraday = tf in INTRADAY_TIMEFRAMES
    sess = session_date or to_date
    try:
        sess_dt = _parse_date(sess)
    except ValueError:
        return {"error": "Invalid session_date — use YYYY-MM-DD.", "index_name": index_name}

    as_of = _parse_as_of(as_of_time)

    # --- Daily series (always, for the chosen range) ---
    day_span = (to_dt - from_dt).days + 8  # buffer for prior close
    daily_limit = max(min(day_span + 15, 400), 40)
    daily_frames = _fetch_many(
        symbols, "1d",
        market=market, groww_token=groww_token, exchange=exchange, limit=daily_limit,
        asset_class=ac,
    )
    daily = _daily_series(daily_frames, from_dt, to_dt)

    intraday: list[dict[str, Any]] = []
    if is_intraday:
        # Enough bars to cover one session with prior bar context
        if tf == "5m":
            limit = 120
        elif tf in ("10m", "15m"):
            limit = 80
        elif tf == "30m":
            limit = 50
        else:
            limit = 40
        # Widen fetch window: need prior day for first-bar comparison
        intra_frames = _fetch_many(
            symbols, tf,
            market=market, groww_token=groww_token, exchange=exchange, limit=limit,
            asset_class=ac,
        )
        intraday = _intraday_series(intra_frames, sess_dt, as_of=as_of, asset_class=ac)

    last_daily = daily[-1] if daily else None
    options = _options_snapshot(ac, index_name, groww_token=groww_token)
    outcome = _build_outcome_layman(
        index_name=index_name,
        from_date=from_date,
        to_date=to_date,
        daily=daily,
        intraday=intraday,
        is_intraday=is_intraday,
        timeframe=tf,
        session_date=sess_dt.date().isoformat() if is_intraday else None,
        as_of=as_of,
        universe_size=len(symbols),
    )
    # Fold a one-liner options read into the layman outcome when available
    if options.get("available"):
        opt_line = (
            f"Options ({options.get('oc_symbol')}): PCR(OI) {options.get('pcr_oi')} · "
            f"bias {options.get('bias') or '—'} · max pain {options.get('max_pain')} · "
            f"S {options.get('support')} / R {options.get('resistance')}."
        )
        outcome["options_line"] = opt_line
        how = list(outcome.get("how_to_read") or [])
        how.append(
            "Options PCR > 1 with A/D > 1 often confirms a healthier advance; "
            "PCR < 0.8 with rising A/D can mean a hollow / short-covering rally."
        )
        outcome["how_to_read"] = how
        summary = str(outcome.get("summary") or "")
        if summary and opt_line not in summary:
            outcome["summary"] = f"{summary} {opt_line}"
    plain = outcome["summary"]

    return {
        "index_name": index_name,
        "asset_class": ac,
        "from_date": from_date,
        "to_date": to_date,
        "timeframe": tf,
        "session_date": sess_dt.date().isoformat() if is_intraday else None,
        "as_of_time": as_of.strftime("%H:%M") if as_of else None,
        "timezone": tz_label,
        "mode": "intraday" if is_intraday else "daily",
        "universe_size": len(symbols),
        "scanned_daily": len(daily_frames),
        "warning": (
            f"Universe capped at {len(symbols)} names for speed."
            if len(symbols) >= _HARD_CAP else (
                f"Large universe ({len(symbols)} names) — fetch may be slow."
                if len(symbols) > _WARN_UNIVERSE else None
            )
        ),
        "daily": daily,
        "intraday": intraday,
        "latest": last_daily,
        "options": options,
        "outcome_layman": outcome,
        "plain_english": plain,
        "currency": _currency_for(ac),
        "market": market,
    }
