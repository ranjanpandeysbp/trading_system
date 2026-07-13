"""
smc_ttg_sniper_engine.py
--------------------------
SM - TTG - Sniper Entry — Liquidity Sweep + Order Block + Fair Value Gap.
https://www.youtube.com/watch?v=MypSrcfiqtM&t=32s

Mechanical 5-step model:
1. Identify a liquidity sweep (price runs past a prior swing high/low and closes back inside).
2. Confirm the sweep completed with a strong, obvious displacement away from it.
3. Mark the Order Block — the origin (opposite-colour) candle of that impulsive move.
4. Mark the Fair Value Gap inside/near the Order Block — the precise entry zone.
5. Wait for price to pull back into the zone, then enter:
   - Aggressive: the moment price taps the FVG/Order Block, SL beyond the zone, fixed R:R target.
   - Conservative: same tap, but wait for a lower-timeframe structure shift first.

Advanced stop tip: when there's no FVG and the Order Block is wide, the stop tightens to
just beyond the specific sweep candle's extreme instead of the whole block.

Context rule: a sweep only counts if it aligns with the higher-timeframe trend bias —
this isn't a "trade every sweep" scanner.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.smart_money_shared import enrich_smc_live, hold_for_tf

logger = logging.getLogger(__name__)

YOUTUBE_TTG_SNIPER_URL = "https://www.youtube.com/watch?v=MypSrcfiqtM&t=32s"

LTF_OPTIONS = ["5m", "15m", "30m", "1h"]
HTF_OPTIONS = ["1h", "4h", "1d"]
ENTRY_MODE_OPTIONS = ["Aggressive", "Conservative"]

PHASE_NONE = "NO_SETUP"
PHASE_MARKED = "OB_FVG_MARKED"
PHASE_ENTRY = "SNIPER_ENTRY"

HOLD_TTG_SNIPER = "TTG Sniper — fixed R:R target, exit on stop/target or setup invalidation"


@dataclass
class TTGSniperConfig:
    ltf: str = "15m"
    htf: str = "1h"
    trend_lookback: int = 20
    swing_window: int = 5
    sweep_lookback_bars: int = 40
    displacement_search_bars: int = 6
    displacement_atr_mult: float = 1.3
    entry_mode: str = "Aggressive"
    rr_ratio: float = 2.0
    max_setup_age_bars: int = 25
    require_htf_alignment: bool = True
    take_confidence_threshold: float = 60.0
    min_bars: int = 80
    lookback_bars: int = 500


# ---------------------------------------------------------------------------
# 1. HTF trend bias (context filter)
# ---------------------------------------------------------------------------

def identify_trend(df: pd.DataFrame, lookback: int = 20) -> pd.DataFrame:
    out = df.copy()
    out["sma"] = out["close"].rolling(window=lookback, min_periods=max(2, lookback // 4)).mean()
    out["trend"] = np.where(out["close"] > out["sma"], 1, -1)
    return out


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=max(2, period // 2)).mean()


def _swing_columns(df: pd.DataFrame, window: int) -> pd.DataFrame:
    out = df.copy()
    half = max(1, window // 2)
    highs = out["high"].values
    lows = out["low"].values
    n = len(out)
    swing_hi = np.full(n, np.nan)
    swing_lo = np.full(n, np.nan)

    for i in range(half, n - half):
        w_hi = highs[i - half : i + half + 1].max()
        w_lo = lows[i - half : i + half + 1].min()
        if highs[i] == w_hi:
            swing_hi[i] = highs[i]
        if lows[i] == w_lo:
            swing_lo[i] = lows[i]

    out["swing_high"] = swing_hi
    out["swing_low"] = swing_lo
    return out


# ---------------------------------------------------------------------------
# Step 1-2: Liquidity sweep detection
# ---------------------------------------------------------------------------

def detect_liquidity_sweeps(df: pd.DataFrame, cfg: TTGSniperConfig) -> list[dict[str, Any]]:
    """A sweep = price pierces a prior swing high/low and closes back inside it (the trap)."""
    swung = _swing_columns(df, cfg.swing_window)
    highs, lows, closes = swung["high"].values, swung["low"].values, swung["close"].values
    swing_hi, swing_lo = swung["swing_high"].values, swung["swing_low"].values
    n = len(swung)
    half = max(1, cfg.swing_window // 2)

    sweeps: list[dict[str, Any]] = []
    for i in range(half + 1, n):
        lookback_start = max(0, i - cfg.sweep_lookback_bars)
        window_hi = swing_hi[lookback_start : i - half]
        window_lo = swing_lo[lookback_start : i - half]
        valid_hi = window_hi[~np.isnan(window_hi)]
        valid_lo = window_lo[~np.isnan(window_lo)]

        if valid_hi.size:
            level = float(valid_hi[-1])
            if highs[i] > level and closes[i] < level:
                sweeps.append({"index": i, "direction": "SHORT", "sweep_level": level, "sweep_extreme": float(highs[i])})
        if valid_lo.size:
            level = float(valid_lo[-1])
            if lows[i] < level and closes[i] > level:
                sweeps.append({"index": i, "direction": "LONG", "sweep_level": level, "sweep_extreme": float(lows[i])})

    return sweeps


# ---------------------------------------------------------------------------
# Step 2-4: displacement -> Order Block -> Fair Value Gap
# ---------------------------------------------------------------------------

def find_setup_after_sweep(df: pd.DataFrame, sweep: dict[str, Any], atr: pd.Series, cfg: TTGSniperConfig) -> dict[str, Any] | None:
    i = sweep["index"]
    direction = sweep["direction"]
    n = len(df)
    end = min(n, i + cfg.displacement_search_bars + 1)
    window = df.iloc[i:end]
    if window.empty:
        return None

    atr_i = atr.iloc[i] if not pd.isna(atr.iloc[i]) else (df["high"] - df["low"]).iloc[max(0, i - 14) : i + 1].mean()
    if not atr_i or atr_i <= 0:
        return None

    if direction == "LONG":
        disp_pos = int(window["high"].values.argmax())
        disp_idx = i + disp_pos
        displacement = float(window["high"].iloc[disp_pos] - df["close"].iloc[i])
    else:
        disp_pos = int(window["low"].values.argmin())
        disp_idx = i + disp_pos
        displacement = float(df["close"].iloc[i] - window["low"].iloc[disp_pos])

    if displacement < cfg.displacement_atr_mult * atr_i:
        return None  # not strong/obvious enough -> "context over patterns"

    # Step 3: Order Block = last opposite-colour candle from the sweep up to the displacement peak.
    ob_idx = i
    for k in range(disp_idx, i - 1, -1):
        o, c = df["open"].iloc[k], df["close"].iloc[k]
        if direction == "LONG" and c < o:
            ob_idx = k
            break
        if direction == "SHORT" and c > o:
            ob_idx = k
            break
    else:
        ob_idx = i

    ob_top = float(df["high"].iloc[ob_idx])
    ob_bottom = float(df["low"].iloc[ob_idx])

    # Step 4: Fair Value Gap inside the impulsive leg, overlapping the Order Block.
    fvg_top = fvg_bottom = None
    for k in range(max(ob_idx + 2, i + 2), disp_idx + 1):
        if k >= n:
            break
        if direction == "LONG" and df["low"].iloc[k] > df["high"].iloc[k - 2]:
            top, bottom = float(df["low"].iloc[k]), float(df["high"].iloc[k - 2])
            if bottom <= ob_top and top >= ob_bottom:
                fvg_top, fvg_bottom = top, bottom
                break
        if direction == "SHORT" and df["high"].iloc[k] < df["low"].iloc[k - 2]:
            top, bottom = float(df["low"].iloc[k - 2]), float(df["high"].iloc[k])
            if bottom <= ob_top and top >= ob_bottom:
                fvg_top, fvg_bottom = top, bottom
                break

    has_fvg = fvg_top is not None
    zone_top = fvg_top if has_fvg else ob_top
    zone_bottom = fvg_bottom if has_fvg else ob_bottom

    return {
        "direction": direction,
        "sweep_index": i,
        "sweep_level": sweep["sweep_level"],
        "sweep_extreme": sweep["sweep_extreme"],
        "disp_index": disp_idx,
        "displacement": displacement,
        "atr": float(atr_i),
        "ob_index": ob_idx,
        "ob_top": ob_top,
        "ob_bottom": ob_bottom,
        "fvg_top": fvg_top,
        "fvg_bottom": fvg_bottom,
        "has_fvg": has_fvg,
        "zone_top": zone_top,
        "zone_bottom": zone_bottom,
    }


def _mss_confirmed(df: pd.DataFrame, direction: str, setup: dict[str, Any], cfg: TTGSniperConfig) -> bool:
    """Conservative entry: after the tap, has a lower-TF structure shift confirmed the reversal?"""
    swung = _swing_columns(df, max(3, cfg.swing_window - 2))
    tap_idx = setup["disp_index"]
    after = swung.iloc[tap_idx:]
    if direction == "LONG":
        swing_highs = after["swing_high"].dropna()
        if swing_highs.empty:
            return False
        return float(df["close"].iloc[-1]) > float(swing_highs.iloc[0])
    swing_lows = after["swing_low"].dropna()
    if swing_lows.empty:
        return False
    return float(df["close"].iloc[-1]) < float(swing_lows.iloc[0])


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_ttg_pipeline(df_ltf: pd.DataFrame, df_htf: pd.DataFrame, cfg: TTGSniperConfig) -> dict[str, Any]:
    ltf = normalize_ohlcv(df_ltf)
    htf = normalize_ohlcv(df_htf)
    if ltf.empty or len(ltf) < cfg.min_bars:
        return {"error": f"Insufficient {cfg.ltf} data."}
    if htf.empty or len(htf) < max(cfg.trend_lookback, 10):
        return {"error": f"Insufficient {cfg.htf} data."}

    htf = identify_trend(htf, cfg.trend_lookback)
    atr = _atr(ltf)
    sweeps = detect_liquidity_sweeps(ltf, cfg)

    return {"df_ltf": ltf, "df_htf": htf, "atr": atr, "sweeps": sweeps}


def evaluate_live_signal(pipeline: dict[str, Any], cfg: TTGSniperConfig) -> dict[str, Any]:
    if pipeline.get("error"):
        return {"signal": "NO_DATA"}

    ltf = pipeline["df_ltf"]
    htf = pipeline["df_htf"]
    atr = pipeline["atr"]
    sweeps = pipeline["sweeps"]
    n = len(ltf)
    price = float(ltf["close"].iloc[-1])
    trend = int(htf["trend"].iloc[-1])
    trend_label = "UPTREND" if trend == 1 else "DOWNTREND"

    reasons: list[str] = [f"HTF **{cfg.htf}** trend bias (SMA-{cfg.trend_lookback}): **{trend_label}**"]
    conf = 20.0
    direction = "WAIT"
    phase = PHASE_NONE
    verdict = "WAIT"
    stop = price
    target = price
    setup: dict[str, Any] | None = None

    candidates = [s for s in sweeps if s["index"] >= n - 1 - cfg.max_setup_age_bars]
    candidates.sort(key=lambda s: -s["index"])

    for sw in candidates:
        if cfg.require_htf_alignment:
            wanted_trend = 1 if sw["direction"] == "LONG" else -1
            if wanted_trend != trend:
                continue
        result = find_setup_after_sweep(ltf, sw, atr, cfg)
        if result:
            setup = result
            break

    if setup is None:
        reasons.append(
            "No fresh, HTF-aligned liquidity sweep with strong displacement found in the lookback window "
            "— per the strategy's own rule, sit on your hands rather than force a trade."
        )
        conf = 20.0
    else:
        direction = setup["direction"]
        phase = PHASE_MARKED
        conf += 18
        reasons.append(
            f"**Step 1-2 — Liquidity sweep:** price swept the prior swing "
            f"{'high' if direction == 'SHORT' else 'low'} at **{setup['sweep_level']:,.4g}** and closed back "
            "inside — the trap is confirmed."
        )
        conf += 10
        reasons.append(
            f"Displacement after the sweep measured **{setup['displacement']:,.4g}** "
            f"(**{setup['displacement'] / setup['atr']:.1f}x ATR**) — a strong, obvious move, not a weak drift."
        )
        reasons.append(
            f"**Step 3 — Order Block:** marked at **{setup['ob_bottom']:,.4g} – {setup['ob_top']:,.4g}** "
            "(origin candle of the impulsive move)."
        )
        if setup["has_fvg"]:
            conf += 14
            reasons.append(
                f"**Step 4 — Fair Value Gap:** found inside the Order Block at "
                f"**{setup['fvg_bottom']:,.4g} – {setup['fvg_top']:,.4g}** — this is the precise entry zone."
            )
        else:
            reasons.append(
                "**Step 4 — Fair Value Gap:** none formed inside the Order Block — the entry zone falls back "
                "to the full Order Block (wider; the stop below is tightened to compensate)."
            )

        zone_top, zone_bottom = setup["zone_top"], setup["zone_bottom"]
        tap_window = ltf.iloc[setup["disp_index"] :]
        tapped = bool(((tap_window["low"] <= zone_top) & (tap_window["high"] >= zone_bottom)).any())

        buffer = max((zone_top - zone_bottom) * 0.1, price * 0.0005)
        wide_ob = (not setup["has_fvg"]) and (setup["ob_top"] - setup["ob_bottom"]) > 1.2 * setup["atr"]

        if direction == "LONG":
            if wide_ob:
                stop = setup["sweep_extreme"] - buffer
                reasons.append(
                    f"**Advanced stop tip:** the Order Block is wide with no FVG, so the stop is tightened to "
                    f"just below the sweep low **{setup['sweep_extreme']:,.4g}** instead of the whole block — "
                    "if that protected level breaks, the trade idea is dead anyway."
                )
            else:
                stop = zone_bottom - buffer
            entry_ref = zone_bottom if not tapped else price
            invalidated = price < stop
        else:
            if wide_ob:
                stop = setup["sweep_extreme"] + buffer
                reasons.append(
                    f"**Advanced stop tip:** the Order Block is wide with no FVG, so the stop is tightened to "
                    f"just above the sweep high **{setup['sweep_extreme']:,.4g}** instead of the whole block — "
                    "if that protected level breaks, the trade idea is dead anyway."
                )
            else:
                stop = zone_top + buffer
            entry_ref = zone_top if not tapped else price
            invalidated = price > stop

        risk = abs(entry_ref - stop) or max(price * 0.002, 0.01)
        target = entry_ref + risk * cfg.rr_ratio if direction == "LONG" else entry_ref - risk * cfg.rr_ratio

        if invalidated:
            phase = PHASE_NONE
            direction = "WAIT"
            verdict = "INVALIDATED"
            reasons.append("Price closed beyond the stop level — setup invalidated, the sweep thesis is dead.")
            conf = 18.0
        elif not tapped:
            verdict = f"WATCH {direction}"
            reasons.append("**Step 5 — waiting for pullback:** price hasn't tapped back into the entry zone yet.")
        elif cfg.entry_mode == "Aggressive":
            phase = PHASE_ENTRY
            verdict = f"TAKE {direction}"
            conf += 26
            reasons.append(
                "**Step 5 — Aggressive entry:** price tapped the FVG/Order Block — entry triggered immediately, "
                f"targeting a fixed **{cfg.rr_ratio:.0f}R**."
            )
        else:
            if _mss_confirmed(ltf, direction, setup, cfg):
                phase = PHASE_ENTRY
                verdict = f"TAKE {direction}"
                conf += 30
                reasons.append(
                    "**Step 5 — Conservative entry:** price tapped the zone AND a lower-timeframe market "
                    f"structure shift confirmed the reversal — targeting a fixed **{cfg.rr_ratio:.0f}R**."
                )
            else:
                verdict = f"WATCH {direction}"
                reasons.append(
                    "Price tapped the zone, but conservative mode is waiting for a market-structure-shift "
                    "confirmation before entering."
                )

    conf = max(15.0, min(93.0, conf))
    take = phase == PHASE_ENTRY and conf >= cfg.take_confidence_threshold

    if direction == "LONG" and stop < price:
        sl_pct = max(0.15, (price - stop) / price * 100)
        tp_pct = max(0.2, (target - price) / price * 100) if target > price else sl_pct * cfg.rr_ratio
    elif direction == "SHORT" and stop > price:
        sl_pct = max(0.15, (stop - price) / price * 100)
        tp_pct = max(0.2, (price - target) / price * 100) if target < price else sl_pct * cfg.rr_ratio
    else:
        sl_pct = 0.4
        tp_pct = sl_pct * cfg.rr_ratio

    hold = hold_for_tf(cfg.ltf, "intraday" if cfg.ltf in ("5m", "15m", "30m") else "swing")
    plan = make_trade_plan(
        direction=direction if take and direction in ("LONG", "SHORT") else "—",
        timeframe=cfg.ltf,
        stop_loss_pct=round(sl_pct, 2),
        take_profit_pct=round(tp_pct, 2),
        confidence_pct=round(conf, 1),
        style="intraday",
        exit_rule=f"Fixed {cfg.rr_ratio:.0f}R target. Exit if price closes beyond the sweep/zone stop (setup invalidated).",
        max_hold_exit=f"Time stop per {cfg.ltf} scalp window if neither SL nor TP hits.",
    )

    return enrich_smc_live({
        "signal": direction if phase == PHASE_ENTRY else "NONE",
        "direction": direction,
        "take_trade": take,
        "verdict": verdict,
        "phase": phase,
        "confidence_pct": round(conf, 1),
        "sl_pct": round(sl_pct, 2),
        "tp_pct": round(tp_pct, 2),
        "hold_duration": hold,
        "rr_ratio": cfg.rr_ratio,
        "entry_price": round(price, 6),
        "stop_price": round(stop, 6),
        "target_price": round(target, 6),
        "sweep_level": setup.get("sweep_level") if setup else None,
        "sweep_extreme": setup.get("sweep_extreme") if setup else None,
        "ob_top": setup.get("ob_top") if setup else None,
        "ob_bottom": setup.get("ob_bottom") if setup else None,
        "fvg_top": setup.get("fvg_top") if setup else None,
        "fvg_bottom": setup.get("fvg_bottom") if setup else None,
        "has_fvg": setup.get("has_fvg") if setup else None,
        "entry_mode": cfg.entry_mode,
        "trend": trend_label,
        "htf": cfg.htf,
        "ltf": cfg.ltf,
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": hold},
    }, hold_duration=hold)


def _signal_history(sweeps: list[dict[str, Any]], df: pd.DataFrame, limit: int = 8) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sw in sorted(sweeps, key=lambda s: -s["index"]):
        i = sw["index"]
        if i >= len(df):
            continue
        ts = df.index[i]
        rows.append({
            "time": ts.strftime("%Y-%m-%d %H:%M") if hasattr(ts, "strftime") else str(ts),
            "direction": sw["direction"],
            "sweep_level": round(sw["sweep_level"], 4),
            "sweep_extreme": round(sw["sweep_extreme"], 4),
        })
        if len(rows) >= limit:
            break
    return rows


def fetch_exec_data(
    ticker: str,
    market: str,
    cfg: TTGSniperConfig,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    is_crypto = "CoinDCX" in market
    df_ltf = fetch_data_for_gap_scan(ticker, cfg.ltf, market, groww_token, exchange, limit=cfg.lookback_bars)
    df_ltf = normalize_ohlcv(df_ltf)
    if df_ltf.empty or len(df_ltf) < cfg.min_bars:
        df_ltf = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, cfg.ltf, is_crypto=is_crypto, limit=cfg.lookback_bars, market=market),
        )

    df_htf = fetch_data_for_gap_scan(ticker, cfg.htf, market, groww_token, exchange, limit=max(120, cfg.lookback_bars // 4))
    df_htf = normalize_ohlcv(df_htf)
    if df_htf.empty:
        df_htf = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, cfg.htf, is_crypto=is_crypto, limit=max(120, cfg.lookback_bars // 4), market=market),
        )

    return df_ltf, df_htf


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: TTGSniperConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or TTGSniperConfig()
    df_ltf, df_htf = fetch_exec_data(ticker, market, cfg, groww_token=groww_token, exchange=exchange)
    if df_ltf.empty or len(df_ltf) < cfg.min_bars:
        return {"ticker": ticker, "error": f"Insufficient {cfg.ltf} data."}
    if df_htf.empty:
        return {"ticker": ticker, "error": f"Insufficient {cfg.htf} data."}

    pipeline = run_ttg_pipeline(df_ltf, df_htf, cfg)
    if pipeline.get("error"):
        return {"ticker": ticker, "error": pipeline["error"]}

    live = evaluate_live_signal(pipeline, cfg)

    return {
        "ticker": ticker,
        "market": market,
        "htf": cfg.htf,
        "ltf": cfg.ltf,
        "bars_htf": len(pipeline["df_htf"]),
        "bars_ltf": len(pipeline["df_ltf"]),
        "last_close": float(pipeline["df_ltf"]["close"].iloc[-1]),
        "signal_history": _signal_history(pipeline["sweeps"], pipeline["df_ltf"]),
        "live": live,
    }


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: TTGSniperConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or TTGSniperConfig()
    results = []
    for ticker in tickers:
        try:
            results.append(analyze_ticker(ticker, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            results.append({"ticker": ticker, "error": str(exc)[:200]})

    entries = [r for r in results if not r.get("error") and (r.get("live") or {}).get("take_trade")]
    watches = [
        r for r in results
        if not r.get("error")
        and not (r.get("live") or {}).get("take_trade")
        and (r.get("live") or {}).get("verdict", "").startswith("WATCH")
    ]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))
    watches.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market,
        "htf": cfg.htf,
        "ltf": cfg.ltf,
        "results": results,
        "entries": entries,
        "watchlist": watches,
        "entry_count": len(entries),
        "watch_count": len(watches),
    }
