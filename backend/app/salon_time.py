"""Salon clock helpers. Appointments are scheduled in Asia/Kolkata."""

from datetime import datetime
from zoneinfo import ZoneInfo

SALON_TZ = ZoneInfo("Asia/Kolkata")


def clock_hour(time_value: str) -> int | None:
    """Turn a spoken time such as '2:00 PM' into a 24-hour hour, or None."""
    try:
        clock, meridiem = time_value.strip().split()
        hour = int(clock.split(":")[0])
    except (AttributeError, ValueError):
        return None
    meridiem = meridiem.upper()
    if meridiem == "PM" and hour != 12:
        hour += 12
    if meridiem == "AM" and hour == 12:
        hour = 0
    return hour


def salon_now() -> datetime:
    """Current time in Asia/Kolkata, which is the salon's clock."""
    return datetime.now(SALON_TZ)


def spoken_date(date_value: str | None) -> str:
    """Turn ``2026-10-19`` into a date Tara can say, such as ``Monday, October 19``."""
    if not date_value:
        return ""
    try:
        year, month, day = (int(part) for part in date_value.split("-"))
        moment = datetime(year, month, day)
    except (TypeError, ValueError):
        return date_value
    return f"{moment.strftime('%A')}, {moment.strftime('%B')} {moment.day}"


def slot_start(date_value: str, time_value: str) -> datetime | None:
    """Combine a slot date and spoken time into one timezone-aware start."""
    hour = clock_hour(time_value)
    if hour is None:
        return None
    try:
        minute = int(time_value.strip().split()[0].split(":")[1])
        year, month, day = (int(part) for part in date_value.split("-"))
    except (IndexError, ValueError):
        return None
    return datetime(year, month, day, hour, minute, tzinfo=SALON_TZ)


def slot_is_past(date_value: str, time_value: str, now: datetime | None = None) -> bool:
    """True when the slot's calendar day or start time is already behind."""
    now = now or salon_now()
    if date_value != now.date().isoformat():
        return date_value < now.date().isoformat()
    start = slot_start(date_value, time_value)
    return start is not None and start <= now
