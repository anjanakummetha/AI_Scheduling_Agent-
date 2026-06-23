# Phase A Local Test Report

Generated: `2026-06-17T20:07:07.290279+00:00`

## Safety locks

- UAT env OK: **NO — fix .env**

## Summary

- **7/12** suites passed

- [FAIL] UAT safety env locks
- [FAIL] Read-only deploy locks
- [FAIL] Pre-Kory switch (read-only)
- [PASS] Approval safety
- [PASS] MCP tools smoke
- [FAIL] Lexi pipeline (mocked)
- [FAIL] Kory phase suite
- [PASS] Context + rate limits
- [PASS] Long context + retention
- [PASS] Unit tests (all)
- [PASS] Graceful failure probes
- [PASS] DB health

## Failures

### UAT safety env locks
### Read-only deploy locks
### Pre-Kory switch (read-only)
### Lexi pipeline (mocked)
```
[lexi] Database verified: /Users/anjanakummetha/Downloads/IFG 2026 Summer Internship/AI_Scheduling_Agent/data/lexi.db
[lexi] Tables (8): approval_feedback, approvals, audit_log, email_threads, holds, kory_memory, proposals, scheduling_sessions
[lexi] Indexes (11): idx_approval_feedback_created, idx_approval_feedback_proposal, idx_approvals_proposal_id, idx_audit_log_reference_id, idx_audit_log_timestamp, idx_email_threads_thread_id, idx_holds_proposal_id, idx_kory_memory_fact_key, idx_proposals_status, idx_proposals_thread_id, idx_scheduling_sessions_status
[lexi] Schema initialization complete.

```
### Kory phase suite
```
p/orchestrator.py", line 249, in _handle_inbound_stream_locked
    proposal_id = process_new_email(raw_email)
  File "/Users/anjanakummetha/Downloads/IFG 2026 Summer Internship/AI_Scheduling_Agent/app/agents/triage_agent.py", line 180, in process_new_email
    _maybe_dispatch_asana_booking_reminder(
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^
        conn,
        ^^^^^
    ...<2 lines>...
        intent=triage.intent,
        ^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "/Users/anjanakummetha/Downloads/IFG 2026 Summer Internship/AI_Scheduling_Agent/app/agents/triage_agent.py", line 486, in _maybe_dispatch_asana_booking_reminder
    if os.getenv("LEXI_ASANA_AUTO_CREATE", "false").lower() not in {"1", "true", "yes"}:
       ^^
NameError: name 'os' is not defined. Did you forget to import 'os'?

```
