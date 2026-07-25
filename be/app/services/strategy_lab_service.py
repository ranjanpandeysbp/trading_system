"""Strategy Lab — builder backtest, presets, multi-combo, advanced screener."""

from __future__ import annotations

import asyncio
from typing import Any

from app.market_pulse.asset_class_config import ASSET_CLASS_CONFIG
from app.market_pulse.engine import run_true_backtest
from app.market_pulse.gap_trading import fetch_data_for_gap_scan
from app.market_pulse.groww_auth import set_groww_token
from app.market_pulse.indicators import calculate_dynamic_indicators
from app.market_pulse.mtf_scanner_engine import normalize_ohlcv
from app.market_pulse.presets import get_presets_by_category, get_presets_for_market
from app.market_pulse.serialize import json_safe
from app.market_pulse.signal_eval import eval_rules_on_last_bar
from app.services.settings_service import SettingsService

_TF_DAYS = {"1m": 7, "3m": 30, "5m": 60, "15m": 60, "30m": 90, "1h": 180, "4h": 365, "1d": 730}

# Real default when no preset / no custom rules are supplied (matches FE "RSI mean-reversion").
_DEFAULT_INDICATORS = [
    {"type": "rsi", "period": 14},
    {"type": "ema", "period": 20},
]
_DEFAULT_ENTRY = [
    {"left": "rsi_14", "op": "<", "right_type": "value", "right_val": "35"},
]
_DEFAULT_EXIT = [
    {"left": "rsi_14", "op": ">", "right_type": "value", "right_val": "65"},
]

# Soft default for multi-combo when strategies list is empty (never auto-run entire catalog).
_DEFAULT_COMBO_STRATEGY_COUNT = 5

