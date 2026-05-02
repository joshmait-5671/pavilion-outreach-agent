"""Slack DM approval flow for podcast outreach prospects.

Pattern (mirrors Recapper):
  1. After discovery scores a prospect, send a DM to Josh with prospect details.
  2. Message ends with: "👍 approve · ✋ kill · 💬 reply with notes."
  3. Outreach script polls for reactions on each message_ts before sending.
  4. 👍 → status set to APPROVED, send queued
  5. ✋ → status set to KILLED, dropped
  6. Thread reply text (if any) → appended to prospect.notes for personalization

Uses the Recapper Slack bot (workspace: Pavilion Executive).
Env vars required:
  SLACK_BOT_TOKEN  — xoxb-... from Recapper app
  SLACK_JOSH_USER_ID — UF4HKP3A6 (or override)
"""
import logging
import os
from typing import Optional

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

log = logging.getLogger(__name__)

SLACK_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
JOSH_USER_ID = os.environ.get("SLACK_JOSH_USER_ID", "UF4HKP3A6")

APPROVE_EMOJI = "+1"          # 👍
KILL_EMOJI = "x"              # ✋  (using "x" — works as ❌; can swap to "raised_hand" / "no_entry")
NOTE_TRIGGER_LABEL = "💬 reply in thread"


def _client() -> Optional[WebClient]:
    if not SLACK_TOKEN:
        log.warning("SLACK_BOT_TOKEN not set — Slack approvals disabled")
        return None
    return WebClient(token=SLACK_TOKEN)


def _open_dm(client: WebClient, user_id: str) -> Optional[str]:
    """Open a DM channel with a user. Returns channel_id."""
    try:
        resp = client.conversations_open(users=user_id)
        return resp["channel"]["id"]
    except SlackApiError as e:
        log.error(f"Failed to open DM with {user_id}: {e.response['error']}")
        return None


def send_prospect_for_approval(prospect: dict) -> Optional[str]:
    """
    DM Josh with the prospect. Returns the message_ts (used later to poll reactions).

    prospect dict expects:
      podcast_name, podcast_url, host_name, audience (optional),
      score (0-100), why_fit (1-line rationale), recent_episode (optional title)
    """
    client = _client()
    if not client:
        return None

    channel_id = _open_dm(client, JOSH_USER_ID)
    if not channel_id:
        return None

    # Build the message — voice: "Playboy with the Economist at the Waverly Inn"
    podcast_name = prospect.get("podcast_name", "Unknown podcast")
    podcast_url = prospect.get("podcast_url", "")
    host = prospect.get("host_name", "—")
    audience = prospect.get("audience", "")
    score = prospect.get("score", "?")
    why = prospect.get("why_fit", "—")
    recent_ep = prospect.get("recent_episode", "")

    audience_line = f"  ·  {audience}" if audience else ""

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"🎙️  *<{podcast_url}|{podcast_name}>*\n"
                    f"_Host:_  *{host}*{audience_line}  ·  _Fit score:_  *{score}/100*"
                ),
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Why it might fit*\n{why}",
            },
        },
    ]

    if recent_ep:
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": f"_Recent ep:_  {recent_ep}",
            }],
        })

    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": (
                "👍 approve  ·  ✋ kill  ·  💬 reply in thread to add a note "
                "(e.g. _'lean into the kindness angle'_)"
            ),
        }],
    })

    try:
        resp = client.chat_postMessage(
            channel=channel_id,
            blocks=blocks,
            text=f"🎙️ {podcast_name} — react to approve or kill",
            unfurl_links=False,
            unfurl_media=False,
        )
        message_ts = resp["ts"]
        log.info(f"Sent approval DM for {podcast_name}, ts={message_ts}")
        return message_ts
    except SlackApiError as e:
        log.error(f"Failed to post approval message: {e.response['error']}")
        return None


def check_approval_status(message_ts: str) -> dict:
    """
    Poll a previously-sent message for reactions + thread replies.

    Returns:
      {
        "status": "pending" | "approved" | "killed",
        "notes": str   (concatenated thread replies from Josh)
      }
    """
    client = _client()
    if not client:
        return {"status": "pending", "notes": ""}

    channel_id = _open_dm(client, JOSH_USER_ID)
    if not channel_id:
        return {"status": "pending", "notes": ""}

    # Get reactions on the message
    try:
        resp = client.reactions_get(channel=channel_id, timestamp=message_ts)
        message = resp.get("message", {})
        reactions = message.get("reactions", [])
    except SlackApiError as e:
        log.error(f"reactions_get failed: {e.response['error']}")
        return {"status": "pending", "notes": ""}

    status = "pending"
    for r in reactions:
        if r["name"] == APPROVE_EMOJI and JOSH_USER_ID in r.get("users", []):
            status = "approved"
            break
        if r["name"] in (KILL_EMOJI, "no_entry", "raised_hand", "thumbsdown") and JOSH_USER_ID in r.get("users", []):
            status = "killed"
            break

    # Pull thread replies for notes
    notes = ""
    try:
        thread_resp = client.conversations_replies(channel=channel_id, ts=message_ts)
        replies = thread_resp.get("messages", [])
        # Skip the parent message (index 0); collect Josh's replies
        josh_replies = [
            m.get("text", "").strip()
            for m in replies[1:]
            if m.get("user") == JOSH_USER_ID and m.get("text", "").strip()
        ]
        notes = " | ".join(josh_replies)
    except SlackApiError as e:
        log.warning(f"conversations_replies failed (non-fatal): {e.response['error']}")

    return {"status": status, "notes": notes}


