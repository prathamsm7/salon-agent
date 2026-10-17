"""Salon catalog, slots, and booking tools for the Deepgram receptionist."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from datetime import date as Date
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from upstash_vector import Index, Vector

BACKEND_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_DIR / ".env")

DATA_DIR = BACKEND_DIR / "data"
SLOTS_DB_PATH = DATA_DIR / "slots.json"
STAFF_DB_PATH = DATA_DIR / "staff.json"
SERVICES_PATH = DATA_DIR / "salon_services_rich.json"
SALON_TZ = ZoneInfo("Asia/Kolkata")

_slots_lock = threading.RLock()
_index_lock = threading.Lock()
_vector_index: Index | None = None
_index_ready = False

SERVICE_DETAILS = {
    service["service_id"]: service.get("description") or ""
    for service in json.load(open(SERVICES_PATH, encoding="utf-8"))
    if service.get("service_id")
}


def get_vector_index() -> Index:
    """Open Upstash on first use so the text chat API can start without it."""
    global _vector_index
    if _vector_index is not None:
        return _vector_index
    url = os.environ.get("UPSTASH_VECTOR_REST_URL")
    token = os.environ.get("UPSTASH_VECTOR_REST_TOKEN")
    if not url or not token:
        raise RuntimeError(
            "UPSTASH_VECTOR_REST_URL and UPSTASH_VECTOR_REST_TOKEN are required"
        )
    _vector_index = Index(url=url, token=token)
    return _vector_index


def load_slots_db(path: Path = SLOTS_DB_PATH) -> dict:
    with _slots_lock:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("slots", [])
        return data


def save_slots_db(data: dict, path: Path = SLOTS_DB_PATH) -> None:
    with _slots_lock:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=True, indent=2)


def load_staff(path: Path = STAFF_DB_PATH) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def clock_hour(time_value: str) -> int | None:
    try:
        clock, meridiem = time_value.strip().split()
        hour = int(clock.split(":")[0])
    except (AttributeError, ValueError):
        return None
    meridiem = meridiem.upper()
    if meridiem == "PM" and hour != 12:
        hour += 12
    if meridiem == "AM" and hour == 12:
        hour = 0
    return hour


def salon_now() -> datetime:
    return datetime.now(SALON_TZ)


def slot_start(date_value: str, time_value: str) -> datetime | None:
    hour = clock_hour(time_value)
    if hour is None:
        return None
    try:
        minute = int(time_value.strip().split()[0].split(":")[1])
        year, month, day = (int(part) for part in date_value.split("-"))
    except (IndexError, ValueError):
        return None
    return datetime(year, month, day, hour, minute, tzinfo=SALON_TZ)


def slot_is_past(date_value: str, time_value: str, now: datetime | None = None) -> bool:
    now = now or salon_now()
    if date_value != now.date().isoformat():
        return False
    start = slot_start(date_value, time_value)
    return start is not None and start <= now


def find_available_slots(
    slots_data: dict,
    date_value: str,
    time_value: str | None = None,
    staff_pref: str | None = None,
    any_staff: bool = False,
    part_of_day: str | None = None,
    limit: int = 8,
) -> list[dict]:
    filtered = []
    for slot in slots_data.get("slots", []):
        if slot.get("status") != "available" or slot.get("date") != date_value:
            continue
        if slot_is_past(date_value, slot.get("time") or ""):
            continue
        if time_value and slot.get("time") != time_value:
            continue
        hour = clock_hour(slot.get("time") or "")
        if part_of_day == "morning" and (hour is None or hour >= 12):
            continue
        if part_of_day == "afternoon" and (hour is None or hour < 12 or hour >= 17):
            continue
        if part_of_day == "evening" and (hour is None or hour < 17):
            continue
        if not any_staff and staff_pref:
            normalized = staff_pref.strip().lower()
            names = {
                str(slot.get("staff_id", "")).lower(),
                str(slot.get("staff_name", "")).lower(),
            }
            if normalized not in names:
                continue
        filtered.append(
            {
                "slot_id": slot.get("slot_id"),
                "date": slot.get("date"),
                "time": slot.get("time"),
                "staff_id": slot.get("staff_id"),
                "staff_name": slot.get("staff_name"),
            }
        )
    filtered.sort(
        key=lambda item: (item["date"], clock_hour(item["time"]) or 0, item["staff_name"])
    )
    return filtered[:limit]


def book_slot(slot_id: str, booking_id: str, path: Path = SLOTS_DB_PATH) -> dict | None:
    with _slots_lock:
        slots_data = load_slots_db(path)
        for slot in slots_data.get("slots", []):
            if slot.get("slot_id") != slot_id or slot.get("status") != "available":
                continue
            slot["status"] = "booked"
            slot["booking_id"] = booking_id
            save_slots_db(slots_data, path)
            return {
                "slot_id": slot.get("slot_id"),
                "date": slot.get("date"),
                "time": slot.get("time"),
                "staff_id": slot.get("staff_id"),
                "staff_name": slot.get("staff_name"),
            }
        return None


def format_options(services) -> str:
    if not services:
        return "No services shown."
    lines = []
    for i, opt in enumerate(services, start=1):
        line = (
            f"{i}. {opt.get('name')}: {opt.get('price_inr')} rupees, "
            f"{opt.get('duration_min')} minutes"
        )
        if opt.get("description"):
            line += f". {opt['description']}"
        line += f"\n   internal_service_id: {opt.get('service_id')}"
        lines.append(line)
    return "\n".join(lines)


def format_cart(services) -> str:
    if not services:
        return "Cart is empty."
    lines = [
        (
            f"{i}. {svc.get('name')}: {svc.get('price_inr')} rupees, "
            f"{svc.get('duration_min')} minutes\n"
            f"   internal_service_id: {svc.get('service_id')}"
        )
        for i, svc in enumerate(services, start=1)
    ]
    price = sum(int(svc.get("price_inr") or 0) for svc in services)
    duration = sum(int(svc.get("duration_min") or 0) for svc in services)
    return "\n".join(lines) + f"\nTotal {price} rupees, {duration} minutes"


def format_slots(slots) -> str:
    if not slots:
        return "No open slots were found in our records."
    return "\n".join(
        (
            f"{i}. {slot.get('staff_name')} at {slot.get('time')} on {slot.get('date')}\n"
            f"   internal_slot_id: {slot.get('slot_id')}\n"
            f"   internal_staff_id: {slot.get('staff_id')}"
        )
        for i, slot in enumerate(slots, start=1)
    )


def normalize_gender(value: str | None) -> str | None:
    if not value:
        return None
    mapping = {
        "male": "Male",
        "men": "Male",
        "man": "Male",
        "female": "Female",
        "women": "Female",
        "woman": "Female",
        "ladies": "Female",
        "unisex": "Unisex",
    }
    if value in {"Male", "Female", "Unisex"}:
        return value
    return mapping.get(value.strip().lower())


def _service_metadata(service: dict) -> dict:
    return {
        "service_id": service.get("service_id") or "",
        "name": service.get("name") or "",
        "category": service.get("category") or "",
        "gender": service.get("gender") or "",
        "price_inr": int(service.get("price_inr") or 0),
        "duration_min": int(service.get("duration_min") or 0),
        "description": service.get("description") or "",
    }


def ensure_services_indexed() -> None:
    """Upsert the salon catalog when the Upstash index does not already hold it."""
    global _index_ready
    with _index_lock:
        if _index_ready:
            return
        index = get_vector_index()
        services = json.load(open(SERVICES_PATH, encoding="utf-8"))
        info = index.info()
        if getattr(info, "vector_count", 0) < len(services):
            vectors = [
                Vector(
                    id=service["service_id"],
                    data=service.get("embedding_text") or service.get("description") or service["name"],
                    metadata=_service_metadata(service),
                )
                for service in services
                if service.get("service_id")
            ]
            index.upsert(vectors=vectors)
            deadline = time.time() + 30
            while time.time() < deadline:
                pending = getattr(index.info(), "pending_vector_count", 0)
                if not pending:
                    break
                time.sleep(1)
        _index_ready = True


def search_services(query: str, gender: str | None) -> list[dict]:
    allowed = [gender, "Unisex"] if gender in {"Male", "Female"} else ["Male", "Female", "Unisex"]
    gender_filter = " OR ".join(f"gender = '{value}'" for value in allowed)
    results = get_vector_index().query(
        data=query,
        top_k=5,
        include_metadata=True,
        filter=gender_filter,
    )
    options = []
    for hit in results:
        metadata = hit.metadata or {}
        service_id = metadata.get("service_id") or hit.id
        options.append(
            {
                "service_id": service_id,
                "name": metadata.get("name"),
                "category": metadata.get("category"),
                "gender": metadata.get("gender"),
                "price_inr": metadata.get("price_inr"),
                "duration_min": metadata.get("duration_min"),
                "score": hit.score,
            }
        )
    return options


def new_session() -> dict[str, Any]:
    return {
        "gender": None,
        "categories": [],
        "retrieved_services": [],
        "selected_services": [],
        "date": None,
        "time": None,
        "part_of_day": None,
        "preferred_staff": None,
        "available_slots": [],
        "booking_id": None,
        "booking_status": None,
        "pending_slot_id": None,
    }


def context_summary(session: dict) -> str:
    return (
        f"Cart:\n{format_cart(session.get('selected_services') or [])}\n"
        f"Shown services:\n{format_options(session.get('retrieved_services') or [])}\n"
        f"Gender: {session.get('gender')}\n"
        f"Categories: {', '.join(session.get('categories') or []) or 'none'}\n"
        f"Date: {session.get('date')}\n"
        f"Time: {session.get('time')}\n"
        f"Staff: {session.get('preferred_staff')}\n"
        f"Shown slots:\n{format_slots(session.get('available_slots') or [])}"
    )


def system_prompt() -> str:
    now = salon_now()
    clock = now.strftime("%I:%M %p").lstrip("0")
    return f"""
