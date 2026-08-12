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


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1, max_length=128)
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
    bars: int | None = Field(None, ge=150, le=2000)


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
    data_source: str | None = None
    data_sources_used: list[str] | None = None
    data_source_label: str | None = None
    data_source_counts: dict[str, int] | None = None


class BacktestRequest(BaseModel):
    ticker: str
    strategy: str
    timeframe: str = "1d"
    period: str | None = None
    costs_pct: float = 0.0008
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"
    direction: Literal["both", "long_only", "short_only"] = "both"


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
    groww_api_key_set: bool = False
    groww_totp_secret_set: bool = False
    groww_token_expires_at: str | None = None
    indmoney_client_id_set: bool = False
    indmoney_mpin_set: bool = False
    indmoney_totp_secret_set: bool = False
    indmoney_access_token_set: bool = False
    indmoney_token_expires_at: str | None = None
    initial_capital: float
    costs_pct: float
    benchmark_ticker: str
    gemini_token_set: bool = False
    groq_token_set: bool = False
    claude_token_set: bool = False
    openai_token_set: bool = False
    ai_provider: str = "Google Gemini"
    groq_model: str = "llama-3.3-70b-versatile"
    gemini_model: str = "gemini-2.0-flash"
    claude_model: str = "claude-sonnet-5"
    claude_endpoint: str = "https://atul-mjil3w7p-swedencentral.services.ai.azure.com/anthropic"
    openai_model: str = "gpt-5.6-sol"
    openai_endpoint: str = "https://aiadvisorassis8258039388.services.ai.azure.com/openai/v1"
    default_market: str = "Groww (India Stocks)"
    youtube_api_key_set: bool = False
    youtube_channel_ids: str = ""
    superinvesting_token_set: bool = False


class SettingsUpdate(BaseModel):
    data_provider: str | None = None
    groww_api_token: str | None = None
    groww_exchange: str | None = None
    groww_api_key: str | None = None
    groww_totp_secret: str | None = None
    indmoney_client_id: str | None = None
    indmoney_mpin: str | None = None
    indmoney_totp_secret: str | None = None
    indmoney_access_token: str | None = None
    initial_capital: float | None = None
    costs_pct: float | None = None
    benchmark_ticker: str | None = None
    gemini_api_key: str | None = None
    groq_api_key: str | None = None
    claude_api_key: str | None = None
    openai_api_key: str | None = None
    ai_provider: str | None = None
    groq_model: str | None = None
    gemini_model: str | None = None
    claude_model: str | None = None
    claude_endpoint: str | None = None
    openai_model: str | None = None
    openai_endpoint: str | None = None
    default_market: str | None = None
    youtube_api_key: str | None = None
    youtube_channel_ids: str | None = None
    superinvesting_token: str | None = None


class InvestingAgentChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)


class InvestingAgentTokenRequest(BaseModel):
    token: str = Field(..., min_length=10)


class InvestingAgentStockRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=32)


class AskAIRequest(BaseModel):
    context: str = Field(..., min_length=1)
    question: str | None = None
    section: str | None = None
    system_prompt: str | None = None
    max_tokens: int = Field(default=3000, ge=256, le=8000)
    mode: Literal["ask", "next_move"] = "ask"


class AskAIResponse(BaseModel):
    report: str
    verdict: str | None = None
    confidence_pct: float | None = None
    provider: str
    model: str
    section: str | None = None
    error: bool = False


class DashboardTradingChatRequest(BaseModel):
    """Dashboard chatbot — BB Mean Reversion + all confluence + Manage AI conclusion."""
    message: str = Field(..., min_length=2, max_length=2000)
    asset_class: str | None = None  # india | us | crypto | commodity (optional override)
    style: str | None = None  # scalping | intraday | swing | investing
    tickers: list[str] = Field(default_factory=list)
    extra_checks: list[str] = Field(default_factory=list)  # empty = all 13 confluence checks
    top_n: int | None = Field(default=None, ge=1, le=500)  # None = all eligible picks
    skip_ai: bool = False
    deep_mode: bool = False  # backtest-rank strategies → encyclopedia → live → AI
    # Follow-up: explain prior desk result ("why…") without re-scanning
    explain_only: bool = False
    prior_result: dict[str, Any] | None = None


class AIConfigResponse(BaseModel):
    provider: str
    model: str
    gemini_token_set: bool
    groq_token_set: bool
    superinvesting_token_set: bool = False
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
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"


class ModifyOrderRequest(BaseModel):
    quantity: int | None = Field(None, gt=0)
    limit_price: float | None = None
    trigger_price: float | None = None


class BulkIdsRequest(BaseModel):
    ids: list[int] = Field(..., min_length=1)


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
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"
    timeframes: list[str] | None = None
    from_date: str | None = None
    to_date: str | None = None


class CommandCenterMarketMoversRequest(BaseModel):
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"
    index: str
    timeframe: str = "1d"


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
    run_in_background: bool = False
    report_name: str | None = None


class SaveMfHoldingsReportRequest(BaseModel):
    name: str
    payload: dict[str, Any]


class CommandCenterBestMfRequest(BaseModel):
    amc_ids: list[int] = Field(..., min_length=1)
    asset_type_id: int = 1
    category_filter: str = ""
    rank_period: int = 365
    top_n: int = 30
    run_in_background: bool = False
    report_name: str | None = None


