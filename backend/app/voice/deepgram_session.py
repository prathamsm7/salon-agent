"""One Deepgram voice-agent socket and its salon booking session."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
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

from app.voice.salon_backend import (
    apply_saved_booking,
    dispatch,
    ensure_services_indexed,
    new_session,
)
from app.voice.speak import speak_settings
from app.voice.think import think_settings
from app.db.store import save_message
from app.observability.langfuse_tracing import (
    begin_session_trace,
    finish_session_trace,
    trace_session_error,
    trace_thinking,
    trace_turn,
)
from app.voice.action_log import log_action

Outgoing = tuple[str, Any]
# Guests often read the on-screen list before they speak. A short pause must not hang up.
IDLE_SECONDS = 180
GOODBYE_LINE = "I'll let you go for now. Call again whenever you'd like."
logger = logging.getLogger("uvicorn.error")


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
        self._last_activity = now
        self._quiet_since: float | None = None
        self._agent_speaking = False
        self._tools_in_flight = 0
        self._functions: queue.Queue = queue.Queue()
        self._end_after_audio = False
        self._end_reason: str | None = None
        self._end_deadline: float | None = None
        self._finished = False
        self._send_failed = False

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
            threading.Thread(target=self._function_loop, daemon=True).start()
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
        if not self.agent or not audio or self._send_failed:
            return
        # The mic streams while the guest is on the call, including while they speak.
        self._note_user_speech()
        try:
            with self._send_lock:
                if self.agent:
                    self.agent.send_media(audio)
        except Exception as exc:
            self._fail_send(exc)

    def close(self) -> None:
        if not self._open and self._agent_cm is None:
            return
        self._open = False
        self._functions.put(None)
        finish_session_trace(self.salon, self._end_reason or "closed")
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
                # The browser downsamples the microphone to 24 kHz. A higher rate here
                # makes speech unintelligible, so typed messages still work and voice does not.
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
                        # multi writes Indian English in Telugu or Gujarati script. en-IN stays English.
                        language="en-IN",
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
                think=think_settings(self.caller_name, self.recap),
                speak=speak_settings(),
                greeting=self.greeting,
            ),
        )

    def _fail_send(self, exc: Exception) -> None:
        if self._send_failed:
            return
        self._send_failed = True
        logger.exception("Voice audio send failed conversation=%s", self.conversation_id)
        self._emit("json", {"type": "error", "message": "The voice line dropped while sending audio."})

    def _on_message(self, message: Any) -> None:
        try:
            self._on_message_inner(message)
        except Exception:
            logger.exception("Voice event handler failed conversation=%s", self.conversation_id)

    def _on_message_inner(self, message: Any) -> None:
        if isinstance(message, bytes):
            # Audio is still arriving, so this is not a quiet stretch.
            self._note_activity()
            self._emit("audio", message)
            return
        if isinstance(message, AgentV1FunctionCallRequest):
            for fn in message.functions:
                # Answer off the socket thread. A calendar check must not stall Deepgram's read loop.
                with self._send_lock:
                    self._tools_in_flight += 1
                self._quiet_since = None
                self._note_activity()
                self._cancel_idle_goodbye()
                self._functions.put(fn)
            return

        msg_type = getattr(message, "type", type(message).__name__)
        if msg_type == "SettingsApplied":
            self._settings_applied.set()
            self._emit("json", {"type": "status", "state": "live"})
            begin_session_trace(self.salon, self.greeting)
        elif msg_type == "ConversationText":
            role = getattr(message, "role", "assistant")
            content = getattr(message, "content", "") or ""
            if content:
                stored_role = "user" if role == "user" else "assistant"
                if stored_role == "user":
                    self._note_user_speech()
                    self.salon["last_user_message"] = content
                save_message(self.conversation_id, stored_role, content)
                self._emit("json", {"type": "transcript", "role": stored_role, "content": content})
                trace_turn(self.salon, stored_role, content)
        elif msg_type == "AgentThinking":
            self._note_activity()
            if not self._agent_speaking and self._tools_in_flight == 0:
                self._quiet_since = time.monotonic()
            content = getattr(message, "content", "") or ""
            if content:
                logger.info(
                    "\n\nconversation=%s agent_thinking=%s\n\n",
                    self.conversation_id,
                    " ".join(content.split())[:400],
                )
                trace_thinking(self.salon, content)
        elif msg_type == "UserStartedSpeaking":
            self._note_user_speech()
            # The guest talked over Tara. The browser stops her buffered audio.
            self._emit("json", {"type": "barge_in"})
        elif msg_type == "AgentStartedSpeaking":
            self._agent_speaking = True
            self._quiet_since = None
            self._note_activity()
            self._emit("json", {"type": "speaking", "value": True})
        elif msg_type == "AgentAudioDone":
            self._agent_speaking = False
            self._quiet_since = time.monotonic()
            self._note_activity()
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
            trace_session_error(self.salon, str(description))
            self._emit("json", {"type": "error", "message": str(description)})
            self._emit("json", {"type": "speaking", "value": False})
            self._flush_choice_list()

    def _flush_choice_list(self) -> None:
        choice_list = self._pending_choice_list
        self._pending_choice_list = None
        if choice_list:
            self._emit("json", {"type": "choice_list", "content": choice_list})
            save_message(self.conversation_id, "choice", choice_list)
            trace_turn(self.salon, "choice", choice_list)

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
        trace_session_error(self.salon, str(error))
        self._emit("json", {"type": "error", "message": str(error)})

    def _function_loop(self) -> None:
        while True:
            fn = self._functions.get()
            if fn is None or not self._open:
                return
            try:
                self._handle_function_call(fn)
            except Exception:
                logger.exception("Voice function call failed")
            finally:
                with self._send_lock:
                    self._tools_in_flight = max(0, self._tools_in_flight - 1)
                    still_working = self._tools_in_flight > 0
                self._note_activity()
                if not still_working and not self._agent_speaking and self._open:
                    # The guest's wait starts when the work finishes, not when they last spoke.
                    self._quiet_since = time.monotonic()

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
        self._note_activity()
        self._cancel_idle_goodbye()

    def _note_activity(self) -> None:
        """Tara is working or audio is still moving. This does not cancel a goodbye."""
        self._last_activity = time.monotonic()

    def _cancel_idle_goodbye(self) -> None:
        if self._finished or self._end_reason != "idle":
            return
        # They spoke, or a tool started, after the idle goodbye was queued. Stay on the call.
        self._end_after_audio = False
        self._end_reason = None
        self._end_deadline = None

    def _close_if_idle(self) -> None:
        """After Tara is quiet and the guest says nothing, say goodbye and close."""
        if (
            self._end_after_audio
            or self._agent_speaking
            or self._tools_in_flight
            or self._quiet_since is None
        ):
            return
        now = time.monotonic()
        if (
            now - self._quiet_since < IDLE_SECONDS
            or now - self._last_user_speech < IDLE_SECONDS
            or now - self._last_activity < IDLE_SECONDS
        ):
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
        reason = self._end_reason or "dropped"
        logger.info(
            "Deepgram socket closed conversation=%s reason=%s",
            self.conversation_id,
            reason,
        )
        if self._end_reason:
            return
        self._emit("json", {"type": "status", "state": "closed"})

    def _emit(self, kind: str, payload: Any) -> None:
        try:
            self.loop.call_soon_threadsafe(self.outgoing.put_nowait, (kind, payload))
        except RuntimeError:
            pass
