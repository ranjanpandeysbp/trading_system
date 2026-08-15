"""
etf_top_down_engine.py
----------------------
ETF Top Down — Low-drawdown ETF swing (Jay / Finding Edge podcast).

Video: https://www.youtube.com/watch?v=a4FmBVfjtNA&t=29s

Two principles: (1) make profit (2) don't give the profit back (control drawdown).
ETFs as a product give phase-linked returns with typically milder drawdowns than
single stocks (sector baskets ≈ what MFs hold).

Pipeline:
  1. Noise filter — concentrate on 6 macros: Gold, USD/INR, India VIX,
     GS Composite (bond-yield proxy), Nifty 50, Nifty 500 (+ Silver for RS).
  2. Top-down sieve — Asset → Group → Sector → ETF via Relative Strength.
  3. P&F RS multi-denominator — box 0.25% ≈ daily, 1% ≈ weekly; each leg
     scores −3…+3 (DTB above MA = +3 … DBS below MA = −3). Six legs → max 18.
  4. ETF scanner — ~55 ETFs vs Nifty 50 + Nifty 500; keep Top N with score > 0.
  5. Execution — Renko + D-Smart 10: BUY cross above; SELL / trail below.
  6. Weekly rebalance (Fridays) — volatile names (e.g. Silver) need weekly exits
     so monthly gains are not erased.

Expected returns are phase-relative (not COVID-era 50–100%): MF-like ~12%;
beat MF ~15–18% when entries + sentiment align; strong bull + flows ~24%.
~2–2.5y live experience cited: market flat but strategy ~+5–6% alpha vs market.

Research / education only — not financial advice. D-Smart approximated
(Definedge proprietary); P&F scoring follows the podcast rules.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.etf_ta.etf_28_sma_universe import (
    ETF_28_SMA_PRESETS,
    canonicalize_symbol,
    fire_28_sma_symbols,
)
from app.etf_ta.india_etf_universe import ETF_SHOP_39_PRIMARY, GROWW_INDIA_MARKET
from app.etf_ta.stf_shop_engine import fetch_stf_etf_data
from app.market_pulse.gap_trading import fetch_ohlcv_yfinance
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.pro_trade_shared import build_pro_trade_ai_context, pro_trade_ai_system

logger = logging.getLogger(__name__)

STRATEGY_ID = "etf_top_down"
STRATEGY_NAME = "ETF Top Down"
YOUTUBE_URL = "https://www.youtube.com/watch?v=a4FmBVfjtNA&t=29s"

# Noise-filter macros (podcast: ignore daily noise — these 6 interconnect everything)
# + Silver for asset RS ranking examples (Gold/Silver rallies)
# India VIX live LTP preferred from 5paisa: https://www.5paisa.com/share-market-today/india-vix
MACRO_ASSETS: list[dict[str, Any]] = [
    {"id": "gold", "label": "Gold", "symbol": "GOLDBEES", "yf": ["GOLDBEES.NS", "GC=F"], "invert": False, "role": "noise"},
    {"id": "usdinr", "label": "USD / INR", "symbol": "USDINR", "yf": ["INR=X", "USDINR=X"], "invert": False, "role": "noise"},
    {
        "id": "india_vix",
        "label": "India VIX",
        "symbol": "INDIAVIX",
        "yf": ["^INDIAVIX"],
        "invert": True,
        "role": "noise",
        "live_source": "5paisa",
        "live_url": "https://www.5paisa.com/share-market-today/india-vix",
    },
    {"id": "gs_composite", "label": "GS Composite / Bonds", "symbol": "SETF10GILT", "yf": ["^TNX", "TLT", "SETF10GILT.NS"], "invert": True, "role": "noise"},
    {"id": "nifty50", "label": "Nifty 50", "symbol": "NIFTYBEES", "yf": ["^NSEI", "NIFTYBEES.NS"], "invert": False, "role": "noise"},
    {"id": "nifty500", "label": "Nifty 500", "symbol": "MONIFTY500", "yf": ["^CRSLDX", "MONIFTY500.NS", "BSE500IETF.NS"], "invert": False, "role": "noise"},
    {"id": "silver", "label": "Silver", "symbol": "SILVERBEES", "yf": ["SILVERBEES.NS", "SI=F"], "invert": False, "role": "asset_rs"},
]

# India VIX regimes (podcast): >18 fear, <12 calm / all-clear
VIX_FEAR_ABOVE = 18.0
VIX_CALM_BELOW = 12.0

# Max composite = 6 legs × 3 pts (price+D1+D2) × (daily 0.25% + weekly 1%)
MAX_RS_SCORE = 18

HOW_IT_WORKS = """
### How ETF Top Down works (Finding Edge — Jay)

**Two principles:** (1) Profit from the market. (2) Do not give that profit back —
drawdowns that erase 40% of gains defeat the point. ETFs fit because sector baskets
typically fall less than single stocks when the index drops ~20%, and returns follow
the **market phase** (sentiment + valuation + flows).

**Noise filter (6 macros):** Gold · USD/INR · India VIX · GS Composite/bond yields ·
Nifty 50 · Nifty 500. (Silver is scored for asset RS too.) VIX **>18 = fear**,
**<12 = calm**. Money rotates between risk assets and US/GS yields.

**Top-down sieve:** Asset → Group → Sector → ETF (same stack hedge/MF desks use),
ranked by **Relative Strength** on Point & Figure.

