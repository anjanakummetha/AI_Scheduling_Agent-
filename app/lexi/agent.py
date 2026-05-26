"""
Lexi agent: Hermes/Claude via OpenRouter + Composio tools.
Full agentic loop with scheduling state, feedback context, and Kory's rules.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import OpenAI, NotFoundError
from openai.types.chat import ChatCompletionMessageParam

from app.config import settings
from app.lexi.persona import get_system_prompt
from app.lexi.sessions import get_session_history, save_message
from app.lexi.feedback import get_feedback_context
from app.lexi.scheduling_state import get_active_sessions, init_scheduling_tables

logger = logging.getLogger(__name__)

_OUTLOOK_TOOLS = [
    "OUTLOOK_GET_MESSAGE",
    "OUTLOOK_CREATE_DRAFT_REPLY",
    "OUTLOOK_SEND_DRAFT",
    "OUTLOOK_GET_CALENDAR_VIEW",
    "OUTLOOK_CREATE_ME_EVENT",
    "OUTLOOK_LIST_MESSAGES",
    "OUTLOOK_SEARCH_MESSAGES",
    "OUTLOOK_DELETE_EVENT",
    "OUTLOOK_UPDATE_EVENT",
]

_MAX_TOOL_ROUNDS = 8


def _get_llm_client() -> OpenAI:
    return OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)


def _load_composio_tools() -> list[dict[str, Any]]:
    if not settings.composio_api_key:
        return []
    try:
        from composio import Composio
        from composio.sdk import OpenAIProvider

        provider = OpenAIProvider()
        composio = Composio(api_key=settings.composio_api_key, provider=provider)
        tools = composio.tools.get(
            user_id=settings.composio_user_id,
            tools=_OUTLOOK_TOOLS,
        )
        return list(tools) if tools else []
    except Exception as exc:
        logger.warning("Composio tools unavailable: %s", exc)
        return []


def _execute_composio_tool(tool_name: str, arguments: dict[str, Any]) -> str:
    try:
        from app.integrations.composio_client import execute_tool
        result = execute_tool(tool_name, arguments)
        return json.dumps(result)
    except Exception as exc:
        logger.error("Tool execution failed for %s: %s", tool_name, exc)
        return json.dumps({"error": str(exc)})


def _call_llm(
    client: OpenAI,
    messages: list[ChatCompletionMessageParam],
    tools: list[dict[str, Any]],
) -> Any:
    kwargs: dict[str, Any] = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 2000,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    try:
        return client.chat.completions.create(**kwargs)
    except NotFoundError as exc:
        if tools and ("tool" in str(exc).lower() or "endpoint" in str(exc).lower()):
            logger.warning("Model %s does not support tool use. Retrying without tools.", settings.llm_model)
            kwargs.pop("tools", None)
            kwargs.pop("tool_choice", None)
            return client.chat.completions.create(**kwargs)
        raise


def _build_scheduling_context(chat_session_id: str) -> str:
    """Build a summary of active scheduling sessions to inject into context."""
    try:
        sessions = get_active_sessions(chat_session_id)
        if not sessions:
            return ""
        lines = ["\n--- ACTIVE SCHEDULING HOLDS ---"]
        for s in sessions:
            slots = s.get("offered_slots") or json.loads(s.get("offered_slots_json") or "[]")
            hold_ids = s.get("hold_event_ids") or json.loads(s.get("hold_event_ids_json") or "[]")
            lines.append(
                f"• Contact: {s['contact_name']} ({s['meeting_type']}) — "
                f"Status: {s['status']} — "
                f"{len(slots)} holds placed (IDs: {', '.join(hold_ids[:3])})"
            )
            for i, slot in enumerate(slots, 1):
                start = slot.get("start", "?")
                end = slot.get("end", "?")
                lines.append(f"  Option {i}: {start} – {end}")
        lines.append("--- END ACTIVE HOLDS ---\n")
        return "\n".join(lines)
    except Exception as exc:
        logger.warning("Could not build scheduling context: %s", exc)
        return ""


def chat(
    user_message: str,
    session_id: str,
    channel: str = "web",
) -> str:
    """
    Process a user message and return Lexi's reply.
    Includes: Kory's rules, active hold state, feedback context, full agentic tool loop.
    """
    try:
        init_scheduling_tables()
    except Exception:
        pass

    save_message(session_id, "user", user_message, channel=channel)

    history = get_session_history(session_id, limit=30)
    tools = _load_composio_tools()

    feedback_ctx = get_feedback_context(limit=6)
    sched_ctx = _build_scheduling_context(session_id)

    system_prompt = get_system_prompt(feedback_context=feedback_ctx)
    if sched_ctx:
        system_prompt += sched_ctx

    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": system_prompt},
        *history,
    ]

    client = _get_llm_client()

    for _ in range(_MAX_TOOL_ROUNDS):
        response = _call_llm(client, messages, tools)
        assistant_msg = response.choices[0].message

        if not assistant_msg.tool_calls:
            reply_text = assistant_msg.content or ""
            save_message(session_id, "assistant", reply_text, channel=channel)
            return reply_text

        tool_calls_data = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in assistant_msg.tool_calls
        ]
        save_message(
            session_id, "assistant", assistant_msg.content or "",
            channel=channel, tool_calls=tool_calls_data,
        )
        messages.append({
            "role": "assistant",
            "content": assistant_msg.content or "",
            "tool_calls": tool_calls_data,
        })

        for tc in assistant_msg.tool_calls:
            args = json.loads(tc.function.arguments or "{}")
            tool_result = _execute_composio_tool(tc.function.name, args)
            save_message(session_id, "tool", tool_result, channel=channel)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": tool_result,
            })

    final_resp = _call_llm(client, messages, [])
    reply_text = final_resp.choices[0].message.content or ""
    save_message(session_id, "assistant", reply_text, channel=channel)
    return reply_text
