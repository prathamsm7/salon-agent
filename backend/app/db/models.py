"""Customers, slots, bookings, and the chats attached to them."""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    email: Mapped[str | None] = mapped_column(String(254), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class OtpCode(Base):
    __tablename__ = "otp_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str | None] = mapped_column(String(254), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, index=True)
    code_hash: Mapped[str] = mapped_column(String(128))
    pending_name: Mapped[str | None] = mapped_column(String(80))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class Staff(Base):
    __tablename__ = "staff"

    staff_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(80))
    specializations: Mapped[list] = mapped_column(JSONB)
    genders_served: Mapped[list] = mapped_column(JSONB)

    slots: Mapped[list["Slot"]] = relationship(back_populates="staff")


class Slot(Base):
    __tablename__ = "slots"
    __table_args__ = (UniqueConstraint("staff_id", "date", "time"),)

    slot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    date: Mapped[str] = mapped_column(String(10), index=True)
    time: Mapped[str] = mapped_column(String(16))
    staff_id: Mapped[str] = mapped_column(ForeignKey("staff.staff_id"))
    status: Mapped[str] = mapped_column(String(16), default="available", index=True)

    staff: Mapped[Staff] = relationship(back_populates="slots")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", order_by="Message.id"
    )


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        Index(
            "uq_slot_confirmed_booking",
            "slot_id",
            unique=True,
            postgresql_where=text("status = 'confirmed'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    slot_id: Mapped[str] = mapped_column(ForeignKey("slots.slot_id"))
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id"), unique=True
    )
    status: Mapped[str] = mapped_column(String(16), default="confirmed", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    slot: Mapped[Slot] = relationship()
    services: Mapped[list["BookingService"]] = relationship(
        back_populates="booking", cascade="all, delete-orphan"
    )
    conversation: Mapped[Conversation | None] = relationship()


class BookingService(Base):
    __tablename__ = "booking_services"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), index=True)
    service_id: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(160))
    price_inr: Mapped[int] = mapped_column(Integer, default=0)
    duration_min: Mapped[int] = mapped_column(Integer, default=0)

    booking: Mapped[Booking] = relationship(back_populates="services")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
