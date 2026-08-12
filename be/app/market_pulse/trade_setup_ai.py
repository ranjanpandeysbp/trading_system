"""
trade_setup_ai.py
-----------------
Optional AI refinement of rule-based Trade setup fields:
  confidence %, SL %, TP %, and (when present) reverse/continue probabilities.

Used when the caller passes use_ai=True. Falls back to the original numbers
if no API key is configured or the model response cannot be parsed.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_MAX_ITEMS = 12

_SYSTEM = """You are a careful trading analyst refining rule-based trade setups.
You receive compact JSON for each ticker (already computed levels + sample odds).
Return ONLY valid JSON (no markdown) as:
{"refinements":[{"ticker":"SYM","confidence_pct":55.0,"sl_pct":2.1,"tp_pct":4.5,"reverse_chance_pct":null,"continue_chance_pct":null,"bias":null,"plain_english":"one short sentence","rationale":"one short sentence"}]}

Rules:
- confidence_pct must be between 12 and 88.
- Keep direction/action unchanged; only refine confidence and risk percentages.
- sl_pct and tp_pct must stay positive; prefer modest adjustments (±40% of original) unless original is missing.
- If reverse_chance_pct / continue_chance_pct are provided, refine them so they sum to ~100 (or leave nulls).
- bias may be "reverse", "continue", "mixed", or null.
- Prefer evidence in the payload (samples, analogues, RR, grade). Do not invent prices.
- Educational research only — not financial advice.
"""


def _clip(v: float, lo: float, hi: float) -> float:
    return float(max(lo, min(hi, v)))


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
    # Strip common fences
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


def _compact_item(row: dict[str, Any]) -> dict[str, Any] | None:
    """Build a small payload for one ticker that has a trade setup."""
    setup = row.get("trade_setup") if isinstance(row.get("trade_setup"), dict) else None
    conf = _num((setup or {}).get("confidence_pct") if setup else row.get("confidence_pct"))
    sl = _num((setup or {}).get("sl_pct") if setup else row.get("sl_pct"))
    tp = _num((setup or {}).get("tp_pct") if setup else row.get("tp_pct"))
    if conf is None and sl is None and tp is None and setup is None:
        # Still allow from-top probability-only rows
        if row.get("reverse_chance_pct") is None and row.get("continue_chance_pct") is None:
            return None

    ticker = str(row.get("ticker") or row.get("symbol") or "").strip()
    if not ticker:
        return None

    item: dict[str, Any] = {
        "ticker": ticker,
        "action": (setup or {}).get("action") or row.get("action") or row.get("direction"),
        "direction": (setup or {}).get("direction") or row.get("direction") or row.get("bias"),
        "confidence_pct": conf,
        "sl_pct": sl,
        "tp_pct": tp,
        "rr": (setup or {}).get("rr") if setup else row.get("rr"),
        "grade": (setup or {}).get("grade") if setup else row.get("grade"),
        "entry_price": (setup or {}).get("entry_price") if setup else row.get("entry_price") or row.get("last"),
        "stop_price": (setup or {}).get("stop_price") if setup else row.get("stop_price"),
        "target_price": (setup or {}).get("target_price") if setup else row.get("target_price"),
        "fall_from_top_pct": row.get("fall_from_top_pct") or row.get("fall_from_high_pct"),
        "reverse_chance_pct": row.get("reverse_chance_pct"),
        "continue_chance_pct": row.get("continue_chance_pct"),
        "upside_if_reverse_pct": row.get("upside_if_reverse_pct"),
        "further_fall_if_continue_pct": row.get("further_fall_if_continue_pct"),
        "analogues": row.get("analogues") or row.get("samples"),
        "bias": row.get("bias"),
        "plain_english": (setup or {}).get("plain_english")
        or row.get("plain_english")
        or row.get("reason"),
    }
    # Drop nulls to keep prompt small
    return {k: v for k, v in item.items() if v is not None}


def _apply_refinement(row: dict[str, Any], ref: dict[str, Any]) -> None:
    conf = _num(ref.get("confidence_pct"))
    sl = _num(ref.get("sl_pct"))
    tp = _num(ref.get("tp_pct"))
    rev = _num(ref.get("reverse_chance_pct"))
    cont = _num(ref.get("continue_chance_pct"))
    bias = ref.get("bias")
    plain = ref.get("plain_english") or ref.get("rationale")

    setup = row.get("trade_setup") if isinstance(row.get("trade_setup"), dict) else None
    if setup is None and (conf is not None or sl is not None or tp is not None):
        setup = {}
        row["trade_setup"] = setup

    if setup is not None:
        if conf is not None:
            setup["confidence_pct"] = round(_clip(conf, 12.0, 88.0), 1)
            row["confidence_pct"] = setup["confidence_pct"]
        if sl is not None and sl > 0:
            setup["sl_pct"] = round(_clip(sl, 0.15, 40.0), 2)
            row["sl_pct"] = setup["sl_pct"]
        if tp is not None and tp > 0:
            setup["tp_pct"] = round(_clip(tp, 0.15, 80.0), 2)
            row["tp_pct"] = setup["tp_pct"]
        if setup.get("sl_pct") and setup.get("tp_pct"):
            try:
                setup["rr"] = round(float(setup["tp_pct"]) / float(setup["sl_pct"]), 2)
                row["rr"] = setup["rr"]
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        setup["ai_refined"] = True
        if plain:
            note = str(plain).strip()
            prev = str(setup.get("plain_english") or "").strip()
            setup["plain_english"] = f"{note} (AI-refined)" if not prev else f"{prev} · AI: {note}"
            setup["ai_rationale"] = note

    if conf is not None and setup is None:
        row["confidence_pct"] = round(_clip(conf, 12.0, 88.0), 1)
    if sl is not None and sl > 0 and "sl_pct" in row:
        row["sl_pct"] = round(_clip(sl, 0.15, 40.0), 2)
    if tp is not None and tp > 0 and "tp_pct" in row:
        row["tp_pct"] = round(_clip(tp, 0.15, 80.0), 2)

    if rev is not None:
        row["reverse_chance_pct"] = round(_clip(rev, 0.0, 100.0), 1)
    if cont is not None:
        row["continue_chance_pct"] = round(_clip(cont, 0.0, 100.0), 1)
    if rev is not None and cont is not None:
        total = float(row["reverse_chance_pct"]) + float(row["continue_chance_pct"])
        if total > 0 and abs(total - 100.0) > 8:
            row["reverse_chance_pct"] = round(100.0 * float(row["reverse_chance_pct"]) / total, 1)
            row["continue_chance_pct"] = round(100.0 - float(row["reverse_chance_pct"]), 1)

    if bias in ("reverse", "continue", "mixed"):
        row["bias"] = bias
        labels = {
            "reverse": "Likely reverse / bounce",
            "continue": "Likely continued fall",
            "mixed": "Mixed / no clear edge",
        }
        row["bias_label"] = labels[bias]

    row["ai_refined"] = True
    if plain:
        row["ai_rationale"] = str(plain).strip()


def collect_trade_setup_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Find dict rows that look like trade setups inside a scan payload."""
    rows: list[dict[str, Any]] = []
    for key in ("knives", "results", "entries", "setups", "signals"):
        block = payload.get(key)
        if isinstance(block, list):
            for r in block:
                if isinstance(r, dict):
                    rows.append(r)
    # Single-ticker payloads (e.g. ticker chart)
    if isinstance(payload.get("trade_setup"), dict) or payload.get("confidence_pct") is not None:
        rows.append(payload)
    # Deduplicate by id()
    seen: set[int] = set()
    uniq: list[dict[str, Any]] = []
    for r in rows:
        i = id(r)
        if i in seen:
            continue
        seen.add(i)
        uniq.append(r)
    return uniq


