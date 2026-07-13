import re
from pathlib import Path

ROOT = Path(__file__).parent


def _run() -> None:
    for path in ROOT.glob("*.py"):
        if path.name == "fix_spinners.py":
            continue
        text = path.read_text(encoding="utf-8")
        new = re.sub(r"with nullcontext\(\)[^:]*\):", "with nullcontext():", text)
        if new != text:
            path.write_text(new, encoding="utf-8")
            print("fixed", path.name)


# Guarded: one-time migration script — must not run as a side effect of import
# (e.g. a package-wide import audit or pytest collection).
if __name__ == "__main__":
    _run()
