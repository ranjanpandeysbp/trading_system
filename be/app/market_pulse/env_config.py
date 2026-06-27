"""Load Groq / Gemini credentials from the project .env file."""

import os
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")

GROQ_API_KEY_ENV = "GROQ_API_KEY"
GEMINI_API_KEY_ENV = "GEMINI_API_KEY"
GROQ_MODEL_ENV = "GROQ_MODEL"
GEMINI_MODEL_ENV = "MODEL_NAME"


def get_groq_api_key() -> str:
    return (os.getenv(GROQ_API_KEY_ENV) or "").strip()


def get_gemini_api_key() -> str:
    return (os.getenv(GEMINI_API_KEY_ENV) or "").strip()


def get_groq_model(default: str = "llama-3.3-70b-versatile") -> str:
    return (os.getenv(GROQ_MODEL_ENV) or default).strip()


def get_gemini_model(default: str = "gemini-3.1-flash-lite") -> str:
    return (os.getenv(GEMINI_MODEL_ENV) or default).strip()


def get_api_key_for_provider(provider: str) -> str:
    if provider == "Groq (LLaMA)":
        return get_groq_api_key()
    if provider == "Google Gemini":
        return get_gemini_api_key()
    return ""


def api_key_env_hint(provider: str) -> str:
    if provider == "Groq (LLaMA)":
        return f"Set `{GROQ_API_KEY_ENV}` in your `.env` file (project root)."
    if provider == "Google Gemini":
        return f"Set `{GEMINI_API_KEY_ENV}` in your `.env` file (project root)."
    return "Enter your API key below."


def default_ai_provider() -> str:
    """Prefer Gemini when both keys exist; otherwise whichever key is set."""
    if get_gemini_api_key():
        return "Google Gemini"
    if get_groq_api_key():
        return "Groq (LLaMA)"
    return "Google Gemini"


def default_ai_provider_index() -> int:
    provider = default_ai_provider()
    options = ["Google Gemini", "Groq (LLaMA)"]
    return options.index(provider) if provider in options else 0


# ─── Alert / notification (.env) ───────────────────────────────────────────

def is_alerts_enabled() -> bool:
    return (os.getenv("ALERTS_ENABLED") or "true").strip().lower() in ("1", "true", "yes", "on")


def get_telegram_bot_token() -> str:
    return (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()


def get_telegram_chat_id() -> str:
    return (os.getenv("TELEGRAM_CHAT_ID") or "").strip()


def get_smtp_host() -> str:
    return (os.getenv("SMTP_HOST") or "").strip()


def get_smtp_port() -> int:
    try:
        return int(os.getenv("SMTP_PORT") or "587")
    except ValueError:
        return 587


def get_smtp_user() -> str:
    return (os.getenv("SMTP_USER") or "").strip()


def get_smtp_password() -> str:
    return (os.getenv("SMTP_PASSWORD") or "").strip()


def get_smtp_from() -> str:
    return (os.getenv("SMTP_FROM") or "").strip()


def get_alert_email_to() -> str:
    return (os.getenv("ALERT_EMAIL_TO") or "").strip()
