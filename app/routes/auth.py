import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User, UserPreference
from app.schemas import LoginRequest, SignupRequest
from app.security import create_access_token, password_hash, verify_password
from app.services.audit import audit


router = APIRouter(prefix="/auth", tags=["auth"])


def _allowlist_enabled() -> bool:
    return (os.getenv("MULTI_TENANT_ALLOWLIST_ENABLED", "false") or "false").strip().lower() in {"1", "true", "yes"}


def _is_allowed_email(email: str) -> bool:
    raw = (os.getenv("MULTI_TENANT_ALLOWLIST", "") or "").strip()
    if not raw:
        return False
    allowed = {x.strip().lower() for x in raw.split(",") if x.strip()}
    return email.lower() in allowed


@router.post("/signup")
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    if _allowlist_enabled() and not _is_allowed_email(payload.email):
        raise HTTPException(status_code=403, detail="Signup is limited to allowlisted users")
    existing = db.query(User).filter(User.email == payload.email.lower()).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already exists")
    user = User(email=payload.email.lower(), password_hash=password_hash(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    db.add(UserPreference(user_id=user.id))
    db.commit()
    audit(db, "auth.signup", user_id=user.id)
    token = create_access_token(user.id, user.email)
    resp = JSONResponse({"ok": True, "user_id": user.id, "email": user.email})
    resp.set_cookie("access_token", token, httponly=True, secure=True, samesite="lax")
    return resp


@router.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email.lower()).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token(user.id, user.email)
    audit(db, "auth.login", user_id=user.id)
    resp = JSONResponse({"ok": True, "user_id": user.id, "email": user.email})
    resp.set_cookie("access_token", token, httponly=True, secure=True, samesite="lax")
    return resp


@router.post("/logout")
def logout(db: Session = Depends(get_db)):
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("access_token")
    audit(db, "auth.logout")
    return resp

