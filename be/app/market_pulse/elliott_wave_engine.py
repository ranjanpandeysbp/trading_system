"""
elliott_wave_engine.py
-----------------------
Elliott Wave analyzer — algorithmic 5-wave impulse / ABC corrective detection
via a ZigZag pivot filter, wrapped in this app's standard Pro Trade
scan_universe/analyze_ticker shape so it can be charted (candle or line)
with wave connector lines, labels, and Fibonacci-projected targets.

Wave-count detection itself lives in price_action.py (analyze_elliott_waves) —
this module is the fetch/chart-data/scan wiring around that pure function,
plus a trade-plan layer (signal/confidence/SL/TP) built the same way as the
other Pro Trade engines (pro_trade_shared.ConfidenceScore + sl_tp_pct), so
Elliott Wave results carry the same institutional-grade shape instead of a
bare pattern label.

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
from app.market_pulse.pro_trade_shared import (
    ConfidenceScore,
    atr as _atr_ind,
    build_pro_trade_ai_context,
    pro_trade_ai_system,
    rr_ratio,
    sl_tp_pct,
)

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
    sl_atr_mult: float = 0.5  # stop buffer beyond the signal wave's extreme, in ATR
    min_rr: float = 1.3  # reward:risk floor used as a confidence factor


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


def _build_trade_plan(out: dict[str, Any], df: pd.DataFrame, cfg: ElliottWaveConfig) -> None:
    """Attach entry/stop/target/sl_pct/tp_pct/confidence_pct/signal to `out`
    for a take_trade result — same ConfidenceScore + sl_tp_pct machinery the
    rest of Pro Trade uses, so a wave count turns into an actual risk-managed
    plan instead of just a pattern label."""
    waves = out["waves"]
    signal_wave = waves[-1]
    entry = out["ltp"]
    direction = out["direction"]
    is_long = direction == "LONG"

    atr_series = _atr_ind(df, 14)
    atr_val = float(atr_series.iloc[-1]) if pd.notna(atr_series.iloc[-1]) else entry * 0.01
    buffer = atr_val * cfg.sl_atr_mult
    extreme = float(signal_wave["end_price"])
    stop = extreme - buffer if is_long else extreme + buffer

    targets = out["wave_targets"]
    if out["pattern"] == "IMPULSE":
        # Nearest Fibonacci retracement (38.2%) — the most likely level to be
        # tagged first, used as the primary target rather than a stretch goal.
        target = targets.get("ABC 38.2%")
    else:
        target = targets.get("Reversal target")

    sl_pct, tp_pct = sl_tp_pct(direction, entry, stop, target)
    rr = rr_ratio(sl_pct, tp_pct)

    n = len(df)
    bars_since_signal = (n - 1) - int(signal_wave["end_idx"])
    is_fresh = bars_since_signal <= max(3, round(n * 0.08))

    if out["pattern"] == "IMPULSE":
        w1_len = abs(waves[0]["end_price"] - waves[0]["start_price"])
        w3_len = abs(waves[2]["end_price"] - waves[2]["start_price"])
        w5_len = abs(waves[4]["end_price"] - waves[4]["start_price"])
        wave3_extended = w3_len > 1.3 * max(w1_len, w5_len)
        score = ConfidenceScore(45, "Strictly valid 5-wave impulse (Elliott's overlap/shortest-wave rules satisfied)")
        score.add(
            wave3_extended, 10,
            "Wave 3 is clearly extended vs Waves 1 & 5 — a textbook-strength impulse",
            "Wave 3 isn't strongly extended — a weaker, less textbook impulse",
        )
    else:
        w_a = waves[0]
        w_b = waves[1]
        a_len = abs(w_a["end_price"] - w_a["start_price"])
        b_retrace = abs(w_b["end_price"] - w_b["start_price"]) / a_len if a_len else 0
        clean_b = 0.35 <= b_retrace <= 0.85
        score = ConfidenceScore(45, "Valid 3-leg ABC correction (B didn't retrace beyond A's start)")
        score.add(
            clean_b, 8,
            "Wave B retraced a normal 35-85% of Wave A — a clean correction",
            "Wave B's retracement of Wave A is unusually shallow or deep — a messier correction",
        )

    score.add(
        is_fresh, 10,
        f"Signal wave completed only {bars_since_signal} bar(s) ago — fresh, still actionable",
        f"Signal wave completed {bars_since_signal} bars ago — getting stale",
    )
    score.add(
        rr is not None and rr >= cfg.min_rr, 12,
        f"Reward:risk clears the {cfg.min_rr:g}:1 floor",
        "Reward:risk is thin for this setup",
    )
    confidence_pct, reasons = score.finalize()

    out["entry_price"] = round(entry, 6)
    out["stop_price"] = round(stop, 6)
    out["target_price"] = round(target, 6) if target is not None else None
    out["sl_pct"] = sl_pct
    out["tp_pct"] = tp_pct
    out["rr"] = rr
    out["confidence_pct"] = confidence_pct
    out["confidence_reasons"] = reasons


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
        "signal": "NEUTRAL",
        "verdict": "NO PATTERN",
        "confidence_pct": None,
        "sl_pct": None,
        "tp_pct": None,
        "rules": [
            "ZigZag filter marks significant swing pivots at the configured sensitivity %.",
            "5-wave impulse: Wave 3 cannot be shortest, Wave 2 cannot retrace below Wave 1 start, "
            "Wave 4 cannot overlap Wave 1 territory.",
            "ABC corrective: B must not retrace beyond A's start.",
            "After a valid 5-wave impulse, Fibonacci-projected ABC correction targets are shown "
            "(38.2% / 50% / 61.8% retracement of the impulse range).",
            "A trade plan (signal, confidence%, SL%, TP%) is only produced once a pattern is fully "
            "complete — Wave 5 for an impulse, Wave C for a correction.",
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
        out["signal"] = "BEARISH" if out["direction"] == "SHORT" else "BULLISH"
        out["verdict"] = f"Wave {out['current_wave']} complete — expect ABC correction ({out['direction']})"
        _build_trade_plan(out, df, cfg)
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
        if out["take_trade"]:
            out["signal"] = "BULLISH" if out["direction"] == "LONG" else "BEARISH"
            _build_trade_plan(out, df, cfg)
    elif out["pattern"] == "INCOMPLETE":
        out["verdict"] = f"{len(out['waves'])} pivot legs — no valid impulse/corrective count yet"
    else:
        out["verdict"] = "No pattern"

    out["plain_english"] = _explain(out)
    return out


def _explain(out: dict[str, Any]) -> str:
    pattern = out["pattern"]
    signal = out.get("signal", "NEUTRAL")

    def _plan_line() -> str:
        parts = [f"SIGNAL: {signal}" + (f" ({out['direction']})" if out.get("direction") else "")]
        conf = out.get("confidence_pct")
        sl, tp, rr = out.get("sl_pct"), out.get("tp_pct"), out.get("rr")
        if conf is not None:
            parts.append(f"confidence {conf:.0f}%")
        if sl is not None and tp is not None:
            rr_note = f" (reward:risk 1:{rr:g})" if rr else ""
            parts.append(f"SL {sl:.1f}% · TP {tp:.1f}%{rr_note}")
        return " — ".join(parts)

    if pattern == "IMPULSE" and out["valid_impulse"]:
        targets = out.get("wave_targets") or {}
        tgt_note = ""
        if targets:
            parts = ", ".join(f"{k} ₹{v:g}" for k, v in targets.items())
            tgt_note = f" Watch for the pullback to reach one of these Fibonacci zones: {parts}."
        return (
            f"{_plan_line()}. A clean 5-wave impulse ({out['current_wave']} legs) just completed — the trending "
            "move looks exhausted, so the next leg is expected to correct AGAINST it, not extend further in the "
            f"same direction. That is why the trade case is {signal}, the opposite of the impulse's own direction."
            + tgt_note
        )
    if pattern == "CORRECTIVE":
        if out["take_trade"]:
            return (
                f"{_plan_line()}. Price just finished a 3-leg corrective bounce (A-B-C) inside a larger trend — "
                "that bounce has topped out at Wave C, so it is considered done. The original trend is expected "
                f"to resume from here, which is why the trade case is {signal}: stop placed just beyond the Wave C "
                "extreme, target back near where the correction began."
            )
        return (
            f"SIGNAL: NEUTRAL. A 3-leg corrective bounce is still forming (currently Wave {out['current_wave']} "
            "of A-B-C) — it has not finished yet, so there is no trade case here. Entering now risks getting "
            "caught mid-correction; wait for Wave C to complete."
        )
    if pattern == "INCOMPLETE":
        return (
            f"SIGNAL: NEUTRAL. {len(out['waves'])} swing legs found but none form a valid 5-wave impulse or "
            "3-leg ABC correction under this strategy's strict rules. Nothing tradable — wait for a cleaner "
            "count, or loosen ZigZag sensitivity to catch smaller swings."
        )
    return "SIGNAL: NEUTRAL. No meaningful swing pivots detected at this ZigZag sensitivity — nothing to trade."


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
    entries.sort(key=lambda r: -(r.get("confidence_pct") or 0))

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


ELLIOTT_WAVE_AI_SYSTEM = pro_trade_ai_system(
    "Elliott Wave",
    "Algorithmic zigzag-based wave count (impulse waves 1-5 or corrective A-B-C) — a trade only fires "
    "on specific, well-defined wave positions (e.g. wave C of a correction, expecting reversal). Wave "
    "labels are automated estimates, not certified Elliott Wave analysis, so treat the count itself as "
    "one input among several, not gospel.",
)


def build_elliott_wave_ai_prompt(result: dict[str, Any]) -> str:
    extra: list[str] = []
    waves = result.get("waves")
    if isinstance(waves, list) and waves:
        extra.append(f"Wave count: {len(waves)} waves identified, current wave = {result.get('current_wave')}")
    return build_pro_trade_ai_context(result, engine_label="Elliott Wave", extra_lines=extra or None)
