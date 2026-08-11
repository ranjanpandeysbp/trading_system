"""
pro_trade_shared.py
---------------------
Shared confluence-scoring and risk-conversion helpers for the Pro Trade
engines (Volume Profile CE, Volume Profile POC, PA + Volume Profile,
PA-VP-SMC) — kept in one place so every "actionable trade" across Pro Trade
carries a real, multi-factor confidence_pct instead of a flat/binary signal,
plus consistent sl_pct/tp_pct/hold_duration fields matching the rest of the
app's engines.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=max(2, period // 2)).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-12)
    return 100 - (100 / (1 + rs))


def ema(close: pd.Series, period: int) -> pd.Series:
    return close.ewm(span=period, adjust=False).mean()


def volume_zscore(volume: pd.Series, window: int = 20) -> pd.Series:
    mean = volume.rolling(window, min_periods=max(3, window // 3)).mean()
    std = volume.rolling(window, min_periods=max(3, window // 3)).std()
    return (volume - mean) / std.replace(0, pd.NA)


def kaufman_efficiency_ratio(close: pd.Series, period: int = 14) -> pd.Series:
    """Kaufman's Efficiency Ratio: net directional move over `period` bars
    divided by the sum of every bar-to-bar move in between (0-1). Near 1 means
    price took a clean, direct path (a genuine trend); near 0 means it
    covered a lot of ground but ended up nowhere (chop) — the piece "trend
    strength" is usually missing when that's judged from ADX alone, since ADX
    can stay elevated for a while after a trend has already turned choppy."""
    net_move = (close - close.shift(period)).abs()
    path_length = close.diff().abs().rolling(period).sum()
    return (net_move / path_length.replace(0, pd.NA)).clip(0, 1)


class ConfidenceScore:
    """Accumulates a confluence-weighted confidence score (10-95 clamp) and
    the human-readable reasons behind it — every point added is explained,
    so the final score is auditable, not a black box."""

    def __init__(self, base: float, base_reason: str):
        self.score = base
        self.reasons: list[str] = [base_reason]

    def add(self, condition: bool, points: float, reason_true: str, reason_false: str | None = None) -> "ConfidenceScore":
        if condition:
            self.score += points
            self.reasons.append(f"+{points:.0f}: {reason_true}")
        elif reason_false:
            self.reasons.append(reason_false)
        return self

    def finalize(self, lo: float = 10.0, hi: float = 92.0) -> tuple[float, list[str]]:
        return round(max(lo, min(hi, self.score)), 1), self.reasons


def sl_tp_pct(direction: str, entry: float, stop_loss: float | None, target: float | None) -> tuple[float | None, float | None]:
    """Convert absolute stop/target prices to %-of-entry, direction-aware
    (a SHORT's stop is above entry, target below — sl_pct/tp_pct are always
    reported as positive magnitudes regardless of direction)."""
    if not entry:
        return None, None
    sl_pct = round(abs(entry - stop_loss) / entry * 100, 3) if stop_loss is not None else None
    tp_pct = round(abs(target - entry) / entry * 100, 3) if target is not None else None
    return sl_pct, tp_pct


def rr_ratio(sl_pct: float | None, tp_pct: float | None) -> float | None:
    if not sl_pct or not tp_pct or sl_pct <= 0:
        return None
    return round(tp_pct / sl_pct, 2)


# ---------------------------------------------------------------------------
# Trading-judgment layer — sits between raw confluence math and a final
# suggestion. A vote count alone will happily pass a setup a real desk would
# reject (stop that doesn't match real volatility, poor reward-for-risk, an
# already-extended move, an illiquid name). These helpers apply that
# discipline explicitly and auditably rather than leaving it implicit.
# ---------------------------------------------------------------------------

def atr_sane_stop_target(
    direction: str,
    entry: float,
    stop_loss: float | None,
    target: float | None,
    atr_value: float | None,
    *,
    min_atr_mult: float = 0.5,
    max_atr_mult: float = 4.0,
    default_rr: float = 2.0,
) -> tuple[float | None, float | None, bool]:
    """Sanity-check a proposed stop against the instrument's real volatility.
    A stop tighter than `min_atr_mult`x ATR gets stopped out on noise; wider
    than `max_atr_mult`x ATR isn't a real risk-managed stop. When outside that
    band, both stop and target are re-derived from ATR (preserving the
    original reward:risk ratio where a target was given) instead of blindly
    trusting the engine's raw numbers. Returns (stop, target, was_adjusted)."""
    if not entry or not atr_value or atr_value <= 0 or stop_loss is None:
        return stop_loss, target, False

    dist = abs(entry - stop_loss)
    lo, hi = min_atr_mult * atr_value, max_atr_mult * atr_value
    if lo <= dist <= hi:
        return stop_loss, target, False

    safe_dist = lo if dist < lo else hi
    is_long = direction == "LONG"
    new_stop = entry - safe_dist if is_long else entry + safe_dist

    orig_rr = (abs(target - entry) / dist) if (target is not None and dist) else default_rr
    new_target_dist = safe_dist * orig_rr
    new_target = entry + new_target_dist if is_long else entry - new_target_dist

    return round(new_stop, 4), round(new_target, 4), True


