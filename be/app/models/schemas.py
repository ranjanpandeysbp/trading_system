from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field


class UserRegister(BaseModel):
    name: str = Field(..., min_length=2, max_length=128)
    mobile: str = Field(..., min_length=10, max_length=15)
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)


class UserLogin(BaseModel):
    identifier: str = Field(..., min_length=3, description="Email or 10-digit mobile")
    password: str = Field(..., min_length=1)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=10)
    new_password: str = Field(..., min_length=6, max_length=128)


class UserOut(BaseModel):
    id: int
    name: str
    mobile: str
    email: str
    created_at: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class MessageResponse(BaseModel):
    message: str
    reset_token: str | None = None
    reset_url: str | None = None


class StrategyInfo(BaseModel):
    id: str
    name: str
    category: str
    category_label: str
    timeframes: list[str]
    summary: str = ""
    description: str = ""
    indicators: list[str] = Field(default_factory=list)
    entry_rules: list[str] = Field(default_factory=list)
    exit_rules: list[str] = Field(default_factory=list)
    needs_benchmark: bool = False
    min_bars: int = 30


class StrategyCategoryInfo(BaseModel):
    id: str
    label: str
    description: str
    timeframes: list[str]
    strategy_count: int
    strategies: list[StrategyInfo]


class ScanRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=1)
    strategies: list[str] = Field(..., min_length=1)
    timeframes: list[str] = Field(..., min_length=1)
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"


class ScanSignal(BaseModel):
    ticker: str
    strategy: str
    strategy_label: str
    category: str
    timeframe: str
    action: Literal["BUY", "SELL", "HOLD"]
    signal: int
    price: float
    day_high: float | None = None
    day_low: float | None = None
    sl_pct: float
    tp_pct: float
    confidence_pct: float
    timestamp: str
    rationale: str


class ScanResponse(BaseModel):
    signals: list[ScanSignal]
    scanned_at: str


class BacktestRequest(BaseModel):
    ticker: str
    strategy: str
    timeframe: str = "1d"
    period: str | None = None
    costs_pct: float = 0.0008


class BacktestResponse(BaseModel):
    ticker: str
    strategy: str
    timeframe: str
    period: str
    bars_evaluated: int
    signal_count: int
    benchmark_ticker: str | None = None
    summary: str | None = None
    stats: dict
    recent_signals: list[dict]


class SettingsResponse(BaseModel):
    data_provider: str
    groww_token_set: bool
    groww_exchange: str = "NSE"
    initial_capital: float
    costs_pct: float
    benchmark_ticker: str
    gemini_token_set: bool = False
    groq_token_set: bool = False
    ai_provider: str = "Google Gemini"
    groq_model: str = "llama-3.3-70b-versatile"
    gemini_model: str = "gemini-2.0-flash"
    default_market: str = "Groww (India Stocks)"


class SettingsUpdate(BaseModel):
    data_provider: str | None = None
    groww_api_token: str | None = None
    groww_exchange: str | None = None
    initial_capital: float | None = None
    costs_pct: float | None = None
    benchmark_ticker: str | None = None
    gemini_api_key: str | None = None
    groq_api_key: str | None = None
    ai_provider: str | None = None
    groq_model: str | None = None
    gemini_model: str | None = None
    default_market: str | None = None


class AskAIRequest(BaseModel):
    context: str = Field(..., min_length=1)
    question: str | None = None
    section: str | None = None
    system_prompt: str | None = None
    max_tokens: int = Field(default=3000, ge=256, le=8000)


class AskAIResponse(BaseModel):
    report: str
    verdict: str | None = None
    provider: str
    model: str
    section: str | None = None
    error: bool = False


class AIConfigResponse(BaseModel):
    provider: str
    model: str
    gemini_token_set: bool
    groq_token_set: bool
    ready: bool
    groq_models: list[str]
    gemini_models: list[str]
    providers: list[str]


class PlaceOrderRequest(BaseModel):
    ticker: str
    side: Literal["buy", "sell"]
    quantity: int = Field(..., gt=0)
    price: float | None = None
    strategy: str | None = None
    notes: str | None = None
    sl_pct: float | None = None
    tp_pct: float | None = None
    order_type: Literal["market", "limit", "stop", "stop_limit"] = "market"
    limit_price: float | None = None
    trigger_price: float | None = None


class ModifyOrderRequest(BaseModel):
    quantity: int | None = Field(None, gt=0)
    limit_price: float | None = None
    trigger_price: float | None = None


class AccountSummary(BaseModel):
    id: int
    name: str
    cash_balance: float
    initial_capital: float
    portfolio_value: float
    total_pnl: float
    total_pnl_pct: float
    positions: list[dict]
    recent_orders: list[dict]
    pending_orders: list[dict]


class MarketPulseIndexRequest(BaseModel):
    index_name: str = "NIFTY 50"


class MarketPulseRotationRequest(BaseModel):
    index_name: str = "NIFTY 50"
    tf_key: str = "1d"
    lookback_bars: int = Field(default=5, ge=1, le=500)


