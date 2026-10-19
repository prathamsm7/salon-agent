"""Service catalog: search Upstash, then add or remove items in the cart."""

from __future__ import annotations

import hashlib
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
CATALOG_HASH_PATH = DATA_DIR / ".catalog_index_hash"

_index_lock = threading.Lock()
_vector_index: Index | None = None
_index_ready = False

SERVICES_BY_ID = {
    service["service_id"]: service
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


# Bump when metadata fields change, so Upstash is uploaded again even if the file is unchanged.
METADATA_VERSION = "summary-steps-1"


def _service_metadata(service: dict) -> dict:
    """Fields stored beside a catalog vector and shown in the Upstash dashboard."""
    steps = service.get("steps") or []
    return {
        "service_id": service.get("service_id") or "",
        "name": service.get("name") or "",
        "category": service.get("category") or "",
        "gender": service.get("gender") or "",
        "price_inr": int(service.get("price_inr") or 0),
        "duration_min": int(service.get("duration_min") or 0),
        "description": service.get("description") or "",
        "summary": service.get("summary") or "",
        "steps": " ".join(f"{index}. {step}" for index, step in enumerate(steps, start=1)),
    }


def _catalog_hash() -> str:
    """Hash the catalog file and metadata version so a wording or field change is uploaded again."""
    file_hash = hashlib.sha256(SERVICES_PATH.read_bytes()).hexdigest()
    return f"{METADATA_VERSION}:{file_hash}"


def ensure_services_indexed() -> None:
    """Upload the catalog when it is new or the stored wording has changed."""
    global _index_ready
    with _index_lock:
        if _index_ready:
            return
        index = get_vector_index()
        services = list(SERVICES_BY_ID.values())
        digest = _catalog_hash()
        stored = CATALOG_HASH_PATH.read_text(encoding="utf-8").strip() if CATALOG_HASH_PATH.exists() else ""
        info = index.info()
        if stored != digest or getattr(info, "vector_count", 0) < len(services):
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
            CATALOG_HASH_PATH.write_text(digest + "\n", encoding="utf-8")
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
        record = SERVICES_BY_ID.get(service_id) or {}
        options.append(
            {
                "service_id": service_id,
                "name": metadata.get("name") or record.get("name"),
                "category": metadata.get("category") or record.get("category"),
                "gender": metadata.get("gender") or record.get("gender"),
                "price_inr": metadata.get("price_inr")
                if metadata.get("price_inr") is not None
                else record.get("price_inr"),
                "duration_min": metadata.get("duration_min")
                if metadata.get("duration_min") is not None
                else record.get("duration_min"),
                "summary": record.get("summary") or "",
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
        + "\n\nIf they asked to browse a menu, say only that you found options and ask them to choose. "
        "Do not read the numbered list aloud.\n"
        "If they described a problem or asked what would help, recommend from these summaries. "
        "Name the best match and why it fits. Do not mention the price or the duration unless they asked. "
        "Mention one other close option. Use only this text."
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
    """Return the spoken summary and steps for one shown or selected service."""
    if not service_id:
        return "Which service id should I describe?"
    shown = _catalog(session).get(service_id) or {}
    record = SERVICES_BY_ID.get(service_id) or {}
    if not shown and not record:
        return "That detail was not found in our salon records."
    if not shown:
        return "Search services first, then ask about one from the list."

    name = shown.get("name") or record.get("name") or "That service"
    summary = record.get("summary") or shown.get("summary") or "That detail was not found in our salon records."
    price = shown.get("price_inr")
    if price is None:
        price = record.get("price_inr")
    duration = shown.get("duration_min")
    if duration is None:
        duration = record.get("duration_min")
    steps = record.get("steps") or []
    step_lines = "\n".join(f"{index}. {step}" for index, step in enumerate(steps, start=1))
    text = f"{name}. {summary}\nPrice: {price} rupees. Duration: {duration} minutes."
    if step_lines:
        text += f"\nSteps:\n{step_lines}"
    return (
        text
        + "\n\nSpeak this in a few plain sentences. If they asked for the process, walk through the steps in order. "
        "Do not mention the price or the duration unless they asked. Do not add steps that are not listed."
    )


SERVICE_FUNCTIONS = [
    {
        "name": "find_services",
        "description": (
            "Search the catalog. Pass exactly one descriptive phrase per service or problem. "
            "Haircut and beard is two phrases. Dry frizzy hair is one phrase, for example "
            "\"dry frizzy hair smoother treatment\". Do not add synonym queries. "
            "A named service includes gender and the treatment, for example "
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
                        "One phrase per named service or problem. Include the concern or the treatment. "
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
            "Add one chosen service to the cart. Call only after the customer picks a shown option "
            "or asks to add that service. Do not call this for a recommendation, an explanation, "
            "a browse, or a question. Copy only the chosen ids from the latest shown list."
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
            "Remove a service from the cart only after the customer asks to take it out. "
            "Do not call this to clear the cart, to replace a service, or before adding."
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
        "description": (
            "Return the summary, steps, and duration for a shown or selected service id. "
            "Use this when they ask what a service includes, want more about it, or ask for the process."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "service_id": {"type": "string"},
            },
            "required": ["service_id"],
        },
    },
]