def post_send_confirmation(prospect: dict, sent_to: str, message_ts: Optional[str] = None) -> None:
    """After an email is sent, drop a confirmation in the same DM thread."""
    client = _client()
    if not client:
        return
    channel_id = _open_dm(client, JOSH_USER_ID)
    if not channel_id:
        return
    text = f"📨 Sent to *{sent_to}* for *{prospect.get('podcast_name')}*"
    try:
        if message_ts:
            client.chat_postMessage(channel=channel_id, thread_ts=message_ts, text=text)
        else:
            client.chat_postMessage(channel=channel_id, text=text)
    except SlackApiError as e:
        log.warning(f"Send confirmation failed: {e.response['error']}")


def post_reply_received(prospect: dict, classification: str, snippet: str, message_ts: Optional[str] = None) -> None:
    """When someone replies to outreach, ping Josh."""
    client = _client()
    if not client:
        return
    channel_id = _open_dm(client, JOSH_USER_ID)
    if not channel_id:
        return
    emoji = {"positive": "🟢", "negative": "🔴", "neutral": "🟡"}.get(classification, "📬")
    text = (
        f"{emoji} Reply from *{prospect.get('podcast_name')}* "
        f"({classification})\n>{snippet[:280]}"
    )
    try:
        if message_ts:
            client.chat_postMessage(channel=channel_id, thread_ts=message_ts, text=text)
        else:
            client.chat_postMessage(channel=channel_id, text=text)
    except SlackApiError as e:
        log.warning(f"Reply notification failed: {e.response['error']}")


def post_manual_send_payload(
    prospect: dict,
    subject: str,
    body: str,
    message_ts: Optional[str] = None,
) -> None:
    """For marquee podcasts whose contact email the agent can't find — DM Josh
    a copy-paste-ready email payload so he can send it himself from his own inbox."""
    client = _client()
    if not client:
        return
    channel_id = _open_dm(client, JOSH_USER_ID)
    if not channel_id:
        return

    podcast_name = prospect.get("podcast_name", "Unknown podcast")
    podcast_url = prospect.get("podcast_url", "")
    host = prospect.get("host_name", "—")

    header_text = (
        f"✋ *Manual send needed — {podcast_name}*\n"
        f"_Host:_ *{host}*  ·  Agent couldn't find a booking email. "
        f"Find one yourself, then send the below from your own inbox."
    )
    if podcast_url:
        header_text = f"✋ *Manual send needed — <{podcast_url}|{podcast_name}>*\n" + header_text.split("\n", 1)[1]

    payload_text = f"*Subject:* {subject}\n\n```\n{body}\n```"

    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": header_text}},
        {"type": "section", "text": {"type": "mrkdwn", "text": payload_text}},
        {"type": "context", "elements": [{
            "type": "mrkdwn",
            "text": (
                "Marked _Manual Outreach Queued_ in DB — won't re-DM tomorrow. "
                "Follow-ups for this prospect are also manual."
            ),
        }]},
    ]

    try:
        kwargs = {"channel": channel_id, "blocks": blocks,
                  "text": f"✋ Manual send needed for {podcast_name}",
                  "unfurl_links": False, "unfurl_media": False}
        if message_ts:
            kwargs["thread_ts"] = message_ts
        client.chat_postMessage(**kwargs)
    except SlackApiError as e:
        log.warning(f"Manual send payload failed: {e.response['error']}")


def daily_digest(stats: dict) -> None:
    """End-of-day summary DM."""
    client = _client()
    if not client:
        return
    channel_id = _open_dm(client, JOSH_USER_ID)
    if not channel_id:
        return
    text = (
        f"*Outreach digest — {stats.get('date')}*\n"
        f"Sent today: *{stats.get('sent', 0)}*  ·  "
        f"Replies in: *{stats.get('replies', 0)}*  "
        f"(🟢 {stats.get('positive', 0)} · 🟡 {stats.get('neutral', 0)} · 🔴 {stats.get('negative', 0)})\n"
        f"Pending approval: *{stats.get('pending', 0)}*  ·  "
        f"In queue: *{stats.get('queued', 0)}*  ·  "
        f"Follow-ups firing tomorrow: *{stats.get('followups_tomorrow', 0)}*"
    )
    try:
        client.chat_postMessage(channel=channel_id, text=text)
    except SlackApiError as e:
        log.warning(f"Daily digest failed: {e.response['error']}")
