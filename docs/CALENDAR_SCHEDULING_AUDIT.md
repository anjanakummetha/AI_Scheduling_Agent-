# Phase 0 — Composio Calendar Baseline Audit

**Date:** 2026-06-23  
**Account:** Kory Mitchell (`kory.mitchell@iconicfounders.com`) via Composio  
**Status:** Phase 0 complete — **do not proceed to Phase 1 until Kory approves**

---

## Executive summary

Lexi can **read and write** Kory’s primary work calendar (`Calendar`) and personal rollup (`Kory Master Calendar (ALL)`). Four calendars are visible on the Composio Graph connection; **four M365 group calendars in the Outlook sidebar are not on the API** and remain flagged as unavailable.

After the intelligence layer (dedupe, kid-only skip, copy handling), **171 of 276 raw Master+work events in the next 30 days are treated as non-blocking** — mostly duplicate `(copy)` entries and kid activities. **105 events block** Kory for scheduling in that window.

**Write routing resolves correctly:** business holds/invites → `Calendar`.

---

## What Composio can see

### Calendars on the account (read + write)

| Calendar | can_edit | In conflict read set | Role |
|----------|----------|----------------------|------|
| **Calendar** | ✅ | ✅ | Work — primary write target |
| **Kory Master Calendar (ALL)** | ✅ | ✅ | Personal/family rollup |
| Birthdays | ❌ | ❌ | Informational only |
| Kory's tasks - My workspace | ✅ | ❌ | Task list, not used for conflicts |

### NOT visible via Composio (configured as `optional_group_calendars`)

These appear in Outlook’s sidebar but **do not resolve** on Kory’s Graph/Composio connection:

- IFG Team  
- Kory & Heidi only  
- Deal Activity  
- Daily CEO Update  

**Impact:** Lexi cannot read these calendars directly. Relevant blocks may still appear as `(copy)` entries on Master or on work `Calendar`. Lexi flags them as `calendars_unavailable` in scheduling context.

### Configured vs resolved IDs

Both conflict calendars resolve with `can_edit=true`. Primary/default write: **Calendar**.  
See `docs/CALENDAR_VERIFY_REPORT.json` for Graph calendar IDs.

---

## Raw vs intelligent blocking (merged read set)

Horizon is UTC-based from audit run time (2026-06-23).

| Horizon | Range | Raw blocking (approx.) | After intelligence | Skipped (non-blocking) | By class |
|---------|-------|------------------------|--------------------|-----------------------|----------|
| **30d** | Jun 23 → Jul 23 | ~276 busy events loaded | **105** | **171** | work 59, family DNM 18, unknown 25, travel 2, personal 1 |
| **60d** | Jun 23 → Aug 22 | — | **170** | **316** | work 92, family DNM 40, travel 3, unknown 34, personal 1 |
| **120d** | Jun 23 → Oct 21 | — | **231** | **476** | work 135, family DNM 46, travel 5, unknown 44, personal 1 |

**14-day raw sample (before dedupe):**

| Calendar | Blocking events |
|----------|-----------------|
| Calendar (work) | 38 |
| Kory Master Calendar (ALL) | 54 |
| Birthdays | 0 |
| Kory's tasks | 0 |

Master has ~40% more raw blocking events than work alone because it includes family, travel, and `(copy)` duplicates.

---

## Classification spot-check (Master, 30 days)

| Class | Count | Notes |
|-------|-------|-------|
| duplicate_copy | 48 | Work items already on `Calendar` — correctly skipped |
| unknown_blocking | 45 | **Phase 1 target** — mostly travel/family dinners without clear labels |
| family_do_not_move | 18 | `KM daily inbox review [DO NOT MOVE]` copies |
| travel_blocking | 2 | Flights detected |
| work_blocking | 2 | Placeholder diligence, lunch hold |
| kid_only_non_blocking | 2 | Maclain @ Liz, Maclain Riding Lesson |
| personal_kory_blocking | 1 | KM Personal Training Session |

