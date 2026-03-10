"""Pipeline coordinator — orchestrates all phases for a campaign."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime
from typing import Optional

import anthropic
import gspread
from rich.console import Console
from rich.table import Table

from src.config import CampaignConfig
from src.contacts.finder import find_contact_for_prospect
from src.discovery import qualifier as qual
from src.discovery import scraper, searcher
from src.models import EmailLogEntry, Prospect
from src.monitoring import replies as reply_monitor
from src.outreach import composer, sender
from src.tracking import database as db
from src.tracking import sheets as sh
from src.workflow import approval as appr
from src.workflow import followup as fu

console = Console()


# ─── Discovery Phase ──────────────────────────────────────────────────────────

def run_discovery_phase(
    config: CampaignConfig,
    db_conn: sqlite3.Connection,
    sheets_client: Optional[gspread.Client],
    spreadsheet_id: Optional[str],
    dry_run: bool = False,
    limit_queries: Optional[int] = None,
    min_score_override: Optional[int] = None,
    anthropic_client: Optional[anthropic.Anthropic] = None,
) -> int:
    """Find new podcasts, score them, add to DB and Sheet. Returns new prospect count."""
    if anthropic_client is None:
        anthropic_client = anthropic.Anthropic()

    run_id = db.log_run(db_conn, config.id, "discovery", json.dumps({"dry_run": dry_run}))
    min_score = min_score_override or config.min_qualification_score

    queries = config.discovery.get("search_queries", [])
    if limit_queries:
        queries = queries[:limit_queries]

    serpapi_key = os.getenv("SERPAPI_KEY")
    max_per_query = config.discovery.get("max_results_per_query", 20)

    console.print(f"\n[bold cyan]Discovery:[/] Running {len(queries)} search queries...")
    raw_results = searcher.search_for_podcasts(
        queries=queries,
        max_results_per_query=max_per_query,
        serpapi_key=serpapi_key,
    )
    console.print(f"  Found {len(raw_results)} unique URLs from search")

    # Get existing URLs to avoid re-processing
    existing_prospects = db.get_prospects_by_campaign(db_conn, config.id)
    existing_urls = {p.podcast_url for p in existing_prospects}

    new_count = 0
    for i, result in enumerate(raw_results):
        url = result.get("url", "")
        if not url or url in existing_urls:
            continue

        console.print(f"  [{i+1}/{len(raw_results)}] Scraping: {url[:60]}...")

        # Scrape
        page_data = scraper.scrape_podcast_page(url)
        page_data["podcast_url"] = url
        page_data["podcast_name"] = page_data.get("podcast_name") or result.get("title", url)

        # Score + classify category
        score, reasoning, category = qual.score_prospect(
            prospect_data=page_data,
            guest_profile=config.qualification.get("guest_profile", ""),
            scoring_criteria=config.qualification.get("scoring_criteria", {}),
            model=config.qualification_model,
            client=anthropic_client,
        )

        console.print(f"    Score: {score}/100 [{category}] — {reasoning[:80]}...")

        if score < min_score:
            console.print(f"    [dim]Below threshold ({min_score}), skipping[/]")
            continue

        prospect = Prospect(
            campaign_id=config.id,
            podcast_name=page_data["podcast_name"],
            podcast_url=url,
            category=category,  # Use Claude-assigned category, not raw scrape
            estimated_audience_size=page_data.get("estimated_audience_size"),
            description=page_data.get("description"),
            host_name=page_data.get("host_name"),
            raw_scrape_data=json.dumps(page_data),
            qualification_score=score,
            qualification_notes=reasoning,
            qualified_at=datetime.utcnow(),
            status="Pending Approval",
            approval_status="Pending Approval",
        )

        if dry_run:
            console.print(f"    [yellow][DRY RUN][/] Would add: {prospect.podcast_name}")
            new_count += 1
            continue

        # Save to DB
        prospect_id = db.upsert_prospect(db_conn, prospect)
        prospect.id = prospect_id
        existing_urls.add(url)

        # Add to Sheet
        if sheets_client and spreadsheet_id:
            try:
                row_num = sh.add_prospect_row(
                    sheets_client, spreadsheet_id, config.sheet_tab_name, prospect
                )
                db.update_prospect_field(db_conn, prospect_id, "sheet_row_number", row_num)
                sh.apply_status_color(
                    sheets_client, spreadsheet_id, config.sheet_tab_name,
                    row_num, "Pending Approval"
                )
                console.print(f"    [green]Added to Sheet row {row_num}[/]")
            except Exception as e:
                console.print(f"    [yellow]Sheet update failed: {e}[/]")

        new_count += 1
        time.sleep(1)  # Gentle rate limit between scrapes

    db.complete_run(db_conn, run_id, "success", len(raw_results), new_count)
    console.print(f"\n[bold green]Discovery complete:[/] {new_count} new prospects added")
    return new_count


# ─── Contact Phase ─────────────────────────────────────────────────────────────

def run_contact_phase(
    config: CampaignConfig,
    db_conn: sqlite3.Connection,
    sheets_client: Optional[gspread.Client],
    spreadsheet_id: Optional[str],
    dry_run: bool = False,
    limit: Optional[int] = None,
) -> int:
    """Find booking contacts for prospects that don't have one yet."""
    run_id = db.log_run(db_conn, config.id, "contacts")
    hunter_key = os.getenv("HUNTER_API_KEY") if config.use_hunter else None

    prospects = db.get_prospects_needing_contacts(db_conn, config.id)
    if limit:
        prospects = prospects[:limit]

    console.print(f"\n[bold cyan]Contacts:[/] Finding contacts for {len(prospects)} prospects...")
    found_count = 0

    for prospect in prospects:
        console.print(f"  Searching contact for: {prospect.podcast_name[:50]}...")
        contact = find_contact_for_prospect(
            prospect=prospect,
            hunter_api_key=hunter_key,
            hunter_confidence_min=config.hunter_confidence_min,
            use_hunter=config.use_hunter,
            fallback_to_web=config.contacts.get("fallback_to_web_search", True),
        )

        if not contact:
            console.print(f"    [dim]No contact found[/]")
            continue

        email = contact.get("email", "")
        name = contact.get("name", "")
        source = contact.get("source", "unknown")
        console.print(f"    Found: {email} ({source})")

        if dry_run:
            console.print(f"    [yellow][DRY RUN][/] Would update contact")
            found_count += 1
            continue

        db.update_prospect_fields(db_conn, prospect.id, {
            "booking_contact_email": email,
            "booking_contact_name": name,
            "contact_source": source,
            "contact_confidence": contact.get("confidence"),
            "contact_found_at": datetime.utcnow().isoformat(),
        })

        if sheets_client and spreadsheet_id and prospect.sheet_row_number:
            try:
                sh.update_single_cell(sheets_client, spreadsheet_id, config.sheet_tab_name,
                                       prospect.sheet_row_number, "Contact Name", name)
                sh.update_single_cell(sheets_client, spreadsheet_id, config.sheet_tab_name,
                                       prospect.sheet_row_number, "Contact Email", email)
                sh.update_single_cell(sheets_client, spreadsheet_id, config.sheet_tab_name,
                                       prospect.sheet_row_number, "Contact Source", source)
            except Exception:
                pass

        found_count += 1
        time.sleep(1)

    db.complete_run(db_conn, run_id, "success", len(prospects), found_count)
    console.print(f"\n[bold green]Contacts complete:[/] {found_count}/{len(prospects)} contacts found")
    return found_count


