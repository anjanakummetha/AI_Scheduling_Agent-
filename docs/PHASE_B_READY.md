# Phase B Ready — Teams / Hermes UAT

**Status:** Ready with safety locks ON  
**Gate script:** `scripts/verify_phase_b_ready.py`  
**Report:** `docs/PHASE_B_READY_REPORT.json`

## What was finalized (pre–Phase B)

| Area | Implementation |
|------|----------------|
| **LLM** | `claude-sonnet-4-6` (tool-use, ~200k context, best cost/accuracy for Lexi) |
| **Safety** | `LEXI_DRY_RUN`, Kory read-only, outbound blocked, lexi@ off |
| **Long-term DB** | Auto prune audit (180d), session TTL (7d), raw body trim, VACUUM |
| **Learning** | `approval_feedback` table + `kory_memory` facts |
| **Context caps** | Session JSON 32k chars, calendar 80 events, search 1s throttle |
| **Asana** | Reservation Reminders board path OK (dry-run during UAT) |
| **Calendars** | Master + Calendar conflict merge verified |
| **Rules** | Phase 2 validator suite 30/30 |

## Per chat session limits

See `docs/LONG_CONTEXT_LIMITS.json`:

- **Hermes thread:** ~200k tokens (model window)
- **scheduling_session:** 32k chars max (auto-compacts)
- **Calendar tool:** 80 busy events max
- **Search:** 1 second minimum between Composio Search calls
- **Guidance:** New chat per task; ~25 tool turns then summarize + fresh chat

## Phase B start checklist

```bash
.venv/bin/python scripts/setup_hermes_mcp.py
# Load agent_instructions.txt in Hermes
.venv/bin/python scripts/verify_phase_b_ready.py
```

1. Start Hermes gateway (worker embeds automatically)
2. DM Hermes — `help`, `pending`
3. Test delegation CC → Teams card
4. Test editable approval card (Save / Send blocked by dry run)
5. Test `lexi_research_person` for an upcoming meeting

**Do not unlock sends** until after Phase B sign-off.
