"""SQLite state store — source of truth for all campaign data."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from src.models import EmailLogEntry, Prospect, Reply

_ALLOWED_UPDATE_FIELDS = {
    "status", "approval_status", "approved_at",
    "booking_contact_name", "booking_contact_email", "contact_source",
    "contact_confidence", "contact_found_at",
    "qualification_score", "qualification_notes", "qualified_at",
    "initial_email_subject", "initial_email_body", "initial_email_sent_at",
    "initial_email_message_id", "initial_email_thread_id",
    "follow_up_sent_at", "follow_up_message_id", "follow_up_count",
    "last_reply_received_at", "last_reply_snippet", "reply_classification",
    "sheet_row_number", "notes", "date_contacted", "date_last_response",
    "updated_at",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS campaigns (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    config_path TEXT NOT NULL,
    spreadsheet_id TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS prospects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL REFERENCES campaigns(id),
    podcast_name TEXT NOT NULL,
    podcast_url TEXT NOT NULL,
    category TEXT,
    estimated_audience_size TEXT,
    description TEXT,
    host_name TEXT,
    raw_scrape_data TEXT,
    qualification_score INTEGER,
    qualification_notes TEXT,
    qualified_at TEXT,
    booking_contact_name TEXT,
    booking_contact_email TEXT,
    contact_source TEXT,
    contact_confidence INTEGER,
    contact_found_at TEXT,
    approval_status TEXT DEFAULT 'Pending Approval',
    approved_at TEXT,
    initial_email_subject TEXT,
    initial_email_body TEXT,
    initial_email_sent_at TEXT,
    initial_email_message_id TEXT,
    initial_email_thread_id TEXT,
    follow_up_sent_at TEXT,
    follow_up_message_id TEXT,
    follow_up_count INTEGER DEFAULT 0,
    last_reply_received_at TEXT,
    last_reply_snippet TEXT,
    reply_classification TEXT,
    status TEXT NOT NULL DEFAULT 'Pending Approval',
    sheet_row_number INTEGER,
    notes TEXT,
    date_added TEXT DEFAULT (datetime('now')),
    date_contacted TEXT,
    date_last_response TEXT,
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(campaign_id, podcast_url)
);

CREATE TABLE IF NOT EXISTS email_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prospect_id INTEGER REFERENCES prospects(id),
    campaign_id TEXT NOT NULL,
    email_type TEXT NOT NULL,
    to_address TEXT NOT NULL,
    subject TEXT NOT NULL,
    body_preview TEXT,
    gmail_message_id TEXT,
    gmail_thread_id TEXT,
    sent_at TEXT DEFAULT (datetime('now')),
    status TEXT DEFAULT 'sent'
);

CREATE TABLE IF NOT EXISTS replies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prospect_id INTEGER REFERENCES prospects(id),
    campaign_id TEXT NOT NULL,
    gmail_message_id TEXT UNIQUE,
    gmail_thread_id TEXT,
    from_address TEXT,
    subject TEXT,
    body_snippet TEXT,
    full_body TEXT,
    classification TEXT,
    classification_confidence REAL,
    classification_notes TEXT,
    received_at TEXT,
    processed_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS run_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL,
    run_type TEXT NOT NULL,
    started_at TEXT DEFAULT (datetime('now')),
    completed_at TEXT,
    status TEXT,
    records_processed INTEGER DEFAULT 0,
    records_updated INTEGER DEFAULT 0,
    error_message TEXT,
    config_snapshot TEXT
);

CREATE INDEX IF NOT EXISTS idx_prospects_campaign_status ON prospects(campaign_id, status);
CREATE INDEX IF NOT EXISTS idx_prospects_campaign_url ON prospects(campaign_id, podcast_url);
CREATE INDEX IF NOT EXISTS idx_email_log_prospect ON email_log(prospect_id);
CREATE INDEX IF NOT EXISTS idx_replies_thread ON replies(gmail_thread_id);
CREATE INDEX IF NOT EXISTS idx_run_log_campaign ON run_log(campaign_id, run_type);
"""


def get_db(db_path: str = "data/outreach.db") -> sqlite3.Connection:
    """Return SQLite connection with WAL mode and row_factory."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def initialize_db(db_path: str = "data/outreach.db") -> None:
    """Create all tables if they don't exist. Safe to call repeatedly."""
    conn = get_db(db_path)
    conn.executescript(_SCHEMA)
    conn.commit()
    conn.close()