# ─── Outreach Phase ────────────────────────────────────────────────────────────

def run_outreach_phase(
    config: CampaignConfig,
    db_conn: sqlite3.Connection,
    sheets_client: Optional[gspread.Client],
    spreadsheet_id: Optional[str],
    gmail_service,
    dry_run: bool = False,
    limit: Optional[int] = None,
    prospect_id_filter: Optional[int] = None,
    anthropic_client: Optional[anthropic.Anthropic] = None,
) -> int:
    """Sync approvals, then send initial emails to approved prospects."""
    if anthropic_client is None:
        anthropic_client = anthropic.Anthropic()

    run_id = db.log_run(db_conn, config.id, "outreach")

    # 1. Sync approvals from Sheet
    if sheets_client and spreadsheet_id and config.approval_mode == "sheet":
        approved, rejected = appr.sync_approvals_from_sheet(
            sheets_client, db_conn, config.id, spreadsheet_id, config.sheet_tab_name
        )
        if approved or rejected:
            console.print(f"  Approval sync: +{approved} approved, +{rejected} rejected")

    # 2. Get prospects due for outreach
    prospects = db.get_approved_prospects_due_for_outreach(db_conn, config.id)

    if prospect_id_filter is not None:
        prospects = [p for p in prospects if p.id == prospect_id_filter]

    if not prospects:
        console.print("\n[dim]No prospects ready for outreach[/]")
        db.complete_run(db_conn, run_id, "success", 0, 0)
        return 0

    # 3. Check rate limit
    emails_today = db.get_emails_sent_today(db_conn, config.id)
    remaining_today = config.emails_per_day - emails_today
    if limit:
        remaining_today = min(remaining_today, limit)

    console.print(f"\n[bold cyan]Outreach:[/] {len(prospects)} prospects ready, {remaining_today} email slots today")

    sent_count = 0
    for prospect in prospects:
        if sent_count >= remaining_today:
            console.print(f"  [yellow]Daily limit reached ({config.emails_per_day})[/]")
            break

        if not prospect.booking_contact_email:
            console.print(f"  [dim]Skipping {prospect.podcast_name} — no contact email[/]")
            continue

        console.print(f"  Sending to: {prospect.podcast_name} → {prospect.booking_contact_email}")

        # Compose — pick template by prospect category
        try:
            template_name = config.get_template_for_category(prospect.category)
            console.print(f"    Template: {template_name} (category: {prospect.category or 'unknown'})")
            subject, body = composer.compose_email(
                prospect=prospect,
                template_name=template_name,
                config=config,
                client=anthropic_client,
                extra_vars={"sam_video_url": config.outreach.get("sam_video_url", "")},
            )
        except Exception as e:
            console.print(f"    [red]Compose error:[/] {e}")
            continue

        if dry_run:
            console.print(f"    [yellow][DRY RUN][/] Subject: {subject}")
            console.print(f"    [yellow]Body preview:[/] {body[:200]}...")
            sent_count += 1
            continue

        # Send
        try:
            result = sender.send_email(
                service=gmail_service,
                from_address=config.sender_gmail,
                to_address=prospect.booking_contact_email,
                subject=subject,
                body=body,
            )
        except sender.GmailSendError as e:
            console.print(f"    [red]Send failed:[/] {e}")
            continue

        now = datetime.utcnow()

        # Update DB
        db.update_prospect_fields(db_conn, prospect.id, {
            "initial_email_subject": subject,
            "initial_email_body": body,
            "initial_email_sent_at": now.isoformat(),
            "initial_email_message_id": result["message_id"],
            "initial_email_thread_id": result["thread_id"],
            "status": "Email Sent",
            "date_contacted": now.isoformat(),
        })

        db.log_email_sent(db_conn, EmailLogEntry(
            prospect_id=prospect.id,
            campaign_id=prospect.campaign_id,
            email_type="initial",
            to_address=prospect.booking_contact_email,
            subject=subject,
            body_preview=body[:500],
            gmail_message_id=result["message_id"],
            gmail_thread_id=result["thread_id"],
            sent_at=now,
        ))

        # Update Sheet
        if sheets_client and spreadsheet_id and prospect.sheet_row_number:
            try:
                sh.update_single_cell(sheets_client, spreadsheet_id, config.sheet_tab_name,
                                       prospect.sheet_row_number, "Status", "Email Sent")
                sh.update_single_cell(sheets_client, spreadsheet_id, config.sheet_tab_name,
                                       prospect.sheet_row_number, "Date Contacted", now.strftime("%Y-%m-%d"))
                sh.update_single_cell(sheets_client, spreadsheet_id, config.sheet_tab_name,
                                       prospect.sheet_row_number, "Email Subject", subject)
                sh.apply_status_color(sheets_client, spreadsheet_id, config.sheet_tab_name,
                                       prospect.sheet_row_number, "Email Sent")
            except Exception:
                pass

        console.print(f"    [green]Sent![/] Thread: {result['thread_id']}")
        sent_count += 1

        # Rate limit gap
        if sent_count < remaining_today:
            time.sleep(config.min_gap_seconds)

    db.complete_run(db_conn, run_id, "success", len(prospects), sent_count)
    console.print(f"\n[bold green]Outreach complete:[/] {sent_count} emails sent")
    return sent_count