def meets_rr_floor(sl_pct: float | None, tp_pct: float | None, min_rr: float) -> bool:
    """Institutional desks rarely take a setup below ~1.2-2x reward-for-risk
    depending on style — below the floor, direction may be right but the
    trade itself isn't, so it gets downgraded to WAIT rather than acted on."""
    rr = rr_ratio(sl_pct, tp_pct)
    return rr is not None and rr >= min_rr


def momentum_exhaustion_note(rsi_value: float | None, direction: str) -> tuple[float, str | None]:
    """Confidence penalty + plain note when RSI shows the move is already
    extended in the trade's own direction — not a hard block (the setup may
    still be valid), just an honest chase-risk flag a discretionary trader
    would raise before entering fresh."""
    if rsi_value is None:
        return 0.0, None
    if direction == "LONG" and rsi_value >= 75:
        return -8.0, "RSI already overbought — this move is extended; entering fresh here carries chase risk."
    if direction == "SHORT" and rsi_value <= 25:
        return -8.0, "RSI already oversold — this move is extended; entering fresh here carries chase risk."
    return 0.0, None


def liquidity_ok(volume_zscore_value: float | None, *, min_z: float = -1.5) -> bool:
    """Volume z-score floor for fast-timeframe (scalping/intraday) buckets —
    abnormally thin volume vs. this ticker's own recent history is a slippage
    trap a live trader would skip regardless of what the indicators say.
    Unknown volume data doesn't block (can't judge what we can't measure)."""
    if volume_zscore_value is None:
        return True
    return volume_zscore_value >= min_z


def quality_grade(confidence_pct: float, rr: float | None, liquidity_is_ok: bool, stop_was_adjusted: bool) -> str:
    """A/B/C synthesis of confidence + reward:risk + liquidity + volatility
    fit — a trader's real judgment call is never just the confidence number
    in isolation, and this is the concrete, auditable form of that call."""
    score = 0
    score += 2 if confidence_pct >= 70 else (1 if confidence_pct >= 55 else 0)
    score += 2 if (rr or 0) >= 2.0 else (1 if (rr or 0) >= 1.5 else 0)
    score += 1 if liquidity_is_ok else 0
    score += 1 if not stop_was_adjusted else 0
    if score >= 5:
        return "A"
    if score >= 3:
        return "B"
    return "C"


