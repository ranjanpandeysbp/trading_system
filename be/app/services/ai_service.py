"""Gemini / Groq / Claude / OpenAI / Investing Agent AI reports — settings-backed keys."""

from __future__ import annotations

import re
from typing import Any

from app.services.settings_service import (
    DEFAULT_CLAUDE_ENDPOINT,
    DEFAULT_OPENAI_ENDPOINT,
    SettingsService,
)

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

try:
    from anthropic import AnthropicFoundry
except ImportError:
    AnthropicFoundry = None  # type: ignore

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # type: ignore

AI_PROVIDER_GEMINI = "Google Gemini"
AI_PROVIDER_GROQ = "Groq (LLaMA)"
AI_PROVIDER_CLAUDE = "Claude (Azure)"
AI_PROVIDER_OPENAI = "OpenAI (Azure)"
AI_PROVIDER_INVESTING_AGENT = "Investing Agent"
SUPPORTED_AI_PROVIDERS = [
    AI_PROVIDER_GEMINI,
    AI_PROVIDER_GROQ,
    AI_PROVIDER_CLAUDE,
    AI_PROVIDER_OPENAI,
    AI_PROVIDER_INVESTING_AGENT,
]

# Accept common aliases / casing from older saves
_PROVIDER_ALIASES = {
    "google gemini": AI_PROVIDER_GEMINI,
    "gemini": AI_PROVIDER_GEMINI,
    "groq (llama)": AI_PROVIDER_GROQ,
    "groq": AI_PROVIDER_GROQ,
    "claude (azure)": AI_PROVIDER_CLAUDE,
    "claude": AI_PROVIDER_CLAUDE,
    "anthropic": AI_PROVIDER_CLAUDE,
    "openai (azure)": AI_PROVIDER_OPENAI,
    "openai": AI_PROVIDER_OPENAI,
    "azure openai": AI_PROVIDER_OPENAI,
    "investing agent": AI_PROVIDER_INVESTING_AGENT,
    "superinvesting": AI_PROVIDER_INVESTING_AGENT,
    "super investing": AI_PROVIDER_INVESTING_AGENT,
}


def normalize_ai_provider(provider: str | None) -> str:
    raw = (provider or "").strip()
    if not raw:
        return AI_PROVIDER_GEMINI
    if raw in SUPPORTED_AI_PROVIDERS:
        return raw
    return _PROVIDER_ALIASES.get(raw.lower(), raw)

GROQ_MODEL_OPTIONS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "llama3-70b-8192",
    "mixtral-8x7b-32768",
    "gemma2-9b-it",
]

GEMINI_MODEL_OPTIONS = [
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-3.1-flash-lite",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
]

CLAUDE_MODEL_OPTIONS = [
    "claude-sonnet-5",
    "claude-opus-4-1",
    "claude-sonnet-4-5",
    "claude-haiku-4-5",
]

OPENAI_MODEL_OPTIONS = [
    "gpt-5.6-sol",
    "DeepSeek-V4-Flash",
    "gpt-4o",
    "o4-mini",
    "gpt-4o-mini",
    "gpt-5-nano",
    "gpt-5-mini",
    "gpt-5",
    "gpt-4.1",
    "gpt-4.1-mini",
]

INVESTING_AGENT_MODEL = "superinvesting-chat"

DEFAULT_ASK_AI_SYSTEM = """You are an expert trading analyst for Indian equities, US stocks, and crypto futures.
Use ONLY the scan/context data provided. Be concise and actionable.
Structure your reply with:
## FINAL VERDICT
BUY | SELL | AVOID (one word on its own line after the header)

Then: Setup summary, key levels, risk (SL %), reward (TP %), and what would invalidate the thesis.
Do not invent prices or indicators not present in the context."""


