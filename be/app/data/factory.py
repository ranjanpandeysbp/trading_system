from app.data.base import DataProvider
from app.data.groww_provider import GrowwProvider
from app.data.yfinance_provider import YFinanceProvider
from app.services.settings_service import SettingsService


class DataProviderFactory:
    @staticmethod
    async def get_provider(settings: SettingsService) -> DataProvider:
        provider_name = await settings.get_data_provider()
        exchange = await settings.get_groww_exchange()
        token = await settings.get_groww_token() or ""

        if provider_name == "groww":
            # Groww provider works with or without token (public charting fallback)
            return GrowwProvider(api_token=token, exchange=exchange, fallback_yfinance=True)
        return YFinanceProvider()
