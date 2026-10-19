"""Append one line per voice-agent action so production calls can be traced."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
LOG_PATH = LOG_DIR / "actions.log"

_logger: logging.Logger | None = None


def _logger_for_actions() -> logging.Logger:
    global _logger
    if _logger is not None:
        return _logger
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("salon.actions")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        formatter = logging.Formatter("%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        file_handler = RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
        file_handler.setFormatter(formatter)
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.addHandler(stream_handler)
    _logger = logger
    return logger


def log_action(session: dict, name: str, params: dict | None, result: str) -> None:
    """Record one tool call with the caller, the arguments, and a short result."""
    summary = " ".join(result.split())
    if len(summary) > 400:
        summary = summary[:400] + "..."
    _logger_for_actions().info(
        "user=%s conversation=%s action=%s params=%s result=%s",
        session.get("user_id"),
        session.get("conversation_id"),
        name,
        params or {},
        summary,
    )
