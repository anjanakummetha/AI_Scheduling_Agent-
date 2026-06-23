# Lexi — Final Plan (Kory daily use, deploy-ready)

**Audience:** Kory — high-level, very busy.  
**Product:** One Teams app **Lexi** = full scheduling agent (Lindy-class UX, higher accuracy).  
**Principle:** Read Kory’s truth. Write safely until proven. Confirm before external impact.

---

## 1. Holds when offering times — honest answer

### Today (code as built)

| Stage | What happens |
|-------|----------------|
| Scheduler proposes 2–3 times in draft email | Slots stored in **SQLite only** (`holds` table with ids like `hold-pending-12-01-…`) |
| Real Outlook calendar blocks | **Not created** at offer time |
| On **Approve** | Selected slot → `create_calendar_event` on the **write** mailbox |

So: **No — offering times to someone else does not currently put real holds on a calendar.** It stages options in the database. Holds on a real calendar happen on approval (or if you explicitly call `lexi_place_calendar_hold` in Hermes).

### Target (final product)

When Lexi **offers times** in an important meeting flow:

1. **List times** in the draft (email or chat).  
2. **Place real tentative holds** on the **write calendar** (sandbox: yours; production: Kory’s) for each offered slot.  
3. On confirm → keep one hold, delete others, send mail.  
4. If meal / venue meeting → **ask**: “Create Asana reservation reminder on Kory’s board?”

This matches how a busy EA works: calendar is blocked while options are live.

---

## 2. Dual-mailbox model (current phase: sandbox writes)

Kory’s real inbox and calendar are **read-only truth**. All **writes** go to **your** mailbox and calendar until UAT is complete.

```text
┌─────────────────────────────────────────────────────────────┐
│ READ  (Kory — production Composio connection)                  │
│  • Inbox / threads / search                                  │
│  • Calendar view / free-busy                                   │
│  KORY_COMPOSIO_CONNECTION_ID + COMPOSIO_ENTITY_ID            │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ WRITE (Sandbox — your Composio connection)                   │
│  • Calendar holds & confirmed events  → YOUR calendar        │
│  • Email send / draft                 → FROM you TO you      │
│  SANDBOX_COMPOSIO_CONNECTION_ID + SANDBOX_COMPOSIO_ENTITY_ID │
│  SANDBOX_MAILBOX_EMAIL=you@domain.com                        │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ ASANA (Kory’s board — reservation reminders)                 │
│  • Board: "Lexi Booking reminders"                         │
│  • Tasks created on Kory’s Asana (not sandbox)               │
│  ASANA_COMPOSIO_CONNECTION_ID + ASANA_PROJECT_GID            │
└─────────────────────────────────────────────────────────────┘
```

**Why:** Safe daily testing with real Kory context; no accidental emails to investors from Kory’s mailbox.

**Production cutover (later):** Set `LEXI_WRITE_MODE=kory` — read and write use Kory’s connection; sandbox vars unused.

---

## 3. One bot: Teams app “Lexi”

| Item | Value |
|------|--------|
| Teams install | **Lexi** (existing app) |
| Azure messaging URL | `https://<host>/api/messages` → **Hermes gateway :3978** |
| Brain | Hermes (Claude OAuth) + Lexi MCP tools |
| Approvals | Chat: “approve 12 option 1” / “reject” — no cards required |
| Background | Lexi `:8000` — email webhook, orchestrator, dashboard |

Kory opens **one chat** with Lexi. Any scheduling question or command goes there.

---

## 4. Architecture (long-term)

```text
INGRESS
  Outlook (Kory)     → webhook :8000
  Teams "Lexi"       → Hermes :3978
  Hermes Mac/TUI     → same MCP

HERMES (orchestrator)
  Claude OAuth · multi-turn · agent_instructions.txt
  Calls MCP only — never Composio directly

LEXI CORE (:8000 + MCP)
  propose_schedule()      — one path for email + chat
  validate_proposal()     — rules.py in code
  place_offered_holds()   — real calendar holds per offered slot (write mailbox)
  execute_approval()      — confirm slot, release holds, send mail
  reservation_reminder()  — Asana on Kory board
  scheduling_sessions     — task state across messages
  lexi.db                 — proposals, audit

COMPOSIO
  READ  → Kory M365
  WRITE → Sandbox M365 (now) / Kory (later)
  ASANA → Kory board
```

