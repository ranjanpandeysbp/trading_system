"""
scalp_gold_engine.py
--------------------
Scalping — Gold: The Trading Geek 5-step high-probability gold scalp.

1) Align 1H + 15m structure bias
2) Mark 15m demand/supply POIs + liquidity (swing stops)
3) Wait for price inside a 15m POI (never mid-range)
4) Entry after liquidity sweep — aggressive or conservative (MSS + pullback)
5) TP next logical liquidity / swing · SL beyond the sweep candle

Mindset: catch the highest-probability section of the move — in fast, out faster.

Video: https://www.youtube.com/watch?v=en8RMFRqSME — The Trading Geek.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.intraday_shared import enrich_intra_live
from app.trading_hubs.smc_engine.adapters import to_smc_ohlc
from app.trading_hubs.smc_engine.config import SMCConfig
from app.trading_hubs.smc_engine.imbalances import detect_order_blocks
from app.trading_hubs.smc_engine.liquidity import detect_crt_sweeps
from app.trading_hubs.smc_engine.models import Bias, StructureEvent, SwingType
from app.trading_hubs.smc_engine.structure import (
    current_bias,
    detect_structure_breaks,
    find_fractal_swings,
)

logger = logging.getLogger(__name__)

YOUTUBE_SCALP_GOLD_URL = "https://www.youtube.com/watch?v=en8RMFRqSME"

ENTRY_STYLE_OPTIONS = ["aggressive", "conservative"]
ENTRY_STYLE_LABELS = {
    "aggressive": "Aggressive — enter right after liquidity sweep at POI",
    "conservative": "Conservative — wait for MSS, then pullback to new zone",
}

# Suggested gold / gold-proxy symbols (picker still free — works on any liquid name).
GOLD_SUGGESTED = ["GC=F", "XAUUSD=X", "GLD", "GOLDBEES", "GOLDSHARE", "HDFCGOLD"]

PHASE_NONE = "NO_SETUP"
PHASE_ALIGNED = "TREND_ALIGNED"
PHASE_POI = "POI_ARMED"
PHASE_IN_POI = "IN_POI"
PHASE_SWEEP = "LIQUIDITY_SWEEP"
PHASE_MSS = "INTERNAL_MSS"
PHASE_ENTRY = "GOLD_ENTRY"

GUIDE_MARKDOWN = f"""
### Scalping — Gold (The Trading Geek)
[Video reference]({YOUTUBE_SCALP_GOLD_URL}) — 5-step high-probability **gold** scalp.

**Mindset:** Gold is fast and liquidity-driven. You do **not** need the whole move —
take the highest-probability section, get in fast, get out faster.

| Step | Rule |
|------|------|
| **1. Trend** | **1H** and **15m** structure must align (HH/HL bullish or LH/LL bearish via BOS) |
| **2. Markup** | Extreme **demand** (buys) / **supply** (sells) + liquidity above/below obvious swings |
| **3. Patience** | Do nothing until price is inside a pre-marked **15m POI** — never mid-nowhere |
| **4. Entry** | After a **liquidity sweep** at the POI: **Aggressive** = enter on sweep · **Conservative** = wait for internal MSS, then pullback to the new zone |
| **5. Targets** | TP = next 15m internal swing / opposite zone · SL just beyond the sweep candle / protected extreme |

