from __future__ import annotations

import json
import logging
import os
import queue
import re
import threading
import time
import uuid
from collections.abc import Callable
from functools import lru_cache
from typing import Any

from langfuse import get_client, propagate_attributes

logger = logging.getLogger(__name__)
_jobs: queue.Queue = queue.Queue()
_worker_lock = threading.Lock()
_worker_started = False


def _worker() -> None:
    while True:
        job = _jobs.get()
        try:
            job()
        except Exception:
            logger.exception("Langfuse trace job failed")
        finally:
            _jobs.task_done()


def _submit(job: Callable[[], None]) -> None:
    """Queue trace work so the voice socket never waits on Langfuse."""
    if not is_configured():
        return
    global _worker_started
    with _worker_lock:
        if not _worker_started:
            threading.Thread(target=_worker, name="langfuse-trace", daemon=True).start()
            _worker_started = True
    _jobs.put(job)


def is_configured() -> bool:
    return bool(
        os.getenv("LANGFUSE_PUBLIC_KEY")
        and os.getenv("LANGFUSE_SECRET_KEY")
    )


@lru_cache(maxsize=1)
def _client():
    return get_client()


def redact_text(value: str) -> str:
    """Basic redaction before exporting tool output."""
    value = re.sub(
        r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
        "[REDACTED_EMAIL]",
        value,
    )

    # Mask common phone-number formats.
    value = re.sub(
        r"(?<!\w)\+?\d[\d\s().-]{8,}\d(?!\w)",
        "[REDACTED_PHONE]",
        value,
    )

    # Mask booking codes such as BOOK-20261024-ABC123.
    value = re.sub(
        r"\bBOOK-[A-Z0-9-]+\b",
        "[REDACTED_BOOKING_CODE]",
        value,
        flags=re.IGNORECASE,
    )

    return value


