# Lexi via Hermes — Quick Start

**Full plan:** [FINAL_ARCHITECTURE_AND_DEPLOYMENT.md](./FINAL_ARCHITECTURE_AND_DEPLOYMENT.md)  
**Teams setup:** [TEAMS_HERMES_CONNECT.md](./TEAMS_HERMES_CONNECT.md)

## One-sentence model

**Hermes orchestrates (Claude). Lexi executes accurately (rules + Composio + audit). One Teams chat.**

## Production Teams setup

1. Azure Bot **messaging endpoint** → `https://<public-host>/api/messages` on **Hermes :3978** only.
2. Same `TEAMS_CLIENT_ID` / secret in `~/.hermes/.env` **and** project `.env` (for proactive cards).
3. Lexi worker runs **inside** `hermes_mcp_server.py` — no `uvicorn :8000`.

```bash
hermes gateway run --replace          # :3978 Teams + MCP + Lexi worker
ngrok http 3978                       # point Azure here
```

Optional Composio webhook (instead of inbox poll):

```bash
.venv/bin/python -m app.worker --webhook   # :8780/webhooks/composio
```

## Mac testing (no Teams)

```bash
cd /path/to/AI_Scheduling_Agent && hermes
```

## Verify

```bash
.venv/bin/python scripts/test_mcp_tools.py
.venv/bin/python scripts/verify_pre_kory_switch.py
```

## Lexi MCP only for scheduling

```bash
.venv/bin/python scripts/setup_hermes_mcp.py
```

1. **Lexi MCP** (`hermes_mcp_server.py`) — scheduling, Kory rules, approvals, worker.
2. **Composio MCP** — rare Outlook ops only (accept invite, attachments). Not for scheduling.

**Routing:** calendar/email/scheduling → `lexi_*` first.

## Key MCP tools (Hermes)

| Tool | When |
|------|------|
| `lexi_register_teams_conversation` | First DM — enables approval cards |
| `lexi_handle_teams_command` | `approve`, `reject`, `draft`, `pending` |
| `lexi_get_inbound_reply_queue` | New emails awaiting yes/no |
| `lexi_begin_draft_reply` | After Kory says yes |
| `approve_decision` | Send approved draft |

## Inbound email flow

Every email → worker triage → Teams card → Kory yes → draft → approve → sandbox send.

## Instructions for Hermes

Load `agent_instructions.txt` or `agent_prefill_messages.json` in session.
