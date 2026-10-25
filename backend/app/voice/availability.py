"""Which stored slots are still open for a date, time, part of day, or stylist."""

from __future__ import annotations

from app.calendar.schedule import openings_for_date
from app.salon_time import slot_is_past, slot_start
from app.voice.session_state import set_choice_list
from app.voice.text_format import format_slots

MAX_SHOWN = 10


def find_available_slots(
    slots: list[dict],
    date_value: str,
    time_value: str | None = None,
    staff_pref: str | None = None,
    any_staff: bool = False,
    part_of_day: str | None = None,
    limit: int = 8,
) -> list[dict]:
    """Keep slots that match the request and have not already started."""
    filtered = []
    for slot in slots:
        if slot.get("status") != "available" or slot.get("date") != date_value:
            continue
        if slot_is_past(date_value, slot.get("time") or ""):
            continue
        if time_value and slot.get("time") != time_value:
            continue
        hour = None
        start = slot_start(slot.get("date") or "", slot.get("time") or "")
        if start is not None:
            hour = start.hour
        if part_of_day == "morning" and (hour is None or hour >= 12):
            continue
        if part_of_day == "afternoon" and (hour is None or hour < 12 or hour >= 17):
            continue
        if part_of_day == "evening" and (hour is None or hour < 17):
            continue
        if not any_staff and staff_pref:
            normalized = staff_pref.strip().lower()
            names = {
                str(slot.get("staff_id", "")).lower(),
                str(slot.get("staff_name", "")).lower(),
            }
            if normalized not in names:
                continue
        filtered.append(
            {
                "slot_id": slot.get("slot_id"),
                "date": slot.get("date"),
                "time": slot.get("time"),
                "staff_id": slot.get("staff_id"),
                "staff_name": slot.get("staff_name"),
            }
        )
    filtered.sort(
        key=lambda item: (
            item["date"],
            slot_start(item["date"], item["time"]) or "",
            item["staff_name"],
        )
    )
    return filtered[:limit]


def nearest_slots(
    slots: list[dict],
    date_value: str,
    time_value: str,
    staff_pref: str | None,
    any_staff: bool,
) -> list[dict]:
    """Up to 10 open times closest to the clock time that was not available."""
    pool = find_available_slots(
        slots,
        date_value=date_value,
        staff_pref=staff_pref,
        any_staff=any_staff,
        limit=500,
    )
    target = slot_start(date_value, time_value)
    if target is None:
        return pool[:MAX_SHOWN]

    def distance(item: dict) -> int:
        start = slot_start(item["date"], item["time"])
        if start is None:
            return 10**9
        return abs(int((start - target).total_seconds()))

    pool.sort(key=lambda item: (distance(item), item["time"], item["staff_name"]))
    return pool[:MAX_SHOWN]


def check_availability(
    session: dict,
    date: str | None = None,
    time: str | None = None,
    staff: str | None = None,
    part_of_day: str | None = None,
    **_,
) -> str:
    """List open calendar times and put the same list on screen."""
    date_value = date or session.get("date")
    if not date_value:
        return "Which date would you like for the appointment?"

    part = part_of_day or (None if time else session.get("part_of_day"))
    if time and part_of_day:
        return "Do you want that exact time, or any time in that part of the day?"

    if date:
        session["date"] = date
    if time:
        session["time"] = time
    if part_of_day:
        session["part_of_day"] = part_of_day
    if staff:
        session["preferred_staff"] = staff

    staff_pref = staff or session.get("preferred_staff")
    any_staff = bool(staff_pref and staff_pref.strip().lower() == "any")
    duration = sum(
        int(item.get("duration_min") or 0) for item in session.get("selected_services") or []
    )
    try:
        open_slots = openings_for_date(date_value, duration)
    except RuntimeError:
        return "The schedule could not be read right now. Ask them to try again."
    matched = find_available_slots(
        open_slots,
        date_value=date_value,
        time_value=time,
        staff_pref=None if any_staff else staff_pref,
        any_staff=any_staff,
        part_of_day=None if time else part,
        limit=MAX_SHOWN,
    )
    nearby = False
    if time and not matched:
        matched = nearest_slots(
            open_slots,
            date_value,
            time,
            staff_pref=None if any_staff else staff_pref,
            any_staff=any_staff,
        )
        nearby = True
        closest = matched[0]["time"] if matched else None
        if closest:
            content = (
                f"No slots are open at {time} on {date_value}. "
                f"The nearest open time is {closest}.\n"
                + format_slots(matched)
            )
        else:
            content = f"No slots are open at {time} on {date_value}."
    else:
        content = format_slots(matched)
    session["available_slots"] = matched
    panel = [f"Open times on {date_value}", ""]
    for number, slot in enumerate(matched, start=1):
        panel.append(f"{number}) {slot.get('staff_name')} at {slot.get('time')}")
    set_choice_list(session, panel if matched else [])
    if nearby:
        return (
            content
            + "\n\nTell them that time is not open. Suggest only the nearest time, "
            "and ask them to choose from the short list on screen. "
            "Do not read the list aloud. Do not offer a time that is not in this list."
        )
    return (
        content
        + "\n\nSay only that you found open times and ask them to choose from the list. "
        "Do not read each time aloud. Do not offer a time that is not in this list."
    )


AVAILABILITY_FUNCTION = {
    "name": "check_availability",
    "description": "List open slots. time is h:mm AM/PM. Use part_of_day when there is no clock time.",
    "parameters": {
        "type": "object",
        "properties": {
            "date": {"type": "string", "description": "YYYY-MM-DD"},
            "time": {"type": "string", "description": "h:mm AM/PM"},
            "staff": {"type": "string"},
            "part_of_day": {"type": "string", "enum": ["morning", "afternoon", "evening"]},
        },
        "required": [],
    },
}
