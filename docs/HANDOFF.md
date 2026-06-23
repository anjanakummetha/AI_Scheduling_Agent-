# Lexi pilot — agent handoff (June 2026)

Read this first when picking up the project on a new machine or Cursor account.

## What this is

**Lexi** — AI scheduling assistant for **Kory Mitchell** (IFG / Iconic Founders). Production path:

```text
Teams → Azure Bot → Hermes gateway (:3978) → Lexi MCP (hermes_mcp_server.py)
  → embedded worker (orchestrator) → rules.py + lexi DB + Composio (Kory Outlook)
  → proactive Teams Adaptive Cards for approval
```

Nothing sends to Kory's live inbox or calendar without **Kory approving in Teams** (`LEXI_REQUIRE_KORY_APPROVAL=true`).

## Read these files (in order)

1. `agent_instructions.txt` — Hermes/Lexi behavior, tool routing, delegation rules
2. `rules.py` — Kory scheduling preferences (living document)
3. `docs/TEAMS_HERMES_CONNECT.md` — Teams + Azure + Hermes wiring
4. `docs/LOCAL_MAC_TESTING.md` — local Mac testing before VPS redeploy
5. `docs/KORY_AGENT_NEEDS_ANALYSIS.md` — inbox patterns and gaps
6. `config/calendars.yaml` — calendar read/write routing

## Architecture highlights

- **Hermes-only Teams** — do not point Azure at FastAPI `app/main.py` for chat
- **Email ingress:** Composio webhook + `scripts/listen_outlook_local.py` for local dev
- **Approvals:** Teams Adaptive Cards + `execute_lexi_approval` in `app/agents/comms_agent.py`
- **Delegation:** CC `lexi@iconicfounders.com` + "looping in Lexi" → auto-draft + Teams card
- **Calendar intelligence:** `app/scheduling/calendar_intelligence.py` + `calendar_context.py`
  - Read: work `Calendar` + `Kory Master Calendar (ALL)` with kid/copy dedupe
  - Write: business → `Calendar`, personal Kory → Master
  - Horizon: default 60d, max 120d (`LEXI_CALENDAR_SEARCH_DAYS`)

## Secrets (NOT in git — copy manually)

| File | Purpose |
|------|---------|
| `.env` | Composio, Teams bot, Lexi settings |
| `~/.hermes/.env` | Hermes gateway, Anthropic, Teams home channel |
| `~/.hermes/config.yaml` | Lexi MCP server path — run `scripts/setup_hermes_mcp.py` |

## Local dev quick start

```bash
cd AI_Scheduling_Agent
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # fill in secrets
.venv/bin/python scripts/init_lexi_db.py
.venv/bin/python scripts/setup_hermes_mcp.py

# Terminal 1: Hermes
hermes gateway run --replace

# Terminal 2: ngrok for Teams (local)
ngrok http 3978

# Terminal 3: email listener
.venv/bin/python scripts/listen_outlook_local.py
```

Verify: `scripts/verify_teams_connection.py`, `scripts/verify_calendars_read.py`

## VPS (production — stop while testing locally)

- Host: `srv1686061.hstgr.cloud`, user `lexi`, service `lexi-hermes`
- Stop before local Mac tests: `sudo systemctl stop lexi-hermes`

## Current phase / next work

**Done recently:**
- Hermes + Teams proactive cards (tenant-scoped service URL fix)
- Delegation path → Teams approval cards
- Calendar intelligence module + extended read horizon
- `default_write` → work `Calendar` (not Master)

**Next (priority order):**
1. Finish calendar UAT — verify 45–60d reads vs Outlook; IFG group cals not on Composio yet
2. Test delegation email (TEST subject, CC lexi@, "looping in Lexi") → Teams card
3. Hold lifecycle: offer slots → holds on work Calendar → release on reply → invite
4. Meeting-type routing (Teams link vs coffee address, travel buffers)
5. Redeploy to VPS when local UAT passes

## Safety

- TEST in subject for local test emails when `LEXI_LOCAL_MODE=true`
- Do not auto-send; Kory approves every send/hold/booking in Teams
- Do not commit `.env` or API keys
