"""
smc_lewiskelly_engine.py
---------------------------
C-LewisKelly — Lewis Kelly's intraday Smart Money Concepts framework:
Direction (15m external market structure) -> Targets (session/daily liquidity)
-> Location (15m Order Block + Fair Value Gap confluence = POI) -> Confirmation
& Entry (1m Change of Character at the POI).

1. Direction (15m Market Structure)
   External market structure only (ignore internal chop). BOS = trend
   continuation, CHoCH = reversal. Drives the trade's bias.

2. Targets (Liquidity)
   Price moves to hunt liquidity — session highs/lows and the Previous Day
   High/Low (PDH/PDL) are the take-profit levels: session liquidity as TP1,
   PDH/PDL as TP2.

3. Location (Order Blocks & Fair Value Gaps)
   A Point of Interest (POI) is a 15m Order Block sitting alongside a 15m
   Fair Value Gap (the impulsive leg's imbalance) — where price is expected
   to return to before continuing.

4. Confirmation & Entry (1-Minute Timeframe)
   Once price taps the 15m POI, drop to 1m and wait for a Change of Character
   (a body-close beyond the 1m swing extreme — wicks don't count) confirming
   the reversal back in the 15m bias's direction. Entry is on the 1m Order
   Block/FVG that caused that CHoCH; stop beyond the 1m structural swing
   (not the exact wick).

Reuses the shared `smc_engine` primitives (fractal swings, structure breaks,
FVG/Order Block detection) already used by `scalp_smc_engine.py` and
`smc_sc_best_engine.py` — only the session-liquidity mapping and the
15m-POI/1m-CHoCH sequencing are new.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.smart_money_shared import enrich_smc_live, hold_for_tf
from app.trading_hubs.smc_engine.adapters import to_smc_ohlc
from app.trading_hubs.smc_engine.config import SMCConfig
from app.trading_hubs.smc_engine.imbalances import detect_fvgs, detect_order_blocks
from app.trading_hubs.smc_engine.models import Bias, FairValueGap, OrderBlock, StructureEvent
from app.trading_hubs.smc_engine.structure import current_bias, detect_structure_breaks, find_fractal_swings
from app.trading_hubs.smc_sc_best_engine import _phase_for_zone

logger = logging.getLogger(__name__)

YOUTUBE_LEWISKELLY_URL = "https://www.youtube.com/watch?v=5wm-2G6Of3c"

HTF_OPTIONS = ["5m", "15m", "30m", "1h"]
_MIN_HTF_BARS = 60
_MIN_LTF_BARS = 60


@dataclass
class LewisKellyConfig:
    htf_tf: str = "15m"
    ltf_tf: str = "1m"
    fractal_window: int = 2
    displacement_multiplier: float = 1.5
    htf_lookback_bars: int = 500
    ltf_lookback_bars: int = 500
    recent_choch_bars: int = 15  # 1m CHoCH must be within this many bars of "now" to count as live
    asia_start_hour: int = 0
    asia_end_hour: int = 8
    london_start_hour: int = 7
    london_end_hour: int = 16
    sl_buffer_pct: float = 0.15  # % beyond the broken 1m swing, so the stop isn't glued to the exact level
    take_confidence_threshold: float = 62.0


# ---------------------------------------------------------------------------
# Data fetch
# ---------------------------------------------------------------------------

def _fetch_tf_data(
    ticker: str, market: str, timeframe: str, limit: int, *, groww_token: str = "", exchange: str = "NSE",
) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    df = fetch_data_for_gap_scan(ticker, timeframe, market, groww_token, exchange, limit=limit)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < _MIN_HTF_BARS:
        df = normalize_ohlcv(fetch_ohlcv_yfinance(ticker, timeframe, is_crypto=is_crypto, limit=limit, market=market))
    return df


# ---------------------------------------------------------------------------
# Step 2 — Targets: session & daily liquidity
# ---------------------------------------------------------------------------

def compute_session_liquidity(df: pd.DataFrame, cfg: LewisKellyConfig) -> dict[str, Any]:
    """Asia / London session High-Low (most recent completed-or-in-progress
    session) plus Previous Day High/Low, read directly off the data's own
    timestamps. Session hours are UTC by convention — if your feed reports in
    exchange-local time, adjust asia_*/london_* hours in the config to match."""
    work = df.copy()
    if not isinstance(work.index, pd.DatetimeIndex):
        try:
            work.index = pd.to_datetime(work.index)
        except Exception:
            return {"asia": None, "london": None, "pdh": None, "pdl": None}

    hours = work.index.hour
    dates = work.index.date
    unique_dates = sorted(set(dates))
    today = unique_dates[-1]
    prev_date = unique_dates[-2] if len(unique_dates) >= 2 else None

    def _session_hilo(start_h: int, end_h: int, target_date) -> dict | None:
        if target_date is None:
            return None
        mask = (dates == target_date) & (hours >= start_h) & (hours < end_h)
        sub = work[mask]
        if sub.empty:
            return None
        return {"high": float(sub["high"].max()), "low": float(sub["low"].min()), "date": str(target_date)}

    asia = _session_hilo(cfg.asia_start_hour, cfg.asia_end_hour, today) or \
        _session_hilo(cfg.asia_start_hour, cfg.asia_end_hour, prev_date)
    london = _session_hilo(cfg.london_start_hour, cfg.london_end_hour, today) or \
        _session_hilo(cfg.london_start_hour, cfg.london_end_hour, prev_date)

    pdh = pdl = None
    if prev_date is not None:
        prev_day_df = work[dates == prev_date]
        if not prev_day_df.empty:
            pdh = float(prev_day_df["high"].max())
            pdl = float(prev_day_df["low"].min())

    return {"asia": asia, "london": london, "pdh": pdh, "pdl": pdl}


def _liquidity_targets(session_liq: dict, bias: Bias, spot: float) -> dict[str, Any]:
    """TP1 = nearest not-yet-swept session liquidity in the trade's direction;
    TP2 = PDH (bullish) / PDL (bearish)."""
    candidates = []
    for key in ("asia", "london"):
        s = session_liq.get(key)
        if not s:
            continue
        level = s["high"] if bias == Bias.BULLISH else s["low"]
        swept = (level <= spot) if bias == Bias.BULLISH else (level >= spot)
        if not swept:
            candidates.append((abs(level - spot), level, f"{key.title()} {'High' if bias == Bias.BULLISH else 'Low'}"))

    tp1_price = tp1_label = None
    if candidates:
        candidates.sort(key=lambda c: c[0])
        _, tp1_price, tp1_label = candidates[0]

    tp2_price = session_liq.get("pdh") if bias == Bias.BULLISH else session_liq.get("pdl")
    tp2_label = "PDH" if bias == Bias.BULLISH else "PDL"

    return {"tp1_price": tp1_price, "tp1_label": tp1_label, "tp2_price": tp2_price, "tp2_label": tp2_label}


# ---------------------------------------------------------------------------
# Step 3 — Location: 15m Order Block + FVG confluence (POI)
# ---------------------------------------------------------------------------

def find_poi(fvgs: list[FairValueGap], order_blocks: list[OrderBlock], bias: Bias) -> dict[str, Any] | None:
    """A 15m Order Block sitting alongside (overlapping) a same-direction,
    still-unmitigated Fair Value Gap. Returns the most recent such confluence."""
    if bias == Bias.NEUTRAL:
        return None
    want_bullish = bias == Bias.BULLISH
    obs = [ob for ob in order_blocks if ob.bullish == want_bullish and not ob.mitigated]
    gaps = [g for g in fvgs if g.bullish == want_bullish and not g.mitigated]

    best = None
    for ob in obs:
        for g in gaps:
            if ob.low <= g.ceiling and ob.high >= g.floor:  # zones overlap
                idx = max(ob.index, g.index)
                if best is None or idx > best["index"]:
                    best = {
                        "zone_top": max(ob.high, g.ceiling), "zone_bottom": min(ob.low, g.floor),
                        "ob_index": ob.index, "fvg_index": g.index, "index": idx,
                    }
    return best


# ---------------------------------------------------------------------------
# Step 4 — Confirmation & Entry (1m CHoCH)
# ---------------------------------------------------------------------------

def _nearest_zone(zones: list, before_index: int, want_bullish: bool):
    """Nearest same-direction OB/FVG at or just before `before_index` — the
    zone whose impulsive move is presumed to have caused the CHoCH there."""
    candidates = [z for z in zones if z.bullish == want_bullish and z.index <= before_index]
    if not candidates:
        return None
    return max(candidates, key=lambda z: z.index)


def _zone_bounds(zone) -> tuple[float, float]:
    if isinstance(zone, FairValueGap):
        return zone.floor, zone.ceiling
    return zone.low, zone.high


def find_ltf_entry(
    df_ltf: pd.DataFrame, bias: Bias, smc_cfg: SMCConfig, *, recent_choch_bars: int,
) -> dict[str, Any] | None:
    swings = find_fractal_swings(df_ltf, smc_cfg.fractal_window)
    breaks = detect_structure_breaks(df_ltf, swings)
    if not breaks:
        return None

    last_idx = len(df_ltf) - 1
    wanted = (StructureEvent.CHOCH_BULL, StructureEvent.BOS_BULL) if bias == Bias.BULLISH else (StructureEvent.CHOCH_BEAR, StructureEvent.BOS_BEAR)
    trigger = next(
        (br for br in reversed(breaks) if br.event in wanted and last_idx - br.index <= recent_choch_bars),
        None,
    )
    if trigger is None:
        return None

    want_bullish = bias == Bias.BULLISH
    obs = detect_order_blocks(df_ltf, smc_cfg)
    fvgs = detect_fvgs(df_ltf, smc_cfg)
    entry_zone = _nearest_zone(obs, trigger.index, want_bullish) or _nearest_zone(fvgs, trigger.index, want_bullish)

    zone_bottom, zone_top = (0.0, 0.0)
    zone_kind = "None"
    if entry_zone is not None:
        zone_bottom, zone_top = _zone_bounds(entry_zone)
        zone_kind = "Order Block" if isinstance(entry_zone, OrderBlock) else "Fair Value Gap"

    is_choch = trigger.event in (StructureEvent.CHOCH_BULL, StructureEvent.CHOCH_BEAR)
    return {
        "trigger_index": trigger.index, "trigger_price": trigger.price, "trigger_is_choch": is_choch,
        "swing_price": trigger.reference_swing.price,  # the broken 1m swing — the SL anchor, not the wick
        "zone_kind": zone_kind, "zone_top": zone_top, "zone_bottom": zone_bottom,
        "phase": _phase_for_zone(df_ltf, zone_bottom, zone_top, last_idx) if entry_zone is not None else "AT_ZONE",
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def analyze_ticker(
    ticker: str, market: str, *, cfg: LewisKellyConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or LewisKellyConfig()
    smc_cfg = SMCConfig(fractal_window=cfg.fractal_window, displacement_multiplier=cfg.displacement_multiplier)

    htf_raw = _fetch_tf_data(ticker, market, cfg.htf_tf, cfg.htf_lookback_bars, groww_token=groww_token, exchange=exchange)
    if htf_raw.empty or len(htf_raw) < _MIN_HTF_BARS:
        return {"ticker": ticker, "market": market, "error": f"Insufficient {cfg.htf_tf} data ({len(htf_raw)} bars, need {_MIN_HTF_BARS}+)."}

    df_htf = to_smc_ohlc(htf_raw)
    htf_swings = find_fractal_swings(df_htf, smc_cfg.fractal_window)
    htf_breaks = detect_structure_breaks(df_htf, htf_swings)
    bias = current_bias(htf_breaks)
    last_break = htf_breaks[-1] if htf_breaks else None

    session_liq = compute_session_liquidity(htf_raw, cfg)
    spot = float(df_htf["Close"].iloc[-1])
    targets = _liquidity_targets(session_liq, bias, spot) if bias != Bias.NEUTRAL else {}

    fvgs = detect_fvgs(df_htf, smc_cfg)
    obs = detect_order_blocks(df_htf, smc_cfg)
    poi = find_poi(fvgs, obs, bias)

    tapped = False
    if poi is not None:
        recent = df_htf.iloc[-5:]
        tapped = bool(((recent["Low"] <= poi["zone_top"]) & (recent["High"] >= poi["zone_bottom"])).any())

    reasons: list[str] = []
    if bias != Bias.NEUTRAL:
        reasons.append(
            f"Direction (15m): external structure is **{bias.value.upper()}**"
            + (f" — last break {last_break.event.value} at {last_break.price:.6g}" if last_break else "") + "."
        )
    else:
        reasons.append("Direction (15m): no clear external bias yet (choppy/neutral structure).")

    if targets.get("tp1_price") is not None:
        reasons.append(f"Targets: TP1 {targets['tp1_label']} {targets['tp1_price']:.6g}" +
                        (f" · TP2 {targets['tp2_label']} {targets['tp2_price']:.6g}" if targets.get("tp2_price") else "") + ".")
    elif bias != Bias.NEUTRAL:
        reasons.append("Targets: no unswept session liquidity found ahead in this direction yet — PDH/PDL only.")

    if poi is not None:
        reasons.append(
            f"Location: 15m POI (OB + FVG confluence) at {poi['zone_bottom']:.6g}–{poi['zone_top']:.6g}"
            + (" — **tapped**, watching 1m for confirmation." if tapped else " — not tapped yet.")
        )
    else:
        reasons.append("Location: no 15m Order Block + FVG confluence found yet.")

    verdict = "WAIT"
    phase = "NO_SETUP"
    take = False
    entry = stop = target = spot
    conf = 20.0
    ltf_entry = None

    if bias != Bias.NEUTRAL and poi is not None and tapped:
        ltf_raw = _fetch_tf_data(ticker, market, cfg.ltf_tf, cfg.ltf_lookback_bars, groww_token=groww_token, exchange=exchange)
        if not ltf_raw.empty and len(ltf_raw) >= _MIN_LTF_BARS:
            df_ltf = to_smc_ohlc(ltf_raw)
            ltf_entry = find_ltf_entry(df_ltf, bias, smc_cfg, recent_choch_bars=cfg.recent_choch_bars)

    if ltf_entry is not None:
        direction = "LONG" if bias == Bias.BULLISH else "SHORT"
        # Enter at the near edge of the zone that caused the CHoCH: top of a bullish
        # zone (price is above it, post-reversal), bottom of a bearish one.
        entry = ltf_entry["zone_top"] if direction == "LONG" else ltf_entry["zone_bottom"]
        if not entry:
            entry = spot
        buf = abs(ltf_entry["swing_price"]) * (cfg.sl_buffer_pct / 100.0)
        stop = ltf_entry["swing_price"] - buf if direction == "LONG" else ltf_entry["swing_price"] + buf
        target = targets.get("tp1_price") or (entry + abs(entry - stop) * 2 if direction == "LONG" else entry - abs(entry - stop) * 2)

        conf = 55.0
        conf += 15 if ltf_entry["trigger_is_choch"] else 5
        phase = ltf_entry["phase"]
        reasons.append(
            f"Confirmation (1m): {'CHoCH' if ltf_entry['trigger_is_choch'] else 'BOS'} at {ltf_entry['trigger_price']:.6g}, "
            f"body-close beyond the 1m swing {ltf_entry['swing_price']:.6g}. Entry zone: {ltf_entry['zone_kind']} "
            f"{ltf_entry['zone_bottom']:.6g}–{ltf_entry['zone_top']:.6g}."
        )
        if phase == "AT_ZONE":
            conf += 15
            verdict = f"{'TAKE' if conf >= cfg.take_confidence_threshold else 'WATCH'} {direction}"
            take = conf >= cfg.take_confidence_threshold
        else:
            verdict = f"WATCH {direction}"
            reasons.append("Price hasn't retraced into the 1m entry zone yet — waiting for the pullback, not chasing.")
    elif bias != Bias.NEUTRAL and poi is not None and tapped:
        reasons.append("Confirmation (1m): POI tapped, but no fresh 1m CHoCH/BOS found yet — still waiting.")
    elif bias != Bias.NEUTRAL and poi is not None:
        verdict = f"WATCH {'LONG' if bias == Bias.BULLISH else 'SHORT'}"
        phase = "AWAITING_TAP"

    conf = round(max(15.0, min(92.0, conf)), 1)
    sl_pct = round(abs(entry - stop) / entry * 100, 2) if entry else 1.0
    tp_pct = round(abs(target - entry) / entry * 100, 2) if entry else sl_pct * 2

    hold = hold_for_tf(cfg.ltf_tf, style="intraday")
    plan = make_trade_plan(
        direction=verdict.split()[-1] if take else "—",
        timeframe=cfg.ltf_tf, stop_loss_pct=sl_pct, take_profit_pct=tp_pct,
        confidence_pct=conf, style="intraday",
        exit_rule="Exit if price closes back through the 1m entry zone or the broken swing (structural invalidation).",
        max_hold_exit="Session-based — exit if the targeted session/day liquidity is reached or the 15m bias flips.",
    )

    direction = verdict.split()[-1] if verdict != "WAIT" else "WAIT"
    live = enrich_smc_live({
        "signal": direction if take else "NONE",
        "direction": direction, "take_trade": take, "verdict": verdict, "phase": phase,
        "confidence_pct": conf, "sl_pct": sl_pct, "tp_pct": tp_pct,
        "entry_price": round(entry, 6), "stop_price": round(stop, 6), "target_price": round(target, 6),
        "htf_bias": bias.value.upper(),
        "tp1_price": targets.get("tp1_price"), "tp1_label": targets.get("tp1_label"),
        "tp2_price": targets.get("tp2_price"), "tp2_label": targets.get("tp2_label"),
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": hold},
    }, hold_duration=hold)

    return {
        "ticker": ticker, "market": market, "htf_tf": cfg.htf_tf, "ltf_tf": cfg.ltf_tf,
        "spot": round(spot, 6), "session_liquidity": session_liq,
        "poi": poi, "poi_tapped": tapped,
        "live": live,
    }


def scan_universe(
    tickers: list[str], market: str, *, cfg: LewisKellyConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or LewisKellyConfig()
    results = []
    for ticker in tickers:
        try:
            results.append(analyze_ticker(ticker, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            results.append({"ticker": ticker, "error": str(exc)[:200]})

    entries = [r for r in results if not r.get("error") and (r.get("live") or {}).get("take_trade")]
    watches = [
        r for r in results
        if not r.get("error") and not (r.get("live") or {}).get("take_trade")
        and (r.get("live") or {}).get("verdict", "").startswith("WATCH")
    ]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))
    watches.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market, "htf_tf": cfg.htf_tf, "ltf_tf": cfg.ltf_tf, "results": results,
        "entries": entries, "watchlist": watches,
        "entry_count": len(entries), "watch_count": len(watches),
    }
