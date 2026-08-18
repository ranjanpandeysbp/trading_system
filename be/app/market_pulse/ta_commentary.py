"""
ta_commentary.py
----------------
Shared plain-English technical commentary for Pro Trade (and other scan desks).

Goal: every result should explain what is on the chart — structure, levels,
momentum, extremes — not a cryptic one-liner like "EMA not stacked".
"""

from __future__ import annotations

from typing import Any


def _fmt_px(x: Any, n: int = 2) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if v != v:  # NaN
        return "—"
    return f"{v:,.{n}f}" if abs(v) >= 1 else f"{v:.{max(n, 4)}g}"


def _f(x: Any) -> float | None:
    try:
        v = float(x)
        return None if v != v else v
    except (TypeError, ValueError):
        return None


def looks_optimized(text: str | None) -> bool:
    """True when commentary already reads like a full TA picture."""
    t = (text or "").strip()
    if len(t) < 180:
        return False
    markers = (
        "technical picture",
        "technical bias",
        "why not take",
        "trade map",
        "net read",
        "bullish stack",
        "bearish stack",
        "golden cross",
        "death cross",
        "nearby **support**",
        "bollinger",
    )
    low = t.lower()
    if "\n\n" in t and any(m in low for m in markers):
        return True
    hits = sum(1 for m in markers if m in low)
    return hits >= 2 and len(t) >= 280


def rsi_plain(rsi_v: float | None) -> str:
    if rsi_v is None:
        return "RSI is not ready on this bar."
    if rsi_v >= 78:
        return f"RSI at {rsi_v:.1f} is overbought — momentum is stretched; fresh longs are risky here."
    if rsi_v >= 65:
        return (
            f"RSI at {rsi_v:.1f} sits in a strong-bull zone — upside is active, "
            "but chase risk rises near the top of the band."
        )
    if rsi_v >= 55:
        return f"RSI at {rsi_v:.1f} is mildly bullish — buyers still have the edge without extreme stretch."
    if rsi_v >= 45:
        return f"RSI at {rsi_v:.1f} is neutral / mid-range — no strong momentum impulse from RSI alone."
    if rsi_v >= 35:
        return f"RSI at {rsi_v:.1f} is mildly bearish — sellers have a soft edge."
    if rsi_v >= 22:
        return (
            f"RSI at {rsi_v:.1f} sits in a weak/oversold-leaning zone — shorts need care; "
            "longs need a real reclaim."
        )
    return f"RSI at {rsi_v:.1f} is deeply oversold — downside is stretched; fresh shorts are risky here."


def sr_plain(price: float, support: float | None, resist: float | None) -> str | None:
    if support is None or resist is None or price <= 0:
        return None
    span = max(resist - support, 1e-9)
    pos = (price - support) / span
    if price >= resist * 0.995:
        loc = "pressing / testing **resistance**"
    elif price <= support * 1.005:
        loc = "pressing / testing **support**"
    elif pos >= 0.66:
        loc = "in the **upper third** of the recent swing range (closer to resistance)"
    elif pos <= 0.34:
        loc = "in the **lower third** of the recent swing range (closer to support)"
    else:
        loc = "around the **middle** of the recent swing range"
    room_up = max(resist - price, 0.0)
    room_down = max(price - support, 0.0)
    return (
        f"On the chart, price {_fmt_px(price)} is {loc}. "
        f"Nearby **support** {_fmt_px(support)} · **resistance** {_fmt_px(resist)} "
        f"(~{_fmt_px(room_up)} room up / ~{_fmt_px(room_down)} room down)."
    )


