"""
crypto_ema_crossover_engine.py
------------------------------
Crypto Trading · EMA Crossover

EMA 10 crosses ABOVE EMA 30 → LONG (BUY)
EMA 10 crosses BELOW EMA 30 → SHORT (SELL)

TF: 30m or 1h · Universe default: BTC, ETH, SOL, XRP, BNB
R:R 1:3–1:7 · SL: previous candle low/high · money risk ₹200

Research / education only — not financial advice.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.pro_trade_shared import pack_trade_setup, sl_tp_pct
from app.market_pulse.run_summary import make_trade_plan
from app.market_pulse.smart_wave_crypto_engine import (
    RISK_PER_TRADE_INR,
    TRADE_SIZE_INR,
    calculate_trade_risk,
    ema_crossover_signals,
)

logger = logging.getLogger(__name__)

STRATEGY_ID = "crypto_ema_crossover"
STRATEGY_NAME = "EMA Crossover"
MARKET = "CoinDCX Futures"

DEFAULT_COINS = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "BNB-USDT"]

HOW_IT_WORKS = """
### EMA Crossover (Crypto)

**How it works:** EMA 10 crosses **above** EMA 30 → **LONG**. EMA 10 crosses **below** EMA 30 → **SHORT**.

| Side | Entry |
|------|--------|
| **LONG** | EMA10 × **above** EMA30 → BUY |
| **SHORT** | EMA10 × **below** EMA30 → SELL |

**Timeframe:** 30m or 1h · **Coins:** BTC, ETH, SOL, XRP, BNB (default)

**R:R:** 1:3 to 1:7 (targets from structure risk)