def pack_trade_setup(
    *,
    direction: str,
    entry: float | None,
    stop: float | None,
    target: float | None,
    confidence_pct: float,
    confidence_reasons: list[str] | None = None,
    grade: str | None = None,
    take_trade: bool | None = None,
    reason: str | None = None,
    plain_english: str | None = None,
    timeframe: str | None = None,
    stop_adjusted: bool = False,
) -> dict[str, Any]:
    """Canonical trade-setup payload: % confidence, %SL, %TP (+ levels)."""
    dir_key = (direction or "WAIT").upper()
    if dir_key in ("BUY", "BULLISH"):
        dir_key = "LONG"
    elif dir_key in ("SELL", "BEARISH"):
        dir_key = "SHORT"
    elif dir_key not in ("LONG", "SHORT"):
        dir_key = "WAIT"

    sl_pct, tp_pct = (None, None)
    if entry and dir_key in ("LONG", "SHORT"):
        sl_pct, tp_pct = sl_tp_pct(dir_key, float(entry), stop, target)
    rr = rr_ratio(sl_pct, tp_pct)
    conf = round(float(confidence_pct or 0), 1)
    if grade is None:
        grade = quality_grade(conf, rr, True, stop_adjusted) if dir_key != "WAIT" else "C"
    if take_trade is None:
        take_trade = dir_key in ("LONG", "SHORT") and conf >= 55 and meets_rr_floor(sl_pct, tp_pct, 1.2)

    action = "BUY" if dir_key == "LONG" else ("SELL" if dir_key == "SHORT" else "WAIT")
    signal = "BULLISH" if dir_key == "LONG" else ("BEARISH" if dir_key == "SHORT" else "NEUTRAL")

    def _r(v: float | None, d: int = 4) -> float | None:
        if v is None:
            return None
        try:
            f = float(v)
            return round(f, d) if f == f else None
        except (TypeError, ValueError):
            return None

    return {
        "direction": dir_key,
        "action": action,
        "signal": signal,
        "entry_price": _r(entry),
        "stop_price": _r(stop),
        "target_price": _r(target),
        "sl_pct": round(sl_pct, 2) if sl_pct is not None else None,
        "tp_pct": round(tp_pct, 2) if tp_pct is not None else None,
        "rr": rr,
        "confidence_pct": conf,
        "confidence_reasons": list(confidence_reasons or []),
        "grade": grade,
        "take_trade": bool(take_trade),
        "reason": reason,
        "plain_english": plain_english,
        "timeframe": timeframe,
    }


