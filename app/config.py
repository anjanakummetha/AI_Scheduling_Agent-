"""Application configuration loaded from environment variables."""

from dataclasses import dataclass, field
import os
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")

_HERMES_ENV = Path.home() / ".hermes" / ".env"
if _HERMES_ENV.exists():
    load_dotenv(_HERMES_ENV, override=False)

ANTHROPIC_OPENAI_BASE_URL = "https://api.anthropic.com/v1"
ASANA_BOARD_NAME = "Reservation Reminders"
ASANA_PARENT_PROJECT_NAME = "Kory NON-IFG"


def resolve_lexi_database_path() -> Path:
    """Resolve DB path from LEXI_DATABASE_PATH or default data/lexi.db under project root."""
    raw = os.getenv("LEXI_DATABASE_PATH", "").strip()
    if not raw:
        return ROOT_DIR / "data" / "lexi.db"
    path = Path(raw)
    return path if path.is_absolute() else ROOT_DIR / path


def resolve_llm_base_url() -> str:
    explicit = os.getenv("LLM_BASE_URL", "").strip()
    if explicit:
        return explicit
    return ANTHROPIC_OPENAI_BASE_URL


def resolve_llm_api_key() -> str:
    return (os.getenv("LLM_API_KEY") or os.getenv("ANTHROPIC_API_KEY") or "").strip()


def resolve_llm_model() -> str:
    """Default: Claude Sonnet 4.6 — best balance of tool-use, speed, and 200k context for Lexi."""
    return (
        os.getenv("LLM_MODEL", "").strip()
        or os.getenv("LEXI_LLM_MODEL", "").strip()
        or "claude-sonnet-4-6"
    )


def resolve_kory_sender_emails() -> tuple[str, ...]:
    raw = os.getenv("KORY_SENDER_EMAILS", "").strip()
    if not raw:
        return ()
    return tuple(email.strip().lower() for email in raw.split(",") if email.strip())


def resolve_lexi_write_mode() -> str:
    mode = os.getenv("LEXI_WRITE_MODE", "sandbox").strip().lower()
    return mode if mode in {"sandbox", "kory"} else "sandbox"


def resolve_composio_search_enabled() -> bool:
    return os.getenv("LEXI_COMPOSIO_SEARCH_ENABLED", "true").lower() in {"1", "true", "yes"}


def resolve_teams_inbound_notify_mode() -> str:
    mode = os.getenv("LEXI_TEAMS_INBOUND_NOTIFY_MODE", "delegation_and_followups").strip().lower()
    if mode in {"delegation_only", "delegation_and_followups", "important", "all"}:
        return mode
    return "delegation_and_followups"


def resolve_default_send_channel() -> str:
    ch = os.getenv("LEXI_DEFAULT_SEND_CHANNEL", "kory").strip().lower()
    return ch if ch in {"kory", "lexi"} else "kory"


def resolve_lexi_calendar_search_days() -> int:
    try:
        return max(14, int(os.getenv("LEXI_CALENDAR_SEARCH_DAYS", "60")))
    except ValueError:
        return 60


def resolve_lexi_calendar_search_days_max() -> int:
    try:
        return max(30, int(os.getenv("LEXI_CALENDAR_SEARCH_DAYS_MAX", "120")))
    except ValueError:
        return 120


