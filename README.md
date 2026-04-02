# Outreach Agent

A modular, campaign-driven outreach automation system. Currently configured to book **Sam Jacobs** (Pavilion founder) as a podcast guest. Can be replicated for any outreach campaign in minutes.

---

## What It Does

1. **Discovers** relevant targets (podcasts, brands, etc.) via web search
2. **Scores** each target using Claude (0–100 fit score)
3. **Finds** the right booking contact's email (Hunter.io + web scraping)
4. **Waits for your approval** — you review in Google Sheets and type `Yes` or `No`
5. **Sends** personalized emails from your Gmail inbox (Claude writes a custom hook per email)
6. **Monitors** for replies via Gmail, classifies as positive/negative, updates the Sheet
7. **Sends follow-ups** after 7 days if no response

All tracking lives in a Google Sheet you own. SQLite is the internal source of truth.

---

## Quick Start

### 1. Install dependencies

```bash
cd outreach-agent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Set up credentials

```bash
cp .env.example .env
```

Edit `.env`:
```
ANTHROPIC_API_KEY=sk-ant-...
GMAIL_CREDENTIALS_PATH=auth/client_secrets.json
GMAIL_TOKEN_PATH=auth/gmail_token.json
GOOGLE_SERVICE_ACCOUNT_PATH=auth/service_account.json
HUNTER_API_KEY=             # optional but recommended
```

**Google credentials you need:**

| Credential | How to get it |
|---|---|
| `auth/client_secrets.json` | [Google Cloud Console](https://console.cloud.google.com/) → APIs & Services → Credentials → Create OAuth 2.0 Client ID → Desktop app → Download JSON. Enable Gmail API. |
| `auth/service_account.json` | Google Cloud Console → Service Accounts → Create → Download JSON key. Share your Sheets with the service account email. Enable Sheets API + Drive API. |

> **Tip:** If you only want to use OAuth (no service account), skip `service_account.json`. The system falls back to using your Gmail OAuth credentials for Sheets too.

### 3. Run setup (one time per campaign)

```bash
python scripts/setup_campaign.py --campaign sam_jacobs_podcasts
```

This will:
- Initialize the SQLite database
- Open a browser for Gmail OAuth (sign in as `josh.mait@joinpavilion.com`)
- Create your Google Spreadsheet and share it with your email
- Print the spreadsheet URL

### 4. Discover podcasts

```bash
# Test first (no writes)
python scripts/run_discovery.py --campaign sam_jacobs_podcasts --dry-run

# Real run
python scripts/run_discovery.py --campaign sam_jacobs_podcasts
```

Open your Google Sheet. You'll see rows highlighted yellow with Status = "Pending Approval".

### 5. Approve podcasts

In the Google Sheet, find column **J (Approved)**:
- Type **`Yes`** for podcasts you want to pitch
- Type **`No`** to reject and never contact
- Leave blank to decide later

### 6. Preview emails (dry run)

```bash
python scripts/run_outreach.py --campaign sam_jacobs_podcasts --dry-run
```

This syncs your approvals and prints email previews. **No emails are sent.**

### 7. Send emails

```bash
python scripts/run_outreach.py --campaign sam_jacobs_podcasts
```

Sends up to 25 emails/day from `josh.mait@joinpavilion.com`. Sheet updates to show "Email Sent" (blue).

### 8. Daily operations (run on a schedule)

```bash
python scripts/run_pipeline.py --campaign sam_jacobs_podcasts --skip-discovery
```

This runs contacts → approval sync → outreach → monitor → followup in one command.

---

## CLI Reference

| Script | What it does |
|---|---|
| `setup_campaign.py --campaign X` | One-time setup: DB, Sheets, Gmail OAuth |
| `run_discovery.py --campaign X` | Find and score new targets |
| `run_contacts.py --campaign X` | Find booking contact emails |
| `run_outreach.py --campaign X` | Send initial emails (after approval) |
| `run_monitor.py --campaign X` | Check replies and update statuses |
| `run_followup.py --campaign X` | Send follow-ups to non-responders |
| `run_pipeline.py --campaign X` | Run all phases (cron-friendly) |

All scripts support `--dry-run` (no writes, prints previews) and `--limit N`.

---

## Google Sheet Guide

| Column | Meaning | Who edits |
|---|---|---|
| A–E | Podcast info | Auto |
| F–H | Contact info | Auto |
| I | Qualification score (0–100) | Auto |
| **J** | **Approved** (Yes / No) | **You** |
| K | Status | Auto |
| L–N | Dates | Auto |
| O | Follow-up count | Auto |
| P | Notes | You or auto |
| Q | Email subject sent | Auto |
| R | Last reply snippet | Auto |

**Status color legend:**
- 🟡 Yellow = Pending Approval
- 🔵 Light blue = Approved / Email Sent
- 🔵 Medium blue = Follow-up Sent
- 🟢 Green = Positive Response / Booked
- 🔴 Red = Negative Response / Rejected

---

## Creating a New Campaign

**Example: GTM2026 fashion brand outreach**

```bash
# 1. Copy an existing campaign config
cp campaigns/sam_jacobs_podcasts.yaml campaigns/my_new_campaign.yaml

