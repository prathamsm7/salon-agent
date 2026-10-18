"""Which stored slots are still open for a date, time, part of day, or stylist."""

from __future__ import annotations

from app.db.slots import slots_for_date
from app.salon_time import clock_hour, slot_is_past
from app.voice.session_state import set_choice_list
from app.voice.text_format import format_slots


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
        hour = clock_hour(slot.get("time") or "")
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
        key=lambda item: (item["date"], clock_hour(item["time"]) or 0, item["staff_name"])
    )
    return filtered[:limit]


def check_availability(
    session: dict,
    date: str | None = None,
    time: str | None = None,
    staff: str | None = None,
    part_of_day: str | None = None,
    **_,
) -> str:
    """List open database slots and put the same list on screen."""
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
    open_slots = slots_for_date(date_value)
    matched = find_available_slots(
        open_slots,
        date_value=date_value,
        time_value=time,
        staff_pref=None if any_staff else staff_pref,
        any_staff=any_staff,
        part_of_day=None if time else part,
        limit=8 if time else 24,
    )
    if time and not matched:
        matched = find_available_slots(
            open_slots,
            date_value=date_value,
            time_value=None,
            staff_pref=None if any_staff else staff_pref,
            any_staff=any_staff,
            limit=24,
        )
        content = f"No slots are open at {time} on {date_value}.\n" + format_slots(matched)
    else:
        content = format_slots(matched)
    session["available_slots"] = matched
    panel = [f"Open times on {date_value}", ""]
    for number, slot in enumerate(matched, start=1):
        panel.append(f"{number}) {slot.get('staff_name')} at {slot.get('time')}")
    set_choice_list(session, panel if matched else [])
    return (
        content
        + "\n\nSay only that you found open times and ask them to choose from the list. "
        "Do not read each time aloud."
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