def _extract_openai_response_text(response: Any) -> str:
    text = getattr(response, "output_text", None)
    if isinstance(text, str) and text.strip():
        return text
    parts: list[str] = []
    for item in getattr(response, "output", None) or []:
        content = getattr(item, "content", None)
        if content is None and isinstance(item, dict):
            content = item.get("content")
        if not content:
            # Some SDKs return a single content item / string-ish object
            maybe = getattr(item, "text", None) or (item.get("text") if isinstance(item, dict) else None)
            if maybe:
                parts.append(str(maybe))
            continue
        for block in content:
            if isinstance(block, str):
                parts.append(block)
                continue
            btype = getattr(block, "type", None) or (block.get("type") if isinstance(block, dict) else None)
            if btype in ("output_text", "text"):
                val = getattr(block, "text", None) or (block.get("text") if isinstance(block, dict) else None)
                if val:
                    parts.append(str(val))
            else:
                val = getattr(block, "text", None) or (block.get("text") if isinstance(block, dict) else None)
                if val:
                    parts.append(str(val))
    return "\n".join(parts).strip()


def _extract_claude_text(message: Any) -> str:
    chunks: list[str] = []
    for block in getattr(message, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            chunks.append(str(text))
        elif isinstance(block, dict) and block.get("text"):
            chunks.append(str(block["text"]))
    return "\n".join(chunks).strip()


def call_ai_report(
    prompt_data: str,
    system_prompt: str,
    provider: str,
    model: str,
    api_key: str,
    *,
    user_intro: str | None = None,
    max_tokens: int = 3000,
    base_url: str | None = None,
) -> str:
    """Call Groq, Gemini, Claude, OpenAI, or Investing Agent and return report text."""
    provider = normalize_ai_provider(provider)
    if provider not in SUPPORTED_AI_PROVIDERS:
        return (
            "Custom AI provider is not supported. Use Google Gemini, Groq (LLaMA), "
            "Claude (Azure), OpenAI (Azure), or Investing Agent."
        )
    if not api_key:
        return f"Missing API key for {provider}. Add it in Manage → AI Settings."

    intro = user_intro or "Analyze the following data and give a trade verdict with setup:"
    user_msg = f"{intro}\n\n{prompt_data}"

    try:
        if provider == AI_PROVIDER_INVESTING_AGENT:
            from app.services.superinvesting_service import analyze_message_sync

            # SuperInvesting has its own system/tools; fold system hint into the user message.
            full = f"{system_prompt.strip()}\n\n{user_msg}" if system_prompt else user_msg
            if len(full) > 12000:
                full = full[:12000] + "\n\n[Truncated.]"
            return analyze_message_sync(api_key, full)

        if provider == AI_PROVIDER_CLAUDE:
            if AnthropicFoundry is None:
                return "Anthropic SDK not installed. Run: pip install anthropic"
            endpoint = (base_url or DEFAULT_CLAUDE_ENDPOINT).rstrip("/")
            client = AnthropicFoundry(api_key=api_key, base_url=endpoint)
            message = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_msg}],
            )
            text = _extract_claude_text(message)
            return text or str(message.content)

        if provider == AI_PROVIDER_OPENAI:
            if OpenAI is None:
                return "OpenAI SDK not installed. Run: pip install openai"
            endpoint = (base_url or DEFAULT_OPENAI_ENDPOINT).rstrip("/")
            client = OpenAI(base_url=endpoint, api_key=api_key)
            out_tokens = max(int(max_tokens or 3000), 2048)
            model_l = (model or "").strip().lower()
            # DeepSeek (and similar) on Azure Foundry use chat.completions;
            # gpt-5* / sol deployments use the Responses API.
            prefer_chat = model_l.startswith("deepseek") or "deepseek" in model_l

            def _chat_completions() -> str:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_msg},
                    ],
                    max_tokens=out_tokens,
                    temperature=0.35,
                )
                return resp.choices[0].message.content or ""

            if prefer_chat:
                try:
                    text = _chat_completions()
                    if text:
                        return text
                except Exception:
                    pass  # fall through to Responses API

            try:
                create_kwargs: dict[str, Any] = {
                    "model": model,
                    "instructions": system_prompt,
                    "input": user_msg,
                    "max_output_tokens": out_tokens,
                }
                try:
                    response = client.responses.create(
                        **create_kwargs,
                        reasoning={"effort": "low"},
                    )
                except TypeError:
                    response = client.responses.create(**create_kwargs)
                except Exception:
                    response = client.responses.create(**create_kwargs)
                text = _extract_openai_response_text(response)
                if text:
                    return text
                status = getattr(response, "status", None)
                if status == "incomplete":
                    return (
                        "OpenAI response incomplete (likely hit max_output_tokens while reasoning). "
                        "Try again or raise max tokens in Ask AI."
                    )
            except Exception:
                try:
                    return _chat_completions()
                except Exception as chat_exc:
                    return f"OpenAI call failed: {chat_exc}"
            return "OpenAI returned an empty response."

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

    async def _base_url_for_provider(self, provider: str) -> str | None:
        if provider == AI_PROVIDER_CLAUDE:
            return await self.settings.get_claude_endpoint()
        if provider == AI_PROVIDER_OPENAI:
            return await self.settings.get_openai_endpoint()
        return None

    async def provider_config(self) -> dict[str, Any]:
        provider = normalize_ai_provider(await self.settings.get_ai_provider())
        model = await self.settings.get_ai_model(provider)
        gemini_set = bool(await self.settings.get_gemini_api_key())
        groq_set = bool(await self.settings.get_groq_api_key())
        claude_set = bool(await self.settings.get_claude_api_key())
        openai_set = bool(await self.settings.get_openai_api_key())
        si_set = bool(await self.settings.get_superinvesting_token())
        key = await self.settings.get_api_key_for_provider(provider)
        return {
            "provider": provider,
            "model": model,
            "gemini_token_set": gemini_set,
            "groq_token_set": groq_set,
            "claude_token_set": claude_set,
            "openai_token_set": openai_set,
            "superinvesting_token_set": si_set,
            "ready": bool(key),
            "groq_models": GROQ_MODEL_OPTIONS,
            "gemini_models": GEMINI_MODEL_OPTIONS,
            "claude_models": CLAUDE_MODEL_OPTIONS,
            "openai_models": OPENAI_MODEL_OPTIONS,
            "claude_endpoint": await self.settings.get_claude_endpoint(),
            "openai_endpoint": await self.settings.get_openai_endpoint(),
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
        provider = normalize_ai_provider(await self.settings.get_ai_provider())
        model = await self.settings.get_ai_model(provider)
        api_key = await self.settings.get_api_key_for_provider(provider)

        if not context.strip():
            raise ValueError("Context is empty — run a scan first, then Ask AI.")

        if len(context) > 14000:
            context = context[:14000] + "\n\n[Context truncated to 14k chars.]"

        intro = question or "Analyze this section output and give an actionable trade verdict."
        if section:
            intro = f"Section: {section}\n\n{intro}"

        if provider == AI_PROVIDER_INVESTING_AGENT:
            from app.services.superinvesting_service import SuperInvestingError, SuperInvestingService

            if not api_key:
                return {
                    "report": "Missing SuperInvesting token. Add it in Manage → AI Settings (or Investing Agent page).",
                    "verdict": None,
                    "provider": provider,
                    "model": model,
                    "section": section,
                    "error": True,
                }
            sys = system_prompt or DEFAULT_ASK_AI_SYSTEM
            message = f"{sys.strip()}\n\n{intro}\n\n{context}"
            if len(message) > 12000:
                message = message[:12000] + "\n\n[Truncated.]"
            try:
                result = await SuperInvestingService(api_key).analyze_once(message)
                report = result.get("answer") or "No assistant reply returned."
            except SuperInvestingError as exc:
                report = str(exc)
            except Exception as exc:
                report = f"AI report error: {exc}. Check SuperInvesting token in Manage settings."

            return {
                "report": report,
                "verdict": parse_ai_verdict(report),
                "provider": provider,
                "model": model,
                "section": section,
                "error": report.startswith("Missing")
                or report.startswith("AI report error")
                or report.startswith("SuperInvesting")
                or report.startswith("Feature usage")
                or report.startswith("Failed"),
            }

        report = call_ai_report(
            context,
            system_prompt or DEFAULT_ASK_AI_SYSTEM,
            provider,
            model,
            api_key or "",
            user_intro=intro,
            max_tokens=max_tokens,
            base_url=await self._base_url_for_provider(provider),
        )

        return {
            "report": report,
            "verdict": parse_ai_verdict(report),
            "provider": provider,
            "model": model,
            "section": section,
            "error": report.startswith("Missing") or report.startswith("AI report error"),
        }
