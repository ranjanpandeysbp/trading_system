"""Gemini / Groq AI reports — settings-backed keys (same pattern as Groww token)."""

from __future__ import annotations

import re
from typing import Any

from app.services.settings_service import SettingsService

try:
    from groq import Groq
except ImportError:
    Groq = None  # type: ignore

try:
    from google import genai as genai_new

    GENAI_NEW = True
except ImportError:
    try:
        import google.generativeai as genai  # type: ignore

        GENAI_NEW = False
    except ImportError:
        GENAI_NEW = False
        genai = None  # type: ignore

AI_PROVIDER_GEMINI = "Google Gemini"
AI_PROVIDER_GROQ = "Groq (LLaMA)"
SUPPORTED_AI_PROVIDERS = [AI_PROVIDER_GEMINI, AI_PROVIDER_GROQ]

GROQ_MODEL_OPTIONS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "llama3-70b-8192",
    "mixtral-8x7b-32768",
    "gemma2-9b-it",
]

GEMINI_MODEL_OPTIONS = [
    "gemini-3.1-flash-lite",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
]

DEFAULT_ASK_AI_SYSTEM = """You are an expert trading analyst for Indian equities, US stocks, and crypto futures.
Use ONLY the scan/context data provided. Be concise and actionable.
Structure your reply with:
## FINAL VERDICT
BUY | SELL | AVOID (one word on its own line after the header)

Then: Setup summary, key levels, risk (SL %), reward (TP %), and what would invalidate the thesis.
Do not invent prices or indicators not present in the context."""


def call_ai_report(
    prompt_data: str,
    system_prompt: str,
    provider: str,
    model: str,
    api_key: str,
    *,
    user_intro: str | None = None,
    max_tokens: int = 3000,
) -> str:
    """Call Groq or Gemini and return report text."""
    if provider not in SUPPORTED_AI_PROVIDERS:
        return "Custom AI provider is not supported. Use Google Gemini or Groq (LLaMA)."
    if not api_key:
        return f"Missing API key for {provider}. Add it in Manage → AI Settings."

    intro = user_intro or "Analyze the following data and give a trade verdict with setup:"
    user_msg = f"{intro}\n\n{prompt_data}"

    try:
        if provider == AI_PROVIDER_GROQ:
            if Groq is None:
                return "Groq SDK not installed. Run: pip install groq"
            client = Groq(api_key=api_key)
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=max_tokens,
                temperature=0.35,
            )
            return resp.choices[0].message.content or ""

        if GENAI_NEW:
            client = genai_new.Client(api_key=api_key)
            combined = system_prompt + "\n\n" + user_msg
            resp = client.models.generate_content(model=model, contents=combined)
            return resp.text or ""

        if genai:
            genai.configure(api_key=api_key)
            gmodel = genai.GenerativeModel(model, system_instruction=system_prompt)
            resp = gmodel.generate_content(user_msg)
            return resp.text or ""

        return "Google Gemini library not installed. Run: pip install google-genai"
    except Exception as exc:
        return f"AI report error: {exc}. Check API key and model in Manage settings."


def parse_ai_verdict(report_text: str) -> str | None:
    match = re.search(r"##\s*FINAL\s*VERDICT\s*\n\s*(BUY|SELL|AVOID)", report_text, re.IGNORECASE)
    if not match:
        match = re.search(r"\b(BUY|SELL|AVOID)\b", report_text[:400], re.IGNORECASE)
    return match.group(1).upper() if match else None


class AIService:
    def __init__(self, settings: SettingsService):
        self.settings = settings

    async def provider_config(self) -> dict[str, Any]:
        provider = await self.settings.get_ai_provider()
        model = await self.settings.get_ai_model(provider)
        gemini_set = bool(await self.settings.get_gemini_api_key())
        groq_set = bool(await self.settings.get_groq_api_key())
        key = await self.settings.get_api_key_for_provider(provider)
        return {
            "provider": provider,
            "model": model,
            "gemini_token_set": gemini_set,
            "groq_token_set": groq_set,
            "ready": bool(key),
            "groq_models": GROQ_MODEL_OPTIONS,
            "gemini_models": GEMINI_MODEL_OPTIONS,
            "providers": SUPPORTED_AI_PROVIDERS,
        }

    async def ask(
        self,
        *,
        context: str,
        question: str | None = None,
        system_prompt: str | None = None,
        section: str | None = None,
        max_tokens: int = 3000,
    ) -> dict[str, Any]:
        provider = await self.settings.get_ai_provider()
        model = await self.settings.get_ai_model(provider)
        api_key = await self.settings.get_api_key_for_provider(provider)

        if not context.strip():
            raise ValueError("Context is empty — run a scan first, then Ask AI.")

        if len(context) > 14000:
            context = context[:14000] + "\n\n[Context truncated to 14k chars.]"

        intro = question or "Analyze this section output and give an actionable trade verdict."
        if section:
            intro = f"Section: {section}\n\n{intro}"

        report = call_ai_report(
            context,
            system_prompt or DEFAULT_ASK_AI_SYSTEM,
            provider,
            model,
            api_key,
            user_intro=intro,
            max_tokens=max_tokens,
        )

        return {
            "report": report,
            "verdict": parse_ai_verdict(report),
            "provider": provider,
            "model": model,
            "section": section,
            "error": report.startswith("Missing") or report.startswith("AI report error"),
        }
