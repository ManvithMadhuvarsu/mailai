import os
import threading
import time
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from dotenv import load_dotenv

from google_auth_oauthlib.flow import Flow

from main import run
from tools.gmail_tool import (
    SCOPES,
    CREDENTIALS_PATH,
    TOKEN_PATH,
    save_token_pickle,
    _materialize_credentials_from_env,
)
from tools.s3_state import try_persist_file, try_restore_file


load_dotenv()
logger = logging.getLogger("railway_app")


def _public_base_url(request: Request) -> str:
    # Prefer explicit base URL (recommended on Railway)
    base = (os.getenv("PUBLIC_BASE_URL") or "").strip()
    if base:
        return base.rstrip("/")
    # Fallback to request host
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc))
    return f"{proto}://{host}".rstrip("/")


def _oauth_callback_url(request: Request) -> str:
    return f"{_public_base_url(request)}/oauth/callback"


def _build_flow(request: Request) -> Flow:
    # Railway-friendly: allow providing OAuth client JSON via env var
    # (GMAIL_CREDENTIALS_JSON) rather than requiring a pre-mounted file.
    _materialize_credentials_from_env()
    if not CREDENTIALS_PATH.exists():
        raise FileNotFoundError(
            "credentials.json not found at config/credentials.json. "
            "Provide it either by setting GMAIL_CREDENTIALS_JSON (recommended) "
            "or by mounting /app/config with credentials.json."
        )
    flow = Flow.from_client_secrets_file(
        str(CREDENTIALS_PATH),
        scopes=SCOPES,
        redirect_uri=_oauth_callback_url(request),
    )
    return flow


def _token_exists() -> bool:
    return TOKEN_PATH.exists()


def _start_daemon_loop_once():
    # Prevent multiple background threads
    if getattr(_start_daemon_loop_once, "_started", False):
        return
    _start_daemon_loop_once._started = True  # type: ignore[attr-defined]

    def _loop():
        interval_minutes = int(os.getenv("POLL_INTERVAL_MINUTES", "").strip() or 180)
        interval_seconds = interval_minutes * 60
        logger.info(f"Daemon loop started. interval_minutes={interval_minutes}")
        while True:
            try:
                if _token_exists():
                    run()
                else:
                    logger.warning("No token yet. Waiting for user OAuth at /login")
            except Exception:
                logger.exception("Error in daemon loop")
            time.sleep(interval_seconds)

    t = threading.Thread(target=_loop, name="mailai-daemon", daemon=True)
    t.start()


app = FastAPI()


@app.on_event("startup")
def _startup():
    # Ensure dirs exist for volume mounts
    Path("data").mkdir(exist_ok=True)
    Path("config").mkdir(exist_ok=True)
    # If persistent volumes aren't available, optionally restore token from S3-compatible bucket.
    try_restore_file(TOKEN_PATH)
    _start_daemon_loop_once()


@app.get("/", response_class=HTMLResponse)
def home():
    ok = _token_exists()
    status = "✅ Authorized" if ok else "⚠️ Not authorized"
    body = f"""
    <html>
      <head><title>MailAI</title></head>
      <body style="font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; padding: 24px;">
        <h2>MailAI (Railway)</h2>
        <p>Status: <b>{status}</b></p>
        <p>Polling: every <b>{os.getenv("POLL_INTERVAL_MINUTES","180")}</b> minutes</p>
        <p><a href="/login">Sign in with Google</a></p>
      </body>
    </html>
    """
    return body


@app.get("/health", response_class=PlainTextResponse)
def health():
    return "ok"


@app.get("/login")
def login(request: Request):
    flow = _build_flow(request)
    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="select_account consent",
    )
    # Store state + PKCE verifier in cookies for callback validation/token exchange.
    resp = RedirectResponse(url=authorization_url)
    resp.set_cookie("oauth_state", state, httponly=True, secure=True, samesite="lax")
    if getattr(flow, "code_verifier", None):
        resp.set_cookie("oauth_code_verifier", flow.code_verifier, httponly=True, secure=True, samesite="lax")
    return resp


@app.get("/oauth/callback")
def oauth_callback(request: Request, code: str | None = None, state: str | None = None):
    if not code:
        return PlainTextResponse("Missing code", status_code=400)

    cookie_state = request.cookies.get("oauth_state")
    if state and cookie_state and state != cookie_state:
        return PlainTextResponse("Invalid OAuth state", status_code=400)
    code_verifier = request.cookies.get("oauth_code_verifier")
    if not code_verifier:
        return PlainTextResponse("Missing OAuth code verifier cookie. Restart login.", status_code=400)

    flow = _build_flow(request)
    # Exchange code for tokens
    flow.fetch_token(code=code, code_verifier=code_verifier)
    creds = flow.credentials
    save_token_pickle(creds)
    # Persist token so redeploys don't require re-auth (S3-compatible bucket).
    try_persist_file(TOKEN_PATH)
    resp = RedirectResponse(url="/")
    resp.delete_cookie("oauth_state")
    resp.delete_cookie("oauth_code_verifier")
    return resp

