"""Route a Deepgram function call to the feature that owns it."""

from __future__ import annotations

from app.voice.appointments import (
    book_appointment,
    cancel_appointment,
    extend_booked_services,
    list_bookings,
    read_booking,
    reschedule_appointment,
)
from app.voice.availability import check_availability
from app.voice.action_log import log_action
from app.voice.catalog import add_services, find_services, remove_services, service_details
from app.voice.session_state import as_bool, extract_request
from app.observability.langfuse_tracing import trace_tool_call

def end_session(session: dict, confirmed: bool = False, **_kwargs: object) -> str:
    """Ask before hanging up. The cart stays as it is."""
    confirmed = as_bool(confirmed)
    if not session.get("pending_end"):
        session["pending_end"] = True
        return (
            "Ask one short question: should I end the call? "
            "Do not say goodbye yet. "
            "Call end_session with confirmed true only after they say yes."
        )
    if not confirmed:
        session["pending_end"] = False
        return "They want to keep talking. Do not end the call. Help with what they asked."
    session["pending_end"] = False
    session["end_reason"] = "goodbye"
    return "Say one short goodbye and stop. Do not ask another question. The call will close after you finish."


def _add_services(session: dict, service_ids: list[str] | None = None, booking_id: str | None = None, **kwargs) -> str:
    """A booked appointment is checked on the calendar before it is changed."""
    if booking_id or (session.get("booking_id") and session.get("booking_status") == "confirmed"):
        return extend_booked_services(session, service_ids, booking_id)
    return add_services(session, service_ids, **kwargs)


HANDLERS = {
    "extract_request": extract_request,
    "find_services": find_services,
    "remove_services": remove_services,
    "add_services": _add_services,
    "service_details": service_details,
    "check_availability": check_availability,
    "book_appointment": book_appointment,
    "list_bookings": list_bookings,
    "cancel_appointment": cancel_appointment,
    "reschedule_appointment": reschedule_appointment,
    "read_booking": read_booking,
    "end_session": end_session,
}


def dispatch(
    session: dict,
    name: str,
    params: dict | None = None,
) -> str:
    """Trace tool execution while preserving existing dispatch behavior."""

    params = params or {}

    def execute() -> str:
        handler = HANDLERS.get(name)

        if not handler:
            result = f"Unknown function: {name}"
            log_action(session, name, params, result)
            return result

        try:
            result = handler(session, **params)
        except TypeError as exc:
            result = f"Bad arguments for {name}: {exc}"
        except Exception as exc:
            result = f"Tool error in {name}: {exc}"

        logged = dict(params)

        if name == "end_session" and session.get("end_reason") == "goodbye":
            logged["reason"] = "goodbye"

        log_action(session, name, logged, result)
        return result

    return trace_tool_call(
        session=session,
        tool_name=name,
        arguments=params,
        execute=execute,
    )