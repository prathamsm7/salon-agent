"""Text Tara and the tool results share: service lists, the cart, and open times."""

from __future__ import annotations


def format_options(services) -> str:
    """Number the services just found, including the id the model must copy."""
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
    """List selected services with a price and duration total."""
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
    """Number open times. Slot and staff ids stay in the tool text, not in speech."""
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
