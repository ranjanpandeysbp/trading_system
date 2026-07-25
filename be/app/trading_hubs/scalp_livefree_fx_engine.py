"""
scalp_livefree_fx_engine.py
---------------------------
5-Minute Scalping (LiveFree FX) — HTF bias + session kill zones + London
liquidity sweep + 5m Break of Structure entry.

Video: https://www.youtube.com/watch?v=a74KPzR7phE

Pipeline:
1) HTF bias from 1D / 4H / 1H market structure (HH/HL vs LH/LL) + SMA confirm
2) Session analysis on 15m (Asia / London / NY kill zones)
3) NY session: wait for liquidity sweep of London high/low against HTF bias
4) 5m: Break of Structure back with HTF → entry; SL beyond sweep extreme
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import time
from typing import Any, Literal

import numpy as np
import pandas as pd

from app.market_pulse.fakeout_4h_engine import session_mode_for_market
from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.intraday_shared import enrich_intra_live
from app.trading_hubs.session_constants import IST_TZ, NY_TZ

logger = logging.getLogger(__name__)

YOUTUBE_LIVEFREE_FX_URL = "https://www.youtube.com/watch?v=a74KPzR7phE"

SessionProfile = Literal["fx_est", "india_ist"]

PHASE_NONE = "NO_SETUP"
PHASE_HTF_BIAS = "HTF_BIAS_SET"
PHASE_WAIT_NY = "WAIT_NY_SESSION"
PHASE_WAIT_SWEEP = "WAIT_LIQUIDITY_SWEEP"
PHASE_SWEEP = "LIQUIDITY_SWEEP"
PHASE_WAIT_BOS = "WAIT_5M_BOS"
PHASE_ENTRY = "BOS_ENTRY"

HOLD_LIVEFREE = (
    "LiveFree FX 5m scalp · SL beyond sweep · TP1 @1:1 (50%, SL→BE) · "
    "TP2 next liquidity · first-win walk-away"
)

# EST kill zones (LiveFree FX / ICT-style)
FX_SESSIONS = {
    "asia": (time(19, 0), time(22, 0)),
    "london": (time(2, 0), time(5, 0)),
    "ny": (time(7, 0), time(11, 0)),
}

# India cash-session analogue (IST) — opening range → mid → afternoon expansion
INDIA_SESSIONS = {
    "asia": (time(9, 15), time(10, 30)),
    "london": (time(10, 30), time(12, 30)),
    "ny": (time(13, 0), time(15, 15)),
}


@dataclass
class LiveFreeConfig:
    exec_tf: str = "5m"
    structure_tf: str = "15m"
    htf_list: tuple[str, ...] = ("1d", "4h", "1h")
    swing_window: int = 3
    htf_sma: int = 50
    ltf_sma: int = 5
    sweep_lookback_bars: int = 6  # ~30m on 5m
    bos_swing_lookback: int = 8
    rr_ratio: float = 2.0
    take_confidence_threshold: float = 58.0
    lookback_5m: int = 900
    min_bars_5m: int = 120
    session_profile: SessionProfile | str | None = None  # auto from market if None / "auto"


def _session_profile_for_market(market: str, override: SessionProfile | str | None) -> SessionProfile:
    if override in ("fx_est", "india_ist"):
        return override  # type: ignore[return-value]
    mode = session_mode_for_market(market)
    return "india_ist" if mode == "india" else "fx_est"


def _tz_for_profile(profile: SessionProfile):
    return IST_TZ if profile == "india_ist" else NY_TZ


def _sessions_for_profile(profile: SessionProfile) -> dict[str, tuple[time, time]]:
    return INDIA_SESSIONS if profile == "india_ist" else FX_SESSIONS


def _ensure_tz(df: pd.DataFrame, tz) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index)
    if out.index.tz is None:
        out.index = out.index.tz_localize(tz)
    else:
        out.index = out.index.tz_convert(tz)
    return out.sort_index()


def _in_window(ts: pd.Timestamp, start: time, end: time) -> bool:
    t = ts.time()
    if start <= end:
        return start <= t < end
    # wraps midnight (Asia EST 19–22 does not wrap; London/Asia don't wrap either)
    return t >= start or t < end


def _resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    if df.empty:
        return df
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in df.columns:
        agg["volume"] = "sum"
    out = df.resample(rule).agg(agg).dropna(subset=["open", "high", "low", "close"])
    return out


def _tf_rule(tf: str) -> str:
    return {"1m": "1min", "5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h", "1d": "1D"}.get(tf, tf)


def _swing_flags(df: pd.DataFrame, window: int = 3) -> pd.DataFrame:
    out = df.copy()
    half = max(1, window)
    highs = out["high"].values
    lows = out["low"].values
    n = len(out)
    sh = np.zeros(n, dtype=bool)
    sl = np.zeros(n, dtype=bool)
    for i in range(half, n - half):
        if highs[i] == highs[i - half : i + half + 1].max():
            sh[i] = True
        if lows[i] == lows[i - half : i + half + 1].min():
            sl[i] = True
    out["is_swing_high"] = sh
    out["is_swing_low"] = sl
    return out


def _structure_bias(df: pd.DataFrame, *, sma_period: int, swing_window: int) -> dict[str, Any]:
    """HH/HL = bullish, LH/LL = bearish; SMA as tie-break."""
    if df is None or len(df) < max(sma_period, swing_window * 4, 20):
        return {"bias": "NEUTRAL", "score": 0, "label": "Insufficient bars"}

    work = _swing_flags(df, swing_window)
    work["sma"] = work["close"].rolling(sma_period, min_periods=max(5, sma_period // 3)).mean()
    sh_idx = work.index[work["is_swing_high"]]
    sl_idx = work.index[work["is_swing_low"]]
    score = 0
    notes = []

    if len(sh_idx) >= 2:
        h1, h2 = float(work.loc[sh_idx[-2], "high"]), float(work.loc[sh_idx[-1], "high"])
        if h2 > h1:
            score += 1
            notes.append("HH")
        elif h2 < h1:
            score -= 1
            notes.append("LH")
    if len(sl_idx) >= 2:
        l1, l2 = float(work.loc[sl_idx[-2], "low"]), float(work.loc[sl_idx[-1], "low"])
        if l2 > l1:
            score += 1
            notes.append("HL")
        elif l2 < l1:
            score -= 1
            notes.append("LL")

    last = work.iloc[-1]
    sma = last.get("sma")
    if pd.notna(sma):
        if float(last["close"]) > float(sma):
            score += 1
            notes.append("Above SMA")
        else:
            score -= 1
            notes.append("Below SMA")

    if score >= 2:
        bias = "BULLISH"
    elif score <= -2:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"
    return {"bias": bias, "score": score, "label": ", ".join(notes) or "—"}


def compute_htf_bias(
    df_5m: pd.DataFrame,
    cfg: LiveFreeConfig,
    *,
    dfs: dict[str, pd.DataFrame] | None = None,
) -> dict[str, Any]:
    """Majority vote across 1D / 4H / 1H structure."""
    votes: dict[str, dict[str, Any]] = {}
    for tf in cfg.htf_list:
        if dfs and tf in dfs and dfs[tf] is not None and not dfs[tf].empty:
            frame = dfs[tf]
        else:
            frame = _resample(df_5m, _tf_rule(tf))
        votes[tf] = _structure_bias(frame, sma_period=cfg.htf_sma if tf != "1d" else 20, swing_window=cfg.swing_window)

    bull = sum(1 for v in votes.values() if v["bias"] == "BULLISH")
    bear = sum(1 for v in votes.values() if v["bias"] == "BEARISH")
    if bull >= 2 and bull > bear:
        overall = "BULLISH"
    elif bear >= 2 and bear > bull:
        overall = "BEARISH"
    else:
        overall = "NEUTRAL"
    return {"overall": overall, "votes": votes, "bull_votes": bull, "bear_votes": bear}


def _session_ranges(
    df_15m: pd.DataFrame,
    profile: SessionProfile,
) -> pd.DataFrame:
    """Attach Asia/London/NY flags and London session high/low per calendar day."""
    out = df_15m.copy()
    sessions = _sessions_for_profile(profile)
    out["is_asia"] = [_in_window(ts, *sessions["asia"]) for ts in out.index]
    out["is_london"] = [_in_window(ts, *sessions["london"]) for ts in out.index]
    out["is_ny"] = [_in_window(ts, *sessions["ny"]) for ts in out.index]
    out["sess_date"] = [ts.date() for ts in out.index]

    # London high/low for each session date; for FX London after midnight, use "London date"
    # For EST London 02–05, date is the calendar day of those bars.
    london = out[out["is_london"]]
    if london.empty:
        out["london_high"] = np.nan
        out["london_low"] = np.nan
        out["asia_range"] = np.nan
        out["london_range"] = np.nan
        return out

    lh = london.groupby("sess_date")["high"].max()
    ll = london.groupby("sess_date")["low"].min()
    out["london_high"] = out["sess_date"].map(lh)
    out["london_low"] = out["sess_date"].map(ll)

    asia = out[out["is_asia"]]
    if not asia.empty:
        ar = (asia.groupby("sess_date")["high"].max() - asia.groupby("sess_date")["low"].min())
        out["asia_range"] = out["sess_date"].map(ar)
    else:
        out["asia_range"] = np.nan
    out["london_range"] = out["london_high"] - out["london_low"]
    return out


def _session_context(df_15m: pd.DataFrame) -> dict[str, Any]:
    """Describe Asia vs London volatility for NY continuation logic."""
    if df_15m.empty:
        return {"note": "No 15m session data."}
    last_date = df_15m["sess_date"].iloc[-1]
    day = df_15m[df_15m["sess_date"] == last_date]
    asia_r = float(day["asia_range"].dropna().iloc[-1]) if day["asia_range"].notna().any() else None
    lon_r = float(day["london_range"].dropna().iloc[-1]) if day["london_range"].notna().any() else None
    note = "Session ranges unavailable."
    ny_favored = False
    if asia_r is not None and lon_r is not None:
        if asia_r > lon_r * 1.35 and lon_r > 0:
            note = (
                f"Asia range ({asia_r:.4g}) >> London range ({lon_r:.4g}) — "
                "London was relatively quiet; NY continuation/expansion favored."
            )
            ny_favored = True
        elif lon_r > asia_r * 1.35:
            note = (
                f"London already expanded ({lon_r:.4g}) vs Asia ({asia_r:.4g}) — "
                "NY may be choppier; require a clean sweep."
            )
        else:
            note = f"Asia range {asia_r:.4g} · London range {lon_r:.4g} — balanced; wait for clear sweep."
    return {
        "asia_range": asia_r,
        "london_range": lon_r,
        "ny_favored": ny_favored,
        "note": note,
        "session_date": str(last_date),
    }


def _detect_sweeps_on_5m(
    df_5m: pd.DataFrame,
    london_high: float | None,
    london_low: float | None,
    profile: SessionProfile,
) -> pd.DataFrame:
    out = df_5m.copy()
    sessions = _sessions_for_profile(profile)
    out["is_ny"] = [_in_window(ts, *sessions["ny"]) for ts in out.index]
    out["sweep_high"] = False
    out["sweep_low"] = False
    if london_high is None or london_low is None or np.isnan(london_high) or np.isnan(london_low):
        return out
    # Sweep = pierce London extreme during NY, close back inside
    out["sweep_high"] = (
        out["is_ny"]
        & (out["high"] > london_high)
        & (out["close"] < london_high)
    )
    out["sweep_low"] = (
        out["is_ny"]
        & (out["low"] < london_low)
        & (out["close"] > london_low)
    )
    return out


def _recent_swing_level(df: pd.DataFrame, *, side: str, lookback: int) -> float | None:
    """Most recent confirmed swing high/low before the last bar."""
    work = _swing_flags(df.iloc[:-1], window=2)
    tail = work.iloc[-lookback:] if len(work) >= lookback else work
    if side == "high":
        hits = tail[tail["is_swing_high"]]
        if hits.empty:
            return float(tail["high"].max()) if not tail.empty else None
        return float(hits["high"].iloc[-1])
    hits = tail[tail["is_swing_low"]]
    if hits.empty:
        return float(tail["low"].min()) if not tail.empty else None
    return float(hits["low"].iloc[-1])


def _bos_confirmed(df_5m: pd.DataFrame, direction: str, lookback: int) -> dict[str, Any] | None:
    """Break of Structure: close beyond recent opposing swing after the sweep."""
    if len(df_5m) < lookback + 3:
        return None
    last = df_5m.iloc[-1]
    if direction == "SHORT":
        level = _recent_swing_level(df_5m, side="low", lookback=lookback)
        if level is None:
            return None
        if float(last["close"]) < level:
            return {"direction": "SHORT", "level": level, "close": float(last["close"])}
    else:
        level = _recent_swing_level(df_5m, side="high", lookback=lookback)
        if level is None:
            return None
        if float(last["close"]) > level:
            return {"direction": "LONG", "level": level, "close": float(last["close"])}
    return None


def _next_structure_tp(df_5m: pd.DataFrame, direction: str, entry: float, risk: float, rr: float) -> float:
    work = _swing_flags(df_5m, window=2)
    if direction == "LONG":
        levels = sorted(v for v in work.loc[work["is_swing_high"], "high"].values if v > entry)
        return float(levels[0]) if levels else entry + risk * rr
    levels = sorted((v for v in work.loc[work["is_swing_low"], "low"].values if v < entry), reverse=True)
    return float(levels[0]) if levels else entry - risk * rr


def evaluate_live_signal(
    df_5m: pd.DataFrame,
    df_15m: pd.DataFrame,
    htf_bias: dict[str, Any],
    cfg: LiveFreeConfig,
    profile: SessionProfile,
) -> dict[str, Any]:
    sess_ctx = _session_context(df_15m)
    bias = htf_bias.get("overall", "NEUTRAL")
    reasons = [
        f"HTF bias **{bias}** "
        f"(1D/4H/1H votes bull={htf_bias.get('bull_votes', 0)} bear={htf_bias.get('bear_votes', 0)})"
    ]
    for tf, v in (htf_bias.get("votes") or {}).items():
        reasons.append(f"· **{tf}**: {v.get('bias')} ({v.get('label')})")
    reasons.append(sess_ctx.get("note") or "")

    conf = 18.0
    phase = PHASE_HTF_BIAS if bias in ("BULLISH", "BEARISH") else PHASE_NONE
    direction = "WAIT"
    verdict = "WAIT"
    take = False
    price = float(df_5m["close"].iloc[-1])
    stop = price
    target1 = price
    target2 = price
    sweep_info = None
    bos_info = None
    london_high = london_low = None

    if bias == "NEUTRAL":
        reasons.append("No clear HTF control — only trade with the Daily/4H/1H trend.")
        conf = 20.0
    else:
        conf += 14

    last_15 = df_15m.iloc[-1] if not df_15m.empty else None
    if last_15 is not None and pd.notna(last_15.get("london_high")):
        london_high = float(last_15["london_high"])
        london_low = float(last_15["london_low"])
        reasons.append(f"London liquidity: high **{london_high:,.4g}** · low **{london_low:,.4g}**")

    sessions = _sessions_for_profile(profile)
    now_ts = df_5m.index[-1]
    in_ny = _in_window(now_ts, *sessions["ny"])
    if not in_ny:
        phase = PHASE_WAIT_NY if bias in ("BULLISH", "BEARISH") else phase
        reasons.append(
            f"Outside execution kill zone "
            f"({'IST' if profile == 'india_ist' else 'EST'} "
            f"{sessions['ny'][0].strftime('%H:%M')}–{sessions['ny'][1].strftime('%H:%M')})"
        )
    else:
        conf += 8
        reasons.append("Inside NY / afternoon execution kill zone")

    df_sw = _detect_sweeps_on_5m(df_5m, london_high, london_low, profile)
    look = df_sw.iloc[-cfg.sweep_lookback_bars :]
    swept_high = bool(look["sweep_high"].any())
    swept_low = bool(look["sweep_low"].any())

    if bias == "BEARISH" and swept_high:
        direction = "SHORT"
        phase = PHASE_SWEEP
        conf += 22
        # last sweep bar extreme
        sweep_bars = look[look["sweep_high"]]
        sweep_px = float(sweep_bars["high"].max())
        sweep_info = {
            "type": "London High sweep",
            "level": london_high,
            "extreme": sweep_px,
            "direction": "SHORT",
        }
        reasons.append(
            f"Liquidity sweep of London high **{london_high:,.4g}** "
            f"(wick to {sweep_px:,.4g}, closed back below) — early buyers trapped"
        )
    elif bias == "BULLISH" and swept_low:
        direction = "LONG"
        phase = PHASE_SWEEP
        conf += 22
        sweep_bars = look[look["sweep_low"]]
        sweep_px = float(sweep_bars["low"].min())
        sweep_info = {
            "type": "London Low sweep",
            "level": london_low,
            "extreme": sweep_px,
            "direction": "LONG",
        }
        reasons.append(
            f"Liquidity sweep of London low **{london_low:,.4g}** "
            f"(wick to {sweep_px:,.4g}, closed back above) — early sellers trapped"
        )
    elif in_ny and bias in ("BULLISH", "BEARISH"):
        phase = PHASE_WAIT_SWEEP
        need = "London high" if bias == "BEARISH" else "London low"
        reasons.append(f"Waiting for NY liquidity sweep of **{need}** against trapped counter-trend traders")

    if sess_ctx.get("ny_favored") and phase in (PHASE_SWEEP, PHASE_WAIT_BOS, PHASE_ENTRY):
        conf += 6

    # 5m momentum + BOS
    if direction in ("LONG", "SHORT") and sweep_info:
        work = df_5m.copy()
        work["ltf_sma"] = work["close"].rolling(cfg.ltf_sma, min_periods=2).mean()
        last = work.iloc[-1]
        mom_ok = (
            (direction == "SHORT" and float(last["close"]) < float(last["ltf_sma"]))
            or (direction == "LONG" and float(last["close"]) > float(last["ltf_sma"]))
        )
        bos = _bos_confirmed(work, direction, cfg.bos_swing_lookback)
        if bos and mom_ok:
            bos_info = bos
            phase = PHASE_ENTRY
            conf += 24
            reasons.append(
                f"5m **Break of Structure** {direction} through swing "
                f"**{bos['level']:,.4g}** + momentum vs SMA-{cfg.ltf_sma}"
            )
            entry = price
            extreme = float(sweep_info["extreme"])
            buffer = max(abs(extreme - entry) * 0.05, price * 0.0004)
            if direction == "SHORT":
                stop = extreme + buffer
                risk = max(stop - entry, price * 0.0008)
                target1 = entry - risk
                target2 = _next_structure_tp(work, "SHORT", entry, risk, cfg.rr_ratio)
            else:
                stop = extreme - buffer
                risk = max(entry - stop, price * 0.0008)
                target1 = entry + risk
                target2 = _next_structure_tp(work, "LONG", entry, risk, cfg.rr_ratio)
            reasons.append(
                f"SL just beyond sweep extreme · TP1 @1:1 (50%, SL→BE) · TP2 next liquidity pool"
            )
            verdict = f"TAKE {direction}"
        elif mom_ok or bos:
            phase = PHASE_WAIT_BOS
            verdict = f"WATCH {direction}"
            conf += 8
            if not bos:
                reasons.append("Sweep seen — waiting for 5m structure shift (BoS) back with HTF")
            if not mom_ok:
                reasons.append(f"Waiting for 5m close on the correct side of SMA-{cfg.ltf_sma}")
        else:
            phase = PHASE_WAIT_BOS
            verdict = f"WATCH {direction}"
            reasons.append("Sweep armed — waiting for 5m sellers/buyers to reclaim structure")

    conf = max(15.0, min(92.0, conf))
    take = phase == PHASE_ENTRY and conf >= cfg.take_confidence_threshold and direction in ("LONG", "SHORT")
    if take:
        verdict = f"TAKE {direction}"
    elif direction in ("LONG", "SHORT") and not verdict.startswith("TAKE"):
        verdict = f"WATCH {direction}"

    if direction == "LONG" and stop < price:
        sl_pct = max(0.12, (price - stop) / price * 100)
        tp_pct = max(0.15, (target1 - price) / price * 100) if target1 > price else sl_pct
    elif direction == "SHORT" and stop > price:
        sl_pct = max(0.12, (stop - price) / price * 100)
        tp_pct = max(0.15, (price - target1) / price * 100) if target1 < price else sl_pct
    else:
        sl_pct, tp_pct = 0.35, 0.35

    plan = make_trade_plan(
        direction=direction if take else "—",
        timeframe=cfg.exec_tf,
        stop_loss_pct=round(sl_pct, 2),
        take_profit_pct=round(tp_pct, 2),
        confidence_pct=round(conf, 1),
        style="scalp",
        exit_rule="TP1 @1:1 — close 50%, move SL to BE. TP2 @ next structural liquidity. Walk away after first win.",
        max_hold_exit="Kill-zone scalp — flat by end of NY/afternoon window.",
    )

    return enrich_intra_live({
        "signal": direction if take else "NONE",
        "direction": direction,
        "take_trade": take,
        "verdict": verdict,
        "phase": phase,
        "confidence_pct": round(conf, 1),
        "sl_pct": round(sl_pct, 2),
        "tp_pct": round(tp_pct, 2),
        "hold_duration": HOLD_LIVEFREE,
        "rr_ratio": cfg.rr_ratio,
        "entry_price": round(price, 6),
        "stop_price": round(stop, 6),
        "target_price": round(target1, 6),
        "target1_price": round(target1, 6),
        "target2_price": round(target2, 6),
        "htf_bias": bias,
        "htf_detail": htf_bias,
        "session_context": sess_ctx,
        "london_high": london_high,
        "london_low": london_low,
        "sweep": sweep_info,
        "bos": bos_info,
        "session_profile": profile,
        "reasons": [r for r in reasons if r],
        "trade_plan": {**plan, "holding_period": HOLD_LIVEFREE},
    }, hold_duration=HOLD_LIVEFREE)


def fetch_exec_data(
    ticker: str,
    market: str,
    cfg: LiveFreeConfig,
    *,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, pd.DataFrame]:
    is_crypto = "CoinDCX" in market
    profile = _session_profile_for_market(market, cfg.session_profile)
    tz = _tz_for_profile(profile)

    df_5m = normalize_ohlcv(
        fetch_data_for_gap_scan(ticker, "5m", market, groww_token, exchange, limit=cfg.lookback_5m),
    )
    if df_5m.empty or len(df_5m) < cfg.min_bars_5m:
        df_5m = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, "5m", is_crypto=is_crypto, limit=cfg.lookback_5m, market=market),
        )
    df_5m = _ensure_tz(df_5m, tz)

    # Prefer native HTF pulls; fall back to resample
    frames: dict[str, pd.DataFrame] = {"5m": df_5m}
    for tf in ("15m", "1h", "4h", "1d"):
        raw = normalize_ohlcv(
            fetch_data_for_gap_scan(
                ticker, tf, market, groww_token, exchange,
                limit=200 if tf != "1d" else 120,
            ),
        )
        if raw.empty:
            raw = normalize_ohlcv(
                fetch_ohlcv_yfinance(ticker, tf, is_crypto=is_crypto, limit=200 if tf != "1d" else 120, market=market),
            )
        if raw.empty and not df_5m.empty:
            raw = _resample(df_5m, _tf_rule(tf))
        frames[tf] = _ensure_tz(raw, tz) if not raw.empty else pd.DataFrame()

    return frames


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: LiveFreeConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or LiveFreeConfig()
    profile = _session_profile_for_market(market, cfg.session_profile)
    frames = fetch_exec_data(ticker, market, cfg, groww_token=groww_token, exchange=exchange)
    df_5m = frames.get("5m", pd.DataFrame())
    if df_5m.empty or len(df_5m) < cfg.min_bars_5m:
        return {"ticker": ticker, "error": "Insufficient 5m data."}

    df_15m = frames.get("15m")
    if df_15m is None or df_15m.empty:
        df_15m = _resample(df_5m, "15min")
    df_15m = _session_ranges(df_15m, profile)

    htf_bias = compute_htf_bias(
        df_5m, cfg,
        dfs={tf: frames.get(tf, pd.DataFrame()) for tf in cfg.htf_list},
    )
    live = evaluate_live_signal(df_5m, df_15m, htf_bias, cfg, profile)

    return {
        "ticker": ticker,
        "market": market,
        "session_profile": profile,
        "bars_5m": len(df_5m),
        "last_close": float(df_5m["close"].iloc[-1]),
        "htf_bias": htf_bias,
        "live": live,
    }


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: LiveFreeConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or LiveFreeConfig()
    results = []
    for ticker in tickers:
        try:
            results.append(analyze_ticker(ticker, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            logger.exception("LiveFree FX scan failed for %s", ticker)
            results.append({"ticker": ticker, "error": str(exc)[:200]})

    entries = [r for r in results if not r.get("error") and (r.get("live") or {}).get("take_trade")]
    watches = [
        r for r in results
        if not r.get("error")
        and not (r.get("live") or {}).get("take_trade")
        and str((r.get("live") or {}).get("verdict", "")).startswith("WATCH")
    ]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))
    watches.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market,
        "session_profile": _session_profile_for_market(market, cfg.session_profile),
        "results": results,
        "entries": entries,
        "watchlist": watches,
        "entry_count": len(entries),
        "watch_count": len(watches),
    }
