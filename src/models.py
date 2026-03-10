"""Core data models (dataclasses) shared across modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Prospect:
    """Full lifecycle state of a single outreach prospect."""

    # Identity
    campaign_id: str
    podcast_name: str
    podcast_url: str

    # Discovery metadata
    category: Optional[str] = None
    estimated_audience_size: Optional[str] = None
    description: Optional[str] = None
    host_name: Optional[str] = None
    raw_scrape_data: Optional[str] = None  # JSON blob

    # Qualification
    qualification_score: Optional[int] = None
    qualification_notes: Optional[str] = None
    qualified_at: Optional[datetime] = None

    # Contact finding
    booking_contact_name: Optional[str] = None
    booking_contact_email: Optional[str] = None
    contact_source: Optional[str] = None
    contact_confidence: Optional[int] = None
    contact_found_at: Optional[datetime] = None

    # Approval
    approval_status: str = "Pending Approval"
    approved_at: Optional[datetime] = None

    # Initial outreach
    initial_email_subject: Optional[str] = None
    initial_email_body: Optional[str] = None
    initial_email_sent_at: Optional[datetime] = None
    initial_email_message_id: Optional[str] = None
    initial_email_thread_id: Optional[str] = None

    # Follow-up
    follow_up_sent_at: Optional[datetime] = None
    follow_up_message_id: Optional[str] = None
    follow_up_count: int = 0

    # Response monitoring
    last_reply_received_at: Optional[datetime] = None
    last_reply_snippet: Optional[str] = None
    reply_classification: Optional[str] = None

    # Overall status (mirrors Google Sheet)
    status: str = "Pending Approval"

    # Metadata
    id: Optional[int] = None
    sheet_row_number: Optional[int] = None
    notes: Optional[str] = None
    date_added: datetime = field(default_factory=datetime.utcnow)
    date_contacted: Optional[datetime] = None
    date_last_response: Optional[datetime] = None
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class EmailLogEntry:
    """Record of a single sent email."""

    campaign_id: str
    email_type: str          # "initial" | "follow_up" | "notification"
    to_address: str
    subject: str
    body_preview: str        # First 500 chars
    prospect_id: Optional[int] = None
    gmail_message_id: Optional[str] = None
    gmail_thread_id: Optional[str] = None
    sent_at: datetime = field(default_factory=datetime.utcnow)
    status: str = "sent"     # "sent" | "failed" | "bounced"


@dataclass
class Reply:
    """An incoming reply detected via Gmail."""

    campaign_id: str
    gmail_message_id: str
    gmail_thread_id: str
    from_address: str
    subject: str
    body_snippet: str
    full_body: str
    received_at: datetime
    prospect_id: Optional[int] = None
    classification: Optional[str] = None      # "positive" | "negative" | "neutral"
    classification_confidence: Optional[float] = None
    classification_notes: Optional[str] = None
    processed_at: datetime = field(default_factory=datetime.utcnow)


# Valid status values for prospects
PROSPECT_STATUSES = [
    "Pending Approval",
    "Approved",
    "Rejected",
    "Email Sent",
    "Follow-up Sent",
    "Positive Response",
    "Negative Response",
    "Booked",
]
