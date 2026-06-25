"""One-time copy of TA modules from truebacktesting."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

SRC = Path(r"c:\work\ranjan\work_crypto_india_stocks\truebacktesting")
DST = Path(__file__).resolve().parents[1] / "app" / "market_pulse"

REPLACEMENTS = [
    ("from truebacktesting.", "from app.market_pulse."),
    ("import truebacktesting.", "import app.market_pulse."),
]


def patch_file(path: Path) -> None:
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


def main() -> None:
    for name in [
        "sr_breakout.py",
        "sr_zone_context.py",
        "weak_strong_sr_engine.py",
        "ticker_investigation_engine.py",
    ]:
        shutil.copy2(SRC / name, DST / name)
        patch_file(DST / name)
        print("copied", name)

    rs_src = (SRC / "run_summary.py").read_text(encoding="utf-8").splitlines()
    chunk = "\n".join(rs_src[176:247])
    run_summary = (
        '"""Minimal trade-plan helpers for ticker investigation."""\n'
        "from __future__ import annotations\n\n" + chunk + "\n"
    )
    (DST / "run_summary.py").write_text(run_summary, encoding="utf-8")
    print("wrote run_summary.py")

    app_lines = (SRC / "app.py").read_text(encoding="utf-8").splitlines()
    body = "\n".join(app_lines[2468:3213])
    header = '''"""Trend and Sentiment Screener — composite score (India)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.sr_breakout import (
    analyze_sr_breakout,
    apply_sr_breakout_scoring,
    compute_trade_confidence,
)
from app.market_pulse.ticker_utils import GROWW_MARKET, is_crypto_market, is_india_market

'''
    footer = '''

def run_sentiment_screener(
    tickers: list[str],
    timeframes: list[str],
    *,
    market: str = GROWW_MARKET,
    groww_token: str = "",
    exchange: str = "NSE",
    lookback_days: int = 120,
) -> dict:
    """Scan tickers x timeframes; returns ranked rows."""
    rows: list[dict] = []
    errors: list[str] = []
    for tick in tickers:
        for tf in timeframes:
            try:
                df = fetch_data_for_gap_scan(
                    tick, tf, market, groww_token, exchange, limit=max(lookback_days, 300)
                )
                if df is None or df.empty or len(df) < 50:
                    rows.append({
                        "ticker": tick,
                        "timeframe": tf,
                        "score": 0.0,
                        "rating": "No Data",
                        "insights": ["Insufficient candle history."],
                        "trade_signal": "WAIT",
                        "error": "insufficient_data",
                    })
                    continue
                analysis = analyze_ticker_sentiment(df, market=market, timeframe=tf)
                rows.append({
                    "ticker": tick,
                    "timeframe": tf,
                    "score": analysis.get("score", 0),
                    "rating": analysis.get("rating", ""),
                    "insights": analysis.get("insights", []),
                    "rsi": analysis.get("rsi"),
                    "vol_ratio": analysis.get("vol_ratio"),
                    "macd_hist": analysis.get("macd_hist"),
                    "adx": analysis.get("adx"),
                    "trend_str": analysis.get("trend_str"),
                    "trade_signal": analysis.get("trade_signal"),
                    "sl_pct": analysis.get("sl_pct"),
                    "tp_pct": analysis.get("tp_pct"),
                    "atr_pct": analysis.get("atr_pct"),
                    "trade_confidence": analysis.get("trade_confidence"),
                    "sr_breakout": analysis.get("sr_breakout"),
                    "current_price": float(df["close"].iloc[-1]),
                })
            except Exception as exc:
                errors.append(f"{tick}|{tf}: {exc}")
                rows.append({"ticker": tick, "timeframe": tf, "error": str(exc)[:200]})
    rows.sort(key=lambda r: abs(r.get("score") or 0), reverse=True)
    return {"market": market, "rows": rows, "errors": errors}
'''
    (DST / "sentiment_screener_engine.py").write_text(header + body + footer, encoding="utf-8")
    print("wrote sentiment_screener_engine.py")


if __name__ == "__main__":
    main()
