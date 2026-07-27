"""
risk_engine.py
---------------
Position sizing and portfolio-level risk — the single biggest gap flagged in
the Command Center audit: nearly every engine in this app answers "what to
buy" and "where's the stop" and stops there, with no concept of how much to
buy or how much risk is already on the table across other open positions.
Outside two isolated engines elsewhere in this app, nothing tells the user
how much to buy — and that gap, not signal quality, is the usual reason a
positive-edge system still blows up an account.

`size_position()` is the pure per-trade calculator (fixed-fractional sizing:
size so a stop-out costs exactly `risk_pct`% of equity — standard desk
practice). `portfolio_open_risk()` adds real account state by reading the
app's own paper-trading positions, so a sizing suggestion accounts for risk
*already deployed* elsewhere, not just this one trade in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_RISK_PER_TRADE_PCT = 1.0       # % of equity risked if the stop is hit
DEFAULT_MAX_PORTFOLIO_RISK_PCT = 6.0   # cap on total open risk across all positions at once
_FALLBACK_STOP_PCT = 2.0               # assumed risk % for an open position that has no sl_pct set


@dataclass
class PositionSizeResult:
    quantity: int
    risk_amount: float
    notional: float
    risk_pct_of_equity: float
    capped_by_cash: bool


def size_position(
    entry: float, stop: float, equity: float, *,
    risk_pct: float = DEFAULT_RISK_PER_TRADE_PCT,
    size_multiplier: float = 1.0,
    available_cash: float | None = None,
) -> PositionSizeResult | None:
    """Shares to buy so a stop-out costs exactly `risk_pct`% of `equity` —
    the standard fixed-fractional sizing formula, scaled by
    `size_multiplier` (typically from vol_regime.py: smaller in high/extreme
    volatility). Returns None when inputs can't support a sane size (no
    equity, zero stop distance, or cash too thin for even one share)."""
    if entry is None or stop is None or not equity or equity <= 0:
        return None
    risk_per_share = abs(entry - stop)
    if risk_per_share <= 0:
        return None

    risk_amount = equity * (risk_pct / 100.0) * max(0.1, min(1.5, size_multiplier))
    qty = int(risk_amount / risk_per_share)
    if qty <= 0:
        return None

    notional = qty * entry
    capped_by_cash = False
    if available_cash is not None and notional > available_cash:
        qty = int(available_cash / entry) if entry else 0
        if qty <= 0:
            return None
        notional = qty * entry
        capped_by_cash = True

    actual_risk_amount = qty * risk_per_share
    return PositionSizeResult(
        quantity=qty,
        risk_amount=round(actual_risk_amount, 2),
        notional=round(notional, 2),
        risk_pct_of_equity=round(actual_risk_amount / equity * 100.0, 3),
        capped_by_cash=capped_by_cash,
    )


async def portfolio_open_risk(db, account_id: int) -> dict:
    """Sum of (stop-distance x quantity) across every currently-open paper
    position, as a % of account equity — "how much of the account is
    already at risk right now," independent of any new trade being sized.
    Positions with no sl_pct set fall back to a conservative assumed 2%
    (better to over-count unknown risk than silently ignore it)."""
    from sqlalchemy import select

    from app.models.db_models import PaperAccount, PaperPosition

    account = await db.get(PaperAccount, account_id)
    if not account:
        return {"available": False}

    result = await db.execute(select(PaperPosition).where(PaperPosition.account_id == account_id))
    positions = result.scalars().all()

    equity = account.cash_balance + sum(p.quantity * p.avg_price for p in positions)
    total_risk_amount = 0.0
    same_ticker_counts: dict[str, int] = {}
    for p in positions:
        same_ticker_counts[p.ticker] = same_ticker_counts.get(p.ticker, 0) + 1
        sl_pct = p.sl_pct if p.sl_pct is not None else _FALLBACK_STOP_PCT
        total_risk_amount += p.quantity * p.avg_price * (sl_pct / 100.0)

    total_risk_pct = (total_risk_amount / equity * 100.0) if equity else 0.0
    return {
        "available": True,
        "equity": round(equity, 2),
        "cash_balance": round(account.cash_balance, 2),
        "open_positions": len(positions),
        "total_open_risk_pct": round(total_risk_pct, 2),
        "same_ticker_counts": same_ticker_counts,
        "at_risk_cap": total_risk_pct >= DEFAULT_MAX_PORTFOLIO_RISK_PCT,
    }
