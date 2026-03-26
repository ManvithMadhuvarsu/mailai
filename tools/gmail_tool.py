"""
tools/gmail_tool.py
Handles all Gmail API interactions:
- OAuth authentication with automatic token refresh and re-auth
- Reading emails (plain text + HTML fallback)
- Creating/applying labels
- Saving drafts
"""

import os
import re
import base64
import pickle
import logging
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

# Gmail API scopes
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.labels",
]

TOKEN_PATH = Path("data/token.pickle")
CREDENTIALS_PATH = Path("config/credentials.json")


def get_gmail_service():
    """Authenticate and return Gmail API service.

    Handles token refresh automatically. If the refresh token has been
    revoked or expired (common for Google OAuth 'Testing' apps which
    expire tokens every 7 days), the stale token is deleted and a fresh
    OAuth flow is triggered.
    """
    creds = None

    if TOKEN_PATH.exists():
        with open(TOKEN_PATH, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                logger.info("Gmail token refreshed successfully.")
            except Exception as e:
                # Token was revoked or expired beyond refresh — start fresh
                logger.warning(f"Token refresh failed: {e}. Re-authenticating...")
                print(f"  ⚠️  Token refresh failed: {e}")
                print(f"  🔄  Deleting stale token and re-authenticating...")
                TOKEN_PATH.unlink(missing_ok=True)
                creds = None

        if not creds:
            if not CREDENTIALS_PATH.exists():
                raise FileNotFoundError(
                    "\n❌  credentials.json not found!\n"
                    "    1. Go to https://console.cloud.google.com\n"
                    "    2. Create a project → Enable Gmail API\n"
                    "    3. Create OAuth 2.0 credentials (Desktop app)\n"
                    "    4. Download and save as config/credentials.json\n"
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_PATH), SCOPES,
            )
            creds = flow.run_local_server(port=0)
            logger.info("New Gmail OAuth token obtained.")

        TOKEN_PATH.parent.mkdir(exist_ok=True)
        with open(TOKEN_PATH, "wb") as f:
            pickle.dump(creds, f)

    return build("gmail", "v1", credentials=creds)


