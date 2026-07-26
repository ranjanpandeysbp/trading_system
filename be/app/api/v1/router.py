from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.db_models import User
from app.models.schemas import (
    AIConfigResponse,
    AlertMonitorCreate,
    AlertNotifyConfigUpdate,
    AlertScheduleCreate,
    AlertScheduleHitsDelete,
    AlertScheduleUpdate,
    AskAIRequest,
    AskAIResponse,
    CommandCenterBuySellRequest,
    CommandCenterMegaRequest,
    BacktestRequest,
    BacktestResponse,
    EtfTaRecommendRequest,
    EtfTaScanRequest,
    ForgotPasswordRequest,
    MarketPulseAccurateStrategyRequest,
    MarketPulseCommodityRequest,
    MarketPulseHeatmapRequest,
    MarketPulseIndexRequest,
    MarketPulseMtfRequest,
    MarketPulsePagination,
    MarketPulsePumpDumpRequest,
    MarketPulseRotationRequest,
    MarketPulseSentimentRequest,
    MarketPulseStockRotationMarketRequest,
    CommandCenterDayBiasRequest,
    CommandCenterInvestigateStrategiesRequest,
    CommandCenterMegaAdviceRequest,
    CommandCenterMfHoldingsRequest,
    CommandCenterEtfIndiaHoldingsRequest,
    CommandCenterEtfYahooHoldingsRequest,
    CommandCenterSmartMoneyActivityRequest,
    CommandCenterHeatmapRequest,
    CommandCenterOneClickRequest,
    CommandCenterOptionChainRequest,
    CommandCenterOptionShortLongRequest,
    CommandCenterQuickAnalyzerRequest,
    CommandCenterSma20200Request,
    CommandCenterTickerScanRequest,
    CommandCenterTradeSetupDrillRequest,
    DetectSectorRotationRequest,
    CommandCenterTradeSetupRequest,
    WatchlistCreate,
    WatchlistItemCreate,
    MarketPulseTickerInvestigationRequest,
    MessageResponse,
    ModifyOrderRequest,
    OptionsDeltaNeutralPnlRequest,
    OptionsDeltaNeutralRequest,
    OptionsDoubleCalendarPnlRequest,
    OptionsDoubleCalendarRequest,
    OptionsGokulChhabraRequest,
    PlaceOrderRequest,
    ResetPasswordRequest,
    ScanRequest,
    ScanResponse,
    SeasonalityRequest,
    SettingsResponse,
    SettingsUpdate,
    StrategyInfo,
    StrategyCategoryInfo,
    StrategyLabBacktestRequest,
    StrategyLabMultiComboRequest,
    StrategyLabScreenerRequest,
    TokenResponse,
    TradingHubScanRequest,
    TaScreenerRunRequest,
    UserLogin,
    UserOut,
    UserRegister,
)
from app.services.command_center_service import CommandCenterService
from app.services.options_service import OptionsService
from app.services.ticker_universe_service import TickerUniverseService
from app.services.alerts_service import AlertsService
from app.services.schedule_alerts_service import ScheduleAlertsService
from app.services.watchlist_service import WatchlistService
from app.services.auth_service import AuthService
from app.services.ai_service import AIService
from app.services.backtest_service import BacktestService
from app.services.market_pulse_service import MarketPulseService
from app.services.paper_trading_service import PaperTradingService
from app.services.scanner_service import ScannerService
from app.services.seasonality_service import SeasonalityService
from app.services.strategy_lab_service import StrategyLabService
from app.services.ta_screener_service import TaScreenerService
from app.services.etf_ta_service import EtfTaService
from app.services.trading_hub_service import TradingHubService
from app.services.settings_service import SettingsService
from app.strategies.registry import (
    all_strategy_meta_for_api,
    get_strategy_meta_for_api,
    list_categories,
    list_scanner_categories,
)

router = APIRouter(prefix="/api/v1")


