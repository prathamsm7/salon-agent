"""Book, list, cancel, and reschedule the signed-in customer's appointments."""

from __future__ import annotations

from app.db.bookings import booking_for_user, cancel_booking, confirm_booking, reschedule_booking, user_bookings
from app.db.errors import VoiceDenied
from app.voice.session_state import apply_saved_booking, as_bool
from app.voice.text_format import format_cart, format_slots


_CODE_NOTE = "Do not read this booking code aloud. Use it only inside a function call."


def _format_saved(items: list[dict], label: str) -> str:
    """One block of upcoming or past appointments, with ids for later tool calls."""
    if not items:
        return f"{label}: none."
    lines = [f"{label}:"]
    for index, item in enumerate(items, start=1):
        services = ", ".join(service["name"] for service in item["services"]) or "saved services"
        lines.append(
            f"{index}. {item['staff_name']} at {item['time']} on {item['date']} — {services} ({item['status']})\n"
            f"   booking_code: {item['booking_id']}. {_CODE_NOTE}"
        )
    return "\n".join(lines)


def _show_codes(session: dict, rows: list[tuple[str, str]]) -> None:
    """Put booking codes on screen. Tara must not read them."""
    lines = ["Booking code"]
    for label, code in rows:
        lines.append(f"{code}\n{label}" if label else code)
    session["choice_list"] = "\n".join(lines)


def list_bookings(session: dict, show_code: bool = False, **_) -> str:
    """Read this account's upcoming appointments and the five most recent past ones."""
    user_id = session.get("user_id")
    if not user_id:
        return "Sign in before looking up appointments."
    grouped = user_bookings(user_id)
    past = grouped["past"][:5]
    shown = (
        _format_saved(grouped["active"], "Upcoming")
        + "\n\n"
        + _format_saved(past, "Past")
    )
    if not as_bool(show_code):
        return shown + "\nDo not read any booking code aloud."
    rows = [
        (f"{item['staff_name']} at {item['time']} on {item['date']}", item["booking_id"])
        for item in [*grouped["active"], *past]
        if item.get("booking_id")
    ]
    if not rows:
        return "There is no booking code to show."
    _show_codes(session, rows)
    return (
        "The booking codes are on the screen. Do not read them aloud. "
        "Tell the customer they can see the codes in the chat.\n"
        + shown
    )


def book_appointment(
    session: dict,
    slot_id: str | None = None,
    confirmed: bool = False,
    **_,
) -> str:
    """Prepare a summary, then save the cart on a shown slot after a clear yes."""
    confirmed = as_bool(confirmed)
    if session.get("booking_id") and session.get("booking_status") == "confirmed":
        return "This chat already has an appointment. Reschedule or cancel that one."
    cart = session.get("selected_services") or []
    if not cart:
        return "The cart is empty. Add a service before booking."
    if not slot_id:
        return "Which shown slot should I book?\n" + format_slots(session.get("available_slots") or [])

    shown = {slot.get("slot_id"): slot for slot in session.get("available_slots") or []}
    if shown and slot_id not in shown:
        return "That slot is not in the slots just shown.\n" + format_slots(list(shown.values()))

    ready = confirmed and session.get("pending_slot_id") == slot_id
    if not ready:
        session["pending_cancel_id"] = None
        session["pending_reschedule"] = None
        session["pending_slot_id"] = slot_id
        chosen = shown.get(slot_id) or {}
        return (
            "Not booked yet. Read this summary aloud and ask: Shall I confirm this booking?\n"
            f"Staff: {chosen.get('staff_name')}\n"
            f"When: {chosen.get('time')} on {chosen.get('date')}\n"
            f"Cart:\n{format_cart(cart)}"
        )
    session["pending_slot_id"] = None
    try:
        booked = confirm_booking(
            session.get("user_id"),
            session.get("conversation_id"),
            slot_id,
            cart,
        )
    except VoiceDenied as exc:
        return str(exc)
    if not booked:
        session["booking_status"] = "failed"
        return "That slot was just taken. Please choose another shown slot."

    session["available_slots"] = [
        slot for slot in (session.get("available_slots") or []) if slot.get("slot_id") != slot_id
    ]
    apply_saved_booking(session, booked)
    return (
        f"Booked with {booked.get('staff_name')} "
        f"at {booked.get('time')} on {booked.get('date')}.\n"
        f"booking_code: {booked.get('booking_id')}. {_CODE_NOTE}\n"
        f"Cart:\n{format_cart(cart)}"
    )


