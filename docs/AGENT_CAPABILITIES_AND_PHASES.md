# Lexi + Hermes — Capabilities, Architecture & Final Phases

**Status:** OUTLINE — approve before implementation.  
**Pilot mailbox:** `anjanakummetha@outlook.com` (write) · **Read:** Kory Outlook  
**Teams:** Hermes gateway `:3978` (when tunnel + Azure ready)

---

## 1. What the agent should be able to do (“anything” target)

### A. Conversational (Hermes in Teams or Mac CLI)

| Capability | Description |
|------------|-------------|
| Natural scheduling chat | “Schedule coffee with Jane next week”, “Am I free Thursday?” |
| Multi-turn memory | Remembers attendee, intent, draft across messages (`scheduling_sessions`) |
| Clarify before acting | Asks for email, meeting type, duration, which calendar |
| Read truth from tools | Never guesses calendar or inbox state |
| Proactive nudges | Pending approvals, expiring holds, Friday cleanup reminders |
| Judgment from Kory rules | Lunch exception-only, dinner cap, podcast low urgency, new client same-week |

### B. Email (inbound + outbound)

| Capability | Description |
|------------|-------------|
| Read Kory inbox | Triage scheduling vs non-scheduling |
| Search / open threads | `lexi_search_inbox`, `lexi_get_thread` |
| Back-and-forth coordination | Offer 2–3 times, follow up if no reply 2–3 days |
| Draft in Kory voice | Recipient TZ first, MT in parens; sign “Let’s Win,” |
| Send only after approve | Kory confirms in Teams → Hermes → MCP execute |
| Pilot loopback | Writes from/to `anjanakummetha@outlook.com` (no external send) |

### C. Calendar (read + write)

| Capability | Description |
|------------|-------------|
| Read Kory busy/free | Primary + **named calendars** (see §3) |
| Offer 2–3 slots | Conflict-aware against calendar truth |
| **Hold all offered slots** | Tentative blocks so slots aren’t double-booked |
| Confirm one slot | Release other holds; create confirmed event |
| **Target specific calendar** | “Add to IFG Team”, “Kory Master Calendar”, etc. |
| Reschedule priority | 2 options, 1-day reply, holds on both |
| Hold lifecycle | Remind at 2–3 days; release; Friday cleanup for next week |
| Time zones | Internal MT; external emails show recipient TZ first |

### D. Named calendars (must support)

| Display name | Typical use |
|--------------|-------------|
| **Birthdays** | Personal reminders — usually read-only for scheduling |
| **Kory Master Calendar** | Primary executive calendar (default for most meetings) |
| **IFG Team** | Team / company shared calendar |
| **Kory/Heidi only** | Private exec + EA coordination |
| **Deal Activities** | Deal pipeline meetings |
| **Daily CEO Update** | CEO rhythm / daily block |

**Today:** only default `me` calendar on read/write mailbox.  
**Target:** list calendars → resolve name → read conflicts + create events on chosen calendar.

### E. Asana (when enabled)

| Capability | Description |
|------------|-------------|
| Reservation reminders | Lunch/dinner → Kory NON-IFG → Reservation Reminders |
| On Kory confirm only | Hermes asks; no auto-create |

### F. Approvals & audit

| Capability | Description |
|------------|-------------|
| Kory approves all (Phase 1) | No autonomous sends/bookings |
| Teams via Hermes | DM every message; group/channel @mention |
| Full audit trail | `lexi.db` — proposals, holds, approvals, steps |

---

## 2. Architecture overview