| Step | Rule |
|------|------|
| 1 | Rank macros / assets with **P&F RS** (multi-denominator) |
| 2 | Box **0.25% ≈ daily**, **1% ≈ weekly**; each leg −3…+3 |
| 3 | Legs: Price + vs Nifty50 (D1) + vs Nifty500 (D2) × 2 TF → **max 18** |
| 4 | Scan ~55 ETFs; keep **Top 20 with RS score > 0** |
| 5 | **Buy** Renko close crosses **above D-Smart 10**; **sell** when below |
| 6 | Prefer **Friday** weekly rebalance (Silver-like names need weekly exits) |

**P&F score card (above MA / bullish trend)**
| Pattern | Score |
|---------|------:|
| Double Top Buy above MA | +3 |
| X column (no DTB) | +2 |
| O column retracement (no DBS) | +1 |
| Double Bottom Sell (still above MA) | −1 |

**Below MA / bearish:** DBS = −3 · O column = −2 · DTB below MA = +1 · X (no DTB) = −1

**Expected CAGR (phase-relative, not a promise):** ~12% MF-like baseline; **15–18%**
when entries + sentiment align (beat MF); up to **~24%** in a strong bull with flows.
COVID-style 50–100% was valuation-suppressed — do not expect a repeat. Live cite:
~2–2.5 years, market weak but strategy still **~5–6% alpha** vs market.

