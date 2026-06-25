from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.db_models import User
from app.models.schemas import (
    BacktestRequest,
    BacktestResponse,
    ForgotPasswordRequest,
    MarketPulseCommodityRequest,
    MarketPulseHeatmapRequest,
    MarketPulseIndexRequest,
    MarketPulseMtfRequest,
    MarketPulsePagination,
    MarketPulseRotationRequest,
    MarketPulseSentimentRequest,
    MarketPulseTickerInvestigationRequest,
    MessageResponse,
    PlaceOrderRequest,
    ResetPasswordRequest,
    ScanRequest,
    ScanResponse,
    SettingsResponse,
    SettingsUpdate,
    StrategyInfo,
    StrategyCategoryInfo,
    TokenResponse,
    TradingHubScanRequest,
    UserLogin,
    UserOut,
    UserRegister,
)
from app.services.auth_service import AuthService
from app.services.backtest_service import BacktestService
from app.services.market_pulse_service import MarketPulseService
from app.services.paper_trading_service import PaperTradingService
from app.services.scanner_service import ScannerService
from app.services.trading_hub_service import TradingHubService
from app.services.settings_service import SettingsService
from app.strategies.registry import STRATEGY_META, list_categories

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
    return [StrategyInfo(**meta) for meta in STRATEGY_META.values()]


@router.get("/strategies/categories", response_model=list[StrategyCategoryInfo])
async def list_strategy_categories():
    return [StrategyCategoryInfo(**cat) for cat in list_categories()]


@router.get("/strategies/{strategy_id}", response_model=StrategyInfo)
async def get_strategy_detail(strategy_id: str):
    meta = STRATEGY_META.get(strategy_id)
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
            {"id": "sector_rotation", "label": "Sector Rotation (HTF)"},
            {"id": "sector_rotation_intraday", "label": "Sector Rotation (Intraday)"},
            {"id": "opposite_hedge", "label": "Opposite Hedge-MTF"},
            {"id": "mtf_bias", "label": "MTF Intraday Bias"},
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
    return await service.mtf_bias(payload.tickers)


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
    return await service.ticker_investigation(payload.tickers)


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
        config=payload.config,
        run_bt=payload.run_backtest,
    )
