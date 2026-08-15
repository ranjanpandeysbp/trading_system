"""
ema9_vol_rsi_momentum_engine.py
--------------------------------
9 EMA + Volume + RSI Momentum Scalping (Pro Trade).

Primary setup: 5m · Trend confirmation: 15m.

BUY (score ≥ 7): close above 9 EMA for 4+ bars, HH/HL structure, vol > SMA50,
rising volume preferred, RSI > 40 & rising (don't chase RSI>70), break of prior high.
SELL: mirror with LH/LL, RSI falling, break of prior low.

SL beyond recent swing (ATR buffer) · min RR 1:2 · optional ATR for buffer size.

Research / education only — not financial advice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.pro_trade_shared import (
    ConfidenceScore,
    atr as _atr_ind,
    atr_sane_stop_target,
    build_pro_trade_ai_context,
    ema as _ema,
    pack_trade_setup,
    pro_trade_ai_system,
    quality_grade,
    rr_ratio,
    rsi as _rsi_ind,
    sl_tp_pct,
)
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.smart_money_shared import hold_for_tf

logger = logging.getLogger(__name__)

STRATEGY_ID = "ema9_vol_rsi_momentum"
STRATEGY_NAME = "9 EMA Vol RSI Momentum Scalp"

TIMEFRAME_OPTIONS = ["1m", "5m", "15m", "30m", "1h"]

HOW_IT_WORKS = """
### 9 EMA + Volume + RSI Momentum Scalping

**5m** = entry · **15m** = trend bias.

Trade only when price has established itself above/below the 9 EMA, structure
confirms direction, volume confirms participation, RSI confirms momentum, and
the trigger candle breaks the prior bar high/low — stop beyond structure, ≥1:2 RR.

**BUY score (≥7):** above EMA · 4+ bars held · HH/HL · vol>SMA50 · vol↑ · price↑ ·
RSI>40 · RSI↑ · break prior high (+2).

**SELL score (≥7):** below EMA · 4+ bars held · LH/LL · vol>SMA50 · vol↑ · price↓ ·
RSI<60 · RSI↓ · break prior low (+2).