```text
┌──────────────────────────────────────────────────────────────────┐
│ MICROSOFT TEAMS                                                   │
│  Bot → Hermes (existing app)                                      │
│  DM: all messages │ Group/Channel: @mention                       │
└────────────────────────────┬─────────────────────────────────────┘
                             │ HTTPS POST /api/messages
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│ HERMES GATEWAY (:3978)                                            │
│  • Claude (ANTHROPIC_API_KEY)                                     │
│  • agent_instructions.txt + Kory rules context                    │
│  • scheduling_sessions (multi-turn)                               │
│  • Proactive Teams messages                                       │
│  • MCP client only — no direct Composio                           │
└────────────────────────────┬─────────────────────────────────────┘
                             │ stdio MCP (hermes_mcp_server.py)
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│ LEXI EXECUTION LAYER                                              │
│  ┌─────────────────┐  ┌──────────────────┐  ┌─────────────────┐ │
│  │ propose_schedule│  │ validate_proposal │  │ place_offered_  │ │
│  │ (unified)       │  │ (rules.py)        │  │ holds           │ │
│  └─────────────────┘  └──────────────────┘  └─────────────────┘ │
│  FastAPI :8000 — webhooks, orchestrator, audit (not Teams URL)    │
│  SQLite lexi.db — proposals, holds, sessions, audit_log           │
└────────────────────────────┬─────────────────────────────────────┘
                             │ Composio
          ┌──────────────────┼──────────────────┐
          ▼                  ▼                  ▼
   READ: Kory M365    WRITE: sandbox M365   ASANA (optional)
   • inbox            • anjanakummetha@     • Reservation
   • calendars         outlook.com           Reminders
     (6 named +        • calendar holds
      primary)          • loopback email
```

### Data flow — inbound email

```text
Email → Kory inbox → Composio webhook/poll → Lexi :8000
  → Triage (Claude) → Scheduler + rules + Kory calendar read
  → Hold 2–3 slots on WRITE calendar (pilot: your Outlook)
  → pending_approval → Hermes notifies Kory in Teams
  → Kory approves → confirm event + loopback email
```

### Data flow — Teams chat

```text
Kory → Teams DM → Hermes :3978 → MCP tools
  → lexi_get_calendar_availability (Kory read)
  → lexi_validate_slots / lexi_place_calendar_hold
  → lexi_draft_outbound_email → approve → lexi_send_outbound_email
  → Optional: lexi_create_reservation_reminder (Asana)
```

### Pilot vs production

| | Pilot (now) | Production (later) |
|--|-------------|-------------------|
| Read | Kory Outlook + calendars | Same |
| Write | `anjanakummetha@outlook.com` | Kory Outlook |
| Email send | Loopback to self | Real recipients from Kory |
| `LEXI_WRITE_MODE` | `sandbox` | `kory` |

---

## 3. Calendar model (6 named + primary)

Config target (`calendars.yaml` or `.env`):

```yaml
calendars:
  default_write: "Kory Master Calendar"
  default_read_for_conflicts:
    - "Kory Master Calendar"
    - "IFG Team"
    - "Kory/Heidi only"
    - "Deal Activities"
  aliases:
    master: "Kory Master Calendar"
    team: "IFG Team"
    heidi: "Kory/Heidi only"
    deals: "Deal Activities"
    ceo_daily: "Daily CEO Update"
    birthdays: "Birthdays"
```

**MCP tools to add (Phase 2):**

- `lexi_list_calendars` — discover IDs from Kory + write mailbox  
- `lexi_place_calendar_hold(calendar_name=...)`  
- `lexi_create_event(calendar_name=...)`  
- Conflict check merges all `default_read_for_conflicts` calendars  

**Hermes behavior:**  
“Add this to IFG Team calendar Tuesday 2pm” → resolve alias → hold/create on that calendar.

---

## 4. Rules engine (calendar first)

1. **Kory Outlook calendar(s)** — ground truth for busy/free  
2. **`rules.py`** — durations, caps, blocks, tone  
3. **`validators.py`** — hard gates before staging  
4. **LLM** — draft quality only; cannot override hard rules  

Key Kory rules in plan: 2–3 options, hold all, 2–3 day follow-up, Friday cleanup, no lunch default, 6pm cutoff except dinner, weekly happy hour/dinner caps, new client same-week urgency, podcast 3–4 weeks, reschedule 2 options / 1-day hold.

---

## 5. Final implementation phases

### Phase 0 — Pilot sandbox (current) ✅ mostly done

**Goal:** Safe testing without touching Kory’s send mailbox.

- [x] Read Kory inbox + primary calendar  
- [x] Write holds/events + loopback email to `anjanakummetha@outlook.com`  
- [x] Triage → scheduler → holds → approve path  
- [x] Hermes MCP tools (calendar, queue, approve)  
- [x] Basic validators  
- [ ] Teams → Hermes `:3978` (blocked: tunnel/Azure)  
- [ ] Approve via Hermes CLI / console (Teams substitute)

