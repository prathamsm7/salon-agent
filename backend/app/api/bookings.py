from fastapi import APIRouter, Depends, HTTPException

from app.auth import current_user
from app.db.models import User
from app.db.store import conversation_messages, user_bookings

router = APIRouter()


@router.get("/bookings")
def bookings(user: User = Depends(current_user)):
    grouped = user_bookings(user.id)
    return {
        "active": [_public(item) for item in grouped["active"]],
        "past": [_public(item) for item in grouped["past"]],
    }


@router.get("/conversations/{conversation_id}/messages")
def messages(conversation_id: int, user: User = Depends(current_user)):
    rows = conversation_messages(user.id, conversation_id)
    if rows is None:
        raise HTTPException(status_code=404, detail="That chat was not found.")
    return {"messages": rows}


def _public(item: dict) -> dict:
    return {
        "booking_id": item["booking_id"],
        "conversation_id": item["conversation_id"],
        "status": item["status"],
        "date": item["date"],
        "time": item["time"],
        "staff_name": item["staff_name"],
        "services": [service["name"] for service in item["services"]],
    }
