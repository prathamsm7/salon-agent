from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.calendar.client import staff_rows
from app.calendar.events import create_event, delete_event
from app.calendar.schedule import busy_on

router = APIRouter()

class TestEvent(BaseModel):
    staff_id: str
    date: str
    time: str = "14:00"
    duration_min: int = 60
    title: str = "Calendar test"

@router.get("/staff")
def staff():
    return {"staff": staff_rows()}

def _call(action):
    try:
        return action()
    except KeyError:
        raise HTTPException(status_code=400, detail="Unknown staff calendar")
    except RuntimeError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.get("/busy")
def busy(staff_id: str, date: str):
    return _call(lambda: {"busy": busy_on(staff_id, date)})

@router.post("/events")
def add_event(body: TestEvent):
    def create():
        event = create_event(body.staff_id, body.date, body.time, body.duration_min, body.title)
        return {"event_id": event["id"], "summary": event.get("summary"), "html_link": event.get("htmlLink")}

    return _call(create)

@router.delete("/events/{event_id}")
def remove_event(event_id: str, staff_id: str):
    return _call(lambda: delete_event(staff_id, event_id) or {"deleted": event_id})