"""
ta_backtest_runner.py
---------------------
Run Technical Analysis hub strategies in Multi-Combo / batch backtest context.
Maps engine output to the standard Multi-Combo results row schema.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from backtesting.data_fetcher import get_historical_data
from app.market_pulse.engine import compute_performance_metrics
from app.market_pulse.fakeout_15m_engine import (
    normalize_ohlcv,
    run_fakeout_15m_backtest,
    session_mode_for_market,
)
from app.market_pulse.fakeout_4h_engine import FakeoutStrategy
from app.market_pulse.mtf_scanner_engine import TIMEFRAMES, analyze_ticker as analyze_mtf_ticker
from app.market_pulse.top_down_mtf_engine import analyze_top_down
from app.market_pulse.weekly_stoch_sweet_spot_engine import analyze_weekly_stoch

TA_STRATEGY_OPTIONS: dict[str, str] = {
    "fakeout_15m": "[TA] 1min–15min Breakout Fakeout",
    "fakeout_4h": "[TA] 5min–4h Breakout Fakeout",
    "mtf_scanner": "[TA] MTF Scanner (7-Component)",
    "top_down_mtf": "[TA] Top-Down MTF SMC",
    "weekly_stoch": "[TA] Weekly Stoch Sweet Spot",
    "kn_smart_rsi": "[TA] KN Smart DP SL + RSI MTF",
}

TA_STRATEGY_DEFAULTS = ["weekly_stoch", "fakeout_4h", "top_down_mtf"]


def _error_row(ticker: str, timeframe: str, strategy: str, message: str) -> dict:
    return {
        "Ticker": ticker,
        "Timeframe": timeframe,
        "Strategy": strategy,
        "Return %": None,
        "CAGR %": None,
        "Sharpe": None,
        "Max DD %": None,
        "Win Rate %": None,
        "Trades": 0,
        "Profit Factor": None,
        "Final Capital": None,
        "Status": f"⚠️ {message[:50]}",
        "_ta_module": True,
    }


def _metrics_to_row(
    ticker: str,
    timeframe: str,
    strategy: str,
    metrics: dict,
    *,
    phase: str = "",
    confidence: float | None = None,
    scan_only: bool = False,
) -> dict:
    status = "✅ SCAN" if scan_only else "✅ OK"
    row = {
        "Ticker": ticker,
        "Timeframe": timeframe,
        "Strategy": strategy,
        "Return %": metrics.get("total_return_pct", 0),
        "CAGR %": metrics.get("cagr_pct", 0),
        "Sharpe": metrics.get("sharpe_ratio", 0),
        "Max DD %": metrics.get("max_drawdown_pct", 0),
        "Win Rate %": metrics.get("win_rate_pct", 0),
        "Trades": metrics.get("n_trades", 0),
        "Profit Factor": metrics.get("profit_factor", 0),
        "Final Capital": metrics.get("final_capital", 0),
        "Status": status,
        "_ta_module": True,
    }
    if phase:
        row["Phase"] = phase
    if confidence is not None:
        row["Confidence"] = round(float(confidence), 1)
    return row


def _r_multiples_to_metrics(
    summary: dict,
    trades_df: pd.DataFrame,
    initial_capital: float,
    risk_pct: float = 1.0,
) -> dict:
    """Convert fakeout R-multiple backtest to standard performance metrics."""
    if summary.get("error") or trades_df.empty:
        return {
            "total_return_pct": 0,
            "cagr_pct": 0,
            "sharpe_ratio": 0,
            "max_drawdown_pct": 0,
            "win_rate_pct": 0,
            "n_trades": 0,
            "profit_factor": 0,
            "final_capital": initial_capital,
        }

    capital = initial_capital
    equity_vals = [capital]
    trade_records = []
    completed = trades_df[trades_df["result"].isin(["win", "loss", "timeout"])]
    for _, t in completed.iterrows():
        pnl_r = float(t.get("pnl_r") or 0)
        risk_amt = capital * (risk_pct / 100.0)
        pnl_val = pnl_r * risk_amt
        pnl_pct = (pnl_val / capital * 100.0) if capital else 0.0
        capital += pnl_val
        equity_vals.append(capital)
        trade_records.append({
            "pnl_val": pnl_val,
            "pnl_pct": pnl_pct,
            "duration_days": 0,
        })

    equity = pd.Series(equity_vals)
    trades_out = pd.DataFrame(trade_records)
    metrics = compute_performance_metrics(equity, trades_out, initial_capital)
    if metrics.get("n_trades", 0) == 0:
        metrics["win_rate_pct"] = summary.get("win_rate_%", 0)
        metrics["n_trades"] = summary.get("total_trades", 0)
        total_r = float(summary.get("total_R", 0) or 0)
        metrics["total_return_pct"] = round(total_r * risk_pct, 2)
        metrics["final_capital"] = round(initial_capital * (1 + total_r * risk_pct / 100), 2)
    pf = summary.get("profit_factor")
    if pf not in (None, "∞") and metrics.get("profit_factor", 0) == 0:
        try:
            metrics["profit_factor"] = round(float(pf), 3)
        except (TypeError, ValueError):
            pass
    return metrics


def _weekly_trades_to_metrics(trades_df: pd.DataFrame, equity_series: pd.Series, initial_capital: float) -> dict:
    if trades_df.empty or equity_series.empty:
        return {}
    records = []
    for _, tr in trades_df.iterrows():
        entry = float(tr.get("entry_price") or 0)
        exit_p = float(tr.get("exit_price") or 0)
        pnl_pct = float(tr.get("pnl_pct") or 0)
        pnl_val = (exit_p - entry) / entry * initial_capital if entry else 0
        dur = 7
        try:
            dur = max((tr["exit_date"] - tr["entry_date"]).days, 1)
        except Exception:
            pass
        records.append({"pnl_val": pnl_val, "pnl_pct": pnl_pct, "duration_days": dur})
    return compute_performance_metrics(equity_series, pd.DataFrame(records), initial_capital)


def _kn_smart_to_metrics(result_df: pd.DataFrame, initial_capital: float, commission: float, slippage: float) -> dict:
    if result_df.empty or "signal" not in result_df.columns:
        return {}

    capital = initial_capital
    shares = 0.0
    entry_price = 0.0
    equity_vals = []
    trade_records = []

    for _, row in result_df.iterrows():
        price = float(row["close"])
        signal = row["signal"]

        if shares == 0 and signal == "BUY":
            entry_price = price * (1 + slippage)
            shares = (capital / entry_price) * (1 - commission)
            capital = 0.0
        elif shares > 0 and signal in ("EXIT", "SELL"):
            exit_price = price * (1 - slippage)
            proceeds = shares * exit_price * (1 - commission)
            pnl_val = proceeds - (shares * entry_price)
            pnl_pct = (exit_price - entry_price) / entry_price * 100 if entry_price else 0
            trade_records.append({"pnl_val": pnl_val, "pnl_pct": pnl_pct, "duration_days": 0})
            capital = proceeds
            shares = 0.0
            entry_price = 0.0

        equity_vals.append(capital + shares * price)

    if shares > 0 and entry_price:
        last_price = float(result_df.iloc[-1]["close"])
        proceeds = shares * last_price
        pnl_val = proceeds - (shares * entry_price)
        pnl_pct = (last_price - entry_price) / entry_price * 100
        trade_records.append({"pnl_val": pnl_val, "pnl_pct": pnl_pct, "duration_days": 0})
        capital = proceeds
        shares = 0.0

    equity = pd.Series(equity_vals, index=result_df.index)
    return compute_performance_metrics(equity, pd.DataFrame(trade_records), initial_capital)


def _period_label(start: date, end: date) -> str:
    years = max((end - start).days / 365.25, 0.5)
    if years >= 9:
        return "10y"
    if years >= 4:
        return "5y"
    return "2y"


def run_ta_strategy_row(
    module_key: str,
    ticker: str,
    *,
    market: str,
    groww_token: str,
    exchange: str,
    scan_start: date,
    scan_end: date,
    capital: float,
    commission: float,
    slippage: float,
    timeframes: list[str],
) -> dict:
    """Run one TA hub strategy for a ticker; returns a Multi-Combo-compatible row."""
    label = TA_STRATEGY_OPTIONS.get(module_key, module_key)
    session_mode = session_mode_for_market(market)

    try:
        if module_key == "fakeout_15m":
            df = normalize_ohlcv(
                get_historical_data(
                    symbol=ticker,
                    start_date=str(scan_start),
                    end_date=str(scan_end),
                    market=market,
                    timeframe="1m",
                    groww_token=groww_token,
                    groww_exchange=exchange,
                )
            )
            if df.empty or len(df) < 50:
                return _error_row(ticker, "1m", label, f"Insufficient 1m data ({len(df)} bars)")
            bt = run_fakeout_15m_backtest(df, session_mode=session_mode)
            summary = bt.summary()
            metrics = _r_multiples_to_metrics(summary, bt.df, capital)
            return _metrics_to_row(ticker, "1m", label, metrics)

        if module_key == "fakeout_4h":
            df = normalize_ohlcv(
                get_historical_data(
                    symbol=ticker,
                    start_date=str(scan_start),
                    end_date=str(scan_end),
                    market=market,
                    timeframe="5m",
                    groww_token=groww_token,
                    groww_exchange=exchange,
                )
            )
            if df.empty or len(df) < 50:
                return _error_row(ticker, "5m", label, f"Insufficient 5m data ({len(df)} bars)")
            bt = FakeoutStrategy(session_mode=session_mode).run(df)
            summary = bt.summary()
            metrics = _r_multiples_to_metrics(summary, bt.df, capital)
            return _metrics_to_row(ticker, "5m", label, metrics)

        if module_key == "weekly_stoch":
            period = _period_label(scan_start, scan_end)
            analysis = analyze_weekly_stoch(ticker, market, groww_token, exchange, period=period)
            if analysis.get("error"):
                return _error_row(ticker, "1w", label, analysis["error"])
            signals_df = analysis.get("signals_df")
            if signals_df is None or signals_df.empty:
                return _error_row(ticker, "1w", label, "No weekly signal data")
            from app.market_pulse.weekly_stoch_sweet_spot_engine import backtest as wstoch_backtest
            bt = wstoch_backtest(signals_df, capital)
            equity = pd.Series(bt["df"]["equity"].values, index=bt["df"].index)
            metrics = _weekly_trades_to_metrics(bt["trades"], equity, capital)
            if not metrics:
                wm = analysis.get("metrics") or {}
                metrics = {
                    "total_return_pct": wm.get("strategy_return_pct", 0),
                    "cagr_pct": wm.get("strategy_return_pct", 0),
                    "sharpe_ratio": 0,
                    "max_drawdown_pct": 0,
                    "win_rate_pct": wm.get("win_rate_pct", 0),
                    "n_trades": wm.get("total_trades", 0),
                    "profit_factor": 0,
                    "final_capital": wm.get("final_equity", capital),
                }
            return _metrics_to_row(
                ticker, "1w", label, metrics,
                phase=analysis.get("phase", ""),
                confidence=analysis.get("confidence"),
            )

        if module_key == "kn_smart_rsi":
            intraday_tf = "5m" if "5m" in timeframes else ("15m" if "15m" in timeframes else "5m")
            mtf_tfs = [tf for tf in ("1m", "5m", "15m", "1h") if tf in timeframes] or list(MTF_DEFAULT)
            intraday = get_historical_data(
                symbol=ticker,
                start_date=str(scan_start),
                end_date=str(scan_end),
                market=market,
                timeframe=intraday_tf,
                groww_token=groww_token,
                groww_exchange=exchange,
            )
            daily = get_historical_data(
                symbol=ticker,
                start_date=str(scan_start),
                end_date=str(scan_end),
                market=market,
                timeframe="1d",
                groww_token=groww_token,
                groww_exchange=exchange,
            )
            min_bars = StrategyConfig().slow_ema + StrategyConfig().rsi_length + 10
            if intraday.empty or len(intraday) < min_bars:
                return _error_row(ticker, intraday_tf, label, f"Insufficient {intraday_tf} data")
            if daily.empty or len(daily) < 25:
                return _error_row(ticker, intraday_tf, label, "Insufficient daily data for VWMA")

            mtf_dfs: dict[str, pd.DataFrame] = {}
            for tf in mtf_tfs:
                mtf_dfs[tf] = normalize_ohlcv(
                    get_historical_data(
                        symbol=ticker,
                        start_date=str(scan_start),
                        end_date=str(scan_end),
                        market=market,
                        timeframe=tf,
                        groww_token=groww_token,
                        groww_exchange=exchange,
                    )
                )

            result_df = Strategy().run(
                normalize_ohlcv(intraday),
                normalize_ohlcv(daily),
                {k: normalize_ohlcv(v) for k, v in mtf_dfs.items()},
            )
            metrics = _kn_smart_to_metrics(result_df, capital, commission, slippage)
            if not metrics:
                return _error_row(ticker, intraday_tf, label, "No KN Smart signals in range")
            phase = str(result_df.iloc[-1].get("signal", "HOLD")) if not result_df.empty else ""
            return _metrics_to_row(ticker, intraday_tf, label, metrics, phase=phase)

        if module_key == "mtf_scanner":
            mtf_tfs = [tf for tf in timeframes if tf in TIMEFRAMES] or ["15m", "1h", "4h", "1d"]
            analysis = analyze_mtf_ticker(ticker, mtf_tfs, market, groww_token, exchange, 300)
            if not analysis.get("timeframes"):
                return _error_row(ticker, "MTF", label, "No timeframe had sufficient data")
            conf = analysis.get("confluence") or {}
            avg_score = float(conf.get("avg_score", 50) or 50)
            avg_conf = float(conf.get("avg_confidence", 0) or 0)
            pseudo_return = round((avg_score - 50) * 0.2, 2)
            metrics = {
                "total_return_pct": pseudo_return,
                "cagr_pct": pseudo_return,
                "sharpe_ratio": round(avg_conf / 50, 3),
                "max_drawdown_pct": 0,
                "win_rate_pct": avg_score,
                "n_trades": conf.get("total_tfs", 0),
                "profit_factor": round(avg_score / 50, 3),
                "final_capital": capital,
            }
            tf_label = "+".join(mtf_tfs[:3])
            return _metrics_to_row(
                ticker, tf_label, label, metrics,
                phase=conf.get("verdict_type", "mixed"),
                confidence=avg_conf,
                scan_only=True,
            )

        if module_key == "top_down_mtf":
            htf = "15m" if "15m" in timeframes else (timeframes[0] if timeframes else "15m")
            mtf = "5m" if "5m" in timeframes else htf
            ltf = "1m" if "1m" in timeframes else mtf
            analysis = analyze_top_down(ticker, htf, mtf, ltf, market, groww_token, exchange, 300)
            if analysis.get("error"):
                return _error_row(ticker, f"{htf}/{mtf}/{ltf}", label, analysis["error"])
            confidence = float(analysis.get("confidence", 0) or 0)
            pseudo_return = round((confidence - 50) * 0.15, 2)
            metrics = {
                "total_return_pct": pseudo_return,
                "cagr_pct": pseudo_return,
                "sharpe_ratio": round(confidence / 60, 3),
                "max_drawdown_pct": 0,
                "win_rate_pct": confidence,
                "n_trades": 0,
                "profit_factor": round(confidence / 50, 3),
                "final_capital": capital,
            }
            tf_label = f"{htf}/{mtf}/{ltf}"
            return _metrics_to_row(
                ticker, tf_label, label, metrics,
                phase=analysis.get("phase", ""),
                confidence=confidence,
                scan_only=True,
            )

    except Exception as exc:
        return _error_row(ticker, "—", label, str(exc))

    return _error_row(ticker, "—", label, f"Unknown TA module: {module_key}")


def count_ta_combos(selected_modules: list[str], tickers: list[str]) -> int:
    """TA strategies run once per ticker (not per timeframe)."""
    return len(selected_modules) * len(tickers)