class MarketPulseStockRotationMarketRequest(BaseModel):
    universe_id: str = "sp500"
    tf_key: str = "1d"
    lookback_bars: int = Field(default=5, ge=1, le=500)


class MarketPulseMtfRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=1)
    timeframes: list[str] | None = None
    is_crypto: bool = False


class MarketPulseAccurateStrategyRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=1)
    timeframe: str = "1h"
    min_confluence: float = Field(default=60.0, ge=40.0, le=85.0)
    rr_target: float = Field(default=2.0, ge=1.0, le=4.0)
    market: str = "India (Groww)"


class MarketPulsePumpDumpRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=1)
    timeframe: str = "15m"
    market: str = "India (Groww)"
    initial_balance: float = Field(default=1000.0, ge=100.0)


class MarketPulseSentimentRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=1)
    timeframes: list[str] = Field(default_factory=lambda: ["1d", "4h"])
    lookback_days: int = Field(default=120, ge=50, le=500)


class MarketPulseTickerInvestigationRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=1)
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"


class CommandCenterBuySellRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=1)
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"
    scenario: str = "balanced"
    durations: list[str] | None = None


class CommandCenterMegaRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=1)
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"
    durations: list[str] | None = None


class CommandCenterTickerScanRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=1)
    asset_class: Literal["india", "us", "crypto"] = "india"
    timeframes: list[str] | None = None


class CommandCenterTradeSetupRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=1)
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"
    timeframes: list[str] | None = None
    exchange: str | None = None


class CommandCenterTradeSetupDrillRequest(BaseModel):
    ticker: str = Field(..., min_length=1)
    timeframe: str = "15m"
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"


class CommandCenterDayBiasRequest(BaseModel):
    ticker: str = Field(..., min_length=1)
    timeframe: str = "1d"
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"
    exchange: str | None = None


class CommandCenterOneClickRequest(BaseModel):
    style: Literal["intraday", "scalping", "swing"]
    tickers: list[str] = Field(..., min_length=1)
    asset_class: Literal["india", "us", "crypto"] = "india"


class CommandCenterMfSchemesRequest(BaseModel):
    amc_id: int


class CommandCenterMfHoldingsRequest(BaseModel):
    scheme_ids: list[int] = Field(..., min_length=1)
    scheme_names: dict[int, str] = Field(default_factory=dict)
    from_date: str
    to_date: str


class CommandCenterEtfIndiaHoldingsRequest(BaseModel):
    scheme_ids: list[int] = Field(..., min_length=1)
    scheme_names: dict[int, str] = Field(default_factory=dict)
    from_date: str
    to_date: str


class CommandCenterEtfYahooHoldingsRequest(BaseModel):
    market: Literal["us", "crypto"] = "us"
    symbols: list[str] = Field(..., min_length=1)
    symbol_names: dict[str, str] = Field(default_factory=dict)
    from_date: str
    to_date: str


class CommandCenterInvestigateStrategiesRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=1)
    asset_class: Literal["india", "us", "crypto"] = "india"
    strategy_ids: list[str] = Field(default_factory=list)


class CommandCenterMegaAdviceRequest(BaseModel):
    market: str = "Groww (India Stocks)"
    timeframes: list[str] = Field(default_factory=list)
    ticker_count: int = 0
    use_ai: bool = False
    user_goal: str = ""


class CommandCenterHeatmapRequest(BaseModel):
    index_name: str
    asset_class: Literal["india", "us", "crypto"] = "india"
    tickers: list[str] | None = None


class CommandCenterSma20200Request(BaseModel):
    tickers: list[str] = Field(..., min_length=1)
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"
    timeframes: list[str] | None = None
    exchange: str | None = None
    fast_period: int = 20
    slow_period: int = 200
    rr_ratio: float = 2.0
    sl_buffer_pct: float = 0.1
    take_confidence_threshold: float = 55.0


class CommandCenterOptionChainRequest(BaseModel):
    symbol: str
    is_index: bool = True


class CommandCenterOptionShortLongRequest(BaseModel):
    symbols: list[str] = Field(..., min_length=1)
    is_index: bool = True
    expiries: list[str] | None = None


class CommandCenterQuickAnalyzerRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=1)
    timeframes: list[str] = Field(..., min_length=1)
    asset_class: Literal["india", "us", "crypto"] = "india"
    from_date: str | None = None
    to_date: str | None = None
    include_fundamentals: bool = False
    include_option_chain: bool = False


class TradingHubScanRequest(BaseModel):
    section_id: str
    tickers: list[str] = Field(..., min_length=1)
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"
    config: dict[str, Any] | None = None
    run_backtest: bool = False


class EtfTaScanRequest(BaseModel):
    symbols: list[str] | None = None
    exchange: str = "NSE"


