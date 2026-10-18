"""Load staff and slots from the existing JSON files once."""

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Booking, Slot, Staff

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def seed(db: Session) -> None:
    """Insert staff and slots that are not already in the database.

    Existing slot ids are left unchanged, so adding rows to slots.json and
    restarting the API is how new dates get onto the schedule.
    """
    staff_rows = json.loads((DATA_DIR / "staff.json").read_text(encoding="utf-8"))
    for row in staff_rows:
        if db.get(Staff, row["staff_id"]) is None:
            db.add(
                Staff(
                    staff_id=row["staff_id"],
                    name=row["name"],
                    role=row.get("role") or "",
                    specializations=row.get("specializations") or [],
                    genders_served=row.get("genders_served") or [],
                )
            )
    db.flush()

    payload = json.loads((DATA_DIR / "slots.json").read_text(encoding="utf-8"))
    existing_slots = set(db.scalars(select(Slot.slot_id)))
    existing_codes = set(db.scalars(select(Booking.code)))
    for row in payload.get("slots", []):
        slot_id = row["slot_id"]
        if slot_id in existing_slots:
            continue
        status = "booked" if row.get("status") == "booked" else "available"
        db.add(
            Slot(
                slot_id=slot_id,
                date=row["date"],
                time=row["time"],
                staff_id=row["staff_id"],
                status=status,
            )
        )
        if status != "booked":
            continue
        code = row.get("booking_id") or f"SEED-{slot_id}"
        if code in existing_codes:
            code = f"SEED-{slot_id}"
        existing_codes.add(code)
        db.add(
            Booking(
                code=code,
                user_id=None,
                slot_id=slot_id,
                conversation_id=None,
                status="confirmed",
            )
        )
    db.commit()
