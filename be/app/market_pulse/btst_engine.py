"""
btst_engine.py
-----------------
Buy Today Sell Tomorrow / Sell Today Buy Tomorrow — the classic NSE
overnight-momentum play (buy strength into today's close, exit tomorrow
before delivery actually settles; the short-side mirror, STBT, sells
weakness into today's close and covers tomorrow) hardened with the checks
an experienced desk trader and an institutional derivatives desk would both
apply before actually risking capital overnight with no live stop protecting
the position while the market is closed:

  1. Closing-strength signature (Close Location Value) — where today's close
     sits within today's own high-low range. A close in the top of the range
     (institutional buying absorbing all supply into the close) is the
     classic BTST tell; a close in the bottom of the range is the STBT
     mirror. A close mid-range means no real conviction either way — no
     signal, not a weak one.
  2. Trend alignment — buying strength only counts for more when it's *with*
     the higher-timeframe trend (EMA20/50 stack), not a lone counter-trend
     pop that's more likely to fade overnight.
  3. Volume confirmation, with a climax-exhaustion guard — elevated volume
     backs genuine accumulation/distribution, but abnormally extreme volume
     (a blow-off spike) is flagged as chase risk rather than rewarded, since
     that's often euphoria/panic, not smart accumulation.
  4. Relative strength vs Nifty 50 — the stock must be out-performing (BTST)
     or under-performing (STBT) the index on the day, so this isn't just a
     broad market move dressed up as a single-name signal.
  5. VWAP position — closing on the "richer" side of today's volume-weighted
     average price is the same institutional benchmark a dealing desk
     watches — buyers/sellers paid up through the session rather than
     drifting on thin volume.
  6. RSI chase-risk guard (pro_trade_shared.momentum_exhaustion_note) — an
     already-extended move overnight carries real gap-against-you risk.
  7. Options-market OI buildup (reusing option_chain_engine +
     option_short_long_engine.classify_oi_buildup, the same NSE-derivatives
     read Options → Market Prediction uses) — a fresh Long/Short Buildup is
     genuine institutional derivatives-market conviction building behind the
     move, the single highest-value institutional check here; gracefully
     skipped (not penalized) for cash-only names with no F&O contracts.
  8. No late-session fade — the final stretch of the session shouldn't be
     reversing hard against the signal direction (distribution into the
     close disguised as a strong-looking daily candle).
  9. A genuine historical self-check — this exact ticker's own last ~90
     sessions are scanned for the same closing-strength signature, and the
     empirical next-day follow-through hit-rate is reported and scored, not
     just assumed from theory.
 10. Trading-judgment layer — ATR-sane stop/target (not a raw guess), a
     reward:risk floor, liquidity floor, and a final A/B/C quality grade,
     via the same pro_trade_shared helpers every other Pro Trade engine uses.

On top of that core read, the user can opt into further-analysis confluence
checks reused from elsewhere in this app (PA-VP-SMC, Volume Spread - Next
Candle, Elliott Wave, BB Mean Reversion, Support & Resistance, and a genuine
higher-timeframe Trend & Strength read) — the exact same dispatcher built for
Trading Hub → Intra-Hedging, reused here rather than re-derived.

STBT is the short-side mirror of BTST — since NSE cash-segment short
positions cannot be carried overnight, an STBT idea is explicitly flagged as
requiring execution via stock futures/options, not a plain cash-market sell.

For a deeper institutional-ownership cross-check before sizing a position,
also see Command Center → Smart Money Activity for this ticker's fund/ETF
holdings trend — that read is batch/holdings-data driven (not a live
intraday signal) so it isn't folded into this scan directly, but it's a
natural complementary check.

Works across all 4 asset classes (india/us/crypto/commodity) via
gap_trading.fetch_data_for_gap_scan for price data, with relative strength
measured against a per-market benchmark (Nifty 50 / SPY / Bitcoin — US and
Commodity share SPY since this app has no separate commodity benchmark and
both already share one fetch route elsewhere). Two checks are genuinely
India/NSE-specific and are skipped (not faked) outside India: the
options-market OI-buildup read (no F&O option-chain feed exists for other
markets in this app) and the "STBT needs stock futures/options" execution
note (US allows overnight short margin positions; this app's crypto market
is already CoinDCX *futures*, so shorting isn't cash-segment-restricted
there either) — the classic "exploit delivery settlement" framing behind
BTST is genuinely an NSE mechanic, so outside India this is a generalized
closing-strength overnight-momentum read rather than a delivery-timing play.

Research / education only — not financial advice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.index_ohlcv import fetch_index_ohlcv_for_interval
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.pa_vp_smc_engine import classify_trend
from app.market_pulse.ticker_utils import is_crypto_market, is_us_market
from app.market_pulse.pro_trade_shared import (
    ConfidenceScore,
    atr as _atr_ind,
    atr_sane_stop_target,
    build_pro_trade_ai_context,
    liquidity_ok,
    momentum_exhaustion_note,
    pro_trade_ai_system,
    quality_grade,
    rr_ratio,
    rsi as _rsi_ind,
    sl_tp_pct,
    volume_zscore,
)

logger = logging.getLogger(__name__)

STRATEGY_NAME = "Buy Today Sell Tomorrow / Sell Today Buy Tomorrow"

# Per-market relative-strength benchmark — India uses the NSE index path
# (fetch_index_ohlcv_for_interval), US/Crypto reuse the same
# fetch_data_for_gap_scan route as the scanned ticker itself. Commodity has
# no dedicated benchmark anywhere in this app and shares US's market string
# at the fetch layer already, so it naturally falls through to SPY too.
BENCHMARK_INDIA = "NIFTY 50"
BENCHMARK_US = "SPY"
BENCHMARK_CRYPTO = "B-BTCUSDT"

# Same 6 optional confluence checks built for Trading Hub → Intra-Hedging —
# reused here via the same dispatcher rather than re-derived.
FURTHER_ANALYSIS_OPTIONS: list[dict[str, str]] = [
    {"id": "pa_vp_smc", "label": "PA-VP-SMC"},
    {"id": "volume_spread_next_candle", "label": "Volume Spread - Next Candle"},
    {"id": "elliott_wave", "label": "Elliott Wave"},
    {"id": "bb_mean_reversion", "label": "BB Mean Reversion"},
    {"id": "support_resistance", "label": "Support & Resistance"},
    {"id": "mtf_trend_strength", "label": "Trend & Strength (MTF)"},
]
_FURTHER_ANALYSIS_CONFIRM_POINTS = 6.0
_FURTHER_ANALYSIS_DISAGREE_POINTS = 4.0


@dataclass
class BtstConfig:
    lookback_bars: int = 250
    intraday_tf: str = "15m"
    min_clv: float = 0.65  # Close Location Value threshold for "closed strong" (BTST) / "closed weak" (STBT, mirrored as <= 1 - min_clv)
    min_volume_zscore: float = 0.8
    climax_volume_zscore: float = 3.5  # above this, volume reads as a blow-off/climax rather than healthy accumulation
    min_relative_strength_pct: float = 0.3  # stock must beat (BTST) / lag (STBT) the index by at least this many pts today
    sl_atr_mult: float = 0.7
    tp_atr_mult: float = 1.4
    min_rr: float = 1.3
    historical_lookback_days: int = 90
    check_oi_buildup: bool = True
    further_analysis: list[str] = field(default_factory=list)


def _build_chart_data(df: pd.DataFrame, max_bars: int = 260) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    view = df.iloc[-max_bars:] if len(df) > max_bars else df
    return [
        {
            "time": str(idx),
            "open": round(float(bar["open"]), 6),
            "high": round(float(bar["high"]), 6),
            "low": round(float(bar["low"]), 6),
            "close": round(float(bar["close"]), 6),
            "volume": round(float(bar["volume"]), 2) if "volume" in bar and pd.notna(bar["volume"]) else None,
        }
        for idx, bar in view.iterrows()
    ]


def _relative_strength(
    stock_chg_pct: float | None, market: str, is_india: bool, *, groww_token: str, exchange: str,
) -> dict[str, Any]:
    if stock_chg_pct is None:
        return {"available": False}
    try:
        if is_india:
            bench = fetch_index_ohlcv_for_interval(
                BENCHMARK_INDIA, "1d", limit=10, groww_token=groww_token, exchange=exchange,
            )
            label = BENCHMARK_INDIA
        else:
            ticker = BENCHMARK_CRYPTO if is_crypto_market(market) else BENCHMARK_US
            bench = fetch_data_for_gap_scan(
                ticker, "1d", market, groww_token=groww_token, exchange=exchange, limit=10,
            )
            label = ticker
        bench = normalize_ohlcv(bench) if bench is not None else None
    except Exception as exc:
        logger.debug("BTST benchmark fetch failed: %s", exc)
        bench = None
    if bench is None or bench.empty or len(bench) < 2:
        return {"available": False}
    prev, last = float(bench["close"].iloc[-2]), float(bench["close"].iloc[-1])
    if prev <= 0:
        return {"available": False}
    index_chg_pct = (last - prev) / prev * 100.0
    return {
        "available": True, "benchmark": label, "index_chg_pct": round(index_chg_pct, 3),
        "relative_pct": round(stock_chg_pct - index_chg_pct, 3),
    }


def _vwap_position(ticker: str, market: str, cfg: BtstConfig, *, groww_token: str, exchange: str) -> dict[str, Any]:
    try:
        intraday = fetch_data_for_gap_scan(
            ticker, cfg.intraday_tf, market, groww_token=groww_token, exchange=exchange, limit=40,
        )
        intraday = normalize_ohlcv(intraday) if intraday is not None else None
    except Exception as exc:
        logger.debug("BTST VWAP fetch failed for %s: %s", ticker, exc)
        intraday = None
    if intraday is None or intraday.empty or "volume" not in intraday.columns:
        return {"available": False}

    from app.market_pulse.indicators import add_vwap

    vdf = add_vwap(intraday.copy())
    last_vwap = vdf["vwap"].iloc[-1]
    if pd.isna(last_vwap):
        return {"available": False}
    return {"available": True, "vwap": round(float(last_vwap), 6), "_intraday": intraday}


def _late_session_check(intraday_df: pd.DataFrame | None, direction: str) -> dict[str, Any]:
    """Flags a hard fade against the signal direction in the final stretch of
    the session — a strong-looking daily candle that was actually being sold
    (BTST) or bought back (STBT) into the close in its last hour."""
    if intraday_df is None or intraday_df.empty or "close" not in intraday_df.columns:
        return {"available": False}
    closes = intraday_df["close"].astype(float).dropna()
    if len(closes) < 6:
        return {"available": False}
    n = min(4, len(closes) - 2)
    ref = float(closes.iloc[-1 - n])
    if ref <= 0:
        return {"available": False}
    last_move_pct = (float(closes.iloc[-1]) - ref) / ref * 100.0
    is_long = direction == "LONG"
    confirms = (is_long and last_move_pct >= -0.15) or (not is_long and last_move_pct <= 0.15)
    return {"available": True, "last_move_pct": round(last_move_pct, 3), "confirms": confirms}


def _historical_edge(df: pd.DataFrame, is_long: bool, cfg: BtstConfig) -> dict[str, Any]:
    """This ticker's own history: of the last `historical_lookback_days`
    sessions that showed this same closing-strength signature (excluding
    today), what fraction saw the next day's close continue the same way? A
    real empirical check, not just a rule applied on theory alone."""
    n = len(df)
    start = max(0, n - cfg.historical_lookback_days - 2)
    end = n - 1  # exclude today itself as a signal day
    if end - start < 20:
        return {"available": False}
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    wins = total = 0
    for i in range(start, end):
        rng = highs[i] - lows[i]
        if rng <= 0:
            continue
        clv = (closes[i] - lows[i]) / rng
        is_signal = clv >= cfg.min_clv if is_long else clv <= (1 - cfg.min_clv)
        if not is_signal:
            continue
        total += 1
        if is_long and closes[i + 1] > closes[i]:
            wins += 1
        elif not is_long and closes[i + 1] < closes[i]:
            wins += 1
    if total < 5:
        return {"available": False, "sample_size": total}
    return {"available": True, "sample_size": total, "hit_rate_pct": round(wins / total * 100, 1)}


def _oi_buildup_check(ticker: str, price_chg_pct: float | None, *, groww_token: str) -> dict[str, Any]:
    try:
        from app.market_pulse.option_chain_engine import fetch_option_chain
        from app.market_pulse.option_short_long_engine import _with_retry, classify_oi_buildup
    except Exception:
        return {"available": False}
    try:
        chain = _with_retry(lambda: fetch_option_chain(ticker, False, groww_token))
    except Exception as exc:
        logger.debug("BTST OI-buildup option-chain fetch failed for %s: %s", ticker, exc)
        chain = None
    if not chain or not chain.get("strikes"):
        return {"available": False}
    return {"available": True, **classify_oi_buildup(chain, price_chg_pct)}


def _apply_further_analysis(
    ticker: str, direction: str, checks: list[str], *, market: str, groww_token: str, exchange: str,
) -> tuple[list[str], float]:
    valid_ids = {o["id"] for o in FURTHER_ANALYSIS_OPTIONS}
    valid = [c for c in (checks or []) if c in valid_ids]
    if not valid:
        return [], 0.0

    from app.trading_hubs.intra_hedging_engine import _run_one_further_check

    reasons: list[str] = []
    delta = 0.0
    for check_id in valid:
        confirmed, note = _run_one_further_check(
            check_id, ticker, market, direction,
            momentum_timeframe="1d", groww_token=groww_token, exchange=exchange,
        )
        if note:
            reasons.append(note)
        if confirmed is True:
            delta += _FURTHER_ANALYSIS_CONFIRM_POINTS
        elif confirmed is False:
            delta -= _FURTHER_ANALYSIS_DISAGREE_POINTS
    return reasons, delta


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: BtstConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or BtstConfig()
    out: dict[str, Any] = {
        "ticker": ticker,
        "strategy": STRATEGY_NAME,
        "error": None,
        "take_trade": False,
        "signal": "NEUTRAL",
        "direction": "NONE",
        "verdict": "No read yet",
        "confidence_pct": None,
        "grade": None,
        "sl_pct": None,
        "tp_pct": None,
        "chart_data": [],
        "rules": [
            "Core signal: Close Location Value (CLV) — where today's close sits within today's high-low range. "
            "A close in the top of the range = BTST candidate (bought strength into the close); a close in the "
            "bottom of the range = STBT candidate (sold weakness into the close). Mid-range close = no signal.",
            "Confirmation layer: higher-timeframe trend alignment (EMA20/50 stack), elevated-but-not-climactic "
            "volume, out/under-performance vs a per-market benchmark (Nifty 50 / SPY / Bitcoin), VWAP position, "
            "an RSI chase-risk guard, no hard late-session fade, and this ticker's own empirical historical "
            "follow-through rate for this exact signature. Options-market OI buildup (fresh institutional "
            "derivatives conviction) is checked for India names only — no F&O option-chain feed exists for "
            "other markets in this app.",
            "Optional further analysis (pick any): PA-VP-SMC, Volume Spread - Next Candle, Elliott Wave, BB Mean "
            "Reversion, Support & Resistance, and a genuine higher-timeframe Trend & Strength read — each adds "
            "independent confirmation on top of the core BTST/STBT read.",
            "Stop sits just beyond today's low (BTST) / high (STBT), sanity-checked against ATR; target is an "
            "ATR-scaled overnight move, reward:risk floor enforced. For India, STBT requires stock futures/"
            "options since NSE cash-segment shorts cannot be carried overnight.",
        ],
    }

    try:
        df = fetch_data_for_gap_scan(
            ticker, "1d", market, groww_token=groww_token, exchange=exchange, limit=cfg.lookback_bars,
        )
    except Exception as exc:
        out["error"] = f"Data fetch failed: {exc}"
        return out

    df = normalize_ohlcv(df)
    if df is None or df.empty or len(df) < 40:
        out["error"] = "Insufficient daily OHLCV for BTST/STBT analysis"
        return out

    today = df.iloc[-1]
    today_open, today_high, today_low, today_close = (
        float(today["open"]), float(today["high"]), float(today["low"]), float(today["close"]),
    )
    prev_close = float(df["close"].iloc[-2]) if len(df) >= 2 else None
    entry = today_close
    out["ltp"] = round(entry, 6)
    out["bars"] = len(df)
    out["chart_data"] = _build_chart_data(df)

    rng = today_high - today_low
    if rng <= 0:
        out["verdict"] = "Today's high-low range is zero/invalid — nothing to read."
        out["plain_english"] = f"SIGNAL: NEUTRAL. {out['verdict']}"
        return out

    clv = (today_close - today_low) / rng
    out["clv"] = round(clv, 3)

    if clv >= cfg.min_clv:
        direction = "LONG"
    elif clv <= (1 - cfg.min_clv):
        direction = "SHORT"
    else:
        out["verdict"] = (
            f"Closed mid-range today (CLV {clv:.2f}, range {today_low:,.4g}-{today_high:,.4g}) — no real "
            "institutional conviction either way. Not a BTST or STBT candidate."
        )
        out["plain_english"] = f"SIGNAL: NEUTRAL. {out['verdict']}"
        return out

    is_long = direction == "LONG"
    is_india = not is_crypto_market(market) and not is_us_market(market)
    stock_chg_pct = (
        (today_close - prev_close) / prev_close * 100.0 if prev_close and prev_close > 0 else None
    )

    trend = classify_trend(df)
    trend_aligned = (is_long and trend.get("trend") == "bullish") or (not is_long and trend.get("trend") == "bearish")

    vz_series = volume_zscore(df["volume"], 20).dropna() if "volume" in df.columns else pd.Series(dtype=float)
    vz_val = float(vz_series.iloc[-1]) if not vz_series.empty else None
    vol_confirms = vz_val is not None and cfg.min_volume_zscore <= vz_val < cfg.climax_volume_zscore
    vol_climax = vz_val is not None and vz_val >= cfg.climax_volume_zscore

    rel = _relative_strength(stock_chg_pct, market, is_india, groww_token=groww_token, exchange=exchange)
    rel_confirms = False
    if rel.get("available"):
        rel_pct = rel["relative_pct"]
        rel_confirms = (is_long and rel_pct >= cfg.min_relative_strength_pct) or (
            not is_long and -rel_pct >= cfg.min_relative_strength_pct
        )

    vwap_info = _vwap_position(ticker, market, cfg, groww_token=groww_token, exchange=exchange)
    intraday_df = vwap_info.pop("_intraday", None) if vwap_info.get("available") else None
    vwap_confirms = False
    if vwap_info.get("available"):
        vwap_val = vwap_info["vwap"]
        vwap_confirms = (is_long and entry > vwap_val) or (not is_long and entry < vwap_val)

    rsi_series = _rsi_ind(df["close"], 14).dropna()
    rsi_val = float(rsi_series.iloc[-1]) if not rsi_series.empty else None
    exhaustion_pts, exhaustion_note = momentum_exhaustion_note(rsi_val, direction)

    late_session = _late_session_check(intraday_df, direction)

    hist_edge = _historical_edge(df, is_long, cfg)

    oi = (
        _oi_buildup_check(ticker, stock_chg_pct, groww_token=groww_token)
        if (cfg.check_oi_buildup and is_india) else {"available": False}
    )

    atr_series = _atr_ind(df, 14)
    atr_val = float(atr_series.iloc[-1]) if pd.notna(atr_series.iloc[-1]) else entry * 0.01
    raw_stop = today_low - atr_val * cfg.sl_atr_mult if is_long else today_high + atr_val * cfg.sl_atr_mult
    raw_target = entry + atr_val * cfg.tp_atr_mult if is_long else entry - atr_val * cfg.tp_atr_mult
    stop, target, stop_adjusted = atr_sane_stop_target(direction, entry, raw_stop, raw_target, atr_val)
    sl_pct, tp_pct = sl_tp_pct(direction, entry, stop, target)
    rr = rr_ratio(sl_pct, tp_pct)

    score = ConfidenceScore(
        35,
        f"Closed {'in the top' if is_long else 'in the bottom'} of today's range (CLV {clv:.2f}) — the classic "
        f"{'BTST' if is_long else 'STBT'} closing-strength signature.",
    )
    score.add(
        trend_aligned, 12,
        f"Price is in a genuine {trend.get('trend')} trend (EMA20/50 stack) — {'buying strength into an uptrend' if is_long else 'selling weakness into a downtrend'}, not {'catching a falling knife' if is_long else 'fighting an uptrend'}.",
        f"EMA stack is {trend.get('trend', 'mixed')} — this trade would be fighting (or isn't backed by) the higher-timeframe trend.",
    )
    score.add(
        vol_confirms, 10,
        f"Elevated volume ({vz_val:.1f}σ above average) backs real participation behind the move, without reading as a blow-off climax." if vz_val is not None else "",
        (f"Volume ({vz_val:.1f}σ) is a blow-off climax, not healthy accumulation — chase risk into the close." if vol_climax else
         (f"Volume ({vz_val:.1f}σ) isn't elevated enough to confirm real participation." if vz_val is not None else "Volume data unavailable")),
    )
    bench_label = rel.get("benchmark", "the benchmark")
    score.add(
        rel_confirms, 12,
        f"Out-performing {bench_label} by {rel.get('relative_pct'):+.2f} points today — this is stock-specific conviction, not just a market-wide move." if is_long and rel.get("available") else
        (f"Under-performing {bench_label} by {abs(rel.get('relative_pct', 0)):.2f} points today — genuine relative weakness, not just a market-wide pullback." if rel.get("available") else ""),
        f"Relative strength vs {bench_label} doesn't confirm this as a stock-specific move." if rel.get("available") else "Benchmark data unavailable for a relative-strength read.",
    )
    score.add(
        vwap_confirms, 8,
        f"Closed {'above' if is_long else 'below'} today's VWAP ({vwap_info.get('vwap'):,.4g}) — buyers/sellers paid up through the session, not drifting on thin volume." if vwap_info.get("available") else "",
        "Closed on the wrong side of VWAP for this trade direction." if vwap_info.get("available") else "Intraday data unavailable for a VWAP read.",
    )
    if exhaustion_note:
        score.score += exhaustion_pts
        score.reasons.append(exhaustion_note)
    if oi.get("available"):
        label, bias = oi.get("label"), oi.get("bias")
        strong_match = (is_long and label == "Long Buildup") or (not is_long and label == "Short Buildup")
        weak_match = (is_long and label == "Short Covering") or (not is_long and label == "Long Unwinding")
        if strong_match:
            score.score += 16
            score.reasons.append(f"+16: [Options OI] {oi.get('reason', '')}")
        elif weak_match:
            score.score += 6
            score.reasons.append(f"+6: [Options OI] {oi.get('reason', '')}")
        else:
            score.reasons.append(f"[Options OI] {oi.get('reason', 'Derivatives OI read does not confirm this direction.')}")
    elif is_india:
        score.reasons.append(
            "No F&O option chain for this ticker — cash-only name, options-market OI-buildup institutional-"
            "conviction read unavailable (neither confirmed nor denied)."
        )
    else:
        score.reasons.append(
            "Options-market OI-buildup read is India/NSE-specific — no F&O option-chain feed exists for this "
            "market in this app (neither confirmed nor denied)."
        )
    if late_session.get("available"):
        score.add(
            late_session["confirms"], 8,
            f"No late-session fade — the final stretch held ({late_session['last_move_pct']:+.2f}%), not distribution disguised as a strong daily candle.",
            f"The final stretch of the session moved {late_session['last_move_pct']:+.2f}% against this direction — possible distribution/covering into the close, undercutting the daily candle's story.",
        )
    else:
        score.reasons.append("Not enough intraday data to check for a late-session fade.")
    if hist_edge.get("available"):
        hr = hist_edge["hit_rate_pct"]
        score.add(
            hr >= 55, 10,
            f"This ticker's own history: this closing-strength signature followed through the next day {hr:.0f}% of the time over the last {hist_edge['sample_size']} occurrences — a real empirical edge, not just theory.",
            f"This ticker's own history shows only a {hr:.0f}% next-day follow-through rate ({hist_edge['sample_size']} occurrences) — this exact signature hasn't been reliable on this specific name.",
        )
    else:
        score.reasons.append(
            "Not enough historical occurrences of this exact closing-strength signature on this ticker to "
            "compute a reliable historical edge — proceeding on the rule-based checks alone."
        )
    score.add(
        rr is not None and rr >= cfg.min_rr, 8,
        f"Reward:risk of {rr:.1f}:1 clears the {cfg.min_rr:g}:1 floor — worth the overnight gap risk." if rr else "",
        "Reward:risk is thin for the overnight gap risk this trade carries.",
    )

    confidence_pct, reasons = score.finalize()

    fa_reasons: list[str] = []
    if cfg.further_analysis:
        fa_reasons, fa_delta = _apply_further_analysis(
            ticker, direction, cfg.further_analysis, market=market, groww_token=groww_token, exchange=exchange,
        )
        if fa_reasons:
            confidence_pct = round(min(95.0, max(10.0, confidence_pct + fa_delta)), 1)
            reasons = reasons + fa_reasons

    liquidity = liquidity_ok(vz_val)
    grade = quality_grade(confidence_pct, rr, liquidity, stop_adjusted)

    out.update({
        "take_trade": True,
        "direction": direction,
        "signal": "BULLISH" if is_long else "BEARISH",
        "verdict": (
            f"{'BTST' if is_long else 'STBT'} candidate — closed {'strong' if is_long else 'weak'} "
            f"(CLV {clv:.2f}), {confidence_pct:.0f}% confidence."
        ),
        "entry_price": round(entry, 6),
        "stop_price": round(stop, 6) if stop is not None else None,
        "target_price": round(target, 6) if target is not None else None,
        "sl_pct": sl_pct,
        "tp_pct": tp_pct,
        "rr": rr,
        "confidence_pct": confidence_pct,
        "confidence_reasons": reasons,
        "grade": grade,
        "today_open": round(today_open, 6),
        "today_high": round(today_high, 6),
        "today_low": round(today_low, 6),
        "today_close": round(today_close, 6),
        "day_chg_pct": round(stock_chg_pct, 3) if stock_chg_pct is not None else None,
        "trend": trend.get("trend"),
        "volume_zscore": round(vz_val, 2) if vz_val is not None else None,
        "volume_climax": vol_climax,
        "relative_strength": rel if rel.get("available") else None,
        "vwap": vwap_info.get("vwap") if vwap_info.get("available") else None,
        "rsi": round(rsi_val, 1) if rsi_val is not None else None,
        "oi_buildup": {k: v for k, v in oi.items() if k not in ("strikes",)} if oi.get("available") else None,
        "late_session_check": late_session if late_session.get("available") else None,
        "historical_edge": hist_edge if hist_edge.get("available") else None,
        "stop_adjusted_for_atr": stop_adjusted,
        "further_analysis_applied": list(cfg.further_analysis or []),
        "is_india": is_india,
    })
    out["plain_english"] = _explain(out, cfg)
    return out


def _explain(out: dict[str, Any], cfg: BtstConfig) -> str:
    direction = out.get("direction", "NONE")
    is_long = direction == "LONG"
    conf = out.get("confidence_pct")
    sl, tp, rr = out.get("sl_pct"), out.get("tp_pct"), out.get("rr")
    label = "BTST (Buy Today, Sell Tomorrow)" if is_long else "STBT (Sell Today, Buy Tomorrow)"

    plan = [f"SIGNAL: {out.get('signal')} ({label})"]
    if conf is not None:
        plan.append(f"confidence {conf:.0f}%")
    if sl is not None and tp is not None:
        rr_note = f" (reward:risk 1:{rr:g})" if rr else ""
        plan.append(f"SL {sl:.1f}% · TP {tp:.1f}%{rr_note}")
    plan_line = " — ".join(plan)

    parts = [
        f"{plan_line}. {out['ticker']} closed {'strong, in the top' if is_long else 'weak, in the bottom'} of "
        f"today's range (CLV {out.get('clv', 0):.2f}) — the classic {'BTST' if is_long else 'STBT'} "
        f"closing-strength signature institutional buyers/sellers leave behind at the end of a session.",
    ]
    checks = []
    if out.get("trend") in ("bullish", "bearish"):
        checks.append(f"a {out['trend']} higher-timeframe trend")
    if out.get("volume_zscore") is not None and not out.get("volume_climax"):
        checks.append("real volume participation")
    if out.get("relative_strength"):
        checks.append(f"{'out' if is_long else 'under'}-performance vs Nifty 50")
    if out.get("vwap") is not None:
        checks.append(f"closing on the {'right' if is_long else 'right'} side of VWAP")
    oi = out.get("oi_buildup")
    if oi and oi.get("label") in ("Long Buildup", "Short Buildup"):
        checks.append(f"fresh options-market {oi['label']} — genuine institutional derivatives conviction")
    if checks:
        parts.append("Backing this up: " + ", ".join(checks) + ".")
    hist = out.get("historical_edge")
    if hist:
        parts.append(
            f"This exact signature has followed through on {out['ticker']} {hist['hit_rate_pct']:.0f}% of the "
            f"time over its last {hist['sample_size']} occurrences — a real, ticker-specific empirical edge."
        )
    if out.get("volume_climax"):
        parts.append(
            "Caution: today's volume is a blow-off climax level, not healthy accumulation — this move carries "
            "extra chase risk of reversing overnight or at tomorrow's open."
        )
    ls = out.get("late_session_check")
    if ls and not ls.get("confirms"):
        parts.append(
            f"Caution: the final stretch of the session moved {ls['last_move_pct']:+.2f}% against this "
            "direction — possible late distribution/covering the daily candle alone doesn't show."
        )
    parts.append(
        "Important: this is an OVERNIGHT position with no live stop-loss order protecting it while the market "
        "is closed — the stop above is the level to act on the moment the market reopens, not a guaranteed exit "
        "price, since a gap can open beyond it. Size accordingly."
    )
    if not is_long and out.get("is_india"):
        parts.append(
            "STBT requires execution via stock futures/options — NSE cash-segment short positions cannot be "
            "carried overnight; plan the F&O route before entering, not after."
        )
    elif not is_long:
        parts.append(
            "Confirm your broker/exchange allows carrying this short position overnight before entering."
        )
    extras = out.get("further_analysis_applied") or []
    if extras:
        parts.append(
            f"{len(extras)} optional further-analysis check(s) selected ({', '.join(extras)}) — see the "
            "confidence reasons below for exactly which ones agreed and which didn't."
        )
    parts.append(
        "For a deeper institutional-ownership cross-check before sizing, Command Center → Smart Money Activity "
        "shows this ticker's fund/ETF holdings trend — a complementary, slower-moving read this scan doesn't "
        "include directly."
    )
    return " ".join(parts)


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: BtstConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or BtstConfig()
    results: list[dict[str, Any]] = []
    for t in tickers:
        try:
            results.append(analyze_ticker(t, market, cfg=cfg, groww_token=groww_token, exchange=exchange))
        except Exception as exc:
            logger.exception("BTST/STBT analysis failed for %s", t)
            results.append({"ticker": t, "error": str(exc)[:300], "take_trade": False})

    entries = [r for r in results if not r.get("error") and r.get("take_trade")]
    entries.sort(key=lambda r: -(r.get("confidence_pct") or 0))
    btst_entries = [r for r in entries if r.get("direction") == "LONG"]
    stbt_entries = [r for r in entries if r.get("direction") == "SHORT"]

    return {
        "strategy": STRATEGY_NAME,
        "results": results,
        "entries": entries,
        "entry_count": len(entries),
        "btst_count": len(btst_entries),
        "stbt_count": len(stbt_entries),
        "scanned": len(results),
        "config": {
            "lookback_bars": cfg.lookback_bars,
            "min_clv": cfg.min_clv,
            "min_rr": cfg.min_rr,
        },
        "disclaimer": (
            "Overnight positions carry gap risk no live stop can protect against — this is a structured, "
            "transparent framework combining price, volume, relative strength, VWAP, options OI, and this "
            "ticker's own historical follow-through, not a guaranteed edge. STBT requires F&O execution. "
            "Research / education only, not financial advice."
        ),
    }


BTST_AI_SYSTEM = pro_trade_ai_system(
    "Buy Today Sell Tomorrow / Sell Today Buy Tomorrow",
    "A closing-strength signature (Close Location Value) determines BTST (closed strong) vs STBT (closed weak) "
    "candidacy, then scored for confidence using higher-timeframe trend alignment, volume participation "
    "(with a blow-off-climax penalty), relative strength vs Nifty 50, VWAP position, an RSI chase-risk guard, "
    "options-market OI buildup (fresh institutional derivatives conviction via option_short_long_engine), a "
    "late-session-fade check, this exact ticker's own empirical historical follow-through rate, plus optional "
    "further-analysis checks (PA-VP-SMC, Volume Spread, Elliott Wave, BB Mean Reversion, Support & Resistance, "
    "MTF Trend & Strength). Stop/target are ATR-sane, reward:risk floor enforced, A/B/C quality grade. Since "
    "this is an overnight hold, there is no live stop-loss order protecting the position while the market is "
    "closed, and STBT (short) requires stock futures/options execution, not a plain cash-market sell.",
)


def build_btst_ai_prompt(result: dict[str, Any]) -> str:
    extra: list[str] = []
    applied = result.get("further_analysis_applied")
    if isinstance(applied, list) and applied:
        extra.append(f"Optional further-analysis checks applied: {', '.join(applied)}")
    if result.get("volume_climax"):
        extra.append("Today's volume reads as a blow-off climax, not healthy accumulation — extra chase risk.")
    oi = result.get("oi_buildup")
    if oi:
        extra.append(f"Options OI buildup: {oi.get('label', '—')} ({oi.get('bias', '—')})")
    hist = result.get("historical_edge")
    if hist:
        extra.append(f"Historical follow-through on this exact ticker: {hist.get('hit_rate_pct')}% over {hist.get('sample_size')} occurrences")
    return build_pro_trade_ai_context(result, engine_label="Buy Today Sell Tomorrow / Sell Today Buy Tomorrow", extra_lines=extra or None)
