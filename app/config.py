"""Application configuration loaded from environment variables."""

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    app_name: str = "AI Scheduling Agent"
    database_path: Path = ROOT_DIR / "data" / "scheduling_agent.db"
    rules_dir: Path = ROOT_DIR / "app" / "rules"
    llm_base_url: str = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
    llm_api_key: str = os.getenv("LLM_API_KEY", "ollama")
    llm_model: str = os.getenv("LLM_MODEL", "nousresearch/hermes-4-70b")
    composio_api_key: str | None = os.getenv("COMPOSIO_API_KEY")
    composio_user_id: str = os.getenv("COMPOSIO_USER_ID", "kory")
    demo_mode: bool = os.getenv("DEMO_MODE", "true").lower() in {"1", "true", "yes"}
    scheduling_timezone: str = os.getenv("SCHEDULING_TIMEZONE", "America/Denver")
    outlook_timezone: str = os.getenv("OUTLOOK_TIMEZONE", "America/New_York")
    lexi_agent_name: str = os.getenv("LEXI_AGENT_NAME", "Lexi")
    composio_outlook_auth_config_id: str | None = os.getenv("COMPOSIO_OUTLOOK_AUTH_CONFIG_ID")
    composio_asana_auth_config_id: str | None = os.getenv("COMPOSIO_ASANA_AUTH_CONFIG_ID")


settings = Settings()
