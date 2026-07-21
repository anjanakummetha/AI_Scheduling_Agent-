# Final Plan — Finish, Verify, and Deploy Lexi + CEO Dashboard

**Date:** 2026-07-21 · **Target:** Hostinger KVM 2 (`srv1686061.hstgr.cloud`) · **Owner approval required for every live write and every gate change.**

---

## 0. Where we actually are (verified today, 2026-07-21)

| Check | Result |
|---|---|
| Agent test suite (`.venv/bin/python -m pytest`) | ✅ 296 passed |
| Phase 5 dry-run E2E matrix (20 capabilities, real reads) | ✅ 19 pass / 1 skip → skip closed 7/20 via sandbox hold write on Lexi's own mailbox (create/verify/delete all passed) |
| Rung 0 realistic scenarios (10 Kory-style emails, dry-run) | ✅ 10/10 clean, 0 real writes, 8 offered / 2 correctly deferred (after the two scheduler fixes) |
| Dashboard production build (`npm run build`, Node 20.20) | ✅ passes |
| Dashboard write-safety scan (`test:no-write-slugs`) | ✅ passes |
| Dashboard read-only unit test (`test:readonly`) | ⚠️ **cannot run on Node 20** — `node --test` can't import the `.ts` module (tooling gap, not a product bug) |
| Deploy artifacts (`deploy/`: install.sh, systemd units, Caddyfile, watchdog, backups) | ✅ exist; VPS has a **stale June build** running `lexi-hermes` |
| Kory user guide | ✅ `docs/KORY_USER_GUIDE.html` (final review pending) |

**Known gaps (the actual work left):**

1. **G1 — Repo hygiene:** ~36 modified + ~30 untracked files uncommitted; dashboard lives untracked inside the agent repo; CI never ran against the final tree.
2. **G2 — Dead sandbox connection:** `.env.testing` still points at deleted Composio account `ca_yd7Gdu84OgJO`; sandbox posture must be re-established before live write tests.
3. **G3 — `test:readonly` tooling:** the read-only client unit test silently can't execute on Node 20 (needs Node ≥22 type-stripping or `tsx` loader).
4. **G4 — Live UAT never done end-to-end:** real Teams round trip (Azure bot → Hermes → cards → approve), webhook ingress, hold lifecycle live, proactive jobs (4:45 briefing, 24 h reminders, watchdog), dashboard against live APIs with auth on.
5. **G5 — Production config not written:** `.env.production` values, DNS/Caddy hostnames, dashboard `REQUIRE_AUTH`, `LEXI_API_TOKEN`, Azure messaging endpoint → VPS (currently ngrok-era), Composio webhook URL.
6. **G6 — Stale VPS:** June build must be stopped/replaced; DB/backup state on VPS unknown.

---

## Standing guardrails (apply to every phase below)

- **Approval protocol for live actions:** before ANY write or send, I state in chat — the exact action, target account/calendar/recipient, and content — and wait for your explicit "approved" in this conversation. One approval = one action (no blanket approvals).
- **Hard technical backstops stay on during all testing:** `LEXI_ENV=testing` (recipient allowlist active), `LEXI_KORY_SPACE_READ_ONLY=true`, `LEXI_REQUIRE_KORY_APPROVAL=true`, `LEXI_ALLOW_IMMEDIATE_SEND=false`, `LEXI_AUTO_EXECUTE_ENABLED=false`. Kory's real Outlook/Asana/HubSpot are **never** written during testing.
- **Write-connection guard:** every sandbox write script re-asserts at runtime that the resolved Composio connection ≠ Kory's (`ca_qORrE-…`) and aborts otherwise (pattern already proven in the 7/20 hold test).
- **Test hygiene:** every test artifact is created with a `TEST` marker, read back to verify, then deleted, with the audit log checked after each rung.
- **Context-realistic tests:** live scenarios mirror Kory's actual traffic (referral intros, PE-fund meeting requests, reschedules, dinner asks, East-Coast investor early calls, delegation via CC lexi@) — reusing the Rung 0 scenario bank, sent from a test mailbox to Lexi's mailbox.

---

## Phase 1 — Code freeze & cleanup (no approvals needed) — ✅ SUBSTANTIALLY DONE 2026-07-21

