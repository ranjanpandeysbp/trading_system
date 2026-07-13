from pathlib import Path
import re


def _run() -> None:
    for path in Path(__file__).parent.glob("*.py"):
        if path.name == "fix_future.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "from __future__ import annotations" not in text:
            continue
        new_text = re.sub(r"^from contextlib import nullcontext\n", "", text, count=1, flags=re.M)
        if "from contextlib import nullcontext" not in new_text and "nullcontext()" in new_text:
            new_text = new_text.replace(
                "from __future__ import annotations\n",
                "from __future__ import annotations\n\nfrom contextlib import nullcontext\n",
                1,
            )
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
            print("fixed", path.name)


# Guarded: one-time migration script — must not run as a side effect of import
# (e.g. a package-wide import audit or pytest collection).
if __name__ == "__main__":
    _run()
