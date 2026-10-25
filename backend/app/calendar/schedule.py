"""Open times on each stylist's calendar."""

from datetime import datetime, timedelta

from googleapiclient.errors import HttpError
from sqlalchemy import select

from app.calendar.client import STAFF, calendar_id, service
from app.db.models import Staff
from app.db.session import SessionLocal
from app.salon_time import SALON_TZ, slot_is_past, slot_start

OPEN_MINUTES = 10 * 60
CLOSE_MINUTES = 20 * 60
STEP_MINUTES = 30


def spoken_clock(moment: datetime) -> str:
    """Format a salon time the way the rest of the app stores it, such as 2:00 PM."""
    return moment.strftime("%I:%M %p").lstrip("0")


def window(date_value: str, time_value: str, duration_min: int) -> tuple[datetime, datetime]:
    """Turn a date, clock time, and duration into a start and end in salon time."""
    text = time_value.strip()
    if " " in text:
        start = slot_start(date_value, text)
        if start is None:
            raise RuntimeError("That time was not understood.")
    else:
        hour, minute = (int(part) for part in text.split(":"))
        start = datetime.fromisoformat(date_value).replace(
            hour=hour, minute=minute, second=0, microsecond=0, tzinfo=SALON_TZ
        )
    return start, start + timedelta(minutes=duration_min)


def parse_opening(slot_id: str) -> tuple[str, str, str] | None:
    """Read a generated id ``ST01|2026-10-24|14:00`` into staff, date, and spoken time."""
    staff_id, separator, rest = slot_id.partition("|")
    date_value, separator_2, clock = rest.partition("|")
    if not separator or not separator_2 or staff_id not in STAFF:
        return None
    try:
        start, _ = window(date_value, clock, 0)
    except (RuntimeError, ValueError):
        return None
    return staff_id, date_value, spoken_clock(start)


def _day_bounds(date_value: str) -> tuple[datetime, datetime]:
    start = datetime.fromisoformat(date_value).replace(tzinfo=SALON_TZ)
    return start, start + timedelta(days=1)


def busy_on(staff_id: str, date_value: str) -> list[dict]:
    saved_id = calendar_id(staff_id)
    start, end = _day_bounds(date_value)
    body = {
        "timeMin": start.isoformat(),
        "timeMax": end.isoformat(),
        "timeZone": "Asia/Kolkata",
        "items": [{"id": saved_id}],
    }
    result = service().freebusy().query(body=body).execute()
    return result["calendars"][saved_id].get("busy", [])


def busy_blocks(staff_id: str, date_value: str, ignore_event_id: str | None = None) -> list[dict]:
    """Busy ranges for one stylist. A moved appointment can ignore its current event."""
    if not ignore_event_id:
        return busy_on(staff_id, date_value)
    start, end = _day_bounds(date_value)
    listed = (
        service()
        .events()
        .list(
            calendarId=calendar_id(staff_id),
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    blocks = []
    for event in listed.get("items", []):
        if event.get("id") == ignore_event_id or event.get("status") == "cancelled":
            continue
        start_at = event.get("start", {}).get("dateTime")
        end_at = event.get("end", {}).get("dateTime")
        if start_at and end_at:
            blocks.append({"start": start_at, "end": end_at})
    return blocks


def _aware(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=SALON_TZ)
    return moment


def overlaps(start: datetime, end: datetime, blocks: list[dict]) -> bool:
    for block in blocks:
        busy_start = _aware(datetime.fromisoformat(block["start"]))
        busy_end = _aware(datetime.fromisoformat(block["end"]))
        if start < busy_end and end > busy_start:
            return True
    return False


def _minutes(moment: datetime) -> int:
    return moment.hour * 60 + moment.minute


def ensure_hours(start: datetime, end: datetime) -> None:
    """Keep the whole visit inside 10:00 AM to 8:00 PM on the same day."""
    if end.date() != start.date() or _minutes(start) < OPEN_MINUTES or _minutes(end) > CLOSE_MINUTES:
        raise RuntimeError("Bookings are only available from 10:00 AM to 8:00 PM.")


def ensure_free(staff_id: str, start: datetime, end: datetime, ignore_event_id: str | None = None) -> None:
    """Refuse a second visit that overlaps this stylist's calendar."""
    if overlaps(start, end, busy_blocks(staff_id, start.date().isoformat(), ignore_event_id)):
        raise RuntimeError("That stylist already has a booking at this time.")


def _staff_names() -> list[tuple[str, str]]:
    with SessionLocal() as db:
        rows = db.execute(select(Staff.staff_id, Staff.name).order_by(Staff.name)).all()
    named = [(staff_id, name) for staff_id, name in rows if staff_id in STAFF]
    if named:
        return named
    return list(STAFF.items())


def openings_for_date(date_value: str, duration_min: int) -> list[dict]:
    """Open 30-minute starts on each stylist calendar that can fit this visit."""
    duration = duration_min if duration_min and duration_min > 0 else 60
    try:
        day = datetime.fromisoformat(date_value).replace(tzinfo=SALON_TZ)
    except ValueError:
        return []
    last_start = CLOSE_MINUTES - duration
    if last_start < OPEN_MINUTES:
        return []
    openings = []
    for staff_id, name in _staff_names():
        try:
            blocks = busy_blocks(staff_id, date_value)
        except KeyError:
            continue
        except HttpError:
            continue
        minute = OPEN_MINUTES
        while minute <= last_start:
            start = day.replace(hour=minute // 60, minute=minute % 60, second=0, microsecond=0)
            end = start + timedelta(minutes=duration)
            spoken = spoken_clock(start)
            if slot_is_past(date_value, spoken) or overlaps(start, end, blocks):
                minute += STEP_MINUTES
                continue
            openings.append(
                {
                    "slot_id": f"{staff_id}|{date_value}|{start.strftime('%H:%M')}",
                    "date": date_value,
                    "time": spoken,
                    "staff_id": staff_id,
                    "staff_name": name,
                    "status": "available",
                }
            )
            minute += STEP_MINUTES
    return openings