def bb_vwap_plain(
    *,
    price: float,
    pct_b: float | None = None,
    bb_u: float | None = None,
    bb_m: float | None = None,
    bb_l: float | None = None,
    vwap: float | None = None,
    at_upper: bool | None = None,
    at_lower: bool | None = None,
) -> str | None:
    if pct_b is None and bb_u is None and bb_l is None and vwap is None:
        return None
    parts: list[str] = []
    if at_upper is None and pct_b is not None:
        at_upper = pct_b >= 0.85
    if at_lower is None and pct_b is not None:
        at_lower = pct_b <= 0.15

    if at_upper:
        parts.append(
            f"Price is hugging the **upper Bollinger**"
            + (f" ({_fmt_px(bb_u)})" if bb_u is not None else "")
            + " — a stretch / extension zone. Mean-reversion shorts become more interesting; "
            "trend longs need strong confirmation."
        )
    elif at_lower:
        parts.append(
            f"Price is hugging the **lower Bollinger**"
            + (f" ({_fmt_px(bb_l)})" if bb_l is not None else "")
            + " — a washout / discount zone. Mean-reversion longs become more interesting; "
            "trend shorts need strong confirmation."
        )
    elif pct_b is not None:
        if 0.35 <= pct_b <= 0.65:
            parts.append(
                f"Price is near the **middle Bollinger**"
                + (f" ({_fmt_px(bb_m)})" if bb_m is not None else "")
                + " — range mid, not an extreme."
            )
        elif pct_b > 0.65:
            parts.append(f"Price is in the upper half of the Bollinger envelope (%B {pct_b:.2f}).")
        else:
            parts.append(f"Price is in the lower half of the Bollinger envelope (%B {pct_b:.2f}).")

    if vwap is not None and price > 0:
        vs = "above" if price >= vwap else "below"
        bias = (
            "institutional / session flow still supports buyers."
            if price >= vwap
            else "institutional / session flow still presses sellers."
        )
        parts.append(f"Session **VWAP** is {_fmt_px(vwap)} and price is **{vs}** it — {bias}")

    return " ".join(parts) if parts else None


def _signal_bias_plain(signal: str, direction: str, event: str | None, phase: str | None) -> str:
    sig = (signal or "").upper()
    d = (direction or "").upper()
    ev = (event or phase or "").replace("_", " ").strip()
    if sig in ("BULLISH",) or d in ("LONG", "BUY"):
        core = "Technical bias: **bullish / LONG-leaning**."
    elif sig in ("BEARISH",) or d in ("SHORT", "SELL"):
        core = "Technical bias: **bearish / SHORT-leaning**."
    elif sig in ("WATCH",):
        core = "Technical bias: **WATCH** — structure is forming, but not a full TAKE yet."
    elif sig in ("WAIT", "NONE", "NEUTRAL", ""):
        core = "Technical bias: **neutral / wait** — no clear actionable side on this bar."
    else:
        core = f"Technical bias: **{sig or d or 'unclear'}**."
    if ev:
        core += f" Active label on the tape: **{ev}**."
    return core


def _checks_plain(checks: list[Any]) -> str | None:
    if not isinstance(checks, list) or not checks:
        return None
    passed = [c for c in checks if isinstance(c, dict) and c.get("passed")]
    failed = [c for c in checks if isinstance(c, dict) and not c.get("passed")]
    bits: list[str] = []
    if passed:
        names = ", ".join(str(c.get("label") or c.get("id") or "check") for c in passed[:4])
        bits.append(f"Passing filters: {names}.")
    if failed:
        names = ", ".join(str(c.get("label") or c.get("id") or "check") for c in failed[:4])
        bits.append(f"Still open / failing: {names}.")
    return " ".join(bits) if bits else None


