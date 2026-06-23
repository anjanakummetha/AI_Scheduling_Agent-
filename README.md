# Kory's AI Scheduling Agent

Phase 1 — Kory approves all actions before execution.

## Files

| File | Purpose |
|---|---|
| `rules.py` | All of Kory's scheduling rules — edit this to adjust any rule |
| `prompts.py` | Builds the system prompt from rules — feeds rules to Hermes |
| `hermes_mcp_server.py` | Lexi MCP + embedded headless worker (orchestrator) |
| `app/worker/` | Optional standalone worker (`python -m app.worker`) |
| `app/main.py` | Optional debug dashboard only (`LEXI_DASHBOARD_ENABLED=true`) |
| `setup.py` | Run once to register the Outlook email trigger with Composio |
| `.env` | Your API keys and config (create from `.env.example`) |
| `logs/decisions.log` | Full log of every decision the agent makes |

---

## Setup (Do This Once)

### 1. Install dependencies
```bash
cd /Users/anjanakummetha/IEP_Project/agent
pip install -r requirements.txt
```

### 2. Create your .env file
```bash
cp .env.example .env
```
Then open `.env` and fill in:
- `COMPOSIO_API_KEY` — from your Composio dashboard → Settings → API Keys
- `COMPOSIO_USER_ID` — the user ID you used when connecting Microsoft 365

### 3. Set up LLM (Anthropic, same as Hermes)

Lexi uses **Anthropic** for email triage and scheduling (not Ollama). The Hermes CLI gateway also uses `provider: anthropic` in `~/.hermes/config.yaml`.

In `.env`, set:

```bash
ANTHROPIC_API_KEY=your_key_here
```

If the key is already in `~/.hermes/.env`, Lexi loads it automatically when `ANTHROPIC_API_KEY` is not set in the project `.env`.

Optional: `LLM_MODEL=claude-opus-4-20250514` to align with a heavier Hermes default.

### 4. Asana — Lexi Booking reminders (optional)

When Kory mentions **lunch** or **dinner** in an email (from his address or his `Let's Win, Kory` signature), Lexi creates a task on the Asana board **Lexi Booking reminders**.

In `.env` (leave blank until Composio + Asana are wired):

- `ASANA_COMPOSIO_CONNECTION_ID` — Composio `ca_...` for the Asana connection
- `ASANA_PROJECT_GID` — project GID for the board (from the Asana URL)
- `KORY_SENDER_EMAILS` — optional comma-separated Kory addresses

Until those are set, tasks are **simulated** locally (logged in `audit_log`).

### 5. Register the Outlook trigger (run once)
```bash
python setup.py
```
This tells Composio to watch Kory's Outlook inbox and notify the agent.

---

## Product architecture (Lindy-class, accuracy-first)

**Hermes** = conversational orchestrator (Teams + Mac, Claude OAuth).  
**Lexi** = execution layer (Composio, rules, proposals, audit).

**Master plan (implementation + deployment):** [docs/FINAL_ARCHITECTURE_AND_DEPLOYMENT.md](docs/FINAL_ARCHITECTURE_AND_DEPLOYMENT.md)

Quick start: [docs/hermes_lexi_assistant.md](docs/hermes_lexi_assistant.md) · Instructions: `agent_instructions.txt`

**Test everything (except Teams — connect on deploy day):**
```bash
.venv/bin/python scripts/test_kory_phase_suite.py
```
Report: [docs/TEST_RESULTS_REPORT.md](docs/TEST_RESULTS_REPORT.md) · Kory needs: [docs/KORY_AGENT_NEEDS_ANALYSIS.md](docs/KORY_AGENT_NEEDS_ANALYSIS.md)

```bash
hermes gateway run --replace   # reload MCP tools
cd /path/to/AI_Scheduling_Agent && hermes
```

MCP server: `hermes_mcp_server.py` (tools: `lexi_get_calendar_availability`, `lexi_place_calendar_hold`, …).

## Running Lexi (Hermes-only Teams)

```bash
hermes gateway run --replace   # Teams :3978 + Lexi MCP + inbound worker
```

Lexi worker (embedded in MCP by default):
1. Polls **Kory's inbox** (or Composio webhook if `python -m app.worker --webhook`)
2. Runs triage + scheduling orchestration with full rule validation
3. Pushes Adaptive Cards to the Hermes DM (same bot credentials in `.env`)
4. Exposes MCP tools to Hermes for chat commands and approvals

Optional Composio webhook:

```bash
.venv/bin/python -m app.worker --webhook   # :8780/webhooks/composio
```

Optional audit dashboard:

```bash
LEXI_DASHBOARD_ENABLED=true .venv/bin/uvicorn app.main:create_app --factory --port 8080
```

---

## Adjusting the Rules

All scheduling rules live in `rules.py`. To change any rule:
1. Open `rules.py`
2. Edit the relevant section
3. Restart Hermes gateway (`hermes gateway run --replace`)

No other files need to change when rules change.

---

## Checking the Decision Log

Every email the agent processes is logged:
```bash
cat logs/decisions.log
```

Each entry includes: timestamp, email sender, subject, proposed action summary, and whether Kory approved it.
