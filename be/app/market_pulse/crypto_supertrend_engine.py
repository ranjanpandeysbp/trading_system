"""
crypto_supertrend_engine.py
---------------------------
Crypto Trading · SuperTrend (S2 · Archit Trend Flow)

GREEN line below price = UPTREND → LONG when ST turns GREEN.
RED line above price = DOWNTREND → SHORT when ST turns RED.
SL / invalidate: color flip (also fixed % stop from desk presets).
Target: fixed % from entry (per coin).

Per-coin ATR / Factor / SL% / TP% (default desk):

| Coin     | TF | ATR | Factor | SL% | TP% |
|----------|----|-----|--------|-----|-----|
| BTC-USDT | 1h | 25  | 6.325  | 2.5 | 4   |
| ETH-USDT | 1h | 15  | 6.325  | 2.5 | 5   |
| SOL-USDT | 1h | 25  | 3.5    | 3.5 | 7   |
| XRP-USDT | 1h | 10  | 2.5    | 2.5 | 4   |

Research / education only — not financial advice.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from typing import Any

import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.pro_trade_shared import pack_trade_setup, sl_tp_pct
from app.market_pulse.run_summary import make_trade_plan
from app.market_pulse.smart_wave_crypto_engine import supertrend_signals

logger = logging.getLogger(__name__)

STRATEGY_ID = "crypto_supertrend"
STRATEGY_NAME = "SuperTrend"
MARKET = "CoinDCX Futures"

COIN_PRESETS: dict[str, dict[str, Any]] = {
    "BTC-USDT": {"timeframe": "1h", "atr_length": 25, "factor": 6.325, "sl_pct": 2.5, "tp_pct": 4.0},
    "ETH-USDT": {"timeframe": "1h", "atr_length": 15, "factor": 6.325, "sl_pct": 2.5, "tp_pct": 5.0},
    "SOL-USDT": {"timeframe": "1h", "atr_length": 25, "factor": 3.5, "sl_pct": 3.5, "tp_pct": 7.0},
    "XRP-USDT": {"timeframe": "1h", "atr_length": 10, "factor": 2.5, "sl_pct": 2.5, "tp_pct": 4.0},
}

DEFAULT_COINS = list(COIN_PRESETS.keys())

HOW_IT_WORKS = """
### SuperTrend (S2 · Archit Trend Flow)

SuperTrend shows trend with a colored line. **GREEN below price = uptrend**. **RED above price = downtrend**.
Uses ATR to auto-adjust for volatility. Color change = signal.

| Side | Rule |
|------|------|
| **LONG** | SuperTrend turns **GREEN** → LONG |
| **SHORT** | SuperTrend turns **RED** → SHORT |
| **SL** | Color flip (invalidate) · also fixed % stop from preset |
| **TF** | 30m or 1h (desk presets use **1h**) |

