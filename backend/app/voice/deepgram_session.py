"""One Deepgram voice-agent socket and its salon booking session."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from typing import Any

import certifi

# The Deepgram websocket uses the default SSL store, which is incomplete
# on some local Python installs. httpx already trusts certifi.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

from deepgram.client import DeepgramClient
from deepgram.agent.v1.types import (
    AgentV1FunctionCallRequest,
    AgentV1InjectAgentMessage,
    AgentV1InjectUserMessage,
    AgentV1KeepAlive,
    AgentV1SendFunctionCallResponse,
    AgentV1Settings,
    AgentV1SettingsAgent,
    AgentV1SettingsAgentListen,
    AgentV1SettingsAgentListenProvider_V1,
    AgentV1SettingsAudio,
    AgentV1SettingsAudioInput,
    AgentV1SettingsAudioOutput,
)
from deepgram.core.events import EventType
from deepgram.types.speak_settings_v1 import SpeakSettingsV1
from deepgram.types.speak_settings_v1endpoint import SpeakSettingsV1Endpoint
from deepgram.types.speak_settings_v1provider import (
    SpeakSettingsV1Provider_Deepgram,
    SpeakSettingsV1Provider_ElevenLabs,
)
from deepgram.types.think_settings_v1 import ThinkSettingsV1
from deepgram.types.think_settings_v1provider import ThinkSettingsV1Provider_Google

from app.voice.salon_backend import (
    SALON_SUPPORT_FUNCTIONS,
    apply_saved_booking,
    dispatch,
    ensure_services_indexed,
    new_session,
    system_prompt,
)
from app.db.store import save_message
from app.voice.action_log import log_action

Outgoing = tuple[str, Any]
IDLE_SECONDS = 45
GOODBYE_LINE = "I'll let you go for now. Call again whenever you'd like."


def use_elevenlabs() -> bool:
    """USE_ELEVENLABS=true speaks with ElevenLabs. Anything else uses Deepgram."""
    return os.environ.get("USE_ELEVENLABS", "").strip().lower() in {"1", "true", "yes", "on"}


def _elevenlabs_voice() -> tuple[str, str] | None:
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


def _speak_settings() -> SpeakSettingsV1:
    """Speak with ElevenLabs only when USE_ELEVENLABS is on. Otherwise use Meena."""
    elevenlabs = _elevenlabs_voice()
    if elevenlabs is None:
        return SpeakSettingsV1(
            provider=SpeakSettingsV1Provider_Deepgram(
                type="deepgram",
                version="v2",
                model="flux-meena-en",
            )
        )
    api_key, voice_id = elevenlabs
    return SpeakSettingsV1(
        provider=SpeakSettingsV1Provider_ElevenLabs(
            type="eleven_labs",
            model_id="eleven_turbo_v2_5",
        ),
        endpoint=SpeakSettingsV1Endpoint(
            url=f"wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/multi-stream-input",
            headers={"xi-api-key": api_key},
        ),
    )


class DeepgramSalonSession:
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        outgoing: asyncio.Queue[Outgoing],
        *,
        user_id: int,
        user_name: str,
        conversation_id: int,
        recap: str = "",
        greeting: str | None = None,
        booking: dict | None = None,
    ) -> None:
        self.loop = loop
        self.outgoing = outgoing
        self.conversation_id = conversation_id
        self.caller_name = user_name
        self.recap = recap
        self.greeting = greeting or (
            "Hi, Welcome to the salon Kesh Kala, this is Tara. "
            "How can I help you today?"
        )
        self.salon = new_session()
        self.salon["user_id"] = user_id
        self.salon["user_name"] = user_name
        self.salon["conversation_id"] = conversation_id
        apply_saved_booking(self.salon, booking)
        self._open = True
        self._settings_applied = threading.Event()
        self._startup_error: str | None = None
        self._send_lock = threading.Lock()
        self._pending_choice_list: str | None = None
        self._agent_cm = None
        self.agent = None
        now = time.monotonic()
        self._last_user_speech = now
        self._quiet_since: float | None = None
        self._agent_speaking = False
        self._end_after_audio = False
        self._end_reason: str | None = None
        self._end_deadline: float | None = None
        self._finished = False

    def start(self) -> None:
        ensure_services_indexed()
        try:
            client = DeepgramClient()
            self._agent_cm = client.agent.v1.connect()
            self.agent = self._agent_cm.__enter__()

            self.agent.on(EventType.MESSAGE, self._on_message)
            self.agent.on(EventType.ERROR, self._on_error)
            self.agent.on(EventType.CLOSE, lambda _: self._on_deepgram_close())

            self.agent.send_settings(self._settings())
            threading.Thread(target=self.agent.start_listening, daemon=True).start()
            threading.Thread(target=self._keepalive_loop, daemon=True).start()

            if not self._settings_applied.wait(timeout=15):
                raise TimeoutError("Timed out waiting for Deepgram settings")
            if self._startup_error:
                raise RuntimeError(self._startup_error)
        except Exception:
            self.close()
            raise

    def send_text(self, content: str) -> None:
        if not self.agent or not content.strip():
            return
        self._note_user_speech()
        with self._send_lock:
            self.agent.send_inject_user_message(AgentV1InjectUserMessage(content=content))

    def send_audio(self, audio: bytes) -> None:
        if not self.agent or not audio:
            return
        with self._send_lock:
            self.agent.send_media(audio)

    def close(self) -> None:
        if not self._open and self._agent_cm is None:
            return
        self._open = False
        agent_cm = self._agent_cm
        self._agent_cm = None
        self.agent = None
        if agent_cm is not None:
            try:
                agent_cm.__exit__(None, None, None)
            except Exception:
                pass
        self._emit("closed", None)

    def _settings(self) -> AgentV1Settings:
        return AgentV1Settings(
            audio=AgentV1SettingsAudio(
                input=AgentV1SettingsAudioInput(encoding="linear16", sample_rate=24000),
                output=AgentV1SettingsAudioOutput(
                    encoding="linear16", sample_rate=24000, container="none"
                ),
            ),
            agent=AgentV1SettingsAgent(
                listen=AgentV1SettingsAgentListen(
                    provider=AgentV1SettingsAgentListenProvider_V1(
                        type="deepgram",
                        model="nova-3",
                        language="multi",
                        smart_format=True,
                        # Silence before the guest is treated as finished. Extra listen fields are rejected.
                        endpointing=500,
                        keyterms=[
                            "hair",
                            "frizzy",
                            "treatment",
                            "smoothening",
                            "haircut",
                            "beard",
                            "facial",
                            "cleanup",
                            "keratin",
                            "highlights",
                            "waxing",
                            "manicure",
                            "pedicure",
                            "rupees",
                        ],
                    )
                ),
                think=ThinkSettingsV1(
                    provider=ThinkSettingsV1Provider_Google(
                        type="google", 
                        model="gemini-3.1-flash-lite",
                    ),
                    prompt=system_prompt(
                        self.caller_name,
                        self.recap,
                        bilingual=_elevenlabs_voice() is not None,
                    ),
                    functions=SALON_SUPPORT_FUNCTIONS,
                ),
                speak=_speak_settings(),
                greeting=self.greeting,
            ),
        )

    def _on_message(self, message: Any) -> None:
        if isinstance(message, bytes):
            self._emit("audio", message)
            return
        if isinstance(message, AgentV1FunctionCallRequest):
            for fn in message.functions:
                self._handle_function_call(fn)
            return

        msg_type = getattr(message, "type", type(message).__name__)
        if msg_type == "SettingsApplied":
            self._settings_applied.set()
            self._emit("json", {"type": "status", "state": "live"})
        elif msg_type == "ConversationText":
            role = getattr(message, "role", "assistant")
            content = getattr(message, "content", "") or ""
            if content:
                stored_role = "user" if role == "user" else "assistant"
                if stored_role == "user":
                    self._note_user_speech()
                save_message(self.conversation_id, stored_role, content)
                self._emit("json", {"type": "transcript", "role": stored_role, "content": content})
        elif msg_type == "UserStartedSpeaking":
            self._note_user_speech()
        elif msg_type == "AgentStartedSpeaking":
            self._agent_speaking = True
            self._emit("json", {"type": "speaking", "value": True})
        elif msg_type == "AgentAudioDone":
            self._agent_speaking = False
            self._quiet_since = time.monotonic()
            self._emit("json", {"type": "speaking", "value": False})
            # After Tara finishes speaking so the chat order is reply, then options.
            self._flush_choice_list()
            if self._end_after_audio:
                self._finish_call()
        elif msg_type == "InjectionRefused" and self._end_reason == "idle":
            self._finish_call()
        elif msg_type == "Error":
            description = getattr(message, "description", None) or str(message)
            if not self._settings_applied.is_set():
                self._startup_error = str(description)
                self._settings_applied.set()
            self._emit("json", {"type": "error", "message": str(description)})
            self._emit("json", {"type": "speaking", "value": False})
            self._flush_choice_list()

    def _flush_choice_list(self) -> None:
        choice_list = self._pending_choice_list
        self._pending_choice_list = None
        if choice_list:
            self._emit("json", {"type": "choice_list", "content": choice_list})
            save_message(self.conversation_id, "choice", choice_list)

    def _handle_function_call(self, fn: Any) -> None:
        if not self.agent:
            return
        raw_args = fn.arguments
        params = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
        content = dispatch(self.salon, fn.name, params)
        if self.salon.get("end_reason") == "goodbye":
            self._end_after_audio = True
            self._end_reason = "goodbye"
            self._end_deadline = time.monotonic() + 20
        choice_list = self.salon.pop("choice_list", None)
        if choice_list:
            # Show after Tara's spoken reply so the chat order is reply, then options.
            self._pending_choice_list = choice_list
        with self._send_lock:
            if not self.agent:
                return
            self.agent.send_function_call_response(
                AgentV1SendFunctionCallResponse(
                    type="FunctionCallResponse",
                    id=fn.id,
                    name=fn.name,
                    content=content if isinstance(content, str) else json.dumps(content),
                )
            )

    def _on_error(self, error: Any) -> None:
        self._emit("json", {"type": "error", "message": str(error)})

    def _keepalive_loop(self) -> None:
        while self._open:
            time.sleep(5)
            if not self._open or not self.agent or not self._settings_applied.is_set():
                continue
            if (
                self._end_after_audio
                and self._end_deadline is not None
                and time.monotonic() > self._end_deadline
            ):
                self._finish_call()
                continue
            self._close_if_idle()
            try:
                with self._send_lock:
                    if self.agent:
                        self.agent.send_keep_alive(AgentV1KeepAlive())
            except Exception:
                break

    def _note_user_speech(self) -> None:
        self._last_user_speech = time.monotonic()

    def _close_if_idle(self) -> None:
        """After Tara is quiet and the guest says nothing, say goodbye and close."""
        if self._end_after_audio or self._agent_speaking or self._quiet_since is None:
            return
        now = time.monotonic()
        if now - self._quiet_since < IDLE_SECONDS or now - self._last_user_speech < IDLE_SECONDS:
            return
        self._end_after_audio = True
        self._end_reason = "idle"
        self._end_deadline = time.monotonic() + 20
        log_action(self.salon, "end_session", {"reason": "idle"}, "Closing after no reply.")
        try:
            with self._send_lock:
                if self.agent:
                    self.agent.send_inject_agent_message(
                        AgentV1InjectAgentMessage(message=GOODBYE_LINE, behavior="queue")
                    )
        except Exception:
            self._finish_call()

    def _finish_call(self) -> None:
        with self._send_lock:
            if self._finished:
                return
            self._finished = True
        self._emit("json", {"type": "status", "state": "ended", "reason": self._end_reason or "goodbye"})
        self.close()

    def _on_deepgram_close(self) -> None:
        if self._end_reason:
            return
        self._emit("json", {"type": "status", "state": "closed"})

    def _emit(self, kind: str, payload: Any) -> None:
        try:
            self.loop.call_soon_threadsafe(self.outgoing.put_nowait, (kind, payload))
        except RuntimeError:
            pass