**Test commands:**
```bash
.venv/bin/python scripts/test_sandbox_integration.py
.venv/bin/python scripts/lexi_console.py inject --subject "..." --body "..."
.venv/bin/python scripts/lexi_console.py approve <id>
hermes  # + MCP approve_decision
```

---

### Phase 1 — Teams + Hermes wiring + rule hardening

**Goal:** One chat surface (Teams → Hermes); email pipeline unchanged.

| Task | Deliverable |
|------|-------------|
| Tunnel + `teams app update` → `:3978` | Teams DM works |
| MCP registered in `~/.hermes/config.yaml` | Hermes calls Lexi |
| `agent_instructions.txt` + full Kory rules | Chat behavior |
| Expand validators | Workout windows, weekly caps, coffee 90m, urgency |
| Hold on every offer path | Inbound + outbound unified |
| Proactive pending notify | Hermes → Teams when email staged |
| Deprecate Lexi `:8000` as Azure target | Docs + config only |

**Exit criteria:** Kory DMs Hermes → sees pending email proposal → approves → loopback email + sandbox calendar event.

---

### Phase 2 — Named calendars + hold lifecycle + sessions

**Goal:** “Add to IFG Team” / “Kory Master” works; Lindy-style follow-up.

| Task | Deliverable |
|------|-------------|
| `lexi_list_calendars` + ID map for 6 calendars | Name → Graph calendar ID |
| Read conflicts across multiple calendars | Master + Team + Deals + Heidi |
| Write to named calendar | `calendar_name` param on hold/create |
| `scheduling_sessions` wired to Hermes | Multi-turn Teams memory |
| Hold reminder job (2–3 days) | Draft reminder email + release |
| Friday hold cleanup | Clear next-week holds |
| Reschedule flow | 2 options, 1-day hold |
| Podcast vs new-client triage | Priority in scheduler |
| Asana on Kory confirm | `ASANA_ENABLED=true` gated |

**Exit criteria:** “Put deal review on Deal Activities Thursday” creates event on correct calendar; no-reply holds auto-release with reminder draft.

---

### Phase 3 — Full Lindy parity + production cutover

**Goal:** Production-ready on Kory’s mailbox; minimal manual steps.

| Task | Deliverable |
|------|-------------|
| `LEXI_WRITE_MODE=kory` | Real sends from Kory |
| Multi-attendee availability | Find mutual slots (Graph free/busy) |
| Family Google Calendar read | “Do Not Move” blocks (if API available) |
| Post-meeting follow-up drafts | Templates via Hermes |
| VPS deployment | Stable tunnel, no ngrok |
| Weekly capacity dashboard | Happy hour/dinner counts in validators |

**Exit criteria:** End-to-end on Kory mailbox with external recipients; all 6 calendars; hold lifecycle automated.

---

### Phase 4 — “Anything” extensions (optional)

| Task | Deliverable |
|------|-------------|
| Teams meeting pipeline summaries | Graph delivery (Hermes docs) |
| Group calendar create for new deals | Auto-route by intent |
| Auto-execute policy (Phase 2+) | Only if Kory opts in per meeting type |
| CRM / deal room hooks | Deal Activities calendar integration |

---

## 6. What works today vs not yet

| Request | Today | After Phase 2 |
|---------|-------|---------------|
| Read Kory email | ✅ | ✅ |
| Email loopback to `anjanakummetha@outlook.com` | ✅ | ✅ (pilot) |
| Add hold to **default** sandbox calendar | ✅ | ✅ |
| Add to **Kory Master / IFG Team / …** | ❌ | ✅ |
| Teams chat via Hermes | ❌ (no tunnel) | ✅ Phase 1 |
| Hold cleanup 2–3 days | ❌ | ✅ Phase 2 |
| Asana reservation | ❌ (paused) | ✅ Phase 2 |

---

## 7. Sign-off before coding

- [ ] Architecture: Teams → Hermes `:3978` → MCP → Lexi  
- [ ] Pilot: read Kory, write `anjanakummetha@outlook.com`  
- [ ] Six calendars in Phase 2 scope  
- [ ] Phase order: 0 → 1 → 2 → 3  
- [ ] No production Kory writes until Phase 3 UAT  

**Reply “approved” or note edits — then Phase 1 implementation begins.**
