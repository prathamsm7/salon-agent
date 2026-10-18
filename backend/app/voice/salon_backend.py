"""Public entry points for the receptionist.

Search lives in ``catalog``, open times in ``availability``, and appointments in
``appointments``. ``dispatch`` sends each Deepgram tool call to the right one.
"""

from app.voice.catalog import ensure_services_indexed
from app.voice.dispatch import dispatch
from app.voice.prompt import SALON_SUPPORT_FUNCTIONS, system_prompt
from app.voice.session_state import apply_saved_booking, new_session

__all__ = [
    "SALON_SUPPORT_FUNCTIONS",
    "apply_saved_booking",
    "dispatch",
    "ensure_services_indexed",
    "new_session",
    "system_prompt",
]
