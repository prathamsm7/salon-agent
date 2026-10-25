"""Which stylist calendar to call, and the Google Calendar service."""

import os

from googleapiclient.discovery import build

from app.calendar.auth import credentials

STAFF = {
    "ST01": "Rahul",
    "ST02": "Amit",
    "ST03": "Priya",
    "ST04": "Neha",
}


def staff_rows() -> list[dict]:
    rows = []
    for staff_id, name in STAFF.items():
        calendar_id = os.environ.get(f"GOOGLE_CALENDAR_{staff_id}", "")
        rows.append({"staff_id": staff_id, "name": name, "calendar_id": calendar_id})
    return rows


def calendar_id(staff_id: str) -> str:
    saved = os.environ.get(f"GOOGLE_CALENDAR_{staff_id}", "")
    if staff_id not in STAFF or not saved:
        raise KeyError(staff_id)
    return saved


def service():
    return build("calendar", "v3", credentials=credentials(), cache_discovery=False)
