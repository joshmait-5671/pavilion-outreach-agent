"""Approval gate — sync user's Yes/No edits from Google Sheets to the DB."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Optional

import gspread

from src.models import Prospect
from src.tracking import database as db
from src.tracking import sheets as sh


def sync_approvals_from_sheet(
    sheets_client: gspread.Client,
    db_conn: sqlite3.Connection,
    campaign_id: str,
    spreadsheet_id: str,
    tab_name: str,
) -> tuple[int, int]:
    """Read the Approved column from Google Sheets and update DB statuses.
    Returns (newly_approved_count, newly_rejected_count)."""
    rows = sh.read_approval_column(sheets_client, spreadsheet_id, tab_name)

    newly_approved = 0
    newly_rejected = 0

    # Get all prospects keyed by sheet_row_number
    all_prospects = db.get_prospects_by_campaign(db_conn, campaign_id)
    by_row: dict[int, Prospect] = {
        p.sheet_row_number: p
        for p in all_prospects
        if p.sheet_row_number is not None
    }

    for row_info in rows:
        row_num = row_info["row_number"]
        approved_val = row_info["approved_value"].strip().lower()
        current_status = row_info["current_status"]

        prospect = by_row.get(row_num)
        if not prospect:
            continue

        # Only act on rows that are still pending
        if prospect.status not in ("Pending Approval",):
            continue

        if approved_val == "yes":
            db.mark_approved(db_conn, prospect.id)
            # Update sheet Status cell
            try:
                sh.update_single_cell(
                    sheets_client, spreadsheet_id, tab_name, row_num, "Status", "Approved"
                )
                sh.apply_status_color(
                    sheets_client, spreadsheet_id, tab_name, row_num, "Approved"
                )
            except Exception:
                pass
            newly_approved += 1

        elif approved_val == "no":
            db.mark_rejected(db_conn, prospect.id)
            try:
                sh.update_single_cell(
                    sheets_client, spreadsheet_id, tab_name, row_num, "Status", "Rejected"
                )
                sh.apply_status_color(
                    sheets_client, spreadsheet_id, tab_name, row_num, "Rejected"
                )
            except Exception:
                pass
            newly_rejected += 1

    return newly_approved, newly_rejected


def get_pending_approval_prospects(
    db_conn: sqlite3.Connection, campaign_id: str
) -> list[Prospect]:
    """Return all prospects with status = 'Pending Approval'."""
    return db.get_prospects_by_status(db_conn, campaign_id, "Pending Approval")


def sync_approvals_from_slack(
    db_conn: sqlite3.Connection,
    campaign_id: str,
) -> tuple[int, int]:
    """Read 👍 / ✋ reactions on Slack approval DMs and update DB statuses.
    Also captures any thread-reply notes from Josh into prospect.slack_notes
    (used downstream by the email composer for personalization).

    Returns (newly_approved_count, newly_rejected_count). Best-effort —
    silently no-ops if SLACK_BOT_TOKEN / scopes aren't set.
    """
    try:
        from src.outreach.slack_approval import check_approval_status
    except Exception:
        return (0, 0)

    pending = get_pending_approval_prospects(db_conn, campaign_id)
    newly_approved = 0
    newly_rejected = 0

    for prospect in pending:
        if not prospect.slack_message_ts:
            continue
        result = check_approval_status(prospect.slack_message_ts)

        # Always capture notes if present (even if still pending)
        if result.get("notes"):
            db.update_prospect_field(
                db_conn, prospect.id, "slack_notes", result["notes"]
            )

        if result["status"] == "approved":
            mark_approved(db_conn, prospect.id)
            newly_approved += 1
        elif result["status"] == "killed":
            mark_rejected(db_conn, prospect.id)
            newly_rejected += 1

    return (newly_approved, newly_rejected)


def mark_approved(db_conn: sqlite3.Connection, prospect_id: int) -> None:
    """Set status='Approved', approval_status='Approved', approved_at=now."""
    db.update_prospect_fields(db_conn, prospect_id, {
        "status": "Approved",
        "approval_status": "Approved",
        "approved_at": datetime.utcnow().isoformat(),
    })


def mark_rejected(db_conn: sqlite3.Connection, prospect_id: int) -> None:
    """Set status='Rejected', approval_status='Rejected'."""
    db.update_prospect_fields(db_conn, prospect_id, {
        "status": "Rejected",
        "approval_status": "Rejected",
    })


# Monkey-patch db module to use local functions
db.mark_approved = mark_approved
db.mark_rejected = mark_rejected
