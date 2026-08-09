"""
traffic_light_indicator_engine.py
---------------------------------
Traffic Light Indicator — SMA 20 / 50 / 200 “traffic light” stack for swing buys/sells.

Source: https://www.youtube.com/watch?v=xIKoYISD6mY&t=29s

Colors (daily chart):
  Red    = SMA 200 (slow)
  Yellow = SMA 50  (medium)
  Green  = SMA 20  (fast)

BUY setup
  1. Stack order: Red on top, Yellow middle, Green bottom  →  SMA200 > SMA50 > SMA20
  2. Price candle closes *below all three* SMAs
  3. Buy the next morning (next session open)

SELL setup
  1. Stack flips: Green on top, Yellow middle, Red bottom  →  SMA20 > SMA50 > SMA200
  2. Price candle closes *above all three* (above Green)
  3. Sell the next morning to book profits

Stock selection (from the video): prefer large-cap / blue-chip names. Small/weak names can
dip and never recover. Patience: setups may take weeks to months (sometimes a year+) to form.

Optional further analysis: Trend & Strength (MTF) confirmation via the shared dispatcher.

Research / education only — not financial advice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.pro_trade_shared import (
    ConfidenceScore,
    atr as _atr_ind,
    build_pro_trade_ai_context,
    pro_trade_ai_system,
    sl_tp_pct,
)
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.smart_money_shared import hold_for_tf

logger = logging.getLogger(__name__)

YOUTUBE_URL = "https://www.youtube.com/watch?v=xIKoYISD6mY&t=29s"
STRATEGY_NAME = "Traffic Light Indicator"
STRATEGY_ID = "traffic_light_indicator"

SMA_GREEN = 20
SMA_YELLOW = 50
SMA_RED = 200

FURTHER_ANALYSIS_OPTIONS = [
    {"id": "mtf_trend_strength", "label": "Trend & Strength (MTF)"},
]

_FURTHER_CONFIRM = 6.0
_FURTHER_DISAGREE = 5.0

HOW_IT_WORKS = """
### How the Traffic Light Indicator works

Imagine three moving averages as a **traffic light** on a daily chart:

| Color | SMA | Role |
|-------|-----|------|
| **Red** | 200-day | Long-term “ceiling / floor” of institutional trend |
| **Yellow** | 50-day | Medium trend |
| **Green** | 20-day | Short swing trend |

**BUY (accumulation / swing entry)**  
When the stack is **Red > Yellow > Green** (bearish MA order) and price **closes under all three**,
the video treats that as a washed-out large-cap that is ready for a patient buy the **next morning**.
You are buying weakness into a structured pullback under the traffic light — not chasing green candles.

**SELL (book profits / exit)**  
When the stack **flips** to **Green > Yellow > Red** (bullish MA order) and price **closes above all three**,
sell the **next morning**. The light has turned “go” for the trend; the strategy books the swing.

**Who it is for**  
Swing traders holding weeks–months. Long-term investors can treat closes under the **200 SMA (Red)**
as accumulate zones on quality large-caps. Avoid applying this blindly to thin small-caps.