def _html_to_text(html: str) -> str:
    """Strip HTML tags and decode common entities to plain text."""
    # Remove style and script blocks entirely
    html = re.sub(r"<(style|script)[^>]*>.*?</(style|script)>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Replace block-level tags with newlines for readability
    html = re.sub(r"<(br|p|div|tr|li)[^>]*>", "\n", html, flags=re.IGNORECASE)
    # Remove remaining tags
    html = re.sub(r"<[^>]+>", "", html)
    # Decode common HTML entities
    entities = {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&nbsp;": " ", "&quot;": '"', "&#39;": "'"}
    for entity, char in entities.items():
        html = html.replace(entity, char)
    # Collapse excessive whitespace
    html = re.sub(r"\n{3,}", "\n\n", html)
    html = re.sub(r"[ \t]+", " ", html)
    return html.strip()


def _decode_part(part: dict) -> str:
    """Safely decode a base64url-encoded email body part."""
    data = part.get("body", {}).get("data", "")
    if not data:
        return ""
    try:
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _extract_body(payload: dict) -> str:
    """
    Recursively extract the best available body from an email payload.
    Priority: text/plain > text/html > any text part.
    """
    mime = payload.get("mimeType", "")

    # Leaf node
    if "parts" not in payload:
        if mime == "text/plain":
            return _decode_part(payload)
        if mime == "text/html":
            return _html_to_text(_decode_part(payload))
        return ""

    plain, html = "", ""
    for part in payload["parts"]:
        sub_mime = part.get("mimeType", "")
        if sub_mime == "text/plain":
            plain = _decode_part(part)
        elif sub_mime == "text/html":
            html = _html_to_text(_decode_part(part))
        elif sub_mime.startswith("multipart/"):
            # Recurse into nested multipart containers
            nested = _extract_body(part)
            if nested:
                plain = plain or nested

    return plain or html


def fetch_recent_emails(service, days: int = 1) -> list:
    """Fetch emails from the last N days from the inbox."""
    since = (datetime.now() - timedelta(days=days)).strftime("%Y/%m/%d")
    query = f"after:{since} in:inbox"

    try:
        messages = []
        next_page_token = None

        while True:
            results = service.users().messages().list(
                userId="me",
                q=query,
                maxResults=100,
                pageToken=next_page_token,
            ).execute()

            batch = results.get("messages", [])
            messages.extend(batch)
            next_page_token = results.get("nextPageToken")

            # Safety cap to avoid infinite loops or memory issues in very large mailboxes
            if not next_page_token or len(messages) >= 500:
                break

        emails = []
        for msg in messages:
            try:
                detail = service.users().messages().get(
                    userId="me", id=msg["id"], format="full"
                ).execute()
                emails.append(_parse_email(detail))
            except HttpError as e:
                logger.warning(f"Failed to fetch email {msg['id']}: {e}")

        return emails

    except HttpError as e:
        logger.error(f"Gmail API error while listing messages: {e}")
        print(f"❌ Gmail API error: {e}")
        return []


def _parse_email(raw: dict) -> dict:
    """Parse raw Gmail message into a clean, normalized dict."""
    headers = {
        h["name"].lower(): h["value"]
        for h in raw["payload"].get("headers", [])
    }

    body = _extract_body(raw["payload"])

    # Truncate body to ~4000 chars to avoid LLM token overflow while keeping context
    body = body[:4000].strip()

    # Extract sender name and address separately
    sender_raw = headers.get("from", "")
    sender_name = re.sub(r"<.*?>", "", sender_raw).strip().strip('"')
    sender_email = re.search(r"<(.+?)>", sender_raw)
    sender_email = sender_email.group(1) if sender_email else sender_raw.strip()

    return {
        "id": raw["id"],
        "thread_id": raw["threadId"],
        "subject": headers.get("subject", "(no subject)").strip(),
        "sender": sender_raw,
        "sender_name": sender_name,
        "sender_email": sender_email,
        "reply_to": headers.get("reply-to", sender_raw),
        "date": headers.get("date", ""),
        "body": body,
        "label_ids": raw.get("labelIds", []),
        "snippet": raw.get("snippet", ""),
    }


def get_or_create_label(service, label_name: str) -> str | None:
    """Get label ID by name, creating it if it doesn't exist."""
    try:
        existing = service.users().labels().list(userId="me").execute()
        for label in existing.get("labels", []):
            if label["name"] == label_name:
                return label["id"]

        new_label = service.users().labels().create(
            userId="me",
            body={
                "name": label_name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            },
        ).execute()
        logger.info(f"Created Gmail label: {label_name}")
        print(f"  ✅ Created Gmail label: {label_name}")
        return new_label["id"]

    except HttpError as e:
        logger.error(f"Label error for '{label_name}': {e}")
        print(f"❌ Label error: {e}")
        return None


def apply_label(service, message_id: str, label_id: str) -> bool:
    """Apply a label to a Gmail message. Returns True on success."""
    try:
        service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"addLabelIds": [label_id]},
        ).execute()
        return True
    except HttpError as e:
        logger.warning(f"Failed to apply label to {message_id}: {e}")
        print(f"❌ Failed to apply label: {e}")
        return False


def save_draft(service, to: str, subject: str, body: str, thread_id: str = None) -> str | None:
    """Save an email as a Gmail draft (does NOT send automatically)."""
    try:
        msg = MIMEMultipart("alternative")
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        draft_body = {"message": {"raw": raw}}
        if thread_id:
            draft_body["message"]["threadId"] = thread_id

        draft = service.users().drafts().create(
            userId="me", body=draft_body
        ).execute()
        logger.info(f"Draft saved: subject='{subject}' to='{to}'")
        return draft["id"]

    except HttpError as e:
        logger.error(f"Failed to save draft to '{to}': {e}")
        print(f"❌ Failed to save draft: {e}")
        return None