**How to use this screen**
1. Read macro / asset board first (who is dominating?).
2. Focus Top-20 RS ETFs (score > 0), then Renko × D-Smart BUY/SELL.
3. Prefer Friday fills; trail with D-Smart 10.
4. Research only — not advice. D-Smart ≈ EMA(10) on Renko closes.
""".strip()

RULES = [
    "Two principles: make profit; do not give profit back (drawdown control).",
    "Noise filter: Gold, USD/INR, India VIX, GS Composite/bonds, Nifty 50, Nifty 500 (+ Silver RS).",
    "India VIX: >18 fear · <12 calm (live LTP from 5paisa.com/share-market-today/india-vix).",
    "Top-down sieve: Asset → Group → Sector → ETF via Relative Strength.",
    "P&F box 0.25% ≈ daily, 1% ≈ weekly; score −3…+3 per leg (DTB above MA = +3).",
    "Six legs (price + D1 Nifty50 + D2 Nifty500 × daily + weekly) → max score 18.",
    "Shortlist Top N ETFs with composite RS score strictly > 0.",
    "Entry: Renko close crosses above D-Smart 10; exit / trail when below.",
    "Weekly rebalance preferred (Fridays) — protect gains on volatile ETFs.",
    "Returns are phase-relative (~12 / 15–18 / ~24% bands) — not COVID-era guarantees.",
]

ETF_TOP_DOWN_AI_SYSTEM = pro_trade_ai_system(
    STRATEGY_NAME,
    "Top-down ETF swing (Jay / Finding Edge): noise-filter macros, dual P&F RS "
    "(0.25% daily + 1% weekly, max 18), Top-20 score > 0, Renko + D-Smart 10, "
    "weekly Friday rebalance. Principles: profit + don't give it back.",
)


@dataclass
class EtfTopDownConfig:
    top_n: int = 20
    min_rs_score: float = 0.01  # strictly > 0
    lookback_bars: int = 400
    chart_bars: int = 120
    pn_f_box_pct: float = 0.25  # ~daily (podcast: 0.25% daily, 1% weekly)
    pn_f_weekly_box_pct: float = 1.0
    pn_f_ma_period: int = 10
    renko_box_pct: float = 1.0  # weekly-style brick %
    d_smart_period: int = 10
    max_etfs_hold: int = 10
    prefer_friday: bool = True
    use_dual_tf_rs: bool = True  # daily 0.25% + weekly 1% → max 18


def _r(x: float, n: int = 4) -> float:
    return round(float(x), n)


def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    out = normalize_ohlcv(df) if df is not None else pd.DataFrame()
    if out is None or out.empty:
        return pd.DataFrame()
    out = out.copy()
    out.columns = [str(c).lower() for c in out.columns]
    for col in ("open", "high", "low", "close", "volume"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out.dropna(subset=["close"])


def _fetch_symbol(
    symbol: str,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
    market: str = GROWW_INDIA_MARKET,
    limit: int = 400,
    yf_candidates: list[str] | None = None,
) -> pd.DataFrame:
    try:
        df = fetch_stf_etf_data(symbol, groww_token=groww_token, exchange=exchange, limit=limit, market=market)
        work = _normalize_df(df)
        if len(work) >= 60:
            return work
    except Exception:
        logger.debug("Groww fetch failed for %s", symbol, exc_info=True)
    for yf_sym in yf_candidates or [f"{symbol}.NS", symbol]:
        try:
            from app.market_pulse.ticker_utils import is_crypto_market

            df = fetch_ohlcv_yfinance(
                yf_sym,
                "1d",
                is_crypto=is_crypto_market(market),
                limit=limit,
                market=market,
            )
            work = _normalize_df(df)
            if len(work) >= 40:
                return work
        except Exception:
            continue
    return pd.DataFrame()


# ── Point & Figure helpers ───────────────────────────────────────────────────

def _build_pnf_columns(closes: pd.Series, box_pct: float) -> list[dict[str, Any]]:
    """Classic % box P&F: X = up column, O = down column. 3-box reversal."""
    vals = [float(x) for x in closes.dropna().tolist() if np.isfinite(float(x)) and float(x) > 0]
    if len(vals) < 5 or box_pct <= 0:
        return []
    box = box_pct / 100.0
    columns: list[dict[str, Any]] = []
    direction: str | None = None  # "X" or "O"
    col_high = vals[0]
    col_low = vals[0]
    ref = vals[0]

    def _boxes_up(a: float, b: float) -> int:
        if a <= 0:
            return 0
        return int(np.floor(np.log(b / a) / np.log(1.0 + box) + 1e-12))

    def _boxes_down(a: float, b: float) -> int:
        if a <= 0:
            return 0
        return int(np.floor(np.log(a / b) / np.log(1.0 + box) + 1e-12))

    for px in vals[1:]:
        if direction is None:
            up = _boxes_up(ref, px)
            dn = _boxes_down(ref, px)
            if up >= 1:
                direction = "X"
                col_high = px
                col_low = ref
                columns.append({"type": "X", "high": col_high, "low": col_low, "boxes": up})
            elif dn >= 1:
                direction = "O"
                col_high = ref
                col_low = px
                columns.append({"type": "O", "high": col_high, "low": col_low, "boxes": dn})
            continue

        if direction == "X":
            up = _boxes_up(col_high, px)
            if up >= 1:
                col_high = px
                columns[-1]["high"] = col_high
                columns[-1]["boxes"] = int(columns[-1]["boxes"]) + up
            else:
                dn = _boxes_down(col_high, px)
                if dn >= 3:
                    direction = "O"
                    col_low = px
                    col_high = columns[-1]["high"]
                    columns.append({"type": "O", "high": col_high, "low": col_low, "boxes": dn})
        else:
            dn = _boxes_down(col_low, px)
            if dn >= 1:
                col_low = px
                columns[-1]["low"] = col_low
                columns[-1]["boxes"] = int(columns[-1]["boxes"]) + dn
            else:
                up = _boxes_up(col_low, px)
                if up >= 3:
                    direction = "X"
                    col_high = px
                    col_low = columns[-1]["low"]
                    columns.append({"type": "X", "high": col_high, "low": col_low, "boxes": up})
    return columns


def _pnf_pattern_score(columns: list[dict[str, Any]], price: float, ma: float) -> tuple[int, str]:
    """Video rules: score −3…+3 from last P&F column + MA position."""
    if not columns:
        return 0, "no_pnf"
    last = columns[-1]
    prev = columns[-2] if len(columns) >= 2 else None
    typ = str(last["type"])
    above_ma = price >= ma if np.isfinite(ma) and ma > 0 else True

    # Double Top Buy: new X column high exceeds prior X column high
    dtb = False
    dbs = False
    if typ == "X" and prev is not None:
        prior_x_highs = [c["high"] for c in columns[:-1] if c["type"] == "X"]
        if prior_x_highs and float(last["high"]) > max(float(x) for x in prior_x_highs):
            dtb = True
    if typ == "O" and prev is not None:
        prior_o_lows = [c["low"] for c in columns[:-1] if c["type"] == "O"]
        if prior_o_lows and float(last["low"]) < min(float(x) for x in prior_o_lows):
            dbs = True

    if above_ma:
        if dtb:
            return 3, "double_top_buy_above_ma"
        if typ == "X":
            return 2, "x_column_above_ma"
        if dbs:
            return -1, "dbs_but_above_ma"
        return 1, "o_column_retracement_above_ma"

    # below MA
    if dbs:
        return -3, "double_bottom_sell_below_ma"
    if typ == "O":
        return -2, "o_column_below_ma"
    if dtb:
        return 1, "dtb_below_ma"
    return -1, "x_column_below_ma"


def _rs_score_vs_benchmark(
    asset_close: pd.Series,
    bench_close: pd.Series,
    *,
    box_pct: float,
    ma_period: int,
) -> dict[str, Any]:
    aligned = pd.concat([asset_close.rename("a"), bench_close.rename("b")], axis=1).dropna()
    if len(aligned) < max(30, ma_period + 5):
        return {"score": 0, "pattern": "insufficient", "ratio": None}
    ratio = aligned["a"] / aligned["b"].replace(0, np.nan)
    ratio = ratio.dropna()
    if len(ratio) < 20:
        return {"score": 0, "pattern": "insufficient", "ratio": None}
    cols = _build_pnf_columns(ratio, box_pct)
    ma = float(ratio.rolling(ma_period).mean().iloc[-1])
    px = float(ratio.iloc[-1])
    score, pattern = _pnf_pattern_score(cols, px, ma)
    return {
        "score": int(score),
        "pattern": pattern,
        "ratio": _r(px, 6),
        "ratio_ma": _r(ma, 6),
        "column": cols[-1]["type"] if cols else None,
    }


def _price_pnf_score(close: pd.Series, *, box_pct: float, ma_period: int) -> dict[str, Any]:
    if close is None or len(close) < max(30, ma_period + 5):
        return {"score": 0, "pattern": "insufficient"}
    cols = _build_pnf_columns(close, box_pct)
    ma = float(close.rolling(ma_period).mean().iloc[-1])
    px = float(close.iloc[-1])
    score, pattern = _pnf_pattern_score(cols, px, ma)
    return {"score": int(score), "pattern": pattern, "ma": _r(ma), "column": cols[-1]["type"] if cols else None}


def _score_bundle_at_box(
    close: pd.Series,
    nifty: pd.Series | None,
    nifty500: pd.Series | None,
    *,
    box_pct: float,
    ma_period: int,
    skip_d1: bool = False,
    skip_d2: bool = False,
) -> tuple[int, dict[str, Any]]:
    """One timeframe: price + D1 (Nifty50) + D2 (Nifty500). Max +9."""
    price_leg = _price_pnf_score(close, box_pct=box_pct, ma_period=ma_period)
    legs: dict[str, Any] = {"price": price_leg}
    total = int(price_leg.get("score") or 0)
    if nifty is not None and not skip_d1:
        d1 = _rs_score_vs_benchmark(close, nifty, box_pct=box_pct, ma_period=ma_period)
        legs["vs_nifty50"] = d1
        total += int(d1.get("score") or 0)
    if nifty500 is not None and not skip_d2:
        d2 = _rs_score_vs_benchmark(close, nifty500, box_pct=box_pct, ma_period=ma_period)
        legs["vs_nifty500"] = d2
        total += int(d2.get("score") or 0)
    return total, legs


def _composite_rs_score(
    close: pd.Series,
    nifty: pd.Series | None,
    nifty500: pd.Series | None,
    *,
    cfg: EtfTopDownConfig,
    skip_d1: bool = False,
    skip_d2: bool = False,
) -> dict[str, Any]:
    """
    Podcast composite: daily (0.25%) + weekly (1%) bundles.
    Each bundle = price + D1 + D2 (−3…+3 each) → max 18 when dual TF enabled.
    """
    daily_total, daily_legs = _score_bundle_at_box(
        close, nifty, nifty500,
        box_pct=cfg.pn_f_box_pct,
        ma_period=cfg.pn_f_ma_period,
        skip_d1=skip_d1,
        skip_d2=skip_d2,
    )
    legs: dict[str, Any] = {"daily": daily_legs, "daily_box_pct": cfg.pn_f_box_pct}
    total = daily_total
    weekly_total = 0
    if cfg.use_dual_tf_rs:
        weekly_total, weekly_legs = _score_bundle_at_box(
            close, nifty, nifty500,
            box_pct=cfg.pn_f_weekly_box_pct,
            ma_period=cfg.pn_f_ma_period,
            skip_d1=skip_d1,
            skip_d2=skip_d2,
        )
        legs["weekly"] = weekly_legs
        legs["weekly_box_pct"] = cfg.pn_f_weekly_box_pct
        total += weekly_total
    max_possible = MAX_RS_SCORE if cfg.use_dual_tf_rs else 9
    # Fewer legs if denominators skipped (e.g. Nifty itself)
    if skip_d1:
        max_possible -= 3 if not cfg.use_dual_tf_rs else 6
    if skip_d2:
        max_possible -= 3 if not cfg.use_dual_tf_rs else 6
    return {
        "total": int(total),
        "daily_total": int(daily_total),
        "weekly_total": int(weekly_total),
        "max_score": int(max(max_possible, 3)),
        "legs": legs,
    }


def _vix_regime(raw_vix: float | None) -> dict[str, Any]:
    if raw_vix is None or not np.isfinite(raw_vix):
        return {"level": None, "regime": "unknown", "note": "India VIX unavailable"}
    if raw_vix > VIX_FEAR_ABOVE:
        regime, note = "fear", f"India VIX {raw_vix:.1f} > {VIX_FEAR_ABOVE:.0f} — fear / risk-off bias"
    elif raw_vix < VIX_CALM_BELOW:
        regime, note = "calm", f"India VIX {raw_vix:.1f} < {VIX_CALM_BELOW:.0f} — calm / risk-on bias"
    else:
        regime, note = "neutral", f"India VIX {raw_vix:.1f} — between calm ({VIX_CALM_BELOW:.0f}) and fear ({VIX_FEAR_ABOVE:.0f})"
    return {"level": _r(raw_vix, 2), "regime": regime, "note": note}


# ── Renko + D-Smart ──────────────────────────────────────────────────────────

def _build_renko(closes: pd.Series, box_pct: float) -> pd.DataFrame:
    vals = [float(x) for x in closes.dropna().tolist() if np.isfinite(float(x)) and float(x) > 0]
    if len(vals) < 5 or box_pct <= 0:
        return pd.DataFrame()
    box = box_pct / 100.0
    bricks: list[dict[str, Any]] = []
    ref = vals[0]
    for px in vals[1:]:
        while px >= ref * (1.0 + box):
            new_ref = ref * (1.0 + box)
            bricks.append({"close": new_ref, "dir": 1, "open": ref})
            ref = new_ref
        while px <= ref / (1.0 + box):
            new_ref = ref / (1.0 + box)
            bricks.append({"close": new_ref, "dir": -1, "open": ref})
            ref = new_ref
    if not bricks:
        return pd.DataFrame()
    return pd.DataFrame(bricks)


def _d_smart_signal(renko: pd.DataFrame, period: int = 10) -> dict[str, Any]:
    """D-Smart 10 proxy = EMA(period) of Renko closes (Definedge indicator approximated)."""
    if renko is None or renko.empty or len(renko) < period + 2:
        return {"action": "WAIT", "d_smart": None, "renko_close": None, "crossed_above": False, "crossed_below": False}
    closes = renko["close"].astype(float)
    dsmart = closes.ewm(span=period, adjust=False).mean()
    c0, c1 = float(closes.iloc[-2]), float(closes.iloc[-1])
    d0, d1 = float(dsmart.iloc[-2]), float(dsmart.iloc[-1])
    above = c1 > d1
    below = c1 < d1
    crossed_above = c0 <= d0 and c1 > d1
    crossed_below = c0 >= d0 and c1 < d1
    if crossed_above or (above and not crossed_below):
        action = "BUY" if crossed_above else "HOLD_LONG"
    elif crossed_below or below:
        action = "SELL" if crossed_below else "FLAT"
    else:
        action = "WAIT"
    return {
        "action": action,
        "d_smart": _r(d1),
        "renko_close": _r(c1),
        "above_d_smart": above,
        "crossed_above": crossed_above,
        "crossed_below": crossed_below,
        "bricks": len(renko),
    }


def _align_benchmarks(
    frames: dict[str, pd.DataFrame],
) -> dict[str, pd.Series]:
    out: dict[str, pd.Series] = {}
    for k, df in frames.items():
        if df is not None and not df.empty and "close" in df.columns:
            out[k] = df["close"].astype(float)
    return out


def _ohlc_row(close: float, *, open_: float | None = None, high: float | None = None, low: float | None = None) -> dict[str, float]:
    c = float(close)
    o = float(open_ if open_ is not None else c)
    h = float(high if high is not None else max(o, c))
    l = float(low if low is not None else min(o, c))
    return {"open": o, "high": h, "low": l, "close": c, "volume": 0.0}


def _fetch_india_vix_frame(
    *,
    limit: int = 400,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    India VIX history for RS + live LTP from 5paisa.

    Live: https://www.5paisa.com/share-market-today/india-vix
    History fallback: Yahoo ^INDIAVIX (when available).
    """
    meta: dict[str, Any] = {
        "live_source": None,
        "history_source": None,
        "url": "https://www.5paisa.com/share-market-today/india-vix",
        "quote": None,
    }
    quote = None
    try:
        from app.market_pulse.news_scanner import fetch_india_vix_5paisa

        quote = fetch_india_vix_5paisa()
    except Exception:
        logger.debug("5paisa India VIX fetch failed", exc_info=True)

    hist = pd.DataFrame()
    # Prefer direct Yahoo ^INDIAVIX (do not append .NS — common VIX quirk)
    try:
        import yfinance as yf

        raw = yf.Ticker("^INDIAVIX").history(period="2y", interval="1d", auto_adjust=True)
        if raw is not None and not raw.empty:
            work = raw.rename(columns={c: str(c).lower() for c in raw.columns})
            keep = [c for c in ("open", "high", "low", "close", "volume") if c in work.columns]
            hist = work[keep].dropna(subset=["close"]).tail(limit)
            if not hist.empty:
                hist.index = pd.to_datetime(hist.index).tz_localize(None)
                meta["history_source"] = "yfinance:^INDIAVIX"
    except Exception:
        logger.debug("Yahoo ^INDIAVIX history failed", exc_info=True)

    live_px = float(quote["price"]) if quote and quote.get("price") is not None else None
    if live_px is not None and live_px > 0:
        meta["live_source"] = "5paisa.com"
        meta["quote"] = quote
        today = pd.Timestamp.now(tz=None).normalize()
        row = _ohlc_row(
            live_px,
            open_=quote.get("open"),
            high=quote.get("day_high"),
            low=quote.get("day_low"),
        )
        if hist.empty:
            prev = quote.get("prev_close")
            idx = [today - pd.Timedelta(days=1), today]
            rows = [
                _ohlc_row(float(prev)) if prev else row,
                row,
            ]
            hist = pd.DataFrame(rows, index=pd.DatetimeIndex(idx))
            meta["history_source"] = "5paisa.com (live + prev_close)"
        else:
            work = hist.copy()
            idx = pd.to_datetime(work.index)
            if getattr(idx, "tz", None) is not None:
                idx = idx.tz_convert(None)
            work.index = idx
            last_idx = pd.Timestamp(work.index[-1]).normalize()
            if last_idx >= today - pd.Timedelta(days=1):
                for col, val in row.items():
                    if col in work.columns:
                        work.iloc[-1, work.columns.get_loc(col)] = val
            else:
                work.loc[today] = {c: row.get(c, 0.0) for c in work.columns}
            hist = work

    return hist, meta


