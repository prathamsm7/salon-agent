"""Service catalog: search Upstash, then add or remove items in the cart."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from dotenv import load_dotenv
from upstash_vector import Index, Vector

from app.voice.session_state import set_choice_list
from app.voice.text_format import format_cart, format_options

BACKEND_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_DIR / ".env")

DATA_DIR = BACKEND_DIR / "data"
STAFF_DB_PATH = DATA_DIR / "staff.json"
SERVICES_PATH = DATA_DIR / "salon_services_rich.json"

_index_lock = threading.Lock()
_vector_index: Index | None = None
_index_ready = False

SERVICE_DETAILS = {
    service["service_id"]: service.get("description") or ""
    for service in json.load(open(SERVICES_PATH, encoding="utf-8"))
    if service.get("service_id")
}


def normalize_gender(value: str | None) -> str | None:
    """Map spoken words such as 'men' or 'ladies' onto Male, Female, or Unisex."""
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


def load_staff(path: Path = STAFF_DB_PATH) -> list[dict]:
    """Read the staff reference file. The live schedule uses the database copy."""
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def get_vector_index() -> Index:
    """Open Upstash on first use so the rest of the API can start without it."""
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


def _service_metadata(service: dict) -> dict:
    """Fields stored beside a catalog vector and returned with a search hit."""
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
    """Upload the catalog when Upstash does not already hold every service."""
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
    """Return the closest catalog matches, limited to the requested gender."""
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


def _catalog(session: dict) -> dict[str, dict]:
    """Services the caller has been shown or has already put in the cart."""
    catalog = {}
    for service in session.get("retrieved_services") or []:
        if service.get("service_id"):
            catalog[service["service_id"]] = service
    for service in session.get("selected_services") or []:
        if service.get("service_id"):
            catalog.setdefault(service["service_id"], service)
    return catalog


def find_services(
    session: dict,
    queries: list[str] | None = None,
    categories: list[str] | None = None,
    gender: str | None = None,
    **_,
) -> str:
    """Search once per phrase the customer named and show the matches on screen."""
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
    set_choice_list(session, panel)
    return (
        "\n\n".join(blocks)
        + "\n\nSay only that you found options for these topics and ask them to select "
        "their choice. Do not read the numbered list aloud."
    )


def add_services(session: dict, service_ids: list[str] | None = None, **_) -> str:
    """Add shown service ids to the cart. Unknown ids are left out."""
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
    """Drop service ids from the cart. Ids that are not in the cart are ignored."""
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
    """Return the stored description for one shown service."""
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


SERVICE_FUNCTIONS = [
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
        "description": (
            "Remove service ids from the cart. Call the function only after asked to remove a service. "
            "Remove a service only if the cart is not empty."
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
]
