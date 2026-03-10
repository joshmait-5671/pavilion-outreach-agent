"""Compose personalized outreach emails using Jinja2 + Claude."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import anthropic
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import CampaignConfig
from src.models import Prospect


def compose_email(
    prospect: Prospect,
    template_name: str,
    config: CampaignConfig,
    client: Optional[anthropic.Anthropic] = None,
    extra_vars: Optional[dict] = None,
) -> tuple[str, str]:
    """Compose an email for a prospect. Returns (subject, body)."""
    if client is None:
        client = anthropic.Anthropic()

    # Build personalization variables
    personalization = {}
    if config.personalization_enabled:
        personalization = _generate_personalization(prospect, config, client)

    # Build template context
    contact_name = prospect.booking_contact_name or prospect.host_name or ""
    context = {
        "podcast_name": prospect.podcast_name,
        "host_name": prospect.host_name or "",
        "contact_name": contact_name,
        "category": prospect.category or "",
        "sender_name": config.sender_name,
        "sender_title": config.sender_title,
        "guest_name": config.guest_name,
        "guest_title": config.guest_title,
        "recent_episode_reference": personalization.get("recent_episode_reference", ""),
        "value_proposition_hook": personalization.get("value_proposition_hook", ""),
        "follow_up_topic_hook": personalization.get("follow_up_topic_hook", ""),
        "initial_sent_date": _fmt_date(prospect.initial_email_sent_at),
    }
    if extra_vars:
        context.update(extra_vars)

    # Render Jinja2 template
    env = Environment(
        loader=FileSystemLoader(config.template_dir),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    # Make undefined variables render as empty string instead of raising
    env.undefined = _SilentUndefined

    template = env.get_template(template_name)
    rendered = template.render(**context)

    # Split subject from body (first line is subject)
    lines = rendered.strip().split("\n")
    subject_line = ""
    body_lines = lines

    for i, line in enumerate(lines):
        if line.lower().startswith("subject:"):
            subject_line = line.split(":", 1)[1].strip()
            body_lines = lines[i + 1:]
            # Skip blank line after subject
            while body_lines and not body_lines[0].strip():
                body_lines = body_lines[1:]
            break

    subject = subject_line or f"Guest pitch: {config.guest_name} for {prospect.podcast_name}"
    body = "\n".join(body_lines).strip()

    return subject, body


def _generate_personalization(
    prospect: Prospect,
    config: CampaignConfig,
    client: anthropic.Anthropic,
) -> dict:
    """Call Claude to generate personalization fields for this prospect."""
    prompt = _build_personalization_prompt(prospect, config)
    try:
        response_text = _call_claude(client, config.composition_model, prompt)
        data = _extract_json(response_text)
        return {
            "recent_episode_reference": data.get("recent_episode_reference", ""),
            "value_proposition_hook": data.get("value_proposition_hook", ""),
            "follow_up_topic_hook": data.get("follow_up_topic_hook", ""),
        }
    except Exception:
        return {}


def _build_personalization_prompt(prospect: Prospect, config: CampaignConfig) -> str:
    episodes_text = ""
    if prospect.raw_scrape_data:
        try:
            scrape = json.loads(prospect.raw_scrape_data)
            episodes = scrape.get("recent_episodes", [])
            if episodes:
                titles = [e.get("title", "") for e in episodes[:5] if e.get("title")]
                episodes_text = "Recent episodes:\n" + "\n".join(f"- {t}" for t in titles)
        except (json.JSONDecodeError, TypeError):
            pass

    return f"""You are a PR and podcast booking specialist crafting a personalized outreach email.

GUEST BEING PITCHED:
- Name: {config.guest_name}
- Title: {config.guest_title}
- Book: "Kind Folks Finish First" (WSJ Bestseller) — argues kindness and reciprocity are competitive advantages
- Company: Pavilion — professional community for GTM/sales leaders with 10,000+ members, ~$200M valuation
- Background: 15+ years as CRO/VP Sales at B2B SaaS companies; built Pavilion from scratch
- Co-host: Topline Podcast (#1 B2B tech podcast for founders/operators)
- LinkedIn: 103K+ followers; thought leader on sales, GTM, community building, leadership

PODCAST BEING PITCHED:
- Name: {prospect.podcast_name}
- Category: {prospect.category or 'Business'}
- Description: {prospect.description or ''}
- Host: {prospect.host_name or 'Unknown'}
{episodes_text}

SENDER (writing the email):
- Name: {config.sender_name}
- Title: {config.sender_title}

Generate THREE personalization fields for this specific podcast. Be genuine and specific — not generic.

Respond with ONLY valid JSON:
{{
  "value_proposition_hook": "<1-2 sentences that open the email by connecting {config.guest_name}'s unique story to THIS podcast's specific audience — reference the podcast's topic/focus. Do not be sycophantic. Be direct and specific.>",
  "recent_episode_reference": "<If there are recent episodes listed above, reference ONE specific episode by name and explain in 1 sentence why it makes this pitch a natural fit. If no episodes are known, write an empty string.>",
  "follow_up_topic_hook": "<A 5-10 word phrase completing: 'I think your audience would connect with his perspective on...' — make it specific to this podcast's category>"
}}"""


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _call_claude(client: anthropic.Anthropic, model: str, prompt: str) -> str:
    msg = client.messages.create(
        model=model,
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def _extract_json(text: str) -> dict:
    text = re.sub(r"```(?:json)?\n?", "", text).strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        return json.loads(m.group(0))
    return json.loads(text)


def _fmt_date(dt: Optional[datetime]) -> str:
    if dt is None:
        return "recently"
    return dt.strftime("%B %d")


class _SilentUndefined:
    """Jinja2 undefined class that renders as empty string."""
    def __init__(self, *args, **kwargs):
        pass
    def __str__(self):
        return ""
    def __call__(self, *args, **kwargs):
        return ""
    def __getattr__(self, name):
        return self.__class__()
