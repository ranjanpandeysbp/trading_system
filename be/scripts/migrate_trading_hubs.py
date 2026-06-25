"""Copy Swing / Intraday / Scalping / Smart Money engines from truebacktesting."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

SRC = Path(r"c:\work\ranjan\work_crypto_india_stocks\truebacktesting")
DST = Path(__file__).resolve().parents[1] / "app" / "trading_hubs"

ENGINE_FILES = [
    "swing_trading_st_engine.py",
    "swing_trading_st_mtf_mss_engine.py",
    "swing_trading_st_supertrend_engine.py",
    "swing_trading_st_kiss_engine.py",
    "swing_trading_st_ha_ema_engine.py",
    "intraday_alpha_945_engine.py",
    "intraday_fib945_engine.py",
    "intraday_vwap_fade_engine.py",
    "scalp_rectangle_engine.py",
    "smc_cisd_engine.py",
    "smc_weekly_sweep_cisd_engine.py",
    "smc_mtf_day_plan_engine.py",
    "smc_golden_bullet_engine.py",
    "top_down_mtf_engine.py",
    "swing_trading_st_shared.py",
    "intraday_shared.py",
    "smart_money_shared.py",
]

MARKET_PULSE = {
    "gap_trading",
    "mtf_scanner_engine",
    "run_summary",
    "indicators",
    "groww_auth",
}

REPLACEMENTS = [
    ("from truebacktesting.weekly_stoch_sweet_spot_engine import _resample_weekly", "from app.trading_hubs.weekly_helpers import _resample_weekly"),
]


def patch_text(text: str) -> str:
    text = re.sub(
        r"from truebacktesting\.fakeout_4h_engine import \([^)]+\)",
        "from app.trading_hubs.session_constants import (\n    INDIA_MARKET_CLOSE,\n    INDIA_MARKET_OPEN,\n    IST_TZ,\n    NY_TZ,\n    _ist_time_on_date,\n)",
        text,
        flags=re.S,
    )
    for old, new in REPLACEMENTS:
        text = text.replace(old, new)
    for mod in MARKET_PULSE:
        text = text.replace(f"from truebacktesting.{mod}", f"from app.market_pulse.{mod}")
        text = text.replace(f"import truebacktesting.{mod}", f"import app.market_pulse.{mod}")
    text = text.replace("from truebacktesting.", "from app.trading_hubs.")
    text = text.replace("import truebacktesting.", "import app.trading_hubs.")
    text = re.sub(r"^import streamlit as st\s*\n", "", text, flags=re.M)
    text = re.sub(r"^from streamlit import .+\s*\n", "", text, flags=re.M)
    text = re.sub(r"@st\.cache_data\([^)]*\)\s*\n", "", text)
    text = re.sub(r"@st\.cache_resource\([^)]*\)\s*\n", "", text)
    text = re.sub(r"^@st\.fragment\s*\n", "", text, flags=re.M)
    # Remove streamlit render helpers from shared modules (keep enrich_* functions)
    for fn in (
        "render_st_trade_banner",
        "render_st_trade_metrics",
        "render_intra_trade_banner",
        "render_intra_trade_metrics",
        "render_smc_trade_banner",
        "render_smc_trade_metrics",
    ):
        pattern = rf"^def {fn}\(.*?(?=^def |\Z)"
        text = re.sub(pattern, "", text, flags=re.M | re.S)
    return text


def main() -> None:
    DST.mkdir(parents=True, exist_ok=True)
    for name in ENGINE_FILES:
        shutil.copy2(SRC / name, DST / name)
        path = DST / name
        path.write_text(patch_text(path.read_text(encoding="utf-8")), encoding="utf-8")
        print("patched", name)
    print("done", len(ENGINE_FILES), "files")


if __name__ == "__main__":
    main()
