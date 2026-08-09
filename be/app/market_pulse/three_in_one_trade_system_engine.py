"""
three_in_one_trade_system_engine.py
-----------------------------------
3-in-1 Trade System — Mahesh Kaushik / FIRE in India style:

  DMA stack (50 / 100 / 200)  +  CAR (Cumulative Average Reversal)  +  Volume/turnover filter

Core method (as commonly documented on FIRE in India evolutions of the system):

1. Capital — 75% new buying / 25% reserve for SIP averaging; max holdings (e.g. 15);
   FIRE compounding: recycle booked profits into the pool, size buys from remaining slots.
2. Selection — prefer liquid/turnover names; price above SMA50, SMA100, SMA200;
   not more than max_pct above 200 DMA (default 10%); prioritize *closest* to 200 DMA.
3. Entry — CAR rising for N consecutive days (default 10; optimized impatient: 5–7).
   CAR = expanding average of closes from the most recent 52-week high day forward.
4. Exit — sell all at +6.28% above average purchase price.
5. Defense / SIP — if down ≥20% from buy, eligible to average 1/3 original size from reserve
   only when CAR rises again for N days and SIP gap (optimized: 30 calendar days) is met.

This scanner evaluates DMA + CAR + volume pillars per ticker and ranks BUY candidates
by proximity to the 200 DMA. It does not manage live broker portfolios.

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
    build_pro_trade_ai_context,
    pro_trade_ai_system,
)
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.smart_money_shared import hold_for_tf

logger = logging.getLogger(__name__)

STRATEGY_ID = "three_in_one_trade_system"
STRATEGY_NAME = "3-in-1 Trade System"
# Common FIRE-in-India / Mahesh references (evolving series — no single canonical URL required)
REFERENCE_NOTE = "Mahesh Kaushik 3-in-1 (DMA + CAR + Volume) · FIRE in India enhancements"

PROFIT_TARGET_PCT = 6.28
SIP_DRAWDOWN_PCT = 20.0

HOW_IT_WORKS = """
### How the 3-in-1 Trade System works

**Pillars:** DMA stack · CAR (Cumulative Average Reversal) · Volume / turnover discipline  
Tracked and refined on the FIRE in India channel around Mahesh Kaushik’s method.

#### 1. Capital allocation
- Split capital: **75% new buying** · **25% reserve** (averaging / SIP only).
- Cap holdings (e.g. **15 stocks**).
- **FIRE compounding (optimized):** recycle booked profits into the pool; size each new buy from
  remaining slots so you never exhaust capital before filling the book. Prefer this over aggressive
  “raise buy amount every 3 wins” if you risk running out of dry powder.

#### 2. Stock selection (scanner)
- Prefer **turnover** (volume × price) over raw volume — filters thin/penny names.
- Price **above SMA 50, 100, and 200**.
- Not more than **10% above the 200 DMA** (avoid chase / overextension).
- **Optimized:** among eligibles, buy those **closest to the 200 DMA** first (better margin of safety).
- Prefer a **custom quality watchlist** (100–200 strong names) when averaging 20% dips — fundamentals matter.

#### 3. Entry — CAR method
- From the day of the **52-week high**, compute the **cumulative (expanding) average** of closes.
- **Buy only when CAR has risen for N consecutive days** (classic **10**; impatient/backtested **5–7**).

#### 4. Exit
- Book **all units at +6.28%** above your **average purchase price**.

#### 5. Defense / SIP (on a fall)
- If down **≥20%** from buy price → eligible to average.
- Do **not** average blindly: wait for **CAR rising N days** again.
- Deploy **~1/3 of original** buy size from the **reserve**.
- **Optimized SIP gap: 30 calendar days** between SIPs (stricter than a 7-day gap) to avoid catching knives.

#### How to use this screen
1. Pick asset class + tickers (quality / liquid set recommended).
2. Set CAR days (10 safe / 5–7 earlier) and max % above 200 DMA.
3. Scan — actionable rows already pass DMA + CAR (+ volume pillar).
4. Results are sorted by **closeness to 200 DMA** among buys.
5. Place buys / SIPs / +6.28% exits on your broker; this app does not submit orders.