You are Tara, the receptionist at salon Kesh Kala. Today is {now.date().isoformat()} ({now.strftime("%A")}).
The current time is {clock} Asia/Kolkata. Do not offer a slot that has already started.

Talk only about this salon's services and appointments. For anything else, say you can only help with salon bookings or can ask for the clarification.
Use tool results only. Never invent a service, price, duration, slot, staff member, or description.
If a tool says nothing matched or the detail is not stored, tell the customer it was not found in our records. Do not guess.
Never say internal ids to the customer: service ids, staff ids, slot ids. Use those codes only inside function calls.
A greeting needs no tool.
Your reply is spoken aloud. Use plain sentences. Say "rupees" and "minutes".

Order:
1. extract_request when the message states service, gender, a date, a time, or staff
2. remove_services, then add_services (use service ids from the latest shown list)
3. find_services to browse. Exactly one descriptive phrase per service the customer named. Haircut and beard is two phrases. Face treatments is one phrase. Example: "men's face cleanup and facial treatment", not "face treatments" or "hair". Do not add synonym queries.
4. service_details when they ask what a shown service includes
5. check_availability
6. book_appointment only when the cart has services and the customer has said yes to the summary
7. read_booking only when they ask for the cart, a total, or the booking

On a browse ("show me…", "I want a haircut and beard"), call find_services immediately. Do not ask for date, time, or staff.
After find_services, say only that you found options for those topics and ask them to select their choice. Do not read the numbered list aloud; it is already on screen.
When they choose, call add_services with service ids copied from the latest shown list. Do not search again for a choice from that list.
Ask for a date only after they want to book.
Do not ask for gender again once it is known.
When they choose a slot, do not book yet.
Call book_appointment with confirmed true only after they clearly say yes. A slot choice is not a yes.
book_appointment must copy a slot_id from the latest shown list. "Last" is the last line of that list, not a guessed id.
One short reply after the tool result. Do not repeat the same question.
Speak service names, prices, durations, staff first names, dates, and times only when confirming a selection or booking.
Do not narrate function calls, staff roles, or specializations.
Never narrate the error messages to the customer. Say something went wrong and ask them to try again.
"""


SALON_SUPPORT_FUNCTIONS = [
    {
        "name": "extract_request",
        "description": "Save gender, categories, date, time, part of day, or staff from this message.",
        "parameters": {
            "type": "object",
            "properties": {
                "gender": {"type": "string", "enum": ["Male", "Female", "Unisex"]},
                "categories": {"type": "array", "items": {"type": "string"}},
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "time": {"type": "string", "description": "h:mm AM/PM"},
                "part_of_day": {"type": "string", "enum": ["morning", "afternoon", "evening"]},
                "staff": {"type": "string", "description": "Staff name or any"},
            },
            "required": [],
        },
    },
    {
        "name": "find_services",
        "description": (
            "Search the catalog. Pass exactly one descriptive phrase per service the customer named. "
            "Haircut and beard is two phrases. Face treatments is one phrase. Do not add synonym queries. "
            "Each phrase includes gender and what they want, for example "
            "\"men's face cleanup and facial treatment\", not \"face treatments\" or \"hair\". "
            "Browse is not an add."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "One phrase per named service. Include gender and the treatment. "
                        "Do not send extra paraphrases of the same service."
                    ),
                },
                "gender": {"type": "string", "enum": ["Male", "Female", "Unisex"]},
            },
            "required": ["queries"],
        },
    },
    {
        "name": "add_services",
        "description": (
            "Add shown service ids to the cart. Call only after asked to add a service. "
            "Add a service only after the list is shown to the customer. "
            "Copy service ids from the latest find_services result."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "service_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["service_ids"],
        },
    },
    {
        "name": "remove_services",
        "description": f"""Remove service ids from the cart. Call the function only after asked to remove a service.
        Remove service only if cart is not empty.
        """,
        "parameters": {
            "type": "object",
            "properties": {
                "service_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["service_ids"],
        },
    },
    {
        "name": "service_details",
        "description": "Return the description for a shown service id.",
        "parameters": {
            "type": "object",
            "properties": {
                "service_id": {"type": "string"},
            },
            "required": ["service_id"],
        },
    },
    {
        "name": "check_availability",
        "description": "List open slots. time is h:mm AM/PM. Use part_of_day when there is no clock time.",
        "parameters": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "time": {"type": "string", "description": "h:mm AM/PM"},
                "staff": {"type": "string"},
                "part_of_day": {"type": "string", "enum": ["morning", "afternoon", "evening"]},
            },
            "required": [],
        },
    },
    {
        "name": "book_appointment",
        "description": (
            "Book one slot_id copied from the latest shown list. "
            "The first call only prepares a summary. "
            "Set confirmed to true only after the customer says yes to that summary. "
            "Last means the last line of the shown list. Do not guess a slot id. "
            "Cart must already have services."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "slot_id": {
                    "type": "string",
                    "description": "Exact slot_id from the latest check_availability result.",
                },
                "confirmed": {
                    "type": "boolean",
                    "description": "True only after the customer agreed to the spoken summary.",
                },
            },
            "required": ["slot_id"],
        },
    },
    {
        "name": "read_booking",
        "description": "Read cart, date, time, staff, shown slots, and booking. Changes nothing.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
]


def _catalog(session: dict) -> dict[str, dict]:
    catalog = {}
    for service in session.get("retrieved_services") or []:
        if service.get("service_id"):
            catalog[service["service_id"]] = service
    for service in session.get("selected_services") or []:
        if service.get("service_id"):
            catalog.setdefault(service["service_id"], service)
    return catalog


def _set_choice_list(session: dict, lines: list[str]) -> None:
    text = "\n".join(line for line in lines if line is not None).strip()
    session["choice_list"] = text or None


def extract_request(
    session: dict,
    gender: str | None = None,
    categories: list[str] | None = None,
    date: str | None = None,
    time: str | None = None,
    part_of_day: str | None = None,
    staff: str | None = None,
    **_,
) -> str:
    g = normalize_gender(gender)
    if g:
        session["gender"] = g
    if categories:
        session["categories"] = categories
    if date:
        session["date"] = date
    if time:
        session["time"] = time
    if part_of_day:
        session["part_of_day"] = part_of_day
    if staff:
        session["preferred_staff"] = staff
    return (
        f"Gender: {session.get('gender')}\n"
        f"Categories: {', '.join(session.get('categories') or []) or 'none'}\n"
        f"Date: {session.get('date')}\n"
        f"Time: {session.get('time')}\n"
        f"Part of day: {session.get('part_of_day')}\n"
        f"Staff: {session.get('preferred_staff')}"
    )


def find_services(
    session: dict,
    queries: list[str] | None = None,
    categories: list[str] | None = None,
    gender: str | None = None,
    **_,
) -> str:
    query_list = [q for q in (queries or categories or session.get("categories") or []) if q]
    if not query_list:
        return "Which service should I search for you?"

    g = normalize_gender(gender) or session.get("gender")
    if g not in {"Male", "Female", "Unisex"}:
        g = None
    if g:
        session["gender"] = g

    shown: list[dict] = []
    seen: set[str] = set()
    blocks = []
    panel = []
    for query in query_list:
        options = search_services(query, g)
        unique = []
        for option in options:
            sid = option.get("service_id")
            if not sid or sid in seen:
                continue
            seen.add(sid)
            unique.append(option)
            shown.append(option)
        blocks.append(
            f"{query}:\n{format_options(unique) if unique else 'Not found in our salon records.'}"
        )
        if unique:
            panel.append(query)
            for number, service in enumerate(unique, start=1):
                panel.append(
                    f"{number}) {service.get('name')} — "
                    f"{service.get('price_inr')} rupees, {service.get('duration_min')} minutes"
                )
            panel.append("")

    session["retrieved_services"] = shown
    session["categories"] = query_list
    _set_choice_list(session, panel)
    return (
        "\n\n".join(blocks)
        + "\n\nSay only that you found options for these topics and ask them to select "
        "their choice. Do not read the numbered list aloud."
    )


def add_services(session: dict, service_ids: list[str] | None = None, **_) -> str:
    if not service_ids:
        return "Which service ids should I add?"
    catalog = _catalog(session)
    added = [catalog[sid] for sid in service_ids if sid in catalog]
    missing = [sid for sid in service_ids if sid not in catalog]
    if not added:
        return f"Unknown service ids: {', '.join(missing)}. Search services first."

    cart = {svc["service_id"]: svc for svc in session.get("selected_services") or []}
    for service in added:
        cart[service["service_id"]] = service
    session["selected_services"] = list(cart.values())
    notes = [f"Selected {s.get('name')}." for s in added]
    if missing:
        notes.append("Some requested services were not found in our records.")
    return "\n".join(notes) + "\n\nCart:\n" + format_cart(session["selected_services"])


def remove_services(session: dict, service_ids: list[str] | None = None, **_) -> str:
    if not service_ids:
        return "Which service ids should I remove?"
    drop = set(service_ids)
    session["selected_services"] = [
        service
        for service in (session.get("selected_services") or [])
        if service.get("service_id") not in drop
    ]
    return f"Removed the requested services.\n\nCart:\n{format_cart(session['selected_services'])}"


def service_details(session: dict, service_id: str | None = None, **_) -> str:
    if not service_id:
        return "Which service id should I describe?"
    service = _catalog(session).get(service_id) or {}
    description = (
        service.get("description")
        or SERVICE_DETAILS.get(service_id)
        or "That detail was not found in our salon records."
    )
    name = service.get("name") or "That service"
    return f"{name}: {description}"


def check_availability(
    session: dict,
    date: str | None = None,
    time: str | None = None,
    staff: str | None = None,
    part_of_day: str | None = None,
    **_,
) -> str:
    date_value = date or session.get("date")
    if not date_value:
        return "Which date would you like for the appointment?"

    part = part_of_day or (None if time else session.get("part_of_day"))
    if time and part_of_day:
        return "Do you want that exact time, or any time in that part of the day?"

    if date:
        session["date"] = date
    if time:
        session["time"] = time
    if part_of_day:
        session["part_of_day"] = part_of_day
    if staff:
        session["preferred_staff"] = staff

    staff_pref = staff or session.get("preferred_staff")
    any_staff = bool(staff_pref and staff_pref.strip().lower() == "any")
    matched = find_available_slots(
        load_slots_db(),
        date_value=date_value,
        time_value=time,
        staff_pref=None if any_staff else staff_pref,
        any_staff=any_staff,
        part_of_day=None if time else part,
        limit=8 if time else 24,
    )
    if time and not matched:
        matched = find_available_slots(
            load_slots_db(),
            date_value=date_value,
            time_value=None,
            staff_pref=None if any_staff else staff_pref,
            any_staff=any_staff,
            limit=24,
        )
        content = f"No slots are open at {time} on {date_value}.\n" + format_slots(matched)
    else:
        content = format_slots(matched)
    session["available_slots"] = matched
    panel = [f"Open times on {date_value}", ""]
    for number, slot in enumerate(matched, start=1):
        panel.append(f"{number}) {slot.get('staff_name')} at {slot.get('time')}")
    _set_choice_list(session, panel if matched else [])
    return (
        content
        + "\n\nSay only that you found open times and ask them to choose from the list. "
        "Do not read each time aloud."
    )


def book_appointment(
    session: dict,
    slot_id: str | None = None,
    confirmed: bool = False,
    **_,
) -> str:
    cart = session.get("selected_services") or []
    if not cart:
        return "The cart is empty. Add a service before booking."
    if not slot_id:
        return "Which shown slot should I book?\n" + format_slots(session.get("available_slots") or [])

    shown = {slot.get("slot_id"): slot for slot in session.get("available_slots") or []}
    if shown and slot_id not in shown:
        return "That slot is not in the slots just shown.\n" + format_slots(list(shown.values()))

    ready = confirmed and session.get("pending_slot_id") == slot_id
    if not ready:
        session["pending_slot_id"] = slot_id
        chosen = shown.get(slot_id) or {}
        return (
            "Not booked yet. Read this summary aloud and ask: Shall I confirm this booking?\n"
            f"Staff: {chosen.get('staff_name')}\n"
            f"When: {chosen.get('time')} on {chosen.get('date')}\n"
            f"Cart:\n{format_cart(cart)}"
        )
    session["pending_slot_id"] = None

    booking_id = f"BOOK-{Date.today().strftime('%Y%m%d')}-{slot_id.split('-')[-1]}"
    booked = book_slot(slot_id, booking_id)
    if not booked:
        session["booking_status"] = "failed"
        return "That slot was just taken. Please choose another shown slot."

    session["available_slots"] = [
        slot for slot in (session.get("available_slots") or []) if slot.get("slot_id") != slot_id
    ]
    session.update(
        {
            "booking_id": booking_id,
            "booking_status": "confirmed",
            "date": booked.get("date"),
            "time": booked.get("time"),
        }
    )
    return (
        f"Booked with {booked.get('staff_name')} "
        f"at {booked.get('time')} on {booked.get('date')}.\n"
        f"internal_booking_id: {booking_id}\n"
        f"Cart:\n{format_cart(cart)}"
    )


def read_booking(session: dict, **_) -> str:
    return (
        f"Cart:\n{format_cart(session.get('selected_services') or [])}\n\n"
        f"Date: {session.get('date')}\n"
        f"Time: {session.get('time')}\n"
        f"Staff: {session.get('preferred_staff')}\n\n"
        f"Shown slots:\n{format_slots(session.get('available_slots') or [])}\n\n"
        f"Booking status: {session.get('booking_status') or 'none'}\n"
        f"internal_booking_id: {session.get('booking_id')}"
    )


HANDLERS = {
    "extract_request": extract_request,
    "find_services": find_services,
    "remove_services": remove_services,
    "add_services": add_services,
    "service_details": service_details,
    "check_availability": check_availability,
    "book_appointment": book_appointment,
    "read_booking": read_booking,
}


def dispatch(session: dict, name: str, params: dict | None = None) -> str:
    handler = HANDLERS.get(name)
    if not handler:
        return f"Unknown function: {name}"
    try:
        print("\n ==> name",name)
        print("\n ==> params",params)
        return handler(session, **(params or {}))
    except TypeError as exc:
        return f"Bad arguments for {name}: {exc}"
    except Exception as exc:  # noqa: BLE001 — return tool failures to the agent
        return f"Tool error in {name}: {exc}"
