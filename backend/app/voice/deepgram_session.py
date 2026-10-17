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
from deepgram.types.speak_settings_v1provider import SpeakSettingsV1Provider_Deepgram
from deepgram.types.think_settings_v1 import ThinkSettingsV1
from deepgram.types.think_settings_v1provider import ThinkSettingsV1Provider_Google

from app.voice.salon_backend import (
    SALON_SUPPORT_FUNCTIONS,
    dispatch,
    ensure_services_indexed,
    new_session,
    system_prompt,
)

Outgoing = tuple[str, Any]


class DeepgramSalonSession:
    def __init__(self, loop: asyncio.AbstractEventLoop, outgoing: asyncio.Queue[Outgoing]) -> None:
        self.loop = loop
        self.outgoing = outgoing
        self.salon = new_session()
        self._open = True
        self._settings_applied = threading.Event()
        self._send_lock = threading.Lock()
        self._pending_choice_list: str | None = None
        self._agent_cm = None
        self.agent = None

    def start(self) -> None:
        ensure_services_indexed()
        try:
            client = DeepgramClient()
            self._agent_cm = client.agent.v1.connect()
            self.agent = self._agent_cm.__enter__()

            self.agent.on(EventType.MESSAGE, self._on_message)
            self.agent.on(EventType.ERROR, self._on_error)
            self.agent.on(
                EventType.CLOSE,
                lambda _: self._emit("json", {"type": "status", "state": "closed"}),
            )

            self.agent.send_settings(self._settings())
            threading.Thread(target=self.agent.start_listening, daemon=True).start()
            threading.Thread(target=self._keepalive_loop, daemon=True).start()

            if not self._settings_applied.wait(timeout=15):
                raise TimeoutError("Timed out waiting for Deepgram settings")
        except Exception:
            self.close()
            raise

    def send_text(self, content: str) -> None:
        if not self.agent or not content.strip():
            return
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
                language="en",
                listen=AgentV1SettingsAgentListen(
                    provider=AgentV1SettingsAgentListenProvider_V1(
                        type="deepgram",
                        model="nova-3",
                        language="en",
                        smart_format=True,
                        # Wait through a natural pause before deciding the guest has finished.
                        endpointing=2000,
                        keyterms=[
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
                    prompt=system_prompt(),
                    functions=SALON_SUPPORT_FUNCTIONS,
                ),
                speak=SpeakSettingsV1(
                    provider=SpeakSettingsV1Provider_Deepgram(
                        type="deepgram", model="aura-2-thalia-en"
                    )
                ),
                greeting=(
                    "Hi, Welcome to the salon Kesh Kala, this is Tara. "
                    "How can I help you today?"
                ),
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
                self._emit("json", {"type": "transcript", "role": role, "content": content})
        elif msg_type == "AgentStartedSpeaking":
            self._emit("json", {"type": "speaking", "value": True})
        elif msg_type == "AgentAudioDone":
            self._emit("json", {"type": "speaking", "value": False})
            # After Tara finishes speaking so the chat order is reply, then options.
            self._flush_choice_list()
        elif msg_type == "Error":
            description = getattr(message, "description", None) or str(message)
            self._emit("json", {"type": "error", "message": str(description)})
            self._emit("json", {"type": "speaking", "value": False})
            self._flush_choice_list()

    def _flush_choice_list(self) -> None:
        choice_list = self._pending_choice_list
        self._pending_choice_list = None
        if choice_list:
            self._emit("json", {"type": "choice_list", "content": choice_list})

    def _handle_function_call(self, fn: Any) -> None:
        if not self.agent:
            return
        raw_args = fn.arguments
        params = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
        content = dispatch(self.salon, fn.name, params)
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
            try:
                with self._send_lock:
                    if self.agent:
                        self.agent.send_keep_alive(AgentV1KeepAlive())
            except Exception:
                break

    def _emit(self, kind: str, payload: Any) -> None:
        try:
            self.loop.call_soon_threadsafe(self.outgoing.put_nowait, (kind, payload))
        except RuntimeError:
            pass