| Coin | TF | ATR Length | Factor | SL % | Target % |
|------|-----|------------|--------|------|----------|
| BTCUSDT | 1h | 25 | 6.325 | 2.5 | 4 |
| ETHUSDT | 1h | 15 | 6.325 | 2.5 | 5 |
| SOLUSDT | 1h | 25 | 3.5 | 3.5 | 7 |
| XRPUSDT | 1h | 10 | 2.5 | 2.5 | 4 |
"""

RULES = [
    "GREEN ST below price = uptrend (LONG on fresh green flip).",
    "RED ST above price = downtrend (SHORT on fresh red flip).",
    "Invalidate / structural SL when SuperTrend color flips against the trade.",
    "Money SL/TP from per-coin % presets (ATR length + factor also per coin).",
    "Default universe: BTC ETH SOL XRP on CoinDCX · 1h.",
]

PRO_TIPS = [
    "Prefer flips that hold into the next bar close — avoid one-bar whipsaws.",
    "BTC/ETH use a high factor (6.325) — fewer but cleaner flips.",
    "SOL uses a wider 3.5% stop — size down if you keep ₹ risk fixed.",
]


@dataclass
class SupertrendConfig:
    timeframe: str = "1h"
    atr_length: int = 25
    factor: float = 6.325
    sl_pct: float = 2.5
    tp_pct: float = 4.0
    lookback_bars: int = 300
    min_bars: int = 60
    chart_bars: int = 120
    take_confidence_threshold: float = 55.0
    side: str = "both"
    default_tickers: list[str] = field(default_factory=lambda: list(DEFAULT_COINS))

    def __post_init__(self) -> None:
        tf = str(self.timeframe or "1h").lower()
        if tf in ("60m", "1hr", "60"):
            tf = "1h"
        if tf in ("30", "30min"):
            tf = "30m"
        if tf not in ("15m", "30m", "1h", "4h"):
            tf = "1h"
        self.timeframe = tf
        side = str(self.side or "both").lower()
        if side in ("buy", "long", "up"):
            side = "long"
        elif side in ("sell", "short", "down"):
            side = "short"
        elif side not in ("long", "short", "both"):
            side = "both"
        self.side = side


def normalize_ticker(ticker: str) -> str:
    t = (ticker or "").strip().upper().replace("/", "-").replace("_", "-")
    if t.endswith("USDT") and "-" not in t:
        t = t[:-4] + "-USDT"
    if t in COIN_PRESETS:
        return t
    if f"{t}-USDT" in COIN_PRESETS:
        return f"{t}-USDT"
    return t


def preset_for(ticker: str) -> dict[str, Any] | None:
    return COIN_PRESETS.get(normalize_ticker(ticker))


def config_for_ticker(ticker: str, base: SupertrendConfig | None = None) -> SupertrendConfig:
    cfg = base or SupertrendConfig()
    pre = preset_for(ticker)
    if not pre:
        return cfg
    return replace(
        cfg,
        timeframe=str(pre["timeframe"]),
        atr_length=int(pre["atr_length"]),
        factor=float(pre["factor"]),
        sl_pct=float(pre["sl_pct"]),
        tp_pct=float(pre["tp_pct"]),
    )


def _r(x: float, n: int = 6) -> float:
    return round(float(x), n)


def _build_chart(work: pd.DataFrame, *, max_bars: int) -> list[dict[str, Any]]:
    if work is None or work.empty:
        return []
    tail = work.iloc[-max_bars:]
    rows: list[dict[str, Any]] = []
    for idx, bar in tail.iterrows():
        row: dict[str, Any] = {
            "time": str(idx),
            "open": _r(float(bar["open"])),
            "high": _r(float(bar["high"])),
            "low": _r(float(bar["low"])),
            "close": _r(float(bar["close"])),
            "volume": _r(float(bar["volume"]), 2) if "volume" in bar and pd.notna(bar.get("volume")) else None,
        }
        if "supertrend" in bar and pd.notna(bar.get("supertrend")):
            row["supertrend"] = _r(float(bar["supertrend"]), 6)
        if "st_direction" in bar and pd.notna(bar.get("st_direction")):
            row["st_direction"] = int(bar["st_direction"])
        rows.append(row)
    return rows


def analyze_ticker(
    ticker: str,
    *,
    cfg: SupertrendConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
) -> dict[str, Any]:
    ticker_n = normalize_ticker(ticker)
    cfg = config_for_ticker(ticker_n, cfg)
    pre = preset_for(ticker_n)

    out: dict[str, Any] = {
        "ticker": ticker_n,
        "timeframe": cfg.timeframe,
        "strategy": STRATEGY_ID,
        "strategy_label": STRATEGY_NAME,
        "signal": "WAIT",
        "direction": "NONE",
        "take_trade": False,
        "checks": [],
        "metrics": {},
        "preset": pre,
        "pro_tips": PRO_TIPS[:3],
    }

    try:
        raw = fetch_data_for_gap_scan(
            ticker_n, cfg.timeframe, MARKET, groww_token, exchange, limit=int(cfg.lookback_bars),
        )
        df = normalize_ohlcv(raw)
    except Exception as exc:
        out["error"] = str(exc)[:240]
        return out

    need = max(int(cfg.min_bars), int(cfg.atr_length) + 15)
    if df is None or len(df) < need:
        out["error"] = f"Need ≥{need} {cfg.timeframe} bars; got {0 if df is None else len(df)}"
        return out

    work = supertrend_signals(df, period=int(cfg.atr_length), mult=float(cfg.factor))
    i = len(work) - 1
    if i < 1:
        out["error"] = "Not enough bars"
        return out

    sig = int(work["signal"].iloc[i]) if pd.notna(work["signal"].iloc[i]) else 0
    sig_idx = i
    if sig == 0:
        for j in range(i, max(i - 2, 0) - 1, -1):
            s = int(work["signal"].iloc[j]) if pd.notna(work["signal"].iloc[j]) else 0
            if s != 0:
                sig, sig_idx = s, j
                break

    price = float(work["close"].iloc[i])
    st_val = float(work["supertrend"].iloc[i]) if pd.notna(work["supertrend"].iloc[i]) else None
    st_dir = int(work["st_direction"].iloc[i]) if pd.notna(work["st_direction"].iloc[i]) else 0
    color = "GREEN" if st_dir == 1 else ("RED" if st_dir == -1 else "—")

    want_long = sig == 1 and cfg.side in ("long", "both")
    want_short = sig == -1 and cfg.side in ("short", "both")

    checks = [
        {
            "id": "st_flip",
            "label": f"SuperTrend color flip (ATR {cfg.atr_length} · factor {cfg.factor:g})",
            "passed": sig != 0,
            "detail": (
                "GREEN flip → LONG"
                if sig == 1
                else "RED flip → SHORT"
                if sig == -1
                else f"current {color} — wait for fresh flip"
            ),
        },
        {
            "id": "preset",
            "label": f"{cfg.timeframe} · SL {cfg.sl_pct:g}% · TP {cfg.tp_pct:g}%",
            "passed": True,
            "detail": (
                f"preset {ticker_n}"
                if pre
                else f"no preset — ATR {cfg.atr_length} / factor {cfg.factor:g}"
            ),
        },
    ]
    out["checks"] = checks
    out["ltp"] = _r(price)
    out["metrics"] = {
        "price": _r(price),
        "supertrend": _r(st_val) if st_val is not None else None,
        "st_color": color,
        "st_direction": st_dir,
        "atr_length": cfg.atr_length,
        "factor": cfg.factor,
        "sl_pct": cfg.sl_pct,
        "tp_pct": cfg.tp_pct,
    }
    out["chart_data"] = _build_chart(work, max_bars=int(cfg.chart_bars))
    out["chart_series"] = [
        {
            "key": "supertrend",
            "label": f"ST ({cfg.atr_length}, {cfg.factor:g})",
            "color": "#34d399" if st_dir == 1 else "#f43f5e",
        },
    ]

    if not want_long and not want_short:
        out["signal"] = "WATCH" if st_dir != 0 else "WAIT"
        out["reason"] = "WAIT: " + checks[0]["detail"]
        out["plain_english"] = f"{ticker_n} {cfg.timeframe}: {out['reason']}"
        return out

    is_long = want_long
    direction = "LONG" if is_long else "SHORT"
    entry = float(work["close"].iloc[sig_idx])
    sl_pct = float(cfg.sl_pct)
    tp_pct = float(cfg.tp_pct)
    if is_long:
        stop = entry * (1.0 - sl_pct / 100.0)
        target = entry * (1.0 + tp_pct / 100.0)
    else:
        stop = entry * (1.0 + sl_pct / 100.0)
        target = entry * (1.0 - tp_pct / 100.0)

    # Structural reference: SuperTrend line at signal bar
    st_at_sig = (
        float(work["supertrend"].iloc[sig_idx])
        if pd.notna(work["supertrend"].iloc[sig_idx])
        else None
    )

    sl_pct_v, tp_pct_v = sl_tp_pct(direction, entry, stop, target)
    conf = 64.0
    if pre:
        conf += 6
    if st_at_sig is not None:
        conf += 2
    conf = min(85.0, conf)
    take = conf >= float(cfg.take_confidence_threshold)

    setup = pack_trade_setup(
        direction=direction,
        entry=entry,
        stop=stop,
        target=target,
        confidence_pct=conf,
        confidence_reasons=[
            f"SuperTrend {'GREEN' if is_long else 'RED'} flip · ATR {cfg.atr_length} / {cfg.factor:g}",
            f"SL {sl_pct:g}% · TP {tp_pct:g}% · invalidate on opposite color",
        ],
        reason=(
            f"{'BUY' if is_long else 'SELL'} SuperTrend flip · {cfg.timeframe} · "
            f"ATR {cfg.atr_length}/{cfg.factor:g} · SL {sl_pct:g}% / TP {tp_pct:g}%"
        ),
        plain_english=(
            f"{'Buy' if is_long else 'Sell'} {ticker_n} on {cfg.timeframe}: "
            f"SuperTrend turned {'GREEN' if is_long else 'RED'}. "
            f"Stop {sl_pct:g}% ({_r(stop)}); target {tp_pct:g}% ({_r(target)}). "
            f"Also exit if SuperTrend flips color."
        ),
        timeframe=cfg.timeframe,
        grade="A" if conf >= 70 else "B",
        take_trade=take,
    )

    plan = make_trade_plan(
        direction=direction,
        timeframe=cfg.timeframe,
        stop_loss_pct=round(sl_pct_v or sl_pct, 2),
        take_profit_pct=round(tp_pct_v or tp_pct, 2),
        confidence_pct=conf,
        style="intraday",
        exit_rule=(
            f"SL {sl_pct:g}% ({_r(stop)}); TP {tp_pct:g}% ({_r(target)}). "
            f"Invalidate when SuperTrend flips {'RED' if is_long else 'GREEN'}."
        ),
        max_hold_exit=f"Trail with SuperTrend line after partial TP on {cfg.timeframe}.",
    )

    levels = [
        {"label": "Entry", "price": _r(entry), "color": "#38bdf8"},
        {"label": f"SL {sl_pct:g}%", "price": _r(stop), "color": "#f43f5e"},
        {"label": f"TP {tp_pct:g}%", "price": _r(target), "color": "#34d399"},
    ]
    if st_at_sig is not None:
        levels.append({
            "label": "ST line",
            "price": _r(st_at_sig),
            "color": "#a78bfa",
        })
    out["chart_levels"] = levels
    out.update({
        "take_trade": take,
        "direction": direction,
        "signal": "BULLISH" if is_long else "BEARISH",
        "action": "BUY" if is_long else "SELL",
        "status": "take" if take else "setup_low_conf",
        "reason": setup["reason"],
        "entry_price": _r(entry),
        "stop_price": _r(stop),
        "target_price": _r(target),
        "supertrend_price": _r(st_at_sig) if st_at_sig is not None else None,
        "sl_pct": sl_pct_v or sl_pct,
        "tp_pct": tp_pct_v or tp_pct,
        "confidence_pct": conf,
        "grade": setup.get("grade"),
        "trade_plan": plan,
        "trade_setup": setup,
        "trade_suggestion": {
            "action": "BUY" if is_long else "SELL",
            "entry": _r(entry),
            "stop": _r(stop),
            "target": _r(target),
            "sl_pct": sl_pct,
            "tp_pct": tp_pct,
            "atr_length": cfg.atr_length,
            "factor": cfg.factor,
            "timeframe": cfg.timeframe,
        },
        "plain_english": setup["plain_english"],
        "pro_checklist": [
            f"SuperTrend turns {'GREEN' if is_long else 'RED'}",
            f"TF {cfg.timeframe} · ATR {cfg.atr_length} · factor {cfg.factor:g}",
            f"SL {sl_pct:g}% · Target {tp_pct:g}% · exit on opposite color",
        ],
    })
    return out


def scan_universe(
    *,
    cfg: SupertrendConfig | None = None,
    groww_token: str = "",
    exchange: str = "NSE",
    tickers: list[str] | None = None,
) -> dict[str, Any]:
    cfg = cfg or SupertrendConfig()
    if tickers:
        scan_list = [normalize_ticker(t) for t in dict.fromkeys(tickers)]
    else:
        scan_list = list(cfg.default_tickers)

    results: list[dict[str, Any]] = []

    def _one(t: str) -> dict[str, Any]:
        try:
            return analyze_ticker(t, cfg=cfg, groww_token=groww_token, exchange=exchange)
        except Exception as exc:
            logger.exception("%s failed for %s", STRATEGY_NAME, t)
            return {
                "ticker": t,
                "timeframe": (preset_for(t) or {}).get("timeframe", cfg.timeframe),
                "strategy": STRATEGY_ID,
                "error": str(exc)[:240],
                "signal": "WAIT",
                "take_trade": False,
            }

    if not scan_list:
        return {
            "strategy": STRATEGY_ID,
            "strategy_label": STRATEGY_NAME,
            "how_it_works": HOW_IT_WORKS,
            "rules": RULES,
            "pro_tips": PRO_TIPS,
            "presets": COIN_PRESETS,
            "results": [],
            "entry_count": 0,
            "scanned": 0,
            "error": "No tickers",
            "disclaimer": "Research / education only — not financial advice.",
        }

    workers = min(4, max(1, len(scan_list)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_one, t): t for t in scan_list}
        for fut in as_completed(futs):
            results.append(fut.result())

    results.sort(
        key=lambda r: (
            0 if r.get("take_trade") else 1,
            0 if r.get("signal") in ("BULLISH", "BEARISH") else 1,
            -(float(r.get("confidence_pct") or 0)),
        )
    )
    actionable = [r for r in results if r.get("take_trade")]
    return {
        "strategy": STRATEGY_ID,
        "strategy_label": STRATEGY_NAME,
        "how_it_works": HOW_IT_WORKS,
        "rules": RULES,
        "pro_tips": PRO_TIPS,
        "presets": [{"ticker": k, **v} for k, v in COIN_PRESETS.items()],
        "config": {
            "side": cfg.side,
            "default_tickers": cfg.default_tickers,
        },
        "results": results,
        "entry_count": len(actionable),
        "scanned": len(results),
        "asset_class": "crypto",
        "market": MARKET,
        "currency": "$",
        "disclaimer": (
            "Research / education only — not financial advice. "
            "S2 SuperTrend · per-coin ATR/factor/SL%/TP% (BTC/ETH/SOL/XRP · 1h)."
        ),
    }
