"""Create, list, cancel, and move appointments. Each confirmed booking holds one calendar event."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from app.db.errors import VoiceDenied
from app.db.models import Booking, BookingService, Conversation, Slot
from app.db.session import SessionLocal
from app.db.slots import lock_slot
from app.salon_time import salon_now, slot_is_past, slot_start


def booking_query():
    """Load an appointment with its services, slot, and stylist in one query."""
    return select(Booking).options(
        joinedload(Booking.services),
        joinedload(Booking.slot).joinedload(Slot.staff),
    )


def booking_payload(booking: Booking) -> dict:
    """Turn a booking row into the dict the voice tools and HTTP API share."""
    slot = booking.slot
    staff_name = slot.staff.name if slot and slot.staff else ""
    services = [
        {
            "service_id": item.service_id,
            "name": item.name,
            "price_inr": item.price_inr,
            "duration_min": item.duration_min,
        }
        for item in booking.services
    ]
    start = slot_start(slot.date, slot.time) if slot else None
    active = booking.status == "confirmed" and start is not None and start > salon_now()
    return {
        "booking_id": booking.code,
        "conversation_id": booking.conversation_id,
        "status": "cancelled" if booking.status == "cancelled" else ("confirmed" if active else "past"),
        "stored_status": booking.status,
        "active": active,
        "date": slot.date if slot else None,
        "time": slot.time if slot else None,
        "staff_id": slot.staff_id if slot else None,
        "staff_name": staff_name,
        "services": services,
    }


def is_active(payload: dict) -> bool:
    """True when the appointment is confirmed and its start time is still ahead."""
    return bool(payload.get("active"))


def _visit_title(services: list[dict]) -> str:
    names = [
        str(item.get("name") or "").strip()
        for item in services
        if str(item.get("name") or "").strip()
    ]
    return ", ".join(names)[:180] or "Salon appointment"


def _visit_minutes(services: list[dict]) -> int:
    total = sum(int(item.get("duration_min") or 0) for item in services)
    return total if total > 0 else 60


def _ensure_opening(db, slot_id: str) -> Slot | None:
    """Find or create the slot row for a shown calendar time. Does not lock it."""
    from app.calendar.schedule import parse_opening

    parsed = parse_opening(slot_id)
    if parsed is None:
        return db.get(Slot, slot_id)
    staff_id, date_value, spoken = parsed
    existing = db.scalar(
        select(Slot).where(
            Slot.staff_id == staff_id,
            Slot.date == date_value,
            Slot.time == spoken,
        )
    )
    if existing is not None:
        return existing
    existing = Slot(
        slot_id=slot_id,
        date=date_value,
        time=spoken,
        staff_id=staff_id,
        status="available",
    )
    try:
        with db.begin_nested():
            db.add(existing)
            db.flush()
    except IntegrityError:
        existing = db.scalar(
            select(Slot).where(
                Slot.staff_id == staff_id,
                Slot.date == date_value,
                Slot.time == spoken,
            )
        )
    return existing


def _slot_for_opening(db, slot_id: str) -> Slot | None:
    """Lock the slot row for a shown calendar time, creating it when this is the first booking."""
    existing = _ensure_opening(db, slot_id)
    if existing is None:
        return None
    return lock_slot(db, existing.slot_id)


def _drop_event(created: dict | None) -> None:
    if not created:
        return
    from app.calendar.events import delete_calendar_event

    try:
        delete_calendar_event(created["calendar_id"], created["event_id"])
    except Exception:
        return


def confirm_booking(
    user_id: int,
    conversation_id: int,
    slot_id: str,
    services: list[dict],
) -> dict | None:
    """Book a free slot for this chat. None means the slot was no longer available."""
    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        if conversation is None or conversation.user_id != user_id:
            raise VoiceDenied("This chat is not on the signed-in account.")
        existing = db.scalar(
            select(Booking).where(
                Booking.conversation_id == conversation_id,
                Booking.status == "confirmed",
            )
        )
        if existing is not None:
            raise VoiceDenied(
                "This chat already has an appointment. Reschedule or cancel that one."
            )
        slot = _slot_for_opening(db, slot_id)
        if slot is None or slot.status != "available" or slot_is_past(slot.date, slot.time):
            db.rollback()
            return None
        code = f"BOOK-{slot.date.replace('-', '')}-{secrets.token_hex(3).upper()}"
        booking = Booking(
            code=code,
            user_id=user_id,
            slot_id=slot.slot_id,
            conversation_id=conversation_id,
            status="confirmed",
        )
        slot.status = "booked"
        db.add(booking)
        db.flush()
        for service in services:
            db.add(
                BookingService(
                    booking_id=booking.id,
                    service_id=str(service.get("service_id") or ""),
                    name=str(service.get("name") or "Service"),
                    price_inr=int(service.get("price_inr") or 0),
                    duration_min=int(service.get("duration_min") or 0),
                )
            )
        conversation.updated_at = datetime.now(timezone.utc)
        from app.calendar.events import book_on_calendar

        created = None
        try:
            created = book_on_calendar(
                slot.staff_id,
                slot.date,
                slot.time,
                _visit_minutes(services),
                _visit_title(services),
                description=code,
            )
            booking.google_event_id = created["event_id"]
            booking.google_calendar_id = created["calendar_id"]
            db.commit()
        except IntegrityError:
            db.rollback()
            _drop_event(created)
            return None
        except RuntimeError as exc:
            db.rollback()
            _drop_event(created)
            raise VoiceDenied(str(exc)) from exc
        except Exception as exc:
            db.rollback()
            _drop_event(created)
            raise VoiceDenied("The calendar could not be updated. Ask them to try again.") from exc
        booking = db.scalar(booking_query().where(Booking.id == booking.id))
        return booking_payload(booking) if booking else None


def user_bookings(user_id: int) -> dict:
    """Split this customer's appointments into upcoming and past lists."""
    with SessionLocal() as db:
        rows = db.scalars(
            booking_query()
            .where(Booking.user_id == user_id)
            .order_by(Booking.created_at.desc())
        ).unique().all()
    active = []
    past = []
    for booking in rows:
        payload = booking_payload(booking)
        if payload["active"]:
            active.append(payload)
        else:
            past.append(payload)
    active.sort(key=lambda item: (item["date"] or "", item["time"] or ""))
    past.sort(key=lambda item: (item["date"] or "", item["time"] or ""), reverse=True)
    return {"active": active, "past": past}


