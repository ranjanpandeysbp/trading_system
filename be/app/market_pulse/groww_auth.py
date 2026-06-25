"""Thread-local Groww token for market pulse engines (replaces Streamlit session)."""

from __future__ import annotations

import contextvars

_groww_token: contextvars.ContextVar[str] = contextvars.ContextVar("groww_token", default="")


def set_groww_token(token: str) -> None:
    _groww_token.set((token or "").strip())


def get_active_groww_token() -> str:
    return _groww_token.get()
