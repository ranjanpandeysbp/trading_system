"""
rlb_breakout_engine.py
----------------------
RLB — Rocket Launcher Breakout screener.

Source: https://www.youtube.com/watch?v=pBQ1oVDVe3M

Seven confirmations (bullish momentum / explosive breakout filter):

1. Breakout above previous day's high — close (or LTP) > prior high
2. Bullish candle — close > open (green day)
3. Close above 20 EMA
4. Close above 50 EMA (video also allows 50 SMA; we use EMA50 by default)
5. RSI > 60 (prefer ≥ 65 for strong momentum)
6. Daily gain > 2%
7. Volume > 5-day SMA of volume

Combining trend, momentum, price action, and volume filters false breakouts.

Research / education only — not financial advice. All asset classes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.pro_trade_shared import (
    ConfidenceScore,
    atr as _atr_ind,
    build_pro_trade_ai_context,
    ema as _ema,
    pro_trade_ai_system,
    rsi as _rsi,
    sl_tp_pct,
)
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.smart_money_shared import hold_for_tf

logger = logging.getLogger(__name__)

YOUTUBE_URL = "https://www.youtube.com/watch?v=pBQ1oVDVe3M"
STRATEGY_ID = "rlb_breakout"
STRATEGY_NAME = "RLB - Breakout"

HOW_IT_WORKS = """
### How RLB (Rocket Launcher Breakout) works