def analyze_macro_board(
    *,
    cfg: EtfTopDownConfig,
    groww_token: str = "",
    exchange: str = "NSE",
) -> list[dict[str, Any]]:
    frames: dict[str, pd.DataFrame] = {}
    vix_meta: dict[str, Any] = {}
    for m in MACRO_ASSETS:
        if m["id"] == "india_vix":
            frames[m["id"]], vix_meta = _fetch_india_vix_frame(limit=cfg.lookback_bars)
        else:
            frames[m["id"]] = _fetch_symbol(
                str(m["symbol"]),
                groww_token=groww_token,
                exchange=exchange,
                limit=cfg.lookback_bars,
                yf_candidates=list(m.get("yf") or []),
            )

    series = _align_benchmarks(frames)
    nifty = series.get("nifty50")
    nifty500 = series.get("nifty500")
    rows: list[dict[str, Any]] = []
    # Prefer live 5paisa LTP for regime (fear/calm), else last history close
    vix_raw = None
    if vix_meta.get("quote") and vix_meta["quote"].get("price") is not None:
        vix_raw = float(vix_meta["quote"]["price"])
    elif "india_vix" in series and not series["india_vix"].empty:
        vix_raw = float(series["india_vix"].iloc[-1])
    vix_info = _vix_regime(vix_raw)
    if vix_meta.get("live_source"):
        vix_info = {
            **vix_info,
            "source": vix_meta.get("live_source"),
            "url": vix_meta.get("url"),
            "as_of": (vix_meta.get("quote") or {}).get("as_of"),
            "change_pct": (vix_meta.get("quote") or {}).get("pct"),
            "history_source": vix_meta.get("history_source"),
        }

    for m in MACRO_ASSETS:
        mid = m["id"]
        s = series.get(mid)
        if s is None or s.empty:
            err_row: dict[str, Any] = {
                "id": mid, "label": m["label"], "symbol": m["symbol"],
                "role": m.get("role"), "error": "No data", "total_score": None, "rank": None,
            }
            if mid == "india_vix" and vix_raw is not None:
                # Still surface live 5paisa quote for regime even without history
                err_row.pop("error", None)
                err_row.update({
                    "ltp": _r(vix_raw),
                    "total_score": None,
                    "vix_regime": vix_info,
                    "live_source": vix_meta.get("live_source"),
                    "source_url": vix_meta.get("url"),
                    "note": "Live VIX from 5paisa; history unavailable for full RS score",
                })
            rows.append(err_row)
            continue
        # Inverted assets (VIX, yields): reciprocal so "strength" = calm / falling yields
        work = (1.0 / s.replace(0, np.nan)) if m.get("invert") else s
        work = work.dropna()
        composite = _composite_rs_score(
            work, nifty, nifty500, cfg=cfg,
            skip_d1=(mid == "nifty50"),
            skip_d2=(mid == "nifty500"),
        )
        total = int(composite["total"])
        last = float(s.iloc[-1])
        if mid == "india_vix" and vix_raw is not None:
            last = float(vix_raw)
        row: dict[str, Any] = {
            "id": mid,
            "label": m["label"],
            "symbol": m["symbol"],
            "role": m.get("role"),
            "ltp": _r(last),
            "invert": bool(m.get("invert")),
            "total_score": total,
            "daily_score": composite.get("daily_total"),
            "weekly_score": composite.get("weekly_total"),
            "max_score": composite.get("max_score"),
            "legs": composite.get("legs"),
            "dominating": total > 0,
        }
        if mid == "india_vix":
            row["vix_regime"] = vix_info
            row["live_source"] = vix_meta.get("live_source") or "yfinance"
            row["source_url"] = vix_meta.get("url") or m.get("live_url")
            if vix_meta.get("quote"):
                row["change_pct"] = vix_meta["quote"].get("pct")
                row["as_of"] = vix_meta["quote"].get("as_of")
        rows.append(row)

    scored = [r for r in rows if r.get("total_score") is not None]
    scored.sort(key=lambda r: float(r["total_score"]), reverse=True)
    for i, r in enumerate(scored):
        r["rank"] = i + 1
    err = [r for r in rows if r.get("total_score") is None]
    # Attach board-level VIX note on first row metadata via caller — return vix separately
    for r in scored + err:
        r["board_vix"] = vix_info
    return scored + err


