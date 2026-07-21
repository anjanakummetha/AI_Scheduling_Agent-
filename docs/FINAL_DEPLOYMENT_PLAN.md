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

## Phase 1 — Code freeze & cleanup (no approvals needed; ~half day)

1. **Fix G3:** make `test:readonly` actually run (add `tsx` as devDependency or run under Node 22 with type-stripping); confirm it passes.
2. **Sandbox posture (G2):** decide — reconnect a dedicated sandbox mailbox in Composio, **or** formally adopt Lexi's own mailbox (`ca_4BTJ6d0O8sSZ`) as the sandbox target. Update `.env.testing`; remove the dead id.
3. **Repo structure decision (G1):** commit the dashboard as part of this repo (matches the joint-deploy runbook) or split to its own repo. Then commit everything in logical commits; audit `.gitignore` (logs/, `__pycache__`, `data/*.db`, scratch JSON reports, `node_modules`, all real `.env*`).
4. **Secret sweep:** verify no `.env`/keys ever entered git history; confirm `.env.production.example` and `.env.testing.example` are complete and placeholder-only.
5. **CI green:** push and confirm `.github/workflows/ci.yml` passes on the final tree (pytest + dashboard build + no-write-slugs + readonly test).
6. **Doc pass:** final review of `KORY_USER_GUIDE.html`; prune/mark stale docs (ngrok-era instructions) so the deploy runbook is the single source of truth.

**Gate 1 (exit):** CI green, working tree clean, sandbox connection valid.

## Phase 2 — Full local regression (hermetic + read-only live reads; ~half day)

1. Re-run: pytest (296), `phase5_e2e_validation.py` (expect 20/20 vs live reads, dry-run), `rung0_realistic_scenarios.py` (expect ≥8 offered / rest correct deferrals, 0 writes).
2. **Calendar read UAT (HANDOFF item):** compare Lexi's 45–60-day availability reads against the Outlook UI for ~5 spot-check days, including Master + work merge, kid-event dedupe, family Do-Not-Move blocks, MT timezone accuracy.
3. **Dashboard live-read UAT on the Mac:** run against real Outlook/Asana/LinkedIn + local `lexi-api`; walk all 7 tabs; verify briefing generation, prioritization engine output sanity, Inbox Intelligence counts vs real inbox, Lexi panel (online/holds/approvals), per-tab refresh, fallback banners, Composio budget consumption stays sane.

**Gate 2 (exit):** all suites green; spot checks match Outlook ground truth. *(Reads only — no approvals needed, but I'll report findings before Phase 3.)*

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
