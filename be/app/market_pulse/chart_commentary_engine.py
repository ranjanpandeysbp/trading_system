"""
chart_commentary_engine.py
--------------------------
Snapshot commentary for any OHLC chart: what is happening now, what may
happen next, and an optional trade setup (Conf % / SL % / TP %).

Reads the bars *as supplied by the client* (manual refresh), plus optional
indicator toggles, S/R levels, and user drawings (trend / hline / fib).

Rule path: Python TA (SMC FVG/OB/liquidity, candlesticks, RSI, EMA, BB, volume).
AI path: same snapshot polished by the configured LLM (falls back to rules).

Research / education only — not financial advice.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import pandas as pd

from app.market_pulse.indicators import add_bollinger_bands, add_ema, add_rsi, add_vol_sma
from app.market_pulse.pa_vp_smc_engine import (
    PaVpSmcConfig,
    classify_trend,
    detect_liquidity_sweep,
    detect_order_blocks,
    detect_recent_fvg,
    premium_discount_zone,
)
from app.market_pulse.pro_trade_shared import build_bias_sr_trade_setup, pack_trade_setup
from app.trading_hubs.support_resistance_engine import detect_candlestick_patterns

logger = logging.getLogger(__name__)

_AI_SYSTEM = """You are a Price Action + Smart Money Concepts desk commentator.
You receive a Python TA snapshot of a live chart (factors, levels, last bars).
Rewrite the commentary using ONLY that evidence — never invent prices or indicators.

Return ONLY valid JSON (no markdown):
{
  "now": "2-4 sentences: what is happening right now",
  "next": "2-3 sentences: what can happen next",
  "trade_setup": {
    "action": "BUY|SELL|WAIT",
    "confidence_pct": 55.0,
    "sl_pct": 1.2,
    "tp_pct": 2.4,
    "plain_english": "one short sentence"
  },
  "factors": ["short", "labels"]
}

