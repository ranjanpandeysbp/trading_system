from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.db_models import AppSetting


class SettingsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get(self, key: str, default: str) -> str:
        result = await self.db.execute(select(AppSetting).where(AppSetting.key == key))
        row = result.scalar_one_or_none()
        return row.value if row else default

    async def _set(self, key: str, value: str) -> None:
        result = await self.db.execute(select(AppSetting).where(AppSetting.key == key))
        row = result.scalar_one_or_none()
        if row:
            row.value = value
        else:
            self.db.add(AppSetting(key=key, value=value))
        await self.db.commit()

    async def get_data_provider(self) -> str:
        return await self._get("data_provider", settings.default_data_provider)

    async def get_groww_token(self) -> str | None:
        token = await self._get("groww_api_token", "")
        return token or None

    async def get_groww_exchange(self) -> str:
        return await self._get("groww_exchange", "NSE")

    async def get_initial_capital(self) -> float:
        return float(await self._get("initial_capital", str(settings.default_initial_capital)))

    async def get_costs_pct(self) -> float:
        return float(await self._get("costs_pct", str(settings.default_costs_pct)))

    async def get_benchmark_ticker(self) -> str:
        return await self._get("benchmark_ticker", settings.benchmark_ticker)

    async def get_all(self) -> dict:
        token = await self.get_groww_token()
        return {
            "data_provider": await self.get_data_provider(),
            "groww_token_set": bool(token),
            "groww_exchange": await self.get_groww_exchange(),
            "initial_capital": await self.get_initial_capital(),
            "costs_pct": await self.get_costs_pct(),
            "benchmark_ticker": await self.get_benchmark_ticker(),
        }

    async def update(self, payload: dict) -> dict:
        if payload.get("data_provider") is not None:
            await self._set("data_provider", payload["data_provider"])
        if payload.get("groww_api_token") is not None:
            await self._set("groww_api_token", payload["groww_api_token"])
        if payload.get("groww_exchange") is not None:
            await self._set("groww_exchange", payload["groww_exchange"])
        if payload.get("initial_capital") is not None:
            await self._set("initial_capital", str(payload["initial_capital"]))
        if payload.get("costs_pct") is not None:
            await self._set("costs_pct", str(payload["costs_pct"]))
        if payload.get("benchmark_ticker") is not None:
            await self._set("benchmark_ticker", payload["benchmark_ticker"])
        return await self.get_all()
