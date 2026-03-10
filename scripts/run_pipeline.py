#!/usr/bin/env python3
"""Run the full outreach pipeline (cron-friendly)."""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

load_dotenv()
console = Console()


@click.command()
@click.option("--campaign", required=True)
@click.option("--campaigns-dir", default="campaigns")
@click.option("--db-path", default=None)
@click.option("--skip-discovery", is_flag=True, help="Skip podcast discovery phase")
@click.option("--skip-contacts", is_flag=True, help="Skip contact finding phase")
@click.option("--skip-outreach", is_flag=True, help="Skip email sending phase")
@click.option("--skip-monitor", is_flag=True, help="Skip reply monitoring phase")
@click.option("--skip-followup", is_flag=True, help="Skip follow-up phase")
@click.option("--dry-run", is_flag=True, help="Run all phases in dry-run mode")
def main(campaign, campaigns_dir, db_path, skip_discovery, skip_contacts,
         skip_outreach, skip_monitor, skip_followup, dry_run):
    """Run the full outreach pipeline for a campaign."""
    from src.config import load_campaign
    from src.tracking.database import get_db, initialize_db, get_spreadsheet_id
    from src.tracking.sheets import get_sheets_client
    from src.outreach.sender import get_gmail_service
    from src.workflow.orchestrator import run_full_pipeline
    import anthropic

    if dry_run:
        console.print(Panel("[yellow]DRY RUN MODE — no emails will be sent[/]", expand=False))

    config = load_campaign(campaign, campaigns_dir)
    console.print(f"\n[bold]Campaign:[/] {config.name}")

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
        except Exception as e:
            console.print(f"[yellow]Sheets unavailable:[/] {e}")

    gmail_service = None
    if not dry_run and not skip_outreach and not skip_monitor and not skip_followup:
        try:
            gmail_service = get_gmail_service(gmail_token)
        except Exception as e:
            console.print(f"[red]Gmail unavailable:[/] {e}")
            if not skip_outreach:
                console.print("[red]Cannot run outreach without Gmail. Use --skip-outreach or run setup_campaign.py[/]")
                sys.exit(1)

    anthropic_client = anthropic.Anthropic()

    results = run_full_pipeline(
        config=config,
        db_conn=conn,
        sheets_client=sheets_client,
        spreadsheet_id=spreadsheet_id,
        gmail_service=gmail_service,
        skip_discovery=skip_discovery,
        skip_contacts=skip_contacts,
        skip_outreach=skip_outreach,
        skip_monitor=skip_monitor,
        skip_followup=skip_followup,
        dry_run=dry_run,
        anthropic_client=anthropic_client,
    )

    conn.close()

    # Summary table
    table = Table(title="Pipeline Summary")
    table.add_column("Phase", style="cyan")
    table.add_column("Result", style="green")
    for phase, count in results.items():
        table.add_row(phase.title(), str(count))

    console.print("\n")
    console.print(table)


if __name__ == "__main__":
    main()
