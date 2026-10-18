"""Read and lock appointment slots. A slot is one stylist at one date and time."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Slot, Staff
from app.db.session import SessionLocal


def slots_for_date(date_value: str) -> list[dict]:
    """Return every available slot on a date, with the stylist's name filled in."""
    with SessionLocal() as db:
        rows = db.execute(
            select(Slot, Staff.name)
            .join(Staff, Slot.staff_id == Staff.staff_id)
            .where(Slot.date == date_value, Slot.status == "available")
            .order_by(Slot.time, Staff.name)
        ).all()
    return [
        {
            "slot_id": slot.slot_id,
            "date": slot.date,
            "time": slot.time,
            "staff_id": slot.staff_id,
            "staff_name": staff_name,
            "status": slot.status,
        }
        for slot, staff_name in rows
    ]


def lock_slot(db: Session, slot_id: str) -> Slot | None:
    """Lock one slot row so two bookings cannot take it at the same time."""
    return db.scalar(select(Slot).where(Slot.slot_id == slot_id).with_for_update())
