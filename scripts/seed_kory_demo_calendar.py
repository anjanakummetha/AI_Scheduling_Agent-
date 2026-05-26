"""Seed Outlook with Kory-style demo calendar data.

The source calendar begins Sunday March 29, 2026. For this demo it is shifted to
begin Sunday May 3, 2026 so all scheduling tests are in the future from May 8.

Default mode is dry-run. Use `--execute` to write to Outlook.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import json
from pathlib import Path
import re
import sys
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.integrations.composio_client import execute_tool
from app.config import settings


PREFIX = "[DEMO KORY]"
SOURCE_START = date(2026, 3, 29)
TARGET_START = date(2026, 5, 3)
TIMEZONE = settings.outlook_timezone
SEED_LOG = ROOT / "data" / "kory_demo_calendar_seed_log.json"


RAW_CALENDAR_TEXT = """
March 29 (Sun): All Day: Stay at Kimpton Canary Hotel; All Day: Palm Sunday; 1:00pm: nolan work on deck; 2:05pm: Flight to Denver (UA 1740)
March 30 (Mon): 5:00am: Document food; 6:00am: Calls for today; 8:30am: KM Personal Training; 8:00am: CapDemo check in; 10:00am: IFG Deal + Pipeline review; 10:00am: Outreach Proposal Review; 11:15am: Justin White; 12:30pm: CapDemo check in (+5 hidden).
March 31 (Tue): 6:00am: kory work on deck; 8:30am: Dan Madden; 9:30am: Project point; 12:30pm: Redox Tech; 1:00pm: Newco Prep; 2:00pm: Record Video; 2:30pm: KM daily inbox review; 3:30pm: Intro Call Colby Durnin; 4:00pm: Kory - Dan Phillips.
April 1 (Wed): 6:00am: Call Michael McGrath; 8:30am: KM Personal Training; 9:00am: Chris Meyer; 9:30am: Jerry Schill; 10:30am: J.P. Morgan Private Bank; 11:00am: Shift 11a-3p; 11:30am: IFG Weekly Stand Up; 3:00pm: Kory | Joe; 4:00pm: Happy Hour Scott Johnson.
April 2 (Thu): 8:00am: YPO RM Grad Video Taping; 8:30am: Gastano Group - Restaurant Home Office; 9:00am: Brad Griffin; 10:00am: WDB [No scheduling]; 1:00pm: Kory Bryan; 2:00pm: Newco Plan; 3:00pm: KM daily inbox review.
April 3 (Fri): All Day: Good Friday; 6:30am: KM Personal Training; 8:30am: Prep for podcast; 9:00am: The Turn Podcast: Phil Cooper; 10:00am: Post podcast wrap-up; 10:30am: Patrick/Kory weekly sync; 11:30am: FC <> IFG Follow up; 1:00pm: Kory/Travis weekly check in (+4 hidden).
April 4 (Sat): 7:00am: integrate GPT; 8:30am: cancel credit cards; 11:00am: Haircut both; 12:00pm: Massage Kory; 1:00pm: Bike Ride; 5:00pm: Dinner with the Bergs.
April 5 (Sun): All Day: Easter Day; 8:00am: Ernie ruck; 7:00pm: Kory/Heidi - Check in.
April 6 (Mon): 6:00am: bring stuff for cells; 8:30am: Travis/Heidi check-in; 10:00am: IFG Deal + Pipeline review; 10:00am: ITG; 11:00am: Brew | Drew; 11:00am: Check-in Call: Martin McCormick (+2 hidden).
April 7 (Tue): All Day: Stay at Hyatt Centric Chicago; 8:00am: send joe sutano the ifg deal; 8:30am: Exit Denim; 9:30am: ITG; 11:30am: Coffee: Charlie Pappas; 1:00pm: Optional Newco Q&A.
April 8 (Wed): All Day: Stay at Hyatt Centric Chicago; All Day: Kory in Chicago; 8:30am: KM Personal Training; 10:00am: Call Nate; 11:00am: Mitchell Miller phone; 12:30pm: Kory / Brandon Lunch.
April 9 (Thu): All Day: Kory in Chicago; 8:30am: KM Personal Training; 1:25pm: Kristin bday; 1:00pm: Kory | Travis - hold; 5:15pm: Southwest flight.
April 10 (Fri): All Day: Natalia @ Family Wedding (Myrtle Beach); 8:30am: KM Personal Training; 8:30am: The Turn - VO Recording; 9:00am: ITG; 11:30am: No Scheduling Reserve; 2:30pm: KM daily inbox review; 3:30pm: Intro Call: Michael/Heidi sync (+1 hidden).
April 11 (Sat): 9:45am: Haircut nikki; 12:00pm: Brunch with Caley; 6:30pm: Dave and Renee Dinner.
April 12 (Sun): All Day: Natalia @ Family Wedding; All Day: Michael McGrath Birthday; mountains for 4th of july; install Lindy; Make cup; K-walk with Michelle; Liu.
April 13 (Mon): 8:30am: KM Personal Training; 8:20am: floral kory; 10:00am: IFG Deal + Pipeline review; 10:00am: Register right for Blackberry; 11:00am: Podcast Interview Prep; 11:30am: The Turn Podcast: Chris Lee; 1:00pm: Podcast Interview Prep; 1:15pm: Doug (+3 hidden).
April 14 (Tue): 6:00am: Walk on thread; 8:00am: Edee Drop Off; 8:30am: Intro session; 9:00am: Castille Construction; 10:00am: WDB; 11:30am: ITG Weekly Stand Up; 2:00pm: Kory/Lony/Heidi sync; 2:20pm: Monthly Touch Base (+2 hidden).
April 15 (Wed): All Day: Tax Day; 8:30am: KM Personal Training; 9:30am: Kory to call Nathan; 9:00am: Do Hex work; 11:30am: Monthly Check In; 12:45pm: Africa Conference Call; 2:00pm: Sujash Barman (+1 hidden).
April 16 (Thu): 6:00am: review claude AI dashboard; 8:00am: Edee Drop Off; 9:00am: Intro Call; 11:00am: Intro Call; 1:00pm: Intro Call; 2:30pm: KM daily inbox review (+1 hidden).
April 17 (Fri): 8:30am: KM Personal Training; 8:30am: IFG Interview: Arpana sync; 10:30am: Arpana sync; 12:15pm: Arpana sync; 12:30pm: Lunch with CRC; 1:15pm: lanch; 2:00pm: sync - Peter Hammond (+3 hidden).
April 18 (Sat): All Day: Maclain on Spring break; All Day: Stay at Mer Monte Hotel; All Day: Danny workout; 11:00am: Wells fargo Appt; 5:00pm: Tim's Bday; 7:40pm: Flight to Santa Barbara.
April 19 (Sun): All Day: Maclain on Spring break; All Day: Stay at Mer Monte Hotel; Kimberly.
April 20 (Mon): All Day: Maclain on Spring break; All Day: Stay at Mer Monte Hotel; All Day: Michael Kaplan's Birthday; 6:00am: Flight to Denver; 9:00am: WDB; 11:30am: The Roulette Group; 11:30am: Weekly Stand Up; 2:30pm: Realse cleaning (+4 hidden).
April 21 (Tue): All Day: Maclain on Spring break; All Day: ND @ EOS Conference; 5:00pm: YPO Pre Trip Call; 8:00am: Cap Demo call; 8:45am: Rabies vaccine; 9:00am: Touch Base; 10:30am: Intro Call; 11:30am: Intro Call (+4 hidden).
April 22 (Wed): All Day: Maclain on Spring break; All Day: ND @ EOS Conference; 7:00am: Capital Demo; 3:00pm: KM daily inbox review (+9 hidden).
April 23 (Thu): All Day: Maclain on Spring break; All Day: ND @ EOS Conference; All Day: Kory brake; 9:00am: intro call: Angelo; 9:30am: dan madden (+5 hidden).
April 24 (Fri): All Day: Maclain on Spring break; All Day: ND @ EOS Conference; All Day: Maclain Birthday; 10:00am: Danny workout; 6:00pm: Bday Dinner.
April 25 (Sat): All Day: Stay at Mer Monte Hotel.
April 26 (Sun): All Day: Maclain on Spring break; 8:00am: Free trial bloom ends today; 7:30am: AI intern scope build; 10:30am: Brunch @ Mongers; 11:00am: Family Brunch.
April 27 (Mon): 6:00am: Make mothers day plan; 8:30am: Electrical EPC; Natalle to call kory; 10:00am: Deal + Pipeline review; 11:30am: Onboarding; 1:15pm: Doug (+3 hidden).
April 28 (Tue): 9:00am: Proposal for act - Rob; 8:30am: KM Personal Training; 8:00am: Edee Drop Off; 9:00am: Board Meeting; 12:30pm: prep act proposal (+4 hidden).
April 29 (Wed): 5:00am: YPO prep; 8:30am: KM Personal Training; 8:00am: More Beaver Forum; 1:00pm: K & B with Liz R; 3:00pm: KM daily inbox review (+3 hidden).
April 30 (Thu): 6:30am: Wire money denver angels; 8:30am: Podcast interview prep; 9:30am: Podcast post interview block; 10:00am: WDB; 12:00pm: Kory (IFG) | Nick; 1:00pm: Catch up emails (+7 hidden).
May 1 (Fri): All Day: B & C Lazy U Ranch KM; 8:30am: work on comp agents; 8:30am: work on Dog Hirsch; 9:00am: walk dogs for call; 9:30am: Greg Hirsch; 10:30am: Weekly sync; 11:15am: Podcast interview prep; 12:00pm: Podcast interview (+2 hidden).
May 2 (Sat): 6:30pm: Pay credit cards; 7:00am: KM to review Boucher Blog article; 8:00am: Danny 805; 10:30am: Brunch at house; 1:00pm: Bday Party; 5:00pm: Parents night out; 5:30pm: Satchel's on 6th.
""".strip()


@dataclass(frozen=True)
class SeedEvent:
    source_date: date
    target_date: date
    title: str
    start: datetime
    end: datetime
    all_day: bool

    @property
    def seed_key(self) -> str:
        return f"{self.start.isoformat()}|{self.title}"


def main() -> None:
    load_dotenv(".env")
    parser = argparse.ArgumentParser(description="Seed Kory demo calendar into Outlook.")
    parser.add_argument("--execute", action="store_true", help="Create events in Outlook.")
    parser.add_argument("--limit", type=int, default=None, help="Optional max events to create.")
    args = parser.parse_args()

    events = parse_events()
    if args.limit:
        events = events[: args.limit]

    print(f"Source start: {SOURCE_START} -> Target start: {TARGET_START}")
    print(f"Events parsed: {len(events)}")
    print(f"Date range: {events[0].target_date} through {events[-1].target_date}")
    print("Mode:", "EXECUTE" if args.execute else "DRY RUN")

    for index, event in enumerate(events, start=1):
        seed_key = event.seed_key
        print(
            f"{index:03d}. {event.target_date} "
            f"{'ALL DAY' if event.all_day else event.start.strftime('%I:%M%p').lower()} "
            f"{event.title}"
        )
        if args.execute:
            created = load_seed_log()
            if seed_key in created:
                print(f"     skipped existing seed key: {seed_key}")
                continue
            event_id = create_outlook_event(event)
            created[seed_key] = {"event_id": event_id, "subject": event.title}
            save_seed_log(created)

    if not args.execute:
        print("\nDry run only. Re-run with --execute to write these events to Outlook.")


def parse_events() -> list[SeedEvent]:
    parsed: list[SeedEvent] = []
    for line in RAW_CALENDAR_TEXT.splitlines():
        if not line.strip():
            continue
        source_day, entries_text = parse_day_line(line)
        target_day = shift_date(source_day)
        parsed.extend(parse_day_entries(source_day, target_day, entries_text))
    return parsed


def parse_day_line(line: str) -> tuple[date, str]:
    match = re.match(r"^(March|April|May)\s+(\d{1,2})\s+\([A-Za-z]{3}\):\s*(.*)$", line.strip())
    if not match:
        raise ValueError(f"Could not parse day line: {line}")
    month_name, day_text, entries_text = match.groups()
    month = {"March": 3, "April": 4, "May": 5}[month_name]
    return date(2026, month, int(day_text)), entries_text.strip().rstrip(".")


def parse_day_entries(source_day: date, target_day: date, entries_text: str) -> list[SeedEvent]:
    events: list[SeedEvent] = []
    pending_untimed: list[str] = []
    for raw_entry in [entry.strip() for entry in entries_text.split(";") if entry.strip()]:
        all_day_match = re.match(r"^All Day:\s*(.+)$", raw_entry, re.IGNORECASE)
        time_match = re.match(r"^(\d{1,2}:\d{2}(?:am|pm)):\s*(.+)$", raw_entry, re.IGNORECASE)
        if all_day_match:
            events.append(make_all_day_event(source_day, target_day, all_day_match.group(1)))
        elif time_match:
            start_time = parse_time(time_match.group(1))
            title = clean_title(time_match.group(2))
            events.append(make_timed_event(source_day, target_day, start_time, title))
        else:
            pending_untimed.append(clean_title(raw_entry))

    for title in pending_untimed:
        if title:
            events.append(make_all_day_event(source_day, target_day, title))
    return events


def make_all_day_event(source_day: date, target_day: date, title: str) -> SeedEvent:
    start = datetime.combine(target_day, time.min)
    end = start + timedelta(days=1)
    return SeedEvent(source_day, target_day, prefixed(title), start, end, True)


def make_timed_event(source_day: date, target_day: date, start_time: time, title: str) -> SeedEvent:
    start = datetime.combine(target_day, start_time)
    duration = duration_for(title)
    return SeedEvent(source_day, target_day, prefixed(title), start, start + duration, False)


def create_outlook_event(event: SeedEvent) -> str | None:
    payload: dict[str, Any] = {
        "user_id": "me",
        "subject": event.title,
        "start": {"dateTime": event.start.isoformat(), "timeZone": TIMEZONE},
        "end": {"dateTime": event.end.isoformat(), "timeZone": TIMEZONE},
        "location": {"displayName": "Demo Calendar"},
        "body": {
            "contentType": "text",
            "content": (
                "Created for AI Scheduling Agent demo. "
                f"Original Kory calendar date: {event.source_date}."
            ),
        },
    }
    if event.all_day:
        payload["isAllDay"] = True
    result = execute_tool("OUTLOOK_CREATE_ME_EVENT", payload)
    data = result.get("data") if isinstance(result, dict) else None
    return data.get("id") if isinstance(data, dict) else None


def shift_date(source_day: date) -> date:
    return TARGET_START + (source_day - SOURCE_START)


def parse_time(value: str) -> time:
    return datetime.strptime(value.lower(), "%I:%M%p").time()


def clean_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title.strip().rstrip("."))
    return title


def prefixed(title: str) -> str:
    return title if title.startswith(PREFIX) else f"{PREFIX} {title}"


def duration_for(title: str) -> timedelta:
    text = title.lower()
    if "personal training" in text or "workout" in text:
        return timedelta(minutes=90)
    if "flight" in text:
        return timedelta(hours=2)
    if "happy hour" in text or "dinner" in text:
        return timedelta(minutes=90)
    if "lunch" in text or "brunch" in text or "coffee" in text:
        return timedelta(minutes=90)
    if "podcast" in text or "board meeting" in text or "wdb" in text or "no scheduling" in text:
        return timedelta(hours=1)
    if "deal + pipeline" in text or "weekly stand up" in text or "weekly sync" in text:
        return timedelta(hours=1)
    if "daily inbox" in text or "touch base" in text or "intro call" in text:
        return timedelta(minutes=30)
    return timedelta(minutes=45)


def load_seed_log() -> dict[str, Any]:
    if not SEED_LOG.exists():
        return {}
    return json.loads(SEED_LOG.read_text())


def save_seed_log(data: dict[str, Any]) -> None:
    SEED_LOG.parent.mkdir(parents=True, exist_ok=True)
    SEED_LOG.write_text(json.dumps(data, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
        sys.exit(130)