# ─── Monitoring Phase ──────────────────────────────────────────────────────────

def run_monitoring_phase(
    config: CampaignConfig,
    db_conn: sqlite3.Connection,
    sheets_client: Optional[gspread.Client],
    spreadsheet_id: Optional[str],
    gmail_service,
    dry_run: bool = False,
    anthropic_client: Optional[anthropic.Anthropic] = None,
) -> int:
    """Check Gmail for replies, classify, update statuses."""
    if anthropic_client is None:
        anthropic_client = anthropic.Anthropic()

    run_id = db.log_run(db_conn, config.id, "monitor")

    prospects = db.get_prospects_with_threads(db_conn, config.id)
    if not prospects:
        console.print("\n[dim]No threads to monitor yet[/]")
        db.complete_run(db_conn, run_id, "success", 0, 0)
        return 0

    known_ids = db.get_known_reply_message_ids(db_conn, config.id)
    sender_email = config.sender_gmail

    console.print(f"\n[bold cyan]Monitor:[/] Checking {len(prospects)} threads for replies...")

    new_replies = reply_monitor.check_for_replies(
        service=gmail_service,
        campaign_prospects=prospects,
        known_message_ids=known_ids,
        classification_model=config.classification_model,
        sender_email=sender_email,
        client=anthropic_client,
    )

    processed = 0
    for reply in new_replies:
        cls = reply.classification or "neutral"
        console.print(f"  Reply from {reply.from_address[:40]}: [{cls}] {reply.body_snippet[:60]}...")

        if dry_run:
            console.print(f"    [yellow][DRY RUN][/] Would update to '{_status_from_classification(cls)}'")
            processed += 1
            continue

        # Save reply
        db.log_reply(db_conn, reply)

        # Update prospect status
        new_status = _status_from_classification(cls)
        if reply.prospect_id:
            db.update_prospect_fields(db_conn, reply.prospect_id, {
                "status": new_status,
                "last_reply_received_at": reply.received_at.isoformat() if reply.received_at else None,
                "last_reply_snippet": reply.body_snippet[:300],
                "reply_classification": cls,
                "date_last_response": (reply.received_at or datetime.utcnow()).isoformat(),
            })

            # Update Sheet
            prospect = db.get_prospect_by_id(db_conn, reply.prospect_id)
            if prospect and sheets_client and spreadsheet_id and prospect.sheet_row_number:
                try:
                    sh.update_single_cell(sheets_client, spreadsheet_id, config.sheet_tab_name,
                                           prospect.sheet_row_number, "Status", new_status)
                    sh.update_single_cell(sheets_client, spreadsheet_id, config.sheet_tab_name,
                                           prospect.sheet_row_number, "Last Reply", reply.body_snippet[:100])
                    sh.update_single_cell(sheets_client, spreadsheet_id, config.sheet_tab_name,
                                           prospect.sheet_row_number, "Date Last Response",
                                           (reply.received_at or datetime.utcnow()).strftime("%Y-%m-%d"))
                    sh.apply_status_color(sheets_client, spreadsheet_id, config.sheet_tab_name,
                                           prospect.sheet_row_number, new_status)
                except Exception:
                    pass

            # Notify on positive
            if cls == "positive" and config.notify_on_positive and not dry_run:
                _send_positive_notification(
                    gmail_service, config, prospect, reply.body_snippet
                )

        processed += 1

    db.complete_run(db_conn, run_id, "success", len(prospects), processed)
    console.print(f"\n[bold green]Monitor complete:[/] {processed} new replies processed")
    return processed


