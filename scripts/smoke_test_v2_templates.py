"""Render the v2 templates with a fake prospect — verify they look right."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from src.config import load_campaign
from src.models import Prospect
from src.outreach import composer

# Fake prospect (mimics one The Knowledge Project would generate)
prospect = Prospect(
    campaign_id="sam_jacobs_podcasts",
    podcast_name="The Knowledge Project",
    podcast_url="https://fs.blog/knowledge-project-podcast/",
    host_name="Shane Parrish",
    booking_contact_name="Shane Parrish",
    booking_contact_email="shane@example.com",
    category="Personal Development",
    qualification_score=88,
    description="Mental models, decision-making, philosophy.",
    initial_email_sent_at=datetime(2026, 4, 22),  # for follow-up rendering
    follow_up_count=0,
    slack_notes="Lean hard into the kindness-as-strategy angle. Shane's audience eats this.",
)

config = load_campaign("sam_jacobs_podcasts", campaigns_dir="campaigns")
# Set composition_model from env
config_attrs = ["composition_model", "qualification_model", "personalization_model"]

# Disable Anthropic call (no key during smoke test) — let _generate_personalization fail silently
import os as _os
_os.environ.pop("ANTHROPIC_API_KEY", None)

print("=" * 70)
print("TOUCH 1 — initial_outreach.j2")
print("=" * 70)
subject, body = composer.compose_email(prospect, "initial_outreach.j2", config, client=None)
print(f"Subject: {subject}\n")
print(body)

print("\n" + "=" * 70)
print("TOUCH 2 — follow_up.j2 (count=0 → first FU)")
print("=" * 70)
prospect.follow_up_count = 0
subject, body = composer.compose_email(prospect, "follow_up.j2", config, client=None)
print(f"Subject: {subject}\n")
print(body)

print("\n" + "=" * 70)
print("TOUCH 3 — follow_up_2.j2 (count=1 → second FU)")
print("=" * 70)
prospect.follow_up_count = 1
subject, body = composer.compose_email(prospect, "follow_up_2.j2", config, client=None)
print(f"Subject: {subject}\n")
print(body)
