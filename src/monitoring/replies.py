"""Detect and classify incoming replies via Gmail."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from src.models import Prospect, Reply


def check_for_replies(
    service,
    campaign_prospects: list[Prospect],
    known_message_ids: set[str],
    classification_model: str = "claude-opus-4-6",
    sender_email: str = "",
    client: Optional[anthropic.Anthropic] = None,
) -> list[Reply]:
    """Check Gmail threads for new replies. Returns list of Reply objects (not yet saved to DB)."""
    if client is None:
        client = anthropic.Anthropic()

    from src.outreach.sender import get_thread_messages, mark_as_read

    new_replies: list[Reply] = []

    for prospect in campaign_prospects:
        if not prospect.initial_email_thread_id:
            continue

        messages = get_thread_messages(service, prospect.initial_email_thread_id)
        if not messages:
            continue

        for msg in messages:
            msg_id = msg.get("message_id", "")
            if not msg_id or msg_id in known_message_ids:
                continue

            # Skip messages sent by us
            from_addr = msg.get("from", "").lower()
            if sender_email and sender_email.lower() in from_addr:
                continue
            # Also skip if it's in SENT label
            labels = msg.get("label_ids", [])
            if "SENT" in labels:
                continue

            # Classify this reply
            body = msg.get("full_body", "") or msg.get("snippet", "")
            classification, confidence, notes = classify_reply(
                reply_body=body,
                podcast_name=prospect.podcast_name,
                model=classification_model,
                client=client,
            )

            reply = Reply(
                prospect_id=prospect.id,
                campaign_id=prospect.campaign_id,
                gmail_message_id=msg_id,
                gmail_thread_id=msg.get("thread_id", ""),
                from_address=msg.get("from", ""),
                subject=msg.get("subject", ""),
                body_snippet=body[:300],
                full_body=body,
                classification=classification,
                classification_confidence=confidence,
                classification_notes=notes,
                received_at=msg.get("received_at") or datetime.utcnow(),
            )
            new_replies.append(reply)

            # Mark as read
            try:
                mark_as_read(service, msg_id)
            except Exception:
                pass

    return new_replies


def classify_reply(
    reply_body: str,
    podcast_name: str,
    model: str = "claude-opus-4-6",
    client: Optional[anthropic.Anthropic] = None,
) -> tuple[str, float, str]:
    """Classify a reply as 'positive', 'negative', or 'neutral'.
    Returns (classification, confidence_0_to_1, reasoning)."""
    if client is None:
        client = anthropic.Anthropic()

    # Fast-path keyword classification before calling Claude
    body_lower = reply_body.lower()
    fast = _fast_classify(body_lower)
    if fast:
        return fast, 0.95, "Fast-path keyword classification"

    prompt = _build_classification_prompt(reply_body, podcast_name)
    try:
        response_text = _call_claude(client, model, prompt)
        data = _extract_json(response_text)
        classification = data.get("classification", "neutral").lower()
        if classification not in ("positive", "negative", "neutral"):
            classification = "neutral"
        confidence = float(data.get("confidence", 0.7))
        notes = data.get("reasoning", "")
        return classification, confidence, notes
    except Exception:
        return "neutral", 0.5, "Classification failed"


def _fast_classify(body_lower: str) -> Optional[str]:
    POSITIVE_SIGNALS = [
        "sounds great", "love to", "would love", "interested",
        "let's do it", "let's connect", "set up a call", "send more info",
        "tell me more", "yes!", "yes,", "absolutely", "definitely interested",
        "would be happy", "great idea", "love this", "sounds fun",
    ]
    NEGATIVE_SIGNALS = [
        "not a fit", "not interested", "not accepting", "full calendar",
        "no longer accept", "don't accept unsolicited", "please remove",
        "unsubscribe", "stop emailing", "not taking guests",
        "not doing interviews", "already have guests lined up",
        "out of office",  # neutral-ish but not actionable
    ]
    OOO_SIGNALS = ["out of office", "on vacation", "will return", "auto-reply"]

    for sig in OOO_SIGNALS:
        if sig in body_lower:
            return "neutral"
    for sig in POSITIVE_SIGNALS:
        if sig in body_lower:
            return "positive"
    for sig in NEGATIVE_SIGNALS:
        if sig in body_lower:
            return "negative"
    return None


def _build_classification_prompt(reply_body: str, podcast_name: str) -> str:
    return f"""Classify this email reply to a podcast guest booking pitch.

The email was pitched to: {podcast_name}
The pitch was to book a guest (Sam Jacobs, founder of Pavilion) on the podcast.

REPLY TEXT:
---
{reply_body[:1500]}
---

Classify as:
- "positive": They are interested, want more info, or are open to booking (includes unclear but encouraging responses)
- "negative": They declined, are not interested, or asked to be removed
- "neutral": Out of office, auto-reply, or too ambiguous to act on

Respond with ONLY valid JSON:
{{
  "classification": "positive" | "negative" | "neutral",
  "confidence": <float 0.0-1.0>,
  "reasoning": "<one sentence>"
}}"""


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _call_claude(client: anthropic.Anthropic, model: str, prompt: str) -> str:
    msg = client.messages.create(
        model=model,
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def _extract_json(text: str) -> dict:
    import json
    text = re.sub(r"```(?:json)?\n?", "", text).strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        return json.loads(m.group(0))
    return json.loads(text)
