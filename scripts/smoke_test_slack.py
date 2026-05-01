"""Smoke test the Slack approval flow with one fake prospect."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if not os.environ.get("SLACK_BOT_TOKEN") or not os.environ.get("SLACK_JOSH_USER_ID"):
    sys.exit("SLACK_BOT_TOKEN and SLACK_JOSH_USER_ID must be set in env (.env or shell)")

from src.outreach.slack_approval import send_prospect_for_approval

prospect = {
    "podcast_name": "The Knowledge Project",
    "podcast_url": "https://fs.blog/knowledge-project-podcast/",
    "host_name": "Shane Parrish",
    "audience": "~500K listeners · heavy reader crowd",
    "score": 88,
    "why_fit": (
        "The kindness-as-strategy thesis from Sam's book is exactly Shane's lane. "
        "He's done deep eps on moral philosophy, decision-making, and reputational capital. "
        "The AI Pulse Report data on people being optimistic and anxious at the same time "
        "is also a perfect fit — Shane covers that human-systems tension constantly."
    ),
    "recent_episode": "#212 — Ben Horowitz on Hard Things About Hard Things (3 weeks ago)",
}

ts = send_prospect_for_approval(prospect)
print(f"Sent to Josh. message_ts = {ts}")
