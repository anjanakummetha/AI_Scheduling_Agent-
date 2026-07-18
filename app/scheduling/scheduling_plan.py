"""LLM + rules scheduling plan — window, duration, format before slot search."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.config import settings
from app.scheduling.scheduling_window import SchedulingWindow, infer_scheduling_window

PLAN_SYSTEM_PROMPT = """You are Lexi, Kory Mitchell's scheduling assistant.
Read the email and return ONLY valid JSON with these keys:
- task_type: "offer_times" | "general_reply" | "no_action"
- window_label: string or null (e.g. "next week", "this week", "tomorrow")
- duration_minutes: integer or null (default 30 for intro calls)
- meeting_format: "virtual" | "in_person" | null
- urgency: boolean
- draft_context: one sentence on tone/context for the reply (no invented times)

Do not propose specific clock times — only interpret what the sender is asking for.
No markdown fences."""


@dataclass
class SchedulingPlan:
    task_type: str = "offer_times"
    window: SchedulingWindow | None = None
    duration_minutes: int | None = None
    meeting_format: str | None = None
    urgency: bool = False
    draft_context: str = ""
    source: str = "rules"
    raw: dict[str, Any] = field(default_factory=dict)


def build_scheduling_plan(
    *,
    subject: str = "",
    body: str = "",
    intent: str | None = None,
    reference_now: datetime | None = None,
    use_llm: bool = True,
) -> SchedulingPlan:
    """Combine rule-based window detection with optional LLM interpretation."""
    rule_window = infer_scheduling_window(subject=subject, body=body, now=reference_now)
    plan = SchedulingPlan(
        window=rule_window,
        source="rules" if rule_window else "default",
    )

    if not use_llm or not settings.llm_api_key:
        plan = _apply_intent_defaults(plan, intent)
        return plan

    try:
        from app.llm.hermes_client import get_hermes_client

        client = get_hermes_client()
        payload = {
            "subject": subject,
            "body": body,
            "intent": intent,
            "rule_window": (
                {
                    "label": rule_window.label,
                    "start": rule_window.start.isoformat(),
                    "end": rule_window.end.isoformat(),
                }
                if rule_window
                else None
            ),
        }
        response = client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": PLAN_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, default=str)},
            ],
            temperature=0.1,
        )
        content = response.choices[0].message.content or ""
        parsed = _parse_json_object(content)
        plan = _merge_llm_plan(plan, parsed, subject=subject, body=body, now=reference_now)
        plan.source = "llm+rules" if rule_window else "llm"
        plan.raw = parsed
    except Exception:
        pass

    return _apply_intent_defaults(plan, intent)


def _apply_intent_defaults(plan: SchedulingPlan, intent: str | None) -> SchedulingPlan:
    if plan.task_type == "offer_times" and plan.duration_minutes is None:
        from app.scheduling.meeting_type import resolve_meeting_type

        spec = resolve_meeting_type(intent=intent or "")
        plan.duration_minutes = spec.duration_minutes
    return plan


def _merge_llm_plan(
    plan: SchedulingPlan,
    parsed: dict[str, Any],
    *,
    subject: str,
    body: str,
    now: datetime | None,
) -> SchedulingPlan:
    task = str(parsed.get("task_type") or "offer_times").strip().lower()
    if task in {"offer_times", "general_reply", "no_action"}:
        plan.task_type = task

    label = parsed.get("window_label")
    if isinstance(label, str) and label.strip():
        llm_window = infer_scheduling_window(
            subject=f"{subject} {label}",
            body=body,
            now=now,
        )
        if llm_window:
            plan.window = llm_window

    dur = parsed.get("duration_minutes")
    if isinstance(dur, int) and dur > 0:
        plan.duration_minutes = dur
    elif isinstance(dur, str) and dur.isdigit():
        plan.duration_minutes = int(dur)

    fmt = parsed.get("meeting_format")
    if fmt in {"virtual", "in_person"}:
        plan.meeting_format = fmt

    plan.urgency = bool(parsed.get("urgency"))
    plan.draft_context = str(parsed.get("draft_context") or "").strip()
    return plan


def _parse_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)
