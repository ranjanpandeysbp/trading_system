"""
scalp_ichimoku_crash_engine.py
-------------------------------
Ichimoku Cloud "Crash Predictor" scalping/short-selling strategy —
AbhishekXTrades.

Source: https://www.youtube.com/watch?v=TqqqxCpPxoM

Rules (as taught), on a 4-hour chart, primarily crypto (ETH/BTC) but
applicable to other markets:

4 conditions for a SHORT (crash) setup:
  1. Price below the Conversion Line (Tenkan-sen, 9-period).
  2. Bearish crossover: Tenkan-sen below the Base Line (Kijun-sen,
     26-period).
  3. Lagging Span (Chikou — the current close, plotted 26 periods back)
     positioned below the price candles from 26 periods ago. This confirms
     the crossover is genuine and not a trap.
  4. Cloud (Senkou Span A/B, plotted 26 periods ahead) sits above price,
     acting as overhead resistance.

Entry: once all four conditions are fulfilled, enter as soon as a red
candle closes.
Stop-loss: slightly above the Base Line (Kijun-sen) — NOT the faster
Conversion Line, which reacts too quickly to minor fluctuations.
Risk:Reward: minimum 1:3, ideally 1:4 — never settle for 1:2 when catching
a large crash.

Non-negotiable rules from the video (surfaced in `reasons` for the trader
to follow — this is a stateless scanner, not a position tracker, so it
can't enforce them):
  - Backtest before trusting the strategy live.
  - Hold the 1:3 / 1:4 minimum risk:reward.
  - Never deploy full capital on a single trade.

This implementation also mirrors the four conditions for the LONG side
(price/Tenkan/Chikou above their references, cloud below price acting as
support) — the video is framed around the short/crash use case
specifically, but the underlying Ichimoku alignment check is direction-
agnostic, and every other scanner in this app reports both directions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.intraday_shared import enrich_intra_live

logger = logging.getLogger(__name__)

YOUTUBE_ICHIMOKU_CRASH_URL = "https://www.youtube.com/watch?v=TqqqxCpPxoM"

EXECUTION_TF_OPTIONS = ["1h", "4h", "1d"]


@dataclass
class IchimokuCrashConfig:
    execution_tf: str = "4h"
    tenkan_period: int = 9
    kijun_period: int = 26
    senkou_b_period: int = 52
    displacement: int = 26
    sl_buffer_pct: float = 0.3
    min_rr: float = 3.0
    lookback: int = 400
    min_bars: int = 120


def add_ichimoku(df: pd.DataFrame, cfg: IchimokuCrashConfig) -> pd.DataFrame:
    """Tenkan/Kijun/Senkou A/B computed from rolling high-low midpoints, no
    external TA library dependency (pandas_ta's ichimoku() is broken under
    this environment's numpy version — this avoids that entirely)."""
    out = df.copy()
    high, low, close = out["high"], out["low"], out["close"]
    out["tenkan"] = (high.rolling(cfg.tenkan_period).max() + low.rolling(cfg.tenkan_period).min()) / 2
    out["kijun"] = (high.rolling(cfg.kijun_period).max() + low.rolling(cfg.kijun_period).min()) / 2
    senkou_a = (out["tenkan"] + out["kijun"]) / 2
    senkou_b = (high.rolling(cfg.senkou_b_period).max() + low.rolling(cfg.senkou_b_period).min()) / 2
    # Shifted forward so the value at row i is the cloud boundary actually
    # displayed above/below the candle at row i on a real chart.
    out["senkou_a"] = senkou_a.shift(cfg.displacement)
    out["senkou_b"] = senkou_b.shift(cfg.displacement)
    out["past_low"] = low.shift(cfg.displacement)
    out["past_high"] = high.shift(cfg.displacement)
    return out


def scan_ichimoku_crash_signals(work: pd.DataFrame, cfg: IchimokuCrashConfig) -> list[dict[str, Any]]:
    if work.empty or "senkou_a" not in work.columns:
        return []

    signals: list[dict[str, Any]] = []
    closes = work["close"].to_numpy()
    opens = work["open"].to_numpy()
    tenkan = work["tenkan"].to_numpy()
    kijun = work["kijun"].to_numpy()
    senkou_a = work["senkou_a"].to_numpy()
    senkou_b = work["senkou_b"].to_numpy()
    past_low = work["past_low"].to_numpy()
    past_high = work["past_high"].to_numpy()

    for i in range(len(work)):
        vals = (tenkan[i], kijun[i], senkou_a[i], senkou_b[i], past_low[i], past_high[i])
        if any(pd.isna(v) for v in vals):
            continue
        c, o = float(closes[i]), float(opens[i])
        cloud_top, cloud_bot = max(senkou_a[i], senkou_b[i]), min(senkou_a[i], senkou_b[i])
        is_red, is_green = c < o, c > o

        short_ok = c < tenkan[i] and tenkan[i] < kijun[i] and c < past_low[i] and c < cloud_bot
        long_ok = c > tenkan[i] and tenkan[i] > kijun[i] and c > past_high[i] and c > cloud_top

        if short_ok and is_red:
            signals.append({
                "bar_index": i, "timestamp": str(work.index[i]), "direction": "SHORT",
                "entry": c, "kijun": float(kijun[i]),
            })
        elif long_ok and is_green:
            signals.append({
                "bar_index": i, "timestamp": str(work.index[i]), "direction": "LONG",
                "entry": c, "kijun": float(kijun[i]),
            })

    return signals


def evaluate_live_signal(
    work: pd.DataFrame, signals: list[dict[str, Any]], cfg: IchimokuCrashConfig,
) -> dict[str, Any]:
    if work.empty:
        return {"signal": "NO_DATA", "verdict": "NO DATA", "take_trade": False}

    last = work.iloc[-1]
    price = float(last["close"])
    tenkan = float(last["tenkan"]) if pd.notna(last.get("tenkan")) else None
    kijun = float(last["kijun"]) if pd.notna(last.get("kijun")) else None
    senkou_a = float(last["senkou_a"]) if pd.notna(last.get("senkou_a")) else None
    senkou_b = float(last["senkou_b"]) if pd.notna(last.get("senkou_b")) else None
    past_low = float(last["past_low"]) if pd.notna(last.get("past_low")) else None
    past_high = float(last["past_high"]) if pd.notna(last.get("past_high")) else None

    reasons: list[str] = []
    short_conds: dict[str, bool] | None = None
    long_conds: dict[str, bool] | None = None
    cloud_top = cloud_bot = None

    if None not in (tenkan, kijun, senkou_a, senkou_b, past_low, past_high):
        cloud_top, cloud_bot = max(senkou_a, senkou_b), min(senkou_a, senkou_b)
        short_conds = {
            "Price below the Conversion Line (Tenkan)": price < tenkan,
            "Tenkan below the Base Line (Kijun) — bearish cross": tenkan < kijun,
            "Lagging Span below the candles from 26 bars ago": price < past_low,
            "Cloud above price (resistance overhead)": price < cloud_bot,
        }
        long_conds = {
            "Price above the Conversion Line (Tenkan)": price > tenkan,
            "Tenkan above the Base Line (Kijun) — bullish cross": tenkan > kijun,
            "Lagging Span above the candles from 26 bars ago": price > past_high,
            "Cloud below price (support underneath)": price > cloud_top,
        }
        n_short = sum(short_conds.values())
        n_long = sum(long_conds.values())
        lead = "SHORT" if n_short >= n_long else "LONG"
        lead_conds = short_conds if lead == "SHORT" else long_conds
        reasons.append(f"Ichimoku alignment ({lead.lower()} case, {sum(lead_conds.values())}/4 conditions met):")
        for label, ok in lead_conds.items():
            reasons.append(("✅ " if ok else "❌ ") + label)
    else:
        reasons.append("Not enough history yet to compute the full Ichimoku Cloud (needs 52 + 26 bars of lookback).")

    last_idx = len(work) - 1
    last_signal = signals[-1] if signals else None
    is_fresh = bool(last_signal and last_signal["bar_index"] == last_idx)

    verdict, direction, take = "WAIT", "WAIT", False
    entry = stop = target = price
    confidence = 0.0
    phase = "NO_SETUP"
    if short_conds and all(short_conds.values()):
        phase = "SHORT_SETUP"
    elif long_conds and all(long_conds.values()):
        phase = "LONG_SETUP"

    if is_fresh and last_signal:
        direction = last_signal["direction"]
        entry = last_signal["entry"]
        kijun_ref = last_signal["kijun"]
        buffer = entry * (cfg.sl_buffer_pct / 100.0)
        stop = kijun_ref + buffer if direction == "SHORT" else kijun_ref - buffer
        risk = abs(entry - stop)
        target = entry - risk * cfg.min_rr if direction == "SHORT" else entry + risk * cfg.min_rr

        n_true = sum((short_conds if direction == "SHORT" else long_conds or {}).values()) if (short_conds or long_conds) else 4
        confidence = 55.0 + n_true * 10.0

        take = True
        verdict = (
            ("BUY PUT" if direction == "SHORT" else "BUY CALL")
            + " — all 4 Ichimoku conditions aligned, "
            + ("red" if direction == "SHORT" else "green")
            + " candle confirmed"
        )
        reasons.append(
            f"Entry trigger: all four {'bearish' if direction == 'SHORT' else 'bullish'} conditions held and a "
            + ("red" if direction == "SHORT" else "green")
            + " candle closed — the confirmation signal."
        )
        reasons.append(
            f"Stop-loss just {'above' if direction == 'SHORT' else 'below'} the Base Line (Kijun-sen) at "
            f"{stop:,.4g} — not the faster Conversion Line, which reacts to minor noise."
        )
        reasons.append(
            f"Target set for a minimum 1:{cfg.min_rr:.0f} risk:reward ({target:,.4g}) — never settle for 1:2 "
            "on a trade meant to catch a large move."
        )
        reasons.append("Backtest this setup, hold the 1:3+ R:R discipline, and never deploy full capital on one trade.")
    elif last_signal:
        reasons.append(
            f"Most recent qualifying {last_signal['direction']} setup was {last_signal['timestamp']} — "
            "not the current candle, so no fresh trigger right now."
        )
    else:
        reasons.append("No bar yet where all four Ichimoku conditions aligned with a confirming candle close.")

    sl_pct = round(abs(entry - stop) / entry * 100, 2) if take and entry else None
    tp_pct = round(abs(target - entry) / entry * 100, 2) if take and entry else None

    hold_duration = f"No fixed time exit — hold for the full 1:{cfg.min_rr:.0f}+ target (Ichimoku Crash Predictor)"

    plan = make_trade_plan(
        direction=direction if take else "—", timeframe=cfg.execution_tf,
        stop_loss_pct=sl_pct or 1.0, take_profit_pct=tp_pct or ((sl_pct or 1.0) * cfg.min_rr),
        confidence_pct=confidence, style="scalp",
        exit_rule=f"Exit at the fixed 1:{cfg.min_rr:.0f}+ target, or if price closes back through the Base Line against the trade.",
        max_hold_exit="No fixed time exit — this is a trend/crash-catching trade, not an intraday-only scalp.",
    )

    live = enrich_intra_live({
        "signal": direction if take else "NONE",
        "direction": direction if take else None,
        "take_trade": take,
        "verdict": verdict,
        "phase": phase,
        "confidence_pct": round(confidence, 1) if take else 0.0,
        "sl_pct": sl_pct, "tp_pct": tp_pct,
        "entry_price": round(entry, 6) if take else None,
        "stop_price": round(stop, 6) if take else None,
        "target_price": round(target, 6) if take else None,
        "tenkan": round(tenkan, 6) if tenkan is not None else None,
        "kijun": round(kijun, 6) if kijun is not None else None,
        "cloud_top": round(cloud_top, 6) if cloud_top is not None else None,
        "cloud_bottom": round(cloud_bot, 6) if cloud_bot is not None else None,
        "option_action": ("BUY PUT" if direction == "SHORT" else "BUY CALL") if take else None,
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": hold_duration} if take else None,
    }, hold_duration=hold_duration)

    return live


def analyze_ticker(
    ticker: str, market: str, *, cfg: IchimokuCrashConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or IchimokuCrashConfig()
    is_crypto = "CoinDCX" in market

    df = fetch_data_for_gap_scan(ticker, cfg.execution_tf, market, groww_token, exchange, limit=cfg.lookback)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < cfg.min_bars:
        df = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, cfg.execution_tf, is_crypto=is_crypto, limit=cfg.lookback, market=market)
        )
    if df.empty or len(df) < cfg.min_bars:
        return {
            "ticker": ticker, "market": market,
            "error": f"Insufficient {cfg.execution_tf} data ({len(df)} bars, need {cfg.min_bars}+).",
        }

    work = add_ichimoku(df, cfg)
    signals = scan_ichimoku_crash_signals(work, cfg)
    live = evaluate_live_signal(work, signals, cfg)

    return {
        "ticker": ticker, "market": market, "execution_tf": cfg.execution_tf,
        "bars": len(work), "last_close": float(work["close"].iloc[-1]),
        "signal_history": signals[-8:], "live": live,
    }


def scan_universe(
    tickers: list[str], market: str, *, cfg: IchimokuCrashConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or IchimokuCrashConfig()
    results = []
    for ticker in tickers:
        try:
            results.append(analyze_ticker(ticker, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            logger.debug("Ichimoku Crash scan failed for %s: %s", ticker, exc)
            results.append({"ticker": ticker, "market": market, "error": str(exc)[:200]})

    entries = [r for r in results if not r.get("error") and (r.get("live") or {}).get("take_trade")]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market, "execution_tf": cfg.execution_tf, "results": results,
        "entries": entries, "entry_count": len(entries),
    }
