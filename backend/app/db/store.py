"""Backward-compatible imports. New code should use the feature modules directly.

Slots live in ``app.db.slots``, appointments in ``app.db.bookings``, and chats in
``app.db.conversations``.
"""

from app.db.bookings import (
    booking_for_user,
    booking_payload,
    cancel_booking,
    confirm_booking,
    is_active,
    reschedule_booking,
    user_bookings,
)
from app.db.conversations import conversation_messages, prepare_voice, save_message
from app.db.errors import VoiceDenied
from app.db.slots import slots_for_date

__all__ = [
    "VoiceDenied",
    "booking_for_user",
    "booking_payload",
    "cancel_booking",
    "confirm_booking",
    "conversation_messages",
    "is_active",
    "prepare_voice",
    "reschedule_booking",
    "save_message",
    "slots_for_date",
    "user_bookings",
]
