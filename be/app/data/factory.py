from app.data.base import DataProvider
from app.data.groww_provider import GrowwProvider
from app.data.indmoney_provider import IndMoneyProvider
from app.data.provider_ctx import normalize_provider
from app.data.yfinance_provider import YFinanceProvider
from app.services.settings_service import SettingsService


class DataProviderFactory:
    @staticmethod
    async def get_provider(settings: SettingsService) -> DataProvider:
        provider_name = normalize_provider(await settings.get_data_provider())
        exchange = await settings.get_groww_exchange()

        if provider_name == "indmoney":
            token = await settings.get_indmoney_access_token() or ""
            return IndMoneyProvider(access_token=token, exchange=exchange, fallback_yfinance=True)

        if provider_name == "groww":
            token = await settings.get_groww_access_token() or ""
            return GrowwProvider(api_token=token, exchange=exchange, fallback_yfinance=True)

        return YFinanceProvider()
