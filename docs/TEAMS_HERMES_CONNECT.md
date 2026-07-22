> ⚠️ **Superseded for production by `deploy/README.md`.** This doc describes the
> local/ngrok pilot wiring. For the VPS deploy, the Azure messaging endpoint points at
> `https://srv1686061.hstgr.cloud/api/messages` (Caddy → `lexi-gateway.service` on :3978),
> not ngrok. Use this doc only for the Azure Bot / Hermes concepts and local testing.

# Connect Teams + Azure → Hermes → Lexi (Hermes-only)

**Pilot:** read Kory Outlook, write sandbox mailbox, **no send without Kory approval**.

## Architecture (single Teams connection)

```text
Teams  →  Azure Bot  →  Hermes :3978/api/messages
                           →  Lexi MCP (hermes_mcp_server.py)
                                 →  Lexi worker (orchestrator, embedded)
                                 →  rules + lexi.db + Composio
                           →  Proactive Adaptive Cards (same bot DM)
```

- **Do not** point Azure at Lexi FastAPI (`app/main.py`).
- **Do not** run `uvicorn` on :8000 for production.

## Step 1 — Azure Bot

1. Azure Portal → your Bot → **Configuration**
2. **Messaging endpoint:** `https://<public-host>/api/messages` (Hermes gateway, TLS required)
3. Copy **Microsoft App ID** → `TEAMS_CLIENT_ID`
4. **Manage password** → new secret → `TEAMS_CLIENT_SECRET`
5. **App Registration** → Directory (tenant) ID → `TEAMS_TENANT_ID`
6. Kory’s AAD object ID → `TEAMS_ALLOWED_USERS`

## Step 2 — Credentials

**`~/.hermes/.env`** (Hermes gateway):

```bash
TEAMS_CLIENT_ID=...
TEAMS_CLIENT_SECRET=...
TEAMS_TENANT_ID=...
TEAMS_ALLOWED_USERS=<kory-azure-object-id>
ANTHROPIC_API_KEY=...
```

**Project `.env`** (Lexi worker + proactive cards — same bot app):

```bash
TEAMS_CLIENT_ID=...          # same as Hermes
TEAMS_CLIENT_SECRET=...
TEAMS_TENANT_ID=...
TEAMS_CONVERSATION_ID=       # set after Step 5
LEXI_TEAMS_ENABLED=true
LEXI_TEAMS_TEXT_ONLY=false   # Adaptive Cards on
```

## Step 3 — Lexi MCP in Hermes

```bash
cd AI_Scheduling_Agent
.venv/bin/python scripts/setup_hermes_mcp.py
```

Merge output into `~/.hermes/config.yaml`. Load `agent_instructions.txt` in Hermes.

The MCP server **auto-starts** the Lexi worker (`LEXI_EMBED_WORKER=true` default):
- **Production:** Composio webhook → `:8780/webhooks/composio` (no idle inbox polling)
- **Optional:** backup poll every 30m (`LEXI_ORCHESTRATOR_BACKUP_POLL_MINUTES=30`)
- **Local dev only:** `LEXI_ORCHESTRATOR_POLL_OUTLOOK=true` if you cannot expose a webhook

## Step 4 — Run (local, no VPS)

```bash
# Terminal 1 — Hermes (Teams + MCP + embedded Lexi worker + webhook on :8780)
hermes gateway run --replace

# Terminal 2 — expose webhook for Composio (local testing only)
ngrok http 8780
# Set LEXI_WEBHOOK_PUBLIC_URL=https://<ngrok-host>
# .venv/bin/python scripts/register_composio_webhook.py
```

Production ingress env:

```bash
LEXI_WEBHOOK_ENABLED=true
LEXI_WEBHOOK_PORT=8780
LEXI_WEBHOOK_PUBLIC_URL=https://your-stable-host.example.com
LEXI_ORCHESTRATOR_POLL_OUTLOOK=false
LEXI_ORCHESTRATOR_BACKUP_POLL_MINUTES=30
```

Register with Composio (once per stable URL):

```bash
.venv/bin/python scripts/register_composio_webhook.py
.venv/bin/python scripts/ensure_outlook_trigger.py
.venv/bin/python scripts/verify_webhook_ingress.py
```

## Step 5 — Wire Teams conversation (for cards)

After Kory messages Hermes in Teams once:

1. Hermes calls `lexi_register_teams_conversation(conversation_id, service_url)`  
   OR set `TEAMS_CONVERSATION_ID` in project `.env` from `/sethome` / Hermes logs.

2. Verify: `lexi_get_system_status` → `teams_cards_ready: true`

## Step 6 — Verify

```bash
.venv/bin/python scripts/verify_pre_kory_switch.py
.venv/bin/python scripts/test_approval_safety.py
.venv/bin/python scripts/test_mcp_tools.py
```

In Teams (Hermes chat):

- `lexi_get_system_status` — worker running, write mode sandbox
- `lexi_get_inbound_reply_queue` — emails awaiting draft yes/no
- Card **Approve** / **Reject** posts `approve N` to chat → Hermes calls `lexi_handle_teams_command`

## Approval flow

1. New Kory email → worker triages → **Adaptive Card** in Hermes DM: “Should I draft a reply?”
2. Kory: `draft <id> yes` → Hermes → `lexi_begin_draft_reply` → approval card
3. Kory: **Approve** on card or `approve <id> option 1` → `execute_lexi_approval`

Safety (`.env`):

- `LEXI_REQUIRE_KORY_APPROVAL=true`
- `LEXI_AUTO_EXECUTE_ENABLED=false`
- `LEXI_ALLOW_IMMEDIATE_SEND=false`
- `LEXI_WRITE_MODE=sandbox` until UAT

## Hermes command routing

When Kory sends structured commands (`approve`, `reject`, `draft`, `pending`, `inbound`):

→ Hermes calls **`lexi_handle_teams_command`** first before free-form chat.

## Before switching write to Kory’s mailbox

1. Full UAT on sandbox loopback
2. `LEXI_WRITE_MODE=kory`
3. Re-run `verify_pre_kory_switch.py`

## Optional debug dashboard

```bash
LEXI_DASHBOARD_ENABLED=true .venv/bin/uvicorn app.main:create_app --factory --port 8080
```

Not used for Teams or email ingress.
