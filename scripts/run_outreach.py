#!/usr/bin/env python3
"""Sync approvals from Sheet and send initial outreach emails."""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import click
from dotenv import load_dotenv
from rich.console import Console

load_dotenv()
console = Console()


@click.command()
@click.option("--campaign", required=True)
@click.option("--campaigns-dir", default="campaigns")
@click.option("--db-path", default=None)
@click.option("--dry-run", is_flag=True, help="Compose emails but do not send; prints previews")
@click.option("--limit", default=None, type=int)
@click.option("--prospect-id", default=None, type=int, help="Send only to this specific prospect ID")
def main(campaign, campaigns_dir, db_path, dry_run, limit, prospect_id):
    """Send initial outreach emails to approved prospects."""
    from src.config import load_campaign
    from src.tracking.database import get_db, initialize_db, get_spreadsheet_id
    from src.tracking.sheets import get_sheets_client
    from src.outreach.sender import get_gmail_service
    from src.workflow.orchestrator import run_outreach_phase
    import anthropic

    config = load_campaign(campaign, campaigns_dir)
    db_path = db_path or os.getenv("DB_PATH", "data/outreach.db")
    initialize_db(db_path)
    conn = get_db(db_path)

    sheets_client = None
    spreadsheet_id = get_spreadsheet_id(conn, config.id)
    sa_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_PATH", "auth/service_account.json")
    gmail_token = os.getenv("GMAIL_TOKEN_PATH", "auth/gmail_token.json")

    if spreadsheet_id:
        try:
            sheets_client = get_sheets_client(sa_path, gmail_token)
        except Exception:
            pass

    gmail_service = None
    if not dry_run:
        gmail_service = get_gmail_service(gmail_token)
    else:
        # For dry run, create a mock service object
        class _MockGmailService:
            pass
        gmail_service = _MockGmailService()

    anthropic_client = anthropic.Anthropic()

    run_outreach_phase(
        config=config,
        db_conn=conn,
        sheets_client=sheets_client,
        spreadsheet_id=spreadsheet_id,
        gmail_service=gmail_service,
        dry_run=dry_run,
        limit=limit,
        prospect_id_filter=prospect_id,
        anthropic_client=anthropic_client,
    )
    conn.close()


if __name__ == "__main__":
    main()
