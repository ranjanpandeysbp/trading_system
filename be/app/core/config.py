from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    app_name: str = "Indian Stock Paper Trading API"
    debug: bool = True
    database_url: str = f"sqlite+aiosqlite:///{BASE_DIR / 'data' / 'paper_trading.db'}"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    default_data_provider: str = "yfinance"
    default_initial_capital: float = 1_000_000.0
    default_costs_pct: float = 0.0008
    benchmark_ticker: str = "^NSEI"
    jwt_secret_key: str = "change-me-in-production-use-a-long-random-secret"
    jwt_algorithm: str = "HS256"
    jwt_expire_days: int = 30
    password_reset_expire_hours: int = 24


settings = Settings()