class SaveBestMfReportRequest(BaseModel):
    name: str
    payload: dict[str, Any]


class MfFirePlanRequest(BaseModel):
    """MF FIRE planner — 25×/35× FI, 1% rule, crore milestones, SIP runway.

    Source: https://www.youtube.com/watch?v=HmW6T6i2Okc&t=6s
    """
    annual_expenses: float = Field(default=600_000, ge=0, le=1e9)
    monthly_salary: float = Field(default=100_000, ge=0, le=1e8)
    current_corpus: float = Field(default=0, ge=0, le=1e11)
    monthly_sip: float = Field(default=25_000, ge=0, le=1e8)
    expected_equity_return_pct: float = Field(default=12.0, ge=0, le=30)
    inflation_pct: float = Field(default=6.5, ge=0, le=20)
    fire_multiple: float = Field(default=25.0, ge=10, le=50)
    long_runway_multiple: float = Field(default=35.0, ge=15, le=60)
    equity_only_until_cr: float = Field(default=3.0, ge=0.5, le=20)
    age: int | None = Field(default=35, ge=18, le=80)
    home_loan_balance: float = Field(default=0, ge=0, le=1e10)
    home_loan_rate_pct: float = Field(default=8.5, ge=0, le=25)
    extra_emi_toward_loan: float = Field(default=0, ge=0, le=1e7)
    dual_income: bool = False
    principles_checklist: list[str] = Field(default_factory=list)


class CommandCenterEtfIndiaHoldingsRequest(BaseModel):
    scheme_ids: list[int] = Field(..., min_length=1)
    scheme_names: dict[int, str] = Field(default_factory=dict)
    from_date: str
    to_date: str
    run_in_background: bool = False
    report_name: str | None = None


class CommandCenterEtfYahooHoldingsRequest(BaseModel):
    market: Literal["us", "crypto"] = "us"
    symbols: list[str] = Field(..., min_length=1)
    symbol_names: dict[str, str] = Field(default_factory=dict)
    from_date: str
    to_date: str
    run_in_background: bool = False
    report_name: str | None = None


class SaveEtfHoldingsReportRequest(BaseModel):
    name: str
    payload: dict[str, Any]


class CommandCenterIndiaFiiDiiHoldingsRequest(BaseModel):
    """India FII-DII Holding — ownership · P&L · valuation · deals (screener.in)."""
    tickers: list[str] = Field(..., min_length=1)
    from_date: str
    to_date: str
    run_in_background: bool = False
    report_name: str | None = None


class SaveFiiDiiHoldingsReportRequest(BaseModel):
    name: str
    payload: dict[str, Any]


class CommandCenterSmartMoneyActivityRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=1)
    asset_class: Literal["india", "us", "crypto"] = "india"
    source: Literal["mutual_fund", "etf", "both"] = "both"
    from_date: str
    to_date: str
    # Optional manual selection — when set, overrides preferred-AMC auto universe
    amc_ids: list[int] = Field(default_factory=list)
    mf_scheme_ids: list[int] = Field(default_factory=list)
    mf_scheme_names: dict[int, str] = Field(default_factory=dict)
    etf_scheme_ids: list[int] = Field(default_factory=list)
    etf_scheme_names: dict[int, str] = Field(default_factory=dict)
    etf_symbols: list[str] = Field(default_factory=list)
    etf_symbol_names: dict[str, str] = Field(default_factory=dict)
    run_in_background: bool = False
    report_name: str | None = None


class SaveSmartMoneyActivityReportRequest(BaseModel):
    name: str
    tickers: list[str] = Field(default_factory=list)
    from_date: str = ""
    to_date: str = ""
    payload: dict[str, Any]


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


class CommandCenterAdvanceDeclineGraphRequest(BaseModel):
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"
    index_name: str = "NIFTY 50"
    from_date: str
    to_date: str
    timeframe: str = Field(default="1d", description="1d (daily) or intraday: 5m, 10m, 15m, 30m, 1h")
    session_date: str | None = Field(default=None, description="Session day for intraday (defaults to to_date)")
    as_of_time: str | None = Field(default=None, description="Optional HH:MM — include bars up to this time")
    exchange: str | None = None


class CommandCenterComparativeStrengthRequest(BaseModel):
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"
    base_symbol: str = Field(..., min_length=1, max_length=64)
    compare_symbols: list[str] = Field(..., min_length=1)
    timeframe: str = Field(default="1d", description="1m, 5m, 15m, 30m, 1h, 4h, 1d, 1w")
    lookback_bars: int = Field(default=20, ge=3, le=120)
    exchange: str | None = None


class CommandCenterOilDollarBondRequest(BaseModel):
    from_date: str | None = Field(default=None, description="YYYY-MM-DD (daily mode)")
    to_date: str | None = Field(default=None, description="YYYY-MM-DD (daily mode)")
    mode: Literal["daily", "intraday"] = "daily"
    session_date: str | None = Field(default=None, description="YYYY-MM-DD for same-day intraday")
    interval: str = Field(default="1d", description="1d for daily; 1m/5m/15m/30m/1h for intraday")


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


