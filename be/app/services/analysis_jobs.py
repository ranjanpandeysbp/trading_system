"""Generic background-job runner for analysis surfaces across the app
(Trading Hubs, Pro Trade, Command Center, Technical Analysis, Market Pulse,
Scanner, Seasonality, Trading Agent, Investing Agent).

Source keys are ``analysis:{domain}:{section}`` so reports stay scoped per
screen. Reuses the shared job store in ``strategy_leaderboard_jobs``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.services.strategy_leaderboard_jobs import (
    LeaderboardJob,
    complete_job,
    create_job,
    fail_job,
    get_job,
    list_jobs,
    update_progress,
)

logger = logging.getLogger(__name__)

__all__ = [
    "LeaderboardJob", "create_job", "get_job", "list_jobs", "update_progress",
    "complete_job", "fail_job", "run_analysis_job", "job_to_dict",
    "analysis_source", "is_analysis_source", "parse_analysis_source",
    "ANALYSIS_DOMAINS", "execute_analysis",
]

ANALYSIS_DOMAINS = frozenset({
    "trading_hub",
    "pro_trade",
    "command_center",
    "technical_analysis",
    "market_pulse",
    "scanner",
    "seasonality",
    "trading_agent",
    "investing_agent",
    "prediction",
})


def analysis_source(domain: str, section: str) -> str:
    return f"analysis:{domain}:{section}"


def is_analysis_source(source: str | None) -> bool:
    return bool(source) and source.startswith("analysis:")


def parse_analysis_source(source: str) -> tuple[str, str]:
    # analysis:{domain}:{section}  (section may itself contain colons — take rest)
    parts = source.split(":", 2)
    if len(parts) < 3:
        raise ValueError(f"Invalid analysis source: {source}")
    return parts[1], parts[2]


def job_to_dict(job: LeaderboardJob) -> dict[str, Any]:
    return {
        "job_id": job.id,
        "status": job.status,
        "progress": job.progress,
        "progress_note": job.progress_note,
        "result": job.result,
        "error": job.error,
        "name": job.name,
        "report_id": job.report_id,
        "source": job.source,
        "created_at": job.created_at,
        "meta": job.meta,
    }


def _tickers(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("tickers") or []
    return [str(t) for t in raw if t]


def _asset_class(payload: dict[str, Any]) -> str:
    return str(payload.get("asset_class") or "india")


def _timeframes(payload: dict[str, Any]) -> list[str] | None:
    tfs = payload.get("timeframes") or payload.get("durations")
    if not tfs:
        return None
    return [str(t) for t in tfs]


async def execute_analysis(
    domain: str,
    section: str,
    payload: dict[str, Any],
    *,
    settings: Any,
    db: Any,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Dispatch one analysis run. ``section`` is the tab/screener/strategy id."""
    from app.market_pulse.data_source_ctx import attach_data_source, clear_tracking, start_tracking

    start_tracking()
    try:
        if hasattr(settings, "prepare_market_data"):
            try:
                await settings.prepare_market_data()
            except Exception:
                logger.debug("prepare_market_data failed", exc_info=True)
        result = await _execute_analysis_body(
            domain, section, payload, settings=settings, db=db, user_id=user_id,
        )
        return attach_data_source(result) if isinstance(result, dict) else result
    finally:
        clear_tracking()


