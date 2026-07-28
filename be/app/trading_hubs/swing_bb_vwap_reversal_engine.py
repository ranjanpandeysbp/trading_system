"""
swing_bb_vwap_reversal_engine.py
----------------------------------
"Simple BB + VWAP Setup For Consistent 1:3 Trades" — multi-timeframe
Bollinger Band + VWAP reversal strategy.

Source: https://www.youtube.com/watch?v=5s_6CLbEa2g

Indicators (as taught, with modified settings):
  - Bollinger Bands: length 20, multiplier **1** (not the standard 2) — the
    median/basis line is hidden on the chart but still needed for the math.
  - VWAP: source changed to **Close** (not the usual typical price/HLC3).

Timeframes:
  - Higher timeframe (1h or 4h): establishes the overall trend bias.
    Operationalized here the same way as the entry timeframe — HTF close
    above its own session VWAP(close) -> bullish bias; below -> bearish
    bias. Only setups matching that bias are considered.
  - Lower timeframe (15m or 5m): entry trigger.

Sell setup (only when the HTF bias is bearish):
  - A candle opens ABOVE VWAP and closes BELOW the lower Bollinger Band.
  - VWAP must itself be positioned above the lower Bollinger Band at that
    time (otherwise the "reversal" reading doesn't hold).
  - Stop-loss at the entry candle's high.
  - Book ~50% at 1:2, trail the remainder toward 1:3 as long as price
    stays below VWAP.

Buy setup (only when the HTF bias is bullish):
  - A candle opens BELOW VWAP and closes ABOVE the upper Bollinger Band.
  - Stop-loss at the entry candle's low.
  - Book ~50% at 1:2, trail the remainder toward 1:3 while price holds
    above VWAP.

Skip entries when the Bollinger Bands are flat (low width relative to
price) — that signals a lack of momentum, not a genuine breakout.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.indicators import add_bollinger_bands
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.intraday_shared import enrich_intra_live

logger = logging.getLogger(__name__)

YOUTUBE_BB_VWAP_URL = "https://www.youtube.com/watch?v=5s_6CLbEa2g"

HTF_OPTIONS = ["1h", "4h"]
LTF_OPTIONS = ["5m", "15m"]


@dataclass
class BbVwapReversalConfig:
    htf_tf: str = "1h"
    execution_tf: str = "15m"
    bb_length: int = 20
    bb_mult: float = 1.0
    min_bb_width_pct: float = 0.15   # (upper - lower) / price, as a % — below this, treat the bands as "flat"
    rr_ratio: float = 2.0            # partial-book risk:reward
    trail_rr_ratio: float = 3.0      # stretch target for the trailed remainder
    htf_lookback: int = 250
    ltf_lookback: int = 500
    min_htf_bars: int = 30
    min_ltf_bars: int = 30


def _add_vwap_close(df: pd.DataFrame) -> pd.DataFrame:
    """Session-anchored VWAP using CLOSE as the price source (the video's
    modified "Source: Close" setting) rather than the usual typical price."""
    out = df.copy()
    cv = out["close"] * out["volume"]
    try:
        if isinstance(out.index, pd.DatetimeIndex) and len(np.unique(out.index.date)) > 1:
            out["vwap_close"] = (
                cv.groupby(out.index.date).cumsum()
                / out["volume"].groupby(out.index.date).cumsum().replace(0, np.nan)
            )
        else:
            out["vwap_close"] = cv.cumsum() / out["volume"].cumsum().replace(0, np.nan)
    except Exception:
        out["vwap_close"] = cv.cumsum() / out["volume"].cumsum().replace(0, np.nan)
    return out


def _fetch_tf(
    ticker: str, tf: str, market: str, *, groww_token: str = "", exchange: str = "NSE", limit: int = 400,
) -> pd.DataFrame:
    is_crypto = "CoinDCX" in market
    df = fetch_data_for_gap_scan(ticker, tf, market, groww_token, exchange, limit=limit)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < 20:
        df = normalize_ohlcv(fetch_ohlcv_yfinance(ticker, tf, is_crypto=is_crypto, limit=limit, market=market))
    return df


def htf_bias_from_df(htf_df: pd.DataFrame) -> tuple[str, float | None, float | None]:
    work = _add_vwap_close(htf_df)
    last = work.iloc[-1]
    price = float(last["close"])
    vwap = float(last["vwap_close"]) if pd.notna(last.get("vwap_close")) else None
    if vwap is None:
        return "NEUTRAL", price, None
    if price > vwap:
        return "BULL", price, vwap
    if price < vwap:
        return "BEAR", price, vwap
    return "NEUTRAL", price, vwap


def scan_bb_vwap_signals(
    work: pd.DataFrame, cfg: BbVwapReversalConfig, htf_bias: str, upper_col: str, lower_col: str,
) -> list[dict[str, Any]]:
    if work.empty or "vwap_close" not in work.columns or upper_col not in work.columns:
        return []
    if htf_bias not in ("BULL", "BEAR"):
        return []

    signals: list[dict[str, Any]] = []
    opens = work["open"].to_numpy()
    closes = work["close"].to_numpy()
    highs = work["high"].to_numpy()
    lows = work["low"].to_numpy()
    vwap = work["vwap_close"].to_numpy()
    upper = work[upper_col].to_numpy()
    lower = work[lower_col].to_numpy()

    for i in range(len(work)):
        v, u, l = vwap[i], upper[i], lower[i]
        if any(pd.isna(x) for x in (v, u, l)):
            continue
        o, c = float(opens[i]), float(closes[i])
        v, u, l = float(v), float(u), float(l)
        if c <= 0:
            continue
        bb_width_pct = (u - l) / c * 100
        if bb_width_pct < cfg.min_bb_width_pct:
            continue  # bands flat -> no momentum, skip

        if htf_bias == "BEAR" and o > v and c < l and v > l:
            signals.append({
                "bar_index": i, "timestamp": str(work.index[i]), "direction": "SHORT",
                "entry": c, "sl_ref": float(highs[i]), "bb_width_pct": round(bb_width_pct, 3),
            })
        elif htf_bias == "BULL" and o < v and c > u:
            signals.append({
                "bar_index": i, "timestamp": str(work.index[i]), "direction": "LONG",
                "entry": c, "sl_ref": float(lows[i]), "bb_width_pct": round(bb_width_pct, 3),
            })

    return signals


def evaluate_live_signal(
    work: pd.DataFrame, signals: list[dict[str, Any]], cfg: BbVwapReversalConfig,
    htf_bias: str, htf_price: float | None, htf_vwap: float | None,
    upper_col: str, lower_col: str,
) -> dict[str, Any]:
    if work.empty:
        return {"signal": "NO_DATA", "verdict": "NO DATA", "take_trade": False}

    last = work.iloc[-1]
    price = float(last["close"])
    vwap = float(last["vwap_close"]) if pd.notna(last.get("vwap_close")) else None
    upper = float(last[upper_col]) if pd.notna(last.get(upper_col)) else None
    lower = float(last[lower_col]) if pd.notna(last.get(lower_col)) else None
    bb_width_pct = (upper - lower) / price * 100 if (upper is not None and lower is not None and price) else None

    reasons: list[str] = []
    if htf_price is not None and htf_vwap is not None:
        reasons.append(
            f"HTF ({cfg.htf_tf}) bias: **{htf_bias}** (close {htf_price:,.4g} vs session VWAP {htf_vwap:,.4g}) — "
            + ("only short setups are considered." if htf_bias == "BEAR"
               else "only long setups are considered." if htf_bias == "BULL"
               else "trend unclear, no setups considered either direction.")
        )
    if bb_width_pct is not None:
        flat = bb_width_pct < cfg.min_bb_width_pct
        reasons.append(
            f"Bollinger Band(20, {cfg.bb_mult:g}) width: {bb_width_pct:.2f}% of price — "
            + ("flat, skipping (no momentum)." if flat else "sufficient volatility for a valid setup.")
        )

    last_idx = len(work) - 1
    last_signal = signals[-1] if signals else None
    is_fresh = bool(last_signal and last_signal["bar_index"] == last_idx)

    verdict, direction, take = "WAIT", "WAIT", False
    entry = stop = partial_target = stretch_target = price
    confidence = 0.0

    if is_fresh and last_signal:
        direction = last_signal["direction"]
        entry = last_signal["entry"]
        stop = last_signal["sl_ref"]
        risk = abs(entry - stop)
        partial_target = entry - risk * cfg.rr_ratio if direction == "SHORT" else entry + risk * cfg.rr_ratio
        stretch_target = entry - risk * cfg.trail_rr_ratio if direction == "SHORT" else entry + risk * cfg.trail_rr_ratio

        confidence = 60.0 + (15.0 if last_signal.get("bb_width_pct", 0) > cfg.min_bb_width_pct * 2 else 0.0)
        take = True
        verdict = (
            ("SELL" if direction == "SHORT" else "BUY")
            + (" — opened above VWAP, closed below the lower BB" if direction == "SHORT"
               else " — opened below VWAP, closed above the upper BB")
        )
        reasons.append(
            ("Entry trigger: candle opened above VWAP and closed below the lower Bollinger Band, with VWAP "
             "still positioned above the lower band — the short reversal setup."
             if direction == "SHORT" else
             "Entry trigger: candle opened below VWAP and closed above the upper Bollinger Band — the long "
             "breakout-reversal setup.")
        )
        reasons.append(f"Stop-loss at the entry candle's {'high' if direction == 'SHORT' else 'low'} ({stop:,.4g}).")
        reasons.append(
            f"Book ~50% at 1:{cfg.rr_ratio:.0f} risk:reward ({partial_target:,.4g}); trail the remainder toward "
            f"1:{cfg.trail_rr_ratio:.0f} ({stretch_target:,.4g}) as long as price stays "
            f"{'below' if direction == 'SHORT' else 'above'} VWAP."
        )
    elif last_signal:
        reasons.append(
            f"Most recent qualifying {last_signal['direction']} setup was {last_signal['timestamp']} — "
            "not the current candle, so no fresh trigger right now."
        )
    elif htf_bias not in ("BULL", "BEAR"):
        pass
    else:
        reasons.append(
            f"No {'sell' if htf_bias == 'BEAR' else 'buy'} setup (candle open/close vs VWAP and the Bollinger "
            "Band) found in the fetched window yet."
        )

    sl_pct = round(abs(entry - stop) / entry * 100, 2) if take and entry else None
    tp_pct = round(abs(partial_target - entry) / entry * 100, 2) if take and entry else None

    hold_duration = (
        f"Intraday / short swing — book partial at 1:{cfg.rr_ratio:.0f}, trail the remainder toward "
        f"1:{cfg.trail_rr_ratio:.0f} while price holds the correct side of VWAP"
    )

    plan = make_trade_plan(
        direction=direction if take else "—", timeframe=cfg.execution_tf, stop_loss_pct=sl_pct, take_profit_pct=tp_pct,
        confidence_pct=confidence, style="swing",
        exit_rule=(
            f"Book ~50% at 1:{cfg.rr_ratio:.0f} R:R, then trail the remainder toward 1:{cfg.trail_rr_ratio:.0f} "
            "as long as price stays on the correct side of VWAP."
        ),
        max_hold_exit="Exit the trailed remainder if price closes back through VWAP against the trade.",
    )

    live = enrich_intra_live({
        "signal": direction if take else "NONE",
        "direction": direction if take else None,
        "take_trade": take,
        "verdict": verdict,
        "phase": htf_bias,
        "confidence_pct": round(confidence, 1) if take else 0.0,
        "sl_pct": sl_pct, "tp_pct": tp_pct,
        "entry_price": round(entry, 6) if take else None,
        "stop_price": round(stop, 6) if take else None,
        "target_price": round(partial_target, 6) if take else None,
        "stretch_target_price": round(stretch_target, 6) if take else None,
        "vwap": round(vwap, 6) if vwap is not None else None,
        "bb_upper": round(upper, 6) if upper is not None else None,
        "bb_lower": round(lower, 6) if lower is not None else None,
        "bb_width_pct": round(bb_width_pct, 3) if bb_width_pct is not None else None,
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": hold_duration} if take else None,
    }, hold_duration=hold_duration)

    return live


def analyze_ticker(
    ticker: str, market: str, *, cfg: BbVwapReversalConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or BbVwapReversalConfig()

    htf_df = _fetch_tf(ticker, cfg.htf_tf, market, groww_token=groww_token, exchange=exchange, limit=cfg.htf_lookback)
    if htf_df.empty or len(htf_df) < cfg.min_htf_bars:
        return {
            "ticker": ticker, "market": market,
            "error": f"Insufficient {cfg.htf_tf} data ({len(htf_df)} bars) for the HTF trend bias.",
        }
    htf_bias, htf_price, htf_vwap = htf_bias_from_df(htf_df)

    ltf_df = _fetch_tf(ticker, cfg.execution_tf, market, groww_token=groww_token, exchange=exchange, limit=cfg.ltf_lookback)
    if ltf_df.empty or len(ltf_df) < cfg.min_ltf_bars:
        return {
            "ticker": ticker, "market": market,
            "error": f"Insufficient {cfg.execution_tf} data ({len(ltf_df)} bars).",
        }

    work = _add_vwap_close(ltf_df)
    work = add_bollinger_bands(work, period=cfg.bb_length, std_dev=cfg.bb_mult, col="close")
    upper_col = f"bb_upper_{cfg.bb_length}_{cfg.bb_mult}"
    lower_col = f"bb_lower_{cfg.bb_length}_{cfg.bb_mult}"

    signals = scan_bb_vwap_signals(work, cfg, htf_bias, upper_col, lower_col)
    live = evaluate_live_signal(work, signals, cfg, htf_bias, htf_price, htf_vwap, upper_col, lower_col)

    return {
        "ticker": ticker, "market": market, "execution_tf": cfg.execution_tf, "htf_tf": cfg.htf_tf,
        "bars": len(work), "last_close": float(work["close"].iloc[-1]),
        "signal_history": signals[-8:], "live": live,
    }


def scan_universe(
    tickers: list[str], market: str, *, cfg: BbVwapReversalConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or BbVwapReversalConfig()
    results = []
    for ticker in tickers:
        try:
            results.append(analyze_ticker(ticker, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            logger.debug("BB+VWAP Reversal scan failed for %s: %s", ticker, exc)
            results.append({"ticker": ticker, "market": market, "error": str(exc)[:200]})

    entries = [r for r in results if not r.get("error") and (r.get("live") or {}).get("take_trade")]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market, "execution_tf": cfg.execution_tf, "results": results,
        "entries": entries, "entry_count": len(entries),
    }
