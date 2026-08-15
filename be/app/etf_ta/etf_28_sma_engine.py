"""
etf_28_sma_engine.py
--------------------
ETF 28 SMA Momentum Strategy (FIRE in India).

Rules (from the channel videos):
  1. Capital: 30% averaging reserve; 70% ÷ max ETFs = initial buy size.
     Trade near close (after ~3:15 PM IST).
  2. Entry: wait for *two consecutive* daily closes above 28 SMA; buy on day 2.
     Cap new buys at 4 ETFs / day. Require ≥1 year history.
  3. Exit (FIFO block): two consecutive closes below 28 SMA AND profit ≥ 3.14%.
     If breakdown but profit < 3.14% (or loss) → hold.
     Fast momentum: if >18% in ~1 month, sell on first red candle.
  4. Averaging: only on a fresh 2-day close above 28 SMA, and only if price is
     ≥5% below last purchase. Amount = (fall% / 2) × (initial_buy / 10).
  5. FIFO vs LIFO: FIFO sells the whole block on breakdown+target;
     LIFO can sell the latest cheap lot at +3.14% on a down-close;
     when capital is exhausted, LIFO aggressively frees lots >3.14% on a dip.

Research / education only — not financial advice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd

from app.etf_ta.etf_28_sma_universe import (
    ETF_28_SMA_PRESETS,
    canonicalize_symbol,
    combined_universe,
    fire_28_sma_symbols,
)
from app.etf_ta.india_etf_universe import GROWW_INDIA_MARKET
from app.etf_ta.stf_shop_engine import fetch_stf_etf_data
from app.market_pulse.pro_trade_shared import build_pro_trade_ai_context, pro_trade_ai_system

logger = logging.getLogger(__name__)

STRATEGY_ID = "etf_28_sma"
STRATEGY_NAME = "ETF 28 SMA Momentum"

SMA_PERIOD = 28
MIN_HISTORY_BARS = 252  # ~1 trading year
PROFIT_TARGET_PCT = 3.14
AVG_MIN_DROP_PCT = 5.0
FAST_MOMENTUM_PCT = 18.0
FAST_MOMENTUM_BARS = 21  # ~1 month of sessions
MAX_NEW_BUYS_PER_DAY = 4
DEFAULT_AVERAGING_RESERVE_PCT = 30.0

SellMode = Literal["FIFO", "LIFO"]

HOW_IT_WORKS = """
### How ETF 28 SMA Momentum works

Track diversified ETFs with the **28-day SMA**. Hold winners while momentum lasts;
average down only on a fresh breakout that is ≥5% cheaper than your last buy.

| Step | Rule |
|------|------|
| Capital | Keep **30%** for averaging; split the other **70%** by max ETF slots |
| Entry | **Two consecutive** closes above 28 SMA → buy on day 2 (max **4** new ETFs/day) |
| Exit | Two closes below 28 SMA **and** profit ≥ **3.14%** — else hold |
| Fast exit | If >**18%** in ~1 month, sell on the first red candle |
| Average | Fresh 2-day breakout + ≥5% below last buy; amount = (fall%/2) × (initial/10) |
| Sell mode | **FIFO** = one block; **LIFO** = sell cheap lots early; free capital when exhausted |

**How to use this screen**
1. Choose a preset (FIRE list / ETF Shop / Combined) or pick tickers.
2. Set total capital, max ETF slots, and FIFO vs LIFO.
3. Optionally paste open lots (symbol, buy price, amount) for sell/average advice.
4. Scan near the close (~after 3:15 PM IST) — act on BUY / AVERAGE / SELL rows.
5. Prefer distinct underlyings (avoid overlapping Nifty/Bank ETFs).

