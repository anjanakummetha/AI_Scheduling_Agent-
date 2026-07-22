# Phase 3 Execution Report — Live Sandbox Write Testing & UAT

**Purpose:** the Gate 3 sign-off evidence required by `docs/FINAL_DEPLOYMENT_PLAN.md` before
anything touches the VPS. Records what was actually executed (not just built), what remains
deferred, and why the deferred items are safe to close in production under confirm-gating.

**Posture for all testing:** `LEXI_ENV=testing`, hard backstops ON. Kory's real Outlook/Asana/
HubSpot were **never** the write target — writes route to the Lexi sandbox connection
(`ca_4BTJ6d0O8sSZ`), re-asserted `!= ca_qORrE-NzPib2` (Kory) at runtime by
`scripts/uat/preflight_livewrite.py`. Sandbox email loopback redirects every send to `lexi@`.

---

## Rung-by-rung results

### Rung 1 — Calendar holds & lifecycle — ✅ core verified
- Hold create → verify-in-Outlook → delete proven on the Lexi sandbox calendar (the 7/20
  `phase5_e2e_validation` 7/20 test, and again in the in-process E2E below with 3 real holds).
- Lifecycle logic (expiry release, Friday cleanup, reminders) covered by
  `tests/test_kory_briefings.py` and the hold-lifecycle unit tests; live force-fire of the
  release path is a VPS smoke item (Rung 4 note).

### Rung 2 — Full email loop — ✅ verified in-process (2026-07-21)
Verified the exact production code path email → triage → schedule → Teams card → approve →
send → holds, in-process (the Teams Send button calls `execute_lexi_approval(...,
execution_phase="send_offer")`, which is what the harness drives):
- Proposal 220: `ok=True`, `email_sent=true` — a real `[Lexi pilot]` email delivered to the
  allowlisted test recipient (loopback to `lexi@`), **no Kory CC**.
- `holds_confirmed=3` — three real Outlook events on the Lexi sandbox calendar, then deleted
  for hygiene (`scripts/uat/cleanup_holds.py`).
- Kory connection `ca_qORrE-NzPib2` was never the write target.
- Reusable harness (recovered into the repo this phase): `scripts/uat/inject_scenario.py`,
  `inproc_e2e.py`, `verify_sandbox_state.py`, `cleanup_holds.py`, gated by
  `preflight_livewrite.py`.

### Rung 3 — Teams UAT — ✅ live round trip verified (2026-07-21)
- Real Azure Bot → ngrok → Hermes gateway (:3978) round trip confirmed (`help` command
  returned a Lexi reply; POST 200 through the full chain).
- Interactive Adaptive Cards render with `LEXI_TEAMS_TEXT_ONLY=false` (editable Type/Times/
  Email-draft + Save draft·Send·Discard). Send button gates on writes-allowed posture.
- Escalation and acceptance (counterpart proposing a new time) flows exercised.

### Rung 4 — Proactive jobs — ✅ force-fired in dry-run (2026-07-21)
- **Daily CEO briefing:** window/dedup logic green (`tests/test_kory_briefings.py` 2/2:
  fires in-window, skips outside-window, once-per-day). `build_daily_ceo_briefing()`
  force-fired live (read-only calendar) and produced a full briefing.
- **24h reminder:** `process_kory_24h_reminders()` with `LEXI_KORY_REMINDER_HOURS=0`
  correctly flagged all pending proposals as overdue and produced reminder entries.
- **Due-check:** `process_daily_ceo_briefing_if_due(now=...)` returns `outside_window`
  for a midday time; fires only inside the configured MT window.
- **Watchdog:** health-check/alert/restart logic reviewed; the `systemctl restart` half is a
  VPS smoke item (Phase 4).

### Rung 5 — Asana/HubSpot writes — ⛔ DEFERRED to Phase 5C (by design, not a gap)
There is no Asana/HubSpot **sandbox** — those Composio connections are Kory's REAL accounts.
They have only ever run dry-run (write-blocked, `[Lexi WRITE BLOCKED]` confirmations logged).
The first live Asana/HubSpot writes therefore happen in production at **Phase 5C, confirm-gated
per action**, behind `LEXI_ASANA_LIVE_WRITES_ENABLED` / `LEXI_HUBSPOT_LIVE_WRITES_ENABLED`
(both ship `false`). Unit coverage: `tests/` Asana/HubSpot suites + `test:hubspot_staging`.

### Rung 6 — Failure drills — ✅ verified locally (2026-07-21)
- **Backup/restore round trip:** `deploy/backup_lexi_db.sh` (online `.backup`) against a copy
  of the DB, then wiped `proposals`+`audit_log` and restored — 229 proposals / 187 audit rows
  recovered intact; backup passed `PRAGMA integrity_check`.
- **Composio 429/timeout retry:** `tests/test_composio_retry.py` 4/4 — retryable
  classification correct, reads retry-then-succeed, **writes never retried** (safety
  property), non-retryable reads not retried.
- **Worker kill / watchdog restart:** logic reviewed; live restart is a Phase 4 VPS smoke item.

---

## Regression at time of report
- `pytest`: **299 passed** (`.venv/bin/python -m pytest`).
- Dashboard auth E2E (never previously exercised): with `REQUIRE_AUTH=true`, protected path
  → 307 `/login`, wrong password → 401, correct creds → 200 + `ceo_dashboard_session` cookie,
  authenticated request → 200.

## Deferred to Phase 4/5 (tracked, not blocking Gate 3)
- Live `systemctl` watchdog restart + backup-timer firing → Phase 4 VPS smoke.
- Asana/HubSpot first live writes → Phase 5C, confirm-gated.
- F1 (possible duplicate Sun 7/26 facials) and F2 (weekend dinner offered without family-
  calendar check) → Kory to confirm before Phase 5 live sends.

**Gate 3 status:** the live email loop, Teams round trip, proactive jobs, and failure drills
that can be exercised without Kory's real write surfaces are **executed and green**. Remaining
items are inherently production/confirm-gated and are the correct place to close them.
