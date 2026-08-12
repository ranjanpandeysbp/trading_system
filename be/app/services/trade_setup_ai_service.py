"""Shared helper: optionally AI-refine trade setups on a scan payload."""

from __future__ import annotations

import asyncio
from typing import Any

from app.market_pulse.serialize import json_safe
from app.market_pulse.trade_setup_ai import refine_trade_setups_with_ai
from app.services.ai_service import AI_PROVIDER_CLAUDE, AI_PROVIDER_OPENAI, normalize_ai_provider
from app.services.settings_service import SettingsService


async def maybe_refine_trade_setups_ai(
    settings: SettingsService,
    payload: dict[str, Any],
    *,
    use_ai: bool,
    section: str,
) -> dict[str, Any]:
    """If use_ai, refine confidence/SL/TP (and reverse/continue odds) via configured AI."""
    if not use_ai or not isinstance(payload, dict):
        if isinstance(payload, dict):
            payload.setdefault("use_ai", False)
        return payload

    provider = normalize_ai_provider(await settings.get_ai_provider())
    api_key = await settings.get_api_key_for_provider(provider)
    model = await settings.get_ai_model(provider)
    base_url = None
    if provider == AI_PROVIDER_OPENAI:
        base_url = await settings.get_openai_endpoint()
    elif provider == AI_PROVIDER_CLAUDE:
        base_url = await settings.get_claude_endpoint()

    def _run():
        return refine_trade_setups_with_ai(
            payload,
            provider=str(provider or ""),
            model=str(model or ""),
            api_key=str(api_key or ""),
            section=section,
            base_url=base_url,
        )

    refined = await asyncio.to_thread(_run)
    return json_safe(refined)