def _trade_map_plain(r: dict[str, Any]) -> str | None:
    setup = r.get("trade_setup") if isinstance(r.get("trade_setup"), dict) else {}
    action = str(setup.get("action") or r.get("action") or "").upper()
    take = bool(setup.get("take_trade") if "take_trade" in setup else r.get("take_trade"))
    stop = setup.get("stop_price", r.get("stop_price"))
    target = setup.get("target_price", r.get("target_price"))
    sl = _f(setup.get("sl_pct", r.get("sl_pct")))
    tp = _f(setup.get("tp_pct", r.get("tp_pct")))
    conf = _f(setup.get("confidence_pct", r.get("confidence_pct")))
    grade = setup.get("grade") or r.get("grade")
    if take and action in ("BUY", "SELL") and (stop is not None or target is not None):
        return (
            f"**Trade map:** {action} idea"
            + (f" with stop {_fmt_px(stop)}" if stop is not None else "")
            + (f" ({sl:.1f}% risk)" if sl is not None else "")
            + (f" and first target {_fmt_px(target)}" if target is not None else "")
            + (f" ({tp:.1f}% reward)" if tp is not None else "")
            + (
                f". Confidence {conf:.0f}%"
                + (f" · grade {grade}" if grade else "")
                + "."
                if conf is not None
                else "."
            )
        )
    if action in ("BUY", "SELL") or str(r.get("direction") or "").upper() in ("LONG", "SHORT"):
        side = action or str(r.get("direction"))
        return (
            f"Net read: structure leans **{side}**, but filters have not cleared a full TAKE — "
            "use this as a watchlist bias, not a forced entry."
        )
    return "Net read: wait for a clearer closed-bar trigger before committing risk."


def compose_from_scan_result(result: dict[str, Any]) -> str:
    """Build a multi-paragraph TA commentary from whatever fields a scan row exposes."""
    if not isinstance(result, dict):
        return ""
    if result.get("error"):
        return f"**{result.get('ticker') or 'Ticker'}**: {result.get('error')}"

    existing = str(result.get("commentary") or result.get("plain_english") or "").strip()
    if looks_optimized(existing):
        return existing

    ticker = str(result.get("ticker_name") or result.get("ticker") or "Ticker")
    tf = str(result.get("timeframe") or result.get("execution_tf") or "—")
    strategy = str(result.get("strategy_label") or result.get("strategy") or "Setup")
    signal = str(result.get("signal") or "")
    direction = str(result.get("direction") or "")
    event = result.get("event") or result.get("phase")
    metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
    live = result.get("live") if isinstance(result.get("live"), dict) else {}

    price = _f(result.get("ltp") or result.get("entry_price") or metrics.get("price") or live.get("entry_price"))
    support = _f(metrics.get("support") or result.get("support") or live.get("support"))
    resist = _f(metrics.get("resistance") or result.get("resistance") or live.get("resistance"))
    rsi_v = _f(metrics.get("rsi") or result.get("rsi") or live.get("rsi"))
    pct_b = _f(metrics.get("pct_b") or result.get("pct_b"))
    bb_u = _f(metrics.get("bb_upper") or result.get("bb_upper"))
    bb_m = _f(metrics.get("bb_mid") or result.get("bb_mid"))
    bb_l = _f(metrics.get("bb_lower") or result.get("bb_lower"))
    vwap = _f(metrics.get("vwap") or result.get("vwap") or live.get("vwap"))
    at_upper = bool(metrics.get("at_upper_bb")) if "at_upper_bb" in metrics else None
    at_lower = bool(metrics.get("at_lower_bb")) if "at_lower_bb" in metrics else None

    parts: list[str] = [f"**{ticker}** · {tf} technical picture ({strategy})"]

    # Prefer keeping a short engine reason as context, then expand around it.
    reason = str(result.get("reason") or "").strip()
    if reason and reason.lower() not in existing.lower() and len(reason) < 220:
        parts.append(f"Engine note: {reason}")
    elif existing and len(existing) < 220:
        parts.append(f"Engine note: {existing}")

    parts.append(_signal_bias_plain(signal, direction, str(event) if event else None, str(result.get("phase") or "") or None))

    if price is not None:
        ema_bits = []
        for key, label in (
            ("ema_fast", "fast EMA"),
            ("ema_slow", "slow EMA"),
            ("ema9", "EMA9"),
            ("ema21", "EMA21"),
            ("ema50", "EMA50"),
            ("trail_ema", "trail EMA"),
        ):
            v = _f(metrics.get(key) or result.get(key))
            if v is not None:
                side = "above" if price >= v else "below"
                ema_bits.append(f"**{side}** {label} ({_fmt_px(v)})")
        if ema_bits:
            parts.append(f"Last close {_fmt_px(price)} is " + ", ".join(ema_bits[:3]) + ".")
        elif price is not None:
            parts.append(f"Last close is {_fmt_px(price)}.")

    sr = sr_plain(price, support, resist) if price is not None else None
    if sr:
        parts.append(sr)

    if rsi_v is not None:
        parts.append(rsi_plain(rsi_v))

    bb = bb_vwap_plain(
        price=price or 0.0,
        pct_b=pct_b,
        bb_u=bb_u,
        bb_m=bb_m,
        bb_l=bb_l,
        vwap=vwap,
        at_upper=at_upper,
        at_lower=at_lower,
    )
    if bb:
        parts.append(bb)

    checks = result.get("checks") or live.get("reasons")
    if isinstance(checks, list):
        # live.reasons is often list[str]
        if checks and isinstance(checks[0], str):
            parts.append("Key readings: " + " ".join(str(x) for x in checks[:4]))
        else:
            ch = _checks_plain(checks)
            if ch:
                parts.append(ch)

    # Volume / score style extras when present
    if metrics.get("vol_vs_ma") is not None:
        try:
            vv = float(metrics["vol_vs_ma"])
            parts.append(
                f"Volume is **{vv:.2f}×** its recent average — "
                + ("participation confirms the move." if vv >= 1.0 else "participation is soft.")
            )
        except (TypeError, ValueError):
            pass
    if result.get("phase") and not event:
        parts.append(f"Sequence / phase on the tape: **{str(result.get('phase')).replace('_', ' ')}**.")

    tm = _trade_map_plain(result)
    if tm:
        parts.append(tm)

    return "\n\n".join(parts)


