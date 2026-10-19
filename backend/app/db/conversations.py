"""Chats saved with a customer, including the lines Tara and the caller already said."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.db.bookings import booking_payload, booking_query
from app.db.errors import VoiceDenied
from app.db.models import Booking, Conversation, Message
from app.db.session import SessionLocal
from app.salon_time import spoken_date


def save_message(conversation_id: int, role: str, content: str) -> None:
    """Append one user, assistant, or choice line to a chat."""
    text = (content or "").strip()
    if not text or role not in {"user", "assistant", "choice"}:
        return
    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        if conversation is None:
            return
        db.add(Message(conversation_id=conversation_id, role=role, content=text))
        conversation.updated_at = datetime.now(timezone.utc)
        db.commit()


def conversation_messages(user_id: int, conversation_id: int) -> list[dict] | None:
    """Return a chat's lines, or None when the chat is not on this account."""
    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        if conversation is None or conversation.user_id != user_id:
            return None
        rows = db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.id)
        ).all()
    return [{"role": row.role, "content": row.content} for row in rows]


def prepare_voice(user_id: int, user_name: str, conversation_id: int | None) -> dict:
    """Open a new chat, or resume an upcoming appointment's chat with a short recap.

    A past appointment stays readable through the HTTP API and is not resumed here.
    """
    with SessionLocal() as db:
        if conversation_id is None:
            conversation = Conversation(user_id=user_id)
            db.add(conversation)
            db.commit()
            db.refresh(conversation)
            conversation_id = conversation.id
            booking = None
            recent: list = []
        else:
            conversation = db.get(Conversation, conversation_id)
            if conversation is None or conversation.user_id != user_id:
                raise VoiceDenied("That chat was not found on this account.")
            booking_row = db.scalar(
                booking_query().where(Booking.conversation_id == conversation_id)
            )
            booking = booking_payload(booking_row) if booking_row else None
            if booking is not None and not booking["active"]:
                raise VoiceDenied(
                    "This chat is saved with a past appointment. Read it from past bookings, or start a new chat."
                )
            recent_rows = list(
                reversed(
                    db.scalars(
                        select(Message)
                        .where(Message.conversation_id == conversation_id)
                        .order_by(Message.id.desc())
                        .limit(8)
                    ).all()
                )
            )
            recent = [(row.role, row.content[:400]) for row in recent_rows]

    recap_lines = []
    if booking:
        service_names = ", ".join(item["name"] for item in booking["services"]) or "the saved services"
        recap_lines.append(
            "Open appointment. Do not read its booking code aloud. "
            "If they ask to see the booking code, call read_booking with show_code true. "
            f"Staff {booking['staff_name']} at {booking['time']} on {booking['date']}. "
            f"Services: {service_names}."
        )
    greeting = _greeting(user_name, booking, bool(recent))
    if recent:
        recap_lines.append("Recent chat:")
        for role, content in recent:
            recap_lines.append(f"{role}: {content}")
    return {
        "conversation_id": conversation_id,
        "booking": booking,
        "recap": "\n".join(recap_lines),
        "greeting": greeting,
    }


def _greeting(user_name: str, booking: dict | None, continuing: bool) -> str:
    """What Tara says first. A reconnect continues; it does not re-pitch the visit."""
    name = (user_name or "").strip() or "there"
    if continuing:
        return f"Hi {name}, this is Tara. Welcome back. How can I help you?"
    if booking:
        when = spoken_date(booking.get("date"))
        return (
            f"Hi {name}, this is Tara. I have your appointment with "
            f"{booking['staff_name']} at {booking['time']} on {when}. "
            "Would you like to keep this appointment, reschedule it, or cancel it?"
        )
    return "Hi, Welcome to the salon Kesh Kala, this is Tara. How can I help you today?"