class DetectSectorRotationRequest(BaseModel):
    market: Literal["india", "us", "crypto"] = "india"
    sectors: list[str] | None = None
    crs_sma_period: int = 50
    hma_length: int = 9
    pullback_months: int = 2
    pullback_mode: Literal["months", "quarters"] = "months"


class TradingHubScanRequest(BaseModel):
    section_id: str
    tickers: list[str] = Field(..., min_length=1)
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"
    config: dict[str, Any] | None = None
    run_backtest: bool = False


class TradingHubBackgroundScanRequest(BaseModel):
    tickers: list[str] = Field(default_factory=list)
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"
    config: dict[str, Any] | None = None
    run_in_background: bool = False
    report_name: str | None = None


class SaveTradingHubReportRequest(BaseModel):
    name: str
    payload: dict[str, Any]


class SupportResistanceChartRequest(BaseModel):
    ticker: str = Field(..., min_length=1)
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"
    timeframe: str = "1d"
    ltf: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    include_volume: bool = True
    ema_periods: list[int] = Field(default_factory=list)
    include_rsi: bool = False
    include_fibonacci: bool = False
    include_supply_demand: bool = False
    include_order_blocks: bool = False


class BramhastraChartRequest(BaseModel):
    ticker: str = Field(..., min_length=1)
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"
    config: dict[str, Any] | None = None


class Swing5ScanRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=1)
    timeframes: list[str] = Field(default_factory=lambda: ["1d"])
    strategies: list[str] = Field(..., min_length=1)
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"
    config: dict[str, Any] | None = None


class EtfTopDownScanRequest(BaseModel):
    """ETF Top Down — Finding Edge/Jay: noise macros, dual P&F RS (max 18), Renko/D-Smart 10, Friday rebalance."""
    tickers: list[str] = Field(default_factory=list)
    preset: str | None = None
    exchange: str = "NSE"
    top_n: int = Field(default=20, ge=5, le=40)
    renko_box_pct: float = Field(default=1.0, ge=0.25, le=5.0)
    pn_f_box_pct: float = Field(default=0.25, ge=0.1, le=2.0, description="Daily P&F box % (weekly fixed at 1%)")
    d_smart_period: int = Field(default=10, ge=5, le=20)
    lookback_bars: int = Field(default=400, ge=120, le=800)
    max_etfs_hold: int = Field(default=10, ge=1, le=20)


class FallingKnifeScanRequest(BaseModel):
    """Falling Knife — live session rise/fall scan and/or date-range history + forecast."""
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"
    tickers: list[str] = Field(default_factory=list)
    drop_pct: float = Field(default=10.0, ge=0.5, le=90.0)
    lookback_hours: float = Field(default=24.0, ge=1.0, le=336.0)
    exchange: str | None = None
    # History mode (when from_date set); from_top = peak drawdown over Y years
    mode: Literal["live", "history", "from_top"] = "live"
    from_date: str | None = None
    to_date: str | None = None
    move_side: Literal["fall", "rise", "both"] = "both"
    threshold_pct: float | None = Field(
        default=None,
        ge=0.5,
        le=90.0,
        description="History mode: min % rise/fall to count as an event (defaults to drop_pct).",
    )
    lookback_years: float | None = Field(
        default=None,
        ge=0.5,
        le=5.0,
        description="From-top mode: years of history for the peak (defaults to 1).",
    )


class Etf28SmaLotInput(BaseModel):
    symbol: str
    price: float = Field(gt=0)
    amount: float = Field(default=0, ge=0)
    units: float | None = None
    purchase_date: str | None = None
    lot_id: str | None = None


class Etf28SmaScanRequest(BaseModel):
    """ETF 28 SMA Momentum — FIRE in India rules (2 closes above/below SMA28, 3.14%, averaging)."""
    tickers: list[str] = Field(default_factory=list)
    preset: str | None = None
    exchange: str = "NSE"
    total_capital: float = Field(default=500_000.0, ge=10_000, le=100_000_000)
    averaging_reserve_pct: float = Field(default=30.0, ge=0, le=90)
    max_etfs: int = Field(default=20, ge=1, le=80)
    max_new_buys_per_day: int = Field(default=4, ge=1, le=10)
    sell_mode: Literal["FIFO", "LIFO"] = "FIFO"
    capital_exhausted: bool = False
    profit_target_pct: float = Field(default=3.14, ge=1.0, le=20.0)
    avg_min_drop_pct: float = Field(default=5.0, ge=1.0, le=25.0)
    fast_momentum_pct: float = Field(default=18.0, ge=5.0, le=50.0)
    lookback_bars: int = Field(default=400, ge=260, le=800)
    holdings: list[Etf28SmaLotInput] = Field(default_factory=list)


class EtfTaScanRequest(BaseModel):
    symbols: list[str] | None = None
    exchange: str = "NSE"
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"


class EtfTaRecommendRequest(BaseModel):
    symbols: list[str] | None = None
    exchange: str = "NSE"
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"
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
    averaging_trigger_pct: float = -10.0


class EtfShopConfigUpdateRequest(BaseModel):
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"
    deposited_capital: float | None = None
    growth_amount: float | None = None
    dividend_withdrawn: float | None = None
    shop_start_date: str | None = None
    preset: str | None = None
    custom_symbols: str | None = None
    exchange: str | None = None
    sell_mode: Literal["combined", "percentage", "absolute"] | None = None
    profit_target_pct: float | None = None
    profit_target_inr: float | None = None
    min_profit_inr: float | None = None
    slots_divisor: int | None = Field(default=None, ge=30, le=90)
    prefer_sip: bool | None = None
    averaging_trigger_pct: float | None = None
    notify_telegram: bool | None = None
    notify_email: bool | None = None