Works on India NSE ETFs. Research only — not advice.
""".strip()

RULES = [
    "≥1 year of daily history required.",
    "Buy only after 2 consecutive closes above 28 SMA (day-2 entry).",
    "Max 4 new ETF buys per day.",
    "Sell (FIFO) only on 2 closes below 28 SMA and profit ≥ 3.14%.",
    "If breakdown but P&L < 3.14% → hold the diversified basket.",
    "Fast momentum (>18%/~month) → sell on first red candle.",
    "Average only on fresh 2-day breakout ≥5% below last buy.",
    "Avg amount = (fall% / 2) × (initial_buy / 10).",
    "LIFO: sell latest lot at ≥3.14% on a down-close; free capital if exhausted.",
    "Execute near market close (after ~3:15 PM IST).",
]

ETF_28_SMA_AI_SYSTEM = pro_trade_ai_system(
    STRATEGY_NAME,
    "28 SMA two-close breakout momentum on diversified ETFs; "
    "3.14% profit + SMA breakdown exits; 5% cheaper re-breakout averaging; "
    "FIFO block vs LIFO lot booking.",
)


@dataclass
class Etf28SmaConfig:
    total_capital: float = 500_000.0
    averaging_reserve_pct: float = DEFAULT_AVERAGING_RESERVE_PCT
    max_etfs: int = 20
    max_new_buys_per_day: int = MAX_NEW_BUYS_PER_DAY
    sma_period: int = SMA_PERIOD
    profit_target_pct: float = PROFIT_TARGET_PCT
    avg_min_drop_pct: float = AVG_MIN_DROP_PCT
    fast_momentum_pct: float = FAST_MOMENTUM_PCT
    fast_momentum_bars: int = FAST_MOMENTUM_BARS
    sell_mode: SellMode = "FIFO"
    capital_exhausted: bool = False
    lookback_bars: int = 400
    chart_bars: int = 120
    min_history_bars: int = MIN_HISTORY_BARS


@dataclass
class LotInput:
    symbol: str
    price: float
    amount: float
    units: float | None = None
    purchase_date: str | None = None
    lot_id: str | None = None


def _r(x: float, n: int = 4) -> float:
    return round(float(x), n)


def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).lower() for c in out.columns]
    for col in ("open", "high", "low", "close", "volume"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out.dropna(subset=["close"])


def capital_plan(cfg: Etf28SmaConfig) -> dict[str, Any]:
    total = max(float(cfg.total_capital), 0.0)
    reserve_pct = max(0.0, min(90.0, float(cfg.averaging_reserve_pct)))
    reserve = total * reserve_pct / 100.0
    initial_pool = total - reserve
    slots = max(1, int(cfg.max_etfs))
    initial_buy = initial_pool / slots
    return {
        "total_capital": _r(total, 2),
        "averaging_reserve_pct": _r(reserve_pct, 2),
        "averaging_reserve": _r(reserve, 2),
        "initial_pool": _r(initial_pool, 2),
        "max_etfs": slots,
        "initial_buy_amount": _r(initial_buy, 2),
        "tenth_of_initial": _r(initial_buy / 10.0, 2),
        "max_new_buys_per_day": int(cfg.max_new_buys_per_day),
        "note": "Execute decisions near the close (after ~3:15 PM IST).",
    }


def averaging_amount(fall_pct: float, initial_buy: float) -> float:
    """(fall% / 2) × (initial_buy / 10). Fall 8% → 4 × (initial/10)."""
    if fall_pct <= 0 or initial_buy <= 0:
        return 0.0
    return (fall_pct / 2.0) * (initial_buy / 10.0)


def quantity_for_amount(amount: float, price: float) -> int:
    """Whole units affordable at LTP for the rupee allocation."""
    if amount <= 0 or price <= 0:
        return 0
    return int(amount // price)


def _consec_above(close: pd.Series, sma: pd.Series, i: int) -> int:
    n = 0
    j = i
    while j >= 0:
        c, s = float(close.iloc[j]), float(sma.iloc[j])
        if not np.isfinite(c) or not np.isfinite(s) or c <= s:
            break
        n += 1
        j -= 1
    return n


def _consec_below(close: pd.Series, sma: pd.Series, i: int) -> int:
    n = 0
    j = i
    while j >= 0:
        c, s = float(close.iloc[j]), float(sma.iloc[j])
        if not np.isfinite(c) or not np.isfinite(s) or c >= s:
            break
        n += 1
        j -= 1
    return n


def _build_chart(work: pd.DataFrame, *, max_bars: int) -> list[dict[str, Any]]:
    if work is None or work.empty:
        return []
    has_vol = "volume" in work.columns
    tail = work.iloc[-max_bars:]
    rows: list[dict[str, Any]] = []
    for idx, bar in tail.iterrows():
        row: dict[str, Any] = {
            "time": str(idx)[:10],
            "open": _r(float(bar["open"])),
            "high": _r(float(bar["high"])),
            "low": _r(float(bar["low"])),
            "close": _r(float(bar["close"])),
            "volume": _r(float(bar["volume"]), 2) if has_vol and pd.notna(bar.get("volume")) else None,
        }
        if "sma28" in bar and pd.notna(bar.get("sma28")):
            row["sma28"] = _r(float(bar["sma28"]))
        rows.append(row)
    return rows


def _lot_units(lot: LotInput, price_fallback: float) -> float:
    if lot.units is not None and lot.units > 0:
        return float(lot.units)
    px = float(lot.price) if lot.price > 0 else price_fallback
    if px <= 0:
        return 0.0
    return float(lot.amount) / px


def _lots_for_symbol(holdings: list[LotInput], symbol: str) -> list[LotInput]:
    sym = canonicalize_symbol(symbol)
    return [h for h in holdings if canonicalize_symbol(h.symbol) == sym]


def _weighted_avg(lots: list[LotInput], price: float) -> tuple[float, float, float]:
    units = 0.0
    cost = 0.0
    for lot in lots:
        u = _lot_units(lot, price)
        if u <= 0:
            continue
        units += u
        cost += u * float(lot.price)
    if units <= 0:
        return 0.0, 0.0, 0.0
    return cost / units, units, cost


def analyze_etf(
    symbol: str,
    df: pd.DataFrame,
    *,
    cfg: Etf28SmaConfig,
    holdings: list[LotInput] | None = None,
    capital: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sym = canonicalize_symbol(symbol)
    cap = capital or capital_plan(cfg)
    initial_buy = float(cap["initial_buy_amount"])
    base: dict[str, Any] = {
        "ticker": sym,
        "strategy": STRATEGY_ID,
        "signal": "WAIT",
        "action": "WAIT",
        "take_trade": False,
        "status": "no_data",
        "checks": [],
        "metrics": {},
        "lots_advice": [],
        "trade_suggestion": {"action": "WAIT", "reason": ""},
    }

    if df is None or df.empty:
        base["error"] = "No price data"
        return base

    work = _normalize_df(df)
    if len(work) < cfg.min_history_bars:
        base["error"] = f"Need ≥{cfg.min_history_bars} daily bars (~1 year); got {len(work)}"
        base["status"] = "insufficient_history"
        base["checks"] = [{
            "id": "history", "label": "≥1 year history", "passed": False,
            "detail": f"{len(work)} bars",
        }]
        return base

    if len(work) < cfg.sma_period + 3:
        base["error"] = f"Need ≥{cfg.sma_period + 3} bars for SMA{cfg.sma_period}"
        return base

    work = work.copy()
    work["sma28"] = work["close"].rolling(cfg.sma_period).mean()
    work = work.dropna(subset=["sma28"])
    if len(work) < 3:
        base["error"] = "Not enough bars after SMA"
        return base

    close = work["close"]
    sma = work["sma28"]
    i = len(work) - 1
    price = float(close.iloc[-1])
    sma_now = float(sma.iloc[-1])
    prev_close = float(close.iloc[-2])
    above = price > sma_now
    days_above = _consec_above(close, sma, i)
    days_below = _consec_below(close, sma, i)
    pct_vs_sma = (price - sma_now) / sma_now * 100.0 if sma_now else 0.0

    look = min(cfg.fast_momentum_bars, len(work) - 1)
    month_ago = float(close.iloc[-1 - look]) if look > 0 else price
    month_pct = ((price - month_ago) / month_ago * 100.0) if month_ago > 0 else 0.0
    red_candle = price < prev_close
    buy_setup = days_above >= 2
    breakdown = days_below >= 2

    lots = _lots_for_symbol(holdings or [], sym)
    avg_px, total_units, total_cost = _weighted_avg(lots, price)
    last_buy = float(lots[-1].price) if lots else None
    pnl_pct = ((price - avg_px) / avg_px * 100.0) if avg_px > 0 else None
    held = total_units > 0

    checks: list[dict[str, Any]] = [
        {"id": "history", "label": "≥1 year history", "passed": True, "detail": f"{len(work)} bars"},
        {
            "id": "above_sma", "label": f"Close vs SMA{cfg.sma_period}",
            "passed": above, "detail": f"{_r(pct_vs_sma, 2)}% · {days_above}d above / {days_below}d below",
        },
        {
            "id": "buy_2day", "label": "2 consecutive closes above 28 SMA",
            "passed": buy_setup, "detail": f"{days_above} day(s) above",
        },
        {
            "id": "breakdown_2day", "label": "2 consecutive closes below 28 SMA",
            "passed": breakdown, "detail": f"{days_below} day(s) below",
        },
        {
            "id": "fast_mom", "label": f"Fast momentum >{cfg.fast_momentum_pct}% / ~month",
            "passed": month_pct >= cfg.fast_momentum_pct,
            "detail": f"{_r(month_pct, 2)}% over {look} sessions",
        },
    ]

    action = "WAIT"
    signal = "NEUTRAL"
    reason_parts: list[str] = []
    lots_advice: list[dict[str, Any]] = []
    suggested_amount = 0.0
    fall_pct = 0.0

    fast_exit = held and month_pct >= cfg.fast_momentum_pct and red_candle

    can_average = False
    if held and last_buy and last_buy > 0 and buy_setup:
        fall_pct = (last_buy - price) / last_buy * 100.0
        if fall_pct >= cfg.avg_min_drop_pct:
            can_average = True
            suggested_amount = averaging_amount(fall_pct, initial_buy)
            qty_hint = quantity_for_amount(suggested_amount, price)
            checks.append({
                "id": "avg_5pct", "label": f"≥{cfg.avg_min_drop_pct}% below last buy",
                "passed": True,
                "detail": (
                    f"fall {_r(fall_pct, 2)}% · avg ₹{_r(suggested_amount, 0)}"
                    + (f" · ~{qty_hint} qty" if qty_hint else "")
                ),
            })
        else:
            checks.append({
                "id": "avg_5pct", "label": f"≥{cfg.avg_min_drop_pct}% below last buy",
                "passed": False, "detail": f"fall {_r(fall_pct, 2)}% — ignore averaging",
            })

    if held and cfg.sell_mode == "LIFO" and lots:
        for idx, lot in enumerate(lots):
            lot_pnl = ((price - float(lot.price)) / float(lot.price) * 100.0) if lot.price > 0 else 0.0
            u = _lot_units(lot, price)
            sell_lot = False
            lot_reason = ""
            if lot_pnl >= cfg.profit_target_pct and red_candle:
                sell_lot = True
                lot_reason = (
                    f"LIFO: lot @ ₹{_r(lot.price)} is +{_r(lot_pnl, 2)}% and today is a red candle"
                )
            if cfg.capital_exhausted and lot_pnl >= cfg.profit_target_pct and (
                red_candle or price <= prev_close * 1.001
            ):
                sell_lot = True
                lot_reason = (
                    f"Capital exhausted — free lot @ ₹{_r(lot.price)} (+{_r(lot_pnl, 2)}%) on slight dip"
                )
            lots_advice.append({
                "lot_index": idx,
                "lot_id": lot.lot_id,
                "buy_price": _r(float(lot.price)),
                "amount": _r(float(lot.amount), 2),
                "units": _r(u, 4),
                "pnl_pct": _r(lot_pnl, 2),
                "sell": sell_lot,
                "reason": lot_reason or "Hold lot",
                "is_latest": idx == len(lots) - 1,
            })
        lifo_sells = [a for a in lots_advice if a.get("sell")]
        if lifo_sells:
            preferred = next((a for a in reversed(lots_advice) if a.get("sell")), lifo_sells[0])
            action = "SELL_LOT"
            signal = "TAKE_PROFIT"
            reason_parts.append(str(preferred["reason"]))

    if held and action == "WAIT":
        if fast_exit:
            action = "SELL"
            signal = "TAKE_PROFIT"
            reason_parts.append(
                f"Fast momentum {_r(month_pct, 1)}% in ~{look}d + first red candle — book before SMA lag erases gains"
            )
        elif breakdown:
            if pnl_pct is not None and pnl_pct >= cfg.profit_target_pct:
                action = "SELL"
                signal = "TAKE_PROFIT"
                reason_parts.append(
                    f"2 closes below SMA{cfg.sma_period} and P&L {_r(pnl_pct, 2)}% ≥ {cfg.profit_target_pct}% "
                    f"({'FIFO sell all' if cfg.sell_mode == 'FIFO' else 'block exit'})"
                )
            else:
                action = "HOLD"
                signal = "HOLD"
                reason_parts.append(
                    f"Breakdown vs SMA but P&L {_r(pnl_pct, 2) if pnl_pct is not None else 'n/a'}% "
                    f"< {cfg.profit_target_pct}% — golden rule: do not sell"
                )
        elif can_average:
            action = "AVERAGE"
            signal = "ADD"
            reason_parts.append(
                f"Fresh 2-day breakout {_r(fall_pct, 1)}% below last buy — average ~₹{_r(suggested_amount, 0)}"
            )
        else:
            action = "HOLD"
            signal = "HOLD" if above else "WATCH"
            reason_parts.append("Hold while above SMA / waiting for exit or average rules")

    if not held:
        if buy_setup:
            action = "BUY"
            signal = "BUY"
            suggested_amount = initial_buy
            reason_parts.append(
                f"2 consecutive closes above SMA{cfg.sma_period} — buy up to ₹{_r(initial_buy, 0)} "
                f"(slot 1/{cap['max_etfs']}; max {cfg.max_new_buys_per_day} new ETFs today)"
            )
        elif days_above == 1:
            action = "WATCH"
            signal = "WATCH"
            reason_parts.append("Day 1 above 28 SMA — wait for second close (do not buy yet)")
        else:
            action = "WAIT"
            signal = "WAIT"
            reason_parts.append("No 2-day close above 28 SMA")

    take = action in ("BUY", "AVERAGE", "SELL", "SELL_LOT")
    bar_date = work.index[-1]
    if hasattr(bar_date, "strftime"):
        bar_date = bar_date.strftime("%Y-%m-%d")

    suggested_qty = quantity_for_amount(suggested_amount, price) if suggested_amount else 0
    if action not in ("BUY", "AVERAGE", "BUY_DEFERRED"):
        suggested_qty = 0
    approx_cost = _r(suggested_qty * price, 2) if suggested_qty else None

    # Rewrite buy/average reason so qty is always visible next to the ₹ amount
    if action in ("BUY", "AVERAGE") and suggested_amount:
        qty_phrase = (
            f"qty {suggested_qty} @ ₹{_r(price)}"
            if suggested_qty > 0
            else f"qty 0 @ ₹{_r(price)} (allocation below 1 unit — raise capital/slot or pick cheaper ETF)"
        )
        if action == "BUY":
            reason_parts = [
                f"2 consecutive closes above SMA{cfg.sma_period} — buy up to ₹{_r(suggested_amount, 1)} · "
                f"{qty_phrase} (slot 1/{cap['max_etfs']}; max {cfg.max_new_buys_per_day} new ETFs today)"
            ]
        else:
            reason_parts = [
                f"Fresh 2-day breakout {_r(fall_pct, 1)}% below last buy — average ~₹{_r(suggested_amount, 0)} · {qty_phrase}"
            ]

    metrics = {
        "price": _r(price),
        "sma28": _r(sma_now),
        "pct_vs_sma": _r(pct_vs_sma, 2),
        "days_above_sma": days_above,
        "days_below_sma": days_below,
        "month_pct": _r(month_pct, 2),
        "red_candle": red_candle,
        "held": held,
        "avg_price": _r(avg_px) if held else None,
        "pnl_pct": _r(pnl_pct, 2) if pnl_pct is not None else None,
        "last_buy": _r(last_buy) if last_buy else None,
        "fall_from_last_buy_pct": _r(fall_pct, 2) if held and last_buy else None,
        "suggested_amount": _r(suggested_amount, 2) if suggested_amount else None,
        "suggested_qty": int(suggested_qty) if suggested_qty or action in ("BUY", "AVERAGE") else None,
        "approx_cost": approx_cost,
        "total_units": _r(total_units, 4) if held else None,
        "total_cost": _r(total_cost, 2) if held else None,
        "bars": len(work),
        "bar_date": str(bar_date),
        "sell_mode": cfg.sell_mode,
    }

    reason = " · ".join(reason_parts) if reason_parts else ""

    return {
        **base,
        "ltp": _r(price),
        "signal": signal,
        "action": action,
        "status": action.lower(),
        "take_trade": take,
        "reason": reason,
        "checks": checks,
        "metrics": metrics,
        "lots_advice": lots_advice,
        "suggested_qty": int(suggested_qty) if suggested_qty or action in ("BUY", "AVERAGE") else None,
        "trade_suggestion": {
            "action": action,
            "amount": _r(suggested_amount, 2) if suggested_amount else None,
            "quantity": int(suggested_qty) if action in ("BUY", "AVERAGE") else None,
            "approx_cost": approx_cost,
            "price": _r(price),
            "reason": reason,
        },
        "chart_data": _build_chart(work, max_bars=cfg.chart_bars),
        "chart_series": [{"key": "sma28", "label": f"SMA{cfg.sma_period}", "color": "#38bdf8"}],
        "chart_levels": [
            {"price": _r(sma_now), "label": f"SMA{cfg.sma_period}", "color": "#38bdf8"},
            *([{"price": _r(avg_px), "label": "Avg cost", "color": "#fbbf24"}] if held and avg_px > 0 else []),
        ],
    }


def parse_holdings(raw: list[dict[str, Any]] | None) -> list[LotInput]:
    out: list[LotInput] = []
    for row in raw or []:
        if not isinstance(row, dict):
            continue
        sym = canonicalize_symbol(str(row.get("symbol") or row.get("ticker") or ""))
        if not sym:
            continue
        try:
            price = float(row.get("price") or row.get("buy_price") or 0)
            amount = float(row.get("amount") or row.get("invested") or 0)
            units = row.get("units")
            units_f = float(units) if units is not None and str(units) != "" else None
        except (TypeError, ValueError):
            continue
        if price <= 0 and units_f and amount > 0:
            price = amount / units_f
        if price <= 0:
            continue
        if amount <= 0 and units_f:
            amount = price * units_f
        out.append(LotInput(
            symbol=sym,
            price=price,
            amount=amount if amount > 0 else price * (units_f or 0),
            units=units_f,
            purchase_date=str(row.get("purchase_date") or "") or None,
            lot_id=str(row.get("lot_id") or row.get("id") or "") or None,
        ))
    return out


def scan_universe(
    tickers: list[str],
    *,
    cfg: Etf28SmaConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
    market: str = GROWW_INDIA_MARKET,
    holdings: list[LotInput] | None = None,
) -> dict[str, Any]:
    cfg = cfg or Etf28SmaConfig()
    cap = capital_plan(cfg)
    symbols: list[str] = []
    seen: set[str] = set()
    for t in tickers:
        s = canonicalize_symbol(t)
        if s and s not in seen:
            seen.add(s)
            symbols.append(s)
    holdings = holdings or []

    results: list[dict[str, Any]] = []
    for sym in symbols:
        try:
            df = fetch_stf_etf_data(
                sym,
                groww_token=groww_token,
                exchange=exchange,
                limit=cfg.lookback_bars,
                market=market,
            )
            results.append(analyze_etf(sym, df, cfg=cfg, holdings=holdings, capital=cap))
        except Exception as exc:
            logger.exception("ETF 28 SMA failed for %s", sym)
            results.append({
                "ticker": sym,
                "strategy": STRATEGY_ID,
                "signal": "WAIT",
                "action": "WAIT",
                "take_trade": False,
                "error": str(exc)[:240],
            })

    buys = [r for r in results if r.get("action") == "BUY"]
    averages = [r for r in results if r.get("action") == "AVERAGE"]
    sells = [r for r in results if r.get("action") in ("SELL", "SELL_LOT")]
    holds = [r for r in results if r.get("action") == "HOLD"]
    watches = [r for r in results if r.get("action") == "WATCH"]

    buys_sorted = sorted(
        buys,
        key=lambda r: float((r.get("metrics") or {}).get("pct_vs_sma") or 0),
        reverse=True,
    )
    buy_limit = int(cfg.max_new_buys_per_day)
    for i, r in enumerate(buys_sorted):
        r["buy_priority"] = i + 1
        metrics = dict(r.get("metrics") or {})
        qty = metrics.get("suggested_qty")
        amt = metrics.get("suggested_amount")
        px = r.get("ltp") or metrics.get("price")
        qty_bit = f" · qty {qty} @ ₹{px}" if qty is not None and px is not None else ""
        amount_bit = f"buy up to ₹{_r(float(amt or 0), 1)}"
        slot_bit = f"(slot 1/{cap['max_etfs']}; max {buy_limit} new ETFs today)"
        if i >= buy_limit:
            r["action"] = "BUY_DEFERRED"
            r["take_trade"] = False
            r["reason"] = (
                f"2 consecutive closes above SMA{cfg.sma_period} — {amount_bit}{qty_bit} {slot_bit}"
                f" · Deferred — already {buy_limit} stronger new-buy candidates today (not actionable today)"
            )
            r["trade_suggestion"] = {
                **(r.get("trade_suggestion") or {}),
                "action": "BUY_DEFERRED",
                "quantity": qty,
                "amount": amt,
                "reason": r["reason"],
            }
        else:
            # Top buys are actionable; reason includes ₹ allocation + share qty
            r["take_trade"] = True
            r["reason"] = (
                f"2 consecutive closes above SMA{cfg.sma_period} — {amount_bit}{qty_bit} "
                f"{slot_bit} · priority #{i + 1}/{buy_limit}"
            )
            r["trade_suggestion"] = {
                **(r.get("trade_suggestion") or {}),
                "action": "BUY",
                "quantity": qty,
                "amount": amt,
                "reason": r["reason"],
            }

    # Prefer actionable buys first in results ordering
    results.sort(
        key=lambda r: (
            0 if r.get("take_trade") and r.get("action") == "BUY" else
            1 if r.get("take_trade") else
            2 if r.get("action") == "BUY_DEFERRED" else 3,
            -(float((r.get("metrics") or {}).get("pct_vs_sma") or 0)),
        )
    )

    actionable = [r for r in results if r.get("take_trade")]
    actionable_buys = [
        {
            "ticker": r.get("ticker"),
            "ltp": r.get("ltp"),
            "quantity": (r.get("metrics") or {}).get("suggested_qty") or r.get("suggested_qty"),
            "amount": (r.get("metrics") or {}).get("suggested_amount"),
            "approx_cost": (r.get("metrics") or {}).get("approx_cost"),
            "buy_priority": r.get("buy_priority"),
            "reason": r.get("reason"),
        }
        for r in results if r.get("action") == "BUY" and r.get("take_trade")
    ]

    return {
        "strategy": STRATEGY_ID,
        "strategy_label": STRATEGY_NAME,
        "how_it_works": HOW_IT_WORKS,
        "rules": RULES,
        "capital_plan": cap,
        "config": {
            "sma_period": cfg.sma_period,
            "profit_target_pct": cfg.profit_target_pct,
            "avg_min_drop_pct": cfg.avg_min_drop_pct,
            "fast_momentum_pct": cfg.fast_momentum_pct,
            "sell_mode": cfg.sell_mode,
            "capital_exhausted": cfg.capital_exhausted,
            "max_new_buys_per_day": cfg.max_new_buys_per_day,
            "max_etfs": cfg.max_etfs,
            "total_capital": cfg.total_capital,
            "averaging_reserve_pct": cfg.averaging_reserve_pct,
        },
        "summary": {
            "buy": len([r for r in results if r.get("action") == "BUY"]),
            "buy_deferred": len([r for r in results if r.get("action") == "BUY_DEFERRED"]),
            "average": len(averages),
            "sell": len(sells),
            "hold": len(holds),
            "watch": len(watches),
            "errors": len([r for r in results if r.get("error")]),
            "actionable": len(actionable),
        },
        "daily_board": {
            "buys_today": [r for r in results if r.get("action") == "BUY"],
            "actionable_buys": actionable_buys,
            "averages": averages,
            "sells": sells,
            "deferred_buys": [r for r in results if r.get("action") == "BUY_DEFERRED"],
        },
        "actionable": actionable,
        "results": results,
        "entry_count": len(actionable),
        "scanned": len(results),
        "ai_system_prompt": ETF_28_SMA_AI_SYSTEM,
        "disclaimer": (
            "Research / education only — not financial advice. "
            "Prefer distinct ETF underlyings; execute near the close after ~3:15 PM IST."
        ),
        "execution_hint": "Make decisions near market close (ideally after 3:15 PM IST). Actionable buys include quantity.",
    }


def build_etf_28_sma_ai_prompt(result: dict[str, Any]) -> str:
    extra = [
        f"Action: {result.get('action')}",
        f"Reason: {result.get('reason')}",
        f"Metrics: {result.get('metrics')}",
        f"Lots advice: {result.get('lots_advice')}",
    ]
    return build_pro_trade_ai_context(
        result,
        engine_label=STRATEGY_NAME,
        extra_lines=extra,
    )


def universe_payload() -> dict[str, Any]:
    from app.etf_ta.etf_28_sma_universe import etf_28_sma_preset_asset_class

    presets = {k: list(v) for k, v in ETF_28_SMA_PRESETS.items()}
    return {
        "strategy": STRATEGY_ID,
        "strategy_label": STRATEGY_NAME,
        "presets": presets,
        "preset_asset_class": {k: etf_28_sma_preset_asset_class(k) for k in presets},
        "default_preset": "FIRE 28 SMA — curated list",
        "default_symbols": fire_28_sma_symbols(),
        "fire_list": fire_28_sma_symbols(),
        "combined": combined_universe(),
        "how_it_works": HOW_IT_WORKS,
        "rules": RULES,
    }