def cancel_appointment(
    session: dict,
    booking_id: str | None = None,
    confirmed: bool = False,
    **_,
) -> str:
    """Prepare a cancel summary, then free the slot after the customer says yes."""
    confirmed = as_bool(confirmed)
    code = booking_id or session.get("booking_id")
    if not code:
        return "Which appointment should I cancel?\n" + list_bookings(session)
    user_id = session.get("user_id")
    current = booking_for_user(user_id, code) if user_id else None
    if not current:
        return "That appointment was not found on this account."
    if not current["active"]:
        return "That appointment is already past or cancelled."
    ready = confirmed and session.get("pending_cancel_id") == code
    if not ready:
        session["pending_slot_id"] = None
        session["pending_reschedule"] = None
        session["pending_cancel_id"] = code
        services = ", ".join(service["name"] for service in current["services"]) or "the saved services"
        return (
            "Not cancelled yet. Read this summary aloud and ask: Shall I cancel this booking?\n"
            f"Staff: {current['staff_name']}\n"
            f"When: {current['time']} on {current['date']}\n"
            f"Services: {services}\n"
            f"booking_code: {code}. {_CODE_NOTE}"
        )
    session["pending_cancel_id"] = None
    cancelled = cancel_booking(user_id, code)
    if not cancelled:
        return "That appointment could not be cancelled. It may already have started."
    if session.get("booking_id") == code:
        session["booking_status"] = "cancelled"
    return (
        f"Cancelled the appointment with {cancelled.get('staff_name')} "
        f"at {cancelled.get('time')} on {cancelled.get('date')}. The time is open again.\n"
        f"booking_code: {code}. {_CODE_NOTE}"
    )


def reschedule_appointment(
    session: dict,
    booking_id: str | None = None,
    slot_id: str | None = None,
    confirmed: bool = False,
    **_,
) -> str:
    """Prepare a move summary, then point the same appointment at a new shown slot."""
    confirmed = as_bool(confirmed)
    code = booking_id or session.get("booking_id")
    if not code:
        return "Which appointment should I move?\n" + list_bookings(session)
    if not slot_id:
        return "Which shown slot should I move it to?\n" + format_slots(
            session.get("available_slots") or []
        )
    shown = {slot.get("slot_id"): slot for slot in session.get("available_slots") or []}
    if shown and slot_id not in shown:
        return "That slot is not in the slots just shown.\n" + format_slots(list(shown.values()))
    user_id = session.get("user_id")
    current = booking_for_user(user_id, code) if user_id else None
    if not current:
        return "That appointment was not found on this account."
    if not current["active"]:
        return "Only an upcoming appointment can be moved."
    pending = session.get("pending_reschedule") or {}
    ready = (
        confirmed
        and pending.get("booking_id") == code
        and pending.get("slot_id") == slot_id
    )
    if not ready:
        session["pending_slot_id"] = None
        session["pending_cancel_id"] = None
        session["pending_reschedule"] = {"booking_id": code, "slot_id": slot_id}
        chosen = shown.get(slot_id) or {}
        return (
            "Not moved yet. Read this summary aloud and ask: Shall I move this booking?\n"
            f"From: {current['staff_name']} at {current['time']} on {current['date']}\n"
            f"To: {chosen.get('staff_name')} at {chosen.get('time')} on {chosen.get('date')}\n"
            f"booking_code: {code}. {_CODE_NOTE}"
        )
    session["pending_reschedule"] = None
    try:
        moved = reschedule_booking(user_id, code, slot_id)
    except VoiceDenied as exc:
        return str(exc)
    if not moved:
        return "That slot was just taken. Please choose another shown slot."
    session["available_slots"] = [
        slot for slot in (session.get("available_slots") or []) if slot.get("slot_id") != slot_id
    ]
    if session.get("booking_id") in {None, code}:
        apply_saved_booking(session, moved)
    return (
        f"Moved the appointment to {moved.get('staff_name')} "
        f"at {moved.get('time')} on {moved.get('date')}.\n"
        f"booking_code: {moved.get('booking_id')}. {_CODE_NOTE}"
    )


