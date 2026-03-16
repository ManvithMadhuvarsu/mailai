"""
tools/gmail_tool.py
Handles all Gmail API interactions:
- OAuth authentication
- Reading emails
- Creating/applying labels
- Saving drafts
"""

import os
import base64
import pickle
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

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
    """Authenticate and return Gmail API service."""
    creds = None

    if TOKEN_PATH.exists():
        with open(TOKEN_PATH, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_PATH.exists():
                raise FileNotFoundError(
                    "\n❌  credentials.json not found!\n"
                    "    1. Go to https://console.cloud.google.com\n"
                    "    2. Create a project → Enable Gmail API\n"
                    "    3. Create OAuth 2.0 credentials (Desktop app)\n"
                    "    4. Download and save as config/credentials.json\n"
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_PATH), SCOPES
            )
            creds = flow.run_local_server(port=0)

        TOKEN_PATH.parent.mkdir(exist_ok=True)
        with open(TOKEN_PATH, "wb") as f:
            pickle.dump(creds, f)

    return build("gmail", "v1", credentials=creds)


def fetch_recent_emails(service, days: int = 1) -> list[dict]:
    """Fetch emails from the last N days."""
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
                pageToken=next_page_token
            ).execute()
            
            messages.extend(results.get("messages", []))
            next_page_token = results.get("nextPageToken")
            
            # Safety cap to avoid infinite loops or memory issues in very large mailboxes
            if not next_page_token or len(messages) >= 2000:
                break

        emails = []
        for msg in messages:
            detail = service.users().messages().get(
                userId="me", id=msg["id"], format="full"
            ).execute()
            emails.append(_parse_email(detail))

        return emails

    except HttpError as e:
        print(f"❌ Gmail API error: {e}")
        return []


def _parse_email(raw: dict) -> dict:
    """Parse raw Gmail message into clean dict."""
    headers = {
        h["name"].lower(): h["value"]
        for h in raw["payload"].get("headers", [])
    }

    # Extract body
    body = ""
    payload = raw["payload"]

    if "parts" in payload:
        for part in payload["parts"]:
            if part["mimeType"] == "text/plain":
                data = part["body"].get("data", "")
                body = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                break
    else:
        data = payload["body"].get("data", "")
        if data:
            body = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")

    return {
        "id": raw["id"],
        "thread_id": raw["threadId"],
        "subject": headers.get("subject", "(no subject)"),
        "sender": headers.get("from", ""),
        "reply_to": headers.get("reply-to", headers.get("from", "")),
        "date": headers.get("date", ""),
        "body": body[:3000],  # Truncate to avoid token overflow
        "label_ids": raw.get("labelIds", []),
        "snippet": raw.get("snippet", ""),
    }


def get_or_create_label(service, label_name: str) -> str:
    """Get label ID, creating the label if it doesn't exist."""
    try:
        existing = service.users().labels().list(userId="me").execute()
        for label in existing.get("labels", []):
            if label["name"] == label_name:
                return label["id"]

        # Create label with colour
        new_label = service.users().labels().create(
            userId="me",
            body={
                "name": label_name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            },
        ).execute()
        print(f"  ✅ Created Gmail label: {label_name}")
        return new_label["id"]

    except HttpError as e:
        print(f"❌ Label error: {e}")
        return None


def apply_label(service, message_id: str, label_id: str):
    """Apply a label to a Gmail message."""
    try:
        service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"addLabelIds": [label_id]},
        ).execute()
    except HttpError as e:
        print(f"❌ Failed to apply label: {e}")


def save_draft(service, to: str, subject: str, body: str, thread_id: str = None) -> str:
    """Save an email as a Gmail draft (does NOT send automatically)."""
    try:
        msg = MIMEMultipart("alternative")
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        draft_body = {"message": {"raw": raw}}
        if thread_id:
            draft_body["message"]["threadId"] = thread_id

        draft = service.users().drafts().create(
            userId="me", body=draft_body
        ).execute()

        return draft["id"]

    except HttpError as e:
        print(f"❌ Failed to save draft: {e}")
        return None
