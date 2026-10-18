"""Deliver the sign-in code by email through Resend."""

import os

import httpx
from fastapi import HTTPException


def send_sign_in_code(email: str, code: str) -> None:
    """Email a 6-digit code. Without a Resend key, print it for local sign-in."""
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
                "subject": "Your Kesh Kala sign-in code",
                "text": (
                    f"Your Kesh Kala sign-in code is {code}.\n"
                    "It expires in five minutes.\n"
                ),
            },
            timeout=15,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="The sign-in email could not be sent.") from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="The sign-in email could not be sent.")
