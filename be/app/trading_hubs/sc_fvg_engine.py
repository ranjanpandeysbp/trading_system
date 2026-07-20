"""
sc_fvg_engine.py
----------------------
SC - FVG — S&P micro-futures reversal-at-key-levels strategy.
Video: "How I'd Trade $4 Into $2,000 In Only 5 Days" (Riley Coleman)
https://www.youtube.com/watch?v=-xuQXmQWMCk

Core idea: trade reversals exclusively at pre-mapped key levels, never the middle
of a range, for a mechanically favorable risk-to-reward ratio:

1. Map the big picture — 15m swing highs/lows become the day's Resistance/Support zones.
2. Wait for an "unhealthy move" — a Fair Value Gap on the 5-minute chart, i.e. a rapid,
   unchecked spike into the zone that leaves buyers/sellers exhausted.
3. Wait for the reversal to actually confirm on the 1-minute chart:
   a "failed continuation" candle (a rejection candle that fails to extend the spike
   and closes back through the prior candle's low/high), plus market structure
   starting to shift (LH/LL forming for a short, HH/HL forming for a long).
4. Enter on the stop-market break of the rejection candle's structural extreme.
5. Risk management: fixed 1:3 (configurable) R:R, stop just beyond the rejection
   candle's extreme (ATR-buffered here, matching this app's structural-stop convention).

This engine fetches three timeframes internally regardless of any user selection
(the strategy's own definition, not a user-configurable choice): 15m for the HTF
zones, 5m for the Fair Value Gap ("unhealthy move"), and 1m for the rejection/entry
trigger — mirroring the video's own "map on 15m, watch the FVG on 5m, execute on 1m"
workflow.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan, fetch_ohlcv_yfinance
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.price_action import _calc_atr
from app.market_pulse.price_extremes import _find_swing_points, classify_swing_structure
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.smart_money_shared import enrich_smc_live
from app.market_pulse.ticker_utils import is_crypto_market

logger = logging.getLogger(__name__)

YOUTUBE_SC_FVG_URL = "https://www.youtube.com/watch?v=-xuQXmQWMCk"

ZONE_TF = "15m"
FVG_TF = "5m"
EXEC_TF = "1m"
HOLD_SC_FVG = (
    "Intraday scalp — fixed R:R target, trail the stop tightly behind each closing "
    "1m candle once the trade accelerates in your favor; exit fully on a stop or target hit."
)

PHASE_NO_ZONE = "NO_ZONE"
PHASE_AT_ZONE_NO_FVG = "AT_ZONE_NO_FVG"
PHASE_AWAITING_REJECTION = "AWAITING_REJECTION"
PHASE_ENTRY = "ENTRY_TRIGGERED"


@dataclass
class ScFvgConfig:
    zone_lookback_bars: int = 40
    swing_window: int = 3
    zone_proximity_pct: float = 0.15
    fvg_lookback_bars: int = 5
    fresh_bars: int = 2
    atr_period: int = 14
    rr_ratio: float = 3.0
    take_confidence_threshold: float = 60.0
    min_bars: int = 60


def _fetch_ohlcv(
    ticker: str, market: str, timeframe: str, *,
    groww_token: str = "", exchange: str = "NSE", limit: int = 300,
) -> pd.DataFrame:
    is_crypto = is_crypto_market(market)
    df = fetch_data_for_gap_scan(ticker, timeframe, market, groww_token, exchange, limit=limit)
    df = normalize_ohlcv(df)
    if df.empty or len(df) < 30:
        df = normalize_ohlcv(
            fetch_ohlcv_yfinance(ticker, timeframe, is_crypto=is_crypto, limit=limit, market=market),
        )
    return df


def _htf_zones(zone_df: pd.DataFrame, cfg: ScFvgConfig) -> tuple[float | None, float | None]:
    window = zone_df.tail(cfg.zone_lookback_bars)
    swing_highs, swing_lows = _find_swing_points(window, window=cfg.swing_window)
    resistance = max((p for _, p in swing_highs), default=None) or (
        float(window["high"].max()) if not window.empty else None
    )
    support = min((p for _, p in swing_lows), default=None) or (
        float(window["low"].min()) if not window.empty else None
    )
    return resistance, support


def _fvg_flags(fvg_df: pd.DataFrame, cfg: ScFvgConfig) -> tuple[bool, bool, int, int]:
    high2 = fvg_df["high"].shift(2)
    low2 = fvg_df["low"].shift(2)
    bullish = (fvg_df["low"] > high2) & (fvg_df["close"] > fvg_df["open"])
    bearish = (fvg_df["high"] < low2) & (fvg_df["close"] < fvg_df["open"])

    recent_bullish = bool(bullish.tail(cfg.fvg_lookback_bars).any())
    recent_bearish = bool(bearish.tail(cfg.fvg_lookback_bars).any())

    def _bars_ago(mask: pd.Series) -> int:
        hits = mask.tail(cfg.fvg_lookback_bars)
        true_positions = [i for i, v in enumerate(hits.values) if v]
        return (len(hits) - 1 - true_positions[-1]) if true_positions else -1

    return recent_bullish, recent_bearish, _bars_ago(bullish), _bars_ago(bearish)


def analyze_ticker(
    ticker: str, market: str, *, cfg: ScFvgConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or ScFvgConfig()

    zone_df = _fetch_ohlcv(ticker, market, ZONE_TF, groww_token=groww_token, exchange=exchange)
    fvg_df = _fetch_ohlcv(ticker, market, FVG_TF, groww_token=groww_token, exchange=exchange)
    exec_df = _fetch_ohlcv(ticker, market, EXEC_TF, groww_token=groww_token, exchange=exchange)

    if zone_df.empty or len(zone_df) < cfg.min_bars:
        return {"ticker": ticker, "market": market, "error": f"Insufficient {ZONE_TF} data for HTF zones ({len(zone_df)} bars, need {cfg.min_bars}+)."}
    if fvg_df.empty or len(fvg_df) < cfg.min_bars:
        return {"ticker": ticker, "market": market, "error": f"Insufficient {FVG_TF} data for FVG detection ({len(fvg_df)} bars, need {cfg.min_bars}+)."}
    if exec_df.empty or len(exec_df) < cfg.min_bars:
        return {"ticker": ticker, "market": market, "error": f"Insufficient {EXEC_TF} data for entry trigger ({len(exec_df)} bars, need {cfg.min_bars}+)."}

    resistance, support = _htf_zones(zone_df, cfg)
    recent_bullish_fvg, recent_bearish_fvg, bull_fvg_ago, bear_fvg_ago = _fvg_flags(fvg_df, cfg)

    price = float(exec_df["close"].iloc[-1])
    atr = _calc_atr(exec_df, cfg.atr_period)
    if not atr or atr <= 0:
        atr = max(price * 0.001, 1e-6)

    recent_exec = exec_df.tail(cfg.fresh_bars + 1)
    near_resistance = resistance is not None and float(recent_exec["high"].max()) >= resistance * (1 - cfg.zone_proximity_pct / 100)
    near_support = support is not None and float(recent_exec["low"].min()) <= support * (1 + cfg.zone_proximity_pct / 100)

    base = {
        "ticker": ticker, "market": market, "timeframe": EXEC_TF,
        "price": price, "atr": round(float(atr), 6),
        "resistance": round(resistance, 6) if resistance else None,
        "support": round(support, 6) if support else None,
    }

    def _finalize(*, phase: str, direction: str, verdict: str, confidence: float,
                  take: bool, reasons: list[str], entry=None, stop=None, target=None) -> dict:
        payload: dict[str, Any] = {
            "direction": direction, "take_trade": take, "verdict": verdict,
            "phase": phase, "confidence_pct": confidence, "reasons": reasons,
        }
        if entry is not None:
            sl_dist = abs(entry - stop)
            tp_dist = abs(target - entry)
            sl_pct = round(sl_dist / entry * 100, 2) if entry else 0.0
            tp_pct = round(tp_dist / entry * 100, 2) if entry else 0.0
            plan = make_trade_plan(
                direction=direction if take else "—",
                timeframe=EXEC_TF, stop_loss_pct=sl_pct, take_profit_pct=tp_pct,
                confidence_pct=confidence, style="scalping",
                exit_rule="Trail the stop behind each closing 1m candle once the trade "
                          "accelerates; full exit on stop or target.",
                max_hold_exit="Time stop: same session, exit by close.",
            )
            payload.update({
                "entry_price": round(entry, 6), "stop_price": round(stop, 6),
                "target_price": round(target, 6), "sl_pct": sl_pct, "tp_pct": tp_pct,
                "rr_ratio": cfg.rr_ratio,
                "trade_plan": {**plan, "direction": direction if take else "—", "holding_period": HOLD_SC_FVG},
            })
        base["phase"] = phase
        base["live"] = enrich_smc_live(payload, hold_duration=HOLD_SC_FVG)
        return base

    if not near_resistance and not near_support:
        res_str = f"{resistance:,.4g}" if resistance else "—"
        sup_str = f"{support:,.4g}" if support else "—"
        return _finalize(
            phase=PHASE_NO_ZONE, direction="WAIT", verdict="WAIT", confidence=0.0, take=False,
            reasons=[
                f"Price {price:,.4g} is away from both the 15m resistance ({res_str}) and "
                f"support ({sup_str}) zones — not trading the middle of the range.",
            ],
        )

    if near_resistance:
        if not recent_bullish_fvg:
            return _finalize(
                phase=PHASE_AT_ZONE_NO_FVG, direction="SHORT", verdict="WATCH SHORT", confidence=32.0, take=False,
                reasons=[
                    f"Price is testing 15m resistance ({resistance:,.4g}) but no recent bullish Fair Value "
                    f"Gap (\"unhealthy move\") in the last {cfg.fvg_lookback_bars} 5m bars — the spike into "
                    f"this level wasn't rapid/unchecked enough yet to expect exhaustion.",
                ],
            )

        last3 = exec_df.tail(cfg.fresh_bars + 1)
        rejection_idx = None
        for i in range(1, len(last3)):
            row, prev = last3.iloc[i], last3.iloc[i - 1]
            if row["close"] < row["open"] and row["close"] < prev["low"]:
                rejection_idx = i

        if rejection_idx is None:
            return _finalize(
                phase=PHASE_AWAITING_REJECTION, direction="SHORT", verdict="WATCH SHORT", confidence=45.0, take=False,
                reasons=[
                    f"At resistance ({resistance:,.4g}) with a bullish FVG {bull_fvg_ago} 5m bar(s) ago — "
                    f"the unhealthy move is in place. Waiting for a failed-continuation rejection candle "
                    f"on the 1m chart (a bearish close through the prior candle's low) to confirm.",
                ],
            )

        structure = classify_swing_structure(exec_df.tail(30), window=2)
        structure_confirms = structure.get("structure_bias") == "bearish"
        swing_high = float(last3["high"].iloc[max(0, rejection_idx - 2):rejection_idx + 1].max())
        stop = swing_high + atr * 0.25
        target = price - (stop - price) * cfg.rr_ratio
        conf = round(min(90.0, 55.0 + (20.0 if structure_confirms else 0.0) + max(0, 3 - bull_fvg_ago) * 3), 1)
        take = structure_confirms and (stop - price) > 0 and conf >= cfg.take_confidence_threshold
        reasons = [
            f"Unhealthy move: bullish FVG {bull_fvg_ago} 5m bar(s) ago spiked into 15m resistance "
            f"({resistance:,.4g}) — exhaustion setup.",
            f"Rejection: bearish 1m candle closed below the prior candle's low — failed continuation confirmed.",
            f"Market structure {'has shifted to lower-highs/lower-lows — reversal confirmed' if structure_confirms else 'has NOT shifted yet — do not guess the top, wait one more bar'}.",
        ]
        return _finalize(
            phase=PHASE_ENTRY, direction="SHORT",
            verdict=f"{'TAKE' if take else 'WATCH'} SHORT", confidence=conf, take=take,
            reasons=reasons, entry=price, stop=stop, target=target,
        )

    # near_support -> mirror image LONG setup
    if not recent_bearish_fvg:
        return _finalize(
            phase=PHASE_AT_ZONE_NO_FVG, direction="LONG", verdict="WATCH LONG", confidence=32.0, take=False,
            reasons=[
                f"Price is testing 15m support ({support:,.4g}) but no recent bearish Fair Value Gap "
                f"(\"unhealthy move\") in the last {cfg.fvg_lookback_bars} 5m bars — the drop into this "
                f"level wasn't rapid/unchecked enough yet to expect exhaustion.",
            ],
        )

    last3 = exec_df.tail(cfg.fresh_bars + 1)
    rejection_idx = None
    for i in range(1, len(last3)):
        row, prev = last3.iloc[i], last3.iloc[i - 1]
        if row["close"] > row["open"] and row["close"] > prev["high"]:
            rejection_idx = i

    if rejection_idx is None:
        return _finalize(
            phase=PHASE_AWAITING_REJECTION, direction="LONG", verdict="WATCH LONG", confidence=45.0, take=False,
            reasons=[
                f"At support ({support:,.4g}) with a bearish FVG {bear_fvg_ago} 5m bar(s) ago — the unhealthy "
                f"move is in place. Waiting for a failed-continuation rejection candle on the 1m chart "
                f"(a bullish close through the prior candle's high) to confirm.",
            ],
        )

    structure = classify_swing_structure(exec_df.tail(30), window=2)
    structure_confirms = structure.get("structure_bias") == "bullish"
    swing_low = float(last3["low"].iloc[max(0, rejection_idx - 2):rejection_idx + 1].min())
    stop = swing_low - atr * 0.25
    target = price + (price - stop) * cfg.rr_ratio
    conf = round(min(90.0, 55.0 + (20.0 if structure_confirms else 0.0) + max(0, 3 - bear_fvg_ago) * 3), 1)
    take = structure_confirms and (price - stop) > 0 and conf >= cfg.take_confidence_threshold
    reasons = [
        f"Unhealthy move: bearish FVG {bear_fvg_ago} 5m bar(s) ago spiked into 15m support "
        f"({support:,.4g}) — exhaustion setup.",
        f"Rejection: bullish 1m candle closed above the prior candle's high — failed continuation confirmed.",
        f"Market structure {'has shifted to higher-highs/higher-lows — reversal confirmed' if structure_confirms else 'has NOT shifted yet — do not guess the bottom, wait one more bar'}.",
    ]
    return _finalize(
        phase=PHASE_ENTRY, direction="LONG",
        verdict=f"{'TAKE' if take else 'WATCH'} LONG", confidence=conf, take=take,
        reasons=reasons, entry=price, stop=stop, target=target,
    )


def scan_universe(
    tickers: list[str], market: str, *, cfg: ScFvgConfig | None = None, groww_token: str = "", exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or ScFvgConfig()
    results = []
    for ticker in tickers:
        try:
            results.append(analyze_ticker(ticker, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            logger.debug("SC-FVG scan failed for %s: %s", ticker, exc)
            results.append({"ticker": ticker, "market": market, "error": str(exc)[:200]})

    entries = [r for r in results if not r.get("error") and (r.get("live") or {}).get("take_trade")]
    watches = [
        r for r in results
        if not r.get("error")
        and not (r.get("live") or {}).get("take_trade")
        and r.get("phase") in (PHASE_AT_ZONE_NO_FVG, PHASE_AWAITING_REJECTION, PHASE_ENTRY)
    ]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))
    watches.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market,
        "results": results,
        "entries": entries,
        "watchlist": watches,
        "entry_count": len(entries),
        "watch_count": len(watches),
    }
