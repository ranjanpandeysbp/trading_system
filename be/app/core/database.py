from collections.abc import AsyncGenerator
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    pass


def _build_engine():
    url = settings.sqlalchemy_url
    kwargs: dict = {"echo": settings.debug}
    if settings.is_mysql:
        # Survive dropped idle connections (MySQL wait_timeout) and recycle pools.
        kwargs.update(pool_pre_ping=True, pool_recycle=28000, pool_size=5, max_overflow=10)
    return create_async_engine(url, **kwargs)


engine = _build_engine()
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


def _sqlite_file_path(url: str) -> Path | None:
    """Extract filesystem path from a sqlite+aiosqlite URL, else None."""
    if not url.startswith("sqlite"):
        return None
    # sqlite+aiosqlite:///C:/path/to.db  or  sqlite+aiosqlite:////absolute/path.db
    raw = url.split("///", 1)[-1] if "///" in url else urlparse(url).path
    if not raw:
        return None
    return Path(raw)


async def init_db() -> None:
    if settings.is_sqlite:
        db_path = _sqlite_file_path(settings.sqlalchemy_url)
        if db_path is not None:
            db_path.parent.mkdir(parents=True, exist_ok=True)

    from app.models import db_models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate_schema)


def _migrate_schema(conn) -> None:
    """Additive schema patches for existing DBs (create_all alone won't ADD COLUMN).

    Uses SQLAlchemy inspector so column checks work on both SQLite and MySQL.
    Index DDL is dialect-aware where syntax differs.
    """
    import sqlalchemy as sa

    dialect = conn.dialect.name  # "sqlite" | "mysql" | ...
    insp = sa.inspect(conn)

    def add_column(table: str, col_name: str, col_type: str) -> None:
        cols = {c["name"] for c in insp.get_columns(table)}
        if col_name in cols:
            return
        # MySQL prefers DATETIME / DOUBLE / TEXT; SQLite accepts FLOAT/DATETIME/TEXT.
        mysql_type = col_type
        if dialect == "mysql":
            if col_type.upper() == "FLOAT":
                mysql_type = "DOUBLE"
            elif col_type.upper() == "DATETIME":
                mysql_type = "DATETIME"
            elif col_type.upper() == "TEXT":
                mysql_type = "TEXT"
        conn.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN {col_name} {mysql_type}"))

    tables = set(insp.get_table_names())

    if "paper_accounts" in tables:
        add_column("paper_accounts", "user_id", "INTEGER")

    if "paper_orders" in tables:
        for col_name, col_type in (
            ("limit_price", "FLOAT"),
            ("trigger_price", "FLOAT"),
            ("filled_price", "FLOAT"),
            ("filled_at", "DATETIME"),
            ("cancelled_at", "DATETIME"),
            ("notes", "TEXT"),
            ("asset_class", "TEXT"),
            ("realized_pnl", "FLOAT"),
        ):
            add_column("paper_orders", col_name, col_type)

    if "paper_positions" in tables:
        add_column("paper_positions", "notes", "TEXT")
        add_column("paper_positions", "asset_class", "TEXT")

    if "watchlist_items" in tables:
        add_column("watchlist_items", "notes", "TEXT")

    if "saved_backtest_reports" in tables:
        add_column("saved_backtest_reports", "source", "TEXT")
        add_column("saved_backtest_reports", "updated_at", "DATETIME")

    if "trade_suggestions" in tables:
        add_column("trade_suggestions", "setup_id", "INTEGER")

    if "auto_trade_setups" in tables:
        add_column("auto_trade_setups", "direction", "TEXT")

    if "etf_shop_configs" in tables:
        cols = {c["name"] for c in insp.get_columns("etf_shop_configs")}
        if "averaging_trigger_pct" not in cols:
            add_column("etf_shop_configs", "averaging_trigger_pct", "FLOAT")
        if "asset_class" not in cols:
            if dialect == "mysql":
                conn.execute(
                    sa.text(
                        "ALTER TABLE etf_shop_configs ADD COLUMN asset_class VARCHAR(16) DEFAULT 'india'"
                    )
                )
            else:
                conn.execute(
                    sa.text("ALTER TABLE etf_shop_configs ADD COLUMN asset_class TEXT DEFAULT 'india'")
                )
            # Old UNIQUE on user_id alone must be dropped before multi-asset shops.
            idx_names = {ix["name"] for ix in insp.get_indexes("etf_shop_configs")}
            if "ix_etf_shop_configs_user_id" in idx_names:
                if dialect == "mysql":
                    conn.execute(sa.text("DROP INDEX ix_etf_shop_configs_user_id ON etf_shop_configs"))
                else:
                    conn.execute(sa.text("DROP INDEX ix_etf_shop_configs_user_id"))
            uq_name = "uq_etf_shop_configs_user_asset"
            idx_names = {ix["name"] for ix in insp.get_indexes("etf_shop_configs")}
            if uq_name not in idx_names:
                if dialect == "mysql":
                    conn.execute(
                        sa.text(
                            f"CREATE UNIQUE INDEX {uq_name} ON etf_shop_configs (user_id, asset_class)"
                        )
                    )
                else:
                    conn.execute(
                        sa.text(
                            f"CREATE UNIQUE INDEX IF NOT EXISTS {uq_name} "
                            "ON etf_shop_configs (user_id, asset_class)"
                        )
                    )

    if "etf_shop_lots" in tables:
        add_column("etf_shop_lots", "asset_class", "TEXT")
