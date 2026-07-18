# Local Mac testing (Kory live inbox)

Use this while fixing issues on your Mac. Redeploy to the VPS when stable.

## Safety rules

1. **Stop the VPS worker first** — only one machine should process Kory's mail at a time.
2. **Subject line must include `TEST`** on every test email.
3. **From:** `anjana.kummetha@iconicfounders.com` only.
4. **Sends and calendar writes** still require Kory approval in Teams (`LEXI_REQUIRE_KORY_APPROVAL=true`).
5. **Local DB** is `data/lexi_local.db` — does not touch VPS proposal history.

## One-time switch (already in `.env`)

```bash
LEXI_LOCAL_MODE=true
LEXI_DATABASE_PATH=data/lexi_local.db
```

Kory read + write connections stay on production Composio accounts. Approval gates stay on.

## Start

```bash
cd "/Users/anjanakummetha/Downloads/IFG 2026 Summer Internship/AI_Scheduling_Agent"
chmod +x scripts/start_local_mac.sh
./scripts/start_local_mac.sh
```

### Terminal A — Hermes (Teams chat + MCP tools)

```bash
hermes gateway run --replace
```

### Terminal B — ngrok for Teams

```bash
ngrok http 3978
```

In **Azure Bot** → Configuration → Messaging endpoint:

```text
https://<your-ngrok-host>/api/messages
```

Revert to the VPS URL when you redeploy.

### Terminal C — inbound email

```bash
.venv/bin/python scripts/listen_outlook_local.py
```

This subscribes to Composio's Outlook trigger for Kory's mailbox. No VPS webhook needed while testing locally.

### Stop VPS (required)

```bash
ssh lexi@2.24.111.64 'sudo systemctl stop lexi-hermes'
```

## Verify connection

In Teams (after ngrok + Azure update), message Lexi:

```text
What is your status? Check lexi_get_system_status.
```

Expect: `lexi_local` database path, worker running, approval required.

## Test email template

**To:** Kory's inbox  
**From:** anjana.kummetha@iconicfounders.com  
**Subject:** `TEST — 30-min intro call next week`  
**Body:** Ask to schedule a short call; offer no fixed times (let Lexi propose).

Watch Terminal C for trigger logs → Teams for notification/card.

## Scheduling UAT (prospect → Kory → Lexi)

You play the **person who wants to meet Kory**. Kory loops in Lexi (CC `lexi@iconicfounders.com`). With `delegation_only` notify mode, Lexi will **not** ping Teams on your prospect email alone — only after Kory delegates.

### Step 1 — You (prospect) email Kory

**From:** `anjana.kummetha@iconicfounders.com`  
**To:** Kory’s inbox — **do not CC Lexi**  
**Subject:** `TEST — 30-min intro call next week`  
**Body:** e.g. “Hi Kory — would love to find 30 minutes for an intro call. What works on your end?”

Lexi ingests and triages quietly (no Teams card yet).

### Step 2 — Kory loops in Lexi

From **Kory’s mailbox**, reply on that thread and **CC:** `lexi@iconicfounders.com`  
**Body:** e.g. “Looping in Lexi — she’ll help us find a time.”

Expected: Teams card with editable draft (Lexi voice) → **Send offer** → email from `lexi@` to you (Kory CC’d) → holds after send.

### Step 3 — You (prospect) pick a time

Reply to Lexi’s offer (“Option 1 works”) → Teams **Send calendar invite?** → approve → Outlook invite.

### Optional — Kory voice

Before approving **Send offer**, ask Hermes: `lexi_begin_draft_reply(<proposal_id>, voice_mode=kory)`.

### “None of the times work”

Reply “None of those times work — any other options?” → Teams **Find new times?** card.

## Production-level settings (your Mac `.env`)

These should be set for real sends (not sandbox loopback):

```bash
LEXI_DRY_RUN=false
LEXI_WRITE_MODE=kory
SANDBOX_EMAIL_LOOPBACK=false
LEXI_KORY_OUTBOUND_BLOCKED=false
LEXI_REQUIRE_KORY_APPROVAL=true
LEXI_DELEGATION_AUTO_DRAFT=true
LEXI_TEAMS_INBOUND_NOTIFY_MODE=delegation_only
```

Quick start all services:

```bash
chmod +x scripts/start_uat_test.sh
./scripts/start_uat_test.sh
```

## Switch back to VPS

1. Stop local Hermes + `listen_outlook_local.py` (Ctrl+C).
2. Restore Azure Bot URL → `https://srv1686061.hstgr.cloud/api/messages`
3. On VPS: `sudo systemctl start lexi-hermes`
4. In `.env` on VPS (not Mac): remove `LEXI_LOCAL_MODE`, use `data/lexi.db`

## What runs where

| Action | Mac local | VPS production |
|--------|-----------|----------------|
| Code fixes | Yes | rsync + restart |
| Teams chat | ngrok → Mac :3978 | Traefik → VPS :3978 |
| Inbound email | `listen_outlook_local.py` | Composio webhook :8780 |
| SQLite proposals | `data/lexi_local.db` | `data/lexi.db` |
