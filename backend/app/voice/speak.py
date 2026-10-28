"""Which voice Tara uses: ElevenLabs when it can speak, otherwise Deepgram."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request

from deepgram.types.speak_settings_v1 import SpeakSettingsV1
from deepgram.types.speak_settings_v1endpoint import SpeakSettingsV1Endpoint
from deepgram.types.speak_settings_v1provider import (
    SpeakSettingsV1Provider_Deepgram,
    SpeakSettingsV1Provider_ElevenLabs,
)

logger = logging.getLogger("uvicorn.error")
_ELEVENLABS_RETRY_SECONDS = 120
_speak_lock = threading.Lock()
_elevenlabs_ready = False
_elevenlabs_blocked_until = 0.0


def use_elevenlabs() -> bool:
    """USE_ELEVENLABS=true speaks with ElevenLabs. Anything else uses Deepgram."""
    return os.environ.get("USE_ELEVENLABS", "").strip().lower() in {"1", "true", "yes", "on"}


def elevenlabs_voice() -> tuple[str, str] | None:
    """Return the ElevenLabs key and voice id when the flag is on.

    The voice must be a premade voice on a free key. Library voices are rejected.
    """
    if not use_elevenlabs():
        return None
    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "").strip()
    if not api_key or not voice_id:
        raise RuntimeError("USE_ELEVENLABS is on, but ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID are required.")
    return api_key, voice_id


def speaks_bilingual() -> bool:
    """Hindi replies are only safe when ElevenLabs is the voice."""
    return elevenlabs_voice() is not None


def _deepgram_voice() -> SpeakSettingsV1:
    return SpeakSettingsV1(
        provider=SpeakSettingsV1Provider_Deepgram(
            type="deepgram",
            version="v2",
            model="flux-meena-en",
        )
    )


def _elevenlabs_voice_settings(api_key: str, voice_id: str) -> SpeakSettingsV1:
    return SpeakSettingsV1(
        provider=SpeakSettingsV1Provider_ElevenLabs(
            type="eleven_labs",
            model_id="eleven_turbo_v2_5",
        ),
        endpoint=SpeakSettingsV1Endpoint(
            url=(
                "wss://api.elevenlabs.io/v1/text-to-speech/"
                f"{voice_id}/multi-stream-input"
            ),
            headers={"xi-api-key": api_key},
        ),
    )


def _elevenlabs_block_reason(api_key: str, voice_id: str) -> str | None:
    """Return why ElevenLabs cannot speak, or None when a short phrase succeeds.

    An empty account rejects this without spending a credit. A working account
    uses one character, then the result is kept for the life of the process.
    """
    url = (
        "https://api.elevenlabs.io/v1/text-to-speech/"
        f"{voice_id}?output_format=pcm_16000"
    )
    payload = json.dumps({"text": ".", "model_id": "eleven_turbo_v2_5"}).encode()
    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={"xi-api-key": api_key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            response.read(1)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        if "quota_exceeded" in detail:
            return "ElevenLabs has no credits left, so Tara is speaking with Deepgram."
        return "ElevenLabs refused speech, so Tara is speaking with Deepgram."
    except Exception:
        logger.exception("ElevenLabs speech check failed")
        return "ElevenLabs could not be reached, so Tara is speaking with Deepgram."
    return None


def speak_settings() -> SpeakSettingsV1:
    """Speak with ElevenLabs when it can, and with Meena when it cannot."""
    global _elevenlabs_ready, _elevenlabs_blocked_until
    elevenlabs = elevenlabs_voice()
    if elevenlabs is None:
        return _deepgram_voice()
    api_key, voice_id = elevenlabs
    now = time.monotonic()
    with _speak_lock:
        if _elevenlabs_ready:
            return _elevenlabs_voice_settings(api_key, voice_id)
        if now < _elevenlabs_blocked_until:
            return _deepgram_voice()
        reason = _elevenlabs_block_reason(api_key, voice_id)
        if reason:
            _elevenlabs_blocked_until = time.monotonic() + _ELEVENLABS_RETRY_SECONDS
            logger.warning(reason)
            return _deepgram_voice()
        _elevenlabs_ready = True
        return _elevenlabs_voice_settings(api_key, voice_id)