def booking_for_user(user_id: int, code: str) -> dict | None:
    """Load one appointment when it belongs to this customer."""
    with SessionLocal() as db:
        booking = db.scalar(
            booking_query().where(Booking.user_id == user_id, Booking.code == code)
        )
        return booking_payload(booking) if booking else None


def cancel_booking(user_id: int, code: str) -> dict | None:
    """Cancel an upcoming appointment and mark its slot available again."""
    with SessionLocal() as db:
        booking = db.scalar(
            select(Booking)
            .where(Booking.user_id == user_id, Booking.code == code)
            .with_for_update()
        )
        if booking is None:
            return None
        slot = lock_slot(db, booking.slot_id)
        if slot is None:
            return None
        loaded = db.scalar(booking_query().where(Booking.id == booking.id))
        if loaded is None or not booking_payload(loaded)["active"]:
            db.rollback()
            return None
        if booking.google_event_id and booking.google_calendar_id:
            from app.calendar.events import delete_calendar_event

            try:
                delete_calendar_event(booking.google_calendar_id, booking.google_event_id)
            except Exception as exc:
                db.rollback()
                raise VoiceDenied("The calendar could not be updated. Ask them to try again.") from exc
        booking.status = "cancelled"
        if slot.status == "booked":
            slot.status = "available"
        db.commit()
        db.expire_all()
        loaded = db.scalar(booking_query().where(Booking.id == booking.id))
        return booking_payload(loaded) if loaded else None


def reschedule_booking(user_id: int, code: str, new_slot_id: str) -> dict | None:
    """Move an upcoming appointment onto a free slot. None means that slot was taken."""
    with SessionLocal() as db:
        booking = db.scalar(
            select(Booking)
            .where(Booking.user_id == user_id, Booking.code == code)
            .with_for_update()
        )
        if booking is None:
            raise VoiceDenied("That appointment was not found on this account.")
        current = db.scalar(booking_query().where(Booking.id == booking.id))
        if current is None or not booking_payload(current)["active"]:
            raise VoiceDenied("Only an upcoming appointment can be moved.")
        ensured = _ensure_opening(db, new_slot_id)
        if ensured is None:
            db.rollback()
            return None
        locked = {
            slot_id: lock_slot(db, slot_id)
            for slot_id in sorted({booking.slot_id, ensured.slot_id})
        }
        old_slot = locked.get(booking.slot_id)
        new_slot = locked.get(ensured.slot_id)
        if old_slot is None or new_slot is None:
            db.rollback()
            return None
        if new_slot.slot_id == old_slot.slot_id:
            raise VoiceDenied("That is already the time on this appointment.")
        if new_slot.status != "available" or slot_is_past(new_slot.date, new_slot.time):
            db.rollback()
            return None
        payload = booking_payload(current)
        from app.calendar.events import book_on_calendar, delete_calendar_event

        created = None
        previous_event = booking.google_event_id
        previous_calendar = booking.google_calendar_id
        try:
            created = book_on_calendar(
                new_slot.staff_id,
                new_slot.date,
                new_slot.time,
                _visit_minutes(payload["services"]),
                _visit_title(payload["services"]),
                description=booking.code,
                ignore_event_id=previous_event,
            )
            old_slot.status = "available"
            new_slot.status = "booked"
            booking.slot_id = new_slot.slot_id
            booking.google_event_id = created["event_id"]
            booking.google_calendar_id = created["calendar_id"]
            db.commit()
        except IntegrityError:
            db.rollback()
            _drop_event(created)
            return None
        except RuntimeError as exc:
            db.rollback()
            _drop_event(created)
            raise VoiceDenied(str(exc)) from exc
        except VoiceDenied:
            db.rollback()
            _drop_event(created)
            raise
        except Exception as exc:
            db.rollback()
            _drop_event(created)
            raise VoiceDenied("The calendar could not be updated. Ask them to try again.") from exc
        if previous_event and previous_calendar:
            try:
                delete_calendar_event(previous_calendar, previous_event)
            except Exception:
                pass
        booking_id = booking.id
        db.expire_all()
        moved = db.scalar(booking_query().where(Booking.id == booking_id))
        return booking_payload(moved) if moved else None
