"""LLM client for triage/scheduler/comms — native Anthropic SDK (plan Phase 3).

Migrated off the OpenAI-compatible endpoint so we can use prompt caching
(cache_control) and read cache-hit usage. The public surface is a thin
OpenAI-shaped shim (`client.chat.completions.create(...)` →
`response.choices[0].message.content`) so the existing call sites are unchanged,
while under the hood we get:

  - prompt caching on the (stable) system prompt — big saving on per-email triage;
  - a per-call max_tokens cap (previously unbounded);
  - per-role model tiering via resolve_llm_model_for_role;
  - thinking disabled for these classification/drafting tasks (the deterministic
    engine does the reasoning) to hold down latency and token cost;
  - per-call cost logging to the llm_cost_log table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import (
    resolve_llm_max_tokens_for_role,
    resolve_llm_model_for_role,
    settings,
)


# --- OpenAI-shaped response adapters (so call sites don't change) ------------
@dataclass
class _Message:
    content: str


@dataclass
class _Choice:
    message: _Message


@dataclass
class _Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass
class _Response:
    choices: list[_Choice]
    usage: _Usage
    model: str


def _supports_thinking_disabled(model: str) -> bool:
    # Haiku 4.5 and Fable 5 reject an explicit {type: "disabled"} (Fable) or use a
    # different thinking model (Haiku) — omit thinking for those; disable for the rest.
    m = model.lower()
    return not ("haiku" in m or "fable" in m)


def _split_system(messages: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    system_blocks: list[dict] = []
    convo: list[dict] = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        if role == "system":
            if isinstance(content, str) and content.strip():
                system_blocks.append({"type": "text", "text": content})
        else:
            convo.append({"role": role, "content": content})
    # Cache the (stable) system prompt: one breakpoint on the last block.
    if system_blocks:
        system_blocks[-1] = {**system_blocks[-1], "cache_control": {"type": "ephemeral"}}
    return system_blocks, convo


class _Completions:
    def create(
        self,
        *,
        model: str | None = None,
        messages: list[dict[str, Any]],
        role: str = "drafting",
        max_tokens: int | None = None,
        temperature: float | None = None,  # accepted but ignored (unsupported on modern models)
        **_ignored: Any,
    ) -> _Response:
        import anthropic

        resolved_model = model or resolve_llm_model_for_role(role)
        cap = max_tokens or resolve_llm_max_tokens_for_role(role)
        system_blocks, convo = _split_system(messages)

        kwargs: dict[str, Any] = {
            "model": resolved_model,
            "max_tokens": cap,
            "messages": convo or [{"role": "user", "content": "."}],
        }
        if system_blocks:
            kwargs["system"] = system_blocks
        if _supports_thinking_disabled(resolved_model):
            kwargs["thinking"] = {"type": "disabled"}

        client = anthropic.Anthropic(api_key=settings.llm_api_key)
        resp = client.messages.create(**kwargs)

        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        u = resp.usage
        usage = _Usage(
            prompt_tokens=getattr(u, "input_tokens", 0) or 0,
            completion_tokens=getattr(u, "output_tokens", 0) or 0,
            cache_read_input_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            cache_creation_input_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
        )
        _log_cost(role=role, model=resolved_model, usage=usage)
        return _Response(choices=[_Choice(_Message(text))], usage=usage, model=resp.model)


class _Chat:
    def __init__(self) -> None:
        self.completions = _Completions()


class HermesClient:
    """Drop-in stand-in for the old OpenAI client (chat.completions.create surface)."""

    def __init__(self) -> None:
        self.chat = _Chat()


def get_hermes_client() -> HermesClient:
    if not settings.llm_api_key:
        raise RuntimeError(
            "No LLM API key configured. Set ANTHROPIC_API_KEY in .env "
            "(or in ~/.hermes/.env) or set LLM_API_KEY explicitly."
        )
    return HermesClient()


def _log_cost(*, role: str, model: str, usage: _Usage) -> None:
    """Best-effort cost ledger — never block a response on logging."""
    try:
        from app.storage.llm_cost_log import record_llm_call

        record_llm_call(
            role=role,
            model=model,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            cache_read_tokens=usage.cache_read_input_tokens,
            cache_creation_tokens=usage.cache_creation_input_tokens,
        )
    except Exception:
        pass
