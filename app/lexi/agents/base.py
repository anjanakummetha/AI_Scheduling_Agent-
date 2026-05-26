"""Shared agent runner used by all Lexi subagents."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from openai import OpenAI, NotFoundError
from openai.types.chat import ChatCompletionMessageParam

from app.config import settings

logger = logging.getLogger(__name__)

_LLM_TIMEOUT = 50
_MAX_TOOL_ROUNDS = 5

# Process-level tool schema cache: slug list → schema list, refreshed every 5 min
_schema_cache: dict[str, tuple[list, float]] = {}
_CACHE_TTL = 300


def get_llm_client() -> OpenAI:
    return OpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        timeout=_LLM_TIMEOUT,
    )


def load_tools(tool_slugs: list[str]) -> list[dict[str, Any]]:
    """Load Composio tool schemas for the given slugs, using a 5-min cache."""
    if not settings.composio_api_key or not tool_slugs:
        return []

    cache_key = ",".join(sorted(tool_slugs))
    cached = _schema_cache.get(cache_key)
    if cached and (time.monotonic() - cached[1]) < _CACHE_TTL:
        return cached[0]

    try:
        from composio import Composio
        from composio.sdk import OpenAIProvider

        composio = Composio(api_key=settings.composio_api_key, provider=OpenAIProvider())
        tools = list(composio.tools.get(user_id=settings.composio_user_id, tools=tool_slugs) or [])
        _schema_cache[cache_key] = (tools, time.monotonic())
        return tools
    except Exception as exc:
        logger.warning("Tool load failed for %s: %s", tool_slugs[:2], exc)
        return []


def execute_tool(tool_name: str, arguments: dict[str, Any]) -> str:
    try:
        from app.integrations.composio_client import execute_tool as _exec
        return json.dumps(_exec(tool_name, arguments))
    except Exception as exc:
        logger.error("Tool %s error: %s", tool_name, exc)
        return json.dumps({"error": str(exc), "tool": tool_name})


def run_agent(
    system_prompt: str,
    messages: list[ChatCompletionMessageParam],
    tool_slugs: list[str],
    max_rounds: int = _MAX_TOOL_ROUNDS,
) -> str:
    """
    Core agentic loop. Runs the LLM with Composio tools until a text reply is produced.
    Returns the assistant's final text response.
    """
    tools = load_tools(tool_slugs)
    client = get_llm_client()

    full_messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": system_prompt},
        *messages,
    ]

    for round_num in range(max_rounds):
        kwargs: dict[str, Any] = {
            "model": settings.llm_model,
            "messages": full_messages,
            "temperature": 0.2,
            "max_tokens": 4096,  # must be large enough for tool call JSON arguments
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        try:
            response = client.chat.completions.create(**kwargs)
        except NotFoundError as exc:
            if tools and ("tool" in str(exc).lower() or "endpoint" in str(exc).lower()):
                logger.warning("Model does not support tool use; retrying without tools.")
                kwargs.pop("tools", None)
                kwargs.pop("tool_choice", None)
                response = client.chat.completions.create(**kwargs)
            else:
                raise

        msg = response.choices[0].message

        if not msg.tool_calls:
            return msg.content or ""

        # Execute all tool calls in this round
        full_messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ],
        })

        for tc in msg.tool_calls:
            raw_args = tc.function.arguments or "{}"
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError:
                # Strip markdown code fences if model wrapped them
                cleaned = raw_args.strip()
                if cleaned.startswith("```"):
                    cleaned = "\n".join(
                        l for l in cleaned.splitlines()
                        if not l.strip().startswith("```")
                    ).strip()
                try:
                    args = json.loads(cleaned)
                except json.JSONDecodeError:
                    # Last resort: try ast.literal_eval for Python-style dicts
                    import ast
                    try:
                        args = ast.literal_eval(cleaned)
                    except Exception:
                        logger.warning("Could not parse tool args for %s: %r", tc.function.name, raw_args[:100])
                        args = {}
            logger.info("[%s] round=%d tool=%s", system_prompt[:20].strip(), round_num + 1, tc.function.name)
            result = execute_tool(tc.function.name, args)
            full_messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

    # Force a final text answer
    kwargs.pop("tools", None)
    kwargs.pop("tool_choice", None)
    kwargs["messages"] = full_messages
    final = client.chat.completions.create(**kwargs)
    return final.choices[0].message.content or ""