def build_bias_sr_trade_setup(
    df: pd.DataFrame,
    *,
    biases: list[str],
    support: float | None = None,
    resistance: float | None = None,
    timeframe: str = "1d",
    base_reason: str = "Indicator tilt + S/R levels",
) -> dict[str, Any]:
    """Build a trade setup from bullish/bearish bias votes + nearest S/R + ATR."""
    if df is None or df.empty or "close" not in df.columns:
        return pack_trade_setup(
            direction="WAIT",
            entry=None,
            stop=None,
            target=None,
            confidence_pct=10.0,
            reason="Insufficient price data",
            plain_english="No trade setup — insufficient bars.",
            timeframe=timeframe,
        )

    entry = float(df["close"].iloc[-1])
    atr_s = atr(df)
    atr_v = float(atr_s.iloc[-1]) if len(atr_s) and pd.notna(atr_s.iloc[-1]) else None

    bull = sum(1 for b in biases if str(b).lower() == "bullish")
    bear = sum(1 for b in biases if str(b).lower() == "bearish")
    voted = bull + bear

    if bull > bear:
        direction = "LONG"
    elif bear > bull:
        direction = "SHORT"
    elif support and resistance and entry:
        mid = (float(support) + float(resistance)) / 2.0
        direction = "LONG" if entry <= mid else "SHORT"
    else:
        direction = "WAIT"

    if direction == "WAIT" or not entry:
        return pack_trade_setup(
            direction="WAIT",
            entry=entry,
            stop=None,
            target=None,
            confidence_pct=25.0,
            confidence_reasons=["Mixed / neutral indicator tilt — no clear side"],
            reason="WAIT: no clear directional tilt",
            plain_english="Indicators are mixed — wait for a clearer lean before risking capital.",
            timeframe=timeframe,
        )

    is_long = direction == "LONG"
    if is_long:
        stop = float(support) if support and support < entry else None
        target = float(resistance) if resistance and resistance > entry else None
        if stop is None and atr_v:
            stop = entry - 1.2 * atr_v
        if target is None and stop is not None:
            target = entry + 2.0 * abs(entry - stop)
    else:
        stop = float(resistance) if resistance and resistance > entry else None
        target = float(support) if support and support < entry else None
        if stop is None and atr_v:
            stop = entry + 1.2 * atr_v
        if target is None and stop is not None:
            target = entry - 2.0 * abs(stop - entry)

    stop, target, adjusted = atr_sane_stop_target(
        direction, entry, stop, target, atr_v, default_rr=2.0
    )

    score = ConfidenceScore(38.0, base_reason)
    score.add(voted >= 1, 10, f"{bull} bull / {bear} bear among selected indicators", "No directional indicator votes")
    score.add(abs(bull - bear) >= 2, 12, "Clear majority tilt", "Tilt is thin (1-vote edge)")
    score.add(bool(support and resistance), 10, "S1/R1 levels available for SL/TP", "Missing S/R — ATR used")
    score.add(atr_v is not None and atr_v > 0, 6, "ATR available for stop sanity", "No ATR")
    score.add(not adjusted, 4, "Stop fits ATR band", "Stop widened/narrowed to ATR band")
    if is_long:
        score.add(support is not None and support < entry, 8, "Support below entry for long SL", "No support under entry")
        score.add(resistance is not None and resistance > entry, 6, "Resistance above for long TP", "No resistance overhead")
    else:
        score.add(resistance is not None and resistance > entry, 8, "Resistance above entry for short SL", "No resistance over entry")
        score.add(support is not None and support < entry, 6, "Support below for short TP", "No support underneath")

    conf, reasons = score.finalize()
    setup = pack_trade_setup(
        direction=direction,
        entry=entry,
        stop=stop,
        target=target,
        confidence_pct=conf,
        confidence_reasons=reasons,
        stop_adjusted=adjusted,
        timeframe=timeframe,
    )
    setup["reason"] = (
        f"{setup['action']}: {base_reason} · conf {conf:.0f}% · "
        f"SL {setup.get('sl_pct') or 0:.1f}% · TP {setup.get('tp_pct') or 0:.1f}%"
    )
    setup["plain_english"] = (
        f"{'Buy' if is_long else 'Sell'} setup: selected indicators lean "
        f"{'bullish' if is_long else 'bearish'} ({bull}↑ / {bear}↓). "
        f"Risk {setup.get('sl_pct') or 0:.1f}% to stop · aim {setup.get('tp_pct') or 0:.1f}% to target "
        f"· confidence {conf:.0f}% (grade {setup.get('grade')})."
    )
    return setup


