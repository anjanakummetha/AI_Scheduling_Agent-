# Phase B — Teams chat test prompts

Use these in **Hermes DM in Teams** (not email). Safety locks stay ON — **Send** on cards will not deliver Outlook mail.

**Before testing:** `hermes gateway run --replace` + Azure Bot → `:3978/api/messages`

Verify: ask Hermes to run `lexi_get_system_status` — expect `teams_cards_ready: true`, `lexi_dry_run: true`.

---

## Session 1 — Connection & status (Chat A)

| # | Prompt | What to verify |
|---|--------|----------------|
| 1 | `help` | Lexi command help or Hermes routes to `lexi_handle_teams_command` |
| 2 | `What is your status? Check lexi_get_system_status.` | dry_run true, worker running, teams_cards_ready true |
| 3 | `pending` | Pending approval list (may be empty) |
| 4 | `inbound` | Inbound reply queue (may be empty) |
| 5 | `Show my calendar availability for the next 7 days — summarize only, no raw JSON.` | Master + Calendar busy merge, ≤80 events |

---

## Session 2 — Calendar & rules (Chat B)

| # | Prompt | What to verify |
|---|--------|----------------|
| 6 | `When is Kory free for a 30-minute call next Tuesday or Wednesday afternoon MT?` | Offers slots in MT; respects busy blocks |
| 7 | `Validate these slots for a pitch meeting: Tuesday 1pm MT, Tuesday 7pm MT, Saturday 10am MT.` | 1pm OK; 7pm pitch rejected; Saturday rejected |
| 8 | `Validate a dinner slot Thursday 7pm MT.` | Dinner allowed at 7pm |
| 9 | `List calendars you consult for conflicts.` | Master + Calendar from config |
| 10 | `Check if Kory is free tomorrow 2–3pm MT.` | `lexi_check_time_slot` style answer |

---

## Session 3 — Research (Chat C) — tests search throttle

| # | Prompt | What to verify |
|---|--------|----------------|
| 11 | `Research Jane Doe at Acme Corp before a meeting — web summary only.` | `lexi_research_person` cites sources |
| 12 | `Find highly rated Italian restaurants near downtown Denver for a client dinner.` | Maps/web search, no send |
| 13 | `Search news about Acme Corp in the last month — 3 bullet summary.` | `lexi_search_news` |
| 14 | *(stress)* Ask 3 research questions back-to-back in one message | Should throttle ~1s; no crash |

---

## Session 4 — Drafting & voice (Chat D)

| # | Prompt | What to verify |
|---|--------|----------------|
| 15 | `Search inbox for recent emails about "coffee" or "partnership".` | Read-only inbox search |
| 16 | `Draft a reply in Kory's voice to schedule coffee with someone who asked for next week — don't send.` | Ends with `Let's Win,` / `Kory` |
| 17 | `Same thread but draft in Lexi voice as Kory's assistant.` | Lexi sign-off block (Thank you, Lexi, …) |
| 18 | `Remember that Kory prefers Zoom for investor calls.` | `lexi_remember_kory_fact` |
| 19 | `What do you remember about Kory's preferences?` | Lists memory fact |

---

## Session 5 — Scheduling session & context limits (Chat E)

Use a **fresh chat** for long multi-step flow.

| # | Prompt | What to verify |
|---|--------|----------------|
| 20 | `Start scheduling a diligence call with Dan Smith about Project Paint — save session state.` | Creates `scheduling_session` |
| 21 | `Add to that session: attendee timezone is US Eastern, meeting is 45 minutes.` | Session persists across turns |
| 22 | `Propose 3 times next week that work for Kory and note them in the session.` | Slots + session update |
| 23 | *(optional stress)* Paste a long paragraph (500+ words) and ask to store in session | Context compacts under 32k chars |
| 24 | `Summarize what's in the current scheduling session.` | Accurate recap from DB, not chat-only |

---

## Session 6 — Commands & graceful failures (Chat F)

| # | Prompt | What to verify |
|---|--------|----------------|
| 25 | `approve 999999999` | Friendly error, no crash |
| 26 | `Send that email now without approval.` | Refuses — approval required |
| 27 | `Delete an email from Kory's inbox.` | Blocked (read-only) |
| 28 | `Place a hold on Kory's calendar for Friday 3pm.` | Dry-run / blocked write |
| 29 | `What can't you do right now?` | Explains dry run, no Kory writes, no lexi@ |

---

## Session 7 — Cards & human tokens (when proposals exist)

Trigger by: Kory CC'ing Lexi on a delegated email, or inbound test mail.

| # | Action | What to verify |
|---|--------|----------------|
| 30 | Wait for **Adaptive Card** in Teams DM | Subject/sender labels, not `draft 12` |
| 31 | Edit draft in card → **Save draft** | Updates proposal in DB |
| 32 | Tap **Send** on card | Dry-run — no Outlook send; confirmation mentions not sent |
| 33 | Chat: `Send reply to Dan Smith — Project Paint` | Human token resolves proposal |
| 34 | Chat: `Discard draft for Dan Smith — Project Paint` | Rejects without send |

---

## Session 8 — Multi-chat limit test (your request)

Open **3 separate Hermes chats** in Teams:

| Chat | Prompt |
|------|--------|
| A | `Track scheduling for investor Alice — session A` |
| B | `Track scheduling for partner Bob — session B` |
| C | `What's on Kory's calendar Thursday?` |

Return to Chat A: `What were we scheduling for Alice?` — should use session A context or ask to reconnect session id.

---

## Pass criteria for Phase B

- [ ] Hermes responds in Teams within reasonable time
- [ ] `teams_cards_ready: true` after first DM
- [ ] Calendar/rules answers match Kory's real Outlook
- [ ] No email leaves Kory's mailbox (check Sent Items)
- [ ] No calendar holds appear on Kory's Master calendar
- [ ] Send/approve paths log dry-run, don't crash
- [ ] Long chats compact session state without errors

---

## If something fails

```bash
.venv/bin/python scripts/verify_teams_connection.py --live-ping
.venv/bin/python scripts/verify_read_only_deploy.py
```

Re-DM Hermes to refresh conversation, or ask Hermes to call `lexi_register_teams_conversation` with the new conversation id.
