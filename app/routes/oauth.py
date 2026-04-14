import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from sqlalchemy.orm import Session

from app.deps import current_user
from app.db import get_db
from app.models import GmailAccount, User
from app.security import encrypt_secret
from app.services.audit import audit
from tools.gmail_tool import CREDENTIALS_PATH, SCOPES, _materialize_credentials_from_env


router = APIRouter(prefix="/oauth/google", tags=["oauth"])


def _callback_url(request: Request) -> str:
    base = (os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if not base:
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc))
        base = f"{proto}://{host}"
    return f"{base}/app/oauth/google/callback"


def _build_flow(request: Request) -> Flow:
    _materialize_credentials_from_env()
    if not CREDENTIALS_PATH.exists():
        raise HTTPException(status_code=500, detail="Missing Google OAuth credentials")
    return Flow.from_client_secrets_file(str(CREDENTIALS_PATH), scopes=SCOPES, redirect_uri=_callback_url(request))


@router.get("/start")
def start_oauth(
    request: Request,
    user: User = Depends(current_user),
):
    flow = _build_flow(request)
    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="select_account consent",
    )
    resp = RedirectResponse(authorization_url)
    resp.set_cookie("oauth_state_mt", state, httponly=True, secure=True, samesite="lax")
    if getattr(flow, "code_verifier", None):
        resp.set_cookie("oauth_verifier_mt", flow.code_verifier, httponly=True, secure=True, samesite="lax")
    resp.set_cookie("oauth_uid_mt", str(user.id), httponly=True, secure=True, samesite="lax")
    return resp


@router.get("/callback")
def oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    db: Session = Depends(get_db),
):
    if not code:
        raise HTTPException(status_code=400, detail="Missing code")
    cookie_state = request.cookies.get("oauth_state_mt")
    if state and cookie_state and state != cookie_state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    verifier = request.cookies.get("oauth_verifier_mt")
    uid_raw = request.cookies.get("oauth_uid_mt")
    if not verifier or not uid_raw:
        raise HTTPException(status_code=400, detail="Missing OAuth verifier/session")

    user = db.query(User).filter(User.id == int(uid_raw)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    flow = _build_flow(request)
    flow.fetch_token(code=code, code_verifier=verifier)
    creds = flow.credentials
    refresh_token = creds.refresh_token or ""
    if not refresh_token:
        raise HTTPException(status_code=400, detail="No refresh token returned")

    scopes = " ".join(creds.scopes or [])
    account = db.query(GmailAccount).filter(GmailAccount.user_id == user.id).first()
    encrypted = encrypt_secret(refresh_token)
    if account:
        account.encrypted_refresh_token = encrypted
        account.scopes = scopes
        account.status = "connected"
    else:
        account = GmailAccount(
            user_id=user.id,
            provider="google",
            encrypted_refresh_token=encrypted,
            scopes=scopes,
            gmail_email=user.email,
            status="connected",
        )
        db.add(account)
    db.commit()
    audit(db, "oauth.google.connected", user_id=user.id)

    resp = RedirectResponse("/app/dashboard")
    resp.delete_cookie("oauth_state_mt")
    resp.delete_cookie("oauth_verifier_mt")
    resp.delete_cookie("oauth_uid_mt")
    return resp


@router.post("/disconnect")
def disconnect_google(user: User = Depends(current_user), db: Session = Depends(get_db)):
    account = db.query(GmailAccount).filter(GmailAccount.user_id == user.id).first()
    if account:
        db.delete(account)
        db.commit()
    audit(db, "oauth.google.disconnected", user_id=user.id)
    return {"ok": True}