class EtfShopAddLotRequest(BaseModel):
    symbol: str
    price: float = Field(..., gt=0)
    amount: float = Field(..., gt=0)
    lot_type: Literal["standard", "sip"] = "standard"
    purchase_date: str | None = None
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"


class EtfShopCloseLotRequest(BaseModel):
    sale_price: float = Field(..., gt=0)
    sale_date: str | None = None
    dividend_pct: float = Field(default=0.0, ge=0, le=100)


class AutoTradeSetupCreateRequest(BaseModel):
    name: str = Field(..., max_length=120)
    asset_class: Literal["india", "us", "crypto", "commodity"]
    style: Literal["scalping", "intraday", "swing", "investing"]
    direction: Literal["both", "long_only", "short_only"] = "both"
    interval_minutes: int = Field(default=360, ge=1, le=1440)
    universe_cap: int = Field(default=20, ge=5, le=50)
    top_n: int = Field(default=8, ge=1, le=20)


class AutoTradeSetupUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    direction: Literal["both", "long_only", "short_only"] | None = None
    interval_minutes: int | None = Field(default=None, ge=1, le=1440)
    universe_cap: int | None = Field(default=None, ge=5, le=50)
    top_n: int | None = Field(default=None, ge=1, le=20)


class TodoCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    notes: str | None = None


class TodoUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    notes: str | None = None
    status: Literal["pending", "done"] | None = None


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


class StrategyLeaderboardRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=1)
    timeframes: list[str] = Field(default_factory=lambda: ["1d"])
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"
    strategy_ids: list[str] | None = None
    bars: int = Field(350, ge=150, le=2000)
    forward_bars: int = Field(10, ge=3, le=60)


class SaveBacktestReportRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    payload: dict[str, Any]


class BacktesterLeaderboardRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=1)
    strategy_ids: list[str] = Field(..., min_length=1)
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"
    timeframe: str | None = None
    period: str | None = None
    costs_pct: float | None = None
    bars: int = Field(350, ge=150, le=2000)
    forward_bars: int = Field(10, ge=3, le=60)
    direction: Literal["both", "long_only", "short_only"] = "both"
    # When set, the job auto-saves a named report on completion (background run).
    report_name: str | None = Field(None, max_length=200)
    run_in_background: bool = False


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


class AlertScheduleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    market: Literal["india", "us", "crypto", "commodity"] = "india"
    tickers: list[str] = Field(..., min_length=1)
    timeframes: list[str] = Field(..., min_length=1)
    strategies: list[str] = Field(..., min_length=1)
    schedule_mode: Literal["interval", "daily_at"] = "interval"
    poll_minutes: int = Field(default=15, ge=1, le=1440)
    daily_time: str | None = Field(default=None, description="HH:MM local")
    notify_telegram: bool = True
    notify_email: bool = False
    enabled: bool = False


class AlertScheduleUpdate(BaseModel):
    name: str | None = None
    tickers: list[str] | None = None
    timeframes: list[str] | None = None
    strategies: list[str] | None = None
    schedule_mode: Literal["interval", "daily_at"] | None = None
    poll_minutes: int | None = Field(default=None, ge=1, le=1440)
    daily_time: str | None = None
    notify_telegram: bool | None = None
    notify_email: bool | None = None
    enabled: bool | None = None


class AlertScheduleHitsDelete(BaseModel):
    ids: list[int] = []
    delete_all: bool = False
    schedule_id: int | None = None


class CustomStrategyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    market: str
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"
    description: str | None = None
    timeframe: str = "1d"
    indicators: list[dict[str, Any]] = Field(default_factory=list)
    entry_rules: list[dict[str, Any]] = Field(default_factory=list)
    exit_rules: list[dict[str, Any]] = Field(default_factory=list)
    entry_mode: Literal["AND", "OR"] = "AND"
    exit_mode: Literal["AND", "OR"] = "AND"
    direction_mode: Literal["long_only", "short_only", "long_short"] = "long_only"
    position_sizing: Literal["pct_of_capital", "risk_pct"] = "pct_of_capital"
    capital_allocation_pct: float = 95.0
    risk_pct: float = 1.0
    sl_pct: float = 0.0
    tp_pct: float = 0.0
    source: Literal["manual", "ai"] = "manual"


class CustomStrategyUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    timeframe: str | None = None
    indicators: list[dict[str, Any]] | None = None
    entry_rules: list[dict[str, Any]] | None = None
    exit_rules: list[dict[str, Any]] | None = None
    entry_mode: Literal["AND", "OR"] | None = None
    exit_mode: Literal["AND", "OR"] | None = None
    direction_mode: Literal["long_only", "short_only", "long_short"] | None = None
    position_sizing: Literal["pct_of_capital", "risk_pct"] | None = None
    capital_allocation_pct: float | None = None
    risk_pct: float | None = None
    sl_pct: float | None = None
    tp_pct: float | None = None


class AIStrategyGenerateRequest(BaseModel):
    text: str = Field(..., min_length=10)
    market: str
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"
    strategy_name: str | None = None


