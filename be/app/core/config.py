from pathlib import Path
from urllib.parse import quote_plus

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]
_DEFAULT_SQLITE_PATH = (BASE_DIR / "data" / "paper_trading.db").as_posix()
_DEFAULT_SQLITE_URL = f"sqlite+aiosqlite:///{_DEFAULT_SQLITE_PATH}"


class Settings(BaseSettings):
    """App settings.

    Database mode (primary SQLAlchemy DB — paper trading / users / jobs / etc.):
      DB_MODE=sqlite   (default) → local file be/data/paper_trading.db
      DB_MODE=mysql    → MySQL via MYSQL_* vars (or DATABASE_URL if set)

    If DATABASE_URL is set, it always wins (full SQLAlchemy URL override).
    """

    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Indian Stock Paper Trading API"
    debug: bool = True

    # --- Database ---
    # sqlite (default) | mysql
    db_mode: str = Field(default="sqlite", description="Database backend: sqlite or mysql")
    # Optional full URL override (e.g. sqlite+aiosqlite:///... or mysql+aiomysql://...)
    database_url: str | None = Field(default=None, description="Optional SQLAlchemy URL; overrides DB_MODE when set")

    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_database: str = "trading_system"
    mysql_charset: str = "utf8mb4"

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    default_data_provider: str = "yfinance"
    default_initial_capital: float = 1_000_000.0
    default_costs_pct: float = 0.0008
    benchmark_ticker: str = "^NSEI"
    jwt_secret_key: str = "change-me-in-production-use-a-long-random-secret"
    jwt_algorithm: str = "HS256"
    jwt_expire_days: int = 30
    password_reset_expire_hours: int = 24

    def _build_mysql_url(self) -> str:
        user = quote_plus(self.mysql_user or "")
        password = quote_plus(self.mysql_password or "")
        host = self.mysql_host or "127.0.0.1"
        port = int(self.mysql_port or 3306)
        db = self.mysql_database or "trading_system"
        charset = self.mysql_charset or "utf8mb4"
        return f"mysql+aiomysql://{user}:{password}@{host}:{port}/{db}?charset={charset}"

    @property
    def sqlalchemy_url(self) -> str:
        """Resolved async SQLAlchemy URL (honours DATABASE_URL, else DB_MODE)."""
        explicit = (self.database_url or "").strip()
        if explicit:
            return explicit

        mode = (self.db_mode or "sqlite").strip().lower()
        if mode in ("mysql", "my_sql", "mariadb"):
            return self._build_mysql_url()
        return _DEFAULT_SQLITE_URL

    @property
    def is_sqlite(self) -> bool:
        return self.sqlalchemy_url.startswith("sqlite")

    @property
    def is_mysql(self) -> bool:
        url = self.sqlalchemy_url
        return url.startswith("mysql") or url.startswith("mariadb")


settings = Settings()
