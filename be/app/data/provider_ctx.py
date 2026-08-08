"""Active market-data provider context (IndMoney / Groww / yfinance)."""

from __future__ import annotations

import contextvars

_data_provider: contextvars.ContextVar[str] = contextvars.ContextVar("data_provider", default="yfinance")
_indmoney_token: contextvars.ContextVar[str] = contextvars.ContextVar("indmoney_token", default="")


def normalize_provider(name: str | None) -> str:
    p = (name or "yfinance").strip().lower()
    if p in ("indmoney", "indstocks", "ind", "ind_money", "ind-money"):
        return "indmoney"
    if p in ("groww",):
        return "groww"
    return "yfinance"


def set_data_provider(name: str) -> None:
    _data_provider.set(normalize_provider(name))


def get_active_data_provider() -> str:
    return normalize_provider(_data_provider.get())


def set_indmoney_token(token: str) -> None:
    _indmoney_token.set((token or "").strip())


def get_active_indmoney_token() -> str:
    return _indmoney_token.get()
