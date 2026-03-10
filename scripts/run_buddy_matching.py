#!/usr/bin/env python3
"""
Pavilion AI Buddy Matching System.

Workflow:
  1. propose  — reads Requests sheet, finds pairs, writes to Matches sheet for Josh to review
  2. send     — reads Approved rows from Matches sheet, sends intro emails, marks people as Matched
  3. setup    — creates the Google Sheet with correct tabs and headers

Usage:
  python scripts/run_buddy_matching.py propose
  python scripts/run_buddy_matching.py send
  python scripts/run_buddy_matching.py setup
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import click
import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from datetime import datetime

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_root, ".env"), override=True)
console = Console()


def _load_config(config_path: str) -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


def _get_sheets_client():
    from src.tracking.sheets import get_sheets_client
    sa_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_PATH", "auth/service_account.json")
    token_path = os.getenv("GMAIL_TOKEN_PATH", "auth/gmail_token.json")
    creds_path = os.getenv("GMAIL_CREDENTIALS_PATH", "auth/client_secrets.json")
    return get_sheets_client(sa_path, token_path, creds_path)


def _open_or_create_spreadsheet(gc, name: str):
    """Open existing spreadsheet by name or create a new one."""
    try:
        sh = gc.open(name)
        console.print(f"[green]Opened existing spreadsheet:[/] {name}")
        return sh
    except Exception:
        sh = gc.create(name)
        console.print(f"[green]Created new spreadsheet:[/] {name}")
        console.print(f"  URL: https://docs.google.com/spreadsheets/d/{sh.id}")
        return sh


def _ensure_tab(sh, tab_name: str, headers: list[str]):
    """Ensure a worksheet tab exists with the right headers."""
    try:
        ws = sh.worksheet(tab_name)
        console.print(f"  Tab '{tab_name}' already exists")
        return ws
    except Exception:
        ws = sh.add_worksheet(title=tab_name, rows=500, cols=len(headers))
        ws.append_row(headers, value_input_option="USER_ENTERED")
        console.print(f"  Created tab '{tab_name}'")
        return ws


# ── SETUP ─────────────────────────────────────────────────────────────────────

@click.group()
def cli():
    pass


@cli.command()
@click.option("--config", default="campaigns/ai_buddy_program.yaml")
def setup(config):
    """Create the Google Sheet with correct tabs and headers."""
    cfg = _load_config(config)
    tracking = cfg["tracking"]

    gc = _get_sheets_client()
    sh = _open_or_create_spreadsheet(gc, tracking["spreadsheet_name"])

    requests_headers = [
        "Timestamp", "Name", "Email", "Function", "Chapter / Location",
        "AI Experience Level", "Pavilion Member?",
        "Anything specific you want help with?",
        "Status", "Match ID", "Date Matched",
    ]
    matches_headers = [
        "Match ID", "Person A Name", "Person A Email", "Person A Function",
        "Person B Name", "Person B Email", "Person B Function",
        "Match Basis", "Match Score", "Approval", "Intro Sent", "Date Sent", "Notes",
    ]

    _ensure_tab(sh, tracking["requests_tab"], requests_headers)
    _ensure_tab(sh, tracking["matches_tab"], matches_headers)

    # Remove default Sheet1 if it exists and is empty
    try:
        default = sh.worksheet("Sheet1")
        sh.del_worksheet(default)
    except Exception:
        pass

    console.print(f"\n[bold green]Setup complete.[/]")
    console.print(f"Spreadsheet: https://docs.google.com/spreadsheets/d/{sh.id}")
    console.print("\nNext: share the HubSpot form URL with members and point it at the Requests tab.")


# ── PROPOSE ───────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--config", default="campaigns/ai_buddy_program.yaml")
@click.option("--dry-run", is_flag=True, help="Show proposed matches without writing to sheet")
def propose(config, dry_run):
    """Find new matches and write them to the Matches tab for review."""
    from src.buddy.matcher import parse_requests, run_matching

    cfg = _load_config(config)
    tracking = cfg["tracking"]
    matching_cfg = cfg["matching"]

    gc = _get_sheets_client()
    sh = gc.open(tracking["spreadsheet_name"])

    requests_ws = sh.worksheet(tracking["requests_tab"])
    matches_ws = sh.worksheet(tracking["matches_tab"])

    # Load requests
    all_rows = requests_ws.get_all_records()
    requests = parse_requests(all_rows)

    console.print(f"\n[bold]AI Buddy Matching[/]")
    console.print(f"  Unmatched requests: {len(requests)}")

    if len(requests) < 2:
        console.print("[yellow]  Not enough unmatched requests to form pairs.[/]")
        return

    # Run matching
    matches = run_matching(
        requests=requests,
        prefer_mix=matching_cfg.get("prefer_member_nonmember_mix", True),
        max_level_gap=matching_cfg.get("max_level_gap", 1),
    )

    console.print(f"  Proposed matches: {len(matches)}")
    unmatched_count = len(requests) - (len(matches) * 2)
    if unmatched_count > 0:
        console.print(f"  [yellow]Could not match: {unmatched_count} person(s) — will try again next run[/]")

    if not matches:
        console.print("[yellow]No matches found.[/]")
        return

    # Display proposed matches
    table = Table(title="Proposed Matches", show_lines=True)
    table.add_column("Match ID", style="cyan", width=10)
    table.add_column("Person A", width=20)
    table.add_column("Person B", width=20)
    table.add_column("Basis", width=40)
    table.add_column("Score", justify="right", width=7)

    for m in matches:
        table.add_row(
            m.match_id,
            f"{m.person_a.name}\n[dim]{m.person_a.function}[/]",
            f"{m.person_b.name}\n[dim]{m.person_b.function}[/]",
            m.match_basis,
            str(m.match_score),
        )
    console.print(table)

    if dry_run:
        console.print("[yellow][DRY RUN] — not writing to sheet.[/]")
        return

    # Write proposed matches to Matches tab
    existing_ids = set()
    for row in matches_ws.get_all_records():
        existing_ids.add(row.get("Match ID", ""))

    new_rows = []
    for m in matches:
        if m.match_id in existing_ids:
            continue
        new_rows.append([
            m.match_id,
            m.person_a.name, m.person_a.email, m.person_a.function,
            m.person_b.name, m.person_b.email, m.person_b.function,
            m.match_basis,
            m.match_score,
            "Pending Approval",  # ← Josh changes this to "Approved"
            "", "",              # Intro Sent, Date Sent (filled after sending)
            "",                  # Notes
        ])

    if new_rows:
        matches_ws.append_rows(new_rows, value_input_option="USER_ENTERED")
        console.print(f"\n[green]✓[/] {len(new_rows)} proposed matches written to '{tracking['matches_tab']}' tab.")
        console.print(f"  Open the sheet, review, and change [bold]Approval[/] column to [bold]Approved[/] for each match you want to send.")
        console.print(f"  Then run: [bold]python scripts/run_buddy_matching.py send[/]")
    else:
        console.print("[yellow]All proposed matches already exist in the sheet.[/]")


# ── SEND ──────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--config", default="campaigns/ai_buddy_program.yaml")
@click.option("--dry-run", is_flag=True, help="Compose but do not send emails")
def send(config, dry_run):
    """Send intro emails for all Approved matches."""
    from src.buddy.matcher import parse_requests, BuddyRequest
    from src.buddy.intro_composer import compose_intro, make_subject
    from src.outreach.sender import get_gmail_service, send_email
    import anthropic

    cfg = _load_config(config)
    tracking = cfg["tracking"]
    intro_cfg = cfg["intro"]

    gc = _get_sheets_client()
    sh = gc.open(tracking["spreadsheet_name"])
    requests_ws = sh.worksheet(tracking["requests_tab"])
    matches_ws = sh.worksheet(tracking["matches_tab"])

    anthropic_client = anthropic.Anthropic()
    gmail_token = os.getenv("GMAIL_TOKEN_PATH", "auth/gmail_token.json")
    oauth_creds = os.getenv("GMAIL_CREDENTIALS_PATH", "auth/client_secrets.json")
    gmail_service = get_gmail_service(gmail_token, oauth_creds)

    match_rows = matches_ws.get_all_records()
    request_rows = requests_ws.get_all_records()

    # Build email lookup for updating request rows
    email_to_row_index = {
        row.get("Email", "").strip().lower(): i + 2
        for i, row in enumerate(request_rows)
    }

    approved = [
        (i + 2, row) for i, row in enumerate(match_rows)
        if row.get("Approval", "").strip().lower() == "approved"
        and not row.get("Intro Sent", "").strip()
    ]

    if not approved:
        console.print("[yellow]No approved matches pending intro emails.[/]")
        return

    console.print(f"\n[bold]Sending intro emails for {len(approved)} approved match(es)...[/]\n")

    # Parse requests into BuddyRequest objects for composer
    all_requests = parse_requests(request_rows)
    email_to_request = {r.email.lower(): r for r in all_requests}

    for sheet_row_idx, match_row in approved:
        email_a = match_row["Person A Email"].strip()
        email_b = match_row["Person B Email"].strip()
        match_id = match_row["Match ID"]

        req_a = email_to_request.get(email_a.lower())
        req_b = email_to_request.get(email_b.lower())

        if not req_a or not req_b:
            console.print(f"  [red]Match {match_id}:[/] Could not find request records — skipping")
            continue

        # Build a ProposedMatch object for the composer
        from src.buddy.matcher import ProposedMatch
        match = ProposedMatch(
            match_id=match_id,
            person_a=req_a,
            person_b=req_b,
            match_basis=match_row.get("Match Basis", ""),
            match_score=int(match_row.get("Match Score", 0)),
        )

        console.print(f"  [{match_id}] Composing intro: {req_a.name} ↔ {req_b.name}")

        try:
            body = compose_intro(match, intro_cfg["program_description"], anthropic_client)
            subject = make_subject(match)
        except Exception as e:
            console.print(f"    [red]Compose error:[/] {e}")
            continue

        if dry_run:
            console.print(f"    [yellow][DRY RUN][/] Subject: {subject}")
            console.print(f"    Preview: {body[:200]}...")
            continue

        try:
            # Send to both people simultaneously (cc both)
            send_email(
                service=gmail_service,
                from_address=intro_cfg["sender_email"],
                to_address=email_a,
                cc_address=email_b,
                subject=subject,
                body=body,
            )

            now = datetime.utcnow().strftime("%Y-%m-%d %H:%M")

            # Mark match row as sent
            col_intro_sent = 11   # Column K
            col_date_sent = 12    # Column L
            matches_ws.update_cell(sheet_row_idx, col_intro_sent, "Yes")
            matches_ws.update_cell(sheet_row_idx, col_date_sent, now)

            # Mark both people as Matched in Requests tab
            for email in (email_a, email_b):
                req_row = email_to_row_index.get(email.lower())
                if req_row:
                    requests_ws.update_cell(req_row, 9, "Matched")   # Column I = Status
                    requests_ws.update_cell(req_row, 10, match_id)   # Column J = Match ID
                    requests_ws.update_cell(req_row, 11, now)        # Column K = Date Matched

            console.print(f"    [green]✓[/] Intro sent to {req_a.name} and {req_b.name}")

        except Exception as e:
            console.print(f"    [red]Send error:[/] {e}")

    if not dry_run:
        console.print(f"\n[bold green]Done.[/]")


if __name__ == "__main__":
    cli()
