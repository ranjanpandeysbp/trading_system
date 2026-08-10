from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, track_data_sources
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
    Etf28SmaScanRequest,
    EtfTopDownScanRequest,
    FallingKnifeScanRequest,
    EtfShopAddLotRequest,
    EtfShopCloseLotRequest,
    EtfShopConfigUpdateRequest,
    EtfTaRecommendRequest,
    EtfTaScanRequest,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    AutoTradeSetupCreateRequest,
    AutoTradeSetupUpdateRequest,
    InvestingAgentChatRequest,
    InvestingAgentStockRequest,
    InvestingAgentTokenRequest,
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
    SaveMfHoldingsReportRequest,
    CommandCenterBestMfRequest,
    SaveBestMfReportRequest,
    MfFirePlanRequest,
    TradingHubBackgroundScanRequest,
    SaveTradingHubReportRequest,
    CommandCenterEtfIndiaHoldingsRequest,
    CommandCenterEtfYahooHoldingsRequest,
    SaveEtfHoldingsReportRequest,
    CommandCenterIndiaFiiDiiHoldingsRequest,
    SaveFiiDiiHoldingsReportRequest,
    SaveSmartMoneyActivityReportRequest,
    CommandCenterSmartMoneyActivityRequest,
    CommandCenterHeatmapRequest,
    CommandCenterAdvanceDeclineGraphRequest,
    CommandCenterComparativeStrengthRequest,
    CommandCenterOilDollarBondRequest,
    CommandCenterOneClickRequest,
    CommandCenterOptionChainRequest,
    CommandCenterOptionShortLongRequest,
    CommandCenterQuickAnalyzerRequest,
    CommandCenterSma20200Request,
    CommandCenterMarketMoversRequest,
    CommandCenterTickerScanRequest,
    CommandCenterTradeSetupDrillRequest,
    DetectSectorRotationRequest,
    CommandCenterTradeSetupRequest,
    TodoCreateRequest,
    TodoUpdateRequest,
    WatchlistCreate,
    WatchlistItemCreate,
    WatchlistItemUpdate,
    MarketPulseTickerInvestigationRequest,
    MessageResponse,
    BulkIdsRequest,
    ModifyOrderRequest,
    OptionsDeltaNeutralPnlRequest,
    OptionsDeltaNeutralRequest,
    OptionsDoubleCalendarPnlRequest,
    OptionsDoubleCalendarRequest,
    OptionsGokulChhabraRequest,
    OptionsMarketPredictionRequest,
    OptionsCallPutWritingRequest,
    BramhastraChartRequest,
    OptionsHedgingPnlRequest,
    OptionsHedgingRequest,
    OptionsZeroToHeroRequest,
    OptionsBackgroundStartRequest,
    SaveOptionsReportRequest,
    AnalysisBackgroundStartRequest,
    SaveAnalysisReportRequest,
    ProTradeVolumeProfileCeRequest,
    ProTradeVolumeProfilePocRequest,
    ProTradePaVolumeProfileRequest,
    ProTradePaVpSmcRequest,
    ProTradeVolumeSpreadNextCandleRequest,
    ProTradeElliottWaveRequest,
    ProTradeFibonacciProRequest,
    ProTradeBbMeanReversionRequest,
    ProTradeTrafficLightRequest,
    ProTradeBuyLowSellHighRequest,
    ProTradeRlbBreakoutRequest,
    ProTradeThreeInOneRequest,
    ProTradeSimpleEffectiveRequest,
    ProTradeBbRsiVolRequest,
    ProTradeBtstRequest,
    ProTradeTickerChartRequest,
    DashboardTradingChatRequest,
    PlaceOrderRequest,
    PredictionPatternAnalogueRequest,
    PredictionAstroFinanceRequest,
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
    StrategyLeaderboardRequest,
    SaveBacktestReportRequest,
    AIStrategyGenerateRequest,
    BacktesterLeaderboardRequest,
    CustomStrategyCreate,
    CustomStrategyUpdate,
    TokenResponse,
    Swing5ScanRequest,
    SupportResistanceChartRequest,
    TradeCandidateCreate,
    TradeCandidateHitsDelete,
    TradeCandidateUpdate,
    TradingHubScanRequest,
    TaScreenerRunRequest,
    UserLogin,
    UserOut,
    UserRegister,
    SaveYoutubeAiViewRequest,
    UpdateYoutubeAiViewRequest,
    WorkflowEvaluateRequest,
    YoutubeAnalysisAiViewRequest,
    YoutubeAnalysisScanRequest,
)
from app.services.command_center_service import CommandCenterService
from app.services.options_service import OptionsService
from app.services.pro_trade_service import ProTradeService
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
from app.services.strategy_leaderboard_service import StrategyLeaderboardService
from app.services.backtester_leaderboard_service import BacktesterLeaderboardService
from app.services.ta_screener_service import TaScreenerService
from app.services.etf_ta_service import EtfTaService
from app.services.trading_hub_service import TradingHubService
from app.services.settings_service import SettingsService
from app.services.youtube_analysis_service import (
    YOUTUBE_MARKET_SYSTEM,
    build_market_ai_context,
    delete_youtube_ai_view,
    get_youtube_ai_view,
    list_youtube_ai_views,
    save_youtube_ai_view,
    scan_channels,
    scan_videos,
    update_youtube_ai_view,
)
from app.strategies.registry import (
    all_strategy_meta_for_api,
    get_strategy_meta_for_api,
    list_categories,
    list_scanner_categories,
)

router = APIRouter(prefix="/api/v1", dependencies=[Depends(track_data_sources)])


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


@router.post("/auth/change-password", response_model=MessageResponse)
async def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = AuthService(db)
    try:
        return await service.change_password(current_user, payload.old_password, payload.new_password)
    except ValueError as exc:
        # Always 400 — 401 would clear the session via the FE auth interceptor.
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
    from app.market_pulse.data_source_ctx import summarize_sources

    meta = summarize_sources()
    return ScanResponse(
        signals=signals,
        scanned_at=datetime.now(timezone.utc).isoformat(),
        data_source=meta.get("data_source"),
        data_sources_used=meta.get("data_sources_used"),
        data_source_label=meta.get("data_source_label"),
        data_source_counts=meta.get("data_source_counts"),
    )


@router.get("/falling-knife/session")
async def falling_knife_session(
    asset_class: str = "india",
    current_user: User = Depends(get_current_user),
):
    from app.market_pulse.falling_knife_engine import session_info
    from app.market_pulse.serialize import json_safe

    return json_safe({"asset_class": asset_class, "session": session_info(asset_class)})


