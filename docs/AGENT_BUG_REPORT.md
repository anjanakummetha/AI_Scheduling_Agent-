# Lexi agent bug report (live audit)

Generated from live Composio read of Kory inbox + calendar, inbound pipeline simulation, and validator regression (2026-06-11).

## Fallback when the agent makes a mistake

Lexi is designed so **Kory is always the last line of defense** — nothing sends or books without explicit approval.

| Layer | What happens |
|-------|----------------|
| **1. Ask before draft** | Every inbound email stops at `awaiting_reply_prompt`; Hermes asks Kory first |
| **2. Draft review** | Full draft shown in Teams; `lexi_update_proposal_draft` for edits |
| **3. Approve / modify / reject** | `approve_decision`, `modify_and_approve_decision`, `reject_decision` |
| **4. Scheduling fails** | `begin_draft_reply` → `general_fallback` (non-slot reply) instead of bad slots |
| **5. LLM fails** | Template reply (`template_fallback`) or engine slot fallback (if calendar live) |
| **6. Calendar unavailable** | Scheduler **refuses** to propose slots (no silent empty-calendar proposals) |
| **7. Rule violations** | Validators strip bad slots before holds; need ≥2 valid options or scheduling fails |
| **8. Audit trail** | `lexi.db` — proposals, holds, steps, approvals for replay |

**Kory override:** Rules are defaults; explicit Kory instruction in Teams wins over `rules.py`.

---

## Fixes applied in this audit

| Fix | Impact |
|-----|--------|
| `HARD_BLOCKS` in validators (trainer, Doug, timed blocks) | Blocks M/W/F 6:30–8 and Mon Doug 1:15–2:15 in proposed slots |
| Scheduler requires live calendar (`status == available`) | No proposals on fake-empty calendar when Composio fails |
| `recipient_timezone_confidence()` — unknown domains → ask | No silent Eastern default for new contacts |
| Draft banner when TZ unknown | MT-only times + “ask Kory” note in draft body |
| Removed duplicate `Saturday` key in `rules.py` | Config integrity |

---

## Open bugs / gaps (priority order)

### Medium

| ID | Area | Issue | Mitigation |
|----|------|-------|------------|
| B-01 | Calendars | **4 of 6 configured conflict calendars missing** on Kory Composio account: IFG Team, Kory/Heidi only, Deal Activities, Daily CEO Update | Subscribe/shared calendars in Outlook; verify via `lexi_list_calendars` |
| B-02 | Validators | **Bi-weekly Capital Demolition** (Thu 7–8) not enforced — only calendar merge catches it | Add bi-weekly logic or rely on calendar (document) |
| B-03 | Validators | **YPO, board meetings, HRT, school pickup** — no fixed times in rules; calendar-only | Ensure multi-calendar read includes all subscribed cals |

### Low

| ID | Area | Issue | Mitigation |
|----|------|-------|------------|
| B-04 | Validators | Weekly happy-hour / dinner caps not counted | Add rolling counters or warn in Hermes |
| B-05 | Validators | Soft blocks (WOB, Patrick sync, 3pm inbox) — warnings only | Acceptable; Kory approves |
| B-06 | Validators | Lunch = warning not hard reject | By design (Kory can override) |
| B-07 | Sandbox | Write connection may be `@gmail.com` not sandbox `@outlook.com` | Reconnect Composio or align `SANDBOX_MAILBOX_EMAIL` |
| B-08 | Ops | No CI / automated nightly audit | Run `scripts/audit_live_accuracy.py` after rule changes |

### Fixed during audit (was bugs)

| ID | Was | Now |
|----|-----|-----|
| ~~B-09~~ | Trainer block not in validators | **Fixed** |
| ~~B-10~~ | Doug Monday block not in validators | **Fixed** |
| ~~B-11~~ | Silent Eastern TZ default | **Fixed** — `unknown` confidence |
| ~~B-12~~ | Calendar fail → empty busy → bad slots | **Fixed** — scheduler aborts |

---

## Live read snapshot (Kory)

**Inbox (recent):** scheduling-adjacent threads (Fractional CFO, LinkedIn connect, intros), internal IFG dailies, LinkedIn digest, forwarded deal email.

**Calendar (14d):** 25 events — e.g. IFG call 7:00, Keith Allis 8:30, Ben Lewis 9:30 MT.

**Triage simulation (5 messages):** 3 scheduling-classified, 2 non-scheduling; all stopped at `awaiting_reply_prompt` ✓

---

## How to re-run

```bash
.venv/bin/python scripts/audit_live_accuracy.py
.venv/bin/python scripts/test_kory_phase_suite.py --skip-live-llm
.venv/bin/python scripts/test_live_e2e.py --skip-approval
```

JSON output: `docs/LIVE_ACCURACY_AUDIT.json`
