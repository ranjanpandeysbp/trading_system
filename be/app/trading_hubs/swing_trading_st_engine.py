"""
swing_trading_st_engine.py
--------------------------
ST swing strategies (YouTube ST playbook):
  1. Mean Reversion Capitulation — oversold + volume spike + right side of the V
  2. Continuation Breakout — multi-month high break + MA trailing exit

Backtrader backtest + pandas live signal scan for Groww · CoinDCX · US.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Type

import numpy as np
import pandas as pd

from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.indicators import add_rsi
from app.market_pulse.run_summary import make_trade_plan
from app.trading_hubs.swing_trading_st_shared import (
    HOLD_CAPITULATION,
    HOLD_CONTINUATION,
    enrich_st_live,
)

logger = logging.getLogger(__name__)

STRATEGY_MEAN_REVERSION = "mean_reversion_capitulation"
STRATEGY_CONTINUATION = "continuation_breakout"

YOUTUBE_ST_URL = "https://www.youtube.com/watch?v=k-X0164r66U"


@dataclass
class STConfig:
    strategy: str = STRATEGY_CONTINUATION
    volume_period: int = 20
    volume_factor: float = 2.0
    rsi_period: int = 14
    rsi_lower: float = 30.0
    breakout_period: int = 60
    ma_period: int = 20
    risk_per_trade_pct: float = 1.0
    initial_cash: float = 100_000.0
    commission: float = 0.001
    min_bars: int = 80
    tp_risk_multiple: float = 2.5


def _normalize_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = [str(c[0]).lower() for c in out.columns]
    else:
        out.columns = [str(c).lower() for c in out.columns]
    for col in ("open", "high", "low", "close", "volume"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if "volume" not in out.columns or out["volume"].isna().all():
        out["volume"] = 1.0
    out = out.dropna(subset=["open", "high", "low", "close"], how="any")
    return out.reset_index(drop=True)


def _prepare_bt_df(df: pd.DataFrame) -> pd.DataFrame:
    """Backtrader PandasData feed — datetime index, OHLCV columns."""
    work = _normalize_ohlc(df)
    if work.empty:
        return work
    if "datetime" not in work.columns:
        work["datetime"] = pd.date_range(end=pd.Timestamp.utcnow(), periods=len(work), freq="D")
    work = work.set_index("datetime")
    return work[["open", "high", "low", "close", "volume"]].astype(float)


def _get_backtrader_strategies() -> tuple[Any, Any, Any]:
    import backtrader as bt

    class MeanReversionCapitulation(bt.Strategy):
        params = (
            ("volume_period", 20),
            ("volume_factor", 2.0),
            ("rsi_period", 14),
            ("rsi_lower", 30),
            ("risk_pct", 0.01),
        )

        def __init__(self):
            self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
            self.avg_volume = bt.indicators.SMA(self.data.volume, period=self.p.volume_period)
            self.order = None

        def next(self):
            if self.order:
                return
            if not self.position:
                capitulation = (
                    self.rsi[0] < self.p.rsi_lower
                    and self.data.volume[0] > self.avg_volume[0] * self.p.volume_factor
                )
                if capitulation and self.data.close[0] > self.data.high[-1]:
                    stop = self.data.low[0]
                    risk_per_share = self.data.close[0] - stop
                    if risk_per_share > 0:
                        risk_amount = self.broker.get_cash() * self.p.risk_pct
                        size = max(1, int(risk_amount / risk_per_share))
                        self.order = self.buy(size=size)
            elif self.data.close[0] < self.data.low[-1]:
                self.order = self.close()

    class ContinuationBreakout(bt.Strategy):
        params = (
            ("breakout_period", 60),
            ("ma_period", 20),
            ("risk_pct", 0.01),
        )

        def __init__(self):
            self.breakout_level = bt.indicators.Highest(self.data.high(-1), period=self.p.breakout_period)
            self.ma = bt.indicators.SMA(self.data.close, period=self.p.ma_period)
            self.order = None

        def next(self):
            if self.order:
                return
            if not self.position:
                if self.data.close[0] > self.breakout_level[0]:
                    stop = self.data.low[0]
                    risk_per_share = self.data.close[0] - stop
                    if risk_per_share > 0:
                        risk_amount = self.broker.get_cash() * self.p.risk_pct
                        size = max(1, int(risk_amount / risk_per_share))
                        self.order = self.buy(size=size)
            elif self.data.close[0] < self.ma[0]:
                self.order = self.close()

    return bt, MeanReversionCapitulation, ContinuationBreakout


def run_backtrader_backtest(df: pd.DataFrame, cfg: STConfig) -> dict[str, Any]:
    """Run cerebro backtest on historical OHLCV."""
    feed_df = _prepare_bt_df(df)
    if len(feed_df) < cfg.min_bars:
        return {"error": f"Need ≥{cfg.min_bars} daily bars (have {len(feed_df)})."}

    try:
        bt, MeanRev, ContBreak = _get_backtrader_strategies()
    except ImportError:
        return {"error": "backtrader not installed — pip install backtrader"}

    import backtrader as bt_mod

    cerebro = bt_mod.Cerebro()
    data = bt_mod.feeds.PandasData(dataname=feed_df)
    cerebro.adddata(data)

    risk_pct = cfg.risk_per_trade_pct / 100.0
    if cfg.strategy == STRATEGY_MEAN_REVERSION:
        cerebro.addstrategy(
            MeanRev,
            volume_period=cfg.volume_period,
            volume_factor=cfg.volume_factor,
            rsi_period=cfg.rsi_period,
            rsi_lower=cfg.rsi_lower,
            risk_pct=risk_pct,
        )
    else:
        cerebro.addstrategy(
            ContBreak,
            breakout_period=cfg.breakout_period,
            ma_period=cfg.ma_period,
            risk_pct=risk_pct,
        )

    cerebro.broker.setcash(cfg.initial_cash)
    cerebro.broker.setcommission(commission=cfg.commission)
    cerebro.addanalyzer(bt_mod.analyzers.TradeAnalyzer, _name="trades")
    cerebro.addanalyzer(bt_mod.analyzers.Returns, _name="returns")

    start_val = cerebro.broker.getvalue()
    results = cerebro.run()
    end_val = cerebro.broker.getvalue()
    strat = results[0]
    trade_an = strat.analyzers.trades.get_analysis()
    ret_an = strat.analyzers.returns.get_analysis()

    total_closed = trade_an.get("total", {}).get("closed", 0) if trade_an else 0
    won = trade_an.get("won", {}).get("total", 0) if trade_an else 0
    win_rate = (won / total_closed * 100) if total_closed else 0.0

    return {
        "start_value": round(start_val, 2),
        "end_value": round(end_val, 2),
        "pnl": round(end_val - start_val, 2),
        "pnl_pct": round((end_val - start_val) / start_val * 100, 2) if start_val else 0,
        "total_trades": int(total_closed),
        "win_rate_pct": round(win_rate, 1),
        "bars": len(feed_df),
    }


def _evaluate_mean_reversion(df: pd.DataFrame, cfg: STConfig) -> dict[str, Any]:
    work = _normalize_ohlc(df)
    if len(work) < cfg.volume_period + 5:
        return {"signal": "NO_DATA"}

    work = add_rsi(work, cfg.rsi_period)
    rsi_col = f"rsi_{cfg.rsi_period}"
    vol_ma = work["volume"].rolling(cfg.volume_period).mean()
    i = len(work) - 1
    row = work.iloc[i]
    prev = work.iloc[i - 1]

    rsi = float(row[rsi_col]) if pd.notna(row.get(rsi_col)) else 50.0
    vol = float(row["volume"])
    avg_vol = float(vol_ma.iloc[i]) if pd.notna(vol_ma.iloc[i]) else vol
    vol_spike = vol > avg_vol * cfg.volume_factor if avg_vol > 0 else False
    oversold = rsi < cfg.rsi_lower
    right_side_v = float(row["close"]) > float(prev["high"])
    capitulation = oversold and vol_spike

    price = float(row["close"])
    stop = float(row["low"])
    sl_pct = max(0.5, (price - stop) / price * 100) if price > 0 else 3.0
    tp_pct = max(sl_pct * cfg.tp_risk_multiple, sl_pct + 2.0)

    conf = 30.0
    reasons: list[str] = []
    if oversold:
        conf += 15
        reasons.append(f"RSI {rsi:.0f} oversold (<{cfg.rsi_lower})")
    if vol_spike:
        conf += 18
        reasons.append(f"Volume {vol/avg_vol:.1f}× average (capitulation spike)")
    if right_side_v and capitulation:
        conf += 22
        reasons.append("Right side of V — close above prior bar high")
        signal = "ENTRY"
        direction = "LONG"
        take = conf >= 58
    elif capitulation:
        conf += 8
        reasons.append("Capitulation forming — wait for close above prior high")
        signal = "WATCH"
        direction = "LONG"
        take = False
    else:
        signal = "NONE"
        direction = "WAIT"
        take = False

    conf = min(90, conf)
    return _trade_payload(
        signal=signal, direction=direction, take=take, confidence=conf,
        sl_pct=sl_pct, tp_pct=tp_pct, price=price, stop=stop,
        reasons=reasons, extra={"rsi": round(rsi, 1), "vol_ratio": round(vol / max(avg_vol, 1), 2), "hold_duration": HOLD_CAPITULATION},
    )


def _evaluate_continuation(df: pd.DataFrame, cfg: STConfig) -> dict[str, Any]:
    work = _normalize_ohlc(df)
    if len(work) < cfg.breakout_period + cfg.ma_period + 5:
        return {"signal": "NO_DATA"}

    i = len(work) - 1
    row = work.iloc[i]
    hist_high = work["high"].iloc[i - cfg.breakout_period: i].max()
    ma = work["close"].rolling(cfg.ma_period).mean().iloc[i]
    price = float(row["close"])
    stop = float(row["low"])
    breakout = price > float(hist_high) if pd.notna(hist_high) else False
    dist_pct = (price - float(hist_high)) / float(hist_high) * 100 if hist_high else 0

    sl_pct = max(0.8, (price - stop) / price * 100) if price > 0 else 4.0
    tp_pct = max(sl_pct * cfg.tp_risk_multiple, sl_pct + 3.0)

    conf = 35.0
    reasons: list[str] = []
    if breakout:
        conf += 25 + min(20, dist_pct * 2)
        reasons.append(f"Breakout above {cfg.breakout_period}-bar high ({dist_pct:+.2f}%)")
        signal = "ENTRY"
        direction = "LONG"
        take = conf >= 60
    elif price >= float(hist_high) * 0.97:
        conf += 15
        reasons.append(f"Approaching {cfg.breakout_period}-bar high — breakout watch")
        signal = "WATCH"
        direction = "LONG"
        take = False
    else:
        signal = "NONE"
        direction = "WAIT"
        take = False

    if pd.notna(ma) and price > float(ma):
        conf += 10
        reasons.append(f"Price above {cfg.ma_period}-period MA (trend support)")
    else:
        conf -= 5

    conf = max(25, min(88, conf))
    return _trade_payload(
        signal=signal, direction=direction, take=take, confidence=conf,
        sl_pct=sl_pct, tp_pct=tp_pct, price=price, stop=stop,
        reasons=reasons,
        extra={"breakout_level": round(float(hist_high), 4) if pd.notna(hist_high) else None, "ma20": round(float(ma), 4) if pd.notna(ma) else None, "hold_duration": HOLD_CONTINUATION},
    )


def _trade_payload(
    *,
    signal: str,
    direction: str,
    take: bool,
    confidence: float,
    sl_pct: float,
    tp_pct: float,
    price: float,
    stop: float,
    reasons: list[str],
    extra: dict | None = None,
) -> dict[str, Any]:
    dir_u = direction if direction in ("LONG", "SHORT", "WAIT") else "WAIT"
    verdict = "WAIT"
    if take and dir_u == "LONG":
        verdict = "TAKE LONG"
    elif take and dir_u == "SHORT":
        verdict = "TAKE SHORT"
    elif dir_u == "LONG":
        verdict = "WATCH LONG"
    tp_price = price * (1 + tp_pct / 100) if dir_u == "LONG" else price * (1 - tp_pct / 100)
    hold_duration = (extra or {}).get("hold_duration") or HOLD_CONTINUATION

    plan = make_trade_plan(
        direction=dir_u if take else "—",
        timeframe="1d",
        stop_loss_pct=round(sl_pct, 2),
        take_profit_pct=round(tp_pct, 2),
        confidence_pct=round(confidence, 1),
        style="swing",
        exit_rule="; ".join(reasons[:2]) if reasons else "ST swing rule",
        max_hold_exit=f"Exit if TP not reached within {hold_duration.split('(')[0].strip()}.",
    )
    payload = {
        "signal": signal,
        "direction": dir_u,
        "take_trade": take,
        "verdict": verdict,
        "confidence_pct": round(confidence, 1),
        "sl_pct": round(sl_pct, 2),
        "tp_pct": round(tp_pct, 2),
        "hold_duration": hold_duration,
        "rr_ratio": round(tp_pct / sl_pct, 2) if sl_pct > 0 else None,
        "entry_price": price,
        "stop_price": stop,
        "target_price": round(tp_price, 6),
        "reasons": reasons,
        "trade_plan": {**plan, "holding_period": hold_duration},
        **(extra or {}),
    }
    return enrich_st_live(payload, hold_duration=hold_duration)


def evaluate_live_signal(df: pd.DataFrame, cfg: STConfig) -> dict[str, Any]:
    if cfg.strategy == STRATEGY_MEAN_REVERSION:
        return _evaluate_mean_reversion(df, cfg)
    return _evaluate_continuation(df, cfg)


def analyze_ticker(
    ticker: str,
    market: str,
    *,
    cfg: STConfig,
    groww_token: str = "",
    exchange: str = "NSE",
    run_bt: bool = True,
) -> dict[str, Any]:
    limit = max(400, cfg.breakout_period + cfg.ma_period + 50)
    df = fetch_data_for_gap_scan(ticker, "1d", market, groww_token, exchange, limit=limit)
    df = _normalize_ohlc(df)
    if df.empty or len(df) < 30:
        return {"ticker": ticker, "error": "Insufficient daily OHLCV data."}

    live = evaluate_live_signal(df, cfg)
    result: dict[str, Any] = {
        "ticker": ticker,
        "market": market,
        "strategy": cfg.strategy,
        "bars": len(df),
        "last_close": float(df["close"].iloc[-1]),
        "live": live,
    }
    if run_bt:
        result["backtest"] = run_backtrader_backtest(df, cfg)
    return result


def scan_universe(
    tickers: list[str],
    market: str,
    *,
    cfg: STConfig,
    groww_token: str = "",
    exchange: str = "NSE",
    run_bt: bool = False,
) -> dict[str, Any]:
    results = []
    for ticker in tickers:
        try:
            results.append(
                analyze_ticker(
                    ticker, market, cfg=cfg, groww_token=groww_token,
                    exchange=exchange, run_bt=run_bt,
                ),
            )
        except Exception as exc:
            results.append({"ticker": ticker, "error": str(exc)[:200]})

    entries = [
        r for r in results
        if not r.get("error") and (r.get("live") or {}).get("take_trade")
    ]
    entries.sort(key=lambda x: -(x.get("live") or {}).get("confidence_pct", 0))

    return {
        "market": market,
        "strategy": cfg.strategy,
        "results": results,
        "entries": entries,
        "entry_count": len(entries),
    }
