"""Pre-meeting attendee research — web, news, and prior inbox threads."""

from __future__ import annotations

import time
from typing import Any

from app.integrations.composio_search import (
    execute_search_action,
    search_enabled,
    search_news,
    web_search,
)
from app.integrations.outlook_inbox import search_inbox

_last_search_at: float = 0.0
SEARCH_MIN_INTERVAL_SEC = 1.0


def throttle_search_calls() -> None:
    """Respect Composio Search ~1–2 req/s guidance to reduce 429s."""
    global _last_search_at
    now = time.monotonic()
    wait = SEARCH_MIN_INTERVAL_SEC - (now - _last_search_at)
    if wait > 0:
        time.sleep(wait)
    _last_search_at = time.monotonic()


def research_person(
    name: str,
    *,
    company: str = "",
    email: str = "",
    include_inbox: bool = True,
    include_news: bool = True,
) -> dict[str, Any]:
    """Bundle web + news + inbox search for pre-meeting prep (read-only)."""
    if not search_enabled():
        raise RuntimeError("Composio Search is disabled.")

    person = (name or "").strip()
    if not person and not email.strip():
        raise ValueError("name or email is required.")

    org = (company or "").strip()
    label = person or email.split("@", 1)[0]
    search_terms = " ".join(part for part in (person, org) if part)

    throttle_search_calls()
    web = web_search(f"{search_terms} professional background role company")

    news: dict[str, Any] | None = None
    if include_news and search_terms:
        throttle_search_calls()
        news = search_news(f"{search_terms} news")

    prior_threads: list[dict[str, Any]] = []
    inbox_log_id: str | None = None
    if include_inbox:
        inbox_query = email.strip() or person
        if inbox_query:
            prior_threads, inbox_log_id = search_inbox(query=inbox_query, top=8)

    # Optional: LinkedIn-style public search if slug available
    scholar = None
    if search_terms:
        try:
            throttle_search_calls()
            scholar = execute_search_action(
                "COMPOSIO_SEARCH_SCHOLAR",
                {"query": search_terms},
            )
        except Exception:
            scholar = None

    return {
        "subject": label,
        "company": org or None,
        "email": email.strip() or None,
        "web_summary": web.get("data"),
        "recent_news": (news or {}).get("data") if news else None,
        "prior_email_threads": prior_threads,
        "scholar": (scholar or {}).get("data") if scholar else None,
        "inbox_composio_log_id": inbox_log_id,
        "sources_used": [s for s in ("web", "news" if include_news else None, "inbox" if include_inbox else None, "scholar" if scholar else None) if s],
        "hint": (
            "Summarize for Kory: role, company, recent news, and any prior email history. "
            "Cite citations from web results. Ask Kory if identity is ambiguous."
        ),
    }