@dataclass(frozen=True)
class Settings:
    app_name: str = "Lexi Scheduling Agent"
    lexi_database_path: Path = field(default_factory=resolve_lexi_database_path)
    rules_dir: Path = ROOT_DIR / "app" / "rules"
    llm_base_url: str = field(default_factory=resolve_llm_base_url)
    llm_api_key: str = field(default_factory=resolve_llm_api_key)
    llm_model: str = field(default_factory=resolve_llm_model)
    composio_api_key: str | None = os.getenv("COMPOSIO_API_KEY")
    # Read path: Kory Outlook
    kory_composio_connection_id: str | None = (
        os.getenv("KORY_COMPOSIO_CONNECTION_ID", "").strip() or None
    )
    composio_entity_id: str | None = os.getenv("COMPOSIO_ENTITY_ID", "").strip() or None
    # Write path: sandbox (pilot) or Kory when LEXI_WRITE_MODE=kory
    lexi_write_mode: str = field(default_factory=resolve_lexi_write_mode)
    sandbox_composio_connection_id: str | None = (
        os.getenv("SANDBOX_COMPOSIO_CONNECTION_ID", "").strip() or None
    )
    sandbox_composio_entity_id: str | None = (
        os.getenv("SANDBOX_COMPOSIO_ENTITY_ID", "").strip() or None
    )
    sandbox_mailbox_email: str | None = os.getenv("SANDBOX_MAILBOX_EMAIL", "").strip() or None
    sandbox_email_loopback: bool = os.getenv("SANDBOX_EMAIL_LOOPBACK", "true").lower() in {
        "1",
        "true",
        "yes",
    }
    demo_mode: bool = os.getenv("DEMO_MODE", "false").lower() in {"1", "true", "yes"}
    lexi_dry_run: bool = os.getenv("LEXI_DRY_RUN", "true").lower() in {"1", "true", "yes"}
    # When true, blocks all Kory mailbox outbound (sends + draft creation) regardless of approval.
    lexi_kory_outbound_blocked: bool = os.getenv(
        "LEXI_KORY_OUTBOUND_BLOCKED", "true"
    ).lower() in {"1", "true", "yes"}
    # Blocks ALL Composio writes against Kory's connected account (calendar + mail).
    lexi_kory_space_read_only: bool = os.getenv(
        "LEXI_KORY_SPACE_READ_ONLY", "true"
    ).lower() in {"1", "true", "yes"}
    lexi_composio_connection_id: str | None = (
        os.getenv("LEXI_COMPOSIO_CONNECTION_ID", "").strip() or None
    )
    lexi_mailbox_email: str | None = os.getenv("LEXI_MAILBOX_EMAIL", "").strip() or None
    lexi_cc_emails: str | None = os.getenv("LEXI_CC_EMAILS", "").strip() or None
    lexi_default_send_channel: str = field(default_factory=resolve_default_send_channel)
    lexi_delegation_auto_draft: bool = os.getenv(
        "LEXI_DELEGATION_AUTO_DRAFT", "true"
    ).lower() in {"1", "true", "yes"}
    lexi_delegation_cc_only: bool = os.getenv(
        "LEXI_DELEGATION_CC_ONLY", "true"
    ).lower() in {"1", "true", "yes"}
    lexi_teams_inbound_notify_mode: str = field(default_factory=resolve_teams_inbound_notify_mode)
    lexi_composio_search_enabled: bool = field(default_factory=resolve_composio_search_enabled)
    scheduling_timezone: str = os.getenv("SCHEDULING_TIMEZONE", "America/Denver")
    outlook_timezone: str = os.getenv("OUTLOOK_TIMEZONE", "America/New_York")
    lexi_calendar_search_days: int = field(default_factory=resolve_lexi_calendar_search_days)
    lexi_calendar_search_days_max: int = field(
        default_factory=resolve_lexi_calendar_search_days_max
    )
    asana_project_gid: str | None = os.getenv("ASANA_PROJECT_GID", "").strip() or None
    asana_section_gid: str | None = os.getenv("ASANA_SECTION_GID", "").strip() or None
    asana_composio_connection_id: str | None = (
        os.getenv("ASANA_COMPOSIO_CONNECTION_ID", "").strip() or None
    )
    hubspot_composio_connection_id: str | None = (
        os.getenv("HUBSPOT_COMPOSIO_CONNECTION_ID", "").strip() or None
    )
    # Explicit live-write kill switches for CRM/task systems. Keep false for UAT.
    asana_live_writes_enabled: bool = os.getenv(
        "LEXI_ASANA_LIVE_WRITES_ENABLED", "false"
    ).lower() in {"1", "true", "yes"}
    hubspot_live_writes_enabled: bool = os.getenv(
        "LEXI_HUBSPOT_LIVE_WRITES_ENABLED", "false"
    ).lower() in {"1", "true", "yes"}
    # Outreach campaigns: stage locally by default; never send until enabled.
    outreach_live_sends_enabled: bool = os.getenv(
        "LEXI_OUTREACH_LIVE_SENDS_ENABLED", "false"
    ).lower() in {"1", "true", "yes"}
    outreach_outlook_drafts_enabled: bool = os.getenv(
        "LEXI_OUTREACH_OUTLOOK_DRAFTS_ENABLED", "false"
    ).lower() in {"1", "true", "yes"}
    asana_enabled: bool = os.getenv("ASANA_ENABLED", "false").lower() in {"1", "true", "yes"}
    lexi_teams_enabled: bool = os.getenv("LEXI_TEAMS_ENABLED", "false").lower() in {
        "1",
        "true",
        "yes",
    }
    lexi_teams_text_only: bool = os.getenv("LEXI_TEAMS_TEXT_ONLY", "true").lower() in {
        "1",
        "true",
        "yes",
    }
    lexi_suppress_teams_push: bool = os.getenv(
        "LEXI_SUPPRESS_TEAMS_PUSH", "false"
    ).lower() in {"1", "true", "yes"}
    kory_sender_emails: tuple[str, ...] = field(default_factory=resolve_kory_sender_emails)
    heidi_escalation_cc_kory: bool = os.getenv(
        "HEIDI_ESCALATION_CC_KORY", "true"
    ).lower() in {"1", "true", "yes"}


settings = Settings()