# ─── Follow-up Phase ───────────────────────────────────────────────────────────

def run_followup_phase(
    config: CampaignConfig,
    db_conn: sqlite3.Connection,
    sheets_client: Optional[gspread.Client],
    spreadsheet_id: Optional[str],
    gmail_service,
    dry_run: bool = False,
    limit: Optional[int] = None,
    anthropic_client: Optional[anthropic.Anthropic] = None,
) -> int:
    """Send follow-up emails to prospects past the wait threshold."""
    if not config.follow_up.get("enabled", True):
        return 0

    run_id = db.log_run(db_conn, config.id, "followup")

    candidates = fu.get_followup_candidates(
        db_conn, config.id, config.follow_up_wait_days, config.max_follow_ups
    )
    if limit:
        candidates = candidates[:limit]

    console.print(f"\n[bold cyan]Follow-up:[/] {len(candidates)} prospects due for follow-up")

    sent_count = 0
    for prospect in candidates:
        console.print(f"  Follow-up to: {prospect.podcast_name}")
        if dry_run:
            console.print(f"    [yellow][DRY RUN][/] Would send follow-up")
            sent_count += 1
            continue

        success = fu.send_followup_email(
            prospect=prospect,
            gmail_service=gmail_service,
            config=config,
            db_conn=db_conn,
            sheets_client=sheets_client,
            spreadsheet_id=spreadsheet_id,
            tab_name=config.sheet_tab_name,
            anthropic_client=anthropic_client,
        )
        if success:
            sent_count += 1
            time.sleep(config.min_gap_seconds)

    db.complete_run(db_conn, run_id, "success", len(candidates), sent_count)
    console.print(f"\n[bold green]Follow-up complete:[/] {sent_count} follow-ups sent")
    return sent_count