class TradeCandidateCreate(BaseModel):
    name: str | None = None
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"
    ticker: str = Field(..., min_length=1)
    timeframe: str = Field(..., min_length=1)
    strategies: list[str] = Field(..., min_length=1)
    enabled: bool = True


class TradeCandidateUpdate(BaseModel):
    name: str | None = None
    ticker: str | None = None
    timeframe: str | None = None
    strategies: list[str] | None = None
    enabled: bool | None = None


class TradeCandidateHitsDelete(BaseModel):
    ids: list[int] = []
    delete_all: bool = False
    candidate_id: int | None = None


class AlertNotifyConfigUpdate(BaseModel):
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_user: str | None = None
    smtp_password: str | None = None  # omit / empty = keep existing
    smtp_from: str | None = None
    email_to: str | None = None  # comma-separated
    telegram_bot_token: str | None = None
    telegram_chat_ids: str | None = None


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


class WatchlistItemUpdate(BaseModel):
    display_name: str | None = None
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


class OptionsHedgingRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=1)
    asset_class: Literal["india", "us", "crypto", "commodity"] = "india"
    exchange: str | None = None
    dte: int = 2
    hedge_distance_pct: float = 4.0
    zone_timeframe: str = "15m"
    zone_fallback_timeframe: str = "1h"
    total_capital: float = 500_000.0
    profit_target_pct_of_capital: float = 0.0125
    max_loss_pct_of_capital: float = 0.025
    max_adjustments_per_day: int = 1


class OptionsHedgingPnlRequest(BaseModel):
    total_capital: float
    current_pnl: float
    profit_target_pct_of_capital: float = 0.0125
    max_loss_pct_of_capital: float = 0.025


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


class OptionsMarketPredictionRequest(BaseModel):
    symbol: str = "NIFTY"
    is_index: bool = True
    exchange: str | None = None
    futures_price: float | None = None
    fii_index_position_cut: bool | None = None
    further_analysis: list[str] | None = None


class OptionsCallPutWritingRequest(BaseModel):
    """Call / Put writing walls from option-chain OI — resistance, support, short-covering risk."""
    symbol: str = "NIFTY"
    is_index: bool = True
    exchange: str | None = None


class OptionsZeroToHeroRequest(BaseModel):
    tickers: list[str] | None = None  # ignored — fixed Nifty 50 / Bank Nifty universe
    exchange: str | None = None
    execution_tf: str = "15m"
    sl_buffer_pct: float = 0.05
    max_pullback_candles: int = 3
    partial_book_rr: float = 1.0
    partial_book_pct: float = 55.0
    session_end: str = "15:15"


class OptionsBackgroundStartRequest(BaseModel):
    """Loose start payload for Options background jobs. Section-specific
    fields (tickers, DTEs, etc.) are accepted via extra='allow' and forwarded
    to the matching OptionsService method."""
    model_config = {"extra": "allow"}
    run_in_background: bool = True
    report_name: str | None = None


class SaveOptionsReportRequest(BaseModel):
    name: str
    payload: dict[str, Any]


class AnalysisBackgroundStartRequest(BaseModel):
    """Generic start payload for analysis background jobs across domains."""
    model_config = {"extra": "allow"}
    domain: str
    section: str
    run_in_background: bool = True
    report_name: str | None = None


class SaveAnalysisReportRequest(BaseModel):
    name: str
    payload: dict[str, Any]


class ProTradeVolumeProfileCeRequest(BaseModel):
    """Volume Profile CE scan — VA reversal, POC compression, I-profile LVN."""
    tickers: list[str] = Field(default_factory=list)
    asset_class: str = "india"
    exchange: str | None = None
    intraday_tf: str = "15m"
    daily_tf: str = "1d"
    num_bins: int = Field(default=50, ge=10, le=120)
    value_area_pct: float = Field(default=0.70, ge=0.5, le=0.9)
    compression_days: int = Field(default=3, ge=2, le=10)
    compression_threshold_pct: float = Field(default=0.20, ge=0.05, le=2.0)
    val_touch_tol_pct: float = Field(default=0.15, ge=0.02, le=1.0)
    lvn_threshold_pct: float = Field(default=0.10, ge=0.02, le=0.4)


class ProTradeVolumeProfilePocRequest(BaseModel):
    """Volume Profile POC — first-touch pullback to HVN zone edge."""
    tickers: list[str] = Field(default_factory=list)
    asset_class: str = "india"
    exchange: str | None = None
    timeframe: str = "1d"
    lookback_bars: int = Field(default=120, ge=40, le=400)
    profile_bars: int = Field(default=60, ge=20, le=200)
    num_bins: int = Field(default=40, ge=10, le=120)
    cluster_vol_pct: float = Field(default=0.70, ge=0.4, le=0.95)
    breakout_buffer_pct: float = Field(default=1.0, ge=0.1, le=5.0)


class ProTradePaVolumeProfileRequest(BaseModel):
    """PA + Volume Profile — FVG and S/R flip filtered by VP clusters (Trader Dale)."""
    tickers: list[str] = Field(default_factory=list)
    asset_class: str = "india"
    exchange: str | None = None
    timeframe: str = "15m"
    lookback_bars: int = Field(default=200, ge=60, le=500)
    vp_lookback: int = Field(default=40, ge=10, le=120)
    num_bins: int = Field(default=40, ge=10, le=120)
    poc_tolerance_pct: float = Field(default=0.35, ge=0.05, le=2.0)
    breakout_buffer_pct: float = Field(default=0.15, ge=0.05, le=2.0)