1. **✅ G3 fixed:** added `tsx` devDependency; `test:readonly` now runs on Node 20 and passes 4/4.
2. **✅ G2 fixed (D1 = Lexi's own mailbox):** `.env.testing` sandbox repointed to `ca_4BTJ6d0O8sSZ` (Lexi, verified ACTIVE); dead `ca_yd7…` id removed; `SANDBOX_COMPOSIO_ENTITY_ID` blanked so it auto-derives (`Lexi`).
3. **✅ G1 (D2 = separate repos):** agent `.gitignore` now ignores `CEO_Executive_Dashboard--main/`; both repos committed on branch `deploy-prep-phase1` (agent `e562eb7`, dashboard `0bda61b`). **Push pending user approval** (classifier-gated).
4. **✅ Secret sweep:** no real `.env`/credentials tracked or in history in either repo (only `*.example` placeholders); real env files verified git-ignored.
5. **✅ CI made reliable (would previously have gone red):**
   - Agent `test_kory_phase_suite.py` P1-01/P1-02 asserted LLM-triage-dependent outcomes that keyless CI and `LEXI_LOCAL_MODE` can't satisfy → gated behind live-LLM (mirrors P1-05) + skip-on-local-mode. No product change.
   - Agent `test_approval_safety.py`: the approval gate only raises with dry-run OFF, so the "blocked-without-approval" checks are meaningless under dry-run → skip them under dry-run (covered hermetically by `tests/test_approval_gate_lexi.py`), and added a **hard SAFETY ABORT** if dry-run is off with a real `COMPOSIO_API_KEY` present. CI runs the step in the only safe place for dry-run-off (keyless CI) with the approved recipient allowlisted.
   - Verified all CI steps exit 0 in CI-equivalent conditions: pytest 296, phase suite 30/30, approval safety ALL PASS. Dashboard: build compiles, lint 0 errors, `test:readonly` + `test:no-write-slugs` pass.
   - **Remaining:** confirm the actual GitHub Actions run is green after push.
6. **Doc pass:** ⬜ still to do — prune ngrok-era docs so `deploy/README.md` is the single source of truth; final `KORY_USER_GUIDE.html` review.

**Gate 1 (exit):** CI green on GitHub (needs push), working tree clean ✅, sandbox connection valid ✅.

## Phase 2 — Full local regression (hermetic + read-only live reads) — ✅ DONE 2026-07-21 (reads only, 0 writes)

Safety pre-flight confirmed all backstops ON at runtime and observed them firing live (e.g. `[Lexi WRITE BLOCKED] ASANA_CREATE_A_TASK`).

1. **✅ Regression — all green, 0 real writes:**
   - pytest `-m "not live"`: **296 passed**.
   - `phase5_e2e_validation.py` (live reads, dry-run): **20/20 passed**, 0 failures, 16 write-blocked confirmations, no unexpected sends.
   - `rung0_realistic_scenarios.py` (10 Kory-style emails, live reads): **10/10 clean, 0 real writes**; split **7 OFFERED / 3 ASK_KORY** (defers: East-Coast early call, happy hour, lunch — all correct/conservative). Variance from the prior 8/2 (happy hour now defers) is within known LLM-triage variance; all outcomes safe.
2. **✅ Calendar read spot-check (this week, live):** structurally correct — all Mountain Time, both sources merged (`Kory Master Calendar (ALL)` + `Calendar`), 28 events; trainer block (Wed/Fri 6:30–8:30 AM), `[DO NOT MOVE]` inbox review, and WOB deep-work block all present. **Finding F1 (for Kory to eyeball in Outlook):** Sun 7/26 shows two facials at the same 2–3 PM slot ("Calming 60 Min Facial…" and "Facial envy", both "(copy)") — possible Master-rollup dedup gap or two genuine bookings.
3. **✅ Dashboard live-read UAT:** all 7 tabs' API routes return HTTP 200 with real live data matching the provided screenshots (Garnett Station priority, father-son-trips task, 11:15 AM briefing). Read-only confirmed (all GET; no-write-slugs passes). Lexi panel correctly reports **degraded** because the orchestrator worker heartbeat is stale (~25 h) — the worker isn't running locally; it runs in production. Correct degraded-state handling, not a bug.
4. **✅ Budget sane:** Composio **1% of the 200k/mo cap** (1,913 calls MTD); LLM ~$2.00 MTD on the dev key. All of today's live testing was negligible.

**Findings to carry forward (neither is a blocker; both are "confirm with Kory"):**
- **F1** — possible duplicate calendar events (two Sun facials) → confirm against Outlook; if real, tighten Master-rollup dedup.
- **F2** — `slot_engine.py:114` / `validators.py:343` intentionally exempt `dinner` from BOTH the weekend guard and the 6 PM cutoff (consistent in both places, so not a bug), but the dinner exemption skips the rule's "check family calendar first" condition. In rung0, dinner offered Sat 7/25 18:00. Confirm Kory is OK with weekend dinners being offered without a family-calendar check.

**Gate 2 (exit):** ✅ all suites green, 0 writes, budget sane; calendar/dashboard reads match ground truth (pending Kory's eyeball on F1).

## Phase 3 — Live sandbox write testing (every write pre-approved by you; ~1–2 days)

Run locally with VPS `lexi-hermes` stopped. Scenario content is Kory-realistic throughout.

- **Rung 1 — Calendar holds & lifecycle:** place hold on sandbox calendar → verify in Outlook → test conflict refusal → reminder staging → release/delete. (Re-proves the 7/20 test plus the full lifecycle.)
- **Rung 2 — Full email loop:** send a realistic scheduling email from a test account to lexi@ → webhook/poll ingestion → triage → Teams notification → `draft #1` → adaptive card (edit, Find new times, Save draft) → you approve → send to **allowlisted test recipient only** → holds placed → counterpart "accepts" → invite sent → holds cleaned. Repeat for the key scenario shapes: referral intro, PE-fund in-person, reschedule, dinner ask, East-Coast early call (expect defer-to-Kory), delegation-CC, and a rule-violating ask (expect refusal + escalation to you in Teams).
- **Rung 3 — Teams UAT:** all keyword commands (`brief`, `today`, `prebrief`, `pending`, `inbound`, `inbox review`, `unanswered`, `approve/reject/draft/skip #N`, human-label form), `/new` session reset (context clears, memory/drafts persist), "Remember that…" memory write + recall across sessions.
- **Rung 4 — Proactive jobs:** force-fire the 4:45 AM briefing (time override), 24 h reminder, hold-release reminder; verify Teams-push gating consistency.
- **Rung 5 — Asana/HubSpot writes (sandbox-marked):** create/complete/comment on a `TEST —` Asana task in a test section; HubSpot meeting-note on a test contact. Verify, then delete.
- **Rung 6 — Failure drills:** kill the worker mid-cycle (watchdog restart + heartbeat), simulate Composio 429/timeout (retry/backoff), unreachable `lexi-api` (dashboard panel degrades gracefully), DB backup + restore round trip.

**Gate 3 (exit):** every rung passed, zero unintended writes in audit log, all test artifacts cleaned up. **You sign off before anything touches the VPS.**

## Phase 4 — Production deployment, gates closed (~half day; your approval before each irreversible step)

1. Prep: choose final hostnames (`dash.…`, `agent.…`), point DNS at the VPS, write `.env.production` on the VPS (all write gates CLOSED, `LEXI_DRY_RUN` posture per runbook), dashboard env with `REQUIRE_AUTH=true`, strong `DASHBOARD_PASSWORD`/`AUTH_SECRET`, `LEXI_API_TOKEN` shared with the agent.
2. Stop stale June services; snapshot/back up existing VPS DB first.
3. `git pull` + `bash deploy/install.sh` (agent, API, watchdog, backups) + dashboard standalone build + `ceo-dashboard.service` + Caddy TLS.
4. Re-point **Azure bot messaging endpoint** and **Composio webhook** to the VPS URLs.
5. Smoke: boot banner shows closed posture; `/api/health` 200; Teams round trip; dashboard over HTTPS behind login; backups + watchdog timers firing.

**Gate 4 (exit):** production runs clean in read-only posture for **2–3 days** (briefings/notifications in Teams, dashboard in daily use, watchdog quiet, budget burn acceptable).

## Phase 5 — Go-live enablement ladder (one gate at a time, soak between; you flip each rung)

A → calendar **holds** live on Kory's calendar (each still Teams-approved) — soak 2–3 days.
B → **approved sends** from Lexi's mailbox to real counterparts — consider keeping the recipient allowlist populated with known counterparts for the first week even in production — soak ≥ 1 week.
C → **Asana/HubSpot live writes** (confirm-gated per action).
D → later/optional, separate decisions: outreach campaign sending, Heidi escalation email, any relaxation of approval gates. **Never enabled:** autonomous sends (`LEXI_ALLOW_IMMEDIATE_SEND`, `LEXI_AUTO_EXECUTE_ENABLED`).

## Phase 6 — Handoff & operations

- Deliver `KORY_USER_GUIDE.html` (update the login URL + any behavior deltas found in UAT).
- Ops card for you/Heidi: health URL, restart command, backup restore, watchdog behavior, monthly Composio/LLM cost review, rollback = `systemctl stop lexi-hermes` + `restore_lexi_db.sh` + re-close env gates.
- 30-day review: audit-log sampling of every send/hold vs approval, deferral-rate tuning, rules.py updates from Kory's rulings.

---

## Decisions I need from you (before the relevant phase)

| # | Decision | Needed by |
|---|---|---|
| D1 | Sandbox mailbox: reconnect a dedicated one in Composio, or keep using Lexi's own mailbox as sandbox | Phase 1 |
| D2 | Dashboard repo: commit inside this repo (matches joint-deploy runbook) or separate repo | Phase 1 |
| D3 | Production hostnames for dashboard + agent (and which domain) | Phase 4 |
| D4 | Keep recipient allowlist active for week 1 of production sends (recommended) | Phase 5 |
| D5 | Heidi escalation: stays OFF at launch (recommended) | Phase 5 |

**Estimated effort:** Phases 1–2 ≈ 1 day · Phase 3 ≈ 1–2 days (approval-paced) · Phase 4 ≈ half day · Phase 5 ≈ 1–2 weeks of calendar soak time with minimal hands-on work.