def enrich_forecast_trade_setup(
    forecast: dict[str, Any] | None,
    *,
    entry: float | None,
    atr_value: float | None = None,
    timeframe: str = "1d",
) -> dict[str, Any] | None:
    """Attach %SL / %TP to a Falling Knife (or similar) forecast that already has confidence %."""
    if not forecast or not isinstance(forecast, dict):
        return forecast
    direction_raw = str(forecast.get("direction") or "").lower()
    # Historical fall forecast → short bias into the dump; rise → long into the pump.
    direction = "SHORT" if direction_raw == "fall" else ("LONG" if direction_raw == "rise" else "WAIT")
    conf = float(forecast.get("confidence_pct") or 40.0)
    move = forecast.get("predicted_magnitude_pct") or forecast.get("predicted_move_pct")
    try:
        move_abs = abs(float(move)) if move is not None else None
    except (TypeError, ValueError):
        move_abs = None

    if direction == "WAIT" or not entry:
        forecast["trade_setup"] = pack_trade_setup(
            direction="WAIT",
            entry=entry,
            stop=None,
            target=None,
            confidence_pct=conf,
            reason="No actionable side from forecast",
            timeframe=timeframe,
        )
        return forecast

    # Risk ~0.4× typical move (or 1.2× ATR); reward = typical move magnitude.
    if atr_value and atr_value > 0 and entry:
        sl_dist = 1.2 * atr_value
    elif move_abs and entry:
        sl_dist = entry * (max(0.4, move_abs * 0.4) / 100.0)
    else:
        sl_dist = entry * 0.015 if entry else None

    if move_abs and entry:
        tp_dist = entry * (move_abs / 100.0)
    elif sl_dist:
        tp_dist = sl_dist * 2.0
    else:
        tp_dist = None

    if direction == "LONG":
        stop = entry - sl_dist if sl_dist else None
        target = entry + tp_dist if tp_dist else None
    else:
        stop = entry + sl_dist if sl_dist else None
        target = entry - tp_dist if tp_dist else None

    stop, target, adjusted = atr_sane_stop_target(
        direction, float(entry), stop, target, atr_value, default_rr=2.0
    )
    setup = pack_trade_setup(
        direction=direction,
        entry=float(entry),
        stop=stop,
        target=target,
        confidence_pct=conf,
        confidence_reasons=[
            f"Forecast {direction_raw} · samples {forecast.get('samples')}",
            f"Typical move {move_abs:.1f}%" if move_abs else "Move size unknown",
        ],
        stop_adjusted=adjusted,
        timeframe=timeframe,
        reason=(
            f"{'SELL' if direction == 'SHORT' else 'BUY'} into next {direction_raw}: "
            f"conf {conf:.0f}%"
        ),
        plain_english=str(forecast.get("plain_english") or ""),
    )
    forecast["trade_setup"] = setup
    forecast["sl_pct"] = setup.get("sl_pct")
    forecast["tp_pct"] = setup.get("tp_pct")
    forecast["rr"] = setup.get("rr")
    forecast["action"] = setup.get("action")
    forecast["entry_price"] = setup.get("entry_price")
    forecast["stop_price"] = setup.get("stop_price")
    forecast["target_price"] = setup.get("target_price")
    return forecast


# ---------------------------------------------------------------------------
# Per-ticker "Ask AI" prompt — shared context builder + system prompt used by
# every Pro Trade submenu's per-result "Ask AI" panel. Two output shapes exist
# across the engines: some report one flat verdict on `result` itself
# (direction/confidence_pct/entry_price/...), others (Volume Profile CE/POC,
# PA-Volume Profile) report a list of independent `setups`, each carrying its
# own signal/direction/confidence — this builder handles both without
# fabricating any field the engine didn't actually produce.
# ---------------------------------------------------------------------------

def pro_trade_ai_system(engine_label: str, methodology: str) -> str:
    """Shared system-prompt template for a Pro Trade engine's per-ticker Ask AI."""
    return (
        f"You are analyzing one ticker's result from the '{engine_label}' Pro Trade scan.\n\n"
        f"Methodology: {methodology}\n\n"
        "Given this data:\n"
        "1. **Read the setup** — state plainly what the data shows (direction, key levels, why they matter).\n"
        "2. **Confidence & quality** — comment on the confidence%/grade and reward:risk if present, and what "
        "would make this setup stronger or weaker.\n"
        "3. **Risk framing** — explain the stop-loss/target in plain terms (what % is being risked to make what %).\n"
        "4. **Verdict** — BUY / SELL / WAIT right now, with the single strongest supporting and opposing factor.\n\n"
        "Cite only figures present in the data — never invent a price, level, or percentage. "
        "This is research/education only, not financial advice."
    )