class ProTradePaVpSmcRequest(BaseModel):
    """PA-VP-SMC — Price Action + Volume Profile + Smart Money Concepts confluence."""
    tickers: list[str] = Field(default_factory=list)
    asset_class: str = "india"
    exchange: str | None = None
    htf: str = "1h"
    ltf: str = "15m"
    lookback_bars: int = Field(default=300, ge=80, le=600)
    swing_window: int = Field(default=5, ge=3, le=15)
    vp_num_bins: int = Field(default=50, ge=10, le=120)
    vp_value_area_pct: float = Field(default=0.70, ge=0.5, le=0.95)
    zone_tolerance_pct: float = Field(default=0.5, ge=0.1, le=3.0)
    min_confluence_factors: int = Field(default=3, ge=1, le=7)
    rr_min: float = Field(default=1.5, ge=0.5, le=5.0)


class ProTradeVolumeSpreadNextCandleRequest(BaseModel):
    """Volume Spread Analysis — VSA signals predicting the next candle (Wyckoff)."""
    tickers: list[str] = Field(default_factory=list)
    asset_class: str = "india"
    exchange: str | None = None
    timeframe: str = "15m"
    lookback_bars: int = Field(default=200, ge=60, le=500)
    vol_ma_period: int = Field(default=20, ge=10, le=50)
    ultra_vol_lookback: int = Field(default=50, ge=20, le=120)
    low_spread_factor: float = Field(default=0.75, ge=0.4, le=1.0)
    rr_ratio: float = Field(default=1.5, ge=0.5, le=5.0)


class ProTradeElliottWaveRequest(BaseModel):
    """Elliott Wave — ZigZag-filtered 5-wave impulse / ABC corrective detection."""
    tickers: list[str] = Field(default_factory=list)
    asset_class: str = "india"
    exchange: str | None = None
    timeframe: str = "1d"
    lookback_bars: int = Field(default=250, ge=50, le=650)
    zigzag_pct: float = Field(default=3.0, ge=1.0, le=10.0)
    start_date: str | None = None
    end_date: str | None = None


class ProTradeFibonacciProRequest(BaseModel):
    """Fibonacci Pro — multi-strategy Fib playbook (golden pocket, OTE, 78.6, extensions, cluster, fade)."""
    tickers: list[str] = Field(default_factory=list)
    asset_class: str = "india"
    exchange: str | None = None
    timeframe: str = "1d"
    lookback_bars: int = Field(default=250, ge=60, le=650)
    fib_lookback: int = Field(default=100, ge=30, le=300)
    secondary_lookback: int = Field(default=40, ge=20, le=120)
    zone_tol_atr: float = Field(default=0.55, ge=0.2, le=2.0)
    min_rr: float = Field(default=1.4, ge=0.8, le=5.0)
    strategies: list[str] = Field(default_factory=list)
    start_date: str | None = None
    end_date: str | None = None


class ProTradeBbMeanReversionRequest(BaseModel):
    """BB Mean Reversion — Bollinger %B stretch confirmed by regime filter, RSI,
    candlestick reversal, volume climax, and independent Support/Resistance confluence."""
    tickers: list[str] = Field(default_factory=list)
    asset_class: str = "india"
    exchange: str | None = None
    timeframes: list[str] = Field(default_factory=lambda: ["1d"])
    lookback_bars: int = Field(default=250, ge=60, le=650)
    bb_period: int = Field(default=20, ge=10, le=50)
    bb_std: float = Field(default=2.0, ge=1.0, le=3.5)
    er_hard_block: float = Field(default=0.65, ge=0.3, le=0.9)
    er_soft_ceiling: float = Field(default=0.42, ge=0.2, le=0.7)
    squeeze_pctile_floor: float = Field(default=15.0, ge=0.0, le=40.0)
    rsi_overbought: float = Field(default=65.0, ge=55.0, le=85.0)
    rsi_oversold: float = Field(default=35.0, ge=15.0, le=45.0)
    zone_tolerance_pct: float = Field(default=1.2, ge=0.1, le=5.0)
    min_rr: float = Field(default=1.3, ge=0.5, le=5.0)
    extra_checks: list[str] = Field(default_factory=list)


class ProTradeTrafficLightRequest(BaseModel):
    """Traffic Light Indicator — SMA20 (Green) / SMA50 (Yellow) / SMA200 (Red).

    BUY: Red>Yellow>Green and close below all three → buy next morning.
    SELL: Green>Yellow>Red and close above all three → sell next morning.
    Optional further_analysis includes ``mtf_trend_strength``.
    """
    tickers: list[str] = Field(default_factory=list)
    asset_class: str = "india"
    exchange: str | None = None
    timeframe: str = "1d"
    lookback_bars: int = Field(default=400, ge=220, le=1200)
    further_analysis: list[str] = Field(default_factory=list)
    rr_min: float = Field(default=1.5, ge=0.5, le=5.0)
    sl_atr_mult: float = Field(default=1.5, ge=0.5, le=4.0)
    tp_atr_mult: float = Field(default=3.0, ge=1.0, le=8.0)
    take_confidence_threshold: float = Field(default=55.0, ge=30.0, le=90.0)


