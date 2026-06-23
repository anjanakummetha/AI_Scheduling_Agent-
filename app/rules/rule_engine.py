"""Minimal rule helpers for Lexi triage (priority contacts only)."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import yaml

from app.config import settings


@lru_cache
def load_rules() -> dict[str, Any]:
    path = settings.rules_dir / "priority_contacts.yaml"
    with path.open() as file:
        data = yaml.safe_load(file) or {}
    return {"priority_contacts": data.get("priority_contacts", [])}


def is_priority_contact(email: str) -> bool:
    normalized = email.strip().lower()
    contacts = load_rules()["priority_contacts"]
    return any(contact.get("email", "").lower() == normalized for contact in contacts)