**Patience**  
Setups can take a month to over a year. After entry, quality names often consolidate before bouncing —
that is expected, not a reason to panic-sell the next red day.
""".strip()


TRAFFIC_LIGHT_AI_SYSTEM = pro_trade_ai_system(
    "Traffic Light Indicator",
    "SMA 20 (Green) / 50 (Yellow) / 200 (Red) traffic-light stack on daily (or HTF) charts. "
    "BUY when Red>Yellow>Green and close below all three — enter next morning. "
    "SELL when Green>Yellow>Red and close above all three — exit next morning. "
    "Prefer large-cap names; optional Trend & Strength (MTF) confirmation.",
)


@dataclass
class TrafficLightConfig:
    timeframe: str = "1d"
    lookback_bars: int = 400
    sma_green: int = SMA_GREEN
    sma_yellow: int = SMA_YELLOW
    sma_red: int = SMA_RED
    min_bars: int = 220
    rr_min: float = 1.5
    sl_atr_mult: float = 1.5
    tp_atr_mult: float = 3.0
    take_confidence_threshold: float = 55.0
    further_analysis: list[str] = field(default_factory=list)
    chart_bars: int = 180


def _build_chart_data(df: pd.DataFrame, *, max_bars: int = 180) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    has_vol = "volume" in df.columns
    has_g = "sma_green" in df.columns
    has_y = "sma_yellow" in df.columns
    has_r = "sma_red" in df.columns
    tail = df.iloc[-max_bars:]
    rows: list[dict[str, Any]] = []
    for idx, bar in tail.iterrows():
        row: dict[str, Any] = {
            "time": str(idx),
            "open": round(float(bar["open"]), 6),
            "high": round(float(bar["high"]), 6),
            "low": round(float(bar["low"]), 6),
            "close": round(float(bar["close"]), 6),
            "volume": round(float(bar["volume"]), 2) if has_vol and pd.notna(bar.get("volume")) else None,
        }
        if has_g and pd.notna(bar.get("sma_green")):
            row["sma_green"] = round(float(bar["sma_green"]), 6)
        if has_y and pd.notna(bar.get("sma_yellow")):
            row["sma_yellow"] = round(float(bar["sma_yellow"]), 6)
        if has_r and pd.notna(bar.get("sma_red")):
            row["sma_red"] = round(float(bar["sma_red"]), 6)
        rows.append(row)
    return rows


def _apply_further_analysis(
    ticker: str,
    direction: str,
    checks: list[str],
    *,
    market: str,
    groww_token: str,
    exchange: str,
) -> tuple[list[str], float, dict[str, Any] | None]:
    valid_ids = {o["id"] for o in FURTHER_ANALYSIS_OPTIONS}
    valid = [c for c in (checks or []) if c in valid_ids]
    if not valid:
        return [], 0.0, None

    from app.trading_hubs.intra_hedging_engine import _run_one_further_check

    reasons: list[str] = []
    delta = 0.0
    detail: dict[str, Any] | None = None
    for check_id in valid:
        confirmed, note = _run_one_further_check(
            check_id,
            ticker,
            market,
            direction,
            momentum_timeframe="1d",
            groww_token=groww_token,
            exchange=exchange,
        )
        if note:
            reasons.append(note)
        if confirmed is True:
            delta += _FURTHER_CONFIRM
        elif confirmed is False:
            delta -= _FURTHER_DISAGREE
        if check_id == "mtf_trend_strength":
            detail = {"confirmed": confirmed, "note": note}
    return reasons, delta, detail


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: TrafficLightConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or TrafficLightConfig()
    tf = (cfg.timeframe or "1d").strip() or "1d"
    out: dict[str, Any] = {
        "ticker": ticker,
        "strategy": STRATEGY_ID,
        "strategy_label": STRATEGY_NAME,
        "error": None,
        "take_trade": False,
        "signal": "WAIT",
        "direction": "NONE",
        "verdict": "No traffic-light setup yet",
        "confidence_pct": None,
        "sl_pct": None,
        "tp_pct": None,
        "chart_data": [],
        "sma_levels": [],
        "youtube": YOUTUBE_URL,
        "how_it_works": HOW_IT_WORKS,
        "rules": [
            "Daily (or HTF) chart with SMA20 (Green), SMA50 (Yellow), SMA200 (Red).",
            "BUY: Red>Yellow>Green stack AND close below all three → buy next morning.",
            "SELL: Green>Yellow>Red flip AND close above all three → sell next morning.",
            "Prefer large-cap / blue-chip names; be patient — setups can take months.",
        ],
    }

    try:
        df = fetch_data_for_gap_scan(
            ticker, tf, market, groww_token=groww_token, exchange=exchange, limit=cfg.lookback_bars,
        )
    except Exception as exc:
        out["error"] = f"Data fetch failed: {exc}"
        return out

    df = normalize_ohlcv(df)
    if df is None or df.empty or len(df) < cfg.min_bars:
        out["error"] = f"Insufficient {tf} data (need ≥{cfg.min_bars} bars for SMA{cfg.sma_red})."
        return out

    work = df.copy()
    work["sma_green"] = work["close"].rolling(cfg.sma_green, min_periods=cfg.sma_green).mean()
    work["sma_yellow"] = work["close"].rolling(cfg.sma_yellow, min_periods=cfg.sma_yellow).mean()
    work["sma_red"] = work["close"].rolling(cfg.sma_red, min_periods=cfg.sma_red).mean()
    work = work.dropna(subset=["sma_green", "sma_yellow", "sma_red"])
    if work.empty or len(work) < 5:
        out["error"] = "Not enough bars after SMA warm-up."
        return out

    last = work.iloc[-1]
    close = float(last["close"])
    g = float(last["sma_green"])
    y = float(last["sma_yellow"])
    r = float(last["sma_red"])

    buy_stack = r > y > g
    sell_stack = g > y > r
    price_below_all = close < min(g, y, r)
    price_above_all = close > max(g, y, r)

    stack_label = (
        "BUY stack (Red > Yellow > Green)" if buy_stack
        else "SELL stack (Green > Yellow > Red)" if sell_stack
        else "Mixed / transitional stack"
    )

    signal = "WAIT"
    direction = "NONE"
    take = False
    score = ConfidenceScore(42.0, "Traffic Light SMA 20/50/200 base")
    reasons_extra: list[str] = [
        f"SMA20 (Green)={g:.4g} · SMA50 (Yellow)={y:.4g} · SMA200 (Red)={r:.4g}",
        f"Stack: {stack_label}",
        f"Close {close:.4g} — "
        + ("below all three" if price_below_all else "above all three" if price_above_all else "inside the traffic light"),
    ]

    if buy_stack and price_below_all:
        signal, direction, take = "BUY", "LONG", True
        score.add(True, 18, "BUY stack Red>Yellow>Green")
        score.add(True, 14, "Close below all three SMAs — next-morning buy candidate")
        verdict = (
            f"BUY setup: traffic light is Red>Yellow>Green and price closed under all three. "
            f"Plan to buy {ticker} at the next session open (video: next morning)."
        )
    elif sell_stack and price_above_all:
        signal, direction, take = "SELL", "SHORT", True
        score.add(True, 18, "SELL stack Green>Yellow>Red")
        score.add(True, 14, "Close above all three SMAs — next-morning sell / book-profits candidate")
        verdict = (
            f"SELL setup: traffic light flipped Green>Yellow>Red and price closed above all three. "
            f"Plan to sell {ticker} at the next session open to book profits."
        )
    elif buy_stack:
        signal = "WATCH_BUY"
        direction = "LONG"
        score.add(True, 10, "BUY stack ready — waiting for a close below all three")
        verdict = (
            "BUY stack is in place (Red>Yellow>Green) but price has not closed under all three yet. "
            "Watch for a daily close below Green/Yellow/Red before buying next morning."
        )
    elif sell_stack:
        signal = "WATCH_SELL"
        direction = "SHORT"
        score.add(True, 10, "SELL stack ready — waiting for a close above all three")
        verdict = (
            "SELL stack is in place (Green>Yellow>Red) but price has not closed above all three yet. "
            "Watch for a daily close above Green before selling next morning."
        )
    else:
        verdict = (
            "No clean traffic-light stack. Wait for Red>Yellow>Green (buy path) or "
            "Green>Yellow>Red (sell path) to form — this can take weeks to months."
        )

    atr_s = _atr_ind(work, 14)
    atr_last = float(atr_s.dropna().iloc[-1]) if not atr_s.dropna().empty else close * 0.02
    if atr_last > 0 and take:
        if direction == "LONG":
            score.add(
                (min(g, y, r) - close) / atr_last >= 0.3,
                4,
                "Meaningful stretch under the traffic light (ATR)",
            )
        if direction == "SHORT":
            score.add(
                (close - max(g, y, r)) / atr_last >= 0.3,
                4,
                "Meaningful stretch above the traffic light (ATR)",
            )

    fa_detail = None
    if cfg.further_analysis and direction in ("LONG", "SHORT"):
        fa_reasons, fa_delta, fa_detail = _apply_further_analysis(
            ticker, direction, cfg.further_analysis,
            market=market, groww_token=groww_token, exchange=exchange,
        )
        reasons_extra.extend(fa_reasons)
        if fa_delta > 0:
            score.add(True, fa_delta, "Trend & Strength further analysis confirms")
        elif fa_delta < 0:
            score.add(True, fa_delta, "Trend & Strength further analysis disagrees")

    confidence, score_reasons = score.finalize()
    reasons = score_reasons + reasons_extra
    if take and confidence < cfg.take_confidence_threshold:
        take = False
        reasons.append(
            f"Confidence {confidence}% below take threshold {cfg.take_confidence_threshold}% — watch only"
        )

    entry = close
    stop = target = None
    sl_pct = tp_pct = None
    if take and direction == "LONG":
        stop = entry - cfg.sl_atr_mult * atr_last
        target = entry + cfg.tp_atr_mult * atr_last
        if g > entry:
            target = max(target, g)
    elif take and direction == "SHORT":
        stop = entry + cfg.sl_atr_mult * atr_last
        target = entry - cfg.tp_atr_mult * atr_last
        if g < entry:
            target = min(target, g)

    if stop and target and entry > 0:
        sl_pct, tp_pct = sl_tp_pct(direction, entry, stop, target)
        if sl_pct and tp_pct and (tp_pct / sl_pct) < cfg.rr_min:
            reasons.append(f"R:R below {cfg.rr_min:.1f} — treat as watch / size small")
            take = False

    hold = hold_for_tf(tf, "swing" if tf in ("1d", "1w", "1wk") else "intraday")
    plan = make_trade_plan(
        direction=direction if take else "—",
        timeframe=tf,
        stop_loss_pct=round(sl_pct or 0, 2),
        take_profit_pct=round(tp_pct or 0, 2),
        confidence_pct=confidence,
        style="swing",
        exit_rule=(
            "Traffic Light: invalidate if stack unwinds against the thesis before target. "
            "Entry is next-session open after a confirmed close."
        ),
        max_hold_exit=f"Swing hold typical weeks–months ({hold}); re-check stack weekly.",
    )

    plain = verdict
    if take:
        plain += f" Suggested SL≈{sl_pct}% · TP≈{tp_pct}% (ATR-based; adjust to structure)."

    chart = _build_chart_data(work, max_bars=cfg.chart_bars)
    sma_levels = [
        {"label": f"SMA{cfg.sma_red} (Red)", "price": round(r, 6), "color": "#ef4444", "key": "sma_red"},
        {"label": f"SMA{cfg.sma_yellow} (Yellow)", "price": round(y, 6), "color": "#eab308", "key": "sma_yellow"},
        {"label": f"SMA{cfg.sma_green} (Green)", "price": round(g, 6), "color": "#22c55e", "key": "sma_green"},
    ]

    score_dict = {"total": confidence, "reasons": reasons}

    out.update({
        "timeframe": tf,
        "ltp": round(close, 6),
        "bars": len(work),
        "take_trade": take,
        "signal": signal,
        "direction": direction if direction in ("LONG", "SHORT") else "NONE",
        "verdict": verdict,
        "plain_english": plain,
        "confidence_pct": confidence,
        "sl_pct": sl_pct,
        "tp_pct": tp_pct,
        "entry_price": round(entry, 6) if take else None,
        "stop_price": round(stop, 6) if take and stop else None,
        "target_price": round(target, 6) if take and target else None,
        "trade_plan": {**plan, "holding_period": hold},
        "reasons": reasons[:10],
        "trade_suggestion": {
            "action": "BUY" if take and direction == "LONG" else "SELL" if take and direction == "SHORT" else "WAIT",
            "side": direction if take else "WAIT",
            "confidence_pct": confidence,
            "sl_pct": sl_pct,
            "tp_pct": tp_pct,
            "entry_price": round(entry, 6) if take else None,
            "stop_price": round(stop, 6) if take and stop else None,
            "target_price": round(target, 6) if take and target else None,
            "plain_english": plain,
            "reasons": reasons[:6],
            "action_label": (
                "BUY next morning — traffic light" if take and direction == "LONG"
                else "SELL next morning — traffic light" if take and direction == "SHORT"
                else "WAIT — traffic light"
            ),
        },
        "stack": {
            "buy_stack": buy_stack,
            "sell_stack": sell_stack,
            "label": stack_label,
            "price_below_all": price_below_all,
            "price_above_all": price_above_all,
        },
        "smas": {
            "green_20": round(g, 6),
            "yellow_50": round(y, 6),
            "red_200": round(r, 6),
        },
        "sma_levels": sma_levels,
        "chart_data": chart,
        "chart_series": [
            {"key": "sma_red", "label": "SMA200 (Red)", "color": "#ef4444"},
            {"key": "sma_yellow", "label": "SMA50 (Yellow)", "color": "#eab308"},
            {"key": "sma_green", "label": "SMA20 (Green)", "color": "#22c55e"},
        ],
        "further_analysis_applied": list(cfg.further_analysis or []),
        "trend_strength": fa_detail,
        "score_breakdown": score_dict,
        "large_cap_note": (
            "Video guidance: apply primarily to large-cap / blue-chip names. "
            "Small or weak stocks may dip under the traffic light and never recover."
        ),
    })
    return out


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: TrafficLightConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or TrafficLightConfig()
    results: list[dict[str, Any]] = []
    for t in tickers:
        try:
            results.append(
                analyze_ticker(t, market, cfg=cfg, groww_token=groww_token, exchange=exchange)
            )
        except Exception as exc:
            logger.exception("Traffic Light failed for %s", t)
            results.append({"ticker": t, "strategy": STRATEGY_ID, "error": str(exc)[:240]})

    actionable = [r for r in results if r.get("take_trade")]
    return {
        "strategy": STRATEGY_ID,
        "strategy_label": STRATEGY_NAME,
        "youtube": YOUTUBE_URL,
        "how_it_works": HOW_IT_WORKS,
        "timeframe": cfg.timeframe,
        "config": {
            "sma_green": cfg.sma_green,
            "sma_yellow": cfg.sma_yellow,
            "sma_red": cfg.sma_red,
            "further_analysis": list(cfg.further_analysis or []),
            "lookback_bars": cfg.lookback_bars,
        },
        "further_analysis_options": FURTHER_ANALYSIS_OPTIONS,
        "results": results,
        "entry_count": len(actionable),
        "scanned": len(results),
        "ai_system_prompt": TRAFFIC_LIGHT_AI_SYSTEM,
        "disclaimer": (
            "Research / education only — not financial advice. Prefer large-caps; "
            "confirm with Trend & Strength / your own risk rules before acting."
        ),
    }


def build_traffic_light_ai_prompt(result: dict[str, Any]) -> str:
    extra = [
        f"Stack: {result.get('stack')}",
        f"SMAs: {result.get('smas')}",
        f"Signal: {result.get('signal')}",
        f"Trend & Strength: {result.get('trend_strength')}",
        f"Large-cap note: {result.get('large_cap_note')}",
    ]
    return build_pro_trade_ai_context(
        result,
        engine_label=STRATEGY_NAME,
        extra_lines=extra,
    )
