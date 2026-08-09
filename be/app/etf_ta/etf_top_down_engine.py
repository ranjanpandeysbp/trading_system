"""
etf_top_down_engine.py
----------------------
ETF Top Down — Low-risk / high-reward ETF swing (Jay / Finding H podcast).

Video: https://www.youtube.com/watch?v=a4FmBVfjtNA&t=29s

Pipeline:
  1. Top-down macro filter — rank Gold, Silver, Nifty 50, Nifty 500,
     GS Composite (bond proxy), India VIX (inverted) via P&F RS scores.
  2. ETF scanner — score ~55 ETFs vs Nifty 50 + Nifty 500 (multi-denominator
     P&F RS, −3…+3 per leg); keep Top N with score > 0.
  3. Execution — Renko bricks + D-Smart 10 proxy (EMA of Renko closes):
     BUY when price crosses above D-Smart 10; SELL / trail when below.
  4. Weekly rebalance preference (Fridays) — volatile assets (e.g. Silver)
     need weekly checks so gains are not given back.

Research / education only — not financial advice. D-Smart is approximated
(Definedge proprietary); P&F scoring follows the video's published rules.
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

# Macro proxies (India-friendly symbols / Yahoo tickers)
MACRO_ASSETS: list[dict[str, Any]] = [
    {"id": "gold", "label": "Gold", "symbol": "GOLDBEES", "yf": ["GOLDBEES.NS", "GC=F"], "invert": False},
    {"id": "silver", "label": "Silver", "symbol": "SILVERBEES", "yf": ["SILVERBEES.NS", "SI=F"], "invert": False},
    {"id": "nifty50", "label": "Nifty 50", "symbol": "NIFTYBEES", "yf": ["^NSEI", "NIFTYBEES.NS"], "invert": False},
    {"id": "nifty500", "label": "Nifty 500", "symbol": "MONIFTY500", "yf": ["^CRSLDX", "MONIFTY500.NS", "BSE500IETF.NS"], "invert": False},
    {"id": "gs_composite", "label": "GS Composite / Bonds", "symbol": "SETF10GILT", "yf": ["^TNX", "TLT", "SETF10GILT.NS"], "invert": True},
    {"id": "india_vix", "label": "India VIX", "symbol": "INDIAVIX", "yf": ["^INDIAVIX"], "invert": True},
]

HOW_IT_WORKS = """
### How ETF Top Down works

Low-drawdown ETF swing: **top-down asset filter → Relative Strength (P&F) → Renko + D-Smart 10**,
rebalanced **weekly (Fridays)**.

| Step | Rule |
|------|------|
| 1 | Rank **6 macros**: Gold, Silver, Nifty 50, Nifty 500, GS Composite/bonds, India VIX |
| 2 | Score each vs denominators with **P&F RS** (−3…+3 per leg; DTB above MA = +3) |
| 3 | Scan ETF universe (~55); keep **Top 20 with RS score > 0** |
| 4 | **Buy** when Renko price crosses **above D-Smart 10**; **sell** when it falls below |
| 5 | Prefer **Friday** weekly rebalance — Silver-like volatility needs weekly checks |

