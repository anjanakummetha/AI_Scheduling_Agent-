# Lexi Test Results Report

**Generated:** 2026-07-21 19:17 UTC
**Scope:** Full project except Teams/Azure connection (deferred to deploy day)

## Summary

| Metric | Count |
|--------|-------|
| Total cases | 30 |
| PASS | 15 |
| FAIL | 0 |
| SKIP | 15 |

**Overall:** ALL PASSED

## Pilot configuration

- **Read:** Kory Outlook (inbox + calendar)
- **Write:** anjanakummetha@outlook.com (loopback email + calendar holds)
- **Inbound:** Every email → ask before draft; scheduler (slots+holds) only for scheduling intents

## Results by phase

### Phase 1 — Inbound ask-before-draft

| ID | Test | Status | Detail |
|----|------|--------|--------|
| P1-01 | Inbound reply-prompt decision (live LLM) | SKIP | skipped |
| P1-02 | Scheduler not auto-run on ingest | PASS | False |
| P1-03 | Non-scheduling email creates proposal | PASS | id=3 |
| P1-04 | Decline reply path | PASS | no_reply_needed |
| P1-05 | Scheduling draft after yes (live LLM) | SKIP | skipped |

### Phase 2 — Kory rules validators

| ID | Test | Status | Detail |
|----|------|--------|--------|
| P2-01 | Reject 7pm pitch slot (6pm cutoff) | PASS | ['Option 1 (Thursday 19:00 MT): after 6 PM is only allowed for planned dinners.'] |
| P2-02 | Accept 1pm pitch slot | PASS |  |
| P2-03 | Allow 7pm dinner slot | PASS |  |
| P2-04 | Reject Saturday coffee | PASS | ['Option 1 (Saturday 10:00 MT): weekend meetings are not allowed by default.'] |
| P2-05 | Reject Monday trainer block | PASS | ["Option 1 (Monday 07:00 MT): overlaps hard block 'Trainer Workout' (06:30–08:00 Monday)."] |
| P2-06 | Reject Monday Doug block | PASS | ["Option 1 (Monday 13:30 MT): overlaps hard block 'Doug (Executive Coach)' (13:15–14:15 Monday)."] |
| P2-07a | kory_approves_all enabled | PASS |  |
| P2-07b | auto_execute disabled | PASS |  |
| P2-07c | immediate_send disabled | PASS |  |
| P2-07d | Unapproved send blocked | PASS |  |

### Phase 3 — Live Composio (read Kory, write sandbox)

| ID | Test | Status | Detail |
|----|------|--------|--------|
| P3-01 | Pilot config read Kory / write sandbox | SKIP | skipped (--ci) |
| P3-02 | Read Kory inbox | SKIP | skipped (--ci) |
| P3-03 | Read Kory calendar 7d | SKIP | skipped (--ci) |
| P3-04 | Sandbox loopback email send | SKIP | skipped (--ci) |

### Phase 4 — Kory email pattern triage

| ID | Test | Status | Detail |
|----|------|--------|--------|
| KY-01 | Investor diligence call (deal scheduling) | SKIP | skipped (no --skip-live-llm) |
| KY-02 | Coffee / partnership (typical external ask) | SKIP | skipped (no --skip-live-llm) |
| KY-03 | Internal IFG sync | SKIP | skipped (no --skip-live-llm) |
| KY-04 | Meeting summary (no scheduling reply needed) | SKIP | skipped (no --skip-live-llm) |
| KY-05 | YPO newsletter digest | SKIP | skipped (no --skip-live-llm) |
| KY-06 | Dinner + investor (high priority) | SKIP | skipped (no --skip-live-llm) |

### Phase 5 — Integration scripts

| ID | Test | Status | Detail |
|----|------|--------|--------|
| P5-01 | Mock pipeline | PASS |  |
| P5-02 | Sandbox integration | SKIP | skipped (--ci) |
| P5-04 | Stack verify | SKIP | skipped (--ci) |
| P5-05 | Live E2E staging | SKIP | skipped (--ci) |
| P5-03 | MCP smoke | PASS |  |

## Deferred (deploy tomorrow)

- Azure Bot messaging endpoint → Hermes `:3978`
- Hostinger VPS + TLS reverse proxy
- Composio Hermes OAuth in production Hermes session ([composio.dev/hermes](https://composio.dev/hermes))

## Hermes dual MCP setup

```bash
.venv/bin/python scripts/setup_hermes_mcp.py
```

1. Paste composio.dev/hermes setup into Hermes chat
2. Merge Lexi + Composio MCP in `~/.hermes/config.yaml`
3. Load `agent_instructions.txt`
