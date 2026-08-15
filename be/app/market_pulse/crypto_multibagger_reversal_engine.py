"""
crypto_multibagger_reversal_engine.py
-------------------------------------
Crypto Trading · Multibagger Reversal (SHORT)

Universe: CoinDCX USDT pairs with |24h %| ≥ threshold (default 40%).
Chart: 5m · EMA (default 280) · SuperTrend (10, 3)

SHORT when close < EMA AND SuperTrend flips RED.
SL: exit when SuperTrend turns GREEN (reference stop = ST line).
Target: −10% from entry (10% of price).

Research / education only — not financial advice.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.market_pulse.coindcx_24h_volatility_engine import fetch_change_24h
from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.pro_trade_shared import pack_trade_setup, sl_tp_pct
from app.market_pulse.run_summary import make_trade_plan
from app.market_pulse.smart_wave_crypto_engine import multibagger_signals, multibagger_trade

logger = logging.getLogger(__name__)

STRATEGY_ID = "crypto_multibagger_reversal"
STRATEGY_NAME = "Multibagger Reversal"
MARKET = "CoinDCX Futures"

HOW_IT_WORKS = """
### Multibagger Reversal (Crypto SHORT)

1. Screen CoinDCX USDT pairs that moved **≥40%** (abs) in the last 24 hours.
2. On the **5m** chart: plot **EMA 280** (or 300) + **SuperTrend (10, 3)**.
3. **SHORT** when price is **below** the EMA **and** SuperTrend **turns RED**.
4. **Stop / exit:** when SuperTrend turns **GREEN** (reference SL = SuperTrend line).
5. **Target:** **10%** of the coin price (entry × 0.90).
"""

RULES = [
    "Universe: |24h % change| ≥ threshold (default 40%) on CoinDCX USDT futures.",
    "TF: 5m · EMA 280 (configurable 300) · SuperTrend period 10, multiplier 3.",
    "SHORT only: close < EMA AND fresh SuperTrend RED flip.",
    "SL / exit: SuperTrend turns GREEN · reference stop at ST line.",
    "Target: −10% from entry.",
]

PRO_TIPS = [
    "Best after parabolic pumps — fade exhaustion, don't fight a fresh green ST.",
    "Prefer liquid pairs (higher 24h volume) to reduce slippage on shorts.",
    "If price is already deep below EMA without a fresh ST flip, wait for the flip.",
]


@dataclass
class MultibaggerReversalConfig:
    move_threshold_pct: float = 40.0
    timeframe: str = "5m"
    ema_period: int = 280  # indicators list; set 300 to match alternate entry wording
    st_period: int = 10
    st_mult: float = 3.0
    target_pct: float = 10.0
    lookback_bars: int = 400
    min_bars: int = 300
    chart_bars: int = 120
    max_candidates: int = 40
    take_confidence_threshold: float = 55.0


def _r(x: float, n: int = 6) -> float:
    return round(float(x), n)


def find_movers(
    *,
    threshold_pct: float = 40.0,
    max_candidates: int = 40,
) -> list[dict[str, Any]]:
    """CoinDCX pairs with |24h %| ≥ threshold, ranked by |move| desc."""
    rows = fetch_change_24h()
    out: list[dict[str, Any]] = []
    for row in rows:
        pct = row.get("percent_change")
        if pct is None:
            continue
        if abs(float(pct)) < float(threshold_pct):
            continue
        out.append(row)
    out.sort(key=lambda r: abs(float(r.get("percent_change") or 0)), reverse=True)
    return out[: max(1, int(max_candidates))]


def _pct_map() -> dict[str, dict[str, Any]]:
    return {str(r.get("ticker")): r for r in fetch_change_24h() if r.get("ticker")}


def _build_chart(work: pd.DataFrame, *, ema_period: int, max_bars: int) -> list[dict[str, Any]]:
    if work is None or work.empty:
        return []
    ema_key = f"ema{ema_period}"
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
        if ema_key in bar and pd.notna(bar.get(ema_key)):
            row[ema_key] = _r(float(bar[ema_key]), 6)
            row["ema"] = row[ema_key]
        if "supertrend" in bar and pd.notna(bar.get("supertrend")):
            row["supertrend"] = _r(float(bar["supertrend"]), 6)
        rows.append(row)
    return rows


def analyze_ticker(
    ticker: str,
    *,
    cfg: MultibaggerReversalConfig | None = None,
    mover: dict[str, Any] | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or MultibaggerReversalConfig()
    pct_24h = None
    if mover and mover.get("percent_change") is not None:
        pct_24h = float(mover["percent_change"])

    out: dict[str, Any] = {
        "ticker": ticker,
        "timeframe": cfg.timeframe,
        "strategy": STRATEGY_ID,
        "strategy_label": STRATEGY_NAME,
        "signal": "WAIT",
        "direction": "NONE",
        "take_trade": False,
        "pct_24h": pct_24h,
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

    if int(cfg.ema_period) == 280 and int(cfg.st_period) == 10 and float(cfg.st_mult) == 3.0:
        work = multibagger_signals(df)
        ema_col = "ema280"
    else:
        from app.market_pulse.smart_wave_crypto_engine import supertrend_signals

        work = df.copy()
        ema_col = f"ema{int(cfg.ema_period)}"
        work[ema_col] = work["close"].ewm(span=int(cfg.ema_period), adjust=False).mean()
        work = supertrend_signals(work, period=int(cfg.st_period), mult=float(cfg.st_mult))
        work["mb_signal"] = 0
        work.loc[(work["close"] < work[ema_col]) & (work["signal"] == -1), "mb_signal"] = -1

    if ema_col != f"ema{cfg.ema_period}":
        work[f"ema{cfg.ema_period}"] = work[ema_col]
    work["ema"] = work[ema_col]

    i = len(work) - 1
    price = float(work["close"].iloc[i])
    ema_v = float(work[ema_col].iloc[i]) if pd.notna(work[ema_col].iloc[i]) else None
    st_v = float(work["supertrend"].iloc[i]) if pd.notna(work["supertrend"].iloc[i]) else None
    st_dir = int(work["st_direction"].iloc[i]) if pd.notna(work["st_direction"].iloc[i]) else 0
    below_ema = ema_v is not None and price < ema_v
    st_red = st_dir == -1
    st_green = st_dir == 1
    fresh_red = int(work["mb_signal"].iloc[i]) == -1
    if not fresh_red:
        tail = work["mb_signal"].iloc[max(0, i - 2) : i + 1]
        if bool((tail == -1).any()):
            fresh_red = True

    move_ok = pct_24h is not None and abs(pct_24h) >= float(cfg.move_threshold_pct)

    checks = [
        {
            "id": "move_24h",
            "label": f"|24h| ≥ {cfg.move_threshold_pct:g}%",
            "passed": move_ok,
            "detail": f"24h {pct_24h:+.2f}%" if pct_24h is not None else "24h unknown",
        },
        {
            "id": "below_ema",
            "label": f"Close below EMA {cfg.ema_period}",
            "passed": below_ema,
            "detail": f"price {_r(price)} · EMA {_r(ema_v) if ema_v is not None else '—'}",
        },
        {
            "id": "st_red_flip",
            "label": "SuperTrend turns RED",
            "passed": fresh_red,
            "detail": (
                "fresh RED flip"
                if fresh_red
                else ("ST currently RED — wait for fresh flip" if st_red else "ST GREEN — no short")
            ),
        },
    ]
    out["checks"] = checks
    out["ltp"] = _r(price)
    out["metrics"] = {
        "price": _r(price),
        "ema": _r(ema_v) if ema_v is not None else None,
        "ema_period": cfg.ema_period,
        "supertrend": _r(st_v) if st_v is not None else None,
        "st_direction": "RED" if st_red else ("GREEN" if st_green else "—"),
        "pct_24h": round(pct_24h, 2) if pct_24h is not None else None,
        "below_ema": below_ema,
        "fresh_st_red": fresh_red,
    }
    out["chart_data"] = _build_chart(work, ema_period=int(cfg.ema_period), max_bars=int(cfg.chart_bars))
    out["chart_series"] = [
        {"key": f"ema{cfg.ema_period}", "label": f"EMA {cfg.ema_period}", "color": "#fbbf24"},
        {"key": "supertrend", "label": "SuperTrend", "color": "#f43f5e" if st_red else "#34d399"},
    ]

    if not (move_ok and below_ema and fresh_red):
        why = [c["detail"] for c in checks if not c["passed"]]
        out["signal"] = "WATCH" if move_ok and below_ema else "WAIT"
        out["reason"] = "WAIT: " + ("; ".join(why) if why else "no SHORT confluence")
        out["plain_english"] = (
            f"{ticker} 5m: 24h {pct_24h:+.1f}% · "
            f"{'below' if below_ema else 'above'} EMA{cfg.ema_period} · "
            f"ST {'RED' if st_red else 'GREEN'}. {out['reason']}"
            if pct_24h is not None
            else out["reason"]
        )
        return out

    entry = price
    target = entry * (1.0 - float(cfg.target_pct) / 100.0)
    stop = float(st_v) if st_v is not None and st_v > entry else entry * 1.03
    sl_pct_v, tp_pct_v = sl_tp_pct("SHORT", entry, stop, target)
    confidence_pct = 58.0
    if abs(pct_24h or 0) >= 60:
        confidence_pct += 8
    if abs(pct_24h or 0) >= 80:
        confidence_pct += 6
    confidence_pct = min(88.0, confidence_pct)
    take = confidence_pct >= float(cfg.take_confidence_threshold)

    setup = pack_trade_setup(
        direction="SHORT",
        entry=entry,
        stop=stop,
        target=target,
        confidence_pct=confidence_pct,
        confidence_reasons=[
            f"24h {pct_24h:+.1f}%",
            f"Below EMA{cfg.ema_period}",
            "SuperTrend RED flip",
            f"Target −{cfg.target_pct:g}%",
        ],
        reason=f"Multibagger SHORT · 24h {pct_24h:+.1f}% · below EMA{cfg.ema_period} · ST RED",
        plain_english=(
            f"Short {ticker}: moved {pct_24h:+.1f}% in 24h, price under EMA{cfg.ema_period}, "
            f"SuperTrend just flipped red. Aim −{cfg.target_pct:g}% "
            f"({_r(target)}); exit if SuperTrend turns green (ref SL {_r(stop)})."
        ),
        timeframe=cfg.timeframe,
        grade="A" if confidence_pct >= 70 else "B",
        take_trade=take,
    )

    trade = multibagger_trade(work, i)
    trade["stoploss"] = _r(stop)
    trade["target"] = _r(target)
    trade["exit_rule"] = "Exit when SuperTrend turns GREEN"
    trade["ema_period"] = cfg.ema_period

    plan = make_trade_plan(
        direction="SHORT",
        timeframe=cfg.timeframe,
        stop_loss_pct=round(sl_pct_v or 0, 2),
        take_profit_pct=round(tp_pct_v or float(cfg.target_pct), 2),
        confidence_pct=confidence_pct,
        style="intraday",
        exit_rule=(
            f"Cover at −{cfg.target_pct:g}% ({_r(target)}). "
            f"Hard exit when SuperTrend turns GREEN (ref SL {_r(stop)})."
        ),
        max_hold_exit="Intraday fade — don't overnight a failed multibagger short without ST still red.",
    )

    out["chart_levels"] = [
        {"label": "Entry", "price": _r(entry), "color": "#38bdf8"},
        {"label": "SL (ST)", "price": _r(stop), "color": "#f43f5e"},
        {"label": "TP −10%", "price": _r(target), "color": "#34d399"},
    ]
    out.update({
        "take_trade": take,
        "direction": "SHORT",
        "signal": "BEARISH",
        "action": "SELL",
        "status": "take" if take else "setup_low_conf",
        "reason": setup["reason"],
        "entry_price": _r(entry),
        "stop_price": _r(stop),
        "target_price": _r(target),
        "sl_pct": sl_pct_v,
        "tp_pct": tp_pct_v or float(cfg.target_pct),
        "confidence_pct": confidence_pct,
        "grade": setup.get("grade"),
        "trade_plan": plan,
        "trade_setup": setup,
        "trade_suggestion": trade,
        "plain_english": setup["plain_english"],
        "pro_checklist": [
            f"|24h| ≥ {cfg.move_threshold_pct:g}%",
            f"5m close below EMA {cfg.ema_period}",
            "SuperTrend (10,3) turns RED",
            "Exit on SuperTrend GREEN",
            f"Target −{cfg.target_pct:g}% of price",
        ],
    })
    return out


def scan_universe(
    *,
    cfg: MultibaggerReversalConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
    tickers: list[str] | None = None,
) -> dict[str, Any]:
    """Scan 24h movers (or an explicit ticker list) for Multibagger SHORT setups."""
    cfg = cfg or MultibaggerReversalConfig()
    movers = find_movers(
        threshold_pct=float(cfg.move_threshold_pct),
        max_candidates=int(cfg.max_candidates),
    )
    all_pct = _pct_map()
    mover_by_ticker = {**all_pct, **{str(m.get("ticker")): m for m in movers}}

    if tickers:
        scan_list = list(dict.fromkeys(tickers))
    else:
        scan_list = [str(m["ticker"]) for m in movers]

    results: list[dict[str, Any]] = []

    def _one(t: str) -> dict[str, Any]:
        try:
            return analyze_ticker(
                t,
                cfg=cfg,
                mover=mover_by_ticker.get(t),
                groww_token=groww_token,
                exchange=exchange,
            )
        except Exception as exc:
            logger.exception("%s failed for %s", STRATEGY_NAME, t)
            return {
                "ticker": t,
                "timeframe": cfg.timeframe,
                "strategy": STRATEGY_ID,
                "error": str(exc)[:240],
                "signal": "WAIT",
                "take_trade": False,
                "pct_24h": (mover_by_ticker.get(t) or {}).get("percent_change"),
            }

    if not scan_list:
        return {
            "strategy": STRATEGY_ID,
            "strategy_label": STRATEGY_NAME,
            "how_it_works": HOW_IT_WORKS,
            "rules": RULES,
            "pro_tips": PRO_TIPS,
            "movers": movers,
            "results": [],
            "entry_count": 0,
            "scanned": 0,
            "error": f"No CoinDCX pairs with |24h| ≥ {cfg.move_threshold_pct:g}%",
            "disclaimer": "Research / education only — not financial advice.",
        }

    workers = min(8, max(1, len(scan_list)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_one, t): t for t in scan_list}
        for fut in as_completed(futs):
            results.append(fut.result())

    results.sort(
        key=lambda r: (
            0 if r.get("take_trade") else 1,
            0 if r.get("signal") == "BEARISH" else 1,
            -(abs(float(r.get("pct_24h") or 0))),
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
            "move_threshold_pct": cfg.move_threshold_pct,
            "timeframe": cfg.timeframe,
            "ema_period": cfg.ema_period,
            "st_period": cfg.st_period,
            "st_mult": cfg.st_mult,
            "target_pct": cfg.target_pct,
            "max_candidates": cfg.max_candidates,
        },
        "movers": movers,
        "mover_count": len(movers),
        "results": results,
        "entry_count": len(actionable),
        "scanned": len(results),
        "asset_class": "crypto",
        "market": MARKET,
        "currency": "$",
        "disclaimer": (
            "Research / education only — not financial advice. "
            "SHORT fade after ≥40% 24h move when 5m price < EMA and SuperTrend flips red; "
            "exit on ST green; target −10%."
        ),
    }
