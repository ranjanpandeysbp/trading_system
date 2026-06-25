"""One-time patch: fix imports and strip streamlit from copied modules."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parent

REPLACEMENTS = [
    ("from truebacktesting.", "from app.market_pulse."),
    ("import truebacktesting.", "import app.market_pulse."),
]

for path in ROOT.glob("*.py"):
    if path.name in {"patch_imports.py", "__init__.py"}:
        continue
    text = path.read_text(encoding="utf-8")
    for old, new in REPLACEMENTS:
        text = text.replace(old, new)
    text = re.sub(r"^import streamlit as st\s*\n", "", text, flags=re.M)
    text = re.sub(r"^from streamlit import .+\s*\n", "", text, flags=re.M)
    text = re.sub(r"@st\.cache_data\([^)]*\)\s*\n", "", text)
    text = re.sub(r"@st\.cache_resource\([^)]*\)\s*\n", "", text)
    text = re.sub(r"^@st\.fragment\s*\n", "", text, flags=re.M)
    text = re.sub(r"with st\.spinner\([^)]*\):", "with nullcontext():", text)
    if "nullcontext()" in text and "from contextlib import nullcontext" not in text:
        text = "from contextlib import nullcontext\n" + text
    path.write_text(encoding="utf-8", data=text)

print("patched", len(list(ROOT.glob("*.py"))), "files")
