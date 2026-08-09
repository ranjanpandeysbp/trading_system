"""
simple_effective_engine.py
--------------------------
Simple Effective — price action + MA band + MACD (high-accuracy, multi-asset / multi-TF).

Setup (from the video methodology):
  1. Two MAs form a band/channel + MACD.
  2. Signal candle must cross and *fully close* outside the MA band.
  3. Entry only when the next price action breaks the signal candle’s High (buy)
     or Low (sell).
  4. Stop-loss at the *opposite* edge of the MA band.
  5. Book at 1:1 or 1:1.5 RRR (optional trail toward 1:3).
  6. MACD must show a matching crossover — otherwise invalid.
  7. Avoid Sell when Open == Low (gap-down / open=low trap).
  8. Critical: MACD crossover must occur *inside* the histogram zone —
     Buy cross with green (hist > 0) histogram; Sell cross with red (hist < 0).

Research / education only — not financial advice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any

import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.pro_trade_shared import (
    ConfidenceScore,
    build_pro_trade_ai_context,
    ema as _ema,
    pro_trade_ai_system,
    sl_tp_pct,
)
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.smart_money_shared import hold_for_tf

logger = logging.getLogger(__name__)

STRATEGY_ID = "simple_effective"
STRATEGY_NAME = "Simple Effective"

HOW_IT_WORKS = """
### How Simple Effective works

A straightforward, high-accuracy setup: **price action + MA band + MACD**.

| Step | Rule |
|------|------|
| 1 | Plot **two MAs** as a band/channel + **MACD** |
| 2 | Signal candle must **close fully outside** the band |
| 3 | Enter only when price **breaks the signal High (Buy)** or **Low (Sell)** |
| 4 | **Stop** = opposite edge of the MA band |
| 5 | Target **1:1 or 1:1.5** RRR (trail toward 1:3 only if momentum continues) |
| 6 | **MACD crossover** must agree — no cross = no trade |
| 7 | **Avoid Sell** if Open = Low (especially gap-down traps) |
| 8 | **Key filter:** MACD cross must sit **inside the histogram zone** — Buy in **green** hist, Sell in **red** hist |

**How to use this screen**
1. Pick asset class + timeframe (works on 1m · 15m · higher TFs) and tickers.
2. Scan — look for BUY/SELL or SETUP (waiting for high/low break).
3. Confirm MACD cross is inside the correct histogram colour before acting.
4. Place SL on the far side of the band; take profit at your chosen RRR.

