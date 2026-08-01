"""
volume_profile_poc_engine.py
----------------------------
Volume Profile POC — institutional "first touch" pullback strategy (AKTV).

Source: https://www.youtube.com/watch?v=ooHX6tf5RVI

Rules:
  1. Build Volume Profile on a lookback window → POC + high-volume cluster zone.
  2. Wait for price to break away from the zone.
  3. Enter on the FIRST retest of the zone edge (not the exact POC center).
  4. Do not take subsequent retests.
  5. Stop in an LVN behind the HVN barrier; target just before the next HVN.

Research / education only — not financial advice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.pro_trade_shared import ConfidenceScore, atr as _atr_ind, rsi as _rsi_ind, sl_tp_pct
from app.trading_hubs.smart_money_shared import hold_for_tf

logger = logging.getLogger(__name__)

YOUTUBE_URL = "https://www.youtube.com/watch?v=ooHX6tf5RVI"
STRATEGY_NAME = "Volume Profile POC"


@dataclass
class VolumeProfilePocConfig:
    timeframe: str = "1d"
    lookback_bars: int = 120
    profile_bars: int = 60  # bars used to build the institutional VP
    num_bins: int = 40
    cluster_vol_pct: float = 0.70  # bins ≥ this fraction of POC volume form the HVN zone
    breakout_buffer_pct: float = 1.0  # % beyond zone edge to confirm breakout
    next_hvn_vol_pct: float = 0.55  # next target HVN threshold vs POC volume
    recency_bars: int = 2  # a first touch older than this many bars ago is stale, not a live entry


def calculate_volume_profile(df: pd.DataFrame, num_bins: int = 50) -> pd.DataFrame:
    if df is None or df.empty or "close" not in df.columns or "volume" not in df.columns:
        return pd.DataFrame()
    min_price = float(df["low"].min() if "low" in df.columns else df["close"].min())
    max_price = float(df["high"].max() if "high" in df.columns else df["close"].max())
    if not np.isfinite(min_price) or not np.isfinite(max_price) or max_price <= min_price:
        return pd.DataFrame()
    bins = np.linspace(min_price, max_price, max(num_bins, 5) + 1)
    work = df.copy()
    work["Price_Bin"] = pd.cut(work["close"], bins=bins, include_lowest=True)
    vp = work.groupby("Price_Bin", observed=False)["volume"].sum().reset_index()
    vp = vp.rename(columns={"volume": "Volume"})
    vp["Bin_Mid"] = vp["Price_Bin"].apply(lambda x: float(x.mid) if pd.notna(x) else np.nan)
    return vp.dropna(subset=["Bin_Mid"]).reset_index(drop=True)


def identify_key_levels(vp: pd.DataFrame, *, cluster_vol_pct: float = 0.70) -> dict[str, Any] | None:
    if vp is None or vp.empty or float(vp["Volume"].sum()) <= 0:
        return None
    poc_idx = int(vp["Volume"].idxmax())
    poc_row = vp.iloc[poc_idx]
    poc_price = float(poc_row["Bin_Mid"])
    max_vol = float(poc_row["Volume"])
    if max_vol <= 0:
        return None

    threshold = max_vol * cluster_vol_pct
    high_vol = vp[vp["Volume"] >= threshold]
    zone_upper = float(high_vol["Bin_Mid"].max())
    zone_lower = float(high_vol["Bin_Mid"].min())

    below = vp[vp["Bin_Mid"] < zone_lower]
    if not below.empty:
        stop_long = float(below.loc[below["Volume"].idxmin(), "Bin_Mid"])
    else:
        stop_long = zone_lower * 0.99

    above = vp[vp["Bin_Mid"] > zone_upper]
    if not above.empty:
        stop_short = float(above.loc[above["Volume"].idxmin(), "Bin_Mid"])
    else:
        stop_short = zone_upper * 1.01

    # Next HVN targets (outside the primary cluster)
    next_long_target = None
    next_short_target = None
    next_thresh = max_vol * 0.55
    above_nodes = vp[(vp["Bin_Mid"] > zone_upper) & (vp["Volume"] >= next_thresh)].sort_values("Bin_Mid")
    below_nodes = vp[(vp["Bin_Mid"] < zone_lower) & (vp["Volume"] >= next_thresh)].sort_values("Bin_Mid", ascending=False)
    if not above_nodes.empty:
        # Target just before next HVN
        nxt = float(above_nodes.iloc[0]["Bin_Mid"])
        next_long_target = zone_upper + (nxt - zone_upper) * 0.9
    if not below_nodes.empty:
        nxt = float(below_nodes.iloc[0]["Bin_Mid"])
        next_short_target = zone_lower - (zone_lower - nxt) * 0.9

    return {
        "poc": round(poc_price, 4),
        "zone_upper": round(zone_upper, 4),
        "zone_lower": round(zone_lower, 4),
        "stop_loss_lvn_long": round(stop_long, 4),
        "stop_loss_lvn_short": round(stop_short, 4),
        "target_long": round(next_long_target, 4) if next_long_target is not None else None,
        "target_short": round(next_short_target, 4) if next_short_target is not None else None,
        "max_volume": round(max_vol, 2),
        "cluster_bins": int(len(high_vol)),
    }


def _score_first_touch(
    *, direction: str, entry: float, stop_loss: float, target: float | None,
    bars_since_touch: int, breakout_run_pct: float, vol_ratio: float | None, rsi_val: float | None,
    tf: str,
) -> dict[str, Any]:
    score = ConfidenceScore(45, "fresh first touch of the HVN zone edge after breakout")
    score.add(bars_since_touch == 0, 15, "touch is on the latest closed bar — as live as this scan gets")
    score.add(breakout_run_pct >= 0.5, 10, f"breakout ran {breakout_run_pct:.2f}% beyond the zone before pulling back — real displacement, not a marginal poke")
    score.add(vol_ratio is not None and vol_ratio >= 1.3, 15, f"breakout bar volume {vol_ratio:.1f}x the recent average" if vol_ratio else "")
    if direction == "LONG":
        score.add(rsi_val is not None and 45 <= rsi_val <= 68, 10, f"RSI({14}) at {rsi_val:.0f} — momentum supportive, not yet overbought" if rsi_val is not None else "")
    else:
        score.add(rsi_val is not None and 32 <= rsi_val <= 55, 10, f"RSI(14) at {rsi_val:.0f} — momentum supportive, not yet oversold" if rsi_val is not None else "")
    confidence, reasons = score.finalize()
    sl_pct, tp_pct = sl_tp_pct(direction, entry, stop_loss, target)
    return {
        "confidence_pct": confidence, "sl_pct": sl_pct, "tp_pct": tp_pct,
        "hold_duration": hold_for_tf(tf, "intraday" if tf in ("1m", "3m", "5m", "15m", "30m", "1h") else "swing"),
        "reasons": reasons,
    }


def detect_first_touch(
    future_df: pd.DataFrame,
    levels: dict[str, Any],
    *,
    breakout_buffer_pct: float = 1.0,
    recency_bars: int = 2,
    context_df: pd.DataFrame | None = None,
    timeframe: str = "1d",
) -> dict[str, Any] | None:
    """
    Scan forward bars after the profile window.
    Long: breakout above zone_upper, then first touch of zone_upper from above.
    Short: breakdown below zone_lower, then first touch of zone_lower from below.

    Only the FIRST touch counts, and — critically — it's only reported as a
    live BUY/SELL if that first touch happened within `recency_bars` of the
    latest bar. A first touch that happened many bars ago already played out
    (price has since moved on); surfacing it as "actionable" now would be
    handing out a stale, already-expired entry. Older touches are reported
    as WAIT with an explanatory note instead.
    """
    if future_df is None or future_df.empty:
        return None

    zone_upper = float(levels["zone_upper"])
    zone_lower = float(levels["zone_lower"])
    buf_up = zone_upper * (1.0 + breakout_buffer_pct / 100.0)
    buf_dn = zone_lower * (1.0 - breakout_buffer_pct / 100.0)

    long_broken = False
    short_broken = False
    long_touch_pos: int | None = None
    short_touch_pos: int | None = None
    long_run_pct = 0.0
    short_run_pct = 0.0

    for pos in range(len(future_df)):
        row = future_df.iloc[pos]
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])

        if close > buf_up:
            long_broken = True
            long_run_pct = max(long_run_pct, (close - zone_upper) / zone_upper * 100.0)
        if close < buf_dn:
            short_broken = True
            short_run_pct = max(short_run_pct, (zone_lower - close) / zone_lower * 100.0)

        if long_broken and long_touch_pos is None and low <= zone_upper:
            long_touch_pos = pos
        if short_broken and short_touch_pos is None and high >= zone_lower:
            short_touch_pos = pos

    last_pos = len(future_df) - 1
    last = future_df.iloc[-1]
    close = float(last["close"])

    vol_ratio = None
    rsi_val = None
    if context_df is not None and len(context_df) >= 10:
        if "volume" in context_df.columns:
            recent_vol = context_df["volume"].iloc[-20:]
            avg_vol = float(recent_vol.mean()) if len(recent_vol) else 0.0
            last_vol = float(context_df["volume"].iloc[-1] or 0)
            if avg_vol > 0:
                vol_ratio = last_vol / avg_vol
        rsi_series = _rsi_ind(context_df["close"], 14).dropna()
        if not rsi_series.empty:
            rsi_val = float(rsi_series.iloc[-1])

    if long_touch_pos is not None:
        bars_since = last_pos - long_touch_pos
        entry, stop_loss, target = round(zone_upper, 4), levels["stop_loss_lvn_long"], levels.get("target_long")
        base = {
            "setup": "poc_first_touch", "direction": "LONG",
            "entry_time": str(future_df.index[long_touch_pos]),
            "stop_loss": stop_loss, "target_1": target,
            "levels": levels, "bars_since_touch": bars_since,
        }
        if bars_since <= recency_bars:
            extra = _score_first_touch(
                direction="LONG", entry=entry, stop_loss=stop_loss, target=target,
                bars_since_touch=bars_since, breakout_run_pct=long_run_pct,
                vol_ratio=vol_ratio, rsi_val=rsi_val, tf=timeframe,
            )
            return {
                **base, **extra, "signal": "BUY", "entry": entry,
                "logic": (
                    f"Breakout above HVN zone, FIRST pullback to zone upper edge "
                    f"{bars_since} bar(s) ago — still live. SL in LVN below zone."
                ),
            }
        return {
            **base, "signal": "WAIT", "entry": None,
            "logic": (
                f"First touch of the zone edge already happened {bars_since} bars ago — stale, "
                "the live entry window has passed. Waiting for the next fresh setup."
            ),
            "last_close": round(close, 4),
        }

    if short_touch_pos is not None:
        bars_since = last_pos - short_touch_pos
        entry, stop_loss, target = round(zone_lower, 4), levels["stop_loss_lvn_short"], levels.get("target_short")
        base = {
            "setup": "poc_first_touch", "direction": "SHORT",
            "entry_time": str(future_df.index[short_touch_pos]),
            "stop_loss": stop_loss, "target_1": target,
            "levels": levels, "bars_since_touch": bars_since,
        }
        if bars_since <= recency_bars:
            extra = _score_first_touch(
                direction="SHORT", entry=entry, stop_loss=stop_loss, target=target,
                bars_since_touch=bars_since, breakout_run_pct=short_run_pct,
                vol_ratio=vol_ratio, rsi_val=rsi_val, tf=timeframe,
            )
            return {
                **base, **extra, "signal": "SELL", "entry": entry,
                "logic": (
                    f"Breakdown below HVN zone, FIRST retest of zone lower edge "
                    f"{bars_since} bar(s) ago — still live. SL in LVN above zone."
                ),
            }
        return {
            **base, "signal": "WAIT", "entry": None,
            "logic": (
                f"First touch of the zone edge already happened {bars_since} bars ago — stale, "
                "the live entry window has passed. Waiting for the next fresh setup."
            ),
            "last_close": round(close, 4),
        }

    # No completed first touch yet — report watch state
    if long_broken:
        return {
            "setup": "poc_first_touch",
            "signal": "WATCH",
            "direction": "LONG",
            "entry": None,
            "stop_loss": levels["stop_loss_lvn_long"],
            "target_1": levels.get("target_long"),
            "logic": "Broke out above HVN zone — waiting for FIRST pullback to zone upper edge",
            "levels": levels,
            "last_close": round(close, 4),
        }
    if short_broken:
        return {
            "setup": "poc_first_touch",
            "signal": "WATCH",
            "direction": "SHORT",
            "entry": None,
            "stop_loss": levels["stop_loss_lvn_short"],
            "target_1": levels.get("target_short"),
            "logic": "Broke down below HVN zone — waiting for FIRST retest of zone lower edge",
            "levels": levels,
            "last_close": round(close, 4),
        }
    return {
        "setup": "poc_first_touch",
        "signal": "WAIT",
        "direction": None,
        "entry": None,
        "logic": "Price still building / ranging in HVN — wait for breakout away from the zone first",
        "levels": levels,
        "last_close": round(close, 4),
    }


def _build_chart_data(df: pd.DataFrame, *, max_bars: int = 160) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    tail = df.iloc[-max_bars:]
    rows: list[dict[str, Any]] = []
    for idx, bar in tail.iterrows():
        rows.append({
            "time": str(idx),
            "open": round(float(bar["open"]), 6),
            "high": round(float(bar["high"]), 6),
            "low": round(float(bar["low"]), 6),
            "close": round(float(bar["close"]), 6),
            "volume": round(float(bar["volume"]), 2) if "volume" in bar and pd.notna(bar["volume"]) else None,
        })
    return rows


def _vp_histogram(vp: pd.DataFrame) -> list[dict[str, Any]]:
    if vp is None or vp.empty:
        return []
    out: list[dict[str, Any]] = []
    for _, row in vp.iterrows():
        mid = row.get("Bin_Mid")
        if mid is None or pd.isna(mid):
            continue
        out.append({"price": round(float(mid), 4), "volume": round(float(row.get("Volume") or 0), 2)})
    return out


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: VolumeProfilePocConfig,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "ticker": ticker,
        "strategy": STRATEGY_NAME,
        "youtube": YOUTUBE_URL,
        "error": None,
        "levels": None,
        "setups": [],
        "actionable": [],
        "chart_data": [],
        "vp_histogram": [],
        "rules": [
            "Enter only on the FIRST touch of the HVN zone edge after breakout — skip later retests.",
            "Treat the high-volume cluster as a thick zone; prefer the outer edge over the exact POC line.",
            "Place stop loss in an LVN behind the heavy volume barrier.",
            "Take profit before the next heavy volume zone.",
        ],
    }

    try:
        df = fetch_data_for_gap_scan(
            ticker,
            cfg.timeframe,
            market,
            groww_token=groww_token,
            exchange=exchange,
            limit=cfg.lookback_bars,
        )
    except Exception as exc:
        out["error"] = f"Data fetch failed: {exc}"
        return out

    if df is None or df.empty or len(df) < max(30, cfg.profile_bars // 2):
        out["error"] = "Insufficient OHLCV for Volume Profile POC"
        return out

    profile_n = min(cfg.profile_bars, max(20, len(df) - 10))
    historical = df.iloc[:profile_n].copy()
    future = df.iloc[profile_n:].copy()
    if future.empty:
        # Use last third as "future" if profile ate everything
        split = max(20, int(len(df) * 0.65))
        historical = df.iloc[:split].copy()
        future = df.iloc[split:].copy()

    vp = calculate_volume_profile(historical, num_bins=cfg.num_bins)
    levels = identify_key_levels(vp, cluster_vol_pct=cfg.cluster_vol_pct)
    if not levels:
        out["error"] = "Could not identify POC / HVN levels"
        return out

    out["levels"] = levels
    out["ltp"] = round(float(df["close"].iloc[-1]), 4)
    out["profile"] = {
        "tf": cfg.timeframe,
        "profile_bars": int(len(historical)),
        "forward_bars": int(len(future)),
        "num_bins": cfg.num_bins,
        "cluster_vol_pct": cfg.cluster_vol_pct,
    }
    out["chart_data"] = _build_chart_data(df, max_bars=160)
    out["vp_histogram"] = _vp_histogram(vp)

    signal = detect_first_touch(
        future,
        levels,
        breakout_buffer_pct=cfg.breakout_buffer_pct,
        recency_bars=cfg.recency_bars,
        context_df=df,
        timeframe=cfg.timeframe,
    )
    if signal is None:
        signal = {
            "setup": "poc_first_touch",
            "signal": "WAIT",
            "direction": None,
            "logic": "No forward bars to evaluate first touch",
            "levels": levels,
        }

    out["setups"] = [signal]
    actionable = [
        s for s in out["setups"]
        if s.get("signal") not in (None, "WAIT", "WATCH") and s.get("direction") and s.get("entry") is not None
    ]
    out["actionable"] = actionable
    out["direction"] = actionable[0].get("direction") if actionable else None
    out["verdict"] = "TAKE" if actionable else ("WATCH" if signal.get("signal") == "WATCH" else "WAIT")
    out["take_trade"] = bool(actionable)
    return out


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: VolumeProfilePocConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or VolumeProfilePocConfig()
    results = []
    for t in tickers:
        try:
            results.append(
                analyze_ticker(t, market, cfg=cfg, groww_token=groww_token, exchange=exchange)
            )
        except Exception as exc:
            logger.exception("Volume Profile POC failed for %s", t)
            results.append({
                "ticker": t,
                "error": str(exc),
                "setups": [],
                "actionable": [],
                "take_trade": False,
                "chart_data": [],
                "vp_histogram": [],
            })

    entry_count = sum(1 for r in results if r.get("take_trade"))
    return {
        "strategy": STRATEGY_NAME,
        "youtube": YOUTUBE_URL,
        "results": results,
        "entry_count": entry_count,
        "scanned": len(results),
        "config": {
            "timeframe": cfg.timeframe,
            "lookback_bars": cfg.lookback_bars,
            "profile_bars": cfg.profile_bars,
            "num_bins": cfg.num_bins,
            "cluster_vol_pct": cfg.cluster_vol_pct,
            "breakout_buffer_pct": cfg.breakout_buffer_pct,
        },
        "disclaimer": "Research / education only — not financial advice.",
    }