class ProTradeBuyLowSellHighRequest(BaseModel):
    """Buy Low Sell High — 25-day low GTT ladder.

    Buy GTT at 25DL+5%; update on new lows before fill; next add when price is
    10% below average; sell all at average+5%; no stop-loss. All asset classes.
    """
    tickers: list[str] = Field(default_factory=list)
    asset_class: str = "india"
    exchange: str | None = None
    timeframe: str = "1d"
    lookback_bars: int = Field(default=320, ge=60, le=1200)
    low_lookback: int = Field(default=25, ge=10, le=60)
    buy_buffer_pct: float = Field(default=5.0, ge=1.0, le=15.0)
    sell_target_pct: float = Field(default=5.0, ge=1.0, le=20.0)
    add_on_drop_pct: float = Field(default=10.0, ge=3.0, le=30.0)


class ProTradeRlbBreakoutRequest(BaseModel):
    """RLB — Rocket Launcher Breakout (7 confirmations).

    Prior-high break, green candle, EMA20, EMA50, RSI>60 (prefer ≥65),
    day gain >2%, volume > 5-day SMA. Source: https://www.youtube.com/watch?v=pBQ1oVDVe3M
    """
    tickers: list[str] = Field(default_factory=list)
    asset_class: str = "india"
    exchange: str | None = None
    timeframe: str = "1d"
    lookback_bars: int = Field(default=250, ge=60, le=1200)
    rsi_min: float = Field(default=60.0, ge=50.0, le=80.0)
    rsi_prefer: float = Field(default=65.0, ge=55.0, le=85.0)
    min_day_chg_pct: float = Field(default=2.0, ge=0.5, le=10.0)
    volume_sma_period: int = Field(default=5, ge=3, le=20)
    require_all_seven: bool = True


class ProTradeThreeInOneRequest(BaseModel):
    """3-in-1 Trade System — DMA 50/100/200 + CAR rising + volume/turnover.

    Mahesh Kaushik / FIRE in India style: buy when above all DMAs, within max %
    of 200 DMA, CAR rising N days; exit +6.28% of average; SIP after −20% with
    CAR re-trigger. Ranked closest-to-200-DMA first.
    """
    tickers: list[str] = Field(default_factory=list)
    asset_class: str = "india"
    exchange: str | None = None
    timeframe: str = "1d"
    lookback_bars: int = Field(default=400, ge=220, le=1200)
    car_rising_days: int = Field(default=10, ge=5, le=20)
    max_pct_above_200: float = Field(default=10.0, ge=2.0, le=25.0)
    require_volume_breakout: bool = False
    sip_gap_days: int = Field(default=30, ge=7, le=60)
    max_holdings: int = Field(default=15, ge=5, le=40)


class ProTradeSimpleEffectiveRequest(BaseModel):
    """Simple Effective — MA band close-outside + MACD hist-zone cross + trigger break.

    SL at opposite band edge; TP at 1:1 or 1:1.5 RRR. Avoid Open=Low sell traps.
    Multi-asset / multi-timeframe.
    """
    tickers: list[str] = Field(default_factory=list)
    asset_class: str = "india"
    exchange: str | None = None
    timeframes: list[str] = Field(default_factory=lambda: ["15m"])
    lookback_bars: int = Field(default=300, ge=80, le=1200)
    ma_fast: int = Field(default=9, ge=3, le=50)
    ma_slow: int = Field(default=21, ge=5, le=100)
    use_ema: bool = True
    rr_multiple: float = Field(default=1.5, ge=1.0, le=3.0)


class ProTradeBbRsiVolRequest(BaseModel):
    """BB-RSI-VOL — Lower BB + RSI≤35 + low vol → Buy; Upper BB + RSI≥70 + high vol → Sell.

    Filtered by S/R + 9/50 EMA. All asset classes / timeframes. Returns conf% · SL% · TP%.
    """
    tickers: list[str] = Field(default_factory=list)
    asset_class: str = "india"
    exchange: str | None = None
    timeframes: list[str] = Field(default_factory=lambda: ["15m"])
    lookback_bars: int = Field(default=300, ge=80, le=1200)
    bb_period: int = Field(default=20, ge=10, le=50)
    bb_std: float = Field(default=2.0, ge=1.0, le=3.5)
    rsi_buy: float = Field(default=35.0, ge=20.0, le=45.0)
    rsi_sell: float = Field(default=70.0, ge=60.0, le=85.0)
    min_rr: float = Field(default=1.2, ge=0.8, le=4.0)
    require_sr: bool = True
    take_confidence_threshold: float = Field(default=55.0, ge=40.0, le=85.0)


