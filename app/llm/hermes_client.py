"""OpenAI-compatible Hermes client."""

from openai import OpenAI

from app.config import settings


def get_hermes_client() -> OpenAI:
    return OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)