def upsert_campaign(conn: sqlite3.Connection, campaign_id: str, name: str, config_path: str) -> None:
    """Insert or update a campaign row."""
    conn.execute(
        """
        INSERT INTO campaigns (id, name, config_path, updated_at)
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name,
            config_path=excluded.config_path,
            updated_at=datetime('now')
        """,
        (campaign_id, name, config_path),
    )
    conn.commit()


def save_spreadsheet_id(conn: sqlite3.Connection, campaign_id: str, spreadsheet_id: str) -> None:
    """Save the Google Sheets spreadsheet ID for a campaign."""
    conn.execute(
        "UPDATE campaigns SET spreadsheet_id=?, updated_at=datetime('now') WHERE id=?",
        (spreadsheet_id, campaign_id),
    )
    conn.commit()


def get_spreadsheet_id(conn: sqlite3.Connection, campaign_id: str) -> Optional[str]:
    """Retrieve the stored Google Sheets spreadsheet ID."""
    row = conn.execute(
        "SELECT spreadsheet_id FROM campaigns WHERE id=?", (campaign_id,)
    ).fetchone()
    return row["spreadsheet_id"] if row else None


def upsert_prospect(conn: sqlite3.Connection, prospect: Prospect) -> int:
    """Insert prospect if URL not already in campaign; update if exists. Returns id."""
    existing = conn.execute(
        "SELECT id FROM prospects WHERE campaign_id=? AND podcast_url=?",
        (prospect.campaign_id, prospect.podcast_url),
    ).fetchone()

    now = _dt()
    if existing:
        prospect_id = existing["id"]
        # Only update discovery fields if not yet qualified
        conn.execute(
            """
            UPDATE prospects SET
                podcast_name=?, category=?, estimated_audience_size=?,
                description=?, host_name=?, raw_scrape_data=?, updated_at=?
            WHERE id=?
            """,
            (
                prospect.podcast_name, prospect.category, prospect.estimated_audience_size,
                prospect.description, prospect.host_name, prospect.raw_scrape_data,
                now, prospect_id,
            ),
        )
    else:
        cur = conn.execute(
            """
            INSERT INTO prospects (
                campaign_id, podcast_name, podcast_url, category,
                estimated_audience_size, description, host_name, raw_scrape_data,
                qualification_score, qualification_notes,
                approval_status, status, date_added, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                prospect.campaign_id, prospect.podcast_name, prospect.podcast_url,
                prospect.category, prospect.estimated_audience_size,
                prospect.description, prospect.host_name, prospect.raw_scrape_data,
                prospect.qualification_score, prospect.qualification_notes,
                prospect.approval_status, prospect.status, now, now,
            ),
        )
        prospect_id = cur.lastrowid

    conn.commit()
    return prospect_id


def get_prospect_by_id(conn: sqlite3.Connection, prospect_id: int) -> Optional[Prospect]:
    """Fetch single prospect by ID."""
    row = conn.execute("SELECT * FROM prospects WHERE id=?", (prospect_id,)).fetchone()
    return _row_to_prospect(row) if row else None


def get_prospects_by_status(conn: sqlite3.Connection, campaign_id: str, status: str) -> list[Prospect]:
    """Fetch all prospects for a campaign matching a given status."""
    rows = conn.execute(
        "SELECT * FROM prospects WHERE campaign_id=? AND status=? ORDER BY qualification_score DESC",
        (campaign_id, status),
    ).fetchall()
    return [_row_to_prospect(r) for r in rows]


def get_prospects_by_campaign(conn: sqlite3.Connection, campaign_id: str) -> list[Prospect]:
    """Fetch all prospects for a campaign."""
    rows = conn.execute(
        "SELECT * FROM prospects WHERE campaign_id=? ORDER BY date_added DESC",
        (campaign_id,),
    ).fetchall()
    return [_row_to_prospect(r) for r in rows]


def update_prospect_status(conn: sqlite3.Connection, prospect_id: int, status: str) -> None:
    """Update status and updated_at."""
    conn.execute(
        "UPDATE prospects SET status=?, updated_at=? WHERE id=?",
        (status, _dt(), prospect_id),
    )
    conn.commit()


def update_prospect_field(conn: sqlite3.Connection, prospect_id: int, field: str, value: Any) -> None:
    """Update a single field on a prospect. Enforces allowlist."""
    if field not in _ALLOWED_UPDATE_FIELDS:
        raise ValueError(f"Field '{field}' is not in the allowed update list")
    conn.execute(
        f"UPDATE prospects SET {field}=?, updated_at=? WHERE id=?",
        (value, _dt(), prospect_id),
    )
    conn.commit()


def update_prospect_fields(conn: sqlite3.Connection, prospect_id: int, updates: dict[str, Any]) -> None:
    """Update multiple fields at once."""
    for f in updates:
        if f not in _ALLOWED_UPDATE_FIELDS:
            raise ValueError(f"Field '{f}' is not in the allowed update list")
    if not updates:
        return
    sets = ", ".join(f"{k}=?" for k in updates)
    vals = list(updates.values()) + [_dt(), prospect_id]
    conn.execute(f"UPDATE prospects SET {sets}, updated_at=? WHERE id=?", vals)
    conn.commit()


def get_approved_prospects_due_for_outreach(conn: sqlite3.Connection, campaign_id: str) -> list[Prospect]:
    """Return Approved prospects with no initial email sent yet."""
    rows = conn.execute(
        """
        SELECT * FROM prospects
        WHERE campaign_id=?
          AND approval_status='Approved'
          AND status='Approved'
          AND initial_email_sent_at IS NULL
        ORDER BY qualification_score DESC
        """,
        (campaign_id,),
    ).fetchall()
    return [_row_to_prospect(r) for r in rows]


def get_prospects_due_for_followup(
    conn: sqlite3.Connection, campaign_id: str, wait_days: int, max_follow_ups: int
) -> list[Prospect]:
    """Return prospects where initial email was sent > wait_days ago and follow-up not yet sent."""
    rows = conn.execute(
        f"""
        SELECT * FROM prospects
        WHERE campaign_id=?
          AND status='Email Sent'
          AND follow_up_count < ?
          AND initial_email_sent_at IS NOT NULL
          AND datetime(initial_email_sent_at, '+{wait_days} days') <= datetime('now')
          AND follow_up_sent_at IS NULL
        ORDER BY initial_email_sent_at ASC
        """,
        (campaign_id, max_follow_ups),
    ).fetchall()
    return [_row_to_prospect(r) for r in rows]


def get_prospects_with_threads(conn: sqlite3.Connection, campaign_id: str) -> list[Prospect]:
    """Return prospects that have a Gmail thread ID (for reply monitoring)."""
    rows = conn.execute(
        """
        SELECT * FROM prospects
        WHERE campaign_id=?
          AND initial_email_thread_id IS NOT NULL
          AND status NOT IN ('Booked', 'Rejected')
        """,
        (campaign_id,),
    ).fetchall()
    return [_row_to_prospect(r) for r in rows]


def get_emails_sent_today(conn: sqlite3.Connection, campaign_id: str) -> int:
    """Count emails sent today for rate limiting."""
    row = conn.execute(
        """
        SELECT COUNT(*) as cnt FROM email_log
        WHERE campaign_id=? AND email_type IN ('initial', 'follow_up')
          AND date(sent_at) = date('now')
        """,
        (campaign_id,),
    ).fetchone()
    return row["cnt"] if row else 0


def log_email_sent(conn: sqlite3.Connection, entry: EmailLogEntry) -> None:
    """Append to email_log table."""
    conn.execute(
        """
        INSERT INTO email_log (
            prospect_id, campaign_id, email_type, to_address, subject,
            body_preview, gmail_message_id, gmail_thread_id, sent_at, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entry.prospect_id, entry.campaign_id, entry.email_type,
            entry.to_address, entry.subject, entry.body_preview[:500],
            entry.gmail_message_id, entry.gmail_thread_id,
            entry.sent_at.isoformat() if entry.sent_at else _dt(), entry.status,
        ),
    )
    conn.commit()


