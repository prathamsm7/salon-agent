"""Email one-time codes and bearer tokens."""

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import OtpCode, User
from app.db.session import get_db
from app.mail import send_sign_in_code

OTP_TTL = timedelta(minutes=5)
OTP_COOLDOWN = timedelta(seconds=30)
OTP_ATTEMPTS = 5
TOKEN_TTL = timedelta(days=7)
bearer = HTTPBearer(auto_error=False)


def normalize_email(value: str) -> str | None:
    """Return a lowercase address, or None when it cannot be an email."""
    email = (value or "").strip().lower()
    if not email or len(email) > 254 or " " in email:
        return None
    local, separator, domain = email.partition("@")
    if separator != "@" or not local or "." not in domain:
        return None
    return email


def _secret() -> str:
    secret = os.environ.get("JWT_SECRET", "")
    if not secret:
        raise RuntimeError("JWT_SECRET is required")
    return secret


def _hash_code(email: str, code: str) -> str:
    return hmac.new(
        _secret().encode(),
        f"{email}:{code}".encode(),
        hashlib.sha256,
    ).hexdigest()


def request_otp(db: Session, email: str, name: str | None) -> None:
    user = db.scalar(select(User).where(User.email == email))
    clean_name = (name or "").strip()
    if user is None and not clean_name:
        raise HTTPException(status_code=400, detail={"code": "name_required"})
    if user is None and (len(clean_name) > 80):
        raise HTTPException(status_code=400, detail="Name is too long.")
    now = datetime.now(timezone.utc)
    row = db.scalar(select(OtpCode).where(OtpCode.email == email))
    if row is not None and row.last_sent_at > now - OTP_COOLDOWN:
        raise HTTPException(
            status_code=429,
            detail="Please wait a moment before requesting another code.",
        )
    code = f"{secrets.randbelow(1_000_000):06d}"
    send_sign_in_code(email, code)
    if row is None:
        row = OtpCode(
            email=email,
            code_hash=_hash_code(email, code),
            pending_name=clean_name or None,
            expires_at=now + OTP_TTL,
            last_sent_at=now,
            attempts=0,
        )
        db.add(row)
    else:
        row.code_hash = _hash_code(email, code)
        row.pending_name = clean_name or row.pending_name
        row.expires_at = now + OTP_TTL
        row.last_sent_at = now
        row.attempts = 0
    db.commit()


def verify_otp(db: Session, email: str, code: str) -> User:
    row = db.scalar(select(OtpCode).where(OtpCode.email == email))
    now = datetime.now(timezone.utc)
    if row is None or row.attempts >= OTP_ATTEMPTS or row.expires_at < now:
        raise HTTPException(status_code=401, detail="That code is wrong or expired.")
    if not hmac.compare_digest(row.code_hash, _hash_code(email, code.strip())):
        row.attempts += 1
        db.commit()
        raise HTTPException(status_code=401, detail="That code is wrong or expired.")
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        if not row.pending_name:
            raise HTTPException(status_code=400, detail={"code": "name_required"})
        user = User(email=email, name=row.pending_name)
        db.add(user)
    db.delete(row)
    db.commit()
    db.refresh(user)
    return user


def issue_token(user: User) -> str:
    expires = datetime.now(timezone.utc) + TOKEN_TTL
    return jwt.encode(
        {"sub": str(user.id), "exp": expires},
        _secret(),
        algorithm="HS256",
    )


def user_from_token(token: str, db: Session) -> User | None:
    try:
        payload = jwt.decode(token, _secret(), algorithms=["HS256"])
        user_id = int(payload.get("sub", ""))
    except (jwt.PyJWTError, ValueError):
        return None
    return db.get(User, user_id)


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Sign in again.")
    user = user_from_token(credentials.credentials, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in again.")
    return user
