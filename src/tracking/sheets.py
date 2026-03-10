"""Google Sheets integration — human-facing tracking dashboard."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Optional

import gspread
from google.oauth2.service_account import Credentials as SACredentials
from google.oauth2.credentials import Credentials as OAuthCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle

from src.models import Prospect

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

# Column layout — order matters, sheet_row_number lookups use this
COLUMNS = [
    "Podcast Name",       # A
    "URL",                # B
    "Category",           # C
    "Audience Size",      # D
    "Host",               # E
    "Contact Name",       # F
    "Contact Email",      # G
    "Contact Source",     # H
    "Score",              # I
    "Approved",           # J  ← user edits this
    "Status",             # K
    "Date Added",         # L
    "Date Contacted",     # M
    "Date Last Response", # N
    "Follow-ups",         # O
    "Notes",              # P
    "Email Subject",      # Q
    "Last Reply",         # R
]

COL_LETTER = {name: chr(ord("A") + i) for i, name in enumerate(COLUMNS)}
COL_INDEX = {name: i + 1 for i, name in enumerate(COLUMNS)}  # 1-based

# Status → background color (RGB 0-1 floats)
STATUS_COLORS: dict[str, dict] = {
    "Pending Approval": {"red": 1.0, "green": 0.98, "blue": 0.6},
    "Approved":         {"red": 0.68, "green": 0.85, "blue": 1.0},
    "Email Sent":       {"red": 0.68, "green": 0.85, "blue": 1.0},
    "Follow-up Sent":   {"red": 0.42, "green": 0.66, "blue": 0.96},
    "Positive Response":{"red": 0.7,  "green": 0.93, "blue": 0.7},
    "Booked":           {"red": 0.3,  "green": 0.85, "blue": 0.3},
    "Negative Response":{"red": 0.96, "green": 0.78, "blue": 0.78},
    "Rejected":         {"red": 0.96, "green": 0.78, "blue": 0.78},
}


def get_sheets_client(
    service_account_path: str = "auth/service_account.json",
    oauth_token_path: str = "auth/gmail_token.json",
    oauth_credentials_path: str = "auth/client_secrets.json",
) -> gspread.Client:
    """Return authenticated gspread client.
    Prefers user OAuth token (so sheets live in user's Drive);
    falls back to service account."""
    # Prefer OAuth so the spreadsheet is created in the user's own Drive
    if os.path.exists(oauth_token_path):
        try:
            creds = _load_or_refresh_oauth(oauth_token_path, oauth_credentials_path)
            return gspread.authorize(creds)
        except Exception:
            pass

    # Service account fallback
    if os.path.exists(service_account_path):
        creds = SACredentials.from_service_account_file(service_account_path, scopes=SCOPES)
        return gspread.authorize(creds)

    raise FileNotFoundError(
        "No Google credentials found. Run setup_campaign.py to authorize."
    )


def _load_or_refresh_oauth(token_path: str, credentials_path: str) -> OAuthCredentials:
    """Load existing OAuth token or run new flow."""
    creds = None
    if os.path.exists(token_path):
        with open(token_path, "rb") as f:
            creds = pickle.load(f)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_path, "wb") as f:
            pickle.dump(creds, f)
        return creds

    if not os.path.exists(credentials_path):
        raise FileNotFoundError(
            f"No service account at {service_account_path!r} and no OAuth credentials at {credentials_path!r}. "
            "Run setup_campaign.py first."
        )

    flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
    creds = flow.run_local_server(port=0)
    with open(token_path, "wb") as f:
        pickle.dump(creds, f)
    return creds


def setup_spreadsheet(
    client: gspread.Client,
    spreadsheet_name: str,
    sheet_tab_name: str,
    owner_email: str,
) -> str:
    """Create spreadsheet with headers, formatting. Share with owner. Returns spreadsheet_id."""
    spreadsheet = client.create(spreadsheet_name)
    worksheet = spreadsheet.sheet1
    worksheet.update_title(sheet_tab_name)

    # Write header row
    worksheet.update("A1", [COLUMNS])

    # Format header: bold, frozen
    spreadsheet.batch_update({
        "requests": [
            {
                "repeatCell": {
                    "range": {
                        "sheetId": worksheet.id,
                        "startRowIndex": 0,
                        "endRowIndex": 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "textFormat": {"bold": True},
                            "backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.9},
                        }
                    },
                    "fields": "userEnteredFormat(textFormat,backgroundColor)",
                }
            },
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": worksheet.id,
                        "gridProperties": {"frozenRowCount": 1},
                    },
                    "fields": "gridProperties.frozenRowCount",
                }
            },
            # Auto-resize columns
            {
                "autoResizeDimensions": {
                    "dimensions": {
                        "sheetId": worksheet.id,
                        "dimension": "COLUMNS",
                        "startIndex": 0,
                        "endIndex": len(COLUMNS),
                    }
                }
            },
        ]
    })

    # Share with owner
    try:
        spreadsheet.share(owner_email, perm_type="user", role="writer")
    except Exception:
        pass  # May fail if using service account without Drive API

    return spreadsheet.id


def get_or_create_spreadsheet(
    client: gspread.Client,
    spreadsheet_name: str,
    sheet_tab_name: str,
    owner_email: str,
) -> tuple[str, gspread.Worksheet]:
    """Return (spreadsheet_id, worksheet) — creates if not found by name."""
    try:
        spreadsheet = client.open(spreadsheet_name)
        try:
            ws = spreadsheet.worksheet(sheet_tab_name)
        except gspread.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(title=sheet_tab_name, rows=1000, cols=len(COLUMNS))
            ws.update("A1", [COLUMNS])
        return spreadsheet.id, ws
    except gspread.SpreadsheetNotFound:
        sid = setup_spreadsheet(client, spreadsheet_name, sheet_tab_name, owner_email)
        spreadsheet = client.open_by_key(sid)
        ws = spreadsheet.worksheet(sheet_tab_name)
        return sid, ws


def add_prospect_row(
    client: gspread.Client,
    spreadsheet_id: str,
    tab_name: str,
    prospect: Prospect,
) -> int:
    """Append a new row to the sheet. Returns the row number (1-indexed)."""
    ws = client.open_by_key(spreadsheet_id).worksheet(tab_name)
    row_data = _prospect_to_row(prospect)
    ws.append_row(row_data, value_input_option="USER_ENTERED")
    # Row number = current row count (including header)
    all_vals = ws.col_values(1)
    row_number = len(all_vals)
    return row_number


def update_prospect_row(
    client: gspread.Client,
    spreadsheet_id: str,
    tab_name: str,
    row_number: int,
    prospect: Prospect,
) -> None:
    """Update all fields in an existing row by row_number."""
    ws = client.open_by_key(spreadsheet_id).worksheet(tab_name)
    row_data = _prospect_to_row(prospect)
    ws.update(f"A{row_number}", [row_data])


def update_single_cell(
    client: gspread.Client,
    spreadsheet_id: str,
    tab_name: str,
    row_number: int,
    column_name: str,
    value: str,
) -> None:
    """Update a single cell by row_number and column name."""
    col_letter = COL_LETTER.get(column_name)
    if not col_letter:
        raise ValueError(f"Unknown column: {column_name}")
    ws = client.open_by_key(spreadsheet_id).worksheet(tab_name)
    ws.update(f"{col_letter}{row_number}", [[value]])


def read_approval_column(
    client: gspread.Client,
    spreadsheet_id: str,
    tab_name: str,
) -> list[dict]:
    """Read the Approved column (J) and podcast name (A). Returns list of dicts."""
    ws = client.open_by_key(spreadsheet_id).worksheet(tab_name)
    names = ws.col_values(COL_INDEX["Podcast Name"])
    approved = ws.col_values(COL_INDEX["Approved"])
    statuses = ws.col_values(COL_INDEX["Status"])

    results = []
    max_row = max(len(names), len(approved), len(statuses))
    for i in range(1, max_row):  # skip header (row 0 = row 1 in sheet)
        results.append({
            "row_number": i + 1,
            "podcast_name": names[i] if i < len(names) else "",
            "approved_value": (approved[i] if i < len(approved) else "").strip(),
            "current_status": (statuses[i] if i < len(statuses) else "").strip(),
        })
    return results


def read_all_rows(
    client: gspread.Client,
    spreadsheet_id: str,
    tab_name: str,
) -> list[dict]:
    """Read all data rows as list of dicts keyed by column header."""
    ws = client.open_by_key(spreadsheet_id).worksheet(tab_name)
    return ws.get_all_records()


def apply_status_color(
    client: gspread.Client,
    spreadsheet_id: str,
    tab_name: str,
    row_number: int,
    status: str,
) -> None:
    """Color the entire row based on status."""
    color = STATUS_COLORS.get(status)
    if not color:
        return

    spreadsheet = client.open_by_key(spreadsheet_id)
    ws = spreadsheet.worksheet(tab_name)
    spreadsheet.batch_update({
        "requests": [
            {
                "repeatCell": {
                    "range": {
                        "sheetId": ws.id,
                        "startRowIndex": row_number - 1,
                        "endRowIndex": row_number,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": color,
                        }
                    },
                    "fields": "userEnteredFormat.backgroundColor",
                }
            }
        ]
    })


# --- helpers ---

def _fmt_dt(dt: Optional[datetime]) -> str:
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%d")


def _prospect_to_row(p: Prospect) -> list[Any]:
    return [
        p.podcast_name or "",                          # A
        p.podcast_url or "",                           # B
        p.category or "",                              # C
        p.estimated_audience_size or "",               # D
        p.host_name or "",                             # E
        p.booking_contact_name or "",                  # F
        p.booking_contact_email or "",                 # G
        p.contact_source or "",                        # H
        p.qualification_score if p.qualification_score is not None else "", # I
        "",                                            # J - Approved (user fills)
        p.status or "Pending Approval",                # K
        _fmt_dt(p.date_added),                         # L
        _fmt_dt(p.date_contacted),                     # M
        _fmt_dt(p.date_last_response),                 # N
        p.follow_up_count or 0,                        # O
        p.notes or "",                                 # P
        p.initial_email_subject or "",                 # Q
        p.last_reply_snippet or "",                    # R
    ]