### Examples that work today

- **Kid-only (non-blocking):** `Maclain @ Liz (copy)`, `Maclain Riding Lesson (copy)`  
- **Personal Kory (blocking):** `KM Personal Training Session (copy)`  
- **Family hard block:** `KM daily inbox review [DO NOT MOVE] (copy)`  
- **Travel:** `Flight to Washington (UA 2023) (copy)`  
- **Work dedupe:** `WOB (copy)`, `HOLD: Intro call w/ Steve Quinn (copy)` → skipped as duplicate of work cal

### Examples that need Phase 1 tuning

- Cape Town trip items (tours, hotel, dinners) → currently **unknown_blocking**; should be **travel_blocking** or family personal depending on Kory attendance  
- `Kory Mitchell and Brad Beldon (copy)` → **unknown_blocking** but is a work intro (should dedupe or classify as work)  
- Events with **KM** or **Kory** in the title are mixed: some are work meetings, some personal — **cannot rely on initials alone**

---

## KM / Kory labeling pattern scan (Master, 30d)

Kory often labels personal/family items with **"KM"** or his name. This is a **useful signal, not a rule.**

| Pattern | Count (30d) | Behavior today |
|---------|-------------|----------------|
| Title contains `KM` or starts with `Kory` | 28 | Mixed: training + inbox DNM block; work intros skipped as duplicate; some work copies still unknown |
| Blocking without KM/Kory in title | 0* | *After copy strip — travel emojis/tours dominate unknown set |

**Design for Phase 1 (per Kory):**

1. **`KM` / `KM ` prefix** → lean toward `personal_kory_blocking` *unless* work signals (IFG, intro, hold, Teams, etc.) or kid-only patterns win.  
2. **`[DO NOT MOVE]`** → always `family_do_not_move` (already implemented).  
3. **Kid names (Maclain, Gracie)** without Kory logistics → `kid_only_non_blocking` (already implemented).  
4. **Travel emojis / hotel / flight / city tours** → `travel_blocking`.  
5. **Never block solely on "Kory" in title** — many work meetings include his name.

---

## Gap analysis

| Gap | Severity | Phase |
|-----|----------|-------|
| Group calendars not on Composio API | Medium | 0 documented; may need IT/Graph subscription |
| 25–44 `unknown_blocking` per horizon | High | 1 — classification rules |
| Travel/family dinner heuristics (emoji, restaurant) | High | 1 |
| KM as soft signal vs hard rule | Medium | 1 |
| `outbound_agent.py` still uses 14-day horizon | Medium | 1 |
| Full `rules.py` validators not wired to slot engine | High | 3 |

---

## What Lexi can do today (Phase 0 baseline)

✅ List all Composio-visible calendars  
✅ Read work + Master for 30–120 day horizons (chunked)  
✅ Dedupe Master `(copy)` vs work Calendar  
✅ Skip kid-only Master events for business scheduling  
✅ Detect DO NOT MOVE, training, flights  
✅ Resolve write target → work `Calendar`  
✅ Flag missing group calendars  

❌ Direct read of IFG Team / Heidi / Deal / CEO calendars  
❌ Perfect classification of travel weeks and ambiguous Master items  
❌ Full Kory rules engine on proposed slots (Phase 3)  

---

## Commands to reproduce

```bash
# Quick verify
.venv/bin/python scripts/verify_calendars_read.py

# Full context load (uses intelligence layer)
.venv/bin/python -c "
from dotenv import load_dotenv; load_dotenv('.env')
from app.scheduling.calendar_context import load_scheduling_calendar_context
import json
ctx = load_scheduling_calendar_context(horizon_days=30)
print(json.dumps({'blocking': len(ctx['busy_events']), 'summary': ctx.get('busy_summary')}, indent=2))
"
```

---

## Next step

**Phase 1** (awaiting go-ahead): tighten classification — KM soft signal, travel week detection, work-name dedupe on Master, wire extended horizon everywhere, add regression tests from this audit’s examples.
