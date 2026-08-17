"""
swing_fire_engine.py
--------------------
Swing - FIRE — Harsh (FIRE) equity swing playbook mechanized for Trading Hubs.

Research / education only — NOT FINANCIAL ADVICE.

Core ideas from the interview:
  1. Equity cash only — avoid F&O wipeouts; concentrate (few names), cap loss ~10%.
  2. Prefer strength / all-time-high leaders — not falling knives at 52w lows.
  3. Sector leaders that print new highs while the index is sideways.
  4. IPO / VCP bases (Minervini): contracting pullback depths → tightness → breakout;
     trail with 21 EMA (or 63 EMA); exit on 2 consecutive red closes below the trail EMA;
     re-enter when price reclaims the trail EMA.
  5. Market-cycle ROC (monthly):
       - Large-cap / Nifty-style: length 18 → aggressive near 0, de-risk near 45.
       - Small-cap style: length 20 → aggressive near 0, de-risk near 100.
  6. Nifty / Gold relative channel: near the bottom → equity preferred; near the top → caution.

This engine is long-only (matching the cash/IPO/VCP framing). Fundamentals (ROE/ROC>20%,
RHP, niche product) and Chittorgarh IPO lists are human/AI research overlays — disclosed
in the guide, not faked as automated PE/EPS screens here.
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
from app.market_pulse.weak_strong_engine import _benchmark_symbol
from app.trading_hubs.intraday_shared import enrich_intra_live

logger = logging.getLogger(__name__)

STRATEGY_ID = "swing_fire"
HOLD_SWING_FIRE = "Swing weeks–months — trail 21/63 EMA; exit on 2 red closes below trail; reclaim = re-entry"

ROC_MODE_LARGE = "largecap"
ROC_MODE_SMALL = "smallcap"
ROC_MODE_OPTIONS = [ROC_MODE_LARGE, ROC_MODE_SMALL]

TRAIL_EMA21 = "ema21"
TRAIL_EMA63 = "ema63"
TRAIL_OPTIONS = [TRAIL_EMA21, TRAIL_EMA63]

REGIME_ON = "on"
REGIME_OFF = "off"
REGIME_OPTIONS = [REGIME_ON, REGIME_OFF]


@dataclass
class SwingFireConfig:
    execution_tf: str = "1d"
    trail_ema: str = TRAIL_EMA21
    roc_mode: str = ROC_MODE_SMALL
    regime_filter: str = REGIME_ON
    max_sl_pct: float = 10.0
    ath_proximity_pct: float = 18.0
    swing_window: int = 5
    vcp_min_contractions: int = 2
    vcp_lookback_bars: int = 80
    tightness_bars: int = 8
    tightness_max_range_pct: float = 10.0
    exit_red_closes: int = 2
    rr_ratio: float = 2.0
    recent_bars: int = 3
    take_confidence_threshold: float = 55.0
    lookback: int = 420
    min_bars: int = 120
    regime_lookback: int = 520


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _r(v: float | None, n: int = 4) -> float | None:
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return None
    return round(float(v), n)


def _fetch_daily(
    ticker: str, market: str, *, groww_token: str = "", exchange: str = "NSE", limit: int = 420,
) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    df = fetch_data_for_gap_scan(ticker, "1d", market, groww_token, exchange, limit=limit)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < 60:
        df = normalize_ohlcv(fetch_ohlcv_yfinance(ticker, "1d", is_crypto=is_crypto, limit=limit, market=market))
    return df


def add_swing_fire_indicators(df: pd.DataFrame, cfg: SwingFireConfig) -> pd.DataFrame:
    out = df.copy()
    out["ema21"] = _ema(out["close"], 21)
    out["ema63"] = _ema(out["close"], 63)
    out["trail"] = out["ema21"] if cfg.trail_ema == TRAIL_EMA21 else out["ema63"]
    out["vol_ma20"] = out["volume"].rolling(20).mean()
    # Trailing ATH / 52w-style high over available history (capped lookback).
    hi_win = min(252, max(60, len(out) - 1))
    out["ath_trail"] = out["high"].rolling(hi_win, min_periods=min(40, hi_win)).max()
    return out


def _trail_period(cfg: SwingFireConfig) -> int:
    return 21 if cfg.trail_ema == TRAIL_EMA21 else 63


def _roc_settings(cfg: SwingFireConfig) -> tuple[int, float]:
    """Return (monthly ROC length, sell/de-risk threshold)."""
    if cfg.roc_mode == ROC_MODE_LARGE:
        return 18, 45.0
    return 20, 100.0


def _monthly_roc(daily: pd.DataFrame, length: int) -> float | None:
    if daily.empty or len(daily) < length * 15:
        return None
    try:
        monthly = daily["close"].resample("ME").last().dropna()
    except Exception:
        monthly = daily["close"].resample("M").last().dropna()
    if len(monthly) < length + 1:
        return None
    last = float(monthly.iloc[-1])
    prev = float(monthly.iloc[-(length + 1)])
    if prev <= 0:
        return None
    return (last / prev - 1.0) * 100.0


def _regime_benchmark(market: str, cfg: SwingFireConfig) -> str:
    if "CoinDCX" in market or "crypto" in market.lower():
        return "BTC"
    if "US" in market or "Yahoo" in market:
        return "SPY"
    if cfg.roc_mode == ROC_MODE_SMALL:
        return "NIFTY SMALLCAP 100"
    return "NIFTY 50"


def _gold_symbol(market: str) -> str | None:
    if "CoinDCX" in market or "crypto" in market.lower():
        return None
    if "US" in market or "Yahoo" in market:
        return "GLD"
    return "GOLDBEES"


def compute_market_regime(
    market: str,
    cfg: SwingFireConfig,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    """Monthly ROC cycle + optional Nifty/Gold (or SPY/GLD) relative preference."""
    length, sell_thr = _roc_settings(cfg)
    bench = _regime_benchmark(market, cfg)
    info: dict[str, Any] = {
        "benchmark": bench,
        "roc_length_months": length,
        "roc_sell_threshold": sell_thr,
        "roc_pct": None,
        "regime": "UNKNOWN",
        "equity_vs_gold": None,
        "equity_pref": "UNKNOWN",
        "aggressive_ok": True,
        "notes": [],
    }

    try:
        bdf = _fetch_daily(bench, market, groww_token=groww_token, exchange=exchange, limit=cfg.regime_lookback)
        roc = _monthly_roc(bdf, length) if not bdf.empty else None
        info["roc_pct"] = _r(roc, 2)
        if roc is None:
            info["notes"].append("Could not compute monthly ROC — regime filter soft-passes.")
            info["regime"] = "UNKNOWN"
        elif roc <= 8.0:
            info["regime"] = "ACCUMULATE"
            info["notes"].append(
                f"Monthly ROC({length}) ≈ {roc:.1f}% near 0 → historically best time to go aggressive in equity."
            )
        elif roc >= sell_thr * 0.85:
            info["regime"] = "DISTRIBUTE"
            info["aggressive_ok"] = False
            info["notes"].append(
                f"Monthly ROC({length}) ≈ {roc:.1f}% near {sell_thr:g} → de-risk equity "
                "(shift toward gold / bonds / smaller size)."
            )
        else:
            info["regime"] = "NEUTRAL"
            info["notes"].append(f"Monthly ROC({length}) ≈ {roc:.1f}% — mid-cycle; selective setups only.")

        # Crossing back above zero from negative (visual entry cue from the talk).
        if roc is not None and -5.0 <= roc <= 5.0:
            info["notes"].append("ROC near zero — watch for a reclaim of the zero line as an aggressive-entry cue.")
    except Exception as exc:
        logger.debug("Swing-FIRE regime ROC failed: %s", exc)
        info["notes"].append(f"Regime ROC unavailable ({exc.__class__.__name__}).")

    gold = _gold_symbol(market)
    if gold:
        try:
            eq_sym, _ = _benchmark_symbol(market)
            edf = _fetch_daily(eq_sym, market, groww_token=groww_token, exchange=exchange, limit=cfg.regime_lookback)
            gdf = _fetch_daily(gold, market, groww_token=groww_token, exchange=exchange, limit=cfg.regime_lookback)
            if not edf.empty and not gdf.empty:
                joined = edf[["close"]].rename(columns={"close": "eq"}).join(
                    gdf[["close"]].rename(columns={"close": "gold"}), how="inner",
                )
                joined = joined.dropna()
                if len(joined) >= 60:
                    ratio = joined["eq"] / joined["gold"].replace(0, np.nan)
                    ratio = ratio.dropna()
                    lo = float(ratio.rolling(252, min_periods=60).min().iloc[-1])
                    hi = float(ratio.rolling(252, min_periods=60).max().iloc[-1])
                    cur = float(ratio.iloc[-1])
                    info["equity_vs_gold"] = {
                        "equity": eq_sym, "gold": gold, "ratio": _r(cur, 4),
                        "range_low": _r(lo, 4), "range_high": _r(hi, 4),
                    }
                    span = hi - lo
                    if span > 0:
                        pos = (cur - lo) / span
                        if pos <= 0.25:
                            info["equity_pref"] = "EQUITY"
                            info["notes"].append(
                                f"{eq_sym}/{gold} near channel bottom → equity historically outperforms gold."
                            )
                        elif pos >= 0.75:
                            info["equity_pref"] = "GOLD"
                            info["notes"].append(
                                f"{eq_sym}/{gold} near channel top → prefer caution / gold overstretch risk."
                            )
                        else:
                            info["equity_pref"] = "BALANCED"
        except Exception as exc:
            logger.debug("Swing-FIRE equity/gold ratio failed: %s", exc)

    if cfg.regime_filter == REGIME_OFF:
        info["aggressive_ok"] = True
        info["notes"].append("Regime filter OFF — scanning regardless of ROC / equity-gold channel.")

    return info


def _find_swing_highs(high: np.ndarray, window: int) -> list[int]:
    idxs: list[int] = []
    n = len(high)
    for i in range(window, n - window):
        seg = high[i - window: i + window + 1]
        if high[i] >= np.max(seg) - 1e-12:
            idxs.append(i)
    return idxs


def _detect_vcp(
    work: pd.DataFrame, cfg: SwingFireConfig, *, end_i: int | None = None,
) -> dict[str, Any] | None:
    """Detect a Minervini-style VCP: contracting pullback depths into a pivot high + tightness."""
    if end_i is None:
        end_i = len(work) - 1
    start = max(0, end_i - cfg.vcp_lookback_bars)
    if end_i - start < 30:
        return None

    highs = work["high"].to_numpy()
    lows = work["low"].to_numpy()
    closes = work["close"].to_numpy()

    swing_hs = [i for i in _find_swing_highs(highs[start: end_i + 1], cfg.swing_window)]
    swing_hs = [start + i for i in swing_hs]
    if len(swing_hs) < 2:
        return None

    # Pivot = highest swing high in the window (cup lip / resistance).
    pivot_i = max(swing_hs, key=lambda i: highs[i])
    pivot = float(highs[pivot_i])
    if pivot <= 0:
        return None

    # Pullbacks: after each approach near the pivot, measure depth to subsequent swing low.
    depths: list[float] = []
    trough_idxs: list[int] = []
    approaches = [i for i in swing_hs if highs[i] >= pivot * 0.97]
    if len(approaches) < cfg.vcp_min_contractions:
        approaches = swing_hs[-max(cfg.vcp_min_contractions + 1, 3):]

    for a_i in approaches:
        # Next local trough after approach
        search_end = min(end_i, a_i + 25)
        if search_end <= a_i + 2:
            continue
        trough_rel = int(np.argmin(lows[a_i: search_end + 1]))
        trough_i = a_i + trough_rel
        depth_pct = (pivot - float(lows[trough_i])) / pivot * 100.0
        if 1.0 <= depth_pct <= 45.0:
            depths.append(depth_pct)
            trough_idxs.append(trough_i)

    # Keep last N unique contracting depths
    if len(depths) < cfg.vcp_min_contractions:
        return None
    depths = depths[-4:]
    contracting = all(depths[i] > depths[i + 1] * 0.92 for i in range(len(depths) - 1))
    if not contracting:
        return None

    # Tightness: last N bars range vs price
    t0 = max(start, end_i - cfg.tightness_bars + 1)
    hi_t = float(np.max(highs[t0: end_i + 1]))
    lo_t = float(np.min(lows[t0: end_i + 1]))
    px = float(closes[end_i])
    if px <= 0:
        return None
    tight_pct = (hi_t - lo_t) / px * 100.0
    if tight_pct > cfg.tightness_max_range_pct:
        return None

    return {
        "pivot": pivot,
        "pivot_i": pivot_i,
        "depths_pct": [round(d, 2) for d in depths],
        "tightness_pct": round(tight_pct, 2),
        "contractions": len(depths),
    }


def _ipo_listing_high(work: pd.DataFrame) -> tuple[float | None, bool]:
    """Proxy listing high = early-window high when history looks 'young' (< ~2y)."""
    if len(work) < 40:
        return None, False
    young = len(work) < 520
    early = work.iloc[: min(40, max(20, len(work) // 10))]
    listing_high = float(early["high"].max())
    return listing_high, young


def _near_ath(work: pd.DataFrame, cfg: SwingFireConfig, i: int) -> tuple[bool, float | None, float | None]:
    price = float(work["close"].iloc[i])
    ath = work["ath_trail"].iloc[i]
    if pd.isna(ath) or float(ath) <= 0:
        return False, None, None
    ath_f = float(ath)
    dist = (ath_f - price) / ath_f * 100.0
    return dist <= cfg.ath_proximity_pct, ath_f, dist


def scan_swing_fire_signals(
    work: pd.DataFrame,
    cfg: SwingFireConfig,
    *,
    regime: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Bar-by-bar LONG entry signals: VCP breakout, IPO listing-high breakout, reclaim of trail EMA."""
    if work.empty or "trail" not in work.columns:
        return []

    signals: list[dict[str, Any]] = []
    closes = work["close"].to_numpy()
    opens = work["open"].to_numpy()
    lows = work["low"].to_numpy()
    highs = work["high"].to_numpy()
    trail = work["trail"].to_numpy()
    vol = work["volume"].to_numpy() if "volume" in work.columns else np.ones(len(work))
    vol_ma = work["vol_ma20"].to_numpy() if "vol_ma20" in work.columns else np.full(len(work), np.nan)

    aggressive = True if regime is None else bool(regime.get("aggressive_ok", True))
    start = max(cfg.min_bars // 2, 40)

    for i in range(start, len(work)):
        if any(pd.isna(x) for x in (closes[i], trail[i])):
            continue
        price = float(closes[i])
        tr = float(trail[i])
        if price <= 0:
            continue

        near, ath, dist = _near_ath(work, cfg, i)
        listing_high, young = _ipo_listing_high(work.iloc[: i + 1])
        vcp = _detect_vcp(work, cfg, end_i=i - 1)  # structure before today's break

        setup = None
        pivot = None
        # Fresh VCP breakout
        if vcp and near:
            pivot = float(vcp["pivot"])
            prev = float(closes[i - 1]) if i > 0 else price
            if prev <= pivot and price > pivot:
                setup = "VCP_BREAKOUT"
        # IPO / base: breakout of early listing high
        if setup is None and listing_high and young and near:
            prev = float(closes[i - 1]) if i > 0 else price
            if prev <= listing_high * 1.001 and price > listing_high:
                setup = "IPO_LISTING_BREAKOUT"
                pivot = listing_high
            # Retest: dipped to listing high then closed back above within recent window
            elif i >= 2 and float(lows[i]) <= listing_high * 1.01 and price > listing_high and float(closes[i - 1]) < listing_high * 1.02:
                setup = "IPO_RETEST"
                pivot = listing_high

        # Trail EMA reclaim after being below (re-entry rule)
        if setup is None and i >= cfg.exit_red_closes + 1:
            below_streak = all(
                float(closes[i - k]) < float(trail[i - k])
                and float(closes[i - k]) < float(opens[i - k])
                for k in range(1, cfg.exit_red_closes + 1)
                if not pd.isna(trail[i - k])
            )
            if below_streak and price > tr and float(closes[i - 1]) <= float(trail[i - 1]):
                setup = "EMA_RECLAIM"
                pivot = tr

        if not setup:
            continue
        if not aggressive and setup != "EMA_RECLAIM":
            # In distribute regime only allow reclaim management, not fresh breakouts
            continue

        # Stop: recent swing low, but never worse than the hard ~10% loss cap.
        swing_low = float(np.min(lows[max(0, i - 12): i + 1]))
        hard_floor = price * (1.0 - cfg.max_sl_pct / 100.0)
        stop = max(swing_low, hard_floor)
        if stop >= price:
            stop = price * (1.0 - min(cfg.max_sl_pct, 8.0) / 100.0)
        risk = price - stop
        if risk <= 0:
            continue
        target = price + risk * cfg.rr_ratio
        vol_ok = True
        if not pd.isna(vol_ma[i]) and float(vol_ma[i]) > 0:
            vol_ok = float(vol[i]) >= float(vol_ma[i]) * 0.9

        signals.append({
            "bar_index": i,
            "timestamp": str(work.index[i]),
            "direction": "LONG",
            "setup": setup,
            "entry": price,
            "sl_ref": stop,
            "target": target,
            "pivot": pivot,
            "ath": ath,
            "ath_dist_pct": _r(dist, 2),
            "vcp": vcp,
            "volume_ok": vol_ok,
            "trail": tr,
        })

    # Keep only signals within recent window for live freshness; full list for backtest
    return signals


def evaluate_live_signal(
    work: pd.DataFrame,
    signals: list[dict[str, Any]],
    cfg: SwingFireConfig,
    regime: dict[str, Any],
) -> dict[str, Any]:
    if work.empty or "trail" not in work.columns:
        return {"signal": "NO_DATA", "verdict": "NO DATA", "take_trade": False}

    last = work.iloc[-1]
    price = float(last["close"])
    trail = float(last["trail"]) if pd.notna(last.get("trail")) else None
    ema21 = float(last["ema21"]) if pd.notna(last.get("ema21")) else None
    ema63 = float(last["ema63"]) if pd.notna(last.get("ema63")) else None
    near, ath, dist = _near_ath(work, cfg, len(work) - 1)
    listing_high, young = _ipo_listing_high(work)
    vcp = _detect_vcp(work, cfg)

    reasons: list[str] = [
        "Swing - FIRE: long-only equity swing — ATH / VCP / IPO bases, trail EMA, ~10% loss cap. "
        "Not F&O. Concentrate; book profits in sideways markets.",
    ]
    for n in regime.get("notes") or []:
        reasons.append(str(n))

    if ath is not None and dist is not None:
        reasons.append(
            f"Strength filter: price {price:,.4g} is {dist:.1f}% below trailing high {ath:,.4g} — "
            + ("NEAR ATH (leaders preferred)." if near else "too far from highs (falling-knife risk — skip).")
        )
    if young and listing_high:
        reasons.append(f"Young / IPO-like history — listing-high proxy {listing_high:,.4g}.")
    if vcp:
        reasons.append(
            f"VCP structure: pivot {vcp['pivot']:,.4g} · contractions {vcp['depths_pct']} · "
            f"tightness {vcp['tightness_pct']:.1f}% (shallower pullbacks + tight range before break)."
        )
    else:
        reasons.append("No clean contracting VCP in the lookback window right now.")

    if trail is not None:
        reasons.append(
            f"Trail EMA{_trail_period(cfg)} = {trail:,.4g} — "
            f"{'above' if price > trail else 'below'} (exit on {_trail_period(cfg)} with "
            f"{cfg.exit_red_closes} consecutive red closes below; reclaim = re-entry)."
        )

    last_idx = len(work) - 1
    recent = [s for s in signals if s["bar_index"] >= last_idx - cfg.recent_bars]
    last_signal = recent[-1] if recent else (signals[-1] if signals else None)
    is_fresh = bool(last_signal and last_signal["bar_index"] >= last_idx - cfg.recent_bars)

    # Exit warning: N consecutive red closes below trail
    exit_warn = False
    if trail is not None and len(work) >= cfg.exit_red_closes:
        exit_warn = True
        for k in range(cfg.exit_red_closes):
            row = work.iloc[-(k + 1)]
            c, o, t = float(row["close"]), float(row["open"]), float(row["trail"]) if pd.notna(row.get("trail")) else None
            if t is None or not (c < t and c < o):
                exit_warn = False
                break
    if exit_warn:
        reasons.append(
            f"EXIT WARNING: {cfg.exit_red_closes} consecutive red closes below the trail EMA — "
            "book / flatten per FIRE trail rule."
        )

    take = False
    direction = "WAIT"
    verdict = "WAIT"
    confidence = 0.0
    entry = stop = target = price

    if is_fresh and last_signal and not exit_warn:
        take = True
        direction = "LONG"
        entry = float(last_signal["entry"])
        stop = float(last_signal["sl_ref"])
        target = float(last_signal["target"])
        setup = last_signal.get("setup", "BREAKOUT")
        confidence = 58.0
        if last_signal.get("volume_ok"):
            confidence += 8.0
        if near:
            confidence += 8.0
        if last_signal.get("vcp"):
            confidence += 10.0
        if regime.get("regime") == "ACCUMULATE":
            confidence += 8.0
        if regime.get("equity_pref") == "EQUITY":
            confidence += 4.0
        if regime.get("equity_pref") == "GOLD":
            confidence -= 6.0
        if regime.get("regime") == "DISTRIBUTE":
            confidence -= 12.0
        confidence = float(min(92.0, max(40.0, confidence)))
        take = confidence >= cfg.take_confidence_threshold
        verdict = f"BUY — {setup.replace('_', ' ').title()}"
        reasons.append(
            f"Fresh trigger **{setup}** @ {entry:,.4g}; SL {stop:,.4g} (capped ~{cfg.max_sl_pct:g}%); "
            f"T1 ~{target:,.4g} (1:{cfg.rr_ratio:g})."
        )
        reasons.append(
            "After entry: trail with the EMA; if stopped on 2 red closes below it, re-enter on reclaim — "
            "accept a small premium to avoid giving back a full trend."
        )
    elif exit_warn and trail is not None and price < trail:
        verdict = "EXIT / FLATTEN — trail EMA broken"
        direction = "FLAT"
        reasons.append("No new long while the trail-exit condition is active.")
    elif last_signal and not is_fresh:
        reasons.append(
            f"Last setup {last_signal.get('setup')} at {last_signal.get('timestamp')} — not fresh within "
            f"{cfg.recent_bars} bars."
        )
        if near and trail is not None and price > trail:
            verdict = "WATCH — leader above trail, no fresh breakout"
    elif not near:
        verdict = "SKIP — not near highs"
    elif not regime.get("aggressive_ok", True):
        verdict = "WAIT — regime says de-risk"
    else:
        reasons.append("No fresh VCP / IPO breakout / EMA reclaim in the recent window.")

    sl_pct = round(abs(entry - stop) / entry * 100, 2) if take and entry else (
        round(cfg.max_sl_pct, 2) if exit_warn else None
    )
    tp_pct = round(abs(target - entry) / entry * 100, 2) if take and entry else None

    plan = make_trade_plan(
        direction=direction if take else "—",
        timeframe=cfg.execution_tf,
        stop_loss_pct=sl_pct,
        take_profit_pct=tp_pct,
        confidence_pct=confidence,
        style="swing",
        exit_rule=(
            f"Hard loss cap ~{cfg.max_sl_pct:g}%. Trail EMA{_trail_period(cfg)}; exit on "
            f"{cfg.exit_red_closes} consecutive red closes below it; re-enter on reclaim."
        ),
        max_hold_exit="Hold while above trail EMA and structure intact; book profits faster in sideways markets.",
    )

    live = enrich_intra_live({
        "signal": direction if take else ("EXIT" if exit_warn else "NONE"),
        "direction": "LONG" if take else None,
        "take_trade": take,
        "verdict": verdict,
        "phase": regime.get("regime"),
        "confidence_pct": round(confidence, 1) if take else 0.0,
        "sl_pct": sl_pct,
        "tp_pct": tp_pct,
        "entry_price": round(entry, 6) if take else None,
        "stop_price": round(stop, 6) if take else None,
        "target_price": round(target, 6) if take else None,
        "ema21": _r(ema21),
        "ema63": _r(ema63),
        "trail_ema": _r(trail),
        "ath": _r(ath),
        "ath_dist_pct": _r(dist, 2),
        "listing_high": _r(listing_high) if young else None,
        "vcp": vcp,
        "regime": regime,
        "exit_warning": exit_warn,
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": HOLD_SWING_FIRE} if take else None,
    }, hold_duration=HOLD_SWING_FIRE)

    return live


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: SwingFireConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
    regime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = cfg or SwingFireConfig()
    if regime is None:
        regime = compute_market_regime(market, cfg, groww_token=groww_token, exchange=exchange)

    df = _fetch_daily(ticker, market, groww_token=groww_token, exchange=exchange, limit=cfg.lookback)
    if df.empty or len(df) < cfg.min_bars:
        return {
            "ticker": ticker, "market": market,
            "error": f"Insufficient daily data ({len(df)} bars, need {cfg.min_bars}+).",
        }

    work = add_swing_fire_indicators(df, cfg)
    signals = scan_swing_fire_signals(work, cfg, regime=regime)
    live = evaluate_live_signal(work, signals, cfg, regime)

    return {
        "ticker": ticker,
        "market": market,
        "execution_tf": "1d",
        "bars": len(work),
        "last_close": float(work["close"].iloc[-1]),
        "signal_history": signals[-8:],
        "regime": regime,
        "live": live,
    }


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: SwingFireConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or SwingFireConfig()
    regime = compute_market_regime(market, cfg, groww_token=groww_token, exchange=exchange)
    results = []
    for ticker in tickers:
        try:
            results.append(
                analyze_ticker(
                    ticker, market, cfg=cfg, groww_token=groww_token, exchange=exchange, regime=regime,
                )
            )
        except Exception as exc:
            logger.debug("Swing-FIRE scan failed for %s: %s", ticker, exc)
            results.append({"ticker": ticker, "market": market, "error": str(exc)[:200]})

    entries = [r for r in results if not r.get("error") and (r.get("live") or {}).get("take_trade")]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market,
        "execution_tf": "1d",
        "strategy": STRATEGY_ID,
        "regime": regime,
        "results": results,
        "entries": entries,
        "entry_count": len(entries),
        "how_it_works": (
            "Swing - FIRE (Harsh): prefer ATH leaders & IPO/VCP bases; trail 21/63 EMA; "
            "exit on 2 red closes below trail; monthly ROC cycle + equity/gold channel for aggression. "
            "Hard ~10% loss cap. Equity cash swing — not F&O."
        ),
    }