def _fmt(v: Any, digits: int = 2) -> str:
    if v is None:
        return "—"
    if isinstance(v, (int, float)):
        return f"{v:,.{digits}f}"
    return str(v)


def build_pro_trade_ai_context(
    result: dict[str, Any],
    *,
    engine_label: str,
    extra_lines: list[str] | None = None,
) -> str:
    """Curated (not raw-JSON) per-ticker prompt context, reused by every Pro
    Trade engine's build_X_ai_prompt() wrapper."""
    ticker = result.get("ticker")
    if result.get("error"):
        return f"=== {engine_label.upper()} ===\nTicker: {ticker}\nError: {result['error']}"

    lines = [
        f"=== {engine_label.upper()} ===",
        f"Ticker: {ticker}",
    ]
    if result.get("timeframe"):
        lines.append(f"Timeframe: {result.get('timeframe')}")
    if result.get("ltp") is not None:
        lines.append(f"LTP: {_fmt(result.get('ltp'), 4)}")

    setups = result.get("setups")
    actionable = result.get("actionable")
    if isinstance(setups, list) and setups:
        lines += ["", "-- Setups checked --"]
        for s in setups:
            name = s.get("setup", "setup")
            sig = s.get("signal", "—")
            direction = s.get("direction")
            logic = s.get("logic") or s.get("reason") or ""
            line = f"- {name}: {sig}" + (f" ({direction})" if direction else "") + (f" — {logic}" if logic else "")
            lines.append(line)
            if s.get("entry") is not None or s.get("confidence_pct") is not None:
                lines.append(
                    f"  entry={_fmt(s.get('entry'), 4)} stop={_fmt(s.get('stop_loss'), 4)} "
                    f"target={_fmt(s.get('target'), 4)} confidence={_fmt(s.get('confidence_pct'), 0)}%"
                )
        if isinstance(actionable, list):
            lines.append(f"Actionable setups: {len(actionable)} of {len(setups)}")
    else:
        signal = result.get("signal") or result.get("direction") or result.get("verdict") or "—"
        lines.append(f"Signal / direction: {signal}")
        if result.get("confidence_pct") is not None:
            grade = f" (Grade {result['grade']})" if result.get("grade") else ""
            lines.append(f"Confidence: {_fmt(result.get('confidence_pct'), 0)}%{grade}")
        if result.get("take_trade"):
            lines += [
                f"Entry: {_fmt(result.get('entry_price'), 4)}",
                f"Stop-loss: {_fmt(result.get('stop_price'), 4)} "
                f"({_fmt(result.get('sl_pct'), 1)}% risk)",
                f"Target: {_fmt(result.get('target_price'), 4)} "
                f"({_fmt(result.get('tp_pct'), 1)}% reward)",
            ]
            if result.get("rr") is not None:
                lines.append(f"Reward:Risk: 1:{_fmt(result.get('rr'), 2)}")

    session_vp = result.get("session_vp")
    if isinstance(session_vp, dict) and session_vp:
        lines += [
            "",
            "-- Session volume profile --",
            f"POC: {_fmt(session_vp.get('poc'), 4)} · VAH: {_fmt(session_vp.get('vah'), 4)} "
            f"· VAL: {_fmt(session_vp.get('val'), 4)}",
        ]

    if result.get("support_zone") or result.get("resistance_zone"):
        lines += [
            "",
            f"Support zone: {result.get('support_zone') or '—'}",
            f"Resistance zone: {result.get('resistance_zone') or '—'}",
        ]

    if result.get("plain_english"):
        lines += ["", "-- Narrative --", str(result["plain_english"])]

    reasons = result.get("confidence_reasons") or []
    if reasons:
        lines += ["", "-- Confidence reasons --"] + [f"- {r}" for r in reasons]

    if extra_lines:
        lines += ["", "-- Setup detail --"] + extra_lines

    return "\n".join(lines)
