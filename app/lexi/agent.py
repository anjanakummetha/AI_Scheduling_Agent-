"""Lexi agent: Hermes 4 70B via OpenRouter + Composio tools, agentic loop."""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import OpenAI, NotFoundError
from openai.types.chat import ChatCompletionMessageParam

from app.config import settings
from app.lexi.persona import get_system_prompt
from app.lexi.sessions import get_session_history, save_message

logger = logging.getLogger(__name__)

_OUTLOOK_TOOLS = [
    "OUTLOOK_GET_MESSAGE",
    "OUTLOOK_CREATE_DRAFT_REPLY",
    "OUTLOOK_SEND_DRAFT",
    "OUTLOOK_GET_CALENDAR_VIEW",
    "OUTLOOK_CREATE_ME_EVENT",
    "OUTLOOK_LIST_MESSAGES",
    "OUTLOOK_SEARCH_MESSAGES",
]

_MAX_TOOL_ROUNDS = 6


def _get_llm_client() -> OpenAI:
    return OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)


def _load_composio_tools() -> list[dict[str, Any]]:
    """Return Composio Outlook tools as OpenAI function schemas.

    Returns an empty list if Composio is not configured or the key is invalid.
    """
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
    """Execute a Composio tool and return JSON string result."""
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
    """
    Call the LLM. If the model doesn't support tool use (404 from OpenRouter),
    automatically retry without tools so conversation still works.
    """
    kwargs: dict[str, Any] = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 1500,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    try:
        return client.chat.completions.create(**kwargs)
    except NotFoundError as exc:
        # Model doesn't support tool use on this provider — retry without tools
        if tools and ("tool" in str(exc).lower() or "endpoint" in str(exc).lower()):
            logger.warning(
                "Model %s does not support tool use on this provider. "
                "Retrying without tools. Connect Outlook once the model supports function calling.",
                settings.llm_model,
            )
            kwargs.pop("tools", None)
            kwargs.pop("tool_choice", None)
            return client.chat.completions.create(**kwargs)
        raise


def chat(
    user_message: str,
    session_id: str,
    channel: str = "web",
) -> str:
    """
    Process a user message within a session and return Lexi's reply.

    Handles the full agentic loop: LLM → tool calls → execute → LLM → reply.
    Persists all messages to the chat_messages table.
    """
    save_message(session_id, "user", user_message, channel=channel)

    history = get_session_history(session_id, limit=30)
    tools = _load_composio_tools()

    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": get_system_prompt()},
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
            session_id,
            "assistant",
            assistant_msg.content or "",
            channel=channel,
            tool_calls=tool_calls_data,
        )
        messages.append(
            {
                "role": "assistant",
                "content": assistant_msg.content or "",
                "tool_calls": tool_calls_data,
            }
        )

        for tc in assistant_msg.tool_calls:
            args = json.loads(tc.function.arguments or "{}")
            tool_result = _execute_composio_tool(tc.function.name, args)
            save_message(session_id, "tool", tool_result, channel=channel)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_result,
                }
            )

    final_resp = _call_llm(client, messages, tools)
    reply_text = final_resp.choices[0].message.content or ""
    save_message(session_id, "assistant", reply_text, channel=channel)
    return reply_text