def log_reply(conn: sqlite3.Connection, reply: Reply) -> None:
    """Insert into replies table. Ignores duplicates by gmail_message_id."""
    try:
        conn.execute(
            """
            INSERT INTO replies (
                prospect_id, campaign_id, gmail_message_id, gmail_thread_id,
                from_address, subject, body_snippet, full_body,
                classification, classification_confidence, classification_notes,
                received_at, processed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reply.prospect_id, reply.campaign_id, reply.gmail_message_id,
                reply.gmail_thread_id, reply.from_address, reply.subject,
                reply.body_snippet, reply.full_body,
                reply.classification, reply.classification_confidence,
                reply.classification_notes,
                reply.received_at.isoformat() if reply.received_at else _dt(),
                reply.processed_at.isoformat() if reply.processed_at else _dt(),
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass  # Already processed


def get_known_reply_message_ids(conn: sqlite3.Connection, campaign_id: str) -> set[str]:
    """Return set of all gmail_message_ids already in replies table for this campaign."""
    rows = conn.execute(
        "SELECT gmail_message_id FROM replies WHERE campaign_id=?", (campaign_id,)
    ).fetchall()
    return {r["gmail_message_id"] for r in rows}


def log_run(conn: sqlite3.Connection, campaign_id: str, run_type: str, config_snapshot: str = "") -> int:
    """Insert a run_log row, return run_id."""
    cur = conn.execute(
        "INSERT INTO run_log (campaign_id, run_type, config_snapshot) VALUES (?, ?, ?)",
        (campaign_id, run_type, config_snapshot),
    )
    conn.commit()
    return cur.lastrowid


def complete_run(
    conn: sqlite3.Connection,
    run_id: int,
    status: str,
    processed: int,
    updated: int,
    error: str = "",
) -> None:
    """Update run_log row with completion info."""
    conn.execute(
        """
        UPDATE run_log SET
            completed_at=datetime('now'), status=?,
            records_processed=?, records_updated=?, error_message=?
        WHERE id=?
        """,
        (status, processed, updated, error or None, run_id),
    )
    conn.commit()


def get_prospects_needing_contacts(conn: sqlite3.Connection, campaign_id: str) -> list[Prospect]:
    """Return prospects that have no booking contact email yet."""
    rows = conn.execute(
        """
        SELECT * FROM prospects
        WHERE campaign_id=?
          AND booking_contact_email IS NULL
          AND status NOT IN ('Rejected')
        ORDER BY qualification_score DESC NULLS LAST
        """,
        (campaign_id,),
    ).fetchall()
    return [_row_to_prospect(r) for r in rows]


# --- helpers ---

def _dt() -> str:
    return datetime.utcnow().isoformat()


def _row_to_prospect(row: sqlite3.Row) -> Prospect:
    d = dict(row)

    def _parse_dt(val):
        if val is None:
            return None
        try:
            return datetime.fromisoformat(val)
        except (ValueError, TypeError):
            return None

    return Prospect(
        id=d.get("id"),
        campaign_id=d["campaign_id"],
        podcast_name=d["podcast_name"],
        podcast_url=d["podcast_url"],
        category=d.get("category"),
        estimated_audience_size=d.get("estimated_audience_size"),
        description=d.get("description"),
        host_name=d.get("host_name"),
        raw_scrape_data=d.get("raw_scrape_data"),
        qualification_score=d.get("qualification_score"),
        qualification_notes=d.get("qualification_notes"),
        qualified_at=_parse_dt(d.get("qualified_at")),
        booking_contact_name=d.get("booking_contact_name"),
        booking_contact_email=d.get("booking_contact_email"),
        contact_source=d.get("contact_source"),
        contact_confidence=d.get("contact_confidence"),
        contact_found_at=_parse_dt(d.get("contact_found_at")),
        approval_status=d.get("approval_status", "Pending Approval"),
        approved_at=_parse_dt(d.get("approved_at")),
        initial_email_subject=d.get("initial_email_subject"),
        initial_email_body=d.get("initial_email_body"),
        initial_email_sent_at=_parse_dt(d.get("initial_email_sent_at")),
        initial_email_message_id=d.get("initial_email_message_id"),
        initial_email_thread_id=d.get("initial_email_thread_id"),
        follow_up_sent_at=_parse_dt(d.get("follow_up_sent_at")),
        follow_up_message_id=d.get("follow_up_message_id"),
        follow_up_count=d.get("follow_up_count", 0),
        last_reply_received_at=_parse_dt(d.get("last_reply_received_at")),
        last_reply_snippet=d.get("last_reply_snippet"),
        reply_classification=d.get("reply_classification"),
        status=d.get("status", "Pending Approval"),
        sheet_row_number=d.get("sheet_row_number"),
        notes=d.get("notes"),
        date_added=_parse_dt(d.get("date_added")) or datetime.utcnow(),
        date_contacted=_parse_dt(d.get("date_contacted")),
        date_last_response=_parse_dt(d.get("date_last_response")),
        updated_at=_parse_dt(d.get("updated_at")) or datetime.utcnow(),
    )