**How to use this screen**
1. Pick ETF universe (FIRE / ETF Shop / Combined — same lists as other ETF strategies).
2. Scan — read macro leaders first, then Top-20 RS ETFs with BUY/SELL from Renko+D-Smart.
3. Prefer acting on Fridays; trail exits with D-Smart 10.
4. Research only — not advice. D-Smart approximated as EMA(10) on Renko closes.
""".strip()

RULES = [
    "Top-down: filter macros before picking ETFs.",
    "P&F RS score −3…+3 (Double Top Buy above MA = +3; DBS below MA = −3).",
    "Multi-denominator vs Nifty 50 + Nifty 500 (and macros in the board).",
    "Shortlist Top N ETFs with RS score strictly > 0.",
    "Entry: Renko close crosses above D-Smart 10.",
    "Exit / trail: Renko close falls below D-Smart 10.",
    "Weekly rebalance preferred (Fridays).",
]

ETF_TOP_DOWN_AI_SYSTEM = pro_trade_ai_system(
    STRATEGY_NAME,
    "Top-down ETF swing: macro RS filter, P&F relative strength ranking, "
    "Renko + D-Smart 10 entry/exit, weekly Friday rebalance.",
)


@dataclass
class EtfTopDownConfig:
    top_n: int = 20
    min_rs_score: float = 0.01  # strictly > 0
    lookback_bars: int = 400
    chart_bars: int = 120
    pn_f_box_pct: float = 0.25  # ~daily equivalent (video: 0.25% daily, 1% weekly)
    pn_f_ma_period: int = 10
    renko_box_pct: float = 1.0  # weekly-style brick %
    d_smart_period: int = 10
    max_etfs_hold: int = 10
    prefer_friday: bool = True


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
            df = fetch_ohlcv_yfinance(yf_sym, "1d", is_crypto=False, limit=limit, market=market)
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


def analyze_macro_board(
    *,
    cfg: EtfTopDownConfig,
    groww_token: str = "",
    exchange: str = "NSE",
) -> list[dict[str, Any]]:
    frames: dict[str, pd.DataFrame] = {}
    for m in MACRO_ASSETS:
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

    for m in MACRO_ASSETS:
        mid = m["id"]
        s = series.get(mid)
        if s is None or s.empty:
            rows.append({
                "id": mid, "label": m["label"], "symbol": m["symbol"],
                "error": "No data", "total_score": None, "rank": None,
            })
            continue
        # For inverted assets (VIX, yields), use reciprocal so "strength" = calm / falling yields
        work = (1.0 / s.replace(0, np.nan)) if m.get("invert") else s
        work = work.dropna()
        price_leg = _price_pnf_score(work, box_pct=cfg.pn_f_box_pct, ma_period=cfg.pn_f_ma_period)
        legs = {"price": price_leg}
        total = int(price_leg.get("score") or 0)
        if nifty is not None and mid != "nifty50":
            d1 = _rs_score_vs_benchmark(work, nifty, box_pct=cfg.pn_f_box_pct, ma_period=cfg.pn_f_ma_period)
            legs["vs_nifty50"] = d1
            total += int(d1.get("score") or 0)
        if nifty500 is not None and mid != "nifty500":
            d2 = _rs_score_vs_benchmark(work, nifty500, box_pct=cfg.pn_f_box_pct, ma_period=cfg.pn_f_ma_period)
            legs["vs_nifty500"] = d2
            total += int(d2.get("score") or 0)

        last = float(s.iloc[-1])
        rows.append({
            "id": mid,
            "label": m["label"],
            "symbol": m["symbol"],
            "ltp": _r(last),
            "invert": bool(m.get("invert")),
            "total_score": total,
            "legs": legs,
            "dominating": total > 0,
        })

    scored = [r for r in rows if r.get("total_score") is not None]
    scored.sort(key=lambda r: float(r["total_score"]), reverse=True)
    for i, r in enumerate(scored):
        r["rank"] = i + 1
    # preserve order by rank for scored; append errors
    err = [r for r in rows if r.get("total_score") is None]
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
    price_leg = _price_pnf_score(close, box_pct=cfg.pn_f_box_pct, ma_period=cfg.pn_f_ma_period)
    legs = {"price": price_leg}
    total = int(price_leg.get("score") or 0)
    if nifty is not None:
        d1 = _rs_score_vs_benchmark(close, nifty, box_pct=cfg.pn_f_box_pct, ma_period=cfg.pn_f_ma_period)
        legs["vs_nifty50"] = d1
        total += int(d1.get("score") or 0)
    if nifty500 is not None:
        d2 = _rs_score_vs_benchmark(close, nifty500, box_pct=cfg.pn_f_box_pct, ma_period=cfg.pn_f_ma_period)
        legs["vs_nifty500"] = d2
        total += int(d2.get("score") or 0)

    renko = _build_renko(close, cfg.renko_box_pct)
    ds = _d_smart_signal(renko, cfg.d_smart_period)

    action = "WAIT"
    signal = "NEUTRAL"
    reason = ""
    if total > 0 and ds.get("crossed_above"):
        action, signal = "BUY", "BUY"
        reason = f"RS {total} > 0 and Renko crossed above D-Smart {cfg.d_smart_period}"
    elif total > 0 and ds.get("action") == "HOLD_LONG":
        action, signal = "HOLD", "HOLD"
        reason = f"RS {total} > 0 and price above D-Smart {cfg.d_smart_period} — trail"
    elif ds.get("crossed_below") or ds.get("action") == "FLAT":
        action, signal = "SELL", "SELL"
        reason = f"Renko below D-Smart {cfg.d_smart_period} — exit / trail stop"
    elif total <= 0:
        action, signal = "SKIP", "WEAK"
        reason = f"RS score {total} ≤ 0 — filtered out (need outperformance)"
    else:
        reason = "Waiting for Renko × D-Smart cross"

    checks = [
        {"id": "rs_pos", "label": "RS score > 0", "passed": total > 0, "detail": f"score {total}"},
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
        "legs": legs,
        "d_smart": ds,
        "signal": signal,
        "action": action,
        "take_trade": take,
        "reason": reason,
        "checks": checks,
        "metrics": {
            "rs_score": total,
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

    return {
        "strategy": STRATEGY_ID,
        "strategy_label": STRATEGY_NAME,
        "youtube": YOUTUBE_URL,
        "how_it_works": HOW_IT_WORKS,
        "rules": RULES,
        "config": {
            "top_n": cfg.top_n,
            "min_rs_score": cfg.min_rs_score,
            "pn_f_box_pct": cfg.pn_f_box_pct,
            "renko_box_pct": cfg.renko_box_pct,
            "d_smart_period": cfg.d_smart_period,
            "max_etfs_hold": cfg.max_etfs_hold,
            "prefer_friday": cfg.prefer_friday,
        },
        "macro_board": macro,
        "macro_leader": leader,
        "rebalance_hint": {
            "prefer_friday": cfg.prefer_friday,
            "is_friday_utc": is_friday,
            "note": "Rebalance weekly — prefer Fridays (IST). Silver-like names need weekly exits.",
        },
        "summary": {
            "scanned": len(results),
            "shortlisted": len(shortlist),
            "buy": len(buys),
            "sell": len(sells),
            "hold": len(holds),
            "errors": len([r for r in results if r.get("error")]),
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
            "P&F RS follows the video scoring rules."
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
    }
    return {
        "strategy": STRATEGY_ID,
        "strategy_label": STRATEGY_NAME,
        "youtube": YOUTUBE_URL,
        "presets": presets,
        "default_preset": "Top ~55 (FIRE + ETF Shop)",
        "default_symbols": top55,
        "how_it_works": HOW_IT_WORKS,
        "rules": RULES,
        "macro_assets": [{"id": m["id"], "label": m["label"], "symbol": m["symbol"]} for m in MACRO_ASSETS],
    }
