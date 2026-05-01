# Outreach Agent — v2 Rebuild Notes (2026-04-29)

## What changed

### Voice
**Old:** corporate cold pitch — "I'm writing to pitch Sam Jacobs as a guest."
**New:** "Playboy with the Economist at the Waverly Inn." Confident, dry, peer-to-peer. Brief is the message. Touch 1 leads with the AI Pulse Report; the pitch is a postscript.

### Cadence
**Old:** initial + 1 follow-up @ 7 days. Two touches.
**New:** initial + 2 follow-ups @ 7 + 14 days. Three touches.
- **Touch 1** — `initial_outreach.j2` — leads with the AI Pulse Report, 4 stat bullets, mentions Sam as a soft offer, closes with "no pressure."
- **Touch 2** — `follow_up.j2` — tied to one of their recent episodes, with a specific data point from the report that maps to it.
- **Touch 3** — `follow_up_2.j2` — soft close + calendar link.

### Approval
**Old:** Google Sheet column J ("Yes" / "No"). You approve in a spreadsheet you don't open.
**New:** Slack DM from the Recapper bot for every new prospect. React 👍 to approve, ✋ to kill, thread-reply with notes (which get baked into the personalization prompt). Sheet column J is kept as fallback.

### Reporting
Slack-side: confirmation pings when emails go out, reply notifications with classification (🟢/🟡/🔴), and a daily digest. All implemented in `src/outreach/slack_approval.py`. Wire into the daily pipeline next.

### AI Pulse Report
Now hosted at https://pavilion-ai-pulse.netlify.app — clean URL, three stat cards, takeaways, PDF download. Used as the lead asset in Touch 1.

---

## REQUIRED before this is fully live

### 1. Add Slack scopes (2 min, Josh)

The Recapper bot in Pavilion Executive workspace currently has:
`chat:write, im:write, im:read, channels:history, channels:read, users:read, files:read, channels:join, users:read.email, channels:manage`

It's missing the two scopes the approval-polling needs:
- `reactions:read` — to read 👍/✋ on the DM
- `im:history` — to read thread replies for notes

**To fix:**
1. Go to https://api.slack.com/apps
2. Open the Recapper app
3. Left nav → **OAuth & Permissions**
4. Scroll to **Bot Token Scopes** → click **Add an OAuth Scope**
5. Add `reactions:read` and `im:history`
6. Top of page → **Reinstall to Workspace** → approve
7. The token doesn't change. No code change needed.

Once those scopes are added, `sync_approvals_from_slack` lights up — your 👍 reactions will flip prospects to Approved automatically.

### 2. Set local env vars

Add to `.env` (real values live in 1Password / Recapper app dashboard, not in this repo):
```
SLACK_BOT_TOKEN=xoxb-...                # Recapper bot token (api.slack.com/apps → OAuth & Permissions)
SLACK_JOSH_USER_ID=U...                 # Josh's Slack user ID (Pavilion Executive workspace)
```

### 3. Set Railway env vars

Same two vars on the Railway project running the daily pipeline.

### 4. (Optional) Sanity-check the new templates

```bash
cd /Users/joshmait/Desktop/Claude/pavilion/outreach-agent
source .venv/bin/activate
python3 scripts/smoke_test_v2_templates.py
```

Renders all three touches with a fake prospect. Voice should sound right.

### 5. Smoke test the Slack DM

```bash
python3 scripts/smoke_test_slack.py
```

Should DM you a fake prospect from the Recapper bot.

---

## Files touched

| File | What changed |
|---|---|
| `templates/sam_jacobs_podcasts/initial_outreach.j2` | Rewrote in Waverly voice. Leads with AI Pulse. v1 backed up to `.v1.bak`. |
| `templates/sam_jacobs_podcasts/follow_up.j2` | Rewrote as Touch 2 — tied to their episode + one data point. |
| `templates/sam_jacobs_podcasts/follow_up_2.j2` | NEW — Touch 3, soft close + calendar. |
| `campaigns/sam_jacobs_podcasts.yaml` | `max_follow_ups: 1 → 2`; added `follow_up_2_template`, `ai_pulse_report_url`, `calendar_link`. |
| `src/config.py` | Properties for `follow_up_2_template`, `ai_pulse_report_url`, `calendar_link`. |
| `src/models.py` | `Prospect` adds `follow_up_2_*`, `slack_message_ts`, `slack_notes`. |
| `src/tracking/database.py` | Schema adds 4 new columns; idempotent `_migrate_add_columns()` runs on init. |
| `src/tracking/database.py` | `get_prospects_due_for_followup` rewritten to handle both FU stages. |
| `src/outreach/composer.py` | Context exposes `slack_notes`, `ai_pulse_report_url`, `calendar_link`, `recent_episode_topic`, `specific_data_hook`. Personalization prompt rewritten with voice guide and new fields. |
| `src/outreach/slack_approval.py` | NEW — full module: send_prospect_for_approval, check_approval_status, post_send_confirmation, post_reply_received, daily_digest. |
| `src/workflow/approval.py` | Added `sync_approvals_from_slack()`. |
| `src/workflow/orchestrator.py` | Discovery now DMs Josh per prospect. Outreach phase syncs Slack approvals before Sheet. |
| `src/workflow/followup.py` | Picks template based on `follow_up_count` (Touch 2 vs Touch 3). Tracks `follow_up_2_*` columns. |
| `scripts/smoke_test_slack.py` | NEW — fake prospect Slack DM smoke test. |
| `scripts/smoke_test_v2_templates.py` | NEW — render all 3 templates with a fake prospect. |
| `.env.example` | Added Slack vars. |

## Backups

The old `initial_outreach.j2` and `follow_up.j2` are saved as `.v1.bak` in the same directory. Roll back with:
```bash
cp templates/sam_jacobs_podcasts/initial_outreach.j2.v1.bak templates/sam_jacobs_podcasts/initial_outreach.j2
cp templates/sam_jacobs_podcasts/follow_up.j2.v1.bak templates/sam_jacobs_podcasts/follow_up.j2
```
