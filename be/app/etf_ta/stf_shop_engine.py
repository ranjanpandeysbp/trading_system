"""
stf_shop_engine.py
------------------
ETF Shop 4.0 — programmatic India ETF swing + dynamic SIP engine
(FIRE in India / Mahesh Chandra Kaushik).

Rules:
  - Rank tracked ETFs by cheapness vs 20 DMA (Rank 1 = standard buy candidate)
  - Max 1 buy / max 1 sell per day (standard Rank 1 OR dynamic SIP — not both)
  - Weakness: −10% from initial purchase → stop averaging, enter SIP mode (latched)
  - SIP: 1/day on ETF with largest fall from last buy; skip plus-zone (above last buy)
  - SIP budget: 10% of total invested in that ETF (fixed for the SIP cycle)
  - FIFO profit booking: BOTH % target AND minimum ₹ profit on lot
  - Dynamic capital: deposited + compounded growth − personal dividend draw
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.etf_ta.india_etf_universe import GROWW_INDIA_MARKET

SLOTS_DIVISOR = 60
DEFAULT_PROFIT_TARGET_PCT = 6.0
DEFAULT_PROFIT_TARGET_INR = 700.0
DEFAULT_MIN_PROFIT_INR = 500.0
DEFAULT_STCG_TAX_PCT = 15.0
DEFAULT_BROKERAGE_PCT = 0.03
DMA_PERIOD = 20
SIP_WEAKNESS_THRESHOLD_PCT = -10.0
SIP_BUDGET_FRACTION = 0.10

SellMode = Literal["percentage", "absolute", "combined"]


def fetch_stf_etf_data(
    symbol: str,
    groww_token: str = "",
    exchange: str = "NSE",
    limit: int = 120,
) -> pd.DataFrame:
    """Daily OHLCV for one NSE ETF."""
    return fetch_data_for_gap_scan(
        symbol,
        "1d",
        GROWW_INDIA_MARKET,
        groww_token,
        exchange,
        limit=limit,
    )


def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).lower() for c in out.columns]
    for col in ("open", "high", "low", "close", "volume"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out.dropna(subset=["close"])


def analyze_etf_dma(df: pd.DataFrame, symbol: str) -> dict[str, Any]:
    """CMP vs 20 DMA metrics for one ETF."""
    base = {
        "symbol": symbol,
        "price": None,
        "sma20": None,
        "pct_from_dma": None,
        "below_dma": False,
        "rank": None,
        "error": None,
        "data_ok": False,
        "bar_date": None,
    }
    if df is None or df.empty or len(df) < DMA_PERIOD + 2:
        base["error"] = f"Need ≥{DMA_PERIOD + 2} daily bars"
        return base

    work = _normalize_df(df)
    close = work["close"]
    sma20 = close.rolling(DMA_PERIOD).mean()
    price = float(close.iloc[-1])
    dma = float(sma20.iloc[-1])
    if not np.isfinite(dma) or dma <= 0 or not np.isfinite(price):
        base["error"] = "Invalid price or 20 DMA"
        return base

    pct = (price - dma) / dma * 100.0
    bar_date = work.index[-1]
    if hasattr(bar_date, "strftime"):
        bar_date = bar_date.strftime("%Y-%m-%d")

    base.update({
        "price": round(price, 4),
        "sma20": round(dma, 4),
        "pct_from_dma": round(pct, 3),
        "below_dma": price < dma,
        "data_ok": True,
        "bar_date": str(bar_date),
    })
    return base


def rank_etfs_by_dma(analyses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Rank by cheapness vs 20 DMA — lowest % vs DMA = Rank 1.
    Rows with data errors are isolated and excluded.
    """
    for a in analyses:
        a["rank"] = None

    valid = [a for a in analyses if a.get("data_ok") and not a.get("error")]
    valid.sort(key=lambda x: float(x.get("pct_from_dma") or 0))
    for i, row in enumerate(valid, start=1):
        row["rank"] = i
    return analyses


def data_error_symbols(analyses: list[dict[str, Any]]) -> list[str]:
    return [a["symbol"] for a in analyses if a.get("error") or not a.get("data_ok")]


