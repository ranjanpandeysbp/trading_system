from contextlib import nullcontext
import re
from pathlib import Path

ROOT = Path(__file__).parent
for path in ROOT.glob("*.py"):
    if path.name == "fix_spinners.py":
        continue
    text = path.read_text(encoding="utf-8")
    new = re.sub(r"with nullcontext\(\)[^:]*\):", "with nullcontext():", text)
    if new != text:
        path.write_text(new, encoding="utf-8")
        print("fixed", path.name)
