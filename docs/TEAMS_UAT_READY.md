# Teams UAT readiness checklist

**Built:** 2026-07-16  
**Constraint honored:** No live writes to Outlook / HubSpot / Asana during automated tests. All Composio writes blocked when `LEXI_DRY_RUN=true`.

## New features (code complete)

| Feature | Teams / Hermes | Notes |
|--------|----------------|-------|
| `unanswered` | `lexi_unanswered_brief` | Read-only inbox scan |
| `today` | `lexi_today_calendar` | Read-only calendar |
| `prebrief` | `lexi_prebrief` | Who introduced + optional research |
| `brief` | `lexi_daily_ceo_briefing` | Full morning package |
| 4:45 AM MT job | orchestrator cycle | Idempotent; respects `LEXI_SUPPRESS_TEAMS_PUSH` |
| 24h Kory nudge | orchestrator cycle | Pending / awaiting_reply >24h |
| Email to lexi@ | ingress router | don't schedule / brief / asana / hubspot / remember |
| Who introduced | `introducer.py` + recipient_profiles | Parsed on new proposals |
| Asana chat | `lexi_list_asana_tasks`, create/complete (gated) | Simulated when Asana unavailable |
| HubSpot | `lexi_hubspot_*` tools | Staged batches only until approve + dry_run off |

## Before Kory tests in Teams

1. Set in `.env` (your machine):
   - `HUBSPOT_COMPOSIO_CONNECTION_ID=ca_jdY18Wb0L46M`
   - `LEXI_TEAMS_INBOUND_NOTIFY_MODE=delegation_and_followups` (or keep `delegation_only` if you only want CC'd mail)
   - `LEXI_DRY_RUN=true` for first Teams pass (recommended)
   - `LEXI_SUPPRESS_TEAMS_PUSH=false` when you want real cards
   - `LEXI_WEBHOOK_PUBLIC_URL` + worker running
2. Register Teams conversation: `lexi_register_teams_conversation`
3. Hermes running on :3978 with Lexi MCP

## Teams test script (you)

1. `brief` — morning package  
2. `unanswered` / `today` / `prebrief`  
3. CC lexi@ on scheduling email → approval card  
4. Email lexi@: "don't schedule with X"  
5. `pending` / approve flow  
6. HubSpot: ask Hermes for cleanup proposals (read-only staging)  
7. Asana: list due today (read); create only with confirm=true after you approve  

## Automated tests

- **222 passed**, 3 pre-existing failures (`test_lexi_draft_opening`, `test_lexi_email_format`, `test_lexi_reply_resolve`)
- New suites: `test_briefings_teams_shortcuts`, `test_lexi_mail_intent`, `test_hubspot_staging`, `test_kory_briefings`

## Still deferred

- BCC on scheduling  
- CEO dashboard sync  
- LinkedIn scraping (use HubSpot CRM Sync path)
