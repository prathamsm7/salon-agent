"""In-memory state for one voice call: cart, shown lists, and a pending yes."""

from __future__ import annotations

from typing import Any

from app.voice.text_format import format_cart, format_options, format_slots


def new_session() -> dict[str, Any]:
    """Start a call with an empty cart and no appointment chosen yet."""
    return {
        "gender": None,
        "categories": [],
        "retrieved_services": [],
        "selected_services": [],
        "date": None,
        "time": None,
        "part_of_day": None,
        "preferred_staff": None,
        "available_slots": [],
        "booking_id": None,
        "booking_status": None,
        "user_id": None,
        "user_name": None,
        "conversation_id": None,
        "pending_slot_id": None,
        "pending_cancel_id": None,
        "pending_reschedule": None,
    }


def set_choice_list(session: dict, lines: list[str]) -> None:
    """Stage the on-screen list. It is sent after Tara finishes speaking."""
    text = "\n".join(line for line in lines if line is not None).strip()
    session["choice_list"] = text or None


def as_bool(value) -> bool:
    """Accept the boolean Deepgram sends, including the string form."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1"}
    return bool(value)


def apply_saved_booking(session: dict, booking: dict | None) -> None:
    """Copy a stored appointment into the live call so later tools see it."""
    if not booking:
        return
    session["booking_id"] = booking["booking_id"]
    session["booking_status"] = booking["stored_status"]
    session["date"] = booking["date"]
    session["time"] = booking["time"]
    session["preferred_staff"] = booking["staff_name"]
    if booking.get("services"):
        session["selected_services"] = booking["services"]


def context_summary(session: dict) -> str:
    """One snapshot of the cart, search results, and times currently shown."""
    return (
        f"Cart:\n{format_cart(session.get('selected_services') or [])}\n"
        f"Shown services:\n{format_options(session.get('retrieved_services') or [])}\n"
        f"Gender: {session.get('gender')}\n"
        f"Categories: {', '.join(session.get('categories') or []) or 'none'}\n"
        f"Date: {session.get('date')}\n"
        f"Time: {session.get('time')}\n"
        f"Staff: {session.get('preferred_staff')}\n"
        f"Shown slots:\n{format_slots(session.get('available_slots') or [])}"
    )


def extract_request(
    session: dict,
    gender: str | None = None,
    categories: list[str] | None = None,
    date: str | None = None,
    time: str | None = None,
    part_of_day: str | None = None,
    staff: str | None = None,
    **_,
) -> str:
    """Remember gender, services, date, time, or staff from the latest message."""
    from app.voice.catalog import normalize_gender

    g = normalize_gender(gender)
    if g:
        session["gender"] = g
    if categories:
        session["categories"] = categories
    if date:
        session["date"] = date
    if time:
        session["time"] = time
    if part_of_day:
        session["part_of_day"] = part_of_day
    if staff:
        session["preferred_staff"] = staff
    return (
        f"Gender: {session.get('gender')}\n"
        f"Categories: {', '.join(session.get('categories') or []) or 'none'}\n"
        f"Date: {session.get('date')}\n"
        f"Time: {session.get('time')}\n"
        f"Part of day: {session.get('part_of_day')}\n"
        f"Staff: {session.get('preferred_staff')}"
    )


EXTRACT_FUNCTION = {
    "name": "extract_request",
    "description": "Save gender, categories, date, time, part of day, or staff from this message.",
    "parameters": {
        "type": "object",
        "properties": {
            "gender": {"type": "string", "enum": ["Male", "Female", "Unisex"]},
            "categories": {"type": "array", "items": {"type": "string"}},
            "date": {"type": "string", "description": "YYYY-MM-DD"},
            "time": {"type": "string", "description": "h:mm AM/PM"},
            "part_of_day": {"type": "string", "enum": ["morning", "afternoon", "evening"]},
            "staff": {"type": "string", "description": "Staff name or any"},
        },
        "required": [],
    },
}
