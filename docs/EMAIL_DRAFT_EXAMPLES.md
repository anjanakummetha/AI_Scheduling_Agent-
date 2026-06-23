# Lexi Email Draft — Format & Examples

## Format rules (from `rules.py`)

| Rule | Implementation |
|------|----------------|
| Recipient TZ **first**, MT in parentheses | `app/scheduling/email_format.py` |
| Sign-off **Let's Win,** then **Kory** on next line | Never "Best", "Warmly", "Regards" |
| **2–3 bullet options** | Scheduling replies only |
| **Never mention YPO** in outgoing drafts | Enforced in LLM prompt + instructions |
| Wait **30 min** before drafting (human policy) | Orchestrator asks Kory first in Teams |

Run live preview:

```bash
.venv/bin/python scripts/preview_email_draft.py
```

---

## Example: diligence call (Project Paint style)

**Inbound**

- **From:** bill.heermann@newportadvisors.co  
- **Subject:** RE: diligence call and organization for Project Paint  
- **Body:** *Can we schedule a 60-minute diligence call next week?*

**Lexi draft (after Kory says yes)**

```
Hi Bill,

Happy to connect on Project Paint diligence.

Thanks for reaching out — a few options that work on my end:

• Wednesday, June 17 at 4:00–4:30 PM Eastern (2:00–2:30 PM MT)
• Thursday, June 18 at 5:00–5:30 PM Eastern (3:00–3:30 PM MT)
• Friday, June 19 at 3:00–3:30 PM Eastern (1:00–1:30 PM MT)

Let me know which works best and I can send a calendar invite.

Let's Win,
Kory
```

---

## Example: internal IFG sync (Mountain Time only)

**From:** Heidi.Heckler@iconicfounders.com — internal domain → MT only in line.

```
Hi Heidi,

Thanks for reaching out — a few options that work on my end:

• Thursday, June 18 at 2:00–2:30 PM MT
• Friday, June 19 at 10:00–10:30 AM MT

Let me know which works best and I can send a calendar invite.

Let's Win,
Kory
```

---

## Example: general (non-scheduling) reply

No times offered — acknowledgment only:

```
Hi Natalie,

Thanks for sending the ERRG summary — I've got it.

Let's Win,
Kory
```

---

## Hermes MCP

```text
lexi_preview_scheduling_email()
```

Returns the Project Paint example JSON for chat display.
