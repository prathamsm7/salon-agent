"""Route a Deepgram function call to the feature that owns it."""

from __future__ import annotations

from app.voice.appointments import (
    book_appointment,
    cancel_appointment,
    list_bookings,
    read_booking,
    reschedule_appointment,
)
from app.voice.availability import check_availability
from app.voice.catalog import add_services, find_services, remove_services, service_details
from app.voice.session_state import extract_request

HANDLERS = {
    "extract_request": extract_request,
    "find_services": find_services,
    "remove_services": remove_services,
    "add_services": add_services,
    "service_details": service_details,
    "check_availability": check_availability,
    "book_appointment": book_appointment,
    "list_bookings": list_bookings,
    "cancel_appointment": cancel_appointment,
    "reschedule_appointment": reschedule_appointment,
    "read_booking": read_booking,
}


def dispatch(session: dict, name: str, params: dict | None = None) -> str:
    """Run one tool and return its text. Failures stay in the tool result."""
    handler = HANDLERS.get(name)
    if not handler:
        return f"Unknown function: {name}"
    try:
        print("\n ==> name", name)
        print("\n ==> params", params)
        return handler(session, **(params or {}))
    except TypeError as exc:
        return f"Bad arguments for {name}: {exc}"
    except Exception as exc:  # noqa: BLE001 — return tool failures to the agent
        return f"Tool error in {name}: {exc}"