Versatile across Stocks, Indices, Forex, Crypto, Commodities. Research only — not advice.
""".strip()

RULES = [
    "Two MAs form a band; MACD confirms.",
    "Signal candle closes fully outside the band.",
    "Enter on break of signal High (Buy) or Low (Sell).",
    "SL at opposite MA-band edge; TP at 1:1 or 1:1.5 RRR.",
    "MACD crossover required; must occur inside green hist (Buy) or red hist (Sell).",
    "Skip Sell setups where Open == Low on the signal candle.",
]

SIMPLE_EFFECTIVE_AI_SYSTEM = pro_trade_ai_system(
    "Simple Effective",
    "MA-band close-outside + trigger break of signal high/low + MACD crossover "
    "inside matching histogram zone; SL opposite band edge; TP 1:1–1:1.5 RRR. "
    "Avoid Open=Low sell traps.",
)


@dataclass
class SimpleEffectiveConfig:
    timeframe: str = "15m"
    lookback_bars: int = 300
    ma_fast: int = 9
    ma_slow: int = 21
    use_ema: bool = True
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    rr_multiple: float = 1.5  # 1.0 or 1.5 recommended
    signal_lookback: int = 8  # search recent bars for signal+trigger
    open_low_eps_pct: float = 0.02  # treat open≈low within this % as trap
    min_bars: int = 80
    chart_bars: int = 120
    take_confidence_threshold: float = 58.0


def _r(x: float, n: int = 6) -> float:
    return round(float(x), n)


def _macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    line = _ema(close, fast) - _ema(close, slow)
    sig = line.ewm(span=signal, adjust=False).mean()
    hist = line - sig
    return line, sig, hist


def _band_edges(ma_a: float, ma_b: float) -> tuple[float, float]:
    return (min(ma_a, ma_b), max(ma_a, ma_b))


def _build_chart(work: pd.DataFrame, *, max_bars: int) -> list[dict[str, Any]]:
    if work is None or work.empty:
        return []
    has_vol = "volume" in work.columns
    tail = work.iloc[-max_bars:]
    rows: list[dict[str, Any]] = []
    for idx, bar in tail.iterrows():
        row: dict[str, Any] = {
            "time": str(idx),
            "open": _r(float(bar["open"])),
            "high": _r(float(bar["high"])),
            "low": _r(float(bar["low"])),
            "close": _r(float(bar["close"])),
            "volume": _r(float(bar["volume"]), 2) if has_vol and pd.notna(bar.get("volume")) else None,
        }
        for k in ("ma_fast", "ma_slow", "macd", "macd_signal", "macd_hist"):
            if k in bar and pd.notna(bar.get(k)):
                row[k] = _r(float(bar[k]), 6)
        rows.append(row)
    return rows


def _scan_setups(work: pd.DataFrame, cfg: SimpleEffectiveConfig) -> dict[str, Any] | None:
    """Find most recent valid signal (+ optional trigger) in the lookback window."""
    n = len(work)
    if n < 5:
        return None

    start = max(2, n - cfg.signal_lookback - 1)
    best: dict[str, Any] | None = None

    for i in range(start, n - 1):  # signal at i, trigger can be i+1..n-1
        row = work.iloc[i]
        prev = work.iloc[i - 1]
        o, h, low, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        mf, ms = float(row["ma_fast"]), float(row["ma_slow"])
        band_lo, band_hi = _band_edges(mf, ms)
        macd, macds, hist = float(row["macd"]), float(row["macd_signal"]), float(row["macd_hist"])
        p_macd, p_macds = float(prev["macd"]), float(prev["macd_signal"])

        close_above = c > band_hi
        close_below = c < band_lo
        if not close_above and not close_below:
            continue

        bull_cross = p_macd <= p_macds and macd > macds
        bear_cross = p_macd >= p_macds and macd < macds

        direction = None
        if close_above and bull_cross and hist > 0:
            direction = "LONG"
        elif close_below and bear_cross and hist < 0:
            # Open=Low sell trap
            mid = (h + low) / 2.0 if h > low else c
            eps = abs(mid) * (cfg.open_low_eps_pct / 100.0)
            if abs(o - low) <= max(eps, 1e-8):
                continue  # trap — skip
            direction = "SHORT"
        else:
            continue

        # Trigger: later bar breaks signal high/low
        triggered = False
        trigger_i = None
        trigger_price = None
        for j in range(i + 1, n):
            bar_j = work.iloc[j]
            if direction == "LONG" and float(bar_j["high"]) > h:
                triggered = True
                trigger_i = j
                trigger_price = h
                break
            if direction == "SHORT" and float(bar_j["low"]) < low:
                triggered = True
                trigger_i = j
                trigger_price = low
                break

        waiting = (not triggered) and (i == n - 2 or i >= n - 3)

        setup = {
            "direction": direction,
            "signal_i": i,
            "signal_time": str(work.index[i]),
            "signal_ohlc": {"open": _r(o), "high": _r(h), "low": _r(low), "close": _r(c)},
            "band_lo": _r(band_lo),
            "band_hi": _r(band_hi),
            "ma_fast": _r(mf),
            "ma_slow": _r(ms),
            "macd": _r(macd, 6),
            "macd_signal": _r(macds, 6),
            "macd_hist": _r(hist, 6),
            "hist_zone": "green" if hist > 0 else "red" if hist < 0 else "flat",
            "triggered": triggered,
            "waiting_trigger": waiting and not triggered,
            "trigger_i": trigger_i,
            "trigger_time": str(work.index[trigger_i]) if trigger_i is not None else None,
            "entry_level": _r(trigger_price) if trigger_price is not None else (_r(h) if direction == "LONG" else _r(low)),
            "freshness": n - 1 - i,
        }
        # Prefer triggered recent, else waiting
        if best is None:
            best = setup
        else:
            score_new = (2 if triggered else 1) * 100 - setup["freshness"]
            score_old = (2 if best["triggered"] else 1) * 100 - best["freshness"]
            if score_new >= score_old:
                best = setup

    # Also allow signal on last bar (forming — wait for next bar trigger)
    i = n - 1
    if i >= 1:
        row = work.iloc[i]
        prev = work.iloc[i - 1]
        o, h, low, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        mf, ms = float(row["ma_fast"]), float(row["ma_slow"])
        band_lo, band_hi = _band_edges(mf, ms)
        macd, macds, hist = float(row["macd"]), float(row["macd_signal"]), float(row["macd_hist"])
        p_macd, p_macds = float(prev["macd"]), float(prev["macd_signal"])
        close_above = c > band_hi
        close_below = c < band_lo
        bull_cross = p_macd <= p_macds and macd > macds
        bear_cross = p_macd >= p_macds and macd < macds
        direction = None
        if close_above and bull_cross and hist > 0:
            direction = "LONG"
        elif close_below and bear_cross and hist < 0:
            mid = (h + low) / 2.0 if h > low else c
            eps = abs(mid) * (cfg.open_low_eps_pct / 100.0)
            if abs(o - low) > max(eps, 1e-8):
                direction = "SHORT"
        if direction:
            setup = {
                "direction": direction,
                "signal_i": i,
                "signal_time": str(work.index[i]),
                "signal_ohlc": {"open": _r(o), "high": _r(h), "low": _r(low), "close": _r(c)},
                "band_lo": _r(band_lo),
                "band_hi": _r(band_hi),
                "ma_fast": _r(mf),
                "ma_slow": _r(ms),
                "macd": _r(macd, 6),
                "macd_signal": _r(macds, 6),
                "macd_hist": _r(hist, 6),
                "hist_zone": "green" if hist > 0 else "red" if hist < 0 else "flat",
                "triggered": False,
                "waiting_trigger": True,
                "trigger_i": None,
                "trigger_time": None,
                "entry_level": _r(h) if direction == "LONG" else _r(low),
                "freshness": 0,
            }
            if best is None or (not best["triggered"] and setup["freshness"] <= best["freshness"]):
                best = setup

    return best


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: SimpleEffectiveConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or SimpleEffectiveConfig()
    tf = (cfg.timeframe or "15m").strip() or "15m"
    out: dict[str, Any] = {
        "ticker": ticker,
        "strategy": STRATEGY_ID,
        "strategy_label": STRATEGY_NAME,
        "error": None,
        "take_trade": False,
        "signal": "WAIT",
        "direction": "NONE",
        "verdict": "No Simple Effective setup yet",
        "confidence_pct": None,
        "chart_data": [],
        "how_it_works": HOW_IT_WORKS,
        "rules": RULES,
    }

    try:
        df = fetch_data_for_gap_scan(
            ticker, tf, market, groww_token=groww_token, exchange=exchange, limit=cfg.lookback_bars,
        )
    except Exception as exc:
        out["error"] = f"Data fetch failed: {exc}"
        return out

    df = normalize_ohlcv(df)
    need = max(cfg.min_bars, cfg.macd_slow + cfg.macd_signal + 5, cfg.ma_slow + 5)
    if df is None or df.empty or len(df) < need:
        out["error"] = f"Insufficient {tf} data (need ≥{need} bars)."
        return out

    work = df.copy()
    if cfg.use_ema:
        work["ma_fast"] = _ema(work["close"], cfg.ma_fast)
        work["ma_slow"] = _ema(work["close"], cfg.ma_slow)
    else:
        work["ma_fast"] = work["close"].rolling(cfg.ma_fast, min_periods=cfg.ma_fast).mean()
        work["ma_slow"] = work["close"].rolling(cfg.ma_slow, min_periods=cfg.ma_slow).mean()
    macd, macds, hist = _macd(work["close"], cfg.macd_fast, cfg.macd_slow, cfg.macd_signal)
    work["macd"], work["macd_signal"], work["macd_hist"] = macd, macds, hist
    work = work.dropna(subset=["ma_fast", "ma_slow", "macd", "macd_signal", "macd_hist"])
    if len(work) < 10:
        out["error"] = "Not enough bars after indicator warm-up."
        return out

    setup = _scan_setups(work, cfg)
    last = work.iloc[-1]
    close = float(last["close"])
    mf, ms = float(last["ma_fast"]), float(last["ma_slow"])
    band_lo, band_hi = _band_edges(mf, ms)

    score = ConfidenceScore(32.0, "Simple Effective base")
    checks: list[dict[str, Any]] = []

    if not setup:
        checks.append({
            "id": "outside_close",
            "label": "Close outside MA band + MACD hist-zone cross",
            "pass": False,
            "detail": "No recent signal candle with valid MACD-in-histogram crossover",
        })
        confidence, score_reasons = score.finalize()
        out.update({
            "timeframe": tf,
            "ltp": _r(close),
            "bars": len(work),
            "status": "NO_SETUP",
            "signal": "WAIT",
            "direction": "NONE",
            "take_trade": False,
            "confidence_pct": confidence,
            "verdict": "No Simple Effective signal — wait for a full close outside the MA band with MACD cross inside the matching histogram zone.",
            "plain_english": "No setup. Need close outside the MA band + MACD crossover in the green (Buy) or red (Sell) histogram.",
            "checks": checks,
            "reasons": [f"✗ {c['label']} — {c['detail']}" for c in checks],
            "metrics": {
                "ma_fast": _r(mf),
                "ma_slow": _r(ms),
                "band_lo": _r(band_lo),
                "band_hi": _r(band_hi),
                "macd": _r(float(last["macd"]), 6),
                "macd_signal": _r(float(last["macd_signal"]), 6),
                "macd_hist": _r(float(last["macd_hist"]), 6),
                "rr_multiple": cfg.rr_multiple,
            },
            "chart_data": _build_chart(work, max_bars=cfg.chart_bars),
            "chart_series": [
                {"key": "ma_fast", "label": f"{'EMA' if cfg.use_ema else 'SMA'}{cfg.ma_fast}", "color": "#38bdf8"},
                {"key": "ma_slow", "label": f"{'EMA' if cfg.use_ema else 'SMA'}{cfg.ma_slow}", "color": "#fb923c"},
            ],
            "chart_levels": [
                {"label": "Band lo", "price": _r(band_lo), "color": "#94a3b8"},
                {"label": "Band hi", "price": _r(band_hi), "color": "#94a3b8"},
            ],
            "score_breakdown": {"total": confidence, "reasons": score_reasons[:8]},
        })
        return out

    direction = setup["direction"]
    band_lo_s, band_hi_s = float(setup["band_lo"]), float(setup["band_hi"])
    entry = float(setup["entry_level"])
    # SL at opposite end of band
    if direction == "LONG":
        stop = band_lo_s
        risk = entry - stop
        target = entry + risk * cfg.rr_multiple if risk > 0 else entry * 1.01
        signal_name = "BULLISH"
    else:
        stop = band_hi_s
        risk = stop - entry
        target = entry - risk * cfg.rr_multiple if risk > 0 else entry * 0.99
        signal_name = "BEARISH"

    checks = [
        {
            "id": "outside_close",
            "label": "Close fully outside MA band",
            "pass": True,
            "detail": f"Signal close outside band [{band_lo_s:.4g}–{band_hi_s:.4g}]",
            "weight": 16,
        },
        {
            "id": "macd_cross",
            "label": "MACD crossover",
            "pass": True,
            "detail": f"MACD {_r(setup['macd'], 5)} vs signal {_r(setup['macd_signal'], 5)}",
            "weight": 16,
        },
        {
            "id": "hist_zone",
            "label": f"Cross inside {setup['hist_zone']} histogram",
            "pass": True,
            "detail": f"Histogram {_r(setup['macd_hist'], 5)} ({setup['hist_zone']})",
            "weight": 18,
        },
        {
            "id": "trigger",
            "label": "Break of signal High/Low",
            "pass": bool(setup["triggered"]),
            "detail": (
                f"Triggered @ {_r(entry)} ({setup.get('trigger_time')})"
                if setup["triggered"]
                else f"Wait for break of {'High' if direction == 'LONG' else 'Low'} {_r(entry)}"
            ),
            "weight": 14,
        },
        {
            "id": "sell_trap",
            "label": "No Open=Low sell trap",
            "pass": True,
            "detail": "Sell trap filter passed / N/A for buys",
            "weight": 8,
        },
    ]
    for ch in checks:
        score.add(bool(ch["pass"]), float(ch.get("weight", 10)), f"{ch['label']}: {ch['detail']}")

    if setup["triggered"]:
        score.add(True, 8.0, "Entry trigger confirmed")
    if abs(cfg.rr_multiple - 1.5) < 0.01 or abs(cfg.rr_multiple - 1.0) < 0.01:
        score.add(True, 4.0, f"Realistic RRR {cfg.rr_multiple:.1f}:1")

    confidence, score_reasons = score.finalize()
    take = bool(setup["triggered"]) and confidence >= cfg.take_confidence_threshold
    waiting = bool(setup.get("waiting_trigger")) and not setup["triggered"]

    if take:
        status = "BUY" if direction == "LONG" else "SELL"
        verdict = (
            f"Simple Effective {status} — close outside MA band, MACD cross in {setup['hist_zone']} hist, "
            f"and signal {'High' if direction == 'LONG' else 'Low'} broken. "
            f"SL opposite band edge · TP at {cfg.rr_multiple:.1f}:1 RRR."
        )
    elif waiting:
        status = "SETUP_WAIT_TRIGGER"
        signal_name = "WATCH"
        verdict = (
            f"Setup ready ({'Buy' if direction == 'LONG' else 'Sell'}) — MACD OK in {setup['hist_zone']} hist. "
            f"Enter only if price breaks signal {'High' if direction == 'LONG' else 'Low'} {_r(entry)}."
        )
    else:
        status = "SETUP_STALE"
        signal_name = "WAIT"
        take = False
        verdict = "Older band+MACD signal without a clean recent trigger — wait for a fresh close outside the band."

    sl_pct, tp_pct = sl_tp_pct(direction, entry, stop, target)
    hold = hold_for_tf(tf)
    plan = make_trade_plan(
        direction=direction if (take or waiting) else "—",
        timeframe=tf,
        stop_loss_pct=round(sl_pct or 0, 2),
        take_profit_pct=round(tp_pct or 0, 2),
        confidence_pct=confidence,
        style="intraday" if tf not in ("1d", "1w", "1wk") else "swing",
        exit_rule=(
            f"Simple Effective: SL at opposite MA-band edge; book at {cfg.rr_multiple:.1f}:1 RRR "
            "(trail toward 1:3 only if momentum continues). Invalidate if MACD hist flips against the trade."
        ),
        max_hold_exit=f"Typical hold ({hold}); respect RRR — accuracy over home runs.",
    )

    plain = verdict
    if take or waiting:
        plain += (
            f" Entry≈{_r(entry)} · SL≈{_r(stop)} (opp. band) · TP≈{_r(target)} "
            f"({cfg.rr_multiple:.1f}:1)."
        )

    levels = [
        {"label": "Band lo", "price": _r(band_lo_s), "color": "#94a3b8"},
        {"label": "Band hi", "price": _r(band_hi_s), "color": "#94a3b8"},
        {"label": "Entry", "price": _r(entry), "color": "#38bdf8"},
        {"label": "SL", "price": _r(stop), "color": "#f87171"},
        {"label": f"TP {cfg.rr_multiple:.1f}:1", "price": _r(target), "color": "#34d399"},
    ]

    out.update({
        "timeframe": tf,
        "ltp": _r(close),
        "bars": len(work),
        "take_trade": take,
        "signal": signal_name,
        "direction": direction if (take or waiting) else "NONE",
        "status": status,
        "verdict": verdict,
        "plain_english": plain,
        "confidence_pct": confidence,
        "sl_pct": _r(sl_pct, 2) if sl_pct is not None else None,
        "tp_pct": _r(tp_pct, 2) if tp_pct is not None else None,
        "entry_price": _r(entry) if (take or waiting) else None,
        "stop_price": _r(stop) if (take or waiting) else None,
        "target_price": _r(target) if (take or waiting) else None,
        "rr": cfg.rr_multiple,
        "trade_plan": {**plan, "holding_period": hold},
        "setup": setup,
        "checks": checks,
        "metrics": {
            "ma_fast": setup["ma_fast"],
            "ma_slow": setup["ma_slow"],
            "band_lo": setup["band_lo"],
            "band_hi": setup["band_hi"],
            "macd": setup["macd"],
            "macd_signal": setup["macd_signal"],
            "macd_hist": setup["macd_hist"],
            "hist_zone": setup["hist_zone"],
            "signal_time": setup["signal_time"],
            "triggered": setup["triggered"],
            "rr_multiple": cfg.rr_multiple,
            "ma_type": "EMA" if cfg.use_ema else "SMA",
        },
        "reasons": [f"{'✓' if ch['pass'] else '✗'} {ch['label']} — {ch['detail']}" for ch in checks],
        "trade_suggestion": {
            "action": "BUY" if take and direction == "LONG" else "SELL" if take and direction == "SHORT" else "WAIT",
            "side": direction if take else "WAIT",
            "confidence_pct": confidence,
            "sl_pct": _r(sl_pct, 2) if sl_pct is not None else None,
            "tp_pct": _r(tp_pct, 2) if tp_pct is not None else None,
            "entry_price": _r(entry) if (take or waiting) else None,
            "stop_price": _r(stop) if (take or waiting) else None,
            "target_price": _r(target) if (take or waiting) else None,
            "plain_english": plain,
            "action_label": (
                f"{'BUY' if direction == 'LONG' else 'SELL'} — Simple Effective trigger"
                if take
                else (
                    f"WAIT TRIGGER — break {'High' if direction == 'LONG' else 'Low'} {_r(entry)}"
                    if waiting
                    else "WAIT — no live Simple Effective setup"
                )
            ),
        },
        "chart_levels": levels,
        "chart_data": _build_chart(work, max_bars=cfg.chart_bars),
        "chart_series": [
            {"key": "ma_fast", "label": f"{'EMA' if cfg.use_ema else 'SMA'}{cfg.ma_fast}", "color": "#38bdf8"},
            {"key": "ma_slow", "label": f"{'EMA' if cfg.use_ema else 'SMA'}{cfg.ma_slow}", "color": "#fb923c"},
        ],
        "score_breakdown": {"total": confidence, "reasons": score_reasons[:12]},
    })
    return out


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: SimpleEffectiveConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
    timeframes: list[str] | None = None,
) -> dict[str, Any]:
    cfg = cfg or SimpleEffectiveConfig()
    tfs = [t.strip() for t in (timeframes or [cfg.timeframe]) if t and str(t).strip()]
    if not tfs:
        tfs = [cfg.timeframe]

    results: list[dict[str, Any]] = []
    for t in tickers:
        for tf in tfs:
            try:
                local = replace(cfg, timeframe=tf)
                results.append(
                    analyze_ticker(t, market, cfg=local, groww_token=groww_token, exchange=exchange)
                )
            except Exception as exc:
                logger.exception("Simple Effective failed for %s %s", t, tf)
                results.append({
                    "ticker": t, "timeframe": tf, "strategy": STRATEGY_ID, "error": str(exc)[:240],
                })

    actionable = [r for r in results if r.get("take_trade")]
    return {
        "strategy": STRATEGY_ID,
        "strategy_label": STRATEGY_NAME,
        "how_it_works": HOW_IT_WORKS,
        "rules": RULES,
        "timeframes": tfs,
        "config": {
            "ma_fast": cfg.ma_fast,
            "ma_slow": cfg.ma_slow,
            "use_ema": cfg.use_ema,
            "rr_multiple": cfg.rr_multiple,
            "macd_fast": cfg.macd_fast,
            "macd_slow": cfg.macd_slow,
            "macd_signal": cfg.macd_signal,
        },
        "results": results,
        "entry_count": len(actionable),
        "scanned": len(results),
        "ai_system_prompt": SIMPLE_EFFECTIVE_AI_SYSTEM,
        "disclaimer": (
            "Research / education only — not financial advice. "
            "Prefer 1:1–1:1.5 RRR for accuracy; never take MA breaks without MACD-in-histogram confirmation."
        ),
    }


def build_simple_effective_ai_prompt(result: dict[str, Any]) -> str:
    extra = [
        f"Status: {result.get('status')}",
        f"Setup: {result.get('setup')}",
        f"Metrics: {result.get('metrics')}",
        f"Checks: {result.get('checks')}",
    ]
    return build_pro_trade_ai_context(
        result,
        engine_label=STRATEGY_NAME,
        extra_lines=extra,
    )
