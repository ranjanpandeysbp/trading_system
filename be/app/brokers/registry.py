"""Broker registry — add new brokers here to extend Live Trade."""

from __future__ import annotations

from app.brokers.coindcx import CoinDCXBrokerAdapter
from app.brokers.groww import GrowwBrokerAdapter
from app.brokers.indmoney import IndMoneyBrokerAdapter
from app.services.settings_service import SettingsService

# Display order in Live Trade / Manage
BROKER_CATALOG: list[dict[str, str]] = [
    {
        "id": "indmoney",
        "label": "INDMoney",
        "description": "India equities via INDstocks / INDMoney (TOTP).",
        "asset_focus": "india",
    },
    {
        "id": "groww",
        "label": "Groww",
        "description": "India equities via Groww (API key + TOTP).",
        "asset_focus": "india",
    },
    {
        "id": "coindcx",
        "label": "CoinDCX",
        "description": "Crypto spot via CoinDCX (API key + secret).",
        "asset_focus": "crypto",
    },
]


def get_broker_adapter(broker_id: str, settings: SettingsService):
    key = (broker_id or "").strip().lower()
    if key == "groww":
        return GrowwBrokerAdapter(settings)
    if key in ("indmoney", "indstocks"):
        return IndMoneyBrokerAdapter(settings)
    if key == "coindcx":
        return CoinDCXBrokerAdapter(settings)
    raise ValueError(f"Unknown broker: {broker_id}. Supported: indmoney, groww, coindcx")


def list_broker_catalog() -> list[dict[str, str]]:
    return list(BROKER_CATALOG)