Rules:
- Prefer WAIT when signals conflict.
- confidence_pct between 12 and 88.
- sl_pct / tp_pct positive when action is BUY or SELL; null ok for WAIT.
- Educational research only — not financial advice.
"""


def _bars_to_df(bars: list[dict[str, Any]] | None) -> pd.DataFrame:
    if not bars:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for b in bars:
        if not isinstance(b, dict):
            continue
        try:
            o = float(b.get("open"))
            h = float(b.get("high"))
            l = float(b.get("low"))
            c = float(b.get("close"))
        except (TypeError, ValueError):
            continue
        if not all(v == v for v in (o, h, l, c)):
            continue
        vol = b.get("volume")
        try:
            volume = float(vol) if vol is not None else 0.0
        except (TypeError, ValueError):
            volume = 0.0
        rows.append(
            {
                "time": str(b.get("time") or b.get("t") or b.get("label") or ""),
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": volume,
            }
        )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    try:
        df.index = pd.to_datetime(df["time"], errors="coerce")
    except Exception:
        pass
    return df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)


def _num(v: Any) -> float | None:
    try:
        if v is None or v == "":
            return None
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _extract_json(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def _support_resistance_from_levels(
    price: float,
    levels: list[dict[str, Any]] | None,
) -> tuple[float | None, float | None, list[str]]:
    notes: list[str] = []
    if not levels or not price:
        return None, None, notes
    below: list[float] = []
    above: list[float] = []
    for lv in levels:
        if not isinstance(lv, dict):
            continue
        p = _num(lv.get("price") if "price" in lv else lv.get("value"))
        if p is None:
            continue
        label = str(lv.get("label") or "S/R").strip()
        notes.append(f"{label} @ {p:g}")
        if p < price:
            below.append(p)
        elif p > price:
            above.append(p)
    support = max(below) if below else None
    resistance = min(above) if above else None
    return support, resistance, notes


def _drawing_notes(drawings: list[dict[str, Any]] | None, price: float) -> list[str]:
    notes: list[str] = []
    if not drawings:
        return notes
    for d in drawings:
        if not isinstance(d, dict):
            continue
        kind = str(d.get("kind") or d.get("type") or "").lower()
        if kind in ("hline", "hray"):
            p = _num(d.get("price"))
            if p is not None:
                side = "below" if p < price else ("above" if p > price else "at")
                notes.append(f"Drawn {kind} {side} price @ {p:g}")
        elif kind == "trend":
            y1, y2 = _num(d.get("y1")), _num(d.get("y2"))
            if y1 is not None and y2 is not None:
                slope = "rising" if y2 > y1 else ("falling" if y2 < y1 else "flat")
                notes.append(f"Drawn trend line ({slope}) from {y1:g} → {y2:g}")
        elif kind == "fib":
            y1, y2 = _num(d.get("y1")), _num(d.get("y2"))
            if y1 is not None and y2 is not None:
                notes.append(f"Drawn fib range {min(y1, y2):g}–{max(y1, y2):g}")
        elif kind == "rect":
            y1, y2 = _num(d.get("y1")), _num(d.get("y2"))
            if y1 is not None and y2 is not None:
                notes.append(f"Drawn zone {min(y1, y2):g}–{max(y1, y2):g}")
    return notes


def _indicator_set(indicators: list[str] | None) -> set[str]:
    return {str(x).strip().lower() for x in (indicators or []) if str(x).strip()}


def compute_chart_commentary(
    *,
    bars: list[dict[str, Any]] | None,
    ticker: str | None = None,
    asset_class: str | None = None,
    indicators: list[str] | None = None,
    levels: list[dict[str, Any]] | None = None,
    drawings: list[dict[str, Any]] | None = None,
    timeframe: str | None = None,
) -> dict[str, Any]:
    """Rule-based chart read from the current bar snapshot."""
    sym = (ticker or "CHART").strip().upper() or "CHART"
    df = _bars_to_df(bars)
    inds = _indicator_set(indicators)
    # Default to core read when client sends nothing
    if not inds:
        inds = {"volume", "ema_9", "ema_20", "bollinger", "rsi"}

    if df.empty or len(df) < 5:
        setup = pack_trade_setup(
            direction="WAIT",
            entry=None,
            stop=None,
            target=None,
            confidence_pct=10.0,
            reason="Insufficient bars for commentary",
            plain_english="Need more candles before a chart read.",
            timeframe=timeframe or "chart",
        )
        return {
            "ticker": sym,
            "asset_class": asset_class,
            "source": "python_ta",
            "now": "Not enough candles on the chart yet to form a reliable read.",
            "next": "Load or stream more bars, then refresh commentary.",
            "trade_setup": setup,
            "factors": ["insufficient_bars"],
            "factor_notes": [],
            "bar_count": int(len(df)),
            "last_close": None,
            "use_ai": False,
        }

    price = float(df["close"].iloc[-1])
    prev = float(df["close"].iloc[-2])
    chg_pct = ((price / prev) - 1.0) * 100.0 if prev else 0.0
    factors: list[str] = []
    notes: list[str] = []
    biases: list[str] = []

    # ── Trend / structure ──────────────────────────────────────────────
    trend = classify_trend(df)
    tname = str(trend.get("trend") or "mixed")
    factors.append(f"trend_{tname}")
    if trend.get("note"):
        notes.append(str(trend["note"]))
    if tname == "bullish":
        biases.append("bullish")
    elif tname == "bearish":
        biases.append("bearish")

    zone = premium_discount_zone(df, swing_window=5)
    zname = str(zone.get("zone") or "unknown")
    if zname in ("premium", "discount"):
        factors.append(f"range_{zname}")
        notes.append(
            f"Price in {zname} of recent swing range"
            + (f" (~{float(zone.get('pct', 0)) * 100:.0f}% of range)" if zone.get("pct") is not None else "")
        )
        if zname == "discount":
            biases.append("bullish")
        elif zname == "premium":
            biases.append("bearish")

    # ── SMC ────────────────────────────────────────────────────────────
    cfg = PaVpSmcConfig()
    fvg = detect_recent_fvg(df)
    if fvg:
        factors.append(str(fvg.get("type") or "fvg"))
        notes.append(
            f"Unfilled {fvg.get('type')} between {fvg.get('bottom')}–{fvg.get('top')}"
        )
        if str(fvg.get("direction")) == "LONG":
            biases.append("bullish")
        elif str(fvg.get("direction")) == "SHORT":
            biases.append("bearish")

    obs = detect_order_blocks(df, cfg, max_blocks=4)
    if obs:
        nearest = obs[0]
        factors.append(f"order_block_{nearest.get('type')}")
        notes.append(
            f"Nearest {nearest.get('type')} order block {nearest.get('bottom')}–{nearest.get('top')}"
        )
        if nearest.get("type") == "bullish" and nearest["bottom"] <= price <= nearest["top"] * 1.005:
            biases.append("bullish")
        elif nearest.get("type") == "bearish" and nearest["bottom"] * 0.995 <= price <= nearest["top"]:
            biases.append("bearish")

    sweep = detect_liquidity_sweep(df, swing_window=5)
    if sweep:
        factors.append(str(sweep.get("type") or "liquidity_sweep"))
        notes.append(str(sweep.get("note") or sweep.get("type")))
        if str(sweep.get("direction")) == "LONG":
            biases.append("bullish")
        elif str(sweep.get("direction")) == "SHORT":
            biases.append("bearish")

    # ── Candlesticks ───────────────────────────────────────────────────
    patterns = detect_candlestick_patterns(df, lookback=5)
    for p in patterns[-3:]:
        name = str(p.get("name") or "pattern")
        factors.append(f"candle_{name.lower().replace(' ', '_')}")
        notes.append(f"{name}: {p.get('note') or p.get('direction') or ''}".strip())
        d = str(p.get("direction") or "").lower()
        if d == "bullish":
            biases.append("bullish")
        elif d == "bearish":
            biases.append("bearish")

    # ── Indicators (only those applied / selected) ─────────────────────
    work = df.copy()
    ema_periods = sorted(
        {
            int(x.split("_")[1])
            for x in inds
            if x.startswith("ema_") and x.split("_")[1].isdigit()
        }
    )
    for period in ema_periods:
        work = add_ema(work, period)
        col = f"ema_{period}"
        if col in work.columns and pd.notna(work[col].iloc[-1]):
            ema_v = float(work[col].iloc[-1])
            rel = "above" if price > ema_v else "below"
            factors.append(f"{col}_{rel}")
            notes.append(f"Price {rel} EMA {period} ({ema_v:g})")
            if period in (9, 20, 50, 200):
                biases.append("bullish" if price > ema_v else "bearish")

    if "bollinger" in inds or "bb" in inds:
        work = add_bollinger_bands(work)
        up_col, mid_col, lo_col = "bb_upper_20_2.0", "bb_middle_20_2.0", "bb_lower_20_2.0"
        if {up_col, mid_col, lo_col}.issubset(work.columns):
            up = float(work[up_col].iloc[-1])
            lo = float(work[lo_col].iloc[-1])
            mid = float(work[mid_col].iloc[-1])
            if price <= lo * 1.002:
                factors.append("bb_near_lower")
                notes.append(f"Price near / at lower Bollinger ({lo:g})")
                biases.append("bullish")
            elif price >= up * 0.998:
                factors.append("bb_near_upper")
                notes.append(f"Price near / at upper Bollinger ({up:g})")
                biases.append("bearish")
            else:
                factors.append("bb_mid_band")
                notes.append(f"Price inside Bollinger mid zone (mid {mid:g})")

    if "rsi" in inds:
        work = add_rsi(work)
        rsi_col = "rsi_14" if "rsi_14" in work.columns else ("rsi" if "rsi" in work.columns else None)
        if rsi_col and pd.notna(work[rsi_col].iloc[-1]):
            rsi_v = float(work[rsi_col].iloc[-1])
            factors.append(f"rsi_{rsi_v:.0f}")
            if rsi_v < 35:
                notes.append(f"RSI {rsi_v:.1f} — oversold tilt")
                biases.append("bullish")
            elif rsi_v > 65:
                notes.append(f"RSI {rsi_v:.1f} — overbought tilt")
                biases.append("bearish")
            else:
                notes.append(f"RSI {rsi_v:.1f} — neutral band")

    if "volume" in inds and "volume" in df.columns:
        work = add_vol_sma(work, 20)
        last_vol = float(df["volume"].iloc[-1] or 0)
        avg_col = "vol_sma_20" if "vol_sma_20" in work.columns else None
        if avg_col and pd.notna(work[avg_col].iloc[-1]) and float(work[avg_col].iloc[-1]) > 0:
            avg_v = float(work[avg_col].iloc[-1])
            ratio = last_vol / avg_v
            factors.append("volume_spike" if ratio >= 1.5 else "volume_normal")
            notes.append(
                f"Last volume {ratio:.1f}× 20-bar average"
                + (" — participation elevated" if ratio >= 1.5 else "")
            )

    # ── Levels + drawings ─────────────────────────────────────────────
    support, resistance, level_notes = _support_resistance_from_levels(price, levels)
    for ln in level_notes[:6]:
        notes.append(f"Level: {ln}")
        factors.append("sr_level")
    if support is not None:
        factors.append("support_below")
    if resistance is not None:
        factors.append("resistance_above")

    for dn in _drawing_notes(drawings, price):
        notes.append(dn)
        factors.append("user_drawing")

    # Deduplicate while preserving order
    seen_f: set[str] = set()
    uniq_factors: list[str] = []
    for f in factors:
        if f in seen_f:
            continue
        seen_f.add(f)
        uniq_factors.append(f)

    setup = build_bias_sr_trade_setup(
        df,
        biases=biases,
        support=support,
        resistance=resistance,
        timeframe=timeframe or "chart",
        base_reason="Chart commentary confluence (SMC + TA + overlays)",
    )

    bull = sum(1 for b in biases if b == "bullish")
    bear = sum(1 for b in biases if b == "bearish")
    lean = "bullish" if bull > bear else ("bearish" if bear > bull else "mixed")

    now_parts = [
        f"{sym} last {price:g} ({chg_pct:+.2f}% vs prior bar).",
        f"Structure lean is {lean} ({bull} bull / {bear} bear votes).",
    ]
    if notes:
        now_parts.append("Key reads: " + "; ".join(notes[:5]) + ("…" if len(notes) > 5 else "") + ".")
    now = " ".join(now_parts)

    if lean == "bullish":
        nxt = (
            "If buyers hold the discount / support confluence, a push toward the nearest "
            "resistance or unfilled bullish FVG is the path of least resistance. "
            "A break and close back below recent swing lows would invalidate."
        )
    elif lean == "bearish":
        nxt = (
            "If sellers defend premium / resistance, continuation toward support or a "
            "bearish imbalance fill is favored. A reclaim above recent swing highs would invalidate."
        )
    else:
        nxt = (
            "Signals are mixed — expect range or chop until a liquidity sweep or clear "
            "BOS with volume confirms a side. Stand aside until confluence stacks."
        )

    return {
        "ticker": sym,
        "asset_class": asset_class,
        "source": "python_ta",
        "now": now,
        "next": nxt,
        "trade_setup": setup,
        "factors": uniq_factors,
        "factor_notes": notes[:16],
        "bar_count": int(len(df)),
        "last_close": round(price, 6),
        "change_pct": round(chg_pct, 3),
        "indicators_applied": sorted(inds),
        "use_ai": False,
    }


def polish_commentary_with_ai(
    payload: dict[str, Any],
    *,
    provider: str,
    model: str,
    api_key: str,
    base_url: str | None = None,
    bars_tail: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Optional AI rewrite of now/next (+ soft trade_setup tweak). Falls back to payload."""
    if not api_key or not isinstance(payload, dict):
        payload["ai_commentary"] = {
            "applied": False,
            "reason": "No AI API key — using Python technical analysis.",
        }
        payload["source"] = "python_ta"
        return payload

    compact = {
        "ticker": payload.get("ticker"),
        "last_close": payload.get("last_close"),
        "change_pct": payload.get("change_pct"),
        "factors": payload.get("factors"),
        "factor_notes": payload.get("factor_notes"),
        "indicators_applied": payload.get("indicators_applied"),
        "rule_now": payload.get("now"),
        "rule_next": payload.get("next"),
        "trade_setup": payload.get("trade_setup"),
        "last_bars": (bars_tail or [])[-24:],
    }
    prompt = (
        "Polish this chart commentary snapshot. Return JSON only.\n\n"
        f"{json.dumps(compact, default=str)}"
    )
    try:
        from app.services.ai_service import call_ai_report

        text = call_ai_report(
            prompt,
            _AI_SYSTEM,
            provider,
            model,
            api_key,
            user_intro="Write now / next / trade_setup from the TA snapshot:",
            max_tokens=1800,
            base_url=base_url,
        )
    except Exception as exc:
        logger.warning("AI chart commentary failed: %s", exc)
        payload["ai_commentary"] = {"applied": False, "reason": f"AI call failed: {exc}"[:180]}
        payload["source"] = "python_ta"
        return payload

    parsed = _extract_json(text if isinstance(text, str) else str(text))
    if not parsed:
        payload["ai_commentary"] = {
            "applied": False,
            "reason": "AI response could not be parsed — kept Python TA commentary.",
            "raw_preview": (text or "")[:240] if isinstance(text, str) else None,
        }
        payload["source"] = "python_ta"
        return payload

    if isinstance(parsed.get("now"), str) and parsed["now"].strip():
        payload["now"] = parsed["now"].strip()
    if isinstance(parsed.get("next"), str) and parsed["next"].strip():
        payload["next"] = parsed["next"].strip()
    if isinstance(parsed.get("factors"), list):
        payload["factors"] = [str(x) for x in parsed["factors"] if x][:24]

    ai_setup = parsed.get("trade_setup") if isinstance(parsed.get("trade_setup"), dict) else None
    base = payload.get("trade_setup") if isinstance(payload.get("trade_setup"), dict) else {}
    if ai_setup and base:
        action = str(ai_setup.get("action") or base.get("action") or "WAIT").upper()
        if action in ("BUY", "LONG", "BULLISH"):
            direction = "LONG"
        elif action in ("SELL", "SHORT", "BEARISH"):
            direction = "SHORT"
        else:
            direction = "WAIT"
        conf = _num(ai_setup.get("confidence_pct"))
        if conf is None:
            conf = _num(base.get("confidence_pct")) or 40.0
        conf = max(12.0, min(88.0, float(conf)))
        sl = _num(ai_setup.get("sl_pct"))
        tp = _num(ai_setup.get("tp_pct"))
        if sl is None:
            sl = _num(base.get("sl_pct"))
        if tp is None:
            tp = _num(base.get("tp_pct"))
        entry = _num(base.get("entry_price"))
        stop = _num(base.get("stop_price"))
        target = _num(base.get("target_price"))
        # Prefer keeping levels; only overwrite pct fields via pack when we have entry
        merged = pack_trade_setup(
            direction=direction,
            entry=entry,
            stop=stop,
            target=target,
            confidence_pct=conf,
            confidence_reasons=list(base.get("confidence_reasons") or []) + ["AI commentary polish"],
            reason=str(ai_setup.get("plain_english") or base.get("reason") or ""),
            plain_english=str(ai_setup.get("plain_english") or base.get("plain_english") or ""),
            timeframe=base.get("timeframe"),
        )
        if sl is not None:
            merged["sl_pct"] = round(abs(float(sl)), 2)
        if tp is not None:
            merged["tp_pct"] = round(abs(float(tp)), 2)
        payload["trade_setup"] = merged

    payload["source"] = "ai"
    payload["use_ai"] = True
    payload["ai_commentary"] = {"applied": True, "provider": provider, "model": model}
    return payload
