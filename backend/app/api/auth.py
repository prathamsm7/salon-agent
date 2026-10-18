from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import current_user, issue_token, normalize_email, request_otp, verify_otp
from app.db.models import User
from app.db.session import get_db

router = APIRouter()


class OtpRequest(BaseModel):
    email: str
    name: str | None = None


class OtpVerify(BaseModel):
    email: str
    code: str


class UserOut(BaseModel):
    id: int
    name: str
    email: str


class TokenOut(BaseModel):
    token: str
    user: UserOut


def _email_or_400(value: str) -> str:
    email = normalize_email(value)
    if email is None:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    return email


def _user_out(user: User) -> UserOut:
    return UserOut(id=user.id, name=user.name, email=user.email or "")


@router.post("/otp/request")
def otp_request(body: OtpRequest, db: Session = Depends(get_db)):
    request_otp(db, _email_or_400(body.email), body.name)
    return {"sent": True}


@router.post("/otp/verify", response_model=TokenOut)
def otp_verify(body: OtpVerify, db: Session = Depends(get_db)):
    user = verify_otp(db, _email_or_400(body.email), body.code)
    return TokenOut(token=issue_token(user), user=_user_out(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return _user_out(user)
