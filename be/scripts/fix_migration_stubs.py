"""Fix STREAMLIT_STUB placement — from __future__ must be first."""
from __future__ import annotations

import re
from pathlib import Path

STUB_BLOCK = re.compile(
    r'^"""Streamlit UI stripped.*?st = _StStub\(\)\s*#\s*STREAMLIT_STUB\s*\n+',
    re.DOTALL,
)
FUTURE = re.compile(r'^from __future__ import annotations\s*\n', re.MULTILINE)


def fix_file(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if "STREAMLIT_STUB" not in text:
        return False
    m_stub = STUB_BLOCK.match(text)
    if not m_stub:
        return False
    stub = m_stub.group(0)
    rest = text[m_stub.end() :]
    if not rest.lstrip().startswith('from __future__'):
        # Remove stub entirely if no future import follows
        path.write_text(rest, encoding="utf-8")
        return True
    # future import first, then stub, then remainder after future line
    rest = rest.lstrip()
    if rest.startswith('from __future__ import annotations'):
        after_future = rest[len("from __future__ import annotations\n") :]
        # preserve module docstring if it was before future in rest
        new_text = "from __future__ import annotations\n\n" + stub + after_future
        path.write_text(new_text, encoding="utf-8")
        return True
    return False


def main() -> None:
    root = Path(__file__).resolve().parents[1] / "app" / "market_pulse"
    n = 0
    for path in sorted(root.glob("*.py")):
        if fix_file(path):
            n += 1
            print("fixed", path.name)
    print("done", n)


if __name__ == "__main__":
    main()
