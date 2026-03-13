#!/usr/bin/env python3
"""Check Gmail for replies to outreach emails and update statuses."""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import click
from dotenv import load_dotenv

load_dotenv()


@click.command()
@click.option("--campaign", required=True)
@click.option("--campaigns-dir", default="campaigns")
@click.option("--db-path", default=None)
@click.option("--dry-run", is_flag=True)
def main(campaign, campaigns_dir, db_path, dry_run):
    """Check Gmail for replies and update prospect statuses."""
    from src.config import load_campaign
    from src.tracking.database import (
        get_db, initialize_db, get_spreadsheet_id, save_spreadsheet_id,
        upsert_campaign, get_prospect_count,
    )
    from src.tracking.sheets import get_sheets_client
    from src.outreach.sender import get_gmail_service
    from src.workflow.orchestrator import run_monitoring_phase
    import anthropic

    config = load_campaign(campaign, campaigns_dir)
    db_path = db_path or os.getenv("DB_PATH", "data/outreach.db")
    initialize_db(db_path)
    conn = get_db(db_path)

    # Ensure campaign record exists (ephemeral Railway deploys)
    upsert_campaign(conn, config.id, config.name, f"{campaigns_dir}/{campaign}.yaml")

    sheets_client = None
    spreadsheet_id = get_spreadsheet_id(conn, config.id)
    sa_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_PATH", "auth/service_account.json")
    gmail_token = os.getenv("GMAIL_TOKEN_PATH", "auth/gmail_token.json")

    if not spreadsheet_id:
        env_sid = os.getenv("SPREADSHEET_ID")
        if env_sid:
            save_spreadsheet_id(conn, config.id, env_sid)
            spreadsheet_id = env_sid

    if spreadsheet_id:
        try:
            sheets_client = get_sheets_client(sa_path, gmail_token)
        except Exception:
            pass

    # Bootstrap prospects from Sheet if DB is empty
    if sheets_client and spreadsheet_id:
        from src.tracking.sheets import bootstrap_prospects_from_sheet
        existing = get_prospect_count(conn, config.id)
        if existing == 0:
            bootstrap_prospects_from_sheet(
                sheets_client, spreadsheet_id, config.sheet_tab_name, conn, config.id
            )

    gmail_service = get_gmail_service(gmail_token)
    anthropic_client = anthropic.Anthropic()

    run_monitoring_phase(
        config=config,
        db_conn=conn,
        sheets_client=sheets_client,
        spreadsheet_id=spreadsheet_id,
        gmail_service=gmail_service,
        dry_run=dry_run,
        anthropic_client=anthropic_client,
    )
    conn.close()


if __name__ == "__main__":
    main()
