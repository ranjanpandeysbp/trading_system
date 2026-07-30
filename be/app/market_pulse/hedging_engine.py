"""
hedging_engine.py
-------------------
Hedging — Non-Directional Delta-Neutral Options Hedging (intraday), per Vikas's
breakdown: https://www.youtube.com/watch?v=FXhudoBZ5SU

Setup:
  - Chart Demand/Supply zones first: the strong swing low below the session's
    opening price is the Demand Zone, the strong swing high above it is the
    Supply Zone (15-minute chart; falls back to 1-hour if no clear zone
    forms — same convention Vikas gives for a slow/quiet open).
  - Short one ATM Call + one ATM Put (each ~0.5 delta, canceling out —
    Delta Neutral at entry).
  - Immediately buy deep OTM Call + Put hedges, ~4% away from spot, to cap
    the tail risk of a gap/black-swan move. Structurally this is the same
    short-straddle-plus-far-wings shape as this app's Delta-Neutral (Iron
    Fly) engine, so leg pricing/selection is delegated there rather than
    reimplemented — `delta_neutral_engine.build_delta_neutral(iron_fly=True,
    wing_width_pct=hedge_distance_pct)` IS this structure. What's new here
    is the zone-based adjustment process and capital-based risk framework
    below, which the Delta-Neutral engine doesn't have.

Adjustment process (the crucial, distinctive part of this strategy):
  - Don't adjust on a small mark-to-market wiggle, and don't adjust just
    because price is touching a zone — wait for a 15m candle to strictly
    CLOSE beyond the Demand/Supply zone before treating it as broken.
  - Once broken: exit the losing leg (the one whose delta spiked), keep the
    hedges exactly as they are, sell a fresh ATM leg on the broken side.
    This deliberately leaves a small residual delta (not re-flattened to
    zero) as a snap-back safety net. Max one adjustment per day.

Risk management (the "brain" of the strategy, per Vikas):
  - Hard stop at 2-3% of TOTAL capital (not margin deployed) — exit
    everything immediately if touched.
  - Take profit around 1-1.5% of total capital — small, frequent wins
    rather than chasing more; the inverted risk:reward is offset by a high
    win rate.
  - Size positions so the capital-based stop doesn't feel threatening —
    hedging needing less margin is not a reason to use all of it.

Data sources: identical convention to delta_neutral_engine.py (which this
module delegates leg pricing to) — real NSE/Yahoo option chains for
India/US, Black-Scholes-simulated (clearly labeled) for Crypto/Commodities.
Demand/Supply zones use this app's own OHLCV feed (Groww/yfinance) on the
selected intraday timeframe.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.market_pulse.delta_neutral_engine import DeltaNeutralConfig, build_delta_neutral
from app.market_pulse.double_calendar_engine import _fetch_tf_ohlcv

logger = logging.getLogger(__name__)

YOUTUBE_HEDGING_URL = "https://www.youtube.com/watch?v=FXhudoBZ5SU"

ZONE_TIMEFRAME_OPTIONS = ["15m", "30m", "1h"]
ZONE_FALLBACK_OPTIONS = ["1h", "4h"]


@dataclass
class HedgingConfig:
    dte: int = 2  # target days-to-expiry; resolves to the nearest listed expiry (current/next weekly for India)
    hedge_distance_pct: float = 4.0  # far-OTM hedge legs, this % away from spot
    zone_timeframe: str = "15m"
    zone_fallback_timeframe: str = "1h"
    zone_break_buffer_pct: float = 0.0  # extra cushion beyond the zone edge before calling it "broken"
    total_capital: float = 500_000.0
    profit_target_pct_of_capital: float = 0.0125  # ~1-1.5% of total capital
    max_loss_pct_of_capital: float = 0.025  # ~2-3% of total capital
    max_adjustments_per_day: int = 1
    risk_free_rate: float = 0.065
    realized_vol_window: int = 20


# ---------------------------------------------------------------------------
# Step 1 — Demand/Supply zones from the session open
# ---------------------------------------------------------------------------

def _session_bars(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    last_date = df.index[-1].date()
    return df[df.index.map(lambda ts: ts.date()) == last_date]


def _zone_from_bar(bar: pd.Series, *, is_high: bool) -> dict[str, float]:
    body_top = max(float(bar["open"]), float(bar["close"]))
    body_bottom = min(float(bar["open"]), float(bar["close"]))
    if is_high:
        return {"top": float(bar["high"]), "bottom": body_top}
    return {"top": body_bottom, "bottom": float(bar["low"])}


def find_demand_supply_zones(
    ticker: str, market: str, cfg: HedgingConfig, *, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    """Demand = the session's strongest swing low below the opening price;
    Supply = the session's strongest swing high above it. Falls back to the
    1h chart's recent range (looking for prior major reversal areas) when
    the primary timeframe hasn't printed enough of today's session yet."""
    primary = _fetch_tf_ohlcv(ticker, market, cfg.zone_timeframe, groww_token=groww_token, exchange=exchange)
    session = _session_bars(primary) if not primary.empty else primary
    tf_used = cfg.zone_timeframe
    session_open: float | None = None

    if session.empty or len(session) < 3:
        fallback = _fetch_tf_ohlcv(ticker, market, cfg.zone_fallback_timeframe, groww_token=groww_token, exchange=exchange)
        if fallback.empty:
            return {"demand": None, "supply": None, "session_open": None, "timeframe": tf_used, "fallback_used": False}
        session = fallback.iloc[-40:]
        tf_used = cfg.zone_fallback_timeframe

    if session.empty:
        return {"demand": None, "supply": None, "session_open": None, "timeframe": tf_used, "fallback_used": tf_used != cfg.zone_timeframe}

    session_open = float(session["open"].iloc[0])
    below = session[session["low"] < session_open]
    above = session[session["high"] > session_open]

    demand = _zone_from_bar(session.loc[below["low"].idxmin()], is_high=False) if not below.empty else None
    supply = _zone_from_bar(session.loc[above["high"].idxmax()], is_high=True) if not above.empty else None

    return {
        "demand": demand, "supply": supply, "session_open": round(session_open, 6),
        "timeframe": tf_used, "fallback_used": tf_used != cfg.zone_timeframe,
    }


def evaluate_adjustment_signal(df_tf: pd.DataFrame, zones: dict[str, Any], cfg: HedgingConfig) -> dict[str, Any]:
    """Only a strict CLOSE beyond the zone counts as broken — a wick/touch is
    explicitly NOT an adjustment trigger (avoids the 'fake adjustment' trap:
    reacting to a small mark-to-market wiggle or a level merely being tested)."""
    if df_tf.empty:
        return {"status": "NO_DATA", "note": "Not enough intraday data to evaluate zone breaks yet."}

    last_closed = df_tf.iloc[-1]
    price = float(last_closed["close"])
    demand, supply = zones.get("demand"), zones.get("supply")

    if demand:
        break_level = demand["bottom"] * (1 - cfg.zone_break_buffer_pct / 100)
        if price < break_level:
            return {
                "status": "ADJUST_PUT",
                "note": (
                    f"A {zones['timeframe']} candle closed below the Demand zone ({demand['bottom']:,.4g}) — "
                    "exit the losing Put leg, keep the hedges exactly as they are, sell a fresh ATM Put to replace it."
                ),
            }
    if supply:
        break_level = supply["top"] * (1 + cfg.zone_break_buffer_pct / 100)
        if price > break_level:
            return {
                "status": "ADJUST_CALL",
                "note": (
                    f"A {zones['timeframe']} candle closed above the Supply zone ({supply['top']:,.4g}) — "
                    "exit the losing Call leg, keep the hedges exactly as they are, sell a fresh ATM Call to replace it."
                ),
            }
    if demand and price > 0 and (price - demand["top"]) / price * 100 <= 0.5:
        return {"status": "WATCH_DEMAND", "note": "Price is testing the Demand zone — do not adjust yet; wait to see if it bounces (avoid a fake adjustment)."}
    if supply and price > 0 and (supply["bottom"] - price) / price * 100 <= 0.5:
        return {"status": "WATCH_SUPPLY", "note": "Price is testing the Supply zone — do not adjust yet; wait to see if it rejects (avoid a fake adjustment)."}
    return {"status": "HOLD", "note": "Price is inside the Demand/Supply range — no adjustment needed, let theta decay work."}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def build_hedging(
    ticker: str, asset_class: str, market: str, *,
    cfg: HedgingConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or HedgingConfig()

    zones = find_demand_supply_zones(ticker, market, cfg, groww_token=groww_token, exchange=exchange)

    dn_cfg = DeltaNeutralConfig(
        dte=cfg.dte, iron_fly=True, wing_width_pct=cfg.hedge_distance_pct,
        risk_free_rate=cfg.risk_free_rate, realized_vol_window=cfg.realized_vol_window,
    )
    base = build_delta_neutral(ticker, asset_class, market, [], cfg=dn_cfg, groww_token=groww_token, exchange=exchange)
    if base.get("error"):
        return base

    adjustment: dict[str, Any]
    try:
        tf_df = _fetch_tf_ohlcv(ticker, market, zones["timeframe"], groww_token=groww_token, exchange=exchange)
        eval_df = _session_bars(tf_df) if not zones.get("fallback_used") else tf_df.iloc[-40:]
        adjustment = evaluate_adjustment_signal(eval_df, zones, cfg)
    except Exception as exc:
        logger.debug("Hedging adjustment-signal eval failed for %s: %s", ticker, exc)
        adjustment = {"status": "NO_DATA", "note": "Could not evaluate the adjustment signal right now."}

    profit_target = round(cfg.total_capital * cfg.profit_target_pct_of_capital, 2)
    loss_limit = round(cfg.total_capital * cfg.max_loss_pct_of_capital, 2)

    reasons: list[str] = [
        f"Non-Directional Delta-Neutral Hedge on {ticker}: short ATM Call + ATM Put (straddle, ~0.5Δ each, "
        f"canceling out), hedged with far OTM Call + Put ~{cfg.hedge_distance_pct:.1f}% away from spot to cap "
        "tail risk on a gap or broker glitch.",
    ]
    if zones.get("session_open") is not None:
        d_txt = f"{zones['demand']['bottom']:,.4g}–{zones['demand']['top']:,.4g}" if zones.get("demand") else "not found"
        s_txt = f"{zones['supply']['bottom']:,.4g}–{zones['supply']['top']:,.4g}" if zones.get("supply") else "not found"
        reasons.append(
            f"Session open {zones['session_open']:,.4g} on the {zones['timeframe']} chart"
            + (" (fallback timeframe — today's session hadn't formed a clear zone yet)" if zones.get("fallback_used") else "")
            + f" — Demand {d_txt}, Supply {s_txt}."
        )
    else:
        reasons.append("Could not chart Demand/Supply zones right now — insufficient intraday data.")
    reasons.append(adjustment["note"])
    reasons.append(
        f"Risk management: take profit around {cfg.profit_target_pct_of_capital * 100:.2g}% of total capital "
        f"(~{profit_target:,.0f}); hard stop at {cfg.max_loss_pct_of_capital * 100:.2g}% of total capital "
        f"(~{loss_limit:,.0f}) — if touched, exit every leg immediately, no exceptions."
    )
    reasons.append(
        f"Position sizing: don't deploy your full capital just because hedging needs less margin — size so a "
        f"{cfg.max_loss_pct_of_capital * 100:.2g}% capital loss doesn't trigger emotional decisions."
    )
    reasons.append(f"Maximum {cfg.max_adjustments_per_day} adjustment(s) per day — this app can't track your open "
                    "position across the session, so treat this as a manual checklist rule, not an enforced limit.")
    any_simulated = any(leg.get("source", "").startswith("Simulated") for leg in base["legs"].values())
    if any_simulated:
        reasons.append(
            "One or more legs used simulated (Black-Scholes) pricing — no live/liquid option quote was available "
            "at that strike/expiry. Treat premiums as an estimate, not a fillable quote."
        )

    return {
        "ticker": ticker, "asset_class": asset_class, "market": market,
        "spot": base["spot"], "target_expiry": base["target_expiry"],
        "legs": base["legs"], "net_credit": base["net_credit"],
        "max_profit": base["max_profit"], "max_loss": base["max_loss"], "pop_pct": base["pop_pct"],
        "hedge_distance_pct": cfg.hedge_distance_pct,
        "demand_zone": zones.get("demand"), "supply_zone": zones.get("supply"),
        "zone_timeframe": zones.get("timeframe"), "zone_fallback_used": zones.get("fallback_used", False),
        "session_open": zones.get("session_open"),
        "adjustment_signal": adjustment,
        "total_capital": cfg.total_capital, "profit_target": profit_target, "loss_limit": loss_limit,
        "entry_ok": bool(base.get("entry_ok", True)),
        "reasons": reasons,
    }


def build_hedging_many(
    tickers: list[str], asset_class: str, market: str, *,
    cfg: HedgingConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> list[dict[str, Any]]:
    results = []
    for ticker in tickers:
        try:
            results.append(build_hedging(ticker, asset_class, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            logger.debug("Hedging failed for %s: %s", ticker, exc)
            results.append({"ticker": ticker, "asset_class": asset_class, "error": str(exc)[:200]})
    return results


def evaluate_hedging_pnl(total_capital: float, current_pnl: float, cfg: HedgingConfig | None = None) -> dict[str, Any]:
    """current_pnl = your actual running P&L on the whole hedge right now (in
    account currency), positive or negative — this app doesn't track your
    live position, so you supply it manually."""
    cfg = cfg or HedgingConfig()
    if total_capital is None or total_capital <= 0:
        return {"error": "Invalid total capital."}

    pnl_pct_of_capital = current_pnl / total_capital
    profit_target = round(total_capital * cfg.profit_target_pct_of_capital, 2)
    loss_limit = round(total_capital * cfg.max_loss_pct_of_capital, 2)

    if current_pnl <= -loss_limit:
        action = "EXIT_ALL"
        message = (
            f"\U0001F534 Loss has reached {abs(pnl_pct_of_capital) * 100:.2f}% of total capital "
            f"(limit {cfg.max_loss_pct_of_capital * 100:.2g}%) — \"Hands up, I am out.\" Close every leg "
            "immediately, no exceptions, no more adjustments."
        )
    elif current_pnl >= profit_target:
        action = "CLOSE_PROFIT"
        message = (
            f"\U0001F535 Profit target reached — {pnl_pct_of_capital * 100:.2f}% of total capital captured "
            f"(target {cfg.profit_target_pct_of_capital * 100:.2g}%). Close the position — this strategy runs "
            "on a high win rate of small, frequent wins, not chasing large ones."
        )
    else:
        action = "HOLD"
        message = (
            f"⚪ Hold — {pnl_pct_of_capital * 100:+.2f}% of total capital so far, inside the "
            f"-{cfg.max_loss_pct_of_capital * 100:.2g}%/+{cfg.profit_target_pct_of_capital * 100:.2g}% risk band."
        )
    return {
        "pnl_pct_of_capital": round(pnl_pct_of_capital * 100, 2),
        "profit_target": profit_target, "loss_limit": loss_limit,
        "action": action, "message": message,
    }
