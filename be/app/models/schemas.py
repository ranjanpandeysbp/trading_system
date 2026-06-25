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


class SettingsUpdate(BaseModel):
    data_provider: str | None = None
    groww_api_token: str | None = None
    groww_exchange: str | None = None
    initial_capital: float | None = None
    costs_pct: float | None = None
    benchmark_ticker: str | None = None


class PlaceOrderRequest(BaseModel):
    ticker: str
    side: Literal["buy", "sell"]
    quantity: int = Field(..., gt=0)
    price: float | None = None
    strategy: str | None = None
    sl_pct: float | None = None
    tp_pct: float | None = None


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


class MarketPulseIndexRequest(BaseModel):
    index_name: str = "NIFTY 50"


class MarketPulseRotationRequest(BaseModel):
    index_name: str = "NIFTY 50"
    tf_key: str = "1d"
    lookback_bars: int = Field(default=5, ge=1, le=500)


class MarketPulseMtfRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=1)
    timeframes: list[str] | None = None


class MarketPulseSentimentRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=1)
    timeframes: list[str] = Field(default_factory=lambda: ["1d", "4h"])
    lookback_days: int = Field(default=120, ge=50, le=500)


class MarketPulseTickerInvestigationRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=1, max_length=15)


class TradingHubScanRequest(BaseModel):
    section_id: str
    tickers: list[str] = Field(..., min_length=1, max_length=20)
    config: dict[str, Any] | None = None
    run_backtest: bool = False


class MarketPulseCommodityRequest(BaseModel):
    timeframes: list[str] | None = None


class MarketPulseHeatmapRequest(BaseModel):
    timeframe: str = "1d"
    mode: str = "sectoral"


class MarketPulsePagination(BaseModel):
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=10, ge=1, le=50)