Skip chop around the 9 EMA. Don't chase after a huge ATR-sized candle — prefer
a pullback toward EMA then trigger.
"""

RULES = [
    "Entry TF default 5m; trend TF default 15m (price vs 9 EMA on HTF).",
    "BUY: ≥4 closes above 9 EMA · HH/HL · vol > SMA50 · RSI>40 rising · break prior high.",
    "SELL: ≥4 closes below 9 EMA · LH/LL · vol > SMA50 · RSI falling · break prior low.",
    "Score ≥ 7 required · min RR 1:2 · SL beyond recent swing + ATR buffer.",
    "Avoid EMA chop; don't chase RSI>70 longs or huge impulse candles.",
]

PRO_TIPS = [
    "Best when 15m bias agrees with 5m trigger.",
    "Volume expanding with price is stronger than price-up / volume-down.",
    "After a spike candle, wait for EMA pullback then breakout trigger.",
    "Trail under/over 9 EMA after T1 (1R).",
]

AI_SYSTEM = pro_trade_ai_system(
    STRATEGY_NAME,
    "5m momentum scalp with 15m EMA bias; score ≥7; Conf%/SL%/TP%; structure SL.",
)


@dataclass
class Ema9VolRsiMomentumConfig:
    entry_tf: str = "5m"
    trend_tf: str = "15m"
    lookback_bars: int = 400
    ema_period: int = 9
    vol_sma_period: int = 50
    rsi_period: int = 14
    hold_bars: int = 4
    min_score: int = 7
    min_rr: float = 2.0
    rsi_buy_min: float = 40.0
    rsi_buy_chase: float = 70.0
    rsi_sell_max: float = 60.0
    atr_period: int = 14
    atr_buffer_mult: float = 0.2
    require_htf_align: bool = True
    avoid_chop: bool = True
    chop_crosses_max: int = 4
    chop_lookback: int = 12
    skip_huge_candle: bool = True
    huge_candle_atr_mult: float = 2.5
    take_confidence_threshold: float = 55.0
    min_bars: int = 80
    chart_bars: int = 120
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
        need = max(int(self.min_bars), int(self.vol_sma_period) + 30, int(self.ema_period) * 5)
        if int(self.lookback_bars) < need:
            self.lookback_bars = need


def _r(x: float, n: int = 6) -> float:
    return round(float(x), n)


def _fetch(ticker: str, tf: str, market: str, token: str, exchange: str, limit: int) -> pd.DataFrame:
    raw = fetch_data_for_gap_scan(ticker, tf, market, token, exchange, limit=limit)
    return normalize_ohlcv(raw)


def _prepare(df: pd.DataFrame, cfg: Ema9VolRsiMomentumConfig) -> pd.DataFrame:
    work = df.copy()
    close = work["close"].astype(float)
    vol = work["volume"].astype(float) if "volume" in work.columns else pd.Series(np.nan, index=work.index)
    work["ema9"] = _ema(close, int(cfg.ema_period))
    work["rsi"] = _rsi_ind(close, int(cfg.rsi_period))
    work["vol_sma"] = vol.rolling(int(cfg.vol_sma_period)).mean()
    work["atr"] = _atr_ind(work, int(cfg.atr_period))
    return work


def _bars_held_side(close: pd.Series, ema: pd.Series, *, above: bool, max_look: int = 40) -> int:
    n = len(close)
    held = 0
    for j in range(n - 1, max(-1, n - 1 - max_look), -1):
        c, e = float(close.iloc[j]), float(ema.iloc[j])
        if not np.isfinite(c) or not np.isfinite(e):
            break
        ok = c > e if above else c < e
        if not ok:
            break
        held += 1
    return held


def _structure_bullish(high: pd.Series, low: pd.Series, lookback: int = 10) -> bool:
    """Recent higher-high / higher-low tilt."""
    if len(high) < lookback + 2:
        return False
    h = high.iloc[-lookback:].astype(float)
    l = low.iloc[-lookback:].astype(float)
    mid = lookback // 2
    return float(h.iloc[-1]) >= float(h.iloc[mid]) and float(l.iloc[-1]) >= float(l.iloc[0])


def _structure_bearish(high: pd.Series, low: pd.Series, lookback: int = 10) -> bool:
    if len(high) < lookback + 2:
        return False
    h = high.iloc[-lookback:].astype(float)
    l = low.iloc[-lookback:].astype(float)
    mid = lookback // 2
    return float(h.iloc[-1]) <= float(h.iloc[mid]) and float(l.iloc[-1]) <= float(l.iloc[0])


def _recent_swing_low(low: pd.Series, lookback: int = 8) -> float | None:
    if len(low) < 3:
        return None
    return float(low.iloc[-lookback:].min())


def _recent_swing_high(high: pd.Series, lookback: int = 8) -> float | None:
    if len(high) < 3:
        return None
    return float(high.iloc[-lookback:].max())


def _ema_chop(close: pd.Series, ema: pd.Series, lookback: int, max_crosses: int) -> bool:
    n = min(lookback, len(close) - 1)
    if n < 4:
        return False
    crosses = 0
    for j in range(len(close) - n, len(close)):
        prev_c, prev_e = float(close.iloc[j - 1]), float(ema.iloc[j - 1])
        c, e = float(close.iloc[j]), float(ema.iloc[j])
        if not all(np.isfinite(x) for x in (prev_c, prev_e, c, e)):
            continue
        if (prev_c <= prev_e and c > e) or (prev_c >= prev_e and c < e):
            crosses += 1
    return crosses >= max_crosses


def _vol_rising(vol: pd.Series, bars: int = 3) -> bool:
    if len(vol) < bars + 1:
        return False
    tail = vol.iloc[-(bars + 1) :].astype(float)
    if tail.isna().any():
        return False
    return all(float(tail.iloc[i]) > float(tail.iloc[i - 1]) for i in range(1, len(tail)))


def _price_rising(close: pd.Series, bars: int = 3) -> bool:
    if len(close) < bars + 1:
        return False
    tail = close.iloc[-(bars + 1) :].astype(float)
    return all(float(tail.iloc[i]) >= float(tail.iloc[i - 1]) for i in range(1, len(tail)))


def _price_falling(close: pd.Series, bars: int = 3) -> bool:
    if len(close) < bars + 1:
        return False
    tail = close.iloc[-(bars + 1) :].astype(float)
    return all(float(tail.iloc[i]) <= float(tail.iloc[i - 1]) for i in range(1, len(tail)))


def _htf_bias(df: pd.DataFrame, cfg: Ema9VolRsiMomentumConfig) -> str:
    """bullish | bearish | mixed from trend TF close vs EMA9."""
    if df is None or df.empty or len(df) < cfg.ema_period + 5:
        return "mixed"
    close = df["close"].astype(float)
    ema = _ema(close, cfg.ema_period)
    price, e = float(close.iloc[-1]), float(ema.iloc[-1])
    if not np.isfinite(price) or not np.isfinite(e):
        return "mixed"
    if price > e:
        return "bullish"
    if price < e:
        return "bearish"
    return "mixed"


def _build_chart(work: pd.DataFrame, *, max_bars: int) -> list[dict[str, Any]]:
    if work is None or work.empty:
        return []
    has_vol = "volume" in work.columns
    tail = work.iloc[-max_bars:]
    rows: list[dict[str, Any]] = []
    for idx, bar in tail.iterrows():
        row: dict[str, Any] = {
            "time": str(idx),
            "open": _r(float(bar["open"])),
            "high": _r(float(bar["high"])),
            "low": _r(float(bar["low"])),
            "close": _r(float(bar["close"])),
            "volume": _r(float(bar["volume"]), 2) if has_vol and pd.notna(bar.get("volume")) else None,
        }
        for k in ("ema9", "vol_sma", "rsi"):
            if k in bar and pd.notna(bar.get(k)):
                row[k] = _r(float(bar[k]), 6)
        rows.append(row)
    return rows


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: Ema9VolRsiMomentumConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or Ema9VolRsiMomentumConfig()
    out: dict[str, Any] = {
        "ticker": ticker,
        "timeframe": cfg.entry_tf,
        "trend_tf": cfg.trend_tf,
        "strategy": STRATEGY_ID,
        "strategy_label": STRATEGY_NAME,
        "signal": "WAIT",
        "direction": "NONE",
        "take_trade": False,
        "checks": [],
        "metrics": {},
        "pro_tips": PRO_TIPS[:4],
        "buy_score": 0,
        "sell_score": 0,
    }

    try:
        ltf_raw = _fetch(ticker, cfg.entry_tf, market, groww_token, exchange, int(cfg.lookback_bars))
        htf_raw = (
            _fetch(ticker, cfg.trend_tf, market, groww_token, exchange, max(120, int(cfg.lookback_bars) // 2))
            if cfg.require_htf_align
            else pd.DataFrame()
        )
    except Exception as exc:
        out["error"] = str(exc)[:240]
        return out

    if ltf_raw is None or len(ltf_raw) < cfg.min_bars:
        out["error"] = f"Need ≥{cfg.min_bars} {cfg.entry_tf} bars; got {0 if ltf_raw is None else len(ltf_raw)}"
        return out

    work = _prepare(ltf_raw, cfg)
    i = len(work) - 1
    if i < 5 or pd.isna(work["ema9"].iloc[i]) or pd.isna(work["rsi"].iloc[i]):
        out["error"] = "Indicators not ready"
        return out

    close = work["close"].astype(float)
    high = work["high"].astype(float)
    low = work["low"].astype(float)
    vol = work["volume"].astype(float) if "volume" in work.columns else pd.Series(np.nan, index=work.index)

    price = float(close.iloc[i])
    prev = float(close.iloc[i - 1])
    prev_high = float(high.iloc[i - 1])
    prev_low = float(low.iloc[i - 1])
    ema_v = float(work["ema9"].iloc[i])
    rsi_v = float(work["rsi"].iloc[i])
    rsi_prev = float(work["rsi"].iloc[i - 1]) if pd.notna(work["rsi"].iloc[i - 1]) else rsi_v
    vol_now = float(vol.iloc[i]) if pd.notna(vol.iloc[i]) else None
    vol_sma = float(work["vol_sma"].iloc[i]) if pd.notna(work["vol_sma"].iloc[i]) else None
    atr_v = float(work["atr"].iloc[i]) if pd.notna(work["atr"].iloc[i]) else None

    held_above = _bars_held_side(close, work["ema9"], above=True)
    held_below = _bars_held_side(close, work["ema9"], above=False)
    crossed_above = float(close.iloc[i - 1]) <= float(work["ema9"].iloc[i - 1]) and price > ema_v
    crossed_below = float(close.iloc[i - 1]) >= float(work["ema9"].iloc[i - 1]) and price < ema_v
    # "crossed" also true if currently held after a prior cross (within hold window)
    established_above = held_above >= int(cfg.hold_bars)
    established_below = held_below >= int(cfg.hold_bars)

    bull_struct = _structure_bullish(high, low)
    bear_struct = _structure_bearish(high, low)
    vol_ok = vol_now is not None and vol_sma is not None and vol_now > vol_sma
    vol_up = _vol_rising(vol)
    price_up = _price_rising(close)
    price_dn = _price_falling(close)
    rsi_rising = rsi_v > rsi_prev
    rsi_falling = rsi_v < rsi_prev
    break_high = price > prev_high
    break_low = price < prev_low
    huge = (
        atr_v is not None
        and atr_v > 0
        and (float(high.iloc[i]) - float(low.iloc[i])) >= float(cfg.huge_candle_atr_mult) * atr_v
    )
    chop = _ema_chop(close, work["ema9"], int(cfg.chop_lookback), int(cfg.chop_crosses_max)) if cfg.avoid_chop else False

    htf = _htf_bias(htf_raw, cfg) if cfg.require_htf_align and htf_raw is not None and not htf_raw.empty else "mixed"

    # ── Scores ────────────────────────────────────────────────────────────
    buy = 0
    sell = 0
    buy_bits: list[str] = []
    sell_bits: list[str] = []

    if crossed_above or established_above:
        buy += 1
        buy_bits.append("above/cross 9 EMA")
    if established_above:
        buy += 1
        buy_bits.append(f"{held_above} bars above EMA")
    if bull_struct:
        buy += 1
        buy_bits.append("HH/HL structure")
    if vol_ok:
        buy += 1
        buy_bits.append("vol > SMA50")
    if vol_up:
        buy += 1
        buy_bits.append("volume rising")
    if price_up:
        buy += 1
        buy_bits.append("price rising")
    if rsi_v > float(cfg.rsi_buy_min):
        buy += 1
        buy_bits.append(f"RSI>{cfg.rsi_buy_min:g}")
    if rsi_rising:
        buy += 1
        buy_bits.append("RSI rising")
    if break_high:
        buy += 2
        buy_bits.append("broke prior high")

    if crossed_below or established_below:
        sell += 1
        sell_bits.append("below/cross 9 EMA")
    if established_below:
        sell += 1
        sell_bits.append(f"{held_below} bars below EMA")
    if bear_struct:
        sell += 1
        sell_bits.append("LH/LL structure")
    if vol_ok:
        sell += 1
        sell_bits.append("vol > SMA50")
    if vol_up:
        sell += 1
        sell_bits.append("volume rising")
    if price_dn:
        sell += 1
        sell_bits.append("price falling")
    if rsi_v < float(cfg.rsi_sell_max):
        sell += 1
        sell_bits.append(f"RSI<{cfg.rsi_sell_max:g}")
    if rsi_falling:
        sell += 1
        sell_bits.append("RSI falling")
    if break_low:
        sell += 2
        sell_bits.append("broke prior low")

    checks = [
        {
            "id": "htf_bias",
            "label": f"{cfg.trend_tf} trend bias",
            "passed": htf != "mixed",
            "detail": f"bias: {htf}",
        },
        {
            "id": "chop",
            "label": "Not chopping 9 EMA",
            "passed": not chop,
            "detail": "clean of EMA chop" if not chop else "chopping around 9 EMA — skip",
        },
        {
            "id": "huge_candle",
            "label": "No huge impulse chase",
            "passed": not (cfg.skip_huge_candle and huge),
            "detail": "no chase spike" if not huge else "huge candle — wait pullback",
        },
        {
            "id": "buy_score",
            "label": f"BUY score ≥ {cfg.min_score}",
            "passed": buy >= int(cfg.min_score),
            "detail": f"BUY {buy}/10 · {', '.join(buy_bits) or '—'}",
        },
        {
            "id": "sell_score",
            "label": f"SELL score ≥ {cfg.min_score}",
            "passed": sell >= int(cfg.min_score),
            "detail": f"SELL {sell}/10 · {', '.join(sell_bits) or '—'}",
        },
    ]

    out["buy_score"] = buy
    out["sell_score"] = sell
    out["checks"] = checks
    out["ltp"] = _r(price)
    out["metrics"] = {
        "price": _r(price),
        "ema9": _r(ema_v),
        "rsi": _r(rsi_v, 2),
        "rsi_prev": _r(rsi_prev, 2),
        "vol": _r(vol_now, 2) if vol_now is not None else None,
        "vol_sma50": _r(vol_sma, 2) if vol_sma is not None else None,
        "atr": _r(atr_v, 4) if atr_v is not None else None,
        "held_above": held_above,
        "held_below": held_below,
        "htf_bias": htf,
        "break_high": break_high,
        "break_low": break_low,
        "buy_bits": buy_bits,
        "sell_bits": sell_bits,
    }
    out["chart_data"] = _build_chart(work, max_bars=int(cfg.chart_bars))
    out["chart_series"] = [
        {"key": "ema9", "label": "EMA 9", "color": "#fbbf24"},
    ]

    # Filters
    long_blocked = (
        chop
        or (cfg.skip_huge_candle and huge and break_high)
        or rsi_v >= float(cfg.rsi_buy_chase)
        or (cfg.require_htf_align and htf == "bearish")
        or cfg.side == "short"
    )
    short_blocked = (
        chop
        or (cfg.skip_huge_candle and huge and break_low)
        or (cfg.require_htf_align and htf == "bullish")
        or cfg.side == "long"
    )

    long_ok = buy >= int(cfg.min_score) and break_high and established_above and not long_blocked
    short_ok = sell >= int(cfg.min_score) and break_low and established_below and not short_blocked

    direction = "NONE"
    score = 0
    bits: list[str] = []
    if long_ok and (not short_ok or buy >= sell):
        direction = "LONG"
        score = buy
        bits = buy_bits
    elif short_ok:
        direction = "SHORT"
        score = sell
        bits = sell_bits

    if direction == "NONE":
        why = []
        if chop:
            why.append("EMA chop")
        if not long_ok and not short_ok:
            why.append(f"scores buy={buy} sell={sell} (need ≥{cfg.min_score} + trigger)")
        if cfg.require_htf_align and htf == "mixed":
            why.append("HTF mixed")
        out["signal"] = "WATCH" if max(buy, sell) >= int(cfg.min_score) - 2 else "WAIT"
        out["reason"] = "WAIT: " + ("; ".join(why) if why else "no confluence")
        out["plain_english"] = (
            f"{ticker} {cfg.entry_tf}: buy {buy}/10 · sell {sell}/10 · HTF {htf}. "
            f"{out['reason']}"
        )
        return out

    is_long = direction == "LONG"
    entry = price
    buffer = (atr_v * float(cfg.atr_buffer_mult)) if atr_v and atr_v > 0 else entry * 0.001
    if is_long:
        swing = _recent_swing_low(low)
        stop = (swing - buffer) if swing is not None else (entry - (atr_v or entry * 0.01) * 1.2)
        risk = max(entry - stop, entry * 0.001)
        t1 = entry + risk * float(cfg.min_rr)
        t2 = entry + risk * float(cfg.min_rr) * 1.5
        t3 = entry + risk * float(cfg.min_rr) * 2.0
    else:
        swing = _recent_swing_high(high)
        stop = (swing + buffer) if swing is not None else (entry + (atr_v or entry * 0.01) * 1.2)
        risk = max(stop - entry, entry * 0.001)
        t1 = entry - risk * float(cfg.min_rr)
        t2 = entry - risk * float(cfg.min_rr) * 1.5
        t3 = entry - risk * float(cfg.min_rr) * 2.0

    stop, t1, adjusted = atr_sane_stop_target(
        direction, entry, stop, t1, atr_v, default_rr=float(cfg.min_rr),
    )
    sl_pct_v, tp_pct_v = sl_tp_pct(direction, entry, stop, t1)
    rr = rr_ratio(sl_pct_v, tp_pct_v) or float(cfg.min_rr)

    conf = ConfidenceScore(42.0, f"{STRATEGY_NAME} score {score}")
    conf.add(score >= int(cfg.min_score), 14, f"Score {score} ≥ {cfg.min_score}", "Score thin")
    conf.add(score >= int(cfg.min_score) + 2, 8, "Strong score cushion", "Barely at threshold")
    conf.add(htf == ("bullish" if is_long else "bearish"), 10, f"HTF {cfg.trend_tf} aligned", "HTF not aligned")
    conf.add(vol_ok, 8, "Volume > SMA50", "Volume weak")
    conf.add(vol_up, 6, "Volume expanding", "Volume not expanding")
    conf.add(not chop, 6, "Not chopping EMA", "Choppy EMA")
    conf.add(not adjusted, 4, "SL fits ATR", "SL ATR-adjusted")
    conf.add(rr >= float(cfg.min_rr) * 0.95, 8, f"RR ≥ 1:{cfg.min_rr:g}", "RR thin")
    confidence_pct, reasons = conf.finalize()
    grade = quality_grade(confidence_pct, rr, True, adjusted)
    take = confidence_pct >= float(cfg.take_confidence_threshold) and rr >= float(cfg.min_rr) * 0.9

    setup = pack_trade_setup(
        direction=direction,
        entry=entry,
        stop=stop,
        target=t1,
        confidence_pct=confidence_pct,
        confidence_reasons=reasons + [f"Factors: {', '.join(bits)}"],
        reason=f"{'BUY' if is_long else 'SELL'} score {score} · HTF {htf}",
        plain_english=(
            f"{'Buy' if is_long else 'Sell'} {ticker} on {cfg.entry_tf}: score {score}/10, "
            f"HTF {htf}, risk {sl_pct_v:.1f}% · aim {tp_pct_v:.1f}% (1:{rr:g})."
        ),
        timeframe=cfg.entry_tf,
        grade=grade,
        take_trade=take,
        stop_adjusted=adjusted,
    )
    # Attach multi-target extras
    setup["target2_price"] = _r(t2)
    setup["target3_price"] = _r(t3)

    plan = make_trade_plan(
        direction=direction,
        timeframe=cfg.entry_tf,
        stop_loss_pct=round(sl_pct_v or 0, 2),
        take_profit_pct=round(tp_pct_v or 0, 2),
        confidence_pct=confidence_pct,
        style="intraday" if cfg.entry_tf not in ("1d", "1w", "1wk") else "swing",
        exit_rule=(
            f"9EMA+Vol+RSI scalp: SL beyond structure ({_r(stop)}); "
            f"T1 1:{cfg.min_rr:g} ({_r(t1)}); T2 {_r(t2)}; T3 {_r(t3)}. "
            f"Invalidate on close back through 9 EMA. Factors: {', '.join(bits[:4])}."
        ),
        max_hold_exit=f"Typical scalp hold ({hold_for_tf(cfg.entry_tf)}); trail via 9 EMA after T1.",
    )

    out["chart_levels"] = [
        {"label": "Entry", "price": _r(entry), "color": "#38bdf8"},
        {"label": "SL", "price": _r(stop), "color": "#f43f5e"},
        {"label": "T1", "price": _r(t1), "color": "#34d399"},
        {"label": "T2", "price": _r(t2), "color": "#a78bfa"},
    ]

    out.update({
        "take_trade": take,
        "direction": direction,
        "signal": "BULLISH" if is_long else "BEARISH",
        "action": "BUY" if is_long else "SELL",
        "status": "take" if take else "setup_low_conf",
        "reason": setup["reason"],
        "entry_price": _r(entry),
        "stop_price": _r(stop),
        "target_price": _r(t1),
        "target2_price": _r(t2),
        "target3_price": _r(t3),
        "sl_pct": sl_pct_v,
        "tp_pct": tp_pct_v,
        "rr": rr,
        "confidence_pct": confidence_pct,
        "confidence_reasons": reasons,
        "grade": grade,
        "trade_plan": plan,
        "trade_setup": setup,
        "trade_suggestion": {
            "action": "BUY" if is_long else "SELL",
            "entry": _r(entry),
            "stop": _r(stop),
            "target": _r(t1),
            "target2": _r(t2),
            "target3": _r(t3),
            "sl_pct": sl_pct_v,
            "tp_pct": tp_pct_v,
            "confidence_pct": confidence_pct,
            "score": score,
        },
        "plain_english": setup["plain_english"],
        "pro_checklist": [
            f"HTF {cfg.trend_tf} bias agrees",
            f"≥{cfg.hold_bars} candles beyond 9 EMA",
            "Structure HH/HL or LH/LL",
            "Volume > SMA50 (+ rising preferred)",
            "RSI momentum (not chasing >70 longs)",
            "Trigger: break prior high/low",
            f"Min RR 1:{cfg.min_rr:g} · SL beyond swing",
        ],
    })
    return out


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: Ema9VolRsiMomentumConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    cfg = cfg or Ema9VolRsiMomentumConfig()
    results: list[dict[str, Any]] = []
    for t in tickers:
        try:
            results.append(
                analyze_ticker(t, market, cfg=cfg, groww_token=groww_token, exchange=exchange)
            )
        except Exception as exc:
            logger.exception("%s failed for %s", STRATEGY_NAME, t)
            results.append({
                "ticker": t,
                "timeframe": cfg.entry_tf,
                "strategy": STRATEGY_ID,
                "error": str(exc)[:240],
                "signal": "WAIT",
                "take_trade": False,
            })

    actionable = [r for r in results if r.get("take_trade")]
    return {
        "strategy": STRATEGY_ID,
        "strategy_label": STRATEGY_NAME,
        "how_it_works": HOW_IT_WORKS,
        "rules": RULES,
        "pro_tips": PRO_TIPS,
        "entry_tf": cfg.entry_tf,
        "trend_tf": cfg.trend_tf,
        "config": {
            "entry_tf": cfg.entry_tf,
            "trend_tf": cfg.trend_tf,
            "ema_period": cfg.ema_period,
            "vol_sma_period": cfg.vol_sma_period,
            "rsi_period": cfg.rsi_period,
            "hold_bars": cfg.hold_bars,
            "min_score": cfg.min_score,
            "min_rr": cfg.min_rr,
            "require_htf_align": cfg.require_htf_align,
            "side": cfg.side,
        },
        "results": results,
        "entry_count": len(actionable),
        "scanned": len(results),
        "ai_system_prompt": AI_SYSTEM,
        "disclaimer": (
            "Research / education only — not financial advice. "
            "Score ≥7 with structure SL and ≥1:2 RR on 5m, confirmed by 15m EMA bias."
        ),
    }


def build_ema9_vol_rsi_momentum_ai_prompt(result: dict[str, Any]) -> str:
    extra = [
        f"Direction: {result.get('direction')} · BUY score {result.get('buy_score')} · SELL score {result.get('sell_score')}",
        f"HTF: {(result.get('metrics') or {}).get('htf_bias')}",
        f"Conf {result.get('confidence_pct')}% · SL {result.get('sl_pct')}% · TP {result.get('tp_pct')}%",
        f"Reason: {result.get('reason')}",
        f"Checks: {result.get('checks')}",
    ]
    return build_pro_trade_ai_context(result, engine_label=STRATEGY_NAME, extra_lines=extra)
