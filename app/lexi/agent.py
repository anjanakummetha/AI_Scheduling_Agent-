"""
Lexi orchestrator — routes messages to specialized subagents.

Architecture:
  Router → classifies intent (regex, no LLM call)
        ↓
  Calendar Agent  — add/block/read calendar events
  Email Agent     — find/draft/send emails
  Scheduling Agent — find slots, place holds, options email
  Task Agent      — Asana reservation + follow-up tasks
  General Agent   — catch-all for complex/mixed requests

Each subagent has:
  - Focused system prompt (~200-300 tokens vs 1500+ monolithic)
  - Only the tools it needs loaded (faster, fewer mistakes)
  - Max 4-6 tool rounds (sufficient for specialized tasks)
"""

from __future__ import annotations

import logging
from typing import Any

from openai.types.chat import ChatCompletionMessageParam

from app.config import settings
from app.lexi.router import classify, RoutingDecision
from app.lexi.sessions import get_session_history, save_message
from app.lexi.feedback import get_feedback_context
from app.lexi.scheduling_state import get_active_sessions, init_scheduling_tables
from app.lexi.agents import base as base_agent
from app.lexi.agents import (
    calendar_agent,
    email_agent,
    scheduling_agent,
    task_agent,
)
from app.lexi.persona import get_system_prompt

logger = logging.getLogger(__name__)

_GENERAL_TOOLS = [
    "OUTLOOK_GET_MESSAGE",
    "OUTLOOK_LIST_MESSAGES",
    "OUTLOOK_SEARCH_MESSAGES",
    "OUTLOOK_CREATE_DRAFT",
    "OUTLOOK_CREATE_DRAFT_REPLY",
    "OUTLOOK_SEND_DRAFT",
    "OUTLOOK_GET_CALENDAR_VIEW",
    "OUTLOOK_CREATE_ME_EVENT",
    "OUTLOOK_UPDATE_EVENT",
    "OUTLOOK_DELETE_EVENT",
]


def _get_session_messages(session_id: str) -> list[ChatCompletionMessageParam]:
    """Load clean conversation history (tool messages stripped)."""
    return get_session_history(session_id, limit=20)


def _build_active_holds_context(session_id: str) -> str:
    try:
        sessions = get_active_sessions(session_id)
        if not sessions:
            return ""
        import json
        lines = ["Active scheduling holds on calendar:"]
        for s in sessions:
            slots = s.get("offered_slots") or json.loads(s.get("offered_slots_json") or "[]")
            lines.append(f"  Contact: {s['contact_name']} | {len(slots)} hold(s)")
            for i, slot in enumerate(slots, 1):
                lines.append(f"    Option {i}: {slot.get('start','?')} – {slot.get('end','?')}")
        return "\n".join(lines)
    except Exception:
        return ""


def chat(
    user_message: str,
    session_id: str,
    channel: str = "web",
) -> str:
    """
    Main entry point. Routes to the right subagent and returns Lexi's reply.
    Wraps everything in a top-level try/except so the webhook never 500s.
    """
    try:
        return _dispatch(user_message, session_id, channel)
    except Exception as exc:
        logger.exception("Unhandled error in Lexi dispatch (session=%s): %s", session_id, exc)
        fallback = (
            "I hit a technical snag on that one. "
            "Please try again — or rephrase what you need."
        )
        try:
            save_message(session_id, "assistant", fallback, channel=channel)
        except Exception:
            pass
        return fallback


def _dispatch(user_message: str, session_id: str, channel: str) -> str:
    try:
        init_scheduling_tables()
    except Exception:
        pass

    save_message(session_id, "user", user_message, channel=channel)

    history = _get_session_messages(session_id)
    holds_ctx = _build_active_holds_context(session_id)
    feedback_ctx = get_feedback_context(limit=4)

    decision = classify(user_message)
    logger.info(
        "Routing session=%s intent=%s secondary=%s task=%s",
        session_id, decision.primary, decision.secondary, decision.needs_task
    )

    # Build the user-turn messages for the subagents
    # Include conversation history so agents have context
    agent_messages: list[ChatCompletionMessageParam] = [
        *history,
        {"role": "user", "content": user_message},
    ]

    # Extra context shared across subagents
    extra = []
    if holds_ctx:
        extra.append(holds_ctx)
    if feedback_ctx:
        extra.append(feedback_ctx)
    extra_context = "\n\n".join(extra)

    result = _run_primary(decision.primary, agent_messages, extra_context)

    # Chain secondary agents if needed (e.g. calendar + email)
    for secondary in decision.secondary:
        secondary_ctx = f"Primary agent result:\n{result}\n\n{extra_context}"
        secondary_result = _run_primary(secondary, agent_messages, secondary_ctx)
        result = f"{result}\n\n{secondary_result}"

    # Create Asana reservation task if needed
    if decision.needs_task and task_agent.is_available():
        try:
            task_ctx = f"Meeting just confirmed:\n{result}"
            task_result = task_agent.run(agent_messages, task_ctx)
            result = f"{result}\n\n{task_result}"
        except Exception as exc:
            logger.warning("Task agent failed: %s", exc)

    save_message(session_id, "assistant", result, channel=channel)
    return result


def _run_primary(intent: str, messages: list[ChatCompletionMessageParam], ctx: str) -> str:
    """Dispatch to the correct specialized agent."""
    if intent == "calendar":
        return calendar_agent.run(messages, ctx)
    elif intent == "email":
        return email_agent.run(messages, ctx)
    elif intent == "scheduling":
        return scheduling_agent.run(messages, ctx)
    elif intent == "confirm_hold":
        return scheduling_agent.run(messages, ctx)
    elif intent == "task":
        return task_agent.run(messages, ctx)
    else:
        # General: use the full persona + all tools (fallback for complex/ambiguous)
        return _run_general(messages, ctx)


def _run_general(
    messages: list[ChatCompletionMessageParam],
    extra_context: str,
) -> str:
    """Fallback general agent with full persona and all tools."""
    feedback_ctx = get_feedback_context(limit=4)
    system_prompt = get_system_prompt(feedback_context=feedback_ctx)
    if extra_context:
        system_prompt += f"\n\n{extra_context}"
    return base_agent.run_agent(system_prompt, messages, _GENERAL_TOOLS, max_rounds=6)