def read_booking(session: dict, show_code: bool = False, **_) -> str:
    """Read the cart and any appointment on this call. Changes nothing."""
    code = session.get("booking_id")
    if as_bool(show_code):
        if not code:
            return (
                "This chat has no booking code. "
                "If they have other appointments, call list_bookings with show_code true."
            )
        staff = session.get("preferred_staff") or "Appointment"
        when = f"{session.get('time')} on {session.get('date')}"
        _show_codes(session, [(f"{staff} at {when}", code)])
        return (
            "The booking code is on the screen. Do not read the code aloud. "
            "Tell the customer they can see it in the chat."
        )
    return (
        f"Cart:\n{format_cart(session.get('selected_services') or [])}\n\n"
        f"Date: {session.get('date')}\n"
        f"Time: {session.get('time')}\n"
        f"Staff: {session.get('preferred_staff')}\n\n"
        f"Shown slots:\n{format_slots(session.get('available_slots') or [])}\n\n"
        f"Booking status: {session.get('booking_status') or 'none'}\n"
        f"booking_code: {code}. {_CODE_NOTE}"
    )


APPOINTMENT_FUNCTIONS = [
    {
        "name": "book_appointment",
        "description": (
            "Book one slot_id copied from the latest shown list. "
            "The first call only prepares a summary. "
            "Set confirmed to true only after the customer says yes to that summary. "
            "Last means the last line of the shown list. Do not guess a slot id. "
            "Cart must already have services. Do not call this when the chat already has an appointment."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "slot_id": {
                    "type": "string",
                    "description": "Exact slot_id from the latest check_availability result.",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": "True only after the customer agreed to the spoken summary.",
                },
            },
            "required": ["slot_id"],
        },
    },
    {
        "name": "read_booking",
        "description": (
            "Read cart, date, time, staff, shown slots, and booking. Changes nothing. "
            "Set show_code true only when the customer asks to see the booking code. "
            "That puts the code on screen. Never read the code aloud."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "show_code": {
                    "type": "boolean",
                    "description": "True only when they ask to see the booking code.",
                }
            },
            "required": [],
        },
    },
    {
        "name": "list_bookings",
        "description": (
            "List this caller's upcoming and past appointments. Changes nothing. "
            "Set show_code true only when they ask to see a booking code and this chat has none. "
            "Never read a booking code aloud."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "show_code": {
                    "type": "boolean",
                    "description": "True only when they ask to see the booking code.",
                }
            },
            "required": [],
        },
    },
    {
        "name": "cancel_appointment",
        "description": (
            "Cancel one upcoming appointment on this account. "
            "The first call only prepares a summary. "
            "Set confirmed to true only after the customer says yes. "
            "Use the open appointment on this chat when booking_id is omitted."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "booking_id": {
                    "type": "string",
                    "description": "booking_code from list_bookings or this chat.",
                },
                "confirmed": {"type": "boolean"},
            },
            "required": [],
        },
    },
    {
        "name": "reschedule_appointment",
        "description": (
            "Move one upcoming appointment onto a slot_id copied from the latest shown list. "
            "The first call only prepares a summary. "
            "Set confirmed to true only after the customer says yes. "
            "Services stay the same."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "booking_id": {"type": "string"},
                "slot_id": {
                    "type": "string",
                    "description": "Exact slot_id from the latest check_availability result.",
                },
                "confirmed": {"type": "boolean"},
            },
            "required": ["slot_id"],
        },
    },
]
