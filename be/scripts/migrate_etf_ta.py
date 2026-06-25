"""Copy ETF TA IN modules from truebacktesting."""
from __future__ import annotations

import shutil
from pathlib import Path

SRC = Path(r"c:\work\ranjan\work_crypto_india_stocks\truebacktesting")
DST = Path(__file__).resolve().parents[1] / "app" / "etf_ta"

REPLACEMENTS = [
    ("from truebacktesting.gap_trading", "from app.market_pulse.gap_trading"),
    ("from truebacktesting.india_etf_universe", "from app.etf_ta.india_etf_universe"),
]


def patch(text: str) -> str:
    for old, new in REPLACEMENTS:
        text = text.replace(old, new)
    return text


def main() -> None:
    DST.mkdir(parents=True, exist_ok=True)
    for name in ("india_etf_universe.py", "stf_shop_engine.py"):
        shutil.copy2(SRC / name, DST / name)
        (DST / name).write_text(patch((DST / name).read_text(encoding="utf-8")), encoding="utf-8")
        print("patched", name)
    (DST / "__init__.py").write_text('"""India ETF TA — ETF Shop 4.0 (STF Shop)."""\n', encoding="utf-8")


if __name__ == "__main__":
    main()
