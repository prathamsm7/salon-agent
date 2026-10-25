from __future__ import annotations

import logging
import os
import queue
import re
import threading
import time
from collections.abc import Callable
from functools import lru_cache
from typing import Any

from langfuse import get_client, propagate_attributes

logger = logging.getLogger(__name__)
_open_sessions: dict[str, Any] = {}
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


def _trace_context(session: dict) -> dict | None:
    context = session.get("trace_context")
    if not isinstance(context, dict) or not context.get("trace_id"):
        return None
    return {
        "trace_id": context["trace_id"],
        "parent_span_id": context.get("parent_span_id"),
    }


def begin_session_trace(session: dict, greeting: str) -> None:
    """Open one trace for this call. Later turns and tools attach to it."""
    greeting_text = greeting or ""

    def job() -> None:
        _begin_session_trace(session, greeting_text)

    _submit(job)


def _begin_session_trace(session: dict, greeting: str) -> None:
    if _trace_context(session):
        return
    session_id, traced_user = _ids(session)
    conversation_id = session.get("conversation_id")
    try:
        client = _client()
        with client.start_as_current_observation(
            name="salon.session",
            as_type="span",
            input={"greeting": _clip(greeting or "")},
            metadata={
                "component": "salon-agent",
                "conversation_id": str(conversation_id or ""),
            },
            end_on_exit=False,
        ) as span:
            with propagate_attributes(
                session_id=session_id,
                user_id=traced_user,
                tags=["salon-agent", "deepgram"],
                trace_name="salon.session",
            ):
                span.update(metadata={"conversation_id": str(conversation_id or "")})
            session["trace_context"] = {
                "trace_id": span.trace_id,
                "parent_span_id": span.id,
            }
            _open_sessions[span.trace_id] = span
    except Exception:
        logger.exception("Could not start Langfuse session")


def trace_turn(session: dict, role: str, content: str) -> None:
    """Record one customer, Tara, or on-screen list inside the open session."""
    if not content:
        return
    text = content

    def job() -> None:
        _trace_turn(session, role, text)

    _submit(job)


def _trace_turn(session: dict, role: str, content: str) -> None:
    context = _trace_context(session)
    if not context or not content:
        return
    text = _clip(content)
    session_id, traced_user = _ids(session)
    payload = {"role": role, "text": text}
    try:
        with _client().start_as_current_observation(
            trace_context=context,
            name=f"salon.turn.{role}",
            as_type="span",
            input={"role": role} if role == "assistant" else payload,
            output=payload,
        ):
            with propagate_attributes(
                session_id=session_id,
                user_id=traced_user,
                tags=["salon-agent", "deepgram"],
                trace_name="salon.session",
            ):
                pass
    except Exception:
        logger.exception("Could not record Langfuse turn")


def trace_thinking(session: dict, content: str) -> None:
    """Record one Deepgram AgentThinking event on the open session."""
    if not content:
        return
    text = content

    def job() -> None:
        _trace_thinking(session, text)

    _submit(job)


def _trace_thinking(session: dict, content: str) -> None:
    context = _trace_context(session)
    if not context or not content:
        return
    text = _clip(content)
    session_id, traced_user = _ids(session)
    try:
        with _client().start_as_current_observation(
            trace_context=context,
            name="salon.agent.thinking",
            as_type="span",
            input={"role": "thinking"},
            output={"text": text},
        ):
            with propagate_attributes(
                session_id=session_id,
                user_id=traced_user,
                tags=["salon-agent", "deepgram"],
                trace_name="salon.session",
            ):
                pass
    except Exception:
        logger.exception("Could not record Langfuse thinking")


def trace_session_error(session: dict, message: str) -> None:
    """Record a voice-session failure on the open trace."""
    text = message

    def job() -> None:
        _trace_session_error(session, text)

    _submit(job)


def _trace_session_error(session: dict, message: str) -> None:
    context = _trace_context(session)
    if not context:
        return
    session_id, traced_user = _ids(session)
    try:
        with _client().start_as_current_observation(
            trace_context=context,
            name="salon.error",
            as_type="span",
            input={"message": _clip(message, 1000)},
            level="ERROR",
            status_message="Voice session error",
        ):
            with propagate_attributes(
                session_id=session_id,
                user_id=traced_user,
                tags=["salon-agent", "deepgram"],
                trace_name="salon.session",
            ):
                pass
    except Exception:
        logger.exception("Could not record Langfuse session error")


def finish_session_trace(session: dict, reason: str | None) -> None:
    """Close the session trace. A second close does nothing."""

    def job() -> None:
        _finish_session_trace(session, reason)

    _submit(job)


def _finish_session_trace(session: dict, reason: str | None) -> None:
    context = session.get("trace_context")
    if not isinstance(context, dict) or context.get("closed"):
        return
    context["closed"] = True
    span = _open_sessions.pop(context.get("trace_id") or "", None)
    if span is None:
        return
    try:
        span.update(
            output={"end_reason": reason or "closed"},
            status_message=reason or "closed",
        )
        span.end()
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
    user_id: Any,
    elapsed_ms: float,
    result: str | None = None,
    error_type: str | None = None,
) -> None:
    client = _client()
    with client.start_as_current_observation(
        trace_context=_trace_context(session),
        as_type="tool",
        name=f"salon.tool.{tool_name}",
        input=trace_input,
        metadata={
            "component": "salon-agent",
            "conversation_id": str(conversation_id or ""),
        },
    ) as observation:
        with propagate_attributes(
            session_id=(
                f"salon-conversation-{conversation_id}"
                if conversation_id
                else None
            ),
            user_id=f"salon-user-{user_id}" if user_id else None,
            tags=["salon-agent", "deepgram"],
        ):
            if error_type:
                observation.update(
                    output={"error_type": error_type},
                    metadata={"duration_ms": elapsed_ms, "tool_error": True},
                    level="ERROR",
                    status_message="Unhandled tool exception",
                )
                return
            is_error = str(result).startswith(
                (
                    "Tool error in ",
                    "Bad arguments for ",
                    "Unknown function: ",
                )
            )
            observation.update(
                output={"result": redact_text(str(result))},
                metadata={
                    "duration_ms": elapsed_ms,
                    "tool_error": is_error,
                },
                level="ERROR" if is_error else "DEFAULT",
                status_message="Tool returned an error" if is_error else "Success",
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