Research / education only — not financial advice.
""".strip()

RULES = [
    "Above SMA50, SMA100, and SMA200.",
    "Price ≤ max_pct above 200 DMA (default 10%).",
    "CAR (expanding avg from 52w high) rising for N consecutive days (default 10).",
    "Prefer closest-to-200-DMA among signals.",
    "Exit all at average + 6.28%.",
    "SIP only if ≥20% down, CAR rising again, and SIP gap (prefer 30 days) met — use 25% reserve, ~1/3 size.",
]

THREE_IN_ONE_AI_SYSTEM = pro_trade_ai_system(
    "3-in-1 Trade System",
    "DMA 50/100/200 stack + CAR rising from 52-week high + volume/turnover discipline. "
    "Buy when CAR rises N days and price is above all DMAs within 10% of 200 DMA; "
    "prioritize closest to 200 DMA; exit at +6.28% of average; SIP only after −20% with CAR re-trigger.",
)


@dataclass
class ThreeInOneConfig:
    timeframe: str = "1d"
    lookback_bars: int = 400
    sma_fast: int = 50
    sma_mid: int = 100
    sma_slow: int = 200
    max_pct_above_200: float = 10.0
    car_rising_days: int = 10  # classic 10; optimized impatient 5–7
    week52_bars: int = 252
    volume_sma_period: int = 20
    require_volume_breakout: bool = False  # soft by default; hard if True
    profit_target_pct: float = PROFIT_TARGET_PCT
    sip_drawdown_pct: float = SIP_DRAWDOWN_PCT
    sip_gap_days: int = 30  # optimized
    new_buy_capital_pct: float = 75.0
    reserve_capital_pct: float = 25.0
    max_holdings: int = 15
    min_bars: int = 220
    chart_bars: int = 160
    take_confidence_threshold: float = 62.0


def _r(x: float, n: int = 6) -> float:
    return round(float(x), n)


def _consecutive_true_from_end(mask: pd.Series) -> int:
    n = 0
    for v in reversed(mask.fillna(False).tolist()):
        if v:
            n += 1
        else:
            break
    return n


def compute_car_from_52w_high(
    close: pd.Series,
    high: pd.Series,
    *,
    week52_bars: int = 252,
) -> tuple[pd.Series, int, float]:
    """Expanding mean of closes from the most recent 52w high bar forward."""
    if close is None or close.empty:
        return pd.Series(dtype=float), -1, float("nan")
    n = len(close)
    w = min(week52_bars, n)
    window_high = high.iloc[-w:]
    peak_rel = int(window_high.values.argmax())
    start = n - w + peak_rel
    peak_price = float(high.iloc[start])
    car = pd.Series(index=close.index, dtype=float)
    segment = close.iloc[start:]
    car.iloc[start:] = segment.expanding(min_periods=1).mean().values
    return car, start, peak_price


def _build_chart(work: pd.DataFrame, *, max_bars: int) -> list[dict[str, Any]]:
    if work is None or work.empty:
        return []
    has_vol = "volume" in work.columns
    cols = ["sma50", "sma100", "sma200", "car"]
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
        for c in cols:
            if c in bar and pd.notna(bar.get(c)):
                row[c] = _r(float(bar[c]))
        rows.append(row)
    return rows


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: ThreeInOneConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or ThreeInOneConfig()
    tf = (cfg.timeframe or "1d").strip() or "1d"
    out: dict[str, Any] = {
        "ticker": ticker,
        "strategy": STRATEGY_ID,
        "strategy_label": STRATEGY_NAME,
        "error": None,
        "take_trade": False,
        "signal": "WAIT",
        "direction": "NONE",
        "verdict": "No 3-in-1 setup yet",
        "confidence_pct": None,
        "chart_data": [],
        "how_it_works": HOW_IT_WORKS,
        "rules": RULES,
        "reference": REFERENCE_NOTE,
    }

    try:
        df = fetch_data_for_gap_scan(
            ticker, tf, market, groww_token=groww_token, exchange=exchange, limit=cfg.lookback_bars,
        )
    except Exception as exc:
        out["error"] = f"Data fetch failed: {exc}"
        return out

    df = normalize_ohlcv(df)
    need = max(cfg.min_bars, cfg.sma_slow + 5, cfg.week52_bars // 2)
    if df is None or df.empty or len(df) < need:
        out["error"] = f"Insufficient {tf} data (need ≥{need} bars)."
        return out

    work = df.copy()
    work["sma50"] = work["close"].rolling(cfg.sma_fast, min_periods=cfg.sma_fast).mean()
    work["sma100"] = work["close"].rolling(cfg.sma_mid, min_periods=cfg.sma_mid).mean()
    work["sma200"] = work["close"].rolling(cfg.sma_slow, min_periods=cfg.sma_slow).mean()
    if "volume" in work.columns:
        work["vol_sma"] = work["volume"].rolling(cfg.volume_sma_period, min_periods=cfg.volume_sma_period).mean()
        work["turnover"] = work["volume"] * work["close"]
        work["turnover_sma"] = work["turnover"].rolling(cfg.volume_sma_period, min_periods=cfg.volume_sma_period).mean()
    else:
        work["vol_sma"] = pd.NA
        work["turnover"] = pd.NA
        work["turnover_sma"] = pd.NA

    car, peak_i, peak_px = compute_car_from_52w_high(
        work["close"], work["high"], week52_bars=cfg.week52_bars,
    )
    work["car"] = car
    work = work.dropna(subset=["sma50", "sma100", "sma200"])
    if len(work) < cfg.car_rising_days + 2:
        out["error"] = "Not enough bars after DMA warm-up."
        return out

    last = work.iloc[-1]
    close = float(last["close"])
    s50 = float(last["sma50"])
    s100 = float(last["sma100"])
    s200 = float(last["sma200"])
    car_now = float(last["car"]) if pd.notna(last.get("car")) else None
    vol = float(last["volume"]) if "volume" in last and pd.notna(last.get("volume")) else None
    vol_sma = float(last["vol_sma"]) if pd.notna(last.get("vol_sma")) else None
    turnover = float(last["turnover"]) if pd.notna(last.get("turnover")) else None
    turnover_sma = float(last["turnover_sma"]) if pd.notna(last.get("turnover_sma")) else None

    pct_above_200 = ((close / s200) - 1.0) * 100.0 if s200 > 0 else 999.0
    above_all_dma = close > s50 and close > s100 and close > s200
    # Must be above 200 already via above_all_dma; band is upper cap only
    within_extension = pct_above_200 <= cfg.max_pct_above_200

    car_series = work["car"].dropna()
    car_rising = car_series.diff() > 0
    car_streak = _consecutive_true_from_end(car_rising)
    car_ok = car_streak >= cfg.car_rising_days and car_now is not None

    vol_breakout = vol is not None and vol_sma is not None and vol > vol_sma
    turnover_ok = turnover is not None and turnover_sma is not None and turnover >= turnover_sma
    volume_pillar = vol_breakout or turnover_ok
    if vol is None:
        volume_pillar = True  # don't hard-fail crypto/commodity gaps without volume
        vol_note = "Volume unavailable — volume pillar skipped"
    else:
        vol_note = (
            f"Vol {_r(vol, 0)} vs SMA{cfg.volume_sma_period} {_r(vol_sma or 0, 0)}; "
            f"turnover {'≥' if turnover_ok else '<'} SMA"
        )

    checks = [
        {
            "id": "above_dma_stack",
            "label": "Above SMA 50 / 100 / 200",
            "pass": above_all_dma,
            "detail": f"Close {_r(close)} · 50={_r(s50)} · 100={_r(s100)} · 200={_r(s200)}",
            "weight": 18,
        },
        {
            "id": "near_200_dma",
            "label": f"≤ {cfg.max_pct_above_200:.0f}% above 200 DMA",
            "pass": above_all_dma and within_extension,
            "detail": f"{_r(pct_above_200, 2)}% above 200 DMA (closer is better)",
            "weight": 14,
        },
        {
            "id": "car_rising",
            "label": f"CAR rising ≥ {cfg.car_rising_days} days",
            "pass": car_ok,
            "detail": f"CAR streak {car_streak} day(s); CAR={_r(car_now) if car_now else '—'}",
            "weight": 22,
        },
        {
            "id": "volume_breakout",
            "label": "Volume / turnover confirmation",
            "pass": volume_pillar if cfg.require_volume_breakout else (volume_pillar or vol is None),
            "detail": vol_note,
            "weight": 10,
            "soft": not cfg.require_volume_breakout,
        },
    ]

    score = ConfidenceScore(30.0, "3-in-1 base")
    for ch in checks:
        if ch.get("soft") and not ch["pass"]:
            score.add(False, 0, ch["label"], f"Soft miss: {ch['label']} — {ch['detail']}")
        else:
            score.add(bool(ch["pass"]), float(ch["weight"]), f"{ch['label']}: {ch['detail']}")

    # Prefer closer to 200 DMA among passes
    if above_all_dma and within_extension:
        closeness_bonus = max(0.0, 8.0 - min(8.0, abs(pct_above_200)))
        if closeness_bonus > 0:
            score.add(True, closeness_bonus, f"Close to 200 DMA (+{closeness_bonus:.0f} safety bonus)")

    if car_streak >= cfg.car_rising_days + 3:
        score.add(True, 4.0, f"CAR streak extended ({car_streak} > {cfg.car_rising_days})")

    confidence, score_reasons = score.finalize()

    hard_ok = above_all_dma and within_extension and car_ok
    if cfg.require_volume_breakout:
        hard_ok = hard_ok and volume_pillar

    take = hard_ok and confidence >= cfg.take_confidence_threshold

    if take:
        signal, direction = "BULLISH", "LONG"
        status = "BUY_3IN1"
        verdict = (
            f"3-in-1 BUY — above 50/100/200 DMA, {_r(pct_above_200, 2)}% above 200 DMA, "
            f"CAR rising {car_streak} days (need {cfg.car_rising_days}). "
            f"Prioritize closest-to-200 among peers. Target +{cfg.profit_target_pct:.2f}% from average."
        )
    elif above_all_dma and within_extension and car_streak >= max(3, cfg.car_rising_days - 3):
        signal, direction = "WATCH", "LONG"
        status = "WATCH_CAR"
        take = False
        verdict = (
            f"Near entry — DMA stack OK ({_r(pct_above_200, 2)}% above 200) but CAR streak "
            f"{car_streak}/{cfg.car_rising_days}. Wait for continuous CAR rise."
        )
    elif above_all_dma and not within_extension:
        signal, direction = "WAIT", "NONE"
        status = "OVEREXTENDED"
        verdict = (
            f"Above DMAs but {_r(pct_above_200, 2)}% above 200 DMA (cap {cfg.max_pct_above_200:.0f}%). "
            "Skip — prefer names closer to the 200 DMA."
        )
    else:
        signal, direction = "WAIT", "NONE"
        status = "FILTERED"
        failed = [ch["label"] for ch in checks if not ch["pass"] and not ch.get("soft")]
        verdict = f"Filtered — missing: {', '.join(failed) if failed else 'DMA/CAR conditions'}."

    entry = close
    target = _r(close * (1 + cfg.profit_target_pct / 100.0))
    # Educational SIP level (from current as hypothetical buy)
    sip_trigger = _r(close * (1 - cfg.sip_drawdown_pct / 100.0))

    hold = hold_for_tf(tf)
    plan = make_trade_plan(
        direction="LONG" if take or direction == "LONG" else "—",
        timeframe=tf,
        stop_loss_pct=0.0,
        take_profit_pct=cfg.profit_target_pct,
        confidence_pct=confidence,
        style="swing",
        exit_rule=(
            f"3-in-1: sell ALL at average + {cfg.profit_target_pct:.2f}%. "
            f"No classic hard SL — defense is SIP after −{cfg.sip_drawdown_pct:.0f}% only with CAR re-trigger "
            f"and ≥{cfg.sip_gap_days}d gap, using the 25% reserve (~1/3 size)."
        ),
        max_hold_exit=f"Swing hold ({hold}); book at +{cfg.profit_target_pct:.2f}% of average.",
    )

    plain = verdict
    if take:
        plain += (
            f" Suggested exit from this print ≈ {_r(target)} (+{cfg.profit_target_pct:.2f}%). "
            f"If later −{cfg.sip_drawdown_pct:.0f}% to ≈ {_r(sip_trigger)}, wait for CAR+{cfg.car_rising_days}d "
            f"and {cfg.sip_gap_days}d gap before averaging from reserve."
        )

    chart = _build_chart(work, max_bars=cfg.chart_bars)
    levels = [
        {"label": "SMA50", "price": _r(s50), "color": "#38bdf8"},
        {"label": "SMA100", "price": _r(s100), "color": "#a78bfa"},
        {"label": "SMA200", "price": _r(s200), "color": "#f59e0b"},
    ]
    if take:
        levels.append({"label": f"TP +{cfg.profit_target_pct:.2f}%", "price": target, "color": "#34d399"})
    if car_now is not None:
        levels.append({"label": "CAR", "price": _r(car_now), "color": "#f472b6"})

    out.update({
        "timeframe": tf,
        "ltp": _r(close),
        "bars": len(work),
        "take_trade": take,
        "signal": signal,
        "direction": direction,
        "status": status,
        "verdict": verdict,
        "plain_english": plain,
        "confidence_pct": confidence,
        "rank_key_pct_above_200": _r(pct_above_200, 4),  # lower = better
        "sl_pct": None,
        "tp_pct": cfg.profit_target_pct,
        "entry_price": _r(entry) if take else None,
        "stop_price": None,
        "target_price": target if take else None,
        "no_stop_loss": True,
        "trade_plan": {**plan, "holding_period": hold, "no_stop_loss": True},
        "checks": checks,
        "metrics": {
            "sma50": _r(s50),
            "sma100": _r(s100),
            "sma200": _r(s200),
            "pct_above_200": _r(pct_above_200, 2),
            "car": _r(car_now) if car_now is not None else None,
            "car_streak_days": car_streak,
            "car_days_required": cfg.car_rising_days,
            "week52_high": _r(peak_px),
            "volume": _r(vol, 0) if vol is not None else None,
            "volume_sma": _r(vol_sma, 0) if vol_sma is not None else None,
            "turnover": _r(turnover, 0) if turnover is not None else None,
            "sip_trigger_from_ltp": sip_trigger,
            "profit_target_pct": cfg.profit_target_pct,
            "sip_gap_days": cfg.sip_gap_days,
        },
        "reasons": [f"{'✓' if ch['pass'] else '✗'} {ch['label']} — {ch['detail']}" for ch in checks],
        "trade_suggestion": {
            "action": "BUY" if take else "WAIT",
            "side": "LONG" if take else "WAIT",
            "confidence_pct": confidence,
            "sl_pct": None,
            "tp_pct": cfg.profit_target_pct,
            "entry_price": _r(entry) if take else None,
            "stop_price": None,
            "target_price": target if take else None,
            "plain_english": plain,
            "action_label": (
                "BUY — 3-in-1 (DMA + CAR)" if take
                else f"WAIT — CAR {car_streak}/{cfg.car_rising_days} · {status}"
            ),
        },
        "capital_hints": {
            "new_buy_pct": cfg.new_buy_capital_pct,
            "reserve_pct": cfg.reserve_capital_pct,
            "max_holdings": cfg.max_holdings,
            "sip_fraction_of_original": "1/3",
            "compounding": "FIRE compounding — recycle profits; size from remaining slots",
        },
        "chart_levels": levels,
        "chart_data": chart,
        "chart_series": [
            {"key": "sma50", "label": "SMA50", "color": "#38bdf8"},
            {"key": "sma100", "label": "SMA100", "color": "#a78bfa"},
            {"key": "sma200", "label": "SMA200", "color": "#f59e0b"},
            {"key": "car", "label": "CAR", "color": "#f472b6"},
        ],
        "score_breakdown": {"total": confidence, "reasons": score_reasons[:12]},
    })
    return out


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: ThreeInOneConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or ThreeInOneConfig()
    results: list[dict[str, Any]] = []
    for t in tickers:
        try:
            results.append(
                analyze_ticker(t, market, cfg=cfg, groww_token=groww_token, exchange=exchange)
            )
        except Exception as exc:
            logger.exception("3-in-1 failed for %s", t)
            results.append({"ticker": t, "strategy": STRATEGY_ID, "error": str(exc)[:240]})

    # Optimized ranking: actionable first, then closest to 200 DMA
    def sort_key(r: dict[str, Any]) -> tuple:
        if r.get("error"):
            return (2, 999.0, 0.0)
        take = 0 if r.get("take_trade") else 1
        dist = r.get("rank_key_pct_above_200")
        dist_f = float(dist) if dist is not None else 999.0
        return (take, dist_f, -float(r.get("confidence_pct") or 0))

    results.sort(key=sort_key)
    for i, r in enumerate(results):
        if isinstance(r, dict) and not r.get("error"):
            r["rank"] = i + 1

    actionable = [r for r in results if r.get("take_trade")]
    return {
        "strategy": STRATEGY_ID,
        "strategy_label": STRATEGY_NAME,
        "reference": REFERENCE_NOTE,
        "how_it_works": HOW_IT_WORKS,
        "rules": RULES,
        "timeframe": cfg.timeframe,
        "config": {
            "car_rising_days": cfg.car_rising_days,
            "max_pct_above_200": cfg.max_pct_above_200,
            "profit_target_pct": cfg.profit_target_pct,
            "sip_drawdown_pct": cfg.sip_drawdown_pct,
            "sip_gap_days": cfg.sip_gap_days,
            "new_buy_capital_pct": cfg.new_buy_capital_pct,
            "reserve_capital_pct": cfg.reserve_capital_pct,
            "max_holdings": cfg.max_holdings,
            "require_volume_breakout": cfg.require_volume_breakout,
        },
        "capital_playbook": {
            "new_buying": f"{cfg.new_buy_capital_pct:.0f}%",
            "reserve_for_sip": f"{cfg.reserve_capital_pct:.0f}%",
            "max_holdings": cfg.max_holdings,
            "exit": f"+{cfg.profit_target_pct:.2f}% of average — sell all",
            "sip": (
                f"After −{cfg.sip_drawdown_pct:.0f}%: CAR rising {cfg.car_rising_days}d again, "
                f"gap ≥{cfg.sip_gap_days} calendar days, deploy ~1/3 original from reserve"
            ),
            "compounding": "FIRE compounding — add profits to pool; size buys from remaining slots",
            "selection_tip": "Among BUY signals, prefer lowest % above 200 DMA (already ranked)",
        },
        "results": results,
        "entry_count": len(actionable),
        "scanned": len(results),
        "ai_system_prompt": THREE_IN_ONE_AI_SYSTEM,
        "disclaimer": (
            "Research / education only — not financial advice. Prefer fundamentally strong liquid names "
            "when averaging 20% dips. Scanner ranks by closeness to 200 DMA among signals."
        ),
    }


def build_three_in_one_ai_prompt(result: dict[str, Any]) -> str:
    extra = [
        f"Status: {result.get('status')}",
        f"Rank: {result.get('rank')}",
        f"Metrics: {result.get('metrics')}",
        f"Checks: {result.get('checks')}",
        f"Capital hints: {result.get('capital_hints')}",
    ]
    return build_pro_trade_ai_context(
        result,
        engine_label=STRATEGY_NAME,
        extra_lines=extra,
    )