Discipline + fixed risk plan beat premature stop moves.
Suggested symbols: `{', '.join(GOLD_SUGGESTED)}` (or any liquid gold proxy).
"""


@dataclass
class ScalpGoldConfig:
    entry_style: str = "conservative"
    htf: str = "1h"
    ltf: str = "15m"
    fractal_window: int = 2
    poi_touch_tol_pct: float = 0.25
    max_sweep_age_bars: int = 6
    max_mss_age_bars: int = 10
    min_rr: float = 1.5
    take_confidence_threshold: float = 64.0
    lookback_htf: int = 220
    lookback_ltf: int = 400
    min_htf_bars: int = 60
    min_ltf_bars: int = 80


def _fetch(
    ticker: str,
    timeframe: str,
    market: str,
    *,
    limit: int,
    groww_token: str,
    exchange: str,
) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market or "crypto" in market.lower()
    df = normalize_ohlcv(
        fetch_data_for_gap_scan(ticker, timeframe, market, groww_token, exchange, limit=limit)
    )
    if df is None or df.empty or len(df) < max(20, limit // 25):
        df = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, timeframe, is_crypto=is_crypto, limit=limit, market=market)
        )
    return df if df is not None else pd.DataFrame()


def _structure_bias(df_raw: pd.DataFrame, cfg: ScalpGoldConfig) -> dict[str, Any]:
    smc = to_smc_ohlc(df_raw)
    swings = find_fractal_swings(smc, cfg.fractal_window)
    breaks = detect_structure_breaks(smc, swings)
    bias = current_bias(breaks)
    return {"df": smc, "swings": swings, "breaks": breaks, "bias": bias}


def _hh_hl_context(swings: list, bias: Bias) -> bool:
    """Light confirmation of HH/HL or LH/LL from last few swings."""
    highs = [s for s in swings if s.kind == SwingType.HIGH]
    lows = [s for s in swings if s.kind == SwingType.LOW]
    if len(highs) < 2 or len(lows) < 2:
        return bias != Bias.NEUTRAL
    if bias == Bias.BULLISH:
        return highs[-1].price >= highs[-2].price * 0.999 and lows[-1].price >= lows[-2].price * 0.999
    if bias == Bias.BEARISH:
        return highs[-1].price <= highs[-2].price * 1.001 and lows[-1].price <= lows[-2].price * 1.001
    return False


def _pick_pois(
    df: pd.DataFrame,
    bias: Bias,
    cfg: ScalpGoldConfig,
) -> list[dict[str, Any]]:
    smc_cfg = SMCConfig(fractal_window=cfg.fractal_window, displacement_multiplier=1.35)
    obs = detect_order_blocks(df, smc_cfg)
    pois: list[dict[str, Any]] = []
    want_demand = bias == Bias.BULLISH
    for ob in obs:
        if ob.mitigated:
            continue
        if want_demand and not ob.bullish:
            continue
        if (not want_demand) and ob.bullish:
            continue
        # Prefer recent extremes (last third of series)
        if ob.index < len(df) * 0.35:
            continue
        pois.append({
            "kind": "demand" if ob.bullish else "supply",
            "zone_low": float(ob.low),
            "zone_high": float(ob.high),
            "index": ob.index,
            "extreme": True if (want_demand and ob.low <= float(df["Low"].iloc[max(0, ob.index - 20):ob.index + 1].min()) * 1.001)
            or ((not want_demand) and ob.high >= float(df["High"].iloc[max(0, ob.index - 20):ob.index + 1].max()) * 0.999)
            else False,
        })
    # Keep 2–3 nearest extremes / latest
    pois.sort(key=lambda p: p["index"], reverse=True)
    extremes = [p for p in pois if p["extreme"]]
    chosen = (extremes[:2] + [p for p in pois if p not in extremes])[:3]
    return chosen


def _liquidity_levels(swings: list, bias: Bias) -> dict[str, list[float]]:
    highs = [float(s.price) for s in swings if s.kind == SwingType.HIGH][-5:]
    lows = [float(s.price) for s in swings if s.kind == SwingType.LOW][-5:]
    return {
        "buy_side": highs,   # stops above highs (fuel for shorts / squeeze longs)
        "sell_side": lows,   # stops below lows
        "target_long": highs[-2:] if bias == Bias.BULLISH and len(highs) >= 2 else highs[-1:],
        "target_short": lows[-2:] if bias == Bias.BEARISH and len(lows) >= 2 else lows[-1:],
    }


def _in_poi(price: float, poi: dict[str, Any], tol_pct: float) -> bool:
    lo, hi = poi["zone_low"], poi["zone_high"]
    pad = max(abs(hi - lo) * 0.2, price * tol_pct / 100.0)
    return (lo - pad) <= price <= (hi + pad)


def _active_poi(price: float, pois: list[dict[str, Any]], tol_pct: float) -> dict[str, Any] | None:
    hits = [p for p in pois if _in_poi(price, p, tol_pct)]
    if not hits:
        return None
    # Prefer extreme + most recent
    hits.sort(key=lambda p: (0 if p.get("extreme") else 1, -p["index"]))
    return hits[0]


def _recent_sweep_at_poi(
    df: pd.DataFrame,
    poi: dict[str, Any],
    bias: Bias,
    cfg: ScalpGoldConfig,
) -> dict[str, Any] | None:
    smc_cfg = SMCConfig(fractal_window=cfg.fractal_window)
    sweeps = detect_crt_sweeps(df, smc_cfg)
    cutoff = max(0, len(df) - cfg.max_sweep_age_bars)
    want = "sell_side" if bias == Bias.BULLISH else "buy_side"
    for s in reversed(sweeps):
        if s.index < cutoff or not s.validated:
            continue
        if s.direction != want:
            continue
        # Sweep should interact with POI
        if not (poi["zone_low"] * 0.997 <= s.swept_level <= poi["zone_high"] * 1.003
                or _in_poi(float(df["Close"].iloc[s.index]), poi, cfg.poi_touch_tol_pct * 1.5)):
            # Also accept wick into POI on sweep bar
            bar_lo = float(df["Low"].iloc[s.index])
            bar_hi = float(df["High"].iloc[s.index])
            if not (bar_lo <= poi["zone_high"] and bar_hi >= poi["zone_low"]):
                continue
        candle_low = float(df["Low"].iloc[s.index])
        candle_high = float(df["High"].iloc[s.index])
        return {
            "index": s.index,
            "level": float(s.swept_level),
            "direction": s.direction,
            "candle_low": candle_low,
            "candle_high": candle_high,
            "time": str(df.index[s.index]),
        }
    return None


def _internal_mss_after(
    breaks: list,
    after_i: int,
    bias: Bias,
    max_age: int,
    n_bars: int,
) -> Any | None:
    """Internal market shift confirming reversal in HTF bias direction after the sweep."""
    cutoff_hi = n_bars
    cutoff_lo = after_i
    if bias == Bias.BULLISH:
        want = (StructureEvent.BOS_BULL, StructureEvent.CHOCH_BULL)
    else:
        want = (StructureEvent.BOS_BEAR, StructureEvent.CHOCH_BEAR)
    cands = [b for b in breaks if after_i < b.index <= min(cutoff_hi - 1, after_i + max_age) and b.event in want]
    return cands[0] if cands else None


def _new_zone_after_mss(
    df: pd.DataFrame,
    mss_i: int,
    bias: Bias,
    cfg: ScalpGoldConfig,
) -> dict[str, Any] | None:
    """Demand/supply that created the internal shift — conservative pullback entry."""
    smc_cfg = SMCConfig(fractal_window=cfg.fractal_window, displacement_multiplier=1.2)
    obs = detect_order_blocks(df, smc_cfg)
    want_bull = bias == Bias.BULLISH
    cands = [
        o for o in obs
        if o.bullish == want_bull and not o.mitigated and o.impulse_index <= mss_i + 1 and o.index >= max(0, mss_i - 8)
    ]
    if not cands:
        # Fallback: last opposing candle before MSS
        i = max(0, mss_i - 1)
        return {
            "zone_low": float(df["Low"].iloc[i]),
            "zone_high": float(df["High"].iloc[i]),
            "index": i,
            "kind": "demand" if want_bull else "supply",
        }
    ob = max(cands, key=lambda o: o.impulse_index)
    return {
        "zone_low": float(ob.low),
        "zone_high": float(ob.high),
        "index": ob.index,
        "kind": "demand" if ob.bullish else "supply",
    }


def _next_target(
    price: float,
    bias: Bias,
    swings: list,
    liquidity: dict[str, list[float]],
    pois: list[dict[str, Any]],
) -> float:
    if bias == Bias.BULLISH:
        highs = sorted(s.price for s in swings if s.kind == SwingType.HIGH and s.price > price)
        pools = [x for x in liquidity.get("target_long", []) if x > price]
        opp = [p["zone_low"] for p in pois if p["kind"] == "supply" and p["zone_low"] > price]
        cands = highs[:2] + pools + opp
        return float(min(cands)) if cands else price * 1.004
    lows = sorted((s.price for s in swings if s.kind == SwingType.LOW and s.price < price), reverse=True)
    pools = [x for x in liquidity.get("target_short", []) if x < price]
    opp = [p["zone_high"] for p in pois if p["kind"] == "demand" and p["zone_high"] < price]
    cands = list(lows[:2]) + pools + opp
    return float(max(cands)) if cands else price * 0.996


def evaluate_live_signal(ctx: dict[str, Any], cfg: ScalpGoldConfig) -> dict[str, Any]:
    reasons: list[str] = []
    conf = 18.0
    phase = PHASE_NONE
    verdict = "WAIT"
    take = False
    direction = "WAIT"

    htf = ctx["htf"]
    ltf = ctx["ltf"]
    pois = ctx.get("pois") or []
    liquidity = ctx.get("liquidity") or {}
    price = float(ctx["ltp"])
    style = cfg.entry_style if cfg.entry_style in ENTRY_STYLE_OPTIONS else "conservative"

    htf_bias: Bias = htf["bias"]
    ltf_bias: Bias = ltf["bias"]
    aligned = htf_bias == ltf_bias and htf_bias != Bias.NEUTRAL
    struct_ok = _hh_hl_context(ltf["swings"], ltf_bias)

    if not aligned:
        reasons.append(
            f"Trend not aligned — 1H **{htf_bias.value}** vs 15m **{ltf_bias.value}** "
            "(both must agree before looking for gold setups)"
        )
        return _pack(direction, take, verdict, phase, conf, reasons, price, price, price, cfg, None, style)

    bias = htf_bias
    bias_label = bias.value.upper()
    direction = "LONG" if bias == Bias.BULLISH else "SHORT"
    conf += 16
    phase = PHASE_ALIGNED
    reasons.append(
        f"1H + 15m aligned **{bias_label}**"
        + (" · HH/HL (or LH/LL) structure intact" if struct_ok else " · await clearer HH/HL or LH/LL")
    )
    if struct_ok:
        conf += 6

    if not pois:
        reasons.append("No unmitigated 15m demand/supply POI marked — wait for extreme zones")
        verdict = f"WATCH {direction}"
        return _pack(direction, take, verdict, phase, conf, reasons, price, price, price, cfg, bias_label, style)

    phase = PHASE_POI
    conf += 8
    poi_bits = ", ".join(
        f"{p['kind']} {p['zone_low']:,.4g}–{p['zone_high']:,.4g}" + ("★" if p.get("extreme") else "")
        for p in pois
    )
    reasons.append(f"15m POIs: {poi_bits}")

    buy_liq = liquidity.get("buy_side") or []
    sell_liq = liquidity.get("sell_side") or []
    if buy_liq or sell_liq:
        reasons.append(
            "Liquidity (retail stops): "
            + (f"above {', '.join(f'{x:,.4g}' for x in buy_liq[-2:])} " if buy_liq else "")
            + (f"below {', '.join(f'{x:,.4g}' for x in sell_liq[-2:])}" if sell_liq else "")
        )

    active = _active_poi(price, pois, cfg.poi_touch_tol_pct)
    if not active:
        reasons.append("Price mid-range / not in a 15m POI — stay flat (patience rule)")
        verdict = f"WATCH {direction}"
        return _pack(direction, take, verdict, phase, conf, reasons, price, price, price, cfg, bias_label, style)

    phase = PHASE_IN_POI
    conf += 12
    reasons.append(
        f"Price inside 15m **{active['kind']}** POI {active['zone_low']:,.4g}–{active['zone_high']:,.4g}"
    )

    sweep = _recent_sweep_at_poi(ltf["df"], active, bias, cfg)
    if not sweep:
        reasons.append("Await liquidity sweep at POI before entry (avoid fake-outs)")
        verdict = f"WATCH {direction}"
        return _pack(direction, take, verdict, phase, conf, reasons, price, price, price, cfg, bias_label, style)

    phase = PHASE_SWEEP
    conf += 14
    reasons.append(
        f"Liquidity sweep @ {sweep['level']:,.4g} ({sweep['direction']}) on bar {str(sweep['time'])[:16]}"
    )

    entry = price
    stop = sweep["candle_low"] if direction == "LONG" else sweep["candle_high"]
    target = _next_target(price, bias, ltf["swings"], liquidity, pois)
    entry_ready = False

    if style == "aggressive":
        entry_ready = True
        entry = price
        reasons.append("Aggressive model: enter on/after sweep at POI")
    else:
        mss = _internal_mss_after(ltf["breaks"], sweep["index"], bias, cfg.max_mss_age_bars, len(ltf["df"]))
        if not mss:
            reasons.append("Conservative: wait for internal 15m market shift after the sweep")
            verdict = f"WATCH {direction}"
            return _pack(direction, take, verdict, phase, conf, reasons, entry, stop, target, cfg, bias_label, style)

        phase = PHASE_MSS
        conf += 10
        reasons.append(f"Internal MSS confirmed ({mss.event.value}) after sweep")
        new_zone = _new_zone_after_mss(ltf["df"], mss.index, bias, cfg)
        if not new_zone:
            reasons.append("Could not map pullback zone after MSS")
            verdict = f"WATCH {direction}"
            return _pack(direction, take, verdict, phase, conf, reasons, entry, stop, target, cfg, bias_label, style)

        if _in_poi(price, new_zone, cfg.poi_touch_tol_pct * 1.2):
            entry_ready = True
            entry = float((new_zone["zone_low"] + new_zone["zone_high"]) / 2.0)
            # Keep SL beyond original sweep extreme (protected low/high)
            reasons.append(
                f"Conservative pullback into new {new_zone['kind']} "
                f"{new_zone['zone_low']:,.4g}–{new_zone['zone_high']:,.4g}"
            )
        else:
            reasons.append(
                f"Await pullback into post-MSS {new_zone['kind']} "
                f"{new_zone['zone_low']:,.4g}–{new_zone['zone_high']:,.4g}"
            )
            verdict = f"WATCH {direction}"
            return _pack(direction, take, verdict, phase, conf, reasons, entry, stop, target, cfg, bias_label, style)

    if entry_ready:
        # R:R gate vs nearest logical target
        risk = abs(entry - stop)
        reward = abs(target - entry)
        rr = reward / risk if risk > 0 else 0.0
        if rr < cfg.min_rr:
            # stretch target slightly or reject
            if direction == "LONG":
                target = entry + risk * cfg.min_rr
            else:
                target = entry - risk * cfg.min_rr
            rr = cfg.min_rr
            reasons.append(f"Target adjusted to min {cfg.min_rr:.1f}R (nearest logical level was tighter)")
        else:
            reasons.append(f"TP at next logical liquidity / swing · ~{rr:.1f}R")

        phase = PHASE_ENTRY
        conf += 12
        verdict = f"TAKE {direction}"
        conf = max(15.0, min(92.0, conf))
        take = conf >= cfg.take_confidence_threshold
        return _pack(direction, take, verdict, phase, conf, reasons, entry, stop, target, cfg, bias_label, style)

    verdict = f"WATCH {direction}"
    conf = max(15.0, min(92.0, conf))
    return _pack(direction, take, verdict, phase, conf, reasons, entry, stop, target, cfg, bias_label, style)


def _pack(
    direction: str,
    take: bool,
    verdict: str,
    phase: str,
    conf: float,
    reasons: list[str],
    entry: float,
    stop: float,
    target: float,
    cfg: ScalpGoldConfig,
    bias_label: str | None,
    style: str,
) -> dict[str, Any]:
    if direction == "LONG" and stop < entry:
        sl_pct = max(0.15, (entry - stop) / entry * 100)
        tp_pct = max(0.2, (target - entry) / entry * 100)
    elif direction == "SHORT" and stop > entry:
        sl_pct = max(0.15, (stop - entry) / entry * 100)
        tp_pct = max(0.2, (entry - target) / entry * 100)
    else:
        sl_pct = 0.5
        tp_pct = sl_pct * cfg.min_rr

    hold = "Gold scalp · tight SL beyond sweep · TP nearest liquidity · out faster than greed"
    plan = make_trade_plan(
        direction=direction if take else "—",
        timeframe=cfg.ltf,
        stop_loss_pct=round(sl_pct, 2),
        take_profit_pct=round(tp_pct, 2),
        confidence_pct=round(conf, 1),
        style="scalp",
        exit_rule="Do not prematurely trail SL; exit at next logical pool or plan invalidation.",
        max_hold_exit="Intrasession scalp — flatten if 15m structure breaks against you.",
    )
    return enrich_intra_live({
        "signal": direction if take else "NONE",
        "direction": direction if direction in ("LONG", "SHORT") else None,
        "take_trade": take,
        "verdict": verdict,
        "phase": phase,
        "confidence_pct": round(max(15.0, min(92.0, conf)), 1),
        "sl_pct": round(sl_pct, 2),
        "tp_pct": round(tp_pct, 2),
        "rr_ratio": cfg.min_rr,
        "entry_price": round(entry, 6),
        "stop_price": round(stop, 6),
        "target_price": round(target, 6),
        "htf_bias": bias_label,
        "entry_style": style,
        "htf": cfg.htf,
        "ltf": cfg.ltf,
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": hold},
        "hold_duration": hold,
    }, hold_duration=hold)


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: ScalpGoldConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or ScalpGoldConfig()
    if cfg.entry_style not in ENTRY_STYLE_OPTIONS:
        cfg.entry_style = "conservative"

    df_1h = _fetch(ticker, cfg.htf, market, limit=cfg.lookback_htf, groww_token=groww_token, exchange=exchange)
    df_15 = _fetch(ticker, cfg.ltf, market, limit=cfg.lookback_ltf, groww_token=groww_token, exchange=exchange)
    if df_1h.empty or len(df_1h) < cfg.min_htf_bars:
        return {"ticker": ticker, "error": f"Insufficient {cfg.htf} data for trend alignment."}
    if df_15.empty or len(df_15) < cfg.min_ltf_bars:
        return {"ticker": ticker, "error": f"Insufficient {cfg.ltf} data for POI / sweep model."}

    htf = _structure_bias(df_1h, cfg)
    ltf = _structure_bias(df_15, cfg)
    pois = _pick_pois(ltf["df"], ltf["bias"] if ltf["bias"] != Bias.NEUTRAL else htf["bias"], cfg)
    liquidity = _liquidity_levels(ltf["swings"], htf["bias"] if htf["bias"] != Bias.NEUTRAL else ltf["bias"])
    ltp = float(ltf["df"]["Close"].iloc[-1])

    live = evaluate_live_signal(
        {"htf": htf, "ltf": ltf, "pois": pois, "liquidity": liquidity, "ltp": ltp},
        cfg,
    )

    return {
        "ticker": ticker,
        "market": market,
        "htf": cfg.htf,
        "ltf": cfg.ltf,
        "entry_style": cfg.entry_style,
        "bars_htf": len(df_1h),
        "bars_ltf": len(df_15),
        "last_close": ltp,
        "htf_bias": htf["bias"].value,
        "ltf_bias": ltf["bias"].value,
        "poi_count": len(pois),
        "pois": [
            {k: v for k, v in p.items() if k in ("kind", "zone_low", "zone_high", "extreme")}
            for p in pois
        ],
        "youtube": YOUTUBE_SCALP_GOLD_URL,
        "live": live,
    }


def scan_scalp_gold_signals(
    df_htf: pd.DataFrame,
    df_ltf: pd.DataFrame,
    cfg: ScalpGoldConfig,
) -> list[dict[str, Any]]:
    """Historical Gold scalp entries on the LTF (1H bias = snapshot).

    HTF structure bias is computed once on the full 1H frame (same approximation
    as silver-bullet / BB+VWAP hub backtests). 15m POI / sweep / MSS is walked.
    """
    cfg = cfg or ScalpGoldConfig()
    signals: list[dict[str, Any]] = []
    if df_htf is None or df_htf.empty or len(df_htf) < cfg.min_htf_bars:
        return signals
    if df_ltf is None or df_ltf.empty or len(df_ltf) < cfg.min_ltf_bars:
        return signals

    htf = _structure_bias(df_htf, cfg)
    if htf["bias"] == Bias.NEUTRAL:
        return signals

    cooldown = max(6, int(cfg.max_mss_age_bars))
    step = 2
    next_i = cfg.min_ltf_bars
    n = len(df_ltf)

    while next_i < n:
        i = next_i
        window = df_ltf.iloc[: i + 1]
        if len(window) < cfg.min_ltf_bars:
            next_i = i + step
            continue
        try:
            ltf = _structure_bias(window, cfg)
            # Need aligned bias on the sliced LTF too
            if ltf["bias"] != htf["bias"] or ltf["bias"] == Bias.NEUTRAL:
                next_i = i + step
                continue
            pois = _pick_pois(ltf["df"], ltf["bias"], cfg)
            liquidity = _liquidity_levels(ltf["swings"], htf["bias"])
            ltp = float(ltf["df"]["Close"].iloc[-1])
            live = evaluate_live_signal(
                {"htf": htf, "ltf": ltf, "pois": pois, "liquidity": liquidity, "ltp": ltp},
                cfg,
            )
        except Exception:
            logger.debug("Scalp Gold bar scan failed at %s", i, exc_info=True)
            next_i = i + step
            continue

        if live.get("take_trade") and live.get("direction") in ("LONG", "SHORT"):
            ts = window.index[-1] if len(window) else df_ltf.index[i]
            signals.append({
                "bar_index": i,
                "direction": live["direction"],
                "time": str(pd.Timestamp(ts)),
                "confidence_pct": live.get("confidence_pct"),
                "phase": live.get("phase"),
                "entry_price": live.get("entry_price"),
                "stop_price": live.get("stop_price"),
                "target_price": live.get("target_price"),
                "entry_style": cfg.entry_style,
            })
            next_i = i + cooldown
        else:
            next_i = i + step

    return signals


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: ScalpGoldConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or ScalpGoldConfig()
    # If caller passes nothing useful, fall back to gold suggestions.
    use = [t for t in tickers if t] or list(GOLD_SUGGESTED)
    results = []
    for ticker in use:
        try:
            results.append(analyze_ticker(ticker, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            logger.exception("Scalp Gold failed for %s", ticker)
            results.append({"ticker": ticker, "error": str(exc)[:220]})

    entries = [r for r in results if not r.get("error") and (r.get("live") or {}).get("take_trade")]
    watches = [
        r for r in results
        if not r.get("error")
        and not (r.get("live") or {}).get("take_trade")
        and str((r.get("live") or {}).get("verdict") or "").startswith("WATCH")
    ]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))
    watches.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market,
        "strategy": "Scalping — Gold (The Trading Geek 5-step)",
        "youtube": YOUTUBE_SCALP_GOLD_URL,
        "entry_style": cfg.entry_style,
        "htf": cfg.htf,
        "ltf": cfg.ltf,
        "suggested_symbols": GOLD_SUGGESTED,
        "results": results,
        "entries": entries,
        "watchlist": watches,
        "entry_count": len(entries),
        "watch_count": len(watches),
        "disclaimer": "Research / education only — not financial advice. Gold moves fast; size risk tightly.",
    }