def scan_etf_universe(
    symbols: list[str],
    *,
    groww_token: str = "",
    exchange: str = "NSE",
) -> list[dict[str, Any]]:
    """Fetch and rank all ETFs; failed pulls stay out of ranking."""
    rows: list[dict[str, Any]] = []
    for sym in symbols:
        try:
            df = fetch_stf_etf_data(sym, groww_token, exchange)
            rows.append(analyze_etf_dma(df, sym))
        except Exception as exc:
            rows.append({
                "symbol": sym,
                "error": str(exc)[:100],
                "price": None,
                "sma20": None,
                "pct_from_dma": None,
                "below_dma": False,
                "rank": None,
                "data_ok": False,
            })
    return rank_etfs_by_dma(rows)


def effective_capital(
    deposited: float,
    growth_amount: float = 0.0,
    dividend_withdrawn: float = 0.0,
) -> float:
    """Shop capital pool for dynamic slot sizing."""
    return max(0.0, float(deposited) + float(growth_amount) - float(dividend_withdrawn))


def slot_size_from_capital(total_capital: float, divisor: int = SLOTS_DIVISOR) -> float:
    return round(max(0.0, float(total_capital)) / max(1, divisor), 2)


def open_slots(portfolio: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [s for s in portfolio if (s.get("status") or "open") == "open"]


def closed_slots(portfolio: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [s for s in portfolio if (s.get("status") or "open") == "closed"]


def deployed_capital(portfolio: list[dict[str, Any]]) -> float:
    return sum(float(s.get("amount") or 0) for s in open_slots(portfolio))


def _slots_for_symbol(portfolio: list[dict[str, Any]], symbol: str) -> list[dict[str, Any]]:
    sym = symbol.upper().strip()
    return [s for s in open_slots(portfolio) if (s.get("symbol") or "").upper() == sym]


def initial_purchase_price_by_symbol(portfolio: list[dict[str, Any]]) -> dict[str, float]:
    """Earliest open lot buy price per symbol (= initial purchase reference)."""
    out: dict[str, float] = {}
    for slot in sorted(open_slots(portfolio), key=lambda x: x.get("purchase_date") or ""):
        sym = (slot.get("symbol") or "").upper()
        if sym and sym not in out:
            out[sym] = float(slot.get("purchase_price") or 0)
    return out


def last_purchase_price_by_symbol(portfolio: list[dict[str, Any]]) -> dict[str, float]:
    """Most recent open lot buy price per symbol."""
    out: dict[str, float] = {}
    for slot in sorted(open_slots(portfolio), key=lambda x: x.get("purchase_date") or ""):
        sym = (slot.get("symbol") or "").upper()
        if sym:
            out[sym] = float(slot.get("purchase_price") or 0)
    return out


def total_invested_by_symbol(portfolio: list[dict[str, Any]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for slot in open_slots(portfolio):
        sym = (slot.get("symbol") or "").upper()
        if sym:
            out[sym] = out.get(sym, 0.0) + float(slot.get("amount") or 0)
    return out


def sip_amount_for_symbol(portfolio: list[dict[str, Any]], symbol: str) -> float:
    """Monthly SIP budget = 10% of total invested in that ETF."""
    invested = total_invested_by_symbol(portfolio).get(symbol.upper(), 0.0)
    return round(invested * SIP_BUDGET_FRACTION, 2)


def update_sip_locked_symbols(
    portfolio: list[dict[str, Any]],
    analyses: list[dict[str, Any]],
    sip_locked: set[str] | list[str] | None,
    *,
    weakness_threshold_pct: float = SIP_WEAKNESS_THRESHOLD_PCT,
) -> set[str]:
    """
    Latch symbols into SIP mode when CMP falls to weakness threshold vs initial buy.
    Once latched, symbol stays in SIP mode.
    """
    locked = {s.upper() for s in (sip_locked or [])}
    price_map = {a["symbol"]: a.get("price") for a in analyses if a.get("price")}
    initial_map = initial_purchase_price_by_symbol(portfolio)

    for sym, initial_px in initial_map.items():
        if initial_px <= 0:
            continue
        price = price_map.get(sym)
        if price is None:
            continue
        pct_from_initial = (float(price) - initial_px) / initial_px * 100.0
        if pct_from_initial <= weakness_threshold_pct:
            locked.add(sym)
    return locked


def rank_sip_candidates(
    portfolio: list[dict[str, Any]],
    analyses: list[dict[str, Any]],
    sip_locked: set[str] | list[str],
) -> list[dict[str, Any]]:
    """
    Dynamic fall model — sort by fall from last buy price (most negative = top).
    Plus-zone filter: skip ETFs trading above last buy price.
    """
    price_map = {a["symbol"]: a.get("price") for a in analyses if a.get("price")}
    last_buy = last_purchase_price_by_symbol(portfolio)
    invested = total_invested_by_symbol(portfolio)
    locked = {s.upper() for s in sip_locked}
    rows: list[dict[str, Any]] = []

    for sym in sorted(locked):
        price = price_map.get(sym)
        lb = last_buy.get(sym)
        if price is None or not lb or lb <= 0:
            continue
        if sym not in invested or invested[sym] <= 0:
            continue
        fall_pct = (float(price) - lb) / lb * 100.0
        if fall_pct >= 0:
            continue
        sip_amt = round(invested[sym] * SIP_BUDGET_FRACTION, 2)
        rows.append({
            "symbol": sym,
            "price": price,
            "last_buy_price": lb,
            "fall_from_last_buy_pct": round(fall_pct, 3),
            "sip_amount": sip_amt,
            "total_invested": round(invested[sym], 2),
            "plus_zone": False,
        })

    rows.sort(key=lambda x: float(x.get("fall_from_last_buy_pct") or 0))
    for i, row in enumerate(rows, start=1):
        row["sip_rank"] = i
    return rows


def rank_1_buy(
    analyses: list[dict[str, Any]],
    *,
    slot_amount: float,
) -> dict[str, Any] | None:
    """Standard shop buy: Rank 1 (cheapest vs 20 DMA) — 1 ETF per day."""
    ranked = sorted(
        [a for a in analyses if a.get("rank") == 1],
        key=lambda x: int(x["rank"]),
    )
    if not ranked:
        ranked = sorted(
            [a for a in analyses if a.get("rank")],
            key=lambda x: int(x["rank"]),
        )
    if not ranked:
        return None

    row = ranked[0]
    return {
        "action": "BUY",
        "buy_type": "standard",
        "symbol": row["symbol"],
        "rank": row["rank"],
        "price": row.get("price"),
        "pct_from_dma": row.get("pct_from_dma"),
        "slot_amount": slot_amount,
        "reason": (
            f"Rank {row['rank']} — cheapest vs 20 DMA ({row.get('pct_from_dma'):.2f}%). "
            f"Standard shop: buy 1 ETF/day at top rank."
        ),
    }


def sip_buy_recommendation(
    sip_candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Top dynamic SIP candidate — largest fall from last buy (plus-zone excluded)."""
    if not sip_candidates:
        return None
    row = sip_candidates[0]
    return {
        "action": "BUY",
        "buy_type": "sip",
        "symbol": row["symbol"],
        "sip_rank": row.get("sip_rank", 1),
        "price": row.get("price"),
        "fall_from_last_buy_pct": row.get("fall_from_last_buy_pct"),
        "slot_amount": row.get("sip_amount"),
        "sip_amount": row.get("sip_amount"),
        "total_invested": row.get("total_invested"),
        "reason": (
            f"SIP #{row.get('sip_rank')} — largest fall from last buy "
            f"({row.get('fall_from_last_buy_pct'):.2f}%) · budget "
            f"₹{row.get('sip_amount'):,.0f} (10% of ₹{row.get('total_invested'):,.0f} invested)."
        ),
    }


def _slot_profit_inr(slot: dict[str, Any], current_price: float) -> float:
    buy_px = float(slot.get("purchase_price") or 0)
    qty = float(slot.get("quantity") or 0)
    if buy_px <= 0:
        return 0.0
    if qty <= 0:
        amt = float(slot.get("amount") or 0)
        qty = amt / buy_px if buy_px else 0
    return round((float(current_price) - buy_px) * qty, 2)


def _sell_hit(
  *,
    sell_mode: SellMode,
    profit_pct: float,
    profit_inr: float,
    profit_target_pct: float,
    profit_target_inr: float,
    min_profit_inr: float,
) -> bool:
    if sell_mode == "percentage":
        return profit_pct >= profit_target_pct
    if sell_mode == "absolute":
        return profit_inr >= profit_target_inr
    return profit_pct >= profit_target_pct and profit_inr >= min_profit_inr


def sell_candidates_fifo(
    portfolio: list[dict[str, Any]],
    analyses: list[dict[str, Any]],
    *,
    sell_mode: SellMode = "combined",
    profit_target_pct: float = DEFAULT_PROFIT_TARGET_PCT,
    profit_target_inr: float = DEFAULT_PROFIT_TARGET_INR,
    min_profit_inr: float = DEFAULT_MIN_PROFIT_INR,
) -> list[dict[str, Any]]:
    """FIFO lots eligible to sell — oldest purchase checked first per symbol."""
    price_map = {a["symbol"]: a.get("price") for a in analyses if a.get("price")}
    out: list[dict[str, Any]] = []

    by_sym: dict[str, list[dict[str, Any]]] = {}
    for slot in open_slots(portfolio):
        by_sym.setdefault(slot["symbol"], []).append(slot)

    for sym, slots in by_sym.items():
        price = price_map.get(sym)
        if price is None:
            continue
        slots.sort(key=lambda x: x.get("purchase_date") or "")
        for slot in slots:
            buy_px = float(slot.get("purchase_price") or 0)
            if buy_px <= 0:
                continue
            profit_pct = (float(price) - buy_px) / buy_px * 100.0
            profit_inr = _slot_profit_inr(slot, float(price))
            hit = _sell_hit(
                sell_mode=sell_mode,
                profit_pct=profit_pct,
                profit_inr=profit_inr,
                profit_target_pct=profit_target_pct,
                profit_target_inr=profit_target_inr,
                min_profit_inr=min_profit_inr,
            )
            if not hit:
                continue
            if sell_mode == "combined":
                trigger = (
                    f"+{profit_pct:.2f}% (≥{profit_target_pct:.1f}%) "
                    f"and +₹{profit_inr:,.0f} (≥₹{min_profit_inr:,.0f})"
                )
            elif sell_mode == "percentage":
                trigger = f"+{profit_pct:.2f}% (target {profit_target_pct:.1f}%)"
            else:
                trigger = f"+₹{profit_inr:,.0f} (target ₹{profit_target_inr:,.0f})"
            out.append({
                "action": "SELL",
                "symbol": sym,
                "slot_id": slot.get("slot_id"),
                "purchase_price": buy_px,
                "purchase_date": slot.get("purchase_date"),
                "current_price": price,
                "profit_pct": round(profit_pct, 2),
                "profit_inr": profit_inr,
                "amount": slot.get("amount"),
                "quantity": slot.get("quantity"),
                "sell_mode": sell_mode,
                "eligible": True,
                "reason": f"FIFO lot {trigger} · buy ₹{buy_px:.2f}.",
            })

    if sell_mode == "percentage":
        out.sort(key=lambda x: float(x.get("profit_pct") or 0), reverse=True)
    else:
        out.sort(key=lambda x: float(x.get("profit_inr") or 0), reverse=True)
    return out


# Backward-compatible alias
sell_candidates_lifo = sell_candidates_fifo


def net_profit_after_costs(
    gross_profit_inr: float,
    *,
    stcg_tax_pct: float = DEFAULT_STCG_TAX_PCT,
    brokerage_pct: float = DEFAULT_BROKERAGE_PCT,
    sale_amount: float = 0.0,
) -> dict[str, float]:
    """Estimated net after STCG and brokerage (Shop growth reinvestment)."""
    tax = max(0.0, gross_profit_inr * stcg_tax_pct / 100.0)
    brokerage = max(0.0, sale_amount * brokerage_pct / 100.0)
    net = gross_profit_inr - tax - brokerage
    return {
        "gross_profit": round(gross_profit_inr, 2),
        "stcg_tax": round(tax, 2),
        "brokerage": round(brokerage, 2),
        "net_profit": round(net, 2),
    }


def split_profit_reinvestment(
    net_profit: float,
    dividend_pct: float = 0.0,
) -> dict[str, float]:
    """Personal dividend vs growth amount reinvested into shop."""
    div_pct = max(0.0, min(100.0, float(dividend_pct)))
    dividend = round(net_profit * div_pct / 100.0, 2)
    growth = round(net_profit - dividend, 2)
    return {"dividend": dividend, "growth_add": growth}


def profit_analyzer_summary(portfolio: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bika Hua Maal — sold lots grouped by underlying ETF."""
    by_sym: dict[str, dict[str, Any]] = {}
    for slot in closed_slots(portfolio):
        sym = (slot.get("symbol") or "").upper()
        if not sym:
            continue
        gross = float(slot.get("gross_profit") or 0)
        net = float(slot.get("net_profit") or gross)
        row = by_sym.setdefault(sym, {
            "symbol": sym,
            "bookings": 0,
            "gross_profit_inr": 0.0,
            "net_profit_inr": 0.0,
            "total_sold_amount": 0.0,
        })
        row["bookings"] += 1
        row["gross_profit_inr"] = round(row["gross_profit_inr"] + gross, 2)
        row["net_profit_inr"] = round(row["net_profit_inr"] + net, 2)
        row["total_sold_amount"] = round(
            row["total_sold_amount"] + float(slot.get("sale_amount") or slot.get("amount") or 0),
            2,
        )

    rows = list(by_sym.values())
    rows.sort(key=lambda x: float(x.get("net_profit_inr") or 0), reverse=True)
    for i, row in enumerate(rows, start=1):
        row["profit_rank"] = i
    return rows


def annualized_return_pct(
    *,
    deposited: float,
    growth_amount: float,
    dividend_withdrawn: float,
    shop_start_date: str | None,
) -> float | None:
    """CAGR-style annualized return from shop start date."""
    if not shop_start_date or deposited <= 0:
        return None
    try:
        start = datetime.strptime(shop_start_date[:10], "%Y-%m-%d")
    except ValueError:
        return None
    days = (datetime.now() - start).days
    if days < 1:
        return None
    total_gain = float(growth_amount) + float(dividend_withdrawn)
    years = days / 365.25
    if years <= 0:
        return None
    ratio = 1.0 + total_gain / float(deposited)
    if ratio <= 0:
        return None
    return round((ratio ** (1.0 / years) - 1.0) * 100.0, 2)


def daily_stf_recommendation(
    *,
    deposited_capital: float,
    growth_amount: float = 0.0,
    dividend_withdrawn: float = 0.0,
    portfolio: list[dict[str, Any]],
    analyses: list[dict[str, Any]],
    sell_mode: SellMode = "combined",
    profit_target_pct: float = DEFAULT_PROFIT_TARGET_PCT,
    profit_target_inr: float = DEFAULT_PROFIT_TARGET_INR,
    min_profit_inr: float = DEFAULT_MIN_PROFIT_INR,
    slots_divisor: int = SLOTS_DIVISOR,
    sip_locked: set[str] | list[str] | None = None,
    shop_start_date: str | None = None,
    prefer_sip_when_available: bool = True,
) -> dict[str, Any]:
    """Combined daily tracker — standard or SIP buy + FIFO sell (max 1 each)."""
    pool = effective_capital(deposited_capital, growth_amount, dividend_withdrawn)
    slot_amt = slot_size_from_capital(pool, slots_divisor)
    deployed = deployed_capital(portfolio)
    free = max(0.0, pool - deployed)
    pct_deployed = (deployed / pool * 100.0) if pool > 0 else 0.0

    errors = data_error_symbols(analyses)
    locked = update_sip_locked_symbols(portfolio, analyses, sip_locked)
    sip_candidates = rank_sip_candidates(portfolio, analyses, locked)

    sells = sell_candidates_fifo(
        portfolio,
        analyses,
        sell_mode=sell_mode,
        profit_target_pct=profit_target_pct,
        profit_target_inr=profit_target_inr,
        min_profit_inr=min_profit_inr,
    )

    sip_buy = sip_buy_recommendation(sip_candidates) if prefer_sip_when_available else None
    standard_buy = rank_1_buy(analyses, slot_amount=slot_amt)

    buy: dict[str, Any] | None = None
    if sip_buy and sip_candidates:
        buy = sip_buy
    elif standard_buy:
        buy = standard_buy

    if buy:
        need = float(buy.get("slot_amount") or buy.get("sip_amount") or slot_amt)
        if free < need * 0.95:
            buy = {
                **buy,
                "blocked": True,
                "block_reason": (
                    f"Insufficient free capital (need ₹{need:,.0f}, free ₹{free:,.0f}). "
                    "If market capital is exhausted, stop buying and wait for recovery."
                ),
            }
        else:
            buy = {**buy, "blocked": False}

    if not buy:
        if sip_candidates and not prefer_sip_when_available:
            buy_note = {
                "action": "NO BUY",
                "reason": "SIP candidates exist but standard Rank 1 buy mode selected.",
            }
        else:
            buy_note = {
                "action": "NO BUY",
                "reason": (
                    "No standard Rank 1 or eligible SIP (plus-zone filtered) — "
                    "check master list or wait for dip."
                ),
            }
    else:
        buy_note = buy

    primary_sell = sells[0] if sells else None
    if primary_sell and len(sells) > 1:
        primary_sell = {
            **primary_sell,
            "note": (
                f"{len(sells)} FIFO lots eligible — sell max 1 today; "
                "move row Bought → Sold."
            ),
        }

    ann = annualized_return_pct(
        deposited=deposited_capital,
        growth_amount=growth_amount,
        dividend_withdrawn=dividend_withdrawn,
        shop_start_date=shop_start_date,
    )

    return {
        "version": "ETF Shop 4.0",
        "effective_capital": round(pool, 2),
        "deposited_capital": round(float(deposited_capital), 2),
        "growth_amount": round(float(growth_amount), 2),
        "dividend_withdrawn": round(float(dividend_withdrawn), 2),
        "shop_start_date": shop_start_date,
        "annualized_return_pct": ann,
        "slot_size": slot_amt,
        "deployed_capital": round(deployed, 2),
        "free_capital": round(free, 2),
        "pct_deployed": round(pct_deployed, 1),
        "sell_mode": sell_mode,
        "profit_target_pct": profit_target_pct,
        "profit_target_inr": profit_target_inr,
        "min_profit_inr": min_profit_inr,
        "sip_locked_symbols": sorted(locked),
        "sip_candidates": sip_candidates,
        "buy_recommendation": buy_note,
        "sell_candidates": sells,
        "primary_sell": primary_sell,
        "data_errors": errors,
        "ranked_all": sorted(
            [a for a in analyses if a.get("rank")],
            key=lambda x: int(x["rank"]),
        ),
        "profit_analyzer": profit_analyzer_summary(portfolio),
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def new_slot(
    symbol: str,
    purchase_price: float,
    amount: float,
    purchase_date: str | None = None,
    *,
    lot_type: str = "standard",
) -> dict[str, Any]:
    qty = amount / purchase_price if purchase_price > 0 else 0.0
    return {
        "slot_id": str(uuid.uuid4())[:8],
        "symbol": symbol.upper().strip(),
        "purchase_price": round(float(purchase_price), 4),
        "purchase_date": purchase_date or datetime.now().strftime("%Y-%m-%d"),
        "amount": round(float(amount), 2),
        "quantity": round(qty, 4),
        "status": "open",
        "lot_type": lot_type,
    }


def close_slot(
    portfolio: list[dict[str, Any]],
    slot_id: str,
    *,
    gross_profit: float | None = None,
    net_profit: float | None = None,
    sale_amount: float | None = None,
) -> list[dict[str, Any]]:
    out = []
    for s in portfolio:
        if s.get("slot_id") == slot_id:
            closed = {
                **s,
                "status": "closed",
                "closed_date": datetime.now().strftime("%Y-%m-%d"),
            }
            if gross_profit is not None:
                closed["gross_profit"] = round(float(gross_profit), 2)
            if net_profit is not None:
                closed["net_profit"] = round(float(net_profit), 2)
            if sale_amount is not None:
                closed["sale_amount"] = round(float(sale_amount), 2)
            out.append(closed)
        else:
            out.append(s)
    return out


def shop_start_from_portfolio(portfolio: list[dict[str, Any]]) -> str | None:
    """Earliest purchase date across all lots (open + closed)."""
    dates = [s.get("purchase_date") for s in portfolio if s.get("purchase_date")]
    return min(dates) if dates else None
