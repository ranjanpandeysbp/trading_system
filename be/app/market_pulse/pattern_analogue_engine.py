"""
pattern_analogue_engine.py
--------------------------
Historical chart-shape analogue finder.

For a ticker + timeframe, take the most recent ``pattern_bars`` candles as the
template shape, search earlier history (chosen lookback / date range) for the
most similar windows, and report what happened in the next ``forward_bars``
after each match — plus aggregate bias stats for a forward prediction.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv

PATTERN_ANALOGUE_AI_SYSTEM = (
    "You are a desk analyst for Pattern Analogue Prediction. Conclude from the "
    "similarity matches and forward-outcome stats: what historically followed "
    "shapes like the current window. Cite match dates, avg/median forward return, "
    "and next-bar up-rate. Research/education only — not financial advice."
)


@dataclass
class PatternAnalogueConfig:
    timeframe: str = "15m"
    pattern_bars: int = 20
    forward_bars: int = 5
    search_lookback_bars: int = 500
    search_from_date: str = ""
    search_to_date: str = ""
    top_n: int = 10
    min_similarity: float = 0.82
    step: int = 1


def _parse_date(value: str | None) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw[:10], fmt)
        except ValueError:
            continue
    try:
        return pd.Timestamp(raw).to_pydatetime()
    except Exception:
        return None


def _bar_time(idx: Any) -> str:
    try:
        ts = pd.Timestamp(idx)
        if pd.isna(ts):
            return str(idx)
        return ts.isoformat()
    except Exception:
        return str(idx)


def _shape_vector(closes: np.ndarray) -> np.ndarray | None:
    """Normalize a close path to a comparable shape (z-scored relative returns)."""
    if closes is None or len(closes) < 3:
        return None
    base = float(closes[0])
    if not np.isfinite(base) or abs(base) < 1e-12:
        return None
    rel = closes / base - 1.0
    std = float(np.std(rel))
    if std < 1e-12:
        return np.zeros_like(rel)
    return (rel - float(np.mean(rel))) / (std + 1e-12)


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom < 1e-12:
        return 0.0
    return float(np.dot(a, b) / denom)


def _forward_stats(
    df: pd.DataFrame,
    end_i: int,
    forward_bars: int,
) -> dict[str, Any] | None:
    """Outcome after the window ending at ``end_i`` (inclusive)."""
    n = len(df)
    start_fwd = end_i + 1
    end_fwd = end_i + forward_bars
    if start_fwd >= n or end_fwd >= n:
        return None

    entry = float(df["close"].iloc[end_i])
    if not np.isfinite(entry) or abs(entry) < 1e-12:
        return None

    next_close = float(df["close"].iloc[start_fwd])
    fwd_close = float(df["close"].iloc[end_fwd])
    window = df.iloc[start_fwd : end_fwd + 1]
    max_high = float(window["high"].max())
    min_low = float(window["low"].min())

    next_ret = (next_close / entry - 1.0) * 100.0
    fwd_ret = (fwd_close / entry - 1.0) * 100.0
    mfe = (max_high / entry - 1.0) * 100.0
    mae = (min_low / entry - 1.0) * 100.0

    return {
        "next_bar_time": _bar_time(df.index[start_fwd]),
        "forward_end_time": _bar_time(df.index[end_fwd]),
        "entry_close": round(entry, 6),
        "next_close": round(next_close, 6),
        "forward_close": round(fwd_close, 6),
        "next_bar_return_pct": round(next_ret, 3),
        "forward_return_pct": round(fwd_ret, 3),
        "max_favorable_pct": round(mfe, 3),
        "max_adverse_pct": round(mae, 3),
        "next_direction": "UP" if next_ret > 0 else ("DOWN" if next_ret < 0 else "FLAT"),
        "forward_direction": "UP" if fwd_ret > 0 else ("DOWN" if fwd_ret < 0 else "FLAT"),
    }


def _filter_search_range(df: pd.DataFrame, cfg: PatternAnalogueConfig) -> pd.DataFrame:
    start = _parse_date(cfg.search_from_date)
    end = _parse_date(cfg.search_to_date)
    if start is None and end is None:
        return df
    out = df
    if start is not None:
        out = out[out.index >= pd.Timestamp(start)]
    if end is not None:
        # include the whole end day
        end_ts = pd.Timestamp(end) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        out = out[out.index <= end_ts]
    return out


def _fetch_limit(cfg: PatternAnalogueConfig) -> int:
    need = int(cfg.search_lookback_bars) + int(cfg.pattern_bars) + int(cfg.forward_bars) + 30
    # Intraday sources are thinner; still request enough for the search window.
    return max(120, min(need, 2500 if cfg.timeframe in ("1d", "1w", "1wk", "1M") else 1200))


def _template_label(df: pd.DataFrame, start_i: int, end_i: int) -> str:
    """Lightweight shape label from net move + path roughness."""
    closes = df["close"].iloc[start_i : end_i + 1].astype(float).values
    if len(closes) < 2:
        return "flat"
    net = (closes[-1] / closes[0] - 1.0) * 100.0
    path = float(np.sum(np.abs(np.diff(closes) / closes[:-1]))) * 100.0
    if abs(net) < 0.15 and path < 1.0:
        return "sideways / quiet"
    if net >= 1.0 and path < abs(net) * 1.8:
        return "smooth rally"
    if net <= -1.0 and path < abs(net) * 1.8:
        return "smooth selloff"
    if net > 0:
        return "choppy up"
    if net < 0:
        return "choppy down"
    return "choppy flat"


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: PatternAnalogueConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or PatternAnalogueConfig()
    pb = max(5, int(cfg.pattern_bars))
    fb = max(1, int(cfg.forward_bars))
    top_n = max(1, min(50, int(cfg.top_n)))
    min_sim = float(np.clip(cfg.min_similarity, 0.0, 1.0))
    step = max(1, int(cfg.step))

    out: dict[str, Any] = {
        "ticker": ticker,
        "timeframe": cfg.timeframe,
        "pattern_bars": pb,
        "forward_bars": fb,
        "matches": [],
        "outcome_summary": None,
        "template": None,
        "prediction": None,
        "take_trade": False,
        "error": None,
    }

    try:
        df = fetch_data_for_gap_scan(
            ticker,
            cfg.timeframe,
            market,
            groww_token=groww_token,
            exchange=exchange,
            limit=_fetch_limit(cfg),
        )
    except Exception as exc:
        out["error"] = f"Data fetch failed: {exc}"
        return out

    df = normalize_ohlcv(df)
    if df is None or df.empty:
        out["error"] = "No OHLCV data"
        return out

    # Prefer explicit date range when given; else keep last search_lookback_bars.
    if cfg.search_from_date or cfg.search_to_date:
        hist = _filter_search_range(df, cfg)
        # Always keep enough recent bars for the live template from full df.
        # Merge: historical search slice + latest bars from full df.
        recent = df.tail(pb + fb + 5)
        hist = pd.concat([hist, recent]).sort_index()
        hist = hist[~hist.index.duplicated(keep="last")]
        df = hist
    else:
        keep = int(cfg.search_lookback_bars) + pb + fb + 5
        if len(df) > keep:
            df = df.tail(keep)

    min_needed = pb + fb + 10
    if len(df) < min_needed:
        out["error"] = f"Need at least {min_needed} bars; got {len(df)}"
        return out

    closes = df["close"].astype(float).values
    n = len(closes)
    template_end = n - 1
    template_start = template_end - pb + 1
    template_vec = _shape_vector(closes[template_start : template_end + 1])
    if template_vec is None:
        out["error"] = "Could not build template shape"
        return out

    template_net = (closes[template_end] / closes[template_start] - 1.0) * 100.0
    out["template"] = {
        "start_time": _bar_time(df.index[template_start]),
        "end_time": _bar_time(df.index[template_end]),
        "bars": pb,
        "start_close": round(float(closes[template_start]), 6),
        "end_close": round(float(closes[template_end]), 6),
        "net_return_pct": round(float(template_net), 3),
        "shape_label": _template_label(df, template_start, template_end),
        "ltp": round(float(closes[template_end]), 6),
    }
    out["ltp"] = out["template"]["ltp"]

    # Search windows that end before the live template starts (no look-ahead / overlap).
    last_search_end = template_start - 1
    first_end = pb - 1
    if last_search_end - fb < first_end:
        out["error"] = "Not enough history before the current pattern window"
        return out

    scored: list[tuple[float, int]] = []
    for end_i in range(first_end, last_search_end + 1 - fb, step):
        # Require full forward path available after the analogue.
        if end_i + fb >= template_start:
            continue
        start_i = end_i - pb + 1
        vec = _shape_vector(closes[start_i : end_i + 1])
        if vec is None or len(vec) != len(template_vec):
            continue
        sim = _cosine_similarity(template_vec, vec)
        if sim >= min_sim:
            scored.append((sim, end_i))

    scored.sort(key=lambda x: x[0], reverse=True)

    # De-duplicate heavily overlapping matches (keep highest sim).
    picked: list[tuple[float, int]] = []
    used_ends: list[int] = []
    for sim, end_i in scored:
        if any(abs(end_i - u) < max(3, pb // 3) for u in used_ends):
            continue
        picked.append((sim, end_i))
        used_ends.append(end_i)
        if len(picked) >= top_n:
            break

    matches: list[dict[str, Any]] = []
    for rank, (sim, end_i) in enumerate(picked, start=1):
        start_i = end_i - pb + 1
        fwd = _forward_stats(df, end_i, fb)
        if not fwd:
            continue
        net = (closes[end_i] / closes[start_i] - 1.0) * 100.0
        matches.append({
            "rank": rank,
            "similarity": round(float(sim) * 100.0, 2),
            "match_start": _bar_time(df.index[start_i]),
            "match_end": _bar_time(df.index[end_i]),
            "match_net_return_pct": round(float(net), 3),
            "shape_label": _template_label(df, start_i, end_i),
            **fwd,
        })

    out["matches"] = matches
    out["search_stats"] = {
        "bars_available": n,
        "candidates_above_threshold": len(scored),
        "matches_returned": len(matches),
        "min_similarity_pct": round(min_sim * 100.0, 1),
        "search_from_date": cfg.search_from_date or None,
        "search_to_date": cfg.search_to_date or None,
        "search_lookback_bars": cfg.search_lookback_bars,
    }

    if not matches:
        out["prediction"] = {
            "bias": "WAIT",
            "confidence_pct": 0.0,
            "plain_english": (
                f"No historical windows ≥ {min_sim * 100:.0f}% similar to the last {pb} "
                f"{cfg.timeframe} bars in the chosen search range."
            ),
        }
        out["outcome_summary"] = {"samples": 0}
        return out

    next_rets = [float(m["next_bar_return_pct"]) for m in matches]
    fwd_rets = [float(m["forward_return_pct"]) for m in matches]
    up_next = sum(1 for r in next_rets if r > 0)
    up_fwd = sum(1 for r in fwd_rets if r > 0)
    avg_next = float(np.mean(next_rets))
    avg_fwd = float(np.mean(fwd_rets))
    med_fwd = float(np.median(fwd_rets))
    avg_sim = float(np.mean([float(m["similarity"]) for m in matches]))

    summary = {
        "samples": len(matches),
        "avg_similarity_pct": round(avg_sim, 2),
        "avg_next_bar_return_pct": round(avg_next, 3),
        "avg_forward_return_pct": round(avg_fwd, 3),
        "median_forward_return_pct": round(med_fwd, 3),
        "next_bar_up_pct": round(100.0 * up_next / len(matches), 1),
        "forward_up_pct": round(100.0 * up_fwd / len(matches), 1),
        "avg_max_favorable_pct": round(float(np.mean([m["max_favorable_pct"] for m in matches])), 3),
        "avg_max_adverse_pct": round(float(np.mean([m["max_adverse_pct"] for m in matches])), 3),
    }
    out["outcome_summary"] = summary

    # Bias from forward horizon; confidence from agreement × similarity.
    if avg_fwd > 0.05 and summary["forward_up_pct"] >= 55:
        bias = "BUY"
        side = "LONG"
    elif avg_fwd < -0.05 and summary["forward_up_pct"] <= 45:
        bias = "SELL"
        side = "SHORT"
    else:
        bias = "WAIT"
        side = "WAIT"

    agreement = abs(summary["forward_up_pct"] - 50.0) / 50.0
    conf = min(92.0, max(20.0, avg_sim * 0.55 + agreement * 40.0 + min(15.0, len(matches))))
    if bias == "WAIT":
        conf = min(conf, 48.0)

    out["prediction"] = {
        "bias": bias,
        "side": side,
        "confidence_pct": round(conf, 1),
        "horizon_bars": fb,
        "plain_english": (
            f"Current {pb}-bar {cfg.timeframe} shape ({out['template']['shape_label']}, "
            f"{out['template']['net_return_pct']:+.2f}%) matched {len(matches)} historical windows "
            f"(avg similarity {avg_sim:.1f}%). After those analogues, next bar avg "
            f"{avg_next:+.2f}% (up {summary['next_bar_up_pct']:.0f}%) and {fb}-bar forward avg "
            f"{avg_fwd:+.2f}% / median {med_fwd:+.2f}% (up {summary['forward_up_pct']:.0f}%). "
            f"Suggested bias: {bias}."
        ),
    }
    out["take_trade"] = bias in ("BUY", "SELL") and conf >= 55
    out["direction"] = side
    out["confidence_pct"] = round(conf, 1)
    out["signal"] = bias
    return out


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: PatternAnalogueConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
    max_workers: int = 6,
) -> dict[str, Any]:
    cfg = cfg or PatternAnalogueConfig()
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    def _one(t: str) -> dict[str, Any]:
        return analyze_ticker(t, market, cfg=cfg, groww_token=groww_token, exchange=exchange)

    workers = max(1, min(max_workers, len(tickers) or 1))
    if workers == 1 or len(tickers) <= 1:
        for t in tickers:
            row = _one(t)
            if row.get("error") and not row.get("matches"):
                errors.append({"ticker": t, "error": str(row["error"])})
            results.append(row)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(_one, t): t for t in tickers}
            for fut in as_completed(futs):
                t = futs[fut]
                try:
                    row = fut.result()
                except Exception as exc:
                    row = {"ticker": t, "error": str(exc), "matches": []}
                if row.get("error") and not row.get("matches"):
                    errors.append({"ticker": t, "error": str(row["error"])})
                results.append(row)

    results.sort(
        key=lambda r: (
            0 if r.get("take_trade") else 1,
            -(float(r.get("confidence_pct") or 0)),
            str(r.get("ticker") or ""),
        )
    )
    actionable = [r for r in results if r.get("take_trade")]
    return {
        "strategy": "Pattern Analogue — historical shape match → forward outcome",
        "timeframe": cfg.timeframe,
        "pattern_bars": cfg.pattern_bars,
        "forward_bars": cfg.forward_bars,
        "config": {
            "pattern_bars": cfg.pattern_bars,
            "forward_bars": cfg.forward_bars,
            "search_lookback_bars": cfg.search_lookback_bars,
            "search_from_date": cfg.search_from_date or None,
            "search_to_date": cfg.search_to_date or None,
            "top_n": cfg.top_n,
            "min_similarity": cfg.min_similarity,
        },
        "scanned": len(tickers),
        "entry_count": len(actionable),
        "results": results,
        "errors": errors,
        "disclaimer": "Research / education only — not financial advice. Past analogues do not guarantee future results.",
    }


def build_pattern_analogue_ai_prompt(row: dict[str, Any]) -> str:
    pred = row.get("prediction") or {}
    summary = row.get("outcome_summary") or {}
    lines = [
        f"Ticker: {row.get('ticker')}",
        f"TF: {row.get('timeframe')} · pattern_bars={row.get('pattern_bars')} · forward_bars={row.get('forward_bars')}",
        f"Template: {row.get('template')}",
        f"Prediction: {pred}",
        f"Outcome summary: {summary}",
        f"Top matches: {(row.get('matches') or [])[:5]}",
    ]
    return "\n".join(str(x) for x in lines)
