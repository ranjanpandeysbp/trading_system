"""
elliott_wave_engine.py
-----------------------
Elliott Wave analyzer — algorithmic 5-wave impulse / ABC corrective detection
via a ZigZag pivot filter, wrapped in this app's standard Pro Trade
scan_universe/analyze_ticker shape so it can be charted (candle or line)
with wave connector lines, labels, and Fibonacci-projected targets.

Wave-count detection itself lives in price_action.py (analyze_elliott_waves) —
this module is the fetch/chart-data/scan wiring around that pure function,
matching the pattern of the other Pro Trade engines in this package.

Research / education only — not financial advice. Elliott Wave labels are
algorithmic estimates, not certified wave counts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.price_action import analyze_elliott_waves

logger = logging.getLogger(__name__)

STRATEGY_NAME = "Elliott Wave"


@dataclass
class ElliottWaveConfig:
    timeframe: str = "1d"
    lookback_bars: int = 250
    zigzag_pct: float = 3.0
    min_bars: int = 30
    start_date: str = ""  # optional "YYYY-MM-DD" — crops the fetched history to this window
    end_date: str = ""  # optional "YYYY-MM-DD"


def _build_chart_data(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    return [
        {
            "time": str(idx),
            "open": round(float(bar["open"]), 6),
            "high": round(float(bar["high"]), 6),
            "low": round(float(bar["low"]), 6),
            "close": round(float(bar["close"]), 6),
            "volume": round(float(bar["volume"]), 2) if "volume" in bar and pd.notna(bar["volume"]) else None,
        }
        for idx, bar in df.iterrows()
    ]


def _enrich_waves_with_time(waves: list[dict[str, Any]], df: pd.DataFrame) -> list[dict[str, Any]]:
    """Attach the actual bar time for each wave's start/end index so the
    frontend can plot connector lines without re-deriving index lookups."""
    n = len(df)
    out = []
    for w in waves:
        si = min(int(w["start_idx"]), n - 1)
        ei = min(int(w["end_idx"]), n - 1)
        out.append({
            **w,
            "start_time": str(df.index[si]),
            "end_time": str(df.index[ei]),
        })
    return out


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: ElliottWaveConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or ElliottWaveConfig()
    out: dict[str, Any] = {
        "ticker": ticker,
        "strategy": STRATEGY_NAME,
        "error": None,
        "pattern": "NONE",
        "current_wave": 0,
        "waves": [],
        "wave_targets": {},
        "valid_impulse": False,
        "notes": "",
        "chart_data": [],
        "take_trade": False,
        "verdict": "NO PATTERN",
        "rules": [
            "ZigZag filter marks significant swing pivots at the configured sensitivity %.",
            "5-wave impulse: Wave 3 cannot be shortest, Wave 2 cannot retrace below Wave 1 start, "
            "Wave 4 cannot overlap Wave 1 territory.",
            "ABC corrective: B must not retrace beyond A's start.",
            "After a valid 5-wave impulse, Fibonacci-projected ABC correction targets are shown "
            "(38.2% / 50% / 61.8% retracement of the impulse range).",
        ],
    }

    try:
        df = fetch_data_for_gap_scan(
            ticker,
            cfg.timeframe,
            market,
            groww_token=groww_token,
            exchange=exchange,
            limit=cfg.lookback_bars,
        )
    except Exception as exc:
        out["error"] = f"Data fetch failed: {exc}"
        return out

    df = normalize_ohlcv(df)
    if df is None or df.empty:
        out["error"] = "Insufficient OHLCV for Elliott Wave analysis"
        return out

    if cfg.start_date or cfg.end_date:
        full_start = df.index.min()
        full_end = df.index.max()
        df = df.loc[(cfg.start_date or None):(cfg.end_date or None)]
        if df.empty or len(df) < cfg.min_bars:
            out["error"] = (
                f"Only {len(df)} bars in {cfg.start_date or '…'} → {cfg.end_date or '…'} "
                f"(need ≥{cfg.min_bars}). Fetched history covers {full_start} → {full_end} — "
                "widen the date range or increase Candle History."
            )
            return out

    if len(df) < cfg.min_bars:
        out["error"] = "Insufficient OHLCV for Elliott Wave analysis"
        return out

    ew = analyze_elliott_waves(df, zigzag_pct=cfg.zigzag_pct)
    out["ltp"] = round(float(df["close"].iloc[-1]), 6)
    out["bars"] = len(df)
    out["chart_data"] = _build_chart_data(df)
    out["pattern"] = ew.get("pattern", "NONE")
    out["current_wave"] = ew.get("current_wave", 0)
    out["waves"] = _enrich_waves_with_time(ew.get("waves") or [], df)
    out["wave_targets"] = ew.get("wave_targets") or {}
    out["valid_impulse"] = bool(ew.get("valid_impulse"))
    out["notes"] = ew.get("notes") or ""

    if out["pattern"] == "IMPULSE" and out["valid_impulse"]:
        last_wave = out["waves"][-1] if out["waves"] else None
        direction = last_wave.get("direction") if last_wave else None
        out["take_trade"] = True
        out["direction"] = "SHORT" if direction == "UP" else "LONG"
        out["verdict"] = f"Wave {out['current_wave']} complete — expect ABC correction ({out['direction']})"
    elif out["pattern"] == "CORRECTIVE":
        last_wave = out["waves"][-1] if out["waves"] else None
        direction = last_wave.get("direction") if last_wave else None
        out["take_trade"] = bool(out["waves"]) and str(out.get("current_wave")) == "C"
        out["direction"] = "LONG" if direction == "DOWN" else "SHORT"
        out["verdict"] = (
            f"Wave C complete — correction likely done, expect resumption ({out['direction']})"
            if out["take_trade"]
            else f"Corrective ABC in progress (currently Wave {out['current_wave']})"
        )
    elif out["pattern"] == "INCOMPLETE":
        out["verdict"] = f"{len(out['waves'])} pivot legs — no valid impulse/corrective count yet"
    else:
        out["verdict"] = "No pattern"

    out["plain_english"] = _explain(out)
    return out


def _explain(out: dict[str, Any]) -> str:
    pattern = out["pattern"]
    notes = out.get("notes") or ""
    if pattern == "IMPULSE" and out["valid_impulse"]:
        targets = out.get("wave_targets") or {}
        tgt_note = ""
        if targets:
            parts = ", ".join(f"{k} {v:g}" for k, v in targets.items())
            tgt_note = f" Watch the Fibonacci ABC retracement zone for the correction: {parts}."
        return (
            f"A valid 5-wave impulse completed, currently at Wave {out['current_wave']}. {notes} "
            f"TRADE CASE: the impulse is exhausted — favor {out.get('direction', '—')} for the corrective ABC leg, "
            "not a continuation of the same direction." + tgt_note
        )
    if pattern == "CORRECTIVE":
        if out["take_trade"]:
            return (
                f"Wave C of the ABC correction has completed. {notes} "
                f"TRADE CASE: the correction looks done — favor {out.get('direction', '—')} for resumption of the "
                "prior trend, with a stop beyond the Wave C extreme."
            )
        return (
            f"An ABC corrective sequence is in progress (currently Wave {out['current_wave']}). {notes} "
            "TRADE CASE: wait — the correction hasn't finished, entries here risk being caught in the middle of it."
        )
    if pattern == "INCOMPLETE":
        return (
            f"{notes} TRADE CASE: nothing tradable yet — the pivot structure doesn't clear this strategy's "
            "impulse or corrective validation rules. Wait for a cleaner count, or loosen ZigZag sensitivity."
        )
    return f"{notes or 'No swing pivots detected at this ZigZag sensitivity.'} TRADE CASE: nothing to trade."


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: ElliottWaveConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or ElliottWaveConfig()
    results: list[dict[str, Any]] = []
    for t in tickers:
        try:
            results.append(analyze_ticker(t, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            logger.exception("Elliott Wave failed for %s", t)
            results.append({"ticker": t, "error": str(exc)[:300], "take_trade": False, "waves": []})

    entries = [r for r in results if not r.get("error") and r.get("take_trade")]

    return {
        "strategy": STRATEGY_NAME,
        "results": results,
        "entries": entries,
        "entry_count": len(entries),
        "scanned": len(results),
        "config": {
            "timeframe": cfg.timeframe,
            "lookback_bars": cfg.lookback_bars,
            "zigzag_pct": cfg.zigzag_pct,
        },
        "disclaimer": (
            "Elliott Wave labels are algorithmic estimates, not certified wave counts. "
            "Research / education only — not financial advice."
        ),
    }
