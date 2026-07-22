# Live Teams UAT — Runbook

Test Lexi directly in Microsoft Teams over a temporary ngrok tunnel, in a **safe
posture**: sends are dry-run (nothing real leaves any mailbox), Teams approval
cards still push so the UX works, Kory's Outlook/calendar stay read-only, Kory is
never CC'd, and only emails whose **subject contains `TEST`** are processed.

## Launch (3 steps)

1. **Terminal A — gateway + worker (safe posture):**
   ```bash
   bash scripts/run_teams_uat.sh
   ```
   It prints the posture check (dry-run on, Teams push on, Kory read-only, no CC) then starts the Hermes gateway on `:3978`.

2. **Terminal B — public tunnel:**
   ```bash
   ngrok http 3978
   ```
   Copy the `https://<random>.ngrok-free.app` URL.

3. **Azure Bot → Configuration → Messaging endpoint:**
   set it to `https://<ngrok-host>/api/messages` → **Apply**. (Temporary; revert after testing.)

Then DM Lexi/Hermes in Teams. First message registers the conversation for cards.

## What to try (all safe — nothing sends)

**Chat commands (read-only):**
- `help`, `brief`, `today`, `prebrief`, `pending`, `inbox review`, `unanswered`

**Scheduling flows** — send a test email (subject MUST contain `TEST`), then watch Teams:

| Scenario | How to trigger | Expected |
|---|---|---|
| **Delegation** | From your inbox, email a counterpart with subject like `TEST intro` and **CC lexi@iconicfounders.com**, saying "Lexi will get us a few times." | Lexi drafts an offer **to the counterpart** (greets them by name, Lexi voice) and pushes an approval card. Approving simulates the send (dry-run). |
| **Offer** | Email `lexi@iconicfounders.com` (subject `TEST coffee`) asking for time. | Lexi proposes calendar-checked times → approval card. |
| **Acceptance** | After an offer, reply proposing a specific time ("Tuesday 9am works"). | Lexi validates against Kory's calendar and pushes an **invite** card. |
| **Escalation** | Ask for something Kory's rules block (e.g. `TEST lunch this week`). | Lexi sends **you** a Teams message naming the blocker with 2-3 options — no generic defer. |

**Approvals:** every card has Send/Discard (and Find new times / invite). Approving runs the flow but the underlying send/hold is **dry-run** — confirm in the logs it says "NOT sent".

## Safety recap (enforced by the launcher)
- `LEXI_DRY_RUN=true` — no real email/calendar writes.
- `LEXI_KORY_SPACE_READ_ONLY=true`, `LEXI_KORY_OUTBOUND_BLOCKED=true` — Kory's mailbox/calendar never written.
- `LEXI_CC_KORY_ENABLED=false` — Kory not CC'd during testing.
- Recipient allowlist active (only your test addresses).
- `LEXI_LOCAL_MODE=true` — only `TEST`-subject emails are processed, so real inbound is ignored.
- `LEXI_FORCE_TEAMS_PUSH=true` — the one UAT-only override: pushes cards to Teams even though sends are simulated.

## Teardown
- Ctrl-C both terminals. Revert the Azure messaging endpoint. Nothing persists; no real messages were sent.

## Going to production later
Flip the enablement ladder in `.env.production` (holds → drafts → approved sends), set the Azure endpoint to the VPS, and remove `LEXI_FORCE_TEAMS_PUSH` (production pushes cards normally because dry-run is off).
