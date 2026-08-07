"""
comparative_strength_engine.py
------------------------------
Compare one base index/stock against one or more peers across an asset class.

For each peer vs base over a shared lookback window:
  • Absolute return % (base and peer)
  • Relative strength spread % = peer_return − base_return
      (+ve → peer stronger than base, −ve → peer weaker)
  • Multi-horizon consistency (5 / 10 / 20 / 60 bars when available)
  • CRS slope (peer÷base ratio trend)
  • Absolute trend stack (EMA9 / EMA21 / EMA50)
  • Expert-style LONG / SHORT / WAIT with confidence %

Research / education only — not financial advice.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Literal

import numpy as np
import pandas as pd

from app.market_pulse.asset_class_config import ALL_DURATIONS
from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.ticker_utils import is_crypto_market, is_us_market

logger = logging.getLogger(__name__)

AssetClass = Literal["india", "us", "crypto", "commodity"]

TIMEFRAME_OPTIONS = list(ALL_DURATIONS)  # 1m, 5m, 15m, 30m, 1h, 4h, 1d, 1w
LOOKBACK_OPTIONS = [5, 10, 20, 40, 60]

_MIN_BARS = 20
_HORIZONS = (5, 10, 20, 60)

# Sensible quick-pick bases per asset class (label → symbol for fetch)
BASE_PRESETS: dict[str, list[dict[str, str]]] = {
    "india": [
        {"label": "Nifty 50", "symbol": "NIFTY 50"},
        {"label": "Bank Nifty", "symbol": "NIFTY BANK"},
        {"label": "Nifty IT", "symbol": "NIFTY IT"},
        {"label": "Nifty Midcap 150", "symbol": "NIFTY MIDCAP 150"},
        {"label": "Sensex", "symbol": "SENSEX"},
        {"label": "Reliance", "symbol": "RELIANCE"},
        {"label": "HDFC Bank", "symbol": "HDFCBANK"},
        {"label": "TCS", "symbol": "TCS"},
    ],
    "us": [
        {"label": "S&P 500 (SPY)", "symbol": "SPY"},
        {"label": "Nasdaq (QQQ)", "symbol": "QQQ"},
        {"label": "Dow (DIA)", "symbol": "DIA"},
        {"label": "Russell 2000 (IWM)", "symbol": "IWM"},
        {"label": "Apple", "symbol": "AAPL"},
        {"label": "Microsoft", "symbol": "MSFT"},
        {"label": "NVIDIA", "symbol": "NVDA"},
    ],
    "crypto": [
        {"label": "Bitcoin", "symbol": "BTC"},
        {"label": "Ethereum", "symbol": "ETH"},
        {"label": "Solana", "symbol": "SOL"},
        {"label": "XRP", "symbol": "XRP"},
    ],
    "commodity": [
        {"label": "Gold", "symbol": "GC=F"},
        {"label": "Silver", "symbol": "SI=F"},
        {"label": "Crude Oil", "symbol": "CL=F"},
        {"label": "Copper", "symbol": "HG=F"},
    ],
}


def list_base_presets(asset_class: str) -> list[dict[str, str]]:
    return list(BASE_PRESETS.get(asset_class, BASE_PRESETS["india"]))


def _market_for(asset_class: str) -> str:
    from app.market_pulse.asset_class_config import ASSET_CLASS_CONFIG

    cfg = ASSET_CLASS_CONFIG.get(asset_class) or ASSET_CLASS_CONFIG["india"]
    return str(cfg["market"])


def _looks_like_index(symbol: str, asset_class: str) -> bool:
    s = (symbol or "").strip().upper()
    if not s:
        return False
    if asset_class == "india":
        try:
            from app.market_pulse.nse_index_yfinance import is_nse_index_symbol

            return is_nse_index_symbol(s)
        except Exception:
            return s.startswith("NIFTY") or s in {"SENSEX", "BANKNIFTY", "FINNIFTY"}
    if asset_class == "us":
        return s in {"SPY", "QQQ", "DIA", "IWM", "^GSPC", "^IXIC", "^DJI"}
    return False


def _normalize_index(idx: pd.DatetimeIndex, timeframe: str) -> pd.DatetimeIndex:
    out = pd.to_datetime(idx)
    if getattr(out, "tz", None) is not None:
        out = out.tz_convert(None)
    if timeframe in ("1d", "1w", "1M"):
        out = out.normalize()
    return out


def _fetch_ohlcv(
    symbol: str,
    market: str,
    timeframe: str,
    *,
    asset_class: str = "india",
    groww_token: str = "",
    exchange: str = "NSE",
    limit: int = 320,
) -> pd.DataFrame:
    """Fetch OHLC for stock or index. Indices use dedicated index OHLCV path."""
    sym = (symbol or "").strip()
    df = pd.DataFrame()

    # NSE / broad indices (NIFTY 50, BANKNIFTY, …) — do not send raw name to Groww equity API
    if asset_class in ("india",) and _looks_like_index(sym, asset_class):
        try:
            from app.market_pulse.index_ohlcv import fetch_index_ohlcv_for_interval

            raw = fetch_index_ohlcv_for_interval(
                sym, timeframe, limit=limit, groww_token=groww_token, exchange=exchange,
            )
            if raw is not None and not raw.empty:
                df = normalize_ohlcv(raw)
        except Exception as exc:
            logger.debug("Index OHLCV failed for %s: %s", sym, exc)

    if df.empty:
        try:
            df = normalize_ohlcv(
                fetch_data_for_gap_scan(sym, timeframe, market, groww_token, exchange, limit=limit)
            )
        except Exception as exc:
            logger.debug("Gap-scan OHLCV failed for %s: %s", sym, exc)
            df = pd.DataFrame()

    if df.empty or len(df) < _MIN_BARS:
        is_crypto = is_crypto_market(market)
        # Map common India index names to Yahoo for fallback
        yf_sym = sym
        if asset_class == "india" and _looks_like_index(sym, asset_class):
            try:
                from app.market_pulse.nse_index_yfinance import index_yf_candidates

                cands = index_yf_candidates(sym)
                if cands:
                    yf_sym = cands[0]
            except Exception:
                yf_sym = "^NSEI" if "50" in sym.upper() else sym
        df = normalize_ohlcv(
            fetch_ohlcv_yfinance(yf_sym, timeframe, is_crypto=is_crypto, limit=limit, market=market)
        )

    if not df.empty and "close" in df.columns:
        df = df.copy()
        df.index = _normalize_index(pd.DatetimeIndex(df.index), timeframe)
        df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


def _pct_change(close: pd.Series, bars: int) -> float | None:
    if close is None or len(close) <= bars:
        return None
    a = float(close.iloc[-(bars + 1)])
    b = float(close.iloc[-1])
    if a == 0 or not np.isfinite(a) or not np.isfinite(b):
        return None
    return round((b / a - 1.0) * 100.0, 3)


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.astype(float).ewm(span=span, adjust=False).mean()


def _trend_stack(close: pd.Series) -> dict[str, Any]:
    n = len(close)
    if n < 25:
        return {"bias": "INSUFFICIENT", "ema9": None, "ema21": None, "ema50": None}
    e9 = float(_ema(close, 9).iloc[-1])
    e21 = float(_ema(close, min(21, max(5, n // 3))).iloc[-1])
    e50 = float(_ema(close, min(50, max(10, n // 2))).iloc[-1]) if n >= 40 else None
    last = float(close.iloc[-1])
    if e50 is not None and last >= e9 >= e21 >= e50:
        bias = "BULLISH"
    elif e50 is not None and last <= e9 <= e21 <= e50:
        bias = "BEARISH"
    elif last > e21:
        bias = "MILDLY_BULLISH"
    elif last < e21:
        bias = "MILDLY_BEARISH"
    else:
        bias = "MIXED"
    return {
        "bias": bias,
        "ema9": round(e9, 4),
        "ema21": round(e21, 4),
        "ema50": round(e50, 4) if e50 is not None else None,
        "last": round(last, 4),
    }


def _crs_slope_pct(peer: pd.Series, base: pd.Series, bars: int = 10) -> float | None:
    """% change of peer/base ratio over recent bars — rising CRS = peer strengthening."""
    aligned = pd.concat([peer.rename("p"), base.rename("b")], axis=1).dropna()
    if len(aligned) <= bars:
        return None
    ratio = aligned["p"] / aligned["b"].replace(0, np.nan)
    ratio = ratio.dropna()
    if len(ratio) <= bars:
        return None
    a = float(ratio.iloc[-(bars + 1)])
    b = float(ratio.iloc[-1])
    if a == 0 or not np.isfinite(a) or not np.isfinite(b):
        return None
    return round((b / a - 1.0) * 100.0, 3)


def _vol_confirm(df: pd.DataFrame) -> str:
    if df is None or df.empty or "volume" not in df.columns:
        return "UNKNOWN"
    vol = pd.to_numeric(df["volume"], errors="coerce")
    if vol.dropna().empty or len(vol) < 25:
        return "UNKNOWN"
    sma = vol.rolling(20).mean()
    last = float(vol.iloc[-1])
    avg = float(sma.iloc[-1]) if np.isfinite(sma.iloc[-1]) else 0.0
    if avg <= 0:
        return "UNKNOWN"
    ratio = last / avg
    if ratio >= 1.3:
        return "EXPANDING"
    if ratio <= 0.7:
        return "DRYING"
    return "NORMAL"


def _trade_suggestion(
    *,
    symbol: str,
    base_symbol: str,
    rs_pct: float,
    horizons: dict[str, float | None],
    peer_trend: dict[str, Any],
    base_trend: dict[str, Any],
    crs_slope: float | None,
    volume: str,
) -> dict[str, Any]:
    """Expert relative-strength trade framing with confidence."""
    score = 0.0
    reasons: list[str] = []

    if rs_pct >= 8:
        score += 28
        reasons.append(f"Strong outperformance vs {base_symbol} (+{rs_pct:.1f}%).")
    elif rs_pct >= 3:
        score += 16
        reasons.append(f"Moderate outperformance vs {base_symbol} (+{rs_pct:.1f}%).")
    elif rs_pct <= -8:
        score -= 28
        reasons.append(f"Strong underperformance vs {base_symbol} ({rs_pct:.1f}%).")
    elif rs_pct <= -3:
        score -= 16
        reasons.append(f"Moderate underperformance vs {base_symbol} ({rs_pct:.1f}%).")
    else:
        reasons.append(f"RS near flat vs {base_symbol} ({rs_pct:+.1f}%) — no clear edge yet.")

    vals = [v for v in horizons.values() if v is not None]
    if len(vals) >= 2:
        pos = sum(1 for v in vals if v > 0.5)
        neg = sum(1 for v in vals if v < -0.5)
        if pos >= max(2, len(vals) - 1):
            score += 14
            reasons.append("Multi-horizon RS consistently positive.")
        elif neg >= max(2, len(vals) - 1):
            score -= 14
            reasons.append("Multi-horizon RS consistently negative.")
        else:
            reasons.append("Horizons disagree — treat as tactical only.")

    if crs_slope is not None:
        if crs_slope >= 1.5:
            score += 12
            reasons.append(f"CRS rising ({crs_slope:+.1f}%) — peer strengthening vs base.")
        elif crs_slope <= -1.5:
            score -= 12
            reasons.append(f"CRS falling ({crs_slope:+.1f}%) — peer weakening vs base.")

    pb = str(peer_trend.get("bias") or "")
    bb = str(base_trend.get("bias") or "")
    if "BULLISH" in pb:
        score += 10
        reasons.append(f"Peer EMA stack {pb.replace('_', ' ').lower()}.")
    elif "BEARISH" in pb:
        score -= 10
        reasons.append(f"Peer EMA stack {pb.replace('_', ' ').lower()}.")
    if "BULLISH" in bb and score < 0:
        score -= 4
        reasons.append("Base still constructive — prefer short peer / rotate into base.")
    if "BEARISH" in bb and score > 0:
        score += 4
        reasons.append("Base soft — long peer is a relative long, not a broad-market long.")

    if volume == "EXPANDING":
        score += 6 if score >= 0 else -6
        reasons.append("Volume expanding — move has participation.")
    elif volume == "DRYING":
        score *= 0.85
        reasons.append("Volume drying — treat RS move with caution.")

    score = float(max(-100.0, min(100.0, score)))
    conf = int(round(min(95, max(35, abs(score) * 0.9 + 20))))

    if score >= 35:
        action = "LONG"
        thesis = (
            f"LONG {symbol} vs {base_symbol}: peer is relatively stronger. "
            "Prefer pullbacks in the peer; use base weakness or peer EMA as timing."
        )
    elif score <= -35:
        action = "SHORT"
        thesis = (
            f"SHORT {symbol} / rotate toward {base_symbol}: peer is relatively weaker. "
            "Prefer bounces to short peer, or reduce peer and overweight base."
        )
    elif score >= 15:
        action = "LONG_WATCH"
        thesis = f"Lean LONG {symbol} on dips — RS edge exists but conviction is only moderate."
        conf = min(conf, 58)
    elif score <= -15:
        action = "SHORT_WATCH"
        thesis = f"Lean SHORT {symbol} / favor {base_symbol} — weakness present but not decisive."
        conf = min(conf, 58)
    else:
        action = "WAIT"
        thesis = f"No high-conviction relative trade vs {base_symbol} right now — wait for RS to stretch."
        conf = min(conf, 45)

    return {
        "action": action,
        "side": "LONG" if "LONG" in action else ("SHORT" if "SHORT" in action else "WAIT"),
        "confidence_pct": conf,
        "score": round(score, 1),
        "thesis": thesis,
        "reasons": reasons[:6],
    }


def _analyze_peer(
    *,
    symbol: str,
    peer_df: pd.DataFrame,
    base_df: pd.DataFrame,
    base_symbol: str,
    lookback: int,
) -> dict[str, Any]:
    peer_close = peer_df["close"].astype(float)
    base_close = base_df["close"].astype(float)
    aligned = pd.concat(
        [peer_close.rename("peer"), base_close.rename("base")],
        axis=1,
    ).dropna()
    if len(aligned) < max(8, min(_MIN_BARS, lookback + 2)):
        return {
            "symbol": symbol,
            "error": f"Insufficient overlapping bars ({len(aligned)}).",
            "status": "ERROR",
        }

    peer_s = aligned["peer"]
    base_s = aligned["base"]
    lb = min(lookback, len(aligned) - 2)

    peer_ret = _pct_change(peer_s, lb)
    base_ret = _pct_change(base_s, lb)
    if peer_ret is None or base_ret is None:
        return {"symbol": symbol, "error": "Could not compute returns.", "status": "ERROR"}

    rs_pct = round(peer_ret - base_ret, 3)
    horizons: dict[str, float | None] = {}
    for h in _HORIZONS:
        if len(aligned) > h + 1:
            pr = _pct_change(peer_s, h)
            br = _pct_change(base_s, h)
            horizons[f"rs_{h}b"] = round(pr - br, 3) if pr is not None and br is not None else None
        else:
            horizons[f"rs_{h}b"] = None

    peer_trend = _trend_stack(peer_s)
    base_trend = _trend_stack(base_s)
    crs_slope = _crs_slope_pct(peer_s, base_s, bars=min(10, max(3, lb // 2)))
    volume = _vol_confirm(peer_df)

    if rs_pct >= 1.0:
        status = "STRONGER"
    elif rs_pct <= -1.0:
        status = "WEAKER"
    else:
        status = "INLINE"

    trade = _trade_suggestion(
        symbol=symbol,
        base_symbol=base_symbol,
        rs_pct=rs_pct,
        horizons=horizons,
        peer_trend=peer_trend,
        base_trend=base_trend,
        crs_slope=crs_slope,
        volume=volume,
    )

    window = aligned.tail(lb + 1).copy()
    peer_norm = (window["peer"] / float(window["peer"].iloc[0]) - 1.0) * 100.0
    base_norm = (window["base"] / float(window["base"].iloc[0]) - 1.0) * 100.0
    series = [
        {
            "i": i,
            "label": str(idx.date()) if hasattr(idx, "date") else str(idx),
            "peer_cum_pct": round(float(peer_norm.iloc[i]), 3),
            "base_cum_pct": round(float(base_norm.iloc[i]), 3),
            "spread_pct": round(float(peer_norm.iloc[i] - base_norm.iloc[i]), 3),
        }
        for i, idx in enumerate(window.index)
    ]

    return {
        "symbol": symbol,
        "status": status,
        "peer_return_pct": peer_ret,
        "base_return_pct": base_ret,
        "relative_strength_pct": rs_pct,
        "lookback_bars": lb,
        "horizons": horizons,
        "crs_slope_pct": crs_slope,
        "peer_trend": peer_trend,
        "base_trend": base_trend,
        "volume": volume,
        "last_price": round(float(peer_s.iloc[-1]), 4),
        "base_last_price": round(float(base_s.iloc[-1]), 4),
        "trade": trade,
        "series": series,
        "plain_english": (
            f"{symbol} is {status.lower()} than {base_symbol} by {rs_pct:+.2f}% "
            f"over {lb} bars (peer {peer_ret:+.2f}% vs base {base_ret:+.2f}%). "
            f"Trade lean: {trade['action']} · confidence {trade['confidence_pct']}%."
        ),
    }


def compute_comparative_strength(
    *,
    asset_class: str,
    base_symbol: str,
    compare_symbols: list[str],
    timeframe: str = "1d",
    lookback_bars: int = 20,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    """Compare one base ticker against one or more peers."""
    asset_class = (asset_class or "india").strip().lower()
    if asset_class not in ("india", "us", "crypto", "commodity"):
        asset_class = "india"
    timeframe = (timeframe or "1d").strip()
    # Accept any known duration; unknown → 1d
    if timeframe not in TIMEFRAME_OPTIONS:
        # tolerate aliases
        aliases = {"daily": "1d", "day": "1d", "weekly": "1w", "week": "1w", "60m": "1h", "240m": "4h"}
        timeframe = aliases.get(timeframe.lower(), timeframe)
    if timeframe not in TIMEFRAME_OPTIONS:
        timeframe = "1d"
    lookback = int(lookback_bars or 20)
    lookback = max(3, min(120, lookback))

    base = (base_symbol or "").strip().upper()
    peers: list[str] = []
    seen = {base}
    for raw in compare_symbols or []:
        sym = str(raw or "").strip().upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        peers.append(sym)

    if not base:
        return {"error": "Select a base index or stock.", "rows": []}
    if not peers:
        return {"error": "Select at least one compare ticker different from the base.", "rows": []}

    market = _market_for(asset_class)
    # Intraday needs more bars for overlap; daily/weekly less
    if timeframe in ("1m", "5m"):
        limit = max(400, lookback + 120)
    elif timeframe in ("15m", "30m", "1h"):
        limit = max(320, lookback + 100)
    else:
        limit = max(260, lookback + 80)

    try:
        base_df = _fetch_ohlcv(
            base, market, timeframe,
            asset_class=asset_class, groww_token=groww_token, exchange=exchange, limit=limit,
        )
    except Exception as exc:
        return {
            "error": f"Failed to load base {base}: {exc}",
            "base_symbol": base,
            "rows": [],
        }

    min_needed = max(8, min(_MIN_BARS, lookback + 2))
    if base_df.empty or len(base_df) < min_needed:
        return {
            "error": (
                f"Could not load enough bars for base {base} on {timeframe} "
                f"(got {0 if base_df is None or base_df.empty else len(base_df)}). "
                "Try another symbol, a higher timeframe, or check Groww/Yahoo connectivity."
            ),
            "base_symbol": base,
            "rows": [],
        }

    peer_frames: dict[str, pd.DataFrame] = {}
    errors: list[str] = []

    def _one(sym: str) -> tuple[str, pd.DataFrame | None, str | None]:
        try:
            df = _fetch_ohlcv(
                sym, market, timeframe,
                asset_class=asset_class, groww_token=groww_token, exchange=exchange, limit=limit,
            )
            if df.empty or len(df) < min_needed:
                return sym, None, f"{sym}: insufficient data ({0 if df is None or df.empty else len(df)} bars)"
            return sym, df, None
        except Exception as exc:
            return sym, None, f"{sym}: {exc}"

    with ThreadPoolExecutor(max_workers=min(8, max(1, len(peers)))) as pool:
        futs = [pool.submit(_one, s) for s in peers]
        for fut in as_completed(futs):
            sym, df, err = fut.result()
            if err or df is None:
                errors.append(err or f"{sym}: failed")
            else:
                peer_frames[sym] = df

    base_trend = _trend_stack(base_df["close"].astype(float))
    base_ret = _pct_change(base_df["close"].astype(float), min(lookback, len(base_df) - 2))

    rows: list[dict[str, Any]] = []
    for sym in peers:
        if sym not in peer_frames:
            rows.append({
                "symbol": sym,
                "status": "ERROR",
                "error": next((e for e in errors if e.startswith(sym)), "fetch failed"),
            })
            continue
        rows.append(
            _analyze_peer(
                symbol=sym,
                peer_df=peer_frames[sym],
                base_df=base_df,
                base_symbol=base,
                lookback=lookback,
            )
        )

    ok_rows = [r for r in rows if r.get("status") in ("STRONGER", "WEAKER", "INLINE")]
    stronger = sorted(
        [r for r in ok_rows if r.get("status") == "STRONGER"],
        key=lambda r: float(r.get("relative_strength_pct") or 0),
        reverse=True,
    )
    weaker = sorted(
        [r for r in ok_rows if r.get("status") == "WEAKER"],
        key=lambda r: float(r.get("relative_strength_pct") or 0),
    )
    inline = [r for r in ok_rows if r.get("status") == "INLINE"]

    ideas: list[dict[str, Any]] = []
    for r in ok_rows:
        t = r.get("trade") or {}
        if t.get("action") in ("LONG", "SHORT", "LONG_WATCH", "SHORT_WATCH"):
            ideas.append({
                "symbol": r["symbol"],
                "action": t.get("action"),
                "side": t.get("side"),
                "confidence_pct": t.get("confidence_pct"),
                "relative_strength_pct": r.get("relative_strength_pct"),
                "thesis": t.get("thesis"),
                "reasons": t.get("reasons") or [],
            })
    ideas.sort(key=lambda x: (0 if x["action"] in ("LONG", "SHORT") else 1, -int(x.get("confidence_pct") or 0)))

    parts = [
        f"Base: {base} ({timeframe}, {lookback} bars). Base return "
        f"{base_ret if base_ret is not None else '—'}%. Trend: {base_trend.get('bias', '—')}."
    ]
    if stronger:
        top = ", ".join(f"{r['symbol']} ({r['relative_strength_pct']:+.1f}%)" for r in stronger[:5])
        parts.append(f"Stronger than base: {top}.")
    if weaker:
        bot = ", ".join(f"{r['symbol']} ({r['relative_strength_pct']:+.1f}%)" for r in weaker[:5])
        parts.append(f"Weaker than base: {bot}.")
    if ideas:
        best = ideas[0]
        parts.append(
            f"Top idea: {best['action']} {best['symbol']} "
            f"(RS {best['relative_strength_pct']:+.1f}%, conf {best['confidence_pct']}%)."
        )
    else:
        parts.append("No high-conviction relative long/short right now — wait for a clearer RS stretch.")

    return {
        "asset_class": asset_class,
        "market": market,
        "base_symbol": base,
        "timeframe": timeframe,
        "lookback_bars": lookback,
        "base_return_pct": base_ret,
        "base_trend": base_trend,
        "base_last_price": round(float(base_df["close"].iloc[-1]), 4),
        "compared_count": len(peers),
        "scanned_ok": len(ok_rows),
        "rows": rows,
        "stronger": stronger,
        "weaker": weaker,
        "inline": inline,
        "trade_ideas": ideas,
        "errors": errors,
        "summary": " ".join(parts),
        "how_to_read": [
            "Relative strength % = peer return − base return over the lookback.",
            "+ve = peer stronger than base · −ve = peer weaker than base.",
            "LONG ideas favor outperforming peers with constructive trend/CRS.",
            "SHORT ideas favor underperforming peers (or rotate capital into the base).",
            "Confidence blends RS magnitude, multi-horizon agreement, CRS slope, EMA stack, and volume.",
            "Educational only — not financial advice. Size risk and confirm with price action.",
        ],
    }
