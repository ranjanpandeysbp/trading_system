"""Copy remaining truebacktesting modules into indian_stock_trading."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

SRC = Path(r"c:\work\ranjan\work_crypto_india_stocks\truebacktesting")
BE = Path(__file__).resolve().parents[1] / "app"

REPLACEMENTS = [
    ("from truebacktesting.", "from app.market_pulse."),
    ("import truebacktesting.", "import app.market_pulse."),
    ("from app.market_pulse.trading_hubs.", "from app.trading_hubs."),
    ("from app.market_pulse.etf_ta.", "from app.etf_ta."),
]

# Engines → market_pulse (TA / pulse)
MARKET_PULSE_FILES = [
    "mega_analyser.py",
    "buy_sell_advisor_engine.py",
    "buy_sell_advisor_tab.py",
    "price_action.py",
    "price_action_simple.py",
    "pump_dump_tab.py",
    "pump_dump_predictor.py",
    "india_pump_dump_predictor.py",
    "find_sr_tab.py",
    "weak_strong_sr_tab.py",
    "pattern_breakout_tab.py",
    "fakeout_4h_engine.py",
    "fakeout_4h_tab.py",
    "fakeout_15m_engine.py",
    "fakeout_15m_tab.py",
    "mtf_scanner_tab.py",
    "mtf_hedging_tab.py",
    "hedging_toolkit_engine.py",
    "top_down_mtf_engine.py",
    "top_down_mtf_tab.py",
    "smc_fake_market_shift_engine.py",
    "smc_fake_market_shift_tab.py",
    "weekly_stoch_sweet_spot_engine.py",
    "weekly_stoch_sweet_spot_tab.py",
    "kn_smart_rsi_engine.py",
    "kn_smart_rsi_tab.py",
    "velez_retracement_engine.py",
    "velez_retracement_tab.py",
    "smart_wave_crypto_engine.py",
    "smart_wave_crypto_tab.py",
    "crypto_scalping_engine.py",
    "crypto_scalping_tab.py",
    "confluence_strategy_tab.py",
    "strategy_scheduler_tab.py",
    "elliott_wave_tab.py",
    "top_bottom.py",
    "top_bottom_forecast.py",
    "smc_options_tab.py",
    "ta_mtf_hub_ui.py",
    "ta_screener_ui.py",
    "ta_backtest_runner.py",
    "ta_structure_chart.py",
    "ta_ticker_sections.py",
    "mtf_analysis.py",
    "sr_breakout.py",
    "sr_zone_context.py",
    "sma_ema_position.py",
    "price_extremes.py",
    "big_whale_pump_dump_engine.py",
    "big_whale_pump_dump_tab.py",
    "pump_dump_breakout_tab.py",
    "zireman_confluence_engine.py",
    "accurate_strategy_tab.py",
    "stock_price_rotation.py",
    "stock_price_rotation_markets.py",
    "sector_rotation_markets.py",
    "us_market_yfinance.py",
    "us_index_constituents.py",
    "crypto_session.py",
    "seasonality.py",
    "screener.py",
    "alerts_tab.py",
    "alert_notifier.py",
    "presets.py",
    "multi_combo_saves.py",
    "reporter.py",
    "engine.py",
    "signal_eval.py",
    "section_strategy_guides.py",
    "strategy_encyclopedia_guide.py",
    "ask_ai_context.py",
    "ai_view.py",
    "env_config.py",
    "news_scanner.py",
    "market_pulse_feeds.py",
    "index_ohlcv.py",
    "nse_index_yfinance.py",
    "demo_trading.py",
    "gap_trading.py",
    "indicators.py",
    "heatmap.py",
    "week52_high_low.py",
]

DATA_FILES = [
    "data/EQUITY_L.csv",
    "data/us_sp500.txt",
    "data/us_nasdaq100.txt",
    "data/us_dow30.txt",
    "data/us_russell2000_sample.txt",
]


def patch_file(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for old, new in REPLACEMENTS:
        text = text.replace(old, new)
    # Strip streamlit imports (keep logic; UI dead in API)
    text = re.sub(r"^import streamlit as st\s*\n", "", text, flags=re.M)
    text = re.sub(r"^from streamlit import .+\s*\n", "", text, flags=re.M)
    text = re.sub(r"@st\.cache_data\([^)]*\)\s*\n", "", text)
    text = re.sub(r"@st\.cache_resource\([^)]*\)\s*\n", "", text)
    text = re.sub(r"^@st\.fragment\s*\n", "", text, flags=re.M)
    if "st." in text and "STREAMLIT_STUB" not in text:
        stub = (
            '"""Streamlit UI stripped — use FastAPI + React."""\n'
            "class _StStub:\n"
            "    session_state = {}\n"
            "    def __getattr__(self, _):\n"
            "        def _noop(*a, **k): return None\n"
            "        return _noop\n"
            "st = _StStub()  # STREAMLIT_STUB\n\n"
        )
        if "st = _StStub()" not in text:
            text = stub + text
    path.write_text(encoding="utf-8", data=text)


def main() -> None:
    dst_mp = BE / "market_pulse"
    dst_mp.mkdir(parents=True, exist_ok=True)
    data_dst = BE / "data"
    data_dst.mkdir(parents=True, exist_ok=True)

    copied = 0
    for name in MARKET_PULSE_FILES:
        src = SRC / name
        if not src.exists():
            print("skip missing", name)
            continue
        out = dst_mp / Path(name).name
        shutil.copy2(src, out)
        patch_file(out)
        copied += 1
        print("copied", name)

    for rel in DATA_FILES:
        src = SRC / rel
        if src.exists():
            out = data_dst / Path(rel).name
            shutil.copy2(src, out)
            print("data", rel)

    print(f"Done — {copied} modules copied to market_pulse/")


if __name__ == "__main__":
    main()
