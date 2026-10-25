"""Which model Tara thinks with, and where that call is sent."""

from __future__ import annotations

import logging
import os

from deepgram.types.think_settings_v1 import ThinkSettingsV1
from deepgram.types.think_settings_v1endpoint import ThinkSettingsV1Endpoint
from deepgram.types.think_settings_v1provider import (
    ThinkSettingsV1Provider_Google,
    ThinkSettingsV1Provider_OpenAi,
)

from app.voice.prompt import SALON_SUPPORT_FUNCTIONS, system_prompt
from app.voice.speak import speaks_bilingual

logger = logging.getLogger("uvicorn.error")


def _use_openai_byo() -> bool:
    """THINK_PROVIDER=openai sends think calls to your OpenAI key."""
    return os.environ.get("THINK_PROVIDER", "").strip().lower() in {"openai", "open_ai"}


def _openai_model() -> str:
    return os.environ.get("OPENAI_MODEL", "gpt-4.1-mini").strip() or "gpt-4.1-mini"


def think_settings(caller_name: str, recap: str) -> ThinkSettingsV1:
    """Google stays the default. OpenAI BYO bills and logs on your OpenAI account."""
    prompt = system_prompt(caller_name, recap, bilingual=speaks_bilingual())
    if not _use_openai_byo():
        return ThinkSettingsV1(
            provider=ThinkSettingsV1Provider_Google(
                type="google",
                model="gemini-3.1-flash-lite",
            ),
            prompt=prompt,
            functions=SALON_SUPPORT_FUNCTIONS,
        )

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("THINK_PROVIDER=openai requires OPENAI_API_KEY.")
    model = _openai_model()
    # Reasoning models reject temperature. Keep voice turns on the lowest effort.
    if model.startswith("gpt-5"):
        provider = ThinkSettingsV1Provider_OpenAi(
            type="open_ai",
            model=model,
            reasoning_mode="minimal",
        )
    else:
        provider = ThinkSettingsV1Provider_OpenAi(
            type="open_ai",
            model=model,
            temperature=0.4,
        )
    logger.info(
        "Think provider is OpenAI BYO model %s. Turns are logged on your OpenAI account.",
        model,
    )
    return ThinkSettingsV1(
        provider=provider,
        endpoint=ThinkSettingsV1Endpoint(
            url="https://api.openai.com/v1/chat/completions",
            headers={"authorization": f"Bearer {api_key}"},
        ),
        prompt=prompt,
        functions=SALON_SUPPORT_FUNCTIONS,
        context_length="max",
    )