_SCREENER_PRESETS: dict[str, dict[str, Any]] = {
    "rsi_oversold": {
        "label": "RSI Oversold (<35)",
        "indicators": _DEFAULT_INDICATORS,
        "entry_rules": _DEFAULT_ENTRY,
    },
    "rsi_overbought": {
        "label": "RSI Overbought (>65)",
        "indicators": _DEFAULT_INDICATORS,
        "entry_rules": [
            {"left": "rsi_14", "op": ">", "right_type": "value", "right_val": "65"},
        ],
    },
    "above_ema20": {
        "label": "Price above EMA 20",
        "indicators": [{"type": "ema", "period": 20}],
        "entry_rules": [
            {"left": "close", "op": ">", "right_type": "indicator", "right_val": "ema_20"},
        ],
    },
    "below_ema20": {
        "label": "Price below EMA 20",
        "indicators": [{"type": "ema", "period": 20}],
        "entry_rules": [
            {"left": "close", "op": "<", "right_type": "indicator", "right_val": "ema_20"},
        ],
    },
}


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

    async def _asset_ctx(self, asset_class: str | None = None, market: str | None = None) -> tuple[str, str, str]:
        """Return (market, groww_token, exchange). Prefer explicit market, else asset_class, else settings."""
        token = await self.settings.get_groww_token() or ""
        if market:
            resolved_market = market
            ac = "india"
            for key, cfg in ASSET_CLASS_CONFIG.items():
                if str(cfg["market"]) == market:
                    ac = key
                    break
        else:
            ac = asset_class or "india"
            cfg = ASSET_CLASS_CONFIG.get(ac) or ASSET_CLASS_CONFIG["india"]
            resolved_market = str(cfg["market"])

        if ac == "india":
            exchange = await self.settings.get_groww_exchange()
        else:
            cfg = ASSET_CLASS_CONFIG.get(ac) or ASSET_CLASS_CONFIG["india"]
            exchange = str(cfg.get("exchange") or "NSE")
        return resolved_market, token, exchange

    async def presets(self, market: str | None = None, asset_class: str | None = None) -> dict[str, Any]:
        resolved_market, _, _ = await self._asset_ctx(asset_class=asset_class, market=market)
        by_cat = get_presets_by_category(resolved_market)
        flat = get_presets_for_market(resolved_market)
        from app.market_pulse.section_strategy_guides import SECTION_GUIDES

        guides = {
            key: SECTION_GUIDES[key]
            for key in (
                "strategy_builder",
                "multi_combo",
                "screener",
                "strategy_encyclopedia",
                "saved_strategies",
            )
            if key in SECTION_GUIDES
        }
        return {
            "market": resolved_market,
            "asset_class": asset_class or "india",
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
            "guides": guides,
            "screener_presets": {
                k: {"label": v["label"]} for k, v in _SCREENER_PRESETS.items()
            },
            "count": len(flat),
        }

    async def backtest(self, payload: dict[str, Any]) -> dict[str, Any]:
        asset_class = payload.get("asset_class") or "india"
        market, token, exchange = await self._asset_ctx(
            asset_class=asset_class,
            market=payload.get("market"),
        )

        def _run():
            set_groww_token(token)
            ticker = str(payload["ticker"]).upper()
            tf = payload.get("timeframe", "1d")
            indicators = list(payload.get("indicators") or [])
            entry_rules = list(payload.get("entry_rules") or [])
            exit_rules = list(payload.get("exit_rules") or [])
            preset_name = payload.get("preset_name")

            if preset_name:
                preset = get_presets_for_market(market).get(preset_name)
                if not preset:
                    raise ValueError(f"Unknown preset: {preset_name}")
                indicators = preset["indicators"]
                entry_rules = preset["entry_rules"]
                exit_rules = preset.get("exit_rules") or []
                tf = payload.get("timeframe") or preset.get("recommended_timeframe", "1d")
            elif not indicators or not entry_rules:
                # Real RSI mean-reversion default (not an empty / no-op ruleset).
                indicators = list(_DEFAULT_INDICATORS)
                entry_rules = list(_DEFAULT_ENTRY)
                exit_rules = list(_DEFAULT_EXIT)

            days = int(payload.get("days") or _period_for_tf(tf))
            df = _fetch_bars(ticker, tf, market, token, exchange, days)
            if df.empty or len(df) < 30:
                raise ValueError(f"Insufficient data for {ticker} ({tf})")

            df = calculate_dynamic_indicators(df, indicators)
            entry_mode = payload.get("entry_mode", "AND")
            exit_mode = payload.get("exit_mode", "AND")

            direction_mode = payload.get("direction_mode", "long_only")
            if direction_mode == "short_only":
                long_entry, long_exit = [], []
                short_entry, short_exit = entry_rules, exit_rules
                short_entry_mode, short_exit_mode = entry_mode, exit_mode
            elif direction_mode == "long_short":
                long_entry, long_exit = entry_rules, exit_rules
                short_entry, short_exit = exit_rules, entry_rules
                short_entry_mode, short_exit_mode = exit_mode, entry_mode
            else:
                long_entry, long_exit = entry_rules, exit_rules
                short_entry, short_exit = None, None
                short_entry_mode, short_exit_mode = "AND", "AND"

            result = run_true_backtest(
                df,
                long_entry,
                long_exit,
                entry_mode=entry_mode,
                exit_mode=exit_mode,
                initial_capital=float(payload.get("capital", 100_000)),
                commission=float(payload.get("commission", 0.001)),
                slippage=float(payload.get("slippage", 0.0005)),
                sl_pct=float(payload.get("sl_pct") or 0),
                tp_pct=float(payload.get("tp_pct") or 0),
                short_entry_rules=short_entry,
                short_exit_rules=short_exit,
                short_entry_mode=short_entry_mode,
                short_exit_mode=short_exit_mode,
                position_sizing=payload.get("position_sizing", "pct_of_capital"),
                capital_allocation_pct=float(payload.get("capital_allocation_pct") or 95.0),
                risk_pct=float(payload.get("risk_pct") or 1.0),
            )
            metrics = result.get("metrics") or {}
            trades = result.get("trades")
            trade_list = trades.to_dict(orient="records") if trades is not None and not trades.empty else []
            return {
                "ticker": ticker,
                "timeframe": tf,
                "market": market,
                "asset_class": asset_class,
                "preset_name": preset_name or "RSI mean-reversion (default)",
                "metrics": metrics,
                "trades": trade_list[-50:],
                "trade_count": len(trade_list),
            }

        return json_safe(await asyncio.to_thread(_run))

    async def multi_combo(self, payload: dict[str, Any]) -> dict[str, Any]:
        asset_class = payload.get("asset_class") or "india"
        market, token, exchange = await self._asset_ctx(
            asset_class=asset_class,
            market=payload.get("market"),
        )
        # No ticker count limit — scan the full list.
        tickers = list(dict.fromkeys(
            t.strip().upper() for t in (payload.get("tickers") or []) if t and str(t).strip()
        ))
        timeframes = payload.get("timeframes") or ["1d"]
        strategy_names = [s for s in (payload.get("strategies") or []) if s]
        all_presets = get_presets_for_market(market)
        if not strategy_names:
            strategy_names = list(all_presets.keys())[:_DEFAULT_COMBO_STRATEGY_COUNT]

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
                            })
                        except Exception as exc:
                            rows.append({
                                "Ticker": ticker, "Timeframe": tf, "Strategy": strat,
                                "Status": str(exc)[:80],
                            })
            rows.sort(key=lambda r: float(r.get("Return %") or -999), reverse=True)
            return {
                "market": market,
                "asset_class": asset_class,
                "ticker_count": len(tickers),
                "strategy_count": len(strategy_names),
                "rows": rows,
                "count": len(rows),
            }

        return json_safe(await asyncio.to_thread(_run))

    async def screener_scan(self, payload: dict[str, Any]) -> dict[str, Any]:
        asset_class = payload.get("asset_class") or "india"
        market, token, exchange = await self._asset_ctx(
            asset_class=asset_class,
            market=payload.get("market"),
        )
        # No ticker count limit — scan the full list.
        tickers = list(dict.fromkeys(
            t.strip().upper() for t in (payload.get("tickers") or []) if t and str(t).strip()
        ))
        timeframes = payload.get("timeframes") or ["1d"]

        screener_preset = payload.get("screener_preset") or ""
        if screener_preset and screener_preset in _SCREENER_PRESETS:
            sp = _SCREENER_PRESETS[screener_preset]
            indicators = list(sp["indicators"])
            entry_rules = list(sp["entry_rules"])
        else:
            indicators = payload.get("indicators") or list(_DEFAULT_INDICATORS)
            entry_rules = payload.get("entry_rules") or list(_DEFAULT_ENTRY)

        entry_mode = payload.get("entry_mode", "AND")

        def _run():
            set_groww_token(token)
            hits: list[dict] = []
            for tf in timeframes:
                for ticker in tickers:
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
                                "Signal": "BUY" if screener_preset != "rsi_overbought" else "SELL",
                            })
                    except Exception:
                        continue
            return {
                "market": market,
                "asset_class": asset_class,
                "screener_preset": screener_preset or "custom",
                "ticker_count": len(tickers),
                "signals": hits,
                "count": len(hits),
            }

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