async def _execute_analysis_body(
    domain: str,
    section: str,
    payload: dict[str, Any],
    *,
    settings: Any,
    db: Any,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Dispatch one analysis run. ``section`` is the tab/screener/strategy id."""
    if domain == "trading_hub":
        from app.services.trading_hub_service import TradingHubService

        svc = TradingHubService(settings, db)
        if section == "swing_5_strategies":
            return await svc.scan_swing5(
                _tickers(payload),
                _timeframes(payload) or ["1d"],
                payload.get("strategies") or payload.get("strategy_keys") or [],
                asset_class=_asset_class(payload),
                config=payload.get("config"),
            )
        return await svc.scan(
            section,
            _tickers(payload),
            asset_class=_asset_class(payload),
            config=payload.get("config"),
            run_bt=bool(payload.get("run_backtest")),
            user_id=user_id,
        )

    if domain == "pro_trade":
        from app.services.pro_trade_service import ProTradeService

        svc = ProTradeService(settings, db)
        tickers = _tickers(payload)
        ac = _asset_class(payload)
        exchange = payload.get("exchange")
        # Strip meta keys; remaining become cfg_overrides when relevant.
        cfg = {
            k: v for k, v in payload.items()
            if k not in {
                "tickers", "asset_class", "exchange", "report_name",
                "run_in_background", "domain", "section", "section_id",
            }
        }
        if section == "volume_profile_ce":
            return await svc.volume_profile_ce(tickers=tickers, asset_class=ac, exchange=exchange, cfg_overrides=cfg or None)
        if section == "volume_profile_poc":
            return await svc.volume_profile_poc(tickers=tickers, asset_class=ac, exchange=exchange, cfg_overrides=cfg or None)
        if section == "pa_volume_profile":
            return await svc.pa_volume_profile(tickers=tickers, asset_class=ac, exchange=exchange, cfg_overrides=cfg or None)
        if section == "pa_vp_smc":
            return await svc.pa_vp_smc(tickers=tickers, asset_class=ac, exchange=exchange, cfg_overrides=cfg or None)
        if section == "volume_spread_next_candle":
            return await svc.volume_spread_next_candle(tickers=tickers, asset_class=ac, exchange=exchange, cfg_overrides=cfg or None)
        if section == "elliott_wave":
            return await svc.elliott_wave(tickers=tickers, asset_class=ac, exchange=exchange, cfg_overrides=cfg or None)
        if section == "fibonacci_pro":
            return await svc.fibonacci_pro(tickers=tickers, asset_class=ac, exchange=exchange, cfg_overrides=cfg or None)
        if section == "bb_mean_reversion":
            return await svc.bb_mean_reversion(tickers=tickers, asset_class=ac, exchange=exchange, cfg_overrides=cfg or None)
        if section == "traffic_light_indicator":
            return await svc.traffic_light_indicator(tickers=tickers, asset_class=ac, exchange=exchange, cfg_overrides=cfg or None)
        if section == "buy_low_sell_high":
            return await svc.buy_low_sell_high(tickers=tickers, asset_class=ac, exchange=exchange, cfg_overrides=cfg or None)
        if section == "rlb_breakout":
            return await svc.rlb_breakout(tickers=tickers, asset_class=ac, exchange=exchange, cfg_overrides=cfg or None)
        if section == "three_in_one_trade_system":
            return await svc.three_in_one_trade_system(tickers=tickers, asset_class=ac, exchange=exchange, cfg_overrides=cfg or None)
        if section == "simple_effective":
            tfs = None
            if isinstance(cfg, dict):
                tfs = cfg.get("timeframes")
            return await svc.simple_effective(
                tickers=tickers, asset_class=ac, exchange=exchange, timeframes=tfs, cfg_overrides=cfg or None,
            )
        if section == "bb_rsi_vol":
            tfs = None
            if isinstance(cfg, dict):
                tfs = cfg.get("timeframes")
            return await svc.bb_rsi_vol(
                tickers=tickers, asset_class=ac, exchange=exchange, timeframes=tfs, cfg_overrides=cfg or None,
                use_ai=bool(payload.get("use_ai", False)),
            )
        if section in ("ema9_bb_rsi_vol", "ema5_bb_rsi_vol", "ema_cross"):
            tfs = None
            if isinstance(cfg, dict):
                tfs = cfg.get("timeframes")
            ov = dict(cfg or {})
            if section == "ema5_bb_rsi_vol":
                ov.setdefault("ema_period", 5)
            return await svc.ema9_bb_rsi_vol(
                tickers=tickers, asset_class=ac, exchange=exchange, timeframes=tfs, cfg_overrides=ov,
                use_ai=bool(payload.get("use_ai", False)),
            )
        if section == "ema5_9_crossover":
            tfs = None
            if isinstance(cfg, dict):
                tfs = cfg.get("timeframes")
            return await svc.ema5_9_crossover(
                tickers=tickers, asset_class=ac, exchange=exchange, timeframes=tfs, cfg_overrides=cfg or None,
                use_ai=bool(payload.get("use_ai", False)),
            )
        if section == "ema9_vol_rsi_momentum":
            return await svc.ema9_vol_rsi_momentum(
                tickers=tickers, asset_class=ac, exchange=exchange, cfg_overrides=cfg or None,
                use_ai=bool(payload.get("use_ai", False)),
            )
        if section == "flat_retest":
            tfs = None
            if isinstance(cfg, dict):
                tfs = cfg.get("timeframes")
            return await svc.flat_retest(
                tickers=tickers, asset_class=ac, exchange=exchange, timeframes=tfs, cfg_overrides=cfg or None,
                use_ai=bool(payload.get("use_ai", False)),
            )
        if section == "btst":
            return await svc.btst(tickers, asset_class=ac, cfg_overrides=cfg or None)
        raise ValueError(f"Unknown Pro Trade section: {section}")

    if domain == "prediction":
        from app.services.prediction_service import PredictionService

        svc = PredictionService(settings, db)
        tickers = _tickers(payload)
        ac = _asset_class(payload)
        exchange = payload.get("exchange")
        cfg = {
            k: v for k, v in payload.items()
            if k not in {
                "tickers", "asset_class", "exchange", "report_name",
                "run_in_background", "domain", "section", "section_id",
            }
        }
        if section == "pattern_analogue":
            chart_image = payload.get("chart_image_base64")
            cfg_clean = {
                k: v for k, v in (cfg or {}).items()
                if k not in {"chart_image_base64", "chart_image_mime", "template_shape_pct"}
            }
            return await svc.pattern_analogue(
                tickers=tickers,
                asset_class=ac,
                exchange=exchange,
                cfg_overrides=cfg_clean or None,
                chart_image_base64=chart_image,
            )
        if section.startswith("astro_finance") or section in {
            "lunar_cycle", "amavasya_sr", "bhadra_timing", "transit_gaps", "trading_calendar",
            "astro_finance",
        }:
            strategy = str(payload.get("strategy") or section)
            if strategy in ("astro_finance", "astro_finance_lunar_cycle"):
                strategy = "lunar_cycle"
            if section.startswith("astro_finance_") and section != "astro_finance":
                strategy = section.replace("astro_finance_", "", 1)
            strategies = payload.get("strategies")
            return await svc.astro_finance(
                strategy=strategy if not strategies else None,
                strategies=strategies,
                tickers=tickers,
                asset_class=ac,
                exchange=exchange,
                cfg_overrides=cfg or None,
            )
        if section in ("falling_knife", "falling-knife", "runup_descent"):
            from app.services.falling_knife_service import FallingKnifeService

            scan_payload = {
                "asset_class": ac,
                "tickers": tickers,
                "exchange": exchange,
                **(cfg or {}),
            }
            if section == "runup_descent" and not scan_payload.get("mode"):
                scan_payload["mode"] = "runup_descent"
            return await FallingKnifeService(settings).scan(scan_payload)
        raise ValueError(f"Unknown Prediction section: {section}")

    if domain == "command_center":
        return await _execute_command_center(section, payload, settings=settings, db=db)

    if domain == "technical_analysis":
        return await _execute_technical_analysis(section, payload, settings=settings)

    if domain == "market_pulse":
        return await _execute_market_pulse(section, payload, settings=settings)

    if domain == "scanner":
        from app.models.schemas import ScanRequest
        from app.services.scanner_service import ScannerService

        svc = ScannerService(settings)
        strategies = payload.get("strategies") or payload.get("strategy_ids") or []
        tfs = _timeframes(payload) or ["1d"]
        req = ScanRequest(
            tickers=_tickers(payload),
            strategies=[str(s) for s in strategies],
            timeframes=tfs,
            asset_class=_asset_class(payload),  # type: ignore[arg-type]
            bars=payload.get("bars"),
        )
        signals = await svc.scan(req)
        rows = []
        for s in signals:
            if hasattr(s, "model_dump"):
                rows.append(s.model_dump())
            elif isinstance(s, dict):
                rows.append(s)
            else:
                rows.append(dict(s))
        return {"signals": rows, "scanned_at": payload.get("scanned_at")}

    if domain == "seasonality":
        from app.services.seasonality_service import SeasonalityService

        svc = SeasonalityService(settings)
        return await svc.analyze(
            _tickers(payload),
            years=int(payload.get("years") or 10),
            asset_class=_asset_class(payload),
        )

    if domain == "trading_agent":
        return await _execute_trading_agent(section, payload, settings=settings, db=db)

    if domain == "investing_agent":
        return await _execute_investing_agent(section, payload, settings=settings)

    raise ValueError(f"Unknown analysis domain: {domain}")


async def _execute_trading_agent(
    section: str,
    payload: dict[str, Any],
    *,
    settings: Any,
    db: Any,
) -> dict[str, Any]:
    from app.services.dashboard_trading_chat_service import DashboardTradingChatService

    if section not in ("trading_chat", "chat", "ask"):
        raise ValueError(f"Unknown Trading Agent section: {section}")

    message = str(payload.get("message") or "").strip()
    if not message:
        raise ValueError("message is required for Trading Agent")

    top_n = payload.get("top_n")
    top_n_i = int(top_n) if top_n is not None else None
    extra = payload.get("extra_checks")
    tickers = payload.get("tickers")
    return await DashboardTradingChatService(settings, db=db).chat(
        message=message,
        asset_class=payload.get("asset_class") or None,
        style=payload.get("style") or None,
        tickers=list(tickers) if isinstance(tickers, list) else None,
        extra_checks=list(extra) if isinstance(extra, list) else None,
        top_n=top_n_i,
        skip_ai=bool(payload.get("skip_ai") or False),
        deep_mode=bool(payload.get("deep_mode") or False),
        explain_only=bool(payload.get("explain_only") or False),
        prior_result=payload.get("prior_result") if isinstance(payload.get("prior_result"), dict) else None,
    )


async def _execute_investing_agent(
    section: str,
    payload: dict[str, Any],
    *,
    settings: Any,
) -> dict[str, Any]:
    """Fundamental Analyst (Investing Agent) — non-streaming analyze_once for background jobs."""
    from app.services.superinvesting_service import SuperInvestingError, SuperInvestingService

    if section not in ("chat", "analysis", "fundamental"):
        raise ValueError(f"Unknown Investing Agent section: {section}")

    message = str(payload.get("message") or payload.get("prompt") or "").strip()
    if not message:
        raise ValueError("message is required for Investing Agent")

    token = await settings.get_superinvesting_token()
    if not token:
        raise ValueError("Fundamental Analyst token is not set. Add it under Manage → AI Settings.")

    try:
        result = await SuperInvestingService(token).analyze_once(message)
    except SuperInvestingError as exc:
        raise ValueError(str(exc)) from exc

    return {
        "kind": "investing_agent",
        "message": message,
        "answer": result.get("answer") or "",
        "conversation_id": result.get("conversation_id"),
        "tools": result.get("tools") or [],
        "reasoning": result.get("reasoning") or "",
    }


async def _execute_command_center(section: str, payload: dict[str, Any], *, settings: Any, db: Any) -> dict[str, Any]:
    from app.services.command_center_service import CommandCenterService

    svc = CommandCenterService(settings, db)
    tickers = _tickers(payload)
    ac = _asset_class(payload)
    tfs = _timeframes(payload)

    if section == "mega_analyser":
        return await svc.mega_analyser(tickers, asset_class=ac, durations=tfs)
    if section == "buy_sell":
        return await svc.buy_sell_advisor(tickers, asset_class=ac, durations=tfs)
    if section == "investigation":
        from app.services.market_pulse_service import MarketPulseService
        return await MarketPulseService(settings).ticker_investigation(tickers, asset_class=ac)
    if section == "momentum":
        return await svc.momentum(tickers, asset_class=ac, timeframes=tfs)
    if section == "ema_position":
        return await svc.ema_position(tickers, asset_class=ac, timeframes=tfs)
    if section == "mtf_trend_strength":
        return await svc.mtf_trend_strength(
            tickers,
            asset_class=ac,
            timeframes=tfs,
            from_date=payload.get("from_date") or None,
            to_date=payload.get("to_date") or None,
        )
    if section == "divergences":
        return await svc.divergences(tickers, asset_class=ac, timeframes=tfs)
    if section == "candlestick_chart_patterns" or section == "patterns":
        return await svc.patterns(tickers, asset_class=ac, timeframes=tfs)
    if section == "stop_hunt":
        return await svc.stop_hunt(tickers, asset_class=ac, timeframes=tfs)
    if section == "take_profit":
        return await svc.take_profit(tickers, asset_class=ac, timeframes=tfs)
    if section == "real_bottom":
        return await svc.real_bottom(tickers, asset_class=ac, timeframes=tfs)
    if section == "weak_strong":
        return await svc.weak_strong(tickers, asset_class=ac, timeframes=tfs)
    if section == "sma_20_200":
        return await svc.sma_20_200(tickers, asset_class=ac, timeframes=tfs)
    if section == "copy_trade":
        return await svc.copy_trade(tickers, asset_class=ac)
    if section == "take_trade":
        return await svc.take_trade(tickers, asset_class=ac, timeframes=tfs)
    if section == "trade_setup":
        return await svc.trade_setup(tickers, asset_class=ac, timeframes=tfs)
    if section == "fundamental_analysis":
        return await svc.fundamental_analysis(tickers)
    if section == "stock_upgrade_downgrade":
        return await svc.stock_upgrade_downgrade(tickers, asset_class=ac)
    if section in ("one_click_intraday", "one_click_scalping", "one_click_swing"):
        style = {
            "one_click_intraday": "intraday",
            "one_click_scalping": "scalping",
            "one_click_swing": "swing",
        }[section]
        return await svc.one_click(style, tickers, asset_class=ac)
    if section == "investigation_strategies":
        return await svc.investigate_with_strategies(
            ac, tickers, strategy_ids=payload.get("strategy_ids"),
        )
    if section == "mega_setup_advisor":
        return await svc.mega_setup_advice(
            market=str(payload.get("market") or "Groww (India Stocks)"),
            timeframes=tfs or ["15m", "1h", "1d"],
            ticker_count=int(payload.get("ticker_count") or len(tickers) or 10),
            use_ai=bool(payload.get("use_ai", False)),
        )
    if section == "quick_analyzer":
        return await svc.quick_analyzer(
            tickers,
            tfs or ["1d"],
            asset_class=ac,
            from_date=payload.get("from_date"),
            to_date=payload.get("to_date"),
            include_fundamentals=bool(payload.get("include_fundamentals")),
            include_option_chain=bool(payload.get("include_option_chain")),
            user_id=None,
        )
    if section == "market_movers":
        return await svc.market_movers(
            ac, str(payload.get("index") or ""), str(payload.get("timeframe") or "1d"),
        )
    if section == "india_market_heatmap":
        return await svc.india_market_heatmap(
            str(payload.get("index_name") or ""),
            asset_class=ac,
            tickers=tickers or None,
        )
    if section == "option_chain":
        return await svc.option_chain(
            str(payload.get("symbol") or ""),
            bool(payload.get("is_index", False)),
        )
    if section == "option_short_long":
        return await svc.option_short_long(
            symbols=list(payload.get("symbols") or tickers),
            is_index=bool(payload.get("is_index", False)),
            expiries=payload.get("expiries"),
        )
    if section == "detect_sector_rotation":
        return await svc.detect_sector_rotation(
            market=str(payload.get("market") or "india"),
            sectors=payload.get("sectors"),
            crs_sma_period=int(payload.get("crs_sma_period") or 50),
            hma_length=int(payload.get("hma_length") or 9),
            pullback_months=int(payload.get("pullback_months") or 2),
            pullback_mode=str(payload.get("pullback_mode") or "months"),
        )
    if section == "comparative_strength":
        return await svc.comparative_strength(
            asset_class=str(payload.get("asset_class") or ac or "india"),
            base_symbol=str(payload.get("base_symbol") or ""),
            compare_symbols=list(payload.get("compare_symbols") or tickers or []),
            timeframe=str(payload.get("timeframe") or (tfs[0] if tfs else "1d")),
            lookback_bars=int(payload.get("lookback_bars") or 20),
            exchange=payload.get("exchange"),
        )
    if section == "advance_decline_graph":
        return await svc.advance_decline_graph(
            str(payload.get("index_name") or "NIFTY 50"),
            asset_class=str(payload.get("asset_class") or ac or "india"),
            from_date=str(payload.get("from_date") or ""),
            to_date=str(payload.get("to_date") or ""),
            timeframe=str(payload.get("timeframe") or (tfs[0] if tfs else "1d")),
            session_date=payload.get("session_date"),
            as_of_time=payload.get("as_of_time"),
            exchange=payload.get("exchange"),
        )
    if section == "oil_dollar_bond":
        return await svc.oil_dollar_bond(
            from_date=payload.get("from_date") or None,
            to_date=payload.get("to_date") or None,
            mode=str(payload.get("mode") or "daily"),
            session_date=payload.get("session_date") or None,
            interval=str(payload.get("interval") or "1d"),
        )
    raise ValueError(f"Unknown Command Center section: {section}")


async def _execute_technical_analysis(section: str, payload: dict[str, Any], *, settings: Any) -> dict[str, Any]:
    from app.services.market_pulse_service import MarketPulseService

    mp = MarketPulseService(settings)
    tickers = _tickers(payload)
    ac = _asset_class(payload)
    tfs = _timeframes(payload)

    if section == "ticker_investigation":
        return await mp.ticker_investigation(tickers, asset_class=ac)
    if section == "sentiment_screener":
        return await mp.sentiment_screener(tickers, timeframes=tfs)
    if section == "mtf_scanner":
        return await mp.mtf_scanner(tickers, timeframes=tfs)

    from app.services.ta_screener_service import TaScreenerService

    return await TaScreenerService(settings).run(
        section,
        tickers,
        timeframe=payload.get("timeframe") or (tfs[0] if tfs else None),
        options=payload.get("options") or payload.get("config"),
        asset_class=ac,
    )


async def _execute_market_pulse(section: str, payload: dict[str, Any], *, settings: Any) -> dict[str, Any]:
    from app.services.market_pulse_service import MarketPulseService

    mp = MarketPulseService(settings)
    tickers = _tickers(payload)

    if section == "gainers_losers":
        return await mp.gainers_losers(
            str(payload.get("index_name") or "Nifty 50"),
            str(payload.get("tf_key") or payload.get("timeframe") or "1d"),
            int(payload.get("lookback_bars") or 1),
        )
    if section == "stock_rotation":
        return await mp.stock_rotation(
            str(payload.get("index_name") or "Nifty 50"),
            str(payload.get("tf_key") or "1d"),
            int(payload.get("lookback_bars") or payload.get("lookback") or 5),
        )
    if section in ("stock_rotation_us", "stock_rotation_crypto"):
        market = str(payload.get("market") or ("us" if "us" in section else "crypto"))
        return await mp.stock_rotation_market(
            market,
            str(payload.get("universe_id") or payload.get("index_name") or ""),
            str(payload.get("tf_key") or "1d"),
            int(payload.get("lookback_bars") or payload.get("lookback") or 5),
        )
    if section == "commodity_screener":
        return await mp.commodity_screener(timeframes=_timeframes(payload))
    if section == "mtf_bias":
        return await mp.mtf_bias(tickers, is_crypto=False)
    if section == "mtf_bias_crypto":
        return await mp.mtf_bias(tickers, is_crypto=True)
    if section == "accurate_strategy":
        return await mp.accurate_strategy(
            tickers,
            timeframe=str(payload.get("timeframe") or "1h"),
            min_confluence=float(payload.get("min_confluence") or 60.0),
            rr_target=float(payload.get("rr_target") or 2.0),
            market=str(payload.get("market") or "India (Groww)"),
        )
    if section == "pump_dump_breakout":
        return await mp.pump_dump_breakout(
            tickers,
            timeframe=str(payload.get("timeframe") or "15m"),
            market=str(payload.get("market") or "India (Groww)"),
            initial_balance=float(payload.get("initial_balance") or 1000.0),
        )
    raise ValueError(f"Unknown Market Pulse section: {section}")


def run_analysis_job(
    job_id: str,
    domain: str,
    section: str,
    payload: dict[str, Any],
    *,
    report_name: str | None = None,
    user_id: int | None = None,
) -> None:
    async def _run() -> None:
        from app.core.database import AsyncSessionLocal
        from app.services.analysis_report_service import AnalysisReportService
        from app.services.settings_service import SettingsService

        try:
            label = section.replace("_", " ")
            update_progress(job_id, 0.05, f"Running {domain.replace('_', ' ')} · {label}…")
            async with AsyncSessionLocal() as db:
                settings = SettingsService(db)
                result = await execute_analysis(
                    domain, section, payload, settings=settings, db=db, user_id=user_id,
                )

            report_id: int | None = None
            save_name = (report_name or "").strip()
            if save_name and user_id is not None:
                async with AsyncSessionLocal() as db:
                    saved = await AnalysisReportService(db).save(
                        domain, section, save_name, result, user_id=user_id,
                        tickers=_tickers(payload),
                        asset_class=_asset_class(payload),
                    )
                    report_id = saved.get("id")
                    result = {
                        **(result if isinstance(result, dict) else {"data": result}),
                        "saved_report_id": report_id,
                        "saved_report_name": saved.get("name") or save_name,
                    }

            await complete_job(job_id, result if isinstance(result, dict) else {"data": result}, report_id=report_id)
        except Exception as exc:
            logger.exception("Analysis job %s (%s/%s) failed", job_id, domain, section)
            await fail_job(job_id, str(exc)[:500])

    asyncio.create_task(_run())
