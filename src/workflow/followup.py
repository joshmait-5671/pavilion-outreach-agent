"""Follow-up email scheduling and sending."""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime
from typing import Optional

import gspread

from src.config import CampaignConfig
from src.models import EmailLogEntry, Prospect
from src.outreach import composer, sender
from src.tracking import database as db
from src.tracking import sheets as sh


def get_followup_candidates(
    db_conn: sqlite3.Connection,
    campaign_id: str,
    wait_days: int,
    max_follow_ups: int,
    skip_statuses: Optional[list[str]] = None,
) -> list[Prospect]:
    """Return prospects that are past the follow-up wait threshold."""
    skip = skip_statuses or ["Positive Response", "Booked", "Negative Response", "Rejected"]
    candidates = db.get_prospects_due_for_followup(db_conn, campaign_id, wait_days, max_follow_ups)
    return [p for p in candidates if p.status not in skip]


def send_followup_email(
    prospect: Prospect,
    gmail_service,
    config: CampaignConfig,
    db_conn: sqlite3.Connection,
    sheets_client: Optional[gspread.Client],
    spreadsheet_id: Optional[str],
    tab_name: Optional[str],
    anthropic_client=None,
) -> bool:
    """Compose and send follow-up email as a reply in the original thread."""
    # Compose
    try:
        subject, body = composer.compose_email(
            prospect=prospect,
            template_name=config.follow_up_template,
            config=config,
            client=anthropic_client,
        )
    except Exception as e:
        print(f"  [!] Failed to compose follow-up for {prospect.podcast_name}: {e}")
        return False

    to_addr = prospect.booking_contact_email
    if not to_addr:
        return False

    # Send as reply in original thread
    try:
        result = sender.send_email(
            service=gmail_service,
            from_address=config.sender_gmail,
            to_address=to_addr,
            subject=subject,
            body=body,
            reply_to_thread_id=prospect.initial_email_thread_id,
        )
    except sender.GmailSendError as e:
        print(f"  [!] Failed to send follow-up to {to_addr}: {e}")
        return False

    now = datetime.utcnow()

    # Update DB
    db.update_prospect_fields(db_conn, prospect.id, {
        "follow_up_sent_at": now.isoformat(),
        "follow_up_message_id": result["message_id"],
        "follow_up_count": (prospect.follow_up_count or 0) + 1,
        "status": "Follow-up Sent",
    })

    # Log email
    log_entry = EmailLogEntry(
        prospect_id=prospect.id,
        campaign_id=prospect.campaign_id,
        email_type="follow_up",
        to_address=to_addr,
        subject=subject,
        body_preview=body[:500],
        gmail_message_id=result["message_id"],
        gmail_thread_id=result["thread_id"],
        sent_at=now,
    )
    db.log_email_sent(db_conn, log_entry)

    # Update Sheet
    if sheets_client and spreadsheet_id and tab_name and prospect.sheet_row_number:
        try:
            sh.update_single_cell(
                sheets_client, spreadsheet_id, tab_name,
                prospect.sheet_row_number, "Status", "Follow-up Sent"
            )
            sh.update_single_cell(
                sheets_client, spreadsheet_id, tab_name,
                prospect.sheet_row_number, "Follow-ups",
                str((prospect.follow_up_count or 0) + 1)
            )
            sh.apply_status_color(
                sheets_client, spreadsheet_id, tab_name,
                prospect.sheet_row_number, "Follow-up Sent"
            )
        except Exception:
            pass

    return True