def _flatten_for_compose(result: dict[str, Any]) -> dict[str, Any]:
    """Merge nested `live` fields so hub rows compose as well as Pro Trade rows."""
    live = result.get("live") if isinstance(result.get("live"), dict) else {}
    if not live:
        return result
    merged = dict(result)
    for key in (
        "signal",
        "direction",
        "action",
        "reason",
        "reasons",
        "phase",
        "event",
        "rsi",
        "support",
        "resistance",
        "vwap",
        "entry_price",
        "stop_price",
        "target_price",
        "sl_pct",
        "tp_pct",
        "confidence_pct",
        "grade",
        "take_trade",
        "checks",
        "metrics",
        "trade_setup",
        "commentary",
        "plain_english",
    ):
        if merged.get(key) is None and live.get(key) is not None:
            merged[key] = live[key]
    if not merged.get("metrics") and isinstance(live.get("metrics"), dict):
        merged["metrics"] = live["metrics"]
    # Hub reasons are often list[str] — expose as checks-style for compose
    if not merged.get("checks") and isinstance(live.get("reasons"), list):
        merged["checks"] = live["reasons"]
    return merged


def optimize_result_commentary(result: dict[str, Any]) -> dict[str, Any]:
    """Mutate one scan row so commentary / plain_english are a full TA picture."""
    if not isinstance(result, dict) or result.get("error"):
        return result
    text = compose_from_scan_result(_flatten_for_compose(result))
    if not text:
        return result
    result["commentary"] = text
    result["plain_english"] = text
    setup = result.get("trade_setup")
    if isinstance(setup, dict):
        pe = str(setup.get("plain_english") or "")
        # Preserve AI-refined notes; only fill thin engine text
        if not setup.get("ai_refined") and not looks_optimized(pe):
            setup["plain_english"] = text
        result["trade_setup"] = setup
    live = result.get("live")
    if isinstance(live, dict):
        if not looks_optimized(str(live.get("commentary") or live.get("plain_english") or "")):
            live["commentary"] = text
            live["plain_english"] = text
        result["live"] = live
    return result


def optimize_payload_commentary(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Walk a scan payload and optimize commentary on every result / entry row."""
    if not isinstance(payload, dict):
        return payload
    for key in ("results", "entries", "rows", "signals"):
        rows = payload.get(key)
        if isinstance(rows, list):
            payload[key] = [
                optimize_result_commentary(r) if isinstance(r, dict) else r
                for r in rows
            ]
    # Some desks nest under data.results
    data = payload.get("data")
    if isinstance(data, dict):
        optimize_payload_commentary(data)
    return payload
