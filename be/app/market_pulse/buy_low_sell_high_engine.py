"""
buy_low_sell_high_engine.py
---------------------------
Buy Low Sell High — 25-day low (25 DL) GTT ladder for swing accumulation.

Method (all asset classes; originally popularised for Nifty 50 / Bank Nifty names):

1. Track the **25-day low** of each ticker.
2. Place a **GTT buy** at **5% above** the 25 DL. When price trades through that level, buy.
3. If a **new 25 DL** prints before the GTT fills, **update** the GTT to 5% above the new 25 DL.
4. After you are filled, arm the **next** buy GTT only when price is **10% below average cost**.
   That next GTT is again **5% above the latest 25 DL**.
5. **Sell target = average cost + 5%** — sell **all** units.
6. **No stop-loss** — the system buys dips via the ladder; exit is the +5% average target.

This scanner simulates the GTT state on daily bars and emits the live recommended
GTT / sell levels. It does **not** place broker GTTs — research / education only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.pro_trade_shared import (
    build_pro_trade_ai_context,
    pro_trade_ai_system,
)
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.smart_money_shared import hold_for_tf

logger = logging.getLogger(__name__)

STRATEGY_ID = "buy_low_sell_high"
STRATEGY_NAME = "Buy Low Sell High"

HOW_IT_WORKS = """
### How Buy Low Sell High works

Think of this as a **GTT dip-buy ladder** anchored to the **25-day low (25 DL)**:

| Step | Rule |
|------|------|
| 1 | Track each ticker’s **25-day low** |
| 2 | Place a **buy GTT at 25 DL + 5%**. When price rises through that level, you get filled |
| 3 | If a **new 25 DL** prints *before* fill, **move the GTT** to 5% above the new low |
| 4 | After a fill, only arm the **next** buy when price is **10% below your average**. New GTT = latest 25 DL + 5% |
| 5 | **Sell all** when price hits **average + 5%** |
| 6 | **No stop-loss** — you accumulate on weakness; the exit is the +5% average target |

**Universe tip (India):** originally framed on liquid **Nifty 50 / Bank Nifty** names. Works on any
asset class in this app (India · US · Crypto · Commodities) — prefer liquid names so GTTs fill cleanly.

**How to use this screen**
1. Pick an asset class and tickers (or a Nifty/Bank basket on India).
2. Scan — each card shows 25 DL, suggested buy GTT, distance to trigger, and sell target if in a position.
3. Place / update broker GTTs to match the suggested levels (this app does not submit GTTs for you).
4. When status says **SELL**, book all units near average + 5%.
5. When status says **ADD TRANCHE**, price is ≥10% below average — place the next GTT at 25 DL + 5%.

