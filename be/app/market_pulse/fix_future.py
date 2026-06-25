from pathlib import Path
import re

for path in Path(__file__).parent.glob("*.py"):
    if path.name == "fix_future.py":
        continue
    text = path.read_text(encoding="utf-8")
    if "from __future__ import annotations" not in text:
        continue
    text = re.sub(r"^from contextlib import nullcontext\n", "", text, count=1, flags=re.M)
    if "from contextlib import nullcontext" not in text and "nullcontext()" in text:
        text = text.replace(
            "from __future__ import annotations\n",
            "from __future__ import annotations\n\nfrom contextlib import nullcontext\n",
            1,
        )
    path.write_text(text, encoding="utf-8")
    print("fixed", path.name)
