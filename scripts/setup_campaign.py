#!/usr/bin/env python3
"""One-time setup for a campaign: init DB, create Google Sheet, run Gmail OAuth."""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

load_dotenv()
console = Console()


@click.command()
@click.option("--campaign", required=True, help="Campaign ID (YAML filename without .yaml)")
@click.option("--campaigns-dir", default="campaigns", help="Directory containing campaign YAML files")
@click.option("--db-path", default=None, help="SQLite DB path (default: DB_PATH env or data/outreach.db)")
@click.option("--skip-gmail", is_flag=True, help="Skip Gmail OAuth setup")
@click.option("--reset-sheet", is_flag=True, help="Delete existing Sheet tab and recreate")
def main(campaign, campaigns_dir, db_path, skip_gmail, reset_sheet):
    """Initialize a campaign: database, Google Sheets, Gmail OAuth."""
    console.print(Panel(f"[bold cyan]Setting up campaign:[/] {campaign}", expand=False))

    # Load config
    from src.config import load_campaign
    try:
        config = load_campaign(campaign, campaigns_dir)
        console.print(f"[green]✓[/] Loaded campaign config: {config.name}")
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/] {e}")
        sys.exit(1)
    except ValueError as e:
        console.print(f"[red]Config validation error:[/] {e}")
        sys.exit(1)

    # Initialize DB
    db_path = db_path or os.getenv("DB_PATH", "data/outreach.db")
    from src.tracking.database import initialize_db, get_db, upsert_campaign
    initialize_db(db_path)
    conn = get_db(db_path)
    config_path = f"{campaigns_dir}/{campaign}.yaml"
    upsert_campaign(conn, config.id, config.name, config_path)
    console.print(f"[green]✓[/] Database initialized: {db_path}")

    # Gmail OAuth
    if not skip_gmail:
        gmail_creds = os.getenv("GMAIL_CREDENTIALS_PATH", "auth/client_secrets.json")
        gmail_token = os.getenv("GMAIL_TOKEN_PATH", "auth/gmail_token.json")
        if os.path.exists(gmail_token):
            console.print(f"[green]✓[/] Gmail token already exists: {gmail_token}")
        elif os.path.exists(gmail_creds):
            console.print(f"\n[cyan]Starting Gmail OAuth flow...[/]")
            console.print(f"[dim]A browser window will open. Sign in as: {config.sender_gmail}[/]")
            from src.outreach.sender import run_gmail_oauth_flow
            try:
                run_gmail_oauth_flow(gmail_creds, gmail_token)
                console.print(f"[green]✓[/] Gmail OAuth complete")
            except Exception as e:
                console.print(f"[red]Gmail OAuth failed:[/] {e}")
                console.print("[yellow]Tip:[/] Download client_secrets.json from Google Cloud Console")
        else:
            console.print(f"[yellow]![/] Gmail credentials not found at {gmail_creds!r}")
            console.print("  Download from: Google Cloud Console → APIs & Services → Credentials")
            console.print(f"  Save to: {gmail_creds}")

    # Google Sheets setup
    sa_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_PATH", "auth/service_account.json")
    gmail_token = os.getenv("GMAIL_TOKEN_PATH", "auth/gmail_token.json")
    gmail_creds = os.getenv("GMAIL_CREDENTIALS_PATH", "auth/client_secrets.json")

    if not os.path.exists(sa_path) and not os.path.exists(gmail_token):
        console.print(f"[yellow]![/] No Google credentials found. Skipping Sheets setup.")
        console.print("  Options:")
        console.print(f"  1. Service account JSON → {sa_path}")
        console.print(f"  2. OAuth token (run without --skip-gmail)")
    else:
        try:
            from src.tracking.sheets import get_sheets_client, get_or_create_spreadsheet
            from src.tracking.database import save_spreadsheet_id, get_spreadsheet_id

            sheets_client = get_sheets_client(sa_path, gmail_token, gmail_creds)

            # Check for existing spreadsheet
            existing_id = get_spreadsheet_id(conn, config.id)
            if existing_id and not reset_sheet:
                console.print(f"[green]✓[/] Spreadsheet already exists: {existing_id}")
                console.print(f"  URL: https://docs.google.com/spreadsheets/d/{existing_id}")
            else:
                console.print(f"\n[cyan]Creating Google Spreadsheet...[/]")
                sid, ws = get_or_create_spreadsheet(
                    sheets_client,
                    config.spreadsheet_name,
                    config.sheet_tab_name,
                    config.owner_email,
                )
                save_spreadsheet_id(conn, config.id, sid)
                console.print(f"[green]✓[/] Spreadsheet created")
                console.print(f"  URL: https://docs.google.com/spreadsheets/d/{sid}")
        except Exception as e:
            console.print(f"[yellow]Sheets setup failed:[/] {e}")
            console.print("  Campaign will work without Sheets — tracking will be DB-only")

    conn.close()

    console.print(Panel(
        "[bold green]Setup complete![/]\n\n"
        "Next steps:\n"
        f"  1. python scripts/run_discovery.py --campaign {campaign}\n"
        f"  2. Open Google Sheet → type Yes/No in column J (Approved)\n"
        f"  3. python scripts/run_outreach.py --campaign {campaign} --dry-run\n"
        f"  4. python scripts/run_outreach.py --campaign {campaign}",
        expand=False
    ))


if __name__ == "__main__":
    main()
