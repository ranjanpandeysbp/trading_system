from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(settings.database_url, echo=settings.debug)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    from pathlib import Path

    data_dir = settings.database_url.split("///")[-1]
    Path(data_dir).parent.mkdir(parents=True, exist_ok=True)

    from app.models import db_models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate_schema)


def _migrate_schema(conn) -> None:
    import sqlalchemy as sa

    insp = sa.inspect(conn)
    if "paper_accounts" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("paper_accounts")}
        if "user_id" not in cols:
            conn.execute(sa.text("ALTER TABLE paper_accounts ADD COLUMN user_id INTEGER"))

    if "paper_orders" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("paper_orders")}
        for col_name, col_type in (
            ("limit_price", "FLOAT"),
            ("trigger_price", "FLOAT"),
            ("filled_price", "FLOAT"),
            ("filled_at", "DATETIME"),
            ("cancelled_at", "DATETIME"),
            ("notes", "TEXT"),
        ):
            if col_name not in cols:
                conn.execute(sa.text(f"ALTER TABLE paper_orders ADD COLUMN {col_name} {col_type}"))
        if "asset_class" not in cols:
            conn.execute(sa.text("ALTER TABLE paper_orders ADD COLUMN asset_class TEXT DEFAULT 'india'"))

    if "paper_positions" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("paper_positions")}
        if "notes" not in cols:
            conn.execute(sa.text("ALTER TABLE paper_positions ADD COLUMN notes TEXT"))
        if "asset_class" not in cols:
            conn.execute(sa.text("ALTER TABLE paper_positions ADD COLUMN asset_class TEXT DEFAULT 'india'"))

    if "watchlist_items" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("watchlist_items")}
        if "notes" not in cols:
            conn.execute(sa.text("ALTER TABLE watchlist_items ADD COLUMN notes TEXT"))