# ─── Full Pipeline ─────────────────────────────────────────────────────────────

def run_full_pipeline(
    config: CampaignConfig,
    db_conn: sqlite3.Connection,
    sheets_client: Optional[gspread.Client],
    spreadsheet_id: Optional[str],
    gmail_service,
    skip_discovery: bool = False,
    skip_contacts: bool = False,
    skip_outreach: bool = False,
    skip_monitor: bool = False,
    skip_followup: bool = False,
    dry_run: bool = False,
    anthropic_client: Optional[anthropic.Anthropic] = None,
) -> dict:
    """Run all pipeline phases in sequence."""
    results = {}

    if not skip_discovery:
        results["discovery"] = run_discovery_phase(
            config, db_conn, sheets_client, spreadsheet_id, dry_run=dry_run,
            anthropic_client=anthropic_client
        )

    if not skip_contacts:
        results["contacts"] = run_contact_phase(
            config, db_conn, sheets_client, spreadsheet_id, dry_run=dry_run
        )

    if not skip_outreach:
        results["outreach"] = run_outreach_phase(
            config, db_conn, sheets_client, spreadsheet_id, gmail_service,
            dry_run=dry_run, anthropic_client=anthropic_client
        )

    if not skip_monitor:
        results["monitor"] = run_monitoring_phase(
            config, db_conn, sheets_client, spreadsheet_id, gmail_service,
            dry_run=dry_run, anthropic_client=anthropic_client
        )

    if not skip_followup:
        results["followup"] = run_followup_phase(
            config, db_conn, sheets_client, spreadsheet_id, gmail_service,
            dry_run=dry_run, anthropic_client=anthropic_client
        )

    return results


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _status_from_classification(classification: str) -> str:
    return {
        "positive": "Positive Response",
        "negative": "Negative Response",
        "neutral": "Email Sent",  # Keep as Email Sent for neutral (OOO, etc.)
    }.get(classification, "Email Sent")


def _send_positive_notification(gmail_service, config: CampaignConfig, prospect: Prospect, snippet: str) -> None:
    """Send notification email to owner when a positive response is received."""
    subject = f"[Outreach] Positive response: {prospect.podcast_name}"
    body = f"""You got a positive response!

Podcast: {prospect.podcast_name}
Contact: {prospect.booking_contact_email}

Their reply:
{snippet}

Open your Google Sheet to see full details and follow up:
Campaign: {config.name}
"""
    try:
        sender.send_email(
            service=gmail_service,
            from_address=config.sender_gmail,
            to_address=config.notify_email,
            subject=subject,
            body=body,
        )
    except Exception:
        pass
