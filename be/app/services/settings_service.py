from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.db_models import AppSetting

DEFAULT_CLAUDE_ENDPOINT = "https://atul-mjil3w7p-swedencentral.services.ai.azure.com/anthropic"
DEFAULT_CLAUDE_MODEL = "claude-sonnet-5"
DEFAULT_OPENAI_ENDPOINT = "https://aiadvisorassis8258039388.services.ai.azure.com/openai/v1"
DEFAULT_OPENAI_MODEL = "gpt-5-nano"


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

    async def get_gemini_api_key(self) -> str | None:
        token = await self._get("gemini_api_key", "")
        if not token:
            import os
            token = (os.getenv("GEMINI_API_KEY") or "").strip()
        return token or None

    async def get_groq_api_key(self) -> str | None:
        token = await self._get("groq_api_key", "")
        if not token:
            import os
            token = (os.getenv("GROQ_API_KEY") or "").strip()
        return token or None

    async def get_claude_api_key(self) -> str | None:
        token = await self._get("claude_api_key", "")
        if not token:
            import os
            token = (
                os.getenv("CLAUDE_API_KEY")
                or os.getenv("ANTHROPIC_FOUNDRY_API_KEY")
                or ""
            ).strip()
        return token or None

    async def get_openai_api_key(self) -> str | None:
        token = await self._get("openai_api_key", "")
        if not token:
            import os
            token = (os.getenv("OPENAI_API_KEY") or os.getenv("AZURE_OPENAI_API_KEY") or "").strip()
        return token or None

    async def get_ai_provider(self) -> str:
        provider = await self._get("ai_provider", "")
        if not provider:
            gemini = await self.get_gemini_api_key()
            groq = await self.get_groq_api_key()
            claude = await self.get_claude_api_key()
            openai = await self.get_openai_api_key()
            si = await self.get_superinvesting_token()
            if gemini:
                return "Google Gemini"
            if groq:
                return "Groq (LLaMA)"
            if claude:
                return "Claude (Azure)"
            if openai:
                return "OpenAI (Azure)"
            if si:
                return "Investing Agent"
            return "Google Gemini"
        return provider

    async def get_groq_model(self) -> str:
        import os
        return await self._get("groq_model", os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"))

    async def get_gemini_model(self) -> str:
        import os
        return await self._get("gemini_model", os.getenv("MODEL_NAME", "gemini-2.0-flash"))

    async def get_claude_model(self) -> str:
        import os
        return await self._get(
            "claude_model",
            os.getenv("CLAUDE_MODEL", DEFAULT_CLAUDE_MODEL),
        )

    async def get_claude_endpoint(self) -> str:
        import os
        return await self._get(
            "claude_endpoint",
            os.getenv("CLAUDE_ENDPOINT")
            or os.getenv("ANTHROPIC_FOUNDRY_BASE_URL")
            or DEFAULT_CLAUDE_ENDPOINT,
        )

    async def get_openai_model(self) -> str:
        import os
        return await self._get(
            "openai_model",
            os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
        )

    async def get_openai_endpoint(self) -> str:
        import os
        return await self._get(
            "openai_endpoint",
            os.getenv("OPENAI_ENDPOINT")
            or os.getenv("AZURE_OPENAI_ENDPOINT")
            or DEFAULT_OPENAI_ENDPOINT,
        )

    async def get_ai_model(self, provider: str | None = None) -> str:
        provider = provider or await self.get_ai_provider()
        if provider == "Groq (LLaMA)":
            return await self.get_groq_model()
        if provider == "Investing Agent":
            return "superinvesting-chat"
        if provider == "Claude (Azure)":
            return await self.get_claude_model()
        if provider == "OpenAI (Azure)":
            return await self.get_openai_model()
        return await self.get_gemini_model()

    async def get_api_key_for_provider(self, provider: str) -> str | None:
        if provider == "Groq (LLaMA)":
            return await self.get_groq_api_key()
        if provider == "Google Gemini":
            return await self.get_gemini_api_key()
        if provider == "Investing Agent":
            return await self.get_superinvesting_token()
        if provider == "Claude (Azure)":
            return await self.get_claude_api_key()
        if provider == "OpenAI (Azure)":
            return await self.get_openai_api_key()
        return None

    async def get_default_market(self) -> str:
        return await self._get("default_market", "Groww (India Stocks)")

    def _youtube_key(self, base: str, user_id: int | None) -> str:
        if user_id is None:
            return base
        return f"{base}__u{user_id}"

    async def get_youtube_api_key(self, user_id: int | None = None) -> str | None:
        if user_id is not None:
            token = await self._get(self._youtube_key("youtube_api_key", user_id), "")
            if token:
                return token
        token = await self._get("youtube_api_key", "")
        if not token:
            import os
            token = (os.getenv("YOUTUBE_API_KEY") or "").strip()
        return token or None

    async def get_superinvesting_token(self) -> str | None:
        token = await self._get("superinvesting_token", "")
        if not token:
            import os
            token = (os.getenv("SUPERINVESTING_TOKEN") or "").strip()
        return token or None

    async def get_youtube_channel_ids(self, user_id: int | None = None) -> str:
        if user_id is not None:
            val = await self._get(self._youtube_key("youtube_channel_ids", user_id), "")
            if val:
                return val
        return await self._get("youtube_channel_ids", "")

    async def save_youtube_prefs(
        self,
        user_id: int,
        *,
        youtube_api_key: str | None = None,
        youtube_channel_ids: str | None = None,
    ) -> None:
        if youtube_api_key is not None and youtube_api_key.strip():
            await self._set(self._youtube_key("youtube_api_key", user_id), youtube_api_key.strip())
        if youtube_channel_ids is not None:
            await self._set(
                self._youtube_key("youtube_channel_ids", user_id),
                youtube_channel_ids.strip(),
            )

    async def get_all(self, user_id: int | None = None) -> dict:
        token = await self.get_groww_token()
        return {
            "data_provider": await self.get_data_provider(),
            "groww_token_set": bool(token),
            "groww_exchange": await self.get_groww_exchange(),
            "initial_capital": await self.get_initial_capital(),
            "costs_pct": await self.get_costs_pct(),
            "benchmark_ticker": await self.get_benchmark_ticker(),
            "gemini_token_set": bool(await self.get_gemini_api_key()),
            "groq_token_set": bool(await self.get_groq_api_key()),
            "claude_token_set": bool(await self.get_claude_api_key()),
            "openai_token_set": bool(await self.get_openai_api_key()),
            "ai_provider": await self.get_ai_provider(),
            "groq_model": await self.get_groq_model(),
            "gemini_model": await self.get_gemini_model(),
            "claude_model": await self.get_claude_model(),
            "claude_endpoint": await self.get_claude_endpoint(),
            "openai_model": await self.get_openai_model(),
            "openai_endpoint": await self.get_openai_endpoint(),
            "default_market": await self.get_default_market(),
            "youtube_api_key_set": bool(await self.get_youtube_api_key(user_id)),
            "youtube_channel_ids": await self.get_youtube_channel_ids(user_id),
            "superinvesting_token_set": bool(await self.get_superinvesting_token()),
        }

    async def update(self, payload: dict, user_id: int | None = None) -> dict:
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
        if payload.get("gemini_api_key") is not None:
            await self._set("gemini_api_key", payload["gemini_api_key"])
        if payload.get("groq_api_key") is not None:
            await self._set("groq_api_key", payload["groq_api_key"])
        if payload.get("claude_api_key") is not None:
            await self._set("claude_api_key", payload["claude_api_key"].strip())
        if payload.get("openai_api_key") is not None:
            await self._set("openai_api_key", payload["openai_api_key"].strip())
        if payload.get("ai_provider") is not None:
            await self._set("ai_provider", payload["ai_provider"])
        if payload.get("groq_model") is not None:
            await self._set("groq_model", payload["groq_model"])
        if payload.get("gemini_model") is not None:
            await self._set("gemini_model", payload["gemini_model"])
        if payload.get("claude_model") is not None:
            await self._set("claude_model", payload["claude_model"].strip())
        if payload.get("claude_endpoint") is not None:
            await self._set("claude_endpoint", payload["claude_endpoint"].strip().rstrip("/"))
        if payload.get("openai_model") is not None:
            await self._set("openai_model", payload["openai_model"].strip())
        if payload.get("openai_endpoint") is not None:
            await self._set("openai_endpoint", payload["openai_endpoint"].strip().rstrip("/"))
        if payload.get("default_market") is not None:
            await self._set("default_market", payload["default_market"])
        if user_id is not None and (
            payload.get("youtube_api_key") is not None
            or payload.get("youtube_channel_ids") is not None
        ):
            await self.save_youtube_prefs(
                user_id,
                youtube_api_key=payload.get("youtube_api_key"),
                youtube_channel_ids=payload.get("youtube_channel_ids"),
            )
        elif payload.get("youtube_api_key") is not None:
            await self._set("youtube_api_key", payload["youtube_api_key"])
        if payload.get("superinvesting_token") is not None:
            await self._set("superinvesting_token", payload["superinvesting_token"].strip())
        return await self.get_all(user_id)
