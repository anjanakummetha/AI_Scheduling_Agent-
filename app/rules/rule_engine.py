"""Load YAML scheduling rules and expose small rule helpers."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import yaml

from app.config import settings


def _load_yaml(filename: str) -> dict[str, Any]:
    path = settings.rules_dir / filename
    with path.open() as file:
        return yaml.safe_load(file) or {}


@lru_cache
def load_rules() -> dict[str, Any]:
    return {
        "scheduling": _load_yaml("scheduling_rules.yaml"),
        "meeting_types": _load_yaml("meeting_types.yaml").get("meeting_types", {}),
        "priority_contacts": _load_yaml("priority_contacts.yaml").get("priority_contacts", []),
    }


def is_priority_contact(email: str) -> bool:
    normalized = email.strip().lower()
    contacts = load_rules()["priority_contacts"]
    return any(contact.get("email", "").lower() == normalized for contact in contacts)


def rules_for_prompt() -> str:
    rules = load_rules()
    scheduling = rules["scheduling"]
    meeting_types = rules["meeting_types"]
    priority_contacts = rules["priority_contacts"]

    return f"""
Scheduling phase:
- Approval required: {scheduling['phase']['approval_required']}
- Autonomous sending: {scheduling['phase']['autonomous_sending']}
- Autonomous calendar writes: {scheduling['phase']['autonomous_calendar_writes']}

Timezone:
- Internal calendar timezone: {scheduling['timezone']['internal']}
- External email format: {scheduling['timezone']['external_format']}

Hard blocks:
{scheduling.get('hard_blocks', [])}

Meeting types:
{meeting_types}

Priority contacts:
{priority_contacts}

Email rules:
{scheduling['email']}
"""