class EtfTaRecommendRequest(BaseModel):
    symbols: list[str] | None = None
    exchange: str = "NSE"
    deposited_capital: float = 500_000.0
    growth_amount: float = 0.0
    dividend_withdrawn: float = 0.0
    portfolio: list[dict[str, Any]] = Field(default_factory=list)
    sip_locked: list[str] = Field(default_factory=list)
    sell_mode: Literal["combined", "percentage", "absolute"] = "combined"
    profit_target_pct: float = 6.0
    profit_target_inr: float = 700.0
    min_profit_inr: float = 500.0
    slots_divisor: int = Field(default=60, ge=30, le=90)
    shop_start_date: str | None = None
    prefer_sip: bool = True


class MarketPulseCommodityRequest(BaseModel):
    timeframes: list[str] | None = None


class MarketPulseHeatmapRequest(BaseModel):
    timeframe: str = "1d"
    mode: str = "sectoral"


class TaScreenerRunRequest(BaseModel):
    screener_id: str
    tickers: list[str] = Field(..., min_length=1)
    timeframe: str | None = None
    options: dict[str, Any] | None = None
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"


class StrategyLabBacktestRequest(BaseModel):
    ticker: str
    timeframe: str = "1d"
    market: str | None = None
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"
    preset_name: str | None = None
    indicators: list[dict[str, Any]] | None = None
    entry_rules: list[dict[str, Any]] | None = None
    exit_rules: list[dict[str, Any]] | None = None
    entry_mode: str = "AND"
    exit_mode: str = "AND"
    capital: float = 100_000.0
    commission: float = 0.001
    slippage: float = 0.0005
    sl_pct: float = 0.0
    tp_pct: float = 0.0
    days: int | None = None
    direction_mode: Literal["long_only", "short_only", "long_short"] = "long_only"
    position_sizing: Literal["pct_of_capital", "risk_pct"] = "pct_of_capital"
    capital_allocation_pct: float = 95.0
    risk_pct: float = 1.0


class StrategyLabMultiComboRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=1)
    timeframes: list[str] = Field(default_factory=lambda: ["1d"])
    strategies: list[str] | None = None
    market: str | None = None
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"
    capital: float = 100_000.0
    commission: float = 0.001


class StrategyLabScreenerRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=1)
    timeframes: list[str] = Field(default_factory=lambda: ["1d"])
    indicators: list[dict[str, Any]] | None = None
    entry_rules: list[dict[str, Any]] | None = None
    entry_mode: str = "AND"
    market: str | None = None
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"
    screener_preset: str | None = None


class SeasonalityRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=1)
    years: int = Field(default=10, ge=3, le=20)
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"


class AlertMonitorCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    ticker: str
    timeframe: str = "1d"
    market: str | None = None
    strategy_name: str = "Custom"
    indicators: list[dict[str, Any]] = Field(default_factory=list)
    entry_rules: list[dict[str, Any]] = Field(default_factory=list)
    exit_rules: list[dict[str, Any]] = Field(default_factory=list)
    entry_mode: str = "AND"
    poll_minutes: int = Field(default=15, ge=1, le=1440)
    notify_telegram: bool = True
    notify_email: bool = False
    enabled: bool = True


class MarketPulsePagination(BaseModel):
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=10, ge=1, le=50)


class WatchlistCreate(BaseModel):
    market_type: Literal["india", "us", "crypto"] = "india"
    name: str = Field(..., min_length=1, max_length=128)


class WatchlistItemCreate(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=32)
    display_name: str = ""
    added_price: float | None = None
    notes: str | None = None


class OptionsDoubleCalendarRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=1)
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"
    timeframes: list[str] | None = None
    exchange: str | None = None
    short_dte: int = 14
    long_dte: int = 21
    otm_offset_pct: float = 1.5
    diagonal_widen_pct: float = 0.0
    take_profit_start: float = 0.20
    take_profit_max: float = 0.40
    stop_loss: float = -0.30
    vix_max_threshold: float = 20.0
    vol_percentile_max: float = 40.0


class OptionsDoubleCalendarPnlRequest(BaseModel):
    net_debit: float
    current_mark: float
    stop_loss: float = -0.30
    take_profit_start: float = 0.20
    take_profit_max: float = 0.40


class OptionsDeltaNeutralRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=1)
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"
    timeframes: list[str] | None = None
    exchange: str | None = None
    dte: int = 30
    short_delta_target: float = 0.20
    wing_width_pct: float = 5.0
    iron_fly: bool = False
    profit_target_pct: float = 0.50
    stop_loss_multiple: float = 1.0
    vix_max_threshold: float = 20.0
    vol_percentile_max: float = 40.0
    adx_trend_max: float = 25.0


class OptionsDeltaNeutralPnlRequest(BaseModel):
    net_credit: float
    current_cost_to_close: float
    profit_target_pct: float = 0.50
    stop_loss_multiple: float = 1.0


class OptionsGokulChhabraRequest(BaseModel):
    tickers: list[str] | None = None  # ignored — fixed Nifty 50 / Bank Nifty universe
    exchange: str | None = None
    vwma_length: int = 20
    st_period: int = 10
    st_multiplier: float = 3.0
    session_start: str = "09:45"
    session_end: str = "15:15"
    pullback_tol_pct: float = 0.08
    min_rr: float = 2.0
    target_delta_min: float = 0.60
    target_delta_max: float = 0.75
