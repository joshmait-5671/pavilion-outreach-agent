#!/usr/bin/env python3
"""Send a daily progress report email for a campaign."""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import click
from datetime import datetime, timedelta
from dotenv import load_dotenv
from rich.console import Console

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_root, ".env"))
console = Console()


def _get_stats(conn, campaign_id: str) -> dict:
    """Pull key metrics from the DB."""
    def q(sql, *args):
        return conn.execute(sql, args).fetchone()[0]

    today = datetime.utcnow().date().isoformat()
    yesterday = (datetime.utcnow().date() - timedelta(days=1)).isoformat()

    return {
        # Pipeline totals
        "total_discovered":     q("SELECT COUNT(*) FROM prospects WHERE campaign_id=?", campaign_id),
        "pending_approval":     q("SELECT COUNT(*) FROM prospects WHERE campaign_id=? AND status='Pending Approval'", campaign_id),
        "approved":             q("SELECT COUNT(*) FROM prospects WHERE campaign_id=? AND approval_status='Approved'", campaign_id),
        "rejected":             q("SELECT COUNT(*) FROM prospects WHERE campaign_id=? AND approval_status='Rejected'", campaign_id),

        # Outreach
        "emails_sent_total":    q("SELECT COUNT(*) FROM email_log WHERE campaign_id=? AND email_type='initial'", campaign_id),
        "emails_sent_today":    q("SELECT COUNT(*) FROM email_log WHERE campaign_id=? AND email_type='initial' AND date(sent_at)=?", campaign_id, today),
        "followups_sent_total": q("SELECT COUNT(*) FROM email_log WHERE campaign_id=? AND email_type='follow_up'", campaign_id),

        # Replies
        "total_replies":        q("SELECT COUNT(*) FROM replies WHERE campaign_id=?", campaign_id),
        "positive_replies":     q("SELECT COUNT(*) FROM replies WHERE campaign_id=? AND classification='Positive'", campaign_id),
        "negative_replies":     q("SELECT COUNT(*) FROM replies WHERE campaign_id=? AND classification='Negative'", campaign_id),
        "new_replies_today":    q("SELECT COUNT(*) FROM replies WHERE campaign_id=? AND date(received_at)=?", campaign_id, today),

        # Booked
        "booked":               q("SELECT COUNT(*) FROM prospects WHERE campaign_id=? AND status='Booked'", campaign_id),

        # New discoveries today
        "discovered_today":     q("SELECT COUNT(*) FROM prospects WHERE campaign_id=? AND date(date_added)=?", campaign_id, today),
    }


def _build_email_body(stats: dict, campaign_name: str, spreadsheet_url: str) -> tuple[str, str]:
    """Return (subject, plain-text body)."""
    date_str = datetime.utcnow().strftime("%B %-d, %Y")
    reply_rate = (
        round(stats["total_replies"] / stats["emails_sent_total"] * 100, 1)
        if stats["emails_sent_total"] > 0 else 0
    )

    subject = f"📊 Daily Report: Sam Jacobs Podcast Outreach — {date_str}"

    body = f"""Daily Outreach Report — {campaign_name}
{date_str}
{'=' * 52}

🎙 PIPELINE
  Podcasts discovered:   {stats['total_discovered']:>6}  (+{stats['discovered_today']} today)
  Pending your approval: {stats['pending_approval']:>6}
  Approved by you:       {stats['approved']:>6}
  Rejected:              {stats['rejected']:>6}

📧 OUTREACH
  Initial emails sent:   {stats['emails_sent_total']:>6}  ({stats['emails_sent_today']} sent today)
  Follow-ups sent:       {stats['followups_sent_total']:>6}

💬 REPLIES
  Total replies:         {stats['total_replies']:>6}  (reply rate: {reply_rate}%)
  Positive / interested: {stats['positive_replies']:>6}
  Negative / pass:       {stats['negative_replies']:>6}
  New today:             {stats['new_replies_today']:>6}

🎯 BOOKED
  Confirmed bookings:    {stats['booked']:>6}

{'=' * 52}

👉 ACTION NEEDED: {stats['pending_approval']} podcasts are waiting for your approval in the tracking sheet.
   Open the sheet, review, and type Yes or No in column J (Approved).

📋 Tracking Sheet: {spreadsheet_url}

--
Sent automatically by the Pavilion Podcast Outreach Agent
"""
    return subject, body


@click.command()
@click.option("--campaign", required=True, help="Campaign ID (e.g. sam_jacobs_podcasts)")
@click.option("--campaigns-dir", default="campaigns")
@click.option("--db-path", default=None)
@click.option("--to", default=None, help="Override recipient email (default: campaign notify_email)")
@click.option("--dry-run", is_flag=True, help="Print report but don't send")
def main(campaign, campaigns_dir, db_path, to, dry_run):
    """Compose and send a daily progress report via Gmail."""
    from src.config import load_campaign
    from src.tracking.database import get_db, initialize_db, get_spreadsheet_id
    from src.outreach.sender import get_gmail_service, send_email

    config = load_campaign(campaign, campaigns_dir)
    db_path = db_path or os.getenv("DB_PATH", "data/outreach.db")
    initialize_db(db_path)
    conn = get_db(db_path)

    stats = _get_stats(conn, config.id)
    conn.close()

    spreadsheet_id = ""
    try:
        conn2 = get_db(db_path)
        spreadsheet_id = get_spreadsheet_id(conn2, config.id) or ""
        conn2.close()
    except Exception:
        pass

    spreadsheet_url = (
        f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
        if spreadsheet_id else "(not yet created)"
    )

    subject, body = _build_email_body(stats, config.name, spreadsheet_url)
    recipient = to or config.tracking.get("notify_email", config.sender_gmail)

    if dry_run:
        console.print(f"\n[bold]Subject:[/] {subject}\n")
        console.print(body)
        return

    try:
        gmail_token = os.getenv("GMAIL_TOKEN_PATH", "auth/gmail_token.json")
        oauth_creds = os.getenv("GMAIL_CREDENTIALS_PATH", "auth/client_secrets.json")
        service = get_gmail_service(gmail_token, oauth_creds)
        result = send_email(
            service=service,
            from_address=config.sender_gmail,
            to_address=recipient,
            subject=subject,
            body=body,
        )
        console.print(f"[green]✓[/] Daily report sent to {recipient}")
    except Exception as e:
        console.print(f"[red]Failed to send report:[/] {e}")
        raise


if __name__ == "__main__":
    main()