def analyze_etf(
    symbol: str,
    df: pd.DataFrame,
    *,
    nifty: pd.Series | None,
    nifty500: pd.Series | None,
    cfg: EtfTopDownConfig,
) -> dict[str, Any]:
    sym = canonicalize_symbol(symbol)
    base: dict[str, Any] = {
        "ticker": sym,
        "strategy": STRATEGY_ID,
        "signal": "WAIT",
        "action": "WAIT",
        "take_trade": False,
        "rs_score": 0,
        "checks": [],
        "metrics": {},
    }
    work = _normalize_df(df)
    if work.empty or len(work) < 60:
        base["error"] = f"Need ≥60 daily bars; got {len(work)}"
        return base

    close = work["close"].astype(float)
    composite = _composite_rs_score(close, nifty, nifty500, cfg=cfg)
    total = int(composite["total"])
    legs = composite.get("legs") or {}

    renko = _build_renko(close, cfg.renko_box_pct)
    ds = _d_smart_signal(renko, cfg.d_smart_period)

    action = "WAIT"
    signal = "NEUTRAL"
    reason = ""
    score_bit = f"RS {total}/{composite.get('max_score', MAX_RS_SCORE)}"
    if total > 0 and ds.get("crossed_above"):
        action, signal = "BUY", "BUY"
        reason = f"{score_bit} > 0 and Renko crossed above D-Smart {cfg.d_smart_period}"
    elif total > 0 and ds.get("action") == "HOLD_LONG":
        action, signal = "HOLD", "HOLD"
        reason = f"{score_bit} > 0 and price above D-Smart {cfg.d_smart_period} — trail"
    elif ds.get("crossed_below") or ds.get("action") == "FLAT":
        action, signal = "SELL", "SELL"
        reason = f"Renko below D-Smart {cfg.d_smart_period} — exit / trail stop"
    elif total <= 0:
        action, signal = "SKIP", "WEAK"
        reason = f"{score_bit} ≤ 0 — filtered out (need outperformance)"
    else:
        reason = "Waiting for Renko × D-Smart cross"

    checks = [
        {
            "id": "rs_pos",
            "label": f"RS score > 0 (max {composite.get('max_score', MAX_RS_SCORE)})",
            "passed": total > 0,
            "detail": (
                f"total {total} · daily {composite.get('daily_total')} · "
                f"weekly {composite.get('weekly_total')}"
            ),
        },
        {
            "id": "dsmart", "label": f"Above D-Smart {cfg.d_smart_period}",
            "passed": bool(ds.get("above_d_smart")),
            "detail": f"Renko {_r(ds.get('renko_close') or 0)} vs DS {_r(ds.get('d_smart') or 0)}",
        },
        {
            "id": "cross_up", "label": "Crossed above D-Smart",
            "passed": bool(ds.get("crossed_above")),
            "detail": "entry trigger" if ds.get("crossed_above") else "—",
        },
    ]

    # chart: last N daily bars + SMA proxy for D-Smart visual on candle chart
    tail = work.iloc[-cfg.chart_bars:].copy()
    tail["sma_ds"] = tail["close"].ewm(span=cfg.d_smart_period, adjust=False).mean()
    chart_data = []
    for idx, bar in tail.iterrows():
        chart_data.append({
            "time": str(idx)[:10],
            "open": _r(float(bar["open"])),
            "high": _r(float(bar["high"])),
            "low": _r(float(bar["low"])),
            "close": _r(float(bar["close"])),
            "sma_ds": _r(float(bar["sma_ds"])) if pd.notna(bar.get("sma_ds")) else None,
        })

    take = action in ("BUY", "SELL")
    return {
        **base,
        "ltp": _r(float(close.iloc[-1])),
        "rs_score": total,
        "daily_score": composite.get("daily_total"),
        "weekly_score": composite.get("weekly_total"),
        "max_score": composite.get("max_score"),
        "legs": legs,
        "d_smart": ds,
        "signal": signal,
        "action": action,
        "take_trade": take,
        "reason": reason,
        "checks": checks,
        "metrics": {
            "rs_score": total,
            "daily_score": composite.get("daily_total"),
            "weekly_score": composite.get("weekly_total"),
            "max_score": composite.get("max_score"),
            "d_smart": ds.get("d_smart"),
            "renko_close": ds.get("renko_close"),
            "renko_bricks": ds.get("bricks"),
            "above_d_smart": ds.get("above_d_smart"),
            "bar_date": str(work.index[-1])[:10],
        },
        "trade_suggestion": {"action": action, "reason": reason},
        "chart_data": chart_data,
        "chart_series": [{"key": "sma_ds", "label": f"D-Smart≈EMA{cfg.d_smart_period}", "color": "#a78bfa"}],
        "chart_levels": (
            [{"price": ds["d_smart"], "label": "D-Smart 10", "color": "#a78bfa"}]
            if ds.get("d_smart") is not None else []
        ),
    }


