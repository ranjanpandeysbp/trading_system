"""Strategy Lab — builder backtest, presets, multi-combo, advanced screener."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any

from app.market_pulse.engine import run_true_backtest
from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.groww_auth import set_groww_token
from app.market_pulse.indicators import calculate_dynamic_indicators
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.presets import get_presets_by_category, get_presets_for_market
from app.market_pulse.serialize import json_safe
from app.market_pulse.signal_eval import eval_rules_on_last_bar
from app.services.settings_service import SettingsService

_TF_DAYS = {"1m": 7, "5m": 60, "15m": 60, "30m": 90, "1h": 180, "4h": 365, "1d": 730}


def _period_for_tf(tf: str, lookback: int = 200) -> int:
    base = _TF_DAYS.get(tf, 60)
    return min(base, max(7, lookback // 5))


def _fetch_bars(ticker: str, tf: str, market: str, token: str, exchange: str, days: int):
    limit = min(5000, max(100, days * 75 if tf == "5m" else days * 25 if tf == "15m" else days))
    df = fetch_data_for_gap_scan(ticker, tf, market, token, exchange, limit=limit)
    return normalize_ohlcv(df)


class StrategyLabService:
    def __init__(self, settings: SettingsService):
        self.settings = settings

    async def presets(self, market: str | None = None) -> dict[str, Any]:
        market = market or await self.settings.get_default_market()
        by_cat = get_presets_by_category(market)
        flat = get_presets_for_market(market)
        return {
            "market": market,
            "categories": {k: list(v.keys()) for k, v in by_cat.items()},
            "presets": {
                name: {
                    "description": p.get("description", ""),
                    "recommended_timeframe": p.get("recommended_timeframe", "1d"),
                    "recommended_sl": p.get("recommended_sl"),
                    "recommended_tp": p.get("recommended_tp"),
                }
                for name, p in flat.items()
            },
            "count": len(flat),
        }

    async def backtest(self, payload: dict[str, Any]) -> dict[str, Any]:
        market = payload.get("market") or await self.settings.get_default_market()
        token = await self.settings.get_groww_token() or ""
        exchange = await self.settings.get_groww_exchange()

        def _run():
            set_groww_token(token)
            ticker = str(payload["ticker"]).upper()
            tf = payload.get("timeframe", "1d")
            indicators = payload.get("indicators") or []
            entry_rules = payload.get("entry_rules") or []
            exit_rules = payload.get("exit_rules") or []
            preset_name = payload.get("preset_name")

            if preset_name:
                preset = get_presets_for_market(market).get(preset_name)
                if not preset:
                    raise ValueError(f"Unknown preset: {preset_name}")
                indicators = preset["indicators"]
                entry_rules = preset["entry_rules"]
                exit_rules = preset.get("exit_rules") or []
                tf = payload.get("timeframe") or preset.get("recommended_timeframe", "1d")

            days = int(payload.get("days") or _period_for_tf(tf))
            df = _fetch_bars(ticker, tf, market, token, exchange, days)
            if df.empty or len(df) < 30:
                raise ValueError(f"Insufficient data for {ticker} ({tf})")

            df = calculate_dynamic_indicators(df, indicators)
            result = run_true_backtest(
                df,
                entry_rules,
                exit_rules,
                entry_mode=payload.get("entry_mode", "AND"),
                exit_mode=payload.get("exit_mode", "AND"),
                initial_capital=float(payload.get("capital", 100_000)),
                commission=float(payload.get("commission", 0.001)),
                slippage=float(payload.get("slippage", 0.0005)),
                sl_pct=float(payload.get("sl_pct") or 0),
                tp_pct=float(payload.get("tp_pct") or 0),
            )
            metrics = result.get("metrics") or {}
            trades = result.get("trades")
            trade_list = trades.to_dict(orient="records") if trades is not None and not trades.empty else []
            return {
                "ticker": ticker,
                "timeframe": tf,
                "market": market,
                "metrics": metrics,
                "trades": trade_list[-50:],
                "trade_count": len(trade_list),
            }

        return json_safe(await asyncio.to_thread(_run))

    async def multi_combo(self, payload: dict[str, Any]) -> dict[str, Any]:
        market = payload.get("market") or await self.settings.get_default_market()
        tickers = [t.upper() for t in payload.get("tickers") or []][:10]
        timeframes = payload.get("timeframes") or ["1d"]
        strategy_names = payload.get("strategies") or []
        token = await self.settings.get_groww_token() or ""
        exchange = await self.settings.get_groww_exchange()
        all_presets = get_presets_for_market(market)
        if not strategy_names:
            strategy_names = list(all_presets.keys())[:5]

        def _run():
            set_groww_token(token)
            rows: list[dict] = []
            for strat in strategy_names:
                preset = all_presets.get(strat)
                if not preset:
                    continue
                for ticker in tickers:
                    for tf in timeframes:
                        try:
                            days = _period_for_tf(tf)
                            df = _fetch_bars(ticker, tf, market, token, exchange, days)
                            if df.empty or len(df) < 30:
                                rows.append({
                                    "Ticker": ticker, "Timeframe": tf, "Strategy": strat,
                                    "Status": "NO DATA", "Return %": None,
                                })
                                continue
                            df = calculate_dynamic_indicators(df, preset["indicators"])
                            bt = run_true_backtest(
                                df, preset["entry_rules"], preset.get("exit_rules") or [],
                                initial_capital=float(payload.get("capital", 100_000)),
                                commission=float(payload.get("commission", 0.001)),
                            )
                            m = bt.get("metrics") or {}
                            rows.append({
                                "Ticker": ticker,
                                "Timeframe": tf,
                                "Strategy": strat,
                                "Return %": m.get("total_return_pct"),
                                "CAGR %": m.get("cagr_pct"),
                                "Sharpe": m.get("sharpe_ratio"),
                                "Max DD %": m.get("max_drawdown_pct"),
                                "Win Rate %": m.get("win_rate_pct"),
                                "Trades": m.get("n_trades"),
                                "Status": "OK",
                                "_indicators": preset["indicators"],
                                "_entry_rules": preset["entry_rules"],
                                "_exit_rules": preset.get("exit_rules") or [],
                            })
                        except Exception as exc:
                            rows.append({
                                "Ticker": ticker, "Timeframe": tf, "Strategy": strat,
                                "Status": str(exc)[:80],
                            })
            rows.sort(key=lambda r: float(r.get("Return %") or -999), reverse=True)
            return {"market": market, "rows": rows, "count": len(rows)}

        return json_safe(await asyncio.to_thread(_run))

    async def screener_scan(self, payload: dict[str, Any]) -> dict[str, Any]:
        market = payload.get("market") or await self.settings.get_default_market()
        tickers = [t.upper() for t in payload.get("tickers") or []]
        timeframes = payload.get("timeframes") or ["1d"]
        indicators = payload.get("indicators") or [{"type": "rsi", "period": 14}, {"type": "ema", "period": 20}]
        entry_rules = payload.get("entry_rules") or [
            {"left": "rsi_14", "op": "<", "right_type": "value", "right_val": "35"},
        ]
        entry_mode = payload.get("entry_mode", "AND")
        token = await self.settings.get_groww_token() or ""
        exchange = await self.settings.get_groww_exchange()

        def _run():
            set_groww_token(token)
            hits: list[dict] = []
            for tf in timeframes:
                for ticker in tickers[:20]:
                    try:
                        df = _fetch_bars(ticker, tf, market, token, exchange, _period_for_tf(tf))
                        if df.empty or len(df) < 15:
                            continue
                        df = calculate_dynamic_indicators(df, indicators)
                        if eval_rules_on_last_bar(df, entry_rules, mode=entry_mode):
                            last = df.iloc[-1]
                            hits.append({
                                "Ticker": ticker,
                                "Timeframe": tf,
                                "Close": round(float(last["close"]), 2),
                                "Volume": float(last.get("volume", 0)),
                                "Signal": "BUY",
                            })
                    except Exception:
                        continue
            return {"market": market, "signals": hits, "count": len(hits)}

        return json_safe(await asyncio.to_thread(_run))

    def sections(self) -> dict[str, Any]:
        return {
            "sections": [
                {"id": "builder", "label": "Strategy Builder & Tester"},
                {"id": "multi_combo", "label": "Multi-Combo Scanner"},
                {"id": "screener", "label": "Advanced Screener"},
                {"id": "presets", "label": "Strategy Encyclopedia (Presets)"},
            ]
        }
