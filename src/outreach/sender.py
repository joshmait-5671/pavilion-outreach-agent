"""Gmail API — send outreach emails and read replies."""

from __future__ import annotations

import base64
import os
import pickle
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    # Sheets + Drive so one OAuth token covers everything
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]


class GmailSendError(Exception):
    pass


def run_gmail_oauth_flow(
    credentials_path: str = "auth/client_secrets.json",
    token_path: str = "auth/gmail_token.json",
) -> None:
    """Run interactive OAuth2 flow for Gmail access. Saves token to token_path."""
    if not os.path.exists(credentials_path):
        raise FileNotFoundError(
            f"Gmail OAuth credentials not found at {credentials_path!r}.\n"
            "Download 'client_secrets.json' from Google Cloud Console:\n"
            "  APIs & Services → Credentials → OAuth 2.0 Client IDs → Download JSON\n"
            f"Then save it to {credentials_path!r}"
        )

    Path(token_path).parent.mkdir(parents=True, exist_ok=True)
    flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
    creds = flow.run_local_server(port=0)

    with open(token_path, "wb") as f:
        pickle.dump(creds, f)

    print(f"Gmail OAuth token saved to {token_path}")


def get_gmail_service(token_path: str = "auth/gmail_token.json"):
    """Build and return Gmail API service object."""
    creds = _load_credentials(token_path)
    return build("gmail", "v1", credentials=creds)


def _load_credentials(token_path: str) -> Credentials:
    if not os.path.exists(token_path):
        raise FileNotFoundError(
            f"Gmail token not found at {token_path!r}. Run setup_campaign.py first."
        )

    with open(token_path, "rb") as f:
        creds = pickle.load(f)

    if creds.valid:
        return creds

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_path, "wb") as f:
            pickle.dump(creds, f)
        return creds

    raise PermissionError(
        f"Gmail token at {token_path!r} is expired and cannot be refreshed. "
        "Run setup_campaign.py to re-authorize."
    )


def send_email(
    service,
    from_address: str,
    to_address: str,
    subject: str,
    body: str,
    reply_to_thread_id: Optional[str] = None,
    cc_address: Optional[str] = None,
) -> dict[str, str]:
    """Send an email via Gmail API. Returns dict with message_id and thread_id."""
    msg = MIMEMultipart("alternative")
    msg["From"] = from_address
    msg["To"] = to_address
    if cc_address:
        msg["Cc"] = cc_address
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    body_payload: dict = {"raw": raw}
    if reply_to_thread_id:
        body_payload["threadId"] = reply_to_thread_id

    try:
        result = service.users().messages().send(userId="me", body=body_payload).execute()
        return {
            "message_id": result["id"],
            "thread_id": result.get("threadId", result["id"]),
        }
    except HttpError as e:
        raise GmailSendError(f"Failed to send email to {to_address}: {e}") from e


def get_thread_messages(service, thread_id: str) -> list[dict]:
    """Fetch all messages in a Gmail thread. Returns list of message dicts."""
    try:
        thread = service.users().threads().get(userId="me", id=thread_id, format="full").execute()
        messages = thread.get("messages", [])
        return [_parse_message(m) for m in messages]
    except HttpError:
        return []


def list_unread_replies(
    service,
    since_timestamp: Optional[datetime] = None,
) -> list[dict]:
    """Fetch unread messages from Gmail inbox."""
    query = "in:inbox is:unread"
    if since_timestamp:
        epoch = int(since_timestamp.timestamp())
        query += f" after:{epoch}"

    try:
        response = service.users().messages().list(
            userId="me", q=query, maxResults=100
        ).execute()
        message_refs = response.get("messages", [])
    except HttpError:
        return []

    results = []
    for ref in message_refs:
        try:
            msg = service.users().messages().get(
                userId="me", id=ref["id"], format="full"
            ).execute()
            results.append(_parse_message(msg))
        except HttpError:
            continue

    return results


def mark_as_read(service, message_id: str) -> None:
    """Mark a Gmail message as read."""
    try:
        service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"removeLabelIds": ["UNREAD"]},
        ).execute()
    except HttpError:
        pass


def get_sender_email(service) -> str:
    """Return the authenticated user's email address."""
    profile = service.users().getProfile(userId="me").execute()
    return profile.get("emailAddress", "")


def _parse_message(msg: dict) -> dict:
    """Extract useful fields from a Gmail API message object."""
    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}

    body = _extract_body(msg.get("payload", {}))
    snippet = msg.get("snippet", "")

    internal_date = msg.get("internalDate")
    received_at = None
    if internal_date:
        received_at = datetime.utcfromtimestamp(int(internal_date) / 1000)

    return {
        "message_id": msg["id"],
        "thread_id": msg.get("threadId", msg["id"]),
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "subject": headers.get("subject", ""),
        "snippet": snippet,
        "full_body": body,
        "received_at": received_at,
        "label_ids": msg.get("labelIds", []),
    }


def _extract_body(payload: dict) -> str:
    """Recursively extract plain text body from Gmail message payload."""
    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data", "")

    if mime_type == "text/plain" and body_data:
        return base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        text = _extract_body(part)
        if text:
            return text

    return ""