def scan_universe(
    tickers: list[str],
    *,
    cfg: EtfTopDownConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
    market: str = GROWW_INDIA_MARKET,
) -> dict[str, Any]:
    cfg = cfg or EtfTopDownConfig()
    symbols: list[str] = []
    seen: set[str] = set()
    for t in tickers:
        s = canonicalize_symbol(t)
        if s and s not in seen:
            seen.add(s)
            symbols.append(s)

    macro = analyze_macro_board(cfg=cfg, groww_token=groww_token, exchange=exchange)
    nifty_df = _fetch_symbol("NIFTYBEES", groww_token=groww_token, exchange=exchange, limit=cfg.lookback_bars,
                             yf_candidates=["^NSEI", "NIFTYBEES.NS"])
    n500_df = _fetch_symbol("MONIFTY500", groww_token=groww_token, exchange=exchange, limit=cfg.lookback_bars,
                            yf_candidates=["^CRSLDX", "MONIFTY500.NS", "BSE500IETF.NS"])
    nifty = nifty_df["close"].astype(float) if not nifty_df.empty else None
    nifty500 = n500_df["close"].astype(float) if not n500_df.empty else None

    results: list[dict[str, Any]] = []
    for sym in symbols:
        try:
            df = _fetch_symbol(sym, groww_token=groww_token, exchange=exchange, market=market, limit=cfg.lookback_bars)
            results.append(analyze_etf(sym, df, nifty=nifty, nifty500=nifty500, cfg=cfg))
        except Exception as exc:
            logger.exception("ETF Top Down failed for %s", sym)
            results.append({"ticker": sym, "strategy": STRATEGY_ID, "error": str(exc)[:240], "rs_score": 0, "action": "WAIT"})

    # Rank by RS; shortlist top_n with score > 0
    ranked = sorted(
        [r for r in results if not r.get("error")],
        key=lambda r: float(r.get("rs_score") or 0),
        reverse=True,
    )
    for i, r in enumerate(ranked):
        r["rs_rank"] = i + 1
        score = float(r.get("rs_score") or 0)
        if score > cfg.min_rs_score and i < cfg.top_n:
            r["shortlisted"] = True
        else:
            r["shortlisted"] = False
            if score <= cfg.min_rs_score:
                r["action"] = "SKIP"
                r["take_trade"] = False
                if not r.get("reason"):
                    r["reason"] = f"RS {score} ≤ 0 — not shortlisted"
            elif i >= cfg.top_n:
                r["action"] = "WATCH"
                r["take_trade"] = False
                r["reason"] = (r.get("reason") or "") + f" · Outside Top {cfg.top_n}"

    shortlist = [r for r in ranked if r.get("shortlisted")]
    buys = [r for r in shortlist if r.get("action") == "BUY"]
    sells = [r for r in results if r.get("action") == "SELL"]
    holds = [r for r in shortlist if r.get("action") == "HOLD"]

    today = pd.Timestamp.utcnow()
    is_friday = bool(today.dayofweek == 4)  # UTC approx; UI notes IST Friday
    leader = macro[0] if macro and macro[0].get("total_score") is not None else None
    vix_info = (macro[0].get("board_vix") if macro else None) or _vix_regime(None)

    return {
        "strategy": STRATEGY_ID,
        "strategy_label": STRATEGY_NAME,
        "youtube": YOUTUBE_URL,
        "how_it_works": HOW_IT_WORKS,
        "rules": RULES,
        "philosophy": {
            "principles": [
                "Make profit from the market.",
                "Do not give that profit back — control drawdown.",
            ],
            "why_etf": (
                "Sector ETFs ≈ the baskets MFs hold; typically milder drawdowns than "
                "single stocks when the index drops ~20%. Returns follow market phase."
            ),
            "expected_cagr": {
                "mf_like": "~12%",
                "beat_mf_aligned": "15–18%",
                "strong_bull": "up to ~24%",
                "note": "Phase-relative — not COVID-era 50–100% guarantees.",
            },
            "live_alpha_cite": "~5–6% alpha vs market over ~2–2.5 years (even when market was flat).",
        },
        "config": {
            "top_n": cfg.top_n,
            "min_rs_score": cfg.min_rs_score,
            "pn_f_box_pct": cfg.pn_f_box_pct,
            "pn_f_weekly_box_pct": cfg.pn_f_weekly_box_pct,
            "use_dual_tf_rs": cfg.use_dual_tf_rs,
            "max_rs_score": MAX_RS_SCORE if cfg.use_dual_tf_rs else 9,
            "renko_box_pct": cfg.renko_box_pct,
            "d_smart_period": cfg.d_smart_period,
            "max_etfs_hold": cfg.max_etfs_hold,
            "prefer_friday": cfg.prefer_friday,
        },
        "macro_board": macro,
        "macro_leader": leader,
        "vix_regime": vix_info,
        "rebalance_hint": {
            "prefer_friday": cfg.prefer_friday,
            "is_friday_utc": is_friday,
            "note": (
                "Rebalance weekly — prefer Fridays (IST). "
                "Volatile names (e.g. Silver) need weekly exits so gains are not given back."
            ),
        },
        "summary": {
            "scanned": len(results),
            "shortlisted": len(shortlist),
            "buy": len(buys),
            "sell": len(sells),
            "hold": len(holds),
            "errors": len([r for r in results if r.get("error")]),
            "macro_leader": (leader or {}).get("label") if leader else None,
            "vix_regime": (vix_info or {}).get("regime"),
        },
        "shortlist": shortlist,
        "daily_board": {"buys": buys, "sells": sells, "holds": holds},
        "results": ranked + [r for r in results if r.get("error")],
        "entry_count": len(buys) + len(sells),
        "scanned": len(results),
        "ai_system_prompt": ETF_TOP_DOWN_AI_SYSTEM,
        "disclaimer": (
            "Research / education only — not financial advice. "
            "D-Smart approximated as EMA on Renko closes (Definedge proprietary). "
            "P&F RS follows Finding Edge / Jay podcast scoring (0.25% daily + 1% weekly, max 18)."
        ),
    }


