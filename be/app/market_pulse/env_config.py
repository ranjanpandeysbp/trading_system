"""Stub env helpers for news scanner AI (optional)."""

def api_key_env_hint(_provider: str) -> str:
    return "Set GEMINI_API_KEY or GROQ_API_KEY in environment"


def get_api_key_for_provider(_provider: str) -> str:
    import os
    return os.getenv("GEMINI_API_KEY") or os.getenv("GROQ_API_KEY") or ""