@router.post("/falling-knife/scan")
async def falling_knife_scan(
    payload: FallingKnifeScanRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.falling_knife_service import FallingKnifeService

    return await FallingKnifeService(SettingsService(db)).scan(payload.model_dump())


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
    return SettingsResponse(**await service.get_all(current_user.id))


@router.put("/settings", response_model=SettingsResponse)
async def update_settings(
    payload: SettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = SettingsService(db)
    data = payload.model_dump(exclude_unset=True)
    return SettingsResponse(**await service.update(data, user_id=current_user.id))


@router.post("/settings/test-provider")
async def test_provider(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.data.factory import DataProviderFactory

    settings = SettingsService(db)
    await settings.prepare_market_data()
    provider = await DataProviderFactory.get_provider(settings)
    return await provider.health_check()


@router.post("/settings/indmoney/refresh-token")
async def refresh_indmoney_token(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Force TOTP → access token refresh for IndMoney / INDstocks."""
    settings = SettingsService(db)
    token = await settings.get_indmoney_access_token(force_refresh=True)
    if not token:
        return {
            "ok": False,
            "error": "Could not refresh token. Save Client ID, MPIN, and TOTP secret first "
            "(from indstocks.com → API Trading → Setup TOTP).",
        }
    return {
        "ok": True,
        "indmoney_access_token_set": True,
        "indmoney_token_expires_at": await settings.get_indmoney_token_expires_at(),
    }


@router.post("/settings/groww/refresh-token")
async def refresh_groww_token(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Force TOTP → access token refresh for Groww Trading API."""
    settings = SettingsService(db)
    token = await settings.get_groww_access_token(force_refresh=True)
    if not token:
        return {
            "ok": False,
            "error": "Could not refresh Groww token. Save Groww TOTP API key + TOTP secret "
            "(Groww → Trading APIs → Generate TOTP token), or paste an access token.",
        }
    return {
        "ok": True,
        "groww_token_set": True,
        "groww_token_expires_at": await settings.get_groww_token_expires_at(),
    }


@router.get("/markets")
async def list_markets():
    from app.market_pulse.ticker_utils import MARKET_OPTIONS
    return {"markets": MARKET_OPTIONS}


@router.get("/market/marquee")
async def market_marquee(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Popular India / US / Crypto / Commodity LTPs for the header marquee."""
    from app.services.marquee_quotes_service import fetch_marquee_quotes

    settings = SettingsService(db)
    token, _ = await settings.prepare_market_data()
    return await fetch_marquee_quotes(groww_token=token)


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
            mode=payload.mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AskAIResponse(**result)


@router.post("/dashboard/trading-chat")
async def dashboard_trading_chat(
    payload: DashboardTradingChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Ask what to buy/sell (top picks or single ticker) via BB + confluence + Manage AI."""
    from app.services.dashboard_trading_chat_service import DashboardTradingChatService

    service = DashboardTradingChatService(SettingsService(db), db=db)
    return await service.chat(
        message=payload.message,
        asset_class=payload.asset_class,
        style=payload.style,
        tickers=payload.tickers,
        extra_checks=payload.extra_checks or None,
        top_n=payload.top_n,
        skip_ai=payload.skip_ai,
        deep_mode=payload.deep_mode,
        explain_only=payload.explain_only,
        prior_result=payload.prior_result,
    )


@router.get("/investing-agent/status")
async def investing_agent_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    settings = SettingsService(db)
    return {"token_set": bool(await settings.get_superinvesting_token())}


@router.put("/investing-agent/token")
async def investing_agent_save_token(
    payload: InvestingAgentTokenRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    settings = SettingsService(db)
    await settings.update({"superinvesting_token": payload.token.strip()})
    return {"token_set": True, "message": "Token saved. It will be used until you replace it."}


@router.post("/investing-agent/chat")
async def investing_agent_chat(
    payload: InvestingAgentChatRequest,
    current_user: User = Depends(get_current_user),
):
    """Stream SuperInvesting analysis (SSE). Index questions like 'nifty analysis' use chat, not stock card."""
    from app.core.database import AsyncSessionLocal
    from app.services.superinvesting_service import run_analysis_stream

    # Resolve token in a short-lived session — do not hold DB open for the 1–3 min stream.
    async with AsyncSessionLocal() as session:
        token = await SettingsService(session).get_superinvesting_token()
    if not token:
        raise HTTPException(
            status_code=400,
            detail="Save a SuperInvesting Bearer token at the top of Investing Agent first.",
        )
    message = payload.message.strip()
    return StreamingResponse(
        run_analysis_stream(token, message),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/investing-agent/stock/card")
async def investing_agent_stock_card(
    symbol: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.superinvesting_service import SuperInvestingError, SuperInvestingService

    settings = SettingsService(db)
    token = await settings.get_superinvesting_token()
    if not token:
        raise HTTPException(status_code=400, detail="Save a SuperInvesting Bearer token first.")
    try:
        return await SuperInvestingService(token).stock_card(symbol.strip())
    except SuperInvestingError as exc:
        raise HTTPException(status_code=exc.status_code or 400, detail=str(exc)) from exc


@router.post("/investing-agent/stock/detail")
async def investing_agent_stock_detail(
    payload: InvestingAgentStockRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.superinvesting_service import SuperInvestingError, SuperInvestingService

    settings = SettingsService(db)
    token = await settings.get_superinvesting_token()
    if not token:
        raise HTTPException(status_code=400, detail="Save a SuperInvesting Bearer token first.")
    try:
        return await SuperInvestingService(token).stock_detail(payload.symbol.strip())
    except SuperInvestingError as exc:
        raise HTTPException(status_code=exc.status_code or 400, detail=str(exc)) from exc


@router.get("/investing-agent/search")
async def investing_agent_search(
    query: str,
    page: int = 1,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.superinvesting_service import SuperInvestingError, SuperInvestingService

    settings = SettingsService(db)
    token = await settings.get_superinvesting_token()
    if not token:
        raise HTTPException(status_code=400, detail="Save a SuperInvesting Bearer token first.")
    try:
        return await SuperInvestingService(token).stock_search(query.strip(), page=page, limit=limit)
    except SuperInvestingError as exc:
        raise HTTPException(status_code=exc.status_code or 400, detail=str(exc)) from exc


@router.get("/investing-agent/starters")
async def investing_agent_starters(
    current_user: User = Depends(get_current_user),
):
    from app.services.superinvesting_service import SuperInvestingService

    return await SuperInvestingService.fetch_starters()


@router.post("/youtube-analysis/scan")
async def youtube_analysis_scan(
    payload: YoutubeAnalysisScanRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    import asyncio
    from datetime import date, timedelta

    settings = SettingsService(db)
    api_key = (payload.youtube_api_key or "").strip() or (
        await settings.get_youtube_api_key(current_user.id) or ""
    )
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="YouTube Data API key is required. Enter it once — it will be saved for your account.",
        )

    gemini_key = await settings.get_gemini_api_key()
    if payload.fetch_transcripts and not gemini_key:
        raise HTTPException(
            status_code=400,
            detail="Gemini API key is required for transcripts. Add it under Manage Settings (or GEMINI_API_KEY).",
        )

    video_items = [str(v).strip() for v in (payload.video_urls or []) if str(v).strip()]
    channel_items = [str(c).strip() for c in (payload.channel_ids or []) if str(c).strip()]
    # Prefer explicit video list; fall back to channel_ids payload for older clients
    prefs_text = "\n".join(video_items or channel_items)
    await settings.save_youtube_prefs(
        current_user.id,
        youtube_api_key=(payload.youtube_api_key or "").strip() or None,
        youtube_channel_ids=prefs_text,
    )

    today = date.today()
    try:
        to_d = date.fromisoformat(payload.to_date) if payload.to_date else today
        from_d = date.fromisoformat(payload.from_date) if payload.from_date else (to_d - timedelta(days=4))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid date: {exc}") from exc

    gemini_model = await settings.get_gemini_model()
    if video_items:
        result = await asyncio.to_thread(
            scan_videos,
            api_key=api_key,
            video_urls=video_items,
            from_date=None,
            to_date=None,
            fetch_transcripts=payload.fetch_transcripts,
            gemini_api_key=gemini_key,
            gemini_model=gemini_model,
        )
    else:
        result = await asyncio.to_thread(
            scan_channels,
            api_key=api_key,
            channel_ids=channel_items,
            from_date=from_d,
            to_date=to_d,
            max_per_channel=payload.max_per_channel,
            fetch_transcripts=payload.fetch_transcripts,
            gemini_api_key=gemini_key,
            gemini_model=gemini_model,
        )
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])

    result["ai_context"] = build_market_ai_context(result)
    result["ai_system_prompt"] = YOUTUBE_MARKET_SYSTEM
    result["youtube_api_key_set"] = True
    result["youtube_channel_ids"] = await settings.get_youtube_channel_ids(current_user.id)
    result["gemini_token_set"] = bool(gemini_key)
    return result


@router.get("/youtube-analysis/prefs")
async def youtube_analysis_prefs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    settings = SettingsService(db)
    return {
        "youtube_api_key_set": bool(await settings.get_youtube_api_key(current_user.id)),
        "youtube_channel_ids": await settings.get_youtube_channel_ids(current_user.id),
        "gemini_token_set": bool(await settings.get_gemini_api_key()),
        "gemini_model": await settings.get_gemini_model(),
    }


@router.put("/youtube-analysis/prefs")
async def youtube_analysis_prefs_save(
    payload: SettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Save YouTube API key / channel IDs without running a scan."""
    settings = SettingsService(db)
    await settings.save_youtube_prefs(
        current_user.id,
        youtube_api_key=payload.youtube_api_key,
        youtube_channel_ids=payload.youtube_channel_ids,
    )
    return {
        "youtube_api_key_set": bool(await settings.get_youtube_api_key(current_user.id)),
        "youtube_channel_ids": await settings.get_youtube_channel_ids(current_user.id),
        "gemini_token_set": bool(await settings.get_gemini_api_key()),
        "gemini_model": await settings.get_gemini_model(),
    }


@router.post("/youtube-analysis/ai-view", response_model=AskAIResponse)
async def youtube_analysis_ai_view(
    payload: YoutubeAnalysisAiViewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    context = (payload.ai_context or "").strip()
    if not context and payload.scan:
        context = build_market_ai_context(payload.scan)
    if not context:
        raise HTTPException(status_code=400, detail="Provide ai_context or a prior scan payload.")

    service = AIService(SettingsService(db))
    try:
        result = await service.ask(
            context=context,
            question=payload.question
            or (
                "Summarize these YouTube transcripts into a clear market view. "
                "Explain likely stock-market impact for the next few days and the next 1–2 weeks."
            ),
            system_prompt=YOUTUBE_MARKET_SYSTEM,
            section="youtube-analysis/ai-view",
            max_tokens=payload.max_tokens,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AskAIResponse(**result)


@router.post("/youtube-analysis/ai-views")
async def youtube_analysis_save_ai_view(
    payload: SaveYoutubeAiViewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await save_youtube_ai_view(
        db, current_user.id,
        name=payload.name,
        payload=payload.model_dump(exclude={"name"}),
    )


@router.get("/youtube-analysis/ai-views")
async def youtube_analysis_list_ai_views(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await list_youtube_ai_views(db, user_id=current_user.id)


@router.get("/youtube-analysis/ai-views/{view_id}")
async def youtube_analysis_get_ai_view(
    view_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await get_youtube_ai_view(db, view_id, user_id=current_user.id)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.put("/youtube-analysis/ai-views/{view_id}")
async def youtube_analysis_update_ai_view(
    view_id: int,
    payload: UpdateYoutubeAiViewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await update_youtube_ai_view(
        db, view_id, user_id=current_user.id, name=payload.name, report_text=payload.report,
    )
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.delete("/youtube-analysis/ai-views/{view_id}")
async def youtube_analysis_delete_ai_view(
    view_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await delete_youtube_ai_view(db, view_id, user_id=current_user.id)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/paper/account")
async def get_paper_account(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    settings = SettingsService(db)
    service = PaperTradingService(db, settings, user_id=current_user.id)
    return await service.get_summary()


@router.get("/paper/price")
async def get_paper_price(
    ticker: str,
    asset_class: str = "india",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    settings = SettingsService(db)
    service = PaperTradingService(db, settings, user_id=current_user.id)
    try:
        return await service.get_price(ticker, asset_class)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not fetch a price for {ticker}: {exc}") from exc


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


@router.post("/paper/orders/delete-bulk")
async def delete_paper_orders(
    payload: BulkIdsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    settings = SettingsService(db)
    service = PaperTradingService(db, settings, user_id=current_user.id)
    try:
        return await service.delete_orders(payload.ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/paper/positions/close-bulk")
async def close_paper_positions(
    payload: BulkIdsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    settings = SettingsService(db)
    service = PaperTradingService(db, settings, user_id=current_user.id)
    try:
        return await service.close_positions(payload.ids)
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


@router.post("/command-center/mtf-trend-strength")
async def command_center_mtf_trend_strength(
    payload: CommandCenterTickerScanRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).mtf_trend_strength(
        payload.tickers,
        asset_class=payload.asset_class,
        timeframes=payload.timeframes,
        from_date=payload.from_date,
        to_date=payload.to_date,
    )


@router.get("/command-center/market-movers/options")
async def command_center_market_movers_options(
    asset_class: str = "india",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).market_movers_options(asset_class)


@router.post("/command-center/market-movers")
async def command_center_market_movers(
    payload: CommandCenterMarketMoversRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).market_movers(
        payload.asset_class, payload.index, payload.timeframe,
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


@router.post("/command-center/mutual-fund/holdings/start")
async def command_center_mf_holdings_start(
    payload: CommandCenterMfHoldingsRequest,
    current_user: User = Depends(get_current_user),
):
    """Kick off the holdings-change analysis as a background job and return
    immediately with a job id. Poll GET
    /command-center/mutual-fund/holdings/jobs/{id} for progress and result.

    When ``run_in_background`` is true (or ``report_name`` is set), the
    finished result is auto-saved under that name for later viewing.
    """
    from app.services.mf_holdings_jobs import MF_HOLDINGS_SOURCE, create_job, run_mf_holdings_job

    report_name = (payload.report_name or "").strip() or None
    auto_save = bool(payload.run_in_background or report_name)
    if payload.run_in_background and not report_name:
        raise HTTPException(status_code=400, detail="Report name is required for background runs.")

    job = await create_job(
        name=report_name,
        user_id=current_user.id,
        source=MF_HOLDINGS_SOURCE,
        meta={
            "scheme_names": list(payload.scheme_names.values()),
            "from_date": payload.from_date,
            "to_date": payload.to_date,
            "auto_save": auto_save,
        },
        request_payload={
            "scheme_ids": payload.scheme_ids,
            "scheme_names": payload.scheme_names,
            "from_date": payload.from_date,
            "to_date": payload.to_date,
            "report_name": report_name if auto_save else None,
        },
    )
    run_mf_holdings_job(
        job.id, payload.scheme_ids, payload.scheme_names, payload.from_date, payload.to_date,
        report_name=report_name if auto_save else None,
        user_id=current_user.id if auto_save else None,
    )
    return {
        "job_id": job.id,
        "status": job.status,
        "name": job.name,
        "auto_save": auto_save,
    }


@router.get("/command-center/mutual-fund/holdings/jobs")
async def command_center_mf_holdings_list_jobs(
    status: str | None = "running",
    current_user: User = Depends(get_current_user),
):
    from app.services.mf_holdings_jobs import MF_HOLDINGS_SOURCE, job_to_dict, list_jobs

    jobs = list_jobs(user_id=current_user.id, source=MF_HOLDINGS_SOURCE, status=status or None)
    return {"jobs": [job_to_dict(j) for j in jobs]}


@router.get("/command-center/mutual-fund/holdings/jobs/{job_id}")
async def command_center_mf_holdings_job_status(
    job_id: str,
    current_user: User = Depends(get_current_user),
):
    from app.services.mf_holdings_jobs import get_job, job_to_dict

    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found (it may have expired).")
    if job.user_id is not None and job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found (it may have expired).")
    return job_to_dict(job)


@router.post("/command-center/mutual-fund/holdings/reports")
async def command_center_mf_holdings_save_report(
    payload: SaveMfHoldingsReportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = CommandCenterService(SettingsService(db), db)
    result = payload.payload
    return await service.save_mutual_fund_holdings_report(
        payload.name,
        result.get("scheme_ids", []),
        result.get("scheme_names", {}),
        (result.get("dates") or [None])[0] or "",
        (result.get("dates") or [None, None])[-1] or "",
        result,
        user_id=current_user.id,
    )


@router.get("/command-center/mutual-fund/holdings/reports")
async def command_center_mf_holdings_list_reports(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = CommandCenterService(SettingsService(db), db)
    return await service.list_mutual_fund_holdings_reports(user_id=current_user.id)


@router.get("/command-center/mutual-fund/holdings/reports/{report_id}")
async def command_center_mf_holdings_get_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = CommandCenterService(SettingsService(db), db)
    return await service.get_mutual_fund_holdings_report(report_id, user_id=current_user.id)


@router.delete("/command-center/mutual-fund/holdings/reports/{report_id}")
async def command_center_mf_holdings_delete_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = CommandCenterService(SettingsService(db), db)
    return await service.delete_mutual_fund_holdings_report(report_id, user_id=current_user.id)


@router.get("/best-mf/options")
async def best_mf_options(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AMC list is shared with Mutual Fund Holdings — GET /command-center/mutual-fund/amcs."""
    return await CommandCenterService(SettingsService(db)).best_mf_options()


@router.post("/best-mf/run")
async def best_mf_run(
    payload: CommandCenterBestMfRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).best_mf_run(
        payload.amc_ids, payload.asset_type_id,
        category_filter=payload.category_filter, rank_period=payload.rank_period, top_n=payload.top_n,
    )


@router.post("/best-mf/start")
async def best_mf_start(
    payload: CommandCenterBestMfRequest,
    current_user: User = Depends(get_current_user),
):
    """Kick off the ranking run as a background job and return immediately
    with a job id. Poll GET /best-mf/jobs/{id} for progress and result.

    When ``run_in_background`` is true (or ``report_name`` is set), the
    finished result is auto-saved under that name for later viewing.
    """
    from app.services.best_mf_jobs import BEST_MF_SOURCE, create_job, run_best_mf_job

    report_name = (payload.report_name or "").strip() or None
    auto_save = bool(payload.run_in_background or report_name)
    if payload.run_in_background and not report_name:
        raise HTTPException(status_code=400, detail="Report name is required for background runs.")

    job = await create_job(
        name=report_name,
        user_id=current_user.id,
        source=BEST_MF_SOURCE,
        meta={
            "amc_count": len(payload.amc_ids),
            "asset_type_id": payload.asset_type_id,
            "category_filter": payload.category_filter,
            "rank_period": payload.rank_period,
            "auto_save": auto_save,
        },
        request_payload={
            "amc_ids": payload.amc_ids,
            "asset_type_id": payload.asset_type_id,
            "category_filter": payload.category_filter,
            "rank_period": payload.rank_period,
            "top_n": payload.top_n,
            "report_name": report_name if auto_save else None,
        },
    )
    run_best_mf_job(
        job.id, payload.amc_ids, payload.asset_type_id,
        category_filter=payload.category_filter, rank_period=payload.rank_period, top_n=payload.top_n,
        report_name=report_name if auto_save else None,
        user_id=current_user.id if auto_save else None,
    )
    return {
        "job_id": job.id,
        "status": job.status,
        "name": job.name,
        "auto_save": auto_save,
    }


@router.get("/best-mf/jobs")
async def best_mf_list_jobs(
    status: str | None = "running",
    current_user: User = Depends(get_current_user),
):
    from app.services.best_mf_jobs import BEST_MF_SOURCE, job_to_dict, list_jobs

    jobs = list_jobs(user_id=current_user.id, source=BEST_MF_SOURCE, status=status or None)
    return {"jobs": [job_to_dict(j) for j in jobs]}


@router.get("/best-mf/jobs/{job_id}")
async def best_mf_job_status(
    job_id: str,
    current_user: User = Depends(get_current_user),
):
    from app.services.best_mf_jobs import get_job, job_to_dict

    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found (it may have expired).")
    if job.user_id is not None and job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found (it may have expired).")
    return job_to_dict(job)


@router.post("/best-mf/reports")
async def best_mf_save_report(
    payload: SaveBestMfReportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = CommandCenterService(SettingsService(db), db)
    return await service.save_best_mf_report(payload.name, payload.payload, user_id=current_user.id)


@router.get("/best-mf/reports")
async def best_mf_list_reports(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = CommandCenterService(SettingsService(db), db)
    return await service.list_best_mf_reports(user_id=current_user.id)


@router.get("/best-mf/reports/{report_id}")
async def best_mf_get_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = CommandCenterService(SettingsService(db), db)
    return await service.get_best_mf_report(report_id, user_id=current_user.id)


@router.delete("/best-mf/reports/{report_id}")
async def best_mf_delete_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = CommandCenterService(SettingsService(db), db)
    return await service.delete_best_mf_report(report_id, user_id=current_user.id)


@router.get("/mf-fire/guide")
async def mf_fire_guide(
    current_user: User = Depends(get_current_user),
):
    from app.market_pulse.mf_fire_engine import HOW_IT_WORKS, PRINCIPLES, STRATEGY_NAME, YOUTUBE_URL

    return {
        "strategy": "mf_fire",
        "strategy_label": STRATEGY_NAME,
        "youtube": YOUTUBE_URL,
        "how_it_works": HOW_IT_WORKS,
        "principles": PRINCIPLES,
    }


@router.post("/mf-fire/plan")
async def mf_fire_plan(
    payload: MfFirePlanRequest,
    current_user: User = Depends(get_current_user),
):
    from app.market_pulse.mf_fire_engine import MfFireConfig, build_mf_fire_ai_prompt, plan_mf_fire
    from app.market_pulse.serialize import json_safe

    cfg = MfFireConfig(
        annual_expenses=payload.annual_expenses,
        monthly_salary=payload.monthly_salary,
        current_corpus=payload.current_corpus,
        monthly_sip=payload.monthly_sip,
        expected_equity_return_pct=payload.expected_equity_return_pct,
        inflation_pct=payload.inflation_pct,
        fire_multiple=payload.fire_multiple,
        long_runway_multiple=payload.long_runway_multiple,
        equity_only_until_cr=payload.equity_only_until_cr,
        age=payload.age,
        home_loan_balance=payload.home_loan_balance,
        home_loan_rate_pct=payload.home_loan_rate_pct,
        extra_emi_toward_loan=payload.extra_emi_toward_loan,
        dual_income=payload.dual_income,
        principles_checklist=list(payload.principles_checklist or []),
    )
    result = plan_mf_fire(cfg)
    result["ai_context"] = build_mf_fire_ai_prompt(result)
    return json_safe(result)


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


@router.post("/command-center/etf/holdings/india/start")
async def command_center_etf_holdings_india_start(
    payload: CommandCenterEtfIndiaHoldingsRequest,
    current_user: User = Depends(get_current_user),
):
    """Kick off the India ETF holdings-change analysis as a background job.
    Poll GET /command-center/etf/holdings/jobs/{id} for progress and result."""
    from app.services.etf_holdings_jobs import ETF_HOLDINGS_SOURCE, create_job, run_etf_holdings_job

    report_name = (payload.report_name or "").strip() or None
    auto_save = bool(payload.run_in_background or report_name)
    if payload.run_in_background and not report_name:
        raise HTTPException(status_code=400, detail="Report name is required for background runs.")

    job = await create_job(
        name=report_name,
        user_id=current_user.id,
        source=ETF_HOLDINGS_SOURCE,
        meta={
            "asset_class": "india",
            "names": list(payload.scheme_names.values()),
            "from_date": payload.from_date,
            "to_date": payload.to_date,
            "auto_save": auto_save,
        },
        request_payload={
            "asset_class": "india",
            "scheme_ids": payload.scheme_ids,
            "scheme_names": payload.scheme_names,
            "symbols": [],
            "symbol_names": {},
            "from_date": payload.from_date,
            "to_date": payload.to_date,
            "report_name": report_name if auto_save else None,
        },
    )
    run_etf_holdings_job(
        job.id, "india", payload.scheme_ids, payload.scheme_names, [], {},
        payload.from_date, payload.to_date,
        report_name=report_name if auto_save else None,
        user_id=current_user.id if auto_save else None,
    )
    return {"job_id": job.id, "status": job.status, "name": job.name, "auto_save": auto_save}


@router.post("/command-center/etf/holdings/yahoo/start")
async def command_center_etf_holdings_yahoo_start(
    payload: CommandCenterEtfYahooHoldingsRequest,
    current_user: User = Depends(get_current_user),
):
    """Kick off the US/Crypto ETF holdings-change analysis as a background
    job. Poll GET /command-center/etf/holdings/jobs/{id} for progress/result."""
    from app.services.etf_holdings_jobs import ETF_HOLDINGS_SOURCE, create_job, run_etf_holdings_job

    report_name = (payload.report_name or "").strip() or None
    auto_save = bool(payload.run_in_background or report_name)
    if payload.run_in_background and not report_name:
        raise HTTPException(status_code=400, detail="Report name is required for background runs.")

    job = await create_job(
        name=report_name,
        user_id=current_user.id,
        source=ETF_HOLDINGS_SOURCE,
        meta={
            "asset_class": payload.market,
            "names": list(payload.symbol_names.values()) or payload.symbols,
            "from_date": payload.from_date,
            "to_date": payload.to_date,
            "auto_save": auto_save,
        },
        request_payload={
            "asset_class": payload.market,
            "scheme_ids": [],
            "scheme_names": {},
            "symbols": payload.symbols,
            "symbol_names": payload.symbol_names,
            "from_date": payload.from_date,
            "to_date": payload.to_date,
            "report_name": report_name if auto_save else None,
        },
    )
    run_etf_holdings_job(
        job.id, payload.market, [], {}, payload.symbols, payload.symbol_names,
        payload.from_date, payload.to_date,
        report_name=report_name if auto_save else None,
        user_id=current_user.id if auto_save else None,
    )
    return {"job_id": job.id, "status": job.status, "name": job.name, "auto_save": auto_save}


@router.get("/command-center/etf/holdings/jobs")
async def command_center_etf_holdings_list_jobs(
    status: str | None = "running",
    current_user: User = Depends(get_current_user),
):
    from app.services.etf_holdings_jobs import ETF_HOLDINGS_SOURCE, job_to_dict, list_jobs

    jobs = list_jobs(user_id=current_user.id, source=ETF_HOLDINGS_SOURCE, status=status or None)
    return {"jobs": [job_to_dict(j) for j in jobs]}


@router.get("/command-center/etf/holdings/jobs/{job_id}")
async def command_center_etf_holdings_job_status(
    job_id: str,
    current_user: User = Depends(get_current_user),
):
    from app.services.etf_holdings_jobs import get_job, job_to_dict

    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found (it may have expired).")
    if job.user_id is not None and job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found (it may have expired).")
    return job_to_dict(job)


@router.post("/command-center/etf/holdings/reports")
async def command_center_etf_holdings_save_report(
    payload: SaveEtfHoldingsReportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = CommandCenterService(SettingsService(db), db)
    result = payload.payload
    asset_class = str(result.get("market") or "india")
    scheme_names = result.get("scheme_names") or {}
    names = list(scheme_names.values()) if isinstance(scheme_names, dict) else []
    dates = result.get("dates") or []
    return await service.save_etf_holdings_report(
        payload.name,
        asset_class,
        names,
        str(dates[0])[:10] if dates else "",
        str(dates[-1])[:10] if dates else "",
        result,
        user_id=current_user.id,
    )


@router.get("/command-center/etf/holdings/reports")
async def command_center_etf_holdings_list_reports(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = CommandCenterService(SettingsService(db), db)
    return await service.list_etf_holdings_reports(user_id=current_user.id)


@router.get("/command-center/etf/holdings/reports/{report_id}")
async def command_center_etf_holdings_get_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = CommandCenterService(SettingsService(db), db)
    return await service.get_etf_holdings_report(report_id, user_id=current_user.id)


@router.delete("/command-center/etf/holdings/reports/{report_id}")
async def command_center_etf_holdings_delete_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = CommandCenterService(SettingsService(db), db)
    return await service.delete_etf_holdings_report(report_id, user_id=current_user.id)


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


@router.post("/command-center/smart-money-activity/start")
async def command_center_smart_money_activity_start(
    payload: CommandCenterSmartMoneyActivityRequest,
    current_user: User = Depends(get_current_user),
):
    """Kick off the Smart Money Activity scan as a background job. Poll GET
    /command-center/smart-money-activity/jobs/{id} for progress and result."""
    from app.services.smart_money_activity_jobs import (
        SMART_MONEY_ACTIVITY_SOURCE,
        create_job,
        run_smart_money_activity_job,
    )

    report_name = (payload.report_name or "").strip() or None
    auto_save = bool(payload.run_in_background or report_name)
    if payload.run_in_background and not report_name:
        raise HTTPException(status_code=400, detail="Report name is required for background runs.")

    request_payload = {
        "tickers": payload.tickers,
        "asset_class": payload.asset_class,
        "source": payload.source,
        "from_date": payload.from_date,
        "to_date": payload.to_date,
        "amc_ids": payload.amc_ids,
        "mf_scheme_ids": payload.mf_scheme_ids,
        "mf_scheme_names": payload.mf_scheme_names,
        "etf_scheme_ids": payload.etf_scheme_ids,
        "etf_scheme_names": payload.etf_scheme_names,
        "etf_symbols": payload.etf_symbols,
        "etf_symbol_names": payload.etf_symbol_names,
    }
    job = await create_job(
        name=report_name,
        user_id=current_user.id,
        source=SMART_MONEY_ACTIVITY_SOURCE,
        meta={"tickers": payload.tickers, "asset_class": payload.asset_class, "auto_save": auto_save},
        request_payload={**request_payload, "report_name": report_name if auto_save else None},
    )
    run_smart_money_activity_job(
        job.id, payload.tickers,
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
        report_name=report_name if auto_save else None,
        user_id=current_user.id if auto_save else None,
    )
    return {"job_id": job.id, "status": job.status, "name": job.name, "auto_save": auto_save}


@router.get("/command-center/smart-money-activity/jobs")
async def command_center_smart_money_activity_list_jobs(
    status: str | None = "running",
    current_user: User = Depends(get_current_user),
):
    from app.services.smart_money_activity_jobs import SMART_MONEY_ACTIVITY_SOURCE, job_to_dict, list_jobs

    jobs = list_jobs(user_id=current_user.id, source=SMART_MONEY_ACTIVITY_SOURCE, status=status or None)
    return {"jobs": [job_to_dict(j) for j in jobs]}


@router.get("/command-center/smart-money-activity/jobs/{job_id}")
async def command_center_smart_money_activity_job_status(
    job_id: str,
    current_user: User = Depends(get_current_user),
):
    from app.services.smart_money_activity_jobs import get_job, job_to_dict

    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found (it may have expired).")
    if job.user_id is not None and job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found (it may have expired).")
    return job_to_dict(job)


@router.post("/command-center/smart-money-activity/reports")
async def command_center_smart_money_activity_save_report(
    payload: SaveSmartMoneyActivityReportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = CommandCenterService(SettingsService(db), db)
    tickers = payload.tickers or [
        str(r.get("ticker")) for r in (payload.payload.get("results") or [])
        if isinstance(r, dict) and r.get("ticker")
    ]
    return await service.save_smart_money_activity_report(
        payload.name, tickers, payload.from_date, payload.to_date, payload.payload, user_id=current_user.id,
    )


@router.get("/command-center/smart-money-activity/reports")
async def command_center_smart_money_activity_list_reports(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = CommandCenterService(SettingsService(db), db)
    return await service.list_smart_money_activity_reports(user_id=current_user.id)


@router.get("/command-center/smart-money-activity/reports/{report_id}")
async def command_center_smart_money_activity_get_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = CommandCenterService(SettingsService(db), db)
    return await service.get_smart_money_activity_report(report_id, user_id=current_user.id)


@router.delete("/command-center/smart-money-activity/reports/{report_id}")
async def command_center_smart_money_activity_delete_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = CommandCenterService(SettingsService(db), db)
    return await service.delete_smart_money_activity_report(report_id, user_id=current_user.id)


@router.post("/command-center/fundamental-analysis")
async def command_center_fundamental_analysis(
    payload: CommandCenterTickerScanRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).fundamental_analysis(payload.tickers)


@router.post("/command-center/india-fii-dii-holdings")
async def command_center_india_fii_dii_holdings(
    payload: CommandCenterIndiaFiiDiiHoldingsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).india_fii_dii_holdings(
        payload.tickers,
        from_date=payload.from_date,
        to_date=payload.to_date,
    )


@router.post("/command-center/india-fii-dii-holdings/start")
async def command_center_india_fii_dii_holdings_start(
    payload: CommandCenterIndiaFiiDiiHoldingsRequest,
    current_user: User = Depends(get_current_user),
):
    """Kick off the FII-DII holdings analysis as a background job. Poll GET
    /command-center/india-fii-dii-holdings/jobs/{id} for progress and result."""
    from app.services.fii_dii_holdings_jobs import FII_DII_HOLDINGS_SOURCE, create_job, run_fii_dii_holdings_job

    report_name = (payload.report_name or "").strip() or None
    auto_save = bool(payload.run_in_background or report_name)
    if payload.run_in_background and not report_name:
        raise HTTPException(status_code=400, detail="Report name is required for background runs.")

    job = await create_job(
        name=report_name,
        user_id=current_user.id,
        source=FII_DII_HOLDINGS_SOURCE,
        meta={
            "tickers": payload.tickers,
            "from_date": payload.from_date,
            "to_date": payload.to_date,
            "auto_save": auto_save,
        },
        request_payload={
            "tickers": payload.tickers,
            "from_date": payload.from_date,
            "to_date": payload.to_date,
            "report_name": report_name if auto_save else None,
        },
    )
    run_fii_dii_holdings_job(
        job.id, payload.tickers, payload.from_date, payload.to_date,
        report_name=report_name if auto_save else None,
        user_id=current_user.id if auto_save else None,
    )
    return {"job_id": job.id, "status": job.status, "name": job.name, "auto_save": auto_save}


@router.get("/command-center/india-fii-dii-holdings/jobs")
async def command_center_india_fii_dii_holdings_list_jobs(
    status: str | None = "running",
    current_user: User = Depends(get_current_user),
):
    from app.services.fii_dii_holdings_jobs import FII_DII_HOLDINGS_SOURCE, job_to_dict, list_jobs

    jobs = list_jobs(user_id=current_user.id, source=FII_DII_HOLDINGS_SOURCE, status=status or None)
    return {"jobs": [job_to_dict(j) for j in jobs]}


@router.get("/command-center/india-fii-dii-holdings/jobs/{job_id}")
async def command_center_india_fii_dii_holdings_job_status(
    job_id: str,
    current_user: User = Depends(get_current_user),
):
    from app.services.fii_dii_holdings_jobs import get_job, job_to_dict

    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found (it may have expired).")
    if job.user_id is not None and job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found (it may have expired).")
    return job_to_dict(job)


@router.post("/command-center/india-fii-dii-holdings/reports")
async def command_center_india_fii_dii_holdings_save_report(
    payload: SaveFiiDiiHoldingsReportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = CommandCenterService(SettingsService(db), db)
    result = payload.payload
    ok = result.get("ok") or []
    tickers = [str(r.get("ticker")) for r in ok if isinstance(r, dict) and r.get("ticker")]
    return await service.save_fii_dii_holdings_report(
        payload.name, tickers, "", "", result, user_id=current_user.id,
    )


@router.get("/command-center/india-fii-dii-holdings/reports")
async def command_center_india_fii_dii_holdings_list_reports(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = CommandCenterService(SettingsService(db), db)
    return await service.list_fii_dii_holdings_reports(user_id=current_user.id)


@router.get("/command-center/india-fii-dii-holdings/reports/{report_id}")
async def command_center_india_fii_dii_holdings_get_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = CommandCenterService(SettingsService(db), db)
    return await service.get_fii_dii_holdings_report(report_id, user_id=current_user.id)


@router.delete("/command-center/india-fii-dii-holdings/reports/{report_id}")
async def command_center_india_fii_dii_holdings_delete_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = CommandCenterService(SettingsService(db), db)
    return await service.delete_fii_dii_holdings_report(report_id, user_id=current_user.id)


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


@router.get("/command-center/advance-decline-graph/indices")
async def command_center_advance_decline_graph_indices(
    asset_class: str = "india",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).advance_decline_graph_indices(asset_class)


@router.post("/command-center/advance-decline-graph")
async def command_center_advance_decline_graph(
    payload: CommandCenterAdvanceDeclineGraphRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).advance_decline_graph(
        payload.index_name,
        asset_class=payload.asset_class,
        from_date=payload.from_date,
        to_date=payload.to_date,
        timeframe=payload.timeframe,
        session_date=payload.session_date,
        as_of_time=payload.as_of_time,
        exchange=payload.exchange,
    )


@router.get("/command-center/comparative-strength/presets")
async def command_center_comparative_strength_presets(
    asset_class: str = "india",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).comparative_strength_presets(asset_class)


@router.post("/command-center/comparative-strength")
async def command_center_comparative_strength(
    payload: CommandCenterComparativeStrengthRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).comparative_strength(
        asset_class=payload.asset_class,
        base_symbol=payload.base_symbol,
        compare_symbols=payload.compare_symbols,
        timeframe=payload.timeframe,
        lookback_bars=payload.lookback_bars,
        exchange=payload.exchange,
    )


@router.post("/command-center/oil-dollar-bond")
async def command_center_oil_dollar_bond(
    payload: CommandCenterOilDollarBondRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await CommandCenterService(SettingsService(db)).oil_dollar_bond(
        from_date=payload.from_date,
        to_date=payload.to_date,
        mode=payload.mode,
        session_date=payload.session_date,
        interval=payload.interval,
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
    return await CommandCenterService(SettingsService(db), db).quick_analyzer(
        payload.tickers,
        payload.timeframes,
        asset_class=payload.asset_class,
        from_date=payload.from_date,
        to_date=payload.to_date,
        include_fundamentals=payload.include_fundamentals,
        include_option_chain=payload.include_option_chain,
        user_id=current_user.id,
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


@router.get("/strategy-lab/custom-strategies")
async def custom_strategies_list(
    market: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.custom_strategy_service import CustomStrategyService

    return {"strategies": await CustomStrategyService(db, SettingsService(db)).list_strategies(current_user.id, market=market)}


@router.post("/strategy-lab/custom-strategies")
async def custom_strategies_create(
    payload: CustomStrategyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.custom_strategy_service import CustomStrategyService

    return await CustomStrategyService(db, SettingsService(db)).create_strategy(current_user.id, payload.model_dump())


@router.patch("/strategy-lab/custom-strategies/{strategy_id}")
async def custom_strategies_update(
    strategy_id: int,
    payload: CustomStrategyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.custom_strategy_service import CustomStrategyService

    row = await CustomStrategyService(db, SettingsService(db)).update_strategy(
        current_user.id, strategy_id, payload.model_dump(exclude_unset=True),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Custom strategy not found")
    return row


@router.delete("/strategy-lab/custom-strategies/{strategy_id}")
async def custom_strategies_delete(
    strategy_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.custom_strategy_service import CustomStrategyService

    ok = await CustomStrategyService(db, SettingsService(db)).delete_strategy(current_user.id, strategy_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Custom strategy not found")
    return {"deleted": True}


@router.post("/strategy-lab/ai-generate")
async def strategy_lab_ai_generate(
    payload: AIStrategyGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.custom_strategy_service import CustomStrategyService

    try:
        return await CustomStrategyService(db, SettingsService(db)).ai_generate(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/strategy-lab/leaderboard/catalog")
async def strategy_leaderboard_catalog(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = StrategyLeaderboardService(SettingsService(db))
    return await service.strategies_catalog()


@router.post("/strategy-lab/leaderboard/run")
async def strategy_leaderboard_run(
    payload: StrategyLeaderboardRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Synchronous run — fine for a quick 1-2 strategy / 1 ticker check, but
    a full leaderboard across many strategies can take minutes; prefer
    /leaderboard/start + polling /leaderboard/jobs/{id} for that."""
    service = StrategyLeaderboardService(SettingsService(db), db)
    return await service.run(
        payload.tickers, payload.timeframes,
        asset_class=payload.asset_class, strategy_ids=payload.strategy_ids,
        bars=payload.bars, forward_bars=payload.forward_bars,
    )


@router.post("/strategy-lab/leaderboard/start")
async def strategy_leaderboard_start(
    payload: StrategyLeaderboardRequest,
    current_user: User = Depends(get_current_user),
):
    """Kick off a leaderboard run as a background job and return immediately
    with a job id — the right shape for a computation that can take minutes.
    Poll GET /strategy-lab/leaderboard/jobs/{id} for progress and the
    eventual result."""
    from app.services.strategy_leaderboard_jobs import create_job, run_leaderboard_job

    job = await create_job(
        user_id=current_user.id,
        request_payload={
            "tickers": payload.tickers,
            "timeframes": payload.timeframes,
            "asset_class": payload.asset_class,
            "strategy_ids": payload.strategy_ids,
            "bars": payload.bars,
            "forward_bars": payload.forward_bars,
        },
    )
    run_leaderboard_job(
        job.id, payload.tickers, payload.timeframes,
        asset_class=payload.asset_class, strategy_ids=payload.strategy_ids,
        bars=payload.bars, forward_bars=payload.forward_bars,
    )
    return {"job_id": job.id, "status": job.status}


@router.get("/strategy-lab/leaderboard/jobs/{job_id}")
async def strategy_leaderboard_job_status(
    job_id: str,
    current_user: User = Depends(get_current_user),
):
    from app.services.strategy_leaderboard_jobs import get_job

    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found (it may have expired).")
    return {
        "job_id": job.id, "status": job.status, "progress": job.progress,
        "progress_note": job.progress_note, "result": job.result, "error": job.error,
    }


@router.post("/strategy-lab/leaderboard/reports")
async def strategy_leaderboard_save_report(
    payload: SaveBacktestReportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = StrategyLeaderboardService(SettingsService(db), db)
    return await service.save_report(payload.name, payload.payload, user_id=current_user.id)


@router.get("/strategy-lab/leaderboard/reports")
async def strategy_leaderboard_list_reports(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = StrategyLeaderboardService(SettingsService(db), db)
    return await service.list_reports(user_id=current_user.id)


@router.get("/strategy-lab/leaderboard/reports/{report_id}")
async def strategy_leaderboard_get_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = StrategyLeaderboardService(SettingsService(db), db)
    return await service.get_report(report_id, user_id=current_user.id)


@router.delete("/strategy-lab/leaderboard/reports/{report_id}")
async def strategy_leaderboard_delete_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = StrategyLeaderboardService(SettingsService(db), db)
    return await service.delete_report(report_id, user_id=current_user.id)


@router.get("/backtester/leaderboard/catalog")
async def backtester_leaderboard_catalog(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Full backtestable catalog — built-in indicator strategies, Trading
    Hub engines, TA screeners, and Strategy Lab presets — grouped by
    category, the same catalog the single-ticker Backtester page uses."""
    service = BacktesterLeaderboardService(SettingsService(db))
    return await service.catalog()


@router.post("/backtester/leaderboard/start")
async def backtester_leaderboard_start(
    payload: BacktesterLeaderboardRequest,
    current_user: User = Depends(get_current_user),
):
    """Kick off a multi-ticker x multi-strategy backtest as a background job
    and return immediately with a job id. Poll GET
    /backtester/leaderboard/jobs/{id} for progress and the eventual result.

    When ``run_in_background`` is true (or ``report_name`` is set), the finished
    result is auto-saved under that name for later viewing.
    """
    from app.services.backtester_leaderboard_jobs import (
        BACKTESTER_SOURCE,
        create_job,
        run_backtester_job,
    )

    report_name = (payload.report_name or "").strip() or None
    auto_save = bool(payload.run_in_background or report_name)
    if payload.run_in_background and not report_name:
        raise HTTPException(status_code=400, detail="Report name is required for background backtests.")

    job = await create_job(
        name=report_name,
        user_id=current_user.id,
        source=BACKTESTER_SOURCE,
        meta={
            "tickers": payload.tickers,
            "strategy_count": len(payload.strategy_ids),
            "asset_class": payload.asset_class,
            "timeframe": payload.timeframe,
            "period": payload.period,
            "auto_save": auto_save,
        },
        request_payload={
            "tickers": payload.tickers,
            "strategy_ids": payload.strategy_ids,
            "asset_class": payload.asset_class,
            "timeframe": payload.timeframe,
            "period": payload.period,
            "costs_pct": payload.costs_pct,
            "bars": payload.bars,
            "forward_bars": payload.forward_bars,
            "direction": payload.direction,
            "report_name": report_name if auto_save else None,
        },
    )
    run_backtester_job(
        job.id, payload.tickers, payload.strategy_ids,
        asset_class=payload.asset_class, timeframe=payload.timeframe,
        period=payload.period, costs_pct=payload.costs_pct,
        bars=payload.bars, forward_bars=payload.forward_bars, direction=payload.direction,
        report_name=report_name if auto_save else None,
        user_id=current_user.id if auto_save else None,
    )
    return {
        "job_id": job.id,
        "status": job.status,
        "name": job.name,
        "auto_save": auto_save,
    }


@router.get("/backtester/leaderboard/jobs")
async def backtester_leaderboard_list_jobs(
    status: str | None = "running",
    current_user: User = Depends(get_current_user),
):
    """List this user's Backtester jobs (default: still running). Used to show
    ongoing background backtests when returning to the page."""
    from app.services.backtester_leaderboard_jobs import BACKTESTER_SOURCE, job_to_dict, list_jobs

    jobs = list_jobs(user_id=current_user.id, source=BACKTESTER_SOURCE, status=status or None)
    return {"jobs": [job_to_dict(j) for j in jobs]}


@router.get("/backtester/leaderboard/jobs/{job_id}")
async def backtester_leaderboard_job_status(
    job_id: str,
    current_user: User = Depends(get_current_user),
):
    from app.services.backtester_leaderboard_jobs import get_job, job_to_dict

    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found (it may have expired).")
    if job.user_id is not None and job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found (it may have expired).")
    return job_to_dict(job)


@router.post("/backtester/leaderboard/reports")
async def backtester_leaderboard_save_report(
    payload: SaveBacktestReportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = BacktesterLeaderboardService(SettingsService(db), db)
    return await service.save_report(payload.name, payload.payload, user_id=current_user.id)


@router.get("/backtester/leaderboard/reports")
async def backtester_leaderboard_list_reports(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = BacktesterLeaderboardService(SettingsService(db), db)
    return await service.list_reports(user_id=current_user.id)


@router.get("/backtester/leaderboard/reports/{report_id}")
async def backtester_leaderboard_get_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = BacktesterLeaderboardService(SettingsService(db), db)
    return await service.get_report(report_id, user_id=current_user.id)


@router.delete("/backtester/leaderboard/reports/{report_id}")
async def backtester_leaderboard_delete_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = BacktesterLeaderboardService(SettingsService(db), db)
    return await service.delete_report(report_id, user_id=current_user.id)


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


# ── Trade Candidate hub ──────────────────────────────────────────────────

@router.get("/trade-candidates")
async def trade_candidates_list(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.trade_candidate_service import TradeCandidateService

    return {"candidates": await TradeCandidateService(db, SettingsService(db)).list_candidates(current_user.id)}


@router.post("/trade-candidates")
async def trade_candidates_create(
    payload: TradeCandidateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.trade_candidate_service import TradeCandidateService

    try:
        return await TradeCandidateService(db, SettingsService(db)).create_candidate(
            current_user.id, payload.model_dump(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/trade-candidates/{candidate_id}")
async def trade_candidates_update(
    candidate_id: int,
    payload: TradeCandidateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.trade_candidate_service import TradeCandidateService

    row = await TradeCandidateService(db, SettingsService(db)).update_candidate(
        current_user.id, candidate_id, payload.model_dump(exclude_unset=True),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Trade candidate not found")
    return row


@router.delete("/trade-candidates/{candidate_id}")
async def trade_candidates_delete(
    candidate_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.trade_candidate_service import TradeCandidateService

    ok = await TradeCandidateService(db, SettingsService(db)).delete_candidate(current_user.id, candidate_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Trade candidate not found")
    return {"deleted": True}


@router.post("/trade-candidates/{candidate_id}/check")
async def trade_candidates_check(
    candidate_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.trade_candidate_service import TradeCandidateService

    result = await TradeCandidateService(db, SettingsService(db)).check_candidate(current_user.id, candidate_id)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/trade-candidates/hits")
async def trade_candidates_hits(
    candidate_id: int | None = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.trade_candidate_service import TradeCandidateService

    return {
        "hits": await TradeCandidateService(db, SettingsService(db)).list_hits(
            current_user.id, limit=limit, candidate_id=candidate_id,
        )
    }


@router.delete("/trade-candidates/hits/{hit_id}")
async def trade_candidates_hit_delete(
    hit_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.trade_candidate_service import TradeCandidateService

    ok = await TradeCandidateService(db, SettingsService(db)).delete_hit(current_user.id, hit_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Hit not found")
    return {"deleted": True, "id": hit_id}


@router.post("/trade-candidates/hits/delete")
async def trade_candidates_hits_delete_bulk(
    payload: TradeCandidateHitsDelete,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.trade_candidate_service import TradeCandidateService

    svc = TradeCandidateService(db, SettingsService(db))
    if payload.delete_all:
        n = await svc.delete_all_hits(current_user.id, candidate_id=payload.candidate_id)
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


@router.patch("/watchlists/{watchlist_id}/items/{item_id}")
async def watchlists_update_item(
    watchlist_id: int,
    item_id: int,
    payload: WatchlistItemUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await WatchlistService(db, SettingsService(db)).update_item(
            current_user.id, watchlist_id, item_id,
            display_name=payload.display_name, notes=payload.notes,
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
    service = TradingHubService(SettingsService(db), db)
    return await service.scan(
        payload.section_id,
        payload.tickers,
        asset_class=payload.asset_class,
        config=payload.config,
        run_bt=payload.run_backtest,
        user_id=current_user.id,
    )


@router.post("/trading-hubs/intra-hedging/start")
async def trading_hubs_intra_hedging_start(
    payload: TradingHubBackgroundScanRequest,
    current_user: User = Depends(get_current_user),
):
    """Kick off an Intra-Hedging scan as a background job and return
    immediately with a job id. Poll GET
    /trading-hubs/intra-hedging/jobs/{id} for progress and result.

    When ``run_in_background`` is true (or ``report_name`` is set), the
    finished result is auto-saved under that name for later viewing.
    """
    from app.services.intra_hedging_jobs import INTRA_HEDGING_SOURCE, create_job, run_intra_hedging_job

    report_name = (payload.report_name or "").strip() or None
    auto_save = bool(payload.run_in_background or report_name)
    if payload.run_in_background and not report_name:
        raise HTTPException(status_code=400, detail="Report name is required for background runs.")

    job = await create_job(
        name=report_name,
        user_id=current_user.id,
        source=INTRA_HEDGING_SOURCE,
        meta={
            "asset_class": payload.asset_class,
            "universe_mode": (payload.config or {}).get("universe_mode"),
            "auto_save": auto_save,
        },
        request_payload={
            "tickers": payload.tickers,
            "asset_class": payload.asset_class,
            "config": payload.config,
            "report_name": report_name if auto_save else None,
        },
    )
    run_intra_hedging_job(
        job.id, payload.tickers, payload.asset_class, payload.config,
        report_name=report_name if auto_save else None,
        user_id=current_user.id if auto_save else None,
    )
    return {
        "job_id": job.id,
        "status": job.status,
        "name": job.name,
        "auto_save": auto_save,
    }


@router.get("/trading-hubs/intra-hedging/jobs")
async def trading_hubs_intra_hedging_list_jobs(
    status: str | None = "running",
    current_user: User = Depends(get_current_user),
):
    from app.services.intra_hedging_jobs import INTRA_HEDGING_SOURCE, job_to_dict, list_jobs

    jobs = list_jobs(user_id=current_user.id, source=INTRA_HEDGING_SOURCE, status=status or None)
    return {"jobs": [job_to_dict(j) for j in jobs]}


@router.get("/trading-hubs/intra-hedging/jobs/{job_id}")
async def trading_hubs_intra_hedging_job_status(
    job_id: str,
    current_user: User = Depends(get_current_user),
):
    from app.services.intra_hedging_jobs import get_job, job_to_dict

    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found (it may have expired).")
    if job.user_id is not None and job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found (it may have expired).")
    return job_to_dict(job)


@router.post("/trading-hubs/intra-hedging/reports")
async def trading_hubs_intra_hedging_save_report(
    payload: SaveTradingHubReportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TradingHubService(SettingsService(db), db)
    result = payload.payload
    tickers = [r.get("ticker") for r in (result.get("results") or []) if isinstance(r, dict) and r.get("ticker")]
    return await service.save_intra_hedging_report(
        payload.name, tickers, str(result.get("market") or "india"),
        result, user_id=current_user.id,
    )


@router.get("/trading-hubs/intra-hedging/reports")
async def trading_hubs_intra_hedging_list_reports(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TradingHubService(SettingsService(db), db)
    return await service.list_intra_hedging_reports(user_id=current_user.id)


@router.get("/trading-hubs/intra-hedging/reports/{report_id}")
async def trading_hubs_intra_hedging_get_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TradingHubService(SettingsService(db), db)
    return await service.get_intra_hedging_report(report_id, user_id=current_user.id)


@router.delete("/trading-hubs/intra-hedging/reports/{report_id}")
async def trading_hubs_intra_hedging_delete_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TradingHubService(SettingsService(db), db)
    return await service.delete_intra_hedging_report(report_id, user_id=current_user.id)


@router.post("/trading-hubs/support-resistance/chart")
async def support_resistance_chart(
    payload: SupportResistanceChartRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    import asyncio

    from app.market_pulse.asset_class_config import ASSET_CLASS_CONFIG
    from app.trading_hubs.support_resistance_engine import SupportResistanceConfig, build_chart_payload

    settings = SettingsService(db)
    cfg_data = ASSET_CLASS_CONFIG.get(payload.asset_class) or ASSET_CLASS_CONFIG["india"]
    market = str(cfg_data["market"])
    if payload.asset_class == "india":
        groww_token = await settings.get_groww_token() or ""
        exchange = await settings.get_groww_exchange()
    else:
        groww_token = ""
        exchange = str(cfg_data.get("exchange") or "NSE")

    cfg = SupportResistanceConfig(htf=payload.timeframe)
    result = await asyncio.to_thread(
        build_chart_payload,
        payload.ticker, market, cfg,
        groww_token=groww_token, exchange=exchange,
        start_date=payload.start_date, end_date=payload.end_date,
        ltf=payload.ltf,
        include_volume=payload.include_volume,
        ema_periods=payload.ema_periods,
        include_rsi=payload.include_rsi,
        include_fibonacci=payload.include_fibonacci,
        include_supply_demand=payload.include_supply_demand,
        include_order_blocks=payload.include_order_blocks,
    )
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/trading-hubs/bramhastra/chart")
async def bramhastra_chart(
    payload: BramhastraChartRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    import asyncio

    from app.market_pulse.asset_class_config import ASSET_CLASS_CONFIG
    from app.trading_hubs.intraday_bramhastra_engine import BramhastraConfig, build_chart_payload
    from app.trading_hubs.registry import build_config

    settings = SettingsService(db)
    cfg_data = ASSET_CLASS_CONFIG.get(payload.asset_class) or ASSET_CLASS_CONFIG["india"]
    market = str(cfg_data["market"])
    if payload.asset_class == "india":
        groww_token = await settings.get_groww_token() or ""
        exchange = await settings.get_groww_exchange()
    else:
        groww_token = ""
        exchange = str(cfg_data.get("exchange") or "NSE")

    cfg = build_config(BramhastraConfig, {**(payload.config or {}), "asset_class": payload.asset_class})
    result = await asyncio.to_thread(
        build_chart_payload,
        payload.ticker, market, cfg,
        groww_token=groww_token, exchange=exchange,
    )
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/trading-hubs/swing-5/scan")
async def trading_hubs_swing5_scan(
    payload: Swing5ScanRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Swing Trading — 5 Strategies: multi-strategy/multi-timeframe scan,
    kept as its own endpoint since its {strategy: {hits, misses, errors}}
    shape doesn't fit the generic /trading-hubs/scan results-list contract."""
    service = TradingHubService(SettingsService(db), db)
    return await service.scan_swing5(
        payload.tickers,
        payload.timeframes,
        payload.strategies,
        asset_class=payload.asset_class,
        config=payload.config,
    )


@router.get("/etf-ta/universe")
async def etf_ta_universe(
    asset_class: str = "india",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = EtfTaService(SettingsService(db), db)
    return service.universe(asset_class)


@router.get("/etf-28-sma/universe")
async def etf_28_sma_universe(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """FIRE 28 SMA + ETF Shop presets and curated ticker lists."""
    return EtfTaService(SettingsService(db), db).etf_28_sma_universe()


@router.get("/etf-28-sma/guide")
async def etf_28_sma_guide(
    current_user: User = Depends(get_current_user),
):
    from app.etf_ta.etf_28_sma_engine import HOW_IT_WORKS, RULES, STRATEGY_NAME

    return {
        "strategy": "etf_28_sma",
        "strategy_label": STRATEGY_NAME,
        "how_it_works": HOW_IT_WORKS,
        "rules": RULES,
    }


@router.post("/etf-28-sma/scan")
async def etf_28_sma_scan(
    payload: Etf28SmaScanRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = EtfTaService(SettingsService(db), db)
    return await service.etf_28_sma_scan(payload.model_dump())


@router.get("/etf-top-down/universe")
async def etf_top_down_universe(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return EtfTaService(SettingsService(db), db).etf_top_down_universe()


@router.get("/etf-top-down/guide")
async def etf_top_down_guide(
    current_user: User = Depends(get_current_user),
):
    from app.etf_ta.etf_top_down_engine import HOW_IT_WORKS, RULES, STRATEGY_NAME, YOUTUBE_URL

    return {
        "strategy": "etf_top_down",
        "strategy_label": STRATEGY_NAME,
        "youtube": YOUTUBE_URL,
        "how_it_works": HOW_IT_WORKS,
        "rules": RULES,
    }


@router.post("/etf-top-down/scan")
async def etf_top_down_scan(
    payload: EtfTopDownScanRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = EtfTaService(SettingsService(db), db)
    return await service.etf_top_down_scan(payload.model_dump())


@router.post("/etf-ta/stf-shop/scan")
async def etf_ta_stf_scan(
    payload: EtfTaScanRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = EtfTaService(SettingsService(db), db)
    return await service.scan(payload.symbols, payload.exchange, asset_class=payload.asset_class)


@router.post("/etf-ta/stf-shop/recommend")
async def etf_ta_stf_recommend(
    payload: EtfTaRecommendRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = EtfTaService(SettingsService(db), db)
    return await service.recommend(payload.model_dump())


@router.get("/etf-ta/stf-shop/portfolio")
async def etf_ta_stf_portfolio(
    asset_class: str = "india",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Persisted shop state — capital/rules config + FIFO lot ledger for this user's shop in this asset class."""
    service = EtfTaService(SettingsService(db), db)
    return await service.portfolio(current_user.id, asset_class)


@router.put("/etf-ta/stf-shop/config")
async def etf_ta_stf_update_config(
    payload: EtfShopConfigUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = EtfTaService(SettingsService(db), db)
    fields = payload.model_dump(exclude_unset=True, exclude={"asset_class"})
    return await service.update_config(current_user.id, fields, asset_class=payload.asset_class)


@router.post("/etf-ta/stf-shop/lots")
async def etf_ta_stf_add_lot(
    payload: EtfShopAddLotRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Record a real buy (from a recommendation or manual entry) as a new FIFO lot."""
    service = EtfTaService(SettingsService(db), db)
    try:
        return await service.add_lot(
            current_user.id,
            symbol=payload.symbol,
            price=payload.price,
            amount=payload.amount,
            lot_type=payload.lot_type,
            purchase_date=payload.purchase_date,
            asset_class=payload.asset_class,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/etf-ta/stf-shop/lots/{lot_id}/close")
async def etf_ta_stf_close_lot(
    lot_id: int,
    payload: EtfShopCloseLotRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Book a FIFO sell — records real profit and reinvests it into the capital pool."""
    service = EtfTaService(SettingsService(db), db)
    try:
        return await service.close_lot(
            current_user.id,
            lot_id,
            sale_price=payload.sale_price,
            sale_date=payload.sale_date,
            dividend_pct=payload.dividend_pct,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/etf-ta/stf-shop/daily")
async def etf_ta_stf_daily(
    asset_class: str = "india",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Today's buy/sell recommendation from the persisted config + open lots —
    no portfolio payload needed, and SIP-locked symbols are latched server-side."""
    service = EtfTaService(SettingsService(db), db)
    return await service.daily(current_user.id, asset_class)


@router.get("/suggestions/setups")
async def suggestions_list_setups(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """All of this user's Auto Trade setups — each an independently
    scheduled (asset_class, style) scan."""
    from app.services.suggestion_engine_service import SuggestionEngineService

    service = SuggestionEngineService(SettingsService(db), db)
    setups = await service.list_setups(current_user.id)
    return {"setups": setups}


@router.post("/suggestions/setups")
async def suggestions_create_setup(
    payload: AutoTradeSetupCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.suggestion_engine_service import SuggestionEngineService

    service = SuggestionEngineService(SettingsService(db), db)
    try:
        return await service.create_setup(
            current_user.id,
            name=payload.name,
            asset_class=payload.asset_class,
            style=payload.style,
            direction=payload.direction,
            interval_minutes=payload.interval_minutes,
            universe_cap=payload.universe_cap,
            top_n=payload.top_n,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/suggestions/setups/{setup_id}")
async def suggestions_update_setup(
    setup_id: int,
    payload: AutoTradeSetupUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.suggestion_engine_service import SuggestionEngineService

    service = SuggestionEngineService(SettingsService(db), db)
    fields = payload.model_dump(exclude_unset=True)
    try:
        return await service.update_setup(current_user.id, setup_id, **fields)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/suggestions/setups/{setup_id}")
async def suggestions_delete_setup(
    setup_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.suggestion_engine_service import SuggestionEngineService

    service = SuggestionEngineService(SettingsService(db), db)
    try:
        return await service.delete_setup(current_user.id, setup_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/suggestions/setups/{setup_id}/start")
async def suggestions_start_setup(
    setup_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.suggestion_engine_service import SuggestionEngineService

    service = SuggestionEngineService(SettingsService(db), db)
    try:
        return await service.start_setup(current_user.id, setup_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/suggestions/setups/{setup_id}/stop")
async def suggestions_stop_setup(
    setup_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.suggestion_engine_service import SuggestionEngineService

    service = SuggestionEngineService(SettingsService(db), db)
    try:
        return await service.stop_setup(current_user.id, setup_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/suggestions/setups/{setup_id}/run-now")
async def suggestions_run_setup_now(
    setup_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Force an immediate sweep for one setup — fire-and-forget background run."""
    from app.services.suggestion_engine_service import SuggestionEngineService, run_suggestion_sweep

    service = SuggestionEngineService(SettingsService(db), db)
    try:
        await service._get_owned(current_user.id, setup_id)  # noqa: SLF001 — ownership check before firing the background task
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    run_suggestion_sweep(setup_id)
    return {"started": True}


@router.get("/suggestions")
async def suggestions_list(
    setup_id: int | None = None,
    asset_class: str | None = None,
    style: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.suggestion_engine_service import SuggestionEngineService

    service = SuggestionEngineService(SettingsService(db), db)
    suggestions = await service.list_suggestions(current_user.id, setup_id=setup_id, asset_class=asset_class, style=style)
    return {"suggestions": suggestions}


@router.get("/todos")
async def todos_list(
    search: str | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.todo_service import TodoService

    service = TodoService(db)
    try:
        todos = await service.list_todos(current_user.id, search=search, status=status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"todos": todos}


@router.post("/todos")
async def todos_create(
    payload: TodoCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.todo_service import TodoService

    service = TodoService(db)
    try:
        return await service.create_todo(current_user.id, title=payload.title, notes=payload.notes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/todos/{todo_id}")
async def todos_update(
    todo_id: int,
    payload: TodoUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.todo_service import TodoService

    service = TodoService(db)
    fields = payload.model_dump(exclude_unset=True)
    try:
        return await service.update_todo(current_user.id, todo_id, **fields)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/todos/{todo_id}")
async def todos_delete(
    todo_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.todo_service import TodoService

    service = TodoService(db)
    deleted = await service.delete_todo(current_user.id, todo_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Todo not found")
    return {"deleted": True}


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


@router.post("/options/hedging")
async def options_hedging(
    payload: OptionsHedgingRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await OptionsService(SettingsService(db)).hedging(
        payload.tickers, asset_class=payload.asset_class, exchange=payload.exchange,
        cfg_overrides={
            "dte": payload.dte,
            "hedge_distance_pct": payload.hedge_distance_pct,
            "zone_timeframe": payload.zone_timeframe,
            "zone_fallback_timeframe": payload.zone_fallback_timeframe,
            "total_capital": payload.total_capital,
            "profit_target_pct_of_capital": payload.profit_target_pct_of_capital,
            "max_loss_pct_of_capital": payload.max_loss_pct_of_capital,
            "max_adjustments_per_day": payload.max_adjustments_per_day,
        },
    )


@router.post("/options/hedging/pnl")
async def options_hedging_pnl(
    payload: OptionsHedgingPnlRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await OptionsService(SettingsService(db)).hedging_pnl(
        payload.total_capital, payload.current_pnl,
        cfg_overrides={
            "profit_target_pct_of_capital": payload.profit_target_pct_of_capital,
            "max_loss_pct_of_capital": payload.max_loss_pct_of_capital,
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


@router.post("/options/market-prediction")
async def options_market_prediction(
    payload: OptionsMarketPredictionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await OptionsService(SettingsService(db)).market_prediction(
        payload.symbol,
        is_index=payload.is_index,
        exchange=payload.exchange,
        futures_price=payload.futures_price,
        fii_index_position_cut=payload.fii_index_position_cut,
        further_analysis=payload.further_analysis,
    )


@router.post("/options/call-put-writing")
async def options_call_put_writing(
    payload: OptionsCallPutWritingRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await OptionsService(SettingsService(db)).call_put_writing(
        payload.symbol,
        is_index=payload.is_index,
        exchange=payload.exchange,
    )


@router.post("/options/zero-to-hero")
async def options_zero_to_hero(
    payload: OptionsZeroToHeroRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await OptionsService(SettingsService(db)).zero_to_hero(
        tickers=payload.tickers,
        exchange=payload.exchange,
        cfg_overrides={
            "execution_tf": payload.execution_tf,
            "sl_buffer_pct": payload.sl_buffer_pct,
            "max_pullback_candles": payload.max_pullback_candles,
            "partial_book_rr": payload.partial_book_rr,
            "partial_book_pct": payload.partial_book_pct,
            "session_end": payload.session_end,
        },
    )


def _options_section_or_404(section_id: str) -> str:
    from app.services.options_jobs import OPTIONS_SECTIONS

    if section_id not in OPTIONS_SECTIONS:
        raise HTTPException(status_code=404, detail=f"Unknown Options section: {section_id}")
    return section_id


@router.post("/options/{section_id}/start")
async def options_section_start(
    section_id: str,
    payload: OptionsBackgroundStartRequest,
    current_user: User = Depends(get_current_user),
):
    """Kick off an Options subsection scan as a background job."""
    from app.services.options_jobs import create_job, options_source, run_options_job

    section_id = _options_section_or_404(section_id)
    body = payload.model_dump(exclude_none=False)
    report_name = (payload.report_name or "").strip() or None
    auto_save = bool(payload.run_in_background or report_name)
    if payload.run_in_background and not report_name:
        raise HTTPException(status_code=400, detail="Report name is required for background runs.")

    # Strip meta fields before dispatching to the engine.
    request_payload = {
        k: v for k, v in body.items()
        if k not in ("run_in_background", "report_name")
    }
    request_payload["report_name"] = report_name if auto_save else None
    request_payload["section_id"] = section_id

    job = await create_job(
        name=report_name,
        user_id=current_user.id,
        source=options_source(section_id),
        meta={"section_id": section_id, "auto_save": auto_save},
        request_payload=request_payload,
    )
    run_options_job(
        job.id, section_id, request_payload,
        report_name=report_name if auto_save else None,
        user_id=current_user.id if auto_save else None,
    )
    return {
        "job_id": job.id,
        "status": job.status,
        "name": job.name,
        "auto_save": auto_save,
        "section_id": section_id,
    }


@router.get("/options/{section_id}/jobs")
async def options_section_list_jobs(
    section_id: str,
    status: str | None = "running",
    current_user: User = Depends(get_current_user),
):
    from app.services.options_jobs import job_to_dict, list_jobs, options_source

    section_id = _options_section_or_404(section_id)
    jobs = list_jobs(
        user_id=current_user.id, source=options_source(section_id), status=status or None,
    )
    return {"jobs": [job_to_dict(j) for j in jobs]}


@router.get("/options/{section_id}/jobs/{job_id}")
async def options_section_job_status(
    section_id: str,
    job_id: str,
    current_user: User = Depends(get_current_user),
):
    from app.services.options_jobs import get_job, job_to_dict, options_source

    section_id = _options_section_or_404(section_id)
    job = get_job(job_id)
    if not job or job.source != options_source(section_id):
        raise HTTPException(status_code=404, detail="Job not found (it may have expired).")
    if job.user_id is not None and job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found (it may have expired).")
    return job_to_dict(job)


@router.post("/options/{section_id}/reports")
async def options_section_save_report(
    section_id: str,
    payload: SaveOptionsReportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    section_id = _options_section_or_404(section_id)
    service = OptionsService(SettingsService(db), db)
    return await service.save_report(
        section_id, payload.name, payload.payload, user_id=current_user.id,
    )


@router.get("/options/{section_id}/reports")
async def options_section_list_reports(
    section_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    section_id = _options_section_or_404(section_id)
    service = OptionsService(SettingsService(db), db)
    return await service.list_reports(section_id, user_id=current_user.id)


@router.get("/options/{section_id}/reports/{report_id}")
async def options_section_get_report(
    section_id: str,
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    section_id = _options_section_or_404(section_id)
    service = OptionsService(SettingsService(db), db)
    return await service.get_report(section_id, report_id, user_id=current_user.id)


@router.delete("/options/{section_id}/reports/{report_id}")
async def options_section_delete_report(
    section_id: str,
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    section_id = _options_section_or_404(section_id)
    service = OptionsService(SettingsService(db), db)
    return await service.delete_report(section_id, report_id, user_id=current_user.id)


@router.post("/analysis/start")
async def analysis_start(
    payload: AnalysisBackgroundStartRequest,
    current_user: User = Depends(get_current_user),
):
    """Kick off a generic analysis background job for any domain/section."""
    from app.services.analysis_jobs import (
        ANALYSIS_DOMAINS,
        analysis_source,
        create_job,
        run_analysis_job,
    )

    domain = (payload.domain or "").strip()
    section = (payload.section or "").strip()
    if domain not in ANALYSIS_DOMAINS:
        raise HTTPException(status_code=400, detail=f"Unknown analysis domain: {domain}")
    if not section:
        raise HTTPException(status_code=400, detail="section is required")

    body = payload.model_dump(exclude_none=False)
    report_name = (payload.report_name or "").strip() or None
    auto_save = bool(payload.run_in_background or report_name)
    if payload.run_in_background and not report_name:
        raise HTTPException(status_code=400, detail="Report name is required for background runs.")

    request_payload = {
        k: v for k, v in body.items()
        if k not in ("run_in_background", "report_name", "domain", "section")
    }
    request_payload["domain"] = domain
    request_payload["section"] = section
    request_payload["report_name"] = report_name if auto_save else None

    job = await create_job(
        name=report_name,
        user_id=current_user.id,
        source=analysis_source(domain, section),
        meta={"domain": domain, "section": section, "auto_save": auto_save},
        request_payload=request_payload,
    )
    run_analysis_job(
        job.id, domain, section, request_payload,
        report_name=report_name if auto_save else None,
        user_id=current_user.id if auto_save else None,
    )
    return {
        "job_id": job.id,
        "status": job.status,
        "name": job.name,
        "auto_save": auto_save,
        "domain": domain,
        "section": section,
    }


@router.get("/analysis/jobs")
async def analysis_list_jobs(
    domain: str,
    section: str,
    status: str | None = "running",
    current_user: User = Depends(get_current_user),
):
    from app.services.analysis_jobs import ANALYSIS_DOMAINS, analysis_source, job_to_dict, list_jobs

    if domain not in ANALYSIS_DOMAINS:
        raise HTTPException(status_code=400, detail=f"Unknown analysis domain: {domain}")
    jobs = list_jobs(
        user_id=current_user.id,
        source=analysis_source(domain, section),
        status=status or None,
    )
    return {"jobs": [job_to_dict(j) for j in jobs]}


@router.get("/analysis/jobs/{job_id}")
async def analysis_job_status(
    job_id: str,
    current_user: User = Depends(get_current_user),
):
    from app.services.analysis_jobs import get_job, is_analysis_source, job_to_dict

    job = get_job(job_id)
    if not job or not is_analysis_source(job.source):
        raise HTTPException(status_code=404, detail="Job not found (it may have expired).")
    if job.user_id is not None and job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found (it may have expired).")
    return job_to_dict(job)


@router.post("/analysis/reports")
async def analysis_save_report(
    domain: str,
    section: str,
    payload: SaveAnalysisReportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.analysis_jobs import ANALYSIS_DOMAINS
    from app.services.analysis_report_service import AnalysisReportService

    if domain not in ANALYSIS_DOMAINS:
        raise HTTPException(status_code=400, detail=f"Unknown analysis domain: {domain}")
    return await AnalysisReportService(db).save(
        domain, section, payload.name, payload.payload, user_id=current_user.id,
        asset_class=str(payload.payload.get("asset_class") or "india"),
    )


@router.get("/analysis/reports")
async def analysis_list_reports(
    domain: str,
    section: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.analysis_jobs import ANALYSIS_DOMAINS
    from app.services.analysis_report_service import AnalysisReportService

    if domain not in ANALYSIS_DOMAINS:
        raise HTTPException(status_code=400, detail=f"Unknown analysis domain: {domain}")
    return await AnalysisReportService(db).list_reports(domain, section, user_id=current_user.id)


@router.get("/analysis/reports/{report_id}")
async def analysis_get_report(
    report_id: int,
    domain: str,
    section: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.analysis_jobs import ANALYSIS_DOMAINS
    from app.services.analysis_report_service import AnalysisReportService

    if domain not in ANALYSIS_DOMAINS:
        raise HTTPException(status_code=400, detail=f"Unknown analysis domain: {domain}")
    return await AnalysisReportService(db).get_report(domain, section, report_id, user_id=current_user.id)


@router.delete("/analysis/reports/{report_id}")
async def analysis_delete_report(
    report_id: int,
    domain: str,
    section: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.analysis_jobs import ANALYSIS_DOMAINS
    from app.services.analysis_report_service import AnalysisReportService

    if domain not in ANALYSIS_DOMAINS:
        raise HTTPException(status_code=400, detail=f"Unknown analysis domain: {domain}")
    return await AnalysisReportService(db).delete_report(domain, section, report_id, user_id=current_user.id)


@router.get("/pro-trade/sections")
async def pro_trade_sections(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await ProTradeService(SettingsService(db)).sections()


@router.post("/pro-trade/volume-profile-ce")
async def pro_trade_volume_profile_ce(
    payload: ProTradeVolumeProfileCeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await ProTradeService(SettingsService(db)).volume_profile_ce(
        tickers=payload.tickers,
        asset_class=payload.asset_class,
        exchange=payload.exchange,
        cfg_overrides={
            "intraday_tf": payload.intraday_tf,
            "daily_tf": payload.daily_tf,
            "num_bins": payload.num_bins,
            "value_area_pct": payload.value_area_pct,
            "compression_days": payload.compression_days,
            "compression_threshold_pct": payload.compression_threshold_pct,
            "val_touch_tol_pct": payload.val_touch_tol_pct,
            "lvn_threshold_pct": payload.lvn_threshold_pct,
        },
    )


@router.post("/pro-trade/volume-profile-poc")
async def pro_trade_volume_profile_poc(
    payload: ProTradeVolumeProfilePocRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await ProTradeService(SettingsService(db)).volume_profile_poc(
        tickers=payload.tickers,
        asset_class=payload.asset_class,
        exchange=payload.exchange,
        cfg_overrides={
            "timeframe": payload.timeframe,
            "lookback_bars": payload.lookback_bars,
            "profile_bars": payload.profile_bars,
            "num_bins": payload.num_bins,
            "cluster_vol_pct": payload.cluster_vol_pct,
            "breakout_buffer_pct": payload.breakout_buffer_pct,
        },
    )


@router.post("/pro-trade/pa-volume-profile")
async def pro_trade_pa_volume_profile(
    payload: ProTradePaVolumeProfileRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await ProTradeService(SettingsService(db)).pa_volume_profile(
        tickers=payload.tickers,
        asset_class=payload.asset_class,
        exchange=payload.exchange,
        cfg_overrides={
            "timeframe": payload.timeframe,
            "lookback_bars": payload.lookback_bars,
            "vp_lookback": payload.vp_lookback,
            "num_bins": payload.num_bins,
            "poc_tolerance_pct": payload.poc_tolerance_pct,
            "breakout_buffer_pct": payload.breakout_buffer_pct,
        },
    )


@router.post("/pro-trade/pa-vp-smc")
async def pro_trade_pa_vp_smc(
    payload: ProTradePaVpSmcRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await ProTradeService(SettingsService(db)).pa_vp_smc(
        tickers=payload.tickers,
        asset_class=payload.asset_class,
        exchange=payload.exchange,
        cfg_overrides={
            "htf": payload.htf,
            "ltf": payload.ltf,
            "lookback_bars": payload.lookback_bars,
            "swing_window": payload.swing_window,
            "vp_num_bins": payload.vp_num_bins,
            "vp_value_area_pct": payload.vp_value_area_pct,
            "zone_tolerance_pct": payload.zone_tolerance_pct,
            "min_confluence_factors": payload.min_confluence_factors,
            "rr_min": payload.rr_min,
        },
    )


@router.post("/pro-trade/volume-spread-next-candle")
async def pro_trade_volume_spread_next_candle(
    payload: ProTradeVolumeSpreadNextCandleRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await ProTradeService(SettingsService(db)).volume_spread_next_candle(
        tickers=payload.tickers,
        asset_class=payload.asset_class,
        exchange=payload.exchange,
        cfg_overrides={
            "timeframe": payload.timeframe,
            "lookback_bars": payload.lookback_bars,
            "vol_ma_period": payload.vol_ma_period,
            "ultra_vol_lookback": payload.ultra_vol_lookback,
            "low_spread_factor": payload.low_spread_factor,
            "rr_ratio": payload.rr_ratio,
        },
    )


@router.post("/pro-trade/elliott-wave")
async def pro_trade_elliott_wave(
    payload: ProTradeElliottWaveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await ProTradeService(SettingsService(db)).elliott_wave(
        tickers=payload.tickers,
        asset_class=payload.asset_class,
        exchange=payload.exchange,
        cfg_overrides={
            "timeframe": payload.timeframe,
            "lookback_bars": payload.lookback_bars,
            "zigzag_pct": payload.zigzag_pct,
            "start_date": payload.start_date or "",
            "end_date": payload.end_date or "",
        },
    )


@router.post("/pro-trade/fibonacci-pro")
async def pro_trade_fibonacci_pro(
    payload: ProTradeFibonacciProRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await ProTradeService(SettingsService(db)).fibonacci_pro(
        tickers=payload.tickers,
        asset_class=payload.asset_class,
        exchange=payload.exchange,
        cfg_overrides={
            "timeframe": payload.timeframe,
            "lookback_bars": payload.lookback_bars,
            "fib_lookback": payload.fib_lookback,
            "secondary_lookback": payload.secondary_lookback,
            "zone_tol_atr": payload.zone_tol_atr,
            "min_rr": payload.min_rr,
            "strategies": payload.strategies or [],
            "start_date": payload.start_date or "",
            "end_date": payload.end_date or "",
        },
    )


@router.post("/pro-trade/bb-mean-reversion")
async def pro_trade_bb_mean_reversion(
    payload: ProTradeBbMeanReversionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await ProTradeService(SettingsService(db)).bb_mean_reversion(
        tickers=payload.tickers,
        asset_class=payload.asset_class,
        exchange=payload.exchange,
        timeframes=payload.timeframes,
        cfg_overrides={
            "lookback_bars": payload.lookback_bars,
            "bb_period": payload.bb_period,
            "bb_std": payload.bb_std,
            "er_hard_block": payload.er_hard_block,
            "er_soft_ceiling": payload.er_soft_ceiling,
            "squeeze_pctile_floor": payload.squeeze_pctile_floor,
            "rsi_overbought": payload.rsi_overbought,
            "rsi_oversold": payload.rsi_oversold,
            "zone_tolerance_pct": payload.zone_tolerance_pct,
            "min_rr": payload.min_rr,
            "extra_checks": payload.extra_checks,
        },
    )


@router.post("/pro-trade/traffic-light-indicator")
async def pro_trade_traffic_light_indicator(
    payload: ProTradeTrafficLightRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await ProTradeService(SettingsService(db)).traffic_light_indicator(
        tickers=payload.tickers,
        asset_class=payload.asset_class,
        exchange=payload.exchange,
        cfg_overrides={
            "timeframe": payload.timeframe,
            "lookback_bars": payload.lookback_bars,
            "further_analysis": payload.further_analysis,
            "rr_min": payload.rr_min,
            "sl_atr_mult": payload.sl_atr_mult,
            "tp_atr_mult": payload.tp_atr_mult,
            "take_confidence_threshold": payload.take_confidence_threshold,
        },
    )


@router.post("/pro-trade/buy-low-sell-high")
async def pro_trade_buy_low_sell_high(
    payload: ProTradeBuyLowSellHighRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await ProTradeService(SettingsService(db)).buy_low_sell_high(
        tickers=payload.tickers,
        asset_class=payload.asset_class,
        exchange=payload.exchange,
        cfg_overrides={
            "timeframe": payload.timeframe,
            "lookback_bars": payload.lookback_bars,
            "low_lookback": payload.low_lookback,
            "buy_buffer_pct": payload.buy_buffer_pct,
            "sell_target_pct": payload.sell_target_pct,
            "add_on_drop_pct": payload.add_on_drop_pct,
        },
    )


@router.post("/pro-trade/rlb-breakout")
async def pro_trade_rlb_breakout(
    payload: ProTradeRlbBreakoutRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await ProTradeService(SettingsService(db)).rlb_breakout(
        tickers=payload.tickers,
        asset_class=payload.asset_class,
        exchange=payload.exchange,
        cfg_overrides={
            "timeframe": payload.timeframe,
            "lookback_bars": payload.lookback_bars,
            "rsi_min": payload.rsi_min,
            "rsi_prefer": payload.rsi_prefer,
            "min_day_chg_pct": payload.min_day_chg_pct,
            "volume_sma_period": payload.volume_sma_period,
            "require_all_seven": payload.require_all_seven,
        },
    )


@router.post("/pro-trade/3-in-1-trade-system")
async def pro_trade_three_in_one(
    payload: ProTradeThreeInOneRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await ProTradeService(SettingsService(db)).three_in_one_trade_system(
        tickers=payload.tickers,
        asset_class=payload.asset_class,
        exchange=payload.exchange,
        cfg_overrides={
            "timeframe": payload.timeframe,
            "lookback_bars": payload.lookback_bars,
            "car_rising_days": payload.car_rising_days,
            "max_pct_above_200": payload.max_pct_above_200,
            "require_volume_breakout": payload.require_volume_breakout,
            "sip_gap_days": payload.sip_gap_days,
            "max_holdings": payload.max_holdings,
        },
    )


@router.post("/pro-trade/simple-effective")
async def pro_trade_simple_effective(
    payload: ProTradeSimpleEffectiveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await ProTradeService(SettingsService(db)).simple_effective(
        tickers=payload.tickers,
        asset_class=payload.asset_class,
        exchange=payload.exchange,
        timeframes=payload.timeframes,
        cfg_overrides={
            "lookback_bars": payload.lookback_bars,
            "ma_fast": payload.ma_fast,
            "ma_slow": payload.ma_slow,
            "use_ema": payload.use_ema,
            "rr_multiple": payload.rr_multiple,
            "timeframe": (payload.timeframes[0] if payload.timeframes else "15m"),
        },
    )


@router.post("/pro-trade/bb-rsi-vol")
async def pro_trade_bb_rsi_vol(
    payload: ProTradeBbRsiVolRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await ProTradeService(SettingsService(db)).bb_rsi_vol(
        tickers=payload.tickers,
        asset_class=payload.asset_class,
        exchange=payload.exchange,
        timeframes=payload.timeframes,
        cfg_overrides={
            "lookback_bars": payload.lookback_bars,
            "bb_period": payload.bb_period,
            "bb_std": payload.bb_std,
            "rsi_buy": payload.rsi_buy,
            "rsi_sell": payload.rsi_sell,
            "min_rr": payload.min_rr,
            "require_sr": payload.require_sr,
            "take_confidence_threshold": payload.take_confidence_threshold,
            "timeframe": (payload.timeframes[0] if payload.timeframes else "15m"),
        },
    )


@router.post("/pro-trade/btst")
async def pro_trade_btst(
    payload: ProTradeBtstRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await ProTradeService(SettingsService(db)).btst(
        tickers=payload.tickers,
        asset_class=payload.asset_class,
        exchange=payload.exchange,
        cfg_overrides={
            "lookback_bars": payload.lookback_bars,
            "min_clv": payload.min_clv,
            "min_volume_zscore": payload.min_volume_zscore,
            "climax_volume_zscore": payload.climax_volume_zscore,
            "min_relative_strength_pct": payload.min_relative_strength_pct,
            "sl_atr_mult": payload.sl_atr_mult,
            "tp_atr_mult": payload.tp_atr_mult,
            "min_rr": payload.min_rr,
            "historical_lookback_days": payload.historical_lookback_days,
            "check_oi_buildup": payload.check_oi_buildup,
            "further_analysis": payload.further_analysis,
        },
    )


@router.post("/pro-trade/ticker-chart")
async def pro_trade_ticker_chart(
    payload: ProTradeTickerChartRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await ProTradeService(SettingsService(db)).ticker_chart(
        ticker=payload.ticker,
        asset_class=payload.asset_class,
        mode=payload.mode,
        from_date=payload.from_date,
        to_date=payload.to_date,
        session_date=payload.session_date,
        interval=payload.interval,
    )


@router.post("/prediction/pattern-analogue")
async def prediction_pattern_analogue(
    payload: PredictionPatternAnalogueRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.prediction_service import PredictionService

    return await PredictionService(SettingsService(db)).pattern_analogue(
        tickers=payload.tickers,
        asset_class=payload.asset_class,
        exchange=payload.exchange,
        cfg_overrides={
            "timeframe": payload.timeframe,
            "pattern_bars": payload.pattern_bars,
            "forward_bars": payload.forward_bars,
            "search_lookback_bars": payload.search_lookback_bars,
            "search_from_date": payload.search_from_date or "",
            "search_to_date": payload.search_to_date or "",
            "top_n": payload.top_n,
            "min_similarity": payload.min_similarity,
        },
    )


@router.post("/prediction/astro-finance")
async def prediction_astro_finance(
    payload: PredictionAstroFinanceRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.prediction_service import PredictionService

    return await PredictionService(SettingsService(db)).astro_finance(
        strategy=payload.strategy,
        strategies=payload.strategies or None,
        tickers=payload.tickers,
        asset_class=payload.asset_class,
        exchange=payload.exchange,
        cfg_overrides={
            "lookback_days": payload.lookback_days,
            "forward_days": payload.forward_days,
            "event_window_days": payload.event_window_days,
            "strong_moon_signs": payload.strong_moon_signs or [],
            "timezone_name": payload.timezone_name or "",
        },
    )


@router.post("/workflow/evaluate")
async def workflow_evaluate(
    payload: WorkflowEvaluateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Run all desks for a Workflow market (India/US/Crypto/Commodities) in index or stock mode."""
    from app.services.workflow_evaluate_service import WorkflowEvaluateService

    return await WorkflowEvaluateService(SettingsService(db), db).evaluate(
        payload.market,
        payload.mode,
        tickers=payload.tickers or None,
    )


@router.post("/pro-trade/btst/start")
async def pro_trade_btst_start(
    payload: TradingHubBackgroundScanRequest,
    current_user: User = Depends(get_current_user),
):
    """Kick off a BTST/STBT scan as a background job and return immediately
    with a job id. Poll GET /pro-trade/btst/jobs/{id} for progress and result.

    When ``run_in_background`` is true (or ``report_name`` is set), the
    finished result is auto-saved under that name for later viewing.
    """
    from app.services.btst_jobs import BTST_SOURCE, create_job, run_btst_job

    report_name = (payload.report_name or "").strip() or None
    auto_save = bool(payload.run_in_background or report_name)
    if payload.run_in_background and not report_name:
        raise HTTPException(status_code=400, detail="Report name is required for background runs.")

    job = await create_job(
        name=report_name,
        user_id=current_user.id,
        source=BTST_SOURCE,
        meta={"asset_class": payload.asset_class, "auto_save": auto_save},
        request_payload={
            "tickers": payload.tickers,
            "asset_class": payload.asset_class,
            "config": payload.config,
            "report_name": report_name if auto_save else None,
        },
    )
    run_btst_job(
        job.id, payload.tickers, payload.asset_class, payload.config,
        report_name=report_name if auto_save else None,
        user_id=current_user.id if auto_save else None,
    )
    return {
        "job_id": job.id,
        "status": job.status,
        "name": job.name,
        "auto_save": auto_save,
    }


@router.get("/pro-trade/btst/jobs")
async def pro_trade_btst_list_jobs(
    status: str | None = "running",
    current_user: User = Depends(get_current_user),
):
    from app.services.btst_jobs import BTST_SOURCE, job_to_dict, list_jobs

    jobs = list_jobs(user_id=current_user.id, source=BTST_SOURCE, status=status or None)
    return {"jobs": [job_to_dict(j) for j in jobs]}


@router.get("/pro-trade/btst/jobs/{job_id}")
async def pro_trade_btst_job_status(
    job_id: str,
    current_user: User = Depends(get_current_user),
):
    from app.services.btst_jobs import get_job, job_to_dict

    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found (it may have expired).")
    if job.user_id is not None and job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found (it may have expired).")
    return job_to_dict(job)


@router.post("/pro-trade/btst/reports")
async def pro_trade_btst_save_report(
    payload: SaveTradingHubReportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ProTradeService(SettingsService(db), db)
    result = payload.payload
    tickers = [r.get("ticker") for r in (result.get("results") or []) if isinstance(r, dict) and r.get("ticker")]
    return await service.save_btst_report(
        payload.name, tickers, str(result.get("asset_class") or "india"),
        result, user_id=current_user.id,
    )


@router.get("/pro-trade/btst/reports")
async def pro_trade_btst_list_reports(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ProTradeService(SettingsService(db), db)
    return await service.list_btst_reports(user_id=current_user.id)


@router.get("/pro-trade/btst/reports/{report_id}")
async def pro_trade_btst_get_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ProTradeService(SettingsService(db), db)
    return await service.get_btst_report(report_id, user_id=current_user.id)


@router.delete("/pro-trade/btst/reports/{report_id}")
async def pro_trade_btst_delete_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ProTradeService(SettingsService(db), db)
    return await service.delete_btst_report(report_id, user_id=current_user.id)
