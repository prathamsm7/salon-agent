"""Create and remove a stylist's appointment on Google Calendar."""

from googleapiclient.errors import HttpError

from app.calendar.client import calendar_id, service
from app.calendar.schedule import ensure_free, ensure_hours, window


def create_event(
    staff_id: str,
    date_value: str,
    time_value: str,
    duration_min: int,
    title: str,
    description: str | None = None,
    ignore_event_id: str | None = None,
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
    return service().events().insert(calendarId=saved_id, body=event).execute()


def book_on_calendar(
    staff_id: str,
    date_value: str,
    time_value: str,
    duration_min: int,
    title: str,
    description: str | None = None,
    ignore_event_id: str | None = None,
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
    )
    return {"event_id": event["id"], "calendar_id": calendar_id(staff_id)}


def delete_calendar_event(saved_calendar_id: str, event_id: str) -> None:
    """Remove one event. A missing event is already gone."""
    try:
        service().events().delete(calendarId=saved_calendar_id, eventId=event_id).execute()
    except HttpError as error:
        if getattr(error, "resp", None) is not None and error.resp.status in {404, 410}:
            return
        raise


def delete_event(staff_id: str, event_id: str) -> None:
    delete_calendar_event(calendar_id(staff_id), event_id)