def build_etf_top_down_ai_prompt(result: dict[str, Any]) -> str:
    extra = [
        f"Action: {result.get('action')}",
        f"RS score: {result.get('rs_score')}",
        f"D-Smart: {result.get('d_smart')}",
        f"Reason: {result.get('reason')}",
    ]
    return build_pro_trade_ai_context(result, engine_label=STRATEGY_NAME, extra_lines=extra)


def universe_payload() -> dict[str, Any]:
    from app.etf_ta.etf_28_sma_universe import etf_28_sma_preset_asset_class
    from app.etf_ta.multi_asset_etf_universe import cross_asset_scan_presets

    # Prefer ~55 liquid names: FIRE list capped + shop primary
    fire = fire_28_sma_symbols()
    shop = [canonicalize_symbol(s) for s in ETF_SHOP_39_PRIMARY]
    top55: list[str] = []
    seen: set[str] = set()
    for s in fire + shop:
        if s and s not in seen:
            seen.add(s)
            top55.append(s)
        if len(top55) >= 55:
            break

    presets = {
        "Top ~55 (FIRE + ETF Shop)": top55,
        **{k: list(v) for k, v in ETF_28_SMA_PRESETS.items()},
        # Ensure cross-asset keys stay present even if 28-SMA dict changes
        **{k: list(v) for k, v in cross_asset_scan_presets().items() if k not in ETF_28_SMA_PRESETS},
    }
    return {
        "strategy": STRATEGY_ID,
        "strategy_label": STRATEGY_NAME,
        "youtube": YOUTUBE_URL,
        "presets": presets,
        "preset_asset_class": {k: etf_28_sma_preset_asset_class(k) for k in presets},
        "default_preset": "Top ~55 (FIRE + ETF Shop)",
        "default_symbols": top55,
        "how_it_works": HOW_IT_WORKS,
        "rules": RULES,
        "macro_assets": [{"id": m["id"], "label": m["label"], "symbol": m["symbol"]} for m in MACRO_ASSETS],
    }
