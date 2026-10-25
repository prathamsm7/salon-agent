"""Create and remove a stylist's appointment on Google Calendar."""

from googleapiclient.errors import HttpError

from app.calendar.client import calendar_id, service
from app.calendar.schedule import ensure_free, ensure_hours, window


def _attendees(guest_email: str | None) -> list[dict] | None:
    email = (guest_email or "").strip()
    if not email:
        return None
    return [{"email": email}]


def create_event(
    staff_id: str,
    date_value: str,
    time_value: str,
    duration_min: int,
    title: str,
    description: str | None = None,
    ignore_event_id: str | None = None,
    guest_email: str | None = None,
) -> dict:
    saved_id = calendar_id(staff_id)
    start, end = window(date_value, time_value, duration_min)
    ensure_hours(start, end)
    ensure_free(staff_id, start, end, ignore_event_id)
    event = {
        "summary": title,
        "start": {"dateTime": start.isoformat(), "timeZone": "Asia/Kolkata"},
        "end": {"dateTime": end.isoformat(), "timeZone": "Asia/Kolkata"},
    }
    if description:
        event["description"] = description
    attendees = _attendees(guest_email)
    if attendees:
        event["attendees"] = attendees
    return (
        service()
        .events()
        .insert(
            calendarId=saved_id,
            body=event,
            sendUpdates="all" if attendees else "none",
        )
        .execute()
    )


def book_on_calendar(
    staff_id: str,
    date_value: str,
    time_value: str,
    duration_min: int,
    title: str,
    description: str | None = None,
    ignore_event_id: str | None = None,
    guest_email: str | None = None,
) -> dict:
    """Create the event and return the ids needed to move or delete it later."""
    event = create_event(
        staff_id,
        date_value,
        time_value,
        duration_min,
        title,
        description,
        ignore_event_id,
        guest_email,
    )
    return {"event_id": event["id"], "calendar_id": calendar_id(staff_id)}


def update_event(
    saved_calendar_id: str,
    event_id: str,
    staff_id: str,
    date_value: str,
    time_value: str,
    duration_min: int,
    title: str,
    guest_email: str | None = None,
) -> dict:
    """Lengthen or retitle the same event. The current event does not block itself."""
    start, end = window(date_value, time_value, duration_min)
    ensure_hours(start, end)
    ensure_free(staff_id, start, end, event_id)
    body = {
        "summary": title,
        "start": {"dateTime": start.isoformat(), "timeZone": "Asia/Kolkata"},
        "end": {"dateTime": end.isoformat(), "timeZone": "Asia/Kolkata"},
    }
    attendees = _attendees(guest_email)
    if attendees:
        body["attendees"] = attendees
    try:
        return (
            service()
            .events()
            .patch(
                calendarId=saved_calendar_id,
                eventId=event_id,
                body=body,
                sendUpdates="all" if attendees else "none",
            )
            .execute()
        )
    except HttpError as error:
        raise RuntimeError("The calendar could not be updated.") from error


def delete_calendar_event(saved_calendar_id: str, event_id: str) -> None:
    """Remove one event. A missing event is already gone."""
    try:
        service().events().delete(
            calendarId=saved_calendar_id,
            eventId=event_id,
            sendUpdates="all",
        ).execute()
    except HttpError as error:
        if getattr(error, "resp", None) is not None and error.resp.status in {404, 410}:
            return
        raise


def delete_event(staff_id: str, event_id: str) -> None:
    delete_calendar_event(calendar_id(staff_id), event_id)
