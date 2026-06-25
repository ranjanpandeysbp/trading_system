"""
commodity_screener_engine.py
----------------------------
Multi-commodity signal engine — yfinance prices, multi-timeframe moves,
correlated Nifty index and US equity trade ideas.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# ── Commodity metadata & Yahoo tickers ─────────────────────────────────────

COMMODITY_META: dict[str, dict[str, str | float]] = {
    "OIL": {"name": "WTI Crude Oil", "unit": "$/bbl", "yf": "CL=F"},
    "GOLD": {"name": "Gold Spot", "unit": "$/oz", "yf": "GC=F"},
    "SILVER": {"name": "Silver Spot", "unit": "$/oz", "yf": "SI=F"},
    "NATGAS": {"name": "Natural Gas", "unit": "$/MMBtu", "yf": "NG=F"},
    "COPPER": {"name": "Copper", "unit": "$/lb", "yf": "HG=F"},
    "WHEAT": {"name": "Wheat", "unit": "¢/bu", "yf": "ZW=F"},
    "IRON": {"name": "Iron Ore (BHP proxy)", "unit": "$/t proxy", "yf": "BHP"},
}

TIMEFRAME_CONFIG: dict[str, dict[str, Any]] = {
    "15 Mins": {"kind": "intraday", "interval": "15m", "bars": 1, "period": "5d", "label": "15-minute bar"},
    "1 Hour": {"kind": "intraday", "interval": "1h", "bars": 1, "period": "1mo", "label": "1-hour bar"},
    "4 Hours": {"kind": "intraday", "interval": "1h", "bars": 4, "period": "1mo", "label": "~4 hourly bars"},
    "1 Day": {"kind": "daily", "bars": 1, "label": "1 session"},
    "1 Week": {"kind": "daily", "bars": 5, "label": "~5 sessions"},
    "1 Month": {"kind": "daily", "bars": 21, "label": "~21 sessions"},
    "3 Months": {"kind": "daily", "bars": 63, "label": "~63 sessions"},
}

# US equities — from original commodity_trader correlation map
US_CORRELATIONS: dict[str, list[dict]] = {
    "OIL": [
        {"ticker": "XOM", "sector": "Integrated Oil", "corr": +0.92, "lag": 0},
        {"ticker": "CVX", "sector": "Integrated Oil", "corr": +0.90, "lag": 0},
        {"ticker": "SLB", "sector": "Oil Services", "corr": +0.85, "lag": 1},
        {"ticker": "AAL", "sector": "Airlines", "corr": -0.78, "lag": 2},
        {"ticker": "DAL", "sector": "Airlines", "corr": -0.76, "lag": 2},
        {"ticker": "LYB", "sector": "Chemicals", "corr": -0.60, "lag": 2},
    ],
    "GOLD": [
        {"ticker": "NEM", "sector": "Gold Mining", "corr": +0.88, "lag": 0},
        {"ticker": "GDX", "sector": "Gold ETF", "corr": +0.95, "lag": 0},
        {"ticker": "TLT", "sector": "Long Bonds", "corr": +0.65, "lag": 1},
    ],
    "SILVER": [
        {"ticker": "PAAS", "sector": "Silver Mining", "corr": +0.90, "lag": 0},
        {"ticker": "SLV", "sector": "Silver ETF", "corr": +0.96, "lag": 0},
        {"ticker": "ENPH", "sector": "Solar/Clean", "corr": +0.60, "lag": 2},
    ],
    "NATGAS": [
        {"ticker": "EQT", "sector": "Gas E&P", "corr": +0.89, "lag": 0},
        {"ticker": "NEE", "sector": "Utilities", "corr": -0.55, "lag": 2},
        {"ticker": "CF", "sector": "Fertilisers", "corr": -0.70, "lag": 2},
    ],
    "COPPER": [
        {"ticker": "FCX", "sector": "Copper Mining", "corr": +0.91, "lag": 0},
        {"ticker": "TSLA", "sector": "EV / Battery", "corr": +0.60, "lag": 2},
        {"ticker": "CAT", "sector": "Industrials", "corr": +0.72, "lag": 1},
    ],
    "WHEAT": [
        {"ticker": "ADM", "sector": "Agri Processing", "corr": +0.80, "lag": 1},
        {"ticker": "GIS", "sector": "Consumer Food", "corr": -0.55, "lag": 3},
        {"ticker": "MOS", "sector": "Fertilisers", "corr": +0.62, "lag": 2},
    ],
    "IRON": [
        {"ticker": "VALE", "sector": "Iron Ore Mining", "corr": +0.92, "lag": 0},
        {"ticker": "NUE", "sector": "Steel", "corr": +0.78, "lag": 1},
        {"ticker": "STLD", "sector": "Steel", "corr": +0.76, "lag": 1},
    ],
}

# Nifty sectoral indices — India macro linkage
NIFTY_CORRELATIONS: dict[str, list[dict]] = {
    "OIL": [
        {"ticker": "NIFTY ENERGY", "sector": "Oil & Gas", "corr": +0.82, "lag": 0},
        {"ticker": "NIFTY METAL", "sector": "Metals (input costs)", "corr": +0.35, "lag": 1},
        {"ticker": "NIFTY AUTO", "sector": "Auto (fuel cost)", "corr": -0.48, "lag": 2},
        {"ticker": "NIFTY FMCG", "sector": "FMCG (input costs)", "corr": -0.42, "lag": 2},
        {"ticker": "NIFTY CHEMICALS", "sector": "Chemicals", "corr": -0.58, "lag": 2},
        {"ticker": "NIFTY 50", "sector": "Broad market", "corr": -0.25, "lag": 3},
    ],
    "GOLD": [
        {"ticker": "NIFTY METAL", "sector": "Precious / base metals", "corr": +0.45, "lag": 1},
        {"ticker": "NIFTY FMCG", "sector": "Defensive", "corr": +0.30, "lag": 2},
        {"ticker": "NIFTY BANK", "sector": "Risk-off headwind", "corr": -0.40, "lag": 1},
        {"ticker": "NIFTY IT", "sector": "Risk-off headwind", "corr": -0.35, "lag": 2},
        {"ticker": "NIFTY FINANCIAL SERVICES", "sector": "Risk sentiment", "corr": -0.38, "lag": 2},
    ],
    "SILVER": [
        {"ticker": "NIFTY METAL", "sector": "Industrial metals", "corr": +0.72, "lag": 0},
        {"ticker": "NIFTY ENERGY", "sector": "Energy complex", "corr": +0.40, "lag": 1},
        {"ticker": "NIFTY AUTO", "sector": "Industrial demand", "corr": +0.38, "lag": 2},
    ],
    "NATGAS": [
        {"ticker": "NIFTY ENERGY", "sector": "Gas & power", "corr": +0.75, "lag": 0},
        {"ticker": "NIFTY CHEMICALS", "sector": "Fertilisers / gas feed", "corr": -0.55, "lag": 2},
        {"ticker": "NIFTY FMCG", "sector": "Utilities pass-through", "corr": -0.30, "lag": 3},
    ],
    "COPPER": [
        {"ticker": "NIFTY METAL", "sector": "Base metals", "corr": +0.85, "lag": 0},
        {"ticker": "NIFTY AUTO", "sector": "EV / industrial", "corr": +0.50, "lag": 1},
        {"ticker": "NIFTY INFRA", "sector": "Infrastructure", "corr": +0.55, "lag": 1},
        {"ticker": "NIFTY REALTY", "sector": "Construction cycle", "corr": +0.42, "lag": 2},
        {"ticker": "NIFTY CEMENT", "sector": "Construction", "corr": +0.48, "lag": 2},
    ],
    "WHEAT": [
        {"ticker": "NIFTY FMCG", "sector": "Food margins", "corr": -0.52, "lag": 3},
        {"ticker": "NIFTY CHEMICALS", "sector": "Agri / fertilisers", "corr": +0.58, "lag": 2},
        {"ticker": "NIFTY CONSUMER DURABLES", "sector": "Rural demand", "corr": -0.35, "lag": 3},
    ],
    "IRON": [
        {"ticker": "NIFTY METAL", "sector": "Steel & mining", "corr": +0.88, "lag": 0},
        {"ticker": "NIFTY INFRA", "sector": "Infra spend", "corr": +0.62, "lag": 1},
        {"ticker": "NIFTY REALTY", "sector": "Construction", "corr": +0.50, "lag": 2},
        {"ticker": "NIFTY CEMENT", "sector": "Cement demand", "corr": +0.55, "lag": 2},
        {"ticker": "NIFTY AUTO", "sector": "Industrial cycle", "corr": +0.40, "lag": 2},
    ],
}

# CoinDCX USDT perpetual futures — macro / thematic linkage to commodities
CRYPTO_CORRELATIONS: dict[str, list[dict]] = {
    "OIL": [
        {"ticker": "BTC-USDT", "sector": "L1 — inflation / risk-off", "corr": -0.48, "lag": 1},
        {"ticker": "ETH-USDT", "sector": "L1 — energy cost headwind", "corr": -0.52, "lag": 1},
        {"ticker": "SOL-USDT", "sector": "High-beta L1", "corr": -0.58, "lag": 2},
        {"ticker": "DOGE-USDT", "sector": "Meme / risk-off", "corr": -0.50, "lag": 2},
        {"ticker": "AVAX-USDT", "sector": "Alt L1", "corr": -0.45, "lag": 2},
    ],
    "GOLD": [
        {"ticker": "BTC-USDT", "sector": "Digital gold narrative", "corr": +0.58, "lag": 0},
        {"ticker": "LTC-USDT", "sector": "Store-of-value peer", "corr": +0.42, "lag": 1},
        {"ticker": "ETH-USDT", "sector": "Risk rotation out of alts", "corr": -0.38, "lag": 1},
        {"ticker": "SOL-USDT", "sector": "High-beta alt", "corr": -0.45, "lag": 2},
        {"ticker": "PEPE-USDT", "sector": "Meme / risk-off", "corr": -0.48, "lag": 2},
        {"ticker": "SHIB-USDT", "sector": "Meme / risk-off", "corr": -0.46, "lag": 2},
    ],
    "SILVER": [
        {"ticker": "ETH-USDT", "sector": "Industrial / risk-on", "corr": +0.45, "lag": 1},
        {"ticker": "SOL-USDT", "sector": "High-beta L1", "corr": +0.48, "lag": 1},
        {"ticker": "LINK-USDT", "sector": "Oracle / infra", "corr": +0.40, "lag": 2},
        {"ticker": "RENDER-USDT", "sector": "Compute / industrial", "corr": +0.38, "lag": 2},
        {"ticker": "BTC-USDT", "sector": "Precious-metals complex", "corr": +0.35, "lag": 1},
    ],
    "NATGAS": [
        {"ticker": "BTC-USDT", "sector": "Inflation sensitivity", "corr": -0.40, "lag": 1},
        {"ticker": "ETH-USDT", "sector": "Energy cost / risk-off", "corr": -0.44, "lag": 2},
        {"ticker": "NEAR-USDT", "sector": "Alt L1", "corr": -0.35, "lag": 2},
        {"ticker": "FET-USDT", "sector": "AI / high-beta", "corr": -0.32, "lag": 3},
    ],
    "COPPER": [
        {"ticker": "BTC-USDT", "sector": "Risk-on / growth", "corr": +0.50, "lag": 1},
        {"ticker": "ETH-USDT", "sector": "Risk-on / growth", "corr": +0.54, "lag": 1},
        {"ticker": "SOL-USDT", "sector": "High-beta L1", "corr": +0.56, "lag": 1},
        {"ticker": "AVAX-USDT", "sector": "Alt L1", "corr": +0.48, "lag": 2},
        {"ticker": "INJ-USDT", "sector": "DeFi / growth", "corr": +0.45, "lag": 2},
        {"ticker": "SUI-USDT", "sector": "New L1 cycle", "corr": +0.42, "lag": 2},
    ],
    "WHEAT": [
        {"ticker": "BTC-USDT", "sector": "Food inflation / risk-off", "corr": -0.34, "lag": 2},
        {"ticker": "ETH-USDT", "sector": "Macro headwind", "corr": -0.38, "lag": 2},
        {"ticker": "UNI-USDT", "sector": "DeFi risk-off", "corr": -0.30, "lag": 3},
        {"ticker": "AAVE-USDT", "sector": "DeFi risk-off", "corr": -0.28, "lag": 3},
    ],
    "IRON": [
        {"ticker": "ETH-USDT", "sector": "Industrial cycle", "corr": +0.46, "lag": 1},
        {"ticker": "SOL-USDT", "sector": "Industrial / growth", "corr": +0.50, "lag": 1},
        {"ticker": "AVAX-USDT", "sector": "Alt L1 cycle", "corr": +0.44, "lag": 2},
        {"ticker": "DOT-USDT", "sector": "Infra / construction", "corr": +0.40, "lag": 2},
        {"ticker": "ARB-USDT", "sector": "L2 / infra spend", "corr": +0.36, "lag": 2},
        {"ticker": "BTC-USDT", "sector": "Macro risk-on", "corr": +0.38, "lag": 2},
    ],
}


@dataclass
class CommodityPrice:
    symbol: str
    name: str
    price: float
    prev_price: float
    unit: str
    change_pct: float = 0.0

    @property
    def direction(self) -> str:
        return "UP" if self.change_pct > 0 else "DOWN"


@dataclass
class TradeSignal:
    ticker: str
    sector: str
    direction: str
    confidence: float
    sl_pct: float
    tp_pct: float
    rationale: str
    commodity: str
    commodity_change: float
    timeframe: str = ""
    asset_class: str = "NIFTY"


def _rr_ratio(confidence: float) -> float:
    if confidence >= 80:
        return 3.0
    if confidence >= 65:
        return 2.5
    if confidence >= 50:
        return 2.0
    return 1.5


def _pct_return_over_bars(closes: pd.Series, bars: int) -> float | None:
    clean = closes.dropna()
    if len(clean) < 2:
        return None
    bars = min(int(bars), len(clean) - 1)
    if bars < 1:
        return None
    start = float(clean.iloc[-1 - bars])
    end = float(clean.iloc[-1])
    if start <= 0:
        return None
    return (end / start - 1) * 100


def _yf_close_series(raw: pd.DataFrame, yf_sym: str) -> pd.Series | None:
    if raw is None or raw.empty:
        return None
    try:
        if isinstance(raw.columns, pd.MultiIndex):
            if yf_sym in raw.columns.get_level_values(0):
                col = raw[yf_sym]["Close"] if "Close" in raw[yf_sym].columns else raw[yf_sym]["close"]
            else:
                return None
        elif "Close" in raw.columns:
            col = raw["Close"]
        else:
            return None
        closes = pd.to_numeric(col, errors="coerce").dropna()
        return closes if not closes.empty else None
    except Exception:
        return None


def fetch_commodity_close_series() -> dict[str, pd.Series]:
    """Daily closes for all tracked commodities (1y history)."""
    symbols = {sym: str(meta["yf"]) for sym, meta in COMMODITY_META.items()}
    tickers = list(dict.fromkeys(symbols.values()))
    out: dict[str, pd.Series] = {}
    try:
        raw = yf.download(
            tickers,
            period="1y",
            interval="1d",
            group_by="ticker",
            progress=False,
            auto_adjust=True,
            threads=True,
        )
    except Exception as exc:
        logger.warning("Commodity batch download failed: %s", exc)
        raw = pd.DataFrame()

    yf_to_sym = {v: k for k, v in symbols.items()}
    for yf_sym in tickers:
        closes = _yf_close_series(raw, yf_sym)
        if closes is not None:
            out[yf_to_sym.get(yf_sym, yf_sym)] = closes

    for sym, yf_sym in symbols.items():
        if sym in out:
            continue
        try:
            tdf = yf.download(yf_sym, period="1y", interval="1d", progress=False, auto_adjust=True)
            closes = _yf_close_series(tdf, yf_sym)
            if closes is not None:
                out[sym] = closes
        except Exception as exc:
            logger.debug("Commodity download skip %s: %s", yf_sym, exc)
    return out


def fetch_commodity_intraday_series(interval: str, period: str) -> dict[str, pd.Series]:
    """Intraday closes for commodities (15m / 1h bars)."""
    symbols = {sym: str(meta["yf"]) for sym, meta in COMMODITY_META.items()}
    tickers = list(dict.fromkeys(symbols.values()))
    out: dict[str, pd.Series] = {}
    try:
        raw = yf.download(
            tickers,
            period=period,
            interval=interval,
            group_by="ticker",
            progress=False,
            auto_adjust=True,
            threads=True,
        )
    except Exception as exc:
        logger.warning("Commodity intraday download failed (%s): %s", interval, exc)
        raw = pd.DataFrame()

    yf_to_sym = {v: k for k, v in symbols.items()}
    for yf_sym in tickers:
        closes = _yf_close_series(raw, yf_sym)
        if closes is not None:
            out[yf_to_sym.get(yf_sym, yf_sym)] = closes

    for sym, yf_sym in symbols.items():
        if sym in out:
            continue
        try:
            tdf = yf.download(
                yf_sym, period=period, interval=interval, progress=False, auto_adjust=True,
            )
            closes = _yf_close_series(tdf, yf_sym)
            if closes is not None:
                out[sym] = closes
        except Exception as exc:
            logger.debug("Commodity intraday skip %s: %s", yf_sym, exc)
    return out


def _intraday_cache_key(interval: str, period: str) -> str:
    return f"{interval}|{period}"


def _load_intraday_maps(timeframes: tuple[str, ...]) -> dict[str, dict[str, pd.Series]]:
    """Load intraday series keyed by interval|period for selected timeframes."""
    maps: dict[str, dict[str, pd.Series]] = {}
    for tf_label in timeframes:
        cfg = TIMEFRAME_CONFIG.get(tf_label) or {}
        if cfg.get("kind") != "intraday":
            continue
        interval = str(cfg["interval"])
        period = str(cfg.get("period") or "1mo")
        key = _intraday_cache_key(interval, period)
        if key not in maps:
            maps[key] = fetch_commodity_intraday_series(interval, period)
    return maps


def _series_for_timeframe(
    sym: str,
    tf_label: str,
    daily_map: dict[str, pd.Series],
    intraday_maps: dict[str, dict[str, pd.Series]],
) -> pd.Series | None:
    cfg = TIMEFRAME_CONFIG.get(tf_label)
    if not cfg:
        return None
    if cfg.get("kind") == "intraday":
        key = _intraday_cache_key(str(cfg["interval"]), str(cfg.get("period") or "1mo"))
        return (intraday_maps.get(key) or {}).get(sym)
    return daily_map.get(sym)


class SignalEngine:
    MIN_MOVE_PCT = 0.30

    def compute_signal(
        self,
        commodity: CommodityPrice,
        target: dict,
        *,
        timeframe: str = "",
        asset_class: str = "NIFTY",
    ) -> TradeSignal | None:
        move = commodity.change_pct
        if abs(move) < self.MIN_MOVE_PCT:
            return None

        corr = float(target["corr"])
        lag = int(target.get("lag") or 0)
        effective_move = move * corr
        if abs(effective_move) < 0.10:
            return None

        direction = "LONG" if effective_move > 0 else "SHORT"
        move_score = min(abs(move) / 3.0, 1.0)
        base_conf = abs(corr) * move_score * 100
        confidence = max(10.0, round(base_conf - lag * 6, 1))
        confidence = min(confidence, 97.0)

        vol_factor = abs(move) / 1.5
        sl = round(1.5 + vol_factor * 0.8, 2)
        tp = round(sl * _rr_ratio(confidence), 2)

        direction_word = "risen" if move > 0 else "fallen"
        rationale = (
            f"{commodity.name} {direction_word} {abs(move):.2f}% over {timeframe or 'window'} "
            f"(corr={corr:+.2f}, lag={lag}d)"
        )
        if confidence < 35:
            direction = "HOLD"

        return TradeSignal(
            ticker=target["ticker"],
            sector=target.get("sector", ""),
            direction=direction,
            confidence=confidence,
            sl_pct=sl,
            tp_pct=tp,
            rationale=rationale,
            commodity=commodity.symbol,
            commodity_change=move,
            timeframe=timeframe,
            asset_class=asset_class,
        )

    def compute_commodity_direct_trade(
        self,
        commodity: CommodityPrice,
        *,
        timeframe: str = "",
        yf_ticker: str = "",
    ) -> TradeSignal | None:
        """Direct commodity futures / proxy trade idea with SL% and TP%."""
        move = commodity.change_pct
        if abs(move) < self.MIN_MOVE_PCT:
            return None

        direction = "LONG" if move > 0 else "SHORT"
        move_score = min(abs(move) / 2.5, 1.0)
        confidence = max(35.0, round(move_score * 100, 1))
        confidence = min(confidence, 92.0)

        vol_factor = abs(move) / 1.5
        sl = round(1.2 + vol_factor * 0.9, 2)
        tp = round(sl * _rr_ratio(confidence), 2)

        # Tighter risk on short intraday windows
        if timeframe in ("15 Mins", "1 Hour"):
            sl = round(sl * 0.65, 2)
            tp = round(tp * 0.65, 2)
        elif timeframe == "4 Hours":
            sl = round(sl * 0.8, 2)
            tp = round(tp * 0.8, 2)

        direction_word = "risen" if move > 0 else "fallen"
        rationale = (
            f"{commodity.name} {direction_word} {abs(move):.2f}% over {timeframe} "
            f"— momentum {'continuation' if abs(move) > 0.6 else 'watch'} setup"
        )
        if confidence < 40:
            direction = "HOLD"

        return TradeSignal(
            ticker=yf_ticker or commodity.symbol,
            sector=commodity.name,
            direction=direction,
            confidence=confidence,
            sl_pct=sl,
            tp_pct=tp,
            rationale=rationale,
            commodity=commodity.symbol,
            commodity_change=move,
            timeframe=timeframe,
            asset_class="COMMODITY",
        )


def _commodity_stance(change_pct: float) -> str:
    if change_pct >= SignalEngine.MIN_MOVE_PCT:
        return "BUY"
    if change_pct <= -SignalEngine.MIN_MOVE_PCT:
        return "SELL"
    return "NEUTRAL"


def _merge_signal(
    bucket: dict[str, TradeSignal],
    sig: TradeSignal,
) -> None:
    key = sig.ticker
    existing = bucket.get(key)
    if not existing:
        bucket[key] = sig
        return
    if sig.confidence > existing.confidence:
        existing.direction = sig.direction
        existing.confidence = sig.confidence
        existing.sl_pct = sig.sl_pct
        existing.tp_pct = sig.tp_pct
        existing.rationale = sig.rationale
        existing.commodity = sig.commodity
        existing.commodity_change = sig.commodity_change
    existing.timeframe = (
        f"{existing.timeframe}, {sig.timeframe}".strip(", ")
        if existing.timeframe
        else sig.timeframe
    )


def scan_commodity_screener(
    timeframes: tuple[str, ...],
    min_move_pct: float = 0.30,
) -> dict | None:
    """Full scan: commodity moves per TF + Nifty / Crypto / US correlated signals."""
    if not timeframes:
        return None

    close_map = fetch_commodity_close_series()
    if not close_map:
        return None

    intraday_maps = _load_intraday_maps(timeframes)

    engine = SignalEngine()
    engine.MIN_MOVE_PCT = float(min_move_pct)

    commodity_rows: list[dict] = []
    commodity_trade_bucket: dict[str, TradeSignal] = {}
    nifty_bucket: dict[str, TradeSignal] = {}
    crypto_bucket: dict[str, TradeSignal] = {}
    us_bucket: dict[str, TradeSignal] = {}
    triggers: dict[str, list[TradeSignal]] = {}

    for sym, meta in COMMODITY_META.items():
        tf_moves: dict[str, float] = {}
        last_px: float | None = None

        for tf_label in timeframes:
            cfg = TIMEFRAME_CONFIG.get(tf_label)
            if not cfg:
                continue
            series = _series_for_timeframe(sym, tf_label, close_map, intraday_maps)
            if series is None or series.dropna().empty:
                continue
            clean = series.dropna()
            if last_px is None:
                last_px = float(clean.iloc[-1])
            chg = _pct_return_over_bars(clean, cfg["bars"])
            if chg is not None:
                tf_moves[tf_label] = chg

        if not tf_moves or last_px is None:
            continue

        clean_daily = close_map.get(sym)
        if clean_daily is not None and not clean_daily.dropna().empty:
            last_px = float(clean_daily.dropna().iloc[-1])

        avg_chg = sum(tf_moves.values()) / len(tf_moves)
        stances = [_commodity_stance(c) for c in tf_moves.values()]
        buy_votes = stances.count("BUY")
        sell_votes = stances.count("SELL")
        if buy_votes > sell_votes:
            consensus = "BUY"
        elif sell_votes > buy_votes:
            consensus = "SELL"
        else:
            consensus = "NEUTRAL"

        commodity_rows.append({
            "symbol": sym,
            "name": str(meta["name"]),
            "unit": str(meta["unit"]),
            "price": last_px,
            "tf_moves": tf_moves,
            "avg_change": round(avg_chg, 2),
            "consensus": consensus,
            "buy_votes": buy_votes,
            "sell_votes": sell_votes,
            "tf_count": len(tf_moves),
        })

        sym_signals: list[TradeSignal] = []
        for tf_label, chg in tf_moves.items():
            if abs(chg) < min_move_pct:
                continue
            prev = last_px / (1 + chg / 100) if chg != -100 else last_px
            comm = CommodityPrice(
                symbol=sym,
                name=str(meta["name"]),
                price=last_px,
                prev_price=prev,
                unit=str(meta["unit"]),
                change_pct=chg,
            )
            direct = engine.compute_commodity_direct_trade(
                comm, timeframe=tf_label, yf_ticker=str(meta["yf"]),
            )
            if direct:
                _merge_signal(commodity_trade_bucket, direct)
                sym_signals.append(direct)
            for target in NIFTY_CORRELATIONS.get(sym, []):
                sig = engine.compute_signal(
                    comm, target, timeframe=tf_label, asset_class="NIFTY",
                )
                if sig:
                    _merge_signal(nifty_bucket, sig)
                    sym_signals.append(sig)
            for target in CRYPTO_CORRELATIONS.get(sym, []):
                sig = engine.compute_signal(
                    comm, target, timeframe=tf_label, asset_class="CRYPTO",
                )
                if sig:
                    _merge_signal(crypto_bucket, sig)
                    sym_signals.append(sig)
            for target in US_CORRELATIONS.get(sym, []):
                sig = engine.compute_signal(
                    comm, target, timeframe=tf_label, asset_class="US",
                )
                if sig:
                    _merge_signal(us_bucket, sig)
                    sym_signals.append(sig)

        if sym_signals:
            sym_signals.sort(key=lambda x: x.confidence, reverse=True)
            triggers[sym] = sym_signals

    if not commodity_rows:
        return None

    commodity_trades = sorted(
        commodity_trade_bucket.values(), key=lambda x: x.confidence, reverse=True,
    )
    nifty_list = sorted(nifty_bucket.values(), key=lambda x: x.confidence, reverse=True)
    crypto_list = sorted(crypto_bucket.values(), key=lambda x: x.confidence, reverse=True)
    us_list = sorted(us_bucket.values(), key=lambda x: x.confidence, reverse=True)

    return {
        "commodities": commodity_rows,
        "commodity_trades": commodity_trades,
        "nifty_signals": nifty_list,
        "crypto_signals": crypto_list,
        "us_signals": us_list,
        "triggers": triggers,
        "timeframes": list(timeframes),
        "min_move_pct": min_move_pct,
        "data_feed": "yfinance",
    }