@router.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@router.post("/auth/register", response_model=TokenResponse)
async def register(payload: UserRegister, db: AsyncSession = Depends(get_db)):
    service = AuthService(db)
    try:
        return await service.register(payload.name, payload.mobile, payload.email, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/auth/login", response_model=TokenResponse)
async def login(payload: UserLogin, db: AsyncSession = Depends(get_db)):
    service = AuthService(db)
    try:
        return await service.login(payload.identifier, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.post("/auth/forgot-password", response_model=MessageResponse)
async def forgot_password(payload: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    service = AuthService(db)
    return await service.forgot_password(payload.email)


@router.post("/auth/reset-password", response_model=TokenResponse)
async def reset_password(payload: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    service = AuthService(db)
    try:
        result = await service.reset_password(payload.token, payload.new_password)
        return TokenResponse(
            access_token=result["access_token"],
            token_type=result["token_type"],
            user=UserOut(**result["user"]),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/auth/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)):
    return UserOut(
        id=current_user.id,
        name=current_user.name,
        mobile=current_user.mobile,
        email=current_user.email,
        created_at=current_user.created_at.isoformat() if current_user.created_at else None,
    )


@router.post("/auth/logout")
async def logout():
    return {"message": "Logged out successfully"}


@router.get("/strategies", response_model=list[StrategyInfo])
async def list_strategies():
    return [StrategyInfo(**meta) for meta in all_strategy_meta_for_api().values()]


@router.get("/strategies/categories", response_model=list[StrategyCategoryInfo])
async def list_strategy_categories():
    return [StrategyCategoryInfo(**cat) for cat in list_categories()]


@router.get("/strategies/scanner-categories", response_model=list[StrategyCategoryInfo])
async def list_scanner_strategy_categories():
    return [StrategyCategoryInfo(**cat) for cat in list_scanner_categories()]


@router.get("/strategies/{strategy_id}", response_model=StrategyInfo)
async def get_strategy_detail(strategy_id: str):
    meta = get_strategy_meta_for_api(strategy_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Unknown strategy: {strategy_id}")
    return StrategyInfo(**meta)


@router.post("/scanner/scan", response_model=ScanResponse)
async def scan(
    request: ScanRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    settings = SettingsService(db)
    service = ScannerService(settings)
    signals = await service.scan(request)
    return ScanResponse(signals=signals, scanned_at=datetime.now(timezone.utc).isoformat())


@router.post("/backtest/run", response_model=BacktestResponse)
async def run_backtest(
    request: BacktestRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    settings = SettingsService(db)
    service = BacktestService(settings)
    try:
        result = await service.run(request)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return BacktestResponse(**result)


@router.get("/settings", response_model=SettingsResponse)
async def get_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = SettingsService(db)
    return SettingsResponse(**await service.get_all())


@router.put("/settings", response_model=SettingsResponse)
async def update_settings(
    payload: SettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = SettingsService(db)
    data = payload.model_dump(exclude_unset=True)
    return SettingsResponse(**await service.update(data))


@router.post("/settings/test-provider")
async def test_provider(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.data.factory import DataProviderFactory

    settings = SettingsService(db)
    provider = await DataProviderFactory.get_provider(settings)
    return await provider.health_check()


@router.get("/markets")
async def list_markets():
    from app.market_pulse.ticker_utils import MARKET_OPTIONS
    return {"markets": MARKET_OPTIONS}


@router.get("/market/marquee")
async def market_marquee(
    current_user: User = Depends(get_current_user),
):
    """Popular India / US / Crypto / Commodity LTPs for the header marquee."""
    from app.services.marquee_quotes_service import fetch_marquee_quotes

    return await fetch_marquee_quotes()


@router.get("/ai/config", response_model=AIConfigResponse)
async def ai_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = AIService(SettingsService(db))
    return AIConfigResponse(**await service.provider_config())


@router.post("/ai/ask", response_model=AskAIResponse)
async def ai_ask(
    payload: AskAIRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = AIService(SettingsService(db))
    try:
        result = await service.ask(
            context=payload.context,
            question=payload.question,
            system_prompt=payload.system_prompt,
            section=payload.section,
            max_tokens=payload.max_tokens,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AskAIResponse(**result)


@router.get("/paper/account")
async def get_paper_account(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    settings = SettingsService(db)
    service = PaperTradingService(db, settings, user_id=current_user.id)
    return await service.get_summary()


@router.post("/paper/orders")
async def place_order(
    request: PlaceOrderRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    settings = SettingsService(db)
    service = PaperTradingService(db, settings, user_id=current_user.id)
    try:
        return await service.place_order(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/paper/orders/{order_id}/cancel")
async def cancel_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    settings = SettingsService(db)
    service = PaperTradingService(db, settings, user_id=current_user.id)
    try:
        return await service.cancel_order(order_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/paper/orders/{order_id}/modify")
async def modify_order(
    order_id: int,
    request: ModifyOrderRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    settings = SettingsService(db)
    service = PaperTradingService(db, settings, user_id=current_user.id)
    try:
        return await service.modify_order(order_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/paper/execute-signal")
async def execute_signal(
    signal: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    settings = SettingsService(db)
    service = PaperTradingService(db, settings, user_id=current_user.id)
    try:
        return await service.execute_from_signal(signal)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/paper/reset")
async def reset_paper_account(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    settings = SettingsService(db)
    service = PaperTradingService(db, settings, user_id=current_user.id)
    return await service.reset_account()


@router.get("/market-pulse/sections")
async def market_pulse_sections():
    return {
        "sections": [
            {"id": "tomorrow_outlook", "label": "Tomorrow's Market Outlook"},
            {"id": "intelligence", "label": "News Scanner & Market Intelligence"},
            {"id": "nifty_breadth", "label": "Nifty Index Breadth"},
            {"id": "nifty_monthly", "label": "Nifty 1-Month Performance"},
            {"id": "nifty_movers", "label": "Nifty Gainers & Losers"},
            {"id": "gainers_losers", "label": "Gainers & Losers (India multi-TF)"},
            {"id": "stock_rotation", "label": "Stock Price Rotation"},
            {"id": "commodity_screener", "label": "Commodity Screener (Nifty)"},
            {"id": "accurate_strategy", "label": "Accurate Strategy — OB + FVG + S/R"},
            {"id": "pump_dump_breakout", "label": "Pump/Dump Breakout"},
            {"id": "big_whale_pump_dump", "label": "Big Whale Pump & Dump"},
            {"id": "sector_rotation", "label": "Sector Rotation (HTF)"},
            {"id": "sector_rotation_intraday", "label": "Sector Rotation (Intraday)"},
            {"id": "sector_rotation_us", "label": "Sector Rotation — US (HTF)"},
            {"id": "sector_rotation_us_intraday", "label": "Sector Rotation — US (Intraday)"},
            {"id": "sector_rotation_crypto", "label": "Sector Rotation — Crypto (HTF)"},
            {"id": "sector_rotation_crypto_intraday", "label": "Sector Rotation — Crypto (Intraday)"},
            {"id": "stock_rotation_us", "label": "Stock Price Rotation — US"},
            {"id": "stock_rotation_crypto", "label": "Stock Price Rotation — Crypto"},
            {"id": "opposite_hedge", "label": "Opposite Hedge-MTF"},
            {"id": "mtf_bias", "label": "MTF Intraday Bias"},
            {"id": "mtf_bias_crypto", "label": "MTF Intraday Bias — Crypto"},
            {"id": "week52", "label": "52-Week High & Low"},
            {"id": "heatmap", "label": "Live Heatmap (India)"},
        ]
    }


@router.get("/market-pulse/indices")
async def market_pulse_indices(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = MarketPulseService(SettingsService(db))
    return await service.index_options()


@router.get("/market-pulse/tomorrow-outlook")
async def market_pulse_tomorrow_outlook(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = MarketPulseService(SettingsService(db))
    return await service.tomorrow_outlook()


@router.get("/market-pulse/intelligence")
async def market_pulse_intelligence(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = MarketPulseService(SettingsService(db))
    return await service.intelligence()


@router.get("/market-pulse/nifty-breadth")
async def market_pulse_nifty_breadth(
    offset: int = 0,
    limit: int = 10,
    include_sr: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        service = MarketPulseService(SettingsService(db))
        return await service.nifty_breadth(offset, limit, include_sr=include_sr)
    except Exception as e:
        return {"error": str(e), "items": [], "total": 0, "offset": offset, "limit": limit}


@router.get("/market-pulse/nifty-monthly")
async def market_pulse_nifty_monthly(
    offset: int = 0,
    limit: int = 2,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = MarketPulseService(SettingsService(db))
    return await service.nifty_monthly(offset, limit)


@router.get("/market-pulse/nifty-movers")
async def market_pulse_nifty_movers(
    index_name: str = "NIFTY 50",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = MarketPulseService(SettingsService(db))
    return await service.nifty_movers(index_name)


@router.post("/market-pulse/gainers-losers")
async def market_pulse_gainers_losers(
    payload: MarketPulseRotationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = MarketPulseService(SettingsService(db))
    return await service.gainers_losers(payload.index_name, payload.tf_key, payload.lookback_bars)


@router.post("/market-pulse/stock-rotation")
async def market_pulse_stock_rotation(
    payload: MarketPulseRotationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = MarketPulseService(SettingsService(db))
    return await service.stock_rotation(payload.index_name, payload.tf_key, payload.lookback_bars)


@router.get("/market-pulse/sector-rotation")
async def market_pulse_sector_rotation(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = MarketPulseService(SettingsService(db))
    return await service.sector_rotation()


@router.get("/market-pulse/sector-rotation/intraday")
async def market_pulse_sector_rotation_intraday(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = MarketPulseService(SettingsService(db))
    return await service.sector_rotation_intraday()


@router.get("/market-pulse/sector-rotation/{market}")
async def market_pulse_sector_rotation_market(
    market: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if market not in ("us", "crypto"):
        raise HTTPException(status_code=400, detail="market must be 'us' or 'crypto'")
    service = MarketPulseService(SettingsService(db))
    return await service.sector_rotation_market(market)


@router.get("/market-pulse/sector-rotation/{market}/intraday")
async def market_pulse_sector_rotation_market_intraday(
    market: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if market not in ("us", "crypto"):
        raise HTTPException(status_code=400, detail="market must be 'us' or 'crypto'")
    service = MarketPulseService(SettingsService(db))
    return await service.sector_rotation_market_intraday(market)


@router.get("/market-pulse/stock-rotation/{market}/universes")
async def market_pulse_stock_rotation_universes(
    market: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if market not in ("us", "crypto"):
        raise HTTPException(status_code=400, detail="market must be 'us' or 'crypto'")
    service = MarketPulseService(SettingsService(db))
    return await service.rotation_universes(market)


@router.post("/market-pulse/stock-rotation/{market}")
async def market_pulse_stock_rotation_market(
    market: str,
    payload: MarketPulseStockRotationMarketRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if market not in ("us", "crypto"):
        raise HTTPException(status_code=400, detail="market must be 'us' or 'crypto'")
    service = MarketPulseService(SettingsService(db))
    return await service.stock_rotation_market(
        market, payload.universe_id, payload.tf_key, payload.lookback_bars
    )


@router.get("/market-pulse/opposite-hedge")
async def market_pulse_opposite_hedge(
    capital: float = 100_000.0,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = MarketPulseService(SettingsService(db))
    return await service.opposite_hedge(capital)


@router.post("/market-pulse/mtf-bias")
async def market_pulse_mtf_bias(
    payload: MarketPulseMtfRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = MarketPulseService(SettingsService(db))
    return await service.mtf_bias(payload.tickers, is_crypto=payload.is_crypto)


@router.post("/market-pulse/accurate-strategy")
async def market_pulse_accurate_strategy(
    payload: MarketPulseAccurateStrategyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = MarketPulseService(SettingsService(db))
    return await service.accurate_strategy(
        payload.tickers,
        timeframe=payload.timeframe,
        min_confluence=payload.min_confluence,
        rr_target=payload.rr_target,
        market=payload.market,
    )


@router.post("/market-pulse/pump-dump-breakout")
async def market_pulse_pump_dump_breakout(
    payload: MarketPulsePumpDumpRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = MarketPulseService(SettingsService(db))
    return await service.pump_dump_breakout(
        payload.tickers,
        timeframe=payload.timeframe,
        market=payload.market,
        initial_balance=payload.initial_balance,
    )


@router.get("/market-pulse/big-whale-pump-dump")
async def market_pulse_big_whale_pump_dump(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = MarketPulseService(SettingsService(db))
    return await service.big_whale_pump_dump()


@router.get("/market-pulse/week52")
async def market_pulse_week52(
    index_name: str = "NIFTY 50",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = MarketPulseService(SettingsService(db))
    return await service.week52(index_name)


@router.get("/market-pulse/heatmap")
async def market_pulse_heatmap(
    timeframe: str = "1d",
    mode: str = "sectoral",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = MarketPulseService(SettingsService(db))
    return await service.heatmap(timeframe, mode)


@router.post("/market-pulse/mtf-scanner")
async def market_pulse_mtf_scanner(
    payload: MarketPulseMtfRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = MarketPulseService(SettingsService(db))
    return await service.mtf_scanner(payload.tickers, payload.timeframes)


@router.post("/market-pulse/sentiment-screener")
async def market_pulse_sentiment_screener(
    payload: MarketPulseSentimentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = MarketPulseService(SettingsService(db))
    return await service.sentiment_screener(payload.tickers, payload.timeframes, payload.lookback_days)


@router.post("/market-pulse/ticker-investigation")
async def market_pulse_ticker_investigation(
    payload: MarketPulseTickerInvestigationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = MarketPulseService(SettingsService(db))
    return await service.ticker_investigation(payload.tickers, asset_class=payload.asset_class)


@router.get("/command-center/sections")
async def command_center_sections(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return CommandCenterService(SettingsService(db)).sections()


@router.get("/command-center/ticker-universe")
async def command_center_ticker_universe(
    asset_class: str = "india",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if asset_class not in {"india", "us", "crypto", "commodity"}:
        raise HTTPException(status_code=400, detail=f"Unknown asset class: {asset_class}")
    return await CommandCenterService(SettingsService(db)).ticker_universe(asset_class)


@router.get("/command-center/ticker-suggestions")
async def command_center_ticker_suggestions(
    asset_class: str = "india",
    q: str = "",
    limit: int = 80,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if asset_class not in {"india", "us", "crypto", "commodity"}:
        raise HTTPException(status_code=400, detail=f"Unknown asset class: {asset_class}")
    svc = TickerUniverseService()
    return {"tickers": svc.suggest(asset_class, q, limit=min(limit, 200))}


@router.get("/command-center/tomorrow-outlook")
async def command_center_tomorrow(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = CommandCenterService(SettingsService(db))
    return await service.tomorrow_outlook()


@router.post("/command-center/buy-sell")
async def command_center_buy_sell(
    payload: CommandCenterBuySellRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = CommandCenterService(SettingsService(db))
    return await service.buy_sell_advisor(
        payload.tickers,
        asset_class=payload.asset_class,
        scenario=payload.scenario,
        durations=payload.durations,
    )


@router.post("/command-center/mega-analyser")
async def command_center_mega(
    payload: CommandCenterMegaRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = CommandCenterService(SettingsService(db))
    return await service.mega_analyser(
        payload.tickers,
        asset_class=payload.asset_class,
        durations=payload.durations,
    )


@router.get("/command-center/global-market-mood")
async def command_center_global_market_mood(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).global_market_mood()


@router.post("/command-center/momentum")
async def command_center_momentum(
    payload: CommandCenterTickerScanRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).momentum(
        payload.tickers, asset_class=payload.asset_class, timeframes=payload.timeframes,
    )


@router.post("/command-center/ema-position")
async def command_center_ema_position(
    payload: CommandCenterTickerScanRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).ema_position(
        payload.tickers, asset_class=payload.asset_class, timeframes=payload.timeframes,
    )


@router.post("/command-center/trade-setup")
async def command_center_trade_setup(
    payload: CommandCenterTradeSetupRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).trade_setup(
        payload.tickers, asset_class=payload.asset_class, timeframes=payload.timeframes,
        exchange=payload.exchange,
    )


@router.post("/command-center/trade-setup/patterns")
async def command_center_trade_setup_patterns(
    payload: CommandCenterTradeSetupDrillRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).trade_setup_patterns(
        payload.ticker, asset_class=payload.asset_class, timeframe=payload.timeframe,
    )


@router.post("/command-center/trade-setup/support-resistance")
async def command_center_trade_setup_support_resistance(
    payload: CommandCenterTradeSetupDrillRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).trade_setup_support_resistance(
        payload.ticker, asset_class=payload.asset_class, timeframe=payload.timeframe,
    )


@router.post("/command-center/trade-setup/smart-money")
async def command_center_trade_setup_smart_money(
    payload: CommandCenterTradeSetupDrillRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).trade_setup_smart_money(
        payload.ticker, asset_class=payload.asset_class, timeframe=payload.timeframe,
    )


@router.post("/command-center/trade-setup/scalping")
async def command_center_trade_setup_scalping(
    payload: CommandCenterTradeSetupDrillRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).trade_setup_scalping(
        payload.ticker, asset_class=payload.asset_class, timeframe=payload.timeframe,
    )


@router.post("/command-center/trade-setup/time-series")
async def command_center_trade_setup_time_series(
    payload: CommandCenterTradeSetupDrillRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).trade_setup_time_series(
        payload.ticker, asset_class=payload.asset_class, timeframe=payload.timeframe,
    )


@router.post("/command-center/trade-setup/divergence")
async def command_center_trade_setup_divergence(
    payload: CommandCenterTradeSetupDrillRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).trade_setup_divergence(
        payload.ticker, asset_class=payload.asset_class, timeframe=payload.timeframe,
    )


@router.post("/command-center/divergences")
async def command_center_divergences(
    payload: CommandCenterTradeSetupRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).divergences(
        payload.tickers, asset_class=payload.asset_class, timeframes=payload.timeframes,
    )


@router.post("/command-center/patterns")
async def command_center_patterns(
    payload: CommandCenterTradeSetupRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).patterns(
        payload.tickers, asset_class=payload.asset_class, timeframes=payload.timeframes,
    )


@router.post("/command-center/trade-setup/stop-hunt")
async def command_center_trade_setup_stop_hunt(
    payload: CommandCenterTradeSetupDrillRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).trade_setup_stop_hunt(
        payload.ticker, asset_class=payload.asset_class, timeframe=payload.timeframe,
    )


@router.post("/command-center/stop-hunt")
async def command_center_stop_hunt(
    payload: CommandCenterTradeSetupRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).stop_hunt(
        payload.tickers, asset_class=payload.asset_class, timeframes=payload.timeframes,
    )


@router.post("/command-center/trade-setup/take-profit")
async def command_center_trade_setup_take_profit(
    payload: CommandCenterTradeSetupDrillRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).trade_setup_take_profit(
        payload.ticker, asset_class=payload.asset_class, timeframe=payload.timeframe,
    )


@router.post("/command-center/trade-setup/real-bottom")
async def command_center_trade_setup_real_bottom(
    payload: CommandCenterTradeSetupDrillRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).trade_setup_real_bottom(
        payload.ticker, asset_class=payload.asset_class, timeframe=payload.timeframe,
    )


@router.post("/command-center/trade-setup/intra-hwp")
async def command_center_trade_setup_intra_hwp(
    payload: CommandCenterTradeSetupDrillRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).trade_setup_intra_hwp(
        payload.ticker, asset_class=payload.asset_class, timeframe=payload.timeframe,
    )


@router.post("/command-center/trade-setup/weak-strong")
async def command_center_trade_setup_weak_strong(
    payload: CommandCenterTradeSetupDrillRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).trade_setup_weak_strong(
        payload.ticker, asset_class=payload.asset_class, timeframe=payload.timeframe,
    )


@router.post("/command-center/trade-setup/copy-trade")
async def command_center_trade_setup_copy_trade(
    payload: CommandCenterTradeSetupDrillRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).trade_setup_copy_trade(
        payload.ticker, asset_class=payload.asset_class, timeframe=payload.timeframe,
    )


@router.post("/command-center/trade-setup/sma-20-200")
async def command_center_trade_setup_sma_20_200(
    payload: CommandCenterTradeSetupDrillRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).trade_setup_sma_20_200(
        payload.ticker, asset_class=payload.asset_class, timeframe=payload.timeframe,
    )


@router.post("/command-center/real-bottom")
async def command_center_real_bottom(
    payload: CommandCenterTradeSetupRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).real_bottom(
        payload.tickers, asset_class=payload.asset_class, timeframes=payload.timeframes,
    )


@router.post("/command-center/weak-strong")
async def command_center_weak_strong(
    payload: CommandCenterTradeSetupRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).weak_strong(
        payload.tickers, asset_class=payload.asset_class, timeframes=payload.timeframes,
        exchange=payload.exchange,
    )


@router.post("/command-center/sma-20-200")
async def command_center_sma_20_200(
    payload: CommandCenterSma20200Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).sma_20_200(
        payload.tickers, asset_class=payload.asset_class, timeframes=payload.timeframes,
        exchange=payload.exchange,
        cfg_overrides={
            "fast_period": payload.fast_period,
            "slow_period": payload.slow_period,
            "rr_ratio": payload.rr_ratio,
            "sl_buffer_pct": payload.sl_buffer_pct,
            "take_confidence_threshold": payload.take_confidence_threshold,
        },
    )


@router.post("/command-center/copy-trade")
async def command_center_copy_trade(
    payload: CommandCenterTradeSetupRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).copy_trade(
        payload.tickers, asset_class=payload.asset_class,
    )


@router.post("/command-center/take-profit")
async def command_center_take_profit(
    payload: CommandCenterTradeSetupRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).take_profit(
        payload.tickers, asset_class=payload.asset_class, timeframes=payload.timeframes,
    )


@router.post("/command-center/take-trade")
async def command_center_take_trade(
    payload: CommandCenterTradeSetupRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).take_trade(
        payload.tickers, asset_class=payload.asset_class, timeframes=payload.timeframes,
    )


@router.post("/command-center/one-click")
async def command_center_one_click(
    payload: CommandCenterOneClickRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).one_click(
        payload.style, payload.tickers, asset_class=payload.asset_class,
    )


@router.get("/command-center/mutual-fund/amcs")
async def command_center_mf_amcs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).mutual_fund_amc_list()


@router.get("/command-center/mutual-fund/schemes")
async def command_center_mf_schemes(
    amc_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).mutual_fund_schemes(amc_id)


@router.post("/command-center/mutual-fund/holdings")
async def command_center_mf_holdings(
    payload: CommandCenterMfHoldingsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).mutual_fund_holdings_change(
        payload.scheme_ids, payload.scheme_names, payload.from_date, payload.to_date,
    )


@router.get("/command-center/etf/amcs")
async def command_center_etf_amcs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).etf_amc_list()


@router.get("/command-center/etf/schemes")
async def command_center_etf_schemes(
    amc_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).etf_schemes(amc_id)


@router.get("/command-center/etf/catalog")
async def command_center_etf_catalog(
    market: str = "us",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """US categories (INDMoney) or crypto issuers."""
    return await CommandCenterService(SettingsService(db)).etf_issuers(market)


@router.get("/command-center/etf/issuer-schemes")
async def command_center_etf_issuer_schemes(
    issuer_name: str,
    market: str = "us",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).etf_issuer_schemes(market, issuer_name)


@router.post("/command-center/etf/holdings/india")
async def command_center_etf_holdings_india(
    payload: CommandCenterEtfIndiaHoldingsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).etf_india_holdings_change(
        payload.scheme_ids, payload.scheme_names, payload.from_date, payload.to_date,
    )


@router.post("/command-center/etf/holdings/yahoo")
async def command_center_etf_holdings_yahoo(
    payload: CommandCenterEtfYahooHoldingsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """US (INDMoney + NPORT) or Crypto (SEC NPORT) holdings trend."""
    return await CommandCenterService(SettingsService(db)).etf_us_holdings_change(
        payload.market, payload.symbols, payload.symbol_names, payload.from_date, payload.to_date,
    )


@router.post("/command-center/smart-money-activity")
async def command_center_smart_money_activity(
    payload: CommandCenterSmartMoneyActivityRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).smart_money_activity(
        payload.tickers,
        asset_class=payload.asset_class,
        source=payload.source,
        from_date=payload.from_date,
        to_date=payload.to_date,
        amc_ids=payload.amc_ids or None,
        mf_scheme_ids=payload.mf_scheme_ids or None,
        mf_scheme_names=payload.mf_scheme_names or None,
        etf_scheme_ids=payload.etf_scheme_ids or None,
        etf_scheme_names=payload.etf_scheme_names or None,
        etf_symbols=payload.etf_symbols or None,
        etf_symbol_names=payload.etf_symbol_names or None,
    )


@router.post("/command-center/fundamental-analysis")
async def command_center_fundamental_analysis(
    payload: CommandCenterTickerScanRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).fundamental_analysis(payload.tickers)


@router.post("/command-center/upgrade-downgrade")
async def command_center_upgrade_downgrade(
    payload: CommandCenterTickerScanRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).stock_upgrade_downgrade(
        payload.tickers, asset_class=payload.asset_class,
    )


@router.get("/command-center/investigation-strategies/catalog")
async def command_center_investigation_strategy_catalog(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).investigation_strategy_catalog()


@router.post("/command-center/investigation-strategies/run")
async def command_center_investigation_strategy_run(
    payload: CommandCenterInvestigateStrategiesRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).investigate_with_strategies(
        payload.asset_class, payload.tickers, strategy_ids=payload.strategy_ids,
    )


@router.post("/command-center/mega-setup-advisor")
async def command_center_mega_setup_advisor(
    payload: CommandCenterMegaAdviceRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).mega_setup_advice(
        payload.market,
        payload.timeframes,
        ticker_count=payload.ticker_count,
        use_ai=payload.use_ai,
        user_goal=payload.user_goal,
    )


@router.get("/command-center/coindcx-24h-volatility")
async def command_center_coindcx_24h_volatility(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).coindcx_24h_volatility()


@router.get("/command-center/nse-indices")
async def command_center_nse_indices(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).nse_indices()


@router.get("/command-center/global-indices")
async def command_center_global_indices(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).global_indices()


@router.get("/command-center/futures-indices")
async def command_center_futures_indices(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).futures_indices()


@router.get("/command-center/gift-nifty")
async def command_center_gift_nifty(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).gift_nifty()


@router.get("/command-center/india-market-heatmap/indices")
async def command_center_india_market_heatmap_indices(
    asset_class: str = "india",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).india_market_heatmap_indices(asset_class)


@router.post("/command-center/india-market-heatmap")
async def command_center_india_market_heatmap(
    payload: CommandCenterHeatmapRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).india_market_heatmap(
        payload.index_name, asset_class=payload.asset_class, tickers=payload.tickers,
    )


@router.post("/command-center/day-bias")
async def command_center_day_bias(
    payload: CommandCenterDayBiasRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).day_bias(
        payload.ticker, asset_class=payload.asset_class, timeframe=payload.timeframe, exchange=payload.exchange,
    )


@router.post("/command-center/option-chain")
async def command_center_option_chain(
    payload: CommandCenterOptionChainRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).option_chain(payload.symbol, payload.is_index)


@router.post("/command-center/option-short-long")
async def command_center_option_short_long(
    payload: CommandCenterOptionShortLongRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).option_short_long(
        payload.symbols, payload.is_index, expiries=payload.expiries,
    )


@router.get("/command-center/option-short-long/expiries")
async def command_center_option_short_long_expiries(
    symbol: str,
    is_index: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).option_short_long_expiries(symbol, is_index)


@router.post("/command-center/quick-analyzer")
async def command_center_quick_analyzer(
    payload: CommandCenterQuickAnalyzerRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).quick_analyzer(
        payload.tickers,
        payload.timeframes,
        asset_class=payload.asset_class,
        from_date=payload.from_date,
        to_date=payload.to_date,
        include_fundamentals=payload.include_fundamentals,
        include_option_chain=payload.include_option_chain,
    )


@router.get("/command-center/detect-sector-rotation/universe")
async def command_center_detect_sector_rotation_universe(
    market: str = "india",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).detect_sector_rotation_universe(market)


@router.post("/command-center/detect-sector-rotation")
async def command_center_detect_sector_rotation(
    payload: DetectSectorRotationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).detect_sector_rotation(
        payload.market,
        sectors=payload.sectors,
        crs_sma_period=payload.crs_sma_period,
        hma_length=payload.hma_length,
        pullback_months=payload.pullback_months,
        pullback_mode=payload.pullback_mode,
    )


@router.get("/technical-analysis/screeners")
async def ta_screener_list(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return TaScreenerService(SettingsService(db)).catalog()


@router.post("/technical-analysis/scan")
async def ta_screener_scan(
    payload: TaScreenerRunRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TaScreenerService(SettingsService(db))
    try:
        return await service.run(
            payload.screener_id,
            payload.tickers,
            timeframe=payload.timeframe,
            options=payload.options,
            asset_class=payload.asset_class,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/strategy-lab/sections")
async def strategy_lab_sections(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return StrategyLabService(SettingsService(db)).sections()


@router.get("/strategy-lab/presets")
async def strategy_lab_presets(
    market: str | None = None,
    asset_class: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await StrategyLabService(SettingsService(db)).presets(market=market, asset_class=asset_class)


@router.post("/strategy-lab/backtest")
async def strategy_lab_backtest(
    payload: StrategyLabBacktestRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = StrategyLabService(SettingsService(db))
    try:
        return await service.backtest(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/strategy-lab/multi-combo")
async def strategy_lab_multi_combo(
    payload: StrategyLabMultiComboRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = StrategyLabService(SettingsService(db))
    return await service.multi_combo(payload.model_dump())


@router.post("/strategy-lab/screener")
async def strategy_lab_screener(
    payload: StrategyLabScreenerRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = StrategyLabService(SettingsService(db))
    return await service.screener_scan(payload.model_dump())


@router.post("/seasonality/analyze")
async def seasonality_analyze(
    payload: SeasonalityRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = SeasonalityService(SettingsService(db))
    return await service.analyze(
        payload.tickers,
        years=payload.years,
        asset_class=payload.asset_class,
    )


@router.get("/alerts/config")
async def alerts_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await AlertsService(db, SettingsService(db)).config()


@router.get("/alerts/monitors")
async def alerts_list(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return {"monitors": await AlertsService(db, SettingsService(db)).list_monitors(current_user.id)}


@router.post("/alerts/monitors")
async def alerts_create(
    payload: AlertMonitorCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    mon = await AlertsService(db, SettingsService(db)).create_monitor(
        current_user.id, payload.model_dump(),
    )
    return mon


@router.delete("/alerts/monitors/{monitor_id}")
async def alerts_delete(
    monitor_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ok = await AlertsService(db, SettingsService(db)).delete_monitor(current_user.id, monitor_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Monitor not found")
    return {"deleted": True}


@router.patch("/alerts/monitors/{monitor_id}")
async def alerts_toggle(
    monitor_id: int,
    enabled: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ok = await AlertsService(db, SettingsService(db)).toggle_monitor(current_user.id, monitor_id, enabled)
    if not ok:
        raise HTTPException(status_code=404, detail="Monitor not found")
    return {"enabled": enabled}


@router.post("/alerts/poll")
async def alerts_poll(
    force: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await AlertsService(db, SettingsService(db)).poll_all(current_user.id, force=force)


# ── Alert schedules (Setup & Schedule) ──────────────────────────────────────

@router.get("/alerts/notify-config")
async def alerts_notify_config_get(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.schedule_alerts_service import ScheduleAlertsService

    return await ScheduleAlertsService(db, SettingsService(db)).get_notify_config(current_user.id)


@router.put("/alerts/notify-config")
async def alerts_notify_config_put(
    payload: AlertNotifyConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.schedule_alerts_service import ScheduleAlertsService

    return await ScheduleAlertsService(db, SettingsService(db)).save_notify_config(
        current_user.id, payload.model_dump(exclude_unset=True),
    )


@router.get("/alerts/schedules")
async def alerts_schedules_list(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.schedule_alerts_service import ScheduleAlertsService

    return {"schedules": await ScheduleAlertsService(db, SettingsService(db)).list_schedules(current_user.id)}


@router.get("/alerts/schedule-catalog")
async def alerts_schedule_catalog(
    current_user: User = Depends(get_current_user),
):
    from app.services.schedule_catalog_service import build_schedule_catalog

    return build_schedule_catalog()


@router.post("/alerts/schedules")
async def alerts_schedules_create(
    payload: AlertScheduleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.schedule_alerts_service import ScheduleAlertsService

    try:
        return await ScheduleAlertsService(db, SettingsService(db)).create_schedule(
            current_user.id, payload.model_dump(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/alerts/schedules/{schedule_id}")
async def alerts_schedules_update(
    schedule_id: int,
    payload: AlertScheduleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.schedule_alerts_service import ScheduleAlertsService

    row = await ScheduleAlertsService(db, SettingsService(db)).update_schedule(
        current_user.id, schedule_id, payload.model_dump(exclude_unset=True),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return row


@router.delete("/alerts/schedules/{schedule_id}")
async def alerts_schedules_delete(
    schedule_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.schedule_alerts_service import ScheduleAlertsService

    ok = await ScheduleAlertsService(db, SettingsService(db)).delete_schedule(current_user.id, schedule_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"deleted": True}


@router.post("/alerts/schedules/{schedule_id}/enable")
async def alerts_schedules_enable(
    schedule_id: int,
    enabled: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.schedule_alerts_service import ScheduleAlertsService

    ok = await ScheduleAlertsService(db, SettingsService(db)).set_enabled(
        current_user.id, schedule_id, enabled,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"enabled": enabled}


@router.post("/alerts/schedules/{schedule_id}/run")
async def alerts_schedules_run(
    schedule_id: int,
    force: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.schedule_alerts_service import ScheduleAlertsService

    return await ScheduleAlertsService(db, SettingsService(db)).run_schedule(
        current_user.id, schedule_id, force=force,
    )


@router.post("/alerts/schedules/run-due")
async def alerts_schedules_run_due(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.schedule_alerts_service import ScheduleAlertsService

    return await ScheduleAlertsService(db, SettingsService(db)).run_due_for_user(current_user.id)


@router.get("/alerts/schedule-hits")
async def alerts_schedule_hits(
    schedule_id: int | None = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.schedule_alerts_service import ScheduleAlertsService

    return {
        "hits": await ScheduleAlertsService(db, SettingsService(db)).list_hits(
            current_user.id, limit=limit, schedule_id=schedule_id,
        )
    }


@router.delete("/alerts/schedule-hits/{hit_id}")
async def alerts_schedule_hit_delete(
    hit_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.schedule_alerts_service import ScheduleAlertsService

    ok = await ScheduleAlertsService(db, SettingsService(db)).delete_hit(current_user.id, hit_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Hit not found")
    return {"deleted": True, "id": hit_id}


@router.post("/alerts/schedule-hits/delete")
async def alerts_schedule_hits_delete_bulk(
    payload: AlertScheduleHitsDelete,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.schedule_alerts_service import ScheduleAlertsService

    svc = ScheduleAlertsService(db, SettingsService(db))
    if payload.delete_all:
        n = await svc.delete_all_hits(current_user.id, schedule_id=payload.schedule_id)
        return {"deleted": n, "all": True}
    n = await svc.delete_hits(current_user.id, payload.ids or [])
    return {"deleted": n, "ids": payload.ids or []}


@router.get("/watchlists")
async def watchlists_list(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return {"watchlists": await WatchlistService(db, SettingsService(db)).list_watchlists(current_user.id)}


@router.post("/watchlists")
async def watchlists_create(
    payload: WatchlistCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await WatchlistService(db, SettingsService(db)).create_watchlist(
            current_user.id, payload.market_type, payload.name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/watchlists/{watchlist_id}")
async def watchlists_delete(
    watchlist_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ok = await WatchlistService(db, SettingsService(db)).delete_watchlist(current_user.id, watchlist_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    return {"deleted": True}


@router.get("/watchlists/{watchlist_id}/items")
async def watchlists_items(
    watchlist_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await WatchlistService(db, SettingsService(db)).get_items_with_quotes(current_user.id, watchlist_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/watchlists/{watchlist_id}/items")
async def watchlists_add_item(
    watchlist_id: int,
    payload: WatchlistItemCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await WatchlistService(db, SettingsService(db)).add_item(
            current_user.id, watchlist_id, payload.ticker, payload.display_name, payload.added_price,
            notes=payload.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/watchlists/{watchlist_id}/items/{item_id}")
async def watchlists_remove_item(
    watchlist_id: int,
    item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ok = await WatchlistService(db, SettingsService(db)).remove_item(current_user.id, watchlist_id, item_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"deleted": True}


@router.post("/market-pulse/commodity-screener")
async def market_pulse_commodity(
    payload: MarketPulseCommodityRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = MarketPulseService(SettingsService(db))
    return await service.commodity_screener(payload.timeframes)


@router.get("/trading-hubs")
async def trading_hubs_list(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TradingHubService(SettingsService(db))
    return service.hubs()


@router.post("/trading-hubs/scan")
async def trading_hubs_scan(
    payload: TradingHubScanRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TradingHubService(SettingsService(db))
    return await service.scan(
        payload.section_id,
        payload.tickers,
        asset_class=payload.asset_class,
        config=payload.config,
        run_bt=payload.run_backtest,
    )


@router.get("/etf-ta/universe")
async def etf_ta_universe(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = EtfTaService(SettingsService(db))
    return service.universe()


@router.post("/etf-ta/stf-shop/scan")
async def etf_ta_stf_scan(
    payload: EtfTaScanRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = EtfTaService(SettingsService(db))
    return await service.scan(payload.symbols, payload.exchange)


@router.post("/etf-ta/stf-shop/recommend")
async def etf_ta_stf_recommend(
    payload: EtfTaRecommendRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = EtfTaService(SettingsService(db))
    return await service.recommend(payload.model_dump())


@router.get("/options/sections")
async def options_sections(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await OptionsService(SettingsService(db)).sections()


@router.post("/options/double-calendar")
async def options_double_calendar(
    payload: OptionsDoubleCalendarRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await OptionsService(SettingsService(db)).double_calendar(
        payload.tickers, asset_class=payload.asset_class, timeframes=payload.timeframes,
        exchange=payload.exchange,
        cfg_overrides={
            "short_dte": payload.short_dte,
            "long_dte": payload.long_dte,
            "otm_offset_pct": payload.otm_offset_pct,
            "diagonal_widen_pct": payload.diagonal_widen_pct,
            "take_profit_start": payload.take_profit_start,
            "take_profit_max": payload.take_profit_max,
            "stop_loss": payload.stop_loss,
            "vix_max_threshold": payload.vix_max_threshold,
            "vol_percentile_max": payload.vol_percentile_max,
        },
    )


@router.post("/options/double-calendar/pnl")
async def options_double_calendar_pnl(
    payload: OptionsDoubleCalendarPnlRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await OptionsService(SettingsService(db)).double_calendar_pnl(
        payload.net_debit, payload.current_mark,
        cfg_overrides={
            "stop_loss": payload.stop_loss,
            "take_profit_start": payload.take_profit_start,
            "take_profit_max": payload.take_profit_max,
        },
    )


@router.post("/options/delta-neutral")
async def options_delta_neutral(
    payload: OptionsDeltaNeutralRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await OptionsService(SettingsService(db)).delta_neutral(
        payload.tickers, asset_class=payload.asset_class, timeframes=payload.timeframes,
        exchange=payload.exchange,
        cfg_overrides={
            "dte": payload.dte,
            "short_delta_target": payload.short_delta_target,
            "wing_width_pct": payload.wing_width_pct,
            "iron_fly": payload.iron_fly,
            "profit_target_pct": payload.profit_target_pct,
            "stop_loss_multiple": payload.stop_loss_multiple,
            "vix_max_threshold": payload.vix_max_threshold,
            "vol_percentile_max": payload.vol_percentile_max,
            "adx_trend_max": payload.adx_trend_max,
        },
    )


@router.post("/options/delta-neutral/pnl")
async def options_delta_neutral_pnl(
    payload: OptionsDeltaNeutralPnlRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await OptionsService(SettingsService(db)).delta_neutral_pnl(
        payload.net_credit, payload.current_cost_to_close,
        cfg_overrides={
            "profit_target_pct": payload.profit_target_pct,
            "stop_loss_multiple": payload.stop_loss_multiple,
        },
    )


@router.post("/options/gokul-chhabra")
async def options_gokul_chhabra(
    payload: OptionsGokulChhabraRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await OptionsService(SettingsService(db)).gokul_chhabra(
        tickers=payload.tickers,
        exchange=payload.exchange,
        cfg_overrides={
            "vwma_length": payload.vwma_length,
            "st_period": payload.st_period,
            "st_multiplier": payload.st_multiplier,
            "session_start": payload.session_start,
            "session_end": payload.session_end,
            "pullback_tol_pct": payload.pullback_tol_pct,
            "min_rr": payload.min_rr,
            "target_delta_min": payload.target_delta_min,
            "target_delta_max": payload.target_delta_max,
        },
    )
