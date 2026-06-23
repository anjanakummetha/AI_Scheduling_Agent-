#!/usr/bin/env python3
"""Print Hermes MCP configuration: Lexi only (no Composio MCP catalog).

Usage:
    .venv/bin/python scripts/setup_hermes_mcp.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "hermes_mcp_server.py"


def main() -> None:
    lexi_server = {
        "command": str(ROOT / ".venv" / "bin" / "python"),
        "args": [str(SERVER)],
        "env": {
            "PYTHONPATH": str(ROOT),
        },
    }

    json_snippet = {
        "mcpServers": {
            "lexi-scheduling": lexi_server,
        }
    }

    yaml_hint = f"""# Merge into ~/.hermes/config.yaml
# PRODUCTION: Lexi MCP ONLY — do NOT add composio MCP (rate limit / token bloat)

mcp:
  servers:
    lexi-scheduling:
      command: "{lexi_server['command']}"
      args:
        - "{SERVER}"
      env:
        PYTHONPATH: "{ROOT}"

# Recommended Hermes settings:
# compression: enabled
# session_reset: idle 1440min, at_hour 4
"""

    print("=== Hermes + Lexi MCP (slim — no Composio MCP) ===\n")
    print("1) Add Lexi MCP only:\n")
    print(yaml_hint)
    print("\n2) Or merge this JSON:\n")
    print(json.dumps(json_snippet, indent=2))
    print(
        "\n3) Load agent_instructions.txt in Hermes.\n"
        "\nTool routing:\n"
        "  • All scheduling/calendar/mail → lexi_* tools\n"
        "  • Rare Outlook slugs → lexi_execute_outlook_action (not Composio MCP)\n"
        "\nInbound email:\n"
        "  • Delegation (CC Lexi) → auto-draft + Teams approval card\n"
        "  • Other mail → silent triage; Kory asks in chat\n"
        "\nVerify (no API):\n"
        f'  cd "{ROOT}"\n'
        "  .venv/bin/python scripts/verify_read_only_deploy.py\n"
        "  .venv/bin/python scripts/test_mcp_tools.py\n"
    )


if __name__ == "__main__":
    main()
