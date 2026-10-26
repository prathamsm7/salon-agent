"""Deliver the sign-in code by email."""

import os
import smtplib
from email.message import EmailMessage

import httpx
from fastapi import HTTPException

_SUBJECT = "Your Kesh Kala sign-in code"
_FAILED = "The sign-in email could not be sent."


def _body(code: str) -> str:
    return f"Your Kesh Kala sign-in code is {code}.\nIt expires in five minutes.\n"


def send_sign_in_code(email: str, code: str) -> None:
    """Email a 6-digit code. Gmail is used when SMTP is configured."""
    if os.environ.get("SMTP_HOST", "").strip():
        _send_smtp(email, code)
        return
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    if not api_key:
        print(f"OTP for {email}: {code}", flush=True)
        return
    sender = os.environ.get("RESEND_FROM", "Kesh Kala <onboarding@resend.dev>").strip()
    try:
        response = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "from": sender,
                "to": [email],
                "subject": _SUBJECT,
                "text": _body(code),
            },
            timeout=15,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=_FAILED) from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=_FAILED)


def _send_smtp(email: str, code: str) -> None:
    host = os.environ["SMTP_HOST"].strip()
    port = int(os.environ.get("SMTP_PORT", "587") or "587")
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").replace(" ", "")
    sender = os.environ.get("SMTP_FROM", "").strip() or user
    message = EmailMessage()
    message["From"] = sender
    message["To"] = email
    message["Subject"] = _SUBJECT
    message.set_content(_body(code))
    try:
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.starttls()
            if user:
                server.login(user, password)
            server.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise HTTPException(status_code=502, detail=_FAILED) from exc
