# Lexi finish plan (Kory / IFG)

**Status:** Features from this backlog are **not set up yet**. Phase A (read-only audit) is done; one ingress crash was fixed in code. Dashboard comes **after** Lexi. **BCC on scheduling is deferred.**

**Hard rule until Phase 2/3 go-ahead:** no Outlook / HubSpot / Asana writes (no send, create, update, merge, complete against live systems).

---

## Direct answer: did we set everything up?

**No.** What exists today vs what you asked for:

| Request | Reality today |
|--------|----------------|
| Scheduling → Teams cards when someone emails Kory | **Partial / flaky.** Live mode is `delegation_only` — cards mainly when Lexi is CC’d (or Kory delegation phrasing). Cold meeting asks often become `no_reply_needed`. Worker/webhook health also uncertain. |
| Accurate dates/slots | Engine + validators exist; **needs more synthetic + your Teams UAT**. A few unit tests already failing on copy/fixtures. |
| Daily CEO briefing 4:45 AM MT | **Not built** |
| 24h reminders if Kory doesn’t reply | **Not built** (hold reminders ~3d exist; different feature) |
| Email Lexi as another chat channel | **Partial** (lexi@ + CC delegation + thread followup). No full “forward and instruct” task router. |
| Teams shortcuts: unanswered + today calendar + prebrief | **Not built** (`pending` / `inbound` / `inbox review` exist) |
| Prebrief + **who introduced** | Research tool exists; **who introduced missing** |
| Asana full chat (overdue/today/upcoming, add/update/complete) | **Reservation reminders only** |
| HubSpot connect + cleanup + batch outreach | **Not wired** (connection id known: `ca_jdY18Wb0L46M`; env not set; 0 MCP tools) |
| BCC scheduling | **Deferred** |
| CEO dashboard | **After Lexi** |

---

## Product north star (what Kory actually needs)

Lexi should let Kory run the day from **Teams** (and secondarily **email to lexi@**) with:

1. **Trustworthy scheduling** — correct dates/timezones, approval before any outbound email/calendar write.
2. **Morning clarity** — 4:45 MT brief + one-shot shortcuts for unanswered mail, today’s calendar, and meeting prebriefs (including who introduced).
3. **No dropped balls** — 24h nudge when he hasn’t acted; hold follow-ups already covered separately.
4. **Ops in chat** — Asana beyond reservations; HubSpot cleanup + batch outreach drafts, never auto-send.
5. **Hermes as the brain** — every capability exposed as MCP tools so Hermes composes accurately instead of inventing CRM/calendar writes.

Architecture stays: **Teams → Hermes → Lexi MCP → deterministic scheduling engine → Composio (approval-gated).**

---

## Critical gaps to fix (ordered by pain)

1. **Ingress / Teams notify policy** — `LEXI_TEAMS_INBOUND_NOTIFY_MODE=delegation_only` explains “scheduling email to Kory doesn’t always show in Teams.” Need an explicit product decision:
   - Keep: only when Lexi CC’d / delegated (current), **or**
   - Widen for important scheduling intents (your UAT choice).
2. **Webhook worker + public URL** — status showed worker not running / URL unset; without this, mail never enters the pipeline.
3. **`conversation_already_tracked` early return** — can suppress later messages on the same conversation.
4. **Live `.env` risk** — `LEXI_DRY_RUN=false`, `LEXI_WRITE_MODE=kory` while example recommends dry/sandbox for UAT.
5. **Who introduced** — no storage/parser; prebrief incomplete vs what Kory liked.
6. **HubSpot** — not connected in Lexi env.
7. **Asana** — chat workflows missing beyond Reservation Reminders.
8. **Slot/date copy tests** — TZ unknown path copy vs outdated assertions; hold-reminder test fixture flake.
9. **`from_kory` heuristic** — any `@iconicfounders.com` sender strengthens “from Kory”; Heidi/Anjana can look like Kory for delegation.

---

## Three phases

### Phase 1 — Agent builds + dry validation (no live writes)

**You do not need Teams yet.** Agent implements missing pieces and proves them with:

- Local pytest + fixtures  
- Synthetic email → orchestrator paths  
- Hermes MCP tools (`lexi_preview_schedule`, `lexi_validate_slots`, `lexi_validate_scheduling_cases`, status, mocked Asana/HubSpot)  
- **Spend cap:** no polling loops; no bulk HubSpot scans; no mass `research_person`; Anthropic only where Hermes path truly needs it; **0 Outlook/HubSpot/Asana writes**