---

## 5. Daily workflows for Kory

### A. Someone emails Kory (automatic)

1. Webhook reads **Kory’s inbox**.  
2. Triage + `propose_schedule()` using **Kory’s calendar**.  
3. Draft reply lists 2–3 times.  
4. **Place holds on sandbox calendar** for each slot (target behavior).  
5. Notify Kory in Teams: summary + “approve 1 / 2 / 3 / reject”.  
6. If **important + meal** (dinner/lunch/happy hour) or priority high → also ask: **“Add reservation reminder to Asana?”**  
7. On approve → send email **from sandbox to sandbox** (now), confirm one hold, drop others.  
8. If Kory said yes to reservation → Asana task on **Lexi Booking reminders**.

### B. Kory asks in Teams (any time)

Examples:

- “Schedule lunch with Jane next week”  
- “Am I free Thursday?” (reads **Kory’s** calendar)  
- “Draft a reply to the investor dinner thread”  
- “Put a reminder to book Nobu for that dinner” → **Asana task**  
- “What’s waiting on me?”  

Flow: clarify → read Kory calendar → propose → holds on **sandbox** → confirm → sandbox email loopback.

### C. Reservation reminder (explicit or prompted)

**Triggers:**

| Trigger | Action |
|---------|--------|
| Kory: “remind me to make a reservation” | `create_booking_reminder_task` → Kory’s Asana board |
| Important meeting + lunch/dinner in draft | Agent asks: “Create reservation reminder?” |
| Kory mentions lunch/dinner in outbound mail | Auto-suggest Asana reminder |

Asana always targets **Kory’s board**, even when calendar/email writes are sandboxed.

---

## 6. “Important enough” for holds + reservation ask

Use **deterministic rules** (not model guess):

| Signal | Holds on offer | Ask Asana reservation? |
|--------|----------------|-------------------------|
| Priority **high** | Yes | Yes if meal/venue intent |
| Intent `dinner_request`, `lunch_request`, `happy_hour` | Yes | **Yes** |
| Intent `board_meeting`, `pitch` + priority high | Yes | Optional ask |
| Priority **low** internal sync | Optional | No |
| Kory explicit “hold these” | Yes | If meal |

Validator runs **before** Kory sees options.

---

## 7. Accuracy (built to last)

1. **Read path** — only Kory Composio connection for inbox/calendar facts.  
2. **Write path** — explicit sandbox vs kory mode; `LEXI_DRY_RUN` for extra safety.  
3. **Rules in code** — `rules.py` → `validate_proposal()` (6pm, lunch default, weekly caps).  
4. **Confirm gates** — send mail, confirm booking, create Asana only after yes.  
5. **Audit** — every tool call → `audit_log`.  
6. **One proposal id** per case — no double sends.

---

## 8. Memory & context (busy exec)

| Layer | What | Purpose |
|-------|------|---------|
| **Chat session** | Hermes thread history | Same-day back-and-forth |
| **scheduling_sessions** | Structured task (Jane, slots, draft) | Resume interrupted scheduling |
| **lexi.db** | Proposals, holds, audit | “What’s pending?” / history |
| **kory_memory** | Explicit facts Kory states | Preferences over months |
| **rules + contacts** | `rules.py`, `priority_contacts.yaml` | Policy |

Getting better = saved facts + rule updates + audit review — not silent model learning.

---

## 9. Environment (sandbox phase)