# 2. Edit it — change: campaign.id, discovery.search_queries,
#    qualification.guest_profile, outreach.sender_name, tracking.spreadsheet_name

# 3. Create email templates
mkdir templates/my_new_campaign/
# Create: templates/my_new_campaign/initial_outreach.j2
#         templates/my_new_campaign/follow_up.j2

# 4. Set up
python scripts/setup_campaign.py --campaign my_new_campaign

# 5. Run
python scripts/run_discovery.py --campaign my_new_campaign
```

Each campaign gets its own:
- Google Spreadsheet
- SQLite data partition (all rows tagged by campaign_id)
- Email templates
- Configuration

---

## Architecture

```
outreach-agent/
├── campaigns/           # YAML config files (one per campaign)
├── templates/           # Jinja2 email templates (one dir per campaign)
├── src/
│   ├── config.py        # YAML loader
│   ├── models.py        # Data classes (Prospect, Reply, EmailLog)
│   ├── discovery/       # Web search + scraping + Claude scoring
│   ├── contacts/        # Hunter.io + web search contact finding
│   ├── outreach/        # Gmail sender + Jinja2+Claude email composer
│   ├── tracking/        # SQLite database + Google Sheets
│   ├── monitoring/      # Gmail reply detection + Claude classification
│   └── workflow/        # Approval sync, follow-ups, pipeline orchestrator
├── scripts/             # CLI entry points
├── auth/                # OAuth tokens (gitignored)
├── data/outreach.db     # SQLite (auto-created, gitignored)
└── .env                 # API keys (gitignored)
```

---

## APIs & Services

| Service | Required? | Used for |
|---|---|---|
| **Anthropic Claude** | Yes | Podcast scoring, email personalization, reply classification |
| **Gmail API (OAuth)** | Yes | Send outreach emails, detect replies |
| **Google Sheets API** | Yes | Human-facing tracking dashboard |
| **Hunter.io** | Recommended (~$49/mo) | Finding booking contact emails |
| **SerpAPI** | Optional (~$50/mo) | Better search results (fallback: DuckDuckGo) |

---

## Cron Setup (optional)

To run daily automatically:

```bash
# Edit crontab
crontab -e

# Run pipeline at 9am every weekday, skipping discovery (run that manually)
0 9 * * 1-5 cd /path/to/outreach-agent && .venv/bin/python scripts/run_pipeline.py --campaign sam_jacobs_podcasts --skip-discovery >> logs/daily.log 2>&1

# Run discovery every Monday
0 8 * * 1 cd /path/to/outreach-agent && .venv/bin/python scripts/run_discovery.py --campaign sam_jacobs_podcasts >> logs/discovery.log 2>&1
```

---

## Notes

- **Rate limits**: Default 25 emails/day with 90-second gaps between sends, to keep your Gmail account healthy
- **Approval gate**: Zero emails are ever sent without `Yes` in column J. This is a hard constraint.
- **Google Sheets is the view, SQLite is the truth**: If they ever diverge, re-running any script will resync the Sheet from DB state
- **Hunter.io**: Sign up at https://hunter.io — Starter plan ($49/mo) covers ~500 searches/month, which is plenty for 100 prospects
