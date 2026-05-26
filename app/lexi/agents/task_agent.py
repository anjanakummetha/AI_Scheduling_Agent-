"""
Task subagent — creates Asana tasks for reservations and follow-ups.
Triggered automatically for coffee/happy hour/dinner meetings.
"""

from __future__ import annotations

from openai.types.chat import ChatCompletionMessageParam

from app.lexi.agents.base import run_agent, load_tools

_TOOLS = [
    "ASANA_CREATE_A_TASK",
    "ASANA_GET_WORKSPACES",
    "ASANA_GET_PROJECTS",
]

_SYSTEM = """You are Lexi's task specialist. Your only job is creating Asana tasks.

RESERVATION TASKS:
When a coffee, happy hour, or dinner meeting is confirmed:
1. Get the workspace ID first using ASANA_GET_WORKSPACES (use the first workspace)
2. Create a task with ASANA_CREATE_A_TASK:
   - name: "Make reservation — [Venue] — [Day] [Time]"
   - notes: venue name, date/time, party size (default 2), special notes
     For happy hour: "Bar booth for 2. Hard end 6 PM."
     For coffee: "Table for 2."
   - due_on: the day BEFORE the meeting (YYYY-MM-DD format)

FOLLOW-UP TASKS:
When asked to track a follow-up:
1. Create task: "Follow up with [Name] re: [topic]"
2. Due: specified date or 2 days from now

Always confirm the task was created with its name and due date.
"""


def is_available() -> bool:
    """Check if Asana tools are loaded (account connected)."""
    return bool(load_tools(["ASANA_CREATE_A_TASK"]))


def run(
    messages: list[ChatCompletionMessageParam],
    extra_context: str = "",
) -> str:
    if not is_available():
        return "Asana is not connected — skipping reservation task. Connect at /setup."
    prompt = _SYSTEM
    if extra_context:
        prompt += f"\n\nCONTEXT:\n{extra_context}"
    return run_agent(prompt, messages, _TOOLS, max_rounds=3)
