"""
Railway Runner — Outreach Agent
--------------------------------
Writes Gmail token from env var, then runs the daily pipeline on a schedule.
- 9am ET: send emails + follow-ups + monitor replies
- Every 4 hours: monitor replies
"""

import os
import sys
import json
import logging
from datetime import datetime
import pytz
from apscheduler.schedulers.blocking import BlockingScheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

# ── Write Gmail token from env var ────────────────────────────────────────────
def write_token_from_env():
    import base64
    token_b64 = os.environ.get("GMAIL_TOKEN_B64")
    if token_b64:
        token_path = os.environ.get("GMAIL_TOKEN_PATH", "auth/gmail_token.json")
        os.makedirs(os.path.dirname(token_path), exist_ok=True)
        with open(token_path, "wb") as f:
            f.write(base64.b64decode(token_b64))
        log.info(f"Wrote Gmail token (pickle) to {token_path}")
    else:
        log.warning("GMAIL_TOKEN_B64 not set — using existing file if present")

# ── Run pipeline ──────────────────────────────────────────────────────────────
def run_daily_pipeline():
    et = pytz.timezone("America/New_York")
    now = datetime.now(et)
    if now.weekday() >= 5:
        log.info("Weekend — skipping pipeline.")
        return
    log.info("Running daily outreach pipeline...")
    os.system("python scripts/run_pipeline.py --campaign sam_jacobs_podcasts --skip-discovery")

def run_monitor():
    log.info("Running reply monitor...")
    os.system("python scripts/run_monitor.py --campaign sam_jacobs_podcasts")

# ── Scheduler ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    write_token_from_env()

    scheduler = BlockingScheduler(timezone="America/New_York")

    # Daily pipeline: 9am ET Mon-Fri
    scheduler.add_job(run_daily_pipeline, "cron", day_of_week="mon-fri", hour=9, minute=0)

    # Monitor replies every 4 hours
    scheduler.add_job(run_monitor, "interval", hours=4)

    log.info("Outreach Agent scheduler started.")
    log.info("  - Daily pipeline: 9am ET Mon-Fri")
    log.info("  - Reply monitor: every 4 hours")
    scheduler.start()