**SL:** Previous candle low (long) / high (short) · size so risk ≈ **₹200**
"""

RULES = [
    "Fresh EMA10/EMA30 cross only (not already stacked without a cross).",
    "LONG: prior candle low as structure SL · SHORT: prior candle high.",
    "Targets at 3R / 5R / 7R (configurable min–max RR).",
    "Money risk ≈ ₹200 on leveraged notional.",
    "Default universe: BTC ETH SOL XRP BNB on CoinDCX.",
]

PRO_TIPS = [
    "Prefer crosses that hold for the next bar close — avoid one-tick whippy flips.",
    "On 1h the same rules apply with fewer signals and cleaner swings.",
    "If structure SL implies >₹200 risk at your size, reduce size — don't widen the stop blindly.",
]


@dataclass
class EmaCrossoverConfig:
    timeframe: str = "30m"  # 30m | 1h
    fast: int = 10
    slow: int = 30
    lookback_bars: int = 250
    min_bars: int = 50
    chart_bars: int = 120
    rr_min: float = 3.0
    rr_max: float = 7.0
    risk_inr: float = float(RISK_PER_TRADE_INR)
    margin_inr: float = float(TRADE_SIZE_INR)
    leverage: int = 5
    take_confidence_threshold: float = 55.0
    side: str = "both"
    default_tickers: list[str] = field(default_factory=lambda: list(DEFAULT_COINS))

    def __post_init__(self) -> None:
        tf = str(self.timeframe or "30m").lower()
        if tf in ("60m", "1hr", "60"):
            tf = "1h"
        if tf not in ("30m", "1h"):
            tf = "30m"
        self.timeframe = tf
        side = str(self.side or "both").lower()
        if side in ("buy", "long", "up"):
            side = "long"
        elif side in ("sell", "short", "down"):
            side = "short"
        elif side not in ("long", "short", "both"):
            side = "both"
        self.side = side
        if float(self.rr_min) < 1:
            self.rr_min = 3.0
        if float(self.rr_max) < float(self.rr_min):
            self.rr_max = float(self.rr_min)


def _r(x: float, n: int = 6) -> float:
    return round(float(x), n)


def _build_chart(work: pd.DataFrame, *, max_bars: int) -> list[dict[str, Any]]:
    if work is None or work.empty:
        return []
    tail = work.iloc[-max_bars:]
    rows: list[dict[str, Any]] = []
    for idx, bar in tail.iterrows():
        row: dict[str, Any] = {
            "time": str(idx),
            "open": _r(float(bar["open"])),
            "high": _r(float(bar["high"])),
            "low": _r(float(bar["low"])),
            "close": _r(float(bar["close"])),
            "volume": _r(float(bar["volume"]), 2) if "volume" in bar and pd.notna(bar.get("volume")) else None,
        }
        for k in ("ema10", "ema30"):
            if k in bar and pd.notna(bar.get(k)):
                row[k] = _r(float(bar[k]), 6)
        rows.append(row)
    return rows


def analyze_ticker(
    ticker: str,
    *,
    cfg: EmaCrossoverConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or EmaCrossoverConfig()
    out: dict[str, Any] = {
        "ticker": ticker,
        "timeframe": cfg.timeframe,
        "strategy": STRATEGY_ID,
        "strategy_label": STRATEGY_NAME,
        "signal": "WAIT",
        "direction": "NONE",
        "take_trade": False,
        "checks": [],
        "metrics": {},
        "pro_tips": PRO_TIPS[:3],
    }

    try:
        raw = fetch_data_for_gap_scan(
            ticker, cfg.timeframe, MARKET, groww_token, exchange, limit=int(cfg.lookback_bars),
        )
        df = normalize_ohlcv(raw)
    except Exception as exc:
        out["error"] = str(exc)[:240]
        return out

    if df is None or len(df) < int(cfg.min_bars):
        out["error"] = f"Need ≥{cfg.min_bars} {cfg.timeframe} bars; got {0 if df is None else len(df)}"
        return out

    if int(cfg.fast) == 10 and int(cfg.slow) == 30:
        work = ema_crossover_signals(df)
    else:
        work = df.copy()
        work["ema10"] = work["close"].ewm(span=int(cfg.fast), adjust=False).mean()
        work["ema30"] = work["close"].ewm(span=int(cfg.slow), adjust=False).mean()
        prev10 = work["ema10"].shift(1)
        prev30 = work["ema30"].shift(1)
        work["signal"] = 0
        work.loc[(work["ema10"] > work["ema30"]) & (prev10 <= prev30), "signal"] = 1
        work.loc[(work["ema10"] < work["ema30"]) & (prev10 >= prev30), "signal"] = -1

    i = len(work) - 1
    if i < 1:
        out["error"] = "Not enough bars for prior candle SL"
        return out

    # Prefer last-bar cross; accept within last 2 bars
    sig = int(work["signal"].iloc[i]) if pd.notna(work["signal"].iloc[i]) else 0
    sig_idx = i
    if sig == 0:
        for j in range(i, max(i - 2, 0) - 1, -1):
            s = int(work["signal"].iloc[j]) if pd.notna(work["signal"].iloc[j]) else 0
            if s != 0:
                sig, sig_idx = s, j
                break

    price = float(work["close"].iloc[i])
    ema10 = float(work["ema10"].iloc[i]) if pd.notna(work["ema10"].iloc[i]) else None
    ema30 = float(work["ema30"].iloc[i]) if pd.notna(work["ema30"].iloc[i]) else None
    stacked_bull = ema10 is not None and ema30 is not None and ema10 > ema30
    stacked_bear = ema10 is not None and ema30 is not None and ema10 < ema30

    want_long = sig == 1 and cfg.side in ("long", "both")
    want_short = sig == -1 and cfg.side in ("short", "both")

    checks = [
        {
            "id": "cross",
            "label": f"EMA{cfg.fast} × EMA{cfg.slow} fresh cross",
            "passed": sig != 0,
            "detail": (
                f"bullish cross → LONG"
                if sig == 1
                else f"bearish cross → SHORT"
                if sig == -1
                else (
                    f"stacked {'bull' if stacked_bull else 'bear' if stacked_bear else '—'} — wait for fresh cross"
                )
            ),
        },
        {
            "id": "side",
            "label": "Side filter",
            "passed": want_long or want_short or sig == 0,
            "detail": f"side={cfg.side}",
        },
    ]
    out["checks"] = checks
    out["ltp"] = _r(price)
    out["metrics"] = {
        "price": _r(price),
        "ema10": _r(ema10) if ema10 is not None else None,
        "ema30": _r(ema30) if ema30 is not None else None,
        "stacked": "bull" if stacked_bull else ("bear" if stacked_bear else "—"),
        "rr_min": cfg.rr_min,
        "rr_max": cfg.rr_max,
        "risk_inr": cfg.risk_inr,
    }
    out["chart_data"] = _build_chart(work, max_bars=int(cfg.chart_bars))
    out["chart_series"] = [
        {"key": "ema10", "label": f"EMA {cfg.fast}", "color": "#34d399"},
        {"key": "ema30", "label": f"EMA {cfg.slow}", "color": "#fbbf24"},
    ]

    if not want_long and not want_short:
        out["signal"] = "WATCH" if stacked_bull or stacked_bear else "WAIT"
        out["reason"] = "WAIT: " + checks[0]["detail"]
        out["plain_english"] = f"{ticker} {cfg.timeframe}: {out['reason']}"
        return out

    is_long = want_long
    direction = "LONG" if is_long else "SHORT"
    entry = float(work["close"].iloc[sig_idx])
    prev = work.iloc[sig_idx - 1]
    # Structure SL: previous candle low (long) / high (short)
    if is_long:
        stop = float(prev["low"])
        if stop >= entry:
            stop = entry * 0.995
        risk = entry - stop
        t1 = entry + risk * float(cfg.rr_min)
        t2 = entry + risk * min(5.0, float(cfg.rr_max))
        t3 = entry + risk * float(cfg.rr_max)
    else:
        stop = float(prev["high"])
        if stop <= entry:
            stop = entry * 1.005
        risk = stop - entry
        t1 = entry - risk * float(cfg.rr_min)
        t2 = entry - risk * min(5.0, float(cfg.rr_max))
        t3 = entry - risk * float(cfg.rr_max)

    money = calculate_trade_risk(
        entry, stop, margin_inr=float(cfg.margin_inr), leverage=int(cfg.leverage),
    )
    # If structure risk exceeds ₹200 at default size, flag — still use structure SL
    within = bool(money.get("within_limit", True))
    if not within:
        # Prefer structure SL but note size reduction
        pass

    sl_pct_v, tp_pct_v = sl_tp_pct(direction, entry, stop, t1)
    conf = 60.0
    conf += 8 if within else -4
    conf += 6 if abs(float(cfg.rr_min) - 3) < 0.01 else 4
    conf = min(85.0, max(40.0, conf))
    take = conf >= float(cfg.take_confidence_threshold)

    setup = pack_trade_setup(
        direction=direction,
        entry=entry,
        stop=stop,
        target=t1,
        confidence_pct=conf,
        confidence_reasons=[
            f"EMA{cfg.fast}/{cfg.slow} fresh cross",
            f"Structure SL (prev candle {'low' if is_long else 'high'})",
            f"RR 1:{cfg.rr_min:g}–1:{cfg.rr_max:g}",
            f"Money risk ≈ ₹{cfg.risk_inr:g}",
        ],
        reason=f"{'BUY' if is_long else 'SELL'} on EMA{cfg.fast}×EMA{cfg.slow} · 1:{cfg.rr_min:g}+ RR",
        plain_english=(
            f"{'Buy' if is_long else 'Sell'} {ticker} on {cfg.timeframe}: "
            f"EMA{cfg.fast} crossed {'above' if is_long else 'below'} EMA{cfg.slow}. "
            f"SL at previous candle {'low' if is_long else 'high'} ({_r(stop)}); "
            f"targets 1:{cfg.rr_min:g} / mid / 1:{cfg.rr_max:g}. Size for ≈₹{cfg.risk_inr:g} risk."
        ),
        timeframe=cfg.timeframe,
        grade="A" if conf >= 70 and within else "B",
        take_trade=take,
    )
    setup["target2_price"] = _r(t2)
    setup["target3_price"] = _r(t3)

    plan = make_trade_plan(
        direction=direction,
        timeframe=cfg.timeframe,
        stop_loss_pct=round(sl_pct_v or 0, 2),
        take_profit_pct=round(tp_pct_v or 0, 2),
        confidence_pct=conf,
        style="intraday",
        exit_rule=(
            f"SL previous candle {'low' if is_long else 'high'} ({_r(stop)}). "
            f"T1 1:{cfg.rr_min:g} ({_r(t1)}); T2 {_r(t2)}; T3 1:{cfg.rr_max:g} ({_r(t3)}). "
            f"Invalidate on opposite EMA re-cross. Size ≈₹{cfg.risk_inr:g} risk."
        ),
        max_hold_exit=f"Typical {cfg.timeframe} swing; trail under/over EMA{cfg.fast} after T1.",
    )

    out["chart_levels"] = [
        {"label": "Entry", "price": _r(entry), "color": "#38bdf8"},
        {"label": "SL", "price": _r(stop), "color": "#f43f5e"},
        {"label": f"T1 1:{cfg.rr_min:g}", "price": _r(t1), "color": "#34d399"},
        {"label": f"T3 1:{cfg.rr_max:g}", "price": _r(t3), "color": "#a78bfa"},
    ]
    out.update({
        "take_trade": take,
        "direction": direction,
        "signal": "BULLISH" if is_long else "BEARISH",
        "action": "BUY" if is_long else "SELL",
        "status": "take" if take else "setup_low_conf",
        "reason": setup["reason"],
        "entry_price": _r(entry),
        "stop_price": _r(stop),
        "target_price": _r(t1),
        "target2_price": _r(t2),
        "target3_price": _r(t3),
        "sl_pct": sl_pct_v,
        "tp_pct": tp_pct_v,
        "rr": float(cfg.rr_min),
        "confidence_pct": conf,
        "grade": setup.get("grade"),
        "trade_plan": plan,
        "trade_setup": setup,
        "risk": money,
        "money_plan": {
            "sl_inr": cfg.risk_inr,
            "rr_min": cfg.rr_min,
            "rr_max": cfg.rr_max,
            "within_limit": within,
            "risk_inr_est": money.get("risk_inr"),
        },
        "trade_suggestion": {
            "action": "BUY" if is_long else "SELL",
            "entry": _r(entry),
            "stop": _r(stop),
            "target": _r(t1),
            "target2": _r(t2),
            "target3": _r(t3),
            "rr": f"1:{cfg.rr_min:g}–1:{cfg.rr_max:g}",
        },
        "plain_english": setup["plain_english"],
        "pro_checklist": [
            f"EMA{cfg.fast} crosses {'above' if is_long else 'below'} EMA{cfg.slow}",
            f"SL = previous candle {'low' if is_long else 'high'}",
            f"Targets 1:{cfg.rr_min:g} → 1:{cfg.rr_max:g}",
            f"Size for ≈₹{cfg.risk_inr:g} fixed risk",
            f"TF {cfg.timeframe} · major coins preferred",
        ],
    })
    return out


def scan_universe(
    *,
    cfg: EmaCrossoverConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
    tickers: list[str] | None = None,
) -> dict[str, Any]:
    cfg = cfg or EmaCrossoverConfig()
    scan_list = list(dict.fromkeys(tickers)) if tickers else list(cfg.default_tickers)

    results: list[dict[str, Any]] = []

    def _one(t: str) -> dict[str, Any]:
        try:
            return analyze_ticker(t, cfg=cfg, groww_token=groww_token, exchange=exchange)
        except Exception as exc:
            logger.exception("%s failed for %s", STRATEGY_NAME, t)
            return {
                "ticker": t,
                "timeframe": cfg.timeframe,
                "strategy": STRATEGY_ID,
                "error": str(exc)[:240],
                "signal": "WAIT",
                "take_trade": False,
            }

    if not scan_list:
        return {
            "strategy": STRATEGY_ID,
            "strategy_label": STRATEGY_NAME,
            "how_it_works": HOW_IT_WORKS,
            "rules": RULES,
            "pro_tips": PRO_TIPS,
            "results": [],
            "entry_count": 0,
            "scanned": 0,
            "error": "No tickers",
            "disclaimer": "Research / education only — not financial advice.",
        }

    workers = min(5, max(1, len(scan_list)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_one, t): t for t in scan_list}
        for fut in as_completed(futs):
            results.append(fut.result())

    results.sort(
        key=lambda r: (
            0 if r.get("take_trade") else 1,
            0 if r.get("signal") in ("BULLISH", "BEARISH") else 1,
            -(float(r.get("confidence_pct") or 0)),
        )
    )
    actionable = [r for r in results if r.get("take_trade")]
    return {
        "strategy": STRATEGY_ID,
        "strategy_label": STRATEGY_NAME,
        "how_it_works": HOW_IT_WORKS,
        "rules": RULES,
        "pro_tips": PRO_TIPS,
        "config": {
            "timeframe": cfg.timeframe,
            "fast": cfg.fast,
            "slow": cfg.slow,
            "rr_min": cfg.rr_min,
            "rr_max": cfg.rr_max,
            "risk_inr": cfg.risk_inr,
            "side": cfg.side,
            "default_tickers": cfg.default_tickers,
        },
        "results": results,
        "entry_count": len(actionable),
        "scanned": len(results),
        "asset_class": "crypto",
        "market": MARKET,
        "currency": "$",
        "disclaimer": (
            "Research / education only — not financial advice. "
            "EMA10×EMA30 on 30m/1h · prev-candle SL · 1:3–1:7 targets · ₹200 risk sizing."
        ),
    }