def refine_trade_setups_with_ai(
    payload: dict[str, Any],
    *,
    provider: str,
    model: str,
    api_key: str,
    section: str = "trade_setup",
    max_items: int = _MAX_ITEMS,
    base_url: str | None = None,
) -> dict[str, Any]:
    """
    Mutates and returns payload: AI-refines matched trade setups in place.
    Safe no-op when api_key missing or nothing to refine.
    """
    if not api_key:
        payload["ai_refinement"] = {
            "applied": False,
            "reason": "No AI API key configured — using rule-based confidence/SL/TP.",
        }
        return payload

    candidates = collect_trade_setup_rows(payload)
    # Prefer matched / take_trade rows
    ranked = sorted(
        candidates,
        key=lambda r: (
            0 if r.get("matched") or r.get("take_trade") else 1,
            0 if isinstance(r.get("trade_setup"), dict) else 1,
            -(float(_num(r.get("confidence_pct")) or 0)),
        ),
    )
    compact: list[dict[str, Any]] = []
    index_by_ticker: dict[str, dict[str, Any]] = {}
    for r in ranked:
        item = _compact_item(r)
        if not item:
            continue
        t = str(item["ticker"]).upper()
        if t in index_by_ticker:
            continue
        compact.append(item)
        index_by_ticker[t] = r
        if len(compact) >= max(1, min(max_items, 20)):
            break

    if not compact:
        payload["ai_refinement"] = {"applied": False, "reason": "No trade setups to refine."}
        return payload

    prompt = (
        f"Section: {section}\n"
        f"Refine these {len(compact)} trade setup(s). Return JSON only.\n\n"
        f"{json.dumps(compact, default=str)}"
    )

    try:
        from app.services.ai_service import call_ai_report

        text = call_ai_report(
            prompt,
            _SYSTEM,
            provider,
            model,
            api_key,
            user_intro="Refine confidence / SL / TP / reverse-continue odds:",
            max_tokens=2200,
            base_url=base_url,
        )
    except Exception as exc:
        logger.warning("AI trade-setup refine call failed: %s", exc)
        payload["ai_refinement"] = {"applied": False, "reason": f"AI call failed: {exc}"[:180]}
        return payload

    parsed = _extract_json(text if isinstance(text, str) else str(text))
    refinements = (parsed or {}).get("refinements") if parsed else None
    if not isinstance(refinements, list) or not refinements:
        payload["ai_refinement"] = {
            "applied": False,
            "reason": "AI response could not be parsed — kept rule-based numbers.",
            "raw_preview": (text or "")[:240] if isinstance(text, str) else None,
        }
        return payload

    applied = 0
    for ref in refinements:
        if not isinstance(ref, dict):
            continue
        t = str(ref.get("ticker") or "").strip().upper()
        row = index_by_ticker.get(t)
        if not row:
            continue
        _apply_refinement(row, ref)
        applied += 1

    payload["ai_refinement"] = {
        "applied": applied > 0,
        "refined_count": applied,
        "requested_count": len(compact),
        "provider": provider,
        "model": model,
        "reason": (
            f"AI refined {applied}/{len(compact)} trade setup(s)."
            if applied
            else "AI returned no matching tickers — kept rule-based numbers."
        ),
    }
    payload["use_ai"] = True
    return payload