```bash
# ── Read: Kory ──
KORY_COMPOSIO_CONNECTION_ID=ca_...
COMPOSIO_ENTITY_ID=...
COMPOSIO_API_KEY=...

# ── Write: your sandbox mailbox ──
LEXI_WRITE_MODE=sandbox
SANDBOX_COMPOSIO_CONNECTION_ID=ca_...
SANDBOX_COMPOSIO_ENTITY_ID=...
SANDBOX_MAILBOX_EMAIL=you@yourdomain.com
SANDBOX_EMAIL_LOOPBACK=true

# ── Asana: Kory board ──
ASANA_COMPOSIO_CONNECTION_ID=ca_...
ASANA_PROJECT_GID=...

# ── Safety ──
LEXI_DRY_RUN=false
# Use dry_run OR sandbox loopback — sandbox loopback is preferred for realistic sends

# ── Teams → Hermes ──
# TEAMS_* in ~/.hermes/.env, Azure URL → :3978
```

---

## 10. Implementation checklist (build order)

### Phase 1 — Sandbox dual connection (foundation)

- [ ] `app/config.py`: `LEXI_WRITE_MODE`, sandbox connection ids  
- [ ] `composio_client.py`: `execute_read_tool()` vs `execute_write_tool()` routing  
- [ ] Email loopback: `to` and `from` = `SANDBOX_MAILBOX_EMAIL`  
- [ ] Calendar writes → sandbox connection only  

### Phase 2 — Real holds when offering times

- [ ] `place_offered_holds(proposal_id, slots)` → `create_calendar_event` per slot on **write** calendar  
- [ ] Scheduler + `propose_schedule()` call it (not DB-only mock ids)  
- [ ] On approve: keep winner, `delete_calendar_event` on losers  

### Phase 3 — One brain (Hermes + unified propose)

- [ ] `propose_schedule()` shared by webhook + MCP  
- [ ] `validate_proposal()` from `rules.py`  
- [ ] Azure → Hermes :3978; Lexi instructions in Hermes  
- [ ] Teams proactive notify on `pending_approval`  

### Phase 4 — Inbox + sessions

- [ ] MCP: `lexi_search_inbox`, `lexi_get_thread`  
- [ ] `scheduling_sessions` table  
- [ ] MCP: `lexi_create_reservation_reminder` (wraps Asana)  

### Phase 5 — Reservation intelligence

- [ ] After draft for meal/high priority → prompt Kory (chat) or flag in Teams summary  
- [ ] On confirm → Asana task with meeting subject, slot, attendees  

### Phase 6 — Production cutover

- [ ] `LEXI_WRITE_MODE=kory`  
- [ ] UAT checklist on real sends  
- [ ] Retire sandbox loopback  

---

## 11. Deployment topology

```text
teams.domain.com/api/messages     → Hermes :3978
api.domain.com/webhooks/composio  → Lexi :8000

Services:
  hermes-gateway (3978)
  lexi-api (8000)
  composio triggers on Kory mailbox
```

**Go-live tests:**

1. Kory email arrives → read from his inbox → proposal + sandbox holds + Teams ping.  
2. “approve 1” in Lexi chat → loopback email to you, one sandbox hold kept.  
3. “Remind me to book dinner” → Asana task on Kory board.  
4. “Am I free Tuesday?” → matches Kory calendar read.  

---

## 12. Success definition

Lexi is **done** when Kory can use **one Teams chat** daily for:

- Any scheduling question (calendar/inbox grounded in **his** data)  
- Approving inbound mail with yes/no  
- Starting outbound scheduling with holds on offer  
- Reservation reminders on **his** Asana board  
- Safe writes during pilot (**your** calendar + loopback email)  
- Clear path to `LEXI_WRITE_MODE=kory` without re-architecture  

---

## 13. Summary table

| Question | Answer |
|----------|--------|
| One bot? | **Lexi** in Teams → Hermes :3978 |
| Holds when offering times? | **Not today**; **yes in final** (write calendar per slot) |
| Read from? | **Kory** inbox + calendar |
| Send/hold from? | **Your** mailbox/calendar now; Kory later |
| Asana? | **Kory’s** “Lexi Booking reminders” board |
| Reservation ask? | **Yes** for important / meal meetings + on Kory request |
| Lindy parity? | Same conversational surface; stronger validation + audit |

This document is the **final plan**. Implement phases 1–6 in order.
