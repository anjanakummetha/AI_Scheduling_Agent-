"""LLM client for triage/scheduler/comms — Anthropic via OpenAI-compatible API.

Uses the same Anthropic credentials as the Hermes gateway (provider: anthropic).
See https://docs.anthropic.com/en/api/openai-sdk
"""

from openai import OpenAI

from app.config import ANTHROPIC_OPENAI_BASE_URL, settings


def get_hermes_client() -> OpenAI:
    if not settings.llm_api_key:
        raise RuntimeError(
            "No LLM API key configured. Set ANTHROPIC_API_KEY in .env "
            "(or in ~/.hermes/.env) or set LLM_API_KEY explicitly."
        )
    if "11434" in settings.llm_base_url:
        raise RuntimeError(
            "Ollama is not supported for Lexi. Remove LLM_BASE_URL pointing at localhost:11434 "
            f"or unset it to use Anthropic ({ANTHROPIC_OPENAI_BASE_URL})."
        )
    return OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)