Research / education only — not financial advice. Simulated fills assume the day’s high traded through the GTT.
""".strip()

RULES = [
    "Track 25-day low (rolling min of daily lows).",
    "Buy GTT = 25 DL × (1 + buy_buffer%). Default +5%.",
    "Before fill: if 25 DL makes a new low, update GTT to 5% above the new 25 DL.",
    "After fill: next buy GTT only when LTP ≤ average × (1 − add_on_drop%). Default −10%.",
    "Sell all at average × (1 + sell_target%). Default +5%. No stop-loss.",
]

BUY_LOW_SELL_HIGH_AI_SYSTEM = pro_trade_ai_system(
    "Buy Low Sell High",
    "25-day low GTT ladder: buy GTT at 25DL+5%, update on new lows before fill, "
    "add next tranche only when price is 10% below average, sell all at average+5%, no stop-loss.",
)


@dataclass
class BuyLowSellHighConfig:
    timeframe: str = "1d"
    lookback_bars: int = 320
    low_lookback: int = 25
    buy_buffer_pct: float = 5.0
    sell_target_pct: float = 5.0
    add_on_drop_pct: float = 10.0
    min_bars: int = 40
    chart_bars: int = 120
    near_trigger_pct: float = 1.5  # within this % of GTT → NEAR_TRIGGER


def _r(x: float, n: int = 6) -> float:
    return round(float(x), n)


def _simulate(
    df: pd.DataFrame,
    *,
    low_n: int,
    buy_buf: float,
    sell_tgt: float,
    add_drop: float,
) -> dict[str, Any]:
    """Walk daily bars and simulate GTT fills / average / sell-all."""
    work = df.copy()
    work["low_25"] = work["low"].rolling(low_n, min_periods=low_n).min()
    work = work.dropna(subset=["low_25"])
    if work.empty:
        return {"error": "Not enough bars for 25-day low."}

    buy_mult = 1.0 + buy_buf / 100.0
    sell_mult = 1.0 + sell_tgt / 100.0
    add_mult = 1.0 - add_drop / 100.0

    units = 0.0
    avg = 0.0
    pending_gtt: float | None = None
    events: list[dict[str, Any]] = []
    gtt_updates = 0
    buys = 0
    sells = 0

    for idx, bar in work.iterrows():
        low25 = float(bar["low_25"])
        high = float(bar["high"])
        close = float(bar["close"])
        low = float(bar["low"])
        buy_lvl = low25 * buy_mult
        t = str(idx)

        if units <= 0:
            # Always keep GTT pinned to 5% above latest 25 DL
            if pending_gtt is None:
                pending_gtt = buy_lvl
                events.append({"time": t, "type": "GTT_PLACE", "price": _r(pending_gtt), "low_25": _r(low25)})
            elif abs(pending_gtt - buy_lvl) / max(pending_gtt, 1e-9) > 1e-6:
                pending_gtt = buy_lvl
                gtt_updates += 1
                events.append({"time": t, "type": "GTT_UPDATE", "price": _r(pending_gtt), "low_25": _r(low25)})

            if pending_gtt is not None and high >= pending_gtt:
                fill = float(pending_gtt)
                units = 1.0
                avg = fill
                buys += 1
                events.append({"time": t, "type": "BUY", "price": _r(fill), "avg": _r(avg), "units": units})
                pending_gtt = None
        else:
            # Sell all at avg + sell_target%
            sell_lvl = avg * sell_mult
            if high >= sell_lvl:
                events.append({
                    "time": t, "type": "SELL_ALL", "price": _r(sell_lvl),
                    "avg": _r(avg), "units": units, "pnl_pct": _r(sell_tgt),
                })
                sells += 1
                units = 0.0
                avg = 0.0
                pending_gtt = None
                # Re-arm fresh GTT for next cycle on same bar's 25DL
                pending_gtt = buy_lvl
                events.append({"time": t, "type": "GTT_PLACE", "price": _r(pending_gtt), "low_25": _r(low25)})
                if high >= pending_gtt and low <= pending_gtt:
                    # Same-bar re-entry possible but skip to avoid churn; leave GTT pending
                    pass
                continue

            # Arm next tranche only when price ≤ avg − add_on_drop%
            if pending_gtt is None and close <= avg * add_mult:
                pending_gtt = buy_lvl
                events.append({
                    "time": t, "type": "GTT_ADD_ARM", "price": _r(pending_gtt),
                    "avg": _r(avg), "trigger": _r(avg * add_mult), "low_25": _r(low25),
                })
            elif pending_gtt is not None:
                if abs(pending_gtt - buy_lvl) / max(pending_gtt, 1e-9) > 1e-6:
                    pending_gtt = buy_lvl
                    gtt_updates += 1
                    events.append({"time": t, "type": "GTT_UPDATE", "price": _r(pending_gtt), "low_25": _r(low25)})
                if high >= pending_gtt:
                    fill = float(pending_gtt)
                    new_units = units + 1.0
                    avg = (avg * units + fill) / new_units
                    units = new_units
                    buys += 1
                    events.append({
                        "time": t, "type": "BUY_ADD", "price": _r(fill),
                        "avg": _r(avg), "units": units,
                    })
                    pending_gtt = None

    last = work.iloc[-1]
    low25 = float(last["low_25"])
    close = float(last["close"])
    high = float(last["high"])
    buy_lvl = low25 * buy_mult
    sell_lvl = avg * sell_mult if units > 0 else None
    add_arm_lvl = avg * add_mult if units > 0 else None

    # Effective pending for display
    display_gtt = pending_gtt
    if units <= 0 and display_gtt is None:
        display_gtt = buy_lvl
    if units > 0 and display_gtt is None and add_arm_lvl is not None and close <= add_arm_lvl:
        display_gtt = buy_lvl

    dist_to_gtt = None
    if display_gtt and display_gtt > 0:
        dist_to_gtt = _r((close / display_gtt - 1.0) * 100.0, 2)

    status = "WATCH_PLACE_GTT"
    signal = "WAIT"
    take = False
    direction = "NONE"
    verdict = "Place / keep buy GTT at 25 DL + buffer."

    if units > 0 and sell_lvl is not None and close >= sell_lvl:
        status = "SELL_ALL"
        signal = "BULLISH"
        take = True
        direction = "SHORT"  # exit long
        verdict = f"Price at/above average + {sell_tgt:.0f}% — sell all units."
    elif units > 0 and sell_lvl is not None and high >= sell_lvl:
        status = "SELL_ZONE"
        signal = "BULLISH"
        take = True
        direction = "SHORT"
        verdict = f"Today’s high tagged sell target (avg + {sell_tgt:.0f}%) — book profits."
    elif units > 0 and display_gtt is not None and close >= display_gtt * 0.995:
        status = "ADD_FILL_ZONE"
        signal = "BULLISH"
        take = True
        direction = "LONG"
        verdict = "Add-tranche GTT in fill zone — average down if filled."
    elif units > 0 and add_arm_lvl is not None and close <= add_arm_lvl:
        status = "ARM_ADD_GTT"
        signal = "BULLISH"
        take = True
        direction = "LONG"
        verdict = f"Price ≤ average − {add_drop:.0f}% — arm next buy GTT at latest 25 DL + {buy_buf:.0f}%."
    elif units > 0:
        status = "HOLD_FOR_SELL"
        signal = "HOLD"
        take = False
        direction = "LONG"
        dist_sell = _r((close / sell_lvl - 1.0) * 100.0, 2) if sell_lvl else None
        verdict = (
            f"In position (avg {_r(avg)}). Hold for sell at {_r(sell_lvl)} "
            f"({dist_sell}% from target)." if sell_lvl else "In position — hold for +5% average target."
        )
    elif display_gtt is not None and close >= display_gtt:
        status = "BUY_FILL_ZONE"
        signal = "BULLISH"
        take = True
        direction = "LONG"
        verdict = f"Price at/above buy GTT ({_r(display_gtt)}) — first tranche fill zone."
    elif display_gtt is not None and dist_to_gtt is not None and abs(dist_to_gtt) <= 1.5:
        status = "NEAR_TRIGGER"
        signal = "WAIT"
        take = False
        direction = "LONG"
        verdict = f"Within ~1.5% of buy GTT {_r(display_gtt)} — keep GTT live."
    else:
        status = "WATCH_PLACE_GTT"
        signal = "WAIT"
        take = False
        direction = "NONE"
        verdict = (
            f"25 DL = {_r(low25)}; place buy GTT at {_r(buy_lvl)} "
            f"(+{buy_buf:.0f}%). Update if a new 25 DL prints before fill."
        )

    # Confidence: actionable states + proximity
    conf = 40.0
    if status in ("SELL_ALL", "SELL_ZONE", "BUY_FILL_ZONE", "ADD_FILL_ZONE", "ARM_ADD_GTT"):
        conf = 72.0
    elif status == "NEAR_TRIGGER":
        conf = 58.0
    elif status == "HOLD_FOR_SELL":
        conf = 55.0
    if dist_to_gtt is not None and -3 <= dist_to_gtt <= 3:
        conf = min(88.0, conf + 8.0)

    return {
        "work": work,
        "units": units,
        "avg": avg,
        "low_25": low25,
        "close": close,
        "buy_gtt": display_gtt,
        "buy_gtt_fresh": buy_lvl,
        "sell_target": sell_lvl,
        "add_arm_level": add_arm_lvl,
        "dist_to_gtt_pct": dist_to_gtt,
        "status": status,
        "signal": signal,
        "take_trade": take,
        "direction": direction,
        "verdict": verdict,
        "confidence_pct": _r(conf, 1),
        "events": events[-12:],
        "stats": {"buys": buys, "sells": sells, "gtt_updates": gtt_updates},
        "in_position": units > 0,
    }


def _build_chart(work: pd.DataFrame, *, max_bars: int, buy_buf: float) -> list[dict[str, Any]]:
    buy_mult = 1.0 + buy_buf / 100.0
    tail = work.iloc[-max_bars:]
    rows: list[dict[str, Any]] = []
    for idx, bar in tail.iterrows():
        low25 = float(bar["low_25"]) if pd.notna(bar.get("low_25")) else None
        row: dict[str, Any] = {
            "time": str(idx),
            "open": _r(float(bar["open"])),
            "high": _r(float(bar["high"])),
            "low": _r(float(bar["low"])),
            "close": _r(float(bar["close"])),
            "volume": _r(float(bar["volume"]), 2) if "volume" in bar and pd.notna(bar.get("volume")) else None,
        }
        if low25 is not None:
            row["low_25"] = _r(low25)
            row["buy_gtt"] = _r(low25 * buy_mult)
        rows.append(row)
    return rows


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: BuyLowSellHighConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or BuyLowSellHighConfig()
    tf = (cfg.timeframe or "1d").strip() or "1d"
    out: dict[str, Any] = {
        "ticker": ticker,
        "strategy": STRATEGY_ID,
        "strategy_label": STRATEGY_NAME,
        "error": None,
        "take_trade": False,
        "signal": "WAIT",
        "direction": "NONE",
        "verdict": "No data yet",
        "confidence_pct": None,
        "chart_data": [],
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
    need = max(cfg.min_bars, cfg.low_lookback + 5)
    if df is None or df.empty or len(df) < need:
        out["error"] = f"Insufficient {tf} data (need ≥{need} bars)."
        return out

    sim = _simulate(
        df,
        low_n=cfg.low_lookback,
        buy_buf=cfg.buy_buffer_pct,
        sell_tgt=cfg.sell_target_pct,
        add_drop=cfg.add_on_drop_pct,
    )
    if sim.get("error"):
        out["error"] = sim["error"]
        return out

    work: pd.DataFrame = sim["work"]
    take = bool(sim["take_trade"])
    direction = str(sim["direction"])
    status = str(sim["status"])
    close = float(sim["close"])
    buy_gtt = sim["buy_gtt"]
    sell_target = sim["sell_target"]
    avg = float(sim["avg"]) if sim["in_position"] else None

    entry = None
    stop = None  # explicit: no stop-loss
    target = None
    sl_pct = None
    tp_pct = cfg.sell_target_pct if take or sim["in_position"] else None

    if status in ("BUY_FILL_ZONE", "NEAR_TRIGGER", "WATCH_PLACE_GTT", "ARM_ADD_GTT", "ADD_FILL_ZONE"):
        entry = float(buy_gtt) if buy_gtt else None
        target = _r(entry * (1 + cfg.sell_target_pct / 100.0)) if entry else None
    elif status in ("SELL_ALL", "SELL_ZONE", "HOLD_FOR_SELL") and avg:
        entry = avg
        target = float(sell_target) if sell_target else _r(avg * (1 + cfg.sell_target_pct / 100.0))
        tp_pct = cfg.sell_target_pct

    hold = hold_for_tf(tf)
    plan_dir = "LONG"
    if status in ("SELL_ALL", "SELL_ZONE"):
        plan_dir = "SHORT"
    elif direction == "LONG":
        plan_dir = "LONG"
    plan = make_trade_plan(
        direction=plan_dir if (take or sim["in_position"]) else "—",
        timeframe=tf,
        stop_loss_pct=0.0,
        take_profit_pct=round(cfg.sell_target_pct, 2),
        confidence_pct=float(sim["confidence_pct"] or 0),
        style="swing",
        exit_rule=(
            f"Buy Low Sell High: NO stop-loss. Sell ALL at average + {cfg.sell_target_pct:.0f}%. "
            f"Buy / update GTT at 25 DL + {cfg.buy_buffer_pct:.0f}%. "
            f"Next add only when price ≤ average − {cfg.add_on_drop_pct:.0f}%."
        ),
        max_hold_exit=f"Swing hold typical days–weeks ({hold}); exit at avg + {cfg.sell_target_pct:.0f}%.",
    )

    action = "WAIT"
    if status in ("BUY_FILL_ZONE", "ADD_FILL_ZONE"):
        action = "BUY"
    elif status in ("SELL_ALL", "SELL_ZONE"):
        action = "SELL"
    elif status == "ARM_ADD_GTT":
        action = "PLACE_ADD_GTT"
    elif status in ("WATCH_PLACE_GTT", "NEAR_TRIGGER"):
        action = "PLACE_GTT"

    plain = str(sim["verdict"])
    if buy_gtt:
        plain += f" Suggested buy GTT ≈ {_r(buy_gtt)}."
    if sell_target:
        plain += f" Sell-all target ≈ {_r(sell_target)}."
    plain += " No stop-loss."

    chart = _build_chart(work, max_bars=cfg.chart_bars, buy_buf=cfg.buy_buffer_pct)
    levels = []
    if sim["low_25"]:
        levels.append({"label": f"{cfg.low_lookback} DL", "price": _r(sim["low_25"]), "color": "#94a3b8"})
    if buy_gtt:
        levels.append({"label": "Buy GTT", "price": _r(float(buy_gtt)), "color": "#22c55e"})
    if sell_target:
        levels.append({"label": "Sell +5% avg", "price": _r(float(sell_target)), "color": "#f59e0b"})
    if avg:
        levels.append({"label": "Avg cost", "price": _r(avg), "color": "#38bdf8"})

    out.update({
        "timeframe": tf,
        "ltp": _r(close),
        "bars": len(work),
        "take_trade": take,
        "signal": sim["signal"],
        "direction": direction if direction in ("LONG", "SHORT") else "NONE",
        "status": status,
        "verdict": sim["verdict"],
        "plain_english": plain,
        "confidence_pct": sim["confidence_pct"],
        "sl_pct": sl_pct,
        "tp_pct": tp_pct,
        "entry_price": _r(entry) if entry else None,
        "stop_price": stop,
        "target_price": _r(target) if target else None,
        "no_stop_loss": True,
        "trade_plan": {**plan, "holding_period": hold, "stop_loss": None, "no_stop_loss": True},
        "reasons": [
            f"25-day low: {_r(sim['low_25'])}",
            f"Buy GTT (25DL+{cfg.buy_buffer_pct:.0f}%): {_r(float(buy_gtt)) if buy_gtt else '—'}",
            f"In position: {'yes' if sim['in_position'] else 'no'}"
            + (f" · avg {_r(avg)} · units {sim['units']}" if sim["in_position"] else ""),
            f"Sell target (avg+{cfg.sell_target_pct:.0f}%): {_r(float(sell_target)) if sell_target else '—'}",
            f"Add-arm level (avg−{cfg.add_on_drop_pct:.0f}%): {_r(float(sim['add_arm_level'])) if sim['add_arm_level'] else '—'}",
            f"Dist to GTT: {sim['dist_to_gtt_pct']}%",
            f"Simulated history: {sim['stats']['buys']} buys · {sim['stats']['sells']} sells · {sim['stats']['gtt_updates']} GTT updates",
        ],
        "trade_suggestion": {
            "action": action,
            "side": direction if take else "WAIT",
            "confidence_pct": sim["confidence_pct"],
            "sl_pct": None,
            "tp_pct": tp_pct,
            "entry_price": _r(entry) if entry else None,
            "stop_price": None,
            "target_price": _r(target) if target else None,
            "plain_english": plain,
            "action_label": {
                "BUY": "BUY — GTT fill zone",
                "SELL": "SELL ALL — avg + target",
                "PLACE_GTT": "PLACE / UPDATE buy GTT",
                "PLACE_ADD_GTT": "ARM next buy GTT (avg −10%)",
                "WAIT": "WAIT — keep watching 25 DL",
            }.get(action, action),
        },
        "levels": {
            "low_25": _r(sim["low_25"]),
            "buy_gtt": _r(float(buy_gtt)) if buy_gtt else None,
            "buy_gtt_fresh_25dl": _r(float(sim["buy_gtt_fresh"])),
            "avg_cost": _r(avg) if avg else None,
            "sell_target": _r(float(sell_target)) if sell_target else None,
            "add_arm_level": _r(float(sim["add_arm_level"])) if sim["add_arm_level"] else None,
            "dist_to_gtt_pct": sim["dist_to_gtt_pct"],
            "in_position": sim["in_position"],
            "simulated_units": sim["units"],
        },
        "chart_levels": levels,
        "chart_data": chart,
        "chart_series": [
            {"key": "low_25", "label": f"{cfg.low_lookback} DL", "color": "#94a3b8"},
            {"key": "buy_gtt", "label": "Buy GTT (+5%)", "color": "#22c55e"},
        ],
        "recent_events": sim["events"],
        "sim_stats": sim["stats"],
        "config_used": {
            "low_lookback": cfg.low_lookback,
            "buy_buffer_pct": cfg.buy_buffer_pct,
            "sell_target_pct": cfg.sell_target_pct,
            "add_on_drop_pct": cfg.add_on_drop_pct,
        },
    })
    return out


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: BuyLowSellHighConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or BuyLowSellHighConfig()
    results: list[dict[str, Any]] = []
    for t in tickers:
        try:
            results.append(
                analyze_ticker(t, market, cfg=cfg, groww_token=groww_token, exchange=exchange)
            )
        except Exception as exc:
            logger.exception("Buy Low Sell High failed for %s", t)
            results.append({"ticker": t, "strategy": STRATEGY_ID, "error": str(exc)[:240]})

    actionable = [r for r in results if r.get("take_trade")]
    return {
        "strategy": STRATEGY_ID,
        "strategy_label": STRATEGY_NAME,
        "how_it_works": HOW_IT_WORKS,
        "rules": RULES,
        "timeframe": cfg.timeframe,
        "config": {
            "low_lookback": cfg.low_lookback,
            "buy_buffer_pct": cfg.buy_buffer_pct,
            "sell_target_pct": cfg.sell_target_pct,
            "add_on_drop_pct": cfg.add_on_drop_pct,
            "lookback_bars": cfg.lookback_bars,
        },
        "results": results,
        "entry_count": len(actionable),
        "scanned": len(results),
        "ai_system_prompt": BUY_LOW_SELL_HIGH_AI_SYSTEM,
        "disclaimer": (
            "Research / education only — not financial advice. Levels are simulated from OHLC; "
            "place real GTTs on your broker. Prefer liquid names (e.g. Nifty 50 / Bank Nifty on India)."
        ),
    }


def build_buy_low_sell_high_ai_prompt(result: dict[str, Any]) -> str:
    extra = [
        f"Status: {result.get('status')}",
        f"Levels: {result.get('levels')}",
        f"No stop-loss: {result.get('no_stop_loss')}",
        f"Recent events: {result.get('recent_events')}",
    ]
    return build_pro_trade_ai_context(
        result,
        engine_label=STRATEGY_NAME,
        extra_lines=extra,
    )
