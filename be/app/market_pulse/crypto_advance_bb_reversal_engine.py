"""
crypto_advance_bb_reversal_engine.py
------------------------------------
Crypto Trading · Advance BB Reversal (~80%)

30m Bollinger Band mean-reversion:

SHORT — prior bar outside UPPER BB → current closes back inside → SHORT → target LOWER BB
LONG  — prior bar outside LOWER BB → current closes back inside → LONG  → target UPPER BB

Money management (Smart Wave): SL ₹200 · TGT ₹600 (1:3).
Avoid bad trades: with-trend · short near resistance · long near support.

Research / education only — not financial advice.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.market_pulse.coindcx_24h_volatility_engine import ranked_display_tickers
from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.price_action import detect_support_resistance
from app.market_pulse.pro_trade_shared import pack_trade_setup, sl_tp_pct
from app.market_pulse.run_summary import make_trade_plan
from app.market_pulse.smart_wave_crypto_engine import (
    REWARD_PER_TRADE_INR,
    RISK_PER_TRADE_INR,
    TRADE_SIZE_INR,
    bb_reversal_signals,
    calculate_trade_risk,
)

logger = logging.getLogger(__name__)

STRATEGY_ID = "crypto_advance_bb_reversal"
STRATEGY_NAME = "Advance BB Reversal"
MARKET = "CoinDCX Futures"

HOW_IT_WORKS = """
### Advance BB Reversal (Crypto · ~80%)

**Timeframe:** 30 minutes · Bollinger Bands (20, 2).

| Side | Setup | Target |
|------|--------|--------|
| **SHORT** | Price outside **UPPER** BB → next candle **closes inside** | **Lower** BB |
| **LONG** | Price outside **LOWER** BB → next candle **closes inside** | **Upper** BB |

**Money:** SL ₹200 · TGT ₹600 (1:3) — size the position so stop risk ≈ ₹200.

