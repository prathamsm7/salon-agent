"""Which model Tara thinks with, and where that call is sent."""

from __future__ import annotations

import logging
import os

from deepgram.types.think_settings_v1 import ThinkSettingsV1
from deepgram.types.think_settings_v1endpoint import ThinkSettingsV1Endpoint
from deepgram.types.think_settings_v1provider import (
    ThinkSettingsV1Provider_Anthropic,
    ThinkSettingsV1Provider_Google,
    ThinkSettingsV1Provider_OpenAi,
)

from app.voice.prompt import SALON_SUPPORT_FUNCTIONS, system_prompt
from app.voice.speak import speaks_bilingual

logger = logging.getLogger("uvicorn.error")


ANTHROPIC_MODEL = "claude-sonnet-5-5"


def _think_provider() -> str:
    return os.environ.get("THINK_PROVIDER", "").strip().lower()


def _use_openai_byo() -> bool:
    """THINK_PROVIDER=openai sends think calls to your OpenAI key."""
    return _think_provider() in {"openai", "open_ai"}


def _openai_model() -> str:
    return os.environ.get("OPENAI_MODEL", "gpt-4.1-mini").strip() or "gpt-4.1-mini"


def think_settings(caller_name: str, recap: str) -> ThinkSettingsV1:
    """Anthropic when THINK_PROVIDER=anthropic. OpenAI BYO bills your key. Google otherwise."""
    prompt = system_prompt(caller_name, recap, bilingual=speaks_bilingual())
    if _think_provider() == "anthropic":
        logger.info("Think provider is Anthropic model %s.", ANTHROPIC_MODEL)
        return ThinkSettingsV1(
            provider=ThinkSettingsV1Provider_Anthropic(
                type="anthropic",
                model=ANTHROPIC_MODEL,
            ),
            prompt=prompt,
            functions=SALON_SUPPORT_FUNCTIONS,
        )
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
            reasoning_mode="high",
        )
    else:
        provider = ThinkSettingsV1Provider_OpenAi(
            type="open_ai",
            model=model,
            temperature=0.4,
            reasoning_mode="high",
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