class ProTradeBtstRequest(BaseModel):
    """Buy Today Sell Tomorrow / Sell Today Buy Tomorrow — closing-strength (CLV) signature confirmed by
    trend, volume, relative strength vs Nifty, VWAP, RSI chase-risk guard, options OI buildup, late-session
    fade check, and this ticker's own historical follow-through rate. India cash/F&O only."""
    tickers: list[str] = Field(default_factory=list)
    asset_class: str = "india"
    exchange: str | None = None
    lookback_bars: int = Field(default=250, ge=60, le=650)
    min_clv: float = Field(default=0.65, ge=0.5, le=0.95)
    min_volume_zscore: float = Field(default=0.8, ge=-1.0, le=3.0)
    climax_volume_zscore: float = Field(default=3.5, ge=1.5, le=6.0)
    min_relative_strength_pct: float = Field(default=0.3, ge=0.0, le=3.0)
    sl_atr_mult: float = Field(default=0.7, ge=0.2, le=2.0)
    tp_atr_mult: float = Field(default=1.4, ge=0.5, le=4.0)
    min_rr: float = Field(default=1.3, ge=0.5, le=5.0)
    historical_lookback_days: int = Field(default=90, ge=20, le=250)
    check_oi_buildup: bool = True
    further_analysis: list[str] = Field(default_factory=list)


class ProTradeTickerChartRequest(BaseModel):
    """Pro Trade — Ticker Chart with support / resistance (daily range or same-day intraday)."""
    ticker: str
    asset_class: str = "india"
    mode: str = "daily"  # daily | intraday
    from_date: str | None = None
    to_date: str | None = None
    session_date: str | None = None
    interval: str = "1d"  # 1d or 1m/5m/15m/30m/1h
    exchange: str | None = None
    indicators: list[str] = Field(
        default_factory=lambda: ["volume", "ema_9", "ema_50"],
        description="Selected overlays: rsi, macd, supertrend, vwap, volume, bollinger, fibonacci, ema_5/9/20/50/200",
    )


class PredictionPatternAnalogueRequest(BaseModel):
    """Find historical windows shaped like the latest N bars (or a chart screenshot), then measure before/after."""
    tickers: list[str] = Field(default_factory=list)
    asset_class: str = "india"
    exchange: str | None = None
    timeframe: str = "15m"
    pattern_bars: int = Field(default=20, ge=5, le=120)
    forward_bars: int = Field(default=5, ge=1, le=60)
    before_bars: int = Field(default=5, ge=0, le=60)
    search_lookback_bars: int = Field(default=500, ge=80, le=2500)
    search_from_date: str | None = None
    search_to_date: str | None = None
    top_n: int = Field(default=10, ge=1, le=50)
    min_similarity: float = Field(default=0.82, ge=0.5, le=0.99)
    chart_image_base64: str | None = Field(
        default=None,
        description="Optional chart screenshot (raw base64 or data URL). Digitized into the template shape.",
    )


class PredictionAstroFinanceRequest(BaseModel):
    """Financial astrology + numerology desks (lunar, Bhadra, Mercury Rx, Nakshatra, Gann, eclipse…).

    Pass ``strategies`` to run several desks in one call (preferred). Legacy ``strategy``
    still works for a single desk; if both empty, all desks run.
    """
    strategy: str | None = Field(
        default=None,
        description=(
            "Legacy single desk: lunar_cycle | amavasya_sr | bhadra_timing | transit_gaps | "
            "trading_calendar | mercury_retrograde | nakshatra_timing | tithi_panchang | "
            "gann_numerology | eclipse_nodes"
        ),
    )
    strategies: list[str] = Field(
        default_factory=list,
        description="One or more desks to run together (same ids as strategy).",
    )
    tickers: list[str] = Field(default_factory=list)
    asset_class: str = "india"
    exchange: str | None = None
    lookback_days: int = Field(default=730, ge=120, le=2500)
    forward_days: int = Field(default=3, ge=1, le=10)
    event_window_days: int = Field(default=1, ge=0, le=3)
    strong_moon_signs: list[str] = Field(default_factory=list)
    timezone_name: str | None = None


class YoutubeAnalysisScanRequest(BaseModel):
    """Fetch listed YouTube videos and Gemini transcripts."""
    youtube_api_key: str | None = None  # optional if saved for this user
    video_urls: list[str] = Field(default_factory=list)  # URLs or 11-char IDs
    channel_ids: list[str] = Field(default_factory=list)  # legacy channel mode
    from_date: str | None = None  # optional; unused for video_urls mode
    to_date: str | None = None
    max_per_channel: int = Field(default=25, ge=1, le=50)
    fetch_transcripts: bool = True
    save_api_key: bool = True


class YoutubeAnalysisAiViewRequest(BaseModel):
    """Run market-impact AI summary over a prior scan (or raw context)."""
    ai_context: str | None = None
    scan: dict[str, Any] | None = None
    question: str | None = None
    max_tokens: int = Field(default=4000, ge=256, le=8000)


class SaveYoutubeAiViewRequest(BaseModel):
    """Persist a generated AI View for future reference."""
    name: str
    report: str
    verdict: str | None = None
    provider: str | None = None
    model: str | None = None
    ai_context: str = ""
    video_urls: list[str] = Field(default_factory=list)
    from_date: str | None = None
    to_date: str | None = None
    snapshot_note: str | None = None


class UpdateYoutubeAiViewRequest(BaseModel):
    """Rename and/or edit the report text of a saved AI View."""
    name: str | None = None
    report: str | None = None


class WorkflowEvaluateRequest(BaseModel):
    """Run all desks in a Workflow playbook for index or stock mode."""
    market: Literal["india", "us", "crypto", "commodities"] = "india"
    mode: Literal["index", "stock"] = "index"
    tickers: list[str] = Field(default_factory=list)
