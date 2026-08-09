"""Build one copy-paste markdown of all strategy guides."""
from __future__ import annotations

import sys
import types
from pathlib import Path

# strategy_encyclopedia_guide imports streamlit at module load — stub for CLI use
if "streamlit" not in sys.modules:
    sys.modules["streamlit"] = types.ModuleType("streamlit")

from app.market_pulse.section_strategy_guides import SECTION_GUIDES
from app.market_pulse.strategy_encyclopedia_guide import (
    _SECTION_EXTRAS,
    encyclopedia_catalog,
)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "ALL_STRATEGIES_EXPLAINED.md"


def main() -> None:
    cat = encyclopedia_catalog()
    parts: list[str] = [
        "# TrueBacktester — All Strategies Explained",
        "",
        f"Generated catalog: **{cat['section_count']}** sections across **{cat['hub_count']}** hubs.",
        "",
        "Research / education only — not financial advice. Always confirm with your own analysis and risk rules.",
        "",
    ]
    if cat.get("overview"):
        parts += ["# App overview", "", cat["overview"].strip(), ""]
    if cat.get("workflows"):
        parts += ["# Workflows", "", cat["workflows"].strip(), ""]
    if cat.get("when_to_use"):
        parts += ["# When to use what", "", cat["when_to_use"].strip(), ""]

    seen: set[str] = set()
    for hub in cat["hubs"]:
        parts += [f"## {hub['hub']}", ""]
        for entry in hub["sections"]:
            sid = entry["id"]
            seen.add(sid)
            parts += [f"### {entry['title']}", f"*id: `{sid}`*", ""]
            body = (entry.get("guide") or "").strip()
            extra = (entry.get("extra") or "").strip()
            if not body:
                body = (SECTION_GUIDES.get(sid) or "").strip() or "_No detailed guide available yet._"
            parts.append(body)
            if extra:
                parts += ["", extra]
            parts += ["", "---", ""]

    # Prediction desks + any SECTION_GUIDES keys not already listed
    extras: list[tuple[str, str, str]] = [
        ("pattern_analogue", "Prediction — Pattern Analogue", "pattern_analogue"),
        ("astro_finance", "Prediction — Astro Finance", "astro_finance"),
    ]
    try:
        from app.trading_hubs.registry import HUB_META, HUB_SECTIONS as TH_SECTIONS

        for hub_id, sections in (TH_SECTIONS or {}).items():
            meta = (HUB_META or {}).get(hub_id) or {}
            label = meta.get("label") or hub_id
            for sec in sections or []:
                if isinstance(sec, dict):
                    sid = str(sec.get("id") or "")
                    title = str(sec.get("label") or sid)
                elif isinstance(sec, (list, tuple)) and sec:
                    sid = str(sec[0])
                    title = str(sec[1] if len(sec) > 1 else sid)
                else:
                    continue
                if sid:
                    extras.append((sid, f"Trading Hubs — {label} — {title}", sid))
    except Exception as exc:  # noqa: BLE001
        parts += [f"_Trading hubs registry skipped: {exc}_", ""]

    # Also include any SECTION_GUIDES not covered
    for sid in sorted(SECTION_GUIDES.keys()):
        if sid not in seen and sid not in {e[0] for e in extras}:
            extras.append((sid, sid.replace("_", " ").title(), sid))

    header_done = False
    for sid, title, guide_key in extras:
        if sid in seen:
            continue
        body = (SECTION_GUIDES.get(guide_key) or SECTION_GUIDES.get(sid) or "").strip()
        extra = (_SECTION_EXTRAS.get(guide_key) or _SECTION_EXTRAS.get(sid) or "").strip()
        if not body and not extra:
            continue
        if not header_done:
            parts += ["## Additional desks & guides", ""]
            header_done = True
        parts += [f"### {title}", f"*id: `{sid}`*", "", body or "_See app section for methodology._"]
        if extra:
            parts += ["", extra]
        parts += ["", "---", ""]
        seen.add(sid)

    if cat.get("strategy_lab_detail"):
        parts += ["# Strategy Lab & tools detail", "", cat["strategy_lab_detail"].strip(), ""]

    text = "\n".join(parts)
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT}")
    print(f"chars={len(text)} lines={text.count(chr(10)) + 1} sections={len(seen)}")


if __name__ == "__main__":
    main()