def safe_arguments(value: Any) -> Any:
    """Remove common sensitive fields from nested tool arguments."""
    sensitive_keys = {
        "email",
        "phone",
        "password",
        "token",
        "authorization",
        "booking_id",
        "booking_code",
        "customer_name",
        "user_name",
    }

    if isinstance(value, dict):
        return {
            key: (
                "[REDACTED]"
                if key.lower() in sensitive_keys
                else safe_arguments(item)
            )
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [safe_arguments(item) for item in value]

    if isinstance(value, str):
        return redact_text(value)

    return value


def _clip(value: str, limit: int = 4000) -> str:
    text = redact_text(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _ids(session: dict) -> tuple[str | None, str | None]:
    conversation_id = session.get("conversation_id")
    user_id = session.get("user_id")
    session_id = f"salon-conversation-{conversation_id}" if conversation_id else None
    traced_user = f"salon-user-{user_id}" if user_id else None
    return session_id, traced_user


def _tags(session: dict) -> list[str]:
    tags = ["salon-agent", "deepgram"]
    conversation_id = session.get("conversation_id")
    if conversation_id is not None and str(conversation_id) != "":
        tags.append(f"conversation-{conversation_id}")
    return tags


def _propagate(session: dict, trace_name: str):
    """Apply session id and tags before the span is created.

    Langfuse only groups a trace into a session when session_id is present at
    creation. Tags are immutable after that, so the conversation id has to be
    included here too.
    """
    session_id, traced_user = _ids(session)
    return propagate_attributes(
        session_id=session_id,
        user_id=traced_user,
        tags=_tags(session),
        trace_name=trace_name,
    )


def _metadata(session: dict, extra: dict | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "component": "salon-agent",
        "conversation_id": str(session.get("conversation_id") or ""),
    }
    if extra:
        data.update(extra)
    return data


def _emit(session: dict, *, name: str, as_type: str, **kwargs: Any) -> None:
    """Write one finished trace into this call's Langfuse session."""
    metadata = _metadata(session, kwargs.pop("metadata", None))
    try:
        with _propagate(session, name):
            with _client().start_as_current_observation(
                name=name,
                as_type=as_type,  # type: ignore[arg-type]
                metadata=metadata,
                **kwargs,
            ):
                pass
        _client().flush()
    except Exception:
        logger.exception("Could not record Langfuse %s", name)


def _think_model() -> str:
    provider = os.getenv("THINK_PROVIDER", "").strip().lower()
    if provider in {"openai", "open_ai"}:
        return os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip() or "gpt-4.1-mini"
    return "gemini-3.1-flash-lite"


def _chat_message(role: str, content: str) -> dict[str, str]:
    """Langfuse only replays messages that use role and content."""
    mapped = {"user": "user", "assistant": "assistant", "system": "system", "tool": "tool"}.get(
        role, "assistant"
    )
    return {"role": mapped, "content": _clip(content)}


def _tool_messages(tool_name: str, arguments: Any, content: str) -> list[dict[str, Any]]:
    tool_call_id = f"call_{uuid.uuid4().hex[:16]}"
    arguments_json = json.dumps(safe_arguments(arguments), default=str)
    return [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": tool_call_id,
                    "type": "function",
                    "name": tool_name,
                    "arguments": arguments_json,
                    "function": {"name": tool_name, "arguments": arguments_json},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": _clip(content),
        },
    ]


def begin_session_trace(session: dict, greeting: str) -> None:
    """Record the greeting as its own trace in this call's session."""
    greeting_text = greeting or ""

    def job() -> None:
        _begin_session_trace(session, greeting_text)

    _submit(job)


def _begin_session_trace(session: dict, greeting: str) -> None:
    if session.get("trace_context"):
        return
    # Marks this call so a second settings event does not greet twice.
    session["trace_context"] = {"started": True}
    if not greeting:
        return
    _emit(
        session,
        name="salon.session",
        as_type="generation",
        model=_think_model(),
        output=[_chat_message("assistant", greeting)],
    )


def trace_turn(session: dict, role: str, content: str) -> None:
    """Record one customer, Tara, or on-screen list as its own session trace."""
    if not content:
        return
    text = content

    def job() -> None:
        _trace_turn(session, role, text)

    _submit(job)


def _trace_turn(session: dict, role: str, content: str) -> None:
    if not content:
        return
    message = _chat_message(role, content)
    payload = [message]
    if message["role"] == "user":
        _emit(
            session,
            name=f"salon.turn.{role}",
            as_type="generation",
            model=_think_model(),
            input=payload,
        )
        return
    _emit(
        session,
        name=f"salon.turn.{role}",
        as_type="generation",
        model=_think_model(),
        output=payload,
    )


def trace_thinking(session: dict, content: str) -> None:
    """Record one Deepgram AgentThinking event on the open session."""
    if not content:
        return
    text = content

    def job() -> None:
        _trace_thinking(session, text)

    _submit(job)


def _trace_thinking(session: dict, content: str) -> None:
    if not content:
        return
    _emit(
        session,
        name="salon.agent.thinking",
        as_type="span",
        output=_clip(content),
    )


def trace_session_error(session: dict, message: str) -> None:
    """Record a voice-session failure on the open trace."""
    text = message

    def job() -> None:
        _trace_session_error(session, text)

    _submit(job)


def _trace_session_error(session: dict, message: str) -> None:
    _emit(
        session,
        name="salon.error",
        as_type="span",
        input={"message": _clip(message, 1000)},
        level="ERROR",
        status_message="Voice session error",
    )


def finish_session_trace(session: dict, reason: str | None) -> None:
    """Flush this call's traces. A second close does nothing."""

    def job() -> None:
        _finish_session_trace(session, reason)

    _submit(job)


def _finish_session_trace(session: dict, reason: str | None) -> None:
    context = session.get("trace_context")
    if isinstance(context, dict):
        if context.get("closed"):
            return
        context["closed"] = True
    try:
        # End reason stays in metadata. An output object is what the session
        # view renders as "JSON-only" instead of the conversation.
        if reason:
            _emit(
                session,
                name="salon.session.end",
                as_type="span",
                metadata={"end_reason": reason},
                status_message=reason,
            )
            return
        _client().flush()
    except Exception:
        logger.exception("Could not finish Langfuse session")


def trace_tool_call(
    session: dict,
    tool_name: str,
    arguments: dict,
    execute: Callable[[], str],
) -> str:
    """Trace one tool execution without requiring Langfuse to be configured."""
    if not is_configured():
        return execute()

    conversation_id = session.get("conversation_id")
    user_id = session.get("user_id")

    trace_input = {
        "tool_name": tool_name,
        "arguments": safe_arguments(arguments),
    }

    if os.getenv("LANGFUSE_CAPTURE_USER_TEXT", "").lower() == "true":
        message = session.get("last_user_message")
        if message:
            trace_input["user_message"] = redact_text(str(message))

    started = time.perf_counter()
    try:
        result = execute()
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        _submit(
            lambda: _record_tool(
                session,
                tool_name,
                trace_input,
                conversation_id,
                user_id,
                elapsed_ms,
                error_type=type(exc).__name__,
            )
        )
        raise
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    recorded = result
    _submit(
        lambda: _record_tool(
            session,
            tool_name,
            trace_input,
            conversation_id,
            user_id,
            elapsed_ms,
            result=recorded,
        )
    )
    return result


def _record_tool(
    session: dict,
    tool_name: str,
    trace_input: dict,
    conversation_id: Any,
    _user_id: Any,
    elapsed_ms: float,
    result: str | None = None,
    error_type: str | None = None,
) -> None:
    if error_type:
        content = f"Tool error in {tool_name}: {error_type}"
        level = "ERROR"
        status = "Unhandled tool exception"
        tool_error = True
    else:
        content = redact_text(str(result))
        tool_error = content.startswith(
            (
                "Tool error in ",
                "Bad arguments for ",
                "Unknown function: ",
            )
        )
        level = "ERROR" if tool_error else "DEFAULT"
        status = "Tool returned an error" if tool_error else "Success"

    call_message, result_message = _tool_messages(
        tool_name,
        trace_input.get("arguments", {}),
        content,
    )
    _emit(
        session,
        name=f"salon.tool.{tool_name}",
        as_type="tool",
        input=[call_message],
        output=[result_message],
        metadata={
            "conversation_id": str(conversation_id or ""),
            "duration_ms": elapsed_ms,
            "tool_error": tool_error,
        },
        level=level,
        status_message=status,
    )


def flush_langfuse() -> None:
    """Flush pending traces during application shutdown."""
    if not is_configured():
        return

    try:
        _jobs.join()
        _client().flush()
    except Exception:
        logger.exception("Could not flush Langfuse traces")