**Avoid bad trades:**
1. Trade **with the trend** (price vs EMA20).
2. Prefer **shorts near resistance**.
3. Prefer **longs near support**.
"""

RULES = [
    "TF default 30m · BB period 20 · std 2.",
    "SHORT: prev close > upper BB, current close ≤ upper BB → target lower BB.",
    "LONG: prev close < lower BB, current close ≥ lower BB → target upper BB.",
    "Risk plan: ₹200 stop / ₹600 target (1:3) on position size.",
    "Filters: with-trend · short near resistance · long near support.",
]

PRO_TIPS = [
    "Claimed accuracy ~80% when filters are respected — still research only.",
    "Don't fade a strong trend against EMA20 without S/R confluence.",
    "Exit early if price re-closes outside the band against the trade.",
]


@dataclass
class AdvanceBbReversalConfig:
    timeframe: str = "30m"
    bb_period: int = 20
    bb_std: float = 2.0
    trend_ema: int = 20
    lookback_bars: int = 200
    min_bars: int = 60
    chart_bars: int = 120
    max_tickers: int = 30
    risk_inr: float = float(RISK_PER_TRADE_INR)  # 200
    reward_inr: float = float(REWARD_PER_TRADE_INR)  # 600
    margin_inr: float = float(TRADE_SIZE_INR)
    leverage: int = 5
    require_trend: bool = True
    require_sr: bool = True
    sr_near_pct: float = 1.5  # % of price to count as "near" S/R
    take_confidence_threshold: float = 55.0
    side: str = "both"  # long | short | both

    def __post_init__(self) -> None:
        side = str(self.side or "both").lower()
        if side in ("buy", "long", "up"):
            side = "long"
        elif side in ("sell", "short", "down"):
            side = "short"
        elif side not in ("long", "short", "both"):
            side = "both"
        self.side = side


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
        for k in ("bb_upper", "bb_mid", "bb_lower", "ema_trend"):
            if k in bar and pd.notna(bar.get(k)):
                row[k] = _r(float(bar[k]), 6)
        rows.append(row)
    return rows


def _near_level(price: float, levels: list[dict], *, near_pct: float) -> tuple[bool, float | None]:
    if not levels or price <= 0:
        return False, None
    tol = price * (near_pct / 100.0)
    best = None
    for lv in levels:
        p = float(lv.get("price") or 0)
        if p <= 0:
            continue
        d = abs(p - price)
        if d <= tol and (best is None or d < best[0]):
            best = (d, p)
    if best is None:
        return False, None
    return True, best[1]


def analyze_ticker(
    ticker: str,
    *,
    cfg: AdvanceBbReversalConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or AdvanceBbReversalConfig()
    out: dict[str, Any] = {
        "ticker": ticker,
        "timeframe": cfg.timeframe,
        "strategy": STRATEGY_ID,
        "strategy_label": STRATEGY_NAME,
        "signal": "WAIT",
        "direction": "NONE",
        "take_trade": False,
        "accuracy": "~80%",
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

    work = bb_reversal_signals(df, period=int(cfg.bb_period), std=float(cfg.bb_std))
    work["ema_trend"] = work["close"].ewm(span=int(cfg.trend_ema), adjust=False).mean()

    i = len(work) - 1
    row = work.iloc[i]
    price = float(row["close"])
    upper = float(row["bb_upper"]) if pd.notna(row["bb_upper"]) else None
    lower = float(row["bb_lower"]) if pd.notna(row["bb_lower"]) else None
    mid = float(row["bb_mid"]) if pd.notna(row["bb_mid"]) else None
    ema_v = float(row["ema_trend"]) if pd.notna(row["ema_trend"]) else None
    sig = int(row["signal"]) if pd.notna(row["signal"]) else 0

    # Fresh signal: prefer last bar; also accept flip within last 2 bars
    sig_idx = i
    if sig == 0 and i >= 1:
        for j in range(i, max(i - 2, 0) - 1, -1):
            s = int(work["signal"].iloc[j]) if pd.notna(work["signal"].iloc[j]) else 0
            if s != 0:
                sig = s
                sig_idx = j
                break

    trend_bull = ema_v is not None and price >= ema_v
    trend_bear = ema_v is not None and price <= ema_v

    sr = detect_support_resistance(work)
    supports = sr.get("supports") or []
    resistances = sr.get("resistances") or []
    near_sup, sup_px = _near_level(price, supports, near_pct=float(cfg.sr_near_pct))
    near_res, res_px = _near_level(price, resistances, near_pct=float(cfg.sr_near_pct))

    want_long = sig == 1 and cfg.side in ("long", "both")
    want_short = sig == -1 and cfg.side in ("short", "both")

    trend_ok_long = (not cfg.require_trend) or trend_bull
    trend_ok_short = (not cfg.require_trend) or trend_bear
    sr_ok_long = (not cfg.require_sr) or near_sup
    sr_ok_short = (not cfg.require_sr) or near_res

    checks = [
        {
            "id": "bb_setup",
            "label": "BB pierce → close inside",
            "passed": sig != 0,
            "detail": (
                "LONG setup (outside lower → inside)"
                if sig == 1
                else "SHORT setup (outside upper → inside)"
                if sig == -1
                else "No fresh BB re-entry on last bars"
            ),
        },
        {
            "id": "with_trend",
            "label": f"With trend (EMA{cfg.trend_ema})",
            "passed": (want_long and trend_ok_long) or (want_short and trend_ok_short) or sig == 0,
            "detail": (
                f"price {_r(price)} · EMA {_r(ema_v) if ema_v is not None else '—'} · "
                f"{'bullish' if trend_bull else 'bearish' if trend_bear else '—'}"
            ),
        },
        {
            "id": "sr_filter",
            "label": "S/R confluence",
            "passed": (want_long and sr_ok_long) or (want_short and sr_ok_short) or sig == 0,
            "detail": (
                f"near support {_r(sup_px) if near_sup else '—'}"
                if want_long or sig == 1
                else f"near resistance {_r(res_px) if near_res else '—'}"
                if want_short or sig == -1
                else f"S {_r(sup_px) if near_sup else '—'} · R {_r(res_px) if near_res else '—'}"
            ),
        },
    ]
    out["checks"] = checks
    out["ltp"] = _r(price)
    out["metrics"] = {
        "price": _r(price),
        "bb_upper": _r(upper) if upper is not None else None,
        "bb_mid": _r(mid) if mid is not None else None,
        "bb_lower": _r(lower) if lower is not None else None,
        "ema_trend": _r(ema_v) if ema_v is not None else None,
        "near_support": near_sup,
        "near_resistance": near_res,
        "support": _r(sup_px) if near_sup else None,
        "resistance": _r(res_px) if near_res else None,
        "signal_bar": sig_idx,
        "risk_inr": cfg.risk_inr,
        "reward_inr": cfg.reward_inr,
    }
    out["chart_data"] = _build_chart(work, max_bars=int(cfg.chart_bars))
    out["chart_series"] = [
        {"key": "bb_upper", "label": "BB Upper", "color": "#94a3b8"},
        {"key": "bb_mid", "label": "BB Mid", "color": "#38bdf8"},
        {"key": "bb_lower", "label": "BB Lower", "color": "#94a3b8"},
        {"key": "ema_trend", "label": f"EMA{cfg.trend_ema}", "color": "#fbbf24"},
    ]

    long_ok = want_long and trend_ok_long and sr_ok_long and lower is not None and upper is not None
    short_ok = want_short and trend_ok_short and sr_ok_short and lower is not None and upper is not None

    if not long_ok and not short_ok:
        why = [c["detail"] for c in checks if not c["passed"]]
        out["signal"] = "WATCH" if sig != 0 else "WAIT"
        out["reason"] = "WAIT: " + ("; ".join(why) if why else "filters blocked or no setup")
        out["plain_english"] = (
            f"{ticker} {cfg.timeframe}: "
            f"{'BB setup seen but filters failed' if sig != 0 else 'no BB re-entry'}. "
            f"{out['reason']}"
        )
        return out

    is_long = long_ok and (not short_ok or (want_long and not want_short))
    direction = "LONG" if is_long else "SHORT"
    entry = price
    target = float(upper) if is_long else float(lower)

    # Soft price stop from risk ₹200 on leveraged notional (Smart Wave sizing)
    risk = calculate_trade_risk(
        entry,
        entry * (0.99 if is_long else 1.01),  # placeholder; replaced below
        margin_inr=float(cfg.margin_inr),
        leverage=int(cfg.leverage),
    )
    position = float(risk.get("position_inr") or (cfg.margin_inr * cfg.leverage))
    sl_pct_money = (float(cfg.risk_inr) / position * 100.0) if position > 0 else 0.75
    # Cap soft SL so it stays sane vs band width
    if is_long:
        stop = entry * (1.0 - sl_pct_money / 100.0)
        # Prefer stop just beyond recent low / lower band
        band_stop = float(lower) * 0.998 if lower else stop
        stop = min(stop, band_stop) if band_stop < entry else stop
    else:
        stop = entry * (1.0 + sl_pct_money / 100.0)
        band_stop = float(upper) * 1.002 if upper else stop
        stop = max(stop, band_stop) if band_stop > entry else stop

    risk = calculate_trade_risk(entry, stop, margin_inr=float(cfg.margin_inr), leverage=int(cfg.leverage))
    sl_pct_v, tp_pct_v = sl_tp_pct(direction, entry, stop, target)

    conf = 62.0
    if (is_long and near_sup) or (not is_long and near_res):
        conf += 8
    if (is_long and trend_bull) or (not is_long and trend_bear):
        conf += 8
    if abs(tp_pct_v or 0) >= abs(sl_pct_v or 1) * 1.5:
        conf += 6
    conf = min(88.0, conf)
    take = conf >= float(cfg.take_confidence_threshold) and bool(risk.get("within_limit", True))

    setup = pack_trade_setup(
        direction=direction,
        entry=entry,
        stop=stop,
        target=target,
        confidence_pct=conf,
        confidence_reasons=[
            "BB pierce → close inside",
            f"With EMA{cfg.trend_ema}" if ((is_long and trend_bull) or (not is_long and trend_bear)) else "Trend soft",
            "Near S/R" if ((is_long and near_sup) or (not is_long and near_res)) else "S/R optional miss",
            f"Risk ₹{cfg.risk_inr:g} / reward ₹{cfg.reward_inr:g}",
        ],
        reason=(
            f"{'LONG' if is_long else 'SHORT'} BB re-entry · target opposite band · "
            f"₹{cfg.risk_inr:g}/₹{cfg.reward_inr:g}"
        ),
        plain_english=(
            f"{'Buy' if is_long else 'Sell'} {ticker} on {cfg.timeframe}: price pierced the "
            f"{'lower' if is_long else 'upper'} Bollinger and closed back inside. "
            f"Aim for the opposite band ({_r(target)}); size so stop risk ≈ ₹{cfg.risk_inr:g} "
            f"(target ≈ ₹{cfg.reward_inr:g}). Accuracy claim ~80% with filters."
        ),
        timeframe=cfg.timeframe,
        grade="A" if conf >= 72 else "B",
        take_trade=take,
    )

    plan = make_trade_plan(
        direction=direction,
        timeframe=cfg.timeframe,
        stop_loss_pct=round(sl_pct_v or 0, 2),
        take_profit_pct=round(tp_pct_v or 0, 2),
        confidence_pct=conf,
        style="intraday",
        exit_rule=(
            f"TP at opposite BB ({_r(target)}). Soft SL {_r(stop)} "
            f"(size for ≈₹{cfg.risk_inr:g} risk / ₹{cfg.reward_inr:g} reward). "
            f"Invalidate if close re-exits the band against the trade."
        ),
        max_hold_exit="Typical 30m–few hours; don't overnight if band expansion continues against you.",
    )

    out["chart_levels"] = [
        {"label": "Entry", "price": _r(entry), "color": "#38bdf8"},
        {"label": "SL", "price": _r(stop), "color": "#f43f5e"},
        {"label": "TP (opp BB)", "price": _r(target), "color": "#34d399"},
    ]
    if near_sup and sup_px:
        out["chart_levels"].append({"label": "Support", "price": _r(sup_px), "color": "#86efac"})
    if near_res and res_px:
        out["chart_levels"].append({"label": "Resistance", "price": _r(res_px), "color": "#fda4af"})

    out.update({
        "take_trade": take,
        "direction": direction,
        "signal": "BULLISH" if is_long else "BEARISH",
        "action": "BUY" if is_long else "SELL",
        "status": "take" if take else "setup_low_conf",
        "reason": setup["reason"],
        "entry_price": _r(entry),
        "stop_price": _r(stop),
        "target_price": _r(target),
        "sl_pct": sl_pct_v,
        "tp_pct": tp_pct_v,
        "confidence_pct": conf,
        "grade": setup.get("grade"),
        "trade_plan": plan,
        "trade_setup": setup,
        "risk": risk,
        "money_plan": {
            "sl_inr": cfg.risk_inr,
            "tgt_inr": cfg.reward_inr,
            "rr": f"1:{cfg.reward_inr / cfg.risk_inr:g}" if cfg.risk_inr else "1:3",
            "margin_inr": cfg.margin_inr,
            "leverage": cfg.leverage,
        },
        "trade_suggestion": {
            "action": "BUY" if is_long else "SELL",
            "entry": _r(entry),
            "stop": _r(stop),
            "target": _r(target),
            "accuracy": "~80%",
            "tip": "Trade WITH the trend. Short near resistance, Long near support.",
        },
        "plain_english": setup["plain_english"],
        "pro_checklist": [
            "30m BB pierce → next candle closes inside",
            "Go with trend (EMA)",
            "Short near resistance / Long near support",
            f"Size for SL ₹{cfg.risk_inr:g} · TGT ₹{cfg.reward_inr:g}",
            "Target = opposite Bollinger band",
        ],
    })
    return out


def scan_universe(
    *,
    cfg: AdvanceBbReversalConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
    tickers: list[str] | None = None,
) -> dict[str, Any]:
    cfg = cfg or AdvanceBbReversalConfig()
    if tickers:
        scan_list = list(dict.fromkeys(tickers))
    else:
        scan_list = ranked_display_tickers(limit=int(cfg.max_tickers))

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
            "error": "No crypto tickers to scan",
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
            "bb_period": cfg.bb_period,
            "bb_std": cfg.bb_std,
            "risk_inr": cfg.risk_inr,
            "reward_inr": cfg.reward_inr,
            "require_trend": cfg.require_trend,
            "require_sr": cfg.require_sr,
            "side": cfg.side,
        },
        "results": results,
        "entry_count": len(actionable),
        "scanned": len(results),
        "asset_class": "crypto",
        "market": MARKET,
        "currency": "$",
        "disclaimer": (
            "Research / education only — not financial advice. "
            "30m BB pierce→inside · opposite-band target · ₹200/₹600 money plan · "
            "with-trend + S/R filters. Claimed accuracy ~80%."
        ),
    }