#### Build order (Hermes-first)

| # | Workstream | Deliverable | Dry pass criteria |
|---|------------|-------------|-------------------|
| **1** | Ingress + scheduling fidelity | Keep NameError fix; tighten conversation-skip / follow-up; document notify_mode; expand date/slot fixtures; Hermes validate tools | All synthetic scheduling cases pass; notify behavior documented |
| **2** | Teams shortcuts | `unanswered`, `today`, `prebrief` (+ help). MCP + `lexi_handle_teams_command` | Commands return structured text from mocks/fixtures |
| **3** | Prebrief + who introduced | Structured brief; parse intro/CC/forward chain; store on recipient profile; “Introduced by: X \| Unknown” | Fixture threads attribute correctly |
| **4** | 24h Kory reminders + 4:45 MT briefing | Job for aged unanswered/pending; daily America/Denver 4:45 package (calendar, Asana due, unanswered, next prebriefs). Email optional, approval-gated | Clock-frozen unit tests; Teams push suppressed |
| **5** | Email-to-Lexi as chat | Intent router on mail to lexi@: schedule / don’t schedule / Asana / HubSpot / brief / remember | Synthetic forwards stage safe actions only |
| **6** | Asana full chat | MCP: overdue / due today / upcoming; add / update / complete (gated); optional Call List views | Reads mocked or one capped read; writes blocked without approval |
| **7** | HubSpot | Wire connection; read contacts/deals; cleanup triage proposals; batch outreach drafts for approval | Tool discovery + at most tiny read sample; **no merge/send** |

**Out of Phase 1:** BCC, dashboard, LinkedIn scraping, auto-send.

### Phase 2 — You test in Teams

You run the script; agent fixes only from your reports.

| # | You do | Pass if |
|---|--------|---------|
| T1 | CC lexi@ on scheduling ask | Card + correct dates/TZ |
| T2 | Cold inbound (after you choose notify policy) | Matches agreed policy |
| T3 | `unanswered` / `today` / `prebrief` | Useful briefs; who introduced or Unknown |
| T4 | Email lexi@: “don’t schedule with X” | Staged; no surprise invite |
| T5 | Asana overdue + approve a write | List OK; write only after approve |
| T6 | HubSpot cleanup sample + outreach batch | Drafts only until Send |
| T7 | 4:45 / 24h nudge (or simulated) | Right content, not spam |

**Gate:** prefer sandbox write mode; `LEXI_REQUIRE_KORY_APPROVAL=true`; confirm notify_mode with you before changing live behavior.

### Phase 3 — Production

- Stable webhook + backup poll  
- `dry_run` false only after sign-off  
- 4:45 MT live; HubSpot/Asana writes always approval-gated  
- Then connect CEO dashboard (shared briefing JSON / actions Lexi already owns)

---

## Spend discipline (most important operational constraint)

| Prefer | Avoid |
|--------|--------|
| pytest, fixtures, Hermes MCP dry tools | Inbox poll loops |
| `lexi_validate_scheduling_cases` | Bulk HubSpot inactive scans in Phase 1 |
| One-off status/DB reads | Live research on many people |
| Mocks for Asana/HubSpot writes | Any Composio write tool |
| Suppressed Teams push in dry runs | Burning Anthropic on pure unit logic |

---

## Acceptance checklist (definition of “Lexi done” before dashboard)

- [ ] Scheduling path: Lexi CC → Teams card → accurate slots (your T1 pass)  
- [ ] Agreed cold-inbound notify policy documented and working  
- [ ] `unanswered` / `today` / `prebrief` with who introduced  
- [ ] 4:45 MT CEO briefing (Teams; email optional)  
- [ ] 24h nudge for Kory inaction  
- [ ] Email-to-Lexi handles “don’t schedule / do X”  
- [ ] Asana overdue/today/upcoming + gated mutations  
- [ ] HubSpot connected; cleanup + outreach are **approval batches only**  
- [ ] BCC still out of scope  
- [ ] Dashboard explicitly **after** this list  

---

## Related artifacts

- Phase A audit: `docs/PHASE_A_BUILD_BACKLOG.json`  
- Canvas: `lexi-finish-plan.canvas.tsx` (open beside chat)
