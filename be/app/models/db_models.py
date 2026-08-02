from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, Integer, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    mobile: Mapped[str] = mapped_column(String(15), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    reset_token: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    reset_token_expires: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


class PaperAccount(Base):
    __tablename__ = "paper_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(128), default="Default")
    cash_balance: Mapped[float] = mapped_column(Float, default=1_000_000.0)
    initial_capital: Mapped[float] = mapped_column(Float, default=1_000_000.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PaperPosition(Base):
    __tablename__ = "paper_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer, index=True)
    ticker: Mapped[str] = mapped_column(String(32))
    quantity: Mapped[int] = mapped_column(Integer)
    avg_price: Mapped[float] = mapped_column(Float)
    side: Mapped[str] = mapped_column(String(8), default="long")
    sl_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    tp_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    strategy: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    asset_class: Mapped[str] = mapped_column(String(16), default="india")


class PaperOrder(Base):
    __tablename__ = "paper_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer, index=True)
    ticker: Mapped[str] = mapped_column(String(32))
    side: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float)
    order_type: Mapped[str] = mapped_column(String(16), default="market")
    status: Mapped[str] = mapped_column(String(16), default="filled")
    strategy: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    sl_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    tp_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    trigger_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    filled_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    asset_class: Mapped[str] = mapped_column(String(16), default="india")


class AlertMonitor(Base):
    __tablename__ = "alert_monitors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(128))
    market: Mapped[str] = mapped_column(String(64))
    ticker: Mapped[str] = mapped_column(String(32))
    timeframe: Mapped[str] = mapped_column(String(8))
    strategy_name: Mapped[str] = mapped_column(String(256))
    indicators_json: Mapped[str] = mapped_column(Text)
    entry_rules_json: Mapped[str] = mapped_column(Text)
    exit_rules_json: Mapped[str] = mapped_column(Text)
    entry_mode: Mapped[str] = mapped_column(String(8), default="AND")
    poll_minutes: Mapped[int] = mapped_column(Integer, default=15)
    notify_telegram: Mapped[bool] = mapped_column(default=True)
    notify_email: Mapped[bool] = mapped_column(default=False)
    enabled: Mapped[bool] = mapped_column(default=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_signal: Mapped[str] = mapped_column(String(16), default="INACTIVE")
    last_alert_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AlertSchedule(Base):
    __tablename__ = "alert_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(128))
    market: Mapped[str] = mapped_column(String(16), default="india")  # india|us|crypto
    tickers_json: Mapped[str] = mapped_column(Text, default="[]")
    timeframes_json: Mapped[str] = mapped_column(Text, default="[]")
    strategies_json: Mapped[str] = mapped_column(Text, default="[]")
    schedule_mode: Mapped[str] = mapped_column(String(16), default="interval")  # interval|daily_at
    poll_minutes: Mapped[int] = mapped_column(Integer, default=15)
    daily_time: Mapped[str | None] = mapped_column(String(8), nullable=True)  # HH:MM
    notify_telegram: Mapped[bool] = mapped_column(default=True)
    notify_email: Mapped[bool] = mapped_column(default=False)
    enabled: Mapped[bool] = mapped_column(default=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AlertScheduleHit(Base):
    __tablename__ = "alert_schedule_hits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    schedule_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    schedule_name: Mapped[str] = mapped_column(String(128))
    strategy_name: Mapped[str] = mapped_column(String(256))
    ticker: Mapped[str] = mapped_column(String(32))
    timeframe: Mapped[str] = mapped_column(String(8))
    market: Mapped[str] = mapped_column(String(16))
    verdict: Mapped[str] = mapped_column(String(32), default="BUY")
    reasons_json: Mapped[str] = mapped_column(Text, default="[]")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    bar_asof: Mapped[str] = mapped_column(String(64), default="")
    dedupe_key: Mapped[str] = mapped_column(String(256), index=True, default="")
    notified_telegram: Mapped[bool] = mapped_column(default=False)
    notified_email: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AlertNotifyConfig(Base):
    __tablename__ = "alert_notify_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    smtp_host: Mapped[str | None] = mapped_column(String(128), nullable=True)
    smtp_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    smtp_user: Mapped[str | None] = mapped_column(String(128), nullable=True)
    smtp_password: Mapped[str | None] = mapped_column(String(256), nullable=True)
    smtp_from: Mapped[str | None] = mapped_column(String(256), nullable=True)
    email_to: Mapped[str | None] = mapped_column(Text, nullable=True)  # comma-separated
    telegram_bot_token: Mapped[str | None] = mapped_column(String(256), nullable=True)
    telegram_chat_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Watchlist(Base):
    __tablename__ = "watchlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    market_type: Mapped[str] = mapped_column(String(16), default="india")
    name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    watchlist_id: Mapped[int] = mapped_column(Integer, index=True)
    ticker: Mapped[str] = mapped_column(String(32))
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    added_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SavedBacktestReport(Base):
    __tablename__ = "saved_backtest_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    asset_class: Mapped[str] = mapped_column(String(16))
    tickers: Mapped[str] = mapped_column(Text)  # comma-separated
    timeframes: Mapped[str] = mapped_column(Text)  # comma-separated
    payload_json: Mapped[str] = mapped_column(Text)  # full leaderboard result, JSON-encoded
    # Which leaderboard service saved this row — "strategy_leaderboard" (Strategy
    # Lab's "Strategy Leaderboard" tab, payload rows shaped total_signals/
    # overall_win_rate_pct) vs "backtester_leaderboard" (Multi-Combo/Screener/
    # Builder, payload rows shaped num_trades/win_rate_pct/total_return_pct).
    # Both services share this one table but their payload shapes are NOT
    # interchangeable — without this filter a report saved from one shows up
    # (and renders blank Win Rate/Signals) in the other's saved-reports list.
    source: Mapped[str] = mapped_column(String(32), default="strategy_leaderboard", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BackgroundJob(Base):
    """Durable record of a background leaderboard/backtest run — the
    in-memory job store (strategy_leaderboard_jobs.py) is fast for live
    progress polling, but a job that's still "running" only in memory is
    silently lost if the backend process restarts mid-run (deploy, crash,
    manual restart). This table is the source of truth for status/result
    linkage and stores the full original request so an orphaned "running"
    job found at startup (impossible to genuinely still be running, since
    the process just started fresh) can be transparently re-launched from
    scratch rather than vanishing with no report and no explanation."""
    __tablename__ = "background_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # uuid4 hex, shared with the in-memory job id
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    source: Mapped[str] = mapped_column(String(32), index=True)  # "backtester_leaderboard" | "strategy_leaderboard"
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)  # running | done | error
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_json: Mapped[str] = mapped_column(Text)  # full original request payload, for resume-on-restart
    meta_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TradeCandidate(Base):
    """A saved setup: one ticker + one timeframe + one or more strategies,
    checked live for BUY/SELL triggers on the Trade Candidate hub."""
    __tablename__ = "trade_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(128))
    asset_class: Mapped[str] = mapped_column(String(16), default="india")  # india|us|crypto|commodity
    ticker: Mapped[str] = mapped_column(String(32))
    timeframe: Mapped[str] = mapped_column(String(8))
    strategies_json: Mapped[str] = mapped_column(Text, default="[]")
    enabled: Mapped[bool] = mapped_column(default=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CustomStrategy(Base):
    """A user-built Strategy Lab strategy — indicator + entry/exit rule set,
    hand-built in the Builder or generated via the AI Strategy Creator."""
    __tablename__ = "custom_strategies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(128))
    market: Mapped[str] = mapped_column(String(64))
    asset_class: Mapped[str] = mapped_column(String(16), default="india")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    timeframe: Mapped[str] = mapped_column(String(8), default="1d")
    indicators_json: Mapped[str] = mapped_column(Text, default="[]")
    entry_rules_json: Mapped[str] = mapped_column(Text, default="[]")
    exit_rules_json: Mapped[str] = mapped_column(Text, default="[]")
    entry_mode: Mapped[str] = mapped_column(String(8), default="AND")
    exit_mode: Mapped[str] = mapped_column(String(8), default="AND")
    direction_mode: Mapped[str] = mapped_column(String(16), default="long_only")
    position_sizing: Mapped[str] = mapped_column(String(16), default="pct_of_capital")
    capital_allocation_pct: Mapped[float] = mapped_column(Float, default=95.0)
    risk_pct: Mapped[float] = mapped_column(Float, default=1.0)
    sl_pct: Mapped[float] = mapped_column(Float, default=0.0)
    tp_pct: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(8), default="manual")  # manual|ai
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TradeCandidateHit(Base):
    """A logged BUY/SELL trigger from checking a TradeCandidate."""
    __tablename__ = "trade_candidate_hits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    candidate_name: Mapped[str] = mapped_column(String(128))
    ticker: Mapped[str] = mapped_column(String(32))
    timeframe: Mapped[str] = mapped_column(String(8))
    asset_class: Mapped[str] = mapped_column(String(16))
    strategy_id: Mapped[str] = mapped_column(String(128))
    strategy_label: Mapped[str] = mapped_column(String(256))
    verdict: Mapped[str] = mapped_column(String(16), default="BUY")
    confidence_pct: Mapped[float] = mapped_column(Float, default=0.0)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    rationale: Mapped[str] = mapped_column(Text, default="")
    bar_asof: Mapped[str] = mapped_column(String(64), default="")
    dedupe_key: Mapped[str] = mapped_column(String(256), index=True, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