Source: [YouTube](https://www.youtube.com/watch?v=pBQ1oVDVe3M)

RLB screens for stocks with **strong bullish momentum** and **explosive breakout** potential by
requiring **seven confirmations** at once — trend + candle + momentum + volume.

| # | Confirmation | Rule |
|---|--------------|------|
| 1 | Breakout above prior high | Close **> previous day's high** |
| 2 | Bullish (green) candle | Close **> Open** |
| 3 | Above 20 EMA | Close **> EMA20** |
| 4 | Above 50 EMA | Close **> EMA50** (video allows 50 SMA) |
| 5 | Strong RSI momentum | RSI **> 60** (prefer **≥ 65**) |
| 6 | Significant daily gain | Day change **> 2%** |
| 7 | Volume confirmation | Volume **> 5-day SMA of volume** |

**How to use this screen**
1. Pick an asset class and liquid tickers.
2. Scan on the daily chart (default).
3. Focus on **PASS / actionable** rows — all 7 checks green, or near-misses with high score.
4. Prefer RSI ≥ 65 and clear volume expansion for higher-conviction “rocket” launches.
5. Use the suggested ATR stop / target as a risk frame — not a guarantee of continuation.

False breakouts often fail one of: prior-high break, green candle, EMA stack, RSI, % gain, or volume.
Requiring all seven filters those out.

Research / education only — not financial advice.
""".strip()

RULES = [
    "Close > previous day's high (breakout).",
    "Green candle: close > open.",
    "Close > EMA20.",
    "Close > EMA50.",
    "RSI > 60 (prefer ≥ 65).",
    "Daily % change > 2%.",
    "Volume > 5-day SMA of volume.",
]

RLB_AI_SYSTEM = pro_trade_ai_system(
    "RLB - Breakout (Rocket Launcher Breakout)",
    "Seven-check bullish breakout screener: prior-high break, green candle, EMA20, EMA50, "
    "RSI>60 (prefer ≥65), daily gain >2%, volume > 5-day volume SMA.",
)


@dataclass
class RlbBreakoutConfig:
    timeframe: str = "1d"
    lookback_bars: int = 250
    ema_fast: int = 20
    ema_slow: int = 50
    rsi_period: int = 14
    rsi_min: float = 60.0
    rsi_prefer: float = 65.0
    min_day_chg_pct: float = 2.0
    volume_sma_period: int = 5
    min_bars: int = 60
    chart_bars: int = 120
    sl_atr_mult: float = 1.2
    tp_atr_mult: float = 2.4
    take_confidence_threshold: float = 70.0
    # Require all 7 for take_trade; partials still scored
    require_all_seven: bool = True


def _r(x: float, n: int = 6) -> float:
    return round(float(x), n)


def _build_chart(df: pd.DataFrame, *, max_bars: int) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    has_vol = "volume" in df.columns
    has_e20 = "ema20" in df.columns
    has_e50 = "ema50" in df.columns
    tail = df.iloc[-max_bars:]
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
        if has_e20 and pd.notna(bar.get("ema20")):
            row["ema20"] = _r(float(bar["ema20"]))
        if has_e50 and pd.notna(bar.get("ema50")):
            row["ema50"] = _r(float(bar["ema50"]))
        rows.append(row)
    return rows


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: RlbBreakoutConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or RlbBreakoutConfig()
    tf = (cfg.timeframe or "1d").strip() or "1d"
    out: dict[str, Any] = {
        "ticker": ticker,
        "strategy": STRATEGY_ID,
        "strategy_label": STRATEGY_NAME,
        "error": None,
        "take_trade": False,
        "signal": "WAIT",
        "direction": "NONE",
        "verdict": "No RLB setup yet",
        "confidence_pct": None,
        "chart_data": [],
        "youtube": YOUTUBE_URL,
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
    need = max(cfg.min_bars, cfg.ema_slow + 5, cfg.rsi_period + 5, cfg.volume_sma_period + 2)
    if df is None or df.empty or len(df) < need:
        out["error"] = f"Insufficient {tf} data (need ≥{need} bars)."
        return out

    work = df.copy()
    work["ema20"] = _ema(work["close"], cfg.ema_fast)
    work["ema50"] = _ema(work["close"], cfg.ema_slow)
    work["rsi"] = _rsi(work["close"], cfg.rsi_period)
    work["vol_sma5"] = (
        work["volume"].rolling(cfg.volume_sma_period, min_periods=cfg.volume_sma_period).mean()
        if "volume" in work.columns
        else pd.Series(index=work.index, dtype=float)
    )
    work["atr"] = _atr_ind(work, 14)
    work = work.dropna(subset=["ema20", "ema50", "rsi"])
    if len(work) < 3:
        out["error"] = "Not enough bars after indicator warm-up."
        return out

    last = work.iloc[-1]
    prev = work.iloc[-2]
    o = float(last["open"])
    h = float(last["high"])
    low = float(last["low"])
    c = float(last["close"])
    prev_high = float(prev["high"])
    prev_close = float(prev["close"])
    e20 = float(last["ema20"])
    e50 = float(last["ema50"])
    rsi_v = float(last["rsi"])
    vol = float(last["volume"]) if "volume" in last and pd.notna(last.get("volume")) else None
    vol_sma = float(last["vol_sma5"]) if pd.notna(last.get("vol_sma5")) else None
    atr_v = float(last["atr"]) if pd.notna(last.get("atr")) else None

    day_chg_pct = ((c / prev_close) - 1.0) * 100.0 if prev_close > 0 else 0.0

    checks = [
        {
            "id": "prior_high_break",
            "label": "Breakout above previous high",
            "pass": c > prev_high,
            "detail": f"Close {_r(c)} vs prior high {_r(prev_high)}",
            "weight": 16,
        },
        {
            "id": "green_candle",
            "label": "Bullish (green) candle",
            "pass": c > o,
            "detail": f"Close {_r(c)} vs open {_r(o)}",
            "weight": 12,
        },
        {
            "id": "above_ema20",
            "label": "Above 20 EMA",
            "pass": c > e20,
            "detail": f"Close {_r(c)} vs EMA20 {_r(e20)}",
            "weight": 12,
        },
        {
            "id": "above_ema50",
            "label": "Above 50 EMA",
            "pass": c > e50,
            "detail": f"Close {_r(c)} vs EMA50 {_r(e50)}",
            "weight": 12,
        },
        {
            "id": "rsi_momentum",
            "label": f"RSI > {cfg.rsi_min:.0f} (prefer ≥{cfg.rsi_prefer:.0f})",
            "pass": rsi_v > cfg.rsi_min,
            "detail": f"RSI {_r(rsi_v, 1)}",
            "weight": 14,
            "strong": rsi_v >= cfg.rsi_prefer,
        },
        {
            "id": "day_gain",
            "label": f"Daily gain > {cfg.min_day_chg_pct:.0f}%",
            "pass": day_chg_pct > cfg.min_day_chg_pct,
            "detail": f"Day change {_r(day_chg_pct, 2)}%",
            "weight": 12,
        },
        {
            "id": "volume_confirm",
            "label": f"Volume > {cfg.volume_sma_period}-day SMA",
            "pass": vol is not None and vol_sma is not None and vol > vol_sma,
            "detail": (
                f"Vol {_r(vol, 0)} vs SMA{cfg.volume_sma_period} {_r(vol_sma, 0)}"
                if vol is not None and vol_sma is not None
                else "Volume data unavailable"
            ),
            "weight": 14,
        },
    ]

    passed = sum(1 for ch in checks if ch["pass"])
    all_seven = passed == 7
    score = ConfidenceScore(28.0, "RLB base")
    for ch in checks:
        score.add(bool(ch["pass"]), float(ch["weight"]), f"{ch['label']}: {ch['detail']}")
        if ch.get("strong"):
            score.add(True, 6.0, f"RSI preference met (≥{cfg.rsi_prefer:.0f})")

    # Extra quality: EMA stack alignment
    if e20 > e50 and c > e20:
        score.add(True, 4.0, "EMA20 > EMA50 with price above both — trend aligned")

    confidence, score_reasons = score.finalize()
    take = all_seven if cfg.require_all_seven else passed >= 6
    if take and confidence < cfg.take_confidence_threshold:
        take = False

    if all_seven:
        signal, direction = "BULLISH", "LONG"
        verdict = (
            f"RLB PASS — all 7 Rocket Launcher confirmations hit on {ticker}. "
            f"Prior-high break + green candle + EMA20/50 + RSI {rsi_v:.0f} + "
            f"{day_chg_pct:.1f}% day + volume above {cfg.volume_sma_period}-day average."
        )
    elif passed >= 5:
        signal, direction = "WATCH", "LONG"
        take = False
        failed = [ch["label"] for ch in checks if not ch["pass"]]
        verdict = (
            f"Near-miss RLB ({passed}/7). Missing: {', '.join(failed)}. "
            "Watch for the remaining confirmations before treating as a rocket launch."
        )
    else:
        signal, direction = "WAIT", "NONE"
        take = False
        verdict = f"RLB not ready — only {passed}/7 confirmations. Filter remains selective by design."

    entry = c
    sl_pct = tp_pct = None
    stop = target = None
    if take and atr_v and atr_v > 0:
        stop = _r(c - cfg.sl_atr_mult * atr_v)
        target = _r(c + cfg.tp_atr_mult * atr_v)
        sl_pct, tp_pct = sl_tp_pct("LONG", entry, stop, target)
    elif take:
        stop = _r(c * 0.98)
        target = _r(c * 1.04)
        sl_pct, tp_pct = sl_tp_pct("LONG", entry, stop, target)

    hold = hold_for_tf(tf)
    plan = make_trade_plan(
        direction="LONG" if take or direction == "LONG" else "—",
        timeframe=tf,
        stop_loss_pct=round(sl_pct or 0, 2),
        take_profit_pct=round(tp_pct or 0, 2),
        confidence_pct=confidence,
        style="momentum",
        exit_rule=(
            "RLB: trail under EMA20 or prior-day low if momentum fades; "
            "invalidate if close back below prior high / EMA20."
        ),
        max_hold_exit=f"Momentum hold typical days–weeks ({hold}); book into extension / RSI extreme.",
    )

    plain = verdict
    if take and sl_pct is not None and tp_pct is not None:
        plain += f" Suggested risk frame SL≈{sl_pct:.1f}% · TP≈{tp_pct:.1f}% (ATR-based)."

    chart = _build_chart(work, max_bars=cfg.chart_bars)
    levels = [
        {"label": "Prior high", "price": _r(prev_high), "color": "#a78bfa"},
        {"label": "EMA20", "price": _r(e20), "color": "#38bdf8"},
        {"label": "EMA50", "price": _r(e50), "color": "#fb923c"},
    ]
    if take and stop:
        levels.append({"label": "SL", "price": stop, "color": "#f87171"})
    if take and target:
        levels.append({"label": "TP", "price": target, "color": "#34d399"})

    out.update({
        "timeframe": tf,
        "ltp": _r(c),
        "bars": len(work),
        "take_trade": take,
        "signal": signal,
        "direction": direction,
        "status": "RLB_PASS" if all_seven else f"PARTIAL_{passed}_OF_7",
        "verdict": verdict,
        "plain_english": plain,
        "confidence_pct": confidence,
        "passed_count": passed,
        "checks_total": 7,
        "all_seven": all_seven,
        "sl_pct": _r(sl_pct, 2) if sl_pct is not None else None,
        "tp_pct": _r(tp_pct, 2) if tp_pct is not None else None,
        "entry_price": _r(entry) if take else None,
        "stop_price": stop if take else None,
        "target_price": target if take else None,
        "trade_plan": {**plan, "holding_period": hold},
        "checks": checks,
        "metrics": {
            "open": _r(o),
            "high": _r(h),
            "low": _r(low),
            "close": _r(c),
            "prev_high": _r(prev_high),
            "ema20": _r(e20),
            "ema50": _r(e50),
            "rsi": _r(rsi_v, 1),
            "day_chg_pct": _r(day_chg_pct, 2),
            "volume": _r(vol, 0) if vol is not None else None,
            "volume_sma5": _r(vol_sma, 0) if vol_sma is not None else None,
            "atr": _r(atr_v, 4) if atr_v is not None else None,
        },
        "reasons": [f"{'✓' if ch['pass'] else '✗'} {ch['label']} — {ch['detail']}" for ch in checks],
        "trade_suggestion": {
            "action": "BUY" if take else "WAIT",
            "side": "LONG" if take else "WAIT",
            "confidence_pct": confidence,
            "sl_pct": _r(sl_pct, 2) if sl_pct is not None else None,
            "tp_pct": _r(tp_pct, 2) if tp_pct is not None else None,
            "entry_price": _r(entry) if take else None,
            "stop_price": stop if take else None,
            "target_price": target if take else None,
            "plain_english": plain,
            "action_label": (
                "BUY — RLB rocket launcher pass" if take
                else f"WAIT — {passed}/7 RLB confirmations"
            ),
        },
        "chart_levels": levels,
        "chart_data": chart,
        "chart_series": [
            {"key": "ema20", "label": "EMA20", "color": "#38bdf8"},
            {"key": "ema50", "label": "EMA50", "color": "#fb923c"},
        ],
        "score_breakdown": {"total": confidence, "reasons": score_reasons[:12]},
    })
    return out


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: RlbBreakoutConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or RlbBreakoutConfig()
    results: list[dict[str, Any]] = []
    for t in tickers:
        try:
            results.append(
                analyze_ticker(t, market, cfg=cfg, groww_token=groww_token, exchange=exchange)
            )
        except Exception as exc:
            logger.exception("RLB Breakout failed for %s", t)
            results.append({"ticker": t, "strategy": STRATEGY_ID, "error": str(exc)[:240]})

    actionable = [r for r in results if r.get("take_trade")]
    return {
        "strategy": STRATEGY_ID,
        "strategy_label": STRATEGY_NAME,
        "youtube": YOUTUBE_URL,
        "how_it_works": HOW_IT_WORKS,
        "rules": RULES,
        "timeframe": cfg.timeframe,
        "config": {
            "ema_fast": cfg.ema_fast,
            "ema_slow": cfg.ema_slow,
            "rsi_min": cfg.rsi_min,
            "rsi_prefer": cfg.rsi_prefer,
            "min_day_chg_pct": cfg.min_day_chg_pct,
            "volume_sma_period": cfg.volume_sma_period,
            "lookback_bars": cfg.lookback_bars,
        },
        "results": results,
        "entry_count": len(actionable),
        "scanned": len(results),
        "ai_system_prompt": RLB_AI_SYSTEM,
        "disclaimer": (
            "Research / education only — not financial advice. "
            "RLB filters for high-momentum breakouts; they can reverse quickly — size risk accordingly."
        ),
    }


def build_rlb_breakout_ai_prompt(result: dict[str, Any]) -> str:
    extra = [
        f"Status: {result.get('status')}",
        f"Passed: {result.get('passed_count')}/{result.get('checks_total')}",
        f"Metrics: {result.get('metrics')}",
        f"Checks: {result.get('checks')}",
    ]
    return build_pro_trade_ai_context(
        result,
        engine_label=STRATEGY_NAME,
        extra_lines=extra,
    )
