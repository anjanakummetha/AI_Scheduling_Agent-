# Kory Agent Needs — Analysis from Inbox & Rules

**Based on:** Live inbox sample (June 2026), `rules.py`, and pilot test runs.  
**Pilot:** Read Kory · Write `anjanakummetha@outlook.com` · Teams connection deferred.

---

## 1. What Kory's inbox actually contains

| Category | Examples from inbox | Agent behavior |
|----------|---------------------|----------------|
| **Deal / diligence scheduling** | Project Paint diligence call, Ridgeline Deal threads | High priority; offer 2–3 slots; holds; TZ in reply |
| **Internal IFG sync** | Heidi outreach messaging, ERRG summaries | Internal = faster path; summaries often **no reply** |
| **Investor / LP** | Solamere, Lava Island fund threads | Priority contacts; dinner/coffee rules |
| **Operational / admin** | Financial statements, health insurance | General reply on request — **no auto scheduling** |
| **Newsletters / digests** | YPO Marketplace, Deal Network | Ask "draft reply?" — usually **no** |
| **System / bounce** | Undeliverable receipts | Decline/skip drafting |

---

## 2. Core needs (from `rules.py`)

### Must never violate
- M/W/F trainer 6:30–8:00 AM
- Monday Doug 1:15–2:15 PM
- Thursday Capital Demolition 7:00 AM (bi-weekly)
- Weekends (except dinner edge cases)
- 6:00 PM cutoff for non-dinner meetings
- Family personal blocks — use Outlook calendars only (not whole family Google cal)

### Meeting types Kory uses daily
| Type | Duration | Notes |
|------|----------|-------|
| Coffee | 30 min | Virtual default |
| Lunch | 60 min | Exception-only; warn if routine |
| Dinner | 90 min | Evening allowed; weekly cap |
| New client / pitch | 30–60 min | Same-week urgency |
| Internal sync | 30 min | Trusted domain auto-path later |
| Board / YPO | Hard blocks | Read from calendar, never offer over |

### Voice
- External: recipient TZ first, MT in parentheses
- Sign-off: `Let's Win,` / `Kory`

---

## 3. Implemented workflow (pilot)

```text
New email (any) → triage → awaiting_reply_prompt
  → Teams/Hermes: "Should I draft a reply?"
  → NO  → no_reply_needed
  → YES → scheduling intent? 
           YES → scheduler (2–3 slots + holds + draft)
           NO  → general LLM draft only
  → Show draft → edits → approve → send (sandbox loopback)
```

**Key:** Scheduler autodraft runs **only** for scheduling-classified mail **after** Kory says yes.

---

## 4. Calendars — multi-Outlook (wired; not family Google)

Lexi reads **multiple Kory Outlook calendars** from `config/calendars.yaml` when checking busy/free and placing holds. The family Google calendar is **not** merged — it has Bridget/Maclain events unrelated to Kory.

- Kory Master Calendar (ALL) — default write
- IFG Team, Kory/Heidi only, Deal Activities, Daily CEO Update, Birthdays

Use `lexi_list_calendars` to see which calendars are on the account. Shared calendars appear once subscribed in Outlook.

---

## 5. Tool routing (Hermes)

| Task | Tool path |
|------|-----------|
| Schedule, holds, rules | **Lexi MCP** (`lexi_*`) |
| Accept invite, attachments, rare Outlook | **Composio MCP** direct |
| Email triggers | Lexi `:8000` webhooks |

Setup: `scripts/setup_hermes_mcp.py` + [composio.dev/hermes](https://composio.dev/hermes)

---

## 6. Gaps for production (post-Teams deploy)

1. ~~Named calendar targeting~~ — done (`lexi_list_calendars`, `calendar_name` on holds)
2. ~~Hold lifecycle~~ — done (3-day release + Friday cleanup)
3. `OUTLOOK_ACCEPT_EVENT` for invites
4. ~~Family Google Calendar~~ — not used; multi-Outlook only
5. `LEXI_WRITE_MODE=kory` after UAT
6. Asana reservation reminders (`ASANA_ENABLED=true`)

---

## 7. Test coverage map

| Kory pattern | Test ID |
|--------------|---------|
| Diligence call | KY-01 |
| Coffee/partnership | KY-02 |
| Internal Heidi sync | KY-03 |
| Meeting summary | KY-04 |
| YPO digest | KY-05 |
| Investor dinner | KY-06 |
| 6pm rule | P2-01 |
| Dinner 7pm OK | P2-03 |
| Ask before draft | P1-01 |
| Scheduler after yes only | P1-05b |

Run: `.venv/bin/python scripts/test_kory_phase_suite.py`
